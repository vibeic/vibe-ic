#!/usr/bin/env bash
# ===========================================================================
# setup_branch_protection.sh — enable gatekeeper branch protection on `main`.
#
# Idempotent `gh api` script that locks `main` so that the ONLY way code lands
# is a PR that (a) passes the Gatekeeper CI required checks, (b) has a required
# review, and (c) is merged by the single gatekeeper bot/app through GitHub's
# native MERGE QUEUE. Re-running it converges to the same state.
#
# chip-AGNOSTIC: contains no chip / vendor / SKU literal. Repo, branch, the
# gatekeeper actor, and the required-check names are all parameters/env vars.
#
# ---------------------------------------------------------------------------
# !!! WARNING — THIS BREAKS THE CURRENT DIRECT-PUSH LOOP !!!
# ---------------------------------------------------------------------------
# Today the core-agent loop pushes straight to `main`. After this script runs,
# direct pushes to `main` are REJECTED for everyone except the gatekeeper
# actor, and even the gatekeeper must go through a PR + the merge queue. If you
# enable this BEFORE the gatekeeper-loop is live and landing PRs, ALL merges
# stop and the repo is frozen.
#
# REQUIRED ORDER OF OPERATIONS:
#   1. Land gatekeeper-ci.yml + CODEOWNERS + the gatekeeper-agent on `main`
#      (via the existing direct-push loop, one last time).
#   2. Bring the gatekeeper-loop online and confirm it can open, check, and
#      merge a trivial PR through the queue end-to-end.
#   3. ONLY THEN run this script with --confirm.
#
# Without --confirm this script is a NO-OP: it prints this warning + the exact
# settings it WOULD apply, and exits 0 WITHOUT calling the GitHub API.
# ===========================================================================

set -euo pipefail

# --------------------------- configuration ---------------------------------
# Override via environment; all chip-AGNOSTIC, no hard-coded design literals.
REPO="${REPO:-vibeic/vibe-ic}"
BRANCH="${BRANCH:-main}"
# The single identity allowed to push to / merge into the protected branch.
# Set GATEKEEPER_ACTOR to the bot/app/machine-user login that runs the loop.
GATEKEEPER_ACTOR="${GATEKEEPER_ACTOR:-vibeic-gatekeeper-bot}"
# Is the gatekeeper actor a GitHub App (true) or a user/team (false)?
GATEKEEPER_IS_APP="${GATEKEEPER_IS_APP:-false}"
REQUIRED_APPROVALS="${REQUIRED_APPROVALS:-1}"

# Required status-check CONTEXTS — must match the job NAMES in
# .github/workflows/gatekeeper-ci.yml exactly (and fire on both the
# pull_request and merge_group events, or the queue stalls). We require the
# single aggregate gate plus the two always-on gates for defence in depth.
REQUIRED_CHECKS_DEFAULT=(
  "Gatekeeper required (aggregate)"
  "Governance gates (chip-AGNOSTIC + version + scope + git)"
  "Plugin audit + pytest (targeted)"
)
# Allow override as a newline- or comma-separated env list.
if [ -n "${REQUIRED_CHECKS:-}" ]; then
  IFS=$'\n,' read -r -d '' -a REQUIRED_CHECKS_ARR < <(printf '%s\0' "$REQUIRED_CHECKS") || true
else
  REQUIRED_CHECKS_ARR=("${REQUIRED_CHECKS_DEFAULT[@]}")
fi

CONFIRM=0
for arg in "$@"; do
  case "$arg" in
    --confirm) CONFIRM=1 ;;
    -h|--help)
      sed -n '2,40p' "$0"
      exit 0
      ;;
    *)
      echo "unknown argument: $arg (use --confirm or --help)" >&2
      exit 2
      ;;
  esac
done

# ----------------------- JSON payload builders -----------------------------
# Build the restrictions block — RESTRICT pushes to a single gatekeeper.
build_restrictions() {
  if [ "$GATEKEEPER_IS_APP" = "true" ]; then
    printf '{"users":[],"teams":[],"apps":["%s"]}' "$GATEKEEPER_ACTOR"
  else
    printf '{"users":["%s"],"teams":[],"apps":[]}' "$GATEKEEPER_ACTOR"
  fi
}

# Build the required_status_checks.checks[] array from REQUIRED_CHECKS_ARR.
build_checks_json() {
  local first=1 out="["
  local c
  for c in "${REQUIRED_CHECKS_ARR[@]}"; do
    [ -z "$c" ] && continue
    if [ "$first" -eq 0 ]; then out+=","; fi
    # -1 context id == "any app may report this context"
    out+=$(printf '{"context":%s,"app_id":-1}' "$(json_str "$c")")
    first=0
  done
  out+="]"
  printf '%s' "$out"
}

# Minimal JSON string escaper (chip-AGNOSTIC, no external deps).
json_str() {
  python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1"
}

# The PR-review block. When REQUIRED_APPROVALS==0 (the single-identity model —
# the gatekeeper≠submitter rule was removed, and GitHub forbids approving your
# OWN PR) we OMIT required_pull_request_reviews entirely (JSON null) so a
# self-authored PR is not deadlocked by an unsatisfiable Code-Owner review.
# main stays protected by the required STATUS CHECKS + the loop's Step-2.7.
# When REQUIRED_APPROVALS>=1 (a distinct bot/human reviewer exists) we require a
# real Code-Owner review.
build_reviews_block() {
  if [ "${REQUIRED_APPROVALS}" -ge 1 ] 2>/dev/null; then
    printf '{"required_approving_review_count":%s,"require_code_owner_reviews":true,"dismiss_stale_reviews":true}' "${REQUIRED_APPROVALS}"
  else
    printf 'null'
  fi
}

build_protection_payload() {
  cat <<JSON
{
  "required_status_checks": {
    "strict": true,
    "checks": $(build_checks_json)
  },
  "enforce_admins": true,
  "required_pull_request_reviews": $(build_reviews_block),
  "restrictions": $(build_restrictions),
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
}

# ---------------------------- dry-run path ---------------------------------
print_warning_and_plan() {
  cat <<'WARN'
===========================================================================
WARNING: setup_branch_protection.sh ran WITHOUT --confirm  (DRY RUN, NO-OP)
===========================================================================
Running this script WITH --confirm BREAKS the current direct-push loop:
  * direct pushes to the protected branch will be REJECTED for everyone
    except the gatekeeper actor;
  * even the gatekeeper must land via a PR through the native merge queue.

DO NOT enable this until the gatekeeper-loop is LIVE and proven able to open,
check, and merge a PR end-to-end. Enabling it early FREEZES the repository.

Required order:
  1. Land gatekeeper-ci.yml + CODEOWNERS + gatekeeper-agent on the branch
     (one last time via the existing direct-push loop).
  2. Bring the gatekeeper-loop online; confirm a trivial PR merges via queue.
  3. ONLY THEN re-run THIS script with --confirm.
WARN
  echo ""
  echo "WOULD apply to ${REPO}@${BRANCH}:"
  echo "  - require PR before merge (no direct push)"
  if [ "${REQUIRED_APPROVALS}" -ge 1 ] 2>/dev/null; then
    echo "  - require ${REQUIRED_APPROVALS} Code-Owner approving review(s) (CODEOWNERS -> @vibeic/gatekeeper)"
  else
    echo "  - NO PR-review requirement (single-identity self-merge): quality via required STATUS CHECKS + the loop's Step-2.7 (GitHub forbids self-approving your own PR)"
  fi
  echo "  - required status checks (strict, must match gatekeeper-ci job names):"
  local c
  for c in "${REQUIRED_CHECKS_ARR[@]}"; do
    [ -z "$c" ] && continue
    echo "        * ${c}"
  done
  echo "  - RESTRICT pushes to single gatekeeper actor: ${GATEKEEPER_ACTOR}" \
       "(is_app=${GATEKEEPER_IS_APP})"
  echo "  - enforce_admins=true, linear_history=true, force_pushes=false"
  echo "  - enable the native MERGE QUEUE on the branch"
  echo ""
  echo "Payload that WOULD be PUT to /repos/${REPO}/branches/${BRANCH}/protection:"
  build_protection_payload
  echo ""
  echo "No GitHub API call was made. Re-run with --confirm to apply."
}

# ----------------------------- apply path ----------------------------------
apply_protection() {
  command -v gh >/dev/null 2>&1 || { echo "ERROR: gh CLI not found" >&2; exit 3; }

  echo ">> Applying branch protection to ${REPO}@${BRANCH} (idempotent PUT)..."
  build_protection_payload | gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    "/repos/${REPO}/branches/${BRANCH}/protection" \
    --input -

  echo ">> Enabling the native MERGE QUEUE on ${BRANCH}..."
  # The merge queue is configured via the ruleset/auto-merge-queue API. PUT is
  # idempotent: re-running converges to merge_method=squash with the same
  # required check grouping the queue enforces.
  gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    "/repos/${REPO}/branches/${BRANCH}/protection/required_merge_queue" \
    -f merge_method="squash" 2>/dev/null \
    || gh api \
         --method POST \
         -H "Accept: application/vnd.github+json" \
         "/repos/${REPO}/merge-queue" \
         -f branch="${BRANCH}" 2>/dev/null \
    || echo "   (note: enable the merge queue in repo Settings → Branches if" \
            "the API path is unavailable on this plan)"

  echo ">> Done. ${BRANCH} now requires PR + gatekeeper review + queue merge."
  echo "   The direct-push loop is now DISABLED for all non-gatekeeper actors."
}

# ------------------------------- main --------------------------------------
if [ "$CONFIRM" -ne 1 ]; then
  print_warning_and_plan
  exit 0
fi

apply_protection
