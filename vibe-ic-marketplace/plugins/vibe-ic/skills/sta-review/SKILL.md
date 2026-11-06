---
name: sta-review
description: Read Static Timing Analysis reports, triage setup/hold/recovery/removal violations, and propose fixes (RTL pipelining, sizing, useful skew, buffer insertion). Use when the user says "STA", "timing report", "timing violation", "setup fail", "hold fail", "close timing", "WNS", "TNS".
---

# STA Review

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt。
> Run the native timing tools first. AI reviews their results.

STA signoff uses the selected native OpenSTA, PrimeTime or Tempus reports.
Read the launch and capture paths, SDC clocks and exceptions, Liberty corner,
SPEF and electrical drive/load model before proposing an implementation fix.

## Read the native timing results

Read the selected rows in `<project>/reports/flow_engine.json` and open their
native `reports`. `flow/steps.json` names each current tool and
`flow/native_limits.json` retains its original limits. Review `tool_ran`,
`native_steps`, `native_metrics`, and each metric's value, operator and limit.
A missing native measurement is `NOT_MEASURED`. AI reviews the engineering
meaning of every result and fixes problems in the design, tool or plugin.

```bash
python3 programs/flow_engine.py report --project <project>
```

Classify the reported failing paths as cell delay, net delay, logic depth,
clock skew or hold problems. If the I/O constraints or drive/load model are
unresolved, fix those constraints before attributing the failure to RTL.
Use the actual path components to support each classification.

## When to use

- After synthesis, after CTS, after routing, after ECO
- Any time WNS (Worst Negative Slack) or TNS (Total Negative Slack) goes positive
- When hold violations appear after routing
- Multi-corner sign-off (ss/tt/ff × low/high temp × low/high Vdd)

## Inputs

1. STA report(s) — setup + hold + recovery/removal + min-pulse-width
2. SDC constraints
3. Top violating paths (usually `-max_paths 100`)
4. Corner/mode matrix
5. Optional: RTL source for the violating module

## Workflow

1. **Categorize** every violating endpoint:
   - Cell delay limited → upsize driver, Vt swap
   - Net delay limited → insert buffer, reroute, shorten wire
   - Logic depth limited → pipeline / restructure RTL
   - Clock skew limited → useful skew, CTS re-balance
   - Hold → buffer insertion on min paths
2. **Propose fix per endpoint** with an estimated slack gain
3. **Flag paths that cannot be fixed by ECO** — require RTL change
4. **Cross-corner view**: if a path fails only at one corner, adjust margin first
5. **Summarize**: WNS/TNS before → after, number of endpoints touched

## Output format

- `sta/sta_review.md`:
  - Summary (WNS, TNS, #failing endpoints, corner)
  - Top 20 paths with classification + fix + slack delta
  - RTL change recommendations (handoff to `/rtl-repair`)
  - ECO fix list (handoff to `/eco-plan`)

## Technical basis

Static timing analysis is governed by setup/hold relationships around launch/capture flops. Standard references: Bhasker & Chadha "Static Timing Analysis for Nanometer Designs". OpenSTA is the open-source signoff-class engine (https://github.com/The-OpenROAD-Project/OpenSTA).

## Handoff

- RTL change → `/rtl-repair`
- Metal-only fix → `/eco-plan`
- Power impact of sizing → `/ir-drop-triage`
## Captured rule — PnR must run set_wire_rc + repair_design + repair_timing -setup (not hold-fix-only)

**Enforced by two programs — no longer prose judgment:**
- The full deterministic command sequence (`set_wire_rc -signal/-clock` with
  NONFATAL fallbacks → `estimate_parasitics` → `repair_design` →
  `repair_timing -setup` → `detailed_placement`; then post-CTS `repair_timing -hold`;
  then post-global-route re-estimate + repair) is **emitted by
  `programs/phase3_one_shot_runner.py`** (phase3 PnR template).
- **`programs/pnr_timing_repair_completeness_check.py`** is the static gate that
  FAILs any PnR script missing that chain (the hold-only silicon-DOA shape).

Worked example (kept for context): benchmark_clean/sha256 v0.1.25 post-route
WNS = -102.76 ns, mis-blamed on the SHA round; real cause was the missing
`set_wire_rc` / `repair_design` / `repair_timing -setup` (STA optimistic,
RSZ-0089). After adding the chain (v0.1.26): WNS = +10.95 ns MET on the same RTL.
General across all OpenROAD-driven PnR — template-level, not chip-specific.

_Captured by benchmark-enhancement-capture 2026-05-28; extracted to programs in M4._

## Captured rule — a corner that is unreported is not a corner that met

**Enforced by a program — no longer prose judgment.**

This skill already said, in prose, *"Multi-corner sign-off (ss/tt/ff × low/high
temp × low/high Vdd)"* and *"Cross-corner view: if a path fails only at one
corner, adjust margin first."* Prose cannot fail a run. Measured consequence: a
campaign ledger carried **no STA column at all** while two ICs violated setup at
the slow sign-off corner (worst setup slack **-4.33 ns**, TNS -259.13; and
**-2.35 ns**, TNS -10.36), both persisting unchanged into the post-fix verify
runs. Because timing was simply absent from the record, "the phase-3 failures
were LVS tooling artifacts" — true of the LVS part — was allowed to stand as the
whole explanation.

```bash
python3 programs/flow_engine.py report --project <run_dir>
```

Review the native STA results and their original limits for each reported corner.
Open the referenced OpenSTA logs and resolved configuration. Check:

- **R1** a reported corner is unnamed, or a corner carrying no sign-off role is
  characterised only half-way (setup without hold, or the reverse);
- **R2** a corner the flow DECLARED it would analyse has no datapoint for the
  role it was declared to serve — including the case where an STA verdict JSON
  outlives the report it cites;
- **R3** any sign-off corner violates. **A typ-only "MET" is a misleading pass**
  and never carries the run; when the typ corner met while a sign-off corner
  violated, the finding says so in those words;
- **R4** a multi-corner claim is not backed by multiple corner LIBRARIES —
  either the collapse is undisclosed (`R4_MULTI_CORNER_CLAIM_UNSUPPORTED`) or
  the run records no corner-to-liberty resolution at all
  (`R4_LIBRARY_RESOLUTION_UNRECORDED`);
- **R5** DRV is violated (`R5_DRV_VIOLATION`) **or was never queried**
  (`R5_DRV_UNQUERIED`).

### R4: a "multi-corner" run that read one library

Measured: a flow's "multi-corner" STA read the **typ liberty three times**,
varying only the SPEF. Three corners were reported; **one library was analysed**,
and the report did not say so. The degradation path is *designed* — the runner's
own docstring says that when corner libs are unavailable *"it degrades to the
single-corner `read_liberty` (byte-identical to the pre-multi-corner
emission)"*. **The degradation is not the defect; the silence is.** A degraded
run was byte-indistinguishable from a genuine one. What that silence cost: real
PVT STA run by hand closed setup+hold at three corners with TNS=0, but carried
**139 `max_slew` DRV violations at the slow corner**, entirely invisible to the
flow's single-corner check.

R4 is judged at **run level**, not per axis: a single-library RC axis is *not* a
degradation (the RC axis varies parasitics, and one process library across its
corners is correct by design). The degradation is when the run as a whole reports
several corners while never analysing more than one distinct library on **any**
axis. Judging per axis would label every healthy run degraded — the mirror image
of the defect.

A disclosed collapse is **not** a FAIL. It yields the verdict
**`SINGLE_CORNER_ONLY`** (exit 0): a PDK that genuinely ships one library cannot
do better, and failing it would fabricate a violation on every single-library
PDK. But the verdict *string* carries the limitation, so no downstream summary
can quote a bare "PASS" and have it read as multi-corner closure. **Never record
a `SINGLE_CORNER_ONLY` run as multi-corner sign-off.**

### R5: DRV must actually be asked for

`report_check_types -max_slew -max_capacitance` is what surfaces slew/cap
violations. If the flow never emits it, the report **cannot** show a slew
violation however many exist — an unqueried limit is indistinguishable from a
met one, which is the same disease R2 names for unreported slack. The emitter
attests the query with a `SIGNOFF_CHECK_TYPES_REPORTED` marker; its **absence**
is what separates "queried and clean" from "never asked".

Use the native configuration's `STA_CORNERS`, resolved Liberty files and
per-corner OpenSTA reports to identify the analysed corners. Compare their
setup WNS, hold WNS, TNS and DRV values against the original limits. A corner
name alone does not prove which library was read. Report absent corner or
library measurements as `NOT_MEASURED`, and review every tool result before
claiming signoff.
