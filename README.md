# Artifact Mimicry

Artifact Mimicry is a skills-and-MCP plugin for ChatGPT and Codex. It recreates
screenshots, photos, PDFs, Word, PowerPoint, Excel, and Google Workspace
templates as native editable artifacts while preserving their visual system.
It supports LTR, RTL, and mixed-direction layouts.

The `artifact_mimicry.execute` MCP tool is the mandatory rendering path. Version
1.0 downloads the supplied visual reference, extracts a generic scene graph
with Workers AI, builds native editable Word objects through LibreOffice in a
Cloudflare Container, reopens the saved DOCX, renders it, and returns it only
after independent structural, geometric, contrast, and visual-fidelity gates
pass. The runtime permits at most one evidence-driven correction. It never
returns a previous artifact, a flattened reference image, or a manually
approximated fallback.

The executable MCP is deployed independently at:

`https://artifact-mimicry-mcp.izeesub.workers.dev/mcp`

Its private operating mode uses ChatGPT Web Developer Mode with GitHub OAuth,
an explicit owner allowlist, S256 PKCE, and the single `artifact:render` scope.
The renderer, generated artifacts, and permissions remain independent from
Governed Jcode and every other MCP service.

## Runtime boundary

- MCP and OAuth: Cloudflare Worker
- Reference analysis: Workers AI vision
- Native DOCX rendering: Cloudflare Container running LibreOffice UNO
- Validation: saved-file reopen, PDF/PNG render, actual object geometry,
  relationships, border coverage, contrast, edge structure, palette, OCR, and
  structural editability
- Storage: only validated DOCX output, unlisted and expiring after 24 hours

The renderer is reference-agnostic. Real incident files are retained only as
regression tests; production behavior contains no template-specific layout,
fixture name, timetable rule, or meeting-grid rule.

## Release verification

The deployment workflow blocks release unless both suites pass:

1. Worker/MCP routing, OAuth, reference-boundary, scene-graph, correction, and
   fail-closed tests.
2. The exact Linux/AMD64 production container tests, including real
   LibreOffice creation, reopen, rasterization, geometry inspection, visual
   validation, and rejection of the supplied failed DOCX.
