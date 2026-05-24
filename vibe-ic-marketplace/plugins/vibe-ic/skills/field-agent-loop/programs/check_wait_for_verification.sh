#!/usr/bin/env bash
# Deterministic rule — run at every field-agent cron tick BEFORE Step 1.
#
# Returns the JSON list of OPEN ORGANIC issues authored by the current
# `gh` user with the `wait-for-verification` label. For each issue, the
# field-agent MUST:
#   1. Dispatch a verify agent scoped to that issue.
#   2. On VERIFIED  → gh issue close + remove `wait-for-verification`.
#   3. On NOT VERIF → gh issue comment with counter-evidence
#                      + remove `wait-for-verification`.
#
# Unattended `wait-for-verification` = stalled core-agent slice.
# This rule guarantees the field-agent does not drop the gate.

set -euo pipefail

REPO="${VIBE_IC_BACKLOG_REPO:-reyerchu/AI_IC_design}"

gh issue list --repo "$REPO" --state open \
  --label "wait-for-verification" \
  --search "ORGANIC" \
  --json number,title,labels,updatedAt,author \
  --limit 30
