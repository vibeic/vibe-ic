"""v1.4.41 — FLOOR-DRC thick-top-metal LEF/deck reconciliation.

spm clean-room, proven via independent klayout `width_check` /
`enclosing_check` (NOT trusting the SVRF rule name): Mt.W.1_3 (MET5 min-width
0.44um) and Mt.EN.1_3 (VIA4-in-MET5 enclosure 0.09um) fired 1 and 6 real
violations respectively — an EXACT match to svrfdrc's own count, proving the
width/enclosure engine primitives are trustworthy (unlike the earlier
SHRINK/GROW wide-metal no-op). Root cause: the tech LEF states MET5
WIDTH/MINWIDTH 0.28um (a generic mid-layer profile) but the deck's ENABLED
`#DEFINE TOPMETAL_5` configures MET5 as this stackup's thick top metal,
governed by the deck's own `Mt.*` rule family requiring 0.44um — a genuine
LEF/deck inconsistency the router had no way to see from the LEF alone.

Fix: discover the deck's real top-metal minimum width for every ENABLED
`#DEFINE TOPMETAL_N` and, only when it exceeds the LEF's stated value, stage
a corrected LEF copy (WIDTH/MINWIDTH raised — never lowered) so every step
reading `PdkConfig.tech_lef` sees the deck-true number. Chip/PDK-AGNOSTIC:
no metal name or numeric value is hardcoded; these tests use a SYNTHETIC
deck/LEF with different names/values than the real PDK's to prove genericity.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


_LEF_TMPL = """\
LAYER MET2
  TYPE ROUTING ;
  WIDTH 0.20 ;
  MINWIDTH 0.20 ;
END MET2

LAYER MET3
  TYPE ROUTING ;
  WIDTH {w3} ;
  MINWIDTH {w3} ;
END MET3
"""

_DECK_TMPL = """\
#DEFINE TOPMETAL_3

Mx.W.1_1 {{
    @Mx.W.1: Min. width of Mx 0.20 MET2
    INTERNAL __met2__ <0.20 REGION SINGULAR ABUT<90
}}

Mt.W.1_1 {{
    @Mt.W.1: Min. width of Mt {deckw} MET3
    INTERNAL __met3__ <{deckw} REGION SINGULAR ABUT<90
}}

L1=NOT __via3__ sealring_THICK_IMD
L2=NOT __met3__ sealring_THICK_IMD
Mt.EN.1_1 {{
    @Mt.EN.1: Min. enclosure of Vt-1 by Mt {deckenc} MET3 VIA3
    L3=CUT L1 L2
    NOT L3 L2
    ENCLOSURE L1 L2 <{deckenc} REGION SINGULAR ABUT<90
}}
"""

_DECK_DISABLED_TMPL = _DECK_TMPL.replace("#DEFINE TOPMETAL_3",
                                          "//#DEFINE TOPMETAL_3")


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_noop_when_no_deck(tmp_path):
    lef = _write(tmp_path, "tech.lef", _LEF_TMPL.format(w3="0.28"))
    out, notes = R._discover_topmetal_width_fix(tmp_path, None, lef)
    assert out == lef
    assert notes == []


def test_noop_when_topmetal_option_disabled(tmp_path):
    lef = _write(tmp_path, "tech.lef", _LEF_TMPL.format(w3="0.28"))
    deck = _write(tmp_path, "deck.rule",
                  _DECK_DISABLED_TMPL.format(deckw="0.44", deckenc="0.09"))
    out, notes = R._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    assert out == lef  # the option is commented out -> never enabled
    assert notes == []


def test_noop_when_lef_already_honors_deck(tmp_path):
    # LEF already states 0.44 -- the deck's 0.44 requirement is already met.
    lef = _write(tmp_path, "tech.lef", _LEF_TMPL.format(w3="0.44"))
    deck = _write(tmp_path, "deck.rule",
                  _DECK_TMPL.format(deckw="0.44", deckenc="0.09"))
    out, notes = R._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    assert out == lef
    assert notes == []


def test_stages_corrected_lef_generic_layer_and_value(tmp_path):
    # A DIFFERENT layer (MET3, not the real PDK's MET5) and a DIFFERENT value
    # (0.55, not the real PDK's 0.44) -- proves the mechanism reads the deck's
    # own numbers rather than hardcoding any one PDK's fact.
    original_text = _LEF_TMPL.format(w3="0.20")
    lef = _write(tmp_path, "tech.lef", original_text)
    deck = _write(tmp_path, "deck.rule",
                  _DECK_TMPL.format(deckw="0.55", deckenc="0.12"))
    out, notes = R._discover_topmetal_width_fix(tmp_path, str(deck), lef)

    assert out != lef
    assert out.is_file()
    assert len(notes) == 1
    assert "TOPMETAL_3" in notes[0]
    assert "0.55" in notes[0]
    assert "0.12" in notes[0]  # Mt.EN.1 value captured for provenance

    fixed = out.read_text()
    assert "WIDTH 0.55 ;" in fixed
    assert "MINWIDTH 0.55 ;" in fixed
    # MET2 (not the top-metal option) is untouched.
    assert "WIDTH 0.20 ;" in fixed
    assert "MINWIDTH 0.20 ;" in fixed

    # the REAL PDK LEF on disk is never mutated.
    assert lef.read_text() == original_text

    # staged under the project, with a `.lef` extension -> already covered
    # by the project's blanket `*.lef` gitignore (never committed).
    assert out.parent == tmp_path / "phase3" / "pdk_stage"
    assert out.suffix == ".lef"


def test_multiple_enabled_topmetal_options_each_fixed(tmp_path):
    lef = _write(tmp_path, "tech.lef",
                 "LAYER MET3\n  WIDTH 0.20 ;\n  MINWIDTH 0.20 ;\nEND MET3\n"
                 "LAYER MET4\n  WIDTH 0.20 ;\n  MINWIDTH 0.20 ;\nEND MET4\n")
    deck = _write(tmp_path, "deck.rule", """\
#DEFINE TOPMETAL_3
#DEFINE TOPMETAL_4

Mt.W.1_1 {
    @Mt.W.1: Min. width of Mt 0.40 MET3
    INTERNAL __met3__ <0.40 REGION SINGULAR ABUT<90
}
Mt.W.1_2 {
    @Mt.W.1: Min. width of Mt 0.50 MET4
    INTERNAL __met4__ <0.50 REGION SINGULAR ABUT<90
}
""")
    out, notes = R._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    assert len(notes) == 2
    fixed = out.read_text()
    assert "WIDTH 0.4 ;" in fixed and "MINWIDTH 0.4 ;" in fixed
    assert "WIDTH 0.5 ;" in fixed and "MINWIDTH 0.5 ;" in fixed


def test_wired_into_custom_pdk_detection(tmp_path, monkeypatch):
    # end-to-end: _detect_pdk's custom-PDK branch calls the fix and
    # PdkConfig.tech_lef reflects the corrected (staged) path.
    pdk_dir = tmp_path / "input" / "pdk"
    (pdk_dir / "liberty").mkdir(parents=True)
    (pdk_dir / "liberty" / "std_tt.lib").write_text("library(std) {}\n")
    lef_dir = pdk_dir / "lef"
    lef_dir.mkdir()
    (lef_dir / "tech.tlef").write_text(
        "LAYER MET3\n  WIDTH 0.20 ;\n  MINWIDTH 0.20 ;\nEND MET3\n")
    (lef_dir / "macro.lef").write_text("MACRO INV\nEND INV\n")
    calibre_dir = pdk_dir / "calibre"
    calibre_dir.mkdir()
    (calibre_dir / "FOO_DRC.rule").write_text(
        _DECK_TMPL.format(deckw="0.44", deckenc="0.09"))

    pdk = R._detect_pdk(tmp_path, override="auto")
    assert pdk is not None
    assert "pdk_stage" in pdk.tech_lef
    assert Path(pdk.tech_lef).read_text().count("WIDTH 0.44 ;") >= 1
