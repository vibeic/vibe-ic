#!/usr/bin/env python3
"""dft_atpg_coverage_check.py — REAL stuck-at coverage gate (Step 11 DFT/ATPG).

ANTI-FABRICATION checker for flow Step 11. The old gate trusted the
self-produced boolean `stuck_at_ge_target` that the *producing* step
(fault_atpg_run / a runner) wrote into reports/phase2/dft/coverage.json —
i.e. the step asserted its own PASS. A run that emitted

    {"stuck_at_ge_target": true, "stuck_at_coverage_percent": 0.0,
     "stuck_at_target": 50.0}

would have sailed through even though the netlist had NO scan chain and
0% real stuck-at coverage — a silicon DFT-deficit that ships untestable
parts.

This checker does NOT re-echo that boolean. It independently parses the
ATPG artefact(s), reads the REAL measured stuck-at coverage number and
the REAL target, and recomputes the verdict:

    PASS iff measured_coverage_pct >= target_pct   (recomputed here)

It accepts the two coverage.json schemas seen in the wild — the
fault_atpg_run schema (`coverage_pct` / `target_pct`) and the
runner/skill schema (`stuck_at_coverage_percent` / `stuck_at_target`) —
plus a fallback that parses the human-readable atpg_coverage.rpt. The
written `stuck_at_ge_target` field is ONLY used as a cross-check: a
mismatch between the recomputed verdict and the written boolean is
surfaced as `self_assertion_mismatch` in the report (the recomputed
number always wins).

Honest-failure rules (no UNDISCLOSED pass on absence):
  * coverage.json (and atpg_coverage.rpt) both absent, and no disclosed
    skip sentinel                                              → FAIL (rc=1)
  * present but no measured coverage number can be extracted   → FAIL (rc=1)
  * present but no target can be extracted                     → FAIL (rc=1)
  * measured < target                                          → FAIL (rc=1)
  * measured >= target                                         → PASS (rc=0)
  * no measurable coverage AND a sibling sentinel in
    phase2/stage2/dft/ self-reports verdict ∈ {SKIP, SKIPPED,
    SKIPPED-CONDITION}                        → SKIPPED-CONDITION (rc=2)

THERE IS ONE SKIP PATH, AND IT IS DISCLOSED. This docstring used to say
"There is no SKIP path" and "NO vacuous pass on absence" without
qualification, which the shipped code has not matched since the disclosed-skip
branch landed (see `main()`, guarded by
`dft_signoff_common.disclosed_atpg_skip`): with genuinely absent stuck-at
evidence AND a co-located `dft_atpg_not_run.json` sentinel, this program
prints "SKIPPED-CONDITION" and returns rc=2, which flow_compliance_check
scores as passed=True in its VACUOUS_PASS tier. Reproduced on the real
spm x ihp-sg13g2 run (scan_netlist.v / atpg_coverage.rpt /
reports/phase2/dft/coverage.json all absent): rc=2, not rc=1.

The narrower rule the code DOES implement: absence alone is never enough.
The skip requires BOTH the absence of any measurable coverage AND an
explicit runner-written sentinel naming the capability gap. Step 11 still
applies to every digital design that reaches synthesis, so an undisclosed
absence remains a missing-evidence FAIL, and a design that DID produce a
measurement is judged on that measurement — a real low coverage still FAILs
whatever any sentinel says.

FOUNDRY-GRADE FLOOR (2026-07 DFT-depth raise): the checker no longer
trusts a lenient written target. It enforces a FOUNDRY floor (default
95 %, configurable via --foundry-floor / down for legacy) so a producing
step that writes `target_pct: 50` (or the old 80 %) can no longer pass a
sub-foundry number. The effective target is:

    effective_target = max(written_target, foundry_floor)

    PASS iff measured_coverage_pct >= effective_target

This closes the loophole where a below-foundry coverage sailed through
only because the artefact carried a lax self-chosen target. §4.05: the
floor RAISES the bar (never relaxes it) — a design below the foundry bar
FAILs honestly instead of shipping untestable silicon.

Usage:
    python3 dft_atpg_coverage_check.py <project_dir> [--json <out>]
    python3 dft_atpg_coverage_check.py <project_dir> [--coverage-json PATH]
    python3 dft_atpg_coverage_check.py <project_dir> [--foundry-floor 98]

main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error OR disclosed
                    SKIPPED-CONDITION (rc=2 is overloaded; the stdout line and
                    the --json `verdict` field distinguish them).

chip-AGNOSTIC: reads only the generic coverage.json / atpg_coverage.rpt
schemas; no design-specific knowledge.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover - standalone fallback
    _pl = None

try:
    import dft_signoff_common
except Exception:  # pragma: no cover - path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import dft_signoff_common  # type: ignore

try:
    import l_doc_consumer_contract as _l20c
except Exception:  # pragma: no cover - path fallback
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import l_doc_consumer_contract as _l20c  # type: ignore
    except Exception:
        _l20c = None


_PROGRAM = "dft_atpg_coverage_check"
_VERSION = "1.1.0"

# Foundry / ATE sign-off floor. A written target below this is clamped UP so
# a lenient self-chosen target cannot pass a sub-foundry coverage number.
FOUNDRY_FLOOR_DEFAULT = 95.0

# ── The SINGLE non-blocking-verdict contract, shared with dft_signoff_check ──
# The stuck-at verdicts `audit()` can emit that DO NOT block DFT sign-off. This
# is the ONE definition of "non-blocking stuck-at disposition"; it is consulted
# by BOTH this program's own rc mapping (`main`) AND the aggregate
# `dft_signoff_check`, so the two gates cannot classify the same recorded verdict
# differently — the whole point of vibe-ic#603 was that two gates keyed on the
# same L20 applicability and disagreed, and that can only recur if one of them
# re-invents this list instead of reading it.
#
#   PASS          — measured stuck-at coverage met the foundry floor.
#   INFORMATIONAL — `audit()` downgraded a floor FAIL because the design's OWN
#                   L20 declares no DFT (see `l20_dft_applicability`). This is
#                   NEVER a blanket pass: a design that DECLARES DFT still yields
#                   PASS/FAIL against the floor, and a real below-floor coverage
#                   on a DFT-declaring design still FAILs. INFORMATIONAL is non-
#                   blocking ONLY because the applicability-guarded downgrade
#                   already decided the floor does not govern this design.
#
# SKIPPED-CONDITION is deliberately absent: `audit()` never emits it (the
# disclosed-skip short-circuits in `main()` before `audit()` is reached), so a
# stuck-at status of SKIPPED-CONDITION reaching this predicate would be an
# unexpected state and must NOT vacuously pass.
NON_BLOCKING_STUCK_AT_VERDICTS = frozenset({"PASS", "INFORMATIONAL"})


def stuck_at_signoff_passes(verdict: Optional[str]) -> bool:
    """True iff a stuck-at verdict (as emitted by `audit()`) is non-blocking for
    DFT sign-off.

    ONE predicate, shared by this program's `main()` rc mapping and by
    `dft_signoff_check`'s aggregate, so a design's recorded stuck-at disposition
    is judged identically wherever it is read. This is the invariant that keeps
    the coverage gate and the sign-off gate from drifting into opposite verdicts
    about the same tree (vibe-ic#603). chip-AGNOSTIC — a pure string check."""
    return str(verdict).strip().upper() in NON_BLOCKING_STUCK_AT_VERDICTS

# Field names that may hold the REAL measured stuck-at coverage (%) — in
# priority order. vibe-ic#603: `test_coverage_pct` (detected / (total −
# ATPG-untestable)) is the sign-off number and is preferred when present; a
# design wrapped in an unused pad frame whose TESTABLE logic is covered would
# otherwise FAIL on the raw ratio alone. fault_atpg_run writes `coverage_pct`
# (raw) + `test_coverage_pct`; the runner/skill JSON writes
# `stuck_at_coverage_percent`. We never read `stuck_at_ge_target` for the number.
_MEASURED_FIELDS = (
    "test_coverage_pct",
    "coverage_pct",
    "stuck_at_coverage_percent",
    "stuck_at_coverage_pct",
    "coverage_percent",
    "stuck_at_pct",
)

# The RAW fault-coverage field(s), reported ALONGSIDE the (possibly test-based)
# measured number so the two never collapse into one — the core of #603.
_RAW_FIELDS = (
    "coverage_pct",
    "stuck_at_coverage_percent",
    "stuck_at_coverage_pct",
    "coverage_percent",
    "stuck_at_pct",
)

# Field names that may hold the REAL target/min coverage (%) — priority order.
_TARGET_FIELDS = (
    "target_pct",
    "stuck_at_target",
    "target_percent",
    "min_coverage",
    "target",
)


def _load_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _as_pct(val: Any) -> Optional[float]:
    """Coerce a number to a percentage. A fractional value in [0,1] is
    treated as a ratio and scaled to %; anything > 1 is taken as already-%.
    Returns None if not coercible."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f < 0:
        return None
    # Heuristic: ratios are <= 1.0; percentages can exceed 1.0. A genuine
    # 1.0 is ambiguous (1% vs 100%) but in stuck-at practice "1.0" stored
    # as a ratio means 100% and a 1% coverage would be stored as "1.0"%
    # only in degenerate runs — fault_atpg_run already normalises ratio→%
    # before writing, so the JSON path almost always carries a %. We only
    # scale strictly-less-than-1 values, leaving 1.0 as 1.0% (conservative:
    # the lower interpretation never produces a false PASS).
    if f < 1.0:
        return f * 100.0
    return f


def _extract_number(blob: dict, fields: Tuple[str, ...]) -> Tuple[Optional[float], Optional[str]]:
    """Return (pct, source_field) for the first present, coercible field."""
    for fld in fields:
        if fld in blob and blob[fld] is not None:
            pct = _as_pct(blob[fld])
            if pct is not None:
                return pct, fld
    return None, None


# ── Human-readable .rpt fallback parsers ───────────────────────────────
# Two rpt dialects exist:
#   fault_atpg_run.py:   "Stuck-at %    : 81.72"  +  "Target (min)  : 55.00"
#   runner/skill .rpt:   "Stuck-at coverage reached  : 0.0% (target was ≥50%)"
_RPT_MEASURED_PATTERNS = (
    re.compile(r"Stuck-at\s*%\s*:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
    re.compile(r"Stuck-at\s+coverage\s+reached\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*%", re.IGNORECASE),
    re.compile(r"stuck_at_coverage\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*%", re.IGNORECASE),
)
_RPT_TARGET_PATTERNS = (
    re.compile(r"Target\s*\(min\)\s*:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
    re.compile(r"target\s+was\s*[>≥]=?\s*([0-9]+(?:\.[0-9]+)?)\s*%?", re.IGNORECASE),
    re.compile(r"target\s*[>≥]=?\s*([0-9]+(?:\.[0-9]+)?)\s*%", re.IGNORECASE),
)


def _parse_rpt(text: str) -> Tuple[Optional[float], Optional[float]]:
    """Return (measured_pct, target_pct) parsed from an atpg_coverage.rpt."""
    measured: Optional[float] = None
    for pat in _RPT_MEASURED_PATTERNS:
        m = pat.search(text)
        if m:
            measured = float(m.group(1))
            break
    target: Optional[float] = None
    for pat in _RPT_TARGET_PATTERNS:
        m = pat.search(text)
        if m:
            target = float(m.group(1))
            break
    return measured, target


def evaluate(coverage_json: Optional[dict],
             rpt_text: Optional[str],
             foundry_floor: float = FOUNDRY_FLOOR_DEFAULT) -> dict:
    """Pure evaluator. Independently derives measured + target stuck-at
    coverage from the artefact(s) and recomputes the verdict against a
    FOUNDRY floor. NEVER trusts a written boolean, and NEVER trusts a
    written target below the foundry floor. Returns a verdict dict.

    effective_target = max(written_target, foundry_floor)
    PASS iff measured >= effective_target.

    chip-AGNOSTIC."""
    reasons: List[str] = []

    measured: Optional[float] = None
    measured_src: Optional[str] = None
    target: Optional[float] = None
    target_src: Optional[str] = None

    raw_measured: Optional[float] = None
    raw_src: Optional[str] = None
    if coverage_json is not None:
        measured, measured_src = _extract_number(coverage_json, _MEASURED_FIELDS)
        target, target_src = _extract_number(coverage_json, _TARGET_FIELDS)
        raw_measured, raw_src = _extract_number(coverage_json, _RAW_FIELDS)

    # Fall back to the human-readable report for whatever is still missing.
    if rpt_text and (measured is None or target is None):
        rpt_measured, rpt_target = _parse_rpt(rpt_text)
        if measured is None and rpt_measured is not None:
            measured = rpt_measured
            measured_src = "atpg_coverage.rpt"
        if target is None and rpt_target is not None:
            target = rpt_target
            target_src = "atpg_coverage.rpt"

    # The boolean the producing step asserted — used ONLY for cross-check.
    self_asserted = None
    if coverage_json is not None and "stuck_at_ge_target" in coverage_json:
        self_asserted = bool(coverage_json.get("stuck_at_ge_target"))

    # Honest-failure on insufficient substance.
    if measured is None:
        reasons.append(
            "no measured stuck-at coverage number found in coverage.json "
            f"(looked for {list(_MEASURED_FIELDS)}) or atpg_coverage.rpt")
    if target is None:
        reasons.append(
            "no stuck-at coverage target found in coverage.json "
            f"(looked for {list(_TARGET_FIELDS)}) or atpg_coverage.rpt")

    # FOUNDRY floor: clamp the written target UP so a lenient self-chosen
    # target cannot pass a sub-foundry number. A missing written target still
    # FAILs above (insufficient substance) — the floor only ever RAISES the
    # bar, it never invents a target to make an under-specified run pass.
    effective_target: Optional[float] = None
    floor_governs = False
    if target is not None:
        effective_target = max(target, foundry_floor)
        floor_governs = foundry_floor > target
        if floor_governs:
            reasons.append(
                f"written target {target:.2f}% is below the foundry floor "
                f"{foundry_floor:.2f}% — foundry floor governs "
                f"(effective target {effective_target:.2f}%)")

    recomputed_ge_target: Optional[bool] = None
    if measured is not None and effective_target is not None:
        recomputed_ge_target = measured >= effective_target
        if not recomputed_ge_target:
            reasons.append(
                f"measured stuck-at coverage {measured:.2f}% < "
                f"effective target {effective_target:.2f}% "
                f"(written {target:.2f}%, foundry floor {foundry_floor:.2f}%) "
                f"— DFT/ATPG coverage below required foundry floor "
                f"(untestable silicon)")

    # Cross-check the self-asserted boolean against our recomputation.
    self_assertion_mismatch = (
        recomputed_ge_target is not None
        and self_asserted is not None
        and recomputed_ge_target != self_asserted
    )
    if self_assertion_mismatch:
        reasons.append(
            f"self-asserted stuck_at_ge_target={self_asserted} contradicts "
            f"recomputed {recomputed_ge_target} from measured "
            f"{measured:.2f}% vs effective target {effective_target:.2f}% — "
            f"boolean ignored, recomputed verdict governs")

    verdict = "PASS" if recomputed_ge_target is True else "FAIL"

    return {
        "measured_coverage_pct": (round(measured, 4)
                                  if measured is not None else None),
        "measured_source": measured_src,
        # RAW fault coverage, reported alongside so the sign-off (test) number
        # never silently stands in for it — vibe-ic#603. `measured_is_test`
        # tells a reader which number the verdict was computed on.
        "raw_coverage_pct": (round(raw_measured, 4)
                             if raw_measured is not None else None),
        "raw_source": raw_src,
        "measured_is_test_coverage": measured_src == "test_coverage_pct",
        "target_pct": round(target, 4) if target is not None else None,
        "target_source": target_src,
        "foundry_floor_pct": round(foundry_floor, 4),
        "effective_target_pct": (round(effective_target, 4)
                                 if effective_target is not None else None),
        "foundry_floor_governs": floor_governs,
        "recomputed_ge_target": recomputed_ge_target,
        "self_asserted_ge_target": self_asserted,
        "self_assertion_mismatch": self_assertion_mismatch,
        "verdict": verdict,
        "status": verdict,
        "reasons": reasons,
    }


# ── L20 gate applicability (vibe-ic#603 item 3) ────────────────────────
# The 95 % foundry floor is a SIGN-OFF requirement for a design that DECLARES a
# DFT topology. A design whose own inputs DECLARE no DFT requirement — L20
# applicability NOT_APPLICABLE, or an EXTRACTED L20 carrying no chains / tap /
# compression / bist — should have
# its ATPG coverage reported as INFORMATIONAL, not FAILed against the floor —
# otherwise the flow's auto-inserted scan chain produces a coverage number that
# a design that never asked for DFT is then punished by. This reads the design's
# OWN L20; a design that DOES declare DFT keeps the floor (this only ever
# downgrades a FAIL to informational, never the reverse — §4.05).
_L20_PRESENT_KEYS = ("dft_present", "dft_required", "scan_required",
                     "standard_scan_chain_present")
_L20_CHAIN_KEYS = ("scan_chains", "scan_chain", "chains", "scan_chain_topology")
_L20_TAP_KEYS = ("jtag_tap", "tap", "jtag", "test_access_port")
_L20_COMPRESSION_KEYS = ("test_compression", "compression", "edt")
_L20_BIST_KEYS = ("bist_mbist", "bist", "mbist")


def _truthy(v: Any) -> bool:
    if v is None or v is False:
        return False
    if isinstance(v, (list, dict, str)):
        return len(v) > 0
    return bool(v)


def l20_dft_applicability(project: Path) -> dict:
    """Read the design's OWN L20 and report whether it DECLARES DFT.

    Returns ``{l20_present, applicable, asserts_dft, reason}``. When L20 is
    absent or unparseable the floor stands (``asserts_dft`` conservatively True-
    equivalent: we return asserts_dft=None and the caller keeps the floor).

    An L20 that is PRESENT but has never claimed extraction is the SAME
    uninformative state and gets the SAME conservative answer — its
    ``dft_present: false`` is the emitter's field default, not a decision. Only
    ``asserts_dft is False`` licenses disabling the foundry floor, and after
    this change exactly ONE state produces it: ``applicability:
    NOT_APPLICABLE`` — an explicit, human-authored declaration.

    KNOWN AND DELIBERATELY UNTOUCHED, opposite direction: a layer that DOES
    claim extraction and records no DFT is currently folded into
    ``asserts_dft=True`` by the ``is_extraction_claimed`` term, so it keeps the
    floor even though it is the one state that would legitimately earn the
    downgrade. Correcting that LOOSENS the gate for some designs and is a
    separate decision; it is not bundled here, where every change tightens."""
    out = {"l20_present": False, "applicable": None, "asserts_dft": None,
           "reason": None}
    if _l20c is None:
        out["reason"] = "l_doc_consumer_contract unavailable — floor stands"
        return out
    try:
        path, doc = _l20c.load_l_doc(project, "L20")
    except Exception:
        path, doc = None, None
    if path is None:
        out["reason"] = "no L20 doc — floor stands"
        return out
    out["l20_present"] = True
    if doc is None:
        out["reason"] = "L20 unparseable — floor stands"
        return out
    applic = _l20c.applicability_of(doc)
    out["applicable"] = applic
    if applic in ("NOT_APPLICABLE", "N/A", "NA"):
        out["reason"] = f"L20 applicability={applic}"
        out["asserts_dft"] = False
        return out
    fields = _l20c.l_doc_fields(doc)

    def _get(keys):
        for k in keys:
            if k in fields:
                return fields[k]
        return None
    declares_topology = (
        _truthy(_get(_L20_PRESENT_KEYS))
        or _truthy(_get(_L20_TAP_KEYS))
        or _truthy(_get(_L20_COMPRESSION_KEYS))
        or _truthy(_get(_L20_BIST_KEYS))
        or _truthy(_get(_L20_CHAIN_KEYS))
    )
    if declares_topology or _l20c.is_extraction_claimed(doc):
        out["asserts_dft"] = True
        out["reason"] = "L20 declares a DFT topology"
        return out

    # NOT-RUN IS NOT RAN-AND-EMPTY. What is left here is a layer that is
    # present, asserts no DFT topology, AND has never claimed extraction — the
    # emitter's untouched skeleton, whose `dft_present: false` is a FIELD
    # DEFAULT, not a decision. `l_doc_consumer_contract.is_extraction_claimed`
    # names this trap in its own docstring: the producer state is THREE-valued
    # (NOT-RUN / RAN-AND-EMPTY / RAN-AND-FOUND) and only RAN-AND-EMPTY is a
    # design saying "I need no DFT". Reading NOT-RUN as RAN-AND-EMPTY turns the
    # ABSENCE of a stated requirement into a DECLARATION that the requirement is
    # absent, and silently switches off a foundry sign-off floor on that basis.
    #
    # This function already fails safe for its other two uninformative states —
    # see the docstring: "When L20 is absent or unparseable the floor stands".
    # An un-extracted skeleton carries no more information than an absent file,
    # so it must not buy a LOOSER verdict than deleting the file would. Before
    # this change the gate was NON-MONOTONIC IN EVIDENCE: `rm L20_*.json` made
    # it STRICTER than leaving the empty skeleton in place.
    #
    # asserts_dft=None is the value the caller already treats as "keep the
    # floor" (`l20.get("asserts_dft") is False` gates the downgrade), so the
    # unknown state now lands on the conservative side by construction. The two
    # genuine downgrade paths are untouched: `applicability: NOT_APPLICABLE`
    # (early return above) and a layer that claims extraction. chip-AGNOSTIC —
    # no design, PDK, vendor or part literal is involved.
    out["asserts_dft"] = None
    out["reason"] = (
        f"L20 is present but UN-EXTRACTED (extraction_status="
        f"{str(doc.get('extraction_status') or 'unset')!r}, no chains/tap/"
        f"compression/bist and no extraction_evidence), so whether this design "
        f"requires DFT is UNKNOWN, not declared-absent. The foundry floor "
        f"STANDS — an un-extracted layer must not buy a looser verdict than "
        f"having no layer at all. To report ATPG coverage as informational, "
        f"the design must actually declare it: set L20 applicability to "
        f"NOT_APPLICABLE, or extract L20 and record the no-DFT decision.")
    return out


def _resolve_paths(project: Path,
                   coverage_json_override: Optional[str]) -> Tuple[List[Path], List[Path]]:
    """Return (coverage_json_candidates, rpt_candidates) in priority order.

    Canonical coverage.json: reports/phase2/dft/coverage.json (matches the
    flow YAML + fault_atpg_run's report_path(dft/coverage.json) routing).
    Older flat layout reports/dft/coverage.json is accepted as a fallback.
    """
    cov_candidates: List[Path] = []
    if coverage_json_override:
        cov_candidates.append(Path(coverage_json_override))
    else:
        if _pl is not None:
            cov_candidates.append(_pl.report_path(project, "dft/coverage.json"))
            cov_candidates.append(_pl.reports_phase2_dir(project) / "dft" / "coverage.json")
        cov_candidates.append(project / "reports" / "phase2" / "dft" / "coverage.json")
        cov_candidates.append(project / "reports" / "dft" / "coverage.json")

    rpt_candidates: List[Path] = []
    if _pl is not None:
        rpt_candidates.append(_pl.dft_dir(project) / "atpg_coverage.rpt")
    rpt_candidates.append(project / "phase2" / "stage2" / "dft" / "atpg_coverage.rpt")
    rpt_candidates.append(project / "dft" / "atpg_coverage.rpt")

    # De-dup preserving order.
    def _dedup(paths: List[Path]) -> List[Path]:
        seen = set()
        out = []
        for p in paths:
            key = str(p)
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out

    return _dedup(cov_candidates), _dedup(rpt_candidates)


def _has_measurable_coverage(project: Path,
                             coverage_json_override: Optional[str]) -> bool:
    """True iff a REAL measurable coverage artefact is present: a
    coverage.json or atpg_coverage.rpt exists AND — for a coverage.json — it
    does not self-report faults_total==0 (which means the engine never
    enumerated a single fault, i.e. it did not run). Used ONLY to GUARD the
    disclosed-skip path so a real run (measurable coverage present) can NEVER
    take the skip. A present-but-low coverage counts as measurable and is
    judged normally (still FAILs)."""
    cov_candidates, rpt_candidates = _resolve_paths(project, coverage_json_override)
    if any(p.is_file() for p in rpt_candidates):
        return True
    cov_path = next((p for p in cov_candidates if p.is_file()), None)
    if cov_path is not None:
        data = _load_json(cov_path)
        if isinstance(data, dict) and data.get("faults_total") == 0:
            return False  # engine-did-not-run (0 faults enumerated)
        return True
    return False


# The stuck-at engine's OWN machine-readable coverage metadata, and the
# disclosed-aside name `_dft_retain_unmeasured` moves it to. Paths and one YAML
# key only — no design, PDK or vendor literal.
_ENGINE_COVERAGE_META = (
    "phase2/stage2/dft/coverage.yml",
    "phase2/stage2/dft/coverage.unmeasured.yml",
)
_ATPG_NOT_RUN_RECORD = "phase2/stage2/dft/dft_atpg_not_run.json"
_RATIO_RE = re.compile(r"^\s*ratio:\s*([0-9.eE+-]+)\s*$", re.MULTILINE)


def _engine_metadata_left_behind(project: Path) -> Optional[dict]:
    """Return the engine's unread coverage metadata, or None.

    WHY THIS EXISTS. `fault_atpg_run._run_docker` starts the engine with
    `docker run --rm` under a client-side `subprocess.run(..., timeout=)`.
    A timeout kills the docker CLIENT; the container is untouched, keeps
    running, completes, writes its coverage metadata into the mounted project
    and only then `--rm`s itself. The flow, meanwhile, has already recorded
    "no measurement" and moved on. Nothing ever looks again.

    MEASURED — the same design on two rounds, two plugin versions and two
    images, entirely from artefact mtimes:

      v1.9.27 / image 0.2.51   dft_atpg_not_run.json 18:58:49
                               coverage.yml          19:04:20   (+331 s)
      v1.9.8  / image 0.2.48   dft_atpg_not_run.json 06:28:45
                               coverage.yml          06:33:57   (+312 s)

    Both files carry a BYTE-IDENTICAL `ratio: 9.16633307933807e-1` — 91.67 %
    stuck-at coverage over a full `faultPoints:` enumeration, produced by the
    engine from the run's own netlist. Both runs nonetheless reported "no
    DFT/ATPG coverage evidence found ... Step 11 cannot pass without a real
    stuck-at coverage measurement".

    THIS FUNCTION DOES NOT CHANGE ANY VERDICT. The branch that calls it
    returns FAIL before and after. It replaces a false sentence ("nothing was
    measured") with a true and actionable one ("the measurement is here, it
    landed N seconds late, and here is the mechanism"). Recovering the number
    into the canonical reports is a producer-side change and is deliberately
    NOT done here — a gate must not manufacture the evidence it grades.

    chip-AGNOSTIC / PDK-AGNOSTIC: file paths and one YAML key.
    """
    not_run = project / _ATPG_NOT_RUN_RECORD
    for rel in _ENGINE_COVERAGE_META:
        p = project / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _RATIO_RE.search(text)
        if not m:
            continue
        # THE PRODUCER'S OWN PARSER, NOT A SECOND ONE. A gate that re-derives
        # a number the producer already knows how to derive will eventually
        # disagree with it, and the disagreement will be read as a finding.
        # `_count_yaml_block_items`' docstring is explicit that Fault writes
        # SIBLING top-level sequences (`sa0Covered:`, `sa1Uncovered:`, ...)
        # after `faultPoints:`, so a naive count sums all of them — 138 698
        # instead of 44 934 on the tree measured below.
        try:
            import fault_atpg_run as _fatpg   # sibling program, same dir
            parsed = _fatpg.parse_atpg_coverage(text, "", 0)
        except Exception:
            continue
        pct = parsed.get("coverage_pct") or 0.0
        if not (0.0 < pct <= 100.0):
            continue
        points = parsed.get("faults_total") or 0
        covered = parsed.get("faults_covered") or 0
        delta = None
        if not_run.is_file():
            try:
                delta = int(round(p.stat().st_mtime - not_run.stat().st_mtime))
            except OSError:
                delta = None
        return {
            "path": rel,
            "ratio": m.group(1),
            "coverage_pct": pct,
            "fault_points": points,
            "faults_covered": covered,
            "parsed_by": "fault_atpg_run.parse_atpg_coverage",
            "coverage_source": parsed.get("coverage_source"),
            "faults_total_source": parsed.get("faults_total_source"),
            "not_run_record": (_ATPG_NOT_RUN_RECORD if not_run.is_file()
                               else None),
            "landed_after_not_run_s": delta,
        }
    return None


def audit(project: Path,
          coverage_json_override: Optional[str] = None,
          foundry_floor: float = FOUNDRY_FLOOR_DEFAULT) -> dict:
    cov_candidates, rpt_candidates = _resolve_paths(project, coverage_json_override)

    cov_path = next((p for p in cov_candidates if p.is_file()), None)
    rpt_path = next((p for p in rpt_candidates if p.is_file()), None)

    base = {
        "program": _PROGRAM,
        "version": _VERSION,
        "project_dir": str(project),
        "coverage_json": str(cov_path) if cov_path else None,
        "atpg_rpt": str(rpt_path) if rpt_path else None,
    }

    if cov_path is None and rpt_path is None:
        # No evidence at all → honest FAIL (NOT a vacuous pass on absence).
        #
        # ... but "the canonical reports are absent" and "the engine produced
        # no measurement" are two different statements, and this branch used to
        # print the second while only having established the first.
        orphan = _engine_metadata_left_behind(project)
        reasons = [
            "no DFT/ATPG coverage evidence found: neither "
            f"coverage.json ({cov_candidates[0]}) nor "
            f"atpg_coverage.rpt ({rpt_candidates[0]}) exists — "
            "Step 11 cannot pass without a real stuck-at coverage "
            "measurement"
        ]
        if orphan is not None:
            # Only CLAIM the ordering when the mtimes actually show it. A tree
            # that has been copied or hand-edited can carry a delta that is
            # zero or negative, and asserting "written N s AFTER" off that
            # would be the same kind of unbacked sentence this reason exists
            # to remove.
            _d = orphan["landed_after_not_run_s"]
            if isinstance(_d, int) and _d > 0:
                _when = (f"It was written {_d}s AFTER "
                         f"{orphan['not_run_record']} declared the "
                         f"measurement absent. ")
            elif orphan["not_run_record"] is None:
                _when = "No not-run record sits beside it. "
            else:
                _when = (f"Its mtime does not post-date "
                         f"{orphan['not_run_record']} "
                         f"(delta={_d}s), so the ordering is NOT established "
                         f"on this tree — the metadata's presence is. ")
            reasons.append(
                "BUT THE ENGINE'S OWN COVERAGE METADATA IS IN THE TREE AND "
                "WAS NEVER READ: "
                f"{orphan['path']} holds ratio={orphan['ratio']!r} "
                f"(= {orphan['coverage_pct']:.2f}%) over "
                f"{orphan['fault_points']} enumerated fault points. "
                + _when +
                "The producer runs the engine with `docker run --rm` and a "
                "client-side `subprocess` timeout, which kills the docker "
                "CLIENT and not the container — so on a wall-budget expiry "
                "the engine keeps running, completes, and lands its metadata "
                "after the flow has stopped listening. This step is still "
                "FAIL (the canonical reports really are absent); what is "
                "corrected here is the CLAIM that nothing was measured."
            )
        base.update({
            "measured_coverage_pct": None,
            "target_pct": None,
            "recomputed_ge_target": None,
            "foundry_floor_pct": round(foundry_floor, 4),
            "engine_metadata_left_behind": orphan,
            "verdict": "FAIL",
            "status": "FAIL",
            "reasons": reasons,
        })
        return base

    coverage_json = _load_json(cov_path) if cov_path else None
    if cov_path is not None and coverage_json is None:
        base["reasons_prefix"] = [
            f"coverage.json present but not valid JSON: {cov_path}"]
    rpt_text = None
    if rpt_path is not None:
        try:
            rpt_text = rpt_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            rpt_text = None

    result = evaluate(coverage_json, rpt_text, foundry_floor=foundry_floor)
    # Surface a JSON-parse note as a leading reason if applicable.
    if base.get("reasons_prefix"):
        result["reasons"] = base.pop("reasons_prefix") + result.get("reasons", [])
    result.update(base)

    # ── L20 gate applicability (vibe-ic#603 item 3) ───────────────────────
    # Only ever DOWNGRADES a FAIL to INFORMATIONAL, and only when the design's
    # OWN L20 declares no DFT requirement. A design that declares DFT keeps the
    # floor; a real MEASUREMENT is still reported either way (degrade loudly).
    l20 = l20_dft_applicability(project)
    result["l20_applicability"] = l20
    if result.get("verdict") == "FAIL" and l20.get("asserts_dft") is False:
        result["verdict"] = "INFORMATIONAL"
        result["status"] = "INFORMATIONAL"
        result["floor_enforced"] = False
        result.setdefault("reasons", []).insert(
            0,
            f"{l20.get('reason')}, so ATPG coverage is INFORMATIONAL, not "
            f"gated at the {foundry_floor:.0f}% foundry floor. Measured test "
            f"coverage {result.get('measured_coverage_pct')}% "
            f"(raw fault coverage {result.get('raw_coverage_pct')}%) is "
            f"reported for the record; a design that DECLARES DFT would be "
            f"held to the floor.")
    else:
        result["floor_enforced"] = True
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Step 11 DFT/ATPG real stuck-at coverage gate "
                    "(recomputes coverage >= target; ignores self-asserted bool)")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--coverage-json", default=None,
                    help="Explicit path to coverage.json (overrides auto-resolve)")
    ap.add_argument("--foundry-floor", type=float, default=FOUNDRY_FLOOR_DEFAULT,
                    help="Foundry/ATE stuck-at coverage floor %% — the effective "
                         "target is max(written_target, floor). Default "
                         f"{FOUNDRY_FLOOR_DEFAULT:.0f}%%. Raising it (e.g. 98) "
                         "tightens the bar; a lenient written target can never "
                         "drop below it.")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    # HONEST disclosed-skip (flow step-11): when the OSS Fault ATPG engine
    # genuinely could not MEASURE sign-off coverage on this netlist form AND
    # the runner honestly self-reported the skip via a sibling
    # dft_atpg_not_run.json (verdict ∈ SKIP/SKIPPED/SKIPPED-CONDITION), AND no
    # measurable coverage artefact exists, resolve to SKIPPED-CONDITION
    # (rc=2 → VACUOUS_PASS) instead of a hard missing-evidence FAIL. Guarded
    # on BOTH conditions — a real run (measurable coverage present) NEVER
    # takes this path, so a real low coverage still FAILs.
    _skip = dft_signoff_common.disclosed_atpg_skip(project)
    if _skip is not None and not _has_measurable_coverage(project, args.coverage_json):
        print(f"{_PROGRAM}: SKIPPED-CONDITION — DFT ATPG disclosed-skipped: "
              f"{_skip}")
        if args.json:
            try:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(json.dumps({
                    "program": _PROGRAM,
                    "version": _VERSION,
                    "project_dir": str(project),
                    "verdict": "SKIPPED-CONDITION",
                    "status": "SKIPPED-CONDITION",
                    "reason": _skip,
                    "reasons": [f"DFT ATPG disclosed-skipped: {_skip} — no "
                                "measurable stuck-at coverage artefact and a "
                                "sibling sentinel honestly self-reports the "
                                "skip"],
                }, indent=2, ensure_ascii=False) + "\n")
            except Exception as exc:  # pragma: no cover - IO edge
                print(f"WARN: could not write --json {args.json}: {exc}",
                      file=sys.stderr)
        return 2

    report = audit(project, args.coverage_json, foundry_floor=args.foundry_floor)
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        try:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(out + "\n")
        except Exception as exc:  # pragma: no cover - IO edge
            print(f"WARN: could not write --json {args.json}: {exc}",
                  file=sys.stderr)
    print(out)

    verdict = report.get("verdict")
    meas = report.get("measured_coverage_pct")
    raw = report.get("raw_coverage_pct")
    tgt = report.get("target_pct")
    eff = report.get("effective_target_pct")
    print(f"{_PROGRAM}: measured={meas} raw={raw} written_target={tgt} "
          f"effective_target={eff} verdict={verdict}", file=sys.stderr)
    # PASS and the L20-INFORMATIONAL downgrade (design declares no DFT) both
    # resolve to rc=0; only a floor-enforced FAIL is rc=1. Routed through the
    # SHARED predicate so this rc mapping and dft_signoff_check's stuck-at
    # acceptance read the SAME non-blocking set — they cannot drift.
    return 0 if stuck_at_signoff_passes(verdict) else 1


if __name__ == "__main__":
    sys.exit(main())
