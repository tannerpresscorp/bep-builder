"""NCS layer names in conceptual conformance with ISO 13567.

Implements the rules in NCS CLG Appendix C (sections 6.10-6.12, verified against a
licensed copy of NCS V6):

  * "ANNO" may not be used anywhere in a layer name, because ISO reserves the
    Element field for building elements. Annotation codes (TEXT, DIMS, NPLT, ...)
    go in a minor-group field reserved for annotation instead.
  * Each field holds one kind of data only. One minor group is the annotation
    field; the other is EITHER an element refinement (e.g. FULL) OR a drawing
    view (DETL, ELEV, SECT) — only two of the three options fit.
  * The status field is either status letters OR phase numbers, never both.
  * Every layer name in the project has the same length and field order; unused
    fields are filled with placeholders (underscores).
  * The project documents its format in an ISO 13567-3 layer naming system
    definition file.

A project profile fixes those choices:

  level   1 -> one-letter discipline (A-WALL-...), 2 -> two letters (AI-WALL-...)
  format  "element" -> D-MAJR-ELEM-ANNO-S   (Fig. 6.11-1 pattern)
          "view"    -> D-MAJR-VIEW-ANNO-S   (Fig. 6.11-2 pattern)
  status  "status" (A D E F M N T X), "phase" (1-9), or "none"

Usage:
  python iso13567.py check   [profile opts] NAME [NAME ...] | --file F
  python iso13567.py convert [profile opts] [--anno-element CODE] NAME ... | --file F
  python iso13567.py definition [profile opts]       # ISO 13567-3 definition file text
Profile opts: --level 1|2  --format element|view  --status status|phase|none
"""
import argparse
import re
import sys

DISC = set("GHVBCLSAIQFPDMEWTRXZO")
STATUS_LETTERS = set("ADEFMNTX")
PHASE_DIGITS = set("123456789")
CODE = re.compile(r"^[A-Z0-9~]{4}$")
PLACEHOLDER = "____"

# NCS CLG 3.2 annotation minor groups, plus NCS's general "ANNO" major group.
ANNOT_CODES = {"BRNG", "DIMS", "IDEN", "KEYN", "LABL", "LEGN", "LOGO", "MARK", "MATC", "NOTE",
               "NPLT", "PROS", "RDME", "REDL", "REFR", "REVC", "REVS", "SCHD", "STMP", "SYMB",
               "TABL", "TEXT", "TITL", "TTLB"}
# NCS CLG 2.1 drawing-view codes. "ANNN" (letter + 001-999) numbers drawings within a view.
VIEW_CODES = {"DETL", "ELEV", "SECT"}
# Annotation that belongs to the sheet rather than to a building element. When a project
# defines a sheet-level element code (listed on its Compliance Disclosure Statement), old
# ANNO layers carrying these codes can move to it automatically; all other annotation
# (DIMS, IDEN, TEXT, KEYN...) describes an element, so a person picks the element.
SHEET_LEVEL_CODES = {"TTLB", "LOGO", "STMP", "PROS", "RDME", "REVS", "NOTE", "LEGN", "TITL",
                     "SCHD", "TABL", "NPLT"}
ANNN = re.compile(r"^[A-Z][0-9]{3}$")

STATUS_MEANING = {"A": "Abandoned", "D": "Existing to demolish", "E": "Existing to remain",
                  "F": "Future work", "M": "Items to be moved", "N": "New work",
                  "T": "Temporary work", "X": "Not in contract"}


class Profile:
    def __init__(self, level=1, fmt="element", status="status"):
        if level not in (1, 2):
            raise ValueError("level must be 1 or 2")
        if fmt not in ("element", "view"):
            raise ValueError("format must be 'element' or 'view'")
        if status not in ("status", "phase", "none"):
            raise ValueError("status must be 'status', 'phase' or 'none'")
        self.level, self.fmt, self.status = level, fmt, status

    @property
    def field_count(self):
        return 4 + (1 if self.status != "none" else 0)

    @property
    def length(self):
        # discipline + "-" + 3 x (4 chars + "-") + status
        n = self.level + 1 + 4 + 1 + 4 + 1 + 4
        return n + (2 if self.status != "none" else 0)

    def describe(self):
        second = ("element refinement (e.g. FULL, PATT)" if self.fmt == "element"
                  else "drawing view (DETL, ELEV, SECT, or a letter+number like D001)")
        st = {"status": "status letters A D E F M N T X",
              "phase": "phase numbers 1-9", "none": "no status field"}[self.status]
        return (f"Level {self.level} discipline · major group · {second} · annotation code · {st}; "
                f"every name is {self.length} characters, unused fields filled with {PLACEHOLDER}")

    def example(self):
        d = "A" if self.level == 1 else "AI"
        second = "FULL" if self.fmt == "element" else "ELEV"
        s = {"status": "-N", "phase": "-2", "none": ""}[self.status]
        return f"{d}-WALL-{second}-TEXT{s}"


def _status_problem(ch, mode):
    if mode == "status" and ch not in STATUS_LETTERS and ch != "_":
        return f"status '{ch}' must be one of the status letters A D E F M N T X (this project uses status, not phase)"
    if mode == "phase" and ch not in PHASE_DIGITS and ch != "_":
        return f"status '{ch}' must be a phase number 1-9 (this project uses phase, not status letters)"
    return None


def check(name, prof):
    """Return a list of problems with `name` under profile `prof` (empty = conforms)."""
    if " " in name:
        return ["no spaces allowed"]
    pr = []
    if name != name.upper():
        pr.append("use uppercase only")
    f = name.upper().split("-")
    if "ANNO" in f:
        pr.append("'ANNO' isn't allowed under ISO 13567 — put the annotation code (TEXT, DIMS, NPLT…) "
                  "in the annotation field of a building-element layer instead")
    if len(f) != prof.field_count:
        pr.append(f"needs {prof.field_count} fields like {prof.example()} "
                  f"(use {PLACEHOLDER} for an unused field); found {len(f)}")
        return pr
    disc, major, second, annot = f[0], f[1], f[2], f[3]

    if len(disc) != prof.level or not disc.isalpha() or disc[0] not in DISC:
        pr.append(f"discipline '{disc}' must be {prof.level} letter{'s' if prof.level == 2 else ''} "
                  f"starting with a known designator")

    if major == PLACEHOLDER or not CODE.match(major):
        pr.append(f"major group '{major}' must be a 4-character building element code")
    elif major != "ANNO" and major in ANNOT_CODES:
        pr.append(f"'{major}' is an annotation code, so it can't be the major group (ISO's Element "
                  f"field) — use a building element such as WALL and put {major} in the annotation field")
    elif major in VIEW_CODES:
        pr.append(f"'{major}' is a drawing-view code and can't be the major group under ISO 13567 — "
                  f"use a building element and {'put the view in the view field' if prof.fmt == 'view' else 'choose the view format for this project'}")

    if second != PLACEHOLDER:
        if prof.fmt == "element":
            if second in ANNOT_CODES:
                pr.append(f"'{second}' is an annotation code; it belongs in the annotation field (4th), not the element field")
            elif second in VIEW_CODES or ANNN.match(second):
                pr.append(f"'{second}' is a drawing-view code; this project's format reserves this field for element refinements")
            elif not CODE.match(second):
                pr.append(f"element refinement '{second}' must be 4 characters or {PLACEHOLDER}")
        else:
            if not (second in VIEW_CODES or ANNN.match(second)):
                pr.append(f"'{second}' isn't a drawing-view code; this field only takes DETL, ELEV, SECT, "
                          f"a letter+number (D001), or {PLACEHOLDER}")

    if annot != PLACEHOLDER and annot not in ANNOT_CODES:
        pr.append(f"'{annot}' isn't an annotation code; the 4th field only takes codes like TEXT, DIMS, "
                  f"NOTE, NPLT, or {PLACEHOLDER}")

    if prof.status != "none":
        st = f[4]
        if len(st) != 1:
            pr.append(f"status field '{st}' must be one character")
        else:
            p = _status_problem(st, prof.status)
            if p:
                pr.append(p)
    return pr


def convert(name, prof, anno_element=None, sheet_element=None):
    """Suggest the ISO-profile form of a legacy NCS layer name.

    Returns (new_name or None, [notes]). None means a person must decide something
    first; the notes say what. `anno_element` replaces ANNO on every layer;
    `sheet_element` (the project's sheet-level code) replaces it only for sheet-level
    annotation such as title blocks and general notes.
    """
    notes = []
    f = [x for x in name.upper().replace("_", "-").split("-") if x]
    if len(f) < 2:
        return None, ["not a recognizable NCS layer name"]
    disc, major, rest = f[0], f[1], f[2:]

    status = None
    if rest and len(rest[-1]) == 1:
        status = rest.pop()

    if prof.level == 2 and len(disc) == 1:
        return None, [f"this project uses 2-letter disciplines; choose a modifier for '{disc}' (e.g. {disc}I, {disc}D)"]
    if prof.level == 1 and len(disc) == 2:
        notes.append(f"dropped discipline modifier '{disc[1]}' (project uses 1-letter disciplines)")
        disc = disc[0]

    elem, view, annot = [], [], []
    for code in rest:
        if code in ANNOT_CODES:
            annot.append(code)
        elif code in VIEW_CODES or ANNN.match(code):
            view.append(code)
        else:
            elem.append(code)

    if major == "ANNO":
        if not annot:
            annot = ["TEXT"]
            notes.append("plain ANNO layer mapped to annotation code TEXT")
        if not anno_element and sheet_element and annot[0] in SHEET_LEVEL_CODES:
            anno_element = sheet_element
        if not anno_element:
            if sheet_element:
                return None, notes + [f"{annot[0]} describes a building element, so it doesn't go on {sheet_element}; "
                                      f"pick the element it belongs to (e.g. WALL, DOOR, EQPM)"]
            return None, notes + [f"ANNO layers need a building element in its place; pick the element this "
                                  f"{', '.join(annot)} describes (e.g. WALL, DOOR, EQPM) or a project-wide code "
                                  f"for sheet-level annotation, listed on the Compliance Disclosure Statement"]
        major = anno_element
        notes.append(f"ANNO replaced by element '{anno_element}'; '{annot[0]}' moved to the annotation field")
    elif major in VIEW_CODES:
        return None, [f"'{major}' layers need a building element as the major group; move {major} to the view field"]
    elif major in ANNOT_CODES:
        return None, [f"'{major}' is an annotation code, not a building element; choose the element it annotates"]

    if len(annot) > 1:
        return None, notes + [f"more than one annotation code ({', '.join(annot)}); split into separate layers"]
    if prof.fmt == "element":
        if view:
            return None, notes + [f"drawing-view code {view[0]} has no place in this project's element format"]
        if len(elem) > 1:
            return None, notes + [f"two element refinements ({', '.join(elem)}); only one fits"]
        second = elem[0] if elem else PLACEHOLDER
    else:
        if elem:
            return None, notes + [f"element refinement {elem[0]} has no place in this project's view format"]
        second = view[0] if view else PLACEHOLDER

    parts = [disc, major, second, annot[0] if annot else PLACEHOLDER]
    if prof.status != "none":
        if status is None:
            parts.append("_")
            notes.append("no status in the original; placeholder '_' added — set the real status")
        elif _status_problem(status, prof.status):
            parts.append("_")
            notes.append(f"original status '{status}' doesn't fit this project's {prof.status} field; set it")
        else:
            parts.append(status)
    elif status:
        notes.append(f"status '{status}' dropped (project doesn't use a status field)")

    out = "-".join(parts)
    leftover = check(out, prof)
    if leftover:
        return None, notes + leftover
    return out, notes


def definition_file(prof, project="Project"):
    """Tab-delimited ISO 13567-3 layer naming system definition (format part)."""
    rows = [("Position", "NCS field", "ISO 13567 field", "Characters", "Allowed codes")]
    pos = 1
    rows.append((str(pos), f"Discipline designator (Level {prof.level})", "Agent responsible",
                 str(prof.level + 1), "NCS discipline designators" + (" with modifier" if prof.level == 2 else "") + "; trailing '-' counted in field"))
    pos += prof.level + 1
    rows.append((str(pos), "Major group", "Element", "5", "NCS major groups (building elements); ANNO not used; trailing '-' counted"))
    pos += 5
    if prof.fmt == "element":
        rows.append((str(pos), "Minor group 1", "Element (continued)", "5", f"NCS minor groups refining the element, or {PLACEHOLDER}"))
    else:
        rows.append((str(pos), "Minor group 1 (drawing view)", "Projection", "5", f"DETL, ELEV, SECT, letter+001-999, or {PLACEHOLDER}"))
    pos += 5
    last = prof.status == "none"
    rows.append((str(pos), "Minor group 2 (annotation)", "Presentation", "4" if last else "5",
                 f"NCS annotation codes ({', '.join(sorted(ANNOT_CODES))}) or {PLACEHOLDER}"))
    pos += 4 if last else 5
    if prof.status == "status":
        rows.append((str(pos), "Status", "Status", "1", ", ".join(f"{k}={v}" for k, v in STATUS_MEANING.items())))
    elif prof.status == "phase":
        rows.append((str(pos), "Status (phase)", "Phase", "1", "1-9 = construction phase number"))
    head = [f"# Layer naming system definition — {project}",
            "# NCS layer format in conceptual conformance with ISO 13567 (NCS CLG Appendix C)",
            f"# Total length: {prof.length} characters; field order fixed; '-' delimiters belong to the preceding field",
            f"# Example: {prof.example()}"]
    return "\n".join(head + ["\t".join(r) for r in rows]) + "\n"


def _profile_args(ap):
    ap.add_argument("--level", type=int, choices=[1, 2], default=1)
    ap.add_argument("--format", dest="fmt", choices=["element", "view"], default="element")
    ap.add_argument("--status", choices=["status", "phase", "none"], default="status")


def _names(a):
    names = list(a.names)
    if a.file:
        with open(a.file, encoding="utf-8") as fh:
            names += [x for line in fh for x in re.split(r"[\s,]+", line) if x]
    if not names:
        sys.exit("Give layer names as arguments or with --file")
    return names


def main(argv=None):
    ap = argparse.ArgumentParser(description="NCS layer names in conceptual conformance with ISO 13567")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("check", "convert"):
        s = sub.add_parser(cmd)
        _profile_args(s)
        s.add_argument("names", nargs="*")
        s.add_argument("--file")
        if cmd == "convert":
            s.add_argument("--anno-element", help="element code to use in place of ANNO on every layer")
            s.add_argument("--sheet-element", help="project code for sheet-level annotation (title blocks, general notes); used only for those ANNO layers")
    s = sub.add_parser("definition")
    _profile_args(s)
    s.add_argument("--project", default="Project")
    a = ap.parse_args(argv)
    prof = Profile(a.level, a.fmt, a.status)

    if a.cmd == "definition":
        sys.stdout.write(definition_file(prof, a.project))
        return
    names = _names(a)
    print(f"Profile: {prof.describe()}\n")
    if a.cmd == "check":
        bad = 0
        print("| Layer | Conforms? | Problem |\n|---|---|---|")
        for n in names:
            p = check(n, prof)
            bad += bool(p)
            print(f"| {n} | {'No' if p else 'Yes'} | {'; '.join(p) or '—'} |")
        print(f"\n{len(names) - bad} conform, {bad} to fix")
    else:
        print("| Original | Suggested | Notes |\n|---|---|---|")
        for n in names:
            new, notes = convert(n, prof, a.anno_element.upper() if a.anno_element else None,
                                 a.sheet_element.upper() if a.sheet_element else None)
            print(f"| {n} | {new or '— needs a decision'} | {'; '.join(notes) or '—'} |")


if __name__ == "__main__":
    # Windows pipes and redirects default to the ANSI code page (cp1252), which can't
    # encode the symbols this tool prints; write UTF-8 everywhere instead.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    main()
