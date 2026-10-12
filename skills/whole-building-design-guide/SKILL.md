---
name: whole-building-design-guide
description: Look up and apply guidance from the Whole Building Design Guide (WBDG, wbdg.org) and the NIBS National BIM Standard (NBIMS-US) — federal facility criteria (UFC, GSA P100, GSA BIM Guides, VA BIM standards, USACE, NAVFAC), COBie deliverables, design objectives, and BIM Execution Plan (BEP) structure. Use this whenever the user is writing or reviewing a BEP, planning BIM uses or information exchanges, working on a federal or government building project, asks what an agency requires for BIM/CAD deliverables, mentions WBDG, NBIMS, COBie, UFC, or GSA P100, or needs authoritative building-design guidance with citations — even if they don't name WBDG.
---

# Whole Building Design Guide (WBDG)

WBDG is a free web portal run by the National Institute of Building Sciences (NIBS).
It collects design guidance and the official criteria many U.S. federal agencies
require. Its sister resource, NBIMS-US (hosted at nibs.org), includes the BIM
Execution Plan standard. Together they are the authoritative backbone for a BEP on
public work.

This skill turns those sites into a reliable "connection": a repeatable way to find the
right page, cite it, and turn it into BEP content.

## How to look things up

There is no WBDG API, so research goes through web tools. Search narrowly so results
come from the source, not from blogs that paraphrase it:

1. `WebSearch` with `allowed_domains: ["wbdg.org", "nibs.org"]` and a short query
   (agency + topic), e.g. "GSA BIM guide spatial program", "UFC 1-300-09N
   design procedures", "COBie deliverable". For a specific agency, add its own domain
   too (`gsa.gov`, `va.gov`, `usace.army.mil`, `navfac.navy.mil`) — agencies often
   publish the newest version on their own site before WBDG catches up.
2. `WebFetch` the best result for the full text. WBDG pages sometimes render empty
   through fetch; if that happens, try the PDF link in the result, the `nibs.org`
   mirror, or fall back to the search snippet — and say which you used.
3. Check the document's date or version. Federal criteria are revised often; tell the
   user the version you cited and note when something looks superseded.

`references/wbdg-map.md` lists where things live on WBDG and which agencies publish
what. Read it before searching — it saves guessing at queries.

Cite every requirement with a link. A BEP is a contract-adjacent document; an uncited
requirement is a liability for the user. Paraphrase rather than copying long passages.

## Building a BEP

When the user is setting up or reviewing a BEP, follow the NBIMS-US / Penn State
planning procedure (Version 3 uses five steps):

1. **Goals** — what the owner and team want BIM to achieve.
2. **BIM uses** — which uses deliver those goals (design authoring, clash detection,
   4D, cost, record model, asset management…).
3. **Process** — how each use flows between parties (process maps).
4. **Information exchanges** — who delivers what model content, at what level of
   development, when (including COBie for facility handover).
5. **Infrastructure** — contracts, communication, technology, standards, and QC.

Use `references/bep-outline.md` for the section-by-section template. For each section:
fill in what the user has told you, pull agency requirements from WBDG with citations,
and mark anything unknown as a clear **TODO** rather than inventing it. A BEP with
honest gaps is far more useful than one that looks complete but isn't.

For the CAD/BIM standards section (layers, sheets, set order), hand off to the
`national-cad-standard` skill if it is available. For DoD or USACE work, that skill's
`references/usace-graphics-standard.md` holds the A/E/C Graphics Standard rules
(text, screening, numbering, revisions, CUI) — and ask early whether the drawings
will be marked CUI, since that changes how the team stores and shares files.

### Optional: ISO 9001 alignment

If the user's firm runs an ISO 9001 quality system, or the owner asks for one, tag each
BEP section with the ISO 9001:2015 clause it supports using
`references/iso9001-alignment.md`. Use clause numbers and plain descriptions only —
ISO text is copyrighted and usually licensed to a single user, so never quote it or ask
the user to paste it.

## Connecting to Autodesk

Most BEP uses land in Autodesk tools. When a step needs software how-to — Revit COBie
export, Navisworks clash tests, model coordination in Autodesk Construction Cloud,
shared coordinates — use the Autodesk Product Help connector
(`mcp__Autodesk_Product_Help__search_help_content`, locale from context, usually
`en_US`). Useful product codes: `RVT` (Revit), `NAVMAN` (Navisworks Manage), `CIV3D`
(Civil 3D), `BIM360` / `DOCS` (Autodesk Docs / ACC), `ACD` (AutoCAD). Put the help URL
beside each step so the team can follow it later. Don't write click-paths from memory —
they change between releases.

## Output

- **Quick lookups:** a direct answer, the requirement in plain words, then the source
  link and version.
- **BEP sections:** Markdown using the headings in `references/bep-outline.md`, with a
  "Sources" list at the end.
- **Comparisons across agencies:** a table (Agency | Requirement | Source).

Keep language beginner-friendly: define acronyms the first time (LOD, COBie, IFC) in
one short phrase.
