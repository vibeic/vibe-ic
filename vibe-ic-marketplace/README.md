# Vibe-IC Marketplace — **v1.0** (open marketplace foundation)

**AI-Native IC Design plugins for Claude Code — Vibe Coding for ASIC**

> From natural-language dialogue to tapeout-ready GDS, driven by AI agents with EDA tools as callable execution engines — **with gates that catch fabricated artefacts**.

---

## Open marketplace surface (v0.85 → v1.0, 2026-04-26)

The full open-platform stack ships in this release. Anyone can publish
plugins to a registry (reference deployment target: `https://vibeic.ai/api/v1`),
and any developer can install them — with cryptographic signature
verification, automatic trust-tier scoring, encrypted-IP support, and
per-call billing. See:

- [`docs/design/ROADMAP.md` § 6](../docs/design/ROADMAP.md) — open-platform vision
- [`docs/design/plugin_platform_spec.md`](../docs/design/plugin_platform_spec.md) — plugin.yaml + CLI + registry layout
- [`docs/design/registry_api.md`](../docs/design/registry_api.md) — HTTP protocol
- [`docs/design/encrypted_ip_spec.md`](../docs/design/encrypted_ip_spec.md) — AES-256-GCM IP artifacts
- [`docs/design/release_spec.md`](../docs/design/release_spec.md) — MCP tool hand-off + billing rail + v1.0 frozen schemas

CLI quick reference:

```bash
# Local lifecycle (no registry needed)
vibe-ic plugin keygen     --out ~/.vibe-ic/keys/me.pem
vibe-ic plugin pack       ./my-plugin --out my-plugin-1.0.0.tgz --sign ~/.vibe-ic/keys/me.pem
vibe-ic plugin validate   my-plugin-1.0.0.tgz
vibe-ic plugin install    my-plugin-1.0.0.tgz [--verify-sig pubkey.pem]
vibe-ic plugin list / info / uninstall

# Registry (default: vibeic.ai; override with VIBE_IC_REGISTRY_URL)
vibe-ic plugin login      --namespace my-org --secret ...
vibe-ic plugin publish    my-plugin-1.0.0.tgz
vibe-ic plugin search     "spi"
vibe-ic plugin install    my-org/my-plugin                     # registry resolves
vibe-ic plugin yank       my-org/my-plugin@1.0.0 --reason ...

# Encrypted IP (v0.95)
vibe-ic plugin ip keygen  --out customer-key.bin
vibe-ic plugin ip encrypt secret.v --key customer-key.bin
vibe-ic plugin install    vendor/my-ip --ip-key customer-key.bin

# MCP tool catalogue (v1.0; mcp-eda reads ~/.vibe-ic/mcp_tools.json)
vibe-ic plugin mcp-tools  list
vibe-ic plugin mcp-tools  show

# Billing rail (v1.0)
vibe-ic plugin billing record  --namespace V --plugin-id P --version V \
                               --mcp-tool-name T --cost-cents N
vibe-ic plugin billing report  --since 30d
```

**Three plugin layers** (`layer:` field in `plugin.yaml`):

| Layer | What it carries | Examples |
|-------|-----------------|----------|
| `exp` | K1-K5 entries, PRACTICAL_NOTES, T5/T6 captures, decision_log | `reference-plugins/example-exp/` |
| `ip`  | hard / firm / soft IP + `ip_metadata.yaml` (encryptable) | `reference-plugins/example-ip/` |
| `eda` | third-party MCP EDA / device tool stub | `reference-plugins/example-eda/` |

**Reference server** (deployable to vibeic.ai):
```bash
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/vibeic_registry_server.py \
    --port 8090 --state-dir /var/lib/vibeic-registry
```

Stdlib-only (sqlite3 + http.server). Run behind nginx for HTTPS.

**Acceptance gates** (run them on a clean machine; exit 0 = release ready):
```bash
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/acceptance_gate_cli.py   # 8 steps
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/acceptance_gate_registry.py   # 13 steps
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/acceptance_gate_full.py   # 15 steps
```

---

## What is Vibe-IC?

Vibe-IC brings the "Vibe Coding" paradigm to IC design. Instead of manually driving dozens of EDA tools through arcane TCL scripts, you describe what you want in plain language and an AI agent orchestrates the entire RTL-to-GDSII flow.

**This is not AI4EDA** (bolting ML onto existing tools). This is **AI-Native Design**: the AI agent is the core decision-maker; EDA tools are callable execution engines.

### Three-phase design flow (**source of truth: `plugins/vibe-ic/flow/phase2_phase3.yaml`**)

```
┌────────────┬────────────────────────────────────────────────┬────────────────────────┐
│ Phase 1    │ Dialogue → L1-L27 design documents              │ ic-expert-agent        │
│            │ (phase1-orchestrate, 10 lesson files)          │ agent → L1..L9 JSON    │
├────────────┼────────────────────────────────────────────────┼────────────────────────┤
│ Phase 2    │ Step 01-06: RTL generation + verification      │ RTL + sim + formal     │
│            │ Step 07-13: synthesis + DFT (+ Fault ATPG)     │ + FPGA early proto     │
│            │                                                │ + mapped netlist       │
├────────────┼────────────────────────────────────────────────┼────────────────────────┤
│ Phase 3    │ Step 14-24: physical design + sign-off         │ CTS, routing, DRC/LVS  │
│            │ Step 25-28: output + validation                │ tape-out GDS + FPGA    │
│            │                                                │ on-board sign-off      │
└────────────┴────────────────────────────────────────────────┴────────────────────────┘

                     ┌─────────────────────────────────────┐
                     │  flow_compliance_check.py --strict  │
                     │           exit 0 = PASS             │
                     └─────────────────────────────────────┘
```

Verified on **GF180MCU 180 nm**, **SKY130 130 nm**, and the **m18e80pm180su** custom 180 nm PDK. Hardware-validated on a DE10-Lite (MAX10) FPGA with a production single-wire ID communication IC (2,827 cells, 17 RTL modules) via the protocol tester.

---

## Plugins in this marketplace

| Plugin | Purpose | Count |
|--------|---------|-------|
| **[vibe-ic](plugins/vibe-ic/)** | Skill catalog — one SKILL.md per task. Includes `flow-orchestrate` (strict 33-step entry point), 2 agents, 10 lesson files, Phase-1 orchestrator, L2-L9 doc generators. | 60 skills + 2 agents + 10 lessons |
| **[vibe-ic-d](plugins/vibe-ic-d/)** | **Deterministic edition** — compliance YAMLs + programs that make skill execution auditable. Includes `flow_compliance_check`, 4 per-stage gates, `waivers_schema_check`, `fault_atpg_run`, and the v0.47.2-.4 anti-fabrication layer (`def_stage_progression_check`, `provenance_logger/check`, `fpga_on_board_attestation_check`). | 60 compliance specs + 64 programs |

### vibe-ic vs vibe-ic-d

- `vibe-ic` alone gives you the skill library and the agent definitions. Agents produce high-quality output but **different agents may skip different sections** — a variability source that breaks reproducibility.
- `vibe-ic-d` adds a **compliance gate** at two levels:
  1. **Per-skill** — every SKILL.md has a matching `compliance.yaml` enumerating required output elements (section headers, metadata fields, handoff lines, tool invocations). A generic driver audits skill output; task only completes when the audit returns PASS.
  2. **Per-flow** — the 33-step canonical Phase 2+3 flow has per-step gate predicates and a top-level `flow_compliance_check --strict` that must exit 0 before any PASS claim. Waivers are machine-validated (reason ≥ 20 chars, non-self approver).

**This is the plugin's public contract with agents**: if `flow_compliance_check --strict` exits non-zero, the design is not signed off. Period.

Provenance: vibe-ic-d's discipline was extracted from two **real** debug sessions —
- 2026-04-16: 11 distinct FPGA-protocol bugs traced to SKILL.md sections agents skipped silently.
- 2026-04-21: a 10-IC Phase 2+3 campaign ran only 7 of 28 mandatory steps yet declared "10/10 PASS". Led to the strict 28-step gate, 15 YAML gate-signature fixes, and the open-source Fault integration.

See [plugins/vibe-ic-d/README.md](plugins/vibe-ic-d/README.md) for the full program matrix.

---

## The canonical Phase 2+3 flow (33 steps)

**Source of truth**: [`plugins/vibe-ic/flow/phase2_phase3.yaml`](plugins/vibe-ic/flow/phase2_phase3.yaml)

**Entry point for agents**: [`AGENT_USAGE_GUIDE.md`](AGENT_USAGE_GUIDE.md) — mandatory first read.

### Stage 1 — RTL + Verification (Steps 01-06)

| # | Step | Primary skill | Gate |
|---|---|---|---|
| 01 | Spec-to-RTL | `spec-to-rtl` | `rtl/*.sv` present |
| 02 | Lint (hygiene + Quartus-unsafe ROM init) | `rtl-review` | `rtl_hygiene_lint` + `rom_init_lint` exit 0 |
| 03 | CDC / RDC | `cdc-check` + `rdc-check` | 3 CDC programs exit 0 |
| 04 | Simulation (testbench-driven) | `testbench-gen` | `sim/results.xml` or `sim/pass.flag` |
| 05 | Formal (assertions proved) | `assertion-gen` + `formal-verify` | `formal/results.json.all_proved = true` |
| 06 | FPGA early prototype | `fpga-test-harness` | `.sof` + `quartus_map_audit.json` |

### Stage 2 — Synthesis + DFT (Steps 07-13)

| # | Step | Primary skill | Gate |
|---|---|---|---|
| 07 | Constraint setup (SDC + PVT) | `constraint-gen` | `constraints/*.sdc` + `pvt_matrix.json` |
| 08 | SDC validation | `sdc-validator` | `sdc_syntax_check` exit 0 |
| 09 | Synthesis (Yosys → netlist) | `synth-doctor` + MCP `eda_synth` | `synth_netlist_check` exit 0 |
| 10 | Pre-layout STA (multi-corner) | `sta-review` + MCP `eda_sta` | `sta_report_check --mode sta` exit 0 |
| 11 | **DFT insertion (scan + ATPG)** | `dft-insert` + `atpg` + **`fault_atpg_run`** | `stuck_at_ge_target = true` |
| 12 | Post-DFT optimization | `synth-doctor` | `synth/post_dft_netlist.v` present |
| 13 | Equivalence check (RTL ≡ post-DFT) | `equivalence-check` | `reports/lec.json.equivalent = true` |

### Stage 3 — Physical Design + Sign-off (Steps 14-24)

| # | Step | Primary skill | Gate |
|---|---|---|---|
| 14 | Floorplan + PDN | MCP `eda_pnr` | `pnr/floorplan.def` |
| 15 | Clock planning | `cts-plan` | `cts/clock_plan.json` |
| 16 | Placement | `placement-optimize` | `pnr/placed.def` |
| 17 | **CTS (Clock Tree Synthesis)** | MCP `eda_pnr` | `pnr/post_cts.def` + `clock_tree.rpt` |
| 18 | Post-CTS hold fixing | `hold-fix` | `pnr/post_hold.def` |
| 19 | Routing | MCP `eda_pnr` | `routed.def` + DRC 0 viol |
| 20 | Post-route STA (MCMM sign-off) | `sta-review` + MCP `eda_sta` | WNS ≥ 0 across all corners |
| 21 | IR drop | `ir-drop-triage` | `ir_drop_report_check` exit 0 |
| 22 | EM check | `em-check` | `em_report_check` exit 0 |
| 23 | Antenna check | (PDK) | `reports/antenna.rpt` clean |
| 24 | Physical Verification (DRC / LVS / ERC) | `drc-fix` + `lvs-triage` + `perc-check` | All three exit 0 |

### Stage 4 — Output + Validation (Steps 25-28)

| # | Step | Primary skill | Gate |
|---|---|---|---|
| 25 | Power analysis | `power-analysis` | `power_report_check` exit 0 |
| 26 | Tapeout checklist | `tapeout-checklist` | `tapeout_signoff_check --strict` exit 0 |
| 27 | **GDSII output** (gated on 24 + 26) | MCP `eda_gds` | `gds/*.gds` + `gds_size_check` exit 0 |
| 28 | **FPGA final sign-off** (on-board) | `fpga-test-harness` | `on_board_pass.json.all_scenarios_passed = true` |

### Waivers (the ONLY legitimate way to skip a step)

```json
{
  "waived_steps": [
    {
      "id": 28,
      "reason": "No physical FPGA board in sub-agent env; benchmark IC session already validated the same BIST-on-hardware workflow with matching pass_flags",
      "approver": "reyerchu",
      "ticket": "N/A-pilot"
    }
  ]
}
```

Rubber-stamp waivers are rejected: reason must be ≥ 20 chars and not a placeholder (`TODO`, `n/a`, `skip`); approver must not be `agent` / `self` / `claude`. See `programs/waivers_schema_check.py`.

---

## Agent architecture (Phase 1)

[`plugins/vibe-ic/agents/`](plugins/vibe-ic/agents/)

### One unified agent

- **`ic-expert-agent.md`** — the single IC Expert Agent (unified front-door + reviewer: it runs the plain-language requirement dialogue itself, absorbing the former PM Agent role). Consumes the elicited dialogue facts + the fact manifest + per-layer lessons. For every `deferred` fact, fills in the documented `ic_expert_default` along with its reasoning. Emits the final L1-L27 JSON doc. **Never** reads the benchmark.

### Fact manifest — Phase-1 source of truth

[`plugins/vibe-ic/agents/lessons/manifests/`](plugins/vibe-ic/agents/lessons/manifests/) — one manifest per layer. Each entry:

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

- **Built by `tools/training/extract_fact_manifest.py`** (internal training tool) which walks a benchmark JSON and emits every leaf value as a fact skeleton. A curator (human or IC-Expert subagent) fills in the Q-bank, defaults, and provenance.
- **Used at inference** by the IC Expert Agent — no benchmark read.
- **Current status**: L1 manifest has all 40 facts curated (PoC). L2-L9 manifests are still schema-only prose lessons (`lessons/ic_expert_L2..L9.md`).

### Sample dialogues (reference only)

`docs/tutorials/phase1_sample_dialogue_{beginner,intermediate,expert}{,_zh}.md` — six dialogues (EN + ZH × three user levels) showing the IC Expert Agent's intended dialogue shape.

### Tutorial

[`docs/tutorials/phase1_closed_loop_training.md`](../docs/tutorials/phase1_closed_loop_training.md) — full methodology **and** the post-mortem of two earlier verification attempts that used unsound shortcuts (mimicry with answer key visible / verbatim copy from prior runs). The tutorial is written as a retraction and is the honest baseline for future work.

---

## Installation

```bash
# Clone the marketplace
git clone https://github.com/reyerchu/AI_IC_design.git
cd AI_IC_design

# Install core skills + agents
claude plugin install vibe-ic-marketplace/plugins/vibe-ic

# Install the deterministic edition (recommended — compliance gates)
claude plugin install vibe-ic-marketplace/plugins/vibe-ic-d

# MCP EDA server (Docker-packaged 20 tools; optional but recommended)
cd mcp-eda && npm install && npm start
```

Manual install:

```bash
cp -r vibe-ic-marketplace/plugins/vibe-ic /path/to/your-project/.claude/plugins/
cp -r vibe-ic-marketplace/plugins/vibe-ic-d    /path/to/your-project/.claude/plugins/
```

---

## Typical workflow

```bash
# ---- Phase 1 ---- dialogue + doc generation -------------------------
"I want a chip that does X"                   → ic-expert-agent (dialogue)
   └→ handoff                                 → ic-expert-agent (L1..L9 JSON)

# ---- Phase 2+3 ---- 33-step canonical flow --------------------------
"Run Phase 2+3 for this IC"                   → skill: flow-orchestrate
                                                (emits 33-step plan BEFORE executing)
   └→ per-stage gate after each stage         → stage{1,2,3,4}_compliance.py
   └→ final gate                              → flow_compliance_check.py --strict

# ---- Skill-level single-task invocations (any time) -----------------
"Review this RTL"                             → skill: rtl-review
"Write a testbench for X"                     → skill: testbench-gen
"Triage this DRC report"                      → skill: drc-fix
"Ready for tapeout?"                          → skill: tapeout-checklist
```

**The canonical rule**: for any task that touches downstream EDA (synth, PnR, GDS, sign-off), the agent's first action must be to invoke `flow-orchestrate` — do not let an agent call Quartus / Yosys / OpenROAD directly from a prompt. See [`AGENT_USAGE_GUIDE.md`](AGENT_USAGE_GUIDE.md).

---

## Skills catalog

Grouped by design-flow phase.

### Phase 1 — Dialogue → L1-L27 (11 skills)
| Skill | Purpose |
|---|---|
| **phase1-orchestrate** | Entry point; drives the ic-expert-agent dialogue |
| **prompt-intake** | Initial user-dialogue intake for the IC Expert Agent |
| **datasheet-gen** | Generate structured datasheet-style L1 doc |
| **frs-gen** | L2 Functional Requirements |
| **cmd-protocol-gen** | L3 Command Protocol |
| **regmap-gen** | L4 Memory Map / Register spec |
| **adi-spec-gen** | L5 Analog-Digital Interface |
| **control-logic-gen** | L6 Control Logic |
| **test-debug-gen** | L7 Test & Debug |
| **timing-waveform-gen** | L8 Timing & Waveform (external + internal) |
| **integration-spec-gen** | L9 Integration (DTOP ports, submodules, wires) |
| **doc-consistency-check** | Cross-layer consistency verification |

### Phase 2 — RTL + Verification (13 skills)
spec-to-rtl, rtl-review, rtl-repair, rtl-constants-gen, assertion-gen, testbench-gen, formal-verify, equivalence-check, cdc-check, rdc-check, coverage-closure, ppa-predict, hls-c2rtl, synth-wrapper-gen.

### Phase 2/3 — Synthesis → GDSII (16 skills)
synth-doctor, dft-insert, atpg, upf-author, constraint-gen, sdc-validator, placement-optimize, cts-plan, sta-review, hold-fix, drc-fix, lvs-triage, ir-drop-triage, em-check, perc-check, eco-plan, power-analysis.

### Orchestration + sign-off (6 skills)
**flow-orchestrate** (canonical 33-step), spec-review, spec-validator, architecture-explore, checkpoint-gate, tapeout-checklist, regression-manage.

### Silicon-adjacent (6 skills)
analog-sizing, analog-layout, ams-sim, schematic-gen, bringup-plan, yield-diagnostic.

### FPGA prototyping (3 skills)
fpga-hps-bridge, fpga-signaltap, fpga-test-harness.

### Domain-specific (1 skill)
**otp-content-gen** — generate OTP memory contents from spec (single-wire ID controller family).

---

## MCP-EDA server

One Docker image (`hpretl/iic-osic-tools:latest`) provides every tool. Supports GF180MCU, SKY130, and custom PDKs (e.g. `m18e80pm180su`).

| Category | Tools |
|----------|-------|
| Synthesis | Yosys (`eda_synth`) |
| Verification | Verilator (`eda_lint`), iverilog (`eda_simulate`), SymbiYosys (`eda_formal`), cocotb (`eda_cocotb`), Yosys LEC (`eda_equiv`) |
| Timing | OpenSTA (`eda_sta`, `eda_sta_mcorner`) |
| Backend | OpenROAD (`eda_pnr`), KLayout (`eda_gds`, `eda_drc_klayout`), Magic (`eda_extraction`) |
| Signoff | Netgen (`eda_lvs`), OpenROAD PSM (`eda_ir_drop`), **Fault** (`eda_dft` via `fault_atpg_run`) |
| Analog | ngspice / Xyce (`eda_spice`) |
| Audit | vibe-ic-d programs (`eda_rtl_audit`) |
| FPGA | Quartus / Vivado (`eda_fpga_compile`, `eda_fpga_program`) |
| Search | PostgreSQL (`eda_ic_search`) |

See [mcp-eda/INSTALL_GUIDE.md](../mcp-eda/INSTALL_GUIDE.md).

---

## Deterministic programs

```
cd plugins/vibe-ic-d/programs && python3 -m pytest tests/ -q
# 526 passed, 2 skipped, 0 failed.
```

**Headline programs**:

*v0.46 — canonical flow + gates*:

| Program | Role |
|---|---|
| **`flow_compliance_check.py`** | Strict 33-step gate — reads `flow/phase2_phase3.yaml`, validates every step's outputs + gate predicate, rejects rubber-stamp waivers. **Exit 0 is the only PASS.** |
| `stage{1,2,3,4}_compliance.py` | Per-stage interim gates |
| **`waivers_schema_check.py`** | Rejects placeholder reasons (`TODO`, `n/a`), self-approvers (`agent`, `claude`), duplicate ids |
| **`fault_atpg_run.py`** | Open-source stuck-at ATPG via Fault + iic-osic-tools Docker. PDK_CONFIG table supports GF180 + m18e80pm180su. |
| **`rom_init_lint.py`** | Catches Quartus-unsafe `initial begin for(i=0;...) rom[i]=...` (silent-failure class surfaced 2026-04-21) |
| **`quartus_map_audit.py`** | Scans `.map.rpt` for `Stuck at GND/VCC`, Warning 10030/10855, lost fanout |
| **`bist_window_calculator.py`** | Computes sample-window size for BIST responses |
| `otp_image_check.py` | Validates OTP-content generator outputs |

*v0.47.2-.4 — anti-fabrication layer*:

| Program | Role |
|---|---|
| **`def_stage_progression_check.py`** | Rejects byte-identical stage DEFs (the "`cp routed.def 5 times`" cheat). Requires SHA uniqueness + size monotone + instance-count non-regression + `+ ROUTED` geometry. |
| **`provenance_logger.py`** | Wrap ANY tool invocation; records `{tool, version, argv, input/output hashes, exit, duration}` to `<project>/provenance.jsonl`. |
| **`provenance_check.py`** | Gate verifier: does `provenance.jsonl` contain an exit-0 entry, from an allow-listed tool, declaring this output, whose logged hash still matches the file on disk? Mandatory at Steps 9 / 19 / 24 / 27. |
| **`fpga_on_board_attestation_check.py`** | Step 28 hardening: rejects pure-JSON self-attestation. Requires pass.json + bitstream-hash match + Quartus programmer log + ≥1 non-JSON hardware artefact (webcam / UART / scope). |
| `eda_report_audit` tightened | Every mode now needs tool signature (OpenROAD/Netgen/KLayout/Magic) + `MIN_REPORT_BYTES`. Rejects hand-typed <2 KB stubs. |

See [plugins/vibe-ic-d/README.md](plugins/vibe-ic-d/README.md) for the full matrix.

---

## Repository structure

```
vibe-ic-marketplace/
├── AGENT_USAGE_GUIDE.md             ← MUST READ for any agent
├── README.md                        ← this file
├── .claude-plugin/marketplace.json
└── plugins/
    ├── vibe-ic/
    │   ├── flow/
    │   │   └── phase2_phase3.yaml   ← 33-step source of truth
    │   ├── agents/
    │   │   ├── ic-expert-agent.md    ← assembles JSON from answers + defaults
    │   │   └── lessons/
    │   │       ├── ic_expert_L1..L9.md   ← prose lessons per layer
    │   │       └── manifests/
    │   │           └── L1_manifest.json  ← 40-fact Q-bank (PoC)
    │   └── skills/
    │       ├── flow-orchestrate/    ← strict 33-step entry
    │       ├── phase1-orchestrate/  ← Phase-1 dialogue driver
    │       ├── spec-to-rtl/         ← Step 01
    │       ├── ...                  ← 60 skills total
    │       └── otp-content-gen/
    └── vibe-ic-d/
        ├── programs/
        │   ├── flow_compliance_check.py  ← final gate
        │   ├── stage{1,2,3,4}_compliance.py
        │   ├── waivers_schema_check.py
        │   ├── fault_atpg_run.py         ← Step 11 ATPG
        │   ├── rom_init_lint.py
        │   ├── quartus_map_audit.py
        │   ├── bist_window_calculator.py
        │   └── ...                       ← 62 programs total
        ├── skills/                       ← compliance YAMLs
        └── tests/                        ← 490 tests
```

External tools/ (at repo root): `tools/training/` (closed-loop harness), `tools/phase1_regression.py` (benchmark-driven regression for Phase 1).

---

## Links

- **Main repository**: [AI_IC_design](https://github.com/reyerchu/AI_IC_design)
- **Marketplace pattern**: [superpowers-marketplace](https://github.com/obra/superpowers-marketplace)
- **GF180MCU PDK**: [google/gf180mcu-pdk](https://github.com/google/gf180mcu-pdk)
- **SKY130 PDK**: [google/skywater-pdk](https://github.com/google/skywater-pdk)
- **Fault (open-source ATPG)**: [cloudv-io/fault](https://github.com/cloudv-io/fault)
- **iic-osic-tools Docker**: [hpretl/iic-osic-tools](https://hub.docker.com/r/hpretl/iic-osic-tools)

## License

MIT
