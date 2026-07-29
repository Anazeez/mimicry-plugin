import { strFromU8, unzipSync } from "fflate";

const MAX_RESPONSE_BYTES = 40 * 1024 * 1024;
const CORRECTABLE_GATES = new Set([
  "G_ALIGNMENT",
  "G_RELATIONSHIPS",
  "G_BORDER_CONTINUITY",
  "V_CONTRAST",
  "V_EDGE_SIMILARITY",
  "V_PALETTE",
  "V_STRUCTURE"
]);

export class ContainerRenderError extends Error {
  constructor(message, report = null, code = "RENDER_FAILED") {
    super(message);
    this.name = "ContainerRenderError";
    this.code = code;
    this.report = report;
    const findings = Array.isArray(report?.findings) ? report.findings : [];
    this.correctable =
      findings.length > 0 &&
      findings.every((finding) => CORRECTABLE_GATES.has(finding.gate));
  }
}

const withTimeout = async (promise, controller, timeoutMs) => {
  const timer = setTimeout(() => controller.abort("renderer timeout"), timeoutMs);
  try {
    return await promise;
  } finally {
    clearTimeout(timer);
  }
};

export async function renderInContainer({
  renderer,
  scene,
  reference,
  timeoutMs = 180_000
}) {
  if (!renderer?.fetch) {
    throw new ContainerRenderError(
      "Artifact Mimicry renderer unavailable. No editable artifact was generated.",
      null,
      "RENDERER_UNAVAILABLE"
    );
  }
  const form = new FormData();
  form.set(
    "scene",
    new Blob([JSON.stringify(scene)], { type: "application/json" }),
    "scene.json"
  );
  form.set(
    "reference",
    new Blob([reference.bytes], { type: reference.mimeType }),
    reference.filename || "reference.bin"
  );
  const controller = new AbortController();
  let response;
  try {
    response = await withTimeout(
      renderer.fetch(
        new Request("http://renderer/render", {
          method: "POST",
          body: form,
          signal: controller.signal
        })
      ),
      controller,
      timeoutMs
    );
  } catch (error) {
    if (error instanceof ContainerRenderError) throw error;
    throw new ContainerRenderError(
      "Artifact Mimicry renderer unavailable. No editable artifact was generated.",
      null,
      "RENDERER_UNAVAILABLE"
    );
  }
  if (!response.ok) {
    let payload = {};
    try {
      payload = await response.json();
    } catch {
      // A non-JSON renderer error is intentionally reduced to a stable failure.
    }
    throw new ContainerRenderError(
      payload.message || "Artifact Mimicry validation failed. No editable artifact was generated.",
      payload.validation || null,
      payload.code || "RENDER_FAILED"
    );
  }
  const declared = Number(response.headers.get("content-length") || 0);
  if (declared > MAX_RESPONSE_BYTES) {
    throw new ContainerRenderError("Renderer response exceeds the artifact limit");
  }
  const packed = new Uint8Array(await response.arrayBuffer());
  if (packed.byteLength > MAX_RESPONSE_BYTES) {
    throw new ContainerRenderError("Renderer response exceeds the artifact limit");
  }
  let files;
  try {
    files = unzipSync(packed);
  } catch {
    throw new ContainerRenderError("Renderer returned an invalid artifact bundle");
  }
  const bytes = files["artifact.docx"];
  const manifestBytes = files["manifest.json"];
  if (!bytes || !manifestBytes) {
    throw new ContainerRenderError("Renderer bundle is incomplete");
  }
  const manifest = JSON.parse(strFromU8(manifestBytes));
  if (manifest?.fidelity?.status !== "PASS") {
    throw new ContainerRenderError(
      "Artifact Mimicry validation failed. No editable artifact was generated.",
      manifest?.fidelity || null,
      "FIDELITY_FAILED"
    );
  }
  return { bytes, report: manifest.fidelity, manifest };
}

export async function renderWithOneCorrection({
  scene,
  reference,
  renderer,
  renderOnce = renderInContainer,
  correctScene
}) {
  try {
    return await renderOnce({ renderer, scene, reference });
  } catch (error) {
    if (
      !(error instanceof ContainerRenderError) ||
      !error.correctable ||
      typeof correctScene !== "function"
    ) {
      throw error;
    }
    const corrected = await correctScene(
      scene,
      error.report?.correction_hints || []
    );
    return renderOnce({ renderer, scene: corrected, reference });
  }
}
