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
        'uses.coord')."""
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
        """Suggest ISO 13567 layer names for existing layers under the plan's layer profile.
        A null suggestion means a person must decide, e.g. which element an ANNO layer belongs to;
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
        tldraw MCP server's exec tool. Exchanges that match no BIM use are listed at the end."""
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
