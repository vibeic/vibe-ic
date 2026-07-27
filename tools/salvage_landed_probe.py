#!/usr/bin/env python3
"""salvage_landed_probe.py — is a parked branch's BEHAVIOUR already in main?

WHY THIS EXISTS
---------------
Issue #315 accumulated ~200 parked branches and four separate rounds tried to
triage them.  Every round used a different instrument and every instrument was
wrong IN THE SAME DIRECTION -- it reported already-landed work as unlanded:

    commit-subject grep      21 of 22 "unlanded"  (subjects are rewritten at land)
    rev-list --count        217 refs "unlanded"   (squash-merge destroys ancestry)
    whole-file blob compare  19 of 22 "DIVERGENT" (main = the change PLUS later work)
    cherry-pick residual      0 ALREADY_LANDED    (a rewritten equivalent still conflicts)

All four ask "are these BYTES in main?".  The question that matters is "is this
BEHAVIOUR in main?", and a fix that was re-implemented has the behaviour without
the bytes.  Acting on the byte answer means redoing finished work -- and, worse,
redoing work that was DECLINED for a reason.

WHAT THIS MEASURES
------------------
The branch's own regression test is transplanted onto three trees and run:

    T_base : the branch's base commit + the branch's test  -> should FAIL
    T_tip  : the branch tip                                -> should PASS
    T_main : today's main            + the branch's test   -> the measurement

DISCRIMINATION CONTROL.  Only nodes that FAIL on base and PASS on tip are
evidence: a node that already passes on base tests nothing about this fix, so
counting it would manufacture a verdict.  The verdict is the fraction of that
set which passes on main.

WHAT THIS DOES NOT ANSWER
-------------------------
"UNLANDED" means the behaviour is absent from main.  It does NOT mean the work
should land.  Behaviour is legitimately absent when a maintainer DECLINED it --
issue #315 recorded salvage items that would have regressed main if re-applied.
The verdict is an input to reading the change and its ledger entry, never a
substitute for it.  `--help` says so; so does every UNLANDED row.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------- pure core
# Everything below is pure: text in, verdict out.  The git/pytest plumbing
# lives in the thin layer at the bottom so the judgement is unit-testable.

#: pytest's short summary lines (`-rA`).
OUTCOME_RE = re.compile(
    r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+?)(?:\s+-\s+(.*))?$", re.M)
#: the `____ test_name ____` headers inside the FAILURES block.
FAILHDR_RE = re.compile(r"^_{5,}\s+(\S+?)\s+_{5,}$", re.M)
#: a test reaching into a PRIVATE helper BY NAME measures naming, not behaviour.
PRIVATE_ATTR_RE = re.compile(r"has no attribute '_[A-Za-z0-9_]+'")
MISSING_MOD_RE = re.compile(r"No module named '([^']+)'")

PASS = "PASSED"
MISSING = "MISSING"

VERDICT_LANDED = "LANDED"
VERDICT_UNLANDED = "UNLANDED"
VERDICT_PARTIAL = "PARTIAL"
VERDICT_NO_DISCRIMINATION = "INCONCLUSIVE_NO_DISCRIMINATING_TEST"
VERDICT_MISSING_MODULE = "INCONCLUSIVE_MISSING_MODULE"
VERDICT_API_DRIFT = "INCONCLUSIVE_API_DRIFT"
VERDICT_BASE_UNRUNNABLE = "INCONCLUSIVE_BASE_UNRUNNABLE"

#: verdicts that assert something about main.  Anything else is a non-answer,
#: which is the honest output when the probe could not measure.
CONCLUSIVE = frozenset({VERDICT_LANDED, VERDICT_UNLANDED, VERDICT_PARTIAL})


def failure_reasons(text: str) -> Dict[str, str]:
    """test-name -> traceback text, parsed out of the FAILURES block.

    Not cosmetic.  On the pytest in this tree the `-rA` short-summary FAILED
    lines carry no reason at all, so a quarantine that reads the summary sees
    an empty string and never fires -- the failure would then be scored as
    behavioural absence.  The reason has to come from the FAILURES block.
    """
    if "= FAILURES =" not in text:
        return {}
    body = text.split("= FAILURES =", 1)[1]
    hits = list(FAILHDR_RE.finditer(body))
    out: Dict[str, str] = {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        out[m.group(1)] = body[m.end():end]
    return out


def parse_outcomes(text: str) -> Dict[str, Tuple[str, str]]:
    """pytest output -> {test-name: (outcome, reason)}."""
    reasons = failure_reasons(text)
    out: Dict[str, Tuple[str, str]] = {}
    for outcome, node, msg in OUTCOME_RE.findall(text):
        name = node.split("::", 1)[-1] if "::" in node else node
        out[name] = (outcome, (msg or "").strip() or reasons.get(name, ""))
    return out


def harness_status(text: str, outcomes: Optional[Dict] = None) -> str:
    """OK / COLLECT_ERROR / NO_NODES for one pytest run."""
    if outcomes is None:
        outcomes = parse_outcomes(text)
    if "ERROR collecting" in text or "INTERNALERROR" in text:
        return "COLLECT_ERROR"
    if not outcomes:
        return "NO_NODES"
    return "OK"


def discriminating_set(base: Dict[str, Tuple[str, str]],
                       tip: Dict[str, Tuple[str, str]],
                       base_status: str) -> List[str]:
    """Nodes that are evidence about this fix: PASS on tip, not-PASS on base.

    A node absent from the base run counts ONLY when the base run was healthy
    (the branch added that test, so its absence is real).  When the base run
    failed to collect, EVERY node is absent, and treating that as
    discrimination turns a broken import into a confident full-file verdict --
    the exact "measured the thing next to the question" error this tool is a
    reaction to.  So an unhealthy base discriminates nothing.
    """
    if base_status != "OK":
        return []
    out = []
    for name, (outcome, _reason) in tip.items():
        if outcome != PASS:
            continue
        if base.get(name, (MISSING, ""))[0] in ("FAILED", "ERROR", MISSING):
            out.append(name)
    return sorted(out)


def is_api_drift(reason: str) -> bool:
    """True when the failure is about a PRIVATE helper's NAME, not behaviour.

    A test that calls `mod._helper(...)` fails with AttributeError when main
    re-implemented the same behaviour under different private names.  That is
    evidence about naming; scoring it as absence is a false UNLANDED.
    """
    return bool(PRIVATE_ATTR_RE.search(reason or ""))


def classify(discriminating: Sequence[str],
             main: Dict[str, Tuple[str, str]],
             main_status: str,
             base_status: str = "OK",
             main_text: str = "") -> dict:
    """The verdict, plus the evidence it rests on."""
    if base_status != "OK":
        return {"verdict": VERDICT_BASE_UNRUNNABLE, "passed": [], "failed": [],
                "drift": [], "score": "0/0"}
    if main_status == "COLLECT_ERROR":
        mods = sorted(set(MISSING_MOD_RE.findall(main_text)))
        return {"verdict": VERDICT_MISSING_MODULE, "passed": [], "failed": [],
                "drift": list(discriminating), "missing_modules": mods, "score": "0/0"}
    if not discriminating:
        return {"verdict": VERDICT_NO_DISCRIMINATION, "passed": [], "failed": [],
                "drift": [], "score": "0/0"}

    passed, failed, drift = [], [], []
    for name in discriminating:
        outcome, reason = main.get(name, (MISSING, ""))
        if outcome == PASS:
            passed.append(name)
        elif outcome == MISSING or is_api_drift(reason):
            drift.append(name)
        else:
            failed.append(name)

    effective = len(passed) + len(failed)
    if effective == 0:
        verdict = VERDICT_API_DRIFT
    elif not failed:
        verdict = VERDICT_LANDED
    elif not passed:
        verdict = VERDICT_UNLANDED
    else:
        verdict = VERDICT_PARTIAL
    return {"verdict": verdict, "passed": passed, "failed": failed, "drift": drift,
            "score": "%d/%d" % (len(passed), effective)}


def verdict_note(verdict: str) -> str:
    """The sentence that stops a verdict being read as an instruction."""
    if verdict == VERDICT_UNLANDED:
        return ("behaviour absent from main -- NOT necessarily work to do: "
                "check whether it was declined")
    if verdict == VERDICT_PARTIAL:
        return "some behaviour present -- read the diff before acting"
    if verdict == VERDICT_LANDED:
        return "behaviour present in main; nothing to land"
    return "no measurement -- the probe could not discriminate"


# ------------------------------------------------------------- thin IO layer

def run(cmd: Sequence[str], cwd: str, timeout: int = 1200) -> str:
    import subprocess
    try:
        r = subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""
    return (r.stdout or "") + (r.stderr or "")


def pytest_text(tree: str, tests: Iterable[str]) -> str:
    return run([sys.executable, "-m", "pytest", "-q", "--no-header",
                "-p", "no:cacheprovider", "-rA", "--tb=short", *tests], cwd=tree)


def probe_from_texts(base_text: str, tip_text: str, main_text: str) -> dict:
    """The whole judgement, given three pytest transcripts."""
    b, t, m = (parse_outcomes(x) for x in (base_text, tip_text, main_text))
    bs = harness_status(base_text, b)
    ms = harness_status(main_text, m)
    D = discriminating_set(b, t, bs)
    rec = classify(D, m, ms, bs, main_text)
    rec["discriminating"] = list(D)
    rec["note"] = verdict_note(rec["verdict"])
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-log", required=True, help="pytest transcript on the branch base")
    ap.add_argument("--tip-log", required=True, help="pytest transcript on the branch tip")
    ap.add_argument("--main-log", required=True, help="pytest transcript on today's main")
    ap.add_argument("--json", help="write the full record here")
    a = ap.parse_args(argv)

    texts = []
    for p in (a.base_log, a.tip_log, a.main_log):
        with open(p, encoding="utf-8", errors="replace") as fh:
            texts.append(fh.read())
    rec = probe_from_texts(*texts)
    print("%s  %s  (%s)" % (rec["verdict"], rec["score"], rec["note"]))
    if rec["failed"]:
        print("  absent on main : %s" % ", ".join(rec["failed"][:8]))
    if rec["drift"]:
        print("  unmeasured     : %d node(s) -- private-API naming, needs a read"
              % len(rec["drift"]))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=1)
    return 0 if rec["verdict"] in CONCLUSIVE else 2


if __name__ == "__main__":
    sys.exit(main())
