"""Level 1 BIM process map for a BEP plan (BEP section 05).

Builds one layout from the plan, then renders it two ways:
  * tldraw  — a JavaScript snippet for the tldraw connector's `exec` tool (editable canvas)
  * mermaid — a Mermaid flowchart for Markdown, GitHub, Claude Docs, and artifacts

Layout rules (kept simple so maps read the same on every project):
  * Columns are project phases: Planning, Design, Construction, Operations.
  * "Owner requirements & goals" always starts the Planning column.
  * Each selected BIM use sits in its first phase. The first use in a phase is that
    phase's lead: it receives the arrow from the previous phase and feeds the other
    uses in its own phase.
  * Information exchanges (section 06) label the arrow into the use they feed, matched
    by keywords (e.g. "coordination model" -> 3D coordination). Exchanges that match no
    use are listed in a note so nothing is silently dropped.
"""
import json
import re

PHASES = ["Planning", "Design", "Construction", "Operations"]
PHASE_COLORS = {"Planning": "grey", "Design": "blue", "Construction": "orange", "Operations": "green"}

# Keywords that tie an exchange to the BIM use it feeds.
USE_KEYWORDS = {
    "existing": ["existing", "scan", "survey", "point cloud"],
    "authoring": ["design model", "authoring", "discipline model"],
    "review": ["review"],
    "coord": ["coordination", "clash", "nwc", "navisworks", "federated"],
    "drawings": ["drawing", "sheet", "document set"],
    "code": ["code"],
    "energy": ["energy"],
    "cost": ["cost", "quantity", "estimate", "takeoff"],
    "4d": ["4d", "schedule", "sequenc"],
    "ifc": ["ifc", "open exchange"],
    "record": ["record", "as-built", "as built"],
    "cobie": ["cobie", "handover", "facility data", "asset"],
}


def _phase_of(phase_text):
    first = phase_text.split(",")[0].strip()
    return first if first in PHASES else "Design"   # "All" and unknowns sit in Design


def build(plan, uses_catalog):
    """Return the map model: {"title", "columns": {phase: [node]}, "edges": [...], "notes": [...]}."""
    p = plan
    name = p["project"]["name"] or "Untitled project"
    goals = [g["goal"] for g in p["goals"] if g.get("goal", "").strip()]
    req_label = "Owner requirements & goals"
    agency = p["project"].get("agency", "private")
    sub = []
    if agency and agency != "private":
        sub.append({"gsa": "GSA criteria", "usace": "USACE / DoD criteria", "va": "VA criteria",
                    "federal": "Federal agency criteria", "state": "State / local criteria"}.get(agency, agency))
    if goals:
        sub.append(f"{len(goals)} BIM goal{'s' if len(goals) != 1 else ''}")
    columns = {ph: [] for ph in PHASES}
    columns["Planning"].append({"id": "req", "title": req_label, "sub": " · ".join(sub), "phase": "Planning"})

    for uid, uname, uphase in uses_catalog:
        u = p["uses"].get(uid, {})
        if not u.get("on"):
            continue
        ph = _phase_of(uphase)
        columns[ph].append({"id": f"u_{uid}", "use": uid, "title": uname,
                            "sub": u.get("party", "").strip(), "phase": ph})

    # Fill phases skipped between the first and last used phase with a stub, so work
    # never appears to jump straight from design to operations.
    used_idx = [i for i, ph in enumerate(PHASES) if columns[ph]]
    for i in range(used_idx[0], used_idx[-1] + 1):
        ph = PHASES[i]
        if not columns[ph]:
            columns[ph].append({"id": f"stub_{ph.lower()}", "title": ph,
                                "sub": "No BIM uses selected for this phase", "phase": ph, "stub": True})

    # Edges: previous phase lead -> this phase lead; lead -> other uses in its phase.
    edges = []
    prev_lead = None
    for ph in PHASES:
        nodes = columns[ph]
        if not nodes:
            continue
        lead = nodes[0]
        if prev_lead is not None:
            edges.append({"from": prev_lead["id"], "to": lead["id"], "labels": []})
        for other in nodes[1:]:
            edges.append({"from": lead["id"], "to": other["id"], "labels": []})
        prev_lead = lead

    # Exchanges label the arrow into the use they feed.
    into = {e["to"]: e for e in edges}
    exchanges = [dict(e) for e in p["exchanges"] if e.get("what", "").strip()]
    if p.get("cobie") and p["uses"].get("cobie", {}).get("on") and \
            not any(re.search("cobie", e["what"], re.I) for e in exchanges):
        exchanges.append({"what": "COBie handover", "lod": "", "due": ""})
    notes = []
    for ex in exchanges:
        text = ex["what"].lower() + " " + ex.get("content", "").lower()
        target = None
        fid = (ex.get("feeds") or "").strip()
        if fid and f"u_{fid}" in into:
            target = f"u_{fid}"          # chosen explicitly (e.g. in the maps workbook)
        for uid, words in ([] if target else USE_KEYWORDS.items()):
            if f"u_{uid}" in into and any(w in text for w in words):
                target = f"u_{uid}"
                break
        label = " · ".join(x for x in (ex["what"], ex.get("lod", ""), ex.get("due", "")) if x and x.strip())
        if target:
            into[target]["labels"].append(label)
        else:
            notes.append(label)

    if len([n for ph in PHASES for n in columns[ph]]) == 1:
        notes.insert(0, "No BIM uses selected yet — choose them in section 04")
    return {"title": f"{name} · BEP Level 1 process map (section 05)", "columns": columns,
            "edges": edges, "notes": notes}


# ------------------------------------------------------------------ Mermaid
def _m(s):
    return s.replace('"', "'").replace("\n", "<br/>")


def to_mermaid(model):
    lines = ["flowchart LR"]
    for i, ph in enumerate(PHASES):
        nodes = model["columns"][ph]
        if not nodes:
            continue
        lines.append(f'  subgraph P{i}["{ph}"]')
        lines.append("    direction TB")
        for n in nodes:
            label = _m(n["title"]) + (f"<br/><small>{_m(n['sub'])}</small>" if n["sub"] else "")
            lines.append(f'    {n["id"]}["{label}"]')
        lines.append("  end")
    for e in model["edges"]:
        if e["labels"]:
            lines.append(f'  {e["from"]} -->|"{_m("; ".join(e["labels"]))}"| {e["to"]}')
        else:
            lines.append(f'  {e["from"]} --> {e["to"]}')
    for i, ph in enumerate(PHASES):
        for n in model["columns"][ph]:
            lines.append(f"  class {n['id']} {ph.lower()}")
    lines += ["  classDef planning fill:#eef0ef,stroke:#6b7479",
              "  classDef design fill:#e3eefb,stroke:#2f6db3",
              "  classDef construction fill:#fcefe0,stroke:#c26a12",
              "  classDef operations fill:#e5f4ea,stroke:#2c7a4d"]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ tldraw
def to_tldraw(model, colw=320, gap=40):
    """JavaScript for the tldraw connector's exec tool. Clears nothing; run on a new canvas."""
    used = [ph for ph in PHASES if model["columns"][ph]]
    col = {ph: i for i, ph in enumerate(used)}
    shapes = []
    shapes.append({"_type": "text", "shapeId": "title", "x": 0, "y": -10, "text": model["title"], "color": "black"})
    for ph in used:
        shapes.append({"_type": "rectangle", "shapeId": f"ph_{ph.lower()}", "x": col[ph] * (colw + gap), "y": 70,
                       "w": colw, "h": 50, "text": ph.upper(), "color": "black", "fill": "solid"})
        for j, n in enumerate(model["columns"][ph]):
            text = n["title"] + (f"\n{n['sub']}" if n["sub"] else "")
            shapes.append({"_type": "rectangle", "shapeId": n["id"], "x": col[ph] * (colw + gap) + 20,
                           "y": 180 + j * 180, "w": colw - 40, "h": 110, "text": text,
                           "color": "grey" if n.get("stub") else PHASE_COLORS[ph],
                           "fill": "none" if n.get("stub") else "tint"})
    arrows = [{"from": e["from"], "to": e["to"], "text": "; ".join(e["labels"])} for e in model["edges"]]
    note_lines = ["Arrows = information exchanges (section 06)", "Generated from the plan — edit freely"]
    if model["notes"]:
        note_lines += ["", "Not yet placed on the map:"] + [f"• {x}" for x in model["notes"]]
    tallest = max(len(model["columns"][ph]) for ph in used)
    note = {"_type": "note", "shapeId": "legend", "x": 0, "y": 180 + tallest * 180 + 20,
            "text": "\n".join(note_lines), "color": "yellow"}
    return (
        "// BEP Level 1 process map — generated by bep.py process-map\n"
        f"const shapes = {json.dumps(shapes, ensure_ascii=False)};\n"
        f"const arrows = {json.dumps(arrows, ensure_ascii=False)};\n"
        f"const note = {json.dumps(note, ensure_ascii=False)};\n"
        "shapes.forEach(s => editor.createShape(s));\n"
        "arrows.forEach(a => createArrowBetweenShapes(a.from, a.to, a.text ? { text: a.text } : {}));\n"
        "editor.createShape(note);\n"
        "editor.selectAll(); editor.zoomToSelection(); editor.selectNone();\n"
        "return editor.getCurrentPageShapes().length;\n"
    )
