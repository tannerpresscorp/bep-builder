---
name: bep-builder-cli
description: Build, check, and export a BIM Execution Plan (BEP) with the bundled `bep` command-line tool — create a plan file, fill it in from a conversation, see what's missing, check NCS layer and sheet names, draw the Level 1 process map (tldraw or Mermaid), and export Markdown or HTML. Uses the same plan format as the BIM Execution Plan Builder web app. Use this whenever the user wants to start, fill in, update, validate, or export a BEP / BIM project execution plan, asks what's still missing from their plan, wants a BEP from the command line or in a repo, or brings a plan exported from the BEP Builder app — even if they don't mention a CLI.
---

# BEP Builder CLI

`scripts/bep.py` builds a BIM Execution Plan as a JSON plan file, then assembles it into
a finished document. It follows the NBIMS-US / Penn State planning procedure in 11
sections, applies National CAD Standard (NCS) conventions, adds USACE / DoD overrides
when the agency is USACE, and can tag sections with ISO 9001 clause numbers.

It's plain Python (3.8+, standard library only), so it runs anywhere — this workspace,
the user's computer, or a CI job.

## Why work through the tool instead of writing the plan by hand

The plan file is the single source of truth. Every answer the user gives lands in a
known field, `status` and `validate` show exactly what's still missing, and `export`
produces the same document every time. That makes the plan easy to update next week,
easy to diff in a repo, and portable to the web app — none of which a free-written
document gives you.

## Workflow

1. **Create the plan.** `python scripts/bep.py init plan.json` (add `--agency usace` etc.
   if you already know the owner type). Use `--example` only when the user wants to see a
   sample; its values are labeled EXAMPLE and must be replaced.
   If the user already has a plan file, or one from the web app, skip this and use it.
2. **Look up ids once.** `python scripts/bep.py catalog` lists BIM use ids, agency ids,
   sheet levels, model rule ids (a0–a8, d0–d8), and check ids. Read it before filling
   uses or quality control so you don't guess ids.
3. **Fill it in from the conversation.** Ask for information a section at a time, in plan
   order, and write each answer as soon as you have it (commands below). Don't invent
   names, dates, or firms — anything the user hasn't told you stays empty and will show
   as a TODO, which is the honest state of the plan.
4. **Show progress.** Run `status` after a batch of answers so the user sees which of
   the 11 sections are done, partial, or empty.
5. **Close the gaps.** Run `validate` and ask the user about the remaining TODOs, grouped
   by section, in plain words.
6. **Draw the process map.** Once BIM uses are chosen, give the user the Level 1 process
   map for section 05 (see "Process maps" below).
7. **Export.** `export plan.json --format md -o plan.md` (or `--format html`). Send the
   file to the user. Mention how many TODOs remain if any. The Markdown export already
   embeds the process map as a Mermaid diagram in section 05.

Keep the user's plan file — they'll want to update it as the project moves.

## Commands

```bash
B="python scripts/bep.py"          # path is relative to this skill's folder

$B init plan.json [--example] [--agency private|gsa|usace|va|federal|state] [--force]
$B catalog
$B show plan.json [project.name]                  # whole plan, or one value
$B set  plan.json project.owner "City of Springfield"
$B set  plan.json project.iso yes                 # booleans accept yes/no/true/false
$B add  plan.json team role="MEP lead" org="Acme" name="Dana Ruiz" email="dana@acme.com"
$B remove plan.json team 2                        # 0-based row index
$B use  plan.json coord --party "BIM manager" --value "Fewer field conflicts" --flow "MEP uploads NWC Fri → BIM mgr runs clash → issues Tue"
$B use  plan.json energy --off
$B qc   plan.json clash --tool "Navisworks Manage" --who "BIM manager" --freq Weekly
$B qc   plan.json a3 --off                        # drop a model rule from the plan
$B status plan.json
$B validate plan.json [--strict]                  # --strict exits 1 if TODOs remain (for CI)
$B check-names A-WALL-FULL S-501 AD101 --file layers.txt
$B check-names --plan plan.json A-WALL-____-TEXT-N  # applies the plan's status field / ISO profile
$B convert plan.json G-ANNO-TTLB A-WALL-ELEV-N [--anno-element CODE]   # suggest ISO 13567 names
$B definition plan.json -o layer-definition.txt   # ISO 13567-3 layer naming system definition file
$B process-map plan.json [--format mermaid|tldraw] [-o map.js]   # Level 1 process map (section 05)
$B maps-workbook plan.json [more.json] -o maps.xlsx               # spreadsheet of uses + exchanges
$B apply-maps plan.json maps-edited.xlsx|.numbers [--project NAME] [--dry-run]
$B export plan.json --format md|html -o out.md
```

### Process maps

`process-map` turns the plan into a Level 1 process map: phase columns (Planning, Design,
Construction, Operations), one box per selected BIM use with its responsible party, and
arrows labeled with the information exchanges from section 06. Skipped phases get a grey
placeholder box so work never appears to jump from design straight to operations, and
exchanges that match no use are listed in a note rather than dropped.

- **tldraw connector available** (tools named `mcp__tldraw__*`): run
  `$B process-map plan.json --format tldraw -o map.js`, read `map.js`, and pass its full
  contents as the `code` of `mcp__tldraw__exec` with no `canvasId` (a new canvas). The user
  gets an editable diagram. Don't hand-draw the map instead — the script keeps the map
  consistent with the plan. To redraw after the plan changes, run it on a new canvas.
- **Otherwise:** `$B process-map plan.json` prints Mermaid. Show it in a ```mermaid block,
  or rely on the copy embedded in the Markdown export.

**Planning maps in a spreadsheet (Excel or Numbers on iPhone/iPad).** When the team
wants to review uses and exchanges in a spreadsheet:

1. `$B maps-workbook plan.json [other-plan.json …] -o maps.xlsx` (needs openpyxl; also install defusedxml so workbooks are read safely) builds
   the workbook — Uses, Exchanges, Summary, Keywords, Read Me — one row set per project.
   Keep a copy; it's the baseline for comparing what comes back.
2. Send it. If they'll edit on a phone or iPad, follow the `ios-numbers-spreadsheets`
   skill for the open/edit/send-back steps and for reading `.numbers` files.
3. When it comes back, show what changed (that skill's `diff_tables.py` with
   `--key "Uses=Project,BIM use" --key "Exchanges=Project,Exchange"`), then preview with
   `$B apply-maps plan.json returned-file --project "Project name" --dry-run`.
4. After the user agrees, run it without `--dry-run`, then regenerate the process map.
   `apply-maps` reads `.xlsx`, `.csv` and, with numbers-parser, `.numbers`; running it twice
   is harmless (the second run reports no changes).

An exchange's **Feeds use** chosen in the sheet is stored as the exchange's `feeds` field
and overrides keyword matching on the map; it's only stored when it differs from what the
keywords would pick. (`add … exchanges … feeds=<use id>` sets it directly.)

The map is generated, so when the user wants it to read differently, change the plan
(uses, parties, exchange names) and regenerate rather than editing the drawing by hand.
Exchange names are matched to uses by keyword ("coordination model" → 3D coordination,
"COBie handover" → asset management); renaming an exchange so it says what it feeds is
the way to move an unplaced exchange onto the map.

### Where answers go

| Section | Fields |
|---|---|
| 01 Project | `project.name`, `.owner`, `.location`, `.delivery`, `.phase`, `.start` (YYYY-MM-DD), `.agency`, `.cui` (yes/no), `.iso` |
| 02 Team | `add … team role= org= name= email=` |
| 03 Goals | `add … goals goal= uses=` (highest priority first) |
| 04–05 Uses and process | `use … <id> --party --value --flow` |
| 06 Exchanges | `add … exchanges what= from= to= content= lod= due= [feeds=<use id>]`; `set … cobie yes` |
| 07 Collaboration | `collab.cde`, `.sharing`, `.meetings`, `.coords`, `.naming`, `.changes` |
| 08 Technology | `add … tech discipline= software= version= formats=` |
| 09 Standards | `standards.ncs`, `.sheet` (level1/level2/campus), `.level2`, `.minor` (booleans), `.statusField` (status/phase/none/both), `.iso13567` (boolean), `.layerFormat` (element/view), `.sheetCode` (4 chars), `.plotting`, `.notes`; `add … standards.codes code= meaning=` |
| 10 Quality control | `qc … visual|clash|standards|integrity --tool --who --freq`; `qc … a0..a8|d0..d8 [--off] --who --freq` |
| 11 Deliverables | `add … deliver item= format= due=` |

`add` replaces the first placeholder row (blank, or still the new-plan default such as
the starter "BIM manager" or "Architectural" row) before appending, so a fresh plan
doesn't keep empty or leftover rows — no need to `remove` them first. Responsible-party values are free text; using the team
member's role (e.g. "BIM manager") keeps the plan readable.

## Judgment calls

- **Agency.** If the project is for USACE or another DoD owner, set `project.agency usace`
  and ask the CUI question early — the answer changes how files are stored and shared.
  For GSA, VA, or other federal owners, the `whole-building-design-guide` skill can look up
  their criteria; put the result in `standards.notes` with its source and version.
- **Layer and sheet conventions.** For anything beyond the choices the tool offers, use the
  `national-cad-standard` skill. `check-names` applies the same rules as that skill's
  checker, so use it whenever the user pastes layer names or sheet numbers — with
  `--plan` once the plan's standards are set.
- **Status field.** Ask how the project uses the last layer field and set
  `standards.statusField`: `status` (letters N, E, D…), `phase` (numbers 1–9), or `none`.
  `both` is plain NCS and blocks ISO conformance, so avoid it when ISO matters.
- **ISO 13567.** Turn on `standards.iso13567` for international work or when the owner
  asks for ISO layer naming, and pick `standards.layerFormat` (`element` keeps a
  refinement like FULL; `view` keeps DETL/ELEV/SECT). `ANNO` is never used under ISO, and
  it can't simply be renamed TEXT — annotation codes go in the annotation field of the
  element they describe. Old ANNO layers need a person to choose that element: run
  `convert`, which moves sheet-level annotation (title blocks, general notes, legends,
  stamps) to the plan's `standards.sheetCode` automatically, then ask about the ones it
  flags. The sheet code is added to the Compliance Disclosure Statement list and the
  definition file automatically. Deliver the `definition` file with the CAD set.
- **Firm defaults in new plans:** ISO 13567 off (turn on per project when an owner requires
  it), element layer format, status letters, sheet-level annotation code `SHET`. Change
  them per project only when the user says so.
- **ISO 9001.** Turn on `project.iso` only if the user's firm or owner wants ISO alignment.
  The export cites clause numbers only, never ISO text — that's deliberate, because ISO
  copies are usually single-user licensed.
- **Software steps.** If the user asks how to set something up in Revit, Navisworks, or
  Autodesk Construction Cloud, look it up with the Autodesk Product Help connector rather
  than from memory, and add the link to the relevant field.

## The web app

The plan format is the same one the BIM Execution Plan Builder web app stores as
document `bep/plan` in its shared database. The app wraps it as
`{"plan": {...}, "updatedBy": ..., "updatedAt": ...}`; `bep.py` accepts that wrapped form
directly, so a document read from the app (for example with the ArtifactData tool, saved
with `out_dir`) can be validated and exported here. To push a CLI plan into the app,
write it back to `bep/plan` in that same wrapped shape — only when the user asks, since
it replaces what the whole team sees.

## Talking to the user

Many users are architects and BIM managers, not programmers. Keep command output out of
your replies unless they ask; describe what changed ("Added Dana as MEP lead; 4 of 11
sections are now complete"). When TODOs remain, ask about them in plain language rather
than listing field paths.
