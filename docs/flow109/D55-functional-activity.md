# D55 functional activity component

The general `--flow 109 --entry-step D55 --exit-step D55` entry dispatches
`flow109_functional_activity.execute`. It uses the existing
`sim_activity_dump.dump` producer on the **adopted gate netlist**, never RTL,
and the existing `_ppa.power` activity and power-report consumers.

The pinned LibreLane `OpenROAD.STAPostPNR` has no VCD/SAIF configuration.
Its present final-power adoption is vectorless. D55 therefore uses native
OpenSTA `read_vcd`/`report_power` as a complementary component. It does not
replace or publish `reports/phase3/power.rpt`, and cannot claim the actual
post-route/final power operation adopted this activity.

## Input and qualification

`input/flow109/D55.json` has schema
`vibeic.flow109.functional-activity.v1`, `basis: adopted_netlist_gls`, the exact
`top`, SHA-bound `adopted_netlist`, `liberty`, nonempty `simulation_models`,
`sdc`, `requirements`, `loads`, and a `modes` object with one SHA-bound
`testbench` for every required mode. Required files use `{path, sha256}`.
The SDC is a source-bound, qualified input, not an adapter-generated timing
target. Only simple create_clock, input/output delay/transition and clock
uncertainty/transition commands with scalar get_ports/get_clocks are supported.
Nested Tcl evaluation, source/read commands and transitive Verilog file I/O
(includes/readmem/fopen/system/SDF) are explicitly unimplemented and rejected
before native launch, rather than publishing an incomplete input hash closure.

The bound requirements file records owner approval and source reference,
`modes.<name>.required_ports`, and a full-window `{start_tick: 0, end_tick,
timescale}`. `external_loads` records one rail's voltage and every output's
`{rail, capacitance_library_units}`. The separately bound load file must equal
that approved content plus `requirements_sha256`. The selected Liberty's
nominal voltage must match. The adapter does not choose product thresholds.

Each compiler, simulator and OpenSTA use needs an independent current D03
qualification, with exact executable, library/model scope, operation source
closure and configuration. Native launch rechecks qualification, source and
input identities, refuses undeclared engines, and leaves native lifetime to
owner/progress supervision instead of imposing a fixed wall-clock kill. Generated VCD, scope manifest, Tcl and power report are
also hash-bound before consumption/publication. Tests' developer control
records are not production PDK/tool qualification.

## Evidence and limits

Each unique attempt retains actual argv/return code/log, GLS VCD and scope,
per-port observations/transitions, window, native annotation origin for every
required top port, output-load census and actual vector-power report. A global
nonzero annotation count alone is insufficient: every required data port must
have origin `vcd`; all native scalar top ports must be in the requirement set.
A simulator failure remains FAIL even when it writes a partial VCD.

A successful component publishes
`adopted/functional_activity/gls_activity_freeze.json`; failed attempts cannot
leave an old current freeze available. Existing attempt receipts are retained.

This tranche supports only full-window, single-rail, scalar top-port GLS.
Partial windows, bus/inout handling, mapped RTL VCD/SAIF, analog current traces,
mission adequacy, qualified upper bounds and actual downstream post-route
power adoption remain unimplemented/unmeasured. A component PASS proves this
declared native producer/consumer operation, not D55 signoff.

## Row acceptance (the three registry obligations)

The sealed Default row (`input/flow109/D55-row.json`) judges each registry
obligation with its registry operator against an authority the producer does
not write. The producer's own scenario list and freeze are evidence only.

| Obligation | Operator | Authority | Measured from sealed evidence |
|---|---|---|---|
| `functional_mission_modes` | `covers_all` | `requirements/functional_activity/functional_mission_modes.json#/required_items` (`{name}` items, requirements-owner approved, source-bound) | modes whose native GLS, VCD census and VCD-annotated power all passed |
| `activity_waveform_bound_identity` | `matches_adopted_reference` | `adopted/functional_activity/activity_waveform_bound_identity.json`, sourced from `input/flow109/D55/activity_waveform_bound_identity.json` | per mode: adopted-netlist SHA-256, top, VCD scope, VCD port widths, VCD timescale |
| `load_rail_mapping` | `matches_adopted_reference` | `adopted/functional_activity/load_rail_mapping.json`, sourced from `input/flow109/D55/load_rail_mapping.json` | `{rails: {r: {voltage_v}}, ports: {p: {rail, capacitance_pf}}}` from SDC `set_load` scaled by the Liberty `capacitive_load_unit`, pad rail connectivity and nominal voltage |

Adopted references use schema `vibeic.flow109.adopted-reference.v1`, carry a
complete `reference_identity`, and their `input/` source must hold the same
body. `propose-waveform-reference` writes a waveform-identity proposal from the
adopted netlist's port declarations (never from a VCD) for every approved
mission mode; the load mapping comes from the documents and is not proposed by
code. Absent, unapproved or unbound authority leaves the obligation
NOT_MEASURED; a missed mode, a waveform bound to another netlist/scope/port set,
or a differing load or rail is FAIL. The row PASSes only when all three pass
and every acceptance dependency row is accepted. The container image check
uses the runtime-resolved EDA image digest; no digest is stored in source.
