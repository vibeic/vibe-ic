---
name: benchmark-verify
description: "Normalized, MANDATORY end-to-end verification for any benchmark IC after it has been driven from Design Documents → generated RTL → silicon through the full Vibe-IC flow. Produces ONE BENCHMARK_VERIFICATION_REPORT.md per IC covering all six pillars with hard gates: (1) Functional Verification Coverage == 100% (closed-loop until met), (2) 56-step Output Comparison vs the open-source reference (every applicable step PASS), (3) Code Coverage line >= 90%, (4) FPGA digital verification (test patterns on-board/BFM), (5) Analog closed-loop verification (or N/A for pure-digital), (6) Design-for-ECO readiness — spare-cell coverage PASS + spare preservation intact (or N/A if the IC has no place-and-route). Use when: 'verify the benchmark', 'benchmark verification report', 'is this IC production-ready', 'cross-check vs open source', after /vibe-ic-all on a benchmark IC, or for any IC in benchmark_clean/."
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
- **No vacuous result counts as PASS** (e.g. a Magic `gds read` that dropped geometry and
  reports "0 DRC" is INCONCLUSIVE, not clean). A missing input is **PENDING**, never a silent PASS.
  *Enforced by `programs/drc_vacuous_pass_check.py`* — flips a 0-violation DRC verdict to
  INCONCLUSIVE unless the log proves geometry was loaded; SKIPs (never PASSes) when no DRC log exists.
- The upstream open-source IP is the **golden oracle for cross-check only** — never a Phase-1/2 input.

## The five pillars (== report sections == hard gates)

### Pillar 1 — Functional Verification Coverage  ▸ gate: **== 100%**
**LLM judgment (irreducible):** walk L1–L27 (functional spec, interface, register map,
command/protocol, timing, behavioral sequences, test cases) and enumerate **every requirement** —
a program cannot reliably know that a prose timing sentence in L8 is a distinct *testable*
requirement (vs a restatement) nor author the directed test that covers it. For each requirement,
bind a verification item (directed test, assertion, golden-vector check, or formal property) and
confirm it PASSES against the generated RTL.
- `Functional Coverage = verified_requirements / total_requirements` → **must be 100%**
  (*the == 100% gate is enforced by `programs/benchmark_verify_report.py`*).
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

> **Independent differential self-verification (ORGANIC #700, BINDING — N-version):** #697 makes
> the self-TB as *complete* as the hidden scorer, but a single agent that derives BOTH the RTL and
> the self-TB from ONE reading still self-verifies **circularly** — a misread bakes into both
> surfaces. Break the circularity by deriving a **reference model INDEPENDENTLY** (fresh reasoning,
> not reusing the RTL derivation; explicitly enumerate + example-pin every ambiguous quantity —
> latency / registered-vs-comb / off-by-one / packing / encoding) and cross-checking it against the
> RTL every cycle:
> ```bash
> python3 programs/diff_verify_harness.py --rtl <rtl> --ref <independent_ref.py> \
>     --top <module> --vectors directed+random+boundary
> ```
> `AGREE` ⇒ the two independent derivations match every cycle; a first-mismatch line ⇒ a
> designer-vs-reference DIFF — adjudicate by re-reading the spec, fix the wrong derivation, re-run.
> Emit only after they AGREE. **Honest scope:** it catches OVERSIGHT misreads (one derivation
> noticed a clause the other missed; empirically caught an hmac live-vs-latched read, 3471 diffs →
> 0), NOT genuine ambiguity that biases all blind readings the same way nor benchmark spec↔TB
> contradictions (FLOOR per #697; 0/8 on the hardest CVDP ambiguity residual). It is a COMPLEMENT to
> #697 + #699, run BEFORE the scorer on fresh runs.

### Pillar 2 — 56-step Output Comparison vs open-source reference  ▸ gate: **every applicable step PASS**
For each of the 56 canonical flow steps (`flow/phase1_phase2_phase3.yaml`, which now includes
the Design-for-ECO spare-cell insertion step), compare OUR step output against the open-source
reference's corresponding output. Comparison is **step-appropriate, not byte-identical**.

*The step→class→comparison-method dispatch table and the legal verdict-token enum
(MATCH / EQUIVALENT / IN-RANGE / BOTH-CLEAN / DIFFERENT-BUT-OK / N/A / GAP / NO-TOOL / FAIL) and
which tokens count as PASS are enforced by `programs/benchmark_verify_report.py`* (its
`STEP_METHOD`, `VERDICT_TOKENS`, `PASS_TOKENS`). The step classes are:
**equivalence** (RTL/sim/formal/LEC/post-layout — LEC/co-sim/proof), **metric** (synth/SDC/DEF/
CTS/STA/SPEF/power — magnitude in range), **clean** (lint/CDC/DRC/LVS/IR/EM/antenna/SI — both
independently clean), **layout-endpoint** (GDS — both DRC/LVS/STA-clean + functional-equiv), **N/A**
(analog A1–A9 / mixed-signal M1–M4 for a pure-digital IC; manufacturing for no-silicon).

**LLM judgment (irreducible):** for a *metric* step, deciding whether two magnitudes are in a
*sensible* range (vs a hard threshold) requires understanding WHY they diverge; for a
*layout-endpoint* step, deciding that a different micro-architecture (our carry-save vs the ref's
array) is a *benign* divergence rather than a failure is design judgment, not a fixed compare.

Produce one `cross_check/**/step_<id>.md` per step (what ran, OUR result, REF result, verdict
token from the enum above).
**Close runnable GAPs** (e.g. run SPEF/IR/EM/antenna/power if the flow skipped them). Genuine
NO-TOOL items (e.g. open-source full-chip fast-SPICE) are recorded honestly — and noted if the
reference shares the same limitation. No step may be left unresolved.

### Pillar 3 — Test Cases & Code Coverage  ▸ gate: **line coverage >= 90%**
Author unit-test-style test cases (cocotb / SV testbench, via `eda_cocotb` / `eda_simulate`)
for the generated RTL. *The coverage measurement + the >= 90% line-coverage gate are enforced by
`programs/coverage_metric_check.py` / `coverage_closure.py` / `verilator_coverage_measure.py`.*
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
- **Preservation** — `reports/spare_preservation.json` from `spare_cell_preservation_check.py`:
  NO spare/ECO cell/gate/pad was optimized away by any later step → `all_keep_attr_intact: true`
  and `removed: 0`. (Every optimization skill — synth-doctor, rtl-repair, hold-fix, eco-plan,
  ppa-predict, drc-fix — carries the hard rule that it must never strip a keep-marked spare.)

**Applicability:** this gate applies to any **digital place-and-route IC** (a DEF/GDS exists
under `phase3/`). It is **N/A** only for an IC that genuinely never reached place-and-route
(e.g. analog-only). A **missing spare report is PENDING**, never a silent PASS.
**Closed-loop:** if PENDING/FAIL, run the stage3 Design-for-ECO step + its two checkers (or
restore any spare a prior optimization dropped) until coverage PASS + preservation intact.

## Procedure (run for each benchmark IC)
1. Confirm the IC reached the flow end (RTL generated + phase3 attempted). Read `SOURCE_MANIFEST.md`.
2. **Pillar 2:** dispatch the per-step cross-check (split phase1/2 and phase3 to keep tool
   runs bounded), writing `cross_check/<half>/step_*.md`. Run REAL tools in `vibeic-eda`; close gaps.
3. **Pillar 1:** build `reports/functional_coverage.json` from the L-doc requirements; close-loop to 100%.
4. **Pillar 3:** author tests, measure coverage → `reports/code_coverage.json`; close-loop to >= 90%.
5. **Pillar 4:** test patterns + FPGA/BFM run → `reports/hw_test.json`.
6. **Pillar 5:** analog closed-loop if applicable.
6b. **Pillar 6 (digital PnR ICs):** confirm the stage3 Design-for-ECO step ran, then run the two
    checkers → `reports/spare_cell_coverage.json` (readiness PASS) + `reports/spare_preservation.json`
    (`all_keep_attr_intact` + `removed:0`). N/A only if the IC never reached place-and-route.
7. **Aggregate + gate** — generate the single report:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_verify_report.py <project_dir> \
       --ref <open_source_reference_dir>
   ```
   It emits `<project>/BENCHMARK_VERIFICATION_REPORT.md` with the 6-pillar gate summary +
   the full 56-step comparison table, and exits non-zero until ALL gates pass.
8. **Close the loop** on any failing/pending gate, then re-aggregate. The benchmark IC is
   **DONE only when the report's OVERALL is PRODUCTION-READY** (functional 100% · 56/56 applicable
   PASS · code line >= 90% · FPGA PASS · analog converged-or-N/A · Design-for-ECO ready-or-N/A) —
   with honest, evidence-backed results and source provenance tagged.

## Acceptance
A benchmark IC passes `benchmark-verify` iff its `BENCHMARK_VERIFICATION_REPORT.md` shows:
- Functional Coverage **100%**, and
- Every applicable step of the 56 = PASS (no GAP/PENDING/FAIL/unexplained NO-TOOL), and
- Code line coverage **>= 90%**, and
- FPGA digital verification **PASS** (or justified N/A), and
- Analog **converged** (or N/A), and
- **Design-for-ECO ready** — `reports/spare_cell_coverage.json` readiness PASS **and**
  `reports/spare_preservation.json` `all_keep_attr_intact` + `removed:0` (or N/A if the IC has
  no place-and-route); verified by `spare_cell_coverage_check.py` + `spare_cell_preservation_check.py`,
  per the `design-for-eco` skill, and
- `SOURCE_MANIFEST.md` present with GENERATED/REUSED-IP tagged.
Anything short of that is **NOT complete** — keep working (closed-loop), do not claim done.

> **Plugin-test hard rule.** If the verification run modified any plugin code (e.g. a chip-agnostic fix to `benchmark_verify_report.py` or a checker), re-run the FULL suite before claiming done: `cd <plugin> && pytest -q` (pytest.ini collects BOTH `programs/tests/` AND `tests/`). Never validate with only `programs/tests/` — the integration/regression gates (INDEX freshness, every-skill-has-compliance, orchestrator branch tests) live in `tests/`. See `_shared/TESTING_STRATEGY.md`.
> *Enforced by `programs/plugin_change_pytest_gate.py`* — detects changed plugin `*.py` (git or an explicit `--changed-files` list) and FAILs DONE unless `--pytest-log` attests a clean run that collected BOTH test trees; ERRORs (never silent-PASSes) when the change state can't be determined.

## Worked example
`benchmark_clean/spm/` — first IC verified under this skill: RTL 100% GENERATED, functional
equivalence vs golden + upstream (10,013 vectors), 56-step cross-check under
`benchmark_clean/spm/cross_check/`, signed-off DRC/LVS/STA. Use it as the reference shape for
a complete report.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/benchmark-verify/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
