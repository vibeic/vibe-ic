#!/usr/bin/env bash
# aggregate_order_audit.sh — the whole-selection pytest session, off the landing
# gate's critical path.
#
# WHAT THIS ANSWERS, AND WHY NOTHING ELSE DOES
# ============================================
# One pytest process over the WHOLE selection preserves the order/global-state
# semantics of the command this repo's per-file driver replaced. It is the only
# thing that can see a failure which appears when file A runs before file B. The
# per-file path -- however wide, however parallel -- runs each file alone and is
# blind to that class by construction.
#
# WHY IT IS NO LONGER IN EVERY ROUND, measured 2026-08-18:
#   before the reader fix   362 s  -> AGGREGATE_NORECORD, ZERO cases recorded
#   after  the reader fix  3198 s  -> AGGREGATE_COMPLETE, 3477 cases, 4 red
# The 362 s was never cheap. It was a healthy run killed at 20% by its own progress
# reader (a single EMPTY LINE in the relay was treated as a protocol violation, and
# protocol failure is absorbing, so the stall clock froze and the watchdog fired).
# Fixing the reader did not make the aggregate slow -- it revealed what it always
# cost. 3198 s against a 600 s target for a complete landing round is not a tuning
# problem; it does not fit, at any width, because one process is one process.
#
# WHEN IT RUNS: ON A MINOR VERSION BUMP, NOT ON A CLOCK
# ======================================================
# A patch bump (1.10.66 -> 1.10.67) does not run it. A MINOR bump (1.10.x -> 1.11.0)
# does, and refuses the bump if it fails.
#
# A version boundary is a better trigger than a schedule for one reason: it cannot
# be forgotten. "Run this nightly" needs something to remember; a minor bump is
# something a human is already doing deliberately, and the audit rides on that act.
# It also bounds the exposure in the unit that matters -- a cross-file regression can
# live for at most ONE MINOR SERIES, never for "however long since anyone last ran
# the script".
#
# THE TRADE, STATED RATHER THAN HIDDEN
# ====================================
# A landing round no longer asks the order/global-state question. It is asked HERE
# instead, on a cadence the project can afford. That is a real reduction in what a
# LANDING checks, and it is written down here so nobody has to rediscover it:
#   * a cross-file/order regression can now reach main and be caught on the next
#     audit run rather than at the gate;
#   * the window is ONE MINOR SERIES. Shorten it by cutting minors more often,
#     never by pretending the gap is not there.
# The alternative that was rejected: keep it in every round and accept 53 minutes.
# The alternative that was NOT taken: delete it, which is what a broken check
# already looks like.
#
# IT REFUSES RATHER THAN PASSES when it cannot answer -- rc 2. A run that could not
# look has not looked.
#
# USAGE
#   tools/ci/aggregate_order_audit.sh [--base REF] [--repo DIR]
# EXIT
#   0  the whole-selection session completed and found nothing new
#   1  it completed and found failures
#   2  NOT DETERMINED -- it could not produce a record. Never a pass.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE="${GATEKEEPER_BASE:-origin/main}"
REQUIRE_MINOR=0
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="$2"; shift 2 ;;
    --require-minor-bump) REQUIRE_MINOR=1; shift ;;
    --repo) REPO="$2"; shift 2 ;;
    -h|--help) sed -n '1,45p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
PLUGIN="$REPO/vibe-ic-marketplace/plugins/vibe-ic"
_plugin_version() { # $1 = git ref, or HEAD-of-worktree when empty
  if [ -n "${1:-}" ]; then
    git -C "$REPO" show "$1:vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json" 2>/dev/null
  else
    cat "$PLUGIN/.claude-plugin/plugin.json" 2>/dev/null
  fi | grep -aoE '"version"[[:space:]]*:[[:space:]]*"[0-9.]+"' | grep -aoE '[0-9]+\.[0-9]+\.[0-9]+' | head -1
}
[ -d "$PLUGIN" ] || { echo "[NOT DETERMINED] no plugin tree at $PLUGIN" >&2; exit 2; }

# ── IS THIS A MINOR BUMP? ────────────────────────────────────────────────────
# Compared against the BASE's version, not against a remembered one: a stored
# "last audited version" is another thing that can go stale, and this check must not
# depend on anything but the two trees in front of it.
if [ "$REQUIRE_MINOR" = 1 ]; then
  NEWV="$(_plugin_version "")"; OLDV="$(_plugin_version "$BASE")"
  if [ -z "$NEWV" ] || [ -z "$OLDV" ]; then
    # UNREADABLE IS NOT "NOT A MINOR BUMP". If we cannot tell, we run the audit --
    # the expensive direction is the safe one here, because skipping it silently is
    # exactly how a check stops existing.
    echo "aggregate_order_audit: version unreadable (new='${NEWV:-?}' base='${OLDV:-?}') — auditing anyway"
  else
    NMIN="${NEWV%.*}"; OMIN="${OLDV%.*}"
    if [ "$NMIN" = "$OMIN" ]; then
      echo "aggregate_order_audit: SKIPPED — $OLDV -> $NEWV is a patch bump."
      echo "  The whole-selection order/global-state question is asked on MINOR bumps"
      echo "  (e.g. ${OMIN}.x -> $(echo "$OMIN" | awk -F. '{print $1"."$2+1}').0), not on every landing."
      exit 0
    fi
    echo "aggregate_order_audit: MINOR bump $OLDV -> $NEWV — auditing."
  fi
fi

SEL="$(mktemp -t agg_sel.XXXXXX)"
JUNIT="$(mktemp -t agg_junit.XXXXXX)"
trap 'rm -f "$SEL"' EXIT

( cd "$PLUGIN" && python3 programs/ci_targeted_test_select.py --base "$BASE" ) > "$SEL" 2>/dev/null
N="$(wc -l < "$SEL")"
if [ "${N:-0}" -eq 0 ]; then
  # AN EMPTY SELECTION IS NOT A CLEAN RUN. It is a question that was never asked,
  # and this script's whole reason to exist is that such a thing must not read as
  # an answer.
  echo "[NOT DETERMINED] the selection is EMPTY — nothing was asked, so nothing was" >&2
  echo "  answered. Check --base: '$BASE'." >&2
  exit 2
fi
echo "aggregate_order_audit: $N file(s), one pytest process, base=$BASE"

START="$(date +%s)"
out="$( cd "$PLUGIN" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 programs/pytest_per_file_junit.py \
        --selection "$SEL" --junit "$JUNIT" \
        --stall-after "${AGG_FILE_STALL_AFTER:-300}" \
        --aggregate-check --aggregate-only \
        --aggregate-stall-after "${AGG_STALL_AFTER:-300}" \
        --fallback-jobs 8 --fallback-rescue-jobs 32 \
        -- python3 -m pytest -q -p pytest_timeout -p no:cacheprovider \
           -m "not audit_63x9" --timeout=180 --timeout-method=thread 2>&1 )"
rc=$?
WALL=$(( $(date +%s) - START ))
printf '%s\n' "$out" | tail -4

if printf '%s\n' "$out" | grep -qa 'AGGREGATE_NORECORD'; then
  echo "[NOT DETERMINED] the aggregate session produced no record after ${WALL}s." >&2
  echo "  This is the failure mode this audit exists to detect, not to tolerate:" >&2
  echo "  a session that recorded nothing has answered nothing." >&2
  rm -f "$JUNIT"; exit 2
fi

if [ -s "$JUNIT" ]; then
  python3 "$REPO/tools/ci/print_junit_reds.py" "$JUNIT" 2>&1 | sed 's/^/  /'
fi
echo "aggregate_order_audit: ${WALL}s, rc=$rc, junit kept at $JUNIT"
exit "$rc"
