#!/usr/bin/env python3
"""aging_derate_sta_check.py — aging-corner STA sign-off gate for tapeout.

The tapeout-signoff survey found aging (NBTI / PBTI / HCI transistor-Vt
drift over lifetime) was MISSING from the flow — only a recommendation
string ("consider aging"), never a deterministic verdict. Fresh-silicon
STA proves the design meets timing at t=0; it says NOTHING about the
design after 3–10 years of bias-temperature / hot-carrier stress has
shifted the transistor threshold voltages and slowed the paths. Aging
sign-off is exactly the check that a design which MEETS timing fresh but
VIOLATES it aged is caught before tape-out.

This gate closes that hole with a deterministic slack threshold:

    PASS iff  aging_corner_worst_slack  >=  margin_ns   (default margin 0)

It reads the worst-case slack from a STA report that was run WITH an
aging derate applied — either an aging Liberty corner (a foundry
end-of-life .lib) or an aging `set_timing_derate` BEYOND the fresh-silicon
OCV. When a fresh-silicon STA report is ALSO supplied, the gate reports
the fresh-vs-aged delta so the classic aging catch — "MET fresh,
VIOLATED aged" — is named explicitly in the finding.

Accepted report schemas (aging report AND optional fresh report):
  1. JSON — any of these worst-slack keys (ns unless a *_ps key is used):
       worst_slack_ns / wns_ns / worst_negative_slack_ns / worst_slack /
       slack_ns / worst_setup_slack_ns   (also *_ps → converted)
     plus optional aging markers (see below).
  2. Plain .rpt — OpenSTA `report_worst_slack` ("worst slack -0.42"),
     `report_checks` path tail ("-0.42  slack (VIOLATED)" / "0.31 slack
     (MET)"), or a Quartus-style "Slack : -6.047". The MINIMUM (worst)
     slack found is used.

Aging evidence (§4.05 anti-vacuous-pass): a FRESH report mislabeled as
"aging" would trivially pass and FALSELY claim aging sign-off. So unless
`--assume-aging` is given (the caller asserts the report came from a
foundry aging Liberty corner they trust), the aging report must carry
aging evidence — an aging Liberty corner name or an aging derate marker
(tokens: aging / aged / nbti / pbti / hci / lifetime / end-of-life / eol /
degradation / vt-shift / N-year), or a JSON `is_aging`/`aging_corner`/
`aging_derate` field. Absent → SKIP (cannot certify), never PASS.

Honest-verdict rules:
  * aging report absent / unreadable                     → SKIP (rc 3)
  * aging report present but no aging evidence            → SKIP (rc 3)
      (and no --assume-aging): cannot certify it is an aged corner
  * aging report present but no slack value extractable   → SKIP (rc 3)
  * aging-corner worst slack  <  margin                   → FAIL (rc 1)
      (names the fresh-vs-aged delta when a fresh report is supplied)
  * aging-corner worst slack  >=  margin                  → PASS (rc 0)
  * report path not found at all                          → rc 2 (IO/arg)

SKIP (rc 3) is a distinct "cannot judge / not supplied" verdict — it is
NEVER conflated with PASS. The open PDK (sky130 / gf180mcu) ships NO
foundry aging Liberty, so on those PDKs this gate honestly SKIPs unless a
caller supplies an aging-derated STA report; it never fabricates an aging
number the PDK cannot supply.

Honest scope (disclosed, not fabricated):
  * A real NBTI/PBTI/HCI sign-off needs a FOUNDRY aging Liberty corner
    (transistor Vt-shift vs stress-time/temperature/voltage) or a
    calibrated aging `set_timing_derate`. This gate VERIFIES the aging-
    derated STA when one is supplied; it does NOT itself model the physics
    and it does NOT invent an aging corner where the PDK has none.

Usage:
    python3 aging_derate_sta_check.py <aging_report> [--fresh FRESH]
            [--margin-ns M] [--assume-aging] [--json OUT]
    <aging_report> may be a JSON file, a .rpt file, or a directory (the
    program then searches for *aging*.json / *aging*.rpt / *eol* / *aged*).

main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error / 3 SKIP.

chip-AGNOSTIC: reads only generic STA-report schemas + generic aging
tokens; no design/PDK literal appears in any rule.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_VERSION = "1.0.0"

# Worst-slack JSON keys (ns). A *_ps twin is handled by _PS_KEYS below.
_SLACK_NS_KEYS = (
    "worst_slack_ns", "wns_ns", "worst_negative_slack_ns", "worst_slack",
    "slack_ns", "worst_setup_slack_ns", "worst_hold_slack_ns",
)
_SLACK_PS_KEYS = ("worst_slack_ps", "wns_ps", "slack_ps")

# Aging-evidence JSON keys (truthy / present ⇒ evidence).
_AGING_FLAG_KEYS = ("is_aging", "aging", "aged")
_AGING_STR_KEYS = ("aging_corner", "aging_derate", "corner", "corner_name",
                   "scenario", "label")

# Aging tokens — aging-SPECIFIC (a plain `set_timing_derate` / generic OCV is
# NOT aging evidence; only these lifetime/degradation tokens are). Boundaries
# are LETTER-only lookarounds (not \b) so an underscore-separated corner name
# like "ss_aging_10yr" or "ff_nbti_eol" matches (\b treats "_" as a word char
# and would miss those), while a letter-flanked word like "staging"/"packaged"
# does NOT falsely fire.
_AGING_TOKEN_RE = re.compile(
    r"(?<![A-Za-z])(?:aging|aged|nbti|pbti|hci|hot[- ]?carrier|"
    r"bias[- ]?temperature|lifetime|end[- ]?of[- ]?life|eol|"
    r"degrad(?:ation|ed)|vt[h]?[- ]?shift|"
    r"\d+[- ]?(?:year|yr)s?)(?![A-Za-z])",
    re.IGNORECASE,
)

# Slack scrapers for text reports.
_WORST_SLACK_RE = re.compile(
    r"worst\s+slack\s+([-+]?\d+(?:\.\d+)?)", re.IGNORECASE)
_SLACK_TAG_RE = re.compile(
    r"([-+]?\d+(?:\.\d+)?)\s*(?:ns)?\s*slack\s*\((MET|VIOLATED)\)",
    re.IGNORECASE)
_SLACK_COLON_RE = re.compile(
    r"^\s*Slack\s*:\s*([-+]?\d+(?:\.\d+)?)", re.IGNORECASE | re.MULTILINE)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _slack_from_json(data: Any) -> Optional[float]:
    """Return the worst (minimum) slack in ns from a JSON report, or None."""
    if not isinstance(data, dict):
        return None
    scopes = [data]
    for k in ("summary", "timing", "setup", "aging", "worst"):
        sub = data.get(k)
        if isinstance(sub, dict):
            scopes.append(sub)
    vals: List[float] = []
    for scope in scopes:
        for k in _SLACK_NS_KEYS:
            if k in scope:
                v = _num(scope[k])
                if v is not None:
                    vals.append(v)
        for k in _SLACK_PS_KEYS:
            if k in scope:
                v = _num(scope[k])
                if v is not None:
                    vals.append(v / 1000.0)
    return min(vals) if vals else None


def _slack_from_text(text: str) -> Optional[float]:
    """Return the worst (minimum) slack in ns scraped from a text report."""
    vals: List[float] = []
    for m in _WORST_SLACK_RE.finditer(text):
        v = _num(m.group(1))
        if v is not None:
            vals.append(v)
    for m in _SLACK_TAG_RE.finditer(text):
        v = _num(m.group(1))
        if v is not None:
            # A VIOLATED tag with a positive magnitude means a negative slack.
            if m.group(2).upper() == "VIOLATED" and v > 0:
                v = -v
            vals.append(v)
    for m in _SLACK_COLON_RE.finditer(text):
        v = _num(m.group(1))
        if v is not None:
            vals.append(v)
    return min(vals) if vals else None


def _aging_evidence(data: Optional[Any], text: str) -> Optional[str]:
    """Return a short evidence string if the report shows aging derate, else
    None. §4.05: a plain OCV / fresh report has NO aging evidence."""
    if isinstance(data, dict):
        scopes = [data]
        for k in ("summary", "timing", "aging", "corner"):
            sub = data.get(k)
            if isinstance(sub, dict):
                scopes.append(sub)
        for scope in scopes:
            for k in _AGING_FLAG_KEYS:
                if bool(scope.get(k)):
                    return f"json:{k}={scope.get(k)}"
            for k in _AGING_STR_KEYS:
                val = scope.get(k)
                if isinstance(val, str) and _AGING_TOKEN_RE.search(val):
                    return f"json:{k}={val[:40]}"
    m = _AGING_TOKEN_RE.search(text)
    if m:
        return f"token:{m.group(0)}"
    return None


def _discover_report(path: Path, kind: str) -> Optional[Path]:
    """kind='aging' → aging-named report discovery; kind='fresh' → generic."""
    if path.is_file():
        return path
    if not path.is_dir():
        return None
    if kind == "aging":
        patterns = ["*aging*.json", "*aging*.rpt", "*aged*.json", "*aged*.rpt",
                    "*eol*.json", "*eol*.rpt", "*nbti*.rpt", "*end_of_life*"]
    else:
        patterns = ["*fresh*.json", "*fresh*.rpt", "*sta*.rpt", "*timing*.rpt",
                    "*sta*.json", "*timing*.json"]
    for pat in patterns:
        hits = sorted(path.rglob(pat))
        if hits:
            return hits[0]
    return None


def _read(path: Path) -> Tuple[Optional[str], Optional[Any], Optional[str]]:
    """Return (raw_text, parsed_json_or_None, error_or_None)."""
    try:
        raw = path.read_text(errors="replace")
    except OSError as exc:
        return None, None, f"cannot read {path.name}: {exc}"
    data = None
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return raw, None, f"unparseable JSON in {path.name}: {exc}"
    return raw, data, None


def evaluate(aging_path: Path, fresh_path: Optional[Path], margin_ns: float,
             assume_aging: bool) -> Tuple[str, Dict[str, Any]]:
    """Return (verdict, report). verdict in {PASS, FAIL, SKIP}."""
    rep: Dict[str, Any] = {
        "program": "aging_derate_sta_check",
        "version": _VERSION,
        "aging_report": str(aging_path),
        "fresh_report": str(fresh_path) if fresh_path else None,
        "margin_ns": margin_ns,
        "findings": [],
    }

    raw, data, err = _read(aging_path)
    if raw is None:
        rep["verdict"] = "SKIP"
        rep["skip_reason"] = "aging_report_unreadable"
        rep["findings"].append({"severity": "SKIP", "rule": "AGING_REPORT_UNREADABLE",
                                "message": err or "cannot read aging report"})
        return "SKIP", rep
    if err:  # bad JSON in a .json aging report
        rep["verdict"] = "SKIP"
        rep["skip_reason"] = "aging_report_unparseable"
        rep["findings"].append({"severity": "SKIP", "rule": "AGING_REPORT_UNPARSEABLE",
                                "message": err})
        return "SKIP", rep

    # (1) aging evidence — unless the caller asserts it via --assume-aging.
    evidence = _aging_evidence(data, raw)
    if not assume_aging and evidence is None:
        rep["verdict"] = "SKIP"
        rep["skip_reason"] = "no_aging_evidence"
        rep["findings"].append({
            "severity": "SKIP", "rule": "NO_AGING_EVIDENCE",
            "message": ("report carries no aging-derate evidence (aging Liberty "
                        "corner or aging set_timing_derate marker); cannot "
                        "certify it is an aged corner — pass --assume-aging only "
                        "if you supplied a trusted foundry aging Liberty. §4.05: "
                        "a fresh report must NOT pass as aging sign-off.")})
        return "SKIP", rep
    rep["aging_evidence"] = evidence if evidence is not None else "assumed(--assume-aging)"

    # (2) aging-corner worst slack.
    aged_slack = _slack_from_json(data) if data is not None else None
    if aged_slack is None:
        aged_slack = _slack_from_text(raw)
    if aged_slack is None:
        rep["verdict"] = "SKIP"
        rep["skip_reason"] = "no_aging_slack_value"
        rep["findings"].append({
            "severity": "SKIP", "rule": "NO_AGING_SLACK",
            "message": "no worst-case slack value found in the aging STA report"})
        return "SKIP", rep

    # (3) optional fresh-silicon slack (for the fresh-vs-aged narrative).
    fresh_slack: Optional[float] = None
    if fresh_path is not None:
        f_raw, f_data, f_err = _read(fresh_path)
        if f_raw is not None and not f_err:
            fresh_slack = (_slack_from_json(f_data) if f_data is not None else None)
            if fresh_slack is None:
                fresh_slack = _slack_from_text(f_raw)
        elif f_err:
            rep["findings"].append({"severity": "INFO", "rule": "FRESH_REPORT_IGNORED",
                                    "message": f"fresh report ignored: {f_err}"})

    rep["measured"] = {
        "aging_worst_slack_ns": aged_slack,
        "fresh_worst_slack_ns": fresh_slack,
        "margin_ns": margin_ns,
        "aging_delta_ns": (round(aged_slack - fresh_slack, 6)
                           if fresh_slack is not None else None),
    }

    # (4) verdict.
    passed = aged_slack >= margin_ns
    if passed:
        rep["verdict"] = "PASS"
        rep["findings"].append({
            "severity": "INFO", "rule": "AGING_TIMING_MET",
            "message": (f"aging-corner worst slack {aged_slack:.4f} ns "
                        f">= margin {margin_ns:.4f} ns — meets timing aged")})
        return "PASS", rep

    # FAIL — name the classic aging catch when fresh is available.
    msg = (f"aging-corner worst slack {aged_slack:.4f} ns < margin "
           f"{margin_ns:.4f} ns — VIOLATES timing under aging (Vt-drift over "
           f"lifetime)")
    if fresh_slack is not None and fresh_slack >= margin_ns:
        msg += (f"; the design MET timing fresh (slack {fresh_slack:.4f} ns) "
                f"but FAILS aged — exactly what aging sign-off catches")
    rep["verdict"] = "FAIL"
    rep["findings"].append({
        "severity": "ERROR", "rule": "AGING_TIMING_VIOLATED", "message": msg})
    return "FAIL", rep


def _emit(rep: Dict[str, Any], json_out: Optional[str]) -> None:
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(out + "\n")
    print(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("aging_report",
                    help="aging-derated STA report (JSON/.rpt) or dir")
    ap.add_argument("--fresh", default=None,
                    help="optional fresh-silicon STA report (JSON/.rpt) or dir")
    ap.add_argument("--margin-ns", type=float, default=0.0,
                    help="required worst-slack margin in ns (default 0.0)")
    ap.add_argument("--assume-aging", action="store_true",
                    help="assert the report IS an aging-derated corner (skips "
                         "the aging-evidence requirement; use only with a "
                         "trusted foundry aging Liberty)")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    in_path = Path(args.aging_report)
    if not in_path.exists():
        # an explicit path that does not exist is a user/arg error, not the
        # honest "project has no aging report" case.
        print(f"ERROR: aging report path not found: {in_path}", file=sys.stderr)
        return 2

    aging_in = _discover_report(in_path, "aging")
    if aging_in is None:
        # a directory that exists but holds NO aging-named report — the honest
        # open-PDK case (a fresh STA may exist but no aging corner). §4.05:
        # SKIP, never PASS, never fabricate an aging number.
        rep = {
            "program": "aging_derate_sta_check", "version": _VERSION,
            "aging_report": str(in_path), "verdict": "SKIP",
            "skip_reason": "aging_report_absent",
            "findings": [{
                "severity": "SKIP", "rule": "AGING_REPORT_ABSENT",
                "message": ("no aging-derated STA report found under "
                            f"{in_path} — the open PDK ships no foundry aging "
                            "Liberty; §4.05: SKIP, never a pass")}],
        }
        _emit(rep, args.json)
        return 3

    fresh_in: Optional[Path] = None
    if args.fresh is not None:
        fresh_path = Path(args.fresh)
        if not fresh_path.exists():
            print(f"ERROR: --fresh path not found: {fresh_path}", file=sys.stderr)
            return 2
        # a dir with no fresh report is fine — fresh is informative only.
        fresh_in = _discover_report(fresh_path, "fresh")

    verdict, rep = evaluate(aging_in, fresh_in, args.margin_ns, args.assume_aging)
    _emit(rep, args.json)
    return {"PASS": 0, "FAIL": 1, "SKIP": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
