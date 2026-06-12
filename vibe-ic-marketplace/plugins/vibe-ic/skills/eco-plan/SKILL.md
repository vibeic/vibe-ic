---
name: eco-plan
description: Plan an Engineering Change Order (ECO) — a late-stage design change that minimizes disruption to an already-placed-and-routed netlist. Use when the user says "need an ECO", "late-stage fix", "spin without re-place-and-route", "metal-only fix", or describes a bug found after P&R.
---

# ECO Plan

Given a change request against a netlist that has already been placed and routed, produce an ECO plan that minimizes disruption, area impact, and risk. Distinguish metal-only ECOs (re-route only) from base-layer ECOs (cell changes).

## When to use

Trigger when the user:
- Has taped out or is near tape-out and must fix a bug
- Wants to avoid full re-synthesis + P&R
- Asks whether a fix can be metal-only
- Needs a functional ECO plan with spare-cell usage

## Inputs to gather

1. Description of the bug or change
2. Current netlist (post-P&R) or at least the affected module
3. Spare cell map, if available
4. Constraint: metal-only vs base-layer allowed
5. Urgency and acceptable area/timing impact

## Planning workflow

1. **Localize the change** — identify the minimal RTL region that must change
2. **Predict impact** — how many gates change, what's the delta on timing-critical paths
3. **Check spare cells** — can the new logic be built from nearby spares?
4. **Metal-only feasibility** — if yes, produce a re-route-only plan; if no, flag base-layer need
5. **Risk assessment** — list the paths that could get worse and the tests that must re-run
6. **Write the plan** — step-by-step for the P&R tool

## Output format

```
# ECO Plan — <bug/change id>

## Change summary
<one paragraph>

## Classification
- Type: functional ECO / timing ECO / metal-only
- Risk: low / medium / high
- Estimated gate delta: +N / -M cells

## Affected region
- Module(s): ...
- Critical paths touched: ...

## Spare cell plan
| Need | Size | Nearest spare | Distance |
|------|------|---------------|----------|
| ...  | ...  | ...           | ...      |

## Step-by-step
1. ...
2. ...

## Regression to re-run
- [ ] Gate-level sim of <test>
- [ ] STA with updated SDF
- [ ] DRC/LVS spot check in affected region

## Fallback if metal-only fails
<plan B>
```

## Technical basis

Grounded in agentic EDA ECO research and industrial spare-cell methodologies. The AI-native contribution is fast triage: deciding in minutes whether a fix is metal-only, which historically required a senior engineer's intuition plus a day of tool runs.

## Do not

- Do not claim metal-only feasibility without checking spare availability
- Do not skip the regression list — ECOs are where silent bugs hide
- Do not propose changes that violate the sign-off timing margin without flagging it

## Canonical loop infrastructure (mandatory — shared with all *-fix loops)

When an ECO is iterated (try a metal-only routing/spare-mapping variant →
STA/DRC spot-check → adjust → retry), that loop MUST be driven by the two
shared closed-loop primitives so every fix loop in Vibe-IC obeys one
convergence / plateau / regression policy and one runaway / dedup guard —
do **not** hand-roll a bespoke retry counter or duplicate-variant check.

**1. `programs/iterative_search.py` — the ECO variant sweep.**
Model the ECO knobs as a typed `SearchSpace`; `IterativeSearch` proposes the
next spare-mapping/route trial and `ConvergenceChecker` classifies the
score history (e.g. worst-slack or residual-violation count):

```python
import iterative_search as it
space = it.SearchSpace([
    it.Dimension("spare_gates", "integer", lo=0, hi=64),     # spares to consume
    it.Dimension("detour_um", "continuous", lo=0.0, hi=200.0),
    it.Dimension("metal_only", "boolean"),                   # metal-only vs base-layer
])
checker = it.ConvergenceChecker(target=0.0, tolerance=1.0, patience=4)
search  = it.IterativeSearch(space, checker, maximize=True, seed=7, max_rounds=20)

def evaluate(point):          # caller runs the P&R ECO + STA/DRC spot-check here
    return measured_worst_slack_ps        # higher (toward target) is better
outcome = search.run(evaluate)            # outcome.status / best_point / rounds
```

`IterativeSearch` builds an `AdmissionGuard(bounds=space.bounds(),
max_iterations=max_rounds)` internally, so each proposed ECO variant is already
runaway- and dedup-guarded via `search.propose()` / `search.run()`.

**2. `programs/loop_admission_guard.py` — admit each ECO trial BEFORE the P&R run.**
A P&R ECO + regression spot-check is expensive; gate every proposed variant
through `AdmissionGuard.admit()` first:

```python
import loop_admission_guard as g
guard = g.AdmissionGuard(
    bounds={"detour_um": (0.0, 200.0)},     # clamp into range
    caps={"spare_gates": 64},               # REJECT a runaway spare-consumption count
    max_iterations=20)                       # hard RUNAWAY iteration budget
res = guard.admit({"spare_gates": 4, "detour_um": 12.0, "metal_only": True})
if res.admitted:
    run_eco_iteration(res.proposal)          # res.proposal is post-clamp / safe
# else res.reason in {DUPLICATE, RUNAWAY_CAP, RUNAWAY_ITERATION_BUDGET}
```

CLI one-shot decision (exit 0 = ADMITTED, 1 = REJECTED):

```bash
python3 programs/loop_admission_guard.py decision.json
# decision.json: {"bounds":{...},"caps":{...},"max_iterations":20,
#                 "history":[...prior variants...],"proposal":{...}}
```

`canonical_fingerprint(proposal)` is the dedup key — re-proposing an ECO
variant already tried this session is rejected with `reason="DUPLICATE"`
instead of consuming another P&R/STA round. This is ADDITIVE: it enforces a
budget + plateau/regression exit around the existing Planning-workflow and
"Regression to re-run" steps without changing any of them.

## ⛔ ECO spare-cell preservation (mandatory)

> ⛔ **ECO spare-cell preservation:** cells/gates/pads carrying the `dont_touch` /
> `keep` attribute (or otherwise tagged spare/ECO) are RESERVED for metal-only
> ECO — they are the very resource this skill consumes. An ECO may legitimately
> WIRE UP spares from the pool, but it must NEVER delete, resize, or re-purpose
> spares it does not use, and must NEVER run `opt_clean` / `clean -purge` /
> `remove_buffers` / area-recovery that strips remaining keep-marked spares or
> reserved pads (those are reserved for the NEXT ECO). The spare pool is a
> renewable reserve, not scratch area to clean up. After the ECO,
> `spare_cell_preservation_check.py` MUST still PASS for all spares not
> intentionally consumed by this ECO (keep attrs intact, 0 unexpectedly
> removed); an unintended drop is a regression — restore it and re-run the
> checker. See the `design-for-eco` skill.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/eco-plan/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
