---
name: analog-hw-measure
description: Execute hardware measurements on analog blocks via scope capture + FPGA ADC read. Use when running hardware-in-the-loop verification, "measure analog", "scope capture", "read ADC", or during analog hardware tuning.
---

# Analog HW Measure

Drives the measurement instruments (oscilloscope + FPGA ADC) to capture real analog block behavior, then parses the results into a structured measurement report comparable to SPICE simulation output.

## When to use

- After `analog-hw-testbench-gen` has programmed the FPGA
- When the user says "measure the LDO output", "capture scope waveform"
- During `analog-hw-tuning-loop` iterations

## Inputs

1. `analog/<block>/spec.json` — specs with min/max limits
2. `analog/<block>/hw_test/pin_assignments.qsf` — which scope channel maps to which signal
3. Scope connection info (default: <host> lab at <lan-ip>)
4. FPGA ADC channel mapping

## MCP tools used

| Tool | Purpose |
|------|---------|
| `device_scope_capture` | Capture transient waveform (CSV: time, voltage) |
| `device_scope_periodic_pulse_check` | Measure frequency, duty cycle, amplitude |
| `eda_fpga_adc_read` | Read MAX10 ADC for DC voltage (when available) |
| `device_camera_led_diff` | Capture LED pass/fail indication |

## Measurement types per block

| Block type | Key measurements | Instrument |
|-----------|-----------------|------------|
| LDO | Vout DC, load regulation, PSRR, transient response | ADC (DC) + Scope (transient) |
| Oscillator | Frequency, duty cycle, jitter, startup time | Scope (periodic) |
| POR | Trip voltage, hysteresis, release delay | Scope (single-shot ramp) |
| Bandgap | Vref DC, temperature coefficient | ADC (DC, sweep temp manually) |
| Comparator | Propagation delay, offset, hysteresis | Scope (transient) |

## Workflow

1. Verify FPGA is programmed and scope is connected
2. For each spec in spec.json:
   a. Configure scope timebase and trigger (via stimulus controller)
   b. Trigger measurement sequence on FPGA
   c. Capture data via appropriate MCP tool
   d. Parse captured data → extract metric
   e. Compare against spec limits → PASS/FAIL
3. Aggregate all measurements into report

## Waveform parsing

The DC/rise/settling/overshoot/freq/jitter math below is FIXED and
deterministic — do NOT re-derive it by hand each run. Once you have a
captured scope CSV (`time,voltage`), invoke the program so the numbers come
out identically every time:

```bash
python3 programs/scope_waveform_metrics.py <scope_csv> \
    [--spec analog/<block>/spec.json] [--json analog/<block>/hw_measurements.json]
```

It emits `{dc_level, rise_time, settling_time, overshoot, freq, jitter}` and,
when a spec JSON with per-metric `min`/`max` is given, a per-spec
`PASS`/`FAIL` (a metric that cannot be computed grades `SKIP`, never a false
`FAIL`). Exit 0 = extracted / all gradeable specs PASS, 1 = a spec FAILed,
2 = IO/parse error. The program degrades gracefully: a capture shorter than
`--min-samples` (default 8), with no detectable edge, or non-periodic reports
the affected metric as `null` + a MISSING/SKIP note instead of guessing.

The frozen formulas it implements (kept here for reference / review only):
- **DC level**: mean of last 20% of capture window
- **Rise time**: 10%-90% transition time
- **Settling time**: time to stay within ±2% of final value
- **Overshoot**: (peak - final) / final × 100%
- **Frequency**: FFT peak or zero-crossing period measurement (the program
  uses the deterministic mean-crossing-period path)
- **Jitter**: std dev of period over N cycles

**AI judgment stays with you** — choosing the right instrument per block
(scope transient vs ADC DC vs periodic-pulse), setting timebase/trigger,
deciding when a capture is trustworthy, and interpreting a `SKIP`/MISSING
metric (re-capture vs accept) are NOT delegated to the program. The program
only freezes the arithmetic on a capture you already judged good.

## Output format

### `analog/<block>/hw_measurements.json`
```json
{
  "block_name": "ldo_1v8",
  "timestamp": "2026-04-29T14:30:00Z",
  "measurements": {
    "vout_dc": {"value": 1.803, "unit": "V", "spec_min": 1.75, "spec_max": 1.85, "status": "PASS"},
    "load_reg": {"value": 0.5, "unit": "%", "spec_max": 2.0, "status": "PASS"},
    "settling_time": {"value": 12.3, "unit": "us", "spec_max": 50, "status": "PASS"}
  },
  "scope_files": ["analog/ldo_1v8/hw_test/scope_transient.csv"],
  "all_pass": true
}
```

## Do not

- Do not assume scope is always available — check connection first and report gracefully if offline
- Do not overwrite previous measurement files — timestamp or version them
- Do not interpret ADC readings without calibration (MAX10 ADC has ±2 LSB offset)

## Handoff

- `hw_measurements.json` → `analog-hw-tuning-loop` for three-way comparison
- Scope CSV files → `scope_response_byte_decode_check` (if protocol testing)
- If any measurement FAIL → report to tuning loop for sizing adjustment

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/analog-hw-measure/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
