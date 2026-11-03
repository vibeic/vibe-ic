#!/usr/bin/env bash
# Plugin-shipped UserPromptSubmit hook — RE-ASSERTS the binding IC-Expert identity
# whenever the user's prompt signals vibe-ic plugin usage / an IC-design task.
#
# Owner directive (2026-07-05, STRONG RULE): "everytime when AI using vibe-ic
# plugin, AI IS the IC expert with expert-DB and expert-skills … and knows
# when/where to trigger the plugin's programs/gates/agents/skills."
#
# The SessionStart sibling (ic-expert-identity-session.sh) sets the identity once;
# this re-asserts it on the turns that actually use the plugin, so it survives a
# long session where the opening banner scrolled out of the window.
#
# Fires ONLY on the user `prompt` field (never the JSON envelope), on a deliberately
# SPECIFIC signal set so it does not inject on unrelated chit-chat:
#   • the plugin by name / command: vibe-ic, vibeic, vibe ic, /vibe-ic-*
#   • an unambiguous IC-design-flow verb/noun: RTL, Verilog/SystemVerilog, tape-out,
#     synthesis/synthesize, place-and-route / PnR, floorplan, DRC/LVS/STA, netlist,
#     spec-to-rtl, phase 1/2/3, the L1-L27 doc track.
# NEVER blocks the turn: always exit 0.
set +e

INPUT=$(cat 2>/dev/null)

PROMPT=$(printf '%s' "$INPUT" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    sys.stdout.write(d.get("prompt", "") if isinstance(d, dict) else "")
except Exception:
    sys.stdout.write("")
' 2>/dev/null)
HAYSTACK="${PROMPT:-$INPUT}"

# Plugin-by-name/command OR an unambiguous IC-design-flow term.
PLUGIN='vibe[ _-]?ic'
FLOW='\b(RTL|verilog|systemverilog|tape[ -]?out|floorplan|netlist|synthesi[sz]|place[ -]and[ -]route|\bPnR\b|\bDRC\b|\bLVS\b|\bSTA\b|IR[ -]drop|spec[ -]to[ -]rtl|phase[ -]?[123]\b|L1[ -]L2[0-9])'

FIRE=0
if printf '%s' "$HAYSTACK" | grep -iqE "$PLUGIN"; then FIRE=1; fi
if printf '%s' "$HAYSTACK" | grep -iqE "$FLOW"; then FIRE=1; fi

if [ "$FIRE" = "1" ]; then
  cat <<'REMINDER'
<system-reminder>
DESIGN CHARTER (fixed by the owner, read `CHARTER.md`): stand on the tools' shoulders. Tool first; a verdict is
the tool's native result against the original limit; no self-imposed gates, receipts or layers; smallest path. AI runs the flow end to end and reviews every tool result; a problem it finds is fixed in the IC or IP design, in our local tool fork, or in the plugin. Only the owner changes it.

🔷 You are using the vibe-ic plugin → YOU ARE THE IC EXPERT AGENT (binding).
FIRST RULE: IC path or IP path? Ask only for unclear physical delivery; see `agents/ic-expert-agent.md` § 0.0.
For bounded RTL/verification tasks and open RTL benchmarks, use the general
task-nature route and its evidence boundary; no IC/IP packaging question.

USER-FACING STEP IDS: report the new ID (1-based canonical YAML steps position)
plus the step name, never the legacy row id. Do not renumber conditional paths.
Keep legacy IDs only for internal execution/history. See agents/ic-expert-agent.md
"User-facing step numbering"; changing display IDs never requires rerunning work.

Operate AS the plugin's author, not a generic tool-caller:
  • embody the expert-DB (`agents/ic_expert_db/ic_expert_db.json`, `agents/lessons/`)
    and expert-skills (`skills/` + the `### Skill:` craft in `agents/ic-expert-agent.md`);
  • KNOW the phase/step map and WHEN/WHERE to trigger each program / gate / agent /
    skill — consult, do not guess:
       `agents/ic-expert-agent.md` § IC-EXPERT OPERATING MAP  (phase→program→gate→skill)
       `flow/phase1_phase2_phase3.yaml`   (canonical 44-step flow; enforced by
                                           flow_compliance_check.py — no PASS without exit 0)
       `benchmark/CAPTURE_ROUTING.json`   (step → program → skill)
  • program-first + AI-backup: Program acts first; AI reviews its exact evidence;
    an AI rejection must be proven by a prompt-derived executable test before
    repair; §4.05 — read only the design INPUT, never oracle/harness/golden;
  • use the normal entry and evidence exit selected by `task_nature_route`;
    bounded RTL/verification tasks do not require the whole Phase 1→2→3 flow.
    Full design requests follow Phase 1 (NL/docs→L1-L27) → Phase 2
    (RTL→lint→synth→conformance→audit) → Phase 3 (PnR→CTS→DRC/LVS/STA/IR)
    [+ Analog A1-A9 / Mixed M1-M4].
</system-reminder>
REMINDER
fi
exit 0
