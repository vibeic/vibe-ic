#!/usr/bin/env bash
# evidence_selftest.sh -- jharv3's standard, applied to evidence_contract.py.
#
# Their finding: a self-test that asserts only that SOME check went red cannot tell "the check
# works" from "something else happened to shout". They deleted an entire check and the self-test
# still passed, because a different check fired on the same synthetic row.
#
# So each guarantee gets a case only IT catches, and is proven load-bearing in both arms:
#     unblinded must CATCH the case (exit non-zero)  AND  blinded must MISS it (exit 0)
# Passing only the first arm proves nothing: a checker that fails on everything passes it.
set -uo pipefail
CHK="${1:?usage: evidence_selftest.sh <evidence_contract.py> <verdicts.tsv>}"
SRC="${2:?}"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
python3 - "$SRC" "$T" <<'PY'
import re, sys, os
src, T = sys.argv[1], sys.argv[2]
L = open(src, encoding="utf-8", errors="replace").read().splitlines()
def build(name, sub):
    out=[L[0]]; done=0
    for ln in L[1:]:
        c=ln.split("\t")
        if len(c)>=3 and c[1]=="RECOVER" and not done:
            new,n = sub(c[2])
            if n: c[2]=new; done=1
        out.append("\t".join(c))
    open(os.path.join(T,name),"w",encoding="utf-8").write("\n".join(out)+"\n")
    return done
p=re.compile(r'(here,\s*)([0-9a-f]{64})(\s+on main)')
assert build("bad.tsv",   lambda s: p.subn(r'\g<1>'+'0'*64+r'\g<3>', s, count=1)), "no row to corrupt"
assert build("absent.tsv",lambda s: p.subn(r'\g<1>(no such path on origin/main)\g<3>', s, count=1)), "no row to flip"
open(os.path.join(T,"empty.tsv"),"w",encoding="utf-8").write(L[0]+"\n")
print("cases built")
PY
blind () { sed "$1" "$CHK" > "$T/blind.py"; }
run  () { python3 "$1" "$2" >/dev/null 2>&1; echo $?; }
fail=0
for spec in "hash-compare|s/            ok = (actual == claimed_main)/            ok = True/|bad.tsv" \
            "absent-branch|s/            ok = actual is None/            ok = True/|absent.tsv" \
            "non-empty-assert|s/^assert tot > 0.*/pass/|empty.tsv"; do
  IFS='|' read -r name sedexpr case_f <<< "$spec"
  blind "$sedexpr"
  u=$(run "$CHK" "$T/$case_f"); b=$(run "$T/blind.py" "$T/$case_f")
  if [ "$u" != "0" ] && [ "$b" = "0" ]; then printf '  %-18s unblinded=%s blinded=%s LOAD-BEARING\n' "$name" "$u" "$b"
  else printf '  %-18s unblinded=%s blinded=%s **NOT PROVEN**\n' "$name" "$u" "$b"; fail=1; fi
done

# jharv3's generalisation, and they were right that my standard was necessary and not sufficient:
# A CASE MUST ASSERT THE OUTCOME THE BRANCH ACTUALLY CHANGES. Both arms on pass/fail cannot see a
# branch that only moves a row between two NON-FAILING buckets. Mine has exactly one: the test
# that files an UNDETERMINED row as "no claim by design" rather than "claim I could not read".
# Blinding it moves 4 rows between those buckets and the exit code is 0 either way.
bucket () { python3 "$1" "$2" 2>/dev/null | tail -1 | sed 's/.*no_claim_by_design=\([0-9]*\).*DID_NOT_CHECK=\([0-9]*\).*/\1|\2/'; }
blind 's/        if "UNDETERMINED (" in c\[2\]:/        if False:/'
ub=$(bucket "$CHK" "$SRC"); bb=$(bucket "$T/blind.py" "$SRC")
ue=$(run "$CHK" "$SRC"); be=$(run "$T/blind.py" "$SRC")
if [ "$ub" != "$bb" ]; then
  printf '  %-18s buckets %s -> %s (exit %s -> %s) LOAD-BEARING BY BUCKET\n' "undetermined-class" "$ub" "$bb" "$ue" "$be"
  [ "$ue" = "$be" ] && printf '       note: exit code is identical both ways — pass/fail alone could NOT see this branch\n'
else
  printf '  %-18s buckets unchanged (%s) **NOT PROVEN**\n' "undetermined-class" "$ub"; fail=1
fi

[ "$fail" = "0" ] && echo "SELFTEST OK: every guarantee proven load-bearing, by failure or by bucket" || echo "SELFTEST FAILED"
exit $fail
