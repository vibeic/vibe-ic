#!/usr/bin/env python3
"""v0.1.82 — digital-benchmark l_doc extractors: L9 submodule headings,
L12 no_calibration, L4 register-map N/A. All input-docs-only, chip-AGNOSTIC,
honest (only fire on explicit input assertions)."""
from __future__ import annotations
import sys
from pathlib import Path
PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import phase1_doc_one_shot_runner as P  # noqa: E402
import l_doc_structured_field_count_check as G  # noqa: E402


# ---- L9 numbered submodule-contract headings -------------------------------
_L8 = """# L8 — Submodule Integration Spec
## 8.2 必要 sub-module 對外契約
### 8.2.1 CPU core(必含)
### 8.2.2 Bus wrapper(必含)
### 8.2.3 Shared SRAM
### 8.2.4 GPIO peripheral
"""


def test_l9_heading_submodules_extracted():
    subs = P._l9_heading_submodule_extract(_L8)
    assert subs == ["CPU core", "Bus wrapper", "Shared SRAM", "GPIO peripheral"]


def test_l9_section_titles_not_submodules():
    # the `## 8.2 必要 sub-module 對外契約` title must be dropped
    subs = P._l9_heading_submodule_extract(_L8)
    assert not any("契約" in s or "必要" in s for s in subs)


def test_l9_requires_submodule_context():
    # a numbered-heading doc with no submodule/integration context → nothing
    assert P._l9_heading_submodule_extract("# Spec\n### 1.1 Foo\n### 1.2 Bar\n") == []


# ---- L12 no_calibration ----------------------------------------------------
def test_l12_no_calibration_regex_zh():
    assert P._RE_L12_NO_CALIBRATION.search("無 trimming\n無 OTP-based calibration")


def test_l12_no_calibration_regex_en():
    assert P._RE_L12_NO_CALIBRATION.search("This part has no calibration or trimming.")


def test_l12_gate_honors_no_calibration():
    ok, _ = G._check_l_doc(12, {"no_calibration": True, "behavioral_sequences": []})
    assert ok is True


def test_l12_gate_still_fails_without_flag_or_content():
    ok, _ = G._check_l_doc(12, {"behavioral_sequences": []})
    assert ok is False


# ---- L4 register-map N/A ----------------------------------------------------
def test_l4_no_regmap_regex():
    assert P._RE_L4_NO_REGMAP.search("status: not-applicable")
    assert P._RE_L4_NO_REGMAP.search("subservient 無 SW-visible chip registers")


def test_l4_gate_honors_register_map_present_false():
    ok, _ = G._check_l_doc(4, {"register_map_present": False, "registers": []})
    assert ok is True


def test_l4_gate_still_fails_without_flag():
    ok, _ = G._check_l_doc(4, {"registers": []})
    assert ok is False


# ---- v0.1.88 — L11 genuine-N/A for reused-IP CPU SoC --------------------------
def test_l11_na_when_no_command_no_otp_no_cal():
    # reused-IP CPU SoC: no command protocol + otp_present False + no cal → N/A
    ok, _ = G._check_l_doc(11, {"otp_present": False, "behavioral_sequences": []},
                           {"no_command_protocol": True}, "digital_arithmetic_primitive")
    assert ok is True


def test_l11_still_required_for_otp_chip():
    # otp_present True → L11 still demanded even with no_command_protocol
    ok, _ = G._check_l_doc(11, {"otp_present": True, "behavioral_sequences": []},
                           {"no_command_protocol": True}, "digital_arithmetic_primitive")
    assert ok is False


def test_l11_still_required_without_escape():
    # no no_command_protocol escape → L11 still demanded
    ok, _ = G._check_l_doc(11, {"otp_present": False, "behavioral_sequences": []},
                           {}, "digital_arithmetic_primitive")
    assert ok is False


def test_l11_na_blocked_when_calibration_present():
    ok, _ = G._check_l_doc(11, {"otp_present": False,
                                "calibration_tables": [{"k": 1}]},
                           {"no_command_protocol": True}, "digital_arithmetic_primitive")
    # calibration present → N/A short-circuit must NOT fire; 1 cal entry < 3 → FAIL.
    assert ok is False
