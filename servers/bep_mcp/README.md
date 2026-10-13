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

The server currently provides these read-only tools. Write tools come in the next step of the [delivery plan](../../docs/design/mcp-server.md#6-delivery-plan).

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

Data tools return JSON, both as text and as `structuredContent`. Document tools (map, export, definition) return plain text. A failure returns an error result carrying the CLI's own message, so the model can correct its input.

## Tests

```bash
python -m pip install "mcp>=2,<3"
python tests/test_mcp.py
```

The tests check that each tool's output matches the matching CLI command, and that plan names can't leave the plans folder. They are skipped if the SDK isn't installed.
