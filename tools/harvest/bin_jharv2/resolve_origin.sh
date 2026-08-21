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
# the authority for "is this ref on origin" is ls-remote, never a tracking ref
LIVE=$(mktemp); trap 'rm -f "$LIVE"' EXIT
git -C "$R" ls-remote --heads origin 2>/dev/null | awk '{sub("refs/heads/","",$2); print $2}' | sort -u > "$LIVE"
[ -s "$LIVE" ] || { echo "NO_LIVE_REFS_FROM_LS_REMOTE" >&2; exit 1; }
echo "#authority	git ls-remote --heads origin	$(grep -c '' "$LIVE") live refs" >&2
while IFS=$'\t' read -r p host kind head; do
  [ -n "$head" ] || { printf '%s\t%s\tUNKNOWN\t-\n' "$p" "$host"; continue; }
  if ! git -C "$R" rev-parse -q --verify "$head^{commit}" >/dev/null 2>&1; then
    # origin cannot have it if this clone, which holds every origin ref, has never seen the object
    # this clone holds every live origin ref; if it has never seen the object, origin cannot
    # have it. The host's own ON_REMOTE label must NOT survive that -- it is the stale-cache
    # answer, and it is the one that reads "safe to delete" while losing work.
    printf '%s\t%s\tNOT_ON_ORIGIN\tobject absent in the clone holding every live origin ref\n' "$p" "$host"; continue
  fi
  # origin/HEAD is a LOCAL SYMBOLIC ref, not a branch on origin: `ls-remote --heads` does not
  # list it, so a row naming it sends a reader somewhere ambiguous. Exclude it, and require the
  # ref finally named to be LIVE on origin -- a tracking ref is a memory of origin, not origin.
  r=$(git -C "$R" for-each-ref --format='%(refname:short)' --contains "$head" refs/remotes/origin 2>/dev/null         | grep -v '^origin/HEAD$' | while read -r c; do grep -qxF "${c#origin/}" "$LIVE" && { echo "$c"; break; }; done)
  [ -z "$r" ] && r=$(git -C "$R" for-each-ref --format='%(refname:short)' --points-at "$head" refs/remotes/origin 2>/dev/null         | grep -v '^origin/HEAD$' | while read -r c; do grep -qxF "${c#origin/}" "$LIVE" && { echo "$c"; break; }; done)
  if [ -n "$r" ]; then printf '%s\t%s\tON_REMOTE\t%s\n' "$p" "$host" "$r"
  else
    # origin could not confirm it. Whatever the HOST said, it is not ON_REMOTE: refusing to
    # inherit a tracking-ref answer is the whole point of resolving here.
    case "$kind" in
      ON_REMOTE) printf '%s\t%s\tNOT_ON_ORIGIN\thost claimed ON_REMOTE; no LIVE origin ref contains it\n' "$p" "$host";;
      *)         printf '%s\t%s\t%s\t-\n' "$p" "$host" "$kind";;
    esac
  fi
done
