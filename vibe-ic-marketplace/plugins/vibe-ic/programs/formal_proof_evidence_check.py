#!/usr/bin/env python3
"""formal_proof_evidence_check.py — Step 5 formal proof EVIDENCE-CHAIN
gate (ORGANIC-20260606 #448).

The audited residual (after #440 removed the runner's placeholder/
re-label emission): the flow gate itself still trusted the bare
`all_proved` field — a hand-planted `{"all_proved": true}` results.json
passed with no .sby and no SymbiYosys run anywhere. `all_proved: true`
is a CLAIM; this gate verifies the chain that substantiates it:

  (a) a `.sby` task exists under formal/ and every RTL/assertion file
      it references actually exists (it could elaborate);
  (b) a SymbiYosys log exists (sby/smtbmc tool signature) whose status
      is PASS;
  (c) results.json's `evidence` pointer (when path-shaped, per the
      #433 convention) dereferences to an existing non-empty file.

Verdicts / exit codes (chip-AGNOSTIC — structural artifacts only):
  0 = all_proved:true with a complete evidence chain (PASS)
  1 = all_proved claimed without the chain, or chain broken, or no
      proof claim at all (FAIL — a bare field is not a proof)
  2 = results.json honestly self-reports SKIPPED-CONDITION (no proof
      ran; the #440 manifest shape) — vacuous for THIS gate
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402

# SymbiYosys transcript signatures + pass markers. Tool-output shapes,
# not chip-class literals.
_SBY_SIG_RE = re.compile(
    r"SBY|symbiyosys|smtbmc|engine_\d|summary:\s*Elapsed", re.IGNORECASE)
_SBY_PASS_RE = re.compile(
    r"DONE \(PASS", re.IGNORECASE)
_SBY_FAIL_RE = re.compile(
    r"DONE \(FAIL|DONE \(ERROR|Status:\s*FAILED|Assert failed",
    re.IGNORECASE)
# files a .sby references: `read -formal <f>` / `read_verilog <f>` in
# [script], plus bare filenames in [files].
_SBY_READ_RE = re.compile(
    r"^\s*read(?:_verilog|_sv)?\s+(?:-formal\s+|-sv\s+)?(\S+)",
    re.IGNORECASE | re.MULTILINE)


def _resolve(formal_dir: Path, project: Path, token: str):
    """A referenced file may be relative to the .sby dir or the project."""
    if any(ch in token for ch in "*?["):
        hits = list(formal_dir.glob(token)) + list(project.glob(token))
        return hits[0] if hits else None
    for base in (formal_dir, project):
        p = base / token
        if p.is_file():
            return p
    return None


def audit(project: Path) -> dict:
    formal_dir = _pl.formal_dir(project)
    results_path = formal_dir / "results.json"
    rep = {"program": "formal_proof_evidence_check", "version": "1.0.0",
           "findings": []}

    if not results_path.is_file():
        rep.update(verdict="FAIL", rc=1)
        rep["findings"].append(
            "NO_RESULTS: formal/results.json absent — nothing claims a "
            "proof (step 5 reports its capability gap upstream)")
        return rep
    try:
        results = json.loads(results_path.read_text(errors="replace"))
    except (OSError, ValueError):
        rep.update(verdict="FAIL", rc=1)
        rep["findings"].append("BAD_JSON: results.json unparseable")
        return rep

    verdict_field = str(results.get("verdict", "")).upper().replace("_", "-")
    if verdict_field == "SKIPPED-CONDITION":
        rep.update(verdict="SKIPPED-CONDITION", rc=2)
        rep["findings"].append(
            "SELF_REPORTED_SKIP: results.json honestly reports no proof "
            "ran (#440 manifest shape) — vacuous for this gate")
        return rep

    if results.get("all_proved") is not True:
        rep.update(verdict="FAIL", rc=1)
        rep["findings"].append(
            "NO_PROOF_CLAIM: all_proved is not true — no proof to gate")
        return rep

    # (a) an elaboratable .sby ----------------------------------------------
    sby_ok = False
    sby_missing_refs = []
    for sby in sorted(formal_dir.glob("*.sby")):
        txt = sby.read_text(errors="replace")
        refs = _SBY_READ_RE.findall(txt)
        missing = [t for t in refs if _resolve(formal_dir, project, t) is None]
        if not missing and refs:
            sby_ok = True
            rep["sby"] = str(sby.relative_to(project))
            break
        if missing:
            sby_missing_refs.append(f"{sby.name}: {', '.join(missing[:4])}")
    if not sby_ok:
        rep["findings"].append(
            "SBY_CHAIN_BROKEN (#448): no .sby whose referenced files all "
            "exist" + (f" — missing: {'; '.join(sby_missing_refs[:3])}"
                       if sby_missing_refs else " (no .sby found)"))

    # (b) a SymbiYosys log with PASS status ---------------------------------
    log_ok = False
    log_candidates = (list(formal_dir.glob("*.log"))
                      + list(formal_dir.rglob("logfile.txt"))
                      + list(formal_dir.rglob("*.sby.log")))
    for lg in sorted(set(log_candidates)):
        try:
            txt = lg.read_text(errors="replace")
        except OSError:
            continue
        if _SBY_SIG_RE.search(txt) and _SBY_PASS_RE.search(txt) \
                and not _SBY_FAIL_RE.search(txt):
            log_ok = True
            rep["sby_log"] = str(lg.relative_to(project))
            break
    if not log_ok:
        rep["findings"].append(
            "SBY_LOG_MISSING (#448): no SymbiYosys transcript "
            "(sby/smtbmc signature) with PASS status under formal/ — "
            "all_proved without a proof run is a bare field, not a proof")

    # (c) evidence pointer dereferences (path-shaped only, #433 convention) -
    ev_ok = True
    ev = results.get("evidence")
    if isinstance(ev, str) and "/" in ev:
        tgt = project / ev
        if not tgt.is_file() or tgt.stat().st_size == 0:
            ev_ok = False
            rep["findings"].append(
                f"EVIDENCE_MISSING (#448): results.json evidence "
                f"'{ev}' does not exist or is empty")

    if sby_ok and log_ok and ev_ok:
        rep.update(verdict="PASS", rc=0)
        rep["findings"].append(
            "PROOF_CHAIN_OK: all_proved substantiated by an "
            "elaboratable .sby + SymbiYosys PASS transcript")
    else:
        rep.update(verdict="FAIL", rc=1)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1
    rep = audit(args.project_dir.resolve())
    rc = rep.pop("rc")
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
