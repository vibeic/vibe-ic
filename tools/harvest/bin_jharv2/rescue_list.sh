#!/usr/bin/env bash
# rescue_list.sh <clone> <label> -- preserve the exact heads given on stdin (one sha per line),
# no re-filtering. Used for ON_LOCAL_REF_ONLY: those are on a branch, but on no REMOTE, so they
# survive only as long as this clone does -- and whole clones have been deleted during this
# triage. One anchor whose TREE is origin/main's tree; its only content is its parents.
# Checks the push AND re-reads the ref from the remote: a rescue that is only claimed is not one.
set -uo pipefail
R="${1:?}"; LABEL="${2:?}"
declare -a P=(); declare -A SEEN=()
while read -r h; do
  [ -n "$h" ] || continue
  [ -n "${SEEN[$h]:-}" ] && continue
  git -C "$R" rev-parse -q --verify "$h^{commit}" >/dev/null 2>&1 || continue
  SEEN[$h]=1; P+=("-p" "$h")
done
n=$(( ${#P[@]} / 2 ))
[ "$n" -gt 0 ] || { echo "NOTHING $R"; exit 0; }
T=$(git -C "$R" rev-parse origin/main^{tree})
C=$(git -C "$R" -c user.email=harvest@vibe-ic.invalid -c user.name='vibe-ic harvest' \
      commit-tree "$T" "${P[@]}" -m "rescue($LABEL): $n commits that were on a LOCAL ref only

Tree is origin/main's tree, so this anchor introduces no change of its own. Its parents were on
a local branch in one clone and on no remote at all: they survived only as long as that clone
did, and whole clones have been deleted during this triage. Nothing was deleted, no ref moved.") \
  || { echo "COMMIT_TREE_FAILED $R"; exit 1; }
if git -C "$R" push -q origin "$C:refs/heads/harvest/rescue-$LABEL" 2>/dev/null; then
  got=$(git -C "$R" ls-remote origin "refs/heads/harvest/rescue-$LABEL" | cut -f1)
  [ "$got" = "$C" ] && echo "PUSHED_CONFIRMED harvest/rescue-$LABEL = $C parents=$n" \
                    || echo "**NOT_ON_REMOTE** harvest/rescue-$LABEL want=$C got=${got:-none}"
else
  echo "**PUSH_FAILED** harvest/rescue-$LABEL = $C parents=$n  (make it a local ref and push from a clone whose hook passes)"
fi
