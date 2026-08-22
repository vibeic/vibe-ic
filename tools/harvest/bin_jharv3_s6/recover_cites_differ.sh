#!/bin/bash
# recover_cites_differ.sh <verdicts.tsv> <out.tsv>
# CONTRACT CHECK for RECOVER: "name at least one file whose sha256 differs from main."
# For each RECOVER row, take every token cited before `sha256` and ask whether that
# path's blob in the row's judged HEAD tree differs from origin/main's blob at the
# same path (absent from main counts as differing).
#
# Two regexes were wrong before this one, both mine, not the data:
#   - requiring a leading alnum missed the dotfile `.image-version-ignore`
#   - requiring a file extension missed it again (it has no second dot)
# Hence: take whatever token precedes `sha256` and let the repo decide if it is a path.
#
# Rows whose recoverable content is a working-tree edit or an untracked file resolve
# to nothing here BY CONSTRUCTION -- that content is in no tree. Those are reported
# as NO_CITED_PATH_RESOLVED, which is a prompt to check the preservation ref by hand,
# NOT a pass and NOT a failure.
set -u; MAIN=${MAIN:-a4caccefe}; IN="${1:?}"; OUT="${2:?}"
: > "$OUT"
python3 - "$IN" <<'PY' | while IFS=$'\t' read -r p head cites; do
import re,sys
rows=[l.rstrip('\n').split('\t') for l in open(sys.argv[1],encoding='utf-8')][1:]
pat=re.compile(r'(\S+)\s+sha256')
for r in rows:
    if len(r)!=3 or r[1]!="RECOVER": continue
    cs=[]
    for m in pat.finditer(r[2]):
        c=m.group(1).strip('`",;()')
        if c and not c.endswith(':') and c not in cs: cs.append(c)
    h=re.findall(r'\[worktree HEAD when judged: ([0-9a-f]{40})',r[2])
    print("%s\t%s\t%s"%(r[0], h[0] if h else "-", ",".join(cs) if cs else "-"))
PY
  res="NO_CITED_PATH_RESOLVED"; det=""
  IFS=',' read -ra CS <<< "$cites"
  for c in "${CS[@]}"; do
    case "$c" in ""|to|is|and|at|of|the|a) continue;; esac
    inmain=$(git rev-parse "$MAIN:$c" 2>/dev/null); intree=""
    [ "$head" != "-" ] && intree=$(git rev-parse "$head:$c" 2>/dev/null)
    if [ -n "$intree" ]; then
      if [ -z "$inmain" ]; then res="DIFFERS_absent_from_main"; det="$c"; break; fi
      if [ "$intree" != "$inmain" ]; then res="DIFFERS"; det="$c"; break; fi
      res="IDENTICAL_TO_MAIN"; det="$c"
    fi
  done
  echo -e "$p\t$res\t$det" >> "$OUT"
done
n=$(wc -l < "$OUT"); bad=$(grep -c 'IDENTICAL_TO_MAIN' "$OUT" || true)
echo "$n RECOVER rows checked; $bad cite a file identical to main"
[ "$n" -eq 0 ] && { echo "REFUSING: examined 0 rows." >&2; exit 2; }
exit 0
