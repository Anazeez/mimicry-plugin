import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from container.app.extractor import _expand_boundary_artwork, extract_scene_graph
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
        vertical = [node for node in scene["nodes"] if node["id"].startswith("grid-v-")]
        horizontal = [node for node in scene["nodes"] if node["id"].startswith("grid-h-")]
        self.assertEqual((len(horizontal), len(vertical)), (4, 7))
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

    def test_grid_words_are_grouped_per_cell_and_centered(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            image = Image.new("RGB", (600, 400), "white")
            draw = ImageDraw.Draw(image)
            for x in (20, 200, 380, 580):
                draw.line((x, 100, x, 380), fill="#d98f70", width=3)
            for y in (100, 240, 380):
                draw.line((20, y, 580, y), fill="#d98f70", width=3)
            image.save(reference)
            tsv = (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext\n"
                "5\t1\t1\t1\t1\t1\t300\t140\t50\t30\t92\tاكتب\n"
                "5\t1\t1\t1\t1\t2\t225\t140\t50\t30\t93\tهنا\n"
                "5\t1\t1\t1\t1\t3\t110\t140\t45\t30\t91\tDaily\n"
            )
            with patch("container.app.extractor._ocr_tsv", return_value=tsv):
                scene = validate_scene_graph(extract_scene_graph(reference))

        texts = [node for node in scene["nodes"] if node["type"] == "text"]
        self.assertEqual(len(texts), 2)
        arabic = next(node for node in texts if "اكتب" in node["text"]["value"])
        self.assertEqual(arabic["text"]["align"], "center")
        self.assertLess(arabic["bbox"][0], 0.38)
        self.assertGreater(arabic["bbox"][0] + arabic["bbox"][2], 0.58)

    def test_colorful_single_character_artwork_is_not_emitted_as_text(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            image = Image.new("RGB", (300, 300), "white")
            draw = ImageDraw.Draw(image)
            for index, color in enumerate(
                ("#f47b42", "#2a8a7a", "#f1d2aa", "#1c3144")
            ):
                draw.rectangle((50 + index * 8, 50, 58 + index * 8, 90), fill=color)
            image.save(reference)
            tsv = (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext\n"
                "5\t1\t1\t1\t1\t1\t48\t48\t50\t50\t95\tA\n"
            )
            with patch("container.app.extractor._ocr_tsv", return_value=tsv):
                scene = validate_scene_graph(extract_scene_graph(reference))

        self.assertFalse(any(node["type"] == "text" for node in scene["nodes"]))

    def test_repeated_cell_text_edges_do_not_replace_true_grid_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            image = Image.new("RGB", (800, 500), "white")
            draw = ImageDraw.Draw(image)
            vertical = (30, 215, 400, 585, 770)
            horizontal = (160, 270, 380, 480)
            for x in vertical:
                draw.line((x, horizontal[0], x, horizontal[-1]), fill="#d98f70", width=3)
            for y in horizontal:
                draw.line((vertical[0], y, vertical[-1], y), fill="#d98f70", width=3)
            # A wide header decoration and repeated text baselines are not grid rules.
            draw.line((30, 50, 560, 50), fill="#d98f70", width=3)
            for y in (220, 330, 440):
                for x in range(55, 745, 185):
                    draw.line((x, y, x + 100, y), fill="#111111", width=5)
            image.save(reference)
            with patch("container.app.extractor._ocr_tsv", return_value=""):
                scene = validate_scene_graph(extract_scene_graph(reference))

        horizontal_nodes = [
            node for node in scene["nodes"] if node["id"].startswith("grid-h-")
        ]
        self.assertEqual(len(horizontal_nodes), 4)
        self.assertAlmostEqual(horizontal_nodes[0]["bbox"][1], 160 / 500, places=2)

    def test_artwork_straddling_a_grid_boundary_is_preserved_whole(self):
        x, width, expanded = _expand_boundary_artwork(
            575, 20, 50, [20, 200, 380, 570], 600
        )
        self.assertTrue(expanded)
        self.assertLess(x, 570)
        self.assertGreater(x + width, 570)

    def test_page_geometry_preserves_reference_aspect_ratio(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            Image.new("RGB", (1280, 688), "white").save(reference)
            with patch("container.app.extractor._ocr_tsv", return_value=""):
                scene = validate_scene_graph(extract_scene_graph(reference))

        self.assertAlmostEqual(
            scene["page"]["width"] / scene["page"]["height"],
            1280 / 688,
            places=3,
        )

    def test_ocr_font_size_is_resolution_independent(self):
        tsv_template = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
            "left\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t{left}\t{top}\t{width}\t{height}\t95\tاجتماع\n"
        )
        sizes = []
        for image_width, image_height in ((640, 344), (1280, 688)):
            with tempfile.TemporaryDirectory() as directory:
                reference = Path(directory) / "reference.png"
                Image.new("RGB", (image_width, image_height), "white").save(reference)
                tsv = tsv_template.format(
                    left=image_width // 2,
                    top=image_height // 10,
                    width=image_width // 5,
                    height=image_height // 20,
                )
                with patch("container.app.extractor._ocr_tsv", return_value=tsv):
                    scene = validate_scene_graph(extract_scene_graph(reference))
            text = next(node for node in scene["nodes"] if node["type"] == "text")
            sizes.append(text["text"]["font_size_pt"])

        self.assertAlmostEqual(sizes[0], sizes[1], places=2)
        self.assertGreaterEqual(sizes[0], 12)

    def test_ocr_font_is_capped_to_the_measured_word_text_box(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            Image.new("RGB", (1280, 688), "white").save(reference)
            tsv = (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext\n"
                "5\t1\t1\t1\t1\t1\t957\t65\t91\t29\t95\t2025\n"
                "5\t1\t1\t1\t1\t2\t1000\t65\t48\t29\t95\tيونيو\n"
            )
            with patch("container.app.extractor._ocr_tsv", return_value=tsv):
                scene = validate_scene_graph(extract_scene_graph(reference))

        text = next(node for node in scene["nodes"] if node["type"] == "text")
        page_height_points = (
            scene["page"]["height"] * 72 / 25.4
        )
        box_height_points = text["bbox"][3] * page_height_points
        self.assertLessEqual(
            text["text"]["font_size_pt"],
            box_height_points * 0.92 + 0.01,
        )


if __name__ == "__main__":
    unittest.main()
