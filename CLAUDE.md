# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Tools for writing a BIM Execution Plan (BEP) under the U.S. National CAD Standard (NCS), WBDG / NBIMS-US guidance and agency overrides (USACE, GSA, VA). There are three ways to use it, and all three share one plan format:

- `app/index.html`: the web app. It is a single self-contained page with no build step and no dependencies.
- `skills/bep-builder-cli/scripts/bep.py`: the command-line tool. It uses only the Python 3.8+ standard library; only `maps-workbook` needs `openpyxl`.
- `skills/*/`: Claude skills. Each has a `SKILL.md`, its `scripts/`, `references/` and `evals/evals.json`.

## Commands

```bash
pip install openpyxl                       # only needed for the maps workbook
python tests/test_bep.py                   # full suite; this is what CI runs
python -c "import sys; sys.path.insert(0,'tests'); import test_bep; test_bep.test_examples_in_sync()"   # run one test

cd skills/bep-builder-cli/scripts
python bep.py init plan.json --example     # or --agency usace|gsa|va|federal|state|private
python bep.py status plan.json             # completion of the 11 sections
python bep.py validate plan.json --strict  # lists TODOs; exits 1 while any remain
python bep.py export plan.json -o plan.md  # or --format html
python bep.py catalog                      # every id the other commands accept

python -m http.server -d app 8000          # serve the web app locally
```

There is no linter or formatter configured. `test_app_matches_cli` and the app half of `test_examples_in_sync` run only when `node` is on PATH, and print "skipped" otherwise. CI (`.github/workflows/ci.yml`) has Node, so make sure those tests pass locally with Node too.

## Architecture

**The plan JSON is the contract.** The web app and the command-line tool read and write the same structure, with these top-level keys: `project`, `team`, `goals`, `uses`, `exchanges`, `cobie`, `collab`, `tech`, `standards`, `qc`, `checks` and `deliver`.
- `bep.py load()` also accepts the app's stored document, which wraps the plan as `{"plan": {...}, "updatedBy": ...}`.
- `normalize()` fills in missing keys from `blank_plan()`, so older plans keep working. Add any new field to `blank_plan()` so this keeps working.
- The 11 sections follow the Penn State / NBIMS-US BEP procedure. `section_status()` decides whether each section is done, partial or empty. `build_doc()` turns the plan into document blocks, and any missing value becomes a `Todo` that `validate` and `export` report.

**The web app re-implements the Python logic in JavaScript.** Its `<script>` has `/* ---------- … ---------- */` section markers. Each port says which Python file it copies:
- ISO 13567 profile → `iso13567.py`
- Level 1 process map → `processmap.py`
- NCS name checker → `check_names.py`
- Document model → `bep.py`, including `blankPlan`/`normalize`, completion status and the reference data

A change to any of these must be made in both languages. The tests check the two stay in step:
- `test_app_matches_cli` loads everything in the app's script above the `/* ---------- Events ---------- */` marker into Node. It compares the process map and ISO results with the Python output. Code the tests need must stay above that marker.
- `test_examples_in_sync` requires `examples/example-plan.json`, `bep.py example_plan()` and the app's `examplePlan()` to be identical once normalized, and complete (no TODOs). Change all three together.

**Duplicate modules across skills.** Each skill is meant to be installed on its own, so some files are copied between them. Change every copy together:
- `iso13567.py` is identical in `bep-builder-cli/scripts/` and `national-cad-standard/scripts/`.
- `read_tables.py` is identical in `bep-builder-cli/scripts/` and `ios-numbers-spreadsheets/scripts/`.
- The NCS layer and sheet checks live in both `bep.py` (`check_layer`, `check_sheet`) and `national-cad-standard/scripts/check_names.py`.

**How the web app saves.** At start-up, the app checks whether it is running as a Claude artifact (`window.claude`):
- As an artifact, it saves to a shared store document named `bep/plan` and syncs with teammates through `onSnapshot`. Read-only viewers can't edit.
- Anywhere else it falls back to `localStorage` (key `bep-builder-plan`), and the page shows a banner saying it saves in this browser only.

**Process map.** `processmap.build()` builds one layout. It then outputs either Mermaid, used in the Markdown export and the app, or a tldraw `exec` script. Exchanges are placed on the arrow into the BIM use they feed. That use comes from the exchange's `feeds` field, or failing that from keyword matching against `USE_KEYWORDS`. Exchanges that match nothing are listed in a note rather than dropped.

**Maps workbook round trip.** `maps-workbook` writes an `.xlsx` with Uses, Exchanges, Summary and Keywords sheets. `apply-maps` reads an edited copy back in (`.xlsx`, `.numbers` or `.csv`, via `read_tables.py`) and updates the plan. Applying an unchanged workbook must change nothing, and applying the same edits twice must give the same result. The tests check both.

## Conventions

- **New plans start with these firm defaults:** ISO 13567 layer naming is off, the layer format is `element`, the status field uses status letters, and `sheetCode` is `SHET`. Under ISO 13567, `SHET` takes the place of `ANNO` for sheet-level annotation. Keep the CLI and the app in agreement on these.
- **Licensing:** the repository must contain no NCS text. Reference summaries made from a licensed copy are kept out of it. ISO 9001 and ISO 13567 are cited by clause number only. `.gitignore` excludes `*.pdf`, `*.numbers` and `plans/`, so project data and licensed standards aren't committed.
- **Deployment:** `.github/workflows/pages.yml` publishes only the `app/` folder to GitHub Pages, at https://tannerpresscorp.github.io/bep-builder/. It runs on pushes to `master` that change `app/`. Don't add a second Pages workflow: both deploy to the same site, and one would overwrite the other.
- **Example data:** keep example values clearly marked "Example"/"EXAMPLE". Skills and evals must never make up project facts. Anything unknown stays a TODO.
