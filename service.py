"""
service.py — SolverService: the boundary between engine and server.

Why this layer exists
---------------------
``engine.py`` is pure game logic — it knows nothing about files, HTTP, or
caching.  ``server.py`` is pure HTTP plumbing — it should not decide which
word list to load or how to optimise startup.  ``SolverService`` sits between
them and owns those decisions:

  - Which word list file to load.
  - Whether to cache the compiled DAWG on disk (cutting ~0.8 s startup cost
    to milliseconds after the first run).
  - How to expose the engine API in a testable, replaceable way.

Replacing the engine underneath (e.g. with a Rust extension via PyO3) only
requires providing a new ``SolverService`` implementation — ``server.py``
never needs to change.

Usage
-----
::

    # Production: auto-find word list, use disk cache
    service = SolverService.from_word_list()

    # Explicit path
    service = SolverService.from_word_list(word_list_path="twl06.txt")

    # Tests: inject a tiny word set, no disk access
    from engine import build_dawg
    service = SolverService(words={"GO","OIL"}, dawg=build_dawg({"GO","OIL"}))

    # Solve
    result = service.solve(grid_data=[[...]], rack_str="OYILLG?")
"""

from __future__ import annotations

import dataclasses
import logging
import os
import pickle
import time

from engine import (
    BOARD_SIZE,
    COL_LABELS,
    Board,
    Dawg,
    Move,
    WordListError,
    build_dawg,
    find_top_moves,
    load_word_list,
    load_word_list_from_path,
)

logger = logging.getLogger(__name__)

# Default path for the pickled DAWG cache.
# The cache file sits next to the word list; its name encodes the word count
# so a change in word list automatically invalidates the old cache.
# Cache filename encodes both the source file stem and word count.
# Switching word lists (e.g. enable1.txt → TWL06.txt) always produces
# a different cache name, so stale caches are never silently reused.
_CACHE_FILENAME_TEMPLATE = ".dawg_cache_{stem}_{word_count}.pkl"


@dataclasses.dataclass
class SolverService:
    """
    Facade over the solver engine.

    Holds the loaded word set and DAWG, and exposes ``solve()`` as the single
    entry point for the HTTP handler.  Because this is a plain dataclass it is
    trivially injectable in tests::

        service = SolverService(words={"GO","OIL"}, dawg=build_dawg({"GO","OIL"}))
        result  = service.solve([[...]], "GO")
        assert result["moves"]

    Attributes
    ----------
    words:
        Set of all legal uppercase words (used for board validation).
    dawg:
        Compiled DAWG used by the move generator.
    """

    words: set[str]
    dawg:  Dawg

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_word_list(
        cls,
        word_list_path: str | None = None,
        *,
        use_cache: bool = True,
        cache_dir: str | None = None,
    ) -> "SolverService":
        """
        Build a ``SolverService`` by loading a word list from disk.

        Parameters
        ----------
        word_list_path:
            Path to the word list file.  If ``None``, the first file found in
            ``engine.WORD_LIST_SEARCH_PATHS`` is used.
        use_cache:
            When ``True`` (default), save/restore a pickled DAWG beside the
            word list file.  This cuts startup time from ~0.8 s to ~0.05 s on
            subsequent runs.
        cache_dir:
            Directory for the cache file.  Defaults to the directory containing
            the word list file.

        Raises
        ------
        WordListError
            If no word list can be found (only when ``word_list_path`` is None).
        FileNotFoundError
            If ``word_list_path`` is given but does not exist.
        """
        if word_list_path is not None:
            words, dawg = cls._load_with_cache(
                word_list_path, use_cache=use_cache, cache_dir=cache_dir
            )
        else:
            # Search default paths; load_word_list() raises WordListError on failure.
            from engine import WORD_LIST_SEARCH_PATHS
            found_path: str | None = next(
                (p for p in WORD_LIST_SEARCH_PATHS if os.path.exists(p)), None
            )
            if found_path is None:
                raise WordListError(
                    "No word list found.\n"
                    "Download one with:\n"
                    "  curl -O https://raw.githubusercontent.com/dolph/dictionary"
                    "/master/enable1.txt"
                )
            words, dawg = cls._load_with_cache(
                found_path, use_cache=use_cache, cache_dir=cache_dir
            )

        return cls(words=words, dawg=dawg)

    @classmethod
    def _load_with_cache(
        cls,
        word_list_path: str,
        *,
        use_cache: bool,
        cache_dir: str | None,
    ) -> tuple[set[str], Dawg]:
        """
        Load (words, dawg) from disk, using a pickle cache when available.

        Cache invalidation strategy: the cache filename encodes the word count.
        When the word list changes, the count changes, the old cache filename
        is never matched, and a fresh DAWG is built automatically.  This is
        intentionally simple — a content hash would be more robust but adds
        a full-file read on every startup.
        """
        if not use_cache:
            return load_word_list_from_path(word_list_path)

        # ── Try to load from cache ────────────────────────────────────────
        base_dir    = cache_dir or os.path.dirname(os.path.abspath(word_list_path))
        word_count  = cls._count_valid_words(word_list_path)
        # Use the base filename (without extension) so cache files are
        # self-describing and switching word lists auto-invalidates the cache.
        stem        = os.path.splitext(os.path.basename(word_list_path))[0]
        cache_name  = _CACHE_FILENAME_TEMPLATE.format(stem=stem, word_count=word_count)
        cache_path  = os.path.join(base_dir, cache_name)

        if os.path.exists(cache_path):
            try:
                t0 = time.perf_counter()
                with open(cache_path, "rb") as fh:
                    cached: dict = pickle.load(fh)
                words: set[str] = cached["words"]
                dawg:  Dawg     = cached["dawg"]
                elapsed = time.perf_counter() - t0
                print(f"Loaded {len(words):,} words from cache ({elapsed:.2f}s)")
                return words, dawg
            except Exception as exc:
                # Corrupt or incompatible cache — fall through to rebuild.
                logger.warning("Cache load failed (%s); rebuilding DAWG.", exc)

        # ── Build from scratch and save cache ────────────────────────────
        words, dawg = load_word_list_from_path(word_list_path)
        cls._save_cache(cache_path, words, dawg)
        return words, dawg

    @staticmethod
    def _count_valid_words(path: str) -> int:
        """Count words in *path* that would pass the engine's length filter."""
        with open(path) as fh:
            return sum(
                1 for line in fh
                if 2 <= len(line.strip()) <= BOARD_SIZE
            )

    @staticmethod
    def _save_cache(cache_path: str, words: set[str], dawg: Dawg) -> None:
        """Persist words and DAWG to *cache_path* as a pickle file."""
        try:
            with open(cache_path, "wb") as fh:
                pickle.dump({"words": words, "dawg": dawg}, fh,
                            protocol=pickle.HIGHEST_PROTOCOL)
            print(f"DAWG cached to {cache_path!r}")
        except OSError as exc:
            # Cache write failure is non-fatal; log and continue.
            logger.warning("Could not write DAWG cache: %s", exc)

    # ------------------------------------------------------------------
    # Core solve API
    # ------------------------------------------------------------------

    def solve(self, grid_data: list[list], rack_str: str) -> dict:
        """
        Build a board, validate existing words, find best moves, return result.

        This is the single method the HTTP handler calls.  Separating it from
        the handler means tests can call ``service.solve(grid, rack)`` directly
        without constructing an HTTP request or spinning up a server::

            result = service.solve([[...]], "OYILLG?")
            assert result["moves"][0]["score"] > 0

        Parameters
        ----------
        grid_data:
            15×15 list-of-lists from the browser JSON payload.
        rack_str:
            Rack as a string, e.g. ``"OYILLG?"`` or ``"O Y I L L G ?"``.

        Returns
        -------
        dict with keys: ``board``, ``rack``, ``moves``, ``notes``, ``tiles_on_board``.
        """
        board = _board_from_grid(grid_data)
        rack  = _parse_rack(rack_str)

        tile_count = sum(
            1 for r in range(BOARD_SIZE) for c in range(BOARD_SIZE)
            if board.occupied(r, c)
        )
        print(f"  Solve: {tile_count} tiles on board, rack {rack}", flush=True)

        # Validate all words on the board and log each one.
        invalid_words = self._validate_board(board)

        moves: list[Move] = find_top_moves(board, rack, self.dawg, top_n=5)
        notes = f"{len(invalid_words)} invalid board word(s)" if invalid_words else ""

        return {
            "board":          board.to_list(),
            "rack":           rack,
            "moves":          [m.to_dict() for m in moves],
            "notes":          notes,
            "tiles_on_board": tile_count,
        }

    def invalid_words(self, board: Board) -> list[str]:
        """
        Return a list of words on *board* that are not in the word set.

        Useful for board validation outside of a full solve cycle, e.g. to
        highlight incorrect placements in the UI before the user submits.
        """
        return [w for w, *_ in board.words_on_board() if w not in self.words]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_board(self, board: Board) -> list[str]:
        """
        Log every word on the board to the terminal with a ✓/✗ marker.

        Returns the list of invalid words (empty if all words are legal).
        """
        invalid: list[str] = []
        for word, row, col, is_horizontal in board.words_on_board():
            is_valid  = word in self.words
            direction = "→" if is_horizontal else "↓"
            mark      = "✓" if is_valid else "✗"
            if not is_valid:
                invalid.append(word)
            print(f"    {mark} {word} @ {COL_LABELS[col]}{row + 1} {direction}",
                  flush=True)
        return invalid


# ---------------------------------------------------------------------------
# Payload helpers (used by SolverService.solve and testable independently)
# ---------------------------------------------------------------------------

def _board_from_grid(grid_data: list[list]) -> Board:
    """
    Construct a Board from the 15×15 list-of-lists sent by the browser.

    Non-letter values and empty strings are treated as empty squares.
    Rows and columns beyond the board boundary are silently ignored.
    """
    board = Board()
    for row_idx, row in enumerate(grid_data[:BOARD_SIZE]):
        for col_idx, cell in enumerate(row[:BOARD_SIZE]):
            letter = str(cell).upper().strip()
            if letter and letter != Board.EMPTY:
                board.place(row_idx, col_idx, letter)
    return board


def _parse_rack(rack_str: str) -> list[str]:
    """
    Parse a rack string into a list of single uppercase letters.

    Accepts space-separated tokens (``"O ? Y I L L G"``) and compact form
    (``"OYILLG?"``).  Commas are treated as whitespace.
    """
    tokens = rack_str.replace(",", " ").split()
    if len(tokens) > 1:
        return [t.upper() for t in tokens if t.strip()]
    return [ch.upper() for ch in rack_str.replace(" ", "") if ch.strip()]
