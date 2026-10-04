#!/usr/bin/env python3
"""Produce native merged-top PV, then derive M4 from current M1-M3 evidence.

ENFORCEMENT: blocking in M4, advisory to the independent digital track.
No ready assertion is an input. LibreLane's existing material-bound evidence
reader verifies Magic/KLayout/Netgen/antenna reports against the merged GDS.
Ordinary M4 first runs those existing producers for the declared logical pair.
Missing coverage cannot fall back to legacy counts. --check-only compares an
existing signoff to the fresh derivation; it never creates that signoff.
rc 0 genuinely ready, 2 unmeasured/upstream blocked production, 1 audit refused.
"""
from __future__ import annotations
# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import argparse
import sys
from pathlib import Path

from _atomic_artefact import write_json
import mixed_signal_m3_run as m3
import mixed_signal_power_domain_run as m2
import librelane_signoff_evidence as pv
import _mixed_signal_top_pv as top_pv

PROGRAM = "mixed_signal_signoff_run"
SCHEMA = "vibeic.mixed_signal.m4.v1"
OUTPUT = m3.DIR + "/signoff.json"
UPSTREAM = ("phase3/mixed_signal/top_merged.gds", m3.DIR + "/merge.json",
            m3.DIR + "/top_lvs.json", m3.DIR + "/power_domain_run.json",
            *(m3.DIR + "/" + name for name in m2.OUTPUTS),
            m3.COSIM, m3.SI, m3.RECEIPT,
            "reports/phase3/librelane_pv_drc.json",
            "reports/phase3/librelane_pv_lvs.json",
            "reports/phase3/antenna_librelane.json", "reports/phase3/fill_librelane.json",
            top_pv.OUTPUT, top_pv.REQUEST)


def bindings(project):
    paths = set(UPSTREAM)
    # Native readers also verify their input/state/log/config dependencies.
    # Retain their current records in the rollup's explicit source binding.
    for pattern in ("phase3/librelane/**/vibeic_receipt.json",
                    "phase3/librelane/**/input_fingerprint.json",
                    "phase3/librelane/**/drc_judgment.json"):
        paths.update(str(p.relative_to(project)) for p in project.glob(pattern))
    result = {}
    for rel in sorted(paths):
        path = project / rel
        if not path.resolve().is_relative_to(project.resolve()):
            raise m3.Refusal("FOREIGN_UPSTREAM", rel)
        result[rel] = m3.digest(path) if path.is_file() else None
    return result


def derive(project, top):
    who = m3.subject(project, top)
    before = bindings(project)
    for rel in (m3.RECEIPT, m3.DIR + "/power_domain_run.json"):
        try:
            produced = m3.read(project / rel)
        except m3.Refusal:
            continue  # Missing/malformed production is disclosed by its audit.
        if isinstance(produced.get("top"), str) and produced["top"] != top:
            raise m3.Refusal("WRONG_DESIGN", "upstream production belongs to another top")
    checks = []
    merged = project / "phase3/mixed_signal/top_merged.gds"
    try:
        top_pv.verify(project, top)
        production_reason = None
    except (ValueError, OSError, KeyError, TypeError) as exc:
        production_reason = str(exc)
    # An M1 PASS without exact native subject binding cannot certify a layout.
    # The merged-top LVS obligation below supplies that binding when available.
    try:
        merge = m3.read(project / (m3.DIR + "/merge.json"))
        lvs = m3.read(project / (m3.DIR + "/top_lvs.json"))
        ok = (merge.get("verdict") == "PASS" and lvs.get("verdict") == "PASS"
              and lvs.get("program") == "mixed_signal_top_lvs_run"
              and lvs.get("layout") == "phase3/mixed_signal/top_merged.gds")
        checks.append({"step": "M1", "verdict": "FAIL" if "FAIL" in
                       (merge.get("verdict"), lvs.get("verdict")) else "NOT_MEASURED" if "NOT_MEASURED" in
                       (merge.get("verdict"), lvs.get("verdict")) else "NOT_VERIFIED",
                       "reason": "merged-top native LVS binding required" if ok
                       else "M1 absent, failed, waived, or wrong layout"})
    except m3.Refusal as exc:
        checks.append({"step": "M1", "verdict": "NOT_VERIFIED", "reason": str(exc)})
    try:
        receipt = m2.verify(project)
        if receipt.get("top") != top:
            raise m3.Refusal("WRONG_DESIGN", "M2 top differs from M4")
        checks.append({"step": "M2", "verdict": "PASS",
                       "reason": "current placed structural evidence only"})
    except (ValueError, OSError, KeyError, TypeError) as exc:
        try:
            upstream = m3.read(project / (m3.DIR + "/power_domain_run.json")).get("verdict")
        except m3.Refusal:
            upstream = None
        checks.append({"step": "M2", "verdict": upstream if upstream in ("FAIL", "NOT_MEASURED")
                       else "NOT_VERIFIED", "reason": str(exc)})
    for kind in ("cosim", "si"):
        check = m3.audit(project, kind)
        checks.append({"step": "M3_" + kind, "verdict": check["verdict"],
                       "evidence_sha256": check["output_sha256"],
                       "findings": check["findings"]})
    for kind in ("drc", "lvs", "antenna", "density"):
        try:
            native = pv.obligation(project, kind, layout=merged, mixed_top=True)
            if native is None:
                native = {"verdict": "NOT_MEASURED", "reason":
                          "applicable LibreLane native producer not selected; no legacy fallback"}
        except (ValueError, OSError, KeyError, TypeError) as exc:
            native = {"verdict": "NOT_MEASURED", "reason": str(exc)}
        if production_reason and native.get("verdict") != "FAIL":
            native = dict(native, verdict="NOT_MEASURED", production_refusal=production_reason)
        checks.append({"step": "PV_" + kind, "verdict": native.get("verdict", "NOT_MEASURED"),
                       "native": native})
        if kind == "lvs" and native.get("verdict") == "PASS" and checks[0].get("reason") == "merged-top native LVS binding required":
            checks[0] = {"step": "M1", "verdict": "PASS",
                         "reason": "native LVS verified exact current merged GDS"}
    if bindings(project) != before:
        raise m3.Refusal("STALE_UPSTREAM", "evidence changed during derivation")
    ready = all(c["verdict"] == "PASS" for c in checks)
    return {"program": PROGRAM, "schema": SCHEMA, **who, "inputs": before,
            "checks": checks, "ready_for_tapeout": ready,
            "verdict": "PASS" if ready else "FAIL" if any(c["verdict"] == "FAIL" for c in checks) else "NOT_READY"}


def verify(project):
    data = m3.read(project / OUTPUT)
    if (data.get("program") != PROGRAM or data.get("schema") != SCHEMA
            or data.get("project") != m3.subject(project, data.get("top"))["project"]):
        raise m3.Refusal("WRONG_PRODUCER_OR_PROJECT", "M4 needs current deterministic production")
    expected = derive(project, data.get("top"))
    if data != expected:
        raise m3.Refusal("STALE_OR_MISMATCHED_SIGNOFF", "signoff differs from current derivation")
    if expected["ready_for_tapeout"] is not True:
        if expected["verdict"] == "FAIL":
            raise m3.Refusal("UPSTREAM_FAILED", "current required evidence contains FAIL")
        raise m3.Refusal("UPSTREAM_NOT_VERIFIED", "current M1-M3/top-level PV do not justify readiness")
    return expected


def audit(project):
    report = {"program": PROGRAM, "verdict": "NOT_VERIFIED", "passed": False,
              "ready_for_tapeout": False, "findings": []}
    try:
        data = verify(project)
        report.update(verdict="PASS", passed=True, ready_for_tapeout=True, checks=data["checks"])
    except (ValueError, OSError, KeyError, TypeError) as exc:
        if getattr(exc, "rule", "") == "UPSTREAM_FAILED":
            report["verdict"] = "FAIL"
        report["findings"].append({"rule": getattr(exc, "rule", "INVALID_EVIDENCE"),
                                   "message": str(exc)})
    path = project / OUTPUT
    report["output_sha256"] = m3.digest(path) if path.is_file() else None
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--top")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    project = args.project.resolve()
    try:
        protected = (*bindings(project), OUTPUT)
        m3.guard_audit_path(project, args.json, protected)
        if args.check_only:
            report = audit(project)
            rc = 0 if report["passed"] else 1
        else:
            # Previous signoff is never read by derive, and cannot survive a
            # failed attempt as the current invocation's readiness result.
            if not (project / OUTPUT).resolve().is_relative_to(project):
                raise m3.Refusal("FOREIGN_OUTPUT", OUTPUT)
            (project / OUTPUT).unlink(missing_ok=True)
            top_pv.produce(project, args.top)
            report = derive(project, args.top)
            write_json(project / OUTPUT, report)
            rc = 0 if report["ready_for_tapeout"] else 1 if report["verdict"] == "FAIL" else 2
        m3.audit_output(project, args.json, report, protected)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"[{PROGRAM}] {getattr(exc, 'rule', 'INVALID_EVIDENCE')}: {exc}", file=sys.stderr)
        return 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
