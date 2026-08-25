---
name: synth-doctor
description: "Automatically diagnose and fix EDA tool failures. Parses Yosys synthesis and OpenROAD P&R logs, classifies errors into known patterns, and provides actionable fix commands. Triggers when: synthesis fails, P&R fails, 'why did synth fail', 'fix synthesis error', 'DRC violation', or any EDA tool error during Phase 2. Proactively suggest this when any Phase 2 tool returns non-zero exit code."
---

# Synth Doctor — EDA Error Classifier + Auto-Fix

Automatically diagnose EDA tool failures and provide actionable fix suggestions.

## Tools

### synth_doctor.py — Yosys Synthesis Errors

**Run the program — do not re-derive the classification by hand.** The 10-pattern
log→fix table below is implemented deterministically in
`programs/synth_doctor.py`; invoke it on any Yosys synth log and it emits
`{matched_pattern, canonical_fix, confidence}` per finding (chip-AGNOSTIC,
identical every run):

```bash
python3 programs/synth_doctor.py synth.log          # human diagnosis
python3 programs/synth_doctor.py synth.log --fix     # include the canonical fix recipe
python3 programs/synth_doctor.py synth.log --json    # machine output {matched_pattern, canonical_fix, confidence}
```

Importable too: `from synth_doctor import diagnose; diagnose(open('synth.log').read())`.
Verdicts: `CLEAN` (no known signature — note the deny-list + length-floor mean a
clean log NEVER false-alerts), `DIAGNOSED` (≥1 known pattern, fix + confidence
attached), `MANUAL_REVIEW` (only an unrecognised error → `UNKNOWN`, no auto-fix),
`MISSING` (log file absent — graceful, exit 2, no crash). `confidence` is the
per-pattern auto-fix success rate from the 135-IC campaign (`PRACTICAL_NOTES.md`).

**AI judgment still required** when the program returns `DIAGNOSED` with low
confidence or `MANUAL_REVIEW`: the canonical fix is a *recipe*, not a blind patch.
For `MULTI_DRIVER`, the correct merge priority is an FSM-context judgement; for
`WIDTH_MISMATCH`, choose zero- vs sign-extend per signal signedness; for
`SYNTAX_ERROR`/`UNKNOWN`, read the raw error and decide. Apply the program's
classification first, then reason about the specific fix.

10 known patterns from 135-IC campaign (implemented in `programs/synth_doctor.py`):
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

**Run the program** — `programs/pnr_doctor.py` is the PnR analog of
`synth_doctor.py`, implementing the 10-pattern OpenROAD log→fix table below.
Same `{matched_pattern, canonical_fix, confidence}` envelope, same verdicts and
no-false-alert contract (deny-list + length-floor; a clean route log returns
`CLEAN`):

```bash
python3 programs/pnr_doctor.py pnr.log              # human diagnosis
python3 programs/pnr_doctor.py pnr.log --fix         # include the canonical fix recipe
python3 programs/pnr_doctor.py pnr.log --drc drc.rpt # also scan a DRC report (source-tagged)
python3 programs/pnr_doctor.py pnr.log --json        # machine output
```

Importable: `from pnr_doctor import diagnose; diagnose(log_text, drc_text)`.

10 known patterns (implemented in `programs/pnr_doctor.py`; `confidence` shown):
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

**AI judgment still required** for the two `confidence=0.0` patterns:
`DRT_POWER_NET` needs a manual floorplan/PDN fix, and `TIMING_FAIL` must NOT be
"fixed" by silently relaxing a fixed-spec clock — re-architect the long path
(see `arith_ss_corner_risk_check.py` below) or relax only if the spec allows.
The program flags them but deliberately does not auto-fix.

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

### prefix_adder_synth_recipe.py — the parallel-prefix half of that fix, emitted

The remedy named above is not something to hand-write into a `.ys` file. yosys
already ships the parallel-prefix carry-lookahead structures (Brent-Kung is the
DEFAULT `$lcu` map; Kogge-Stone / Han-Carlson / Sklansky ship as `choices/`
maps), so the gap was never the algorithm — it was invoking it correctly. This
program emits the exact recipe, with the combinational-equivalence step
attached:

```bash
python3 programs/prefix_adder_synth_recipe.py --list          # known topologies
python3 programs/prefix_adder_synth_recipe.py \
    --emit <rtl.v> --top <module> --topology kogge-stone      # RTL `a + b`
python3 programs/prefix_adder_synth_recipe.py \
    --emit <netlist.v> --top <module> --topology kogge-stone --gate-level
```

It prints the `.ys` script to stdout (rc 0); rc 2 is an argument error. Feed it
to yosys, or to `eda_run_tcl` / the synth step, the same way as any other
recipe.

**Two things it encodes that are easy to get wrong by hand.**

1. **Ordering.** For a NON-default topology the choice map and `+/techmap.v`
   must be in the SAME `techmap` call with the choice map FIRST. Split across
   two calls, `$alu` never lowers to `$lcu` and it silently falls through to
   Brent-Kung — you would believe you had selected Kogge-Stone and measured
   something else. There is no error message for this.
2. **`--gate-level` is a different problem.** A netlist that is ALREADY a
   gate-level ripple has no `$add`/`$alu` for the prefix techmap to match, so
   the recipe first runs `extract_fa -fa -ha; opt_clean; lift_adder` to recover
   the word-level adder. That path needs the vibeic yosys fork
   (`vibeic-eda:0.2.5+`); on stock yosys `lift_adder` does not exist and the
   script will error rather than quietly skip.

**The CEC step is not decoration and you may not drop it.** This program is a
QoR recipe emitter, not a correctness gate, and its ONE correctness guarantee
is the equivalence proof it appends: a restructured adder is a different
netlist, and `equiv_status` reporting anything other than proven-equivalent is a
hard FAIL — do not ship the restructured netlist. `--no-cec` exists for
measuring depth in isolation and is never the form that reaches a design.

Measured in `vibeic-eda:0.2.3`, 32-bit `a+b`: AIG-AND depth ripple 128 →
Brent-Kung 109 → Kogge-Stone 72, every form CEC-equal to the ripple reference;
and with `--gate-level`, an already-gate-level 32-bit ripple went 128 → 73.

### output_latency_advisor.py — registered-output / sampling-latency notes

Surfaces outputs that are registered (valid **+1 cycle** after their inputs).
Confirm each against the spec's required valid-cycle — an off-by-one-cycle
output (Moore/pipelined vs combinational) is a classic spec miss.

```bash
python3 programs/output_latency_advisor.py --rtl-dir <rtl>
```

## Integration with flow-orchestrate

When flow-orchestrate detects a tool failure:
1. Run `programs/synth_doctor.py` (or `programs/pnr_doctor.py`) `--json` on the log
2. If `verdict==DIAGNOSED` and the finding's `auto_fixable` is true (confidence>0):
   apply the `canonical_fix` and retry
3. If `verdict==MANUAL_REVIEW`, or a finding has `confidence==0`: present the
   diagnosis to the user with the suggested fix and exercise AI judgment
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
INSUFFICIENT on a complex design):** two extra ordering rules are load-bearing, not optional.
Both are **enforced deterministically by `programs/yosys_tiecell_recipe_order_check.py`**
(run it on any `.ys` synth script before yosys runs; `--json` for machine output; SKIP on
non-synth scripts, exit 1 on violation, exit 2 on missing file):
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

> The complementary **presence + techmap→hilomap→write_verilog ordering** is enforced by
> `programs/yosys_hilomap_required_check.py`. Run both before synth: the hilomap-required
> check asserts the tie-cell pass exists in the right place; the tiecell-recipe-order check
> asserts the two v0.1.98 refinements above. Do not re-derive either by hand.

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
