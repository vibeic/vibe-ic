# vibe-ic-d — Deterministic Edition (**v0.40**)

**Content-deterministic skill execution for vibe-ic-core.**

Release: v0.40 (2026-04-20) — 3-layer verification, 41 programs, 412 tests, 0 WEAK skills.

## What it does

When different AI agents execute the same `vibe-ic-core` skill, they
sometimes skip required sections, omit metadata fields, or forget the
hand-off block — producing outputs that differ in completeness, not just
in wording. This plugin makes execution **content-deterministic**:

> Different agents executing the same skill always ship outputs containing
> the same required elements, even when the prose inside each element
> varies.

## 3-Layer Verification Architecture

| Layer | Mechanism | What it catches |
|-------|-----------|----------------|
| **L1 — compliance.yaml** | Regex patterns on agent text output | Missing sections, missing keywords |
| **L2 — Deterministic programs** | Artifact checks (files, JSON, RTL, reports) | Agent claims without evidence |
| **L3 — mcp_execution_verify** | MCP tool execution proof via manifest | Agent faking tool runs |

Coverage: 58/58 skills have L1. 49/58 have L2. 10/58 have L3.

## How it works

1. For every vibe-ic-core skill, `vibe-ic-d` ships a `compliance.yaml`
   that enumerates every required output element (section headers,
   metadata fields, tool invocations, hand-off lines) as a regex list.
2. A shared driver `_shared/skill_compliance_check.py` audits any
   agent-produced output against the YAML.
3. **41 deterministic programs** verify actual artifacts on disk — not
   just what the agent wrote in its report.

## Layout

```
vibe-ic-d/
├── README.md                      — this file
├── run_tests.sh                   — runs the full test suite
├── pytest.ini                     — configures --import-mode=importlib
├── _shared/
│   ├── skill_compliance_check.py  — generic YAML-driven audit driver
│   ├── bootstrap_compliance.py    — regenerates all compliance.yaml
│   ├── gen_compliance_tests.py    — regenerates all test_compliance.py
│   └── add_compliance_gate.py     — adds gate section to SKILL.md files
├── programs/                      — 41 deterministic programs
│   ├── # RTL / PHY Audit (7)
│   ├── phy_counter_audit.py       — detects bus-sampling vs time-based TX counters
│   ├── crc_bitorder_check.py      — verifies CRC bit-reversal in TX loading
│   ├── interface_encoding_audit.py — detects gray-code/binary mismatches
│   ├── oe_pattern_check.py        — analyzes output-enable timing patterns
│   ├── rtl_hygiene_lint.py        — undriven wires, unread regs, case no-default
│   ├── fsm_error_invariant.py     — error-signal context auditor
│   ├── rx_tolerance_sweep.py      — pulse-width decode coverage analyzer
│   │
│   ├── # Design Artifact Check (6)
│   ├── constants_validation.py    — validates RTL constants JSON (name/value/width)
│   ├── integration_spec_audit.py  — validates L9 spec (dtop, submodules, wires)
│   ├── assertion_property_check.py — verifies SVA property declarations
│   ├── synth_wrapper_check.py     — verifies wrapper instantiates DUT
│   ├── sdc_syntax_check.py        — validates SDC create_clock + constraints
│   ├── upf_syntax_check.py        — validates UPF power domains + supplies
│   │
│   ├── # Backend Report Audit (8)
│   ├── eda_report_audit.py        — multi-mode: drc/lvs/power/em/ir_drop/sta
│   ├── drc_report_check.py        — wrapper: DRC violation categories
│   ├── lvs_report_check.py        — wrapper: LVS mismatch categories
│   ├── power_report_check.py      — wrapper: leakage + dynamic power
│   ├── em_report_check.py         — wrapper: EM current density
│   ├── ir_drop_report_check.py    — wrapper: IR-drop voltage values
│   ├── sta_report_check.py        — wrapper: WNS/TNS + setup/hold
│   ├── synth_netlist_check.py     — netlist cell count validation
│   │
│   ├── # Signoff / Flow (6)
│   ├── signoff_audit.py           — multi-mode: tapeout/flow
│   ├── tapeout_signoff_check.py   — wrapper: GDS/netlist/timing/DRC evidence
│   ├── flow_stage_check.py        — wrapper: synth/pnr/gds/sta stages
│   ├── coverage_metric_check.py   — coverage report percentage metrics
│   ├── cdc_crossing_check.py      — CDC clock domain crossing analysis
│   ├── gds_size_check.py          — GDS file existence and size
│   │
│   ├── # Infrastructure (14)
│   ├── module_port_audit.py       — DTOP port mismatch detection
│   ├── corner_coverage_audit.py   — PVT corner coverage (SS/TT/FF)
│   ├── sv_compat_check.py         — SystemVerilog construct detection
│   ├── pdk_consistency_check.py   — PDK target consistency
│   ├── fpga_qsf_lint.py           — FPGA QSF project validation
│   ├── testbench_exists_check.py  — testbench with >=10 test cases
│   ├── l9_completeness_check.py   — L9 Integration Spec completeness
│   ├── mcp_execution_verify.py    — MCP tool execution proof
│   ├── output_artifact_check.py   — output file existence
│   ├── json_schema_check.py       — JSON required keys validation
│   ├── eda_log_check.py           — EDA log pattern matching
│   ├── crc_vector_gen.py          — parametric CRC RTL+ref generator
│   ├── protocol_gap_check.py      — inter-unit-gap SVA generator
│   ├── tristate_bus_check.py      — bus-arbitration SVA generator
│   │
│   └── tests/                     — 32 test files, 412 tests
│       ├── test_constants_validation.py
│       ├── test_eda_report_audit.py
│       ├── test_report_wrappers.py  — tests all 8 thin wrappers
│       └── ... (29 more test files)
└── skills/
    ├── spec-to-rtl/
    │   └── compliance.yaml        — 12 requirements + 8 cross_checks
    ├── sta-review/
    │   └── compliance.yaml        — 6 requirements + 3 cross_checks
    ... (58 skills total)
```

## Test suite

```bash
cd programs && python3 -m pytest tests/ -v
```

**412 passed, 2 skipped, 0 failed.**

| Category | Tests | Programs |
|----------|------:|----------|
| RTL/PHY audit | 87 | 7 programs |
| Design artifact | 33 | 6 programs (5 new + constants_valid_json) |
| Backend report | 27 | 8 programs (eda_report_audit + 6 wrappers + synth_netlist) |
| Signoff/flow | 28 | 6 programs |
| Infrastructure | 218 | 14 programs |
| Wrapper integration | 16 | 8 thin wrappers |
| Generators (shared) | 3 | protocol_gap, tristate_bus, rx_tolerance |

## Skill Coverage Assessment

| Grade | Count | Meaning |
|-------|:-----:|---------|
| **STRONG** | 17 | All domain rules have program verification |
| **MEDIUM** | 17 | Some domain rules have program verification |
| **WEAK** | 15 | Domain rules are text-only (inherent limit — methodology/tool-result claims) |
| **TEXT_ONLY** | 9 | Advisory skills, no artifacts to verify |

Domain rule coverage: **73/129 (57%)** verified by programs.
Remaining 56 rules are inherently text-only (regex is the physical limit).

## Usage

### For agents executing a skill

After producing output:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/<skill>/compliance.yaml \
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
traced to SKILL.md sections that agents skipped silently. Enhanced
through 10-IC benchmark (v0.38), IC expert review (v0.39), and
3-layer verification architecture (v0.40).

## License

MIT
