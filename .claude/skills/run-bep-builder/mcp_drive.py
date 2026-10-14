"""Drive the bep_mcp server as a real stdio subprocess, the way an MCP client does.

Usage:  python .claude/skills/run-bep-builder/mcp_drive.py [SERVER_CMD] [PLANS_DIR]
  SERVER_CMD defaults to the installed `bep_mcp` command; PLANS_DIR defaults to a new
  temporary folder. Prints each step; exits 1 if any step behaves unexpectedly.
  The server's log lines (one per tool call) arrive on this script's stderr.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile

from mcp import Client, StdioServerParameters

CMD = sys.argv[1] if len(sys.argv) > 1 else shutil.which("bep_mcp")
PLANS = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="bep-plans-")
failed = []


def check(label, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {label}{': ' + detail if detail else ''}")
    if not ok:
        failed.append(label)


async def call(c, tool, **args):
    r = await c.call_tool(tool, args)
    text = "".join(getattr(x, "text", "") for x in r.content)
    return r.is_error, (text if r.is_error else json.loads(text) if text.startswith("{") else text)


async def main():
    if not CMD:
        sys.exit("bep_mcp isn't installed: python -m pip install -e servers/bep_mcp")
    params = StdioServerParameters(command=CMD, env={**os.environ, "BEP_PLANS_DIR": PLANS})
    async with Client(params) as c:
        tools = (await c.list_tools()).tools
        check("17 tools listed", len(tools) == 17, str(len(tools)))
        prompts = [p.name for p in (await c.list_prompts()).prompts]
        check("start_bep prompt listed", prompts == ["start_bep"], str(prompts))
        p = await c.get_prompt("start_bep", {"plan": "demo.json", "agency": "usace"})
        check("start_bep renders", "bep_create_plan" in p.messages[0].content.text)

        err, r = await call(c, "bep_create_plan", plan="demo.json", agency="usace")
        check("bep_create_plan", not err and r.get("created"), str(r)[:120] if err else "")
        err, r = await call(c, "bep_set_value", plan="demo.json", path="project.name", value="EXAMPLE — Demo")
        check("bep_set_value project.name", not err, str(r)[:120] if err else r["new"])
        err, r = await call(c, "bep_set_value", plan="demo.json", path="project.nope", value="x")
        check("bad field is refused with the field list", err and "Fields:" in r, r[:120])
        err, r = await call(c, "bep_add_row", plan="demo.json", list="team",
                            fields={"role": "BIM manager", "org": "Example Org", "name": "Example name"})
        check("bep_add_row team", not err, f"index {r['index']}" if not err else r[:120])
        err, r = await call(c, "bep_set_bim_use", plan="demo.json", use_id="coord", party="BIM manager")
        check("bep_set_bim_use coord", not err, str(r)[:120] if err else str(r["use"]))
        err, r = await call(c, "bep_check_names", names=["A-WALL-FULL", "AD-101"])
        check("bep_check_names flags AD-101", not err and r["to_fix"] == 1)
        res = await c.read_resource("bep://plans/demo.json")
        check("bep://plans/demo.json resource", json.loads(res.contents[0].text)["project"]["name"] == "EXAMPLE — Demo")
        err, r = await call(c, "bep_get_plan", plan="../demo.json")
        check("path escape is refused", err, r[:80])
        err, r = await call(c, "bep_list_todos", plan="demo.json")
        check("bep_list_todos", not err, f"{r['todo_count']} TODOs" if not err else r[:120])
        err, r = await call(c, "bep_save_document", plan="demo.json", document="plan_md", file_name="demo.md")
        check("bep_save_document writes demo.md", not err and os.path.isfile(os.path.join(PLANS, "demo.md")))
    print("plans folder:", PLANS)
    sys.exit(1 if failed else 0)


asyncio.run(main())
