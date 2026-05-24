---
name: hold-fix
description: "Post-CTS and post-route hold violation fixing via buffer/delay cell insertion. CTS always introduces hold violations that must be fixed. Use when: 'hold violation', 'hold fix', 'hold slack', 'fix hold', 'negative hold slack', 'post-CTS hold', 'short path padding', or after CTS completes (Step 19)."
---

# Hold Fix — Post-CTS / Post-Route Hold Violation Repair

After CTS, clock insertion delay makes fast data paths arrive too early at capture flops, causing hold violations. This is expected and must be fixed by inserting buffers or delay cells on short paths. Hold fixing is iterative: fix -> check -> re-fix until all hold slack >= 0 at the fast (FF) corner.

## When to use

- **After CTS (Step 19)**: CTS introduces clock insertion delay that creates hold violations on short paths. This is the primary trigger.
- **After routing**: parasitics change path delays, potentially creating new hold violations.
- **After ECO**: any timing ECO can shift hold margins.
- **Before signoff**: hold must be clean at FF corner for tapeout.

## Inputs

1. Post-CTS or post-route database (DEF + netlist)
2. SDC constraints with clock definitions
3. Liberty files for the fast (FF) corner — hold is worst at FF
4. STA hold report (`report_checks -path_delay min`)
5. Area budget — maximum area overhead for buffer insertion (typically 2-5%)
6. Hold slack margin target (e.g., 0 ps for nominal, +50 ps for guardband)

## Workflow

### Step 1: Analyze Hold Violations

Run STA at the FF corner (fast process, high voltage, low temperature):

```tcl
# OpenSTA
read_liberty gf180mcu_fd_sc_mcu7t5v0__ff_1p10v_m40c.lib
read_verilog <design>.v
read_sdc constraints/<design>.sdc
report_checks -path_delay min -slack_max 0 -format full_clock_expanded
```

Collect:
- Total number of hold-violating endpoints
- Worst Hold Slack (WHS)
- Total Hold Slack (THS) — sum of all negative hold slacks
- Distribution: how many endpoints per slack bucket (0 to -100 ps, -100 to -200 ps, etc.)

### Step 2: Hold Fix Strategy

The fix is always the same: **slow down the data path** by inserting buffers or delay cells.

Strategy selection:
| Violation severity | Strategy |
|--------------------|----------|
| Slack > -50 ps | Single buffer insertion |
| Slack -50 to -200 ps | Buffer chain (2-3 buffers) |
| Slack < -200 ps | Delay cell insertion or path restructure |

Buffer selection from library:
- Prefer minimum-drive buffers (smallest area, most delay)
- Use delay cells if available in the PDK (e.g., `gf180mcu_fd_sc_mcu7t5v0__dlygate`)
- Avoid high-drive buffers — they add less delay per area

### Step 3: Execute Hold Fix in OpenROAD

```tcl
# OpenROAD hold fix
repair_timing -hold \
    -slack_margin <margin_ps> \
    -allow_setup_violations false \
    -max_buffer_percent <area_budget_%>

# Check results
report_worst_slack -min
report_tns -min
```

Key parameters:
- `-slack_margin`: target hold slack (0 for exact, positive for guardband)
- `-allow_setup_violations false`: **critical** — never trade setup for hold
- `-max_buffer_percent`: cap area overhead (default 5%)

### Step 4: Verify — No Setup Regression

After hold fix, verify setup timing is still clean:

```tcl
# Check setup at SS corner
report_checks -path_delay max -slack_max 0
report_worst_slack -max
```

If setup degrades:
- The inserted buffers added delay on paths that were also setup-critical
- Reduce hold margin target
- Or upsize the hold buffers to reduce their setup impact

### Step 5: Iterate Until Clean

```
Iteration 1: WHS = -180 ps, THS = -12400 ps, 87 endpoints
  -> Insert 143 buffers
Iteration 2: WHS = -22 ps, THS = -340 ps, 8 endpoints
  -> Insert 12 buffers
Iteration 3: WHS = +5 ps, THS = 0 ps, 0 endpoints
  -> CLEAN. Hold fixed.
```

Convergence criteria:
- WHS >= 0 ps (or >= margin target)
- THS = 0 ps
- Setup WNS has not degraded beyond acceptable limit
- Area overhead within budget

Typical iteration count: 2-4 rounds for a clean design.

### Step 6: Corner Coverage

Hold must be verified across all fast corners:
- FF, high voltage, low temperature (worst hold)
- FF, nominal voltage, low temperature
- TT at all temperatures (sanity check)

If using MCMM, the hold analysis view must use the FF corner.

## Constraints and Guardrails

1. **Never violate setup while fixing hold**: this is a hard rule. `-allow_setup_violations false`.
2. **Area budget**: hold buffers should not exceed 5% of total cell area. If exceeded, investigate why — possible CTS imbalance.
3. **Don't fix false paths**: verify that hold-violating paths are real (not async crossings marked as false_path in SDC).
4. **Clock gating paths**: hold fix near ICG cells needs special care — the enable timing must remain correct.
5. **Scan chain**: DFT scan paths also need hold clean at scan clock frequency.

## Output format

- `timing/hold_fix_report.md`:
  - Before/after summary: WHS, THS, #violating endpoints
  - Buffers inserted: count, type, total area overhead
  - Setup impact: WNS before/after hold fix
  - Per-iteration log
  - Corner coverage matrix
  - Any remaining violations (if area budget exceeded)

## Technical basis

Hold timing: T_hold < T_clk_skew + T_data_delay. When CTS adds clock insertion delay (skew), short data paths violate hold. Standard reference: Bhasker & Chadha "Static Timing Analysis for Nanometer Designs" Chapter 7. OpenROAD `repair_timing -hold` documentation: https://openroad.readthedocs.io/en/latest/main/src/rsz/README.html.

## Handoff

- Hold clean -> `/sta-review` for full signoff timing review
- Setup degraded -> `/sta-review` to classify setup violations
- Area exceeded -> `/placement-optimize` to reclaim area
- New hold after routing -> re-run this skill post-route
- Signoff -> `/tapeout-checklist` includes hold clean as gate

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
