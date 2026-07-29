import assert from "node:assert/strict";
import test from "node:test";
import { z } from "zod";

import { mimicryHintsInputSchema } from "./task-schema.js";

test("advertises optional non-geometric hints rather than requiring model-authored shapes", () => {
  const schema = z.toJSONSchema(mimicryHintsInputSchema);

  assert.equal(schema.required, undefined);
  assert.ok(schema.properties.instructions);
  assert.ok(schema.properties.language);
  assert.ok(schema.properties.replacement_text);
  assert.equal(schema.properties.elements, undefined);
  assert.equal(schema.properties.page, undefined);
});

test("accepts an empty hint object because the reference controls geometry", () => {
  assert.equal(mimicryHintsInputSchema.safeParse({}).success, true);
});

test("accepts text replacements but strips attempted geometry overrides", () => {
  const result = mimicryHintsInputSchema.parse({
    language: "ar",
    replacement_text: { title: "اجتماع يومي" },
    bbox: [0, 0, 1, 1],
    elements: [{ id: "title", x: 0 }]
  });

  assert.deepEqual(result, {
    language: "ar",
    replacement_text: { title: "اجتماع يومي" }
  });
});
