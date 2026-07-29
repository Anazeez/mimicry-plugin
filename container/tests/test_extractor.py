import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from container.app.extractor import extract_scene_graph
from container.app.schemas import validate_scene_graph


class DeterministicExtractorTests(unittest.TestCase):
    def test_extracts_page_grid_and_native_text_without_a_full_page_image(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            image = Image.new("RGB", (1200, 800), "white")
            draw = ImageDraw.Draw(image)
            for x in (40, 240, 440, 640, 840, 1040, 1160):
                draw.line((x, 240, x, 720), fill="#e8a181", width=3)
            for y in (240, 400, 560, 720):
                draw.line((40, y, 1160, y), fill="#e8a181", width=3)
            draw.rectangle((820, 50, 1130, 110), fill="#111111")
            image.save(reference)

            tsv = (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext\n"
                "5\t1\t1\t1\t1\t1\t820\t50\t310\t60\t95\tDaily\n"
            )
            with patch("container.app.extractor._ocr_tsv", return_value=tsv):
                scene = validate_scene_graph(extract_scene_graph(reference))

        self.assertEqual(scene["page"]["orientation"], "landscape")
        grids = [node for node in scene["nodes"] if node["type"] == "grid"]
        self.assertEqual(len(grids), 1)
        self.assertEqual((grids[0]["rows"], grids[0]["columns"]), (3, 6))
        self.assertTrue(any(node["type"] == "text" for node in scene["nodes"]))
        self.assertFalse(
            any(
                node["type"] == "image"
                and node["bbox"][2] >= 0.95
                and node["bbox"][3] >= 0.95
                for node in scene["nodes"]
            )
        )

    def test_mixed_arabic_english_ocr_is_marked_rtl_and_kept_editable(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            Image.new("RGB", (600, 900), "white").save(reference)
            tsv = (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext\n"
                "5\t1\t1\t1\t1\t1\t300\t50\t220\t60\t91\tاجتماع\n"
                "5\t1\t2\t1\t1\t1\t40\t800\t180\t40\t88\t2026\n"
            )
            with patch("container.app.extractor._ocr_tsv", return_value=tsv):
                scene = validate_scene_graph(extract_scene_graph(reference))

        texts = [node for node in scene["nodes"] if node["type"] == "text"]
        self.assertEqual(scene["page"]["orientation"], "portrait")
        self.assertTrue(all(node["editable"] for node in texts))
        self.assertEqual(texts[0]["text"]["direction"], "rtl")
        self.assertEqual(texts[0]["text"]["align"], "right")


if __name__ == "__main__":
    unittest.main()
