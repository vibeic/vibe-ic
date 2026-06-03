#!/usr/bin/env bash
# Plugin-shipped UserPromptSubmit hook: if the user's prompt expresses intent to
# RUN or INTERPRET a benchmark, inject a system reminder telling Claude to
# (1) load the open-benchmark-methodology skill AND (2) use the /vibe-ic-benchmark
# front door instead of hand-rolling a harness.
#
# Hard enforcement of the program-first benchmark doctrine that prevented the
# 2026-05-28 RTLLM methodology mistake (direct-agent authoring vs runner-driven
# scoring).
#
# SENSITIVITY (tightened 2026-06-03 — the old "bare benchmark anywhere in the
# whole JSON envelope" matched too eagerly: internal paths like
# `benchmark-harness/` / `benchmark_phase1/`, tool-result / task-notification
# text, and incidental mentions such as "the benchmark hook" all false-fired).
# Two changes:
#   1. Match ONLY the user's `prompt` field, never the surrounding envelope
#      (tool results, notifications, file paths the agent is discussing).
#   2. Trigger only on genuine benchmark intent:
#        - a specific benchmark NAME (VerilogEval / CVDP / RTLLM / PyHDL-Eval /
#          RTL-Repo / MetRex / ResBench / ChipAgents), or the /vibe-ic-benchmark
#          command; OR
#        - the standalone word "benchmark" (NOT the path/compound forms
#          benchmark-harness / benchmark_phase1 / benchmark-enhancement) together
#          with a run/score/setup/sweep action verb.
INPUT=$(cat 2>/dev/null)

# (1) Extract just the user's prompt text. Fall back to the raw input only if the
#     envelope has no parseable `prompt` field (the tight pattern below still
#     guards against most incidental matches).
PROMPT=$(printf '%s' "$INPUT" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    sys.stdout.write(d.get("prompt", "") if isinstance(d, dict) else "")
except Exception:
    sys.stdout.write("")
' 2>/dev/null)
HAYSTACK="${PROMPT:-$INPUT}"

# (2) Intent match.
NAMES='verilogeval|cvdp|rtllm|pyhdl[-_]?eval|rtl[-_]?repo|metrex|resbench|chipagents|vibe-?ic-benchmark'
# standalone "benchmark" = not immediately followed by `-` or `_` (excludes the
# benchmark-harness / benchmark_phase1 / benchmark-enhancement compound paths).
BARE='benchmark([^-_a-z]|$)'
VERB='(^|[^a-z])(run|rerun|re-run|score|scoring|setup|set up|sweep|evaluate|eval|執行|跑|重跑|評測|評分)([^a-z]|$)'

FIRE=0
if printf '%s' "$HAYSTACK" | grep -iqE "$NAMES"; then
  FIRE=1
elif printf '%s' "$HAYSTACK" | grep -iqE "$BARE" \
     && printf '%s' "$HAYSTACK" | grep -iqE "$VERB"; then
  FIRE=1
fi

if [ "$FIRE" = "1" ]; then
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
