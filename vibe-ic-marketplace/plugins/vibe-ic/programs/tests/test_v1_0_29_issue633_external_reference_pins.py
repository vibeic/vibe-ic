"""Regression for ORGANIC #633 — analog_content_detected_must_emit_l5_check
over-fires on external reference PINS (VREF/VHI/VLO), demanding an on-chip
bandgap L5 block for a data-converter taking an externally-supplied reference.

現象 (round-2 v1.0.22 6-IC clean-room): the gate's bandgap keyword class
matches `VREF`/`Vref`. For a delta-sigma ADC whose ONLY reference evidence is
external reference-PIN declarations ("Reference pins VHI/VLO", "Vref ...
reference (VHI−VLO)"), the gate FAILs ("bandgap (6 hits) — need L5 entry")
even though there is NO on-chip bandgap/reference circuit to spec. The gate's
only suppression was per-hit negation; it had no path distinguishing an
external reference PIN from an on-chip bandgap BLOCK.

Fix: an external-reference-pin discriminator. The bandgap class requires an L5
entry ONLY when an on-chip bandgap descriptor is present; the requirement is
SUPPRESSED when every bandgap-class hit is a bare external-reference-pin
mention AND the reference is positively externally supplied (a reference token
declared as an external pin in L1.pin_table / L9.top_ports, OR an explicit
external-reference-pin context on a hit line).

NEGATIVE no-leak: (a) a genuine on-chip bandgap descriptor (bandgap / BG_ref /
reference circuit) still demands an L5 entry; (b) an ambiguous bare `VREF` with
NO external-pin declaration stays fail-closed (still FAILs); (c) an on-chip
bandgap WITH a matching L5 block still PASSes.

chip-AGNOSTIC: pure pin-declaration + on-chip-descriptor structure; no chip /
vendor / SKU literal.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import analog_content_detected_must_emit_l5_check as G  # noqa: E402

_GATE = _PROGRAMS / "analog_content_detected_must_emit_l5_check.py"


def _build(tmp_path, l1_md, l5_md, l5_blocks, l1_pins):
    """Defect-artifact fixture: a project shaped like the round-2 converter —
    external reference-pin docs + an L5 with only the real (non-bandgap)
    blocks + an L1 pin_table declaring the reference tokens as external pins."""
    proj = tmp_path / "proj"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (docs / "L1_DATASHEET.md").write_text(l1_md)
    (docs / "L5_ANALOG_SPEC.md").write_text(l5_md)
    (gd / "L5_ADI_SPEC.json").write_text(
        json.dumps({"analog_blocks": l5_blocks}))
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"pin_table": [{"name": n} for n in l1_pins]}))
    return proj


def _run(proj):
    r = subprocess.run([sys.executable, str(_GATE), str(proj)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


# ── (1) the fix: external reference pins no longer false-FAIL ─────────────────

def test_external_reference_pins_pass(tmp_path):
    proj = _build(
        tmp_path,
        "Reference pins VHI/VLO; VLDO/VREF for the LDO channel "
        "(external supply).\n",
        "| Vref | reference (VHI-VLO) | external |\n"
        "Delta-sigma modulator, 2nd order. On-chip LDO regulator.\n",
        [{"name": "mod", "type": "delta_sigma"},
         {"name": "reg", "type": "ldo"}],
        ["VHI", "VLO", "VREF", "clk", "dout"])
    rc, out = _run(proj)
    assert rc == 0, out
    assert "[PASS]" in out


# ── (2) NEGATIVE no-leak ─────────────────────────────────────────────────────

def test_onchip_bandgap_descriptor_still_required_NOLEAK(tmp_path):
    """A genuine on-chip bandgap circuit (descriptor present) with no matching
    L5 block STILL FAILs — the suppression must not leak."""
    proj = _build(
        tmp_path,
        "On-chip bandgap reference circuit provides 1.2V.\n",
        "Bandgap reference core generates VBG. Delta-sigma modulator.\n",
        [{"name": "mod", "type": "delta_sigma"}],
        ["clk", "dout"])
    rc, out = _run(proj)
    assert rc == 1 and "[FAIL]" in out


def test_ambiguous_vref_without_external_decl_fails_closed_NOLEAK(tmp_path):
    """A bare `VREF` with NO external-pin declaration and no on-chip descriptor
    stays fail-closed (still FAILs) — the suppression requires positive
    external evidence."""
    proj = _build(
        tmp_path,
        "The part uses VREF internally.\n",
        "VREF node. Delta-sigma modulator.\n",
        [{"name": "mod", "type": "delta_sigma"}],
        ["clk", "dout"])  # VREF NOT in pin_table
    rc, out = _run(proj)
    assert rc == 1 and "[FAIL]" in out


def test_onchip_bandgap_with_block_passes_NOLEAK(tmp_path):
    proj = _build(
        tmp_path,
        "On-chip bandgap.\n", "Bandgap reference.\n",
        [{"name": "bg", "type": "bandgap"}], ["clk"])
    rc, out = _run(proj)
    assert rc == 0 and "[PASS]" in out


# ── (3) helper unit ──────────────────────────────────────────────────────────

def test_bandgap_external_only_helper(tmp_path):
    proj = _build(
        tmp_path, "Reference pins VHI/VLO; VREF external.\n",
        "Vref reference (VHI-VLO).\n",
        [{"name": "mod", "type": "delta_sigma"}],
        ["VHI", "VLO", "VREF"])
    # external-only when reference token is a declared external pin
    assert G._bandgap_external_only(
        proj, ["Vref reference (VHI-VLO) external"]) is True
    # NOT external-only when an on-chip descriptor is present
    assert G._bandgap_external_only(
        proj, ["on-chip bandgap reference circuit"]) is False
    # a CLEAN project with no L1/L9 (no declared external pins):
    empty = tmp_path / "empty"
    empty.mkdir()
    # the reference-pin CONTEXT alone (no L1/L9 needed) is enough
    assert G._bandgap_external_only(
        empty, ["Reference pins VHI/VLO supplied off-chip"]) is True
    # a bare VREF with no external evidence → fail-closed
    assert G._bandgap_external_only(empty, ["uses VREF"]) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
