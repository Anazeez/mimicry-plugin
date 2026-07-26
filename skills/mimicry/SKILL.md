---
name: mimicry
description: Use when a user supplies a screenshot, photo, PDF, Word, PowerPoint, Excel, Google Docs, Google Slides, or Google Sheets template and wants a visually matching, editable artifact with replaced contextual content, including LTR, RTL, or mixed-direction layouts.
---

# Mimicry

## Core contract

Reconstruct the source's visual system as a native, editable office artifact. The source is the design authority: do not reinterpret, beautify, or apply a generic AI aesthetic.

The finished artifact must preserve structure, hierarchy, geometry, typography, color, repeated elements, and directionality. Never present a flattened screenshot as an editable deliverable.

## Execute

1. **Resolve source and target.** Identify the source format, requested output application, editable content boundaries, language direction, and authorized source material. Preserve the source application when no target is named. If the requested connector is unavailable, create the closest native editable file and state the limitation; never claim an external Google or Microsoft artifact was created when it was not.
2. **Inspect before building.** For native files, inspect page/slide/sheet structure, styles, themes, masters, formulas, charts, and assets. For images or PDFs, measure the canvas and reconstruct regions, spacing, type hierarchy, colors, borders, crops, and repeated structures.
3. **Create a Mimicry Blueprint.** Normalize the design using `references/blueprint.schema.json`. Record every material region and its direction. Validate a saved blueprint with `python3 scripts/validate_blueprint.py <file>`.
4. **Build natively.** Use real text, tables, cells, charts, shapes, images, styles, themes, masters, formulas, and placeholders. Clone native styles and masters when present. When content is absent, use clearly editable placeholders that preserve the original density and line count.
5. **Render and compare.** Render the output at the source dimensions and inspect it at the user's target size. Compare geometry, line breaks, font metrics, colors, borders, crop, layering, density, and reading order. Make one focused correction pass for material mismatches.
6. **Deliver with a fidelity note.** Name the output format, direction mode, substitutions, unresolved limitations, and what was visually verified. Say “exact” only when the rendered comparison supports it.

## Route by artifact

| Target | Required reference |
|---|---|
| Word or Google Docs | `references/documents.md` |
| PowerPoint or Google Slides | `references/presentations.md` |
| Excel or Google Sheets | `references/spreadsheets.md` |
| Any RTL or mixed-language artifact | `references/directionality.md` |
| Every final visual comparison | `references/fidelity.md` |

Load only the references needed for the requested target, plus fidelity.

## Non-negotiable checks

- Match the source canvas/page/slide/sheet dimensions before positioning content.
- Preserve editability and semantic structure; use an image only for an element that is inherently raster.
- Preserve formulas, number formats, chart data, notes, links, alt text, and reading order when present and supported.
- Resolve missing fonts by metric similarity and disclose every substitution.
- Apply direction at document, section, paragraph, run, table, slide, sheet, and cell level where the target supports it.
- Mixed Arabic/Hebrew and Latin text must keep correct numbers, punctuation, formulas, URLs, and acronyms.
- Do not invent logos, signatures, seals, or proprietary assets missing from the authorized source.

## Common failure modes

| Failure | Correction |
|---|---|
| “Similar” layout from visual intuition | Measure and encode a blueprint first |
| Correct content in a generic theme | Treat source styling as binding |
| RTL implemented only with right alignment | Apply bidi direction and logical reading order |
| Spreadsheet looks right but loses behavior | Preserve formulas, formats, validation, and ranges |
| Deliverable is a screenshot inside a file | Rebuild with native editable objects |
| Repeated review loops | One render comparison and one focused correction pass |

