---
name: hold-fix
description: "Post-CTS and post-route hold violation fixing via buffer/delay cell insertion. CTS always introduces hold violations that must be fixed. Use when: 'hold violation', 'hold fix', 'hold slack', 'fix hold', 'negative hold slack', 'post-CTS hold', 'short path padding', or after CTS completes (Step 19)."
---

# Hold Fix — Post-CTS / Post-Route Hold Violation Repair

After CTS, clock insertion delay makes fast data paths arrive too early at capture flops, causing hold violations. This is expected and must be fixed by inserting buffers or delay cells on short paths. Hold fixing is iterative: fix -> check -> re-fix until all hold slack >= 0 at the fast (FF) corner.

## When to use

- **After CTS (Step 19)**: CTS introduces clock insertion delay that creates hold violations on short paths. This is the primary trigger.
- **After routing**: parasitics change path delays, potentially creating new hold violations.
- **After ECO**: any timing ECO can shift hold margins.
- **Before signoff**: hold must be clean at FF corner for tapeout.

## Inputs

1. Post-CTS or post-route database (DEF + netlist)
2. SDC constraints with clock definitions
3. Liberty files for the fast (FF) corner — hold is worst at FF
4. STA hold report (`report_checks -path_delay min`)
5. Area budget — maximum area overhead for buffer insertion (typically 2-5%)
6. Hold slack margin target (e.g., 0 ps for nominal, +50 ps for guardband)

## Workflow

### Step 1: Analyze Hold Violations

Run STA at the FF corner (fast process, high voltage, low temperature):

```tcl
# OpenSTA
read_liberty gf180mcu_fd_sc_mcu7t5v0__ff_1p10v_m40c.lib
read_verilog <design>.v
read_sdc constraints/<design>.sdc
report_checks -path_delay min -slack_max 0 -format full_clock_expanded
```

Collect:
- Total number of hold-violating endpoints
- Worst Hold Slack (WHS)
- Total Hold Slack (THS) — sum of all negative hold slacks
- Distribution: how many endpoints per slack bucket (0 to -100 ps, -100 to -200 ps, etc.)

### Step 2: Hold Fix Strategy

The fix is always the same: **slow down the data path** by inserting buffers or delay cells.

Strategy selection (slack-bucket → strategy) is a pure numeric-threshold lookup —
**enforced by `programs/hold_fix_planner.py`** (`pick_strategy`: `> -50 ps` →
single buffer; `-200..-50 ps` → 2-3 buffer chain; `< -200 ps` → delay cell /
restructure). Feed it the per-endpoint hold-slack list; do not re-read a prose
table.

Buffer cell selection from the PDK Liberty list (prefer minimum-drive buffers,
prefer delay-gate cells, reject clock buffers / inverters / high-drive cells) is
a deterministic library-cell ranking — **enforced by
`programs/hold_buffer_cell_picker.py`**. Pass it the candidate cell-name list; it
returns the SKILL-preferred minimum-drive delay/buffer and FAILs honestly when no
safe buffer/delay cell exists.

### Step 3: Execute Hold Fix in OpenROAD

Do not hand-copy the `repair_timing -hold` block — **emit it via
`programs/openroad_hold_repair_tcl_gen.py`**, which bakes in the two hard
guardrails (`-allow_setup_violations false`, never tradeable; `-max_buffer_percent`
capped at 5%) and the post-fix verification reports. It FAILs rather than emit a
budget over the cap or a `true` setup-violation flag:

```bash
python3 ../../programs/openroad_hold_repair_tcl_gen.py \
    --margin-ps <margin_ps> --max-buffer-percent <area_budget_%> --out hold_repair.tcl
```

Key parameters:
- `-slack_margin`: target hold slack (0 for exact, positive for guardband)
- `-allow_setup_violations false`: **critical** — never trade setup for hold (the
  emitter refuses any other value)
- `-max_buffer_percent`: cap area overhead (default 5%; emitter rejects > 5%)

### Step 4: Verify — No Setup Regression

After hold fix, verify setup timing is still clean:

```tcl
# Check setup at SS corner
report_checks -path_delay max -slack_max 0
report_worst_slack -max
```

If setup degrades:
- The inserted buffers added delay on paths that were also setup-critical
- Reduce hold margin target
- Or upsize the hold buffers to reduce their setup impact

### Step 5: Iterate Until Clean

```
Iteration 1: WHS = -180 ps, THS = -12400 ps, 87 endpoints
  -> Insert 143 buffers
Iteration 2: WHS = -22 ps, THS = -340 ps, 8 endpoints
  -> Insert 12 buffers
Iteration 3: WHS = +5 ps, THS = 0 ps, 0 endpoints
  -> CLEAN. Hold fixed.
```

Convergence criteria (WHS >= margin AND THS == 0 AND setup WNS not degraded AND
area within budget) and the iterate-until-clean loop are **enforced by
`programs/iterative_search.py` + `programs/loop_admission_guard.py`** (the
`ConvergenceChecker` classifies `CONVERGED` / `PLATEAU` / `REGRESSION` /
`EXHAUSTED`). Do **not** hand-roll an iteration counter — see "Canonical loop
infrastructure" below for the wiring.

Typical iteration count: 2-4 rounds for a clean design.

### Step 6: Corner Coverage

Hold must be verified at the FAST (FF, high-V, low-T) corner — the worst-case
corner for hold. That the hold (min-path) analysis is actually driven by the FF
Liberty / operating condition (not SS/TT) is **enforced by
`programs/hold_corner_coverage_check.py`**, which FAILs if the hold view reads a
non-fast corner or if no hold analysis is present at all:

```bash
python3 ../../programs/hold_corner_coverage_check.py <hold_analysis.tcl_or_log>
```

Broader SS/TT/FF Liberty presence across the whole tree is audited separately by
`programs/corner_coverage_audit.py`. Sanity checks at TT across temperatures are
still good practice.

## Constraints and Guardrails

The two numeric/template guardrails are enforced by programs (not prose):

1. **Never violate setup while fixing hold** (`-allow_setup_violations false`) —
   enforced by `programs/openroad_hold_repair_tcl_gen.py` (refuses `true`).
2. **Area budget** (hold buffers <= 5% of total cell area) — enforced by
   `programs/hold_area_budget_check.py`. If it FAILs (budget exceeded), THEN apply
   the LLM judgment below: investigate WHY (possible CTS imbalance / over-skewed
   clock tree) rather than just inserting more buffers.

The remaining guardrails need LLM intent/spec judgment and stay here:

3. **Don't fix false paths**: verify that hold-violating paths are real (not async
   crossings that SHOULD be `false_path` / `set_clock_groups -asynchronous` in the
   SDC). A path missing its constraint vs a genuinely fast path is a spec judgment.
4. **Clock gating paths**: hold fix near ICG cells needs special care — the enable
   timing must remain correct.
5. **Scan chain**: DFT scan paths also need hold clean at scan clock frequency.

## Output format

- `timing/hold_fix_report.md`:
  - Before/after summary: WHS, THS, #violating endpoints
  - Buffers inserted: count, type, total area overhead
  - Setup impact: WNS before/after hold fix
  - Per-iteration log
  - Corner coverage matrix
  - Any remaining violations (if area budget exceeded)

## Technical basis

Hold timing: T_hold < T_clk_skew + T_data_delay. When CTS adds clock insertion delay (skew), short data paths violate hold. Standard reference: Bhasker & Chadha "Static Timing Analysis for Nanometer Designs" Chapter 7. OpenROAD `repair_timing -hold` documentation: https://openroad.readthedocs.io/en/latest/main/src/rsz/README.html.

## Handoff

- Hold clean -> `/sta-review` for full signoff timing review
- Setup degraded -> `/sta-review` to classify setup violations
- Area exceeded -> `/placement-optimize` to reclaim area
- New hold after routing -> re-run this skill post-route
- Signoff -> `/tapeout-checklist` includes hold clean as gate

## Canonical loop infrastructure (mandatory — shared with all *-fix loops)

The "Iterate Until Clean" loop (Step 5) MUST be driven by the two shared
closed-loop primitives so every fix loop in Vibe-IC obeys one
convergence / plateau / regression policy and one runaway / dedup guard —
do **not** hand-roll a bespoke iteration counter or duplicate-check.

**1. `programs/iterative_search.py` — the parameter sweep.**
Model the hold-fix knobs as a typed `SearchSpace` and let `IterativeSearch`
propose the next buffer/skew trial; `ConvergenceChecker` classifies the slack
history (`CONVERGED` / `PLATEAU` / `REGRESSION` / `EXHAUSTED` / `CONTINUE`):

```python
import iterative_search as it
space = it.SearchSpace([
    it.Dimension("buffers", "integer", lo=0, hi=512),     # delay cells to insert
    it.Dimension("skew_ps", "continuous", lo=-50.0, hi=50.0),
    it.Dimension("strategy", "enumerate", choices=["repair_hold", "buffer", "pad"]),
])
# target=0 WHS, tolerance = margin; patience guards against a stuck loop
checker = it.ConvergenceChecker(target=0.0, tolerance=1.0, patience=4)
search  = it.IterativeSearch(space, checker, maximize=True, seed=7, max_rounds=20)

def evaluate(point):          # caller runs OpenROAD repair_timing -hold + OpenSTA here
    return measured_WHS_ps    # higher (toward 0) is better
outcome = search.run(evaluate)
# outcome.status, outcome.best_point, outcome.best_score, outcome.rounds
```

`IterativeSearch` internally constructs an `AdmissionGuard(bounds=space.bounds(),
max_iterations=max_rounds)`, so every proposed point is already runaway- and
dedup-guarded when you use `search.propose()` / `search.run()`.

**2. `programs/loop_admission_guard.py` — admit each iteration BEFORE the EDA run.**
If you drive the loop manually (not via `search.run`), wrap every proposed
buffer/skew trial through `AdmissionGuard.admit()` and only spend the expensive
OpenROAD/OpenSTA round when `res.admitted` is true:

```python
import loop_admission_guard as g
guard = g.AdmissionGuard(
    bounds={"skew_ps": (-50.0, 50.0)},      # clamp into range
    caps={"buffers": 512},                  # REJECT a runaway buffer count
    max_iterations=20)                       # hard RUNAWAY iteration budget
res = guard.admit({"buffers": 143, "skew_ps": -22.0})
if res.admitted:
    run_iteration(res.proposal)              # res.proposal is post-clamp / safe
# else res.reason in {DUPLICATE, RUNAWAY_CAP, RUNAWAY_ITERATION_BUDGET}
```

CLI one-shot decision (exit 0 = ADMITTED, 1 = REJECTED):

```bash
python3 programs/loop_admission_guard.py decision.json
# decision.json: {"bounds":{...},"caps":{...},"max_iterations":20,
#                 "history":[...prior proposals...],"proposal":{...}}
```

`canonical_fingerprint(proposal)` (md5, key-order- and float-noise-stable) is
the dedup key — an already-tried buffer/skew combination is rejected with
`reason="DUPLICATE"` instead of burning another STA run. This replaces the
informal "Typical iteration count: 2-4 rounds" expectation with an enforced
budget and plateau/regression exit, while leaving every existing convergence
criterion in Step 5 unchanged.

## ⛔ ECO spare-cell preservation (mandatory)

> ⛔ **ECO spare-cell preservation:** cells/gates/pads carrying the `dont_touch` /
> `keep` attribute (or otherwise tagged spare/ECO) are RESERVED for a future
> metal-only ECO. NEVER delete, resize, re-purpose, or optimize them away. Hold
> fixing INSERTS buffers/delay cells — it is fine to *physically realize* a
> brand-new buffer ON a spare site, but you must NOT silently CONSUME a spare
> buffer without replacing it: if a hold fix repurposes a keep-marked spare, you
> must re-insert an equivalent spare so the ECO pool is not depleted, and the
> consumed instance's keep attribute must not be stripped from the surviving
> pool. No `opt_clean` / `remove_buffers` / area-recovery on keep-marked
> instances. After hold fix, `spare_cell_preservation_check.py` MUST still PASS
> (spare set + keep attrs intact, 0 removed); a dropped spare is a regression —
> restore it and re-run the checker. See the `design-for-eco` skill.

## Compliance gate (mandatory — not optional)

After producing your output, save it to a file and run:

```bash
python3 ../../_shared/skill_compliance_check.py \
    --requirements ./compliance.yaml <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with the specific missing elements listed.
`compliance.yaml` (in this skill's directory) enumerates every required
element of your output — section headers, metadata fields, handoff lines,
tool invocations.

**Your task is not complete until the audit returns PASS.** If it fails,
re-read the listed missing elements, patch your output, and re-run the
audit. This guarantees that different agents executing this same SKILL.md
produce reports containing the same required elements, even when the prose
inside each element differs. Missing elements are the single largest
source of skill-execution non-determinism.
