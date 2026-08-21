# The PPA flow, driven end to end on one real IC

Tree under test: `land/ppa-tf` @ `bb90724dc` (v1.11.32), **unmodified**.
Design: `spm` (serial-parallel modulo-2^size multiplier) on **`sky130A`**.
Sibling documents: [`FINDINGS.md`](FINDINGS.md) (18 findings) ·
[`METHOD.md`](METHOD.md) (environment, pipeline, reproduction).

---

## The short version

The machinery runs. Every gate this lane drove behaved correctly, several of them
refused things that deserved refusing, and not one of them produced a false PASS.

It also does not yet join up. Driven exactly as a downloaded plugin would drive
it, on a design that reaches a routed, DRC-clean, LVS-matching GDS with all STA
corners MET, **the shipped PPA feasibility gate returns `UNDETERMINED` on 9 of 9
axes, 7 of them because the metric it proves from is produced by nothing in
`programs/`.** No candidate can be feasible, so the head-to-head's "both sides
feasible" condition cannot be satisfied by any run of this flow today.

And one number is wrong in a way that matters: **the Phase-3 power report is
computed on the pre-place-and-route netlist while its own header says it is
post-PnR.** It is 1.873× low, and the clock tree — a third of real power —
reports as exactly zero.

Both are fixable, both are small, and both are named with the line that causes
them in `FINDINGS.md`.

---

## 1. The IC, and what was rejected

**Chosen: `spm`** — a serial-parallel modulo-2^size integer multiplier,
`size=32`, a carry-save accumulator array with a replicated serial-operand
broadcast register bank. 287 std-cell instances after synthesis, 488 after scan
insertion, 3373 placed after buffering, filler, taps and spares.

Chosen for **flow completeness, not impressiveness**. It is the smallest design
available here that actually reaches every stage the PPA machinery needs:

| | |
|---|---|
| routed GDS | yes — `phase3/stage4/gds/spm.gds` |
| sign-off DRC | yes — KLayout, PDK deck, 145 rule categories registered |
| LVS | yes — netgen, power-aware gate netlist, circuits match uniquely |
| multi-corner STA | yes — ss / tt / ff, with extracted SPEF |
| power report | yes — but see F-7 |
| **wall time** | **247 s median**, which is what makes a 60-point search affordable |

**Rejected — `sha256` on `sky130A`**: 9764 synthesised instances, ~34× `spm`.
A 60-point sweep would not have fit the window, and nothing about the PPA
machinery is exercised better by a larger design.

**Rejected — `subservient`**: 1023 instances, a SERV-based SoC. Its converged
runs on this host are on a different open PDK, and its PnR is dominated by
memory-macro handling — which would have made the search measure macro placement
rather than the PPA contract.

**The PDK was not chosen — it was arrived at by being refused twice.** The design's
own Phase-1 record declares `pdk_target: "sky130"`, and the runner refused both a
contradicting explicit PDK and a silent open-source fallback. Both refusals were
correct. Details in `METHOD.md`.

---

## 2. The default-run baseline — the number a downloaded plugin gives

`phase3_one_shot_runner.py <project> --top-name spm --pdk sky130A --die-um auto
--util 0.30 --spare-density 0.02` — every knob at its shipped default.

**Sign-off, from the tools' own output:**

| gate | result |
|---|---|
| sign-off DRC | **0 items** over **145 registered rule categories**, layout **20336 measured shapes** |
| DRC vacuity discriminator | `drc_vacuous_pass_check`: PASS — the zero is EARNED, not empty-layout, not deck-never-ran |
| LVS | `circuits match uniquely` under a power-aware gate netlist (3373 instances PG-patched) |
| antenna | net 0, pin 0, routing complete |
| STA | all analysed sign-off corners MET, governing worst slack **+0.570 ns** against a 10.0 ns target |
| static IR | worst **0.024 % of VDD** against a declared 10 % budget |
| EM | 2431 segments analysed, max segment current 0.1951 mA |
| LEC | RTL ≡ post-DFT netlist, 64/64 points PROVEN |
| spare ECO cells | 10 inserted, evenly distributed |

**The overall runner verdict is nevertheless `FAIL`,** and it should be reported
that way rather than summarised around:

```
FAIL  canonicalize_artefacts: post-layout LEC FAILED (verdict=RUN_ERROR):
      LEC_POST_RUN_ERROR: yosys did not produce a parseable output
ENV_UNAVAILABLE  digital_hardmacro_gen [SKIPPED_NO_CAPABILITY]
```

Neither is a PPA measurement, but the first one is why `equivalence` can never be
proven at post-route (F-16). `5 of 5 declared sign-off gates PASSED`; the flow
does not let that stand in for the whole.

**Canonical records extracted through the machinery** (not by reading logs):
131 records — **112 MEASURED, 9 INVALID, 8 NOT_MEASURED, 2 DERIVED**, zero
numeric sentinels, every NOT_MEASURED row carrying a reason instead of a value.

---

## 3. The search — 60 configurations, all 60 published

**The design declares no PPA objective.** `L19_CONSTRAINTS_PDK.json` carries
`die_area_budget_um: null` and `power_budget_uw: null`. So the objective is
declared *by this run*, in writing, in `search/winner.json` and here:

> **minimise `area.design_report.um2` at `scope.stage = post_route`**
> (OpenROAD `report_design_area`, status MEASURED), subject to the hard
> feasibility gate. Power and timing are published alongside it and never
> collapsed into it.

`area.die.um2` — the figure a reader is likeliest to think "area" means — is
**`DERIVED`** (the backend multiplies the floorplan bounding box), and
`COMPARABLE_STATUS` is `MEASURED` only, so it is published but cannot be the
objective.

**Space** (`search/space.json`, hand-authored — see F-1): three levers, every one
citing the shipped CLI flag that applies it.

| lever | values | applied by |
|---|---|---|
| `placement_density` | 0.30, 0.20, 0.40, 0.50, 0.60 | `--util` |
| `die_um` | auto, 210x210, 240x240, 280x280 | `--die-um` |
| `spare_cell_density` | 0.02, 0.00, 0.05 | `--spare-density` |

5 × 4 × 3 = **60 points**. The first value on every axis is the shipped default,
so `_ppa.search.propose` puts the **baseline configuration first** — the search's
reference point is the default run, not a lucky draw.

**Budget, declared as an input:** `max_trials=60`, `max_full_pnr_trials=60`,
`max_cpu_hours=24`, `max_wall_seconds=14400`, `concurrency=8`,
`memory_limit_mb=16384`, `per_trial_timeout_s=3600`,
`failed_trial_policy=COUNTS_AGAINST_BUDGET`, `seed=1121`, `cache_policy=IGNORE`.

**What the budget bought,** in the manifest's own words:

> budget 60 trial(s) / 60 full-PnR: proposed 60, ran 60 (0 from cache, charged 60), of which 60 reached full place-and-route; 5.5460 CPU-hours, wall time not reconstructible at concurrency 8; 0 candidate(s) are comparable at scope 'post_route_extracted'.

| | min | median | max | total |
|---|---|---|---|---|
| wall s | 190 | 247 | 399 | 4.29 h |
| CPU s | 222 | 317 | 627 | 5.546 h |
| peak RSS MB | 599 | 626 | 1087 | — |

Every CPU and RSS figure is that trial's own cgroup, from its own container.

**All 60 candidate records are in `search/manifest.json`**, and every trial's full
canonical record set is in `records/trials/tNNN/`. Nothing is published
winner-only.

### What the search actually moved

`area.design_report.um2` took **59 distinct values across
60 trials**, from **6136** to **7393 µm²** — a
**20.5 %** spread. The levers behave like physics:

**`die_um`** (mean objective, µm²)

| value | n | mean | min | max |
|---|---|---|---|---|
| `210x210` | 15 | 6607.0 | 6411.0 | 6847.0 |
| `240x240` | 15 | 6765.1 | 6560.0 | 6993.0 |
| `280x280` | 15 | 7151.5 | 6969.0 | 7393.0 |
| `auto` | 15 | 6495.7 | 6136.0 | 6994.0 |

**`placement_density`**

| value | n | mean | min | max |
|---|---|---|---|---|
| `0.20` | 12 | 6901.7 | 6545.0 | 7393.0 |
| `0.30` | 12 | 6782.7 | 6454.0 | 7294.0 |
| `0.40` | 12 | 6713.9 | 6267.0 | 7263.0 |
| `0.50` | 12 | 6679.5 | 6160.0 | 7307.0 |
| `0.60` | 12 | 6696.2 | 6136.0 | 7291.0 |

**`spare_cell_density`**

| value | n | mean | min | max |
|---|---|---|---|---|
| `0.00` | 20 | 6611.5 | 6136.0 | 7082.0 |
| `0.02` | 20 | 6735.8 | 6291.0 | 7223.0 |
| `0.05` | 20 | 6917.1 | 6462.0 | 7393.0 |

A bigger die costs area, monotonically, because distance has to be buffered.
Spare ECO cells cost area directly and monotonically, which is what they are for.
Placement density improves the objective monotonically from 0.20 to 0.50 and then
**flattens and very slightly reverses** at 0.60 (mean 6679.5 vs
6696.2 µm²) — the last increment
buys nothing on average, and it is the density at which the run's only
DRC-dirty trial appears (`t033`, on the largest die).

### And what it did not move

**`power.total_w` is `0.000306 W` in
60 of 60 trials — identical to the last digit,** across every
combination of die size, placement density and spare density. That is not a
coincidence and not stability: it is F-7. The power number is computed on the
pre-PnR synthesis netlist, so no place-and-route knob can reach it. A controlled
re-measurement on the routed netlist with extracted parasitics — same tool, same
liberty, same SDC, same declared activity basis — gives
**0.000573 W**, **1.873×**
the shipped figure, with the clock group moving from 0.0 % to 33.7 % of total.

The same re-measurement on the winner gives **0.000559 W** — so the winner is in
fact **-2.44 %**
lower in real post-route power as well as smaller. **The shipped power number
reports that difference as exactly zero**, because it is the same number for both
arms. A search run against it as an objective would have been searching a
constant.

### The best five, and the worst three

| trial | die_um | density | spare | objective µm² |
|---|---|---|---|---|
| t028 | auto | 0.60 | 0.00 | **6136** |
| t032 | auto | 0.50 | 0.00 | **6160** |
| t007 | auto | 0.40 | 0.00 | **6267** |
| t020 | auto | 0.60 | 0.02 | **6291** |
| t024 | auto | 0.50 | 0.02 | **6306** |
| … | | | | |
| t022 | 280x280 | 0.30 | 0.05 | **7294** |
| t010 | 280x280 | 0.50 | 0.05 | **7307** |
| t019 | 280x280 | 0.20 | 0.05 | **7393** |

**Winner: `t028`** — `die_um=auto, placement_density=0.60,
spare_cell_density=0.00` at
**6136 µm²**, against the default run's **6594 µm²**:
**-6.95 %**.

### The winner is not free, and the report says so

At `die_um=auto`, the objective decomposes exactly:

| placement density | spare 0.00 | spare 0.02 | spare 0.05 |
|---|---|---|---|
| 0.20 | 6709 | 6823 | 6994 |
| 0.30 | 6454 | 6594 | 6775 |
| 0.40 | 6267 | 6394 | 6578 |
| 0.50 | 6160 | 6306 | 6492 |
| 0.60 | 6136 | 6291 | 6462 |

The default run is the `0.30 / 0.02` cell. The winner is the `0.60 / 0.00` cell.
The move splits into two unequal halves:

* **0.30 → 0.60 density at spare 0.02**: 6594 → 6291 µm²,
  **-4.60 %**. A real placement improvement; nothing is
  given up.
* **spare 0.02 → 0.00 at density 0.60**: 6291 → 6136 µm²,
  a further **-2.46 %**, bought by **deleting all
  10 spare ECO cells**.

So roughly two-thirds of the headline win is engineering and one-third is paying
for area with metal-only ECO readiness. A design that wants to keep
design-for-ECO should read the winner as **`t020` at 6291 µm²
(-4.60 %)**, not `t028`.

### One trial is genuinely infeasible, and the search found it

**`t033`** (`die 280x280, density 0.60, spare 0.00`) produced **2 real sign-off
DRC violations**, category `m3.2` (Metal-3 minimum spacing), edge-pairs at
(137.03–137.46, 217.4) µm. The flow caught it:

```
FAIL   drc      violations=2 (user=2, stdcell=0) top_rules: m3.2=2
```

Nothing was hand-edited to make it pass. It is published as INFEASIBLE and
excluded from the frontier on that ground.

**It is also the negative control that validates the F-3 bridge.** OpenROAD's own
detailed-route DRC record for that same trial reads
`route.drc.violation.count = 0`. Anyone bridging the feasibility namespace by the
obvious rename — `route.drc.violation.count` → `physical.drc.violations` — would
have published `t033` as clean. The bridge must read the sign-off deck, and the
one in `tools/signoff_records.py` does.

---

## 4. Feasibility, and the frontier that is empty by construction

**With the shipped extractors only:** all
61 arms come back `UNDETERMINED`, rc=2 —
{'UNDETERMINED': 61}. Seven of nine axes report `FEAS_METRIC_ABSENT` —
the metric they prove from is produced by nothing in `programs/` (F-3).

**With `tools/signoff_records.py` bridging the namespace:**

| axis | statuses across all 61 arms |
|---|---|
| `antenna` | {'SATISFIED': 61} |
| `drc` | {'SATISFIED': 60, 'VIOLATED': 1} |
| `drv` | {'UNDETERMINED': 61} |
| `em` | {'UNDETERMINED': 61} |
| `equivalence` | {'UNDETERMINED': 61} |
| `hold` | {'UNDETERMINED': 61} |
| `ir` | {'SATISFIED': 61} |
| `lvs` | {'SATISFIED': 61} |
| `setup` | {'UNDETERMINED': 61} |

Set-level verdicts: **{'UNDETERMINED': 60, 'INFEASIBLE': 1}**. `drc`, `lvs`, `antenna` and `ir` become
decidable — and the bridged gate **discriminates rather than merely refusing**:
one arm comes back `INFEASIBLE`, and it is `t033`, on the `drc` axis, which is
the trial that really does have two sign-off violations. `setup`, `hold`, `drv`, `em`
and `equivalence` stay `UNDETERMINED`, and **every one of those five is a real
gap in the flow's evidence, not a gap in the bridge** — F-6 (the multi-corner
sign-off STA reports carry no `STA_BASIS` stamp), F-15 (no artefact prints a hold
`wns`), F-16 (post-layout LEC errored), F-17 (the EM report supports no violation
count), and F-3 for `drv`.

**The published frontier is empty, and the manifest says why:**

```
frontier included: 0
frontier excluded: {'FEASIBILITY_UNDETERMINED': 60}
toolchain.feasibility_source: "STUB"
```

`ppa_search_run.py:243` hard-wires `evaluate_feasibility(None)` — the stub — even
though `_ppa/feasibility.py` landed three commits earlier (F-12). The stub's
reason string, published verbatim into every manifest, asserts that
`_ppa/feasibility.py` has not landed. On this tree that is untrue.

`ppa_search_run.py --verify` nevertheless returns **rc=0**:

> manifest is self-consistent: every trial published, every budget dimension
> declared, every frontier point eligible and at one scope.

That is correct. A manifest that publishes an empty frontier *and says why* is
self-consistent. It is the frontier that is empty, not the bookkeeping.

---

## 5. The head-to-head, and its four alignment conditions

Arms: **`vibe-ic-phase3-defaults`** (baseline, `tuned_by_this_project: false`) vs
**`vibe-ic-phase3-searched`** (subject, the winner). Both declare
`tuning.supported: false`, which is a **measured** fact, not a convenience:

```
$ python3 programs/ppa_closure_run.py --list-edges
[CANNOT CHECK] no declared edge has an executable controller. Every one of the
22 edges is DECLARED_ONLY and none may be displayed as a closed-loop success.
ppa_closure_run: 22 declared edges, 0 BOUND, 22 DECLARED_ONLY
```

The flow ships no executable tuner. The search harness that chose the subject's
configuration is this lane's, which is exactly what `tuned_by_this_project: true`
records on that arm.

**Condition 0 — same problem.** Passes, by hash, not by heading:

```
$ python3 programs/ppa_problem_integrity_check.py --baseline ... --candidate ... \
      --require-implementation-differs
[PASS] problem, analysis and toolchain identities MATCH and the implementation
       identity differs — these two runs are comparable.     rc=0
```

The RTL (`sha256:e7feff2cbbad384a…`) and the synthesis netlist
(`sha256:871c924ee5a3cc8b…`) are **byte-identical in every one of the 61 arms**.
Getting here needed F-13 and F-14 resolved first.

**The four conditions, and what each verdict was:**

**A — the honest record, shipped numbers only** — `records/head_to_head.json`, rc=1, `STAGE_CONTRADICTS_BASIS`

> arm 'vibe-ic-phase3-defaults' declares measurement_basis='post_route_sta', which may cite ['post_route', 'post_route_extracted'], but its `power_mw` was taken at stage='synth' -- a stage this basis does not cover. A record that cites a pre-physical number under a sign-off basis is claiming a measurement it did not take.

Condition that failed: **same stage**. Cause: F-7.

**B — same record with the power axis taken from the labelled post-route diagnostic** — `records/head_to_head_diagnostic_power.json`, rc=2, `FEASIBILITY_NOT_CHECKED`

> feasibility is not established for ['vibe-ic-phase3-defaults', 'vibe-ic-phase3-searched']: vibe-ic-phase3-defaults: ['drv', 'hold', 'setup']; vibe-ic-phase3-searched: ['drv', 'hold', 'setup']. An unclosed or unverified implementation cannot be the cheaper one, and a comparison that did not look is UNDETERMINED.

Condition that failed: **both sides feasible**. Cause: F-6 for setup and hold, F-3 and F-15 for drv.

Conditions **same corner** and **same activity basis** hold in both records, and
`check_scope_parity` passed them: every axis carries the full `REQUIRED_SCOPE`
and the two arms' scope dicts are equal. Record A never reaches the feasibility
check, because the stage contradiction is fatal first; record B is the one that
shows what the remaining condition would say.

Full machine reports: `records/head_to_head_report.json`,
`records/head_to_head_diagnostic_power_report.json`.

**The correct output here is a REFUSAL, and it is the deliverable.** The winner
is better on the declared objective — 6136 vs 6594 µm², a real
-6.95 % — and the head-to-head still must not be published
as a win, because a condition does not hold and the machinery names which one.
A smaller claim would have been the wrong answer; so would fixing the gate.

---

## 6. The report and the page-claim gate

`ppa_report_gen.py` refused twice before it produced anything, both times
correctly, and both times on a defect that is now F-9 and F-10:

```
[REFUSE] CLAIM_ID_COLLISION: two different records produce claim id
  `route.drc.violation.count.93321146` — same metric, same scope, different
  fact. A citation that resolves to two numbers binds a sentence to neither.
rc=1
```

`rc=1` means **no report can be generated from a default run at all** until the
colliding scopes are disambiguated. With the uniform, value-preserving
disambiguation in `tools/adapt_records.py`:

```
$ python3 programs/ppa_report_gen.py records_flat.json --out report.md --claims claims.json
PPA report: 131 record(s) — DERIVED=2, INVALID=9, MEASURED=112, NOT_MEASURED=8
rc=0

$ python3 programs/ppa_page_claim_check.py report.md --claims claims.json --cite-numbers
page-claim check: 35 sentence(s), 139 claim(s), 9 banned form(s) enforced -> rc=0 OK
```

**The page-claim gate's verdict: rc=0, PASS**, with `--cite-numbers` on, so every
sentence stating a number carries a `[claim:<id>]` bound to an artefact path and
hash. It refused no sentence, because the generator emits none it cannot support.

Artefacts: `report/report.md`, `report/claims.json`, `report/page_claim.json`.

---

## 7. What this lane did not do

No GDS was hand-edited. No violating geometry was deleted. No pin was moved. No
rule deck was relaxed. `t033`'s two `m3.2` violations are published as
violations. No `--write-baseline` was run on any hygiene gate. No file under
`vibe-ic-marketplace/plugins/vibe-ic/` was modified — the two places where a
shipped module had to be worked around (F-4, F-8) are worked around by *calling*
it differently through hooks it already exposes, and both are written down.

---

## REQUESTS TO THE LANDER

Ordered by how much they unblock. Every one names the file and the reason;
`FINDINGS.md` carries the evidence.

**1 — `phase3_one_shot_runner.py`: stamp the multi-corner STA emitters** (F-6).
Three `puts "STA_BASIS: POST_ROUTE_SPEF"` lines, in the emitters that write
`sta_spef_multicorner.rpt` and `sta_mcorner_ocv.rpt`. Today they stamp nothing,
48 of 56 timing rows come out `stage=null`, and the *sign-off* corners are the
ones that cannot be staged. This is the single highest-value fix in the set:
it is three lines and it unblocks the timing half of feasibility.

**2 — `phase3_one_shot_runner.py`: fix the Phase-3 power session** (F-7).
`reports/phase3/power_spm.tcl` must `read_verilog` the routed netlist and
`read_spef` the extracted parasitics, or the report's Substance section must stop
saying "post-PnR netlist". Today it is 1.873× low with the clock tree at zero.
Either fix is honest; shipping both statements is not.

**3 — a `klayout` / `netgen` / `psm` backend, or an extractor that bridges to the
feasibility namespace** (F-3). Seven of nine axes have no producer. The flow
measures all seven. `ppa-e2e/tools/signoff_records.py` is a working reference
implementation, including the `zero_three_ways` discriminator for DRC — and note
from `t033` why the obvious rename is not safe.

**4 — `ppa_search_run.py`: let the caller supply the real feasibility function**
(F-12). `Ledger.evaluate_feasibility` already takes one; line 243 passes `None`.
Add a flag. And correct `stub_feasibility`'s reason string — it is published into
every manifest and it says `_ppa/feasibility.py` has not landed, which stopped
being true at v1.11.26.

**5 — `_ppa/metrics.py`: accept the three envelopes this lane's own producers
write** (F-4), or have the producers write the bundle. Today
`ppa_metric_extract.py` indexes zero records from every shipped extractor's
output. Also: it writes an empty `--out` bundle on a refusal; the exit code is
honest but the file is not.

**6 — `_ppa/area.py` vs `_ppa/metrics.py`: agree on the unit of a `_count`**
(F-5). `area.py:175` says `"cells"`, `metrics.py` demands `"count"`. Six records
per run refused. One of the two files is wrong and either fix works.

**7 — `_ppa/backends/openroad.py`: put the source artefact in the scope** (F-9).
The log and the metrics JSON give different values for the same metric under an
identical scope. Both consumers refuse, one of them fatally.

**8 — `_ppa/timing.py`: collapse the duplicate reports and rank the paths**
(F-10). Every row is emitted twice from byte-identical files — the record already
carries `source.sha256`, so the dedupe is local. And
`timing.*.worst_path_slack_ns` needs a path ordinal in scope, or should emit only
the worst.

**9 — `_ppa/power.py`: fill the PVT scope it already has the parser for** (F-8).
`REQUIRED_SCOPE["power_mw"]` needs `process`, `voltage_v`, `temperature_c`,
`mode`; `power.py` records the liberty file name and the same lane ships
`opensta.parse_liberty_pvt`. Two lines.

**10 — `docs/PPA_INTERFACES.md` §4: state the rule that makes the contract
work** (F-13). "An artefact that varies with the implementation may not sit in
the `analysis` identity." It is currently implicit, and the obvious reading makes
`ppa_problem_integrity_check` refuse every legitimate comparison.

**11 — declare `jsonschema` as a dependency, or bundle it.** Without it
`ppa_contract_check.py` returns rc=2 on every contract with a correctly worded
`PPA-C-010`. The refusal is right; the missing dependency is not.

**12 — `_ppa/benchmark.derive_feasibility`: accept `status` as the schema says it
may** (F-18). It requires an integer `violations` on every floor check, so a
record that is valid against `comparison.v2` and declares `status: CLEAN`
everywhere derives as NOT_CHECKED. LVS is the awkward case: it produces a
verdict, and `violations: 0` is currently the only way to say it is clean.

**13 — smaller ones**: `phase3_one_shot_runner.py` should not write absolute host
paths into the analysis scripts it emits (F-14); the EM report needs a violation
count and a declared limit before `reliability.em.violations` can mean anything
(F-17); and a relative `--json` path with `cwd=programs/` plants a file in the
shipped tree, which the atomic-artefact writer does not guard against.

---

## Where everything is

```
ppa-e2e/
  RESULT.md  FINDINGS.md  METHOD.md
  search/    space.json plan.json trials.json manifest.json
             manifest_verify.json winner.json trial_args.txt
  records/   README.md          what each file in an arm directory is
             baseline/          the default run, in full
             trials/t000..t059/ all 60, records + contract + both feasibility runs
             head_to_head.json  head_to_head_report.json
             head_to_head_diagnostic_power.json  ..._report.json
             summary.json       every figure this document quotes
  report/    default-run/  report.md claims.json page_claim.json report_run.json
             winner/       the same for the search winner
  diag/      the labelled post-route power re-measurement (F-7), baseline and winner
  tools/     every caller-side program this lane wrote
```

Nothing under `vibe-ic-marketplace/plugins/vibe-ic/` is touched by this branch.
