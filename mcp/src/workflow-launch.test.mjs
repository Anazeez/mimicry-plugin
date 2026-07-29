import assert from "node:assert/strict";
import test from "node:test";

import {
  ARTIFACT_WORKFLOW_STEP_CONFIG,
  launchArtifactWorkflow,
} from "./workflow-launch.js";

test("uses a Cloudflare-valid bounded retry configuration", () => {
  assert.deepEqual(ARTIFACT_WORKFLOW_STEP_CONFIG, {
    retries: {
      limit: 1,
      delay: "1 second",
      backoff: "linear",
    },
    timeout: "15 minutes",
  });
});

test("launches one durable workflow using the artifact job id", async () => {
  const calls = [];
  const binding = {
    async create(options) {
      calls.push(options);
      return { id: options.id };
    },
  };
  const payload = { filename: "verified.docx" };

  const instance = await launchArtifactWorkflow(
    binding,
    "5db2490c-1b56-4420-b4eb-88b102f74a69",
    payload,
  );

  assert.equal(instance.id, "5db2490c-1b56-4420-b4eb-88b102f74a69");
  assert.deepEqual(calls, [
    {
      id: "5db2490c-1b56-4420-b4eb-88b102f74a69",
      params: payload,
    },
  ]);
});
