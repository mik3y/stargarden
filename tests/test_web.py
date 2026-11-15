"""The web console's API and stream, driven over aiohttp's test client."""

import asyncio
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from stargarden.app import Stargarden
from stargarden.config import Config, WebConfig
from stargarden.console import Console, install_log_buffer
from stargarden.web import WebConsole


@pytest.mark.asyncio
async def test_api_and_stream(tmp_path: Path, config: Config) -> None:
    program = Stargarden(config)
    server = WebConsole(Console(program, install_log_buffer("INFO")), program.config.web, dist=tmp_path / "no-dist")

    async def drive() -> None:
        async with TestClient(TestServer(server.app())) as client:
            await asyncio.sleep(0.1)
            status = await (await client.get("/api/status")).json()
            assert status["on"] is True and status["paused"] is False and status["leg_s"] == 100.0

            r = await client.post("/api/actions/set_position", json={"position": 0.5})
            assert r.status == 200 and (await r.json()) == {"ok": True, "result": 0.5}
            assert program.sunset.paused and program.sunset.position == 0.5
            r = await client.post("/api/actions/set_leg", json={"seconds": 600})
            assert (await r.json())["result"] == 600 and program.sunset.leg_s == 600
            r = await client.post("/api/actions/toggle_paused")  # no body at all
            assert r.status == 200 and program.sunset.paused is False

            r = await client.post("/api/actions/set_leg", json={"seconds": 1})
            assert r.status == 400 and "set_leg" in (await r.json())["error"]
            r = await client.post("/api/actions/shutdown", json={})
            assert r.status == 404
            r = await client.post("/api/actions/set_leg", json=[1, 2])
            assert r.status == 400
            r = await client.post("/api/actions/set_leg", data=b"{not json")
            assert r.status == 400

            program.lighting.fade_master(1.0, 0.0)  # past the fade-up
            await asyncio.sleep(0.1)  # the preview is the last rendered frame: let the render loop draw one
            fixtures = await (await client.get("/api/fixtures")).json()
            assert [f["name"] for f in fixtures] == ["a"] and max(fixtures[0]["rows"][0][0]["rgb"]) > 0
            log = await (await client.get("/api/log?since=0")).json()
            assert any("sunset: held at 50%" in line["msg"] for line in log["lines"]) and log["next"] == len(log["lines"])
            tail = await (await client.get(f"/api/log?since={log['next']}")).json()
            assert tail["lines"] == [] and tail["next"] == log["next"]  # the console's own requests are not logged

            page = await client.get("/")
            assert page.status == 200 and "bun run build" in await page.text()  # nothing built: the hint page
            assert (await client.get("/assets/nope.js")).status == 404

            async with client.ws_connect(f"/ws?since={log['next']}") as ws:
                seen: dict[str, dict] = {}
                for _ in range(12):
                    msg = await asyncio.wait_for(ws.receive_json(), 2.0)
                    seen.setdefault(msg["type"], msg)
                    if msg["type"] == "fixtures":  # something to log, so a "log" message follows
                        await client.post("/api/actions/restart")
                    if {"status", "fixtures", "log"} <= seen.keys():
                        break
                assert seen["status"]["status"]["on"] is True
                assert seen["fixtures"]["fixtures"][0]["name"] == "a"
                assert all(line["seq"] >= log["next"] for line in seen["log"]["lines"])  # nothing replayed before `since`
                assert any("restarted" in line["msg"] for line in seen["log"]["lines"])
            program.shutdown()

    await program.run(foreground=drive())


@pytest.mark.asyncio
async def test_serves_the_built_app(tmp_path: Path, config: Config) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>built</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("no")
    program = Stargarden(config)
    server = WebConsole(Console(program, install_log_buffer("INFO")), program.config.web, dist=dist)

    async def drive() -> None:
        async with TestClient(TestServer(server.app())) as client:
            assert "built" in await (await client.get("/")).text()
            r = await client.get("/assets/app.js")
            assert r.status == 200 and r.content_type in ("application/javascript", "text/javascript")
            assert (await client.get("/assets/../secret.txt")).status == 404
            assert (await client.get("/api/status")).status == 200  # the API wins over the catch-all
            program.shutdown()

    await program.run(foreground=drive())


@pytest.mark.asyncio
async def test_run_binds_a_port(tmp_path: Path, config: Config) -> None:
    program = Stargarden(config)
    cfg = WebConfig(enabled=True, host="127.0.0.1", port=0)  # any free port
    server = WebConsole(Console(program, install_log_buffer("INFO")), cfg, dist=tmp_path / "no-dist")

    async def drive() -> None:
        await asyncio.wait_for(server.bound.wait(), 5.0)
        assert server.port
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{server.port}/api/status") as r:
                assert r.status == 200 and (await r.json())["site"] == "Stargarden"
        program.shutdown()

    await program.run(foreground=drive(), background=[server.run()])


@pytest.mark.asyncio
async def test_run_survives_a_busy_port(tmp_path: Path, config: Config) -> None:
    program = Stargarden(config)
    console = Console(program, install_log_buffer("INFO"))
    first = WebConsole(console, WebConfig(port=0), dist=tmp_path / "no-dist")

    async def drive() -> None:
        await asyncio.wait_for(first.bound.wait(), 5.0)
        second = WebConsole(console, WebConfig(port=first.port), dist=tmp_path / "no-dist")
        await asyncio.wait_for(second.run(), 5.0)  # returns instead of raising
        records, _ = console.log_buffer.since(0)
        assert any("cannot listen" in r.getMessage() for r in (r for _, r in records))
        program.shutdown()

    await program.run(foreground=drive(), background=[first.run()])
