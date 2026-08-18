# FPGA SignalTap — PRACTICAL_NOTES

> Source: SignalTap Generator development + CD4013B debug experience
> Version: v0.25

---

## 1. Overview

The fpga-signaltap skill auto-generates Quartus SignalTap II `.stp` configuration files. The skill was developed during CD4013B FPGA-test debugging to capture DUT internal signals when BIST fails.

> **TWO PRODUCERS, AND THEY DISAGREE (measured 2026-08-03, vibe-ic#693).**
> This document describes `tools/signaltap_gen.py`; `SKILL.md` names the MCP
> tool `eda_rtl_signaltap_autogen`. They are not interchangeable. Validated with
> `programs/signaltap_stp_completeness_check.py` against the same published RTL:
> `signaltap_gen.py` **PASSES** (ports + BIST group + populated trigger + depth
> + clock); `eda_rtl_signaltap_autogen` **FAILS** on its default invocation
> (one heuristic signal, no ports, no BIST group, empty `<trigger_set/>`).
> Whichever you use, run the validator on the output before you spend a
> Quartus round-trip on it.

---

## 2. Port-parsing caveats

signaltap_gen.py parses the module port list from SystemVerilog source. Known pitfalls:

### 2.1 Formats that parse successfully

```systemverilog
// Standard ANSI port declaration — parses correctly
module foo (
    input  logic        clk,
    input  logic [7:0]  data_in,
    output logic [15:0] data_out
);
```

### 2.2 Formats that may fail to parse

| Format | Issue | Workaround |
|------|------|------|
| Non-ANSI port style | `module foo(a, b);` + separate declarations | switch to ANSI style or use `--ports` manually |
| With `signed` modifier | `input logic signed [8:0] temp` | v0.25 fixed this |
| With default value | `input logic en = 1'b1` | remove default value |
| Multi-line comment in the middle | `/* ... */` spanning multiple lines | use `//` single-line comments |
| `interface` port | `modport slave s` | not supported, must specify manually |
| Packed struct port | `input my_struct_t data` | use `--ports` to specify manually |

### 2.3 Recommendation

For modules where parsing fails, use `--ports` to specify manually:
```bash
python3 signaltap_gen.py --module lm75 \
    --ports "clk:I:1,rst_n:I:1,scl_i:I:1,sda_i:I:1,sda_o:O:1,sda_oe:O:1,addr:I:3,temp_data:I:9,os_out:O:1"
```

---

## 3. Trigger-signal selection notes

### 3.1 Recommended trigger signals

| Scenario | Recommended trigger | Rationale |
|------|-------------|------|
| BIST failure debug | `bist_fail` (rising edge) | precisely catches the first failure point |
| I2C communication debug | `sda_oe` (rising edge) | captures the moment the slave starts driving SDA |
| FSM stuck | `fsm_state == IDLE` | use pattern trigger to detect return to IDLE |
| Timing violation | `clk` (rising edge) | needs pre-trigger to see setup/hold |
| UART output debug | `uart_tx_valid` (rising edge) | captures every UART byte |

### 3.2 Trigger-level recommendations

SignalTap supports multi-level trigger (e.g. A then B), but adding trigger levels significantly increases FPGA resource usage:

| Trigger levels | Extra ALMs | Use case |
|:------------:|:---------:|----------|
| 1 (basic) | ~50 | most debug needs |
| 2 (sequential) | ~150 | requires "event A followed by event B" |
| 3+ | ~300+ | rarely useful — UART log is more practical |

### 3.3 CD4013B debug experience

When BIST v2 failed, the issue captured via SignalTap:
- **Trigger**: `bist_fail` rising edge
- **Capture depth**: 1024 samples
- **Finding**: the BIST engine waited only 1 clock after applying `set1=1`, but the async-set output needs 2 clocks to settle (because the output goes through a combinational MUX)
- **Fix**: BIST wait counter changed from 1 to 3

---

## 4. Capture-buffer design

### 4.1 Buffer-depth selection

| Depth | M10K Blocks | Use case |
|:-----:|:-----------:|----------|
| 256 | 1 | quick scan, few signals (<10 signals) |
| 1024 | 2-4 | **recommended default**, enough to see full BIST sequence |
| 2048 | 4-8 | I2C/SPI transactions need a longer window |
| 4096+ | 8+ | only large FPGAs have enough M10K |

### 4.2 M10K resource on Cyclone V 5CSEBA6U23I7

- Total of 553 M10K blocks
- SignalTap recommendation: do not exceed 10% = 55 blocks
- For 1024 depth + 32 signals, ~4 blocks are used (very small)

---

## 5. Integration with fpga-test-harness

### Workflow

```
1. fpga-test-harness produces the BIST SOF
2. Program the FPGA, run BIST
3. If BIST PASS → done
4. If BIST FAIL:
   a. fpga-signaltap generates .stp
   b. add STP_FILE assignment in .qsf
   c. re-run quartus_map → quartus_fit → quartus_asm
   d. re-program, run BIST again
   e. SignalTap auto-triggers and captures signals
   f. analyse the waveform → fix RTL or BIST
```

### Auto-injected QSF lines for STP

```tcl
set_global_assignment -name ENABLE_SIGNALTAP ON
set_global_assignment -name USE_SIGNALTAP_FILE <module>_debug.stp
set_global_assignment -name SLD_NODE_CREATOR_ID 110 -section_id auto_signaltap_0
```

---

## 6. Known limitations

1. **Requires JTAG link**: SignalTap-captured data flows back to the PC over USB-Blaster JTAG, which is inconvenient for remote debug
2. **Compile-time increase**: adding SignalTap raises quartus_fit time by roughly 20-30%
3. **Port parser does not support SV interface**: see section 2.2 above
4. **.stp XML format depends on Quartus version**: schemas may differ between v23.1 and v25.1
5. **Cannot auto-analyse waveforms**: post-.stp waveform analysis still requires manual work (or future VCD-parser integration)

---

## 7. Suggested improvements

1. Add VCD/EVCD output parsing to auto-compare SignalTap capture vs golden model
2. Support auto-generation of trigger conditions from SVA assertions
3. Add a "minimal signal set" mode: capture only DUT ports + FSM state to reduce resource usage
4. Support the XML format of the Quartus 25.1 Signal Tap Logic Analyzer (new version)
