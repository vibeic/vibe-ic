# u_hawaii_adc × sky130A — regression re-run RESULT (plugin v1.9.86)

**Verdict:** PASS

> Scope: this cell PASSED earlier on 1.9.84 (PASS=8 FAIL=0 MISSING=0). This round re-establishes
> it on **1.9.86**. Two gates now matter and both are GREEN:
> `flow_compliance_check.py --strict` → **PASS=8 FAIL=0 MISSING=0, Overall PASS, exit 0**, and the
> deliverable gate `run_output_completeness_check.py` → **COMPLETE, exit 0**. The only change this
> round was an **execution-gap closure**: re-running the analog orchestrator so its aggregated
> verdict describes today's artifacts. No constraint relaxed, no check widened, no artifact
> hand-edited, no stub emitted.

## THE TRIPLE — measured on 1.9.86 (exact commands + exit codes)
```
# gate 1 — flow compliance
python3 …/vibe-ic/1.9.86/programs/flow_compliance_check.py \
        /home/reyerchu/_c_o_u_hawaii_adc_sky130A_run --strict
  Steps: 63 total (8/10 executed PASS, 0 DEFERRED, 2 VACUOUS-PASS excluded)
  PASS=8  FAIL=0  MISSING=0  WAIVED-DEFERRED=0  SKIPPED=53  VACUOUS-PASS=2
  Overall: PASS  (strict=True)                                    # exit 0

# gate 2 — deliverable completeness (my mandated final act)
python3 …/vibe-ic/1.9.86/programs/run_output_completeness_check.py \
        /home/reyerchu/_c_o_u_hawaii_adc_sky130A_run
  [PASS] COMPLETE — deliverable RESULT.md present                 # exit 0
```

## THE FINDING — a gate got sharper, the design did NOT get worse
On first measure with 1.9.86, `flow_compliance_check` was still PASS=8/0/0, but
`run_output_completeness_check` came back **FAIL exit 1 — DELIVERABLE_CONTRADICTS_ORCHESTRATOR**:
RESULT.md claimed PASS while `reports/phase3/analog_one_shot.json` recorded `verdict='FAIL'`.

Root cause — **stale orchestrator verdict**, not a regression:
- `analog_one_shot.json` was dated **2026-08-03 22:45**. Its FAIL came from
  `A4_corner_sweep` (`A4_NETLIST_ABSENT`) and `A6_block_pv` (`A6_PV_DRC_NO_EVIDENCE`) — i.e. the
  netlists / corner_results / DRC reports did not yet exist when the orchestrator ran.
- Those artifacts were produced **later, on 2026-08-04** (netlists `*.sp` 08:41–00:04,
  `corner_results.json` 08:42/08:50, `drc.report`/`lvs.report` 08:45). The orchestrator's
  aggregated verdict was simply never regenerated after them.
- 1.9.86's deliverable gate now globs deep enough to READ `reports/phase3/analog_one_shot.json`
  (it previously globbed one level too shallow to see it). So the sharpened gate legitimately
  turned the cell red on a stale FAIL. **That is the gate working.**

Ruled out "design got worse" with a control: the per-step gates read against **today's**
artifacts all PASS —
`analog_a3_netlist_gen_check` 2/2 clean, `analog_a4_corner_sweep_check` 2/2 clean,
`analog_a6_block_pv_check` **2/2 DRC-0 + LVS-match** (real magic 8.3.679 `DRC violations: 0`,
real netgen `Circuits match uniquely`). The silicon evidence is real and passing; only the
aggregation file was stale.

## THE CLOSURE — re-ran the flow's own program (execution-gap)
```
python3 …/vibe-ic/1.9.86/programs/analog_one_shot_runner.py \
        /home/reyerchu/_c_o_u_hawaii_adc_sky130A_run          # exit 0
  A1..A8 PASS (both blocks delta_sigma, ldo); A9 WAIVED (no HIL hw_measurements.json)
  verdict: PASS_WITH_WAIVERS
```
Run **without** `--allow-deterministic-stubs`. Verified afterward: **no file under
`phase3/analog/` was modified today (2026-08-05)** and **no `deterministic_stub` marker exists**
anywhere in the analog tree — the runner only re-read the real 2026-08-04 artifacts and
rewrote the aggregated verdict. The stale FAIL json is preserved at
`/tmp/analog_stale_backup.json` for audit.

### BEFORE / AFTER triple
| | flow PASS/FAIL/MISSING | orchestrator verdict | completeness gate |
|---|---|---|---|
| before (1.9.86, round start) | 8 / 0 / 0 (exit 0) | **FAIL** (stale, 08-03) | **FAIL** exit 1 |
| after  (orchestrator re-run) | 8 / 0 / 0 (exit 0) | PASS_WITH_WAIVERS | **PASS** exit 0 |

`PASS_WITH_WAIVERS` (not FAIL) is compatible with the RESULT.md headline; the completeness gate
only forbids a PASS shipped over an orchestrator **FAIL**.

## WHAT I DID NOT VERIFY
- I did not re-execute the analog SPICE corner sims or the magic DRC / netgen LVS from scratch;
  I relied on the real 2026-08-04 tool artifacts already on disk (their gate checks pass today).
- I did not re-run Phase 1 / Phase 2 digital steps — they are legitimately N/A / SKIPPED for this
  mixed-signal ΔΣ ADC (analog-owned routing), as established in the prior round and unchanged.
- A9 (hardware-in-the-loop) remains WAIVED — no on-hardware `hw_measurements.json`; not required
  for this deliverable.

Prior 1.9.82 report preserved at `RESULT_round3_v1.9.71.md.bak`; stale orchestrator json at
`/tmp/analog_stale_backup.json`.
