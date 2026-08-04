"""v1.6.68 — the thick-top-metal deck/LEF reconciliation was HALF a fix.

v1.4.41 discovered that a deck's enabled `#DEFINE TOPMETAL_N` option governs
the top metal by its own stricter `Mt.*` rule family, and reconciled the
tech LEF's WIDTH/MINWIDTH against the deck's `Mt.W.1`. It stopped there.

Measured on a real sign-off run of a commercial thick-top-metal PDK, AFTER
that fix had already staged its corrected LEF:

  * the same enabled option also states `Mt.S.1` (min space between two top
    metals) at a value the LEF under-declares — the router, which can only
    see the LEF, drew legal-per-LEF metal that the sign-off deck then failed
    in the hundreds;
  * it also states `Vt1.S.1` (min space between two top-1 vias) at a value
    the LEF's CUT layer under-declares — thousands more;
  * and worse, the width half ALONE made the staged LEF geometrically
    SELF-INCONSISTENT: WIDTH was raised while PITCH was left alone, so
    WIDTH + SPACING exceeded PITCH. A track grid finer than width+space
    cannot hold a legal wire on every track; the router will legally use
    adjacent tracks and produce spacing violations BY CONSTRUCTION. The fix
    for one rule manufactured violations of another.
  * the enclosure provenance lookup built the via layer's name by ARITHMETIC
    (VIA{n} for METn) rather than reading it, so on a deck whose "Vt-1" is
    the via BELOW the top metal it matched nothing, silently, forever.

These tests use a SYNTHETIC deck/LEF whose layer names, via-naming
convention and numeric values are all deliberately unlike any real PDK's,
so nothing here can pass by having memorised one vendor's stackup.

chip-AGNOSTIC / PDK-AGNOSTIC: every number and every layer name is read out
of the deck + LEF text supplied at run time.
"""
import re
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# A deliberately ODD stackup: the top metal is MET3, and the deck's "Vt-1"
# for MET3 is named TOPCUT9 — a name no arithmetic on "3" can ever produce.
#
# The stack declares THREE routing layers with MET3 on top, because the
# reconciler's PAIRED GUARD refuses to act when the deck's enabled
# `TOPMETAL_N` and the LEF's routing-layer count describe different stacks —
# a top-metal rule applied to an intermediate layer silently corrupts a thin
# routing layer. A two-layer fixture under `TOPMETAL_3` would exercise that
# guard, not this reconciliation; `test_a_stack_the_deck_is_not_written_for_
# is_left_alone` covers the guard on purpose.
_LEF = """\
LAYER MET1
  TYPE ROUTING ;
  PITCH 0.30 ;
  WIDTH 0.20 ;
  SPACING 0.10 ;
  MINWIDTH 0.20 ;
END MET1

LAYER MET2
  TYPE ROUTING ;
  PITCH 0.30 ;
  WIDTH 0.20 ;
  SPACING 0.10 ;
  MINWIDTH 0.20 ;
END MET2

LAYER MET3
  TYPE ROUTING ;
  PITCH {pitch} ;
  WIDTH {w} ;
  SPACING {sp} ;
  SPACING 0.90 RANGE 10.001 100000 ;
  MINWIDTH {w} ;
END MET3

LAYER TOPCUT9
  TYPE CUT ;
  SPACING {vsp} ;
  WIDTH 0.15 ;
END TOPCUT9
"""

_DECK = """\
#DEFINE TOPMETAL_3

Mx.S.1_1 {{
    @Mx.S.1: Min. space between two Mxs 0.10 MET2
    EXTERNAL backend__met2_not_array <0.10 REGION SINGULAR ABUT<90
}}

Mt.W.1_1 {{
    @Mt.W.1: Min. width of Mt {dw} MET3
    INTERNAL __met3__ <{dw} REGION SINGULAR ABUT<90
}}

Mt.S.1_1 {{
    @Mt.S.1: Min. space between two Mts 9.99 MET3
    EXTERNAL __met3__ <{ds} REGION SINGULAR ABUT<90
}}

L1=NOT __topcut9__ sealring_THICK_IMD
L2=NOT __met3__ sealring_THICK_IMD
Mt.EN.1_1 {{
    @Mt.EN.1: Min. enclosure of Vt-1 by Mt {denc} MET3 TOPCUT9
    L3=CUT L1 L2
    NOT L3 L2
    ENCLOSURE L1 L2 <{denc} REGION SINGULAR ABUT<90
}}

Vt1.S.1_1 {{
    @Vt1.S.1: Min. space between two Vt-1s 9.99 TOPCUT9
    EXTERNAL TOPCUT9_fuse <{dvs} REGION SINGULAR ABUT<90
}}
"""


def _run(tmp_path, *, w="0.20", sp="0.10", pitch="0.30", vsp="0.12",
         dw="0.50", ds="0.40", dvs="0.25", denc="0.07"):
    lef = tmp_path / "tech.lef"
    lef.write_text(_LEF.format(w=w, sp=sp, pitch=pitch, vsp=vsp))
    deck = tmp_path / "deck.rule"
    deck.write_text(_DECK.format(dw=dw, ds=ds, dvs=dvs, denc=denc))
    out, notes = R._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    text = Path(out).read_text() if out else ""
    return out, notes, text, lef


def _layer(text, name):
    m = re.search(r"(?ms)^LAYER\s+%s\s*\n(.*?)^END\s+%s\s*$"
                  % (re.escape(name), re.escape(name)), text)
    assert m, f"layer {name} missing from staged LEF"
    return m.group(1)


def _val(block, key):
    m = re.search(r"(?m)^\s*%s\s+([0-9.]+)\s*;" % re.escape(key), block)
    return float(m.group(1)) if m else None


# ── (1) SPACING: the half that was missing ───────────────────────────────
def test_top_metal_spacing_is_raised_to_the_deck_value(tmp_path):
    _, notes, text, _ = _run(tmp_path)
    assert _val(_layer(text, "MET3"), "SPACING") == 0.40
    assert any("Mt.S.1" in n for n in notes)


def test_spacing_comes_from_the_executable_line_not_the_comment(tmp_path):
    # The @comment in _DECK deliberately says 9.99 while the EXECUTABLE
    # `EXTERNAL ... <0.40` says 0.40. A deck's comment is prose; the
    # constraint the sign-off tool enforces is the EXTERNAL line.
    _, _, text, _ = _run(tmp_path, ds="0.40")
    assert _val(_layer(text, "MET3"), "SPACING") == 0.40


def test_spacing_is_never_lowered(tmp_path):
    # LEF already stricter than the deck -> left alone (and, with nothing
    # else to do, no staged file at all).
    out, notes, _, lef = _run(tmp_path, w="0.50", sp="0.60", pitch="1.20",
                              vsp="0.30")
    assert out == lef
    assert notes == []


def test_wide_metal_range_spacing_line_is_not_touched(tmp_path):
    # `SPACING <v> RANGE ...` is the WIDE-METAL rule, a different
    # constraint from the base spacing. Rewriting it would silently
    # re-scope a rule the deck never asked us to change.
    _, _, text, _ = _run(tmp_path)
    assert "SPACING 0.90 RANGE 10.001 100000 ;" in _layer(text, "MET3")


# ── (2) the arithmetic consequence the width-only fix manufactured ───────
def test_pitch_is_raised_so_width_plus_spacing_fits(tmp_path):
    _, notes, text, _ = _run(tmp_path)
    blk = _layer(text, "MET3")
    w, sp, pitch = _val(blk, "WIDTH"), _val(blk, "SPACING"), _val(blk, "PITCH")
    assert (w, sp) == (0.50, 0.40)
    assert pitch is not None and pitch >= w + sp, (
        "a track grid finer than WIDTH+SPACING cannot hold a legal wire on "
        "every track — the router produces spacing violations by construction")
    assert any("PITCH" in n for n in notes)


def test_pitch_is_left_alone_when_already_wide_enough(tmp_path):
    _, _, text, _ = _run(tmp_path, pitch="2.50")
    assert _val(_layer(text, "MET3"), "PITCH") == 2.50


# ── (3) spacing is evaluated even when the WIDTH half needs nothing ──────
def test_spacing_still_fixed_when_width_already_satisfies_the_deck(tmp_path):
    # The pre-v1.6.68 loop `continue`d as soon as the width was already
    # good, so a LEF that got the width right but the spacing wrong was
    # shipped unreconciled.
    _, notes, text, _ = _run(tmp_path, w="0.50", sp="0.10", pitch="1.00")
    assert _val(_layer(text, "MET3"), "SPACING") == 0.40
    assert any("Mt.S.1" in n for n in notes)


# ── (4) the CUT layer below the top metal ────────────────────────────────
def test_top_via_cut_spacing_is_raised_to_the_deck_value(tmp_path):
    _, notes, text, _ = _run(tmp_path)
    assert _val(_layer(text, "TOPCUT9"), "SPACING") == 0.25
    assert any("Vt1.S.1" in n for n in notes)


def test_cut_layer_width_is_not_turned_into_a_pitch(tmp_path):
    # A CUT layer has no track grid; inventing a PITCH for it would be a
    # fabricated constraint.
    blk = _layer(_run(tmp_path)[2], "TOPCUT9")
    assert _val(blk, "PITCH") is None
    assert _val(blk, "WIDTH") == 0.15


def test_cut_spacing_is_never_lowered(tmp_path):
    _, _, text, _ = _run(tmp_path, vsp="0.90")
    assert _val(_layer(text, "TOPCUT9"), "SPACING") == 0.90


# ── (5) the via layer NAME is read from the deck, never computed ─────────
def test_via_layer_name_is_read_from_the_deck_not_derived(tmp_path):
    # TOPCUT9 cannot be produced by any arithmetic on "3". If the note
    # carries it, and the cut layer got reconciled, the name was READ.
    _, notes, text, _ = _run(tmp_path)
    assert any("TOPCUT9" in n for n in notes)
    assert any("enclosure=0.07um" in n for n in notes)
    assert _val(_layer(text, "TOPCUT9"), "SPACING") == 0.25


def test_no_cut_fix_when_the_deck_names_no_top_via(tmp_path):
    # Deck without an Mt.EN.1 line -> we do not know which cut is "Vt-1",
    # so we touch none of them rather than guess.
    lef = tmp_path / "tech.lef"
    lef.write_text(_LEF.format(w="0.20", sp="0.10", pitch="0.30", vsp="0.12"))
    deck = tmp_path / "deck.rule"
    deck.write_text(re.sub(r"(?s)Mt\.EN\.1_1 \{.*?\n\}\n", "",
                           _DECK.format(dw="0.50", ds="0.40", dvs="0.25",
                                        denc="0.07")))
    out, notes, = R._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    text = Path(out).read_text()
    assert _val(_layer(text, "MET3"), "SPACING") == 0.40   # metal still fixed
    assert _val(_layer(text, "TOPCUT9"), "SPACING") == 0.12  # cut untouched
    assert not any("Vt1.S.1" in n for n in notes)


# ── (6) blast radius ─────────────────────────────────────────────────────
def test_non_top_metal_layers_are_untouched(tmp_path):
    blk = _layer(_run(tmp_path)[2], "MET2")
    assert (_val(blk, "WIDTH"), _val(blk, "SPACING"), _val(blk, "PITCH")) \
        == (0.20, 0.10, 0.30)


def test_the_real_pdk_lef_on_disk_is_never_mutated(tmp_path):
    original = _LEF.format(w="0.20", sp="0.10", pitch="0.30", vsp="0.12")
    out, _, _, lef = _run(tmp_path)
    assert out != lef
    assert lef.read_text() == original


def test_a_stack_the_deck_is_not_written_for_is_left_alone(tmp_path):
    """The PAIRED GUARD, pinned here because these three new rules run INSIDE
    the loop it protects.

    The deck's `Mt.*` family governs the stack's TOPMOST routing layer. If the
    tech LEF in hand declares a DIFFERENT number of routing layers than the
    deck's enabled `TOPMETAL_N`, the two describe different stacks and METn is
    an intermediate layer here — raising its width, its spacing AND its pitch
    would corrupt a thin routing layer three ways instead of one. Nothing is
    changed and the mismatch is said out loud.

    Without this, widening the reconciler from one rule to four would have
    quadrupled the blast radius of that mis-application while every existing
    test still passed.
    """
    lef = tmp_path / "tech.lef"
    # Two routing layers under an enabled TOPMETAL_3: the deck is written for
    # a taller stack than this LEF describes.
    lef.write_text(re.sub(r"(?ms)^LAYER MET1\n.*?^END MET1\n\n", "",
                          _LEF.format(w="0.20", sp="0.10", pitch="0.30",
                                      vsp="0.12")))
    original = lef.read_text()
    deck = tmp_path / "deck.rule"
    deck.write_text(_DECK.format(dw="0.50", ds="0.40", dvs="0.25",
                                 denc="0.07"))
    out, notes = R._discover_topmetal_width_fix(tmp_path, str(deck), lef)
    assert out == lef, "a mismatched stack was 'corrected' anyway"
    assert lef.read_text() == original
    assert any("SKIPPED" in n and "DIFFERENT metal stacks" in n
               for n in notes), notes
