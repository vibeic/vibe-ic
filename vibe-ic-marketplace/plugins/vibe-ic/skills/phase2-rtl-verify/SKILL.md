---
name: phase2-rtl-verify
description: After phase2_one_shot_runner emits RTL + SOF + reference TB PASS, AI spot-checks RTL quality and L9-contract conformance. Triggers when /vibe-ic-phase2 / /vibe-ic-phase2 returns PASS, or on phrases like "review the RTL", "check RTL quality", "verify phase 2b output".
tier: verification
paired_program: phase2_one_shot_runner.py
---

# Phase 2b RTL Verification

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
> `docs/design/CASE_STUDIES/EXAMPLE_CHIP_EXAMPLE_TESTER_byte6_verdict.md`.

But the RTL itself may still:
- have unused signals / unused states / dangling registers
- be hardware-correct for byte[6] but emit device-side BR or other Wave-34/35-class violations
- not actually match L9 ports contract beyond the bytes the TB exercises

## Verification checklist

1. **L9 contract conformance**: open `generated_docs/L9_INTEGRATION_SPEC.json`. Confirm rtl/chip_top.sv top-level ports == L9.ports[]. Confirm submodule list matches L9.submodules. Use `frontend_backend_handoff_check.py`.

2. **State-machine coverage**: open `rtl/main_fsm.sv`. List declared states. Confirm every L9.fsm_states[].name appears. Run `fsm_state_coverage_check.py`.

3. **Dead-RTL audit**: search rtl/ for `reg X` declarations where X is never read; for `wire X` declarations where X is never assigned; for case-arms that are unreachable.

4. **Wave-34 device-BR forbidden**: scan rtl/tx_phy.sv + rtl/main_fsm.sv for any state that drives id_bus low for >= BR_MIN ticks. Use `slave_tx_no_device_break_check.py`.

5. **Self-RX mask**: confirm rtl/chip_top.sv has `id_in_masked = id_bus_drive_low ? 1 : id_in` pattern. Use `self_rx_mask_required_check.py`.

6. **OTP image cite**: confirm L11.otp_bytes[] addresses + values match what altsyncram / behavioral RAM is loading from `input/otp/<name>.{hex,mif}`.

7. **Reference TB transcript inspection**: open `sim/reference_tb/ref_tb.log`. Confirm it includes ALL scenarios the L10 test_cases prescribe, not just the canonical 5. If L10 has 18 opcodes × happy + addr_max + len_max + pre_wake_false cases, transcript should show ≥40 PASS lines.

8. **byte[6]=0xF2 across SOF rebuild stress**: verify byte[6] PASS persists across at least 5 rebuild + reburn cycles (not just 5 connect_test runs of one SOF).

## Spot-check actions

- Pull a random opcode from L3.opcodes that's NOT in {0x70, 0x72, 0x74}, send via host_emulator (or scope inject), confirm chip responds with the expected response opcode.
- Diff this run's RTL vs known-good reference from a previously hardware-verified project. Identify structural deltas.

## When to escalate

- Find any Wave-34 violation → invoke `rtl-repair` skill for ECO loop
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

