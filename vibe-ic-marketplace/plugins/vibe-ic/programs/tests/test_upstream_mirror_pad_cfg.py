"""The pin: OUR per-side pad arithmetic against UPSTREAM's, read from upstream.

`_pad_ring.UPSTREAM_MIRROR` declares that this module mirrors upstream's
`pad_cfg.tcl` side arithmetic. The repo already pins OUR half — a vertical side
must sum the master's WIDTH, not its height. Nothing pinned THEIRS, so the
statement "upstream does it this way" was a claim in a docstring, true when it
was written and unchecked from then on. This asks upstream.

WHEN UPSTREAM IS NOT ON THE HOST the test SKIPS BY NAME. That is not the same
as passing: a skip says "the question could not be put here", and the reason
names the missing input, so a run on a host without the toolchain cannot read
as a run that checked.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

from not_verified_tier import skip_not_verified  # noqa: E402
_spec = importlib.util.spec_from_file_location("_pad_ring_pin",
                                               PROGRAMS / "_pad_ring.py")
PR = importlib.util.module_from_spec(_spec)
sys.modules["_pad_ring_pin"] = PR
_spec.loader.exec_module(PR)


def _upstream_tcl() -> Path:
    """The declared upstream artefact on this host, or None.

    Resolution order, all of it explicit so a reader can see every place that
    was tried and none of them is a guess:
      1. $VIBEIC_LIBRELANE_ROOT, for a host that stages upstream itself;
      2. the installed `librelane` package, if importable.
    """
    rel = PR.UPSTREAM_MIRROR["upstream"]
    tail = rel.split("/", 1)[1]              # drop the leading `librelane/`
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


def test_the_declaration_is_well_formed():
    """Runs everywhere: the declaration itself is host-independent."""
    m = PR.UPSTREAM_MIRROR
    assert m["upstream"].endswith(".tcl")
    assert "getHeight" not in m["mirrors"] or "no getHeight" in m["mirrors"]
    assert m["pinned_by"].startswith("tests/") and "::" in m["pinned_by"]
    # the pin names THIS file, so the declaration cannot drift off its own pin
    named_file = m["pinned_by"].split("::", 1)[0].rsplit("/", 1)[-1]
    assert named_file == Path(__file__).name


def test_upstream_side_arithmetic_measures_the_master_width():
    """Upstream's per-side arithmetic steps and sums by the master's WIDTH, and
    the master's HEIGHT reaches no arithmetic at all.

    This is the invariant whose silent violation summed 19 x 350 = 6650 um
    against a 1500 um side. It is asserted against upstream's own text.

    THE FIRST VERSION OF THIS TEST ASSERTED THE WRONG THING AND UPSTREAM SAID
    SO. It asserted that `getMaster] getHeight` appears nowhere in the side
    loop — the sentence the mirror was documented with. Run against the real
    file, that FAILED: upstream reads the master's height TWICE inside the
    loop, at both places it reads the width. What it does with it is the whole
    point, and it is the thing the prose sentence flattened:

        set width  [expr [[$inst getMaster] getWidth] / $units]
        set height [expr [[$inst getMaster] getHeight] / $units]
        puts "$master_name: $width $height"
        incr sum_of_cell_widths $width
        ...
        set cur_pos [expr $cur_pos + $space_between_pads_min_filler + $width]

    `$height` is read, PRINTED, and never used in arithmetic. So the conclusion
    the mirror rests on is sound and the evidence it was written with was not,
    and an unused local named `height` sitting one line under the used `width`
    is exactly the shape that invited the confusion in the first place. The pin
    asserts what is true.
    """
    tcl = _upstream_tcl()
    if tcl is None:
        skip_not_verified(
            f"upstream {PR.UPSTREAM_MIRROR['upstream']} is not on this host: "
            f"$VIBEIC_LIBRELANE_ROOT is unset or does not carry it and "
            f"`librelane` is not importable. The question could not be put "
            f"here; it is put in the container image that ships the flow.",
            "set $VIBEIC_LIBRELANE_ROOT to a LibreLane checkout that carries it, or run in the container image that ships the flow")
    text = tcl.read_text(errors="replace")

    # The side loop is where the per-side arithmetic lives. Bound the search to
    # it so a height read elsewhere (the CORNER SITE height, which legitimately
    # is the into-die dimension of a vertical side) is not read as a finding
    # about the pad master.
    start = text.find("foreach side $sides")
    assert start != -1, (
        f"{tcl}: upstream no longer has a `foreach side $sides` loop — the "
        f"mirror declaration in _pad_ring.UPSTREAM_MIRROR describes a shape "
        f"that has moved, and the divergence must be re-read rather than "
        f"assumed away.")
    body = text[start:]

    # 1. the FIT SUM accumulates the width
    assert re.search(r"incr\s+sum_of_cell_widths\s+\$width", body), (
        f"{tcl}: upstream's per-side fit sum no longer accumulates `$width`. "
        f"Ours sums the master width on all four sides on the strength of "
        f"upstream doing the same.")

    # 2. the ALONG-THE-ROW STEP advances by the width
    assert re.search(r"set\s+cur_pos\s+\[expr[^\]]*\+\s*\$width\s*\]", body), (
        f"{tcl}: upstream's along-the-row step no longer advances by `$width`.")

    # 3. and the master's HEIGHT reaches no arithmetic — every use of the
    #    `$height` local is a diagnostic print.
    arithmetic_height = [
        ln.strip() for ln in body.splitlines()
        if re.search(r"(?<![a-z_])\$height\b", ln)
        and not ln.lstrip().startswith("puts")
        and not re.match(r"\s*set\s+height\s", ln)
    ]
    assert arithmetic_height == [], (
        f"{tcl}: upstream's side loop now uses the pad master's HEIGHT in "
        f"arithmetic: {arithmetic_height}. Ours takes the along-the-row extent "
        f"from the WIDTH on all four sides; one of the two changed and the "
        f"mirror is broken.")


def test_upstream_still_declares_the_variables_this_module_borrows_verbatim():
    """The contract says the variable names are upstream's, verbatim, so that
    one config drives both. That is checkable against upstream's own file."""
    tcl = _upstream_tcl()
    if tcl is None:
        pytest.skip(
            f"upstream {PR.UPSTREAM_MIRROR['upstream']} is not on this host — "
            f"see the skip reason on the arithmetic pin above.")
    text = tcl.read_text(errors="replace")
    borrowed = [v for v in PR.REQUIRED_VARS if v.startswith("PAD_")]
    missing = [v for v in borrowed if v not in text]
    assert missing == [], (
        f"{tcl}: this module declares it borrows upstream's variable names "
        f"verbatim, and upstream's own pad config no longer mentions "
        f"{missing}. A config that drives one flow no longer drives the other.")
