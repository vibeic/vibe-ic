#!/usr/bin/env python3
"""
final_test_attestation_check.py — gate (v1.6.13 Wave 88, renumbered
in v1.6.14 Wave 90: Step 38 → 39; v1.6.15 Wave 91: Step 39 → 40;
v1.6.16: Step 41 final-test, STUB → REAL substance verification).

Step 41 — Final Test (ATE: functional + parametric + burn-in)

What this gate guards (the silicon / anti-fabrication failure)
--------------------------------------------------------------
The producing step writes `final_test_yield.json` containing a
`shippable: true|false` flag. A STUB gate that merely re-reads that
flag lets the producing step assert its own PASS — pure fabrication.

This checker instead INDEPENDENTLY parses the final-test artefact(s)
and verifies the substance behind `shippable`:

  1. Final-test yield: a measured final-test yield number must be
     present AND a target/floor threshold must be present, and
     measured >= target. We refuse to invent a threshold the
     artefact does not state (that would be fabrication) — absence of
     a target on a REQUIRED gate is an honest FAIL.
  2. Functional / parametric failures: if pass/fail die counts are
     present they must be self-consistent with the yield, and there
     must be at least one part that actually passed final test
     (cannot ship zero good parts).
  3. Burn-in: if `burn_in_results.json` is present (mandatory for
     automotive / medical graded parts), it must show zero burn-in
     failures for the graded/shipping population. A burn-in artefact
     that records failures but is still flagged shippable is the
     exact silicon escape this gate blocks.
  4. `shippable` (when present) must be CONSISTENT with the parsed
     numbers — i.e. it must be true only when (1)-(3) hold. A
     `shippable: true` that contradicts the numbers is a hard FAIL.

Behaviour
---------
* SKIP  (rc=2) — required artefacts missing AND step not waived
                 (step genuinely did not run yet).
* WAIVED(rc=0) — `waivers.json` declares step waived (evidence + ticket).
* PASS  (rc=0) — artefacts present AND substance verified: measured
                 final-test yield >= stated target, good-die count > 0,
                 burn-in (if present) shows zero graded failures, and
                 `shippable` is consistent with the numbers.
* FAIL  (rc=1) — artefacts present but substance fails OR insufficient
                 data to justify ship (missing yield / missing target /
                 inconsistent shippable flag / burn-in failures).

chip-AGNOSTIC. No vendor / IC / tool / yield-number hard-coded.
The only literals are field-name synonyms and the arithmetic
"measured >= target" / "failures == 0" — both supplied by the data.

Usage
-----
    python3 final_test_attestation_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ── waiver plumbing (unchanged contract) ────────────────────────────
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


_GATE_NAME = 'final_test_attestation_check'
_GATE_LABEL = 'final_test_attestation'
# Producing step writes these under phase3/stage5_manufacturing/.
_YIELD_FILE = 'phase3/stage5_manufacturing/final_test_yield.json'
_BURNIN_FILE = 'phase3/stage5_manufacturing/burn_in_results.json'
_REQUIRED_FILES = [_YIELD_FILE]  # yield required; burn-in conditional
_WAIVER_RATIONALE = 'ATE final-test attestation reader not shipped.'

# Field-name synonyms (chip-agnostic; pick the first present).
_MEASURED_YIELD_KEYS = (
    "measured_yield", "final_test_yield", "yield", "yield_pct",
    "yield_percent", "ft_yield", "actual_yield", "observed_yield",
)
_TARGET_YIELD_KEYS = (
    "target_yield", "yield_target", "target", "yield_floor",
    "min_yield", "minimum_yield", "yield_threshold", "spec_yield",
)
_PASS_COUNT_KEYS = (
    "good_die", "good_dies", "pass_count", "passed", "n_pass",
    "num_pass", "passing_die", "good_parts", "parts_passed",
)
_FAIL_COUNT_KEYS = (
    "bad_die", "bad_dies", "fail_count", "failed", "n_fail",
    "num_fail", "failing_die", "bad_parts", "parts_failed",
)
_TOTAL_COUNT_KEYS = (
    "total_die", "total_dies", "tested", "n_tested", "num_tested",
    "total_parts", "parts_tested", "total", "population",
)
# Burn-in failure-count synonyms.
_BURNIN_FAIL_KEYS = (
    "failures", "fail_count", "n_fail", "num_fail", "failed",
    "burn_in_failures", "infant_mortality", "early_failures",
)
_BURNIN_TESTED_KEYS = (
    "tested", "n_tested", "num_tested", "population", "sample_size",
    "parts_tested", "total", "burn_in_population",
)


def _first_num(d, keys):
    """Return (key, float-value) for the first present numeric key, else (None, None)."""
    if not isinstance(d, dict):
        return None, None
    for k in keys:
        if k in d and d[k] is not None:
            v = d[k]
            try:
                return k, float(v)
            except (TypeError, ValueError):
                continue
    return None, None


def _normalize_yield(value):
    """Normalize a yield to a fraction in [0,1].

    Accepts a percentage (e.g. 97.3 meaning 97.3 %) or a fraction
    (0.973). Heuristic: > 1.0 is treated as a percentage. Returns the
    fraction. (Both measured and target run through the same path so a
    >= comparison stays apples-to-apples regardless of representation.)
    """
    if value is None:
        return None
    return value / 100.0 if value > 1.0 else value


def _read_json(path):
    try:
        return json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        return {"__parse_error__": str(exc)}


def _verify_substance(project):
    """Independently verify final-test ship-readiness.

    Returns (verdict, rc, findings, parsed) where verdict ∈
    {PASS, FAIL} and findings is a list of severity-tagged dicts.
    Caller handles SKIP / WAIVED before reaching here.
    """
    findings = []
    parsed = {}

    yp = project / _YIELD_FILE
    data = _read_json(yp)
    if data.get("__parse_error__"):
        findings.append({"severity": "ERROR", "rule": "YIELD_PARSE_ERROR",
                         "message": f"{_YIELD_FILE}: {data['__parse_error__']}"})
        return "FAIL", 1, findings, parsed
    if not isinstance(data, dict):
        findings.append({"severity": "ERROR", "rule": "YIELD_NOT_OBJECT",
                         "message": f"{_YIELD_FILE} is not a JSON object"})
        return "FAIL", 1, findings, parsed

    ok = True

    # ── 1. measured yield vs stated target ──────────────────────────
    mk, mv = _first_num(data, _MEASURED_YIELD_KEYS)
    tk, tv = _first_num(data, _TARGET_YIELD_KEYS)
    m_frac = _normalize_yield(mv)
    t_frac = _normalize_yield(tv)
    parsed["measured_yield_key"] = mk
    parsed["measured_yield"] = mv
    parsed["target_yield_key"] = tk
    parsed["target_yield"] = tv

    if mv is None:
        ok = False
        findings.append({"severity": "ERROR", "rule": "MEASURED_YIELD_MISSING",
                         "message": "no measured final-test yield field present; "
                                    "cannot justify ship from absence"})
    if tv is None:
        # We refuse to invent a threshold — honest FAIL on required gate.
        ok = False
        findings.append({"severity": "ERROR", "rule": "TARGET_YIELD_MISSING",
                         "message": "no target/floor yield field present; refusing "
                                    "to fabricate a threshold the artefact does not state"})
    if m_frac is not None and t_frac is not None:
        if m_frac + 1e-9 < t_frac:
            ok = False
            findings.append({"severity": "ERROR", "rule": "YIELD_BELOW_TARGET",
                             "message": f"measured yield {mv} < target {tv} "
                                        f"({m_frac:.4f} < {t_frac:.4f})"})
        else:
            findings.append({"severity": "INFO", "rule": "YIELD_MEETS_TARGET",
                             "message": f"measured yield {mv} >= target {tv}"})

    # ── 2. good-die count sanity ────────────────────────────────────
    pk, pv = _first_num(data, _PASS_COUNT_KEYS)
    fk, fv = _first_num(data, _FAIL_COUNT_KEYS)
    nk, nv = _first_num(data, _TOTAL_COUNT_KEYS)
    parsed["pass_count"] = pv
    parsed["fail_count"] = fv
    parsed["total_count"] = nv

    if pv is not None:
        if pv <= 0:
            ok = False
            findings.append({"severity": "ERROR", "rule": "ZERO_GOOD_DIE",
                             "message": f"good-die count is {pv}; cannot ship zero good parts"})
        else:
            findings.append({"severity": "INFO", "rule": "GOOD_DIE_PRESENT",
                             "message": f"good-die count = {pv}"})
        # Cross-check counts vs measured yield if total is given.
        if nv and nv > 0 and m_frac is not None:
            implied = pv / nv
            if abs(implied - m_frac) > 0.02:  # 2 pp tolerance
                ok = False
                findings.append({"severity": "ERROR", "rule": "YIELD_COUNT_INCONSISTENT",
                                 "message": f"good/total = {pv}/{nv} = {implied:.4f} "
                                            f"contradicts reported yield {m_frac:.4f}"})
        # pass + fail must not exceed total
        if nv and fv is not None and (pv + fv) - nv > 1e-6:
            ok = False
            findings.append({"severity": "ERROR", "rule": "COUNT_OVERFLOW",
                             "message": f"pass({pv})+fail({fv}) exceeds total({nv})"})

    # ── 3. burn-in (conditional, mandatory for graded parts) ────────
    bp = project / _BURNIN_FILE
    if bp.is_file():
        bdata = _read_json(bp)
        if bdata.get("__parse_error__"):
            ok = False
            findings.append({"severity": "ERROR", "rule": "BURNIN_PARSE_ERROR",
                             "message": f"{_BURNIN_FILE}: {bdata['__parse_error__']}"})
        elif not isinstance(bdata, dict):
            ok = False
            findings.append({"severity": "ERROR", "rule": "BURNIN_NOT_OBJECT",
                             "message": f"{_BURNIN_FILE} is not a JSON object"})
        else:
            bfk, bfv = _first_num(bdata, _BURNIN_FAIL_KEYS)
            btk, btv = _first_num(bdata, _BURNIN_TESTED_KEYS)
            parsed["burn_in_present"] = True
            parsed["burn_in_failures"] = bfv
            parsed["burn_in_tested"] = btv
            if bfv is None:
                ok = False
                findings.append({"severity": "ERROR", "rule": "BURNIN_FAIL_COUNT_MISSING",
                                 "message": "burn-in artefact present but no failure-count "
                                            "field; cannot attest zero graded failures"})
            elif bfv > 0:
                ok = False
                findings.append({"severity": "ERROR", "rule": "BURNIN_FAILURES",
                                 "message": f"burn-in records {bfv} failure(s); graded "
                                            f"parts must show zero burn-in failures"})
            else:
                findings.append({"severity": "INFO", "rule": "BURNIN_CLEAN",
                                 "message": f"burn-in: 0 failures"
                                            + (f" / {btv} tested" if btv else "")})
    else:
        parsed["burn_in_present"] = False
        findings.append({"severity": "INFO", "rule": "BURNIN_ABSENT",
                         "message": "no burn_in_results.json (non-graded part); burn-in not applicable"})

    # ── 4. shippable flag must be CONSISTENT with the numbers ───────
    shippable = data.get("shippable", None)
    parsed["shippable_flag"] = shippable
    substance_pass = ok
    if shippable is True and not substance_pass:
        findings.append({"severity": "ERROR", "rule": "SHIPPABLE_CONTRADICTS_DATA",
                         "message": "artefact flags shippable=true but parsed numbers do "
                                    "not justify ship (see ERROR findings above)"})
    elif shippable is False and substance_pass:
        # Producer says NOT shippable; respect that — do not override to PASS.
        ok = False
        findings.append({"severity": "ERROR", "rule": "PRODUCER_NOT_SHIPPABLE",
                         "message": "numbers look ok but artefact flags shippable=false; "
                                    "respecting producer hold"})

    if ok:
        findings.append({"severity": "INFO", "rule": "SHIP_JUSTIFIED",
                         "message": "ship attestation justified by parsed yield/burn-in numbers"})
        return "PASS", 0, findings, parsed
    return "FAIL", 1, findings, parsed


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

    found = [p for p in _REQUIRED_FILES if (project / p).is_file()]
    missing = [p for p in _REQUIRED_FILES if p not in found]

    waiver = _step_waived(project, args.step_label)
    parsed = {}
    if missing and not waiver:
        verdict, rc = "SKIP", 2
        findings = [{"severity": "INFO", "rule": "REQUIRED_FILES_MISSING",
                      "message": f"missing: {missing}"}]
    elif missing and waiver:
        verdict, rc = "WAIVED", 0
        findings = [{"severity": "WAIVED", "rule": "STEP_WAIVED",
                      "message": f"waiver={waiver.get('ticket','?')}: {waiver.get('reason','?')}"}]
    else:
        verdict, rc, findings, parsed = _verify_substance(project)

    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": args.step_label,
        "required_files": _REQUIRED_FILES,
        "found": found,
        "missing": missing,
        "waiver": waiver,
        "rationale_when_skipped": _WAIVER_RATIONALE,
        "parsed": parsed,
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    if missing:
        print(f"  missing: {missing}")
    if waiver:
        print(f"  waiver:  {waiver.get('ticket','?')}")
    for f in findings:
        if f.get("severity") in ("ERROR", "WARN"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
