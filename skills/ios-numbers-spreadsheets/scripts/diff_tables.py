#!/usr/bin/env python3
"""Show what changed between the spreadsheet you sent and the one that came back.

Matches tables by name, then by header similarity (Numbers' "One per Table" Excel
export renames worksheets), matches columns by header text (so reordered columns
are fine), and matches rows by key columns.

Usage:
  python diff_tables.py ORIGINAL EDITED [--key "Table=Col A,Col B" ...] [--json]

  --key   Columns that identify a row, per table. Without it, the first column is
          used when its values are unique, otherwise row position.
          Example: --key "Uses=Project,BIM use" --key "Exchanges=Project,Exchange"

Formula cells are compared by value; a changed formula is reported separately.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from read_tables import read  # noqa: E402


def _norm(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return round(v, 9)
    if isinstance(v, str):
        return v.strip()
    return v


def match_tables(a_tables, b_tables):
    pairs, used = [], set()
    for a in a_tables:
        best, score = None, 0.0
        for j, b in enumerate(b_tables):
            if j in used:
                continue
            if b["table"].lower() == a["table"].lower() or b["sheet"].lower() == a["sheet"].lower():
                best, score = j, 2.0
                break
            ha, hb = set(h for h in a["header"] if h), set(h for h in b["header"] if h)
            s = len(ha & hb) / max(1, len(ha | hb))
            if s > score:
                best, score = j, s
        if best is not None and score >= 0.6:
            used.add(best)
            pairs.append((a, b_tables[best]))
        else:
            pairs.append((a, None))
    extra = [b for j, b in enumerate(b_tables) if j not in used]
    return pairs, extra


def _calculated_columns(table):
    """Headers of columns that hold formulas in this table (values are recalculated, not typed)."""
    import re
    cols = set()
    for coord in table.get("formulas", {}):
        letters = re.match(r"[A-Z]+", coord).group(0)
        n = 0
        for ch in letters:
            n = n * 26 + ord(ch) - 64
        if 0 < n <= len(table["header"]):
            cols.add(table["header"][n - 1])
    return cols


def keyed(table, key_cols):
    idx = [table["header"].index(k) for k in key_cols] if key_cols else None
    out = {}
    for n, r in enumerate(table["rows"]):
        if all(_norm(v) == "" for v in r):
            continue
        k = tuple(_norm(r[i]) if i < len(r) else "" for i in idx) if idx else ("row", n + 1)
        out[k] = r
    return out


def pick_key(table, given):
    if given:
        missing = [k for k in given if k not in table["header"]]
        if missing:
            sys.exit(f"Key column(s) {missing} not in table '{table['table']}'. Columns: {table['header']}")
        return given
    first = [_norm(r[0]) for r in table["rows"] if r and _norm(r[0]) != ""]
    if table["header"] and first and len(first) == len(set(first)):
        return [table["header"][0]]
    return None


def diff(orig, edited, keys):
    pairs, extra = match_tables(orig["tables"], edited["tables"])
    report = []
    for a, b in pairs:
        entry = {"table": a["table"], "matched": b["table"] if b else None, "changes": [], "added": [], "removed": [],
                 "columns_added": [], "columns_removed": [], "formulas_changed": []}
        if b is None:
            entry["note"] = "not found in the edited file"
            report.append(entry)
            continue
        kc = keys.get(a["table"]) or keys.get(a["sheet"]) or keys.get("*")
        kc = pick_key(a, kc)
        if kc and any(k not in b["header"] for k in kc):
            kc = None
        entry["key"] = kc or "row position"
        ca, cb = a["header"], b["header"]
        entry["columns_added"] = [h for h in cb if h and h not in ca]
        entry["columns_removed"] = [h for h in ca if h and h not in cb]
        ra, rb = keyed(a, kc), keyed(b, kc)
        calc = _calculated_columns(a)
        entry["calculated_columns"] = sorted(c for c in calc if c)
        shared_cols = [h for h in ca if h and h in cb and h not in calc]
        for k, row in ra.items():
            if k not in rb:
                entry["removed"].append(dict(zip(ca, row)))
                continue
            other = rb[k]
            for h in shared_cols:
                va = row[ca.index(h)] if ca.index(h) < len(row) else None
                vb = other[cb.index(h)] if cb.index(h) < len(other) else None
                if _norm(va) != _norm(vb):
                    entry["changes"].append({"row": " / ".join(str(x) for x in k), "column": h, "before": va, "after": vb})
        for k, row in rb.items():
            if k not in ra:
                entry["added"].append(dict(zip(cb, row)))
        fa, fb = a.get("formulas", {}), b.get("formulas", {})
        if fa and fb:
            for cell in sorted(set(fa) | set(fb)):
                if fa.get(cell, "").replace(" ", "").upper() != fb.get(cell, "").replace(" ", "").upper():
                    entry["formulas_changed"].append({"cell": cell, "before": fa.get(cell), "after": fb.get(cell)})
        report.append(entry)
    for b in extra:
        report.append({"table": None, "matched": b["table"], "note": "new table in the edited file", "rows": len(b["rows"])})
    return {"original": orig["file"], "edited": edited["file"], "skipped_in_edited": edited.get("skipped", []), "tables": report}


def to_markdown(d):
    out = [f"Comparing **{Path(d['original']).name}** → **{Path(d['edited']).name}**", ""]
    if d["skipped_in_edited"]:
        out += [f"Skipped (export summary): {', '.join(d['skipped_in_edited'])}", ""]
    for t in d["tables"]:
        name = t["table"] or t["matched"]
        if t.get("note"):
            out += [f"### {name}", t["note"], ""]
            continue
        n = len(t["changes"]) + len(t["added"]) + len(t["removed"])
        out += [f"### {name}" + (f" (now '{t['matched']}')" if t["matched"] != t["table"] else ""),
                f"Rows matched by: {', '.join(t['key']) if isinstance(t['key'], list) else t['key']}"]
        if t.get("calculated_columns"):
            out.append(f"Calculated columns not compared: {', '.join(t['calculated_columns'])}")
        if not n and not t["columns_added"] and not t["columns_removed"] and not t["formulas_changed"]:
            out += ["No changes.", ""]
            continue
        if t["changes"]:
            out += ["", "| Row | Column | Before | After |", "|---|---|---|---|"]
            out += [f"| {c['row']} | {c['column']} | {c['before'] if c['before'] not in (None, '') else '—'} | {c['after'] if c['after'] not in (None, '') else '—'} |" for c in t["changes"]]
        for label, rows in (("Added rows", t["added"]), ("Removed rows", t["removed"])):
            if rows:
                out += ["", f"**{label}:**"] + ["- " + ", ".join(f"{k}: {v}" for k, v in r.items() if v not in (None, "")) for r in rows]
        if t["columns_added"] or t["columns_removed"]:
            out += ["", f"Columns added: {t['columns_added'] or '—'} · removed: {t['columns_removed'] or '—'}"]
        if t["formulas_changed"]:
            out += ["", "**Formulas changed:**"] + [f"- {f['cell']}: `{f['before']}` → `{f['after']}`" for f in t["formulas_changed"]]
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    keys = {}
    while "--key" in args:
        i = args.index("--key")
        spec = args[i + 1]
        args = args[:i] + args[i + 2:]
        tname, cols = spec.split("=", 1) if "=" in spec else ("*", spec)
        keys[tname] = [c.strip() for c in cols.split(",")]
    if len(args) != 2:
        sys.exit(__doc__)
    d = diff(read(args[0]), read(args[1]), keys)
    print(json.dumps(d, indent=2, ensure_ascii=False, default=str) if as_json else to_markdown(d))
