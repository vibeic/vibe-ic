#!/bin/bash
# phase23_claim_validator.sh — v0.110 Stop-hook STRONG enforcement.
#
# Fires on every assistant turn-end. Quick-rejects 99% of turns (no claim
# regex match). When the assistant claims Phase 2+3 completion, runs
# `phase23_completion_self_audit_check.py` against the active project and
# BLOCKS the turn from ending if audit FAILs — the assistant must address
# the missing canonical steps before the next user-visible turn.
#
# Hook protocol (Claude Code Stop hook):
#   - stdin: JSON event with `transcript_path` (path to JSONL of recent turns)
#   - stdout: optional message injected back into the assistant context
#   - exit 0: allow turn to end
#   - exit 2: block turn end + inject stderr as system message
#
# CLAIM REGEX — case-insensitive matches that trigger the audit:
#   "phase 2+3 complete" / "phase 2+3 done" / "phase 2+3 finished"
#   "design flow complete" / "design flow done"
#   "tape-?out ready" / "ready for fab" / "ready to tape"
#   "all 34 steps pass" / "34/34 pass"
#   Chinese variants: "全部完成" / "全部過了" / "完成 phase 2+3"
#   "phase23 done" / Chinese: "Phase 2+3 通過"
#
# False-positive guard: if the assistant is QUOTING the regex itself (e.g.
# in a discussion about the rule), the audit may misfire. To override for
# legitimate meta-discussion, the assistant can include the phrase
# `[NOT-CLAIMING-COMPLETE]` anywhere in its reply — the validator skips.
#
# JSON parsing uses python3 (universally available on dev hosts) — no jq
# dependency.

set -uo pipefail

# Read hook event JSON from stdin; tolerate missing input.
EVENT_JSON=$(timeout 1 cat 2>/dev/null || echo '{}')
if [[ -z "$EVENT_JSON" ]]; then
  EVENT_JSON='{}'
fi

# Extract transcript_path via python3.
TRANSCRIPT=$(printf '%s' "$EVENT_JSON" | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin); print(d.get("transcript_path","") or "", end="")
except Exception: pass' 2>/dev/null || echo "")

if [[ -z "$TRANSCRIPT" || ! -f "$TRANSCRIPT" ]]; then
  exit 0  # no transcript → can't validate, fail-open
fi

# Pull last assistant message text from JSONL transcript via python3.
LAST_ASSISTANT=$(python3 - "$TRANSCRIPT" <<'PY' 2>/dev/null || echo ""
import json, sys
path = sys.argv[1]
last_text = ""
try:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            # accept either {"role":..., "content":...} or {"type":..., "message": {...}}
            role = ev.get("role") or (ev.get("message") or {}).get("role")
            if role != "assistant": continue
            content = ev.get("content") or (ev.get("message") or {}).get("content")
            if not content: continue
            if isinstance(content, str):
                last_text = content
            elif isinstance(content, list):
                parts = []
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        parts.append(blk.get("text", ""))
                    elif isinstance(blk, str):
                        parts.append(blk)
                last_text = "\n".join(parts)
except Exception:
    pass
print(last_text)
PY
)

if [[ -z "$LAST_ASSISTANT" ]]; then
  exit 0
fi

# Override escape: meta-discussion about the rule itself.
if printf '%s' "$LAST_ASSISTANT" | grep -qF '[NOT-CLAIMING-COMPLETE]'; then
  exit 0
fi

# Regex match for completion-claim phrases (case-insensitive, multilingual).
CLAIM_RE='(phase[ -]?2[+\-]3.*(complete|done|finish|通過|完成))|(design[ -]flow[ -](complete|done))|(tape[ -]?out[ -]?(ready|complete))|(ready[ -]for[ -]fab)|(all[ -]34[ -]steps?[ -]pass)|(34/34[ -]pass)|(phase23[ -](done|complete))|(全部(完成|過了|PASS))'
if ! printf '%s' "$LAST_ASSISTANT" | grep -iqE "$CLAIM_RE"; then
  exit 0  # no claim → allow turn to end
fi

# A claim was made. Find the project_dir.
PROJECT_DIR="${VIBE_IC_PROJECT_DIR:-}"

if [[ -z "$PROJECT_DIR" ]]; then
  PROJECT_DIR=$(printf '%s' "$LAST_ASSISTANT" \
    | grep -oE '/[^[:space:]"`'"'"']+phase2\+3_[a-zA-Z0-9_-]+' \
    | head -1 \
    | sed -E 's,/(rtl|fpga|gds|synth|pnr|dft|generated_docs|gate_reports|FINAL_REPORT\.md).*$,,')
  PROJECT_DIR="${PROJECT_DIR%/}"
fi

if [[ -z "$PROJECT_DIR" ]]; then
  PROJECT_DIR=$(grep -hoE '/[^[:space:]"`'"'"']+phase2\+3_[a-zA-Z0-9_-]+' "$TRANSCRIPT" 2>/dev/null \
    | head -1 \
    | sed -E 's,/(rtl|fpga|gds|synth|pnr|dft|generated_docs|gate_reports|FINAL_REPORT\.md).*$,,')
  PROJECT_DIR="${PROJECT_DIR%/}"
fi

if [[ -z "$PROJECT_DIR" || ! -d "$PROJECT_DIR" ]]; then
  cat >&2 <<EOF
⚠️  Phase 2+3 completion-claim detected, but the validator could not
   auto-locate the project directory. Set VIBE_IC_PROJECT_DIR or include
   the project path in your reply, then re-run the audit manually:

       python3 vibe-ic-d/programs/phase23_completion_self_audit_check.py \\
           <project_dir>

   See CLAUDE.md rule #11. (This warning is not blocking — but if you are
   actually claiming completion, run the audit and paste the output.)
EOF
  exit 0
fi

# Locate the audit gate.
# PORTABILITY: every candidate is derived from THIS script's own location (or an
# explicit env override). Absolute paths under a personal home directory used to
# be listed here; they resolved on one machine only and were dead weight
# everywhere else.
GATE=""
_HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
for candidate in \
  ${VIBE_IC_PROGRAMS_DIR:+"$VIBE_IC_PROGRAMS_DIR/phase23_completion_self_audit_check.py"} \
  "$_HOOK_DIR/../programs/phase23_completion_self_audit_check.py" \
  "$_HOOK_DIR/../../vibe-ic/programs/phase23_completion_self_audit_check.py"
do
  if [[ -f "$candidate" ]]; then
    GATE="$candidate"
    break
  fi
done

if [[ -z "$GATE" ]]; then
  cat >&2 <<EOF
⚠️  Could not locate phase23_completion_self_audit_check.py.
   Plugin install may be incomplete. Cannot enforce 34/34 rule on this turn.
EOF
  exit 0
fi

# Run the gate with a strict timeout.
AUDIT_OUT=$(timeout 120 python3 "$GATE" "$PROJECT_DIR" 2>&1)
AUDIT_RC=$?

if [[ "$AUDIT_RC" == "0" ]]; then
  # Distinguish PASS from PASS_WITH_WAIVERS — both allow turn-end but
  # waivered runs require explicit acknowledgement that deferred steps
  # are NOT pass and must be closed at foundry tapeout review.
  if printf '%s' "$AUDIT_OUT" | grep -q "PASS_WITH_WAIVERS"; then
    # v0.113 (BACKLOG-v10 P0.3): scan THIS reply's text for forbidden
    # phrasing AND require at least one disambiguation phrase. If the
    # reply conflates waivers with PASS, BLOCK turn-end (exit 2) so the
    # agent has to revise before the user sees misleading text.
    FORBIDDEN_RE='(all[ -]34[ -]steps?[ -]pass)|(every[ -]step[ -](pass|done))|(全部[ ]?(PASS|過了|通過))|(production[ -]tapeout[ -]ready)|(ready[ -]for[ -]production[ -]fab)'
    REQUIRED_RE='(DEFERRED)|(waiver)|(PASS_WITH_WAIVERS)|(executed[ ]?PASS)|(deferred[ -]via)|(open[ -]work)|(foundry[ -]sign-?off)|(延後|deferred|延遲)'
    has_forbidden=0
    has_required=0
    if printf '%s' "$LAST_ASSISTANT" | grep -iqE "$FORBIDDEN_RE"; then
      has_forbidden=1
    fi
    if printf '%s' "$LAST_ASSISTANT" | grep -iqE "$REQUIRED_RE"; then
      has_required=1
    fi

    if [[ "$has_forbidden" == "1" ]] && [[ "$has_required" == "0" ]]; then
      cat >&2 <<EOF
⛔ STOP — your reply contains forbidden PASS_WITH_WAIVERS phrasing.

The audit returned PASS_WITH_WAIVERS — the run has DEFERRED step(s) via
waivers.json that are NOT executed and NOT pass. Your reply uses
phrasing like "all 34 steps PASS / every step done / all PASS (zh) /
production tapeout ready" without any disambiguation that ${0##*/} treats
waivers as open work, not as PASS.

REVISE your reply to either:
  (a) replace "all N steps PASS" with the precise form
      "executed PASS = X / (34 − M waivers), M DEFERRED pending
       foundry sign-off review", AND/OR
  (b) explicitly mention the M deferred steps + ticket ids inline.

This is not optional — production-readiness equivalence is the user's
load-bearing question and getting it wrong undoes the audit's purpose.

(If you are truly discussing the rule itself, not making a real claim,
include the literal phrase [NOT-CLAIMING-COMPLETE] anywhere in your
reply.)

Audit detail follows for reference:

$AUDIT_OUT
EOF
      exit 2  # BLOCK turn-end
    fi

    cat <<EOF
⚠️ phase23_completion_self_audit_check PASS_WITH_WAIVERS — claim allowed BUT REQUIRES CAVEAT.

$AUDIT_OUT

This run has DEFERRED step(s) via waivers.json — they are NOT executed
and NOT pass. They are open work for foundry tapeout review.

When you describe this run to the user, do NOT say "all 34 steps PASS".
Say "N steps PASS, M steps DEFERRED via waiver pending foundry sign-off".

If your reply already conflates waivers with PASS, REVISE before
ending the turn. The foundry sign-off equivalence is the user's
load-bearing question — getting it right matters more than the audit
exit code.
EOF
    exit 0
  fi
  cat <<EOF
✅ phase23_completion_self_audit_check PASS (no waivers) — claim allowed.
   project: $PROJECT_DIR
   Every canonical step executed and verified.
EOF
  exit 0
fi

# Audit FAIL — BLOCK the turn from ending. Exit 2 + stderr message gets
# injected back to the assistant.
cat >&2 <<EOF
⛔ STOP — Phase 2+3 completion claim BLOCKED by v0.110 strong-enforcement hook.

You said something that pattern-matches "Phase 2+3 complete / done / passed (zh) / tape-out ready / all-passed (zh)" but:

$AUDIT_OUT

This is the SOLE acceptance criterion (CLAUDE.md rule #11). Your claim is
not valid until \`flow_compliance_check.py --strict\` returns
\`Overall: PASS\` with \`non-waived PASS = 34/34\`.

Required next actions:
  1. Identify the missing / failing canonical steps (see audit output).
  2. Either complete them, OR add a justified entry to
     $PROJECT_DIR/waivers.json (see vibe-ic/flow/phase1_phase2_phase3.yaml
     for the schema).
  3. Re-run:
         python3 vibe-ic-d/programs/phase23_completion_self_audit_check.py \\
             $PROJECT_DIR
  4. Once it returns PASS, paste the last 10 lines into FINAL_REPORT.md
     and you may then claim completion.

If you genuinely need to discuss the rule itself (meta-conversation, not
a real claim), include the override phrase \`[NOT-CLAIMING-COMPLETE]\`
in your reply and the validator will skip.
EOF

exit 2  # Claude Code Stop-hook: exit 2 blocks turn-end + injects stderr
