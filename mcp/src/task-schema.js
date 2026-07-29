import { z } from "zod";

const normalizedCoordinate = z
  .number()
  .min(0)
  .max(1)
  .describe("Normalized page coordinate from 0 to 1.");

const positiveNormalizedExtent = z
  .number()
  .gt(0)
  .max(1)
  .describe("Normalized page width or height greater than 0 and at most 1.");

export const mimicryElementInputSchema = z
  .object({
    id: z
      .string()
      .min(1)
      .describe("Unique stable name for this independently editable Word object."),
    type: z
      .enum(["roundRect", "rect", "ellipse", "parallelogram", "text"])
      .describe(
        "Native editable primitive. Decompose icons and avatars into multiple supported primitives.",
      ),
    x: normalizedCoordinate.describe("Left edge as a fraction of page width."),
    y: normalizedCoordinate.describe("Top edge as a fraction of page height."),
    w: positiveNormalizedExtent.describe("Width as a fraction of page width."),
    h: positiveNormalizedExtent.describe("Height as a fraction of page height."),
    editable: z
      .literal(true)
      .describe("Must be true; every supplied object is independently editable."),
    text: z.string().optional().describe("Editable text contained by this shape."),
    fill: z
      .string()
      .nullable()
      .optional()
      .describe("Six-digit hex fill color, or null for no fill."),
    text_color: z
      .string()
      .optional()
      .describe("Six-digit hex color for editable text."),
    font: z.string().optional().describe("Word font family."),
    font_size_pt: z.number().gt(0).optional().describe("Font size in points."),
    bold: z.boolean().optional(),
    rtl: z
      .boolean()
      .optional()
      .describe("True when the shape text uses right-to-left direction."),
  })
  .describe("One independently editable native Word shape or text object.");

export const mimicryTaskInputSchema = z
  .object({
    task: z.literal("artifact_mimicry").optional(),
    output: z
      .object({
        format: z.literal("docx"),
        artifact_kind: z.literal("editable_template"),
        editable: z.literal(true),
      })
      .optional(),
    page: z
      .object({
        width_in: z.number().gt(0).describe("Word page width in inches."),
        height_in: z.number().gt(0).describe("Word page height in inches."),
      })
      .describe("Target Word page geometry."),
    elements: z
      .array(mimicryElementInputSchema)
      .min(1)
      .describe(
        "Required native editable decomposition. Include every visible text box, rounded shape, icon primitive, avatar primitive, line-like rectangle, and background region.",
      ),
    validation: z
      .record(z.string(), z.unknown())
      .optional()
      .describe("Optional fail-closed structural expectations."),
  })
  .describe(
    "Complete editable Word reconstruction task. The reference image alone is insufficient; supply at least one native editable element.",
  );
