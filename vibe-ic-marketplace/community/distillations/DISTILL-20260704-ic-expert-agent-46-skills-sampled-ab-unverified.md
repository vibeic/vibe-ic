# Sampled blind A/B verification of the 46 new ic-expert-agent.md skill sections (v1.3.10) — result: 0/8, tier UNVERIFIED not Tier-1

**Filed by:** benchmark-agent · **Plugin:** v1.3.10 · **Method:** zero-oracle blind A/B at the real CVDP docker/cocotb oracle, same methodology as `DISTILL-20260704-cvdp-blind-absorbable-conventions.md`

## What this corrects

Commit `cce512f06` (v1.3.10) landed 46 new `### Skill:` sections in `agents/ic-expert-agent.md`, cross-checked against the plugin only by **textual overlap** ("is this pattern already documented anywhere") — not by empirical blind-pass-rate lift. That is a much weaker bar than the Tier 1/2/floor classification used in the prior distillation, which requires a blind (zero-oracle, single-shot) author WITH the lesson injected to actually flip a failing design to a PASS at the real oracle.

This run applies that real bar to a sample of 8 of the 46 (chosen for diversity across ic_classes: 64b66b decoder, run-length encoder, clock-jitter detector, serial-line converter, sync LIFO, BST rank-search, skid buffer, sync-serial-parity link).

## Method

For each of the 8 sampled designs: one blind agent authored RTL from the spec alone (condition A, baseline, no lesson), a second independent blind agent authored RTL from the same spec PLUS the general (benchmark-ID-scrubbed) lesson text injected as a hint (condition B). Both sets were scored via the real CVDP harness (`cvdp_benchmark/run_benchmark.py`, docker + cocotb, local-import mode) against the actual hidden testbenches.

## Result: 0/8 pass in BOTH conditions — no verified Tier-1 (blind-lift) case in this sample

| design | A failure | B failure | verdict |
|---|---|---|---|
| 64b66b_decoder_0011 | wrong decoded data | wrong decoded data (different value) | no lift — both wrong |
| run_length_0007 | `data_out` mismatch | **identical** assertion, identical values | lesson had zero measurable effect |
| clock_jitter_detection_module_0003 | jitter flag mismatch | **identical** assertion | lesson had zero measurable effect |
| sync_lifo_0010 | harness `CalledProcessError` (infra) | same infra error | inconclusive — infra-blocked, not a code signal |
| binary_search_tree_sorting_0014 | latency off by +2 (7 vs 5) | latency off by −1 (4 vs 5) | **directional improvement, still fails** — classic Tier-2 pattern (rule correct, insufficient alone) |
| Serial_Line_Converter_0011 | missing signal `parity_out` | missing signal `alt_invert_state` (different) | different bug surfaced, not resolved |
| skid_buffer_0001 | `AttributeError: no child object named i_data` | (same interface-mismatch class) | **benchmark-floor**: the prompt's own code template names the port `data_i`, but the hidden test + golden reference use `i_data` — the prompt contradicts its own oracle; no blind author can get this from the prompt alone |
| sync_serial_communication_0014 | harness `CalledProcessError` (infra) | ran to a real (wrong) functional assertion | inconclusive — A didn't even reach functional scoring |

## Honest conclusion

- **0 of 8 verified Tier-1** (full blind-pass lift) in this sample — worse than the prior campaign's 7/33 (~21%) verified rate, though n=8 is too small to treat as a precision estimate.
- **1 of 8 (BST)** shows a genuine directional signal (the lesson changed the failure in the direction the convention predicts) without reaching a full pass — this is the Tier-2 "converge-aid, not single-shot-sufficient" pattern from the prior campaign, not a floor case.
- **1 of 8 (skid_buffer)** is a genuine **benchmark-floor defect** (prompt template contradicts its own hidden oracle) — unrelated to lesson quality, unfixable by any skill-file change.
- **2 of 8** hit harness infrastructure errors uncorrelated with the lesson (inconclusive, not attributable either way).
- **2 of 8** show literally no differential effect — the injected lesson did not change the author's output in any way that mattered to the test.

## What this means for the 46 sections landed in v1.3.10

They should be treated as **UNVERIFIED / documentation-only** (a fresh author who reads them may or may not do better), **not** as Tier-1 "verified blind-absorbable" convention. No section is retracted — documented craft knowledge has value even unverified — but none should be cited as a proven pass-rate lift until run through this same empirical A/B at a larger sample.

## Follow-up (not done in this session — scope/time)

Full empirical A/B tiering of all 46 (not just this 8-item sample) needs ~46×2 blind-authoring + scoring runs. Given the n=8 sample already shows the heuristic-documented set skews toward Tier-2/floor rather than Tier-1, a full run should be budgeted as its own benchmark campaign rather than folded into an ad-hoc session.
