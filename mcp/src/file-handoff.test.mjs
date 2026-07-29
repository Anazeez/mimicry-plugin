import assert from "node:assert/strict";
import test from "node:test";

import {
  EXECUTE_TOOL_META,
  referenceFileSchema,
} from "./file-handoff.js";

test("execute declares the reference upload rewrite path", () => {
  assert.deepEqual(EXECUTE_TOOL_META["openai/fileParams"], ["reference_file"]);
});

test("reference upload accepts the canonical proxied file payload", () => {
  const parsed = referenceFileSchema.parse({
    download_url: "https://files.example.test/reference.png",
    file_id: "file_123",
    mime_type: "image/png",
    file_name: "reference.png",
  });

  assert.equal(parsed.file_id, "file_123");
  assert.equal(parsed.download_url, "https://files.example.test/reference.png");
});

test("reference upload rejects legacy mounted path strings", () => {
  assert.throws(() => referenceFileSchema.parse("/mnt/data/reference.png"));
});
