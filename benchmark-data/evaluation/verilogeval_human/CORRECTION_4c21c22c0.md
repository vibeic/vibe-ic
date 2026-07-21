# CORRECTION to commit 4c21c22c0's message

Commit `4c21c22c0` (VerilogEval v1.4.81 re-run) claimed of the previous
`verilogeval_human/pass_at_1.json` value:

> "read passed=153, pass_at_1_pct=98.08 — VerilogEval-v2's figure. Human has
> measured 154/156 in every round of this campaign, so the recorded value was
> wrong at the source"

**Both halves of that are wrong, and the error is mine.**

`results/verilogeval/run_cleanroom_v1388_human/` in `vibeic-bench` carries the
v1.3.88 artifact, and it reads `passed: 153, pass_at_1_pct: 98.08`. Its RESULT.md
headline is explicit: *"pass@1 = 153/156 = 98.08% (raw), SINGLE-SHOT"*.

So:

- The 153 was **not** VerilogEval-v2's figure copied across. It was
  VerilogEval-Human's own genuine measured result on plugin v1.3.88.
- It was **not** wrong at the source. It was correct for the run that produced it
  and had simply been superseded — the tracked value was four plugin versions
  stale (v1.3.88 → v1.4.81).
- "154/156 in every round of this campaign" is also too strong: v1.4.68, v1.4.74
  and v1.4.81 all measured 154; v1.3.88 measured 153.

The numbers committed in `4c21c22c0` are unaffected and remain correct —
VE-v2 153/156 and VE-Human 154/156 on v1.4.81, both taken from the runs' own
artifacts. Only the characterisation of the *previous* value was wrong.

Recording this rather than quietly moving on, because the failure mode matters:
a stale-but-honest figure was described as a data defect, which is a more
dramatic claim than the evidence supported. A correction that outruns its
evidence is still a false report.
