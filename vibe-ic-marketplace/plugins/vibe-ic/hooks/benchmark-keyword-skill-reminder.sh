#!/usr/bin/env bash
# Plugin-shipped UserPromptSubmit hook: if user message mentions any benchmark
# keyword, inject a system reminder telling Claude to (1) load the
# open-benchmark-methodology skill AND (2) use the /vibe-ic-benchmark front
# door instead of hand-rolling a harness.
#
# Hard enforcement of the program-first benchmark doctrine that prevented the
# 2026-05-28 RTLLM methodology mistake (direct-agent authoring vs runner-
# driven scoring).
#
# Trigger keywords (per user 2026-05-29 directive — "let benchmark,
# VerilogEval and CVDP be the trigger keywords"):
#
#   benchmark      catch-all — covers "run benchmark X" / "score benchmark"
#   VerilogEval    VerilogEval-v2 / VerilogEval-Human
#   CVDP           CVDP / cvdp-bench
#   RTLLM          RTLLM v2
#   PyHDL-Eval     pyhdl_eval, pyhdl-eval
#   RTL-Repo       rtl-repo, rtl_repo
#   MetRex / ResBench / ChipAgentsBench / vibeic-bench
#
INPUT=$(cat 2>/dev/null)
# Match against the JSON envelope (incl. the prompt field). Cheap; never blocks.
if echo "$INPUT" | grep -iqE 'verilogeval|cvdp|rtllm|pyhdl[-_]?eval|rtl[-_]?repo|metrex|resbench|chipagents|vibeic[-_]?bench|benchmark'; then
  cat <<'REMINDER'
<system-reminder>
Benchmark keyword detected (benchmark / VerilogEval / CVDP / RTLLM / …).

DO THIS BEFORE RESPONDING (two-step):

  1. Invoke Skill(skill="vibe-ic:open-benchmark-methodology") to load
     the program-first doctrine:
       § 2 run-shape decision matrix (A=full runner / B=runner --skip-phase3
            / C=gates.py harness / D=agentic with runner / E=blocked-or-OOS)
       § 3 tool-substitution disclosure (VCS→iverilog, DC→yosys+OpenROAD,
            cvdp-sim→iic-osic-tools) + cwd=design_dir rule
       § 4 triage rubric A-H — do NOT label a fail "benchmark-defect" without
            walking through it
       § 5 per-benchmark cheat sheet (current shape + status + TARGET RE-RUN)

  2. Use the runner front-door — NOT a hand-rolled harness:
        /vibe-ic-benchmark <bench> [--list | --setup | --score | --run …]
     or programmatically:
        python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py --list
     This auto-routes the benchmark to its registry shape (BENCHMARK_REGISTRY.json).

DO NOT:
  - propose a benchmark plan / interpret a result without consulting the methodology
  - call something "benchmark floor" without the § 4 triage rubric
  - bypass /vibe-ic-benchmark to run an ad-hoc harness (that's how the
    2026-05-28 RTLLM wrong-shape happened; doctrine: programs-first)
</system-reminder>
REMINDER
fi
exit 0
