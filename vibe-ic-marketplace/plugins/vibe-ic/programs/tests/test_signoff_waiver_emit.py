"""Unit tests for `signoff_waiver_emit.py`.

Pin the deterministic shape + honesty gates of the chipignite-submission
waiver emitter.
"""
import importlib
import json

import pytest

mod = importlib.import_module("signoff_waiver_emit")


def _valid_entry(**overrides):
    base = dict(
        project_name="spm",
        failed_check="XOR",
        reason_class="stock-empty-vs-user-content-xor-delta",
        mitigation=("30 XOR deltas vs stock empty wrapper are intended user "
                    "content (spm core placed inside Caravel user-project "
                    "area); see PHASE_C_CLEANUP_RESULT.md for evidence."),
        approver="reyerchu@vibeic",
    )
    base.update(overrides)
    return mod.WaiverEntry(**base)


# ---------------------------------------------------------------------------
# Schema enums
# ---------------------------------------------------------------------------
class TestEnums:
    def test_precheck_fails_include_known_chipignite_checks(self):
        for name in ("License", "Makefile", "Consistency",
                     "XOR", "GPIO-Defines", "DRC", "LVS"):
            assert name in mod.CHIPIGNITE_PRECHECK_FAIL_NAMES

    def test_reason_classes_have_descriptions(self):
        for cls, desc in mod.REASON_CLASSES.items():
            assert cls and desc
            assert len(desc) > 40

    def test_blackbox_and_xor_classes_present(self):
        for k in ("blackbox-macro-signoff-limit",
                  "open-source-extraction-naming-convention",
                  "stock-empty-vs-user-content-xor-delta",
                  "precheck-tool-self-issue"):
            assert k in mod.REASON_CLASSES


# ---------------------------------------------------------------------------
# build_waiver_entry — id + timestamp auto-fill
# ---------------------------------------------------------------------------
class TestBuildWaiverEntry:
    def test_auto_fills_id_and_signed_at(self):
        d = mod.build_waiver_entry(_valid_entry())
        assert d["id"].startswith("spm__xor__")
        assert d["signed_at"]  # ISO date

    def test_stable_id_is_deterministic(self):
        a = mod.build_waiver_entry(_valid_entry())
        b = mod.build_waiver_entry(_valid_entry())
        assert a["id"] == b["id"]  # same inputs → same id

    def test_stable_id_differs_per_check(self):
        a = mod.build_waiver_entry(_valid_entry(failed_check="XOR"))
        b = mod.build_waiver_entry(_valid_entry(failed_check="Consistency"))
        assert a["id"] != b["id"]

    def test_drops_empty_sub_check_detail(self):
        d = mod.build_waiver_entry(_valid_entry())
        assert "sub_check_detail" not in d

    def test_keeps_sub_check_detail_when_supplied(self):
        d = mod.build_waiver_entry(_valid_entry(
            sub_check_detail="LAYOUT mismatch on sky130_fd_sc_hd__conb_1"))
        assert "LAYOUT" in d["sub_check_detail"]

    def test_drops_risk_justification_for_low_risk(self):
        d = mod.build_waiver_entry(_valid_entry())
        assert "risk_justification" not in d

    def test_emit_returns_valid_json(self):
        text = mod.emit_waiver_json(_valid_entry())
        d = json.loads(text)
        assert d["project_name"] == "spm"
        assert d["failed_check"] == "XOR"
        assert d["emitted_by"].startswith("vibe-ic plugin")


# ---------------------------------------------------------------------------
# validate_waiver — honesty gates
# ---------------------------------------------------------------------------
class TestValidateWaiverHonestyGates:
    def test_valid_entry_passes(self):
        d = mod.build_waiver_entry(_valid_entry())
        assert mod.validate_waiver(d) == []

    def test_missing_mitigation_rejected(self):
        d = mod.build_waiver_entry(_valid_entry(mitigation=""))
        errs = mod.validate_waiver(d)
        assert any("mitigation" in e for e in errs)

    def test_short_mitigation_rejected(self):
        d = mod.build_waiver_entry(_valid_entry(mitigation="too short"))
        errs = mod.validate_waiver(d)
        assert any(">= 40" in e for e in errs)

    def test_placeholder_in_mitigation_rejected(self):
        d = mod.build_waiver_entry(_valid_entry(
            mitigation="TODO: explain the XOR delta later, " +
                       "30 deltas vs stock empty wrapper"))
        errs = mod.validate_waiver(d)
        assert any("placeholder" in e for e in errs)

    def test_ai_approver_rejected(self):
        d = mod.build_waiver_entry(_valid_entry(approver="ai"))
        errs = mod.validate_waiver(d)
        assert any("approver" in e for e in errs)

    def test_claude_approver_rejected(self):
        d = mod.build_waiver_entry(_valid_entry(approver="claude"))
        errs = mod.validate_waiver(d)
        assert any("approver" in e for e in errs)

    def test_agent_approver_rejected(self):
        d = mod.build_waiver_entry(_valid_entry(approver="agent"))
        errs = mod.validate_waiver(d)
        assert any("approver" in e for e in errs)

    def test_real_email_approver_accepted(self):
        d = mod.build_waiver_entry(_valid_entry(approver="reyer@defintek.io"))
        assert mod.validate_waiver(d) == []

    def test_unknown_reason_class_rejected(self):
        d = mod.build_waiver_entry(
            _valid_entry(reason_class="my-personal-category"))
        errs = mod.validate_waiver(d)
        assert any("reason_class" in e for e in errs)

    def test_medium_risk_needs_justification(self):
        d = mod.build_waiver_entry(_valid_entry(
            risk_assessment="medium", risk_justification=""))
        errs = mod.validate_waiver(d)
        assert any("risk_justification" in e for e in errs)

    def test_high_risk_with_short_justification_rejected(self):
        d = mod.build_waiver_entry(_valid_entry(
            risk_assessment="high", risk_justification="brief"))
        errs = mod.validate_waiver(d)
        assert any("risk_justification" in e for e in errs)

    def test_medium_risk_with_real_justification_accepted(self):
        d = mod.build_waiver_entry(_valid_entry(
            risk_assessment="medium",
            risk_justification=(
                "Blackbox-macro abstract LEF carries no obstruction layers, "
                "so wrapper-level routing over the macro is not auto-blocked; "
                "PnR-side dont_use=spm constraint mitigates.")))
        assert mod.validate_waiver(d) == []

    def test_invalid_risk_level_rejected(self):
        d = mod.build_waiver_entry(_valid_entry(risk_assessment="critical"))
        errs = mod.validate_waiver(d)
        assert any("risk_assessment" in e for e in errs)

    def test_evidence_files_non_list_rejected(self):
        e = _valid_entry()
        d = mod.build_waiver_entry(e)
        d["evidence_files"] = "single-string-not-list"
        errs = mod.validate_waiver(d)
        assert any("list" in e for e in errs)

    def test_evidence_files_empty_string_rejected(self):
        e = _valid_entry()
        e.evidence_files = ["valid/path.md", ""]
        d = mod.build_waiver_entry(e)
        errs = mod.validate_waiver(d)
        assert any("evidence_files[1]" in e for e in errs)


class TestAnonApprovers:
    @pytest.mark.parametrize("name", ["", "anon", "self", "tbd", "TODO"])
    def test_bad_names_rejected(self, name):
        d = mod.build_waiver_entry(_valid_entry(approver=name))
        errs = mod.validate_waiver(d)
        assert errs  # at least one error


class TestEmitShape:
    def test_emit_includes_emitted_by(self):
        text = mod.emit_waiver_json(_valid_entry())
        assert "vibe-ic plugin" in text

    def test_indent_default_is_2(self):
        text = mod.emit_waiver_json(_valid_entry())
        # 2-space indent: first nested key starts with two spaces
        assert '\n  "' in text

    def test_signed_at_is_iso_date_today(self):
        import datetime as dt
        d = mod.build_waiver_entry(_valid_entry())
        # YYYY-MM-DD shape
        assert len(d["signed_at"]) == 10
        assert d["signed_at"].count("-") == 2
        # Parses as date
        dt.date.fromisoformat(d["signed_at"])
