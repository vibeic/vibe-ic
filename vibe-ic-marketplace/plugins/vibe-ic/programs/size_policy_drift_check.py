#!/usr/bin/env python3
"""size_policy_drift_check.py — one policy about layout artefacts, stated once.

THIS GATE BLOCKS (rc=1) when the mechanisms that decide whether a layout
artefact ships stop agreeing with each other.

WHY IT EXISTS (#419)
--------------------
Five mechanisms held an opinion about `*.gds` / `*.def` / `*.spef` / `*.oas`,
each locally reasonable, and no two of them agreed:

  1. `.gitignore` ignored `*.gds`/`*.def` at the root and NEGATED them back
     for `benchmark-data/ic/**`; `*.spef`/`*.oas` were never ignored at all.
     So git accepted all four.
  2. The comment beside that negation said files over 50 MB would be stopped
     by "benchmark_evidence_structure_check 的 size-guard". No such guard
     existed — the sentence was the whole implementation.
  3. `benchmark_evidence_publish` dropped all four by EXTENSION, so a cell
     published by the program carried less evidence than the hand-staged
     cells it replaced.
  4. That program's docstring justified the drop as "gitignored / too large",
     which by then was false on both counts.
  5. `benchmark_evidence_structure_check`'s NO_RAW_GEOMETRY FAILED any cell
     carrying one — and therefore failed ALL THREE reference cells, the most
     complete evidence this repository publishes.

Nobody introduced a contradiction on purpose. Each mechanism was edited alone
and stayed true to what its author knew. What was missing was anything that
could notice the set had stopped being consistent.

WHAT IT CHECKS
--------------
  * the three modules that name a size ceiling agree on the number;
  * `.gitignore` still permits layout artefacts under `benchmark-data/ic/**`,
     since every other mechanism is now built on that being true;
  * neither module has reverted to an extension-only drop;
  * the docstrings do not still assert the superseded policy.

It reads the SOURCE, not the imported constants, for the docstring half —
a comment can go stale while the code stays right, and a stale comment is
what made this take five mechanisms to unpick.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

_CEILING_OWNERS = {
    "tracked_blob_size_guard.py": r"^_CEILING\s*=\s*(.+)$",
    "benchmark_evidence_publish.py": r"^_SIZE_CEILING\s*=\s*(.+)$",
    "benchmark_evidence_structure_check.py": r"^_SIZE_CEILING\s*=\s*(.+)$",
}

# Phrases that asserted the superseded policy. Any of them reappearing means
# a docstring has drifted back behind the code.
_STALE_CLAIMS = (
    "EXCLUDED BY CONSTRUCTION",
    "must never be committed",
    "must be gitignored; keep only",
)


def _repo_root(start: Path) -> Path:
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() \
        else start


def audit(programs: Path, gitignore: Path) -> dict:
    findings, ceilings = [], {}

    for name, pat in _CEILING_OWNERS.items():
        p = programs / name
        if not p.is_file():
            findings.append(f"MISSING: {name} — a ceiling owner is gone; the "
                            f"policy cannot be consistent with a missing half")
            continue
        src = p.read_text(errors="replace")
        m = re.search(pat, src, re.MULTILINE)
        if not m:
            findings.append(
                f"NO_CEILING: {name} no longer declares a size ceiling — an "
                f"extension-only rule is what #419 replaced")
            continue
        try:
            ceilings[name] = int(eval(m.group(1).split("#")[0].strip(),  # noqa: S307
                                      {"__builtins__": {}}, {}))
        except Exception:
            findings.append(f"UNPARSEABLE: {name} ceiling {m.group(1)!r}")
        for claim in _STALE_CLAIMS:
            if claim in src:
                findings.append(
                    f"STALE_CLAIM: {name} still says {claim!r} — the code "
                    f"routes by size; the prose says it refuses by kind")

    if len(set(ceilings.values())) > 1:
        findings.append(
            "CEILING_DISAGREEMENT: " + ", ".join(
                f"{k}={v}" for k, v in sorted(ceilings.items())))

    gi = gitignore.read_text(errors="replace") if gitignore.is_file() else ""
    for ext in ("gds", "def"):
        if not re.search(rf"^!benchmark-data/ic/\*\*/\*\.{ext}\s*$",
                         gi, re.MULTILINE):
            findings.append(
                f"GITIGNORE_REVERTED: the negation for *.{ext} under "
                f"benchmark-data/ic/** is gone. Every other mechanism now "
                f"assumes git accepts these; without it the publisher stages "
                f"files that can never be committed.")

    return {"program": "size_policy_drift_check", "ceilings": ceilings,
            "findings": findings,
            "verdict": "FAIL" if findings else "PASS"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--programs", default=str(_HERE))
    ap.add_argument("--gitignore", default=None)
    a = ap.parse_args(argv)
    programs = Path(a.programs).resolve()
    gi = Path(a.gitignore) if a.gitignore \
        else _repo_root(programs) / ".gitignore"

    rep = audit(programs, gi)
    if rep["findings"]:
        print(f"[FAIL] size_policy_drift_check: {len(rep['findings'])} "
              f"disagreement(s) about which layout artefacts ship:")
        for f in rep["findings"]:
            print(f"   {f}")
        return 1
    v = next(iter(rep["ceilings"].values()), 0)
    print(f"[PASS] size_policy_drift_check: {len(rep['ceilings'])} module(s) "
          f"agree on a {v / 1e6:.0f} MB ceiling, and .gitignore still accepts "
          f"layout artefacts under benchmark-data/ic/**.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
