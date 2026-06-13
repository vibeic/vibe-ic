# Step 16 — Clock planning

**What ran:** Inspected OURS OpenROAD CTS log (TritonCTS) and SDC; compared to REF `cts/clock_plan.json` + `clock_tree.rpt`.

| Metric | OURS | REF |
|---|---|---|
| Clock name / period | core_clock, 25.9 ns (~38.6 MHz, per L1/L7/L9) | clk, 20.0 ns (relaxed 110 ns at SS) |
| Clock net sinks | 1,556 | 1,618 |
| Root buffer | sky130_fd_sc_hd__clkbuf_16 | sky130_fd_sc_hd__clkbuf_16 |
| Sink buffer | sky130_fd_sc_hd__clkbuf_4 | sky130_fd_sc_hd__clkbuf_4 |
| Topology | H-Tree (TritonCTS) | H-Tree (TritonCTS) |

**Verdict: IN-RANGE / DIFFERENT-BUT-OK.** Both designs use the same TritonCTS H-tree planning with identical root/sink buffer choices. OURS targets a 25.9 ns clock (its L9 spec) vs REF's 20 ns. Sink counts are comparable (1,556 vs 1,618). The clock period difference reflects each design's own L-spec, not a planning defect.

**Evidence:** OURS `phase3/stage3/pnr/openroad.log` (CTS-0007/0010/0050/0051), `phase3/stage3/pnr/constraint.sdc`; REF `phase3/stage3/cts/clock_tree.rpt`.
