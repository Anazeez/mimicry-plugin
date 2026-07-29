import { extractAndRenderInContainer } from "./container-client.js";
import { downloadReference } from "./reference.js";

export async function executeReferencePipeline({
  referenceFile,
  hints = {},
  renderer,
  downloadReferenceImpl = downloadReference,
  extractAndRenderImpl = extractAndRenderInContainer,
  onArtifact
}) {
  const reference = await downloadReferenceImpl(referenceFile);
  const result = await extractAndRenderImpl({
    renderer,
    reference,
    hints
  });
  if (result?.report?.status !== "PASS" || !result?.bytes) {
    throw new Error(
      "Artifact Mimicry validation failed. No editable artifact was generated."
    );
  }
  if (typeof onArtifact === "function") onArtifact(result);
  return result;
}
