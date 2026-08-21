#!/usr/bin/env python3
"""A MULTI-FILE cell model must be concatenated, not quoted as one filename.

THE DEFECT
==========
`PDK_CONFIG["ihp-sg13g2"]["cell_model"]` is TWO space-separated paths, and the
config's own comment says why: `sg13g2_udp.v` "holds the UDP primitives the
stdcell models reference and must be read alongside `sg13g2_stdcell.v`".

`_cell_model_prep` treated the whole string as ONE path. It therefore

  * computed `os.path.dirname(<pathA> <pathB>)` — a nonsense primitives.v
    sibling, and
  * emitted `cp "<pathA> <pathB>" "<combined>"` — one quoted argument naming
    no file on disk.

MEASURED ORGANICALLY on spm x ihp-sg13g2 (plugin 1.6.71, image
sha256:4182c63b10d1), the container answered

    cp: cannot stat '.../sg13g2_udp.v .../sg13g2_stdcell.v':
        No such file or directory

so no combined cell model was written, `fault atpg` had nothing to elaborate
against, and the run reported `faults_total=0` -> `stuck-at coverage=0.00%`.
With the fix, the SAME netlist/PDK/image reported `faults_total=1000`,
`faults_covered=904` -> `90.40%`, `atpg_exit=0`. A tooling gap that reads
exactly like an untestable design.

WHY THESE ASSERTIONS FAIL WITHOUT THE FIX
=========================================
`test_multifile_cell_model_concatenates_every_component` fails on the
pre-fix code because the emitted snippet contains `cp "<A> <B>"` (both paths
inside ONE pair of quotes) and never mentions the second path as its own
argument.

`test_single_path_cell_model_behaviour_is_unchanged` is the OTHER direction:
a single-path PDK must keep working. It guards against "fix the bus case,
break the scalar case" — the shape that made the original defect invisible.

`test_no_component_path_is_ever_double_quoted_into_one_argument` is the
rubber-stamp guard: it is not satisfied by merely MENTIONING both paths
somewhere, which a naive `cell_model.replace(" ", '" "')` would also do
while still leaving `os.path.dirname` pointed at garbage.
"""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import fault_atpg_run as F  # noqa: E402


def _ihp_cell_model() -> str:
    return F.PDK_CONFIG["ihp-sg13g2"]["cell_model"]


def test_the_ihp_config_really_is_multi_file() -> None:
    """Anchor the premise. If this ever becomes one path the rest is moot,
    and the test should say so out loud rather than silently pass."""
    parts = shlex.split(_ihp_cell_model())
    assert len(parts) == 2, f"expected a 2-file cell model, got {parts!r}"
    assert all(p.endswith(".v") for p in parts), parts


def test_multifile_cell_model_concatenates_every_component() -> None:
    cm = _ihp_cell_model()
    parts = shlex.split(cm)
    _eff, prep = F._cell_model_prep(cm)

    # Every component must appear as its OWN quoted shell argument.
    for p in parts:
        assert f'"{p}"' in prep, f"component not passed as its own argument: {p}"

    # And the pre-fix shape must be gone: the two paths must never sit inside
    # a single pair of quotes.
    assert f'"{cm}"' not in prep, (
        "both paths are still quoted as ONE argument — this is the defect")
    assert "cp " not in prep, (
        "a multi-file model cannot be copied; it must be concatenated")


def test_primitives_sibling_resolves_against_the_first_component() -> None:
    """`os.path.dirname` must run on a real path, not on the joined string."""
    cm = _ihp_cell_model()
    first_dir = str(Path(shlex.split(cm)[0]).parent)
    _eff, prep = F._cell_model_prep(cm)
    assert f'"{first_dir}/primitives.v"' in prep, prep
    # The joined-string dirname the pre-fix code computed must not appear.
    assert " ".join(shlex.split(cm)) not in prep.replace('" "', "\x00"), prep


def test_no_component_path_is_ever_double_quoted_into_one_argument() -> None:
    """Rubber-stamp guard: mentioning both paths is not enough — neither may
    be embedded in a multi-path quoted token."""
    cm = _ihp_cell_model()
    _eff, prep = F._cell_model_prep(cm)
    for token in prep.split('"'):
        # A quoted token that contains a space AND two `.v` names is the bug.
        if token.count(".v") >= 2 and " " in token:
            raise AssertionError(
                f"two model files share one quoted argument: {token!r}")


def test_every_pdk_cell_model_gets_its_primitives_exactly_once() -> None:
    """The invariant this control is really about: whatever the config spells,
    the combined model must contain the library's UDP primitives, and must
    contain them EXACTLY ONCE.

    It used to assert `len(split(cm)) == 1` for sky130/gf180 — i.e. it pinned
    the SPELLING (single-path) rather than the property. v1.8.43 had to make
    sky130 name `primitives.v` explicitly, because Step 29's consumer
    (`pdk_cell_models.container_model_paths`) has no implicit co-located-
    primitives prepend and so handed iverilog a model whose UDPs are undefined:
    `67 error(s) during elaboration`, `sky130_fd_sc_hd__udp_dff$P_pp$PG$N
    referenced 64 times`, and canonical Step 29 MISSING on every sky130 run.
    Pinning the spelling would have blocked the fix while asserting nothing
    about correctness; pinning the property catches both the missing-primitives
    bug AND the duplicate-primitives bug the explicit spelling could cause."""
    for pdk in F.PDK_CONFIG:
        cm = F.PDK_CONFIG[pdk].get("cell_model")
        if not cm:
            continue
        parts = shlex.split(cm)
        eff, prep = F._cell_model_prep(cm)
        assert eff == f"/work/{F._COMBINED_CELL_MODEL}"
        assert f'> "{eff}"' in prep or f'cp ' in prep, prep
        for part in parts:
            assert f'"{part}"' in prep, f"{pdk}: {part} not in prep"
        # The UDP primitives must reach the combined model EXACTLY ONCE.
        # Two legal spellings, and the emitted snippet must match the one in use:
        #   (a) the config NAMES its primitives file  -> no implicit prepend, or
        #       the executed `cat` would list it twice and redefine every UDP;
        #   (b) the config does NOT name it           -> the implicit
        #       `if [ -f <co-located primitives.v> ]` prepend must be present.
        # NOTE this asserts on the BRANCH STRUCTURE, not on a substring count:
        # the snippet legitimately names each part in BOTH the then- and
        # else-branch, and only one branch ever runs.
        prim = f"{Path(parts[0]).parent}/primitives.v"
        prim_named = any(os.path.normpath(x) == os.path.normpath(prim)
                         for x in parts)
        udp_named = any(Path(x).name in ("primitives.v", "sg13g2_udp.v")
                        for x in parts)
        if prim_named:
            assert f'if [ -f "{prim}"' not in prep, (
                f"{pdk}: primitives.v is named explicitly AND prepended "
                f"implicitly — the combined model would redefine every UDP")
        else:
            assert udp_named or f'if [ -f "{prim}"' in prep, (
                f"{pdk}: no primitives source at all")


def test_prep_is_idempotent_when_primitives_is_named_explicitly() -> None:
    """v1.8.43 — a config that names its own primitives.v must NOT also get the
    implicit co-located prepend: the combined model would redefine every UDP and
    iverilog rejects it. Constructed from the real sky130 entry."""
    cm = F.PDK_CONFIG["sky130"]["cell_model"]
    parts = shlex.split(cm)
    assert any(Path(p).name == "primitives.v" for p in parts), cm
    _eff, prep = F._cell_model_prep(cm)
    assert "if [ -f " not in prep, (
        "the implicit prepend branch must be gone when primitives.v is explicit")
    # and the executed command lists each configured file once, in order
    assert prep.count('"' + parts[0] + '"') == 1, prep
    assert prep.index(parts[0]) < prep.index(parts[1]), prep


def test_prep_snippet_still_creates_the_output_directory() -> None:
    """Guard the part of the contract the fix must not disturb."""
    eff, prep = F._cell_model_prep(_ihp_cell_model())
    assert eff == f"/work/{F._COMBINED_CELL_MODEL}"
    assert "mkdir -p" in prep


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
