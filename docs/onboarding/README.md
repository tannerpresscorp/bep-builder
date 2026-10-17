# Onboarding guide

A guide for new contributors to bep-builder. Each page has a single job:

| Page | Read it when | Type |
|---|---|---|
| [Tutorial: your first hour](tutorial-first-hour.md) | You've just cloned the repo. Do this first. | Tutorial |
| [Architecture](architecture.md) | You want to know why it's built this way: one plan format, a single-file app, logic written twice. | Explanation |
| [How-to guides](how-to.md) | You have a specific change to make: add a plan field, add a BIM use, deploy. | How-to |
| [Reference](reference.md) | You need an exact fact: a plan field, a CLI command, a test, a workflow. | Reference |

[CLAUDE.md](../../CLAUDE.md) is the condensed version for Claude Code sessions, and the top-level [README](../../README.md) is the user-facing overview.

## Five-minute orientation

- **What it does:** helps a building project team write a BIM Execution Plan (BEP). The plan has 11 sections following the Penn State / NBIMS-US procedure, applies US National CAD Standard (NCS) naming, and adds agency rules (USACE, GSA, VA).
- **Front ends, one file format:** a web app (`app/index.html`), a Python CLI (`skills/bep-builder-cli/scripts/bep.py`) and Claude skills (`skills/*/`) all work on the same plan JSON. An MCP server (`servers/bep_mcp/`) gives Claude the CLI's operations as tools.
- **Almost no build, almost no dependencies:** the app is one HTML file; the only build step is a small script that wraps it for GitHub Pages. The CLI is Python standard library, plus openpyxl and defusedxml for spreadsheets. Node is only needed to run some tests (and the run skill below). A dev container sets all of this up in Codespaces.
- **Trying a change in the real app:** `.claude/skills/run-bep-builder/` drives the web app in headless Chromium and the MCP server over stdio. It is a project skill for sessions in this repository, not one of the installable `skills/*`. See [the layout](reference.md#repository-layout) and [how to use it](how-to.md#smoke-test-a-change-in-the-real-app).
- **The one rule that trips people up:** the app re-implements the Python logic in JavaScript. Most behaviour changes have to be made in both languages, and some modules are copied between skills. See [Logic that exists twice](reference.md#logic-that-exists-twice).
- **Checking your work:** `python tests/test_bep.py` runs all 20 tests, `python tests/test_mcp.py` runs the MCP server's 11, and `python tests/test_mcp_team.py` runs the team server's 21. Install Node, openpyxl and `mcp`, or some checks are skipped quietly. CI runs the same suite on Linux and Windows.
- **Deployment:** merging a change to `app/` (or `tools/build_pages.py`) on `master` publishes it to <https://tannerpresscorp.github.io/bep-builder/>.
- **Licensing:** never add NCS text to the repository (see [Licensing](architecture.md#licensing)).

## Background on the domain

You don't need to know BIM to work on the code, but these official pages explain the standards it implements. They are links only, not quotations; some of the standards are paid publications.

| Topic | Source |
|---|---|
| US National CAD Standard (NCS) V7: layer guidelines, Uniform Drawing System, plotting and BIM guidelines | <https://www.nationalcadstandard.org/> · [contents](https://www.nationalcadstandard.org/ncs7/content.php) |
| ISO 13567 (CAD layer organization), parts 1 and 2 | [Part 1](https://committee.iso.org/standard/70181.html) · [Part 2](https://committee.iso.org/standard/70182.html). Part 3 (ISO/TR 13567-3) was withdrawn in 2015. |
| National BIM Standard – United States (NBIMS-US) V4, including its BEP module | <https://www.nibs.org/nbims/v4> |
| Penn State BIM Project Execution Planning Guide and BIM uses | <https://bim.psu.edu/> · [downloads](https://bim.psu.edu/downloads/) · [BIM uses](https://bim.psu.edu/uses/) |
| USACE A/E/C Graphics Standard, ERDC/ITL SR-23-1, Release 2.2 (PDF) | <https://www.wbdg.org/FFC/AECCAD/ERDC_ITL_SR_23_1_2023.pdf> |
| Mermaid flowcharts (used for the process map) | [Syntax](https://mermaid.js.org/syntax/flowchart.html) · [How GitHub renders them](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams) |
| GitHub Pages with a custom Actions workflow | <https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages> |
| openpyxl | <https://openpyxl.readthedocs.io/en/stable/> |
