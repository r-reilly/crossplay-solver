# Crossplay Solver

A local web-based move solver for [NYT Crossplay](https://www.nytimes.com/games/crossplay).

Enter your board manually, type your rack, and get the top 5 scored plays in under a second — complete with word definitions. No accounts, no ads, no data sent anywhere except the dictionary lookup.

---

## Features

- **Interactive 15×15 board** — click a cell, type a letter, arrow-key to navigate
- **Auto-save** — board and rack persist in `localStorage`; they reload automatically when you reopen the page or restart the server, so you never re-enter a position
- **Carousel result cards** — use ← → arrows to browse the top 5 moves; each card shows the word, position, score, and a fetched definition
- **Word definitions** — fetched automatically from the [Free Dictionary API](https://dictionaryapi.dev/); falls back to the singular form for plurals (e.g. QAIDS → QAID)
- **DAWG disk cache** — the compiled word graph is saved after the first run; subsequent starts load in ~50 ms instead of ~800 ms
- **Dark mode** — respects `prefers-color-scheme`
- **Zero dependencies** — Python standard library only; no npm, no build step

---

## Project layout

```
crossplay_solver.py   # Thin entry point (16 lines) — delegates to server.py
engine.py             # Pure solver: DAWG, Board, scoring, find_top_moves()
service.py            # SolverService: word-list loading, DAWG caching, solve()
server.py             # HTTP handler + inline HTML/CSS/JS UI
test_engine.py        # 67 unit tests — no word-list file required
collins.txt           # Word list (see Setup)
```

### Dependency graph

```
crossplay_solver.py
        │
        ▼
    server.py  ──imports──▶  service.py  ──imports──▶  engine.py
```

Each layer knows only about the layer to its right:
- `engine.py` — no I/O, no HTTP, no side-effects. Import and test without starting anything.
- `service.py` — owns file loading and caching; calls only engine functions.
- `server.py` — owns HTTP; calls only `SolverService.solve()`.
- `crossplay_solver.py` — one function call; exists so users type `python crossplay_solver.py`.

---

## Algorithm

Implements **Appel & Jacobsen (1988), "The World's Fastest Scrabble Program"**:

1. **DAWG** — The word list is compiled into a Directed Acyclic Word Graph. Structurally identical suffix sub-graphs are merged so the full dictionary fits in memory and every prefix lookup is O(word length).

2. **Cross-check sets** — Before generating any move, the engine precomputes which letters may legally be placed at each empty square without creating an illegal perpendicular word. Invalid placements are ruled out *during* generation — there is no post-filtering step.

3. **Anchor-based generation** — For each empty square adjacent to a placed tile (an *anchor*), the engine walks left through the DAWG building prefixes, then extends right — gated at every step by the cross-check sets.

Scoring follows Crossplay rules: Crossplay-specific tile values, verified bonus-square positions, and a **40-point bingo bonus** for using all 7 rack tiles.

---

## Setup

**1. Python 3.10 or later** (no third-party packages needed)

```bash
python --version   # must be 3.10+
```

**2. Word list — Collins Scrabble Words**

Crossplay's dictionary most closely matches **Collins Scrabble Words** (also distributed as `sowpods.txt`). Download your Collins word list, name it `collins.txt`, and place it in the same directory as the solver files.

The engine searches for a word list in this order:

```
collins.txt  →  sowpods.txt  →  TWL06.txt  →  twl06.txt  →  enable1.txt
```

> **Why Collins and not TWL06 or enable1.txt?**
> TWL06 (North American tournament list) omits words that Crossplay accepts — EW, ELD, WOS among others. `enable1.txt` has even larger gaps. Collins is the closest freely available match to the Crossplay dictionary and correctly validates cross-words like ELD and WOS that determine whether high-value plays (e.g. QAIDS at A15 for 130 pts) are legal.

---

## Running

```bash
python crossplay_solver.py
```

Opens `http://localhost:8080` automatically. On the **first run** the DAWG is built (~0.8 s) and cached to `.dawg_cache_<N>.pkl`; subsequent starts load from cache (~0.05 s).

| Flag | Default | Description |
|------|---------|-------------|
| `--port PORT` | `8080` | TCP port |
| `--no-browser` | off | Skip auto-opening browser |

```bash
python crossplay_solver.py --port 9090 --no-browser
```

---

## Using the UI

1. **Click any cell** on the board and type a letter — the cursor advances right automatically.
2. **Arrow keys** navigate, **Backspace** clears a cell.
3. Type your **rack** (use `?` for a blank tile) and click **Find best moves**.
4. The top 5 moves appear as horizontal cards in a carousel. Use **← →** arrows to browse. Click any card to highlight that placement on the board.
5. **Clear board** resets everything including the saved state.

**Board state is saved automatically.** Every cell and rack change is written to `localStorage` immediately. If you close the tab, restart the server, or refresh the page, the board and rack reload exactly as you left them — a brief green flash on the board confirms the restore.

---

## Running the tests

```bash
python -m unittest test_engine -v   # no word-list file needed
```

Or with pytest:

```bash
pytest test_engine.py -v
```

**67 tests** cover:

| Class | What is tested |
|-------|---------------|
| `TestDawgNode` | Node equality and structural hashing |
| `TestDawg` | Insert, membership, prefix traversal, minimisation |
| `TestBoard` | Placement, bounds, neighbours, word extraction |
| `TestSquareMultipliers` | Every bonus type; disjoint-set invariant |
| `TestCrossChecks` | Occupied, unconstrained, and constrained squares |
| `TestAnchorSquares` | Empty board, first-move rule, adjacency |
| `TestScoring` | Face value, blanks, multipliers, bingo bonus |
| `TestFindTopMoves` | Type, sort order, deduplication, bounds, cross-word validity, blanks |
| `TestServiceHelpers` | `_board_from_grid`, `_parse_rack` |
| `TestSolverService` | `solve()` keys, empty rack, valid/invalid notes, `invalid_words()`, server injection |
| `TestWordListError` | `WordListError` raised instead of `sys.exit` |

Tests use an injected 50-word set — no word file required — and run in under 300 ms.

---

## Using the engine directly

```python
from engine import Board, build_dawg, find_top_moves, load_word_list

words, dawg = load_word_list()   # raises WordListError if no file found

board = Board()
board.place(7, 7, "W"); board.place(7, 8, "A"); board.place(7, 9, "I")
board.place(7,10, "V"); board.place(7,11, "E"); board.place(7,12, "D")

moves = find_top_moves(board, ["O","Y","I","L","L","G","?"], dawg, top_n=5)
for m in moves:
    col = "ABCDEFGHIJKLMNO"[m.col]
    print(f"{m.word:15} {col}{m.row+1} {'→' if m.horizontal else '↓'}  {m.score} pts")
```

## Using SolverService

```python
from service import SolverService

# Production: auto-find word list, use DAWG disk cache
service = SolverService.from_word_list()

# Explicit path, no cache
service = SolverService.from_word_list("TWL06.txt", use_cache=False)

# In tests: inject a tiny word set, no filesystem access
from engine import build_dawg
service = SolverService(words={"GO","OIL"}, dawg=build_dawg({"GO","OIL"}))

result = service.solve(grid_data=[[...]], rack_str="OYILLG?")
# result = {"board":..., "rack":..., "moves":[...], "notes":"", "tiles_on_board":N}
```

---

## Crossplay vs Scrabble

| Difference | Scrabble | Crossplay |
|------------|----------|-----------|
| Bingo bonus | 50 pts | 40 pts |
| Tile values | Standard | Different (e.g. H=3, V=6, W=5) |
| Bonus layout | Standard symmetric pattern | Different positions |

Both tile values and bonus positions are hardcoded as `frozenset` constants in `engine.py` and verified against the official blank Crossplay board.

---

## Architecture notes

### Why `SolverService` instead of direct engine calls?

Previously `server.py` called `find_top_moves` and `load_word_list` directly. This made three things hard:

1. **Testing** — you had to touch the filesystem to swap in a small word set.
2. **Caching** — the DAWG rebuild on every restart was impossible to optimise without leaking disk logic into the server.
3. **Replaceability** — swapping the engine (e.g. for a Rust extension) required changing `server.py`.

`SolverService` solves all three: inject it in tests, hide caching inside it, replace just it when swapping engines.

### Why `WordListError` instead of `sys.exit`?

`sys.exit` in a library function makes code untestable without process-level tricks. `WordListError` (a `FileNotFoundError` subclass) lets the server log a clean message, lets tests assert on it directly, and lets future callers handle it however they want.

### Why is the HTML inlined in `server.py`?

The tool runs with a single `python crossplay_solver.py` command and zero build steps. Keeping the UI in the same file makes distribution trivial — one directory, four `.py` files, one word list. The HTML is at the *bottom* of the file so the Python logic is always visible first.
