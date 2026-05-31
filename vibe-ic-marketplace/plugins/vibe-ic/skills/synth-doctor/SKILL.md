---
name: synth-doctor
description: "Automatically diagnose and fix EDA tool failures. Parses Yosys synthesis and OpenROAD P&R logs, classifies errors into known patterns, and provides actionable fix commands. Triggers when: synthesis fails, P&R fails, 'why did synth fail', 'fix synthesis error', 'DRC violation', or any EDA tool error during Phase 2. Proactively suggest this when any Phase 2 tool returns non-zero exit code."
---

# Synth Doctor — EDA Error Classifier + Auto-Fix

Automatically diagnose EDA tool failures and provide actionable fix suggestions.

## Tools

### synth_doctor.py — Yosys Synthesis Errors
```bash
python3 tools/vibe_ic_tools/synth_doctor.py synth.log          # diagnosis
python3 tools/vibe_ic_tools/synth_doctor.py synth.log --fix     # with fix code
python3 tools/vibe_ic_tools/synth_doctor.py synth.log --json    # machine output
```

10 known patterns from 135-IC campaign:
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

### pnr_doctor.py — OpenROAD P&R Errors
```bash
python3 tools/vibe_ic_tools/pnr_doctor.py pnr.log              # diagnosis
python3 tools/vibe_ic_tools/pnr_doctor.py pnr.log --drc drc.rpt # with DRC
```

10 known patterns:
| Pattern | Auto-fixable |
|---------|:------------:|
| GPL_DIVERGE | Skip (trivial design) |
| DRT_POWER_NET | Use global route only |
| FLOORPLAN_FAIL | Fix site name |
| DRC_SPACING | Reduce utilization |
| TIMING_FAIL | Relax clock period |
| NO_CLOCK | Add virtual clock |
| CONGESTION | Reduce density |

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

### output_latency_advisor.py — registered-output / sampling-latency notes

Surfaces outputs that are registered (valid **+1 cycle** after their inputs).
Confirm each against the spec's required valid-cycle — an off-by-one-cycle
output (Moore/pipelined vs combinational) is a classic spec miss.

```bash
python3 programs/output_latency_advisor.py --rtl-dir <rtl>
```

## Integration with flow-orchestrate

When flow-orchestrate detects a tool failure:
1. Run synth_doctor or pnr_doctor on the log
2. If auto-fixable: apply fix and retry
3. If manual: present diagnosis to user with suggested fix
4. Log all diagnoses to phase2_eda.log

## ⛔ ECO spare-cell preservation (mandatory)

> ⛔ **ECO spare-cell preservation:** cells/gates/pads carrying the `dont_touch` /
> `keep` attribute (or otherwise tagged spare/ECO) are RESERVED for a future
> metal-only ECO. NEVER delete, resize, re-purpose, or optimize them away. When
> fixing a synthesis/PnR failure, do **not** emit `opt_clean` / `clean -purge` /
> `remove_buffers` / area-recovery passes that act on keep-marked instances — a
> "remove unused logic" fix must explicitly exclude the spare pool. After any
> fix you apply, `spare_cell_preservation_check.py` MUST still PASS (spare set +
> keep attrs intact, 0 removed); if your fix drops a spare it is a regression —
> restore it and re-run the checker. See the `design-for-eco` skill.

## Constant nets need a tie-cell pass before PnR (captured v0.1.95)

A gate netlist that drives any constant bit (1'h0 / 1'h1 — from CRC tables, output
clamps, tie-offs, zeroed unused outputs) as a bare net will fail TritonRoute with
**DRT-0305 (zero_ net)** / DRT-0199 during detailed route. The fix is a tie-cell pass:
map the constants to the PDK's dedicated tie cell (sky130 `sky130_fd_sc_hd__conb_1`,
dual HI/LO output) and split shared nets — in yosys, after abc and before write_verilog:

```
setundef -zero; hilomap -hicell <TIE_CELL> <HI_PIN> -locell <TIE_CELL> <LO_PIN>; splitnets; clean
```

**Recipe refinement (v0.1.98, learned on the HDLC pilot — the v0.1.95 recipe was
INSUFFICIENT on a complex design):** two extra rules are load-bearing, not optional:
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

**Path note (the recurring trap):** `phase3_one_shot_runner.py` ALREADY does a tie-cell pass
automatically (it discovers the tie cell from the liberty and inserts hilomap). But the
**bare MCP `eda_synth`→`eda_pnr` path** (what the doc→GDS pilots drive) does NOT — its
yosys script is `synth; dfflibmap; abc; clean; write_verilog` with no hilomap, and it only
emits a `zero_net_hint` rather than auto-applying the fix. So when driving the bare MCP
path, either (a) re-synth with the refined `setundef -zero; hilomap; splitnets; clean` pass
above via `eda_run_tcl` before `eda_pnr`, or (b) drive synth through the phase3 runner which
handles it. The cell count is unchanged — the tie cells replace the bare constants 1:1.
Forward-validated SENT→QSPI→HDLC (3 pilots). Tracked for a permanent eda_synth fix in
`ORGANIC-20260531-mcp-eda-synth-missing-hilomap-tiecells`.

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
