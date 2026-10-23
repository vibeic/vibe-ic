# 109-flow implementation entry

The existing general front door now accepts an explicit `--flow 109` selection.
`flow109.json` owns the stable responsibility IDs, four phases, seven stages,
Boolean selection, per-row Default tool profiles, source-bound old-70 mapping,
and the 277 metric specifications. `G1` through `G9` name the nine gate layers;
`L1` through `L27` remain specification documents. No old matrix result is
credited to the new rows or gate layers.

## Resolve a plan

Pass a JSON manifest containing an explicit `features` object. Every
non-derived feature must be Boolean; absent or unknown features are refused.
Derived features are computed from the registry and contradictory declarations
are refused. The registry includes reference profiles for implementation tests;
they are not evidence that a project's features have been independently checked.

```
python3 programs/vibe_ic_one_shot_runner.py PROJECT --route ic \
  --flow 109 --flow109-manifest INPUT_MANIFEST.json --flow109-plan-only
```

The result is `reports/flow109/plan.json` with `NOT_MEASURED` execution and
acceptance states. This operation does not invoke EDA or reinterpret old PASS
receipts. Source-owned public Python APIs are `resolve_plan`, `resolve_step`,
`resolve_execution_window`, `execution_context` and `validate_execution_context`
in `programs/flow109.py`.

## Execute an existing native component

The first tranche binds selected backend responsibilities to their real
existing producer and complete canonical consumer. For example:

```
python3 programs/vibe_ic_one_shot_runner.py PROJECT --route ic \
  --flow 109 --flow109-manifest INPUT_MANIFEST.json \
  --entry-step D38 --exit-step D38 --no-dashboard
```

This dispatches the existing Default CTS window with its original execution ID
and receipts. Qualification must succeed both at admission and at the actual
producer boundary. The manifest supplies `runtime_tool_uses` and a
project-relative `qualification_registry`; source-owned use IDs are returned by
`resolve_step`. The admission module owns the exact identity/evidence schema.
An unavailable admission implementation refuses before native dispatch.

The request is preserved under `reports/flow109/requests/`. It binds the
registry, planner, selected features/profile, responsibility, runtime tool
identities and qualification path. Child execution receives the explicit
`VIBEIC_FLOW109_CONTEXT` path. The source resolver revalidates this context;
ordinary 70-flow invocation clears an inherited 109 context.

Only a single explicit mapped component is dispatchable in this tranche.
The registry currently maps 28 rows: 22 existing backend components and the
A01, A04, A05, D44, D55 and D62 adapters described below. A dispatch mapping is
not a native test result or a completed row. The remaining 81 rows return
`FLOW109_PRODUCER_UNIMPLEMENTED`. Translating an entire
new span into an old span would silently execute a different dependency order,
so multi-row execution remains `FLOW109_WINDOW_UNIMPLEMENTED` until its actual
adapters are implemented. This boundary can be extended as implementation lands.

Native component PASS remains scoped to the existing consumer. The new metric
bindings, G1-G9 checks, full route acceptance and tool/profile qualifications
have independent statuses; this registry does not establish 109/109 PASS.

## A01 structured analog specification component

`--entry-step A01 --exit-step A01` calls the existing
`analog_a1_spec_emit.py` producer and `analog_a1_spec_extract_check.py` consumer.
It does not start topology generation, SPICE, PVT or layout. Use the declared
IC/IP endpoint and a nonempty structured analog block list with attributed L5
specifications. Existing unbound/human-owned specs are preserved, and do not
become fresh production merely because the old gate accepts their shape.

The Python tool use also requires `semantics.operation_sources`: the exact
portable path-to-SHA256 map returned by `flow109_analog.operation_sources()`.
That map binds the adapter, producer, consumer and existing transitive source
closure. Source changes invalidate this qualification scope before launch.
The adapter checks D03 admission again at each actual subprocess call and
binds consumed L1/L5/L9/block-list bytes, current outputs and actual gate JSONs.

Each attempt is preserved under `reports/flow109/attempts/A01-*/`; the latest
component view is `reports/flow109/components/A01.json`. A completed native
component returns CLI success with `component_status: PASS`. The two A01
`covers_all` obligations are then evaluated from the current emitted specs and
gates against their exact requirements-owner-approved registry refs. Missing,
stale, partial, defaulted or AI-owned authority remains `NOT_MEASURED`; a
measured miss is `FAIL`. `flow109_acceptance` remains `NOT_MEASURED` because
G1-G9 and whole-flow delivery are outside this row binding. Qualification
contract fixtures in developer tests are not production qualification records.

## A04/A05 source-authorized analog circuit components

A04 requires an approved circuit/topology and positive gain/noise/power budget
declaration, exact structured specs, typed model/corner scope, and a current
A02 receipt. It runs the existing topology emitter and retained reader, then
refuses any mismatch between the expert selection and emitted IR.

A05 requires current A02/A04 receipts and an approved per-device sizing plus
operating-point threshold declaration. It runs the existing netlist emitter
and retained reader, snapshots the emitted deck and complete self-contained
local model read set, and executes that snapshot with native ngspice. Exit zero
is insufficient: every required measurement must be finite and within its
source-owned bounds. See `docs/flow109/A04-analog-topology.md` and
`docs/flow109/A05-analog-netlist-sizing.md`.

Both are bounded component results. PVT/statistics, production-PDK signoff,
G1-G9, full Flow 109 qualification and benchmark PASS remain `NOT_MEASURED`.

## D44 final adopted-netlist equivalence component

`--entry-step D44 --exit-step D44` uses the installed LibreLane `Yosys.EQY`
step and the existing `librelane_eqy` recipe/partition consumer. A model/port
elaboration check rejects functionless/unknown instantiated cells. No second
full LEC or gate-level simulation substitutes for the actual EQY proof.

`input/flow109/D44.json` binds reference RTL, the final adopted netlist,
functional Liberty, explicit LibreLane PDK/library/root, and STA/LVS-reference/
release netlist sources. This tranche supports identical logical bytes and no
arbitrary power/physical-cell/port transformations. Its one supported physical
transformation is the source-owned, DEF-bound single-domain powered functional
view: the current producer restores the adopted supply connections and may
project only producer-declared supply ports proven inert or fixed at the
declared powered level. The regenerated views must have matching complete
functional interfaces and no surviving black/white box. Off-state, switched-
domain, isolation/retention, or general power-aware equivalence is not claimed.
Any other representation change is `NOT_MEASURED`, never a reason to drop cells
or ports. The native generic
PDK preprocessing branch uses Icarus; LibreLane's other formal-PDK helper
branch requires its own qualified tool use and is not silently substituted.

All per-use identities bind `flow109_final_lec.operation_sources()` in
`semantics.operation_sources`. The adapter checks admission again at actual
model/proof launch and retains exact native configurations, inputs, source
hashes and partition evidence. Every declared EQY partition must have a result;
unresolved/unknown or gold-X partitions cannot produce component PASS.

An immutable retained native EQY receipt may avoid repeating a completed proof,
but only when its pinned image, native configuration and fingerprint, cell
models, generated EQY script, proof-kernel sources, complete partition/status
population, RTL/adopted-netlist identities, and current regenerated physical
views all revalidate. Changed orchestration is not treated as proof-compatible
by assertion: the current producer must recreate byte-identical gold and gate
functional views. Missing or changed evidence refuses adoption.

A proven component publishes
`adopted/final_lec/sta_lvs_release_netlist_mapping.json` with the common logical
netlist source and proof identity. This prepares the downstream source chain;
it does not claim that STA, LVS, or release consumers have run/adopted it.
The D44 component also evaluates its two row-local runtime bindings. The
`final_lec_unproved` count is derived from the complete declared EQY partition
census (including counterexamples, undecided partitions, and gold-X partitions),
not from the component verdict. The `sta_lvs_release_netlist_mapping` binding
revalidates the current manifest, qualification/source closure, proof receipt,
and exact common netlist bytes for all three named roles. Missing or stale
evidence cannot pass. Its `consumer_adoption: NOT_MEASURED` explicitly means the
mapping is proven here but downstream STA/LVS execution is not.

The source-whitelisted runtime-metric consumer re-evaluates both bindings from
current evidence and applies the registry's typed `eq` and
`matches_adopted_reference` operators. Its row record sets `delivery_blocked`
for missing/stale or failing evidence, and only both current obligations may
produce row-metric `PASS`. The canonical single-component dispatcher still
returns the component verdict rather than this row record; changing that shared
policy is outside D44 registration. This does not convert a component result
into whole-flow acceptance:
`flow109_acceptance` and `baseline_adoption` remain `NOT_MEASURED`, downstream
production qualification is not inferred, and G1-G9 remain separately
unmeasured.

## D62 ODB metal-density fill component

Default execution preserves the existing native fill/readback checks. Missing
additional density/keepout audit documents do not prevent that native operation
or its engineering handoff. They leave metric acceptance `NOT_MEASURED` and
delivery blocked. Supplied documents must remain current and valid. The native
checkers run when their approved limits are available; missing limits never
become assumed passing density results.

`--entry-step D62 --exit-step D62` uses OpenROAD `density_fill` on the bound
input ODB, writes a new ODB in an immutable attempt directory, and opens it in
an independent native process. `input/flow109/D62.json` binds that input,
the qualified PDK/rules, and the fixed operation configuration. Admission is
checked at the native launch boundary. Non-fill geometry must remain unchanged,
previous fill cannot disappear, and the independent fill census must agree.

`flow109_density_fill.validate_filled_odb` verifies the current receipt and
output hashes before a downstream consumer can use them. The synthetic native
control proves fill persistence. The D62 runtime metric checker separately runs
OpenROAD `check_metal_density` over the current filled ODB using approved,
rules/PDK-bound per-layer limits and an approved core window/step. It also
counts actual intersections between `dbFill` rectangles and OpenDB
`isFillObstruction` rectangles. The receipt binds the three exact native argv
and read sets, checker sources, authority documents, ODB/DEF outputs, and tool
identity. An empty keepout set is measured only when the requirements owner has
explicitly validated its absence.

These are source-qualified D62 current-ODB measurements, not a foundry DFM deck
signoff. D63 still owns final-GDS DFM semantics; D62 does not reuse fill counts
as density or invent a zero keepout result. The fixture controls do not qualify
GF180 rules or establish that an extractor models floating-fill capacitance.
The handoff therefore keeps `extraction_fill_sensitivity: NOT_VERIFIED`. D69
must consume a common final ODB/GDS geometry identity and qualified extraction
evidence; an old pre-fill GDS or SPEF cannot satisfy that requirement.

This adapter does not adopt an old GDS-finishing result, update STA/LVS release
acceptance, or grant a 109-flow PASS. A D62 row PASS covers only its three
current metric obligations; downstream and whole-flow acceptance remain
separate.

## Measured final-extraction blocker

D69 remains unimplemented and cannot reuse a pre-fill SPEF as final evidence.
In EDA 0.4.29, OpenROAD `d4d1c6987aa8a1c4bdf99cf8166130549c981b03`
produced identical SPEF bytes (excluding DATE) before and after adding 41,549
explicit fills to the public Nangate45 RCX regression design. This is a
capability counterexample for that use, not GF180 qualification or a statement
about every extraction model. See `vibeic/vibeic-eda#333` for the pinned
reproducer and the required correlation/common-geometry evidence. A suitable
alternative extractor or authoritative correlated fill model can be evaluated;
a caller-authored qualification label cannot replace those measurements.

## D55 GLS activity and vector-power component

D55 runs the existing DUT-scoped activity producer with an adopted mapped
netlist, then consumes that actual VCD with native OpenSTA. All required scalar
top ports must be observed and VCD-annotated; nonzero vectorless power does not
prove annotation. Approved mode/window/load requirements and all consumed
inputs are bound. Only the self-contained single-rail scalar subset is
implemented. See `docs/flow109/D55-functional-activity.md` for its inputs and
retained producer/consumer evidence. This prepares activity evidence without
claiming final post-route power adoption or all D55 obligations.
