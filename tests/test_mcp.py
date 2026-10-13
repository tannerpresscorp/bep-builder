"""Tests for the bep_mcp server (servers/bep_mcp). Design: docs/design/mcp-server.md.

Run:  python tests/test_mcp.py      (or: pytest tests/)
Needs the MCP Python SDK (pip install "mcp>=2,<3") and Python 3.10+; skipped otherwise.
Tools are called through the SDK's in-process client: no subprocess, no network.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "skills/bep-builder-cli/scripts"
sys.path[:0] = [str(ROOT / "servers/bep_mcp"), str(CLI)]

import logging
logging.disable(logging.INFO)   # the server logs one line per tool call; keep test output readable

try:
    from mcp import Client
    from bep_mcp.server import create_server
except ImportError as e:          # no SDK, or Python < 3.10
    Client = None
    SKIP = f"(skipped: MCP SDK not available: {e})"

READ_TOOLS = {"bep_list_plans", "bep_get_catalog", "bep_get_plan", "bep_get_status", "bep_list_todos",
              "bep_check_names", "bep_convert_layers", "bep_get_process_map", "bep_export_plan",
              "bep_get_layer_definition"}


def cli(*args):
    r = subprocess.run([sys.executable, str(CLI / "bep.py"), *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


class Plans:
    """A temporary plans folder holding the example plan as ex.json and a blank plan as new.json."""
    def __enter__(self):
        self.dir = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "examples/example-plan.json", self.dir / "ex.json")
        cli("init", self.dir / "new.json")
        return self.dir

    def __exit__(self, *exc):
        shutil.rmtree(self.dir)


def call(plans_dir, tool, **args):
    """Call one tool; return (is_error, structured content or text)."""
    async def go():
        async with Client(create_server(plans_dir)) as c:
            r = await c.call_tool(tool, args)
            text = "".join(getattr(x, "text", "") for x in r.content)
            return r.is_error, (r.structured_content if r.structured_content is not None else text)
    return asyncio.run(go())


def tools(plans_dir):
    async def go():
        async with Client(create_server(plans_dir)) as c:
            return (await c.list_tools()).tools
    return asyncio.run(go())


def test_tool_list_and_annotations():
    with Plans() as d:
        ts = {t.name: t for t in tools(d)}
    assert set(ts) == READ_TOOLS
    for t in ts.values():
        a = t.annotations
        assert a.read_only_hint and not a.destructive_hint and a.open_world_hint is False, t.name
        assert t.description, t.name


def test_read_tools_match_the_cli():
    with Plans() as d:
        err, plans = call(d, "bep_list_plans")
        assert not err and [p["plan"] for p in plans["plans"]] == ["ex.json", "new.json"]
        assert plans["plans"][0]["sections_done"] == 11 and plans["plans"][0]["todo_count"] == 0
        err, st = call(d, "bep_get_status", plan="new.json")
        assert not err and st["todo_count"] > 0 and len(st["sections"]) == 11
        err, todos = call(d, "bep_list_todos", plan="new.json")
        assert not err and todos["todo_count"] == st["todo_count"]
        assert call(d, "bep_list_todos", plan="ex.json")[1]["todo_count"] == 0
        err, v = call(d, "bep_get_plan", plan="ex.json", path="project.agency")
        assert not err and v["value"] == "va"
        # Parity: the same text as the CLI commands produce
        assert call(d, "bep_export_plan", plan="ex.json")[1] == cli("export", d / "ex.json")
        assert call(d, "bep_export_plan", plan="ex.json", format="html")[1] == cli("export", d / "ex.json", "--format", "html")
        assert call(d, "bep_get_process_map", plan="ex.json", format="tldraw")[1] == cli("process-map", d / "ex.json", "--format", "tldraw")
        assert call(d, "bep_get_process_map", plan="ex.json")[1].startswith(cli("process-map", d / "ex.json"))
        assert call(d, "bep_get_layer_definition", plan="ex.json")[1] == cli("definition", d / "ex.json")
        err, names = call(d, "bep_check_names", names=["A-WALL-D", "a-door", "AD-101"])
        assert not err and names["valid"] == 1 and names["to_fix"] == 2
        err, conv = call(d, "bep_convert_layers", plan="ex.json", names=["G-ANNO-TTLB-N", "A-ANNO-DIMS"])
        assert not err and conv["results"][0]["suggested"] == "G-SHET-____-TTLB-N" and conv["results"][1]["suggested"] is None
        err, cat = call(d, "bep_get_catalog")
        assert not err and "coord" in [u["id"] for u in cat["bim_uses"]] and "team" in cat["lists"]
        # Nothing was written
        assert json.loads((d / "ex.json").read_text(encoding="utf-8")) == json.loads(
            (ROOT / "examples/example-plan.json").read_text(encoding="utf-8"))


def test_plan_names_cannot_leave_the_plans_folder():
    with Plans() as d:
        outside = d.parent / (d.name + "-outside.json")
        shutil.copy(d / "ex.json", outside)
        try:
            (d / "link.json").symlink_to(outside)
            have_link = True
        except (OSError, NotImplementedError):    # symlinks need extra rights on Windows
            have_link = False
        try:
            bad = ["../ex.json", str(d / "ex.json"), "sub/ex.json", "ex.txt", ".hidden.json", "", "missing.json"]
            bad += ["link.json"] if have_link else []
            for name in bad:
                err, msg = call(d, "bep_get_status", plan=name)
                assert err, name
            err, msg = call(d, "bep_get_plan", plan="ex.json", path="project.nope")
            assert err and "isn't in this plan" in msg
            (d / "broken.json").write_text("{not json", encoding="utf-8")
            err, msg = call(d, "bep_get_status", plan="broken.json")
            assert err and "isn't a readable plan file" in msg
            listed = {p["plan"]: p for p in call(d, "bep_list_plans")[1]["plans"]}
            assert listed["broken.json"]["error"] and "ex.json" in listed
        finally:
            outside.unlink()


def test_server_needs_a_plans_folder():
    try:
        create_server(str(ROOT / "no-such-folder"))
        assert False, "expected ValueError"
    except ValueError:
        pass
    env = {k: v for k, v in os.environ.items() if k != "BEP_PLANS_DIR"}
    env["PYTHONPATH"] = str(ROOT / "servers/bep_mcp")
    r = subprocess.run([sys.executable, "-m", "bep_mcp"], capture_output=True, text=True,
                       encoding="utf-8", env=env, timeout=60)
    assert r.returncode != 0 and "BEP_PLANS_DIR" in r.stderr


if __name__ == "__main__":
    if Client is None:
        print(SKIP)
        sys.exit(0)
    failed = 0
    for name, fn in [(k, v) for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
