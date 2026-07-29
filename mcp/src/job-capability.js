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
