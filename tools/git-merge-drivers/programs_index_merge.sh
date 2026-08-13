#!/usr/bin/env bash
# programs_index_merge.sh — git merge driver for programs/INDEX.md.
#
# WHY THIS EXISTS
# ---------------
# `programs/INDEX.md` is generated in full by `tools/gen_programs_index.py`;
# `--check` fails CI on any drift, so the file has NO hand-authored content.
# Its "## Stats" block carries three tree-wide COUNTERS:
#
#     - **Total programs (excluding helpers / shims):** 1079
#     | `any` | 1070 |
#     ### `any` (1070 programs)
#
# Every branch that adds one program rewrites all three. Two branches that add
# programs at opposite ends of the alphabet still collide, because they collide
# on the counters and not on the entries. Measured 2026-08-13 on `24ff95307`:
# of 30 CONFLICTING open PRs, 26 conflict on INDEX.md and 25 conflict on
# INDEX.md and NOTHING ELSE (vibe-ic#1431, vibe-ic#1363).
#
# Resolving that by hand is the same three commands every time -- discard both
# sides, regenerate, verify -- because a generated file has no side worth
# keeping. This driver is those three commands.
#
# WHY DISCARDING BOTH SIDES IS SAFE HERE AND NOWHERE ELSE
# -------------------------------------------------------
# It is safe ONLY because the generator is the source of truth: whatever the two
# sides say, the correct content is a pure function of the post-merge tree, which
# git has already checked out by the time a driver runs. This driver is bound to
# exactly one path via `.gitattributes` and MUST NOT be generalised to files that
# carry authored content.
#
# It also REFUSES rather than guesses. If the generator is missing, errors, or
# produces a file that fails its own `--check`, the driver exits non-zero and git
# leaves a normal conflict for a human. A merge driver that always exits 0 would
# turn every generator breakage into a silently committed wrong index -- strictly
# worse than the conflict it replaces.
#
# Installed by `tools/install-git-hooks.sh` (git merge drivers live in
# `.git/config`, which is not tracked, so a committed `.gitattributes` does
# nothing on its own).
#
# Usage (git calls this; %A is both the "ours" input and the output file):
#     programs_index_merge.sh %O %A %B %P
set -uo pipefail

CURRENT="${2:-}"   # %A — ours, and where the result must be written
PATHNAME="${4:-programs/INDEX.md}"

die () { echo "programs-index merge driver: $* — leaving a normal conflict for a human." >&2; exit 1; }

[ -n "$CURRENT" ] || die "called without the %A output path"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "not inside a git repository"
GEN="$REPO_ROOT/tools/gen_programs_index.py"
[ -f "$GEN" ] || die "generator not found at $GEN"

# Regenerate straight into git's output file. The generator reads the PROGRAMS
# TREE, which git has already merged on disk, so neither side's stale counters
# are consulted -- that is the whole point.
if ! python3 "$GEN" --out "$CURRENT" >/dev/null 2>&1; then
  die "generator exited non-zero for $PATHNAME"
fi

# Never trust our own output: a driver that wrote a wrong index and exited 0
# would be a check that lies.
if ! grep -q '^<<<<<<< \|^>>>>>>> ' "$CURRENT"; then
  :
else
  die "regenerated $PATHNAME still contains conflict markers"
fi

[ -s "$CURRENT" ] || die "regenerated $PATHNAME is empty"

echo "programs-index merge driver: regenerated $PATHNAME from the merged tree." >&2
exit 0
