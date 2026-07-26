#!/usr/bin/env python3
"""Validate the required structure of a Mimicry Blueprint without dependencies."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REQUIRED = {
    "version",
    "source",
    "target",
    "canvas",
    "direction",
    "palette",
    "typography",
    "regions",
    "repeatedStructures",
    "substitutions",
    "intentLock",
    "signatureFeatures",
    "constructionPlan",
    "validation",
}
DIRECTIONS = {"ltr", "rtl", "mixed"}
FAMILIES = {"document", "presentation", "spreadsheet"}
APPLICATIONS = {
    "word",
    "powerpoint",
    "excel",
    "google-docs",
    "google-slides",
    "google-sheets",
}


def object_field(value: Any, name: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{name} must be an object")
        return {}
    return value


def validate(data: Any) -> list[str]:
    errors: list[str] = []
    root = object_field(data, "blueprint", errors)
    if not root:
        return errors

    missing = sorted(REQUIRED - root.keys())
    if missing:
        errors.append("missing required fields: " + ", ".join(missing))

    source = object_field(root.get("source"), "source", errors)
    for key in ("kind", "format"):
        if not isinstance(source.get(key), str) or not source.get(key):
            errors.append(f"source.{key} must be a non-empty string")

    target = object_field(root.get("target"), "target", errors)
    if target.get("family") not in FAMILIES:
        errors.append("target.family must be document, presentation, or spreadsheet")
    if target.get("application") not in APPLICATIONS:
        errors.append("target.application is not supported")

    canvas = object_field(root.get("canvas"), "canvas", errors)
    for key in ("width", "height"):
        value = canvas.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            errors.append(f"canvas.{key} must be a positive number")
    if canvas.get("unit") not in {"px", "pt", "in", "mm", "cm", "cell"}:
        errors.append("canvas.unit is not supported")

    if root.get("direction") not in DIRECTIONS:
        errors.append("direction must be ltr, rtl, or mixed")

    for key in ("palette", "typography", "regions", "repeatedStructures", "substitutions"):
        if not isinstance(root.get(key), list):
            errors.append(f"{key} must be an array")

    for index, region_value in enumerate(root.get("regions", [])):
        region = object_field(region_value, f"regions[{index}]", errors)
        for key in ("id", "role"):
            if not isinstance(region.get(key), str) or not region.get(key):
                errors.append(f"regions[{index}].{key} must be a non-empty string")
        if region.get("direction") not in DIRECTIONS:
            errors.append(f"regions[{index}].direction must be ltr, rtl, or mixed")
        bounds = object_field(region.get("bounds"), f"regions[{index}].bounds", errors)
        for key in ("x", "y", "width", "height"):
            value = bounds.get(key)
            positive = key in {"width", "height"}
            invalid = (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or (positive and value <= 0)
                or (not positive and value < 0)
            )
            if invalid:
                qualifier = "positive" if positive else "non-negative"
                errors.append(f"regions[{index}].bounds.{key} must be a {qualifier} number")

    if root.get("direction") == "mixed" and isinstance(root.get("regions"), list):
        region_directions = {
            region.get("direction") for region in root["regions"] if isinstance(region, dict)
        }
        if not {"ltr", "rtl"}.issubset(region_directions):
            errors.append("mixed blueprints require at least one ltr and one rtl region")

    intent = object_field(root.get("intentLock"), "intentLock", errors)
    if intent.get("invokedSkill") != "mimicry":
        errors.append("intentLock.invokedSkill must be mimicry")
    if not isinstance(intent.get("requestedFormat"), str) or not intent.get("requestedFormat"):
        errors.append("intentLock.requestedFormat must be a non-empty string")
    if not isinstance(intent.get("flatImageExplicit"), bool):
        errors.append("intentLock.flatImageExplicit must be boolean")
    if not isinstance(intent.get("editable"), bool):
        errors.append("intentLock.editable must be boolean")
    elif not intent.get("flatImageExplicit") and not intent.get("editable"):
        errors.append("editable artifact output is required unless a flat image was explicit")

    features = root.get("signatureFeatures")
    if not isinstance(features, list) or len(features) < 5:
        errors.append("signatureFeatures must contain at least five features")
        features = []
    critical_primitives = {}
    for index, feature_value in enumerate(features):
        feature = object_field(feature_value, f"signatureFeatures[{index}]", errors)
        feature_id = feature.get("id")
        primitive = feature.get("primitive")
        if not isinstance(feature_id, str) or not feature_id:
            errors.append(f"signatureFeatures[{index}].id must be a non-empty string")
        if not isinstance(primitive, str) or not primitive:
            errors.append(f"signatureFeatures[{index}].primitive must be a non-empty string")
        if feature.get("critical") is True and isinstance(feature_id, str):
            critical_primitives[feature_id] = primitive

    plan = root.get("constructionPlan")
    if not isinstance(plan, list):
        errors.append("constructionPlan must be an array")
        plan = []
    covered = set()
    for index, item_value in enumerate(plan):
        item = object_field(item_value, f"constructionPlan[{index}]", errors)
        feature_id = item.get("signatureFeatureId")
        primitive = item.get("nativePrimitive")
        if isinstance(feature_id, str):
            covered.add(feature_id)
        if item.get("editable") is not True:
            errors.append(f"constructionPlan[{index}] must remain editable")
        if item.get("preservesGeometry") is not True:
            errors.append(f"constructionPlan[{index}] must preserve geometry")
        if (
            critical_primitives.get(feature_id) in {"capsule", "pill", "rounded-rectangle"}
            and primitive in {"table-cell", "rectangular-cell", "flattened-image"}
        ):
            errors.append(
                f"constructionPlan[{index}] cannot use {primitive} for signature rounded geometry"
            )
    missing_critical = sorted(set(critical_primitives) - covered)
    if missing_critical:
        errors.append("constructionPlan does not cover: " + ", ".join(missing_critical))

    gate = object_field(root.get("validation"), "validation", errors)
    for key in ("correctArtifactType", "editable", "rendered"):
        if gate.get(key) is not True:
            errors.append(f"validation.{key} must pass")
    signature_score = gate.get("signatureGeometryScore")
    if not isinstance(signature_score, (int, float)) or signature_score < 90:
        errors.append("validation.signatureGeometryScore must be at least 90")
    overall_score = gate.get("overallFidelityScore")
    if not isinstance(overall_score, (int, float)) or overall_score < 85:
        errors.append("validation.overallFidelityScore must be at least 85")
    failures = gate.get("materialFailures")
    if not isinstance(failures, list) or failures:
        errors.append("validation.materialFailures must be an empty array")

    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_blueprint.py BLUEPRINT.json", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"invalid blueprint: {exc}", file=sys.stderr)
        return 1
    errors = validate(data)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
