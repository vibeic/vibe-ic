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
gh issue list --repo "$REPO" --state closed \
  --search "ORGANIC author:@me" \
  --label "core-closed" \
  --json number,title,labels,updatedAt,author \
  --limit 30 \
  | jq '[ .[] | select( any(.labels[]?; .name == "field-verified") | not ) ]'
