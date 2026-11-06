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

## Iterate using native results

Run the owning tool on each proposed change and read its native result against
the original limit. Keep the previous design and measured result so you can
revert a regression. Stop when the declared requirements are met, the approved
run budget is exhausted, or another trial cannot resolve the remaining cause.
Report the best measured result and every unresolved requirement. Do not add an
admission record or change a limit to obtain a pass.

## Preserve the ECO reserve

Keep unused spare cells, ECO gates and reserved pads through synthesis and
physical repair. Compare the native netlist or database before and after the
change. No unused reserve instance may disappear, and its keep attributes must
remain intact. A consumed spare must be named in the intended ECO. Restore any
unintentionally removed spare before rerunning the native tools. See
`design-for-eco` for the design intent.
