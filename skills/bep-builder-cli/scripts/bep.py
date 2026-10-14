#!/usr/bin/env python3
"""bep — build a BIM Execution Plan (BEP) from the command line.

Uses the same plan format as the BIM Execution Plan Builder web app, so a plan
exported from the app's shared store (document "bep/plan") can be validated and
exported here, and a plan built here can be loaded back into the app.

Standard library only (Python 3.8+).

Commands
  init PLAN [--example] [--agency A] [--force]   Create a new plan file
  catalog                                        List BIM uses, agencies, QC rule ids
  show PLAN [PATH]                               Print the plan, or one value (e.g. project.name)
  set PLAN PATH VALUE                            Set one value (e.g. project.agency usace)
  add PLAN LIST key=value [key=value ...]        Append a row (team, goals, exchanges, tech, deliver, standards.codes)
  remove PLAN LIST INDEX                         Remove a row (0-based index)
  use PLAN USE_ID [--off] [--party P] [--value V] [--flow F]
                                                 Turn a BIM use on/off and fill its details
  qc PLAN RULE_ID [--off] [--who W] [--freq F]   Configure a model rule (a0-a8, d0-d8) or check (visual, clash, standards, integrity; also --tool)
  status PLAN                                    Completion of the 11 sections
  validate PLAN [--strict]                       List every TODO; --strict exits 1 if any remain
  check-names [--plan PLAN] NAME ... | --file F  Check NCS layer names and sheet IDs; with --plan, apply
                                                 the plan's status-field setting and ISO 13567 profile
  convert PLAN NAME ... [--anno-element CODE]    Suggest ISO 13567 profile names for existing layers
  definition PLAN [-o OUT]                       Write the ISO 13567-3 layer naming system definition file
  maps-workbook PLAN [PLAN ...] -o OUT.xlsx       Process-map data workbook (Uses, Exchanges, Summary, Keywords)
                                                 for review in Excel or Numbers; needs openpyxl
  apply-maps PLAN FILE [--project NAME] [--dry-run]
                                                 Apply an edited maps workbook (.xlsx/.numbers/.csv) to PLAN
  process-map PLAN [--format mermaid|tldraw] [-o OUT]
                                                 Level 1 process map (section 05): Mermaid text, or a
                                                 script for the tldraw connector's exec tool
  export PLAN --format md|html [-o OUT]          Write the assembled plan
"""
import argparse
import copy
import datetime as _dt
import errno
import html
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import iso13567  # noqa: E402  (bundled next to this script)
import processmap  # noqa: E402

# ---------------------------------------------------------------- reference data
HELP = {
    "layers": "https://help.autodesk.com/view/RVT/2027/ENU/?guid=GUID-3541F82B-9E25-47C5-BE52-3F6C6F40DA02",
    "coords": "https://help.autodesk.com/view/RVT/2027/ENU/?guid=GUID-B82147D6-7EAB-48AB-B0C3-3B160E2DCD17",
    "ifc": "https://help.autodesk.com/view/RVT/2026/ENU/?guid=GUID-E029E3AD-1639-4446-A935-C9796BC34C95",
    "cobie": "https://help.autodesk.com/view/RVT/2027/ENU/?guid=GUID-3ACFF70F-D513-44A1-8579-A226A8530FB9",
    "clash": "https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/How-to-create-a-reusable-Clash-Detective-template-in-Navisworks-Manage-2026.html",
    "usace": "https://www.wbdg.org/FFC/AECCAD/ERDC_ITL_SR_23_1_2023.pdf",
    "ncs": "https://nibs.org/projects/united-states-national-cad-standard-ncs/",
    "psu": "https://psu.pb.unizin.org/bimprojectexecutionplanning/",
}

AGENCIES = {
    "private": "Private / no agency criteria",
    "gsa": "GSA",
    "usace": "USACE / DoD",
    "va": "VA",
    "federal": "Other federal agency",
    "state": "State or local government",
}

USES = [
    ("existing", "Existing conditions modeling", "Planning"),
    ("authoring", "Design authoring", "Design"),
    ("review", "Design reviews", "Design"),
    ("coord", "3D coordination (clash detection)", "Design, Construction"),
    ("drawings", "Drawing generation", "Design"),
    ("code", "Code validation", "Design"),
    ("energy", "Energy analysis", "Design"),
    ("cost", "Cost estimation (5D)", "Design, Construction"),
    ("4d", "Phase planning (4D)", "Construction"),
    ("ifc", "Open exchange (IFC)", "All"),
    ("record", "Record modeling", "Operations"),
    ("cobie", "Asset management (COBie)", "Operations"),
]
USE_IDS = [u[0] for u in USES]

QC_AUTHOR = [
    "Start from the approved template and keep every element in its correct category",
    "Use modeling tools instead of drafting elements by hand",
    "Assign properties and materials to the objects themselves",
    "Host elements on the correct level or host, without large offsets",
    "Let callouts, view references, and titles fill in automatically",
    "Pull schedules, the drawing index, and keynotes from the model",
    "Derive plans, elevations, sections, and details from the model",
    "Don't override dimensions; model real-world sizes after schematic design",
    "Pin or lock items that must not move, such as field-verified conditions",
]
QC_DELIVER = [
    "All models share one coordinate system",
    "All models share units and unit tolerance",
    "All models share level names and the vertical datum",
    "Purge, clean, and audit each model before sharing",
    "Remove unused views, links, and temporary content; keep links relative",
    "No duplicate or erroneous geometry that would distort quantities",
    "Resolve excess warnings; document any exceptions",
    "Provide one composite model per building",
    "Derive contract documents from the model",
]
QC_CHECKS = [
    ("visual", "Visual check", "No unintended content; design intent is followed"),
    ("clash", "Interference check", "Find conflicts between disciplines"),
    ("standards", "Standards check", "Layer, sheet, and naming conventions are followed"),
    ("integrity", "Model integrity check", "No duplicates, warnings resolved, data complete"),
]

SECTIONS = [
    ("01", "project", "Project information"),
    ("02", "team", "Key contacts and roles"),
    ("03", "goals", "BIM goals"),
    ("04", "uses", "BIM uses"),
    ("05", "process", "BIM process"),
    ("06", "exchanges", "Information exchanges"),
    ("07", "collab", "Collaboration procedures"),
    ("08", "tech", "Technology infrastructure"),
    ("09", "standards", "CAD and BIM standards"),
    ("10", "qc", "Quality control"),
    ("11", "deliver", "Model structure and deliverables"),
]
ISO = {
    "01": "4.1, 4.2, 8.2.2", "02": "5.3, 7.2", "03": "6.2", "04": "8.1, 8.3.2",
    "05": "4.4, 8.1", "06": "8.3.3, 8.3.5, 8.4.3",
    "07": "7.4, 7.5.3, 8.4; change control 6.3, 8.3.6", "08": "7.1.3, 7.1.5",
    "09": "7.5.2, 8.3.3", "10": "8.3.4, 8.6, 9.1; failed checks 8.7, 10.2",
    "11": "8.3.5, 8.5.2",
}
ROW_TEMPLATES = {
    "team": {"role": "", "org": "", "name": "", "email": ""},
    "goals": {"goal": "", "uses": ""},
    "exchanges": {"what": "", "from": "", "to": "", "content": "", "lod": "", "due": "", "feeds": ""},
    "tech": {"discipline": "", "software": "", "version": "", "formats": ""},
    "deliver": {"item": "", "format": "", "due": ""},
    "standards.codes": {"code": "", "meaning": ""},
}
STATUS_FIELDS = {"both": "status letters or phase numbers (NCS default; not ISO-conformant)",
                 "status": "status letters A D E F M N T X", "phase": "phase numbers 1-9",
                 "none": "no status field"}
LAYER_FORMATS = {"element": "element format D-MAJR-ELEM-ANNT-S", "view": "drawing-view format D-MAJR-VIEW-ANNT-S"}
SHEET_LEVELS = {"level1": "Level 1 — A-101", "level2": "Level 2 discipline modifiers — AD101",
                "campus": "Level 2 building identifiers — AA101"}


# ---------------------------------------------------------------- plan model
def blank_plan():
    return {
        "v": 1,
        "project": {"name": "", "owner": "", "location": "", "delivery": "", "agency": "private",
                    "phase": "", "start": "", "cui": "", "iso": False},
        "team": [{"role": "BIM manager", "org": "", "name": "", "email": ""}],
        "goals": [{"goal": "", "uses": ""}],
        "uses": {u: {"on": False, "party": "", "value": "", "flow": ""} for u in USE_IDS},
        "exchanges": [dict(ROW_TEMPLATES["exchanges"])],
        "cobie": False,
        "collab": {"cde": "", "sharing": "", "meetings": "", "coords": "", "naming": "", "changes": ""},
        "tech": [{"discipline": "Architectural", "software": "", "version": "", "formats": ""}],
        "standards": {"ncs": "V7 (2024)", "level2": False, "minor": True, "status": True,
                      "sheet": "level1", "codes": [], "plotting": "", "notes": "",
                      "statusField": "status", "iso13567": False, "layerFormat": "element", "sheetCode": "SHET"},
        "qc": {**{f"a{i}": {"on": True, "who": "", "freq": ""} for i in range(len(QC_AUTHOR))},
               **{f"d{i}": {"on": True, "who": "", "freq": ""} for i in range(len(QC_DELIVER))}},
        "checks": {c[0]: {"tool": "", "who": "", "freq": ""} for c in QC_CHECKS},
        "deliver": [dict(ROW_TEMPLATES["deliver"])],
    }


def example_plan():
    p = blank_plan()
    p["project"] = {"name": "EXAMPLE — Riverside Outpatient Clinic", "owner": "Example owner (replace)",
                    "location": "Springfield, IL", "delivery": "Design-bid-build", "agency": "va",
                    "phase": "Design development", "start": "2026-09-01", "cui": "no", "iso": True}
    p["team"] = [
        {"role": "BIM manager", "org": "Example Architects", "name": "Example name", "email": ""},
        {"role": "Architectural lead", "org": "Example Architects", "name": "Example architect", "email": ""},
        {"role": "MEP lead", "org": "Example Engineers", "name": "Example engineer", "email": ""},
        {"role": "Owner representative", "org": "Example owner", "name": "Example owner rep", "email": ""},
    ]
    p["goals"] = [
        {"goal": "Catch MEP conflicts before construction documents are issued", "uses": "3D coordination"},
        {"goal": "Hand over equipment data the facilities team can load directly", "uses": "COBie"},
    ]
    for u in ("authoring", "coord", "drawings", "cobie"):
        p["uses"][u]["on"] = True
    p["uses"]["coord"].update(party="BIM manager (Example name)",
                              value="Reduces field rework on a ceiling-congested clinic",
                              flow="MEP lead uploads NWC exports each Friday → BIM manager runs clash tests → "
                                   "issues assigned in Tuesday coordination meeting → fixes in next upload.")
    p["uses"]["authoring"].update(party="Architectural lead (Example architect)",
                               value="One coordinated model drives drawings, schedules and quantities",
                               flow="Discipline leads model in Revit from the firm template → work-share to ACC daily → BIM manager publishes the composite model each Friday.")
    p["uses"]["drawings"].update(party="Architectural lead (Example architect)",
                               value="Sheets stay consistent with the model as the design changes",
                               flow="Views and schedules are placed from the model → sheets checked against the NCS sheet list → PDF and DWG sets issued at each milestone.")
    p["uses"]["cobie"].update(party="Owner representative (Example owner rep)",
                               value="Facilities team loads equipment data into their CMMS without re-keying",
                               flow="Design team adds COBie parameters to equipment families → contractor fills serial and warranty data during construction → owner rep checks the COBie workbook before closeout.")
    p["cobie"] = True
    p["exchanges"] = [
        {"what": "Coordination model", "from": "MEP lead", "to": "BIM manager",
         "content": "Ducts, pipes, cable tray over 2 in.", "lod": "LOD 300", "due": "Weekly"},
        {"what": "COBie handover", "from": "Contractor", "to": "Owner",
         "content": "Equipment, spaces, zones", "lod": "LOD 500 data", "due": "Closeout"},
    ]
    p["collab"].update(cde="Autodesk Construction Cloud", sharing="Weekly, Friday",
                       meetings="Coordination meeting every Tuesday",
                       coords="Shared coordinates from the site model (survey point at grid A/1)",
                       naming="[Project]-[Originator]-[Discipline]-[Building].rvt, e.g. ROC-EXA-A-B01.rvt",
                       changes="Changes are requested by design change request or owner directive, reviewed in the Tuesday meeting, approved by the owner rep, and logged in the ACC issue log before models are updated.")
    p["tech"] = [
        {"discipline": "Architectural", "software": "Revit", "version": "2026", "formats": "RVT, IFC, DWG"},
        {"discipline": "MEP", "software": "Revit", "version": "2026", "formats": "RVT, NWC"},
        {"discipline": "Coordination", "software": "Navisworks Manage", "version": "2026", "formats": "NWD, NWF"},
    ]
    p["standards"]["plotting"] = "Firm NCS pen table (example-ncs.ctb)"
    p["checks"] = {
        "visual": {"tool": "Revit and Navisworks walkthrough", "who": "Architectural lead (Example architect)", "freq": "Before each model share"},
        "clash": {"tool": "Navisworks Manage Clash Detective", "who": "BIM manager (Example name)", "freq": "Weekly"},
        "standards": {"tool": "bep.py check-names on exported layer and sheet lists", "who": "BIM manager (Example name)", "freq": "Before each submission"},
        "integrity": {"tool": "Revit Warnings review and Purge Unused", "who": "MEP lead (Example engineer)", "freq": "At each design milestone"},
    }
    p["deliver"] = [{"item": "Composite model", "format": "RVT + IFC", "due": "Construction documents"},
                    {"item": "COBie workbook", "format": "XLSX", "due": "Closeout"}]
    return p


def normalize(p):
    """Fill missing keys from the blank plan so older or partial files still work.

    Sections are merged key by key, and every row of a list (team, exchanges, ...) is
    filled from its row template, so a row saved without a field doesn't crash export.
    """
    def merge(base, x):
        if x is None:
            return base
        if not isinstance(base, dict):
            return x
        if not isinstance(x, dict):
            return base   # a section replaced by a scalar (damaged file): fall back to blank
        out = dict(base)
        for k, v in x.items():
            out[k] = merge(base[k], v) if k in base else v
        return out
    plan = merge(blank_plan(), p if isinstance(p, dict) else {})
    for list_path, template in ROW_TEMPLATES.items():
        parent, key = _walk(plan, list_path)
        rows = parent.get(key)
        if not isinstance(rows, list):
            parent[key] = copy.deepcopy(get_path(blank_plan(), list_path))
            continue
        # a row damaged into a scalar (e.g. by an old `set team.0 foo`) becomes a blank row;
        # null fields count as missing, as they do for sections
        parent[key] = [{**template, **{k: v for k, v in row.items() if v is not None}}
                       if isinstance(row, dict) else dict(template) for row in rows]
    return plan


class PlanFileError(ValueError):
    """A plan file that is missing or isn't a plan. The message is written for people."""


def load(path):
    if os.path.isdir(path):   # checked first: on Windows, opening a folder raises PermissionError
        raise PlanFileError(f"{path} is a folder, not a plan file.")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        raise PlanFileError(f"No plan file at {path}. Create one with: bep.py init {path}") from None
    return loads(raw, path)


def loads(raw, label):
    """The normalized plan in a plan file's bytes. `label` names the file in error messages.
    The MCP server uses this to parse the very bytes it takes a plan's version from."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise PlanFileError(f"{label} isn't valid JSON (line {e.lineno}, column {e.colno}: {e.msg}).") from None
    except UnicodeDecodeError:
        raise PlanFileError(f"{label} isn't a text file in UTF-8, so it can't be a plan.") from None
    # Accept the web app's stored document ({"plan": {...}, "updatedBy": ..., ...})
    if isinstance(data, dict) and "plan" in data and "project" not in data:
        data = data["plan"]
    if not isinstance(data, dict):
        kind = {list: "an array", str: "a string", bool: "true or false", type(None): "null"}.get(type(data), "a number")
        raise PlanFileError(f"{label} isn't a plan: it holds {kind}, not a JSON object.")
    std = data.get("standards")
    if isinstance(std, dict) and "statusField" not in std and std.get("status") is False:
        std["statusField"] = "none"   # older plans stored only an on/off flag
    plan = normalize(data)
    plan["standards"]["status"] = plan["standards"]["statusField"] != "none"
    return plan


def save(path, plan):
    """Write the plan atomically: a crash mid-write leaves the previous file intact."""
    plan["standards"]["status"] = plan["standards"].get("statusField", "status") != "none"
    path = os.path.realpath(path)   # write through a symlink to the real plan, keeping the link
    if os.path.exists(path) and not os.access(path, os.W_OK):
        # os.replace would swap out a read-only plan; refuse, as writing in place would
        raise PermissionError(f"{path} is read-only")
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):   # else mkstemp's error names its temporary file, not the plan
        raise FileNotFoundError(errno.ENOENT, "No such folder", folder)
    fd, tmp = tempfile.mkstemp(prefix=".bep-", suffix=".json", dir=folder)
    try:
        # mkstemp creates the file owner-only (0600); keep the plan's existing permissions,
        # or the normal umask-derived mode for a new plan, so shared plans stay readable.
        try:
            mode = os.stat(path).st_mode & 0o7777
        except FileNotFoundError:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(tmp, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _index(k):
    i = int(k)
    if i < 0:
        raise IndexError(f"row index {k} must be 0 or more")
    return i


def _walk(obj, path):
    keys = path.split(".")
    for k in keys[:-1]:
        obj = obj[_index(k)] if isinstance(obj, list) else obj[k]
    return obj, keys[-1]


def get_path(plan, path):
    obj, last = _walk(plan, path)
    return obj[_index(last)] if isinstance(obj, list) else obj[last]


def set_path(plan, path, raw):
    obj, last = _walk(plan, path)
    key = _index(last) if isinstance(obj, list) else last
    if isinstance(obj, dict) and key not in obj:
        raise ValueError(f"'{last}' isn't a field here. Fields: {', '.join(obj)}")
    current = obj[key]
    if isinstance(current, (dict, list)):
        kind = "list" if isinstance(current, list) else "section"
        hint = ("use 'add' or 'remove' for rows" if isinstance(current, list)
                else f"set one of its fields: {', '.join(current)}")
        raise ValueError(f"'{path}' is a {kind}, not a single value; {hint}")
    if isinstance(current, bool):
        word = raw.strip().lower()
        if word not in ("1", "true", "yes", "y", "on", "0", "false", "no", "n", "off"):
            raise ValueError(f"expected yes or no, got '{raw}'")
        value = word in ("1", "true", "yes", "y", "on")
    else:
        value = raw
    if path == "project.agency" and value not in AGENCIES:
        raise ValueError(f"agency must be one of: {', '.join(AGENCIES)}")
    if path == "standards.sheet" and value not in SHEET_LEVELS:
        raise ValueError(f"sheet must be one of: {', '.join(SHEET_LEVELS)}")
    if path == "project.cui" and value not in ("", "yes", "no"):
        raise ValueError("cui must be yes, no, or empty")
    if path == "standards.statusField" and value not in STATUS_FIELDS:
        raise ValueError(f"statusField must be one of: {', '.join(STATUS_FIELDS)}")
    if path == "standards.sheetCode":
        value = value.upper()
        if not re.fullmatch(r"[A-Z0-9~]{4}", value):
            raise ValueError("sheetCode must be exactly 4 letters, digits or ~")
    if path == "standards.layerFormat" and value not in LAYER_FORMATS:
        raise ValueError(f"layerFormat must be one of: {', '.join(LAYER_FORMATS)}")
    obj[key] = value
    return value


SHEET_CODE_MEANING = "Sheet-level annotation (title blocks, general notes, legends, stamps); replaces ANNO"


def disclosure_codes(plan):
    """User-defined codes for the Compliance Disclosure Statement, including the sheet code under ISO."""
    s = plan["standards"]
    codes = [c for c in s["codes"] if filled(c.get("code", ""))]
    sc = s.get("sheetCode", "")
    if s["iso13567"] and filled(sc) and not any(c["code"].upper() == sc for c in codes):
        codes = [{"code": sc, "meaning": SHEET_CODE_MEANING}] + codes
    return codes


def profile_for(plan):
    s = plan["standards"]
    status = s["statusField"] if s["statusField"] in ("status", "phase", "none") else "status"
    return iso13567.Profile(level=2 if s["level2"] else 1, fmt=s["layerFormat"], status=status)


def filled(v):
    return v.strip() != "" if isinstance(v, str) else bool(v)


# ---------------------------------------------------------------- completion
def section_status(plan, sid):
    p = plan

    def ratio(flags):
        n = sum(1 for f in flags if f)
        return "empty" if n == 0 else "done" if n == len(flags) else "partial"

    on = [u for u in USE_IDS if p["uses"][u]["on"]]
    if sid == "project":
        return ratio([filled(p["project"][k]) for k in ("name", "owner", "location", "delivery", "phase")])
    if sid == "team":
        if not any(filled(t["role"]) and filled(t["name"]) for t in p["team"]):
            return "empty"
        return "done" if all(filled(t["name"]) for t in p["team"]) else "partial"
    if sid == "goals":
        return "done" if any(filled(g["goal"]) for g in p["goals"]) else "empty"
    if sid == "uses":
        if not on:
            return "empty"
        return "done" if all(filled(p["uses"][u]["party"]) for u in on) else "partial"
    if sid == "process":
        return "empty" if not on else ratio([filled(p["uses"][u]["flow"]) for u in on])
    if sid == "exchanges":
        if not any(filled(e["what"]) for e in p["exchanges"]):
            return "empty"
        return "done" if all(filled(e["what"]) and filled(e["lod"]) and filled(e["due"]) for e in p["exchanges"]) else "partial"
    if sid == "collab":
        return ratio([filled(v) for v in p["collab"].values()])
    if sid == "tech":
        if not any(filled(t["software"]) for t in p["tech"]):
            return "empty"
        return "done" if all(filled(t["software"]) and filled(t["version"]) for t in p["tech"]) else "partial"
    if sid == "standards":
        usace = p["project"]["agency"] == "usace"
        return ratio([filled(p["standards"]["ncs"]), filled(p["standards"]["plotting"]),
                      (not usace) or filled(p["project"]["cui"])])
    if sid == "qc":
        return ratio([filled(p["checks"][c[0]]["who"]) and filled(p["checks"][c[0]]["freq"]) for c in QC_CHECKS])
    if sid == "deliver":
        if not any(filled(d["item"]) for d in p["deliver"]):
            return "empty"
        return "done" if all(filled(d["item"]) and filled(d["due"]) for d in p["deliver"]) else "partial"
    return "empty"


# ---------------------------------------------------------------- document model
class Todo:
    def __init__(self, msg, section):
        self.msg, self.section = msg, section


def build_doc(plan):
    p = plan
    doc = []
    cur = {"code": ""}

    def val(v, todo):
        return v if filled(v) else Todo(todo, cur["code"])

    def sec(code, title, blocks_fn):
        cur["code"] = code
        doc.append({"code": code, "title": title, "blocks": blocks_fn()})

    on = [u for u in USES if p["uses"][u[0]]["on"]]
    usace = p["project"]["agency"] == "usace"

    sec("01", "Project information", lambda: [{"kv": [
        ("Project", val(p["project"]["name"], "project name")),
        ("Owner", val(p["project"]["owner"], "owner")),
        ("Location", val(p["project"]["location"], "location")),
        ("Delivery method", val(p["project"]["delivery"], "delivery method")),
        ("Current phase", val(p["project"]["phase"], "phase")),
        ("Effective date", val(p["project"]["start"], "date")),
        ("Governing criteria", AGENCIES.get(p["project"]["agency"], p["project"]["agency"]) +
         (" — A/E/C Graphics Standard R2.2 applies over NCS" if usace else "")),
    ]}])

    def team():
        rows = [t for t in p["team"] if filled(t["role"]) or filled(t["name"])]
        if not rows:
            return [{"p": val("", "list the team and their roles")}]
        return [{"table": (["Role", "Organization", "Name", "Email"],
                           [[val(t["role"], "role"), val(t["org"], f"{t['role'] or 'team member'}: organization"), val(t["name"], f"{t['role'] or 'team member'}: name"), t["email"] or "—"] for t in rows])}]
    sec("02", "Key contacts and roles", team)

    def goals():
        rows = [g for g in p["goals"] if filled(g["goal"])]
        if not rows:
            return [{"p": val("", "state the project's BIM goals")}]
        return [{"table": (["Priority", "Goal", "Related BIM uses"],
                           [[str(i + 1), g["goal"], val(g["uses"], f"goal {i + 1}: related uses")] for i, g in enumerate(rows)])}]
    sec("03", "BIM goals", goals)

    def uses():
        if not on:
            return [{"p": val("", "select BIM uses")}]
        return [{"table": (["BIM use", "Phase", "Responsible", "Value"],
                           [[n, ph, val(p["uses"][u]["party"], f"{n}: responsible party"), val(p["uses"][u]["value"], f"{n}: why it's worth doing")] for u, n, ph in on])}]
    sec("04", "BIM uses", uses)

    def process():
        if not on:
            return [{"p": val("", "describe the process for each BIM use")}]
        return [{"kv": [(n, val(p["uses"][u]["flow"], f"{n}: describe the flow")) for u, n, _ in on]}]
    sec("05", "BIM process", process)

    def exchanges():
        rows = [[e["what"], f"{e['from'] or '?'} → {e['to'] or '?'}", val(e["content"], f"{e['what']}: model content"),
                 val(e["lod"], f"{e['what']}: LOD"), val(e["due"], f"{e['what']}: due")] for e in p["exchanges"] if filled(e["what"])]
        if p["cobie"] and not any(re.search("cobie", e["what"], re.I) for e in p["exchanges"]):
            rows.append(["COBie facility data", "Contractor → Owner", "Equipment, spaces, zones, systems",
                         "As-built data", val("", "COBie facility data: due date")])
        if not rows:
            return [{"p": val("", "define information exchanges")}]
        return [{"table": (["Exchange", "From → To", "Model content", "LOD", "Due"], rows)}]
    sec("06", "Information exchanges", exchanges)

    c = p["collab"]
    sec("07", "Collaboration procedures", lambda: [{"kv": [
        ("Common data environment", val(c["cde"], "where files live")),
        ("Model sharing", val(c["sharing"], "frequency")),
        ("Coordination meetings", val(c["meetings"], "meeting schedule")),
        ("Shared coordinates", val(c["coords"], "coordinate source")),
        ("Model file naming", val(c["naming"], "naming convention")),
        ("Change control", val(c["changes"], "change process")),
    ]}])

    def tech():
        rows = [t for t in p["tech"] if filled(t["discipline"]) or filled(t["software"])]
        if not rows:
            return [{"p": val("", "list software by discipline")}]
        return [{"table": (["Discipline", "Software", "Version", "Formats"],
                           [[val(t["discipline"], "discipline"), val(t["software"], f"{t['discipline'] or 'discipline'}: software"),
                             val(t["version"], f"{t['discipline'] or 'discipline'}: version"), t["formats"] or "—"] for t in rows])}]
    sec("08", "Technology infrastructure", tech)

    def standards():
        s = p["standards"]
        sf = s["statusField"]
        if s["iso13567"]:
            prof = profile_for(p)
            layer_kv = [("Layer naming", "NCS layer format in conceptual conformance with ISO 13567 — "
                         + prof.describe() + f". Example: {prof.example()}"),
                        ("ANNO", "Not used. Annotation codes (TEXT, DIMS, NOTE, NPLT…) go in the reserved annotation "
                         "minor group of the element they describe" +
                         (f"; sheet-level annotation (title blocks, general notes) uses element code {s['sheetCode']}, "
                          f"e.g. G-{s['sheetCode']}-____-TTLB" if filled(s.get("sheetCode", "")) else "")),
                        ("Status field", STATUS_FIELDS[sf] if sf != "both" else val("", "ISO needs status OR phase — set statusField to status, phase or none")),
                        ("Layer naming system definition file", "ISO 13567-3 definition file delivered with all CAD files")]
        else:
            opt = [x for x, on_ in (("discipline modifiers (AD-WALL)", s["level2"]),
                                    ("minor groups (A-WALL-FULL)", s["minor"])) if on_]
            layer_kv = [("Layer naming", "Discipline designator + major group required (A-WALL)" +
                         ("; also uses " + ", ".join(opt) if opt else "; optional fields not used")),
                        ("Status field", STATUS_FIELDS[sf] + (" — e.g. A-WALL-D" if sf == "status" else " — e.g. A-WALL-2" if sf == "phase" else ""))]
        blocks = [{"kv": [
            ("Governing standard", f"U.S. National CAD Standard {s['ncs']}"),
            *layer_kv,
            ("Sheet identification", SHEET_LEVELS.get(s["sheet"], s["sheet"]) + "; 5 characters, sequence 01–99"),
            ("Drawing set order", "G H V B C L S A I Q F P D M E W T R X Z O"),
            ("Plotting", f"{s['plotting']}; NCS line widths 0.13–2.00 mm" if filled(s["plotting"]) else val("", "plot style file")),
            ("Schedules", "Minimum columns: Mark, Item Description, Distinguishing Feature; data from the model"),
        ]}]
        codes = disclosure_codes(p)
        if codes:
            blocks += [{"sub": "User-defined codes (Compliance Disclosure Statement)"},
                       {"table": (["Code", "Meaning"], [[x["code"], val(x.get("meaning", ""), f"{x['code']}: meaning")] for x in codes])}]
        if usace:
            cui = p["project"]["cui"]
            blocks += [{"sub": "USACE / DoD overrides (A/E/C Graphics Standard R2.2)"}, {"list": [
                "ANSI D contract sheets (E/F oversized; ISO A1 international)",
                "Arial, all capitals; 3/32 in. text (building), 1/8 in. (civil); 3/16 in. titles",
                "Existing conditions screened 20–60%; demolition plans separate",
                "Revisions: 1, 2, 3 for amendments; A, B, C for modifications",
                "Drawings contain CUI: mark top and bottom of every sheet and add the cover designation block" if cui == "yes"
                else "Drawings do not contain CUI" if cui == "no" else val("", "CUI decision"),
            ]}]
        if filled(s["notes"]):
            blocks.append({"p": s["notes"]})
        return blocks
    sec("09", "CAD and BIM standards", standards)

    def qc():
        checks = [[n, purpose, val(p["checks"][cid]["tool"], f"{n}: tool"), val(p["checks"][cid]["who"], f"{n}: responsible"),
                   val(p["checks"][cid]["freq"], f"{n}: frequency")] for cid, n, purpose in QC_CHECKS]
        rules = [(f"a{i}", r) for i, r in enumerate(QC_AUTHOR)] + [(f"d{i}", r) for i, r in enumerate(QC_DELIVER)]
        rule_rows = [[r, p["qc"][k]["who"] or "BIM manager", p["qc"][k]["freq"] or "Before each model share"]
                     for k, r in rules if p["qc"][k]["on"]]
        return [{"table": (["Check", "Purpose", "Tool", "Responsible", "Frequency"], checks)},
                {"sub": "Model rules (NCS BIM Implementation)"},
                {"table": (["Rule", "Responsible", "When"], rule_rows)}]
    sec("10", "Quality control", qc)

    def deliver():
        rows = [[d["item"], val(d["format"], f"{d['item']}: format"), val(d["due"], f"{d['item']}: due")] for d in p["deliver"] if filled(d["item"])]
        if p["cobie"] and not any(re.search("cobie", r[0], re.I) for r in rows):
            rows.append(["COBie workbook", "XLSX / IFC COBie", val("", "COBie workbook: due date")])
        if not rows:
            return [{"p": val("", "list final deliverables")}]
        return [{"table": (["Deliverable", "Format", "Due"], rows)}]
    sec("11", "Model structure and deliverables", deliver)
    return doc


def collect_todos(doc):
    out = []

    def walk(x):
        if isinstance(x, Todo):
            out.append(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    walk(doc)
    return out


def _md(v):
    s = f"**TODO: {v.msg}**" if isinstance(v, Todo) else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def _h(v):
    return f'<span class="todo">TODO: {html.escape(v.msg)}</span>' if isinstance(v, Todo) else html.escape(str(v)).replace("\n", "<br>")


def to_markdown(plan, doc):
    p = plan
    out = [f"# BIM Execution Plan — {p['project']['name'] or 'Untitled project'}", "",
           f"Prepared with bep-builder-cli · {_dt.date.today().isoformat()}", ""]
    for s in doc:
        out += [f"## {s['code']}. {s['title']}", ""]
        if p["project"]["iso"]:
            out += [f"*ISO 9001:2015 — {ISO[s['code']]}*", ""]
        if s["code"] == "05" and any(p["uses"][u]["on"] for u in USE_IDS):
            out += ["**Level 1 process map**", "", "```mermaid",
                    processmap.to_mermaid(processmap.build(p, USES)).rstrip(), "```", ""]
        for b in s["blocks"]:
            if "p" in b:
                out += [_md(b["p"]), ""]
            if "sub" in b:
                out += [f"### {b['sub']}", ""]
            if "list" in b:
                out += [f"- {_md(i)}" for i in b["list"]] + [""]
            if "kv" in b:
                out += [f"- **{k}:** {_md(v)}" for k, v in b["kv"]] + [""]
            if "table" in b:
                head, rows = b["table"]
                out += [f"| {' | '.join(head)} |", "|" + "|".join("---" for _ in head) + "|"]
                out += [f"| {' | '.join(_md(c) for c in r)} |" for r in rows] + [""]
    out += ["## Sources", "", f"- U.S. National CAD Standard — {HELP['ncs']}",
            f"- BIM Project Execution Planning Guide (Penn State) — {HELP['psu']}"]
    if p["project"]["agency"] == "usace":
        out.append(f"- A/E/C Graphics Standard R2.2 — {HELP['usace']}")
    return "\n".join(out) + "\n"


def to_html(plan, doc):
    p = plan
    name = html.escape(p["project"]["name"] or "Untitled project")
    parts = [f"<h1>BIM Execution Plan — {name}</h1>"]
    for s in doc:
        parts.append(f"<h2>{s['code']}. {html.escape(s['title'])}</h2>")
        if p["project"]["iso"]:
            parts.append(f'<p class="iso">ISO 9001:2015 — {html.escape(ISO[s["code"]])}</p>')
        for b in s["blocks"]:
            if "p" in b:
                parts.append(f"<p>{_h(b['p'])}</p>")
            if "sub" in b:
                parts.append(f"<h3>{html.escape(b['sub'])}</h3>")
            if "list" in b:
                parts.append("<ul>" + "".join(f"<li>{_h(i)}</li>" for i in b["list"]) + "</ul>")
            if "kv" in b:
                parts.append("<ul>" + "".join(f"<li><b>{html.escape(k)}:</b> {_h(v)}</li>" for k, v in b["kv"]) + "</ul>")
            if "table" in b:
                head, rows = b["table"]
                parts.append("<table><thead><tr>" + "".join(f"<th>{html.escape(x)}</th>" for x in head) + "</tr></thead><tbody>" +
                             "".join("<tr>" + "".join(f"<td>{_h(c)}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table>")
    css = ("body{font:15px/1.55 Arial,Helvetica,sans-serif;color:#16212a;max-width:900px;margin:32px auto;padding:0 20px}"
           "h1{text-transform:uppercase;font-size:24px}h2{border-bottom:1px solid #ccc;padding-bottom:4px;margin-top:28px;font-size:18px}"
           "table{border-collapse:collapse;width:100%;font-size:14px;margin:8px 0}th,td{border:1px solid #ccc;padding:6px 8px;text-align:left;vertical-align:top}"
           "th{background:#eef2f1}.todo{color:#c2361f;font-weight:bold}.iso{color:#56646e;font:12px monospace}")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>BEP — {name}</title><style>{css}</style></head><body>{''.join(parts)}</body></html>\n")


# ---------------------------------------------------------------- NCS name checker
DISC = set("GHVBCLSAIQFPDMEWTRXZO")
STATUS = set("ADEFMNTX123456789")
CODE = re.compile(r"^[A-Z0-9~]{4}$")
SHEET = re.compile(r"^(?:([A-Z])[-_]|([A-Z]{2}))([0-9])([0-9]{2})(?:-([A-Z0-9]{1,3}))?$")


def check_layer(n, status_field="both"):
    if " " in n or "_" in n:
        return ["separate fields with hyphens, not underscores or spaces"]
    pr = []
    if n != n.upper():
        pr.append("use uppercase only")
    f = n.upper().split("-")
    d, rest = f[0], f[1:]
    if not 1 <= len(d) <= 2 or d[0] not in DISC or not d.isalpha():
        pr.append(f"'{d}' is not a known discipline designator")
    if not rest:
        return pr + ["missing the 4-character major group"]
    if len(rest) > 1 and len(rest[-1]) == 1:
        st = rest.pop()
        if st not in STATUS:
            pr.append(f"'{st}' is not a valid status code")
        elif status_field == "none":
            pr.append(f"this project doesn't use a status field; remove '-{st}'")
        elif status_field == "status" and st.isdigit():
            pr.append(f"'{st}' is a phase number; this project uses status letters")
        elif status_field == "phase" and not st.isdigit():
            pr.append(f"'{st}' is a status letter; this project uses phase numbers")
    major, minors = rest[0], rest[1:]
    if not CODE.match(major):
        pr.append(f"major group '{major}' must be exactly 4 letters, digits or ~")
    if len(minors) > 2:
        pr.append("no more than two minor groups are allowed")
    for m in minors:
        if not CODE.match(m):
            pr.append(f"minor group '{m}' must be exactly 4 letters, digits or ~")
    return pr


def check_sheet(n):
    u = n.upper()
    m = SHEET.match(u)
    if not m:
        if re.match(r"^[A-Z][0-9]{3}", u):
            return ["a 1-letter discipline needs a hyphen (e.g. S-501)"]
        if re.match(r"^[A-Z]{2}-[0-9]", u):
            return ["a 2-letter discipline takes no hyphen (e.g. AD101)"]
        if re.match(r"^[A-Z]{1,2}-?[0-9]{4,}", u):
            return ["sequence number must be exactly 2 digits (01-99)"]
        return ["doesn't match the 5-character sheet format (A-101 or AD101)"]
    pr = []
    letter = m.group(1) or m.group(2)[0]
    if n != u:
        pr.append("use uppercase only")
    if letter not in DISC:
        pr.append(f"'{letter}' is not a known discipline designator")
    if m.group(4) == "00":
        pr.append("sequence 00 isn't permitted; start at 01")
    return pr


def is_sheet(n):
    return bool(re.match(r"^[A-Za-z]{1,2}[-_]?\d", n))


# ---------------------------------------------------------------- plan operations
# The logic behind the editing and checking commands, as plain functions: they change the
# plan or return data, and raise ValueError with a message for people. The commands below
# print and exit around them; other callers (such as an MCP server) use them directly.
def _check_list(list_path):
    if list_path not in ROW_TEMPLATES:
        raise ValueError(f"Unknown list '{list_path}'. Lists: {', '.join(ROW_TEMPLATES)}")


def add_row(plan, list_path, fields):
    """Add a row to a list, filling the first placeholder row instead of appending after it."""
    _check_list(list_path)
    row = dict(ROW_TEMPLATES[list_path])
    for k, v in fields.items():
        if k not in row:
            raise ValueError(f"'{k}' isn't a field of {list_path}. Fields: {', '.join(row)}")
        row[k] = v
    lst = get_path(plan, list_path)
    # A placeholder row is blank, or still exactly the new-plan default.
    try:
        default_row = get_path(blank_plan(), list_path)[0]
    except IndexError:
        default_row = None
    empty = next((i for i, r in enumerate(lst)
                  if r == default_row or not any(filled(x) for x in r.values())), None)
    if empty is not None:
        lst[empty] = row
    else:
        lst.append(row)
    return row


def remove_row(plan, list_path, index):
    """Remove and return a row (0-based index)."""
    _check_list(list_path)
    lst = get_path(plan, list_path)
    if not 0 <= index < len(lst):
        raise ValueError(f"{list_path} has {len(lst)} rows; index {index} doesn't exist")
    return lst.pop(index)


def set_use(plan, use_id, on=True, party=None, value=None, flow=None):
    """Turn a BIM use on or off and set the details given (None leaves a field as it is)."""
    if use_id not in USE_IDS:
        raise ValueError(f"Unknown BIM use '{use_id}'. Run 'catalog' for ids.")
    u = plan["uses"][use_id]
    u["on"] = on
    for k, v in (("party", party), ("value", value), ("flow", flow)):
        if v is not None:
            u[k] = v
    if use_id == "cobie" and on:
        plan["cobie"] = True
    return u


def set_qc(plan, qc_id, on=True, who=None, freq=None, tool=None):
    """Configure a QC check (visual, clash, standards, integrity) or a model rule (a0-a8, d0-d8)."""
    if qc_id in plan["checks"]:
        if not on:
            raise ValueError(f"Checks can't be turned off; '{qc_id}' always appears in section 10.")
        c = plan["checks"][qc_id]
        for k, v in (("tool", tool), ("who", who), ("freq", freq)):
            if v is not None:
                c[k] = v
        return c
    if qc_id in plan["qc"]:
        if tool is not None:
            raise ValueError("--tool applies to checks (visual, clash, standards, integrity), not model rules.")
        r = plan["qc"][qc_id]
        r["on"] = on
        for k, v in (("who", who), ("freq", freq)):
            if v is not None:
                r[k] = v
        return r
    raise ValueError(f"Unknown rule or check '{qc_id}'. Run 'catalog' for ids.")


def check_names(names, plan=None):
    """Check layer names and sheet ids, applying the plan's status field and ISO 13567 profile.

    Returns {"profile": description or None, "status_field": id or None,
             "results": [{"name", "kind": "layer"|"sheet", "problems": [...]}]}.
    """
    prof = profile_for(plan) if plan and plan["standards"]["iso13567"] else None
    sf = plan["standards"]["statusField"] if plan else "both"
    results = []
    for n in names:
        kind = "sheet" if is_sheet(n) else "layer"
        if kind == "sheet":
            pr = check_sheet(n)
        else:
            pr = iso13567.check(n, prof) if prof else check_layer(n, sf)
        results.append({"name": n, "kind": kind, "problems": pr})
    return {"profile": prof.describe() if prof else None,
            "status_field": sf if plan else None,
            "results": results}


def convert_layers(plan, names, anno_element=None):
    """Suggest ISO 13567 names for existing layers under the plan's profile.

    Returns {"profile", "anno_element", "sheet_code",
             "results": [{"name", "suggested": name or None, "notes": [...]}]}.
    A suggestion of None means a person has to decide (e.g. which element an ANNO layer belongs to).
    """
    prof = profile_for(plan)
    elem = anno_element.upper() if anno_element else None
    sheet = plan["standards"].get("sheetCode") or None
    results = []
    for n in names:
        new, notes = iso13567.convert(n, prof, elem, sheet)
        results.append({"name": n, "suggested": new, "notes": notes})
    return {"profile": prof.describe(), "anno_element": elem, "sheet_code": sheet, "results": results}


def layer_definition(plan):
    """The ISO 13567-3 layer naming system definition file, with the plan's user-defined codes."""
    text = iso13567.definition_file(profile_for(plan), plan["project"]["name"] or "Project")
    codes = disclosure_codes(plan)
    if codes:
        text += "\n# User-defined codes (also on the NCS Compliance Disclosure Statement)\nCode\tMeaning\n"
        text += "".join(f"{c['code']}\t{c.get('meaning', '')}\n" for c in codes)
    return text


# ---------------------------------------------------------------- commands
def cmd_init(a):
    if os.path.exists(a.plan) and not a.force:
        sys.exit(f"{a.plan} already exists. Use --force to overwrite it.")
    plan = example_plan() if a.example else blank_plan()
    if a.agency:
        set_path(plan, "project.agency", a.agency)
    save(a.plan, plan)
    print(f"Created {a.plan}" + (" (example project — replace the EXAMPLE values)" if a.example else ""))


def cmd_catalog(a):
    print("BIM uses (bep use PLAN <id>):")
    for u, n, ph in USES:
        print(f"  {u:<10} {n}  [{ph}]")
    print("\nAgencies (bep set PLAN project.agency <id>):")
    for k, v in AGENCIES.items():
        print(f"  {k:<10} {v}")
    print("\nStatus field (bep set PLAN standards.statusField <id>):")
    for k, v in STATUS_FIELDS.items():
        print(f"  {k:<10} {v}")
    print("\nISO 13567 layer formats (bep set PLAN standards.layerFormat <id>; turn on with standards.iso13567 yes):")
    for k, v in LAYER_FORMATS.items():
        print(f"  {k:<10} {v}")
    print("\nSheet-level annotation code (bep set PLAN standards.sheetCode <4 chars>): replaces ANNO on title\n"
          "  blocks, general notes, legends and stamps under ISO 13567. Firm default: SHET")
    print("\nSheet levels (bep set PLAN standards.sheet <id>):")
    for k, v in SHEET_LEVELS.items():
        print(f"  {k:<10} {v}")
    print("\nModel rules (bep qc PLAN <id>):")
    for i, r in enumerate(QC_AUTHOR):
        print(f"  a{i:<9} {r}")
    for i, r in enumerate(QC_DELIVER):
        print(f"  d{i:<9} {r}")
    print("\nChecks (bep qc PLAN <id> --tool T --who W --freq F):")
    for cid, n, _ in QC_CHECKS:
        print(f"  {cid:<10} {n}")
    print("\nLists for add/remove: " + ", ".join(ROW_TEMPLATES))


def cmd_show(a):
    plan = load(a.plan)
    try:
        value = get_path(plan, a.path) if a.path else plan
    except (KeyError, IndexError, ValueError, TypeError):
        sys.exit(f"{a.path} isn't in this plan. Run 'show {a.plan}' to see its fields.")
    print(json.dumps(value, indent=2, ensure_ascii=False) if isinstance(value, (dict, list)) else value)


def cmd_set(a):
    plan = load(a.plan)
    try:
        v = set_path(plan, a.path, a.value)
    except (KeyError, IndexError, ValueError, TypeError) as e:
        sys.exit(f"Couldn't set {a.path}: {e}")
    save(a.plan, plan)
    print(f"{a.path} = {v!r}")


def cmd_add(a):
    plan = load(a.plan)
    try:
        _check_list(a.list)
        fields = {}
        for kv in a.fields:
            if "=" not in kv:
                raise ValueError(f"Expected key=value, got '{kv}'")
            k, v = kv.split("=", 1)
            fields[k] = v
        row = add_row(plan, a.list, fields)
    except ValueError as e:
        sys.exit(str(e))
    save(a.plan, plan)
    print(f"Added to {a.list}: {row}")


def cmd_remove(a):
    plan = load(a.plan)
    try:
        removed = remove_row(plan, a.list, a.index)
    except ValueError as e:
        sys.exit(str(e))
    save(a.plan, plan)
    print(f"Removed from {a.list}: {removed}")


def cmd_use(a):
    plan = load(a.plan)
    try:
        u = set_use(plan, a.use_id, on=not a.off, party=a.party, value=a.value, flow=a.flow)
    except ValueError as e:
        sys.exit(str(e))
    save(a.plan, plan)
    print(f"{a.use_id}: {u}")


def cmd_qc(a):
    plan = load(a.plan)
    try:
        out = set_qc(plan, a.rule_id, on=not a.off, who=a.who, freq=a.freq, tool=a.tool)
    except ValueError as e:
        sys.exit(str(e))
    save(a.plan, plan)
    print(f"{a.rule_id}: {out}")


def cmd_status(a):
    plan = load(a.plan)
    marks = {"done": "■ done", "partial": "◧ partial", "empty": "□ empty"}
    done = 0
    for code, sid, title in SECTIONS:
        st = section_status(plan, sid)
        done += st == "done"
        print(f"{code}  {title:<34} {marks[st]}")
    todos = collect_todos(build_doc(plan))
    print(f"\n{done} of 11 sections complete · {len(todos)} TODO items")


def cmd_validate(a):
    plan = load(a.plan)
    todos = collect_todos(build_doc(plan))
    titles = {c: t for c, _, t in SECTIONS}
    if not todos:
        print("No TODO items. The plan is complete.")
        return
    last = None
    for t in todos:
        if t.section != last:
            print(f"\n{t.section}. {titles[t.section]}")
            last = t.section
        print(f"  - {t.msg}")
    print(f"\n{len(todos)} TODO items")
    if a.strict:
        sys.exit(1)


def cmd_check_names(a):
    names = list(a.names)
    if a.file:
        with open(a.file, encoding="utf-8") as fh:
            names += [x for line in fh for x in re.split(r"[\s,]+", line) if x]
    if not names:
        sys.exit("Give names as arguments or with --file")
    res = check_names(names, load(a.plan) if a.plan else None)
    if res["profile"]:
        print(f"ISO 13567 profile: {res['profile']}\n")
    elif res["status_field"]:
        print(f"Status field: {STATUS_FIELDS[res['status_field']]}\n")
    print("| Name | Kind | Valid? | Problem |\n|---|---|---|---|")
    for r in res["results"]:
        pr = r["problems"]
        print(f"| {r['name']} | {r['kind']} | {'No' if pr else 'Yes'} | {'; '.join(pr) or '—'} |")
    bad = sum(1 for r in res["results"] if r["problems"])
    print(f"\n{len(names) - bad} valid, {bad} to fix")


def cmd_convert(a):
    plan = load(a.plan)
    res = convert_layers(plan, a.names, a.anno_element)
    if not plan["standards"]["iso13567"]:
        print("Note: ISO 13567 isn't turned on in this plan (standards.iso13567); converting with its "
              "settings anyway.\n")
    print(f"Profile: {res['profile']}\n")
    print("| Original | Suggested | Notes |\n|---|---|---|")
    if res["sheet_code"] and not res["anno_element"]:
        print(f"Sheet-level annotation (title blocks, general notes…) moves to {res['sheet_code']}; other ANNO layers need their element.\n")
    for r in res["results"]:
        print(f"| {r['name']} | {r['suggested'] or '— needs a decision'} | {'; '.join(r['notes']) or '—'} |")


def cmd_definition(a):
    text = layer_definition(load(a.plan))
    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote {a.output}")
    else:
        sys.stdout.write(text)


def cmd_process_map(a):
    plan = load(a.plan)
    model = processmap.build(plan, USES)
    text = processmap.to_tldraw(model) if a.format == "tldraw" else processmap.to_mermaid(model)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote {a.output} ({sum(len(v) for v in model['columns'].values())} boxes, "
              f"{len(model['edges'])} arrows, {len(model['notes'])} unplaced exchanges)")
    else:
        sys.stdout.write(text)


def use_name_to_id():
    return {n: u for u, n, _ in USES}


def exchange_feeds(plan, ex):
    """The use an exchange feeds: its explicit 'feeds' value, else the keyword match."""
    if ex.get("feeds") and plan["uses"].get(ex["feeds"], {}).get("on"):
        return ex["feeds"]
    text = (ex.get("what", "") + " " + ex.get("content", "")).lower()
    for uid, words in processmap.USE_KEYWORDS.items():
        if plan["uses"].get(uid, {}).get("on") and any(w in text for w in words):
            return uid
    return ""


def cmd_maps_workbook(a):
    import mapsbook
    plans = [(load(path)["project"]["name"] or path, load(path)) for path in a.plans]
    mapsbook.build(plans, a.output)
    print(f"Wrote {a.output} ({len(plans)} project{'s' if len(plans) != 1 else ''}). Formulas calculate when "
          "it's opened in Excel or Numbers.")


def cmd_apply_maps(a):
    from read_tables import read
    plan = load(a.plan)
    project = a.project or plan["project"]["name"]
    data = read(a.file)
    def find(*cols):
        for t in data["tables"]:
            if all(c in t["header"] for c in cols):
                return t
        return None
    uses_t = find("Project", "BIM use", "Selected (Y/N)", "Responsible")
    ex_t = find("Project", "Exchange", "Feeds use")
    if not uses_t and not ex_t:
        sys.exit("Couldn't find the Uses or Exchanges table in that file. Is it the maps workbook?")
    names = use_name_to_id()
    changes = []

    if uses_t:
        h = uses_t["header"]
        rows = [r for r in uses_t["rows"] if str(r[h.index("Project")] or "").strip() == project]
        if not rows:
            sys.exit(f"No rows for project '{project}' in the Uses table. Pass --project with the name used in the sheet.")
        for r in rows:
            uid = names.get(str(r[h.index("BIM use")] or "").strip())
            if not uid:
                continue
            on = str(r[h.index("Selected (Y/N)")] or "").strip().upper() == "Y"
            party = str(r[h.index("Responsible")] or "").strip()
            u = plan["uses"][uid]
            if u["on"] != on:
                changes.append(f"{'Selected' if on else 'Deselected'} {r[h.index('BIM use')]}")
                u["on"] = on
            if (u.get("party") or "") != party:
                changes.append(f"{r[h.index('BIM use')]}: responsible '{u.get('party') or '—'}' → '{party or '—'}'")
                u["party"] = party
        if plan["uses"]["cobie"]["on"] and not plan["cobie"]:
            plan["cobie"] = True
            changes.append("COBie handover now required (COBie use selected)")

    if ex_t:
        h = ex_t["header"]
        col = lambda r, name: str(r[h.index(name)] or "").strip() if name in h else ""
        new = []
        for r in ex_t["rows"]:
            if col(r, "Project") != project or not col(r, "Exchange"):
                continue
            row = {"what": col(r, "Exchange"), "from": col(r, "From"), "to": col(r, "To"),
                   "content": col(r, "Model content"), "lod": col(r, "LOD"), "due": col(r, "Due"),
                   "feeds": names.get(col(r, "Feeds use"), "")}
            auto = "added:" in col(r, "Note") and not any(row[k] for k in ("from", "to", "content", "lod", "due"))
            if auto:
                continue   # untouched placeholder the plan adds by itself
            new.append(row)
        old = [e for e in plan["exchanges"] if e.get("what", "").strip()]
        key = lambda e: e["what"].lower()
        oldk, newk = {key(e): e for e in old}, {key(e): e for e in new}
        for k, e in newk.items():
            if k not in oldk:
                changes.append(f"Added exchange '{e['what']}'")
            else:
                diffs = [f"{f} '{oldk[k].get(f, '') or '—'}' → '{e[f] or '—'}'" for f in ("from", "to", "content", "lod", "due")
                         if (oldk[k].get(f) or "") != e[f]]
                if e["feeds"] and e["feeds"] != exchange_feeds(plan, oldk[k]):
                    diffs.append(f"feeds → {e['feeds']}")
                if diffs:
                    changes.append(f"Exchange '{e['what']}': " + "; ".join(diffs))
        for k, e in oldk.items():
            if k not in newk:
                changes.append(f"Removed exchange '{e['what']}'")
        # keep explicit feeds only where it differs from what keywords would choose
        for e in new:
            probe = dict(e, feeds="")
            if e["feeds"] == exchange_feeds(plan, probe):
                e["feeds"] = ""
        plan["exchanges"] = new or [dict(ROW_TEMPLATES["exchanges"])]

    if not changes:
        print(f"No changes for '{project}' — the sheet matches the plan.")
        return
    print(f"Changes for '{project}' from {a.file}:")
    for c in changes:
        print(f"  - {c}")
    if a.dry_run:
        print("\nDry run: plan not changed.")
    else:
        save(a.plan, plan)
        print(f"\nSaved {a.plan}. Run process-map to redraw the map.")


def cmd_export(a):
    plan = load(a.plan)
    doc = build_doc(plan)
    text = to_markdown(plan, doc) if a.format == "md" else to_html(plan, doc)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote {a.output} ({len(collect_todos(doc))} TODO items)")
    else:
        sys.stdout.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bep", description="Build a BIM Execution Plan from the command line.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("plan"); s.add_argument("--example", action="store_true")
    s.add_argument("--agency", choices=list(AGENCIES)); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("catalog"); s.set_defaults(fn=cmd_catalog)
    s = sub.add_parser("show"); s.add_argument("plan"); s.add_argument("path", nargs="?"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("set"); s.add_argument("plan"); s.add_argument("path"); s.add_argument("value"); s.set_defaults(fn=cmd_set)
    s = sub.add_parser("add"); s.add_argument("plan"); s.add_argument("list"); s.add_argument("fields", nargs="*"); s.set_defaults(fn=cmd_add)
    s = sub.add_parser("remove"); s.add_argument("plan"); s.add_argument("list"); s.add_argument("index", type=int); s.set_defaults(fn=cmd_remove)
    s = sub.add_parser("use"); s.add_argument("plan"); s.add_argument("use_id"); s.add_argument("--off", action="store_true")
    s.add_argument("--party"); s.add_argument("--value"); s.add_argument("--flow"); s.set_defaults(fn=cmd_use)
    s = sub.add_parser("qc"); s.add_argument("plan"); s.add_argument("rule_id"); s.add_argument("--off", action="store_true")
    s.add_argument("--who"); s.add_argument("--freq"); s.add_argument("--tool"); s.set_defaults(fn=cmd_qc)
    s = sub.add_parser("status"); s.add_argument("plan"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("validate"); s.add_argument("plan"); s.add_argument("--strict", action="store_true"); s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("check-names"); s.add_argument("names", nargs="*"); s.add_argument("--file")
    s.add_argument("--plan"); s.set_defaults(fn=cmd_check_names)
    s = sub.add_parser("convert"); s.add_argument("plan"); s.add_argument("names", nargs="+")
    s.add_argument("--anno-element"); s.set_defaults(fn=cmd_convert)
    s = sub.add_parser("definition"); s.add_argument("plan"); s.add_argument("-o", "--output"); s.set_defaults(fn=cmd_definition)
    s = sub.add_parser("maps-workbook"); s.add_argument("plans", nargs="+"); s.add_argument("-o", "--output", required=True)
    s.set_defaults(fn=cmd_maps_workbook)
    s = sub.add_parser("apply-maps"); s.add_argument("plan"); s.add_argument("file"); s.add_argument("--project")
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_apply_maps)
    s = sub.add_parser("process-map"); s.add_argument("plan"); s.add_argument("--format", choices=["mermaid", "tldraw"], default="mermaid")
    s.add_argument("-o", "--output"); s.set_defaults(fn=cmd_process_map)
    s = sub.add_parser("export"); s.add_argument("plan"); s.add_argument("--format", choices=["md", "html"], default="md")
    s.add_argument("-o", "--output"); s.set_defaults(fn=cmd_export)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except PlanFileError as e:
        sys.exit(str(e))
    except PermissionError as e:
        sys.exit(f"Permission denied: {e}")
    except OSError as e:   # e.g. a missing output folder or input spreadsheet: one line, not a traceback
        sys.exit(f"{e.strerror}: {e.filename}" if e.filename else str(e))


if __name__ == "__main__":
    # Windows pipes and redirects default to the ANSI code page (cp1252), which can't
    # encode the symbols this tool prints; write UTF-8 everywhere instead.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    main()
