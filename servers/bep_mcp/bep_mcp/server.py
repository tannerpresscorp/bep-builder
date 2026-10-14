"""bep_mcp: MCP tools for BIM Execution Plans, over the bep-builder CLI.

Design: docs/design/mcp-server.md. Every rule comes from bep.py (imported in-process);
this module only adds the MCP tool surface, the plan-folder sandbox and error mapping.

Plans are JSON files in one folder, BEP_PLANS_DIR. Tools name a plan by file name
("clinic.json"), never by path, and can't reach anything outside that folder.
"""
import argparse
import contextlib
import functools
import hashlib
import json
import logging
import os
import re
import secrets
import sys
import threading
from pathlib import Path
from typing import Any, Literal

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, ToolAnnotations

from bep_mcp import team as teamlib


def _cli_dir():
    """Folder holding bep.py: BEP_CLI_DIR, else this repository's copy next to the server."""
    env = os.environ.get("BEP_CLI_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "skills" / "bep-builder-cli" / "scripts"


_CLI = _cli_dir()
if not (_CLI / "bep.py").is_file():
    raise ImportError(f"bep.py not found in {_CLI}; set BEP_CLI_DIR to skills/bep-builder-cli/scripts")
sys.path.insert(0, str(_CLI))
import bep  # noqa: E402
import processmap  # noqa: E402

log = logging.getLogger("bep_mcp")

PLAN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,100}\.json")
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                       open_world_hint=False)
EDIT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                       open_world_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False,
                              open_world_hint=False)
DOCUMENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,100}\.(md|html|txt)")
# One lock for every load -> change -> save, so overlapping requests can't lose each other's edits.
WRITE_LOCK = threading.Lock()
SECTION_TITLES = {code: title for code, _, title in bep.SECTIONS}


class Denied(ToolError):
    """The caller has no (or too little) access to a plan. Logged as `denied`, not `error`."""


def _current_user():
    """The signed-in user's name, or None (stdio, or no token on the request)."""
    token = get_access_token()
    return token.client_id if token else None


def _one_line(text, limit=300):
    """Text safe for one log line: user-supplied names can't forge extra lines."""
    return re.sub(r"[\r\n]+", " ", str(text))[:limit]


def _plan_label(plan):
    if not plan:
        return "-"
    return plan if isinstance(plan, str) and PLAN_NAME.fullmatch(plan) else repr(_one_line(plan, 120))


@contextlib.contextmanager
def _audited(kind, name, plan=None):
    """Log one line per tool, resource or prompt call to stderr (stdout carries the protocol):
    `user=<name|-> kind=<kind> name=<name> plan=<plan|-> ok | denied: msg | error: msg`.
    Never logs a token."""
    head = f"user={_current_user() or '-'} kind={kind} name={name} plan={_plan_label(plan)}"
    try:
        yield
    except Denied as e:
        log.info("%s denied: %s", head, _one_line(e))
        raise
    except (ToolError, ResourceError, MCPError) as e:
        log.info("%s error: %s", head, _one_line(getattr(e, "message", e)))
        raise
    except Exception:
        log.exception("%s crashed", head)
        raise
    log.info("%s ok", head)


def check_plan_name(name):
    """ToolError unless `name` is a plain plan file name (step 1 of every plan-touching call)."""
    if not isinstance(name, str) or not PLAN_NAME.fullmatch(name):
        raise ToolError(f"'{name}' isn't a plan file name. Use a name like 'clinic.json' "
                        "(letters, digits, '.', '_', '-' or spaces, ending in .json), with no folders.")


def resolve_plan(plans_dir, name, must_exist=True):
    """The plan file `name` inside plans_dir, or ToolError if the name could escape it."""
    check_plan_name(name)
    root = Path(os.path.realpath(plans_dir))
    path = Path(os.path.realpath(root / name))
    if path.parent != root:
        raise ToolError(f"'{name}' points outside the plans folder.")
    if must_exist and not path.is_file():
        raise ToolError(f"No plan named '{name}'. Call bep_list_plans to see the plans.")
    return path


def version_of(raw):
    """A plan file's version: the first 16 hex characters of the sha256 of its bytes."""
    return hashlib.sha256(raw).hexdigest()[:16]


def parse_plan(raw):
    """The normalized plan in the file bytes `raw` (bep.loads), so a plan is parsed from the very
    bytes its version was taken from. Errors say "it", not the file's path; read_plan adds the
    plan's file name."""
    return bep.loads(raw, "it")


def read_plan(path, name):
    """(plan, version) from ONE read of the plan file."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise ToolError(f"'{name}' isn't a readable plan file: it can't be read.") from None
    try:
        return parse_plan(raw), version_of(raw)
    except ValueError as e:   # PlanFileError is a ValueError
        raise ToolError(f"'{name}' isn't a readable plan file: {e}") from e


def _load(plans_dir, name):
    """(plan, version) of the plan file `name`."""
    return read_plan(resolve_plan(plans_dir, name), name)


def _save(path, plan):
    try:
        bep.save(path, plan)
    except PermissionError as e:
        raise ToolError(f"Can't save '{path.name}': it is read-only.") from e
    except OSError as e:      # keep the folder path out of the message
        raise ToolError(f"Can't save '{path.name}': {e.strerror or 'disk error'}.") from None


def _check_version(plan, current, if_version):
    """Refuse a write when the caller read an older version of the plan. No if_version (None or
    "") means no check."""
    if if_version and if_version != current:
        raise ToolError(f"'{plan}' changed since you read it (now version {current}). "
                        "Read it again and retry.")


def _edit(plans_dir, name, change, if_version=None):
    """Load the plan, apply change(plan) under the write lock, save it, and return
    (change's result, the plan's new status, its new version). bep.py's ValueErrors become
    tool errors. With if_version, a plan that has changed since is left alone."""
    with WRITE_LOCK:
        path = resolve_plan(plans_dir, name)
        plan, current = read_plan(path, name)
        _check_version(name, current, if_version)
        try:
            result = change(plan)
        except ValueError as e:
            raise ToolError(str(e)) from e
        _save(path, plan)
        new_version = version_of(path.read_bytes())
    return result, _status(plan), new_version


def _status(plan):
    sections = [{"code": code, "id": sid, "title": title, "status": bep.section_status(plan, sid)}
                for code, sid, title in bep.SECTIONS]
    todos = bep.collect_todos(bep.build_doc(plan))
    return {"sections": sections, "done": sum(s["status"] == "done" for s in sections),
            "todo_count": len(todos)}


def _catalog():
    """Every id the tools accept (bep_get_catalog and the bep://catalog resource)."""
    return {
        "bim_uses": [{"id": u, "name": n, "phase": ph} for u, n, ph in bep.USES],
        "agencies": bep.AGENCIES,
        "status_fields": bep.STATUS_FIELDS,
        "layer_formats": bep.LAYER_FORMATS,
        "sheet_levels": bep.SHEET_LEVELS,
        "qc_model_rules": {**{f"a{i}": r for i, r in enumerate(bep.QC_AUTHOR)},
                           **{f"d{i}": r for i, r in enumerate(bep.QC_DELIVER)}},
        "qc_checks": {cid: {"name": n, "purpose": p} for cid, n, p in bep.QC_CHECKS},
        "lists": {k: list(v) for k, v in bep.ROW_TEMPLATES.items()},
        "sections": [{"code": c, "id": i, "title": t} for c, i, t in bep.SECTIONS],
    }


def create_server(plans_dir, team=None):
    """Build the server for one plans folder. main() calls this; tests call it directly.

    team=None is the local (stdio) mode: no sign-in, no limits. team=TeamConfig is the team mode:
    every plan-touching call needs a signed-in user (from the HTTP bearer token) with a grant on
    the plan, and with no user the call is refused. The mode is fixed here, so a missing token
    can never turn into full access."""
    if not Path(plans_dir).is_dir():
        raise ValueError(f"BEP_PLANS_DIR {plans_dir!r} isn't a folder")
    auth = {}
    if team is not None:
        auth = {"token_verifier": teamlib.TeamTokenVerifier(team),
                "auth": AuthSettings(issuer_url=team.public_url, resource_server_url=team.public_url + "/mcp",
                                     validate_token_resource=False)}
    server = MCPServer(
        "bep_mcp",
        instructions=(
            "Tools for BIM Execution Plans (BEPs) under the U.S. National CAD Standard. Plans are "
            "JSON files named like 'clinic.json'; start with bep_list_plans. Call bep_get_catalog "
            "for the ids other tools accept. bep_get_status and bep_list_todos show what a plan "
            "still needs. Never invent project facts; leave unknowns as TODOs. The start_bep "
            "prompt walks through a new plan; resources bep://catalog and bep://plans/{plan} "
            "give the same data as bep_get_catalog and bep_get_plan. Reads return the plan's "
            "version; pass it as if_version when you change the plan, so you don't overwrite "
            "someone else's edit."),
        **auth,
    )

    def authorize(plan, need):
        """Raise Denied unless the caller may use `plan` as `need` ("viewer" or "editor").
        plan=None only asks for a signed-in user. Local mode allows everything. Depends on the
        plan's name (and the real name behind a link), never on whether the file exists."""
        if team is None:
            return
        user = _current_user()
        if user is None:
            raise Denied("Sign-in required.")
        if plan is None:
            return
        role = teamlib.effective_role(team, user, plans_dir, plan)
        if role is None:
            raise Denied(f"You don't have access to a plan named '{plan}'.")
        if need == "editor" and role != "editor":
            raise Denied(f"You can view '{plan}' but not change it.")

    def guarded(need):
        """Decorator for a tool: log it, then check the plan name, then the caller's access,
        and only then run it (so nothing reveals whether a plan exists to someone without
        access). A tool without a plan argument only needs a signed-in user."""
        def decorate(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                plan = kwargs.get("plan")
                with _audited("tool", fn.__name__, plan):
                    if plan is not None:
                        check_plan_name(plan)
                    authorize(plan, need)
                    return fn(*args, **kwargs)
            return wrapper
        return decorate

    def visible_plans():
        """[(path, role)] of the plan files the caller may see, in name order."""
        out = []
        user = _current_user()
        for path in sorted(Path(plans_dir).glob("*.json")):
            if not PLAN_NAME.fullmatch(path.name):
                continue
            role = None
            if team is None:
                role = "editor"
            elif user is not None:
                role = teamlib.effective_role(team, user, plans_dir, path.name)
            if role is not None:
                out.append((path, role))
        return out

    @server.tool(annotations=READ, structured_output=True)
    @guarded(None)
    def bep_list_plans() -> dict[str, Any]:
        """List the plan files you can use, with each project's name, how many of its 11 sections
        are complete, and each plan's version (pass it as if_version when you change the plan)."""
        plans = []
        for path, role in visible_plans():
            entry = {"plan": path.name}
            try:
                raw = path.read_bytes()
                entry["version"] = version_of(raw)
                plan = parse_plan(raw)
            except (ValueError, OSError):
                plans.append({**entry, "error": "not a readable plan file", **({"role": role} if team else {})})
                continue
            st = _status(plan)
            entry.update(project=plan["project"]["name"], sections_done=st["done"], todo_count=st["todo_count"])
            if team is not None:
                entry["role"] = role
            plans.append(entry)
        return {"plans": plans} if team is not None else {"plans_dir": str(plans_dir), "plans": plans}

    @server.tool(annotations=READ, structured_output=True)
    @guarded(None)
    def bep_get_catalog() -> dict[str, Any]:
        """Every id the other tools accept: BIM uses, agencies, status fields, ISO 13567 layer
        formats, sheet levels, QC model rules and checks, and the editable lists with their fields."""
        return _catalog()

    @server.tool(annotations=READ, structured_output=True)
    @guarded("viewer")
    def bep_get_plan(plan: str, path: str | None = None) -> dict[str, Any]:
        """Read a whole plan, or one value by dotted path (e.g. 'project.name', 'team.0',
        'uses.coord'). Top-level keys: project (name, agency, phase...), team, goals, uses
        (by BIM use id), exchanges, cobie, collab, tech, standards (NCS and ISO 13567 settings),
        qc (model rules a0-d8), checks (visual, clash, standards, integrity), deliver. The result
        includes the plan's version: pass it as if_version to a write tool."""
        p, version = _load(plans_dir, plan)
        if not path:
            return {"plan": plan, "version": version, "value": p}
        try:
            return {"plan": plan, "version": version, "path": path, "value": bep.get_path(p, path)}
        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise ToolError(f"'{path}' isn't in this plan ({e}). Call bep_get_plan without a path "
                            "to see its fields.") from e

    @server.tool(annotations=READ, structured_output=True)
    @guarded("viewer")
    def bep_get_status(plan: str) -> dict[str, Any]:
        """Completion of the plan's 11 sections (done, partial or empty), its number of TODOs and
        its version."""
        p, version = _load(plans_dir, plan)
        return {"plan": plan, "version": version, **_status(p)}

    @server.tool(annotations=READ, structured_output=True)
    @guarded("viewer")
    def bep_list_todos(plan: str) -> dict[str, Any]:
        """Everything the plan is still missing, grouped by section. An empty list means the plan
        is complete."""
        todos = bep.collect_todos(bep.build_doc(_load(plans_dir, plan)[0]))
        groups = {}
        for t in todos:
            groups.setdefault(t.section, []).append(t.msg)
        return {"plan": plan, "todo_count": len(todos),
                "sections": [{"code": c, "title": SECTION_TITLES[c], "todos": m}
                             for c, m in groups.items()]}

    @server.tool(annotations=READ, structured_output=True)
    @guarded("viewer")
    def bep_check_names(names: list[str], plan: str | None = None) -> dict[str, Any]:
        """Check CAD layer names and sheet ids against NCS naming. With a plan, apply its status
        field and, when it uses ISO 13567, its layer profile."""
        if not names:
            raise ToolError("Give at least one layer name or sheet id.")
        res = bep.check_names(names, _load(plans_dir, plan)[0] if plan else None)
        res["valid"] = sum(1 for r in res["results"] if not r["problems"])
        res["to_fix"] = len(res["results"]) - res["valid"]
        return res

    @server.tool(annotations=READ, structured_output=True)
    @guarded("viewer")
    def bep_convert_layers(plan: str, names: list[str], anno_element: str | None = None) -> dict[str, Any]:
        """Suggest ISO 13567 layer names for existing layers under the plan's layer profile
        (standards.layerFormat, statusField, sheetCode). This works even while the plan has ISO
        13567 naming off; iso13567_on in the result says whether it is on. A null suggestion means a person must decide, e.g. which element an ANNO layer belongs to;
        pass anno_element (a 4-character element code) to place them."""
        if not names:
            raise ToolError("Give at least one layer name.")
        if anno_element and not re.fullmatch(r"[A-Za-z0-9~]{4}", anno_element):
            raise ToolError("anno_element must be exactly 4 letters, digits or ~.")
        p = _load(plans_dir, plan)[0]
        res = bep.convert_layers(p, names, anno_element)
        res["iso13567_on"] = bool(p["standards"]["iso13567"])
        return res

    @server.tool(annotations=READ, structured_output=False)
    @guarded("viewer")
    def bep_get_process_map(plan: str, format: Literal["mermaid", "tldraw"] = "mermaid") -> str:
        """The plan's Level 1 process map (section 05): a Mermaid flowchart, or a script for the
        tldraw MCP server's exec tool. In Mermaid, phases are subgraphs, each BIM use is a node
        named u_<use id>, a phase with no uses shows a stub node, and each exchange labels the
        arrow into the use it feeds. Exchanges that match no BIM use are listed at the end."""
        model = processmap.build(_load(plans_dir, plan)[0], bep.USES)
        text = processmap.to_tldraw(model) if format == "tldraw" else processmap.to_mermaid(model)
        if model["notes"] and format == "mermaid":
            text += "\n%% Not on the map (name each exchange after the use it feeds): " + "; ".join(model["notes"]) + "\n"
        return text

    @server.tool(annotations=READ, structured_output=False)
    @guarded("viewer")
    def bep_export_plan(plan: str, format: Literal["md", "html"] = "md") -> str:
        """The finished BIM Execution Plan as Markdown or HTML. Missing values appear as
        'TODO: ...' in the text."""
        p = _load(plans_dir, plan)[0]
        doc = bep.build_doc(p)
        return bep.to_markdown(p, doc) if format == "md" else bep.to_html(p, doc)

    @server.tool(annotations=READ, structured_output=False)
    @guarded("viewer")
    def bep_get_layer_definition(plan: str) -> str:
        """The ISO 13567-3 layer naming system definition file for the plan, including its
        user-defined codes."""
        return bep.layer_definition(_load(plans_dir, plan)[0])

    @server.tool(annotations=DESTRUCTIVE, structured_output=True)
    @guarded("editor")
    def bep_create_plan(plan: str, example: bool = False, agency: str | None = None,
                        overwrite: bool = False, if_version: str | None = None) -> dict[str, Any]:
        """Create a plan file: blank, or the labelled example project (example=true). agency is one
        of the agency ids from bep_get_catalog. An existing plan is only replaced when
        overwrite=true, which discards it. When replacing, pass the version from your last read
        as if_version to avoid overwriting someone else's change."""
        with WRITE_LOCK:
            path = resolve_plan(plans_dir, plan, must_exist=False)
            if path.exists() and not overwrite:
                raise ToolError(f"'{plan}' already exists. Pass overwrite=true to replace it, or pick another name.")
            if path.is_file():
                try:
                    _check_version(plan, version_of(path.read_bytes()), if_version)
                except OSError:
                    raise ToolError(f"'{plan}' can't be read to check its version.") from None
            p = bep.example_plan() if example else bep.blank_plan()
            if agency:
                try:
                    bep.set_path(p, "project.agency", agency)
                except ValueError as e:
                    raise ToolError(str(e)) from e
            _save(path, p)
            saved, version = read_plan(path, plan)
        return {"plan": plan, "created": True, "example": example, **_status(saved), "version": version}

    @server.tool(annotations=EDIT, structured_output=True)
    @guarded("editor")
    def bep_set_value(plan: str, path: str, value: str, if_version: str | None = None) -> dict[str, Any]:
        """Set one value by dotted path, e.g. 'project.name', 'team.0.email', 'collab.cde',
        'standards.iso13567'. Values are text; on/off fields take yes/no. Lists are changed with
        bep_add_row and bep_remove_row, BIM uses with bep_set_bim_use, QC with bep_set_qc. Pass the
        version from your last read as if_version to avoid overwriting someone else's change."""
        def change(p):
            try:
                old = bep.get_path(p, path)
            except (KeyError, IndexError, ValueError, TypeError):
                old = None
            try:
                new = bep.set_path(p, path, value)
            except (KeyError, IndexError, ValueError, TypeError) as e:
                raise ValueError(f"Couldn't set {path}: {e}") from e
            return {"path": path, "old": old, "new": new}
        result, status, version = _edit(plans_dir, plan, change, if_version)
        return {"plan": plan, **result, "status": status, "version": version}

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                             idempotent_hint=False, open_world_hint=False),
                 structured_output=True)
    @guarded("editor")
    def bep_add_row(plan: str, list: str, fields: dict[str, str], if_version: str | None = None) -> dict[str, Any]:
        """Add a row to one of the plan's lists: team, goals, exchanges, tech, deliver or
        standards.codes (fields per list in bep_get_catalog). A blank placeholder row is filled
        first instead of adding after it. Pass the version from your last read as if_version to
        avoid overwriting someone else's change."""
        def change(p):
            row = bep.add_row(p, list, fields)
            return {"list": list, "index": next(i for i, r in enumerate(bep.get_path(p, list)) if r is row),
                    "row": row}
        result, status, version = _edit(plans_dir, plan, change, if_version)
        return {"plan": plan, **result, "status": status, "version": version}

    @server.tool(annotations=DESTRUCTIVE, structured_output=True)
    @guarded("editor")
    def bep_remove_row(plan: str, list: str, index: int, if_version: str | None = None) -> dict[str, Any]:
        """Remove a row (0-based index) from team, goals, exchanges, tech, deliver or
        standards.codes. Read the list with bep_get_plan first to pick the right index, and pass
        its version as if_version so the index can't point at a row someone else moved."""
        result, status, version = _edit(
            plans_dir, plan,
            lambda p: {"list": list, "index": index, "removed": bep.remove_row(p, list, index)}, if_version)
        return {"plan": plan, **result, "status": status, "version": version}

    @server.tool(annotations=EDIT, structured_output=True)
    @guarded("editor")
    def bep_set_bim_use(plan: str, use_id: str, on: bool = True, party: str | None = None,
                        value: str | None = None, flow: str | None = None,
                        if_version: str | None = None) -> dict[str, Any]:
        """Turn a BIM use on or off (ids in bep_get_catalog) and set who is responsible (party),
        why it's worth doing (value) and its process flow. Omitted details are left as they are.
        Turning on 'cobie' also marks COBie handover as required. Pass the version from your last
        read as if_version to avoid overwriting someone else's change."""
        result, status, version = _edit(plans_dir, plan, lambda p: {
            "use_id": use_id, "use": bep.set_use(p, use_id, on=on, party=party, value=value, flow=flow)},
            if_version)
        return {"plan": plan, **result, "status": status, "version": version}

    @server.tool(annotations=EDIT, structured_output=True)
    @guarded("editor")
    def bep_set_qc(plan: str, id: str, on: bool = True, who: str | None = None,
                   freq: str | None = None, tool: str | None = None,
                   if_version: str | None = None) -> dict[str, Any]:
        """Configure a QC check (visual, clash, standards, integrity: tool, who, freq) or a model
        rule (a0-a8, d0-d8: on, who, freq). Checks can't be turned off; rules have no tool.
        Omitted details are left as they are. In the plan, checks are stored at checks.<id> and
        rules at qc.<id>. Pass the version from your last read as if_version to avoid overwriting
        someone else's change."""
        result, status, version = _edit(plans_dir, plan, lambda p: {
            "id": id, "qc": bep.set_qc(p, id, on=on, who=who, freq=freq, tool=tool)}, if_version)
        return {"plan": plan, **result, "status": status, "version": version}

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True,
                                             idempotent_hint=True, open_world_hint=False),
                 structured_output=True)
    @guarded("editor")
    def bep_save_document(plan: str, document: Literal["plan_md", "plan_html", "layer_definition"],
                          file_name: str) -> dict[str, Any]:
        """Write a document into the plans folder: the finished plan as Markdown (plan_md) or HTML
        (plan_html), or the ISO 13567-3 layer definition file. file_name is a plain name ending
        in .md, .html or .txt; an existing file of that name is replaced. Needs edit access to the
        plan and to the plan name the document is named after ('clinic-bep.md' counts as
        'clinic-bep.json')."""
        if not DOCUMENT_NAME.fullmatch(file_name or ""):
            raise ToolError(f"'{file_name}' isn't a document file name. Use a name like 'clinic-bep.md' "
                            "(ending in .md, .html or .txt), with no folders.")
        authorize(Path(file_name).stem + ".json", "editor")
        root = Path(os.path.realpath(plans_dir))
        out = Path(os.path.realpath(root / file_name))
        if out.parent != root:
            raise ToolError(f"'{file_name}' points outside the plans folder.")
        if team is not None and out.name != file_name:     # a link would write somewhere else
            raise ToolError(f"'{file_name}' is a link; give the document its own file name.")
        p = _load(plans_dir, plan)[0]
        if document == "layer_definition":
            text = bep.layer_definition(p)
        else:
            doc = bep.build_doc(p)
            text = bep.to_markdown(p, doc) if document == "plan_md" else bep.to_html(p, doc)
        with WRITE_LOCK:
            try:
                out.write_text(text, encoding="utf-8")
            except PermissionError as e:
                raise ToolError(f"Can't write '{file_name}': permission denied.") from e
        return {"plan": plan, "document": document, "file": file_name, "bytes": len(text.encode("utf-8")),
                "todo_count": len(bep.collect_todos(bep.build_doc(p)))}

    @server.resource("bep://catalog", name="catalog", title="BEP catalog",
                     description="Every id the tools accept (same as bep_get_catalog).",
                     mime_type="application/json")
    def catalog_resource() -> str:
        try:
            with _audited("resource", "catalog"):
                authorize(None, None)
                return json.dumps(_catalog(), indent=2, ensure_ascii=False)
        except ToolError as e:
            raise ResourceError(str(e)) from None

    @server.resource("bep://plans/{plan}", name="plan", title="BEP plan",
                     description="One plan file from the plans folder, normalized, as JSON "
                                 "(same as bep_get_plan without a path). Read-only.",
                     mime_type="application/json")
    def plan_resource(plan: str) -> str:
        try:
            with _audited("resource", "plan", plan):
                check_plan_name(plan)
                authorize(plan, "viewer")
                return json.dumps(_load(plans_dir, plan)[0], indent=2, ensure_ascii=False)
        except ToolError as e:
            raise ResourceError(str(e)) from None

    @server.prompt(name="start_bep", title="Start a BIM Execution Plan",
                   description="Interview the user section by section and fill a plan with the "
                               "bep tools, leaving anything unknown as a TODO.")
    def start_bep(plan: str = "plan.json", agency: str = "") -> str:
        # The SDK turns other exceptions from a prompt into "Internal server error"; MCPError keeps the message.
        try:
            with _audited("prompt", "start_bep", plan):
                check_plan_name(plan)            # same name rules as the tools
                authorize(plan, "editor")        # it ends in bep_create_plan, so it needs edit access
                resolve_plan(plans_dir, plan, must_exist=False)
                if agency and agency not in bep.AGENCIES:
                    raise MCPError(code=INVALID_PARAMS,
                                   message=f"Unknown agency '{agency}'. Use one of: {', '.join(bep.AGENCIES)}.")
                return start_bep_text(plan, agency, (Path(plans_dir) / plan).is_file())
        except ToolError as e:
            raise MCPError(code=INVALID_PARAMS, message=str(e)) from None

    return server


def start_bep_text(plan, agency, exists):
    """The start_bep prompt: the bep-builder-cli skill's workflow, written for the MCP tools."""
    if exists:
        first = (f"1. {plan} already exists. Call bep_get_status and bep_list_todos on it, tell me "
                 "where it stands, and carry on from the first section that isn't done.")
    else:
        a = f', agency "{agency}"' if agency else ""
        first = (f"1. Create {plan} with bep_create_plan (blank, not the example{a}). "
                 + ("" if agency else "Ask me who the owner is first if it decides the agency "
                    "(USACE, GSA, VA, other federal, state or private)."))
    return f"""Help me write a BIM Execution Plan (BEP) in {plan}, using the bep tools.

{first}
2. Call bep_get_catalog once, so you use real ids for BIM uses, agencies, QC checks and model rules.
3. Interview me one section at a time, in plan order, and save each answer as soon as I give it:
   - 01 Project: bep_set_value on project.name, owner, location, delivery, phase, start (YYYY-MM-DD), agency, cui (yes/no), iso. For USACE or other DoD work, ask the CUI question early.
   - 02 Team: bep_add_row on team (role, org, name, email).
   - 03 Goals: bep_add_row on goals (goal, uses), highest priority first.
   - 04-05 BIM uses: bep_set_bim_use with the responsible party, the value to the project and the process flow.
   - 06 Exchanges: bep_add_row on exchanges (what, from, to, content, lod, due); bep_set_value cobie for COBie.
   - 07 Collaboration: bep_set_value on collab.cde, sharing, meetings, coords, naming, changes.
   - 08 Technology: bep_add_row on tech (discipline, software, version, formats).
   - 09 Standards: bep_set_value on standards.* (NCS version, sheet level, status field, ISO 13567, layer format, plotting). Check any layer or sheet names I give you with bep_check_names.
   - 10 Quality control: bep_set_qc for the visual, clash, standards and integrity checks (tool, who, freq) and the model rules.
   - 11 Deliverables: bep_add_row on deliver (item, format, due).
4. Never invent names, firms, dates or numbers. Anything I haven't told you stays empty, so it shows as a TODO.
5. After each section, show progress with bep_get_status. When we reach the end, go through bep_list_todos with me, grouped by section, in plain words.
6. Once BIM uses are chosen, show the Level 1 process map with bep_get_process_map.
7. At the end, offer to save the plan with bep_save_document (plan_md or plan_html) and say how many TODOs remain.
"""


def create_http_app(plans_dir, config, host="127.0.0.1"):
    """The team server as an ASGI app (Starlette) serving streamable HTTP at /mcp. Every request
    needs a bearer token from the config's users. One uvicorn process serves it: a plan is
    protected from lost edits by the write lock and if_version, which only work inside one process.

    Host and Origin headers are checked against config.allowed_hosts / allowed_origins (plus
    localhost), which stops DNS-rebinding; behind a reverse proxy, list the public host name."""
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[*config.allowed_hosts, "127.0.0.1:*", "localhost:*"],
        allowed_origins=[*config.allowed_origins, "http://127.0.0.1:*", "http://localhost:*"])
    return create_server(plans_dir, config).streamable_http_app(
        stateless_http=True, json_response=True, transport_security=security, host=host)


def _parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="bep_mcp",
        description="MCP server for BIM Execution Plans. With no options it serves one person over "
                    "stdio. With --http it serves a team over HTTP; put an HTTPS reverse proxy in front.")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP at /mcp instead of stdio")
    ap.add_argument("--config", metavar="PATH", help="team config file (or set BEP_TEAM_CONFIG); with --http")
    ap.add_argument("--host", default="127.0.0.1", help="address to bind (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8765, help="port to listen on (default 8765)")
    ap.add_argument("--new-token", action="store_true",
                    help="print a new random token and its sha256 (for the config), then exit")
    return ap.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if args.new_token:
        token = secrets.token_urlsafe(32)
        print(f"token:  {token}\nsha256: {teamlib.hash_token(token)}")
        return
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="bep_mcp: %(message)s")
    plans_dir = os.environ.get("BEP_PLANS_DIR")
    if not plans_dir:
        sys.exit("bep_mcp: set BEP_PLANS_DIR to the folder that holds your plan .json files")
    if not args.http:
        if args.config:
            sys.exit("bep_mcp: --config is for the team server; add --http")
        try:
            server = create_server(plans_dir)
        except ValueError as e:
            sys.exit(f"bep_mcp: {e}")
        log.info("serving plans in %s", os.path.realpath(plans_dir))
        server.run("stdio")
        return
    config_path = args.config or os.environ.get("BEP_TEAM_CONFIG")
    if not config_path:
        sys.exit("bep_mcp: --http needs --config PATH (or BEP_TEAM_CONFIG)")
    try:
        config = teamlib.load_config(config_path)
        if teamlib.config_inside(config_path, plans_dir):
            raise ValueError(f"team config {config_path} is inside the plans folder, where the tools could "
                             "read and change it; keep it in a folder the plans don't use")
        app = create_http_app(plans_dir, config, args.host)
    except ValueError as e:
        sys.exit(f"bep_mcp: {e}")
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("binding %s: traffic is plain HTTP; serve it only behind an HTTPS proxy", args.host)
    log.info("team server for %d user(s), plans in %s, http://%s:%d/mcp",
             len(config.users), os.path.realpath(plans_dir), args.host, args.port)
    import uvicorn      # installed with the SDK
    uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
