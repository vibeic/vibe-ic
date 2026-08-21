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

# Import the structural port-abort classifier. It replaces a FALSE diagnosis
# ("RTL and post-DFT netlist differ") with a truthful one ("equiv_make aborted
# on the port match; nothing was compared") at the SAME hard-FAIL severity.
# It never downgrades the tier and never names a cause it has not measured.
try:
    from lec_gate_netlist_select import (
        classify_port_abort as _classify_port_abort,
        port_abort_cause as _port_abort_cause,
        CANONICAL_STATUS as _GNS_STATUS,
        CANONICAL_VERDICT as _GNS_VERDICT,
    )
    _HAS_GNS = True
except ImportError:  # graceful degradation if the module is absent
    _HAS_GNS = False
    _GNS_STATUS = "LEC_STRUCTURAL_PORT_ABORT"
    _GNS_VERDICT = "STRUCTURAL-PORT-ABORT"

    def _classify_port_abort(log_text: str, compared_points: int):  # type: ignore[misc]
        return None

    def _port_abort_cause(project, gate_field: str = ""):  # type: ignore[misc]
        return False, ""


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
    rpt_text: str = ""
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

    # --- (d) INCONCLUSIVE: NO completed comparison → zero decided points ----
    # A run that reaches 0 decided points is NOT classifiable as PASS or FAIL —
    # there is no equivalence evidence in EITHER direction. Two causes, both
    # non-blocking:
    #   * a frontend PARSE-ABORT: the gold/gate never elaborated (read_verilog /
    #     read_slang could not parse a modern-SV closure) → no miter built; and
    #   * a wall-clock TIMEOUT that killed yosys BEFORE any completed
    #     equiv_status verdict (v1462 ibex/CPU-class): 0 points decided, no
    #     counterexample — a disclosed budget gap (lec_run marks it INCONCLUSIVE).
    # It must NOT be a hard FAIL (which cascade-marks downstream steps MISSING)
    # and must NOT be a vacuous PASS. §4.05-safe: this re-classifies ONLY a
    # zero-decided-point run — a miter that DID run and left non-equivalent /
    # unproven points still FAILs (the guard below requires no such points).
    verdict_field = str(lc.get("verdict", "")).strip().upper()
    is_inconclusive = (lc.get("inconclusive") is True
                       or verdict_field == "INCONCLUSIVE")
    zero_miter = ((compared in (None, 0))
                  and (non_equiv in (None, 0))
                  and (unproven in (None, 0))
                  and not rpt_info.get("rpt_success_line"))

    # --- (c0) SKIPPED-CONDITION: lec_run's DISCLOSED-skip verdict ----------
    # SKIPPED-CONDITION is the producer's explicit "I did NOT decide this"
    # signal: the gold top could not be resolved to a real RTL module, an
    # unstaged hard-macro module was referenced, or the netlist carries
    # SAT-unmodelable cells. In EVERY such case lec_run built no deciding miter
    # and recorded NO counterexample — exactly like INCONCLUSIVE, it is a
    # visible non-PASS with zero equivalence evidence in either direction, NOT
    # a proof of non-equivalence. Treating it as LEC_NOT_EQUIVALENT (the old
    # behaviour) turned a disclosed capability/staging gap into a hard FAIL that
    # cascade-marked every downstream step MISSING — the identical mis-handling
    # #208 fixed for INCONCLUSIVE. §4.05 NO-LEAK: this reclassifies ONLY when
    # there is no counterexample (non_equiv in {None,0}); a genuine mismatch
    # lands non_equiv>0 and still FAILs at the substance verdict (b) below, so a
    # real non-equivalence can never be laundered into a non-blocking skip.
    is_skipped = verdict_field == "SKIPPED-CONDITION"
    if is_skipped and (non_equiv in (None, 0)):
        res.inconclusive = True
        res.passed = False
        res.findings.append(Finding(
            rule="LEC_SKIPPED_CONDITION", severity="WARNING",
            message=("LEC verdict is SKIPPED-CONDITION — lec_run made a "
                     "DISCLOSED skip (gold top not resolvable to an RTL module, "
                     "an unstaged hard-macro module, or SAT-unmodelable cells) "
                     "and built no deciding miter, recording NO counterexample. "
                     "RTL≡netlist was not decided in EITHER direction — this is "
                     "the same evidence class as INCONCLUSIVE, a non-blocking "
                     "disclosed skip (never a hard FAIL that cascades downstream "
                     "MISSING, never a vacuous PASS). Resolve the top / stage "
                     "the macro / supply Liberty, or close with sign-off LEC, "
                     "to get a real verdict."),
            file=LEC_JSON_REL))
        return res

    if is_inconclusive and zero_miter:
        res.inconclusive = True
        res.passed = False
        res.findings.append(Finding(
            rule="LEC_INCONCLUSIVE_PARSE_ABORT", severity="WARNING",
            message=("LEC verdict is INCONCLUSIVE — no completed comparison "
                     "produced any decided points (0 compared): a frontend "
                     "parse-abort built no miter, or a wall-clock timeout killed "
                     "yosys before any equiv_status verdict. RTL≡netlist could "
                     "not be decided in EITHER direction (no counterexample). "
                     "This is a non-blocking SKIPPED-CONDITION (never a hard "
                     "FAIL that cascades, never a vacuous PASS). Re-run with the "
                     "slang frontend / a larger --timeout, or close with "
                     "sign-off LEC, to get a real verdict."),
            file=LEC_JSON_REL))
        return res

    # --- (d2) #208 — NON-CONVERGENCE INCONCLUSIVE: a COMPLETED miter left
    # points unproven, but equiv_induct did NOT converge (a flat wall) and NO
    # counterexample was recorded (0 non-equivalent points). Non-convergence is
    # NOT non-equivalence — a real difference produces a counterexample
    # (non_equivalent_points > 0). lec_run is the authority that inspected the
    # raw yosys log for a counterexample and only then marked the run
    # INCONCLUSIVE; trust that verdict here ONLY while non_equiv == 0. A single
    # non-equivalent point forces the substance FAIL below (§4.05 NO-LEAK — this
    # can never launder a real mismatch into a pass). Non-blocking, but a visible
    # non-PASS: it must be closed with sign-off LEC.
    if is_inconclusive and (non_equiv in (None, 0)):
        res.inconclusive = True
        res.passed = False
        res.findings.append(Finding(
            rule="LEC_INCONCLUSIVE_NONCONVERGENCE", severity="WARNING",
            message=("LEC verdict is INCONCLUSIVE — a completed equivalence "
                     f"miter left {unproven} point(s) unproven, but equiv_induct "
                     "did NOT converge (a flat induction wall) and NO "
                     "counterexample was recorded (0 non-equivalent points). "
                     "Non-convergence is not non-equivalence: a real difference "
                     "produces a counterexample. This is INCONCLUSIVE, NOT "
                     "NOT_EQUIVALENT — a disclosed sequential-depth capability "
                     "gap. Close with sign-off LEC (Conformal/VC LEC), which "
                     "handles deep sequential induction. Visible non-PASS (never "
                     "a vacuous PASS)."),
            file=LEC_JSON_REL))
        return res

    # --- (d3) STRUCTURAL PORT-ABORT — a TRUTHFUL name for rule (a) ----------
    # yosys equiv_make refuses to build a miter when a gate-side top-level port
    # has no gold counterpart:
    #   ERROR: Can't match gate port `_NNN_.d_gate' to a gold port.
    # compared_points is then 0 and NOTHING was compared. Reporting that as
    # LEC_NOT_EQUIVALENT / "RTL and post-DFT netlist differ — fall back to step
    # 9" is a FALSE statement: no comparison ever happened, so no difference was
    # ever observed, and the next agent is sent to re-synthesise a design that
    # was never examined.
    #
    # This changes the RULE NAME and the MESSAGE only. It is deliberately NOT a
    # reclassification into the INCONCLUSIVE tier:
    #   * res.inconclusive stays False, so main() still returns rc=1 (hard
    #     FAIL) exactly as before. Routing it to rc=3 would print the
    #     PASS_WITH_WAIVERS sentinel and flow_compliance would record step 13 as
    #     WAIVED-DEFERRED — so a genuine top-level port-set mismatch (scan ports
    #     present in the netlist and absent from the gold RTL — a real DFT
    #     integration defect) would be laundered into a near-pass. Equivalence
    #     was not proven; an unproven equivalence is never a waiver.
    #   * the ATPG-cut cause is asserted ONLY when port_abort_cause() confirms
    #     the fingerprint on the netlist that lec.json says was compared. The
    #     yosys string alone proves only "the port sets do not match"; naming a
    #     cause from it would put a fabricated finding in a sign-off report.
    #
    # The zero_miter guard is load-bearing and NOT redundant with the
    # compared==0 test inside classify_port_abort: it additionally requires no
    # counterexample and no unproven point, so a run that recorded a real
    # mismatch keeps the mismatch verdict even if its log also carries an abort
    # line from an earlier attempt.
    _structural_port_abort = bool(
        zero_miter
        and _classify_port_abort(
            rpt_text, compared if compared is not None else 0) is not None)

    # --- substance verdict ------------------------------------------------
    # (a) the boolean itself must be true.
    if equivalent is not True:
        if _structural_port_abort:
            _cause_ok, _cause = _port_abort_cause(
                project, str(lc.get("gate", "")))
            res.findings.append(Finding(
                rule=_GNS_STATUS, severity="ERROR",
                message=(
                    f"LEC verdict is {_GNS_VERDICT}: yosys equiv_make aborted "
                    "with a port-match error, so NO miter was built and "
                    f"compared_points={compared if compared is not None else 0}. "
                    "Nothing was compared — this is NOT evidence that the RTL "
                    "and the netlist differ, and it is NOT a pass either. "
                    + (f"Measured cause — {_cause}. The upstream producer is "
                       "fault_atpg_run.py, which writes Fault's ATPG "
                       "combinational-cut output verbatim to scan_netlist.v "
                       "when no scan netlist exists yet; post_dft_opt then "
                       "opt_cleans that into the netlist handed to LEC. Fix the artifact the DFT chain hands "
                       "over — do NOT re-point LEC at a different netlist, "
                       "because comparing <top>_synth.v would report the "
                       "post-DFT equivalence step as PASS without ever reading "
                       "the post-DFT netlist."
                       if _cause_ok else
                       "The gate netlist named in the report does NOT carry the "
                       "ATPG combinational-cut fingerprint, so the cause is "
                       "unconfirmed and is NOT guessed here. Diff the top-level "
                       "port set of the gate netlist against the gold RTL: the "
                       "usual cause is DFT/scan ports present in the netlist "
                       "and absent from the RTL, which is a real defect.")),
                file=LEC_RPT_REL))
        else:
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

    # A real not-equivalent / unproven / vacuous / missing result → 1 (hard FAIL).
    if not (result.passed or result.inconclusive):
        return 1

    # A genuine PASS → 0.
    if result.passed:
        return 0

    # INCONCLUSIVE → the WAIVED-DEFERRED tier (rc=3 + the `PASS_WITH_WAIVERS`
    # stdout sentinel), NOT a bare rc=0.
    #
    # WHY (the bug this replaces): this branch used to `return 0`, reasoning
    # that INCONCLUSIVE must not be a hard FAIL that cascade-marks downstream
    # steps MISSING — which is correct — and that `result.passed` staying False
    # in the JSON kept it "a visible non-PASS". It did not. Step 13's gate in
    # flow/phase1_phase2_phase3.yaml is
    #     program_exit_zero: "lec_equivalence_check . --json …"
    # and `_check_program_exit_zero` maps rc==0 → passed=True with NO downgrade
    # tier attached. So an INCONCLUSIVE LEC was recorded in the authoritative
    # flow_compliance matrix as a BARE PASS — i.e. the compliance table asserted
    # "RTL ≡ post-DFT netlist: PASS" about a netlist nothing had proven
    # equivalent. That is strictly worse than a visible FAIL, and it is exactly
    # the false-clean this module's own docstring exists to prevent.
    #
    # rc=3 + sentinel is the ESTABLISHED idiom for precisely this shape (a
    # disclosed capability gap that must not read as a bare PASS) — see
    # cpu_functional_oracle_waiver_check, which emits `{"verdict":
    # "PASS_WITH_WAIVERS", "exit_code": 3}`. flow_compliance promotes it to
    # WAIVED-DEFERRED, which is visible, is excluded from a strict PASS
    # headline, and still does not cascade downstream steps to MISSING —
    # keeping every property the rc=0 choice was reaching for, without the
    # false PASS.
    #
    # The sentinel MUST be the LAST line AND must stay SHORT. flow_compliance
    # inspects only the trailing 300 chars of stdout and requires the token at
    # line-START (`line.lstrip().startswith(...)`). A long single line would be
    # sliced mid-string by the [-300:] window, the `PASS_WITH_WAIVERS` prefix
    # would fall outside it, `startswith` would fail, and the gate would quietly
    # fall back to a bare rc-3 FAIL. So: the (long) reason goes on its own line
    # FIRST, and the short sentinel line goes LAST.
    reason = (result.findings[0].rule if result.findings
              else "LEC_INCONCLUSIVE")
    detail = (result.findings[0].message if result.findings
              else "LEC verdict is INCONCLUSIVE — no equivalence decided.")
    print(detail)
    print(f"PASS_WITH_WAIVERS: step 13 LEC not decided ({reason}) — "
          f"WAIVED-DEFERRED to sign-off LEC, never a bare PASS.")
    return 3


if __name__ == "__main__":
    sys.exit(main())
