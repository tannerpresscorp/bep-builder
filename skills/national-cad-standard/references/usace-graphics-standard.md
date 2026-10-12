# DoD / USACE overrides — A/E/C Graphics Standard, Release 2.2

Source: ERDC/ITL SR-23-1, *A/E/C Graphics Standard Release 2.2* (US Army Corps of
Engineers CAD/BIM Technology Center, August 2023). Approved for public release; hosted
on WBDG: https://www.wbdg.org/FFC/AECCAD/ERDC_ITL_SR_23_1_2023.pdf

**When to use this file:** any DoD, USACE, Army, Navy, or Air Force project. The
standard embraces NCS (especially the Uniform Drawing System) and adds drafting rules
NCS leaves open; where it is more specific, it governs. Its companion, the
**A/E/C CAD Standard Release 6.1** (ERDC/ITL TR-19-7), covers DoD layers and symbology —
look it up on WBDG when a project needs those. Before citing, check WBDG for a newer
release.

## Contents
1. Sheets and borders
2. Text
3. Linework and screening
4. Numbering (floors, rooms, doors)
5. Schedules
6. Revisions
7. Controlled Unclassified Information (CUI)

---

## 1. Sheets and borders

| Item | Rule |
|---|---|
| Contract sheet size | ANSI D (22 × 34 in.); ANSI E or F for oversized work (master plans, civil works) |
| International projects | ISO A1; A0 for oversized |
| Margin | At least 3/16 in. from paper edge; keep a binding edge on the left |
| Borders | Use the Center's border sheets for all printed contract and O&M sets, PDF and paper (not shop drawings) |
| Sheet areas | Drawing area and title block area required; production data area optional |
| Sheet ID block | Sheet ID per NCS (A-101). "SHEET ID" label 1/8 in.; the identifier 9/32 in. Optional BLDG ID field (3/16 in.) for multi-structure sets |
| "Sheet X of Y" | Removed — the drawing index carries sheet order |

## 2. Text

| Item | Rule |
|---|---|
| Font | Arial (regular for most text, italic to set text apart, bold for titles and cover sheets) |
| Case | All capitals (stays readable at half size) |
| Building disciplines (H, S, A, I, F, P, M, E, T, R, X, O) | Normal 3/32 in. (2.4 mm), subtitle 1/8 in. (3 mm), title 3/16 in. (5 mm) |
| Civil disciplines (G, V, C, B, L) — and all symbols, linestyles, border text | Normal and subtitle 1/8 in. (3 mm), title 3/16 in. (5 mm) |
| Text width / line spacing | Width factor equal to height; line spacing half the text height |
| Leader terminators | Arrowhead width 1.5 × text height; dot 0.75 × text height |

## 3. Linework and screening

- Line weights follow the NCS plotting line-width table (see `bim-and-plotting.md`).
- **New work** plots at 100%; **existing conditions** (including their text) are
  screened between 20% and 60%. Survey drawings are delivered unscreened and screened
  later when used as a background.
- **Demolition plans are separate from new-work plans.** Mark removed or relocated items
  with notes, keynotes, symbol modifiers, patterns, line styles, or callouts.

## 4. Numbering

- **Floors:** ground floor = Floor 1 (F1); up from there in sequence; below = B1, B2…;
  non-habitable top level = attic; roofs = ROOF or R1, R2 at different elevations.
- **Rooms:** every floor plan except structural shows room IDs. The number starts with the
  floor number and runs from the main entrance (lobby = 100, first room to the right =
  101). Construction room numbers may differ from final signage — agree on numbering
  with the owner first.
- **Doors:** a door in a one-door room takes the room number of its secure side. Several
  doors in one room → room number + letter, clockwise from the corridor door (126A,
  126B). The same mark goes in the door schedule's Mark column.
- **Civil:** state the project coordinate system and datum (usually State Plane) at least
  once on civil plans and describe the grid in the general notes.

## 5. Schedules

- Minimum per UDS: Heading, Mark, Item Description, Distinguishing Feature.
- Outline 0.70 mm; grid lines 0.35 mm; heading 3/16 in.; subheadings 1/8 in.;
  text 3/32 in.

## 6. Revisions

| Type | When | Indicator |
|---|---|---|
| Amendment | During advertisement (before award) | Numbers: 1, 2, 3 |
| Modification | After construction contract award | Capital letters: A, B, C |

- Every revision gets an equilateral-triangle indicator beside a revision cloud drawn at
  medium weight (0.35 mm).
- Revision (Issue) block columns: MARK, DESCRIPTION, DATE; text 3/32 in.
- As-built guidance: ERDC/ITL SR-21-6, *Record Package Guidance* (or newer).

## 7. Controlled Unclassified Information (CUI)

- The Project Delivery Team decides, using the CUI process flowchart, whether drawings
  contain CUI.
- If yes: "CUI" at the top and bottom of every sheet (Arial, 1/4 in.), plus a CUI
  Designation Indicator block on the cover sheet only (Arial, 1/8 in.) listing the
  controlling DoD component, the originating office, and the CUI categories.
- In a BEP, record the CUI decision, who made it, and how CUI files are stored and
  shared (it affects the common data environment and who can access models).
