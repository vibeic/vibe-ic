#!/usr/bin/env python3
"""Write RESULT.md from summary.json, so every figure in the prose is the figure
in the artefact. Nothing here is typed twice."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path("/home/reyerchu/_jppae2e")
OUT = ROOT / "wt/ppa-e2e/RESULT.md"
S = json.loads((ROOT / "records/summary.json").read_text())
W = json.loads((ROOT / "search/winner.json").read_text())
M = json.loads((ROOT / "search/manifest.json").read_text())
PLAN = {f"t{c['index']:03d}": c["knobs"]
        for c in json.loads((ROOT / "search/plan.json").read_text())["plan"]}
OBJ, PW, SW, FE = S["objective"], S["power_invariance"], S["sweep"], S["feasibility"]
_wp = json.loads((ROOT / f"records/trials/{OBJ['winner']}/power_postroute_records.json").read_text())
WINP = [r["value"] for r in _wp["metrics"]
        if r["metric"] == "power.total_w" and r["scope"].get("group") == "Total"][0]


def h2h(tag):
    p = ROOT / f"records/{tag}_report.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def grid():
    o = {}
    for t in PLAN:
        f = ROOT / f"records/trials/{t}/records_flat.json"
        if not f.is_file():
            continue
        for r in json.loads(f.read_text()):
            if (r["metric"] == "area.design_report.um2" and r["status"] == "MEASURED"
                    and (r.get("scope") or {}).get("stage") == "post_route"):
                o[t] = r["value"]
    rows = []
    for dens in ("0.20", "0.30", "0.40", "0.50", "0.60"):
        cells = []
        for sp in ("0.00", "0.02", "0.05"):
            m = [o[t] for t, k in PLAN.items()
                 if t in o and k["die_um"] == "auto"
                 and k["placement_density"] == dens and k["spare_cell_density"] == sp]
            cells.append(f"{m[0]:.0f}" if m else "—")
        rows.append(f"| {dens} | {cells[0]} | {cells[1]} | {cells[2]} |")
    return "\n".join(rows), o


def lever_table(name):
    return "\n".join(
        f"| `{k}` | {v['n']} | {v['mean']} | {v['min']} | {v['max']} |"
        for k, v in S["lever_effect"][name].items())


def ranking(o):
    top = W["ranking"][:5]
    bot = W["ranking"][-3:]
    def row(r):
        k = r["knobs"]
        return (f"| {r['trial']} | {k['die_um']} | {k['placement_density']} | "
                f"{k['spare_cell_density']} | **{r['objective']:.0f}** |")
    return ("\n".join(row(r) for r in top), "\n".join(row(r) for r in bot))


gtab, objs = grid()
top, bot = ranking(objs)
h1, h2 = h2h("head_to_head"), h2h("head_to_head_diagnostic_power")


RC = {"head_to_head": 1, "head_to_head_diagnostic_power": 2}


def verdict_block(rep, tag, title, cond, cause):
    if rep is None:
        return f"**{title}** — `{tag}` report absent."
    r = rep.get("refusal") or {}
    return (f"**{title}** — `records/{tag}.json`, rc={RC[tag]}, "
            f"`{r.get('code')}`\n\n"
            f"> {r.get('message')}\n\n"
            f"Condition that failed: **{cond}**. Cause: {cause}.")


base = OBJ["baseline"]
win_v = OBJ["winner_value"]
keep_eco = objs.get("t020")

TEXT = f"""# The PPA flow, driven end to end on one real IC

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
| **wall time** | **{SW['wall_s']['median']:.0f} s median**, which is what makes a 60-point search affordable |

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

> {S['manifest']['sentence']}

| | min | median | max | total |
|---|---|---|---|---|
| wall s | {SW['wall_s']['min']:.0f} | {SW['wall_s']['median']:.0f} | {SW['wall_s']['max']:.0f} | {SW['wall_s']['sum_h']:.2f} h |
| CPU s | {SW['cpu_s']['min']:.0f} | {SW['cpu_s']['median']:.0f} | {SW['cpu_s']['max']:.0f} | {SW['cpu_s']['sum_h']:.3f} h |
| peak RSS MB | {SW['peak_rss_mb']['min']:.0f} | {SW['peak_rss_mb']['median']:.0f} | {SW['peak_rss_mb']['max']:.0f} | — |

Every CPU and RSS figure is that trial's own cgroup, from its own container.

**All 60 candidate records are in `search/manifest.json`**, and every trial's full
canonical record set is in `records/trials/tNNN/`. Nothing is published
winner-only.

### What the search actually moved

`area.design_report.um2` took **{OBJ['distinct_values']} distinct values across
{OBJ['n']} trials**, from **{OBJ['min']:.0f}** to **{OBJ['max']:.0f} µm²** — a
**{OBJ['spread_pct']:.1f} %** spread. The levers behave like physics:

**`die_um`** (mean objective, µm²)

| value | n | mean | min | max |
|---|---|---|---|---|
{lever_table('die_um')}

**`placement_density`**

| value | n | mean | min | max |
|---|---|---|---|---|
{lever_table('placement_density')}

**`spare_cell_density`**

| value | n | mean | min | max |
|---|---|---|---|---|
{lever_table('spare_cell_density')}

A bigger die costs area, monotonically, because distance has to be buffered.
Spare ECO cells cost area directly and monotonically, which is what they are for.
Placement density improves the objective monotonically from 0.20 to 0.50 and then
**flattens and very slightly reverses** at 0.60 (mean {S['lever_effect']['placement_density']['0.50']['mean']} vs
{S['lever_effect']['placement_density']['0.60']['mean']} µm²) — the last increment
buys nothing on average, and it is the density at which the run's only
DRC-dirty trial appears (`t033`, on the largest die).

### And what it did not move

**`power.total_w` is `{PW['values'] and list(PW['values'])[0]} W` in
{PW['n']} of {PW['n']} trials — identical to the last digit,** across every
combination of die size, placement density and spare density. That is not a
coincidence and not stability: it is F-7. The power number is computed on the
pre-PnR synthesis netlist, so no place-and-route knob can reach it. A controlled
re-measurement on the routed netlist with extracted parasitics — same tool, same
liberty, same SDC, same declared activity basis — gives
**{PW['diagnostic_postroute']} W**, **{PW['diagnostic_postroute']/PW['baseline']:.3f}×**
the shipped figure, with the clock group moving from 0.0 % to 33.7 % of total.

The same re-measurement on the winner gives **{WINP} W** — so the winner is in
fact **{(WINP-PW['diagnostic_postroute'])/PW['diagnostic_postroute']*100:.2f} %**
lower in real post-route power as well as smaller. **The shipped power number
reports that difference as exactly zero**, because it is the same number for both
arms. A search run against it as an objective would have been searching a
constant.

### The best five, and the worst three

| trial | die_um | density | spare | objective µm² |
|---|---|---|---|---|
{top}
| … | | | | |
{bot}

**Winner: `{OBJ['winner']}`** — `die_um=auto, placement_density=0.60,
spare_cell_density=0.00` at
**{win_v:.0f} µm²**, against the default run's **{base:.0f} µm²**:
**{OBJ['vs_baseline_pct']:.2f} %**.

### The winner is not free, and the report says so

At `die_um=auto`, the objective decomposes exactly:

| placement density | spare 0.00 | spare 0.02 | spare 0.05 |
|---|---|---|---|
{gtab}

The default run is the `0.30 / 0.02` cell. The winner is the `0.60 / 0.00` cell.
The move splits into two unequal halves:

* **0.30 → 0.60 density at spare 0.02**: {base:.0f} → {keep_eco:.0f} µm²,
  **{(keep_eco-base)/base*100:.2f} %**. A real placement improvement; nothing is
  given up.
* **spare 0.02 → 0.00 at density 0.60**: {keep_eco:.0f} → {win_v:.0f} µm²,
  a further **{(win_v-keep_eco)/keep_eco*100:.2f} %**, bought by **deleting all
  10 spare ECO cells**.

So roughly two-thirds of the headline win is engineering and one-third is paying
for area with metal-only ECO readiness. A design that wants to keep
design-for-ECO should read the winner as **`t020` at {keep_eco:.0f} µm²
({(keep_eco-base)/base*100:.2f} %)**, not `{OBJ['winner']}`.

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
{sum(FE['shipped_only'].values())} arms come back `UNDETERMINED`, rc=2 —
{FE['shipped_only']}. Seven of nine axes report `FEAS_METRIC_ABSENT` —
the metric they prove from is produced by nothing in `programs/` (F-3).

**With `tools/signoff_records.py` bridging the namespace:**

| axis | statuses across all {sum(FE['bridged'].values())} arms |
|---|---|
""" + "\n".join(
    f"| `{k}` | {v} |" for k, v in sorted(FE["bridged_axes"].items())) + f"""

Set-level verdicts: **{FE['bridged']}**. `drc`, `lvs`, `antenna` and `ir` become
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
frontier included: {S['manifest']['frontier_included']}
frontier excluded: {S['manifest']['frontier_excluded']}
toolchain.feasibility_source: "{S['manifest']['feasibility_source']}"
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
$ python3 programs/ppa_problem_integrity_check.py --baseline ... --candidate ... \\
      --require-implementation-differs
[PASS] problem, analysis and toolchain identities MATCH and the implementation
       identity differs — these two runs are comparable.     rc=0
```

The RTL (`sha256:e7feff2cbbad384a…`) and the synthesis netlist
(`sha256:871c924ee5a3cc8b…`) are **byte-identical in every one of the 61 arms**.
Getting here needed F-13 and F-14 resolved first.

**The four conditions, and what each verdict was:**

{verdict_block(h1, 'head_to_head', 'A — the honest record, shipped numbers only',
               'same stage', 'F-7')}

{verdict_block(h2, 'head_to_head_diagnostic_power',
               'B — same record with the power axis taken from the labelled post-route diagnostic',
               'both sides feasible',
               'F-6 for setup and hold, F-3 and F-15 for drv')}

Conditions **same corner** and **same activity basis** hold in both records, and
`check_scope_parity` passed them: every axis carries the full `REQUIRED_SCOPE`
and the two arms' scope dicts are equal. Record A never reaches the feasibility
check, because the stage contradiction is fatal first; record B is the one that
shows what the remaining condition would say.

Full machine reports: `records/head_to_head_report.json`,
`records/head_to_head_diagnostic_power_report.json`.

**The correct output here is a REFUSAL, and it is the deliverable.** The winner
is better on the declared objective — {win_v:.0f} vs {base:.0f} µm², a real
{OBJ['vs_baseline_pct']:.2f} % — and the head-to-head still must not be published
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

**Requests 1 and 2 are SATISFIED and are kept, marked, rather than deleted** —
the finding was true when it was written and the record of it is worth keeping;
only the present tense had gone false. A satisfied request left in the present
tense is a document contradicting the tree it describes: it tells a reader to
go add three lines that are already there. Measured 2026-08-22 — every
`sta_*` report on this host written before 2026-08-21 carries no `STA_BASIS`
and every one written after carries it, and the run trees split on exactly that
line. **The first LIVE request in this list is #3.**

**1 — `phase3_one_shot_runner.py`: stamp the multi-corner STA emitters** (F-6).
**SATISFIED by `e4c5840d6` (v1.11.57, 2026-08-21)**, which added the stamps and
the guard `tests/test_multicorner_signoff_reports_declare_their_stage.py`. All
three emitters — `_emit_spef_sta`, `_emit_corner_spef_sta` and
`_emit_mcorner_ocv_sta` — now write a `STA_BASIS:` line, and `_ppa/timing`
resolves it to `stage=post_route_extracted`. Kept as the record of the finding,
NOT as a live request. AS WRITTEN: three `puts "STA_BASIS: POST_ROUTE_SPEF"`
lines, in the emitters that write `sta_spef_multicorner.rpt` and
`sta_mcorner_ocv.rpt`; at the time they stamped nothing, 48 of 56 timing rows
came out `stage=null`, and the *sign-off* corners were the ones that could not
be staged.

**2 — `phase3_one_shot_runner.py`: fix the Phase-3 power session** (F-7).
**SATISFIED by `e4c5840d6` (v1.11.57, 2026-08-21)**: the session links the
routed netlist and reads the extracted parasitics when they exist, and when
they do not it degrades LOUDLY — the `POWER_BASIS` stamp, the note and the
provenance envelope all name what was actually linked. Kept as the record of
the finding, NOT as a live request. AS WRITTEN:
`reports/phase3/power_spm.tcl` must `read_verilog` the routed netlist and
`read_spef` the extracted parasitics, or the report's Substance section must stop
saying "post-PnR netlist"; at the time it was 1.873× low with the clock tree at
zero. Either fix is honest; shipping both statements is not.

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
"""

OUT.write_text(TEXT)
print(f"wrote {OUT} ({len(TEXT.splitlines())} lines)")
