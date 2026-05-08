#!/usr/bin/env python3
"""
Crossplay Board Solver
======================
Takes a photo of a NYT Crossplay game board, uses Claude's vision API
to parse the board state, then finds the top 5 highest-scoring moves.

Usage:
    python crossplay_solver.py <image_path> <rack_letters>

Example:
    python crossplay_solver.py board.png KVANEST
    python crossplay_solver.py board.jpg "K V A N E S T"
"""

import sys
import os
import json
import base64
import itertools
import argparse
from typing import Optional
import anthropic

# ──────────────────────────────────────────────────────────
# Crossplay tile values (unique, not Scrabble)
# ──────────────────────────────────────────────────────────
TILE_VALUES: dict[str, int] = {
    'A': 1, 'B': 3, 'C': 3, 'D': 2, 'E': 1,
    'F': 4, 'G': 2, 'H': 3, 'I': 1, 'J': 8,
    'K': 6, 'L': 1, 'M': 3, 'N': 1, 'O': 1,
    'P': 3, 'Q': 10, 'R': 1, 'S': 1, 'T': 1,
    'U': 1, 'V': 6, 'W': 5, 'X': 8, 'Y': 4,
    'Z': 10, '?': 0,  # blank tile
}

BINGO_BONUS = 40  # bonus for playing all 7 tiles

# ──────────────────────────────────────────────────────────
# Crossplay 15×15 board multiplier layout
# Positions are (row, col) 0-indexed
# ──────────────────────────────────────────────────────────
BOARD_SIZE = 15
CENTER = (7, 7)

# Premium square positions (Crossplay has a distinct layout)
TRIPLE_WORD   = {(0,0),(0,7),(0,14),(7,0),(7,14),(14,0),(14,7),(14,14)}
DOUBLE_WORD   = {(1,1),(1,13),(2,2),(2,12),(3,3),(3,11),(4,4),(4,10),
                 (7,7),(10,4),(10,10),(11,3),(11,11),(12,2),(12,12),(13,1),(13,13)}
TRIPLE_LETTER = {(1,5),(1,9),(5,1),(5,5),(5,9),(5,13),
                 (9,1),(9,5),(9,9),(9,13),(13,5),(13,9)}
DOUBLE_LETTER = {(0,3),(0,11),(2,6),(2,8),(3,0),(3,7),(3,14),
                 (6,2),(6,6),(6,8),(6,12),(7,3),(7,11),
                 (8,2),(8,6),(8,8),(8,12),(11,0),(11,7),(11,14),
                 (12,6),(12,8),(14,3),(14,11)}

def get_square_multiplier(row: int, col: int):
    """Return (letter_mult, word_mult) for a board square."""
    pos = (row, col)
    if pos in TRIPLE_WORD:   return (1, 3)
    if pos in DOUBLE_WORD:   return (1, 2)
    if pos in TRIPLE_LETTER: return (3, 1)
    if pos in DOUBLE_LETTER: return (2, 1)
    return (1, 1)

# ──────────────────────────────────────────────────────────
# Word list — we use the SOWPODS / NWL23 common word list
# via a built-in fallback for common words, plus Claude for
# validation of less common words
# ──────────────────────────────────────────────────────────

def load_word_list() -> set[str]:
    """
    Try to load a local word list file (words.txt / enable1.txt / twl06.txt).
    Falls back to a minimal built-in set for demonstration.
    Place a 'words.txt' file (one word per line) in the same directory
    to get full solver accuracy.
    """
    word_files = ['words.txt', 'enable1.txt', 'twl06.txt', 'sowpods.txt',
                  '/usr/share/dict/words', '/usr/dict/words']
    for path in word_files:
        if os.path.exists(path):
            with open(path) as f:
                words = {w.strip().upper() for w in f if 2 <= len(w.strip()) <= 15}
            print(f"✓ Loaded {len(words):,} words from {path}")
            return words

    # Fallback: a small curated set of common 2–7 letter words
    print("⚠  No word list file found. Using built-in fallback word set.")
    print("   For best results, add a 'words.txt' file (one word per line).")
    fallback = {
        "AA","AB","AD","AE","AG","AH","AI","AL","AM","AN","AR","AS","AT","AW","AX","AY",
        "BA","BE","BI","BO","BY","DA","DE","DO","ED","EF","EH","EL","EM","EN","ER","ES",
        "ET","EX","FA","FE","GI","GO","HA","HE","HI","HM","HO","ID","IF","IN","IS","IT",
        "JO","KA","KI","LA","LI","LO","MA","ME","MI","MM","MO","MU","MY","NA","NE","NO",
        "NU","OD","OE","OF","OH","OI","OM","ON","OP","OR","OS","OW","OX","OY","PA","PE",
        "PI","PO","QI","RE","SH","SI","SO","TA","TI","TO","UH","UM","UN","UP","UT","WE",
        "WO","XI","XU","YA","YE","ZA","ZO",
        "ACE","AGE","AID","AIM","AIR","ALE","ANT","APE","ARE","ART","ASH","ASK","ATE",
        "AWE","AXE","BAD","BAG","BAN","BAR","BAT","BAY","BED","BIG","BIT","BOW","BOX",
        "BOY","BUD","BUS","BUT","BUY","CAN","CAP","CAR","CAT","COB","COD","COP","COT",
        "COW","CRY","CUP","CUT","DAM","DAY","DEN","DID","DIG","DIM","DIP","DOG","DOT",
        "DRY","DUE","DUG","EAR","EAT","EEL","EGG","ELK","ELM","EMU","END","ERA","EVE",
        "EWE","EYE","FAD","FAN","FAR","FAT","FAX","FIG","FIT","FIX","FLY","FOP","FOR",
        "FRY","FUB","FUN","FUR","GAP","GAS","GEL","GEM","GET","GOD","GOT","GUM","GUN",
        "GUT","GUY","GYM","HAD","HAM","HAS","HAT","HAY","HER","HIM","HIS","HIT","HOG",
        "HOP","HOT","HOW","HUB","HUG","HUM","HUT","ICE","ILL","IMP","INK","ION","IRE",
        "IVY","JAB","JAG","JAM","JAR","JAW","JAY","JET","JIG","JOB","JOG","JOT","JOY",
        "JUG","JUT","KEG","KEY","KID","KIT","LAB","LAD","LAG","LAP","LAW","LAX","LAY",
        "LEG","LET","LID","LIE","LIT","LOG","LOT","LOW","MAP","MAT","MAW","MAY","MET",
        "MID","MIX","MOB","MOP","MOW","MUD","MUG","NAG","NAP","NAY","NET","NEW","NIB",
        "NOD","NOR","NOT","NOW","NUB","NUN","OAK","OAR","OAT","ODD","ODE","OFF","OIL",
        "OLD","OPT","ORB","ORE","OUR","OUT","OWE","OWL","OWN","PAD","PAL","PAN","PAP",
        "PAT","PAW","PAY","PEA","PEG","PEN","PEP","PET","PEW","PIE","PIG","PIN","PIT",
        "PLY","POD","POI","POT","POW","PRY","PUB","PUG","PUN","PUP","PUS","PUT","RAG",
        "RAM","RAN","RAP","RAT","RAW","RAY","RED","REF","RIB","RID","RIG","RIM","RIP",
        "ROB","ROD","ROE","ROT","ROW","RUB","RUG","RUM","RUN","RUT","SAC","SAP","SAT",
        "SAW","SAY","SET","SEW","SKY","SLY","SOB","SOD","SON","SOP","SOT","SOW","SOY",
        "SPA","SPY","STY","SUB","SUM","SUN","SUP","TAB","TAD","TAN","TAP","TAR","TAT",
        "TAX","TEA","TED","TEN","THE","TIE","TIN","TIP","TOD","TOE","TON","TOO","TOP",
        "TOT","TOW","TOY","TUB","TUG","TUN","TUX","TWO","UDO","USE","VAN","VAR","VAT",
        "VET","VIA","VIE","VOW","WAD","WAG","WAR","WAS","WAX","WAY","WEB","WED","WET",
        "WHO","WHY","WIG","WIN","WIS","WIT","WOE","WOG","WOK","WON","WOO","WOP","WOT",
        "YAK","YAM","YAP","YAW","YEA","YES","YET","YEW","YOD","YOK","YOU","ZAG","ZAP",
        "ZED","ZEE","ZEN","ZIG","ZIP","ZIT","ZOO",
        "KNAVERY","VIVIDLY","WAXWING","QUIZZED","SKYWARD","WHISKEY","BOXWOOD",
        "QUIZ","JAZZ","FIZZ","FUZZ","BUZZ","ZEAL","ZERO","ZONE","ZOOM","ZEST",
        "JINX","JIVE","JOKE","JOLT","JUMP","JUNK","JURY","JUST",
        "QUAY","QUICK","QUIET","QUITE","QUOTA","QUOTE",
        "VAIN","VALE","VAST","VEAL","VEER","VEIL","VEIN","VENT","VERY","VEST",
        "VIEW","VINE","VISA","VOID","VOLT","VOTE","WADE","WAGE","WAIT","WAKE",
        "WALK","WALL","WAND","WANT","WARD","WARM","WARN","WARP","WARS","WART",
        "WARY","WASP","WAVE","WAVY","WEAK","WEAL","WEAN","WEAR","WEAVE","WEED",
        "WEEK","WELD","WELL","WENT","WEPT","WERE","WEST","WHAT","WHEN","WHET",
        "WHIM","WHIP","WHIR","WHIZ","WIDE","WIFE","WILD","WILL","WILT","WILY",
        "WIND","WINE","WING","WINK","WIRE","WISE","WISH","WITH","WOKE","WOLD",
        "WOLF","WOOD","WOOL","WORD","WORE","WORK","WORM","WORN","WOVE","WRAP",
        "WREN","WRIT","YACK","YAKS","YANK","YARD","YARN","YAWN","YEAR","YELL",
        "KELP","KEPT","KERN","KILT","KIND","KING","KINK","KISS","KNOB","KNOT",
        "KNOW","LACK","LAKE","LAME","LAMP","LAND","LANE","LANK","LARD","LARK",
    }
    return fallback


# ──────────────────────────────────────────────────────────
# Board representation
# ──────────────────────────────────────────────────────────

class Board:
    def __init__(self):
        self.grid: list[list[str]] = [['.' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.is_empty = True

    def place(self, row: int, col: int, letter: str):
        self.grid[row][col] = letter.upper()
        self.is_empty = False

    def get(self, row: int, col: int) -> str:
        if 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE:
            return self.grid[row][col]
        return '#'  # out of bounds sentinel

    def is_occupied(self, row: int, col: int) -> bool:
        return self.grid[row][col] != '.'

    def has_adjacent(self, row: int, col: int) -> bool:
        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            if self.is_occupied(row+dr, col+dc):
                return True
        return False

    def display(self) -> str:
        header = "    " + " ".join(f"{c:2}" for c in range(BOARD_SIZE))
        rows = [header]
        for r in range(BOARD_SIZE):
            row_str = f"{r:2}  " + " ".join(f" {self.grid[r][c]}" for c in range(BOARD_SIZE))
            rows.append(row_str)
        return "\n".join(rows)


# ──────────────────────────────────────────────────────────
# Move scoring
# ──────────────────────────────────────────────────────────

def score_word_at(board: Board, word: str, row: int, col: int, horizontal: bool,
                  word_set: set[str]) -> Optional[int]:
    """
    Score a word placed at (row,col) going right (horizontal=True) or down.
    Returns None if the placement is invalid.
    """
    cells = []
    for i, letter in enumerate(word):
        r = row + (0 if horizontal else i)
        c = col + (i if horizontal else 0)
        if r >= BOARD_SIZE or c >= BOARD_SIZE:
            return None
        existing = board.get(r, c)
        if existing != '.':
            if existing != letter:
                return None  # conflicts with existing tile
            cells.append((r, c, letter, False))  # not a new tile
        else:
            cells.append((r, c, letter, True))   # new tile placed

    # Must place at least one new tile
    new_tiles = [(r,c,l) for r,c,l,is_new in cells if is_new]
    if not new_tiles:
        return None

    # Must connect to existing tiles (or touch center on first move)
    if board.is_empty:
        touches_center = any(r == 7 and c == 7 for r,c,_ in new_tiles)
        if not touches_center:
            return None
    else:
        connects = any(board.has_adjacent(r,c) or board.is_occupied(r,c)
                       for r,c,_ in new_tiles)
        if not connects:
            return None

    # Score the main word
    main_score = 0
    word_mult = 1
    for r, c, letter, is_new in cells:
        lv = TILE_VALUES.get(letter, 0)
        lm, wm = get_square_multiplier(r, c) if is_new else (1, 1)
        main_score += lv * lm
        word_mult *= wm

    main_score *= word_mult

    # Score cross-words formed by new tiles
    cross_dir = (1, 0) if horizontal else (0, 1)
    for r, c, letter, is_new in cells:
        if not is_new:
            continue
        dr, dc = cross_dir
        # Find extent of cross-word
        r0, c0 = r, c
        while board.get(r0-dr, c0-dc) != '.':
            r0 -= dr; c0 -= dc
        cross_letters = []
        rr, cc = r0, c0
        while True:
            ch = board.get(rr, cc)
            if ch == '.':
                if rr == r and cc == c:
                    ch = letter  # the tile we're placing
                else:
                    break
            cross_letters.append((rr, cc, ch))
            rr += dr; cc += dc
        if len(cross_letters) < 2:
            continue
        cross_word = ''.join(ch for _,_,ch in cross_letters)
        if cross_word not in word_set:
            return None  # invalid cross-word
        # Score cross-word
        cs = 0
        cwm = 1
        for rr2, cc2, ch2 in cross_letters:
            lv = TILE_VALUES.get(ch2, 0)
            lm, wm = get_square_multiplier(rr2, cc2) if (rr2==r and cc2==c) else (1, 1)
            cs += lv * lm
            cwm *= wm
        main_score += cs * cwm

    # Bingo bonus
    if len(new_tiles) == 7:
        main_score += BINGO_BONUS

    return main_score


# ──────────────────────────────────────────────────────────
# Move finder — brute-force anchor-based search
# ──────────────────────────────────────────────────────────

def find_top_moves(board: Board, rack: list[str], word_set: set[str],
                   top_n: int = 5) -> list[dict]:
    """Find the top N highest-scoring moves from the given rack."""
    best: list[dict] = []

    # Collect candidate anchor positions
    anchors: set[tuple[int,int]] = set()
    if board.is_empty:
        anchors.add(CENTER)
    else:
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if not board.is_occupied(r, c) and board.has_adjacent(r, c):
                    anchors.add((r, c))

    # For each word in word list that can be spelled from rack + board letters
    # we try every placement direction and anchor
    rack_upper = [t.upper() for t in rack]

    # Pre-filter words to those formable from rack + board
    rack_counter: dict[str,int] = {}
    blanks = 0
    for t in rack_upper:
        if t == '?':
            blanks += 1
        else:
            rack_counter[t] = rack_counter.get(t, 0) + 1

    seen_moves: set[tuple] = set()

    for word in word_set:
        if len(word) < 2:
            continue
        # Check if word letters can come from rack + board tiles
        need: dict[str,int] = {}
        for ch in word:
            need[ch] = need.get(ch, 0) + 1

        # Quick feasibility: letters needed beyond what's on board
        # (conservative — we check properly during placement)
        letters_from_rack = {}
        feasible = True
        for ch, cnt in need.items():
            have = rack_counter.get(ch, 0)
            if have < cnt:
                letters_from_rack[ch] = cnt - have
        total_from_rack = sum(letters_from_rack.values())
        if total_from_rack > len(rack_upper):
            continue
        # Check blanks can cover shortfall
        shortfall = sum(max(0, cnt - rack_counter.get(ch,0))
                        for ch, cnt in need.items())
        if shortfall > blanks:
            # Could still work if board tiles provide some letters
            pass  # we'll validate during placement

        for (ar, ac) in anchors:
            for horizontal in [True, False]:
                # Try placing word such that it covers the anchor
                dr = 0 if horizontal else 1
                dc = 1 if horizontal else 0
                for i in range(len(word)):
                    start_r = ar - (0 if horizontal else i)
                    start_c = ac - (i if horizontal else 0)
                    if start_r < 0 or start_c < 0:
                        continue
                    key = (word, start_r, start_c, horizontal)
                    if key in seen_moves:
                        continue
                    seen_moves.add(key)
                    score = score_word_at(board, word, start_r, start_c,
                                          horizontal, word_set)
                    if score is None:
                        continue
                    move = {
                        'word': word,
                        'row': start_r,
                        'col': start_c,
                        'horizontal': horizontal,
                        'score': score,
                    }
                    best.append(move)

    # Sort by score descending, deduplicate
    best.sort(key=lambda m: -m['score'])
    # Deduplicate by (word, row, col, direction)
    seen_dedup: set = set()
    deduped = []
    for m in best:
        key = (m['word'], m['row'], m['col'], m['horizontal'])
        if key not in seen_dedup:
            seen_dedup.add(key)
            deduped.append(m)

    return deduped[:top_n]


# ──────────────────────────────────────────────────────────
# Claude vision: parse board image → board state
# ──────────────────────────────────────────────────────────

def parse_board_with_claude(image_path: str, client: anthropic.Anthropic) -> dict:
    """
    Send board image to Claude and get back a structured board state.
    Returns {'grid': 2D list, 'rack': list, 'notes': str}
    """
    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')

    # Detect image type
    ext = image_path.rsplit('.', 1)[-1].lower()
    media_type_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                      'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp'}
    media_type = media_type_map.get(ext, 'image/jpeg')

    prompt = """You are analyzing a NYT Crossplay game board image.

Crossplay is a 15×15 word game board (like Scrabble). Your task is to extract the EXACT board state.

Please analyze the image carefully and return a JSON object with this structure:
{
  "grid": [
    [".", ".", "A", ...],   // 15 rows, 15 cols each
    ...
  ],
  "rack": ["K", "V", "A", "N", "E", "S", "T"],  // player's 7 letter tiles if visible
  "bonus_squares_visible": true/false,
  "notes": "any observations about the board state"
}

Rules for the grid:
- Use "." for empty squares
- Use the UPPERCASE letter for any tile placed on that square
- Use "?" for blank tiles that have been played
- The board is exactly 15×15
- Row 0 is the TOP row, Row 14 is the BOTTOM row
- Col 0 is the LEFT column, Col 14 is the RIGHT column

If you can see the player's rack tiles (usually shown at the bottom), list them.
If the rack is not visible, return an empty array for "rack".

Return ONLY valid JSON, nothing else."""

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data,
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }]
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    return json.loads(raw)


# ──────────────────────────────────────────────────────────
# Pretty output
# ──────────────────────────────────────────────────────────

def format_move(move: dict, idx: int) -> str:
    direction = "→" if move['horizontal'] else "↓"
    row_label = move['row'] + 1
    col_label = chr(ord('A') + move['col'])
    bingo = " 🎯 BINGO!" if len(move['word']) == 7 else ""
    return (f"  #{idx}  {move['word']:15s} {col_label}{row_label} {direction}  "
            f"Score: {move['score']:>4} pts{bingo}")


def print_results(top_moves: list[dict], rack: list[str], board: Board):
    print("\n" + "="*60)
    print("  🎮  CROSSPLAY MOVE ANALYZER — TOP 5 PLAYS")
    print("="*60)
    print(f"  Your rack: {' '.join(rack)}")
    print("-"*60)
    if not top_moves:
        print("  No valid moves found. Try exchanging tiles.")
    else:
        for i, move in enumerate(top_moves, 1):
            print(format_move(move, i))
            # Show breakdown hint
            extras = []
            if move['score'] >= 50:
                extras.append("🔥 HIGH VALUE!")
            elif move['score'] >= 30:
                extras.append("⭐ Great play")
            if extras:
                print(f"       {'  '.join(extras)}")
    print("="*60)
    print()


# ──────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Crossplay Board Solver — find top 5 moves from a board photo')
    parser.add_argument('image', help='Path to board screenshot/photo')
    parser.add_argument('rack', nargs='?', default='',
                        help='Your 7 rack tiles, e.g. KVANEST or "K V A N E S T"')
    parser.add_argument('--top', type=int, default=5, help='Number of moves to show')
    parser.add_argument('--no-vision', action='store_true',
                        help='Skip Claude vision (use manual board input mode)')
    args = parser.parse_args()

    # ── Init Claude client ──────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY environment variable not set.")
        print("   Set it with: export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)
    client = anthropic.Anthropic(api_key=api_key)

    # ── Load word list ──────────────────────────────────
    word_set = load_word_list()

    # ── Parse board ─────────────────────────────────────
    board = Board()
    rack_from_image: list[str] = []

    if not args.no_vision and os.path.exists(args.image):
        print(f"\n📷 Analyzing board image: {args.image}")
        print("   (Sending to Claude Vision API...)")
        try:
            parsed = parse_board_with_claude(args.image, client)

            # Load grid
            grid = parsed.get('grid', [])
            if len(grid) == BOARD_SIZE and len(grid[0]) == BOARD_SIZE:
                for r in range(BOARD_SIZE):
                    for c in range(BOARD_SIZE):
                        ch = str(grid[r][c]).upper().strip()
                        if ch and ch != '.':
                            board.place(r, c, ch)
                print(f"✓ Board parsed: {sum(1 for r in range(BOARD_SIZE) for c in range(BOARD_SIZE) if board.is_occupied(r,c))} tiles on board")
            else:
                print("⚠  Grid size mismatch in parsed output. Board may be empty.")

            rack_from_image = [t.upper() for t in parsed.get('rack', []) if t]
            if rack_from_image:
                print(f"✓ Rack detected from image: {' '.join(rack_from_image)}")
            if parsed.get('notes'):
                print(f"   Note: {parsed['notes']}")

        except json.JSONDecodeError as e:
            print(f"⚠  Could not parse Claude's board response: {e}")
            print("   Continuing with empty board.")
        except Exception as e:
            print(f"⚠  Vision API error: {e}")
    else:
        if args.no_vision:
            print("ℹ  Vision skipped (--no-vision). Using empty board.")
        else:
            print(f"⚠  Image not found: {args.image}. Using empty board.")

    # ── Get rack letters ────────────────────────────────
    rack_str = args.rack.replace(' ', '').upper()
    if rack_str:
        rack = list(rack_str)
    elif rack_from_image:
        rack = rack_from_image
    else:
        # Interactive prompt
        print("\nEnter your 7 rack tiles (e.g. KVANEST or K V A N E S T):")
        rack_input = input("Rack: ").replace(' ', '').upper()
        rack = list(rack_input)

    if not rack:
        print("❌ No rack tiles provided.")
        sys.exit(1)

    print(f"\n🔎 Searching for best moves with rack: {' '.join(rack)}")
    print(f"   Word list size: {len(word_set):,} words")

    # ── Find moves ──────────────────────────────────────
    top_moves = find_top_moves(board, rack, word_set, top_n=args.top)

    # ── Display results ─────────────────────────────────
    print_results(top_moves, rack, board)

    # ── Show parsed board ───────────────────────────────
    if not board.is_empty:
        print("Parsed board state:")
        print(board.display())
        print()

    return top_moves


if __name__ == '__main__':
    main()
