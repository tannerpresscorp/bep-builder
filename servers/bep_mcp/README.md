# bep_mcp

An [MCP](https://modelcontextprotocol.io/) server that gives Claude and other MCP clients tools for working with bep-builder BIM Execution Plans. Design: [docs/design/mcp-server.md](../../docs/design/mcp-server.md).

It runs locally over stdio and imports `skills/bep-builder-cli/scripts/bep.py`, so every rule (validation, defaults, TODOs) is the CLI's own. Plans are JSON files in one folder, `BEP_PLANS_DIR`. Tools name a plan by file name (`clinic.json`) and can't reach anything outside that folder.

## Install and connect

It needs Python 3.10 or newer. From the repository root:

```bash
python -m pip install -e servers/bep_mcp
claude mcp add bep -e BEP_PLANS_DIR="$HOME/plans" -- bep_mcp
```

Install it editable (`-e`) from inside the repository: the server finds `bep.py` relative to its own source. To use a `bep.py` somewhere else, set `BEP_CLI_DIR` to its folder.

Without installing, you can also run `python -m bep_mcp` with `PYTHONPATH=servers/bep_mcp`.

## Tools

**Read-only:**

| Tool | What it returns |
|---|---|
| `bep_list_plans` | The plans in the folder, with project name, sections done and TODO count |
| `bep_get_catalog` | Every id the other tools accept |
| `bep_get_plan` | The whole plan, or one value by dotted path |
| `bep_get_status` | Completion of the 11 sections, and the TODO count |
| `bep_list_todos` | What the plan is missing, by section |
| `bep_check_names` | NCS layer and sheet name checks (optionally with the plan's ISO 13567 profile) |
| `bep_convert_layers` | Suggested ISO 13567 layer names |
| `bep_get_process_map` | The Level 1 process map, as Mermaid or a tldraw script |
| `bep_export_plan` | The finished plan, as Markdown or HTML |
| `bep_get_layer_definition` | The ISO 13567-3 layer naming definition file |

**Write.** Each one writes exactly what the matching CLI command would, and returns the plan's new status. Tools marked *destructive* can discard data, so clients can ask before running them.

| Tool | Does | CLI equivalent |
|---|---|---|
| `bep_create_plan` *(destructive with `overwrite`)* | Create a blank or example plan | `init` |
| `bep_set_value` | Set one value by dotted path | `set` |
| `bep_add_row` | Add a row to a list | `add` |
| `bep_remove_row` *(destructive)* | Remove a row by index | `remove` |
| `bep_set_bim_use` | Turn a BIM use on or off and fill in its details | `use` |
| `bep_set_qc` | Configure a QC check or model rule | `qc` |
| `bep_save_document` *(destructive: replaces a file of the same name)* | Write the plan (Markdown or HTML) or the layer definition into the plans folder | `export -o`, `definition -o` |

Writes run one at a time under a lock, so overlapping requests can't overwrite each other's edits. Saves are atomic, as in the CLI.

Data tools return JSON, both as text and as `structuredContent`. Document tools (map, export, definition) return plain text. A failure returns an error result carrying the CLI's own message, so the model can correct its input.

## Evaluations

`evals/evals.xml` holds 10 questions a model should be able to answer using only this server's read-only tools, with `BEP_PLANS_DIR` set to `evals/plans`. That folder has two example plans: `clinic.json`, which is complete, and `barracks.json`, a USACE plan that has just been started. The questions test whether the tool descriptions are clear enough for a model to find the right tool and arguments, for example which dotted path to read or how to read the process map. To run them, connect any MCP client to the server with that folder, ask each question, and compare the final answer with `<answer>`. `test_eval_answers_match_the_fixtures` keeps the answers true as the code changes.

## Tests

```bash
python -m pip install "mcp>=2,<3"
python tests/test_mcp.py
```

The tests check that each tool's output matches the matching CLI command, and that plan names can't leave the plans folder. They are skipped if the SDK isn't installed.
