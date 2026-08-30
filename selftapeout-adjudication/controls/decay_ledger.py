#!/usr/bin/env python3
"""J79 — the decay ledger: every number this report publishes that is a read of
something which can change WITHOUT ME.

J78 found a predicate whose answer changed with the clock and swept `meas/` for the
same cut-defect.  The sweep stopped at the scripts.  The same class lives in the
REPORT: a sentence like "`git ls-remote` returns 67 heads" is a predicate evaluated
once and then published as if it were a property of the world.  (That illustration is
itself superseded -- 67 became 72 within the hour, and 262 later, which is the whole
point of using it as the example.)

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
# J98: the `jself` grep was a SUBSTRING PROXY for "the two pad-site branches are
# gone".  It held only while no other branch of mine matched the substring.  At
# 21:49 on 2026-08-22 the one-branch-per-agent rule put `next/jself` on the remote
# and the proxy went 0 -> 1 -- while the claim it stood for stayed TRUE.  So the
# claim is now measured BY NAME, with a positive control, in
# controls/branch_claim_by_name.py (meas/_j98/ in the working tree), and the proxy
# is demoted to informational.
_GONE = ["jself/pad-site-declared-in-pdk-tool-config",
         "jself/pad-site-declared-in-pdk-tool-config-on-v1.11.68"]
# INFORMATIONAL, deliberately not a pass/fail row.  J74 published this as `67`; J79
# measured `72` two hours later and the report was corrected to say which half of the
# sentence carries it.  Pinning a number that moves whenever ANY other agent pushes
# would make this ledger cry MOVED forever and train its reader to ignore it -- the
# failure mode a gate that is always red actually has.
row("external", "remote heads TOTAL (informational, not pinned)",
    "67 at J74 / 72 at J79", heads, ok=True,
    note="a count of OTHER people's branches; it moves whenever anyone pushes, so it "
         "is reported and never asserted")
for _b in _GONE:
    _h = sh(f"git ls-remote --heads origin refs/heads/{_b} 2>/dev/null", WT)
    row("external", f"J74's claim, BY NAME: {_b.split('/')[-1][:38]}", "ABSENT",
        "ABSENT" if not _h else "PRESENT " + _h.split()[0][:9],
        note="the load-bearing half of J74's sentence, measured by name instead of "
             "by a substring that a later branch of mine started matching (J98)")
row("external", "remote heads matching substring 'jself' (RETIRED proxy)",
    "0 at J74/J79 -> 1 since 21:49 (`next/jself` is mine)", jself, ok=True,
    note="informational only since J98: this counted the CLAIM until my own "
         "consolidated branch started matching it; the rows above are the claim")
row("external", "origin/main sha — re-verified at ae78abb28 by J91", "ae78abb28",
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

# J98: the one-branch-per-agent rule makes THIS the only ref I push, so it is the
# one that has to be pinned.  It was not, and three superseded branches were.
_MINE = sh("git ls-remote --heads origin refs/heads/next/jself", WT)
_MINE_LOCAL = sh("git rev-parse HEAD", "wt_jself")[:9]
row("external", "next/jself: remote tip == wt_jself HEAD (my only push ref)",
    _MINE_LOCAL or "unreadable",
    (_MINE.split()[0][:9] if _MINE else "GONE"),
    note="one-branch-per-agent; J74 measured that a pushed branch can vanish with "
         "nothing recomputing the sentence that published it")

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
# J98: this compared against BR2, which consolidation SUPERSEDED -- so it was
# reporting drift against a branch I no longer push to.  It follows `next/jself`.
pushed = sh("git show next/jself:selftapeout-adjudication/RESULT.md 2>/dev/null | "
            "sha256sum | cut -c1-9", WT) or "unreadable"
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
# J98 re-pin.  These were the values the REPORT published at J79.  J96 corrected
# the report to the post-swap ladder and did not re-pin here, so the ledger cried
# MOVED on two readings the report already states correctly -- a ledger that is
# always red trains its reader to ignore it, which is the failure mode this file
# warns about in its own `heads TOTAL` row.  Old pins kept beside the new ones so
# the correction is legible rather than silent.
PUB_LAST  = {3800: "300", 4200: "2296", 5153: "2418", 5434: "2409"}   # 3800 was 2340 at J79
PUB_RUNGS = {3800: "2352 -> 2352 -> 2344 -> 2340 -> 2307 -> 300"}     # was "...-> 2340" at J79
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
        # J100: this was an EXACT-match pin on a sequence that grows a term per rung,
        # so it was guaranteed to report MOVED the moment the arm made progress -- and
        # it did, on a run where the published sentence ("it reads 2352 / 2352 / 2344 /
        # 2340 / 2307, swap 2089, then 300") had not become false at all.  A check that
        # reddens by construction is noise, and noise is what a real red hides in.
        # The sentence's actual claim is about the terms it NAMES, so the correct
        # predicate is PREFIX: those terms must still read as published.  A changed
        # term, a reordering, or a TRUNCATED ladder all still fail it.  This is a
        # RELAXATION and is labelled as one rather than folded into HELD.
        _now = " -> ".join(r)
        _pub = PUB_RUNGS[die]
        _is_prefix = _now.startswith(_pub)
        row("prefix", f"die {die} residual per rung (PREFIX pin)", _pub,
            _now if _now != _pub else "(identical)", ok=_is_prefix,
            note="J100: PREFIX, not equality -- the ladder grows a term per rung, so "
                 "equality reddens on progress. The published terms must still read as "
                 "published; a changed or dropped term still fails")

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

# J98: ANSWERED.  Two runs of this file 48 s apart bracket it -- 22:19:5x printed
# `none yet`, 22:20:59 printed the verdict, and the log's mtime when the line
# landed is 22:20:11.  The row is re-pinned to the ANSWER rather than deleted, and
# it still carries the four arms that have NOT answered, so it keeps its signal.
_ANS = sorted((d, v) for d, v in verdicts if v)
_OPEN = sorted(d for d, v in verdicts if v is None)
row("live-open", "arms that printed POST_HOLD_LEGALIZE_* (was: none yet)",
    "3300:POST_HOLD_LEGALIZE_FAILED",
    ", ".join(f"{d}:{v}" for d, v in _ANS) or "none yet",
    note="J98: the report's one stated-open item, answered on the die-3300 arm and "
         "TERMINAL there (all 9 rungs spent). It moves no verdict: the row is decided "
         "on area, at a build-to die this arm is not")
row("live-open", "arms still unanswered", "3800, 4200, 5153, 5434",
    ", ".join(str(d) for d in _OPEN) or "none",
    note="an answer from any of these is a FINDING; a second FAILED is not a verdict")

# ---- (d) monotone-safe.  The dwell WAS measured as "time since the log was last
# written", on the assumption that rung 5 emits nothing until it finishes.  At 15:59
# the die-4200 arm falsified that assumption by printing INTERMEDIATE progress after
# 10 h of silence, and the proxy re-zeroed from 45.9x to 0.7x -- the ledger flagged
# MOVED on a run that had simply started talking.  A proxy that assumes silence breaks
# the moment its subject stops being silent, so it is replaced by a quantity that
# CANNOT re-zero: cumulative CPU seconds from /proc.  This is not the same quantity as
# the published ratio (it counts from process start, not from rung-5 entry) and is
# therefore pinned in its own right rather than substituted into that sentence.
# J100: the 3300 entry is RETIRED from this table rather than left permanently red.
# Its pin did its job -- it reported `process gone`, which J99 then explained: that
# arm's pnr.tcl EXITED and the runner advanced it to signoff.  A pin whose question has
# been ANSWERED should be re-pinned to the successor fact, not kept red forever, or the
# ledger trains its reader to skip its own red lines.  The successor fact is the
# `die 3300 arm: last PNR_STAGE in its log` row added above, which is what now carries
# the signal.  The other four arms are still in PnR and stay here.
PUB_CPU = {3800: 52023, 4200: 50556, 5153: 26806, 5434: 16142}
PIDS    = {3800: 1933325, 4200: 2004621, 5153: 3598939, 5434: 2685425}
row("retired", "die 3300 arm cumulative CPU seconds (RETIRED, ANSWERED)",
    ">= 70115 while in PnR", "pnr.tcl exited; arm is in signoff", ok=True,
    note="J99/J100: the pin reported `process gone`, that was a FINDING, and it has "
         "been answered. Retired in favour of the last-PNR_STAGE row, which is the "
         "successor fact. Kept visible so the retirement is not a deletion")
for die, pub in PUB_CPU.items():
    try:
        f = open(f"/proc/{PIDS[die]}/stat").read().split()
        got = (int(f[13]) + int(f[14])) // 100
    except OSError:
        got = None
    row("monotone", f"die {die} arm cumulative CPU seconds",
        f">= {pub}", "process gone" if got is None else got,
        ok=(got is not None and got >= pub),
        note="monotone by construction; 'process gone' is a FINDING, not a decay. J99 ANSWERED the 3300 one: that arm's pnr.tcl EXITED -- it left PnR and the runner advanced it to signoff. The row is kept as-is because the pin is correct and its answer belongs beside it, not inside it")

# ---- (e) J99.  The die-3300 arm's routed.def is being written by a process that is
# STILL RUNNING, so "0 of 257 867 signal nets are routed" is a reading of a live file
# and not a property of the design.  Pinned by the file's own SHA-256 -- not a proxy:
# if the hash holds, the counts published beside it hold with it; if it moves, the
# gate has to be re-run before the sentence may be repeated.
J99_DEFS = [
    ("die 3300 routed.def (LIVE — signoff still running)",
     "proj/edge_llm_matmul_accel/phase3/stage3/pnr/routed.def",
     "325d5e7352b95858e551ede6a8db64db775666582568f02fe148fa318a7422a4",
     "0 of 257867 signal nets routed; gate rc=1"),
    ("sha256 control routed.def (the OK arm of the pair)",
     "proj/sha256/phase3/stage3/pnr/routed.def",
     "e26bbd7245435cf9abbe24056a1c7b440b7abbc0041bb012a6182a86e2c4212c",
     "16071 of 16071 signal nets routed; gate rc=0"),
]
import hashlib
for _name, _path, _pub_sha, _reading in J99_DEFS:
    try:
        _h = hashlib.sha256()
        with open(_path, "rb") as _f:
            for _chunk in iter(lambda: _f.read(1 << 22), b""):
                _h.update(_chunk)
        _got = _h.hexdigest()
    except OSError:
        _got = "unreadable"
    row("live-file", _name, _pub_sha[:10], _got[:10], ok=(_got == _pub_sha),
        note=f"J99 published `{_reading}` off THIS file; a moved hash retracts that "
             f"reading until def_stage_progression_check.py is re-run")

# The stage the 3300 arm has reached.  Published as the stage J99 saw, because a LATER
# stage is not a decay -- it is the arm making progress -- and an EARLIER one would mean
# the log was replaced.  So this row is informational and never asserted.
try:
    _stage = "none"
    with open("proj/edge_llm_matmul_accel/phase3/stage3/pnr/openroad.log",
              errors="replace") as _f:
        for _line in _f:
            if _line.startswith("PNR_STAGE:"):
                _stage = _line.split(":", 1)[1].strip()
except OSError:
    _stage = "unreadable"
row("live-open", "die 3300 arm: last PNR_STAGE in its log",
    "postroute_setup_repair_estimate", _stage, ok=True,
    note="informational, never asserted: a LATER stage is progress, not decay. J99 "
         "pins it so that an EARLIER one -- which would mean the log was replaced -- "
         "is visible")

W = max(len(r[1]) for r in rows)
print(f"{'kind':<11} {'claim':<{W}} {'published':<28} {'now':<28} state")
print("-" * (11 + W + 28 + 28 + 16))
moved = []
for kind, name, pub, got, ok, note in rows:
    state = "HELD" if ok else "MOVED"
    if kind == "monotone" and ok:
        state = "MONOTONE-SAFE"
    if kind == "prefix" and ok:
        state = "PREFIX-SAFE" if got != "(identical)" else "HELD"
    if kind == "retired" and ok:
        state = "RETIRED"
    if not ok:
        moved.append(name)
    print(f"{kind:<11} {name:<{W}} {str(pub):<28} {str(got):<28} {state}")
print()
for kind, name, pub, got, ok, note in rows:
    if note and (not ok or kind in ("live-last", "external", "live-open",
                                    "prefix", "retired")):
        print(f"  * {name}: {note}")
print()
if moved:
    print(f"{len(moved)} published reading(s) MOVED: {moved}")
    print("Correct the sentence where it stands, or say beside it what it is a reading OF.")
    sys.exit(1)
print("No published live-state reading has moved.")
