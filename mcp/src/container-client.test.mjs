import assert from "node:assert/strict";
import test from "node:test";
import { zipSync, strToU8 } from "fflate";
import {
  ContainerRenderError,
  extractAndRenderInContainer
} from "./container-client.js";

const reference = {
  bytes: new Uint8Array([0x89, 0x50, 0x4e, 0x47]),
  mimeType: "image/png",
  filename: "reference.png",
  digest: "abc"
};
const scene = {
  version: "scene-graph.v1",
  page: { width: 297, height: 210, orientation: "landscape" },
  nodes: [],
  constraints: []
};

test("sends only reference and hints to deterministic container extraction", async () => {
  let request;
  const archive = zipSync({
    "artifact.docx": new Uint8Array([0x50, 0x4b, 0x03, 0x04]),
    "manifest.json": strToU8(
      JSON.stringify({ fidelity: { status: "PASS", gates: { S_EDITABILITY: true } } })
    )
  });
  const renderer = {
    async fetch(input) {
      request = input;
      return new Response(archive, {
        status: 200,
        headers: { "content-type": "application/zip" }
      });
    }
  };

  const result = await extractAndRenderInContainer({
    renderer,
    reference,
    hints: { language: "ar" }
  });
  assert.equal(new URL(request.url).pathname, "/extract-render");
  assert.equal(request.method, "POST");
  const form = await request.formData();
  assert.equal(form.get("scene"), null);
  assert.deepEqual(JSON.parse(await form.get("hints").text()), { language: "ar" });
  assert.deepEqual(
    Array.from(new Uint8Array(await form.get("reference").arrayBuffer())),
    Array.from(reference.bytes)
  );
  assert.deepEqual(Array.from(result.bytes), [0x50, 0x4b, 0x03, 0x04]);
  assert.equal(result.report.status, "PASS");
});

test("returns the exact independent validation report on fail-closed response", async () => {
  const report = {
    status: "FAIL",
    findings: [{ gate: "G_ALIGNMENT", node_ids: ["grid"] }],
    correction_hints: [{ gate: "G_ALIGNMENT", node_ids: ["grid"] }]
  };
  const renderer = {
    async fetch() {
      return Response.json(
        { code: "FIDELITY_FAILED", validation: report },
        { status: 422 }
      );
    }
  };
  await assert.rejects(
    extractAndRenderInContainer({ renderer, reference, hints: {} }),
    (error) => {
      assert.ok(error instanceof ContainerRenderError);
      assert.deepEqual(error.report, report);
      return true;
    }
  );
});

test("retains a failed render preview for owner diagnostics", async () => {
  const preview = new Uint8Array([0xff, 0xd8, 0xff]);
  const renderer = {
    async fetch() {
      return Response.json(
        {
          code: "FIDELITY_FAILED",
          validation: { status: "FAIL", findings: [] },
          debug_preview_base64: Buffer.from(preview).toString("base64"),
          debug_preview_mime: "image/jpeg"
        },
        { status: 422 }
      );
    }
  };
  await assert.rejects(
    extractAndRenderInContainer({ renderer, reference, hints: {} }),
    (error) => {
      assert.deepEqual(Array.from(error.debugPreview), Array.from(preview));
      assert.equal(error.debugPreviewMime, "image/jpeg");
      return true;
    }
  );
});
