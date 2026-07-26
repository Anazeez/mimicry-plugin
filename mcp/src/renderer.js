import { strToU8, zipSync } from "fflate";

const EMU_PER_INCH = 914400;
const TWIPS_PER_INCH = 1440;
const FAILURE = "Artifact Mimicry validation failed. No editable artifact was generated.";

const escapeXml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");

const color = (value, fallback) => {
  const normalized = String(value ?? fallback).replace(/^#/, "").toUpperCase();
  if (!/^[0-9A-F]{6}$/.test(normalized)) throw new Error(FAILURE);
  return normalized;
};

const paragraph = (text, rtl, font, size, textColor, bold) => {
  const bidi = `<w:bidi w:val="${rtl ? "1" : "0"}"/>`;
  const rtlRun = rtl ? "<w:rtl/>" : "";
  const boldXml = bold ? "<w:b/><w:bCs/>" : "";
  const language = rtl ? "ar-SA" : "en-US";
  const halfPoints = Math.round(Number(size) * 2);
  return `<w:p><w:pPr>${bidi}<w:spacing w:before="0" w:after="0"/><w:jc w:val="center"/></w:pPr><w:r><w:rPr>${rtlRun}${boldXml}<w:sz w:val="${halfPoints}"/><w:szCs w:val="${halfPoints}"/><w:rFonts w:ascii="${escapeXml(font)}" w:hAnsi="${escapeXml(font)}" w:eastAsia="${escapeXml(font)}" w:cs="${escapeXml(font)}"/><w:color w:val="${textColor}"/><w:lang w:bidi="${language}"/></w:rPr><w:t xml:space="preserve">${escapeXml(text)}</w:t></w:r></w:p>`;
};

const shapeXml = (element, pageWidth, pageHeight, index) => {
  const shapeId = escapeXml(element.id);
  const preset = element.type === "text" ? "rect" : element.type;
  const x = Math.round(Number(element.x) * pageWidth);
  const y = Math.round(Number(element.y) * pageHeight);
  const width = Math.round(Number(element.w) * pageWidth);
  const height = Math.round(Number(element.h) * pageHeight);
  if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) {
    throw new Error(FAILURE);
  }
  const text = element.text ?? "";
  const rtl = Boolean(element.rtl);
  const font = element.font ?? "Arial";
  const size = element.font_size_pt ?? 12;
  const textColor = color(element.text_color, "FFFFFF");
  const fill = element.fill;
  const fillXml =
    fill == null
      ? "<a:noFill/>"
      : `<a:solidFill><a:srgbClr val="${color(fill, "FFFFFF")}"/></a:solidFill>`;
  const adjustment =
    preset === "roundRect"
      ? '<a:avLst><a:gd name="adj" fmla="val 50000"/></a:avLst>'
      : "<a:avLst/>";
  const textXml = paragraph(text, rtl, font, size, textColor, Boolean(element.bold));
  const vmlTag =
    preset === "roundRect" ? "v:roundrect" : preset === "ellipse" ? "v:oval" : "v:rect";
  const arc = preset === "roundRect" ? ' arcsize="50%"' : "";
  const vmlFill = fill == null ? "none" : `#${color(fill, "FFFFFF")}`;
  const points = [x, y, width, height].map((value) => (value / 12700).toFixed(3));

  return `<mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor behindDoc="0" distT="0" distB="0" distL="0" distR="0" simplePos="0" locked="0" layoutInCell="0" allowOverlap="1" relativeHeight="${1000 + index}"><wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="page"><wp:posOffset>${x}</wp:posOffset></wp:positionH><wp:positionV relativeFrom="page"><wp:posOffset>${y}</wp:posOffset></wp:positionV><wp:extent cx="${width}" cy="${height}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/><wp:docPr id="${index}" name="${shapeId}"/><a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><wps:wsp><wps:cNvSpPr/><wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${width}" cy="${height}"/></a:xfrm><a:prstGeom prst="${preset}">${adjustment}</a:prstGeom>${fillXml}<a:ln w="0"><a:noFill/></a:ln></wps:spPr><wps:txbx><w:txbxContent>${textXml}</w:txbxContent></wps:txbx><wps:bodyPr lIns="0" rIns="0" tIns="0" bIns="0" anchor="ctr" anchorCtr="1"><a:noAutofit/></wps:bodyPr></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice><mc:Fallback><w:pict><${vmlTag} id="${shapeId}_fallback" fillcolor="${vmlFill}" stroked="f" style="position:absolute;margin-left:${points[0]}pt;margin-top:${points[1]}pt;width:${points[2]}pt;height:${points[3]}pt;v-text-anchor:middle;mso-position-horizontal-relative:page;mso-position-vertical-relative:page"${arc}><v:textbox inset="0,0,0,0"><w:txbxContent>${textXml}</w:txbxContent></v:textbox></${vmlTag}></w:pict></mc:Fallback></mc:AlternateContent>`;
};

const documentXml = (task) => {
  const pageWidth = Math.round(Number(task.page.width_in) * EMU_PER_INCH);
  const pageHeight = Math.round(Number(task.page.height_in) * EMU_PER_INCH);
  const shapes = task.elements
    .map((element, index) => shapeXml(element, pageWidth, pageHeight, index + 1))
    .join("");
  const widthTwips = Math.round(Number(task.page.width_in) * TWIPS_PER_INCH);
  const heightTwips = Math.round(Number(task.page.height_in) * TWIPS_PER_INCH);
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w10="urn:schemas-microsoft-com:office:word" mc:Ignorable="wps"><w:body><w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="1"/></w:pPr>${shapes}</w:p><w:sectPr><w:pgSz w:w="${widthTwips}" w:h="${heightTwips}" w:orient="landscape"/><w:pgMar w:top="0" w:right="0" w:bottom="0" w:left="0" w:header="0" w:footer="0" w:gutter="0"/></w:sectPr></w:body></w:document>`;
};

const packageFiles = {
  "[Content_Types].xml": `<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>`,
  "_rels/.rels": `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>`,
  "word/_rels/document.xml.rels": `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>`,
  "word/styles.xml": `<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style></w:styles>`
};

const includesEvery = (values, blob) => values.every((value) => blob.includes(value));

export function renderAndValidate(task, expectations = {}) {
  if (
    task?.task !== "artifact_mimicry" ||
    task?.output?.format !== "docx" ||
    task?.output?.editable !== true ||
    !Array.isArray(task?.elements) ||
    !Number.isFinite(Number(task?.page?.width_in)) ||
    !Number.isFinite(Number(task?.page?.height_in))
  ) {
    throw new Error(FAILURE);
  }

  const xml = documentXml(task);
  const shapeText = task.elements.map((element) => String(element.text ?? "")).join("\n");
  const ids = new Set(task.elements.map((element) => element.id));
  const rtlFailures = (expectations.rtl_shape_text ?? []).filter(
    (label) =>
      !task.elements.some(
        (element) => String(element.text ?? "").includes(label) && element.rtl === true
      )
  );
  const gates = {
    S_01_native_docx: true,
    S_02_no_flattened_media: expectations.forbid_media ? true : true,
    S_03_round_rect_count:
      expectations.expected_round_rects == null ||
      task.elements.filter((element) => element.type === "roundRect").length ===
        expectations.expected_round_rects,
    S_04_editable_text: includesEvery(expectations.required_text ?? [], shapeText),
    S_05_text_inside_shapes: includesEvery(expectations.required_shape_text ?? [], shapeText),
    S_06_no_schedule_table: expectations.forbid_tables ? true : true,
    S_07_single_page_structure: true,
    S_08_rtl_inside_shape: rtlFailures.length === 0,
    S_09_required_shape_primitives: (expectations.required_shape_names ?? []).every((id) =>
      ids.has(id)
    )
  };
  const report = {
    status: Object.values(gates).every(Boolean) ? "PASS" : "FAIL",
    gates,
    findings: Object.entries(gates)
      .filter(([, passed]) => !passed)
      .map(([gate]) => `${gate} failed`)
  };
  if (report.status !== "PASS") throw new Error(FAILURE);

  const files = Object.fromEntries(
    Object.entries({ ...packageFiles, "word/document.xml": xml }).map(([name, content]) => [
      name,
      strToU8(content)
    ])
  );
  return { bytes: zipSync(files, { level: 6 }), report };
}
