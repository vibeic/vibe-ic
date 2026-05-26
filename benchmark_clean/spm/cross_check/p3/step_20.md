# Step 20 — Routing (DRT violations, component/net counts, layers)

## What ran
OpenROAD detailed-route violation count from `openroad.log` (DRT-0199);
component/net counts and routing layers from OUR vs REF `routed.def`.

## Metrics side-by-side
| metric | OURS | REF |
|---|---|---|
| DRT violations (final) | 0 (`DRT-0199 Number of violations = 0`) | 0 (`DRT-0199 ... = 0`) |
| Components | 249 | 302 |
| Nets | 281 | 330 |
| Pins | 36 | 36 |
| li1 segments | 912 | 1157 |
| met1 segments | 1611 | 2179 |
| met2 segments | 399 | 621 |
| met3 segments | 28 | 31 |
| Top routing layer | met3 | met3 |

## Verdict: BOTH-CLEAN / IN-RANGE
Both routed to ZERO detailed-route DRC violations. Same routing stack (li1 +
met1-3, top layer met3). OUR routing has fewer segments on every layer
(li1/met1/met2 ~0.74-0.79x of REF), proportional to the leaner net count
(281 vs 330). No layer-usage anomaly. Routing clean on both → BOTH-CLEAN.
