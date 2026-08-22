#!/usr/bin/env python3
"""J79 — the decay ledger: every number this report publishes that is a read of
something which can change WITHOUT ME.

J78 found a predicate whose answer changed with the clock and swept `meas/` for the
same cut-defect.  The sweep stopped at the scripts.  The same class lives in the
REPORT: a sentence like "`git ls-remote` returns 67 heads" is a predicate evaluated
once and then published as if it were a property of the world.

So each published live-state reading is pinned here with the value it was published
at, and re-measured.  Three outcomes, and the third is the one that makes this worth
having:

  HELD          re-measures to the published value.
  MONOTONE-SAFE the sentence publishes a LOWER BOUND and the re-measurement is above
                it -- the number moved and the sentence did not become false.
  MOVED         the published value no longer reproduces.  Correct the sentence.

Run it at the START of any dispatch that is going to quote this report.
"""
import os, re, subprocess, sys, time

os.chdir("/home/reyerchu/_jself_priv")
sys.path.insert(0, os.path.abspath("meas/_j68"))
from logcut import post_hold

WT = "wt/vibe-ic-marketplace"
REPORT_WT = "wt_report"
ARMS = [(3300, "proj/edge_llm_matmul_accel/phase3/stage3/pnr/openroad.log"),
        (3800, "proj/matmul_d3800/phase3/stage3/pnr/openroad.log"),
        (4200, "meas/matmul_fullflow/fullflow_4200.log"),
        (5153, "meas/matmul_fullflow/fullflow_5153.log"),
        (5434, "meas/matmul_fullflow/fullflow_5434.log")]

rows = []
def row(kind, name, published, measured, ok=None, note=""):
    if ok is None:
        ok = (published == measured)
    rows.append((kind, name, published, measured, ok, note))

def sh(cmd, cwd=None):
    return subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                          text=True, timeout=120).stdout.strip()

# ---- (c) EXTERNAL state: the git remote.  Nothing on this host controls it. ----
heads = sh(f"git ls-remote --heads origin 2>/dev/null | wc -l", WT)
jself = sh(f"git ls-remote --heads origin 2>/dev/null | grep -c jself || true", WT)
# INFORMATIONAL, deliberately not a pass/fail row.  J74 published this as `67`; J79
# measured `72` two hours later and the report was corrected to say which half of the
# sentence carries it.  Pinning a number that moves whenever ANY other agent pushes
# would make this ledger cry MOVED forever and train its reader to ignore it -- the
# failure mode a gate that is always red actually has.
row("external", "remote heads TOTAL (informational, not pinned)",
    "67 at J74 / 72 at J79", heads, ok=True,
    note="a count of OTHER people's branches; it moves whenever anyone pushes, so it "
         "is reported and never asserted")
row("external", "remote heads matching 'jself' (J74)", "0", jself,
    note="THIS is the load-bearing half of J74's sentence, and it is stable")
row("external", "origin/main sha (J66/J67)", "a4caccefe",
    sh("git ls-remote origin refs/heads/main", WT).split()[0][:9])

# J80's branch.  J74/J79 measured that a pushed branch can vanish from the remote with
# nothing recomputing the sentence that published it, so this one is pinned the day it
# is pushed rather than the day someone notices.
BR = "next/clkbuf-downsize-diagnostic-is-inverted"
got = sh(f"git ls-remote --heads origin refs/heads/{BR}", WT)
row("external", f"{BR} on the remote", "f99979a73",
    (got.split()[0][:9] if got else "GONE"))

BR3 = "next/placeability-bound-is-printed-and-never-consulted"
got3 = sh(f"git ls-remote --heads origin refs/heads/{BR3}", WT)
row("external", "the placeability-bound branch on the remote", "4d1de0e2c",
    (got3.split()[0][:9] if got3 else "GONE"))

BR2 = "next/six-shuttle-refusals-readjudicated-on-the-self-tapeout-path"
got2 = sh(f"git ls-remote --heads origin refs/heads/{BR2}", WT)
# NOT pinned to a literal sha.  It was, and the pin invalidated ITSELF: re-pinning it
# is a commit, which moves the tip the pin names, so every refresh left the ledger
# reporting a sha one behind the commit it travelled in.  A pin that cannot survive
# being updated is not a pin.  The invariant that actually matters -- and that
# terminates -- is "the branch is on the remote and its tip is what this worktree
# has", which is exactly what J74 found violated.
_rw = sh("git rev-parse HEAD", REPORT_WT)[:9]
row("external", "the report branch: remote tip == this worktree's HEAD",
    _rw or "unreadable", (got2.split()[0][:9] if got2 else "GONE"))

# The pushed report is a SNAPSHOT.  This directory's copy keeps moving, so the two
# WILL diverge -- that is expected, not a failure, and it is reported so nobody quotes
# the pushed copy as current.  A silent snapshot is how a stale number gets a URL.
import hashlib
def _h(path):
    try: return hashlib.sha256(open(path, "rb").read()).hexdigest()[:9]
    except OSError: return "missing"
live = _h("RESULT.md")
pushed = sh(f"git show {BR2}:selftapeout-adjudication/RESULT.md 2>/dev/null | "
            f"sha256sum | cut -c1-9", WT) or "unreadable"
row("external", "pushed RESULT.md == this directory's RESULT.md",
    "equal at push time", "EQUAL" if live == pushed else f"DRIFTED (live {live} / pushed {pushed})",
    ok=True, note="informational: the canonical copy is the one in _jself_priv; the "
                  "pushed one is a named snapshot and re-push is how it catches up")

# ---- (a) FROZEN source on main: the wall S7 rests on. ----
wall = sh("git archive origin/main plugins/vibe-ic/programs/pad_ring_gen.py 2>/dev/null "
          "| tar -xO 2>/dev/null | grep -c PAD_INSTANCE_NOT_IN_BLOCK || true", WT)
row("frozen", "PAD_INSTANCE_NOT_IN_BLOCK on origin/main", ">=1 (present)",
    f"{wall} occurrence(s)", ok=(wall.isdigit() and int(wall) >= 1),
    note="S7's wall; if this ever goes to 0 the four UNDETERMINED tiers change")

# ---- (b) LIVE logs: first-block reads are stable, last-block reads are not. ----
PUB_FIRST = {3800: "2352", 4200: "2296", 5153: "2418", 5434: "2409"}
PUB_LAST  = {3800: "2340", 4200: "2296", 5153: "2418", 5434: "2409"}
PUB_RUNGS = {3800: "2352 -> 2352 -> 2344 -> 2340"}
verdicts = []
for die, p in ARMS:
    txt = open(p, errors="replace").read()
    ph = post_hold(txt)
    r = re.findall(r"Violations remain:\s*(\d+)", ph)
    v = re.search(r"POST_HOLD_LEGALIZE_(OK|FAILED)[^\n]*", txt)
    verdicts.append((die, v.group(0) if v else None))
    if die in PUB_FIRST:
        row("live-first", f"die {die} post-hold FIRST-block residual",
            PUB_FIRST[die], r[0] if r else "-",
            note="stable convention: the first block does not move as rungs climb")
        row("live-last", f"die {die} post-hold LAST-block residual",
            PUB_LAST[die], r[-1] if r else "-",
            note="DECAYING BY CONSTRUCTION: a new rung rewrites it")
    if die in PUB_RUNGS:
        row("live-last", f"die {die} residual per rung", PUB_RUNGS[die],
            " -> ".join(r), note="the whole ladder; grows a term per rung")

# NOTE: the first version of this row compared "none yet (published as OPEN)"
# against "none yet" and so reported MOVED on a reading that had not moved -- the
# ledger's own third instrument defect of this dispatch.  The published value and the
# measured value have to be in the SAME vocabulary or the comparison is decoration.
# J88's two probes are TERMINAL -- both printed PROBE_DONE -- so they are pinned as
# completed readings.  The sentence they replaced ("still searching at 7 min") was a
# live read that decayed within the hour; a terminal fact cannot.
for _tag, _want in (("j88_rootbig", "2042"), ("j88_rootfit", "8")):
    try:
        _t = open(f"meas/_j88/{_tag}.log", errors="replace").read()
    except OSError:
        _t = ""
    _r = re.findall(r"Violations remain:\s*(\d+)", _t)
    row("frozen", f"{_tag} terminal post-hold residual", _want,
        (_r[-1] if _r else "no log") if "PROBE_DONE" in _t else "STILL RUNNING",
        note="terminal: the probe printed PROBE_DONE, so this reading is final")

row("live-open", "any arm printed POST_HOLD_LEGALIZE_*", "none yet",
    "none yet" if all(v is None for _, v in verdicts)
    else ", ".join(f"{d}:{v}" for d, v in verdicts if v),
    note="the report's one stated-open item, published as OPEN; an answer is a FINDING")

# ---- (d) monotone-safe.  The dwell WAS measured as "time since the log was last
# written", on the assumption that rung 5 emits nothing until it finishes.  At 15:59
# the die-4200 arm falsified that assumption by printing INTERMEDIATE progress after
# 10 h of silence, and the proxy re-zeroed from 45.9x to 0.7x -- the ledger flagged
# MOVED on a run that had simply started talking.  A proxy that assumes silence breaks
# the moment its subject stops being silent, so it is replaced by a quantity that
# CANNOT re-zero: cumulative CPU seconds from /proc.  This is not the same quantity as
# the published ratio (it counts from process start, not from rung-5 entry) and is
# therefore pinned in its own right rather than substituted into that sentence.
PUB_CPU = {3300: 70115, 3800: 52023, 4200: 50556, 5153: 26806, 5434: 16142}
PIDS    = {3300: 423747, 3800: 1933325, 4200: 2004621, 5153: 3598939, 5434: 2685425}
for die, pub in PUB_CPU.items():
    try:
        f = open(f"/proc/{PIDS[die]}/stat").read().split()
        got = (int(f[13]) + int(f[14])) // 100
    except OSError:
        got = None
    row("monotone", f"die {die} arm cumulative CPU seconds",
        f">= {pub}", "process gone" if got is None else got,
        ok=(got is not None and got >= pub),
        note="monotone by construction; 'process gone' is a FINDING, not a decay")

W = max(len(r[1]) for r in rows)
print(f"{'kind':<11} {'claim':<{W}} {'published':<28} {'now':<28} state")
print("-" * (11 + W + 28 + 28 + 16))
moved = []
for kind, name, pub, got, ok, note in rows:
    state = "HELD" if ok else "MOVED"
    if kind == "monotone" and ok:
        state = "MONOTONE-SAFE"
    if not ok:
        moved.append(name)
    print(f"{kind:<11} {name:<{W}} {str(pub):<28} {str(got):<28} {state}")
print()
for kind, name, pub, got, ok, note in rows:
    if note and (not ok or kind in ("live-last", "external", "live-open")):
        print(f"  * {name}: {note}")
print()
if moved:
    print(f"{len(moved)} published reading(s) MOVED: {moved}")
    print("Correct the sentence where it stands, or say beside it what it is a reading OF.")
    sys.exit(1)
print("No published live-state reading has moved.")
