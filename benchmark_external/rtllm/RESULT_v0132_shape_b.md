# RTLLM v2.0 — Shape B re-run after 4 plugin fixes (Vibe-IC v0.1.32 → v0.1.33)

Date 2026-05-28. After v0.1.31's RTLLM Shape B run surfaced 4 chip-agnostic
plugin gaps, v0.1.32 shipped fixes for all 4 and re-ran. v0.1.33 fixes one bug
**introduced** by v0.1.32's chip_top auto-emit (port-DECLARATION instead of
`.name(name)` connections — caught independently by 3 of the 5 v0.1.32 agents).

## Headline

| Run | Plugin | pass@1 | Note |
|---|---|---|---|
| Wrong-shape direct-agent (baseline) | v0.1.26 | 37/50 = 74.0% | Measured "Opus + MCP-EDA" only |
| Shape B correct, no plugin fixes | v0.1.31 | 34/50 = 68.0% | First honest Shape B |
| **Shape B + 4 plugin fixes** | **v0.1.32** | **34/50 = 68.0%** | Same score — fixes don't move the host scorer |
| Shape B + chip_top fix | v0.1.33 | (identical samples) | Internal fix; doesn't change `samples/*.v` |

**Honest finding: 4 real plugin fixes shipped, RTLLM host score unchanged at 34/50.** The host scorer is `iverilog samples/<leaf>.v + testbench.v`, so chip_top wrappers, phase1 ingestion paths, and synth_netlist_check internals **don't affect the score**. Score reflects AI authoring quality in the spec-to-rtl role, which is similar across v0.1.31 and v0.1.32.

## What v0.1.32 fixed (all chip-agnostic)

| # | Fix | Where | Impact on host score? |
|---|---|---|---|
| 1 | `phase1_prompt.md` auto-bridge → `input/docs/` | `phase1_one_shot_runner.step_ingest_render` | UX only |
| 2 | Auto-emit `chip_top.v` wrapper when L9.top ≠ authored top | `phase2_one_shot_runner.step_yosys_synth` | Runner verdict only (scorer uses `samples/<leaf>.v`, not chip_top) |
| 3 | `synth_netlist_check` regex: strip yosys block-comments + escaped-IDs | `synth_netlist_check.CELL_INST_RE` | Runner verdict only |
| 4 | Ship `skills/spec-to-rtl/SKILL.md` (previously-phantom skill) | new SKILL file | AI guidance |

**v0.1.32 also exposed Fix 2's own bug** — caught by 3 independent agents (batches 1, 2, 4): the auto-emitted chip_top wrapper spliced port DECLARATIONS into the DUT instance port-connect list, producing `multi_8bit u_dut (input wire clk, …);` which yosys rejects. **v0.1.33 fixes it** to extract port names and emit named-port connections `multi_8bit u_dut (.clk(clk), .rst(rst), …)`. Internal to the runner — host scorer was never affected by the bug.

## What ELSE the agents discovered (new findable plugin gaps, not yet shipped)

Filed for future patches:

- **`phase1_engine.cli run-all` extracts 0 facts from free-form NL prompts.** Fix 1's bridge correctly copies `phase1_prompt.md` into `input/docs/`, but the doc-ingester then uses `from_existing_docs()` which only consumes pre-structured `L*.json`, not raw markdown. Result: every Path-A NL prompt → 0 facts → 0 L docs → phase2 hard-FAIL at `phase1_precheck` "0/13 L docs". Workaround in v0.1.32: agents hand-authored 14 stub `L*.json` files per design. → file `ORGANIC-20260528-phase1-engine-nl-prompt-zero-facts`.
- **`yosys -top chip_top` is hardcoded even when L9.top_module matches the authored top.** When the AI's authored module name already equals L9.top_module (no rewrite needed), Fix 2 correctly skips auto-emit — but the runner STILL passes `-top chip_top` to yosys, causing "Module `chip_top` not found". Fix: pass `L9.top_module` (or the actual top) to yosys instead of hardcoding "chip_top".
- **`synth_netlist_check` threshold ≥10** trips legitimately-tiny primitives (right_shifter: 8 cells = one 8-bit shift register; correct). Should be design-class-aware or dropped for primitive-class.
- **`final_audit` requires `phase1/analog/analog_block_list.json`** even with `--skip-analog`. Should waive when skip flag set.

## Why the score didn't move

| Plugin fix | What it improves | Why host scorer is unaffected |
|---|---|---|
| Fix 1 prompt-md bridge | Setup UX (one cp instead of two) | Scorer reads `samples/<leaf>.v` produced AFTER bridge; bridge doesn't change RTL content |
| Fix 2 chip_top auto-emit | Runner verdict (yosys can find a top) | `samples/<leaf>.v` is the inner authored module, NOT chip_top; scorer compiles the inner module + testbench.v directly |
| Fix 3 netlist-check regex | Runner verdict (correct cell counts on DFF-heavy designs) | Scorer doesn't use synth_netlist_check at all; it's an internal gate |
| Fix 4 spec-to-rtl SKILL | AI guidance quality (structured authoring contract) | Marginal at best; the AI's RTL authoring patterns didn't materially shift between v0.1.31 and v0.1.32 |

The RTLLM score bottleneck is **AI authoring quality in the spec-to-rtl role** + **the irreducible benchmark-defect floor** (~13 fails per skill § 4 categories A/B/D/E). Plugin work makes the runner correct-by-design and turnkey for new users, but it does not change what the AI emits in `samples/<leaf>.v`.

## Triage of 16 fails per skill § 4

| Category | Count | Designs |
|---|---|---|
| A. Description ↔ TB inconsistency | 5 | sequence_detector (reset_n↔rst_n), freq_divbyeven (module-name mismatch), radix2_div (res_ready under-spec), adder_pipe_64bit (DATA_WIDTH/STG_WIDTH params not in prose), clkgenerator (TB phase ↔ spec init contradiction) |
| B. Benchmark under-spec | 1 | LFSR (TB positional instantiation order undocumented) |
| D. iverilog ↔ VCS tool-substitution gap | 2 | ring_counter (array-aggregate init), asyn_fifo (`break;`) |
| E. Spec-ambiguity functional | 5 | barrel_shifter (shift vs rotate), freq_divbyfrac, freq_divbyodd (phase), pulse_detect (registered vs comb), fsm |
| F/G/H. Agent-fixable with more time | 3 | float_multi (IEEE-754 FP32), signal_generator (function ambiguity), traffic_light (state encoding) |

**~13 are FLOOR** (A/B/D/E unrecoverable under blind+iverilog without contradicting the description / peeking at the hidden TB / using a commercial simulator).
**~3 are agent-fixable** but only with deeper per-design close-loop budget — plugin work doesn't address that.

## Reproduce

```bash
/vibe-ic-benchmark rtllm --setup --dataset <RTLLM> --run <run>
# drive 5 batches per benchmark-harness/blind_instructions_shape_b.md
# AI plays spec-to-rtl role on rtl_gen WAIVE
/vibe-ic-benchmark rtllm --score --run <run>
```
