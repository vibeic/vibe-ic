#!/usr/bin/env bash
# Re-verify every row of verdicts_joined_corrections.tsv against the machine that holds it.
# A corrections file is a claim like any other; without this it is my word against joined's.
#
# Dispatches predelete_guard.sh to the host named in the row. A correction to RECOVER is supported
# only if the guard REFUSES with measured content -- not merely refuses. "no git dir", "not present"
# and a disagreeing origin/main are fail-closed states, NOT evidence, and are reported separately;
# counting them as support would let an unreachable host confirm any correction I cared to write.
# `ssh` READS STDIN. Inside a `while read` loop it swallows the rest of the input file, so the loop
# runs once and reports a clean exit -- measured: 1 of 10 rows checked, "unsupported=0", rc=0. Every
# ssh/scp below therefore takes -n, and the row count is asserted against the file at the end,
# because a loop that silently stops early is indistinguishable from a loop that found nothing wrong.
set -uo pipefail
F=${1:?usage: corrections_check.sh <corrections.tsv> [guard]}
G=${2:-$(cd "$(dirname "$0")" && pwd)/predelete_guard.sh}
EXPECT=${HARV_MAIN:-81cd5321b08}
HOP=${HARV_HOP:-192.168.1.102}
sup=0; unsup=0; unmeas=0; rc=0
while IFS=$'\t' read -r host path from to mhost ev shard vac probe; do
  [ "$host" = host ] && continue
  [ -n "$path" ] || continue
  ip=192.168.1.$mhost
  if [ "$mhost" = 105 ]; then
    out=$(printf '%s\n' "$path" | bash "$G" "$EXPECT" 2>/dev/null | head -1)
  else
    scp -q -o BatchMode=yes -o ConnectTimeout=10 "$G" "$HOP:/tmp/_cc_guard.sh" </dev/null 2>/dev/null
    out=$(timeout 300 ssh -n -o BatchMode=yes -o ConnectTimeout=12 "$HOP" \
      "scp -q -o BatchMode=yes -o ConnectTimeout=10 /tmp/_cc_guard.sh $ip:/tmp/_cc_guard.sh 2>/dev/null && ssh -o BatchMode=yes -o ConnectTimeout=10 $ip 'printf \"%s\\n\" \"$path\" | bash /tmp/_cc_guard.sh $EXPECT'" 2>/dev/null | head -1)
  fi
  v=${out%%$'\t'*}; why=$(printf '%s' "$out" | cut -f3-)
  case "$why" in
    *not_contained_in_main=*|*uncommitted_differing=*)
       if [ "$v" = REFUSE ] && [ "$to" = RECOVER ]; then
         # refused WITH measured content -- but the numbers must not both be zero
         nc=$(printf '%s' "$why" | sed -n 's/.*not_contained_in_main=\([0-9]*\).*/\1/p'); nc=${nc:-0}
         uc=$(printf '%s' "$why" | sed -n 's/.*uncommitted_differing=\([0-9]*\).*/\1/p'); uc=${uc:-0}
         if [ $((nc+uc)) -gt 0 ]; then
           printf 'SUPPORTED   %-42s %s\n' "$(basename "$path")" "$why"; sup=$((sup+1))
         else
           printf 'UNSUPPORTED %-42s refused but measured nothing: %s\n' "$(basename "$path")" "$why"; unsup=$((unsup+1)); rc=1
         fi
       else
         printf 'UNSUPPORTED %-42s guard says %s (correction claims %s)\n' "$(basename "$path")" "$v" "$to"; unsup=$((unsup+1)); rc=1
       fi;;
    *)
       # A fail-closed state is not evidence. But a row whose HEAD object has been gc'd is still
       # verifiable by its NAMED bytes: hash one file on the host and compare both ways. The probe
       # must match the worktree sha AND differ from the main sha -- matching only one proves
       # nothing, and a probe that equals main's bytes REFUTES the correction.
       if [ -n "${probe:-}" ]; then
         pf=${probe%%|*}; rest=${probe#*|}; pw=${rest%%|*}; pm=${rest##*|}
         if [ "$mhost" = 105 ]; then got=$(sha256sum "$path/$pf" 2>/dev/null | cut -d' ' -f1)
         else got=$(timeout 300 ssh -n -o BatchMode=yes -o ConnectTimeout=12 "$HOP" \
                "ssh -n -o BatchMode=yes -o ConnectTimeout=10 $ip 'sha256sum \"$path/$pf\" 2>/dev/null | cut -d\" \" -f1'" 2>/dev/null); fi
         if [ -z "$got" ]; then
           printf 'UNMEASURED  %-42s probe file unreadable: %s\n' "$(basename "$path")" "$pf"; unmeas=$((unmeas+1))
         elif [ "$got" = "$pm" ]; then
           printf 'REFUTED     %-42s probe equals MAIN bytes -- the correction is wrong\n' "$(basename "$path")"; unsup=$((unsup+1)); rc=1
         elif [ "$got" = "$pw" ]; then
           printf 'SUPPORTED   %-42s by probe: %s sha256 %s here, %s on main\n' "$(basename "$path")" "$pf" "${got:0:16}" "${pm:0:16}"; sup=$((sup+1))
         else
           printf 'UNSUPPORTED %-42s probe sha %s matches neither the claimed worktree nor main bytes\n' "$(basename "$path")" "${got:0:16}"; unsup=$((unsup+1)); rc=1
         fi
       else
         printf 'UNMEASURED  %-42s %s -- fail-closed state, not evidence\n' "$(basename "$path")" "${why:-no answer}"; unmeas=$((unmeas+1))
       fi;;
  esac
done < "$F"
rows=$(( $(grep -c '' "$F") - 1 ))
seen=$((sup+unsup+unmeas))
printf '# supported=%s unsupported=%s unmeasured=%s   checked=%s of %s rows\n' "$sup" "$unsup" "$unmeas" "$seen" "$rows"
if [ "$seen" -ne "$rows" ]; then
  printf '*** DENOMINATOR MISMATCH: the loop saw %s of %s rows. A short loop reports no failures.\n' "$seen" "$rows"
  rc=1
fi
[ "$unsup" -eq 0 ] || rc=1
exit $rc
