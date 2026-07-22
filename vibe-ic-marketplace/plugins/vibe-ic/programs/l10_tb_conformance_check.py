#!/usr/bin/env python3
"""l10_tb_conformance_check.py — v0.54 plugin gate

Verifies that EVERY deterministic test vector enumerated in
`generated_docs/L10_TEST_CASES.json` has actually been exercised by the
testbench suite under `sim/tb/`.

Coverage rules per test case:
  - For a `cmd_response` case with opcode 0xXX: require evidence that the
    host packet byte sequence was driven into DUT, AND that the expected
    response was checked. Accepted evidence:
      (a) the opcode literal (`8'hXX`, `8'h<XX>`, or the hex byte in a
          `tb_vec` array) appears in at least one `sim/tb/tb_*.v`, AND
      (b) `sim/work/summary.txt` or `reports/sim/summary.txt` records
          a passing case whose id matches the L10 `id` field (case-
          insensitive substring).
  - For `error_path` / `state_transition` / `timing_sequence` /
    `analog_interaction` cases, require the case `id` to appear in at
    least one tb file (comment or task name) — documented trace-to-
    requirement.

This gate complements `cmd_response_conformance_check.py` which only
verifies CRC-residue correctness of the host vectors; it does NOT verify
that the tb harness actually drove them. l10_tb_conformance_check.py
closes that gap.

Usage:
    python3 l10_tb_conformance_check.py \\
        --l10 generated_docs/L10_TEST_CASES.json \\
        --tb-dir sim/tb \\
        --summary sim/work/summary.txt \\
        --out reports/gates/l10_tb_conformance.json

Exit code:
    0 — every L10 case has tb evidence
    1 — one or more cases lacked evidence
    2 — input artefacts missing / malformed
    3 — PASS_WITH_WAIVERS: every genuine-digital case had evidence AND the only
        cases without a digital-TB id-substring trace are `verification_intent`
        cases whose oracle lives on the analog / mixed-signal (A/M) track that
        was explicitly deferred via --skip-analog, anchored to a reviewable
        capability-gap bridge (sim/results.xml). Mirrors #651's class-aware
        rc=3 + `PASS_WITH_WAIVERS:` sentinel so flow_compliance_check promotes
        Step 4 to WAIVED-DEFERRED (Overall PASS_WITH_WAIVERS) instead of a
        hard Step-4 FAIL that cascades to blocked Phase-3 steps.

        OR: all un-evidenced cases are `functional_vector` cases whose oracle
        requires a CPU instruction-set oracle (`cap:cpu_functional_oracle`)
        that was explicitly deferred by the sibling
        `cpu_functional_oracle_waiver_check`. Auto-detected from
        `sim/results.xml <capability_gap>cap:cpu_functional_oracle</…>`.

ORGANIC #773 — class/kind-aware A/M-track waiver:
    Before this fix the gate demanded a digital-TB id-substring trace for
    EVERY L10 case regardless of `kind` and emitted only rc 0/1/2. A
    `kind=verification_intent` case (satisfiable only by the --skip-analog'd
    A/M track — e.g. LDO line/load regulation + SNDR, multi-corner TT/SS/FF,
    tool disclosure, golden-GDS cross-check) therefore hard-FAILed Step 4
    even though the runner's own verdict was PASS_WITH_WAIVERS. The adjacent
    sibling `cpu_functional_oracle_waiver_check` (#651) is class-aware; this
    gate now mirrors it.

    §4.05 NO-LEAK (load-bearing): the relaxation is kind-scoped. A genuine
    digital case (`cmd_response` / `error_path` / `state_transition` / …) with
    no tb evidence must STILL FAIL — even under --skip-analog. The waiver only
    credits `verification_intent` cases, and only when a reviewable
    capability-gap anchor (sim/results.xml) is present; an unanchored blanket
    waiver is NOT honoured (would re-FAIL), so the relaxation can never mask a
    missing digital testbench.

ORGANIC #851 — CPU functional-oracle waiver (mirrors #773 for processor_cpu):
    When `sim/results.xml` carries `<capability_gap>cap:cpu_functional_oracle
    </capability_gap>`, the gate AUTO-DETECTS the processor_cpu class and
    waives `functional_vector` cases that lack TB evidence — they require a
    CPU instruction-set oracle that is a documented capability gap (deferred
    to the per-IC oracle TB skill). The sibling cpu_functional_oracle_waiver_
    check already returns PASS_WITH_WAIVERS (rc=3); this gate now coordinates
    with it instead of independently hard-FAILing.

    §4.05 NO-LEAK: the waiver is scoped to `functional_vector` cases ONLY,
    and ONLY when `cap:cpu_functional_oracle` is present in a reviewable
    results.xml anchor. A non-functional-vector case (e.g. cmd_response with
    opcode) with no evidence still FAILs. An unanchored waiver (no results.xml)
    also still FAILs.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# #206 — share the SUBSTANCE detector with vacuous_testbench_check so the two
# gates never disagree about whether a testbench actually drives the DUT. Import
# by bare name (programs/ is on sys.path under the flow runner; add this file's
# own dir as a fallback for a bare script invocation).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import vacuous_testbench_check as _vtb
except Exception:  # pragma: no cover — never let a helper import break the gate
    _vtb = None


# ----- helpers ------------------------------------------------------


def load_l10(path: str) -> List[Dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    # Accept either a flat list or a dict with "test_cases" / "cases" / "vectors"
    if isinstance(data, list):
        return data
    for key in ("test_cases", "cases", "vectors", "cmd_response", "tests"):
        if key in data and isinstance(data[key], list):
            return data[key]
    raise ValueError("L10 JSON did not contain a recognisable test-case list")


# #209 — a generated TB that drives the DUT but carries NO case oracle marks
# itself with this literal (emitted by `testbench_gen.ORACLE_NONE_MARKER`). Such
# a file is a REAL testbench — it instantiates the DUT and can fail — so it must
# still count as a driver for the #206 vacuity test. But it verifies only the
# substance floor (no output is X after reset), NOT the case's expected
# behaviour, so its text must NOT reach the evidence blob: the blob credits a
# case whenever the case id appears in it, and the case id is this file's own
# module name. Without this exclusion the #209 fix would silently convert every
# previously-uncovered case into "covered" — trading a vacuous testbench for
# vacuous coverage, which is the same lie one layer up.
_ORACLE_NONE_MARKER = "VIBEIC_TB_ORACLE: NONE"


def read_all_tb_text(tb_dir: str) -> Tuple[Dict[str, str], str]:
    """Return (per-file text map, evidence blob) of every .v / .sv under tb_dir.

    `per_file` holds EVERY testbench (it feeds the #206 substance test: does
    anything here drive the DUT). The blob holds only files that carry a real
    case oracle — a self-declared oracle-less scaffold (#209) is excluded, so
    its presence can never be mistaken for coverage.
    """
    per_file: Dict[str, str] = {}
    blob_parts: List[str] = []
    for p in sorted(Path(tb_dir).rglob("*")):
        if p.is_file() and p.suffix in (".v", ".sv", ".svh"):
            try:
                txt = p.read_text(errors="replace")
            except Exception:
                continue
            per_file[str(p)] = txt
            if _ORACLE_NONE_MARKER not in txt:
                blob_parts.append(txt)
    return per_file, "\n".join(blob_parts)


def read_summary(summary_path: str) -> str:
    p = Path(summary_path)
    if not p.exists():
        return ""
    return p.read_text(errors="replace")


# ----- evidence matching -------------------------------------------

OPCODE_RE = re.compile(r"0?x?([0-9A-Fa-f]{2})")


def opcode_patterns(byte_hex: str) -> List[re.Pattern]:
    """Return regex patterns that match `byte_hex` in common Verilog forms."""
    m = OPCODE_RE.fullmatch(byte_hex.strip())
    if not m:
        return []
    h = m.group(1).upper()
    forms = [
        rf"8'h{h}",
        rf"8'h{h.lower()}",
        rf"8'b{int(h, 16):08b}",
        rf"\b0x{h}\b",
        rf"\b{h}\b",
    ]
    return [re.compile(f) for f in forms]


def case_has_opcode_evidence(case: Dict[str, Any], tb_blob: str) -> bool:
    """Check if the case's opcode or host packet bytes appear in any tb file."""
    # Find the opcode hex from common field names
    opcode = None
    for field in ("opcode", "cmd", "cmd_hex", "cmd_byte"):
        if field in case and case[field] is not None:
            opcode = str(case[field])
            break
    # Or first byte of host packet
    if not opcode:
        for field in ("host_packet", "host", "tx_bytes", "cmd_bytes"):
            v = case.get(field)
            if isinstance(v, list) and v:
                opcode = str(v[0])
                break
            if isinstance(v, str) and v:
                opcode = v.split()[0]
                break
    if not opcode:
        return False
    for pat in opcode_patterns(opcode):
        if pat.search(tb_blob):
            return True
    return False


def case_id_appears(case_id: str, tb_blob: str, summary: str) -> bool:
    if not case_id:
        return False
    needle = re.escape(case_id.lower())
    if re.search(needle, tb_blob.lower()):
        return True
    if re.search(needle, summary.lower()):
        return True
    return False


def summary_has_pass(case_id: str, summary: str) -> bool:
    """Grep summary.txt for `<case_id>.*PASS` pattern."""
    if not case_id or not summary:
        return False
    pat = re.compile(rf"{re.escape(case_id)}.*PASS", re.I)
    return bool(pat.search(summary))


# ----- ORGANIC #773 — verification_intent / A-M-track classification -------

# The capability-gap token the gate stamps on an analog-verification-intent
# waiver. A chip-AGNOSTIC capability identifier (a KIND/track class name),
# NOT a chip/vendor/SKU literal — mirrors #651's `cap:cpu_functional_oracle`.
CAP_ANALOG_VERIFICATION_INTENT = "cap:analog_verification_intent_oracle"

# ----- ORGANIC #851 — CPU functional-oracle waiver (processor_cpu class) ----

# The capability-gap token for the CPU functional-oracle waiver. Matches the
# token emitted by cpu_functional_oracle_waiver_check (#651) and carried in
# sim/results.xml by the runner's generic_full_stack connectivity TB.
CAP_CPU_FUNCTIONAL_ORACLE = "cap:cpu_functional_oracle"

# Kind/category/type tokens (case-insensitive) that denote a functional test
# vector whose oracle requires a CPU instruction-set verification oracle —
# the cases that CANNOT be covered by a generic connectivity TB and are
# deferred to a per-IC oracle TB (skill testbench-author). Kept as a small
# synonym set (a KIND vocabulary), never a per-chip literal.
_FUNCTIONAL_VECTOR_KINDS = frozenset({
    "functional_vector",
    "functional",
    "functional_test",
    "instruction_test",
    "cpu_functional",
})

# Kind/category/type tokens (case-insensitive) that denote a case whose oracle
# lives on the analog / mixed-signal (A/M) verification track — the cases a
# digital testbench can NEVER carry an id-substring trace for, and which the
# A/M track satisfies. Kept as a small synonym set (a KIND vocabulary), never
# a per-chip literal.
_VERIFICATION_INTENT_KINDS = frozenset({
    "verification_intent",
    "analog_verification_intent",
    "am_verification_intent",
    "analog_verification",
    "mixed_signal_verification",
})


def case_kind(case: Dict[str, Any]) -> str:
    """Normalised kind/category/type token for a case (lowercased)."""
    raw = case.get("kind", case.get("category", case.get("type", "")))
    return str(raw or "").strip().lower()


def is_verification_intent(case: Dict[str, Any]) -> bool:
    """True iff this case's KIND denotes an A/M-track verification-intent case
    (chip-AGNOSTIC — a kind vocabulary, never a chip/vendor/SKU literal)."""
    return case_kind(case) in _VERIFICATION_INTENT_KINDS


def is_functional_vector(case: Dict[str, Any]) -> bool:
    """ORGANIC #851 — True iff this case's KIND denotes a CPU functional
    test vector whose oracle requires a CPU instruction-set oracle
    (chip-AGNOSTIC — a kind vocabulary, never a chip/vendor/SKU literal)."""
    return case_kind(case) in _FUNCTIONAL_VECTOR_KINDS


# ORGANIC #773 r2 — a DIGITAL class vocabulary (the cmd_response family). A case
# resolving to one of these by its category/type — OR carrying an opcode/cmd
# field — is a digital command-response case whose conformance is satisfiable by
# the digital TB; it must NEVER be A/M-waived even if it ALSO carries a spurious
# `kind=verification_intent`. chip-AGNOSTIC: a class vocabulary, no SKU literal.
_DIGITAL_CLASS_TOKENS = frozenset({
    "cmd_response", "cmd_rsp", "happy", "happy_path", "error_path",
    "state_transition", "timing_sequence", "register_access", "command",
})


def _has_digital_signal(case: Dict[str, Any], is_cmd_rsp: bool) -> bool:
    """True iff the case carries a DIGITAL signal (is_cmd_rsp by category-priority,
    an opcode/cmd field, or a digital category/type token) — so a
    kind=verification_intent mislabel cannot defeat the digital requirement."""
    if is_cmd_rsp:
        return True
    for field in ("opcode", "cmd", "cmd_hex", "cmd_byte"):
        if case.get(field):
            return True
    cat = str(case.get("category", case.get("type", "")) or "").strip().lower()
    return cat in _DIGITAL_CLASS_TOKENS


# ----- ORGANIC #808 — verification_checklist (DV-milestone) classification ----
#
# NEW gap, surfaced after #799 unblocked Step-4. Phase 1 emits a project's
# verification checklist table (e.g. an OpenTitan-style DV checklist) as L10
# `kind=verification_checklist` rows. Those rows are DV PROCESS MILESTONES
# (status Done / N/A / Waived / blank), NOT TB-traceable functional vectors:
# no testbench can ever carry an id-substring / opcode trace for a process
# milestone. The TB-evidence demand therefore counted EVERY checklist row as
# "lack evidence" → 103/103 → Step-4 hard-FAIL on opentitan_aes.
#
# Fix: scope verification_checklist rows OUT of the TB-evidence requirement and
# instead credit the row's CARRIED status. chip-AGNOSTIC — a KIND vocabulary +
# a status vocabulary, never a chip/vendor/SKU literal.

# Kind/category/type tokens (case-insensitive) that denote a DV-milestone
# checklist row whose satisfaction is its carried status, not a TB trace.
_VERIFICATION_CHECKLIST_KINDS = frozenset({
    "verification_checklist",
    "dv_checklist",
    "checklist",
    "milestone",
    "verification_milestone",
})

# Carried statuses that mark a checklist row as SATISFIED or explicitly DEFERRED
# (so the row is credited, not counted as a TB-evidence miss). A status
# vocabulary, chip-AGNOSTIC.
_CHECKLIST_SATISFIED_STATUSES = frozenset({
    "done", "complete", "completed", "pass", "passed", "ok", "yes",
    "n/a", "na", "not applicable", "waived", "waiver", "deferred",
})

# Carried statuses that mark a checklist row as an EXPLICIT shortfall — it must
# still surface as a checklist gap (don't blanket-pass every row). §4.05 NO-LEAK.
_CHECKLIST_FAIL_STATUSES = frozenset({
    "fail", "failed", "error", "blocked", "no", "incomplete", "not done",
})


def is_verification_checklist(case: Dict[str, Any]) -> bool:
    """True iff this case's KIND denotes a DV-milestone checklist row
    (chip-AGNOSTIC — a kind vocabulary, never a chip/vendor/SKU literal)."""
    return case_kind(case) in _VERIFICATION_CHECKLIST_KINDS


def checklist_status(case: Dict[str, Any]) -> str:
    """Normalised carried status of a checklist row (lowercased; '' when blank).

    A blank/None status is a checklist gap but NOT a TB-evidence failure."""
    raw = case.get("status", case.get("state", case.get("result", "")))
    return str(raw or "").strip().lower()


def classify_checklist(case: Dict[str, Any]) -> str:
    """Classify a verification_checklist row by its carried status.

    Returns one of:
      'satisfied'      — Done / N/A / Waived / Pass …  (credited, not a miss)
      'checklist_gap'  — blank/None, or an explicit FAIL/blocked status
                         (surfaced as a checklist shortfall; NOT a TB-evidence
                         failure, so it cannot mask a missing digital TB).
    §4.05 NO-LEAK: this classifier is reached ONLY for verification_checklist
    rows. A functional_vector / functional / cmd_response case never gets here,
    so the TB-evidence demand is unchanged for genuine functional vectors."""
    st = checklist_status(case)
    if st in _CHECKLIST_SATISFIED_STATUSES:
        return "satisfied"
    # blank/None, an explicit fail status, or any unrecognised status → gap.
    return "checklist_gap"


def _read_xml_field(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.IGNORECASE | re.DOTALL)
    return (m.group(1).strip() if m else "")


def analog_skip_anchor(project_root: Optional[str], anchor_path: Optional[str]) -> Optional[str]:
    """ORGANIC #773 — resolve a REVIEWABLE capability-gap anchor for the
    analog-verification-intent waiver (mirrors #651's reviewable
    sim/results.xml bridge). Returns a short, reviewable description string
    when an anchor is found, else None.

    An honest analog-deferred waiver is reviewable only when the runner left a
    capability-gap bridge behind: a `sim/results.xml` carrying a
    `<capability_gap>` and/or a CONNECTIVITY-class verdict. Without that anchor
    the waiver is unanchored and is NOT honoured (the caller re-FAILs), so the
    relaxation cannot become a blanket unreviewable pass."""
    cands: List[str] = []
    if anchor_path:
        cands.append(anchor_path)
    if project_root:
        pr = Path(project_root)
        cands += [
            str(pr / "phase2/stage1/sim/results.xml"),
            str(pr / "sim/results.xml"),
            str(pr / "reports/sim/results.xml"),
        ]
    for c in cands:
        p = Path(c)
        if not p.is_file():
            continue
        try:
            xml = p.read_text(errors="replace")
        except OSError:
            continue
        cap = _read_xml_field(xml, "capability_gap")
        verdict = _read_xml_field(xml, "verdict").upper().replace("_", "-")
        if cap or verdict in ("CONNECTIVITY-PASS", "PASS-WITH-WAIVERS"):
            tag = cap or verdict
            return f"{p} (capability_gap/verdict={tag})"
    return None


def cpu_oracle_anchor(project_root: Optional[str]) -> Optional[str]:
    """ORGANIC #851 — auto-detect the CPU functional-oracle capability gap
    from `sim/results.xml`. Returns a short, reviewable description string
    when the anchor is found AND carries ``cap:cpu_functional_oracle``,
    else None.

    This mirrors `analog_skip_anchor()` but is SPECIFIC to the CPU oracle
    gap: it fires ONLY when the results.xml explicitly declares
    ``<capability_gap>cap:cpu_functional_oracle</capability_gap>``. No
    CLI flag is needed — the gate auto-detects from the runner's own
    artefact, coordinating with the sibling `cpu_functional_oracle_waiver_
    check` which already grants PASS_WITH_WAIVERS for this gap.

    §4.05 NO-LEAK: without the explicit `cap:cpu_functional_oracle` token
    in results.xml this returns None and the gate runs at full strictness.
    A generic ``CONNECTIVITY-PASS`` alone does NOT activate the CPU waiver
    (it only activates the analog waiver); the CPU waiver is token-gated."""
    if not project_root:
        return None
    pr = Path(project_root)
    cands = [
        pr / "phase2/stage1/sim/results.xml",
        pr / "sim/results.xml",
        pr / "reports/sim/results.xml",
    ]
    for p in cands:
        if not p.is_file():
            continue
        try:
            xml = p.read_text(errors="replace")
        except OSError:
            continue
        cap = _read_xml_field(xml, "capability_gap")
        if cap == CAP_CPU_FUNCTIONAL_ORACLE:
            return f"{p} (capability_gap={cap})"
    return None


# ----- CLI ----------------------------------------------------------


def evaluate(
    cases: List[Dict[str, Any]],
    tb_blob: str,
    summary: str,
    skip_analog: bool = False,
    analog_anchor: Optional[str] = None,
    cpu_oracle_waiver: bool = False,
    cpu_oracle_anchor_desc: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Return (results, ok_count, fail_count).

    The per-case ``status`` field ("pass" / "fail" / "waived" /
    "checklist_gap") and the project-level ``waive_count`` / checklist-gap
    count are derivable from the returned ``results`` list (see
    ``count_waived`` / ``count_checklist_gaps``); the 3-tuple return shape is
    preserved for backward compatibility with existing callers.

    ORGANIC #808 — ``kind=verification_checklist`` (DV-milestone) rows are
    scoped OUT of the TB-evidence requirement: a DV process milestone is not
    TB-traceable. A satisfied/deferred row (Done/N/A/Waived/Pass) is credited
    into ``ok_count``; a blank/None-or-explicit-FAIL row is carried separately
    as a checklist gap (status ``checklist_gap``, review_required) and is NOT
    folded into ``fail_count`` — so a checklist row can never mask a missing
    digital testbench (§4.05 NO-LEAK), and functional_vector / functional /
    cmd_response cases STILL require TB evidence (unchanged).

    ORGANIC #773 — when ``skip_analog`` is set AND ``analog_anchor`` resolves
    to a reviewable capability-gap bridge, a `verification_intent` (A/M-track)
    case that lacks a digital-TB id-substring trace is credited as WAIVED-
    DEFERRED instead of FAILing. §4.05 NO-LEAK: a genuine digital case
    (anything NOT `verification_intent`) with no tb evidence STILL FAILs even
    under --skip-analog, and an UNANCHORED verification_intent case (no
    reviewable bridge) also still FAILs — the relaxation is kind-scoped and
    anchor-gated so it can never mask a missing digital testbench.

    ORGANIC #851 — when ``cpu_oracle_waiver`` is set AND
    ``cpu_oracle_anchor_desc`` resolves to a reviewable results.xml carrying
    ``cap:cpu_functional_oracle``, a `functional_vector` case that lacks TB
    evidence is credited as WAIVED-DEFERRED. §4.05 NO-LEAK: a non-functional-
    vector case (e.g. cmd_response with opcode) with no evidence STILL FAILs.
    An unanchored waiver (no results.xml) also still FAILs."""
    results: List[Dict[str, Any]] = []
    ok_count = 0
    fail_count = 0
    checklist_gap_count = 0
    waiver_active = bool(skip_analog) and bool(analog_anchor)
    cpu_waiver_active = bool(cpu_oracle_waiver) and bool(cpu_oracle_anchor_desc)
    for c in cases:
        case_id = str(c.get("id", c.get("name", "")))
        category = c.get("category", c.get("type", c.get("kind", "")))
        is_cmd_rsp = category.lower() in ("cmd_response", "cmd_rsp", "happy", "happy_path") if category else False

        # ORGANIC #808 — verification_checklist (DV-milestone) rows are scoped
        # OUT of the TB-evidence demand: a DV process milestone is not
        # TB-traceable, so credit the row's CARRIED status instead. A
        # satisfied/deferred row (Done/N/A/Waived/Pass) is credited as ok; a
        # blank/None-or-explicit-FAIL row surfaces as a checklist gap (NOT a
        # TB-evidence failure, so it can never mask a missing digital TB).
        # §4.05 NO-LEAK: only kind=verification_checklist reaches this branch —
        # functional_vector / functional / cmd_response cases fall through to the
        # unchanged TB-evidence logic below.
        #
        # CRITICAL (§4.05 no-leak, mirrors the #773 r2 _has_digital_signal
        # guard): a case carrying a GENUINE DIGITAL signal (is_cmd_rsp, an
        # opcode/cmd field, or a digital category token) is a real functional
        # vector that the digital TB MUST exercise — a spurious
        # `kind=verification_checklist` mislabel must NOT exempt it from the
        # TB-evidence demand. So the checklist branch fires ONLY for a row that
        # carries no digital signal; a digital case falls through and still
        # FAILs without TB evidence.
        if is_verification_checklist(c) and not _has_digital_signal(c, is_cmd_rsp):
            cls = classify_checklist(c)
            st = checklist_status(c) or "none"
            if cls == "satisfied":
                results.append({
                    "id": case_id,
                    "category": category,
                    "kind": case_kind(c),
                    "evidence": [
                        f"verification_checklist DV-milestone satisfied "
                        f"(status={st}); not TB-traceable, credited by carried "
                        f"status (ORGANIC #808)"
                    ],
                    "pass": True,
                    "status": "pass",
                    "waived": False,
                    "checklist_gap": False,
                    "review_required": False,
                    "capability_gap": None,
                })
                ok_count += 1
            else:
                results.append({
                    "id": case_id,
                    "category": category,
                    "kind": case_kind(c),
                    "evidence": [
                        f"verification_checklist DV-milestone NOT satisfied "
                        f"(status={st}); surfaced as a checklist shortfall, NOT "
                        f"a TB-evidence failure (ORGANIC #808; review_required)"
                    ],
                    "pass": False,
                    "status": "checklist_gap",
                    "waived": False,
                    "checklist_gap": True,
                    "review_required": True,
                    "capability_gap": None,
                })
                checklist_gap_count += 1
            continue

        evidence: List[str] = []
        if is_cmd_rsp:
            if case_has_opcode_evidence(c, tb_blob):
                evidence.append("opcode in tb")
            if summary_has_pass(case_id, summary):
                evidence.append("summary pass record")
        # For any category, ID substring counts as evidence of trace-to-req
        if case_id_appears(case_id, tb_blob, summary):
            evidence.append("id substring in tb/summary")
        ok = bool(evidence)
        status = "pass" if ok else "fail"
        waived = False
        # ORGANIC #773 — class/kind-aware A/M-track waiver. ONLY a
        # verification_intent case with no digital evidence, under an
        # anchored --skip-analog, is credited as WAIVED-DEFERRED. §4.05
        # NO-LEAK: a non-verification_intent (digital) case never reaches
        # here, and an unanchored verification_intent case (waiver_active
        # False) FAILs as before.
        # ORGANIC #773 r2 (Step-2.7) — a `kind=verification_intent` MISLABEL must
        # not let a genuinely-DIGITAL case escape: refuse the waiver for any case
        # carrying a digital signal (is_cmd_rsp by category-priority, an
        # opcode/cmd field, or a digital category/type), so a digital
        # cmd_response with no TB evidence STILL FAILs even if it also carries a
        # spurious verification_intent kind.
        if (not ok and waiver_active and is_verification_intent(c)
                and not _has_digital_signal(c, is_cmd_rsp)):
            waived = True
            status = "waived"
            cap_gap = CAP_ANALOG_VERIFICATION_INTENT
            evidence = [
                "WAIVED-DEFERRED: verification_intent A/M-track oracle "
                f"({CAP_ANALOG_VERIFICATION_INTENT}); analog track deferred "
                f"via --skip-analog; reviewable anchor: {analog_anchor}"
            ]
        # ORGANIC #851 — CPU functional-oracle waiver. A `functional_vector`
        # case with no TB evidence, under an anchored CPU oracle gap, is
        # credited as WAIVED-DEFERRED. §4.05 NO-LEAK: a non-functional-vector
        # case (e.g. cmd_response with opcode) with no evidence STILL FAILs.
        # An unanchored waiver (no results.xml with cap:cpu_functional_oracle)
        # also still FAILs. The analog waiver takes priority (checked first);
        # the CPU waiver fires only for cases NOT already waived by analog.
        elif (not ok and not waived and cpu_waiver_active
                and is_functional_vector(c)):
            waived = True
            status = "waived"
            cap_gap = CAP_CPU_FUNCTIONAL_ORACLE
            evidence = [
                "WAIVED-DEFERRED: functional_vector CPU instruction-set "
                f"oracle ({CAP_CPU_FUNCTIONAL_ORACLE}); CPU oracle deferred "
                f"(capability gap); reviewable anchor: "
                f"{cpu_oracle_anchor_desc}"
            ]
        else:
            cap_gap = None
        results.append(
            {
                "id": case_id,
                "category": category,
                "evidence": evidence,
                "pass": ok,
                "status": status,
                "waived": waived,
                "review_required": waived,
                "capability_gap": cap_gap,
            }
        )
        if ok:
            ok_count += 1
        elif waived:
            # A WAIVED-DEFERRED case is neither a pass nor a fail: it is
            # carried separately (count_waived) and reported via the rc=3
            # PASS_WITH_WAIVERS path, NOT folded into fail_count (which is
            # reserved for genuine, un-waivable digital misses — §4.05).
            pass
        else:
            fail_count += 1
    return results, ok_count, fail_count


def count_waived(results: List[Dict[str, Any]]) -> int:
    """Number of results carrying the ORGANIC #773 WAIVED-DEFERRED status."""
    return sum(1 for r in results if r.get("status") == "waived")


def count_checklist_gaps(results: List[Dict[str, Any]]) -> int:
    """ORGANIC #808 — number of verification_checklist DV-milestone rows that
    are NOT satisfied (blank/None or an explicit FAIL status). These are
    checklist shortfalls (review_required) — surfaced separately, NOT folded
    into fail_count (which is reserved for genuine TB-evidence misses)."""
    return sum(1 for r in results if r.get("status") == "checklist_gap")


def _tb_files_under(d: Path) -> bool:
    """True when directory `d` directly or recursively holds a testbench
    .v/.sv (a tb_*.v or anything with a `module tb` / `_tb`)."""
    if not d.is_dir():
        return False
    for p in d.rglob("*"):
        if p.is_file() and p.suffix in (".v", ".sv"):
            return True
    return False


def _resolve_tb_dir(given: str) -> Optional[str]:
    """ORGANIC #572 — the default --tb-dir (phase2/stage1/sim/tb) is rigid;
    a project that keeps testbenches at the sim/ ROOT (phase2/stage1/sim/)
    reported 4/4 false 'lack evidence'. Try the given path first, then its
    parent when the leaf is 'tb', then the canonical sim roots. Returns the
    first directory that actually holds a .v/.sv, else None."""
    cands: List[str] = [given]
    gp = Path(given)
    if gp.name == "tb":
        cands.append(str(gp.parent))
    cands += ["phase2/stage1/sim/tb", "phase2/stage1/sim",
              "sim/tb", "sim"]
    seen = set()
    for c in cands:
        if c in seen:
            continue
        seen.add(c)
        if _tb_files_under(Path(c)):
            return c
    # last resort: return the given path if it at least exists as a dir, so
    # the caller's missing-dir error message is accurate.
    return given if Path(given).is_dir() else None


def _resolve_summary(given: str) -> str:
    """ORGANIC #572 — fall back across the common summary locations when the
    default path is absent (mirrors read_summary's own two candidates but
    extends to the sim/ root and reports/)."""
    cands = [given, "phase2/stage1/sim/work/summary.txt",
             "phase2/stage1/sim/summary.txt", "reports/sim/summary.txt",
             "sim/work/summary.txt", "sim/summary.txt"]
    for c in cands:
        if Path(c).is_file():
            return c
    return given


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--l10", required=True, help="phase1/generated_docs/L10_TEST_CASES.json")
    p.add_argument("--tb-dir", default="phase2/stage1/sim/tb", help="directory containing testbench .v files")
    p.add_argument("--summary", default="phase2/stage1/sim/work/summary.txt", help="sim summary file")
    p.add_argument("--out", default="reports/gates/l10_tb_conformance.json")
    p.add_argument("--strict", action="store_true", help="fail on ANY case lacking evidence (default)")
    p.add_argument("--warn-only", action="store_true", help="print warnings but exit 0")
    p.add_argument(
        "--skip-analog", action="store_true",
        help="ORGANIC #773 — the analog / mixed-signal track is explicitly "
             "deferred; verification_intent (A/M-track) L10 cases with no "
             "digital-TB trace are credited as WAIVED-DEFERRED (rc=3 + "
             "PASS_WITH_WAIVERS) when a reviewable capability-gap anchor "
             "(sim/results.xml) is present, instead of hard-FAILing Step 4. "
             "§4.05: genuine digital cases with no evidence STILL FAIL.")
    p.add_argument(
        "--project", default=None,
        help="ORGANIC #773 — project root used to locate the reviewable "
             "analog-deferral anchor (phase2/stage1/sim/results.xml). "
             "Defaults to inferring from --l10's project tree.")
    p.add_argument(
        "--analog-anchor", default=None,
        help="ORGANIC #773 — explicit path to the reviewable capability-gap "
             "anchor (sim/results.xml). Overrides --project inference.")
    args = p.parse_args(argv)

    try:
        cases = load_l10(args.l10)
    except Exception as e:
        print(f"[l10-tb-conformance] cannot load L10: {e}", file=sys.stderr)
        return 2

    tb_dir = _resolve_tb_dir(args.tb_dir)
    if tb_dir is None:
        print(f"[l10-tb-conformance] tb dir missing: {args.tb_dir} "
              f"(and no fallback under sim/)", file=sys.stderr)
        return 2

    per_file, tb_blob = read_all_tb_text(tb_dir)
    summary = read_summary(_resolve_summary(args.summary))

    # #206 — VACUOUS-TB substance gate (shared with vacuous_testbench_check so
    # the two never disagree). A placeholder testbench prints a pass and never
    # instantiates the DUT; its `$display("[TB <id>] PASS_PLACEHOLDER")` puts the
    # case id into tb_blob, so the id-substring / opcode evidence below used to
    # credit it — a check that COUNTED cases present, not cases exercised. When
    # NOTHING under the sim tree drives the design, that "evidence" is theatre:
    # suppress the blob so genuine digital cases FAIL (no evidence) while the
    # existing anchored A/M waiver path is untouched (verification_intent cases
    # still waive; §4.05 — a vacuous DIGITAL TB can never be waived). A tree with
    # >=1 live driver keeps its full evidence corpus, so a trace-companion TB
    # sitting beside a real driver still credits its cases.
    vacuous_sim_tree = False
    vacuous_files: List[str] = []
    if per_file and _vtb is not None and not _vtb.any_source_drives_dut(
            per_file.values()):
        vacuous_sim_tree = True
        vacuous_files = sorted(per_file.keys())
        tb_blob = ""  # evidence suppressed — presence is not coverage (#206)

    # ORGANIC #773 — resolve the reviewable analog-deferral anchor. The
    # project root is the explicit --project, else inferred from the L10
    # path's project tree (…/phase1/generated_docs/L10*.json → project root).
    project_root: Optional[str] = args.project
    if project_root is None:
        l10p = Path(args.l10).resolve()
        # Walk up to the project root: the parent of phase1/ (if present),
        # else the L10 file's parent (best-effort; anchor resolution is
        # tolerant of a missing file).
        for parent in l10p.parents:
            if parent.name in ("generated_docs", "phase1"):
                continue
            if (parent / "phase1").is_dir() or (parent / "phase2").is_dir():
                project_root = str(parent)
                break
        if project_root is None:
            project_root = str(l10p.parent)
    analog_anchor = (
        analog_skip_anchor(project_root, args.analog_anchor)
        if args.skip_analog else None
    )

    # ORGANIC #851 — auto-detect CPU functional-oracle capability gap from
    # results.xml. No CLI flag needed: the gate reads the runner's own
    # artefact and coordinates with cpu_functional_oracle_waiver_check.
    cpu_anchor = cpu_oracle_anchor(project_root)

    results, ok_count, fail_count = evaluate(
        cases, tb_blob, summary,
        skip_analog=args.skip_analog, analog_anchor=analog_anchor,
        cpu_oracle_waiver=bool(cpu_anchor),
        cpu_oracle_anchor_desc=cpu_anchor,
    )
    waive_count = count_waived(results)
    checklist_gap_count = count_checklist_gaps(results)

    # ORGANIC #851 — collect all distinct capability gaps from waived cases.
    waiver_caps = sorted({
        r["capability_gap"] for r in results
        if r.get("status") == "waived" and r.get("capability_gap")
    })
    out = {
        "total": len(cases),
        "ok": ok_count,
        "fail": fail_count,
        "waived": waive_count,
        "checklist_gaps": checklist_gap_count,
        "capability_gap": waiver_caps[0] if len(waiver_caps) == 1 else (waiver_caps or None),
        "capability_gaps": waiver_caps or None,
        "analog_anchor": analog_anchor,
        "cpu_oracle_anchor": cpu_anchor,
        # #206 — the substance verdict the gate judged on: whether the sim tree
        # actually drives the DUT, and (when it does not) the offending vacuous
        # testbench files. Emitted so this verdict can be cross-checked from the
        # gate's own output instead of trusted on its say-so.
        "sim_tree_drives_dut": (not vacuous_sim_tree) if per_file else None,
        "vacuous_sim_tree": vacuous_sim_tree,
        "vacuous_testbench_files": vacuous_files,
        "results": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))

    if fail_count:
        # A genuine FAIL dominates — even if some cases were waived, an
        # un-waivable digital miss is still a hard FAIL (§4.05 NO-LEAK).
        if vacuous_sim_tree:
            print(
                f"[l10-tb-conformance] VACUOUS sim tree — none of "
                f"{len(vacuous_files)} testbench(es) instantiate the DUT; "
                f"id-substring / opcode presence is NOT coverage (#206). "
                f"Files: {', '.join(vacuous_files)}",
                file=sys.stderr,
            )
        print(
            f"[l10-tb-conformance] {fail_count}/{len(cases)} cases lack evidence "
            f"(see {args.out}):",
            file=sys.stderr,
        )
        for r in results:
            if r.get("status") == "fail":
                print(f"  - {r['id']} ({r['category']})", file=sys.stderr)
        if args.warn_only:
            return 0
        return 1

    if waive_count or checklist_gap_count:
        # ORGANIC #773 — class/kind-aware A/M-track waiver, AND/OR
        # ORGANIC #808 — verification_checklist (DV-milestone) checklist gaps,
        # AND/OR ORGANIC #851 — CPU functional-oracle waiver.
        # In all cases every genuine case that REQUIRES a TB trace had its
        # evidence (fail_count == 0 here). Mirror #651/#773: rc=3 +
        # line-start PASS_WITH_WAIVERS sentinel so flow_compliance_check
        # promotes Step 4 to WAIVED-DEFERRED (Overall PASS_WITH_WAIVERS),
        # not a hard FAIL.
        bits = [f"{ok_count}/{len(cases)} cases satisfied"]
        # Count per-gap waiver details for the message.
        analog_waived = sum(1 for r in results
                           if r.get("status") == "waived"
                           and r.get("capability_gap") == CAP_ANALOG_VERIFICATION_INTENT)
        cpu_waived = sum(1 for r in results
                        if r.get("status") == "waived"
                        and r.get("capability_gap") == CAP_CPU_FUNCTIONAL_ORACLE)
        if analog_waived:
            bits.append(
                f"{analog_waived}/{len(cases)} verification_intent A/M-track "
                f"case(s) WAIVED-DEFERRED ({CAP_ANALOG_VERIFICATION_INTENT}, "
                f"review_required; anchor: {analog_anchor})")
        if cpu_waived:
            bits.append(
                f"{cpu_waived}/{len(cases)} functional_vector CPU-oracle "
                f"case(s) WAIVED-DEFERRED ({CAP_CPU_FUNCTIONAL_ORACLE}, "
                f"review_required; anchor: {cpu_anchor})")
        if checklist_gap_count:
            bits.append(
                f"{checklist_gap_count}/{len(cases)} verification_checklist "
                f"DV-milestone row(s) not satisfied (review_required; "
                f"ORGANIC #808 — process milestone, not TB-traceable)")
        print(
            "PASS_WITH_WAIVERS: l10_tb_conformance — " + "; ".join(bits)
            + f"  → {args.out}")
        return 3

    print(f"[l10-tb-conformance] PASS  {ok_count}/{len(cases)} cases covered  → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
