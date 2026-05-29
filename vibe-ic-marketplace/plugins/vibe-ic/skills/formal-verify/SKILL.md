---
name: formal-verify
description: Run formal property verification (FPV) on RTL by driving model-checkers such as SymbiYosys, Jasper, or VC Formal. Use when the user says "prove this", "formal verify", "model check", "run sby", or has SVA properties from assertion-gen that need to be proven or bounded.
---

# Formal Verify

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt.
> Programs first; AI is the backstop on cex narrative.

`assertion-gen` writes the properties; this skill is the **runner**
that dispatches them to a model-checker and interprets the results.
Without a runner, SVA files are just documentation.

## Mandatory Deterministic Preflight

```bash
# MCP tool call — drives SymbiYosys / Jasper / VC Formal:
eda_formal({
  rtl_files: ["<dut>.v"],
  sva_files: ["<assertions>.sva"],
  top_module: "<top>",
  mode: "prove",       // or "bmc" with --bmc-depth N
})
```

The tool returns `property_count`, `proven`, `failed`, plus
`counterexample_paths[]` when failures appear. **Treat the JSON output
as ground truth.** When a property is FAILED, narrate the CEX trace;
when UNDETERMINED at the bound, recommend deeper BMC. Never claim a
property "obviously holds" without the tool's PROVEN verdict.

## When to use

- Control-dominated logic (arbiters, FIFOs, protocol adapters, CDC samplers)
- After `/assertion-gen` produces properties for a module
- Regression: re-prove after any RTL change to a formally-verified block
- Safety-critical paths where simulation coverage is insufficient

## Verification Modes

| Mode | What it proves | When to use | Limitation |
|------|---------------|-------------|-----------|
| **k-induction** (`mode prove`) | Property holds for ALL reachable states | Small modules (<100 FFs, no deep counters) | Fails on large state spaces |
| **BMC** (`mode bmc`) | No bug exists within N cycles | Large/complex modules | Not a complete proof |
| **cover** (`mode cover`) | A given state IS reachable | Checking liveness, debug | — |

## Why Large Modules Fail k-induction

k-induction requires depth ≥ longest counter/timer path. When a module has:
- **Deep counters** (100-1650 cycles): k must be ≥ counter max value
- **Large memory arrays** (47 bytes = 376 bits): state space explodes
- **Complex FSMs** (10+ states with nested cases): solver can't prune

This is the **state explosion problem** — fundamental to model checking.

### Concrete example from <benchmark>:

| Module | States | FFs | Memory | Timer depth | k-induction feasible? |
|--------|--------|-----|--------|-------------|----------------------|
| timer_block | 3 | 4 | 0 | 0 | ✅ Yes (k=20) |
| crc8_engine | 2 | 3 | 0 | 0 | ✅ Yes (k=20) |
| aid_transceiver | 8 | ~15 | 0 | 135 cycles | ❌ Needs k≥135 |
| aid_protocol | 9 | ~10 | 0 | 110 cycles | ❌ Needs k≥110 |
| cmd_processor | 10 | 29 | 336 bits | N/A | ❌ State space too large |
| otp_controller | 7 | ~20 | 376 bits | 1650 cycles | ❌ Needs k≥1650 |

## Solutions for Complex Modules

### Solution A: BMC-Only (Immediate)

Don't pursue complete proof. BMC to depth 50-200 catches most bugs:

```
[options]
mode bmc
depth 50
```

**<benchmark> result**: All 4 complex modules pass BMC at depth 50.

### Solution B: Abstract Timers (`ifdef FORMAL`)

Replace long counters with short ones for formal:

```systemverilog
`ifdef FORMAL
  localparam logic [11:0] EPROG_CYCLES = 4;  // formal: 4 cycles
`else
  localparam logic [11:0] EPROG_CYCLES = 1650;  // real: 1650 cycles
`endif
```

Logic structure unchanged, but solver finishes in seconds.

Reference: [Tom Verbeure — Under the Hood of Formal Verification](https://tomverbeure.github.io/rtl/2019/01/04/Under-the-Hood-of-Formal-Verification.html)

### Solution C: Assume-Constrain Decomposition

Use `assume()` to restrict inputs to legal behavior:

```systemverilog
// cmd_processor: break only in valid states
always @(posedge clk)
  assume (!break_detected || state_r == IDLE || state_r == COMM_ERROR);

// byte_rx_valid never two consecutive cycles
always @(posedge clk)
  if (!init) assume (!byte_rx_valid || !$past(byte_rx_valid));
```

Massively reduces state space — solver ignores unreachable scenarios.

Reference: [ZipCPU — Swapping Assumptions and Assertions](https://zipcpu.com/formal/2018/12/18/skynet.html)

### Solution D: Helper Invariants

Help solver know which state combinations are impossible:

```systemverilog
// otp_controller: prog_timer nonzero only in PROG states
always @(posedge clk)
  if (!init && rst_n)
    assert (prog_timer_r != 0 |-> 
      (prog_state_r == PROG_ACTIVE || prog_state_r == PROG_WAIT));
```

Reference: [ZipCPU — An Exercise in Formal Induction](https://zipcpu.com/blog/2018/03/10/induction-exercise.html)

### Solution E: Per-Command Task Splitting

For `cmd_processor` with 8 commands — split into 8 formal tasks:

```
[tasks]
verify_cmd_id
verify_cmd_set_state
verify_cmd_get_state
...

[options]
verify_cmd_id: mode bmc
verify_cmd_id: depth 30
```

Each task assumes `cmd_byte_r` is one specific value. 8 small problems >> 1 huge problem.

Reference: [SymbiYosys Tasks](https://symbiyosys.readthedocs.io/en/latest/reference.html)

### Solution F: Memory Abstraction

For `otp_controller`'s 47-byte array:
- **Memory slicing**: only verify 3-4 representative bytes
- **Array theory**: SMT solver uses `(Array (_ BitVec 6) (_ BitVec 8))` — more efficient than 47×8 bits

## Inputs to gather

1. RTL module under verification
2. SVA properties (from `/assertion-gen` or hand-written)
3. Target engine: SymbiYosys (open), Jasper (Cadence), VC Formal (Synopsys)
4. Bound (for BMC) or depth (for k-induction)
5. Constraints / assumptions (`assume` properties)

## Workflow

1. **Classify module complexity** — choose k-induction (simple) or BMC (complex)
2. **Generate assertions** — via `/assertion-gen` or manual
3. **Write `.sby` config** with appropriate mode and depth
4. **Run engine** — `sby -f module.sby`
5. **Triage results**:
   - PASS: record bound/depth
   - FAIL: capture CEX trace, map to RTL line, propose fix → `/rtl-repair`
   - TIMEOUT: apply solutions B-F above
6. **Regression harness**: re-run after any RTL change

## Output format

- `formal/<module>.sby`
- `formal/<module>_formal.sv` — assertions
- `formal/<module>_report.md` with per-property status table
- Counterexample VCDs (if FAIL)

## Technical basis

SymbiYosys is the canonical open-source FPV driver on top of Yosys. K-induction and IC3/PDR are the dominant engines. SMT solvers (Yices, Z3) handle the underlying satisfiability.

References:
- [SymbiYosys Documentation](https://symbiyosys.readthedocs.io/)
- [ZipCPU Formal Verification Blog Series](https://zipcpu.com/formal/formal.html)
- [Model Checking and State Explosion (Clarke et al.)](https://link.springer.com/chapter/10.1007/978-3-642-35746-6_1)
- [Formal Verification with SymbiYosys (Clifford Wolf)](https://slideplayer.com/slide/11950984/)
- [HIVE: Scalable HW-FW Co-Verification via Decomposition](https://arxiv.org/html/2309.08002v2)

## Handoff

- CEX → `/rtl-repair`
- Uncovered states → `/coverage-closure`
- New SVA needed → `/assertion-gen`

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/formal-verify/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
