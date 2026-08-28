#!/usr/bin/env python3
"""Did this candidate change the code that judges it?

THE WHOLE QUESTION, and the whole answer:

    the judge set is DERIVED from what the verifier actually executes.
    git says which of those files the candidate touched.
    if the answer is non-empty, a human authorises it or it does not land.

WHAT THIS REPLACES.  A 27KB hand-maintained register plus ~4200 lines of
machinery to validate it, in which:

  * the register is HAND-WRITTEN while the files it names change constantly —
    nineteen landings in one day moved twelve registered files and the register
    followed none of them;
  * "nothing needs to move" is an ILLEGAL STATE (`current` must differ from
    `next`), so a register that is up to date cannot be expressed;
  * catching up REQUIRES TWO LANDINGS by construction (PREPARE then ACTIVATE),
    so a register that falls behind cannot be fixed in one commit;
  * a missing row does not say "row missing" — it makes the verdict
    RC_CANNOT_MEASURE, which surfaces as `assert 2 == 1` in fourteen tests five
    files away.

None of that machinery answers a question git cannot. The register was a SECOND
COPY of a fact the repository already holds, and the copy went stale — which is
the same defect this repository keeps finding in its own gates and fixing by
DERIVING the fact instead of storing it.

WHAT IS *NOT* CHANGED BY THIS.  The real protection is that the verifier runs
the copy of itself from the BASE commit, which `gatekeeper-verify-merge.sh`
already does in shell, before any manifest is read.  That is what stops a
candidate grading its own homework, and it never depended on the register.
"""
from __future__ import annotations
import argparse, ast, subprocess, sys
from pathlib import Path


def _git(*args: str) -> str:
    return subprocess.run(("git",) + args, capture_output=True, text=True,
                          check=False).stdout


def judge_set(repo: Path) -> set[str]:
    """Every file the landing verifier executes, derived — never listed.

    Start from the verifier's entry points and follow what they RUN: the shell
    scripts they invoke and the python modules those import from this repo. A
    file is in the judge set because it is reachable from the thing that judges,
    not because somebody remembered to write it down.
    """
    seeds = ["tools/gatekeeper-verify-merge.sh", "tools/gatekeeper-land.sh"]
    seen: set[str] = set()
    queue = [s for s in seeds if (repo / s).is_file()]
    while queue:
        rel = queue.pop()
        if rel in seen:
            continue
        seen.add(rel)
        try:
            text = (repo / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if rel.endswith(".py"):
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module] if isinstance(node, ast.ImportFrom)
                         and node.level == 0 and node.module else [])
                for mod in names:
                    stem = mod.split(".")[0] + ".py"
                    for d in ("tools/ci", "tools",
                              "vibe-ic-marketplace/plugins/vibe-ic/programs"):
                        cand = f"{d}/{stem}"
                        if (repo / cand).is_file() and cand not in seen:
                            queue.append(cand)
        else:
            # a shell script: anything it names that exists here, it may run
            for token in text.replace('"', " ").replace("'", " ").split():
                token = token.lstrip("$").strip("(){};|&")
                for pre in ("tools/", "vibe-ic-marketplace/"):
                    if token.startswith(pre) and (repo / token).is_file():
                        if token not in seen:
                            queue.append(token)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--authorised", action="append", default=[],
                    help="a judge-set path this landing is allowed to change")
    ap.add_argument("--list", action="store_true", help="print the judge set and exit")
    a = ap.parse_args()
    repo = Path(a.repo).resolve()
    judges = judge_set(repo)
    if a.list:
        for p in sorted(judges):
            print(p)
        return 0
    changed = set(_git("-C", str(repo), "diff", "--name-only",
                       a.base, a.head).split())
    touched = sorted(judges & changed)
    unauthorised = [p for p in touched if p not in set(a.authorised)]
    if not judges:
        # An empty judge set would make every landing pass. That is the one
        # failure mode this check must never have.
        print("REFUSE  the judge set derived EMPTY — the derivation is broken, "
              "and an empty set would authorise every change to every judge")
        return 2
    if unauthorised:
        print(f"REFUSE  this candidate changes {len(unauthorised)} file(s) that "
              f"judge it, and they are not authorised:")
        for p in unauthorised:
            print(f"          {p}")
        print("        Re-run with --authorised <path> for each, or land them "
              "separately. The verifier still executes the BASE copy, so this "
              "is about REVIEW, not about which code ran.")
        return 1
    print(f"OK      judge set {len(judges)} file(s); candidate touches "
          f"{len(touched)}, all authorised" if touched else
          f"OK      judge set {len(judges)} file(s); candidate touches none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
