import json
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from PIL import Image, ImageDraw

from container.app.schemas import validate_scene_graph
from container.app.renderer import (
    _anchor_to_first_page,
    _office_endpoint,
    inspect_rendered_docx,
    render_scene,
)
from container.app.server import FidelityValidationError, RenderRequestError, render_request


ROOT = Path(__file__).resolve().parents[2]
SCENE_PATH = ROOT / "container/tests/fixtures/minimal-scene.json"
FAILED_DOCX = ROOT / "container/tests/fixtures/failed.docx"


class NativeRendererTests(unittest.TestCase):
    def test_office_uses_an_isolated_local_pipe(self):
        accept, connection_url = _office_endpoint()
        self.assertTrue(accept.startswith("pipe,name=mimicry_"))
        self.assertEqual(connection_url, "uno:" + accept)
        self.assertNotIn("socket", accept)

    def test_shapes_are_anchored_to_absolute_page_coordinates(self):
        shape = Mock()
        shape.setPropertyValue = Mock()
        fake_uno = Mock()
        fake_uno.Enum.side_effect = lambda namespace, value: (namespace, value)
        fake_uno.getConstantByName.side_effect = lambda name: {
            "com.sun.star.text.HoriOrientation.NONE": 0,
            "com.sun.star.text.VertOrientation.NONE": 0,
            "com.sun.star.text.RelOrientation.PAGE_FRAME": 7,
        }[name]

        with patch("container.app.renderer.uno", fake_uno):
            _anchor_to_first_page(shape)

        assigned = {
            call.args[0]: call.args[1]
            for call in shape.setPropertyValue.call_args_list
        }
        self.assertEqual(assigned["AnchorPageNo"], 1)
        self.assertEqual(assigned["HoriOrient"], 0)
        self.assertEqual(assigned["VertOrient"], 0)
        self.assertEqual(assigned["HoriOrientRelation"], 7)
        self.assertEqual(assigned["VertOrientRelation"], 7)
        self.assertEqual(
            assigned["Surround"],
            ("com.sun.star.text.WrapTextMode", "THROUGH"),
        )

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
            self.assertIn("package_audit", artifact.manifest)
            audit = artifact.manifest["package_audit"]
            self.assertTrue(audit["audit_complete"], audit)
            self.assertEqual(audit["native_text_regions"], 2, audit)
            self.assertGreaterEqual(audit["native_shape_objects"], 5, audit)
            self.assertEqual(audit["embedded_image_objects"], 1, audit)
            self.assertEqual(audit["largest_unjustified_raster_ratio"], 0.0, audit)
            self.assertEqual(audit["total_unjustified_raster_ratio"], 0.0, audit)
            self.assertFalse(audit["source_reference_embedded"], audit)
            self.assertFalse(audit["monolithic_flattened_object"], audit)
            self.assertEqual(audit["visible_text_native_ratio"], 1.0, audit)
            self.assertEqual(audit["scene_node_coverage"], 1.0, audit)
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

    def test_full_page_reference_image_is_detected_from_saved_docx_package(self):
        scene = validate_scene_graph(
            {
                "version": "scene-graph.v1",
                "page": {
                    "width": 297,
                    "height": 210,
                    "orientation": "landscape",
                },
                "nodes": [
                    {
                        "id": "flattened-page",
                        "type": "image",
                        "bbox": [0.0, 0.0, 1.0, 1.0],
                        "crop": [0.0, 0.0, 1.0, 1.0],
                        "content_ref": "reference",
                        "raster_justification": "source_artwork",
                        "z": 1,
                        "editable": True,
                        "style": {
                            "fill": None,
                            "stroke": None,
                            "stroke_width": 0,
                            "corner_radius": 0,
                            "opacity": 1,
                        },
                    }
                ],
                "constraints": [],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            reference = workspace / "reference.jpg"
            self._reference(reference)
            artifact = render_scene(scene, reference, workspace)

        audit = artifact.manifest["package_audit"]
        self.assertTrue(audit["source_reference_embedded"], audit)
        self.assertGreaterEqual(audit["largest_unjustified_raster_ratio"], 0.95)
        self.assertGreaterEqual(audit["total_unjustified_raster_ratio"], 0.95)

    def test_raster_tiles_cannot_evade_full_page_detection(self):
        nodes = []
        for index, (x, y) in enumerate(
            ((0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5))
        ):
            nodes.append(
                {
                    "id": "tile-%d" % index,
                    "type": "image",
                    "bbox": [x, y, 0.5, 0.5],
                    "crop": [x, y, 0.5, 0.5],
                    "content_ref": "reference",
                    "raster_justification": "source_artwork",
                    "z": index,
                    "editable": True,
                    "style": {
                        "fill": None,
                        "stroke": None,
                        "stroke_width": 0,
                        "corner_radius": 0,
                        "opacity": 1,
                    },
                }
            )
        scene = validate_scene_graph(
            {
                "version": "scene-graph.v1",
                "page": {
                    "width": 297,
                    "height": 210,
                    "orientation": "landscape",
                },
                "nodes": nodes,
                "constraints": [],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            reference = workspace / "reference.jpg"
            self._reference(reference)
            artifact = render_scene(scene, reference, workspace)

        audit = artifact.manifest["package_audit"]
        self.assertTrue(audit["raster_tiling_detected"], audit)
        self.assertEqual(audit["unjustified_raster_objects"], 4, audit)
        self.assertGreaterEqual(audit["total_unjustified_raster_ratio"], 0.99)

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

    def test_failed_fidelity_retains_only_a_diagnostic_preview(self):
        scene_bytes = SCENE_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.jpg"
            self._reference(reference)
            with patch(
                "container.app.server.validate_fidelity",
                return_value={
                    "status": "FAIL",
                    "gates": {"V_STRUCTURE": False},
                    "findings": [{"gate": "V_STRUCTURE", "node_ids": []}],
                    "correction_hints": [],
                },
            ):
                with self.assertRaises(FidelityValidationError) as raised:
                    render_request(
                        scene_bytes,
                        reference.name,
                        reference.read_bytes(),
                        Path(directory),
                    )
        self.assertTrue(raised.exception.preview_bytes.startswith(b"\xff\xd8\xff"))
        self.assertLessEqual(len(raised.exception.preview_bytes), 64 * 1024)

    def test_inconclusive_editability_uses_validation_incomplete_status(self):
        scene_bytes = SCENE_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.jpg"
            self._reference(reference)
            with patch(
                "container.app.server.validate_fidelity",
                return_value={
                    "status": "VALIDATION_INCOMPLETE",
                    "gates": {
                        "G_PACKAGE_MEDIA_AUDIT": False,
                        "S_EDITABILITY": False,
                    },
                    "findings": [
                        {
                            "gate": "G_PACKAGE_MEDIA_AUDIT",
                            "measured": {"audit_complete": False},
                            "required": {"audit_complete": True},
                            "node_ids": [],
                        }
                    ],
                    "correction_hints": [],
                },
            ):
                with self.assertRaises(FidelityValidationError) as raised:
                    render_request(
                        scene_bytes,
                        reference.name,
                        reference.read_bytes(),
                        Path(directory),
                    )

        self.assertEqual(raised.exception.code, "VALIDATION_INCOMPLETE")

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
