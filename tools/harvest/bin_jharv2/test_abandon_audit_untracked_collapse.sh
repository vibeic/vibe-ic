#!/usr/bin/env bash
# RED without the fix. Builds a worktree whose ONLY uncommitted content lives inside an untracked
# directory -- the shape that produced 43 wrong rows on .102 and survived, unfixed, in the one
# script whose job is to make deletion safe.
#
# The finding this pins is NOT "wrong flag". abandon_audit.sh computes TWO numbers:
#   status_lines (n)  -- counts every porcelain entry. A collapsed directory still yields one, so
#                        this number can UNDERCOUNT but can never reach 0 while files exist.
#   new              -- counted AFTER `[ -f ]`, which drops the collapsed "dir/" entry entirely.
# The verdict reads `new`. The safe signal was present and non-zero (status_lines=1) and the script
# used the derived one that can be zeroed. A gate that asks "is anything untracked here?" is safe
# under both forms; this gate asked a question that is not that one.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd); F=$(mktemp -d); trap 'rm -rf "$F"' EXIT
git init -q "$F"; git -C "$F" config user.email t@t; git -C "$F" config user.name t
echo tracked > "$F/kept.txt"; git -C "$F" add kept.txt; git -C "$F" commit -qm base
mkdir -p "$F/scratch/deep"
echo 'the only copy of this work' > "$F/scratch/a.py"
echo 'and this'                   > "$F/scratch/deep/b.py"
truth=$(git -C "$F" ls-files --others --exclude-standard | wc -l)
[ "$truth" -eq 2 ] || { echo "FIXTURE BROKEN: expected 2 untracked, got $truth"; exit 2; }
out=$(printf '%s\t%s\n' "$F" "$F" | bash "$here/abandon_audit.sh")
st=$(printf '%s' "$out" | cut -f2); nums=$(printf '%s' "$out" | cut -f3)
new=$(printf '%s' "$nums" | sed 's/.*new=//')
echo "  truth=2 untracked (both inside a directory) -> $nums verdict=$st"
rc=0
if [ "$new" -ne 2 ]; then echo "  FAIL: new=$new, expected 2 -- the subtree was dropped"; rc=1; fi
case "$st" in *DIRTY*) ;; *) echo "  FAIL: verdict=$st -- an ABANDON row here authorises deleting 2 files"; rc=1;; esac
# positive control: the audit must report CLEAN on a genuinely clean tree, or DIRTY means nothing
rm -rf "$F/scratch"
c=$(printf '%s\t%s\n' "$F" "$F" | bash "$here/abandon_audit.sh" | cut -f2)
[ "$c" = CLEAN ] || { echo "  FAIL: control tree reads $c, not CLEAN -- DIRTY is unfalsifiable"; rc=1; }
echo "  control: genuinely clean tree -> $c"
[ $rc -eq 0 ] && echo "  PASS"; exit $rc
