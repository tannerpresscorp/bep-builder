# BEP Builder

Tools for setting up and deploying a **BIM Execution Plan (BEP)**: a guided web app, a
command-line tool, and Claude skills that apply the U.S. National CAD Standard (NCS),
Whole Building Design Guide (WBDG) criteria, and agency overrides.

| Part | What it does |
|---|---|
| [`app/index.html`](app/index.html) | Single-page BEP builder: 11 sections following the NBIMS-US / Penn State procedure, NCS layer and sheet checks, ISO 13567 layer profiles, Level 1 process map, Markdown/HTML export. Shared team editing works when published as a Claude artifact; opened anywhere else it saves in the browser. |
| [`skills/bep-builder-cli`](skills/bep-builder-cli) | `bep.py` — create, fill, validate and export plans; check names; draw process maps (Mermaid or tldraw); build and re-apply the maps workbook. Python 3.8+, standard library (openpyxl for workbooks). |
| [`skills/national-cad-standard`](skills/national-cad-standard) | NCS layer/sheet checker, ISO 13567 profile checker and converter, USACE A/E/C Graphics Standard overrides. |
| [`skills/whole-building-design-guide`](skills/whole-building-design-guide) | WBDG / NBIMS-US lookup workflow, BEP outline, ISO 9001 clause alignment. |
| [`skills/ios-numbers-spreadsheets`](skills/ios-numbers-spreadsheets) | Round-trip spreadsheets with Apple Numbers on iPhone/iPad: read `.numbers`/Excel/CSV returns and diff them. |

The web app is published to GitHub Pages at
<https://tannerpresscorp.github.io/bep-builder/> on every push to `master` that changes
`app/` or `tools/build_pages.py` (`.github/workflows/pages.yml`). The workflow runs `tools/build_pages.py` to wrap the
artifact page in a full HTML document (doctype, charset, language, viewport) for Pages.

## Quick start (CLI)

```bash
cd skills/bep-builder-cli/scripts
python bep.py init plan.json --agency usace
python bep.py set plan.json project.name "Barracks"
python bep.py use plan.json coord --party "BIM manager"
python bep.py status plan.json
python bep.py validate plan.json --strict      # exit 1 while TODOs remain
python bep.py process-map plan.json            # Mermaid
python bep.py export plan.json -o plan.md
```

Try the full example: `python bep.py status ../../../examples/example-plan.json`.

## GitHub Copilot CLI

To enable draw.io diagram generation in Copilot CLI, add the draw.io marketplace and
install its plugin:

```bash
copilot plugin marketplace add jgraph/drawio-mcp
copilot plugin install drawio@drawio
```

## Firm defaults

New plans start with: ISO 13567 layer naming off (turn on per project), element layer
format, status letters in the status field, and `SHET` as the sheet-level annotation code
that replaces `ANNO` when ISO 13567 is on.

## Tests

```bash
pip install openpyxl defusedxml   # defusedxml: openpyxl uses it to read workbooks safely
python tests/test_bep.py
```

CI runs the same tests on every push (`.github/workflows/ci.yml`). When Node.js is
available, the tests also confirm the web app and the CLI produce identical process maps
and ISO 13567 results.

## Standards and licensing

- The NCS is licensed by the National Institute of Building Sciences. This repository
  contains no NCS text; reference summaries derived from a licensed copy are kept out of it.
  Check project-critical details against your own licensed copy.
- ISO 9001 and ISO 13567 are referenced by clause number only.
- The USACE A/E/C Graphics Standard (ERDC/ITL SR-23-1) is approved for public release.
- Autodesk help links point to Autodesk's public documentation.
