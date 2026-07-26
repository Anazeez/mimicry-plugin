#!/usr/bin/env python3
"""Regression tests for Artifact Mimicry's output and geometry gates."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
from validate_blueprint import validate  # noqa: E402


def valid_blueprint():
    features = [
        {
            "id": "capsules",
            "primitive": "capsule",
            "definingGeometry": "isolated fully rounded slots",
            "critical": True,
        },
        {
            "id": "weekday",
            "primitive": "rounded-rectangle",
            "definingGeometry": "dark rounded headers",
            "critical": True,
        },
        {
            "id": "times",
            "primitive": "capsule",
            "definingGeometry": "mint time capsules",
            "critical": True,
        },
        {
            "id": "spacing",
            "primitive": "gap",
            "definingGeometry": "consistent independent spacing",
            "critical": True,
        },
        {
            "id": "background",
            "primitive": "polygon",
            "definingGeometry": "layered dark green field",
            "critical": True,
        },
    ]
    return {
        "version": "2.0",
        "source": {"kind": "image", "format": "jpg"},
        "target": {"family": "document", "application": "word"},
        "canvas": {"width": 11.69, "height": 8.27, "unit": "in"},
        "direction": "rtl",
        "palette": [],
        "typography": [],
        "regions": [
            {
                "id": "schedule",
                "role": "timetable",
                "bounds": {"x": 0.5, "y": 2.0, "width": 10.5, "height": 5.5},
                "direction": "rtl",
            }
        ],
        "repeatedStructures": [],
        "substitutions": [],
        "intentLock": {
            "invokedSkill": "mimicry",
            "requestedArtifactClass": "document",
            "requestedFormat": "docx",
            "editable": True,
            "flatImageExplicit": False,
        },
        "signatureFeatures": features,
        "constructionPlan": [
            {
                "signatureFeatureId": item["id"],
                "nativePrimitive": "rounded-shape"
                if item["primitive"] in {"capsule", "rounded-rectangle"}
                else "editable-shape",
                "editable": True,
                "preservesGeometry": True,
            }
            for item in features
        ],
        "validation": {
            "correctArtifactType": True,
            "editable": True,
            "rendered": True,
            "signatureGeometryScore": 94,
            "overallFidelityScore": 90,
            "materialFailures": [],
        },
    }


class MimicryRegressions(unittest.TestCase):
    def test_image_reference_routes_to_editable_docx(self):
        self.assertEqual(validate(valid_blueprint()), [])

    def test_flat_output_fails_without_explicit_image_request(self):
        blueprint = valid_blueprint()
        blueprint["intentLock"]["editable"] = False
        self.assertTrue(any("editable" in error for error in validate(blueprint)))

    def test_capsules_cannot_downgrade_to_table_cells(self):
        blueprint = valid_blueprint()
        blueprint["constructionPlan"][0]["nativePrimitive"] = "table-cell"
        self.assertTrue(any("table-cell" in error for error in validate(blueprint)))

    def test_semantic_timetable_can_use_rounded_shapes(self):
        blueprint = valid_blueprint()
        self.assertFalse(any("timetable" in error for error in validate(blueprint)))

    def test_unrendered_artifact_cannot_pass_delivery_gate(self):
        blueprint = valid_blueprint()
        blueprint["validation"]["rendered"] = False
        self.assertTrue(any("rendered" in error for error in validate(blueprint)))


if __name__ == "__main__":
    unittest.main()
