#!/usr/bin/env python3
"""Fail-closed structural and rendered-evidence validator for Mimicry DOCX."""

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
}


def inspect_docx(path, expectations):
    gates = {}
    findings = []
    try:
        archive = ZipFile(path)
    except (BadZipFile, OSError) as exc:
        return {"status": "FAIL", "findings": [f"S-01 invalid DOCX: {exc}"]}
    with archive:
        names = set(archive.namelist())
        native = {"[Content_Types].xml", "word/document.xml"}.issubset(names)
        gates["S-01_native_docx"] = native
        if not native:
            findings.append("S-01 native DOCX parts are missing")
            return {"status": "FAIL", "gates": gates, "findings": findings}
        tree = ET.fromstring(archive.read("word/document.xml"))
        media = [name for name in names if name.startswith("word/media/")]
        gates["S-02_no_flattened_media"] = not media if expectations.get("forbid_media") else True
        if not gates["S-02_no_flattened_media"]:
            findings.append(f"S-02 word/media contains {len(media)} file(s)")
        round_rects = [
            node for node in tree.findall(".//a:prstGeom", NS)
            if node.get("prst") == "roundRect"
        ]
        expected = expectations.get("expected_round_rects")
        gates["S-03_round_rect_count"] = expected is None or len(round_rects) == expected
        if not gates["S-03_round_rect_count"]:
            findings.append(f"S-03 expected {expected} roundRect shapes; observed {len(round_rects)}")
        text_nodes = [node.text or "" for node in tree.findall(".//w:t", NS)]
        text_blob = "\n".join(text_nodes)
        missing_text = [value for value in expectations.get("required_text", []) if value not in text_blob]
        gates["S-04_editable_text"] = not missing_text
        if missing_text:
            findings.append("S-04 missing editable text: " + ", ".join(missing_text))
        shape_text = []
        for shape in tree.findall(".//wps:wsp", NS):
            shape_text.extend(node.text or "" for node in shape.findall(".//w:t", NS))
        missing_nested = [
            value for value in expectations.get("required_shape_text", [])
            if value not in "\n".join(shape_text)
        ]
        gates["S-05_text_inside_shapes"] = not missing_nested
        if missing_nested:
            findings.append("S-05 text is not inside shapes: " + ", ".join(missing_nested))
        tables = tree.findall(".//w:tbl", NS)
        gates["S-06_no_schedule_table"] = not tables if expectations.get("forbid_tables") else True
        if not gates["S-06_no_schedule_table"]:
            findings.append(f"S-06 observed {len(tables)} table(s)")
        breaks = [
            node for node in tree.findall(".//w:br", NS)
            if node.get("{%s}type" % NS["w"]) == "page"
        ]
        gates["S-07_single_page_structure"] = not breaks
        if breaks:
            findings.append(f"S-07 observed {len(breaks)} explicit page break(s)")
        rtl_labels = expectations.get("rtl_shape_text", [])
        rtl_failures = []
        for label in rtl_labels:
            containing = [
                shape for shape in tree.findall(".//wps:wsp", NS)
                if label in "".join(node.text or "" for node in shape.findall(".//w:t", NS))
            ]
            if not containing:
                rtl_failures.append(label)
                continue
            shape = containing[0]
            bidi = shape.find(".//w:bidi", NS)
            rtl = shape.find(".//w:rtl", NS)
            if bidi is None or bidi.get("{%s}val" % NS["w"]) != "1" or rtl is None:
                rtl_failures.append(label)
        gates["S-08_rtl_inside_shape"] = not rtl_failures
        if rtl_failures:
            findings.append("S-08 RTL containment failed: " + ", ".join(rtl_failures))
    return {
        "status": "PASS" if all(gates.values()) else "FAIL",
        "gates": gates,
        "findings": findings,
    }


def apply_render_gate(report, render_report):
    required = {
        "header_containment",
        "grid_alignment",
        "pill_geometry",
        "rtl_layout",
        "word_compatible_render",
    }
    if render_report is None:
        report["status"] = "FAIL"
        report.setdefault("findings", []).append("V-00 rendered evidence is required")
        return report
    missing = sorted(key for key in required if render_report.get(key) != "PASS")
    report.setdefault("gates", {})["V-01_rendered_evidence"] = not missing
    if missing:
        report["status"] = "FAIL"
        report.setdefault("findings", []).append("V-01 render gates failed: " + ", ".join(missing))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("docx")
    parser.add_argument("expectations_json")
    parser.add_argument("--render-report")
    parser.add_argument("--output-report")
    args = parser.parse_args()
    expectations = json.loads(Path(args.expectations_json).read_text(encoding="utf-8"))
    render_report = (
        json.loads(Path(args.render_report).read_text(encoding="utf-8"))
        if args.render_report else None
    )
    report = apply_render_gate(inspect_docx(args.docx, expectations), render_report)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output_report:
        Path(args.output_report).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
