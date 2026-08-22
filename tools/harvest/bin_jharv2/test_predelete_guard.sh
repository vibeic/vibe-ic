#!/usr/bin/env bash
# Four arms. The ALLOW arm is not optional: a guard that refuses everything satisfies every
# REFUSE case and protects nothing, and its output is indistinguishable from a careful one.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd); G="$here/predelete_guard.sh"
R=$(mktemp -d); trap 'rm -rf "$R"' EXIT
UP="$R/upstream"; git init -q --bare "$UP"
mk() { # $1=name -> a clone with origin/main, returns path
  git clone -q "$UP" "$R/$1" 2>/dev/null; git -C "$R/$1" config user.email t@t; git -C "$R/$1" config user.name t; }
git init -q "$R/seed"; git -C "$R/seed" config user.email t@t; git -C "$R/seed" config user.name t
echo base > "$R/seed/f.txt"; git -C "$R/seed" add f.txt; git -C "$R/seed" commit -qm base
git -C "$R/seed" branch -M main; git -C "$R/seed" remote add o "$UP"; git -C "$R/seed" push -q o main
MAIN=$(git -C "$R/seed" rev-parse main); SHORT=${MAIN:0:11}
rc=0
say() { printf '  %-46s %s\n' "$1" "$2"; }

mk clean; git -C "$R/clean" checkout -q main
out=$(printf '%s\n' "$R/clean" | bash "$G" "$SHORT"); v=${out%%$'\t'*}
say "clean worktree" "$v"; [ "$v" = ALLOW ] || { echo "  FAIL: a clean worktree must be ALLOWed or the guard protects nothing"; rc=1; }

mk dirtyc; git -C "$R/dirtyc" checkout -q main; echo changed > "$R/dirtyc/f.txt"
git -C "$R/dirtyc" commit -qam edit
out=$(printf '%s\n' "$R/dirtyc" | bash "$G" "$SHORT"); v=${out%%$'\t'*}
say "committed content not on main" "$v"; [ "$v" = REFUSE ] || { echo "  FAIL"; rc=1; }

mk dirtyu; git -C "$R/dirtyu" checkout -q main; mkdir -p "$R/dirtyu/scratch/deep"
echo only-copy > "$R/dirtyu/scratch/deep/x.py"
out=$(printf '%s\n' "$R/dirtyu" | bash "$G" "$SHORT"); v=${out%%$'\t'*}
say "untracked, inside a directory" "$v"
[ "$v" = REFUSE ] || { echo "  FAIL: the collapse case -- -unormal would report 0 here"; rc=1; }

out=$(printf '%s\n' "$R/does-not-exist" | bash "$G" "$SHORT"); v=${out%%$'\t'*}
say "absent path (unmeasurable)" "$v"
[ "$v" = REFUSE ] || { echo "  FAIL: unmeasured must not read as clean"; rc=1; }

mk stale; git -C "$R/stale" checkout -q main
git -C "$R/stale" update-ref refs/remotes/origin/main "$MAIN"
out=$(printf '%s\n' "$R/stale" | bash "$G" "deadbeef123"); v=${out%%$'\t'*}
say "clone disagrees with expected main" "$v"
[ "$v" = REFUSE ] || { echo "  FAIL: a divergent origin/main manufactures false LANDEDs"; rc=1; }

printf '%s\n%s\n' "$R/clean" "$R/dirtyc" | bash "$G" "$SHORT" >/dev/null 2>&1; e=$?
say "exit code with one refusal in the set" "$e"
[ "$e" -ne 0 ] || { echo "  FAIL: must exit non-zero"; rc=1; }
[ $rc -eq 0 ] && echo "  PASS"; exit $rc
