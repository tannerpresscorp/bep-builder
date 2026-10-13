#!/usr/bin/env python3
"""Read a spreadsheet that came back from Apple Numbers into plain tables.

Handles every format Numbers on iPhone/iPad can hand back:
  .numbers         native Numbers file (needs numbers-parser; see setup_numbers.sh)
  .xlsx / .xlsm    Numbers' Excel export — either layout:
                     "One per Sheet"  -> one worksheet per Numbers sheet
                     "One per Table"  -> one worksheet per table, plus an optional
                                         summary worksheet that only links to the others
  .csv / .tsv      one table only (Numbers exports cell contents, not formulas)

Output (stdout, JSON):
  {"file": ..., "format": ..., "tables": [
     {"sheet": ..., "table": ..., "header": [...], "rows": [[...], ...],
      "formulas": {"B3": "=SUM(...)", ...}}   # when the format keeps formulas
  ]}

Empty padding rows and columns (Numbers adds them) are trimmed. Worksheets that
only contain links to other worksheets (the export summary) are skipped and listed
under "skipped".

Usage:
  python read_tables.py FILE [--header-row N]   # N = 1-based header row; default: auto
"""
import csv
import json
import sys
from pathlib import Path


def _trim(grid):
    """Drop trailing empty rows/columns and fully empty leading rows."""
    def empty(v):
        return v is None or (isinstance(v, str) and v.strip() == "")
    rows = [list(r) for r in grid]
    while rows and all(empty(v) for v in rows[-1]):
        rows.pop()
    while rows and all(empty(v) for v in rows[0]):
        rows.pop(0)
    if not rows:
        return []
    width = max((max((i + 1 for i, v in enumerate(r) if not empty(v)), default=0) for r in rows), default=0)
    return [(r + [None] * width)[:width] for r in rows]


def _clean(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if v is not None and not isinstance(v, (str, int, float, bool)):
        return str(v)
    return v


def _split_header(grid, header_row):
    if not grid:
        return [], []
    h = (header_row - 1) if header_row else _guess_header(grid)
    header = [("" if v is None else str(v)).strip() for v in grid[h]]
    rows = [[_clean(v) for v in r] for r in grid[h + 1:]]
    return header, rows


def _guess_header(grid):
    """First row (within the first 5) whose cells are all non-empty text."""
    for i, r in enumerate(grid[:5]):
        cells = [v for v in r if v not in (None, "")]
        if cells and len(cells) >= max(1, int(len(r) * 0.6)) and all(isinstance(v, str) for v in cells):
            return i
    return 0


def _looks_like_summary(ws):
    """Numbers' 'One per Table' export can add a worksheet whose cells only link elsewhere."""
    texts, links = 0, 0
    for row in ws.iter_rows():
        for c in row:
            if c.value not in (None, ""):
                texts += 1
                if c.hyperlink is not None or (isinstance(c.value, str) and c.value.startswith("=HYPERLINK(")):
                    links += 1
    return texts > 0 and links >= max(1, texts // 2)


def read_xlsx(path, header_row=None):
    from openpyxl import load_workbook
    values = load_workbook(path, data_only=True)       # cached values (Numbers writes them)
    forms = load_workbook(path, data_only=False)       # formulas
    tables, skipped = [], []
    for ws in values.worksheets:
        if _looks_like_summary(forms[ws.title]):
            skipped.append(ws.title)
            continue
        grid = _trim([[c for c in r] for r in ws.iter_rows(values_only=True)])
        header, rows = _split_header(grid, header_row)
        formulas = {}
        for row in forms[ws.title].iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    formulas[c.coordinate] = c.value
        tables.append({"sheet": ws.title, "table": ws.title, "header": header, "rows": rows, "formulas": formulas})
    return tables, skipped


def read_numbers(path, header_row=None):
    try:
        from numbers_parser import Document
    except Exception as e:  # missing or broken install (protobuf version clash is common)
        sys.exit(f"Can't read .numbers files here: {e}\nRun scripts/setup_numbers.sh, then use the venv python it prints.")
    doc = Document(path)
    tables = []
    for sheet in doc.sheets:
        for t in sheet.tables:
            grid = _trim(t.rows(values_only=True))
            hr = header_row or (t.num_header_rows if t.num_header_rows else None)
            header, rows = _split_header(grid, hr)
            formulas = {}
            for r, row in enumerate(t.rows()):
                for c, cell in enumerate(row):
                    if getattr(cell, "is_formula", False) and cell.formula:
                        formulas[f"{_col(c)}{r + 1}"] = "=" + cell.formula
            tables.append({"sheet": sheet.name, "table": t.name, "header": header, "rows": rows, "formulas": formulas})
    return tables, []


def read_delimited(path, header_row=None):
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    with open(path, newline="", encoding="utf-8-sig") as fh:
        grid = _trim([[v if v != "" else None for v in r] for r in csv.reader(fh, delimiter=delim)])
    grid = [[_num(v) for v in r] for r in grid]
    header, rows = _split_header(grid, header_row)
    return [{"sheet": path.stem, "table": path.stem, "header": header, "rows": rows, "formulas": {}}], []


def _num(v):
    """CSV cells arrive as text; turn plain numbers back into numbers (keep codes like 007)."""
    if not isinstance(v, str):
        return v
    t = v.strip()
    if not t or (len(t) > 1 and t[0] == "0" and t[1] != "."):
        return v
    try:
        f = float(t)
    except ValueError:
        return v
    return int(f) if f.is_integer() and "." not in t else f


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def read(path, header_row=None):
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        tables, skipped = read_xlsx(path, header_row)
    elif ext == ".numbers":
        tables, skipped = read_numbers(path, header_row)
    elif ext in (".csv", ".tsv"):
        tables, skipped = read_delimited(path, header_row)
    else:
        sys.exit(f"Unsupported file type '{ext}'. Numbers can export Excel, CSV, TSV or Numbers files.")
    return {"file": str(path), "format": ext.lstrip("."), "tables": tables, "skipped": skipped}


if __name__ == "__main__":
    # Windows pipes and redirects default to the ANSI code page (cp1252), which can't
    # encode the symbols this tool prints; write UTF-8 everywhere instead.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    hr = None
    if "--header-row" in args:
        i = args.index("--header-row")
        hr = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    if len(args) != 1:
        sys.exit(__doc__)
    print(json.dumps(read(args[0], hr), indent=2, ensure_ascii=False, default=str))
