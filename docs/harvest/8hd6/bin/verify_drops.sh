#!/usr/bin/env bash
# verify_drops.sh -- re-derive every DROP a second time, independently of judge.sh, with
# real sha256sum. A wrong DROP is unrecoverable, so the drops get checked twice by two
# different routes and only agreement counts.
#
# Route A (branch touched files): hash BOTH sides of every touched file with sha256sum and
#         require every pair to match.
# Route B (branch touched nothing): require the worktree's whole tree OID to equal the tree
#         OID of a commit that origin/main actually published -- i.e. this tree is a verbatim
#         snapshot of a state main itself went through, not merely an "ancestor".
set -uo pipefail
S=${S:-/home/reyerchu/_harv_priv}
ROWS=${ROWS:-$S/rows.tsv}
ALL=${ALL:-$S/all.tsv}
for f in "$ROWS" "$ALL"; do [ -s "$f" ] || { echo "REFUSING: verify_drops.sh needs $f" >&2; exit 2; }; done
awk -F'\t' '$1=="DROP"{print $2}' "$ROWS" | while read -r wt; do
  repo=$(awk -F'\t' -v w="$wt" '$2==w{print $1; exit}' "$ALL")
  head=$(awk -F'\t' -v w="$wt" '$2==w{print $4; exit}' "$ALL")
  mb=$(git -C "$repo" merge-base "$head" origin/main 2>/dev/null)
  n=$(git -C "$repo" diff --name-only "$mb" "$head" 2>/dev/null | grep -c '')
  if [ "$n" -gt 0 ]; then
    s=0; d=0
    while read -r f; do
      a=$(git -C "$repo" show "$head:$f" 2>/dev/null | sha256sum | cut -d' ' -f1)
      b=$(git -C "$repo" show "origin/main:$f" 2>/dev/null | sha256sum | cut -d' ' -f1)
      [ "$a" = "$b" ] && s=$((s+1)) || d=$((d+1))
    done < <(git -C "$repo" diff --name-only "$mb" "$head")
    [ "$d" -eq 0 ] && v="CONFIRMED" || v="**DISAGREES**"
    printf '%s\tA\t%s\tsha256 identical on %d/%d touched files\n' "$wt" "$v" "$s" "$((s+d))"
  else
    ht=$(git -C "$repo" rev-parse "$head^{tree}")
    mt=$(git -C "$repo" rev-parse "$mb^{tree}")
    onmain=$(git -C "$repo" merge-base --is-ancestor "$mb" origin/main && echo yes || echo no)
    [ "$ht" = "$mt" ] && [ "$onmain" = yes ] && v="CONFIRMED" || v="**DISAGREES**"
    printf '%s\tB\t%s\twhole tree %s is a tree origin/main published (%s)\n' \
      "$wt" "$v" "${ht:0:9}" "$(git -C "$repo" log -1 --format=%cs "$mb")"
  fi
done
