"""
engine.py — Crossplay solver engine.

Contains every piece of pure game logic with no I/O, no HTTP, and no
side-effects.  This module is the right import target for unit tests and
for any alternative front-end (CLI, REST API, GUI, …).

Algorithm
---------
Implements Appel & Jacobsen (1988), "The World's Fastest Scrabble Program":

  1. DAWG — Build a Directed Acyclic Word Graph from the word list so every
     valid prefix can be tested in O(length) time and suffix nodes that are
     structurally identical are merged, minimising memory use.

  2. Cross-check sets — For each empty square precompute which letters may
     be placed there without forming an illegal perpendicular word.  This is
     done separately for horizontal and vertical move generation by reading
     the board through a transparent transpose wrapper.

  3. Anchor-based generation — For each anchor (an empty square adjacent to
     a placed tile), recursively build left-parts and extend right through the
     DAWG, pruned at every step by the cross-check sets.  Invalid placements
     are impossible by construction; no post-hoc filtering is needed.

Public API
----------
  build_dawg(words)                 → Dawg
  load_word_list()                  → tuple[set[str], Dawg]  (raises WordListError)
  load_word_list_from_path(path)    → tuple[set[str], Dawg]
  find_top_moves(board, rack, dawg, *, top_n) → list[Move]

  WordListError                     — raised when no word file is found

  Board                       — mutable 15×15 game state
  Move                        — immutable scored candidate (NamedTuple)
"""

from __future__ import annotations

import os
from collections import Counter
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Board constants
# ---------------------------------------------------------------------------

BOARD_SIZE  = 15
BINGO_BONUS = 40                     # awarded when all 7 rack tiles are played
ALL_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
COL_LABELS  = "ABCDEFGHIJKLMNO"      # A–O for display / logging

# Tile point values for Crossplay (differ from Scrabble).
TILE_VALUES: dict[str, int] = {
    "A": 1,  "B": 3,  "C": 3,  "D": 2,  "E": 1,  "F": 4,  "G": 2,
    "H": 3,  "I": 1,  "J": 8,  "K": 6,  "L": 2,  "M": 3,  "N": 1,
    "O": 1,  "P": 3,  "Q": 10, "R": 1,  "S": 1,  "T": 1,  "U": 1,
    "V": 6,  "W": 5,  "X": 8,  "Y": 4,  "Z": 10, "?": 0,  # ? = blank tile
}

# Bonus square positions (0-indexed row, col).
# Verified against the official Crossplay blank board.
TRIPLE_WORD: frozenset[tuple[int, int]] = frozenset({
    (0, 3),  (0, 11), (3, 0),  (3, 14),
    (11, 0), (11, 14),(14, 3), (14, 11),
})
DOUBLE_WORD: frozenset[tuple[int, int]] = frozenset({
    (1, 1),  (1, 13), (3, 7),  (7, 3),
    (7, 11), (11, 7), (13, 1), (13, 13),
})
TRIPLE_LETTER: frozenset[tuple[int, int]] = frozenset({
    (0, 0),  (0, 14), (1, 6),  (1, 8),  (4, 5),  (4, 9),
    (5, 4),  (5, 10), (6, 1),  (6, 13), (8, 1),  (8, 13),
    (9, 4),  (9, 10), (10, 5), (10, 9), (13, 6), (13, 8),
    (14, 0), (14, 14),
})
DOUBLE_LETTER: frozenset[tuple[int, int]] = frozenset({
    (0, 7),  (2, 4),  (2, 10), (3, 3),  (3, 11), (4, 2),
    (4, 12), (5, 7),  (7, 0),  (7, 5),  (7, 9),  (7, 14),
    (9, 7),  (10, 2), (10, 12),(11, 3), (11, 11),(12, 4),
    (12, 10),(14, 7),
})

# Word-list files tried in order; first existing file wins.
# Collins Scrabble Words (collins.txt / sowpods.txt) is the closest match to
# the Crossplay dictionary and is listed first.  TWL06 is a fallback.
WORD_LIST_SEARCH_PATHS: list[str] = [
    "collins.txt", "sowpods.txt", "Collins.txt", "SOWPODS.txt",
    "TWL06.txt", "twl06.txt", "enable1.txt",
    "/usr/share/dict/words", "/usr/dict/words",
]

# Internal type alias: indexed [row][col] → set of letters allowed by
# cross-word constraints at that square.
_CrossCheckGrid = list[list[set[str]]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def square_multipliers(row: int, col: int) -> tuple[int, int]:
    """Return (letter_multiplier, word_multiplier) for the given board square."""
    pos = (row, col)
    if pos in TRIPLE_WORD:   return (1, 3)
    if pos in DOUBLE_WORD:   return (1, 2)
    if pos in TRIPLE_LETTER: return (3, 1)
    if pos in DOUBLE_LETTER: return (2, 1)
    return (1, 1)


# ---------------------------------------------------------------------------
# DAWG — Directed Acyclic Word Graph
# ---------------------------------------------------------------------------

class DawgNode:
    """
    Single node in the DAWG.

    ``__slots__`` cuts per-node memory by ~40 % vs a plain object; we create
    one node per unique suffix across ~170 k words so this matters.

    The integer ``_id`` supports structural hashing: two nodes are identical
    when they share the same terminal flag and the same set of
    (edge_label, target._id) pairs, which lets the minimisation step detect
    and merge duplicate suffix sub-graphs.
    """

    __slots__ = ("children", "terminal", "_id")
    _next_id: int = 0

    def __init__(self) -> None:
        self.children: dict[str, DawgNode] = {}
        self.terminal: bool = False
        DawgNode._next_id += 1
        self._id = DawgNode._next_id

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, DawgNode)
            and self.terminal == other.terminal
            and self.children == other.children
        )

    def __hash__(self) -> int:
        edge_sig = tuple(sorted(
            (label, node._id) for label, node in self.children.items()
        ))
        return hash((self.terminal, edge_sig))


class Dawg:
    """
    Minimised Directed Acyclic Word Graph built from a *sorted* word list.

    Build pattern
    -------------
    ::

        dawg = Dawg()
        for word in sorted(words):
            dawg.insert(word)
        dawg.finish()           # flush the minimisation buffer

    Or use the convenience function ``build_dawg(word_set)``.

    Query interface
    ---------------
    ``"HELLO" in dawg``          — O(|word|) membership test
    ``dawg.get_node("HEL")``     — node reached after consuming the prefix,
                                    or None if no word starts with that prefix
    """

    def __init__(self) -> None:
        self.root = DawgNode()
        self._minimized: dict[DawgNode, DawgNode] = {}
        # Stack of (parent, edge_label, child) triples not yet minimised.
        # Nodes are minimised as soon as we know the current word's suffix
        # diverges from the previous word.
        self._pending: list[tuple[DawgNode, str, DawgNode]] = []
        self._prev_word: str = ""

    def insert(self, word: str) -> None:
        """
        Insert one word.  Words *must* arrive in ascending lexicographic order.

        Inserting out of order silently produces an incorrect DAWG.
        """
        # Find the length of the shared prefix with the previous word.
        common = 0
        for i in range(min(len(word), len(self._prev_word))):
            if word[i] != self._prev_word[i]:
                break
            common += 1
        else:
            common = min(len(word), len(self._prev_word))

        # Minimise all suffix nodes that diverge from the common prefix.
        self._minimize_pending(down_to=common)

        # Attach the diverging suffix as a chain of new nodes.
        node = self._pending[-1][2] if self._pending else self.root
        for ch in word[common:]:
            child = DawgNode()
            node.children[ch] = child
            self._pending.append((node, ch, child))
            node = child
        node.terminal = True
        self._prev_word = word

    def finish(self) -> None:
        """Flush remaining pending nodes.  Must be called after the last insert()."""
        self._minimize_pending(down_to=0)

    def _minimize_pending(self, down_to: int) -> None:
        """
        Merge structurally identical suffix sub-graphs to minimise node count.

        A node is canonical if we have already seen an identical node and
        registered it.  When a duplicate is found we redirect the parent edge
        to the canonical node and discard the duplicate.
        """
        while len(self._pending) > down_to:
            parent, edge_label, child = self._pending.pop()
            canonical = self._minimized.get(child)
            if canonical is not None:
                parent.children[edge_label] = canonical   # redirect to canonical
            else:
                self._minimized[child] = child            # register as canonical

    def __contains__(self, word: str) -> bool:
        node: DawgNode | None = self.root
        for ch in word:
            node = node.children.get(ch)
            if node is None:
                return False
        return node.terminal  # type: ignore[union-attr]

    def get_node(self, prefix: str) -> DawgNode | None:
        """Return the node reached after consuming *prefix*, or None."""
        node: DawgNode | None = self.root
        for ch in prefix:
            if node is None:
                return None
            node = node.children.get(ch)
        return node


def build_dawg(words: set[str]) -> Dawg:
    """Build and return a minimised DAWG from an *unordered* set of words."""
    dawg = Dawg()
    for word in sorted(words):
        dawg.insert(word)
    dawg.finish()
    return dawg


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------

class Move(NamedTuple):
    """
    An evaluated candidate move.

    Immutable and hashable (NamedTuple) so it can be stored in sets and used
    as dict keys without additional effort.
    """
    score:      int
    word:       str
    row:        int    # 0-indexed start row on the actual (un-transposed) board
    col:        int    # 0-indexed start col
    horizontal: bool

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON responses."""
        return {
            "word": self.word, "row": self.row, "col": self.col,
            "horizontal": self.horizontal, "score": self.score,
        }


class Board:
    """
    Mutable 15×15 Crossplay game board.

    Represented internally as a list-of-lists with '.' for empty squares.
    The ``is_empty`` flag is an optimisation for the opening move: on an
    empty board only the centre square is an anchor.

    Design note
    -----------
    Board is intentionally kept simple and mutable.  The solver never mutates
    a board it was given — it reads it and writes candidates to a separate
    results list.
    """

    EMPTY = "."

    def __init__(self) -> None:
        self._grid: list[list[str]] = [
            [self.EMPTY] * BOARD_SIZE for _ in range(BOARD_SIZE)
        ]
        self.is_empty = True

    # ── Mutation ───────────────────────────────────────────────────────────

    def place(self, row: int, col: int, letter: str) -> None:
        """Place a letter tile at (row, col).  Letter is uppercased automatically."""
        self._grid[row][col] = letter.upper()
        self.is_empty = False

    # ── Read helpers ───────────────────────────────────────────────────────

    def get(self, row: int, col: int) -> str:
        """Return the cell value at (row, col), or '' when out of bounds."""
        if 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE:
            return self._grid[row][col]
        return ""

    def occupied(self, row: int, col: int) -> bool:
        """True when a letter tile has been placed at (row, col)."""
        cell = self.get(row, col)
        return bool(cell) and cell != self.EMPTY

    def has_neighbor(self, row: int, col: int) -> bool:
        """True when at least one orthogonally adjacent square is occupied."""
        return any(
            self.occupied(row + dr, col + dc)
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
        )

    # ── Derived data ───────────────────────────────────────────────────────

    def words_on_board(self) -> list[tuple[str, int, int, bool]]:
        """
        Return every run of ≥ 2 consecutive tiles as
        ``(word, start_row, start_col, is_horizontal)``.

        Used for board validation (checking all existing words are legal)
        and for terminal logging.
        """
        runs: list[tuple[str, int, int, bool]] = []

        for row in range(BOARD_SIZE):       # ── horizontal scan
            col = 0
            while col < BOARD_SIZE:
                if self.occupied(row, col):
                    start = col
                    while col < BOARD_SIZE and self.occupied(row, col):
                        col += 1
                    if col - start >= 2:
                        word = "".join(self._grid[row][c] for c in range(start, col))
                        runs.append((word, row, start, True))
                else:
                    col += 1

        for col in range(BOARD_SIZE):       # ── vertical scan
            row = 0
            while row < BOARD_SIZE:
                if self.occupied(row, col):
                    start = row
                    while row < BOARD_SIZE and self.occupied(row, col):
                        row += 1
                    if row - start >= 2:
                        word = "".join(self._grid[r][col] for r in range(start, row))
                        runs.append((word, start, col, False))
                else:
                    row += 1

        return runs

    def to_list(self) -> list[list[str]]:
        """Serialise to a 15×15 list-of-lists suitable for JSON responses."""
        return [row[:] for row in self._grid]


# ---------------------------------------------------------------------------
# Solver internals  (module-private; use find_top_moves() from outside)
# ---------------------------------------------------------------------------

def _compute_cross_checks(
    board: Board,
    dawg:  Dawg,
    transpose: bool,
) -> _CrossCheckGrid:
    """
    For every empty square compute which letters may be placed there without
    forming an illegal perpendicular (cross) word.

    When ``transpose=False`` we are generating **horizontal** moves.  Cross-
    words run vertically, so we scan the column above and below each square.

    When ``transpose=True`` we are generating **vertical** moves by reading
    the board through a logical row↔col swap.  Cross-words then run
    horizontally.

    Returns a 15×15 grid of letter sets:
      - occupied square  → empty set (no placement allowed)
      - no neighbours    → full alphabet (any letter is fine)
      - has neighbours   → only letters that complete a valid cross-word
    """
    checks: _CrossCheckGrid = [
        [set(ALL_LETTERS) for _ in range(BOARD_SIZE)]
        for _ in range(BOARD_SIZE)
    ]

    # These two helpers make the rest of the logic identical for both
    # directions by swapping row/col access when we are transposed.
    def cell(r: int, c: int) -> str:
        return board.get(c, r) if transpose else board.get(r, c)

    def is_occ(r: int, c: int) -> bool:
        return board.occupied(c, r) if transpose else board.occupied(r, c)

    for row in range(BOARD_SIZE):
        for col in range(BOARD_SIZE):
            if is_occ(row, col):
                checks[row][col] = set()
                continue

            # Collect tiles above (the cross-word prefix).
            above: list[str] = []
            r = row - 1
            while r >= 0 and is_occ(r, col):
                above.append(cell(r, col))
                r -= 1
            prefix = "".join(reversed(above))

            # Collect tiles below (the cross-word suffix).
            below: list[str] = []
            r = row + 1
            while r < BOARD_SIZE and is_occ(r, col):
                below.append(cell(r, col))
                r += 1
            suffix = "".join(below)

            if not prefix and not suffix:
                checks[row][col] = set(ALL_LETTERS)   # unconstrained square
            else:
                checks[row][col] = {
                    letter for letter in ALL_LETTERS
                    if prefix + letter + suffix in dawg
                }

    return checks


def _anchor_squares(board: Board, transpose: bool) -> list[tuple[int, int]]:
    """
    Return all anchor squares in (row, col) for the given generation direction.

    An anchor is an empty square with at least one occupied orthogonal
    neighbour.  On an empty board the centre square is the sole anchor,
    enforcing the rule that the first word must cover H8.
    """
    if board.is_empty:
        center = BOARD_SIZE // 2
        return [(center, center)]

    anchors: list[tuple[int, int]] = []
    for row in range(BOARD_SIZE):
        for col in range(BOARD_SIZE):
            # In transposed mode (row, col) maps to (col, row) on the real board.
            real_r, real_c = (col, row) if transpose else (row, col)
            if not board.occupied(real_r, real_c) and board.has_neighbor(real_r, real_c):
                anchors.append((row, col))
    return anchors


def _score_cross_word(
    board_row:   int,
    board_col:   int,
    new_letter:  str,
    letter_mult: int,
    word_mult:   int,
    transpose:   bool,
    board:       Board,
) -> int:
    """
    Score the perpendicular word formed when *new_letter* is placed at
    (board_row, board_col).  Returns 0 when there are no perpendicular tiles.

    Multipliers apply only to the *new* tile.  Existing tiles always score
    at face value, even if they sit on a bonus square (the bonus was already
    applied when they were originally played).
    """
    # The cross-word runs perpendicular to the current play direction.
    dr, dc = (0, 1) if transpose else (1, 0)

    # Walk backwards to the start of the cross word.
    r, c = board_row - dr, board_col - dc
    while board.occupied(r, c):
        r -= dr
        c -= dc
    r += dr
    c += dc

    # Accumulate all existing tiles in the cross word.
    cross_score = 0
    has_neighbor = False
    while board.occupied(r, c):
        cross_score += TILE_VALUES.get(board.get(r, c), 0)
        has_neighbor = True
        r += dr
        c += dc

    if not has_neighbor:
        return 0   # no perpendicular tiles → no cross word to score

    # Add the new tile (with letter multiplier) and apply the word multiplier.
    cross_score += TILE_VALUES.get(new_letter, 0) * letter_mult
    return cross_score * word_mult


def _score_move(
    word:          str,
    anchor_row:    int,
    start_col:     int,
    blank_indices: frozenset[int],
    transpose:     bool,
    board:         Board,
) -> int:
    """
    Calculate the total score for placing *word* starting at *start_col* on
    *anchor_row* (in possibly-transposed coordinates).

    Scoring rules
    -------------
    - Letter and word multipliers apply only to newly placed tiles.
    - Blank tiles (indices in *blank_indices*) score 0 regardless of letter.
    - Each new tile also scores any cross word it creates.
    - Using all 7 rack tiles in one turn awards the bingo bonus.
    """
    main_score      = 0
    word_multiplier = 1
    new_tile_count  = 0
    cross_total     = 0

    for i, letter in enumerate(word):
        col = start_col + i
        # Un-transpose coordinates to get the real board position.
        board_r, board_c = (col, anchor_row) if transpose else (anchor_row, col)
        tile_value = TILE_VALUES.get(letter, 0) if i not in blank_indices else 0

        if board.occupied(board_r, board_c):
            main_score += tile_value   # existing tile: no multipliers ever apply
        else:
            lm, wm = square_multipliers(board_r, board_c)
            main_score      += tile_value * lm
            word_multiplier *= wm
            new_tile_count  += 1
            cross_total     += _score_cross_word(
                board_r, board_c, letter, lm, wm, transpose, board
            )

    total = main_score * word_multiplier + cross_total
    if new_tile_count == 7:
        total += BINGO_BONUS
    return total


def _generate_from_anchor(
    board:        Board,
    rack_counts:  Counter[str],
    blanks:       int,
    dawg:         Dawg,
    cross_checks: _CrossCheckGrid,
    anchor_row:   int,
    anchor_col:   int,
    transpose:    bool,
    results:      list[Move],
) -> None:
    """
    Generate all legal moves for one anchor using the Appel–Jacobsen
    ``left_part`` / ``extend_right`` DAWG traversal.

    ``left_part``    — recursively build valid prefixes to the left of the
                       anchor by walking backward through the DAWG.
    ``extend_right`` — extend the current prefix one tile to the right,
                       consuming either a rack tile or an existing board tile.

    Both phases call ``cross_ok()`` before placing any tile, so every
    generated candidate is guaranteed to form only legal cross words.
    """

    # Transparent board access; swaps axes when in transposed mode.
    def cell(r: int, c: int) -> str:
        return board.get(c, r) if transpose else board.get(r, c)

    def is_occ(r: int, c: int) -> bool:
        return board.occupied(c, r) if transpose else board.occupied(r, c)

    def cross_ok(col: int, letter: str) -> bool:
        """True iff placing *letter* at (anchor_row, col) forms no illegal cross word."""
        return letter in cross_checks[anchor_row][col]

    def record(
        word:         str,
        start_col:    int,
        blank_idx:    frozenset[int],
        tiles_placed: int,
    ) -> None:
        """Validate a complete candidate word and, if legal, score and append it."""
        if tiles_placed == 0 or len(word) < 2:
            return
        if start_col + len(word) > BOARD_SIZE:
            return
        # Guard against silently merging with an abutting word.
        if is_occ(anchor_row, start_col - 1):
            return
        if is_occ(anchor_row, start_col + len(word)):
            return
        score = _score_move(word, anchor_row, start_col, blank_idx, transpose, board)
        # Un-transpose to get real board coordinates.
        real_r = start_col if transpose else anchor_row
        real_c = anchor_row if transpose else start_col
        results.append(Move(
            score=score, word=word,
            row=real_r, col=real_c,
            horizontal=not transpose,
        ))

    def extend_right(
        prefix:       str,
        node:         DawgNode,
        col:          int,
        rack:         Counter[str],
        blanks_left:  int,
        start_col:    int,
        tiles_placed: int,
        blank_idx:    frozenset[int],
    ) -> None:
        """
        Extend the word rightward one tile at a time via DAWG traversal.

        Backtracks automatically when the call returns — rack mutations are
        undone by the rack[letter] += 1 restore after each recursive call.
        """
        # Terminal node + next square is free ⟹ complete legal word.
        if node.terminal and tiles_placed > 0 and not is_occ(anchor_row, col):
            record(prefix, start_col, blank_idx, tiles_placed)

        if col >= BOARD_SIZE:
            return

        existing = cell(anchor_row, col)
        if existing and existing != Board.EMPTY:
            # Square already occupied — consume the existing letter if the DAWG allows.
            child = node.children.get(existing)
            if child:
                extend_right(
                    prefix + existing, child, col + 1,
                    rack, blanks_left, start_col, tiles_placed, blank_idx,
                )
        else:
            # Try each rack tile the DAWG and cross-checks both permit.
            for letter, child in node.children.items():
                if rack[letter] > 0 and cross_ok(col, letter):
                    rack[letter] -= 1
                    extend_right(
                        prefix + letter, child, col + 1,
                        rack, blanks_left, start_col,
                        tiles_placed + 1, blank_idx,
                    )
                    rack[letter] += 1   # restore for next iteration

            # Try the blank tile (can be any letter that passes cross-checks).
            if blanks_left > 0:
                for letter, child in node.children.items():
                    if cross_ok(col, letter):
                        extend_right(
                            prefix + letter, child, col + 1,
                            rack, blanks_left - 1, start_col,
                            tiles_placed + 1,
                            blank_idx | {len(prefix)},  # record this index as blank
                        )

    def left_part(
        partial:     str,
        node:        DawgNode,
        rack:        Counter[str],
        blanks_left: int,
        limit:       int,
    ) -> None:
        """
        Build all valid prefixes of length ≤ *limit* to the left of the anchor,
        then call extend_right from the anchor column.

        Cross-checks are applied here too: a prefix letter placed to the left
        of the anchor must not form an illegal cross word at that column in
        the perpendicular direction.
        """
        # Try extending right with the prefix built so far.
        extend_right(
            partial, node, anchor_col,
            rack, blanks_left,
            start_col=anchor_col - len(partial),
            tiles_placed=0,
            blank_idx=frozenset(),
        )

        if limit <= 0:
            return

        # The next prefix letter will be placed one column to the left.
        prefix_col = anchor_col - len(partial) - 1

        for letter, child in node.children.items():
            if rack[letter] > 0 and cross_ok(prefix_col, letter):
                rack[letter] -= 1
                left_part(partial + letter, child, rack, blanks_left, limit - 1)
                rack[letter] += 1

        if blanks_left > 0:
            for letter, child in node.children.items():
                if cross_ok(prefix_col, letter):
                    left_part(partial + letter, child, rack, blanks_left - 1, limit - 1)

    # ── Entry: board-prefix or free-prefix generation ─────────────────────

    if is_occ(anchor_row, anchor_col - 1):
        # Existing tiles immediately left of the anchor form a fixed prefix.
        prefix_letters: list[str] = []
        c = anchor_col - 1
        while c >= 0 and is_occ(anchor_row, c):
            prefix_letters.append(cell(anchor_row, c))
            c -= 1
        prefix = "".join(reversed(prefix_letters))
        node = dawg.get_node(prefix)
        if node:
            extend_right(
                prefix, node, anchor_col,
                Counter(rack_counts), blanks,
                start_col=anchor_col - len(prefix),
                tiles_placed=0,
                blank_idx=frozenset(),
            )
    else:
        # No tiles to the left — generate all prefixes up to `free_left` tiles long.
        free_left = 0
        c = anchor_col - 1
        while c >= 0 and not is_occ(anchor_row, c):
            free_left += 1
            c -= 1
        left_part("", dawg.root, Counter(rack_counts), blanks, free_left)


# ---------------------------------------------------------------------------
# Public solver API
# ---------------------------------------------------------------------------

def find_top_moves(
    board: Board,
    rack:  list[str],
    dawg:  Dawg,
    *,
    top_n: int = 5,
) -> list[Move]:
    """
    Find the highest-scoring legal moves for *rack* on *board*.

    Both horizontal and vertical directions are searched.  Candidates that
    are reachable via multiple anchors are deduplicated.  The result is
    sorted by score (highest first) and capped at *top_n*.

    Parameters
    ----------
    board:  Current board state.  Not mutated.
    rack:   Up to 7 tile strings; use ``'?'`` for a blank tile.
    dawg:   DAWG built from the legal word list.
    top_n:  Maximum number of moves to return (keyword-only).

    Returns
    -------
    list[Move]
        At most *top_n* unique, legally scored moves.
    """
    rack_upper  = [t.upper() for t in rack]
    rack_counts = Counter(t for t in rack_upper if t != "?")
    blanks      = rack_upper.count("?")

    candidates: list[Move] = []

    for transpose in (False, True):
        cross_checks = _compute_cross_checks(board, dawg, transpose)
        for anchor_row, anchor_col in _anchor_squares(board, transpose):
            _generate_from_anchor(
                board, rack_counts, blanks, dawg,
                cross_checks, anchor_row, anchor_col,
                transpose, candidates,
            )

    candidates.sort(key=lambda m: -m.score)

    # Deduplicate: the same word/position is often reachable via multiple anchors.
    seen:   set[tuple[str, int, int, bool]] = set()
    unique: list[Move] = []
    for move in candidates:
        key = (move.word, move.row, move.col, move.horizontal)
        if key not in seen:
            seen.add(key)
            unique.append(move)
        if len(unique) == top_n:
            break

    return unique


# ---------------------------------------------------------------------------
# Word-list loading
# ---------------------------------------------------------------------------


class WordListError(FileNotFoundError):
    """Raised when no word-list file can be found on disk.

    Callers (server, CLI, tests) decide how to handle the missing file.
    Using a typed exception instead of sys.exit() keeps the engine
    side-effect-free and makes error handling testable.
    """


def load_word_list_from_path(path: str) -> tuple[set[str], Dawg]:
    """
    Load a word list from an explicit file path and build a DAWG.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Word list not found: {path!r}")
    with open(path) as fh:
        words = {
            line.strip().upper()
            for line in fh
            if 2 <= len(line.strip()) <= BOARD_SIZE
        }
    print(f"Loaded {len(words):,} words from {path}")
    print("Building DAWG ...", end=" ", flush=True)
    dawg = build_dawg(words)
    print("done")
    return words, dawg


def load_word_list() -> tuple[set[str], Dawg]:
    """
    Search ``WORD_LIST_SEARCH_PATHS`` for a word file, load it, build a DAWG.

    Returns ``(word_set, dawg)`` where:
      - ``word_set`` enables O(1) membership checks for board validation.
      - ``dawg``     powers the move generator with O(|word|) prefix traversal.

    Raises
    ------
    WordListError
        When no file in ``WORD_LIST_SEARCH_PATHS`` exists.  The exception
        message includes the download command for ``enable1.txt``.
    """
    for path in WORD_LIST_SEARCH_PATHS:
        if os.path.exists(path):
            return load_word_list_from_path(path)

    raise WordListError(
        "No word list found.\n"
        "Download one with:\n"
        "  curl -O https://raw.githubusercontent.com/dolph/dictionary/master/enable1.txt"
    )
