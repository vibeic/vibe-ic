# Shape D blind instructions — generic agentic JSONL

Shape D selects an I/O protocol. Visible prompt/context/supplied RTL determines
one of the same five product natures used by Shapes B/C. The shared dispatcher
requires a named AI route decision before the canonical runner can start.

PARAMS the coordinator provides:
- `BENCH`: a dispatchable registry key (an I/O label, never a problem class).
- `DATASET`: the coordinator's agentic JSONL directory.
- `RUNDIR`: a fresh general solve run directory.
- `PROJECT`: `<RUNDIR>/projects/<id>/`, containing only visible inputs and
  solver-generated artifacts. Visible inputs include `work/PROMPT.txt`,
  supplied context under `work/`, and the normal `input/` ingestion paths.

The sole parser, `agentic_jsonl_to_shape_d.extract_dataset` / `extract_row`,
stages all row material into a coordinator-owned sibling extraction root,
`<RUNDIR>.shape_d_scorer/`. Its per-row `score/` and `.row_meta.json` stay there.
Only extracted visible inputs are copied into solver projects; the scorer tree
is outside the solver project/mount and never appears in AI routing tasks or
runner argv. The AI receives the issued task and visible solver inputs, without
access to the raw dataset or coordinator extraction tree.

## ABSOLUTE BLINDNESS RULE

Read only the current problem's visible prompt, context and supplied RTL.
NEVER open, cat, grep or list hidden harness/score material, golden/reference
outputs, scorer assets, or their paths. Official scoring is coordinator-owned.

**CROSS-PROBLEM PROHIBITION (ORGANIC-20260605-blindness-rule-cross-problem-refs).**
This rule binds for the whole dataset, including close-loop/repair agents.
Do not read other problems' inputs, harnesses, reference solutions or prior
outputs. Dataset BUILD files and hidden Makefiles/docker-compose files are
scorer authority, not solver inputs. Do not self-run a scoring harness or query
a verdict-level oracle during authoring. Self-verify using prompt-derived tests.
Transcripts exported to `<RUNDIR>/transcripts/` remain subject to
`programs/blindness_audit.py`.

## Procedure

1. The coordinator stages through the generic public entry:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <BENCH> \
       --shape D --solve --dataset <DATASET> --run <RUNDIR>
   ```
   This emits `needs_ai_routing.jsonl` and launches zero runners.

2. The named AI reads each issued task and its visible source manifest, then
   writes the schema-bound response at the issued `response_path`. Confirm the
   Program proposal or override with an exact visible-input citation supporting
   the selected existing nature. Name the AI model and declare no oracle access.
   `NEEDS_CLARIFICATION`, missing, stale, invalid, unattributed or ungrounded
   responses keep the entire batch pending; no runner starts early.

3. Resume the same general lifecycle, omitting the I/O selector:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <BENCH> \
       --resume --dataset <DATASET> --run <RUNDIR>
   ```
   Program validates every hash-bound route before invoking any runner. Program
   maps the AI-selected nature to fixed entry/evidence windows: generation and
   completion D1/lint/2; modification D1/behaviour/4; optimization 2/area/9;
   debug 4/behaviour/4. Mid-flow tasks retain normal D1/front-door provenance.
   AI cannot choose arbitrary steps or rewrite the canonical flow.

4. Complete the existing runner backup, independent candidate review and
   evidence-backed repair worklists with `--resume`. Acceptance remains the
   existing Program First + AI Review contract; a valid route alone does not
   accept a candidate. Use only prompt-derived self-tests, preserving the
   specified behavior (including reset semantics).

5. Official Shape-D scoring is external and **NOT_MEASURED** by this entry.
   The coordinator may score accepted artifacts separately with its official
   scorer. Dispatcher `--score` explicitly refuses `config.format=agentic`
   rather than falling through a nonagentic scorer. Scorer integration is not
   a routing completion gate.

## Final report

Report routing/runner/review status and exact evidence, generated vs reused RTL,
and any unresolved visible-spec ambiguity. Record official scorer status as
external/NOT_MEASURED unless separately measured by the authorized coordinator.
Do not infer a benchmark score, Phase 3, hardmacro or whole-IC result from routing.
