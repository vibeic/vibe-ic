#!/usr/bin/env bash
# Re-verify verdicts_joined_corrections.tsv. Two independent questions per row, and both must hold:
#
#   1. IS IT STILL NEEDED?  The target file must still carry from_verdict for that path. A row is
#      keyed by (target_file, path), NOT by path -- measured: a fix applied to verdicts_joined.tsv
#      left the same three rows LANDED in verdicts_unreachable_resolved.tsv, so a path-keyed file
#      would have reported them done while a reader of the other file still deletes.
#   2. IS IT TRUE?  The worktree must still measure as holding content, on the host that holds it.
#
# A fail-closed state is UNMEASURED, never support: otherwise an unreachable host confirms any
# correction I care to write. Rows whose HEAD object has been gc'd carry a named probe instead.
#
# `ssh` reads stdin; inside a `while read` loop it swallows the rest of the file. Measured: the
# first version of this script reported "supported=1 unsupported=0", rc=0, having checked 1 of 10
# rows. Hence -n on every ssh, and the denominator assertion at the end.
set -uo pipefail
F=${1:?usage: corrections_check.sh <corrections.tsv> [guard] [repo]}
G=${2:-$(cd "$(dirname "$0")" && pwd)/predelete_guard.sh}
REPO=${3:-/home/reyerchu/vibe-ic}
# A CHECKER asks "is this true NOW", so it derives main LIVE -- a frozen constant here goes stale
# silently and turns every row into a fail-closed UNMEASURED. (The corrections FILE is a writer's
# artefact and records the main its measurement used; that one must not be live.)
EXPECT=${HARV_MAIN:-$(git -C "${3:-/home/reyerchu/vibe-ic}" ls-remote origin main 2>/dev/null | awk '{print substr($1,1,11)}')}
[ -n "$EXPECT" ] || { echo "cannot resolve live origin/main; refusing to check against a guess" >&2; exit 2; }
HOP=${HARV_HOP:-192.168.1.102}
# NOT FETCH_HEAD. Any `git fetch` anywhere in the session -- including one for `main` -- repoints
# FETCH_HEAD, and the lookups then read a tree where tools/harvest/*.tsv does not exist, so every
# row reports "row not found in that file any more". Measured: 16 of 16 STALE, from a fetch of main
# run one command earlier. Use a named ref and fetch it explicitly.
BRANCH=${HARV_BRANCH:-harvest/worktree-triage-jharvest}
REF=${HARV_REF:-refs/remotes/origin/$BRANCH}
[ -n "${HARV_NO_FETCH:-}" ] || git -C "$REPO" fetch -q origin "+refs/heads/$BRANCH:$REF" 2>/dev/null || true
git -C "$REPO" rev-parse -q --verify "$REF" >/dev/null 2>&1 || { echo "cannot resolve $REF" >&2; exit 2; }
sup=0; unsup=0; unmeas=0; applied=0; stale=0; rc=0
verdict_in_file() { # file path -> current verdict, via the header's own column names
  git -C "$REPO" show "$REF:tools/harvest/$1" 2>/dev/null | python3 -c '
import sys,csv
rows=list(csv.reader(sys.stdin,delimiter="\t"))
if not rows: sys.exit()
h=[x.strip() for x in rows[0]]
pc=h.index("path") if "path" in h else (1 if len(rows)>1 and len(rows[1])>1 and rows[1][1].startswith("/") else 0)
vc=h.index("verdict") if "verdict" in h else pc+1
t=sys.argv[1]
for r in rows[1:]:
    if len(r)>max(pc,vc) and r[pc]==t: print(r[vc]); break
' "$2"
}
# TAB IS IFS WHITESPACE. `IFS=$'\t' read` collapses consecutive tabs, so an EMPTY field vanishes
# and every later field shifts left. Measured: with probe empty, `probe` received the branch sha and
# 12 of 16 rows reported "probe unreadable" instead of measuring -- a confident wrong answer from a
# field that was correct in the file. Translate to a non-whitespace separator first; \037 (US) is
# not whitespace, so empty fields survive.
while IFS=$'\037' read -r tfile host path from to mhost ev shard vac probe derived; do
  [ "$tfile" = target_file ] && continue
  [ -n "$path" ] || continue
  cur=$(verdict_in_file "$tfile" "$path")
  if [ -z "$cur" ]; then
    printf 'STALE       %-26s %-34s row not found in that file any more\n' "$tfile" "$(basename "$path")"; stale=$((stale+1)); rc=1; continue
  elif [ "$cur" = "$to" ]; then
    printf 'APPLIED     %-26s %-34s already %s\n' "$tfile" "$(basename "$path")" "$cur"; applied=$((applied+1)); continue
  elif [ "$cur" != "$from" ]; then
    printf 'STALE       %-26s %-34s now %s, correction assumed %s\n' "$tfile" "$(basename "$path")" "$cur" "$from"; stale=$((stale+1)); rc=1; continue
  fi
  ip=192.168.1.$mhost
  if [ "$mhost" = 105 ]; then out=$(printf '%s\n' "$path" | bash "$G" "$EXPECT" 2>/dev/null | head -1)
  else
    scp -q -o BatchMode=yes -o ConnectTimeout=10 "$G" "$HOP:/tmp/_cc_guard.sh" </dev/null 2>/dev/null
    out=$(timeout 300 ssh -n -o BatchMode=yes -o ConnectTimeout=12 "$HOP" \
      "scp -q -o BatchMode=yes -o ConnectTimeout=10 /tmp/_cc_guard.sh $ip:/tmp/_cc_guard.sh 2>/dev/null && ssh -n -o BatchMode=yes -o ConnectTimeout=10 $ip 'printf \"%s\\n\" \"$path\" | bash /tmp/_cc_guard.sh $EXPECT'" 2>/dev/null | head -1)
  fi
  v=${out%%$'\t'*}; why=$(printf '%s' "$out" | cut -f3-)
  case "$why" in
    *not_contained_in_main=*|*uncommitted_differing=*)
      nc=$(printf '%s' "$why" | sed -n 's/.*not_contained_in_main=\([0-9]*\).*/\1/p'); nc=${nc:-0}
      uc=$(printf '%s' "$why" | sed -n 's/.*uncommitted_differing=\([0-9]*\).*/\1/p'); uc=${uc:-0}
      if [ "$v" = REFUSE ] && [ "$to" = RECOVER ] && [ $((nc+uc)) -gt 0 ]; then
        printf 'SUPPORTED   %-26s %-34s %s\n' "$tfile" "$(basename "$path")" "$why"; sup=$((sup+1))
      else
        printf 'UNSUPPORTED %-26s %-34s guard says %s: %s\n' "$tfile" "$(basename "$path")" "$v" "$why"; unsup=$((unsup+1)); rc=1
      fi;;
    *)
      if [ -n "${probe:-}" ]; then
        pf=${probe%%|*}; rest=${probe#*|}; pw=${rest%%|*}; pm=${rest##*|}
        if [ "$mhost" = 105 ]; then got=$(sha256sum "$path/$pf" 2>/dev/null | cut -d' ' -f1)
        else got=$(timeout 300 ssh -n -o BatchMode=yes -o ConnectTimeout=12 "$HOP" \
               "ssh -n -o BatchMode=yes -o ConnectTimeout=10 $ip 'sha256sum \"$path/$pf\" 2>/dev/null | cut -d\" \" -f1'" 2>/dev/null); fi
        if   [ -z "$got" ];      then printf 'UNMEASURED  %-26s %-34s probe unreadable\n' "$tfile" "$(basename "$path")"; unmeas=$((unmeas+1))
        elif [ "$got" = "$pm" ]; then printf 'REFUTED     %-26s %-34s probe equals MAIN bytes\n' "$tfile" "$(basename "$path")"; unsup=$((unsup+1)); rc=1
        elif [ "$got" = "$pw" ]; then printf 'SUPPORTED   %-26s %-34s by probe %s\n' "$tfile" "$(basename "$path")" "$pf"; sup=$((sup+1))
        else printf 'UNSUPPORTED %-26s %-34s probe matches neither side\n' "$tfile" "$(basename "$path")"; unsup=$((unsup+1)); rc=1; fi
      else
        printf 'UNMEASURED  %-26s %-34s %s -- fail-closed, not evidence\n' "$tfile" "$(basename "$path")" "${why:-no answer}"; unmeas=$((unmeas+1))
      fi;;
  esac
done < <(tr '\t' '\037' < "$F")
rows=$(( $(grep -c '' "$F") - 1 ))
seen=$((sup+unsup+unmeas+applied+stale))
printf '# supported=%s unsupported=%s unmeasured=%s already_applied=%s stale=%s   checked=%s of %s\n' \
  "$sup" "$unsup" "$unmeas" "$applied" "$stale" "$seen" "$rows"
[ "$seen" -eq "$rows" ] || { printf '*** DENOMINATOR MISMATCH: saw %s of %s rows. A short loop reports no failures.\n' "$seen" "$rows"; rc=1; }
exit $rc
