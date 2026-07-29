import json
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw

from container.app.schemas import validate_scene_graph
from container.app.renderer import render_scene, inspect_rendered_docx
from container.app.server import RenderRequestError, render_request


ROOT = Path(__file__).resolve().parents[2]
SCENE_PATH = ROOT / "container/tests/fixtures/minimal-scene.json"
FAILED_DOCX = ROOT / "fixtures/meeting-grid/failed.docx"


class NativeRendererTests(unittest.TestCase):
    def _reference(self, path):
        image = Image.new("RGB", (800, 560), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((250, 40, 550, 300), fill="#147D6F")
        draw.ellipse((330, 90, 470, 230), fill="#F7EEE8")
        image.save(path, "JPEG", quality=92)

    def test_native_docx_reopens_and_renders(self):
        scene = validate_scene_graph(json.loads(SCENE_PATH.read_text()))
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            reference = workspace / "reference.jpg"
            self._reference(reference)

            artifact = render_scene(scene, reference, workspace)

            self.assertTrue(artifact.docx_path.is_file())
            self.assertTrue(artifact.pdf_path.is_file())
            self.assertTrue(artifact.png_path.is_file())
            self.assertEqual(artifact.manifest["page_count"], 1)
            self.assertGreaterEqual(artifact.manifest["native_shape_count"], 6)
            self.assertEqual(artifact.manifest["image_object_count"], 1)
            self.assertEqual(artifact.manifest["full_page_image_count"], 0)
            self.assertIn(1.5, artifact.manifest["stroke_widths"])
            self.assertIn("#201b19", artifact.manifest["text_colors"])
            self.assertIn("rtl-title", artifact.manifest["rtl_text_nodes"])
            actual = {
                node["id"]: node["bbox"] for node in artifact.manifest["actual_nodes"]
            }
            self.assertEqual(set(actual), {
                "panel-left",
                "panel-right",
                "rtl-title",
                "english-title",
                "divider",
                "portrait",
            })
            for expected in scene["nodes"]:
                for observed_value, expected_value in zip(
                    actual[expected["id"]], expected["bbox"]
                ):
                    self.assertAlmostEqual(observed_value, expected_value, delta=0.02)

            rendered = Image.open(artifact.png_path).convert("RGB")
            nonwhite = sum(
                1 for pixel in rendered.getdata() if min(pixel) < 245
            )
            self.assertGreater(nonwhite / (rendered.width * rendered.height), 0.05)

            with zipfile.ZipFile(artifact.docx_path) as archive:
                xml = "\n".join(
                    archive.read(name).decode("utf-8", "ignore")
                    for name in archive.namelist()
                    if name.endswith(".xml")
                )
            self.assertIn("اجتماع يومي", xml)
            self.assertNotIn("reference-full-page", xml)

    def test_supplied_failed_docx_is_rejected_as_blank_after_reopen(self):
        if not shutil.which("libreoffice"):
            self.skipTest("LibreOffice is required")
        with tempfile.TemporaryDirectory() as directory:
            report = inspect_rendered_docx(FAILED_DOCX, Path(directory))
        self.assertFalse(report["accepted"])
        self.assertIn("R_NONBLANK", report["failed_gates"])

    def test_container_boundary_returns_fresh_render_bundle(self):
        scene_bytes = SCENE_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.jpg"
            self._reference(reference)
            with patch(
                "container.app.server.validate_fidelity",
                return_value={
                    "status": "PASS",
                    "version": "fidelity-v1",
                    "gates": {"S_EDITABILITY": True},
                    "metrics": {},
                    "findings": [],
                    "correction_hints": [],
                },
            ):
                bundle = render_request(
                    scene_bytes, reference.name, reference.read_bytes(), Path(directory)
                )
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"artifact.docx", "artifact.pdf", "artifact.png", "manifest.json"},
            )
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["page_count"], 1)
        self.assertGreater(manifest["nonwhite_ratio"], 0.05)
        self.assertEqual(manifest["fidelity"]["status"], "PASS")

    def test_container_boundary_rejects_oversized_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RenderRequestError) as raised:
                render_request(
                    SCENE_PATH.read_bytes(),
                    "reference.jpg",
                    b"\xff\xd8\xff" + b"x" * (20 * 1024 * 1024),
                    Path(directory),
                )
        self.assertEqual(raised.exception.code, "REQUEST_TOO_LARGE")


if __name__ == "__main__":
    unittest.main()
