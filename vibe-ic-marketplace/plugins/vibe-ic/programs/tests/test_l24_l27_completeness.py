#!/usr/bin/env python3
"""#157 — L24-L27 completeness-layer regression tests.

Issue #157: the phase1 runner + applicability/presence brain capped at L23,
so L24 (signoff), L25 (reliability/mission-profile), L26 (MEMS/transduction)
and L27 (memory-module SPD) were missing from the DEFAULT emission path even
though tools/phase1_engine/schema.py already defined their file-names/titles.

This file is the D1 guard for the fix. It covers, per the issue's checklist:
  (a) l_doc_taxonomy carries L24-L27 + every class classifies each into
      applicable XOR not_applicable.
  (b) opt-in L26/L27 never appear in a fallback/unknown applicable set.
  (c) _skeleton_fields_for / _extraction_hints_for return non-empty for L24-L27.
  (d) emit_l_doc_skeleton("L24"..) no longer KeyErrors + produces a valid
      skeleton.
  (e) presence check does NOT false-fail a chip lacking L26/L27, and DOES
      enforce L24/L25 for a fabricated-chip class (once it targets signoff).
  (f) L1-L13 presence enforcement is byte-unchanged (regression guard).
"""
from __future__ import annotations

import importlib
import json

import pytest

tx = importlib.import_module("l_doc_taxonomy")
pp = importlib.import_module("phase1_post_process")
icp = importlib.import_module("ic_class_profile")
gate = importlib.import_module("phase1_all_l_docs_present_check")

_COMPLETENESS = ("L24", "L25", "L26", "L27")
_OPT_IN = ("L26", "L27")


# ---------------------------------------------------------------------------
# (a) taxonomy carries L24-L27 + every class classifies each applicable XOR NA
# ---------------------------------------------------------------------------
class TestTaxonomyCarriesL24L27:
    def test_codes_present_and_last_is_l27(self):
        codes = tx.all_l_doc_codes()
        assert len(codes) == 28
        for c in _COMPLETENESS:
            assert c in codes
        assert codes[-1] == "L27"

    def test_full_name_stems_match_schema(self):
        # full_name stems MUST match tools/phase1_engine/schema.py stems.
        want = {
            "L24": "L24_SIGNOFF",
            "L25": "L25_RELIABILITY_MISSION_PROFILE",
            "L26": "L26_MECHANICAL_TRANSDUCTION",
            "L27": "L27_MEMORY_MODULE_SPD",
        }
        for code, stem in want.items():
            assert tx.l_doc_spec(code).full_name == stem

    def test_every_class_classifies_each_completeness_code_xor(self):
        for cls, entry in tx.IC_CLASS_APPLICABILITY.items():
            a = set(entry["applicable"])
            n = set(entry["not_applicable"])
            for c in _COMPLETENESS:
                # exactly one of applicable / not_applicable (XOR)
                assert (c in a) ^ (c in n), f"{cls}: {c} not classified XOR"

    def test_l24_l25_applicable_for_fabricated_chip_classes(self):
        for cls in ("chip_otp_centric", "memory_controller", "analog_block",
                    "soc_multi_block", "cpu_core_isa"):
            assert tx.is_applicable(cls, "L24")
            assert tx.is_applicable(cls, "L25")

    def test_l24_l25_not_applicable_for_protocol_classes(self):
        for cls in ("bus_interconnect_protocol", "serial_peripheral_protocol"):
            assert not tx.is_applicable(cls, "L24")
            assert not tx.is_applicable(cls, "L25")
            # rationale present + honest (per-implementation, not protocol-level)
            r = tx.na_rationale(cls, "L24")
            assert "protocol-level" in r

    def test_l26_l27_not_applicable_for_every_class(self):
        for cls in tx.IC_CLASS_APPLICABILITY:
            for c in _OPT_IN:
                assert not tx.is_applicable(cls, c)
                assert c in tx.not_applicable_l_docs(cls)


# ---------------------------------------------------------------------------
# (b) opt-in L26/L27 never in a fallback/unknown applicable set
# ---------------------------------------------------------------------------
class TestOptInNeverInFallback:
    def test_unknown_applicable_excludes_opt_in(self):
        app = tx.applicable_l_docs("unknown")
        assert "L24" in app and "L25" in app
        for c in _OPT_IN:
            assert c not in app

    def test_unrecognised_class_applicable_excludes_opt_in(self):
        # Any class name NOT in the registry hits the same fallback path.
        app = tx.applicable_l_docs("never-seen-class-xyz")
        assert app == set(tx.all_l_doc_codes()) - set(_OPT_IN)

    def test_unknown_not_applicable_is_exactly_opt_in(self):
        assert tx.not_applicable_l_docs("unknown") == set(_OPT_IN)

    def test_is_applicable_unknown_opt_in_false_others_true(self):
        for code in tx.all_l_doc_codes():
            expect = code not in _OPT_IN
            assert tx.is_applicable("unknown", code) is expect

    def test_na_stub_for_unknown_opt_in_has_canonical_rationale(self):
        assert "MEMS" in tx.na_stub("unknown", "L26")["rationale"]
        assert "SPD" in tx.na_stub("unknown", "L27")["rationale"]


# ---------------------------------------------------------------------------
# (c) skeleton fields + extraction hints non-empty for L24-L27
# ---------------------------------------------------------------------------
class TestSkeletonFieldsAndHints:
    def test_skeleton_fields_non_empty(self):
        for c in _COMPLETENESS:
            fields = pp._skeleton_fields_for(c)
            assert isinstance(fields, dict) and fields, c

    def test_extraction_hints_non_empty(self):
        for c in _COMPLETENESS:
            hints = pp._extraction_hints_for(c)
            assert isinstance(hints, list) and hints, c

    def test_l24_carries_signoff_status_fields(self):
        f = pp._skeleton_fields_for("L24")
        for k in ("drc_status", "lvs_status", "sta_status",
                  "antenna_status", "ir_drop_status", "tapeout_gates"):
            assert k in f

    def test_l25_carries_mission_profile_fields(self):
        f = pp._skeleton_fields_for("L25")
        for k in ("mission_profile", "temp_range", "qual_standard",
                  "em_budget", "aging_margin"):
            assert k in f

    def test_l26_l27_carry_expected_fields(self):
        assert "transducer_type" in pp._skeleton_fields_for("L26")
        assert "spd_revision" in pp._skeleton_fields_for("L27")

    def test_no_fabricated_values_only_placeholders(self):
        # Every leaf placeholder must be null / empty container (no invented
        # concrete value).
        def _all_placeholder(v):
            if v is None:
                return True
            if isinstance(v, (list, dict)):
                return len(v) == 0
            return False
        for c in _COMPLETENESS:
            for k, v in pp._skeleton_fields_for(c).items():
                assert _all_placeholder(v), f"{c}.{k} = {v!r} not a placeholder"


# ---------------------------------------------------------------------------
# (d) emit_l_doc_skeleton no longer KeyErrors + valid skeleton
# ---------------------------------------------------------------------------
class TestEmitSkeletonNoKeyError:
    def test_emit_l24_valid_skeleton(self):
        sk = pp.emit_l_doc_skeleton("L24", "chip_otp_centric")
        assert sk["doc_id"] == "L24"
        assert sk["doc_name"] == "L24_SIGNOFF"
        assert sk["applicability"] == "APPLICABLE"
        assert sk["fields"] and sk["extraction_hints"]
        assert sk["extraction_status"] == "NOT_YET_EXTRACTED"

    def test_emit_all_completeness_codes_no_keyerror(self):
        for c in _COMPLETENESS:
            sk = pp.emit_l_doc_skeleton(c, "chip_otp_centric")
            assert sk["doc_id"] == c

    def test_post_process_chip_emits_l24_l25_skeleton_l26_l27_na(self, tmp_path):
        gd = tmp_path / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "x"}))
        rep = pp.post_process(tmp_path, "chip_otp_centric")
        assert "L24" in rep.skeleton_emitted and "L25" in rep.skeleton_emitted
        assert "L26" in rep.na_stubs_emitted and "L27" in rep.na_stubs_emitted
        l24 = json.loads((gd / "L24_SIGNOFF.json").read_text())
        l26 = json.loads((gd / "L26_MECHANICAL_TRANSDUCTION.json").read_text())
        assert l24["applicability"] == "APPLICABLE"
        assert l26["applicability"] == "N/A"

    def test_post_process_protocol_emits_all_na(self, tmp_path):
        gd = tmp_path / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "x"}))
        rep = pp.post_process(tmp_path, "bus_interconnect_protocol")
        for c in _COMPLETENESS:
            assert c in rep.na_stubs_emitted


# ---------------------------------------------------------------------------
# ic_class_profile presence brain — L24-L27 classification
# ---------------------------------------------------------------------------
class TestRequiredLayersCompleteness:
    def test_all_layers_includes_l24_l27(self):
        for c in _COMPLETENESS:
            assert c in icp._ALL_LAYERS

    def test_default_completeness_layers_go_to_skip(self):
        # No detector sets the guard flags → L24-L27 resolve to skip.
        for cls in ("unknown", "bare_fpga", "aid_class_half_duplex",
                    "digital_cmd_driven", "mixed_signal_otp", "pure_analog"):
            spec = icp.required_layers({"ic_class": cls})
            for c in _COMPLETENESS:
                assert c in spec["skip"], f"{cls}: {c} not in skip"
                assert c not in spec["mandatory"]

    def test_targets_signoff_promotes_l24_l25_to_mandatory(self):
        spec = icp.required_layers(
            {"ic_class": "mixed_signal_otp", "targets_signoff": True})
        assert "L24" in spec["mandatory"] and "L25" in spec["mandatory"]
        # L26/L27 still skip (their guards absent).
        assert "L26" in spec["skip"] and "L27" in spec["skip"]

    def test_mems_and_memory_module_flags_promote_l26_l27(self):
        spec = icp.required_layers(
            {"ic_class": "unknown", "is_mems": True, "is_memory_module": True})
        assert "L26" in spec["mandatory"] and "L27" in spec["mandatory"]


# ---------------------------------------------------------------------------
# (e) + (f) presence-check gate behaviour
# ---------------------------------------------------------------------------
_L1_L13 = (
    "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
    "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
    "L7_TEST_DEBUG.json", "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
    "L10_TEST_CASES.json", "L11_OTP_CONTENT.json", "L12_BEHAVIORAL_SEQUENCES.json",
    "L13_LAB_CALIBRATION.json",
)


def _put(project, name, data=None):
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / name).write_text(json.dumps(data if data is not None
                                      else {"placeholder_field": "value"}))


class TestPresenceCheckGate:
    # (e) — no false-fail for a chip lacking L24-L27.
    def test_no_false_fail_when_l24_l27_absent(self, tmp_path):
        for name in _L1_L13:
            _put(tmp_path, name)
        code, lines = gate._check(tmp_path)
        out = "\n".join(lines)
        assert code == 0, out
        assert "PASS" in out
        # L26/L27 (and L24/L25) demote to INFO — never "missing".
        assert "missing" not in out.lower() or "Missing L doc" not in out

    # (f) — L1-L13 enforcement byte-unchanged: 13/13 for the fail-closed class.
    def test_l1_l13_still_enforced_13_of_13(self, tmp_path):
        for name in _L1_L13:
            _put(tmp_path, name)
        code, lines = gate._check(tmp_path)
        out = "\n".join(lines)
        assert code == 0 and "13/13" in out, out

    # (f) — a missing L1-L13 layer still FAILs (enforcement intact).
    def test_missing_l7_still_fails(self, tmp_path):
        for name in _L1_L13:
            if name.startswith("L7_"):
                continue
            _put(tmp_path, name)
        code, lines = gate._check(tmp_path)
        out = "\n".join(lines)
        assert code == 1 and "L7_" in out, out

    # (e) — the gate ENFORCES L24/L25 once the class makes them mandatory.
    def test_gate_enforces_mandatory_l24_l25(self, tmp_path, monkeypatch):
        # Force a fabricated-chip profile whose required_layers marks L24/L25
        # mandatory (as if the project declared targets_signoff).
        monkeypatch.setattr(
            gate, "detect_ic_class",
            lambda p: {"ic_class": "mixed_signal_otp"})
        monkeypatch.setattr(
            gate, "required_layers",
            lambda profile: {
                "mandatory": [f"L{i}" for i in range(1, 14)] + ["L24", "L25"],
                "skip": ["L26", "L27"],
            })
        # L1-L13 present but L24/L25 absent → FAIL flagging both.
        for name in _L1_L13:
            _put(tmp_path, name)
        code, lines = gate._check(tmp_path)
        out = "\n".join(lines)
        assert code == 1, out
        assert "L24_" in out and "L25_" in out
        assert "15/15" not in out  # not all present

    def test_gate_passes_when_mandatory_l24_l25_present(self, tmp_path,
                                                        monkeypatch):
        monkeypatch.setattr(
            gate, "detect_ic_class",
            lambda p: {"ic_class": "mixed_signal_otp"})
        monkeypatch.setattr(
            gate, "required_layers",
            lambda profile: {
                "mandatory": [f"L{i}" for i in range(1, 14)] + ["L24", "L25"],
                "skip": ["L26", "L27"],
            })
        for name in _L1_L13:
            _put(tmp_path, name)
        _put(tmp_path, "L24_SIGNOFF.json")
        _put(tmp_path, "L25_RELIABILITY_MISSION_PROFILE.json")
        code, lines = gate._check(tmp_path)
        out = "\n".join(lines)
        assert code == 0, out
        assert "15/15" in out
