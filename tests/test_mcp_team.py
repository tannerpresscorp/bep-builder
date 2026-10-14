"""Tests for the bep_mcp team server (HTTP mode, tokens, grants, versions).
Design: docs/design/mcp-server.md, section "Team server".

Run:  python tests/test_mcp_team.py      (or: pytest tests/)
Needs the MCP Python SDK (pip install "mcp>=2,<3") and Python 3.10+; skipped otherwise.
The server runs in-process: httpx2's ASGI transport talks straight to the Starlette app, so
there is no subprocess and no network, except the few tests of the command line.

Layout of the fixture: a plans folder with three example plans, and a team config OUTSIDE it.
  alice  editor on everything
  bob    viewer on clinic*.json, editor on barracks.json, no grant on alice-only.json
  carol  editor on alias.json only (alias.json is a symlink to alice-only.json, if links work)
  dana   viewer on everything, editor on a*.json (checks "highest role wins")
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "skills/bep-builder-cli/scripts"
sys.path[:0] = [str(ROOT / "servers/bep_mcp"), str(CLI)]

try:
    import httpx2
    from mcp import Client
except ImportError as e:          # no SDK, or Python < 3.10
    Client = None
    SKIP = f"(skipped: MCP SDK not available: {e})"

if Client is not None:
    # Not inside the try above: when the SDK is there, a missing team.py must fail, not skip.
    from mcp.client.streamable_http import streamable_http_client
    from bep_mcp import team
    from bep_mcp.server import create_http_app, create_server

SENTINEL = "SENTINEL-KEEP-OUT-9137"
NO_ACCESS = "You don't have access to a plan named '{}'."
VIEW_ONLY = "You can view '{}' but not change it."
SIGN_IN = "Sign-in required"
URL = "https://bep.example.com/mcp"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "0"}}}
POST_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

# Every tool, resource and prompt the server may have, and the role it needs on a plan:
#   "any"    any signed-in user (no plan)       "list"    filtered by role, no plan argument
#   "viewer" at least viewer on `plan`          "editor"  editor on `plan`
# A name missing here fails test_every_surface_has_a_rule, so new tools can't skip authorization.
# The second item builds the minimal valid arguments for a plan name.
TOOLS = {
    "bep_list_plans": ("list", lambda p: {}),
    "bep_get_catalog": ("any", lambda p: {}),
    "bep_get_plan": ("viewer", lambda p: {"plan": p}),
    "bep_get_status": ("viewer", lambda p: {"plan": p}),
    "bep_list_todos": ("viewer", lambda p: {"plan": p}),
    "bep_check_names": ("viewer", lambda p: {"plan": p, "names": ["A-WALL-D"]}),
    "bep_convert_layers": ("viewer", lambda p: {"plan": p, "names": ["G-ANNO-TTLB-N"]}),
    "bep_get_process_map": ("viewer", lambda p: {"plan": p}),
    "bep_export_plan": ("viewer", lambda p: {"plan": p}),
    "bep_get_layer_definition": ("viewer", lambda p: {"plan": p}),
    "bep_set_value": ("editor", lambda p: {"plan": p, "path": "project.name", "value": "Changed"}),
    "bep_add_row": ("editor", lambda p: {"plan": p, "list": "team", "fields": {"role": "Tester"}}),
    "bep_remove_row": ("editor", lambda p: {"plan": p, "list": "team", "index": 0}),
    "bep_set_bim_use": ("editor", lambda p: {"plan": p, "use_id": "cobie"}),
    "bep_set_qc": ("editor", lambda p: {"plan": p, "id": "clash", "tool": "Navisworks"}),
    "bep_save_document": ("editor", lambda p: {"plan": p, "document": "plan_md",
                                               "file_name": p[:-len(".json")] + ".md"}),
    # Last on purpose: overwriting resets the plan, which the tools above need to be filled.
    "bep_create_plan": ("editor", lambda p: {"plan": p, "overwrite": True}),
}
RESOURCES = {"bep://catalog": "any"}
RESOURCE_TEMPLATES = {"bep://plans/{plan}": "viewer"}
PROMPTS = {"start_bep": "editor"}


# ---------------------------------------------------------------- fixture

class Team:
    """A temporary team server setup: plans folder, config file next to it (not inside it)."""
    def __enter__(self):
        self.root = Path(tempfile.mkdtemp())
        self.plans = self.root / "plans"
        self.plans.mkdir()
        example = ROOT / "examples/example-plan.json"
        for name in ("alice-only.json", "clinic.json", "barracks.json"):
            shutil.copy(example, self.plans / name)
        plan = json.loads((self.plans / "alice-only.json").read_text(encoding="utf-8"))
        plan["project"]["name"] = SENTINEL
        (self.plans / "alice-only.json").write_text(json.dumps(plan), encoding="utf-8")
        self.has_links = False
        try:
            os.symlink("alice-only.json", self.plans / "alias.json")
            (self.root / "outside-target.json").write_text(json.dumps(plan), encoding="utf-8")
            os.symlink(self.root / "outside-target.json", self.plans / "outside.json")
            self.has_links = True
        except (OSError, NotImplementedError, AttributeError):    # needs extra rights on Windows
            pass
        self.tokens = {u: "tok-" + u + "-" + secrets.token_urlsafe(24) for u in ("alice", "bob", "carol", "dana")}
        self.config_path = self.root / "team.json"
        grants = {"alice": {"*": "editor"},
                  "bob": {"clinic*.json": "viewer", "barracks.json": "editor"},
                  "carol": {"alias.json": "editor"},
                  "dana": {"*": "viewer", "a*.json": "editor"}}
        self.config_path.write_text(json.dumps({
            "public_url": "https://bep.example.com",
            "allowed_hosts": ["bep.example.com"],
            "allowed_origins": ["https://bep.example.com", "https://claude.ai"],
            "users": {u: {"token_sha256": team.hash_token(t), "grants": grants[u]}
                      for u, t in self.tokens.items()}}), encoding="utf-8")
        self.config = team.load_config(self.config_path)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)

    def read(self, name):
        return (self.plans / name).read_bytes()

    def version(self, name):
        return hashlib.sha256(self.read(name)).hexdigest()[:16]


class Env:
    """What a test body gets: clients for the running in-process app."""
    def __init__(self, app, tm):
        self.app, self.tm = app, tm
        self.transport = httpx2.ASGITransport(app=app)

    def http(self, user=None, token=None, headers=None):
        h = dict(headers or {})
        token = token or (self.tm.tokens[user] if user else None)
        if token:
            h["Authorization"] = "Bearer " + token
        return httpx2.AsyncClient(transport=self.transport, headers=h, timeout=60)

    @asynccontextmanager
    async def client(self, user):
        async with self.http(user) as http:
            async with Client(streamable_http_client(URL, http_client=http)) as c:
                yield c


def serve(tm, body):
    """Run `await body(env)` against the team app, in a fresh event loop."""
    async def go():
        app = create_http_app(tm.plans, tm.config)
        async with app.router.lifespan_context(app):
            return await body(Env(app, tm))
    return asyncio.run(go())


def plain(msg):
    """A tool error without the SDK's "Error executing tool NAME: " prefix."""
    return re.sub(r"^Error executing tool \w+: ", "", str(msg))


def text_of(r):
    return "".join(getattr(x, "text", "") for x in r.content)


async def call(c, tool, /, **args):
    """(is_error, structured content or text) of one tool call."""
    r = await c.call_tool(tool, args)
    return r.is_error, (r.structured_content if r.structured_content is not None else text_of(r))


async def read_res(c, uri):
    """(ok, text or error message) of one resource read."""
    try:
        r = await c.read_resource(uri)
        return True, "".join(getattr(x, "text", "") for x in r.contents)
    except Exception as e:      # MCPError from the server
        return False, str(e)


async def get_prompt(c, name, args):
    try:
        r = await c.get_prompt(name, args)
        return True, "".join(getattr(m.content, "text", "") for m in r.messages)
    except Exception as e:
        return False, str(e)


def fail_closed_client(tm):
    """A team-mode server called in-process, so with no token at all."""
    return Client(create_server(tm.plans, team=tm.config))


# ---------------------------------------------------------------- tests

def test_every_surface_has_a_rule():
    """list_tools/resources/templates/prompts must match the rule tables exactly."""
    async def body(env):
        async with env.client("alice") as c:
            tools = {t.name for t in (await c.list_tools()).tools}
            res = {str(r.uri) for r in (await c.list_resources()).resources}
            tmpl = {t.uri_template for t in (await c.list_resource_templates()).resource_templates}
            prompts = {p.name for p in (await c.list_prompts()).prompts}
        return tools, res, tmpl, prompts
    with Team() as tm:
        tools, res, tmpl, prompts = serve(tm, body)
    for found, table, kind in [(tools, TOOLS, "tool"), (res, RESOURCES, "resource"),
                               (tmpl, RESOURCE_TEMPLATES, "resource template"), (prompts, PROMPTS, "prompt")]:
        assert not found - set(table), f"{kind} without an authorization rule in this test: {sorted(found - set(table))}"
        assert not set(table) - found, f"{kind} in the rule table but not served: {sorted(set(table) - found)}"


def test_no_token_or_bad_token_is_401():
    async def body(env):
        out = {}
        for label, kw in [("none", {}), ("bad", {"token": "not-a-real-token"}),
                          ("empty", {"headers": {"Authorization": "Bearer "}}),
                          ("basic", {"headers": {"Authorization": "Basic YWxpY2U6eA=="}}),
                          ("hash", {"token": env.tm.config.users["alice"].token_sha256})]:
            async with env.http(**kw) as http:
                r = await http.post(URL, json=INIT, headers=POST_HEADERS)
                out[label] = (r.status_code, r.headers.get("www-authenticate", ""))
        async with env.http("alice") as http:      # positive control: same request, real token
            r = await http.post(URL, json=INIT, headers=POST_HEADERS)
            out["ok"] = (r.status_code, "")
        return out
    with Team() as tm:
        out = serve(tm, body)
    for label in ("none", "bad", "empty", "basic", "hash"):
        assert out[label][0] == 401, (label, out[label])
        assert "Bearer" in out[label][1], (label, out[label])
    assert out["ok"][0] == 200, out["ok"]      # the 401s come from the token, not from the request


def test_bad_host_is_421_and_bad_origin_is_403():
    async def body(env):
        out = {}
        cases = {"good": {}, "local": {"Host": "127.0.0.1:8765"},
                 "evil host": {"Host": "evil.example.com"}, "wrong port host": {"Host": "bep.example.com.evil.test"},
                 "good origin": {"Origin": "https://claude.ai"}, "local origin": {"Origin": "http://localhost:3000"},
                 "evil origin": {"Origin": "https://evil.example.com"}, "null origin": {"Origin": "null"}}
        for label, extra in cases.items():
            async with env.http("alice") as http:
                r = await http.post(URL, json=INIT, headers={**POST_HEADERS, **extra})
                out[label] = r.status_code
        return out
    with Team() as tm:
        out = serve(tm, body)
    assert out["good"] == out["local"] == out["good origin"] == out["local origin"] == 200, out
    assert out["evil host"] == 421 and out["wrong port host"] == 421, out
    assert out["evil origin"] == 403 and out["null origin"] == 403, out


def test_verifier_and_roles():
    with Team() as tm:
        v = team.TeamTokenVerifier(tm.config)
        ok = asyncio.run(v.verify_token(tm.tokens["bob"]))
        assert ok is not None and ok.client_id == "bob" and ok.subject == "bob" and "bep" in ok.scopes
        for bad in ("", "x", tm.tokens["bob"] + "x", tm.tokens["bob"].upper(), team.hash_token(tm.tokens["bob"]), None):
            assert asyncio.run(v.verify_token(bad)) is None, bad     # never raises, never matches
        r = team.role_for
        assert r(tm.config, "bob", "clinic.json") == "viewer"
        assert r(tm.config, "bob", "Clinic-A.JSON") == "viewer"      # case-insensitive
        assert r(tm.config, "bob", "barracks.json") == "editor"
        assert r(tm.config, "bob", "alice-only.json") is None
        assert r(tm.config, "bob", "barracks.json.bak.json") is None
        assert r(tm.config, "alice", "anything.json") == "editor"
        assert r(tm.config, "nobody", "clinic.json") is None
        assert r(tm.config, "dana", "alice-only.json") == "editor"   # highest matching role wins
        assert r(tm.config, "dana", "clinic.json") == "viewer"
        # Nothing about the file system is consulted: a missing file gets the same answer.
        assert r(tm.config, "bob", "no-such-plan.json") is None
        assert r(tm.config, "alice", "no-such-plan.json") == "editor"


def test_config_stores_only_hashes_and_is_checked():
    with Team() as tm:
        data = json.loads(tm.config_path.read_text(encoding="utf-8"))
        for u, t in tm.tokens.items():
            assert t not in tm.config_path.read_text(encoding="utf-8")
            assert data["users"][u]["token_sha256"] == hashlib.sha256(t.encode()).hexdigest()
        def broken(**change):
            d = json.loads(json.dumps(data))
            for k, v in change.items():
                if v is None:
                    d.pop(k, None)
                else:
                    d[k] = v
            p = tm.root / "broken.json"
            p.write_text(json.dumps(d), encoding="utf-8")
            try:
                team.load_config(p)
            except ValueError as e:
                assert str(e)
                return
            assert False, f"expected ValueError for {change}"
        broken(users={})
        broken(users=None)
        broken(public_url=None)
        broken(public_url="https://bep.example.com/mcp")     # the server adds /mcp itself
        broken(users={"x": {"token_sha256": "short", "grants": {"*": "viewer"}}})
        broken(users={"x": {"token": "plain-text-token", "token_sha256": "0" * 64, "grants": {"*": "viewer"}}})
        broken(users={"x": {"token_sha256": "0" * 64, "grants": {"*": "owner"}}})
        try:
            team.load_config(tm.root / "missing.json")
            assert False
        except ValueError:
            pass


def test_fail_closed_without_a_token():
    """A team-mode server reached with no authenticated user (no token context) denies everything."""
    async def body():
        async with fail_closed_client(tm) as c:
            for tool, (_, args) in TOOLS.items():
                err, msg = await call(c, tool, **args("alice-only.json"))
                assert err and SIGN_IN in str(msg), (tool, msg)
            err, msg = await call(c, "bep_get_catalog")
            assert err and SIGN_IN in str(msg), msg
            err, msg = await call(c, "bep_check_names", names=["A-WALL-D"])    # no plan: still needs sign-in
            assert err and SIGN_IN in str(msg), msg
            ok, msg = await read_res(c, "bep://plans/alice-only.json")
            assert not ok and SIGN_IN in msg, msg
            ok, msg = await read_res(c, "bep://catalog")
            assert not ok and SIGN_IN in msg, msg
            ok, msg = await get_prompt(c, "start_bep", {"plan": "alice-only.json"})
            assert not ok and SIGN_IN in msg, msg
    with Team() as tm:
        before = {p.name: p.read_bytes() for p in tm.plans.glob("*.json") if not p.is_symlink()}
        asyncio.run(body())
        assert before == {p.name: p.read_bytes() for p in tm.plans.glob("*.json") if not p.is_symlink()}


def test_plan_names_are_checked_before_roles_and_existence():
    """Odd names fail on format for everyone (nothing to learn about roles or files)."""
    async def body(env):
        async with env.client("bob") as c:
            for name in ("../alice-only.json", "sub/x.json", "x.txt", ""):
                err, msg = await call(c, "bep_get_status", plan=name)
                assert err and "isn't a plan file name" in str(msg), (name, msg)
                assert "access" not in str(msg)
    with Team() as tm:
        serve(tm, body)


def test_user_cannot_read_a_plan_they_have_no_grant_on():
    """Every tool, the resource and the prompt: an ungranted plan and a plan that doesn't exist
    give the same answer, and nothing from the plan leaks."""
    async def body(env):
        seen = []
        async with env.client("bob") as c:
            for plan in ("alice-only.json", "ghost.json"):
                for tool, (rule, args) in TOOLS.items():
                    if rule in ("any", "list"):
                        continue
                    err, msg = await call(c, tool, **args(plan))
                    assert err and plain(msg).replace(plan, "P") == NO_ACCESS.format("P"), (tool, plan, msg)   # nothing else added
                    seen.append(str(msg))
                ok, msg = await read_res(c, "bep://plans/" + plan)
                assert not ok and NO_ACCESS.format(plan) in msg, (plan, msg)
                seen.append(msg)
                ok, msg = await get_prompt(c, "start_bep", {"plan": plan})
                assert not ok and NO_ACCESS.format(plan) in msg, (plan, msg)
                seen.append(msg)
            # The shapes of the denials are the same for both names.
            forms = set()
            for plan in ("alice-only.json", "ghost.json"):
                for tool in ("bep_get_plan", "bep_set_value"):
                    err, msg = await call(c, tool, **TOOLS[tool][1](plan))
                    forms.add((tool, plain(msg).replace(plan, "P")))
                ok, msg = await read_res(c, "bep://plans/" + plan)
                forms.add(("resource", msg.replace(plan, "P")))
                ok, msg = await get_prompt(c, "start_bep", {"plan": plan})
                forms.add(("prompt", msg.replace(plan, "P")))
            assert len(forms) == 4, forms
        return seen
    with Team() as tm:
        before = tm.read("alice-only.json")
        serve(tm, body)
        assert tm.read("alice-only.json") == before
        assert not (tm.plans / "ghost.json").exists()


def test_leak_check_sentinel_and_folder_path():
    """Put a sentinel inside a plan bob has no grant on; run everything bob can run; the sentinel
    must be in no answer. In team mode no answer holds the server's folder path either."""
    async def body(env):
        seen = []
        async with env.client("bob") as c:
            async def rec(coro):
                r = await coro
                seen.append(json.dumps(r, default=str) if not isinstance(r, str) else r)
                return r
            for tool, (rule, args) in TOOLS.items():
                for plan in ("alice-only.json", "ghost.json", "clinic-broken.json", "../x.json"):
                    if rule in ("any", "list") and plan != "alice-only.json":
                        continue
                    await rec(call(c, tool, **args(plan)))
            await rec(call(c, "bep_check_names", plan="alice-only.json", names=["A-WALL-D"]))
            for plan in ("alice-only.json", "ghost.json", "clinic-broken.json", "../x.json"):
                await rec(read_res(c, "bep://plans/" + plan))
                await rec(get_prompt(c, "start_bep", {"plan": plan}))
            await rec(read_res(c, "bep://catalog"))
            listing = await call(c, "bep_list_plans")
            seen.append(json.dumps(listing, default=str))
            for t in (await c.list_tools()).tools:
                seen.append(t.description or "")
            for r in (await c.list_resources()).resources:
                seen.append(f"{r.uri} {r.name} {r.description}")
        return seen, listing
    with Team() as tm:
        (tm.plans / "clinic-broken.json").write_text("{not json", encoding="utf-8")
        seen, listing = serve(tm, body)
        blob = "\n".join(seen)
        assert SENTINEL not in blob, "the sentinel leaked into an answer"
        for variant in {str(tm.plans), os.path.realpath(tm.plans), str(tm.plans).replace("\\", "/"),
                        os.path.realpath(tm.plans).replace("\\", "/"), str(tm.root)}:
            assert variant not in blob and variant not in blob.replace("\\\\", "\\"), variant
        err, listing = listing
        assert not err and "plans_dir" not in listing


def test_leak_check_plan_content_not_returned_for_denied_plan():
    """Same as above, but looking at the one thing that matters: the plan's own content."""
    async def body(env):
        out = []
        async with env.client("bob") as c:
            for tool, (rule, args) in TOOLS.items():
                if rule in ("any", "list"):
                    continue
                out.append(json.dumps(await call(c, tool, **args("alice-only.json")), default=str))
            out.append(json.dumps(await read_res(c, "bep://plans/alice-only.json")))
            out.append(json.dumps(await get_prompt(c, "start_bep", {"plan": "alice-only.json"})))
            out.append(json.dumps(await call(c, "bep_list_plans"), default=str))
            out.append(json.dumps(await call(c, "bep_check_names", names=["A-WALL-D"]), default=str))
        return out
    with Team() as tm:
        out = serve(tm, body)
    assert not [o for o in out if SENTINEL in o], "sentinel leaked"


def test_list_plans_is_filtered_and_has_roles():
    async def body(env):
        res = {}
        for user in ("alice", "bob", "carol", "dana"):
            async with env.client(user) as c:
                res[user] = await call(c, "bep_list_plans")
        return res
    with Team() as tm:
        res = serve(tm, body)
        for user, (err, out) in res.items():
            assert not err and "plans_dir" not in out, (user, out)
            blob = json.dumps(out)
            for variant in (str(tm.plans), os.path.realpath(tm.plans)):
                assert variant not in blob
        roles = {u: {p["plan"]: p.get("role") for p in out["plans"]} for u, (_, out) in res.items()}
        assert roles["bob"] == {"clinic.json": "viewer", "barracks.json": "editor"}, roles["bob"]
        assert "alice-only.json" not in roles["bob"]
        assert roles["alice"]["alice-only.json"] == "editor" and roles["alice"]["clinic.json"] == "editor"
        assert roles["dana"]["clinic.json"] == "viewer" and roles["dana"]["alice-only.json"] == "editor"
        for p in res["bob"][1]["plans"]:
            assert p["version"] == tm.version(p["plan"])


def test_symlink_alias_cannot_reach_a_plan_without_a_grant():
    async def body(env):
        out = {}
        async with env.client("carol") as c:
            for tool, (rule, args) in TOOLS.items():
                if rule in ("any", "list"):
                    continue
                out[tool] = await call(c, tool, **args("alias.json"))
            out["resource"] = await read_res(c, "bep://plans/alias.json")
            out["prompt"] = await get_prompt(c, "start_bep", {"plan": "alias.json"})
            out["list"] = await call(c, "bep_list_plans")
        async with env.client("alice") as c:      # control: alice may use the alias (grant on both names)
            out["alice"] = await call(c, "bep_get_status", plan="alias.json")
        return out
    with Team() as tm:
        if not tm.has_links:
            print("  (symlink test skipped: this system doesn't allow symlinks)")
            return
        before = tm.read("alice-only.json")
        out = serve(tm, body)
        for tool, (err, msg) in ((k, v) for k, v in out.items() if k in TOOLS):
            assert err and "access" in str(msg) and SENTINEL not in str(msg), (tool, msg)
        assert out["resource"][0] is False and SENTINEL not in out["resource"][1]
        assert out["prompt"][0] is False
        err, listing = out["list"]
        assert not err and [p["plan"] for p in listing["plans"]] == [], listing
        assert out["alice"][0] is False
        assert tm.read("alice-only.json") == before


def test_symlink_leaving_the_folder_is_never_reachable():
    async def body(env):
        async with env.client("alice") as c:     # alice has editor on every name, so only the link check stops her
            return {"get": await call(c, "bep_get_plan", plan="outside.json"),
                    "set": await call(c, "bep_set_value", plan="outside.json", path="project.name", value="X"),
                    "doc": await call(c, "bep_save_document", plan="clinic.json", document="plan_md",
                                      file_name="outside.md"),
                    "resource": await read_res(c, "bep://plans/outside.json"),
                    "list": await call(c, "bep_list_plans")}
    with Team() as tm:
        if not tm.has_links:
            print("  (symlink test skipped: this system doesn't allow symlinks)")
            return
        before = (tm.root / "outside-target.json").read_bytes()
        out = serve(tm, body)
        for k in ("get", "set"):
            assert out[k][0] and "access" in plain(out[k][1]) and SENTINEL not in str(out[k][1]), (k, out[k])
        assert out["resource"][0] is False and SENTINEL not in out["resource"][1]
        assert "outside.json" not in [p["plan"] for p in out["list"][1]["plans"]]
        assert (tm.root / "outside-target.json").read_bytes() == before
        assert out["doc"][0] and "access" in plain(out["doc"][1]), out["doc"]   # outside.md counts as outside.json
        assert not (tm.plans / "outside.md").exists()


def test_viewer_can_read_but_not_write():
    async def body(env):
        out = {}
        async with env.client("bob") as c:
            for tool, (rule, args) in TOOLS.items():
                if rule in ("any", "list"):
                    continue
                out[tool] = (rule, await call(c, tool, **args("clinic.json")))
            out["resource"] = await read_res(c, "bep://plans/clinic.json")
            out["prompt"] = await get_prompt(c, "start_bep", {"plan": "clinic.json"})
        return out
    with Team() as tm:
        before = {n: tm.read(n) for n in ("clinic.json",)}
        out = serve(tm, body)
        assert tm.read("clinic.json") == before["clinic.json"]
        assert not (tm.plans / "clinic.md").exists()
    for tool, v in out.items():
        if tool in ("resource", "prompt"):
            continue
        rule, (err, msg) = v
        if rule == "viewer":
            assert not err, (tool, msg)
        else:
            assert err and plain(msg) == VIEW_ONLY.format("clinic.json"), (tool, msg)
    assert out["resource"][0] and out["prompt"][0] is False
    assert VIEW_ONLY.format("clinic.json") in out["prompt"][1]


def test_editor_can_use_every_write_tool():
    async def body(env):
        out = {}
        async with env.client("bob") as c:
            for tool, (rule, args) in TOOLS.items():
                if rule == "editor":
                    out[tool] = await call(c, tool, **args("barracks.json"))
            out["prompt"] = await get_prompt(c, "start_bep", {"plan": "barracks.json"})
            out["new"] = await call(c, "bep_create_plan", plan="barracks-2.json")      # no grant: denied
        return out
    with Team() as tm:
        out = serve(tm, body)
        for tool, (err, res) in ((k, v) for k, v in out.items() if k in TOOLS):
            assert not err, (tool, res)
            if tool != "bep_save_document":     # writes a document, not the plan: no new plan version
                assert isinstance(res, dict) and re.fullmatch(r"[0-9a-f]{16}", res.get("version", "")), (tool, res)
        assert out["prompt"][0] and "barracks.json" in out["prompt"][1]
        assert out["new"][0] and NO_ACCESS.format("barracks-2.json") in out["new"][1]
        assert not (tm.plans / "barracks-2.json").exists()
        assert (tm.plans / "barracks.md").is_file()
        assert out["bep_create_plan"][1]["version"] == tm.version("barracks.json")


def test_save_document_needs_editor_on_the_output_name_too():
    async def body(env):
        out = {}
        async with env.client("bob") as c:
            # bob is editor on barracks.json only; the output's stem names the plan it would belong to.
            out["same stem"] = await call(c, "bep_save_document", plan="barracks.json",
                                          document="plan_md", file_name="barracks.md")
            out["other stem"] = await call(c, "bep_save_document", plan="barracks.json",
                                           document="plan_md", file_name="clinic-copy.md")
            out["viewer stem"] = await call(c, "bep_save_document", plan="barracks.json",
                                            document="plan_html", file_name="clinic.html")
            out["ungranted stem"] = await call(c, "bep_save_document", plan="barracks.json",
                                               document="layer_definition", file_name="alice-only.txt")
        async with env.client("alice") as c:
            out["alice"] = await call(c, "bep_save_document", plan="alice-only.json",
                                      document="plan_md", file_name="anything.md")
        return out
    with Team() as tm:
        out = serve(tm, body)
        assert not out["same stem"][0] and (tm.plans / "barracks.md").is_file()
        for k in ("other stem", "viewer stem", "ungranted stem"):
            assert out[k][0], (k, out[k])
        for f in ("clinic-copy.md", "clinic.html", "alice-only.txt"):
            assert not (tm.plans / f).exists(), f
        assert not out["alice"][0] and (tm.plans / "anything.md").is_file()


def test_versions_and_if_version():
    async def body(env):
        out = {}
        async with env.client("alice") as c:
            out["plan"] = await call(c, "bep_get_plan", plan="clinic.json")
            out["status"] = await call(c, "bep_get_status", plan="clinic.json")
            old = out["plan"][1]["version"]
            out["bytes_before"] = env.tm.read("clinic.json")
            out["stale"] = await call(c, "bep_set_value", plan="clinic.json", path="project.name",
                                      value="Stale write", if_version="0" * 16)
            out["bytes_after_stale"] = env.tm.read("clinic.json")
            out["fresh"] = await call(c, "bep_set_value", plan="clinic.json", path="project.name",
                                      value="Fresh write", if_version=old)
            out["again"] = await call(c, "bep_set_value", plan="clinic.json", path="project.name",
                                      value="Second write with the old version", if_version=old)
            out["empty"] = await call(c, "bep_set_value", plan="clinic.json", path="project.name",
                                      value="Empty if_version", if_version="")      # same as no check
            out["no check"] = await call(c, "bep_set_value", plan="clinic.json", path="project.name",
                                         value="Unchecked write")
            out["stale row"] = await call(c, "bep_add_row", plan="clinic.json", list="team",
                                          fields={"role": "X"}, if_version=old)
            out["stale remove"] = await call(c, "bep_remove_row", plan="clinic.json", list="team",
                                             index=0, if_version=old)
            out["stale use"] = await call(c, "bep_set_bim_use", plan="clinic.json", use_id="cobie", if_version=old)
            out["stale qc"] = await call(c, "bep_set_qc", plan="clinic.json", id="clash", if_version=old)
            out["stale create"] = await call(c, "bep_create_plan", plan="clinic.json", overwrite=True, if_version=old)
            out["after all"] = env.tm.read("clinic.json")
            out["list"] = await call(c, "bep_list_plans")
        return out
    with Team() as tm:
        v0 = tm.version("clinic.json")
        out = serve(tm, body)
        assert out["plan"][1]["version"] == v0 == out["status"][1]["version"]
        assert out["stale"][0] and "changed since you read it" in str(out["stale"][1]), out["stale"]
        assert out["bytes_after_stale"] == out["bytes_before"]                  # nothing written
        assert not out["fresh"][0] and out["fresh"][1]["version"] != v0
        assert not out["empty"][0], out["empty"]
        assert json.loads(tm.read("clinic.json"))["project"]["name"] == "Unchecked write"
        assert out["fresh"][1]["version"] != out["no check"][1]["version"]
        assert out["no check"][1]["version"] == tm.version("clinic.json")      # the version after the write
        assert out["again"][0] and "changed since you read it" in str(out["again"][1])
        for k in ("stale row", "stale remove", "stale use", "stale qc", "stale create"):
            assert out[k][0] and "changed since you read it" in str(out[k][1]), (k, out[k])
        assert out["after all"] == tm.read("clinic.json")                       # only the unchecked write landed
        listed = {p["plan"]: p["version"] for p in out["list"][1]["plans"]}
        assert listed["clinic.json"] == tm.version("clinic.json")


def test_stdio_mode_unchanged_apart_from_versions():
    """No team: no checks, the folder path is still reported, and versions work as well."""
    async def go(d):
        async with Client(create_server(d)) as c:
            out = {}
            out["list"] = await call(c, "bep_list_plans")
            out["get"] = await call(c, "bep_get_plan", plan="clinic.json")
            out["stale"] = await call(c, "bep_set_value", plan="clinic.json", path="project.name",
                                      value="X", if_version="f" * 16)
            out["fresh"] = await call(c, "bep_set_value", plan="clinic.json", path="project.name",
                                      value="X", if_version=out["get"][1]["version"])
            out["res"] = await read_res(c, "bep://plans/alice-only.json")
            return out
    with Team() as tm:
        out = asyncio.run(go(tm.plans))
        assert out["list"][1]["plans_dir"] and "role" not in out["list"][1]["plans"][0]
        assert out["get"][1]["version"] == hashlib.sha256((ROOT / "examples/example-plan.json").read_bytes()).hexdigest()[:16]
        assert out["stale"][0] and "changed since you read it" in str(out["stale"][1])
        assert not out["fresh"][0] and out["res"][0]


def test_audit_log_has_user_and_outcome_and_never_a_token():
    records = []
    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())
    log = logging.getLogger("bep_mcp")
    handler, level = Grab(level=logging.INFO), log.level
    log.addHandler(handler)
    log.setLevel(logging.INFO)

    async def body(env):
        async with env.client("alice") as c:
            await call(c, "bep_get_status", plan="alice-only.json")
            await call(c, "bep_set_value", plan="alice-only.json", path="project.name", value="Z", if_version="0" * 16)
        async with env.client("bob") as c:
            await call(c, "bep_get_status", plan="alice-only.json")
            await call(c, "bep_list_plans")
            await read_res(c, "bep://plans/alice-only.json")
            await get_prompt(c, "start_bep", {"plan": "alice-only.json"})
    try:
        with Team() as tm:
            serve(tm, body)
            async def anon():
                async with fail_closed_client(tm) as c:
                    await call(c, "bep_get_status", plan="alice-only.json")
            asyncio.run(anon())
            lines = [r for r in records if "kind=" in r]
            def has(*parts):
                return any(all(p in line for p in parts) for line in lines)
            assert has("user=alice", "kind=tool", "name=bep_get_status", "plan=alice-only.json", "ok"), lines
            assert has("user=alice", "name=bep_set_value", "error"), lines            # stale version
            assert has("user=bob", "kind=tool", "name=bep_get_status", "plan=alice-only.json", "denied"), lines
            assert not has("user=bob", "name=bep_get_status", "error"), lines        # denied is not error
            assert has("user=bob", "name=bep_list_plans", "plan=-", "ok"), lines
            assert has("user=bob", "kind=resource", "denied"), lines
            assert has("user=bob", "kind=prompt", "name=start_bep", "denied"), lines
            assert has("user=-", "denied"), lines                                     # no user at all
            everything = "\n".join(records)
            for t in tm.tokens.values():
                assert t not in everything
                assert team.hash_token(t) not in everything
            assert SENTINEL not in everything
    finally:
        log.removeHandler(handler)
        log.setLevel(level)


def run_cli(*args, env_extra=None, timeout=60):
    env = {k: v for k, v in os.environ.items() if k not in ("BEP_PLANS_DIR", "BEP_TEAM_CONFIG")}
    env["PYTHONPATH"] = str(ROOT / "servers/bep_mcp")
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", "bep_mcp", *args], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=timeout)


def test_new_token_prints_a_token_and_its_hash():
    r = run_cli("--new-token")       # works without BEP_PLANS_DIR
    assert r.returncode == 0, r.stderr
    words = r.stdout.split()
    hashes = [w for w in words if re.fullmatch(r"[0-9a-f]{64}", w)]
    assert hashes, r.stdout
    pairs = [(w, h) for w in words for h in hashes if w != h and team.hash_token(w) == h]
    assert pairs and len(pairs[0][0]) >= 40, r.stdout
    other = run_cli("--new-token")
    assert pairs[0][0] not in other.stdout


def test_http_refuses_to_start_on_a_bad_setup():
    with Team() as tm:
        env = {"BEP_PLANS_DIR": str(tm.plans)}
        # missing config file
        r = run_cli("--http", "--config", str(tm.root / "nope.json"), env_extra=env)
        assert r.returncode == 1 and "config" in r.stderr.lower(), (r.returncode, r.stderr)
        # no --config at all
        r = run_cli("--http", env_extra=env)
        assert r.returncode == 1 and "config" in r.stderr.lower(), (r.returncode, r.stderr)
        # a config without users
        empty = tm.root / "empty.json"
        empty.write_text(json.dumps({"public_url": "https://bep.example.com", "users": {}}), encoding="utf-8")
        r = run_cli("--http", "--config", str(empty), env_extra=env)
        assert r.returncode == 1 and "users" in r.stderr, (r.returncode, r.stderr)
        # no plans folder
        r = run_cli("--http", "--config", str(tm.config_path))
        assert r.returncode == 1 and "BEP_PLANS_DIR" in r.stderr, (r.returncode, r.stderr)
        # the config (it holds the token hashes) must not sit where the tools can reach it
        inside = tm.plans / "team.json"
        shutil.copy(tm.config_path, inside)
        r = run_cli("--http", "--config", str(inside), env_extra=env, timeout=30)
        assert r.returncode == 1 and "plans folder" in r.stderr and "config" in r.stderr.lower(), (r.returncode, r.stderr)
        for t in tm.tokens.values():
            assert t not in r.stdout + r.stderr


if __name__ == "__main__":
    if Client is None:
        print(SKIP)
        sys.exit(0)
    logging.disable(logging.INFO)   # the server logs one line per call; the audit test turns it back on
    failed = 0
    for name, fn in [(k, v) for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]:
        try:
            logging.disable(logging.NOTSET if name == "test_audit_log_has_user_and_outcome_and_never_a_token"
                            else logging.INFO)
            fn()
            print(f"PASS {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
