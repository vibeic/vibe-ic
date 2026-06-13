---
name: analog-hw-testbench-gen
description: Generate FPGA RTL for hardware-in-the-loop analog testing — digital stimulus controller + ADC readback + scope trigger. Use when verifying analog blocks on real hardware, "generate hw testbench", "FPGA analog test", or at the hardware verification phase.
---

# Analog HW Testbench Gen

Generates FPGA Verilog for exercising an external analog circuit on a breadboard or test PCB. The FPGA controls enable/trim/bias, generates stimulus, reads the MAX10 internal ADC, and triggers the oscilloscope.

## When to use

- After `analog-sizing-loop` converges in SPICE (hardware verification phase)
- When the user says "test the LDO on hardware", "generate FPGA analog test"
- Step A9 of the analog track (hardware verification sub-step)

## Inputs

1. `analog/<block>/spec.json` — performance specs + pin interface
2. `analog/<block>/sizing_final.json` — converged device sizes (for BOM reference)
3. PDK / target FPGA board (default: DE10-Lite MAX10)

## Workflow

1. Parse spec.json for interface signals (enable, trim bits, analog in/out)
2. Map interface to FPGA GPIO pins (DE10-Lite Arduino header or GPIO)
3. Generate stimulus controller:
   - Enable sequencer: timed enable/disable for POR testing
   - Trim sweep: iterate all trim codes for calibration
   - Load step: toggle a MOSFET load via GPIO for transient testing
4. Generate ADC readback module:
   - MAX10 internal ADC (12-bit, up to 17 channels on DE10-Lite)
   - Continuous sampling with averaging (configurable window)
   - Threshold comparator for pass/fail LED indication
5. Generate scope trigger output:
   - Pulse on GPIO before each stimulus event
   - Configurable pre-trigger delay
6. Generate top-level wrapper with pin assignments (.qsf)
7. Generate Quartus project file (.qpf / .qsf)

## Output format

- `analog/<block>/hw_test/<block>_hw_tb.v` — stimulus + readback RTL
- `analog/<block>/hw_test/<block>_hw_tb_top.v` — top-level with pin assignments
- `analog/<block>/hw_test/<block>_hw_tb.qpf` — Quartus project
- `analog/<block>/hw_test/pin_assignments.qsf` — FPGA pin mapping
- `analog/<block>/hw_test/README.md` — breadboard wiring guide with component BOM

## DE10-Lite MAX10 ADC usage

```verilog
// MAX10 internal ADC — directly instantiable
altera_adc_control u_adc (
    .clk       (clk_50mhz),
    .rst       (rst),
    .channel   (5'd0),      // ADC channel 0-16
    .start     (adc_start),
    .done      (adc_done),
    .data      (adc_data)   // 12-bit result
);
```

## Do not

- Do not generate testbenches that require commercial FPGA IP (use only free Quartus Lite primitives)
- Do not assume specific breadboard wiring — always generate a wiring guide
- DE10-Lite board budget (36 GPIO + 10 Arduino header = 46 external-I/O pins)
  and pin double-assignment (board short) are **enforced by
  `programs/analog_hw_tb_de10lite_budget_check.py`** — run it on the emitted
  `.qsf`:

  ```bash
  python3 programs/analog_hw_tb_de10lite_budget_check.py \
      analog/<block>/hw_test/pin_assignments.qsf --json
  ```
  Exit 0 = PASS, 1 = FAIL (>46 GPIO_0+Arduino pins, or a pin shorted to two
  signals), 2 = QSF missing or not a DE10-Lite (MAX10 10M50DAF484C7G) board
  (out of scope — cannot judge). The check only fires on DE10-Lite QSFs.
  (Full-board physical-pin-map validation — HEX/VGA/SDRAM/G-sensor pins — is
  still your judgment: the program intentionally does not flag "unknown" pins
  to avoid false-firing on legitimate peripheral assignments.)

## Handoff

- `.v` + `.qpf` → `eda_fpga_compile` → `eda_fpga_program`
- After programming → `analog-hw-measure` for scope + ADC data collection
- Wiring guide → user builds/adjusts breadboard circuit

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/analog-hw-testbench-gen/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
