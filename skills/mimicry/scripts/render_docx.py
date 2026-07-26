#!/usr/bin/env python3
"""Render normalized editable shapes to a native DrawingML DOCX."""

import argparse
import html
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


EMU_PER_INCH = 914400
TWIPS_PER_INCH = 1440


def esc(value):
    return html.escape(str(value), quote=True)


def color(value, default):
    value = (value or default).lstrip("#").upper()
    if len(value) != 6 or any(c not in "0123456789ABCDEF" for c in value):
        raise ValueError("colors must be six-digit hex values")
    return value


def paragraph(text, rtl, font, size, text_color, bold):
    bidi = '<w:bidi w:val="1"/>' if rtl else '<w:bidi w:val="0"/>'
    rtl_run = "<w:rtl/>" if rtl else ""
    bold_xml = "<w:b/><w:bCs/>" if bold else ""
    language = "ar-SA" if rtl else "en-US"
    half_points = int(round(float(size) * 2))
    return (
        "<w:p><w:pPr>"
        f"{bidi}<w:spacing w:before=\"0\" w:after=\"0\"/>"
        '<w:jc w:val="center"/></w:pPr><w:r><w:rPr>'
        f"{rtl_run}{bold_xml}<w:sz w:val=\"{half_points}\"/>"
        f'<w:szCs w:val="{half_points}"/>'
        f'<w:rFonts w:ascii="{esc(font)}" w:hAnsi="{esc(font)}" '
        f'w:eastAsia="{esc(font)}" w:cs="{esc(font)}"/>'
        f'<w:color w:val="{text_color}"/><w:lang w:bidi="{language}"/>'
        f"</w:rPr><w:t xml:space=\"preserve\">{esc(text)}</w:t></w:r></w:p>"
    )


def shape_xml(element, page_width, page_height, index):
    shape_id = esc(element["id"])
    kind = element["type"]
    preset = "rect" if kind == "text" else kind
    x = int(round(float(element["x"]) * page_width))
    y = int(round(float(element["y"]) * page_height))
    width = int(round(float(element["w"]) * page_width))
    height = int(round(float(element["h"]) * page_height))
    text = element.get("text", "")
    rtl = bool(element.get("rtl", False))
    font = element.get("font", "Arial")
    size = element.get("font_size_pt", 12)
    text_color = color(element.get("text_color"), "FFFFFF")
    fill = element.get("fill")
    fill_xml = "<a:noFill/>" if fill is None else (
        f'<a:solidFill><a:srgbClr val="{color(fill, "FFFFFF")}"/></a:solidFill>'
    )
    geometry_adjust = (
        '<a:avLst><a:gd name="adj" fmla="val 50000"/></a:avLst>'
        if preset == "roundRect"
        else "<a:avLst/>"
    )
    text_xml = paragraph(text, rtl, font, size, text_color, bool(element.get("bold")))
    pt_x = x / 12700
    pt_y = y / 12700
    pt_w = width / 12700
    pt_h = height / 12700
    vml_tag = "v:roundrect" if preset == "roundRect" else (
        "v:oval" if preset == "ellipse" else "v:rect"
    )
    arc = ' arcsize="50%"' if preset == "roundRect" else ""
    vml_fill = "none" if fill is None else f"#{color(fill, 'FFFFFF')}"
    return f"""
<mc:AlternateContent>
  <mc:Choice Requires="wps">
    <w:drawing>
      <wp:anchor behindDoc="0" distT="0" distB="0" distL="0" distR="0"
        simplePos="0" locked="0" layoutInCell="0" allowOverlap="1"
        relativeHeight="{1000 + index}">
        <wp:simplePos x="0" y="0"/>
        <wp:positionH relativeFrom="page"><wp:posOffset>{x}</wp:posOffset></wp:positionH>
        <wp:positionV relativeFrom="page"><wp:posOffset>{y}</wp:posOffset></wp:positionV>
        <wp:extent cx="{width}" cy="{height}"/>
        <wp:effectExtent l="0" t="0" r="0" b="0"/>
        <wp:wrapNone/>
        <wp:docPr id="{index}" name="{shape_id}"/>
        <a:graphic>
          <a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
            <wps:wsp>
              <wps:cNvSpPr/>
              <wps:spPr>
                <a:xfrm><a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm>
                <a:prstGeom prst="{preset}">{geometry_adjust}</a:prstGeom>
                {fill_xml}
                <a:ln w="0"><a:noFill/></a:ln>
              </wps:spPr>
              <wps:txbx><w:txbxContent>{text_xml}</w:txbxContent></wps:txbx>
              <wps:bodyPr lIns="0" rIns="0" tIns="0" bIns="0"
                anchor="ctr" anchorCtr="1"><a:noAutofit/></wps:bodyPr>
            </wps:wsp>
          </a:graphicData>
        </a:graphic>
      </wp:anchor>
    </w:drawing>
  </mc:Choice>
  <mc:Fallback>
    <w:pict>
      <{vml_tag} id="{shape_id}_fallback" fillcolor="{vml_fill}" stroked="f"
        style="position:absolute;margin-left:{pt_x:.3f}pt;margin-top:{pt_y:.3f}pt;
        width:{pt_w:.3f}pt;height:{pt_h:.3f}pt;v-text-anchor:middle;
        mso-position-horizontal-relative:page;mso-position-vertical-relative:page"{arc}>
        <v:textbox inset="0,0,0,0"><w:txbxContent>{text_xml}</w:txbxContent></v:textbox>
      </{vml_tag}>
    </w:pict>
  </mc:Fallback>
</mc:AlternateContent>"""


def document_xml(task):
    width = int(round(float(task["page"]["width_in"]) * EMU_PER_INCH))
    height = int(round(float(task["page"]["height_in"]) * EMU_PER_INCH))
    shapes = "\n".join(
        shape_xml(item, width, height, index)
        for index, item in enumerate(task["elements"], 1)
    )
    width_twips = int(round(float(task["page"]["width_in"]) * TWIPS_PER_INCH))
    height_twips = int(round(float(task["page"]["height_in"]) * TWIPS_PER_INCH))
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
 xmlns:v="urn:schemas-microsoft-com:vml"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:w10="urn:schemas-microsoft-com:office:word"
 mc:Ignorable="wps">
 <w:body>
  <w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="1"/></w:pPr>{shapes}</w:p>
  <w:sectPr>
   <w:pgSz w:w="{width_twips}" w:h="{height_twips}" w:orient="landscape"/>
   <w:pgMar w:top="0" w:right="0" w:bottom="0" w:left="0" w:header="0" w:footer="0" w:gutter="0"/>
  </w:sectPr>
 </w:body>
</w:document>"""


FILES = {
    "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="xml" ContentType="application/xml"/>
 <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
 <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>""",
    "_rels/.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
    "word/_rels/document.xml.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>""",
    "word/styles.xml": """<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
  <w:name w:val="Normal"/><w:qFormat/>
 </w:style>
</w:styles>""",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_json")
    parser.add_argument("output_docx")
    args = parser.parse_args()
    task = json.loads(Path(args.task_json).read_text(encoding="utf-8"))
    if task.get("task") != "artifact_mimicry":
        raise SystemExit("invalid task")
    if task.get("output", {}).get("format") != "docx":
        raise SystemExit("renderer supports docx tasks only")
    if task.get("output", {}).get("editable") is not True:
        raise SystemExit("editable output is required")
    output = Path(args.output_docx)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in FILES.items():
            archive.writestr(name, content)
        archive.writestr("word/document.xml", document_xml(task))
    print(output)


if __name__ == "__main__":
    main()

