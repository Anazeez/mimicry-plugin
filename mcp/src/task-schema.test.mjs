import assert from "node:assert/strict";
import test from "node:test";
import { z } from "zod";

import { mimicryTaskInputSchema } from "./task-schema.js";

test("advertises the native editable decomposition instead of an opaque task", () => {
  const schema = z.toJSONSchema(mimicryTaskInputSchema);

  assert.deepEqual(schema.required, ["page", "elements"]);
  assert.equal(schema.properties.elements.minItems, 1);
  assert.deepEqual(
    schema.properties.elements.items.required,
    ["id", "type", "x", "y", "w", "h", "editable"],
  );
});

test("rejects an empty task before the renderer is invoked", () => {
  const result = mimicryTaskInputSchema.safeParse({
    page: { width_in: 8.5, height_in: 11 },
    elements: [],
  });

  assert.equal(result.success, false);
  assert.equal(result.error.issues[0].path.join("."), "elements");
});

test("accepts a canonical editable native shape task", () => {
  const result = mimicryTaskInputSchema.safeParse({
    page: { width_in: 8.5, height_in: 11 },
    elements: [
      {
        id: "title",
        type: "roundRect",
        x: 0.1,
        y: 0.1,
        w: 0.8,
        h: 0.1,
        editable: true,
        text: "Editable title",
      },
    ],
  });

  assert.equal(result.success, true);
});
