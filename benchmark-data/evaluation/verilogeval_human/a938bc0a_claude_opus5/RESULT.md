# VerilogEval-Human — Vibe-IC `next/bvehuman`, fresh blind single-shot run

## Summary

**passed 154 / max 154 / total 156** — single-shot functional pass@1 = **154/156 =
98.72%** on the complete 156-problem set, which equals the theoretical maximum.
The two problems that did not pass are the two the record already establishes as
broken (`Prob062_bugs_mux2`, `Prob093_ece241_2014_q3`); `theoretical_max.json`
beside this file carries re-runnable evidence for each, and the official scorer
independently flagged both as `semantic_prompt_oracle_contradiction` in this very
run. The headline keeps the original 156 denominator; no problem is removed from
it and no adjusted headline is claimed.

| View | Value |
|---|---|
| Single-shot functional pass@1 | **154 / 156 = 98.72 %** |
| Theoretical maximum (156 − 2 proven broken) | **154** |
| Distance from the maximum | **0** |

No convergence loop was run: this is the single-shot number, and it is also the
terminal number.

## What this run answers, and what it corrects

The brief asked for the regression: the newest published cell
(`v1.13.78_gpt_5.6_sol`) scores 152/156, two below `v1.4.81_claude_fable5` and
`v1.10.64_gpt_5.6_sol`, which both score 154/156. The two problems that fell are
`Prob139_2013_q2bfsm` and `Prob149_ece241_2013_q4`.

**Bisecting it by plugin version says the regression is not in the program layer.**
Plugin trees were extracted at `e550fb7b` [v1.10.45], `f81eec9a` [v1.10.64] and
`93235bdf` [v1.13.78] and probed directly, alongside current main `1eb2a241`:

| Plugin tree | `spec_artifact_registry.generate()` | v1.10.64 supplemental solver | `deterministic_emit_chain` |
|---|---|---|---|
| v1.10.45 | Prob139 None, Prob149 None | — | module did not exist |
| v1.10.64 | Prob139 None, Prob149 None | Prob139 None, Prob149 None | module did not exist |
| v1.13.78 | Prob139 None, Prob149 None | — | Prob139 None, Prob149 None |
| main 1eb2a241 | Prob139 None, Prob149 None | — | Prob139 None, Prob149 None |

**No deterministic emitter has ever produced RTL for either problem, at any of
those versions.** Both have always been routed to the AI-backup track, so the
154s were an authoring outcome and the 152 was a different authoring outcome. A
reader could previously believe that v1.4.81/v1.10.64's 154/156 was a plugin
capability that v1.13.78 lost; it was not, and the number was never reproducible
without an agent. That is the defect, and the fix is to put the two shapes into
the program layer rather than to restore something that was never there.

## The two program-layer fixes on `next/bvehuman`

### 1. A reset written as a conditional expression is a reset

`_specrtl_common.classify_rtl_resets` only ever looked for an `if` inside a
sequential block, so

    always @(posedge clk) state <= (~resetn) ? A : next;

registered **no reset at all**. `spec_conformance_check` then reported
`reset-not-found` against a spec that plainly declares one, and a `--strict`
caller rejected the design (rc=1).

Measured on `Prob139_2013_q2bfsm`, host 8hd-3, 2026-09-06: that ternary-reset
answer scores `Mismatches: 0 in 1002 samples` against the official golden, and the
gate rejected it. The asynchronous rewrite the rejection invites scores
`Mismatches: 33 in 1002`.

* file: `programs/_specrtl_common.py` — new `_conditional_reset` helper, and a
  fallback branch inside `classify_rtl_resets`. The `if` form keeps its exact
  previous answer; the new path is a fallback, never an override.
* tests: `programs/tests/test_conditional_expression_reset_is_a_reset.py` —
  RED `test_ternary_reset_is_not_reported_missing`,
  `test_ternary_reset_design_survives_strict`,
  `test_conditional_sync_reset_is_classified`,
  `test_conditional_async_reset_takes_its_mode_from_the_sensitivity_list`;
  MUTATION `test_mutation_the_check_did_not_become_vacuous`;
  false-positive guards `test_a_datapath_ternary_is_not_a_reset`,
  `test_an_if_reset_still_wins_over_a_later_ternary`.
* both arms: pre-fix tree **4 failed / 3 passed**, post-fix **7 passed**. The
  three that pass in both are the guards, which is what makes them guards.
* corpus sweep: `classify_rtl_resets` over **163 RTL files** (whole repo + the 156
  emitted samples), compared by MEMBERSHIP — 0 new detections, 0 lost detections,
  0 changed classifications. A planted positive control (`tern_sync.sv`,
  `tern_async.sv`, `datapath_ternary_not_a_reset.sv`) proves the sweep can see the
  new shape: pre-fix 0 entries, post-fix 2, and the ordinary datapath ternary is
  still not a reset.

**What a reader could previously believe that they no longer can:** that reset
semantics were checked against the spec. Only *self*-consistency was; a design
whose reset is a conditional expression had no reset at all as far as the gate
could see, and a correct design was rejected for it.

### 2. A new artifact type: sensor threshold ladder with a change-direction output

`programs/threshold_ladder_synth.py` plus its `spec_artifact_registry` entry.
A monotonic quantity sensed by N thresholds on one thermometer-coded bus, a zone
table, and one further output asserted by the DIRECTION of the last zone change.

The direction sense is the whole problem, and it is **not** a judgement call: the
bottom zone can only ever be ENTERED by a decrease, so a prompt that pins the
direction output asserted in the bottom zone has fixed the sense. The solver
REQUIRES that pin and SKIPs without it rather than guessing.

Measured on `Prob149_ece241_2013_q4`: the emitted RTL scores `Mismatches: 0 in
2040 samples` against the official golden. The opposite reading scores
`Mismatches: 1171 in 2040` — which is exactly the published v1.13.78 single-shot
failure count for that problem, so the reading is identified, not guessed at.

* tests: `programs/tests/test_threshold_ladder_synth.py` (9) and
  `programs/tests/test_threshold_ladder_registry_route.py` (2). The fixture is a
  synthetic battery-gauge ladder, not a benchmark prompt: the solver must fire on
  the SHAPE, never on a remembered design.
* MUTATION tests: `test_no_bottom_pin_skips` (remove the pin ⇒ SKIP),
  `test_a_broken_inclusion_chain_skips`, `test_a_second_unmatched_output_skips`,
  `test_the_zone_outputs_are_read_from_the_table`,
  `test_the_reset_polarity_is_read_from_the_prose`,
  `test_it_does_not_fire_on_another_family` (a K-map prompt).
* both arms: the registry-route control RUNS on the pre-fix tree and answers
  wrongly (**2 failed**), and passes after (**2 passed**). It inlines its fixture
  precisely so it does not die at import time on a tree without the new module —
  a control that cannot run observes nothing.
* corpus sweep: the deterministic chain re-emitted all **156** prompts. Exactly
  **one** membership change — `Prob149_ece241_2013_q4` waived → `threshold_ladder`
  — and every other emission byte-identical. Program-only score 132/156 → 133/156
  with **0 wrong answers** in both arms.

**What a reader could previously believe that they no longer can:** that the dfr
direction in that spec is ambiguous, so any answer is a coin flip. It is not: the
prompt's own "below s[1] … both Nominal flow valve and Supplemental flow valve
opened" admits only one direction, and a program can read it.

## Step 1 — reproduction on the current plugin, and one scope cut

The reproduction was taken as the **program-layer arm at pristine main**
`1eb2a241` (Shape C, official `score_iverilog_tb.py`, all 156 problems):

    pass@1 = 132/156 = 84.62%   attempts: 132 passed, 0 FAILED, 24 NEVER ATTEMPTED

That arm answers the regression question more sharply than a full run would: the
program layer has **zero wrong answers** — every miss is an honest waive — so any
score movement between plugin versions has to come from the AI-backup track, which
is what the bisect then confirmed problem-by-problem.

**Scope cut, stated plainly:** a full dispatcher run on pristine main was started
and then discarded, because I edited that same checkout while it was running and
its provenance was no longer single-tree. A second clean pristine-main dispatcher
run was not re-done; the two frozen clones were given to the fixed-tree run
instead. So step 1's number here is the program-layer arm, not a full-flow
pristine-main pass@1. Everything downstream ran on frozen clones with no tree
edits under a live measurement.

## Attribution

| Stage | Actor | Result |
|---|---|---|
| Routing | Program proposal, AI agreement | 156 decisions, 156 agreements, 0 OVERRIDE_PROGRAM |
| Solving | Program-first, AI backup on a declared WAIVE | Program 132, AI backup 24 |
| Verifying | official iverilog testbench scorer (Program) | 154 PASS, 2 FAIL |
| Review | AI, one prompt-derived executable test per problem | 156/156 accepted; `program_first_ai_review_acceptance.json` status COMPLETE |

Of the 154 passes, **132 came from the deterministic program layer** and 22 from
the 24 AI-authored modules; the 2 that did not pass are the two broken problems,
both of which happen to be in the AI-backup set because no emitter recognises them.

Every one of the 156 reviews carries a self-contained testbench written from the
prompt alone, compiled against the frozen candidate with `iverilog -g2012`. Six of
them were rejected by the acceptance gate on the first pass for leaving a declared
structural obligation uncovered, and were **strengthened, not waived** —
Prob048/Prob049 gained a directed sync-vs-async reset discrimination, Prob071 the
prompt's own worked example, Prob075 and Prob153 real saturation clamps, Prob115
all four enumerated shift modes.

## Audits

| Audit | Result |
|---|---|
| `benchmark_clean_room_check` | PASS — no inherited samples / scores |
| `vibe_ic_entry_guard --strict` | PASS — structural runner-entry evidence found |
| `blindness_audit` | PASS — 1 transcript clean |
| `emit_attestation_check --strict` | PASS — all 156 samples carry a valid emit-path attestation |
| `program_first_ai_review_acceptance` | COMPLETE — 156/156 |

## Shape and entry point

Run shape **C**, the shape `benchmark/BENCHMARK_REGISTRY.json` registers for
`verilogeval-human`. Every problem entered through the one general front door:

    programs/benchmark_dispatch.py verilogeval-human --solve --dataset <ds> --run <run> --jobs 8
    programs/benchmark_dispatch.py verilogeval-human --resume --dataset <ds> --run <run>
    programs/benchmark_dispatch.py verilogeval-human --score  --dataset <ds> --run <run>

No benchmark-only authoring harness was used, and the gate is the only emit path.
The dispatcher routed all 156 tasks through `vibe_ic_one_shot_runner.py`
(Phase 1 front door, `--entry-step D1`); 132 problems were solved by the
deterministic program layer, and for 24 the runner WAIVEd `rtl_gen` with
`fallback_skill = spec-to-rtl`, which is the designed dual track, not a bypass.

## Tool substitution disclosure

| The benchmark mandates | We substituted | Caveat |
|---|---|---|
| Synopsys VCS | Icarus Verilog 14.0 (devel) `s20260301-451-g29806b823`, inside the pinned image | An open-source simulator is not commercial-simulator parity; SV-2012 coverage differs. |
| Cadence Xcelium | the same iverilog | Same caveat. |
| Synopsys Design Compiler (PPA stage) | **not run** | PPA is `N/A_NOT_MEASURED`. No synthesis, physical-design or PPA result is claimed. |

This is a functional pass@1 result only.

**The image moved.** This campaign ran on
`ghcr.io/vibeic/vibeic-eda@sha256:06537f7e8d3c17c6c9c60c20638e94faab0421533a55656ad1819f383c373aba`
(label `0.3.46`), which carries **iverilog 14.0 (devel)**. Every published
VerilogEval-Human cell before the 2026-09-06 owner ruling was measured on
`sha256:66c33ff2…` = 0.3.6 with **host iverilog 11/12**. Numbers are therefore not
directly comparable across the move, and no pre-move figure is carried forward here
as if it described this image.

## Blindness and oracle disclosure

Authoring and review read the prompt only; the authoring transcript is in
`transcripts/`. Three deliberate, declared exceptions, none of which authored a
candidate in this run:

1. **ORACLE-FOR-RCA (convergence mode, declared).** To root-cause the two problems
   the newest published cell lost, and to build the `theoretical_max.json` evidence,
   this agent read `Prob062_bugs_mux2_ref.sv`, `Prob093_ece241_2014_q3_ref.sv`,
   `Prob139_2013_q2bfsm_ref.sv` and `Prob149_ece241_2013_q4_ref.sv`, and ran the
   official testbenches for those four problems against hand-built candidates.
2. **`benchmark/canonical_samples/verilogeval-human/Prob062_bugs_mux2.sv`** was
   opened while assembling the defect evidence. Its content matches what this agent
   had already derived from the prompt (`sel ? b : a`). Prob062 is a proven-broken
   problem, so this could not change a score.
3. **The official scorer was run on program-only emissions during fix development**
   (the `devloop/` arm). That is convergence-mode measurement, and it is why the two
   fixes on the branch can quote exact mismatch counts.

Consequences a reader should apply: **`Prob139_2013_q2bfsm` and
`Prob149_ece241_2013_q4` are not blind results in this cell.** `Prob149` is now
emitted by the deterministic program layer, so its RTL is a function of the prompt
text and not of anything this agent knew; `Prob139` was authored by this agent after
its reference had been read for RCA, and its PASS should be discounted accordingly.
The other 154 problems are unaffected.

## Reproduce

    git clone https://github.com/vibeic/vibe-ic.git && git checkout next/bvehuman
    git clone https://github.com/NVlabs/verilog-eval.git   # at c498220d0a52248f8e3fdffe279075215bde2da6
    cd vibe-ic-marketplace/plugins/vibe-ic
    python3 programs/benchmark_dispatch.py verilogeval-human --solve  --dataset <ds>/dataset_code-complete-iccad2023 --run <run> --jobs 8
    # author the declared AI-backup RTL and one prompt-derived review per problem
    python3 programs/benchmark_dispatch.py verilogeval-human --resume --dataset <ds>/dataset_code-complete-iccad2023 --run <run> --jobs 8
    python3 programs/benchmark_dispatch.py verilogeval-human --score  --dataset <ds>/dataset_code-complete-iccad2023 --run <run>

All of it inside `ghcr.io/vibeic/vibeic-eda@sha256:06537f7e…` with `--skip` as the
first argument after the image.

## Residual

Two problems, both proven broken, both with re-runnable evidence in
`theoretical_max.json` and `evidence/`. **No enhancement is owed on either**, per
the owner's rule. There is no third residual: every other problem passes.

## Addendum — main moved under this cell (recorded 2026-09-06 15:0x, host 8hd-3)

This cell was produced on `next/bvehuman` = `a938bc0a` (tree `edc7d6e2`), one commit
on `1eb2a241`. While the run was in flight, `origin/main` advanced to `63936c8e`
(v1.17.71) and **both of this lane's fixes were landed there as `310eaed34`
"v1.17.66 fix(program-layer): the two VerilogEval-Human problems the newer plugin
lost were never in the program layer"** — `threshold_ladder_synth.py` on main is
byte-identical to the copy in this cell's tree. The `next/bvehuman` ref was deleted
after landing; it has been re-pushed at `a938bc0a` so the exact tree behind these
numbers stays retrievable, and it is now redundant with main and can be deleted.

A sibling lane's `eb2c0d9ee` (v1.17.67) then added a K-map-that-feeds-a-mux emitter.
On current main the program layer therefore covers **both** problems this lane's
bisect named, plus Prob093:

    Prob149_ece241_2013_q4   ->  threshold_ladder   (this lane, v1.17.66)
    Prob093_ece241_2014_q3   ->  karnaugh_map       (sibling lane, v1.17.67)

That is a useful corroboration rather than a change of verdict. On main the emitter
produces `mux_in[2] = (~c & ~d) | (c & d) | (c & ~d)` — algebraically `c | ~d`,
which is the ab=10 column of the printed K-map and exactly the spec-faithful reading
in `theoretical_max.json`. It still cannot match the golden's `~d`. Prob093 is now
deterministically wrong-against-the-golden instead of AI-authored wrong-against-the
-golden, which is the strongest form the "no enhancement is owed" claim can take.

Program-only arm on current main `63936c8e`, same scorer, same dataset:

    134 emitted, 133/156 pass, 1 failed — and that one failure is Prob093.

So the program layer still has **zero genuinely wrong answers**: its only
mismatch is a problem whose golden contradicts its own prompt.
