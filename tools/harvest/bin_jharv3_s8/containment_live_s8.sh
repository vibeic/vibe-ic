#!/bin/bash
# containment_live_s8.sh <heads.tsv> — is each judged head held by a LIVE origin ref?
#
# WHY NOT refs/remotes: it is a cache of origin and outlives branches origin has
# deleted. This fleet deleted 86 heads down to 60 in an hour while shard C was
# being written, and every `git fetch origin harvest/rescue-...` instruction in
# the file stopped resolving. `git ls-remote` is the only authority for what
# origin advertises NOW.
#
# WHY NOT `--contains` per ref: 1576 testable refs x 110 heads is 173k walks.
# Instead the reachable set is built once with `git rev-list --stdin` over the
# live shas, and membership is a lookup.
#
# HOW THIS LIES IF UNGUARDED: an empty or truncated reachable set makes EVERY
# head report "not contained" (a false alarm), and a set built from refs/remotes
# makes deleted branches report "contained" (the dangerous direction). So the set
# is validated before it is used, and the script refuses rather than reporting.
set -uo pipefail
HEADS=${1:?usage: containment_live_s8.sh <path TAB head file>}
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
git ls-remote origin 2>/dev/null | awk '{print $1"\t"$2}' > "$S/lsremote.tsv"
adv=$(wc -l < "$S/lsremote.tsv")
[ "$adv" -gt 100 ] || { echo "REFUSING: ls-remote advertised only $adv refs" >&2; exit 2; }
cut -f1 "$S/lsremote.tsv" | LC_ALL=C sort -u > "$S/shas"
: > "$S/have"
while read -r s; do git cat-file -e "$s^{commit}" 2>/dev/null && echo "$s" >> "$S/have"; done < "$S/shas"
have=$(wc -l < "$S/have")
git rev-list --stdin < "$S/have" 2>/dev/null | LC_ALL=C sort -u > "$S/reach"
# G1: every live sha must be in its own reachable set.
if [ "$(LC_ALL=C comm -23 <(LC_ALL=C sort -u "$S/have") "$S/reach" | wc -l)" -ne 0 ]; then
  echo "REFUSING: the reachable set does not contain the live shas it was built from" >&2; exit 2; fi
# G2: main is a live branch, so all of main must be in it. A truncated walk fails here.
m=$(git rev-parse origin/main 2>/dev/null)
if [ -n "$m" ] && [ "$(git rev-list "$m" | LC_ALL=C sort -u | LC_ALL=C comm -23 - "$S/reach" | wc -l)" -ne 0 ]; then
  echo "REFUSING: origin/main is not fully inside the reachable set" >&2; exit 2; fi
# G3: a sha that cannot be reachable must not be reported as reachable.
grep -qx 0000000000000000000000000000000000000000 "$S/reach" && { echo "REFUSING: null sha is in the set" >&2; exit 2; }
echo "# advertised=$adv testable_locally=$have reachable_commits=$(wc -l < "$S/reach")" >&2
while IFS=$'\t' read -r p h; do
  [ -z "${h:-}" ] && { printf '%s\t-\tNO_HEAD\n' "$p"; continue; }
  if grep -qx "$h" "$S/reach"; then
    tip=$(grep -m1 "^$h	" "$S/lsremote.tsv" | cut -f2)
    printf '%s\t%s\tCONTAINED%s\n' "$p" "$h" "${tip:+ (is the tip of $tip)}"
  else
    printf '%s\t%s\tNOT_HELD_BY_ANY_LIVE_ORIGIN_REF\n' "$p" "$h"
  fi
done < "$HEADS"
