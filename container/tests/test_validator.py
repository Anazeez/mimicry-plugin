import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from container.app.schemas import validate_scene_graph
from container.app.validator import validate_fidelity


class FidelityValidatorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.scene = validate_scene_graph(
            {
                "version": "scene-graph.v1",
                "page": {"width": 300, "height": 200, "orientation": "landscape"},
                "nodes": [
                    {
                        "id": "grid",
                        "type": "grid",
                        "bbox": [0.1, 0.2, 0.8, 0.6],
                        "z": 1,
                        "editable": True,
                        "rows": 3,
                        "columns": 3,
                        "style": {
                            "fill": "#FFFFFF",
                            "stroke": "#222222",
                            "stroke_width": 1,
                            "corner_radius": 0,
                            "opacity": 1,
                        },
                    },
                    {
                        "id": "title",
                        "type": "text",
                        "bbox": [0.18, 0.26, 0.22, 0.1],
                        "z": 2,
                        "editable": True,
                        "text": {
                            "value": "Daily",
                            "direction": "ltr",
                            "font_family": "Noto Sans",
                            "font_size_pt": 18,
                            "weight": 700,
                            "align": "left",
                            "color": "#111111",
                        },
                    },
                ],
                "constraints": [],
            }
        )
        self.reference = self.root / "reference.png"
        self.good = self.root / "good.png"
        self.broken_border = self.root / "broken-border.png"
        self.broken_contrast = self.root / "broken-contrast.png"
        self.missing_text = self.root / "missing-text.png"
        self.blank = self.root / "blank.png"
        self._draw(self.reference, borders=True, text="#111111")
        self._draw(self.good, borders=True, text="#111111")
        self._draw(self.broken_border, borders=False, text="#111111")
        self._draw(self.broken_contrast, borders=True, text="#FEFEFE")
        self._draw(self.missing_text, borders=True, text=None)
        Image.new("RGB", (600, 400), "white").save(self.blank)
        self.manifest = {
            "page_count": 1,
            "native_shape_count": 2,
            "image_object_count": 0,
            "full_page_image_count": 0,
            "package_audit": {
                "audit_complete": True,
                "embedded_image_objects": 0,
                "native_shape_objects": 2,
                "native_text_regions": 1,
                "source_text_regions": 1,
                "visible_text_native_ratio": 1.0,
                "scene_node_coverage": 1.0,
                "native_visible_area_ratio": 1.0,
                "largest_unjustified_raster_ratio": 0.0,
                "total_unjustified_raster_ratio": 0.0,
                "source_reference_embedded": False,
                "raster_tiling_detected": False,
                "monolithic_flattened_object": False,
                "unjustified_raster_objects": 0,
            },
            "actual_nodes": [
                {"id": node["id"], "bbox": node["bbox"], "shape_type": node["type"]}
                for node in self.scene["nodes"]
            ],
        }
        self.ocr_patcher = patch(
            "container.app.validator._ocr_word_count",
            side_effect=lambda _: 1,
        )
        self.ocr_patcher.start()

    def tearDown(self):
        self.ocr_patcher.stop()
        self.directory.cleanup()

    def _draw(self, path, borders, text):
        image = Image.new("RGB", (600, 400), "white")
        draw = ImageDraw.Draw(image)
        left, top, right, bottom = 60, 80, 540, 320
        if borders:
            draw.rectangle((left, top, right, bottom), outline="#222222", width=4)
            for x in (220, 380):
                draw.line((x, top, x, bottom), fill="#222222", width=4)
            for y in (160, 240):
                draw.line((left, y, right, y), fill="#222222", width=4)
        if text:
            draw.rectangle((108, 112, 220, 132), fill=text)
        image.save(path)

    def test_known_good_passes_all_critical_gates(self):
        report = validate_fidelity(
            self.reference, self.good, self.scene, self.manifest
        )
        self.assertEqual(report["status"], "PASS", report)
        self.assertTrue(all(report["gates"].values()), report)

    def test_missing_borders_fail_continuity(self):
        report = validate_fidelity(
            self.reference, self.broken_border, self.scene, self.manifest
        )
        self.assertFalse(report["gates"]["G_BORDER_CONTINUITY"], report)

    def test_white_on_white_text_fails_contrast(self):
        report = validate_fidelity(
            self.reference, self.broken_contrast, self.scene, self.manifest
        )
        self.assertFalse(report["gates"]["V_CONTRAST"], report)
        finding = next(
            item for item in report["findings"] if item["gate"] == "V_CONTRAST"
        )
        self.assertEqual(finding["measured"]["nodes"][0]["id"], "title")
        self.assertLess(finding["measured"]["nodes"][0]["contrast_ratio"], 3)

    def test_displaced_node_fails_alignment(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["actual_nodes"][0]["bbox"][0] += 0.12
        report = validate_fidelity(
            self.reference, self.good, self.scene, manifest
        )
        self.assertFalse(report["gates"]["G_ALIGNMENT"], report)
        finding = next(
            item for item in report["findings"] if item["gate"] == "G_ALIGNMENT"
        )
        self.assertIn("grid", finding["node_ids"])
        node = next(
            item for item in finding["measured"]["nodes"] if item["id"] == "grid"
        )
        self.assertEqual(node["expected_bbox"], self.scene["nodes"][0]["bbox"])
        self.assertEqual(node["actual_bbox"], manifest["actual_nodes"][0]["bbox"])
        self.assertAlmostEqual(node["max_error"], 0.12)

    def test_blank_render_fails_nonblank(self):
        report = validate_fidelity(
            self.reference, self.blank, self.scene, self.manifest
        )
        self.assertFalse(report["gates"]["R_NONBLANK"], report)

    def test_flattened_page_fails_editability(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["full_page_image_count"] = 1
        manifest["package_audit"].update(
            {
                "embedded_image_objects": 1,
                "native_shape_objects": 0,
                "native_text_regions": 0,
                "visible_text_native_ratio": 0.0,
                "scene_node_coverage": 0.0,
                "native_visible_area_ratio": 0.0,
                "largest_unjustified_raster_ratio": 0.97,
                "total_unjustified_raster_ratio": 0.97,
                "source_reference_embedded": True,
            }
        )
        report = validate_fidelity(
            self.reference, self.good, self.scene, manifest
        )
        self.assertFalse(report["gates"]["S_EDITABILITY"], report)
        self.assertEqual(report["status"], "EDITABILITY_FAILED", report)
        self.assertEqual(
            report["metrics"]["largest_unjustified_raster_ratio"], 0.97
        )

    def test_missing_package_audit_fails_closed_as_incomplete(self):
        manifest = json.loads(json.dumps(self.manifest))
        del manifest["package_audit"]

        report = validate_fidelity(
            self.reference, self.good, self.scene, manifest
        )

        self.assertEqual(report["status"], "VALIDATION_INCOMPLETE", report)
        self.assertFalse(report["gates"]["G_PACKAGE_MEDIA_AUDIT"], report)
        self.assertFalse(report["gates"]["S_EDITABILITY"], report)

    def test_tiled_rasters_fail_total_unjustified_coverage(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["package_audit"].update(
            {
                "embedded_image_objects": 16,
                "native_shape_objects": 0,
                "native_text_regions": 1,
                "visible_text_native_ratio": 0.03,
                "scene_node_coverage": 0.05,
                "native_visible_area_ratio": 0.04,
                "largest_unjustified_raster_ratio": 0.09,
                "total_unjustified_raster_ratio": 0.96,
            }
        )

        report = validate_fidelity(
            self.reference, self.good, self.scene, manifest
        )

        self.assertEqual(report["status"], "EDITABILITY_FAILED", report)
        self.assertFalse(report["gates"]["G_NO_FULL_PAGE_RASTER"], report)
        finding = next(
            item
            for item in report["findings"]
            if item["gate"] == "G_NO_FULL_PAGE_RASTER"
        )
        self.assertEqual(finding["measured"]["total_unjustified_raster_ratio"], 0.96)
        self.assertEqual(finding["required"]["maximum_total_ratio"], 0.15)

    def test_hidden_ocr_overlay_does_not_make_visible_text_native(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["package_audit"].update(
            {
                "embedded_image_objects": 1,
                "native_shape_objects": 1,
                "native_text_regions": 31,
                "source_text_regions": 31,
                "visible_text_native_ratio": 0.0,
                "scene_node_coverage": 0.1,
                "native_visible_area_ratio": 0.05,
                "largest_unjustified_raster_ratio": 0.9,
                "total_unjustified_raster_ratio": 0.9,
            }
        )

        report = validate_fidelity(
            self.reference, self.good, self.scene, manifest
        )

        self.assertIn("G_VISIBLE_TEXT_NATIVE", report["gates"], report)
        self.assertIn("G_NATIVE_OBJECT_RATIO", report["gates"], report)
        self.assertFalse(report["gates"]["G_VISIBLE_TEXT_NATIVE"], report)
        self.assertFalse(report["gates"]["G_NATIVE_OBJECT_RATIO"], report)

    def test_missing_rendered_text_fails_visual_text_coverage(self):
        report = validate_fidelity(
            self.reference, self.missing_text, self.scene, self.manifest
        )

        self.assertEqual(report["status"], "FIDELITY_FAILED", report)
        self.assertFalse(report["gates"]["V_TEXT_COVERAGE"], report)
        finding = next(
            item for item in report["findings"] if item["gate"] == "V_TEXT_COVERAGE"
        )
        self.assertEqual(
            finding["measured"]["text_visual_coverage_ratio"],
            0.0,
        )

    def test_ocr_tokenization_cannot_override_complete_node_visual_coverage(self):
        with patch(
            "container.app.validator._ocr_word_count",
            side_effect=(50, 16),
        ):
            report = validate_fidelity(
                self.reference, self.good, self.scene, self.manifest
            )

        self.assertEqual(report["metrics"]["text_detection_ratio"], 0.32)
        self.assertEqual(report["metrics"]["text_visual_coverage_ratio"], 1.0)
        self.assertTrue(report["gates"]["V_TEXT_COVERAGE"], report)


if __name__ == "__main__":
    unittest.main()
