---
name: national-cad-standard
description: Apply the United States National CAD Standard (NCS V7) — AIA CAD Layer Guidelines, CSI Uniform Drawing System sheet and file naming, plotting/BIM implementation guidance, and NCS layer naming in conformance with ISO 13567 — when setting up, auditing, converting, or documenting CAD/BIM standards. Use this whenever the user mentions NCS, the National CAD Standard, AIA layer names (A-WALL, E-LITE, G-ANNO-NPLT), the ANNO major group, status/phase fields, ISO 13567 layer naming, UDS sheet numbers (A-101), drawing set order, layer or sheet naming conventions, CAD standards for a BIM Execution Plan (BEP), or Revit/AutoCAD/Civil 3D export layer mapping — even if they don't say "NCS" by name.
---

# National CAD Standard (NCS)

> **Public repository note:** `references/conventions.md`, `references/bim-and-plotting.md`,
> and `references/iso13567-profile.md` are not included here, because they summarize the
> licensed NCS text, which may not be redistributed. Licensees can recreate them from their
> own copy. Until then, rely on `scripts/check_names.py`, `scripts/iso13567.py`, and the
> licensee's copy of the standard, and tell the user when a detail needs checking there.

This skill helps you set up, explain, check, and document project CAD/BIM conventions
that follow the U.S. National CAD Standard, and connect them to Autodesk tools.

## What the NCS is (so you can explain it simply)

The NCS is published by the National Institute of Building Sciences (NIBS). The
current edition is **V7 (2024)**, delivered as a licensed online document. It bundles:

1. **AIA CAD Layer Guidelines** — how layers are named.
2. **CSI Uniform Drawing System (UDS), Modules 1–8** — sheet identification, drawing
   set order, schedules, drafting conventions, terms and abbreviations, symbols, notes,
   and code conventions.
3. **NIBS BIM Implementation & Plotting Guidelines** — how NCS concepts carry into
   model-based workflows and how sheets are plotted.

Many federal agencies require NCS, which is why it shows up so often in BIM Execution
Plans (BEPs) for public work.

**Which edition.** The rules in the references were checked against a licensed copy of
NCS V6 (layer guidelines, UDS Modules 1–8, BIM Implementation, Plotting Guidelines). V7 keeps the same
structure. If the contract names an edition, cite that edition, and say which one your
answer reflects.

**Licensing matters.** The full text is paid, licensed content. The license allows
using NCS information inside the licensee's organization and in the construction
documents they produce, but not redistributing the standard itself. So explain
conventions in your own words with representative examples, don't reproduce the
official tables wholesale, and point the user to their licensed copy for complete code
lists (CLG Appendix A, the UDS terms/abbreviations and symbols libraries). Being upfront
about this protects the user from building a standard on a guess.

## How to work

1. **Pin down the job.** Usually one of: (a) explain a convention, (b) generate
   layer/sheet names for a project, (c) audit names the user pasted, (d) write the
   "CAD/BIM Standards" section of a BEP, or (e) configure software to match.
2. **Read `references/conventions.md`** for the layer format, status codes, discipline
   designators, sheet-type numbers, and set order. It is the backbone for (b)–(d).
   **On any BIM/Revit project, or when writing a BEP, also read
   `references/bim-and-plotting.md`.** It says which NCS rules are required vs. optional
   for BIM (only `A-WALL`-level layer names are required), where 3D views go in the set,
   the minimum schedule columns, NCS's model authoring and delivery rules (ready-made
   QC checklist items), and the plotting line widths and gray screening.
3. **For anything inside Autodesk software, use the Autodesk Product Help connector**
   (`mcp__Autodesk_Product_Help__search_help_content`, locale from context, usually
   `en_US`). Don't write click-paths from memory — menus move between releases, and the
   connector returns the current official steps. Useful product codes: `RVT` (Revit),
   `ACD` (AutoCAD), `CIV3D` (Civil 3D), `NAVMAN` (Navisworks Manage), `ACDLT` (AutoCAD
   LT). If the user names a release year, validate it with
   `get_available_products` before passing `release_code`. Good queries:
   - "Revit DWG export layer mapping load layers from standards AIA"
   - "AutoCAD CAD Standards check drawing against DWS file"
   - "Civil 3D layer naming template"
   Cite the help URL next to each step you take from it.
4. **For audits, run the checker** rather than judging by eye — it applies the same
   rules every time:
   `python scripts/check_names.py A-WALL-FULL a-wall A-101` (or `--file names.txt`).
   Add `--status-field status|phase|none` when the project has decided how it uses the
   status field (the default `both` is plain NCS). It checks format only, so still read
   the result and flag names that are well-formed but unusual (for example, a major
   group that isn't a recognizable building system).
5. **ISO 13567 or international work.** When the project needs ISO 13567 conformance,
   the user mentions ISO layer naming, or asks to drop `ANNO`, read
   `references/iso13567-profile.md` and use `scripts/iso13567.py`:
   - `check --level 1|2 --format element|view --status status|phase|none NAMES` — strict
     check against the project's fixed-length profile.
   - `convert [same options] [--anno-element CODE] NAMES` — suggests the ISO form of
     existing names and flags the ones a person must decide (every old `ANNO` layer).
   - `definition [same options] --project "Name"` — writes the ISO 13567-3 layer naming
     system definition file the project must deliver.
   If someone proposes swapping `ANNO` for `TEXT` as the major group, explain gently that
   it repeats the same problem (annotation in ISO's Element field) and show the
   annotation-minor-group form instead.
6. **Produce the output** in the format below that fits the job.

## Output formats

**Audit of pasted layer or sheet names** — a table, one row per name:

| Name | Valid? | Problem | Suggested fix |
|---|---|---|---|

Explain each problem in a short plain sentence ("the major group must be exactly four
characters"), so a beginner learns the rule rather than just the answer.

**BEP "CAD/BIM Standards" section** — use these headings:

```
## CAD and BIM Standards
### Governing standard        (NCS version, any agency or owner overrides)
### Layer naming              (format or ISO 13567 profile, status field setting,
                               placeholders, user-defined codes from the NCS
                               Compliance Disclosure Statement, definition file)
### Sheet identification      (format, discipline list used on this project)
### Drawing set organization  (order of disciplines)
### File naming               (model files: set by this BEP; exported CAD sheets: UDS)
### Schedules and annotation  (minimum schedule columns, symbols, keynotes from model)
### Plotting                  (line-width table, plot style files)
### Software configuration    (export setups, templates, .dws files — with help links)
### Model authoring and delivery  (NCS BIM rules as checkable QC items)
### Compliance checking       (who checks, when, with what tool)
```

**Explanations** — lead with a one-line answer, then one concrete example, then the
"why". Teaching the reason ("status codes let you turn off demolition work with one
filter") helps the rule stick.

## Things to watch for

- Owner or agency standards (GSA, USACE, VA, state DOTs) often modify NCS. If the user
  mentions an agency, say that its standard governs where it differs, and suggest the
  `whole-building-design-guide` skill to look up that agency's requirements.
- **DoD / USACE projects** (Army Corps, Army, Navy, Air Force, military installations):
  read `references/usace-graphics-standard.md`. It adds sheet size, Arial all-caps text
  heights, existing-work screening, room and door numbering, revision marks
  (amendments 1-2-3 vs. modifications A-B-C), and CUI marking rules on top of NCS.
- Revit's built-in "AIA" export mapping is a starting point, not a full NCS
  implementation — mention that the mapping usually needs project-specific edits.
- Don't invent official group codes. NCS allows project-specific 4-character major and
  minor groups, but each must be listed on the project's **NCS Compliance Disclosure
  Statement** — so label any custom code as user-defined and add it to that list (and to
  the BEP's layer-naming section).
- Sheet IDs are strict: always 5 characters (`A-101` or `AD101`), sequence 01–99. A
  project uses Level 2 letters either for discipline modifiers or for campus building
  IDs, never both — ask which if the user's names mix them.
