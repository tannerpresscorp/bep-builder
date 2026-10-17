---
name: run-bep-builder
description: Build, run, and drive bep-builder's three runnable parts — the web app (screenshot it in headless Chromium), the bep.py CLI, and the bep_mcp MCP server (launch it over stdio and call its tools). Use when asked to run, start, serve, launch, screenshot, smoke-test or try out the BEP builder app, the CLI, or the MCP server, or to check a change works in the real app rather than only in the tests.
---

# Run bep-builder

bep-builder has three runnable parts that share one plan JSON format. Drive the **web app** with `.claude/skills/run-bep-builder/web.cjs`, which uses Playwright and headless Chromium. Drive the **MCP server** with `.claude/skills/run-bep-builder/mcp_drive.py`, which launches it as a stdio subprocess. The **CLI** is plain commands. All paths are relative to the repository root.

## Prerequisites

Python 3.10+ (3.8+ is enough for the CLI alone). The web driver also needs Node with the `playwright` package and a Chromium. This container already had `playwright@1.56.1` installed globally (`NODE_PATH=/usr/local/lib/node_modules_global`) and Chromium at `/opt/pw-browsers/chromium`; the driver uses that path when it exists. Elsewhere, install them with `npm i -g playwright && npx playwright install chromium`.

```bash
python -m pip install openpyxl defusedxml      # only maps-workbook / apply-maps need these
```

## Web app (agent path)

Build the Pages version and serve **`_site/`**, not `app/` (see Gotchas). Then run the driver:

```bash
python tools/build_pages.py
(python3 -m http.server 8000 --bind 127.0.0.1 --directory _site >/tmp/bep-http.log 2>&1 &)
timeout 15 bash -c 'until curl -sf http://127.0.0.1:8000/ >/dev/null; do sleep 0.3; done'
node .claude/skills/run-bep-builder/web.cjs            # [URL] [OUT_DIR] optional
```

The driver works through this flow:
1. It opens the page and loads the example plan, confirming the replace prompt if it appears.
2. It checks that the progress bar reads `11 of 11 sections complete`.
3. It opens **05 Process**.
4. It runs the NCS name checker on **09 Standards** and expects `AD-101` to be flagged.

It also fails on console errors and on mojibake. Screenshots go to `/tmp/bep-shots/` (`01-start.png` … `04-name-checker.png`); **look at them**. The exit code is 0 only when every check passes. To test a different flow, edit `web.cjs`. The sheet buttons are `#index [data-goto="<step id>"]`, actions are `[data-action="…"]`, and the step ids are in `STEPS` in `app/index.html`.

Stop the server:

```bash
lsof -ti:8000 -sTCP:LISTEN | xargs -r kill
```

Human path: the same server, then open <http://127.0.0.1:8000/> in a browser.

## MCP server (agent path)

Install it in a virtualenv. The editable install is required, because the server finds `bep.py` relative to its own source. Then run the driver with that venv's Python:

```bash
python3 -m venv /tmp/bep-venv
/tmp/bep-venv/bin/pip install -e servers/bep_mcp
/tmp/bep-venv/bin/python .claude/skills/run-bep-builder/mcp_drive.py /tmp/bep-venv/bin/bep_mcp
```

The driver launches `bep_mcp` with `BEP_PLANS_DIR` set to a new temporary folder (or the folder you pass as the second argument). It then works through one session:
1. It lists the tools (17) and the `start_bep` prompt, and renders the prompt.
2. It creates a USACE plan, sets `project.name`, adds a team row and turns on the `coord` BIM use.
3. It checks some names, reads the `bep://plans/demo.json` resource and lists the TODOs.
4. It confirms that a bad field name and a `../` path are refused.
5. It saves `demo.md`.

Each step prints `ok` or `FAIL`, and the exit code is 1 if any step failed. The server writes one log line per tool call to stderr. Add `2>/dev/null` to hide them.

To use it from Claude Code (human path): `claude mcp add bep -e BEP_PLANS_DIR="$HOME/plans" -- bep_mcp`.

## CLI

```bash
T=$(mktemp -d); B="python skills/bep-builder-cli/scripts/bep.py"
$B init $T/plan.json --example          # or --agency usace|gsa|va|federal|state|private
$B status $T/plan.json                  # ends "11 of 11 sections complete · 0 TODO items"
$B validate $T/plan.json --strict       # exit 1 while TODOs remain
$B check-names A-WALL-FULL a-door AD-101   # "1 valid, 2 to fix"
$B export $T/plan.json -o $T/plan.md
```

## Test

```bash
python tests/test_bep.py    # 20 PASS; the app halves need node on PATH
python tests/test_mcp.py    # 11 PASS; needs the mcp package (run with /tmp/bep-venv/bin/python if it isn't global)
```

## Gotchas

- **Serving `app/` directly shows mojibake** ("â€”" for "—", "â†’" for "→"). `app/index.html` is a Claude artifact page with no `<head>` or `<meta charset>`, so `http.server` sends no charset and Chromium decodes it as Latin-1. `tools/build_pages.py` adds the charset and writes `_site/index.html`; serve that. `web.cjs` fails loudly if it sees mojibake.
- **The app saves to `localStorage` outside Claude**, and a banner says so. Each driver run gets a fresh browser profile, so it always starts empty. In a reused browser, "Load example project" asks for confirmation first; the driver handles both cases.
- **The toast "Example project loaded" stays on screen for a moment** and covers the bottom of the screenshots. It's harmless.
- **`bep_set_bim_use` takes `use_id`, not `id`.** Passing `id` returns a pydantic "Field required … use_id" error.
- **Blanking `project.cui` adds a TODO only on USACE plans.** The example plan is VA, so `validate --strict` still exits 0 after `set … project.cui ""`.

## Troubleshooting

- **`web.cjs`: `FAIL mojibake on the page`**: you are serving `app/`. Stop it with `lsof -ti:8000 -sTCP:LISTEN | xargs -r kill`, then serve `_site/` as shown above.
- **`ss -ltnp` shows no pid for port 8000** in this container, so it can't find the server process. Use `lsof -ti:8000 -sTCP:LISTEN` instead.
