#!/usr/bin/env bash
# evidence.sh <clone> <head> <file> -- print verifiable sha256 evidence for one file.
# Emits: <sha_head> <sha_main|ABSENT_ON_MAIN> <lines_head> <lines_main> <first meaningful line>
set -uo pipefail
REPO=$1; HEAD=$2; F=$3
# A path the branch DELETED still differs from main in content, and saying so is the
# evidence -- hashing the absent side and printing the sha256 of nothing is not.
if ! git -C "$REPO" rev-parse -q --verify "$HEAD:$F" >/dev/null 2>&1; then
  b=$(git -C "$REPO" show "origin/main:$F" 2>/dev/null | sha256sum | cut -c1-16)
  lb=$(git -C "$REPO" show "origin/main:$F" 2>/dev/null | grep -c '')
  printf 'DELETED_BY_BRANCH\t%s\t0\t%s\tthe branch removes this path; main still carries it\n' "$b" "$lb"
  exit 0
fi
a=$(git -C "$REPO" show "$HEAD:$F" 2>/dev/null | sha256sum | cut -c1-16)
if git -C "$REPO" rev-parse -q --verify "origin/main:$F" >/dev/null 2>&1; then
  b=$(git -C "$REPO" show "origin/main:$F" 2>/dev/null | sha256sum | cut -c1-16)
  lb=$(git -C "$REPO" show "origin/main:$F" 2>/dev/null | grep -c '')
else b=ABSENT_ON_MAIN; lb=0; fi
la=$(git -C "$REPO" show "$HEAD:$F" 2>/dev/null | grep -c '')
d=$(git -C "$REPO" show "$HEAD:$F" 2>/dev/null | grep -m1 -E '^\s*(#|"""|//|--|\*)?\s*[A-Za-z]' | sed 's/^[[:space:]]*//; s/^["#/*-]*[[:space:]]*//' | cut -c1-110)
printf '%s\t%s\t%s\t%s\t%s\n' "$a" "$b" "$la" "$lb" "$d"
