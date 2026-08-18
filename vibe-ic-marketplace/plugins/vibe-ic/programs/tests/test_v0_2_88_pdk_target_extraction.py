"""v0.2.88 — #451: Phase 1 populates L19.pdk_target; the #438b
PDK-mismatch gate is never silent again.

Pins (acceptance):
  * input docs naming SG13G2 → extractor returns sg13g2 (the u_hawaii
    real gap: spec demands IHP SG13G2, decks used sky130, gate silent);
  * open-PDK tokens (sky130A, gf180mcuD) extracted bare;
  * commercial foundry names need PDK/process context (deny-guard);
  * pure-digital docs with no PDK vocabulary → None (no false positive);
  * gate side: analog deck + pdk_target=None → named
    PDK_TARGET_UNDECLARED WARNING (visible, not silent).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_netlist_pdk_check as NPC            # noqa: E402
import phase1_doc_one_shot_runner as P1           # noqa: E402


def _inputs(tmp_path, text):
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True)
    (d / "spec.md").write_text(text)
    return tmp_path


def test_sg13g2_extracted(tmp_path):
    p = _inputs(tmp_path,
                "# Spec\nTarget process: IHP SG13G2 130nm SiGe BiCMOS.\n")
    tgt, ev = P1._extract_pdk_target_from_inputs(p)
    assert tgt == "sg13g2"
    assert "SG13G2" in ev


def test_open_pdk_tokens_bare(tmp_path):
    p = _inputs(tmp_path, "Implemented on sky130A with the HD cells.\n")
    tgt, _ = P1._extract_pdk_target_from_inputs(p)
    assert tgt == "sky130a"


def test_foundry_name_needs_context(tmp_path):
    p = _inputs(tmp_path,
                "Our sales office in TSMC street handles orders.\n")
    tgt, _ = P1._extract_pdk_target_from_inputs(p)
    assert tgt is None
    p2 = _inputs(tmp_path / "b", "Fabricated in a TSMC 180nm process.\n")
    tgt2, _ = P1._extract_pdk_target_from_inputs(p2)
    assert tgt2 == "tsmc"


def test_no_pdk_vocab_returns_none(tmp_path):
    p = _inputs(tmp_path, "# Adder\nA 32-bit ripple-carry adder.\n")
    tgt, _ = P1._extract_pdk_target_from_inputs(p)
    assert tgt is None


def test_gate_warns_on_undeclared_target(tmp_path):
    a = tmp_path / "phase3" / "analog" / "blk"
    a.mkdir(parents=True)
    (a / "deck.sp").write_text(
        "* deck\n.lib /foss/pdks/sky130A/libs.tech/ngspice/"
        "sky130.lib.spice tt\n"
        "XM1 o i v v sky130_fd_pr__pfet_01v8 W=1 L=1\n.end\n")
    r = NPC.run_audit(tmp_path)   # no L19 at all → declared None
    assert any(f.rule == "PDK_TARGET_UNDECLARED"
               and f.severity == "WARNING" for f in r.findings)
    # visibility, not a block: only WARNING
    assert not any(f.rule == "PDK_TARGET_UNDECLARED"
                   and f.severity == "ERROR" for f in r.findings)


def test_gate_mismatch_still_fires_when_declared(tmp_path):
    a = tmp_path / "phase3" / "analog" / "blk"
    a.mkdir(parents=True)
    (a / "deck.sp").write_text(
        "* deck\n.lib /foss/pdks/sky130A/libs.tech/ngspice/"
        "sky130.lib.spice tt\nXM1 o i v v sky130_fd_pr__pfet_01v8\n.end\n")
    g = tmp_path / "phase1" / "generated_docs"
    g.mkdir(parents=True)
    (g / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
        {"fields": {"pdk_target": "sg13g2"}}))
    r = NPC.run_audit(tmp_path)
    assert any(f.rule == "PDK_MISMATCH" for f in r.findings)
    assert not any(f.rule == "PDK_TARGET_UNDECLARED" for f in r.findings)
