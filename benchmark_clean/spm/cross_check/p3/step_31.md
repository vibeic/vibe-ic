# Step 31 — ECO (Engineering Change Order — repair loop)

## What ran
Step 30 is conditional: ECO repair runs ONLY if Physical Verification (Step 29) or
post-route STA (Step 22) reported violations that need a late-stage fix. We checked
both gates on OUR design:

- Post-route multi-corner STA (Step 22): setup + hold **MET at SS/TT/FF**, TNS=0
  (worst setup +6.61 ns, worst hold +0.30 ns). No timing violation to repair.
- Physical Verification (Step 29): DRC has 0 real routing/BEOL violations, LVS is
  device-exact (3176/3176 transistors). No physical violation to repair.

With no violation open, there is nothing for an ECO to fix — the same situation the
reference flow recorded: `phase3/stage3/eco/no_eco_needed.flag` ("post-route STA
reports TNS=0 and no WNS violations", no-ECO-needed).

## Metrics side-by-side
| metric | OURS | REF |
|---|---|---|
| Post-route STA | MET all corners, TNS=0 | MET, TNS=0 |
| PV (DRC/LVS) | clean (0 real DRC, LVS device-exact) | clean |
| ECO needed? | **no** | **no** (`no_eco_needed.flag`) |

## Verdict: N/A (no ECO needed; reference shares the same outcome)
ECO is a repair step gated on a prior failure. OUR design passes STA and PV with no
open violation, so an ECO is correctly NOT triggered — exactly as the reference flow
emitted `no_eco_needed.flag`. This is an honest N/A (the step is inapplicable because
the precondition — an open violation — does not exist), not a skipped/pending item.
