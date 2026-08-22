"""v0.3.2 — ORGANIC-20260606 #496 ROUND-2 (REOPENED): close both halves of
the analog PDK-substitution disclosure path.

ROUND-1 (test_v0_3_1_issue496_analog_pdk_waiver.py — kept green) wired the
GATE: `flow_compliance_check._pdk_substitution_disclosed` synthesises a
WAIVED-DEFERRED only when the SPICE deck head carries a STRUCTURED
`pdk_substitution` marker. The field agent's counter-evidence:

  ✅ the gate mechanism is correct and strict (injected marker → WAIVED-
     DEFERRED; stripped → hard FAIL).
  ❌ but NOTHING in the plugin EMITTED that structured marker — real runner
     decks carry a PROSE 'PDK NOTE (disclosed)' header the gate could not
     read, so honest real artifacts still dead-ended at A3 FAIL.

ROUND-2 closes both halves and CLOSES THE SELF-TEST GAP (round-1 never tested
the emitter, nor the prose-shaped real artifact):

  (1) EMITTER — analog_real_corner_sweep emits the structured
      `pdk_substitution: target=<L19> substitute=<sim pdk> reason=...` line
      into the deck head whenever the L19 tapeout target differs from the
      simulation PDK family; nothing when they match / no concrete target.
  (2) GATE — `_pdk_substitution_disclosed` ALSO recognises the existing PROSE
      'PDK NOTE' disclosure (PDK NOTE + disclose/substitute wording + BOTH
      PDK names present) so previously-generated honest artifacts pass with
      NO regeneration / NO injection. Undisclosed mismatch still hard-FAILs.

FIELD ACCEPTANCE (verbatim): a REAL-shaped prose artifact WITHOUT any
injected structured marker → A3 = WAIVED-DEFERRED named pdk-substitution.

chip-AGNOSTIC: the fixtures use ONLY open-standard PDK family tokens
(sky130 / sky130A — SkyWater open-source default; sg13g2 / SG13G2 — IHP
open-PDK 130nm process). No chip / vendor / SKU literal; block name is the
open-vocabulary class ``ldo`` / ``delta_sigma``. None are in
programs/tests/chip_deny_list.txt.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_PLUGIN_ROOT = _THIS.parent.parent.parent          # …/plugins/vibe-ic
_PROGS = _PLUGIN_ROOT / "programs"
_FC = _PROGS / "flow_compliance_check.py"
sys.path.insert(0, str(_PROGS))
import flow_compliance_check as fc          # noqa: E402
import analog_real_corner_sweep as rcs      # noqa: E402


# ── open-standard PDK family tokens (NOT chip/vendor/SKU literals) ───────────
_SUBSTITUTE_PDK = "sky130"     # simulation family token (what _detect_pdk returns)
_TARGET_PDK = "sg13g2"         # non-default tapeout target, no public ngspice models

# The REAL prose-format header, copied verbatim in shape from the on-disk
# runner artifact
# <corpus>/u_hawaii_adc_e2e_v02100/phase3/analog/
#   delta_sigma/delta_sigma.sp — a free-text 'PDK NOTE (disclosed)' block with
# NO structured `pdk_substitution` marker anywhere. This is exactly the shape
# the field agent says the round-1 gate could not read.
_PROSE_HEADER = (
    "* delta_sigma — incremental delta-sigma integrator-core subcircuit (A3 netlist gen)\n"
    "* Derived from the A4 real-ngspice-simulated deck\n"
    "* phase3/analog/delta_sigma/sizing_loop/run_cs_0.5p.sp\n"
    "* (A4 PASS_INFORMATIONAL, settled vout=0.8988 V on the sky130A typical proxy).\n"
    "*\n"
    "* PDK NOTE (disclosed): tapeout target is IHP SG13G2 (L9/L19) @ core 1.2 V. SG13G2 has no\n"
    "* public ngspice corner lib, so the open-source sim deck uses sky130A typical models —\n"
    "* modeled, NOT silicon sign-off. The subckt structure is PDK-portable.\n"
    "*\n"
)
_DECK_BODY = (
    ".option scale=1u\n"
    ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt\n"
    "xm1 nd1 vinn ntail vss sky130_fd_pr__nfet_01v8 w=16 l=0.5\n"
    "xm3 nd1 nd1 vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.5\n"
    ".end\n"
)


def _write_l19(proj: Path, target: str | None) -> None:
    g = proj / "phase1" / "generated_docs"
    g.mkdir(parents=True, exist_ok=True)
    f = g / "L19_CONSTRAINTS_PDK.json"
    if target is None:
        if f.exists():
            f.unlink()
        return
    f.write_text(json.dumps({"fields": {"pdk_target": target}}))


def _write_block_list(proj: Path, block: str, btype: str) -> None:
    pa = proj / "phase1" / "analog"
    pa.mkdir(parents=True, exist_ok=True)
    (pa / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"type": btype, "name": block}]}))


def _write_prose_deck(proj: Path, block: str, *, header: str) -> Path:
    """Lay down the prose-format deck at the canonical analog dir the gate
    scans (phase3/analog/<block>)."""
    bdir = proj / "phase3" / "analog" / block
    bdir.mkdir(parents=True, exist_ok=True)
    sp = bdir / f"{block}.sp"
    sp.write_text(header + _DECK_BODY)
    return sp


def _run_strict(proj: Path) -> tuple[int, str]:
    res = subprocess.run(
        [sys.executable, str(_FC), str(proj), "--strict"],
        capture_output=True, text=True)
    return res.returncode, res.stdout + res.stderr


def _a3_block(out: str) -> str:
    lines = out.splitlines()
    grabbed: list[str] = []
    capturing = False
    for ln in lines:
        if "Step A3" in ln and ("[" in ln):
            capturing = True
            grabbed.append(ln)
            continue
        if capturing:
            if ln.startswith("       ") or ln.lstrip().startswith("└"):
                grabbed.append(ln)
            else:
                break
    return "\n".join(grabbed)


# ═════════════════ HALF 2 (GATE): prose disclosure recognition ══════════════
# This is the layer the round-1 self-test MISSED — it only built structured
# markers, never the real prose artifact.

def test_gate_recognises_prose_pdk_note_no_injection(tmp_path):
    """A REAL-shaped prose deck (PDK NOTE, NO structured marker) is accepted
    by the gate predicate WITHOUT any injection."""
    proj = tmp_path / "chip"
    _write_l19(proj, _TARGET_PDK)
    sp = _write_prose_deck(proj, "delta_sigma", header=_PROSE_HEADER)
    # sanity: the artifact carries NO structured marker — pure prose.
    assert "pdk_substitution" not in sp.read_text().lower()
    d = fc._pdk_substitution_disclosed(proj)
    assert d is not None, "prose 'PDK NOTE' disclosure must be recognised"
    assert d["target"].lower() == _TARGET_PDK
    assert "sky130" in d["substitute"].lower()
    assert d["deck"].endswith("delta_sigma.sp")


def test_gate_prose_requires_both_pdk_names(tmp_path):
    """Prose that names PDK NOTE + disclose wording but OMITS the declared
    target token is NOT a valid disclosure (the honesty bar: both PDKs named)."""
    proj = tmp_path / "chip"
    _write_l19(proj, _TARGET_PDK)
    # header that drops every mention of the target family.
    header = (
        "* PDK NOTE (disclosed): open-source sim deck uses sky130A typical "
        "models — modeled, NOT silicon sign-off.\n*\n"
    )
    _write_prose_deck(proj, "delta_sigma", header=header)
    assert fc._pdk_substitution_disclosed(proj) is None


def test_gate_prose_requires_disclose_wording(tmp_path):
    """A 'PDK NOTE' that names both PDKs but carries NO disclose/substitute
    wording is not accepted (prevents a bare comparison note from gaming)."""
    proj = tmp_path / "chip"
    _write_l19(proj, _TARGET_PDK)
    header = (
        "* PDK NOTE: target sg13g2 vs sky130A comparison table below.\n*\n"
    )
    _write_prose_deck(proj, "delta_sigma", header=header)
    assert fc._pdk_substitution_disclosed(proj) is None


def test_gate_prose_none_when_no_l19_target(tmp_path):
    proj = tmp_path / "chip"
    _write_l19(proj, None)
    _write_prose_deck(proj, "delta_sigma", header=_PROSE_HEADER)
    assert fc._pdk_substitution_disclosed(proj) is None


def test_gate_prose_none_when_target_matches_sim(tmp_path):
    """No real mismatch (L19 target == the sim family) → no deferral."""
    proj = tmp_path / "chip"
    _write_l19(proj, "sky130A")
    _write_prose_deck(proj, "delta_sigma", header=_PROSE_HEADER)
    assert fc._pdk_substitution_disclosed(proj) is None


# ═════════ FIELD ACCEPTANCE: replay the failing scenario END-TO-END ═════════
# A real-shaped prose artifact WITHOUT injection → A3 = WAIVED-DEFERRED named
# pdk-substitution. THIS is the exact scenario the field agent says still FAILs.

def test_acceptance_prose_artifact_a3_waived_deferred(tmp_path):
    proj = tmp_path / "chip"
    _write_l19(proj, _TARGET_PDK)
    _write_block_list(proj, "delta_sigma", "delta_sigma")
    # A3 required_outputs / gate files also live under phase2/analog.
    p2 = proj / "phase2" / "analog" / "delta_sigma"
    p2.mkdir(parents=True, exist_ok=True)
    (p2 / "delta_sigma.sp").write_text(_PROSE_HEADER + _DECK_BODY)
    _write_prose_deck(proj, "delta_sigma", header=_PROSE_HEADER)

    rc, out = _run_strict(proj)
    a3 = _a3_block(out)
    assert "WAIVED-DEFERRED" in a3, out
    assert "pdk-substitution" in a3.lower() or "PDK_SUBSTITUTION" in a3
    assert fc._PDK_SUBSTITUTION_TICKET in a3
    assert "review_required=True" in a3
    # NOT counted as executed-PASS.
    assert "[PASS" not in a3
    assert "not executed-PASS" in a3
    assert _TARGET_PDK in a3.lower()

    # ── strip the disclosure entirely → A3 hard-FAILs ─────────────────────
    for rel in ("phase2/analog/delta_sigma/delta_sigma.sp",
                "phase3/analog/delta_sigma/delta_sigma.sp"):
        p = proj / rel
        p.write_text("* delta_sigma deck (no disclosure)\n" + _DECK_BODY)
    rc2, out2 = _run_strict(proj)
    a3_2 = _a3_block(out2)
    assert "[FAIL" in a3_2, out2
    assert "WAIVED" not in a3_2


# ════════════════ HALF 1 (EMITTER): structured marker is written ════════════
# The other layer round-1 never tested — that the plugin ACTUALLY emits the
# structured marker the gate was built to read.

def test_emitter_writes_structured_marker_on_mismatch(tmp_path):
    """When L19 target differs from the sim PDK family, the emitter produces
    the structured `pdk_substitution: target=... substitute=...` line."""
    proj = tmp_path / "chip"
    _write_l19(proj, _TARGET_PDK)
    line = rcs.pdk_substitution_header(proj, _SUBSTITUTE_PDK)
    assert line, "emitter must produce a disclosure on a real mismatch"
    low = line.lower()
    assert low.startswith("* pdk_substitution:")
    assert f"target={_TARGET_PDK}" in low
    assert f"substitute={_SUBSTITUTE_PDK}" in low
    assert "no public ngspice models" in low


def test_emitter_silent_when_no_mismatch(tmp_path):
    """No structured line when the sim family IS the declared target."""
    proj = tmp_path / "chip"
    _write_l19(proj, "sky130A")
    assert rcs.pdk_substitution_header(proj, _SUBSTITUTE_PDK) == ""


def test_emitter_silent_when_no_l19_target(tmp_path):
    proj = tmp_path / "chip"
    _write_l19(proj, None)
    assert rcs.pdk_substitution_header(proj, _SUBSTITUTE_PDK) == ""


def test_emitter_output_is_read_back_by_gate(tmp_path):
    """END-TO-END: the structured line the EMITTER writes is exactly what the
    GATE recognises — closing the round-1 emitter↔gate disconnect. We build a
    deck whose ONLY disclosure is the emitter-produced structured line."""
    proj = tmp_path / "chip"
    _write_l19(proj, _TARGET_PDK)
    emit_line = rcs.pdk_substitution_header(proj, _SUBSTITUTE_PDK)
    assert emit_line
    bdir = proj / "phase3" / "analog" / "ldo0"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "ldo0.sp").write_text(emit_line + _DECK_BODY)
    d = fc._pdk_substitution_disclosed(proj)
    assert d is not None, "gate must read the emitter's own structured marker"
    assert d["target"].lower() == _TARGET_PDK
    assert "sky130" in d["substitute"].lower()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
