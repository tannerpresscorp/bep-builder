"""bep_mcp: MCP tools for BIM Execution Plans, over the bep-builder CLI.

Design: docs/design/mcp-server.md. Every rule comes from bep.py (imported in-process);
this module only adds the MCP tool surface, the plan-folder sandbox and error mapping.

Plans are JSON files in one folder, BEP_PLANS_DIR. Tools name a plan by file name
("clinic.json"), never by path, and can't reach anything outside that folder.
"""
import functools
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations


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


def _logged(fn):
    """Log one line per tool call to stderr (stdout carries the protocol): tool, plan, ok/error."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        plan = kwargs.get("plan") or "-"
        try:
            out = fn(*args, **kwargs)
        except ToolError as e:
            log.info("%s %s error: %s", fn.__name__, plan, e)
            raise
        except Exception:
            log.exception("%s %s crashed", fn.__name__, plan)
            raise
        log.info("%s %s ok", fn.__name__, plan)
        return out
    return wrapper


def resolve_plan(plans_dir, name, must_exist=True):
    """The plan file `name` inside plans_dir, or ToolError if the name could escape it."""
    if not isinstance(name, str) or not PLAN_NAME.fullmatch(name):
        raise ToolError(f"'{name}' isn't a plan file name. Use a name like 'clinic.json' "
                        "(letters, digits, '.', '_', '-' or spaces, ending in .json), with no folders.")
    root = Path(os.path.realpath(plans_dir))
    path = Path(os.path.realpath(root / name))
    if path.parent != root:
        raise ToolError(f"'{name}' points outside the plans folder.")
    if must_exist and not path.is_file():
        raise ToolError(f"No plan named '{name}'. Call bep_list_plans to see the plans.")
    return path


def _load(plans_dir, name):
    path = resolve_plan(plans_dir, name)
    try:
        return bep.load(path)
    except ValueError as e:   # json.JSONDecodeError is a ValueError
        raise ToolError(f"'{name}' isn't a readable plan file: {e}") from e


def _save(path, plan):
    try:
        bep.save(path, plan)
    except PermissionError as e:
        raise ToolError(f"Can't save '{path.name}': it is read-only.") from e


def _edit(plans_dir, name, change):
    """Load the plan, apply change(plan) under the write lock, save it, and return
    (change's result, the plan's new status). bep.py's ValueErrors become tool errors."""
    with WRITE_LOCK:
        path = resolve_plan(plans_dir, name)
        plan = _load(plans_dir, name)
        try:
            result = change(plan)
        except ValueError as e:
            raise ToolError(str(e)) from e
        _save(path, plan)
    return result, _status(plan)


def _status(plan):
    sections = [{"code": code, "id": sid, "title": title, "status": bep.section_status(plan, sid)}
                for code, sid, title in bep.SECTIONS]
    todos = bep.collect_todos(bep.build_doc(plan))
    return {"sections": sections, "done": sum(s["status"] == "done" for s in sections),
            "todo_count": len(todos)}


def create_server(plans_dir):
    """Build the server for one plans folder. main() calls this; tests call it directly."""
    if not Path(plans_dir).is_dir():
        raise ValueError(f"BEP_PLANS_DIR {plans_dir!r} isn't a folder")
    server = MCPServer(
        "bep_mcp",
        instructions=(
            "Tools for BIM Execution Plans (BEPs) under the U.S. National CAD Standard. Plans are "
            "JSON files named like 'clinic.json'; start with bep_list_plans. Call bep_get_catalog "
            "for the ids other tools accept. bep_get_status and bep_list_todos show what a plan "
            "still needs. Never invent project facts; leave unknowns as TODOs."),
    )

    @server.tool(annotations=READ, structured_output=True)
    @_logged
    def bep_list_plans() -> dict[str, Any]:
        """List the plan files in the plans folder, with each project's name and how many of its
        11 sections are complete."""
        plans = []
        for path in sorted(Path(plans_dir).glob("*.json")):
            if not PLAN_NAME.fullmatch(path.name):
                continue
            try:
                plan = bep.load(path)
            except (ValueError, OSError):
                plans.append({"plan": path.name, "error": "not a readable plan file"})
                continue
            st = _status(plan)
            plans.append({"plan": path.name, "project": plan["project"]["name"],
                          "sections_done": st["done"], "todo_count": st["todo_count"]})
        return {"plans_dir": str(plans_dir), "plans": plans}

    @server.tool(annotations=READ, structured_output=True)
    @_logged
    def bep_get_catalog() -> dict[str, Any]:
        """Every id the other tools accept: BIM uses, agencies, status fields, ISO 13567 layer
        formats, sheet levels, QC model rules and checks, and the editable lists with their fields."""
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

    @server.tool(annotations=READ, structured_output=True)
    @_logged
    def bep_get_plan(plan: str, path: str | None = None) -> dict[str, Any]:
        """Read a whole plan, or one value by dotted path (e.g. 'project.name', 'team.0',
        'uses.coord'). Top-level keys: project (name, agency, phase...), team, goals, uses
        (by BIM use id), exchanges, cobie, collab, tech, standards (NCS and ISO 13567 settings),
        qc (model rules a0-d8), checks (visual, clash, standards, integrity), deliver."""
        p = _load(plans_dir, plan)
        if not path:
            return {"plan": plan, "value": p}
        try:
            return {"plan": plan, "path": path, "value": bep.get_path(p, path)}
        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise ToolError(f"'{path}' isn't in this plan ({e}). Call bep_get_plan without a path "
                            "to see its fields.") from e

    @server.tool(annotations=READ, structured_output=True)
    @_logged
    def bep_get_status(plan: str) -> dict[str, Any]:
        """Completion of the plan's 11 sections (done, partial or empty) and its number of TODOs."""
        return {"plan": plan, **_status(_load(plans_dir, plan))}

    @server.tool(annotations=READ, structured_output=True)
    @_logged
    def bep_list_todos(plan: str) -> dict[str, Any]:
        """Everything the plan is still missing, grouped by section. An empty list means the plan
        is complete."""
        todos = bep.collect_todos(bep.build_doc(_load(plans_dir, plan)))
        groups = {}
        for t in todos:
            groups.setdefault(t.section, []).append(t.msg)
        return {"plan": plan, "todo_count": len(todos),
                "sections": [{"code": c, "title": SECTION_TITLES[c], "todos": m}
                             for c, m in groups.items()]}

    @server.tool(annotations=READ, structured_output=True)
    @_logged
    def bep_check_names(names: list[str], plan: str | None = None) -> dict[str, Any]:
        """Check CAD layer names and sheet ids against NCS naming. With a plan, apply its status
        field and, when it uses ISO 13567, its layer profile."""
        if not names:
            raise ToolError("Give at least one layer name or sheet id.")
        res = bep.check_names(names, _load(plans_dir, plan) if plan else None)
        res["valid"] = sum(1 for r in res["results"] if not r["problems"])
        res["to_fix"] = len(res["results"]) - res["valid"]
        return res

    @server.tool(annotations=READ, structured_output=True)
    @_logged
    def bep_convert_layers(plan: str, names: list[str], anno_element: str | None = None) -> dict[str, Any]:
        """Suggest ISO 13567 layer names for existing layers under the plan's layer profile
        (standards.layerFormat, statusField, sheetCode). This works even while the plan has ISO
        13567 naming off; iso13567_on in the result says whether it is on. A null suggestion means a person must decide, e.g. which element an ANNO layer belongs to;
        pass anno_element (a 4-character element code) to place them."""
        if not names:
            raise ToolError("Give at least one layer name.")
        if anno_element and not re.fullmatch(r"[A-Za-z0-9~]{4}", anno_element):
            raise ToolError("anno_element must be exactly 4 letters, digits or ~.")
        p = _load(plans_dir, plan)
        res = bep.convert_layers(p, names, anno_element)
        res["iso13567_on"] = bool(p["standards"]["iso13567"])
        return res

    @server.tool(annotations=READ, structured_output=False)
    @_logged
    def bep_get_process_map(plan: str, format: Literal["mermaid", "tldraw"] = "mermaid") -> str:
        """The plan's Level 1 process map (section 05): a Mermaid flowchart, or a script for the
        tldraw MCP server's exec tool. In Mermaid, phases are subgraphs, each BIM use is a node
        named u_<use id>, a phase with no uses shows a stub node, and each exchange labels the
        arrow into the use it feeds. Exchanges that match no BIM use are listed at the end."""
        model = processmap.build(_load(plans_dir, plan), bep.USES)
        text = processmap.to_tldraw(model) if format == "tldraw" else processmap.to_mermaid(model)
        if model["notes"] and format == "mermaid":
            text += "\n%% Not on the map (name each exchange after the use it feeds): " + "; ".join(model["notes"]) + "\n"
        return text

    @server.tool(annotations=READ, structured_output=False)
    @_logged
    def bep_export_plan(plan: str, format: Literal["md", "html"] = "md") -> str:
        """The finished BIM Execution Plan as Markdown or HTML. Missing values appear as
        'TODO: ...' in the text."""
        p = _load(plans_dir, plan)
        doc = bep.build_doc(p)
        return bep.to_markdown(p, doc) if format == "md" else bep.to_html(p, doc)

    @server.tool(annotations=READ, structured_output=False)
    @_logged
    def bep_get_layer_definition(plan: str) -> str:
        """The ISO 13567-3 layer naming system definition file for the plan, including its
        user-defined codes."""
        return bep.layer_definition(_load(plans_dir, plan))

    @server.tool(annotations=DESTRUCTIVE, structured_output=True)
    @_logged
    def bep_create_plan(plan: str, example: bool = False, agency: str | None = None,
                        overwrite: bool = False) -> dict[str, Any]:
        """Create a plan file: blank, or the labelled example project (example=true). agency is one
        of the agency ids from bep_get_catalog. An existing plan is only replaced when
        overwrite=true, which discards it."""
        with WRITE_LOCK:
            path = resolve_plan(plans_dir, plan, must_exist=False)
            if path.exists() and not overwrite:
                raise ToolError(f"'{plan}' already exists. Pass overwrite=true to replace it, or pick another name.")
            p = bep.example_plan() if example else bep.blank_plan()
            if agency:
                try:
                    bep.set_path(p, "project.agency", agency)
                except ValueError as e:
                    raise ToolError(str(e)) from e
            _save(path, p)
        return {"plan": plan, "created": True, "example": example, **_status(bep.load(path))}

    @server.tool(annotations=EDIT, structured_output=True)
    @_logged
    def bep_set_value(plan: str, path: str, value: str) -> dict[str, Any]:
        """Set one value by dotted path, e.g. 'project.name', 'team.0.email', 'collab.cde',
        'standards.iso13567'. Values are text; on/off fields take yes/no. Lists are changed with
        bep_add_row and bep_remove_row, BIM uses with bep_set_bim_use, QC with bep_set_qc."""
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
        result, status = _edit(plans_dir, plan, change)
        return {"plan": plan, **result, "status": status}

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                             idempotent_hint=False, open_world_hint=False),
                 structured_output=True)
    @_logged
    def bep_add_row(plan: str, list: str, fields: dict[str, str]) -> dict[str, Any]:
        """Add a row to one of the plan's lists: team, goals, exchanges, tech, deliver or
        standards.codes (fields per list in bep_get_catalog). A blank placeholder row is filled
        first instead of adding after it."""
        def change(p):
            row = bep.add_row(p, list, fields)
            return {"list": list, "index": next(i for i, r in enumerate(bep.get_path(p, list)) if r is row),
                    "row": row}
        result, status = _edit(plans_dir, plan, change)
        return {"plan": plan, **result, "status": status}

    @server.tool(annotations=DESTRUCTIVE, structured_output=True)
    @_logged
    def bep_remove_row(plan: str, list: str, index: int) -> dict[str, Any]:
        """Remove a row (0-based index) from team, goals, exchanges, tech, deliver or
        standards.codes. Read the list with bep_get_plan first to pick the right index."""
        result, status = _edit(plans_dir, plan, lambda p: {"list": list, "index": index,
                                                           "removed": bep.remove_row(p, list, index)})
        return {"plan": plan, **result, "status": status}

    @server.tool(annotations=EDIT, structured_output=True)
    @_logged
    def bep_set_bim_use(plan: str, use_id: str, on: bool = True, party: str | None = None,
                        value: str | None = None, flow: str | None = None) -> dict[str, Any]:
        """Turn a BIM use on or off (ids in bep_get_catalog) and set who is responsible (party),
        why it's worth doing (value) and its process flow. Omitted details are left as they are.
        Turning on 'cobie' also marks COBie handover as required."""
        result, status = _edit(plans_dir, plan, lambda p: {
            "use_id": use_id, "use": bep.set_use(p, use_id, on=on, party=party, value=value, flow=flow)})
        return {"plan": plan, **result, "status": status}

    @server.tool(annotations=EDIT, structured_output=True)
    @_logged
    def bep_set_qc(plan: str, id: str, on: bool = True, who: str | None = None,
                   freq: str | None = None, tool: str | None = None) -> dict[str, Any]:
        """Configure a QC check (visual, clash, standards, integrity: tool, who, freq) or a model
        rule (a0-a8, d0-d8: on, who, freq). Checks can't be turned off; rules have no tool.
        Omitted details are left as they are. In the plan, checks are stored at checks.<id> and
        rules at qc.<id>."""
        result, status = _edit(plans_dir, plan, lambda p: {
            "id": id, "qc": bep.set_qc(p, id, on=on, who=who, freq=freq, tool=tool)})
        return {"plan": plan, **result, "status": status}

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True,
                                             idempotent_hint=True, open_world_hint=False),
                 structured_output=True)
    @_logged
    def bep_save_document(plan: str, document: Literal["plan_md", "plan_html", "layer_definition"],
                          file_name: str) -> dict[str, Any]:
        """Write a document into the plans folder: the finished plan as Markdown (plan_md) or HTML
        (plan_html), or the ISO 13567-3 layer definition file. file_name is a plain name ending
        in .md, .html or .txt; an existing file of that name is replaced."""
        if not DOCUMENT_NAME.fullmatch(file_name or ""):
            raise ToolError(f"'{file_name}' isn't a document file name. Use a name like 'clinic-bep.md' "
                            "(ending in .md, .html or .txt), with no folders.")
        root = Path(os.path.realpath(plans_dir))
        out = Path(os.path.realpath(root / file_name))
        if out.parent != root:
            raise ToolError(f"'{file_name}' points outside the plans folder.")
        p = _load(plans_dir, plan)
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

    return server


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="bep_mcp: %(message)s")
    plans_dir = os.environ.get("BEP_PLANS_DIR")
    if not plans_dir:
        sys.exit("bep_mcp: set BEP_PLANS_DIR to the folder that holds your plan .json files")
    try:
        server = create_server(plans_dir)
    except ValueError as e:
        sys.exit(f"bep_mcp: {e}")
    log.info("serving plans in %s", os.path.realpath(plans_dir))
    server.run("stdio")


if __name__ == "__main__":
    main()
