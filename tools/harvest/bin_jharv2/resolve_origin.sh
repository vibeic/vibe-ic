#!/usr/bin/env bash
# resolve_origin.sh -- decide ON_REMOTE from ORIGIN, once, on one machine.
#
# jharv3's finding: survivability measured ON a host is that HOST'S VIEW of origin, not origin.
# A clone that never fetched a branch reports its commit as local-only when origin has had it all
# along. The error is in the safe direction -- it over-warns and over-preserves -- but it makes
# rows say something false and causes pushes of commits origin already holds. So the final split
# is resolved here, against a clone holding all 627 origin refs, from the host-side heads.
set -uo pipefail
R=/home/reyerchu/vibe-ic
while IFS=$'\t' read -r p host kind head; do
  [ -n "$head" ] || { printf '%s\t%s\tUNKNOWN\t-\n' "$p" "$host"; continue; }
  if ! git -C "$R" rev-parse -q --verify "$head^{commit}" >/dev/null 2>&1; then
    # origin cannot have it if this clone, which holds every origin ref, has never seen the object
    printf '%s\t%s\t%s\tnot-on-origin(object absent here)\n' "$p" "$host" "$kind"; continue
  fi
  r=$(git -C "$R" for-each-ref --format='%(refname:short)' --contains "$head" --count=1 refs/remotes/origin 2>/dev/null)
  [ -z "$r" ] && r=$(git -C "$R" for-each-ref --format='%(refname:short)' --points-at "$head" --count=1 refs/remotes/origin 2>/dev/null)
  if [ -n "$r" ]; then printf '%s\t%s\tON_REMOTE\t%s\n' "$p" "$host" "$r"
  else printf '%s\t%s\t%s\t-\n' "$p" "$host" "$kind"; fi
done
