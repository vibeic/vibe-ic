# Dispatch component engine inventory

This inventory describes the current source call graph, not qualification results.
Each use has its own engine-specific operation list and executable name. OpenSTA
inside OpenROAD is not a separate `sta` executable. Independent OpenSTA sessions
use the source-owned `opensta -> sta` alias. Icarus compilation and `vvp` execution
are separate identities. Python retained-result consumers do not claim to rerun
the original physical tool.

| Row | Current component engines | Source evidence |
| --- | --- | --- |
| D31 | Yosys, OpenROAD | `execution_backend_producers.produce_pnr`: JsonHeader plus floorplan/PDN chain; chip chain in `_prepare_librelane_floorplan_for_route` |
| D32 | Python | `produce_pnr` retained ring -> `step_pad_ring_gen`: assignment/generation/check/BTerm Python consumers; native pad ring belongs to D31 |
| D35 | OpenROAD | `produce_pnr` placement chain |
| D37 | OpenROAD | `produce_pnr` spare-cell state chain |
| D38 | OpenROAD | `_cts_split`: CTS + STAMidPNR |
| D39 | OpenROAD | `_cts_split`: post-CTS timing repair + STAMidPNR |
| D40 | OpenROAD | route/fill chain |
| D41 | OpenROAD | `step_postroute_repair_librelane`, RCX and STAPostPNR |
| D43 | OpenROAD | default `produce_signoff('26')` router antenna + prestream census; GDS antenna occurs in D60 |
| D47 | OpenROAD | `_librelane_rcx_publish` |
| D48 | OpenSTA (`sta`) | `_emit_si_crosstalk_report`, `si_mcf_sta.run` |
| D49 | OpenROAD | default `produce_signoff('23')` STAPostPNR; does not dispatch independent direct STA |
| D53 | Icarus, vvp | `sdf_gate_sim` compilation and simulation |
| D54 | OpenSTA (`sta`), Magic, ngspice | `path_spice_tool`: write_path_spice, `extract_cells`, current path correlation |
| D56 | Python | `_ppa.power.adopt_current_power_report`: validates retained STAPostPNR corners and publishes current power receipt; no new STA session |
| D57 | OpenROAD | `librelane_ir_antenna` IRDropReport + Vibeic.TransientIR |
| D58 | OpenROAD | `_emit_ir_em_reports`: PSM EM analysis |
| D59 | Python | `_emit_perc_equivalent`: report/DEF/PDK-IO evidence aggregation |
| D60 | OpenROAD, Magic, KLayout | `step_gds` stream/finishing and GDS antenna; see route note below |
| D61 | KLayout | `_die_finishing_native` -> `die_finishing_gen`; may reuse valid retained finishing |
| D64 | Python/pya and KLayout for digital ODB; KLayout for the retained other profile | `flow109_final_geometry.execute` consumes current D62 geometry and validates native FinishingXOR; retained non-digital profile uses `gds_xor_check` |
| D65 | Magic, KLayout, Netgen, OpenROAD | `step_drc`, `step_lvs`, `_native_erc.emit` (OpenROAD ERC) |

D60's current component has PDK/route-dependent stream-out. Its qualification
inventory is a conservative union of engines it may launch; it does not instruct
Default to execute multiple competing stream-out tools. Source-owned selection
of an exact route-specific qualification subset is unfinished. Missing qualifying
references still refuse admission. The KLayout Python-module execution mode also
needs a real runtime package identity implementation; a host executable hash
alone must not be presented as container/package qualification.

The 109 metric gates and new obligations are not established by this inventory.
No native reference was qualified by these source changes.

## Additional native adapters in this tranche

| Row | Component engines | Actual source owner |
| --- | --- | --- |
| A01 | Python | Existing analog specification emitter and current checker |
| D22 | Python/pyosys, Yosys, yosys-abc | Existing Default synthesis owner and canonical synthesis consumers |
| D44 | Yosys / LibreLane EQY | Final adopted-netlist equivalence component |
| D55 | Icarus, vvp, OpenSTA | Adopted-netlist GLS activity and per-port vector annotation |
| D62 | OpenROAD | Native ODB density fill, independent current ODB readback, `check_metal_density`, and OpenDB fill-obstruction overlap checker |

D64's digital component binds the interpreter, installed pya/native modules and
exact stream script separately from KLayout CLI XOR. This does not qualify every
D60 PDK-specific stream route or adopt final geometry for full-IC signoff.
The final-GDS field-solver reference is an independently measured helper; D69
remains without an admitted full-row extraction route.
