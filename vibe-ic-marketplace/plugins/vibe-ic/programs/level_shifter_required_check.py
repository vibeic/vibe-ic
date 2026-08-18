#!/usr/bin/env python3
"""
level_shifter_required_check.py — M2 gate (substance-verifying).

M2 — level-shifter insertion audit
===================================

A level shifter is REQUIRED on every net that crosses from a power domain at
one rail voltage into a domain at a different rail voltage.  This checker
INDEPENDENTLY derives the set of voltage-mismatched crossings from
``power_domain.json#crossings`` and asserts that for *each* one an inserted
level-shifter entry exists in ``level_shifter.json``.  It does NOT trust the
``all_required_inserted`` boolean written into that file — it recomputes it
and rejects a self-asserted PASS that contradicts the substance.

WHERE power_domain.json / level_shifter.json COME FROM (M2-d4, corrected
2026-07): NOT from this plugin.  Both are INPUTS; no program shipped here
writes either.  They record the power intent and the cells the UPF-driven
implementation flow actually inserted, so that flow (or a hand-authored file)
supplies them.  This docstring used to say "the producer", implying a shipped
producing step — there is none.  Absent input is the honest rc=2 SKIP below.
The sibling gate ``power_domain_signal_crossing_check`` derives the crossings
from the UPF itself and needs no sidecar — but on the flow-audit path M2's
all-absent ``required_outputs`` returns MISSING before any gate runs, so it is
reached only by invoking it directly.

The required set is the SOURCE OF TRUTH: a level_shifter.json that lists no
cells while power_domain.json enumerates a voltage-mismatched crossing is the
exact silicon hazard this gate guards (a signal driven at one VDD into a gate
powered at another VDD) and FAILs.

Behaviour
---------
* SKIP (rc=2) — ``power_domain.json`` absent AND step not waived (genuinely
  inapplicable — e.g. no mixed-signal blocks).  Never a vacuous PASS.
* WAIVED (rc=0) — ``waivers.json`` declares step waived (evidence + ticket).
* PASS (rc=0) — every voltage-mismatched crossing has a matching inserted
  level shifter (including the legitimate zero-required case where the design
  has crossings but none are voltage-mismatched).
* FAIL (rc=1) — power_domain.json malformed, OR one or more required level
  shifters is missing, OR level_shifter.json itself is malformed.

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded.

Usage
-----
    python3 level_shifter_required_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


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


_GATE_NAME = "level_shifter_required_check"
_GATE_LABEL = "level_shifter"
_PD_REL = "reports/analog/mixed_signal/power_domain.json"
_LS_REL = "reports/analog/mixed_signal/level_shifter.json"
_PD_REL_LEGACY = "reports/mixed_signal/power_domain.json"
_LS_REL_LEGACY = "reports/mixed_signal/level_shifter.json"
_WAIVER_RATIONALE = "Level shifter insertion auditor not shipped."


def _first_existing(project, *rels):
    for r in rels:
        p = project / r
        if p.is_file():
            return p
    return None


def _load_json(path):
    try:
        return json.loads(path.read_text()), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _net_keys(entry):
    keys = set()
    if isinstance(entry, str):
        if entry.strip():
            keys.add(entry.strip().lower())
        return keys
    if not isinstance(entry, dict):
        return keys
    for k in ("net", "signal", "name", "on_net", "crossing", "crossing_id",
              "from_net", "wire"):
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            keys.add(v.strip().lower())
    return keys


def _collect_inserted_nets(obj):
    nets = set()
    if not isinstance(obj, dict):
        return nets
    for fld in ("level_shifters", "cells", "inserted", "entries",
                "protections", "list", "items"):
        seq = obj.get(fld)
        if isinstance(seq, list):
            for e in seq:
                nets |= _net_keys(e)
    return nets


def _crossing_net_token(c):
    if isinstance(c, str):
        return c.strip().lower()
    if isinstance(c, dict):
        for k in ("net", "signal", "name", "crossing_id", "id"):
            v = c.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip().lower()
    return ""


def _needs_level_shifter(c):
    if not isinstance(c, dict):
        return False
    vf = c.get("vdd_from", c.get("v_from", c.get("vdd_src")))
    vt = c.get("vdd_to", c.get("v_to", c.get("vdd_sink")))
    if vf is not None and vt is not None:
        try:
            if abs(float(vf) - float(vt)) > 1e-9:
                return True
        except (TypeError, ValueError):
            if str(vf) != str(vt):
                return True
    return c.get("level_shifter_required") is True


def _audit(pd_obj, ls_obj):
    findings = []
    crossings = pd_obj.get("crossings") if isinstance(pd_obj, dict) else None
    if not isinstance(crossings, list):
        findings.append({
            "severity": "ERROR", "rule": "NO_CROSSING_LIST",
            "message": "power_domain.json has no 'crossings' list — cannot "
                       "derive the required level-shifter set."})
        return findings, 0, 1

    inserted = _collect_inserted_nets(ls_obj) if ls_obj is not None else set()
    n_required = 0
    n_missing = 0
    for idx, c in enumerate(crossings):
        if not _needs_level_shifter(c):
            continue
        n_required += 1
        token = _crossing_net_token(c) or f"<crossing#{idx}>"
        if token not in inserted:
            n_missing += 1
            findings.append({
                "severity": "ERROR", "rule": "MISSING_LEVEL_SHIFTER",
                "message": (f"crossing '{token}' is voltage-mismatched and "
                            f"requires a level shifter, but no inserted "
                            f"level-shifter cell references it.")})

    claim = ls_obj.get("all_required_inserted") if isinstance(ls_obj, dict) else None
    if claim is True and n_missing > 0:
        findings.append({
            "severity": "ERROR", "rule": "CONTRADICTS_PRODUCER",
            "message": (f"level_shifter.json claims all_required_inserted=true "
                        f"but {n_missing} required shifter(s) are missing — "
                        f"self-asserted PASS rejected.")})
    return findings, n_required, n_missing


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

    pd_path = _first_existing(project, _PD_REL, _PD_REL_LEGACY)
    waiver = _step_waived(project, args.step_label)

    findings = []
    if pd_path is None and not waiver:
        verdict, rc = "SKIP", 2
        findings = [{"severity": "INFO", "rule": "REQUIRED_FILES_MISSING",
                     "message": f"missing: {_PD_REL} (no power-domain crossing "
                                f"list to derive required shifters from)"}]
    elif pd_path is None and waiver:
        verdict, rc = "WAIVED", 0
        findings = [{"severity": "WAIVED", "rule": "STEP_WAIVED",
                     "message": f"waiver={waiver.get('ticket','?')}: "
                                f"{waiver.get('reason','?')}"}]
    else:
        pd_obj, err = _load_json(pd_path)
        if err is not None:
            verdict, rc = "FAIL", 1
            findings = [{"severity": "ERROR", "rule": "MALFORMED_ARTEFACT",
                         "message": f"power_domain.json unparseable: {err}"}]
        else:
            ls_path = _first_existing(project, _LS_REL, _LS_REL_LEGACY)
            ls_obj = None
            if ls_path is not None:
                ls_obj, ls_err = _load_json(ls_path)
                if ls_err is not None:
                    findings.append({
                        "severity": "ERROR", "rule": "MALFORMED_ARTEFACT",
                        "message": f"level_shifter.json unparseable: {ls_err}"})
                    verdict, rc = "FAIL", 1
                    ls_obj = "__ERR__"
            if ls_obj == "__ERR__":
                pass  # verdict already FAIL
            else:
                a_findings, n_req, n_missing = _audit(pd_obj, ls_obj)
                findings.extend(a_findings)
                # A required level shifter with NO level_shifter.json at all
                # is a missing artefact -> honest FAIL (already counted as
                # missing in _audit because inserted set is empty).
                if n_missing > 0:
                    verdict, rc = "FAIL", 1
                else:
                    verdict, rc = "PASS", 0
                    findings.append({
                        "severity": "INFO", "rule": "ALL_REQUIRED_INSERTED",
                        "message": (f"{n_req} voltage-mismatched crossing(s) "
                                    f"require a level shifter; all are present"
                                    f" (or design has none).")})

    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": args.step_label,
        "required_files": [_PD_REL, _LS_REL],
        "pd_artefact": str(pd_path.relative_to(project)) if pd_path else None,
        "waiver": waiver,
        "rationale_when_skipped": _WAIVER_RATIONALE,
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    for f in findings:
        if f.get("severity") in ("ERROR", "WAIVED"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
