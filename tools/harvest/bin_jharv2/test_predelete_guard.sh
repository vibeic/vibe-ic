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

# THE ARM THAT MATTERS. My first ALLOW arm used a worktree whose diff was EMPTY, so it never
# exercised the state every real worktree is in: its change is already in main, and main has moved
# on the same file since. A blob compare calls that "differing" and refuses. Measured: it refused
# all 29 of my ABANDON rows, every one of them wrongly. A guard that refuses everything protects
# nothing, and the trivial ALLOW arm could not see it.
mk landed; git -C "$R/landed" checkout -q main
printf 'a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n' > "$R/landed/g.txt"
git -C "$R/landed" add g.txt; git -C "$R/landed" commit -qm seed
git -C "$R/landed" push -q origin main 2>/dev/null
git -C "$R/landed" checkout -q -b feat
sed -i '2s/.*/b-CHANGED-BY-BRANCH/' "$R/landed/g.txt"; git -C "$R/landed" commit -qam branch-change
BR=$(git -C "$R/landed" rev-parse HEAD)
# main lands the branch's change AND moves further on the same file
mk adv; git -C "$R/adv" fetch -q origin; git -C "$R/adv" checkout -q main
git -C "$R/adv" pull -q origin main 2>/dev/null
sed -i '2s/.*/b-CHANGED-BY-BRANCH/' "$R/adv/g.txt"; sed -i '9s/.*/i-LATER-WORK-ON-MAIN/' "$R/adv/g.txt"
git -C "$R/adv" commit -qam "land branch change, plus later work"
git -C "$R/adv" push -q origin main 2>/dev/null
git -C "$R/landed" fetch -q origin main 2>/dev/null
NEWMAIN=$(git -C "$R/landed" rev-parse origin/main); NS=${NEWMAIN:0:11}
out=$(printf '%s\n' "$R/landed" | bash "$G" "$NS"); v=${out%%$'\t'*}
say "change landed, main moved on since" "$v"
[ "$v" = ALLOW ] || { echo "  FAIL: its own change IS in main; refusing it means refusing every real worktree"; rc=1; }
b=$(git -C "$R/landed" rev-parse -q --verify "HEAD:g.txt"); m=$(git -C "$R/landed" rev-parse -q --verify "origin/main:g.txt")
[ "$b" != "$m" ] || { echo "  FIXTURE WEAK: blobs are equal, so this arm does not exercise the case"; rc=1; }
say "  (fixture check: head blob != main blob)" "${b:0:8} vs ${m:0:8}"

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
