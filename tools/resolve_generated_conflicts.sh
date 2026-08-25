#!/usr/bin/env bash
# resolve_generated_conflicts.sh — resolve a stopped merge/rebase whose only
# conflicts are in GENERATED files, by regenerating them from the merged tree.
#
# WHY
# ---
# `programs/INDEX.md` is generated in full by `tools/gen_programs_index.py`
# (`--check` fails CI on drift), so it has no hand-authored content. Its Stats
# block carries three tree-wide COUNTERS:
#
#     - **Total programs (excluding helpers / shims):** 1079
#     | `any` | 1070 |
#     ### `any` (1070 programs)
#
# Every branch that adds a program rewrites all three, so branches collide on the
# COUNTERS, not on the entries — two programs at opposite ends of the alphabet
# conflict exactly as reliably as neighbours. Measured 2026-08-13 against
# `24ff95307`: of 30 CONFLICTING open PRs, **26 conflict on INDEX.md and 25 on
# INDEX.md and nothing else** (vibe-ic#1431, vibe-ic#1363).
#
# Resolving that is the same three commands every time, because a generated file
# has no side worth keeping. This script is the entry point for those commands,
# with the checks that make it safe to run without reading the diff.
#
# WHERE THE RULE LIVES — one implementation, not two
# --------------------------------------------------
# The decision, the registry of derived artefacts, the regeneration, the
# freshness re-check and the staging all live in
# `plugins/vibe-ic/programs/generated_artifact_conflict_resolve.py`. This script
# is its command-line name and nothing else.
#
# It was not always. This file first carried its own copy of the rule with a
# ONE-ENTRY registry — `programs/INDEX.md` and nothing more — and that is not a
# smaller version of the same answer, it is a different one. `PROGRAM_INVENTORY
# .json` is the SECOND file every program-adding branch rewrites, and it
# conflicted alongside INDEX.md on a real merge into main (a4caccefe). Against a
# one-entry registry it is a FOREIGN path, so the whole resolution is refused —
# including the half that was resolvable — and the merge gets finished by hand.
# Two implementations of one rule give two answers to that merge, and the weaker
# one was the one with a caller. The program also carries what a shell version
# cannot: a 60 s inner bound per generator (the landing harness runs at
# `--timeout=180`, so a larger bound loses the whole session rather than one
# step), a conflict-marker re-check after regeneration, and a machine-readable
# verdict record.
#
# WHY NOT A GIT MERGE DRIVER — measured, not assumed
# --------------------------------------------------
# The obvious fix is `.gitattributes` + `merge=programs-index`. It does not work,
# and it fails QUIETLY, which is worse. A merge driver runs during the content
# merge, BEFORE git has written the incoming side's new files to the worktree, so
# the generator reads a tree that is missing exactly the program being added and
# emits an index that is one entry stale. Measured on all 27 INDEX.md-conflicting
# PRs: the driver "resolved" every one, and `--check` then failed on every one
# (#1139: regenerated 1079, correct answer 1080, `step_repro_bundle` absent).
# A driver that always exits 0 converts a visible conflict into a silently
# committed wrong index — a check that lies.
#
# At a CONFLICT STOP the tree is already complete: git has checked out every
# non-conflicted path, so `step_repro_bundle.py` is on disk and INDEX.md is the
# sole unmerged entry. That is why this runs here and not there.
#
# EXIT CODES
# ----------
#     0  nothing was unmerged, or every conflicted path was regenerated,
#        verified fresh and staged
#     1  at least one conflicted path is not a registered derived artefact —
#        REFUSED, and the path is named. Nothing was staged.
#     2  the question could not be put (no resolver, generator absent, generator
#        failed or timed out, markers survived, `--check` still red, or a path
#        still unmerged afterwards). An unmeasured tree is not a clean one.
#
# Usage — after `git merge`/`git rebase` stops with a conflict:
#     tools/resolve_generated_conflicts.sh          # regenerate + stage
#     tools/resolve_generated_conflicts.sh --check  # say what it WOULD do
#     git rebase --continue   # or: git commit
set -uo pipefail

DRY=0
[ "${1:-}" = "--check" ] && DRY=1

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "not inside a git repository" >&2; exit 2; }
cd "$REPO_ROOT" || exit 2

RESOLVER="vibe-ic-marketplace/plugins/vibe-ic/programs/generated_artifact_conflict_resolve.py"

# THE NO-OP IS ANSWERED HERE, and only this one. Invoked outside a conflicted
# merge there is nothing to resolve and nothing to refuse, and this script's
# contract has always been that saying so is a success. The resolver treats the
# same state as UNMEASURABLE, which is the right answer to the question IT is
# asked ("was this resolution performed?") and the wrong answer to the question
# an operator asks this script ("is there anything left to do?").
mapfile -t UNMERGED < <(git diff --name-only --diff-filter=U)
if [ "${#UNMERGED[@]}" -eq 0 ]; then
  echo "no unmerged paths — nothing to resolve."
  exit 0
fi

[ -f "$RESOLVER" ] || {
  echo "resolver not found at $RESOLVER — the conflict is left in place." >&2
  exit 2; }

echo "${#UNMERGED[@]} conflicted path(s); handing them to $RESOLVER."

if [ "$DRY" -eq 1 ]; then
  exec python3 "$RESOLVER" --repo "$REPO_ROOT" --dry-run
fi
exec python3 "$RESOLVER" --repo "$REPO_ROOT"
