#!/bin/bash
# unproven_paths.sh <label> <tree> <main_pathblob.tsv> [outdir]
# Files PRESENT in <tree> whose (path,blob) origin/main's history NEVER held.
# 0 unproven  => LANDED holds by content.
# >0          => that content is on no main commit; the row must rest on
#                preservation, and must say so.
set -u; L="$1"; T="$2"; MAP="$3"; O="${4:-.}"; MAIN=${MAIN:-a4caccefe}
tag=$(echo "$L" | tr '/' '_')
git diff --raw --no-abbrev --no-renames $MAIN "$T" \
 | awk '{split($0,a,"\t"); split(a[1],f," "); if(f[5]=="M"||f[5]=="A") print a[2]"\t"f[4]}' \
 | LC_ALL=C sort -u > "$O/${tag}.want"
n=$(wc -l < "$O/${tag}.want")
if [ "$n" -eq 0 ]; then echo -e "$L\tneed=0\tUNPROVEN=0"; exit 0; fi
if [ ! -s "$MAP" ]; then echo "REFUSING: $MAP is empty; that is a broken measurement, not a verdict." >&2; exit 2; fi
LC_ALL=C comm -23 "$O/${tag}.want" "$MAP" > "$O/${tag}.unproven"
echo -e "$L\tneed=$n\tUNPROVEN=$(wc -l < "$O/${tag}.unproven")"
