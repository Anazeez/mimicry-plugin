# Artifact Mimicry Reference-Agnostic Fidelity Engine

Date: 2026-07-29
Status: Approved architecture

## Objective

Rebuild the existing private Artifact Mimicry MCP so each supplied visual
reference is reconstructed as a fresh editable DOCX and validated against that
same reference. No renderer, validator, or threshold may encode a particular
template, row count, column count, language, icon, or shape family.

The MCP tool name, OAuth flow, public Worker URL, and installed ChatGPT
connection remain unchanged.

## Evidence

The failed meeting-grid DOCX contains 37 editable shapes, yet:

- all text is emitted as white;
- all shape strokes are emitted as no-fill, removing the visible grid;
- portraits are replaced by emoji;
- LibreOffice renders the generated DOCX as a blank page;
- the validator derives expected values from the same task it validates.

The current Worker parses the reference-file descriptor but never downloads or
examines its bytes. Its validation is therefore circular and cannot establish
fidelity.

## Considered approaches

### Extend the hand-written OOXML renderer

Rejected. More checks cannot make a self-derived task faithful to an unread
reference, and the current DrawingML/VML package already renders inconsistently
across Word-compatible applications.

### Render an HTML or SVG proxy in Browser Rendering

Rejected as the delivery gate. It could compare a proxy to the reference but
would not inspect the actual DOCX consumed by Word or Google Docs.

### Native office container with independent visual validation

Selected. Cloudflare Workers keeps MCP, OAuth, orchestration, and temporary
artifact delivery. A Cloudflare Container supplies a Linux filesystem,
LibreOffice, fonts, OCR, and image-processing tools needed to build and inspect
the actual DOCX.

## Runtime pipeline

1. The existing `execute` tool receives the canonical reference-file descriptor
   and optional model-provided layout hints.
2. The Worker downloads the reference bytes, enforces MIME and size limits, and
   computes a request-scoped digest.
3. A Cloudflare-hosted vision model extracts a normalized scene graph:
   page, regions, groups, text, direction, bounding boxes, fills, strokes,
   typography, images, shapes, z-order, and relative constraints.
4. The scene graph is schema-validated. User/model hints may enrich it but may
   not override measured geometry without evidence.
5. The Container constructs the DOCX through LibreOffice UNO native objects,
   including editable text, shapes, lines, tables when visually appropriate,
   and separately editable raster elements for inherently raster content.
6. LibreOffice reopens the saved DOCX and exports its rendered page to PDF and
   PNG. Failure to reopen or render is a critical failure.
7. The validator compares the rendered PNG to the reference at a normalized
   resolution and emits structural, geometric, typographic, color, OCR, and
   visual-difference metrics.
8. One bounded correction is allowed using the measured differences. A second
   failure returns the full report and no DOCX.
9. Only a passing DOCX is placed in the existing 24-hour artifact store.

## Generic scene graph

Every node has a stable identifier and:

- primitive type: text, rectangle, rounded rectangle, ellipse, line, polygon,
  table/grid, image, or group;
- normalized `x`, `y`, `width`, and `height`;
- parent group, z-order, alignment, containment, and adjacency constraints;
- fill, stroke, stroke width, opacity, corner radius, and image crop;
- text, font family, size, weight, alignment, language, and LTR/RTL direction;
- editability and semantic role.

Rows, columns, cells, avatars, icons, capsules, posters, and report sections are
expressed through these generic nodes and relationships. There are no
template-specific node types.

## Validation gates

### Structural

- valid DOCX that LibreOffice can reopen;
- requested page count, size, and orientation;
- independently editable required elements;
- no full-page flattened reference;
- RTL/LTR properties preserved.

### Geometry

- normalized bounding-box error;
- row and column alignment;
- gap and margin error;
- containment and adjacency;
- overlap/collision violations;
- line and border continuity;
- relative size and baseline consistency.

### Visual

- foreground/background contrast;
- palette distance;
- OCR text presence and approximate placement;
- edge-map similarity;
- region-level perceptual difference;
- typography hierarchy;
- overall visual similarity.

Critical structure, reopen/render, direction, and signature-geometry gates are
pass/fail. Metric thresholds are versioned and calibrated against known-good
and deliberately broken fixtures.

## Regression fixtures

The same implementation must pass:

1. RTL capsule timetable with independent rounded cells.
2. RTL meeting grid with portraits, icons, visible borders, and six columns.
3. LTR poster/report composition.
4. Mixed RTL/LTR page.

For each known-good fixture, deliberately broken variants must be rejected:
missing borders, white-on-white text, displaced headers, collapsed spacing,
wrong row/column alignment, substituted emoji, and flattened-page images.

The supplied reference and failed DOCX are evidence and test fixtures only.
Production code must contain no identifiers, dimensions, strings, or counts
specific to either file.

## Failure contract

Failures return:

- stage;
- machine-readable gate results;
- expected and observed values;
- rendered preview URL when safe;
- confirmation that no editable artifact was delivered.

Infrastructure failure, scene-graph uncertainty, failed DOCX reopening, or
failed critical fidelity gates all fail closed.

## Privacy and operations

Reference bytes and container working files are request-scoped and deleted after
completion. Only the passing DOCX is retained in the existing unlisted
24-hour store. Logs contain identifiers and metrics, not document contents.

The GitHub Actions deployment remains the source of truth. It builds the
Worker and container image, runs regression tests, deploys to the existing
Cloudflare service, and records the deployed commit and container digest.

## Acceptance

The work is complete only when:

- the known-good fixtures pass through the same generic pipeline;
- every deliberately broken variant fails its intended machine gate;
- the meeting-grid output has visible borders, dark readable text, correctly
  aligned participant columns, and preserved portraits/icons;
- the capsule timetable retains actual capsule geometry;
- the generated DOCX reopens and renders in the container;
- the existing MCP connection invokes the upgraded backend without reinstall,
  renaming, or a new tool.
