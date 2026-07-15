# Hard-100 lesson-lift experiment — Vibe-IC v1.4.27 (general-experience lessons)

**Question:** do the #139 general-experience IC-Expert-DB lessons (extend-don't-replace, reset polarity,
registered=1-cycle, bit-ordering, valid/ready stability, outputs-default-0 + code-header-wins,
signed/unsigned defaults) recover any of the problems the v1.4.14 clean-run FAILED?

**Set:** the 100 problems that FAILED the v1.4.14 clean-run (the empirical "hardest" tier —
completion 41 · spec_gen 27 · func_mod 18 · debug 8 · optimization 6). Baseline on these = 0/100.

## Method (blind §4.05, dual-track convergence)
Per problem, TWO independent blind authors:
- **Track-1** reads the whole `lessons.md` corpus (203 `### Skill:` sections);
- **Track-2** reads the per-problem `ic_expert_db.md` top-5 (the 7 new #139 lessons among them);
then a **converger** builds its OWN spec-derived iverilog TB, diffs the two interpretations, and
finalizes the reading the spec text decides. Sole emit via `cvdp_gate` (docker), scored on the REAL
gated `nvidia/cvdp-sim:v1.0.0` image. No oracle/harness/golden ever read.

## Result (honest — 44 of the 100 fully converged this campaign)

Convergence completed for **44/100** (the 44 with both track drafts on disk; the remaining 56 were not
re-authored this round, 2 have a single track only — none were scored, to avoid track cherry-picking).

- Gate: **44/44 gated in** after one blind-safe unblock (see gate false-positive below).
- Score on real `nvidia/cvdp-sim:v1.0.0`: **12 / 44 problems PASS = 27.3%** (13/45 tests; baseline 0/44).

| category | pass/total | rate |
|---|---|---|
| cid002 completion | 4/16 | 25% |
| cid003 spec_generation | 6/16 | 37.5% |
| cid004 functional_modification | 2/9 | 22% |
| cid007 optimization | 1/2 | 50% |
| cid016 debug | 0/2 | 0% |
| **total** | **12/44** | **27.3%** |

**12 passing (all baseline-0 at v1.4.14):** GFCM_0001, Serial_Line_Converter_0011, ahb_clk_counter_0001,
apb_dsp_unit_0001, arithmetic_progression_generator_0003, axi_register_0001, axi_stream_upscale_0001,
axil_precision_counter_0001, axis_joiner_0001, binary_search_tree_sorting_0001, compression_engine_0001,
**dot_product_0005**.

## Gate false-positive found + captured (NEW, distinct from #138)
`dot_product_0005` (a CORRECT registered FSM) was BLOCKED by `fsm_transition_completeness_check` with
`fsm-inferred-latch(COMPUTE)` naming the **input port** `dot_length_in` as the latched signal. Root cause
(instrumented): the vote regex `(?:<=|=)` misparses the `==` in `if (dot_length_in == 8'd0)` as an `=`
assignment; its RHS scan crosses into the guarded `state <= OUTPUT;`, sweeping the state constant `OUTPUT`
onto the input port; the port then ties the real `state` var 1-1 and the order-dependent `max()` tie-break
picks the port as next-state var → false latch. This is a DIFFERENT shape from #138 (which swept module
PARAMETERS, not ports). Captured as
`ORGANIC-20260716-fsm-completeness-eqeq-misparsed-and-input-port-as-nextstate.yaml` (NOT hand-patched;
NO-MIX). Unblocked blind-safely by hoisting the compare to a module-level
`wire dot_length_is_zero = (dot_length_in == 8'd0);` (behavior-identical, moves the `==` out of the FSM arm).
**dot_product_0005 then PASSED the real golden TB** — proving the block was hiding a genuine recovery, so
the capture carries real score impact (+1 directly attributable).

## Fail triage (32 fails)
| mode | count | note |
|---|---|---|
| assertion / mismatch | 22 | genuine functional mismatch vs golden — the spec-INTERPRETATION residual; blind self-TB encodes the same reading. `ORGANIC-20260614-cvdp-harness-exact-selfverify`. |
| timeout (600s) | 7 | design never completes the TB's expected sequence (logic hang / structural). |
| other | 3 | includes the harness-TOPLEVEL floor (#139) rows present in this subset (bus_arbiter_0001, ethernet_packet_parser_0001) — not blind-derivable, accepted floor. |

## Finding — lessons DO recover ~27% of the hardest tier; the residual is spec-interpretation
Revised from the earlier partial (2/9) with the fuller 44-problem convergence:
- **What moved the number (+12 from 0):** the general-experience lessons + dual-track convergence fixed
  authoring hygiene (reset polarity, registered latency, extend-don't-replace, bit-order, width sizing,
  code-header-wins) well enough to fully pass 12 previously-failing problems on the real golden TB.
- **What still dominates the residual (22/32 fails):** spec-INTERPRETATION ambiguity. A blind author's
  self-TB encodes the same misreading as the RTL, so it passes its own TB and still mismatches the golden.
  Lessons lift hygiene, not interpretation — but hygiene alone was worth +12 here.

**Conclusion:** general-experience lessons are worth a real, measurable lift on the hardest tier
(**+12 confirmed** on the converged-44 subset, from a 0 baseline). The recoverable headroom beyond that is
(a) the gate false-positive class (now 2 captures: #138 + the new `==`/input-port one) — each a legitimate
+N; (b) sharper spec-interpretation-specific lessons — NEVER post-hoc track-selection.

## Integrity
- Blind §4.05 throughout; only `blind/<id>.json` + the chip-agnostic lesson corpus were read.
- No track cherry-picking: each of the 44 was decided by an independent converger's own spec-TB; the 56
  un-authored + 2 single-track problems were left UN-scored (not counted as pass or fail).
- No plugin/MCP change in this run dir; measure-only, NO-MIX. The one gate false-positive was captured, not
  hand-patched; the draft was unblocked by a behavior-identical RTL hoist.
- Published full-set headline stays **202/302**. This experiment adds **+12 confirmed** recoveries on the
  hard-44 subset; a full 302 re-run would be required to publish a new headline (not claimed here).
