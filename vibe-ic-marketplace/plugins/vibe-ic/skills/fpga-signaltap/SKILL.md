---
name: fpga-signaltap
description: "Auto-generate Quartus SignalTap II logic analyzer configurations for FPGA debugging. When to use: FPGA BIST fails and UART log isn't enough to diagnose the root cause. Generates .stp file that captures all DUT I/O signals, internal FSM state, and BIST engine state with configurable triggers. Triggers when: 'signaltap', 'debug FPGA', 'capture signals', 'logic analyzer', 'BIST failed need debug', or when Phase 3 FPGA verification fails and more visibility is needed."
---

# SignalTap II Auto-Generator

Auto-generate Quartus SignalTap II logic analyzer configurations for post-synthesis FPGA debugging.

## When to Use

1. FPGA BIST reports FAIL but UART log doesn't show the root cause
2. Need to capture internal signal transitions at speed
3. Debugging timing-dependent issues that simulation doesn't reproduce
4. Verifying that actual DUT behavior matches expected waveforms

## Requirements

- **Quartus 23.1+** (SignalTap II is included in all editions)
- **DE10-Nano** target board (or any Intel/Altera FPGA with JTAG)
- **USB-Blaster** JTAG cable for signal capture

## Tool: .stp generation (deterministic — MCP tool, not prose)

The `.stp` is generated deterministically by the MCP tool
**`eda_rtl_signaltap_autogen`** — it scans the RTL for the DUT port list +
timing-critical signals and emits the Quartus SignalTap XML (`.stp`) or Vivado
ILA `.tcl`. Defaults: `clock_signal=CLOCK_50`, `depth=2048`, trigger on the
BIST fail event. Pass `extra_signals=[...]` to add anything the heuristic misses.

```text
eda_rtl_signaltap_autogen(rtl_dir=..., top_module=..., target="quartus",
                          clock_signal="CLOCK_50", depth=2048)
  -> <top_module>_debug.stp
```

## Generated .stp policy — enforced by `programs/signaltap_stp_completeness_check.py`

The capture-signal include-set and the trigger/depth/clock policy are NOT
judgment — they are a fixed checklist verified by
`programs/signaltap_stp_completeness_check.py`. The generated `.stp` MUST contain:

1. **All DUT input signals** + **all DUT output signals** (parsed from `--sv`
   or `--ports "name:dir:width,..."`) — a port driven on the board but absent
   from the capture is a `MISSING_PORT` FAIL.
2. **The four BIST-engine signals** `bist_state`, `test_index`, `pass_count`,
   `fail_count` — any absent is a `MISSING_BIST_SIGNAL` FAIL.
3. A **trigger** (default = rising edge of `bist_fail`), a positive
   **sample_depth** (default 1024), and a capture **clock** (default
   `CLOCK_50`) — missing any is `NO_TRIGGER` / `BAD_DEPTH` / `NO_CLOCK`.

```bash
python3 programs/signaltap_stp_completeness_check.py <module>_debug.stp \
    --sv rtl/<module>.sv --json stp_check.json
# 0=PASS  1=FAIL(findings)  2=io-error ; SKIP(0) only when no .stp is given.
```

## Typical Debug Workflow

```
1. BIST runs on FPGA → reports FAIL via UART
2. AI Agent runs eda_rtl_signaltap_autogen to create the .stp
   → validate it with programs/signaltap_stp_completeness_check.py
3. Re-compile SOF with SignalTap enabled (4 stages, in THIS order):
   quartus_stp <module>_fpga --stp_file=<module>_debug.stp
   quartus_map <module>_fpga  (re-fit with logic analyzer)
   quartus_fit <module>_fpga
   quartus_asm <module>_fpga
   → validate the sequence with programs/signaltap_recompile_sequence_check.py
4. Program FPGA, run BIST again
5. SignalTap captures signals around the failure point
6. Analyze waveforms in Quartus SignalTap Viewer  ← LLM judgment (see below)
7. Identify root cause → fix RTL → re-verify
```

### Recompile sequence — enforced by `programs/signaltap_recompile_sequence_check.py`

The 4-stage Quartus pipeline is a fixed, ordered command sequence — not prose.
`programs/signaltap_recompile_sequence_check.py` verifies all four stages are
present, in canonical order (`quartus_stp → map → fit → asm`), with a real
`.stp` attached via `--stp_file`. It catches the common silicon-debug defect
where an agent omits `quartus_stp` and ships a SOF with **no logic analyzer at
all** (`STAGE_MISSING`), or attaches the `.stp` after the fit (`WRONG_ORDER`).

```bash
python3 programs/signaltap_recompile_sequence_check.py recompile.sh \
    --expect-stp <module>_debug.stp --json recompile_check.json
# 0=PASS  1=FAIL  2=io-error ; SKIP(0) when no quartus_* sequence is present.
```

### LLM-judgment step (NOT a program)

Step 6 — **post-capture waveform interpretation** — is the genuine LLM step:
looking at the capture around the failure point and reasoning *"actual vs
expected diverged here because the FSM took the wrong branch"*, deciding WHICH
extra internal signals (beyond the standard set) are worth probing for a novel
bug, and the final root-cause → RTL-fix inference. These are pattern-recognition
tasks that do not reduce to a regex/threshold and stay as agent judgment.

## Integration with fpga-test-harness

When fpga-test-harness generates a BIST that fails:
1. The BIST engine sets `bist_fail` high on first comparison mismatch
2. SignalTap triggers on this signal
3. Pre-trigger captures show the state leading up to failure
4. Post-trigger captures show the actual vs expected divergence

## Example Output

For `cd4013b`:
```xml
<session>
  <instance entity_name="cd4013b_fpga_top" ...>
    <signal_set name="cd4013b_debug">
      <signal name="cd4013b_inst|clk" tap_mode="classic" />
      <signal name="cd4013b_inst|rst_n" tap_mode="classic" />
      <signal name="cd4013b_inst|d" tap_mode="classic" />
      <signal name="cd4013b_inst|q" tap_mode="classic" />
      <signal name="bist_engine|bist_state[2:0]" tap_mode="classic" />
      <signal name="bist_engine|test_index[4:0]" tap_mode="classic" />
      ...
    </signal_set>
    <trigger>
      <basic_trigger>
        <trigger_input signal="bist_fail" edge="rising" />
      </basic_trigger>
    </trigger>
    <buffer depth="1024" />
  </instance>
</session>
```

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
audit. This guarantees that different agents executing this same SKILL.md
produce reports containing the same required elements, even when the prose
inside each element differs. Missing elements are the single largest
source of skill-execution non-determinism.
