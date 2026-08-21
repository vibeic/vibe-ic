#!/usr/bin/env python3
"""tool_warning_id_novelty_check.py — a tool diagnostic ID that was not there
last time is BLOCKING (vibe-ic#1081).

WHY THIS OWES NO ORACLE, WHICH IS THE WHOLE POINT
=================================================
Adopted from OpenROAD-flow-scripts @ f9ec54a6. ORFS counts every tool warning by
message ID and turns it into a metric:

    "cts__flow__warnings__count:ORD-0012": 1
    "cts__flow__warnings__count:RSZ-0062": 1

and reports an unseen ID at `flow/util/checkMetadata.py:91-95`. But
`flow/util/genRuleFile.py:70-75` assigns `level: warning`, so a brand-new tool
warning never fails their build.

We make it BLOCKING, and the reason that is safe is the interesting part: this
check never asks *"is this warning acceptable"* — a question that needs an
oracle. It asks *"did this ID exist last time"*, which is decidable from two
runs of the same cell and nothing else. That is exactly the §D9 property.

A new `DRT-xxxx` / `ODB-xxxx` appearing between two runs of the same design is a
change in tool behaviour nobody decided to accept. Today it is invisible to us.

WHAT IS COUNTED, AND WHAT DELIBERATELY IS NOT
=============================================
Only `WARNING` and `ERROR` diagnostics. `INFO` is excluded on measurement, not
taste: the tracked corpus carries 26x `[INFO DRT-0036]`, 16x `[INFO RCX-0442]`
and so on — progress chatter whose IDs churn with every tool build and would
bury the signal this check exists to surface.

THE ACCEPTANCE LIST EXPIRES LOUDLY
==================================
#1081 requires the adjudication list to be checked itself, "so a stale entry
expires loudly rather than accumulating". An entry whose ID no longer appears in
the run is a FINDING, not a silent pass: it means either the tool stopped
emitting it (the acceptance is dead weight and should be removed) or the check
stopped seeing it (the acceptance is now hiding a live diagnostic). Both need a
human, and neither is discoverable if a stale entry is simply ignored.

Every entry must carry a DATE and a REASON. An entry with a bare ID is refused
at load — an undated, unreasoned acceptance is indistinguishable from someone
silencing a diagnostic they did not look at.

EXIT CODES: 0 PASS, 1 FAIL (blocking), 2 VACUOUS/could-not-look.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2

#: `[WARNING DRT-0349]` / `[ERROR ODB-0220]`. The tool prefix is 2-5 upper-case
#: letters and the number is zero-padded — the shape ORFS emits and the shape
#: measured in this repo's own tracked logs.
DIAG_RE = re.compile(r"\[(WARNING|ERROR)\s+([A-Z]{2,5}-\d{3,5})\]")

LOG_SUFFIXES = (".log", ".rpt", ".out")

BASELINE_NAME = "tool_warning_id_baseline.json"


def scan_ids(root: Path):
    """{message_id: {"count": n, "first_seen_in": rel}} over a run tree."""
    found = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith(LOG_SUFFIXES):
                continue
            p = Path(dirpath) / name
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for _sev, mid in DIAG_RE.findall(text):
                rec = found.setdefault(
                    mid, {"count": 0, "first_seen_in": str(p.relative_to(root))})
                rec["count"] += 1
    return found


def load_baseline(path: Path):
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    return set(doc.get("ids") or [])


def load_acceptances(path: Path):
    """{id: entry} — every entry must carry a date AND a reason.

    Returns (accepted, malformed). Malformed entries are NOT silently dropped:
    an acceptance nobody dated or explained is refused out loud.
    """
    if path is None or not path.is_file():
        return {}, []
    doc = json.loads(path.read_text(encoding="utf-8"))
    accepted, malformed = {}, []
    for e in doc.get("accepted") or []:
        if not isinstance(e, dict):
            malformed.append(repr(e)[:60])
            continue
        mid = e.get("id")
        if not mid or not e.get("accepted_on") or not (e.get("reason") or "").strip():
            malformed.append(
                f"{mid or '<no id>'}: needs both `accepted_on` and a non-empty "
                f"`reason`")
            continue
        accepted[mid] = e
    return accepted, malformed


def audit(run_dir: Path, baseline_path: Path, accept_path):
    seen = scan_ids(run_dir)
    baseline = load_baseline(baseline_path)
    accepted, malformed = load_acceptances(accept_path)

    rep = {"run_dir": str(run_dir), "baseline": str(baseline_path),
           "ids_seen": len(seen), "baseline_ids": None if baseline is None else len(baseline),
           "findings": [], "new_ids": [], "stale_acceptances": [],
           "malformed_acceptances": malformed}

    if not seen:
        rep["verdict"] = "VACUOUS"
        rep["reason"] = (
            f"no WARNING/ERROR diagnostic id was found under {run_dir} — no "
            f"{'/'.join(LOG_SUFFIXES)} file carried one, so nothing was compared")
        return rep

    if baseline is None:
        rep["verdict"] = "VACUOUS"
        rep["reason"] = (
            f"no baseline at {baseline_path} — 'was this id here last time' "
            f"cannot be answered from one run. Record one with --write-baseline; "
            f"this is NOT a pass over {len(seen)} observed id(s)")
        return rep

    for mid in malformed:
        rep["findings"].append(f"MALFORMED ACCEPTANCE — {mid}")

    for mid in sorted(set(seen) - baseline):
        if mid in accepted:
            continue
        rep["new_ids"].append(mid)
        rep["findings"].append(
            f"NEW DIAGNOSTIC {mid} ({seen[mid]['count']}x, first in "
            f"{seen[mid]['first_seen_in']}) — not in the baseline and not "
            f"accepted. Tool behaviour changed and nobody decided to accept it.")

    # The acceptance list is checked too: an entry for an id that no longer
    # appears is dead weight OR is hiding a diagnostic this scan stopped seeing.
    for mid, e in sorted(accepted.items()):
        if mid not in seen:
            rep["stale_acceptances"].append(mid)
            rep["findings"].append(
                f"STALE ACCEPTANCE {mid} (accepted {e['accepted_on']}: "
                f"{e['reason'][:60]}) — the id no longer appears. Either the "
                f"tool stopped emitting it, or this scan stopped seeing it; "
                f"remove the entry or find out which.")

    rep["verdict"] = "FAIL" if rep["findings"] else "PASS"
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--accept", type=Path)
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--json", dest="json_out", type=Path)
    args = ap.parse_args(argv)

    run_dir = args.run_dir
    baseline_path = args.baseline or (run_dir / BASELINE_NAME)

    if not run_dir.is_dir():
        print(f"[FAIL] {run_dir} is not a directory", file=sys.stderr)
        return RC_FAIL

    if args.write_baseline:
        seen = scan_ids(run_dir)
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(
            {"_comment": ("Tool diagnostic ids observed in this cell "
                          "(vibe-ic#1081). An id absent here and unaccepted is "
                          "BLOCKING on the next run."),
             "ids": sorted(seen)}, indent=2) + "\n", encoding="utf-8")
        print(f"[OK] recorded {len(seen)} diagnostic id(s) -> {baseline_path}",
              file=sys.stderr)
        return RC_PASS

    rep = audit(run_dir, baseline_path, args.accept)
    if args.json_out:
        args.json_out.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")

    if rep["verdict"] == "VACUOUS":
        print(f"[VACUOUS] tool_warning_id_novelty: {rep['reason']}",
              file=sys.stderr)
        return RC_VACUOUS

    if rep["verdict"] == "FAIL":
        print(f"[FAIL] tool_warning_id_novelty: {len(rep['findings'])} "
              f"finding(s) over {rep['ids_seen']} observed id(s):", file=sys.stderr)
        for f in rep["findings"]:
            print(f"    {f}", file=sys.stderr)
        print("\nBLOCKING. This asks only whether the id was here last time — "
              "no oracle, no judgement about whether the warning is acceptable.",
              file=sys.stderr)
        return RC_FAIL

    print(f"[PASS] tool_warning_id_novelty: {rep['ids_seen']} diagnostic id(s), "
          f"all present in the {rep['baseline_ids']}-id baseline or explicitly "
          f"accepted; no stale acceptance.", file=sys.stderr)
    return RC_PASS


if __name__ == "__main__":
    raise SystemExit(main())
