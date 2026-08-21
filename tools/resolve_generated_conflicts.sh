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
# has no side worth keeping. This script is those three commands, with the checks
# that make it safe to run without reading the diff.
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

# path -> generator command. A file is resolvable ONLY if it is listed here.
GENERATED_PATH="vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md"
GENERATOR="tools/gen_programs_index.py"

mapfile -t UNMERGED < <(git diff --name-only --diff-filter=U)

if [ "${#UNMERGED[@]}" -eq 0 ]; then
  echo "no unmerged paths — nothing to resolve."
  exit 0
fi

# Refuse on anything not generated. Regenerating a file with authored content
# would discard someone's work; this script exists to be safe to run blind, and
# that property is only worth having if it is enforced rather than documented.
foreign=()
for p in "${UNMERGED[@]}"; do
  [ "$p" = "$GENERATED_PATH" ] || foreign+=("$p")
done

if [ "${#foreign[@]}" -ne 0 ]; then
  echo "REFUSING: ${#foreign[@]} conflicted path(s) are NOT generated files:" >&2
  printf '    %s\n' "${foreign[@]}" >&2
  echo "Resolve those by hand. Nothing was staged." >&2
  exit 1
fi

echo "all ${#UNMERGED[@]} conflicted path(s) are generated; regenerating from the merged tree."

if [ "$DRY" -eq 1 ]; then
  echo "--check: would run '$GENERATOR' and stage $GENERATED_PATH"
  exit 0
fi

[ -f "$GENERATOR" ] || { echo "generator not found at $GENERATOR" >&2; exit 2; }

python3 "$GENERATOR" >/dev/null 2>&1 || {
  echo "generator exited non-zero — conflict left in place." >&2; exit 2; }

# Never trust our own output: verify with the generator's OWN freshness check,
# the same one CI runs, before staging anything.
if ! python3 "$GENERATOR" --check >/dev/null 2>&1; then
  echo "regenerated $GENERATED_PATH still fails --check — conflict left in place." >&2
  exit 2
fi

if grep -q '^<<<<<<< \|^>>>>>>> ' "$GENERATED_PATH"; then
  echo "regenerated $GENERATED_PATH still contains conflict markers — not staging." >&2
  exit 2
fi

git add -- "$GENERATED_PATH"
echo "staged $GENERATED_PATH (verified by '$GENERATOR --check')."
echo "now run: git rebase --continue   (or: git commit)"
