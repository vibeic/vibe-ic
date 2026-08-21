#!/usr/bin/env python3
"""verify.py — re-run every self-check this capture batch claims to have passed.

WHY THIS FILE EXISTS
====================
The batch made about ten verification claims across as many working sessions:
that every record carries a measurement, that each buildable action names a
predicate / population / refusal, that no two patterns restate one class, that
every heading quotes its record verbatim, that the emitter's own summary agrees
with the records. Each was measured once, by hand, and then asserted in prose.

A check a human has to remember is not a check — which is the thesis of the
brief this batch answers. So the claims are here as one command.

FIVE OF THE BATCH'S OWN DEFECTS WERE AGREEMENT FAILURES, not missing elements:
a required field was present in both places and the two copies disagreed. Every
check below therefore compares two artefacts rather than inspecting one.

EVERY SCREEN CARRIES ITS CONTROL. Thirteen screens written for this batch
returned a number that could not be used, and three failed to find the case they
were written for. So each check here first runs an input it MUST flag; if the
control does not fail, the check reports itself broken rather than passing.

    python3 ppa-capture/verify.py          exit 0 = every claim re-measured true
"""
from __future__ import annotations
import json, re, sys, difflib, pathlib, collections

HERE = pathlib.Path(__file__).resolve().parent
RECS = json.loads((HERE / "recoveries.json").read_text())
MD   = (HERE / "RESULT.md").read_text()
CAND = HERE / "candidates"
fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def control(name: str, must_fail: bool) -> None:
    """A control that does not fail cannot validate anything (see A-27)."""
    if not must_fail:
        fails.append(f"CONTROL BROKEN: {name}")
        print(f"  BROKEN  control for {name} did not fail — its result is unusable")


# 1. bucket counts: records vs the table in the report
counts = collections.Counter(r["bucket"] for r in RECS)
for b in ("A", "C", "T"):
    m = re.search(rf"\| \*\*{b}\*\* \| (\d+) \|", MD)
    check(f"bucket {b} count agrees with the report table",
          bool(m) and int(m.group(1)) == counts[b],
          f"records {counts[b]}, table {m.group(1) if m else '-'}")

# 2. every record has a section, and the heading QUOTES the record verbatim
names = {r.get("rule_name", "").strip() for r in RECS} | \
        {r.get("title", "").strip() for r in RECS if r.get("title")}
heads = [(m.group(1), m.group(2).strip())
         for m in re.finditer(r"^### ([ACT]-\d+) · ([^·\n]+?) ·", MD, re.M)]
control("verbatim-heading", "a heading that is not a rule name" not in names)
check("every section heading quotes its record verbatim",
      all(h in names for _, h in heads), f"{len(heads)} headings")
check("one section per record", len(heads) == len(RECS),
      f"{len(heads)} sections, {len(RECS)} records")

# 3. every record carries a measurement (digits OR a spelled number)
NUMW = re.compile(r"\d|\b(zero|one|two|three|four|five|six|seven|eight|nine|ten"
                  r"|eleven|twelve|none|no )\b", re.I)
control("measurement", not NUMW.search("a bare assertion lacking quantity"))
# ^ the first control here read "a claim with no quantity at all", which the
#   pattern matched on the word "no" — the control was itself a positive.
#   The harness reported it BROKEN rather than passing, which is the point.
unmeasured = [r.get("rule_name") or r.get("title")
              for r in RECS if not NUMW.search(" ".join(map(str, r.values())))]
check("every record carries a measurement", not unmeasured, str(unmeasured))

# 4. buildability: predicate / population / refusal in every Bucket-A action
PRED = re.compile(r"(compar|diff|assert|resolv|count|enumerat|collect|walk|requir"
                  r"|check|pars|match|extract|group|partition|appl|import)", re.I)
POP  = re.compile(r"(every|each|all |per |over the|across|population|identifiers)", re.I)
REF  = re.compile(r"(refus|report|flag|rais|fail|reject|names? the|say)", re.I)
control("buildability", not all(rx.search("do it properly") for rx in (PRED, POP, REF)))
thin = [r["rule_name"] for r in RECS if r["bucket"] == "A"
        and not all(rx.search(str(r.get("fix_action", ""))) for rx in (PRED, POP, REF))]
check("every Bucket-A action names predicate, population and refusal",
      not thin, str(thin[:3]))

# 5. no near-duplicate patterns — autojunk MUST be off (see the correction in RESULT.md)
def sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _n(a), _n(b), autojunk=False).ratio()
def _n(s: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", str(s).lower()).split())
_b = RECS[0]["pattern"]
_near = _b.replace("A gate", "A check").replace("proves", "establishes")
control("similarity", sim(_b, _near) > 0.85 and sim(_b, RECS[7]["pattern"]) < 0.5)
worst = max((sim(x["pattern"], y["pattern"]), x["bucket"] + y["bucket"])
            for x, y in __import__("itertools").combinations(
                [r for r in RECS if str(r.get("pattern", "")).strip()], 2))
check("no two patterns restate one class", worst[0] < 0.60, f"max {worst[0]:.2f}")

# 6. B/C/D/T honest sentence rendered verbatim in the report
flat = " ".join(MD.split()).lower()
for r in RECS:
    if r["bucket"] in ("B", "C", "D", "T"):
        why = str(r.get("why_not_bucket_a") or r.get("why_discard") or "")
        probe = " ".join(why.split()[:9]).lower()
        check(f"honest sentence rendered verbatim [{r['bucket']}]",
              bool(probe) and probe in flat)

# 7. the emitter's own summary agrees with the records and with disk
s = json.loads((CAND / "summary.json").read_text())
check("summary totals agree with the records",
      all(s["totals"].get(k, 0) == counts.get(k, 0) for k in "ABCDT"))
claimed = sorted(pathlib.Path(f).name for f in s.get("bucket_A_files", []))
check("summary file list agrees with disk",
      claimed == sorted(p.name for p in CAND.glob("*.py")))

# 8. every sketch resolves back to a section by name
def slug(x: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", x.lower()).strip("_")[:80]
byslug = {slug(h) for _, h in heads}
defs = [d for f in CAND.glob("*.py")
        for d in re.findall(r"^def rule_(\w+)\(", f.read_text(), re.M)]
check("every sketch resolves to its section by name",
      all(d in byslug for d in defs), f"{len(defs)} sketches")

# 9. every Bucket-A rule has a row in the sweep table.
#    THIS ONE DRIFTED ONCE: the table was written at 14 rules and silently
#    stopped covering the batch as it grew to 26. A summary table is a second
#    copy of the record set, so it needs the same agreement check as the rest.
arows = set(re.findall(r"^\| (A-\d+|C-2) \| ", MD, re.M))
asecs = {sid for sid, _ in heads if sid.startswith("A-")}
control("sweep-table", "A-999" not in arows)
check("every Bucket-A rule has a sweep-table row",
      asecs <= arows, f"missing {sorted(asecs - arows)}")

# 10. every record routes to a step that exists, whose program is on disk.
#     The emitter warns about an unrouted record and does not fail; a routing
#     entry pointing at a deleted program would pass it silently.
PLUG = HERE.parent / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
ROUTING = json.loads((PLUG / "benchmark" / "CAPTURE_ROUTING.json").read_text())
control("routing", "no.such.step" not in ROUTING["steps"])
unrouted = [r.get("rule_name") or r.get("title") for r in RECS
            if r.get("step") not in ROUTING["steps"]]
check("every record names a routed step", not unrouted, str(unrouted[:3]))
badprog = [r.get("rule_name") for r in RECS if r["bucket"] == "A"
           and r.get("step") in ROUTING["steps"]
           and not (PLUG / (ROUTING["steps"][r["step"]].get("bucket_A_program") or "x")).is_file()]
check("every Bucket-A target program exists on disk", not badprog, str(badprog[:3]))

# 11. the already-program count in the title matches the two tables that hold it
WORDS = {"eleven": 11, "twelve": 12, "fourteen": 14, "fifteen": 15,
         "sixteen": 16, "seventeen": 17, "eighteen": 18}
m = re.search(r"and the (\w+) rules that were already programs", MD)
claimed = WORDS.get(m.group(1)) if m else None
# COUNT THE TWO ALREADY-PROGRAM TABLES STRUCTURALLY, by their header rows.
# Prose-anchored splitting was tried twice and was wrong twice (23, then 27):
# the anchors sit near other tables and the span swallowed them. A table is
# identified by its own header line and ends at the first non-table line.
def _table_rows(header: str) -> int:
    lines = MD.splitlines()
    try:
        i = next(k for k, l in enumerate(lines) if l.strip() == header)
    except StopIteration:
        return -1
    n, k = 0, i + 2                      # skip header and the --- separator
    while k < len(lines) and lines[k].startswith("| "):
        n, k = n + 1, k + 1
    return n
tbl = (_table_rows("| F | already enforced by | general over |")
       + _table_rows("| class | already enforced by |"))
control("already-program", claimed is not None)
check("the title's already-program count matches the tables",
      claimed == tbl, f"title {claimed}, tables {tbl}")

# 12. the brief's FIRST requirement: a rule for each of the eighteen findings.
#     That table is the primary deliverable and nothing checked it until now.
rule_rows = re.findall(r"^\| (\d{1,2}) \| ", MD, re.M)
seen = {int(x) for x in rule_rows}
# SEPARATION, not existence: asking for a rule that is not there must FAIL.
control("eighteen-rules", not (seen >= set(range(1, 20))))
check("a rule is stated for each of the eighteen findings",
      seen >= set(range(1, 19)), f"missing {sorted(set(range(1,19)) - seen)}")

# 13. the emitted backlogs still pass the sanitiser that consumes them.
#     Two of them were REFUSED on first write (see A-9); a later edit to a
#     field the sanitiser constrains would refuse them again, silently, because
#     nothing in this batch re-runs it.
import subprocess
SAN = PLUG / "programs" / "backlog_sanitize_check.py"
yamls = sorted(CAND.rglob("*.yaml"))
# SEPARATION: the sanitiser must REFUSE a deliberately malformed backlog.
# `SAN.is_file()` only proved the file exists, which validates nothing.
import tempfile
with tempfile.TemporaryDirectory() as _d:
    _bad = pathlib.Path(_d) / "ORGANIC-19700101-control.yaml"
    _bad.write_text("type: bug\ncomponent: not-a-valid-component-shape\n")
    _r = subprocess.run([sys.executable, str(SAN), "--file", str(_bad)],
                        capture_output=True, text=True, timeout=120)
control("sanitiser", SAN.is_file() and _r.returncode != 0)
bad_yaml = []
for y in yamls:
    r = subprocess.run([sys.executable, str(SAN), "--file", str(y)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        bad_yaml.append(y.name)
check("every emitted backlog passes its own sanitiser",
      not bad_yaml, f"{len(yamls)} checked, refused: {bad_yaml}")

# 14. the emitted artefacts are IN SYNC with the records that produced them.
#     candidates/ is generated. Edit recoveries.json without re-emitting and
#     the sketches go stale silently — they still resolve by name (check 8),
#     they still carry a plausible docstring, and they describe the previous
#     version of the rule. Name resolution cannot see content drift.
def _n(s: str) -> str:
    return " ".join(str(s).split())
_sk = _n("".join(f.read_text() for f in CAND.glob("*.py")))
_yl = _n("".join(f.read_text() for f in CAND.rglob("*.yaml")))
control("emitted-sync", _n("a field value that was never emitted anywhere") not in _sk)
drift = [(r.get("rule_name") or r.get("title"), f)
         for r in RECS
         for f in (("pattern", "docstring", "fix_action") if r["bucket"] == "A"
                   else ("pattern", "suggested_fix"))
         if _n(r.get(f, "")) and _n(r.get(f, "")) not in (_sk if r["bucket"] == "A" else _yl)]
check("every emitted artefact is in sync with its record",
      not drift, f"{len(drift)} stale field(s): {drift[:2]}")

# 15. the STATUS block. It read "15 records — 13 Bucket A" while the batch stood
#     at 29 and 26: the section a reader reads first, drifting for the whole
#     second half of the lane, because every other check walked the record set
#     and none walked the prose that summarises it.
W = {"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,
     "eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12}
m = re.search(r"\*\*STATUS\*\*: (\d+) records emitted and validated — (\d+) Bucket A, "
              r"(\d+) C, (\d+) T", MD)
control("status-block", m is not None)
if m:
    got = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    want = (len(RECS), counts["A"], counts["C"], counts["T"])
    check("the STATUS block agrees with the record set", got == want,
          f"status {got}, records {want}")
else:
    check("the STATUS block agrees with the record set", False, "STATUS line not parseable")

# 16. the Bucket-A ladder split must add up to the Bucket-A record count.
la = re.search(r"\| \*\*AUGMENT-EXISTING\*\* \| (\d+) \|", MD)
le = re.search(r"\| \*\*EXTRACT-NEW\*\* \| (\d+) \|", MD)
control("ladder", la is not None and le is not None)
check("the Bucket-A ladder split totals the Bucket-A records",
      bool(la and le) and int(la.group(1)) + int(le.group(1)) == counts["A"],
      f"{la.group(1) if la else '-'} + {le.group(1) if le else '-'} vs {counts['A']}")

# 17. every artefact named as ENFORCING an already-program class must exist.
#     Sixteen findings produced no record because "a program already covers
#     this". Each names the program. Rename or delete one and the claim becomes
#     false in the quietest possible way — the sentence still reads correctly
#     and the class is no longer covered. This is A-7's shape applied to the
#     part of the deliverable that argues something needs no work.
def _tbl_rows(header: str) -> list:
    lines = MD.splitlines()
    try:
        i = next(k for k, l in enumerate(lines) if l.strip() == header)
    except StopIteration:
        return []
    out, k = [], i + 2
    while k < len(lines) and lines[k].startswith("| "):
        out.append(lines[k]); k += 1
    return out
_cells = (_tbl_rows("| F | already enforced by | general over |")
          + _tbl_rows("| class | already enforced by |"))
_named = set()
for _c in _cells:
    _named |= set(re.findall(r"`([A-Za-z0-9_./-]+\.(?:py|md|json))`", _c))
    _named |= set(re.findall(r"\b((?:programs/|tests/)[A-Za-z0-9_./-]+\.py)", _c))
def _exists(n: str) -> bool:
    return any((base / n).is_file() for base in
               (PLUG, PLUG / "programs", PLUG / "programs" / "tests", HERE.parent))
control("enforcer-exists", not _exists("no_such_enforcer_program.py"))
_gone = sorted(n for n in _named if not _exists(n))
check("every program named as enforcing a class exists",
      not _gone, f"{len(_named)} named, missing {_gone}")

print()
if fails:
    print(f"FAIL — {len(fails)} claim(s) no longer hold:")
    for f in fails:
        print(f"    {f}")
    sys.exit(1)
print("PASS — every claim this batch makes was re-measured and holds.")
