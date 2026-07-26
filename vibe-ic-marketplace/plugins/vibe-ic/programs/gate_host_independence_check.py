#!/usr/bin/env python3
"""gate_host_independence_check.py — the same commit must give the same verdict.

THE CLASS (vibe-ic#447), and why a SECOND probe was needed
===========================================================
`gate_discloses_denominator_check` catches a gate that PASSes over an empty
tree without saying so. It does NOT catch the other half of the same class: a
gate that examines the WRONG POPULATION and reports confidently about it.

    provenance_output_hash_completeness_check  PASS in a worktree, FAIL in a
                                               working checkout (v1.6.88)
    cross_layer_reference_check                46 cells vs 23, making a
                                               COUNT baseline host-dependent
    l4_systemrdl_export                        299 documents on disk vs 201
                                               tracked (v1.6.91)
    benchmark_evidence_publish                 reproduced by the author IN the
                                               fix for #448, one day after
                                               landing the shared helper that
                                               exists to prevent it (v1.7.13)

Every one walked THIS MACHINE'S DISK where the question was what the PUBLISHED
tree carries. A working checkout keeps untracked run leftovers; a fresh clone
and a `git worktree` do not. So the verdict depended on who ran it — and always
in the same direction: whoever exercises the tool most gets the most false
alarms.

THE PROBE
=========
Run each corpus-scanning gate TWICE at the same commit — once in the working
checkout, once in a throwaway `git worktree` (tracked files only) — and require
the verdict line to be IDENTICAL. A difference is proof the gate is reading
something that is not in the commit.

Proven BOTH ways before landing, which is what separates this from a guess:

  negative control  the two gates fixed at v1.6.90/91 agree exactly
  positive control  restoring `cross_layer_reference_check`'s pre-fix
                    disk-walking `corpus_cells` makes the checkout report an
                    extra finding while the worktree says PASS — caught

WHY NOT A STATIC CHECK
======================
"Programs that rglob a project directory without using `_published_tree`" is 37
of them, and nearly all are RIGHT: a gate reading a RUN directory should read
the disk, because nothing is published yet. There is no static discriminator
for "this walk targets a published tree", so a static rule would fire on
legitimate code — the failure mode that got the orphan-capability detector
(#439) deleted rather than landed. Running it is the discriminator.

chip-AGNOSTIC: it compares process output, nothing else.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent

_RUN_RE = re.compile(
    # Accepts BOTH `run` and its `run_*` variants. A wrapper added for one
    # gate (`run_tolerating_uncheckable`) silently escaped this parser, so any
    # gate wired through it would not be covered — a coverage hole in the very
    # check that exists to close coverage holes.
    r'^\s*run(?:_\w+)?\s+"([^"]+)"\s+"?(\$ROOT|\$PLUGIN)"?\s+(.+)$', re.M)


def corpus_gates(script: Path) -> List[Tuple[str, str, str]]:
    """(label, cwd-token, command) for EVERY gate the CI script runs.

    The cwd token is LOAD-BEARING and was dropped in a first version: the
    `$PLUGIN`-scoped gates invoke a RELATIVE `programs/x.py`, so running
    them from the repo root made both trees fail to open the file and
    produced 9 identical-error "findings". A probe that reports a defect
    because it could not run the subject is worse than no probe."""
    try:
        text = script.read_text(errors="replace")
    except OSError:
        return []
    # NO FILTER. A first version kept only gates whose argv names
    # `benchmark-data` and parsed exactly ONE of them — most read the corpus
    # from an internal default, so the argv says nothing. Guessing which gates
    # "could" have the defect is how the defect keeps escaping; running all of
    # them costs a couple of minutes and needs no guess.
    return [(m.group(1), m.group(2), m.group(3).strip())
            for m in _RUN_RE.finditer(text)]


def _expand(cmd: str, root: Path) -> List[str]:
    c = cmd.replace('"$PG/', str(root / "vibe-ic-marketplace" / "plugins" /
                                 "vibe-ic" / "programs") + "/")
    c = c.replace('"$ROOT/', str(root) + "/").replace('"', "")
    c = c.replace("$PLUGIN", str(root / "vibe-ic-marketplace" / "plugins" /
                                 "vibe-ic"))
    c = c.replace("$ROOT", str(root))
    return c.split()


def _verdict_line(out: str) -> str:
    """The last non-empty line — the verdict a caller reads."""
    lines = [ln.rstrip() for ln in (out or "").splitlines() if ln.strip()]
    return lines[-1] if lines else "(no output)"


def audit(repo_root: Path, timeout: int = 600) -> Tuple[str, List[Dict]]:
    script = repo_root / "tools" / "ci" / "repo_hygiene_gates.sh"
    gates = corpus_gates(script)
    if not gates:
        # This program's own denominator: reporting clean over an empty gate
        # list is the defect it exists to catch, one level up.
        return "NOTHING_SCANNED", []

    # A DIRTY checkout makes the comparison meaningless: the worktree is at
    # HEAD, so every uncommitted edit and untracked file shows up as a
    # "difference" that has nothing to do with the defect being probed.
    # Measured while building this — an in-progress version of THIS program
    # made the chip-agnostic guard report 1241 files against the worktree's
    # 1240 and flagged itself as an unwired checker. Reporting those as
    # host-dependence would be a probe that fires on its own author.
    #
    # Refused rather than filtered: "the comparison could not be made" is its
    # own state and must not be dressed up as a clean one.
    st = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain"],
                        capture_output=True, text=True, timeout=timeout)
    dirty = [ln for ln in st.stdout.splitlines() if ln.strip()]
    if dirty:
        return "DIRTY_CHECKOUT", [{
            "gate": "(setup)", "kind": "DIRTY_CHECKOUT",
            "detail": (f"{len(dirty)} uncommitted/untracked path(s); the "
                       f"worktree is at HEAD so every one of them would read "
                       f"as a difference. First few: "
                       + ", ".join(x[3:][:40] for x in dirty[:4]))}]

    findings: List[Dict] = []
    td = tempfile.mkdtemp(prefix="hostindep-")
    wt = Path(td) / "wt"
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "add", "-q",
             "--detach", str(wt), "HEAD"],
            capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            # NEVER a silent pass — "I could not look" is its own state.
            return "WORKTREE_UNAVAILABLE", [{
                "gate": "(setup)", "kind": "WORKTREE_UNAVAILABLE",
                "detail": (r.stderr or r.stdout or "").strip()[:300]}]

        plugin_rel = Path("vibe-ic-marketplace") / "plugins" / "vibe-ic"
        for label, wd_tok, cmd in gates:
            ca = repo_root if wd_tok == "$ROOT" else repo_root / plugin_rel
            cb = wt if wd_tok == "$ROOT" else wt / plugin_rel
            a = subprocess.run(_expand(cmd, repo_root), cwd=str(ca),
                               capture_output=True, text=True, timeout=timeout)
            b = subprocess.run(_expand(cmd, wt), cwd=str(cb),
                               capture_output=True, text=True, timeout=timeout)
            va = _verdict_line(a.stdout + a.stderr)
            vb = _verdict_line(b.stdout + b.stderr)
            if va != vb or a.returncode != b.returncode:
                findings.append({
                    "gate": label, "kind": "HOST_DEPENDENT_VERDICT",
                    "detail": ("the same commit gives different answers in a "
                               "working checkout and a fresh worktree, so the "
                               "gate is reading something that is not in the "
                               "commit — almost always untracked run leftovers"),
                    "checkout": f"rc={a.returncode} {va[:200]}",
                    "worktree": f"rc={b.returncode} {vb[:200]}",
                })
    finally:
        subprocess.run(["git", "-C", str(repo_root), "worktree", "remove",
                        "--force", str(wt)], capture_output=True, text=True)
        shutil.rmtree(td, ignore_errors=True)

    return ("FAIL" if findings else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo_root", nargs="?", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args(argv)

    root = Path(a.repo_root).resolve() if a.repo_root else _PLUGIN.parents[2]
    verdict, findings = audit(root)
    gates = corpus_gates(root / "tools" / "ci" / "repo_hygiene_gates.sh")

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"verdict": verdict, "gates_probed": len(gates),
             "findings": findings}, indent=2) + "\n")

    if verdict == "NOTHING_SCANNED":
        print("NOTHING_SCANNED: no corpus-scanning gate parsed from "
              f"{root}/tools/ci/repo_hygiene_gates.sh", file=sys.stderr)
        return 2
    if verdict == "DIRTY_CHECKOUT":
        print("DIRTY_CHECKOUT: host-independence was NOT checked — the "
              "comparison is only meaningful against a clean tree. This is "
              "not a pass.", file=sys.stderr)
        for f in findings:
            print(f"      {f['detail']}", file=sys.stderr)
        return 2
    if verdict == "WORKTREE_UNAVAILABLE":
        print("WORKTREE_UNAVAILABLE: could not create a scratch git worktree, "
              "so host-independence was NOT checked. This is not a pass.",
              file=sys.stderr)
        for f in findings:
            print(f"      {f['detail']}", file=sys.stderr)
        return 2

    for f in findings:
        print(f"  [{f['kind']}] {f['gate']}", file=sys.stderr)
        print(f"      {f['detail']}", file=sys.stderr)
        print(f"      checkout: {f['checkout']}", file=sys.stderr)
        print(f"      worktree: {f['worktree']}", file=sys.stderr)

    if findings:
        print(f"[FAIL] {len(findings)} of {len(gates)} corpus gate(s) give a "
              f"HOST-DEPENDENT verdict.", file=sys.stderr)
        return 1
    print(f"[PASS] all {len(gates)} corpus-scanning gate(s) give the same "
          f"verdict in a working checkout and a fresh worktree.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
