#!/usr/bin/env bash
# programs_index_merge.sh — git merge driver for programs/INDEX.md.
#
# WHY THIS EXISTS
# ---------------
# `programs/INDEX.md` is generated in full by `tools/gen_programs_index.py`, and
# `--check` fails CI on any drift, so the file has NO hand-authored content.
# Its "## Stats" block carries three tree-wide COUNTERS:
#
#     - **Total programs (excluding helpers / shims):** 1079
#     | `any` | 1070 |
#     ### `any` (1070 programs)
#
# Any branch that adds a program rewrites all three, so branches collide on the
# COUNTERS rather than on the entries — two programs at opposite ends of the
# alphabet conflict just as reliably as neighbours. Measured 2026-08-13 against
# `24ff95307`: of 30 CONFLICTING open PRs, 26 conflict on INDEX.md and 25
# conflict on INDEX.md and nothing else (vibe-ic#1431, vibe-ic#1363).
#
# Resolving that by hand is the same three commands every time — discard both
# sides, regenerate, verify — because a fully generated file has no side worth
# keeping. This driver is those three commands.
#
# WHY DISCARDING BOTH SIDES IS SAFE HERE AND NOWHERE ELSE
# -------------------------------------------------------
# It is safe ONLY because the generator is the source of truth: whatever the two
# sides say, the correct content is a pure function of the post-merge PROGRAMS
# TREE, which git has already written to disk by the time a driver runs. The
# driver is bound to exactly one path by `.gitattributes` and MUST NOT be
# generalised to any file carrying authored content.
#
# It REFUSES rather than guesses. If the generator is missing, errors, or emits
# something that fails its own `--check`, this exits non-zero and git leaves an
# ordinary conflict for a human. A merge driver that always exited 0 would turn
# every generator breakage into a silently committed wrong index — strictly
# worse than the conflict it replaces, and precisely the "check that lies"
# this repository exists to eliminate.
#
# Registered by `tools/install-git-hooks.sh`; merge drivers live in `.git/config`,
# which is not tracked, so the committed `.gitattributes` is inert without it.
#
# Usage (git calls this; %A is both the "ours" input and the output file):
#     programs_index_merge.sh %O %A %B %P
set -uo pipefail

CURRENT="${2:-}"                          # %A — ours, and where the result must land
PATHNAME="${4:-programs/INDEX.md}"        # %P — for messages only

die () {
  echo "programs-index merge driver: $* — leaving an ordinary conflict for a human." >&2
  exit 1
}

[ -n "$CURRENT" ] || die "called without the %A output path"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "not inside a git repository"
GEN="$REPO_ROOT/tools/gen_programs_index.py"
[ -f "$GEN" ] || die "generator not found at $GEN"

# Regenerate straight into git's output file. The generator reads the programs
# tree that git has already merged on disk, so neither side's stale counters are
# consulted — that is the entire point.
python3 "$GEN" --out "$CURRENT" >/dev/null 2>&1 \
  || die "generator exited non-zero while regenerating $PATHNAME"

# Never trust our own output.
[ -s "$CURRENT" ] || die "regenerated $PATHNAME is empty"
! grep -q '^<<<<<<< \|^>>>>>>> \|^=======$' "$CURRENT" \
  || die "regenerated $PATHNAME still contains conflict markers"

echo "programs-index merge driver: regenerated $PATHNAME from the merged tree." >&2
exit 0
