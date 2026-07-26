# LTR, RTL, and mixed direction

Direction is structural, not cosmetic alignment.

- Record `ltr`, `rtl`, or `mixed` for the artifact and each material region.
- Apply native bidi paragraph and run properties; use logical start/end alignment where supported.
- Preserve the source's table column order. Do not reverse columns merely because the language is RTL.
- Preserve number, date, currency, URL, email, acronym, and formula order inside RTL text.
- Use explicit directional isolation for mixed runs only when native automatic bidi produces the wrong order.
- In slides, set text direction, paragraph direction, and reading/z-order independently.
- In spreadsheets, set sheet right-to-left mode when the source uses it, then set cell-level direction and alignment. Formulas remain in the application's formula syntax.
- In documents, verify lists, tab stops, hanging indents, punctuation, headers/footers, and page numbers independently.

Render-test mixed strings containing Arabic or Hebrew, Latin product names, parentheses, percentages, dates, and numerals. Visual right alignment alone does not pass.

