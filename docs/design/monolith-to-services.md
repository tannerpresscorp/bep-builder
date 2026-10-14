# Design: moving bep-builder from one codebase to services

Status: **proposal.** Nothing here is built. It sits next to the [MCP server design](mcp-server.md), whose [team server](mcp-server.md#8-team-server) this plan builds on.

## Summary

bep-builder is small. It has about 4,600 lines across `bep.py` and its helper modules, the MCP server and the single-file web app. What gets deployed today is static: GitHub Pages and a Claude artifact. The team server is merged but not deployed, and there are no traffic, load or uptime figures. **A split into services is not needed for scale.** This plan is worth following only to the extent that it fixes one of two real problems:

- **(A) The plan logic exists twice.** The app re-implements `bep.py`'s document model, completion rules, name checker, ISO 13567 profile and process map in JavaScript. Every rule change is made twice, and only parity tests keep the copies together.
- **(B) Two plan stores that don't meet.** The shared artifact's `bep/plan` document and the team server's `BEP_PLANS_DIR` folder hold the same plan format, but nothing syncs them and there is no import step.

The plan is a strangler migration in four phases. Each phase states which problem it fixes, the test that proves nothing changed, and how to undo it.

- **The team server is the first service.** It is already an HTTP front end over `bep.py`, with sign-in, per-plan grants and optimistic concurrency (`version` and `if_version`).
- **Phases 1 and 2 fix (B).**
- **Phase 3 fixes (A) only if the project decides the app may depend on a running service** ([decision needed](#5-the-decision-this-plan-cannot-make)). Running `bep.py` in the browser with Pyodide fixes (A) without a service and may be the better answer; see [trade-offs](#6-trade-offs).
- **Splitting `bep.py` itself into several services is under [revisit later](#8-revisit-later).** Nothing today justifies it.

## 1. Requirements

### Functional

- One plan can be opened, edited and exported from the web app, the CLI, the skills and MCP clients, as today.
- A plan made in one store can be moved to the other without hand-editing JSON (fixes B).
- A rule changed once changes everywhere it is enforced (fixes A, in phase 3 or the Pyodide alternative).

### Non-functional

- No new availability promise. The service has no SLO, and offline or local use must keep working wherever it does today.
- Every phase can be shipped on its own and rolled back without data loss.
- Behaviour is identical before and after each step. The parity tests named in each phase decide this, not review.

### Constraints (every phase must satisfy them)

| Constraint | Source | What it rules out |
|---|---|---|
| Skills install on their own; the CLI is standard-library Python 3.8. | CLAUDE.md, `skills/*/` | A service can wrap `bep.py` but never replace it. No skill or CLI command may come to need a running service. |
| The app has no build step and runs on Pages and as an artifact, with a local-only fallback. | `app/index.html`, `tools/build_pages.py` | A phase where the app calls a service must keep local mode working, unless [§5](#5-the-decision-this-plan-cannot-make) is decided otherwise. |
| The plan JSON contract doesn't change, and services add no fields to it. | CLAUDE.md, `blank_plan()` / `normalize()` | Storing service metadata (owner, version, timestamps) inside the plan. That metadata lives beside the plan, as `version` does today. |
| The team server is one process; `WRITE_LOCK` is an in-process `threading.Lock`. | `server.py` (`WRITE_LOCK`, `_edit`) | Running more than one instance until writes are made safe across processes ([§4.4](#44-concurrency-beyond-one-process)). |
| Parity is proven by tests: `test_app_matches_cli`, `test_examples_in_sync`, and `tests/test_mcp.py` comparing every tool with the CLI byte for byte. | `tests/` | Moving logic without a test that compares the old and new path. |
| No NCS text in the repository. | CLAUDE.md, licensing | Seeding a service or its fixtures with licensed reference material. |

## 2. Where the seams already are

`bep.py`'s section markers already divide it into parts that could become modules or services. The table maps each seam to who uses it today.

| Seam in `bep.py` | Main functions | Used by | Notes |
|---|---|---|---|
| Reference data | agencies, BIM uses, QC rules | everything | Read-only data. Duplicated in the app. |
| Plan model | `blank_plan`, `example_plan`, `normalize`, `load`/`loads`, `save`, `get_path`/`set_path` | CLI, MCP | `loads()` unwraps the artifact's `{"plan": ...}` form. |
| Completion | `section_status` | CLI, MCP | The app's `status()` is a copy. |
| Document model | `build_doc`, `collect_todos`, `to_markdown`, `to_html` | CLI, MCP | The app's `buildDoc`/`docToMd`/`docToHtml` are copies. |
| NCS name checker | `check_layer`, `check_sheet` | CLI, MCP | Also copied to `check_names.py` and the app. |
| ISO 13567 (module `iso13567.py`) | check, convert, definition | CLI, MCP | Copied between two skills and the app. |
| Process map (module `processmap.py`) | `build`, Mermaid and tldraw output | CLI, MCP | The app's `buildMap` is a copy. |
| Plan operations | `add_row`, `remove_row`, `set_use`, `set_qc`, `check_names`, `convert_layers`, `layer_definition` | CLI, MCP | Already plain functions that return data and raise `ValueError`. |
| Maps workbook (module `mapsbook.py`) | `maps-workbook`, `apply-maps` | CLI only | The only part that needs `openpyxl`, so it separates naturally. |

Every seam the app duplicates is a pure function of the plan. That is what makes problem (A) solvable: the app needs the *results* of these functions, not their code.

## 3. Target design

```text
        ┌──────────────┐  ┌───────────┐  ┌────────────┐
        │ web app      │  │ CLI/skills│  │ MCP client │
        │ (Pages or    │  │ (bep.py,  │  │ (Claude    │
        │  artifact)   │  │  offline) │  │  Code/.ai) │
        └──────┬───────┘  └─────┬─────┘  └─────┬──────┘
   JSON API +  │ local mode:    │ imports      │ MCP over HTTP
   CORS, or    │ JS or Pyodide  │              │
   mcp capab.  ▼                ▼              ▼
        ┌────────────────────────────────────────────┐
        │ plan service = the team server process     │
        │  /mcp  (exists)    /api/plans/... (phase 1)│
        │  sign-in, grants, version / if_version     │
        │        imports bep.py (one rule set)       │
        └───────────────────┬────────────────────────┘
                            ▼
                 BEP_PLANS_DIR (*.json files)
```

There is **one service**: the existing team server, given a second, plain JSON interface next to `/mcp`. `bep.py` stays a library that the service imports and the CLI runs. The artifact's `bep/plan` store stays as it is; phase 2 adds a way to move plans between it and the service.

## 4. Phases

### Phase 0: pin the plan contract

- **Fixes:** neither problem directly. It is the precondition for a service boundary, because once the plan crosses a network the contract has to be written down, not just implied by `blank_plan()`.
- **What moves:** nothing. Add `docs/plan.schema.json`, generated from `blank_plan()` and `ROW_TEMPLATES`, and a test that `example_plan()`, `examples/example-plan.json` and a blank plan all validate against it. The schema must allow the artifact's wrapped form only at the API edge, never inside the plan.
- **Entry criteria:** none.
- **Parity test:** the new schema test, plus the existing `test_examples_in_sync`.
- **Rollback:** delete the schema and its test. No runtime code depends on them yet.

### Phase 1: a JSON API on the team server

- **Fixes:** enables (B) and (A). On its own, it fixes neither.
- **Why it's needed:** the team server speaks only streamable-HTTP MCP. A browser page's `fetch` can't use that easily. The server also sends no CORS headers: `create_http_app` checks `Origin` against `allowed_origins` but never adds `Access-Control-Allow-Origin`, so a page on `github.io` can't read its responses.
- **What moves:** a small router mounted beside `/mcp` in `create_http_app`. Every route goes through the same `check_plan_name` → `authorize` → file order, and the same bearer tokens.

  | Route | Calls | Returns |
  |---|---|---|
  | `GET /api/plans` | the `bep_list_plans` logic | names, roles, versions |
  | `GET /api/plans/{plan}` | `read_plan` | the plan, its `version` (also as `ETag`) |
  | `PATCH /api/plans/{plan}` | `_edit` + `set_path` per changed path | the new `version`; `If-Match` maps to `if_version`, and a stale value gives 412 |
  | `PUT /api/plans/{plan}` | the phase 2 import | the new `version` |
  | `GET /api/plans/{plan}/derived` | `section_status`, `build_doc` + `collect_todos`, `processmap`, `check_names` | everything the app now computes in JavaScript |

  Add CORS for `allowed_origins` only. Allow preflight with `Authorization` and `If-Match`. Never use `*`.
- **Entry criteria:** phase 0 merged. The team server has run for one team long enough to trust its sign-in and grant model.
- **Parity test:** extend `tests/test_mcp_team.py`'s access table to the routes, so a route with no rule fails, as tools do now. Add a test that each route's output equals the matching MCP tool's output byte for byte, the same way `tests/test_mcp.py` compares tools with the CLI.
- **Rollback:** unmount the router. `/mcp` is untouched, and no plan data changed format.

### Phase 2: move plans between the two stores

- **Fixes:** (B).
- **What moves:**
  1. `bep_create_plan` gains an optional `plan` argument (plan JSON). The JSON API's `PUT` uses the same function. The input goes through `loads()`, so the artifact's wrapped `{"plan": ...}` document is accepted, then `normalize()`, then `save()`.
  2. The app gets **Download plan JSON** and **Open plan JSON** buttons. Today it downloads only Markdown, HTML and the layer definition file. In artifact mode, Open writes the document with the existing whole-plan `set()`, the same path **Load example** uses.
  3. Optional: **Connect to team server** in the app, for pages on `github.io`, using the phase 1 API. In artifact mode the same link can use the `mcp` capability instead: the team server, added as a claude.ai custom connector, lets the page call `bep_get_plan`/`bep_create_plan` with the viewer's own credentials. Note that declaring `mcp` bars public sharing of that artifact.
- **Data migration:** none in bulk; plans move one at a time, on request. A moved plan's `version` changes, because `version` is a hash of the saved bytes and `save()` rewrites them. Clients must re-read before writing, which is what `if_version` already enforces.
- **Entry criteria:** phase 1 merged for item 3. Items 1 and 2 need only phase 0.
- **Parity test:** a round trip. Example plan → app download → `bep_create_plan` → `bep_get_plan` → app open must equal the example once normalized (extends `test_examples_in_sync`). Add a test that a wrapped document imports the same as a bare plan.
- **Rollback:** remove the buttons and the argument. Plans already copied stay valid, because they use the same format.

### Phase 3: the app takes derived results from the service

- **Fixes:** (A), only if the decision in [§5](#5-the-decision-this-plan-cannot-make) goes that way.
- **What moves:** when the app is connected (phase 2, item 3), it renders completion, TODOs, the document preview, the process map and name checks from `GET /api/plans/{plan}/derived` rather than from its own copies.
  - If local mode must keep working, the JavaScript copies stay as the offline path. That makes three paths to keep in step, not two.
  - Only if the app may require the service can the copies be deleted. That would delete the ports in the Document model, Completion, NCS name checker, ISO 13567 and Level 1 process map sections.
- **Entry criteria:** phase 2, and §5 decided.
- **Parity test:** while both paths exist, `test_app_matches_cli` runs the app's code in Node and compares it with Python. Extend it to compare with the `/derived` output too. Delete it only when the JavaScript copies are deleted.
- **Rollback:** a flag in the app that picks the local path, kept until the copies are deleted.

### 4.4 Concurrency beyond one process

- **Fixes:** neither problem. Do this only if one process is ever not enough.
- **The problem:** `WRITE_LOCK` serializes load → change → save inside one process. Two processes would each hold their own lock, and one write could overwrite the other.
- **The fix:** make the write itself a compare-and-swap on `version`. Under an OS file lock on the plan, re-read, check `if_version`, write the temporary file, then `os.replace` it. Use `fcntl.flock` on POSIX and `msvcrt.locking` on Windows, since CI runs both.
- **If plans move to a database:** use a conditional `UPDATE ... WHERE version = ?` instead. The `version`/`if_version` contract that clients see doesn't change.

## 5. The decision this plan cannot make

Problem (A) can be fixed by a service only if the app is allowed to depend on a running service. Today the app works:

- **on GitHub Pages**, saving in the browser;
- **as an artifact**, saving to the shared store, with no server at all.

| Choice | Effect on (A) | Cost |
|---|---|---|
| Keep local mode (default) | Not fixed. The JavaScript copies stay, and phase 3 adds a third path. | No change for users. |
| App requires the service | Fixed. The copies are deleted. | Pages and the artifact need a reachable, signed-in team server. Offline use and the zero-setup artifact go away. Someone has to run the service. |
| Run `bep.py` in the browser (Pyodide) | Fixed, with no service. | A large one-time download and a slower first load. See §6. |

This is the project's call, not the code's.

## 6. Trade-offs

- **Pyodide instead of phase 3:**
  - What it does: Pyodide runs CPython in the browser, so the app could import the real `bep.py`, `iso13567.py` and `processmap.py` and delete its JavaScript ports. It keeps working offline and on Pages, and needs no service.
  - Costs:
    - A download of several megabytes on first load.
    - A start-up delay before the first render.
    - Loading it from a CDN.
  - Not checked here:
    - The artifact allow-list includes `cdn.jsdelivr.net/npm/`, but whether Pyodide's WebAssembly and package files load inside an artifact must be tested before relying on it.
    - The app has no build step, so the Python files would be fetched at runtime or inlined by `build_pages.py`.
  - Even so, this is likely a better fix for (A) than any service.
- **One service versus several:** splitting name checking, export and the workbook into their own services would add deployment, versioning and network failure modes to pure functions that run in milliseconds. It solves no problem this repository has.
- **JSON API versus MCP only:** MCP clients already have `/mcp`. The JSON API exists only because browsers need CORS and plain HTTP. If the app only ever reaches the server through the artifact's `mcp` capability, phase 1 shrinks to the `/derived` tool.
- **Moving plans out of files:** the file store is simple, can be inspected, and is what the CLI uses. Change it only for §4.4 or for data the plan must not hold (history, audit), and keep that data beside the plan.

## 7. Reliability, testing and operations

- **Tests:** each phase's parity test is listed with the phase. The team server's rule that every surface has an access entry extends to every API route.
- **Deploy:** the service ships as the existing `bep_mcp --http` process behind an HTTPS proxy, as the [server README](../../servers/bep_mcp/README.md#team-server) describes. Pages deployment is unchanged.
- **Observability:** the existing audit line (`user=… kind=… name=… plan=… ok|denied|error`) covers API routes once they reuse `guarded`. There are no metrics today. Add request counts and latency only when there is traffic to measure.
- **Failure modes:**
  - A service outage must not lose work: the app keeps its local copy and shows that it isn't connected.
  - A stale `if_version` returns 412 and the client re-reads, as the MCP tools do today.

## 8. Revisit later

- Several service instances (§4.4) once one process is measured to be the limit.
- Separate services for export or the maps workbook, if a heavy dependency (such as `openpyxl` or a PDF renderer) should stay out of the main process.
- Plan history or audit storage beside the plan files.
- Removing the copies between skills (`iso13567.py`, `read_tables.py`) by publishing them as one shared package. This conflicts with skills installing on their own, so only if that constraint changes.
