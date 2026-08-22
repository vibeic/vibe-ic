#!/usr/bin/env bash
# Hermetic. Builds real repos locally and drives corrections_check.sh with mhost=105 so no host in
# the fleet is required. Five arms; the ALLOW/SUPPORTED arms are the ones that stop a checker that
# simply rejects everything from passing all the others.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd); C="$here/corrections_check.sh"; G="$here/predelete_guard.sh"
R=$(mktemp -d); trap 'rm -rf "$R"' EXIT
UP="$R/up"; git init -q --bare "$UP"
git init -q "$R/seed"; cd "$R/seed"; git config user.email t@t; git config user.name t
printf 'a\nb\nc\n' > f.txt; printf 'notice\n' > NOTICE; git add -A; git commit -qm base
git branch -M main; git remote add o "$UP"; git push -q o main
MAIN=$(git rev-parse main); S=${MAIN:0:11}
git -C "$UP" symbolic-ref HEAD refs/heads/main   # else clones warn and check out nothing
export HARV_MAIN="$S"                            # the guard defaults to the real repo's main otherwise
cd "$R"
mk(){ git clone -q "$UP" "$R/$1"; git -C "$R/$1" config user.email t@t; git -C "$R/$1" config user.name t; git -C "$R/$1" checkout -q main; }
mk clean
mk dirty; echo changed > "$R/dirty/f.txt"; git -C "$R/dirty" commit -qam edit
# A fail-closed clone: origin/main deleted, so the guard cannot measure and MUST consult the probe.
# The probe branch is only reachable in this state -- a measurable clone never gets there, which is
# why arms 3 and 4 need their own fixture rather than reusing the clean one.
mk stale; git -C "$R/stale" update-ref -d refs/remotes/origin/main
hdr=$'host\tpath\tfrom_verdict\tto_verdict\tmeasured_on_host\tevidence\toriginal_shard\toriginal_evidence_was_vacuous\tprobe'
row(){ printf '%s\t%s\tLANDED\tRECOVER\t105\t%s\tx\tno\t%s\n' "105" "$1" "$2" "${3:-}"; }
rc=0
chk(){ # name expect_rc expect_grep file
  out=$(bash "$C" "$4" "$G" 2>&1); e=$?
  printf '  %-42s rc=%s' "$1" "$e"
  [ "$e" = "$2" ] || { printf '  FAIL(rc expected %s)' "$2"; rc=1; }
  printf '%s' "$out" | grep -q "$3" || { printf '  FAIL(missing %s)' "$3"; rc=1; }
  printf '\n'
}
printf '%s\n' "$hdr" > "$R/t1"; row "$R/dirty" "real content" >> "$R/t1"
chk "correction on a tree that DOES hold content" 0 SUPPORTED "$R/t1"
printf '%s\n' "$hdr" > "$R/t2"; row "$R/clean" "fabricated" >> "$R/t2"
chk "correction on a CLEAN tree" 1 UNSUPPORTED "$R/t2"
NS=$(sha256sum "$R/stale/NOTICE" | cut -d' ' -f1)
printf '%s\n' "$hdr" > "$R/t3"; row "$R/stale" "probe equals main" "NOTICE|deadbeef|$NS" >> "$R/t3"
chk "probe bytes EQUAL main (fail-closed clone)" 1 REFUTED "$R/t3"
printf '%s\n' "$hdr" > "$R/t4"; row "$R/stale" "probe matches nothing" "NOTICE|aaa|bbb" >> "$R/t4"
chk "probe matches neither side" 1 UNSUPPORTED "$R/t4"
printf '%s\n' "$hdr" > "$R/t5"; row "$R/stale" "no probe at all" >> "$R/t5"
chk "fail-closed with NO probe -> unmeasured, not support" 0 UNMEASURED "$R/t5"
sed 's/^rows=$((.*$/rows=99/' "$C" > "$R/short.sh"; chmod +x "$R/short.sh"
out=$(bash "$R/short.sh" "$R/t1" "$G" 2>&1); e=$?
printf '  %-42s rc=%s' "truncated loop (denominator)" "$e"
{ [ "$e" = 1 ] && printf '%s' "$out" | grep -q 'DENOMINATOR MISMATCH'; } || { printf '  FAIL'; rc=1; }; printf '\n'
[ $rc -eq 0 ] && echo "  PASS"; exit $rc
