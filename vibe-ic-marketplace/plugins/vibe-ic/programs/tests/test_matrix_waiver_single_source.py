"""The 63x8 matrix has ONE waiver registry, and every dimension reads it.

A waiver is a public, dated admission that one cell of the 504 is not enforced
and why. Its text is the only thing a reader has to judge whether the admission
is still justified. Two texts for one waiver — a central entry and a
module-local mirror, read as ``central or local`` — means the justification a
reader sees and the justification a maintainer edits can be different
documents, with nothing comparing them.

That is not hypothetical. Dimension 3 carried such a mirror until #527: its two
copies had drifted, one calling a set of matching ``.gds`` files "a stub written
by a throwaway seeding script" and the other calling them "SYMLINKS pointing
back at the design's own input layout", and ``or`` silently picked one. #530
then found the same structure in FOUR more modules holding 26 shadowed entries
between them — and dimension 6's two copies had ALSO already drifted, unnoticed,
because that module never compared them.

WHY THIS GUARD IS NAME-AGNOSTIC
===============================
The obvious guard is "no module defines ``_LOCAL_WAIVERS``". That guard would
have found dimension 5 and missed the other three: the mirrors were called
``LOCAL_WAIVERS``, ``_PENDING_WAIVERS`` and ``PENDING_WAIVERS``. A grep for the
one spelling is exactly how #530 came to report five shadowed waivers when
there were twenty-six. So this module asks what the objects ARE, not what they
are called.

WHY IT DOES NOT READ SOURCE TEXT
================================
Asserting on source text is how a test survives the mutation it exists to
catch: the string can be present while the code path is dead, or absent while
an equivalent construct is live. Both tests here run the real modules —
:func:`test_no_matrix_module_holds_its_own_waiver_table` inspects loaded module
attributes, and
:func:`test_no_cell_is_waived_without_the_central_registry` neutralises the
central lookups and asks the modules, through the uniform cell-state interface
they already expose, whether anything is still waived. A second source of
waivers survives that neutralisation; nothing else does.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from flow_matrix import flowref as F  # noqa: E402
from flow_matrix import waivers as W  # noqa: E402

#: The registry module is the ONE place a ``Waiver`` container is legitimate.
_REGISTRY_MODULE = W.__name__

#: Central lookups a dimension module could read. All of them are neutralised
#: together, so a module that reaches for a different one is not let through.
_CENTRAL_LOOKUPS: Tuple[str, ...] = (
    "waiver_for",
    "waivers_for_dim",
    "is_waived",
    "xfail_mark",
)


def _matrix_module_names() -> List[str]:
    """Every matrix module in this directory, discovered from the filesystem.

    Discovery is by filename so a NEW dimension module is covered the day it
    lands — a hardcoded list is a guard that silently stops growing. The
    ASSERTIONS below are on the imported objects, never on the files.
    """
    names = set()
    for pattern in ("test_matrix_*.py", "matrix_*.py"):
        for path in _TESTS_DIR.glob(pattern):
            if path.stem != Path(__file__).stem:
                names.add(path.stem)
    return sorted(names)


def _import_matrix_modules() -> Dict[str, object]:
    """Import every matrix module, failing loudly rather than skipping one.

    A module that cannot be imported is not evidence that it holds no mirror,
    so an ImportError fails the guard instead of shrinking its population.
    """
    mods = {}
    broken = {}
    for name in _matrix_module_names():
        try:
            mods[name] = importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - a broken tree, not a mirror
            broken[name] = f"{type(exc).__name__}: {exc}"
    assert not broken, (
        f"matrix module(s) could not be imported, so this guard could not "
        f"inspect them: {broken}"
    )
    assert mods, "no matrix modules were discovered — the guard is inspecting nothing"
    return mods


def _waiver_containers(module) -> Dict[str, int]:
    """Attributes of *module* that hold ``Waiver`` objects, by attribute name.

    Name-agnostic on purpose: it matches on the TYPE of the contained objects,
    so ``_LOCAL_WAIVERS``, ``LOCAL_WAIVERS``, ``PENDING_WAIVERS`` and any
    future spelling are all caught by the same rule.
    """
    found = {}
    for attr, value in vars(module).items():
        if isinstance(value, (tuple, list, set, frozenset)):
            items = list(value)
        elif isinstance(value, dict):
            items = list(value.values())
        else:
            continue
        n = sum(1 for item in items if isinstance(item, W.Waiver))
        if n:
            found[attr] = n
    return found


def test_no_matrix_module_holds_its_own_waiver_table():
    """Only the registry module may hold ``Waiver`` objects in a container.

    Inspects loaded module attributes, so it fires on any spelling of the
    mirror rather than on one name someone happened to grep for.
    """
    offenders = {}
    for name, module in _import_matrix_modules().items():
        if name == _REGISTRY_MODULE:
            continue
        tables = _waiver_containers(module)
        if tables:
            offenders[name] = tables
    assert not offenders, (
        f"module-local waiver table(s) found: {offenders}. A waiver is a public "
        f"admission and can have exactly one text; the readers resolve "
        f"`central or local`, so the local copy is inert the moment the central "
        f"entry exists and drifts from it unnoticed thereafter. Put the waiver "
        f"in flow_matrix/waivers.py and delete the local copy."
    )


def test_the_waiver_container_detector_actually_fires():
    """The detector must flag a mirror, or the guard above proves nothing.

    Feeds :func:`_waiver_containers` a module object carrying a mirror under a
    name no real module uses, in each container shape a mirror has historically
    taken. A detector that cannot fail is not a guard.

    The probe object is a REAL registry entry, taken from whichever dimension
    still has one — not from a hard-coded dimension. #530 pinned it to
    dimension 5; the 2026-07-28 convergence closed all five of that dimension's
    waivers by fixing the dependencies, and this test then failed on the
    absence of its own fixture rather than on the property it measures. Which
    dimension supplies the object is irrelevant to what is being tested (that
    the detector recognises a ``Waiver`` in a tuple, a dict and a list, and
    does not fire on a module that merely mentions the names).
    """
    real = W.WAIVERS
    assert real, (
        "the central registry is empty, so this test has no real Waiver to "
        "build its probe from and can no longer show the detector fires. If "
        "the matrix is genuinely waiver-free, construct the probe from a "
        "synthetic Waiver here in the same change."
    )
    probe = real[0]

    module = type(sys)("_probe_module_for_the_detector")
    module.NOT_A_KNOWN_MIRROR_NAME = (probe,)
    assert _waiver_containers(module) == {"NOT_A_KNOWN_MIRROR_NAME": 1}

    module = type(sys)("_probe_module_for_the_detector")
    module.some_dict = {probe.key: probe}
    assert _waiver_containers(module) == {"some_dict": 1}

    module = type(sys)("_probe_module_for_the_detector")
    module.some_list = [probe, probe]
    assert _waiver_containers(module) == {"some_list": 2}

    # And it must NOT fire on a module that merely mentions waivers.
    module = type(sys)("_probe_module_for_the_detector")
    module.unrelated = ("_LOCAL_WAIVERS", "PENDING_WAIVERS")
    module.also_unrelated = {"waiver": "a string, not a Waiver"}
    assert _waiver_containers(module) == {}


def _waived_cells() -> Dict[int, List[str]]:
    """Every cell each dimension module currently calls WAIVED, asked live.

    Uses ``matrix_cell_state``, the uniform interface the coverage meta-test
    already reads, so the answer comes from the module that owns the cell.
    """
    steps = F.step_ids()
    out = {}
    for name, module in _import_matrix_modules().items():
        dim = getattr(module, "DIM", None)
        state = getattr(module, "matrix_cell_state", None)
        if dim is None or not callable(state):
            continue
        out[dim] = [str(s) for s in steps if state(s) == "WAIVED"]
    return out


def test_no_cell_is_waived_without_the_central_registry(monkeypatch):
    """Neutralise the central lookups; nothing may still be waived.

    This is the behavioural form of "one registry". A module-local mirror is
    invisible while the central entry exists — ``central or local`` returns the
    central copy either way — so no assertion about the CURRENT verdicts can
    detect it. Taking the central answer away is what makes the second source
    observable: the mirror keeps answering, and this test reddens.

    The floor below is not decoration. If no cell were waived at all, the
    neutralised assertion would hold vacuously and this test would pass having
    measured nothing.
    """
    live = _waived_cells()
    live_total = sum(len(v) for v in live.values())
    assert live_total > 0, (
        "no cell is waived in any dimension, so neutralising the registry "
        "cannot demonstrate anything — this guard has gone vacuous"
    )

    for attr in _CENTRAL_LOOKUPS:
        assert hasattr(W, attr), (
            f"flow_matrix.waivers no longer exposes {attr!r}; this guard "
            f"neutralises a lookup that no longer exists and would pass "
            f"vacuously"
        )
    monkeypatch.setattr(W, "waiver_for", lambda step_id, dim: None)
    monkeypatch.setattr(W, "waivers_for_dim", lambda dim: ())
    monkeypatch.setattr(W, "is_waived", lambda step_id, dim: False)
    monkeypatch.setattr(W, "xfail_mark", lambda step_id, dim: None)
    monkeypatch.setattr(W, "WAIVERS", ())

    survivors = {d: cells for d, cells in _waived_cells().items() if cells}
    assert not survivors, (
        f"with the central registry neutralised these cells are STILL waived: "
        f"{survivors}. Their waiver text comes from somewhere other than "
        f"flow_matrix/waivers.py, which means one accepted gap has two "
        f"accounts and nothing reconciles them."
    )


def test_every_waived_cell_traces_to_a_registry_entry():
    """The waived cells and the registry name the same coordinates.

    The neutralisation test proves no EXTRA source exists. This proves the
    registry is actually the source being read, so the two together pin the
    lookup from both directions.
    """
    live = _waived_cells()
    from_modules = {(dim, cell) for dim, cells in live.items() for cell in cells}
    from_registry = {
        (w.dim, F.normalize_id(w.step_id))
        for w in W.WAIVERS
        if getattr(
            importlib.import_module(_module_for_dim(w.dim)), "matrix_cell_state"
        )(w.step_id) == "WAIVED"
    }
    assert from_modules == from_registry, (
        f"cells the modules report WAIVED {sorted(from_modules)} do not match "
        f"the registry entries that resolve to WAIVED {sorted(from_registry)}"
    )


def _module_for_dim(dim: int) -> str:
    """The dimension module owning *dim*, discovered by its own ``DIM``."""
    for name, module in _import_matrix_modules().items():
        if getattr(module, "DIM", None) == dim:
            return name
    raise AssertionError(f"no matrix module declares DIM == {dim}")
