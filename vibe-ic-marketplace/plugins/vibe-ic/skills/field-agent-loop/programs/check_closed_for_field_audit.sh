#!/usr/bin/env bash
# Deterministic rule — run at every field-agent cron tick BEFORE Step 1.
#
# Returns the JSON list of CLOSED ORGANIC issues authored by the current
# `gh` user that carry the `core-closed` label but LACK `field-verified`.
# These are issues the core-agent self-verified + closed; the field-agent
# must AUDIT each one against the REAL benchmark. For each issue:
#   1. Dispatch a fresh verify agent scoped to that issue (real benchmark).
#   2. VERIFIED ok  → gh issue label add `field-verified` (issue STAYS closed).
#                     This is the terminal "do-not-re-audit" marker.
#   3. NOT adequate → gh issue reopen + post counter-evidence comment
#                     + remove `core-closed`  → back to OPEN (core actionable).
#
# Default terminal state = CLOSED (core-self-verified). The field-agent is
# the audit/reopen safety net — this is what prevents a stalled limbo where
# nobody confirms the fix on real silicon.

set -euo pipefail

REPO="${VIBE_IC_BACKLOG_REPO:-reyerchu/AI_IC_design}"

# List CLOSED ORGANIC issues authored by me carrying `core-closed`, then
# filter OUT any that already carry `field-verified` (already audited).
# TITLE AND AUTHOR MATCHED LOCALLY (vibe-ic#554). `--search` routes through
# GitHub's search index, which returns 0 for these repositories regardless of
# content — positive control: `--search "Actions in:title"` returns 0 while
# #550 is open with "Actions" in its title. Here a false 0 reads as "no closed
# fix needs auditing", which is the audit/reopen safety net switching itself
# off silently.
#
# `--limit 30` was the default and is its own version of the same thing: past
# thirty, the ones that fall off read as absent. Raised, and the script refuses
# rather than under-reports if it comes back at the cap.
LIMIT=1000
OUT="$(gh issue list --repo "$REPO" --state closed \
  --label "core-closed" \
  --json number,title,labels,updatedAt,author \
  --limit "$LIMIT")"

if [ "$(printf '%s' "$OUT" | jq 'length')" -ge "$LIMIT" ]; then
  echo "REFUSING: the listing came back at the --limit cap ($LIMIT); the " \
       "result would be a floor, not a list (vibe-ic#554)." >&2
  exit 2
fi

printf '%s' "$OUT" | jq --arg me "$(gh api user -q .login)" '
  [ .[]
    | select(.title | test("ORGANIC"))
    | select(.author.login == $me)
    | select( any(.labels[]?; .name == "field-verified") | not ) ]'
