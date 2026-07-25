# Capture: L22 measurable coverage-goal emitter

Authored on 8HD-8 against **plugin v1.6.1** (the tree actually exercised).
Repo `main` is **v1.5.60**; the consumer gate
`l22_verification_plan_measurable_check.py` is NEW in v1.6.1 and does not
exist on `main`, so the gate-coupled tests SKIP here and were run against
the v1.6.1 tree. **Apply to a v1.6.1-or-later base.**

## The defect

Measured on `spm`, plugin v1.6.1, phase1 doc mode:

```
L22_VERIFICATION_PLAN.json : fields.coverage_goals = []   (0 of 0 measurable)
                             prose_item_count      = 6
                             verification_plan_present = "implicit"
input doc L7, line 45      : "Toggle / branch coverage(資訊性) | ≥ 95%"
```

The gate's own F2 check FINDS the target — it reports
`coverage_target_hits_input_docs: 1` — and then FAILs the run with
TARGET_OUTSIDE_CONSUMING_LAYER because nothing ever writes it into L22.
The detection is already a solved deterministic problem; only the
write-back is missing. That is what makes this Bucket A.

The emitter imports **the gate's own `_COVERAGE_TARGET_RE`** and the same
`framed_hits()` helper rather than reimplementing the predicate. A private
predicate here could drift and emit goals the gate still rejects.

## The write-LOCATION is load-bearing

`l_doc_consumer_contract.l_doc_fields()` merges the nested `fields`
payload OVER the top level (`merged.update(inner)`). Writing
`coverage_goals` at the top level while `fields` carries its own empty
list is a SILENT NO-OP: the emitter prints success and the gate still
reads `[]`. That was measured during development — the first run printed
`lifted 1 measurable coverage target(s)` while the gate still reported
`carries 0 measurable coverage_goals[]`. It has its own regression test
(`test_writes_into_the_payload_the_consumer_reads`).

## Bidirectional evidence

| direction | result |
|---|---|
| defect (emitter not run) | gate `FAIL`, `TARGET_OUTSIDE_CONSUMING_LAYER` |
| fixed (emitter run) | gate `PASS`, no blocking findings |
| design states no target | emits nothing; gate keeps FAILing (correct) |
| existing goal present | never modified; re-run is idempotent |
| target marked informational | `signoff_gate: false` preserved |

Measured end-to-end on the real design (host 8HD-8, image
`vibeic-eda:0.2.29` = `sha256:45fd4d622fe1755f...`):

```
gate BEFORE  exit 1  [FAIL] TARGET_OUTSIDE_CONSUMING_LAYER
emit                 lifted 1 measurable coverage target(s) — branch coverage>=95.0% (informational)
gate AFTER   exit 0  [PASS] 1 coverage goal(s) with a comparable numeric target
```

and it unblocked Step P0 of the phase2 flow audit
(`final_audit` FAIL -> WAIVED, phase2 verdict `PASS_WITH_WAIVERS`).

22 tests, all passing.

## `signoff_gate` is deliberate

A design may state a measurable target and explicitly mark it
informational — the spm input does exactly that ("資訊性", "非 sign-off
gate"). Emitting it as blocking would invent a sign-off condition the
design never asked for; dropping it would lose a stated requirement. So
it is emitted WITH the qualifier recorded and the qualifying phrase kept
in `evidence` for audit. Default is `true` (treat as binding) — the
safer direction when no qualifier is present.

## Wiring

Run it before the semantic layer gates in
`phase1_doc_one_shot_runner.py`, in the same `_LAYER_REPAIRS` loop as
`l1_param_bus_width_resolve` (see the sibling capture branch
`capture/l1-parametric-bus-width-resolve`, whose
`_capture_patches/02_runner_wiring_against_v1.6.1.patch` introduces that
loop). The two captures are independent programs but share one wiring
site; land the wiring once.
