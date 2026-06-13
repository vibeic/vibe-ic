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
# SENSITIVITY (tightened 2026-06-03, narrowed again per user directive 2026-06-03:
# "benchmark hook should be 'vibe-ic benchmark' or 'vibeic benchmark' or 'vibe ic
# benchmark', …"). The hook now fires ONLY on the explicit project-benchmark
# phrase / command, in any spelling:
#     "vibe-ic benchmark"  "vibeic benchmark"  "vibe ic benchmark"
#     "vibe_ic benchmark"  the /vibe-ic-benchmark slash command
# It deliberately does NOT fire on:
#   - a bare standalone "benchmark" (incidental mentions, "the benchmark hook"),
#   - benchmark NAMES alone (VerilogEval / CVDP / RTLLM / PyHDL-Eval / …),
#   - "benchmark" + a run/score verb,
#   - any compound path (benchmark / benchmark_phase1 / benchmark_external).
# Earlier versions matched all of those and over-fired on tool results, task
# notifications, and ordinary discussion. The reminder only needs to fire when the
# user explicitly invokes the project's benchmark front door.
# Two structural guards remain:
#   1. Match ONLY the user's `prompt` field, never the surrounding JSON envelope.
#   2. Require the literal "vibe[ _-]ic … benchmark" phrase (see PHRASE below).
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

# (2) Intent match — ONLY the explicit project-benchmark phrase / command.
#   vibe + optional [ _-] + ic + one-or-more [ _/-] + benchmark
# matches: "vibe-ic benchmark", "vibeic benchmark", "vibe ic benchmark",
#          "vibe_ic benchmark", "vibe-ic-benchmark", "/vibe-ic-benchmark".
# does NOT match: bare "benchmark", "VerilogEval", "run benchmark",
#          "benchmark", "benchmark_phase1", "benchmark_external".
PHRASE='vibe[ _-]?ic[ _/-]+benchmark'

FIRE=0
if printf '%s' "$HAYSTACK" | grep -iqE "$PHRASE"; then
  FIRE=1
fi

if [ "$FIRE" = "1" ]; then
  cat <<'REMINDER'
<system-reminder>
Project benchmark front-door invoked ("vibe-ic benchmark …").

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
