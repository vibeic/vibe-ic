#!/usr/bin/env python3
"""
mixed_signal_signoff_check.py — gate M4 (hardened, anti-fabrication).

M4 — Mixed-signal sign-off (final verdict roll-up)
==================================================

M4's input, ``reports/analog/mixed_signal/signoff.json``, carries a
self-asserted ``ready_for_tapeout`` boolean.  Trusting that boolean alone is an
anti-fabrication hole: whoever wrote it would be signing off on their own work.

That file is an INPUT: no program shipped in this plugin writes it (M4-d4,
corrected 2026-07 — this docstring used to open with "The producing step
writes …", which sent the reader looking for a step that does not exist). It
is authored by the mixed-signal sign-off owner, and its absence on an
applicable project is a FAIL below, never a vacuous PASS.

This checker therefore performs REAL DETERMINISTIC SUBSTANCE verification:

  1. It confirms ``ready_for_tapeout`` is actually claimed ``true`` in
     signoff.json (the producer's claim — necessary but NOT sufficient).
  2. It then INDEPENDENTLY re-opens every upstream M1–M3 mixed-signal report
     and re-checks the substantive PASS field each one carries (the same
     fields the M1/M2/M3 gates assert):

        M1  reports/analog/mixed_signal/merge.json        verdict ∈ {PASS, WAIVED}
        M2  reports/analog/mixed_signal/power_domain.json all_crossings_protected == true
        M2  reports/analog/mixed_signal/level_shifter.json all_required_inserted == true
        M2  reports/analog/mixed_signal/isolation.json    all_required_inserted == true
        M3  phase3/mixed_signal/cosim/mixed_signal_results.json all_scenarios_passed == true
        M3  reports/analog/mixed_signal/interface_si.json all_interfaces_clean == true

     (Each report is also looked up at the bare ``reports/mixed_signal/…``
     alias path some runners emit — chip-AGNOSTIC, no IC/vendor data.)

  3. If ``ready_for_tapeout`` is ``true`` but ANY upstream report is missing,
     malformed, or not-PASS → honest FAIL with an ``OVERCLAIM_*`` finding.
     This is the silicon hole the gate guards: M4 cannot bless a tapeout when
     a power-domain crossing is unprotected, a required level-shifter/isolation
     cell is absent, AMS co-sim failed, or the A+D merge did not pass.

Verdicts
--------
* SKIP    (rc=2) — no analog blocks declared anywhere (genuinely digital-only
                   project) AND no signoff.json → M4 inapplicable.
* WAIVED  (rc=0) — ``waivers.json`` declares the step waived (evidence+ticket).
* PASS    (rc=0) — ready_for_tapeout true AND every upstream M1–M3 report
                   independently re-checks PASS/WAIVED.
* FAIL    (rc=1) — required signoff.json missing (applicable step), or
                   ready_for_tapeout not true, or any upstream substance
                   does not roll up.

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded.

Usage
-----
    python3 mixed_signal_signoff_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_GATE_NAME = "mixed_signal_signoff_check"
_GATE_LABEL = "mixed_signal_signoff"
_SIGNOFF_REL = "reports/analog/mixed_signal/signoff.json"
_WAIVER_RATIONALE = "Mixed-signal sign-off aggregator not shipped."

# Where an analog-block declaration may live.  Presence of a NON-empty
# `blocks` list means the mixed-signal track is applicable.
_BLOCK_LIST_CANDIDATES = (
    "phase1/analog/analog_block_list.json",
    "phase3/analog/analog_block_list.json",
    "analog/analog_block_list.json",
    "analog_blocks/analog_block_list.json",
)

# Upstream M1–M3 reports M4 rolls up.  Each entry:
#   key            : short id used in findings
#   stage          : M1 / M2 / M3 (for human readability)
#   paths          : ordered candidate relative paths (first found wins)
#   field          : substantive PASS field name (None ⇒ use verdict shape)
#   verdict_based  : True ⇒ accept verdict ∈ {PASS, WAIVED, PASS_WITH_*}
_UPSTREAM = [
    {
        "key": "merge",
        "stage": "M1",
        "paths": ["reports/analog/mixed_signal/merge.json",
                  "reports/mixed_signal/merge.json"],
        "field": None,
        "verdict_based": True,
    },
    {
        "key": "power_domain",
        "stage": "M2",
        "paths": ["reports/analog/mixed_signal/power_domain.json",
                  "reports/mixed_signal/power_domain.json"],
        "field": "all_crossings_protected",
        "verdict_based": False,
    },
    {
        "key": "level_shifter",
        "stage": "M2",
        "paths": ["reports/analog/mixed_signal/level_shifter.json",
                  "reports/mixed_signal/level_shifter.json"],
        "field": "all_required_inserted",
        "verdict_based": False,
    },
    {
        "key": "isolation",
        "stage": "M2",
        "paths": ["reports/analog/mixed_signal/isolation.json",
                  "reports/mixed_signal/isolation.json"],
        "field": "all_required_inserted",
        "verdict_based": False,
    },
    {
        "key": "cosim",
        "stage": "M3",
        "paths": ["phase3/mixed_signal/cosim/mixed_signal_results.json",
                  "reports/mixed_signal/cosim/mixed_signal_results.json"],
        "field": "all_scenarios_passed",
        "verdict_based": False,
    },
    {
        "key": "interface_si",
        "stage": "M3",
        "paths": ["reports/analog/mixed_signal/interface_si.json",
                  "reports/mixed_signal/interface_si.json"],
        "field": "all_interfaces_clean",
        "verdict_based": False,
    },
]

_ACCEPT_VERDICTS = ("PASS", "WAIVED", "PASS_WITH_WAIVERS",
                    "PASS_WITH_STUB", "PASS_WITH_STUB_PARTIAL")


# ----------------------------------------------------------------------------
# waiver helpers (unchanged contract)
# ----------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------
# substance helpers
# ----------------------------------------------------------------------------
def _read_json(path: Path):
    """Return (data, error). data is a dict on success, else None."""
    try:
        data = json.loads(path.read_text())
    except Exception as exc:  # malformed JSON ⇒ honest failure, not a pass
        return None, f"unreadable JSON: {exc}"
    if not isinstance(data, dict):
        return None, "JSON root is not an object"
    return data, None


def _analog_applicable(project: Path):
    """Return (applicable: bool, evidence: str).

    Applicable ⇒ at least one analog_block_list.json declares a non-empty
    `blocks` list.  No such declaration ⇒ digital-only / M4 N/A.
    """
    for rel in _BLOCK_LIST_CANDIDATES:
        p = project / rel
        if not p.is_file():
            continue
        data, err = _read_json(p)
        if data is None:
            # A present-but-broken block list is suspicious — treat the
            # mixed-signal track as applicable so we don't vacuously SKIP.
            return True, f"{rel} present but {err}"
        blocks = data.get("blocks") or data.get("analog_blocks") or []
        if isinstance(blocks, list) and len(blocks) > 0:
            return True, f"{rel} declares {len(blocks)} analog block(s)"
    return False, "no analog_block_list.json with a non-empty blocks list"


def _resolve_upstream(project: Path, spec):
    """Return the first existing candidate path for an upstream report."""
    for rel in spec["paths"]:
        p = project / rel
        if p.is_file():
            return rel, p
    return None, None


def _check_upstream(project: Path, spec):
    """Independently re-check one upstream report's substance.

    Returns a per-report dict:
        {key, stage, path, status, detail}
    status ∈ {"PASS", "FAIL_MISSING", "FAIL_MALFORMED", "FAIL_SUBSTANCE"}
    """
    rel, p = _resolve_upstream(project, spec)
    base = {"key": spec["key"], "stage": spec["stage"]}
    if p is None:
        return {**base, "path": None, "status": "FAIL_MISSING",
                "detail": f"none of {spec['paths']} exist"}
    data, err = _read_json(p)
    if data is None:
        return {**base, "path": rel, "status": "FAIL_MALFORMED",
                "detail": err}

    if spec["verdict_based"]:
        verdict = str(data.get("verdict", "")).strip()
        if verdict in _ACCEPT_VERDICTS:
            return {**base, "path": rel, "status": "PASS",
                    "detail": f"verdict={verdict}"}
        return {**base, "path": rel, "status": "FAIL_SUBSTANCE",
                "detail": f"verdict={verdict or '<missing>'} "
                          f"(expected one of {list(_ACCEPT_VERDICTS)})"}

    field = spec["field"]
    if field not in data:
        return {**base, "path": rel, "status": "FAIL_SUBSTANCE",
                "detail": f"required field '{field}' absent"}
    val = data[field]
    if val is True:
        return {**base, "path": rel, "status": "PASS",
                "detail": f"{field}=true"}
    return {**base, "path": rel, "status": "FAIL_SUBSTANCE",
            "detail": f"{field}={val!r} (expected true)"}


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
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

    signoff_path = project / _SIGNOFF_REL
    waiver = _step_waived(project, args.step_label)
    applicable, applic_evidence = _analog_applicable(project)

    findings = []
    upstream_results = []
    ready_claimed = None  # tri-state: None=absent, True/False=claimed

    # ---- 1. explicit step waiver short-circuits (must carry a ticket) -----
    if waiver:
        verdict, rc = "WAIVED", 0
        findings.append({"severity": "WAIVED", "rule": "STEP_WAIVED",
                         "message": f"waiver={waiver.get('ticket', '?')}: "
                                    f"{waiver.get('reason', '?')}"})
    # ---- 2. signoff.json absent -------------------------------------------
    elif not signoff_path.is_file():
        if not applicable:
            # genuinely digital-only — M4 does not apply
            verdict, rc = "SKIP", 2
            findings.append({"severity": "INFO", "rule": "NOT_APPLICABLE",
                             "message": ("no analog blocks declared and no "
                                         "signoff.json — mixed-signal sign-off "
                                         "inapplicable")})
        else:
            # applicable step is missing its required artefact ⇒ honest FAIL
            verdict, rc = "FAIL", 1
            findings.append({"severity": "ERROR",
                             "rule": "REQUIRED_SIGNOFF_MISSING",
                             "message": (f"{_SIGNOFF_REL} missing although "
                                         f"mixed-signal track applies "
                                         f"({applic_evidence})")})
    # ---- 3. signoff.json present → substance roll-up ----------------------
    else:
        data, err = _read_json(signoff_path)
        if data is None:
            verdict, rc = "FAIL", 1
            findings.append({"severity": "ERROR", "rule": "SIGNOFF_MALFORMED",
                             "message": f"{_SIGNOFF_REL}: {err}"})
        else:
            ready_claimed = data.get("ready_for_tapeout", None)

            # Independently roll up every upstream M1–M3 report.
            upstream_results = [_check_upstream(project, s) for s in _UPSTREAM]
            failed = [r for r in upstream_results if r["status"] != "PASS"]
            for r in failed:
                findings.append({
                    "severity": "ERROR",
                    "rule": f"UPSTREAM_{r['status']}",
                    "message": (f"[{r['stage']}] {r['key']} "
                                f"({r['path'] or 'absent'}): {r['detail']}"),
                })

            if ready_claimed is not True:
                # producer did not even claim ready (or set it false) ⇒ FAIL
                verdict, rc = "FAIL", 1
                findings.append({
                    "severity": "ERROR", "rule": "NOT_READY_FOR_TAPEOUT",
                    "message": (f"ready_for_tapeout={ready_claimed!r} "
                                f"(expected true)")})
            elif failed:
                # The anti-fabrication catch: producer claimed ready=true but
                # the upstream substance does NOT roll up → over-claim.
                verdict, rc = "FAIL", 1
                findings.insert(0, {
                    "severity": "ERROR", "rule": "OVERCLAIM_UNJUSTIFIED_SIGNOFF",
                    "message": (f"ready_for_tapeout=true is NOT justified: "
                                f"{len(failed)} upstream M1–M3 report(s) "
                                f"do not roll up PASS")})
            else:
                verdict, rc = "PASS", 0
                findings.append({
                    "severity": "INFO", "rule": "SIGNOFF_JUSTIFIED",
                    "message": (f"ready_for_tapeout=true justified: all "
                                f"{len(upstream_results)} upstream M1–M3 "
                                f"reports independently re-checked PASS")})

    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": args.step_label,
        "signoff_file": _SIGNOFF_REL,
        "ready_for_tapeout_claimed": ready_claimed,
        "analog_applicable": applicable,
        "applicability_evidence": applic_evidence,
        "upstream_rollup": upstream_results,
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
    if ready_claimed is not None:
        print(f"  ready_for_tapeout (claimed): {ready_claimed}")
    for r in upstream_results:
        print(f"  [{r['stage']}] {r['key']}: {r['status']} ({r['detail']})")
    if waiver:
        print(f"  waiver:  {waiver.get('ticket', '?')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
