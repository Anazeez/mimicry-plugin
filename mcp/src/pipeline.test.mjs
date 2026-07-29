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

test("downloads the reference, extracts its scene, and returns only a passing artifact", async () => {
  const events = [];
  const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
  const scene = { version: "scene-graph.v1", page: {}, nodes: [], constraints: [] };
  const output = new Uint8Array([0x50, 0x4b]);
  const result = await executeReferencePipeline({
    referenceFile,
    hints: { language: "ar" },
    ai: {},
    renderer: {},
    downloadReferenceImpl: async (value) => {
      events.push(["download", value]);
      return { bytes, mimeType: "image/png", filename: "reference.png", digest: "abc" };
    },
    extractSceneGraphImpl: async (value) => {
      events.push(["extract", value.reference.bytes]);
      return scene;
    },
    renderWithOneCorrectionImpl: async (value) => {
      events.push(["render", value.scene]);
      return { bytes: output, report: { status: "PASS", gates: { S_EDITABILITY: true } } };
    }
  });

  assert.deepEqual(events.map(([name]) => name), ["download", "extract", "render"]);
  assert.strictEqual(events[1][1], bytes);
  assert.strictEqual(events[2][1], scene);
  assert.strictEqual(result.bytes, output);
  assert.equal(result.report.status, "PASS");
});

test("warms the renderer concurrently before scene extraction completes", async () => {
  const events = [];
  let releaseWarmup;
  const renderer = {
    fetch() {
      events.push("warm-start");
      return new Promise((resolve) => {
        releaseWarmup = () => {
          events.push("warm-ready");
          resolve(new Response("ok"));
        };
      });
    }
  };
  const resultPromise = executeReferencePipeline({
    referenceFile: { download_url: "https://example.com/reference.png" },
    ai: {},
    renderer,
    downloadReferenceImpl: async () => {
      events.push("download");
      return { bytes: new Uint8Array([1]), mimeType: "image/png" };
    },
    extractSceneGraphImpl: async () => {
      events.push("extract");
      releaseWarmup();
      return { version: "scene-graph.v1" };
    },
    renderWithOneCorrectionImpl: async () => {
      events.push("render");
      return {
        bytes: new Uint8Array([2]),
        report: { status: "PASS" }
      };
    }
  });
  await resultPromise;
  assert.deepEqual(events, [
    "warm-start",
    "download",
    "extract",
    "warm-ready",
    "render"
  ]);
});

test("propagates the second fail-closed result and returns no artifact bytes", async () => {
  let artifacts = 0;
  await assert.rejects(
    executeReferencePipeline({
      referenceFile,
      ai: {},
      renderer: {},
      downloadReferenceImpl: async () => ({
        bytes: new Uint8Array([1]),
        mimeType: "image/png",
        filename: "reference.png",
        digest: "abc"
      }),
      extractSceneGraphImpl: async () => ({
        version: "scene-graph.v1",
        page: {},
        nodes: [],
        constraints: []
      }),
      renderWithOneCorrectionImpl: async () => {
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
