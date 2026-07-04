# Full 46-lesson blind A/B verification (v1.3.10 skill sections) — REAL oracle result

**Filed by:** benchmark-agent · **Plugin:** v1.3.10 · **Method:** zero-oracle blind A/B, full 46 (not the earlier 8-sample), scored at the real CVDP docker/cocotb oracle.

This supersedes `DISTILL-20260704-ic-expert-agent-46-skills-sampled-ab-unverified.md` (which sampled only 8 of the 46). All 46 lessons landed in v1.3.10's `agents/ic-expert-agent.md` were now run through the full methodology: one blind author per design with no lesson (condition A / baseline), one independent blind author with the general (benchmark-ID-scrubbed) lesson injected (condition B), both scored against the real hidden CVDP testbenches via `cvdp_benchmark/run_benchmark.py` (docker + cocotb, local-import mode).

## Headline

- **Condition A (baseline, no lesson): 2/46 pass (4.35%)**
- **Condition B (lesson-injected): 5/46 pass (10.87%)**
- **Net lift: +3 designs (+6.5 percentage points)**

## Tier breakdown (all 46 accounted for)

| Tier | Definition | Count | Designs |
|---|---|---|---|
| **Tier 1 — VERIFIED blind-absorbable** | baseline FAILS, lesson-injected flips to full PASS | **3** | GFCM_0001, events_to_apb_0001, word_change_detector_0001 |
| Already-passing-without-lesson | both A and B pass — lesson not needed, no evidence either way | 2 | 32_bit_Brent_Kung_PP_adder_0001, ttc_lite_0001 |
| **Tier 2 — converge-aid (directional improvement, still fails)** | different failure mode, objectively closer to correct (smaller latency error, got past an infra/compile stage, etc.) | **5** | apb_dsp_op_0002, sync_serial_communication_0014, binary_search_tree_sorting_0014, galois_encryption_0001, binary_search_tree_sorting_0001 |
| **Floor** | benchmark defect independent of any lesson (confirmed: prompt template contradicts its own hidden oracle) | **1** | skid_buffer_0001 |
| **Regression** | lesson injection made the outcome WORSE (B failed at an earlier stage than A) | **1** | hmac_register_0001 |
| Ambiguous-different | different failure in A vs B, neither clearly closer to pass | 3 | Serial_Line_Converter_0011, reed_solomon_encoder_and_decoder_0005, wb2ahb_0001 |
| **No differential effect** | identical failure/error in both conditions — lesson had zero measurable impact | **31** | (remaining 31 of the 46) |

3 + 2 + 5 + 1 + 1 + 3 + 31 = 46. ✓

## Honest reading

- Real, measurable, oracle-verified lift: **3 lessons are genuinely Tier-1 blind-absorbable** (GFCM_0001, events_to_apb_0001, word_change_detector_0001). These should be flagged as high-confidence in `ic-expert-agent.md`.
- 5 more show real Tier-2 signal (worth keeping as converge-aids, cut close-loop iteration time, but not single-shot sufficient alone).
- 1 lesson (hmac_register_0001) actually made blind authoring WORSE — this is a signal the lesson's prose may be steering the author toward a MORE complex/fragile structure than the baseline default. Flagged for review/possible revision or removal.
- The large majority (31/46, ~67%) show **zero measurable effect** on this single-shot blind pass rate. This does not mean they are useless — design-craft documentation has standalone value for a human reader, and correctness on a HARD held-out test is a demanding bar — but they should NOT be cited as "verified blind-absorbable" conventions.
- 1 confirmed benchmark-floor case (skid_buffer_0001), unrelated to the plugin.

## Follow-up actions (not yet done)

1. Mark the 3 verified Tier-1 lessons and the 5 Tier-2 lessons in `ic-expert-agent.md` with a captured-by tier annotation (mirroring the Tier-1/2 labeling convention from the prior 33-case campaign).
2. Investigate and likely revise or retract the hmac_register_0001 lesson (regression signal).
3. File skid_buffer_0001's prompt/oracle port-name contradiction as an upstream CVDP dataset defect report (already noted in the sampled-8 distillation, unresolved).
