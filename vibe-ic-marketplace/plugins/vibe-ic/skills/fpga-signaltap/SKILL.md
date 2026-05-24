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

## Tool

### signaltap_gen.py

Auto-generates `.stp` file from RTL port list:

```bash
# From a SystemVerilog source file
python3 tools/vibe_ic_tools/signaltap_gen.py --module cd4013b --sv rtl/cd4013b.sv

# With custom trigger and depth
python3 tools/vibe_ic_tools/signaltap_gen.py --module cd4013b --sv rtl/cd4013b.sv \
    --trigger bist_fail --depth 2048 --clock clk_50

# From manual port list
python3 tools/vibe_ic_tools/signaltap_gen.py --module cd4013b \
    --ports "clk:I:1,rst_n:I:1,d:I:1,q:O:1,q_bar:O:1" \
    --trigger bist_fail
```

**Input**:
- Module name + `.sv` file (auto-parses ports)
- OR: Module name + manual port list string

**Output**: `<module>_debug.stp` — Quartus SignalTap configuration XML

**Options**:
| Flag | Default | Description |
|------|---------|-------------|
| `--module` | (required) | Top-level DUT module name |
| `--sv` | None | SystemVerilog source to parse ports from |
| `--ports` | None | Manual port list: "name:dir:width,..." |
| `--trigger` | `bist_fail` | Signal name for trigger (rising edge) |
| `--depth` | 1024 | Capture buffer depth (samples) |
| `--clock` | `CLOCK_50` | Capture clock signal |
| `--output` | `<module>_debug.stp` | Output file path |

## Generated .stp Captures

For each DUT, the .stp file captures:

1. **All DUT input signals** — stimulus being applied
2. **All DUT output signals** — actual responses
3. **BIST engine state** — `bist_state`, `test_index`, `pass_count`, `fail_count`
4. **Trigger**: configurable, default = rising edge of `bist_fail` signal

## Typical Debug Workflow

```
1. BIST runs on FPGA → reports FAIL via UART
2. AI Agent runs signaltap_gen.py to create .stp
3. Re-compile SOF with SignalTap enabled:
   quartus_stp <module>_fpga --stp_file=<module>_debug.stp
   quartus_map <module>_fpga  (re-fit with logic analyzer)
   quartus_fit <module>_fpga
   quartus_asm <module>_fpga
4. Program FPGA, run BIST again
5. SignalTap captures signals around the failure point
6. Analyze waveforms in Quartus SignalTap Viewer
7. Identify root cause → fix RTL → re-verify
```

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
