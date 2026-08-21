#!/usr/bin/env python3
"""Smoke tests for l20_dft_scan_topology_actionable_check.py (layergate-7).

NEGATIVE CONTROL IS THE POINT
=============================
Every behaviour below is asserted in BOTH directions: a deliberately
gutted layer must FAIL, and the well-formed counterpart must PASS. A
test that only ever sees the passing side proves nothing — that is how
the L21 completeness check shipped a CAPTURED verdict for a layer that
contained the requirement zero times.

All fixtures are SYNTHESISED neutral data. No real design's files are
copied, and no fixture carries a design name, PDK name or vendor part
number.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l20_dft_scan_topology_actionable_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


def _mk(tmp_path, l20=None, docs=None, siblings=None, dft_artifacts=False,
        waivers=None):
    proj = tmp_path / "p"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    if l20 is not None:
        (gd / "L20_DFT_SCAN_TOPOLOGY.json").write_text(
            json.dumps(l20), encoding="utf-8")
    for code, payload in (siblings or {}).items():
        (gd / f"{code}_SYNTH.json").write_text(json.dumps(payload),
                                               encoding="utf-8")
    if docs:
        dd = proj / "phase1" / "input_doc"
        dd.mkdir(parents=True, exist_ok=True)
        for name, text in docs.items():
            (dd / name).write_text(text, encoding="utf-8")
    if dft_artifacts:
        da = proj / "phase2" / "stage2" / "dft"
        da.mkdir(parents=True, exist_ok=True)
        (da / "scan_netlist_prelim.v").write_text(
            "module synth_top(input a, output b); endmodule\n",
            encoding="utf-8")
    if waivers:
        (proj / "waivers.json").write_text(json.dumps(waivers),
                                           encoding="utf-8")
    return proj


# The skeleton every real run emits: honest, asserts nothing.
_SKELETON = {
    "doc_id": "L20",
    "doc_name": "L20_DFT_SCAN_TOPOLOGY",
    "applicability": "APPLICABLE",
    "fields": {
        "scan_chains": [],
        "test_compression": None,
        "bist_mbist": [],
        "jtag_tap": None,
        "dft_present": False,
    },
    "extraction_status": "NOT_YET_EXTRACTED",
    "extraction_evidence": {},
}

_TYPED_CHAIN = {
    "name": "chain_0",
    "length": 128,
    "scan_in": "si_0",
    "scan_out": "so_0",
    "clock": "shift_clk",
}

# Synthetic requirement text. Technology vocabulary + requirement
# framing; carries no design identity.
_DFT_REQUIREMENT_DOC = (
    "3.2 Test Requirements\n"
    "The device shall provide a full scan chain covering all sequential\n"
    "elements. ATPG stuck-at coverage must be at least 95%. A JTAG TAP\n"
    "controller is required for boundary scan access.\n"
)
_NO_DFT_DOC = (
    "3.2 Functional Requirements\n"
    "The device shall accept a 32-bit operand and produce a result within\n"
    "four cycles. The output must be registered.\n"
)


# ── skips ────────────────────────────────────────────────────────────

def test_skip_when_no_l20(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    assert _run(proj).returncode == 2


def test_skip_when_not_applicable(tmp_path):
    doc = dict(_SKELETON, applicability="NOT_APPLICABLE")
    r = _run(_mk(tmp_path, l20=doc, docs={"spec.txt": _DFT_REQUIREMENT_DOC}))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "SKIP" in r.stdout


# ── F1 VACUOUS_DFT_ASSERTION — negative control pair ─────────────────

def test_NEGATIVE_CONTROL_fail_dft_asserted_but_no_chains(tmp_path):
    """GUTTED: an EXTRACTED L20 claims DFT exists and carries zero chains.

    `extraction_status` is what makes the field values the DESIGN's claim
    rather than the emitter's skeleton — see the twin below, which is the same
    fixture WITHOUT it. Through vibe-ic#1003 this fixture omitted the status
    and still reddened, which is why 48 of 106 published roots reddened on a
    literal 50 protocol emitters write unconditionally.
    """
    doc = json.loads(json.dumps(_SKELETON))
    doc["extraction_status"] = "EXTRACTED"
    doc["fields"]["dft_present"] = True
    doc["fields"]["jtag_tap"] = {"tck": "tck", "tms": "tms"}
    r = _run(_mk(tmp_path, l20=doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VACUOUS_DFT_ASSERTION" in r.stdout


def test_an_UNEXTRACTED_layer_asserts_nothing_with_the_same_fields(tmp_path):
    """The twin of the test above, differing ONLY in extraction_status.

    vibe-ic#1003. `dft_present` on a layer that has never been extracted is the
    producer's field default, not a design's assertion — the identical rule
    `dft_atpg_coverage_check` already applies to this same field in the
    opposite direction ("its `dft_present: false` is the emitter's field
    default, not a decision").

    The pair is the whole argument: same fields, same empty `scan_chains[]`,
    one bit of provenance apart, and only the one whose layer says its content
    is real is held to the consumer contract.
    """
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["dft_present"] = True
    doc["fields"]["jtag_tap"] = {"tck": "tck", "tms": "tms"}
    r = _run(_mk(tmp_path, l20=doc))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS_DFT_ASSERTION" not in r.stdout, r.stdout


def test_a_producer_default_string_is_not_an_assertion_either(tmp_path):
    """The exact corpus value: `dft_present: "partial"` on a skeleton.

    54 of the 106 tracked L20 documents carry this string, written
    unconditionally by 50 protocol emitters, every one of them beside an
    enumerated NON-scan test surface. It is a true statement about a protocol
    that has in-band test facilities and no scan chain; it is not a claim that
    a scan topology exists.
    """
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["dft_present"] = "partial"
    doc["fields"]["in_band_test_facilities"] = [
        {"name": "link error counter", "purpose": "run-time observability"}]
    r = _run(_mk(tmp_path, l20=doc))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS_DFT_ASSERTION" not in r.stdout, r.stdout


def test_POSITIVE_CONTROL_pass_dft_asserted_with_typed_chain(tmp_path):
    """WELL-FORMED: same assertion, backed by a reconcilable chain."""
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["dft_present"] = True
    doc["fields"]["jtag_tap"] = {"tck": "tck", "tms": "tms"}
    doc["fields"]["scan_chains"] = [_TYPED_CHAIN]
    r = _run(_mk(tmp_path, l20=doc))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_NEGATIVE_CONTROL_fail_chain_missing_reconcilable_fields(tmp_path):
    """GUTTED: a chain exists but ATPG cannot reconcile against it."""
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["dft_present"] = True
    doc["fields"]["scan_chains"] = [{"name": "chain_0"}]
    r = _run(_mk(tmp_path, l20=doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VACUOUS_DFT_ASSERTION" in r.stdout
    for field in ("length", "scan_in", "scan_out", "clock"):
        assert field in r.stdout


def test_extraction_that_ran_and_found_nothing_is_not_a_vacuous_claim(tmp_path):
    """RAN-AND-EMPTY is a design saying "I need no DFT", not a broken claim.

    vibe-ic#1003, second half of the same disjunct. `is_extraction_claimed`
    used to count as an assertion ON ITS OWN, so a layer that ran extraction
    and honestly recorded nothing — the ONE state that is a real statement of
    absence — was reported as making a claim it could not back.
    `l_doc_consumer_contract.is_extraction_claimed.__doc__` names the three
    producer states and says only RAN-AND-EMPTY means "I need no DFT".

    The layer still has no immunity: the test above shows the same EXTRACTED
    status DOES redden the moment the layer asserts a DFT field beside an empty
    `scan_chains[]`.
    """
    doc = json.loads(json.dumps(_SKELETON))
    doc["extraction_status"] = "EXTRACTED"
    r = _run(_mk(tmp_path, l20=doc))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS_DFT_ASSERTION" not in r.stdout, r.stdout


def test_a_chain_is_typed_even_on_an_unextracted_layer(tmp_path):
    """CONTENT IS SELF-EVIDENCING — the extraction guard must not reach it.

    The guard added for vibe-ic#1003 covers the assertion-WITHOUT-content arm
    only. A `scan_chains[]` somebody actually wrote is a topology regardless of
    provenance, and it is still held to the typing contract. If this ever goes
    green, the guard has been widened past the defect it was measured for.
    """
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["scan_chains"] = [{"name": "chain_0"}]
    r = _run(_mk(tmp_path, l20=doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VACUOUS_DFT_ASSERTION" in r.stdout


# ── F2 REQUIREMENT_OUTSIDE_CONSUMING_LAYER — negative control pair ───

def test_NEGATIVE_CONTROL_fail_requirement_in_docs_absent_from_l20(tmp_path):
    """GUTTED: the L21 shape — requirement present in the design's own
    input doc, absent from the layer a DFT step consumes."""
    r = _run(_mk(tmp_path, l20=_SKELETON,
                 docs={"spec.txt": _DFT_REQUIREMENT_DOC}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" in r.stdout


def test_POSITIVE_CONTROL_pass_requirement_present_in_l20(tmp_path):
    """WELL-FORMED: same requirement, now carried by L20 itself."""
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["dft_present"] = True
    doc["fields"]["scan_chains"] = [_TYPED_CHAIN]
    doc["fields"]["jtag_tap"] = {"tck": "tck", "tms": "tms", "tdi": "tdi",
                                 "tdo": "tdo"}
    r = _run(_mk(tmp_path, l20=doc,
                 docs={"spec.txt": _DFT_REQUIREMENT_DOC}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_NEGATIVE_CONTROL_fail_requirement_in_sibling_l_doc(tmp_path):
    """GUTTED: requirement lives in a sibling layer, not the consumer."""
    sib = {"doc_id": "L7", "fields": {
        "test_modes": ["The design shall support full scan chain "
                       "insertion with ATPG coverage of at least 95%."]}}
    r = _run(_mk(tmp_path, l20=_SKELETON, siblings={"L7": sib}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" in r.stdout


def test_no_requirement_no_assertion_skips(tmp_path):
    """The honest skeleton on a design that asks for no DFT: SKIP.

    This is the 136/136 fleet shape. If this ever starts failing, the
    gate has become a flow-stopper on legitimately-silent layers.
    """
    r = _run(_mk(tmp_path, l20=_SKELETON, docs={"spec.txt": _NO_DFT_DOC}))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "SKIP" in r.stdout


def test_bare_vocabulary_without_requirement_framing_does_not_fire(tmp_path):
    """A passing mention is not a requirement.

    Measured calibration: an earlier draft accepted a bare ``>`` as
    framing, so a reStructuredText link (``…stages-v>`_.``) turned a
    STATUS sentence into a requirement. Framing must be a real
    requirement word or a two-character comparison operator.
    """
    doc_text = ("Appendix B. The evaluation board exposes a jtag header\n"
                "for the on-board debugger; see `the vendor guide\n"
                "<https://example.invalid/guide.html#jtag-v>`_.\n")
    r = _run(_mk(tmp_path, l20=_SKELETON, docs={"appendix.txt": doc_text}))
    assert r.returncode == 2, r.stdout + r.stderr


# ── F3 BACKEND_INSERTED_UNDECLARED_TOPOLOGY — advises, never blocks ──

def test_backend_artifacts_advise_but_do_not_block(tmp_path):
    """Scan insertion ran, L20 declares none: ADVISE, exit 0.

    ADVISES because nothing reads L20 today. If this assertion ever
    flips to returncode == 1, DFT insertion has been wired to L20 and
    the finding must be promoted deliberately, not by accident.
    """
    r = _run(_mk(tmp_path, l20=_SKELETON, dft_artifacts=True))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[ADVISE]" in r.stdout
    assert "BACKEND_INSERTED_UNDECLARED_TOPOLOGY" in r.stdout


def test_advisory_alone_never_prints_fail(tmp_path):
    r = _run(_mk(tmp_path, l20=_SKELETON, dft_artifacts=True))
    assert "[FAIL]" not in r.stdout


# ── waiver ───────────────────────────────────────────────────────────

def test_waiver_suppresses_blocking_finding(tmp_path):
    proj = _mk(tmp_path, l20=_SKELETON,
               docs={"spec.txt": _DFT_REQUIREMENT_DOC},
               waivers=[{"id": "l20_dft_topology_deferred_to_soc_integration",
                         "rationale": "Scan insertion is performed by the "
                                      "SoC integrator against the delivered "
                                      "soft macro; no chain exists at block "
                                      "level."}])
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr


def test_short_waiver_rationale_does_not_waive(tmp_path):
    """A one-word excuse is not a waiver."""
    proj = _mk(tmp_path, l20=_SKELETON,
               docs={"spec.txt": _DFT_REQUIREMENT_DOC},
               waivers=[{"id": "l20_dft_topology_deferred_to_soc_integration",
                         "rationale": "later"}])
    assert _run(proj).returncode == 1


# ── report emission (so findings can be distilled, not lost) ─────────

def test_writes_machine_readable_report(tmp_path):
    proj = _mk(tmp_path, l20=_SKELETON,
               docs={"spec.txt": _DFT_REQUIREMENT_DOC})
    _run(proj)
    rpt = (proj / "reports" / "phase1"
           / "l20_dft_scan_topology_actionable_check.json")
    assert rpt.is_file()
    data = json.loads(rpt.read_text())
    assert data["verdict"] == "FAIL"
    assert data["blocking_findings"][0]["evidence"]


# ── the cascade into the Step-36 bubble-up gate (vibe-ic#1003) ────────
#
# This gate WRITES `reports/phase1/<gate>.json` unconditionally, and
# `step_internal_fail_bubble_up_check` (Step 36, BLOCKING) scans
# `reports/**/*.json` for `verdict`. So an ADVISORY finding from this gate
# arrives at the step that signs off as a BLOCKING one, which is a declaration
# being overridden by a side effect. The tests below DRIVE both gates rather
# than asserting the coupling in prose.

_BUBBLE = (Path(__file__).resolve().parent.parent
           / "step_internal_fail_bubble_up_check.py")


def _bubble(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_BUBBLE), str(project)],
                          capture_output=True, text=True)


def _clean_project_with_a_real_report(tmp_path):
    """A project the bubble-up gate examines and passes.

    The PASS report is load-bearing: it gives that gate a real denominator, so
    rc 0 means "examined and clean" rather than its rc 2 refusal — otherwise
    the before/after below would compare two refusals.
    """
    proj = _mk(tmp_path, l20=_SKELETON, docs={"spec.txt": _DFT_REQUIREMENT_DOC})
    rp = proj / "reports" / "phase2"
    rp.mkdir(parents=True, exist_ok=True)
    (rp / "some_step.json").write_text(json.dumps({"verdict": "PASS"}),
                                       encoding="utf-8")
    return proj


def test_the_cascade_is_real_when_the_report_declares_nothing(tmp_path):
    """CONTROL for the fix: the default still cascades, exactly as today.

    `--verdict-mode` defaults to BLOCKS so no existing caller changes
    behaviour. This test is what proves the fix below is measuring the flag and
    not measuring some unrelated drift in either gate.
    """
    proj = _clean_project_with_a_real_report(tmp_path)
    before = _bubble(proj)
    assert before.returncode == 0, before.stdout + before.stderr

    gate = _run(proj)
    assert gate.returncode == 1, gate.stdout + gate.stderr

    after = _bubble(proj)
    assert after.returncode == 1, after.stdout + after.stderr
    assert ("l20_dft_scan_topology_actionable_check"
            in after.stdout + after.stderr)


def test_declaring_ADVISES_removes_the_cascade(tmp_path):
    """A finding the flow wired ADVISORY must not redden the blocking step.

    `verdict_mode: ADVISES` is the repo's own convention, already honoured by
    `step_internal_fail_bubble_up_check` and parsed by
    `flow_gate_enforcement_audit`. Nothing new is invented here; this gate
    joins the gates that already speak it.
    """
    proj = _clean_project_with_a_real_report(tmp_path)
    before = _bubble(proj)
    assert before.returncode == 0, before.stdout + before.stderr

    gate = subprocess.run(
        [sys.executable, str(PROG), str(proj), "--verdict-mode", "ADVISES"],
        capture_output=True, text=True)
    # the FINDING is unchanged — only its declared enforcement mode moved
    assert gate.returncode == 1, gate.stdout + gate.stderr

    rpt = (proj / "reports" / "phase1"
           / "l20_dft_scan_topology_actionable_check.json")
    data = json.loads(rpt.read_text())
    assert data["verdict"] == "FAIL"
    assert data["verdict_mode"] == "ADVISES"

    after = _bubble(proj)
    assert after.returncode == 0, after.stdout + after.stderr
# ── vibe-ic#1011: F2 counted a DENIAL as evidence of a requirement ─────────
#
# DRIVEN through the CLI, not through `inspect()`, because the defect being
# fixed was a VERDICT: the gate FAILed 25 published run dirs, 16 of them on
# documents that say in so many words that the requirement does not exist.
#
# All fixtures are SYNTHETIC restatements of shapes measured on the corpus.
# No design, foundry, vendor, process or part token appears in any of them.

#: A sibling layer that DENIES having any DFT surface. Every phrase here is a
#: shape that was live on the published corpus.
_L7_DENIES_DFT = {
    "test_debug_architecture_present": False,
    "notes": ("<standard> does NOT specify JTAG / scan-chain / on-chip BIST "
              "at the protocol level. Conformance is established by the "
              "published compliance test specification."),
    "rationale": ("Neither <bus A> nor <bus B> defines a JTAG / scan / BIST "
                  "/ MBIST / debug architecture. There is no dedicated debug "
                  "interface in either protocol."),
    "ate_or_dft": ("No standard DFT / JTAG path is exposed on the host "
                   "interface; it is not specified at the protocol level."),
}

#: The SAME layer shape, asserting a DFT surface positively. This is the pair
#: that makes the test above mean something.
_L7_STATES_DFT = {
    "test_debug_architecture_present": True,
    "test_modes": [
        {"name": "Scan test",
         "purpose": ("Scan control / scan in / scan out drive the scan "
                     "chains that manufacturing DFT requires.")},
        {"name": "Boundary scan",
         "purpose": "A TAP controller is required for boundary scan access."},
    ],
}


def test_a_sibling_layer_that_DENIES_dft_no_longer_reddens_f2(tmp_path):
    """THE DEFECT. L20 is the honest empty skeleton and the design's own
    documents say there is nothing to carry, so there is no gap to report."""
    r = _run(_mk(tmp_path, l20=_SKELETON, siblings={"L7": _L7_DENIES_DFT}))
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" not in r.stdout, (
        "a document DENYING a DFT requirement was counted as stating one:\n"
        + r.stdout + r.stderr)
    assert r.returncode != 1, r.stdout + r.stderr


def test_a_sibling_layer_that_STATES_dft_still_reddens_f2(tmp_path):
    """THE PAIRED GUARD, and the reason the test above is not a ban.

    This is the shape of the ONE finding among the 25 that is unambiguously
    real: a sibling test-debug layer enumerating scan test and boundary scan
    while L20 carries neither. It MUST stay red, and it is asserted here on a
    synthetic twin so the corpus root is not needed to keep the guard alive.
    """
    r = _run(_mk(tmp_path, l20=_SKELETON, siblings={"L7": _L7_STATES_DFT}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" in r.stdout, (
        "the negation ruler deleted a REAL finding:\n" + r.stdout + r.stderr)


def test_an_input_doc_that_DENIES_dft_no_longer_reddens_f2(tmp_path):
    """The same question on the other evidence channel. Both `framed_hits`
    call sites in this gate opt in, and a fix applied to one of them would
    leave the other counting denials."""
    denial = ("3.2 Test Provisions\n"
              "The protocol does not specify a scan chain, and no JTAG TAP "
              "controller is required at this layer.\n")
    r = _run(_mk(tmp_path, l20=_SKELETON, docs={"spec.txt": denial}))
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" not in r.stdout, (
        r.stdout + r.stderr)


def test_an_input_doc_that_STATES_dft_still_reddens_f2(tmp_path):
    """Paired guard for the input-doc channel — the fixture the file already
    ships, asserted through the new code path."""
    r = _run(_mk(tmp_path, l20=_SKELETON,
                 docs={"spec.txt": _DFT_REQUIREMENT_DOC}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" in r.stdout, (
        r.stdout + r.stderr)


def test_a_prohibition_about_dft_is_a_requirement_not_a_denial(tmp_path):
    """`_NON_NORMATIVE_RE` records the trap this fixture pins: `must NOT
    exceed 5 ns` is a real requirement that contains a negation. A gate that
    cannot tell a PROHIBITION from an ABSENCE deletes half its own corpus."""
    prohibition = ("3.2 Test Requirements\n"
                   "A full scan chain is required. The scan chain shall not "
                   "exceed 5000 flops and must not be observable in mission "
                   "mode.\n")
    r = _run(_mk(tmp_path, l20=_SKELETON, docs={"spec.txt": prohibition}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" in r.stdout, (
        "a prohibition was read as an absence:\n" + r.stdout + r.stderr)


def test_the_denial_ruler_cannot_turn_a_typed_topology_red_or_green(tmp_path):
    """Content stays self-evidencing. A design that CARRIES an actionable
    scan topology passes whatever its prose says, so the new ruler can only
    ever move the evidence side of F2 — never the layer side."""
    doc = dict(_SKELETON)
    doc["fields"] = dict(_SKELETON["fields"], scan_chains=[_TYPED_CHAIN],
                         dft_present=True)
    for sibling in (_L7_DENIES_DFT, _L7_STATES_DFT):
        r = _run(_mk(tmp_path / str(id(sibling)), l20=doc,
                     siblings={"L7": sibling},
                     docs={"spec.txt": _DFT_REQUIREMENT_DOC}))
        assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" not in r.stdout, (
            r.stdout + r.stderr)


# ── vibe-ic#1021: three ruler defects, all measured on published roots ─────
#
# Every fixture is a SYNTHETIC restatement of a shape read off the published
# corpus by hand. None is copied from a design and none carries a design,
# foundry, vendor, protocol-standard or process token.

def test_NEGATIVE_CONTROL_framing_may_not_be_borrowed_across_a_full_stop(
        tmp_path):
    """DEFECT 1. A parenthetical MENTION in one sentence, an unrelated
    `requires` about certification in the next. Before #1021 the +/-160-char
    window reached back across the full stop and reddened the project.

    Paired with the guard below: this must go quiet and that must stay red.
    """
    doc = ("4.1 Debug Connector\n"
           "In this mode all digital circuits are disconnected from the "
           "connector and the bold pins can be used to expose debug related "
           "signals (e.g. JTAG interface). The certification body requires "
           "that privacy precautions have been taken before the mode is "
           "entered.\n")
    r = _run(_mk(tmp_path, l20=_SKELETON, docs={"spec.txt": doc}))
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" not in r.stdout, (
        "framing was borrowed from the NEXT sentence:\n" + r.stdout + r.stderr)


def test_POSITIVE_CONTROL_framing_in_the_terms_own_sentence_still_reddens(
        tmp_path):
    """The paired guard for defect 1. A window that admits nothing is not a
    narrower window, it is a broken one."""
    doc = ("4.1 Debug Connector\n"
           "In this mode all digital circuits are disconnected from the "
           "connector. The design requires a JTAG TAP controller on the "
           "debug connector.\n")
    r = _run(_mk(tmp_path, l20=_SKELETON, docs={"spec.txt": doc}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" in r.stdout, (
        r.stdout + r.stderr)


#: DEFECT 2, in the two roots' own idiom: no negation word anywhere, so no
#: denial ruler reaches it at any reach.
_L7_DEFERS_DFT = {
    "test_debug_architecture_present": False,
    "notes": ("The protocol-level test/debug surface is the sideband channel "
              "plus the link training patterns and symbol error counters. "
              "Chip-level JTAG/scan/BIST remain source / sink silicon "
              "concerns; conformance is established by the published "
              "compliance test specification."),
}


def test_a_sibling_layer_that_DEFERS_dft_to_another_party_does_not_redden(
        tmp_path):
    """DEFECT 2. "this requirement belongs to somebody else" is neither "it
    does not exist" nor "there is one here"."""
    r = _run(_mk(tmp_path, l20=_SKELETON, siblings={"L7": _L7_DEFERS_DFT}))
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" not in r.stdout, (
        "a scope-deferral was counted as a stated requirement:\n"
        + r.stdout + r.stderr)
    assert r.returncode != 1, r.stdout + r.stderr


def test_a_layer_that_names_a_concern_AND_IMPOSES_IT_still_reddens(tmp_path):
    """The paired guard for defect 2, and the reason it is not a ban. The
    ownership vocabulary is narrow by construction: a layer may use the word
    `concern` and still state a requirement of its own."""
    sibling = {
        "test_debug_architecture_present": True,
        "notes": ("Manufacturing test is a first-order concern for this "
                  "design. A full scan chain is required and the TAP "
                  "controller shall be reachable from the debug connector."),
    }
    r = _run(_mk(tmp_path, l20=_SKELETON, siblings={"L7": sibling}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" in r.stdout, (
        "the deferral ruler deleted a REAL finding:\n" + r.stdout + r.stderr)


#: DEFECT 3. Two published roots spend the BIST token on a PROTOCOL MESSAGE
#: NAME, inside a genuine `shall` sentence, so framing is really there and
#: cannot discriminate. Restated synthetically in both shapes.
_BIST_MESSAGE_DOCS = {
    "message_table.txt": (
        "5.2 Data Message Types\n"
        "Data Messages (number of data objects >= 1): 0x01 Capabilities, "
        "0x02 Request, 0x03 BIST Built-In Self Test, 0x04 Sink_Capabilities. "
        "The device shall implement every message type listed.\n"),
    "frame_types.txt": (
        "6.1 Frame Types\n"
        "The controller shall transport the following frame types: 0x27 "
        "Register Downstream, 0x39 Activate, 0x46 Data, 0x58 BIST "
        "Activate, 0x5F Setup.\n"),
    "bit_definition.txt": (
        "6.2 Command Header\n"
        "BIST (B): when set, indicates that the command the driver built is "
        "for sending a BIST frame, and the controller shall send it.\n"),
}


def test_a_protocol_MESSAGE_NAME_carrying_the_bist_token_does_not_redden(
        tmp_path):
    """DEFECT 3. A frame type and a message type are payloads a protocol
    defines on the wire. Neither says anything about whether the design has a
    built-in self-test, which is the only question this layer asks."""
    for name, text in _BIST_MESSAGE_DOCS.items():
        r = _run(_mk(tmp_path / name, l20=_SKELETON, docs={name: text}))
        assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" not in r.stdout, (
            f"a protocol message name was read as a DFT requirement "
            f"({name}):\n" + r.stdout + r.stderr)


def test_a_REAL_bist_requirement_still_reddens(tmp_path):
    """The paired guard for defect 3, and the one that keeps the narrowing
    honest: the token is only rejected when the document says, structurally,
    that it is naming an encoding."""
    doc = ("6.3 Test Provisions\n"
           "The design shall provide memory BIST for every on-chip SRAM and "
           "the MBIST controller is required to report a pass/fail status.\n")
    r = _run(_mk(tmp_path, l20=_SKELETON, docs={"spec.txt": doc}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" in r.stdout, (
        "the message-name ruler deleted a REAL MBIST requirement:\n"
        + r.stdout + r.stderr)


def test_the_message_name_ruler_touches_ONLY_the_bist_alternative(tmp_path):
    """It narrows ONE of sixteen alternatives in the vocabulary. A scan-chain
    requirement sitting in the SAME sentence as a message-type table must be
    unaffected — otherwise the reject is a sentence-level ban rather than a
    token-level one."""
    doc = ("6.1 Frame Types\n"
           "The controller shall transport 0x58 BIST Activate, and the "
           "design shall additionally provide a full scan chain for "
           "manufacturing test.\n")
    r = _run(_mk(tmp_path, l20=_SKELETON, docs={"spec.txt": doc}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" in r.stdout, (
        r.stdout + r.stderr)


def test_all_three_rulers_leave_a_typed_topology_alone(tmp_path):
    """Content stays self-evidencing, exactly as #1011's ruler had to. All
    three of this issue's rulers move only the EVIDENCE side of F2; a design
    that CARRIES an actionable scan topology passes whatever its prose says."""
    doc = dict(_SKELETON)
    doc["fields"] = dict(_SKELETON["fields"], scan_chains=[_TYPED_CHAIN],
                         dft_present=True)
    for i, sibling in enumerate((_L7_DEFERS_DFT, _L7_STATES_DFT)):
        r = _run(_mk(tmp_path / f"case{i}", l20=doc, siblings={"L7": sibling},
                     docs=dict(_BIST_MESSAGE_DOCS)))
        assert "REQUIREMENT_OUTSIDE_CONSUMING_LAYER" not in r.stdout, (
            r.stdout + r.stderr)
