---
name: fpga-hps-bridge
description: "Generate HPS (Hard Processor System) integration for DE10-Nano FPGA verification. Replaces UART with direct memory-mapped register access from the ARM Cortex-A9 — approximately 100x faster, no external cables needed. Triggers when: 'HPS bridge', 'memory mapped FPGA', 'no UART', 'faster BIST', 'on-board test', 'HPS test', 'ARM to FPGA', or when UART is too slow for regression/stress testing."
---

# FPGA HPS Bridge Generator

Generate a complete HPS-to-FPGA bridge integration for Cyclone V SoC FPGA verification, enabling the ARM Cortex-A9 to control BIST engines via direct memory-mapped I/O instead of UART.

## Build the bridge from the register map

Implement the Avalon-MM bridge and software register access from the project's
actual register map. Keep byte offsets, widths, reset values, address decoding
and handshake timing consistent between RTL and software. Simulate reads,
writes, byte enables and reset behavior with native HDL tools, then compile
with Quartus for the selected board. Read its timing and fit reports.

The register table below is a worked integration template. Confirm the
project's required map before using it; no retired generator supplies an
authoritative map.

## When to Use

1. **UART is too slow** — Stress testing 10K+ iterations takes hours over UART but seconds via HPS
2. **No external cable available** — HPS talks to FPGA fabric internally, no USB-UART adapter needed
3. **Remote board access** — SSH into DE10-Nano Linux, run tests remotely
4. **Regression testing** — Batch run multiple ICs without cable swapping
5. **Production validation** — Automated test on deployed boards

## When NOT to Use

1. **Initial debugging** — UART provides per-test detail; HPS gives only aggregate results
2. **No Linux on SD card** — HPS requires a bootable Linux image
3. **Board without HPS** — Pure FPGA boards (e.g., DE0-Nano) don't have an ARM processor
4. **First-time setup** — Requires Platform Designer (Qsys) knowledge

## Prerequisites

- **DE10-Nano** (Cyclone V SoC) with Linux SD card booted
- **Intel Quartus Prime 23.1+** with Platform Designer (Qsys)
- **Python 3** on the DE10-Nano Linux
- **Root access** on the DE10-Nano (for `/dev/mem`)
- Existing BIST engine (e.g., `cd4013b_bist_v5.sv`)
- Working UART-based test as a baseline for comparison

## Generated Files

The following files describe the bridge RTL, software access and integration
guide to author for the selected project. Validate them with native simulation
and Quartus.

### 1. `common_rtl/hps_bridge.sv` — Avalon-MM Slave Register Bridge

Parameterized bridge module that maps BIST control/status to 16 registers accessible from HPS Linux via `/dev/mem`. Features:
- Zero-wait-state Avalon-MM slave interface
- Self-clearing control pulses (start_bist, start_loop, cov_reset)
- 6-layer coverage readout including branch coverage
- CHIP_ID and VERSION registers for identification
- Configurable IC identifier via parameters

### 2. `cd4013b_hps_top.sv` — HPS-Enabled FPGA Top Module

Top-level module that instantiates:
- HPS subsystem (Qsys-generated `soc_system`)
- `hps_bridge` (Avalon-MM slave on LW H2F bridge)
- BIST engine (`cd4013b_bist_v5`)
- DUT (`cd4013b`)
- UART TX/RX (backward compatibility)
- Branch coverage tracking logic

Dual-interface: HPS (fast, no cable) OR UART (universal).

### 3. `hps_test.py` — Python Test Script (runs ON DE10-Nano)

7-stage test flow matching the UART version:
1. Bridge connection check (CHIP_ID, VERSION)
2. BIST execution (single run via register write)
3. Results readout (instant register read)
4. Coverage analysis (6-layer including branch)
5. Fail analysis (aggregate; suggests UART for per-test detail)
6. (Skipped in HPS mode)
7. Report generation (JSON + Markdown)

Plus:
- Stress loop via register write (no UART parsing overhead)
- UART result comparison for cross-validation
- Fmax sweep control register

### 4. `HPS_INTEGRATION_GUIDE.md` — Setup Instructions

Step-by-step guide for:
- Setting up Linux on DE10-Nano SD card
- Creating Platform Designer (Qsys) system
- Adding hps_bridge as custom Avalon-MM slave
- Compiling and programming
- Running tests
- Troubleshooting

## Architecture

```
DE10-Nano SoC
+---------------------------------------------------+
|  HPS (ARM Cortex-A9)          |  FPGA Fabric      |
|  +-------------------+       |  +-------------+   |
|  | Linux (Debian)     |       |  |   BIST v5   |   |
|  | +---------------+ |  H2F  |  |   Engine    |   |
|  | | hps_test.py   |-+--LW---+->|             |   |
|  | | (mmap)        | | Bridge |  |  +-------+  |   |
|  | +---------------+ |       |  |  | DUT   |  |   |
|  +-------------------+       |  |  +-------+  |   |
|                               |  +-------------+   |
+---------------------------------------------------+
```

## Register Map

Keep the selected register map identical in `hps_register_map.md`, the RTL
read/write logic and the software constants. Confirm each offset through
native simulation before hardware access.

| Offset | Name | R/W | Description |
|--------|------|-----|-------------|
| 0x00 | CTRL | R/W | start_bist, start_loop, start_fmax, cov_reset |
| 0x04 | STATUS | R | running, done, all_pass, state |
| 0x08 | TEST_NUM | R | Current test number |
| 0x0C | PASS_COUNT | R | Pass count |
| 0x10 | FAIL_COUNT | R | Fail count |
| 0x14 | TOTAL_TESTS | R | Total test count |
| 0x18 | COV_TOGGLE | R | Toggle coverage bitmap |
| 0x1C | COV_STATE | R | State coverage bitmap |
| 0x20 | COV_GROUP | R | Group coverage bitmap |
| 0x24 | COV_BRANCH | R | Branch coverage bitmap |
| 0x28 | LOOP_COUNT | R/W | Stress loop iteration count |
| 0x2C | LOOP_PASS | R | Loop pass iterations |
| 0x30 | LOOP_FAIL | R | Loop fail iterations |
| 0x34 | FMAX_RESULT | R | Fmax sweep result (MHz) |
| 0x38 | CHIP_ID | R | IC identifier constant |
| 0x3C | VERSION | R | BIST version constant |

## Performance Comparison

| Metric | UART | HPS |
|--------|------|-----|
| Single BIST (48 tests) | ~2-5 seconds | ~0.01-0.05 seconds |
| Stress loop (10K iters) | ~30-60 minutes | ~5-15 seconds |
| Coverage layers | 5 | 6 (adds branch) |
| External hardware | USB-UART cable | None |
| Per-test detail | Full (input/output/diff) | Aggregate only |

## Comparison with UART Approach

| Feature | UART (fpga_test_harness) | HPS (fpga-hps-bridge) |
|---------|--------------------------|------------------------|
| Speed | Slow (115200 baud serial) | Fast (memory-mapped AXI) |
| Cable | Required | Not needed |
| Per-test data | Full detail per test | Aggregate pass/fail |
| Debug capability | Excellent (debug trace) | Limited (use UART for debug) |
| Setup complexity | Low (plug in cable) | High (Qsys + Linux) |
| Board support | Any FPGA with GPIO | Cyclone V SoC only |
| Host | Any PC (Win/Mac/Linux) | DE10-Nano Linux (ARM) |
| Coverage | 5 layers | 6 layers (+ branch) |

## Typical Workflow

```
1. Initial development:
   fpga_test_harness (UART)  -->  debug per-test failures

2. Bridge validation:
   hps_test.py --compare-uart test_report_v5_*.json  -->  verify match

3. Regression testing:
   hps_test.py --stress 10000  -->  fast stress test via HPS

4. Production:
   hps_test.py  -->  automated on-board validation
```

## Adapting for Other ICs

The structural adaptation is mechanical — let the generator do it instead of
copy-editing:

Implement the bridge from the selected project register map. Keep RTL/software byte offsets, widths, reset behavior and handshakes aligned, then verify them through native HDL simulation and Quartus.

This re-emits `hps_bridge.sv` (with the new `CHIP_ID_VALUE`), `<ic>_hps_top.sv`
(instantiating the named DUT + BIST), and `hps_test.py` (with the new
`IC_NAME` / `TOTAL_TESTS`) — all with the IDENTICAL 16-register offsets.

Then apply the parts that need engineering judgment (NOT generated):

1. **Update coverage tracking** — adjust `pin_cur` and branch conditions inside
   the BIST engine to your DUT's pins/groups.
2. **Update Qsys** — same Platform Designer system, just point the top-level at
   `<ic>_hps_top`.
3. **Author `HPS_INTEGRATION_GUIDE.md`** — Linux/SD-card + Qsys setup steps.
