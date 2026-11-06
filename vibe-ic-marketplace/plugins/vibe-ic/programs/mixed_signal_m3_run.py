#!/usr/bin/env python3
"""M3's current-input producer boundary, with honest unavailable coverage.

ENFORCEMENT: blocking in M3, advisory to the independent digital track.
This lane cannot qualify A9's A3-netlist observer as a post-layout wrapper
simulation, or si_signoff_timing_aware's advisory screen as noise signoff.
An explicit native.json contract enables bounded ngspice + actual-wrapper
Icarus/RNM component measurements. Missing physical SI remains NOT_MEASURED.
Unsupported contracts still fail closed. Audit rc=1 is never a vacuous rc=2.
--check-only reads existing bytes; it never produces the required outputs.
"""
from __future__ import annotations


# `programs/` is a flat directory whose modules import each other by bare name
# (vibe-ic#2104): restore the condition a by-path load does not provide.
import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from _atomic_artefact import write_json
from l_doc_consumer_contract import load_l_doc, l_doc_fields
from execution_mixed_subject import project_subject

PROGRAM = "mixed_signal_m3_run"
SCHEMA = "vibeic.mixed_signal.m3.unmeasured.v1"
DIR = "reports/analog/mixed_signal"
COSIM = "phase3/mixed_signal/cosim/mixed_signal_results.json"
SI = DIR + "/interface_si.json"
RECEIPT = DIR + "/m3_run.json"
OUTPUTS = {"cosim": COSIM, "si": SI}


class Refusal(ValueError):
    def __init__(self, rule, message):
        self.rule = rule
        super().__init__(message)


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def read(path):
    try:
        obj = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Refusal("MISSING_OR_MALFORMED_EVIDENCE", str(path)) from exc
    if not isinstance(obj, dict):
        raise Refusal("MALFORMED_EVIDENCE", str(path))
    return obj


def subject(project, top):
    if not isinstance(top, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", top):
        raise Refusal("INVALID_DESIGN", "an explicit top module is required")
    return {"project": project_subject(project), "top": top}


def inputs(project, top):
    """Current design inputs only; outputs/audit files never enter this set."""
    subject(project, top)
    rels = {"phase1/analog/analog_block_list.json",
            "phase3/mixed_signal/top_merged.gds",
            f"phase3/stage3/pnr/{top}_pnr.v", "phase3/stage3/pnr/routed.def",
            f"phase2/stage2/constraints/{top}.sdc"}
    l22, _ = load_l_doc(project, "L22")
    if l22:
        rels.add(str(l22.resolve().relative_to(project.resolve())))
    for pattern in ("phase3/stage3/pnr/**/*.spef", "input/pdk/liberty/**/*.lib",
                    "phase3/analog/**/*.lib", "phase3/analog/**/*.v",
                    "phase3/analog/**/*.sp", "phase3/analog/**/*.gds",
                    "phase3/analog/**/a7_post_layout.json",
                    "phase3/analog/**/layout_provenance.json",
                    "phase3/analog/**/pre_vs_post.json",
                    "phase3/librelane/analog/**/a7_resim/*.sp"):
        rels.update(str(p.relative_to(project)) for p in project.glob(pattern) if p.is_file())
    if (project / "input/mixed_signal/native.json").is_file():
        from _mixed_signal_native import input_paths
        rels.update(input_paths(project, top))
    bound = {}
    for rel in sorted(rels):
        path = project / rel
        if not path.resolve().is_relative_to(project.resolve()):
            raise Refusal("FOREIGN_INPUT", rel)
        bound[rel] = digest(path) if path.is_file() else None
    # Missing L22 must also be distinguishable from a newly supplied plan.
    return bound


def plan(project):
    _, doc = load_l_doc(project, "L22")
    value = l_doc_fields(doc).get("verification_plan", {}) if doc else {}
    rows = value.get("cosim_scenarios", []) if isinstance(value, dict) else []
    return rows if isinstance(rows, list) else []


def produce(project, top, container="host"):
    if (project / "input/mixed_signal/native.json").is_file():
        import _mixed_signal_native as native
        return native.produce(project, top, container)
    who = subject(project, top)
    for rel in (*OUTPUTS.values(), RECEIPT):
        if not (project / rel).resolve().is_relative_to(project.resolve()):
            raise Refusal("FOREIGN_OUTPUT", rel)
    before = inputs(project, top)
    rows = plan(project)
    missing = [rel for rel, sha in before.items() if sha is None]
    common = {"producer": PROGRAM, "schema": SCHEMA, **who,
              "verdict": "NOT_MEASURED", "execution": [], "tool_versions": {},
              "missing_inputs": missing}
    cosim = {**common, "all_scenarios_passed": False,
             "declared_scenarios": rows, "scenarios": [],
             "blockers": [
                 "M3_CURRENT_WRAPPER_COSIM_UNAVAILABLE: A9 composes A3 decks and an observer; "
                 "no qualified coupling of current A7 extraction to the current digital wrapper",
                 *([] if rows else ["M3_SCENARIO_PLAN_ABSENT: no current L22 scenarios"])]}
    si = {**common, "all_interfaces_clean": False, "interfaces": [],
          "coverage": {k: "NOT_MEASURED" for k in ("timing", "noise", "crosstalk")},
          "blockers": [
              "M3_NATIVE_INTERFACE_SI_UNAVAILABLE: OpenSTA/SPEF advisory screening has "
              "no qualified hardmacro receiver/noise model coverage",
              *([] if any(r.endswith(".spef") for r in before) else ["M3_POST_ROUTE_SPEF_ABSENT"]),
              *([] if any(r.startswith("phase3/analog/") and r.endswith(".lib") for r in before)
                else ["M3_HARDMACRO_LIBERTY_ABSENT"])]}
    if inputs(project, top) != before:
        raise Refusal("STALE_INPUT", "inputs changed during production")
    # Withdraw old evidence, including A9's legacy aggregate, before publishing
    # the explicitly unmeasured replacement. Receipt appears last.
    for rel in (*OUTPUTS.values(), RECEIPT):
        (project / rel).unlink(missing_ok=True)
    for rel, data in ((COSIM, cosim), (SI, si)):
        write_json(project / rel, data)
    record = {"program": PROGRAM, "schema": SCHEMA, **who,
              "verdict": "NOT_MEASURED", "inputs": before,
              "outputs": {rel: digest(project / rel) for rel in OUTPUTS.values()},
              "execution": [], "tool_versions": {},
              "blockers": cosim["blockers"] + si["blockers"]}
    if inputs(project, top) != before:
        raise Refusal("STALE_INPUT", "inputs changed before receipt publication")
    write_json(project / RECEIPT, record)
    return record


def _check_si_bounds(criterion, value, label):
    import math
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Refusal("MISSING_MEASUREMENT", label)
    bounds = {key: criterion[key] for key in ("min", "max") if key in criterion}
    if not bounds or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                         for v in bounds.values()):
        raise Refusal("MISSING_LIMIT", label)
    if ("min" in bounds and value < bounds["min"]) or ("max" in bounds and value > bounds["max"]):
        raise Refusal("FAILED_MEASUREMENT", f"{label}={value} outside {bounds}")


def _verify_si(project, report):
    native = read(project / "input/mixed_signal/native.json")
    timing = (native.get("si") or {}).get("interfaces") or []
    measured_pins = {row.get("name"): row.get("metrics", {}) for row in report.get("interfaces", [])
                     if isinstance(row, dict)}
    if not timing:
        raise Refusal("SI_COVERAGE_NOT_MEASURED", "no declared timing criteria")
    for pin in timing:
        criteria = pin.get("criteria") or []
        if not criteria:
            raise Refusal("MISSING_LIMIT", f"timing {pin.get('pin')}")
        for criterion in criteria:
            metric = criterion.get("metric")
            measured = measured_pins.get(pin.get("pin"), {}).get(metric, {})
            _check_si_bounds(criterion, measured.get("measured") if isinstance(measured, dict) else None,
                             f"timing {pin.get('pin')}/{metric}")
    canonical = native.get("canonical") or {}
    scenarios = plan(project)
    observed = {row.get("id"): row for row in report.get("current_interfaces", []) if isinstance(row, dict)}
    if not scenarios or not observed:
        raise Refusal("SI_COVERAGE_NOT_MEASURED", "no measured current-interface scenarios")
    entries = canonical.get("interfaces")
    for scenario in scenarios:
        spec = canonical
        if entries is not None:
            if not isinstance(entries, list):
                raise Refusal("SI_COVERAGE_NOT_MEASURED", "unsupported interface declarations")
            spec = next((entry for entry in entries if isinstance(entry, dict)
                         and entry.get("id") == scenario.get("interface")), {})
        result = observed.get(scenario.get("id"), {})
        for kind in ("noise", "crosstalk"):
            criteria = (spec.get(kind) or {}).get("criteria") or []
            if not criteria:
                raise Refusal("SI_COVERAGE_NOT_MEASURED", f"{kind} criteria absent for {scenario.get('id')}")
            values = (result.get(kind) or {}).get("criteria") or []
            for criterion in criteria:
                metric = criterion.get("metric")
                found = next((row for row in values if isinstance(row, dict)
                              and row.get("metric") == metric and row.get("units") == criterion.get("units")), {})
                _check_si_bounds(criterion, found.get("measured"), f"{scenario.get('id')} {kind}/{metric}")


def verify(project, kind):
    """Read the native report and compare measured values to declared bounds."""
    import math
    data = read(project / OUTPUTS[kind])
    if data.get("verdict") == "FAIL":
        raise Refusal("FAILED_MEASUREMENT", f"{kind} native report failed")
    execution = data.get("execution") or []
    if any(item.get("exit_code") not in (None, 0) for item in execution if isinstance(item, dict)):
        raise Refusal("NATIVE_EXECUTION_FAILED", f"{kind} native execution failed")
    if not any(item.get("stage") == "measurement" and item.get("exit_code") == 0
               for item in execution if isinstance(item, dict)):
        raise Refusal("MISSING_EXECUTION", f"{kind} has no completed native measurement")
    if kind == "cosim":
        scenarios = data.get("scenarios") or []
        declarations = plan(project)
        if not declarations or not scenarios:
            raise Refusal("EMPTY_SCENARIOS", "no declared and measured scenarios")
        results = {row.get("id"): row for row in scenarios if isinstance(row, dict)}
        for declaration in declarations:
            row = results.get(declaration.get("id"), {})
            if row.get("status") == "FAIL":
                raise Refusal("FAILED_MEASUREMENT", f"scenario {declaration.get('id')} failed")
            if row.get("status") != "PASS":
                raise Refusal("EMPTY_SCENARIOS", f"scenario {declaration.get('id')} not measured")
            metrics = row.get("metrics") or {}
            criteria = declaration.get("criteria") or []
            if not criteria:
                raise Refusal("MISSING_LIMIT", "scenario has no declared limits")
            for criterion in criteria:
                name = criterion.get("native_metric")
                value = metrics.get(name)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise Refusal("MISSING_MEASUREMENT", f"scenario {declaration.get('id')}: {name}")
                bounds = {key: criterion[key] for key in ("min", "max") if key in criterion}
                if not bounds or any(isinstance(bound, bool) or not isinstance(bound, (int, float))
                                     or not math.isfinite(bound) for bound in bounds.values()):
                    raise Refusal("MISSING_LIMIT", f"scenario {declaration.get('id')}: {name}")
                if ("min" in bounds and value < bounds["min"]) or ("max" in bounds and value > bounds["max"]):
                    raise Refusal("FAILED_MEASUREMENT", f"scenario {declaration.get('id')}: {name}={value} outside {bounds}")
    else:
        coverage = data.get("coverage") or {}
        if data.get("verdict") != "PASS" or any(coverage.get(key) != "MEASURED" for key in ("timing", "noise", "crosstalk")):
            raise Refusal("SI_COVERAGE_NOT_MEASURED", "; ".join(data.get("blockers", [])) or "timing/noise/crosstalk coverage incomplete")
        _verify_si(project, data)
    return data


def audit(project, kind):
    report = {"program": PROGRAM, "verdict": "NOT_MEASURED", "kind": kind,
              "passed": False, "ready": False, "findings": []}
    try:
        data = verify(project, kind)
        report.update(verdict="PASS", passed=True, ready=True,
                      scope=data.get("scope"), full_design_verified=False)
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        rule = getattr(exc, "rule", "INVALID_EVIDENCE")
        if rule in ("NATIVE_EXECUTION_FAILED", "FAILED_MEASUREMENT"):
            report["verdict"] = "FAIL"
        report["findings"].append({"rule": rule, "message": str(exc)})
    return report


def guard_audit_path(project, output, protected):
    if output:
        path = Path(output).resolve()
        if path.is_relative_to((project / DIR / "native").resolve()):
            raise Refusal("AUDIT_OVERWRITES_EVIDENCE", "audit cannot create/overwrite native execution artifacts")
        if path.is_relative_to(project.resolve()):
            rel = path.relative_to(project.resolve())
            if rel.parts and rel.parts[0] in ("phase1", "phase2", "phase3", "input", "input_doc"):
                raise Refusal("AUDIT_OVERWRITES_EVIDENCE", "audit cannot write design/native input trees")
        if path in {(project / rel).resolve() for rel in protected}:
            raise Refusal("AUDIT_OVERWRITES_EVIDENCE", "audit cannot create or replace evidence")


def audit_output(project, output, report, protected):
    guard_audit_path(project, output, protected)
    if output:
        path = Path(output).resolve()
        write_json(path, report)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--top", required=False)
    ap.add_argument("--container", default="host", help="native host or approved Docker run context")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--kind", choices=OUTPUTS, default="cosim")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    project = args.project.resolve()
    try:
        protected = (*OUTPUTS.values(), RECEIPT)
        guard_audit_path(project, args.json, protected)
        report = audit(project, args.kind) if args.check_only else produce(project, args.top, args.container)
        rc = (0 if report.get("passed") else 1) if args.check_only else (
            1 if report.get("verdict") == "FAIL" else 0 if report.get("verdict") == "PASS" else 2)
        audit_output(project, args.json, report, protected)
    except (Refusal, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[{PROGRAM}] {getattr(exc, 'rule', 'INVALID_EVIDENCE')}: {exc}", file=sys.stderr)
        if not args.check_only and getattr(exc, "rule", "") == "CURRENT_INTERFACE_NOT_SUPPORTED":
            report = {"program": PROGRAM, "verdict": "NOT_MEASURED", "scope": "current_post_layout_interface",
                      "full_design_verified": False, "rule": exc.rule, "reason": str(exc)}
            try:
                audit_output(project, args.json, report, (*OUTPUTS.values(), RECEIPT))
            except (Refusal, OSError, ValueError) as output_exc:
                print(f"[{PROGRAM}] {getattr(output_exc, 'rule', 'INVALID_EVIDENCE')}: {output_exc}", file=sys.stderr)
                return 1
            return 2
        return 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
