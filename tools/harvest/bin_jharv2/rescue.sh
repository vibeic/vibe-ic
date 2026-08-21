#!/usr/bin/env bash
# rescue.sh <clone> <label> -- preserve commits that NOTHING points at, before an executor
# removes the directory that is their only pointer.
#
# Reads `path<TAB>repo<TAB>head` on stdin, keeps the ones still unreferenced, and builds ONE
# anchor commit per clone whose TREE IS origin/main's tree -- so it introduces no change of its
# own -- with every rescued commit as a parent. One ref then keeps every one of those histories
# alive. Identity is passed with `-c` so nothing in anyone's clone config is modified.
#
# Nothing is deleted and no existing ref is moved.
set -uo pipefail
R="${1:?}"; LABEL="${2:?}"
declare -a P=()
while IFS=$'\t' read -r p repo head; do
  [ "$repo" = "$R" ] || continue
  [ -n "$head" ] || continue
  git -C "$R" rev-parse -q --verify "$head^{commit}" >/dev/null 2>&1 || continue
  git -C "$R" for-each-ref --contains "$head" --count=1 --format='x' 2>/dev/null | grep -q x && continue
  P+=("-p" "$head")
done
n=$(( ${#P[@]} / 2 ))
[ "$n" -gt 0 ] || { echo "NOTHING_TO_RESCUE $R"; exit 0; }
T=$(git -C "$R" rev-parse origin/main^{tree})
C=$(git -C "$R" -c user.email=harvest@vibe-ic.invalid -c user.name='vibe-ic harvest' \
      commit-tree "$T" "${P[@]}" -m "rescue($LABEL): $n unreferenced worktree commits, kept alive before anything deletes their directory

Tree is origin/main's tree, so this anchor introduces no change of its own. Its only content is
its PARENTS: $n commits that were reachable from no branch, tag or remote, whose worktree
directory was the only thing pointing at them. Deleting those directories would have made them
garbage. Nothing was deleted and no existing ref was moved.") || { echo "COMMIT_TREE_FAILED $R"; exit 1; }
echo "ANCHOR $R $C parents=$n"
# `| tail` swallows the exit status, so an earlier version printed PUSHED for a push that had
# failed. Check the push, and then CONFIRM the ref is actually on the remote before saying so:
# a rescue that is only claimed is not a rescue.
if git -C "$R" push -q origin "$C:refs/heads/harvest/rescue-$LABEL"; then
  got=$(git -C "$R" ls-remote origin "refs/heads/harvest/rescue-$LABEL" | cut -f1)
  if [ "$got" = "$C" ]; then echo "PUSHED_CONFIRMED refs/heads/harvest/rescue-$LABEL = $C"
  else echo "**PUSH_NOT_ON_REMOTE** refs/heads/harvest/rescue-$LABEL want=$C got=${got:-none}"; fi
else
  echo "**PUSH_FAILED** refs/heads/harvest/rescue-$LABEL = $C"
fi
