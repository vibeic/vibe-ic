# vibe-ic — AI-Native IC Design plugin (**v1.15.42**)

**A deterministic program layer with AI-backup skills, driving spec → RTL → GDS.**

The plugin is no longer "compliance regexes over agent prose". It is **1337 top-level Python
programs** (1248 of them catalogued in [`programs/INDEX.md`](programs/INDEX.md); the other
89 are helper modules and shims) that run the flow, **60 skills** that back the programs up
where judgment is genuinely required, **6 slash commands**, **9 agents**, and
**3077 test files**. Programs decide; skills only fill the holes the programs
deliberately leave.

## ► The one front door

```bash
python3 programs/vibe_ic_one_shot_runner.py <project>
```

That single runner drives the whole chain:

| Phase | What runs |
|-------|-----------|
| **Phase 1** | NL prompt *or* vendor docs → `generated_docs/L*.json` (`L1-L23` emitted; the taxonomy in `programs/l_doc_taxonomy.py` extends to `L27`, with `L26`/`L27` opt-in only) |
| **Phase 2** (`2a` + `2b`) | RTL gen → hygiene lint → testbench gen → yosys synth → SDC/QSF → spec conformance → RTL repair/retry loop (`rtl_repair_retry`) → final audit |
| **Analog** | `A1..A8` from the top-level runner; `programs/analog_one_shot_runner.py` implements the full `A1-A9` (through `A9_hw_verify`) |
| **Phase 3** | synth → PnR → CTS → GDS → DRC / LVS / STA / IR-drop |

Mixed-signal `M1-M4` is a **reporting** track (`final_report_generate.py`,
`benchmark_verify_report.py`, `flow_dashboard*.py`), not a phase the runner schedules.

Flags: `--top-name --container --max-rtl-repair-retries --skip-phase1 --skip-analog --skip-phase3
--skip-hardware --die-um --util --pdk --allow-oss-pdk-fallback --ic-name
--dashboard[-port|-host|-full]`.

### Program-first, AI-backup

Dispatch is deterministic first. `programs/ic_class_registry.json` holds **13 IC
classes**; **2** have a deterministic generator (`aid_class_rtl_gen.py`), and **11**
have `rtl_gen: null`. Of those 11, **10** carry `fallback_skill: "spec-to-rtl"` —
`design_one_shot_runner.step_rtl_gen` returns `status="WAIVED"` with that skill name in
`extras`, the AI authors RTL into the path the runner already computed, and the runner's
own gates (chip-top emit, `rtl_hygiene_lint --fix`, `eda_lint`, `eda_synth`, `rtl_repair_retry`,
`spec_conformance_check`, `full_stack_tb_gen`) then fire around it. `pure_analog` has
`fallback_skill: null` — it routes to the analog track instead. A sibling path waives to
`catalog-glue-author` when reused open-source IP matches.

**This is the intended path, not a bypass.** Authoring RTL with MCP tools *outside* the
runner skips every gate.

## ► Running open benchmarks

Need to score Vibe-IC against an open benchmark (VerilogEval-v2 / VerilogEval-Human /
RTLLM / CVDP / etc.)? Use the **`/vibe-ic-benchmark`** front door:

```bash
# Discover
/vibe-ic-benchmark --list                                # all known benchmarks + shape + status
/vibe-ic-benchmark rtllm                                 # show plan + env check

# Run (per the recommended commands the plan prints)
git clone https://github.com/hkust-zhiyao/RTLLM ~/datasets/RTLLM
/vibe-ic-benchmark rtllm --solve --dataset ~/datasets/RTLLM --run ~/runs/r1
# … complete the runner-declared AI backup/review worklists, then resume
/vibe-ic-benchmark rtllm --resume --dataset ~/datasets/RTLLM --run ~/runs/r1
/vibe-ic-benchmark rtllm --score --dataset ~/datasets/RTLLM --run ~/runs/r1
```

**MUST READ FIRST** — the [`open-benchmark-methodology`](skills/open-benchmark-methodology/SKILL.md)
skill is the source of truth for the one general product entry,
tool-substitution disclosure (iverilog↔VCS, etc.), and evidence-backed triage.
A `UserPromptSubmit` hook auto-injects a reminder when any benchmark keyword
appears in your message. **Don't bypass it.**

Entry points:
- **Open RTL evaluations**: `benchmark_dispatch.py --solve` → the normal
  `vibe_ic_one_shot_runner.py`; only input/output and official-scorer adapters
  vary by dataset.
- **Full IC evaluations**: `/vibe-ic-all <project>` + `benchmark-verify`.
- **Blocked / out-of-scope datasets**: document only; do not publish a number.

See `benchmark/README.md` for the full harness orientation and per-benchmark quickstarts.

---

## What it does

When different AI agents execute the same `vibe-ic` skill, they
sometimes skip required sections, omit metadata fields, or forget the
hand-off block — producing outputs that differ in completeness, not just
in wording. This plugin makes execution **content-deterministic**:

> Different agents executing the same skill always ship outputs containing
> the same required elements, even when the prose inside each element
> varies.

That original guarantee still holds at the skill boundary. Above it, the program layer
now does the actual work, so the far larger guarantee is that a verdict is backed by an
artifact on disk — see **Honesty gates** below.

## 3-Layer Verification Architecture

| Layer | Mechanism | What it catches |
|-------|-----------|----------------|
| **L1 — compliance.yaml** | Regex patterns on agent text output | Missing sections, missing keywords |
| **L2 — Deterministic programs** | Artifact checks (files, JSON, RTL, reports) | Agent claims without evidence |
| **L3 — mcp_execution_verify** | MCP tool execution proof via manifest | Agent faking tool runs |

Measured over the 60 skills: **60/60** ship a `compliance.yaml` (L1), **33/60** declare a
non-empty `cross_checks:` block (L2), **6/60** wire `mcp_execution_verify` (L3).
Coverage is deliberately uneven — advisory/methodology skills have no artifact to check,
which is the physical limit of the approach, not a backlog item.

## Honesty gates

The verification layer refuses to report a pass it cannot back. These are real gates with
tests, not doctrine:

| Gate | Program | Refusal |
|------|---------|---------|
| **Vacuous full-stack TB** | `programs/bit_level_full_stack_tb_check.py` | 0 golden-scored vectors cannot satisfy the functional pillar. When L3 declares no opcode protocol but L4/L5 declare a memory-mapped register file, the run emits `FUNCTIONAL_COVERAGE_GAP` instead of `vacuous_pass`. `bit_level_full_stack_tb_oracle_check.py` additionally demands per-vector expected-vs-actual bytes an agent cannot fabricate. |
| **Silent PDK downgrade** | `programs/phase3_one_shot_runner.py` → `commercial_pdk_fallback_guard` | A configured commercial PDK that silently resolves to an in-container OSS enablement is **REFUSED** (`reports/phase3/pdk_resolution_refusal.json`, `verdict: REFUSED`). Otherwise Phase 3 emits authoritative-looking DRC/LVS sign-off built from the wrong std-cell library. Escape hatch is explicit: `--allow-oss-pdk-fallback`. |
| **Stale waiver** | `programs/waiver_staleness.py` + `waivers_materialize.py` | An `ENV_UNAVAILABLE` waiver's condition is `step_did_not_execute`. Once the step it excuses actually runs, the waiver is evicted — *"the step's real verdict stands; a failure is NOT excused."* |
| **NDA source guard** | `programs/source_chip_agnostic_check.py` | Literal grep-0 over the whole plugin tree: a forbidden token anywhere is exit 1, with exactly one encoded home and no allowlist. |
| **NDA commit-message guard** | `programs/commit_msg_nda_check.py` | A commit *message* is as public as a source file. Enforced at commit + pre-push time. |

Install the guards as git hooks (they do nothing until installed — `.git/hooks/` is not
tracked):

```bash
tools/install-git-hooks.sh          # symlinks tools/git-hooks/{commit-msg,pre-push}
tools/install-git-hooks.sh --force  # replace existing hooks
```

Complementary waiver gates: `waiver_legitimacy_check.py` (fake-reason patterns),
`waiver_staleness_check.py` (age ladder), `waiver_growth_check.py`, `waivers_schema_check.py`.

## PDKs

From `programs/pdk_registry.json`:

| PDK | Node | Notes |
|-----|-----:|-------|
| `sky130A` | 130 nm | open source |
| `gf180mcuD` | 180 nm | open source |
| `ihp-sg13g2` | 130 nm | open source |
| `nangate45` | 45 nm | **`tapeout_capable: false`** — NanGate / FreePDK45 Open Cell Library (Si2, Apache-2.0). A generic, non-foundry library for research and education. |
| `asap7` | 7 nm | **`tapeout_capable: false`** — ASU/ARM ASAP7 *predictive* academic PDK (BSD-3-Clause). Realistic but generic and non-foundry. |
| `custom_auto_detect` | — | `phase3_one_shot_runner.py` auto-detects site / metal prefix / clock buffer from a user-staged `<project>/input/pdk/`. |

NanGate45 and ASAP7 are **research/education enablements**. They produce real PPA numbers
and real DRC/LVS runs, but they are not foundry PDKs and nothing built on them is
tapeout-qualified.

**Commercial PDKs** are supported through a config-driven mechanism, never a checked-in
identifier: `programs/_commercial_pdk.py` resolves the PDK from the env var
`VIBEIC_COMMERCIAL_PDK_ID` or the private, gitignored
`~/.config/vibeic/commercial_pdk.json`. No foundry name, SKU, or process codename lives
in this repo — that is what the NDA guards above enforce.

## Forked EDA toolchain — `vibeic-eda`

The plugin runs its tools inside the `vibeic-eda` container (**0.2.23**), which layers
vibeic forks onto the [iic-osic-tools](https://github.com/iic-jku/iic-osic-tools) base.
Every fork is pinned to a commit SHA in the image `Dockerfile`, so a build is reproducible.

**12 independently pinned forks:** `OpenROAD`, `yosys`, `ngspice`, `magic`, `netgen`,
`iverilog`, `klayout`, `verilator`, `cocotb`, `cocotb-coverage`, `pyuvm`, `sby`.
A 13th — `OpenSTA` — rides in as OpenROAD's `src/sta` submodule, fetched from the
`vibeic/OpenSTA` fork rather than pinned on its own `ARG`.

Fork tracker (branches, fixes, upstream status): <https://vibeic.ai/eda-forks.html>

Configure the container with `EDA_CONTAINER` (default `vibeic-eda`, see `.mcp.json`).

## Parallel by default

The MCP `eda_*` tools wire the parallel flags **on** by default — each of these threadings
is result-invariant, so enabling them only makes the run faster, never different. The
default expands `$(nproc)` *inside* the container, so no core count is hardcoded.

| Tool | Flag | Where |
|------|------|-------|
| OpenROAD | `-threads max` | `mcp-eda/src/index.js` (PnR, retry, STA, IR-drop) |
| OpenSTA | `sta -threads max` | `mcp-eda/src/index.js` |
| KLayout | `-rd threads=$(nproc)` | tiled DRC, 3 call sites |
| cocotb | `make -j$(nproc)` | `mcp-eda/src/index.js` |
| ngspice | `OMP_NUM_THREADS=$(nproc)` | batch sim + corner sweep |
| verilator | `--build-jobs N` | `programs/design_one_shot_runner.py` (C++ build only; runtime `--threads` is deliberately not set) |

Override with the env var **`VIBEIC_EDA_THREADS`** (positive integer pins the count;
OpenROAD/OpenSTA otherwise get the literal `max`). Note the Phase-3 / MCP PnR path reads a
separate **`VIBEIC_OPENROAD_THREADS`** (`mcp-eda/src/lib/pnr_threads.mjs`,
`phase3_one_shot_runner.py`), so setting only `VIBEIC_EDA_THREADS` will not cap it.

## How it works

1. For every vibe-ic skill, the plugin ships a `compliance.yaml`
   that enumerates every required output element (section headers,
   metadata fields, tool invocations, hand-off lines) as a regex list.
2. A shared driver `_shared/skill_compliance_check.py` audits any
   agent-produced output against the YAML.
3. **1337 top-level deterministic programs** verify actual artifacts on disk — not
   just what the agent wrote in its report.

## Layout

At 1337 top-level programs, a hand-maintained per-bucket listing is not meaningful — the catalog is
generated instead. `programs/INDEX.md` is produced by `tools/gen_programs_index.py`, and a
CI freshness test diffs the regenerated index against the committed one and FAILs on drift.

```
plugins/vibe-ic/
├── README.md                      — this file
├── .claude-plugin/plugin.json     — plugin manifest (version lives here)
├── .mcp.json                      — registers the eda-tools MCP server
├── run_tests.sh                   — multi-tier local test runner
├── pytest.ini                     — --import-mode=importlib, testpaths=programs/tests
├── conftest.py                    — puts programs/ on sys.path regardless of cwd
├── _shared/
│   ├── skill_compliance_check.py  — generic YAML-driven audit driver
│   ├── bootstrap_compliance.py    — regenerates all compliance.yaml
│   ├── gen_compliance_tests.py    — regenerates all test_compliance.py
│   └── add_compliance_gate.py     — adds gate section to SKILL.md files
├── programs/                      — 1337 top-level *.py (1248 catalogued)
│   ├── INDEX.md                   — AUTO-GENERATED catalog; CI-checked for drift
│   ├── vibe_ic_one_shot_runner.py — THE front door
│   ├── phase1_one_shot_runner.py  — and phase1_doc_, phase2_, phase23_,
│   ├── phase3_one_shot_runner.py     design_, analog_ runners (10 total)
│   ├── ic_class_registry.json     — class → rtl_gen / fallback_skill dispatch
│   ├── pdk_registry.json          — per-PDK site / metal / deck conventions
│   ├── l_doc_taxonomy.py          — L1..L27 layer definitions
│   ├── _commercial_pdk.py         — config-driven commercial-PDK resolution
│   ├── gds_antenna/, metal_fill/  — sub-packages
│   └── tests/                     — 3077 test files
├── skills/                        — 60 skills, each with SKILL.md + compliance.yaml
│   └── <skill>/tests/             — 82 per-skill compliance regression files
├── commands/                      — 6 slash commands + _anti_fabrication_rules.md
├── agents/                        — 9 agents (ic-expert, core, field, gatekeeper,
│                                    repo-gatekeeper, benchmark, 3 personas)
├── mcp-eda/                       — the eda-tools MCP server (Node)
├── hooks/                         — incl. the benchmark-methodology UserPromptSubmit hook
├── ip-catalog/                    — reusable open-source IP index
└── benchmark/                     — harness scaffolding
```

## Test suite

**3077 test files** under `programs/tests/`, plus **82** per-skill compliance regressions
under `skills/*/tests/`.

Run it the CI way — a bare `pytest` from the plugin root, exactly as
`.github/workflows/ci.yml` and `gatekeeper-ci.yml` do:

```bash
cd vibe-ic-marketplace/plugins/vibe-ic
pytest -q --maxfail=10
```

Never `pytest programs/tests/` alone — a path filter skips the integration gates
(INDEX freshness, every-skill-has-compliance, orchestrator branch regressions).
`run_tests.sh` is the local multi-tier variant that also walks `skills/*/tests/`.

The gatekeeper workflow layers on `plugin_full_audit.py` (D1: every program has a test;
D2: every flow step has a compliance checker) and, at `x.y.0` milestones only, the
both-tree full suite.

## Usage

### For agents executing a skill

After producing output:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/<skill>/compliance.yaml \
    <agent_output_file>
```

- Exit code **0** = PASS, task is complete.
- Exit code **1** = FAIL — stdout lists missing elements.
- Exit code **2** = ERROR (file not found).

### Running deterministic programs

```bash
python3 programs/constants_validation.py /path/to/project
python3 programs/eda_report_audit.py /path/to/project --mode drc
python3 programs/signoff_audit.py /path/to/project --mode tapeout
```

## Schema of `compliance.yaml`

```yaml
skill: <skill-name>
requirements:
  - id: R_violation_categories
    description: "DRC violations grouped by rule family"
    pattern: '(spacing|width|density|antenna|enclosure)'
    skill_section: 'Violation Classification'
cross_checks:
  - id: X_drc_report_check
    description: "Verify DRC report has violation categories and counts"
    rule: postcheck_pass_only
```

## Provenance

The compliance discipline was extracted from a **real FPGA protocol
verification debug session (2026-04)**, where 11 distinct bugs were
traced to SKILL.md sections that agents skipped silently. It grew through a
10-IC benchmark (v0.38), IC expert review (v0.39), and the 3-layer verification
architecture (v0.40).

Everything since has come from the same loop, run continuously: drive real ICs and open
benchmarks through the flow, find where an AI judgment call rescued a run, and absorb
that judgment back into a deterministic program with a regression test. That is why the
program count moved from 41 at v0.40 to 1337 top-level programs today — and why
the honesty gates exist at all. Each one was written after a real run reported a
pass it could not back.

## License

MIT
