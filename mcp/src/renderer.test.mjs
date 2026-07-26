import assert from "node:assert/strict";
import test from "node:test";
import { renderAndValidate } from "./renderer.js";

const task = {
  task: "artifact_mimicry",
  output: { format: "docx", artifact_kind: "editable_template", editable: true },
  page: { width_in: 11.69, height_in: 8.27 },
  elements: [
    {
      id: "arabic_header",
      type: "roundRect",
      x: 0.1,
      y: 0.1,
      w: 0.3,
      h: 0.08,
      fill: "#082122",
      text: "الوقت",
      text_color: "#BDE8DE",
      font: "Arial",
      font_size_pt: 14,
      bold: true,
      rtl: true,
      editable: true
    }
  ]
};

test("returns a native editable DOCX only after structural validation passes", () => {
  const result = renderAndValidate(task, {
    expected_round_rects: 1,
    forbid_media: true,
    forbid_tables: true,
    required_text: ["الوقت"],
    required_shape_text: ["الوقت"],
    rtl_shape_text: ["الوقت"],
    required_shape_names: ["arabic_header"]
  });

  assert.equal(result.report.status, "PASS");
  assert.deepEqual(Array.from(result.bytes.slice(0, 2)), [0x50, 0x4b]);
  assert.equal(result.report.gates.S_09_required_shape_primitives, true);
});

test("fails closed instead of returning an artifact when geometry is unresolved", () => {
  assert.throws(
    () => renderAndValidate({ ...task, elements: [] }, { expected_round_rects: 1 }),
    /Artifact Mimicry validation failed\. No editable artifact was generated\./
  );
});
