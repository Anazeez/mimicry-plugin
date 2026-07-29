import assert from "node:assert/strict";
import test from "node:test";

import { launchArtifactWorkflow } from "./workflow-launch.js";

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
