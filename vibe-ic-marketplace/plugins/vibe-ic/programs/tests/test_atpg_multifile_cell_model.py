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


def test_single_path_cell_model_behaviour_is_unchanged() -> None:
    """The other direction of the control: single-path PDKs must not regress.

    This one PASSES BOTH BEFORE AND AFTER the fix, deliberately. It asserts the
    single-path CONTRACT (the model itself and its co-located primitives.v are
    named, and the combined output path is unchanged) and NOT the mechanism —
    `cp X out` and `cat X > out` are equivalent for one file, so pinning either
    spelling here would turn a control into a restatement of the diff."""
    for pdk in ("sky130", "gf180"):
        cm = F.PDK_CONFIG[pdk]["cell_model"]
        assert len(shlex.split(cm)) == 1, f"{pdk} is unexpectedly multi-file"
        eff, prep = F._cell_model_prep(cm)
        assert eff == f"/work/{F._COMBINED_CELL_MODEL}"
        assert f'"{cm}"' in prep
        assert f'"{str(Path(cm).parent)}/primitives.v"' in prep
        assert f'> "{eff}"' in prep, prep


def test_prep_snippet_still_creates_the_output_directory() -> None:
    """Guard the part of the contract the fix must not disturb."""
    eff, prep = F._cell_model_prep(_ihp_cell_model())
    assert eff == f"/work/{F._COMBINED_CELL_MODEL}"
    assert "mkdir -p" in prep


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
