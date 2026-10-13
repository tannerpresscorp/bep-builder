# Reference

Facts about the repository, to look up rather than read through. For *why* things are built this way, see [architecture.md](architecture.md). For step-by-step changes, see [how-to.md](how-to.md).

- [Repository layout](#repository-layout)
- [Plan JSON](#plan-json)
- [CLI commands](#cli-commands)
- [Other scripts](#other-scripts)
- [Module dependencies](#module-dependencies)
- [Web app script sections](#web-app-script-sections)
- [Logic that exists twice](#logic-that-exists-twice)
- [Tests](#tests)
- [MCP server](#mcp-server)
- [CI and deployment](#ci-and-deployment)

## Repository layout

| Path | What it is |
|---|---|
| `app/index.html` | The web app, written as a Claude artifact page: its `<title>`, `<link>` and `<style>` come first, followed by the HTML and a single `<script>`. There is no `<!doctype>` or `<head>`; the hosting adds them. |
| `tools/build_pages.py` | Wraps `app/index.html` in a full HTML document (doctype, charset, language, viewport) for GitHub Pages. Writes `_site/index.html` by default. |
| `skills/bep-builder-cli/` | Claude skill plus the `bep.py` command-line tool and its helper modules. |
| `skills/national-cad-standard/` | Skill for NCS layer and sheet naming: `check_names.py`, `iso13567.py`, and USACE overrides in `references/`. |
| `skills/whole-building-design-guide/` | Skill for WBDG / NBIMS-US lookups. It has reference notes only, no scripts. |
| `skills/ios-numbers-spreadsheets/` | Skill for round-tripping spreadsheets with Apple Numbers: `read_tables.py`, `diff_tables.py`, `setup_numbers.sh`. |
| `skills/*/SKILL.md` | The skill's instructions. Its YAML front matter (`name`, `description`) is what Claude reads to decide when to use the skill. |
| `skills/*/evals/evals.json` | Example prompts, each with the output expected (`id`, `prompt`, `expected_output`, `files`), for evaluating the skill. No test in this repo runs them. |
| `examples/example-plan.json` | A complete example plan (11 of 11 sections, 0 TODOs). |
| `servers/bep_mcp/` | The MCP server: `bep_mcp/server.py`, its `pyproject.toml` (package `bep-mcp`, command `bep_mcp`), a README listing the tools, and `evals/` (10 evaluation questions with two fixture plans). |
| `docs/design/` | Design proposals, such as `mcp-server.md`. |
| `tests/test_bep.py` | The main test suite. |
| `tests/test_mcp.py` | The MCP server's tests. |
| `.github/workflows/` | `ci.yml` (tests on Linux and Windows), `pages.yml` (deploys the app) and `copilot-setup-steps.yml` (environment for GitHub Copilot's coding agent). |
| `.github/dependabot.yml` | Keeps the GitHub Actions versions up to date. |
| `.devcontainer/devcontainer.json` | Codespaces / dev container: Python 3.12, Node 20, openpyxl, defusedxml and `mcp`, port 8000 forwarded. |
| `SECURITY.md` | How to report a vulnerability. |
| `workspace/` | Empty folder for local working files. |
| `CLAUDE.md` | Guidance for Claude Code sessions in this repo. |

## Plan JSON

`blank_plan()` in `bep.py` and `blankPlan()` in the app define the plan. A saved plan is a JSON object with these keys:

| Key | Type | Contents |
|---|---|---|
| `v` | int | Format version, currently `1`. |
| `project` | object | `name`, `owner`, `location`, `delivery`, `agency` (one of `private`, `gsa`, `usace`, `va`, `federal`, `state`), `phase`, `start` (`YYYY-MM-DD`), `cui` (`""`, `"yes"` or `"no"`), `iso` (bool: tag sections with ISO 9001 clauses). |
| `team` | list | Rows of `{role, org, name, email}`. |
| `goals` | list | Rows of `{goal, uses}`. |
| `uses` | object | One entry per BIM use id (see `bep.py catalog`): `{on, party, value, flow}`. |
| `exchanges` | list | Rows of `{what, from, to, content, lod, due, feeds}`. `feeds` is an optional BIM use id that fixes where the exchange appears on the process map. |
| `cobie` | bool | COBie handover required. |
| `collab` | object | `cde`, `sharing`, `meetings`, `coords`, `naming`, `changes`. |
| `tech` | list | Rows of `{discipline, software, version, formats}`. |
| `standards` | object | `ncs`, `level2`, `minor`, `status` (derived from `statusField`), `sheet` (`level1`, `level2`, `campus`), `codes` (rows of `{code, meaning}`), `plotting`, `notes`, `statusField` (`both`, `status`, `phase`, `none`), `iso13567` (bool), `layerFormat` (`element`, `view`), `sheetCode` (4 characters, default `SHET`). |
| `qc` | object | Model rules `a0`–`a8` (authoring) and `d0`–`d8` (delivery): `{on, who, freq}`. |
| `checks` | object | `visual`, `clash`, `standards`, `integrity`: `{tool, who, freq}`. |
| `deliver` | list | Rows of `{item, format, due}`. |

When the web app runs as a Claude artifact, it stores the plan wrapped as `{"plan": {...}, "updatedBy": ..., ...}`. `bep.py load()` accepts either form.

`normalize()` repairs whatever it is given: it fills missing keys from the blank plan, replaces a section that has been damaged into a plain value with a blank one, and fills every list row from its row template (`ROW_TEMPLATES`), treating `null` fields as missing. `save()` writes atomically through a temporary file, keeps the file's permissions, and refuses to replace a read-only plan.

The 11 sections, in order, are: 01 project, 02 team, 03 goals, 04 uses, 05 process, 06 exchanges, 07 collab, 08 tech, 09 standards, 10 qc, 11 deliver. `section_status()` (Python) and `status()` (app) decide whether each is `done`, `partial` or `empty`.

## CLI commands

Run from `skills/bep-builder-cli/scripts/` as `python bep.py COMMAND ...`. Use `python bep.py COMMAND -h` for every option.

The editing and checking commands are thin wrappers around plain functions in `bep.py`'s "plan operations" section: `add_row`, `remove_row`, `set_use`, `set_qc`, `check_names`, `convert_layers` and `layer_definition`, alongside `set_path` for `set`. These change the plan or return data and raise `ValueError` with a message for people, so other callers, such as the [MCP server](#mcp-server), behave exactly like the CLI.

| Command | Does |
|---|---|
| `init PLAN [--example] [--agency A] [--force]` | Create a plan file (blank, or the example). |
| `catalog` | List every id the other commands accept: BIM uses, agencies, status fields, layer formats, sheet levels, QC rules and checks. |
| `show PLAN [PATH]` | Print the plan, or one value such as `project.name`. |
| `set PLAN PATH VALUE` | Set one value. Unknown fields, invalid values, negative row indexes and whole sections or lists (`set plan.json team foo`) are rejected. |
| `add PLAN LIST key=value ...` | Add a row to `team`, `goals`, `exchanges`, `tech`, `deliver` or `standards.codes`. It fills a blank placeholder row first. |
| `remove PLAN LIST INDEX` | Remove a row (0-based). |
| `use PLAN USE_ID [--off] [--party P] [--value V] [--flow F]` | Turn a BIM use on or off and fill in its details. |
| `qc PLAN ID [--off] [--who W] [--freq F] [--tool T]` | Set up a model rule (`a0`–`d8`) or a check (`visual`, `clash`, `standards`, `integrity`). |
| `status PLAN` | Show the completion of all 11 sections. |
| `validate PLAN [--strict]` | List every TODO. `--strict` exits 1 while any remain. |
| `check-names [--plan PLAN] NAME ... \| --file F` | Check NCS layer names and sheet ids. With `--plan`, it applies that plan's status-field and ISO 13567 settings. |
| `convert PLAN NAME ... [--anno-element CODE]` | Suggest ISO 13567 names for existing layers. |
| `definition PLAN [-o OUT]` | Write the ISO 13567-3 layer naming system definition file. |
| `process-map PLAN [--format mermaid\|tldraw] [-o OUT]` | Draw the Level 1 process map (section 05). |
| `maps-workbook PLAN [PLAN ...] -o OUT.xlsx` | Write the process-map workbook. Needs openpyxl. |
| `apply-maps PLAN FILE [--project NAME] [--dry-run]` | Apply an edited workbook (`.xlsx`, `.numbers` or `.csv`) to the plan. |
| `export PLAN [--format md\|html] [-o OUT]` | Write the finished plan. |

## Other scripts

| Script | Usage |
|---|---|
| `skills/national-cad-standard/scripts/check_names.py` | `python check_names.py [--status-field both\|status\|phase\|none] NAME ... \| --file F`. Prints a Markdown table. Its docstring mentions `references/conventions.md`; that file is deliberately not in the repo (see [architecture.md](architecture.md#licensing)). |
| `iso13567.py` (both copies) | `python iso13567.py {check,convert,definition} ...`. It works on its own as well as being imported by `bep.py`. |
| `skills/ios-numbers-spreadsheets/scripts/read_tables.py` | `python read_tables.py FILE [--header-row N]`. Prints a spreadsheet's tables as JSON. |
| `skills/ios-numbers-spreadsheets/scripts/diff_tables.py` | `python diff_tables.py ORIGINAL EDITED [--key "Table=Col,Col"] [--json]`. Shows what changed between two copies of a spreadsheet. |
| `skills/ios-numbers-spreadsheets/scripts/setup_numbers.sh` | Installs `numbers-parser` in its own virtual environment and prints the Python to use for `.numbers` files. |

## Module dependencies

```mermaid
flowchart LR
  bep[bep.py] --> iso[iso13567.py]
  bep --> pm[processmap.py]
  bep -. maps-workbook .-> mb[mapsbook.py]
  bep -. apply-maps .-> rt[read_tables.py]
  mb --> pm
  mb --> ox[(openpyxl)]
  rt -. .xlsx .-> ox
  rt -. .numbers .-> np[(numbers-parser)]
  dt[diff_tables.py] --> rt
```

Dashed arrows are imports that happen only when that feature is used. Everything else is the Python standard library. Install `defusedxml` next to openpyxl: openpyxl uses it, when present, to read workbooks safely. CI and the dev container install both. `mapsbook.put()` writes plan text that starts with `=` as text, so it can't become a live spreadsheet formula. The web app has no dependencies; it loads IBM Plex fonts from Google Fonts and falls back to system fonts when offline.

## Web app script sections

The `<script>` in `app/index.html` is split by `/* ---------- Name ---------- */` markers:

| Section | Holds |
|---|---|
| Reference data | `HELP`, `STEPS`, `AGENCIES`, `USES`, QC rules, `FREQ` |
| State | `blankPlan()`, `examplePlan()`, and the `plan`, `current` and `mode` variables |
| Helpers | `esc`, `getPath`/`setPath`, `saveFile()` (downloads, through the artifact's `downloads` capability or a plain browser download), `input()`, `editTable()` |
| Completion | `status()`, the JavaScript counterpart of `section_status()` |
| Section renderers | One renderer per section (`R`) |
| ISO 13567 profile | `profileFor`, `isoCheck`, `isoConvert`, `isoDefinition` (port of `iso13567.py`) |
| Level 1 process map | `USE_WORDS`, `buildMap`, `mapToMermaid` (port of `processmap.py`) |
| Document model → Markdown / HTML | `buildDoc`, `docToMd`, `docToHtml` (port of `build_doc` and its exporters) |
| NCS name checker | `checkLayer`, `checkSheet` (port of `check_names.py`) |
| Render | `renderIndex`, `renderSheet`, `renderAll`, ... |
| Saving | `ROW_TEMPLATES`, `normalize()`, `buildPatch`, `overlayEdits`, `scheduleSave`, `flush`, `onRemote` |
| Events | Click and input handlers |
| Boot | Restores the last step, then `boot()` chooses shared or local saving |

The tests run everything **above the Events marker** in Node, so code they call must stay there.

## Logic that exists twice

| Python | JavaScript (app) | Kept in step by |
|---|---|---|
| `bep.py blank_plan()` | `blankPlan()` | review |
| `bep.py example_plan()` and `examples/example-plan.json` | `examplePlan()` | `test_examples_in_sync` |
| `bep.py normalize()` and `ROW_TEMPLATES` | `normalize()` and `ROW_TEMPLATES` | `test_app_normalize_matches_cli_on_damaged_plans` |
| `bep.py section_status()` | `status()` | review |
| `bep.py build_doc()`, `to_markdown()`, `to_html()` | `buildDoc()`, `docToMd()`, `docToHtml()` | review |
| `bep.py USES`, `AGENCIES`, `QC_*` | `USES`, `AGENCIES`, QC constants | review |
| `processmap.py` (including `USE_KEYWORDS`) | `buildMap()`, `mapToMermaid()`, `USE_WORDS` | `test_app_matches_cli` |
| `iso13567.py` | `isoCheck()`, `isoConvert()` | `test_app_matches_cli` |
| `check_names.py` and `bep.py check_layer` / `check_sheet` | `checkLayer()`, `checkSheet()` | review |

Identical file copies between skills: `iso13567.py` (bep-builder-cli and national-cad-standard) and `read_tables.py` (bep-builder-cli and ios-numbers-spreadsheets). No test compares them; check with `diff` (see [how-to.md](how-to.md#edit-a-module-that-is-copied-between-skills)).

## Tests

`python tests/test_bep.py` runs every `test_*` function and exits 1 if any fail. There are 15:

| Test | Guards | Needs |
|---|---|---|
| `test_ncs_names` | NCS layer and sheet rules in `check_names.py`. | |
| `test_iso13567_profile` | ISO 13567 checks and conversions, including the `SHET` sheet code. | |
| `test_cli_plan_lifecycle` | `init`, `set` validation, `use`, `validate --strict`, `export` (USACE overrides, Mermaid map) and the firm defaults. | |
| `test_process_map_example` | Map edges and phase placeholders for the example plan. | |
| `test_examples_in_sync` | The three copies of the example plan are identical and have no TODOs. | Node (app part) |
| `test_maps_workbook_round_trip` | Workbook → edit → apply: an unchanged workbook applies as a no-op, applying twice gives the same result, and `diff_tables.py` output. | openpyxl |
| `test_app_matches_cli` | The app's process map and ISO 13567 results equal Python's. | Node |
| `test_set_refuses_sections_and_keeps_file_valid` | `set` rejects sections, lists and negative indexes, and leaves the plan file untouched when it does. | |
| `test_partial_rows_are_filled_from_templates` | `normalize()` fills rows that are missing fields, so `export` doesn't crash. | |
| `test_maps_workbook_writes_plan_text_as_text` | Plan text starting with `=` stays text in the workbook. | openpyxl |
| `test_app_downloads_without_the_claude_capability` | The app's downloads work as a plain browser download outside Claude. | Node |
| `test_app_shared_save_keeps_teammates_changes` | Shared saving sends only changed fields and doesn't overwrite a teammate's edits. | Node |
| `test_app_normalize_matches_cli_on_damaged_plans` | The app's `normalize()` repairs a damaged plan exactly as Python's does. | Node |
| `test_pages_build_is_a_full_document` | `tools/build_pages.py` produces a full HTML document, and running it twice changes nothing. | |
| `test_plan_operations_are_plain_functions` | `add_row`, `remove_row`, `set_use`, `set_qc` and `check_names` return data and raise `ValueError` rather than printing and exiting. | |

Tests that need Node or openpyxl print `(skipped: ...)` and **pass** when the tool is missing. CI has both, so run them locally with both before pushing.

`python tests/test_mcp.py` runs the MCP server's 9 tests. They need Python 3.10+ and `pip install "mcp>=2,<3"`, and print `skipped` without the SDK.

| Test | Guards |
|---|---|
| `test_tool_list_and_annotations` | The 17 tools exist, with the right read-only and destructive hints. |
| `test_read_tools_match_the_cli` | Export (Markdown and HTML), the tldraw map and the layer definition equal the CLI's output. |
| `test_plan_names_cannot_leave_the_plans_folder` | Folder names, `..`, escaping symlinks and unreadable JSON are refused with a clear error. |
| `test_write_tools_write_what_the_cli_writes` | After each write tool, the plan file is byte-identical to the one the matching CLI command writes. |
| `test_write_tools_refuse_bad_input_and_keep_the_file` | A refused write leaves the plan file untouched; a read-only file gives a clear error (skipped on Windows and as root). |
| `test_save_document_matches_the_cli` | `bep_save_document` writes the same files as `export -o` and `definition -o`. |
| `test_concurrent_writes_are_not_lost` | Twenty simultaneous `bep_add_row` calls keep all twenty rows. |
| `test_eval_answers_match_the_fixtures` | Each answer in `servers/bep_mcp/evals/evals.xml` still matches what the tools return for the fixture plans. |
| `test_server_needs_a_plans_folder` | The server refuses to start without a valid `BEP_PLANS_DIR`. |

## MCP server

Install with `python -m pip install -e servers/bep_mcp` (editable, from inside the repository, so it finds `bep.py`), then register it with a client, for example `claude mcp add bep -e BEP_PLANS_DIR="$HOME/plans" -- bep_mcp`.

| Setting | Meaning |
|---|---|
| `BEP_PLANS_DIR` | Required. The folder whose `*.json` files are the plans the tools can see. |
| `BEP_CLI_DIR` | Optional. The folder holding `bep.py`, if not this repository's `skills/bep-builder-cli/scripts/`. |

| Tool | CLI equivalent | Kind |
|---|---|---|
| `bep_list_plans` | (none) | read |
| `bep_get_catalog` | `catalog` | read |
| `bep_get_plan` | (none; reads the JSON) | read |
| `bep_get_status` | `status` | read |
| `bep_list_todos` | `validate` | read |
| `bep_check_names` | `check-names` | read |
| `bep_convert_layers` | `convert` | read |
| `bep_get_process_map` | `process-map` | read |
| `bep_export_plan` | `export` | read |
| `bep_get_layer_definition` | `definition` | read |
| `bep_create_plan` | `init` | write; destructive with `overwrite` |
| `bep_set_value` | `set` | write |
| `bep_add_row` | `add` | write |
| `bep_remove_row` | `remove` | destructive |
| `bep_set_bim_use` | `use` | write |
| `bep_set_qc` | `qc` | write |
| `bep_save_document` | `export -o`, `definition -o` | destructive (replaces a file of the same name) |

The server logs one line per tool call to stderr; stdout carries the protocol.

## CI and deployment

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | Every push and pull request | On Ubuntu **and Windows**: Python 3.12 + Node 20, `pip install openpyxl defusedxml "mcp>=2,<3"`, `python tests/test_bep.py`, `python tests/test_mcp.py`, then exports the example plan. |
| `pages.yml` | Push to `master` that changes `app/**`, `tools/build_pages.py` or the workflow itself, or a manual run | Runs `python3 tools/build_pages.py app/index.html _site/index.html`, uploads `_site/` and deploys it to GitHub Pages: <https://tannerpresscorp.github.io/bep-builder/>. |
| `copilot-setup-steps.yml` | Changes to itself, or a manual run | Prepares Python, Node, openpyxl, defusedxml and `mcp` for GitHub Copilot's coding agent. |

Because CI runs on Windows too, code and tests must not assume POSIX paths or shell commands. Dependabot opens pull requests to update the Actions versions. The repository also runs CodeQL and AI code review (Copilot, Codex) on pull requests; those are GitHub settings, not workflow files in this repository.
