"""The pin: the seal-ring generator contract, read from upstream.

`die_finishing_gen` drives the PDK's own seal-ring generator through what its
header calls upstream's interface "unchanged": four flags, and a named skip on
the same unset PDK-scoped variable. That is a contract with code this module
does not own, and it was written down once.

SKIPS BY NAME where upstream is not installed.
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
    "_die_fin_pin", PROGRAMS / "die_finishing_gen.py")
DF = importlib.util.module_from_spec(_spec)
sys.modules["_die_fin_pin"] = DF
_spec.loader.exec_module(DF)


def _upstream(rel: str):
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


def _sealring_body(text: str) -> str:
    i = text.find("class SealRing")
    assert i != -1, ("upstream no longer defines a SealRing step — the mirror "
                     "describes a shape that has moved.")
    j = text.find("\nclass ", i + 1)
    return text[i: j if j != -1 else len(text)]


def test_the_declaration_is_well_formed():
    m = DF.UPSTREAM_MIRROR
    assert m["upstream"].endswith("klayout.py")
    assert m["pinned_by"].split("::", 1)[0].rsplit("/", 1)[-1] == \
        Path(__file__).name


def test_upstream_sealring_contract_is_the_one_this_module_drives():
    """Four flags, and the variable whose absence is a named skip."""
    rel = DF.UPSTREAM_MIRROR["upstream"]
    src = _upstream(rel)
    if src is None:
        pytest.skip(
            f"upstream {rel} is not on this host: $VIBEIC_LIBRELANE_ROOT is "
            f"unset or does not carry it and `librelane` is not importable. "
            f"The question could not be put here; it is put in the container "
            f"image that ships the flow.")
    body = _sealring_body(src.read_text(errors="replace"))

    for flag in ("--input", "--output", "--die-width", "--die-height"):
        assert f'"{flag}"' in body, (
            f"{src}: upstream's seal-ring command no longer passes {flag}. "
            f"This module drives the generator with exactly these four flags; "
            f"a contract that changed is a divergence, not a detail.")

    assert DF._ENV_SCRIPT in body, (
        f"{src}: upstream no longer gates the step on {DF._ENV_SCRIPT}. This "
        f"module reports a NAMED skip on that same variable, which is only "
        f"the same skip while upstream keys on it too.")
    assert re.search(r"This step will be skipped", body), (
        f"{src}: upstream no longer SKIPS on the unset script variable. If it "
        f"now fails instead, a disclosed skip here is the wrong verdict.")


def test_upstream_second_path_still_exports_the_tool_search_path():
    """The header says both code paths are reproduced, "KLAYOUT_PATH
    included" — that export is what makes the technology definition load."""
    rel = DF.UPSTREAM_MIRROR["upstream"]
    src = _upstream(rel)
    if src is None:
        pytest.skip(f"upstream {rel} is not on this host — see the skip reason "
                    f"on the contract pin above.")
    body = _sealring_body(src.read_text(errors="replace"))
    assert "KLAYOUT_PATH" in body, (
        f"{src}: upstream's second seal-ring path no longer exports "
        f"KLAYOUT_PATH. This module reproduces that export; if upstream "
        f"dropped it, one of the two is now wrong.")


def test_upstream_generic_path_maps_die_area_indices_to_the_right_dimension():
    """The mapping this module relies on: index 2 is the WIDTH, index 3 the
    HEIGHT.

    Upstream declares the variable as the four-corner rectangle "x0 y0 x1 y1",
    so index 2 is an x and index 3 is a y. The generic path passes them that
    way round and this module mirrors it.

    THIS PIN IS SCOPED TO THE GENERIC PATH ON PURPOSE. Upstream's OTHER
    seal-ring path passes the same two indices to `width` and `height` in the
    OPPOSITE order — measured, and filed as a forked-tool finding rather than
    asserted here, because pinning it either way would mean this repo either
    blesses the transposition or reddens over a defect in a path it does not
    drive. On a square die the two are indistinguishable, which is why it has
    survived.
    """
    rel = DF.UPSTREAM_MIRROR["upstream"]
    src = _upstream(rel)
    if src is None:
        pytest.skip(f"upstream {rel} is not on this host — see the skip reason "
                    f"on the contract pin above.")
    body = _sealring_body(src.read_text(errors="replace"))
    generic = body[body.find("def run_generic"):body.find("def run_ihp")]
    assert generic, f"{src}: upstream no longer has a generic seal-ring path."

    w = re.search(r'"--die-width",\s*\n?\s*f"\{self\.config\[.DIE_AREA.\]\[(\d)\]',
                  generic)
    h = re.search(r'"--die-height",\s*\n?\s*f"\{self\.config\[.DIE_AREA.\]\[(\d)\]',
                  generic)
    assert w and h, (
        f"{src}: could not read which DIE_AREA index the generic path passes "
        f"as width and as height. The mapping is what this module mirrors, so "
        f"an unreadable one is a finding, not a pass.")
    assert (w.group(1), h.group(1)) == ("2", "3"), (
        f"{src}: upstream's generic path now passes DIE_AREA[{w.group(1)}] as "
        f"the width and DIE_AREA[{h.group(1)}] as the height. DIE_AREA is "
        f'declared "x0 y0 x1 y1", so width is index 2 and height is index 3. '
        f"One of upstream and this module has moved.")
