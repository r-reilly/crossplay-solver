"""
crossplay_solver.py — Entry point for the Crossplay Solver.

This file is intentionally minimal.  All game logic lives in engine.py;
all HTTP and UI concerns live in server.py.  This script exists purely so
users can type:

    python crossplay_solver.py

instead of the less intuitive:

    python server.py

For programmatic use, import engine or server directly:

    from engine import Board, build_dawg, find_top_moves, load_word_list
    from server import run_server, solve
"""

from server import _parse_args, run_server

if __name__ == "__main__":
    args = _parse_args()
    run_server(port=args.port, open_browser=not args.no_browser)
