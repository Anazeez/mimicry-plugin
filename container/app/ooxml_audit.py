"""Evidence-bearing OOXML audit for native editability.

The scene graph describes intent. This module inspects the saved DOCX and the
objects LibreOffice recovered from it so validation cannot pass from intent
alone.
"""

from io import BytesIO
from pathlib import Path
import csv
import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from xml.etree import ElementTree

from PIL import Image


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REQUIRED_PARTS = {"[Content_Types].xml", "word/document.xml"}
VECTOR_MEDIA_SUFFIXES = {".emf", ".svg", ".wmf"}
ALLOWED_RASTER_JUSTIFICATIONS = {
    "source_artwork",
    "source_illustration",
    "source_logo",
    "source_photo",
    "source_texture",
}


def _normalized_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _area(bbox):
    return max(0.0, float(bbox[2])) * max(0.0, float(bbox[3]))


def _union_area(boxes):
    """Return the exact normalized union area of axis-aligned boxes."""

    if not boxes:
        return 0.0
    x_values = sorted(
        {
            max(0.0, min(1.0, float(value)))
            for box in boxes
            for value in (box[0], box[0] + box[2])
        }
    )
    total = 0.0
    for left, right in zip(x_values, x_values[1:]):
        if right <= left:
            continue
        intervals = []
        midpoint = (left + right) / 2
        for x, y, width, height in boxes:
            if float(x) <= midpoint <= float(x) + float(width):
                intervals.append(
                    (
                        max(0.0, float(y)),
                        min(1.0, float(y) + float(height)),
                    )
                )
        if not intervals:
            continue
        intervals.sort()
        covered = 0.0
        start, end = intervals[0]
        for next_start, next_end in intervals[1:]:
            if next_start > end:
                covered += max(0.0, end - start)
                start, end = next_start, next_end
            else:
                end = max(end, next_end)
        covered += max(0.0, end - start)
        total += (right - left) * covered
    return min(1.0, total)


def _is_image_shape(node):
    shape_type = str(node.get("shape_type", "")).casefold()
    return "frame" in shape_type or "graphic" in shape_type or "picture" in shape_type


def _difference_hash(image):
    resampling = getattr(Image, "Resampling", Image)
    grayscale = image.convert("L").resize((9, 8), resampling.LANCZOS)
    pixels = list(grayscale.getdata())
    value = 0
    for row in range(8):
        for column in range(8):
            value <<= 1
            if pixels[row * 9 + column] > pixels[row * 9 + column + 1]:
                value |= 1
    return value


def _hash_distance(left, right):
    return bin(int(left ^ right)).count("1")


def _ocr_image_text(image):
    """Return confident visible text in one retained raster, or None if unavailable."""

    if not shutil.which("tesseract"):
        return None
    with tempfile.TemporaryDirectory(prefix="reconstructor-media-ocr-") as directory:
        path = Path(directory) / "media.png"
        image.convert("RGB").save(path)
        result = subprocess.run(
            [
                "tesseract",
                str(path),
                "stdout",
                "-l",
                "ara+eng",
                "--psm",
                "6",
                "tsv",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    if result.returncode != 0:
        return None
    words = []
    for row in csv.DictReader(io.StringIO(result.stdout), delimiter="\t"):
        value = (row.get("text") or "").strip()
        try:
            confidence = float(row.get("conf", "-1"))
        except (TypeError, ValueError):
            continue
        if (
            confidence >= 60
            and value
            and any(character.isalnum() for character in value)
        ):
            words.append(value)
    normalized_words = [
        _normalized_text(word)
        for word in words
        if _normalized_text(word)
    ]
    substantial = [
        word
        for word in normalized_words
        if sum(character.isalnum() for character in word) >= 3
    ]
    if not substantial:
        total_characters = sum(
            character.isalnum()
            for word in normalized_words
            for character in word
        )
        if len(normalized_words) < 2 or total_characters < 4:
            return ""
        substantial = normalized_words
    return _normalized_text(" ".join(substantial))


def _native_text_values(archive, names):
    values = []
    parts = [
        name
        for name in names
        if name == "word/document.xml"
        or re.fullmatch(r"word/(header|footer)\d+\.xml", name)
    ]
    for name in parts:
        root = ElementTree.fromstring(archive.read(name))
        values.extend(
            node.text or ""
            for node in root.iter("{%s}t" % WORD_NS)
            if (node.text or "").strip()
        )
    return values


def _looks_like_raster_tiling(image_nodes):
    if len(image_nodes) < 4:
        return False
    boxes = [node["bbox"] for node in image_nodes]
    union = _union_area(boxes)
    if union < 0.50:
        return False
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    envelope = max(0.0, right - left) * max(0.0, bottom - top)
    summed = sum(_area(box) for box in boxes)
    return envelope >= 0.55 and union / envelope >= 0.90 and summed / union <= 1.15


def audit_docx_package(docx_path, scene, actual_nodes, reference_path):
    """Inspect saved package content and return measured editability evidence."""

    result = {
        "audit_complete": False,
        "package_integrity": False,
        "audit_error": None,
        "embedded_image_objects": 0,
        "package_media_files": 0,
        "native_shape_objects": 0,
        "native_text_regions": 0,
        "source_text_regions": 0,
        "visible_text_native_ratio": 0.0,
        "scene_node_coverage": 0.0,
        "native_visible_area_ratio": 0.0,
        "largest_unjustified_raster_ratio": 0.0,
        "total_unjustified_raster_ratio": 0.0,
        "source_reference_embedded": False,
        "raster_tiling_detected": False,
        "monolithic_flattened_object": False,
        "unjustified_raster_objects": 0,
        "image_justifications": [],
        "raster_text_audit_complete": False,
        "raster_text_audit_error": None,
        "raster_text_regions": 0,
        "duplicate_text_layers": 0,
        "text_region_exclusivity_ratio": 0.0,
        "raster_text_evidence": [],
    }
    try:
        docx_path = Path(docx_path)
        actual = {node["id"]: node for node in actual_nodes}
        expected = {
            node["id"]: node
            for node in scene.get("nodes", [])
            if node.get("type") != "group"
        }
        actual_images = [node for node in actual_nodes if _is_image_shape(node)]
        actual_native = [node for node in actual_nodes if not _is_image_shape(node)]
        result["embedded_image_objects"] = len(actual_images)
        result["native_shape_objects"] = len(actual_native)

        with zipfile.ZipFile(docx_path) as archive:
            names = set(archive.namelist())
            if archive.testzip() is not None or not REQUIRED_PARTS.issubset(names):
                result["audit_error"] = "DOCX package integrity check failed"
                return result
            result["package_integrity"] = True
            native_text = _normalized_text(" ".join(_native_text_values(archive, names)))
            media_names = sorted(
                name for name in names if name.startswith("word/media/") and not name.endswith("/")
            )
            result["package_media_files"] = len(media_names)

            with Image.open(reference_path) as source:
                source = source.convert("RGB")
                source_hash = _difference_hash(source)
                source_size = source.size
            near_source_media = False
            media_images = {}
            for name in media_names:
                try:
                    with Image.open(BytesIO(archive.read(name))) as media:
                        decoded = media.convert("RGB")
                        media_images[name] = decoded.copy()
                        if _hash_distance(source_hash, _difference_hash(decoded)) <= 4:
                            near_source_media = True
                except (OSError, ValueError):
                    continue

            vector_media = [
                name for name in media_names if Path(name).suffix.casefold() in VECTOR_MEDIA_SUFFIXES
            ]

        text_nodes = [node for node in expected.values() if node.get("type") == "text"]
        native_text_nodes = []
        for node in text_nodes:
            value = _normalized_text(node.get("text", {}).get("value"))
            recovered = actual.get(node["id"])
            if (
                value
                and recovered
                and not _is_image_shape(recovered)
                and value in native_text
            ):
                native_text_nodes.append(node)
        result["source_text_regions"] = len(text_nodes)
        result["native_text_regions"] = len(native_text_nodes)
        result["visible_text_native_ratio"] = (
            len(native_text_nodes) / len(text_nodes) if text_nodes else 1.0
        )

        # A retained generic artwork region may not contain source text. Match
        # each scene image to its packaged media by measured size and visual
        # hash, then OCR the media itself. Logos and genuine photographs are
        # explicitly exempt because their internal lettering is legitimate
        # raster content.
        generic_image_nodes = [
            node
            for node in expected.values()
            if node.get("type") == "image"
            and node.get("raster_justification")
            in {"source_artwork", "source_illustration", "source_texture"}
            and node["id"] in actual
            and _is_image_shape(actual[node["id"]])
        ]
        unmatched_media = dict(media_images)
        raster_audit_complete = True
        for node in generic_image_nodes:
            x, y, box_width, box_height = node["bbox"]
            source_crop = source.crop(
                (
                    max(0, int(round(x * source_size[0]))),
                    max(0, int(round(y * source_size[1]))),
                    min(source_size[0], int(round((x + box_width) * source_size[0]))),
                    min(source_size[1], int(round((y + box_height) * source_size[1]))),
                )
            )
            if not unmatched_media or not source_crop.width or not source_crop.height:
                raster_audit_complete = False
                break
            crop_hash = _difference_hash(source_crop)
            media_name, media = min(
                unmatched_media.items(),
                key=lambda item: (
                    abs(item[1].width - source_crop.width)
                    + abs(item[1].height - source_crop.height),
                    _hash_distance(crop_hash, _difference_hash(item[1])),
                ),
            )
            unmatched_media.pop(media_name)
            raster_text = _ocr_image_text(media)
            if raster_text is None:
                raster_audit_complete = False
                break
            if not raster_text:
                continue
            result["raster_text_regions"] += 1
            native_tokens = set(native_text.split())
            raster_tokens = set(raster_text.split())
            duplicate = bool(native_tokens.intersection(raster_tokens))
            if duplicate:
                result["duplicate_text_layers"] += 1
            result["raster_text_evidence"].append(
                {
                    "id": node["id"],
                    "media": media_name,
                    "text": raster_text,
                    "duplicates_native_text": duplicate,
                }
            )
        result["raster_text_audit_complete"] = raster_audit_complete
        result["raster_text_audit_error"] = (
            None
            if raster_audit_complete
            else "retained raster text evidence was unavailable"
        )
        result["text_region_exclusivity_ratio"] = (
            1.0 if result["raster_text_regions"] == 0 else 0.0
        )

        reconstructable = [
            node for node in expected.values() if node.get("type") != "image"
        ]
        mapped_native = [
            node
            for node in reconstructable
            if node["id"] in actual and not _is_image_shape(actual[node["id"]])
        ]
        result["scene_node_coverage"] = (
            len(mapped_native) / len(reconstructable) if reconstructable else 1.0
        )
        reconstructable_area = sum(_area(node["bbox"]) for node in reconstructable)
        native_area = sum(_area(node["bbox"]) for node in mapped_native)
        result["native_visible_area_ratio"] = (
            min(1.0, native_area / reconstructable_area)
            if reconstructable_area
            else 1.0
        )

        largest_image = max((_area(node["bbox"]) for node in actual_images), default=0.0)
        result["source_reference_embedded"] = near_source_media and largest_image >= 0.50
        result["raster_tiling_detected"] = _looks_like_raster_tiling(actual_images)
        result["monolithic_flattened_object"] = bool(vector_media) and (
            largest_image >= 0.50 or result["native_visible_area_ratio"] < 0.50
        )

        unjustified = []
        for node in actual_images:
            source_node = expected.get(node["id"])
            justification = (
                source_node.get("raster_justification")
                if source_node and source_node.get("type") == "image"
                else None
            )
            if (
                not justification
                and source_node
                and source_node.get("type") == "image"
                and str(source_node.get("content_ref", "")).startswith("reference-region:")
            ):
                justification = "source_artwork"
            allowed = justification in ALLOWED_RASTER_JUSTIFICATIONS
            result["image_justifications"].append(
                {
                    "id": node["id"],
                    "classification": justification or "unsupported_fallback",
                    "area_ratio": _area(node["bbox"]),
                    "allowed": allowed,
                }
            )
            if not allowed:
                unjustified.append(node)

        if (
            result["source_reference_embedded"]
            or result["raster_tiling_detected"]
            or result["monolithic_flattened_object"]
        ):
            unjustified = list(actual_images)
        result["unjustified_raster_objects"] = len(unjustified)
        result["largest_unjustified_raster_ratio"] = max(
            (_area(node["bbox"]) for node in unjustified), default=0.0
        )
        result["total_unjustified_raster_ratio"] = _union_area(
            [node["bbox"] for node in unjustified]
        )
        result["audit_complete"] = raster_audit_complete
        return result
    except (ElementTree.ParseError, KeyError, OSError, ValueError, zipfile.BadZipFile) as error:
        result["audit_error"] = "%s: %s" % (type(error).__name__, error)
        return result
