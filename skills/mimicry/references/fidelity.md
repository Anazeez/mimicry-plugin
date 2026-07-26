# Fidelity verification

Render the source and output to the same dimensions. Inspect side by side and, when possible, with a transparency overlay.

Check in this order:

1. canvas, margins, major regions, repeated frames;
2. typography metrics, line breaks, hierarchy, and density;
3. object geometry, spacing, alignment, borders, and corner treatment;
4. palette, opacity, images, crop, layering, and shadows;
5. directionality, reading order, semantic editability, and application behavior.

A mismatch is material when it changes hierarchy, causes reflow or clipping, shifts a repeated edge, changes reading order, obscures content, or makes a native element non-editable.

Perform one focused correction pass for material mismatches. If an exact match is blocked by unavailable fonts, assets, or target-application limits, keep the best editable approximation and disclose:

- original element;
- substitute used;
- reason;
- visible or behavioral impact.

Never award a fidelity score without inspecting rendered output at the target size.

