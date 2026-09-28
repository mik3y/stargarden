"""Web console: the React app in `web/`, a small JSON API, and a WebSocket that
streams the console's status, fixture preview and log lines.

    GET  /api/status             the `Status` snapshot
    GET  /api/fixtures           the fixture preview
    GET  /api/log?since=N        retained log lines numbered N and up
    POST /api/actions/<name>     run a `Console` action; the JSON body holds its keyword arguments
    GET  /ws[?since=N]           stream of {"type": "status" | "fixtures" | "log", ...} messages
    /                            the built app (`bun run build` in web/ → web/dist)

Fixture frames go out at 10 Hz and status at 4 Hz, the same cadence as the TUI;
log lines go out as they arrive. Actions answer over HTTP so they can also be
scripted with curl. There is no authentication: the program runs on a private
network in the field, and the console binds to localhost unless configured otherwise.
"""

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aiohttp import WSCloseCode, web

from .config import WebConfig
from .console import ActionError, Console, UnknownAction, record_to_dict

log = logging.getLogger(__name__)

DIST = Path(__file__).resolve().parents[2] / "web" / "dist"  # src/stargarden/web.py → <repo>/web/dist
FRAME_PERIOD_S = 0.1
STATUS_EVERY = 4  # frames
UNBUILT_PAGE = """<!doctype html><meta charset="utf-8"><title>Stargarden</title>
<body style="font: 16px/1.5 system-ui; background: #0b0e14; color: #e6e9ef; padding: 3rem">
<h1>Stargarden</h1><p>The web console has not been built. In <code>web/</code>:</p>
<pre>bun install
bun run build</pre><p>The API is up: <a href="/api/status" style="color: #f5a524">/api/status</a>.</p>
"""


class WebConsole:
    def __init__(self, console: Console, cfg: WebConfig, dist: Path = DIST) -> None:
        self.console = console
        self.cfg = cfg
        self.dist = dist
        self.port: int | None = None  # the bound port once `run` is listening (cfg.port may be 0)
        self.bound = asyncio.Event()
        self._sockets: set[web.WebSocketResponse] = set()

    def app(self) -> web.Application:
        logging.getLogger("aiohttp.access").propagate = False  # the console's own requests must not fill its log pane
        app = web.Application()
        app.router.add_get("/api/status", self._status)
        app.router.add_get("/api/fixtures", self._fixtures)
        app.router.add_get("/api/log", self._log)
        app.router.add_post("/api/actions/{name}", self._action)
        app.router.add_get("/ws", self._ws)
        app.router.add_get("/", self._index)
        app.router.add_get("/{path:.+}", self._file)
        app.on_shutdown.append(self._close_sockets)
        return app

    async def run(self) -> None:
        """Serve until cancelled. A port that cannot be bound is logged, not fatal:
        the installation runs without its console."""
        runner = web.AppRunner(self.app(), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self.cfg.host, self.cfg.port)
        try:
            try:
                await site.start()
            except OSError as e:
                log.error("web: cannot listen on %s:%d: %s", self.cfg.host, self.cfg.port, e)
                return
            self.port = next(a[1] for a in runner.addresses if isinstance(a, tuple))
            self.bound.set()
            log.info("web: console at http://%s:%d/", self.cfg.host, self.port)
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()

    # -- api ------------------------------------------------------------------------

    async def _status(self, request: web.Request) -> web.Response:
        return web.json_response(asdict(self.console.status()))

    async def _fixtures(self, request: web.Request) -> web.Response:
        return web.json_response([asdict(f) for f in self.console.fixtures()])

    async def _log(self, request: web.Request) -> web.Response:
        records, next_seq = self.console.log_buffer.since(_since(request))
        return web.json_response({"lines": [record_to_dict(s, r) for s, r in records], "next": next_seq})

    async def _action(self, request: web.Request) -> web.Response:
        name = request.match_info["name"]
        params: Any = {}
        if request.can_read_body:
            try:
                params = await request.json()
            except ValueError:
                return _error(400, "body must be JSON")
            if not isinstance(params, dict):
                return _error(400, "body must be a JSON object of keyword arguments")
        try:
            result = self.console.act(name, params)
        except UnknownAction as e:
            return _error(404, str(e))
        except ActionError as e:
            return _error(400, str(e))
        return web.json_response({"ok": True, "result": result})

    # -- stream ---------------------------------------------------------------------

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=15.0)
        await ws.prepare(request)
        self._sockets.add(ws)
        sender = asyncio.create_task(self._push(ws, _since(request)))
        try:
            async for _ in ws:  # the client sends nothing; reading keeps close frames and pings serviced
                pass
        finally:
            sender.cancel()
            self._sockets.discard(ws)
        return ws

    async def _push(self, ws: web.WebSocketResponse, seq: int) -> None:
        frame = 0
        try:
            while not ws.closed:
                if frame % STATUS_EVERY == 0:
                    await ws.send_json({"type": "status", "status": asdict(self.console.status())})
                await ws.send_json({"type": "fixtures", "fixtures": [asdict(f) for f in self.console.fixtures()]})
                records, seq = self.console.log_buffer.since(seq)
                if records:
                    await ws.send_json({"type": "log", "lines": [record_to_dict(s, r) for s, r in records]})
                frame += 1
                await asyncio.sleep(FRAME_PERIOD_S)
        except ConnectionResetError, asyncio.CancelledError:
            pass

    async def _close_sockets(self, app: web.Application) -> None:
        for ws in list(self._sockets):
            await ws.close(code=WSCloseCode.GOING_AWAY, message=b"shutdown")

    # -- the app --------------------------------------------------------------------

    async def _index(self, request: web.Request) -> web.StreamResponse:
        index = self.dist / "index.html"
        if index.is_file():
            return web.FileResponse(index, headers={"Cache-Control": "no-cache"})
        return web.Response(text=UNBUILT_PAGE, content_type="text/html")

    async def _file(self, request: web.Request) -> web.StreamResponse:
        path = (self.dist / request.match_info["path"]).resolve()
        if path.is_file() and path.is_relative_to(self.dist.resolve()):
            return web.FileResponse(path)
        raise web.HTTPNotFound()


def _since(request: web.Request) -> int:
    try:
        return max(0, int(request.query.get("since", 0)))
    except ValueError:
        return 0


def _error(status: int, message: str) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)
