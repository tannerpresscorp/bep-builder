# Tutorial: your first hour with bep-builder

In this tutorial you'll run the tests, build a plan with the command-line tool, open the same plan in the web app, and watch the test suite catch a deliberate mistake. By the end you'll have touched every part of the repository.

You need **git**, **Python 3.8 or newer** and, ideally, **Node.js** (any recent version). If you open the repository in a GitHub Codespace, all of this is already set up, and you can skip the install command in step 1. Commands run from the repository root unless a step says otherwise. Run them in order, in one terminal.

## 1. Get the code and install the one optional package

```bash
git clone https://github.com/tannerpresscorp/bep-builder.git
cd bep-builder
python -m pip install openpyxl defusedxml
```

These are the only packages outside the Python standard library, and only the spreadsheet features need them. openpyxl reads and writes workbooks; defusedxml lets it read them safely.

## 2. Run the tests

```bash
python tests/test_bep.py
```

You should see:

```text
PASS test_ncs_names
PASS test_iso13567_profile
PASS test_cli_plan_lifecycle
PASS test_process_map_example
PASS test_examples_in_sync
PASS test_maps_workbook_round_trip
PASS test_app_matches_cli
PASS test_set_refuses_sections_and_keeps_file_valid
PASS test_partial_rows_are_filled_from_templates
PASS test_maps_workbook_writes_plan_text_as_text
PASS test_app_downloads_without_the_claude_capability
PASS test_app_shared_save_keeps_teammates_changes
PASS test_app_normalize_matches_cli_on_damaged_plans
PASS test_pages_build_is_a_full_document
PASS test_plan_operations_are_plain_functions
```

That's 15 tests. If a line ends in `(skipped: Node.js not installed)`, the test passed without running its JavaScript half. Install Node to see it run for real.

## 3. Build a plan with the CLI

Make a scratch folder so the plan files stay out of the repository, then create the example plan:

```bash
mkdir -p /tmp/bep-tour
python skills/bep-builder-cli/scripts/bep.py init /tmp/bep-tour/plan.json --example
python skills/bep-builder-cli/scripts/bep.py status /tmp/bep-tour/plan.json
```

`status` lists the 11 BEP sections and ends with `11 of 11 sections complete · 0 TODO items`.

Now change something. Switch the project to a USACE job, clear its answer to the controlled unclassified information (CUI) question, and turn on a new BIM use without saying who is responsible for it:

```bash
python skills/bep-builder-cli/scripts/bep.py set /tmp/bep-tour/plan.json project.agency usace
python skills/bep-builder-cli/scripts/bep.py set /tmp/bep-tour/plan.json project.cui ""
python skills/bep-builder-cli/scripts/bep.py use /tmp/bep-tour/plan.json 4d
python skills/bep-builder-cli/scripts/bep.py validate /tmp/bep-tour/plan.json
```

`validate` now ends with `4 TODO items`. Three are for the 4D use (responsible party, why it's worth doing, the process flow). The fourth is the CUI decision, which only USACE projects need. Every blank that matters becomes a TODO instead of being left out.

Export the plan and look at it:

```bash
python skills/bep-builder-cli/scripts/bep.py export /tmp/bep-tour/plan.json -o /tmp/bep-tour/plan.md
grep -n "USACE / DoD overrides\|mermaid\|TODO:" /tmp/bep-tour/plan.md
```

The Markdown has a USACE overrides section, a Mermaid process map, and each TODO in bold.

## 4. Check some CAD names

The NCS name checker is one of the pieces a BIM manager uses most:

```bash
python skills/bep-builder-cli/scripts/bep.py check-names A-WALL-FULL a-door M_HVAC A-101 AD-101
```

The table flags lowercase letters, underscores, and a two-letter discipline code written with a hyphen. Each problem is explained in plain language.

## 5. Open the same thing in the web app

Build the page the way GitHub Pages does, then start a local server for it:

```bash
python tools/build_pages.py
python -m http.server 8000 --bind 127.0.0.1 --directory _site
```

`build_pages.py` wraps `app/index.html`, which is written as a Claude artifact page without a `<head>`, in a full HTML document, and writes it to `_site/index.html`.

Open <http://127.0.0.1:8000/> in a browser. On the first sheet, choose **Load example project**. The sheet index on the left fills in, and the progress bar reads **11 of 11 sections complete**. This is the same example plan the CLI made in step 3. Look at **05 Process**: its map is drawn by the JavaScript port of the Python process-map code.

The banner at the top says the plan is saved in this browser only. When the page runs as a Claude artifact, it saves to a store the whole team shares instead (see [architecture.md](architecture.md#how-the-app-saves)).

Stop the server with Ctrl+C when you're done.

## 6. Break something on purpose

The example plan exists in three places, and a test keeps them identical. Change the JSON copy only:

```bash
sed -i.bak 's/Springfield, IL/Shelbyville, IL/' examples/example-plan.json
python -c "import sys; sys.path.insert(0, 'tests'); import test_bep; test_bep.test_examples_in_sync()"
```

The test fails with an `AssertionError`, because `examples/example-plan.json` no longer matches `example_plan()` in `bep.py` and `examplePlan()` in the app. The same thing would happen in CI on a pull request.

Put the file back and confirm the suite is green again:

```bash
mv examples/example-plan.json.bak examples/example-plan.json
git status --short
python tests/test_bep.py
```

`git status --short` prints nothing, so the working tree is clean.

## 7. Tidy up

```bash
rm -rf /tmp/bep-tour _site
```

## What you've seen

- One **plan JSON** file drives everything: the CLI, the app and the exports.
- **TODOs** are how the tools say what's missing, rather than leaving gaps silently.
- The app **copies Python logic in JavaScript**, and tests catch the copies drifting apart.

Next, read [architecture.md](architecture.md) for why it's built this way, then keep [how-to.md](how-to.md) and [reference.md](reference.md) open while you work.
