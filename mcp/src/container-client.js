import { strFromU8, unzipSync } from "fflate";

const MAX_RESPONSE_BYTES = 40 * 1024 * 1024;
export class ContainerRenderError extends Error {
  constructor(
    message,
    report = null,
    code = "RENDER_FAILED",
    debugPreviewBase64 = null,
    debugPreviewMime = null,
    diagnostic = null
  ) {
    super(message);
    this.name = "ContainerRenderError";
    this.code = code;
    this.report = report;
    this.debugPreviewBase64 = debugPreviewBase64;
    this.debugPreviewMime = debugPreviewMime;
    this.diagnostic = diagnostic;
    this.debugPreview =
      typeof debugPreviewBase64 === "string" && debugPreviewBase64
        ? Uint8Array.from(atob(debugPreviewBase64), (character) =>
            character.charCodeAt(0)
          )
        : null;
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

const wait = (delayMs) =>
  delayMs > 0
    ? new Promise((resolve) => setTimeout(resolve, delayMs))
    : Promise.resolve();

export async function extractAndRenderInContainer({
  renderer,
  reference,
  hints = {},
  timeoutMs = 360_000,
  retryDelayMs = 5_000
}) {
  if (!renderer?.fetch) {
    throw new ContainerRenderError(
      "Artifact Reconstructor renderer unavailable. No editable artifact was generated.",
      null,
      "RENDERER_UNAVAILABLE"
    );
  }
  const buildRequest = (signal) => {
    const form = new FormData();
    form.set(
      "hints",
      new Blob([JSON.stringify(hints)], { type: "application/json" }),
      "hints.json"
    );
    form.set(
      "reference",
      new Blob([reference.bytes], { type: reference.mimeType }),
      reference.filename || "reference.bin"
    );
    return new Request("http://renderer/extract-render", {
      method: "POST",
      body: form,
      signal
    });
  };
  const startedAt = Date.now();
  let response;
  try {
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const controller = new AbortController();
      const remainingMs = Math.max(1, timeoutMs - (Date.now() - startedAt));
      response = await withTimeout(
        renderer.fetch(buildRequest(controller.signal)),
        controller,
        remainingMs
      );
      if (response.status !== 503 || attempt === 4) break;
      try {
        await response.body?.cancel();
      } catch {
        // The retry uses a fresh request body; body cancellation is best effort.
      }
      const delayMs = Math.min(
        retryDelayMs * 2 ** attempt,
        Math.max(0, timeoutMs - (Date.now() - startedAt))
      );
      await wait(delayMs);
    }
  } catch (error) {
    if (error instanceof ContainerRenderError) throw error;
    throw new ContainerRenderError(
      "Artifact Reconstructor renderer unavailable. No editable artifact was generated.",
      null,
      "RENDERER_UNAVAILABLE"
    );
  }
  if (!response.ok) {
    let payload = {};
    const responseText = await response.text();
    try {
      payload = JSON.parse(responseText);
    } catch {
      // A non-JSON renderer error is intentionally reduced to a stable failure.
    }
    const diagnostic =
      typeof payload.diagnostic === "string" && payload.diagnostic
        ? payload.diagnostic
        : `Renderer HTTP ${response.status} (${response.headers.get("content-type") || "unknown content type"})`;
    throw new ContainerRenderError(
      payload.message || "Artifact Reconstructor validation failed. No editable artifact was generated.",
      payload.validation || null,
      payload.code || "RENDER_FAILED",
      payload.debug_preview_base64 || null,
      payload.debug_preview_mime || null,
      diagnostic
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
      "Artifact Reconstructor validation failed. No editable artifact was generated.",
      manifest?.fidelity || null,
      "FIDELITY_FAILED"
    );
  }
  return { bytes, report: manifest.fidelity, manifest };
}
