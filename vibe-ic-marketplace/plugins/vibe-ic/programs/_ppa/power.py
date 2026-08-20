#!/usr/bin/env python3
"""_ppa/power.py — the power split, and the thing that makes a power number
mean anything: WHERE THE ACTIVITY CAME FROM.

Spec §7.2. Owns exactly one question: given a power artefact, what are the
internal / switching / leakage / total figures, and on what ACTIVITY BASIS were
they computed. Nothing here decides a verdict against a threshold — that is the
gate's job (`power_total_vs_budget_check`), and keeping the two apart is why
adding a second power engine will not change a single rule.

WHY THE BASIS IS NOT A FOOTNOTE
===============================
A vectorless estimate and a VCD-driven measurement are both "total power" and
they are not the same number. `PPA_INTERFACES.md` §2 says so in one line —
"Vectorless power and VCD power are different metrics" — and the consequence is
the whole of this module: two power records whose activity basis differs are
NOT COMPARABLE, and a comparison across them is UNDETERMINED, never a winner.
The failure mode this prevents is the cheapest possible win: run the candidate
vectorless, run the baseline against a VCD, and report an improvement that is
an artefact of the activity model.

AND A DECLARED BASIS IS A CLAIM, NOT EVIDENCE
=============================================
MEASURED on the published corpus 2026-08-21, all 17 runs carrying a power
report:

    POWER_ANALYSIS_MODE absent           6
    POWER_ANALYSIS_MODE: vectorless_sdc  3
    POWER_ANALYSIS_MODE: vector_vcd      8

and every one of those 8 is contradicted by its OWN transcript — 5 carry
``READ_VCD_FAIL: ...`` from the `catch` around `read_power_activities`, and 3
carry OpenSTA's own count, ``Annotated 0 pin activities.``. Zero published power
numbers in this repository are vector-driven; eight of them say they are. The
label is written by the runner from the mere EXISTENCE of a `.vcd` file, before
the read is attempted, and the read failure is caught and printed rather than
raised — so `vector_vcd` in these files records an intention.

Therefore this module never takes the declared mode as the answer. It reads the
mode, then reads the evidence that would corroborate or falsify it, and returns
a basis with the corroboration state attached. A vector basis contradicted by
its own transcript is `CONTRADICTED`, the record is `INVALID` per §2, and an
INVALID record may not enter a numeric comparison. That is a REFUSAL, not a
reclassification: this module will not silently re-label such a run
"vectorless", because what the tool actually did with zero annotated activities
is a claim about OpenSTA's fallback that this repository has not measured.

WHAT AN ABSENT BASIS IS
=======================
`UNSTATED`, and UNSTATED is not comparable with anything — INCLUDING another
UNSTATED. Two numbers whose activity models are both unknown are not known to
share an activity model. Treating "unknown == unknown" as a match is exactly
the numeric-sentinel defect §2 forbids, one level up: it turns "not measured"
into a value that participates in arithmetic.

IR DROP IS NOT TOTAL POWER
==========================
Nothing here reads an IR-drop artefact. Peak-current and voltage-droop belong
to power integrity (`ir_drop_*`, `em_peak_current_authority_check`) and answer
a different question; a per-net total power stated by an IR engine on a
different netlist view is a different metric with a different scope and must not
be folded into this axis. On the corpus the two already differ by 4.3x at
baseline, so any tolerance wide enough to reconcile them would be a ruler
fitted to the data.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import canonical_json as _cj

__all__ = [
    "SCHEMA_METRIC", "PARSER",
    "BASIS_VCD", "BASIS_SAIF", "BASIS_VECTORLESS", "BASIS_UNSTATED",
    "BASIS_CONTRADICTED", "KNOWN_BASES",
    "CORROBORATED", "UNCORROBORATED", "CONTRADICTED", "NO_CORROBORATION_NEEDED",
    "STATUS_MEASURED", "STATUS_NOT_MEASURED", "STATUS_INVALID", "STATUS_DERIVED",
    "CATEGORIES", "TOTAL_GROUP",
    "activity_provenance", "parse_power_report", "read_power_report",
    "metric_records", "total_record", "comparable", "compare_total_power",
    "V_A_LOWER", "V_B_LOWER", "V_EQUAL", "V_UNDETERMINED",
]

SCHEMA_METRIC = "vibeic.ppa.metric.v1"
PARSER = "_ppa/power.py"

# ── the activity basis vocabulary ──────────────────────────────────────────
#: A vector-driven measurement whose activity came from a value-change dump.
BASIS_VCD = "VCD"
#: A vector-driven measurement whose activity came from a SAIF activity file.
BASIS_SAIF = "SAIF"
#: A vectorless estimate: activity propagated from the constraints, not observed.
BASIS_VECTORLESS = "VECTORLESS"
#: The artefact states no basis at all. NOT comparable, not even with another
#: UNSTATED — see the module docstring.
BASIS_UNSTATED = "UNSTATED"
#: The artefact states a basis its own transcript falsifies.
BASIS_CONTRADICTED = "CONTRADICTED"

#: The only bases a numeric comparison may run across.
KNOWN_BASES = (BASIS_VCD, BASIS_SAIF, BASIS_VECTORLESS)

CORROBORATED = "CORROBORATED"
UNCORROBORATED = "UNCORROBORATED"
CONTRADICTED = "CONTRADICTED"
NO_CORROBORATION_NEEDED = "NO_CORROBORATION_NEEDED"

# ── §2 record statuses used here ───────────────────────────────────────────
STATUS_MEASURED = "MEASURED"
STATUS_NOT_MEASURED = "NOT_MEASURED"
STATUS_INVALID = "INVALID"
STATUS_DERIVED = "DERIVED"

#: The four figures every `report_power` row carries, in the tool's own order.
CATEGORIES = ("internal", "switching", "leakage", "total")
TOTAL_GROUP = "Total"

#: metric names, one per category. Watts, because that is the unit the artefact
#: states; converting to uW here would make every record DERIVED for no gain.
_METRIC_NAME = {c: f"power.{c}_w" for c in CATEGORIES}

# ── parsing ────────────────────────────────────────────────────────────────
_NUM = r"[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?"
#: A `report_power` row: a group label then four figures, optionally a percent.
_ROW_RE = re.compile(
    r"^[ \t]*(?P<group>[A-Za-z][A-Za-z0-9_ /-]*?)[ \t]+"
    r"(?P<internal>" + _NUM + r")[ \t]+"
    r"(?P<switching>" + _NUM + r")[ \t]+"
    r"(?P<leakage>" + _NUM + r")[ \t]+"
    r"(?P<total>" + _NUM + r")\b", re.M)

_MODE_RE = re.compile(r"^POWER_ANALYSIS_MODE:[ \t]*(?P<mode>\S+)", re.M)
#: OpenSTA's own count of what the activity read actually annotated. This is
#: the ONLY positive evidence in the artefact that a vector basis is real.
_ANNOTATED_RE = re.compile(
    r"^.*?Annotated[ \t]+(?P<n>\d+)[ \t]+pin[ \t]+activit(?:y|ies)\b", re.M)
#: The runner catches a failed activity read and PRINTS it, so a report can
#: state a vector basis and carry the failure of the read that would have
#: produced it, three lines apart.
_FAIL_RE = re.compile(
    r"^(?P<line>(?:READ_VCD_FAIL|READ_SAIF_FAIL|REPORT_POWER_FAIL):.*)$", re.M)
#: The tool's own banner, used for `source.tool_version`. Never for a verdict.
_TOOL_RE = re.compile(r"^(?P<tool>OpenSTA)[ \t]+(?P<version>\S+)", re.M)

#: What a declared mode token means. Unrecognised tokens are UNSTATED, not
#: guessed — a mode this module does not know is a mode it cannot corroborate.
_DECLARED_BASIS = {
    "vector_vcd": BASIS_VCD,
    "vcd": BASIS_VCD,
    "vector_saif": BASIS_SAIF,
    "saif": BASIS_SAIF,
    "vectorless_sdc": BASIS_VECTORLESS,
    "vectorless": BASIS_VECTORLESS,
    "propagated": BASIS_VECTORLESS,
}
_VECTOR_BASES = (BASIS_VCD, BASIS_SAIF)

#: Category figures are printed to three significant digits, so a row's three
#: components sum to its total only to about that. This tolerance exists for a
#: DISCLOSURE, never for a verdict.
_SUM_RTOL = 0.02


def _num(tok: Any) -> Optional[float]:
    try:
        f = float(tok)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # NaN is not a measurement


def _lineno(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def activity_provenance(text: str) -> Dict[str, Any]:
    """Where this report's switching activity came from — from EVIDENCE.

    Returns a dict with the declared mode, the corroborating and falsifying
    evidence found beside it, and the resolved `basis` / `corroboration`. It
    never returns a bare string, because "VCD" on its own is the claim this
    module exists to stop taking at face value.
    """
    evidence: List[Dict[str, Any]] = []

    m = _MODE_RE.search(text)
    declared_token = m.group("mode") if m else None
    if m:
        evidence.append({"kind": "declared_mode", "line": _lineno(text, m.start()),
                         "text": m.group(0).strip()})
    declared = _DECLARED_BASIS.get((declared_token or "").lower())

    annotated: Optional[int] = None
    for am in _ANNOTATED_RE.finditer(text):
        n = int(am.group("n"))
        annotated = n if annotated is None else annotated + n
        evidence.append({"kind": "annotated_pin_activities",
                         "line": _lineno(text, am.start()),
                         "text": am.group(0).strip()})

    failures: List[str] = []
    for fm in _FAIL_RE.finditer(text):
        failures.append(fm.group("line").strip())
        evidence.append({"kind": "activity_read_failure",
                         "line": _lineno(text, fm.start()),
                         "text": fm.group("line").strip()})

    prov: Dict[str, Any] = {
        "declared_mode": declared_token,
        "declared_basis": declared,
        "annotated_pin_activities": annotated,
        "read_failures": failures,
        "evidence": evidence,
    }

    if declared is None:
        # No mode line, or a token this module does not know. Either way the
        # artefact does not say, and "does not say" is not "vectorless".
        prov["basis"] = BASIS_UNSTATED
        prov["corroboration"] = NO_CORROBORATION_NEEDED
        prov["reason"] = (
            "the artefact states no activity basis"
            if declared_token is None else
            f"the artefact states an activity basis this parser does not "
            f"recognise: {declared_token!r}")
        return prov

    if declared in _VECTOR_BASES:
        if failures:
            prov["basis"] = BASIS_CONTRADICTED
            prov["corroboration"] = CONTRADICTED
            prov["reason"] = (
                f"the artefact declares {declared} activity and carries the "
                f"failure of the read that would have produced it: "
                f"{failures[0]}")
            return prov
        if annotated == 0:
            prov["basis"] = BASIS_CONTRADICTED
            prov["corroboration"] = CONTRADICTED
            prov["reason"] = (
                f"the artefact declares {declared} activity and the tool "
                f"reports it annotated 0 pin activities")
            return prov
        if annotated is None:
            prov["basis"] = declared
            prov["corroboration"] = UNCORROBORATED
            prov["reason"] = (
                f"the artefact declares {declared} activity and carries no "
                f"annotated-activity count to corroborate it")
            return prov
        prov["basis"] = declared
        prov["corroboration"] = CORROBORATED
        prov["reason"] = (f"{annotated} pin activities annotated")
        return prov

    # Declared vectorless. The mirror case is real: a report that says
    # vectorless while the tool annotated activities is just as wrong about
    # itself as the other direction, and stating one and not the other would
    # make the check depend on which lie was told.
    if annotated:
        prov["basis"] = BASIS_CONTRADICTED
        prov["corroboration"] = CONTRADICTED
        prov["reason"] = (
            f"the artefact declares vectorless activity and the tool reports "
            f"it annotated {annotated} pin activities")
        return prov
    prov["basis"] = BASIS_VECTORLESS
    prov["corroboration"] = NO_CORROBORATION_NEEDED
    prov["reason"] = "vectorless is the tool default; there is nothing to read"
    return prov


def parse_power_report(text: str, *, path: Optional[str] = None,
                       sha256: Optional[str] = None) -> Dict[str, Any]:
    """Parse one `report_power` artefact into rows plus activity provenance.

    Returns a dict; `rows` is a list of group rows in the order the artefact
    states them, `total_row` is the `Total` row or None. Figures are the values
    PARSED — the raw token is kept beside each one so a consumer can hash what
    the tool wrote rather than what a float round-tripped to (§3).
    """
    rows: List[Dict[str, Any]] = []
    for m in _ROW_RE.finditer(text):
        group = m.group("group").strip()
        row: Dict[str, Any] = {"group": group, "line": _lineno(text, m.start())}
        ok = True
        for c in CATEGORIES:
            v = _num(m.group(c))
            if v is None:
                ok = False
                break
            row[f"{c}_w"] = v
            row[f"{c}_raw"] = m.group(c)
        if ok:
            rows.append(row)

    total_rows = [r for r in rows if r["group"].lower() == TOTAL_GROUP.lower()]
    group_rows = [r for r in rows if r["group"].lower() != TOTAL_GROUP.lower()]

    tm = _TOOL_RE.search(text)
    out: Dict[str, Any] = {
        "path": path,
        "sha256": sha256,
        "tool": (tm.group("tool").lower() if tm else None),
        "tool_version": (tm.group("version") if tm else None),
        "activity": activity_provenance(text),
        "rows": group_rows,
        "total_row": total_rows[0] if total_rows else None,
        "total_rows_seen": len(total_rows),
    }
    out["split_consistency"] = _split_consistency(out)
    out["group_sum_consistency"] = _group_sum_consistency(out)
    return out


def read_power_report(path: Path) -> Optional[Dict[str, Any]]:
    """`parse_power_report` on a file, with the file's own sha256 attached.

    Returns None when the file cannot be READ. The caller must not conflate
    that with a file that was read and held nothing: those are different facts
    and this repository has paid for treating them the same.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    return parse_power_report(raw.decode("utf-8", errors="replace"),
                              path=str(path),
                              sha256="sha256:" + hashlib.sha256(raw).hexdigest())


def _split_consistency(report: Dict[str, Any]) -> Dict[str, Any]:
    """Does internal + switching + leakage reach the row's own total?

    A DISCLOSURE. It is not a verdict and it is deliberately not one: the
    mutation this axis was written against
    (`matrix_mutation_ledger.ART-POWER-FIGURES-X1000`) multiplies every non-zero
    figure by 1000 and therefore PRESERVES this property exactly. A check that
    the mutation cannot move is not a check that discriminates.
    """
    t = report.get("total_row")
    if not t:
        return {"status": STATUS_NOT_MEASURED,
                "reason": "the artefact states no Total row"}
    parts = t["internal_w"] + t["switching_w"] + t["leakage_w"]
    total = t["total_w"]
    if total == 0:
        return {"status": STATUS_DERIVED, "formula":
                "internal_w + switching_w + leakage_w", "sum_w": parts,
                "total_w": total, "consistent": parts == 0,
                "note": "total is zero; a relative tolerance does not apply"}
    return {"status": STATUS_DERIVED,
            "formula": "internal_w + switching_w + leakage_w",
            "sum_w": parts, "total_w": total,
            "relative_error": abs(parts - total) / abs(total),
            "tolerance": _SUM_RTOL,
            "consistent": abs(parts - total) <= _SUM_RTOL * abs(total)}


def _group_sum_consistency(report: Dict[str, Any]) -> Dict[str, Any]:
    """Do the group rows reach the Total row? Same disclosure, same reason."""
    t = report.get("total_row")
    rows = report.get("rows") or []
    if not t or not rows:
        return {"status": STATUS_NOT_MEASURED,
                "reason": "the artefact states no Total row"
                          if not t else "the artefact states no group rows"}
    parts = sum(r["total_w"] for r in rows)
    total = t["total_w"]
    if total == 0:
        return {"status": STATUS_DERIVED, "formula": "sum(group.total_w)",
                "sum_w": parts, "total_w": total, "consistent": parts == 0}
    return {"status": STATUS_DERIVED, "formula": "sum(group.total_w)",
            "sum_w": parts, "total_w": total,
            "relative_error": abs(parts - total) / abs(total),
            "tolerance": _SUM_RTOL,
            "consistent": abs(parts - total) <= _SUM_RTOL * abs(total)}


# ── canonical records ──────────────────────────────────────────────────────
def _parser_sha256() -> str:
    try:
        return "sha256:" + hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest()
    except OSError:                                   # pragma: no cover
        return "sha256:unavailable"


def _source(report: Dict[str, Any]) -> Dict[str, Any]:
    return {"path": report.get("path"), "sha256": report.get("sha256"),
            "tool": report.get("tool"), "tool_version": report.get("tool_version"),
            "parser": PARSER, "parser_sha256": _parser_sha256()}


def _record(metric: str, status: str, value: Optional[float],
            scope: Dict[str, Any], source: Dict[str, Any], *,
            raw: Optional[str] = None, reason: Optional[str] = None
            ) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"schema": SCHEMA_METRIC, "metric": metric,
                           "status": status, "unit": "W", "scope": scope,
                           "source": source}
    if status in (STATUS_MEASURED, STATUS_DERIVED):
        rec["value"] = value
        if raw is not None:
            rec["value_raw"] = raw
    else:
        # §2: a not-measured record carries a reason, NOT a value. No 0, no -1,
        # no "". The row is printed, never omitted.
        rec["reason"] = reason or "not stated by the artefact"
    return rec


def metric_records(report: Dict[str, Any], *, stage: str = "unknown",
                   scenario: str = "default",
                   extra_scope: Optional[Dict[str, Any]] = None
                   ) -> List[Dict[str, Any]]:
    """Every figure the artefact states, as `vibeic.ppa.metric.v1` records.

    One record per (group, category), plus the Total group. Every record's
    scope carries `activity_basis`, because a power number without one is not a
    comparable fact. A record whose basis is CONTRADICTED is `INVALID` — §2:
    "the artefact exists but cannot support the metric".
    """
    act = report.get("activity") or {}
    basis = act.get("basis", BASIS_UNSTATED)
    src = _source(report)
    base_scope = {"stage": stage, "scenario": scenario,
                  "activity_basis": basis,
                  "activity_corroboration": act.get("corroboration"),
                  "tool": report.get("tool")}
    if extra_scope:
        base_scope.update(extra_scope)

    rows = list(report.get("rows") or [])
    if report.get("total_row"):
        rows.append(report["total_row"])

    out: List[Dict[str, Any]] = []
    if not rows:
        for c in CATEGORIES:
            out.append(_record(
                _METRIC_NAME[c], STATUS_NOT_MEASURED, None,
                dict(base_scope, group=TOTAL_GROUP), src,
                reason="the artefact states no power rows"))
        return out

    invalid = basis == BASIS_CONTRADICTED
    for r in rows:
        scope = dict(base_scope, group=r["group"])
        for c in CATEGORIES:
            out.append(_record(
                _METRIC_NAME[c],
                STATUS_INVALID if invalid else STATUS_MEASURED,
                r[f"{c}_w"], scope, src, raw=r[f"{c}_raw"],
                reason=act.get("reason") if invalid else None))
    return out


def total_record(report: Dict[str, Any], **kw: Any) -> Optional[Dict[str, Any]]:
    """The one record a budget comparison is entitled to use, or None.

    None means the artefact states no Total row — which the caller must report
    as NOT MEASURED, never as zero power.
    """
    if not report.get("total_row"):
        return None
    for rec in metric_records(report, **kw):
        if rec["metric"] == _METRIC_NAME["total"] and \
                rec["scope"].get("group", "").lower() == TOTAL_GROUP.lower():
            return rec
    return None                                        # pragma: no cover


# ── comparability ──────────────────────────────────────────────────────────
V_A_LOWER = "A_LOWER"
V_B_LOWER = "B_LOWER"
V_EQUAL = "EQUAL"
V_UNDETERMINED = "UNDETERMINED"

#: Scope keys that must MATCH before two power numbers are one comparison.
#: `activity_basis` is first because it is the one that is easiest to fake.
COMPARABLE_SCOPE_KEYS: Tuple[str, ...] = ("activity_basis", "stage", "scenario")


def comparable(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[bool, str]:
    """`(is_comparable, reason)` for two `vibeic.ppa.metric.v1` records.

    The refusals, in the order they are checked:
      * a record that is not MEASURED may not enter a numeric comparison (§2);
      * a basis outside the known set — UNSTATED or CONTRADICTED — is not a
        basis, and UNSTATED does not match another UNSTATED;
      * differing scope is a different metric, not a worse result.
    """
    for name, rec in (("A", a), ("B", b)):
        if rec.get("metric") != _METRIC_NAME["total"]:
            return False, (f"{name} is {rec.get('metric')!r}, not "
                           f"{_METRIC_NAME['total']!r}")
        if rec.get("status") != STATUS_MEASURED:
            return False, (f"{name} is {rec.get('status')}, and only MEASURED "
                           f"records may enter a numeric comparison"
                           + (f": {rec['reason']}" if rec.get("reason") else ""))
    for name, rec in (("A", a), ("B", b)):
        basis = (rec.get("scope") or {}).get("activity_basis")
        if basis not in KNOWN_BASES:
            return False, (
                f"{name} has activity basis {basis!r}; two numbers whose "
                f"activity models are unknown are not known to share one")
    for key in COMPARABLE_SCOPE_KEYS:
        av = (a.get("scope") or {}).get(key)
        bv = (b.get("scope") or {}).get(key)
        if av != bv:
            return False, (f"scope.{key} differs: {av!r} vs {bv!r} — these are "
                           f"different metrics, so the comparison is "
                           f"UNDETERMINED and not a winner")
    return True, "scope matches on " + ", ".join(COMPARABLE_SCOPE_KEYS)


def compare_total_power(a: Dict[str, Any], b: Dict[str, Any], *,
                        rel_tol: float = 0.0) -> Dict[str, Any]:
    """Which of two total-power records is lower, or UNDETERMINED.

    `rel_tol` is a dead band around equality, expressed relative to the larger
    magnitude. It defaults to 0: this function does not invent a noise floor,
    because a tolerance nobody declared turns an unanswered question into an
    answered one.
    """
    ok, reason = comparable(a, b)
    if not ok:
        return {"verdict": V_UNDETERMINED, "code": "NOT_COMPARABLE",
                "reason": reason}
    av, bv = a["value"], b["value"]
    band = rel_tol * max(abs(av), abs(bv))
    if abs(av - bv) <= band:
        verdict = V_EQUAL
    else:
        verdict = V_A_LOWER if av < bv else V_B_LOWER
    return {"verdict": verdict, "code": "COMPARED", "reason": reason,
            "a_value_w": av, "b_value_w": bv,
            "activity_basis": a["scope"]["activity_basis"],
            "delta_w": bv - av, "rel_tol": rel_tol}


def digest(obj: Any) -> str:
    """The identity of a power document. One serializer, always (§3)."""
    return _cj.digest_of(obj)


# ── the requirement side: a budget is a CONTRACT term, not a constant ──────
#: The document that may declare a power requirement. `PPA_INTERFACES.md` §4
#: gives `_ppa/contract.py` to the contract lane; until that module lands with
#: a loader, this reads the frozen document SHAPE directly and nothing else, so
#: the swap is one function body.
CONTRACT_SCHEMA = "vibeic.ppa.contract.v1"
#: Where a PPA contract may sit. DISCOVERED, never enumerated by design name.
CONTRACT_GLOBS: Tuple[str, ...] = (
    "ppa_contract*.json", "**/ppa_contract*.json",
    "**/*.ppa.contract.json", "contracts/ppa/*.json",
    "phase1/**/PPA_CONTRACT*.json",
)
#: The L-document the flow has always carried. It is a LOWER authority than a
#: PPA contract and it declares no activity basis, which is exactly why the
#: contract exists.
L19_GLOBS: Tuple[str, ...] = (
    "phase1/**/L19*.json", "generated_docs/L19*.json",
    "**/L19_CONSTRAINTS_PDK.json",
)

AUTHORITY_CONTRACT = "ppa_contract"
AUTHORITY_L19 = "L19.power_budget_uw"
AUTHORITY_CLI = "--budget-uw"

_MICRO = 1e-6
#: The metric names a power requirement may be written against, and the factor
#: that takes the stated limit to Watts. A requirement in any other unit is not
#: silently converted — it is reported as unreadable.
_REQ_METRIC_TO_W = {"power.total_w": 1.0, "power.total_uw": _MICRO}
_REQ_UNIT_TO_W = {"W": 1.0, "w": 1.0, "uW": _MICRO, "uw": _MICRO,
                  "µW": _MICRO, "microwatt": _MICRO}


def _discover(project: Path, globs: Sequence[str]) -> List[Path]:
    seen: Dict[str, Path] = {}
    for pat in globs:
        for p in project.glob(pat):
            if p.is_file():
                seen[str(p.resolve())] = p
    return [seen[k] for k in sorted(seen)]


def _rel(p: Path, project: Path) -> str:
    try:
        return str(p.relative_to(project))
    except ValueError:                                 # pragma: no cover
        return str(p)


def _load_json(p: Path) -> Optional[Any]:
    import json
    try:
        return json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return None


def contract_power_requirements(project: Path) -> List[Dict[str, Any]]:
    """Every total-power requirement stated by a `vibeic.ppa.contract.v1` doc.

    A document that does not carry the schema key is not a contract and is
    ignored — silently guessing that some other JSON "looks like" a contract is
    how an authority nobody declared gets invented.
    """
    out: List[Dict[str, Any]] = []
    for fp in _discover(project, CONTRACT_GLOBS):
        doc = _load_json(fp)
        if not isinstance(doc, dict) or doc.get("schema") != CONTRACT_SCHEMA:
            continue
        reqs = doc.get("requirements")
        if not isinstance(reqs, list):
            continue
        for req in reqs:
            if not isinstance(req, dict):
                continue
            metric = req.get("metric")
            if metric not in _REQ_METRIC_TO_W:
                continue
            limit = req.get("limit")
            raw_max = limit.get("max") if isinstance(limit, dict) else None
            val = _num(raw_max)
            unit = req.get("unit")
            factor = _REQ_UNIT_TO_W.get(unit) if unit is not None \
                else _REQ_METRIC_TO_W[metric]
            entry: Dict[str, Any] = {
                "file": _rel(fp, project), "authority": AUTHORITY_CONTRACT,
                "metric": metric, "unit": unit,
                "scope": req.get("scope") if isinstance(req.get("scope"), dict)
                         else {},
                "declared_by": req.get("authority"),
            }
            if val is None or val <= 0 or factor is None:
                entry["max_w"] = None
                entry["max_uw"] = None
                entry["unreadable"] = (
                    f"limit.max={raw_max!r} unit={unit!r} is not a positive "
                    f"power in a unit this parser knows")
            else:
                entry["max_w"] = val * factor
                # §3: report the value PARSED, not one round-tripped through a
                # unit conversion. 1000.0 uW -> W -> uW is 1000.0000000000001,
                # and an identity taken over that is an identity over an
                # arithmetic artefact.
                entry["max_uw"] = val if factor == _MICRO else val / _MICRO
            out.append(entry)
    return out


def l19_power_budgets(project: Path) -> List[Dict[str, Any]]:
    """Every published L19 copy's `power_budget_uw`, read as stated.

    Every copy is read. Phase 1 publishes the same document into several
    directories, and taking the first would make the verdict depend on glob
    order.
    """
    out: List[Dict[str, Any]] = []
    for fp in _discover(project, L19_GLOBS):
        doc = _load_json(fp)
        if not isinstance(doc, dict):
            continue
        fields = doc.get("fields")
        raw = fields.get("power_budget_uw") if isinstance(fields, dict) else None
        if raw is None and "power_budget_uw" in doc:
            raw = doc.get("power_budget_uw")
        val = _num(raw)
        out.append({"file": _rel(fp, project), "authority": AUTHORITY_L19,
                    "metric": "power.total_uw", "unit": "uW",
                    "power_budget_uw": val,
                    "max_w": val * _MICRO if val is not None and val > 0
                             else None,
                    "max_uw": val if val is not None and val > 0 else None,
                    # An L-document states no activity basis. That is not a
                    # defect in the document; it is the reason a requirement
                    # read from it cannot police the basis of the number it
                    # judges, and the verdict says so.
                    "scope": {}})
    return out


def resolve_power_requirement(project: Path, *,
                              budget_uw: Optional[float] = None
                              ) -> Dict[str, Any]:
    """The single total-power requirement in force, or a stated refusal.

    Authority order, highest first:

      1. `--budget-uw` — an explicit caller-supplied requirement. A caller that
         states one has taken the authority on itself, and is entitled to.
      2. A `vibeic.ppa.contract.v1` requirement on `power.total_w`.
      3. L19 `fields.power_budget_uw`.

    A higher authority SUPERSEDES a lower one and the superseded value is
    disclosed, not discarded — a contract exists so that it can override the
    flow's default, and treating any disagreement with a lower document as
    fatal would make declaring one impossible. Disagreement WITHIN one level is
    different: two copies of one authority stating two numbers is not an
    authority, and that refuses.

    Returns `{"requirement": <dict|None>, "sources": [...], "refusal": <str|None>}`.
    """
    sources: List[Dict[str, Any]] = []
    contract_reqs = contract_power_requirements(project)
    l19 = l19_power_budgets(project)
    sources.extend(contract_reqs)
    sources.extend(l19)

    if budget_uw is not None:
        req = {"authority": AUTHORITY_CLI, "file": AUTHORITY_CLI,
               "metric": "power.total_uw", "unit": "uW",
               "max_w": budget_uw * _MICRO, "max_uw": budget_uw,
               "scope": {}}
        sources.insert(0, req)
        return {"requirement": req, "sources": sources, "refusal": None,
                "superseded": [s for s in (contract_reqs + l19)
                               if s.get("max_w") is not None]}

    readable = [r for r in contract_reqs if r.get("max_w") is not None]
    if readable:
        distinct = sorted({r["max_w"] for r in readable})
        if len(distinct) > 1:
            return {"requirement": None, "sources": sources,
                    "refusal": (f"{CONTRACT_SCHEMA} copies state different "
                                f"total-power limits (W): {distinct}"),
                    "superseded": []}
        return {"requirement": readable[0], "sources": sources,
                "refusal": None,
                "superseded": [s for s in l19 if s.get("max_w") is not None]}
    unreadable = [r for r in contract_reqs if r.get("unreadable")]

    stated = sorted({s["max_w"] for s in l19 if s.get("max_w") is not None})
    if len(stated) == 1:
        return {"requirement": next(s for s in l19
                                    if s.get("max_w") == stated[0]),
                "sources": sources, "refusal": None, "superseded": []}
    if len(stated) > 1:
        return {"requirement": None, "sources": sources,
                "refusal": (f"L19 copies disagree: "
                            f"{[round(v / _MICRO, 6) for v in stated]} uW"),
                "superseded": []}
    unset = len([s for s in l19 if s.get("max_w") is None])
    bits = [f"L19_CONSTRAINTS_PDK.json fields.power_budget_uw (unset in "
            f"{unset} of {len(l19)} published copy/copies)"]
    if unreadable:
        bits.append(f"{len(unreadable)} {CONTRACT_SCHEMA} requirement(s) "
                    f"unreadable: {unreadable[0]['unreadable']}")
    return {"requirement": None, "sources": sources,
            "refusal": "; ".join(bits), "superseded": []}


#: Verdicts `judge_against_requirement` may return. UNDETERMINED is a first
#: class answer here and not an error tier: it is what an honest gate says when
#: it holds both a number and a threshold that do not belong to each other.
J_PASS, J_FAIL, J_UNDETERMINED = "PASS", "FAIL", "UNDETERMINED"


def judge_against_requirement(record: Optional[Dict[str, Any]],
                              requirement: Optional[Dict[str, Any]]
                              ) -> Dict[str, Any]:
    """Compare one total-power record against one requirement, or refuse.

    The refusals, and each is a comparison this function is NOT entitled to
    make:

      * no record  -> the artefact stated no total. Not zero power.
      * no requirement -> nothing to compare against.
      * record not MEASURED -> §2: an INVALID or NOT_MEASURED record may not
        enter a numeric comparison. This is the branch that catches a power
        number whose declared VCD basis its own transcript falsifies.
      * requirement declares an activity basis and the record's differs -> a
        budget written against observed activity cannot judge a vectorless
        estimate, and vice versa.

    A requirement that declares NO basis still bounds the number, and says so:
    `basis_policed` is False and the reader can see that the threshold does not
    know what activity model it is judging.
    """
    if record is None:
        return {"verdict": J_UNDETERMINED, "code": "NO_TOTAL_POWER",
                "reason": "no artefact states a Total row"}
    if requirement is None:
        return {"verdict": J_UNDETERMINED, "code": "NO_REQUIREMENT",
                "reason": "no authority declares a total-power limit"}
    if record.get("status") != STATUS_MEASURED:
        return {"verdict": J_UNDETERMINED, "code": "TOTAL_NOT_MEASURED",
                "reason": (f"the total-power record is "
                           f"{record.get('status')}: "
                           f"{record.get('reason', 'no reason stated')}")}
    rec_basis = (record.get("scope") or {}).get("activity_basis")
    if rec_basis not in KNOWN_BASES:
        return {"verdict": J_UNDETERMINED, "code": "ACTIVITY_BASIS_UNUSABLE",
                "reason": (f"the total-power record's activity basis is "
                           f"{rec_basis!r}; a power figure whose activity "
                           f"model is unknown cannot be judged against a "
                           f"threshold")}
    req_basis = (requirement.get("scope") or {}).get("activity_basis")
    if req_basis is not None and req_basis != rec_basis:
        return {"verdict": J_UNDETERMINED, "code": "ACTIVITY_BASIS_MISMATCH",
                "reason": (f"the requirement is declared against "
                           f"{req_basis!r} activity and the measurement is "
                           f"{rec_basis!r} — different metrics, so this is "
                           f"UNDETERMINED and not a verdict")}
    total_w = record["value"]
    max_w = requirement["max_w"]
    out = {"verdict": J_PASS if total_w <= max_w else J_FAIL,
           "code": "COMPARED",
           "total_power_w": total_w, "total_power_uw": total_w / _MICRO,
           "limit_w": max_w,
           "limit_uw": (requirement.get("max_uw")
                        if requirement.get("max_uw") is not None
                        else max_w / _MICRO),
           "utilization": total_w / max_w if max_w else None,
           "activity_basis": rec_basis,
           "basis_policed": req_basis is not None,
           "authority": requirement.get("authority"),
           "authority_file": requirement.get("file")}
    if req_basis is None:
        out["reason"] = (
            f"the requirement ({requirement.get('authority')}) declares no "
            f"activity basis, so it bounds a {rec_basis} number without "
            f"knowing that is what it bounds")
    return out
