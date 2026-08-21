#!/usr/bin/env bash
# covered.sh -- is each sha on stdin reachable from something ORIGIN actually has right now?
# Authority: live branch heads + GitHub's refs/pull/*/head (a PR ref preserves a commit even
# when no branch does — 18 of 39 "orphans" turned out to be held that way).
# REFUSES TO RUN on an empty authority: the previous ad-hoc version of this check read an empty
# live-refs file and reported 21 findings, every one of them an artefact of the empty file.
set -uo pipefail
R=/home/reyerchu/vibe-ic
LIVE="${LIVE:?}"; PULLS="${PULLS:?}"
[ -s "$LIVE" ]  || { echo "REFUSING: live-refs authority is empty" >&2; exit 2; }
[ -s "$PULLS" ] || { echo "REFUSING: pull-refs authority is empty" >&2; exit 2; }
ok=0; bad=0
while read -r h; do
  [ -n "$h" ] || continue
  if grep -qxF "$h" "$PULLS"; then ok=$((ok+1)); echo "  PR_REF $h"; continue; fi
  hit=""
  while read -r c; do
    [ "$c" = "origin/HEAD" ] && continue
    if grep -qxF "${c#origin/}" "$LIVE"; then hit="$c"; break; fi
  done < <(git -C "$R" for-each-ref --format='%(refname:short)' --contains "$h" refs/remotes/origin 2>/dev/null)
  if [ -n "$hit" ]; then ok=$((ok+1)); echo "  LIVE_REF $h -> $hit"; else bad=$((bad+1)); echo "  **UNCOVERED** $h"; fi
done
echo "covered=$ok uncovered=$bad"
