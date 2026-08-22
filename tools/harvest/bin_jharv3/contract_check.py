#!/usr/bin/env python3
"""Validate a shard verdicts file against the deliverable contract.

    usage: contract_check.py [shard]        shard in {a,b,c}, default c
           contract_check.py --file F       validate a local file instead of a ref

WHY --file EXISTS. A mutation sweep showed 15 of this script's 18 guarantees could be
deleted without its test suite noticing: the suite only ever ran it against the REAL
shard files, which are valid, so nothing in the validation body was ever exercised.
A gate that can only be pointed at correct input cannot be shown to reject incorrect
input. --file makes each guarantee testable, and is useful on its own for checking a
file before pushing it.
    env:   VIBEIC_REPO   path to the vibe-ic clone (default: this file's own repo)
           VIBEIC_REF    ref to read the file from
                         (default: origin/harvest/worktree-triage-jharvest)

WHERE ITS INPUT COMES FROM, AND WHY THAT IS WRITTEN DOWN.
jharv2 found a coverage checker that reported `covered=0 uncovered=163` on four
hosts because its repo path was hardcoded -- a total failure that reads exactly
like a total loss. The first version of THIS script had the same constant, and
something worse: it read `FETCH_HEAD:tools/harvest/...`. FETCH_HEAD is ambient --
it means "whatever was fetched last". Run after any other fetch it would validate
a different file, or an older state of this one, and print CONTRACT OK about a
file nobody asked it to check. So the repo is located from this file's own path,
the ref is NAMED and fetched explicitly, and any input that cannot be resolved is
a loud exit naming it -- never a zero, never an empty result that reads as clean.

WHAT IS THE CONTRACT, AND WHAT IS ONE SHARD'S HOUSE STYLE.
The contract fixes the SHAPE (three fields, one of four verdicts, an absolute
path) and requires evidence a stranger can check. It does NOT fix the wording.
The three shards were written by three agents and their evidence grammars differ:
shard C says `rule R2: <file> sha256 X ... differs from origin/main <sha>`, shard
A says `<file>: sha256 X in this tree vs Y on main <sha>`.

An earlier version of this script knew only shard C's grammar and reported 216
"problems" in shard A and 245 in shard B. Every one was this script imposing its
own house style on a file that met the contract perfectly well. So grammar-
dependent verification is now COVERAGE, reported as a number, and only the
contract's real requirements can fail. A row this script cannot parse is a row it
did not check -- and saying so is the honest result, not a failure.
"""
import hashlib
import os
import re
import subprocess
import sys

DEFAULT_REF = "origin/harvest/worktree-triage-jharvest"
# DERIVED, never hardcoded. This was the literal string
# "81cd5321b082f9535f1a607a6feb7855498e7fe6", which was current main on the night it
# was written and is a stale constant on every night after. The whole re-judgement
# exists because 355 verdicts were measured against a main 4 to 18 days old; a gate
# that checks freshness against a frozen sha inherits exactly that bug and reports it
# as a pass. The old value is kept only as the last resort, and saying so out loud.
_FALLBACK_MAIN = "81cd5321b082f9535f1a607a6feb7855498e7fe6"


def _current_main():
    p = subprocess.run(["git", "-C", REPO, "rev-parse", "origin/main"],
                       capture_output=True, text=True)
    sha = p.stdout.strip()
    if p.returncode == 0 and len(sha) == 40:
        return sha
    print(f"WARNING: cannot resolve origin/main; falling back to the frozen "
          f"{_FALLBACK_MAIN[:9]}, which may be stale.", file=sys.stderr)
    return _FALLBACK_MAIN

OK = {"RECOVER", "ABANDON", "LANDED", "UNREACHABLE"}


def die(msg):
    """Fail loudly, naming the missing input. Never degrade to an empty pass."""
    sys.exit(f"contract_check: {msg}")


def find_repo():
    if os.environ.get("VIBEIC_REPO"):
        return os.environ["VIBEIC_REPO"]
    here = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.run(["git", "-C", here, "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    if p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip()
    die(f"cannot locate the vibe-ic clone from {here}; set VIBEIC_REPO")


REPO = find_repo()
MAIN = _current_main()   # after REPO exists: derived, not frozen
REF = os.environ.get("VIBEIC_REF", DEFAULT_REF)


def git(*a, check=True):
    p = subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True)
    if check and p.returncode != 0:
        die(f"git {' '.join(a)} failed: {p.stderr.strip()}")
    return p.stdout


def blob_sha(rev, path):
    p = subprocess.run(["git", "-C", REPO, "rev-parse", f"{rev}:{path}"],
                       capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def main_sha(path, width=16):
    """sha256 of <path> as origin/main holds it now, or None if main lacks it."""
    p = subprocess.run(["git", "-C", REPO, "show", f"{MAIN}:{path}"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return None
    return hashlib.sha256(p.stdout.encode("utf-8", "surrogateescape")).hexdigest()[:width]


HEAD_RE = re.compile(r"worktree HEAD (?:when judged|at re-verification): ([0-9a-f]{40})")
# Shard C: no extension allowlist, no required dot -- the named file is the token
# the rule puts before "sha256". An extension test produced two false reds (.inc
# was absent from the list; .image-version-ignore has no extension at all).
C_RE = re.compile(r"rule \S+[^:]*: (\S+) sha256")
# Shard A: "<file>: sha256 <in tree> in this tree vs <on main> on main <sha>"
A_RE = re.compile(r"^(\S+): sha256 ([0-9a-f]{16}) in this tree vs ([0-9a-f]{16}) on main")
# Shard B: "sha256(<file>) = <64hex> here, <64hex> on main"
B_RE = re.compile(r"sha256\((\S+?)\) = ([0-9a-f]{64}) here, ([0-9a-f]{64}) on main")
UNCOMMITTED_RE = re.compile(r"(uncommitted EDIT|NAMED FILE|tracked uncommitted|UNTRACKED)", re.I)
MAIN_CITED = re.compile(r"\b([0-9a-f]{9,40})\b")


def main():
    argv = sys.argv[1:]
    shard = "(local file)"
    if argv and argv[0] == "--file":
        if len(argv) < 2:
            die("--file needs a path")
        rel = argv[1]
        try:
            body = open(rel).read()
        except OSError as e:
            die(f"cannot read {rel}: {e}")
        if not body.strip():
            die(f"{rel} is absent or empty")
        print(f"repo   {REPO}")
        print(f"file   {rel} (local)")
    else:
        shard = (argv[0] if argv else "c").lower()
        if shard not in {"a", "b", "c"}:
            die(f"shard must be a, b or c, not {shard!r}")
        rel = f"tools/harvest/verdicts_shard_{shard}.tsv"

        if REF.startswith("origin/"):
            git("fetch", "-q", "origin", REF[len("origin/"):], check=False)
        rev = git("rev-parse", "--verify", "--quiet", REF, check=False).strip()
        if not rev:
            die(f"ref {REF!r} does not resolve in {REPO}; fetch it or set VIBEIC_REF")
        body = git("show", f"{rev}:{rel}", check=False)
        if not body.strip():
            die(f"{rel} is absent or empty at {REF} ({rev[:9]})")

        print(f"repo   {REPO}")
        print(f"ref    {REF} = {rev[:9]}")
        print(f"file   {rel}")

    lines = [l for l in body.split("\n") if l.strip()]
    problems, counts = [], {}
    cov = {"verified_differs": 0, "verified_absent_from_main": 0,
           "uncommitted": 0, "landed_since_judging": 0, "not_parseable": 0}
    stale_main = 0

    if lines[0].split("\t") != ["path", "verdict", "evidence"]:
        problems.append(f"header is {lines[0]!r}, contract says path/verdict/evidence")

    for i, ln in enumerate(lines[1:], start=2):
        f = ln.split("\t")
        # --- the contract's real requirements: these may FAIL ---
        if len(f) != 3:
            problems.append(f"line {i}: {len(f)} fields, contract says 3")
            continue
        p, verdict, ev = f
        counts[verdict] = counts.get(verdict, 0) + 1
        if verdict not in OK:
            problems.append(f"line {i}: verdict {verdict!r} is not one of the contract's four")
        if not p.startswith("/"):
            problems.append(f"line {i}: path {p!r} is not absolute")
        if len(ev.strip()) < 40:
            problems.append(f"line {i} ({p}): evidence is too thin to be checkable")
        if verdict == "ABANDON" and not re.search(r"duplicate|superseded|empty", ev, re.I):
            problems.append(f"line {i} ({p}): ABANDON does not say what makes it worthless")

        # --- provenance: informational, never a failure ---
        if MAIN[:9] not in ev:
            stale_main += 1

        # --- grammar-dependent verification: COVERAGE, never a failure ---
        if verdict != "RECOVER":
            continue
        mc, ma = C_RE.search(ev), A_RE.match(ev)
        if mc:
            named, h = mc.group(1), HEAD_RE.search(ev)
            if not h:
                cov["not_parseable"] += 1
                continue
            at_head, at_main = blob_sha(h.group(1), named), blob_sha(MAIN, named)
            if at_head is None:
                cov["uncommitted" if UNCOMMITTED_RE.search(ev) else "not_parseable"] += 1
            elif at_main is None:
                cov["verified_absent_from_main"] += 1
            elif at_head == at_main:
                problems.append(f"line {i} ({p}): {named} is IDENTICAL to main — RECOVER unsupported")
            else:
                cov["verified_differs"] += 1
        elif ma:
            named, in_tree = ma.group(1), ma.group(2)
            now = main_sha(named, 16)
            if now is None:
                cov["verified_absent_from_main"] += 1
            elif now == in_tree:
                # the tree's content reached main after this row was written
                cov["landed_since_judging"] += 1
            else:
                cov["verified_differs"] += 1
        elif mb := B_RE.search(ev):
            named, here = mb.group(1), mb.group(2)
            now = main_sha(named, 64)
            if now is None:
                cov["verified_absent_from_main"] += 1
            elif now == here:
                cov["landed_since_judging"] += 1
            else:
                cov["verified_differs"] += 1
        elif UNCOMMITTED_RE.search(ev):
            cov["uncommitted"] += 1
        else:
            cov["not_parseable"] += 1

    print(f"rows={len(lines)-1}  {counts}")
    print(f"RECOVER coverage: {cov}")
    if stale_main:
        print(f"note: {stale_main} row(s) do not cite current main {MAIN[:9]} — "
              f"a provenance gap, not a wrong verdict. 'landed_since_judging' above "
              f"is what that staleness actually cost.")
    if cov["not_parseable"]:
        print(f"note: {cov['not_parseable']} RECOVER row(s) use an evidence grammar this "
              f"script does not know. NOT CHECKED is not the same as wrong.")
    if problems:
        print(f"\nCONTRACT PROBLEMS: {len(problems)}")
        for pr in problems[:25]:
            print("  " + pr)
        return 1
    print(f"CONTRACT OK — shard {shard}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
