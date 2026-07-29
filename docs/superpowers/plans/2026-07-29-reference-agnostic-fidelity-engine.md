# Reference-Agnostic Fidelity Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace circular task-only validation with a reference-aware DOCX pipeline that builds through LibreOffice, renders the actual file, and gates delivery on generic structural, geometric, contrast, and visual metrics.

**Architecture:** The existing OAuth-protected MCP Worker downloads and validates the reference, obtains a normalized scene graph through its Workers AI binding, and sends the scene graph plus reference bytes to one Cloudflare Container. The container uses LibreOffice UNO to build and reopen the DOCX, renders a PNG, computes independent fidelity metrics, and returns either a passing DOCX and report or a fail-closed report. The tool name, input shape, OAuth flow, artifact store, and public URL remain unchanged.

**Tech Stack:** Cloudflare Workers, Workers AI, Cloudflare Containers, Node.js 24, Python 3.12, LibreOffice headless/UNO, Pillow, OpenCV headless, Tesseract OCR, pytest, Node test runner, GitHub Actions.

## Global Constraints

- Production code contains no fixture-specific text, dimensions, identifiers, row counts, column counts, icons, or thresholds.
- Keep the existing `execute` MCP tool, OAuth flow, Worker URL, and installed connector.
- Reference and work files are request-scoped; only a passing DOCX enters the existing 24-hour store.
- One correction attempt maximum; the second failed validation returns no DOCX.
- Every production behavior begins with a failing automated test.
- Deployment remains GitHub Actions to the existing Cloudflare service.

---

### Task 1: Capture evidence and define the generic scene graph

**Files:**
- Create: `fixtures/meeting-grid/reference.jpg`
- Create: `fixtures/meeting-grid/failed.docx`
- Create: `fixtures/capsule-timetable/reference.jpg`
- Create: `fixtures/ltr-poster/reference.svg`
- Create: `fixtures/mixed-direction/reference.svg`
- Create: `container/app/schemas.py`
- Create: `container/tests/test_schemas.py`
- Create: `mcp/src/reference.js`
- Create: `mcp/src/reference.test.mjs`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `validate_scene_graph(value) -> dict` in Python.
- Produces: `downloadReference(referenceFile, fetchImpl?) -> {bytes, mimeType, digest, filename}` in JavaScript.
- Constraints: 20 MiB maximum, JPEG/PNG/WebP/PDF allowlist, HTTPS only, no redirect to private/link-local addresses.

- [ ] **Step 1: Add sanitized real fixtures**

Copy the supplied meeting-grid reference and failed DOCX and the existing capsule timetable reference into `fixtures/`. Add deterministic SVG fixtures for an LTR poster and a mixed Arabic/English report page. Add a fixture README declaring that production imports from `fixtures/` are prohibited.

- [ ] **Step 2: Write failing reference-ingestion tests**

Test successful image download, MIME mismatch rejection, oversize rejection, HTTP rejection, and private-address redirect rejection using injected `fetchImpl`.

- [ ] **Step 3: Run the reference tests and observe failure**

Run: `cd mcp && node --test src/reference.test.mjs`

Expected: FAIL because `reference.js` does not exist.

- [ ] **Step 4: Implement bounded reference ingestion**

Implement URL validation, redirect-by-redirect validation, streamed byte limit, SHA-256 digest, and magic-byte MIME detection. Never log bytes or signed query parameters.

- [ ] **Step 5: Write failing scene-graph schema tests**

Test generic page, group, text, shape, line, grid, image, normalized bounding boxes, strokes, typography, RTL/LTR, z-order, parent references, and relationship constraints. Test duplicate IDs, out-of-page boxes, invalid parent references, and fixture-specific node types as failures.

- [ ] **Step 6: Run schema tests and observe failure**

Run: `pytest -q container/tests/test_schemas.py`

Expected: FAIL because `validate_scene_graph` is absent.

- [ ] **Step 7: Implement the scene-graph validator**

Use plain Python validation with stable error codes. Return normalized data only after all IDs, bounds, parents, and constraints pass.

- [ ] **Step 8: Verify and commit**

Run: `cd mcp && node --test src/reference.test.mjs && cd .. && pytest -q container/tests/test_schemas.py`

Commit: `Build bounded reference and scene graph contracts`

### Task 2: Replace handwritten OOXML with a native LibreOffice renderer

**Files:**
- Create: `container/Dockerfile`
- Create: `container/requirements.txt`
- Create: `container/app/server.py`
- Create: `container/app/renderer.py`
- Create: `container/tests/test_renderer.py`
- Create: `container/tests/fixtures/minimal-scene.json`
- Delete: `mcp/src/renderer.js`
- Modify: `mcp/src/renderer.test.mjs`

**Interfaces:**
- Consumes: validated scene graph and reference file.
- Produces: `render_scene(scene, workspace) -> RenderedArtifact(docx_path, pdf_path, png_path, manifest)`.
- HTTP: `POST /render` multipart request; JSON failure or multipart/ZIP success response.

- [ ] **Step 1: Write the failing native-render regression**

Create a generic two-column scene with visible strokes, dark text on a pale fill, RTL text, one rounded shape, one line, and one image placeholder. Assert that the DOCX reopens, exports to one-page PDF/PNG, includes non-white pixels, preserves stroke width and dark text, and contains no full-page background image.

- [ ] **Step 2: Run it and observe failure**

Run: `pytest -q container/tests/test_renderer.py::test_native_docx_reopens_and_renders`

Expected: FAIL because `renderer.py` is absent.

- [ ] **Step 3: Implement LibreOffice UNO construction**

Start one isolated headless LibreOffice process per request with a temporary user profile. Create a Writer document, set page geometry, add native text frames, drawing shapes, lines, tables/grids, and image objects through UNO, apply RTL paragraph properties, export DOCX, close, reopen the saved DOCX, export PDF, and rasterize the first page.

- [ ] **Step 4: Implement the container HTTP boundary**

Accept a scene JSON part and reference part, allocate a temporary workspace, call the renderer, return files and manifest, and remove the workspace in `finally`. Limit request size and execution time.

- [ ] **Step 5: Build and run the container tests**

Run:

```bash
docker build -t artifact-mimicry-renderer:test container
docker run --rm artifact-mimicry-renderer:test pytest -q
```

Expected: all renderer tests pass and the output PNG is nonblank.

- [ ] **Step 6: Verify deliberately broken compatibility**

Feed the supplied failed DOCX to the reopen/render checker and assert rejection because its rendered page is blank.

- [ ] **Step 7: Commit**

Commit: `Render editable DOCX through LibreOffice`

### Task 3: Add independent geometry and visual gates

**Files:**
- Create: `container/app/validator.py`
- Create: `container/tests/test_validator.py`
- Create: `container/tests/fixtures/known-good.png`
- Create: `container/tests/fixtures/broken-border.png`
- Create: `container/tests/fixtures/broken-contrast.png`
- Create: `container/tests/fixtures/broken-offset.png`
- Modify: `container/app/server.py`

**Interfaces:**
- Consumes: source reference, rendered PNG, validated scene graph, render manifest.
- Produces: `validate_fidelity(...) -> {status, gates, metrics, findings, correction_hints}`.

- [ ] **Step 1: Write failing machine-judge calibration tests**

Assert the known-good render passes. Assert missing borders fail `G_BORDER_CONTINUITY`, white-on-white text fails `V_CONTRAST`, displaced columns fail `G_ALIGNMENT`, blank render fails `R_NONBLANK`, and flattened full-page media fails `S_EDITABILITY`.

- [ ] **Step 2: Run them and observe failure**

Run: `pytest -q container/tests/test_validator.py`

Expected: FAIL because `validate_fidelity` is absent.

- [ ] **Step 3: Implement deterministic metrics**

Calculate normalized bounding-box error, alignment residuals, gap variance, containment, collision count, line continuity, WCAG contrast, edge-map similarity, palette distance, OCR word-box overlap, and region-level SSIM. Keep each metric independent of fixture content.

- [ ] **Step 4: Calibrate versioned thresholds**

Store thresholds in `container/app/fidelity-v1.json`. Prove every known-good fixture passes and every deliberately broken fixture fails the intended gate. Threshold changes require a version increment and all calibration tests.

- [ ] **Step 5: Attach full reports to container responses**

Return expected, observed, threshold, and affected node IDs for every failure. Never return a DOCX when any critical gate fails.

- [ ] **Step 6: Verify and commit**

Run: `docker run --rm artifact-mimicry-renderer:test pytest -q`

Commit: `Gate artifacts on geometric and visual fidelity`

### Task 4: Orchestrate vision, rendering, and one bounded correction

**Files:**
- Create: `mcp/src/scene-graph.js`
- Create: `mcp/src/scene-graph.test.mjs`
- Create: `mcp/src/container-client.js`
- Create: `mcp/src/container-client.test.mjs`
- Modify: `mcp/src/index.js`
- Modify: `mcp/src/task-schema.js`
- Modify: `mcp/wrangler.jsonc`
- Modify: `mcp/package.json`

**Interfaces:**
- Consumes: downloaded reference, model-provided hints, `env.AI`, and `env.RENDERER`.
- Produces: passing bytes/report or `ArtifactValidationError` with exact stage and gates.

- [ ] **Step 1: Write failing orchestration tests**

Assert the reference bytes are actually downloaded, vision receives the image, hints cannot overwrite measured boxes, container receives the validated scene, one correction is attempted only for correctable geometry/style failures, and no artifact is stored after two failures.

- [ ] **Step 2: Run them and observe failure**

Run: `cd mcp && node --test src/scene-graph.test.mjs src/container-client.test.mjs`

Expected: FAIL because both modules are absent.

- [ ] **Step 3: Implement structured vision extraction**

Call the Workers AI vision binding with the reference bytes, a generic scene-graph JSON schema, temperature zero, and bounded tokens. Parse strictly, reject missing confidence/evidence, and merge only non-geometric user hints.

- [ ] **Step 4: Implement the container client**

Send scene/reference multipart data to the named container binding, enforce timeout and response size, and convert the report into the existing MCP success/failure contract.

- [ ] **Step 5: Replace task-only rendering in `execute`**

Call `downloadReference`, extract/validate the scene graph, call the container, apply at most one correction using measured hints, store only passing bytes, and return the existing resource link. Preserve tool name and OAuth behavior.

- [ ] **Step 6: Configure bindings**

Add Workers AI binding `AI`, Container binding `RENDERER`, its Durable Object migration, and the container image path. Add `@cloudflare/containers`.

- [ ] **Step 7: Verify and commit**

Run:

```bash
cd mcp
npm test
npx wrangler deploy --dry-run --outdir /tmp/artifact-mimicry-fidelity-dry-run
```

Commit: `Orchestrate reference-aware fidelity rendering`

### Task 5: Prove regressions and deploy the existing service

**Files:**
- Create: `container/tests/test_real_regressions.py`
- Modify: `.github/workflows/deploy-mcp.yml`
- Modify: `README.md`

**Interfaces:**
- Produces: one deployment containing the Worker and renderer container.

- [ ] **Step 1: Write real regression tests**

Run the capsule timetable, meeting grid, LTR poster, and mixed-direction page through the same generic pipeline. Assert visible capsule geometry for the first; visible grid borders, dark text, aligned participant columns, and non-emoji portrait/image objects for the second; preserved LTR hierarchy for the third; and independently correct paragraph direction for the fourth.

- [ ] **Step 2: Add deliberately broken real variants**

Generate mutations from scene graphs rather than hard-coded templates: remove strokes, invert contrast, offset one group, collapse gaps, replace images with emoji text, and flatten the page. Assert each mutation fails.

- [ ] **Step 3: Run local end-to-end verification**

Run:

```bash
docker build -t artifact-mimicry-renderer:test container
docker run --rm artifact-mimicry-renderer:test pytest -q
cd mcp
npm test
npx wrangler deploy --dry-run --outdir /tmp/artifact-mimicry-final-dry-run
```

- [ ] **Step 4: Extend GitHub deployment**

Build and test the container before deployment, deploy the Worker/container through Wrangler, and emit commit SHA, image digest, Worker version, and test totals.

- [ ] **Step 5: Deploy and inspect**

Push `main`, dispatch `deploy-mcp.yml`, wait for success, verify the existing root/OAuth/MCP endpoints, invoke the existing connector once with the meeting-grid reference, download the DOCX, reopen/render it independently, and compare its report with the source.

- [ ] **Step 6: Commit final documentation**

Document the fixed pipeline, supported editable/raster boundary, failure report, operating cost, and exact existing MCP URL.

Commit: `Deploy reference-agnostic Artifact Mimicry`
