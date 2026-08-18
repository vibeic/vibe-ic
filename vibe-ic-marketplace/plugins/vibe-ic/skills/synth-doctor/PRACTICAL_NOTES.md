# Synth Doctor — PRACTICAL_NOTES

> Source: 135-IC v2 Campaign (2026-04-09 ~ 04-10)
> Version: v0.25

---

## 1. Overview

In the 135-IC campaign, Synth Doctor processed Yosys synthesis results for all 135 ICs. Out of 134 ICs that synthesised (1 had no synth.log), 80 hit WARNING-level issues, 23 hit FAIL, and 31 PASSed cleanly.

| Stat | Value |
|------|:----:|
| Synth PASS (0 error, 0 warning) | 31 |
| Synth WARN (warnings present) | 80 |
| Synth FAIL (errors present) | 23 |
| No synth.log | 1 |

---

## 2. Most common error patterns

### 1. MULTI_DRIVER (most common, 11 occurrences)

**Symptom**: the same signal is driven by multiple `always_ff` blocks.

**Typical scenarios**:
- In an I2C slave, `sda_oe` is driven by both ACK logic and data-shift logic
- In an FSM, the output register is assigned in both the state logic and the output logic
- In a multi-clock-domain design, a handshake signal is driven by two clock domains

**Auto-fix approach**:
Merge all drivers into a single `always_ff` block using a priority if-else structure:
```systemverilog
// Before fix (two always_ff blocks driving sda_oe)
// After fix (merged into a single always_ff)
always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) sda_oe <= 1'b0;
    else if (ack_phase) sda_oe <= 1'b1;
    else if (data_phase) sda_oe <= shift_out;
    else sda_oe <= 1'b0;
end
```

**Success rate**: ~90%. A few complex multi-layer FSM cases require human judgement on merge order.

### 2. UNPACKED_ARRAY (common)

**Symptom**: Yosys does not support unpacked arrays as module ports or in some contexts.

**Typical scenarios**:
- A register file declared `logic [7:0] regs [0:255]` then exposed as a port
- A test-vector ROM using unpacked array `logic [15:0] vectors [0:31]`

**Auto-fix approach**:
Flatten to a packed array:
```systemverilog
// Before fix
output logic [7:0] regs [0:3]
// After fix
output logic [31:0] regs_flat  // {regs[3], regs[2], regs[1], regs[0]}
```

**Success rate**: 95%. Straightforward array flattening rarely goes wrong.

### 3. WIDTH_MISMATCH (common)

**Symptom**: signal-width mismatch, usually implicit truncation or extension.

**Typical scenarios**:
- A 12-bit DAC value assigned to a 16-bit register
- A 7-bit I2C address compared with an 8-bit register in an address comparator

**Auto-fix approach**: add explicit bit width: `{4'b0, dac_val}`

**Success rate**: 85%. Mostly direct zero-padding; a few need a judgement call between sign-extend and zero-extend.

### 4. LATCH_INFERENCE (common)

**Symptom**: incomplete case/if in `always_comb` causing a latch to be inferred.

**Typical scenarios**:
- A decoder case with no default
- FSM next-state logic missing some states

**Auto-fix approach**: add a default assignment at the top of `always_comb`.

**Success rate**: 95%.

### 5. Other less common patterns

| Pattern | Occurrences | Auto-fix rate |
|---------|:--------:|:---------:|
| RETURN_IN_FUNC | ~3 | 90% |
| PAST_IN_COMB | ~2 | 80% |
| AUTOMATIC_IN_FF | ~2 | 95% |
| SYNTAX_ERROR | ~5 | manual |
| MODULE_NOT_FOUND | ~1 | 95% |
| UNKNOWN | ~3 | manual |

---

## 3. Auto-fix statistics

| Metric | Value |
|------|:----:|
| Total fix attempts | 23 (FAIL ICs) |
| Auto-fix success | ~18 |
| Required manual intervention | ~5 |
| Auto-fix success rate | ~78% |

Reasons fixes failed:
1. Complex multi-layer module hierarchy where fixing one driver impacts other modules
2. Syntax errors involving SystemVerilog features Yosys does not support (e.g. interface, package)
3. Large-SoC cross-module-reference fixes that require understanding the architecture

---

## 4. Known limitations

1. **Cannot handle SystemVerilog interface/modport**: Yosys has limited SV interface support; synth_doctor cannot auto-fix
2. **Slow log parsing on large designs (>50K cells)**: P&R logs can be hundreds of MB; parse time is significant
3. **P&R doctor's DRT_POWER_NET pattern is not auto-fixable**: requires manual floorplan adjustment
4. **Does not detect timing violations**: timing issues are handled by STA, out of synth_doctor scope
5. **MULTI_DRIVER merge order**: currently "first encountered always wins", which may not be the optimal priority

---

## 5. v0.37 newly added patterns (from a digital ASIC flow pilot)

### 6. DRT_ZERO_NET — OpenROAD zero_ Ground Net Error

**Symptom**: OpenROAD TritonRoute reports `DRT-0305: Net zero_ of signal type GROUND is not routable`.

**Root cause**: after Yosys synthesis an internal constant-0 wire named `zero_` is retained; OpenROAD recognises it as a GROUND-type net and refuses to route it through the signal router.

**Fix (Yosys side)**:
```tcl
synth -top MODULE -flatten     # flatten removes hierarchical zero_ nets
hilomap -hicell TIEHI Y -locell TIELO Y   # replace constants with PDK tie cells
```

**Fix (OpenROAD side)**:
```tcl
# If zero_ still appears, mark it as a special net
foreach net [$block_obj getNets] {
    if {[$net getName] == "zero_"} { $net setSpecial }
}
```

**Success rate**: 100% (two-step combination).

### 7. SITE_NOT_FOUND — Wrong Floorplan Site Name

**Symptom**: OpenROAD reports `IFP-0018: Unable to find site: FreeSite`.

**Root cause**: each PDK uses a different site name. Must be read from the cell LEF.

**Fix**: `grep "^SITE " cell_macro.lef` to obtain the correct name (e.g. GF180: `GF018hv5v_mcu_sc7`, SKY130: `unithd`, custom vendor PDK: `unit`).

### 8. MISSING_TRACKS — No Routing Track Definition

**Symptom**: OpenROAD pin placement reports `PPL-0021: Horizontal routing tracks not found`.

**Root cause**: some tech LEFs do not contain track definitions.

**Fix**: manually add `make_tracks`:
```tcl
make_tracks MET1 -x_offset 0.28 -x_pitch 0.56 -y_offset 0.28 -y_pitch 0.56
```
The pitch value is read from the `PITCH` field in the tech LEF.

### 9. SV_LOCAL_DECL — SystemVerilog Local Declaration in Block

**Symptom**: Yosys reports `Local declaration in unnamed block is only supported in SystemVerilog mode!`

**Root cause**: RTL uses local variable declarations like `integer i;` or `logic [7:0] temp;` inside always blocks.

**Fix**: add `-sv` flag: `read_verilog -sv file.v`

**Success rate**: 100%. The MCP eda_synth tool's `sv_mode` parameter already defaults to true.

## 6. Suggested improvements

1. Add INTERFACE_PORT pattern: auto-flatten SV interface to flat ports
2. Add "intent detection" for MULTI_DRIVER: judge the correct merge priority based on FSM state context
3. Add retry mechanism: auto-resynth after fix to confirm the fix worked
4. Log fix history to pipeline.jsonl for traceability
5. **Auto-detect PDK site name, metal layer names, tie cell names** (avoid manual LEF lookup)
6. **Templated Yosys recipes**: auto-pick `-flatten` + `hilomap` parameters per PDK

---

## 7. Quartus / FPGA silent-failure class (2026-04-21, observed on FPGA BIST)

Quartus can return `Quartus Prime Full Compilation was successful. 0 errors` while
still having silently dropped critical init blocks. The only evidence is buried
in the `.map.rpt`. This class of bug passes simulation but breaks hardware.

### Smoking-gun patterns in `.map.rpt`

| Pattern | Meaning | Typical cause |
|---|---|---|
| `Stuck at GND due to stuck port data_in` | register's input optimized to constant 0 | ROM/LUT init dropped; see below |
| `Stuck at VCC ...` | optimized to constant 1 | similar — upstream logic folded |
| `Warning (10030): has no driver or initial value` | array declared but no valid drive found | `initial begin` contents not synthesizable |
| `Warning (10855): initial value for variable <name> should be constant` | an `initial` assignment was rejected | loop-based ROM init is the usual culprit |
| `Lost fanout` | register output never consumed | symptom, not root cause — trace upstream |

### Root cause: `initial begin ... for (integer i=...) mem[i] = ...`

```verilog
// BROKEN on Quartus MAX10 (silent — only warnings, no errors):
reg [7:0] rom [0:31];
integer i;
initial begin
    for (i = 0; i < 32; i = i + 1) rom[i] = 8'h00;
    rom[0] = 8'h70;
    rom[3] = 8'h3D;
end
```

### Fix A — combinational case (always synthesizable)

```verilog
reg [7:0] rom_data;
always @(*) begin
    case (idx)
        5'd0:   rom_data = 8'h70;
        5'd3:   rom_data = 8'h3D;
        default: rom_data = 8'h00;
    endcase
end
```

### Fix B — `$readmemh` with external file

```verilog
reg [7:0] rom [0:31];
initial $readmemh("rom.hex", rom);
```

### Automation

- **Post-synth**: run `programs/quartus_map_audit.py <design>.map.rpt`.
  Any hit → FAIL the synth-doctor gate even when Quartus itself returned success.
- **Pre-synth lint**: run `programs/rom_init_lint.py <rtl-files>`.
  Any hit → block the build before wasting compile time.

### Why this matters

On one FPGA BIST deployment (DE10-Lite / MAX10), a master's ROM used
the for-loop init pattern. Every byte sent was `0x00` on hardware; simulation
was clean. ~hours of misdirected probe-level debug before checking `.map.rpt`.

**Reference**: LL memory `feedback_quartus_init_for_loop.md` +
`feedback_fpga_debug_order.md`.
