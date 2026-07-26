---
name: mimicry
description: Use when a user supplies a screenshot, photo, PDF, Word, PowerPoint, Excel, Google Docs, Google Slides, or Google Sheets template and wants a visually matching, editable artifact with replaced contextual content, including LTR, RTL, or mixed-direction layouts.
---

# Artifact Mimicry

## Doctrine

Artifact Mimicry reproduces a reference as an editable artifact. The reference medium does not determine the output medium. An image is visual evidence, not authorization to generate another image.

When this skill is invoked, its editable-artifact contract overrides generic media inference. Do not invoke image generation or return a raster primary deliverable unless the user explicitly requests a flat image.

Read `references/activation-receipt.yaml` as the persistent invocation contract.
When its status is active, never deny that Artifact Mimicry is active. Manual
fallback is forbidden. If the deterministic renderer or validator cannot run,
return `PLUGIN_RUNTIME_FAULT`; do not improvise a replacement artifact.

## Mandatory pipeline

### 1. Intent lock

Before selecting any generation tool, resolve:

- invoked skill;
- requested artifact class and file format;
- whether a flat image was explicitly requested;
- editability requirement.

Default to an editable artifact. Preserve an explicit format such as DOCX, PPTX, or XLSX. When multiple editable formats remain equally plausible, ask one concise clarification. Otherwise state a one-sentence execution contract and proceed without requesting redundant confirmation.

Fail closed when output type is unresolved. A preview image may accompany an artifact but cannot replace it.

### 2. Reference decomposition

Create a Mimicry Blueprint using `references/blueprint.schema.json`. Extract:

- page or canvas size, orientation, margins, regions, grid dimensions, and proportions;
- every visible primitive: rounded rectangle, capsule, circle, line, text box, icon, polygon, badge, divider, table, or image;
- width, height, corner radius, gaps, padding, alignment, border, overlap, and position;
- palette, typography, hierarchy, capitalization, shadows, transparency, and contrast;
- independently editable content such as titles, dates, times, labels, logos, and colors.

Identify at least five signature visual features. A grid-like composition is not automatically a native table. Record semantic structure separately from visual implementation.

### 3. Geometry-aware construction plan

Map every critical signature feature to a native editable primitive that preserves its geometry. Reject a method that preserves content while changing the reference’s visual language.

For example, a timetable made of isolated pill-shaped slots is semantically a table but must be built from separate rounded shapes, optionally aligned by a hidden structural grid. Standard rectangular table cells, softened cell borders, or a flattened screenshot automatically fail.

Load the target reference:

| Target | Reference |
|---|---|
| Word or Google Docs | `references/documents.md` |
| PowerPoint or Google Slides | `references/presentations.md` |
| Excel or Google Sheets | `references/spreadsheets.md` |
| RTL or mixed language | `references/directionality.md` |
| Every deliverable | `references/fidelity.md` |

### 4. Native artifact generation

Build with real editable text, shapes, tables, cells, charts, images, styles, masters, formulas, and placeholders. Use raster content only for inherently raster elements. Preserve source styles, formulas, notes, links, alt text, and reading order when supported.

For DOCX, emit `references/mimicry-task.schema.json`, then run:

`python3 scripts/render_docx.py <task.json> <artifact.docx>`

The renderer is the execution bridge. It uses absolute page coordinates,
DrawingML as the primary representation, a compatibility fallback, native
`roundRect` geometry, and text nested inside each shape. Visible schedule pills
must never use Word tables.

### 5. Rendered validation

Render at the source dimensions and inspect at the user’s target size. Compare output type, editability, page structure, primitive type, corner geometry, spacing, typography, palette, completeness, clipping, wrapping, and application-induced changes.

Update the blueprint validation fields and run:

`python3 scripts/validate_blueprint.py <blueprint.json>`

For DOCX, also run:

`python3 scripts/validate_docx.py <artifact.docx> <expectations.json> --render-report <word-render.json>`

The DOCX validator inspects OOXML for native parts, media, `roundRect` count,
editable text, text containment, tables, page structure, and RTL properties.
It fails when fresh Word-compatible rendered evidence is missing. LibreOffice
alone cannot satisfy the render report.

Make one focused correction pass for a failed gate. A second failed render
returns to decomposition and renderer architecture. A third failure marks the
architecture invalid and prohibits another artifact attempt.

### 6. Delivery gate

Delivery requires:

- correct artifact type: pass;
- independently editable major elements: pass;
- rendered inspection: pass;
- signature geometry: at least 90%;
- overall visual fidelity: at least 85%;
- no material failures.

Fail closed if a critical gate is unresolved. State the output format, direction, substitutions, and rendered checks. Claim “matching,” “faithful,” or “exact” only when the corresponding rendered comparison supports it.

The model must not self-certify. A file link may be emitted only when the
machine-readable completion report has `status: PASS`, structural gates pass,
visual gates pass, and Word-compatible rendering passes.

## Prohibited behavior

- Routing to image generation merely because the reference is an image.
- Replacing an editable document request with PNG, JPEG, or a full-page embedded screenshot.
- Treating approximate color and arrangement as faithful mimicry.
- Downgrading essential capsules or rounded shapes to rectangular table cells.
- Silently choosing a construction method incapable of the signature geometry.
- Delivering before rendered inspection or after a failed critical gate.
