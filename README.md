# Artifact Mimicry

Artifact Mimicry is a skills-and-MCP plugin for ChatGPT and Codex. It recreates
screenshots, photos, PDFs, Word, PowerPoint, Excel, and Google Workspace
templates as native editable artifacts while preserving their visual system.
It supports LTR, RTL, and mixed-direction layouts.

The `artifact_mimicry.execute` MCP tool is the mandatory rendering path. It
creates and structurally validates a fresh editable DOCX; the skill forbids
manual reconstruction or reuse when the tool is unavailable.

The executable MCP is deployed independently at:

`https://artifact-mimicry-mcp.izeesub.workers.dev/mcp`

Its private operating mode uses ChatGPT Web Developer Mode with GitHub OAuth,
an explicit owner allowlist, S256 PKCE, and the single `artifact:render` scope.
The renderer, generated artifacts, and permissions remain independent from
Governed Jcode and every other MCP service.
