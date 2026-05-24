---
name: protocol-turnaround-audit
description: "Semantic RTL audit for half-duplex bus turnaround violations. For each TX-start-class signal rising-edge assignment, walk the state-machine graph backward to find the RX-completion trigger. Compute worst-case path length in cycles and compare against (delimiter_max - delimiter_detect_threshold) + t_turnaround_min from L2 timing. ERROR if path too short. Triggers when: 'turnaround audit', 'check RX→TX gap', 'half-duplex turnaround', or after a hardware FAIL where tester sees frame overlap."
---

# protocol-turnaround-audit — R2 semantic audit skill

Semantic RTL audit that catches the half-duplex bus turnaround violation at the RTL analysis stage, before simulation or hardware.

## Problem

When a device dispatches its response FSM on detection-of-frame-delimiter without inserting an explicit settle delay, the first device-driven assertion merges with the still-active host-driven delimiter assertion. The receiver sees one wide assertion event, re-classifies it as another delimiter, and the entire response frame layout shifts.

This is structurally invisible to lint, synthesis, and most testbenches — it only manifests when RX→TX transition occurs within `(delimiter_max_duration - delimiter_detect_threshold) + t_turnaround_min` of the trigger event.

## When to Use

1. Before first simulation of any half-duplex protocol IC
2. After spec-to-rtl generates dispatcher RTL
3. After a hardware FAIL where tester logs show frame overlap or shifted bytes
4. Whenever the user says "turnaround audit", "check RX→TX gap", "half-duplex turnaround"

## Algorithm

### Step 1 — Identify TX-start signals

Grep all RTL files for signal assignments matching:
```
/tx.?start|tx.?req|resp.?start|reply.?start|drv.?en/i
```

### Step 2 — Identify RX-completion triggers

For each TX-start signal, trace backward through the state machine to find the triggering condition. Look for signals matching:
```
/rx.?done|.?delim.?seen|.?eof|cmd.?valid|frame.?complete|trailing.?(br|delim)/i
```

### Step 3 — Compute path length

Count the minimum number of state transitions (clock cycles) between the RX-completion trigger and the TX-start assertion. This is the worst-case turnaround budget.

### Step 4 — Compare against L2 timing

Extract from L2 timing JSON:
- `delimiter_max_duration` (or equivalent: `BR_max`, `break_max`, etc.)
- `delimiter_detect_threshold` (when the RX decoder fires the trigger)
- `t_turnaround_min` (or `tSRS`, `tResponseDelay`, `tBusGuard`)

Compute minimum safe budget:
```
min_safe_cycles = ceil((delimiter_max - delimiter_detect_threshold + t_turnaround_min) / clock_period)
```

If `path_length < min_safe_cycles` → **ERROR** with file:line.

## Required Inputs

| Input | Source | Required |
|-------|--------|----------|
| RTL files | `rtl/` directory | Yes |
| L2 timing JSON | `L2_FRS.json` or `L8_TIMING_WAVEFORM.json` | Yes |
| Clock frequency | L2 or design config | Yes |

## Output

Report listing each TX-start signal, its RX trigger, path length in cycles, minimum safe budget, and PASS/ERROR verdict.

```
[protocol-turnaround-audit]
  example_chip_ctrl.v:142  tx_start ← trailing_br_seen
    Path length: 3 cycles
    Min safe budget: 200 cycles (80us @ 2.5MHz)
    Verdict: ERROR — turnaround 3 cycles < 200 cycles minimum

  uart_tx.v:88  tx_req ← rx_frame_complete
    Path length: 50 cycles
    Min safe budget: 10 cycles (100ns @ 100MHz)
    Verdict: PASS — turnaround 50 cycles ≥ 10 cycles minimum
```

## Confidence

~70-85% on the RX→TX turnaround bug class. Depends on correctly modeling that the delimiter-detection trigger fires partway through an active delimiter assertion, not at its end. If the audit adds `(delimiter_max - delimiter_detect_threshold)` slack to the budget, it catches the v101 failure mode.

## Limitations

- State-machine extraction uses heuristic `case(state)` parsing, not a full formal model
- Cannot catch turnaround violations hidden behind parameterized generate blocks
- Requires naming conventions to match the regex catalogs

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/protocol-turnaround-audit/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
