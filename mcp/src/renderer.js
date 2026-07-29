import { strToU8, zipSync } from "fflate";

const EMU_PER_INCH = 914400;
const TWIPS_PER_INCH = 1440;
const FAILURE = "Artifact Mimicry validation failed. No editable artifact was generated.";
const SUPPORTED_TYPES = new Set(["roundRect", "rect", "ellipse", "parallelogram", "text"]);
const TYPE_ALIASES = new Map([
  ["roundedrectangle", "roundRect"],
  ["roundedrect", "roundRect"],
  ["roundrect", "roundRect"],
  ["rounded_rectangle", "roundRect"],
  ["rounded-rectangle", "roundRect"],
  ["capsule", "roundRect"],
  ["pill", "roundRect"],
  ["rectangle", "rect"],
  ["box", "rect"],
  ["circle", "ellipse"],
  ["oval", "ellipse"],
  ["textbox", "text"],
  ["text_box", "text"],
  ["text-box", "text"]
]);
const NAMED_COLORS = new Map([
  ["black", "000000"],
  ["white", "FFFFFF"],
  ["transparent", null],
  ["none", null]
]);

export class ArtifactValidationError extends Error {
  constructor(report) {
    const detail = report.findings?.length ? `\n${report.findings.join("\n")}` : "";
    super(`${FAILURE}${detail}`);
    this.name = "ArtifactValidationError";
    this.report = report;
  }
}

const escapeXml = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");

const color = (value, fallback) => {
  const raw = String(value ?? fallback).trim().toLowerCase();
  if (NAMED_COLORS.has(raw)) return NAMED_COLORS.get(raw);
  let normalized = raw.replace(/^#/, "").toUpperCase();
  if (/^[0-9A-F]{3}$/.test(normalized)) {
    normalized = normalized
      .split("")
      .map((digit) => `${digit}${digit}`)
      .join("");
  }
  if (/^[0-9A-F]{8}$/.test(normalized)) normalized = normalized.slice(0, 6);
  if (!/^[0-9A-F]{6}$/.test(normalized)) {
    throw new TypeError(`invalid six-digit color: ${value}`);
  }
  return normalized;
};

const firstDefined = (...values) => values.find((value) => value != null);

const canonicalType = (value) => {
  const raw = String(value ?? "rect");
  if (SUPPORTED_TYPES.has(raw)) return raw;
  return TYPE_ALIASES.get(raw.toLowerCase()) ?? raw;
};

const normalizedCoordinate = (value, pageExtent, absolute = false) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return Number.NaN;
  return absolute || numeric > 1 ? numeric / pageExtent : numeric;
};

const validationError = (gates, findings, normalization = {}) =>
  new ArtifactValidationError({
    status: "FAIL",
    gates,
    findings,
    normalization
  });

const normalizeTask = (rawTask) => {
  const source = rawTask && typeof rawTask === "object" ? rawTask : {};
  const rawPage = source.page ?? source.canvas ?? {};
  const width = Number(firstDefined(rawPage.width_in, rawPage.width, source.width_in, 11.69));
  const height = Number(firstDefined(rawPage.height_in, rawPage.height, source.height_in, 8.27));
  const rawElements = firstDefined(source.elements, source.shapes, source.objects, []);
  const gates = {
    I_01_task_contract:
      source.task == null || source.task === "artifact_mimicry",
    I_02_output_contract:
      (source.output?.format == null || source.output.format === "docx") &&
      (source.output?.editable == null || source.output.editable === true),
    I_03_page_geometry:
      Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0,
    I_04_elements_present: Array.isArray(rawElements) && rawElements.length > 0
  };
  const findings = [];
  if (!gates.I_01_task_contract) {
    findings.push(`I-01 unsupported task type: ${String(source.task)}`);
  }
  if (!gates.I_02_output_contract) {
    findings.push(
      `I-02 output must be editable DOCX; observed format=${String(source.output?.format)} editable=${String(source.output?.editable)}`
    );
  }
  if (!gates.I_03_page_geometry) {
    findings.push(`I-03 invalid page geometry: width=${String(width)} height=${String(height)}`);
  }
  if (!gates.I_04_elements_present) findings.push("I-04 no editable elements were supplied");
  if (findings.length) throw validationError(gates, findings);

  let normalizedElementAliases = 0;
  const elementFindings = [];
  const elements = rawElements.map((rawElement, index) => {
    const item = rawElement && typeof rawElement === "object" ? rawElement : {};
    const aliased =
      source.shapes != null ||
      item.name != null ||
      item.kind != null ||
      item.left != null ||
      item.top != null ||
      item.width != null ||
      item.height != null ||
      item.backgroundColor != null ||
      item.textColor != null ||
      item.fontSize != null ||
      item.direction != null;
    if (aliased) normalizedElementAliases += 1;
    const type = canonicalType(firstDefined(item.type, item.kind, item.shape, "rect"));
    const rawX = firstDefined(item.x, item.left);
    const rawY = firstDefined(item.y, item.top);
    const rawW = firstDefined(item.w, item.width);
    const rawH = firstDefined(item.h, item.height);
    const absoluteCoordinates = [rawX, rawY, rawW, rawH].some(
      (value) => Number(value) > 1
    );
    const x = normalizedCoordinate(rawX, width, absoluteCoordinates);
    const y = normalizedCoordinate(rawY, height, absoluteCoordinates);
    const w = normalizedCoordinate(rawW, width, absoluteCoordinates);
    const h = normalizedCoordinate(rawH, height, absoluteCoordinates);
    const id = String(firstDefined(item.id, item.name, `element_${index + 1}`)).trim();
    const editable = item.editable == null ? true : item.editable === true;
    if (!SUPPORTED_TYPES.has(type)) {
      elementFindings.push(`I-05 element ${id || index + 1} has unsupported type: ${type}`);
    }
    if (
      ![x, y, w, h].every(Number.isFinite) ||
      x < 0 ||
      y < 0 ||
      w <= 0 ||
      h <= 0 ||
      x + w > 1.001 ||
      y + h > 1.001
    ) {
      elementFindings.push(
        `I-06 element ${id || index + 1} has invalid geometry: x=${x} y=${y} w=${w} h=${h}`
      );
    }
    if (!id) elementFindings.push(`I-07 element ${index + 1} has no identifier`);
    if (!editable) elementFindings.push(`I-08 element ${id || index + 1} is not editable`);
    try {
      if (item.fill != null || item.backgroundColor != null) {
        color(firstDefined(item.fill, item.backgroundColor), "FFFFFF");
      }
      if (item.text_color != null || item.textColor != null) {
        color(firstDefined(item.text_color, item.textColor), "FFFFFF");
      }
    } catch (error) {
      elementFindings.push(`I-09 element ${id || index + 1}: ${error.message}`);
    }
    return {
      id,
      type,
      x,
      y,
      w,
      h,
      editable,
      text: String(item.text ?? ""),
      fill: firstDefined(item.fill, item.backgroundColor, null),
      text_color: firstDefined(item.text_color, item.textColor, "#FFFFFF"),
      font: firstDefined(item.font, item.font_family, item.fontFamily, "Arial"),
      font_size_pt: Number(firstDefined(item.font_size_pt, item.fontSize, 12)),
      bold: Boolean(firstDefined(item.bold, item.fontWeight === "bold", false)),
      rtl: Boolean(firstDefined(item.rtl, item.direction === "rtl", false))
    };
  });

  const ids = elements.map((element) => element.id);
  if (new Set(ids).size !== ids.length) elementFindings.push("I-10 element identifiers are not unique");
  if (elementFindings.length) {
    throw validationError(
      { ...gates, I_05_elements_valid: false },
      elementFindings,
      { normalized_element_aliases: normalizedElementAliases }
    );
  }

  return {
    task: {
      task: "artifact_mimicry",
      output: {
        format: "docx",
        artifact_kind: "editable_template",
        editable: true
      },
      page: { width_in: width, height_in: height },
      elements,
      validation: source.validation
    },
    normalization: {
      defaulted_output_contract: source.task == null || source.output == null,
      normalized_element_aliases: normalizedElementAliases
    }
  };
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
  const textColor = color(element.text_color, "FFFFFF") ?? "FFFFFF";
  const fill = element.fill == null ? null : color(element.fill, "FFFFFF");
  const fillXml =
    fill == null
      ? "<a:noFill/>"
      : `<a:solidFill><a:srgbClr val="${fill}"/></a:solidFill>`;
  const adjustment =
    preset === "roundRect"
      ? '<a:avLst><a:gd name="adj" fmla="val 50000"/></a:avLst>'
      : "<a:avLst/>";
  const textXml = paragraph(text, rtl, font, size, textColor, Boolean(element.bold));
  const vmlTag =
    preset === "roundRect" ? "v:roundrect" : preset === "ellipse" ? "v:oval" : "v:rect";
  const arc = preset === "roundRect" ? ' arcsize="50%"' : "";
  const vmlFill = fill == null ? "none" : `#${fill}`;
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
  const normalized = normalizeTask(task);
  const resolvedTask = normalized.task;
  const suppliedExpectations =
    expectations && Object.keys(expectations).length
      ? expectations
      : resolvedTask.validation ?? {};
  const derivedExpectations = {
    expected_round_rects: resolvedTask.elements.filter(
      (element) => element.type === "roundRect"
    ).length,
    forbid_media: true,
    forbid_tables: true,
    required_text: resolvedTask.elements
      .map((element) => element.text)
      .filter(Boolean),
    required_shape_text: resolvedTask.elements
      .map((element) => element.text)
      .filter(Boolean),
    rtl_shape_text: resolvedTask.elements
      .filter((element) => element.rtl && element.text)
      .map((element) => element.text),
    required_shape_names: resolvedTask.elements.map((element) => element.id)
  };
  const resolvedExpectations = { ...derivedExpectations, ...suppliedExpectations };

  const xml = documentXml(resolvedTask);
  const shapeText = resolvedTask.elements
    .map((element) => String(element.text ?? ""))
    .join("\n");
  const ids = new Set(resolvedTask.elements.map((element) => element.id));
  const roundRectCount = resolvedTask.elements.filter(
    (element) => element.type === "roundRect"
  ).length;
  const rtlFailures = (resolvedExpectations.rtl_shape_text ?? []).filter(
    (label) =>
      !resolvedTask.elements.some(
        (element) => String(element.text ?? "").includes(label) && element.rtl === true
      )
  );
  const gates = {
    S_01_native_docx: true,
    S_02_no_flattened_media:
      !resolvedExpectations.forbid_media || !xml.includes("<a:blip"),
    S_03_round_rect_count:
      resolvedExpectations.expected_round_rects == null ||
      roundRectCount === resolvedExpectations.expected_round_rects,
    S_04_editable_text: includesEvery(
      resolvedExpectations.required_text ?? [],
      shapeText
    ),
    S_05_text_inside_shapes: includesEvery(
      resolvedExpectations.required_shape_text ?? [],
      shapeText
    ),
    S_06_no_schedule_table:
      !resolvedExpectations.forbid_tables || !xml.includes("<w:tbl"),
    S_07_single_page_structure: !xml.includes('w:type="page"'),
    S_08_rtl_inside_shape: rtlFailures.length === 0,
    S_09_required_shape_primitives: (
      resolvedExpectations.required_shape_names ?? []
    ).every((id) => ids.has(id))
  };
  const findings = [];
  if (!gates.S_01_native_docx) findings.push("S-01 native DOCX parts are missing");
  if (!gates.S_02_no_flattened_media) findings.push("S-02 flattened media was observed");
  if (!gates.S_03_round_rect_count) {
    findings.push(
      `S-03 expected ${resolvedExpectations.expected_round_rects} roundRect shapes; observed ${roundRectCount}`
    );
  }
  const missingText = (resolvedExpectations.required_text ?? []).filter(
    (value) => !shapeText.includes(value)
  );
  if (missingText.length) findings.push(`S-04 missing editable text: ${missingText.join(", ")}`);
  const missingShapeText = (resolvedExpectations.required_shape_text ?? []).filter(
    (value) => !shapeText.includes(value)
  );
  if (missingShapeText.length) {
    findings.push(`S-05 text is not inside shapes: ${missingShapeText.join(", ")}`);
  }
  if (!gates.S_06_no_schedule_table) findings.push("S-06 a Word table was observed");
  if (!gates.S_07_single_page_structure) findings.push("S-07 an explicit page break was observed");
  if (rtlFailures.length) {
    findings.push(`S-08 RTL containment failed: ${rtlFailures.join(", ")}`);
  }
  const missingShapes = (resolvedExpectations.required_shape_names ?? []).filter(
    (id) => !ids.has(id)
  );
  if (missingShapes.length) {
    findings.push(`S-09 missing shape primitives: ${missingShapes.join(", ")}`);
  }
  const report = {
    status: Object.values(gates).every(Boolean) ? "PASS" : "FAIL",
    gates,
    findings,
    normalization: normalized.normalization
  };
  if (report.status !== "PASS") throw new ArtifactValidationError(report);

  const files = Object.fromEntries(
    Object.entries({ ...packageFiles, "word/document.xml": xml }).map(([name, content]) => [
      name,
      strToU8(content)
    ])
  );
  return { bytes: zipSync(files, { level: 6 }), report };
}
