import json
from pathlib import Path
import tempfile
import unittest

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
        self.blank = self.root / "blank.png"
        self._draw(self.reference, borders=True, text="#111111")
        self._draw(self.good, borders=True, text="#111111")
        self._draw(self.broken_border, borders=False, text="#111111")
        self._draw(self.broken_contrast, borders=True, text="#FEFEFE")
        Image.new("RGB", (600, 400), "white").save(self.blank)
        self.manifest = {
            "page_count": 1,
            "native_shape_count": 2,
            "image_object_count": 0,
            "full_page_image_count": 0,
            "actual_nodes": [
                {"id": node["id"], "bbox": node["bbox"], "shape_type": node["type"]}
                for node in self.scene["nodes"]
            ],
        }

    def tearDown(self):
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

    def test_displaced_node_fails_alignment(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["actual_nodes"][0]["bbox"][0] += 0.12
        report = validate_fidelity(
            self.reference, self.good, self.scene, manifest
        )
        self.assertFalse(report["gates"]["G_ALIGNMENT"], report)
        self.assertIn("grid", report["findings"][0]["node_ids"])

    def test_blank_render_fails_nonblank(self):
        report = validate_fidelity(
            self.reference, self.blank, self.scene, self.manifest
        )
        self.assertFalse(report["gates"]["R_NONBLANK"], report)

    def test_flattened_page_fails_editability(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["full_page_image_count"] = 1
        report = validate_fidelity(
            self.reference, self.good, self.scene, manifest
        )
        self.assertFalse(report["gates"]["S_EDITABILITY"], report)


if __name__ == "__main__":
    unittest.main()
