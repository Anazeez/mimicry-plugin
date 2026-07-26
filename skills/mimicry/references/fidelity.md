# Fidelity verification

Render the source and output to the same dimensions. Inspect side by side and, when possible, with a transparency overlay.

Check in this order:

1. canvas, margins, major regions, repeated frames;
2. typography metrics, line breaks, hierarchy, and density;
3. object geometry, spacing, alignment, borders, and corner treatment;
4. palette, opacity, images, crop, layering, and shadows;
5. directionality, reading order, semantic editability, and application behavior.

A mismatch is material when it changes output class, editability, primitive
type, signature geometry, hierarchy, reflow, clipping, repeated spacing,
reading order, or content visibility. Rectangular table cells replacing
signature capsules are an automatic signature-geometry failure.

Perform one focused correction pass for material mismatches. If an exact match is blocked by unavailable fonts, assets, or target-application limits, keep the best editable approximation and disclose:

- original element;
- substitute used;
- reason;
- visible or behavioral impact.

Never award a fidelity score without inspecting rendered output at the target size.

The delivery gate is pass/fail for correct artifact type, editability, and
rendered inspection. Signature geometry must score at least 90% and overall
visual fidelity at least 85%, with no material failures.
