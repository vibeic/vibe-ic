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

## Configure the native SignalTap capture

Create the `.stp` in Quartus SignalTap for the selected device and compiled
hierarchy. Choose the actual sampling clock, DUT I/O, relevant FSM/BIST state,
trigger and buffer depth. Use node names from the current netlist. Do not
invent a clock or node name to satisfy a wrapper.

## Typical Debug Workflow

After changing SignalTap assignments, run the supported Quartus compile sequence, regenerate the programming file and program that result before collecting the native capture.

Use Quartus SignalTap to resolve the sampling clock and probe nodes against the current compiled hierarchy. Confirm the trigger, depth and DUT/BIST signal coverage in the actual capture configuration.

### Recompile and capture

After changing the `.stp` or project assignments, use Quartus's supported
compile sequence to regenerate the programming file, program the device and
run SignalTap. Read the native compile, fit and timing results before
interpreting the capture. Record the actual sampling clock and trigger.

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
