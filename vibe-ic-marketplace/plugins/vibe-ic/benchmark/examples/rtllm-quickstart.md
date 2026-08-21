# RTLLM v2.0 quickstart (Shape B, MIT, ungated)

Smallest end-to-end recipe for a fresh plugin user:

```bash
# 1. Clone the dataset (one-time; ~1 MB)
git clone https://github.com/hkust-zhiyao/RTLLM ~/datasets/RTLLM

# 2. Show plan + env check
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py rtllm

# 3. Set up the run dir
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py rtllm \
    --setup --dataset ~/datasets/RTLLM --run ~/runs/rtllm_001

# 4. Drive batches per blind_instructions_shape_b.md
#    Per design: vibe_ic_one_shot_runner.py <project> --skip-phase3 --skip-analog --skip-hardware
#    Each <project> = <run>/work/<leaf>/ with input/phase1_prompt.md = design_description.txt
#    The runner does spec-to-rtl (with chip_top wrapper, hygiene --fix, lint, synth).
#    Then copy <project>/phase2/stage1/rtl/<top>.v to <run>/samples/<leaf>.v.

# 5. Score (host iverilog substituting for VCS; vvp runs from design_dir)
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py rtllm \
    --score --run ~/runs/rtllm_001
# → writes ~/runs/rtllm_001/pass_at_1.json with pass@1
```

## Honest expectations
- 50 designs total. 2 of them (`ring_counter`, `asyn_fifo`) have testbenches
  written in VCS-only constructs that iverilog rejects → tool-substitution
  floor (skill § 4 Cat D), NOT recoverable without VCS.
- A handful of others have description↔TB inconsistencies (skill § 4 Cat A):
  `sequence_detector` (`reset_n`↔`rst_n`), `freq_divbyeven` (module name
  mismatch), `radix2_div` (TB needs a `res_ready` input the prose under-specs),
  etc. Document these per the triage rubric; don't try to "fix" by peeking at
  the TB.
- The 2026-05-28 baseline at 37/50 was Shape C BY MISTAKE; running this
  quickstart (Shape B) measures the Vibe-IC RUNNER's RTLLM number — the correct
  thing to publish.
