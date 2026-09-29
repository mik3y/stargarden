"""The web console's API and stream, driven over aiohttp's test client."""

import asyncio
from dataclasses import replace
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from stargarden.app import Stargarden
from stargarden.audio import Layer
from stargarden.conductor import State
from stargarden.config import WebConfig
from stargarden.console import Console, install_log_buffer
from stargarden.manifest import load_manifest
from stargarden.web import WebConsole
from test_app import make_config


def make_program(tmp_path: Path, assets: Path) -> Stargarden:
    config = make_config(tmp_path, assets)
    # actions, not timers, drive these tests: keep the show and the vacancy timeout out of the way
    config = replace(config, timers=replace(config.timers, show_delay_s=30), presence=replace(config.presence, vacancy_timeout_s=30))
    return Stargarden(config, load_manifest(config.assets_root), seed=1)


@pytest.mark.asyncio
async def test_api_and_stream(tmp_path: Path, assets: Path) -> None:
    program = make_program(tmp_path, assets)
    server = WebConsole(Console(program, install_log_buffer("INFO")), program.config.web, dist=tmp_path / "no-dist")

    async def drive() -> None:
        async with TestClient(TestServer(server.app())) as client:
            await asyncio.sleep(0.3)
            status = await (await client.get("/api/status")).json()
            assert status["state"] == "ambient" and status["levels"]["bed"] == 0.8

            r = await client.post("/api/actions/force", json={"state": "presence"})
            assert r.status == 200 and (await r.json()) == {"ok": True, "result": None}
            assert program.conductor.forced is State.PRESENCE
            r = await client.post("/api/actions/set_level", json={"name": "music", "value": 0.4})
            assert (await r.json())["result"] == pytest.approx(0.4) and program.audio.level(Layer.MUSIC) == pytest.approx(0.4)
            r = await client.post("/api/actions/release")  # no body at all
            assert r.status == 200 and program.conductor.forced is None

            r = await client.post("/api/actions/force", json={"state": "party"})
            assert r.status == 400 and "force" in (await r.json())["error"]
            r = await client.post("/api/actions/shutdown", json={})
            assert r.status == 404
            r = await client.post("/api/actions/force", json=[1, 2])
            assert r.status == 400
            r = await client.post("/api/actions/force", data=b"{not json")
            assert r.status == 400

            fixtures = await (await client.get("/api/fixtures")).json()
            assert [f["name"] for f in fixtures] == ["a"] and max(fixtures[0]["rows"][0][0]["rgb"]) > 0  # ambient is lit
            log = await (await client.get("/api/log?since=0")).json()
            assert any("manual: force" in line["msg"] for line in log["lines"]) and log["next"] == len(log["lines"])
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
                        await client.post("/api/actions/motion", json={"role": "walkway"})
                    if {"status", "fixtures", "log"} <= seen.keys():
                        break
                assert seen["status"]["status"]["state"] == "ambient"
                assert seen["fixtures"]["fixtures"][0]["name"] == "a"
                assert all(line["seq"] >= log["next"] for line in seen["log"]["lines"])  # nothing replayed before `since`
                assert any("walkway" in line["msg"] for line in seen["log"]["lines"])
            program.shutdown()

    await program.run(foreground=drive())


@pytest.mark.asyncio
async def test_serves_the_built_app(tmp_path: Path, assets: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>built</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("no")
    program = make_program(tmp_path, assets)
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
async def test_run_binds_a_port(tmp_path: Path, assets: Path) -> None:
    program = make_program(tmp_path, assets)
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
async def test_run_survives_a_busy_port(tmp_path: Path, assets: Path) -> None:
    program = make_program(tmp_path, assets)
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
