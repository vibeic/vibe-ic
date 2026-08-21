"""The flow refuses to pick a tech LEF, then picks the macro abstract for you.

THE DEFECT (reproduced on origin/main @27ed3dc47, real vendor IP + real
5-routing-layer commercial tech LEF).

Phase 3 will not choose a metal stack. When a staged PDK ships several tech
LEFs it stops the run outright, on the stated ground that

    "The metal stack is a DESIGN CHOICE, so this flow will not pick one for
     you — an arbitrary pick yields a fully green sign-off against a stack
     nobody chose, which is indistinguishable from a correct one."

`_discover_local_macros` then answers that same question a SECOND time, on its
own, and differently::

    # Per-macro LEF: prefer M3, then M4, then any non-_ant.
    m3 = [f for f in nonant if f.stem.endswith("_M3")]

Hard-macro vendors ship one LEF abstract per routing-layer count —
`<macro>_M3.lef` … `<macro>_M7.lef` — and each variant obstructs exactly the
layers a stack of that height must not route over the macro on. So the variant
NUMBER is the metal-stack design choice, and the fixed `_M3` preference makes
it by filesystem convention rather than from the stack in force.

MEASURED CONSEQUENCE on a real Phase-3 run against a commercial PDK with a
5-routing-layer stack, where `_M3` was loaded because the preference is fixed:

  * the `_M5` abstract the stack calls for declares, over the WHOLE footprint,
        LAYER <m4> ; RECT <the whole macro footprint> ;
        LAYER <m5> ; RECT <the whole macro footprint> ;
  * the loaded `_M3` abstract declares neither, and the routed DEF holds
        <m4>  42 power-stripe segments covering  9.3% of the footprint
        <m5>   4 power-stripe segments covering  4.9% of the footprint
    directly over that footprint;
  * on <m3> — the top layer the loaded abstract DOES declare — the same PDN
    placed 0 segments.

The router honours what the abstract declares. The only reason it routed over
the macro on two layers is that it was handed the wrong abstract.

THE FIX: derive the variant from the tech LEF already in force (its
`TYPE ROUTING` layer count), so the stack is chosen once. When the count
cannot be read the historical pick STANDS — byte-identical behaviour — and the
guess is DISCLOSED, naming the layers the loaded abstract leaves free.

chip-AGNOSTIC: keyed on the `_M<N>` variant convention and on LEF grammar
only; no vendor, macro, foundry or process literal anywhere.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import phase3_one_shot_runner as p3


# --------------------------------------------------------------------------
# fixtures — a synthetic vendor macro shipping one abstract per stack height
# --------------------------------------------------------------------------
def _tech_lef(n_routing: int) -> str:
    """A tech LEF declaring exactly ``n_routing`` TYPE ROUTING layers."""
    out = ["VERSION 5.8 ;", "UNITS", "  DATABASE MICRONS 1000 ;", "END UNITS"]
    for i in range(1, n_routing + 1):
        out += [f"LAYER MX{i}",
                "  TYPE ROUTING ;",
                "  DIRECTION HORIZONTAL ;" if i % 2 else
                "  DIRECTION VERTICAL ;",
                "  PITCH 0.56 ;",
                "  WIDTH 0.28 ;",
                f"END MX{i}"]
        if i < n_routing:
            out += [f"LAYER CX{i}", "  TYPE CUT ;", f"END CX{i}"]
    out.append("END LIBRARY")
    return "\n".join(out) + "\n"


def _macro_lef(name: str, obs_layers: list) -> str:
    """A macro abstract obstructing ``obs_layers`` over its whole footprint.

    Carries a PIN PORT on a layer NOT in ``obs_layers`` so a parser that reads
    the file instead of the OBS section is caught.
    """
    body = [f"MACRO {name}",
            "  CLASS BLOCK ;",
            "  SIZE 200 BY 100 ;",
            "  PIN VDD",
            "    DIRECTION INOUT ; USE POWER ;",
            "    PORT",
            "      LAYER PINONLY ;",
            "        RECT 0 0 1 1 ;",
            "    END",
            "  END VDD",
            "  OBS"]
    for lyr in obs_layers:
        body += [f"    LAYER {lyr} ;", "      RECT 0 0 200 100 ;"]
    body += ["  END", f"END {name}", "END LIBRARY"]
    return "\n".join(body) + "\n"


def _stage(tmp_path: Path, variants: dict, extra: dict = None) -> Path:
    """Build a project with `input/pdk_local/vendor/LEF/<name>.lef` files."""
    lef_dir = tmp_path / "input" / "pdk_local" / "vendor" / "LEF"
    lef_dir.mkdir(parents=True)
    for stem, obs in variants.items():
        (lef_dir / f"{stem}.lef").write_text(_macro_lef("MACROA", obs))
    for stem, txt in (extra or {}).items():
        (lef_dir / f"{stem}.lef").write_text(txt)
    return tmp_path


# `_M<N>` obstructs MX1..MX<N> — the real vendor convention, and the reason
# the variant number is a stack declaration and not a preference.
FIVE_VARIANTS = {f"MACROA_M{n}": [f"MX{i}" for i in range(1, n + 1)]
                 for n in (3, 4, 5, 6, 7)}


def _picked(project: Path, tech_lef=None) -> list:
    _libs, lefs, _gds, _v = p3._discover_local_macros(project, tech_lef)
    return [Path(x).name for x in lefs]


# --------------------------------------------------------------------------
# the fix
# --------------------------------------------------------------------------
def test_the_abstract_follows_the_declared_stack(tmp_path):
    """5 routing layers in force -> the _M5 abstract, not the fixed _M3."""
    proj = _stage(tmp_path / "p", FIVE_VARIANTS)
    tlef = tmp_path / "tech.lef"
    tlef.write_text(_tech_lef(5))
    assert _picked(proj, tlef) == ["MACROA_M5.lef"]


@pytest.mark.parametrize("n,expect", [(3, "M3"), (4, "M4"), (5, "M5"),
                                      (6, "M6"), (7, "M7")])
def test_every_stack_height_selects_its_own_abstract(tmp_path, n, expect):
    proj = _stage(tmp_path / f"p{n}", FIVE_VARIANTS)
    tlef = tmp_path / f"tech{n}.lef"
    tlef.write_text(_tech_lef(n))
    assert _picked(proj, tlef) == [f"MACROA_{expect}.lef"]


def test_a_stack_taller_than_any_variant_takes_the_tallest_shipped(tmp_path):
    """9 routing layers, variants stop at M7 -> M7, and the gap is disclosed.

    Picking a LOWER variant would leave layers unobstructed; picking one that
    does not exist is not an option. The tallest shipped is the closest the
    vendor's own data can get, and that is stated rather than implied.
    """
    proj = _stage(tmp_path / "p", FIVE_VARIANTS)
    tlef = tmp_path / "tech.lef"
    tlef.write_text(_tech_lef(9))
    assert _picked(proj, tlef) == ["MACROA_M7.lef"]


def test_a_stack_shorter_than_every_variant_takes_the_lowest(tmp_path):
    proj = _stage(tmp_path / "p", FIVE_VARIANTS)
    tlef = tmp_path / "tech.lef"
    tlef.write_text(_tech_lef(2))
    assert _picked(proj, tlef) == ["MACROA_M3.lef"]


# --------------------------------------------------------------------------
# what must NOT change — this relaxes nothing and defaults to today
# --------------------------------------------------------------------------
def test_with_no_tech_lef_the_historical_pick_stands(tmp_path):
    """Called as before (one argument), the answer is byte-identical to today.

    The historical order is `_M3`, then `_M4`, then any non-`_ant`. Nothing
    about this change may move a run that cannot read its stack.
    """
    proj = _stage(tmp_path / "p", FIVE_VARIANTS)
    assert _picked(proj) == ["MACROA_M3.lef"]


def test_an_unreadable_tech_lef_is_not_silently_a_derivation(tmp_path):
    """A tech LEF that parses to zero routing layers == unknown, not zero."""
    proj = _stage(tmp_path / "p", FIVE_VARIANTS)
    tlef = tmp_path / "tech.lef"
    tlef.write_text("this is not a LEF\n")
    assert _picked(proj, tlef) == ["MACROA_M3.lef"]


def test_the_guess_names_the_layers_it_leaves_unobstructed(tmp_path, capsys):
    """A disclosure that does not say WHAT is unchecked is not a disclosure."""
    proj = _stage(tmp_path / "p", FIVE_VARIANTS)
    _picked(proj)
    out = capsys.readouterr().out
    assert "DISCLOSED PICK" in out
    assert "MACROA_M3.lef" in out
    # M7 obstructs MX1..MX7; M3 obstructs MX1..MX3. The four the loaded
    # abstract leaves free must be named.
    for lyr in ("MX4", "MX5", "MX6", "MX7"):
        assert lyr in out, f"{lyr} is left unobstructed and unnamed"


def test_a_derived_pick_records_the_count_it_derived_from(tmp_path, capsys):
    proj = _stage(tmp_path / "p", FIVE_VARIANTS)
    tlef = tmp_path / "tech.lef"
    tlef.write_text(_tech_lef(5))
    _picked(proj, tlef)
    out = capsys.readouterr().out
    assert "5 routing layer(s)" in out
    assert "MACROA_M5.lef" in out
    assert "DISCLOSED PICK" not in out


def test_a_macro_with_no_keyed_variants_is_untouched(tmp_path):
    """One plain abstract -> the same file, with or without a tech LEF."""
    proj = _stage(tmp_path / "p", {"PLAINMACRO": ["MX1"]})
    tlef = tmp_path / "tech.lef"
    tlef.write_text(_tech_lef(5))
    assert _picked(proj) == ["PLAINMACRO.lef"]
    assert _picked(proj, tlef) == ["PLAINMACRO.lef"]


def test_the_antenna_variant_is_still_never_preferred(tmp_path):
    """`_ant` abstracts are antenna models, not routing-stack variants."""
    proj = _stage(tmp_path / "p", FIVE_VARIANTS,
                  extra={"MACROA_ant": _macro_lef("MACROA_ANT", [])})
    tlef = tmp_path / "tech.lef"
    tlef.write_text(_tech_lef(5))
    assert _picked(proj, tlef) == ["MACROA_M5.lef"]
    assert _picked(proj) == ["MACROA_M3.lef"]


def test_still_exactly_one_abstract_per_macro(tmp_path):
    """Loading two abstracts of one macro is a parser collision, not a fix."""
    proj = _stage(tmp_path / "p", FIVE_VARIANTS)
    tlef = tmp_path / "tech.lef"
    tlef.write_text(_tech_lef(5))
    assert len(_picked(proj, tlef)) == 1


# --------------------------------------------------------------------------
# the OBS reader the disclosure depends on
# --------------------------------------------------------------------------
def test_obs_layers_reads_the_obs_section_and_not_the_pins(tmp_path):
    lef = tmp_path / "m.lef"
    lef.write_text(_macro_lef("M", ["MX1", "MX2", "MX3"]))
    assert p3._macro_abstract_obs_layers(lef) == ["MX1", "MX2", "MX3"]


def test_obs_layers_on_an_unreadable_file_is_cannot_derive(tmp_path):
    """[] must never be produced by a read failure AND by 'obstructs nothing'
    in a way the caller can tell apart — so the caller only ever uses it to
    subtract, never to assert an abstract obstructs nothing."""
    assert p3._macro_abstract_obs_layers(tmp_path / "absent.lef") == []
