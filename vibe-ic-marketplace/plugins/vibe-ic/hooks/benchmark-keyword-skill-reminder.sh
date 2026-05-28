#!/usr/bin/env bash
# Plugin-shipped UserPromptSubmit hook: if user message mentions any benchmark
# keyword, inject a system reminder telling Claude to load the
# open-benchmark-methodology skill BEFORE responding. Hard enforcement of the
# program-first benchmark doctrine that prevented the 2026-05-28 RTLLM
# methodology mistake (direct-agent authoring vs runner-driven scoring).
INPUT=$(cat 2>/dev/null)
# Match against the JSON envelope (incl. the prompt field). Cheap; never blocks.
if echo "$INPUT" | grep -iqE 'verilogeval|cvdp|rtllm|pyhdl[-_]?eval|rtl[-_]?repo|metrex|resbench|chipagents|vibeic[-_]?bench|benchmark'; then
  cat <<'REMINDER'
<system-reminder>
Benchmark keyword detected. BEFORE responding, invoke Skill(skill="vibe-ic:open-benchmark-methodology") to load the program-first benchmark doctrine. It encodes:
  § 2 the run-shape decision matrix (A=full runner / B=runner --skip-phase3 / C=gates.py harness / D=agentic with runner / E=blocked/out-of-scope)
  § 3 mandatory tool-substitution disclosure (VCS→iverilog, etc.) + cwd=design_dir rule
  § 4 the triage rubric (A-H) — do NOT label a fail benchmark-defect without going through it
  § 5 per-benchmark cheat sheet (current shape + status + any TARGET RE-RUN flagged)
Then use /vibe-ic-benchmark (or programs/benchmark_dispatch.py) — the auto-routing front-door — instead of hand-rolling a harness. DO NOT propose a benchmark run plan, interpret a benchmark result, or call something "benchmark floor" without consulting this skill first.
</system-reminder>
REMINDER
fi
exit 0
