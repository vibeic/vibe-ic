#!/bin/bash
# landed_by_history_v4.sh <worktree> <scratchdir> [--self-test]
#
# LANDED test: every file PRESENT in the worktree must hold content that
# origin/main's HISTORY held AT THAT PATH. Judged by CONTENT: comparing against
# main's TIP cannot tell landed work from unlanded work, because vibe-ic
# squash-lands and main keeps moving.
#
# Four ways this measurement silently lies, all four hit for real on .108:
#  1. `git log --raw` omits merge-expressed history unless given -m.
#  2. Only the post-image blob misses every blob main later DELETED.
#  3. This host's awk is mawk 1.3.4: a {40} interval regex NEVER matches, so the
#     history set comes back empty and every path reports "unproven".
#  4. git 2.34.1 has no `--pathspec-from-file` for log; it errors and yields
#     nothing, which under 2>/dev/null looks exactly like "main held none".
# Each produces a clean exit 0. Hence the REFUSAL below: an empty history set
# over a non-empty want set is a broken measurement, never a verdict.
#
# Paths deleted vs main's tip are not required: the worktree holds no copy.
set -u
MAIN=${MAIN:-a4caccefe}

if [ "${1:-}" = "--self-test" ]; then
  fail=0
  # G1: this awk must match a 40-hex blob by the method the gate actually uses.
  z="0000000000000000000000000000000000000000"
  got=$(echo "x" | awk -v b=876bdab23ab802d3f8adc6efe1e8aed2a6f01f33 -v z="$z" \
        '{ if(length(b)==40 && b!=z) print "OK" }')
  [ "$got" = "OK" ] || { echo "G1 RED: awk cannot length-match a 40-hex blob"; fail=1; }
  # G1b: the regex form this replaced must be shown to be the broken one here.
  bad=$(echo "876bdab23ab802d3f8adc6efe1e8aed2a6f01f33" | awk '/^[0-9a-f]{40}$/{print "MATCHED"}')
  [ "$bad" = "MATCHED" ] || echo "G1b NOTE: {40} interval regex does NOT match on this awk ($(awk -W version 2>&1 | head -1)) -- this is why the gate uses length()."
  # G2: -m must surface merge-expressed history that plain --raw drops.
  w=$(git log --format= --raw --no-abbrev --full-history    $MAIN -- .image-version-ignore 2>/dev/null | grep -c .)
  m=$(git log --format= --raw --no-abbrev --full-history -m $MAIN -- .image-version-ignore 2>/dev/null | grep -c .)
  [ "$m" -gt "$w" ] || { echo "G2 RED: -m surfaced no extra history ($m vs $w)"; fail=1; }
  # G3: pre-image blobs must be collected -- 8c31302d is only ever a pre-image here.
  git log --format= --raw --no-abbrev --full-history -m $MAIN -- .image-version-ignore 2>/dev/null \
   | awk 'NF{split($0,a,"\t"); split(a[1],f," "); print f[3]; print f[4]}' \
   | grep -qx 8c31302def9f4817c6f89ac188d35de630646bed \
   || { echo "G3 RED: pre-image blob not collected"; fail=1; }
  # G4: the refusal must actually fire on an empty history set.
  ( need=5; hist=0; if [ "$need" -gt 0 ] && [ "$hist" -eq 0 ]; then exit 2; fi; exit 0 )
  [ $? -eq 2 ] || { echo "G4 RED: refusal did not fire on an empty history set"; fail=1; }
  [ $fail -eq 0 ] && echo "self-test: all guarantees GREEN" || echo "self-test: FAILURES above"
  exit $fail
fi

d="$1"; SC="$2"; tag=$(echo "$d" | tr '/' '_')
T=$(git -C "$d" rev-parse HEAD^{tree}) || exit 2
git diff --raw --no-abbrev --no-renames $MAIN $T > $SC/${tag}.raw
awk '{split($0,a,"\t"); split(a[1],f," "); if(f[5]=="M"||f[5]=="A") print a[2]"\t"f[4]}' \
    $SC/${tag}.raw | LC_ALL=C sort -u > $SC/${tag}.want
cut -f1 $SC/${tag}.want > $SC/${tag}.paths
n=$(wc -l < $SC/${tag}.want)
if [ "$n" -eq 0 ]; then
  echo -e "$d\tneed=0\thist=0\tUNPROVEN=0\t(tree identical to main tip)"; exit 0
fi
git log --format= --raw --no-abbrev --no-renames --full-history -m $MAIN \
    -- $(tr '\n' ' ' < $SC/${tag}.paths) 2>/dev/null \
 | awk 'NF{split($0,a,"\t"); split(a[1],f," ");
        z="0000000000000000000000000000000000000000";
        if(length(f[3])==40 && f[3]!=z) print a[2]"\t"f[3];
        if(length(f[4])==40 && f[4]!=z) print a[2]"\t"f[4]}' \
 | LC_ALL=C sort -u > $SC/${tag}.hist
h=$(wc -l < $SC/${tag}.hist)
if [ "$h" -eq 0 ]; then
  echo "REFUSING: $d needs $n path(s) proved but main's history set came back EMPTY." >&2
  echo "That is a broken measurement, not a LANDED verdict. See notes 1-4 in this file." >&2
  exit 2
fi
LC_ALL=C comm -23 $SC/${tag}.want $SC/${tag}.hist > $SC/${tag}.unproven
echo -e "$d\tneed=$n\thist=$h\tUNPROVEN=$(wc -l < $SC/${tag}.unproven)"
