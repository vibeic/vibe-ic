#!/usr/bin/env bash
# Hermetic: a real repo holding a verdict file, real clones, no fleet. Arms cover the two questions
# the checker asks (is it still needed / is it true) and the parsing bugs that made it lie:
#   - IFS=tab collapses empty fields, shifting every later column left
#   - ssh reads stdin and truncates a while-read loop, which then reports no failures
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd); C="$here/corrections_check.sh"; G="$here/predelete_guard.sh"
R=$(mktemp -d); trap 'rm -rf "$R"' EXIT
UP="$R/up"; git init -q --bare "$UP"; git -C "$UP" symbolic-ref HEAD refs/heads/main
git init -q "$R/seed"; cd "$R/seed"; git config user.email t@t; git config user.name t
printf 'a\nb\nc\n' > f.txt; printf 'notice\n' > NOTICE
mkdir -p tools/harvest
git add -A; git commit -qm base; git branch -M main; git remote add o "$UP"; git push -q o main
MAIN=$(git rev-parse main); S=${MAIN:0:11}; cd "$R"
mk(){ git clone -q "$UP" "$R/$1"; git -C "$R/$1" config user.email t@t; git -C "$R/$1" config user.name t; git -C "$R/$1" checkout -q main; }
mk clean; mk dirty; echo changed > "$R/dirty/f.txt"; git -C "$R/dirty" commit -qam edit
mk stale; git -C "$R/stale" update-ref -d refs/remotes/origin/main
# a repo whose tools/harvest holds the verdict file the corrections target
mk vrepo
mkdir -p "$R/vrepo/tools/harvest"   # git does not track empty dirs, so the clone lacks it
printf 'host\tpath\tverdict\tevidence\tshard\n' > "$R/vrepo/tools/harvest/v.tsv"
printf '105\t%s\tLANDED\tvacuous\tx\n' "$R/dirty" >> "$R/vrepo/tools/harvest/v.tsv"
printf '105\t%s\tLANDED\tvacuous\tx\n' "$R/clean" >> "$R/vrepo/tools/harvest/v.tsv"
printf '105\t%s\tLANDED\tvacuous\tx\n' "$R/stale" >> "$R/vrepo/tools/harvest/v.tsv"
printf '105\t%s\tRECOVER\talready fixed\tx\n' "$R/dirty-applied" >> "$R/vrepo/tools/harvest/v.tsv"
git -C "$R/vrepo" add -A; git -C "$R/vrepo" commit -qm v
git -C "$R/vrepo" update-ref refs/remotes/origin/testbranch HEAD
export HARV_MAIN="$S" HARV_NO_FETCH=1 HARV_REF=refs/remotes/origin/testbranch
hdr=$'target_file\thost\tpath\tfrom_verdict\tto_verdict\tmeasured_on_host\tevidence\toriginal_shard\toriginal_evidence_was_vacuous\tprobe\tderived'
row(){ printf 'v.tsv\t105\t%s\t%s\tRECOVER\t105\tev\tx\tno\t%s\tsha\n' "$1" "${2:-LANDED}" "${3:-}"; }
rc=0
chk(){ out=$(bash "$C" "$4" "$G" "$R/vrepo" 2>&1); e=$?
  printf '  %-46s rc=%s' "$1" "$e"
  [ "$e" = "$2" ] || { printf '  FAIL(want rc=%s)' "$2"; rc=1; }
  printf '%s' "$out" | grep -q "$3" || { printf '  FAIL(want %s)' "$3"; rc=1; }
  printf '\n'; }
printf '%s\n' "$hdr" > "$R/t1"; row "$R/dirty" >> "$R/t1"
chk "needed AND true -> SUPPORTED"                0 SUPPORTED   "$R/t1"
printf '%s\n' "$hdr" > "$R/t2"; row "$R/clean" >> "$R/t2"
chk "needed but FALSE -> UNSUPPORTED"             1 UNSUPPORTED "$R/t2"
printf '%s\n' "$hdr" > "$R/t3"; row "$R/dirty-applied" >> "$R/t3"
chk "already fixed in the file -> APPLIED"        0 APPLIED     "$R/t3"
printf '%s\n' "$hdr" > "$R/t4"; row "$R/dirty" ABANDON >> "$R/t4"
chk "file no longer says from_verdict -> STALE"   1 STALE       "$R/t4"
printf '%s\n' "$hdr" > "$R/t5"; row "/nonexistent-path" >> "$R/t5"
chk "path absent from the file -> STALE"          1 STALE       "$R/t5"
NS=$(sha256sum "$R/stale/NOTICE" | cut -d' ' -f1)
printf '%s\n' "$hdr" > "$R/t6"; row "$R/stale" LANDED "NOTICE|deadbeef|$NS" >> "$R/t6"
chk "probe equals MAIN bytes -> REFUTED"          1 REFUTED     "$R/t6"
printf '%s\n' "$hdr" > "$R/t7"; row "$R/stale" >> "$R/t7"
chk "fail-closed, no probe -> UNMEASURED"         0 UNMEASURED  "$R/t7"
# the empty-field arm: probe is empty and MUST NOT absorb the next column
printf '%s\n' "$hdr" > "$R/t8"; row "$R/dirty" >> "$R/t8"
out=$(bash "$C" "$R/t8" "$G" "$R/vrepo" 2>&1)
printf '  %-46s' "empty probe field does not shift columns"
printf '%s' "$out" | grep -q 'probe' && { printf ' FAIL(probe consulted for an empty field)'; rc=1; } || printf ' ok'
printf '\n'
sed 's/^rows=\$((.*/rows=99/' "$C" > "$R/short.sh"   # only the rows= line; seen= is now separate; chmod +x "$R/short.sh"
out=$(bash "$R/short.sh" "$R/t1" "$G" "$R/vrepo" 2>&1); e=$?
printf '  %-46s rc=%s' "truncated loop -> denominator mismatch" "$e"
{ [ "$e" = 1 ] && printf '%s' "$out" | grep -q 'DENOMINATOR MISMATCH'; } || { printf '  FAIL'; rc=1; }; printf '\n'
[ $rc -eq 0 ] && echo "  PASS"; exit $rc
