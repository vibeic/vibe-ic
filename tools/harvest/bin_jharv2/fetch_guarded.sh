#!/usr/bin/env bash
# fetch_guarded.sh <want-sha-prefix> -- fetch every clone named on stdin to the SAME origin/main,
# never fetching one whose origin is a LOCAL PATH: `git fetch origin main` there fetches that
# path's local branch and has already moved a correct ref BACKWARDS once. Those are repaired from
# a clone with a real remote instead. Refuses to report success unless every clone agrees.
set -uo pipefail
WANT="${1:?}"
mapfile -t C < /dev/stdin
for d in "${C[@]}"; do
  [ -d "$d/.git" ] || continue
  u=$(git -C "$d" config --get remote.origin.url 2>/dev/null)
  case "$u" in
    http*|git@*) flock -w 600 "$d/.git/h2.lock" git -C "$d" fetch --quiet --prune origin main 2>/dev/null || true;;
    *) echo "SKIP_LOCAL_ORIGIN $d ($u)";;
  esac
done
GOOD=""
for d in "${C[@]}"; do
  s=$(git -C "$d" rev-parse -q --verify origin/main 2>/dev/null)
  [ "${s:0:11}" = "$WANT" ] && { GOOD="$d"; break; }
done
[ -n "$GOOD" ] || { echo "NO_GOOD_CLONE_AT $WANT"; exit 1; }
for d in "${C[@]}"; do
  s=$(git -C "$d" rev-parse -q --verify origin/main 2>/dev/null)
  [ "${s:0:11}" = "$WANT" ] && continue
  git -C "$d" fetch -q "$GOOD" "+refs/remotes/origin/main:refs/remotes/origin/main" 2>/dev/null
  n=$(git -C "$d" rev-parse -q --verify origin/main 2>/dev/null)
  echo "REPAIRED $d ${s:0:11} -> ${n:0:11}"
done
bad=0
for d in "${C[@]}"; do s=$(git -C "$d" rev-parse -q --verify origin/main 2>/dev/null); [ "${s:0:11}" = "$WANT" ] || { bad=$((bad+1)); echo "STILL_WRONG $d ${s:0:11}"; }; done
echo "clones=${#C[@]} not_on_$WANT=$bad"
[ "$bad" -eq 0 ] || exit 1
