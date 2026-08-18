"""tests/test_phase2_issue22_fixes.py — v1.6.90

Closes issue #22:
- Bug 1 (P0): chip_top emits literal OE name in rx_masked, not alias,
  so self_rx_mask_check's literal-name proximity scan finds the
  AND-NOT pattern.
- Bug 2 (P2): _is_real_submodule_name rejects common English verbs
  (reads / writes / drives / latches / decodes / asserts / ...) so
  prose extractors no longer leak verbs into L9.submodules.

Both fixes are chip-AGNOSTIC: pattern keyed on literal OE driver name
applies to every aid-class half-duplex single-wire chip; verb deny-
list is structural English vocabulary, no chip-specific tokens.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(
    str(__import__("pathlib").Path(__file__).resolve().parents[2])
)
sys.path.insert(0, str(PLUGIN_ROOT))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _seed_aid_project(project: Path) -> None:
    """Minimal L1/L3/L8/L9 stub so aid_class_rtl_gen.gen() can emit."""
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "TEST"})
    )
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "schema_version": 2,
        "command_set": [{"name": "READ", "opcode_hex": "01"}],
        "crc_parameters": {"polynomial_hex": "0x31"},
    }))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "schema_version": 2,
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "schema_version": 2,
        "doc_class": "rtl_constants",
        "ic_name": "TEST",
        "rx_classifier_ticks": None,
        "timing_constants": [],
        "clock_domains": [],
    }))
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [
            {"name": "clk",     "direction": "input", "width": 1},
            {"name": "reset_n", "direction": "input", "width": 1},
            {"name": "id_bus",  "direction": "inout", "width": 1},
        ],
    }))


def _read_chip_top(project: Path) -> str:
    for cand in (
        project / "phase2" / "stage1" / "rtl" / "chip_top.sv",
        project / "rtl" / "chip_top.sv",
        project / "phase2" / "rtl" / "chip_top.sv",
    ):
        if cand.is_file():
            return cand.read_text()
    hits = list(project.rglob("chip_top.sv"))
    assert hits, f"chip_top.sv not emitted under {project}"
    return hits[0].read_text()


def _seed_phase1_workdir(project: Path) -> None:
    (project / "phase1" / "generated_docs").mkdir(
        parents=True, exist_ok=True
    )


def _load_l9_submodule_names(project: Path) -> set[str]:
    p = project / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return set()
    l9 = json.loads(p.read_text())
    out: set[str] = set()
    for s in (l9.get("submodules") or []):
        nm = s.get("name") if isinstance(s, dict) else None
        if isinstance(nm, str):
            out.add(nm.lower())
    return out


# ---------------------------------------------------------------------------
# Bug 1 (P0) — chip_top mask must use literal OE name
# ---------------------------------------------------------------------------
def test_chip_top_emits_literal_oe_in_rx_masked(tmp_path):
    """v1.6.90 (#22 Bug 1 P0): chip_top.sv mask must use the literal
    OE name (id_bus_drive_low), not the alias (id_bus_oe), so the
    gate's literal-name proximity scan finds the AND-NOT pattern."""
    from programs import aid_class_rtl_gen
    project = tmp_path / "aid_proj"
    _seed_aid_project(project)
    aid_class_rtl_gen.gen(project)
    chip_top = _read_chip_top(project)

    # The masked assignment must use the literal OE name
    # (id_bus_drive_low), NOT the alias (id_bus_oe).
    pat_literal = re.compile(
        r"id_bus_rx_masked\s*=\s*id_bus_rx\s*&\s*~\s*id_bus_drive_low",
        re.IGNORECASE,
    )
    assert pat_literal.search(chip_top), (
        "v1.6.90 (#22 Bug 1): rx_masked must use literal "
        "id_bus_drive_low so self_rx_mask_check finds the AND-NOT "
        f"pattern; chip_top body:\n{chip_top[:2000]}"
    )

    # Negative regression — must NOT mask via the alias.
    pat_alias_only = re.compile(
        r"id_bus_rx_masked\s*=\s*id_bus_rx\s*&\s*~\s*id_bus_oe\b",
        re.IGNORECASE,
    )
    assert not pat_alias_only.search(chip_top), (
        "v1.6.90 (#22 Bug 1): rx_masked must NOT mask via the alias "
        "(id_bus_oe); the literal OE driver name is required."
    )


def test_chip_top_asic_emits_literal_oe_in_rx_masked():
    """Mirror in the ASIC chip_top template."""
    from programs import aid_class_rtl_gen
    src = aid_class_rtl_gen.CHIP_TOP_ASIC
    pat_literal = re.compile(
        r"id_bus_rx_masked\s*=\s*id_bus_rx\s*&\s*~\s*id_bus_drive_low",
        re.IGNORECASE,
    )
    assert pat_literal.search(src), (
        "v1.6.90 (#22 Bug 1): CHIP_TOP_ASIC must mask via literal "
        "id_bus_drive_low so the half-duplex self-RX gate matches."
    )


# ---------------------------------------------------------------------------
# Bug 2 (P2) — _is_real_submodule_name verb deny-list
# ---------------------------------------------------------------------------
def test_is_real_submodule_name_rejects_common_verbs():
    """v1.6.90 (#22 Bug 2 P2): the helper itself rejects common
    English verbs that consistently leak from prose extractors."""
    from programs.phase1_one_shot_runner import _is_real_submodule_name
    forbidden = [
        "reads", "writes", "drives", "latches", "decodes",
        "asserts", "deasserts", "samples", "captures", "polls",
    ]
    for v in forbidden:
        assert not _is_real_submodule_name(v), (
            f"v1.6.90 (#22 Bug 2): verb '{v}' must be rejected by "
            "_is_real_submodule_name; got accepted."
        )


def test_is_real_submodule_name_keeps_real_module_names():
    """Positive control: real RTL module names must NOT be rejected."""
    from programs.phase1_one_shot_runner import _is_real_submodule_name
    # Note: pre-existing helper has a length-floor of 4; "fsm" (3
    # chars) is intentionally rejected as too-short. The positive
    # list below uses only names >= 4 chars.
    real = ["crc8", "tx_phy", "rx_phy", "byte_assembler",
            "wake_gen", "aes_core", "spi_master", "uart_rx"]
    for nm in real:
        assert _is_real_submodule_name(nm), (
            f"v1.6.90 (#22 Bug 2): real module name '{nm}' must be "
            "accepted; got rejected (regression)."
        )


def test_l9_submodule_rejects_verb_reads_end_to_end(tmp_path):
    """End-to-end: 'reads' (verb in prose) must NOT promote to
    L9.submodules even when extractor sees it."""
    from programs.phase1_one_shot_runner import (
        gen_l1_datasheet, gen_l9_integration_spec,
    )
    project = tmp_path / "verb_e2e"
    _seed_phase1_workdir(project)
    extracted = {
        "datasheet.txt": (
            "The host reads the OTP via id_bus.\n"
            "The IC writes the response back.\n"
            "Submodule: crc8 calculator.\n"
        ),
    }
    gen_l1_datasheet(project, extracted)
    gen_l9_integration_spec(project, extracted, {})
    names = _load_l9_submodule_names(project)
    assert "reads" not in names, (
        f"v1.6.90 (#22 Bug 2): 'reads' leaked into L9.submodules; "
        f"got names={sorted(names)}"
    )
    assert "writes" not in names, (
        f"v1.6.90 (#22 Bug 2): 'writes' leaked into L9.submodules; "
        f"got names={sorted(names)}"
    )
