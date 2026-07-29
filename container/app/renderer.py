"""Native LibreOffice scene renderer.

The DOCX is created with UNO drawing objects, saved, reopened by LibreOffice,
and only then exported for inspection. Nothing in this module is fixture-aware.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time

from PIL import Image

try:
    import uno
except ImportError as error:  # pragma: no cover - exercised by the container
    uno = None
    UNO_IMPORT_ERROR = error
else:
    UNO_IMPORT_ERROR = None


PDF_PAGE_PATTERN = re.compile(r"^Pages:\s+(\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class RenderedArtifact:
    docx_path: Path
    pdf_path: Path
    png_path: Path
    manifest: dict


class RenderError(RuntimeError):
    pass


def _property(name, value):
    item = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
    item.Name = name
    item.Value = value
    return item


def _color(value):
    return int(value.lstrip("#"), 16) if value else 0


def _point(x, y):
    value = uno.createUnoStruct("com.sun.star.awt.Point")
    value.X = int(round(x))
    value.Y = int(round(y))
    return value


def _size(width, height):
    value = uno.createUnoStruct("com.sun.star.awt.Size")
    value.Width = max(1, int(round(width)))
    value.Height = max(1, int(round(height)))
    return value


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


@contextmanager
def _office(workspace):
    if uno is None:
        raise RenderError("LibreOffice UNO is unavailable: %s" % UNO_IMPORT_ERROR)
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise RenderError("LibreOffice executable is unavailable")

    profile = Path(workspace) / "lo-profile"
    profile.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    accept = "socket,host=127.0.0.1,port=%d;urp;StarOffice.ComponentContext" % port
    process = subprocess.Popen(
        [
            executable,
            "--headless",
            "--invisible",
            "--nodefault",
            "--nologo",
            "--norestore",
            "--nolockcheck",
            "-env:UserInstallation=%s" % profile.resolve().as_uri(),
            "--accept=%s" % accept,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    desktop = None
    last_error = None
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local
        )
        # Cloudflare starts the container on amd64, while local release checks
        # may emulate amd64. Give LibreOffice enough time to initialize in both
        # environments without weakening the bounded execution contract.
        for _ in range(300):
            if process.poll() is not None:
                detail = process.stderr.read().decode("utf-8", "replace")
                raise RenderError("LibreOffice exited before accepting UNO: %s" % detail)
            try:
                context = resolver.resolve(
                    "uno:socket,host=127.0.0.1,port=%d;urp;StarOffice.ComponentContext"
                    % port
                )
                desktop = context.ServiceManager.createInstanceWithContext(
                    "com.sun.star.frame.Desktop", context
                )
                break
            except Exception as error:
                last_error = error
                time.sleep(0.1)
        if desktop is None:
            raise RenderError("LibreOffice UNO connection timed out: %s" % last_error)
        yield desktop
    finally:
        try:
            if desktop is not None:
                desktop.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stderr is not None:
            process.stderr.close()


def _set_if_supported(target, name, value):
    try:
        target.setPropertyValue(name, value)
    except Exception:
        try:
            setattr(target, name, value)
        except Exception:
            return False
    return True


def _apply_style(shape, style):
    fill = style.get("fill")
    if fill:
        _set_if_supported(
            shape, "FillStyle", uno.Enum("com.sun.star.drawing.FillStyle", "SOLID")
        )
        _set_if_supported(shape, "FillColor", _color(fill))
    else:
        _set_if_supported(
            shape, "FillStyle", uno.Enum("com.sun.star.drawing.FillStyle", "NONE")
        )
    stroke = style.get("stroke")
    width = float(style.get("stroke_width", 0))
    if stroke and width > 0:
        _set_if_supported(
            shape, "LineStyle", uno.Enum("com.sun.star.drawing.LineStyle", "SOLID")
        )
        _set_if_supported(shape, "LineColor", _color(stroke))
        _set_if_supported(shape, "LineWidth", int(round(width * 35.2778)))
    else:
        _set_if_supported(
            shape, "LineStyle", uno.Enum("com.sun.star.drawing.LineStyle", "NONE")
        )
    opacity = float(style.get("opacity", 1))
    transparency = int(round((1 - opacity) * 100))
    _set_if_supported(shape, "FillTransparence", transparency)
    _set_if_supported(shape, "LineTransparence", transparency)


def _crop_reference(reference_path, crop, output_path):
    with Image.open(reference_path) as image:
        width, height = image.size
        x, y, crop_width, crop_height = [float(item) for item in crop]
        box = (
            max(0, int(round(x * width))),
            max(0, int(round(y * height))),
            min(width, int(round((x + crop_width) * width))),
            min(height, int(round((y + crop_height) * height))),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            raise RenderError("image crop is empty")
        image.crop(box).convert("RGB").save(output_path, "PNG")


def _configure_page(document, page):
    page_styles = document.StyleFamilies.getByName("PageStyles")
    style_name = document.CurrentController.ViewCursor.PageStyleName
    if not page_styles.hasByName(style_name):
        style_name = page_styles.getElementNames()[0]
    style = page_styles.getByName(style_name)
    width = int(round(float(page["width"]) * 100))
    height = int(round(float(page["height"]) * 100))
    style.IsLandscape = page["orientation"] == "landscape"
    style.Width = width
    style.Height = height
    style.LeftMargin = 0
    style.RightMargin = 0
    style.TopMargin = 0
    style.BottomMargin = 0
    return width, height


def _set_geometry(shape, bbox, page_width, page_height):
    x, y, width, height = bbox
    shape.Position = _point(x * page_width, y * page_height)
    shape.Size = _size(width * page_width, height * page_height)


def _anchor_to_first_page(shape):
    _set_if_supported(
        shape,
        "AnchorType",
        uno.Enum("com.sun.star.text.TextContentAnchorType", "AT_PAGE"),
    )
    _set_if_supported(shape, "AnchorPageNo", 1)


def _add_text(document, draw_page, node, page_width, page_height):
    shape = document.createInstance("com.sun.star.drawing.TextShape")
    shape.Name = node["id"]
    draw_page.add(shape)
    _anchor_to_first_page(shape)
    _set_geometry(shape, node["bbox"], page_width, page_height)
    text = node["text"]
    shape.String = text["value"]
    _set_if_supported(shape, "CharFontName", text["font_family"])
    _set_if_supported(shape, "CharHeight", float(text["font_size_pt"]))
    _set_if_supported(shape, "CharWeight", 150.0 if text["weight"] >= 600 else 100.0)
    _set_if_supported(shape, "CharColor", _color(text["color"]))
    _set_if_supported(
        shape,
        "TextHorizontalAdjust",
        uno.Enum(
            "com.sun.star.drawing.TextHorizontalAdjust",
            {"left": "LEFT", "center": "CENTER", "right": "RIGHT", "justify": "BLOCK"}[
                text["align"]
            ],
        ),
    )
    _set_if_supported(
        shape,
        "TextVerticalAdjust",
        uno.Enum("com.sun.star.drawing.TextVerticalAdjust", "CENTER"),
    )
    _set_if_supported(shape, "TextLeftDistance", 120)
    _set_if_supported(shape, "TextRightDistance", 120)
    cursor = shape.createTextCursor()
    cursor.gotoEnd(True)
    _set_if_supported(
        cursor,
        "ParaAdjust",
        uno.Enum(
            "com.sun.star.style.ParagraphAdjust",
            {"left": "LEFT", "center": "CENTER", "right": "RIGHT", "justify": "BLOCK"}[
                text["align"]
            ],
        ),
    )
    if text["direction"] in {"rtl", "mixed"}:
        _set_if_supported(
            cursor,
            "WritingMode",
            uno.getConstantByName("com.sun.star.text.WritingMode2.RL_TB"),
        )
        _set_if_supported(
            cursor,
            "ParaWritingMode",
            uno.getConstantByName("com.sun.star.text.WritingMode2.RL_TB"),
        )
    _set_if_supported(shape, "TextAutoGrowHeight", False)
    _set_if_supported(shape, "TextAutoGrowWidth", False)
    _set_geometry(shape, node["bbox"], page_width, page_height)
    return shape


def _add_shape(document, draw_page, node, page_width, page_height, reference, workspace):
    node_type = node["type"]
    if node_type == "text":
        return _add_text(document, draw_page, node, page_width, page_height)
    if node_type == "group":
        return None
    service = {
        "rectangle": "com.sun.star.drawing.RectangleShape",
        "rounded_rectangle": "com.sun.star.drawing.RectangleShape",
        "ellipse": "com.sun.star.drawing.EllipseShape",
        "line": "com.sun.star.drawing.RectangleShape",
        "polygon": "com.sun.star.drawing.RectangleShape",
        "grid": "com.sun.star.drawing.RectangleShape",
        "image": "com.sun.star.drawing.GraphicObjectShape",
    }[node_type]
    shape = document.createInstance(service)
    shape.Name = node["id"]
    draw_page.add(shape)
    _anchor_to_first_page(shape)
    if node_type == "image":
        crop_path = Path(workspace) / ("%s.png" % node["id"])
        _crop_reference(reference, node.get("crop", [0, 0, 1, 1]), crop_path)
        _set_if_supported(shape, "GraphicURL", crop_path.resolve().as_uri())
    _set_geometry(shape, node["bbox"], page_width, page_height)
    if node_type == "line":
        line_style = dict(node.get("style", {}))
        line_style["fill"] = line_style.get("stroke")
        line_style["stroke"] = None
        line_style["stroke_width"] = 0
        _apply_style(shape, line_style)
    else:
        _apply_style(shape, node.get("style", {}))
    if node_type == "rounded_rectangle":
        radius = float(node["style"].get("corner_radius", 0))
        absolute_height = node["bbox"][3] * page_height
        _set_if_supported(shape, "CornerRadius", int(round(radius * absolute_height)))
    if node_type == "grid":
        rows = node["rows"]
        columns = node["columns"]
        x, y, width, height = node["bbox"]
        for row in range(1, rows):
            grid_line = {
                "id": "%s-row-%d" % (node["id"], row),
                "type": "line",
                "bbox": [x, y + height * row / rows, width, 0.0001],
                "style": node.get("style", {}),
            }
            _add_shape(
                document, draw_page, grid_line, page_width, page_height, reference, workspace
            )
        for column in range(1, columns):
            grid_line = {
                "id": "%s-column-%d" % (node["id"], column),
                "type": "line",
                "bbox": [x + width * column / columns, y, 0.0001, height],
                "style": node.get("style", {}),
            }
            _add_shape(
                document, draw_page, grid_line, page_width, page_height, reference, workspace
            )
    return shape


def _store(document, path, filter_name):
    document.storeAsURL(
        path.resolve().as_uri(),
        (
            _property("FilterName", filter_name),
            _property("Overwrite", True),
        ),
    )


def _export_pdf(document, path):
    document.storeToURL(
        path.resolve().as_uri(),
        (
            _property("FilterName", "writer_pdf_Export"),
            _property("Overwrite", True),
        ),
    )


def _rasterize(pdf_path, output_path):
    prefix = output_path.with_suffix("")
    result = subprocess.run(
        [
            "pdftoppm",
            "-f",
            "1",
            "-singlefile",
            "-png",
            "-r",
            "144",
            str(pdf_path),
            str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode != 0:
        raise RenderError("PDF rasterization failed: %s" % result.stderr.strip())
    generated = prefix.with_suffix(".png")
    if generated != output_path:
        generated.replace(output_path)


def _page_count(pdf_path):
    result = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RenderError("PDF inspection failed: %s" % result.stderr.strip())
    match = PDF_PAGE_PATTERN.search(result.stdout)
    if not match:
        raise RenderError("PDF page count is unavailable")
    return int(match.group(1))


def _nonwhite_ratio(path):
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        pixels = rgb.getdata()
        count = rgb.width * rgb.height
        nonwhite = sum(1 for red, green, blue in pixels if min(red, green, blue) < 245)
    return nonwhite / count if count else 0


def _shape_geometry(shape):
    try:
        position = shape.Position
        x, y = position.X, position.Y
    except Exception:
        x = getattr(shape, "HoriOrientPosition")
        y = getattr(shape, "VertOrientPosition")
    try:
        size = shape.Size
        width, height = size.Width, size.Height
    except Exception:
        width = getattr(shape, "Width")
        height = getattr(shape, "Height")
    return float(x), float(y), float(width), float(height)


def _actual_nodes(document, page_width, page_height):
    draw_page = document.getDrawPage()
    nodes = []
    for index in range(draw_page.Count):
        shape = draw_page.getByIndex(index)
        node_id = str(getattr(shape, "Name", "") or "shape-%d" % index)
        x, y, width, height = _shape_geometry(shape)
        nodes.append(
            {
                "id": node_id,
                "shape_type": str(getattr(shape, "ShapeType", "unknown")),
                "bbox": [
                    x / page_width,
                    y / page_height,
                    width / page_width,
                    height / page_height,
                ],
            }
        )
    return nodes


def render_scene(scene, reference_path, workspace):
    """Build, reopen, and render one scene as a native editable DOCX."""

    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    reference_path = Path(reference_path)
    docx_path = workspace / "artifact.docx"
    pdf_path = workspace / "artifact.pdf"
    png_path = workspace / "artifact.png"

    with _office(workspace) as desktop:
        document = desktop.loadComponentFromURL(
            "private:factory/swriter", "_blank", 0, (_property("Hidden", True),)
        )
        if document is None:
            raise RenderError("LibreOffice did not create a Writer document")
        try:
            page_width, page_height = _configure_page(document, scene["page"])
            draw_page = document.getDrawPage()
            for node in sorted(scene["nodes"], key=lambda item: item["z"]):
                _add_shape(
                    document,
                    draw_page,
                    node,
                    page_width,
                    page_height,
                    reference_path,
                    workspace,
                )
            _store(document, docx_path, "Office Open XML Text")
        finally:
            document.close(True)

        reopened = desktop.loadComponentFromURL(
            docx_path.resolve().as_uri(),
            "_blank",
            0,
            (
                _property("Hidden", True),
                _property("FilterName", "Office Open XML Text"),
                _property("ReadOnly", True),
            ),
        )
        if reopened is None:
            raise RenderError("LibreOffice could not reopen the generated DOCX")
        try:
            actual_nodes = _actual_nodes(reopened, page_width, page_height)
            _export_pdf(reopened, pdf_path)
        finally:
            reopened.close(True)

    _rasterize(pdf_path, png_path)
    manifest = {
        "page_count": _page_count(pdf_path),
        "native_shape_count": len([node for node in scene["nodes"] if node["type"] != "group"]),
        "image_object_count": len([node for node in scene["nodes"] if node["type"] == "image"]),
        "full_page_image_count": len(
            [
                node
                for node in scene["nodes"]
                if node["type"] == "image"
                and node["bbox"][2] >= 0.95
                and node["bbox"][3] >= 0.95
            ]
        ),
        "stroke_widths": sorted(
            {
                float(node.get("style", {}).get("stroke_width", 0))
                for node in scene["nodes"]
                if float(node.get("style", {}).get("stroke_width", 0)) > 0
            }
        ),
        "text_colors": sorted(
            {node["text"]["color"] for node in scene["nodes"] if node["type"] == "text"}
        ),
        "rtl_text_nodes": [
            node["id"]
            for node in scene["nodes"]
            if node["type"] == "text" and node["text"]["direction"] in {"rtl", "mixed"}
        ],
        "actual_nodes": actual_nodes,
        "nonwhite_ratio": _nonwhite_ratio(png_path),
    }
    return RenderedArtifact(docx_path, pdf_path, png_path, manifest)


def inspect_rendered_docx(docx_path, workspace):
    """Reopen an arbitrary DOCX and reject visually blank output."""

    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    pdf_path = workspace / "inspection.pdf"
    png_path = workspace / "inspection.png"
    with _office(workspace) as desktop:
        document = desktop.loadComponentFromURL(
            Path(docx_path).resolve().as_uri(),
            "_blank",
            0,
            (
                _property("Hidden", True),
                _property("FilterName", "Office Open XML Text"),
                _property("ReadOnly", True),
            ),
        )
        if document is None:
            return {"accepted": False, "failed_gates": ["R_REOPEN"]}
        try:
            _export_pdf(document, pdf_path)
        finally:
            document.close(True)
    _rasterize(pdf_path, png_path)
    ratio = _nonwhite_ratio(png_path)
    failed = []
    if ratio < 0.002:
        failed.append("R_NONBLANK")
    if _page_count(pdf_path) != 1:
        failed.append("R_SINGLE_PAGE")
    return {
        "accepted": not failed,
        "failed_gates": failed,
        "nonwhite_ratio": ratio,
    }
