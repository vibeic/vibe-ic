# Vibe-IC Plugin — Agent Usage Guide

**STOP.** If you are an AI agent and you have been asked to do anything
involving IC design with this plugin, read this document **before** writing
any code, Tcl, shell, or prompt.

This guide exists because agents (including Claude Code itself, on
2026-04-21) have previously taken "run phase 2+3" tasks and skipped 21 of
28 mandatory steps while declaring PASS. That is not acceptable. The rules
below prevent it.

---

## How to tell what you are being asked

| User phrase | Canonical task | Required entry point |
|---|---|---|
| "run phase 2+3", "synth → GDS", "make it taped out", "RTL to silicon", "run the flow" | **Phase 2+3 canonical flow** | Skill `flow-orchestrate` |
| "generate L1-L9 from this datasheet", "phase 1" | Phase 1 document stack | Skill `datasheet-gen` + L2-L9 skills |
| "write a testbench for X" | Single-skill invocation | Skill `testbench-gen` |
| "review this RTL" | Single-skill invocation | Skill `rtl-review` |

If the task is **anything with downstream EDA** (synth, PnR, GDS, FPGA
sign-off, tape-out, final build), treat it as a phase 2+3 canonical flow.
Anything less and you will miss steps.

---

## Hard rules (violations are caught by `flow_compliance_check.py`)

### Rule 1 — Flow entry point is `flow-orchestrate`, not direct tool calls

**Wrong:**
```
Agent prompt: "Run Quartus, then Yosys, then OpenROAD, then KLayout."
```

**Right:**
```
Agent prompt: "Invoke the `flow-orchestrate` skill with <inputs>.
Follow its 33-step canonical flow. Run flow_compliance_check --strict
at the end; do not declare PASS unless exit 0."
```

### Rule 2 — Emit the 33-step plan table before executing step 1

The user must see ALL 33 steps (as rows in a plan table) BEFORE any step
is executed. This is the single strongest defence against "I'll declare
PASS after 7 steps" — because the plan table makes the scope explicit
up-front.

The plan table must be generated from:

```
vibe-ic-core/flow/phase2_phase3.yaml
```

This YAML is the single source of truth. Skills/programs reference it;
the compliance gate reads it; the plan table summarises it.

### Rule 3 — Compliance gate is the ONLY acceptance criterion

After step 33 runs, invoke:

```bash
python3 plugins/vibe-ic-d/programs/flow_compliance_check.py \
    <project_dir> --strict --json <project_dir>/reports/compliance.json
```

- Exit 0 → you may declare PASS, and must include the JSON report in the
  final response to the user.
- Exit 1 → declare FAIL, list every FAIL/MISSING step, recommend next action.
- Exit 2 → plugin setup error, do not claim any result.

Per-stage gates (for large campaigns; recommended after each stage):

```bash
python3 plugins/vibe-ic-d/programs/stage1_compliance.py <project_dir>
python3 plugins/vibe-ic-d/programs/stage2_compliance.py <project_dir>
python3 plugins/vibe-ic-d/programs/stage3_compliance.py <project_dir>
python3 plugins/vibe-ic-d/programs/stage4_compliance.py <project_dir>
```

Each exits 0 only if every step in that stage passes (or is waived).

### Rule 4 — Skips require waivers, not silence

If a step genuinely cannot run (e.g., no FPGA board this session for
step 33), write to `<project_dir>/waivers.json`:

```json
{
  "waived_steps": [
    {"id": 33, "reason": "No FPGA board available this session", "approver": "user"}
  ]
}
```

The compliance report will show waived steps as `SKIPPED-WAIVED`.

### Rule 5 — Hardware-attestation chain (mandatory for any HW-based PASS claim)

The most damaging fresh-agent failure mode the platform has seen is the
**stale-rig PASS**: the agent runs `device_tester_md905_connect_test`,
sees a PASS coming back from a SOF that was burned to the FPGA in a
**previous session**, and ships the verdict as if its own work passed.
The plugin contract makes this impossible if you follow this rule:

1. **Compile your own SOF this session.** Invoke
   `mcp__eda-tools__eda_fpga_compile`. The result will include
   `compiled_artifact_sha256` and `session_id`. Both go into
   `latest_results.jsonl` automatically.
2. **Program it this session — same session_id.** Invoke
   `mcp__eda-tools__eda_fpga_program` on the SOF you just compiled.
   The result will include `programmed_artifact_sha256` and
   `program_matches_compile`. Verify the latter is `true`.
3. **Only after a clean compile→program does any rig PASS count.**
   Cite `connect_test` PASS only if its `session_id` matches the
   compile/program session **and** its timestamp is later than the
   `fpga_program` step.
4. **Run `fpga_program_chain_attest_check.py <project>` before
   declaring a hardware-attestation PASS.** It scans
   `latest_results.jsonl` and rejects:
     - missing compile / missing program
     - session_id mismatch between compile and program
     - artefact-hash mismatch (the SOF on the board ≠ the SOF you
       compiled)
     - connect_test PASS that predates the `fpga_program` step

A "PASS from connect_test alone" without a session-matched compile +
program is **NOT acceptance** and the supervisor will reject it.

If hardware genuinely is not accessible, waive Step 28 (per Rule 4)
with an honest reason — do **NOT** read a stale rig PASS as evidence.
Tape-out requires a human to have reviewed every waiver.

### Rule 5b — Behavioural-state coverage before claiming Phase-2c done

When you DO have a board attached and you are running on-rig
verification, byte-stream correctness alone is not coverage. Before
declaring Phase-2c (on-board functional) PASS:

1. For each cmd opcode the design supports, send the opcode and
   capture the response payload.
2. Verify the SIDE-EFFECTS the spec mandates for that opcode — not
   just the response bytes. Examples:
     - awake-state register set or cleared
     - register echoed back on subsequent read
     - periodic timer started or stopped
     - cc_en raised / lowered
   Use `mcp__eda-tools__device_camera_capture` +
   `device_camera_led_diff` to read these states off the FPGA's LEDs
   (see the `fpga-led-probe-allocation` skill for the LED layout).
3. Run `functional_state_transition_coverage_check.py` (vibe-ic-d)
   against your TBs to confirm each opcode has at least one state
   assertion.
4. The `behavioural-state-coverage` table goes into `RESULTS.md`
   alongside the synthesis metrics.

The vendor run shipped a 5-bug release because the on-rig verification
checked response bytes but never the side-effect state changes.

### Rule 5c — FINAL_REPORT.md must cite the artefact's SHA-256

When you produce `RESULTS.md` (or `FINAL_REPORT.md`), include the
SHA-256 of the GDS, SOF, and any signed-off netlist. Without this,
a reviewer cannot tell whether the report describes the artefact in
the workspace or some earlier iteration. mcp-eda-server's
`eda_fpga_compile` and `eda_fpga_program` already record the hash —
copy it into the report verbatim.

### Rule 5 — No "3 of 4" soft passes

The legacy `signoff_audit.py --mode flow` used to pass at 3-of-4
evidence. That threshold was the reason I (Claude Code) passed a
"3/4 artefacts present" design as complete while missing STA, DFT, IR
drop, and 18 other steps.

It has been tightened. Do not re-introduce the loose threshold. The
`flow_compliance_check.py` gate requires 28-of-28 (minus waivers).

### Rule 6 — One skill per task; skills are the API

Plugin skills are the interface contract with the human. If you find
yourself writing `subprocess.run(["yosys", ...])` in an agent prompt,
stop — invoke the `synth-doctor` skill or MCP `eda_synth` instead.
Raw tool calls bypass the logging, compliance, and PRACTICAL_NOTES
infrastructure.

---

## Quick reference

### Files that encode authority

| Path | What it is |
|---|---|
| `plugins/vibe-ic-core/flow/phase2_phase3.yaml` | 33-step machine-readable flow definition (source of truth) |
| `plugins/vibe-ic-core/skills/flow-orchestrate/SKILL.md` | Human-readable canonical flow + orchestration rules |
| `plugins/vibe-ic-d/programs/flow_compliance_check.py` | Acceptance gate (must exit 0 for PASS) |
| `plugins/vibe-ic-d/programs/stage{1,2,3,4}_compliance.py` | Per-stage interim gates |
| `docs/design/STANDARD_FLOW.md` | The original 33-step specification (human-readable) |

### What to write in your first message to the user

```
I have been given a phase 2+3 task. Per the Vibe-IC canonical flow
(vibe-ic-core/flow/phase2_phase3.yaml), the mandatory 33 steps are:

Stage 1 (RTL + Verification):
  01 Spec-to-RTL         — skill: spec-to-rtl
  02 Lint                — skill: rtl-review + 2 programs
  03 CDC / RDC           — skills: cdc-check + rdc-check
  04 Simulation          — skill: testbench-gen + MCP eda_simulate
  05 Formal              — skills: assertion-gen + formal-verify
  06 FPGA early proto    — skill: fpga-test-harness + MCP eda_synth
Stage 2 (Synth + DFT):
  07 Constraint setup    — skill: constraint-gen
  08 SDC validation      — skill: sdc-validator
  09 Synthesis           — skill: synth-doctor + MCP eda_synth
  10 Pre-layout STA      — skill: sta-review + MCP eda_sta
  11 DFT insertion       — skills: dft-insert + atpg
  12 Post-DFT opt        — skill: synth-doctor
  13 Equivalence check   — skill: equivalence-check
Stage 3 (Physical + Sign-off):
  14 Floorplan + PDN     — MCP eda_pnr
  15 Clock planning      — skill: cts-plan
  16 Placement           — skill: placement-optimize + MCP eda_pnr
  17 CTS                 — MCP eda_pnr
  18 Post-CTS hold fix   — skill: hold-fix
  19 Routing             — MCP eda_pnr
  20 Parasitic Extract   — MCP eda_extraction (RC → SPEF)
  21 Post-route STA      — skill: sta-review + MCP eda_sta
  22 IR drop             — skill: ir-drop-triage
  23 EM check            — skill: em-check
  24 Antenna check       — (PDK)
  25 Signal Integrity    — crosstalk / noise analysis
  26 Post-Layout Sim     — gate-level sim + SDF back-annotation
  27 Phys verify (DRC/LVS/ERC/Density) — skills: drc-fix + lvs-triage + perc-check
  28 ECO repair loop     — skill: eco-plan (re-verify if changes)
Stage 4 (Output + Validation):
  29 Power analysis      — skill: power-analysis
  30 Metal Fill          — density fill insertion
  31 Tapeout checklist   — skill: tapeout-checklist
  32 GDSII output        — MCP eda_gds (gated on 27, 31)
  33 FPGA final sign-off — skill: fpga-test-harness

I will execute these in order, gate each, and report the compliance
matrix at the end. PASS is declared only when flow_compliance_check
--strict exits 0.
```

No step may be silently omitted. No step may be run out of order.

---

## For humans reading this

This guide is intentionally verbose and repetitive. It encodes lessons
from real failure modes:

- **2026-04-21 — Claude Code ran 7 of 28 steps and declared "10/10 PASS"**
  for a 10-IC phase 2+3 campaign. Root cause: ad-hoc agent prompts that
  invoked Quartus/Yosys/OpenROAD directly instead of going through
  `flow-orchestrate`. Loose compliance threshold (3/4) meant the audit
  passed anyway. This guide is the fix.

When you see future failure modes, add them here. This document is the
plugin's public-facing contract with agents.
