import unittest

from container.app.schemas import SceneGraphError, validate_scene_graph


def valid_scene():
    return {
        "version": "scene-graph.v1",
        "page": {"width": 1200, "height": 800, "orientation": "landscape"},
        "nodes": [
            {
                "id": "root",
                "type": "group",
                "bbox": [0.05, 0.05, 0.9, 0.9],
                "z": 0,
                "editable": True,
            },
            {
                "id": "title",
                "type": "text",
                "parent": "root",
                "bbox": [0.1, 0.1, 0.8, 0.1],
                "z": 1,
                "editable": True,
                "text": {
                    "value": "تقرير PROJECT",
                    "direction": "mixed",
                    "font_family": "Arial",
                    "font_size_pt": 28,
                    "weight": 700,
                    "align": "right",
                    "color": "#173b57",
                },
            },
            {
                "id": "panel",
                "type": "rounded_rectangle",
                "parent": "root",
                "bbox": [0.1, 0.3, 0.8, 0.5],
                "z": 1,
                "editable": True,
                "style": {
                    "fill": "#ffffff",
                    "stroke": "#173b57",
                    "stroke_width": 3,
                    "corner_radius": 0.04,
                    "opacity": 1,
                },
            },
        ],
        "constraints": [
            {
                "type": "inside",
                "source": "title",
                "target": "root",
                "tolerance": 0.01,
            }
        ],
    }


class SceneGraphSchemaTests(unittest.TestCase):
    def test_accepts_generic_nodes_and_relationships(self):
        scene = validate_scene_graph(valid_scene())
        self.assertEqual(scene["version"], "scene-graph.v1")
        self.assertEqual(scene["nodes"][1]["text"]["direction"], "mixed")

    def test_rejects_fixture_specific_node_types(self):
        scene = valid_scene()
        scene["nodes"][2]["type"] = "meeting_grid_cell"
        with self.assertRaisesRegex(SceneGraphError, "SCENE_NODE_TYPE"):
            validate_scene_graph(scene)

    def test_rejects_duplicate_ids(self):
        scene = valid_scene()
        scene["nodes"][2]["id"] = "title"
        with self.assertRaisesRegex(SceneGraphError, "SCENE_DUPLICATE_ID"):
            validate_scene_graph(scene)

    def test_rejects_boxes_outside_the_page(self):
        scene = valid_scene()
        scene["nodes"][1]["bbox"] = [0.8, 0.1, 0.4, 0.1]
        with self.assertRaisesRegex(SceneGraphError, "SCENE_BOUNDS"):
            validate_scene_graph(scene)

    def test_rejects_missing_parent_and_constraint_targets(self):
        scene = valid_scene()
        scene["nodes"][1]["parent"] = "missing"
        with self.assertRaisesRegex(SceneGraphError, "SCENE_REFERENCE"):
            validate_scene_graph(scene)


if __name__ == "__main__":
    unittest.main()
