"""Deterministic reference decomposition for editable document rendering."""

from collections import Counter
import csv
import difflib
from functools import lru_cache
import io
import itertools
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata

from PIL import Image, ImageOps


ARABIC = re.compile(r"[\u0600-\u06ff]")
POINTS_PER_MM = 72 / 25.4


def _hex(color):
    return "#%02x%02x%02x" % tuple(int(value) for value in color[:3])


def _dominant_color(image):
    sample = image.copy()
    sample.thumbnail((160, 160))
    sample = sample.convert("RGB")
    width, height = sample.size
    band = max(2, int(round(min(width, height) * 0.10)))
    border_pixels = []
    border_pixels.extend(sample.crop((0, 0, width, band)).getdata())
    border_pixels.extend(sample.crop((0, height - band, width, height)).getdata())
    border_pixels.extend(sample.crop((0, band, band, height - band)).getdata())
    border_pixels.extend(sample.crop((width - band, band, width, height - band)).getdata())
    colors = Counter(
        tuple((channel // 16) * 16 + 8 for channel in pixel[:3])
        for pixel in border_pixels
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
    try:
        import numpy

        array = numpy.asarray(rgb).astype("int16")
        delta = numpy.sum(
            numpy.abs(array - numpy.asarray(background, dtype="int16")), axis=2
        )
        mask = delta >= 28
        vertical = numpy.flatnonzero(mask.mean(axis=0) >= 0.40).tolist()
        horizontal = numpy.flatnonzero(mask.mean(axis=1) >= 0.65).tolist()
        return _clusters(vertical), _clusters(horizontal)
    except ImportError:
        pass
    pixels = rgb.load()
    vertical = [
        x
        for x in range(width)
        if sum(_different(pixels[x, y], background) for y in range(height)) / height >= 0.40
    ]
    horizontal = [
        y
        for y in range(height)
        if sum(_different(pixels[x, y], background) for x in range(width)) / width >= 0.65
    ]
    return _clusters(vertical), _clusters(horizontal)


def _intersection_lines(image, background, vertical, horizontal):
    """Reject text/photo edges by requiring repeated orthogonal intersections."""

    pixels = image.convert("RGB").load()
    width, height = image.size

    def intersects(x, y):
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                if _different(
                    pixels[min(width - 1, max(0, x + dx)), min(height - 1, max(0, y + dy))],
                    background,
                ):
                    return True
        return False

    vertical_filtered = [
        x
        for x in vertical
        if sum(intersects(x, y) for y in horizontal) >= max(3, int(len(horizontal) * 0.55))
    ]
    horizontal_filtered = [
        y
        for y in horizontal
        if sum(intersects(x, y) for x in vertical_filtered)
        >= max(3, int(len(vertical_filtered) * 0.55))
    ]
    return vertical_filtered, horizontal_filtered


def _continuous_horizontal_lines(image, background, vertical, horizontal):
    """Keep true rules that remain continuous across the detected grid span."""

    if len(vertical) < 2:
        return horizontal
    pixels = image.convert("RGB").load()
    left, right = vertical[0], vertical[-1]
    span = max(1, right - left + 1)
    return [
        y
        for y in horizontal
        if sum(_different(pixels[x, y], background) for x in range(left, right + 1))
        / span
        >= 0.85
    ]


def _regular_subset(values, minimum=3):
    """Return the longest approximately regular run of measured line centers."""

    if len(values) < minimum:
        return []
    for length in range(len(values), minimum - 1, -1):
        best = []
        for run in itertools.combinations(values, length):
            gaps = [right - left for left, right in zip(run, run[1:])]
            median = sorted(gaps)[len(gaps) // 2]
            if median > 4 and all(abs(gap - median) <= max(5, median * 0.45) for gap in gaps):
                if not best or run[-1] - run[0] > best[-1] - best[0]:
                    best = list(run)
        if best:
            return best
    return []


def _ocr_tsv(path, psm=11):
    if not shutil.which("tesseract"):
        return ""
    result = subprocess.run(
        [
            "tesseract",
            str(path),
            "stdout",
            "-l",
            "ara+eng",
            "--psm",
            str(psm),
            "tsv",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    return result.stdout if result.returncode == 0 else ""


def _looks_like_artwork(image):
    """Separate colorful icons and portraits from monochrome text glyphs."""

    pixels = list(image.convert("RGB").getdata())
    if not pixels:
        return False
    colorful = [
        pixel
        for pixel in pixels
        if max(pixel) - min(pixel) >= 28 and min(pixel) < 245
    ]
    quantized = {
        tuple(channel // 24 for channel in pixel)
        for pixel in colorful
    }
    return len(colorful) / len(pixels) >= 0.08 and len(quantized) >= 3


def _cell_for_point(x, y, vertical, horizontal):
    for column, (left, right) in enumerate(zip(vertical, vertical[1:])):
        if left <= x <= right:
            for row, (top, bottom) in enumerate(zip(horizontal, horizontal[1:])):
                if top <= y <= bottom:
                    return column, row
    return None


def _page_geometry(width, height):
    if width >= height:
        page_width = 297.0
        page_height = page_width * height / width
        return page_width, page_height, "landscape"
    page_height = 297.0
    page_width = page_height * width / height
    return page_width, page_height, "portrait"


def _measured_font_size(
    measured_height, image_height, page_height_mm, rtl=False
):
    visual_height_points = (
        float(measured_height) / float(image_height)
        * float(page_height_mm)
        * POINTS_PER_MM
    )
    # OCR measures visible glyph ink rather than a font's em box. Expand that
    # measured ink to the corresponding Word point size; Arabic glyphs need
    # slightly more em height than Latin glyphs in portable Office fonts.
    expansion = 1.7 if rtl else 1.45
    return max(6, min(72, visual_height_points * expansion))


def _line_width_units(value):
    units = 0.0
    for character in value:
        category = unicodedata.category(character)
        if category.startswith("M"):
            continue
        if character.isspace():
            units += 0.32
        elif "\u0600" <= character <= "\u06ff":
            # Arabic joins into compact contextual forms; portable Office sans
            # fonts average roughly 0.4 em per code point for ordinary words.
            units += 0.42
        elif (
            "\u2e80" <= character <= "\u9fff"
            or "\uac00" <= character <= "\ud7af"
        ):
            units += 1.0
        elif character.isdigit():
            units += 0.56
        elif character.isupper():
            units += 0.67
        elif character.islower():
            units += 0.52
        elif category.startswith("P"):
            units += 0.34
        else:
            units += 0.7
    return units


def _text_width_units(value):
    """Estimate the longest line's portable font-width units.

    This is intentionally font-file independent: the generated DOCX may be
    opened by Word, LibreOffice, or Google Docs with different installed font
    files. Conservative script-aware units prevent those engines from wrapping
    a line and moving an absolutely positioned shape during round-trip layout.
    """

    return max(
        (max(0.5, _line_width_units(line)) for line in value.splitlines()),
        default=0.5,
    )


@lru_cache(maxsize=512)
def _correct_display_text(value):
    """Conservatively repair isolated OCR headings using common vocabulary."""

    try:
        from wordfreq import top_n_list, zipf_frequency
    except ImportError:
        return value

    vocabulary = top_n_list("en", 50000)

    def edit_distance(left, right):
        previous = list(range(len(right) + 1))
        for left_index, left_character in enumerate(left, 1):
            current = [left_index]
            for right_index, right_character in enumerate(right, 1):
                current.append(
                    min(
                        current[-1] + 1,
                        previous[right_index] + 1,
                        previous[right_index - 1]
                        + (left_character != right_character),
                    )
                )
            previous = current
        return previous[-1]

    corrected = []
    for token in value.split():
        prefix = re.match(r"^[^A-Za-z]*", token).group(0)
        suffix = re.search(r"[^A-Za-z]*$", token).group(0)
        end = len(token) - len(suffix) if suffix else len(token)
        core = token[len(prefix) : end]
        lowered = core.lower()
        if (
            len(lowered) < 4
            or not lowered.isalpha()
            or zipf_frequency(lowered, "en") >= 3.0
        ):
            corrected.append(token)
            continue
        maximum_distance = max(1, int(round(len(lowered) * 0.45)))
        candidates = []
        for candidate in vocabulary:
            if (
                not candidate.isalpha()
                or abs(len(candidate) - len(lowered)) > maximum_distance
            ):
                continue
            distance = edit_distance(lowered, candidate)
            if distance > maximum_distance:
                continue
            similarity = difflib.SequenceMatcher(
                None, lowered, candidate
            ).ratio()
            if similarity < 0.60:
                continue
            candidates.append(
                (
                    distance,
                    -zipf_frequency(candidate, "en"),
                    -similarity,
                    candidate,
                )
            )
        if not candidates:
            corrected.append(token)
            continue
        replacement = min(candidates)[-1]
        if core[:1].isupper():
            replacement = replacement.capitalize()
        corrected.append(prefix + replacement + suffix)
    return " ".join(corrected)


def _ocr_nodes(
    path,
    image,
    vertical=None,
    horizontal=None,
    page_width_mm=297,
    page_height_mm=210,
):
    width, height = image.size
    lines = {}
    for source_index, psm in enumerate((11, 3, 6)):
        rows = csv.DictReader(io.StringIO(_ocr_tsv(path, psm)), delimiter="\t")
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
            value = value.replace("\u200f", "").replace("\u200e", "").strip()
            if (
                not value
                or confidence < 60
                or box_width < 2
                or box_height < 2
                or not any(character.isalnum() for character in value)
            ):
                continue
            crop = image.crop((left, top, left + box_width, top + box_height))
            if len(value) == 1 and _looks_like_artwork(crop):
                continue
            cell = (
                _cell_for_point(
                    left + box_width / 2,
                    top + box_height / 2,
                    vertical,
                    horizontal,
                )
                if vertical and horizontal
                else None
            )
            # Sparse mode keeps separated headings and names. Automatic mode
            # supplements only measured grid cells where segmentation context
            # improves multiline labels.
            if psm == 3 and cell is None:
                continue
            key = (
                ("cell",) + cell
                if cell is not None
                else (
                    "line",
                    row.get("block_num", ""),
                    row.get("par_num", ""),
                    row.get("line_num", ""),
                )
            )
            lines.setdefault((source_index,) + key, []).append(
                (left, top, box_width, box_height, confidence, value)
            )
    segmented_lines = {}
    for source_key, words in lines.items():
        if source_key[0] != 2 or source_key[1] != "line" or len(words) < 2:
            segmented_lines[source_key] = words
            continue
        ordered = sorted(words, key=lambda word: word[0])
        median_height = sorted(word[3] for word in ordered)[len(ordered) // 2]
        clusters = [[ordered[0]]]
        for word in ordered[1:]:
            previous = clusters[-1][-1]
            gap = word[0] - (previous[0] + previous[2])
            if gap > max(20, median_height * 1.6):
                clusters.append([word])
            else:
                clusters[-1].append(word)
        for segment_index, cluster in enumerate(clusters):
            cluster_ids = {id(word) for word in cluster}
            segmented_lines[source_key + ("segment", segment_index)] = [
                word for word in words if id(word) in cluster_ids
            ]
    lines = segmented_lines
    observations = []
    for source_key, words in lines.items():
        observation_left = min(word[0] for word in words)
        observation_top = min(word[1] for word in words)
        observation_right = max(word[0] + word[2] for word in words)
        observation_bottom = max(word[1] + word[3] for word in words)
        observation_value = " ".join(
            word[5] for word in sorted(words, key=lambda item: item[0])
        )
        observations.append(
            (
                source_key[0],
                [
                    observation_left,
                    observation_top,
                    observation_right - observation_left,
                    observation_bottom - observation_top,
                ],
                observation_value,
            )
        )
    selected = {}
    for source_key, words in lines.items():
        key = source_key[1:]
        score = sum(word[4] for word in words) / len(words)
        score += min(20, sum(len(word[5]) for word in words) * 1.2)
        if key not in selected or score > selected[key][0]:
            selected[key] = (score, words, source_key[0])
    nodes = []
    for key, (_, words, source_index) in selected.items():
        left = min(word[0] for word in words)
        top = min(word[1] for word in words)
        right = max(word[0] + word[2] for word in words)
        bottom = max(word[1] + word[3] for word in words)
        measured_width, measured_height = right - left, bottom - top
        rows = []
        for word in sorted(words, key=lambda item: item[1]):
            if not rows or word[1] - rows[-1][-1][1] > max(4, word[3] * 0.65):
                rows.append([word])
            else:
                rows[-1].append(word)
        if (
            len(rows) > 1
            and len(words) <= 4
            and measured_width / max(1, measured_height) >= 2.2
        ):
            rows = [words]
        value = "\n".join(" ".join(word[5] for word in row) for row in rows)
        if key[0] != "cell":
            normalized_value = re.sub(
                r"[^a-z0-9\u0600-\u06ff]+", "",
                value.lower(),
            )
            consensus_sources = set()
            measured_bbox = [
                left,
                top,
                measured_width,
                measured_height,
            ]
            for (
                observation_source,
                observation_bbox,
                observation_value,
            ) in observations:
                normalized_observation = re.sub(
                    r"[^a-z0-9\u0600-\u06ff]+",
                    "",
                    observation_value.lower(),
                )
                if (
                    normalized_observation
                    and normalized_value
                    and _bbox_overlap_ratio(
                        measured_bbox, observation_bbox
                    )
                    >= 0.45
                    and difflib.SequenceMatcher(
                        None,
                        normalized_value,
                        normalized_observation,
                    ).ratio()
                    >= 0.60
                ):
                    consensus_sources.add(observation_source)
            dense_recovery = (
                source_index == 2
                and len(words) >= 3
                and sum(
                    character.isalpha()
                    for word in words
                    for character in word[5]
                )
                >= 6
            )
            if len(consensus_sources) < 2 and not dense_recovery:
                continue
        rtl = bool(ARABIC.search(value))
        crop = image.crop(
            (left, top, left + measured_width, top + measured_height)
        ).convert("L")
        ordered = sorted(crop.getdata())
        background_luminance = ordered[int((len(ordered) - 1) * 0.65)]
        color = "#111111" if background_luminance >= 145 else "#ffffff"
        if key[0] == "cell":
            column, row = key[1], key[2]
            cell_left, cell_right = vertical[column], vertical[column + 1]
            cell_top, cell_bottom = horizontal[row], horizontal[row + 1]
            inset_x = max(3, (cell_right - cell_left) * 0.04)
            inset_y = max(3, (cell_bottom - cell_top) * 0.08)
            left = cell_left + inset_x
            top = cell_top + inset_y
            box_width = cell_right - cell_left - 2 * inset_x
            box_height = cell_bottom - cell_top - 2 * inset_y
            align = "center"
        else:
            pad_x = max(2, measured_width * 0.06)
            pad_y = max(2, measured_height * 0.12)
            left = max(0, left - pad_x)
            top = max(0, top - pad_y)
            box_width = min(width - left, measured_width + 2 * pad_x)
            box_height = min(height - top, measured_height + 2 * pad_y)
            align = "right" if rtl else "left"
        measured_font_size = _measured_font_size(
            measured_height,
            height,
            page_height_mm,
            rtl,
        )
        # A font larger than its measured Word text box is reflowed during the
        # DOCX round trip.  Writer may then move a page-anchored shape by one or
        # more line heights.  Cap the portable font to the physical box while
        # preserving the reference-measured box and visual center.
        box_height_points = (
            box_height / height * page_height_mm * POINTS_PER_MM
        )
        box_width_points = box_width / width * page_width_mm * POINTS_PER_MM
        line_count = max(1, len(value.splitlines()))
        height_cap = box_height_points * 0.92 / line_count
        width_safety = 2.2 if source_index == 2 else 1.0
        width_cap = (
            box_width_points
            * 0.86
            / (_text_width_units(value) * width_safety)
        )
        fitted_font_size = min(
            measured_font_size,
            max(6, height_cap),
            max(6, width_cap),
        )
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
                    # Arial is available on Microsoft Word/iPad and degrades
                    # predictably to metrically compatible sans fonts in
                    # LibreOffice and Google Docs.
                    "font_family": "Arial",
                    "font_size_pt": fitted_font_size,
                    "weight": 600 if measured_height >= height * 0.035 else 400,
                    "align": align,
                    "color": color,
                },
            }
        )
    # Dense-layout OCR (PSM 6) recovers banner and instruction lines that
    # sparse segmentation can miss. Collapse spatial duplicates so the same
    # source text can never become two native text layers.
    deduplicated = []
    for node in nodes:
        x, y, box_width, box_height = node["bbox"]
        replacement = None
        for index, existing in enumerate(deduplicated):
            ex, ey, ew, eh = existing["bbox"]
            overlap_x = max(0, min(x + box_width, ex + ew) - max(x, ex))
            overlap_y = max(0, min(y + box_height, ey + eh) - max(y, ey))
            overlap = overlap_x * overlap_y
            smaller = min(box_width * box_height, ew * eh)
            if smaller and overlap / smaller >= 0.65:
                replacement = index
                break
        if replacement is None:
            deduplicated.append(node)
        elif len(node["text"]["value"]) > len(
            deduplicated[replacement]["text"]["value"]
        ):
            deduplicated[replacement] = node
    for index, node in enumerate(deduplicated, 1):
        node["id"] = "text-%03d" % index
    return deduplicated


def _expand_boundary_artwork(x, box_width, box_height, vertical, image_width):
    for grid_x in vertical or []:
        if abs(x - grid_x) <= 6 and box_width < box_height * 0.8:
            target_width = min(
                image_width, max(box_width, int(round(box_height * 1.05)))
            )
            return (
                max(0, int(round(grid_x - target_width / 2))),
                target_width,
                True,
            )
    return x, box_width, False


def _flat_color_nodes(image, background, text_nodes):
    """Recover repeated low-contrast panels and slots as native shapes."""

    try:
        import cv2
        import numpy
    except ImportError:
        return []
    array = numpy.asarray(image.convert("RGB"))
    height, width = array.shape[:2]
    page_area = width * height
    quantized = (
        (array.astype("uint16") // 8) * 8 + 4
    ).clip(0, 255).astype("uint8")
    colors, counts = numpy.unique(
        quantized.reshape(-1, 3), axis=0, return_counts=True
    )
    text_boxes = [node["bbox"] for node in text_nodes]

    def overlaps_text(bbox):
        return any(
            _bbox_overlap_ratio(bbox, text_box) >= 0.45
            for text_box in text_boxes
        )

    groups = []
    for color, count in zip(colors, counts):
        if count / page_area < 0.001:
            continue
        if int(
            numpy.max(
                numpy.abs(
                    color.astype("int16")
                    - numpy.asarray(background, dtype="int16")
                )
            )
        ) < 10:
            continue
        mask = (
            numpy.max(
                numpy.abs(array.astype("int16") - color.astype("int16")),
                axis=2,
            )
            <= 12
        ).astype("uint8") * 255
        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        )
        count_components, _, stats, _ = cv2.connectedComponentsWithStats(
            mask, 8
        )
        candidates = []
        for x, y, box_width, box_height, area in stats[1:count_components]:
            box_area = box_width * box_height
            if (
                box_width < 18
                or box_height < 10
                or box_area / page_area > 0.12
                or area / page_area < 0.00045
                or area / max(1, box_area) < 0.62
            ):
                continue
            bbox = [
                x / width,
                y / height,
                box_width / width,
                box_height / height,
            ]
            component_mask = mask[
                y : y + box_height, x : x + box_width
            ]
            corner_width = max(2, int(round(box_width * 0.12)))
            corner_height = max(2, int(round(box_height * 0.20)))
            corner_samples = numpy.concatenate(
                (
                    component_mask[:corner_height, :corner_width].reshape(-1),
                    component_mask[:corner_height, -corner_width:].reshape(-1),
                    component_mask[-corner_height:, :corner_width].reshape(-1),
                    component_mask[-corner_height:, -corner_width:].reshape(-1),
                )
            )
            candidates.append(
                (
                    bbox,
                    float((corner_samples > 0).mean()),
                    overlaps_text(bbox),
                )
            )
        if len(candidates) >= 2 or any(item[2] for item in candidates):
            groups.append((color, candidates))

    entries = [
        (color, bbox, corner_density, overlap)
        for color, candidates in groups
        for bbox, corner_density, overlap in candidates
    ]

    def similar_family_size(left, right):
        _, left_bbox, _, _ = left
        _, right_bbox, _, _ = right
        left_color, right_color = left[0], right[0]
        if int(
            numpy.max(
                numpy.abs(
                    left_color.astype("int16")
                    - right_color.astype("int16")
                )
            )
        ) > 16:
            return False
        for left_value, right_value in (
            (left_bbox[2], right_bbox[2]),
            (left_bbox[3], right_bbox[3]),
        ):
            if max(left_value, right_value) / max(
                min(left_value, right_value), 1e-9
            ) > 1.20:
                return False
        return True

    family_supports = {
        id(entry): sum(
            similar_family_size(entry, other) for other in entries
        )
        for entry in entries
    }
    strongest_non_dark_family = max(
        (
            family_supports[id(entry)]
            for entry in entries
            if float(numpy.mean(entry[0])) > 90
        ),
        default=0,
    )
    repeated_family_floor = max(
        3,
        int(numpy.ceil(strongest_non_dark_family * 0.30)),
    )
    retained = []
    for entry in entries:
        color, bbox, _, _ = entry
        family_support = family_supports[id(entry)]
        pixel_aspect = (bbox[2] * width) / max(bbox[3] * height, 1)
        dark_display_panel = (
            float(numpy.mean(color)) <= 90
            and pixel_aspect >= 2
            and bbox[2] * bbox[3] >= 0.004
        )
        repeated_semantic_shape = (
            bbox[2] * bbox[3] >= 0.0015
            and bbox[3] > 0.025
            and family_support >= repeated_family_floor
        )
        if repeated_semantic_shape or dark_display_panel:
            retained.append(entry)

    nodes = []
    for color, bbox, corner_density, _ in retained:
        rounded = (
            bbox[2] >= bbox[3] * 1.5
            and corner_density < 0.92
        )
        nodes.append(
            {
                "id": "flat-%03d" % (len(nodes) + 1),
                "type": "rounded_rectangle" if rounded else "rectangle",
                "bbox": bbox,
                "z": 10,
                "editable": True,
                "style": {
                    "fill": _hex(tuple(int(value) for value in color)),
                    "stroke": None,
                    "stroke_width": 0,
                    "corner_radius": 0.45 if rounded else 0,
                    "opacity": 1,
                },
            }
        )
    return nodes


def _panel_ocr_nodes(
    image,
    panel_nodes,
    page_width_mm,
    page_height_mm,
):
    """Recover display text from isolated dark panels at panel resolution."""

    width, height = image.size
    nodes = []
    for panel in panel_nodes:
        if panel["type"] not in {"rectangle", "rounded_rectangle"}:
            continue
        fill = panel.get("style", {}).get("fill")
        if not fill:
            continue
        channels = tuple(
            int(fill.lstrip("#")[index : index + 2], 16)
            for index in (0, 2, 4)
        )
        x, y, box_width, box_height = panel["bbox"]
        pixel_aspect = (box_width * width) / max(
            box_height * height, 1
        )
        if (
            sum(channels) / 3 > 90
            or pixel_aspect < 2
        ):
            continue
        crop = image.crop(
            (
                max(0, int(round(x * width))),
                max(0, int(round(y * height))),
                min(width, int(round((x + box_width) * width))),
                min(height, int(round((y + box_height) * height))),
            )
        )
        if crop.width < 10 or crop.height < 10:
            continue
        wide_title_panel = (
            pixel_aspect >= 3
            and box_width * box_height >= 0.02
        )
        minimum_confidence = 10 if wide_title_panel else 20
        processed = ImageOps.autocontrast(crop.convert("L")).resize(
            (crop.width * 3, crop.height * 3)
        )
        candidates = []
        with tempfile.TemporaryDirectory(
            prefix="reconstructor-panel-ocr-"
        ) as directory:
            path = Path(directory) / "panel.png"
            processed.save(path)
            for psm in (13, 7):
                words = []
                for row in csv.DictReader(
                    io.StringIO(_ocr_tsv(path, psm)),
                    delimiter="\t",
                ):
                    value = (row.get("text") or "").strip()
                    try:
                        confidence = float(row.get("conf", "-1"))
                        left = int(row.get("left", "0"))
                    except (TypeError, ValueError):
                        continue
                    value = re.sub(
                        r"^[^\w\u0600-\u06ff]+|[^\w\u0600-\u06ff]+$",
                        "",
                        value,
                    )
                    if (
                        confidence >= minimum_confidence
                        and value
                        and any(character.isalpha() for character in value)
                    ):
                        words.append((left, confidence, value))
                if words:
                    value = " ".join(
                        word[2] for word in sorted(words, key=lambda item: item[0])
                    )
                    average_confidence = (
                        sum(word[1] for word in words) / len(words)
                    )
                    candidates.append(
                        (
                            average_confidence,
                            len(value),
                            value,
                        )
                    )
                    if (
                        average_confidence >= 80
                        and not wide_title_panel
                    ):
                        break
        if not candidates:
            continue
        _, _, value = max(
            candidates,
            key=lambda item: item[0] + min(30, item[1] * 1.5),
        )
        value = _correct_display_text(value)
        inset_x = box_width * 0.04
        inset_y = box_height * 0.10
        text_width = box_width - 2 * inset_x
        text_height = box_height - 2 * inset_y
        box_height_points = (
            text_height * page_height_mm * POINTS_PER_MM
        )
        box_width_points = text_width * page_width_mm * POINTS_PER_MM
        measured_font_size = box_height_points * 0.70
        fitted_font_size = min(
            measured_font_size,
            box_width_points * 0.86 / _text_width_units(value),
        )
        nodes.append(
            {
                "id": "panel-text-%03d" % (len(nodes) + 1),
                "type": "text",
                "bbox": [
                    x + inset_x,
                    y + inset_y,
                    text_width,
                    text_height,
                ],
                "z": 30,
                "editable": True,
                "text": {
                    "value": value,
                    "direction": "ltr",
                    "font_family": "URW Chancery L",
                    "font_size_pt": max(6, min(72, fitted_font_size)),
                    "weight": 400,
                    "align": "center",
                    "color": "#ffffff",
                },
            }
        )
    return nodes


def _merge_panel_text(page_text, panel_text):
    merged = list(page_text)
    for recovered in panel_text:
        overlaps = [
            existing
            for existing in merged
            if _bbox_overlap_ratio(
                existing["bbox"], recovered["bbox"]
            )
            >= 0.25
        ]
        recovered_value = _correct_display_text(
            recovered["text"]["value"]
        )
        fragments = []
        for existing in overlaps:
            existing_value = _correct_display_text(
                existing["text"]["value"]
            )
            normalized_existing = re.sub(
                r"[^a-z0-9\u0600-\u06ff]+",
                "",
                existing_value.lower(),
            )
            normalized_recovered = re.sub(
                r"[^a-z0-9\u0600-\u06ff]+",
                "",
                recovered_value.lower(),
            )
            if (
                normalized_existing
                and normalized_recovered
                and difflib.SequenceMatcher(
                    None,
                    normalized_existing,
                    normalized_recovered,
                ).ratio()
                >= 0.72
            ):
                continue
            fragments.append((existing["bbox"][0], existing_value))
        fragments.append((recovered["bbox"][0], recovered_value))
        combined_value = " ".join(
            value for _, value in sorted(fragments)
        )
        if sum(character.isalpha() for character in combined_value) > (
            sum(character.isalpha() for character in recovered_value) + 2
        ):
            recovered["text"]["value"] = combined_value
        else:
            recovered["text"]["value"] = recovered_value
        merged = [
            existing
            for existing in merged
            if _bbox_overlap_ratio(
                existing["bbox"], recovered["bbox"]
            )
            < 0.55
        ]
        merged.append(recovered)
    for index, node in enumerate(merged, 1):
        node["id"] = "text-%03d" % index
    return merged


def _graphic_nodes(path, image, background, text_nodes, vertical=None, horizontal=None):
    """Preserve bounded non-text artwork as editable image objects."""

    try:
        import cv2
        import numpy
    except ImportError:
        return []
    array = numpy.asarray(image.convert("RGB"))
    delta = numpy.max(numpy.abs(array.astype("int16") - numpy.array(background)), axis=2)
    mask = (delta >= 12).astype("uint8") * 255
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    )
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    )
    grid_top = horizontal[0] if horizontal else 0
    grid_bottom = horizontal[-1] if horizontal else mask.shape[0] - 1
    grid_left = vertical[0] if vertical else 0
    grid_right = vertical[-1] if vertical else mask.shape[1] - 1
    for x in vertical or []:
        mask[
            max(0, grid_top - 4) : min(mask.shape[0], grid_bottom + 5),
            max(0, x - 4) : min(mask.shape[1], x + 5),
        ] = 0
    for y in horizontal or []:
        mask[
            max(0, y - 4) : min(mask.shape[0], y + 5),
            max(0, grid_left - 4) : min(mask.shape[1], grid_right + 5),
        ] = 0
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    width, height = image.size
    page_area = width * height
    text_boxes = [node["bbox"] for node in text_nodes]
    nodes = []

    def overlaps_text(bbox):
        for tx, ty, tw, th in text_boxes:
            ix = max(0, min(bbox[0] + bbox[2], tx + tw) - max(bbox[0], tx))
            iy = max(0, min(bbox[1] + bbox[3], ty + th) - max(bbox[1], ty))
            if ix * iy >= min(bbox[2] * bbox[3], tw * th) * 0.35:
                return True
        return False

    def append_image(x, y, box_width, box_height):
        if box_width < 10 or box_height < 10:
            return
        ratio = box_width * box_height / page_area
        if ratio < 0.00045 or ratio > 0.11:
            return
        x, box_width, boundary_artwork = _expand_boundary_artwork(
            x, box_width, box_height, vertical, width
        )
        box_width = min(box_width, width - x)
        bbox = [x / width, y / height, box_width / width, box_height / height]
        artwork_crop = image.crop((x, y, x + box_width, y + box_height))
        if overlaps_text(bbox) and not (
            boundary_artwork and _looks_like_artwork(artwork_crop)
        ):
            return
        pad_x, pad_y = 3 / width, 3 / height
        crop = [
            max(0, bbox[0] - pad_x),
            max(0, bbox[1] - pad_y),
            min(1 - max(0, bbox[0] - pad_x), bbox[2] + 2 * pad_x),
            min(1 - max(0, bbox[1] - pad_y), bbox[3] + 2 * pad_y),
        ]
        nodes.append(
            {
                "id": "art-%03d" % (
                    1 + sum(node["type"] == "image" for node in nodes)
                ),
                "type": "image",
                "bbox": crop,
                "crop": crop,
                "content_ref": "reference",
                "raster_justification": "source_artwork",
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

    for x, y, box_width, box_height, area in stats[1:count]:
        ratio = area / page_area
        if ratio < 0.00045 or ratio > 0.11 or box_width < 10 or box_height < 10:
            continue
        component = array[y : y + box_height, x : x + box_width]
        component_mask = mask[y : y + box_height, x : x + box_width].copy()
        if box_width / max(1, box_height) >= 8:
            long_horizontal = cv2.morphologyEx(
                component_mask,
                cv2.MORPH_OPEN,
                cv2.getStructuringElement(
                    cv2.MORPH_RECT, (max(20, box_width // 6), 1)
                ),
            )
            islands = component_mask.copy()
            islands[long_horizontal > 0] = 0
            island_count, _, island_stats, _ = cv2.connectedComponentsWithStats(
                islands, 8
            )
            qualified_islands = [
                item
                for item in island_stats[1:island_count]
                if item[4] / page_area >= 0.00045
                and item[2] >= 10
                and item[3] >= 10
            ]
            if len(qualified_islands) >= 2:
                for island_x, island_y, island_width, island_height, _ in (
                    qualified_islands
                ):
                    append_image(
                        x + island_x,
                        y + island_y,
                        island_width,
                        island_height,
                    )
                continue
        quantized = (
            (component.astype("uint16") // 16) * 16 + 8
        ).clip(0, 255).astype("uint8")
        colors, color_counts = numpy.unique(
            quantized.reshape(-1, 3), axis=0, return_counts=True
        )
        dominant_index = int(color_counts.argmax())
        dominant = colors[dominant_index].astype("int16")
        dominant_ratio = float(color_counts[dominant_index]) / (
            box_width * box_height
        )
        component_density = area / (box_width * box_height)
        background_delta = int(
            numpy.max(
                numpy.abs(dominant - numpy.asarray(background, dtype="int16"))
            )
        )
        is_flat_shape = (
            dominant_ratio >= 0.55
            and component_density >= 0.55
            and background_delta >= 10
        )
        if not is_flat_shape:
            append_image(x, y, box_width, box_height)
            continue

        # Flat panels are recovered by _flat_color_nodes, where repetition
        # proves semantic geometry. Here we only retain residual artwork
        # inside a panel; otherwise decorative bars and floral strokes can be
        # misclassified as document controls.
        residual = (
            numpy.max(
                numpy.abs(component.astype("int16") - dominant), axis=2
            )
            >= 32
        ).astype("uint8") * 255
        long_horizontal = cv2.morphologyEx(
            residual,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(
                cv2.MORPH_RECT, (max(20, box_width // 6), 1)
            ),
        )
        residual[long_horizontal > 0] = 0
        residual = cv2.morphologyEx(
            residual,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        )
        residual_count, _, residual_stats, _ = cv2.connectedComponentsWithStats(
            residual, 8
        )
        for (
            residual_x,
            residual_y,
            residual_width,
            residual_height,
            residual_area,
        ) in residual_stats[1:residual_count]:
            if residual_area / page_area < 0.00045:
                continue
            append_image(
                x + residual_x,
                y + residual_y,
                residual_width,
                residual_height,
            )
    return nodes[:80]


def _bbox_iou(left, right):
    overlap_width = max(
        0,
        min(left[0] + left[2], right[0] + right[2])
        - max(left[0], right[0]),
    )
    overlap_height = max(
        0,
        min(left[1] + left[3], right[1] + right[3])
        - max(left[1], right[1]),
    )
    overlap = overlap_width * overlap_height
    union = left[2] * left[3] + right[2] * right[3] - overlap
    return overlap / union if union else 0.0


def _bbox_overlap_ratio(left, right):
    overlap_width = max(
        0,
        min(left[0] + left[2], right[0] + right[2])
        - max(left[0], right[0]),
    )
    overlap_height = max(
        0,
        min(left[1] + left[3], right[1] + right[3])
        - max(left[1], right[1]),
    )
    smaller = min(left[2] * left[3], right[2] * right[3])
    return overlap_width * overlap_height / smaller if smaller else 0.0


def _deduplicate_visual_nodes(nodes):
    deduplicated = []
    for node in nodes:
        duplicate = next(
            (
                existing
                for existing in deduplicated
                if existing["type"] in {"rectangle", "rounded_rectangle"}
                and node["type"] in {"rectangle", "rounded_rectangle"}
                and _bbox_overlap_ratio(existing["bbox"], node["bbox"]) >= 0.80
            ),
            None,
        )
        if duplicate is None:
            deduplicated.append(node)
    for index, node in enumerate(deduplicated, 1):
        if node["type"] == "image":
            node["id"] = "art-%03d" % index
        elif node["type"] in {"rectangle", "rounded_rectangle"}:
            node["id"] = "shape-%03d" % index
    return deduplicated


def _needs_decorative_texture(image, background, redactions):
    try:
        import cv2
        import numpy
    except ImportError:
        return False
    array = numpy.asarray(image.convert("RGB"))
    delta = numpy.sum(
        numpy.abs(array.astype("int16") - numpy.asarray(background, dtype="int16")),
        axis=2,
    )
    residual = (delta >= 42).astype("uint8")
    height, width = residual.shape
    for x, y, box_width, box_height in redactions:
        left = max(0, int(round((x - 0.006) * width)))
        top = max(0, int(round((y - 0.006) * height)))
        right = min(width, int(round((x + box_width + 0.006) * width)))
        bottom = min(height, int(round((y + box_height + 0.006) * height)))
        residual[top:bottom, left:right] = 0
    residual = cv2.morphologyEx(
        residual,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
    )
    border = max(2, int(round(min(width, height) * 0.03)))
    boundary_pixels = numpy.concatenate(
        (
            residual[:border].reshape(-1),
            residual[-border:].reshape(-1),
            residual[:, :border].reshape(-1),
            residual[:, -border:].reshape(-1),
        )
    )
    return (
        float(residual.mean()) >= 0.0025
        and float(boundary_pixels.mean()) >= 0.005
    )


def _text_panel_nodes(image, background, text_nodes):
    """Recover low-contrast flat panels surrounding native text."""

    try:
        import cv2
        import numpy
    except ImportError:
        return []
    array = numpy.asarray(image.convert("RGB"))
    width, height = image.size
    background_array = numpy.asarray(background, dtype="int16")
    nodes = []
    for text_node in text_nodes:
        bx, by, bw, bh = text_node["bbox"]
        if bw / max(bh, 1 / height) < 3:
            continue
        left = max(0, int(round((bx - bw * 0.12) * width)))
        top = max(0, int(round((by - bh * 0.65) * height)))
        right = min(width, int(round((bx + bw * 1.12) * width)))
        bottom = min(height, int(round((by + bh * 1.65) * height)))
        region = array[top:bottom, left:right]
        if region.size == 0:
            continue
        band = max(2, int(round(min(region.shape[:2]) * 0.18)))
        border_pixels = numpy.concatenate(
            (
                region[:band].reshape(-1, 3),
                region[-band:].reshape(-1, 3),
                region[:, :band].reshape(-1, 3),
                region[:, -band:].reshape(-1, 3),
            )
        )
        quantized = (
            (border_pixels.astype("uint16") // 8) * 8 + 4
        ).clip(0, 255).astype("uint8")
        colors, counts = numpy.unique(quantized, axis=0, return_counts=True)
        candidates = sorted(
            zip(colors, counts),
            key=lambda item: int(item[1]),
            reverse=True,
        )
        panel_color = next(
            (
                color.astype("int16")
                for color, _ in candidates
                if int(numpy.max(numpy.abs(color.astype("int16") - background_array)))
                >= 10
            ),
            None,
        )
        if panel_color is None:
            continue
        panel_mask = (
            numpy.max(
                numpy.abs(array.astype("int16") - panel_color), axis=2
            )
            <= 12
        ).astype("uint8") * 255
        component_count, _, stats, _ = cv2.connectedComponentsWithStats(
            panel_mask, 8
        )
        text_box = [
            bx,
            by,
            bw,
            bh,
        ]
        best = None
        best_overlap = 0.0
        for x, y, box_width, box_height, area in stats[1:component_count]:
            if box_width / max(1, box_height) < 3 or area < box_width * box_height * 0.55:
                continue
            candidate = [x / width, y / height, box_width / width, box_height / height]
            overlap_x = max(
                0,
                min(candidate[0] + candidate[2], bx + bw)
                - max(candidate[0], bx),
            )
            overlap_y = max(
                0,
                min(candidate[1] + candidate[3], by + bh)
                - max(candidate[1], by),
            )
            overlap = overlap_x * overlap_y
            if overlap > best_overlap:
                best = candidate
                best_overlap = overlap
        if best is None or best_overlap < text_box[2] * text_box[3] * 0.45:
            continue
        if any(
            max(
                abs(best[index] - existing["bbox"][index])
                for index in range(4)
            )
            <= 0.01
            for existing in nodes
        ):
            continue
        nodes.append(
            {
                "id": "panel-text-%03d" % (len(nodes) + 1),
                "type": "rectangle",
                "bbox": best,
                "z": 10,
                "editable": True,
                "style": {
                    "fill": _hex(tuple(int(value) for value in panel_color)),
                    "stroke": None,
                    "stroke_width": 0,
                    "corner_radius": 0,
                    "opacity": 1,
                },
            }
        )
    return nodes


def extract_scene_graph(reference_path, hints=None):
    """Measure one raster reference into a generic editable scene graph."""

    reference_path = str(reference_path)
    with Image.open(reference_path) as source:
        image = source.convert("RGB")
    width, height = image.size
    page_width, page_height, orientation = _page_geometry(width, height)
    background = _dominant_color(image)
    vertical, horizontal = _long_lines(image, background)
    vertical = [x for x in vertical if width * 0.01 <= x <= width * 0.99]
    horizontal = [y for y in horizontal if height * 0.01 <= y <= height * 0.99]
    vertical, horizontal = _intersection_lines(
        image, background, vertical, horizontal
    )
    horizontal = _continuous_horizontal_lines(
        image, background, vertical, horizontal
    )
    vertical = _regular_subset(vertical, 3)
    horizontal = _regular_subset(horizontal, 3)
    text_nodes = _ocr_nodes(
        reference_path,
        image,
        vertical,
        horizontal,
        page_width_mm=page_width,
        page_height_mm=page_height,
    )
    nodes = []
    flat_nodes = _deduplicate_visual_nodes(
        _flat_color_nodes(image, background, text_nodes)
    )
    panel_text_nodes = _panel_ocr_nodes(
        image,
        flat_nodes,
        page_width_mm=page_width,
        page_height_mm=page_height,
    )
    text_nodes = _merge_panel_text(text_nodes, panel_text_nodes)
    visual_nodes = _deduplicate_visual_nodes(
        flat_nodes
        + _text_panel_nodes(image, background, text_nodes)
        + _graphic_nodes(
            reference_path,
            image,
            background,
            text_nodes,
            vertical,
            horizontal,
        )
    )
    if len(vertical) >= 3 and len(horizontal) >= 3:
        x0, x1 = vertical[0], vertical[-1]
        y0, y1 = horizontal[0], horizontal[-1]
        line_pixels = []
        pixels = image.load()
        for x in vertical:
            for y in horizontal:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        pixel = pixels[
                            min(width - 1, max(0, x + dx)),
                            min(height - 1, max(0, y + dy)),
                        ]
                        if _different(pixel, background):
                            line_pixels.append(tuple((channel // 8) * 8 + 4 for channel in pixel))
        stroke = (
            Counter(line_pixels).most_common(1)[0][0]
            if line_pixels
            else (96, 96, 96)
        )
        stroke_color = _hex(stroke)
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
    nodes.extend(visual_nodes)
    nodes.extend(text_nodes)
    redactions = [
        list(node["bbox"])
        for node in nodes
        if node["type"]
        in {
            "text",
            "rectangle",
            "rounded_rectangle",
            "ellipse",
            "line",
            "polygon",
            "grid",
        }
    ]
    if _needs_decorative_texture(image, background, redactions):
        nodes = [
            {
                "id": "cleaned-page-texture",
                "type": "image",
                "bbox": [0, 0, 1, 1],
                "crop": [0, 0, 1, 1],
                "content_ref": "cleaned-reference-background",
                "redactions": redactions,
                "background_fill": _hex(background),
                "raster_justification": "source_texture",
                "z": 0,
                "editable": True,
                "style": {
                    "fill": None,
                    "stroke": None,
                    "stroke_width": 0,
                    "corner_radius": 0,
                    "opacity": 1,
                },
            }
        ] + [node for node in nodes if node["type"] != "image"]
    else:
        nodes.insert(
            0,
            {
                "id": "page-background",
                "type": "rectangle",
                "bbox": [0, 0, 0.999, 0.999],
                "z": 0,
                "editable": True,
                "style": {
                    "fill": _hex(background),
                    "stroke": None,
                    "stroke_width": 0,
                    "corner_radius": 0,
                    "opacity": 1,
                },
            },
        )
    return {
        "version": "scene-graph.v1",
        "page": {
            "width": page_width,
            "height": page_height,
            "orientation": orientation,
        },
        "nodes": nodes,
        "constraints": [],
    }
