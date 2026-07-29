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


def _contrast_ratio(image, bbox):
    crop = _crop(image, bbox).convert("L")
    values = list(crop.getdata())
    dark = _percentile(values, 0.10)
    light = _percentile(values, 0.90)
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
        node["id"]: _contrast_ratio(rendered, node["bbox"]) for node in text_nodes
    }
    min_contrast = min(contrast_ratios.values()) if contrast_ratios else 21

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
        "reference_ocr_words": _ocr_word_count(reference_path),
        "rendered_ocr_words": _ocr_word_count(rendered_path),
    }

    gates = {
        "S_EDITABILITY": (
            int(manifest.get("full_page_image_count", 0)) == 0
            and int(manifest.get("native_shape_count", 0)) >= len(expected)
            and set(expected).issubset(actual)
        ),
        "R_NONBLANK": metrics["nonwhite_ratio"] >= thresholds["nonwhite_ratio_min"],
        "R_SINGLE_PAGE": int(manifest.get("page_count", 0)) == 1,
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
    }

    details = {
        "S_EDITABILITY": (0, 1, list(expected)),
        "R_NONBLANK": (
            metrics["nonwhite_ratio"],
            thresholds["nonwhite_ratio_min"],
            [],
        ),
        "R_SINGLE_PAGE": (manifest.get("page_count", 0), 1, []),
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
    }
    findings = []
    for gate in config["critical_gates"]:
        if not gates[gate]:
            observed, threshold, node_ids = details[gate]
            findings.append(
                {
                    "gate": gate,
                    "expected": threshold,
                    "observed": observed,
                    "node_ids": node_ids,
                }
            )

    return {
        "status": "PASS" if all(gates[gate] for gate in config["critical_gates"]) else "FAIL",
        "version": config["version"],
        "gates": gates,
        "metrics": metrics,
        "findings": findings,
        "correction_hints": [
            {
                "gate": finding["gate"],
                "node_ids": finding["node_ids"],
                "action": {
                    "G_ALIGNMENT": "restore measured bounding boxes and constraints",
                    "G_BORDER_CONTINUITY": "restore visible native strokes",
                    "V_CONTRAST": "increase foreground-background contrast",
                    "V_EDGE_SIMILARITY": "restore missing or displaced visual edges",
                    "V_PALETTE": "restore the measured source palette",
                    "V_STRUCTURE": "restore the source region hierarchy",
                }.get(finding["gate"], "rebuild and rerender the affected primitives"),
            }
            for finding in findings
        ],
    }
