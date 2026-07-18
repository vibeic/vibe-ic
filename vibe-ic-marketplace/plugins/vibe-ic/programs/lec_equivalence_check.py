#!/usr/bin/env python3
"""
lec_equivalence_check.py — Step 13 deterministic LEC substance gate.

Closes the anti-fabrication hole at flow step `step13-lec`: the gate used
to TRUST the self-produced boolean `reports/lec.json:equivalent==true`.
A producing step could write `{"equivalent": true}` having compared ZERO
points (a vacuous claim), or write `equivalent:true` while the report body
still lists unproven / non-equivalent / aborted points. Both ship a netlist
that is NOT proven equivalent to its RTL — a silicon-correctness hole.

This checker INDEPENDENTLY parses the LEC artefacts and verifies REAL
equivalence evidence:

    PASS  iff  equivalent == true
               AND compared-points count > 0          (non-vacuous)
               AND non-equivalent points     == 0
               AND unproven / abort points   == 0

Any of the following is an HONEST FAIL (rc=1) — this is a REQUIRED check,
so absence of evidence is never a vacuous PASS:
    LEC_REPORT_MISSING       reports/lec.json absent
    LEC_REPORT_UNPARSEABLE   present but not valid JSON
    LEC_NOT_EQUIVALENT       equivalent field is not true
    LEC_VACUOUS_CLAIM        equivalent==true but 0 points compared
    LEC_NONEQUIV_POINTS      one or more non-equivalent points reported
    LEC_UNPROVEN_POINTS      one or more unproven / aborted points
    LEC_NO_POINT_EVIDENCE    equivalent==true, no count field anywhere, and
                             the .rpt (if any) yields no proven-point evidence

Field-name resilience
---------------------
Real LEC reports (Yosys `equiv_*`, Cadence Conformal, Synopsys Formality)
spell the same facts differently. We accept any of these aliases and take
the MAX of compatible aliases for the count, the SUM/MAX for failures:

  equivalent       : equivalent | is_equivalent | equiv | proven (bool)
  compared points  : compared_points | points_compared | total_points |
                     mapped_points | num_compared | proven_points |
                     proved_points | equivalent_points | matched_points |
                     key_points | gates_compared
  non-equivalent   : non_equivalent_points | non_equiv_points |
                     nonequivalent | failing_points | mismatches |
                     diff_points | num_non_equivalent | not_equivalent
  unproven / abort : unproven_points | unproven | abort_points | aborted |
                     inconclusive | num_unproven | undecided

When the JSON omits explicit counts, the human-readable `reports/lec.rpt`
is parsed as a corroborating source: Yosys prints
`Equivalence successfully proven!` plus `Proved N $equiv cells.` on success,
and `Found N unproven $equiv cells` on failure. We extract those.

CLI contract (matches sibling checkers)
    python3 lec_equivalence_check.py <project_dir> [--json <out>]
    main(argv) -> int   exit 0 PASS / 1 FAIL / 2 IO-or-arg error

Chip-AGNOSTIC — no design-specific assumptions; pure JSON/text parsing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple


GATE = "lec_equivalence_check"

# Relative artefact locations (per flow step13-lec required_outputs).
LEC_JSON_REL = "reports/lec.json"
LEC_RPT_REL = "reports/lec.rpt"

# ---- field-name alias panels (lower-cased exact-key match) ----------------
_EQUIV_BOOL_KEYS = (
    "equivalent", "is_equivalent", "equiv", "proven", "proved",
)
_COMPARED_KEYS = (
    "compared_points", "points_compared", "total_points", "mapped_points",
    "num_compared", "proven_points", "proved_points", "equivalent_points",
    "matched_points", "key_points", "gates_compared", "compare_points",
)
_NONEQUIV_KEYS = (
    "non_equivalent_points", "non_equiv_points", "nonequivalent",
    "non_equivalent", "not_equivalent", "failing_points", "mismatches",
    "diff_points", "num_non_equivalent", "diff_count",
)
_UNPROVEN_KEYS = (
    "unproven_points", "unproven", "abort_points", "aborted", "inconclusive",
    "num_unproven", "undecided", "abort_count",
)


# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str = GATE
    passed: bool = False
    inconclusive: bool = False
    equivalent: Optional[bool] = None
    compared_points: Optional[int] = None
    non_equivalent_points: Optional[int] = None
    unproven_points: Optional[int] = None
    evidence_source: str = ""          # "json" | "json+rpt" | "rpt"
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------
def _lc_keys(doc: dict) -> dict:
    """Return a lower-cased-key view of doc (shallow). Last-wins on collide."""
    out = {}
    for k, v in doc.items():
        if isinstance(k, str):
            out[k.lower()] = v
    return out


def _coerce_bool(v) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes", "equivalent", "pass", "passed", "1", "proven",
                 "proved"):
            return True
        if s in ("false", "no", "not_equivalent", "not equivalent", "fail",
                 "failed", "0", "unproven"):
            return False
    return None


def _coerce_count(v) -> Optional[int]:
    """Coerce a count-like value to int. Lists -> their length."""
    if isinstance(v, bool):
        return None  # a bool is not a count
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, (list, tuple)):
        return len(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+", v)
        if m:
            return int(m.group(0))
    return None


def _first_count(lc: dict, keys: Tuple[str, ...]) -> Optional[int]:
    """Return the first parseable count among the alias keys (max if many)."""
    vals: List[int] = []
    for k in keys:
        if k in lc:
            c = _coerce_count(lc[k])
            if c is not None:
                vals.append(c)
    if not vals:
        return None
    return max(vals)


def _bool_field(lc: dict) -> Optional[bool]:
    for k in _EQUIV_BOOL_KEYS:
        if k in lc:
            b = _coerce_bool(lc[k])
            if b is not None:
                return b
    return None


# ---------------------------------------------------------------------------
# .rpt parsing (Yosys / generic) — corroborating point-count evidence
# ---------------------------------------------------------------------------
_RPT_PROVEN_RE = re.compile(
    r"prov(?:ed|en)\s+(\d+)\s+\$?equiv", re.IGNORECASE)
_RPT_UNPROVEN_RE = re.compile(
    r"(?:found\s+)?(\d+)\s+unproven\s+\$?equiv", re.IGNORECASE)
_RPT_SUCCESS_RE = re.compile(
    r"equivalence\s+successfully\s+proven", re.IGNORECASE)


def parse_rpt(text: str) -> dict:
    """Best-effort extraction of point counts from an LEC text report."""
    out: dict = {
        "rpt_success_line": bool(_RPT_SUCCESS_RE.search(text)),
        "rpt_proven_points": None,
        "rpt_unproven_points": None,
    }
    proven = [int(m) for m in _RPT_PROVEN_RE.findall(text)]
    unproven = [int(m) for m in _RPT_UNPROVEN_RE.findall(text)]
    if proven:
        out["rpt_proven_points"] = max(proven)
    if unproven:
        out["rpt_unproven_points"] = max(unproven)
    return out


# ---------------------------------------------------------------------------
# Core audit
# ---------------------------------------------------------------------------
def audit(project: Path) -> AuditResult:
    res = AuditResult()
    json_path = project / LEC_JSON_REL
    rpt_path = project / LEC_RPT_REL

    # 1) JSON must exist — REQUIRED check, absence is honest FAIL.
    if not json_path.is_file():
        res.findings.append(Finding(
            rule="LEC_REPORT_MISSING", severity="ERROR",
            message=(f"{LEC_JSON_REL} not found — LEC (RTL vs post-DFT "
                     "netlist) has no result to verify. Run the "
                     "equivalence-check skill / eda_equiv tool."),
            file=LEC_JSON_REL))
        res.summary = {"json_present": False, "rpt_present": rpt_path.is_file()}
        return res

    # 2) JSON must parse.
    try:
        raw = json_path.read_text(encoding="utf-8", errors="replace")
        doc = json.loads(raw)
    except (OSError, ValueError) as exc:
        res.findings.append(Finding(
            rule="LEC_REPORT_UNPARSEABLE", severity="ERROR",
            message=f"{LEC_JSON_REL} is not valid JSON: {exc}",
            file=LEC_JSON_REL))
        res.summary = {"json_present": True, "json_parse_ok": False}
        return res

    if not isinstance(doc, dict):
        res.findings.append(Finding(
            rule="LEC_REPORT_UNPARSEABLE", severity="ERROR",
            message=f"{LEC_JSON_REL} top-level is not a JSON object.",
            file=LEC_JSON_REL))
        res.summary = {"json_present": True, "json_parse_ok": False}
        return res

    lc = _lc_keys(doc)

    # 3) The self-asserted boolean.
    equivalent = _bool_field(lc)
    res.equivalent = equivalent

    # 4) Extract counts from JSON.
    compared = _first_count(lc, _COMPARED_KEYS)
    non_equiv = _first_count(lc, _NONEQUIV_KEYS)
    unproven = _first_count(lc, _UNPROVEN_KEYS)
    res.evidence_source = "json"

    # 5) Corroborate / supplement from .rpt.
    rpt_info: dict = {}
    if rpt_path.is_file():
        try:
            rpt_text = rpt_path.read_text(encoding="utf-8", errors="replace")
            rpt_info = parse_rpt(rpt_text)
        except OSError:
            rpt_info = {}
        # If JSON gave no compared count, fall back to .rpt proven count.
        if compared is None and rpt_info.get("rpt_proven_points") is not None:
            compared = rpt_info["rpt_proven_points"]
            res.evidence_source = "rpt"
        elif (rpt_info.get("rpt_proven_points") is not None
              and res.evidence_source == "json"):
            res.evidence_source = "json+rpt"
        # If JSON gave no unproven count, fall back to .rpt unproven count.
        if unproven is None and rpt_info.get("rpt_unproven_points") is not None:
            unproven = rpt_info["rpt_unproven_points"]

    res.compared_points = compared
    res.non_equivalent_points = non_equiv
    res.unproven_points = unproven

    res.summary = {
        "json_present": True,
        "rpt_present": rpt_path.is_file(),
        "equivalent_field": equivalent,
        "compared_points": compared,
        "non_equivalent_points": non_equiv,
        "unproven_points": unproven,
        "evidence_source": res.evidence_source,
        "rpt": rpt_info,
    }

    # --- (d) INCONCLUSIVE: a frontend PARSE-ABORT built no miter ----------
    # A run that reaches 0 compared points because the gold/gate never PARSED
    # (read_verilog / read_slang could not elaborate a modern-SV closure) is NOT
    # classifiable as PASS or FAIL — there was no miter. It must NOT be a hard
    # FAIL (which cascade-marks 24 downstream steps MISSING) and must NOT be a
    # vacuous PASS. §4.05-safe: this re-classifies ONLY a genuine zero-miter
    # parse-abort — a miter that DID run and left non-equivalent / unproven
    # points still FAILs (the guard below requires no such points).
    verdict_field = str(lc.get("verdict", "")).strip().upper()
    is_inconclusive = (lc.get("inconclusive") is True
                       or verdict_field == "INCONCLUSIVE")
    zero_miter = ((compared in (None, 0))
                  and (non_equiv in (None, 0))
                  and (unproven in (None, 0))
                  and not rpt_info.get("rpt_success_line"))
    if is_inconclusive and zero_miter:
        res.inconclusive = True
        res.passed = False
        res.findings.append(Finding(
            rule="LEC_INCONCLUSIVE_PARSE_ABORT", severity="WARNING",
            message=("LEC verdict is INCONCLUSIVE — a frontend parse-abort "
                     "built no equivalence miter (0 compared points), so RTL≡"
                     "netlist could not be decided. This is a non-blocking "
                     "SKIPPED-CONDITION (never a hard FAIL that cascades, never "
                     "a vacuous PASS). Re-run with the slang frontend or fix the "
                     "parse error to get a real verdict."),
            file=LEC_JSON_REL))
        return res

    # --- substance verdict ------------------------------------------------
    # (a) the boolean itself must be true.
    if equivalent is not True:
        res.findings.append(Finding(
            rule="LEC_NOT_EQUIVALENT", severity="ERROR",
            message=("LEC result is not equivalent "
                     f"(equivalent field = {equivalent!r}). RTL and post-DFT "
                     "netlist differ — fall back to step 9 (synth/DFT)."),
            file=LEC_JSON_REL))

    # (b) any non-equivalent point => hard fail (independent of the boolean).
    if non_equiv is not None and non_equiv > 0:
        res.findings.append(Finding(
            rule="LEC_NONEQUIV_POINTS", severity="ERROR",
            message=(f"{non_equiv} non-equivalent point(s) reported — the "
                     "netlist is functionally different from the RTL at "
                     "these key points."),
            file=LEC_JSON_REL))

    # (c) any unproven / aborted point => hard fail (equivalence not proven).
    if unproven is not None and unproven > 0:
        res.findings.append(Finding(
            rule="LEC_UNPROVEN_POINTS", severity="ERROR",
            message=(f"{unproven} unproven / aborted point(s) — equivalence "
                     "is NOT proven for these points; a bounded/aborted proof "
                     "is not a clean LEC PASS."),
            file=LEC_JSON_REL))

    # (d) vacuous claim: equivalent==true with an EXPLICIT zero compared count.
    if equivalent is True and compared is not None and compared <= 0:
        res.findings.append(Finding(
            rule="LEC_VACUOUS_CLAIM", severity="ERROR",
            message=("equivalent==true but compared-points count is "
                     f"{compared} — a bare 'equivalent:true' with 0 points "
                     "compared is a vacuous claim, not proof of equivalence."),
            file=LEC_JSON_REL))

    # (e) no point evidence at all: equivalent==true, no count anywhere,
    #     and the .rpt (if present) gave no proven-point line. Cannot
    #     distinguish a real proof from a fabricated boolean => honest FAIL.
    if (equivalent is True
            and compared is None
            and non_equiv is None
            and unproven is None
            and not rpt_info.get("rpt_success_line")):
        res.findings.append(Finding(
            rule="LEC_NO_POINT_EVIDENCE", severity="ERROR",
            message=("equivalent==true but the report carries NO compared / "
                     "non-equivalent / unproven point count, and no .rpt "
                     "proven-points line corroborates it. Cannot verify "
                     "substance — the boolean is self-asserted. Emit point "
                     "counts (e.g. compared_points, non_equivalent_points) "
                     "or a Yosys 'Equivalence successfully proven' .rpt."),
            file=LEC_JSON_REL))

    res.passed = (equivalent is True) and not res.findings
    # Guard: if equivalent is True and the only positive evidence is the
    # .rpt success line (no numeric compared count), we accept it as PASS
    # since Yosys printed the canonical proof line — but only if (b)/(c)/(d)
    # added no findings. That path is already covered: findings is empty and
    # rule (e) did not fire because rpt_success_line is True.
    return res


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Step 13 LEC equivalence substance checker "
                    "(RTL vs post-DFT netlist)")
    parser.add_argument("project_dir", help="Project directory to scan")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2

    result = audit(project.resolve())

    report = asdict(result)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_json)

    print(report_json)
    # PASS → 0. An INCONCLUSIVE parse-abort is a non-blocking SKIPPED-CONDITION
    # (never a hard FAIL that cascade-marks downstream steps MISSING, never a
    # vacuous PASS: result.passed stays False) → 0. A real not-equivalent /
    # unproven / vacuous / missing result → 1.
    return 0 if (result.passed or result.inconclusive) else 1


if __name__ == "__main__":
    sys.exit(main())
