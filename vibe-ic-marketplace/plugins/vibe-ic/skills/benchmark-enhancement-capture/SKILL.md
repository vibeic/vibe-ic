---
name: benchmark-enhancement-capture
description: "MANDATORY after ANY close-loop or real-case run where AI judgment recovered a previously-failing case — not just RTL authoring. Applies to EVERY step in the Vibe-IC flow: Phase 1 NL ingestion, Phase 2 spec-to-RTL / chip_top / synth / TB / rtl_repair_retry / lint / conformance / audit, Phase 3 synth / PnR / CTS / DRC / LVS / STA / IR-drop, Analog A1-A9, Mixed-Signal M1-M4, MCP-EDA tools, and benchmark harness itself. The skill turns each AI-judgment recovery into structured candidates for permanent absorption: (a) deterministic program rules patching the RIGHT program file per step, (b) skill section appended to the RIGHT skill file per step (ic-expert-agent for design judgment / sta-review for timing / drc-fix for DRC / analog-topology-select for analog topology / etc., per CAPTURE_ROUTING.json), (c) community-backlog entries for larger engineering work, or (d) honest discard. Without this loop, every recovery — RTL authoring, PnR closure, DRC waiver classification, analog topology authoring, MCP tool behavior — stays per-session and the plugin never compounds. Triggers on: 'capture enhancements', 'absorb recoveries', 'enhance plugin from this run', '把這次救回的東西寫回 plugin', 'closed-loop enhance', after every /vibe-ic-benchmark close-loop, after every real-case close-loop in benchmark_clean / /vibe-ic-all, after a phase3 timing close-loop, after an analog A2/A4/A6 close-loop, after an MCP tool gap surfaces."
---

# benchmark-enhancement-capture — the plugin's complement-and-codify loop

This skill is what makes Vibe-IC's plugin **compound** over time. Without it,
every AI-judgment recovery — at ANY step in the flow — is a one-off that
evaporates with the session. With it, every recovery has a path to permanently
improve the plugin so the same fix is automatic next time.

## ⭐ THE BENCHMARK AGENT'S #1 MANDATE — converge → capture → distill-to-program (BINDING)

> **Owner directive (2026-06-22, emphatic): "請把這整套透過 Benchmark 不斷去收斂，然後
> capture 這些 fail case 變成可以解，並將所有可以解的都淬鍊在我們的 program 裡面。這是
> Benchmark Agent 最重要的事情了。"**

The Benchmark Agent's PRIMARY, never-ending job is a LOOP, not a one-shot score:

1. **CONVERGE continuously.** Run the benchmark; for EVERY fail, drive it to an
   OFFICIAL PASS — RCA against the harness oracle in convergence mode (§3.9
   oracle-for-RCA) → author → verify with the official scorer (e.g.
   `benchmark/score_one.py`). A fail is NEVER accepted as a "floor" until
   `spec_coverage_check --failure` proves it `spec-absent`.
2. **CAPTURE every fail into a solvable case.** Record `(design, prior-fail,
   recovered-pass, RCA)` so the recovery is reproducible — never a one-off.
3. **DISTILL every generalizable fix into the PROGRAM layer (program-first).**
   Turn each recovery into a deterministic rule / gate / extractor in
   `programs/*.py` (or the gate it belongs to) so the NEXT BLIND run auto-recovers
   it WITHOUT an agent. **This is the load-bearing step: it is what makes the
   benchmark number COMPOUND instead of evaporating.** The gap between the blind
   pass@1 and the converged 100% IS the backlog of fixes still to distill.

**Proven (CVDP campaign, 2026-06):** each program-first fix removed a whole
failure CLASS and lifted the blind floor — PR #42 (gate multi-file split +
flat-file-map recovery), #43 (`score_one` official single-design scorer), #46
(Phase-1 directional-prose port extraction — fixed the #1 blind cause: empty L1
pin_table → guessed port-name/CASE → cocotb "no child object named X"). Full-302
blind reached 185/302 = 61.3% (~1.8× the published SOTA 34 %); convergence reaches
~100 %. **Convergence has truly closed only when a fresh BLIND run produces 0
residual that needs a plugin fix, across TWO consecutive rounds** — until then,
every loop tick MUST end by distilling its recoveries into programs via the
bucket ladder below.

## The fix-all-into-the-plugin principle

> When you report a backlog / find an issue, the expectation is **NOT** to triage it into a
> category and then decide whether it is "worth" fixing. **Every issue gets fixed, and the fix
> lands in the next version of the vibe-ic plugin** — it does not matter whether the fix lives in
> a deterministic program, an MCP tool, or a skill. The category is an implementation detail of
> *where* the fix goes, never a reason to *skip* the fix.
>
> - Do **not** discard an issue as "not a plugin gap", "design-side", "clean-room variance",
>   "spec ambiguity", or "the author should have known". If a fresh user could hit it, the plugin
>   must handle it next time.
> - A recovery that currently relies on a **skill-prose lesson** a fresh author might forget is
>   itself an enhancement: **promote it to a deterministic program** (program-first) so it fires
>   every time, automatically.
> - The honest discard bucket (Bucket D) is reserved **only** for a fix that is genuinely
>   non-generalizable (it would over-fit one design's quirk or peek at a hidden oracle) — and even
>   then you record *why*, you do not silently drop it.
>
> **Convergence test (loop-until-dry):** a benchmark / flow close-loop has converged only when a
> **fresh clean-room re-run on the newest plugin produces 0 residual that needs a plugin fix**.
> As long as a clean-room run still surfaces any recoverable residual, the loop is not done:
> capture it → fix it into the plugin → re-run. One round with zero new backlog is a candidate;
> two consecutive zero-backlog clean-room rounds is convergence.

The bucket ladder (A>B>C>D) below decides *where* a fix goes; it NEVER decides *whether* to fix.
"not a plugin gap", "clean-room variance", and "design-side" are explicitly **NOT** valid Bucket-D
discard reasons — only genuine non-generalizable over-fit is.

## ⭐ THE GENERAL-CORE / THIN-ADAPTER PRINCIPLE — benchmark convergence MUST flow back to general cases (BINDING)

> **The point of converging a benchmark is NOT the benchmark number — it is to make the GENERAL
> Vibe-IC flow (Phase-1 design docs, any user prompt) better.** A fix that raises a benchmark
> score but is locked inside a benchmark-named module, unreachable from the general Phase-1 path,
> has captured only HALF its value. The other (load-bearing) half is making the SAME logic serve a
> plain design doc that has no benchmark harness.

Therefore every enhancement obeys a **two-layer architecture**:

1. **GENERAL CORE (benchmark-AGNOSTIC, no benchmark prefix).** The actual logic — width
   resolution, register-map / FSM / enum / numeric-pack / worked-example extraction, completeness
   assessment, RTL synthesis knowledge — operates on **plain strings + a supplied interface**
   (`prompt: str`, a port list), NEVER on a benchmark record format. It is named for WHAT IT DOES
   (`verilog_width_resolve`, `spec_regmap_extract`, `spec_complete_extract`, `bubble_sort_emit`),
   not for the benchmark it was first written against. Any benchmark OR a Phase-1 doc can call it.

2. **THIN ADAPTER (benchmark-SPECIFIC, the `cvdp_`/`rtllm_`/`verilogeval_` prefix is CORRECT here).**
   It does ONLY the IO mapping: read THIS benchmark's record format (cocotb `dut.<sig>` harness,
   `.env` TOPLEVEL, prose `### Inputs/Outputs`, a markdown table) and hand the recovered interface
   to the general core. It contains no reusable logic.

**The naming test (apply on EVERY enhancement):** if a file is named `cvdp_…` / `rtllm_…` /
`verilogeval_…`, ask *"does its LOGIC read a benchmark literal / record format, or is it pure
prose/param logic that merely got written here first?"* If the latter, the prefix is **naming debt
that hides the general value** — extract it to a benchmark-neutral name so the next benchmark and
the Phase-1 path actually reuse it. (Evidence: 6 extractors were buried under a `cvdp_` prefix with
ZERO benchmark literal in their logic — no other path would ever have reused a `cvdp_*` module;
renaming them surfaced the general engine `spec_complete_extract`, which then scored a harness-less
Phase-1 design doc identically to a CVDP record.)

**The completeness test for "did convergence flow back":** after a benchmark-convergence fix, a
plain Phase-1 design doc that exercises the SAME spec shape (e.g. a `[DATA_WIDTH-1:0]` port whose
default sits in a `| Parameter | … | Default | … |` column) must get the SAME completeness verdict
— with NO benchmark harness present. If it does not, the fix is still adapter-trapped; lift it into
the general core. This is **Bucket A done right**: a deterministic program rule that fires for
benchmarks AND general usage, not just the benchmark it was born in.

## Applies to EVERY step, not just RTL authoring

The first time this skill landed (v0.1.34) it captured 9 RTLLM spec-to-RTL
recoveries into the `ic-expert-agent` skill. But the SAME mechanism applies
to every step in the Vibe-IC flow — each step has its own canonical target
program (Bucket A) and target skill (Bucket B), declared in
`benchmark/CAPTURE_ROUTING.json`:

| Step domain | Bucket A target (program) | Bucket B target (skill) |
|---|---|---|
| Phase 1 NL ingestion | `phase1_one_shot_runner.py`, `phase1_engine/ingest.py` | `agents/ic-expert-agent.md` |
| Phase 2 spec→RTL | `rtl_hygiene_lint.py`, `chip_top_gate_wrapper_gen.py`, `spec_conformance_check.py` | `agents/ic-expert-agent.md` |
| Phase 2 yosys / rtl_repair_retry | `design_one_shot_runner.py` | `synth-doctor`, `rtl-repair`, `phase2-rtl-verify` |
| Phase 3 synth / PnR | `phase3_one_shot_runner.py` | `synth-doctor`, `sta-review` |
| Phase 3 CTS / hold | `phase3_one_shot_runner.py` | `hold-fix`, `sta-review` |
| Phase 3 DRC | `phase3_one_shot_runner.py` | `drc-fix` |
| Phase 3 LVS | `phase3_one_shot_runner.py` | `lvs-triage` |
| Phase 3 IR-drop | `phase3_one_shot_runner.py` | `ir-drop-triage` |
| Analog A2 topology | `analog_a2_topology_select_check.py` | `analog-topology-select` |
| Analog A4 corner sweep | `analog_real_corner_sweep.py` | `ams-sim` |
| Analog A6 per-block PV (DRC+LVS) | `analog_a6_block_pv_check.py` | `drc-fix` + `lvs-triage` |
| Analog A7 post-layout resim | `analog_a7_post_layout_resim_check.py` | `analog-extraction-resim` |
| Mixed-signal M1-M4 | `mixed_signal_m1_top_merge_check.py` | `mixed-signal-cosim` |
| MCP-EDA tool behavior | `mcp-eda/src/tools/*.js` | per-skill (`synth-doctor`, etc.) |
| Benchmark harness | `benchmark/score_*.py` | `open-benchmark-methodology` |

The routing table is consulted by `programs/enhancement_emit.py` to put each
recovery in the right place.

## When to invoke

- **MANDATORY** after every `/vibe-ic-benchmark` close-loop where any
  previously-failing design moved to PASS via AI judgment (not just
  deterministic gate fix).
- **MANDATORY** after every real-case run in `benchmark_clean/` or via
  `/vibe-ic-all` where a close-loop agent applied a chip-agnostic fix that a
  future runner could have applied automatically.
- **STRONGLY ENCOURAGED** at the end of any session where multiple
  AI-judgment fixes accumulated, even if individual fixes were small.

## Prerequisite — a run with NO deliverable cannot be captured (v1.3.51)

Capture presupposes a completed run with a written RESULT/deliverable. The
launch-and-idle abandon bug defeats this: an agent that delegates a long run
as a DETACHED background process and lets its turn END never gets re-invoked
to write the deliverable — the runner's own outputs exist (final_summary /
orchestrator verdict / GDS) but the synthesis RESULT is never written, so
there is nothing to capture from and the whole convergence evaporates. Two
binding rules make the run captureable:

- **Keep your turn alive to completion.** Run the long tool through the
  BLOCKING `_watchdog.run_supervised` (returns only on exit/stall; kills only
  a non-progressing job), never a raw detached `timeout &` fire-and-forget.

  **Why the instruction alone loses to a plausible model (vibe-ic#558).** An
  agent ended its turn on a still-running Phase-3 flow, saying "I'll yield until
  the harness re-invokes me when Phase 3 exits". Nothing did. `claude -p` is
  one-shot, so the three beliefs that justified it are all impossible:

  * *"the harness will re-invoke me when the background job exits"* — nothing
    re-invokes a finished turn. There is no such mechanism.
  * *"a background waiter is armed to fire"* — a waiter can only wake a turn
    that is STILL ALIVE. It cannot start a new one.
  * *"the monitor will fire"* — a monitor notifies the DISPATCHER, not you. It
    cannot resume you.

  Yielding does not pause your turn; it ENDS it, and your "then write the
  result" step never runs. The rule above is not a preference about style — it
  is the only way the deliverable gets written.

- **Self-verify the deliverable as your FINAL act**: run
  `python3 programs/run_output_completeness_check.py <run_dir>` on your own
  run_dir; only `COMPLETE` (exit 0) counts as done. **NO RESULT / empty
  output = the run FAILED** — and the gate emits a Bucket-C capture candidate
  on FAIL (`component=orchestration/deliverable-completeness`) so even the
  *absence* of a deliverable is itself absorbed here, never silent.

## Program-First — the binding priority order (read BEFORE classifying)

> **User directive (binding): "benchmark-enhancement-capture 一定要強調 Program-First."**
> Every recovery is presumed Bucket A until proven otherwise. The buckets are a
> priority LADDER, not a menu: A > B > C > D. You do not get to pick the bucket
> you find easiest — you must climb DOWN the ladder only when the rung above is
> genuinely impossible, and you must say WHY in writing.

For EVERY recovery, answer these in order and stop at the first YES:

0. **Is the ROOT CAUSE inside a forked EDA TOOL — i.e. a flow STEP's own tool
   (OpenROAD / KLayout / magic / netgen / yosys / ngspice / iverilog / verilator)
   produced a WRONG or incomplete output that a plugin-side Python rule could
   only paper over?** → **Bucket T (forked-tool enhancement).** Fix the BUG IN
   THE FORKED TOOL THE STEP USES — never a downstream band-aid in a different
   tool/step. (Owner directive 2026-07-11: "bug fix 要修在產生那個 output 的
   那個 step 所使用的 fork 工具裡，不要修錯地方.") See **Bucket T** below for the
   MANDATORY identification fields. Only when the root cause is genuinely in the
   plugin's own orchestration/extraction logic (not the tool) do you continue to
   step 1.

1. **Can a deterministic Python rule (regex / width / structural pattern /
   table lookup) detect-and-fix this without any LLM judgment?** → **Bucket A.**
   This is the default. A "judgment call" that is really just an unwritten
   regex (e.g. "the reflected CRC poly must be width-aware", "an `init` value
   needs an explicit `0x` or it's a stray token") is Bucket A, NOT Bucket B.
2. **Only if 1 is genuinely impossible** — the fix needs natural-language /
   convention pattern-recognition that no regex captures — → **Bucket B**, AND
   you MUST record `why_not_bucket_a` (one honest sentence: what judgment a
   program cannot make here).
3. **Only if A and B are both right but the engineering is large** (new program,
   corpus, fixtures) → **Bucket C**, AND record `why_not_bucket_a` too.
4. **Only if neither generalizes** → **Bucket D** with `why_discard`.

**Anti-laziness rule:** "this needs judgment" is the single most over-used
excuse to skip the program work. Before writing it, name the EXACT input the
program would see and the EXACT decision it cannot make from that input. If you
can name a regex/threshold/structure that decides it, it is Bucket A. The
v0.2.15 CRC capture is the worked example: every "the model should just know
the right poly width" instinct reduced to three regexes + one width-aware
helper — four Bucket-A rules, zero backlog.

**Enforcement:** `enhancement_emit.py` REFUSES any Bucket B/C record that lacks
a non-empty `why_not_bucket_a` (run it; exit 1 lists the offenders). The gate
exists so "I'll just append a skill paragraph" can never silently bypass the
program-first question.

### Bucket A is a LADDER of four, not two (v0.2.21 / M4 lesson)

When the source is a *skill* whose prose hides a rule, "extract to a program"
splits FOUR ways — decide per rule, in this order:

1. **ALREADY-PROGRAM** — the rule is *already* implemented in an existing
   `programs/*.py`; the skill is just documentation over it. Action: **none to
   code** — trim the skill prose to a one-line `enforced by programs/<x>.py`
   reference. **Check this FIRST.** In the v0.2.21 sweep of 20 skills, ~63% of
   "extractable rules" were already programs (82 candidates → 49 genuinely new).
   Creating a new program for a rule that already exists is duplication, not
   program-first — and risks a *fabricated* near-duplicate. Grep `programs/` for
   an existing checker before writing a new one.
2. **EXTRACT-NEW** — a genuine gap: write `programs/<name>.py` + a dedicated
   test (PASS + the real defect it guards + honest FAIL/SKIP on missing data).
3. **AUGMENT-EXISTING** — the rule belongs in an existing *shared* program but
   isn't there yet. When sweeping skills in parallel, **report** the augment for
   central apply (don't let N agents edit the same shared program and conflict).
4. **KEEP-JUDGMENT** — genuinely needs an LLM; leave in the skill with
   `why_not_bucket_a`.

**Corpus-sweep is mandatory and literal:** a new Bucket-A *guard* program must
run CLEAN on the current repo before it ships — `python3 <new_check>.py` exit 0.
If it fires on legitimate existing state it is a false-positive and MUST be
narrowed or dropped (v0.2.24: an "orphan test file" guard fired on the
mcp-eda / per-skill compliance suites that legitimately live outside
`pytest.ini` testpaths — it was narrowed to "testpaths must be a single tree",
which is the real invariant and fires zero false-positives). A guard that
flags the very state you just shipped is not a guard, it's a bug.

## Program-first + AI-backup: the DUAL-TRACK CONVERGENCE doctrine (ORGANIC #716)

> **User directive (binding):** "AI-backup" does **NOT** mean "use AI only when the program
> fails." It means a **dual-track convergence** — the program and an independent AI solve the
> SAME problem, the two results are compared, and every disagreement is investigated and
> converged. A green lone-track result is never accepted on its own.

"Program-first" makes a fix fire deterministically every time — but a program can still be
*wrong*: a too-narrow regex, a missed template variable (#714's `__OSS_PNR_IMAGE__`), a stale
baseline, a synth gate that silently never ran. A green program verdict can therefore **mask a
real defect**. The cross-check is what catches that. The three steps, for EVERY deterministic
gate:

1. **PROGRAM (primary, program-first).** The gate produces a verdict AND emits the **raw evidence
   it judged on** — the measured value, the log excerpt, the exit code, the cell/wire count — so
   an independent track can re-judge the same inputs. A verdict with no attached evidence cannot
   be cross-checked and is incomplete.
2. **AI-BACKUP (independent solve, no peeking).** An independent AI **solves/evaluates the same
   problem from scratch WITHOUT reading the program's answer**, then a **deterministic comparator
   diffs the two verdicts**. This is *not* an on-failure fallback — it runs even when the program
   says PASS.
3. **CONVERGE (the load-bearing step).** Agreement → accept. **Disagreement → converge:** surface
   BOTH verdicts with their evidence, root-cause *which track is correct and why*, fix the LOSER
   (tighten the program OR correct the AI reading), and re-run until they agree. **Never accept a
   lone-track "pass."**

**Why this is binding (evidence):** in the CVDP 100% campaign, FIVE separate "the program/agent
said done" results that an independent check disagreed with were EACH a real defect — false
B-floor labels, an agent self-reporting PASS while the independent re-score said FAIL, and a synth
gate that silently never ran (#714). Convergence — not either track alone — is what reached
302/302. A lone green track had a measurable false-positive rate.

**How to apply when you author a NEW gate** (this pairs with the Bucket-A ladder above): every new
deterministic gate ships with (a) evidence emission and (b) a named AI cross-check + converge step
— not just the program. This applies to every gate captured this session — #714 OSS_PNR preflight,
#715 multi-file completeness, and the latency / interface / coverage gates (#695/#697/#705): each
carries its independent cross-check whose disagreements are converged, never an "AI only on
failure" afterthought. The cross-check is itself subject to the honesty rules below (no peeking at
the oracle; the blindness boundary still holds).

## ⭐ Bucket T — forked-EDA-tool enhancement (BINDING, owner directive 2026-07-11)

> **We maintain our OWN fork of every OSS EDA tool** (OpenROAD, KLayout, magic,
> netgen, yosys, ngspice, iverilog, verilator — under `vibe-ic-forks/`, shipped as
> the `vibeic-eda` image). So a tool limitation is NEVER an excuse and NEVER a
> reason to band-aid the output downstream. If a flow STEP's output is wrong because
> the tool that STEP uses is wrong, **fix the bug IN THAT FORKED TOOL** so our fork
> matches what the commercial tool does.
>
> **FORBIDDEN PHRASES (owner directive 2026-07-12): "the OSS tool can't do it" AND
> "this needs a commercial / licensed EDA tool"** — naming Calibre, VCS, Design
> Compiler, PrimeTime, Spectre, Xcelium, HSPICE, or Formality as a hard requirement
> is the SAME forbidden excuse. The commercial tool is also software; we own the
> fork's source and enhance ours until it reaches parity. A commercial-tool
> capability gap is a fork-and-enhance BACKLOG item (this bucket), never a hard
> limitation or a WAIVE excuse. **Proven exemplar:** foundry Calibre/SVRF sign-off
> DRC — an admitted "needs a Calibre license" gap — CLOSED by forking KLayout into
> the native `svrfdrc` C++ buddy (`db::SVRFEngine`), byte-identical to the reference
> on a real 87k-line foundry deck, license-free (shipped `vibeic-eda:0.2.11`).

**The load-bearing rule — fix at the GENERATING step's tool, not where the
problem is DETECTED.** Attribute the defect to the step that PRODUCED it, and
fix the forked tool THAT step uses — do not patch a later step's tool. Worked
example (commercial-PDK spm, 2026-07-11): 993 MET1 min-area DRC violations were
*detected* by the DRC step (KLayout/svrf) but *generated* by the routing step
(OpenROAD `detailed_route`, which silently dropped min-area on via-access pads
touching fixed pin edges). The fix belongs in **forked OpenROAD's `drt`**
(`checkMetalShape_minArea`), NOT a KLayout post-process — a KLayout "repair"
would have been the WRONG place (fixing the detector, not the generator).

**MANDATORY identification fields for EVERY Bucket-T item** (in the recoveries
record AND the community backlog / PR — enforced by `enhancement_emit.py`):

1. **`step`** — which canonical flow step produced the bad output (e.g.
   `phase3.detailed_route`, `phase3.gds_streamout`, `phase2.synth`). This
   determines which forked tool owns the fix (see the step→tool map below).
2. **`problem`** — what went wrong: the tool's actual vs expected behaviour, in
   one precise sentence (e.g. "detailed_route leaves via-access pads below the
   layer min-area and reports 0 violations — a false-clean").
3. **`golden_sample` + `bad_sample`** — when available, BOTH artifacts: the
   good/expected output (a commercial-tool result, a hand-fixed layout, or the
   correct reference) AND the current bad output, as file paths, so the fix is
   verifiable against a concrete diff. If no golden exists, say so explicitly
   (`golden_sample: none — <why>`) — never silently omit.
4. **`tool` + `tool_enhancement`** — the forked tool (`OpenROAD` / `KLayout` /
   `magic` / `netgen` / `yosys` / `ngspice` / `iverilog` / `verilator`) and the
   concrete enhancement / guideline to make it do what the commercial tool does
   (the exact function / file / behaviour to change, and how it should behave).

**Step → forked tool (who owns the fix):**

| Flow step (generator) | Forked tool | Typical Bucket-T fixes |
|---|---|---|
| synth / techmap | **yosys** | cell mapping, tri-state, `$readmemh`, unpacked ports |
| floorplan / place / CTS / **detailed_route** / PDN | **OpenROAD** | min-area enforcement, wide-metal spacing, via enclosure, resizer segfault, PDN spacing |
| GDS streamout / merge / grid-snap / metal-density fill | **KLayout** | abutting-shape union, off-grid snap, per-layer density fill |
| DRC / LVS geometry decks | **KLayout** (svrf-native) / **netgen** | SVRF preprocessor, deck fidelity, portless-extraction guard |
| DRC (magic) / PEX (ext2spice) | **magic** | tech-derived extraction, layer retain |
| analog sim / Monte-Carlo | **ngspice** | native `.mc`, param-expand |
| RTL sim / lint | **iverilog** / **verilator** | array-pattern, break, package support |

**How to ship a Bucket-T fix (the proven loop):** (a) reproduce; (b) locate the
exact function/behaviour in the forked tool source; (c) make the MINIMAL,
low-regression change (prefer additive; keep the reported-DRC/marker path
byte-identical so existing PDKs don't regress); (d) rebuild the tool (the fork's
build tree is configured — incremental builds are fast); (e) re-run the step and
verify against the golden/DRC ground truth (svrf-native DRC gives a free,
license-less oracle); (f) commit to the forked-tool repo (`vibe-ic-forks/<tool>`)
with the step/problem/golden/enhancement recorded; (g) file the community
backlog / PR carrying fields 1–4. The forked-tool roadmap of known gaps lives in
`benchmark-data/ic/OSS_EDA_FORK_ROADMAP.md` — add every new Bucket-T item there.

**Bucket T vs the plugin buckets:** Bucket T is the ROOT-CAUSE-LAYER answer (the
defect is in a forked tool). Buckets A/B/C/D are for defects in the plugin's own
orchestration/extraction. A plugin-side wiring change may ACCOMPANY a Bucket-T
fix (e.g. discovering a PDK's layermap so streamout feeds the tool correctly is
Bucket A; making the router enforce min-area is Bucket T) — but you must not
substitute a plugin band-aid FOR the forked-tool fix when the tool is the
generator.

## The three buckets — every recovery goes into ONE

For each `(design, before-RTL, after-RTL, AI-reasoning)` recovery record:

### Bucket A — deterministic program rule
The reasoning reduces to **a structural pattern** that a Python program can
detect and apply without LLM judgment. Examples:
- "Restoring division remainder must be `dividend_width + 1` bits, not
  `dividend_width`" → new `rtl_hygiene_lint.py` rule + auto-`--fix`.
- "Module hardcodes 64-bit width but module name contains 'pipe'/'pipeline'
  → suggest adding `parameter DATA_WIDTH=64`" → new `spec_conformance_check`
  WARN.
- "Output port declared before clk/reset in description order, but TB likely
  uses output-first positional → reorder" → `chip_top_gate_wrapper_gen`
  enhancement.

**Emit**: a patch to the relevant `programs/*.py` file with the new rule,
PLUS a **corpus-sweep verification recipe**: list of repos / sample sets the
new rule must run cleanly against before shipping (zero false-positives).

### Bucket B — ic-expert-agent skill section
The reasoning requires **LLM judgment / pattern recognition** that doesn't
reduce to a deterministic rule. Examples:
- "When TB samples the clock at `t = k·(PERIOD/2)` with blocking statements
  in active region, use NBA toggle so sample lands pre-toggle."
- "Phrase 'whether the result has been consumed' implies a downstream-ready
  input port."
- "RTLLM benchmark family conventionally uses positional output-first
  instantiation."

**Emit**: a new `### Skill: <name>` section appended to
`agents/ic-expert-agent.md`, with the worked example + the general pattern.

### Bucket C — community-backlog entry
The fix is general and important but needs larger engineering work to ship
properly (corpus sweep, new program, new test fixtures). Examples:
- "Ship a deterministic `rtl_gen` for `digital_arithmetic_primitive` IC class"
  — major undertaking; needs spec extraction + template library.
- "Phase1 NL ingester emits 0 facts on free-form RTLLM prompts" — needs
  re-engineering the fact extractor.

**Emit**: a `community/backlogs/ORGANIC-<date>-<slug>.yaml` per the existing
schema (type / severity / component / pattern / suggested_fix / id /
submitted_at / session_context).

> **What `pattern` must say — the field is a rule, not a recap.** A `pattern`
> states the **class** of defect: what shape of input meets what shape of
> handling, and what wrong outcome follows. Write it so a reader can use it
> to recognise a **different** instance — a case you have not seen, in a
> different design, at a different step. It is NOT a restatement of `title`
> (the title names this occurrence; the pattern names the family it belongs
> to) and it is NOT a description of this one symptom. Test it before you
> write it down: *if this sentence only fits the record it sits on, it is not
> a pattern* — it cannot match the next occurrence, which is the only thing
> the field is for. Never paste one in from another record or from an issue
> body: a pattern that came from a different defect is worse than an empty
> one, because it reads as measured. `emit_backlog` refuses a missing or
> empty `pattern`; only you can tell whether a populated one is real.

> **Check-in handoff (scope-guard alignment):** if the role invoking this skill is
> the **benchmark-agent**, it may DRAFT the YAML but must NOT check it into
> `community/backlogs/` itself — `agent_checkin_scope_guard.py` denies benchmark-agent
> that zone (2026-06-21 owner directive: benchmark-agent MEASURES + fixes plugin/MCP,
> it does not file backlog). Hand the draft to the **core-agent / repo-gatekeeper**
> (or **field-agent**, whose zone IS `community/backlogs/`) to create and commit the
> file. This keeps the "who may write where" guard and this skill's Emit step
> consistent rather than contradictory.

### Bucket D — DISCARD (overfit / one-off) — the NARROWEST bucket
The fix only works for that specific design's quirks or peeks at hidden TB
conventions. This is the ONLY honest discard reason: a **genuinely
non-generalizable over-fit**. The following are **NOT** valid Bucket-D reasons —
each of these still gets fixed into the plugin (per the fix-all-into-the-plugin
principle above): "not a plugin gap", "design-side", "clean-room variance",
"spec ambiguity", "the author should have known", or "a skill already documents
it" (that last one is a Bucket-A *promote-prose-to-program* signal, not a
discard). Examples that ARE legitimately Bucket D:
- "Rename module name from spec-stated `freq_diveven` to dir-name
  `freq_divbyeven`" — works for THIS benchmark's typo but encoding it as a
  general rule would over-fit. Document the *judgment* (description vs dir
  typo handling) as Bucket B if generalizable; otherwise discard.
- "Hardcode the exact 6-state encoding the TB happens to use" — pure
  hidden-TB peek.

**Emit**: nothing to plugin; record in the session's RESULT for honesty.
**Real anti-example (ORGANIC #521):** a round-1 close-loop wrongly discarded
two real residuals as Bucket-D "clean-room variance" / "incomplete-closeloop"
and declared a FALSE convergence. They were in fact real plugin enhancements
(#517–#520). "variance" is never a discard reason — capture and fix it.

## The 4th distill target — the IC Expert DB (owner directive 2026-07-02)

Some recoveries are neither a deterministic rule (Bucket A) nor a one-paragraph
convention a fresh author might forget (Bucket B) — they are **generalizable
design-CLASS CRAFT**: the algorithm-correctness point, interface convention,
latency/reset discipline, or specific trap that makes a WHOLE class of design
correct (e.g. "non-restoring division needs a (W+1)-bit partial remainder + a
final sign correction"; "AXI-Stream: hold tdata/tlast stable while tvalid &&
!tready"). These distill into the **IC Expert DB**
(`agents/ic_expert_db/ic_expert_db.json`), keyed by `ic_class`.

- **Consumed by the GENERAL path as a DUAL-TRACK second opinion**: the runner
  writes the RELEVANT DB lessons (via `ic_expert_db_query.py` →
  `render_ic_expert_db_digest`) to a SEPARATE `ic_expert_db.md`, for an
  INDEPENDENT second-track author whose result cross-checks the primary author.
  **Measured (94 hard CVDP designs):** folding the DB into the single main
  digest LOWERED single-shot recovery (38→31, attention dilution), but as a
  complementary track the union is 38→**51 (+13)**. So the DB is a second track,
  NOT extra text in one digest. Serves ANY Phase-1 doc (GENERAL-CORE, not a
  benchmark adapter).
- **ADVISORY, never overriding**: a DB lesson ADDS design knowledge; it must NOT
  assert a hard rule a gate/program enforces, and can NEVER contradict a gate.
  The invariant (advisory + blindness-clean: no design-id, no oracle-value, no
  "disable the gate") is enforced by **`ic_expert_db_consistency_check.py`** —
  run it CLEAN before shipping any DB change.
- **Program-first still wins**: prefer Bucket A when a deterministic rule can
  capture it. Use the IC Expert DB for the residual craft that genuinely needs
  an LLM author — it is the structured home for Bucket-B-class design knowledge
  (retrievable by ic_class, not lost in monolithic prose).

Route in `CAPTURE_ROUTING.json` → `phase2.rtl_gen.ic_expert_db`.

**The dual-track SELECT is deterministic** — `programs/dual_track_select.py` makes
the "keep whichever candidate PASSes" decision by a gate/verifier, NEVER by an
author self-report. FUNCTIONAL tier (a scorer / cocotb TB supplied) picks the
first candidate that truly PASSes (this is where the measured +13 union lift is
real ground truth); STRUCTURAL tier (general Phase-1, no functional oracle) falls
back to iverilog-elaborate + a PRIMARY-first tie-break — it avoids regressing
below the primary single-track (38>31) but does NOT claim functional correctness.
So dual-track is program-first: the two authors produce candidates, a PROGRAM
keeps the passing one.

## Procedure

1. **Collect recovery records**. Input: pairs `(<design>, <prior-fail-sample>, <recovered-pass-sample>, <AI-reasoning>)`. Source = the close-loop agents' final reports + git diff between samples/.

2. **Per record, classify** into Bucket A/B/C/D. The 80/20 heuristic:
   - If the fix is `s/foo/bar/` syntactic or a structural template → A.
   - If the fix requires pattern-recognizing an English phrase or convention → B.
   - If A or B looks right but the engineering effort is large → C.
   - If neither A nor B generalizes → D.

3. **Emit candidates** via `programs/enhancement_emit.py` (the deterministic helper):
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/programs/enhancement_emit.py \
       --records <recoveries.json> \
       --out-skill-section <patch.md> \
       --out-program-rules <patch.py> \
       --out-backlogs <dir>/
   ```

4. **Review the candidates** (Bucket A program rules need corpus-sweep verification BEFORE being applied; Bucket B skills can be appended directly; Bucket C backlogs can be filed immediately).

5. **Apply Bucket A + B**, then SHIP.

   > **WHO ships, and how (contribution-layer scope).** Direct-push here is the
   > **maintainer-internal (Layer-2)** landing method and applies ONLY when the
   > agent running this capture IS the maintainer (`repo-gatekeeper` /
   > `core-agent`, who owns `plugins/vibe-ic/**`). A **non-maintainer** running
   > this skill — e.g. the `benchmark-agent`, or an external contributor — does
   > NOT direct-push; it hands the same Bucket A/B change upstream as a
   > **version-less PR** (or files a Bucket-C **backlog**), which the maintainer
   > reviews and lands (**Layer 1**). `agent_checkin_scope_guard.py` enforces
   > this: only the maintainer role may commit under `plugins/vibe-ic/**`.

   **Maintainer path — SHIP by DIRECT PUSH** (owner directive 2026-06-26,
   STANDING preference — supersedes the 2026-06-17 PR-method): direct commit +
   `git push origin main`, NO `gh pr create`. Every quality GATE is retained —
   only the PR ceremony is dropped. On the main checkout (re-poll +
   `git pull --ff-only` first; commit ONLY your own touched files by explicit
   path), carry only the rule/skill change + its regression test, ASSIGN the
   version (`gatekeeper_assign_version.py --write` → bumps `plugin.json` +
   `marketplace.json`), drive `gatekeeper_review.py --base origin/main --head
   HEAD` to **MERGE_OK** (version bump ENFORCED), run **Step-2.7** on any
   guard/transform/extractor diff, then `git push origin main`. The pusher
   assigns the next strictly-monotonic version pre-push and owns the
   milestone-cadence decision (an `x.y.0` rollover → FULL suite) — see
   `vibe-ic:core-agent-loop` §Step 3.

6. **Verify forward**: the NEXT benchmark run should pick up the rule
   automatically. If the same design now passes from a fresh run without
   close-loop, the loop closed correctly.

## Honesty rules

- **NEVER auto-apply a Bucket A rule** that triggers on the corpus-sweep set
  with any false-positives. The rule must be strictly safer than the prior
  state.
- **NEVER add a Bucket B skill section** that names specific benchmark design
  identifiers. Skills are general patterns, not lookup tables.
- **NEVER expand Bucket B into "the AI should just author the right RTL"** —
  that's not a skill, that's wishing the problem away.
- **NEVER discard (Bucket D) without a written reason** in the session
  RESULT. "Why this fix wasn't generalizable" is itself useful signal for
  future benchmark designers.
- **NEVER use "not a plugin gap" / "clean-room variance" / "design-side" /
  "spec ambiguity" / "the author should have known" as a discard reason** —
  per the fix-all-into-the-plugin principle, those all still get fixed into the
  plugin. Bucket D is ONLY genuine non-generalizable over-fit.
- **NEVER declare convergence on a single zero-backlog round.** Convergence is
  a fresh clean-room re-run on the newest plugin producing 0 residual that needs
  a plugin fix, confirmed across TWO consecutive rounds.

## This skill is the difference between "we tried RTLLM" and "Vibe-IC ships better"

Every AI-judgment recovery this session was a learning moment. Without this
skill, those learnings stay in this session's RESULT and evaporate. With this
skill, they become plugin code + agent skills + filed backlogs — and the next
new user who installs Vibe-IC gets all of them automatically.

That is the closed loop.


## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/SKILL_NAME/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in this skill directory enumerates every required
element of your output: section headers, handoff lines, summary blocks.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
