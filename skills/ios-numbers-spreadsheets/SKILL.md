---
name: ios-numbers-spreadsheets
description: Round-trip spreadsheets with Apple Numbers on iPhone and iPad — build workbooks that open cleanly in Numbers, tell the user exactly how to open, edit, and send them back from their phone, then read whatever comes back (.numbers, Excel, CSV or TSV) and report precisely what changed. Use this whenever the user mentions Numbers, iOS or iPadOS spreadsheets, editing a spreadsheet on their phone or iPad, sends a .numbers file, or returns a workbook Claude made earlier after editing it on a mobile device — even if they just say "I updated the sheet on my phone".
---

# Spreadsheets with Numbers on iPhone and iPad

The user edits spreadsheets in Apple Numbers on iPhone or iPad. Claude can't open
Numbers, so the job is a clean round trip:

1. **Send** a workbook Numbers opens without surprises.
2. **Guide** the user through opening, editing, and sending it back from the phone.
3. **Read** what comes back, in any format Numbers produces, and **report what changed**.
4. **Apply** the changes to wherever the data really lives — only after the user agrees.

The scripts in `scripts/` do the mechanical parts. They agree with each other, so use
them rather than re-deriving file handling each time.

## 1. Build for Numbers

Deliver an **Excel file (.xlsx)**. Numbers opens Excel files directly and keeps their
formulas. A native `.numbers` file can be written here, but only with plain values (the
available library can't write formulas), so use `.numbers` output only for value-only
tables.

Build the workbook with the `xlsx` skill, keeping it simple, because Numbers converts
each worksheet into a Numbers sheet holding a table and anything elaborate is a chance
for the conversion to drift:

- **One table per worksheet, starting at A1, with a single header row.** That header
  becomes the Numbers header row, and it's also what the diff script uses to match
  columns when the file comes back.
- **Short, distinct worksheet names** (Excel's limit is 31 characters). Numbers' "one per
  table" export renames worksheets, so distinct names make matching reliable.
- **Plain formulas** — `SUM`, `IF`, `COUNTIFS`, `SUMIFS`, `INDEX`/`MATCH`, `IFERROR`, and
  `&` for joining text. Avoid dynamic-array functions (`FILTER`, `UNIQUE`, `XLOOKUP`),
  named ranges, and macros.
- **No merged cells inside data tables**; put titles and notes on their own sheet.
- **Mark editable cells visibly** (a fill color) and add a short Read Me sheet saying
  which cells to edit — the user is working on a small screen.
- **Treat dropdowns, comments, and conditional formatting as nice-to-haves.** Apple
  doesn't document how each Excel feature converts, so never make the workbook depend
  on one; if a dropdown matters, say "if the list doesn't appear, type one of: …".
- **Give every row a stable identifier** (an ID, or a pair like Project + Item). Row
  positions shift when someone sorts or inserts on a phone; identifiers don't.

Send the file with `SendUserFile` (`display: "attach"`), and keep the original — the
diff needs it.

## 2. Tell the user how to edit and send it back

Give these steps in plain words (from Apple's Numbers for iPhone guide):

- **Open:** save the attachment to Files, then tap it — it opens in Numbers. (In Numbers'
  document manager, tap **Browse**, find the file, and tap its thumbnail.)
- **Edit:** change the highlighted cells. Sorting and adding rows is fine.
- **Send back — easiest:** share the Numbers file itself (tap **More ⋯ → Share**, or share
  it from Files). This keeps formulas and every table.
- **Send back — as Excel:** **More ⋯ → Export → Excel**. If asked, choose **One per Sheet**;
  that keeps the original worksheet layout. (**One per Table** also works — the scripts
  handle the renamed worksheets and skip the summary sheet it can add.)
- **CSV or TSV** exports carry only cell values, and are best for one table at a time.
- If the spreadsheet has a **password**, Numbers puts it on the exported Excel copy too;
  ask the user to remove the password before exporting, since a protected file can't be
  read here.

## 3. Read what came back and report the changes

```bash
python scripts/read_tables.py FILE          # any format -> JSON tables (header + rows + formulas)
python scripts/diff_tables.py ORIGINAL EDITED --key "Table=Col A,Col B" [--json]
```

- `.xlsx`, `.csv` and `.tsv` work with the system Python.
- **`.numbers` needs `numbers-parser`.** Run `sh scripts/setup_numbers.sh`; it installs the
  library in its own environment (its protobuf version often clashes with system
  packages) and prints the Python to use, e.g. `/tmp/numbers-venv/bin/python
  scripts/diff_tables.py original.xlsx edited.numbers …`.
- **Always pass `--key`** with each table's identifier columns. Without keys the diff
  falls back to the first column (if unique) or row position, and a phone sort would
  then look like every row changed.

`diff_tables.py` matches tables by name or header similarity, columns by header text,
and rows by key, then lists changed cells (before → after), added and removed rows,
added or removed columns, and changed formulas.

Summarize the result for the user in plain words, grouped by table: "On the Uses sheet you
selected Phase planning for the barracks and named the Contractor VDC lead." Calculated
columns may differ simply because Numbers recalculated them — mention those only if a
formula itself changed.

## 4. Apply the changes

The spreadsheet is usually a working copy of something else (a plan file, a database, an
artifact's data). After summarizing, ask before writing changes back, then apply exactly
the reported changes — not a wholesale replace — so anything edited elsewhere in the
meantime survives. If the data has its own import command (for BEP plans:
`bep.py apply-maps`), use it.

## Things to watch for

- A returned file with **no changes** usually means the user sent the original back;
  say so rather than reporting success.
- **New tables or columns** the user added are reported; ask what they're for before
  folding them into anything.
- **Dates** come back as ISO text (`2026-10-12`); numbers typed into text columns may come
  back as numbers. Compare by meaning, not formatting.
