# CVDP example quickstart (Shape D, N=1 public)

The public CVDP repo ships only `example_dataset/` (one problem per category).
The full 1,500+ problem set is gated by NVIDIA + Turing — request access there.

```bash
# 1. Clone
git clone https://github.com/NVlabs/cvdp_benchmark ~/datasets/cvdp_benchmark

# 2. Plan + env check (verify vibeic-eda container is running)
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py cvdp

# 3. Stage the project under the vibeic-eda mount root
#    (the container can only see paths under the mount; symlinks aren't followed)
MOUNT="$VIBEIC_DESIGNS"           # whatever your vibeic-eda /foss/designs mount maps to (you chose it at install)
rsync -a ~/datasets/cvdp_benchmark/example_dataset/<problem>/ $MOUNT/<problem>/

# 4. Drive the runner per blind_instructions_shape_d.md
python3 ${CLAUDE_PLUGIN_ROOT}/programs/vibe_ic_one_shot_runner.py $MOUNT/<problem> \
    --pdk sky130A --ic-name <ic>

# 5. Score against the hidden cocotb harness
python3 ${CLAUDE_PLUGIN_ROOT}/benchmark/score_cocotb_mcp.py \
    --project $MOUNT/<problem> --top <dut> --rtl work/rtl/<dut>.sv \
    --mount-root $MOUNT
# → writes $MOUNT/<problem>/reports/cocotb_score.json
```

## Honest expectations + the reset-polarity gotcha (skill § 4 Cat A)

The 2026-05-28 baseline on the public `fixed_priority_arbiter` problem hit a
spec ↔ harness inconsistency: the spec labels reset *synchronous* but the
hidden cocotb harness samples `grant==0` immediately after `RisingEdge(clk)`
with no settle delay, racing a synchronous-reset NBA update. The
documented resolution: emit BOTH a spec-literal sync-reset variant and an
async-reset variant (`always @(posedge clk or posedge reset)`); the
async-reset variant passes all TC1-TC8. Keep both files; document the
inconsistency in your RESULT — it's FLOOR, not RTL bug.
