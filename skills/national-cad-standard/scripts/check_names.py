"""Check layer and sheet names against the NCS formats in references/conventions.md.

Rules verified against a licensed copy of NCS V6 (CLG section 1, UDS section 1.3).

Usage:
    python check_names.py A-WALL-FULL a-wall E-LITE-XYZ A-101 AD101 A-102-R1
    python check_names.py --file names.txt      (one name per line)
    python check_names.py --status-field status A-WALL-D A-WALL-2
        status-field: both (NCS default: letters or phase numbers), status (letters
        only), phase (numbers only), none (no status field). ISO 13567 conformance
        requires status or phase, not both — for full ISO checks use iso13567.py.

Prints a Markdown table: Name | Kind | Valid? | Problem.
"""
import re
import sys

DISCIPLINES = set("GHVBCLSAIQFPDMEWTRXZO")
STATUS_LETTERS = set("ADEFMNTX")         # A = Abandoned ... X = Not in contract
PHASES = set("123456789")                # construction phase numbers
STATUS = STATUS_LETTERS | PHASES
CODE = re.compile(r"^[A-Z0-9~]{4}$")    # major/minor groups: 4 letters, digits or "~"

# Sheet ID: 5 characters, then an optional "-" plus up to 3 user-defined characters.
#   Level 1: letter + hyphen (or underscore) + type digit + 2-digit sequence   A-101
#   Level 2: two letters, no hyphen                                             AD101
SHEET = re.compile(r"^(?:([A-Z])[-_]|([A-Z]{2}))([0-9])([0-9]{2})(?:-([A-Z0-9]{1,3}))?$")


def check_layer(name, status_field="both"):
    """Return a list of problems (an empty list means the layer name is valid)."""
    if " " in name or "_" in name:
        return ["separate fields with hyphens, not underscores or spaces"]
    problems = []
    if name != name.upper():
        problems.append("use uppercase only")
    fields = name.upper().split("-")
    disc, rest = fields[0], fields[1:]

    if not 1 <= len(disc) <= 2 or disc[0] not in DISCIPLINES or not disc.isalpha():
        problems.append(f"'{disc}' is not a known discipline designator")
    if not rest:
        return problems + ["missing the 4-character major group"]

    # A trailing 1-character field is the status code.
    if len(rest) > 1 and len(rest[-1]) == 1:
        status = rest.pop()
        if status not in STATUS:
            problems.append(f"'{status}' is not a valid status code")
        elif status_field == "none":
            problems.append(f"this project doesn't use a status field; remove '-{status}'")
        elif status_field == "status" and status in PHASES:
            problems.append(f"'{status}' is a phase number; this project uses status letters (A D E F M N T X)")
        elif status_field == "phase" and status in STATUS_LETTERS:
            problems.append(f"'{status}' is a status letter; this project uses phase numbers (1-9)")

    major, minors = rest[0], rest[1:]
    if not CODE.match(major):
        problems.append(f"major group '{major}' must be exactly 4 letters, digits or '~'")
    if len(minors) > 2:
        problems.append("no more than two minor groups are allowed")
    for m in minors:
        if not CODE.match(m):
            problems.append(f"minor group '{m}' must be exactly 4 letters, digits or '~'")
    return problems


def check_sheet(name):
    """Return a list of problems (an empty list means the sheet ID is valid)."""
    upper = name.upper()
    m = SHEET.match(upper)
    if not m:
        if re.match(r"^[A-Z][0-9]{3}", upper):
            return ["a 1-letter discipline needs a hyphen placeholder (e.g. S-501)"]
        if re.match(r"^[A-Z]{2}-[0-9]", upper):
            return ["a 2-letter discipline takes no hyphen (e.g. AD101)"]
        if re.match(r"^[A-Z]{1,2}-?[0-9]{4,}", upper):
            return ["sequence number must be exactly 2 digits (01-99)"]
        return ["does not match the 5-character sheet ID format (A-101 or AD101)"]
    letter = m.group(1) or m.group(2)[0]
    problems = []
    if name != upper:
        problems.append("use uppercase only")
    if letter not in DISCIPLINES:
        problems.append(f"'{letter}' is not a known discipline designator")
    if m.group(4) == "00":
        problems.append("sequence number 00 is not permitted; start at 01")
    return problems


def looks_like_sheet(name):
    # In a sheet ID, digits come straight after the discipline letters (A-101, AD101).
    # In a layer, a 4-character group comes first (A-DETL-D001), even if digits follow.
    return bool(re.match(r"^[A-Za-z]{1,2}[-_]?\d", name))


def main(argv):
    status_field = "both"
    if argv[:1] == ["--status-field"]:
        status_field = argv[1]
        if status_field not in ("both", "status", "phase", "none"):
            print("--status-field must be both, status, phase or none")
            return 1
        argv = argv[2:]
    if argv[:1] == ["--file"]:
        with open(argv[1], encoding="utf-8") as fh:
            names = [line.strip() for line in fh if line.strip()]
    else:
        names = argv
    if not names:
        print(__doc__)
        return 1

    print("| Name | Kind | Valid? | Problem |")
    print("|---|---|---|---|")
    for name in names:
        kind = "sheet" if looks_like_sheet(name) else "layer"
        problems = check_sheet(name) if kind == "sheet" else check_layer(name, status_field)
        valid = "No" if problems else "Yes"
        print(f"| {name} | {kind} | {valid} | {'; '.join(problems) or '—'} |")
    return 0


if __name__ == "__main__":
    # Windows pipes and redirects default to the ANSI code page (cp1252), which can't
    # encode the symbols this tool prints; write UTF-8 everywhere instead.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
