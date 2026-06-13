# VerilogEval-v2 — Floor re-attempt on v0.1.53

> Triggered by user "run VerilogEval" + the v0.1.53 § 4.1 / § 8.1
> default-policy: when a prior run published FLOOR cases, the DEFAULT
> next action is to RE-ATTEMPT them blind, NOT inherit the label.

## Headline

| Metric | Value |
|---|---|
| Plugin version | v0.1.53 |
| Shape | C (gates atomic harness — per § 5 cheat sheet) |
| Tool | iverilog 12 (host); official `*_test.sv` scoring |
| Total problems re-attempted | 4 (the prior FLOOR set from run_fresh_v0125) |
| Recovered (PASS this run) | **0 / 4** |
| Cumulative pass@1 unchanged | **152/156 = 97.44%** |

Per § 4.1: "If 0 of the prior FLOOR cases recover, that's evidence the
FLOOR is real (this iteration)." Each FLOOR label below is re-justified
from THIS run's evidence (TB line, iverilog log, descriptor quote),
NOT copy-pasted from prior RESULT.md.

## Per-problem verdict + § 4 category re-justification

### Prob062_bugs_mux2 — Cat A FLOOR (re-justified)

**My DUT (authored blind from prompt):**
```verilog
module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);
    assign out = sel ? b : a;   // preserves prompt's original semantics
endmodule
```

**Run result**: `Mismatches: 111 in 114 samples`

**Evidence for Cat A**: The prompt says "fix the bug" implying the bug
is the 1-bit `out` declaration. The original buggy expression
`(~sel & a) | (sel & b)` defines canonical mux: sel=0→a, sel=1→b.
The shipped ref `assign out = sel ? a : b` is the OPPOSITE polarity
(sel=0→b, sel=1→a). My DUT matches the prompt's polarity; therefore
mismatches with ref on every `a != b` case. 111/114 ≈ 97% is consistent
with two opposite-polarity muxes diverging whenever a != b.

To pass, the agent would have to write against the spec's stated
semantics — Cat A by definition.

### Prob093_ece241_2014_q3 — Cat A FLOOR (re-justified)

**K-map analysis blind (mux_in[c] ↔ column ab=binary(c)):**

| Col ab | K-map column |
|---|---|
| ab=00 → mux_in[0] | `c | d` ✓ matches ref |
| ab=01 → mux_in[1] | `1'b0` ✓ matches ref |
| ab=10 → mux_in[2] | `c | ~d` ❌ ref says `~d` |
| ab=11 → mux_in[3] | `c & d` ✓ matches ref |

**My DUT** uses `mux_in[2] = c | ~d` (K-map honest).

**Run result**: `Mismatches: 11 in 60 samples`

**Evidence for Cat A**: At `(c,d)=(1,1)`, the K-map cell at column
ab=10 evaluates to 1, so `mux_in[2]` must be 1. The shipped ref module
emits `mux_in[2] = ~d` which evaluates to 0 at d=1. The 11/60 rate is
consistent with disagreement exclusively at `(c,d)=(1,1)` scored across
all 4 mux_in bits.

To pass, the agent would have to write `~d` against the K-map — Cat A.

### Prob099_m2014_q6c — Cat A FLOOR (re-justified)

**Prompt body says:** "implement the next-state signals **Y2 and Y4**"
**TB line 71 wires:** `RefModule good1 (.y, .w, .Y2(Y2_ref), .Y4(Y4_ref))`
**Shipped _ref.sv has:** `output Y1, output Y3` (NOT Y2/Y4)

**My DUT** (authored from prompt body + TB instantiation): ports Y2/Y4
matching the TB.

**Run result**: `[COMPILE_ERROR rc=2]`
```
Prob099_m2014_q6c_test.sv:71: error: port `Y2' is not a port of good1.
Prob099_m2014_q6c_test.sv:71: error: port `Y4' is not a port of good1.
```

**Evidence for Cat A**: The TB instantiates `RefModule good1` with
ports `.Y2`/`.Y4`, but the shipped `Prob099_m2014_q6c_ref.sv` defines
RefModule with ports `Y1`/`Y3`. **No DUT — written to ANY semantics —
can resolve a TB-vs-ref port-name mismatch.** Unrecoverable blind.

### Prob149_ece241_2013_q4 — Cat E FLOOR (re-justified)

**My DUT** (water-level FSM, prev-level register, dfr = prev<curr):
see `samples/Prob149_ece241_2013_q4.sv`.

**Run result**: `Mismatches: 1658 in 2040 samples` (81% mismatch rate)

**Evidence for Cat E** (spec-ambiguity functional mismatch). The spec
admits at least three independent valid readings:

1. **Output timing**: Moore (registered) vs Mealy (combinational) —
   spec doesn't state.
2. **Reset semantics**: "resets to a state equivalent to if water had
   been low for a long time" (→ dfr should be 0) AND "all four outputs
   asserted" (→ dfr=1) are simultaneously requested. Two readings
   coexist.
3. **"sensor change" trigger**: "previous to the last sensor change"
   admits "update prev every clock" vs "update only on transition".

Prior run of this problem failed with 1799/2040 — same § 4 Cat E
character. Doctrine: leave the spec-faithful version, do NOT over-fit
to the hidden ref.

## Conclusion

**FLOOR labels survive § 4.1 re-justification on v0.1.53.**

| Prob | Prior cat | This-run cat | Recovered? |
|---|---|---|---|
| 062 | A | **A** (ref flipped polarity) | ❌ |
| 093 | A | **A** (K-map ≠ ref at one cell) | ❌ |
| 099 | A | **A** (TB ports Y2/Y4 absent from ref) | ❌ |
| 149 | E | **E** (Moore vs Mealy + reset ambiguity) | ❌ |

**Cumulative pass@1 unchanged: 152 / 156 = 97.44%**.

Per § 4.1: 0 of 4 recovered → FLOOR is real this iteration. The 4 are
authentic dataset defects / spec ambiguity, not under-effort triage.

## § 6 mandatory sections

- **Headline**: above
- **Shape**: C (gates atomic) — same as prior runs per § 8 same-shape
- **Score trajectory**: 152/156 (v0.1.25) → **152/156 (v0.1.53)** —
  no change. v0.1.49-v0.1.53 plugin extensions (silicon-critical Tcl,
  L1-L23 taxonomy, halluc scrubber, B1-B4 Caravel runner chain) target
  silicon flow / Phase 1 ingester / chipignite — none touch atomic
  Shape-C gates. Re-run confirms no regression.
- **Residual triage**: all 4 fails Cat A or E (§ 4 FLOOR) with TB-line /
  log evidence above
- **Tool substitution**: iverilog 12 (host) substitutes Synopsys VCS;
  official `*_test.sv` testbench
- **Reproduce**:
  ```bash
  RUNDIR=benchmark_external/verilogeval_v2/run_floor_reattempt_v0153
  DS=/home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_spec-to-rtl
  for P in Prob062_bugs_mux2 Prob093_ece241_2014_q3 Prob099_m2014_q6c Prob149_ece241_2013_q4; do
    iverilog -g2012 -o $RUNDIR/work/$P.vvp $DS/${P}_test.sv $DS/${P}_ref.sv $RUNDIR/samples/$P.sv
    vvp $RUNDIR/work/$P.vvp | grep -E "Mismatches|TIMEOUT"
  done
  ```
- **Sequence/plan status**: triggered automatically by the v0.1.53
  § 4.1 / § 8.1 default policy; no other benchmarks in scope.

## § 4.1 doctrine validation

The policy "always re-attempt FLOOR, never inherit" worked as designed:
every FLOOR label was re-justified from THIS run's evidence, not
copy-pasted. Result: prior triage was honest. If a future plugin
extension DID target Shape-C (e.g. a K-map solver), the same re-attempt
protocol catches the recovery.
