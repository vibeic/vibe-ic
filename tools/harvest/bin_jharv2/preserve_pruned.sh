#!/usr/bin/env bash
# preserve_pruned.sh <clone> <label> -- preserve the CONTENT of pruned checkouts.
#
# A pruned checkout has no HEAD and no commit, so there is no sha to anchor: the FILES on disk
# are the whole of it, and for 458 of them that content exists nowhere else on the fleet. I
# earlier called this the owner's call on the grounds that preserving it meant committing whole
# working trees. That was an assumption and it was wrong — measured, the differing files are 970
# distinct blobs totalling 76 MB, none over GitHub's limit.
#
# This writes ONE commit with NO PARENT, whose tree holds only those differing files under
# preserved/<checkout>/<path>. It is a snapshot on a clearly-named rescue ref; it touches no
# branch anyone uses and merges into nothing.
set -uo pipefail
R="${1:?}"; LABEL="${2:?}"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export GIT_INDEX_FILE="$T/idx"
n=0
while IFS=$'\t' read -r blob size path wt; do
  [ -n "$blob" ] && [ -f "$wt/$path" ] || continue
  b=$(git -C "$R" hash-object -w -- "$wt/$path" 2>/dev/null) || continue
  key="preserved/$(printf '%s' "${wt#/}" | tr '/' '_')/$path"
  git -C "$R" update-index --add --cacheinfo 100644,"$b","$key" 2>/dev/null && n=$((n+1))
done
[ "$n" -gt 0 ] || { echo "NOTHING_TO_PRESERVE"; exit 0; }
tree=$(git -C "$R" write-tree) || { echo "WRITE_TREE_FAILED"; exit 1; }
c=$(git -C "$R" -c user.email=harvest@vibe-ic.invalid -c user.name='vibe-ic harvest' \
     commit-tree "$tree" -m "preserve($LABEL): $n files from pruned checkouts whose content is on no commit

A pruned checkout has no HEAD, so there is no sha to anchor and nothing to rescue by reference:
the files on disk ARE the content. These are only the files that differ from origin/main, each
under preserved/<checkout-path>/<file>. No parent, so this merges into nothing and changes
nothing; it exists so the content survives the directory.") || { echo "COMMIT_TREE_FAILED"; exit 1; }
echo "COMMIT $c files=$n"
if git -C "$R" push -q origin "$c:refs/heads/harvest/preserved-$LABEL" 2>/dev/null; then
  got=$(git -C "$R" ls-remote origin "refs/heads/harvest/preserved-$LABEL" | cut -f1)
  [ "$got" = "$c" ] && echo "PUSHED_CONFIRMED harvest/preserved-$LABEL = $c files=$n" \
                    || echo "**NOT_ON_REMOTE** want=$c got=${got:-none}"
else
  git -C "$R" update-ref "refs/heads/harvest/preserved-$LABEL" "$c"
  echo "**PUSH_FAILED** local ref made: harvest/preserved-$LABEL = $c files=$n"
fi
