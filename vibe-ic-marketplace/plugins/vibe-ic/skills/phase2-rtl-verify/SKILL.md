---
name: phase2-rtl-verify
description: After design_one_shot_runner emits RTL + SOF + reference TB PASS, AI spot-checks RTL quality and L9-contract conformance. Triggers when /vibe-ic-phase2 / /vibe-ic-phase2 returns PASS, or on phrases like "review the RTL", "check RTL quality", "verify phase 2 output".
tier: verification
paired_program: design_one_shot_runner.py
---

# Phase 2 RTL Verification

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt.
> Programs first; AI is the backstop on residual narrative.

## Mandatory Deterministic Preflight

```bash
python3 plugins/vibe-ic/programs/phase2_verify_aggregate.py \
    <project_dir> \
    --out-md /tmp/phase2_verify.md \
    --out-json /tmp/phase2_verify.json --strict
```

The aggregator runs `rtl_precheck_gate`, `spec_conformance_check`, and
`rtl_hygiene_lint`, AND checks RTL/SOF/TB artifact presence. **Refuse
to claim Phase 2 PASS without the aggregator's `verdict: PASS`.**

<!-- WAVE_76_CHIP_AGNOSTIC_BANNER -->

> **Case-study notation.** This skill cites the <chip-class> / <half-duplex-tester> /
> MDV-A1101 <benchmark> reference project as concrete evidence for the
> rules below. The rules themselves are chip-AGNOSTIC and apply to
> any IC of the matching `ic_class` (see
> `vibe-ic-marketplace/plugins/vibe-ic/programs/ic_class_profile.py`).

**Purpose**: phase2 runner generates RTL via `aid_class_rtl_gen.py` (or registry-dispatched per class), then runs reference TB + Quartus + the project's `<host_tester>`. PASS verdict means:
- iverilog reference TB outputs `PROTOCOL_REFERENCE_TB_PASS`
- Quartus emits SOF
- `<host_tester>` reads byte[6]=expected_verdict_byte_hex N/N runs

> **Case study reference.** Concrete `<host_tester>` examples (e.g.
> <chip-class> → <half-duplex-tester> byte[6]=0xF2 verdict) are documented in
> `docs/design/CASE_STUDIES/AS3616_MD905_byte6_verdict.md`.

But the RTL itself may still:
- have unused signals / unused states / dangling registers
- be hardware-correct for byte[6] but emit device-side BR or other Wave-34/35-class violations
- not actually match L9 ports contract beyond the bytes the TB exercises

## Verification checklist

1. **L9 contract conformance**: open `generated_docs/L9_INTEGRATION_SPEC.json`. Confirm rtl/chip_top.sv top-level ports == L9.ports[]. Confirm submodule list matches L9.submodules. Use `frontend_backend_handoff_check.py`.

2. **State-machine coverage**: open `rtl/main_fsm.sv`. List declared states. Confirm every L9.fsm_states[].name appears. Run `fsm_state_coverage_check.py`.

3. **Dead-RTL audit** — *enforced by `programs/rtl_hygiene_lint.py`* (already wired into the Mandatory Deterministic Preflight aggregator above). Its `rule_undriven_and_unread` emits `undriven-wire` (ERROR: `wire X` never driven) and `unread-reg` (WARN: `reg/logic X` written but never read); its `rule_case_coverage` flags missing case-default / un-covered case-arms. Do NOT hand-grep — read the aggregator's `rtl_hygiene_lint` verdict. AI only adjudicates a flagged signal as *intentional* (e.g. spare-cell tie-off) vs a real regression.

4. **Wave-34 device-BR forbidden**: scan rtl/tx_phy.sv + rtl/main_fsm.sv for any state that drives id_bus low for >= BR_MIN ticks. Use `slave_tx_no_device_break_check.py`.

5. **Self-RX mask**: confirm rtl/chip_top.sv has `id_in_masked = id_bus_drive_low ? 1 : id_in` pattern. Use `self_rx_mask_required_check.py`.

6. **OTP image cite**: confirm L11.otp_bytes[] addresses + values match what altsyncram / behavioral RAM is loading from `input/otp/<name>.{hex,mif}`.

7. **Reference TB transcript completeness** — *enforced by `programs/l10_tb_conformance_check.py`* + *`programs/l10_test_cases_cover_l3_constraints_check.py`*. The first FAILs unless EVERY case in `generated_docs/L10_TEST_CASES.json` has TB evidence (opcode literal driven in `sim/tb/*.v` AND a matching PASS record in the sim summary) — i.e. it counts the full prescribed scenario set, not just the canonical 5. The second FAILs unless every L3.opcodes[] constraint (addr_max / len_max / `pre_wake_allowed=false` / response template) has both a positive AND a negative L10 case (the "18 opcodes × {happy, addr_max, len_max, pre_wake_false}" expansion). Run both and read their verdicts:

```bash
python3 plugins/vibe-ic/programs/l10_tb_conformance_check.py \
    --l10 generated_docs/L10_TEST_CASES.json \
    --tb-dir phase2/stage1/sim/tb \
    --summary phase2/stage1/sim/work/summary.txt \
    --out reports/gates/l10_tb_conformance.json
python3 plugins/vibe-ic/programs/l10_test_cases_cover_l3_constraints_check.py <project_dir>
```

AI does NOT eyeball PASS-line counts — it only reviews any case the gates list as lacking evidence to confirm it is a genuine gap (re-spin) vs a documented waiver.

8. **byte[6]=0xF2 across SOF rebuild stress**: verify byte[6] PASS persists across at least 5 rebuild + reburn cycles (not just 5 connect_test runs of one SOF).

## Spot-check actions

- Pull a random opcode from L3.opcodes that's NOT in {0x70, 0x72, 0x74}, send via host_emulator (or scope inject), confirm chip responds with the expected response opcode.
- Diff this run's RTL vs known-good reference from a previously hardware-verified project. Identify structural deltas.

## When to escalate

- Find any Wave-34 violation → invoke `rtl-repair` for the bounded RTL
  repair/retry loop (not a physical/metal ECO)
- Find L9 contract mismatch → re-run phase2 after patching aid_class_rtl_gen template
- Find dead RTL → call out to user, may be intentional or may reveal regression

## Output

Append findings to `<project>/reports/phase2_verify.md`. If all checks pass, write single-line PASS summary.


## Compliance gate (mandatory — not optional)

After producing your output, save it to a file and run:

```bash
python3 ../../_shared/skill_compliance_check.py \
    --requirements ./compliance.yaml <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with the specific missing elements listed.
`compliance.yaml` (in this skill's directory) enumerates every required
element of your output — section headers, metadata fields, handoff lines,
tool invocations.

**Your task is not complete until the audit returns PASS.** If it fails,
re-read the listed missing elements, patch your output, and re-run the
audit.
