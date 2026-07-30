import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from container.app.extractor import (
    _expand_boundary_artwork,
    _text_width_units,
    extract_scene_graph,
)
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

    def test_dense_banner_text_is_native_and_its_flat_panel_is_not_rasterized(self):
        """Catches removal of the dense PSM-6 recovery and panel separation."""

        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            image = Image.new("RGB", (800, 400), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((30, 24, 500, 72), fill="#f7dfd5")
            draw.rectangle((80, 40, 450, 54), fill="#222222")
            image.save(reference)
            header = (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext\n"
            )
            dense = (
                header
                + "5\t1\t1\t1\t1\t1\t80\t40\t110\t14\t92\tاجتماعات\n"
                + "5\t1\t1\t1\t1\t2\t205\t40\t90\t14\t92\tتعاونية\n"
                + "5\t1\t1\t1\t1\t3\t310\t40\t140\t14\t92\tأفضل\n"
            )

            def tsv_for_mode(_, psm=11):
                return dense if psm == 6 else header

            with patch("container.app.extractor._ocr_tsv", side_effect=tsv_for_mode):
                scene = validate_scene_graph(extract_scene_graph(reference))

        text_nodes = [node for node in scene["nodes"] if node["type"] == "text"]
        self.assertEqual(len(text_nodes), 1)
        self.assertIn("اجتماعات", text_nodes[0]["text"]["value"])
        self.assertTrue(
            any(
                node["type"] == "rectangle"
                and node["bbox"][0] <= 30 / 800 + 0.01
                and node["bbox"][2] >= 450 / 800
                for node in scene["nodes"]
            ),
            scene,
        )
        self.assertFalse(
            any(
                node["type"] == "image"
                and node["bbox"][0] < 0.65
                and node["bbox"][1] < 0.20
                for node in scene["nodes"]
            ),
            scene,
        )

    def test_flat_band_does_not_fuse_multiple_portraits_into_one_raster_strip(self):
        """Catches treating a structural band plus visual islands as one image."""

        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            image = Image.new("RGB", (900, 450), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((40, 130, 860, 168), fill="#f3d8c8")
            draw.line((40, 166, 860, 166), fill="#e8a181", width=3)
            for center, color in (((210, 149), "#e9a36f"), ((690, 149), "#4f7792")):
                x, y = center
                draw.ellipse((x - 16, y - 16, x + 16, y + 16), fill=color)
                draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill="#f4d2bb")
            image.save(reference)

            with patch("container.app.extractor._ocr_tsv", return_value=""):
                scene = validate_scene_graph(extract_scene_graph(reference))

        image_nodes = [node for node in scene["nodes"] if node["type"] == "image"]
        self.assertFalse(any(node["bbox"][2] > 0.50 for node in image_nodes), scene)
        self.assertGreaterEqual(len(image_nodes), 2, scene)

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

    def test_ocr_font_is_capped_to_narrow_box_width(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            Image.new("RGB", (1280, 688), "white").save(reference)
            tsv = (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext\n"
                "5\t1\t1\t1\t1\t1\t957\t65\t10\t29\t95\t1\n"
                "5\t1\t1\t1\t1\t2\t972\t65\t38\t29\t95\tيونيو\n"
                "5\t1\t1\t1\t1\t3\t1015\t65\t27\t29\t95\t2025\n"
            )
            with patch("container.app.extractor._ocr_tsv", return_value=tsv):
                scene = validate_scene_graph(extract_scene_graph(reference))

        text = next(node for node in scene["nodes"] if node["type"] == "text")
        page_width_points = scene["page"]["width"] * 72 / 25.4
        box_width_points = text["bbox"][2] * page_width_points
        expected_width_cap = (
            box_width_points * 0.86 / _text_width_units(text["text"]["value"])
        )
        self.assertLessEqual(
            text["text"]["font_size_pt"],
            expected_width_cap + 0.01,
        )
        self.assertLess(text["text"]["font_size_pt"], 12)

    def test_near_aligned_date_words_remain_on_one_native_line(self):
        """Catches splitting one visual date line into clipped Word lines."""

        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            Image.new("RGB", (800, 400), "white").save(reference)
            tsv = (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext\n"
                "5\t1\t1\t1\t1\t1\t500\t61\t20\t10\t95\t1\n"
                "5\t1\t1\t1\t1\t2\t525\t40\t70\t30\t95\tيونيو\n"
                "5\t1\t1\t1\t1\t3\t600\t61\t55\t10\t95\t2025\n"
            )
            with patch("container.app.extractor._ocr_tsv", return_value=tsv):
                scene = validate_scene_graph(extract_scene_graph(reference))

        text = next(node for node in scene["nodes"] if node["type"] == "text")
        self.assertNotIn("\n", text["text"]["value"])

    def test_dense_recovery_uses_a_portable_width_safety_margin(self):
        """Catches Word wrapping a recovered long banner line after round-trip."""

        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            Image.new("RGB", (800, 400), "white").save(reference)
            header = (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext\n"
            )
            dense = (
                header
                + "5\t1\t1\t1\t1\t1\t60\t40\t90\t18\t95\tالاجتماعات\n"
                + "5\t1\t1\t1\t1\t2\t160\t40\t90\t18\t95\tالتعاونية\n"
                + "5\t1\t1\t1\t1\t3\t260\t40\t90\t18\t95\tهي\n"
                + "5\t1\t1\t1\t1\t4\t360\t40\t90\t18\t95\tالأفضل\n"
                + "5\t1\t1\t1\t1\t5\t460\t40\t90\t18\t95\tشارك\n"
                + "5\t1\t1\t1\t1\t6\t560\t40\t90\t18\t95\tزملاءك\n"
            )

            def tsv_for_mode(_, psm=11):
                return dense if psm == 6 else header

            with patch("container.app.extractor._ocr_tsv", side_effect=tsv_for_mode):
                scene = validate_scene_graph(extract_scene_graph(reference))

        text = next(node for node in scene["nodes"] if node["type"] == "text")
        self.assertLessEqual(text["text"]["font_size_pt"], 17.5)

    def test_text_width_estimate_handles_mixed_scripts_and_multiline_text(self):
        self.assertGreater(
            _text_width_units("2025 يونيو"),
            _text_width_units("2025"),
        )
        self.assertLess(_text_width_units("اكتب هنا"), 4)
        self.assertEqual(
            _text_width_units("short\n2025 يونيو"),
            _text_width_units("2025 يونيو"),
        )


if __name__ == "__main__":
    unittest.main()
