#!/usr/bin/env python3
"""acceptance_control_check.py — the control a change is measured against must
be the state BEFORE the feature, not an earlier commit on the same branch.

ADVISORY. Exits 0 on every verdict. It reports; it does not block.

WHY (vibe-ic#401)
-----------------
Validating round N against round N-1 measures a branch against itself, and it
makes a change that contributes nothing look like it contributes a lot.
Measured on a real (withdrawn) branch: round 2 declared its evidence against
the branch's own previous commit and listed four cases it "recovered". At the
MERGE-BASE all four were already present — round 1 had lost them and round 2
put them back. Over 795 markdown documents the two rounds' output was
identical on 795 of 795. Against the wrong control the same 231 lines looked
well covered: 11 of 20 tests failed on the predecessor.

AND THE WRONG CONTROL PROPAGATES. That branch ran two full rounds of
adversarial verification, and both verifiers also compared against the SHA in
the commit body — because that is what the commit body said. A reviewer who
trusts the message inherits the mistake. A machine that recomputes it from
`git` does not.

WHAT IT DOES, AND WHAT THAT IS WORTH TODAY
------------------------------------------
1. Reports `git merge-base <base> <head>` — the control that SHOULD be used —
   so nobody has to look it up.
2. If the message NAMES a control (`CONTROL: <ref>`, or the free-form
   "against `<sha>`" this repo already writes), checks
   `git merge-base --is-ancestor <ref> <base>`. A ref that is not an ancestor
   of the integration branch exists only on the feature branch, and is
   therefore not a valid control.

MEASURED BEFORE SHIPPING: over the last 120 commit messages in this repo,
essentially NONE declare a control SHA. So (2) is close to vacuous today and
the working value is (1). Saying that plainly rather than implying the gate
catches something it currently cannot is the point of writing it down.

HONEST BOUNDARY
---------------
This checks that a named control is ON the integration branch. It does NOT
check that anything was actually re-run against it — that is what the
mutation evidence is for. A legitimate stacked-PR workflow can have a valid
control not yet on the integration branch; ADVISORY-first is the answer, the
gate names what it sees and the author answers.

chip-AGNOSTIC: git refs and commit text only.

USAGE
-----
    acceptance_control_check.py --base <ref> [--head <ref>] [--repo DIR]
                               [--message-file F] [--json OUT]

EXIT CODES
----------
    0 = always (ADVISORY)      2 = refs not resolvable
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import List
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

# `CONTROL: <ref>` and the free-form shape this repo already writes.
_DECL_RES = (
    re.compile(r"^\s*CONTROL\s*:\s*[`\"']?([0-9a-zA-Z_./-]{4,60})[`\"']?\s*$",
               re.MULTILINE),
    re.compile(r"\bagainst\s+[`\"']?([0-9a-f]{7,40})[`\"']?\b"),
    re.compile(r"\bcontrol(?:\s+is|\s+was|\s*=)?\s+[`\"']?([0-9a-f]{7,40})"
               r"[`\"']?\b", re.IGNORECASE),
)


def _git(repo: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def declared_controls(text: str) -> List[str]:
    out: List[str] = []
    for rx in _DECL_RES:
        for m in rx.findall(text or ""):
            if m not in out:
                out.append(m)
    return out


def audit(repo: Path, base: str, head: str, message: str) -> dict:
    mb = _git(repo, "merge-base", base, head)
    if mb.returncode != 0:
        return {"resolvable": False, "reason": mb.stderr.strip()[:200]}
    correct = mb.stdout.strip()
    findings = []
    for ref in declared_controls(message):
        rv = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if rv.returncode != 0:
            # Not a commit-ish in this clone. Silence, not a finding: the
            # message may name a ref that lives on another host, and inventing
            # a verdict about it would be worse than saying nothing.
            continue
        sha = rv.stdout.strip()
        anc = _git(repo, "merge-base", "--is-ancestor", sha, base)
        if anc.returncode != 0:
            findings.append({
                "declared": ref, "sha": sha[:9],
                "problem": "not an ancestor of the integration base — it "
                           "exists only on this branch, so measuring against "
                           "it compares the branch with itself",
            })
    return {"resolvable": True, "correct_control": correct,
            "declared": declared_controls(message), "findings": findings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--message-file")
    ap.add_argument("--message")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()

    if a.message is not None:
        msg = a.message
    elif a.message_file:
        try:
            msg = Path(a.message_file).read_text(errors="replace")
        except OSError:
            msg = ""
    else:
        r = _git(repo, "log", "-1", "--format=%B", a.head)
        msg = r.stdout if r.returncode == 0 else ""

    rep = audit(repo, a.base, a.head, msg)
    if a.json_out:
        atomic_write_text(Path(a.json_out), json.dumps(rep, indent=2) + "\n")

    if not rep.get("resolvable"):
        print(f"[SKIP] acceptance_control_check: cannot resolve "
              f"merge-base({a.base}, {a.head}) — {rep.get('reason', '')}")
        return 2

    print(f"acceptance_control_check (ADVISORY): the control for this change "
          f"is merge-base({a.base}, {a.head}) = {rep['correct_control'][:9]}")
    if rep["findings"]:
        print(f"   {len(rep['findings'])} declared control(s) are NOT valid:")
        for f in rep["findings"]:
            print(f"     {f['declared']} ({f['sha']}) — {f['problem']}")
        print("   Measuring round N against round N-1 makes a change that "
              "contributes nothing look like it contributes a lot, and the "
              "wrong control propagates to every reviewer who trusts the "
              "commit message.")
    elif rep["declared"]:
        print(f"   declared control(s) all valid: "
              f"{', '.join(rep['declared'])}")
    else:
        print("   no control declared in the message — the SHA above is the "
              "one to measure against. (Measured over the last 120 commits "
              "here, almost none declare one, so this branch of the check is "
              "near-vacuous today; the value is the SHA.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
