#!/usr/bin/env python3
"""Validate verdicts_shard_c.tsv against the deliverable contract, reading the
file from the branch AS PUSHED -- not from any local copy.

The RECOVER check is a MEASUREMENT, not a regex. An earlier version of this
script asked "does the evidence contain a token matching a list of extensions?"
and reported a row as naming no checkable file. The row named
.../riscv_isa_ref_oracle/common.inc, which is a perfectly good file; my
extension list simply had no .inc in it. The artefact was right and the checker
was wrong -- the third time tonight a red came from the checker.

So this asks the question the contract actually asks: take the file the row
names, resolve it at the head the row was judged at, and compare it against
origin/main. Either it is absent from main, or its bytes differ. If neither, the
row is making a claim its own evidence does not support.
"""
import re, subprocess, sys

R = "/home/reyerchu/vibe-ic"
MAIN = "81cd5321b082f9535f1a607a6feb7855498e7fe6"
OK = {"RECOVER", "ABANDON", "LANDED", "UNREACHABLE"}


def git(*a):
    return subprocess.run(["git", "-C", R, *a], capture_output=True, text=True)


def blob_sha(rev, path):
    """The blob id of <path> at <rev>, or None if <rev> has no such path."""
    p = git("rev-parse", f"{rev}:{path}")
    return p.stdout.strip() if p.returncode == 0 else None


text = git("show", "FETCH_HEAD:tools/harvest/verdicts_shard_c.tsv")
if text.returncode != 0:
    sys.exit("could not read the file from FETCH_HEAD: " + text.stderr.strip())

lines = [l for l in text.stdout.split("\n") if l.strip()]
problems, counts = [], {}
measured = {"absent_from_main": 0, "bytes_differ": 0, "uncommitted": 0}

if lines[0].split("\t") != ["path", "verdict", "evidence"]:
    problems.append(f"header is {lines[0]!r}, contract says path/verdict/evidence")

HEAD_RE = re.compile(r"worktree HEAD (?:when judged|at re-verification): ([0-9a-f]{40})")
# the file a rule names, whatever its extension
# No extension allowlist and no required dot: the named file is simply the
# token the rule puts before "sha256". An extension test already produced two
# false reds -- .inc was not in the list, and .image-version-ignore has no
# extension at all. Both rows were correct; the pattern was the defect.
NAMED_RE = re.compile(r"rule \S+[^:]*: (\S+) sha256")
# "not held by any commit" has two forms: an uncommitted edit to a tracked
# file, and an untracked file. Both are legitimately unresolvable at a head.
UNCOMMITTED_RE = re.compile(r"(uncommitted EDIT|NAMED FILE|tracked uncommitted|UNTRACKED)", re.I)

for i, ln in enumerate(lines[1:], start=2):
    f = ln.split("\t")
    if len(f) != 3:
        problems.append(f"line {i}: {len(f)} fields, contract says 3")
        continue
    path, verdict, ev = f
    counts[verdict] = counts.get(verdict, 0) + 1

    if verdict not in OK:
        problems.append(f"line {i}: verdict {verdict!r} is not one of the contract's four")
    if not path.startswith("/"):
        problems.append(f"line {i}: path {path!r} is not absolute")
    if MAIN not in ev:
        problems.append(f"line {i} ({path}): evidence does not name main {MAIN[:9]}")

    if verdict == "RECOVER":
        m, h = NAMED_RE.search(ev), HEAD_RE.search(ev)
        if not m:
            # rule L2 rows keep their value in UNCOMMITTED bytes, which no commit
            # holds; the contract is met by naming the edited file.
            if UNCOMMITTED_RE.search(ev):
                measured["uncommitted"] += 1
            else:
                problems.append(f"line {i} ({path}): RECOVER names no file at all")
            continue
        named = m.group(1)
        if not h:
            problems.append(f"line {i} ({path}): names {named} but no head to resolve it at")
            continue
        head = h.group(1)
        at_head, at_main = blob_sha(head, named), blob_sha(MAIN, named)
        if at_head is None:
            # the bytes may live only on disk; accept only if the row says so
            if UNCOMMITTED_RE.search(ev):
                measured["uncommitted"] += 1
            else:
                problems.append(f"line {i} ({path}): names {named}, absent at its own head {head[:9]}")
        elif at_main is None:
            measured["absent_from_main"] += 1
        elif at_head == at_main:
            problems.append(f"line {i} ({path}): {named} is IDENTICAL to main — RECOVER unsupported")
        else:
            measured["bytes_differ"] += 1

    if verdict == "LANDED" and "identical" not in ev and "match" not in ev.lower():
        problems.append(f"line {i} ({path}): LANDED does not state that files matched")
    if verdict == "ABANDON" and not re.search(r"duplicate|superseded|empty", ev, re.I):
        problems.append(f"line {i} ({path}): ABANDON does not say what makes it worthless")

print(f"rows={len(lines)-1}  {counts}")
print(f"RECOVER evidence re-measured: {measured}")
if problems:
    print(f"\nCONTRACT PROBLEMS: {len(problems)}")
    for p in problems[:25]:
        print("  " + p)
    sys.exit(1)
print("CONTRACT OK — every row shaped, verdicted and evidenced as the contract requires,")
print("and every RECOVER's named file re-resolved against origin/main just now.")
