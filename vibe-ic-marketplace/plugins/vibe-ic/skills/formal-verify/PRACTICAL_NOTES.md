# Formal Verify — Practical Notes

**Added**: 2026-04-07 from a digital formal verification pilot (10/10 modules verified)
**Updated**: 2026-04-07 with deep analysis of complex module strategies

---

## Environment Setup

```bash
export PATH=/foss/tools/yosys/bin:/foss/tools/bin:$PATH
sby -f design.sby
```

## Available Solvers

| Solver | Path | Status | Best for |
|--------|------|--------|----------|
| yices | `/foss/tools/yosys/bin/yices` | ✅ Recommended | General use, fast |
| z3 | — | ❌ Not in container | Would be better for large designs |
| boolector | — | ❌ | Bit-vector heavy designs |

---

## SVA → Yosys Assertion Conversion

Yosys does NOT support full SVA syntax. Conversion rules:

### Property/Implication → $past() pattern

```systemverilog
// ❌ SVA (won't compile in Yosys):
property p; @(posedge clk) A |=> B; endproperty
assert property (p);

// ✅ Yosys-compatible:
reg init = 1;
always @(posedge clk) init <= 0;
always @(posedge clk) begin
  if (!init && $past(A))
    a_name: assert (B);
end
```

### Combinational invariant

```systemverilog
// ✅ Yosys-compatible:
always @(*) begin
  a_mutex: assert (!(signal_a && signal_b));
end
```

### Assumption (input constraint)

```systemverilog
// ✅ Yosys-compatible:
always @(posedge clk) begin
  if (!init) assume (!input_a || !$past(input_a));  // no consecutive highs
end
```

---

## Pilot Complete Results: 10/10 Modules

### Simple Modules — k-induction (complete proof)

| Module | Cells | Assertions | Depth | Method | Time |
|--------|-------|-----------|-------|--------|------|
| disconnect_detector | 53 | 4 | 30 | k-induction | <1s |
| crc8_engine | 63 | 3 | 20 | k-induction | <1s |
| gpo_controller | 69 | 4 | 20 | k-induction | <1s |
| wake_generator | 101 | 3 | 20 | k-induction | <1s |
| passthrough_switch | 8 | 3 | 20 | k-induction | <1s |
| timer_block | 223 | 4 | 20 | k-induction | <1s |

### Complex Modules — BMC (bounded proof)

| Module | Cells | Assertions | Depth | Method | Time |
|--------|-------|-----------|-------|--------|------|
| aid_transceiver | 133 | 4 | 50 | BMC | <1s |
| aid_protocol | 171 | 5 | 50 | BMC | <1s |
| cmd_processor | 487 | 5 | 50 | BMC | 1s |
| otp_controller | 1603 | 5 | 50 | BMC | 2s |

**Total: 40 assertions across 10 modules, ALL PASS**

### RTL Bugs Found During Verification

| Module | Bug | Fix |
|--------|-----|-----|
| aid_transceiver | `tx_busy` multi-driver (always_ff + always_comb) | Removed from always_ff reset |
| aid_protocol | 6 combinational signals multi-driven (always_ff + always_comb) | Removed from always_ff reset |

---

## Why Complex Modules Need BMC (Not k-induction)

### Root cause analysis

| Factor | Simple modules | Complex modules |
|--------|---------------|----------------|
| FSM states | 2-4 | 7-10 |
| Flip-flops | 2-4 | 3-29 |
| Memory bits | 0 | 72-376 |
| Timer max depth | None | 100-1650 cycles |
| Sub-system coupling | Independent | Multi-module |

**Core bottleneck**: k-induction depth must ≥ longest counter path. `otp_controller` has a 1650-cycle timer → needs k ≥ 1650 → SMT solver computation explodes exponentially.

### Module-specific complexity

**cmd_processor** (most complex):
- 10 FSM states with 8 nested command handlers
- 336 bits memory (10-byte data + 32-byte response buffer)
- Coupled to OTP and CRC sub-systems

**aid_protocol** (timing-sensitive):
- 9 FSM states with byte-level shift registers
- 8-bit inter-byte timer counting to 110 → k ≥ 110 needed

**aid_transceiver** (bit-level timing):
- 8 FSM states with 12+ timing thresholds (5-135 clocks)
- Double-register synchronizer + edge detection

**otp_controller** (memory-heavy):
- 47-byte memory array = 376 bits state space
- 12-bit programming timer (1650 cycles)
- Lock bit logic across 3 address regions

---

## Advanced Strategies for Upgrading BMC → Full Proof

### Strategy 1: Abstract Timers (`ifdef FORMAL`)

```systemverilog
`ifdef FORMAL
  localparam logic [11:0] EPROG_CYCLES = 4;
`else
  localparam logic [11:0] EPROG_CYCLES = 1650;
`endif
```

Shrinks counter domain, same logic structure. Use simulation for real timing values.

**Applicable to**: aid_transceiver, otp_controller
**Expected result**: k-induction becomes feasible at depth 20-30

### Strategy 2: Assume-Constrain Decomposition

```systemverilog
// cmd_processor: constrain input behavior
always @(posedge clk)
  assume (!break_detected || state_r == IDLE || state_r == COMM_ERROR || state_r == WAITING_FOR_BREAK);

always @(posedge clk)
  if (!init) assume (!byte_rx_valid || !$past(byte_rx_valid));
```

**Applicable to**: cmd_processor, aid_protocol
**Expected result**: 10x reduction in solver time

Reference: [ZipCPU — Swapping Assumptions and Assertions](https://zipcpu.com/formal/2018/12/18/skynet.html)

### Strategy 3: Helper Invariants

```systemverilog
// otp_controller: timer only active in programming states
always @(posedge clk)
  if (!init && rst_n)
    assert (prog_timer_r != 0 |->
      (prog_state_r == PROG_ACTIVE || prog_state_r == PROG_WAIT));
```

Helps solver prune unreachable state combinations.

Reference: [ZipCPU — An Exercise in Formal Induction](https://zipcpu.com/blog/2018/03/10/induction-exercise.html)

### Strategy 4: Per-Command Task Splitting

```
[tasks]
verify_cmd_id
verify_cmd_set_state
verify_cmd_get_state
verify_cmd_dev_info
verify_cmd_imsn
verify_cmd_asn
verify_cmd_program_otp
verify_cmd_otp_status
```

Each task assumes one command value. 8 small problems >> 1 huge problem.

Reference: [SymbiYosys Tasks](https://symbiyosys.readthedocs.io/en/latest/reference.html)

### Strategy 5: Memory Abstraction

For otp_controller's 47-byte array:
- Verify 3-4 representative bytes (1 per address region)
- Use `assume` to constrain addr to verified range
- SMT array theory handles remaining addresses symbolically

### Priority Roadmap

| Priority | Strategy | Modules | Upgrades BMC to... |
|----------|----------|---------|-------------------|
| 1 | Abstract timers | transceiver, otp | k-induction (depth 20) |
| 2 | Assume-constrain | cmd_proc, protocol | k-induction (depth 30) |
| 3 | Per-command split | cmd_proc | 8× k-induction proofs |
| 4 | Helper invariants | All 4 | Strengthen existing proofs |
| 5 | Memory slicing | otp | k-induction (depth 30) |

---

## .sby Config Templates

### Simple module (k-induction)

```
[tasks]
prove
[options]
prove: mode prove
prove: depth 20
[engines]
smtbmc yices
[script]
read -formal module.sv
read -sv module_formal.sv
hierarchy -top module
prep -top module
[files]
module.sv
module_formal.sv
```

### Complex module (BMC)

```
[tasks]
bmc
[options]
bmc: mode bmc
bmc: depth 50
[engines]
smtbmc yices
[script]
read -formal module.sv
read -sv module_formal.sv
hierarchy -top module
prep -top module
[files]
module.sv
module_formal.sv
```

### Multi-task verification

```
[tasks]
bmc
prove

[options]
bmc: mode bmc
bmc: depth 100
prove: mode prove
prove: depth 30

[engines]
smtbmc yices
```

---

## References

- [SymbiYosys Documentation](https://symbiyosys.readthedocs.io/)
- [SymbiYosys Formal Extensions to Verilog](https://symbiyosys.readthedocs.io/en/latest/verilog.html)
- [ZipCPU Formal Verification Blog Series](https://zipcpu.com/formal/formal.html)
- [ZipCPU — Formal Verification Plan for New IP](https://zipcpu.com/formal/2020/07/21/formal-plan.html)
- [ZipCPU — Aggregating Verified Modules](https://zipcpu.com/formal/2018/04/23/invariant.html)
- [Under the Hood of Formal Verification (Tom Verbeure)](https://tomverbeure.github.io/rtl/2019/01/04/Under-the-Hood-of-Formal-Verification.html)
- [Model Checking and State Explosion (Clarke et al.)](https://link.springer.com/chapter/10.1007/978-3-642-35746-6_1)
- [HIVE: Scalable HW-FW Co-Verification](https://arxiv.org/html/2309.08002v2)
- [Formal Verification with SymbiYosys (Clifford Wolf)](https://slideplayer.com/slide/11950984/)
