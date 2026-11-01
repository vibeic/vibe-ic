# A18 macro-only chip top

`analog_macro_top_gen.py PROJECT` generates the logical chip and LibreLane inputs.
`analog_macro_top_run.py PROJECT --generate` runs those inputs in an installed
LibreLane environment. The native A18 adapter calls both automatically. An
external `analog_top.implementation_script` no longer substitutes for declared
connectivity. No Magic chip assembly is performed.

The generator reads these contracts without changing them:

- `phase1/generated_docs/L9_INTEGRATION_SPEC.json`: `top_module`, scalar `ports`,
  `macros`, `instances`, `pad_instances`, and optional `ties`.
- `input/submission_template/tapeout_declaration.json`: owner-readable DIE,
  absolute die/core rectangles, core `top_cell`, pad order/map, sites, rotations,
  corner, fillers and edge spacing, through the existing declaration reader.
- `phase1/generated_docs/L21_POWER_INTENT.json`: `fields.power_domains` entries
  with `power_net` and `ground_net`. Optional `power_rails` entries name a rail
  and its `kind` (`POWER` or `GROUND`). Every return rail requires a pad port.
  `hard_macro_supplies` binds each generated filler/corner PG pin using
  `{ "master": "...", "pin": "...", "rail": "..." }`.
- `input/analog_flow.json`: `analog_top.{pdk,pdk_root,scl,pad}` explicitly selects
  the native process/tool configuration. `stand_in: true` labels development
  material; it grants no acceptance.

Each L9 `macros` key is a master name. Its `gds`, `lef` and `spice` values select
nonempty file paths relative to the project (or absolute paths visible in both
execution environments). The LEF class, pin USE and SPICE `.subckt` pin population
must agree. SPICE instance arguments follow the source `.subckt` order.

Each L9 `instances` entry has this shape:

```json
{
  "name": "filter_a",
  "master": "filter_cell",
  "connections": {"IN": "sense", "OUT": "filtered", "P": "analog_supply", "G": "return"},
  "placement": {"location": [300, 400], "orientation": "N"}
}
```

Each `pad_instances` entry has `name`, `master`, a complete `connections` map and
`terminal` naming the external bond pin. Its terminal net must match the 0.5ic
`pad_signal_map`. Other pad terminals connect to core ports or declared rails.
Placement comes from 0.5ic pad order, not an inferred side. Shared pad libraries
are deduplicated into `PAD_LEFS`/`PAD_GDS`; analog macros use `MACROS`.

`ties` maps an output port to an explicitly declared supply/return net. Thus a
declared low tie connects the pad's core terminal directly to its return rail,
in both Verilog and SPICE, without synthesizing a tie cell.

A reference decap uses the same instance contract: two declarations of the
selected decap master, each with its own placement and TOP/return connections.
Its capacitance belongs in its supplied SPICE/GDS views. The generator neither
selects a value nor adds a buffer. Phase 1 owns L9 updates; do not patch generated
ADC declarations to work around missing Phase-1 inputs.

Outputs under `phase3/analog_top/` include `chip_top.v` (logical core and wrapper),
`chip_top.physical.v` (the equivalent flat native netlist), `chip_top.spice`,
`librelane.json`, `pdn.tcl`, and an analog SDC. The core name stays the declared
`top_cell`; the physical wrapper is `chip_top`. The existing pad-top record maps
these names for downstream backend/precheck readers.

Native execution runs floorplan, pad ring, manual macro placement, row cutting,
PDN, global/detail routing, disconnected-pin measurement and KLayout stream-out.
It preserves routed DEF/ODB, the routed Verilog and GDS at the usual PnR paths,
plus the native State and per-step logs. It performs no synthesis, standard-cell
placement, CTS or timing repair. Filler/corner supply connections remain explicit;
PDK-wide global patterns cannot merge independently declared rails.

Missing views refuse as `A18_MACRO_VIEW_ABSENT: MASTER: VIEW: PATH` before the
native run. Missing connectivity, returns, placement and auxiliary supply intent
also refuse by name. Nonzero native routing/PDN/disconnected-pin counts fail the
implementation receipt, retaining the actual outputs for diagnosis. Row 62
signoff and Flow109/delivery acceptance remain `NOT_MEASURED`; implementation
outputs do not replace D59/D64/D65/D66 or their normal prerequisites.
