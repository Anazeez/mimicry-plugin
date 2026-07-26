# Artifact Mimicry

Artifact Mimicry is a skills-and-MCP plugin for ChatGPT and Codex. It recreates
screenshots, photos, PDFs, Word, PowerPoint, Excel, and Google Workspace
templates as native editable artifacts while preserving their visual system.
It supports LTR, RTL, and mixed-direction layouts.

The `artifact_mimicry.execute` MCP tool is the mandatory rendering path. It
creates and structurally validates a fresh editable DOCX; the skill forbids
manual reconstruction or reuse when the tool is unavailable.

The complete public-submission bundle is attached to the latest GitHub release.
