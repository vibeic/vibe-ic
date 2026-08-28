"""#602 — the ASAP7 GDS stack is a literal, and nothing reconciled it.

`asap7_finfet_lvs.py` states the routing stack as numbers:

    "metals": [(19, 0), (20, 0), (30, 0), ... (90, 0)],   # M1..M9
    "vias":   [(21, 0), (25, 0), (35, 0), ... (85, 0)],   # V1..V8

Its own comment names where they come from — *"the official ASAP7 GDS layers
(libs.tech/klayout/lvs/asap7.lyt LEF/DEF map)"* — and nothing checked the
literal against that file. A PDK bump that renumbers or drops a layer leaves the
extraction running over a set the library no longer has, and the shape of that
failure is the one this repo keeps finding: absent layers contribute nothing,
the extraction still completes, and an LVS over a SUBSET of the interconnect is
indistinguishable from an LVS over all of it.

Filed while reviewing vibeic-eda#39 (ORFS advanced 6159 commits). That bump was
safe — its tech-LEF delta is +6 IMPLANT layers, additive, and the byte-identical
routed DEF corroborates it — which is why this is a reconciliation and not a
correction. Measured against the released `0.2.52`:

    map M1..M9   [(19,0),(20,0),(30,0),(40,0),(50,0),(60,0),(70,0),(80,0),(90,0)]
    literal      identical
    map V1..V8   [(21,0),(25,0),(35,0),(45,0),(55,0),(65,0),(75,0),(85,0)]
    literal      identical

18 declarations, all agreeing. The point is not the agreement; it is that until
now nobody could have found out.

DERIVED, NOT RESTATED. The expected values come from parsing the shipped `.lyt`
at test time. Writing them into this file as a second literal would produce two
copies to keep in step and check neither against the library.

IMAGE-GATED, and SKIPPED rather than passed when no image is present: "I could
not look" and "I looked and they agree" are different claims.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import subprocess
import sys

import pytest
# vibe-ic#1128 — these skips mean A VERIFICATION DID NOT HAPPEN, not that
# one passed. Declared through `not_verified_tier` so the run's roll-up
# cannot count them under `passed`; see that module's docstring.
from not_verified_tier import skip_not_verified  # noqa: E402

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402
PULL_REMEDY = 'docker pull ghcr.io/vibeic/vibeic-eda:latest'  # the repo stores no version to cat
RUN_REMEDY = 'bash tools/vibeic-eda/restart-eda.sh'

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]

#: Where the PDK states the mapping. Named by `asap7_finfet_lvs`'s own comment.
_LYT = "/foss/pdks/asap7/libs.tech/klayout/lvs/asap7.lyt"
#: `M3='30/0` — the map's own form.
_DECL = re.compile(r"\b(M\d+|V\d+)='(\d+)/(\d+)")


def _load():
    spec = importlib.util.spec_from_file_location(
        "asap7_finfet_lvs", _PROGRAMS / "asap7_finfet_lvs.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["asap7_finfet_lvs"] = mod
    spec.loader.exec_module(mod)
    return mod


def _image():
    """The image this host holds, BY DIGEST — asked, not remembered.

    This used to walk up for `tools/vibeic-eda/VERSION`, vibeic-eda's version
    number stored in the vibe-ic repo, which made every image release need a PR
    here. `_eda_image.judged_image()` honours the same `VIBEIC_EDA_IMAGE`
    override and answers None the same way when there is nothing to look at.
    """
    sys.path.insert(0, str(_PROGRAMS))
    import _eda_image as _img
    return _img.judged_image().ref


def _shipped_map():
    """{name: (layer, datatype)} read from the image, or None if unreachable."""
    img = _image()
    if not img:
        return None
    if subprocess.run(["docker", "image", "inspect", img],
                      capture_output=True, text=True).returncode != 0:
        return None
    r = _pr.run(["docker", "run", "--rm", "--entrypoint", "cat", img, _LYT],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout:
        return None
    return {n: (int(l), int(d)) for n, l, d in _DECL.findall(r.stdout)}


@pytest.fixture(scope="module")
def shipped():
    m = _shipped_map()
    if not m:
        skip_not_verified(
            f"{_LYT} not reachable — this half was NOT checked",
            PULL_REMEDY)
    return m


# ── the reconciliation ───────────────────────────────────────────────────────
def test_the_metal_stack_matches_the_shipped_map(shipped):
    M = _load()
    expected = [shipped[f"M{i}"] for i in range(1, 10) if f"M{i}" in shipped]
    assert len(expected) == 9, f"the map declares {len(expected)} of M1..M9"
    assert M.ASAP7_DESIGN_LAYERS["metals"] == expected, (
        "the hard-coded metal stack no longer matches "
        f"{_LYT}. Extraction would run over a layer set the library does not "
        "have, and absent layers contribute nothing rather than failing.")


def test_the_via_stack_matches_the_shipped_map(shipped):
    M = _load()
    expected = [shipped[f"V{i}"] for i in range(1, 9) if f"V{i}" in shipped]
    assert len(expected) == 8, f"the map declares {len(expected)} of V1..V8"
    assert M.ASAP7_DESIGN_LAYERS["vias"] == expected


def test_m1_agrees_with_the_base_layer_table_too(shipped):
    """`ASAP7_LAYERS['m1']` and `ASAP7_DESIGN_LAYERS['metals'][0]` are two
    statements of one fact; they must not drift apart from each other either."""
    M = _load()
    assert M.ASAP7_LAYERS["m1"] == shipped["M1"]
    assert M.ASAP7_DESIGN_LAYERS["metals"][0] == shipped["M1"]


# ── the reconciliation must be capable of failing ────────────────────────────
def test_a_renumbered_map_would_be_caught(shipped):
    """Load-bearing. Every assertion above passes today, so without this the
    file could be comparing something to itself and nobody would know."""
    M = _load()
    tampered = dict(shipped)
    tampered["M5"] = (999, 0)
    expected = [tampered[f"M{i}"] for i in range(1, 10)]
    assert M.ASAP7_DESIGN_LAYERS["metals"] != expected, (
        "a renumbered layer produced no difference — the comparison is not "
        "reading what it thinks it is")


def test_a_dropped_layer_would_be_caught(shipped):
    """The subset case, which is the dangerous one: fewer layers extract
    cleanly and silently cover less interconnect."""
    short = {k: v for k, v in shipped.items() if k != "M9"}
    expected = [short[f"M{i}"] for i in range(1, 10) if f"M{i}" in short]
    assert len(expected) == 8
    M = _load()
    assert M.ASAP7_DESIGN_LAYERS["metals"] != expected


def test_the_declaration_pattern_actually_matches_something(shipped):
    """If the `.lyt` format changes, `_DECL` finds nothing, `shipped` is empty
    and every assertion above passes vacuously. This is the guard against
    that — the same shape the tests are protecting against, one level up."""
    assert len(shipped) >= 17, (
        f"only {len(shipped)} declarations parsed from the map; the format "
        f"likely changed and the reconciliation is comparing against almost "
        f"nothing")
