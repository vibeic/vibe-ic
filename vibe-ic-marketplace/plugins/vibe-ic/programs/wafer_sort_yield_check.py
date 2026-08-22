#!/usr/bin/env python3
"""
wafer_sort_yield_check.py — gate (v1.6.13 Wave 88, renumbered
in v1.6.14 Wave 90: Step 36 → 37; v1.6.15 Wave 91: Step 37 → 38;
re-numbered again to Step 39 in the phase1_phase2_phase3.yaml flow).

Step 39 — wafer sort / probe-test yield analysis

Anti-fabrication hardening (Wave 95)
------------------------------------
The v1.6.13 implementation was a PASS-on-presence STUB: it only checked
that ``wafer_sort_yield.json`` and ``wafer_map.csv`` existed and then
echoed PASS, while the flow gate trusted a self-produced boolean field
``yield_meets_target`` written by the very step it was supposed to audit.
That is an anti-fabrication hole — the producing step asserts its own PASS.

This version performs REAL DETERMINISTIC SUBSTANCE verification:

  1. Parse ``wafer_sort_yield.json`` and read the *measured* yield:
       - from explicit die counts (good_die / total_die, with the usual
         aliases tested_die / pass_die / fail_die), preferred, OR
       - from an explicit measured-yield percentage field.
     When both are present they must be self-consistent (±0.5 pp).
  2. Read the *target* yield from the same artefact (target_yield_pct /
     yield_target_pct / target_yield / target). The target is a spec
     value — it is NOT defaulted. If neither counts-derived measurement
     nor a stated target can be read, the check FAILs honestly (it does
     NOT fabricate a threshold).
  3. FAIL (rc=1) if measured_yield_pct < target_yield_pct.
  4. Verify ``wafer_map.csv`` data-row count is consistent with the
     reported total_die (header excluded; multi-wafer maps summed).

Verdicts
--------
* PASS    (rc=0) — measured yield ≥ target AND wafer-map rows consistent.
* FAIL    (rc=1) — measured < target, OR data missing/empty/unparseable,
                   OR yield_pct vs counts inconsistent, OR wafer-map row
                   count inconsistent with total_die. The step's
                   ``condition`` (silicon_received.json present) already
                   guarantees silicon exists, so absent yield data is a
                   real failure, never a vacuous pass.
* WAIVED  (rc=0) — ``waivers.json`` declares the step waived (ticket +
                   reason recorded); used for non-production runs.
* SKIP    (rc=2) — project dir not found (operational, not silicon).

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded. No yield
target is invented — it must come from the produced artefact.

Usage
-----
    python3 wafer_sort_yield_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


_GATE_NAME = "wafer_sort_yield_check"
_GATE_LABEL = "wafer_sort_yield"

# Canonical (current flow) locations first, legacy fallback second.
_YIELD_JSON_CANDIDATES = [
    "phase3/stage5_manufacturing/wafer_sort_yield.json",
    "manufacturing/wafer_sort_yield.json",
]
_WAFER_MAP_CANDIDATES = [
    "phase3/stage5_manufacturing/wafer_map.csv",
    "manufacturing/wafer_map.csv",
]

# Self-consistency tolerance between a stated yield_pct and the
# counts-derived yield, in percentage points.
_CONSISTENCY_TOL_PP = 0.5
# Tolerance (in die) for wafer-map row-count vs total_die. Real probe
# maps occasionally omit edge/scribe sites; we allow a small slack but
# default to exact unless a slack field is provided.
_DEFAULT_MAP_SLACK = 0


def _load_waivers(project):
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text()).get("waived_steps") or []
    except Exception:
        return []


def _step_waived(project, step_label):
    for w in _load_waivers(project):
        sid = str(w.get("id", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or step_label in ticket:
            return w
    return None


def _first_existing(project: Path, candidates):
    for rel in candidates:
        p = project / rel
        if p.is_file():
            return rel, p
    return None, None


def _num(d, *keys):
    """Return the first numeric value among keys (float), else None."""
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return None


def _parse_yield(doc: dict):
    """Extract (measured_pct, target_pct, total_die, detail) from the JSON.

    measured_pct / target_pct / total_die are None when not derivable.
    detail is a list of human-readable strings describing what was read.
    Raises no exception; returns Nones on absence so the caller decides
    the verdict.
    """
    detail = []

    good = _num(doc, "good_die", "pass_die", "passing_die", "good_dies")
    fail = _num(doc, "fail_die", "failed_die", "failing_die", "bad_die")
    total = _num(doc, "total_die", "tested_die", "total_dies", "die_total",
                 "gross_die")

    # Reconstruct total / good from whatever pair is present.
    if total is None and good is not None and fail is not None:
        total = good + fail
    if good is None and total is not None and fail is not None:
        good = total - fail

    measured_from_counts = None
    if good is not None and total is not None and total > 0:
        measured_from_counts = 100.0 * good / total
        detail.append(
            f"counts: good_die={int(good)} / total_die={int(total)} "
            f"=> {measured_from_counts:.3f}%"
        )

    stated = _num(doc, "yield_pct", "measured_yield_pct", "yield_percent",
                  "yield", "sort_yield_pct", "probe_yield_pct")
    if stated is not None:
        detail.append(f"stated yield={stated:.3f}%")

    # Prefer the counts-derived value (independently recomputed) over the
    # self-asserted stated percentage.
    measured = measured_from_counts if measured_from_counts is not None else stated

    target = _num(doc, "target_yield_pct", "yield_target_pct", "target_yield",
                  "yield_target", "target", "target_pct")
    if target is not None:
        detail.append(f"target yield={target:.3f}%")

    return measured, target, measured_from_counts, stated, total, detail


def _count_map_rows(path: Path):
    """Return number of die-record data rows in the wafer map CSV
    (header excluded). A header is assumed when the first row is fully
    non-numeric in its presumed bin/count column. Blank lines ignored.
    Returns (rows, has_header)."""
    with path.open(newline="") as fh:
        reader = csv.reader(fh)
        rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return 0, False
    # Header heuristic: first row has no purely-numeric cell at all.
    first = rows[0]
    def _looks_numeric(cell):
        try:
            float(cell.strip())
            return True
        except ValueError:
            return False
    has_header = not any(_looks_numeric(c) for c in first)
    data_rows = len(rows) - (1 if has_header else 0)
    return data_rows, has_header


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--step-label", default=_GATE_LABEL)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}", file=sys.stderr)
        return 2

    yield_rel, yield_path = _first_existing(project, _YIELD_JSON_CANDIDATES)
    map_rel, map_path = _first_existing(project, _WAFER_MAP_CANDIDATES)

    waiver = _step_waived(project, args.step_label)

    findings = []
    verdict = "FAIL"
    rc = 1
    measured = target = total = None
    map_rows = None

    # ---- Waiver path (explicit, recorded) -------------------------------
    if waiver and (yield_path is None or map_path is None):
        verdict, rc = "WAIVED", 0
        findings.append({
            "severity": "WAIVED", "rule": "STEP_WAIVED",
            "message": f"waiver={waiver.get('ticket', '?')}: "
                       f"{waiver.get('reason', '?')}",
        })
        _emit(args, project, verdict, args.step_label, yield_rel, map_rel,
              waiver, measured, target, total, map_rows, findings)
        return rc

    # ---- Honest FAIL on missing required artefacts ----------------------
    # The step condition (silicon_received.json) guarantees silicon exists,
    # so absent wafer-sort data is a real failure — never a vacuous pass.
    missing = []
    if yield_path is None:
        missing.append("wafer_sort_yield.json")
    if map_path is None:
        missing.append("wafer_map.csv")
    if missing:
        findings.append({
            "severity": "FAIL", "rule": "REQUIRED_ARTEFACT_MISSING",
            "message": f"silicon received but wafer-sort artefact(s) missing: "
                       f"{missing}",
        })
        _emit(args, project, "FAIL", args.step_label, yield_rel, map_rel,
              waiver, measured, target, total, map_rows, findings)
        return 1

    # ---- Parse the yield JSON ------------------------------------------
    try:
        doc = json.loads(yield_path.read_text())
        if not isinstance(doc, dict):
            raise ValueError("top-level JSON is not an object")
    except Exception as e:  # noqa: BLE001
        findings.append({
            "severity": "FAIL", "rule": "YIELD_JSON_UNPARSEABLE",
            "message": f"cannot parse {yield_rel}: {e}",
        })
        _emit(args, project, "FAIL", args.step_label, yield_rel, map_rel,
              waiver, measured, target, total, map_rows, findings)
        return 1

    measured, target, measured_from_counts, stated, total, detail = _parse_yield(doc)
    for d in detail:
        findings.append({"severity": "INFO", "rule": "YIELD_READ", "message": d})

    # Cannot verify substance without a measurement.
    if measured is None:
        findings.append({
            "severity": "FAIL", "rule": "NO_MEASURED_YIELD",
            "message": "no die counts (good_die/total_die) nor measured "
                       "yield percentage present — cannot verify substance",
        })
        _emit(args, project, "FAIL", args.step_label, yield_rel, map_rel,
              waiver, measured, target, total, map_rows, findings)
        return 1

    # Cannot verify substance without a spec target. We do NOT fabricate one.
    if target is None:
        findings.append({
            "severity": "FAIL", "rule": "NO_TARGET_YIELD",
            "message": "no target_yield_pct stated in artefact — refusing to "
                       "fabricate a threshold; cannot determine PASS/FAIL",
        })
        _emit(args, project, "FAIL", args.step_label, yield_rel, map_rel,
              waiver, measured, target, total, map_rows, findings)
        return 1

    # Cross-check: stated yield_pct vs counts-derived yield must agree.
    if measured_from_counts is not None and stated is not None:
        if abs(measured_from_counts - stated) > _CONSISTENCY_TOL_PP:
            findings.append({
                "severity": "FAIL", "rule": "YIELD_SELF_INCONSISTENT",
                "message": f"stated yield {stated:.3f}% disagrees with "
                           f"counts-derived {measured_from_counts:.3f}% "
                           f"(> {_CONSISTENCY_TOL_PP} pp) — fabrication smell",
            })
            _emit(args, project, "FAIL", args.step_label, yield_rel, map_rel,
                  waiver, measured, target, total, map_rows, findings)
            return 1

    # ---- Wafer-map row-count consistency vs total_die ------------------
    try:
        map_rows, has_header = _count_map_rows(map_path)
    except Exception as e:  # noqa: BLE001
        findings.append({
            "severity": "FAIL", "rule": "WAFER_MAP_UNREADABLE",
            "message": f"cannot read {map_rel}: {e}",
        })
        _emit(args, project, "FAIL", args.step_label, yield_rel, map_rel,
              waiver, measured, target, total, map_rows, findings)
        return 1

    if map_rows == 0:
        findings.append({
            "severity": "FAIL", "rule": "WAFER_MAP_EMPTY",
            "message": f"{map_rel} contains no die-record rows",
        })
        _emit(args, project, "FAIL", args.step_label, yield_rel, map_rel,
              waiver, measured, target, total, map_rows, findings)
        return 1

    if total is not None:
        slack = doc.get("wafer_map_row_slack")
        try:
            slack = int(slack) if slack is not None else _DEFAULT_MAP_SLACK
        except (TypeError, ValueError):
            slack = _DEFAULT_MAP_SLACK
        if abs(map_rows - int(total)) > slack:
            findings.append({
                "severity": "FAIL", "rule": "WAFER_MAP_ROWCOUNT_INCONSISTENT",
                "message": f"wafer_map.csv has {map_rows} die rows but "
                           f"total_die={int(total)} (slack {slack}) — "
                           f"map/summary inconsistency",
            })
            _emit(args, project, "FAIL", args.step_label, yield_rel, map_rel,
                  waiver, measured, target, total, map_rows, findings)
            return 1
        findings.append({
            "severity": "INFO", "rule": "WAFER_MAP_CONSISTENT",
            "message": f"wafer_map.csv {map_rows} die rows == total_die "
                       f"{int(total)}",
        })
    else:
        findings.append({
            "severity": "INFO", "rule": "WAFER_MAP_ROWS",
            "message": f"wafer_map.csv {map_rows} die rows "
                       f"(no total_die to cross-check)",
        })

    # ---- The real yield decision ---------------------------------------
    if measured + 1e-9 < target:
        verdict, rc = "FAIL", 1
        findings.append({
            "severity": "FAIL", "rule": "YIELD_BELOW_TARGET",
            "message": f"measured yield {measured:.3f}% < target "
                       f"{target:.3f}%",
        })
    else:
        verdict, rc = "PASS", 0
        findings.append({
            "severity": "INFO", "rule": "YIELD_MEETS_TARGET",
            "message": f"measured yield {measured:.3f}% >= target "
                       f"{target:.3f}%",
        })

    _emit(args, project, verdict, args.step_label, yield_rel, map_rel,
          waiver, measured, target, total, map_rows, findings)
    return rc


def _emit(args, project, verdict, step_label, yield_rel, map_rel, waiver,
          measured, target, total, map_rows, findings):
    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": step_label,
        "yield_json": yield_rel,
        "wafer_map_csv": map_rel,
        "measured_yield_pct": (round(measured, 4) if measured is not None
                               else None),
        "target_yield_pct": (round(target, 4) if target is not None
                             else None),
        "total_die": (int(total) if total is not None else None),
        "wafer_map_rows": map_rows,
        "waiver": waiver,
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    if measured is not None and target is not None:
        print(f"  yield:   {measured:.3f}% (target {target:.3f}%)")
    if map_rows is not None:
        print(f"  map rows: {map_rows}"
              + (f" / total_die {int(total)}" if total is not None else ""))
    for f in findings:
        if f["severity"] in ("FAIL", "WAIVED"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")


if __name__ == "__main__":
    sys.exit(main())
