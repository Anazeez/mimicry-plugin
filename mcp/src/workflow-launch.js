export const ARTIFACT_WORKFLOW_STEP_CONFIG = Object.freeze({
  retries: Object.freeze({
    limit: 1,
    delay: "1 second",
    backoff: "linear",
  }),
  timeout: "15 minutes",
});

export async function launchArtifactWorkflow(binding, jobId, payload) {
  if (!binding?.create) throw new Error("artifact workflow binding unavailable");
  const instance = await binding.create({ id: jobId, params: payload });
  if (instance?.id !== jobId) {
    throw new Error("artifact workflow returned an unexpected instance id");
  }
  return instance;
}
