# CVDP Campaign — Follow-up / Hand-off Document

> **Purpose.** This is the authoritative hand-off for the CVDP benchmark campaign. A future agent
> should read this ENTIRE file before touching anything CVDP-related. It records (1) exactly where we
> are, (2) the binding official-compliance rules, (3) why the campaign is converged, and (4) the
> concrete, prioritized directions that remain. Owner closed the campaign on 2026-07-01 ("too much
> time/token on CVDP — stop") after reaching the honest official-compliant floor.

---

## 0. TL;DR

- **Official-compliant blind pass@1 = 243/302 = 80.46%** on `cvdp_v1.1.0_nonagentic_code_generation_no_commercial`, plugin **v1.2.63**.
- The model's ONLY inputs are `input.prompt` + `input.context`. The gate reads **NO** `harness.files` and **NO** `output.*`.
- The campaign is **CONVERGED at the honest floor.** Do **NOT** reopen CVDP to chase a higher blind number — the residual is oracle-coupled and unreachable without cheating.
- The value already produced lives in the plugin's **general core** (156 ic-expert skills + spec extractors + gates), which now serves the Phase-1 design-doc path and the other benchmarks.

---

## 1. Current state (numbers)

### 1.1 Per-tier (5-TIER stability × blind pass, §9 of `open-benchmark-methodology`)

| Tier | meaning | cases | blind PASS (compliant) | pass-rate |
|---|---|---|---|---|
| Tier 1 | deterministic program emit (no AI) | 38 | 38 | 100.0% |
| Tier 2 | program-extracted COMPLETE spec + gate + AI author | 221 | 176 | 79.6% |
| Tier 3 | gate-able (spec not fully complete) | 43 | 29 | 67.4% |
| Tier 4 | too-incomplete to gate | 0 | — | — |
| Tier 5 | proven floor (golden fails own TB) | 0 | — | — |
| **TOTAL** | | **302** | **243** | **80.46%** |

Reproduce the distribution: `python3 programs/cvdp_solve_pipeline.py --dist --jsonl <dataset.jsonl>`.

### 1.2 Compounding trajectory (blind pass@1)

`208` (v1.2.52 baseline) → `246` (v1.2.58, +38 skills) → `248` (v1.2.60) → `250` (v1.2.61) →
**`243` official-compliant (v1.2.63)**.

### 1.3 The compliance correction (250 → 243) — READ THIS

The prior 250 was **non-compliant**: the gate READ the hidden harness to fix names. Removed in two steps:

| Plugin | blind | removed read | cost |
|---|---|---|---|
| v1.2.62 | 246 | `.env` TOPLEVEL rename + cocotb `dut.<name>` port-align (FUNCTIONAL interface) | −4 |
| v1.2.63 | 243 | `output.context` multi-file keys (→ use input.context) + harness `.vlt` lint waiver (→ lint advisory) | −3 |

7 of the prior-250 passes relied on held-back data; all 7 are now correctly under-spec floors.

### 1.4 Artifacts

- `RESULT_cvdp_FINAL_compliant.md` — the final published result card.
- `rerun_v1262_compliance/`, `rerun_v1263_compliance/` — the compliance re-measures (drafts re-gated + re-scored; ~0 authoring tokens).
- `run_clean_v1252/` — the 302 baseline blind run + all author drafts.
- `rerun_v1258_blind/`, `rerun_v1260_t3/`, `rerun_v1261_blind/` — the incremental blind re-attempts.

---

## 2. BINDING official-compliance rules (verified 2026-07-01 vs paper + repo)

A future agent MUST obey these when running CVDP (or citing a number). Sources: paper arXiv:2506.14074
§2 ("Models or agents may generate or use a testbench but **never see the test harness or reference
solution**"); repo `README_NON_AGENTIC.md` ("The harness — docker-compose, test files, **.env** — is
NOT provided to the model").

1. **The model's ONLY inputs are `input.prompt` + `input.context`.** Nothing else.
2. **HELD BACK (never read, not even keys):** the entire `harness` object — cocotb `test_*.py`,
   `harness_library.py`, `docker-compose.yml`, **`.env`** (TOPLEVEL / VERILOG_SOURCES / MODULE), and
   any `.vlt` in harness.files. Also `output.*` (the reference solution; values are stripped in the
   public set but even the KEYS are off-limits).
3. **Module name + port names come from the PROMPT.** When the prompt under-determines a name (a
   dataset typo vs the hidden harness top), that is an ACCEPTED under-specification floor — do NOT
   "fix" it by reading the harness.
4. **The model MAY** generate its own testbench and run open-source simulators (iverilog/yosys) to
   self-verify its OWN work. That is explicitly allowed and is what the gate does.
5. **This dataset (code-generation subset) has NO in-context testbench.** Empirically: `input.context`
   = only `rtl/` + `docs/` (0 testbenches, 0 `$display`); harness = cocotb `.py` (hidden). The paper's
   "testbench (SystemVerilog, in-context, may use)" applies to the VERIFICATION categories
   (cid08/10/14), which are NOT in this subset.
6. **Scoring** = official `run_benchmark.py --llm -m local_import` in `cvdp-sim-pinned:latest`
   (Icarus 13). Pass@1 over n=5. A code-gen problem passes iff all cocotb tests pass.
7. **NO-MIX**: a results record never shares a commit with a plugin fix.

Regression guards already in the plugin (they FAIL if someone re-adds a harness read):
`test_main_does_not_rename_from_harness_env`, `test_main_does_not_align_ports_from_harness`,
`test_load_expected_files_map_only_multifile` (proves input.context, not output.context),
`test_main_lint_task_advisory_without_harness_waiver`.

---

## 3. Why the campaign is CONVERGED (do not reopen)

The residual **59 fails** are **oracle-coupled under-determination** — the information needed lives
ONLY in the hidden harness, so a compliant blind author cannot produce it:

- **Interface-name floors (~7):** the hidden cocotb TOPLEVEL / port name the prompt never states
  (e.g. `field_extract`, `findfasterclock` case, `hebb_gates`, `w_out`/`b_out`).
- **Value/behavior floors:** exact register offsets, inferred prices, reverse-index decimation order,
  MSB-vs-LSB packing, exact latency windows, exact `%`-reduction area thresholds — each stated only in
  the TB.
- **CLOSE-but-TB-internal (~13):** one assertion away, but the failing assertion is TB-internal
  behavior (off-limits as author input).

Golden RTL is **stripped**, so §4.1's "original-RTL-also-fails" FLOOR-proof is structurally impossible
— these are recorded as blind-unrecovered residual, not freshly-labelled FLOOR. The generalizable half
was already mined into the plugin (the 15 TB-diff skills of v1.2.61 + everything before). There is **no
further blind lift without crossing the harness-as-input line.**

---

## 4. What the plugin gained (the general core — this is the real deliverable)

CVDP convergence was the FORCING FUNCTION; the payoff is a benchmark-AGNOSTIC general core that also
lifts the Phase-1 design-doc path and other benchmarks:

- **`agents/ic-expert-agent.md`** — 156 design-judgment skills (registered cycle-stepped outputs;
  reset protocols; signed/unsigned; FIFO Gray-full; loadable counters; the 15 TB-diff
  "read-the-prompt-into-a-complete-TB" skills; etc.).
- **Spec extraction** — `spec_complete_extract.py`, `cvdp_complete_extract.py` (width/regmap/FSM/enum/
  worked-example/port-name/latency/clock-domain).
- **Hygiene** — `rtl_hygiene_lint.py` (width-truncate, narrow-bitwise-NOT, use-before-declaration,
  power-up-init, latch repair; enforced `--fix`).
- **Gates** — `spec_conformance_check.py`, `ppa_area_threshold_check.py` (#729), FSM-completeness
  (#522), handshake-livelock (#523), `spec_coverage_check.py` (§3.9 attribution).
- **The gate** — `benchmark/cvdp_gate.py` (GATE-AS-SOLE-EMIT-PATH; now fully official-compliant).

---

## 5. FUTURE DIRECTIONS (prioritized, actionable)

> These are the honest places a future agent CAN still make progress. CVDP-blind itself is done;
> almost all of these flow through the GENERAL CORE and are measured on OTHER surfaces.

### P1 — Move to END-TO-END IC (the owner's chosen next phase, 2026-07-01)
Drive the enhanced Phase-1 through Phase-2 (RTL) → Phase-3 (PnR/GDSII) on the benchmark ICs, with a
REAL output at every step compared against the IC's reference (golden RTL + reference_flow + PDK).
- **Selected ICs:** `opentitan_aes` (primary — has golden + reference_flow + pdk + phase1_prompt),
  `spm` (flow smoke — smallest, known-reachable GDS), `ibex` (largest — queued after aes).
- **Depth:** full Phase1→GDSII, step-by-step comparison.
- This is where the "stronger Phase-1" (trained by CVDP) gets proven on real silicon.
- See `benchmark-data/ic/` and the `open-benchmark-methodology` Shape-A/D + §7.5 mandatory-Phase-1 rules.

### P2 — Lift Tier-2 pass (79.6%) via the OTHER code benchmarks
The 45 Tier-2 fails are "spec extracted but the AI author missed a derivable convention." Run
VerilogEval-v2 / VerilogEval-Human / RTLLM clean-room; every recovery that is GENERAL + no-cheat gets
distilled into the general core (program-first). This lifts CVDP Tier-2 as a side effect without
touching CVDP.

### P3 — Tier-3 → Tier-2 (close extraction gaps)
The 43 Tier-3 problems have an incomplete extracted spec. The #1 gap is an unstated WIDTH; resolve it
from a literal / named-parameter expression / context param default (never a coincidental prose
number). Each closed gap is a `spec_complete_extract` enhancement (general core).

### P4 — Verification-category CVDP (a SEPARATE, legitimate surface)
The verification categories (cid08 Testbench↔Plan, cid10 Q&A-Testbench, cid14 Assertion-Gen) DO
provide an in-context SystemVerilog testbench the model may legitimately USE. That is a different
dataset/track — running it is honest new work (not reopening the code-gen blind floor). Requires the
verification-track dataset (not the no_commercial code-gen subset used here).

### P5 — DO-NOT list (explicitly out of scope)
- Do NOT re-run the code-gen blind to chase >243 — it is converged.
- Do NOT read the harness or golden for ANY reason that feeds authoring/gating (regression-guarded).
- Do NOT present a "converged / oracle-informed" number as a score (that is cheating; owner was
  emphatic).

---

## 6. Key commands / files

```bash
# tier distribution
python3 programs/cvdp_solve_pipeline.py --dist --jsonl <dataset.jsonl>
# author + emit (compliant gate — reads only prompt + context)
python3 benchmark/cvdp_gate.py --batch-dir <drafts> --out <resp> --report <rep> \
    --prompts <prompts.jsonl> --dataset <dataset.jsonl>
# official score (pinned OSS image)
cd <cvdp_benchmark_harness>
OSS_SIM_IMAGE=cvdp-sim-pinned:latest python3 run_benchmark.py -f <dataset.jsonl> \
    --llm -m local_import --prompts-responses-file <resp.jsonl> -t 4 -p <outdir>
```

- Dataset: `benchmark-data/datasets/cvdp-benchmark-dataset/cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl`
- Gate: `vibe-ic-marketplace/plugins/vibe-ic/benchmark/cvdp_gate.py`
- Doctrine: the `open-benchmark-methodology` + `benchmark-enhancement-capture` skills (BINDING).
- Memory: `cvdp-100pct-loop-and-ceiling`, `harness-is-input-not-oracle` (both carry the compliance correction).

---

## 7. One-paragraph hand-off

We drove CVDP from 208 → an honest, official-compliant **243/302 (80.46%)**, distilling every
generalizable recovery into the plugin's program/gate/skill layers (156 ic-expert skills + extractors
+ gates) and — critically — correcting the gate to read ONLY the model's legitimate inputs (prompt +
context), removing four places it had been reading the hidden harness/reference. The code-gen blind is
**converged at the floor**; the remaining 59 fails need information that lives only in the hidden
harness. The next phase (owner-directed) is **end-to-end IC** (Phase1→GDSII) on `opentitan_aes` / `spm`
/ `ibex`, using the now-stronger Phase-1, with step-by-step comparison against each IC's reference —
plus continued general-core lift via VerilogEval / RTLLM (which raises CVDP Tier-2 as a side effect).
Do not reopen the CVDP code-gen blind.
