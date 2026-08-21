#!/usr/bin/env bash
# recheck_drift.sh <shard.tsv> -- RUN THIS IMMEDIATELY BEFORE ACTING ON ANY VERDICT.
#
# A verdict is true as of the commit it was taken against, and this fleet's hosts are not
# quiescent: while shard C was being judged, another agent checked out a branch in
# `wt/b68-base-hy` and made three commits, turning a DROP into a KEEP. Deleting on a stale
# DROP is exactly the unrecoverable outcome the whole rule exists to prevent.
#
# Exit 0 only if every checkout still sits at the HEAD its verdict was taken against.
set -uo pipefail
TSV="${1:?usage: recheck_drift.sh <shard.tsv>}"
moved=0; gone=0; ok=0
while IFS=$'\t' read -r host clone wt br head verdict rest; do
  case "$host" in '#'*|'') continue;; esac
  if [ ! -d "$wt" ]; then gone=$((gone+1)); echo "GONE     $wt"; continue; fi
  now=$(git -C "$wt" rev-parse -q --verify HEAD 2>/dev/null | cut -c1-9)
  if [ "$now" != "$head" ]; then
    moved=$((moved+1))
    printf '%-8s %s\n           verdict was taken at %s, now at %s -- RE-JUDGE before acting\n' \
      "MOVED[$verdict]" "$wt" "$head" "$now"
  else ok=$((ok+1)); fi
done < "$TSV"
echo "unchanged=$ok moved=$moved missing=$gone"
[ "$moved" -eq 0 ] || { echo "REFUSING: $moved checkout(s) moved since judging. Their verdicts are stale."; exit 1; }
