import assert from "node:assert/strict";
import test from "node:test";

import { ReferenceInputError, downloadReference } from "./reference.js";

const PNG = Uint8Array.from([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x00
]);

const descriptor = {
  download_url: "https://files.openai.example/reference.png?signature=secret",
  file_id: "file_reference",
  file_name: "reference.png",
  mime_type: "image/png"
};

test("downloads a bounded reference and returns detected metadata without retaining its signed URL", async () => {
  const result = await downloadReference(descriptor, async () =>
    new Response(PNG, {
      headers: {
        "content-type": "image/png",
        "content-length": String(PNG.byteLength)
      }
    })
  );

  assert.deepEqual(result.bytes, PNG);
  assert.equal(result.mimeType, "image/png");
  assert.equal(result.filename, "reference.png");
  assert.match(result.digest, /^[a-f0-9]{64}$/);
  assert.equal("downloadUrl" in result, false);
});

test("rejects an insecure source URL before fetching", async () => {
  let called = false;

  await assert.rejects(
    () =>
      downloadReference(
        { ...descriptor, download_url: "http://files.example/reference.png" },
        async () => {
          called = true;
          return new Response(PNG);
        }
      ),
    (error) =>
      error instanceof ReferenceInputError && error.code === "REF_HTTPS_REQUIRED"
  );
  assert.equal(called, false);
});

test("rejects a redirect to a private address", async () => {
  await assert.rejects(
    () =>
      downloadReference(descriptor, async () =>
        new Response(null, {
          status: 302,
          headers: { location: "https://127.0.0.1/private.png" }
        })
      ),
    (error) =>
      error instanceof ReferenceInputError && error.code === "REF_PRIVATE_ADDRESS"
  );
});

test("rejects an oversized response from headers without reading its body", async () => {
  await assert.rejects(
    () =>
      downloadReference(descriptor, async () =>
        new Response(PNG, {
          headers: { "content-length": String(20 * 1024 * 1024 + 1) }
        })
      ),
    (error) =>
      error instanceof ReferenceInputError && error.code === "REF_TOO_LARGE"
  );
});

test("rejects declared MIME that disagrees with reference magic bytes", async () => {
  await assert.rejects(
    () =>
      downloadReference(
        { ...descriptor, mime_type: "image/jpeg" },
        async () => new Response(PNG, { headers: { "content-type": "image/jpeg" } })
      ),
    (error) =>
      error instanceof ReferenceInputError && error.code === "REF_MIME_MISMATCH"
  );
});
