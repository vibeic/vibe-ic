---
name: analog-sizing-loop
description: Closed-loop analog optimization — iterates sizing → netlist → SPICE corner sweep → spec check → re-size until all PVT corners pass. Use when the user says "optimize the analog block", "close the loop", "auto-size", or at Step A4 of the analog track.
---

# Analog Sizing Loop

Automates the iterative analog design loop that previously required 5-14 manual iterations (per PRACTICAL_NOTES.md). Orchestrates `analog-sizing` → `analog-netlist-gen` → `eda_spice_corner` in a closed loop with spec-driven convergence.

## When to use

- Step A4 of the analog track (after topology + initial sizing)
- When a single SPICE run shows failing corners and the user wants automated optimization
- After `/analog-sizing` provides an initial design point

## Inputs

1. `analog/<block>/spec.json` — performance targets with min/max limits
2. `analog/<block>/topology.md` — selected topology
3. `analog/<block>/sizing.md` — initial sizing from `analog-sizing`
4. PDK (gf180 or sky130)

## Loop workflow

```
Iteration 0:
  analog-sizing → initial W/L + bias
  analog-netlist-gen → SPICE deck
  eda_spice_corner (TT only) → quick sanity check
    If TT fails → re-size immediately (don't waste time on corners)

Iteration 1-N (max 5):
  eda_spice_corner (all corners: TT/SS/FF × -40/25/125°C)
  Parse yield table vs spec.json limits
  If all PASS → done
  If FAIL:
    1. Identify worst-case corner (e.g., SS @ -40°C)
    2. Identify dominant failure (e.g., gain too low)
    3. Identify sensitive device (e.g., M1 gm too small)
    4. Adjust: increase W (for more gm) or decrease L (for more speed)
    5. Re-generate netlist with new sizes
    6. Re-simulate
```

## Convergence strategy

| Failure mode | Adjustment | Typical fix |
|-------------|------------|-------------|
| Gain too low | Increase gm/Id (↑W or ↑L) | +50% W on input pair |
| Bandwidth too low | Decrease parasitic C (↓W) or ↑bias current | Trade gain for BW |
| Phase margin too low | Increase Cc or add nulling Rz | +50% Cc |
| Noise too high | Increase W×L product on input devices | +2× area on input pair |
| Power too high | Reduce bias current | ↓Ibias by 30% |
| Output swing too small | Reduce Vdsat (↑W at same Id) | Cascode → folded-cascode |

## Output format

### `analog/<block>/sizing_final.json`
```json
{
  "block_name": "ldo_1v8",
  "iterations": 3,
  "converged": true,
  "final_sizing": {
    "M1": {"W": "40u", "L": "2u", "role": "input_pair"},
    "MP_pass": {"W": "100u", "L": "0.5u", "role": "pass_transistor"}
  },
  "worst_corner": "ss_-40C_3.0V",
  "yield_pct": 100
}
```

### `analog/<block>/corner_results.json`
Written by `eda_spice_corner` — PVT matrix with per-spec pass/fail.

### `analog/<block>/sizing_history.json`
```json
{
  "iterations": [
    {"iter": 0, "changes": "initial", "tt_pass": false, "reason": "gain=45dB < 55dB spec"},
    {"iter": 1, "changes": "M1 W: 20u→40u", "tt_pass": true, "all_corners_pass": false, "worst": "ss_-40C"},
    {"iter": 2, "changes": "Ibias: 20uA→30uA", "tt_pass": true, "all_corners_pass": true}
  ]
}
```

## Stopping conditions

1. **All specs pass across all corners** → SUCCESS
2. **5 iterations without convergence** → STOP, report best-so-far + remaining failures
3. **Fundamental topology limitation** (e.g., single-stage gain capped at 40dB but spec requires 60dB) → STOP, recommend topology change

## Do not

- Do not run all corners on iteration 0 — TT-only is sufficient for initial sanity
- Do not make more than 2 simultaneous changes per iteration — hard to debug
- Do not exceed 5 iterations — if not converging, the topology is likely wrong
- Do not adjust a device that has no sensitivity to the failing spec

## Handoff

- `corner_results.json` → `analog_corner_sweep_check` gate (verification)
- `sizing_final.json` → `/analog-layout` (Step A5)
- If 5 iterations fail → back to `/analog-topology-select` (re-evaluate topology)

## Canonical loop infrastructure (mandatory — shared with all closed-loop skills)

The sizing loop (Iteration 0..N) MUST be driven by the two shared closed-loop
primitives so the analog W/L sweep obeys the SAME convergence / plateau /
regression policy and the SAME runaway / dedup guard as the digital fix loops
(hold-fix / drc-fix / eco-plan) — do **not** hand-roll a bespoke iteration
counter or duplicate-sizing check. This sits alongside the existing
"Convergence strategy" table and "Stopping conditions" (5-iteration cap), which
remain authoritative for the device-adjustment heuristics.

**1. `programs/iterative_search.py` — the W/L parameter sweep.**
Model the device sizes as a typed `SearchSpace`; `IterativeSearch` proposes the
next sizing trial and `ConvergenceChecker` classifies the worst-corner yield
score history (`CONVERGED` / `PLATEAU` / `REGRESSION` / `EXHAUSTED` /
`CONTINUE`):

```python
import iterative_search as it
space = it.SearchSpace([
    it.Dimension("W_in_um",  "continuous", lo=1.0, hi=200.0),   # input-pair width
    it.Dimension("L_in_um",  "continuous", lo=0.15, hi=4.0),
    it.Dimension("Ibias_uA", "continuous", lo=1.0,  hi=100.0),
    it.Dimension("Cc_pF",    "continuous", lo=0.1,  hi=10.0),
])
# target = 100% worst-corner yield; maximize toward it
checker = it.ConvergenceChecker(target=100.0, tolerance=0.0, patience=2)
search  = it.IterativeSearch(space, checker, maximize=True, seed=7,
                             max_rounds=5)        # mirrors the 5-iteration cap
def evaluate(point):          # caller runs analog-netlist-gen + eda_spice_corner here
    return worst_corner_yield_pct                 # higher is better
outcome = search.run(evaluate)                    # outcome.status / best_point / rounds
```

`IterativeSearch` constructs an `AdmissionGuard(bounds=space.bounds(),
max_iterations=max_rounds)` internally, so each proposed sizing point is already
runaway- and dedup-guarded via `search.propose()` / `search.run()`. The
`max_rounds=5` budget enforces the existing "Do not exceed 5 iterations" rule
in code rather than by convention.

**2. `programs/loop_admission_guard.py` — admit each sizing trial BEFORE the SPICE run.**
A full PVT corner sweep is the expensive step; gate every proposed sizing
through `AdmissionGuard.admit()` first so a duplicate or runaway sizing never
launches `eda_spice_corner`:

```python
import loop_admission_guard as g
guard = g.AdmissionGuard(
    bounds={"W_in_um": (1.0, 200.0), "Ibias_uA": (1.0, 100.0)},
    caps={"Ibias_uA": 100.0},               # REJECT a runaway bias current
    max_iterations=5)                        # hard RUNAWAY iteration budget
res = guard.admit({"W_in_um": 40.0, "L_in_um": 2.0, "Ibias_uA": 30.0})
if res.admitted:
    run_corner_sweep(res.proposal)           # res.proposal is post-clamp / safe
# else res.reason in {DUPLICATE, RUNAWAY_CAP, RUNAWAY_ITERATION_BUDGET}
```

CLI one-shot decision (exit 0 = ADMITTED, 1 = REJECTED):

```bash
python3 programs/loop_admission_guard.py decision.json
# decision.json: {"bounds":{...},"caps":{...},"max_iterations":5,
#                 "history":[...prior sizings...],"proposal":{...}}
```

`canonical_fingerprint(proposal)` (md5, key-order- and float-noise-stable) is
the dedup key — re-proposing a W/L/bias combination already simulated this
session is rejected with `reason="DUPLICATE"` instead of burning another
multi-corner SPICE sweep. The `sizing_history.json` output should record each
admitted point's fingerprint so the dedup set is reproducible across resumes.

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/analog-sizing-loop/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
