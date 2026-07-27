#!/usr/bin/env python3
"""
power_domain_crossing_check.py — M2 gate (substance-verifying).

M2 — power-domain crossing audit
=================================

For every net that crosses a power-domain boundary (as enumerated in
``power_domain.json#crossings``), this checker INDEPENDENTLY verifies that the
crossing is protected — i.e. that a matching level-shifter entry exists for
every voltage-mismatched crossing and a matching isolation entry exists for
every crossing into / out of a domain that can be powered down.  It does NOT
trust the ``all_crossings_protected`` boolean written into that file; it
recomputes that fact from the crossing list + the level_shifter.json /
isolation.json sidecar artefacts and FAILs on any unprotected crossing.

WHERE THE THREE SIDECARS COME FROM (M2-d4, corrected 2026-07)
-------------------------------------------------------------
NOT from this plugin.  power_domain.json / level_shifter.json /
isolation.json are INPUTS to this checker, and no program shipped here writes
any of them — they record the power intent and the cells the UPF-driven
implementation flow actually inserted, so they are supplied by that flow (or
hand-authored).  Earlier revisions of this docstring said "the producing step"
as though such a step existed; it does not, and a checker that names a
producer nobody ships sends the reader looking for a file that will not be
there.  Absent input is the honest rc=2 SKIP below, never a vacuous PASS.

The sibling gate ``power_domain_signal_crossing_check`` needs no sidecar at
all: it DERIVES the crossings from the UPF power-domain definitions + power
states and audits the UPF strategy.  Note what that does NOT currently buy on
the flow-audit path: all three sidecars are M2's ``required_outputs``, and
``flow_compliance_check.check_step`` returns MISSING on an all-absent
``required_outputs`` list BEFORE it evaluates the gate — so on a project with
UPF but no sidecars the derivation gate is never reached by the audit.  Run it
directly to get that coverage.  Closing the gap properly needs the emitter
nobody has written yet (see the M2 block in the flow yaml).

Domain model (chip-AGNOSTIC, matches the phase3 PERC cross-voltage-domain
model in phase3_one_shot_runner._xdomain_levelshifter_check):

  * A crossing needs a LEVEL SHIFTER when source/sink rail voltages differ
    (vdd_from != vdd_to), because a signal driven at one VDD into a gate
    powered at a different VDD is a real silicon hazard.
  * A crossing needs an ISOLATION CELL when either endpoint domain is
    power-gate-able (can be switched off independently) so the always-on
    side never floats / sees an X.
  * A crossing that is neither voltage-mismatched nor power-gate-bordered
    needs no protection cell and is trivially "protected".

A crossing is PROTECTED iff every protection it *requires* is present:
  required_level_shifter  => a level_shifter.json entry references its net
  required_isolation      => an isolation.json entry references its net

Behaviour
---------
* SKIP (rc=2) — ``power_domain.json`` absent AND step not waived.  An ABSENT
  artefact for a step that genuinely does not apply (e.g. no mixed-signal
  blocks) is an honest SKIP, never a vacuous PASS.
* WAIVED (rc=0) — ``waivers.json`` declares step waived (evidence + ticket).
* PASS (rc=0) — every enumerated crossing is provably protected.
* FAIL (rc=1) — file present but malformed, OR one or more enumerated
  crossings is unprotected (the exact silicon hazard this gate guards).

The ``all_crossings_protected`` boolean carried in the artefact is NEVER the
basis of the verdict; if present it is cross-checked and a mismatch (the file
claims protected, the substance says not) is itself reported as a CONTRADICTS
finding.

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded.

Usage
-----
    python3 power_domain_crossing_check.py <project_dir> [--json <out>]
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


_GATE_NAME = "power_domain_crossing_check"
_GATE_LABEL = "power_domain"
# Canonical artefact path (matches flow required_outputs).  A legacy
# ``reports/mixed_signal/...`` location is also accepted for back-compat.
_PD_REL = "reports/analog/mixed_signal/power_domain.json"
_LS_REL = "reports/analog/mixed_signal/level_shifter.json"
_ISO_REL = "reports/analog/mixed_signal/isolation.json"
_PD_REL_LEGACY = "reports/mixed_signal/power_domain.json"
_LS_REL_LEGACY = "reports/mixed_signal/level_shifter.json"
_ISO_REL_LEGACY = "reports/mixed_signal/isolation.json"
_WAIVER_RATIONALE = "UPF/CPF-driven power-domain crossing audit not shipped."


def _first_existing(project, *rels):
    for r in rels:
        p = project / r
        if p.is_file():
            return p
    return None


def _load_json(path):
    """Return (obj, error_str). error_str is None on success."""
    try:
        return json.loads(path.read_text()), None
    except Exception as exc:  # malformed JSON is a hard FAIL, never a PASS
        return None, f"{type(exc).__name__}: {exc}"


def _net_keys(entry):
    """Collect every net-identifying token from a protection-cell entry.

    Accepts a string (net name) or a dict with any of the common keys.
    Returns a set of non-empty lowercase strings.
    """
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


def _collect_protected_nets(obj):
    """From a level_shifter.json / isolation.json object, collect the set of
    net tokens that are covered by an inserted protection cell."""
    nets = set()
    if not isinstance(obj, dict):
        return nets
    # accept several list-field names the producing step may use
    for fld in ("level_shifters", "isolation_cells", "cells", "inserted",
                "entries", "protections", "list", "items"):
        seq = obj.get(fld)
        if isinstance(seq, list):
            for e in seq:
                nets |= _net_keys(e)
    return nets


def _crossing_net_token(c):
    """Net identity for a crossing record (matched against protection nets)."""
    if isinstance(c, str):
        return c.strip().lower()
    if isinstance(c, dict):
        for k in ("net", "signal", "name", "crossing_id", "id"):
            v = c.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip().lower()
    return ""


def _bool(v):
    return v is True


def _domain_powerdownable(c, key_self, key_other):
    """A crossing borders a power-down-able domain if either endpoint's
    domain is declared switchable / power-gate-able."""
    if not isinstance(c, dict):
        return False
    for k in (key_self, key_other, "power_gateable", "switchable",
              "can_power_down", "has_power_gate"):
        if _bool(c.get(k)):
            return True
    return False


def _required_protections(c):
    """Return (needs_ls, needs_iso) for one crossing record.

    needs_ls : source/sink rail voltages differ
    needs_iso: either endpoint domain can be powered down
    """
    needs_ls = False
    needs_iso = False
    if isinstance(c, dict):
        vf = c.get("vdd_from", c.get("v_from", c.get("vdd_src")))
        vt = c.get("vdd_to", c.get("v_to", c.get("vdd_sink")))
        if vf is not None and vt is not None:
            try:
                needs_ls = abs(float(vf) - float(vt)) > 1e-9
            except (TypeError, ValueError):
                needs_ls = str(vf) != str(vt)
        # explicit producer hints (still recomputed, never blindly trusted
        # for the PASS — only used to UP the requirement, never to waive it)
        if _bool(c.get("level_shifter_required")):
            needs_ls = True
        if _bool(c.get("isolation_required")):
            needs_iso = True
        needs_iso = needs_iso or _domain_powerdownable(
            c, "from_power_down", "to_power_down")
    return needs_ls, needs_iso


def _audit(pd_obj, ls_obj, iso_obj):
    """Independently audit every crossing.  Returns (findings, n_cross,
    n_unprotected)."""
    findings = []
    crossings = pd_obj.get("crossings") if isinstance(pd_obj, dict) else None
    if not isinstance(crossings, list):
        findings.append({
            "severity": "ERROR", "rule": "NO_CROSSING_LIST",
            "message": "power_domain.json has no 'crossings' list — cannot "
                       "verify substance; producer artefact is malformed."})
        return findings, 0, 1  # treat as 1 unprotected -> FAIL

    ls_nets = _collect_protected_nets(ls_obj) if ls_obj is not None else set()
    iso_nets = _collect_protected_nets(iso_obj) if iso_obj is not None else set()

    n_unprotected = 0
    for idx, c in enumerate(crossings):
        token = _crossing_net_token(c) or f"<crossing#{idx}>"
        needs_ls, needs_iso = _required_protections(c)
        missing = []
        if needs_ls:
            if token in ls_nets:
                pass
            else:
                missing.append("level_shifter")
        if needs_iso:
            if token in iso_nets:
                pass
            else:
                missing.append("isolation")
        if missing:
            n_unprotected += 1
            findings.append({
                "severity": "ERROR", "rule": "UNPROTECTED_CROSSING",
                "message": (f"crossing '{token}' requires {missing} but no "
                            f"matching cell found — voltage-mismatch / "
                            f"power-gate boundary is left unprotected.")})
    # cross-check the producer's own boolean (informational; verdict is ours)
    producer_claim = pd_obj.get("all_crossings_protected")
    if producer_claim is True and n_unprotected > 0:
        findings.append({
            "severity": "ERROR", "rule": "CONTRADICTS_PRODUCER",
            "message": (f"power_domain.json claims all_crossings_protected="
                        f"true but {n_unprotected} crossing(s) are provably "
                        f"unprotected — self-asserted PASS rejected.")})
    return findings, len(crossings), n_unprotected


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
                     "message": f"missing: {_PD_REL} (no mixed-signal power-"
                                f"domain artefact to audit)"}]
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
            iso_path = _first_existing(project, _ISO_REL, _ISO_REL_LEGACY)
            ls_obj = _load_json(ls_path)[0] if ls_path else None
            iso_obj = _load_json(iso_path)[0] if iso_path else None
            findings, n_cross, n_unprot = _audit(pd_obj, ls_obj, iso_obj)
            if n_unprot > 0:
                verdict, rc = "FAIL", 1
            else:
                verdict, rc = "PASS", 0
                findings.append({
                    "severity": "INFO", "rule": "ALL_CROSSINGS_PROTECTED",
                    "message": (f"{n_cross} power-domain crossing(s) audited; "
                                f"all required level-shifter / isolation cells "
                                f"present.")})

    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": args.step_label,
        "required_files": [_PD_REL],
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
