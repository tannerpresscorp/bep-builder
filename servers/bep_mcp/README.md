# bep_mcp

An [MCP](https://modelcontextprotocol.io/) server that gives Claude and other MCP clients tools for working with bep-builder BIM Execution Plans. Design: [docs/design/mcp-server.md](../../docs/design/mcp-server.md).

By default it runs locally over stdio (one person). With `--http` it runs as a [team server](#team-server) that several people share. Either way it imports `skills/bep-builder-cli/scripts/bep.py`, so every rule (validation, defaults, TODOs) is the CLI's own. Plans are JSON files in one folder, `BEP_PLANS_DIR`. Tools name a plan by file name (`clinic.json`) and can't reach anything outside that folder.

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

`bep_get_plan`, `bep_get_status`, every write tool (except `bep_save_document`, which writes a document rather than the plan) and each entry of `bep_list_plans` return a `version`: a short fingerprint of the plan file. The write tools accept an optional `if_version`. Pass the version from your last read and the write is refused, with nothing changed, if someone else changed the plan since: `'clinic.json' changed since you read it (now version …). Read it again and retry.` Leave it out and the last write wins, as before. The plan file format has no version field; the version is computed from the file.

Data tools return JSON, both as text and as `structuredContent`. Document tools (map, export, definition) return plain text. A failure returns an error result carrying the CLI's own message, so the model can correct its input.

## Resources and prompt

For clients that attach context rather than call tools:

| Resource | Contents |
|---|---|
| `bep://catalog` | The same JSON as `bep_get_catalog` |
| `bep://plans/{plan}` | One plan, e.g. `bep://plans/clinic.json`: the same JSON as `bep_get_plan` without a path. Read-only, with the same name rules as the tools. |

The **`start_bep`** prompt (arguments `plan`, default `plan.json`, and optional `agency`) asks the model to interview you section by section, in plan order, and save each answer with the tools. Anything you don't say stays a TODO. If the plan already exists, it picks up from the first section that isn't done. In Claude Code it appears as `/mcp__bep__start_bep`.

## Team server

The same server can run for several people at once over streamable HTTP. They share one folder of plan files (the *plans of record* for work done through Claude, the CLI and MCP), each signs in with their own token, and each can be given read-only or edit access to some plans and none to others. Design and the reasons for each decision: [docs/design/mcp-server.md](../../docs/design/mcp-server.md#team-server).

### 1. Make tokens

Each person needs a token. Run this once per person:

```bash
bep_mcp --new-token
```

It prints a random token and its SHA-256. Give the person the **token** (once, over a private channel). Put only the **hash** in the config file; the server never stores or logs tokens.

### 2. Write the config

A JSON file **outside the repository and outside the plans folder** (the server refuses to start if the config is inside `BEP_PLANS_DIR`, because the tools could read and change it). Keep it readable only by the account that runs the server.

```json
{
  "public_url": "https://bep.example.com",
  "allowed_hosts": ["bep.example.com"],
  "allowed_origins": ["https://bep.example.com", "https://claude.ai"],
  "users": {
    "alice": {"token_sha256": "<64 hex characters from --new-token>", "grants": {"*": "editor"}},
    "bob":   {"token_sha256": "<64 hex characters>",
              "grants": {"clinic*.json": "viewer", "barracks.json": "editor"}}
  }
}
```

| Key | Meaning |
|---|---|
| `public_url` | Required. The address people reach the server at, without `/mcp`. |
| `allowed_hosts` | `Host` header values accepted, as the proxy forwards them (the public host name, no port for the default ports). Any other `Host` gets 421. `127.0.0.1:*` and `localhost:*` are always accepted. Default: none besides localhost. |
| `allowed_origins` | `Origin` header values accepted. Any other `Origin` gets 403; a request with no `Origin` is fine. Localhost origins are always accepted. |
| `users` | Required, at least one. Per user: `token_sha256` (64 hex characters; each user needs their own) and `grants`. |

**Grants** map a plan file name pattern to `viewer` or `editor`. Patterns use `*` and `?` and ignore case; if several match, the highest role wins; a plan with no matching pattern doesn't exist as far as that user can tell.

| Role | Can |
|---|---|
| `viewer` | List, read, check, export and draw the plan; read `bep://plans/{plan}`. |
| `editor` | Everything a viewer can, plus create (including overwrite), change and remove rows in the plan, and the `start_bep` prompt. `bep_save_document` also needs `editor` on the plan the document is named after: `clinic-bep.md` counts as `clinic-bep.json`. |

An alias is no way round a grant: a link inside the folder (`alias.json` pointing to `secret.json`) gets the lower of the roles for the two names. Someone without a grant is told `You don't have access to a plan named 'x.json'.` whether the plan exists or not; a viewer who tries to write is told `You can view 'x.json' but not change it.` `bep_get_catalog` and `bep://catalog` need only a valid token. In team mode, `bep_list_plans` shows only plans the person can use (with their `role`) and leaves out the folder path, and no response or error contains the server's folder path.

The config is read once, when the server starts. To **add** someone, add their entry; to **revoke a token or change a grant**, remove or edit the user's entry (removing the hash revokes the token) and **restart the server**.

### 3. Run it

```bash
export BEP_PLANS_DIR=/srv/bep/plans
bep_mcp --http --config /etc/bep/team.json            # 127.0.0.1:8765, endpoint /mcp
bep_mcp --http --config /etc/bep/team.json --port 9000
```

`--config` can also come from `BEP_TEAM_CONFIG`. `--host` defaults to `127.0.0.1`; keep it. The server speaks plain HTTP, so put an HTTPS reverse proxy in front and let only the proxy reach the port. With Caddy, which gets a certificate by itself:

```text
bep.example.com { reverse_proxy 127.0.0.1:8765 }
```

nginx or a Cloudflare Tunnel work the same way. The proxy must pass the `Authorization` header through, and `public_url` and `allowed_hosts` must name the host people use.

**Run exactly one server process** (it starts uvicorn with one worker; don't start several copies or put a process pool in front of it). Edits are serialised by a lock inside the process, and `if_version` relies on the same process seeing every write that goes through MCP. If you run it under systemd or a container, run one instance. Edits made outside the server (the CLI, an editor) are caught by `if_version` too, because the version is read from the file each time.

Every tool, resource and prompt call writes one line to stderr, for example `user=bob kind=tool name=bep_set_value plan=barracks.json ok`, with `denied` or `error: ...` instead of `ok` when it fails. Tokens are never logged.

### 4. Connect

**Claude Code** (each person, with their own token):

```bash
claude mcp add --transport http bep https://bep.example.com/mcp --header "Authorization: Bearer <token>"
```

**claude.ai:** Customize > Connectors > Add custom connector. Enter the URL `https://bep.example.com/mcp`, add the request header `Authorization: Bearer <token>`, and choose "No sign in" as the authentication. claude.ai calls the server from Anthropic's network, so the address must be reachable from the public internet (a tunnel such as Cloudflare Tunnel is enough; `127.0.0.1` or a private network address is not). The request-header option is the only way this server accepts claude.ai today; there is no OAuth sign-in yet.

### Where plans live

There are two stores, on purpose:

- **The team server's folder** holds the plans of record for work done through Claude, the CLI and MCP. It has per-person access, `if_version` checks and a file you can back up or put under version control.
- **The Claude artifact** (the web app's shared `bep/plan`) is a quick editor in the browser. This server can't see it.

Plans move between the two as JSON, because both use the same format (`bep.py` also reads the app's stored document, which wraps the plan as `{"plan": {...}}`). The app has no JSON import or export button; it downloads Markdown and HTML only. So the move goes through Claude: ask Claude, in a session that can read the artifact's shared data, to save the artifact's plan as a file in the plans folder, or to write a plan file's JSON back into the artifact. Don't edit the same plan in both places at once; the last one saved wins, and the two don't sync.

### Team server tests

```bash
python tests/test_mcp_team.py
```

These run the HTTP app in-process, with no network. They check sign-in (no or wrong token gets 401), Host and Origin checks, every tool, resource and prompt against the role it needs, that a missing and an ungranted plan are indistinguishable, versions, the audit log, and the command line. A test fails if a tool, resource or prompt is added without an entry saying what access it needs. They are skipped if the SDK isn't installed.

## Evaluations

`evals/evals.xml` holds 10 questions a model should be able to answer using only this server's read-only tools, with `BEP_PLANS_DIR` set to `evals/plans`. That folder has two example plans: `clinic.json`, which is complete, and `barracks.json`, a USACE plan that has just been started. The questions test whether the tool descriptions are clear enough for a model to find the right tool and arguments, for example which dotted path to read or how to read the process map. To run them, connect any MCP client to the server with that folder, ask each question, and compare the final answer with `<answer>`. `test_eval_answers_match_the_fixtures` keeps the answers true as the code changes.

## Tests

```bash
python -m pip install "mcp>=2,<3"
python tests/test_mcp.py
```

The tests check that each tool's output matches the matching CLI command, and that plan names can't leave the plans folder. They are skipped if the SDK isn't installed.
