---
name: open-benchmark-methodology
description: "Mandatory for VerilogEval, VerilogEval-v2, VerilogEval-Human, CVDP, RTLLM, PyHDL-Eval, RTL-Repo, MetRex, ResBench, ChipAgentsBench, benchmark, pass@1, benchmark floor/defect, run/rerun/score benchmark, or interpreting benchmark results. Enforces one general product entry, clean-room blind evaluation, Program First plus independent AI review/backup, official host scoring, evidence-backed triage, and capture of general enhancements."
---

# Open-Benchmark Methodology

The benchmark measures the Vibe-IC product path, not a benchmark-tuned agent.
Every runnable RTL evaluation uses the same solve core as an ordinary IC-design
request. Dataset differences are allowed only at the input/output boundary.

## Rule 0 — one product entry

For the open RTL suites in `benchmark/BENCHMARK_REGISTRY.json`, the only
authoring path is:

```text
benchmark_dispatch.py <bench> --solve
  -> benchmark_io_adapter.stage           (input translation only)
  -> task_nature_route                     (prompt/context evidence only)
  -> vibe_ic_one_shot_runner --entry-step  (normal product runner)
  -> Program candidate or declared AI backup
  -> independent hash-bound AI review
  -> benchmark_dispatch.py <bench> --resume
  -> accepted candidate
  -> benchmark_dispatch.py <bench> --score
  -> official host scorer
```

For whole-IC `benchmark_clean`, use the ordinary `/vibe-ic-all` entry,
`vibe_ic_one_shot_runner.py`, and the `benchmark-verify` skill. A benchmark IC
must not select another solver because of its IC name.

Forbidden alternatives include:

- benchmark-name or problem-id routers, task loops, tier pipelines, solve
  pipelines, Phase-1 wrappers, prompt exporters, or free-hand authoring loops;
- choosing a route from a CVDP `cid`, benchmark label, problem name, expected
  answer, prior score, or hidden harness;
- writing scoreable RTL directly and then calling a gate/scorer;
- publishing a partial previous-failure run as a benchmark result.

`benchmark/benchmark_entry_surface_check.py` enforces the shipped entry surface
and is called by `--solve`. If it fails, stop and repair the product entry before
running a benchmark.

## GENERAL-CORE / THIN-ADAPTER

Benchmark-specific code may only translate formats or invoke the official
scorer. A thin adapter may:

- stage the current record's visible prompt and supplied context into a normal
  project;
- collect an already-produced candidate;
- package exact accepted bytes into the scorer's required envelope;
- run image/tool preflight and translate official verdict files.

It may not classify the task, author or repair RTL, choose a product step,
infer hidden interface facts, assign PASS/FAIL, or use reference values. Logic
that works from ordinary prose/RTL belongs in a neutrally named general program
and must be reachable from a non-benchmark Phase-1/project flow.

For CVDP, `output.context` values are hidden golden data. At the post-acceptance
host packaging boundary only, the adapter may read its path keys to construct
the official multi-file response envelope. It must never expose values to the
solver or reviewer and must refuse ambiguous file/module mappings.

## Program First, AI Backup, AI authority

This is a sequence, not two independent racing solvers:

1. Program runs first through the normal runner.
2. If Program emits a candidate, an independent AI reviews the exact frozen RTL
   hash against the visible prompt/context.
3. If Program declares a supported WAIVE or route-level AI backup, AI may author
   the missing candidate into the runner-owned RTL directory; `--resume`
   re-enters the same product gates.
4. If AI agrees with Program, record acceptance for that exact hash.
   When Program lacks PASS functional evidence, the AI's current challenge plus
   every active inherited challenge must cover every block-eligible structural
   item emitted in `program_review_obligations`; `spec_coverage_check.py`
   measures this, and an uncovered item blocks acceptance.
5. If AI disagrees, it must identify the prompt requirement and provide a
   prompt-derived executable test that fails on the frozen Program candidate.
   Prose disagreement alone cannot replace the candidate.
6. A repair must pass that immutable challenge, the same runner gates, and a
   fresh independent AI review. AI is the final semantic authority only after
   this evidence chain is complete.

Every candidate therefore has two required checks: deterministic product gates
and semantic AI review. `program_first_ai_acceptance.json` must be `COMPLETE`
before scoring.

## Blind clean-room evaluation

A canonical run is a fresh full-dataset run. Do not read or inherit:

- prior samples, run artifacts, result files, or agent memory;
- sibling problems' solutions, testbenches, build scripts, or conventions;
- hidden harnesses, reference/golden outputs, or the host scorer during solve,
  review, repair, or optimization;
- prior failing IDs as a way to narrow the evaluation.

`--solve` owns run-directory creation, writes clean-room metadata, pre-creates
the transcript directory, and processes every current dataset case. Separate
scaffolding, benchmark-local authoring, and partial prior-failure evaluation are
not entry points. `--limit` is diagnostic only and its run is ineligible for
canonical scoring.

Export author/reviewer transcripts to `<run>/transcripts/`. The score front
door runs `benchmark_clean_room_check.py` and `blindness_audit.py`. Missing
transcripts require an explicit disclosure; a detected oracle access blocks
the score.

**Batch-dispatch ORCHESTRATION RULES — Shapes B/C (ORGANIC-20260605,
REQUIRED):** these bind every shape whose AI worklists fan out over more than
one agent — Shape C and Shape B alike; Shape D is a single project with no
fan-out and is exempt. Batch granularity (one agent per worklist slice, never
per problem), disk truth (progress is read from the run directory, never
from agent returns; resume = `--resume`), transcript export by default, and
the rate-limit resilience ladder (1-agent CANARY, then 2–4 concurrent with
completion-driven dispatch) are stated in
`benchmark/blind_instructions_shape_c.md` § ORCHESTRATION RULES and bound
into Shape B by `benchmark/blind_instructions_shape_b.md`.

Blind evaluation is the exam. Do not loop against official verdicts. Post-score
analysis may diagnose and capture a general enhancement, but the resulting
plugin change is measured only in a new clean-room run.

## Canonical commands

```bash
python3 programs/benchmark_dispatch.py <bench> \
  --solve --dataset <DATASET> --run <FRESH_RUN>

# Complete only runner-declared AI backup/review/repair worklists, then:
python3 programs/benchmark_dispatch.py <bench> \
  --resume --dataset <DATASET> --run <FRESH_RUN>

# Repeat --resume until program_first_ai_acceptance.json is COMPLETE.
python3 programs/benchmark_dispatch.py <bench> \
  --score --dataset <DATASET> --run <FRESH_RUN>
```

CVDP scoring additionally requires `--scorer-root <official-cvdp-root>` (or
`CVDP_BENCHMARK_ROOT`) and the exact official simulation images. Run the shipped
EDA image preflight before scoring. Do not substitute tools silently.

### The Program re-entry: re-running a FIXED Program on a preserved signed input

When a Program gate transformed an AI repair into different bytes, the existing
`AI_REPAIR_FINAL_PROVENANCE_REQUIRED` refusal remains authoritative. An upgraded
Program can be re-entered against the preserved, originally signed input with
the ONE Program re-entry operation:

```bash
python3 programs/benchmark_dispatch.py <bench> --resume \
  --dataset <DATASET> --run <RUN> --worker-threads 1 \
  --program-regate <RUN>/program_regate_request.json
```

`--program-retry` is a DEPRECATED alias of `--program-regate`: it runs the same
merged operation and prints a deprecation line on stderr. It is removed one
version after v1.17.75. Giving both names in one resume is refused, not ordered.
Until v1.17.75 these were TWO operations (`--program-regate`, v1.17.63, and
`--program-retry`, v1.17.71) for one job; issue #2047 merged them.

**BOTH identities, always.** The merged operation refuses unless the Program
moved in BOTH senses, because neither is necessary or sufficient for the other:
a real fix can land with no version bump, and a version can move with the
executable sources untouched.

* the declared VERSION pair — `program_version_before` must be the version that
  produced the preserved input, `program_version_after` must be the running
  Program, and the two must differ (an unchanged version is a loop, not a fix);
* the executable SOURCE TREE — `program_identity`, which fingerprints installed
  runtime source and configuration including dirty edits, must equal the running
  fingerprint, and must differ from the identity of any prior re-entry on this
  task. It is checked again after the runner.

This operation is BLOCKING and supports only an unaccepted, unpublished
`AI_REPAIR` task with a valid signed input snapshot. It does not authorize AI
edits, refresh a signature, supersede a test, or accept a result. The normal
repair boundary automatically saves both `repair_input_candidate_snapshot` and
the `pre_gate_input` manifest before running gates; the request must name a
candidate manifest whose exact RTL hash matches the unchanged signed repair
record and whose `source_rtl_paths` exactly match the task's working RTL paths,
and the task's own pre-gate manifest must describe the same signed bytes.
Reconstructing an unsigned input, supplying arbitrary RTL files, and other
candidate origins are unsupported and refused.

The request is a JSON object with these fields:

| Field | Required binding |
| --- | --- |
| `schema` | `vibeic.benchmark.program_regate.v1` (the legacy `...program_retry.v1` is still accepted) |
| `id` | Exact pending task ID |
| `task_sha256` | SHA-256 of `json.dumps(task, ensure_ascii=False, sort_keys=True)` |
| `prompt_sha256` | Task's current prompt hash |
| `stale_output_sha256` | Task's frozen output hash (legacy spelling `rtl_sha256` also accepted) |
| `signed_input_sha256` | Preserved input hash, equal to signed `repaired_rtl_sha256` (legacy spelling `input_rtl_sha256` also accepted) |
| `repair_record_sha256` | SHA-256 of the unchanged signed record's exact file bytes |
| `input_manifest_path`, `input_manifest_sha256` | Preserved input manifest and its exact file hash |
| `program_version_before`, `program_version_after` | The declared version pair; `_after` must be the running Program |
| `program_identity` | Current `benchmark_dispatch._program_source_identity()` object |
| `author`, `blind` | Attributed blind AI author (`kind: "AI"`, a named `model`, `oracle_accessed: false`) |
| `rationale` | Explanation of the re-entry, at least 80 characters (legacy spelling `reason` also accepted) |
| `review_sha256`, `challenge_sha256` | Exact current proof file hashes if a current review/test exists; otherwise omit or use null |

Where the two front doors spelled one field differently, both spellings are
accepted so no caller breaks; supplying both under CONFLICTING values is refused,
because an ambiguous identity is not an identity.

**What it refuses.** A wrong request or task schema; a missing or duplicate task
id; a non-`AI_REPAIR` candidate; a stale `task_sha256`, `prompt_sha256`,
`stale_output_sha256`, repair record, input manifest or Program identity; a
request naming no source identity at all; an absent, too-short or unattributed
rationale or author; an unchanged, unnamed or non-running version pair; a signed
input that is not the hash the author signed, or that the gates never changed; a
preserved input that is missing, drifted, internally inconsistent, made by a
different Program version, or that does not cover the working RTL file set; a
work tree that drifted from the frozen gate output (a hand edit cannot be
smuggled through a re-entry); prompt or Phase-1 provenance drift; a task already
accepted in either `solve_report.json` or the acceptance report, or already
published; a non-canonical response path or a project that is not the
runner-owned one; a missing, drifted or non-inherited challenge; a task that also
has a pending AI backup; an occupied archive or fresh review/test path; any
source changing during preparation; and a request, snapshot or evidence file that
is not a regular file inside the run, including any symlink traversal. Normal
relative project links to locations inside the same project are preserved,
including missing optional targets; absolute or escaping project links are
refused.

Under the existing coordinator lock, the operation runs the ordinary supplied-RTL
validation entry (`2`) with the original declared exit, in a staged project.
Collection uses the normal runner predicate; the exact return code and raw
reports remain available. It preserves the complete prior project, prior task,
solve/acceptance/worklist bytes, and any current review/test under
`program_regates/<id>/<request-sha>/`. Staged gate outputs remain at their
original paths so references in reports remain usable. Current and inherited
challenges remain obligations of the fresh independent review. Program actions
are recorded separately from the original AI repair author: the transition
records `attributed_to: "PROGRAM"`, `author_signature_unchanged: true` and
`repair_authorized: false`, and the author's signature is bound to the preserved
signed INPUT rather than to the Program's output.

A successful re-entry freezes a candidate in a fresh request-addressed snapshot,
creates unoccupied review/test paths, and returns `2` with `PENDING`. Complete
the fresh independent review and invoke ordinary `--resume` afterward. If the new
output still differs from the signed input, the unchanged final-provenance check
still refuses acceptance. Existing signatures and historical challenges cannot be
automatically rebound to the new output.

Runner failures preserve the original project/task and write a bound failure
record. An interrupted operation without a valid terminal record emits
`PROGRAM_REGATE_REFUSED` and blocks ordinary resume. A replayed request over a
journalled re-entry is REFUSED, never reported as already-applied. Reconcile the
immutable intent, staged output, preserved prior project, and transition before
continuing; automatic rollback and guessed recovery are deliberately unsupported.
Do not delete a journal or overwrite owner edits to make resume advance.

Before invoking any official host scorer, run the deterministic cwd guard over
the exact design and scorer working directory (and testbench when applicable):

```bash
python3 programs/benchmark_score_cwd_guard.py \
  --design <DESIGN_DIR> --cwd <SCORER_CWD> [--tb <TESTBENCH>]
```

A non-zero guard verdict blocks scoring; do not treat it as advisory.

## Four-stage attribution

Record every problem, including failures, in a per-problem table:

1. Routing — AI semantic decision plus the prompt/context evidence, selected
   nature, general entry step, evidence class, and exit step.
2. Solving — Program, declared AI backup, or evidence-backed AI repair; name the
   emitted candidate hash and reason for any handoff.
3. Verifying — deterministic runner gates and independent AI review; neither
   substitutes for the other.
4. Looping — no loop, AI backup, AI challenge/repair/re-review, optimization/PPA,
   or unresolved tool/dataset defect. State who acted and what evidence closed
   the loop.

The aggregate counts must reconcile exactly to the dataset denominator.

## Module-name source priority when prose and directory disagree (#482)

Dataset-agnostic authoring rule. When the prompt's stated module name and the
problem's directory / file leaf name DISAGREE, author the module under the
**directory-leaf name** as the **TB-facing module name**. Hidden testbenches
are generated against the file layout, and prose typos are common, so the
literal prose name will fail to elaborate. Keep the prose name only when no
directory/file convention exists, and note the conflict in the sample header
comment.

Close-loop and re-author actors **MUST NOT** "fix" a passing directory-leaf
module name back to the **prose typo**. A re-author regressed exactly this way,
turning a passing problem into a failing one while believing it was correcting
a mistake.

*why_not_bucket_a*: distinguishing a typo from a genuine intended wrapper name
requires contextual judgment — reading the prose against the file layout — and
no regex separates the two. The deterministic half is the priority order above;
the judgment is which of the two the disagreement is.

## Official scoring and tool disclosure

Scoring is a host-only post-generation step. Use the benchmark's official
testbench, image, command, cwd, module naming, and response format. Report:

- dataset identity/hash and exact denominator;
- plugin version/commit, MCP/EDA image digest and tool versions;
- official scorer command and substitutions (or `none`);
- raw PASS/FAIL/NOT_MEASURED counts and official logs;
- Program/AI routing, solving, verifying, and looping totals.

Never rewrite the official score to compensate for suspected bad goldens. Keep
the official number and separately disclose evidence-backed dataset defects.

## Failure triage

For every non-PASS, separate:

- product defect: Program/AI/gate/adapter behavior is wrong;
- tool gap: required official capability is absent or incompatible;
- incomplete/ambiguous public specification;
- suspected defective dataset/golden;
- host failure or NOT_MEASURED.

A dataset-defect or floor claim needs a prompt quote, official failure evidence,
and a control showing the prompt-correct interpretation cannot satisfy the
official oracle. A known-systematic tool blocker must cite its tracking issue
number. Never infer a floor merely because one attempt failed.

After writing the per-problem triage record, validate both its internal
consistency and whether every general recovery was absorbed into the product:

```bash
python3 programs/triage_record_check.py <TRIAGE_RECORDS.json>
python3 programs/benchmark_triage_absorption_audit.py <TRIAGE_RECORDS.json>
```

Either non-zero verdict blocks the result handoff.

## Category D — a tool-substitution gap is FORK-FIXABLE, not a floor

When the official testbench uses a simulator-only construct, or a language
feature our open-source substitute cannot yet run, that is **FORK-FIXABLE — not
a terminal floor.** We fork the EDA tools and ship them as `vibeic-eda`, so
"our tool cannot do X" is an engineering backlog item against the fork, routed
to `tools/vibeic-eda/FIX_STATUS.md`.

The mechanical half of the detection is a program, not a judgement: `programs/
tb_vcs_only_construct_detect.py` scans the failing testbench for the
iverilog-rejecting VCS/Xcelium-only constructs — array-aggregate `'{...}` init,
`break;` / `continue;`, `std::randomize`, `$urandom_range`, `unique`/`priority
case`, `join_none`, queue ops — and reports the offending line, the
`FORK-FIXABLE` disposition and the `FIX_STATUS.md` route. Use it to
auto-classify D; A/B/C and E-H stay judgement.

**Mandatory before you may even LABEL a residual Category D** — this is the
`asyn_fifo` lesson: run the FLOOR-proof below. Build and run the GOLDEN under a
tool that DOES support the missing feature.

* If the golden PASSES there, it is a confirmed genuine tool gap: open or
  update the `FIX_STATUS.md` row and add the feature to the fork.
* If the golden ALSO fails under the supporting tool, it was never a pure tool
  gap. Re-triage it as a dataset/RTL floor, not D.

Worked example: the RTLLM `asyn_fifo` official testbench uses `break;`, which
stock iverilog 12 rejects. The golden compiles and passes under Verilator with
`--timing` and under the forked iverilog, so it was a confirmed tool gap and is
now fork-closed.

**Never patch a tool to "pass benchmark X".** That is the over-fit prohibition:
the fork dissolves a CAPABILITY floor, never the honesty boundary. A genuine
algorithm-hard port that is honestly DEFERRED in `FIX_STATUS.md` is a
known-deferred engineering item, and still not an unfixable floor.

**A plain tool-substitution gap is NO LONGER T5 by default.** Since we fork the
tools it is Category D FORK-FIXABLE; it may be recorded as a real floor ONLY
once it carries the deferred `FIX_STATUS.md` entry AND has passed the
FLOOR-proof. Never "AI cannot".

## FLOOR-proof: never declare a floor without the original-RTL-also-fails run (#724)

Across one campaign FIVE residuals were labelled "benchmark defect" and ALL
FIVE were later overturned and PASSED — each was our own off-by-one, interface
or reset-boundary bug. A floor claim is almost always a misread, and the
asymmetry is severe: **a false floor ships an unfixed real bug**, while the
disproving run is cheap.

A residual may be labelled FLOOR only after this three-step **FLOOR-proof**, in
order:

1. **Run the exact official scorer** on the candidate RTL — the real harness,
   the real toolchain, the required env image — and read the real failing
   assertion. Not a paraphrase, not your own testbench.
2. **Run the ORIGINAL, unmodified reference/golden RTL through the SAME
   scorer.** If the **original** also fails, it is a genuine benchmark/oracle
   defect and a floor. **If the original passes, the defect is ours** — an
   authoring or extraction bug. It is not a floor; go and fix it.
3. **Only then confirm FLOOR**, and only when you can quote BOTH (a) the exact
   harness assertion that fails AND (b) the exact prompt line mandating two
   **mutually-exclusive** values for identical stimulus, AND you have shown in
   step 2 that the original RTL also fails.

Variant — the harness contradicts the given context itself. When the
contradiction is provable from the given input alone, the floor-proof is (a) a
cross-round expected-vs-got table, the testbench's asserted value for a
stimulus against what the given mapping mandates, shown stable across at least
two independent authoring rounds so it is not a one-off; and (b) a replay under
the design's OWN testbench confirming the given behaviour is internally
consistent while only the hidden oracle disagrees. The given context is then
the whole evidence and no external information is needed.

*why_not_bucket_a*: deciding whether two assertions are truly mutually
exclusive for identical stimulus is an open-ended meaning judgment no regex
makes. The deterministic half — a floor claim MUST carry the
original-RTL-also-fails scorer evidence — is the gate condition.

## Capture enhancement

Post-score recovery is not part of the blind score. When AI finds a correct
repair that Program missed:

1. isolate the general discriminator from prompt and RTL evidence;
2. add a benchmark-agnostic program rule/check/fix at the normal product
   enforcement point;
3. prove the new test fails on the unfixed product and passes after the fix;
4. run no-leak and false-positive controls on non-benchmark/general inputs;
5. issue a version-less PR and wait for it to land;
6. upgrade the installed plugin/MCP and run a new full clean-room benchmark.

Before recording the capture as complete, run
`python3 programs/convergence_doctrine_present_check.py`; a non-zero verdict
means the general-core/adapter and Program-First doctrine is not preserved and
the capture is incomplete.

Do not encode problem IDs, dataset labels, hidden expected values, or a lookup
table. Capture is successful only when the next ordinary Program First run
produces the right behavior without benchmark-specific knowledge.

## RESULT requirements

Every result must include:

- Summary/status and exact official score;
- clean-room/blindness statement;
- environment and official scorer evidence;
- full per-problem four-stage CSV/JSON path and reconciled aggregates;
- all failures with evidence-backed triage;
- captured enhancements/PRs and what they do not claim;
- reproducible next action.

**No RESULT means the run FAILED.** Never publish a number without the result
that backs it. The load-bearing failure is the launch-and-idle abandon bug: the
scorer or runner finished, a verdict and artefacts exist, and no RESULT was
ever written because the turn ended while the run was detached. To keep your
**turn alive to completion**, drive the long run through the BLOCKING
supervised waiter that returns only on exit or stall — never a detached
fire-and-forget.

**Why the instruction alone loses to a plausible model (#558).** An agent ended
its turn on a still-running flow, saying "I'll yield until the harness
re-invokes me when it exits". Nothing did. `claude -p` is one-shot, so the
three beliefs that justified it are each impossible:

* *"the harness **re-invokes** me when the background job exits"* — nothing
  re-invokes a finished turn. There is no such mechanism.
* *"a background waiter is armed to fire"* — a waiter can only wake a turn that
  is **still alive**. It cannot start a new one.
* *"the monitor will fire"* — a monitor **notifies the DISPATCHER**, not you.
  It cannot resume you.

Yielding does not pause your turn; it ENDS it, and the "then write the result"
step never runs. The rule above is not a preference about style — it is the
only way the deliverable gets written.

## Compliance gate (mandatory)

Save the final result and run the skill compliance check:

```bash
python3 programs/benchmark_result_md_lint.py <RESULT.md>
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
  --requirements plugins/vibe-ic/skills/open-benchmark-methodology/compliance.yaml \
  <RESULT.md>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in this skill directory enumerates every required
element of your output: section headers, handoff lines, summary blocks.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.

## Handoff

End with `## Summary` or `## Verdict`, followed by a clear `Next:` statement.
