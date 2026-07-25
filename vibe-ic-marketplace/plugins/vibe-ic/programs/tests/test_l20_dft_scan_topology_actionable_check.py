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
    """GUTTED: L20 claims DFT exists and carries zero chains."""
    doc = json.loads(json.dumps(_SKELETON))
    doc["fields"]["dft_present"] = True
    doc["fields"]["jtag_tap"] = {"tck": "tck", "tms": "tms"}
    r = _run(_mk(tmp_path, l20=doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VACUOUS_DFT_ASSERTION" in r.stdout


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


def test_extraction_claimed_with_empty_chains_fails(tmp_path):
    """A layer claiming EXTRACTED is held to the consumer contract."""
    doc = json.loads(json.dumps(_SKELETON))
    doc["extraction_status"] = "EXTRACTED"
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
