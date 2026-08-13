# Vendored KLayout-fork sign-off engine

These files are a VERBATIM copy of the KLayout fork's chip/PDK-AGNOSTIC engine
scripts, vendored so a clean plugin install can reach the capability with no
container re-image.

* upstream: `vibeic/klayout` — `metal-fill/`
* upstream commit: 9a6d57257e1653ff181252537a4b6288eb713d6a

Do NOT edit these in place — fix them in the fork and re-vendor, otherwise the
plugin copy and the fork silently diverge. Setting `$VIBEIC_KLAYOUT_TOOLS` to a
fork checkout OVERRIDES this copy (see `_klayout_launch.find_engine`), so a
newer engine can always be used without re-vendoring. The override root may use
either the fork's hyphenated directory names (`metal-fill/`) or this plugin's
underscored ones (`metal_fill/`).

This claim is FALSIFIABLE and is checked: the fork's
`plugin-wiring/vendored_sync_check.py` asserts both that every vendored file is
byte-identical to its fork counterpart AND that the commit named above is the
one whose fork content those bytes are. Between 2026-07-08 and 2026-08-12 this
line named 9d2ef8578 while `metal_fill.py` had moved three commits past it, so
the documented maintenance action ("fix them in the fork and re-vendor") would
have silently reverted `space_to_metal` and `mfg_grid_um`. Re-run the checker
after any re-vendoring; it prints the exact line to write.

The `*.example.json` configs carry GENERIC PLACEHOLDER layer numbers and bounds
only — no foundry data. A real sign-off supplies the foundry deck by path.
