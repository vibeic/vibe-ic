# vibe-ic — AI-Native IC Design plugin (**v1.40.18**)

**Design rules: [CHARTER.md](CHARTER.md).** Fixed by the owner: use the tools, judge on their native results, add no self-imposed gates.

**A deterministic program layer with AI-backup skills, driving spec → RTL → GDS.**

The plugin is no longer "compliance regexes over agent prose". It is **782 top-level Python
programs** (672 of them catalogued in [`programs/INDEX.md`](programs/INDEX.md); the other
110 are helper modules and shims) that run the flow, **70 skills** that back the programs up
where judgment is genuinely required, **7 slash commands**, **9 agents**, and
**2917 test files**. Programs decide; skills only fill the holes the programs
deliberately leave.

## ► The one front door

Run from the plugin directory:

```bash
python3 programs/vibe_ic_one_shot_runner.py <project> \
  --route ic --delivery-target shippable_gds
```

The public entry uses `flow_engine_frontend.py` and `flow_engine.py` for every
run. The executable rows live in [`flow/steps.json`](flow/steps.json); their
original numerical limits live in
[`flow/native_limits.json`](flow/native_limits.json). The Router selects the
applicable work for the requested delivery endpoint.

Use `--route ip --delivery-target ip_hardmacro` for an IP hardmacro, or
`--delivery-target rtl` for a bounded RTL task. Explicit windows require both
`--entry-step` and `--exit-step`; use current table names. `--rtl-input original`
selects original RTL input rather than the structured-document input contract.
There is no engine selector or feature-manifest requirement.

| Engineering area | What runs when applicable |
|---|---|
| Requirements | Natural-language input or design documents to layered specifications |
| RTL | Authoring, lint, simulation, formal verification, synthesis and constraints |
| Analog | Topology/sizing, native SPICE/PVT, layout, DRC/LVS, extraction, resimulation and hardmacro packaging |
| Physical design | Floorplan/PDN, placement, CTS, routing, extraction, STA and final GDS checks |
| Mixed signal | Native analog/digital integration, co-simulation and physical/electrical checks |
| Hardware/delivery | Required board measurements, provider precheck and the selected IP or IC package |

Other public options include `--pdk`, `--ic-name`, `--top-name`, `--container`,
`--mode`, `--execution-mode default`, `--skip-phase1`, `--skip-phase2`,
`--skip-phase3`, `--skip-analog`, `--skip-hardware`, and `--no-dashboard`.
Use `python3 programs/vibe_ic_one_shot_runner.py --help` for the full parser.

### Execution and review

[`flow/phase1_phase2_phase3.yaml`](flow/phase1_phase2_phase3.yaml) provides the
canonical user-facing names and positions. Report the 1-based position and
step name, retaining the same numbering through conditional paths. The native
engine follows the executable table and its applicability predicates.

The tool runs first. PASS means its native result meets the original limit;
FAIL means the measured result violates it. Missing execution or reports are
NOT_MEASURED. AI runs the flow end to end and reviews every native result. A
problem is fixed in the design, the tool or the plugin, then the affected work
is rerun. Limits do not move, and bounded results do not establish whole-chip
acceptance.

### Program-first, AI-backup

RTL authoring and verification run through the selected public window.
Deterministic authoring acts first; when it cannot complete the design, AI
backup supplies the missing RTL and the native verification work runs again.
Reusable IP can use the `catalog-glue-author` skill.

Open RTL benchmarks retain independent blind AI review and backup, executable
challenges for blocking obligations, and the official scorer. Actors read only
the problem input and provided context, never the oracle, harness or golden.

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
- **Full IC evaluations**: `/vibe-ic-all <project> --route ic
  --delivery-target shippable_gds` plus `benchmark-verify`; a bounded result
  applies only to its selected window.
- **Blocked / out-of-scope datasets**: document only; do not publish a number.

See `benchmark/README.md` for the full harness orientation and per-benchmark quickstarts.

---

## Native results and expert review

The EDA tools perform the engineering. Thin flow adapters invoke them, read
their reports and compare measured values with the specification or PDK limit.
Native DRC/LVS, STA, IR/EM, simulation and physical measurements remain the
authority for their respective results. Missing measurements stay explicit.

Skills provide design craft and AI backup where the tools cannot author or
interpret the design. AI reviews the actual output and fixes problems without
adding receipts, source-identity checks or hash chains around native results.
See [CHARTER.md](CHARTER.md) for the owner's rules.

## PDKs

From `programs/pdk_registry.json`:

| PDK | Node | Notes |
|-----|-----:|-------|
| `sky130A` | 130 nm | open source |
| `gf180mcuD` | 180 nm | open source |
| `ihp-sg13g2` | 130 nm | open source |
| `nangate45` | 45 nm | **`tapeout_capable: false`** — NanGate / FreePDK45 Open Cell Library (Si2, Apache-2.0). A generic, non-foundry library for research and education. |
| `asap7` | 7 nm | **`tapeout_capable: false`** — ASU/ARM ASAP7 *predictive* academic PDK (BSD-3-Clause). Realistic but generic and non-foundry. |
| `custom_auto_detect` | — | Native PDK resolution reads site, metal, clock and model settings from a user-staged `<project>/input/pdk/`. |

NanGate45 and ASAP7 are **research/education enablements**. They produce real PPA numbers
and real DRC/LVS runs, but they are not foundry PDKs and nothing built on them is
tapeout-qualified.

**Commercial PDKs** are supported through a config-driven mechanism, never a checked-in
identifier: `programs/_commercial_pdk.py` resolves the PDK from the env var
`VIBEIC_COMMERCIAL_PDK_ID` or the private, gitignored
`~/.config/vibeic/commercial_pdk.json`. No foundry name, SKU, or process codename lives
in this repo. Keep private PDK configuration outside the public tree.

## Forked EDA toolchain — `vibeic-eda`

The plugin runs its tools inside the configured `vibeic-eda` container, which layers
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
the native physical-design adapters), so setting only `VIBEIC_EDA_THREADS` will not cap it.

## How it works

1. The Router selects the task's delivery endpoint and bounded work.
2. The engine evaluates the step table's applicability predicates and runs the
   corresponding native command or adapter.
3. **782 top-level deterministic programs** verify actual engineering results
   and provide the design work that the tools do not supply.
4. AI reads every result, fixes problems and resumes the affected work.

## Layout

At 782 top-level programs, a hand-maintained per-bucket listing is not meaningful — the catalog is
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
├── programs/                      — 782 top-level *.py (672 catalogued)
│   ├── INDEX.md                   — AUTO-GENERATED catalog; CI-checked for drift
│   ├── vibe_ic_one_shot_runner.py — THE front door
│   ├── flow_engine_frontend.py    — shared public CLI and Router selection
│   ├── flow_engine.py             — executable step-table engine
│   ├── flow_native_adapters.py    — native tool invocations and measurements
│   ├── ic_class_registry.json     — class → rtl_gen / fallback_skill dispatch
│   ├── pdk_registry.json          — per-PDK site / metal / deck conventions
│   ├── l_doc_taxonomy.py          — L1..L27 layer definitions
│   ├── _commercial_pdk.py         — config-driven commercial-PDK resolution
│   ├── gds_antenna/, metal_fill/  — sub-packages
│   └── tests/                     — 2917 test files
├── skills/                        — 70 skills, each with SKILL.md + compliance.yaml
│   └── <skill>/tests/             — 81 per-skill compliance regression files
├── commands/                      — 7 slash commands + _anti_fabrication_rules.md
├── agents/                        — 9 agents (ic-expert, core, field, gatekeeper,
│                                    repo-gatekeeper, benchmark, 3 personas)
├── mcp-eda/                       — the eda-tools MCP server (Node)
├── hooks/                         — incl. the benchmark-methodology UserPromptSubmit hook
├── ip-catalog/                    — reusable open-source IP index
└── benchmark/                     — harness scaffolding
```

## Test suite

**2917 test files** under `programs/tests/`, plus **81** per-skill compliance regressions
under `skills/*/tests/`.

Run tests from the plugin root:

```bash
cd vibe-ic-marketplace/plugins/vibe-ic
pytest -q --maxfail=10
```

A path filter selects only that part of the suite. `run_tests.sh` is the local
multi-tier variant that also walks `skills/*/tests/`. Record the scope of the
run when reporting its result.

### Inventory maintenance

The program catalogue and documented program/test counts are derived from the
tree. Regenerate and check them from the plugin directory:

```bash
python3 programs/gen_program_inventory.py
python3 programs/gen_program_inventory.py --check
```

A test run establishes only the suites and environment actually exercised.
Report existing failures, skipped hardware work and unmeasured tool results
alongside its outcome.

## Usage

### For agents executing a skill

Skills describe the engineering work and review to perform. Their text-format
requirements can be checked from the plugin directory:

```bash
python3 _shared/skill_compliance_check.py \
    --requirements skills/<skill>/compliance.yaml <agent_output_file>
```

This checks the written format. Engineering completion follows the native
measurements and expert review described in the design charter.

### Running deterministic programs

```bash
python3 programs/vibe_ic_one_shot_runner.py /path/to/project --delivery-target rtl
python3 programs/eda_report_audit.py /path/to/project --mode drc
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
program count moved from 41 at v0.40 to 782 top-level programs today — and how
real runs have shaped the implementation. Current execution follows the owner's
design charter and uses native tool results against original limits.

## License

MIT
