#!/usr/bin/env bash
# nocomm_check.sh -- re-derive the differ set with awk, never comm.
# `comm` requires both inputs in the collation order IT expects; on a mismatch it warns and STILL
# EMITS, usually empty. An empty differ set is exactly what produces LANDED, so every LANDED that
# rests on "it owns files and none of them differ" is re-derived here by a route with no comm in it.
set -uo pipefail
while IFS=$'\t' read -r p repo head; do
  [ -n "$head" ] && [ -d "$repo" ] || continue
  mb=$(git -C "$repo" merge-base "$head" origin/main 2>/dev/null)
  n=0; d=0; first=""
  while read -r f; do
    [ -n "$f" ] || continue
    a=$(git -C "$repo" show "$head:$f" 2>/dev/null | sha256sum | cut -d' ' -f1)
    b=$(git -C "$repo" show "origin/main:$f" 2>/dev/null | sha256sum | cut -d' ' -f1)
    n=$((n+1)); [ "$a" = "$b" ] || { d=$((d+1)); [ -z "$first" ] && first="$f"; }
  done < <(git -C "$repo" diff --name-only "$mb" "$head" 2>/dev/null)
  [ "$d" -eq 0 ] && v=CONFIRMED_LANDED || v='**DISAGREES — LANDED IS WRONG**'
  printf '%s\t%s\towned=%s differing=%s %s\n' "$p" "$v" "$n" "$d" "$first"
done
