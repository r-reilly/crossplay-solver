"""
server.py — Local HTTP server for the Crossplay Solver UI.

Responsibilities
----------------
  - Serve the single-page UI (GET /).
  - Accept board + rack as JSON (POST /solve); delegate to SolverService.
  - Hold a module-level SolverService singleton so the word list and DAWG
    are loaded exactly once per process.

This module is intentionally thin.  All game logic lives in ``engine.py``
and all caching / service-layer decisions live in ``service.py``.

Usage
-----
  Run directly:   python server.py [--port PORT] [--no-browser]
  Import:         from server import run_server   # programmatic startup
"""

from __future__ import annotations

import argparse
import json
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from service import SolverService

# ---------------------------------------------------------------------------
# SolverService singleton
# ---------------------------------------------------------------------------

# The service is loaded once at startup and reused for every request.  It is
# stored at module level so tests can replace it via set_service() without
# touching the filesystem or starting a server.
_service: SolverService | None = None


def get_service() -> SolverService:
    """Return the cached SolverService, building it from disk on first call."""
    global _service
    if _service is None:
        _service = SolverService.from_word_list()
    return _service


def set_service(service: SolverService) -> None:
    """
    Override the module-level service.

    Used in tests to inject a pre-built service with a small word set::

        from engine import build_dawg
        import server

        words = {"GO", "OIL", "LOG"}
        server.set_service(SolverService(words=words, dawg=build_dawg(words)))
    """
    global _service
    _service = service


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class SolverHandler(BaseHTTPRequestHandler):
    """
    Minimal HTTP request handler.

    Routes
    ------
    GET  /       → 200 with the bundled HTML/CSS/JS single-page app
    POST /solve  → 200 with a JSON solve-response (or {"error":"..."} on failure)
    *            → 404
    """

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # suppress the default per-request console noise

    def do_GET(self) -> None:
        body = _UI_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type",   "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/solve":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length))
            result  = get_service().solve(
                grid_data=payload.get("grid", []),
                rack_str=payload.get("rack", ""),
            )
        except Exception as exc:
            traceback.print_exc()
            result = {"error": str(exc)}

        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ReuseAddrServer(HTTPServer):
    """HTTPServer with SO_REUSEADDR so restarts don't block on TIME_WAIT."""
    allow_reuse_address = True


# ---------------------------------------------------------------------------
# Public server entry point
# ---------------------------------------------------------------------------

def run_server(port: int = 8080, open_browser: bool = True) -> None:
    """
    Start the HTTP server and (optionally) open the browser.

    Blocks until Ctrl+C is pressed.

    Parameters
    ----------
    port:         TCP port to listen on.
    open_browser: Open http://localhost:<port> in the default browser.
    """
    # Pre-load so the first browser request is instant.
    get_service()

    server = _ReuseAddrServer(("localhost", port), SolverHandler)
    url    = f"http://localhost:{port}"
    print(f"\n  Crossplay Solver  →  {url}")
    print("  Press Ctrl+C to stop.\n")

    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=[url]).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crossplay Solver — local web UI")
    parser.add_argument("--port",       type=int, default=8080,
                        help="Port to listen on (default: 8080)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not open a browser tab on startup")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_server(port=args.port, open_browser=not args.no_browser)


# ---------------------------------------------------------------------------
# Inline UI — HTML/CSS/JS bundled so the tool needs no build step.
# Kept at the bottom so the Python logic is always visible at the top.
# ---------------------------------------------------------------------------

_UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crossplay Solver</title>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crossplay Solver</title>
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
<style>
:root {
  --bg:       #fafafa;
  --surface:  #ffffff;
  --border:   #e5e5e5;
  --border-2: #d4d4d4;
  --text-1:   #0a0a0a;
  --text-2:   #525252;
  --text-3:   #a3a3a3;
  --accent:   #0a0a0a;
  --accent-fg:#ffffff;
  --tile:     #1a1a2e;
  --tile-fg:  #ffffff;
  --tile-val: #6b7baa;
  --hl:       #0a0a0a;
  --hl-fg:    #ffffff;
  --tw-bg:    #fef2f2; --tw-c: #dc2626;
  --dw-bg:    #fef9ee; --dw-c: #d97706;
  --tl-bg:    #f0fdf4; --tl-c: #16a34a;
  --dl-bg:    #eff6ff; --dl-c: #2563eb;
  --star-bg:  #f5f3ff; --star-c:#7c3aed;
  --danger:   #dc2626;
  --success:  #16a34a;
  --radius:   8px;
  --radius-lg:12px;
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#0a0a0a; --surface:#141414; --border:#262626; --border-2:#333;
    --text-1:#fafafa; --text-2:#a3a3a3; --text-3:#525252;
    --accent:#fafafa; --accent-fg:#0a0a0a;
    --tile:#1e2a4a; --tile-fg:#e2e8f0; --tile-val:#4a5780;
    --hl:#f5f5f5; --hl-fg:#0a0a0a;
    --tw-bg:#2d1414; --tw-c:#f87171;
    --dw-bg:#2d2310; --dw-c:#fbbf24;
    --tl-bg:#0f2d18; --tl-c:#4ade80;
    --dl-bg:#0f1e2d; --dl-c:#60a5fa;
    --star-bg:#1e1430; --star-c:#a78bfa;
    --danger:#f87171; --success:#4ade80;
  }
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{width:100%;min-height:100vh;background:var(--bg)}
body{
  font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;
  font-size:14px;line-height:1.5;
  color:var(--text-1);
}
a{color:inherit}

/* ── Typography ── */
.t-label{font-size:11px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3)}
.t-body{font-size:13px;color:var(--text-2);line-height:1.6}
.t-mono{font-family:'SF Mono','Fira Code',Consolas,monospace}

/* ── Layout ── */
.app{width:100%;padding:0 32px 64px}

header{
  display:flex;align-items:center;justify-content:space-between;
  padding:24px 0 20px;
  border-bottom:1px solid var(--border);
  margin-bottom:32px;
}
.logo{display:flex;align-items:center;gap:10px}
.logo-mark{
  width:28px;height:28px;background:var(--accent);
  border-radius:6px;
  display:flex;align-items:center;justify-content:center;
  flex-shrink:0;
}
.logo-mark svg{color:var(--accent-fg)}
.logo-name{font-size:15px;font-weight:600;letter-spacing:-.01em;color:var(--text-1)}
.logo-tag{font-size:11px;color:var(--text-3);margin-left:2px}
.status-pill{
  display:flex;align-items:center;gap:6px;
  padding:4px 10px;border-radius:20px;
  border:1px solid var(--border);
  font-size:11px;font-weight:500;color:var(--text-3);
  transition:all .2s;
}
.status-pill.active{border-color:#d1fae5;color:var(--success);background:#f0fdf4}
.status-pill.active .dot{background:var(--success)}
@media(prefers-color-scheme:dark){
  .status-pill.active{background:#0f2d18;border-color:#1a4d28}
}
.dot{width:6px;height:6px;border-radius:50%;background:var(--text-3);transition:background .2s}

/* ── Two-col layout ── */
.cols{display:grid;grid-template-columns:2fr 3fr;gap:32px;align-items:start;min-height:calc(100vh - 120px)}
@media(max-width:960px){.cols{grid-template-columns:1fr;min-height:auto}}

/* ── Input column ── */
.input-col{display:flex;flex-direction:column;gap:16px;height:100%}

/* ── Card ── */
.card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);overflow:hidden;
}
.card.grow{flex:1}
.card-header{
  padding:18px 20px 0;
  display:flex;align-items:center;gap:8px;
}
.card-header svg{color:var(--text-3);flex-shrink:0}
.card-body{padding:12px 16px 16px}
.card-body{padding:12px 20px 20px}
.card-header+.card-body{padding-top:12px}

/* ── Tabs ── */
.tab-bar{display:flex;gap:6px;margin-bottom:12px}
.tab{flex:1;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);
  background:var(--surface);color:var(--text-2);font-size:12px;font-weight:500;
  cursor:pointer;transition:all .12s;text-align:center}
.tab.active{background:var(--text-1);color:var(--accent-fg);border-color:var(--text-1)}
.tab:hover:not(.active){border-color:var(--border-2);color:var(--text-1)}

/* ── Manual board grid ── */
.manual-board-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.manual-col-hdr{display:grid;grid-template-columns:18px repeat(15,1fr);gap:2px;margin-bottom:2px;padding-left:2px}
.manual-col-hdr span{font-size:9px;font-weight:600;color:var(--text-3);text-align:center;letter-spacing:.02em}
.manual-rows{display:flex;flex-direction:column;gap:2px}
.manual-row{display:grid;grid-template-columns:18px repeat(15,1fr);gap:2px}
.manual-row-n{font-size:9px;color:var(--text-3);font-weight:600;display:flex;align-items:center;justify-content:flex-end;padding-right:3px}
.mcell{
  aspect-ratio:1;border:1px solid var(--border);border-radius:3px;
  display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:700;cursor:pointer;
  background:var(--bg);color:var(--text-1);text-transform:uppercase;
  transition:all .08s;position:relative;user-select:none;
  min-width:22px;min-height:22px;
}
.mcell:focus,.mcell.sel{outline:none;border-color:var(--text-1);box-shadow:0 0 0 2px var(--text-1);z-index:2}
.mcell.has-tile{background:var(--tile);color:var(--tile-fg);border-color:var(--tile)}
.mcell.ctw{background:var(--tw-bg);border-color:var(--tw-c);color:var(--tw-c);font-size:8px;font-weight:600}
.mcell.cdw{background:var(--dw-bg);border-color:var(--dw-c);color:var(--dw-c);font-size:8px;font-weight:600}
.mcell.ctl{background:var(--tl-bg);border-color:var(--tl-c);color:var(--tl-c);font-size:8px;font-weight:600}
.mcell.cdl{background:var(--dl-bg);border-color:var(--dl-c);color:var(--dl-c);font-size:8px;font-weight:600}
.mcell.cstar{background:var(--star-bg);border-color:var(--star-c);color:var(--star-c);font-size:12px}
.mcell.highlight-move{background:var(--hl);color:var(--hl-fg);border-color:var(--hl)}

/* ── Drop zone ── */
.dropzone{
  border:1px dashed var(--border-2);border-radius:var(--radius);
  padding:48px 24px;text-align:center;cursor:pointer;
  position:relative;transition:border-color .15s,background .15s;
  background:var(--bg);
}
.dropzone:hover,.dropzone.over{
  border-color:var(--text-1);background:var(--surface);
}
.dropzone input{position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer}
.dropzone svg{color:var(--text-3);margin-bottom:8px;transition:color .15s}
.dropzone:hover svg,.dropzone.over svg{color:var(--text-1)}
.dz-hint{font-size:12px;color:var(--text-3);line-height:1.6}
.dz-name{
  font-size:12px;font-weight:500;color:var(--success);
  margin-top:8px;min-height:16px;
  display:flex;align-items:center;justify-content:center;gap:4px;
}
#preview{
  max-height:280px;max-width:100%;border-radius:6px;
  margin:12px auto 0;display:none;
  border:1px solid var(--border);
}

/* ── Text input ── */
.field-row{display:flex;flex-direction:column;gap:6px}
.field-label{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:500;letter-spacing:.05em;text-transform:uppercase;color:var(--text-3)}
.field-label svg{color:var(--text-3)}
.field-hint{font-size:11px;color:var(--text-3);line-height:1.5}
input.rack{
  width:100%;
  border:1px solid var(--border);border-radius:var(--radius);
  padding:13px 14px;
  background:var(--bg);color:var(--text-1);
  font-family:'SF Mono','Fira Code',Consolas,monospace;
  font-size:16px;font-weight:500;letter-spacing:.18em;text-transform:uppercase;
  outline:none;transition:border-color .15s;
}
input.rack::placeholder{color:var(--text-3);letter-spacing:.05em;font-size:13px;font-family:inherit}
input.rack:focus{border-color:var(--text-1)}

/* ── Solve button ── */
.solve-btn{
  width:100%;padding:14px 16px;
  background:var(--accent);color:var(--accent-fg);
  border:none;border-radius:var(--radius);
  font-size:13px;font-weight:500;letter-spacing:.02em;
  cursor:pointer;transition:opacity .15s;
  display:flex;align-items:center;justify-content:center;gap:8px;
}
.solve-btn:hover{opacity:.85}
.solve-btn:active{opacity:.7}
.solve-btn:disabled{opacity:.35;cursor:not-allowed}

/* ── Inline status ── */
.inline-status{
  display:flex;align-items:center;gap:6px;
  font-size:12px;color:var(--text-3);
  min-height:20px;padding:0 2px;
}
.inline-status.ok{color:var(--success)}
.inline-status.err{color:var(--danger)}
.spin{
  width:12px;height:12px;border:1.5px solid var(--border-2);
  border-top-color:var(--text-1);border-radius:50%;
  animation:spin .6s linear infinite;flex-shrink:0;
}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── Results col ── */
.results-col{display:flex;flex-direction:column;gap:16px}

/* ── Rack tiles ── */
.rack-row{display:flex;gap:6px;flex-wrap:wrap}
.tile{
  width:36px;height:42px;
  background:var(--tile);border-radius:5px;
  border-bottom:3px solid rgba(0,0,0,.3);
  display:flex;align-items:center;justify-content:center;
  font-size:16px;font-weight:700;color:var(--tile-fg);
  position:relative;flex-shrink:0;letter-spacing:0;
  font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;
}
.tile .val{
  position:absolute;bottom:2px;right:3px;
  font-size:8px;font-weight:500;color:var(--tile-val);
  font-family:'SF Mono','Fira Code',Consolas,monospace;
}
.tile.blank{background:var(--border-2);color:var(--text-2)}

/* ── Move list ── */
.move-list{display:flex;flex-direction:column;gap:6px}
.move-item{
  display:flex;align-items:center;gap:12px;
  padding:12px 14px;border-radius:var(--radius);
  border:1px solid var(--border);cursor:pointer;
  transition:border-color .12s,background .12s;
  background:var(--surface);
  position:relative;
}
.move-item:hover{border-color:var(--border-2)}
.move-item.sel{border-color:var(--text-1);background:var(--bg)}
.move-item::before{
  content:'';position:absolute;left:0;top:8px;bottom:8px;
  width:2px;border-radius:0 2px 2px 0;
  background:transparent;transition:background .12s;
}
.move-item.sel::before{background:var(--text-1)}
.move-rank{
  font-size:12px;font-weight:500;color:var(--text-3);
  min-width:18px;flex-shrink:0;
}
.move-rank.r1{color:var(--text-1)}
.move-rank.r2{color:var(--text-2)}
.move-rank.r3{color:var(--text-2)}
.move-main{flex:1;min-width:0}
.move-word{font-size:15px;font-weight:600;color:var(--text-1);letter-spacing:.01em;line-height:1.2}
.move-pos{font-size:11px;color:var(--text-3);margin-top:2px;font-family:'SF Mono','Fira Code',Consolas,monospace;letter-spacing:.03em}
.move-badges{display:flex;gap:4px;margin-top:5px;flex-wrap:wrap}
.badge{
  font-size:10px;font-weight:500;letter-spacing:.04em;
  padding:2px 6px;border-radius:4px;
  border:1px solid var(--border);color:var(--text-3);
}
.badge-bingo{border-color:#c4b5fd;color:#7c3aed;background:#f5f3ff}
.badge-hot{border-color:#fca5a5;color:#dc2626;background:#fef2f2}
.badge-strong{border-color:#bbf7d0;color:#16a34a;background:#f0fdf4}
@media(prefers-color-scheme:dark){
  .badge-bingo{background:#1e1430;border-color:#4c3080}
  .badge-hot{background:#2d1414;border-color:#6d2020}
  .badge-strong{background:#0f2d18;border-color:#1a5c32}
}
.move-score{
  display:flex;flex-direction:column;align-items:flex-end;
  flex-shrink:0;
}
.score-val{font-size:18px;font-weight:600;color:var(--text-1);line-height:1}
.score-label{font-size:10px;font-weight:500;letter-spacing:.04em;text-transform:uppercase;color:var(--text-3);margin-top:1px}
.empty-state{
  padding:24px 16px;text-align:center;
  font-size:13px;color:var(--text-3);line-height:1.7;
  border:1px dashed var(--border);border-radius:var(--radius);
}
.empty-state svg{color:var(--text-3);margin-bottom:8px}

/* ── Board ── */
.board-outer{overflow-x:auto;padding-bottom:4px}
.board-col-hdr{display:flex;padding-left:26px;margin-bottom:2px;gap:2px}
.board-col-hdr span{
  width:28px;text-align:center;
  font-size:9px;font-weight:500;letter-spacing:.04em;
  color:var(--text-3);flex-shrink:0;
  font-family:'SF Mono','Fira Code',Consolas,monospace;
}
.board-rows{display:flex;flex-direction:column;gap:2px}
.board-row{display:flex;align-items:center;gap:2px}
.row-n{
  width:22px;text-align:right;padding-right:3px;
  font-size:9px;font-weight:500;color:var(--text-3);flex-shrink:0;
  font-family:'SF Mono','Fira Code',Consolas,monospace;
}
.c{
  width:28px;height:28px;border-radius:3px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:700;
  border:1px solid transparent;transition:all .1s;
}
.ce{background:var(--bg);border-color:var(--border)}
.ct{
  background:var(--tile);color:var(--tile-fg);
  border-color:transparent;font-size:12px;
}
.ch{
  background:var(--hl);color:var(--hl-fg);
  border-color:var(--hl);font-size:12px;
  animation:hl-pulse .9s ease-in-out infinite alternate;
}
@keyframes hl-pulse{
  from{opacity:1} to{opacity:.75}
}
.ctw{background:var(--tw-bg);color:var(--tw-c);border-color:transparent;font-size:8px;font-weight:600;letter-spacing:.02em}
.cdw{background:var(--dw-bg);color:var(--dw-c);border-color:transparent;font-size:8px;font-weight:600;letter-spacing:.02em}
.ctl{background:var(--tl-bg);color:var(--tl-c);border-color:transparent;font-size:8px;font-weight:600;letter-spacing:.02em}
.cdl{background:var(--dl-bg);color:var(--dl-c);border-color:transparent;font-size:8px;font-weight:600;letter-spacing:.02em}
.cstar{background:var(--star-bg);color:var(--star-c);font-size:11px}
.board-legend{
  display:flex;flex-wrap:wrap;gap:12px;
  margin-top:14px;padding-top:14px;border-top:1px solid var(--border);
}
.leg-item{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--text-3)}
.leg-swatch{width:14px;height:14px;border-radius:2px;flex-shrink:0}

/* ── Divider ── */
.divider{height:1px;background:var(--border);margin:14px 0}

/* ── Move cards swipeable row ── */
.move-row{
  display:flex;gap:10px;
  overflow-x:auto;scroll-snap-type:x mandatory;
  padding-bottom:8px;scrollbar-width:none;
}
.move-row::-webkit-scrollbar{display:none}
.move-card{
  flex-shrink:0;width:160px;
  scroll-snap-align:start;
  border:1px solid var(--border);border-radius:var(--radius);
  padding:14px;cursor:pointer;transition:all .12s;
  background:var(--surface);position:relative;overflow:hidden;
}
.move-card::before{
  content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:var(--border);transition:background .12s;
}
.move-card:hover{border-color:var(--border-2)}
.move-card.sel{border-color:var(--text-1)}
.move-card.sel::before{background:var(--text-1)}
.move-num{font-size:11px;font-weight:500;color:var(--text-3);margin-bottom:6px}
.move-num.r1{color:var(--text-1)}
.move-card-word{font-size:17px;font-weight:600;color:var(--text-1);letter-spacing:.01em;margin-bottom:4px}
.move-card-pos{font-size:11px;color:var(--text-3);font-family:'SF Mono','Fira Code',Consolas,monospace;margin-bottom:8px}
.move-card-score{font-size:22px;font-weight:600;color:var(--text-1);line-height:1}
.move-card-pts{font-size:10px;font-weight:500;letter-spacing:.05em;text-transform:uppercase;color:var(--text-3);margin-top:1px}
.move-card-badges{display:flex;flex-direction:column;gap:3px;margin-top:6px}

/* ── Section label inside card ── */
.sec-label{
  font-size:11px;font-weight:500;letter-spacing:.06em;
  text-transform:uppercase;color:var(--text-3);
  margin-bottom:10px;
  display:flex;align-items:center;gap:6px;
}
.sec-label svg{color:var(--text-3)}

/* ── Responsive ── */
@media(max-width:600px){
  .app{padding:0 16px 48px}
  .c{width:22px;height:22px;font-size:9px}
  .board-col-hdr span{width:22px}
  .row-n{width:18px}
  .board-col-hdr{padding-left:20px}
}


/* ── Move carousel ── */
.carousel-wrap{position:relative}
.carousel-track{
  display:flex;gap:0;
  overflow-x:auto;scroll-snap-type:x mandatory;
  padding-bottom:8px;scrollbar-width:none;
  scroll-behavior:smooth;
}
.carousel-track::-webkit-scrollbar{display:none}
.carousel-btn{
  position:absolute;top:50%;transform:translateY(-50%);
  width:28px;height:28px;border-radius:50%;
  border:1px solid var(--border-2);background:var(--surface);
  color:var(--text-1);cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  z-index:10;transition:all .12s;
  box-shadow:0 1px 4px rgba(0,0,0,.08);
}
.carousel-btn:hover{background:var(--bg);border-color:var(--text-1)}
.carousel-btn:disabled{opacity:.3;cursor:not-allowed}
.carousel-btn.prev{left:-14px}
.carousel-btn.next{right:-14px}

/* ── Horizontal move card ── */
.move-card{
  flex-shrink:0;
  width:100%;           /* fills the carousel track; track is the true constraint */
  scroll-snap-align:start;
  border:1px solid var(--border);border-radius:var(--radius-lg);
  padding:16px 18px;cursor:pointer;transition:all .12s;
  background:var(--surface);position:relative;overflow:hidden;
}
.move-card::before{
  content:'';position:absolute;top:0;left:0;right:0;height:3px;
  background:var(--border);transition:background .12s;
}
.move-card:hover{border-color:var(--border-2)}
.move-card.sel{border-color:var(--text-1)}
.move-card.sel::before{background:var(--text-1)}

.mc-top{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:8px}
.mc-left{}
.mc-rank{font-size:11px;font-weight:500;color:var(--text-3);margin-bottom:4px}
.mc-rank.r1{color:var(--text-1);font-weight:600}
.mc-word{font-size:22px;font-weight:700;color:var(--text-1);letter-spacing:.01em;line-height:1}
.mc-pos{font-size:11px;color:var(--text-3);margin-top:4px;font-family:'SF Mono','Fira Code',Consolas,monospace}
.mc-right{text-align:right;flex-shrink:0;padding-left:12px}
.mc-score{font-size:28px;font-weight:700;color:var(--text-1);line-height:1}
.mc-pts{font-size:10px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3);margin-top:2px}

.mc-badges{display:flex;gap:4px;margin-bottom:10px;flex-wrap:wrap}

.mc-def-wrap{
  border-top:1px solid var(--border);padding-top:10px;
  min-height:48px;
}
.mc-def-label{font-size:10px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3);margin-bottom:4px}
.mc-def{font-size:12px;color:var(--text-2);line-height:1.55;font-style:italic}
.mc-pos-tag{font-size:10px;font-weight:500;color:var(--text-3);margin-right:4px;font-style:normal;letter-spacing:.04em}
.mc-def-loading{font-size:11px;color:var(--text-3)}

</style>
</head>
<body>
<div class="app">

<header>
  <div class="logo">
    <div class="logo-mark">
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>
    </div>
    <span class="logo-name">Crossplay Solver</span>
  </div>
  <div class="status-pill" id="statusPill">
    <span class="dot" id="statusDot"></span>
    <span id="statusText">Ready</span>
  </div>
</header>

<div class="cols">

  <!-- Left: board entry -->
  <div class="input-col">

    <div class="card">
      <div class="card-body" style="padding:10px 12px">
        <p style="font-size:11px;color:var(--text-3);margin-bottom:8px">Click a cell then type a letter · Backspace to clear · Arrow keys to navigate</p>
        <div class="manual-board-wrap">
          <div class="manual-col-hdr" id="manualColHdr"></div>
          <div class="manual-rows" id="manualRows"></div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
        <span class="t-label">Rack letters</span>
      </div>
      <div class="card-body">
        <input class="rack t-mono" id="rack-manual" placeholder="e.g. OYILLG?" maxlength="9" autocomplete="off" spellcheck="false" oninput="saveBoard()">
        <span class="field-hint" style="display:block;margin-top:6px">Up to 7 letters · use <code style="font-size:10px;padding:1px 3px;background:var(--bg);border:1px solid var(--border);border-radius:3px">?</code> for blank</span>
      </div>
    </div>

    <div class="card">
      <div class="card-body" style="display:flex;gap:8px;align-items:center;padding-top:14px">
        <button class="solve-btn" style="flex:1" onclick="runManual()">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="6 3 20 12 6 21 6 3"/></svg>
          Find best moves
        </button>
        <button onclick="clearManualBoard()" style="padding:10px 14px;border:1px solid var(--border);border-radius:var(--radius);background:var(--surface);color:var(--text-2);font-size:12px;cursor:pointer;white-space:nowrap">Clear board</button>
      </div>
      <div class="inline-status" id="inlineStatusManual" style="margin:8px 16px 12px"></div>
    </div>

  </div>

  <!-- Right: results -->
  <div class="results-col" id="results">

    <!-- Empty state: blank board shown on load -->
    <div id="emptyState">
      <div class="card">
        <div class="card-body">
          <div class="sec-label">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
            Board
          </div>
          <div class="board-outer">
            <div class="board-col-hdr" id="blankColHdrs"></div>
            <div class="board-rows" id="blankBoardRows"></div>
          </div>
          <div class="board-legend">
            <div class="leg-item"><div class="leg-swatch" style="background:var(--tw-bg);border:1px solid var(--tw-c)"></div><span style="color:var(--tw-c);font-weight:500">3W</span></div>
            <div class="leg-item"><div class="leg-swatch" style="background:var(--dw-bg);border:1px solid var(--dw-c)"></div><span style="color:var(--dw-c);font-weight:500">2W</span></div>
            <div class="leg-item"><div class="leg-swatch" style="background:var(--tl-bg);border:1px solid var(--tl-c)"></div><span style="color:var(--tl-c);font-weight:500">3L</span></div>
            <div class="leg-item"><div class="leg-swatch" style="background:var(--dl-bg);border:1px solid var(--dl-c)"></div><span style="color:var(--dl-c);font-weight:500">2L</span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Results: shown after first solve -->
    <div id="resultsInner" style="display:none;flex-direction:column;gap:16px">

      <!-- Rack + move carousel -->
      <div class="card">
        <div class="card-body">
          <div class="sec-label">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>
            Rack
          </div>
          <div class="rack-row" id="rackDiv"></div>
          <div class="divider"></div>
          <div class="sec-label" style="margin-bottom:14px">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            Top moves
          </div>
          <!-- Carousel: arrow buttons sit outside the scrolling track -->
          <div class="carousel-wrap" style="margin:0 20px">
            <button class="carousel-btn prev" id="carouselPrev" onclick="scrollCarousel(-1)" aria-label="Previous move">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
            </button>
            <div class="carousel-track" id="moveDiv"></div>
            <button class="carousel-btn next" id="carouselNext" onclick="scrollCarousel(1)" aria-label="Next move">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
            </button>
          </div>
        </div>
      </div>

      <!-- Result board -->
      <div class="card">
        <div class="card-body">
          <div class="sec-label">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
            Board
          </div>
          <div class="board-outer">
            <div class="board-col-hdr" id="colHdrs"></div>
            <div class="board-rows" id="boardRows"></div>
          </div>
          <div class="board-legend">
            <div class="leg-item"><div class="leg-swatch" style="background:var(--tw-bg);border:1px solid var(--tw-c)"></div><span style="color:var(--tw-c);font-weight:500">3W</span></div>
            <div class="leg-item"><div class="leg-swatch" style="background:var(--dw-bg);border:1px solid var(--dw-c)"></div><span style="color:var(--dw-c);font-weight:500">2W</span></div>
            <div class="leg-item"><div class="leg-swatch" style="background:var(--tl-bg);border:1px solid var(--tl-c)"></div><span style="color:var(--tl-c);font-weight:500">3L</span></div>
            <div class="leg-item"><div class="leg-swatch" style="background:var(--dl-bg);border:1px solid var(--dl-c)"></div><span style="color:var(--dl-c);font-weight:500">2L</span></div>
          </div>
        </div>
      </div>

    </div><!-- /resultsInner -->

  </div><!-- /results-col -->
</div><!-- /cols -->
</div><!-- /app -->

<script>
const TV={A:1,B:3,C:3,D:2,E:1,F:4,G:2,H:3,I:1,J:8,K:6,L:2,M:3,N:1,O:1,P:3,Q:10,R:1,S:1,T:1,U:1,V:6,W:5,X:8,Y:4,Z:10,'?':0};
const TW=new Set('0,3|0,11|3,0|3,14|11,0|11,14|14,3|14,11'.split('|'));
const DW=new Set('1,1|1,13|3,7|7,3|7,11|11,7|13,1|13,13'.split('|'));
const TL=new Set('0,0|0,14|1,6|1,8|4,5|4,9|5,4|5,10|6,1|6,13|8,1|8,13|9,4|9,10|10,5|10,9|13,6|13,8|14,0|14,14'.split('|'));
const DL=new Set('0,7|2,4|2,10|3,3|3,11|4,2|4,12|5,7|7,0|7,5|7,9|7,14|9,7|10,2|10,12|11,3|11,11|12,4|12,10|14,7'.split('|'));

// ── Manual board state ──────────────────────────────────────────────────────
const manualGrid = Array.from({length:15}, () => Array(15).fill(''));
let selectedCell = null;
let board = null;  // most recently solved board state

// Definition cache: word → definition string (avoids redundant API calls).
const defCache = new Map();

// ── Board persistence via localStorage ──────────────────────────────────────
const STORAGE_KEY = 'crossplay_board_v1';

/** Persist current board + rack to localStorage so state survives page reload. */
function saveBoard() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      grid: manualGrid,
      rack: document.getElementById('rack-manual')?.value ?? '',
    }));
  } catch (e) {
    // localStorage can be unavailable in some privacy modes; fail silently.
  }
}

/**
 * Restore board + rack from localStorage.
 * Called once on DOMContentLoaded after the board cells are rendered.
 * Returns true if any saved state was found.
 */
function restoreBoard() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    const { grid, rack } = JSON.parse(raw);
    // Replay each saved tile through setCell so bonus-square classes are correct.
    let restored = false;
    for (let r = 0; r < 15; r++) {
      for (let c = 0; c < 15; c++) {
        const letter = grid?.[r]?.[c] ?? '';
        if (letter) { setCell(r, c, letter); restored = true; }
      }
    }
    if (rack && document.getElementById('rack-manual')) {
      document.getElementById('rack-manual').value = rack;
    }
    return restored;
  } catch (e) {
    return false;
  }
}

function initManualBoard() {
  const colHdr = document.getElementById('manualColHdr');
  colHdr.innerHTML = '<span></span>' + 'ABCDEFGHIJKLMNO'.split('').map(c=>`<span>${c}</span>`).join('');
  const rows = document.getElementById('manualRows');
  rows.innerHTML = '';
  for (let r = 0; r < 15; r++) {
    const row = document.createElement('div');
    row.className = 'manual-row';
    const lbl = document.createElement('div');
    lbl.className = 'manual-row-n';
    lbl.textContent = r+1;
    row.appendChild(lbl);
    for (let c = 0; c < 15; c++) {
      const el = document.createElement('div');
      el.className = 'mcell';
      el.dataset.r = r; el.dataset.c = c;
      el.tabIndex = 0;
      const k = `${r},${c}`;
      if (k==='7,7') el.classList.add('cstar'), el.textContent='★';
      else if (TW.has(k)) el.classList.add('ctw'), el.textContent='3W';
      else if (DW.has(k)) el.classList.add('cdw'), el.textContent='2W';
      else if (TL.has(k)) el.classList.add('ctl'), el.textContent='3L';
      else if (DL.has(k)) el.classList.add('cdl'), el.textContent='2L';
      el.addEventListener('click', () => selectCell(el));
      el.addEventListener('keydown', onCellKey);
      row.appendChild(el);
    }
    rows.appendChild(row);
  }
}

function selectCell(cell) {
  if (selectedCell) selectedCell.classList.remove('sel');
  selectedCell = cell;
  cell.classList.add('sel');
  cell.focus();
}

function getCell(r, c) {
  return document.querySelector(`.mcell[data-r="${r}"][data-c="${c}"]`);
}

function onCellKey(e) {
  const r = parseInt(e.currentTarget.dataset.r), c = parseInt(e.currentTarget.dataset.c);
  if (e.key === 'Backspace' || e.key === 'Delete') {
    e.preventDefault(); setCell(r, c, '');
  } else if (e.key.length === 1 && /[a-zA-Z?]/.test(e.key)) {
    e.preventDefault();
    setCell(r, c, e.key.toUpperCase());
    if (c < 14) selectCell(getCell(r, c+1));
  } else if (e.key === 'ArrowRight') { e.preventDefault(); if(c<14) selectCell(getCell(r,c+1)); }
  else if (e.key === 'ArrowLeft')  { e.preventDefault(); if(c>0)  selectCell(getCell(r,c-1)); }
  else if (e.key === 'ArrowDown')  { e.preventDefault(); if(r<14) selectCell(getCell(r+1,c)); }
  else if (e.key === 'ArrowUp')    { e.preventDefault(); if(r>0)  selectCell(getCell(r-1,c)); }
}

function setCell(r, c, letter) {
  manualGrid[r][c] = letter;
  const el = getCell(r, c);
  if (!el) return;
  el.classList.remove('has-tile','ctw','cdw','ctl','cdl','cstar','highlight-move');
  el.textContent = '';
  if (letter) {
    el.classList.add('has-tile');
    el.textContent = letter;
  } else {
    const k = `${r},${c}`;
    if (k==='7,7') el.classList.add('cstar'), el.textContent='★';
    else if (TW.has(k)) el.classList.add('ctw'), el.textContent='3W';
    else if (DW.has(k)) el.classList.add('cdw'), el.textContent='2W';
    else if (TL.has(k)) el.classList.add('ctl'), el.textContent='3L';
    else if (DL.has(k)) el.classList.add('cdl'), el.textContent='2L';
  }
  saveBoard();
}

function clearManualBoard() {
  for (let r=0;r<15;r++) for (let c=0;c<15;c++) {
    manualGrid[r][c] = '';          // reset data before setCell to avoid redundant saves
  }
  // Now re-render all cells (setCell reads manualGrid, so blank them first)
  for (let r=0;r<15;r++) for (let c=0;c<15;c++) setCell(r,c,'');
  document.getElementById('rack-manual').value='';
  document.getElementById('inlineStatusManual').textContent='';
  document.getElementById('emptyState').style.display='';
  document.getElementById('resultsInner').style.display='none';
  defCache.clear();
  try { localStorage.removeItem(STORAGE_KEY); } catch(e) {}
}

async function runManual() {
  const rack = document.getElementById('rack-manual').value.trim();
  const statusEl = document.getElementById('inlineStatusManual');
  if (!rack) { statusEl.textContent='Enter your rack letters first'; return; }
  const btn = document.querySelector('.solve-btn');
  btn.disabled = true;
  btn.innerHTML='<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> Solving…';
  statusEl.innerHTML = '<span class="spin"></span> Finding moves…';
  try {
    const resp = await fetch('/solve', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({grid: manualGrid, rack})
    });
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    board = data.board;
    render(data);
    statusEl.textContent = '';
  } catch(err) {
    statusEl.textContent = 'Error: '+err.message;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="6 3 20 12 6 21 6 3"/></svg> Find best moves';
  }
}

// ── Definition lookup ───────────────────────────────────────────────────────
/**
 * Fetch the first definition of *word* from the Free Dictionary API.
 * Results are cached in defCache so repeat views of the same card don't
 * fire extra network requests.
 *
 * Returns { pos, definition } or null on any error.
 */
async function fetchDefinition(word) {
  const key = word.toUpperCase();
  if (defCache.has(key)) return defCache.get(key);

  // Try the exact word first, then fall back to the singular (strip trailing S)
  // to handle plurals like QAIDS → QAID when the exact form isn't in the dictionary.
  const attempts = [word.toLowerCase()];
  if (word.length > 2 && word.endsWith('S')) {
    attempts.push(word.slice(0, -1).toLowerCase());
  }

  for (const attempt of attempts) {
    try {
      const resp = await fetch(
        `https://api.dictionaryapi.dev/api/v2/entries/en/${attempt}`
      );
      if (!resp.ok) continue;
      const data = await resp.json();
      const meanings = data[0]?.meanings;
      if (!meanings?.length) continue;
      const m = meanings[0];
      const result = {
        pos:        m.partOfSpeech || '',
        definition: m.definitions[0]?.definition || '',
        // Note when we fell back to the singular form
        lookedUp:   attempt !== word.toLowerCase() ? attempt.toUpperCase() : null,
      };
      defCache.set(key, result);
      return result;
    } catch {
      continue;
    }
  }

  defCache.set(key, null);
  return null;
}

// ── Carousel helpers ────────────────────────────────────────────────────────
function scrollCarousel(direction) {
  const track = document.getElementById('moveDiv');
  const card  = track.querySelector('.move-card');
  if (!card) return;
  // Cards are 100% wide with no gap — scroll exactly one card width
  const cardWidth = card.offsetWidth;
  track.scrollBy({left: direction * cardWidth, behavior:'smooth'});
}

function updateCarouselArrows() {
  const track = document.getElementById('moveDiv');
  const prev  = document.getElementById('carouselPrev');
  const next  = document.getElementById('carouselNext');
  if (!track || !prev || !next) return;
  prev.disabled = track.scrollLeft <= 4;
  next.disabled = track.scrollLeft >= track.scrollWidth - track.clientWidth - 4;
}

// ── Results rendering ───────────────────────────────────────────────────────
function render(data) {
  document.getElementById('emptyState').style.display='none';
  const ri = document.getElementById('resultsInner');
  ri.style.display='flex'; ri.style.flexDirection='column';

  // Render rack tiles
  const rd = document.getElementById('rackDiv');
  rd.innerHTML='';
  (data.rack||[]).forEach(t=>{
    const d = document.createElement('div');
    d.className='tile'+(t==='?'?' blank':'');
    d.innerHTML=t+'<span class="val">'+(TV[t]??0)+'</span>';
    rd.appendChild(d);
  });

  // Render move carousel cards
  const md = document.getElementById('moveDiv');
  md.innerHTML='';
  if (!data.moves||!data.moves.length) {
    md.innerHTML='<p style="font-size:12px;color:var(--text-3);padding:4px 2px">No valid moves found.</p>';
  } else {
    data.moves.forEach((m, i) => {
      const col     = String.fromCharCode(65 + m.col);
      const dir     = m.horizontal ? '→' : '↓';
      const isBingo = m.word.length === 7;
      const card    = buildMoveCard(m, i, col, dir, isBingo);
      md.appendChild(card);
      // Fetch definition asynchronously and populate when ready
      fillDefinition(card, m.word);
    });
    // Activate first card
    md.firstChild?.classList.add('sel');
    if (data.moves.length) {
      drawBoard(data.board, data.moves[0]);
      highlightManualMove(data.moves[0]);
    }
    // Attach scroll listener for arrow state
    md.addEventListener('scroll', updateCarouselArrows, {passive:true});
    updateCarouselArrows();
  }
}

/**
 * Build the DOM element for a single move card.
 * The definition area is rendered as a loading placeholder;
 * fillDefinition() populates it asynchronously.
 */
function buildMoveCard(move, index, col, dir, isBingo) {
  const el = document.createElement('div');
  el.className = 'move-card' + (index === 0 ? ' sel' : '');
  el.innerHTML = `
    <div class="mc-top">
      <div class="mc-left">
        <div class="mc-rank${index===0?' r1':''}">#${index+1}</div>
        <div class="mc-word">${move.word}</div>
        <div class="mc-pos">${col}${move.row+1} ${dir}</div>
      </div>
      <div class="mc-right">
        <div class="mc-score">${move.score}</div>
        <div class="mc-pts">pts</div>
      </div>
    </div>
    ${isBingo ? '<div class="mc-badges"><span class="badge badge-bingo">Bingo +40</span></div>' : ''}
    <div class="mc-def-wrap">
      <div class="mc-def-label">Definition</div>
      <div class="mc-def mc-def-loading" data-word="${move.word}">•••</div>
    </div>`;
  el.addEventListener('click', () => pick(move, index));
  return el;
}

/**
 * Populate the definition area of a card once the API responds.
 * Uses a data-word attribute to match the async result to the correct element.
 */
async function fillDefinition(cardEl, word) {
  const defEl = cardEl.querySelector('.mc-def');
  if (!defEl) return;
  const result = await fetchDefinition(word);
  defEl.classList.remove('mc-def-loading');
  if (!result) {
    defEl.textContent = 'No definition found.';
    defEl.style.color = 'var(--text-3)';
  } else {
    const fallbackNote = result.lookedUp
      ? `<span style="font-size:10px;color:var(--text-3);font-style:normal">(${result.lookedUp}) </span>`
      : '';
    defEl.innerHTML =
      (result.pos ? `<span class="mc-pos-tag">${result.pos}</span>` : '') +
      fallbackNote +
      escapeHtml(result.definition);
  }
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function pick(move, idx) {
  document.querySelectorAll('.move-card').forEach((el,i)=>el.classList.toggle('sel',i===idx));
  drawBoard(board, move);
  highlightManualMove(move);
  document.getElementById('boardRows').scrollIntoView({behavior:'smooth',block:'nearest'});
  updateCarouselArrows();
}

function highlightManualMove(move) {
  // Clear previous highlights first
  document.querySelectorAll('.mcell.highlight-move').forEach(el=>{
    const r=parseInt(el.dataset.r), c=parseInt(el.dataset.c);
    if (!manualGrid[r][c]) {
      el.classList.remove('highlight-move');
      el.textContent='';
      const k=`${r},${c}`;
      if(k==='7,7') el.classList.add('cstar'),el.textContent='★';
      else if(TW.has(k)) el.classList.add('ctw'),el.textContent='3W';
      else if(DW.has(k)) el.classList.add('cdw'),el.textContent='2W';
      else if(TL.has(k)) el.classList.add('ctl'),el.textContent='3L';
      else if(DL.has(k)) el.classList.add('cdl'),el.textContent='2L';
    }
  });
  if (!move) return;
  for (let i=0;i<move.word.length;i++) {
    const r=move.horizontal?move.row:move.row+i;
    const c=move.horizontal?move.col+i:move.col;
    if (!manualGrid[r][c]) {
      const el=getCell(r,c);
      if (el) {
        el.classList.remove('ctw','cdw','ctl','cdl','cstar');
        el.classList.add('highlight-move');
        el.textContent=move.word[i];
      }
    }
  }
}

// ── Board rendering ─────────────────────────────────────────────────────────
function drawBoardInto(colHdrId, rowsId, grid, move) {
  const ch = document.getElementById(colHdrId);
  ch.innerHTML='';
  for (let c=0;c<15;c++){
    const s=document.createElement('span');
    s.textContent=String.fromCharCode(65+c);
    ch.appendChild(s);
  }
  // Build highlight set: all (row,col) positions covered by the move
  const hi=new Set();
  if (move) {
    for (let i=0;i<move.word.length;i++) {
      const r=move.row+(move.horizontal?0:i);
      const c=move.col+(move.horizontal?i:0);
      hi.add(r+','+c);
    }
  }
  const br=document.getElementById(rowsId);
  br.innerHTML='';
  for (let r=0;r<15;r++) {
    const row=document.createElement('div');row.className='board-row';
    const lbl=document.createElement('div');lbl.className='row-n';lbl.textContent=r+1;row.appendChild(lbl);
    for (let c=0;c<15;c++) {
      const el=document.createElement('div');
      const k=r+','+c;
      const letter=grid&&grid[r]&&grid[r][c]!=='.'?grid[r][c]:null;
      const isHi=hi.has(k);
      if (letter&&isHi)      { el.className='c ch'; el.textContent=letter; }
      else if (letter)        { el.className='c ct'; el.textContent=letter; }
      else if (isHi)          { const li=move.horizontal?c-move.col:r-move.row; el.className='c ch'; el.textContent=move.word[li]||''; }
      else if (k==='7,7')     { el.className='c cstar'; el.textContent='★'; }
      else if (TW.has(k))     { el.className='c ctw'; el.textContent='3W'; }
      else if (DW.has(k))     { el.className='c cdw'; el.textContent='2W'; }
      else if (TL.has(k))     { el.className='c ctl'; el.textContent='3L'; }
      else if (DL.has(k))     { el.className='c cdl'; el.textContent='2L'; }
      else                    { el.className='c ce'; }
      row.appendChild(el);
    }
    br.appendChild(row);
  }
}

function drawBoard(grid, move) {
  drawBoardInto('colHdrs','boardRows',grid,move);
}

document.addEventListener('DOMContentLoaded', ()=>{
  initManualBoard();
  drawBoardInto('blankColHdrs','blankBoardRows',Array.from({length:15},()=>Array(15).fill('.')),null);
  // Restore any previously saved board state — happens after cells are rendered.
  const didRestore = restoreBoard();
  if (didRestore) {
    // Briefly flash the board card border to indicate state was restored.
    const boardCard = document.querySelector('.card');
    if (boardCard) {
      boardCard.style.transition = 'box-shadow .4s';
      boardCard.style.boxShadow = '0 0 0 2px var(--success)';
      setTimeout(() => { boardCard.style.boxShadow = ''; }, 1200);
    }
  }
});
</script>
</body>
</html>
"""
