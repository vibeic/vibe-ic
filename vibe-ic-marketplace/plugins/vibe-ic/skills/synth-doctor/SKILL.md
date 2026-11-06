---
name: synth-doctor
description: "Automatically diagnose and fix EDA tool failures. Parses Yosys synthesis and OpenROAD P&R logs, classifies errors into known patterns, and provides actionable fix commands. Triggers when: synthesis fails, P&R fails, 'why did synth fail', 'fix synthesis error', 'DRC violation', or any EDA tool error during Phase 2. Proactively suggest this when any Phase 2 tool returns non-zero exit code."
---

# Synth Doctor — EDA Error Classifier + Auto-Fix

Automatically diagnose EDA tool failures and provide actionable fix suggestions.

## Read the native tool failure

Open the actual Yosys, OpenROAD or LibreLane log and identify the failed native
command, design scope and diagnostic. Use the following patterns as repair
ideas, not automatic verdicts or a confidence score. Verify the cause in the
actual design before changing it.

### Yosys diagnostic patterns

| Pattern | Frequency | Auto-fixable |
|---------|:---------:|:------------:|
| UNPACKED_ARRAY | Common | Yes — flatten to packed |
| MULTI_DRIVER | Common | Yes — merge to single always_ff |
| RETURN_IN_FUNC | Occasional | Yes — use func name assignment |
| PAST_IN_COMB | Occasional | Yes — shadow register |
| AUTOMATIC_IN_FF | Occasional | Yes — module-level wire |
| LATCH_INFERENCE | Common | Yes — add default assignments |
| SYNTAX_ERROR | Varies | Manual review needed |
| MODULE_NOT_FOUND | Rare | Yes — add source file |
| WIDTH_MISMATCH | Common | Yes — explicit sizing |
| UNKNOWN | Rare | Manual review needed |

For multiple drivers, choose the merge priority from the actual FSM behavior.
For width mismatches, select zero/sign extension from the signal semantics.
An unrecognized error requires the raw native diagnostic and design context.

### OpenROAD diagnostic patterns

| Pattern | OpenROAD signature | Canonical fix | conf |
|---------|---|---|:---:|
| GPL_DIVERGE | GPL-*, "placement diverged" | skip (trivial design) | 0.50 |
| DRT_POWER_NET | POWER/GROUND net in signal router | global/PDN route only (manual) | 0.0 |
| FLOORPLAN_FAIL | IFP-*, die-area invalid | fix site name from cell LEF | 1.0 |
| DRC_SPACING | spacing/short violation | reduce utilization | 0.70 |
| TIMING_FAIL | negative slack / WNS<0 | re-arch long path / relax per spec | 0.0 |
| NO_CLOCK | "no clocks defined" | add (virtual) clock in SDC | 0.90 |
| CONGESTION | congestion / overflow | reduce density | 0.70 |
| DRT_ZERO_NET | DRT-0305 zero_ GROUND | tie-cell pass (setundef -zero; hilomap; splitnets; clean) | 1.0 |
| SITE_NOT_FOUND | IFP-0018 site not found | read SITE from cell LEF | 1.0 |
| MISSING_TRACKS | PPL-0021 no routing tracks | add make_tracks from LEF PITCH | 0.90 |

Do not silently relax a fixed clock requirement to repair timing. Read the
actual critical path and choose a physical or architectural fix. Resolve
power-grid, floorplan and routing issues in the design, configuration or tool.

### arith_ss_corner_risk_check.py — slow-corner timing-risk predictor (pre-synth)

A `TIMING_FAIL` at the **SS** (slow-slow, cold, low-V) corner is most often a
wide, single-cycle **ripple-carry add / accumulate / compare** chain. The spm
and sha256 benchmark ICs both closed at TT but failed cold SS, and were rebuilt
with carry-save / carry-select / CSA-tree architectures. Run this **before**
synth to localise the risk, and again when triaging a `TIMING_FAIL` instead of
guessing which path to pipeline:

```bash
python3 programs/arith_ss_corner_risk_check.py --rtl-dir <rtl>            # advisory
python3 programs/arith_ss_corner_risk_check.py --strict --rtl-dir <rtl>   # exit 1 on HIGH
```

HIGH findings name the destination register, the carry-chain width, and the
add-chain depth. The fix is a carry-save / carry-select / parallel-prefix adder
or a pipeline stage — **not** a clock-period relax when the spec clock is fixed.
Designs that document a carry-save / carry-select / prefix / pipelined strategy
(in module name, signal names, or comments) are recognised and not flagged.

### Map a prefix adder with native Yosys commands

Use Yosys's available carry-lookahead maps when the measured carry chain is
actually limiting timing. For a non-default topology, apply the selected map
and `+/techmap.v` in the same `techmap` call with the choice map first.
Otherwise the design may silently retain the default mapping.

For an already gate-level ripple adder, recover the word-level adder with
`extract_fa -fa -ha; opt_clean; lift_adder` only when the selected Yosys fork
supports those commands. A stock tool without `lift_adder` cannot execute that
path. Run native combinational equivalence after the transformation and native
timing on the resulting mapped design. An unproven equivalence result or a
missing timing result leaves that part of the proposed fix open.

### native tool review — registered-output / sampling-latency notes

Surfaces outputs that are registered (valid **+1 cycle** after their inputs).
Confirm each against the spec's required valid-cycle — an off-by-one-cycle
output (Moore/pipelined vs combinational) is a classic spec miss.

Read the input timing convention and native simulation/formal results before changing output registration. Preserve the specified latency and handshake behavior through any synthesis repair.

## Repair the failed native step

1. Read the failed tool command and its actual diagnostic.
2. Reproduce the design, configuration or tool cause with the smallest relevant
   native execution.
3. Fix that cause and rerun the affected native steps using the same original
   constraints and limits.
4. Review the new result, functional behavior and any affected timing, area,
   power or physical checks before reporting completion.

## ⛔ ECO spare-cell preservation (mandatory)

> Compare the native netlist or implementation database before and after optimization. Preserve every unused ECO spare, its keep attributes and the reserved pads; an unintentionally removed spare must be restored.

## Constant nets need a tie-cell pass before PnR (captured v0.1.95)

A gate netlist that drives any constant bit (1'h0 / 1'h1 — from CRC tables, output
clamps, tie-offs, zeroed unused outputs) as a bare net will fail TritonRoute with
**DRT-0305 (zero_ net)** / DRT-0199 during detailed route. The fix is a tie-cell pass:
map the constants to the PDK's dedicated tie cell (sky130 `sky130_fd_sc_hd__conb_1`,
dual HI/LO output) and split shared nets — in yosys, after abc and before write_verilog:

```
setundef -zero; hilomap -hicell <TIE_CELL> <HI_PIN> -locell <TIE_CELL> <LO_PIN>; splitnets; clean
```

For a design that requires tie cells, run setundef before hilomap and opt_clean -purge before hilomap so newly created tie instances remain in the final native netlist.
1. **`setundef -zero` BEFORE `hilomap`.** A function with don't-care output bits (yosys emits
   `1'hx` for unreachable/dead bits — common in framing/CRC logic) survives `hilomap` as a
   bare `zero_`/`x` net that TritonRoute still rejects with DRT-0305. `setundef -zero` resolves
   the x bits to 0 first so `hilomap` can tie them.
2. **Do NOT run `opt_clean` (or `clean -purge`) AFTER `hilomap`.** `opt_clean` treats the just-
   inserted tie cells as removable constant drivers and DELETES them, re-introducing the bare
   constant nets. Use plain `clean` (or nothing). On HDLC, `hilomap; opt_clean` let DRT-0305
   fire (0 surviving tie cells); `setundef -zero; hilomap; splitnets; clean` kept all 1780
   `conb_1` cells and PnR ran clean. (This also satisfies the ECO spare-cell rule above —
   never `opt_clean` away inserted cells.)

> Read the actual Yosys script/log and emitted netlist to confirm legal tie-cell mapping where the target library requires it. Keep tech mapping, tie mapping and netlist writing in the native tool-supported order.

**Path note (the recurring trap):** `phase3_one_shot_runner.py` ALREADY does a tie-cell pass
automatically (it discovers the tie cell from the liberty and inserts hilomap). But the
**bare MCP `eda_synth`→`eda_pnr` path** (what the doc→GDS pilots drive) does NOT — its
yosys script is `synth; dfflibmap; abc; clean; write_verilog` with no hilomap, and it only
emits a `zero_net_hint` rather than auto-applying the fix. So when driving the bare MCP
path, either (a) re-synth with the refined `setundef -zero; hilomap; splitnets; clean` pass
above via `eda_run_tcl` before `eda_pnr`, or (b) drive synth through the phase3 runner which
handles it. The cell count is unchanged — the tie cells replace the bare constants 1:1.
Forward-validated SENT→QSPI→HDLC→SpaceWire (4 pilots, clean first-pass each). Tracked for a permanent eda_synth fix in
`ORGANIC-20260531-mcp-eda-synth-missing-hilomap-tiecells`.
### Skill: Match structural evidence to the claimed representation

Separate functional behavior, source syntax, generic mapped cells and physical
library cells. A binary truth-table test establishes function. A procedural-if
requirement also needs its stated syntax and relevant four-state semantics.
An explicit state encoding needs encoding/reset/transition evidence. A mux-only
or minimum-cell claim needs an actual mapped graph in the declared cell model;
universal X-propagation assertions over behavioral RTL do not prove topology.

Freeze the source and retain the native command, tool identity and emitted
netlist. Check cell types/counts and binary source/netlist equivalence
separately. Prove a model-specific lower bound before claiming minimality;
otherwise report only the observed mapped count. Do not relabel generic mux
mapping as physical standard-cell qualification.

If a requested native mapping target fails, preserve that failure and track
the generating tool defect. Where the contract permits generic two-input-LUT
decomposition, native Yosys `abc -lut 2; lut2mux; opt_expr; opt_clean` can supply
an independently inspected mux graph. Its successful result neither repairs
the failed target nor changes the allowed cell model. A bad review test is
retained and corrected through the normal fresh-review/supersession mechanism;
correct RTL is not rewritten merely to satisfy an invalid structural proxy.

**Why not Bucket A:** existing native tools generate and inspect graphs;
choosing the applicable representation and proving a lower bound require the
current input's circuit model. No benchmark-specific structural oracle is added.
