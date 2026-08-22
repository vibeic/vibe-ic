#!/usr/bin/env bash
# The FRESHNESS loop, as opposed to check_all.sh's internal-consistency loop.
#
# check_all.sh asks "is this directory self-consistent?" and needs only the checkout. This asks
# "is it still TRUE?" and needs the network and, for the corrections, the fleet. I ran it by hand
# four times; each run found something -- a peer flipping rows to LANDED, a branch deleted under
# 237 citations, three clones stale against a moved main.
#
# Reports rather than fixes. Every remedy here is a judgement call: re-measuring a drifted row,
# fetching a clone FORWARD, re-pointing a citation. A script that did them unattended would be the
# same reflex that pushed refs to fifteen unrelated repositories.
set -uo pipefail
H=${1:-tools/harvest}
R=${2:-/home/reyerchu/vibe-ic}
B=$(cd "$(dirname "$0")" && pwd)
bad=0
echo "== 1. main =="
LIVE=$(timeout 300 git -C "$R" ls-remote origin main 2>/dev/null | awk '{print substr($1,1,11)}')
if [ -z "$LIVE" ]; then echo "  cannot reach origin -- refusing to report freshness against a cache"; exit 2; fi
timeout 400 git -C "$R" fetch -q origin main 2>/dev/null || true
echo "  live origin/main: $LIVE"
# Collect the mains the rows were JUDGED against. The first pattern here matched nothing and the
# section printed no lines at all -- a check finding zero things to check, reporting success. The
# count is asserted below so that can never pass silently again.
mains=$(grep -ohE '(against |vs )?(origin/)?main [0-9a-f]{9,11}|vs [0-9a-f]{9,11}' "$H"/*.tsv 2>/dev/null \
        | grep -oE '[0-9a-f]{9,11}' | sort -u)
nm=$(printf '%s\n' "$mains" | grep -c . || true)
if [ "${nm:-0}" -eq 0 ]; then
  echo "  *** no judged-main sha found in any row -- this check is VACUOUS, not passing ***"; bad=$((bad+1))
fi
echo "  distinct judged mains found in the rows: ${nm:-0}"
# Most of those 72 are partial shas or blob ids scraped out of prose. `cat-file -e || continue`
# skipped every one of them and the section printed NOTHING -- a loop that examines zero candidates
# and reports success, the third time that shape appeared in this one script. Count what was
# actually resolved and assert it is non-zero.
checked=0; skipped=0
for m in $(printf '%s\n' "$mains"); do
  c=$(git -C "$R" rev-parse -q --verify "$m^{commit}" 2>/dev/null) || { skipped=$((skipped+1)); continue; }
  [ -n "$c" ] || { skipped=$((skipped+1)); continue; }
  checked=$((checked+1))
  if git -C "$R" merge-base --is-ancestor "$c" origin/main 2>/dev/null; then
    echo "  $m ancestor (+$(git -C "$R" rev-list --count $c..origin/main))"
  else
    echo "  *** $m NOT an ancestor -- main was rewritten; rows need RE-JUDGING, not re-labelling ***"; bad=$((bad+1))
  fi
done
echo "  resolved to a commit: $checked   not a commit here (partial sha, blob, absent): $skipped"
if [ "$checked" -eq 0 ]; then
  echo "  *** none of the $nm candidates resolved to a commit -- nothing was compared ***"; bad=$((bad+1))
fi
echo "== 2. deletion-bound coverage =="
python3 - "$H" <<'PY'
import csv,sys,os
H=sys.argv[1]
db={(r[0],r[1]) for r in list(csv.reader(open(os.path.join(H,'verdicts_all.tsv')),delimiter='\t'))[1:] if len(r)>=3 and r[2] in ('LANDED','ABANDON')}
have=set()
for f in ('JOINED_DELETION_GUARD_RESULTS.tsv','EXTRAS_DELETION_GUARD_RESULTS.tsv'):
    p=os.path.join(H,f)
    if not os.path.exists(p): continue
    for r in list(csv.reader(open(p),delimiter='\t'))[1:]:
        if len(r)>=2: have.add((r[0],r[1]))
h108=set()
p=os.path.join(H,'shard_c','108_DROP_guard_results.tsv')
if os.path.exists(p):
    h108={r[0] for r in list(csv.reader(open(p),delimiter='\t'))[1:] if r}
miss=[k for k in db if k not in have and k[1] not in h108]
print(f"  {len(db)-len(miss)} of {len(db)} have a recorded guard result")
for k in miss[:10]: print(f"    UNCOVERED {k[0]} {k[1]}")
sys.exit(1 if miss else 0)
PY
[ $? -eq 0 ] || bad=$((bad+1))
echo "== 3. corrections still supported =="
out=$(timeout 900 bash "$B/corrections_check.sh" "$H/verdicts_joined_corrections.tsv" 2>&1) || true
printf '%s\n' "$out" | tail -1 | sed 's/^/  /'
printf '%s' "$out" | grep -qE 'unsupported=[1-9]|stale=[1-9]' && { echo "  -> a correction no longer holds"; bad=$((bad+1)); }
printf '%s' "$out" | grep -qE 'unmeasured=[1-9]' && echo "  -> some rows UNMEASURED (usually a clone stale against the moved main; fetch it FORWARD and re-run)"
echo "== 4. survivability citations =="
timeout 900 python3 "$B/live_ref_citation_check.py" "$H" 2>&1 | tail -3 | sed 's/^/  /'
echo
echo "# freshness problems needing a judgement call: $bad"
exit $([ "$bad" -eq 0 ] && echo 0 || echo 1)
