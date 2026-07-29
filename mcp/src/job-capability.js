const ARTIFACT_JOB_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const isArtifactJobId = (value) =>
  typeof value === "string" && ARTIFACT_JOB_ID.test(value);

export const jobStorageKey = (jobId) => {
  if (!isArtifactJobId(jobId)) throw new Error("invalid artifact job id");
  return `job:${jobId}`;
};

export const artifactJobPath = (jobId) => {
  if (!isArtifactJobId(jobId)) throw new Error("invalid artifact job id");
  return `/jobs/${jobId}`;
};

const EVIDENCE_BACKED_FAILURE_STATUSES = new Set([
  "EDITABILITY_FAILED",
  "FIDELITY_FAILED",
  "VALIDATION_INCOMPLETE",
  "PACKAGE_INVALID",
  "GENERATION_FAILED",
  "UNSUPPORTED_NATIVE_RECONSTRUCTION",
  "RASTER_FALLBACK_PROHIBITED",
]);

const incompleteValidationReport = (errorCode) => ({
  status: "VALIDATION_INCOMPLETE",
  version: null,
  gates: {
    G_PACKAGE_MEDIA_AUDIT: false,
    S_EDITABILITY: false,
  },
  editability: {
    passed: false,
    evidence_available: false,
  },
  findings: [
    {
      gate: "G_PACKAGE_MEDIA_AUDIT",
      measured: {
        validation_evidence_available: false,
        error_code: String(errorCode || "UNKNOWN_FAILURE"),
      },
      required: {
        validation_evidence_available: true,
      },
      node_ids: [],
    },
  ],
});

export const normalizeArtifactJobFailure = ({
  code,
  message,
  diagnostic,
  report,
} = {}) => {
  const hasEvidence = report && typeof report === "object";
  const reportedStatus =
    hasEvidence && EVIDENCE_BACKED_FAILURE_STATUSES.has(report.status)
      ? report.status
      : hasEvidence && EVIDENCE_BACKED_FAILURE_STATUSES.has(code)
        ? code
        : "VALIDATION_INCOMPLETE";
  return {
    status: "FAILED",
    error_code: reportedStatus,
    message: String(
      message ||
        "Artifact Reconstructor validation did not produce a usable artifact.",
    ),
    diagnostic: String(diagnostic || code || "UNKNOWN_FAILURE"),
    validation_report: hasEvidence
      ? report
      : incompleteValidationReport(code),
  };
};

export const withWorkflowStatus = (record, workflow) => {
  const error =
    workflow?.error && typeof workflow.error === "object"
      ? {
          name: String(workflow.error.name || "Error").slice(0, 80),
          message: String(workflow.error.message || "unknown workflow error")
            .replace(/https?:\/\/\S+/gi, "[url]")
            .replace(/[A-Za-z0-9_-]{32,}/g, "[redacted]")
            .slice(0, 240),
        }
      : null;
  return {
    ...record,
    workflow_status:
      typeof workflow?.status === "string" ? workflow.status : "unknown",
    ...(error ? { workflow_error: error } : {}),
  };
};
