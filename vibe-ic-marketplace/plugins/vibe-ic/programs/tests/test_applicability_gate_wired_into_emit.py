"""Tests for v0.1.62 R13 capture: l_doc_taxonomy.is_applicable + na_stub
wired into phase1_doc_one_shot_runner._write_l_doc.

Captured from AMBA AXI parity v0.1.57: the runner over-filled L4/L5/L7/
L11/L13 with OTP-template boilerplate for a bus-interconnect spec.
Claude correctly emitted nothing for those. The N/A stub gate is what
brings the two reports into alignment for the not-applicable docs.

Honesty constraint: gate fires ONLY when ic_class is detected non-unknown
AND the registry entry explicitly excludes the L doc. Unknown ic_class
keeps the legacy emit-everything default — fail-closed.
"""
import importlib
import json
import sys
from pathlib import Path
from _hostpaths import require_repo  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]
RUNNER = PROGRAMS / "phase1_doc_one_shot_runner.py"


def _load_taxonomy():
    if "l_doc_taxonomy" in sys.modules:
        del sys.modules["l_doc_taxonomy"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("l_doc_taxonomy")


# ── Taxonomy still answers correctly ──────────────────────────────────

def test_bus_protocol_l4_l5_l11_not_applicable():
    tax = _load_taxonomy()
    for code in ("L4", "L5", "L7", "L11", "L13"):
        assert not tax.is_applicable("bus_interconnect_protocol", code), (
            f"L{code} must NOT be applicable to bus_interconnect_protocol")


def test_bus_protocol_l1_l2_l3_applicable():
    tax = _load_taxonomy()
    for code in ("L1", "L2", "L3", "L9"):
        assert tax.is_applicable("bus_interconnect_protocol", code), (
            f"L{code} must be applicable to bus_interconnect_protocol")


def test_unknown_class_emit_everything_default():
    """ANTI-REGRESSION: unknown ic_class keeps legacy 14/14 contract."""
    tax = _load_taxonomy()
    for code in ("L1", "L2", "L3", "L4", "L5", "L11", "L13"):
        assert tax.is_applicable("unknown", code), (
            f"unknown ic_class must default to applicable=True for {code}")


def test_na_stub_carries_rationale():
    tax = _load_taxonomy()
    stub = tax.na_stub("bus_interconnect_protocol", "L4_REGMAP")
    assert stub["applicability"] == "N/A"
    assert stub["ic_class"] == "bus_interconnect_protocol"
    assert "register" in stub["rationale"].lower() or \
           "regmap" in stub["rationale"].lower() or \
           "channel" in stub["rationale"].lower()


# ── Runner wiring: chokepoint actually calls the gate ─────────────────

def test_write_l_doc_imports_applicability_gate():
    src = RUNNER.read_text()
    assert "from l_doc_taxonomy import is_applicable" in src
    assert "from l_doc_taxonomy import na_stub" in src
    assert "from ic_class_profile import detect_ic_class" in src, (
        "_write_l_doc must call detect_ic_class to determine the routing.")


def test_gate_fires_BEFORE_disk_write():
    """The gate must replace `content` BEFORE the document is serialised,
    so the on-disk JSON reflects the na_stub, not the over-filled template.

    The write is `_stamp.dump(out, content)` since vibe-ic#522 routed every
    L-document write through the shared chokepoint that records the
    producing release; before that it was an inline
    `out.write_text(json.dumps(content …))`. Both spellings are accepted so
    this ordering assertion survives the next time the write is factored,
    which is the whole reason it broke: it named an implementation detail
    rather than the event it cares about."""
    src = RUNNER.read_text()
    gate_pos = src.find("ic_class_applicability_gate_v0_1_62")
    write_pos = max(src.find("_stamp.dump(out, content)"),
                    src.find("out.write_text(json.dumps(content"))
    assert gate_pos > 0, "the applicability gate is no longer in _write_l_doc"
    assert write_pos > 0, (
        "no recognised serialisation of `content` found in _write_l_doc — "
        "if the write was renamed again, teach this test the new spelling "
        "rather than deleting the ordering assertion")
    assert gate_pos < write_pos


def test_gate_runs_AFTER_scrub_so_audit_is_preserved():
    """R11 scrub must happen first so a not-applicable doc that also had
    a hallucination still carries the scrub-audit trail in the na_stub."""
    src = RUNNER.read_text()
    scrub_pos = src.find("hallucination_scrub_v0_1_60")
    gate_pos = src.find("ic_class_applicability_gate_v0_1_62")
    assert scrub_pos < gate_pos


def test_gate_failure_is_fail_open():
    """Missing/broken taxonomy must NOT gate emission."""
    src = RUNNER.read_text()
    gate_block_start = src.find("from l_doc_taxonomy import is_applicable")
    # Walk backward to find the try: at the start of the gate block
    head = src[max(0, gate_block_start - 500):gate_block_start]
    assert "try:" in head, "gate must be inside try: (fail-open contract)"


# ── End-to-end ────────────────────────────────────────────────────────

def test_end_to_end_bus_protocol_l4_becomes_na_stub(tmp_path):
    """Direct simulation of the chokepoint behavior: given a project where
    L1+L2 already on disk satisfy bus_interconnect_protocol detection, a
    subsequent L4_REGMAP emission must be replaced with na_stub."""
    tax = _load_taxonomy()
    # Use the real AMBA AXI L1+L2 (the canonical evidence project)
    arm = require_repo("benchmark-data/evaluation/phase1_parity/arm_aix/phase1/generated_docs")
    if not (arm / "L1_DATASHEET.json").is_file():
        import pytest
        pytest.skip("AMBA AXI benchmark not present on this host")
    proj = tmp_path / "p"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    # Seed L1+L2 so detect_ic_class can classify
    (gd / "L1_DATASHEET.json").write_text((arm / "L1_DATASHEET.json").read_text())
    (gd / "L2_FRS.json").write_text((arm / "L2_FRS.json").read_text())

    if "ic_class_profile" in sys.modules:
        del sys.modules["ic_class_profile"]
    import ic_class_profile
    profile = ic_class_profile.detect_ic_class(proj)
    assert profile["ic_class"] == "bus_interconnect_protocol"

    # Confirm the runner WOULD emit L4 as na_stub for this class
    assert not tax.is_applicable("bus_interconnect_protocol", "L4")
    stub = tax.na_stub("bus_interconnect_protocol", "L4_REGMAP")
    assert stub["doc_id"] == "L4"
    assert stub["applicability"] == "N/A"


def test_l1_emission_is_always_applicable(tmp_path):
    """L1 must NEVER be na-stubbed (it's the bootstrap doc for ic_class
    detection itself). Verify the taxonomy and bootstrap both honor this."""
    tax = _load_taxonomy()
    # L1 applicable for every known class
    for cls in tax.IC_CLASS_APPLICABILITY:
        assert "L1" in tax.IC_CLASS_APPLICABILITY[cls]["applicable"], (
            f"L1 must be applicable to every ic_class; missing for {cls}")
