# Native post-map mapped-product handoff

This is an opt-in implementation transform, not a timing waiver or a new
signoff gate. In `phase3/librelane_switch.json`, set
`"post_map_repair": "pre_placement"` while Step9 selects `librelane`.
Absent or `"off"` retains the existing Yosys-only product. Invalid values,
a requested transform without a child, and an existing child with the mode
removed are refused. The direct synthesis route does not implement this mode.

Step9 first completes every existing Yosys synthesis, native check, constant,
PDK, provenance, area and handoff check. It retains the original native Yosys
netlist, statistics, log and receipt. It then reuses the ordinary Step7 SDC
producer and LibreLane PDK resolver. `Vibeic.PostMapRepair` consumes that parent
netlist, active SDC, declared exclusions/dont-touch constraints and native
corner set. It invokes OpenROAD `repair_design -pre_placement` with no
floorplan, placement, parasitics, timing exceptions, or clock-period change.
The operation may replace existing masters as well as insert buffers.

The plugin step runs through existing `librelane_contract.run_chain`:
image, config, state/input files, PDK mounts, plugin source and output hashes
are retained by its ordinary native receipt. The exact OpenROAD COMMANDS,
statistics script and transcript are bound too. A read/stat-only native Yosys
invocation recomputes the output cell census and area; it performs no synthesis
or ABC mapping. The existing statistics corroborator and area consumer read
those output measurements, not the retained parent statistics. A missing area
authority remains INCOMPLETE/NOT_MEASURED. Unsupported macro/multiple-library
statistics contexts refuse rather than infer a unit or area.

`synth_inputs.json.librelane_synthesis` retains its Yosys parent `folder` and
`receipt_sha256`, while `netlist_sha256` names the selected output. Optional
`post_map` has schema `vibeic.postmap-handoff.v1` and fields:

- `folder`, `resolved_config`, `state_in`: project-relative native child inputs.
- `parent_sha256`, `netlist_sha256`, `receipt_sha256`, `stats_sha256`.
- `basis`: exact current staged SDC and L8/L9/L19 JSON file census and hashes.

The native child is validated before publication. Statistics are staged;
canonical mapped/netlist copies are written only after their existing consumers
have accepted the candidate. The sidecar's child binding is committed last.
Any interrupted/mixed publication is rejected by the same handoff reader;
there is no fallback to the parent while the transform is requested.

`synth_handoff_netlist_check.bound_handoff` validates both retained producer
closures, current native input/corner/PDK/config/code, actual selected constant
connections, and independent native-stat/published-stat agreement. It returns
`native` (child), `parent`, `mapped` and `canonical`. Existing Step14, Step10,
PnR and LEC use that selected mapped product. The native-copy reader selects
the child rather than comparing against the Yosys parent. Backend checkpoint
preparation carries the exact child receipt/output/input closure as well as the
retained parent, including original namespace path mapping after relocation.

This structural producer receipt does not establish equivalence or timing.
The ordinary LEC producer must prove the selected mapped product against RTL;
Step10 must independently time it at its normal corners and thresholds. A
successful native repair command, lower fanout, or one positive corner cannot
advance a still-negative canonical timing gate. Power, physical core geometry,
placement, routing and post-route timing are outside this transform's scope.
