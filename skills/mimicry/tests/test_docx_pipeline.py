#!/usr/bin/env python3
"""Deterministic DOCX renderer and fail-closed gate tests."""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import render_docx  # noqa: E402
import validate_docx  # noqa: E402


RTL_HEADERS = ["الجمعة", "الخميس", "الأربعاء", "الثلاثاء", "الاثنين", "الأحد", "السبت", "الوقت"]
LOGO_PRIMITIVES = [
    "logo_dumbbell_bar",
    "logo_dumbbell_left_outer",
    "logo_dumbbell_left_inner",
    "logo_dumbbell_right_inner",
    "logo_dumbbell_right_outer",
]


def task():
    elements = [
        {
            "id": shape_id,
            "type": "rect",
            "x": 0.09 + index * 0.006,
            "y": 0.12,
            "w": 0.004,
            "h": 0.02,
            "editable": True,
            "text": "",
            "fill": "#BDE8DE",
        }
        for index, shape_id in enumerate(LOGO_PRIMITIVES)
    ]
    width = 0.108
    start_x = 0.0625
    for column, text in enumerate(RTL_HEADERS):
        elements.append({
            "id": f"schedule_header_{column}",
            "type": "roundRect",
            "x": start_x + column * 0.1095,
            "y": 0.247,
            "w": width,
            "h": 0.046,
            "editable": True,
            "text": text,
            "fill": "#071B1B",
            "text_color": "#BDE8DE",
            "font": "Arial",
            "font_size_pt": 14,
            "bold": True,
            "rtl": True,
        })
    for row in range(11):
        for column in range(8):
            is_time = column == 7
            elements.append({
                "id": f"schedule_body_{row}_{column}",
                "type": "roundRect",
                "x": start_x + column * 0.1095,
                "y": 0.318 + row * 0.0515,
                "w": width,
                "h": 0.044,
                "editable": True,
                "text": f"{11 + row if row < 2 else row - 1:02d}:00 {'AM' if row < 1 else 'PM'}"
                if is_time else "",
                "fill": "#BDE8DE" if is_time else "#FFFFFF",
                "text_color": "#0B2220",
                "font": "Arial",
                "font_size_pt": 12,
                "bold": True,
                "rtl": False,
            })
    return {
        "task": "artifact_mimicry",
        "output": {"format": "docx", "artifact_kind": "editable_template", "editable": True},
        "page": {"width_in": 11.69, "height_in": 8.27},
        "elements": elements,
        "validation": {
            "expected_round_rects": 96,
            "forbid_media": True,
            "forbid_tables": True,
            "required_text": RTL_HEADERS + ["11:00 AM"],
        },
    }


class DocxPipelineTests(unittest.TestCase):
    def test_renderer_emits_96_editable_roundrects_with_contained_rtl(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_path = root / "task.json"
            docx_path = root / "artifact.docx"
            task_path.write_text(json.dumps(task(), ensure_ascii=False), encoding="utf-8")
            render_docx.main = render_docx.main
            original = sys.argv
            try:
                sys.argv = ["render_docx.py", str(task_path), str(docx_path)]
                render_docx.main()
            finally:
                sys.argv = original
            expectations = {
                "expected_round_rects": 96,
                "forbid_media": True,
                "forbid_tables": True,
                "required_text": RTL_HEADERS + ["11:00 AM"],
                "required_shape_text": RTL_HEADERS + ["11:00 AM"],
                "rtl_shape_text": RTL_HEADERS,
                "required_shape_names": LOGO_PRIMITIVES,
            }
            report = validate_docx.inspect_docx(docx_path, expectations)
            self.assertEqual(report["status"], "PASS", report)

    def test_missing_word_render_fails_closed(self):
        report = validate_docx.apply_render_gate({"status": "PASS", "gates": {}, "findings": []}, None)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("V-00 rendered evidence is required", report["findings"])

    def test_word_render_report_unlocks_delivery(self):
        render_report = {
            "header_containment": "PASS",
            "grid_alignment": "PASS",
            "pill_geometry": "PASS",
            "rtl_layout": "PASS",
            "word_compatible_render": "PASS",
        }
        report = validate_docx.apply_render_gate(
            {"status": "PASS", "gates": {}, "findings": []},
            render_report,
        )
        self.assertEqual(report["status"], "PASS", report)


if __name__ == "__main__":
    unittest.main()
