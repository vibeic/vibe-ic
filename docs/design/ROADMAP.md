# Vibe-IC v0.78 / v0.80 / v1.0 Roadmap — Knowledge Distillation × IP Integration × Open Marketplace

**Status**: design proposal, drafted 2026-04-26 from a session-level architecture audit; § 6 added 2026-04-26 from the open-platform vision
**Scope**: three orthogonal axes that all extend the same primitives —
(A) the knowledge-distillation loop that lets benchmark ICs improve future
ICs (§ 3, v0.78), (B) the IP-integration surface needed to support memory /
I/O / wireless / licensed processor IP as first-class inputs (§ 4, v0.80),
and (C) the open-platform marketplace that lets external orgs publish
Experience / IC IP / EDA-tool plugins on top of (A) and (B) (§ 6, v0.85+).
**Audience**: anyone shaping the v0.78 → v1.0 plugin/server release sequence.
Numbers and file paths are quoted as of v0.78.5 / v0.26.5.

---

## 0. Critique response — what got incorporated, what got rejected, why

This section records an external critique of an earlier draft of this roadmap
and the decisions taken in response. Recorded so future readers can see why
specific choices were made and don't relitigate the same questions.

### Accepted

| Critique | Where incorporated |
|----------|--------------------|
| **Decision trace ≠ provenance.** The current `auto_decided: { reason: ... }` only fires during Phase-1 layer-fill. Phase-2b/3 design decisions (utilization, aspect ratio, clock period, …) are made silently and only their *outcome* (WNS, cell count, area) is logged. Without a `{decision, context, outcome}` triple, "experience extraction" is just metric collection. | New § 3.6 *Decision Trace schema* — every Phase-2b/3 step writes a `decision_log.jsonl` next to its existing reports. Hand-filled at first, then auto-extracted from yosys / OpenROAD logs. |
| **System has been accumulating "what to avoid", not "what works".** Phase-2a structural gates, specificity meta-gates, K4 cross-layer rules — every recent addition is a *negative* rule. K3 `typical_structure` is the only positive-pattern store, and it is hand-curated, not mined from successful runs. | § 3.1 IC Expert collector role made bidirectional — drafts both `bug_classes:` (failure modes) and `proven_patterns:` (mined from benchmark runs scoring above a threshold). |
| **IP = knowledge carrier.** Hard / firm IP shouldn't arrive as just `.lib + .lef + .gds`; it should also bring `known_issues`, `integration_notes`, `historical_failure_modes`. For ARM-class or RF hard IP this metadata is more valuable to integrators than the RTL itself. | § 4.1 `ip-instantiate` skill takes a first-class `ip_metadata.yaml` alongside the binary deliverables. |

### Rejected (with reason — do not relitigate without new evidence)

| Critique | Why rejected |
|----------|--------------|
| **"Reframe spec as a Spec Graph for machine reasoning."** | Already a graph. L1-L13 JSON + K2 manifests + K4 cross-layer rules + IC Expert Agent's class-tree walk is exactly that — naming it "graph" is a re-label, not a new capability. The opening claim "spec is a document, no machine reasoning possible" doesn't match what's in the repo. |
| **"Build a Success Probability Model: P(tapeout_success \| features) via XGBoost."** | We have **0 silicon tapeouts**. Ground-truth labels for "tapeout success" do not exist yet. Phase-1 benchmark = 15 ICs; Phase-2+3 fully closed = ~10. Training a useful classifier needs ~100+ silicon-grade labels. **Deferred to v1.x** (after 50+ tapeouts). What we *can* do today is **single-stage decision → outcome regression** (utilization → cell density, opcode count → cell count) — explicitly scoped under § 3.6 since the data exists. |
| **"Replace 33 steps with a Decision Engine; execution becomes the verification layer."** | 33 steps is EDA reality. CTS can't be skipped, floorplan can't be skipped. Vibe-IC didn't invent them. The right move is to *overlay* a decision layer on top of each step (§ 3.6), not to replace the framework. IC Expert Agent + flow yaml + decision_log already constitute a decision engine — wrapping it in a new layer name buys nothing. |

### Calibration: ground-truth cost is not $$ — it's wall-clock + bench time

The earlier draft framed running benchmarks at $5 / $30 / $100 per LLM run.
That framing assumes ANTHROPIC_API_KEY billing. Current reality:

- All Agent execution goes through **Claude Max subscription** ($200/mo flat,
  20× Pro quota) → **zero marginal cost per benchmark run**.
- The single past exception was an early phase1 auto-run-loop bug that called
  the API instead of going through Claude Code; commit messages emphasising
  *"Max budget, zero ANTHROPIC_API_KEY spend"* mark the bug-fix point.

So sample acquisition is **not** the limiting factor for distillation. The
real scarcity hierarchy:

| Tier | What | Time per run | True cost |
|------|------|--------------|-----------|
| T0 | re-render existing persona output, score against ref | seconds | $0 |
| T1 | schema parity (K2 + K4) | seconds | $0 |
| T2 | LLM Phase-1 from persona prompt → JSON | minutes | $0 (Max) |
| T3 | T2 + spec-to-rtl + Yosys synth | 10-30 min | $0 (Max) |
| T4 | T3 + Quartus + OpenROAD GDS | 2-3 hr | $0 (Max) |
| **T5** | **Hardware bench verdict (DE10-Lite + EXAMPLE_TESTER + scope)** | **manual, batch weekly** | **human bench time** |
| **T6** | **Silicon tapeout (Efabless chipIgnite / Tiny Tapeout)** | **8-10 weeks** | **MPW slot, fab time** |

The decisive constraint shifts from *"can we afford to run T4?"* (no — we
can run T4 nightly) to *"can the model train on FPGA labels when only
silicon labels are real ground truth?"* (no — that's why
Success-Probability-Model stays deferred to v1.x). FPGA PASS does not imply
silicon PASS; T5 is the highest-fidelity label until T6 lands.

This calibration is what § 3.4 (rewritten below) operationalises.

### Coda — the critique's framing was right at the meta-level even where wrong on details

Setting aside the rejected items, the meta-point — *"vibeic should evolve
from a flow pipeline into a learnable IC-design decision system"* — matches
the direction this roadmap was already heading. v0.78–v0.82 are the
mechanical work to get there; v1.x is when the loop closes with silicon
labels. Anyone proposing to skip ahead to v1.x-style success-probability
modelling without first having decision_log + proven_patterns + T5 bench
labels is putting the model before the data.

---

## 1. Architecture as built (today)

The 3-Phase / 33-Step flow `vibe-ic-marketplace/plugins/vibe-ic-core/flow/phase2_phase3.yaml`:

| Phase | Steps | Skills | Deliverable |
|-------|-------|--------|-------------|
| **Phase 1** (Path A — prompt) | — | `phase1`, `spec-review`, PM Agent + IC Expert Agent | L1-L13 JSON **+ `human_docs/L*.md`** |
| **Phase 2a** (Path B — existing docs) | — | 17 doc-gen skills | L1-L13 JSON (no `human_docs/` — input is already human-readable) |
| **Phase 2b** | 1-13 | spec-to-rtl → lint → CDC/RDC → sim → formal → FPGA → SDC → synth → STA → DFT → equiv | mapped netlist + scan chain |
| **Phase 3** | 14-33 | floorplan → CTS → place/route → parasitic extraction → multi-corner STA → IR/EM/antenna/SI → post-layout sim → DRC/LVS/ERC → ECO → power → metal fill → tapeout-checklist → GDS → FPGA final | tapeout-ready GDS |

`human_docs/L*.md` is **Phase-1-only** by contract. v0.78 codifies that contract
in `tools/training/render_human_docs.py` (see §6).

### Knowledge layers (K1-K5)

| Layer | File | Purpose | Maturity |
|-------|------|---------|----------|
| **K1** | `agents/class_kb/class-tree.yaml` | IC class taxonomy (12 classes, ~30 subclasses) | ✅ stable |
| **K2** | `agents/lessons/manifests/L1_manifest.json` + per-class `<class>.yaml` | per-layer fact requirements | ✅ stable |
| **K3** | `agents/defaults/class_reference.yaml` (1597 lines) | per-class `typical_structure:` blocks (pin map, register map, submodule shape) | 🟡 **growing — 12 classes filled out of ~30** |
| **K4** | `tools/training/k4_candidate_rules.json` + `mine_k4_rules.py` | mined cross-layer consistency rules | ✅ 12 rules in production |
| **K5** | `phase1_k5_autopatch.py` | auto-patch Phase-1 outputs to schema | ✅ in `regression_suite.py` gate |
| **Q-bank** | `agents/qbank/<class>_L<N>.yaml` | PM-Agent class-specific prompts (73 YAML, 12 classes × 8-13 layers) | ✅ stable |
| **PRACTICAL_NOTES.md** | per-skill | lessons-learned, post-v0.75 cleaned of chip-specific bias | ✅ post-v0.75 hygiene gate enforces |
| **persona_knowledge** | `tools/training/auto_run_loop/persona_knowledge/<ic>_<persona>.yaml` | knowledge-boundary contract for benchmark fairness | ✅ 10 ICs |
| **15-IC scoreboard** | `auto_run_loop/SCOREBOARD.md` | quantified Phase-1 quality (path_coverage + value_match → 0-100) | ✅ mean 72.83, median 73.88 |

### IC Expert Agent (`agents/ic-expert-agent.md`)

The PM Agent talks to the user; the **IC Expert Agent** is the silicon reviewer
behind it. Its current contract:

1. Reviews every Phase-1 layer draft for completeness against K2 manifests.
2. Fills `auto_decided: true` defaults with reasoning trace.
3. Cross-checks layers (L5↔L1, L6↔L5, L9↔L5+L6+L8 — see §3.4 of agent doc).
4. Reads K3 `typical_structure` to lift under-specified designs to floor (v0.50
   fill-to-floor rule).
5. Walks the class parent chain (`cable-side-id-ic` → `protocol-ic` →
   `digital-ic` → `any-ic`) to find a usable shape.

**What it does NOT do today**: write back to K3. Currently a developer
manually edits `class_reference.yaml` after reviewing a benchmark run (e.g.
v0.77 commit `296c571f` extended K3 by hand for spi-peripheral / bus-controller-network /
network-controller / rng-deterministic-LFSR / dsp-block-CORDIC). This is the
biggest single gap in the distillation loop, and the v0.78 roadmap makes IC
Expert Agent the **collector** in addition to its current consumer role
(see §3).

---

## 2. Two-axis gap analysis

### Axis A — Knowledge distillation

| Capability | Today | Gap |
|------------|-------|-----|
| Benchmark IC → measured score | ✅ 15-IC scoreboard, JSON path_coverage + value_match | — |
| Lesson → K3 update | 🟡 **manual** — developer reads benchmark, hand-edits class_reference.yaml | **No automated patch suggester.** v0.77 commit shows what the output looks like; no tool produces it. |
| Lesson → PRACTICAL_NOTES.md | 🟡 manual; v0.75 cleaned 29 files for general-not-specific compliance | No automated proposer; meta-gate only catches violations after the fact. |
| Phase-2b lessons (RTL bug patterns) → K3 | ❌ they go to **programs/** as gates, not class_reference.yaml | "next SPI builder" gets typical_structure from K3 but not "SPI common bug X" — split-brain knowledge |
| Nightly regression "did K3 edit hurt anyone?" | ❌ 15-IC scoreboard exists but no scheduled run | one-off measurement, not a CI gate |
| Cost of running benchmark | 🟡 Max-budget in practice, no cheaper "schema-only" tier | every regression costs ANTHROPIC quota |
| IC Expert Agent as collector | ❌ consumer only | natural place to draft K3 patches based on `auto_decided` accept/reject signal |

### Axis B — IP integration

| IP class | K1/K3 entry | Skill | 33-Step support | Notes |
|----------|-------------|-------|-----------------|-------|
| **Soft IP** (parameterizable RTL: picorv32, ibex, AES, etc.) | ✅ in K1+K3 | spec-to-rtl + flatten | ✅ steps 9 (Yosys -flatten) | works today; this is what current flow assumes |
| **Memory macro** (SRAM / ROM / OTP) | ⚠️ K3 has 4-line `memory-controller` (controller, not macro) | ❌ no memory-compiler integration | ❌ no `set_dont_touch` flow, no floorplan blockage | **otp-content-gen** generates content not macro; OpenRAM hook missing |
| **I/O pad ring** | ❌ no class entry | ❌ no pad-ring-compose skill | ❌ step 14 (Floorplan+PDN) only handles core power; no pad ring step | GF180 + SKY130 both ship IO libraries; flow doesn't expose them |
| **Hard IP black-box** (e.g. PLL, ADC, BLE) | ❌ no class entry | ❌ no ip-instantiate skill | ❌ steps 9/16 don't allow instance-of-`.lib+.lef+.gds` | RF/wireless/mixed-signal needs this category to exist |
| **Firm IP** (obfuscated RTL, e.g. some ARM Cortex-M deliveries) | ❌ no class entry | ❌ | ❌ lint specificity gates would reject obfuscated identifiers | needs lint allowlist + L9 port-shape contract |
| **Licensed IP** (e.g. ARM Cortex-A, AMBA-licensed cores) | ❌ K1's `processor` only has RISC-V open-source | ❌ no AMBA VIP hook | ❌ | license boundary: plugin can't bundle, must take user-provided path |

The honest summary: the platform today is well-architected for **all-from-scratch
RTL** synthesis through 33 steps. Anything that arrives as a black-box deliverable
(macro, IP, pad cell) has no first-class entry point.

---

## 3. v0.78 — Knowledge distillation hardening

**Theme**: make IC Expert Agent the collector, and make K3 enrichment a
PR-bot suggestion instead of a hand edit.

### 3.1 IC Expert Agent → K3 patch proposer, **bidirectional**

New skill `class-knowledge-distill` (or new program `k3_patch_proposer.py`).

The system today has been accumulating *what to avoid* (negative rules:
specificity-meta-gate, the 7 v0.74 Phase-2a structural gates, K4 cross-layer
rules) but not *what works* (positive patterns). The only positive store —
K3 `typical_structure` — is hand-curated. v0.78 fixes both directions in a
single proposer.

**Trigger**: end of any benchmark IC run that produced final L*.json +
(optionally) RTL synth stats + (optionally) hardware verdict.

**Input**:
- The benchmark IC's L1-L13 JSON
- The matching class entry from `class_reference.yaml`
- (optional) Phase-2b synth stats (cell count, latch warnings, port count)
- (optional) hardware verdict (T5 bench: EXAMPLE_TESTER / FPGA BIST PASS/FAIL)
- The 15-IC scoreboard score for this run

**Output** (markdown PR comment + YAML patch suggestion), **two flavours**:

1. **Failure-mode patch** (`bug_classes:` field — see § 3.2 for schema):
   - Things that broke at lint / sim / synth / hardware
   - Cite which gate caught it (or none, if novel)
   - Include the lesson generalised to class level (specificity-meta-gate
     pre-validates)

2. **Success-pattern patch** (`proven_patterns:` field — NEW):
   - Triggered when this benchmark scored above the class median + 5 points
   - Diffs the IC's L*.json against the matching K3 `typical_structure` entry;
     promotes additions / refinements that aren't already in K3
   - Examples:
     - New `typical_pin` entries observed in this IC but absent in K3
     - Register-map naming patterns (CTRL/STATUS/DATA + IRQ_EN/IRQ_STS) that
       worked across N similar ICs
     - Submodule decomposition that produced a clean synth (no latch, no
       zero_ nets, no inferred BRAM mismatch)
     - `auto_decided` defaults that survived hardware (T5) — promote to
       `proven_default: { value, source: "<ic-id>@<commit>", verdict: T5_PASS }`

**Acceptance gate**: a human still merges the proposed YAML diff. The agent
drafts the patch, it does not auto-merge — keeps trust boundary intact and
matches the manual v0.77 workflow as a stepping stone.

**Key signal — `auto_decided` provenance**: IC Expert already writes
`{"provenance": {"auto_decided": true, "reason": "..."}}` in every layer JSON.
Today that trace is consumed only at lint time. v0.78 makes it a first-class
training signal: the agent reads its own past decisions, sees which ones
hardware-passed vs. failed, and proposes promotions or counter-examples.

**Why bidirectional matters**: a system that only files negative rules
becomes monotonically more restrictive — it never learns what to *prefer*,
only what to refuse. The 15-IC scoreboard is the positive-side oracle that
was already collecting the data; v0.78 just connects the wire.

### 3.2 Phase-2b lessons → K3 reflux

Today, every v0.74 Phase-2a structural gate (the 7 IC-agnostic gates that
catch nba_addr_read_race, periodic_timer_vs_rx_activity, internal_vs_external_timing, etc.)
lives only in `programs/`. v0.78 adds a `bug_class:` field to K3 entries:

```yaml
spi-peripheral:
  reference: "darkriscv spi core / OpenCores simple_spi"
  typical_structure:
    L8R_rtl_constants:
      crc8_polynomial: { source_layer: L3, hint: "from L3.crc.poly_value" }
  bug_classes:
    - id: "spi_clkdiv_off_by_one"
      symptom: "first SPI clock half-period truncated"
      caught_by: "phy_counter_check"
      lesson: "Initialize clkcnt to 0, not (DIV-1), when entering SHIFT state."
```

So the next agent designing an SPI peripheral gets both "what an SPI looks
like" (typical_structure) AND "what it usually breaks on" (bug_classes), in
the same lookup.

### 3.3 Nightly fairness regression

`tools/training/auto_run_loop/SCOREBOARD.md` is currently a manual
log. v0.78 adds:

- `bin/run_nightly_phase1.sh` — re-runs the cheapest tier (Stage 1: re-render
  existing personas, no LLM) for all 15 ICs and posts the delta
- GitHub Actions schedule: nightly + on every K3 / agent / qbank change
- A scoreboard delta comment on PRs that touch `class_reference.yaml`,
  `agents/`, or `qbank/`

This catches the case where editing K3 to help class A regresses class B.

### 3.4 Distillation tier system — scarcity is wall-clock + bench, not $$

LLM execution goes through Claude Max ($200/mo flat) → marginal cost per run
is **zero**. The tier system therefore matches cadence to *time* and *human
bench availability*, not dollars. See § 0 calibration for context.

| Tier | What | Wall-clock | True scarcity | Cadence | Gate |
|------|------|-----------|---------------|---------|------|
| T0 | re-render existing persona output → scored against ref | seconds | none | nightly + per PR | blocking |
| T1 | schema parity (K2 manifests + K4 cross-layer rules) | seconds | none | per PR | blocking |
| T2 | LLM Phase-1 from persona prompt → JSON | minutes | none | nightly | informational |
| T3 | T2 + spec-to-rtl + Yosys synth + Verilator coverage | 10-30 min | none | nightly | informational |
| T4 | T3 + Quartus FPGA `.sof` + OpenROAD GDS | 2-3 hr | wall-clock only (4-8 ICs/night per machine) | nightly (rotating subset) | release-gate blocking |
| **T5** | **Hardware bench verdict** (DE10-Lite + EXAMPLE_TESTER + scope) | **manual** | **human bench time, ~1 IC per session** | **weekly batch** | release-gate blocking |
| **T6** | **Silicon tapeout** (Efabless chipIgnite / Tiny Tapeout) | **8-10 weeks** | **MPW slot + fab time** | **per-release** | tagged-release-only |

**What this changes vs. the original draft**:

- T0-T4 all run nightly, not "weekly / monthly / release-gate" as previously
  proposed. There is no reason not to.
- T5 (bench) becomes the **first scarce-resource tier**. It's the highest-
  fidelity label we can reach without silicon. v0.78.1 ships the schedule
  and the bench-side capture skeleton; running the actual bench is a
  separate human task that the scheduler queues.
- T6 (silicon) is reserved for tagged releases. Labels from T6 are the
  only ground truth that the v1.x Success Probability Model can train on
  (see § 0 rejected-items table).

**T5 capture format** (so labels are usable later, not just one-shot logs):

```yaml
# experience_unit.t5.yaml — written by hardware-bench operator after each session
ic_id: "EXAMPLE_CHIP"
commit: "b66585d1"
bench_setup: "DE10-Lite + EXAMPLE_TESTER (tester), USB-Blaster"
fpga_program_pass: true
test_session:
  total_iterations: 5
  pass_iterations: 5
  failure_modes: []        # if any: { iter: 3, observation: "...", root_cause: "..." }
verdict: T5_PASS            # or T5_AMBIGUOUS / T5_FAIL
operator: "reyerchu"
date: "2026-04-26"
notes: |
  byte[6]=0xF2 + 17-byte MSN observed on all 5 iters. No probe artefacts.
```

Key invariants: every T5 capture references a specific git commit (so you
can reconstruct what RTL was burnt) and records `failure_modes` as
structured data, not freeform — that's what the proposer in § 3.1 reads to
draft `bug_classes:` patches.

### 3.5 PRACTICAL_NOTES.md auto-proposer

The v0.75 specificity meta-gate catches violations *after* a contributor has
written something chip-specific. v0.78 adds a **proposer** that, after a
benchmark IC closes, drafts a generalized PRACTICAL_NOTES.md addition based on
which `auto_decided` defaults the IC Expert Agent had to apply (or override).
Same human-merge contract as 3.1.

### 3.6 Decision Trace schema (v0.79 target)

The current system records *outcomes* per step (WNS, cell count, area,
DRC violations) but not *decisions* (why utilization 70 vs 75, why CTS
target skew 100 ps vs 50 ps, why aspect ratio 1.0 vs 1.2). Without
`{decision, context, outcome}` triples, "experience extraction" is just
metric collection — there is nothing to attribute the outcome to.

**Schema** — a `decision_log.jsonl` written next to each step's existing
reports:

```jsonl
{"step": 9, "step_name": "Synthesis", "decision_point": "synth_strategy", "options": ["area", "delay", "balanced"], "chosen": "balanced", "rationale": "no clock target violation reported by pre-STA; default for first-pass", "context": {"pdk": "gf180mcu", "target_freq_mhz": 50, "design_class": "spi-peripheral"}, "outcome": {"cell_count": 612, "area_um2": 41200, "wns_ns": 1.4}}
{"step": 14, "step_name": "Floorplan + PDN", "decision_point": "core_utilization", "options": [0.6, 0.65, 0.7, 0.75], "chosen": 0.7, "rationale": "target ~70% per K3 typical_structure for class spi-peripheral", "context": {"cell_count": 612, "die_constraint_um": [400, 400]}, "outcome": {"core_density": 0.69, "global_route_overflow": 0}}
{"step": 17, "step_name": "CTS", "decision_point": "cts_target_skew_ps", "options": [50, 100, 150], "chosen": 100, "rationale": "default; revisit if post-CTS hold > 50 cells", "context": {"clock_count": 1, "ff_count": 184}, "outcome": {"max_skew_ps": 87, "post_cts_hold_violations": 12}}
```

**Phasing**:
- **v0.79**: hand-fill on a small set of canonical steps (synth, floorplan,
  CTS, route — the four where decisions matter most). One JSONL per step
  per IC.
- **v0.80**: auto-extract from yosys / OpenROAD log files (each tool
  already prints "Using: balanced" / "core_util = 0.70" lines that can
  be regex-pulled). Hand-filled entries treated as ground truth, log-pulled
  entries treated as fallback.
- **v0.81**: feed into the § 3.1 proposer — *"these utilization values
  consistently produced WNS > 0 across 12 ICs; promote to K3
  proven_default for class spi-peripheral"*.

**Cheap parallel deliverable — single-stage decision regression**:
Once 50+ `decision_log.jsonl` rows exist for a single decision point
(say `core_utilization`), fit a stage-local model: `predicted_outcome =
f(decision, context_features)`. Linear regression / random forest over
~50-200 samples is statistically defensible and **does not** assume
silicon ground truth — only the immediate stage outcome (WNS, cell density,
overflow). This is what the rejected Success-Probability-Model (full
silicon outcome) wanted to do but couldn't. Single-stage version is
build-now territory.

### 3.7 Pattern Effectiveness Validation (v0.78.1, **shipped**)

**Closes the reinforcement-without-validation loop.** Without this, the
§ 3.1 proposer would promote a pattern to K3 because *one* IC scored well
with it, then continue reinforcing that pattern even if it never helped
again — or actively hurt later ICs. Critique surfaced this risk
("pattern drift / pseudo-learning"); v0.78.1 closes it.

**Three programs shipped together**:

1. `scoreboard_to_csv.py`
   Parses `tools/training/auto_run_loop/SCOREBOARD.md` markdown table into
   CSV + JSON, exposing per-IC score lookup that previously didn't exist
   (the v0.78 § 3.1 proposer's `_ic_score_in_scoreboard` was a placeholder
   returning None). With this, `is_proven_grade = score >= class_median +
   bonus` actually fires now.

2. `pattern_effectiveness_eval.py`
   For every class-level addition in `class_reference.yaml` git history,
   partitions scoreboard ICs of that class into BEFORE / AFTER the
   addition's commit date. Computes mean, stdev, delta, and a verdict:

   ```yaml
   pattern_stats:
     spi-peripheral:
       promoted_at: "2026-04-25"
       n_before: 1
       n_after: 3
       mean_before: 73.88
       mean_after: 75.92
       delta: +2.04
       stdev_after: 1.15
       verdict: helpful           # |delta| > 1.0 AND |delta| > sem
   ```

   Verdict thresholds (heuristic, tunable):
   - `insufficient_data`: n_before == 0 OR n_after < 2
   - `harmful`: delta < -1.0 AND |delta| > stdev_after / sqrt(n_after)
   - `helpful`: delta > +1.0 AND |delta| > stdev_after / sqrt(n_after)
   - `neutral`: otherwise

3. `k3_patch_proposer.py --pattern-stats <pattern_stats.yaml>` (wired)
   Reads the stats file. When the IC's class verdict is `harmful`,
   emits a `demote_suggestions` block in the report flagging the class
   for human review. `helpful` boosts confidence (no action). `neutral`
   and `insufficient_data` are no-ops.

**Limitations acknowledged**:

- Granularity is **class-level**, not per-pattern-line. Today's signal
  identifies which class entry has been hurting, not which specific line
  within it. Per-pattern-line attribution requires logging which K3
  entries IC Expert Agent actually consulted during fill-to-floor —
  v0.79 task.
- **Coarse temporal partition**: assumes patterns are available to
  every IC built after the addition's commit date. False positives are
  possible when *another* unrelated change (agent code, model update)
  drove the score delta.
- **Low n**: most classes have 1-3 benchmarks total today; verdict will
  mostly be `insufficient_data` until v0.79 broadens the benchmark fleet.
  This is the **right** behaviour — fail to "insufficient_data" instead
  of silently promoting on noise.

**Real-data smoke (today, against actual SCOREBOARD.md and
class_reference.yaml git history)**: 21 classes evaluated, all
`insufficient_data` (n_after = 0 or 1 in 19/21 classes; the two with
n>=2 still don't have a temporal split because the relevant K3 commits
landed in the same release as the new ICs). The framework will start
producing real verdicts as soon as a class gets a 2nd benchmark IC
landing AFTER a K3 patch — v0.79+.

**Why this matters**: GPT critique called this "pattern drift / pseudo-
learning" risk and was correct. Roadmap response: ship the validation
substrate **before** the proposer fires at scale. v0.79 just fills it
with data.

---

## 4. v0.80 — IP integration

**Theme**: extend the 33-step flow with two new steps and a new skill so the
platform stops assuming "all RTL is from scratch".

### 4.1 New skill: `ip-instantiate` — binary deliverables **plus** metadata

One skill, three modes — keyed off how the IP arrives:

| Mode | Binary input | Metadata input (NEW, v0.80) | What it produces |
|------|--------------|----------------------------|------------------|
| **hard-ip** | `.lib + .lef + (.gds + .v stub)` triplet | `ip_metadata.yaml` | Yosys `set_dont_touch` directive for the instance + OpenROAD floorplan placement blockage + DRC/LVS exclude rules + L9 port-shape contract entry + integration warnings from metadata |
| **firm-ip** | obfuscated `.v` (no internal signals visible) | `ip_metadata.yaml` | lint allowlist for obfuscated identifiers + L9 port contract enforcement still applies + integration warnings |
| **soft-ip** | parameterizable `.v` (today's path) | `ip_metadata.yaml` (optional) | dispatched to existing spec-to-rtl flow + integration warnings |

**Crucially**: IP arrives at L9 (Integration Spec). The existing L9 port-shape
contract enforces that the instance's ports match the rest of DTOP. So
`ip-instantiate` reuses existing consistency gates, doesn't bypass them.

**`ip_metadata.yaml` schema** — IP is a knowledge carrier, not just a binary
blob. For ARM / RF / sensor hard IP this metadata is often more valuable to
the integrator than the RTL itself:

```yaml
# ip_metadata.yaml — accompanies every ip-instantiate input
ip_id: "cortex-m0plus"
vendor: "Arm"
license_tag: "internal-eval-2026-Q2"     # recorded in provenance, not enforced
deliverable_kind: hard-ip                 # hard-ip / firm-ip / soft-ip

interface:
  bus: AHB-Lite
  data_width: 32
  clock_domain_required: separate         # IC Expert checks against L9
  reset_polarity: active-low
  power_domains: ["VDD_CORE", "VDD_IO"]

constraints:
  max_freq_mhz: 100                       # at this PDK / corner
  pdk: gf180mcu
  corner: tt_25c

known_issues:
  - id: "scan_chain_ordering"
    description: "Scan-chain insertion before this block's clock-gating cell causes ATPG fault coverage drop"
    workaround: "Insert scan AFTER ICG; see app-note AN-CMSIS-DFT-001"
  - id: "post_route_hold_density"
    description: "Hold-fix buffer count typically 2× a comparable RISC-V"
    workaround: "Budget extra utilization headroom"

integration_notes:
  - "Connect TDI/TDO to top-level JTAG TAP; do not strap to ground"
  - "WAKEUP must be tied high during scan mode"

historical_failure_modes:
  # populated over time from T5/T6 captures of designs using this IP
  - { date: "2026-03-12", design: "soc-foo", verdict: T5_FAIL, root_cause: "missed reset synchronizer between AHB clock and peripheral clock" }
```

**Wired into other layers**:
- `known_issues` → entries auto-promoted to `bug_classes:` in the matching
  K3 class (`processor-licensed-arm` for Cortex), so future agents see them
  even when not directly using this IP.
- `historical_failure_modes` → consumed by § 3.1 IC Expert proposer the
  same way as `auto_decided` provenance: a label that can be cited.
- `license_tag` → recorded in provenance JSON; not validated. Customer-side
  licensing audit is out of scope for the platform.

### 4.2 New 33-step Step 13.5 — IP Integration Audit

Between equivalence-check (step 13) and floorplan (step 14), check:

- Every `ip-instantiate`d block has a complete `.lib + .lef` (and `.gds` if
  going to silicon, not FPGA-only)
- Every IP's clock / reset domain matches the L9-declared domain
- Every IP's power domain is declared in UPF (if multi-domain)
- Every IP's bus protocol matches the integrating bus controller (AMBA AXI
  vs APB vs Wishbone)

Maps to a new program `ip_integration_audit_check.py`.

### 4.3 New 33-step Step 14.5 — Pad Ring Composition

Currently absent. After floorplan core (step 14), before CTS (step 15):

- Compose pad ring from PDK IO library
- Place ESD cells and corner cells per IO library spec
- Insert level-shifters at multi-VDD pad transitions
- Power-pad budgeting (one VDD pad per N signal pads, per IO library rule)
- Generate IO-only DEF that step 16 (placement) consumes

### 4.4 K1 / K3 additions

Four new class entries in K1 + K3:

| Class | Description | Reference |
|-------|-------------|-----------|
| `memory-macro` | SRAM/ROM/OTP macro instantiation (distinct from `memory-controller`) | OpenRAM macro flow |
| `io-pad-ring` | IO library composition + pad ring | GF180/SKY130 IO library |
| `rf-frontend` | RF / mixed-signal hard IP front-end | (BLE deliverable schema) |
| `processor-licensed-arm` | ARM Cortex-* hard or firm IP | user-provided path; license-aware |

Each new class gets:
- K1 entry (`agents/class_kb/class-tree.yaml`)
- K3 typical_structure (when `ip-instantiate` mode = soft, else just the
  black-box port shape)
- K2 manifest (which layers are mandatory — RF gets RF-specific L1 fields:
  Tx_power, RX_sensitivity, frequency_band)
- Q-bank entries (PM Agent class-specific prompts)

### 4.5 mcp-eda surface (probably no breaking change)

Existing `eda_synth` already accepts `synth_attrs` (where `set_dont_touch` can
be passed). Existing `eda_pnr` already reads LEF. Existing `eda_drc_klayout`
already supports `pdk=custom` deck. So **the MCP surface probably needs no new
tool** — just exercise these capabilities from new skills.

What may be needed:
- `eda_padring_compose` — light wrapper around OpenROAD IO composition (if
  step 14.5 is non-trivial to script per project)
- `eda_ip_lib_audit` — verify `.lib + .lef + .gds` triplet consistency for a
  hard-IP

These are optional; can stay as plugin programs and only graduate to MCP tools
if every project ends up rewriting them.

### 4.6 License boundary

For licensed IP (ARM Cortex-A, AMBA VIP, etc.) the plugin must NOT bundle the
RTL. The `ip-instantiate` skill takes:

- `--lib-path /path/to/customer/cortex-m0.lib`
- `--lef-path /path/to/customer/cortex-m0.lef`
- `--metadata /path/to/customer/cortex-m0.ip_metadata.yaml`

with a `--license-tag` argument that gets recorded in provenance but is not
checked against any database — that's a customer-side problem, not a platform
problem. We just make sure provenance is honest about what came from where.

---

## 5. v0.81 — Unified Experience Schema

**Theme**: today's knowledge stores grew incrementally and live in five
different shapes. v0.81 puts them behind one schema so the v0.78
proposer (§ 3.1) and the § 3.6 decision-trace consumer can address them
uniformly. Underlying physical storage stays the same — this is a *view*
unification, not a migration.

### 5.1 The five existing stores

| Store | Format | Contents |
|-------|--------|----------|
| K3 `class_reference.yaml` | YAML | per-class typical_structure (positive patterns, hand-curated) |
| K4 `k4_candidate_rules.json` | JSON | mined cross-layer rules (negative — what fails) |
| PRACTICAL_NOTES.md | markdown | per-skill lessons-learned |
| Scoreboard `SCOREBOARD.md` | markdown | per-IC quantified scores |
| `decision_log.jsonl` (§ 3.6) | JSONL | per-step decision/outcome traces |
| `ip_metadata.yaml` (§ 4.1) | YAML | per-IP integration knowledge |
| `experience_unit.t5.yaml` (§ 3.4) | YAML | per-bench-session hardware verdicts |

### 5.2 The unified `experience_unit`

Every store can be projected into the same minimal shape. **Physical
storage stays where it is**; this is a *view* contract for queries:

```yaml
experience_unit:
  uid: "<store>:<id>"            # e.g. "k3:spi-peripheral.typical_structure.L4_regmap"
  context:                        # what state was the system in
    ic_id: "<id-or-class>"
    class_path: "spi-peripheral"
    step: 14                      # 0 = pre-design / class-level
    pdk: "gf180mcu"
    git_commit: "b66585d1"
  decision:                       # what choice was made (optional for K3/K4)
    point: "core_utilization"
    chosen: 0.7
    options_seen: [0.6, 0.65, 0.7, 0.75]
    rationale: "K3 typical_structure default for spi-peripheral"
  outcome:                        # what was observed
    metric: "wns_ns"
    value: 1.4
    verdict: PASS                 # or T5_PASS / T6_PASS / FAIL / null
  lesson:                         # generalised takeaway (proposer-drafted, human-merged)
    polarity: positive            # or negative
    statement: "core_util 0.7 is safe for spi-peripheral on gf180 at 50 MHz"
    promote_to: ["k3.spi-peripheral.proven_default"]
  provenance:
    source: t5_bench              # or auto_decided / k4_mine / pr_review
    evidence: "experience_unit.t5.EXAMPLE_CHIP.2026-04-26.yaml"
```

### 5.3 Adapters (one per store)

Five small adapters in `tools/experience/`:

- `k3_to_units.py` — emits one unit per `proven_default` / `bug_class` / `typical_pin` entry
- `k4_to_units.py` — emits negative-polarity unit per rule
- `practical_notes_to_units.py` — emits one unit per non-trivial paragraph
- `scoreboard_to_units.py` — emits a context-only unit per IC × persona × commit
- `decision_log_to_units.py` — passthrough (already in shape)
- `t5_capture_to_units.py` — passthrough
- `ip_metadata_to_units.py` — emits one unit per `known_issue` / `historical_failure_mode`

### 5.4 What this enables

**Today**: §3.1 proposer needs custom code per store to query "has this
benchmark IC's auto_decided value been seen before, and what was its
verdict?" The query touches K3 (manual-curated state), `auto_decided`
provenance (hand-grep), scoreboard (tag-grep), maybe T5 logs (grep).
Five glue scripts.

**With unified view**: the same query is one filter over the union of
all unit streams. The proposer's logic shrinks; new stores (when added in
v0.82+) only need a new adapter, not new proposer code.

### 5.5 What this is NOT

- Not a database migration. Adapters read existing files; nothing moves.
- Not an ORM. JSON schema validation only.
- Not where ML training lives. Training pipeline (when built v1.x) reads
  the unified stream as one of its many inputs, but doesn't own this
  schema.

---

## 6. Open Marketplace Platform — v0.85 → v1.0

**Theme**: vibe-IC starts as a private platform with internal contributors
(us). The end state is an OPEN platform where the world publishes three
plugin layers and the IC Expert Agent + the 33-step flow consume them.
This section is a forward-looking architecture, not a v0.78 / v0.80
commitment. Builds on the primitives already shipped in §§ 3-5.

### 6.1 The three plugin layers

Each layer extends infrastructure that already exists. None is greenfield.

| Layer | What gets published | Existing primitive it extends | Open-platform additions |
|-------|---------------------|-------------------------------|-------------------------|
| **L_exp — Experience** | K1-K5 entries, PRACTICAL_NOTES, T5/T6 captures, decision_log fragments | § 5 unified `experience_unit` view + § 3.7 pattern_effectiveness_eval | manifest + signing + namespace + trust tier |
| **L_ip — IC IP** | hard / firm / soft IP blocks with `ip_metadata.yaml` | § 4.1 `ip-instantiate` skill (the consume side) | vendor publish SDK + IP registry + encrypted-RTL handling + version graph |
| **L_eda — EDA tool / device** | new MCP tools (Cadence, Synopsys, Synaptics, scope/JTAG instruments) | mcp-eda-server (20 EDA + 6 device tools today) | per-call billing + capability advertisement + 3rd-party API-key delegation |

The unifying claim: **`pattern_effectiveness_eval` is the platform's
immune system.** Whatever a third-party publishes — a K3 entry, a hard-IP
block, a new `eda_pnr_proprietary` tool — its real-world impact on
SCOREBOARD pass-rate is measured automatically. Harmful contributions are
auto-demoted by the same gate that already protects internal patterns.
This is what makes the platform safely open.

### 6.2 Plugin manifest (cross-layer)

One manifest schema covers all three layers. Stored at the root of any
plugin bundle as `plugin.yaml`:

```yaml
# plugin.yaml — root of every published plugin bundle
plugin_id: "arm-cortex-m0-r1p2"          # globally unique within a namespace
namespace: "arm"                          # vendor / org / community handle
layer: ip                                 # exp | ip | eda
version: "1.0.3"                          # semver
schema_version: "vibe-ic-plugin/v1"       # contract version of THIS file

publisher:
  org: "Arm Ltd."
  contact: "ip-support@arm.com"
  trust_tier: vendor-verified             # see § 6.3 — set by platform, not publisher

provenance:
  source_kind: licensed-binary            # internal / open-source / licensed-binary
  built_from: "git@arm.com:cortex-m0:v1.0.3"
  signature: "sha256:b66585d1..."         # detached sig over the bundle
  signing_key: "arm-publisher-2026-04"

depends_on:                               # optional dependency graph
  - {plugin_id: "amba-axi-vip-r0p3", version: ">=1.0.0"}

billing:                                  # optional; absent = free
  model: per-call                         # per-call | flat-monthly | one-time
  currency: USD
  per_call_cents: 50                      # only meaningful for L_eda
  vendor_share_pct: 80                    # platform takes 100-vendor_share_pct

# layer-specific payload
ip:                                       # only present when layer == ip
  deliverable_kind: hard-ip
  metadata: ./ip_metadata.yaml            # § 4.1 schema
  artifacts:
    lib: ./files/cortex-m0.lib.enc        # encrypted on-disk; key fetched via API
    lef: ./files/cortex-m0.lef.enc
    gds: ./files/cortex-m0.gds.enc
```

### 6.3 Trust tiers — how IC Expert Agent weights contributions

Every plugin gets a `trust_tier` assigned by the platform (not the
publisher). The IC Expert Agent uses this to *weight*, not to *gate*:

| Tier | How earned | Weight in proposer/consumer | Visible to user as |
|------|------------|------------------------------|--------------------|
| `core` | Shipped with vibe-ic-core | 1.0 (baseline) | (no badge) |
| `vendor-verified` | Org passed identity + signing-key audit | 1.0 | "✓ Verified vendor" |
| `community-trusted` | ≥10 ICs successfully used the plugin AND `pattern_effectiveness_eval` verdict ≠ harmful | 0.8 | "✓ Community-trusted (n=12)" |
| `community` | Published, no negative signal | 0.5 | "Community" |
| `experimental` | New, < 3 ICs of evidence | 0.3 | "⚠ Experimental" |
| `quarantined` | `pattern_effectiveness_eval` says HARMFUL | 0.0 (not consumed) | "⊘ Quarantined — see report" |

**Wired into existing components:**
- § 3.1 K3 patch proposer reads `trust_tier` of its source. A `core` K3 entry
  outweighs a `community` one when conflicts arise — but the *measurement*
  (pass-rate impact) wins over both.
- § 3.7 `pattern_effectiveness_eval` is what *changes* tiers automatically:
  HARMFUL verdict → `quarantined`; sustained HELPFUL across 10+ ICs →
  `community-trusted`. Nightly recomputation.
- Customer can override via `--trust-allow @org` / `--trust-block @org` in
  CLI; recorded in provenance.

### 6.4 Layer 1: Experience plugin (L_exp)

External orgs (other IC design houses, universities, individual experts)
publish their distilled K1-K5 entries / PRACTICAL_NOTES / T5+T6 captures.
The unified `experience_unit` view from § 5 is the on-the-wire shape.

**Publish flow:**
```bash
# inside contributor's training repo (already has its own training pipeline)
vibe-ic plugin pack experience \
    --include "k3/spi-peripheral.yaml" \
    --include "practical_notes/spi-peripheral.md" \
    --include "experience_units/t5_*.yaml" \
    --namespace nccu-icdesign-lab \
    --version 0.4.0 \
    --sign ~/.vibe-ic/keys/nccu-2026.pem \
    --out nccu-spi-experience-0.4.0.tgz

vibe-ic plugin publish nccu-spi-experience-0.4.0.tgz
```

**Install + use:**
```bash
vibe-ic plugin install nccu-icdesign-lab/spi-experience@0.4.0
# IC Expert Agent now sees the new K3 entries with trust_tier=community
# until pattern_effectiveness_eval has data.
```

**Key design choice:** *no merge into core K3.* External experience lives
in a separate namespace and is queried alongside core. This means:
- A community K3 entry NEVER overwrites a core entry; both are visible.
- Removing/unpublishing a third-party plugin removes its contribution
  cleanly — no merge-back-out problem.
- IC Expert Agent's "where did this default come from?" trace points to
  `nccu-icdesign-lab/spi-experience@0.4.0`, not "anonymous K3".

### 6.5 Layer 2: IC IP plugin (L_ip) — the publish side of § 4.1

§ 4.1 specified the *consume* side: the `ip-instantiate` skill takes a
`.lib + .lef + .gds + ip_metadata.yaml` quadruple and integrates it. § 6.5
specifies the *publish* side: how an IC vendor lists their IP on the
platform so anyone running vibe-ic can `ip-instantiate` it.

**Vendor SDK** (one CLI tool):
```bash
vibe-ic ip pack \
    --lib /path/to/your/block.lib \
    --lef /path/to/your/block.lef \
    --gds /path/to/your/block.gds \
    --metadata /path/to/your/ip_metadata.yaml \
    --license-terms ./LICENSE.md \
    --encrypt-with-platform-key \         # encrypted; decrypt happens at install time
    --out my-uart-ip-1.2.3.tgz

vibe-ic ip publish my-uart-ip-1.2.3.tgz
```

**Encrypted RTL handling** (for licensed IP that can't ship in the clear):
- Plugin bundle ships encrypted artifacts.
- At install time, customer's vibe-ic CLI fetches a per-customer decryption
  key from the platform after license validation.
- Decrypted artifacts live ONLY in customer's local working dir; never
  re-uploaded.
- This mirrors how Synopsys / Cadence ship reference IP today; we just
  standardize the protocol.

**IP registry behaviour:**
- Search: `vibe-ic ip search "uart"` → returns hits across all namespaces
  with capability + trust_tier + pricing visible.
- Compare: `vibe-ic ip compare arm/uart-pl011 nccu/uart-fast` → side-by-side
  on metadata fields.
- Resolve: `depends_on:` graph resolved at install time, like npm.

**License boundary** (extends § 4.6):
- License *terms* are part of the bundle (`LICENSE.md`).
- License *enforcement* is platform-side at install time (does this customer
  have a current entitlement?). Customer-side audit logging stays the
  customer's responsibility.

### 6.6 Layer 3: EDA tool / device plugin (L_eda)

mcp-eda-server today has 20 EDA + 6 device tools, all built by us. The
open-platform extension lets third parties (Cadence, Synopsys, Mentor,
instrument vendors) publish their own MCP tools that drop into the same
flow.

**Standard contract** — every L_eda plugin must:
- Implement the MCP tool spec (already what mcp-eda-server does)
- Declare `supported_platforms` (already required by current spec)
- Emit the standard `DeviceError` taxonomy on failure (already required)
- Report per-call cost in the response when `billing.model == per-call`

**Capability discovery** (already partially built):
- mcp-eda-server already filters tools by `supported_platforms`.
- New: tools also declare `capabilities: [synth, pnr, sta, gds, drc, lvs,
  dft, equiv, formal, simulate, fpga_compile, scope, jtag]` so the 33-step
  flow can substitute a third-party tool for a built-in one when both
  declare the same capability.

**Example: Synopsys Design Compiler as a plugin:**
```yaml
plugin_id: "dc-shell-2025.06"
namespace: "synopsys"
layer: eda
publisher: {org: "Synopsys, Inc.", trust_tier: vendor-verified}
billing: {model: per-call, currency: USD, per_call_cents: 1500}
eda:
  mcp_tool_name: "eda_synth_dc"
  capabilities: [synth]
  supported_platforms: [linux-x86_64]
  requires_license_server: true             # platform forwards SNPSLMD_LICENSE_FILE
  vendor_endpoint: "https://api.synopsys.com/vibe-ic/dc/v1"
```

When the user runs `eda_workflow_run --step synth`, the workflow sees both
`eda_synth` (built-in Yosys) and `eda_synth_dc` (Synopsys plugin) advertise
the `synth` capability. Customer chooses by default-tool config or per-run
flag; provenance records which one was used.

**Per-call billing:**
- Platform meters every MCP call when `billing.model == per-call`.
- Vendor receives `vendor_share_pct` of the per-call price.
- Customer sees a session cost summary in the workflow report.
- Free tools (`billing` absent) work as today; no metering overhead.

### 6.7 Governance — what the platform must arbitrate

Open marketplaces fail when governance is undefined. Minimum scope:

| Question | Answer |
|----------|--------|
| Who can publish? | Any account that completes identity verification + signs the publisher agreement. |
| What can be unpublished? | Vendor can yank any of their own versions; existing installs continue to work (cached). |
| What if a plugin is harmful? | `pattern_effectiveness_eval` HARMFUL verdict → auto `quarantined` tier. Vendor sees the report and can dispute. |
| Disputes? | One round of vendor rebuttal allowed; if `pattern_effectiveness_eval` re-verdicts HARMFUL with new data, quarantine stands. |
| Malicious / illegal content? | Platform takedown right reserved (per terms-of-service); takedown reasons logged publicly with anonymized stats. |
| What about forks? | A community fork is a NEW `plugin_id` in a NEW namespace — no inheritance of trust_tier. |
| Naming conflicts? | First-come within a namespace; namespaces themselves are first-come per identity-verified org. |

### 6.8 What this is NOT

- **Not a closed marketplace.** No exclusivity, no platform-only IPs, no
  forced revenue share for free tools.
- **Not auto-merge of community contributions into core.** Core stays
  curated by the vibe-ic team. Community plugins live alongside core; the
  IC Expert Agent reads both and weights by trust_tier.
- **Not a license-enforcement engine for the world.** Platform validates
  entitlement at install time; downstream auditing stays the customer's
  problem (same posture as § 4.6).
- **Not a replacement for human review.** Every cross-layer change still
  flows through `pattern_effectiveness_eval` first and through PR review
  on the customer side. The marketplace lowers the cost of distributing
  trustworthy contributions; it does not lower the bar for what counts as
  trustworthy.
- **Not a v0.78 deliverable.** v0.78 is internal distillation hardening.
  The marketplace surface itself is v0.85+ work; primitives shipped today
  are what make it tractable later.

---

## 7. Risks and trade-offs

| Risk | Mitigation |
|------|------------|
| K3 patch proposer hallucinates "improvements" | Human-merge gate stays. The agent's job is to draft, not to merge. v0.77 commit demonstrates the target output shape. |
| Phase-2b → K3 reflux pollutes `typical_structure` with chip-specific bugs | New `bug_classes:` field is generalized first (the existing v0.75 specificity meta-gate runs against it) before merge. |
| Decision-log auto-extraction misclassifies log lines | v0.79 phase is hand-fill only. Log-extraction in v0.80 falls back to "unknown decision" rather than guess. |
| Pad ring step adds tapeout-day surprises | Step 14.5 ships behind a flag for the first 3 ICs; gated to "informational only" until 3 successful tapeouts. |
| Hard-IP `.lib/.lef/.gds` triplet hard to validate without instantiating | `eda_ip_lib_audit` is a smoke check (file existence + version-string parity), not full verification. |
| ARM Cortex-M license discovery (downstream) | Provenance log records `--license-tag`; no enforcement at platform layer. Customer responsible. |
| Nightly T4 (FPGA) wall-clock outpaces machine availability | Rotate which subset of 15 ICs runs each night; full set every 2-3 nights. T5 bench is the real bottleneck, not T4. |
| Unified experience-unit view balloons in size | Adapters lazy-emit; queries push down filters. View materialisation is opt-in. |
| Single-stage decision regression overfits at <50 samples per decision point | v0.79 reports `n_samples` next to every prediction; consumers ignore predictions where n<50. |
| (§ 6) Community Experience plugin floods K3 with low-signal patterns | `pattern_effectiveness_eval` runs nightly; `community` tier weighted 0.5 vs `core` 1.0; harmful → auto `quarantined`. Trust tier is automatic, not editorial. |
| (§ 6) Vendor disputes a HARMFUL pattern_effectiveness verdict | One-round rebuttal with new evidence (more SCOREBOARD samples). Re-verdict either restores tier or sustains quarantine. No appeal beyond data. |
| (§ 6) Encrypted hard-IP key leak | Per-customer keys; never re-uploaded; rotation supported. Same posture vendors already use today (Synopsys/Cadence reference IP). |
| (§ 6) Per-call EDA billing exposes customer designs to vendor servers | Customer can opt out — only the metering counter goes to the platform; the design payload stays local when `vendor_endpoint` is omitted (vendor tool runs customer-side, not vendor-side). |
| (§ 6) Namespace-squatting | First-come per identity-verified org only; squatting on org names without verification is rejected at registration. |

---

## 8. Side-fix shipped with this proposal

`tools/training/render_human_docs.py` (v0.78-pre):

- New `is_phase1_doc_set(gen_dir)` guard — refuses any `generated_docs/`
  whose parent has `input/` (Phase-2a vendor docs marker) and lacks
  `01_prompt.md` / `02_dialog.md` / `phase1_fg_trace.json` markers OR a
  `phase1_*` ancestor.
- `--all` mode now skips non-Phase-1 dirs with a count summary instead of
  rendering into them.
- Single-target mode refuses non-Phase-1 dirs with an explicit reason; can be
  overridden with `--force`.
- New `--report-leaked` mode lists existing stale `human_docs/` siblings in
  non-Phase-1 dirs (does not delete — manual cleanup).

`tools/training/regression_suite.py`: docstring tightened to clarify gate 4
checks Phase-1 generated_docs only.

This makes the user-stated invariant — *"`human_docs/L*.md` belongs to Phase 1
only; Phase 2a already has human-readable vendor docs"* — a code-enforced
contract instead of an unwritten convention.

---

## 9. Sequencing

| Release | Theme | Items | Status |
|---------|-------|-------|--------|
| **v0.78** | Distillation hardening (proposer) | 3.1 IC-Expert K3 patch proposer (bidirectional MVP) + 3.4 T5 capture + 3.5 PRACTICAL_NOTES auto-proposer + 3.6 decision_log + first hand-filled v068 example | ✅ shipped 2026-04-26 (commits 2386780d, 47a7a656, 6457dd15, 638c0520) |
| **v0.78.1** | Pattern effectiveness validation | 3.7 scoreboard_to_csv + pattern_effectiveness_eval + k3_patch_proposer wiring (`--pattern-stats`) + per-IC score lookup (replaced placeholder) | ✅ shipped 2026-04-26 |
| **v0.79** | Phase-2b reflux + decision trace at scale | 3.2 bug_classes field (5 classes filled from real T5 verdicts) + 3.6 decision_log auto-extraction from yosys/OpenROAD logs + per-IC K3-consultation logging (refines § 3.7 to per-pattern granularity) | M |
| **v0.80** | IP integration spine | 4.1 ip-instantiate + ip_metadata.yaml + 4.2 step 13.5 + 4.4 K1/K3 entries | L |
| **v0.81** | Pad ring + unified experience view | 4.3 step 14.5 + § 5 experience-unit adapters | M |
| **v0.82** | RF / wireless first cut | rf-frontend class + first BLE black-box demo + § 5 view query consumers | XL |
| **v0.85** | Open-platform foundations (§ 6) | plugin.yaml schema + signing + namespace + trust tiers + `vibe-ic plugin` CLI (pack/publish/install/search) — single-namespace pilot first | ✅ shipped 2026-04-26 (D1-D8 complete; bench gate 8/8) |
| **v0.90** | L_exp Experience marketplace | HTTP registry protocol + reference server (deployable to vibeic.ai) + nightly trust-tier recompute | ✅ shipped 2026-04-26 (registry API + ref server + recompute job; gate 13/13) |
| **v0.95** | L_ip IP marketplace | AES-256-GCM encrypted artifacts + `vibe-ic plugin ip` subcommands + install --ip-key auto-decrypt | ✅ shipped 2026-04-26 (encrypted-RTL flow + `ip` CLI; 14 tests) |
| **v1.0** | L_eda EDA marketplace + API freeze | MCP-tool auto-register on install (mcp_tools.json hand-off) + per-call billing rail (`billing.jsonl` + `billing record/report` CLI). API surfaces frozen for 1.0. | ✅ shipped 2026-04-26 (mcp_tool_registry + billing_log; 25 tests) |
| **v1.x** (deferred) | Silicon-grounded model | Success Probability Model trained on T6 labels (50+ tapeouts required first) | — |

---

## 10. Glossary cross-reference

- **Path A** = Phase 1 = prompt-driven. Produces `generated_docs/L*.json` +
  `human_docs/L*.md`.
- **Path B** = Phase 2a = existing-vendor-docs-driven. Produces
  `generated_docs/L*.json` only. Vendor docs in `input/` ARE the
  human-readable view.
- **K3** = `agents/defaults/class_reference.yaml`. Per-class typical_structure
  block, walked by IC Expert Agent during default-fill.
- **IC Expert Agent** = silicon-reviewer agent behind PM Agent; today
  consumes K3, v0.78 also drafts patches to it (bidirectional — both
  failure modes and proven patterns).
- **Hard IP** = `.lib + .lef + .gds` triplet, treated as black box.
- **Firm IP** = obfuscated RTL, treated as gray box (port shape known,
  internals hidden).
- **Soft IP** = parameterizable RTL — what current flow assumes for
  everything.
- **T0-T6** = distillation tier ladder (§ 3.4). T0-T4 are wall-clock-bounded,
  T5 needs human bench operator, T6 is silicon (fab + 8-10 weeks).
- **`auto_decided`** = IC Expert Agent's existing provenance trace
  (`{"provenance": {"auto_decided": true, "reason": "..."}}`). v0.78 elevates
  it from lint signal to first-class training signal.
- **`decision_log.jsonl`** = per-step `{decision, context, outcome}` triple
  written by Phase-2b/3 skills (§ 3.6). Hand-filled v0.79, log-extracted
  v0.80.
- **`ip_metadata.yaml`** = `{known_issues, integration_notes,
  historical_failure_modes, license_tag}` accompanying every IP deliverable
  (§ 4.1). IP is a knowledge carrier, not just a binary blob.
- **`experience_unit`** = unified view shape over all knowledge stores
  (§ 5.2). `{context, decision, outcome, lesson, provenance}`. Read-only
  projection, no migration.
- **L_exp / L_ip / L_eda** = the three open-platform plugin layers (§ 6.1).
  L_exp = Experience (K-store contributions), L_ip = IC IP (publish side
  of § 4.1), L_eda = EDA tool / device (third-party MCP tools).
- **Trust tier** = `core` / `vendor-verified` / `community-trusted` /
  `community` / `experimental` / `quarantined` (§ 6.3). Set by the
  platform from `pattern_effectiveness_eval` data, not by the publisher.
  IC Expert Agent uses tier as a *weight* in default-fill, not as a
  hard gate.
- **Namespace** = first-come per identity-verified org (e.g. `arm/`,
  `synopsys/`, `nccu-icdesign-lab/`). All plugin_ids live inside a
  namespace; conflicts resolved within, not across.
