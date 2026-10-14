# Design: `bep_mcp`, an MCP server for bep-builder

Status: **built.** All six steps of the [delivery plan](#6-delivery-plan) are done: `bep.py`'s plain functions, the server in `servers/bep_mcp/` with its read-only and write tools, its packaging and documentation, its evaluation questions, and the phase 2 resources and `start_bep` prompt. A [team server mode](#8-team-server) (HTTP, per-user tokens and grants) was added afterwards.

**Changes from the original proposal, found while building:**
- **Location:** the server lives in `servers/bep_mcp/`, not `mcp/bep_mcp/`. A top-level `mcp/` folder would shadow the `mcp` SDK package whenever Python runs from the repository root.
- **SDK:** the MCP Python SDK is now version 2, where `FastMCP` became `MCPServer` and anticipated failures raise `ToolError`. The server needs `mcp>=2,<3` and Python 3.10 or newer; the CLI still needs only 3.8.
- **Responses:** data tools return JSON both as text and as `structuredContent`, rather than a separate Markdown summary. Document tools (map, export, definition) return plain text.
- **Refactor:** `convert` and `definition` were extracted too (`convert_layers`, `layer_definition`), so their tools reuse the CLI's logic.
- **Saving documents:** writing an export or the definition file is its own tool, `bep_save_document`, instead of a `save_as` option on `bep_export_plan`. That keeps the export tool read-only, since a tool's annotations can't depend on its arguments.

## Summary

`bep_mcp` exposes the bep-builder CLI's operations as tools in the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), so Claude and other MCP clients can do the following directly, without composing shell commands:

- create and edit a BIM Execution Plan
- check CAD names
- draw the process map
- export the plan

It is a **local stdio server written in Python** (and, since the [team server](#8-team-server) was added, can also run over HTTP). It imports `bep.py` and its helper modules in-process, and it reads and writes plan JSON files inside a single folder that the user configures. Phase 1 needs one small refactor in `bep.py`: moving four commands' logic out of their `cmd_*` print-and-exit wrappers into plain functions. Nothing else in the repository changes.

*A later addition, the [team server](#8-team-server), lets the same code run over HTTP for several people.*

## 1. Requirements

### Functional

| # | Requirement | Today's CLI equivalent |
|---|---|---|
| F1 | Create a plan (blank or example, optional agency) | `init` |
| F2 | Read the whole plan or one value | `show` |
| F3 | Change one value, with the CLI's validation | `set` |
| F4 | Add or remove rows in `team`, `goals`, `exchanges`, `tech`, `deliver` and `standards.codes` | `add`, `remove` |
| F5 | Turn BIM uses on or off and fill their details | `use` |
| F6 | Set up QC rules and checks | `qc` |
| F7 | Report completion per section, and list TODOs | `status`, `validate` |
| F8 | Check NCS layer names and sheet ids, optionally under a plan's ISO 13567 profile | `check-names` |
| F9 | Suggest ISO 13567 names, and write the definition file | `convert`, `definition` |
| F10 | Produce the Level 1 process map (Mermaid or tldraw script) | `process-map` |
| F11 | Export the plan as Markdown or HTML | `export` |
| F12 | List the ids the other tools accept | `catalog` |
| F13 | List the plans available | *(new)* |

Out of scope for v1: the maps workbook round trip (`maps-workbook`, `apply-maps`). It produces a binary file for a person to edit in Excel or Numbers, which doesn't fit tool calls; agents can keep using the CLI for it. See [Revisit later](#7-revisit-later).

### Non-functional

- **Same behaviour as the CLI.** Every rule (validation, firm defaults, TODO generation) comes from `bep.py`, never re-implemented. A plan written through MCP must be byte-for-byte what the CLI would write.
- **Safe file access.** The server can only touch `*.json` plan files inside one configured folder. No path from a tool argument may escape it.
- **No data loss.** Writes are atomic (`bep.save()` already writes through a temporary file and `os.replace`). A rejected change leaves the file untouched (`test_set_refuses_sections_and_keeps_file_valid` already covers this for `set`).
- **Cross-platform.** It runs on Windows, macOS and Linux, the same as CI (Ubuntu and Windows).
- **Licensing.** Tool descriptions and responses contain no NCS text, the same rule as the rest of the repository.
- **Scale.** One user, one client and a handful of plans (each under 50 KB). Latency is dominated by the model, not the server; everything is in memory and takes under a millisecond.

### Constraints

- The CLI must stay **standard-library only**, so the MCP SDK dependency must not leak into `skills/bep-builder-cli/`.
- The repository has no package build. Each skill folder is installed on its own.
- The team is small, so prefer the least new code.

## 2. High-level design

```text
 ┌─────────────────────┐   stdio (JSON-RPC)   ┌──────────────────────────────────────┐
 │ MCP client          │ ───────────────────▶ │ bep_mcp (servers/bep_mcp/...server)  │
 │ Claude Code,        │ ◀─────────────────── │  FastMCP: tool schemas, annotations, │
 │ Claude Desktop, ... │                      │  path sandbox, error mapping         │
 └─────────────────────┘                      └───────────────┬──────────────────────┘
                                                              │ import (same process)
                                              ┌───────────────▼──────────────────────┐
                                              │ skills/bep-builder-cli/scripts/       │
                                              │  bep.py · processmap.py · iso13567.py │
                                              └───────────────┬──────────────────────┘
                                                              │ load() / save() (atomic)
                                              ┌───────────────▼──────────────────────┐
                                              │ $BEP_PLANS_DIR/*.json   (plan files) │
                                              └──────────────────────────────────────┘
```

**Where it lives:** `servers/bep_mcp/`, at the top level, beside `skills/` rather than inside it:
- `server.py`
- `pyproject.toml`, declaring the `mcp` and `bep_mcp` entry point
- `README.md`

At start-up it adds `skills/bep-builder-cli/scripts` to `sys.path`, the same way `bep.py` adds its own folder. This keeps the SDK dependency out of the skill.

**Data flow for a write tool:** client call → validate arguments against the schema → resolve the plan path in the sandbox → take the write lock → `bep.load()` → change it through a `bep.py` function → `bep.save()` → release the lock → return a short confirmation plus the new section status.

**Storage:** plan files on disk, exactly as the CLI uses them. There is no database and no cache. Each call loads the file, so edits made by the CLI or a text editor between calls are always picked up.

## 3. Deep dive

### 3.1 Tools

All tool names start with `bep_`, so they can't collide with other servers. "Plan" arguments are file names relative to `BEP_PLANS_DIR` (`clinic.json`), never absolute paths.

| Tool | Arguments | Returns | readOnly | destructive | idempotent |
|---|---|---|---|---|---|
| `bep_list_plans` | — | Plan files with project name and done/partial/empty counts | ✓ | | ✓ |
| `bep_get_catalog` | — | BIM uses, agencies, status fields, layer formats, sheet levels, QC ids | ✓ | | ✓ |
| `bep_create_plan` | `plan`, `example?`, `agency?`, `overwrite?=false` | Confirmation and status | | `overwrite=true` only | |
| `bep_get_plan` | `plan`, `path?` | The whole plan or one value (JSON) | ✓ | | ✓ |
| `bep_set_value` | `plan`, `path`, `value` | Old and new value | | | ✓ |
| `bep_add_row` | `plan`, `list`, `fields{}` | The row and its index | | | |
| `bep_remove_row` | `plan`, `list`, `index` | The removed row | | ✓ | |
| `bep_set_bim_use` | `plan`, `use_id`, `on?`, `party?`, `value?`, `flow?` | The use | | | ✓ |
| `bep_set_qc` | `plan`, `id`, `on?`, `who?`, `freq?`, `tool?` | The rule or check | | | ✓ |
| `bep_get_status` | `plan` | 11 sections with done/partial/empty, plus TODO count | ✓ | | ✓ |
| `bep_list_todos` | `plan` | TODOs grouped by section | ✓ | | ✓ |
| `bep_check_names` | `names[]`, `plan?` | Per name: kind, valid, problems | ✓ | | ✓ |
| `bep_convert_layers` | `plan`, `names[]`, `anno_element?` | Suggested ISO 13567 names and notes | ✓ | | ✓ |
| `bep_get_process_map` | `plan`, `format=mermaid\|tldraw` | Map text, plus unplaced exchanges | ✓ | | ✓ |
| `bep_export_plan` | `plan`, `format=md\|html`, `save_as?` | Document text, or the path written | `save_as` absent | | ✓ |
| `bep_get_layer_definition` | `plan` | ISO 13567-3 definition file text | ✓ | | ✓ |

Every tool sets `openWorldHint: false`, because nothing leaves the machine.

`bep_get_process_map` with `format=tldraw` returns a script for the separate tldraw MCP server's `exec` tool, the same thing the CLI produces today. The client runs it, and this server does nothing more.

**Responses.** Read tools return a short Markdown summary for the model, plus `structuredContent` (JSON) using the same fields as the CLI's data, so clients that render data don't have to parse text. `bep_get_status` is the one most agents will call after each write, so it stays compact: one line per section.

**Errors.** `bep.py` raises `ValueError` / `KeyError` / `IndexError` with messages written for people, for example `'nmae' isn't a field here. Fields: name, owner, ...`. The server returns these as tool errors (`isError: true`) unchanged. Those messages are what lets an agent correct itself. Anything unexpected is logged to **stderr** (stdout is the protocol channel) and returned as a generic "internal error" that includes the tool name.

### 3.2 Refactor needed in `bep.py`

Four commands keep their logic inside `cmd_*` functions that `print()` and `sys.exit()`:

| Command | Logic to extract |
|---|---|
| `add` | Fill the first placeholder row before appending |
| `use` | Turning on `cobie` also sets `plan["cobie"]` |
| `qc` | Checks vs rules, `--off` / `--tool` validation |
| `check-names` | Choose ISO vs NCS checker from the plan |

Move each into a plain function (`add_row(plan, list, fields)`, `set_use(plan, use_id, **kw)`, `set_qc(plan, id, **kw)`, `check_names(names, plan=None)`) that returns data and raises `ValueError`. Then make `cmd_*` a thin wrapper around it. `remove` gets the same treatment (`remove_row(plan, list, index)`), so every write tool has a plain function to call. *(Implemented as step 1 of the delivery plan.)*

That keeps the CLI and MCP behaviour identical by construction. The existing tests cover the CLI side of all four, so they guard the refactor. The other tools already map onto pure functions: `load`, `save`, `get_path`, `set_path`, `section_status`, `build_doc`, `collect_todos`, `to_markdown`, `to_html`, `processmap.build` and `iso13567.*`.

### 3.3 Path sandbox

1. `BEP_PLANS_DIR` comes from the environment and is required. The server refuses to start without it, so it never defaults to the client's working folder.
2. A `plan` argument must match `^[A-Za-z0-9][A-Za-z0-9._ -]{0,100}\.json$`. That rules out separators and `..`.
3. Resolve it as `realpath(BEP_PLANS_DIR / plan)` and require the result to sit inside `realpath(BEP_PLANS_DIR)`. This catches a symlink planted inside the folder that points outside it.
4. `bep_export_plan`'s `save_as` and the definition file follow the same rules, with `.md`, `.html` or `.txt` instead of `.json`.

`bep.save()` already writes through symlinks to the real file and refuses read-only plans. Step 3 runs before it, so a symlink can never redirect a write outside the folder.

### 3.4 Concurrency

There is one stdio client, but it may send overlapping requests, and the SDK doesn't promise to run them one at a time. Each write tool therefore holds a process-wide `threading.Lock` around load → change → save, so the server never races itself. It can race a person editing the same file with the CLI or an editor. In that case the last write wins, just as when two CLI runs overlap today, and the atomic save means the file is never half-written. This is accepted for v1 (see [Trade-offs](#5-trade-offs)).

### 3.5 Resources and prompts (optional, phase 2)

- Resource `bep://plans/{plan}`: the plan JSON (read-only), for clients that attach context instead of calling tools.
- Resource `bep://catalog`: the same data as `bep_get_catalog`.
- Prompt `start_bep`: walks through the skill's interview order, asking for project, team, goals and uses, then filling TODOs. It reuses the workflow already written in `skills/bep-builder-cli/SKILL.md`.

## 4. Reliability, testing and operations

**Testing**
- **Unit tests** in `tests/test_mcp.py`. They are skipped, like the Node and openpyxl tests, when the `mcp` package isn't installed. Each tool is called through the SDK's in-memory client session against a temporary `BEP_PLANS_DIR`, with no subprocess and no network.
  - **Parity:** every write tool must produce the same file as the matching CLI command.
  - **Sandbox:** `../x.json`, absolute paths, an escaping symlink and a bad extension are all rejected.
  - **Errors:** a bad field, a bad index and a read-only plan each return the CLI's message.
- **Evaluations:** ten read-only questions in `servers/bep_mcp/evals.xml`, as the mcp-builder process requires. They run against a copy of `examples/` and check that an agent can answer from the tools. Example: "Which BIM use in the example plan has no exchange feeding it?"
- **CI:** add `pip install mcp` to `ci.yml` so `test_mcp.py` runs on Ubuntu and Windows. The Windows UTF-8 fix from #24 already covers the server's output.

**Operations**
- **Logging:** to stderr only, at INFO level for one line per tool call (the tool, the plan and ok/error), and never the plan's contents.
- **Monitoring:** none needed for a local process. The client shows tool errors.
- **Installation:** `pip install -e servers/bep_mcp`, then register it with a client:

```bash
claude mcp add bep -e BEP_PLANS_DIR="$HOME/plans" -- bep_mcp
```

## 5. Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Language | **Python** | TypeScript (mcp-builder's default) | All the logic is in Python. TypeScript would mean a third implementation, after Python and the app's JavaScript, and the repository already struggles to keep two in step. |
| How to call the logic | **Import in-process** | Run `bep.py` as a subprocess per call | A subprocess would need no refactor, but costs ~50 ms per call, means parsing human-oriented stdout, and gives poorer errors. Importing gives structured data and exact messages; its cost is the small refactor in §3.2, which also improves the CLI. |
| Transport | **stdio**, plus streamable HTTP for a team server | HTTP only | One local user needs no auth or network exposure, so stdio stays the default. HTTP is added as a separate mode (`--http`) for a shared team server; see [Team server](#8-team-server). |
| Where it lives | **`servers/bep_mcp/`** | Inside `skills/bep-builder-cli/` | Keeps the stdlib-only promise of the CLI skill, and the skill folders independently installable. |
| Plan addressing | **File name in one folder** | Absolute paths | The sandbox removes a whole class of path-traversal bugs. Users with plans in several folders run one server per folder. |
| Tool granularity | **One tool per operation (16)** | One generic `bep_run(command, args)` | Typed schemas and per-tool annotations let clients ask before destructive calls (`bep_remove_row`, `bep_create_plan` with overwrite) and let the model pick tools by description. |
| Concurrent edits | **Write lock, plus an optional `if_version` check** | Last write wins only; a version field in the plan file | The lock stops the server racing itself. For several people, reads return a `version` (a hash of the file) and writes may pass it back as `if_version`; omitting it keeps last-write-wins. The hash is computed, not stored, so the plan format is unchanged. See [Team server](#8-team-server). |
| Maps workbook | **Left out of v1** | Return the `.xlsx` as a binary resource | The round trip needs a person in Excel or Numbers. The CLI already handles it well. |

## 6. Delivery plan

1. **Refactor** `add`, `use`, `qc` and `check-names` in `bep.py` into plain functions (§3.2). Existing tests must pass unchanged. Size: S. *(Done.)*
2. **Server skeleton:** `servers/bep_mcp/` with the sandbox, error mapping and the 10 read-only tools, plus `test_mcp.py` (run in CI). Size: M. *(Done.)*
3. **Write tools** (`create`, `set`, `add`, `remove`, `use`, `qc`, `save_document`), plus the parity tests and a concurrency test for the write lock. Size: M. *(Done.)*
4. **Packaging and CI:** add `pyproject.toml`, put `pip install mcp` in CI, and document it in `README.md` and `docs/onboarding/`. Size: S. *(Done.)*
5. **Evaluations:** `evals.xml` with 10 questions, then fix any tool descriptions they show to be unclear. Size: M. *(Done. A first run answered all 10; it led to clearer descriptions for `bep_get_plan`, `bep_get_process_map`, `bep_convert_layers` and `bep_set_qc`.)*
6. *(Phase 2)* Resources and the `start_bep` prompt. Size: S. *(Done. The prompt takes an optional `agency`, and resumes an existing plan from its first unfinished section.)*

Each step is its own PR, and none changes the plan format, the web app or the skills' instructions.

## 7. Revisit later

- **OAuth for the team server,** if static per-user tokens stop being enough (see [Team server](#8-team-server)).
- **The web app's shared store.** Plans saved in the Claude artifact (`bep/plan`) are invisible to this server. Exposing them would mean reading and writing that store through the artifact data API rather than files. That decision depends on where the team keeps its plans of record.
- **Richer tool results** suggested by the first evaluation run: give each `bep_list_todos` item the dotted path it refers to (e.g. `uses.4d.party`), and offer the process map as JSON (phases, use ids, exchange targets) as well as Mermaid.
- **The maps workbook round trip,** once clients handle binary resources and file uploads reliably.
- **Hosting skills next to MCP.** If the skills' scripts gain more shared code, consider one installable package (`bep_builder`) that the CLI, the skills and the MCP server all import. That would also remove the copied modules (`iso13567.py`, `read_tables.py`).

## 8. Team server

Status: **built.** `bep_mcp --http` serves the same tools, resources and prompt to several people over streamable HTTP. The stdio server is unchanged apart from two additive things (a `version` in results and an optional `if_version` argument), and the plan file format is unchanged.

### 8.1 Goal and decisions

Several people should share one folder of BIM Execution Plans through Claude, from Claude Code and from claude.ai. Decisions taken with the project owner:

| Decision | Chosen | Alternatives considered | Why |
|---|---|---|---|
| Hosting | The server binds `127.0.0.1`; an HTTPS reverse proxy (Caddy, nginx, Cloudflare Tunnel) gives it a public address | Terminate TLS inside the server; bind `0.0.0.0` | Certificates, renewal and rate limiting are what proxies already do well. claude.ai connectors call from Anthropic's network, so the address must be public; localhost-only would not work for them. |
| Clients | Claude Code and claude.ai custom connectors | Claude Code only | Both can send a fixed `Authorization` request header (`--header` in Claude Code; the "Request headers" field of a custom connector). |
| Sign-in | **Per-user static bearer tokens**; the config stores only SHA-256 hashes | OAuth now; one shared token; mTLS | OAuth means running or delegating an authorization server, which is more than a small team needs today. One shared token can't say who did what or limit anyone. The SDK's token-verifier hook means OAuth can be added later without changing the tools: only the verifier changes. |
| Authorization | Roles `viewer` / `editor` granted per user by file-name pattern | Per-folder grants; everyone sees everything | The server has one flat folder, so the unit is the plan file name. Patterns (`clinic*.json`) keep the config short. |
| Plans of record | **Two stores, on purpose.** The team server's folder holds the plans of record for Claude, CLI and MCP work; the Claude artifact (`bep/plan`) stays a quick browser editor | One store (make the server read the artifact store, or retire the app's sharing) | The artifact store needs the artifact data API and isn't reachable from a server process; the folder works with the CLI and backups. Both use the same JSON format, but no import step exists yet (the app exports only Markdown and HTML; the server has no tool that accepts plan JSON), so moving a plan needs file access to the server's folder. Cost: they don't sync, and the docs say which is the record. |
| Concurrency | **One server process.** A lock serialises writes; reads return `version` (first 16 hex of the SHA-256 of the file's bytes); writes take an optional `if_version`, and a mismatch is refused with nothing written | A cross-process file lock; a version field stored in the plan | Static tokens and a small team need one process, not a cluster. `if_version` also catches edits made with the CLI or an editor, which a lock can't. A stored version would change the plan format that the app and CLI share. A cross-process lock would need `fcntl` on POSIX and `msvcrt` on Windows, which CI covers, but a lock nobody needs is code to maintain. |
| Transport safety | DNS-rebinding protection on, with `allowed_hosts` and `allowed_origins` from the config (plus localhost) | SDK default | The SDK's default for a `127.0.0.1` bind allows only localhost `Host` values, so behind a proxy the public host name would be refused (421). Bad `Host` gets 421; bad `Origin` gets 403. |
| Audit | One log line per tool, resource and prompt call with the user and the outcome | Per-write history in the folder | stderr is enough for a small team and adds no files beside the plans. Tokens are never logged. |

### 8.2 How it works

Started with `bep_mcp --http --config PATH` (or `BEP_TEAM_CONFIG`), optional `--host` (default 127.0.0.1) and `--port` (default 8765); `bep_mcp --new-token` makes a token and its hash. Setup steps are in the [server README](../../servers/bep_mcp/README.md#team-server).

```text
 Claude Code / claude.ai ──HTTPS──▶ proxy ──HTTP, 127.0.0.1──▶ bep_mcp --http (one uvicorn process)
        Authorization: Bearer <token>            │
                                                 ├─ token verifier: sha256(token) vs every user's hash (constant time)
                                                 ├─ Host / Origin checks
                                                 └─ tools / resources / prompt ──▶ the same functions as stdio ──▶ plans folder
```

- **Mode is fixed when the server is built.** `create_server(plans_dir, team=None)` is the stdio server: no checks. `create_server(plans_dir, team=config)` is team mode: every call that touches a plan needs a signed-in user, and if the request somehow has none, it is refused with `Sign-in required.` Team mode can never fall back to full access.
- **Token to user.** `TeamTokenVerifier` hashes the presented token and compares it with every user's hash using `hmac.compare_digest`, with no early exit, and never raises (an error means "not a valid token"). The SDK turns a miss into 401 with a `WWW-Authenticate` header. The user's name travels with the request and tools read it from the SDK's context, so it is per request even on a long-lived connection.
- **Where `public_url` is used.** The SDK requires auth settings next to a verifier. `public_url` fills the advertised issuer and resource addresses; the server never contacts them. A token carries no audience, so audience validation is off.
- **One rule on every surface.** Each tool, the `bep://plans/{plan}` resource and the `start_bep` prompt run the same three steps in order: check the name's format, check the user's role, and only then touch the file. No answer to a user without a role depends on whether the file exists: a missing plan and a plan they can't see give the same text, apart from the plan name they typed. `bep_list_plans` shows only plans the user can use, with their `role`, and omits `plans_dir`; in team mode no response names the server's folder.
- **Roles.** `viewer` for reads (`bep_get_plan`, `bep_get_status`, `bep_list_todos`, `bep_convert_layers`, `bep_get_process_map`, `bep_export_plan`, `bep_get_layer_definition`, `bep_check_names` with a plan, the resource). `editor` for writes (`bep_create_plan`, `bep_set_value`, `bep_add_row`, `bep_remove_row`, `bep_set_bim_use`, `bep_set_qc`, `bep_save_document`) and for `start_bep`, since it ends by creating or filling a plan. `bep_save_document` needs editor on the source plan and on the plan the output is named after, so a document can't be written over another plan's name. `bep_get_catalog` and `bep://catalog` need only a valid token. The highest matching grant wins.
- **Links inside the folder.** The role for `alias.json` is lowered to the role for the file it really is, so a link can't open a plan its owner has no grant on, and `bep_list_plans` leaves such links out.
- **Config safety.** The config holds the token hashes, so the server refuses to start if the file sits in the plans folder. It is read once at start-up: revoke a token by removing the user's entry and restarting.
- **Versions.** The server reads a plan's bytes once and derives both the plan and its version from them, so the version always describes what was read. Writes re-check it under the lock, right after loading.

### 8.3 What is not covered

- **No OAuth.** Anyone with a token acts as its user until the config changes and the server restarts. Tokens are bearer secrets, so they need the same care as a password; give each person their own so one can be revoked alone.
- **claude.ai with a static header.** The connector form's request-header field is what this design relies on. It is unverified against a live claude.ai connector (the server advertises OAuth metadata for the SDK's sake; a client that ignores it and sends the header is what works).
- **Several processes.** Not supported. The in-process lock and the "one process saw every write" assumption behind `if_version` would not hold. Run exactly one.
- **Syncing with the web app's store.** The two stores don't sync (see Plans of record above).
- **Rate limiting and TLS** belong to the proxy.
