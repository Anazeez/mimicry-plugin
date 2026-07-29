import { z } from "zod";

export const mimicryHintsInputSchema = z
  .object({
    instructions: z
      .string()
      .max(2000)
      .optional()
      .describe(
        "Optional content or format guidance. It cannot override measured reference geometry."
      ),
    language: z
      .string()
      .max(32)
      .optional()
      .describe("Optional preferred document language or locale."),
    replacement_text: z
      .record(z.string(), z.string().max(5000))
      .optional()
      .describe(
        "Optional editable text replacements keyed by measured scene node ID."
      ),
    job_id: z
      .string()
      .uuid()
      .optional()
      .describe(
        "Backward-compatible polling field for connector sessions that have not refreshed to expose await_result."
      )
  })
  .strip()
  .describe(
    "Optional non-geometric guidance. The attached reference controls page geometry, visual primitives, spacing, colors, typography, and direction."
  );

// Retained as an alias for older installed connector drafts. It no longer
// accepts or requires a model-authored page decomposition.
export const mimicryTaskInputSchema = mimicryHintsInputSchema;

export const resolveMimicryHints = ({ hints, task } = {}) => {
  if (hints && typeof hints === "object") {
    return mimicryHintsInputSchema.parse(hints);
  }
  if (task && typeof task === "object") {
    return mimicryHintsInputSchema.parse(task);
  }
  return {};
};
