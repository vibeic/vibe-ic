---
name: sta-review
description: Read Static Timing Analysis reports, triage setup/hold/recovery/removal violations, and propose fixes (RTL pipelining, sizing, useful skew, buffer insertion). Use when the user says "STA", "timing report", "timing violation", "setup fail", "hold fail", "close timing", "WNS", "TNS".
---

# STA Review

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt。
> Mandatory program preflight first; AI is the backstop, not the lead.

STA signoff runs in a commercial tool (PrimeTime, Tempus, OpenSTA). The
deterministic triage (5 endpoint categories → fix strategies) is now in
`programs/sta_triage_classify.py`; this skill is the wrapper that runs
it, narrates residual interpretation, and refuses to override the
program's category counts.

## Mandatory Deterministic Preflight

Before any narrative:

```bash
# 1. STA report audit (presence, WNS/TNS extraction, basic structure):
python3 plugins/vibe-ic/programs/sta_report_check.py \
    --rpt <sta.rpt> --json /tmp/sta_check.json

# 2. Endpoint categorisation (5 categories + fix strategy per category):
python3 plugins/vibe-ic/programs/sta_triage_classify.py \
    --endpoints-json <endpoints.json> \
    --wns <wns_ns> --tns <tns_ns> \
    --out-md /tmp/sta_triage.md --out-json /tmp/sta_triage.json
```

The program returns counts per category (cell_delay_limited /
net_delay_limited / logic_depth_limited / clock_skew_limited /
hold_violation) plus the fix strategy per category. **Do not author
these counts by reading the report.**

```bash
# 3. (when reviewing a PnR Tcl script) confirm the mandatory
#    setup-timing-repair sequence is present, not hold-fix-only:
python3 plugins/vibe-ic/programs/pnr_timing_repair_completeness_check.py \
    <pnr.tcl> --json /tmp/pnr_repair.json
```

`pnr_timing_repair_completeness_check.py` FAILs any OpenROAD PnR script
that runs only `repair_timing -hold` without `set_wire_rc` +
`repair_design` + `repair_timing -setup` (the sha256 silicon-DOA
anti-pattern). The phase3 runner already emits the full chain; this
gate is the static backstop when reviewing a hand-authored script.

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

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/sta-review/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.


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
# 4. timing RECORD completeness (runs unconditionally on a run dir):
python3 plugins/vibe-ic/programs/sta_corner_record_completeness_check.py \
    <run_dir> --json /tmp/sta_corner_record.json
```

`sta_corner_record_completeness_check.py` FAILs when:
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

It learns which corners are sign-off from the run's OWN declarations —
`mcorner_ocv_stance.json` (`setup_process_corner` / `hold_process_corner`),
`multi_corner_spef_stance.json` (`setup_corner` / `hold_corner`) and
`pvt_matrix.json` (`primary_corner`) — so no corner name is hardcoded and a PDK
with a different corner vocabulary is judged the same way. The corner→liberty
resolution comes from the same stances' `corner_library_resolution` block, and
from the `# corner_liberty:` header lines the STA reports now carry; a corner
*name* is never taken as evidence of which file was read, because believing the
name is how this defect survived. It always emits the full per-corner table
(corner, axis, role, setup WNS, hold WNS, TNS, source log) **plus the per-axis
library-resolution and DRV table**, on PASS as well as FAIL: the absence of that
evidence is the defect itself.

Distinct from `post_route_signoff_corner_check` (#147), which judges the slack
inside the multicorner report and is wired `condition_files_exist` on that very
report — so it self-skips when the report is absent. Do not read a
NOT_APPLICABLE from it as "timing is fine".

_Captured by benchmark-enhancement-capture 2026-07-21 (Bucket A, prose → program)._

## Captured rule — a single-register iterative self-loop is loop-bound: retiming can't help, the fix is a multi-cycle round (never a relaxed clock)

**Enforced by a program — no longer prose judgment.**

```bash
# 5. iterative-recurrence timing diagnosis (run when a setup violation
#    persists at the sign-off corner on an ITERATIVE / FSM datapath):
python3 plugins/vibe-ic/programs/iterative_recurrence_timing_diagnosis.py \
    --sta-report <worst_setup_path.rpt> \
    [--retiming-wns-delta <ns_from_a_retiming_experiment>] \
    [--spec-microarch-free] [--spec-latency-unconstrained] \
    [--target-period-ns <hard_period>] --json /tmp/iter_diag.json
```

**The diagnosis.** An iterative datapath computes one iteration per clock by
feeding a state register back to itself: `X <= f(..., X, ...)`. The state→state
cycle then contains **exactly one register**, and two facts hold for ANY such
loop on ANY PDK:

- **Loop-bound period.** Min period of a cyclic path = (Σ combinational delay on
  the cycle) / (registers on the cycle). One register ⇒ the floor is the *whole*
  cone delay. You cannot clock it below one full iteration.
- **Retiming is powerless.** Retiming preserves the register count on every
  cycle, so a one-register cycle stays one register and its bound is invariant.
  It shows up as `abc` dretime returning a **byte-identical** netlist / ~0 ns WNS
  improvement. Do not keep retrying it, and do not reach for pure logic
  restructuring (`dch -f; dc2`) either — it can break the ripple but inflate
  area/die so the routed slow-corner WNS gets **worse** from added wire delay.

**The fix, when the spec authorises it.** If the design spec leaves the microarch
as a free choice (iterative / unrolled / pipelined / multi-cycle) **and** does not
fix the latency-cycle count, split the recurrence cone over **N≥2 clocked
sub-stages** (a *multi-cycle round*). The loop now spans N registers; each cycle
is a genuine single-cycle path at the **same HARD period**, with per-cycle depth
~1/N. Latency in cycles grows ~N×; the period is what closes. The SDC stays the
honest single-cycle SDC — a multi-cycle round is N real single-cycle stages, **not**
a multicycle timing *exception*, so no `set_multicycle_path` masking is introduced.

### A synth-level timing win is NOT a post-route win — measure the shipped corner

**The only number that counts is post-route on the shipped SPEF.** A synthesis
knob that clearly improves the pre-PnR critical path can *degrade* the routed
slow corner, because area bought at synth becomes wire delay after placement —
and modern PnR already resizes for you.

**Measured, twice, in opposite tools, same disease:**

| change | pre-PnR effect | post-route effect |
|---|---|---|
| `dch -f; dc2` restructuring | breaks the ripple | **+26% area, routed SS WORSE** |
| delay-driven mapping + gate sizing | arrival 65.507 → 50.954 ns (**−22.2%**) | **SS WNS −2.519 → −4.386 ns (1.87 ns WORSE)**, +4.6% cells |

The second was a controlled A/B: same RTL, same run-dir shape, both freshly
synthesised, differing **only** in the mapper flags. A 22% pre-PnR improvement
became a 1.87 ns post-route regression. Mechanism: OpenROAD's `repair_design` /
`repair_timing` already resize **after** placement, so synth-time sizing is
largely redundant with them — you keep its area cost and lose the wire delay.

So: **never accept a pre-PnR delta as evidence.** Re-run the post-route A/B on
the shipped SPEF before adopting any synth QoR knob, and be prepared for the
sign to flip.

### A related trap: a timing lever that was never actually engaged

Separately worth knowing, because it invites exactly the "fix" above: a delay
target can be passed and silently ignored. Measured — `abc -liberty <lib> -D
<period>` produced a netlist **byte-identical** to no `-D` at all (identical
worst-path arrival, cell count and area), because on the non-`-constr` path the
default `&nf` mapper ignores `-D`; the fork's own help documents a `-sizing`
flag that exists precisely to make `-D` bind.

Two lessons, and the second matters more:

1. **Verify a flag does something.** Byte-identical output with and without it
   is proof it is inert — a cheap, conclusive diff worth running on any knob you
   believe is protecting you.
2. **Inert is not automatically wrong.** Here, engaging the ignored lever made
   the shipped corner worse, so leaving it inert was the measured-better
   configuration. Do not "repair" an unbound knob on the assumption that binding
   it must help.

Background worth having: yosys techmaps `$lcu` to a **Brent-Kung parallel-prefix
adder** (`techmap.v`, `_90_lcu_brent_kung`), so a fast adder is present by
default and a long carry chain in the report is the *mapper's* area-mode choice,
not what techmap built. That makes "the arithmetic is the floor" a conclusion to
reach last, not first — but as the table above shows, forcing delay-mode mapping
is not the remedy either.

Only once the flow's own knobs are measured out does an architectural change
earn its keep. If a re-measured worst path is *still* one full-width carry-propagate
add, then the per-cycle arithmetic cost is real and the remedies are: register
the carry across sub-cycles (split the add into half-width slices — a register in
the middle is the one split synthesis cannot merge back), or use a
carry-select/carry-lookahead adder. Both are pure microarch choices, in-spec
exactly when the multi-cycle split is. **Re-measure after every change**: the
critical path moves, and the next binding constraint is often a different one.
If the spec instead *forbids* the microarch change, that is an **honest floor**:
report the violated corner as violated, never dress it as a pass, and **never
relax the target clock** (the program FAILs hard on `--relax-clock-proposed`).

The program reads the worst path's start/end **register bank** (instance path
minus the bit-index) to spot the self-loop directly; when the netlist names are
synthesis-anonymised (`_1234_`) it returns `INCONCLUSIVE_NAMES_ANONYMIZED` and
asks for a name-preserving netlist or a retiming-experiment WNS delta rather than
guessing. A *measured* retiming improvement overrides the name heuristic
(`RETIMING_EFFECTIVE_APPLY`) — ground truth beats the heuristic.

Worked example (context, not detection logic) — and an honest open case. A
crypto hash accelerator on an open PDK at a HARD 25.907 ns period: the reference
iterative single-cycle round is an `a_reg`→`a_reg` / `e_reg`→`e_reg` self-loop
that misses the slow sign-off corner at **post-route WNS −2.519 ns**. Everything
tried so far has failed, and each failure is informative:

- `abc` dretime — **byte-identical netlist** (loop-bound, as predicted above).
- logic restructuring (`dch -f; dc2`) — breaks the ripple, **+26% area, routed
  SS worse**.
- delay-driven mapping + gate sizing — **−22% pre-PnR, +4.6% cells, post-route
  SS −4.386 ns (1.87 ns WORSE)**.
- multi-cycle round (2-cycle, and a 16-bit carry-split variant) — functionally
  verified only (NIST vectors 100%, 300/300 random blocks bit-identical to the
  reference). **Its timing was never validly measured**: the runs that appeared
  to measure it were reusing a cached netlist of the ORIGINAL design, so those
  numbers were retracted. See the netlist-cache rule — an RTL edit that never
  reaches synthesis produces confident numbers describing RTL nobody read.

So this cell does **not** converge, and no fix is claimed for it. What the case
does establish is the ordering: rule out flow defects and measure every knob
post-route *before* re-architecting, and treat any number produced by a run
whose RTL may not have been synthesised as void.

_Captured by repo-gatekeeper 2026-07-25 (prose → program; diagnosis + remedy routing)._
