# canonical_samples/ — vetted defect-audit data (NOT an answer bank)

Input to the scorer's **suspected-defective-golden** audit
(ORGANIC-20260605-scorer-disagreeing-golden-flag): when a problem FAILs and a
vetted canonical sample exists here, the scorer additionally runs the
canonical against the hidden golden; a high mismatch rate (>=50%) flags the
problem `suspected_defective_golden` — DISCLOSURE-ONLY (verdict and pass@1
unchanged; dual-reported like the non-discriminating-TB audit).

**Vetting policy (core-agent gate).** A sample enters this tree only when ALL
hold: (1) the prompt admits a CANONICAL reading (e.g. a fix-the-bug prompt
with a unique correct repair); (2) multi-campaign evidence shows the golden
consistently rejects that reading at high mismatch rates; (3) the core agent
re-derives the sample from the prompt alone and re-verifies the rejection
live; (4) the sample is committed with its evidence in the commit message.

**Blindness.** These files are dataset-adjacent SOLUTION KNOWLEDGE: authoring
and close-loop agents must NEVER read this tree (enforced by
`programs/blindness_audit.py`, which flags any transcript access to a
`canonical_samples/` path, and stated in the blind instructions). Only the
host scorer touches it, at scoring time.

Layout: `<bench>/<Prob>.sv` (bench = BENCHMARK_REGISTRY key).
