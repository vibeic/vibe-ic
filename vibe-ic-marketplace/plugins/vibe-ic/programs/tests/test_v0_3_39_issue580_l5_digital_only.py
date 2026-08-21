"""ORGANIC #580 — on a pure-digital IC the phase1 L5 (analog interface
spec) emitter populated external_components / electrical_specs /
design_parameters from the SAME datasheet-literal pool the L8 emitter
harvests: jaccard(L5, L8) = 0.72 > the 70% threshold of the NON-WAIVABLE
l_doc_unique_content_check — a fully-honest clean-room run failed phase2
strict on plugin-generated content.

Fix: when no analog blocks are detected (no_analog), L5 is a minimal
typed NOT_APPLICABLE skeleton (applicability field + empty typed fields +
honest source_documents provenance), never populated from the shared
pool, so the uniqueness gate passes by construction.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase1_doc_one_shot_runner as P1  # noqa: E402

# Digital-only CPU-class doc: rich numeric content (the shared-literal
# pool L8 also harvests) but zero analog blocks.
_DIGITAL_DOC = """\
# RISC-V CPU Core Datasheet

A 32-bit in-order pipeline. Clock frequency 100 MHz, period 10 ns.
Reset is active-low rst_ni. The register file has 31 entries of 32 bits.
Instruction cache: 4 KB, 2-way. Timer compare register width 64 bits.
Interrupt lines: 32 external, threshold register 8 bits.
The boot address is 0x80000000 and the mtvec reset value is 0x00000100.
"""


def _run_l5_l8(tmp_path: Path):
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "input" / "docs" / "cpu.md").write_text(_DIGITAL_DOC)
    extracted = {"cpu.md": _DIGITAL_DOC}
    P1.gen_l5_adi_spec(tmp_path, extracted)
    P1.gen_l8_timing_waveform(tmp_path, extracted)  # writes L8_RTL_CONSTANTS
    gd = tmp_path / "phase1" / "generated_docs"
    l5 = json.loads((gd / "L5_ADI_SPEC.json").read_text())
    l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())
    return l5, l8


def test_digital_only_l5_is_not_applicable_skeleton(tmp_path):
    l5, _ = _run_l5_l8(tmp_path)
    assert l5["applicability"] == "NOT_APPLICABLE"
    assert l5["no_analog"] is True
    assert l5["analog_blocks"] == []
    assert l5["external_components"] == []
    assert l5["electrical_specs"] == []
    assert l5["design_parameters"] == []


def test_digital_only_l5_keeps_provenance(tmp_path):
    """phase1_provenance_presence_check requires non-empty
    provenance/source_documents at top level — the skeleton must not
    trade one gate FAIL for another."""
    l5, _ = _run_l5_l8(tmp_path)
    assert l5["source_documents"], l5
    assert "input/docs/cpu.md" in l5["source_documents"]


def test_digital_only_passes_unique_content_gate(tmp_path):
    """The issue's exact 驗收 end-state: l_doc_unique_content_check must
    PASS (rc 0) on fresh phase1 output for a digital-only IC — pre-fix it
    reported `L5_ADI_SPEC.json vs L8_RTL_CONSTANTS.json: jaccard=0.72`."""
    _run_l5_l8(tmp_path)
    result = subprocess.run(
        [sys.executable, str(PROG / "l_doc_unique_content_check.py"),
         str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout
    assert "L5_ADI_SPEC.json vs L8_RTL_CONSTANTS.json" not in result.stdout


def test_analog_ic_l5_still_populated(tmp_path):
    """NEGATIVE: an IC with real analog content keeps the full L5 shape
    (blocks + specs) — the skeleton only applies to no-analog projects."""
    doc = (
        "# AFE Datasheet\n\n"
        "## Block LDO (x1)\n"
        "The LDO regulator block: dropout 150 mV at 100 mA load,\n"
        "PSRR 60 dB at 1 kHz, output voltage 1.8 V accuracy 2%.\n"
        "Analog supply AVDD 3.3 V.\n"
    )
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "input" / "docs" / "afe.md").write_text(doc)
    P1.gen_l5_adi_spec(tmp_path, {"afe.md": doc})
    l5 = json.loads(
        (tmp_path / "phase1" / "generated_docs" / "L5_ADI_SPEC.json")
        .read_text())
    assert l5.get("applicability") != "NOT_APPLICABLE"
    assert l5["analog_blocks_detected"] is True
    assert l5["analog_blocks"]
