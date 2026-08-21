"""A staged PDK that ships MORE THAN ONE tech LEF must not have its metal
stack chosen by filesystem order.

MEASURED DEFECT (pre-fix). `_detect_pdk` resolved the tech LEF as
``rglob("*tech*.lef")[0]``. A PDK that ships its stack as a MATRIX of tech
LEFs — one per (routing-layer-count x top-metal flavour) — therefore had its
metal stack picked by directory-walk order: arbitrary, not reproducible across
machines, and unrelated to the stack the design or the sign-off deck specifies.
Every downstream number (route, STA, DRC, GDS) is produced against that stack,
so the wrong pick yields a fully green sign-off for a stack nobody chose —
indistinguishable from a correct one.

Paired defect: `_discover_topmetal_width_fix` applies the deck's thick-top-metal
`Mt.W.1` minimum width to ``MET<N>`` for each enabled ``#DEFINE TOPMETAL_<N>``,
without checking that ``MET<N>`` is the LEF's TOPMOST routing layer. On a LEF
with more layers than the deck expects, that widens an INTERMEDIATE thin routing
layer using a rule written for the top metal.

WHAT THIS FILE PINS, AND WHAT IT DOES NOT (measured 2026-08-05)
==============================================================
Sections 1-4 and the two paired-guard tests in section 5 are REGRESSION GUARDS
FOR OLDER WORK. All nine of them PASS unchanged against e3aa9b126, the tree
immediately before 41c49f94d, so none of them discriminates that landing. The
landing commit said of the paired guard that it "is now pinned by a test of its
own"; the pin it refers to (`test_topmetal_width_fix_skips_a_stack_the_deck_does
_not_describe`) already existed, and 41c49f94d changed only the wording of one
assertion in `test_topmetal_width_fix_still_fires_on_the_matching_stack`. That
claim is corrected here rather than left standing.

Section 6 is the part that DOES discriminate it, and it belongs here rather than
in the deck-rule file next door because it needs no new deck rule at all: with
the SAME width-only deck used throughout this file, raising WIDTH alone leaves
the staged LEF geometrically self-inconsistent — WIDTH + SPACING greater than
PITCH, a track grid too fine to hold a legal wire on every track, so the router
legally uses adjacent tracks and manufactures spacing violations BY
CONSTRUCTION. Measured on e3aa9b126: 0.44 + 0.28 = 0.72um of demand left on a
0.66um pitch.

Every fixture below uses synthetic library, deck and layer names.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]


def _p3():
    if "p3_metalstack" in sys.modules:
        return sys.modules["p3_metalstack"]
    spec = importlib.util.spec_from_file_location(
        "p3_metalstack", PROGRAMS / "phase3_one_shot_runner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["p3_metalstack"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _tech_lef(n_routing: int, top_width: float) -> str:
    """A minimal tech LEF with `n_routing` ROUTING layers, MET1..MET<n>."""
    out = ["VERSION 5.7 ;"]
    for i in range(1, n_routing + 1):
        w = top_width if i == n_routing else 0.28
        out.append(
            f"LAYER MET{i}\n"
            f"  TYPE ROUTING ;\n"
            f"  DIRECTION {'HORIZONTAL' if i % 2 else 'VERTICAL'} ;\n"
            f"  PITCH 0.66 ;\n"
            f"  WIDTH {w} ;\n"
            f"  MINWIDTH {w} ;\n"
            f"END MET{i}")
    out.append("END LIBRARY")
    return "\n".join(out) + "\n"


_CELL_LEF = """VERSION 5.7 ;
SITE unit
  SIZE 0.66 BY 5.04 ;
END unit
MACRO CELLA
  PIN VDD
    DIRECTION INOUT ;
    USE POWER ;
  END VDD
  PIN VSS
    DIRECTION INOUT ;
    USE GROUND ;
  END VSS
END CELLA
END LIBRARY
"""

_LIBERTY = """library (libx_typ) {
  nom_voltage : 1.800000 ;
  nom_temperature : 25.000000 ;
  nom_process : 1.000000 ;
}
"""

# A deck whose runtime-option block enables exactly one top-metal option.
_DECK = """// Runtime option selection
//#DEFINE TOPMETAL_4
#DEFINE TOPMETAL_5
//#DEFINE TOPMETAL_6

Mt.W.1_3 {
    @Mt.W.1: Min. width of Mt 0.44 MET5
    INTERNAL __met5__ <0.44 REGION SINGULAR ABUT<90
}
"""


def _stage(root: Path, stacks: dict, deck: bool = True) -> Path:
    """Stage a PDK under `root`/input/pdk. `stacks` maps a flavour dir name to
    {layer_count: top_width}."""
    pdk = root / "input" / "pdk"
    (pdk / "liberty").mkdir(parents=True)
    (pdk / "liberty" / "libx_typ.lib").write_text(_LIBERTY)
    lefdir = pdk / "lef"
    for flavour, variants in stacks.items():
        d = lefdir / flavour
        d.mkdir(parents=True)
        for n, w in variants.items():
            (d / f"libx_{n}lm_tech.lef").write_text(_tech_lef(n, w))
    lefdir.mkdir(parents=True, exist_ok=True)
    (lefdir / "libx_macro.lef").write_text(_CELL_LEF)
    if deck:
        (pdk / "calibre").mkdir(parents=True)
        (pdk / "calibre" / "LIBX_DRC.rule").write_text(_DECK)
    return root


# --------------------------------------------------------------------------
# 1. The refusal — more than one candidate survives narrowing.
# --------------------------------------------------------------------------
def test_ambiguous_metal_stack_is_refused_not_guessed(tmp_path: Path) -> None:
    """Two flavours both offering the deck's declared layer count is ambiguous.
    The flow must REFUSE and name the key to set, never pick one silently."""
    proj = _stage(tmp_path, {"STD": {5: 0.44}, "ALT": {5: 0.44}})
    with pytest.raises(SystemExit) as ei:
        _p3()._detect_pdk(proj)
    msg = str(ei.value)
    assert "tech_lef" in msg, msg
    # It must ENUMERATE what it could not choose between — a refusal that does
    # not say what the candidates were is not actionable.
    assert "STD/libx_5lm_tech.lef" in msg and "ALT/libx_5lm_tech.lef" in msg, msg


# --------------------------------------------------------------------------
# 2. The deck narrows the matrix — structurally, by routing-layer count.
# --------------------------------------------------------------------------
def test_deck_topmetal_option_narrows_the_matrix(tmp_path: Path) -> None:
    """The deck enables TOPMETAL_5, so only the 5-routing-layer LEF qualifies —
    even though the 4lm and 6lm variants are also staged and one of them sorts
    first."""
    proj = _stage(tmp_path, {"STD": {4: 0.44, 5: 0.44, 6: 0.44}})
    cfg = _p3()._detect_pdk(proj)
    assert cfg is not None
    assert Path(cfg.tech_lef).name == "libx_5lm_tech.lef", cfg.tech_lef


def test_without_a_deck_an_ambiguous_matrix_still_refuses(tmp_path: Path) -> None:
    """No deck means no narrowing signal — which is a reason to refuse, not a
    licence to fall back to filesystem order."""
    proj = _stage(tmp_path, {"STD": {4: 0.44, 5: 0.44, 6: 0.44}}, deck=False)
    with pytest.raises(SystemExit):
        _p3()._detect_pdk(proj)


# --------------------------------------------------------------------------
# 3. The declaration wins.
# --------------------------------------------------------------------------
def test_bridge_signoff_config_declaration_selects_the_stack(
        tmp_path: Path) -> None:
    proj = _stage(tmp_path, {"STD": {5: 0.44}, "ALT": {5: 0.44}})
    bridge = proj / "input" / "pdk" / "bridge"
    bridge.mkdir(parents=True)
    (bridge / "signoff_config.json").write_text(
        '{"tech_lef": "lef/ALT/libx_5lm_tech.lef"}')
    cfg = _p3()._detect_pdk(proj)
    assert cfg is not None
    assert Path(cfg.tech_lef).parent.name == "ALT", cfg.tech_lef


def test_a_declaration_pointing_at_nothing_refuses(tmp_path: Path) -> None:
    """A declared path that does not exist must REFUSE, never silently fall
    back — falling back is how a sign-off ends up on an unintended stack."""
    proj = _stage(tmp_path, {"STD": {5: 0.44}, "ALT": {5: 0.44}})
    bridge = proj / "input" / "pdk" / "bridge"
    bridge.mkdir(parents=True)
    (bridge / "signoff_config.json").write_text(
        '{"tech_lef": "lef/NOPE/libx_5lm_tech.lef"}')
    with pytest.raises(SystemExit) as ei:
        _p3()._detect_pdk(proj)
    assert "does not exist" in str(ei.value)


# --------------------------------------------------------------------------
# 4. The single-tech-LEF case — every open PDK — is untouched.
# --------------------------------------------------------------------------
def test_single_tech_lef_pdk_is_unchanged(tmp_path: Path) -> None:
    """Every PDK this flow ships against declares exactly one tech LEF. That
    path must not consult a config, a deck, or anything else."""
    proj = _stage(tmp_path, {"STD": {5: 0.44}}, deck=False)
    cfg = _p3()._detect_pdk(proj)
    assert cfg is not None
    assert Path(cfg.tech_lef).name == "libx_5lm_tech.lef"


# --------------------------------------------------------------------------
# 5. The paired guard on the top-metal width reconciliation.
# --------------------------------------------------------------------------
def test_topmetal_width_fix_skips_a_stack_the_deck_does_not_describe(
        tmp_path: Path) -> None:
    """The deck enables TOPMETAL_5; the LEF in hand has SIX routing layers, so
    its MET5 is an INTERMEDIATE layer. Widening it to the top-metal minimum
    corrupts a thin routing layer, so the pass must change nothing and say so."""
    p3 = _p3()
    deck = tmp_path / "deck.rule"
    deck.write_text(_DECK)
    lef = tmp_path / "libx_6lm_tech.lef"
    lef.write_text(_tech_lef(6, 2.0))          # MET5 is 0.28 here, MET6 is top
    out, notes = p3._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    assert out == lef, "the LEF must be returned UNCHANGED"
    assert notes and "SKIPPED" in notes[0], notes
    assert "DIFFERENT metal stacks" in notes[0], notes
    assert not (tmp_path / "phase3" / "pdk_stage").exists()


def test_topmetal_width_fix_still_fires_on_the_matching_stack(
        tmp_path: Path) -> None:
    """The guard must not disable the pass: on the stack the deck IS written
    for, an under-declared top-metal width is still corrected."""
    p3 = _p3()
    deck = tmp_path / "deck.rule"
    deck.write_text(_DECK)
    lef = tmp_path / "libx_5lm_tech.lef"
    lef.write_text(_tech_lef(5, 0.28))         # top metal under the deck's 0.44
    out, notes = p3._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    assert out != lef, "a corrected LEF should have been staged"
    # The note is tagged `[topmetal-deck-lef-fix]`: the pass reconciles the
    # deck's WIDTH, SPACING, PITCH and top-cut SPACING, so the older
    # `topmetal-width-fix` tag named one quarter of what it does. Asserted on
    # the SUBSTANCE — which rule fired and on which layer — so a future
    # re-tagging cannot make this test go quiet either.
    assert notes and "TOPMETAL_5" in notes[0] and "MET5" in notes[0], notes
    assert "Mt.W.1" in notes[0] and "0.44" in notes[0], notes
    assert "0.44" in Path(out).read_text()


def test_topmetal_width_fix_is_a_noop_when_the_lef_already_honors_the_deck(
        tmp_path: Path) -> None:
    p3 = _p3()
    deck = tmp_path / "deck.rule"
    deck.write_text(_DECK)
    lef = tmp_path / "libx_5lm_tech.lef"
    lef.write_text(_tech_lef(5, 0.44))
    out, notes = p3._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    assert out == lef and not notes


# --------------------------------------------------------------------------
# 6. The staged LEF must be a stack a router can legally use.
#
# Everything above this line passes on e3aa9b126 too. This section is what
# discriminates 41c49f94d, and it uses the SAME width-only deck as the rest of
# the file — the point is that fixing the WIDTH rule ALONE is what breaks the
# geometry, so no new deck rule is needed to show it.
# --------------------------------------------------------------------------
def _tech_lef_spaced(n_routing: int, top_width: float, *,
                     top_spacing: float = 0.28, pitch: float = 0.66) -> str:
    """`_tech_lef` plus the SPACING every real tech LEF declares.

    A separate builder on purpose: the nine tests above are regression guards
    for older work and must keep running against byte-identical fixtures.
    """
    out = ["VERSION 5.7 ;"]
    for i in range(1, n_routing + 1):
        w = top_width if i == n_routing else 0.28
        s = top_spacing if i == n_routing else 0.28
        out.append(
            f"LAYER MET{i}\n"
            f"  TYPE ROUTING ;\n"
            f"  DIRECTION {'HORIZONTAL' if i % 2 else 'VERTICAL'} ;\n"
            f"  PITCH {pitch} ;\n"
            f"  WIDTH {w} ;\n"
            f"  MINWIDTH {w} ;\n"
            f"  SPACING {s} ;\n"
            f"END MET{i}")
    out.append("END LIBRARY")
    return "\n".join(out) + "\n"


def _met_layer(lef_text: str, name: str) -> dict:
    seg = lef_text[lef_text.index(f"LAYER {name}\n"):]
    seg = seg[:seg.index(f"END {name}")]
    return {k.lower(): float(v) for k, v in
            re.findall(r"^\s*(PITCH|WIDTH|MINWIDTH|SPACING)\s+([\d.]+)\s*;",
                       seg, re.MULTILINE)}


def test_the_staged_lef_can_hold_a_legal_wire_on_every_track(
        tmp_path: Path) -> None:
    """THE defect this landing fixes, on this file's own deck.

    The deck states a top-metal minimum WIDTH the LEF under-declares. Raising
    WIDTH and leaving PITCH is not a fix: the routing grid then has a pitch
    FINER than width+space, so a wire that is legal on one track is illegal
    against its neighbour, and the router — which can only see the LEF — draws
    exactly that and hands the sign-off deck a wall of spacing violations it
    manufactured itself.

    Measured on e3aa9b126 with the fixture below: WIDTH 0.44, SPACING 0.28,
    PITCH 0.66 — 0.72um of demand on a 0.66um grid.
    """
    p3 = _p3()
    deck = tmp_path / "deck.rule"
    deck.write_text(_DECK)
    lef = tmp_path / "libx_5lm_tech.lef"
    lef.write_text(_tech_lef_spaced(5, 0.28))       # top metal under the deck
    out, notes = p3._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    assert out != lef, "a corrected LEF should have been staged"
    met5 = _met_layer(Path(out).read_text(), "MET5")
    assert met5["width"] == 0.44 and met5["minwidth"] == 0.44, met5
    assert met5["width"] + met5["spacing"] <= met5["pitch"], (
        f"the staged LEF is geometrically self-inconsistent: WIDTH "
        f"{met5['width']} + SPACING {met5['spacing']} = "
        f"{met5['width'] + met5['spacing']} exceeds PITCH {met5['pitch']}, so "
        f"no legal wire exists on every track and the router produces spacing "
        f"violations by construction\nnotes: {notes}")


def test_a_stack_with_room_already_keeps_its_pitch(tmp_path: Path) -> None:
    """The pitch is DERIVED, never set to a constant, and never LOWERED. A LEF
    whose grid already has room for the widened wire must keep the grid it
    shipped with — coarsening it would cost routing resource for nothing."""
    p3 = _p3()
    deck = tmp_path / "deck.rule"
    deck.write_text(_DECK)
    lef = tmp_path / "libx_5lm_tech.lef"
    lef.write_text(_tech_lef_spaced(5, 0.28, pitch=2.0))
    out, _notes = p3._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    met5 = _met_layer(Path(out).read_text(), "MET5")
    assert met5["width"] == 0.44, met5
    assert met5["pitch"] == 2.0, (
        f"the pitch was rewritten to {met5['pitch']} on a stack that already "
        f"had room for width+space")


def test_an_intermediate_layer_is_never_touched(tmp_path: Path) -> None:
    """Over-breadth guard for section 6: the reconciliation is about the layer
    the deck's TOPMETAL option names. Every other layer must come through the
    staging byte-for-byte, pitch included."""
    p3 = _p3()
    deck = tmp_path / "deck.rule"
    deck.write_text(_DECK)
    lef = tmp_path / "libx_5lm_tech.lef"
    lef.write_text(_tech_lef_spaced(5, 0.28))
    out, _notes = p3._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    staged = Path(out).read_text()
    for lower in ("MET1", "MET2", "MET3", "MET4"):
        assert _met_layer(staged, lower) == _met_layer(lef.read_text(), lower)
