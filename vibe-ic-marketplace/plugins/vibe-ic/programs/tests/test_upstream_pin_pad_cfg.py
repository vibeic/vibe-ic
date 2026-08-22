"""The upstream HALF of the along-the-row pin.

WHY THIS FILE EXISTS
====================
This plugin re-derives, in Python, how much of a side one placed pad consumes.
Upstream computes the same quantity in TCL. Ours drifted: it took the extent
from the ORIENTED footprint, so a vertical side summed the master's HEIGHT --
19 x 350 = 6650 um against a 1500 um side, a 4.4x error that surfaced only as
an unrelated refusal about something else, long after it was introduced.

OUR half of that invariant is already pinned, behaviourally, by
``test_pad_ring.py::test_the_spacing_is_upstreams_arithmetic``: the fixture's
pad master is 75 x 350 and each side is 1_280_000 DEF units, so four pads
summed by WIDTH fit with 196_000-unit gaps and four summed by HEIGHT
(4 x 350_000 = 1_400_000) do not fit at all. That test goes red the moment the
extent goes back to the oriented footprint.

THEIRS WAS NOT PINNED BY ANYTHING. The claim "upstream measures the master's
width in both places" lived in a comment -- prose a human reads, that no
machine ever opens -- and the register carried the entry as a ``known_gap``
for exactly that reason. This file closes that half.

WHAT IT ASSERTS ABOUT UPSTREAM
==============================
1. the file is the one the register snapshotted, by sha256;
2. BOTH places that measure a cell along the row read
   ``[[$inst getMaster] getWidth]``;
3. the master's HEIGHT never enters arithmetic.

Point 3 is the one worth stating carefully, because a raw count of
``getHeight`` in that file is FOUR and reads as a flat contradiction of the
claim. Two of the four are site dimensions, not cell measurements. The other
two are ``set height [expr [[$inst getMaster] getHeight] / $units]``, once in
each measuring block -- and MEASURED, the resulting ``$height`` is used in
exactly one place in the whole file: a ``puts`` diagnostic. In the second block
it is computed and never used at all. So the height is read and discarded, and
the arithmetic is width-only, which is what our Python must match.

WHEN THE DISTRIBUTION IS NOT REACHABLE this SKIPS and names the missing input.
It does not pass. A pin that turns green when it cannot see the thing it pins
is the failure mode the register exists to prevent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
REGISTER = PROGRAMS / "upstream_contract_parity.json"
ENTRY_ID = "pad_ring.along_the_row_extent"

#: Where the distribution is rooted. The shipped image installs librelane under
#: dist-packages; a caller may point elsewhere.
ENV_ROOT = "VIBEIC_UPSTREAM_ROOT"
FALLBACKS = ("/usr/local/lib/python3.12/dist-packages",
             "/usr/lib/python3/dist-packages")


def _entry() -> dict:
    doc = json.loads(REGISTER.read_text(encoding="utf-8"))
    for e in doc["entries"]:
        if e.get("id") == ENTRY_ID:
            return e
    raise AssertionError(f"{ENTRY_ID} is not in the register")


def _upstream_text() -> tuple[str, Path]:
    rel = _entry()["upstream"]["file"]
    roots = [os.environ[ENV_ROOT]] if os.environ.get(ENV_ROOT) else []
    roots += list(FALLBACKS)
    for r in roots:
        p = Path(r) / rel
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace"), p
    pytest.skip(
        f"upstream {rel} is not readable under any of {roots}. Set "
        f"{ENV_ROOT} to a distribution root to run this pin. NOT a pass: the "
        f"upstream half of this invariant was not checked.")


#: `set width [expr [[$inst getMaster] getWidth] / $units]`
_WIDTH_MEASURE = re.compile(
    r"set\s+width\s+\[expr\s+\[\[\$inst\s+getMaster\]\s+getWidth\]")
#: `set height [expr [[$inst getMaster] getHeight] / $units]`
_HEIGHT_MEASURE = re.compile(
    r"set\s+height\s+\[expr\s+\[\[\$inst\s+getMaster\]\s+getHeight\]")


def test_the_file_is_the_one_the_register_snapshotted():
    text, path = _upstream_text()
    recorded = _entry()["snapshot"]["file_sha256"]
    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert actual == recorded, (
        f"{path} has changed since the register snapshotted it. Recorded "
        f"{recorded[:12]}, read {actual[:12]}. Every assertion below describes "
        f"the recorded file; re-measure the entry before trusting them.")


def test_both_along_the_row_measurements_read_the_masters_width():
    text, path = _upstream_text()
    widths = _WIDTH_MEASURE.findall(text)
    assert len(widths) == 2, (
        f"{path}: expected the two cell measurements to read getWidth; found "
        f"{len(widths)}. Upstream measures a cell in exactly two places -- the "
        f"fit sum and the along-the-row step -- and our Python mirrors both.")


def test_the_fit_sum_and_the_row_step_both_accumulate_the_width():
    text, path = _upstream_text()
    assert "incr sum_of_cell_widths $width" in text, (
        f"{path}: the fit sum no longer accumulates $width.")
    assert re.search(r"set\s+cur_pos\s+\[expr\s+\$cur_pos\s+\+\s+"
                     r"\$space_between_pads_min_filler\s+\+\s+\$width\]",
                     text), (
        f"{path}: the along-the-row step no longer advances by $width.")


def test_the_masters_height_is_read_and_then_never_used_in_arithmetic():
    """The claim the raw `getHeight` count appears to contradict."""
    text, path = _upstream_text()
    assert len(_HEIGHT_MEASURE.findall(text)) == 2, (
        f"{path}: expected the master's height to be measured twice.")

    uses = [ln.strip() for ln in text.splitlines()
            if "$height" in ln and not _HEIGHT_MEASURE.search(ln)]
    assert uses == ['puts "$master_name: $width $height"'], (
        f"{path}: the master's height reaches something other than the "
        f"diagnostic line. It is read and discarded upstream, which is why "
        f"our along-the-row extent is width-only on all four sides. Uses "
        f"found: {uses}")
