"""Reference-agnostic scene graph validation."""

from copy import deepcopy
import re


NODE_TYPES = {
    "group",
    "text",
    "rectangle",
    "rounded_rectangle",
    "ellipse",
    "line",
    "polygon",
    "grid",
    "image",
}
CONSTRAINT_TYPES = {
    "inside",
    "align_left",
    "align_right",
    "align_top",
    "align_bottom",
    "align_center_x",
    "align_center_y",
    "adjacent_x",
    "adjacent_y",
    "equal_width",
    "equal_height",
    "gap_x",
    "gap_y",
}
TEXT_DIRECTIONS = {"ltr", "rtl", "mixed"}
TEXT_ALIGNMENTS = {"left", "center", "right", "justify"}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class SceneGraphError(ValueError):
    """Stable fail-closed scene graph error."""

    def __init__(self, code, message):
        super().__init__("%s: %s" % (code, message))
        self.code = code


def _mapping(value, code, label):
    if not isinstance(value, dict):
        raise SceneGraphError(code, "%s must be an object" % label)
    return value


def _number(value, code, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SceneGraphError(code, "%s must be numeric" % label)
    return float(value)


def _bbox(value, node_id):
    if not isinstance(value, list) or len(value) != 4:
        raise SceneGraphError("SCENE_BOUNDS", "%s bbox must contain x, y, width, height" % node_id)
    x, y, width, height = [
        _number(item, "SCENE_BOUNDS", "%s bbox" % node_id) for item in value
    ]
    if (
        x < 0
        or y < 0
        or width <= 0
        or height <= 0
        or x + width > 1.000001
        or y + height > 1.000001
    ):
        raise SceneGraphError("SCENE_BOUNDS", "%s bbox lies outside the normalized page" % node_id)
    return [x, y, width, height]


def _color(value, label):
    if value is not None and (not isinstance(value, str) or not HEX_COLOR.match(value)):
        raise SceneGraphError("SCENE_COLOR", "%s must be #RRGGBB or null" % label)
    return value.lower() if isinstance(value, str) else value


def _validate_text(value, node_id):
    text = _mapping(value, "SCENE_TEXT", "%s text" % node_id)
    if not isinstance(text.get("value"), str):
        raise SceneGraphError("SCENE_TEXT", "%s text value must be a string" % node_id)
    direction = text.get("direction", "ltr")
    if direction not in TEXT_DIRECTIONS:
        raise SceneGraphError("SCENE_TEXT", "%s has invalid text direction" % node_id)
    align = text.get("align", "left")
    if align not in TEXT_ALIGNMENTS:
        raise SceneGraphError("SCENE_TEXT", "%s has invalid text alignment" % node_id)
    size = _number(text.get("font_size_pt", 12), "SCENE_TEXT", "%s font size" % node_id)
    if size <= 0:
        raise SceneGraphError("SCENE_TEXT", "%s font size must be positive" % node_id)
    weight = int(_number(text.get("weight", 400), "SCENE_TEXT", "%s weight" % node_id))
    if weight < 100 or weight > 900:
        raise SceneGraphError("SCENE_TEXT", "%s font weight is outside 100-900" % node_id)
    return {
        "value": text["value"],
        "direction": direction,
        "font_family": str(text.get("font_family", "Arial")),
        "font_size_pt": size,
        "weight": weight,
        "align": align,
        "color": _color(text.get("color", "#000000"), "%s text color" % node_id),
    }


def _validate_style(value, node_id):
    style = _mapping(value or {}, "SCENE_STYLE", "%s style" % node_id)
    stroke_width = _number(
        style.get("stroke_width", 0), "SCENE_STYLE", "%s stroke width" % node_id
    )
    corner_radius = _number(
        style.get("corner_radius", 0), "SCENE_STYLE", "%s corner radius" % node_id
    )
    opacity = _number(style.get("opacity", 1), "SCENE_STYLE", "%s opacity" % node_id)
    if stroke_width < 0 or corner_radius < 0 or not 0 <= opacity <= 1:
        raise SceneGraphError("SCENE_STYLE", "%s style values are outside their ranges" % node_id)
    return {
        "fill": _color(style.get("fill"), "%s fill" % node_id),
        "stroke": _color(style.get("stroke"), "%s stroke" % node_id),
        "stroke_width": stroke_width,
        "corner_radius": corner_radius,
        "opacity": opacity,
    }


def validate_scene_graph(value):
    """Validate and normalize a generic page scene graph."""

    scene = deepcopy(_mapping(value, "SCENE_ROOT", "scene"))
    if scene.get("version") != "scene-graph.v1":
        raise SceneGraphError("SCENE_VERSION", "version must be scene-graph.v1")
    page = _mapping(scene.get("page"), "SCENE_PAGE", "page")
    width = _number(page.get("width"), "SCENE_PAGE", "page width")
    height = _number(page.get("height"), "SCENE_PAGE", "page height")
    if width <= 0 or height <= 0:
        raise SceneGraphError("SCENE_PAGE", "page dimensions must be positive")
    orientation = page.get("orientation", "landscape" if width >= height else "portrait")
    if orientation not in {"landscape", "portrait"}:
        raise SceneGraphError("SCENE_PAGE", "orientation must be landscape or portrait")

    raw_nodes = scene.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise SceneGraphError("SCENE_NODES", "nodes must be a non-empty array")
    normalized_nodes = []
    ids = set()
    for index, raw_node in enumerate(raw_nodes):
        node = _mapping(raw_node, "SCENE_NODE", "node %d" % index)
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            raise SceneGraphError("SCENE_NODE_ID", "node %d requires a stable id" % index)
        if node_id in ids:
            raise SceneGraphError("SCENE_DUPLICATE_ID", "duplicate node id %s" % node_id)
        ids.add(node_id)
        node_type = node.get("type")
        if node_type not in NODE_TYPES:
            raise SceneGraphError("SCENE_NODE_TYPE", "%s has unsupported type %s" % (node_id, node_type))
        normalized = {
            "id": node_id,
            "type": node_type,
            "bbox": _bbox(node.get("bbox"), node_id),
            "z": int(_number(node.get("z", 0), "SCENE_Z", "%s z" % node_id)),
            "editable": node.get("editable") is True,
        }
        if not normalized["editable"]:
            raise SceneGraphError("SCENE_EDITABILITY", "%s must remain editable" % node_id)
        if node.get("parent") is not None:
            normalized["parent"] = node["parent"]
        if node_type == "text":
            normalized["text"] = _validate_text(node.get("text"), node_id)
        else:
            normalized["style"] = _validate_style(node.get("style"), node_id)
        if node_type == "image":
            content_ref = node.get("content_ref")
            if not isinstance(content_ref, str) or not content_ref:
                raise SceneGraphError("SCENE_IMAGE", "%s requires content_ref" % node_id)
            normalized["content_ref"] = content_ref
            normalized["crop"] = list(node.get("crop", [0, 0, 1, 1]))
            raster_justification = node.get("raster_justification")
            if raster_justification is not None:
                if raster_justification not in {
                    "source_artwork",
                    "source_illustration",
                    "source_logo",
                    "source_photo",
                    "source_texture",
                }:
                    raise SceneGraphError(
                        "SCENE_IMAGE",
                        "%s has an unsupported raster justification" % node_id,
                    )
                normalized["raster_justification"] = raster_justification
        if node_type == "grid":
            rows = int(_number(node.get("rows"), "SCENE_GRID", "%s rows" % node_id))
            columns = int(_number(node.get("columns"), "SCENE_GRID", "%s columns" % node_id))
            if rows <= 0 or columns <= 0:
                raise SceneGraphError("SCENE_GRID", "%s rows and columns must be positive" % node_id)
            normalized.update({"rows": rows, "columns": columns})
        normalized_nodes.append(normalized)

    for node in normalized_nodes:
        if node.get("parent") is not None and node["parent"] not in ids:
            raise SceneGraphError("SCENE_REFERENCE", "%s references a missing parent" % node["id"])

    constraints = scene.get("constraints", [])
    if not isinstance(constraints, list):
        raise SceneGraphError("SCENE_CONSTRAINT", "constraints must be an array")
    normalized_constraints = []
    for index, constraint_value in enumerate(constraints):
        constraint = _mapping(
            constraint_value, "SCENE_CONSTRAINT", "constraint %d" % index
        )
        constraint_type = constraint.get("type")
        source = constraint.get("source")
        target = constraint.get("target")
        if constraint_type not in CONSTRAINT_TYPES:
            raise SceneGraphError("SCENE_CONSTRAINT", "unsupported constraint type")
        if source not in ids or target not in ids:
            raise SceneGraphError("SCENE_REFERENCE", "constraint references a missing node")
        tolerance = _number(
            constraint.get("tolerance", 0.01), "SCENE_CONSTRAINT", "constraint tolerance"
        )
        if tolerance < 0 or tolerance > 1:
            raise SceneGraphError("SCENE_CONSTRAINT", "constraint tolerance is outside 0-1")
        normalized_constraints.append(
            {
                "type": constraint_type,
                "source": source,
                "target": target,
                "tolerance": tolerance,
            }
        )

    return {
        "version": "scene-graph.v1",
        "page": {"width": width, "height": height, "orientation": orientation},
        "nodes": normalized_nodes,
        "constraints": normalized_constraints,
    }
