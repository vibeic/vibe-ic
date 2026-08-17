#!/usr/bin/env bash
# tools/run_campaign_tier.sh — the 63x9 campaign's MATRIX SELF-AUDIT, run as one
# named entry point.
#
# NOTHING SCHEDULES THIS YET, and that is stated first because it is the thing a
# reader most needs to know. This script exists so the material the landing gate
# stopped running is still RUNNABLE and still has one address. WHO runs it, and
# how often, is an OPEN OWNER DECISION — see "THE OPEN QUESTION" below. Do not
# read the existence of this file as an answer to it.
#
# WHAT IT RUNS
# ------------
# Exactly the pytest nodes declared in
# `vibe-ic-marketplace/plugins/vibe-ic/programs/landing_excluded_corpus.py`,
# selected by the one marker that file owns. It does not carry its own list:
# a second roster is how the two halves drift, and the drift direction is
# always "the campaign tier quietly stopped running something".
#
#     tools/run_campaign_tier.sh              run them
#     tools/run_campaign_tier.sh --list       what they are, and why each left
#     tools/run_campaign_tier.sh --audit      is the declaration still true
#
# WHY THESE LEFT THE LANDING GATE (owner directive, 2026-08-17)
# ------------------------------------------------------------
# Three different things had grown into one tier:
#
#   (i)   a FLOW GATE      — fires when a flow step runs. The flow runs it.
#                            Not this script's business, and not the landing
#                            gate's either.
#   (ii)  a LANDING REGRESSION — "did this change break something that used to
#                            work". Stays in `tools/gatekeeper-land.sh`.
#   (iii) a MATRIX SELF-AUDIT — "is the published headline figure in
#                            `matrix_63x8/README.md` still consistent with what
#                            the live suite counts". THIS SCRIPT.
#
# A stale published figure breaks nothing. It makes one number out of date,
# which blocks the campaign, not the push. `tools/ci/repo_hygiene_gates.sh` had
# already drawn that line for its own `63x8 census fresh` gate (owner decision
# 2026-08-16); this is the same line drawn through the two pytest arms.
#
# EVERY FILE INVOLVED IS MIXED, so nothing was moved wholesale. The regression
# half of each stayed: the `--check` that can still go red, the CLI driven in
# both directions over a synthetic corpus, the waiver registry whose citations
# must still resolve, the six `verdict_moved()` unit tests. The unit of
# separation is the pytest NODE and the record is the registry, not the marker.
#
# THE OPEN QUESTION — WHAT ENFORCES THE PUBLISHED CENSUS
# ------------------------------------------------------
# `matrix_63x8/README.md` publishes "504 cells: N ENFORCED, N CONTRADICTED,
# N WAIVED, N NA". It has gone stale TWICE with nothing noticing: once
# hand-written and four rows adrift from the live suite, once generated at the
# wrong vintage so main published 28 CONTRADICTED / 12 NA while its own live
# join produced 29 / 11. The reason it was wired into a merge path in the first
# place is on the record: "a generated artefact whose freshness check runs in no
# merge path will go stale again, and next time it may not be a number anyone
# re-derives."
#
# So this is not a solved problem, it is a MOVED one, and the options carry
# measured costs rather than opinions:
#
#   (a) do nothing — 0 s, and it is exactly the condition under which the figure
#       went stale twice.
#   (b) keep only the cheap half in a merge path —
#       `gen_matrix_63x8_census.py <root> --check-figures`, 1.06 s, guards 57
#       anchored figures across 33 corpus files and PRINTS its own coverage
#       (135/382 = 35%), i.e. it is honest about what it does not guard.
#   (c) keep the full `--check` in a merge path — 135.8-241.9 s measured on this
#       fleet, and it is BLIND to the defect currently outstanding: it compares
#       its own regenerated block with the committed block, so both agree while
#       the six published columns sum to 451 of 504 cells.
#   (d) schedule THIS script off the merge path on a fleet host and put the
#       verdict where a human reads it — no landing cost, and nothing blocks a
#       merge that makes the figure worse.
#   (e) change what the published figure MEANS so it can be derived without the
#       504-cell outcome run. That is a correctness decision about the headline,
#       not a scheduling one.
#
# GitHub Actions is NOT an option and this was re-verified rather than assumed:
# there is no `.github/workflows` in this repo, only `.github/workflows-disabled/`,
# whose README records an ACCOUNT-level Actions block ("HTTP 422: Actions has
# been disabled for this user"), appeal ticket 4613114 rejected, and "a
# self-hosted runner does not help: scheduling is the blocked layer, not
# execution".
#
# TWO THINGS THIS SCRIPT WILL REPORT RED, TODAY, FOR REASONS NO PR CAUSED
# -----------------------------------------------------------------------
# Stated up front so a first run is not mistaken for a regression this
# separation introduced:
#
#   * the nine `tools/test_d9_flow_gate_reality.py` page tests need
#     `benchmark-data/evaluation/d9_flow_gate_reality/d9_reality.json`, which
#     left this repo in c5d7f2d00. They fail with FileNotFoundError until the
#     corpus pointer is restored or they move to the repo that owns the JSON.
#   * `test_the_published_total_equals_the_live_census` fails with "the
#     published columns account for 451 cells but the matrix has 504", and the
#     504-cell join reports 53 cells whose predicate never ran because
#     dimensions 3 and 7 skip without the campaign run trees that left with
#     benchmark-data.
#
# Both are findings ABOUT THE PUBLISHED ARTEFACTS. Neither is a reason to stop
# running this; they are the reason it exists.
#
# WHAT IS DELIBERATELY NOT HERE
# -----------------------------
# `test_matrix_d3_outputs_produced.py`, `test_matrix_d4_criteria_match.py`,
# `test_matrix_d6_skip_discipline.py`, `test_matrix_d7_outputs_list_complete.py`
# and `test_matrix_d8_missing_caught.py` were classified OWNER DECISION, not
# "not a regression", so they were left in the landing gate. d1/d2/d5 were
# examined and cleared as landing regressions and stay for a positive reason.
# `tools/test_d9_content_census.py` and `tools/test_d9_corpus_baseline.py` are
# genuine unit regressions over instruments that live in THIS repo; the argument
# for moving them is layering, not regression, and nobody has ruled on it.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PLUGIN="$ROOT/vibe-ic-marketplace/plugins/vibe-ic"
REG="$PLUGIN/programs/landing_excluded_corpus.py"

case "${1:-}" in
  --list)  exec python3 "$REG" --repo "$ROOT" --list ;;
  --audit) exec python3 "$REG" --repo "$ROOT" --audit ;;
  "")      ;;
  *) echo "usage: tools/run_campaign_tier.sh [--list|--audit]" >&2; exit 2 ;;
esac

SELECT="$(python3 "$REG" --select-expr)" || {
  echo "REFUSED: the exclusion registry did not answer, so this tier does not"
  echo "         know what it owns. Running nothing is not the same as running"
  echo "         a clean set." >&2
  exit 2
}

# THE DECLARATION IS PRINTED BEFORE THE RUN, not after. A reader who only sees
# the tail must still be able to tell which nodes this tier is responsible for.
python3 "$REG" --repo "$ROOT" --list || exit 2

FAILED=0

# ── the plugin arm ─────────────────────────────────────────────────────────
# Same session shape as the landing gate's targeted arm — the autoload pin, the
# timeout plugin, the same harness bound — so a red here means the same thing it
# would have meant there. `--timeout=180` does NOT bind the two census items:
# both carry `@pytest.mark.timeout(0)` in their own source, which is where that
# decision already lived.
mapfile -t PLUGIN_FILES < <(python3 "$REG" --repo "$ROOT" \
    --paths vibe-ic-marketplace/plugins/vibe-ic/programs/tests/ \
    | sed 's#^vibe-ic-marketplace/plugins/vibe-ic/##')
if [ "${#PLUGIN_FILES[@]}" -eq 0 ]; then
  echo "REFUSED: the registry declares no plugin-tree node; an empty arm is"
  echo "         not a green one." >&2
  exit 2
fi
echo "=== campaign tier: plugin arm (${#PLUGIN_FILES[@]} file(s), -m $SELECT) ==="
( cd "$PLUGIN" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
    -q -p pytest_timeout -p no:cacheprovider \
    --timeout=180 --timeout-method=thread \
    -m "$SELECT" "${PLUGIN_FILES[@]}" ) || FAILED=1

# ── the repo-tools arm ─────────────────────────────────────────────────────
mapfile -t TOOL_FILES < <(python3 "$REG" --repo "$ROOT" --paths tools/)
if [ "${#TOOL_FILES[@]}" -eq 0 ]; then
  echo "REFUSED: the registry declares no tools-tree node; an empty arm is not"
  echo "         a green one." >&2
  exit 2
fi
echo "=== campaign tier: repo-tools arm (${#TOOL_FILES[@]} file(s), -m $SELECT) ==="
( cd "$ROOT" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
    -q -p pytest_timeout --timeout=180 --timeout-method=thread \
    -m "$SELECT" "${TOOL_FILES[@]}" ) || FAILED=1

# ── the declaration itself ─────────────────────────────────────────────────
# Last, and blocking: a tier that runs a stale list is worse than one that
# refuses. This is the same audit the landing gate runs, asked here so the two
# tiers cannot disagree about what the boundary is.
echo "=== campaign tier: the declaration ==="
python3 "$REG" --repo "$ROOT" --audit || FAILED=1

if [ "$FAILED" -eq 0 ]; then
  echo "=== campaign tier: PASS ==="
else
  echo "=== campaign tier: FAILURES ABOVE — these are findings about PUBLISHED"
  echo "    artefacts, and no landing is blocked by them. See the header for the"
  echo "    two that are red today for reasons no PR caused. ==="
fi
exit "$FAILED"
