#!/usr/bin/env bash
# tools/ci/_published_cell_corpus.sh — the populations the per-cell loops
# iterate, each named for the predicate it actually applies. vibe-ic#1075.
#
# WHY THIS FILE EXISTS
# ====================
# `repo_hygiene_gates.sh` drove THREE per-cell gates from ONE producer —
# published cells carrying a routed DEF. For `macro OBS not crossed` that
# producer is not merely a narrow selector, it selects on the wrong half of a
# two-part predicate the gate's own declaration comment states:
#
#     Runs over every published cell that has both a routed DEF and a macro LEF
#
# MEASURED at `4b22e36ea`, that intersection is EMPTY:
#
#     cells with a routed DEF : 1   (spm/v1.5.58_ihp-sg13g2)
#     cells with a tracked LEF: 3
#     INTERSECTION            : 0
#
# So the one cell the loop selected fails the unstated half, and the checker
# says so and returns 2:
#
#     [CANNOT DETERMINE] macro_obs_geometry_intersect: no macro LEF found.
#     A run with no macro LEF is not a run with no obstruction — it is one
#     this gate could not read. NOT a pass.
#
# That rc 2 is CORRECT. The defect is one level up: the gate occupied a slot in
# the declared-gate denominator and could never produce a verdict, and its only
# wiring in the script was that loop. A declared gate that cannot answer reads,
# to anyone counting, as a gate — which is the same shape as a check that lies,
# arriving through the SELECTOR rather than through the check.
#
# Selecting it on the intersection its comment declares turns a permanent
# NOT_CHECKED into a disclosed zero: `gate_dispatch_over` already prints, for
# an expansion of 0,
#
#     loop corpus "..." expanded over 0 item(s) — it declared 0 gate(s) and
#     NOTHING was checked over it; no gate in this run reports that, because
#     none exists
#
# which is the honest statement of the same fact, and the one case #957 built
# that branch for.
#
# WHAT THIS DELIBERATELY DOES NOT DO
# ==================================
# It does not change the corpus, and it does not touch the OTHER two gates in
# that loop. `drc_vacuous_pass_check` and `step_internal_fail_bubble_up_check`
# are also selected by a predicate that is not their input (#1075 measures
# both), but re-pointing THEM changes verdicts on published bytes rather than
# only the denominator — 14 findings, whose adjudication as defects-to-fix
# versus baseline-to-record is a judgement this file cannot make and must not
# smuggle in beside a wiring repair. They keep the routed-DEF producer, and
# #1075 stays open for them.
#
# WHY A SOURCED LIBRARY AND NOT AN INLINE `git ls-files`
# ======================================================
# Same reason `_gate_dispatch.sh` is one: a test can source THIS file and drive
# the REAL producer over a throwaway repository, instead of a fixture copy of
# the pathspec that would drift from the one that actually runs in CI.
#
# `git ls-files` and never a disk glob, preserving the property the loop was
# given in 2026-08-04: the denominator is a fact about the COMMIT, identical in
# a used checkout, a fresh clone and a scratch worktree. A working-directory
# glob once took the declared-gate count from 68 to 169 and produced 13 FAILs
# about run leftovers rather than about the commit.
#
# chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.

#: The relative path a published cell's routed DEF occupies. Written once here
#: rather than at each call site, because the two producers below must agree on
#: it — the intersection one derives a cell root by stripping it.
PUBLISHED_ROUTED_DEF_REL="phase3/stage3/pnr/routed.def"

#: Pathspec for the routed DEFs themselves. `ic/<ic>/<run>/` is depth-4 and is
#: the shape the published cells use; #1075 records that three tracked
#: `phase3/stage3/pnr/` trees sit at depth 3 and can never match. That is a
#: SECOND, independent narrowing which this change does not address — widening
#: it would add cells to every one of these gates at once, which is the
#: verdict-changing move held back above.
PUBLISHED_CELL_DEF_PATHSPEC="benchmark-data/ic/*/*/${PUBLISHED_ROUTED_DEF_REL}"

# Every published cell carrying a routed DEF, as routed-DEF paths.
#
# A producer's exit status is load-bearing: `gate_dispatch_over` reports
# PRODUCER_FAILED and tells the reader the loop covered an unknown fraction of
# its corpus. So a git failure propagates and is never turned into "no items",
# which is the vacuous-empty this repo removes from gates one at a time.
published_cells_with_routed_def() {
  git -C "${ROOT:?ROOT must be set}" ls-files -- "$PUBLISHED_CELL_DEF_PATHSPEC"
}

# Every published cell carrying a routed DEF **and** at least one tracked LEF.
#
# The gate's real input is narrower still — `macro_obs_geometry_intersect_check`
# reads `**/*.lef` and counts only those that DECLARE A MACRO. This producer
# deliberately stops at "a LEF is tracked in this cell" and does not parse:
# a producer that opened files to decide the corpus would be doing the gate's
# work, and a disagreement between the two would then be invisible — the gate
# would simply not run. Stopping short means a cell whose LEF declares no macro
# still reaches the gate and is answered with the gate's own rc 2, which is a
# state a reader can see.
published_cells_with_routed_def_and_macro_lef() {
  local defs def cell
  defs="$(published_cells_with_routed_def)" || return $?
  [ -n "$defs" ] || return 0
  while IFS= read -r def; do
    [ -n "$def" ] || continue
    cell="${def%/${PUBLISHED_ROUTED_DEF_REL}}"
    # `-- "$cell/*.lef"`: a git pathspec `*` crosses `/`, so this is every
    # tracked LEF anywhere beneath the cell — the same reach the checker's own
    # `**/*.lef` discovery has.
    if [ -n "$(git -C "$ROOT" ls-files -- "$cell/*.lef")" ]; then
      printf '%s\n' "$def"
    fi
  done <<<"$defs"
  # Explicit, and NOT load-bearing today — measured rather than assumed. I
  # first wrote that without it the false `[ -n ... ]` on a last cell with no
  # LEF would leak out and `gate_dispatch_over` would announce an empty
  # intersection as a FAILED PRODUCER. Deleting the line and driving the real
  # function over a DEF-only corpus returns rc 0 anyway: an `if` whose
  # condition is false and which has no `else` is itself 0 in bash, so the
  # loop's status is 0 regardless.
  #
  # It stays because the distinction it protects is one `gate_dispatch_over`
  # acts on — a non-zero producer is reported as covering an unknown fraction
  # of its corpus — and the next command appended after this loop would
  # reinstate the leak silently. It is insurance, and the comment says so
  # rather than claiming a bug it does not currently prevent.
  return 0
}
