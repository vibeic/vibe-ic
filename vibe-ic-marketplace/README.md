# Vibe-IC Marketplace

**AI-Native IC Design plugin for Claude Code — Vibe Coding for ASIC**

> From natural-language dialogue (or existing design documents) to a GDS
> hand-off, driven by AI agents with EDA tools as callable execution engines —
> **with machine gates that catch fabricated artefacts**.

This repository is the **marketplace**: the `.claude-plugin/marketplace.json`
catalogue, the plugin itself, reference plugins for third-party publishers,
and the contribution guides for extending it.

| | |
|---|---|
| Plugins in this marketplace | **1** — [`plugins/vibe-ic`](plugins/vibe-ic/) |
| Plugin version | **1.15.66** |
| Deterministic programs | **1345** top level (`plugins/vibe-ic/programs/*.py`), of which **1253** are catalogued in [`INDEX.md`](plugins/vibe-ic/programs/INDEX.md) |
| Skills | **60** (`plugins/vibe-ic/skills/*/SKILL.md`, each with a `compliance.yaml`) |
| Slash commands | **7** (`plugins/vibe-ic/commands/*.md`) |
| Agents | **9** (`plugins/vibe-ic/agents/*.md`) |
| MCP-EDA tools | **56** (48 EDA + 7 lab-device + 1 health) |
| Canonical flow | **68 steps** across **8 stages** (`plugins/vibe-ic/flow/phase1_phase2_phase3.yaml`) — 26 of them conditional, including the cell/IP vs chip/IC split |
| Test files | **3103** under `plugins/vibe-ic/programs/tests/` + **49** under `plugins/vibe-ic/mcp-eda/test/` (`test_*.py`, any depth) |
| License | Apache-2.0 |

Every count above is generated, not typed: `python3 plugins/vibe-ic/programs/gen_program_inventory.py` writes [`PROGRAM_INVENTORY.json`](plugins/vibe-ic/programs/PROGRAM_INVENTORY.json), and `--check` fails when a stated count drifts from the tree. Several of these populations are simultaneously true and count different things — the artefact carries a `definition` for each, so quote the key, not a bare number.

---

## What is Vibe-IC?

Vibe-IC brings the "Vibe Coding" paradigm to IC design. Instead of manually
driving dozens of EDA tools through arcane TCL scripts, you describe what you
want in plain language — or hand over the design documents you already have —
and an AI agent orchestrates the entire spec-to-GDSII flow.

**This is not AI4EDA** (bolting ML onto existing tools). This is **AI-Native
Design**: the AI agent is the core decision-maker; EDA tools are callable
execution engines.

It is also **program-first**. The product is the deterministic runner chain
(`vibe_ic_one_shot_runner.py` → `phase1/phase2/phase3` runners → 1345 top-level programs
→ MCP-EDA), not a prompt. **60 of the 63 flow steps are gated by a program
whose exit code is the verdict**; the AI is the fall-through when a program
cannot decide, never the thing that declares PASS.

```
                     ┌─────────────────────────────────────┐
                     │  flow_compliance_check.py --strict  │
                     │           exit 0 = PASS             │
                     └─────────────────────────────────────┘
```

**This is the plugin's public contract with agents**: if
`flow_compliance_check --strict` exits non-zero, the design is not signed off.
Period.

Provenance — the discipline was extracted from **real** debug sessions, not
designed in the abstract:

- 2026-04-16: 11 distinct FPGA-protocol bugs traced to SKILL.md sections
  agents skipped silently.
- 2026-04-21: a 10-IC Phase 2+3 campaign ran only 7 of 28 mandatory steps yet
  declared "10/10 PASS". Led to the strict per-step gate, the YAML gate
  signatures, and the open-source ATPG integration.

---

## The canonical flow (68 steps, 8 stages)

**Source of truth**:
[`plugins/vibe-ic/flow/phase1_phase2_phase3.yaml`](plugins/vibe-ic/flow/phase1_phase2_phase3.yaml)

**Entry point for agents**: [`AGENT_USAGE_GUIDE.md`](AGENT_USAGE_GUIDE.md) —
mandatory first read.

The flow covers **Phase 1 (spec extraction) as well as Phase 2 and Phase 3**.
Four of the eight stages are **conditional** — the analog and mixed-signal
stages activate only for designs with analog content, and the manufacturing
stage only once real silicon comes back. Every step declares
`required_outputs` plus a machine `gate` (`files_exist` and/or
`program_exit_zero`); `↻` marks a close-loop step that re-runs until its gate
is satisfied.

Run the whole thing:

```bash
python3 plugins/vibe-ic/programs/flow_compliance_check.py <project_dir> \
        --flow phase1_phase2_phase3 --strict
# exit 0 is the only PASS
```

#### `stage_phase1` — Phase 1, Spec Extraction (input → L1-L27 structured JSON) — 2 steps

End-of-stage gate: `phase1_compliance`

| # | Step | Machine gate |
|---|---|---|
| `D1` | Phase 1 doc extraction — dialogue **or** existing documents → the L1-L27 layered JSON set | program |
| `0.5ic` | Submission template ingest — the operator's slot geometry and identity fixtures, **read** rather than computed. Chooses the path: a template present ⇒ chip/IC, `NO_TEMPLATE.txt` ⇒ cell/IP | program |

#### `stage1` — RTL Generation + Verification — 7 steps

End-of-stage gate: `stage1_compliance` (`stage1_compliance.py`)

| # | Step | Machine gate |
|---|---|---|
| `1` | Spec-to-RTL | artifact |
| `2` | ↻ Lint (RTL hygiene + Quartus-unsafe patterns + RTL-bug claim schema) | program |
| `3` | ↻ CDC / RDC check | program |
| `4` | ↻ Simulation (testbench-based + L10/L12 coverage + Verilator coverage) | program |
| `5` | ↻ Formal verification (assertions proved + bit-level full-stack TB) | program |
| `6` | FPGA early prototype + verification-report audit | program |
| `P0` | Structural-RTL pre-flight (77 chip-AGNOSTIC structural gates) | pre-flight |

#### `stage2` — Synthesis + DFT — 12 steps

End-of-stage gate: `stage2_compliance` (`stage2_compliance.py`)

| # | Step | Machine gate |
|---|---|---|
| `7` | Constraint setup (SDC + PVT matrix) | program |
| `8` | ↻ SDC validation | program |
| `9` | Synthesis (Yosys → mapped netlist) | program |
| `10` | ↻ Pre-layout STA (multi-corner) | program |
| `11` | DFT insertion (scan chain + ATPG + at-speed + BSDL) | program |
| `FS1` | ISO-26262 FMEDA diagnostic coverage (fault injection; safety designs only) | program |
| `DT1` | Transition-delay-fault (at-speed LOC) ATPG | program |
| `DT2` | Path-delay-fault (at-speed, timing-graded) ATPG | program |
| `DT3` | Small-delay-defect (SDD) at-speed grade | program |
| `12` | Post-DFT optimization (resynth / buffering) | artifact |
| `13` | ↻ Equivalence check (RTL ≡ post-DFT netlist) | program |
| `14` | ↻ Synthesis handoff gate (pre-PnR Yosys script + netlist audit) | program |

#### `stage_analog` — Analog Design Pipeline — 9 steps *(conditional)*

Runs in parallel with stages 1-2, only when `phase1/analog/analog_block_list.json`
is present. End-of-stage gate: `analog_compliance`
(`analog_flow_compliance_check.py`)

| # | Step | Machine gate |
|---|---|---|
| `A1` | Analog spec extraction | program |
| `A2` | Analog topology selection | program |
| `A3` | Analog netlist generation | program |
| `A4` | Analog corner sweep (PVT) | program |
| `A5` | Analog layout | program |
| `A6` | Analog physical verification (per-block DRC + LVS before merge) | program |
| `A7` | ↻ Post-layout resimulation | program |
| `A8` | Hardmacro generation (LEF + Liberty + GDS + Verilog) | program |
| `A9` | ↻ Co-simulation / hardware verification | program |

#### `stage3` — Physical Design + Sign-off — 20 steps

End-of-stage gate: `stage3_compliance` (`stage3_compliance.py`)

| # | Step | Machine gate |
|---|---|---|
| `15` | Floorplan + PDN | program |
| `15.5ic` | Pad ring — the I/O pads, corner cells and filler that form the die's edge *(chip/IC path only)*. Precedes routing because the pads **are** the top-level ports | program |
| `16` | Clock planning | program |
| `17` | Placement (global + detailed) | program |
| `18` | Spare-cell + ECO-prep insertion (Design-for-ECO) | program |
| `19` | CTS (clock tree synthesis) | program |
| `20` | ↻ Post-CTS hold fixing | program |
| `21` | Routing (global + detailed) | program |
| `22` | Parasitic extraction (RC → SPEF) | program |
| `23` | ↻ Post-route STA (multi-corner multi-mode sign-off) | program |
| `24` | ↻ IR drop (static + dynamic) | program |
| `25` | ↻ EM check (electromigration lifetime) | program |
| `26` | ↻ Antenna check (gate-oxide protection) | program |
| `26.5ic` | Die finishing — seal ring and die identification *(chip/IC path only)* | program |
| `27` | ↻ Signal integrity (crosstalk / noise / glitch + crosstalk-delay) | program |
| `28` | ↻ PERC / reliability sign-off (ESD + latch-up + cross-domain) | program |
| `29` | Post-layout gate-level simulation (post-sim + SDF) | program |
| `30` | Post-layout SPICE verification (critical-path correlation + analog) | program |
| `31` | ↻ Physical verification (DRC + LVS + ERC + density) | program |
| `32` | ↻ Post-route timing repair pass (multi-corner `repair_design` + `repair_timing` + reroute) | program |

#### `stage_mixed_signal` — Mixed-Signal Integration — 4 steps *(conditional)*

Runs only when `phase1/analog/analog_block_list.json` is present.
End-of-stage gate: `mixed_signal_compliance`

| # | Step | Machine gate |
|---|---|---|
| `M1` | Mixed-signal top-level integration (A+D GDS merge + macro placement) | program |
| `M2` | Mixed-signal power domain + level-shifter / isolation verification | program |
| `M3` | Mixed-signal verification (AMS co-sim + RNM + interface signal integrity) | program |
| `M4` | Mixed-signal sign-off (top-level PV + final verdict) | program |

#### `stage4` — Output + Validation — 9 steps

End-of-stage gate: `stage4_compliance` (`stage4_compliance.py`)

| # | Step | Machine gate |
|---|---|---|
| `33` | Power analysis (pre / post-layout) | program |
| `34` | Metal fill (ECO-aware density fill insertion) | program |
| `35` | DFM screen (CMP density + redundant-via ratio + foundry-side OPC/RET disclosure) | program |
| `36` | Tapeout checklist (final sign-off confirmation) | program |
| `37` | GDSII output (**only if step 31 PV is fully clean**) | program |
| `37.5ip` | Digital hardmacro generation — LEF + Liberty + GDS + Verilog, and they must **agree**. The cell/IP path's terminal step | program |
| `37.5ic` | Shuttle precheck — the operator's own refusal, run before submission *(chip/IC path only)*. The one gate in this flow whose verdict the project does not write | program |
| `38` | Foundry handoff (mask spec + WAT plan + scribe layout + corner test kit) | program |
| `39` | FPGA final sign-off (recompile + on-board test) | program |

#### `stage5_manufacturing` — Manufacturing & Test — 5 steps *(conditional)*

Runs only when `phase3/stage5_manufacturing/silicon_received.json` is present.
End-of-stage gate: `manufacturing_compliance`

| # | Step | Machine gate |
|---|---|---|
| `40` | Fabrication (mask set + wafer fab — external) | program |
| `41` | Wafer sort / probe test (ATE + probe card) | program |
| `42` | Packaging (wirebond / FC-CSP / WLCSP) | program |
| `43` | Final test (ATE: functional + parametric + burn-in) | program |
| `44` | Reliability qualification (HTOL / FIT attestation) | program |

### Waivers (the ONLY legitimate way to skip a step)

```json
{
  "waived_steps": [
    {
      "id": 39,
      "reason": "No physical FPGA board in sub-agent env; benchmark IC session already validated the same BIST-on-hardware workflow with matching pass_flags",
      "approver": "reyerchu",
      "ticket": "N/A-pilot"
    }
  ]
}
```

Rubber-stamp waivers are rejected: the reason must be ≥ 20 characters and not
a placeholder (`TODO`, `n/a`, `skip`); the approver must not be `agent` /
`self` / `claude`. Enforced by
[`programs/waivers_schema_check.py`](plugins/vibe-ic/programs/waivers_schema_check.py).

---

## Toolchain — `vibeic-eda`

The flow executes inside the **`vibeic-eda` 0.2.24** container image, which
layers **13 vibeic EDA forks** on top of the `iic-osic-tools` base:

| | Forked and enhanced |
|---|---|
| Synthesis / netlist | `yosys` |
| Backend | `OpenROAD` |
| Timing | `OpenSTA` |
| Layout / PV | `magic`, `netgen`, `klayout` |
| Simulation | `ngspice`, `iverilog`, `verilator` |
| Verification frameworks | `cocotb`, `cocotb-coverage`, `pyuvm`, `sby` |

Each fork exists because an upstream limitation was hit during a real run and
fixed rather than waived. Live status of every fork:
**<https://vibeic.ai/eda-forks.html>**.

### PDKs

Declared in
[`programs/pdk_registry.json`](plugins/vibe-ic/programs/pdk_registry.json) —
site, metal prefix, clock-buffer cells, Liberty/LEF/GDS globs, DRC/LVS decks,
and the primitive-device model namespace per PDK. Third-party PDK plugins
append entries (see [`docs/CONTRIBUTING_NEW_PDK.md`](docs/CONTRIBUTING_NEW_PDK.md)).

| PDK | Node | Notes |
|---|---|---|
| `sky130A` | 130 nm | Open-source |
| `gf180mcuD` | 180 nm | Open-source |
| `ihp-sg13g2` | 130 nm | Open-source (BiCMOS) |
| `nangate45` | 45 nm | **Generic / predictive** research-and-education enablement — `tapeout_capable=false` |
| `asap7` | 7 nm | **Predictive** research-and-education enablement — `tapeout_capable=false` |
| `custom_auto_detect` | — | Auto-detection for a user-staged PDK |

NanGate45 and ASAP7 are *not* manufacturable enablements; they exist for PPA
exploration and flow regression, and the registry marks them so the tapeout
gates refuse them.

**Commercial PDKs are config-driven, never checked in.** A commercial
enablement is selected by the `VIBEIC_COMMERCIAL_PDK_ID` environment variable
or a private, git-ignored config under `~/.config`; the identifier, the deck
paths, and the cell data live entirely on the user's machine. No
foundry-specific name, SKU, or rule identifier appears anywhere in this
repository — see [`programs/_commercial_pdk.py`](plugins/vibe-ic/programs/_commercial_pdk.py)
for the resolution order.

---

## Agent architecture (Phase 1)

[`plugins/vibe-ic/agents/`](plugins/vibe-ic/agents/) — 9 agent definitions:
one design agent, three simulated user personas used for closed-loop Phase-1
training, and five maintainer/governance roles.

### The design agent

- **`ic-expert-agent.md`** — the single IC Expert Agent (unified front-door +
  reviewer: it runs the plain-language requirement dialogue itself). Consumes
  the elicited dialogue facts, the fact manifest, and the per-layer lessons.
  For every `deferred` fact it fills in the documented `ic_expert_default`
  along with its reasoning, then emits the final L1-L27 JSON set. **Never**
  reads the benchmark.
- **Personas** — `persona-common` / `persona-medium` / `persona-high` simulate
  a plain user, a hobbyist, and a senior IC designer, so the dialogue path can
  be regression-tested without a human in the loop.
- **Governance roles** — `repo-gatekeeper` (with `core-agent` / `gatekeeper-agent`
  aliases), `field-agent`, `benchmark-agent`. Their check-in scopes are
  enforced in [`AGENT_USAGE_GUIDE.md`](AGENT_USAGE_GUIDE.md) and by program.

### Fact manifest — Phase-1 source of truth

[`plugins/vibe-ic/agents/lessons/manifests/`](plugins/vibe-ic/agents/lessons/manifests/)
— one manifest per layer. Each entry:

```jsonc
{
  "path": "ic_name",                    // dot-path in the target L<N>.json
  "benchmark_value": "Single-wire ID Controller",
  "type": "str",
  "category": "identity",
  "pm_question_expert":       "IC name/part number?",
  "pm_question_intermediate": "What is the name or part number of the IC you want to design?",
  "pm_question_beginner":     "What should we call this chip?",
  "ic_expert_default": "Single-wire ID Controller",
  "default_reasoning": "Matches benchmark reference design target for reproduction.",
  "provenance_hint": "user_stated"
}
```

- **Built by** a training tool that walks a benchmark JSON and emits every leaf
  value as a fact skeleton. A curator (human or IC-Expert subagent) fills in
  the Q-bank, defaults, and provenance.
- **Used at inference** by the IC Expert Agent — no benchmark read.
- **Current status**: `L1_manifest.json` is the one curated manifest (40 facts,
  PoC). L2-L9 remain prose lessons —
  [`agents/lessons/ic_expert_L1..L9.md`](plugins/vibe-ic/agents/lessons/) plus
  `ic_expert_L8R.md`.

---

## Installation

```bash
# 1. Add the marketplace
claude plugin marketplace add https://github.com/vibeic/vibe-ic

# 2. Install the single plugin (bundles + auto-registers the MCP-EDA server)
claude plugin install vibe-ic
```

From a local clone:

```bash
git clone https://github.com/vibeic/vibe-ic.git
cd vibe-ic
claude plugin marketplace add ./vibe-ic-marketplace
claude plugin install vibe-ic
```

The MCP-EDA server lives **inside** the plugin
(`plugins/vibe-ic/mcp-eda/`), so one install gets the skills, the agents,
the 1345 top-level programs, and all 56 EDA/device tools. See
[`plugins/vibe-ic/mcp-eda/INSTALL_GUIDE.md`](plugins/vibe-ic/mcp-eda/INSTALL_GUIDE.md)
for the container prerequisites.

---

## Typical workflow

```bash
# ---- Whole flow, one command --------------------------------------------
/vibe-ic-all          # Phase 1 → Phase 2 → Analog → Phase 3, auto-detects
                      # Path A (natural language) vs Path B (existing docs)

# ---- Or phase by phase ---------------------------------------------------
/vibe-ic-phase1       # input → L1-L27 layered JSON + human-readable MD
/vibe-ic-phase2       # L1-L27 → RTL → verification → FPGA .sof
/vibe-ic-phase3       # synth → PnR → GDS → DRC / LVS / STA
/vibe-ic-phase23      # chained Phase 2 → Phase 3
/vibe-ic-benchmark    # run an open benchmark the methodology-correct way

# ---- Skill-level single-task invocations (any time) ----------------------
"Review this RTL"                             → skill: rtl-review
"Write a testbench for X"                     → skill: testbench-gen
"Triage this DRC report"                      → skill: drc-fix
"Ready for tapeout?"                          → skill: tapeout-checklist
```

Each slash command drives a deterministic one-shot runner
(`vibe_ic_one_shot_runner.py`, `phase1_one_shot_runner.py`,
`design_one_shot_runner.py`, `phase23_one_shot_runner.py`,
`phase3_one_shot_runner.py`, `analog_one_shot_runner.py`) and then runs the
compliance gate over the artefacts it produced.

**The canonical rule**: for any task that touches downstream EDA (synth, PnR,
GDS, sign-off), go through the runner — do not let an agent call Quartus /
Yosys / OpenROAD directly from a prompt and then report a verdict. See
[`AGENT_USAGE_GUIDE.md`](AGENT_USAGE_GUIDE.md).

---

## Skills catalog (60)

Every skill directory carries a `SKILL.md` **and** a `compliance.yaml`
enumerating the output elements the skill must actually produce — so skill
output is auditable, not just plausible.

### Phase 1 — spec ingestion + review (5)
`phase1`, `phase1-output-verify`, `phase1-completeness-deep-review`,
`spec-review`, `spec-validator`

### Phase 2 — RTL + verification (11)
`spec-to-rtl`, `catalog-glue-author`, `rtl-review`, `rtl-repair`,
`testbench-gen`, `formal-verify`, `equivalence-check`, `phase2-rtl-verify`,
`hls-c2rtl`, `architecture-explore`, `ppa-predict`

### Phase 3 — synthesis → GDSII → sign-off (11)
`synth-doctor`, `sta-review`, `hold-fix`, `ir-drop-triage`, `drc-fix`,
`lvs-triage`, `eco-plan`, `design-for-eco`, `phase3-backend-verify`,
`tapeout-checklist`, `yield-diagnostic`

### Analog A1-A9 + mixed-signal (15)
`analog-spec-extract`, `analog-topology-select`, `analog-netlist-gen`,
`analog-sizing`, `analog-sizing-loop`, `analog-layout`,
`analog-extraction-resim`, `analog-hardmacro-gen`, `analog-flow-orchestrate`,
`analog-output-verify`, `ams-sim`, `mixed-signal-cosim`,
`analog-hw-testbench-gen`, `analog-hw-measure`, `analog-hw-tuning-loop`

### FPGA + lab hardware (5)
`fpga-hps-bridge`, `fpga-signaltap`, `fpga-led-probe-allocation`,
`hw-debug-loop`, `scope-pattern-attestation`

### Gates, governance, and closed loops (13)
`checkpoint-gate`, `compliance-gate-spot-check`, `full-test-audit`,
`regression-manage`, `regression-issue-fix`, `community-backlog-submit`,
`benchmark-verify`, `benchmark-enhancement-capture`,
`open-benchmark-methodology`, `core-agent-loop`, `gatekeeper-loop`,
`field-agent-loop`, `phase1-coverage-loop`

---

## MCP-EDA server (56 tools)

Bundled at [`plugins/vibe-ic/mcp-eda/`](plugins/vibe-ic/mcp-eda/) and
auto-registered on install. Inventory of record:
[`MCP_TOOL_INVENTORY.json`](plugins/vibe-ic/mcp-eda/MCP_TOOL_INVENTORY.json)
(48 EDA + 7 lab-device + 1 health check).

| Category | Tools |
|----------|-------|
| Synthesis | Yosys (`eda_synth`) |
| Verification | Verilator (`eda_lint`), iverilog (`eda_simulate`), SymbiYosys (`eda_formal`), cocotb (`eda_cocotb`), Yosys LEC (`eda_equiv`) |
| Timing | OpenSTA (`eda_sta`, `eda_sta_mcorner`) |
| Backend | OpenROAD (`eda_pnr`), KLayout (`eda_gds`, `eda_drc_klayout`), Magic (`eda_extraction`) |
| Sign-off | Netgen (`eda_lvs`), OpenROAD PSM (`eda_ir_drop`), ATPG (`eda_dft`) |
| Analog | ngspice / Xyce (`eda_spice`, `eda_spice_corner`), xschem (`eda_xschem_netlist`), `eda_analog_layout` |
| Audit | `eda_rtl_audit`, `eda_spec_conformance`, `eda_phase23_completion_audit`, `eda_doctor` |
| FPGA | `eda_fpga_compile`, `eda_fpga_program`, `eda_fpga_gds_reverify` |
| Lab devices | oscilloscope capture / decode, DE10-Lite programming + ADC read, camera LED diff |
| Search | `eda_ic_search` |

---

## Deterministic programs (1345 top level)

```bash
cd plugins/vibe-ic && python3 -m pytest programs/tests/ -q
```

**Headline programs**:

*Canonical flow + gates*

| Program | Role |
|---|---|
| **`flow_compliance_check.py`** | Strict 68-step gate — reads `flow/phase1_phase2_phase3.yaml`, validates every step's outputs + gate predicate, rejects rubber-stamp waivers. **Exit 0 is the only PASS.** |
| `stage{1,2,3,4}_compliance.py` | Per-stage interim gates |
| `analog_flow_compliance_check.py` | A1-A9 analog-stage gate |
| **`waivers_schema_check.py`** | Rejects placeholder reasons (`TODO`, `n/a`), self-approvers (`agent`, `claude`), duplicate ids |
| **`fault_atpg_run.py`** | Open-source stuck-at ATPG inside the `vibeic-eda` container |
| **`rom_init_lint.py`** | Catches Quartus-unsafe `initial begin for(i=0;...) rom[i]=...` (silent-failure class surfaced 2026-04-21) |
| **`quartus_map_audit.py`** | Scans `.map.rpt` for `Stuck at GND/VCC`, Warning 10030/10855, lost fanout |
| `bist_window_calculator.py` | Computes sample-window size for BIST responses |
| `otp_image_check.py` | Validates OTP-content generator outputs |

*Anti-fabrication layer*

| Program | Role |
|---|---|
| **`def_stage_progression_check.py`** | Rejects byte-identical stage DEFs (the "`cp routed.def` five times" cheat). Requires SHA uniqueness + size monotonicity + instance-count non-regression + `+ ROUTED` geometry. |
| **`provenance_logger.py`** | Wraps ANY tool invocation; records `{tool, version, argv, input/output hashes, exit, duration}` to `<project>/provenance.jsonl`. |
| **`provenance_check.py`** | Gate verifier: does `provenance.jsonl` contain an exit-0 entry, from an allow-listed tool, declaring this output, whose logged hash still matches the file on disk? |
| **`fpga_on_board_attestation_check.py`** | Rejects pure-JSON self-attestation on the FPGA sign-off step. Requires pass.json + bitstream-hash match + programmer log + ≥ 1 non-JSON hardware artefact (webcam / UART / scope). |
| `pdk_consistency_check.py` | Cross-checks the resolved PDK's decks, Liberty, LEF, and device models against `pdk_registry.json` |

---

## Extending the marketplace

The publishing surface is defined by three **plugin layers** (the `layer:`
field in a `plugin.yaml`), each with a working end-to-end example under
[`reference-plugins/`](reference-plugins/):

| Layer | What it carries | Example |
|-------|-----------------|---------|
| `exp` | Experience units — K-entries, practical notes, captures, decision logs | [`reference-plugins/example-exp/`](reference-plugins/example-exp/) |
| `ip`  | Hard / firm / soft IP + `ip_metadata.yaml` | [`reference-plugins/example-ip/`](reference-plugins/example-ip/) |
| `eda` | Third-party MCP EDA / device tool declaration | [`reference-plugins/example-eda/`](reference-plugins/example-eda/) |

Contribution guides, one per extension point:

| Guide | Add a… |
|---|---|
| [`docs/CONTRIBUTING_NEW_SKILL.md`](docs/CONTRIBUTING_NEW_SKILL.md) | skill (SKILL.md + compliance.yaml) |
| [`docs/CONTRIBUTING_NEW_GATE.md`](docs/CONTRIBUTING_NEW_GATE.md) | flow-step gate program |
| [`docs/CONTRIBUTING_NEW_PDK.md`](docs/CONTRIBUTING_NEW_PDK.md) | PDK registry entry |
| [`docs/CONTRIBUTING_NEW_IC_CLASS.md`](docs/CONTRIBUTING_NEW_IC_CLASS.md) | IC class in `ic_class_registry.json` |
| [`docs/CONTRIBUTING_NEW_DEVICE.md`](docs/CONTRIBUTING_NEW_DEVICE.md) | lab device / MCP device tool |
| [`docs/CONTRIBUTING_PARTNER_PLUGIN.md`](docs/CONTRIBUTING_PARTNER_PLUGIN.md) | partner plugin (skeleton in [`templates/partner-plugin-skeleton/`](templates/partner-plugin-skeleton/)) |

Problems found while using the plugin are filed under
[`community/backlogs/`](community/backlogs/) by the Field and Benchmark agents;
only the Repo Gatekeeper lands changes on `main`.

> **Roadmap, not in this tree**: the wider open-platform surface — a signed
> package registry, the `vibe-ic plugin` local-lifecycle CLI, encrypted-IP
> distribution, the shared MCP tool catalogue, and the per-call billing rail —
> is specified but its implementation is **not** present in this repository.
> The plugin layers, reference plugins, and marketplace catalogue above are
> the parts that exist today.

---

## Repository structure

```
vibe-ic-marketplace/
├── AGENT_USAGE_GUIDE.md                 ← MUST READ for any agent
├── README.md                            ← this file
├── .claude-plugin/marketplace.json      ← catalogue (1 plugin)
├── docs/CONTRIBUTING_NEW_*.md           ← 6 extension guides
├── reference-plugins/{example-exp,example-ip,example-eda}/
├── templates/partner-plugin-skeleton/
├── community/backlogs/
└── plugins/
    └── vibe-ic/                         ← the single plugin (v1.15.66)
        ├── .claude-plugin/plugin.json
        ├── flow/
        │   └── phase1_phase2_phase3.yaml   ← 68-step source of truth
        ├── commands/                    ← 7 slash commands
        ├── agents/
        │   ├── ic-expert-agent.md       ← assembles JSON from answers + defaults
        │   ├── repo-gatekeeper.md, field-agent.md, benchmark-agent.md, …
        │   └── lessons/
        │       ├── ic_expert_L1..L9.md  ← prose lessons per layer
        │       └── manifests/L1_manifest.json  ← 40-fact Q-bank (PoC)
        ├── skills/                      ← 60 skills, each + compliance.yaml
        ├── programs/                    ← 4521 *.py at any depth (1345 top level)
        │   ├── flow_compliance_check.py ← final gate
        │   ├── stage{1,2,3,4}_compliance.py
        │   ├── pdk_registry.json, ic_class_registry.json
        │   └── tests/                   ← 3103 test files
        ├── mcp-eda/                     ← bundled MCP server, 56 tools
        ├── ip-catalog/                  ← reusable open-source IP index
        └── hooks/
```

---

## Links

- **Repository**: <https://github.com/vibeic/vibe-ic>
- **EDA fork tracker**: <https://vibeic.ai/eda-forks.html>
- **SKY130 PDK**: [google/skywater-pdk](https://github.com/google/skywater-pdk)
- **GF180MCU PDK**: [google/gf180mcu-pdk](https://github.com/google/gf180mcu-pdk)
- **IHP SG13G2 PDK**: [IHP-GmbH/IHP-Open-PDK](https://github.com/IHP-GmbH/IHP-Open-PDK)
- **iic-osic-tools (base image)**: [hpretl/iic-osic-tools](https://github.com/iic-jku/IIC-OSIC-TOOLS)

## License

Apache-2.0 — see [`LICENSE`](../LICENSE).
