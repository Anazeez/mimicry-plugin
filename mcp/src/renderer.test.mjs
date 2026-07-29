import assert from "node:assert/strict";
import test from "node:test";
import { ArtifactValidationError, renderAndValidate } from "./renderer.js";

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
  assert.throws(() => renderAndValidate({ ...task, elements: [] }), (error) => {
    assert.ok(error instanceof ArtifactValidationError);
    assert.equal(error.report.status, "FAIL");
    assert.equal(error.report.gates.I_04_elements_present, false);
    assert.match(error.message, /I-04 no editable elements were supplied/);
    return true;
  });
});

test("normalizes the permissive MCP payload into the renderer contract", () => {
  const result = renderAndValidate({
    page: { width: 11.69, height: 8.27 },
    shapes: [
      {
        name: "header",
        kind: "pill",
        left: 1.169,
        top: 0.827,
        width: 3.507,
        height: 0.6616,
        backgroundColor: "#082122",
        text: "الوقت",
        textColor: "#BDE8DE",
        fontSize: 14,
        direction: "rtl"
      }
    ]
  });

  assert.equal(result.report.status, "PASS");
  assert.equal(result.report.normalization.defaulted_output_contract, true);
  assert.equal(result.report.normalization.normalized_element_aliases, 1);
  assert.equal(result.report.gates.S_03_round_rect_count, true);
  assert.deepEqual(Array.from(result.bytes.slice(0, 2)), [0x50, 0x4b]);
});

test("reports the exact failed structural gate and observed value", () => {
  assert.throws(
    () => renderAndValidate(task, { expected_round_rects: 2 }),
    (error) => {
      assert.ok(error instanceof ArtifactValidationError);
      assert.equal(error.report.gates.S_03_round_rect_count, false);
      assert.deepEqual(error.report.findings, [
        "S-03 expected 2 roundRect shapes; observed 1"
      ]);
      assert.match(error.message, /expected 2 roundRect shapes; observed 1/);
      return true;
    }
  );
});
