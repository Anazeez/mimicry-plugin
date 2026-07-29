import { renderWithOneCorrection } from "./container-client.js";
import { downloadReference } from "./reference.js";
import { correctSceneGraph, extractSceneGraph } from "./scene-graph.js";

export async function executeReferencePipeline({
  referenceFile,
  hints = {},
  ai,
  renderer,
  downloadReferenceImpl = downloadReference,
  extractSceneGraphImpl = extractSceneGraph,
  renderWithOneCorrectionImpl = renderWithOneCorrection,
  correctSceneGraphImpl = correctSceneGraph,
  onArtifact
}) {
  const reference = await downloadReferenceImpl(referenceFile);
  const scene = await extractSceneGraphImpl({ ai, reference, hints });
  const result = await renderWithOneCorrectionImpl({
    renderer,
    scene,
    reference,
    correctScene: (current, correctionHints) =>
      correctSceneGraphImpl({
        ai,
        reference,
        scene: current,
        correctionHints
      })
  });
  if (result?.report?.status !== "PASS" || !result?.bytes) {
    throw new Error(
      "Artifact Mimicry validation failed. No editable artifact was generated."
    );
  }
  if (typeof onArtifact === "function") onArtifact(result);
  return result;
}
