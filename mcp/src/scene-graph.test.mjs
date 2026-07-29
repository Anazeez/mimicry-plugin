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

  assert.deepEqual(calls[0].input, { prompt: "agree" });
  assert.equal(calls[1].model, "@cf/meta/llama-3.2-11b-vision-instruct");
  assert.match(calls[1].input.image, /^data:image\/jpeg;base64,/);
  assert.equal(calls[1].input.temperature, 0);
  assert.equal(calls[1].input.response_format.type, "json_object");
  assert.equal(calls[1].input.max_tokens, 7000);
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

test("fails closed when vision returns a malformed or fixture-specific graph", async () => {
  const ai = {
    async run() {
      return {
        response: JSON.stringify({
          ...graph,
          nodes: [{ ...graph.nodes[0], type: "daily_meeting_grid" }]
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
