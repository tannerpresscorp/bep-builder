# How-to guides

Short recipes for the changes contributors make most often. Each one lists every place that has to change. The reasons behind these steps are in [architecture.md](architecture.md); exact names are in [reference.md](reference.md).

Commands run from the repository root unless a guide says otherwise.

- [Run the tests the way CI does](#run-the-tests-the-way-ci-does)
- [Run one test](#run-one-test)
- [Run the web app locally](#run-the-web-app-locally)
- [Smoke-test a change in the real app](#smoke-test-a-change-in-the-real-app)
- [Change logic that exists in both Python and JavaScript](#change-logic-that-exists-in-both-python-and-javascript)
- [Add a field to the plan](#add-a-field-to-the-plan)
- [Add a BIM use](#add-a-bim-use)
- [Change the example plan](#change-the-example-plan)
- [Edit a module that is copied between skills](#edit-a-module-that-is-copied-between-skills)
- [Edit a skill or its evals](#edit-a-skill-or-its-evals)
- [Deploy the web app](#deploy-the-web-app)
- [Run the MCP server locally](#run-the-mcp-server-locally)
- [Add or change an MCP tool](#add-or-change-an-mcp-tool)

## Run the tests the way CI does

CI runs the suite on Ubuntu and Windows with Node, openpyxl and defusedxml installed. Without Node or openpyxl, several tests print `(skipped: ...)` and still pass ([which ones](reference.md#tests)). Install everything so nothing is skipped:

```bash
python -m pip install openpyxl defusedxml "mcp>=2,<3"
node --version          # any recent Node; CI uses 20
python tests/test_bep.py
python tests/test_mcp.py
python tests/test_mcp_team.py
```

You should see 16 `PASS` lines, then 11 more, then 21 more, and no `skipped`. In a Codespace or dev container, all of this is already installed.

`test_mcp_team.py` also prints log lines from calls it makes on purpose to be refused, such as `Invalid Host header: evil.example.com` and `Tool 'bep_get_status' failed: "Error executing tool bep_get_status: You don't have access to a plan named 'alice-only.json'."`. The tests still pass. Count the `PASS` lines, not the log.

## Run one test

The suite has its own runner. To run a single test function:

```bash
python -c "import sys; sys.path.insert(0, 'tests'); import test_bep; test_bep.test_examples_in_sync(); print('ok')"
```

Replace `test_examples_in_sync` with any name from the [test list](reference.md#tests). pytest isn't a project dependency; if you have it installed, `python -m pytest tests/test_bep.py -k examples` also works (`-k examples` selects `test_examples_in_sync`).

## Run the web app locally

Build the same full HTML page that GitHub Pages serves, then serve it over HTTP:

```bash
python tools/build_pages.py
python -m http.server 8000 --bind 127.0.0.1 --directory _site
```

Then open <http://127.0.0.1:8000/>. Run `build_pages.py` again after each change to `app/index.html`; `_site/` is in `.gitignore`. Don't serve `app/` directly: it has no `<meta charset>`, so "—" and "→" appear garbled, and without the doctype and viewport the browser uses quirks mode and phones show the desktop layout ([why](architecture.md#why-the-web-app-is-a-single-file)). Avoid opening `app/index.html` straight from disk (`file://`): browsers don't guarantee `localStorage` for local files, and that is where the app saves outside Claude ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage)).

Run this way, the app shows "Shared saving isn't available here" with a button, **Open the shared team plan**, that links to the team's shared artifact, and saves to your browser. To clear a saved plan, use **Clear plan** (under "Start over" on the review page), or remove the `bep-builder-plan` key in the browser's developer tools.

## Smoke-test a change in the real app

The tests never open a browser. To see a change working in the web app and the MCP server, use the repository's run skill, `.claude/skills/run-bep-builder/` (a project skill for this repo's sessions, not one of the installable `skills/*`). Read its `SKILL.md` first: it lists the prerequisites (Node with the `playwright` package, and a Chromium) and the gotchas.

With the `_site/` server from the previous section running, drive the web app:

```bash
node .claude/skills/run-bep-builder/web.cjs
```

It loads the example plan, opens **05 Process**, runs the name checker, prints each step and the screenshot paths (open them), and exits 0 only if every check passes. It also fails on console errors and on garbled "—" and "→", which means you served `app/` instead of `_site/`.

Then drive the MCP server from a virtual environment that has it installed:

```bash
python3 -m venv /tmp/bep-venv
/tmp/bep-venv/bin/pip install -e servers/bep_mcp
/tmp/bep-venv/bin/python .claude/skills/run-bep-builder/mcp_drive.py /tmp/bep-venv/bin/bep_mcp 2>/dev/null
```

Each step prints `ok` or `FAIL`, and the exit code is 1 if any step failed. The driver leaves the temporary plans folder it prints (`plans folder: ...`) behind; delete it when you're done, along with the virtual environment, `_site/` and the screenshots. Stop the server with `lsof -ti:8000 -sTCP:LISTEN | xargs -r kill`.

## Change logic that exists in both Python and JavaScript

Most behaviour lives in both `bep.py` (or its helper modules) and `app/index.html`. The full list of pairs is in [reference.md](reference.md#logic-that-exists-twice).

1. Make the change in Python and run the tests.
2. Find the matching JavaScript. Each port's section marker names its Python source, for example `/* ---------- Level 1 process map (port of processmap.py) ---------- */`. The function names are close (`build_doc` → `buildDoc`, `check_layer` → `checkLayer`).
3. Make the same change in JavaScript. Keep it **above** the `/* ---------- Events ---------- */` marker, because the tests load only that part of the script into Node.
4. Run the tests with Node installed. `test_app_matches_cli` compares the process map and ISO 13567 output between the two languages.
5. For logic no test compares (completion rules, the document builder, the name checker; see [the table](reference.md#logic-that-exists-twice)), check both sides by hand. Export the example plan from the CLI, then load it in the app (**Load example project**) and compare the review page with the export.

## Add a field to the plan

Example: a new `collab.software` field.

1. Add it with its default to `blank_plan()` in `skills/bep-builder-cli/scripts/bep.py`, and to `blankPlan()` in `app/index.html`. `normalize()` on both sides then fills it into older plans automatically.
2. If it is a field of a list row (for example a new `team` column), add it to `ROW_TEMPLATES` in both `bep.py` and the app's Saving section, so older rows are filled in. A new list needs its own entry in both.
3. If it is an on/off value, make the default a real boolean (`False` / `false`). `bep.py set` uses the default's type to decide whether to accept yes/no.
4. If it is limited to fixed values, add a check to `set_path()` in `bep.py`, as `project.agency` has.
5. If it should count toward completion, update `section_status()` (Python) and `status()` (app) the same way.
6. To show it in the exported plan, update `build_doc()` (Python) and `buildDoc()` (app). A blank value should become a TODO: wrap it as `val(value, "what is missing")`, which has the same name and arguments in both languages.
7. Add an input for it in the section's renderer in the app, using `input("collab.software", "Label")`. The renderers are `R.<section>`. Most are under the "Section renderers" marker, but `R.qc`, `R.deliver` and `R.review` sit after the "ISO 13567 profile" marker ([list](reference.md#web-app-script-sections)).
8. If the example plan should fill it, follow [Change the example plan](#change-the-example-plan).
9. Run the tests with Node installed. Shared saving picks the field up automatically: inputs carry their `data-path`, and the app saves changed paths only.

## Add a BIM use

The BIM use catalog is in four places:

| Place | Add |
|---|---|
| `USES` in `bep.py` | `("id", "Display name", "Phase")` |
| `USES` in `app/index.html` (Reference data) | `{ id, name, phase, desc }` and, optionally, a `link: [label, url]` |
| `USE_KEYWORDS` in `processmap.py` | Keywords that place exchanges on this use |
| `USE_WORDS` in `app/index.html` (Level 1 process map) | The same keywords |

The first phase listed picks the process-map column: `Planning`, `Design`, `Construction` or `Operations`. `All`, or anything else, is placed in Design. Plans get the new use automatically through `normalize()`. The maps workbook's Keywords sheet reads `USE_KEYWORDS`, so it picks the new keywords up with no further change.

Then run the tests. `test_app_matches_cli` fails if the two keyword lists place an exchange differently.

## Change the example plan

The example exists in three places, and `test_examples_in_sync` requires them to be identical once normalized:

1. `examples/example-plan.json`
2. `example_plan()` in `bep.py`
3. `examplePlan()` in `app/index.html`

Edit all three, keep the values clearly labelled "Example", and leave no TODOs; the test also checks that. Two quick checks:

```bash
python skills/bep-builder-cli/scripts/bep.py validate examples/example-plan.json --strict
python -c "import sys; sys.path.insert(0, 'tests'); import test_bep; test_bep.test_examples_in_sync(); print('ok')"
```

`test_process_map_example` checks some edges of the example's process map, so changing its uses or exchanges may mean updating that test.

## Edit a module that is copied between skills

`iso13567.py` and `read_tables.py` each exist twice and must stay identical. Edit one copy, copy it over the other, and confirm:

```bash
cp skills/bep-builder-cli/scripts/iso13567.py skills/national-cad-standard/scripts/iso13567.py
cp skills/bep-builder-cli/scripts/read_tables.py skills/ios-numbers-spreadsheets/scripts/read_tables.py
diff -q skills/bep-builder-cli/scripts/iso13567.py skills/national-cad-standard/scripts/iso13567.py
diff -q skills/bep-builder-cli/scripts/read_tables.py skills/ios-numbers-spreadsheets/scripts/read_tables.py
```

No output from `diff -q` means the copies match. If you change the NCS layer or sheet rules, update `check_layer` / `check_sheet` in `bep.py`, `check_names.py`, and `checkLayer` / `checkSheet` in the app. These three are not byte-for-byte copies, so review them side by side.

## Edit a skill or its evals

- `SKILL.md` front matter (`name`, `description`) decides when Claude uses the skill. Keep the description specific about the requests the skill covers. The body is the instructions Claude follows.
- `evals/evals.json` lists example prompts with the expected outcome. Add one when you add a behaviour worth checking. Use made-up "Example" names, and never include licensed standard text; expected outputs must not invent project facts either.
- Scripts that a skill's instructions call must keep working from that skill's own folder. Don't import from another skill; copy the module instead (see above).

## Deploy the web app

There is nothing to run by hand. Merging a change to `app/` or `tools/build_pages.py` into `master` starts `pages.yml`. It wraps the page with `tools/build_pages.py` and publishes `_site/` to <https://tannerpresscorp.github.io/bep-builder/> within about a minute. To redeploy without a change, run the **Pages** workflow manually from the repository's Actions tab.

To confirm a deploy, build the page from your up-to-date `master` and compare it with the live one:

```bash
python tools/build_pages.py app/index.html _site/index.html
curl -sS https://tannerpresscorp.github.io/bep-builder/ -o _site/live.html
cmp -s _site/live.html _site/index.html && echo "live site matches master"
```

Don't add a second workflow that deploys to Pages; see [architecture.md](architecture.md#deployment).

## Run the MCP server locally

The server needs Python 3.10 or newer.

```bash
python -m pip install -e servers/bep_mcp
mkdir -p ~/plans
claude mcp add bep -e BEP_PLANS_DIR="$HOME/plans" -- bep_mcp
```

Then, in Claude Code, ask for something like "create an example plan called demo.json and list its TODOs", or run `/mcp__bep__start_bep` to be interviewed for a new plan. The server logs one line per tool call to stderr.

### Run it as a team server

To try the shared mode on your machine, make a token and a config **outside** the plans folder, then start the HTTP server (it listens on `127.0.0.1:8765`, endpoint `/mcp`):

```bash
bep_mcp --new-token                  # prints a token and its sha256; keep the token, put only the hash in the config
# write ~/bep-team.json as in servers/bep_mcp/README.md (Team server), with "public_url": "http://127.0.0.1:8765"
BEP_PLANS_DIR=$HOME/plans bep_mcp --http --config ~/bep-team.json
claude mcp add --transport http bep-team http://127.0.0.1:8765/mcp --header "Authorization: Bearer <token>"
```

For a real team, run it behind an HTTPS proxy as one process; the README has the config, grants and claude.ai steps. Plans made through this server live in its folder, separate from the web app's shared artifact. The two don't sync and there is no import step ([where plans live](../../servers/bep_mcp/README.md#where-plans-live), and [why](architecture.md#how-the-app-saves)).

## Add or change an MCP tool

1. If the tool needs new plan logic, add it to `bep.py` as a plain function that returns data and raises `ValueError` for bad input. Make the CLI command a thin wrapper around it, so both share one rule.
2. Add the tool in `create_server()` in `servers/bep_mcp/bep_mcp/server.py`, with the `@guarded(...)` decorator (`"viewer"` for a tool that reads a plan, `"editor"` for one that changes it, `None` for one with no plan) and the right annotation: `READ`, `EDIT` or `DESTRUCTIVE` (`bep_add_row` and `bep_save_document` build their `ToolAnnotations` inline, to set hints those constants don't). Take the plan as a file name and resolve it with `resolve_plan`; write through `_edit` so the change holds the write lock, takes an optional `if_version` and returns the new `version`. A tool that can't use `_edit` because it creates a plan or writes a document rather than editing a plan (`bep_create_plan`, `bep_save_document`) takes `WRITE_LOCK` itself. A new resource or prompt must call `check_plan_name` and `authorize` before it loads anything.
3. Name it `bep_<verb>_<noun>` and write the description for the model: what it does, what to call first, and what each argument accepts.
4. In `tests/test_mcp_team.py`, add the tool to the `TOOLS` table with the role it needs (the test `test_every_surface_has_a_rule` fails until you do), so the team tests check that someone without a grant is refused. In `tests/test_mcp.py`, add the tool to `test_tool_list_and_annotations` and compare its output with the matching CLI command. If you change what an existing tool returns, `test_eval_answers_match_the_fixtures` tells you whether an evaluation answer in `servers/bep_mcp/evals/evals.xml` has changed too (to run the evaluations themselves, see [the server README](../../servers/bep_mcp/README.md#evaluations)).
5. List it in `servers/bep_mcp/README.md` and in [reference.md](reference.md#mcp-server).
