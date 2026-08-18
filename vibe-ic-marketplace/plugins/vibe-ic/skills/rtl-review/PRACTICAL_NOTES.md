# RTL Review — Practical Notes from Pilot Experience

**Added**: 2026-04-07 from actual Verilator + Yosys runs

## Common Issues Found in AI-Generated RTL

### 1. Latch Inference (most common blocker)
AI-generated `always_comb` blocks often miss default assignments for signals that are only assigned in specific case branches.

**Pattern**:
```systemverilog
always_comb begin
  // AI forgets to add: signal_x = default_value;
  case (state)
    STATE_A: signal_x = something;  // only here
    // other states don't assign signal_x → LATCH!
  endcase
end
```

**Fix**: Add default assignments for ALL outputs at the top of every `always_comb`.

### 2. inout / Tri-State Ports
AI generates clean `inout` tri-state logic, but Yosys optimizes it away because it can't see external connections.

**Fix**: Create a synthesis wrapper that splits `inout` into `_i`, `_o`, `_oe`. Keep the original top for simulation.

### 3. Width Mismatches
AI frequently uses `int` parameters (32-bit) assigned to narrow registers (15-bit), or declares 1-bit signals used as counters.

**Detection**: `verilator --lint-only -Wall` catches all of these as WIDTHTRUNC warnings.

### 4. Unpacked Array Parameters
```systemverilog
localparam logic [14:0] VALUES[9] = '{...};  // iverilog can't handle this
```
**Fix**: Replace with individual `localparam` + lookup function.

### 5. Mid-Block Variable Declarations
iverilog doesn't support SystemVerilog mid-block declarations. Move all `logic`/`int`/`time` declarations to module scope.

## Tool-Specific Notes

| Tool | SV Support | Best For |
|------|-----------|----------|
| Verilator | Excellent | Lint, simulation |
| Yosys | Good (with `-sv`) | Synthesis |
| iverilog | Poor for SV | Simple Verilog only |
| SymbiYosys | Partial | Formal (needs rewritten assertions) |

## Cross-Module Interface Checks (from protocol-tester FPGA debug 2026-04-18)

### 6. Gray-Code / Binary Encoding Mismatch
When replacing a vendor module with AI-generated RTL, the most dangerous bug is **encoding mismatch**: your module outputs binary counter values but the downstream module compares against gray-code patterns.

**Detection**: Search for counter comparison patterns in consuming modules:
- `signal == 6'b11_0000` with comment `// 32` → gray-code (binary 32 = `6'b10_0000`)
- `signal == 6'd32` → binary
- If producer increments `+1` (binary) but consumer compares gray-code patterns → **MISMATCH**

**Impact**: Silent total failure. No compile error. All comparisons fail.

**Fix**: Output gray-code conversion: `assign out = bin ^ (bin >> 1);`

### 7. TX Data Content Verification
Every TX data loading path must match the protocol spec exactly:
- CRC loading: check bit-reversal requirement
- Status register byte: verify bit field positions match spec
- Command bytes: verify hex values match response table
- Data masking: check if OTP/ROM mask is applied (e.g., `data & mask_value`)

**Common AI mistakes**:
- CRC loaded without bit-reversal → CRC fail on receiver
- OVP/OCP bit positions wrong → status byte invalid
- Status byte uses wrong source registers → protocol violation

### 8. Counter Approach Audit (TX vs RX)
- **TX PHY counters**: Must be time-based (count clocks, not bus state)
- **RX PHY counters**: Must be bus-state based (count while bus LOW/HIGH)
- **TX low counter**: Gate on `tx_data_enable` only (not bus read-back)
- **TX high counter**: Gate on `low_cnt_full | ibt_enable` (sequential after low)
- **Counter hold**: When target reached, hold value (don't keep incrementing)

## Scoring Calibration

From pilot experience:
- AI-generated RTL with 0 synthesis errors but 71 lint warnings = **Score 6/10**
- Same RTL after fixing latches + multi-drivers = **Score 7/10**
- Production-ready would need unused signal cleanup + width fixes = **Score 8/10**
- Cross-module encoding mismatch → **automatic Score 3/10** (protocol-breaking)

---

## ROM/LUT init pattern (2026-04-21, observed FPGA BIST silent-fail)

Review rule (blocking): any reg-array memory initialized inside an `initial`
block via a `for`-loop with an `integer` index is a **Quartus-unsafe pattern**
and must be rejected during RTL review for any design that will target an
Intel/Altera FPGA family.

```verilog
// REJECT ON REVIEW — Quartus MAX10 silently drops this to all-zero:
reg [7:0] rom [0:31];
integer i;
initial begin
    for (i = 0; i < 32; i = i + 1) rom[i] = 8'h00;
    rom[0] = 8'h70;
    // ...
end

// ACCEPT (A) — combinational case:
reg [7:0] rom_data;
always @(*) case (idx)
    5'd0:   rom_data = 8'h70;
    default: rom_data = 8'h00;
endcase

// ACCEPT (B) — $readmemh with external file:
reg [7:0] rom [0:31];
initial $readmemh("rom.hex", rom);
```

### Why blocking

The failure is **silent** — Quartus emits only Warnings (10030) + (10855) in the
`.map.rpt`; `quartus_sh --flow compile` returns success. Simulation passes. The
hardware then behaves as if the ROM is all-zero and typically spends many hours
in probe-level debug before anyone reads the map report.

### Enforcement

- Run `programs/rom_init_lint.py` on any RTL bound for FPGA.
- On any target design that includes a Quartus `.map.rpt`, also run
  `programs/quartus_map_audit.py` — any `Stuck at GND/VCC`, `Warning 10030`,
  or `Warning 10855` hit must fail the review gate.

**Reference**: LL memory `feedback_quartus_init_for_loop.md`.
