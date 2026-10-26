"""Focused regression tests for an explicitly absent L4 register map.

The absence wording is the real input shape supplied for this repair: the
document is marked not applicable, states that no software-visible registers
exist, and says no register file is required.  These tests keep that evidence
separate from an empty or contradictory document and from an OTP-positive
document.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import gen_l4_regmap
from flow_compliance_check import _p0_zero_population_evidence
from ic_class_profile import _l4_has_otp
from l4_register_map_claim import reconcile_register_map_claims
from l_doc_cross_consistency_check import _rel_otp_bytes_subset_layout
import spi_protocol_synth


_GEN_DIR = Path("phase1") / "generated_docs"

_EXPLICIT_ABSENCE = """\
# Register Map

The design has no software-visible registers, address map, interrupts, status
registers, configuration registers, OTP, or nonvolatile memory.
"""

_PARAGRAPH_POSITIVE_AFTER_NEGATIVE = """\
# Register Map

The design has no software-visible registers.

No OTP-based calibration is used

An OTP bank with lock bits stores the device identifier.
"""

_DOCUMENT_NEGATIVE_PLUS_UNRESOLVED = """\
No OTP-based calibration is used.

No OTP is present but OTP is present.
"""

_QUALIFIED_OTP_ABSENCE = """\
No OTP is present unless secure boot is enabled.
"""

_QUALIFIED_REGISTER_ABSENCE = """\
No software-visible registers unless debug mode is enabled.
"""

_COMMA_QUALIFIED_ABSENCE = """\
No OTP, unless secure boot is enabled.

No software-visible registers, unless debug mode is enabled.
"""

_INTERNAL_EXCEPTION_OTP = """\
No component except the boot controller uses OTP.
"""

_SCOPED_COMPONENT_REGISTER_DENIAL = """\
The debug component has no software-visible registers.
"""

_RETAINED_MARKDOWN_IC_ABSENCE = """\
---
layer: L5
ic: spm
status: not-applicable
---

# L5 — Register Map

## 適用性 — N/A

`spm` **無 SW-visible registers**。
"""

_CROSS_CLAUSE_REGISTER_PRESENCE = """\
---
ic: spm
---
# Register Map
`spm` **無 SW-visible registers**。
The register map is present.
"""

_ACTUAL_L6_OTP_NEGATIVE = """\
---
layer: L6
ic: spm
status: not-applicable
---

# L6 — Calibration / Lab Procedures

## 適用性 — N/A

`spm` 為純數位設計,**無 analog/mixed-signal 內容**,因此:

- 無 trimming
- 無 OTP-based calibration
- 無 lab measurement procedure
- 無 analog bias adjustment
- 無溫度補償

→ 不需 Plugin 產生 calibration controller、OTP interface、analog trim DAC 等。
"""


def _read_l4(project: Path) -> dict:
    return json.loads((project / _GEN_DIR / "L4_REGMAP.json").read_text())


def _seed(project: Path, l4: dict) -> None:
    path = project / _GEN_DIR
    path.mkdir(parents=True, exist_ok=True)
    (path / "L4_REGMAP.json").write_text(json.dumps(l4), encoding="utf-8")


def test_actual_explicit_absence_sets_typed_no_register_flag(tmp_path: Path) -> None:
    gen_l4_regmap(tmp_path, {"L5_register_map.md": _EXPLICIT_ABSENCE})
    l4 = _read_l4(tmp_path)
    assert l4["registers"] == []
    assert l4["no_registers_in_input"] is True
    assert l4["register_map_present"] is False
    assert l4["otp_layout"] is None
    assert l4["no_otp_layout_in_input"] is True


def test_exact_markdown_ic_subject_drives_zero_population_consumer(
        tmp_path: Path) -> None:
    """The exact current IC can carry a complete wrapped denial."""
    gen_l4_regmap(
        tmp_path,
        {"L5_register_map.md": _RETAINED_MARKDOWN_IC_ABSENCE},
    )
    l4 = _read_l4(tmp_path)
    assert l4["registers"] == []
    assert l4["no_registers_in_input"] is True
    assert l4["register_map_present"] is False
    assert _p0_zero_population_evidence(
        tmp_path, "l4_regmap_phase2_emitter_contract_check") is not None


def test_markdown_subject_requires_exact_ic_and_complete_proposition(
        tmp_path: Path) -> None:
    """Foreign, scoped, qualified, contradictory, and negated forms refuse."""
    clauses = {
        "foreign": "`other` **無 SW-visible registers**。",
        "component": "`spm.debug` **無 SW-visible registers**。",
        "qualified": "`spm` **無 SW-visible registers unless debug is enabled**。",
        "contradictory": (
            "`spm` **無 SW-visible registers** but CTRL is software-visible。"
        ),
        "mixed": "`spm` **無 SW-visible registers and has a CTRL register**。",
        "outer_negation": "It is not true that `spm` **無 SW-visible registers**。",
    }
    for name, clause in clauses.items():
        project = tmp_path / name
        text = f"---\nic: spm\n---\n\n# Register Map\n\n{clause}\n"
        gen_l4_regmap(project, {"L5_register_map.md": text})
        l4 = _read_l4(project)
        assert l4["registers"] == []
        assert l4["no_registers_in_input"] is False
        assert l4.get("register_map_present") is not False
        assert _p0_zero_population_evidence(
            project, "l4_regmap_phase2_emitter_contract_check") is None


def test_exact_markdown_ic_absence_does_not_override_positive_register(
        tmp_path: Path) -> None:
    """A positive row keeps non-absence authority over the wrapped denial."""
    text = _RETAINED_MARKDOWN_IC_ABSENCE + """

| Address | Name | Access | Description |
|---|---|---|---|
| 0x00 | CTRL | R/W | control register |
"""
    gen_l4_regmap(tmp_path, {"L5_register_map.md": text})
    l4 = _read_l4(tmp_path)
    assert l4["registers"]
    assert l4["no_registers_in_input"] is False
    assert l4.get("register_map_present") is not False
    assert _p0_zero_population_evidence(
        tmp_path, "l4_regmap_phase2_emitter_contract_check") is None


def test_separate_positive_register_presence_vetoes_document_absence(
        tmp_path: Path) -> None:
    """A later complete positive clause keeps the whole document unknown."""
    gen_l4_regmap(
        tmp_path,
        {"L5_register_map.md": _CROSS_CLAUSE_REGISTER_PRESENCE},
    )
    l4 = _read_l4(tmp_path)
    assert l4["registers"] == []
    assert l4["no_registers_in_input"] is False
    assert l4.get("register_map_present") is not False
    assert _p0_zero_population_evidence(
        tmp_path, "l4_regmap_phase2_emitter_contract_check") is None


def test_malformed_unknown_does_not_guess_absence(tmp_path: Path) -> None:
    gen_l4_regmap(tmp_path, {"L5_register_map.md": "# Register Map\n\nTBD\n"})
    l4 = _read_l4(tmp_path)
    assert l4["registers"] == []
    assert l4["no_registers_in_input"] is False
    assert l4.get("register_map_present") is not False
    assert l4["otp_layout"] is None
    assert l4["no_otp_layout_in_input"] is False


def test_double_negated_otp_absence_is_not_an_absence_declaration(
        tmp_path: Path) -> None:
    gen_l4_regmap(
        tmp_path,
        {"L5_register_map.md": "This is not a design with no OTP.\n"},
    )
    l4 = _read_l4(tmp_path)
    assert l4["no_otp_layout_in_input"] is False
    assert l4["otp_layout"] is not None


def test_explicit_absence_drives_real_consumers(tmp_path: Path) -> None:
    gen_l4_regmap(tmp_path, {"L5_register_map.md": _EXPLICIT_ABSENCE})
    l4 = _read_l4(tmp_path)

    assert _l4_has_otp(l4, None, None) is False
    assert reconcile_register_map_claims(l4) == []
    assert _p0_zero_population_evidence(
        tmp_path, "l4_regmap_phase2_emitter_contract_check") is not None
    finding = _rel_otp_bytes_subset_layout(
        {"otp_bytes": [{"address": 0}]}, l4)
    assert finding.verdict == "N/A"


def test_contradictory_register_declaration_stays_unknown(tmp_path: Path) -> None:
    contradictory = _EXPLICIT_ABSENCE + """

| Address | Name | Access | Description |
|---|---|---|---|
| 0x00 | CTRL | R/W | control register |
"""
    gen_l4_regmap(tmp_path, {"L5_register_map.md": contradictory})
    l4 = _read_l4(tmp_path)
    assert l4["registers"]
    assert l4["no_registers_in_input"] is False
    assert l4.get("register_map_present") is not False

    assert _p0_zero_population_evidence(
        tmp_path, "l4_regmap_phase2_emitter_contract_check") is None


def test_otp_positive_control_keeps_declared_geometry(tmp_path: Path) -> None:
    otp = """\
# Register Map

OTP layout: 128-byte one-time-programmable fuse array with lock bits. ID[0].
"""
    gen_l4_regmap(tmp_path, {"otp_layout.md": otp})
    l4 = _read_l4(tmp_path)
    assert l4["otp_layout"] is not None
    assert l4["no_otp_layout_in_input"] is False
    assert l4["otp_layout"]["depth_bytes"] == 128
    assert l4["otp_layout"]["width_bits"] == 8
    assert _l4_has_otp(l4, None, None) is True
    finding = _rel_otp_bytes_subset_layout(
        {"otp_bytes": [{"address": 0}]}, l4)
    assert finding.verdict != "N/A"


def test_otp_declaration_after_unrelated_negative_clause_is_positive(
        tmp_path: Path) -> None:
    """A negative clause must not erase a later real OTP declaration."""
    cases = (
        "There is no reset pin; an OTP bank stores trim data.\n",
        "No OTP-based calibration is used; an OTP bank stores the device "
        "identifier.\n",
    )
    for index, text in enumerate(cases):
        project = tmp_path / f"case_{index}"
        gen_l4_regmap(project, {f"otp_clause_{index}.md": text})
        l4 = _read_l4(project)
        assert l4["no_otp_layout_in_input"] is False
        assert l4["otp_layout"] is not None


def test_otp_positive_paragraph_after_negative_calibration_is_preserved(
        tmp_path: Path) -> None:
    """Paragraph boundaries keep a later OTP bank authoritative."""
    gen_l4_regmap(
        tmp_path,
        {"L5_register_map.md": _PARAGRAPH_POSITIVE_AFTER_NEGATIVE},
    )
    l4 = _read_l4(tmp_path)
    assert l4["no_otp_layout_in_input"] is False
    assert l4["otp_layout"] is not None
    assert _l4_has_otp(l4, None, None) is True
    finding = _rel_otp_bytes_subset_layout(
        {"otp_bytes": [{"address": 0}]}, l4)
    assert finding.verdict == "FAIL"

    unresolved = tmp_path / "unresolved"
    gen_l4_regmap(
        unresolved,
        {"L5_register_map.md": "No OTP is present but OTP is present.\n"},
    )
    unresolved_l4 = _read_l4(unresolved)
    assert unresolved_l4["no_otp_layout_in_input"] is False
    assert unresolved_l4["otp_layout"] is None


def test_document_absence_is_vetoed_by_an_unresolved_otp_clause(
        tmp_path: Path) -> None:
    """A clean denial cannot mask another unresolved OTP-bearing clause."""
    gen_l4_regmap(
        tmp_path,
        {"L5_register_map.md": _DOCUMENT_NEGATIVE_PLUS_UNRESOLVED},
    )
    l4 = _read_l4(tmp_path)
    assert l4["no_otp_layout_in_input"] is False
    assert l4["otp_layout"] is None
    assert _l4_has_otp(l4, None, None) is False
    finding = _rel_otp_bytes_subset_layout(
        {"otp_bytes": [{"address": 0}]}, l4)
    assert finding.verdict == "FAIL"


def test_qualified_otp_absence_remains_unknown_to_actual_consumers(
        tmp_path: Path) -> None:
    """A conditional negative cannot authorize whole-document absence."""
    gen_l4_regmap(
        tmp_path,
        {"L5_register_map.md": _QUALIFIED_OTP_ABSENCE},
    )
    l4 = _read_l4(tmp_path)
    assert l4["no_otp_layout_in_input"] is False
    assert l4["otp_layout"] is None
    assert _l4_has_otp(l4, None, None) is False
    finding = _rel_otp_bytes_subset_layout(
        {"otp_bytes": [{"address": 0}]}, l4)
    assert finding.verdict == "FAIL"

    clean = tmp_path / "clean"
    gen_l4_regmap(clean, {"L5_register_map.md": "No OTP is present.\n"})
    clean_l4 = _read_l4(clean)
    assert clean_l4["no_otp_layout_in_input"] is True
    assert clean_l4["otp_layout"] is None
    clean_finding = _rel_otp_bytes_subset_layout(
        {"otp_bytes": [{"address": 0}]}, clean_l4)
    assert clean_finding.verdict == "N/A"


def test_qualified_register_absence_does_not_declare_zero_population(
        tmp_path: Path) -> None:
    """A qualified no-register claim remains unknown to the L4 gate."""
    gen_l4_regmap(
        tmp_path,
        {"L5_register_map.md": _QUALIFIED_REGISTER_ABSENCE},
    )
    l4 = _read_l4(tmp_path)
    assert l4["registers"] == []
    assert l4["no_registers_in_input"] is False
    assert l4.get("register_map_present") is not False
    assert _p0_zero_population_evidence(
        tmp_path, "l4_regmap_phase2_emitter_contract_check") is None

    clean = tmp_path / "clean"
    gen_l4_regmap(
        clean,
        {"L5_register_map.md": "No software-visible registers.\n"},
    )
    clean_l4 = _read_l4(clean)
    assert clean_l4["no_registers_in_input"] is True
    assert clean_l4["register_map_present"] is False
    assert _p0_zero_population_evidence(
        clean, "l4_regmap_phase2_emitter_contract_check") is not None


def test_comma_qualified_absence_is_not_a_denied_l4_member_list(
        tmp_path: Path) -> None:
    """Comma-delimited conditions remain unknown to actual consumers."""
    gen_l4_regmap(
        tmp_path,
        {"L5_register_map.md": _COMMA_QUALIFIED_ABSENCE},
    )
    l4 = _read_l4(tmp_path)
    assert l4["registers"] == []
    assert l4["no_otp_layout_in_input"] is False
    assert l4["otp_layout"] is None
    assert _l4_has_otp(l4, None, None) is False
    finding = _rel_otp_bytes_subset_layout(
        {"otp_bytes": [{"address": 0}]}, l4)
    assert finding.verdict == "FAIL"

    assert l4["no_registers_in_input"] is False
    assert l4.get("register_map_present") is not False
    assert _p0_zero_population_evidence(
        tmp_path, "l4_regmap_phase2_emitter_contract_check") is None


def test_full_denial_body_requires_whole_design_authority(
        tmp_path: Path) -> None:
    """Internal residual syntax or a scoped subject remains unknown."""
    otp_project = tmp_path / "otp-exception"
    gen_l4_regmap(
        otp_project,
        {"L5_register_map.md": _INTERNAL_EXCEPTION_OTP},
    )
    otp_l4 = _read_l4(otp_project)
    assert otp_l4["no_otp_layout_in_input"] is False
    assert otp_l4["otp_layout"] is None
    assert _l4_has_otp(otp_l4, None, None) is False
    otp_finding = _rel_otp_bytes_subset_layout(
        {"otp_bytes": [{"address": 0}]}, otp_l4)
    assert otp_finding.verdict == "FAIL"

    register_project = tmp_path / "register-subject"
    gen_l4_regmap(
        register_project,
        {"L5_register_map.md": _SCOPED_COMPONENT_REGISTER_DENIAL},
    )
    register_l4 = _read_l4(register_project)
    assert register_l4["registers"] == []
    assert register_l4["no_registers_in_input"] is False
    assert register_l4.get("register_map_present") is not False
    assert _p0_zero_population_evidence(
        register_project,
        "l4_regmap_phase2_emitter_contract_check",
    ) is None

    clean_otp_project = tmp_path / "clean-otp"
    gen_l4_regmap(
        clean_otp_project,
        {"L5_register_map.md": "No OTP is present.\n"},
    )
    clean_otp_l4 = _read_l4(clean_otp_project)
    assert clean_otp_l4["no_otp_layout_in_input"] is True
    assert clean_otp_l4["otp_layout"] is None
    clean_otp_finding = _rel_otp_bytes_subset_layout(
        {"otp_bytes": [{"address": 0}]}, clean_otp_l4)
    assert clean_otp_finding.verdict == "N/A"

    clean_register_project = tmp_path / "clean-register"
    gen_l4_regmap(
        clean_register_project,
        {"L5_register_map.md": "No software-visible registers.\n"},
    )
    clean_register_l4 = _read_l4(clean_register_project)
    assert clean_register_l4["no_registers_in_input"] is True
    assert clean_register_l4["register_map_present"] is False
    assert _p0_zero_population_evidence(
        clean_register_project,
        "l4_regmap_phase2_emitter_contract_check",
    ) is not None


def test_actual_l6_negative_otp_interface_does_not_create_layout(
        tmp_path: Path) -> None:
    """The actual SPM L6 wording names OTP only to reject its interface."""
    gen_l4_regmap(tmp_path, {"L6_calibration.md": _ACTUAL_L6_OTP_NEGATIVE})
    l4 = _read_l4(tmp_path)
    assert l4["otp_layout"] is None
    assert l4["no_otp_layout_in_input"] is True


def test_universal_overlay_does_not_add_register_defaults_to_explicit_absence(
        tmp_path: Path) -> None:
    _seed(tmp_path, {
        "registers": [],
        "register_map_present": False,
        "no_registers_in_input": True,
        "otp_layout": None,
        "no_otp_layout_in_input": True,
    })
    spi_protocol_synth._apply_universal(tmp_path / _GEN_DIR, False)
    l4 = _read_l4(tmp_path)
    assert l4["register_map_present"] is False
    assert "base_address" not in l4
    assert "notes" not in l4


def test_universal_overlay_keeps_supported_register_map_defaults(
        tmp_path: Path) -> None:
    _seed(tmp_path, {
        "registers": [{"name": "CTRL", "address": "0x00"}],
        "register_map_present": True,
    })
    spi_protocol_synth._apply_universal(tmp_path / _GEN_DIR, False)
    l4 = _read_l4(tmp_path)
    assert l4["register_map_present"] is True
    assert l4["base_address"]
    assert l4["notes"]
