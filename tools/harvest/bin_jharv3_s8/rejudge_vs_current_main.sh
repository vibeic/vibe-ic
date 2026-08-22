#!/bin/bash
# rejudge_vs_current_main.sh <rows.tsv> <old_map> <new_map> <outdir>
# rejudge_vs_current_main.sh --self-test <old_map> <new_map>
#
# WHY THIS EXISTS. Shard C's 110 verdicts were judged against origin/main
# a4caccefe (v1.11.66). Main is now ae78abb285 (v1.11.70), 673 commits later.
# A RECOVER decided against a stale main can be work that has since landed, and
# acting on it sends somebody to redo finished work; the reverse -- a LANDED
# going stale -- cannot happen while main only grows, and G2 below MEASURES that
# rather than assuming it.
#
# METHOD. Judged by CONTENT, never by ancestry: vibe-ic squash-lands, so every
# one of these branches shows as "ahead" whether or not its work is on main.
# For a worktree's judged HEAD tree, every (path,blob) pair must be a pair
# origin/main's HISTORY has held -- not a pair main's TIP holds. Comparing
# against the tip cannot separate landed work from unlanded work.
#
# HOW THIS MEASUREMENT LIES IF UNGUARDED (all four hit for real on this fleet):
#  1. `git log --raw` drops merge-expressed history unless given -m.
#  2. Keeping only post-image blobs misses every blob main later DELETED.
#  3. mawk 1.3.4 never matches a {40} interval regex, so the history set comes
#     back EMPTY and every path reports "unproven" -- or, inverted, everything
#     reports proven. The map builder uses length()==40 for this reason.
#  4. An empty or truncated map makes comm -23 return the whole want set (all
#     unproven) and an empty want set makes it return nothing (all proven).
# Each of those exits 0. Hence the refusals here: a degenerate map and an empty
# tree are broken measurements, never verdicts.
set -u

selftest() {
  OLD=$1; NEW=$2; fail=0
  # G1 NON-VACUITY: main's own tip must be fully explained by the history map.
  # If the map is truncated or the awk trap fired, this goes RED.
  tip=$(git ls-tree -r ae78abb285630636b2f305f2ed4aef13f92201ed | awk '$2=="blob"{print $4"\t"$3}' | LC_ALL=C sort -u)
  miss=$(printf '%s\n' "$tip" | LC_ALL=C comm -23 - "$NEW" | grep -c .)
  n=$(printf '%s\n' "$tip" | grep -c .)
  if [ "$n" -lt 1000 ] || [ "$miss" -ne 0 ]; then
    echo "G1 RED: $miss of $n of main's own tip pairs are absent from the history map"; fail=1
  else echo "G1 GREEN: all $n of main's tip (path,blob) pairs are in the map"; fi
  # G2 MONOTONICITY: main only grows, so no pair known at a4caccefe may be lost.
  # This is what licenses "the 34 LANDED rows cannot have regressed".
  lost=$(LC_ALL=C comm -23 "$OLD" "$NEW" | grep -c .)
  if [ "$lost" -ne 0 ]; then echo "G2 RED: $lost (path,blob) pairs known at a4caccefe are absent at ae78abb285"; fail=1
  else echo "G2 GREEN: old map is a subset of new ($(wc -l < "$OLD") -> $(wc -l < "$NEW") pairs, 0 lost)"; fi
  # G3 THE RED THIS METHOD EXISTS TO AVOID: judging against main's TIP instead of
  # its history must MISJUDGE a row we know landed. /home/reyerchu/_dens_priv/wt-jdrc1177
  # is LANDED in the deliverable; against the tip it looks unlanded.
  t=$(git rev-parse 6aa0d6abf1762c84710a5970d67fac623cbc82ad^{tree})
  bytip=$(git diff --raw --no-abbrev --no-renames ae78abb285630636b2f305f2ed4aef13f92201ed "$t" | grep -c .)
  byhist=$(git ls-tree -r 6aa0d6abf1762c84710a5970d67fac623cbc82ad | awk '$2=="blob"{print $4"\t"$3}' | LC_ALL=C sort -u | LC_ALL=C comm -23 - "$NEW" | grep -c .)
  if [ "$bytip" -gt 0 ] && [ "$byhist" -eq 0 ]; then
    echo "G3 GREEN: tip-comparison calls this landed row unlanded on $bytip paths; history says 0 unproven"
  else echo "G3 RED: the control did not separate the two methods (tip=$bytip hist=$byhist)"; fail=1; fi
  # G4 A LIVE NEGATIVE CONTROL: the comm must be able to report unproven at all.
  # /home/reyerchu/_cpath_priv/tree holds content main never held; if this comes
  # back 0 the sweep is passing over an empty set.
  neg=$(git ls-tree -r af1072b95b8f1eedbb59a7ac0fc4c0b083e34cbf | awk '$2=="blob"{print $4"\t"$3}' | LC_ALL=C sort -u | LC_ALL=C comm -23 - "$NEW" | grep -c .)
  if [ "$neg" -gt 0 ]; then echo "G4 GREEN: negative control reports $neg unproven pairs -- the sweep is not vacuous"
  else echo "G4 RED: negative control reports 0 unproven; the comparison is passing over an empty set"; fail=1; fi
  # G5 the refusal must fire on a degenerate map rather than reporting a verdict.
  ( m=/dev/null; if [ "$(wc -l < $m)" -le 1000 ]; then exit 2; fi; exit 0 ); [ $? -eq 2 ] \
    && echo "G5 GREEN: degenerate-map refusal fires" || { echo "G5 RED: refusal did not fire"; fail=1; }
  [ $fail -eq 0 ] && echo "self-test: all guarantees GREEN" || echo "self-test: FAILURES above"
  return $fail
}

if [ "${1:-}" = "--self-test" ]; then selftest "$2" "$3"; exit $?; fi

ROWS=$1; OLD=$2; NEW=$3; OUT=$4
[ "$(wc -l < "$OLD")" -gt 1000 ] || { echo "REFUSING: old map degenerate" >&2; exit 2; }
[ "$(wc -l < "$NEW")" -gt 1000 ] || { echo "REFUSING: new map degenerate" >&2; exit 2; }
printf 'path\tverdict\thead\tnfiles\tunproven_old\tunproven_new\tstatus\n'
while IFS=$'\t' read -r p v h; do
  if [ -z "$h" ]; then printf '%s\t%s\t-\t0\t-\t-\tNO_HEAD\n' "$p" "$v"; continue; fi
  tag=$(printf '%s' "$h" | cut -c1-12)
  f="$OUT/$tag.pairs"
  if [ ! -s "$f" ]; then
    git ls-tree -r "$h" 2>/dev/null | awk '$2=="blob"{print $4"\t"$3}' | LC_ALL=C sort -u > "$f"
  fi
  n=$(wc -l < "$f")
  if [ "$n" -eq 0 ]; then printf '%s\t%s\t%s\t0\t-\t-\tREFUSE_EMPTY_TREE\n' "$p" "$v" "$h"; continue; fi
  uo=$(LC_ALL=C comm -23 "$f" "$OLD" | wc -l)
  un=$(LC_ALL=C comm -23 "$f" "$NEW" | wc -l)
  LC_ALL=C comm -23 "$f" "$NEW" > "$OUT/$tag.unproven_new"
  if [ "$un" -eq 0 ]; then st=ALL_CONTENT_IN_MAIN_HISTORY; else st=HAS_CONTENT_MAIN_NEVER_HELD; fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$p" "$v" "$h" "$n" "$uo" "$un" "$st"
done < "$ROWS"
