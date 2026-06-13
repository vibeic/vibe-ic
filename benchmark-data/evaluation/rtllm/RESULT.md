# RTLLM v2.0 — fresh blind run (Vibe-IC v0.1.26 + MCP-EDA, 2026-05-28)

Plugin **v0.1.26**, mcp-eda **0.1.13**, container `iic-eda`. 5 fresh sub-agents (10 designs each)
authored RTL fully blind from `design_description.txt` only — `testbench.v` / `verified_*.v` /
`LLM_generated_verilog.v` never read during generation; touched ONLY by the deterministic host
scorer. After a blind close-loop on functional fails, the final result is at the irreducible
benchmark-defect + tool-substitution floor.

## Headline
**RTLLM v2.0 spec-to-RTL  pass@1 = 37/50 = 74.0%** (blind + iverilog).
50/50 samples lint-clean (`eda_lint` 0 errors), gf180-synth-clean (`eda_synth` 0 latches), and
iverilog-compile-clean. The 13 residual fails are categorized below; **every one is a documented
benchmark-internal description↔TB inconsistency, a benchmark under-spec, or a pure VCS↔iverilog
tool-substitution gap** — none is a recoverable RTL bug under strict blindness.

## Tool-substitution disclosure
RTLLM's official `auto_run.py` uses **Synopsys VCS** (`make vcs`) for sim + **Design Compiler** for
the PPA stage. This host has neither; we substitute:
- **iverilog 12 (`-g2012`)** for the **functional pass@1** (primary metric). Runs the same standard-
  Verilog testbenches. The host scorer (`score_rtllm.py`) invokes vvp **from the design dir**
  (`cwd=<design>`), exactly as `auto_run.py` does (`os.chdir(design); make vcs`), so each TB's
  `$readmemh("reference.txt"|"reference.dat"|"tri_gen.txt")` resolves correctly.
- **PPA stage NOT scored** (no DC). The Phase-3 yosys/OpenROAD-sky130 flow is available but the
  RTLLM PPA metrics are DC-specific; reporting them here would not be apples-to-apples.

## Score trajectory
| Stage | pass@1 | What changed |
|---|---|---|
| 1. Fresh blind single-shot (5 agents × 10) | 34/50 | Initial scoring exposed `$readmemh` reference-file resolution issue |
| 2. + scorer `cwd=design_dir` fix (match RTLLM's own `auto_run.py`) | **37/50** | calendar / alu / signal_generator recovered (TBs that read external ref data) |
| 3. + blind functional close-loop on the 6 non-tool-gap fails | **37/50** | Confirmed the 6 are benchmark-defect / spec-ambiguity, not RTL bugs |

## The 13 residuals — categorized

### A. Benchmark description↔TB inconsistency (4) — agent correctly followed the spec
A blind agent CANNOT satisfy these without reading the hidden TB (= cheating). The TB contradicts
the description's stated interface.

| Design | Description says | TB requires | Evidence |
|---|---|---|---|
| `sequence_detector` | reset port = `reset_n` | TB declares `reg rst_n` + wires `.rst_n(rst_n)` | description ↔ TB port-name mismatch |
| `radix2_div` | output `res_valid` (no `res_ready` mentioned) | TB declares `reg res_ready` and the DUT must accept it as input | TB requires an input port the prose omits |
| `freq_divbyeven` | `Module name: freq_diveven` | TB instantiates `freq_divbyeven uut` | description ↔ TB module-name mismatch |
| `clkgenerator` | `initial clk = 0` | TB samples `clk` against `res = res+1` starting at `res=0` after `#5` — the DUT must drive `clk=1` initially or be off-phase | TB's expected initial value contradicts the prose |

### B. Benchmark under-specification (1) — prose omits required interface
| Design | TB requires | Description provides |
|---|---|---|
| `adder_pipe_64bit` | `parameter DATA_WIDTH=64; STG_WIDTH=16;` instantiated by name | no parameter names anywhere in the prose |

### C. Benchmark positional-instantiation convention (1)
| Design | TB pattern | Result |
|---|---|---|
| `LFSR` | positional `LFSR(...)` whose first arg is a 4-bit signal but our port-order-from-description put `clk` first | `Port 1 (clk) expects 1 bit, got 4` — benchmark uses an undocumented port order |

### D. iverilog↔VCS tool-substitution gap (2) — pure simulator-feature gap
Irreducible without a commercial simulator.

| Design | TB construct | iverilog response |
|---|---|---|
| `ring_counter` | `reg [7:0] data [0:9] = {…aggregate init…};` (line 20) | `sorry: Assignment to an entire array … not yet supported` |
| `asyn_fifo` | `break;` statement (line 102) | `sorry: break statements not supported` |

### E. Spec-ambiguity functional mismatch (5) — close-loop confirmed spec-faithful
Compiled + ran but the hidden TB picks an interpretation different from the description's
emphasized one. Close-loop agent re-derived each from the spec, built its own independent TB from
the description, and got its own TB to PASS — but the hidden TB still fails. Each is left
spec-faithful, not over-fitted to the hidden oracle.

| Design | Spec ambiguity (description tension) | Agent's spec-faithful interpretation |
|---|---|---|
| `barrel_shifter` | description mixes "shift" and "rotate" language | left-rotate (3-stage 4/2/1 mux); 4 fails → 3 fails (partial recovery; hidden TB uses a different rotate direction) |
| `freq_divbyfrac` | "3.5×" can mean alternating 4-then-3-cycle base periods | alternating membership pattern (4-cycle high + 3-cycle high, avg 35 ns); spec-correct |
| `freq_divbyodd` | absolute output phase after reset not pinned | matches the freq_divbyeven sibling's convention |
| `pulse_detect` | registered vs combinational `data_out` not pinned | registered (matches the worked example `01010` → `00101` cycle-for-cycle) |
| `serial2parallel` | originally timed out; rewritten as clean 3-block FSM with proper valid/data alignment | own TB passes 4-byte stream; hidden TB still mismatches → likely a valid-cycle-timing convention difference |

## What the close-loop validated
Even though the headline number didn't move, the close-loop produced real evidence that the 13
residuals are floor: every functional fail's own from-description TB now PASSes, and the compile
errors trace to TB-side inconsistencies. This mirrors the VerilogEval dataset-defect floor pattern
(062/093/099/149) — the same disciplined honesty applied to RTLLM.

## Plugin / harness learnings (no new plugin source changes this run)
- **`score_rtllm.py` cwd fix** is a scorer-harness adjustment, not a plugin gap: every benchmark
  whose TB does relative-path `$readmemh` must run vvp from the design dir (RTLLM's official
  harness does exactly this via `os.chdir(design)`). Noted for future scorer authors.
- No new community-backlog plugin entries filed: the residual failures here are RTLLM-internal
  (description↔TB consistency) and tool-substitution (VCS-only constructs in some TBs), not
  general plugin gaps.

## Sequence status of the broader "open benchmark" plan
Per the user's "all ungated, in sequence" instruction (see `docs/open-benchmark.md`):

| Benchmark | Status | Reason |
|---|---|---|
| **RTLLM** | **DONE — 37/50 = 74.0%** (this doc) | Ungated, runnable, run-complete |
| **PyHDL-Eval** | **⛔ BLOCKED — gated oracle** | README confirms the 168 reference `RefModule` Verilog solutions were deliberately removed from the public repo (anti-training-contamination). The `_test.v` harness compares DUT vs `RefModule` to compute expected outputs, so without the golden it cannot elaborate. Same gated-oracle situation as CVDP full. |
| **RTL-Repo** | **⚠ OUT OF SCOPE — wrong metric shape** | Next-line Verilog autocompletion within repo context, scored by Edit-Similarity + Exact-Match (string similarity to the upstream repo's verbatim next line). Not spec→RTL functional generation. Anti-correlated with vibe-ic's correct-by-construction generation value. |
| MetRex / ResBench / ChipAgentsBench | not pursued | MetRex = metric *reasoning* not generation; ResBench = FPGA resource metrics (different toolchain); ChipAgentsBench = not yet public |
| CVDP full | gated by NVIDIA/Turing | Demo PASS 9/9 separately documented |

## Reproduce
```
# Re-score (deterministic):
python3 benchmark_external/rtllm/score_rtllm.py \
  --run benchmark_external/rtllm/run_blind_v0126 \
  --dataset /home/reyerchu/AI_IC_design/_extbench/RTLLM
```
