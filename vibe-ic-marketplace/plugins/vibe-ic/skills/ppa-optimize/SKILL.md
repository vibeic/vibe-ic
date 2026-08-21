---
name: ppa-optimize
description: Propose bounded, reversible actuator moves that trade power, performance and area against each other — placement density, clock period, synthesis effort, buffering, floorplan aspect — each with the effect it predicts, the remeasurement that would falsify it, and its rollback. Use when the user says "improve PPA", "close timing", "shrink area", "reduce power", "what should I try next", or when a closure loop needs its next candidate.
---

# PPA Optimize

## The boundary this skill lives inside

This skill produces a **structured proposal**. It never produces a gate
verdict, and it never reports that a move worked. A proposal becomes a result
only when `ppa-measure` re-reads the artefacts afterwards and a deterministic
program — `_ppa/feasibility.py` and `_ppa/pareto.py` per
`docs/PPA_INTERFACES.md` §4 — compares the records.

That ordering is the whole point. The failure mode it prevents is the one that
looks most like success: a model proposes a change, the change is applied, and
the same model reports the improvement it predicted. Nothing in that loop is a
measurement, and the number it produces is indistinguishable from one that is.

Every candidate this skill emits therefore carries four things that make it
falsifiable: the actuator, the predicted effect, the remeasurement that would
refute the prediction, and the rollback.

## When to use

Trigger when the user:
- Has measured PPA and wants the next thing to try
- Is missing a target on one axis and wants to know what it costs on the others
- Needs candidates for a closure controller (`_ppa/closure.py`) to actuate
- Wants the trade-off surface rather than one recommendation

## Inputs to gather

1. The baseline: canonical metric records from `ppa-measure`, with their scope
2. The target: which metric, which threshold, at which scope
3. The actuators that are legal here — some designs forbid touching the RTL,
   some forbid moving the clock period, some allow only PnR configuration
4. The budget: how many tool iterations and how much wall clock the loop may spend
5. What must not regress: the axes that are already at their limit

## Workflow

1. **Pin the baseline scope first.** A proposal that improves a post-place
   number and is checked against a post-route number has not been checked at
   all. State the baseline scope on its own line and require every candidate's
   remeasurement to name the same one.
2. **Enumerate actuators, not outcomes.** "Reduce area 5%" is a wish. "Placement
   density 0.62 to 0.58" is an actuator: it is a thing that can be moved, its
   move can be undone, and the move is visible in a config diff.
3. **Predict, in the units of the metric record.** A prediction in words cannot
   be refuted. A prediction of `+0.05 ns` on `timing.setup.wns_ns` at a named
   scope can be.
4. **Attach the remeasurement.** Name it, with its scope, before the move is
   made. A remeasurement chosen after seeing the result is a different
   experiment from the one that was proposed.
5. **Attach the rollback.** Every candidate states the exact state the design
   returns to. A move with no rollback is not a candidate; it is a commitment,
   and it belongs in a different conversation.
6. **Keep the triple, do not collapse it.** Rank candidates on the frontier over
   power, performance and area. A single weighted score hides which axis paid.
7. **Spend the budget explicitly.** State how many iterations the proposal
   assumes, so a controller can refuse it before it starts rather than halfway.

## Do not

- Do not report an improvement. Report a prediction, and the remeasurement that
  would refute it.
- Do not compare a candidate against a baseline at a different stage, corner,
  mode or activity basis. That comparison is `UNDETERMINED`.
- Do not propose deleting, resizing or reclaiming spare / `dont_touch` / ECO
  cells to recover area. That reserve is a deliberate investment and removing it
  is caught later by `spare_cell_preservation_check.py`. Report the spare pool
  separately as reserve, not as overhead. See the `design-for-eco` skill.
- Do not propose relaxing a rule deck, waiving a check, or hand-editing a
  layout. An improvement obtained that way is worth less than the number it replaces.
- Do not fill a required field with a placeholder. `X_no_placeholder_fields`
  catches it, and it should: an unfillable rollback field means the candidate is
  not reversible and the honest report of that is a sentence, not a dash.

## Output format

The deliverable is one markdown proposal. The template below is the whole shape.

    # PPA Optimization Proposal — <design>

    Verdict authority: _ppa/feasibility.py - this proposal states no pass/fail of its own.

    ## Summary
    <what is being missed, on which axis, at which scope>

    Baseline scope: post_route_extracted / ss / 1.62 V / 125 C / rc_corner=max
    Budget: 6 PnR iterations, 4 h wall clock

    ## Proposal

    ### C1 — loosen placement density
    Actuator: PL_TARGET_DENSITY 0.62 -> 0.58
    Expected effect: timing.setup.wns_ns +0.04 to +0.07 ns; area.core_um2 +1 to +2%
    Remeasure: run /ppa-measure at post_route_extracted, same scope as baseline
    Rollback: restore config revision 4f21 and re-run PnR from the checkpoint
    Costs: 1 PnR iteration

    ### C2 — raise synthesis effort on the critical module
    Actuator: synthesis effort low -> high, scoped to <module>
    Expected effect: timing.setup.wns_ns +0.02 to +0.05 ns; power.total_mw +0 to +3%
    Remeasure: run /ppa-measure at post_route_extracted, same scope as baseline
    Rollback: restore the previous synthesis script revision
    Costs: 1 synthesis + 1 PnR iteration

    ## Frontier

    | candidate | performance | power | area | dominated by |
    |---|---|---|---|---|
    | C1 | + | 0 | - | none |
    | C2 | + | - | 0 | none |

    ## Evidence

    | artefact | sha256 | tool |
    |---|---|---|
    | phase3/stage3/sta/sta_mcorner_ocv.rpt | sha256:0a5b93f6 | opensta |

    Next: run /ppa-measure

Baseline and candidate numbers travel as canonical records, never as loose
figures in the table above:

```json
{
  "schema": "vibeic.ppa.metric.v1",
  "metric": "timing.setup.wns_ns",
  "status": "MEASURED",
  "value": -0.124,
  "unit": "ns",
  "scope": {"stage": "post_route_extracted", "mode": "functional",
            "process": "ss", "voltage_v": 1.62, "temperature_c": 125,
            "rc_corner": "max", "clock": "clk", "check": "setup"},
  "source": {"path": "phase3/stage3/sta/sta_mcorner_ocv.rpt",
             "sha256": "sha256:e61d2c88", "tool": "opensta",
             "parser": "ppa_metric_extract.py"}
}
```

Serialize with `programs/_ppa/canonical_json.py` and nothing else.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/ppa-optimize/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed, exit 2 =
the checker could not read one of its own inputs and reached no conclusion.

**Your task is not complete until the audit returns PASS.**
