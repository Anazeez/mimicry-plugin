# Fidelity fixtures

These files calibrate the generic renderer and machine judge. Production code
must never import from `fixtures/` or contain fixture text, identifiers,
dimensions, row counts, or column counts.

- `meeting-grid`: real RTL grid reference and the rejected pre-fix DOCX.
- `capsule-timetable`: real RTL schedule with independent rounded capsules.
- `ltr-poster`: deterministic LTR poster reference.
- `mixed-direction`: deterministic Arabic/English report reference.
