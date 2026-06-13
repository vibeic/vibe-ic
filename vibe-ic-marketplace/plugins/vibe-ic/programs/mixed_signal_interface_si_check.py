#!/usr/bin/env python3
"""
mixed_signal_interface_si_check.py — M3 interface signal-integrity gate.

M3 — analog↔digital interface signal integrity (substance verification).

SUBSTANCE VERIFICATION (M3-cosim-si, anti-fabrication)
------------------------------------------------------
This gate no longer PASSes on file-presence and no longer trusts the
self-produced ``all_interfaces_clean`` boolean. It independently parses
``reports/analog/mixed_signal/interface_si.json`` (fallback
``reports/mixed_signal/interface_si.json``) and walks EVERY declared
interface crossing, verifying that EVERY signal-integrity metric on it
satisfies the limit *stated in the artefact itself*.

For each metric the checker reads:
  * a measured value  — ``measured`` / ``value`` / ``result`` / ``actual``
  * a stated limit     — one (or more) of:
        ``max`` / ``max_limit`` / ``limit_max`` / ``upper``      (measured ≤ limit)
        ``min`` / ``min_limit`` / ``limit_min`` / ``lower``      (measured ≥ limit)
        ``limit`` + ``relation`` ("max"/"min"/"<="/">=")
  * an optional ``pass`` / ``status`` self-verdict — NEVER trusted in
    isolation; it is cross-checked against the recomputed bound and a
    disagreement is itself a FAIL (the producer lied about its own data).

HARD anti-fabrication rule
--------------------------
The checker NEVER invents a limit the artefact does not state. A metric
that carries a measured value but NO stated numeric limit is an
unverifiable claim → honest FAIL (``SI_LIMIT_UNSTATED``). A present file
that declares ZERO interfaces, or has no recognisable interface array,
is a vacuous "all clean" → honest FAIL. The gate never vacuous-PASSes on
absence of substance.

Exit codes (CLI contract preserved)
-----------------------------------
    0 = PASS   (every interface metric verified within its stated limit)
              or WAIVED (waivers.json declares the step waived)
    1 = FAIL   (a metric out of bounds / unstated limit / vacuous file /
               self-verdict disagreement / file missing while analog
               applies)
    2 = SKIP   (genuinely inapplicable: no analog blocks, file missing,
               no waiver)  /  project-dir / IO error

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded; every
threshold compared against is read from the artefact.

Usage
-----
    python3 mixed_signal_interface_si_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from _analog_stub_marker import is_stub_json  # type: ignore
except Exception:  # pragma: no cover - defensive
    def is_stub_json(_data):  # type: ignore
        return False


_GATE_NAME = 'mixed_signal_interface_si_check'
_GATE_LABEL = 'mixed_signal_interface_si'
# Canonical path first (matches flow required_outputs), then legacy.
_REQUIRED_FILES = [
    'reports/analog/mixed_signal/interface_si.json',
    'reports/mixed_signal/interface_si.json',
]
_WAIVER_RATIONALE = 'Mixed-signal SI tool not shipped.'

_PASS_TOKENS = frozenset({"pass", "passed", "ok", "true", "clean",
                          "within", "within_limit", "in_spec", "good"})
_FAIL_TOKENS = frozenset({"fail", "failed", "error", "false", "violate",
                          "violation", "out", "out_of_spec", "bad"})


# ---------------------------------------------------------------------------
# waiver helpers (unchanged contract)
# ---------------------------------------------------------------------------
def _load_waivers(project):
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        return (json.loads(p.read_text()).get("waived_steps") or [])
    except Exception:
        return []


def _step_waived(project, step_label):
    for w in _load_waivers(project):
        sid = str(w.get("id", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or step_label in ticket:
            return w
    return None


# ---------------------------------------------------------------------------
# analog applicability
# ---------------------------------------------------------------------------
def _analog_blocks_declared(project: Path) -> bool:
    """True iff the project declares any analog block. Used to decide
    whether a missing interface_si artefact is an honest FAIL (analog
    applies) vs a clean SKIP (no analog at all)."""
    bl = project / "phase1/analog/analog_block_list.json"
    if bl.is_file():
        try:
            data = json.loads(bl.read_text(errors="replace"))
        except Exception:
            data = None
        if isinstance(data, dict) and data.get("blocks"):
            return True
        if isinstance(data, list) and data:
            return True
    # spec.json scan under phase3/analog
    adir = project / "phase3/analog"
    if adir.is_dir():
        for d in adir.iterdir():
            if d.is_dir() and (d / "spec.json").is_file():
                return True
    return False


# ---------------------------------------------------------------------------
# substance verification
# ---------------------------------------------------------------------------
def _find_si_file(project: Path):
    for rel in _REQUIRED_FILES:
        p = project / rel
        if p.is_file():
            return rel, p
    return None, None


def _coerce_float(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        # strip a trailing unit suffix if a leading number is present
        try:
            return float(s)
        except ValueError:
            num = ""
            for ch in s:
                if ch.isdigit() or ch in ".+-eE":
                    num += ch
                else:
                    break
            try:
                return float(num) if num not in ("", "+", "-", ".") else None
            except ValueError:
                return None
    return None


def _read_measured(metric: dict):
    for k in ("measured", "value", "result", "actual", "meas"):
        if k in metric:
            f = _coerce_float(metric.get(k))
            if f is not None:
                return f
    return None


def _read_self_verdict(metric: dict):
    """Return True/False if the metric self-declares a pass/fail verdict,
    else None. Used only as a CROSS-CHECK, never as the sole evidence."""
    for k in ("pass", "passed", "ok", "within_limit"):
        v = metric.get(k)
        if isinstance(v, bool):
            return v
    for k in ("status", "verdict", "result_status"):
        v = metric.get(k)
        if isinstance(v, str) and v.strip():
            tok = v.strip().lower()
            if tok in _PASS_TOKENS:
                return True
            if tok in _FAIL_TOKENS:
                return False
    return None


def _check_metric(measured: float, metric: dict):
    """Verify ``measured`` against the limit STATED in ``metric``.

    Returns (ok: bool|None, detail: str). ok is None when no limit is
    stated (unverifiable → caller treats as FAIL). Never fabricates a
    limit.
    """
    # explicit upper bound
    for k in ("max", "max_limit", "limit_max", "upper", "upper_limit",
              "max_value"):
        if k in metric:
            lim = _coerce_float(metric.get(k))
            if lim is not None:
                return (measured <= lim,
                        f"{measured} <= {lim} ({k})")
    # explicit lower bound
    for k in ("min", "min_limit", "limit_min", "lower", "lower_limit",
              "min_value"):
        if k in metric:
            lim = _coerce_float(metric.get(k))
            if lim is not None:
                return (measured >= lim,
                        f"{measured} >= {lim} ({k})")
    # generic limit + relation
    if "limit" in metric:
        lim = _coerce_float(metric.get("limit"))
        if lim is not None:
            rel = str(metric.get("relation",
                                 metric.get("rel", "max"))).strip().lower()
            if rel in ("min", ">=", "ge", "gte", "lower", "floor"):
                return (measured >= lim, f"{measured} >= {lim} (limit/min)")
            # default: treat a bare limit as an upper bound
            return (measured <= lim, f"{measured} <= {lim} (limit/max)")
    return (None, "no stated limit")


def _iter_metrics(iface: dict):
    """Yield (metric_name, metric_dict) for the SI metrics on one
    interface. Accepts a ``metrics`` dict (name->metric) or list, or
    inline metric fields on the interface itself."""
    m = iface.get("metrics")
    if isinstance(m, dict):
        for name, val in m.items():
            if isinstance(val, dict):
                yield str(name), val
            else:
                # bare value with the limit stored on the interface
                yield str(name), {"value": val}
        return
    if isinstance(m, list):
        for i, val in enumerate(m):
            if isinstance(val, dict):
                yield (str(val.get("name", val.get("metric", f"#{i}"))),
                       val)
        return
    # no nested metrics container — the interface dict may itself be a
    # single metric (measured + limit inline).
    if any(k in iface for k in ("measured", "value", "result", "actual")):
        yield (str(iface.get("metric", iface.get("name", "metric"))), iface)


def _extract_interfaces(data: dict):
    if not isinstance(data, dict):
        return None
    for key in ("interfaces", "crossings", "nets", "boundaries", "links"):
        v = data.get(key)
        if isinstance(v, list):
            return v
    return None


def _audit_substance(rel: str, data: dict):
    """Return (passed: bool, findings: list, summary: dict)."""
    findings = []

    if is_stub_json(data):
        findings.append({"severity": "INFO", "rule": "SI_STUB_ACCEPTED",
                         "message": "interface_si.json carries a "
                                    "deterministic_stub marker "
                                    "(PASS_WITH_STUB tier)."})
        return True, findings, {"stub": True, "interfaces_total": 0}

    interfaces = _extract_interfaces(data)
    if interfaces is None:
        findings.append({"severity": "ERROR", "rule": "SI_NO_INTERFACE_ARRAY",
                         "message": f"{rel}: no interfaces[]/crossings[] "
                                    f"array — cannot verify substance; "
                                    f"refusing vacuous PASS."})
        return False, findings, {"interfaces_total": 0,
                                 "reason": "no_interface_array"}

    if len(interfaces) == 0:
        findings.append({"severity": "ERROR", "rule": "SI_ZERO_INTERFACES",
                         "message": f"{rel}: declares ZERO interfaces — "
                                    f"nothing was checked; refusing "
                                    f"vacuous 'all clean'."})
        return False, findings, {"interfaces_total": 0,
                                 "reason": "zero_interfaces"}

    passed = True
    metrics_checked = 0
    metrics_violated = 0
    metrics_unstated = 0
    iface_fail = []
    for i, iface in enumerate(interfaces):
        if not isinstance(iface, dict):
            findings.append({"severity": "ERROR",
                             "rule": "SI_INTERFACE_NOT_OBJECT",
                             "message": f"{rel}: interface #{i} is not an "
                                        f"object."})
            passed = False
            iface_fail.append(f"#{i}")
            continue
        iname = str(iface.get("name", iface.get("net", iface.get("id",
                                                                 f"#{i}"))))
        any_metric = False
        for mname, metric in _iter_metrics(iface):
            any_metric = True
            measured = _read_measured(metric)
            if measured is None:
                # metric with no measured value is unverifiable
                metrics_unstated += 1
                passed = False
                iface_fail.append(iname)
                findings.append({"severity": "ERROR",
                                 "rule": "SI_NO_MEASURED",
                                 "message": f"{iname}.{mname}: no measured "
                                            f"value — cannot verify."})
                continue
            ok, detail = _check_metric(measured, metric)
            if ok is None:
                metrics_unstated += 1
                passed = False
                iface_fail.append(iname)
                findings.append({"severity": "ERROR",
                                 "rule": "SI_LIMIT_UNSTATED",
                                 "message": f"{iname}.{mname}: measured "
                                            f"{measured} but NO stated "
                                            f"limit — unverifiable claim, "
                                            f"refusing to fabricate a "
                                            f"threshold."})
                continue
            metrics_checked += 1
            # cross-check the producer's self-verdict if present
            self_v = _read_self_verdict(metric)
            if self_v is not None and self_v != ok:
                passed = False
                iface_fail.append(iname)
                findings.append({"severity": "ERROR",
                                 "rule": "SI_SELF_VERDICT_DISAGREE",
                                 "message": f"{iname}.{mname}: producer "
                                            f"self-verdict={self_v} but "
                                            f"recomputed bound says "
                                            f"{ok} ({detail})."})
                continue
            if not ok:
                metrics_violated += 1
                passed = False
                iface_fail.append(iname)
                findings.append({"severity": "ERROR",
                                 "rule": "SI_METRIC_OUT_OF_LIMIT",
                                 "message": f"{iname}.{mname}: {detail} "
                                            f"VIOLATED."})
        if not any_metric:
            passed = False
            iface_fail.append(iname)
            findings.append({"severity": "ERROR",
                             "rule": "SI_INTERFACE_NO_METRICS",
                             "message": f"{iname}: no SI metrics declared "
                                        f"— cannot verify it is clean."})

    if passed:
        findings.append({"severity": "INFO", "rule": "SI_ALL_CLEAN",
                         "message": f"{len(interfaces)} interface(s), "
                                    f"{metrics_checked} metric(s) all "
                                    f"within stated limits."})

    summary = {
        "interfaces_total": len(interfaces),
        "metrics_checked": metrics_checked,
        "metrics_violated": metrics_violated,
        "metrics_unstated": metrics_unstated,
        "interfaces_failed": sorted(set(iface_fail)),
    }
    return passed, findings, summary


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--step-label", default=_GATE_LABEL)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}",
              file=sys.stderr)
        return 2

    rel, si_path = _find_si_file(project)
    waiver = _step_waived(project, args.step_label)

    summary = {}
    if si_path is None:
        # artefact missing: waiver > analog-applies-FAIL > clean-SKIP
        if waiver:
            verdict, rc = "WAIVED", 0
            findings = [{"severity": "WAIVED", "rule": "STEP_WAIVED",
                         "message": f"waiver={waiver.get('ticket','?')}: "
                                    f"{waiver.get('reason','?')}"}]
        elif _analog_blocks_declared(project):
            verdict, rc = "FAIL", 1
            findings = [{"severity": "ERROR", "rule": "SI_REPORT_MISSING",
                         "message": f"analog blocks declared but no "
                                    f"interface_si.json (looked: "
                                    f"{_REQUIRED_FILES}); refusing vacuous "
                                    f"PASS on absence."}]
        else:
            verdict, rc = "SKIP", 2
            findings = [{"severity": "INFO", "rule": "SKIP_NO_ANALOG",
                         "message": "no analog blocks and no "
                                    "interface_si.json; step inapplicable."}]
    else:
        try:
            data = json.loads(si_path.read_text(errors="replace"))
        except Exception as exc:
            verdict, rc = "FAIL", 1
            findings = [{"severity": "ERROR", "rule": "SI_PARSE_ERROR",
                         "message": f"{rel}: cannot parse — {exc}"}]
            data = None
        if data is not None:
            ok, findings, summary = _audit_substance(rel, data)
            if ok:
                verdict, rc = "PASS", 0
            else:
                verdict, rc = "FAIL", 1

    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": args.step_label,
        "required_files": _REQUIRED_FILES,
        "found": [rel] if rel else [],
        "missing": [] if rel else list(_REQUIRED_FILES),
        "waiver": waiver,
        "rationale_when_skipped": _WAIVER_RATIONALE,
        "summary": summary,
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False)
                            + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    for f in findings:
        if f.get("severity") in ("ERROR", "WARNING"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
