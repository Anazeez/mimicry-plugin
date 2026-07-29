import { z } from "zod";
import { jsonrepair } from "jsonrepair";

const nodeTypes = [
  "group",
  "text",
  "rectangle",
  "rounded_rectangle",
  "ellipse",
  "line",
  "polygon",
  "grid",
  "image"
];
const VISION_MODEL = "@cf/moonshotai/kimi-k2.6";
const constraintTypes = [
  "inside",
  "align_left",
  "align_right",
  "align_top",
  "align_bottom",
  "align_center_x",
  "align_center_y",
  "adjacent_x",
  "adjacent_y",
  "equal_width",
  "equal_height",
  "gap_x",
  "gap_y"
];
const nodeTypeAliases = new Map([
  ["page", "group"],
  ["document", "group"],
  ["canvas", "group"],
  ["artboard", "group"],
  ["layer", "group"],
  ["root", "group"],
  ["frame", "group"],
  ["container", "group"],
  ["section", "group"],
  ["header", "group"],
  ["footer", "group"],
  ["row", "group"],
  ["column", "group"],
  ["label", "text"],
  ["textbox", "text"],
  ["text_box", "text"],
  ["box", "rectangle"],
  ["rect", "rectangle"],
  ["cell", "rectangle"],
  ["border", "rectangle"],
  ["panel", "rectangle"],
  ["roundedrect", "rounded_rectangle"],
  ["rounded_rect", "rounded_rectangle"],
  ["capsule", "rounded_rectangle"],
  ["pill", "rounded_rectangle"],
  ["circle", "ellipse"],
  ["oval", "ellipse"],
  ["divider", "line"],
  ["table", "grid"],
  ["photo", "image"],
  ["portrait", "image"],
  ["avatar", "image"],
  ["icon", "image"],
  ["logo", "image"],
  ["symbol", "image"],
  ["badge", "image"],
  ["illustration", "image"],
  ["graphic", "image"]
]);
const hexColor = z.string().regex(/^#[0-9a-fA-F]{6}$/);
const bboxSchema = z
  .tuple([
    z.number().min(0).max(1),
    z.number().min(0).max(1),
    z.number().gt(0).max(1),
    z.number().gt(0).max(1)
  ])
  .refine(([x, y, width, height]) => x + width <= 1.000001 && y + height <= 1.000001);
const styleSchema = z.object({
  fill: hexColor.nullable(),
  stroke: hexColor.nullable(),
  stroke_width: z.number().min(0),
  corner_radius: z.number().min(0),
  opacity: z.number().min(0).max(1)
});
const textSchema = z.object({
  value: z.string(),
  direction: z.enum(["ltr", "rtl", "mixed"]),
  font_family: z.string().min(1),
  font_size_pt: z.number().gt(0),
  weight: z.number().int().min(100).max(900),
  align: z.enum(["left", "center", "right", "justify"]),
  color: hexColor
});
const nodeSchema = z
  .object({
    id: z.string().min(1),
    type: z.enum(nodeTypes),
    bbox: bboxSchema,
    z: z.number().int(),
    editable: z.literal(true),
    parent: z.string().min(1).optional(),
    style: styleSchema.optional(),
    text: textSchema.optional(),
    rows: z.number().int().gt(0).optional(),
    columns: z.number().int().gt(0).optional(),
    content_ref: z.string().min(1).optional(),
    crop: bboxSchema.optional()
  })
  .superRefine((node, context) => {
    if (node.type === "text" && !node.text) {
      context.addIssue({ code: "custom", message: "text node requires text" });
    }
    if (node.type !== "text" && node.type !== "group" && !node.style) {
      context.addIssue({ code: "custom", message: `${node.type} requires style` });
    }
    if (node.type === "grid" && (!node.rows || !node.columns)) {
      context.addIssue({ code: "custom", message: "grid requires rows and columns" });
    }
    if (node.type === "image" && !node.content_ref) {
      context.addIssue({ code: "custom", message: "image requires content_ref" });
    }
  });
export const sceneGraphSchema = z
  .object({
    version: z.literal("scene-graph.v1"),
    page: z.object({
      width: z.number().gt(0),
      height: z.number().gt(0),
      orientation: z.enum(["landscape", "portrait"])
    }),
    nodes: z.array(nodeSchema).min(1),
    constraints: z.array(
      z.object({
        type: z.enum(constraintTypes),
        source: z.string().min(1),
        target: z.string().min(1),
        tolerance: z.number().min(0).max(1).default(0.01)
      })
    )
  })
  .superRefine((scene, context) => {
    const ids = new Set();
    for (const [index, node] of scene.nodes.entries()) {
      if (ids.has(node.id)) {
        context.addIssue({
          code: "custom",
          path: ["nodes", index, "id"],
          message: `duplicate id ${node.id}`
        });
      }
      ids.add(node.id);
    }
    for (const [index, node] of scene.nodes.entries()) {
      if (node.parent && !ids.has(node.parent)) {
        context.addIssue({
          code: "custom",
          path: ["nodes", index, "parent"],
          message: `missing parent ${node.parent}`
        });
      }
    }
    for (const [index, constraint] of scene.constraints.entries()) {
      if (!ids.has(constraint.source) || !ids.has(constraint.target)) {
        context.addIssue({
          code: "custom",
          path: ["constraints", index],
          message: "constraint references a missing node"
        });
      }
    }
  });

export const sceneGraphJsonSchema = Object.freeze({
  type: "object",
  additionalProperties: false,
  required: ["version", "page", "nodes", "constraints"],
  properties: {
    version: { const: "scene-graph.v1" },
    page: {
      type: "object",
      additionalProperties: false,
      required: ["width", "height", "orientation"],
      properties: {
        width: { type: "number", exclusiveMinimum: 0 },
        height: { type: "number", exclusiveMinimum: 0 },
        orientation: { enum: ["landscape", "portrait"] }
      }
    },
    nodes: {
      type: "array",
      minItems: 1,
      maxItems: 64,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["id", "type", "bbox", "z", "editable"],
        allOf: [
          {
            if: { properties: { type: { const: "text" } }, required: ["type"] },
            then: { required: ["text"] }
          },
          {
            if: {
              properties: { type: { enum: ["rectangle", "rounded_rectangle", "ellipse", "line", "polygon", "grid", "image"] } },
              required: ["type"]
            },
            then: { required: ["style"] }
          },
          {
            if: { properties: { type: { const: "grid" } }, required: ["type"] },
            then: { required: ["rows", "columns"] }
          },
          {
            if: { properties: { type: { const: "image" } }, required: ["type"] },
            then: { required: ["content_ref"] }
          }
        ],
        properties: {
          id: { type: "string", minLength: 1 },
          type: { enum: nodeTypes },
          bbox: {
            type: "array",
            minItems: 4,
            maxItems: 4,
            items: { type: "number", minimum: 0, maximum: 1 }
          },
          z: { type: "integer" },
          editable: { const: true },
          parent: { type: "string" },
          style: {
            type: "object",
            additionalProperties: false,
            required: ["fill", "stroke", "stroke_width", "corner_radius", "opacity"],
            properties: {
              fill: { type: ["string", "null"] },
              stroke: { type: ["string", "null"] },
              stroke_width: { type: "number", minimum: 0 },
              corner_radius: { type: "number", minimum: 0 },
              opacity: { type: "number", minimum: 0, maximum: 1 }
            }
          },
          text: {
            type: "object",
            additionalProperties: false,
            required: ["value", "direction", "font_family", "font_size_pt", "weight", "align", "color"],
            properties: {
              value: { type: "string" },
              direction: { enum: ["ltr", "rtl", "mixed"] },
              font_family: { type: "string" },
              font_size_pt: { type: "number", exclusiveMinimum: 0 },
              weight: { type: "integer", minimum: 100, maximum: 900 },
              align: { enum: ["left", "center", "right", "justify"] },
              color: { type: "string" }
            }
          },
          rows: { type: "integer", minimum: 1 },
          columns: { type: "integer", minimum: 1 },
          content_ref: { type: "string" },
          crop: {
            type: "array",
            minItems: 4,
            maxItems: 4,
            items: { type: "number", minimum: 0, maximum: 1 }
          }
        }
      }
    },
    constraints: {
      type: "array",
      maxItems: 24,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["type", "source", "target", "tolerance"],
        properties: {
          type: { enum: constraintTypes },
          source: { type: "string" },
          target: { type: "string" },
          tolerance: { type: "number", minimum: 0, maximum: 1 }
        }
      }
    }
  }
});

const sceneGraphResponseFormat = Object.freeze({
  type: "json_schema",
  json_schema: Object.freeze({
    name: "scene_graph",
    strict: true,
    schema: sceneGraphJsonSchema
  })
});

const parseVisionResponse = (response) => {
  const raw =
    typeof response === "string"
      ? response
      : response?.choices?.[0]?.message?.content ??
        response?.answer ??
        response?.response ??
        response?.result ??
        response?.output;
  if (raw && typeof raw === "object") return raw;
  if (typeof raw !== "string") {
    throw new Error("SCENE_RESPONSE: Workers AI returned no structured scene graph");
  }
  const candidates = [
    raw.trim(),
    raw.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "")
  ];
  const firstBrace = raw.indexOf("{");
  const lastBrace = raw.lastIndexOf("}");
  if (firstBrace !== -1 && lastBrace > firstBrace) {
    candidates.push(raw.slice(firstBrace, lastBrace + 1));
  }
  const isSceneCandidate = (value) =>
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    value.version === "scene-graph.v1";
  for (const candidate of [...new Set(candidates)]) {
    try {
      const parsed = JSON.parse(candidate);
      if (isSceneCandidate(parsed)) return parsed;
    } catch {
      // Continue into deterministic repair.
    }
    try {
      const repaired = JSON.parse(jsonrepair(candidate));
      if (isSceneCandidate(repaired)) return repaired;
    } catch {
      // Try the next deterministic extraction form.
    }
  }
  const excerpt = (value) =>
    JSON.stringify(value)
      .replace(/[A-Za-z0-9_-]{32,}/g, "[redacted]")
      .slice(0, 180);
  throw new Error(
    `SCENE_RESPONSE: invalid JSON length=${raw.length} start=${excerpt(raw.slice(0, 120))} end=${excerpt(raw.slice(-120))}`
  );
};

const hasArabic = (value) => /[\u0600-\u06ff]/u.test(value);

const canonicalText = (node, type) => {
  if (type !== "text") return node.text;
  const raw = node.text ?? node.value ?? node.content ?? node.label ?? "";
  const source = raw && typeof raw === "object" ? raw : {};
  const value = String(
    typeof raw === "string" ? raw : source.value ?? source.content ?? source.label ?? ""
  );
  const direction = ["ltr", "rtl", "mixed"].includes(source.direction)
    ? source.direction
    : hasArabic(value)
      ? "rtl"
      : "ltr";
  return {
    value,
    direction,
    font_family:
      source.font_family || node.font_family || (direction === "rtl" ? "Noto Sans Arabic" : "Arial"),
    font_size_pt: Number(source.font_size_pt ?? node.font_size_pt ?? node.font_size ?? 12),
    weight: Number(source.weight ?? node.weight ?? 400),
    align:
      source.align ||
      node.align ||
      (direction === "rtl" ? "right" : direction === "ltr" ? "left" : "center"),
    color: canonicalColor(source.color ?? node.color) || "#111111"
  };
};

const canonicalNodeType = (node, normalized) => {
  if (nodeTypes.includes(normalized)) return normalized;
  const alias = nodeTypeAliases.get(normalized);
  if (alias) return alias;
  if (node.text != null) return "text";
  if (node.rows != null || node.columns != null) return "grid";
  if (node.content_ref != null) return "image";
  if (node.style?.corner_radius > 0) return "rounded_rectangle";
  if (node.style) return "rectangle";
  if (
    Array.isArray(node.bbox) ||
    [node.x, node.y, node.width, node.height].every((item) => Number.isFinite(Number(item))) ||
    [node.position?.x, node.position?.y, node.size?.width, node.size?.height].every((item) =>
      Number.isFinite(Number(item))
    )
  ) {
    return "rectangle";
  }
  return normalized;
};

const canonicalColor = (value) => {
  if (typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value)) return value;
  if (
    value &&
    typeof value === "object" &&
    typeof value.color === "string" &&
    /^#[0-9a-fA-F]{6}$/.test(value.color)
  ) {
    return value.color;
  }
  return null;
};

const canonicalStyle = (node, type) => {
  if (type === "text" || type === "group") return node.style;
  const style = node.style && typeof node.style === "object" ? node.style : {};
  return {
    fill: canonicalColor(style.fill ?? node.fill),
    stroke: canonicalColor(style.stroke ?? node.stroke),
    stroke_width: Number(style.stroke_width ?? node.stroke_width ?? 0),
    corner_radius: Number(style.corner_radius ?? node.corner_radius ?? 0),
    opacity: Number(style.opacity ?? node.opacity ?? 1)
  };
};

const canonicalBBox = (value) => {
  if (
    !Array.isArray(value) ||
    value.length !== 4 ||
    value.some((item) => !Number.isFinite(Number(item)))
  ) {
    return value;
  }
  let [x, y, width, height] = value.map(Number);
  if (
    [x, y, width, height].some((item) => item > 1) &&
    [x, y, width, height].every((item) => item <= 100)
  ) {
    [x, y, width, height] = [x, y, width, height].map((item) => item / 100);
  }
  x = Math.min(1, Math.max(0, x));
  y = Math.min(1, Math.max(0, y));
  width = Math.min(Math.max(0, width), 1 - x);
  height = Math.min(Math.max(0, height), 1 - y);
  return [x, y, width, height].map((item) => Math.round(item * 1_000_000) / 1_000_000);
};

const nodeBBox = (node, type) => {
  if (node.bbox != null) return canonicalBBox(node.bbox);
  const direct = [node.x, node.y, node.width, node.height];
  if (direct.every((item) => Number.isFinite(Number(item)))) return canonicalBBox(direct);
  const nested = [
    node.position?.x,
    node.position?.y,
    node.size?.width,
    node.size?.height
  ];
  if (nested.every((item) => Number.isFinite(Number(item)))) return canonicalBBox(nested);
  return type === "group" ? [0, 0, 1, 1] : node.bbox;
};

const positiveInteger = (...values) => {
  for (const value of values) {
    if (Array.isArray(value) && value.length > 0) return value.length;
    const number = Number(value);
    if (Number.isInteger(number) && number > 0) return number;
  }
  return undefined;
};

const gridDimensions = (node) => ({
  rows: positiveInteger(
    node.rows,
    node.row_count,
    node.rowCount,
    node.grid?.rows,
    Array.isArray(node.horizontal_lines) ? node.horizontal_lines.length + 1 : undefined
  ),
  columns: positiveInteger(
    node.columns,
    node.cols,
    node.column_count,
    node.col_count,
    node.columnCount,
    node.grid?.columns,
    Array.isArray(node.vertical_lines) ? node.vertical_lines.length + 1 : undefined
  )
});

const canonicalizeSceneNodeTypes = (scene) => {
  const nodes = Array.isArray(scene?.nodes)
    ? scene.nodes.map((node, index) => {
        if (!node || typeof node.type !== "string") return node;
        const normalized = node.type.trim().toLowerCase().replace(/[\s-]+/g, "_");
        const type = canonicalNodeType(node, normalized);
        const dimensions = type === "grid" ? gridDimensions(node) : {};
        return {
          ...node,
          z: Number.isInteger(node.z) ? node.z : index,
          editable: true,
          type,
          bbox: nodeBBox(node, type),
          ...(type === "text" ? { text: canonicalText(node, type) } : {}),
          ...(type !== "text" && type !== "group"
            ? { style: canonicalStyle(node, type) }
            : {}),
          ...(type === "image"
            ? { content_ref: node.content_ref || `reference-region:${node.id || index}` }
            : {}),
          ...(dimensions.rows ? { rows: dimensions.rows } : {}),
          ...(dimensions.columns ? { columns: dimensions.columns } : {})
        };
      })
    : scene?.nodes;
  const ids = new Set(Array.isArray(nodes) ? nodes.map((node) => node?.id).filter(Boolean) : []);
  const constraints = Array.isArray(scene?.constraints)
    ? scene.constraints.filter(
        (constraint) => ids.has(constraint?.source) && ids.has(constraint?.target)
      )
    : scene?.constraints;
  return { ...scene, nodes, constraints };
};

const stableSceneError = (error) => {
  const issue = error?.issues?.[0];
  if (issue?.path?.includes("type")) return "SCENE_NODE_TYPE";
  if (issue?.message?.includes("duplicate")) return "SCENE_DUPLICATE_ID";
  if (issue?.message?.includes("parent") || issue?.message?.includes("constraint")) {
    return "SCENE_REFERENCE";
  }
  if (issue?.path?.includes("bbox")) return "SCENE_BOUNDS";
  return "SCENE_INVALID";
};

const applyNonGeometricHints = (scene, hints = {}) => {
  const replacementText =
    hints && typeof hints.replacement_text === "object" && hints.replacement_text
      ? hints.replacement_text
      : {};
  return {
    ...scene,
    nodes: scene.nodes.map((node) =>
      node.type === "text" && Object.hasOwn(replacementText, node.id)
        ? { ...node, text: { ...node.text, value: String(replacementText[node.id]) } }
        : node
    )
  };
};

export async function extractSceneGraph({ ai, reference, hints = {} }) {
  if (!ai?.run) throw new Error("SCENE_AI_UNAVAILABLE: Workers AI binding is missing");
  const image = `data:${reference.mimeType};base64,${Buffer.from(reference.bytes).toString("base64")}`;
  const languageHint =
    typeof hints?.language === "string" ? ` Preferred language: ${hints.language}.` : "";
  const response = await ai.run(VISION_MODEL, {
    messages: [
      {
        role: "system",
        content:
          "Extract a compact, reference-agnostic editable page scene graph with at most 64 nodes and 24 high-value constraints. Measure every distinct visible region, text box, line, border, shape, and image, but represent repeated uniform rows and cells as one grid node instead of enumerating each cell. Use normalized bounding boxes, stable IDs, explicit z-order, typography, colors, RTL/LTR direction, and parent relationships. Prioritize complete nodes over redundant pairwise constraints. A semantic table may be a grid or independent shapes according to its actual visual construction. Return only the declared fields and never invent fixture-specific node types."
      },
      {
        role: "user",
        content: [
          {
            type: "text",
            text: `Return only scene-graph.v1 JSON for the attached reference.${languageHint}`
          },
          {
            type: "image_url",
            image_url: { url: image }
          }
        ]
      }
    ],
    response_format: sceneGraphResponseFormat,
    chat_template_kwargs: { thinking: false },
    temperature: 0,
    max_completion_tokens: 16384
  });
  let parsed;
  try {
    parsed = sceneGraphSchema.parse(canonicalizeSceneNodeTypes(parseVisionResponse(response)));
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("SCENE_")) throw error;
    throw new Error(`${stableSceneError(error)}: ${error.message}`);
  }
  const hinted = applyNonGeometricHints(parsed, hints);
  return sceneGraphSchema.parse(hinted);
}

export async function correctSceneGraph({
  ai,
  reference,
  scene,
  correctionHints = []
}) {
  if (!ai?.run) throw new Error("SCENE_AI_UNAVAILABLE: Workers AI binding is missing");
  const image = `data:${reference.mimeType};base64,${Buffer.from(reference.bytes).toString("base64")}`;
  const response = await ai.run(VISION_MODEL, {
    messages: [
      {
        role: "system",
        content:
          "Correct an editable scene graph from independent rendered-validation evidence. Preserve every measured reference feature that did not fail. Modify only nodes named by the validation hints. Return only scene-graph.v1 JSON."
      },
      {
        role: "user",
        content: [
          {
            type: "text",
            text: JSON.stringify({
              current_scene: scene,
              validation_hints: correctionHints
            })
          },
          {
            type: "image_url",
            image_url: { url: image }
          }
        ]
      }
    ],
    response_format: sceneGraphResponseFormat,
    chat_template_kwargs: { thinking: false },
    temperature: 0,
    max_completion_tokens: 16384
  });
  try {
    return sceneGraphSchema.parse(canonicalizeSceneNodeTypes(parseVisionResponse(response)));
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("SCENE_")) throw error;
    throw new Error(`${stableSceneError(error)}: ${error.message}`);
  }
}
