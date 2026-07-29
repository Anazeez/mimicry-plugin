export async function launchArtifactWorkflow(binding, jobId, payload) {
  if (!binding?.create) throw new Error("artifact workflow binding unavailable");
  const instance = await binding.create({ id: jobId, params: payload });
  if (instance?.id !== jobId) {
    throw new Error("artifact workflow returned an unexpected instance id");
  }
  return instance;
}
