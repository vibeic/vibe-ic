"""The pin: the LEF-write defaults this producer bakes in, read from upstream.

`digital_hardmacro_gen.build_lef_tcl` writes `-hide` and omits `-pinonly`
"because upstream's own script writes it by default", and takes the read-views
route "because `MAGIC_LEF_WRITE_USE_GDS` defaults to false". Those are three
statements about somebody else's code. This asks that code.

The GDS-only route was MEASURED, on a real signed-off run, to produce a LEF
with ZERO PINS — so a default that moves upstream and not here is not a
cosmetic divergence.

SKIPS BY NAME where upstream is not installed. A skip says the question could
not be put; it does not say the answer was yes.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "_dhm_gen_pin", PROGRAMS / "digital_hardmacro_gen.py")
DHM = importlib.util.module_from_spec(_spec)
sys.modules["_dhm_gen_pin"] = DHM
_spec.loader.exec_module(DHM)

#: The upstream module that DECLARES the three knobs. The script mirrored by
#: `UPSTREAM_MIRROR` consumes them; the defaults live one file over, and a pin
#: that read only the script could not see a default change at all.
_DEFAULTS_MODULE = "librelane/steps/magic.py"


def _upstream(rel: str):
    """`rel` ('librelane/...') resolved on this host, or None.

    Both places are tried explicitly so a reader can see every one of them and
    none is a guess: an operator-staged root, then the installed package.
    """
    project, tail = rel.split("/", 1)
    env = os.environ.get("VIBEIC_LIBRELANE_ROOT")
    if env:
        cand = Path(env) / tail
        if cand.is_file():
            return cand
    try:
        import librelane  # type: ignore
    except Exception:
        return None
    cand = Path(librelane.__file__).parent / tail
    return cand if cand.is_file() else None


def _skip(rel: str):
    pytest.skip(
        f"upstream {rel} is not on this host: $VIBEIC_LIBRELANE_ROOT is unset "
        f"or does not carry it and `librelane` is not importable. The question "
        f"could not be put here; it is put in the container image that ships "
        f"the flow.")


def test_the_declaration_is_well_formed():
    """Host-independent, so this file is never entirely skipped."""
    m = DHM.UPSTREAM_MIRROR
    assert m["upstream"].endswith("lef.tcl")
    assert m["pinned_by"].split("::", 1)[0].rsplit("/", 1)[-1] == \
        Path(__file__).name


def test_upstream_lef_write_defaults_are_the_ones_this_module_bakes_in():
    """All three knobs default FALSE upstream, which is what this producer
    assumes when it writes `-hide`, omits `-pinonly`, and reads the views."""
    rel = _DEFAULTS_MODULE
    src = _upstream(rel)
    if src is None:
        _skip(rel)
    text = src.read_text(errors="replace")

    for var, why in (
        ("MAGIC_LEF_WRITE_USE_GDS",
         "this producer takes the read-views route, and the GDS-only route was "
         "measured to yield a LEF with zero pins"),
        ("MAGIC_WRITE_FULL_LEF",
         "this producer writes `-hide`, the abstract form"),
        ("MAGIC_WRITE_LEF_PINONLY",
         "this producer omits `-pinonly`"),
    ):
        m = re.search(
            r'"%s"\s*,\s*bool\s*,.*?default\s*=\s*(True|False)' % re.escape(var),
            text, re.S)
        assert m, (
            f"{src}: upstream no longer declares {var} as a bool with an "
            f"explicit default. {why} on the strength of that default.")
        assert m.group(1) == "False", (
            f"{src}: upstream's default for {var} is now {m.group(1)}, not "
            f"False. {why} — the assumption has moved and this producer has "
            f"not.")


def test_upstream_still_gates_hide_and_pinonly_on_those_two_flags():
    """The SHAPE, not only the defaults: `-hide` is the else-branch of the
    full-LEF flag and `-pinonly` is the then-branch of the pin-only flag. A
    producer that hard-codes the default of an inverted flag is wrong twice."""
    rel = DHM.UPSTREAM_MIRROR["upstream"]
    tcl = _upstream(rel)
    if tcl is None:
        _skip(rel)
    text = tcl.read_text(errors="replace")

    hide = re.search(
        r"if\s*\{\s*\$::env\(MAGIC_WRITE_FULL_LEF\)\s*\}.*?else\s*\{"
        r"(.*?)\}", text, re.S)
    assert hide and "-hide" in hide.group(1), (
        f"{tcl}: `-hide` is no longer the else-branch of MAGIC_WRITE_FULL_LEF. "
        f"This producer writes `-hide` whenever full-LEF is not requested, "
        f"which is only correct while that is upstream's structure.")

    pinonly = re.search(
        r"if\s*\{\s*\$::env\(MAGIC_WRITE_LEF_PINONLY\)\s*\}\s*\{(.*?)\}",
        text, re.S)
    assert pinonly and "-pinonly" in pinonly.group(1), (
        f"{tcl}: `-pinonly` is no longer the then-branch of "
        f"MAGIC_WRITE_LEF_PINONLY.")


def test_the_emitted_tcl_matches_the_defaults_it_claims():
    """Our side of the same invariant, so a divergence names which half moved.

    Runs everywhere: it reads only this repo.
    """
    default = DHM.build_lef_tcl("top", "a.gds", "b.def", "o.lef",
                                full_lef=False, pinonly=False)
    assert "-hide" in default and "-pinonly" not in default
    assert "def read b.def" in default, (
        "the read-views route is what supplies the PORTS; the GDS-only route "
        "was measured to yield an abstract with no pin at all")
    full = DHM.build_lef_tcl("top", "a.gds", "b.def", "o.lef",
                             full_lef=True, pinonly=True)
    assert "-hide" not in full and "-pinonly" in full
