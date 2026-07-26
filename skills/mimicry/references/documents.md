# Documents: Word and Google Docs

Inspect and reproduce:

- page size, orientation, margins, columns, sections, page/section breaks;
- paragraph and character styles, indents, spacing, tabs, lists, drop caps;
- headers, footers, page numbers, footnotes, endnotes, citations, and links;
- tables, cell padding, borders, fills, row repetition, merged cells, and alignment;
- text boxes, shapes, captions, image crop/wrap/anchor, and object layering;
- fields, content controls, comments, tracked changes, and alt text when supported.

Prefer native named styles over per-run formatting. Clone source styles when a native file is available. Use real headers/footers and tables rather than positioned text that only looks correct on one page.

Choose Word primitives from visual geometry, not semantics. A timetable, form,
or matrix that visually uses isolated rounded capsules must use individual
editable rounded-rectangle shapes with text inside them. A hidden table may
assist alignment, but visible rectangular cells, softened cell borders, and a
full-page screenshot are not faithful substitutes. Preserve independent gaps,
corner radii, z-order, and editability for every repeated shape.

For Google Docs, preserve the intended layout within Docs' supported pagination and object model. If a Word feature has no faithful Docs equivalent, use the least destructive editable approximation and list it in substitutions.

Validate by rendering every page. Check page count, line endings, table splits, headers/footers, widows/orphans, and image placement.
