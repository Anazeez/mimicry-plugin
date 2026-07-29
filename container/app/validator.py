"""Independent structural, geometric, and raster fidelity gates."""

import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image, ImageFilter, ImageStat


CONFIG_PATH = Path(__file__).with_name("fidelity-v1.json")


def _load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _normalized_image(path, size):
    with Image.open(path) as image:
        resampling = getattr(Image, "Resampling", Image)
        return image.convert("RGB").resize(size, resampling.LANCZOS)


def _nonwhite_ratio(image):
    count = image.width * image.height
    try:
        import numpy

        pixels = numpy.asarray(image.convert("RGB"))
        return float((pixels.min(axis=2) < 245).mean()) if count else 0
    except ImportError:
        pass
    return (
        sum(1 for red, green, blue in image.getdata() if min(red, green, blue) < 245)
        / count
        if count
        else 0
    )


def _bbox_error(expected, actual):
    return max(abs(float(left) - float(right)) for left, right in zip(expected, actual))


def _relationship_error(kind, source, target):
    sx, sy, sw, sh = source
    tx, ty, tw, th = target
    values = {
        "inside": max(tx - sx, ty - sy, sx + sw - tx - tw, sy + sh - ty - th, 0),
        "align_left": abs(sx - tx),
        "align_right": abs(sx + sw - tx - tw),
        "align_top": abs(sy - ty),
        "align_bottom": abs(sy + sh - ty - th),
        "align_center_x": abs(sx + sw / 2 - tx - tw / 2),
        "align_center_y": abs(sy + sh / 2 - ty - th / 2),
        "adjacent_x": min(abs(sx + sw - tx), abs(tx + tw - sx)),
        "adjacent_y": min(abs(sy + sh - ty), abs(ty + th - sy)),
        "equal_width": abs(sw - tw),
        "equal_height": abs(sh - th),
        "gap_x": min(abs(sx + sw - tx), abs(tx + tw - sx)),
        "gap_y": min(abs(sy + sh - ty), abs(ty + th - sy)),
    }
    return values[kind]


def _crop(image, bbox):
    x, y, width, height = bbox
    return image.crop(
        (
            max(0, int(round(x * image.width))),
            max(0, int(round(y * image.height))),
            min(image.width, int(round((x + width) * image.width))),
            min(image.height, int(round((y + height) * image.height))),
        )
    )


def _percentile(values, fraction):
    if not values:
        return 255
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction)))]


def _relative_luminance(value):
    channel = value / 255
    linear = channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
    return linear


def _contrast_ratio(image, bbox, align="center"):
    x, y, width, height = bbox
    if align == "left":
        sample = [x, y, width * 0.75, height]
    elif align == "right":
        sample = [x + width * 0.25, y, width * 0.75, height]
    else:
        sample = [x + width * 0.125, y, width * 0.75, height]
    crop = _crop(image, sample).convert("L")
    values = list(crop.getdata())
    dark = _percentile(values, 0.002)
    light = _percentile(values, 0.998)
    low = _relative_luminance(dark)
    high = _relative_luminance(light)
    return (high + 0.05) / (low + 0.05)


def _border_coverage(image, bbox):
    crop = _crop(image, bbox).convert("L")
    if crop.width < 3 or crop.height < 3:
        return 0
    band = max(2, int(round(min(crop.width, crop.height) * 0.015)))
    samples = []
    samples.extend(crop.crop((0, 0, crop.width, band)).getdata())
    samples.extend(crop.crop((0, crop.height - band, crop.width, crop.height)).getdata())
    samples.extend(crop.crop((0, 0, band, crop.height)).getdata())
    samples.extend(crop.crop((crop.width - band, 0, crop.width, crop.height)).getdata())
    return sum(1 for value in samples if value < 225) / len(samples)


def _edge_mask(image):
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    return [value > 24 for value in edges.getdata()]


def _edge_f1(reference, rendered):
    try:
        import numpy

        left = numpy.asarray(reference.convert("L").filter(ImageFilter.FIND_EDGES)) > 24
        right = numpy.asarray(rendered.convert("L").filter(ImageFilter.FIND_EDGES)) > 24
        true_positive = int(numpy.logical_and(left, right).sum())
        predicted = int(right.sum())
        expected = int(left.sum())
        if predicted == 0 and expected == 0:
            return 1
        precision = true_positive / predicted if predicted else 0
        recall = true_positive / expected if expected else 0
        return 2 * precision * recall / (precision + recall) if precision + recall else 0
    except ImportError:
        pass
    left = _edge_mask(reference)
    right = _edge_mask(rendered)
    true_positive = sum(1 for a, b in zip(left, right) if a and b)
    predicted = sum(right)
    expected = sum(left)
    if predicted == 0 and expected == 0:
        return 1
    precision = true_positive / predicted if predicted else 0
    recall = true_positive / expected if expected else 0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0


def _palette_distance(reference, rendered):
    left = ImageStat.Stat(reference).mean
    right = ImageStat.Stat(rendered).mean
    return sum(abs(a - b) for a, b in zip(left, right)) / (3 * 255)


def _ssim(reference, rendered):
    # Compare page-scale hierarchy rather than font rasterization noise. Fine
    # edges are judged separately by V_EDGE_SIMILARITY.
    radius = max(1, min(reference.size) / 150)
    reference = reference.filter(ImageFilter.GaussianBlur(radius))
    rendered = rendered.filter(ImageFilter.GaussianBlur(radius))
    try:
        import numpy

        left = numpy.asarray(reference.convert("L"), dtype="float64") / 255
        right = numpy.asarray(rendered.convert("L"), dtype="float64") / 255
        if not left.size:
            return 0
        mean_left, mean_right = float(left.mean()), float(right.mean())
        variance_left, variance_right = float(left.var()), float(right.var())
        covariance = float(((left - mean_left) * (right - mean_right)).mean())
        c1, c2 = 0.01 ** 2, 0.03 ** 2
        return (
            (2 * mean_left * mean_right + c1)
            * (2 * covariance + c2)
            / (
                (mean_left ** 2 + mean_right ** 2 + c1)
                * (variance_left + variance_right + c2)
            )
        )
    except ImportError:
        pass
    left = [value / 255 for value in reference.convert("L").getdata()]
    right = [value / 255 for value in rendered.convert("L").getdata()]
    count = len(left)
    if not count:
        return 0
    mean_left = sum(left) / count
    mean_right = sum(right) / count
    variance_left = sum((value - mean_left) ** 2 for value in left) / count
    variance_right = sum((value - mean_right) ** 2 for value in right) / count
    covariance = sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(left, right)
    ) / count
    c1 = 0.01 ** 2
    c2 = 0.03 ** 2
    return (
        (2 * mean_left * mean_right + c1)
        * (2 * covariance + c2)
        / (
            (mean_left ** 2 + mean_right ** 2 + c1)
            * (variance_left + variance_right + c2)
        )
    )


def _ocr_word_count(path):
    if not shutil.which("tesseract"):
        return None
    with tempfile.TemporaryDirectory(prefix="mimicry-ocr-") as directory:
        prefix = Path(directory) / "ocr"
        result = subprocess.run(
            ["tesseract", str(path), str(prefix), "-l", "eng+ara", "tsv"],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        tsv = prefix.with_suffix(".tsv")
        if not tsv.exists():
            return None
        return sum(
            1
            for line in tsv.read_text("utf-8", "ignore").splitlines()[1:]
            if len(line.split("\t")) >= 12 and line.split("\t")[11].strip()
        )


def validate_fidelity(reference_path, rendered_path, scene, manifest):
    """Return a fail-closed report based on the saved artifact's actual render."""

    config = _load_config()
    thresholds = config["thresholds"]
    with Image.open(reference_path) as source:
        size = (max(300, source.width), max(200, source.height))
        reference_aspect = source.width / source.height
    reference = _normalized_image(reference_path, size)
    rendered = _normalized_image(rendered_path, size)

    expected = {node["id"]: node for node in scene["nodes"]}
    actual = {node["id"]: node for node in manifest.get("actual_nodes", [])}
    geometry_errors = {}
    for node_id, node in expected.items():
        geometry_errors[node_id] = (
            _bbox_error(node["bbox"], actual[node_id]["bbox"])
            if node_id in actual
            else 1
        )
    max_geometry_error = max(geometry_errors.values()) if geometry_errors else 0

    relationship_errors = {}
    for index, constraint in enumerate(scene.get("constraints", [])):
        source = actual.get(constraint["source"])
        target = actual.get(constraint["target"])
        relationship_errors[str(index)] = (
            _relationship_error(
                constraint["type"], source["bbox"], target["bbox"]
            )
            if source and target
            else 1
        )
    max_relationship_error = (
        max(relationship_errors.values()) if relationship_errors else 0
    )

    stroked = [
        node
        for node in scene["nodes"]
        if node.get("style", {}).get("stroke")
        and float(node.get("style", {}).get("stroke_width", 0)) > 0
        and node["type"] in {"grid", "rectangle", "rounded_rectangle", "ellipse"}
    ]
    border_coverages = {
        node["id"]: _border_coverage(rendered, node["bbox"]) for node in stroked
    }
    min_border_coverage = (
        min(border_coverages.values()) if border_coverages else 1
    )

    text_nodes = [node for node in scene["nodes"] if node["type"] == "text"]
    contrast_ratios = {
        node["id"]: _contrast_ratio(
            rendered, node["bbox"], node["text"].get("align", "center")
        )
        for node in text_nodes
    }
    min_contrast = min(contrast_ratios.values()) if contrast_ratios else 21

    reference_ocr_words = _ocr_word_count(reference_path)
    rendered_ocr_words = _ocr_word_count(rendered_path)
    ocr_available = (
        isinstance(reference_ocr_words, int)
        and isinstance(rendered_ocr_words, int)
    )
    text_detection_ratio = (
        min(1.0, rendered_ocr_words / reference_ocr_words)
        if ocr_available and reference_ocr_words > 0
        else 1.0
        if ocr_available
        else None
    )
    page_aspect = float(scene["page"]["width"]) / float(scene["page"]["height"])
    page_aspect_error = abs(page_aspect / reference_aspect - 1)

    metrics = {
        "nonwhite_ratio": _nonwhite_ratio(rendered),
        "bbox_max_error": max_geometry_error,
        "bbox_errors": geometry_errors,
        "relationship_max_error": max_relationship_error,
        "relationship_errors": relationship_errors,
        "border_coverage_min": min_border_coverage,
        "border_coverages": border_coverages,
        "contrast_ratio_min": min_contrast,
        "contrast_ratios": contrast_ratios,
        "edge_f1": _edge_f1(reference, rendered),
        "palette_distance": _palette_distance(reference, rendered),
        "ssim": _ssim(reference, rendered),
        "reference_ocr_words": reference_ocr_words,
        "rendered_ocr_words": rendered_ocr_words,
        "text_detection_ratio": text_detection_ratio,
        "page_aspect_error": page_aspect_error,
    }
    audit = manifest.get("package_audit")
    audit_complete = bool(
        isinstance(audit, dict)
        and audit.get("audit_complete") is True
        and audit.get("package_integrity") is not False
    )
    audit = audit if isinstance(audit, dict) else {}
    audit_metric_names = (
        "embedded_image_objects",
        "native_shape_objects",
        "native_text_regions",
        "source_text_regions",
        "visible_text_native_ratio",
        "scene_node_coverage",
        "native_visible_area_ratio",
        "largest_unjustified_raster_ratio",
        "total_unjustified_raster_ratio",
        "unjustified_raster_objects",
        "source_reference_embedded",
        "raster_tiling_detected",
        "monolithic_flattened_object",
    )
    metrics.update({name: audit.get(name) for name in audit_metric_names})

    editability_gates = {
        "G_PACKAGE_MEDIA_AUDIT": audit_complete,
        "G_NO_SOURCE_REFERENCE_EMBED": (
            audit_complete and audit.get("source_reference_embedded") is False
        ),
        "G_NO_FULL_PAGE_RASTER": (
            audit_complete
            and float(audit.get("largest_unjustified_raster_ratio", 1))
            <= thresholds["largest_unjustified_raster_ratio_max"]
            and float(audit.get("total_unjustified_raster_ratio", 1))
            <= thresholds["total_unjustified_raster_ratio_max"]
            and audit.get("raster_tiling_detected") is False
        ),
        "G_VISIBLE_TEXT_NATIVE": (
            audit_complete
            and float(audit.get("visible_text_native_ratio", 0))
            >= thresholds["visible_text_native_ratio_min"]
        ),
        "G_SCENE_NODE_COVERAGE": (
            audit_complete
            and float(audit.get("scene_node_coverage", 0))
            >= thresholds["scene_node_coverage_min"]
        ),
        "G_NATIVE_OBJECT_RATIO": (
            audit_complete
            and float(audit.get("native_visible_area_ratio", 0))
            >= thresholds["native_visible_area_ratio_min"]
        ),
        "G_OBJECT_EDITABILITY": (
            audit_complete
            and audit.get("monolithic_flattened_object") is False
        ),
        "G_RASTER_JUSTIFICATION": (
            audit_complete
            and int(audit.get("unjustified_raster_objects", 1)) == 0
        ),
    }
    editability_gates["S_EDITABILITY"] = all(editability_gates.values())

    gates = {
        **editability_gates,
        "R_NONBLANK": metrics["nonwhite_ratio"] >= thresholds["nonwhite_ratio_min"],
        "R_SINGLE_PAGE": int(manifest.get("page_count", 0)) == 1,
        "G_PAGE_GEOMETRY": (
            page_aspect_error <= thresholds["page_aspect_error_max"]
        ),
        "G_ALIGNMENT": max_geometry_error <= thresholds["bbox_max_error"],
        "G_RELATIONSHIPS": max_relationship_error
        <= thresholds["relationship_max_error"],
        "G_BORDER_CONTINUITY": min_border_coverage
        >= thresholds["border_coverage_min"],
        "V_CONTRAST": min_contrast >= thresholds["contrast_ratio_min"],
        "V_EDGE_SIMILARITY": metrics["edge_f1"] >= thresholds["edge_f1_min"],
        "V_PALETTE": metrics["palette_distance"]
        <= thresholds["palette_distance_max"],
        "V_STRUCTURE": metrics["ssim"] >= thresholds["ssim_min"],
        "V_TEXT_COVERAGE": (
            ocr_available
            and text_detection_ratio >= thresholds["text_detection_ratio_min"]
        ),
    }

    details = {
        "G_PACKAGE_MEDIA_AUDIT": {
            "measured": {
                "audit_complete": audit_complete,
                "package_integrity": audit.get("package_integrity"),
                "audit_error": audit.get("audit_error"),
            },
            "required": {"audit_complete": True, "package_integrity": True},
            "node_ids": [],
        },
        "G_NO_SOURCE_REFERENCE_EMBED": {
            "measured": {
                "source_reference_embedded": audit.get("source_reference_embedded")
            },
            "required": {"source_reference_embedded": False},
            "node_ids": [],
        },
        "G_NO_FULL_PAGE_RASTER": {
            "measured": {
                "largest_unjustified_raster_ratio": audit.get(
                    "largest_unjustified_raster_ratio"
                ),
                "total_unjustified_raster_ratio": audit.get(
                    "total_unjustified_raster_ratio"
                ),
                "raster_tiling_detected": audit.get("raster_tiling_detected"),
            },
            "required": {
                "maximum_largest_ratio": thresholds[
                    "largest_unjustified_raster_ratio_max"
                ],
                "maximum_total_ratio": thresholds[
                    "total_unjustified_raster_ratio_max"
                ],
                "raster_tiling_detected": False,
            },
            "node_ids": [],
        },
        "G_VISIBLE_TEXT_NATIVE": {
            "measured": {
                "native_text_regions": audit.get("native_text_regions"),
                "source_text_regions": audit.get("source_text_regions"),
                "visible_text_native_ratio": audit.get("visible_text_native_ratio"),
            },
            "required": {
                "minimum_ratio": thresholds["visible_text_native_ratio_min"]
            },
            "node_ids": [],
        },
        "G_SCENE_NODE_COVERAGE": {
            "measured": {"scene_node_coverage": audit.get("scene_node_coverage")},
            "required": {
                "minimum_ratio": thresholds["scene_node_coverage_min"]
            },
            "node_ids": [],
        },
        "G_NATIVE_OBJECT_RATIO": {
            "measured": {
                "native_visible_area_ratio": audit.get("native_visible_area_ratio")
            },
            "required": {
                "minimum_ratio": thresholds["native_visible_area_ratio_min"]
            },
            "node_ids": [],
        },
        "G_OBJECT_EDITABILITY": {
            "measured": {
                "monolithic_flattened_object": audit.get(
                    "monolithic_flattened_object"
                )
            },
            "required": {"monolithic_flattened_object": False},
            "node_ids": [],
        },
        "G_RASTER_JUSTIFICATION": {
            "measured": {
                "unjustified_raster_objects": audit.get(
                    "unjustified_raster_objects"
                )
            },
            "required": {"unjustified_raster_objects": 0},
            "node_ids": [],
        },
        "S_EDITABILITY": {
            "measured": {
                "passed_editability_gates": sum(
                    bool(value)
                    for name, value in editability_gates.items()
                    if name != "S_EDITABILITY"
                )
            },
            "required": {
                "required_editability_gates": len(editability_gates) - 1
            },
            "node_ids": list(expected),
        },
        "R_NONBLANK": (
            metrics["nonwhite_ratio"],
            thresholds["nonwhite_ratio_min"],
            [],
        ),
        "R_SINGLE_PAGE": (manifest.get("page_count", 0), 1, []),
        "G_PAGE_GEOMETRY": (
            page_aspect_error,
            thresholds["page_aspect_error_max"],
            [],
        ),
        "G_ALIGNMENT": (
            max_geometry_error,
            thresholds["bbox_max_error"],
            [
                node_id
                for node_id, error in geometry_errors.items()
                if error > thresholds["bbox_max_error"]
            ],
        ),
        "G_RELATIONSHIPS": (
            max_relationship_error,
            thresholds["relationship_max_error"],
            [],
        ),
        "G_BORDER_CONTINUITY": (
            min_border_coverage,
            thresholds["border_coverage_min"],
            [
                node_id
                for node_id, coverage in border_coverages.items()
                if coverage < thresholds["border_coverage_min"]
            ],
        ),
        "V_CONTRAST": (
            min_contrast,
            thresholds["contrast_ratio_min"],
            [
                node_id
                for node_id, ratio in contrast_ratios.items()
                if ratio < thresholds["contrast_ratio_min"]
            ],
        ),
        "V_EDGE_SIMILARITY": (
            metrics["edge_f1"],
            thresholds["edge_f1_min"],
            [],
        ),
        "V_PALETTE": (
            metrics["palette_distance"],
            thresholds["palette_distance_max"],
            [],
        ),
        "V_STRUCTURE": (metrics["ssim"], thresholds["ssim_min"], []),
        "V_TEXT_COVERAGE": {
            "measured": {
                "reference_ocr_words": reference_ocr_words,
                "rendered_ocr_words": rendered_ocr_words,
                "text_detection_ratio": text_detection_ratio,
            },
            "required": {
                "ocr_available": True,
                "minimum_ratio": thresholds["text_detection_ratio_min"],
            },
            "node_ids": [node["id"] for node in text_nodes],
        },
    }
    findings = []
    for gate in config["critical_gates"]:
        if not gates[gate]:
            detail = details[gate]
            if isinstance(detail, tuple):
                observed, threshold, node_ids = detail
                measured = {"value": observed}
                required = {"threshold": threshold}
            else:
                measured = detail["measured"]
                required = detail["required"]
                node_ids = detail["node_ids"]
            findings.append(
                {
                    "gate": gate,
                    "expected": required,
                    "observed": measured,
                    "required": required,
                    "measured": measured,
                    "node_ids": node_ids,
                }
            )

    if all(gates[gate] for gate in config["critical_gates"]):
        status = "PASS"
    elif not audit_complete or not ocr_available:
        status = "VALIDATION_INCOMPLETE"
    elif not editability_gates["S_EDITABILITY"]:
        status = "EDITABILITY_FAILED"
    else:
        status = "FIDELITY_FAILED"
    return {
        "status": status,
        "version": config["version"],
        "gates": gates,
        "metrics": metrics,
        "editability": {
            "passed": editability_gates["S_EDITABILITY"],
            **{
                name: audit.get(name)
                for name in audit_metric_names
            },
        },
        "findings": findings,
        "correction_hints": [
            {
                "gate": finding["gate"],
                "node_ids": finding["node_ids"],
                "action": {
                    "G_ALIGNMENT": "restore measured bounding boxes and constraints",
                    "G_PAGE_GEOMETRY": "restore the source page aspect ratio",
                    "G_BORDER_CONTINUITY": "restore visible native strokes",
                    "V_CONTRAST": "increase foreground-background contrast",
                    "V_EDGE_SIMILARITY": "restore missing or displaced visual edges",
                    "V_PALETTE": "restore the measured source palette",
                    "V_STRUCTURE": "restore the source region hierarchy",
                    "V_TEXT_COVERAGE": "restore missing or undersized native text",
                }.get(finding["gate"], "rebuild and rerender the affected primitives"),
            }
            for finding in findings
        ],
    }
