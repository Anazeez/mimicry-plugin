import assert from "node:assert/strict";
import test from "node:test";

import {
  artifactJobPath,
  isArtifactJobId,
  jobStorageKey,
  withWorkflowStatus,
} from "./job-capability.js";

const JOB_ID = "17ddc4c7-52e5-4ee1-9965-937ee381472f";

test("job capability accepts only canonical UUID job identifiers", () => {
  assert.equal(isArtifactJobId(JOB_ID), true);
  assert.equal(isArtifactJobId("../oauth"), false);
  assert.equal(isArtifactJobId("17ddc4c7-52e5-4ee1-9965-937ee381472"), false);
});

test("job capability uses isolated storage and public paths", () => {
  assert.equal(jobStorageKey(JOB_ID), `job:${JOB_ID}`);
  assert.equal(artifactJobPath(JOB_ID), `/jobs/${JOB_ID}`);
  assert.throws(() => jobStorageKey("../oauth"), /invalid artifact job id/);
});

test("processing job status includes the durable workflow state", () => {
  assert.deepEqual(
    withWorkflowStatus(
      { status: "PROCESSING", created_at: "2026-07-29T00:00:00.000Z" },
      { status: "running" },
    ),
    {
      status: "PROCESSING",
      created_at: "2026-07-29T00:00:00.000Z",
      workflow_status: "running",
    },
  );
});
