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

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


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


from lec_gate_netlist_select import (  # noqa: E402 — F1 subject binding
    proof_subject_binding as _proof_subject_binding,
    BINDING_STALE as _B_STALE,
    BINDING_UNBOUND as _B_UNBOUND,
    BINDING_SCAN_UNCONSTRAINED as _B_SCAN_UNCONSTRAINED,
    BINDING_MATCH as _B_MATCH,
)

GATE = "lec_equivalence_check"

# Relative artefact locations (per flow step13-lec required_outputs).
LEC_JSON_REL = "reports/lec.json"
LEC_RPT_REL = "reports/lec.rpt"
#: Step 13's own disclosure that it did not prove anything this time
#: (`design_one_shot_runner.step_lec_equivalence` writes it; verdict
#: SKIPPED-CONDITION). See `retire_superseded_not_run`.
LEC_NOT_RUN_REL = "reports/lec_not_run.json"

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
    # #2068 — the budget-exhausted, verdict-less terminal state. NOT a verdict
    # and NOT a waiver: nothing was decided, so nothing can be waived. When
    # True the step is NOT_MEASURED and `exhausted_resource` names what ran out.
    not_measured: bool = False
    exhausted_resource: str = ""
    # #2068 item 2 — an overrun that did NOT cost a verdict. Recorded, never
    # acted on: the budget is a RECORDING ceiling (owner ruling on #2051), so a
    # real verdict produced past it keeps its verdict and the overrun is a note.
    budget_overrun: dict = field(default_factory=dict)
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

# THREE DIFFERENT NUMBERS CARRY THE WORD `unproven`, AND ONLY ONE IS RESIDUAL.
# `max()` over every match of `_RPT_UNPROVEN_RE` reads the LARGEST of them,
# which is structurally the equiv_simple ENTRY line — the population that pass
# STARTED with, before it discharged a single point:
#
#   equiv_simple ENTRY   "Found 3396 unproven $equiv cells (3396 groups) in
#                         equiv:"                  <- the pass's INPUT
#   equiv_induct residual"Found 35 unproven $equiv cells in module equiv:"
#   equiv_status FINAL   "Of those cells 830 are proven and 3242 are
#                         unproven."               <- the run's answer
#
# The final line was never matched at all (`3242 are unproven` carries no
# `$equiv` after the count), so the one authoritative reading was the one
# reading this gate could not see, while the entry line — a number that says
# nothing about what remains — was reported as `rpt_unproven_points` and fed
# straight into `LEC_UNPROVEN_POINTS`. On the measured opentitan_aes log that
# is 3396 unproven published for a run whose own status line says 3242, and on
# a log where equiv_simple then proved everything it is a FAIL manufactured out
# of a pass's input.
#
# lec_run's parser already owns this precedence and documents it; this gate is
# deliberately an INDEPENDENT reader of the same artefacts (a producer bug must
# stay visible to it), so the precedence is re-stated here rather than imported,
# and `test_lec_rpt_reading_matches_the_producer` pins the two readings to the
# same answer on the same logs.
_RPT_FINAL_RE = re.compile(
    r"(\d+)\s+are\s+proven\s+and\s+(\d+)\s+are\s+unproven", re.IGNORECASE)
_RPT_SIMPLE_ENTRY_RE = re.compile(
    r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+\(\d+\s+groups\)"
    r"\s+in\s+equiv\s*:", re.IGNORECASE)
#: Anchored at line start for the same reason lec_run anchors it: a design
#: comment a tool echoes into its log must not be read as this run's residual.
_RPT_INDUCT_RESIDUAL_RE = re.compile(
    r"(?m)^[ \t]*Found\s+(\d+)\s+unproven\s+\$equiv\s+cells"
    r"\s+in\s+module\s+equiv\s*:", re.IGNORECASE)
_RPT_PROVED_PASS_RE = re.compile(
    r"Proved\s+(\d+)\s+previously\s+unproven\s+\$equiv\s+cells",
    re.IGNORECASE)
#: A Verilog LINE COMMENT the tool echoed into its own log. Anchored at line
#: start on purpose: an absolute path (`/foss/pdks/...`) and a `//` inside a
#: sentence are not comments and must survive. Dropped BEFORE any count is
#: read, because a design that carries
#:     // Found 999 unproven $equiv cells in module equiv:
#: would otherwise have written this gate's verdict from its own source file —
#: caught by the spoof arm of test_lec_rpt_point_reading_precedence, which the
#: line-anchored residual pattern alone did NOT stop (it fell through to the
#: generic branch and read 999).
_RPT_HDL_LINE_COMMENT_RE = re.compile(r"(?m)^[ \t]*//.*$")


def parse_rpt(text: str) -> dict:
    """Point counts from an LEC text report, read by PRECEDENCE not by max().

    `rpt_points_source` names which reading produced the numbers, so a reader
    of the summary can tell an equiv_status answer from a mid-ladder estimate
    from a generic tool's line. A count that no reading measured stays None —
    never a zero and never the nearest available number.
    """
    text = _RPT_HDL_LINE_COMMENT_RE.sub("", text or "")
    out: dict = {
        "rpt_success_line": bool(_RPT_SUCCESS_RE.search(text)),
        "rpt_proven_points": None,
        "rpt_unproven_points": None,
        "rpt_points_source": None,
    }
    # 1) equiv_status — the run's own final decomposition. LAST match: a recipe
    #    that calls equiv_status more than once (a resumed leg states the
    #    position it read back and then its own answer) must be read at the
    #    state it FINISHED in.
    finals = list(_RPT_FINAL_RE.finditer(text))
    if finals:
        out["rpt_proven_points"] = int(finals[-1].group(1))
        out["rpt_unproven_points"] = int(finals[-1].group(2))
        out["rpt_points_source"] = "equiv_status"
        return out
    # 2) A yosys log that never reached equiv_status (killed, stalled). Proven
    #    is CUMULATIVE — each pass reports the cells IT discharged and the sets
    #    are disjoint; unproven is the LAST residual, the furthest state the
    #    run reached. Either may be absent, and absent stays None.
    proved = [int(n) for n in _RPT_PROVED_PASS_RE.findall(text)]
    residual = [int(n) for n in _RPT_INDUCT_RESIDUAL_RE.findall(text)]
    if proved or residual:
        if proved:
            out["rpt_proven_points"] = sum(proved)
        if residual:
            out["rpt_unproven_points"] = residual[-1]
        out["rpt_points_source"] = "yosys_pass_lines"
        if residual:
            return out
        # No residual line: the entry count is the only `unproven` number in
        # this log and it is the pass's INPUT. Say so instead of reporting it.
        if _RPT_SIMPLE_ENTRY_RE.search(text):
            out["rpt_unproven_not_measured"] = (
                "the only `unproven` count in this log is the equiv_simple "
                "ENTRY line, which is the population that pass started with, "
                "not what remains: no equiv_status line and no residual line")
        return out
    # 3) A non-Yosys tool. The generic shapes, with the equiv_simple entry line
    #    excluded by SPAN so the exclusion cannot be defeated by a tool that
    #    happens to print the same words elsewhere on the line.
    _entry_spans = [m.span() for m in _RPT_SIMPLE_ENTRY_RE.finditer(text)]
    proven = [int(m) for m in _RPT_PROVEN_RE.findall(text)]
    unproven = [int(m.group(1)) for m in _RPT_UNPROVEN_RE.finditer(text)
                if not any(a <= m.start() < b for a, b in _entry_spans)]
    if proven:
        out["rpt_proven_points"] = max(proven)
        out["rpt_points_source"] = "generic"
    if unproven:
        out["rpt_unproven_points"] = max(unproven)
        out["rpt_points_source"] = "generic"
    if out["rpt_unproven_points"] is None and _entry_spans:
        out["rpt_unproven_not_measured"] = (
            "the only `unproven` count in this log is the equiv_simple ENTRY "
            "line, which is the population that pass started with, not what "
            "remains")
    return out


# ---------------------------------------------------------------------------
# Core audit
# ---------------------------------------------------------------------------
#: #2068 — keys a producer uses to say "my declared budget ran out". lec_run
#: writes `step_budget_exhausted`; `budget_exhausted` is the older spelling and
#: `_lec_leg_stop_evidence` in phase3_one_shot_runner already reads both.
_BUDGET_EXHAUSTED_KEYS = ("step_budget_exhausted", "budget_exhausted")

#: Where the producer names WHAT ran out. Never defaulted: an exhaustion whose
#: resource was not recorded is reported as unnamed, not as wall-clock.
_EXHAUSTED_RESOURCE_KEYS = ("exhausted_resource", "budget_resource",
                            "exhausted_budget_resource")


def budget_exhausted_resource(lc: dict) -> Optional[str]:
    """Return the named exhausted resource when the producer declares budget
    exhaustion, `"unnamed"` when it declares it without naming one, else None.

    `lc` is the lower-cased key map of `reports/lec.json`.
    """
    if not any(lc.get(k) is True for k in _BUDGET_EXHAUSTED_KEYS):
        return None
    for k in _EXHAUSTED_RESOURCE_KEYS:
        v = lc.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "unnamed"


def verdict_was_decided(lc: dict, equivalent: Optional[bool],
                        non_equiv: Optional[int]) -> bool:
    """True iff the LEC actually DECIDED something.

    Decided means one of the two directions was established: a proof
    (`equivalent is True`) or a counterexample (`non_equivalent_points > 0`).
    Everything else -- INCONCLUSIVE, SKIPPED-CONDITION, a bare absent verdict --
    decided nothing, whatever else the report carries. `unproven_points` is
    deliberately NOT a decision: an unproven point is the absence of one.
    """
    if equivalent is True:
        return True
    if non_equiv is not None and non_equiv > 0:
        return True
    return False


def audit(project: Path) -> AuditResult:
    res = AuditResult()
    # The named observed-reset producer has its own independently adopted
    # execution, not a lec_run report. Reopen that real consumer; never project
    # it into legacy proof_identity fields or fall back after its refusal.
    named = ('input/flow109/D25.json', 'input/flow109/D25_source_authority.json',
             'reports/lec_eqy_execution.json')
    if any((project / name).exists() or (project / name).is_symlink() for name in named):
        import os
        import hashlib
        import flow109
        import flow109_metric_acceptance as metrics
        from lec_gate_netlist_select import pnr_consumed_netlist, step15_top
        res.evidence_source = 'adopted_native_eqy'
        try:
            manifest = project / named[0]
            if manifest.is_symlink() or not manifest.is_file():
                raise metrics.MetricRefusal('D25_NATIVE_INPUT_UNBOUND', 'named manifest absent or linked')
            owner = flow109.validate_execution_context(json.loads(
                Path(os.environ[flow109.CONTEXT_ENV]).read_text()))
            context = flow109.component_context(owner, requested_step='D25')
            if context['resolved_row']['id'] != 'D25':
                raise metrics.MetricRefusal('D25_CONTEXT_INVALID', 'not the selected LEC contract')
            accepted = metrics.accept_d25(project, context)
            res.summary = {'metric_acceptance': accepted,
                           'qualification_scope': accepted.get('qualification_scope')}
            execution = accepted.get('native_execution') or {}
            proof = execution.get('proof') or {}
            res.compared_points = proof.get('compared_points')
            res.non_equivalent_points = len(proof.get('non_equivalent_points', []))
            res.unproven_points = len(proof.get('unproven_points', []))
            if accepted['status'] != 'PASS':
                res.not_measured = accepted['status'] != 'FAIL'
                raise metrics.MetricRefusal(accepted['reason'], 'named native consumer did not accept')
            gate = execution['subject']['gate_netlist']
            top = execution['mode']['top']
            consumed, note, scan = pnr_consumed_netlist(project, step15_top(project, top))
            if (consumed is None or not consumed.is_file() or scan
                    or consumed.resolve() != (project / gate['path']).resolve()
                    or hashlib.sha256(consumed.read_bytes()).hexdigest() != gate['sha256']):
                raise metrics.MetricRefusal('LEC_SUBJECT_UNBOUND', 'native proof differs from delivered netlist: ' + note)
            res.summary['subject_binding'] = {
                'state': _B_MATCH, 'top': top, 'proved_path': gate['path'],
                'proved_sha256': 'sha256:' + gate['sha256'],
                'consumer_path': str(consumed.relative_to(project)),
                'consumer_sha256': 'sha256:' + gate['sha256'],
                'consumer_note': note, 'consumer_scan_inserted': scan,
                'execution_record': execution['execution_record']}
            res.passed = res.equivalent = True
        except (flow109.Flow109Error, metrics.MetricRefusal, OSError, ValueError,
                KeyError, TypeError) as exc:
            res.findings.append(Finding(rule=getattr(exc, 'code', 'D25_NATIVE_UNBOUND'),
                severity='ERROR', message=str(exc), file='reports/lec_eqy_execution.json'))
        return res
    if (project / 'reports/lec_eqy.json').is_file() and _os.environ.get('VIBEIC_FLOW109_CONTEXT'):
        import flow109
        import flow109_metric_acceptance as metrics
        try:
            owner = flow109.validate_execution_context(json.loads(
                Path(_os.environ[flow109.CONTEXT_ENV]).read_text()))
            if all(owner['features'].get(key) is False for key in ('requires_dft', 'requires_scan')):
                plan = flow109.resolve_plan(owner['features'], owner['step_profiles'])
                context = flow109.component_context(flow109.execution_context(plan, 'D25', 'D25'),
                                                     requested_step='D25')
                accepted = metrics.accept_d25(project, context)
                proof = accepted.get('native_consumer') or {}
                res.evidence_source = 'native_eqy'
                res.passed = res.equivalent = accepted['status'] == 'PASS'
                res.not_measured = accepted['status'] not in ('PASS', 'FAIL')
                res.compared_points = proof.get('compared_points')
                res.non_equivalent_points = len(proof.get('non_equivalent_points', []))
                res.unproven_points = len(proof.get('unproven_points', []))
                res.summary = {'metric_acceptance': accepted}
                if not res.passed:
                    res.findings.append(Finding(accepted['reason'], 'ERROR', 'native EQY consumer did not accept'))
                return res
        except (flow109.Flow109Error, metrics.MetricRefusal, OSError, ValueError, KeyError, TypeError) as exc:
            res.evidence_source = 'native_eqy'
            res.not_measured = True
            res.findings.append(Finding(getattr(exc, 'code', 'D25_NATIVE_UNBOUND'), 'ERROR', str(exc)))
            return res
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

    # --- (a0) F1 — THE PROOF MUST BE ABOUT THE NETLIST STEP 15 ROUTES ------
    # Checked before any verdict, because a verdict about another file is not
    # a verdict about this chip, whatever it says. Measured on spm (run23):
    # PASS 66/66 on the generic `netlist.v` while PnR routed `spm_synth.v`.
    # The comparison is by sha256: lec_run binds the gate side it read into
    # `proof_identity.gate_netlist`, and step 15's own resolver names the file
    # it routes. Before that file exists (phase 2, no mapped netlist yet) there
    # is nothing routed to be stale against, and the substance rules decide.
    binding = _proof_subject_binding(project, doc)
    res.summary["subject_binding"] = binding
    _bind_state = binding.get("state")
    if _bind_state in (_B_STALE, _B_UNBOUND, _B_SCAN_UNCONSTRAINED):
        if _bind_state == _B_STALE:
            rule = "LEC_STALE_PROOF"
            msg = (f"{LEC_JSON_REL} proved {binding.get('proved_path')} "
                   f"({binding.get('proved_sha256')}), but step 15 routes "
                   f"{binding.get('consumer_path')} "
                   f"({binding.get('consumer_sha256')}). The proof is about "
                   f"a different netlist and says nothing about the one that "
                   f"becomes the chip. Re-run step 13 on the netlist step 15 "
                   f"routes.")
        elif _bind_state == _B_UNBOUND:
            rule = "LEC_SUBJECT_UNBOUND"
            msg = (f"{LEC_JSON_REL} records no sha256 for the gate netlist it "
                   f"proved (proof_identity.gate_netlist), so it cannot be "
                   f"shown to be about {binding.get('consumer_path')} "
                   f"({binding.get('consumer_sha256')}), the netlist step 15 "
                   f"routes. Re-run step 13 with lec_run.")
        else:
            rule = "LEC_SCAN_MODE_UNCONSTRAINED"
            msg = (f"step 15 routes the scan-inserted "
                   f"{binding.get('consumer_path')}, and the proof did not "
                   f"apply the functional-mode constraint from step 11's "
                   f"record (scan_functional_mode.applied is not true): scan "
                   f"enable was not tied inactive on the implementation side.")
        res.findings.append(Finding(rule=rule, severity="ERROR", message=msg,
                                    file=LEC_JSON_REL))
        res.passed = False
        res.inconclusive = False
        return res

    # --- (b0) #2068 — BUDGET EXHAUSTED WITH NO VERDICT: a terminal state of
    # its own, and the one state that is NOT waivable ----------------------
    # lec_run records `step_budget_exhausted` with `exhausted_resource` when
    # the step's declared budget ran out. That ceiling RECORDS, it never kills
    # (owner ruling on #2051), so the flag alone says nothing about the result:
    # a proof completed at 7300 s against a 7200 s budget is still a proof, and
    # (item 2 below) keeps its verdict with the overrun recorded as a note.
    #
    # What is NOT a result is an exhausted budget that left NOTHING decided.
    # Measured on opentitan_aes (lane rbaes2, 8HD-8, image 0.3.46): step 13 ran
    # 8553.69 s against a 7200 s budget, proved 830 of 4072 miter points, hit no
    # counterexample, established no base case, and was recorded INCONCLUSIVE.
    # The INCONCLUSIVE branches below then routed it to rc=3 + the
    # PASS_WITH_WAIVERS sentinel, flow_compliance promoted step 13 to
    # WAIVED-DEFERRED, and the completion audit credited the slot: the IC came
    # out PASS_WITH_WAIVERS on a step that decided nothing at all.
    #
    # A waiver is a decision to accept a KNOWN outcome. Here there is no
    # outcome: not a pass, not a fail, not a disclosed capability gap whose
    # shape is understood -- just a measurement that did not finish. So this
    # returns NOT_MEASURED, naming the resource that ran out, and main() gives
    # it rc=1 WITHOUT the waiver sentinel, so no consumer can promote it into a
    # waiver row. It is placed BEFORE (c0)/(d)/(d1)/(d2) precisely because those
    # are the branches that were laundering it.
    #
    # NO-LEAK, both directions: it fires only when the producer itself declared
    # exhaustion AND nothing was decided. A budget-exhausted run that proved
    # equivalence, or that produced a counterexample, falls straight through --
    # `verdict_was_decided` is the whole test -- and a run that never declared
    # exhaustion is untouched, so every existing verdict in this file stands.
    _exhausted = budget_exhausted_resource(lc)
    _decided = verdict_was_decided(lc, equivalent, non_equiv)
    # THE REMEDY MUST MATCH THE RESOURCE (vibe-ic#2182). This finding used to
    # end with "Re-run the step with a budget it can finish inside" whatever
    # the producer named, so a proof the kernel OOM-killed at a 48 GiB cgroup
    # limit was answered with advice about the clock. A remedy aimed at the
    # wrong resource is the same defect as the wrong label, one sentence later.
    _evidence = str(lc.get("exhausted_resource_evidence") or "").strip()
    if _exhausted == "memory_bytes":
        _remedy = ("The resource that ran out is MEMORY, not time: raising the "
                   "time budget cannot help, and the proof never reached a "
                   "deadline. Re-run it where the cgroup ceiling admits the "
                   "peak this proof needs -- measured, not guessed -- or close "
                   "the remainder with a method that does not unroll the whole "
                   "miter.")
    elif _exhausted in ("not_measured", "unnamed"):
        # vibe-ic#2182. `budget_exhausted_resource` deliberately refuses to
        # default an unrecorded resource to the clock -- see the comment on
        # `_EXHAUSTED_RESOURCE_KEYS`: "Never defaulted: an exhaustion whose
        # resource was not recorded is reported as unnamed, not as wall-clock."
        # The LABEL honoured that and the REMEDY did not: `"unnamed"` fell
        # through to the `else` branch and was answered with "re-run with a
        # bigger budget", i.e. the clock, one sentence after refusing to name
        # it. MEASURED on sha256 at v1.20.18: the producer recorded
        # `step_budget_exhausted: true` with `exhausted_resource: null` AND
        # `step_budget_stopped_this_proof: false` -- the budget never stopped
        # the proof; the ladder ran to its end and did not converge
        # (`induction_wall_kind: "induction_depth"`, `non_convergence: true`,
        # 1314/1612 proven, 298 unproven, 13050 s). A bigger budget cannot
        # help a run no budget stopped. An unnamed resource gets the same
        # discipline as an unmeasured one: establish the cause, do not assume.
        _remedy = ("WHICH resource ran out was NOT MEASURED, so no remedy is "
                   "named here: do not assume the clock. Establish the cause "
                   "first (the container cgroup's oom_kill counter settles "
                   "it), then repair the resource that actually ran out.")
        _wall = str(lc.get("induction_wall_kind") or "").strip()
        _stopped = lc.get("step_budget_stopped_this_proof")
        if _stopped is False:
            _remedy += (" The producer records "
                        "`step_budget_stopped_this_proof: false`, so no budget "
                        "stopped this proof -- raising one cannot change the "
                        "outcome.")
        if _wall:
            _remedy += (f" The producer DID record what the proof ran into: "
                        f"`induction_wall_kind: {_wall}`. Repair that, not the "
                        "ceiling.")
    else:
        _remedy = ("Re-run the step with a budget it can finish inside, or "
                   "close it with a sign-off LEC that reaches a verdict. The "
                   "budget itself stays a RECORDING ceiling -- do NOT shorten "
                   "it, and do NOT turn it into a kill.")
    if _evidence:
        _remedy += f" Evidence for the named resource: {_evidence}."
    if _exhausted is not None and not _decided:
        res.not_measured = True
        res.inconclusive = False
        res.passed = False
        res.exhausted_resource = _exhausted
        res.summary["not_measured"] = True
        res.summary["exhausted_resource"] = _exhausted
        res.findings.append(Finding(
            rule="LEC_BUDGET_EXHAUSTED", severity="ERROR",
            message=("LEC step budget was EXHAUSTED (resource: "
                     f"{_exhausted}) and NO verdict was reached: equivalence "
                     "was neither proven nor refuted, and no counterexample "
                     "was recorded. This is NOT_MEASURED -- a terminal state "
                     "of its own, not a result. It is NOT eligible for a "
                     "waiver row and must NOT be credited in the completion "
                     "audit: a waiver accepts a known outcome, and here there "
                     "is no outcome to accept. The IC cannot be "
                     "PASS_WITH_WAIVERS while this step stands. " + _remedy),
            file=LEC_JSON_REL))
        return res

    # #2068 item 2 — the overrun that did NOT cost a verdict. Recorded here so
    # a reader sees the ceiling was passed; it changes no verdict, and it is
    # deliberately NOT a Finding, because `res.passed` is `not res.findings`
    # and a recording ceiling must never void a real proof.
    if _exhausted is not None and _decided:
        res.budget_overrun = {"exhausted_resource": _exhausted,
                              "verdict_reached": True}
        res.summary["budget_overrun"] = res.budget_overrun

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
    # --- (d1) #2050 — THE MITER ITSELF WAS INCONSISTENT ---------------------
    # `equiv_induct` prints `Circuit inherently diverges!` when its BASE CASE
    # goes UNSAT. Read yosys's `passes/equiv/equiv_induct.cc`: the base case is
    #     ez->assume(all unproven key points equal at steps 1..k); ez->solve()
    # so UNSAT says there is NO trace in which the recipe's own key points can
    # all be equal for k consecutive cycles. That is a statement about the
    # MITER, not about induction depth, and a deeper `-seq` provably cannot
    # help — each rung only ADDS assumed-equal terms and adding clauses
    # preserves UNSAT (MEASURED on opentitan_aes: -seq 4/16/64 printed
    # byte-identical output, all three aborting at base-case step 2).
    #
    # Reporting this as "a disclosed sequential-depth capability gap ... close
    # with sign-off LEC" pointed the reader at the one remedy that cannot work:
    # a commercial sequential engine handed the same inconsistent miter has the
    # same nothing to prove. The usual cause is a key point that is NOT the
    # same signal on the two sides — most often `synth`'s `fsm_recode`
    # re-encoding an FSM state register while the recipe matched the old and
    # new encodings positionally by name.
    #
    # Still INCONCLUSIVE and still non-blocking — this names the cause, it does
    # not change the pass/fail direction. NO-LEAK: `induction_wall_kind` is ""
    # on every log without a flat-wall signature (every PASS, every
    # counterexample FAIL), so no existing verdict moves; a producer that never
    # recorded the field falls through to (d2) exactly as before.
    if (is_inconclusive and (non_equiv in (None, 0))
            and str(lc.get("induction_wall_kind", "")) == "miter_inconsistent"):
        res.inconclusive = True
        res.passed = False
        res.findings.append(Finding(
            rule="LEC_INCONCLUSIVE_MITER_INCONSISTENT", severity="WARNING",
            message=("LEC verdict is INCONCLUSIVE — equiv_induct's SAT BASE "
                     f"CASE went UNSAT (`Circuit inherently diverges!`) with "
                     f"{unproven} point(s) unproven. The base case asks whether "
                     "the miter's own unproven key points CAN all be equal for "
                     "k consecutive cycles; UNSAT means they cannot, so at "
                     "least one matched pair is not the same signal on the two "
                     "sides. This is NOT a sequential-depth gap: a deeper -seq "
                     "only adds assumed-equal terms and preserves UNSAT, and a "
                     "sign-off LEC engine handed the same miter has the same "
                     "nothing to prove. Check first whether synthesis "
                     "re-encoded an FSM state register (yosys `fsm_recode`); if "
                     "so the fix is `synth -encfile <f>` plus `equiv_make "
                     "-encfile <f>`, which matches the two encodings instead of "
                     "matching them positionally by name. Visible non-PASS "
                     "(never a vacuous PASS)."),
            file=LEC_JSON_REL))
        return res

    # --- (d2) ----------------------------------------------------------------
    if is_inconclusive and (non_equiv in (None, 0)):
        res.inconclusive = True
        res.passed = False
        res.findings.append(Finding(
            rule="LEC_INCONCLUSIVE_NONCONVERGENCE", severity="WARNING",
            message=("LEC verdict is INCONCLUSIVE — a completed equivalence "
                     f"miter left {unproven} point(s) unproven, but equiv_induct "
                     "did NOT converge (a flat induction wall). This is "
                     "INCONCLUSIVE, NOT NOT_EQUIVALENT — a disclosed "
                     "sequential-depth capability gap. Close with sign-off LEC "
                     "(Conformal/VC LEC), which handles deep sequential "
                     "induction. NOTE on `non_equivalent_points: 0` — ON THE "
                     "YOSYS PATH that zero is not evidence: no pass in yosys's "
                     "passes/equiv emits a counterexample, and lec_run.py "
                     "hardcodes that field to 0 for this tool, so a genuine "
                     "difference surfaces as an UNPROVEN point, i.e. inside the "
                     "count above. (A sign-off LEC report CAN carry a real "
                     "count, and there the field means what it says.) Visible "
                     "non-PASS (never a vacuous PASS)."),
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
# The not-run record a bound proof supersedes
# ---------------------------------------------------------------------------
# P2LECIN follow-up. On a from-documents run phase 2 reaches step 13 before
# phase 3's synthesis half has written the netlist step 15 routes, so step 13
# records NOT_MEASURED (input_absent) and writes `LEC_NOT_RUN_REL`
# (verdict SKIPPED-CONDITION). Phase 3 then proves that netlist and
# `reports/lec.json` binds it. The record stayed on disk: nothing reads it by
# name, but the directory-level self-skip scans read every `*.json` in
# `reports/` (flow_compliance_check `_sibling_self_skip_for_missing`,
# flow_dashboard_data `_disclosed_skip`) and would publish the phase-2
# "not measured" beside a proof that settled it.
#
# "Superseded" is THIS gate's answer, not a second rule: `audit` passes the
# proof (equivalent, points proven, none unproven or non-equivalent) AND its
# sha256 binds the netlist step 15 routes (MATCH). A stale proof, a
# non-equivalent result, an inconclusive one or no proof at all supersedes
# nothing, so a real not-run still reports NOT_MEASURED.


def bound_proof(project: Path) -> Optional[dict]:
    """The subject binding of the Step-13 proof on disk when that proof
    settles step 13 -- `audit(...).passed` and binding state MATCH -- else
    None. Never raises: an unanswerable question supersedes nothing."""
    project = Path(project)
    if not (project / LEC_JSON_REL).is_file():
        return None
    try:
        res = audit(project)
    except Exception:  # noqa: BLE001 — fail closed: the not-run stands
        return None
    binding = res.summary.get("subject_binding") or {}
    if res.passed and binding.get("state") == _B_MATCH:
        return binding
    return None


def lec_not_run_superseded(project: Path, record: Path) -> Optional[str]:
    """Reader side: why `record` no longer speaks for step 13, or None.

    Non-None only when `record` IS step 13's not-run record and a bound proof
    exists; every other file -- another step's skip record in the same
    directory included -- is not this proof's to excuse."""
    project = Path(project)
    try:
        if Path(record).resolve() != (project / LEC_NOT_RUN_REL).resolve():
            return None
    except OSError:
        return None
    binding = bound_proof(project)
    if binding is None:
        return None
    return (f"{LEC_NOT_RUN_REL} is superseded by {LEC_JSON_REL}, a passing "
            f"proof bound to {binding.get('consumer_path')} "
            f"({binding.get('consumer_sha256')}), the netlist step 15 routes")


def retire_superseded_not_run(project: Path) -> Optional[str]:
    """Writer side: remove step 13's not-run record once a bound proof
    supersedes it, and say so. Returns the note, or None when nothing was
    retired (no record, or no bound proof -- a real not-run is kept). Never
    raises: hygiene must not break a successful step."""
    project = Path(project)
    record = project / LEC_NOT_RUN_REL
    if not record.is_file():
        return None
    note = lec_not_run_superseded(project, record)
    if note is None:
        return None
    try:
        record.unlink()
    except OSError:
        return None
    return f"retired {note}"


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

    # #2068 — NOT_MEASURED: the budget ran out and nothing was decided. rc=1,
    # and — the load-bearing half — WITHOUT the `PASS_WITH_WAIVERS` sentinel,
    # so `flow_compliance_check._check_program_exit_zero` cannot promote it to
    # WAIVED-DEFERRED. The non-waivable token is printed LAST and SHORT for the
    # same reason the waiver sentinel is: the consumer reads only the trailing
    # 300 chars of stdout and requires the token at line-start, so a long line
    # would be sliced mid-string and the disclosure would be lost.
    if result.not_measured:
        if result.evidence_source in ('adopted_native_eqy', 'native_eqy'):
            print('NOT_MEASURED_NON_WAIVABLE: native LEC consumer did not accept')
            return 1
        print(f"LEC NOT_MEASURED: step budget exhausted "
              f"(resource: {result.exhausted_resource}) with no verdict — "
              f"nothing was decided, so nothing can be waived.")
        print(f"NOT_MEASURED_NON_WAIVABLE: LEC_BUDGET_EXHAUSTED "
              f"({result.exhausted_resource})")
        return 1

    if result.budget_overrun:
        # A recording ceiling that recorded. The verdict below is unaffected.
        print(f"NOTE: step budget exhausted (resource: "
              f"{result.budget_overrun.get('exhausted_resource')}) but a real "
              f"verdict was reached — the overrun is recorded, not acted on.")

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
