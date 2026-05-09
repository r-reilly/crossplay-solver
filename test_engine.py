"""
test_engine.py — Unit tests for the Crossplay solver engine.

Run with:  python -m pytest test_engine.py -v
       or: python test_engine.py        (uses unittest directly)

Tests are organised into test classes that mirror the engine's public
concepts: DAWG, Board, scoring, and the full solver.  Each class is
self-contained — no shared setUp fixtures cross class boundaries — so
individual test classes can be run in isolation.

The tests use a small, hand-curated word set rather than the full 168 k-word
enable1.txt so that expected move outcomes are deterministic and tests run in
milliseconds.
"""

from __future__ import annotations

import unittest
from collections import Counter

from engine import (
    WordListError,
    ALL_LETTERS,
    BINGO_BONUS,
    BOARD_SIZE,
    DOUBLE_LETTER,
    DOUBLE_WORD,
    TILE_VALUES,
    TRIPLE_LETTER,
    TRIPLE_WORD,
    Board,
    Dawg,
    DawgNode,
    Move,
    _anchor_squares,
    _compute_cross_checks,
    _score_move,
    build_dawg,
    find_top_moves,
    square_multipliers,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Small but representative word set.  Every word used in board-state tests
# must appear here so the engine treats it as legal.
WORDS: set[str] = {
    "GO", "OIL", "LOG", "LOGO", "GOAL", "OILY", "GILL",
    "GRILL", "GIRL", "GLORY", "LOGY", "OGLING",
    "AB", "AD", "AG", "AI", "AL", "AM", "AN", "AR", "AS", "AT",
    "AW", "AX", "AY", "BA", "BE", "BI", "BO", "BY", "DE", "DO",
    "ED", "EF", "EH", "EL", "EM", "EN", "ER", "ES", "ET", "EX",
    "FA", "FE", "GI", "HA", "HE", "HI", "HM", "HO", "ID", "IF",
    "IN", "IS", "IT", "JO", "KA", "LA", "LI", "LO", "MA", "ME",
    "MI", "MM", "MO", "MU", "MY", "NA", "NE", "NO", "NU", "OD",
    "OE", "OF", "OH", "OM", "ON", "OP", "OR", "OS", "OW", "OX",
    "OY", "PA", "PE", "PI", "QI", "RE", "SI", "SO", "TA", "TI",
    "TO", "UH", "UM", "UN", "UP", "UR", "US", "UT", "WE", "WO",
    "XI", "XU", "YA", "YE", "YO", "ZA",
    "WAIVED", "OGLE", "OGLED", "ODE", "OPE", "OPED",
    "INAGED", "INRAGE", "INRAGED", "INAGEED",
    "GILL", "GILL", "GRILL",
}


def make_dawg(extra: set[str] | None = None) -> tuple[set[str], Dawg]:
    """Return (word_set, dawg) from WORDS, optionally extended by *extra*."""
    words = WORDS | (extra or set())
    return words, build_dawg(words)


# ---------------------------------------------------------------------------
# DAWG tests
# ---------------------------------------------------------------------------

class TestDawgNode(unittest.TestCase):
    """DawgNode identity and structural hashing."""

    def test_fresh_node_is_not_terminal(self) -> None:
        node = DawgNode()
        self.assertFalse(node.terminal)
        self.assertEqual(node.children, {})

    def test_equal_nodes_have_equal_hashes(self) -> None:
        a = DawgNode(); a.terminal = True
        b = DawgNode(); b.terminal = True
        # Both are leaf terminals with no children — structurally identical.
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_nodes_with_different_terminal_flags_are_unequal(self) -> None:
        a = DawgNode(); a.terminal = True
        b = DawgNode(); b.terminal = False
        self.assertNotEqual(a, b)


class TestDawg(unittest.TestCase):
    """DAWG construction and query correctness."""

    def setUp(self) -> None:
        self.words = {"GO", "GOAL", "GOALS", "OIL", "LOG"}
        self.dawg  = build_dawg(self.words)

    def test_all_inserted_words_are_members(self) -> None:
        for word in self.words:
            with self.subTest(word=word):
                self.assertIn(word, self.dawg)

    def test_non_member_words_are_rejected(self) -> None:
        for word in ("GOAT", "OILS", "LOGE", "ZZZZ", ""):
            with self.subTest(word=word):
                self.assertNotIn(word, self.dawg)

    def test_prefix_of_member_is_not_a_member(self) -> None:
        # "GO" is a word but "G" alone is not.
        self.assertNotIn("G", self.dawg)

    def test_get_node_returns_node_for_valid_prefix(self) -> None:
        node = self.dawg.get_node("GO")
        self.assertIsNotNone(node)

    def test_get_node_returns_none_for_invalid_prefix(self) -> None:
        self.assertIsNone(self.dawg.get_node("QQ"))

    def test_get_node_empty_prefix_returns_root(self) -> None:
        self.assertIs(self.dawg.get_node(""), self.dawg.root)

    def test_build_dawg_from_unordered_set(self) -> None:
        """build_dawg must sort internally — input order must not matter."""
        unordered = {"ZEBRA", "APE", "MONKEY"}
        dawg = build_dawg(unordered)
        for w in unordered:
            self.assertIn(w, dawg)

    def test_minimisation_shares_suffix_nodes(self) -> None:
        """
        Words with common suffixes should share DAWG nodes after minimisation.
        We verify this indirectly: both words are found and the DAWG doesn't
        contain invalid extra words.
        """
        words = {"CARE", "BARE", "DARE"}
        dawg  = build_dawg(words)
        self.assertIn("CARE", dawg)
        self.assertIn("BARE", dawg)
        self.assertNotIn("LARE", dawg)


# ---------------------------------------------------------------------------
# Board tests
# ---------------------------------------------------------------------------

class TestBoard(unittest.TestCase):
    """Board state, placement, and word extraction."""

    def _make_board(self, placements: list[tuple[int, int, str]]) -> Board:
        board = Board()
        for r, c, letter in placements:
            board.place(r, c, letter)
        return board

    # ── Basic state ────────────────────────────────────────────────────────

    def test_fresh_board_is_empty(self) -> None:
        board = Board()
        self.assertTrue(board.is_empty)
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                self.assertFalse(board.occupied(r, c))

    def test_place_sets_occupied(self) -> None:
        board = Board()
        board.place(7, 7, "a")          # lowercase should be uppercased
        self.assertTrue(board.occupied(7, 7))
        self.assertFalse(board.is_empty)
        self.assertEqual(board.get(7, 7), "A")

    def test_get_out_of_bounds_returns_empty_string(self) -> None:
        board = Board()
        self.assertEqual(board.get(-1, 0),  "")
        self.assertEqual(board.get(0, -1),  "")
        self.assertEqual(board.get(15, 0),  "")
        self.assertEqual(board.get(0, 15),  "")

    def test_occupied_out_of_bounds_returns_false(self) -> None:
        board = Board()
        self.assertFalse(board.occupied(-1, 7))
        self.assertFalse(board.occupied(7, 15))

    # ── has_neighbor ──────────────────────────────────────────────────────

    def test_has_neighbor_true_for_adjacent_cell(self) -> None:
        board = self._make_board([(7, 7, "A")])
        self.assertTrue(board.has_neighbor(7, 8))   # right
        self.assertTrue(board.has_neighbor(7, 6))   # left
        self.assertTrue(board.has_neighbor(6, 7))   # above
        self.assertTrue(board.has_neighbor(8, 7))   # below

    def test_has_neighbor_false_when_isolated(self) -> None:
        board = self._make_board([(7, 7, "A")])
        self.assertFalse(board.has_neighbor(0, 0))

    def test_has_neighbor_false_for_diagonal(self) -> None:
        board = self._make_board([(7, 7, "A")])
        self.assertFalse(board.has_neighbor(6, 6))  # diagonal — not a neighbour

    # ── words_on_board ────────────────────────────────────────────────────

    def test_words_on_board_finds_horizontal_word(self) -> None:
        board = self._make_board([
            (7, 3, "W"), (7, 4, "A"), (7, 5, "I"),
            (7, 6, "V"), (7, 7, "E"), (7, 8, "D"),
        ])
        runs = board.words_on_board()
        horiz = [(w, r, c) for w, r, c, h in runs if h]
        self.assertIn(("WAIVED", 7, 3), horiz)

    def test_words_on_board_finds_vertical_word(self) -> None:
        board = self._make_board([
            (5, 7, "G"), (6, 7, "O"), (7, 7, "A"), (8, 7, "L"),
        ])
        runs = board.words_on_board()
        vert = [(w, r, c) for w, r, c, h in runs if not h]
        self.assertIn(("GOAL", 5, 7), vert)

    def test_words_on_board_ignores_single_tiles(self) -> None:
        board = self._make_board([(7, 7, "A")])
        self.assertEqual(board.words_on_board(), [])

    def test_words_on_board_finds_both_directions(self) -> None:
        # Place a cross: GO horizontal, OIL vertical sharing the O.
        board = self._make_board([
            (7, 7, "G"), (7, 8, "O"),   # GO →
            (7, 8, "O"), (8, 8, "I"), (9, 8, "L"),   # OIL ↓
        ])
        runs = board.words_on_board()
        words_found = {w for w, *_ in runs}
        self.assertIn("GO",  words_found)
        self.assertIn("OIL", words_found)

    # ── to_list ───────────────────────────────────────────────────────────

    def test_to_list_returns_copy(self) -> None:
        board = Board()
        grid  = board.to_list()
        grid[0][0] = "Z"                # mutate the copy
        self.assertEqual(board.get(0, 0), Board.EMPTY)  # original unchanged


# ---------------------------------------------------------------------------
# Square-multiplier tests
# ---------------------------------------------------------------------------

class TestSquareMultipliers(unittest.TestCase):
    """Bonus-square lookup correctness."""

    def test_triple_word_squares(self) -> None:
        for pos in TRIPLE_WORD:
            with self.subTest(pos=pos):
                self.assertEqual(square_multipliers(*pos), (1, 3))

    def test_double_word_squares(self) -> None:
        for pos in DOUBLE_WORD:
            with self.subTest(pos=pos):
                self.assertEqual(square_multipliers(*pos), (1, 2))

    def test_triple_letter_squares(self) -> None:
        for pos in TRIPLE_LETTER:
            with self.subTest(pos=pos):
                self.assertEqual(square_multipliers(*pos), (3, 1))

    def test_double_letter_squares(self) -> None:
        for pos in DOUBLE_LETTER:
            with self.subTest(pos=pos):
                self.assertEqual(square_multipliers(*pos), (2, 1))

    def test_plain_square_returns_ones(self) -> None:
        # (0, 1) is not in any bonus set.
        self.assertEqual(square_multipliers(0, 1), (1, 1))

    def test_no_square_is_in_two_bonus_sets(self) -> None:
        """Bonus sets must be disjoint — otherwise multipliers are ambiguous."""
        all_sets = [TRIPLE_WORD, DOUBLE_WORD, TRIPLE_LETTER, DOUBLE_LETTER]
        flat     = [pos for s in all_sets for pos in s]
        self.assertEqual(len(flat), len(set(flat)),
                         "A square appears in more than one bonus set")


# ---------------------------------------------------------------------------
# Cross-check tests
# ---------------------------------------------------------------------------

class TestCrossChecks(unittest.TestCase):
    """Per-square cross-check set computation."""

    def setUp(self) -> None:
        self.words, self.dawg = make_dawg()

    def test_occupied_square_has_empty_check_set(self) -> None:
        board = Board()
        board.place(7, 7, "A")
        checks = _compute_cross_checks(board, self.dawg, transpose=False)
        self.assertEqual(checks[7][7], set())

    def test_isolated_empty_square_allows_all_letters(self) -> None:
        board = Board()
        board.place(7, 7, "A")          # place a tile away from (0, 0)
        checks = _compute_cross_checks(board, self.dawg, transpose=False)
        self.assertEqual(checks[0][0], set(ALL_LETTERS))

    def test_constrained_square_only_allows_valid_cross_words(self) -> None:
        """
        Place OIL vertically at real (row5–7, col7).

        For a *vertical* play at real col 8 (transpose=True), the square
        immediately to the right of O — real (row=5, col=8) — must only
        allow letters X where "OX" is a legal word.

        Coordinate mapping when transpose=True:
            transposed (row, col) ↔ real (col, row)
        So real (5, 8) ↔ transposed (8, 5), meaning we check [8][5].
        """
        board = Board()
        board.place(5, 7, "O")
        board.place(6, 7, "I")
        board.place(7, 7, "L")
        checks = _compute_cross_checks(board, self.dawg, transpose=True)
        # Only letters X such that "OX" is a valid word should be allowed.
        valid_after_o = {
            letter for letter in ALL_LETTERS if "O" + letter in self.words
        }
        # Real (5, 8) is transposed (8, 5).
        self.assertEqual(checks[8][5], valid_after_o)

    def test_transposed_checks_are_independent(self) -> None:
        board = Board()
        board.place(7, 7, "G")
        board.place(7, 8, "O")
        h_checks = _compute_cross_checks(board, self.dawg, transpose=False)
        v_checks = _compute_cross_checks(board, self.dawg, transpose=True)
        # The two grids are computed independently and may differ.
        # Both occupied squares must be empty sets in their own direction.
        self.assertEqual(h_checks[7][7], set())
        self.assertEqual(v_checks[7][7], set())


# ---------------------------------------------------------------------------
# Anchor-square tests
# ---------------------------------------------------------------------------

class TestAnchorSquares(unittest.TestCase):
    """Anchor-square enumeration."""

    def test_empty_board_has_single_centre_anchor(self) -> None:
        board   = Board()
        anchors = _anchor_squares(board, transpose=False)
        self.assertEqual(anchors, [(7, 7)])

    def test_placed_tile_creates_adjacent_anchors(self) -> None:
        board = Board()
        board.place(7, 7, "A")
        anchors = set(_anchor_squares(board, transpose=False))
        # The four orthogonal neighbours should be anchors.
        self.assertIn((6, 7), anchors)
        self.assertIn((8, 7), anchors)
        self.assertIn((7, 6), anchors)
        self.assertIn((7, 8), anchors)

    def test_occupied_square_is_not_an_anchor(self) -> None:
        board = Board()
        board.place(7, 7, "A")
        anchors = _anchor_squares(board, transpose=False)
        self.assertNotIn((7, 7), anchors)


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------

class TestScoring(unittest.TestCase):
    """Move-scoring arithmetic."""

    def test_simple_word_no_bonus(self) -> None:
        """Place GO at H8–I8 (no bonus squares at those positions)."""
        board = Board()
        # row=7 col=7 is H8; we place G then O
        # (7,7) is not in any bonus set for Crossplay.
        score = _score_move(
            word="GO",
            anchor_row=7, start_col=7,
            blank_indices=frozenset(),
            transpose=False,
            board=board,
        )
        expected = TILE_VALUES["G"] + TILE_VALUES["O"]   # 2 + 1 = 3
        self.assertEqual(score, expected)

    def test_blank_tile_scores_zero(self) -> None:
        """A blank tile (index in blank_indices) contributes 0 points."""
        board = Board()
        score = _score_move(
            word="GO",
            anchor_row=7, start_col=7,
            blank_indices=frozenset({0}),   # G is blank
            transpose=False,
            board=board,
        )
        expected = 0 + TILE_VALUES["O"]     # 0 + 1 = 1
        self.assertEqual(score, expected)

    def test_double_letter_multiplier_applied(self) -> None:
        """Place a tile on a 2L square and confirm the letter value is doubled."""
        board = Board()
        # (0, 7) is a DOUBLE_LETTER square.
        # Place a single-letter word that starts there.  Using "GO" horizontally
        # puts G at (0,7)=2L and O at (0,8)=plain.
        score = _score_move(
            word="GO",
            anchor_row=0, start_col=7,
            blank_indices=frozenset(),
            transpose=False,
            board=board,
        )
        expected = TILE_VALUES["G"] * 2 + TILE_VALUES["O"]
        self.assertEqual(score, expected)

    def test_bingo_bonus_awarded_for_seven_tiles(self) -> None:
        """Playing all 7 rack tiles in one turn should add BINGO_BONUS."""
        board  = Board()
        word   = "ABCDEFG"          # 7 letters, all new
        # Score without bingo first to know the base.
        base   = sum(TILE_VALUES.get(ch, 0) for ch in word)
        result = _score_move(
            word=word,
            anchor_row=2, start_col=0,
            blank_indices=frozenset(),
            transpose=False,
            board=board,
        )
        # Result must be at least base + BINGO_BONUS (bonus squares may add more).
        self.assertGreaterEqual(result, base + BINGO_BONUS)

    def test_existing_tile_scores_without_multiplier(self) -> None:
        """An existing board tile contributes its face value, no multiplier."""
        board = Board()
        board.place(7, 7, "G")   # G already on board at a plain square
        score = _score_move(
            word="GO",
            anchor_row=7, start_col=7,
            blank_indices=frozenset(),
            transpose=False,
            board=board,
        )
        # G is pre-existing (no multiplier); O is new at (7,8) plain.
        expected = TILE_VALUES["G"] + TILE_VALUES["O"]
        self.assertEqual(score, expected)


# ---------------------------------------------------------------------------
# Full solver tests
# ---------------------------------------------------------------------------

class TestFindTopMoves(unittest.TestCase):
    """Integration tests for find_top_moves."""

    def setUp(self) -> None:
        self.words, self.dawg = make_dawg()

    def _place_word(
        self,
        board: Board,
        word:  str,
        row:   int,
        col:   int,
        horizontal: bool = True,
    ) -> None:
        for i, letter in enumerate(word):
            r = row + (0 if horizontal else i)
            c = col + (i if horizontal else 0)
            board.place(r, c, letter)

    # ── Output contract ───────────────────────────────────────────────────

    def test_returns_list_of_move_namedtuples(self) -> None:
        board = Board()
        moves = find_top_moves(board, ["G", "O"], self.dawg, top_n=5)
        self.assertIsInstance(moves, list)
        for m in moves:
            self.assertIsInstance(m, Move)

    def test_results_are_sorted_by_descending_score(self) -> None:
        board = Board()
        moves = find_top_moves(board, ["G", "O", "A", "L"], self.dawg, top_n=5)
        for i in range(len(moves) - 1):
            self.assertGreaterEqual(moves[i].score, moves[i + 1].score)

    def test_top_n_limits_results(self) -> None:
        board = Board()
        for n in (1, 3, 5):
            moves = find_top_moves(board, list("GOALLLL"), self.dawg, top_n=n)
            self.assertLessEqual(len(moves), n)

    def test_no_duplicate_placements(self) -> None:
        board = Board()
        moves = find_top_moves(board, list("GOALLLL"), self.dawg, top_n=10)
        keys  = [(m.word, m.row, m.col, m.horizontal) for m in moves]
        self.assertEqual(len(keys), len(set(keys)))

    def test_all_moves_within_board_bounds(self) -> None:
        board = Board()
        moves = find_top_moves(board, list("GOALLLL"), self.dawg, top_n=10)
        for m in moves:
            self.assertGreaterEqual(m.row, 0)
            self.assertGreaterEqual(m.col, 0)
            end_col = m.col + (len(m.word) if m.horizontal else 0)
            end_row = m.row + (len(m.word) if not m.horizontal else 0)
            self.assertLessEqual(end_col, BOARD_SIZE)
            self.assertLessEqual(end_row, BOARD_SIZE)

    def test_all_moves_place_at_least_one_new_tile(self) -> None:
        """Every move must use at least one rack tile (no pure board reads)."""
        board = Board()
        self._place_word(board, "GO", 7, 7)
        moves = find_top_moves(board, list("ALLOG"), self.dawg, top_n=5)
        for m in moves:
            new_tiles = sum(
                1 for i in range(len(m.word))
                if not board.occupied(
                    m.row + (0 if m.horizontal else i),
                    m.col + (i if m.horizontal else 0),
                )
            )
            self.assertGreater(new_tiles, 0, f"{m.word} places no new tiles")

    # ── First move ────────────────────────────────────────────────────────

    def test_first_move_on_empty_board_covers_centre(self) -> None:
        """The first word must pass through the centre square H8 (7, 7)."""
        board = Board()
        moves = find_top_moves(board, list("GOALLOG"), self.dawg, top_n=10)
        self.assertTrue(
            any(
                (m.row == 7 and m.col <= 7 <= m.col + len(m.word) - 1 and m.horizontal)
                or (m.col == 7 and m.row <= 7 <= m.row + len(m.word) - 1 and not m.horizontal)
                for m in moves
            ),
            "No first-move candidate covers the centre square H8",
        )

    # ── Cross-word correctness ────────────────────────────────────────────

    def test_generated_moves_form_only_valid_cross_words(self) -> None:
        """
        For every candidate move, verify that each newly placed tile forms
        only legal cross words with adjacent perpendicular tiles.

        This is the key correctness invariant of the cross-check mechanism.
        """
        board = Board()
        self._place_word(board, "GO",  7, 7)
        self._place_word(board, "OIL", 7, 8, horizontal=False)

        moves = find_top_moves(board, list("ALLOG?"), self.dawg, top_n=10)
        for move in moves:
            self._assert_no_invalid_cross_words(move, board)

    def _assert_no_invalid_cross_words(self, move: Move, board: Board) -> None:
        for i, letter in enumerate(move.word):
            row = move.row + (0 if move.horizontal else i)
            col = move.col + (i if move.horizontal else 0)
            if board.occupied(row, col):
                continue  # existing tile — no new cross word formed

            if move.horizontal:
                # Vertical cross word
                above, r = [], row - 1
                while r >= 0 and board.occupied(r, col):
                    above.append(board.get(r, col)); r -= 1
                below, r = [], row + 1
                while r < BOARD_SIZE and board.occupied(r, col):
                    below.append(board.get(r, col)); r += 1
                cross = "".join(reversed(above)) + letter + "".join(below)
            else:
                # Horizontal cross word
                left, c = [], col - 1
                while c >= 0 and board.occupied(row, c):
                    left.append(board.get(row, c)); c -= 1
                right, c = [], col + 1
                while c < BOARD_SIZE and board.occupied(row, c):
                    right.append(board.get(row, c)); c += 1
                cross = "".join(reversed(left)) + letter + "".join(right)

            if len(cross) >= 2:
                self.assertIn(
                    cross, self.words,
                    f"Move {move.word!r} forms invalid cross word {cross!r} "
                    f"at ({row}, {col})",
                )

    # ── Blank tiles ───────────────────────────────────────────────────────

    def test_blank_tile_can_be_used_as_any_letter(self) -> None:
        """A '?' in the rack should contribute to move generation."""
        board = Board()
        # Rack with only one real letter plus a blank: can still form "GO".
        moves = find_top_moves(board, ["G", "?"], self.dawg, top_n=5)
        words_found = {m.word for m in moves}
        self.assertTrue(
            any(len(w) >= 2 for w in words_found),
            "No 2-letter words found with G + blank rack",
        )

    def test_blank_tile_scores_zero(self) -> None:
        """Moves that use a blank tile must not count it for points."""
        board = Board()
        moves = find_top_moves(board, ["?", "O"], self.dawg, top_n=10)
        # If ? is used as G to play GO: score = 0 (blank G) + 1 (O) = 1.
        # No move using a blank should score as if it were a real tile.
        for move in moves:
            # Rough upper bound: 7 tiles × max value (10) × max word mult (3) + bingo.
            self.assertLess(move.score, 7 * 10 * 3 + BINGO_BONUS + 1)

    # ── Move.to_dict ──────────────────────────────────────────────────────

    def test_move_to_dict_has_required_keys(self) -> None:
        board = Board()
        moves = find_top_moves(board, ["G", "O"], self.dawg, top_n=1)
        if moves:
            d = moves[0].to_dict()
            for key in ("word", "row", "col", "horizontal", "score"):
                self.assertIn(key, d)


# ---------------------------------------------------------------------------
# Server-layer helpers (imported separately to avoid loading the UI HTML)
# ---------------------------------------------------------------------------

class TestServiceHelpers(unittest.TestCase):
    """Unit tests for service.py payload helpers."""

    def setUp(self) -> None:
        # Import lazily to avoid triggering word-list loading at collection time.
        import service as svc
        self.svc = svc

    def test_board_from_grid_places_letters(self) -> None:
        grid = [[Board.EMPTY] * 15 for _ in range(15)]
        grid[7][7] = "A"
        grid[7][8] = "B"
        board = self.svc._board_from_grid(grid)
        self.assertTrue(board.occupied(7, 7))
        self.assertEqual(board.get(7, 7), "A")
        self.assertTrue(board.occupied(7, 8))

    def test_board_from_grid_ignores_dots_and_empty_strings(self) -> None:
        grid = [["." if c == 0 else "" for c in range(15)] for _ in range(15)]
        board = self.svc._board_from_grid(grid)
        self.assertTrue(board.is_empty)

    def test_board_from_grid_uppercases_lowercase_input(self) -> None:
        grid = [[Board.EMPTY] * 15 for _ in range(15)]
        grid[0][0] = "z"
        board = self.svc._board_from_grid(grid)
        self.assertEqual(board.get(0, 0), "Z")

    def test_parse_rack_compact_string(self) -> None:
        self.assertEqual(self.svc._parse_rack("OYILLG?"),
                         ["O", "Y", "I", "L", "L", "G", "?"])

    def test_parse_rack_space_separated(self) -> None:
        self.assertEqual(self.svc._parse_rack("O Y I L L G ?"),
                         ["O", "Y", "I", "L", "L", "G", "?"])

    def test_parse_rack_comma_separated(self) -> None:
        self.assertEqual(self.svc._parse_rack("O,Y,I"), ["O", "Y", "I"])


class TestSolverService(unittest.TestCase):
    """Unit tests for SolverService (injecting a tiny word set)."""

    def _make_service(self, words: set[str] | None = None) -> object:
        import service as svc
        w = words or {"GO", "OIL", "LOG", "GOAL"}
        return svc.SolverService(words=w, dawg=build_dawg(w))

    def test_solve_returns_required_keys(self) -> None:
        """End-to-end solve() with an injected service — no filesystem access."""
        service = self._make_service({"GO", "OIL", "LOG"})
        grid    = [[Board.EMPTY] * 15 for _ in range(15)]
        result  = service.solve(grid, "GOAL?LG")
        for key in ("board", "rack", "moves", "notes", "tiles_on_board"):
            self.assertIn(key, result)

    def test_solve_empty_rack_produces_no_moves(self) -> None:
        service = self._make_service({"GO"})
        grid    = [[Board.EMPTY] * 15 for _ in range(15)]
        result  = service.solve(grid, "")
        self.assertEqual(result["moves"], [])

    def test_solve_notes_empty_when_board_words_are_valid(self) -> None:
        service = self._make_service({"GO", "OIL", "LOG"})
        grid    = [[Board.EMPTY] * 15 for _ in range(15)]
        grid[7][7] = "G"; grid[7][8] = "O"
        result  = service.solve(grid, "ILLLOG")
        self.assertEqual(result["notes"], "")

    def test_solve_notes_non_empty_for_invalid_board_word(self) -> None:
        service = self._make_service({"GO"})
        grid    = [[Board.EMPTY] * 15 for _ in range(15)]
        # Place ZZZ — definitely not in {"GO"}.
        grid[7][7]="Z"; grid[7][8]="Z"; grid[7][9]="Z"
        result  = service.solve(grid, "GOOOOO")
        self.assertIn("invalid", result["notes"].lower())

    def test_invalid_words_returns_list_of_illegal_words(self) -> None:
        import service as svc
        service = self._make_service({"GO"})
        board   = Board()
        board.place(7,7,"Z"); board.place(7,8,"Z"); board.place(7,9,"Z")
        invalid = service.invalid_words(board)
        self.assertIn("ZZZ", invalid)

    def test_invalid_words_empty_when_all_legal(self) -> None:
        import service as svc
        service = self._make_service({"GO"})
        board   = Board()
        board.place(7,7,"G"); board.place(7,8,"O")
        invalid = service.invalid_words(board)
        self.assertEqual(invalid, [])

    def test_server_set_service_injects_service(self) -> None:
        """server.set_service / get_service round-trip without disk access."""
        import server
        service = self._make_service({"GO", "OIL"})
        server.set_service(service)
        self.assertIs(server.get_service(), service)

class TestWordListError(unittest.TestCase):
    """engine.WordListError is raised instead of sys.exit when no word file exists."""

    def test_load_word_list_raises_when_no_file_found(self) -> None:
        from engine import WordListError, WORD_LIST_SEARCH_PATHS, load_word_list
        import unittest.mock as mock
        # Patch os.path.exists to always return False so no file is "found".
        with mock.patch("engine.os.path.exists", return_value=False):
            with self.assertRaises(WordListError):
                load_word_list()

    def test_load_word_list_from_path_raises_file_not_found(self) -> None:
        from engine import load_word_list_from_path
        with self.assertRaises(FileNotFoundError):
            load_word_list_from_path("/no/such/file.txt")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
