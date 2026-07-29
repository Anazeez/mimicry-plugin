import assert from "node:assert/strict";
import test from "node:test";
import { executeReferencePipeline } from "./pipeline.js";
import { ContainerRenderError } from "./container-client.js";

const referenceFile = {
  download_url: "https://files.example/reference.png",
  file_id: "file-1",
  mime_type: "image/png",
  file_name: "reference.png"
};
const measuredPassReport = {
  status: "PASS",
  version: "fidelity-v2",
  gates: {
    G_PACKAGE_MEDIA_AUDIT: true,
    G_NO_SOURCE_REFERENCE_EMBED: true,
    G_NO_FULL_PAGE_RASTER: true,
    G_VISIBLE_TEXT_NATIVE: true,
    G_SCENE_NODE_COVERAGE: true,
    G_NATIVE_OBJECT_RATIO: true,
    G_OBJECT_EDITABILITY: true,
    G_RASTER_JUSTIFICATION: true,
    S_EDITABILITY: true,
  },
  editability: {
    passed: true,
    visible_text_native_ratio: 1,
    scene_node_coverage: 1,
    native_visible_area_ratio: 1,
    largest_unjustified_raster_ratio: 0,
    total_unjustified_raster_ratio: 0,
    source_reference_embedded: false,
    monolithic_flattened_object: false,
  },
};

test("downloads the reference and delegates deterministic extraction and rendering", async () => {
  const events = [];
  const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
  const output = new Uint8Array([0x50, 0x4b]);
  const result = await executeReferencePipeline({
    referenceFile,
    hints: { language: "ar" },
    renderer: {},
    downloadReferenceImpl: async (value) => {
      events.push(["download", value]);
      return { bytes, mimeType: "image/png", filename: "reference.png", digest: "abc" };
    },
    extractAndRenderImpl: async (value) => {
      events.push(["extract-render", value.reference.bytes, value.hints]);
      return { bytes: output, report: measuredPassReport };
    }
  });

  assert.deepEqual(events.map(([name]) => name), ["download", "extract-render"]);
  assert.strictEqual(events[1][1], bytes);
  assert.deepEqual(events[1][2], { language: "ar" });
  assert.strictEqual(result.bytes, output);
  assert.equal(result.report.status, "PASS");
});

test("propagates the second fail-closed result and returns no artifact bytes", async () => {
  let artifacts = 0;
  await assert.rejects(
    executeReferencePipeline({
      referenceFile,
      renderer: {},
      downloadReferenceImpl: async () => ({
        bytes: new Uint8Array([1]),
        mimeType: "image/png",
        filename: "reference.png",
        digest: "abc"
      }),
      extractAndRenderImpl: async () => {
        throw new ContainerRenderError("still failed", {
          status: "FAIL",
          findings: [{ gate: "G_ALIGNMENT", node_ids: ["grid"] }]
        });
      },
      onArtifact: () => {
        artifacts += 1;
      }
    }),
    ContainerRenderError
  );
  assert.equal(artifacts, 0);
});

test("rejects a bare editability boolean without measured package evidence", async () => {
  await assert.rejects(
    executeReferencePipeline({
      referenceFile,
      renderer: {},
      downloadReferenceImpl: async () => ({
        bytes: new Uint8Array([1]),
        mimeType: "image/png",
        filename: "reference.png",
        digest: "abc"
      }),
      extractAndRenderImpl: async () => ({
        bytes: new Uint8Array([0x50, 0x4b]),
        report: {
          status: "PASS",
          gates: { S_EDITABILITY: true }
        }
      })
    }),
    (error) => {
      assert.ok(error instanceof ContainerRenderError);
      assert.equal(error.code, "VALIDATION_INCOMPLETE");
      assert.equal(error.report.status, "VALIDATION_INCOMPLETE");
      return true;
    }
  );
});
