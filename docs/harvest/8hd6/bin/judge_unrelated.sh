#!/usr/bin/env bash
# judge_unrelated.sh <repo> -- decide a checkout that shares NO history with this
# repository, purely by comparing file bytes against origin/main.
#
# No merge-base exists, so there is no "files this branch owns" to scope by. The only honest
# route is the whole tree: for every path in HEAD, is the blob byte-identical to origin/main
# at the same path? Paths main does not have at all are listed separately -- those are the
# ones that can actually be lost. Reference main is read from the real clone.
set -uo pipefail
P="${1:?}"; REF=/home/reyerchu/vibe-ic
same=0; diff=0; absent=0; alist=""; dlist=""
while IFS= read -r f; do
  [ -n "$f" ] || continue
  a=$(git -C "$P" rev-parse -q --verify "HEAD:$f" 2>/dev/null)
  [ -n "$a" ] || continue
  b=$(git -C "$REF" rev-parse -q --verify "origin/main:$f" 2>/dev/null)
  if [ -z "$b" ]; then
    absent=$((absent+1)); [ ${#alist} -lt 500 ] && alist="${alist}${alist:+, }${f}"
  elif [ "$(git -C "$P" cat-file blob "$a" | sha256sum | cut -d' ' -f1)" = "$(git -C "$REF" cat-file blob "$b" | sha256sum | cut -d' ' -f1)" ]; then
    same=$((same+1))
  else
    diff=$((diff+1)); [ ${#dlist} -lt 500 ] && dlist="${dlist}${dlist:+, }${f}"
  fi
done < <(git -C "$P" ls-tree -r --name-only HEAD 2>/dev/null)
printf '%s\nidentical_to_main=%d  differ=%d  absent_from_main=%d\n' "$P" "$same" "$diff" "$absent"
[ -n "$dlist" ] && printf 'DIFFER : %s\n' "$dlist"
[ -n "$alist" ] && printf 'ABSENT : %s\n' "$alist"
