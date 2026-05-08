# Crossplay Board Solver 🎮

A Python tool that analyzes a photo of your **NYT Crossplay** game board and suggests the **top 5 highest-scoring moves** you can make.

---

## What It Does

1. **Takes a screenshot/photo** of your Crossplay board
2. **Uses Claude Vision API** to read all the tiles on the board (no manual entry!)
3. **Calculates every valid word** you can form with your rack
4. **Scores each move** using Crossplay's unique tile values and bonus squares
5. **Returns the top 5 plays** ranked by points

---

## Setup

### 1. Install dependencies

```bash
pip install anthropic
```

### 2. Set your Anthropic API key

```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Get a key at: https://console.anthropic.com/

### 3. (Recommended) Add a word list

Download a large word list for maximum accuracy:

```bash
# Option A — enable1 word list (~172k words, good NWL coverage)
curl -O https://raw.githubusercontent.com/dolph/dictionary/master/enable1.txt

# Option B — SOWPODS (~267k words)
# Search for "sowpods.txt" and place in the same folder

# Option C — system dictionary (auto-detected on Linux/macOS)
# /usr/share/dict/words is used automatically if found
```

Place any word file named `words.txt`, `enable1.txt`, `twl06.txt`, or `sowpods.txt`
in the same directory as `crossplay_solver.py`.

Without a word file, the tool uses a built-in fallback set (~400 common words).

---

## Usage

### Basic — image + rack tiles

```bash
python crossplay_solver.py board.png KVANEST
```

### If your rack is visible in the screenshot

```bash
# Claude will auto-detect rack tiles from the image
python crossplay_solver.py board.png
```

### With spaces in rack letters

```bash
python crossplay_solver.py board.jpg "K V A N E S T"
```

### Show top 10 moves instead of 5

```bash
python crossplay_solver.py board.png KVANEST --top 10
```

### Skip Claude vision (empty board / first move only)

```bash
python crossplay_solver.py dummy.png KVANEST --no-vision
```

---

## Example Output

```
📷 Analyzing board image: board.png
   (Sending to Claude Vision API...)
✓ Board parsed: 23 tiles on board
✓ Rack detected from image: K V A N E S T

🔎 Searching for best moves with rack: K V A N E S T
   Word list size: 172,820 words

============================================================
  🎮  CROSSPLAY MOVE ANALYZER — TOP 5 PLAYS
============================================================
  Your rack: K V A N E S T
------------------------------------------------------------
  #1  THANKS          D8 →   Score:   38 pts ⭐ Great play
  #2  SKATE           H4 ↓   Score:   32 pts
  #3  TANK            F7 →   Score:   28 pts
  #4  VANES           J5 →   Score:   26 pts
  #5  STAKE           C11 ↓  Score:   24 pts
============================================================
```

---

## Crossplay Tile Values

| Letters | Points |
|---------|--------|
| A, E, I, L, N, O, R, S, T, U | 1 pt |
| D, G | 2 pts |
| B, C, F, H, M, P, Y | 3–4 pts |
| K, V | 5–6 pts |
| W | 5 pts |
| J, X | 8 pts |
| Q, Z | 10 pts |
| Blank (?) | 0 pts |

**Bingo Bonus:** Play all 7 tiles = +40 points!

---

## Board Multipliers

| Square | Effect |
|--------|--------|
| 2L | Double letter score |
| 3L | Triple letter score |
| 2W | Double word score |
| 3W | Triple word score |

---

## Tips for Best Results

- **Take a clear, straight-on photo** of the board (avoid angles)
- **Good lighting** helps Claude read the tiles accurately
- **Include your rack** in the screenshot if possible (bottom of screen)
- **Use a large word list** file for the best move suggestions
- If a suggested move is rejected by the app, try the next one — Crossplay's word list is curated

---

## Architecture

```
board photo
    │
    ▼
Claude Vision API  ──►  15×15 grid JSON
    │
    ▼
Board Parser  ──►  Board object
    │
    ├── Word List (NWL23-compatible)
    │
    ▼
Anchor-based Move Finder
    │   • Tries all words × all positions × both directions
    │   • Scores: tile values + letter/word multipliers + cross-words + bingo bonus
    │
    ▼
Top 5 Moves (sorted by score)
```
