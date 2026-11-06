# Vibe-IC Marketplace

**AI-Native IC Design plugin for Claude Code — Vibe Coding for ASIC**

> From natural-language dialogue (or existing design documents) to a GDS
> hand-off, driven by AI agents with EDA tools as callable execution engines —
> **with each verdict taken from the tool's native result and original limit**.

This repository is the **marketplace**: the `.claude-plugin/marketplace.json`
catalogue, the plugin itself, reference plugins for third-party publishers,
and the contribution guides for extending it.

| | |
|---|---|
| Plugins in this marketplace | **1** — [`plugins/vibe-ic`](plugins/vibe-ic/) |
| Plugin version | **1.39.66** |
| Deterministic programs | **779** top level (`plugins/vibe-ic/programs/*.py`), of which **670** are catalogued in [`INDEX.md`](plugins/vibe-ic/programs/INDEX.md) |
| Skills | **60** (`plugins/vibe-ic/skills/*/SKILL.md`, each with a `compliance.yaml`) |
| Slash commands | **7** (`plugins/vibe-ic/commands/*.md`) |
| Agents | **9** (`plugins/vibe-ic/agents/*.md`) |
| MCP-EDA tools | **56** (48 EDA + 7 lab-device + 1 health) |
| Executable flow | [`flow/steps.json`](plugins/vibe-ic/flow/steps.json), including conditional IC/IP, analog and hardware paths |
| Test files | **3056** under `plugins/vibe-ic/programs/tests/` + **54** under `plugins/vibe-ic/mcp-eda/test/` (`test_*.py`, any depth) |
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

It is also **program-first**. The public entry `vibe_ic_one_shot_runner.py`
uses `flow_engine_frontend.py` and `flow_engine.py` to run the selected rows in
`flow/steps.json`. Each row names a tool command or adapter; its native report
is compared with the original limits in `flow/native_limits.json`. AI runs the
flow, reviews every result and fixes problems in the design, tool or plugin.

```text
public entry → Router → step-table runners → 779 top-level programs → native tools
```

PASS means a measured result meets its original limit. FAIL means it violates
the limit. A tool that did not run or left no usable report is NOT_MEASURED.
Bounded RTL results apply to their selected window, not to whole-chip delivery.
The owner's [design charter](plugins/vibe-ic/CHARTER.md) defines these rules.

Earlier documentation described **60 of the 63 flow steps are gated by a program**.
That historical count is retained for inventory bookkeeping; the current executable
step table is linked below.

Provenance — the discipline was extracted from **real** debug sessions, not
designed in the abstract:

- 2026-04-16: 11 distinct FPGA-protocol bugs traced to SKILL.md sections
  agents skipped silently.
- 2026-04-21: a 10-IC Phase 2+3 campaign ran only 7 of 28 mandatory steps yet
  declared "10/10 PASS". Led to the strict per-step gate, the YAML gate
  signatures, and the open-source ATPG integration.

---

## The canonical flow

The executable sequence is [`flow/steps.json`](plugins/vibe-ic/flow/steps.json),
with original numerical limits in
[`flow/native_limits.json`](plugins/vibe-ic/flow/native_limits.json).
[`flow/phase1_phase2_phase3.yaml`](plugins/vibe-ic/flow/phase1_phase2_phase3.yaml)
provides the canonical user-facing step names and positions. Report a step's
1-based position and name, and retain that numbering on conditional paths.

**Entry point for agents**: [`AGENT_USAGE_GUIDE.md`](AGENT_USAGE_GUIDE.md).
Run from the marketplace directory:

```bash
python3 plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py <project_dir> \
  --route ic --delivery-target shippable_gds
```

The Router selects the task's delivery endpoint and applicable window. For an
IP hardmacro use `--route ip --delivery-target ip_hardmacro`; bounded RTL work
uses `--delivery-target rtl`. An explicit window supplies both `--entry-step`
and `--exit-step`, using names from the current table. No feature manifest or
engine selector is required.

| Engineering area | Work covered by the selected native steps |
|---|---|
| Requirements | Natural-language input or design documents to layered design specifications; operator submission geometry when supplied |
| RTL and verification | RTL authoring, lint, CDC/RDC, simulation, formal verification and FPGA work when applicable |
| Synthesis and constraints | SDC, synthesis, timing analysis, DFT/ATPG, equivalence and synthesis handoff |
| Analog | Specifications, topology, sizing, SPICE/PVT simulation, layout, DRC/LVS, parasitic extraction, resimulation and hardmacro views |
| Physical implementation | Floorplan/PDN, pad ring, placement, CTS, hold repair, routing and extraction |
| Electrical and physical verification | STA, IR drop, EM, antenna, signal integrity, reliability, DRC/LVS/ERC and density |
| Mixed signal | Macro integration, co-simulation, supplies/domains and analog/digital physical checks |
| Finishing and delivery | Fill, seal ring, final GDS checks, hardmacro packaging, provider precheck and foundry handoff |
| Hardware and manufacturing | Board measurements and post-fabrication work when the required hardware or silicon is available |

A conditional row runs only when its design predicate applies. Missing tools,
inputs or native reports remain visible as unmeasured work. AI reviews the
actual result and addresses design or tool defects without changing a limit.

---

## Toolchain — `vibeic-eda`

The flow executes inside the configured **`vibeic-eda`** container image, which
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
the 779 top-level programs, and all 56 EDA/device tools. See
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

The slash commands enter the same step-table engine through the public
runner and its phase frontends. Analog execution uses its native tool path.
Each result names what actually ran and the measured values against the
original limits.

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

## Deterministic programs (779 top level)

```bash
cd plugins/vibe-ic && python3 -m pytest programs/tests/ -q
```

**Headline programs**:

| Program | Role |
|---|---|
| `vibe_ic_one_shot_runner.py` | Public entry for the Router-selected delivery endpoint and window |
| `task_nature_route.py`, `route_decision.py` | Task-nature routing and bounded RTL dependency selection |
| `flow_engine_frontend.py`, `flow_engine.py` | Run applicable rows of the executable step table |
| `flow_native_adapters.py`, `flow_native_verification.py` | Invoke native EDA commands and read their reports |
| `analog_native_flow.py` | Run native analog and mixed-signal work |
| `benchmark_dispatch.py`, `benchmark_io_adapter.py` | Program-first benchmark dispatch, blind AI review/backup and result collection |
| `fault_atpg_run.py` | Native stuck-at ATPG execution |
| `gen_program_inventory.py` | Regenerate the program inventory, catalogue and documented counts |

The complete generated catalogue is
[`plugins/vibe-ic/programs/INDEX.md`](plugins/vibe-ic/programs/INDEX.md).
Native measurements do not require a hash, identity, provenance or receipt
layer to qualify their result.

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
    └── vibe-ic/                         ← the single plugin (v1.39.66)
        ├── .claude-plugin/plugin.json
        ├── flow/
        │   ├── steps.json, native_limits.json ← executable rows and original limits
        │   └── phase1_phase2_phase3.yaml ← canonical display order
        ├── commands/                    ← 7 slash commands
        ├── agents/
        │   ├── ic-expert-agent.md       ← assembles JSON from answers + defaults
        │   ├── repo-gatekeeper.md, field-agent.md, benchmark-agent.md, …
        │   └── lessons/
        │       ├── ic_expert_L1..L9.md  ← prose lessons per layer
        │       └── manifests/L1_manifest.json  ← 40-fact Q-bank (PoC)
        ├── skills/                      ← 70 skills, each + compliance.yaml
        ├── programs/                    ← 3969 *.py at any depth (779 top level)
        │   ├── vibe_ic_one_shot_runner.py ← public entry
        │   ├── flow_engine.py, flow_native_adapters.py
        │   ├── pdk_registry.json, ic_class_registry.json
        │   └── tests/                   ← 3056 test files
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
