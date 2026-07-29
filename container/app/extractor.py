"""Deterministic reference decomposition for editable document rendering."""

from collections import Counter
import csv
import io
import re
import shutil
import subprocess

from PIL import Image


ARABIC = re.compile(r"[\u0600-\u06ff]")


def _hex(color):
    return "#%02x%02x%02x" % tuple(int(value) for value in color[:3])


def _dominant_color(image):
    sample = image.copy()
    sample.thumbnail((160, 160))
    colors = Counter(
        tuple((channel // 16) * 16 + 8 for channel in pixel[:3])
        for pixel in sample.convert("RGB").getdata()
    )
    return colors.most_common(1)[0][0]


def _different(pixel, background, threshold=28):
    return sum(abs(int(left) - int(right)) for left, right in zip(pixel, background)) >= threshold


def _clusters(indices, minimum_gap=3):
    groups = []
    for value in indices:
        if not groups or value - groups[-1][-1] > minimum_gap:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [int(round(sum(group) / len(group))) for group in groups]


def _long_lines(image, background):
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    vertical = [
        x
        for x in range(width)
        if sum(_different(pixels[x, y], background) for y in range(height)) / height >= 0.28
    ]
    horizontal = [
        y
        for y in range(height)
        if sum(_different(pixels[x, y], background) for x in range(width)) / width >= 0.42
    ]
    return _clusters(vertical), _clusters(horizontal)


def _regular_subset(values, minimum=3):
    """Return the longest approximately regular run of measured line centers."""

    if len(values) < minimum:
        return []
    best = []
    for start in range(len(values) - minimum + 1):
        for end in range(start + minimum, len(values) + 1):
            run = values[start:end]
            gaps = [right - left for left, right in zip(run, run[1:])]
            median = sorted(gaps)[len(gaps) // 2]
            if median > 4 and all(abs(gap - median) <= max(5, median * 0.45) for gap in gaps):
                if len(run) > len(best):
                    best = run
    return best


def _ocr_tsv(path):
    if not shutil.which("tesseract"):
        return ""
    result = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", "ara+eng", "tsv"],
        capture_output=True,
        text=True,
        timeout=45,
    )
    return result.stdout if result.returncode == 0 else ""


def _ocr_nodes(path, image):
    width, height = image.size
    rows = csv.DictReader(io.StringIO(_ocr_tsv(path)), delimiter="\t")
    nodes = []
    for row in rows:
        value = (row.get("text") or "").strip()
        try:
            confidence = float(row.get("conf", "-1"))
            left = int(row["left"])
            top = int(row["top"])
            box_width = int(row["width"])
            box_height = int(row["height"])
        except (TypeError, ValueError, KeyError):
            continue
        if not value or confidence < 35 or box_width < 2 or box_height < 2:
            continue
        rtl = bool(ARABIC.search(value))
        crop = image.crop((left, top, left + box_width, top + box_height)).convert("L")
        ordered = sorted(crop.getdata())
        background_luminance = ordered[int((len(ordered) - 1) * 0.65)]
        color = "#111111" if background_luminance >= 145 else "#ffffff"
        nodes.append(
            {
                "id": "text-%03d" % (len(nodes) + 1),
                "type": "text",
                "bbox": [
                    left / width,
                    top / height,
                    box_width / width,
                    box_height / height,
                ],
                "z": 30,
                "editable": True,
                "text": {
                    "value": value,
                    "direction": "rtl" if rtl else "ltr",
                    "font_family": "Noto Sans Arabic" if rtl else "Noto Sans",
                    "font_size_pt": max(6, min(42, box_height * 0.64)),
                    "weight": 600 if box_height >= height * 0.035 else 400,
                    "align": "right" if rtl else "left",
                    "color": color,
                },
            }
        )
    return nodes


def _graphic_nodes(path, image, background, text_nodes):
    """Preserve bounded non-text artwork as editable image objects."""

    try:
        import cv2
        import numpy
    except ImportError:
        return []
    array = numpy.asarray(image.convert("RGB"))
    delta = numpy.max(numpy.abs(array.astype("int16") - numpy.array(background)), axis=2)
    mask = (delta >= 38).astype("uint8") * 255
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    )
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    width, height = image.size
    page_area = width * height
    text_boxes = [node["bbox"] for node in text_nodes]
    nodes = []
    for x, y, box_width, box_height, area in stats[1:count]:
        ratio = area / page_area
        if ratio < 0.00045 or ratio > 0.11 or box_width < 10 or box_height < 10:
            continue
        bbox = [x / width, y / height, box_width / width, box_height / height]
        overlap_text = False
        for tx, ty, tw, th in text_boxes:
            ix = max(0, min(bbox[0] + bbox[2], tx + tw) - max(bbox[0], tx))
            iy = max(0, min(bbox[1] + bbox[3], ty + th) - max(bbox[1], ty))
            if ix * iy >= min(bbox[2] * bbox[3], tw * th) * 0.35:
                overlap_text = True
                break
        if overlap_text:
            continue
        pad_x, pad_y = 3 / width, 3 / height
        crop = [
            max(0, bbox[0] - pad_x),
            max(0, bbox[1] - pad_y),
            min(1 - max(0, bbox[0] - pad_x), bbox[2] + 2 * pad_x),
            min(1 - max(0, bbox[1] - pad_y), bbox[3] + 2 * pad_y),
        ]
        nodes.append(
            {
                "id": "art-%03d" % (len(nodes) + 1),
                "type": "image",
                "bbox": crop,
                "crop": crop,
                "content_ref": "reference",
                "z": 20,
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
    return nodes[:80]


def extract_scene_graph(reference_path, hints=None):
    """Measure one raster reference into a generic editable scene graph."""

    reference_path = str(reference_path)
    with Image.open(reference_path) as source:
        image = source.convert("RGB")
    width, height = image.size
    background = _dominant_color(image)
    text_nodes = _ocr_nodes(reference_path, image)
    vertical, horizontal = _long_lines(image, background)
    vertical = _regular_subset(vertical, 3)
    horizontal = _regular_subset(horizontal, 3)
    nodes = [
        {
            "id": "page-background",
            "type": "rectangle",
            "bbox": [0, 0, 1, 1],
            "z": 0,
            "editable": True,
            "style": {
                "fill": _hex(background),
                "stroke": None,
                "stroke_width": 0,
                "corner_radius": 0,
                "opacity": 1,
            },
        }
    ]
    if len(vertical) >= 3 and len(horizontal) >= 3:
        x0, x1 = vertical[0], vertical[-1]
        y0, y1 = horizontal[0], horizontal[-1]
        line_pixels = []
        pixels = image.load()
        for x in vertical:
            line_pixels.extend(pixels[x, y] for y in range(y0, y1 + 1, max(1, (y1 - y0) // 60)))
        stroke = Counter(tuple(pixel) for pixel in line_pixels).most_common(1)[0][0]
        stroke_color = _hex(stroke)
        nodes.append(
            {
                "id": "measured-grid",
                "type": "grid",
                "bbox": [x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height],
                "z": 10,
                "editable": True,
                "rows": len(horizontal) - 1,
                "columns": len(vertical) - 1,
                "style": {
                    "fill": None,
                    "stroke": None,
                    "stroke_width": 0,
                    "corner_radius": 0,
                    "opacity": 1,
                },
            }
        )
        for index, x in enumerate(vertical):
            nodes.append(
                {
                    "id": "grid-v-%02d" % index,
                    "type": "line",
                    "bbox": [x / width, y0 / height, max(1 / width, 0.0001), (y1 - y0) / height],
                    "z": 11,
                    "editable": True,
                    "style": {
                        "fill": None,
                        "stroke": stroke_color,
                        "stroke_width": 1,
                        "corner_radius": 0,
                        "opacity": 1,
                    },
                }
            )
        for index, y in enumerate(horizontal):
            nodes.append(
                {
                    "id": "grid-h-%02d" % index,
                    "type": "line",
                    "bbox": [x0 / width, y / height, (x1 - x0) / width, max(1 / height, 0.0001)],
                    "z": 11,
                    "editable": True,
                    "style": {
                        "fill": None,
                        "stroke": stroke_color,
                        "stroke_width": 1,
                        "corner_radius": 0,
                        "opacity": 1,
                    },
                }
            )
    nodes.extend(_graphic_nodes(reference_path, image, background, text_nodes))
    nodes.extend(text_nodes)
    return {
        "version": "scene-graph.v1",
        "page": {
            "width": 297 if width >= height else 210,
            "height": 210 if width >= height else 297,
            "orientation": "landscape" if width >= height else "portrait",
        },
        "nodes": nodes,
        "constraints": [],
    }
