# Vendored KLayout-fork sign-off engine

These files are a VERBATIM copy of the KLayout fork's chip/PDK-AGNOSTIC engine
scripts, vendored so a clean plugin install can reach the capability with no
container re-image.

* upstream: `vibeic/klayout` — `gds-antenna/`
* upstream commit: 9d2ef857833277850d0237435ce558c033ef33af

Do NOT edit these in place — fix them in the fork and re-vendor, otherwise the
plugin copy and the fork silently diverge. Setting `$VIBEIC_KLAYOUT_TOOLS` to a
fork checkout OVERRIDES this copy (see `_klayout_launch.find_engine`), so a
newer engine can always be used without re-vendoring.

The `*.example.json` configs carry GENERIC PLACEHOLDER layer numbers and bounds
only — no foundry data. A real sign-off supplies the foundry deck by path.
