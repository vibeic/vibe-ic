# Findings — PPA machinery driven end to end on one real IC

Eighteen findings, every one reproduced by a shipped program on a real run tree.
Each names the exact call that produced it. Nothing here was worked around
silently; where this lane authored a bridge to get past a gap, the bridge is
named in the finding and shipped under `tools/`.

Tree under test: `land/ppa-tf` @ `bb90724dc` (v1.11.32).
Design: `spm` on `sky130A`. Run trees: `run/baseline` + `run/trials/t000..t059`.

---

## F-1 — no program emits the PnR search space, and the one that exists excludes it

`crosslayer_search_space.py` runs clean on this project and admits five levers.
It also publishes eight it deliberately withholds:

```
$ python3 programs/crosslayer_search_space.py <project> --json space_raw.json
[crosslayer_search_space] admitted 5 lever(s): arithmetic_architecture,
  module_hierarchy, pipelining, state_encoding, synthesis_strategy
pnr_levers_excluded_on_purpose:
  core_utilisation, core_aspect_ratio, cell_padding, placement_density,
  cts_cluster_size, cts_cluster_diameter, routing_layer_adjust, clock_period
pnr_exclusion_reason: "these are the place-and-route knobs the PnR-only search
  already owns"
```

**Measured: there is no PnR-only search.** No program under `programs/` emits a
space containing those eight levers. And of the five that ARE admitted, four
require authoring different RTL; the fifth, `synthesis_strategy`, is not exposed
by `phase3_one_shot_runner.py`'s CLI at all.

So a downloaded plugin that wants to search the knobs its own runner exposes
(`--util`, `--die-um`, `--spare-density`) has no space document to feed
`ppa_search_run.py`. This lane authored one: `search/space.json`, in
`crosslayer_search_space.py`'s output shape, every lever citing the CLI flag
that applies it.

## F-2 — `ppa_metric_extract --backend` drives no backend, including the ones that exist

```
$ python3 programs/ppa_metric_extract.py --backend openroad
[CANNOT CHECK] backend `openroad` exists but ppa_metric_extract does not drive
backends yet; the domain lane that owns it does. rc=2.
```

rc=2 with a marker, which is correct behaviour for an unimplemented path. But it
means the canonical extraction CLI cannot extract from any tool. Of the five
backend modules, only `_ppa/backends/openroad.py` ships a `main()`;
`opensta.py`, `yosys.py`, `librelane.py` and `orfs.py` are library-only. Power
has no CLI at all. This lane wrote `tools/extract_run.py` to call the shipped
library functions directly.

## F-3 — seven of the nine feasibility axes have no producer anywhere in `programs/`

`_ppa/feasibility.py` proves nine axes from nine canonical metric names. Grep for
each name across `programs/`, excluding tests:

| axis metric | produced by |
|---|---|
| `physical.drc.violations` | nothing but `_ppa/feasibility.py` itself |
| `physical.lvs.verdict` | nothing but `_ppa/feasibility.py` itself |
| `physical.antenna.violations` | nothing but `_ppa/feasibility.py` itself |
| `power.ir.violations` | nothing but `_ppa/feasibility.py` itself |
| `reliability.em.violations` | nothing but `_ppa/feasibility.py` itself |
| `equivalence.verdict` | nothing but `_ppa/feasibility.py` itself |
| `timing.drv.max_tran_violations` | nothing but `_ppa/feasibility.py` itself |
| `timing.setup.wns_ns` | `_ppa/timing.py` — MEASURED on ONE view (see F-6) |
| `timing.hold.wns_ns` | `_ppa/timing.py` — NOT_MEASURED on every view (F-15) |

The run tree measures all nine. DRC 0 items over 145 registered categories, LVS
`circuits match uniquely`, antenna 0/0, static IR 0.024% of VDD against a 10%
budget, EM over 2431 segments, LEC PROVEN. **None of it is in canonical record
form, so the PPA feasibility gate can read none of it.**

Driven with the shipped extractors only:

```
$ python3 programs/ppa_feasibility_check.py --candidates feasibility_shipped_only.json
[CANNOT CHECK] at least one candidate was not adjudicated; this run makes no claim about it
baseline: UNDETERMINED
  setup FEAS_NOT_MEASURED,FEAS_INCOMPLETE_VIEW_SET,FEAS_METRIC_ABSENT
  hold  FEAS_NOT_MEASURED,FEAS_INCOMPLETE_VIEW_SET,FEAS_METRIC_ABSENT
  drv drc lvs antenna ir em equivalence:  FEAS_METRIC_ABSENT
rc=2
```

Seven axes: the metric is absent entirely. This is the machinery being HONEST —
`rc=2` is exactly right and it is never mapped to PASS. But it means **no run of
this flow can produce a feasible candidate**, and "both sides feasible" is one of
the four conditions a head-to-head requires.

Bridge authored for this lane: `tools/signoff_records.py`. It reads the run's own
sign-off artefacts and emits canonical records with real provenance, applying the
`fixtures/ppa/drc/zero_three_ways/` discriminator to DRC rather than trusting a
bare zero. With it, `drc`, `lvs`, `antenna` and `ir` become SATISFIED. The other
five stay UNDETERMINED for the reasons in F-6, F-15, F-16 and F-17 — every one a
real gap in the flow's evidence, not an omission in the bridge.

## F-4 — the three shipped record producers emit envelopes the canonical consumer refuses

```
$ python3 programs/ppa_metric_extract.py --records openroad.json timing.json \
      power.json --out bundle.json
[CANNOT CHECK] openroad.json: UNRECOGNISED_DOCUMENT: not a metric record, a list
  of records, or a vibeic.ppa.metric_bundle.v1 bundle.
[CANNOT CHECK] timing.json:   UNRECOGNISED_DOCUMENT: ...
[CANNOT CHECK] power.json:    UNRECOGNISED_DOCUMENT: ...
ppa_metric_extract: 3 document(s) named, 0 read, 3 unreadable, 0 record(s) indexed
rc=2
```

`_ppa/metrics.records_from_document` accepts exactly three shapes: one record, a
bare list, or a `vibeic.ppa.metric_bundle.v1` envelope. The producers write:

| producer | envelope | records live under |
|---|---|---|
| `_ppa/backends/openroad.py --json` | `vibeic.ppa.backend_records.v1` | `records` |
| `_ppa/timing.py --json` | `vibeic.ppa.timing_rows.v1` | `rows` |
| `_ppa/power.py power_document()` | `vibeic.ppa.power.v1` | `metrics` |

All three carry genuine `vibeic.ppa.metric.v1` records inside. None is readable
by the canonical consumer. `tools/adapt_records.py` re-wraps them into the bare
list the consumer already accepts; no value is altered.

**Secondary:** with every input unreadable the program still writes an
`--out` file containing `{"records": []}`. The exit code is honest (rc=2), but a
downstream reader that opens the file and not the exit code sees a clean empty
bundle.

## F-5 — the area lane's declared unit and the metrics lane's required unit disagree

`_ppa/area.py:175` declares the canonical unit of `area.proxy.cell_count` as
`"cells"`. `_ppa/metrics.py`'s `_UNIT_SUFFIXES` maps the `_count` name suffix to
`"count"`. Every yosys proxy-area record is therefore refused by the canonical
index:

```
[REFUSE] #142 'area.proxy.cell_count': UNIT_CONTRADICTS_NAME: metric
  'area.proxy.cell_count' names unit 'count' but the record says 'cells'.
```

Six records per run (`cell_count`, `wire_count`, `wire_bit_count` × two stat
blocks). Two files in one lane, shipped in one branch, holding opposite rules.

## F-6 — the multi-corner sign-off STA reports carry no `STA_BASIS` stamp, so sign-off timing cannot be staged

`_ppa/timing.py::_stage_for` predicts this precisely in its own docstring, and it
is true on a real run:

```
sta_spef_based.rpt         ->  STA_BASIS: POST_ROUTE_SPEF
sta_mcorner_ocv.rpt        ->  <NO STAMP>
sta_spef_multicorner.rpt   ->  <NO STAMP>
```

The stamped report is the SINGLE-corner one. The two MULTI-corner sign-off
reports — the evidence that decides setup at the slow corner and hold at the fast
one — carry nothing, so their rows get `scope.stage = null` with the gap reason
`"report carries no STA_BASIS stamp"`. 48 of 56 timing rows are then refused by
the canonical index as `SCOPE_INCOMPLETE`, and they cover no `required_view`
containing `stage`, so setup and hold are `FEAS_INCOMPLETE_VIEW_SET`.

**This one finding is the root cause of most of the timing half of F-3.** The fix
is three `puts` in `phase3_one_shot_runner.py`'s multi-corner emitters.

> **SATISFIED by `e4c5840d6` (v1.11.57, 2026-08-21).** The three `puts` landed,
> with the guard `tests/test_multicorner_signoff_reports_declare_their_stage.py`.
> `_emit_spef_sta`, `_emit_corner_spef_sta` and `_emit_mcorner_ocv_sta` each
> write a `STA_BASIS:` line now, and `_ppa/timing` resolves the stamp according
> to what that stanza actually read: `PRE_LAYOUT_ESTIMATE` ->
> `pre_layout_estimate` for RC pre-layout and for OCV pre-layout;
> `POST_ROUTE_NO_SPEF` ->
> `post_route_no_extraction` for routed OCV without SPEF; and
> `POST_ROUTE_SPEF` -> `post_route_extracted` for routed OCV with SPEF. The
> finding above is left as written because it was true of the run it describes,
> whose tree is gone; it is a record, not a live request. **A run tree produced
> BEFORE 2026-08-21 still shows exactly this
> — measured 2026-08-22, the run trees on one host split on that date: those
> whose `sta_*` reports carry the stamp refuse 0 `SCOPE_INCOMPLETE`, those whose
> reports predate it refuse 48 each.** Re-running the flow is what clears an old
> tree; no producer change can.

## F-7 — the Phase-3 power report is computed on the PRE-PnR netlist and says it is not

> **SATISFIED by `e4c5840d6` (v1.11.57, 2026-08-21).** The session links the
> routed netlist and reads the extracted parasitics when they exist; when they
> do not it degrades LOUDLY, and the `POWER_BASIS` stamp, the note and the
> provenance envelope all name what was actually linked. Left as written, for
> the same reason as F-6.

`reports/phase3/power.rpt` states, in its own generated header:

> *Substance: ... Numerical leakage / switching / internal values reflect the
> post-PnR netlist + the typical-corner Liberty file.*

The session that produced it:

```
$ grep -E 'read_verilog|read_spef' reports/phase3/power_spm.tcl
read_verilog <project>/phase2/stage2/synth/spm_synth.v
(no read_spef)
```

| | shipped `reports/phase3/power.rpt` | post-route diagnostic |
|---|---|---|
| netlist | `spm_synth.v` — **287** std-cell instances, pre-PnR | `spm_pnr.v` — **3373**, routed |
| parasitics | none | `phase3/stage3/extracted/spm.spef` |
| activity basis | VECTORLESS (`vectorless_sdc`) | VECTORLESS (`vectorless_sdc`) |
| **total power** | **0.306 mW** | **0.573 mW** |
| **clock group** | **0.000 mW (0.0 %)** | **0.193 mW (33.7 %)** |
| switching | 0.0179 mW | 0.251 mW |

The shipped figure is **1.873×** low — it understates total power by **46.6 %** —
and the clock tree, a third of real power, reports as exactly **zero**, because
the netlist the session links has no clock tree in it. The design that was routed
is also the post-DFT netlist; the power session never sees the scan cells either.

Same tool, same liberty, same SDC, same activity basis in both columns. The
diagnostic is `diag/power_postroute.tcl` + `diag/power_postroute.rpt`, authored
by this lane and labelled as such; it is not a flow artefact.

**Consequence for the search:** the power axis is invariant under every PnR knob,
because it is measured before PnR. This is confirmed by the sweep — see
`RESULT.md`, "what the search actually moved".

`tools/extract_run.py` therefore DERIVES the power stage from the session's own
declared inputs rather than from the directory the report was filed in, and
labels it `synth`.

## F-8 — power records cannot satisfy the power axis's own `REQUIRED_SCOPE`

`_ppa/benchmark.py` requires, for the `power_mw` axis:

```python
REQUIRED_SCOPE["power_mw"] = ("stage", "mode", "process", "voltage_v",
                              "temperature_c", "activity_basis")
```

`_ppa/power.py` emits `stage`, `activity_basis`, `group`, `liberty`, `scenario`
and `tool`. **`mode`, `process`, `voltage_v` and `temperature_c` are never
emitted**, so a head-to-head over shipped power records refuses with
`SCOPE_INCOMPLETE` before it can compare anything.

The PVT is recoverable from a value the record already carries. `_ppa/power.py`
puts the liberty FILE NAME in scope, and the same lane ships the parser:

```python
>>> opensta.parse_liberty_pvt('sky130_fd_sc_hd__tt_025C_1v80.lib')
LibertyPVT(process='tt', voltage_v=1.8, temperature_c=25.0, gaps={})
```

`power.py` does not call it. This lane supplies the PVT through `power.py`'s own
`extra_scope` hook, using that shipped parser; `mode` comes from the design's
`pvt_matrix.json` and only when it declares exactly one.

## F-9 — the OpenROAD backend emits two readings of one metric under one scope

`_ppa/backends/openroad.py --run-dir` parses both `openroad.log` and
`openroad.metrics.json` and emits both under an identical scope:

```
route.wirelength.um   16511.0   scope={"stage":"detailed_route","tool":"openroad"}   <- openroad.log
route.wirelength.um   16522     scope={"stage":"detailed_route","tool":"openroad"}   <- openroad.metrics.json
route.via.count        4151     (same scope)                                          <- openroad.log
route.via.count        4159     (same scope)                                          <- openroad.metrics.json
```

Both consumers refuse, correctly and with different codes:

```
_ppa/metrics MetricIndex : CONFLICTING_RECORD  "Two numbers claiming to be the
                           same fact is a conflict"
ppa_report_gen.py        : [REFUSE] CLAIM_ID_COLLISION -> rc=1
```

The scope carries no key naming the artefact each number came from. `rc=1` from
`ppa_report_gen` means **no report can be generated from a default run at all**.
`tools/adapt_records.py` puts the source artefact into the scope, uniformly for
every record of that envelope — never only where it changes an outcome.

## F-10 — every timing row is emitted twice, from byte-identical files

`_ppa/timing.py::_STA_DIRS` reads `phase3/stage3/sta`, `reports/phase3/sta` and
`reports/phase3`. The runner publishes each STA report into two of them:

```
sha256(phase3/stage3/sta/sta_spef_based.rpt) == sha256(reports/phase3/sta_spef_based.rpt)
sha256(phase3/stage3/sta/sta_mcorner_ocv.rpt) == sha256(reports/phase3/sta_mcorner_ocv.rpt)
sha256(phase3/stage3/sta/sta_spef_multicorner.rpt) == sha256(reports/phase3/sta_spef_multicorner.rpt)
```

Result: **all 20 (metric, scope) groups in the timing document collide**, every
one refused as `CONFLICTING_RECORD`. The record already carries `source.sha256`,
so the extractor has everything it needs to collapse the duplicate.

**F-10b, a second and different collision:** `timing.*.worst_path_slack_ns` is
emitted once per REPORTED PATH under one scope — three values (5.20, 5.32, 5.36
ns) for one view — and the scope says nothing about which path. A metric named
"worst path slack" with three values in one view is ambiguous on its face.

## F-11 — `required_views` is global, so a NOT_MEASURED row on any view poisons the axis

`_evaluate_proof` matches every proof against one global `required_views` list.
Measured on the baseline, with the bridge in place:

| declared views | setup | hold |
|---|---|---|
| `[{stage,process:ss},{stage,process:ff}]` | UNDETERMINED (ff uncovered) | UNDETERMINED |
| `[{stage,process:ss}]` | **SATISFIED** | UNDETERMINED (ss uncovered) |
| `[{process:ss},{process:ff}]` (no stage) | UNDETERMINED | UNDETERMINED |

The third row is the instructive one: dropping `stage` lets the view match the
UNSTAMPED rows too (F-6), where `timing.setup.wns_ns` is NOT_MEASURED, and one
NOT_MEASURED record covering a required view makes the axis UNDETERMINED even
though another record measures it. There is no declaration that makes setup and
hold both provable on a default run of this flow.

## F-12 — `ppa_search_run.py` hard-wires the feasibility STUB, and the stub's stated reason is false

```python
programs/ppa_search_run.py:243
    ledger.evaluate_feasibility(None)  # the stub: UNDETERMINED, never ELIGIBLE
```

`Ledger.evaluate_feasibility` accepts an injected `FeasibilityFn`. The CLI has no
flag to supply one, so **every manifest a downloaded plugin can produce marks
every candidate UNDETERMINED and publishes an empty Pareto frontier**:

```
frontier included: 0
excluded x60:  FEASIBILITY_UNDETERMINED (31) / DID_NOT_RUN (29)
toolchain.feasibility_source: "STUB"
toolchain.feasibility_note: "feasibility lane not wired: _ppa/feasibility.py has
                             not landed, so no setup/hold/DRV/DRC/LVS/antenna/
                             IR/EM/equivalence evidence was read"
```

`_ppa/feasibility.py` landed at v1.11.26; `ppa_search_run.py` landed at v1.11.29,
three commits later. The note is published verbatim into every manifest and it is
untrue on this tree.

## F-13 — the contract has no rule for which artefacts belong to `analysis`, and the natural choice refuses every comparison

`docs/PPA_INTERFACES.md` §4 names five identities. It does not say which
artefacts populate `analysis`. Declaring the STA / DRC / LVS reports there — the
obvious reading of "analysis artefacts" — gives:

```
$ python3 programs/ppa_problem_integrity_check.py --baseline b/contract.json \
      --candidate t001/contract.json --require-implementation-differs
[FAIL] PPA-C-012: the analysis identity DIFFERS between the two arms ...
  artefact sta_signoff_multicorner (sha256:1f2a4a6… -> sha256:3424689…)
  artefact lvs, artefact drc_vacuity, artefact sta_signoff_ocv, ...
rc=1
```

Of course they differ — they are outputs of the implementation. The rule that
makes the contract work is implicit and unstated: **an artefact that varies with
the implementation may not sit in `analysis`.** With the reports moved to
`implementation` and `analysis` holding the measurement CONFIGURATION only:

```
[PASS] ppa_problem_integrity_check: 0 finding(s)
  problem, analysis and toolchain identities MATCH and the implementation
  identity differs — these two runs are comparable.
rc=0
```

## F-14 — the runner writes absolute host paths into the analysis scripts it emits

`reports/phase3/power_spm.tcl` is the analysis configuration for the power axis
and belongs in that identity. It contains:

```tcl
read_verilog /home/reyerchu/_jppae2e/run/trials/t001/phase2/stage2/synth/spm_synth.v
```

so two runs of an identical measurement configuration hash differently and
PPA-C-012 refuses. Any hash-based identity over an emitted script is defeated by
the run directory. This lane left the script out of the identity and said so
rather than dropping it silently.

## F-15 — no STA artefact prints a hold `wns`, so the hold axis can never be satisfied

`_ppa/feasibility.py` proves hold from `timing.hold.wns_ns` or
`timing.hold.violations`. The reports print `worst slack min`, which
`_ppa/timing.py` emits as `timing.hold.worst_slack_ns` — a name the hold axis
does not prove from. Across all six STA artefacts of a baseline run,
`timing.hold.wns_ns` is `NOT_MEASURED` on every view, with the reason
`"the artefact carries no wns line for this view"`. The hold axis is structurally
unprovable from this flow's evidence.

## F-16 — post-layout LEC fails, so `equivalence` is about a pre-layout netlist

`reports/lec.json` proves RTL against `post_dft_netlist.v (synth)` — a PRE-layout
netlist. The routed netlist that became the GDS is not the gate side of that
proof. The run's own post-layout LEC step reports:

```
FAIL canonicalize_artefacts: post-layout LEC FAILED (verdict=RUN_ERROR):
     LEC_POST_RUN_ERROR: yosys did not produce a parseable output
```

so `equivalence.verdict` at `post_route_extracted` is `NOT_MEASURED` with that
reason, not `PROVEN`. This is also one of the two steps that make the default
run's overall verdict FAIL.

## F-17 — the EM report supports no violation count

`reports/phase3/em.json` carries `segments_analysed: 2431` and
`max_segment_current_A: 0.0001951`, and **no violation count and no declared
current limit**. `reliability.em.violations` is therefore `NOT_MEASURED` with
that reason. "The tool reported no violations" is not what this artefact says,
and a zero here would be exactly the vacuous pass the fixture tree exists to
prevent.

## F-18 — `derive_feasibility` requires an integer count on every floor check, and LVS is not a count

`_ppa/benchmark.derive_feasibility` walks `FEASIBILITY_FLOOR = ('drc', 'lvs',
'antenna', 'setup', 'hold', 'drv')` and, for each, requires
`checks[name]["violations"]` to be a non-negative `int`. A check declaring
`{"status": "CLEAN"}` and nothing else is counted as **NOT_CHECKED**:

```python
n = c.get("violations")
if isinstance(n, bool) or not isinstance(n, int) or n < 0:
    unchecked.append(name)
```

The `comparison.v2` schema, however, documents `status` as a first-class
alternative to `violations` on a check, with the enum `CLEAN / VIOLATIONS /
NOT_CHECKED`. So a record that is valid against the schema and says `CLEAN` on
every axis derives as `NOT_CHECKED`, and the arm is refused.

**LVS makes this concrete.** LVS produces a VERDICT — `circuits match uniquely` —
not a violation count. The only way to express an LVS-clean arm to
`derive_feasibility` is `violations: 0`, which the schema permits but nothing
states, and which is a slightly odd thing to write about a verdict. Measured
here: with `status: CLEAN` alone, the head-to-head refused naming
`['antenna', 'drc', 'drv', 'hold', 'lvs', 'setup']`; with `violations: 0` added
for the three physical checks, the same record refused naming only
`['drv', 'hold', 'setup']` — which is the accurate answer.

---

## Two smaller things, recorded because they cost time

**`jsonschema` is not a declared dependency.** Without it,
`ppa_contract_check.py` returns rc=2 on every contract with
`PPA-C-010: jsonschema is not importable here, so the contract's shape was NOT
validated. This is not the schema passing`. The refusal is correct and well
worded; the dependency is simply not declared or bundled, so a downloaded plugin
on a stock `python3` gets rc=2 on every contract it builds.

**A relative `--json` path plants a file in the shipped tree.**
`_ppa/backends/openroad.py --json records/x.json` invoked with `cwd=programs/`
writes `programs/records/x.json` into the shipped plugin tree. Self-inflicted
here and cleaned up, but it is the same hazard the repo has hit before, and the
atomic-artefact writer does not guard against it.
