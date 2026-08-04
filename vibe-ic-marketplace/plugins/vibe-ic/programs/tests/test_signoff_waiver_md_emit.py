"""Unit tests for `signoff_waiver_md_emit.py`.

Pin the deterministic shape of the 7-section submitter-facing Markdown.
"""
import importlib
import json

import pytest

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("signoff_waiver_md_emit")


def _meta(**overrides):
    m = mod.ProjectMeta(
        project_name="spm",
        shuttle="chipignite MPW-7 2026-Q3",
        caravel_commit="efabless/caravel@a1b2c3d",
        wrapper_loc=111,
        submitter="reyer@defintek.io",
        submission_date="2026-05-29",
        root_cause_paragraph=(
            "The remaining precheck FAILs stem from the open-source signoff "
            "tooling's inability to verify a hard-macro user-project. "
            "Empirical evidence in the pilot's flatten and LEF-with-obs "
            "experiments confirm the failures are tool-side, not design-side."),
        recommendation_paragraph=(
            "Accept the waivers and proceed with chipignite submission; "
            "the foundry-side commercial signoff will close the remainder."),
        risk=mod.RiskAssessment(
            functional="None — device-level LVS proves equivalence",
            timing="None — WNS 0.0 ns, IR drop < 35 uV",
            manufacturing="None — DRC + antenna + latch-up clean",
            testability="None — Logic Analyzer + GPIO functional",
        ),
        independent_verifications=[
            mod.IndependentVerification("Device-level LVS", "Netgen 1.5",
                                        "261 = 261 PASS", "signoff/lvs/comp.out"),
            mod.IndependentVerification("Full SKY130A DRC", "Magic 8.3",
                                        "0 violations", "signoff/drc/drc.log"),
            mod.IndependentVerification("Antenna check", "Magic + KLayout",
                                        "0 violations both tools",
                                        "signoff/antenna/"),
            mod.IndependentVerification("IR-drop", "OpenROAD",
                                        "worst 35 uV",
                                        "signoff/ir/irdrop.rpt"),
        ],
    )
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


def _waiver(**overrides):
    w = {
        "id": "spm__xor__deadbeef",
        "project_name": "spm",
        "failed_check": "XOR",
        "sub_check_detail": "30 deltas vs stock empty wrapper",
        "reason_class": "stock-empty-vs-user-content-xor-delta",
        "mitigation": "test mitigation that is at least 40 characters long.",
        "evidence_files": ["benchmark_clean/spm_pilot/PHASE_B_RESULT.md"],
        "expected_remediation_path": "waiver",
        "risk_assessment": "low",
        "approver": "reyer@defintek.io",
        "signed_at": "2026-05-29",
    }
    w.update(overrides)
    return w


# ---------------------------------------------------------------------------
# Validate meta
# ---------------------------------------------------------------------------
class TestValidateMeta:
    def test_valid_meta_passes(self):
        assert mod.validate_meta(_meta()) == []

    def test_missing_root_cause_rejected(self):
        errs = mod.validate_meta(_meta(root_cause_paragraph=""))
        assert any("root_cause" in e for e in errs)

    def test_short_root_cause_rejected(self):
        errs = mod.validate_meta(_meta(root_cause_paragraph="short"))
        assert any("80 chars" in e for e in errs)

    def test_placeholder_in_root_cause_rejected(self):
        errs = mod.validate_meta(_meta(
            root_cause_paragraph="TODO: explain later. " * 5))
        assert any("placeholder" in e for e in errs)

    def test_ai_submitter_rejected(self):
        errs = mod.validate_meta(_meta(submitter="ai"))
        assert any("submitter" in e for e in errs)

    def test_incomplete_risk_rejected(self):
        m = _meta()
        m.risk.testability = ""
        errs = mod.validate_meta(m)
        assert any("risk assessment is incomplete" in e for e in errs)

    def test_too_few_verifications_rejected(self):
        m = _meta()
        m.independent_verifications = [
            mod.IndependentVerification("a", "b", "c", "d")]
        errs = mod.validate_meta(m)
        assert any(">= 3 entries" in e for e in errs)


# ---------------------------------------------------------------------------
# emit_markdown — section presence
# ---------------------------------------------------------------------------
class TestSectionPresence:
    def _emit(self, n_waivers=1, **meta_overrides):
        return mod.emit_markdown(
            [_waiver() for _ in range(n_waivers)],
            _meta(**meta_overrides))

    def test_has_h1_title_with_project(self):
        md = self._emit()
        assert md.startswith("# Waiver Request — spm")

    def test_has_section_1_project_id(self):
        md = self._emit()
        assert "## 1. Project identification" in md
        assert "chipignite MPW-7 2026-Q3" in md

    def test_has_section_2_waived_items(self):
        md = self._emit(n_waivers=2)
        assert "## 2. Waived items" in md
        assert "Total: 2 waiver(s)." in md

    def test_section_2_lists_each_waiver_row(self):
        md = self._emit(n_waivers=2)
        # Two table rows + header + separator = 4 |-lines (at least)
        assert md.count("`stock-empty-vs-user-content-xor-delta`") >= 2

    def test_has_section_3_root_cause(self):
        md = self._emit()
        assert "## 3. Root cause analysis" in md
        assert "The remaining precheck FAILs" in md

    def test_has_section_3_1_per_waiver_detail(self):
        md = self._emit()
        assert "### 3.1 Per-waiver detail" in md

    def test_per_waiver_includes_mitigation(self):
        md = self._emit()
        assert "test mitigation that is at least 40 characters long" in md

    def test_per_waiver_includes_evidence_list(self):
        md = self._emit()
        assert "PHASE_B_RESULT.md" in md

    def test_per_waiver_includes_remediation_path(self):
        md = self._emit()
        assert "Expected remediation path" in md

    def test_has_section_4_verifications_table(self):
        md = self._emit()
        assert "## 4. Independent verifications already performed" in md
        assert "| Device-level LVS | Netgen 1.5 |" in md

    def test_has_section_5_risk_4_axes(self):
        md = self._emit()
        assert "## 5. Risk assessment" in md
        for axis in ("Functional", "Timing", "Manufacturing", "Testability"):
            assert f"**{axis}**" in md

    def test_has_section_6_recommendation(self):
        md = self._emit()
        assert "## 6. Recommendation" in md
        assert "Accept the waivers" in md

    def test_has_section_7_attachments_auto_derived(self):
        md = self._emit()
        assert "## 7. Attachments" in md
        # Auto-derived from waiver evidence + JSON path
        assert "PHASE_B_RESULT.md" in md
        assert "signoff/waivers/spm__xor__deadbeef.json" in md

    def test_attachments_use_checklist_format(self):
        md = self._emit()
        # `- [ ]` checkbox markdown
        assert "- [ ]" in md

    def test_emitted_by_attribution(self):
        md = self._emit()
        assert "signoff_waiver_md_emit.py" in md
        assert f"(Vibe-IC plugin v{shipped_plugin_version()})." in md

    def test_idempotent_per_input(self):
        a = self._emit()
        b = self._emit()
        assert a == b


class TestIndependentVerificationRow:
    def test_row_format(self):
        v = mod.IndependentVerification(
            "DRC", "Magic", "0 violations", "signoff/drc/drc.log")
        row = v.as_md_row()
        assert "| DRC | Magic | 0 violations | `signoff/drc/drc.log` |" == row


class TestEmptyAttachments:
    def test_no_meta_attachments_auto_uses_waiver_evidence(self):
        md = mod.emit_markdown([_waiver()], _meta())
        # Both evidence file AND JSON path should appear
        assert "PHASE_B_RESULT.md" in md
        assert "signoff/waivers/spm__xor__deadbeef.json" in md

    def test_explicit_meta_attachments_used(self):
        m = _meta()
        m.attachments = ["extra/calibre_lvs_pass.txt"]
        md = mod.emit_markdown([_waiver()], m)
        assert "extra/calibre_lvs_pass.txt" in md
