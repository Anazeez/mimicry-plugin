import {
  ContainerRenderError,
  extractAndRenderInContainer,
} from "./container-client.js";
import { downloadReference } from "./reference.js";

const REQUIRED_EDITABILITY_GATES = [
  "G_PACKAGE_MEDIA_AUDIT",
  "G_NO_SOURCE_REFERENCE_EMBED",
  "G_NO_FULL_PAGE_RASTER",
  "G_VISIBLE_TEXT_NATIVE",
  "G_SCENE_NODE_COVERAGE",
  "G_NATIVE_OBJECT_RATIO",
  "G_OBJECT_EDITABILITY",
  "G_RASTER_JUSTIFICATION",
  "S_EDITABILITY",
];

const REQUIRED_EDITABILITY_METRICS = [
  "visible_text_native_ratio",
  "scene_node_coverage",
  "native_visible_area_ratio",
  "largest_unjustified_raster_ratio",
  "total_unjustified_raster_ratio",
  "source_reference_embedded",
  "monolithic_flattened_object",
];

export function hasMeasuredEditabilityEvidence(report) {
  return Boolean(
    report &&
      report.status === "PASS" &&
      report.editability &&
      report.editability.passed === true &&
      REQUIRED_EDITABILITY_GATES.every(
        (gate) => report.gates?.[gate] === true,
      ) &&
      REQUIRED_EDITABILITY_METRICS.every(
        (metric) =>
          Object.prototype.hasOwnProperty.call(report.editability, metric) &&
          report.editability[metric] !== null &&
          report.editability[metric] !== undefined,
      ),
  );
}

const incompleteEditabilityReport = (report) => ({
  status: "VALIDATION_INCOMPLETE",
  version: report?.version || null,
  gates: {
    ...(report?.gates || {}),
    G_PACKAGE_MEDIA_AUDIT: false,
    S_EDITABILITY: false,
  },
  editability: {
    ...(report?.editability || {}),
    passed: false,
  },
  findings: [
    {
      gate: "G_PACKAGE_MEDIA_AUDIT",
      measured: {
        complete_measured_editability_evidence: false,
      },
      required: {
        complete_measured_editability_evidence: true,
      },
      node_ids: [],
    },
  ],
});

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
    throw new ContainerRenderError(
      "Artifact Mimicry validation failed. No editable artifact was generated.",
      result?.report || null,
      "FIDELITY_FAILED",
    );
  }
  if (!hasMeasuredEditabilityEvidence(result.report)) {
    throw new ContainerRenderError(
      "Artifact Reconstructor validation is incomplete. No editable artifact was generated.",
      incompleteEditabilityReport(result.report),
      "VALIDATION_INCOMPLETE",
    );
  }
  if (typeof onArtifact === "function") onArtifact(result);
  return result;
}
