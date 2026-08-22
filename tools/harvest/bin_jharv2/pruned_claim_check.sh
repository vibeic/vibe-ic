#!/usr/bin/env bash
# Verify a pruned checkout's ABANDON claim: "byte-identical to main commit <X>, changed nothing".
#
# A pruned checkout has no registration, so it has no HEAD, no merge-base, and no index to scope by.
# Comparing it to CURRENT main measures how far main has moved, not whether the claim is true --
# measured, that reads 891 differing files for a checkout whose tracked content is byte-perfect.
# The claim names a commit; verify against THAT commit.
#
# Files absent from the base are classified by `git check-ignore`, NOT by a pattern list. A
# hardcoded list of __pycache__/.pytest_cache/etc. missed reports/phase3/antenna.json, which
# .gitignore line 129 covers explicitly. The repo's own ignore rules are the authority on what is
# generated; my guess at them is not.
set -uo pipefail
DONOR=${1:?usage: pruned_claim_check.sh <donor-repo> < path<TAB>base-sha}
shift || true
while IFS=$'\t' read -r wt base; do
  [ -n "$wt" ] || continue
  [ -d "$wt" ] || { printf '  %-40s ABSENT\n' "$wt"; continue; }
  git -C "$DONOR" cat-file -e "$base^{commit}" 2>/dev/null || { printf '  %-40s BASE %s NOT IN DONOR -- cannot verify\n' "$wt" "$base"; continue; }
  same=0; diff=0; ign=0; real=0; ex=""; rex=""
  while IFS= read -r -d '' f; do
    rel=${f#$wt/}
    case "$rel" in .git/*|*/.git/*|.git) continue;; esac
    a=$(git -C "$DONOR" hash-object -- "$f" 2>/dev/null) || continue
    b=$(git -C "$DONOR" rev-parse -q --verify "$base:$rel" 2>/dev/null)
    if [ -n "$b" ]; then
      if [ "$a" = "$b" ]; then same=$((same+1)); else diff=$((diff+1)); [ -z "$ex" ] && ex="$rel"; fi
    else
      if git -C "$DONOR" check-ignore -q "$rel" 2>/dev/null; then ign=$((ign+1))
      else real=$((real+1)); [ -z "$rex" ] && rex="$rel"; fi
    fi
  done < <(find "$wt" -name .git -prune -o -type f -print0 2>/dev/null)
  v=CLAIM_HOLDS; [ $((diff+real)) -gt 0 ] && v='*** CLAIM FALSE ***'
  printf '  %-40s vs %s same=%-6s differ=%-4s ignored_extra=%-5s real_extra=%-4s %s%s%s\n' \
    "$(basename "$wt")" "${base:0:11}" "$same" "$diff" "$ign" "$real" "$v" \
    "${ex:+ first_differ=$ex}" "${rex:+ first_real=$rex}"
done
