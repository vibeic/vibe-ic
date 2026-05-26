# Step 18 — CTS depth / skew / buffers

**What ran:** Read OURS TritonCTS log (CTS-0018 buffers, CTS-0012/0013 depth, CTS-0207 dummy loads); compared with REF.

| Metric | OURS | REF |
|---|---|---|
| Clock buffers created | 197 | 137 |
| Min buffers in clock path (depth) | 4 | 3 |
| Max buffers in clock path (depth) | 4 | 3 |
| Dummy loads inserted | 54 | per REF |
| Tree balance | min==max depth = 4 (balanced) | min==max = 3 (balanced) |

**Verdict: IN-RANGE / DIFFERENT-BUT-OK.** Both clock trees are perfectly balanced (min depth == max depth), which is the key skew-quality indicator — equal insertion depth on all paths minimizes structural skew. OURS uses depth-4 with 197 buffers (more sinks fan-out + 25.9 ns budget) vs REF depth-3 / 137 buffers. Both are healthy balanced H-trees.

**Caveat (honest):** OURS log shows `CTS-0104 Clock wire resistance/capacitance values are zero` during CTS — TritonCTS planned the tree without RC-annotated wire delays (same warning appears in REF's clock_tree.rpt). The true skew is captured at Step 22 with the post-route SPEF-annotated STA, where clock-network delay = 0.58 ns propagated and timing closes at TT (WNS=0). Numeric per-sink skew is not separately reported by the open-source TritonCTS summary — depth balance is the available metric.

**Evidence:** OURS `phase3/stage3/pnr/openroad.log` (CTS-0018/0012/0013/0207); REF `phase3/stage3/cts/clock_tree.rpt`.
