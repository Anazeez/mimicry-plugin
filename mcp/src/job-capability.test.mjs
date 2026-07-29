import assert from "node:assert/strict";
import test from "node:test";

import {
  artifactJobPath,
  isArtifactJobId,
  jobStorageKey,
  normalizeArtifactJobFailure,
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
      {
        status: "errored",
        error: { name: "Error", message: "renderer binding unavailable" },
      },
    ),
    {
      status: "PROCESSING",
      created_at: "2026-07-29T00:00:00.000Z",
      workflow_status: "errored",
      workflow_error: {
        name: "Error",
        message: "renderer binding unavailable",
      },
    },
  );
});

test("failed jobs always expose a structured fail-closed validation report", () => {
  assert.deepEqual(
    normalizeArtifactJobFailure({
      code: "RENDER_FAILED",
      message: "container response did not include validation evidence",
    }),
    {
      status: "FAILED",
      error_code: "VALIDATION_INCOMPLETE",
      message: "container response did not include validation evidence",
      diagnostic: "RENDER_FAILED",
      validation_report: {
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
              error_code: "RENDER_FAILED",
            },
            required: {
              validation_evidence_available: true,
            },
            node_ids: [],
          },
        ],
      },
    },
  );
});

test("failed jobs preserve measured editability evidence and status", () => {
  const report = {
    status: "EDITABILITY_FAILED",
    gates: { G_NO_FULL_PAGE_RASTER: false, S_EDITABILITY: false },
    editability: { passed: false, largest_unjustified_raster_ratio: 0.97 },
  };
  const result = normalizeArtifactJobFailure({
    code: "EDITABILITY_FAILED",
    message: "visible design is primarily rasterized",
    diagnostic: "validator rejected the output",
    report,
  });
  assert.equal(result.error_code, "EDITABILITY_FAILED");
  assert.strictEqual(result.validation_report, report);
  assert.equal(result.diagnostic, "validator rejected the output");
});
