# 64b/66b encoder — experience-based floor probe (v1.3.34) — CONFIRMED FLOOR

Tested the hypothesis: can domain/standard experience (IEEE 802.3 Clause-49 64b/66b
block coding) recover a "floor" that the earlier knowledge-class round labeled a
dataset floor? Answer: PARTIALLY the lesson is real, but the target problem has a
genuine prompt-vs-TB CONTRADICTION → it stays a floor. Net benchmark lift = 0.

## What the lesson recovered (real, general)
A general `line-code-encoder` lesson (dual of the shipped `line-code-decoder`):
(1) Type Field = standard BLOCK TYPE by the POSITION of the S/T/Q framing symbol, not
a flat control-bitmap lookup; (2) validate every control-marked lane against the
recognized control-symbol set — an unrecognized symbol makes the block invalid → emit
the module's own default (the zeroed body the data-only path already produces).

- A fresh §4.05-blind author (prompt + given context RTL + this lesson, NO testbench)
  went from failing → **11/13** official cocotb tests on cvdp_copilot_64b66b_encoder_0009.
  Measured, legitimate craft — NOT a no-op.

## Why it is still a FLOOR (the 2 residual fails)
Input control=0xff, data = all /E/ (0xfe):
- The PROMPT's own Example 2 states the body is `56'h1E1E1E1E1E1E1E` (byte-aligned).
- The HIDDEN TB demands `56'h3c78f1e3c78f1e` — the 8x7-bit-PACKED form of 0x1e.
These CONTRADICT. A blind author who trusts the prompt's explicit example (correct
behavior) writes byte-aligned → fails the TB. Passing requires 7-bit packing, which
contradicts the prompt — knowable ONLY by reading the hidden TB (= oracle-peek).
An earlier hand-solution that scored 13/13 did so by choosing 7-bit packing against the
prompt's example (oracle-tainted via RCA); it is NOT a valid §4.05-blind pass.

## Siblings (why no +N is available)
The 64b66b_encoder family's other members are DIFFERENT task types — the control-block
encoder lesson does not apply:
- 0001 (cid003): implement ONLY pure data encoding (trivial data-only).
- 0005 (cid016): bug-fix 3 named bugs (retained data / inverted reset / stuck sync).
- 0022 (cid007): area-optimize an existing correct module, keep equivalence.
So 0009 is the only lesson-applicable problem, and it is a floor.

## Decision
Lesson REVERTED (not shipped): no demonstrated clean-blind benchmark FAIL->PASS. The
lesson text + the passing/failing drafts are preserved in the session scratchpad; it
could be re-added later purely on general-authoring merit, but not as a benchmark gain.
CVDP number unchanged (~243/302). Tool substitution: Icarus 13 in cvdp-sim-pinned.

## The one shipped deliverable of this thread
score_one.py full-302 rescan bug FIXED (v1.3.34): single-design scores now run in
seconds (subset dataset), not ~7 min / 420s-timeout false-FAILs — which is what made
this fast per-problem probing feasible.
