---
name: benchmark-verify
description: "Normalized, MANDATORY end-to-end verification for any benchmark IC after it has been driven from Design Documents → generated RTL → silicon through the native table public entry. Produces ONE BENCHMARK_VERIFICATION_REPORT.md per IC covering all six pillars with hard gates: (1) Functional Verification Coverage == 100% (closed-loop until met), (2) native step/output comparison vs the open-source reference (every selected applicable row PASS), (3) Code Coverage line >= 90%, (4) FPGA digital verification (test patterns on-board/BFM), (5) Analog closed-loop verification (or N/A for pure-digital), (6) Design-for-ECO readiness — spare-cell coverage PASS + spare preservation intact (or N/A if the IC has no place-and-route). Use when: 'verify the benchmark', 'benchmark verification report', 'is this IC production-ready', 'cross-check vs open source', after a /vibe-ic-all invocation whose saved argv uses the public runner with a Router-selected window, or for any IC in benchmark_clean/."
---

# Benchmark Verify — normalized doc→production-ready verification

We run benchmark ICs to validate the **whole Vibe-IC flow**: that starting from a
complete set of **Design Documents** we can reach a **production-ready** result.
A benchmark run is **not finished** when the flow returns a verdict — it is finished
when this skill's five pillars all pass and the single report is written.

This skill is **chip-AGNOSTIC** and **MANDATORY** for every benchmark IC. Apply it
to each IC under `benchmark_clean/<ic>/` (and any future benchmark set).

## ⛔ Prerequisite — honesty + the corrected protocol
Read `benchmark_clean/METHODOLOGY.md` first. Non-negotiable:
- **Input = Design Documents ONLY** (incl. explicit PDK); nothing produced by a later
  phase is fed back as input.
- **Phase-2 RTL must be GENERATED**; IP reuse is allowed but **every reused source MUST be
  tagged `REUSED-IP` in `SOURCE_MANIFEST.md`** (vs `GENERATED`). Production-readiness credit
  applies only to GENERATED content; reused content is reported separately.
- Read the native layout-tool log and DRC result together. A run that did not load the required geometry did not measure that geometry, even if it printed zero violations.
- The upstream open-source IP is the **golden oracle for cross-check only** — never a Phase-1/2 input.

## The five pillars (== report sections == hard gates)

### Pillar 1 — Functional Verification Coverage  ▸ gate: **== 100%**
**LLM judgment (irreducible):** walk L1–L27 (functional spec, interface, register map,
command/protocol, timing, behavioral sequences, test cases) and enumerate **every requirement** —
a program cannot reliably know that a prose timing sentence in L8 is a distinct *testable*
requirement (vs a restatement) nor author the directed test that covers it. For each requirement,
bind a verification item (directed test, assertion, golden-vector check, or formal property) and
confirm it PASSES against the generated RTL.
- Write the benchmark report from the completed native results and official scoring outputs. Disclose cohort scope, unresolved cases and every unavailable measurement; do not fabricate an accepted score.
- Emit `reports/functional_coverage.json`: `{"requirements":[{"id","source","desc","status":"PASS|FAIL|PENDING"}]}`.
- **Closed-loop:** if < 100%, write the missing tests and/or fix the RTL (use `rtl-repair`)
  and re-verify until 100%. Do not waive a requirement; if a doc requirement is genuinely
  untestable, that is a spec defect to record, not a pass.

> **Spec-first coverage attribution (ORGANIC #697, BINDING — program-first):** before claiming
> Pillar-1 PASS, run `programs/spec_coverage_check.py` to make our self-verification as complete as
> the hidden scorer. Both derive from the SAME spec — where "spec" is the WHOLE input chain
> (prompt → fact graph → L1-L27):
> ```bash
> python3 programs/spec_coverage_check.py --prompt input/prompt.md \
>     [--fact-graph input/fact_graph.json] --ldocs generated_docs/ \
>     --rtl <rtl> --tb <self_tb> --strict --json reports/gates/spec_coverage.json
> ```
> Every spec-derived checklist item (ports, reset, latency, table rows, worked examples, **every
> ENUMERATED SET + its outside-the-set/default boundary**, signed-ness, byte order, overflow,
> handshake) must be COVERED by the self-TB. A `--strict` BLOCK means our TB is weaker than the
> hidden one — close the gap (write the missing assertion) before PASS. On any FAIL, run with
> `--failure "<behavior>"`: a `coverage-gap` ⇒ enhance our TB; an `extraction-gap` ⇒ the program
> names the `route_to:` station (ic-expert-agent / spec-to-rtl) that dropped the
> requirement; only a `spec-absent` (nowhere in the chain, with the searched stations cited) is a
> genuine floor and never a Pillar-1 fail. (The structural extraction + per-station routing is
> deterministic; deciding whether a prose sentence is a distinct *testable* requirement is the LLM
> step above.)

> Verify behavior through the selected native simulator or formal tool. Keep benchmark oracle material outside author/reviewer environments and use only input-derived tests for design changes.

### Pillar 2 — selected native step outputs vs open-source reference  ▸ gate: **every applicable selected row PASS**
Read `flow/steps.json` and the exact run's selected `steps/<step-name>/result.json`
results. Compare every selected applicable native tool output with the reference's
corresponding output. Report the step's position in the run's complete `flow/steps.json` table and name.
Unselected and inapplicable steps do not count as PASS. Compare engineering
meaning rather than requiring identical bytes.

Write the benchmark report from the completed native results and official scoring outputs. Disclose cohort scope, unresolved cases and every unavailable measurement; do not fabricate an accepted score.

**LLM judgment (irreducible):** for a *metric* step, deciding whether two magnitudes are in a
*sensible* range (vs a hard threshold) requires understanding WHY they diverge; for a
*layout-endpoint* step, deciding that a different micro-architecture (our carry-save vs the ref's
array) is a *benign* divergence rather than a failure is design judgment, not a fixed compare.

Produce one `cross_check/steps/<step-name>.md` per selected applicable row
(step name, canonical position, what ran, OUR result, REF result, and verdict
token from the enum above).
**Close runnable GAPs** (e.g. run SPEF/IR/EM/antenna/power if the flow skipped them). Genuine
NO-TOOL items (e.g. open-source full-chip fast-SPICE) are recorded honestly — and noted if the
reference shares the same limitation. No step may be left unresolved.

Use native coverage results to select the next input-derived test. Rerun the simulator and retain the original coverage target and actual measured denominator. Read line, branch, toggle and assertion coverage from the actual native simulator. Compare coverage with the original requested target and add input-derived tests for the uncovered behavior.
- **Line coverage >= 90%** (report branch + toggle too). Emit `reports/code_coverage.json`:
  `{"line_pct","branch_pct","toggle_pct"}`.
- **Closed-loop:** below 90% → add test cases targeting the uncovered lines until >= 90%.

### Pillar 4 — FPGA digital verification  ▸ gate: **PASS** (or documented N/A)
Generate **test patterns** and run the digital portion on FPGA (`fpga_test_harness_gen.py`,
`eda_fpga_compile`, `eda_fpga_program`, on-board or BFM). Record `reports/hw_test.json`
`{"verdict":"PASS|FAIL","patterns":N}`. A core with no board-pin contract may run a BFM/
gate-level equivalent — state which. N/A only with explicit justification.

### Pillar 5 — Analog verification  ▸ gate: **converged** (or N/A for pure-digital)
If the IC has analog blocks (`analog/analog_block_list.json` or `phase3/analog/*`), run the
analog **closed-loop**: `analog-sizing-loop` → corner sweep (`ams-sim` / `eda_spice_corner`) →
post-layout resim (`analog-extraction-resim`) → per-block PV (`analog-output-verify`) →
HIL if a bench is available (`analog-hw-tuning-loop`). Pure-digital ICs mark this N/A.

### Pillar 6 — Design-for-ECO readiness  ▸ gate: **spare-cell coverage PASS + spares preserved** (or N/A)
A production IC must be ready for a cheap **metal-only ECO** instead of a full base-layer
respin. That requires a distributed, tied-off pool of spare std cells/gates
(inverter/nand2/nor2/dff/mux2/aoi/oai) + reserved ECO pads — all `dont_touch`/`keep`, placed
after placement and before CTS at ~1-5% density. The methodology is the **`design-for-eco`**
skill. This pillar reads the two deterministic checker outputs:
- **Coverage / readiness** — `reports/spare_cell_coverage.json` from
  `spare_cell_coverage_check.py`: density / distribution / tie-off targets met → `status: PASS`.
- Compare the native netlist or implementation database before and after optimization. Preserve every unused ECO spare, its keep attributes and the reserved pads; an unintentionally removed spare must be restored.

**Applicability:** this gate applies to any **digital place-and-route IC** (a DEF/GDS exists
under `phase3/`). It is **N/A** only for an IC that genuinely never reached place-and-route
(e.g. analog-only). A **missing spare report is PENDING**, never a silent PASS.
**Closed-loop:** if PENDING/FAIL, run the stage3 Design-for-ECO step + its two checkers (or
restore any spare a prior optimization dropped) until coverage PASS + preservation intact.

## Procedure (run for each benchmark IC)
1. Confirm the IC reached the flow end (RTL generated + phase3 attempted). Read `SOURCE_MANIFEST.md`.
2. **Pillar 2:** dispatch comparisons only for the step names selected by the
   exact flow plan/request, keeping tool runs bounded. Write
   `cross_check/steps/<step-name>.md` with the current registry position as
   display metadata. Run REAL tools in `vibeic-eda`; close gaps.
3. **Pillar 1:** build `reports/functional_coverage.json` from the L-doc requirements; close-loop to 100%.
4. **Pillar 3:** author tests, measure coverage → `reports/code_coverage.json`; close-loop to >= 90%.
5. **Pillar 4:** test patterns + FPGA/BFM run → `reports/hw_test.json`.
6. **Pillar 5:** analog closed-loop if applicable.
6b. **Pillar 6 (digital PnR ICs):** confirm the stage3 Design-for-ECO step ran, then run the two
    checkers → `reports/spare_cell_coverage.json` (readiness PASS) + `reports/spare_preservation.json`
    (`all_keep_attr_intact` + `removed:0`). N/A only if the IC never reached place-and-route.
7. **Aggregate + gate** — generate the single report:
Write the benchmark report from the completed native results and official scoring outputs. Disclose cohort scope, unresolved cases and every unavailable measurement; do not fabricate an accepted score.
   It emits `<project>/BENCHMARK_VERIFICATION_REPORT.md` with the 6-pillar gate summary +
   the complete selected-applicable flow row comparison table. The table must
   identify every row by step name and current position and must not treat position
   as execution authority. The gate remains non-PASS until every selected applicable
   row is represented and every pillar passes.
8. **Close the loop** on any failing/pending gate, then re-aggregate. The benchmark IC is
   **DONE only when the report's OVERALL is PRODUCTION-READY** (functional 100% · every
   selected applicable flow step name PASS · code line >= 90% · FPGA PASS · analog
   converged-or-N/A · Design-for-ECO ready-or-N/A) —
   with honest, evidence-backed results and source provenance tagged.

## Acceptance
A benchmark IC passes `benchmark-verify` iff its `BENCHMARK_VERIFICATION_REPORT.md` shows:
- Functional Coverage **100%**, and
- Every selected applicable flow row = PASS, identified by its step name and
  current position (no GAP/PENDING/FAIL/unexplained NO-TOOL); unselected or
  inapplicable rows are disclosed and never counted as PASS, and
- Code line coverage **>= 90%**, and
- FPGA digital verification **PASS** (or justified N/A), and
- Analog **converged** (or N/A), and
- Compare the native netlist or implementation database before and after optimization. Preserve every unused ECO spare, its keep attributes and the reserved pads; an unintentionally removed spare must be restored.
- `SOURCE_MANIFEST.md` present with GENERATED/REUSED-IP tagged.
Anything short of that is **NOT complete** — keep working (closed-loop), do not claim done.

If verification changes plugin code, run the relevant existing tests and the
full suite when requested by the owner. Inspect the current `pytest.ini` and
`run_tests.sh` discovery so the report distinguishes configured pytest
collection from other test directories. Use `./run_tests.sh --list-tiers` to
inspect that discovery and `./run_tests.sh` for the requested full run. Report
the actual commands, collected and executed tests, failures, skips, and missing
dependencies. A collection error is not a passing test; a log or added policy
checker does not replace execution. Keep the IC coverage and engineering
limits above unchanged.

## Worked example
`benchmark_clean/spm/` is a report-shape example only: retain its RTL provenance,
functional equivalence evidence, and signed-off DRC/LVS/STA evidence where their
hashes remain current. For Pillar 2, derive the exact selected step names from
the current flow plan/request, record each current registry position for
display, and write one comparison per selected applicable row under
`benchmark_clean/spm/cross_check/steps/`. Historical fixed-count tables are
not current acceptance authority.
