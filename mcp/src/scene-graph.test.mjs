import assert from "node:assert/strict";
import test from "node:test";
import { extractSceneGraph } from "./scene-graph.js";

const graph = {
  version: "scene-graph.v1",
  page: { width: 297, height: 210, orientation: "landscape" },
  nodes: [
    {
      id: "title",
      type: "text",
      bbox: [0.1, 0.1, 0.4, 0.1],
      z: 1,
      editable: true,
      text: {
        value: "اجتماع يومي",
        direction: "rtl",
        font_family: "Noto Sans Arabic",
        font_size_pt: 24,
        weight: 700,
        align: "right",
        color: "#111111"
      }
    }
  ],
  constraints: []
};

test("sends the actual reference image to Workers AI and validates its scene graph", async () => {
  const calls = [];
  const ai = {
    async run(model, input) {
      calls.push({ model, input });
      return { response: JSON.stringify(graph) };
    }
  };
  const result = await extractSceneGraph({
    ai,
    reference: {
      bytes: new Uint8Array([0xff, 0xd8, 0xff, 0xdb]),
      mimeType: "image/jpeg",
      digest: "abc"
    },
    hints: { language: "ar" }
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].model, "@cf/moonshotai/kimi-k2.6");
  assert.match(
    calls[0].input.messages[1].content[1].image_url.url,
    /^data:image\/jpeg;base64,/
  );
  assert.match(calls[0].input.messages[1].content[0].text, /scene-graph\.v1 JSON/);
  assert.equal(calls[0].input.temperature, 0);
  assert.equal(calls[0].input.response_format.type, "json_schema");
  assert.equal(calls[0].input.response_format.json_schema.name, "scene_graph");
  assert.equal(calls[0].input.response_format.json_schema.strict, true);
  assert.ok(calls[0].input.response_format.json_schema.schema.properties.nodes);
  const nodeSchema =
    calls[0].input.response_format.json_schema.schema.properties.nodes.items;
  assert.equal(nodeSchema.additionalProperties, false);
  assert.ok(nodeSchema.allOf.some((rule) => rule.then?.required?.includes("text")));
  assert.ok(nodeSchema.allOf.some((rule) => rule.then?.required?.includes("style")));
  assert.equal(
    calls[0].input.response_format.json_schema.schema.properties.constraints.maxItems,
    24
  );
  assert.equal(
    calls[0].input.response_format.json_schema.schema.properties.nodes.maxItems,
    64
  );
  assert.deepEqual(calls[0].input.chat_template_kwargs, { thinking: false });
  assert.equal(calls[0].input.max_completion_tokens, 16384);
  assert.deepEqual(result, graph);
});

test("user hints cannot overwrite measured geometry", async () => {
  const ai = {
    async run() {
      return { response: JSON.stringify(graph) };
    }
  };
  const result = await extractSceneGraph({
    ai,
    reference: {
      bytes: new Uint8Array([0x89, 0x50, 0x4e, 0x47]),
      mimeType: "image/png",
      digest: "abc"
    },
    hints: {
      bbox: [0, 0, 1, 1],
      nodes: [{ id: "title", bbox: [0, 0, 1, 1] }],
      replacement_text: { title: "New title" }
    }
  });

  assert.deepEqual(result.nodes[0].bbox, graph.nodes[0].bbox);
  assert.equal(result.nodes[0].text.value, "New title");
});

test("accepts a valid scene object wrapped in model prose and a JSON fence", async () => {
  const ai = {
    async run(_model, input) {
      if (input.prompt === "agree") return { response: "accepted" };
      return {
        response: `Here is the measured scene:\n\`\`\`json\n${JSON.stringify(graph)}\n\`\`\``
      };
    }
  };
  const result = await extractSceneGraph({
    ai,
    reference: {
      bytes: new Uint8Array([0xff, 0xd8, 0xff, 0xdb]),
      mimeType: "image/jpeg",
      digest: "abc"
    }
  });
  assert.deepEqual(result, graph);
});

test("deterministically repairs malformed model JSON before strict validation", async () => {
  const malformed = JSON.stringify(graph).replace(/}$/, ",");
  const ai = {
    async run(_model, input) {
      if (input.prompt === "agree") return { response: "accepted" };
      return { response: malformed };
    }
  };
  const result = await extractSceneGraph({
    ai,
    reference: {
      bytes: new Uint8Array([0xff, 0xd8, 0xff, 0xdb]),
      mimeType: "image/jpeg",
      digest: "abc"
    }
  });
  assert.deepEqual(result, graph);
});

test("canonicalizes common visual node aliases without accepting unknown types", async () => {
  const aliasGraph = {
    ...graph,
    nodes: [
      {
        id: "page",
        type: "Frame",
        bbox: [0, 0, 1, 1],
        z: 0,
        editable: true
      },
      {
        id: "slot",
        type: "pill",
        bbox: [0.1, 0.2, 0.3, 0.1],
        z: 1,
        editable: true,
        style: {
          fill: "#FFFFFF",
          stroke: "#111111",
          stroke_width: 1,
          corner_radius: 20,
          opacity: 1
        }
      }
    ]
  };
  const ai = { async run() { return { response: JSON.stringify(aliasGraph) }; } };
  const result = await extractSceneGraph({
    ai,
    reference: {
      bytes: new Uint8Array([0xff, 0xd8, 0xff, 0xdb]),
      mimeType: "image/jpeg",
      digest: "abc"
    }
  });
  assert.equal(result.nodes[0].type, "group");
  assert.equal(result.nodes[1].type, "rounded_rectangle");
});

test("derives deterministic z-order and editability for model nodes", async () => {
  const incompleteGraph = {
    ...graph,
    nodes: graph.nodes.map(({ z: _z, editable: _editable, ...node }) => node)
  };
  const ai = { async run() { return { response: JSON.stringify(incompleteGraph) }; } };
  const result = await extractSceneGraph({
    ai,
    reference: {
      bytes: new Uint8Array([0xff, 0xd8, 0xff, 0xdb]),
      mimeType: "image/jpeg",
      digest: "abc"
    }
  });
  assert.equal(result.nodes[0].z, 0);
  assert.equal(result.nodes[0].editable, true);
});

test("infers a text node and editable text metadata from model shorthand", async () => {
  const shorthandGraph = {
    ...graph,
    nodes: [
      {
        id: "heading",
        type: "heading",
        bbox: [0.1, 0.1, 0.5, 0.1],
        text: "اجتماع يومي"
      }
    ]
  };
  const ai = { async run() { return { response: JSON.stringify(shorthandGraph) }; } };
  const result = await extractSceneGraph({
    ai,
    reference: {
      bytes: new Uint8Array([0xff, 0xd8, 0xff, 0xdb]),
      mimeType: "image/jpeg",
      digest: "abc"
    }
  });
  assert.equal(result.nodes[0].type, "text");
  assert.equal(result.nodes[0].text.value, "اجتماع يومي");
  assert.equal(result.nodes[0].text.direction, "rtl");
  assert.equal(result.nodes[0].text.color, "#111111");
});

test("prefers OpenAI-style choices over an empty legacy response field", async () => {
  const ai = {
    async run() {
      return {
        response: "",
        choices: [{ message: { content: JSON.stringify(graph) } }]
      };
    }
  };
  const result = await extractSceneGraph({
    ai,
    reference: {
      bytes: new Uint8Array([0xff, 0xd8, 0xff, 0xdb]),
      mimeType: "image/jpeg",
      digest: "abc"
    }
  });
  assert.deepEqual(result, graph);
});

test("fails closed when an unknown node type has no inferable visual primitive", async () => {
  const ai = {
    async run() {
      return {
        response: JSON.stringify({
          ...graph,
          nodes: [
            {
              id: "fixture",
              type: "daily_meeting_grid",
              bbox: [0.1, 0.1, 0.5, 0.5],
              z: 0,
              editable: true
            }
          ]
        })
      };
    }
  };
  await assert.rejects(
    extractSceneGraph({
      ai,
      reference: {
        bytes: new Uint8Array([0x89, 0x50, 0x4e, 0x47]),
        mimeType: "image/png",
        digest: "abc"
      }
    }),
    /SCENE_NODE_TYPE/
  );
});
