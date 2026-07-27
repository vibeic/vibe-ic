"""test_matrix_63x8_coverage.py — the meta-test that makes "full coverage" a
CLAIM THAT CAN BE FALSIFIED rather than an assertion in a commit message.

    63 flow steps x 8 audit dimensions = 504 cells.
    Every cell must be in exactly one of ENFORCED / WAIVED / NA.
    No cell may be missing. No cell may be counted twice.
    A cell with no test is NOT covered, and this file is what says so.

====================================================================
WHY THIS FILE EXISTS AT ALL
====================================================================
The eight dimension modules each report their own census, and each of those
censuses is honest. But eight self-reports do not compose into a coverage
claim: nothing was checking that the eight together *cover the grid*, that a
module's self-reported "63 cells" are actually 63 DISTINCT pytest items that
pytest will really run, or that the 504 tracks the flow yaml rather than a
number someone typed. Every one of those is a place where "full coverage" could
be true of the paperwork and false of the repository — which is the exact
substitution this whole campaign was opened to remove.

====================================================================
HOW EACH PROPERTY IS MEASURED (all live, none read from a table)
====================================================================
1. **The 504 is COMPUTED, never written down.**
   ``EXPECTED_CELLS == len(flowref.step_ids()) * len(DIMENSIONS)``. Add a 64th
   step to ``flow/phase1_phase2_phase3.yaml`` and this file demands 512 cells
   and goes red the same minute, because the eight modules will emit 63 each.
   That is the whole point: coverage must break when the flow grows, or it rots
   in silence.

2. **The test ids are collected by PYTEST ITSELF, in a subprocess.**
   :func:`collect_items` runs
   ``python3 -m pytest <the eight modules> --collect-only`` with a small plugin
   that dumps every collected item's nodeid, function name, parametrize id and
   markers to JSON. Nothing here re-implements parametrization or re-derives
   what "would" be collected: if pytest cannot collect a cell, the cell is not
   covered, and this file reports it. A dimension module that fails to import
   produces an empty census and reddens here rather than silently contributing
   zero cells to an otherwise-green suite.

3. **The state of a cell is answered by the module that OWNS it.**
   Each dimension module exposes ``matrix_cell_state(step_id)`` and
   ``matrix_na_precondition(step_id)``, both re-derived live from the tree on
   every call. This file deliberately does NOT form its own opinion about, say,
   whether step 40 is dormant — a second opinion about a cell it does not own
   would be exactly the adjacent measurement the campaign removes. What it does
   instead is CROSS-CHECK the module's answer against two independent sources:

     * the central waiver registry (``matrix_63x8.waivers.WAIVERS``), and
     * the ``xfail`` markers pytest actually collected.

   All three must agree, in both directions. A module that called a cell
   ENFORCED while pytest collected a strict-xfail for it, or a waiver in the
   registry that no collected item consumes, reddens here.

4. **A WAIVED cell must be a strict xfail with a specific, evidence-backed
   reason.** ``waivers.validate()`` is run on every one (length floors, the
   forbidden-placeholder list, the step must still exist in the yaml), AND the
   collected marker must carry ``strict=True``. ``strict`` is the anti-rot
   mechanism: when the underlying gap is fixed the cell XPASSes and the suite
   goes red, forcing the waiver's deletion.

5. **An NA cell must assert a LIVE precondition.** Three things are checked:
   the module returns a non-empty precondition string for it *right now*; no
   ``skip`` / ``skipif`` marker was collected for the item; and the cell test
   function's AST contains no call to ``pytest.skip`` anywhere. An NA that
   unconditionally skips is silent absence wearing a hat, and it is refused
   here structurally rather than by convention.

====================================================================
WHAT THIS FILE DOES *NOT* CLAIM
====================================================================
Stated plainly, because a green meta-test is the single most over-readable
artefact in this campaign.

  * It proves each of the 504 cells has a real, collected, non-skipping pytest
    item in a known state. It does **not** prove that item's predicate is
    strong. Predicate strength is each dimension module's own problem and is
    documented in that module's KNOWN GAP section; several are narrower than
    their name suggests (dimension 8's 61 ENFORCED cells run against a
    SUBSTITUTED gate; dimension 3's seven externally-attested cells fall back to
    a committed manifest on a host without the campaign's run trees; dimension
    6's legs L1 and L2 are inert for most steps and are carried by L1b/L3).
  * ``ENFORCED`` here means "the module says this cell's live predicate runs and
    passes". It does not mean the predicate would catch every defect of that
    kind. No count in this file should ever be quoted as "504 defects would be
    caught".
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from matrix_63x8 import flowref as F
from matrix_63x8 import waivers as W
from matrix_63x8.cells import DIMENSIONS, DIMENSION_NAMES

TESTS_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = F.PLUGIN_ROOT

#: The eight dimension modules, DISCOVERED not listed. A ninth appearing, or
#: one going missing, changes this set and reddens the census below.
DIMENSION_MODULE_GLOB = "test_matrix_d[1-8]_*.py"

#: A cell test's parametrize id is exactly ``step<flow step id>``. Anything with
#: a suffix (dimension 8's ``step8-out0`` per-entry sweep) is a finer-grained
#: probe, not a cell, and is not counted as one.
_CELL_ID_RE = re.compile(r"^step(.+)$")

VALID_STATES = ("ENFORCED", "WAIVED", "NA")

#: ``(steps, dimensions, cells)`` as MEASURED on 2026-07-27.
#:
#: The 504 below is never USED as an input — every assertion in this file
#: computes the grid from ``len(flowref.step_ids()) * len(DIMENSIONS)``. This
#: triple exists solely as the review gate: the eight dimension modules read the
#: yaml live, so a 64th step would be picked up by all of them and the grid
#: would grow to 512 with the census still partitioning tidily. That is exactly
#: the silent shape to refuse. A new step means eight new cells whose predicates
#: nobody has looked at, so the count change must redden HERE, by name, and be
#: acknowledged in the same commit that adds the step.
GRID_AS_MEASURED: Tuple[int, int, int] = (63, 8, 504)

#: The flow's step ids, in declaration order, as measured 2026-07-27. Pinned
#: alongside the count so a rename or an add-plus-remove — which leaves the
#: count at 63 — is caught too.
STEP_IDS_AS_MEASURED: Tuple[str, ...] = (
    'D1', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', 'FS1',
    'DT1', 'DT2', 'DT3', '12', '13', 'A1', 'A2', 'A3', 'A4', 'A5', 'A7',
    'A8', 'A9', '14', '15', '16', '17', '18', '19', '20', '21', '22', '23',
    '24', '25', '26', '27', '28', '29', '30', '31', '32', '33', '34', '35',
    '36', '37', '38', '39', 'A6', 'M1', 'M2', 'M3', 'M4', '40', '41', '42',
    '43', '44', 'P0',
)

#: Written to a scratch dir and loaded with ``-p``; dumps what pytest really
#: collected. Kept deliberately tiny — it must not be able to change a verdict.
_COLLECTOR_PLUGIN = '''
import json
import os


def pytest_collection_modifyitems(session, config, items):
    rows = []
    for it in items:
        name = it.name
        param = name.split("[", 1)[1][:-1] if "[" in name else None
        marks = []
        for m in it.iter_markers():
            marks.append({
                "name": m.name,
                "strict": m.kwargs.get("strict"),
                "reason": m.kwargs.get("reason"),
            })
        rows.append({
            "nodeid": it.nodeid,
            "file": os.path.basename(str(getattr(it, "fspath", ""))),
            "func": getattr(it, "originalname", None) or name.split("[")[0],
            "param": param,
            "marks": marks,
        })
    out = os.environ["MATRIX_CELL_COLLECT_OUT"]
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rows, fh)
'''


# ══════════════════════════════════════════════════════════════════════
# The eight modules
# ══════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def dimension_module_paths() -> Tuple[Path, ...]:
    return tuple(sorted(TESTS_DIR.glob(DIMENSION_MODULE_GLOB)))


@lru_cache(maxsize=1)
def dimension_modules() -> Dict[int, object]:
    """``{dim: imported module}``, keyed by each module's OWN ``DIM`` constant.

    Keying off the module's constant rather than off its filename is what makes
    a mislabelled module (``test_matrix_d5_*.py`` declaring ``DIM = 4``) a
    duplicate-dimension failure instead of a silent double-count.
    """
    import importlib.util

    out: Dict[int, object] = {}
    for path in dimension_module_paths():
        spec = importlib.util.spec_from_file_location(
            f"_matrix_cov_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        dim = getattr(mod, "DIM", None)
        assert isinstance(dim, int), (
            f"{path.name} declares no integer module-level DIM; the coverage "
            f"census cannot tell which dimension its cells belong to"
        )
        assert dim not in out, (
            f"{path.name} declares DIM={dim}, already claimed by "
            f"{getattr(out[dim], '__file__', '?')} — two modules cannot own the "
            f"same dimension or its cells are double-counted"
        )
        out[dim] = mod
    return out


# ══════════════════════════════════════════════════════════════════════
# Live collection through pytest's own machinery
# ══════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def collect_items() -> Tuple[Dict, ...]:
    """Every item pytest really collects from the eight dimension modules."""
    paths = dimension_module_paths()
    assert paths, f"no dimension module matched {DIMENSION_MODULE_GLOB!r}"
    scratch = Path(tempfile.mkdtemp(prefix="matrix_cov_collect_"))
    try:
        plugin = scratch / "matrix_cell_collector.py"
        plugin.write_text(_COLLECTOR_PLUGIN, encoding="utf-8")
        out = scratch / "collected.json"
        env = dict(os.environ)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env["MATRIX_CELL_COLLECT_OUT"] = str(out)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(scratch)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *[str(p) for p in paths],
             "--collect-only", "-q", "-p", "no:randomly",
             "-p", "matrix_cell_collector"],
            cwd=str(PLUGIN_ROOT), capture_output=True, text=True, timeout=1800,
            env=env,
        )
        assert out.is_file(), (
            f"pytest collection produced no manifest (rc={proc.returncode}).\n"
            f"A dimension module that fails to IMPORT contributes zero cells "
            f"and would otherwise look like a tidy green.\n"
            f"stdout tail:\n{proc.stdout[-3000:]}\n"
            f"stderr tail:\n{proc.stderr[-2000:]}"
        )
        assert proc.returncode == 0, (
            f"collection exited {proc.returncode}; a collection ERROR silently "
            f"removes every cell in the failing module.\n{proc.stdout[-3000:]}"
        )
        return tuple(json.loads(out.read_text(encoding="utf-8")))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


@lru_cache(maxsize=1)
def _file_to_dim() -> Dict[str, int]:
    return {p.name: dim
            for dim, mod in dimension_modules().items()
            for p in [Path(mod.__file__)]}


@lru_cache(maxsize=1)
def collected_cells() -> Dict[Tuple[str, int], List[Dict]]:
    """``{(step, dim): [collected items]}`` for every CELL item.

    A collected item is a cell iff its parametrize id is exactly
    ``step<declared flow step id>``. Duplicate entries in a list are the
    "counted twice" failure and are reported by the census test.
    """
    live_steps = {F.normalize_id(s) for s in F.step_ids()}
    by_file = _file_to_dim()
    out: Dict[Tuple[str, int], List[Dict]] = {}
    for row in collect_items():
        dim = by_file.get(row["file"])
        if dim is None:
            continue
        param = row.get("param")
        if not param:
            continue
        m = _CELL_ID_RE.match(param)
        if not m or m.group(1) not in live_steps:
            continue
        out.setdefault((m.group(1), dim), []).append(row)
    return out


@lru_cache(maxsize=1)
def cell_functions() -> Dict[int, Dict[str, Tuple[str, ...]]]:
    """``{dim: {test function name: (step ids it parametrizes,)}}``.

    Only functions whose cell-id set covers EVERY declared step are reported: a
    helper that happens to parametrize a handful of steps is not a cell test,
    and counting it as one would let a partial sweep pose as full coverage.
    """
    live_steps = [F.normalize_id(s) for s in F.step_ids()]
    by_file = _file_to_dim()
    per_func: Dict[Tuple[int, str], List[str]] = {}
    for row in collect_items():
        dim = by_file.get(row["file"])
        param = row.get("param")
        if dim is None or not param:
            continue
        m = _CELL_ID_RE.match(param)
        if not m or m.group(1) not in live_steps:
            continue
        per_func.setdefault((dim, row["func"]), []).append(m.group(1))
    out: Dict[int, Dict[str, Tuple[str, ...]]] = {}
    for (dim, func), steps in per_func.items():
        if set(steps) == set(live_steps):
            out.setdefault(dim, {})[func] = tuple(steps)
    return out


def _xfail_marks(row: Dict) -> Tuple[Dict, ...]:
    return tuple(m for m in row["marks"] if m["name"] == "xfail")


def _skip_marks(row: Dict) -> Tuple[Dict, ...]:
    return tuple(m for m in row["marks"] if m["name"] in ("skip", "skipif"))


def _state(dim: int, sid: str) -> str:
    mod = dimension_modules()[dim]
    fn = getattr(mod, "matrix_cell_state", None)
    assert callable(fn), (
        f"{Path(mod.__file__).name} exposes no matrix_cell_state(step_id); the "
        f"coverage census has no way to learn what state its cells are in, and "
        f"guessing would be this file forming a second opinion about cells it "
        f"does not own"
    )
    value = fn(sid)
    assert value in VALID_STATES, (
        f"dimension {dim} step {sid}: matrix_cell_state returned {value!r}, "
        f"which is not one of {VALID_STATES}. A fourth state is exactly the "
        f"escape hatch the three-state rule forbids"
    )
    return value


# ══════════════════════════════════════════════════════════════════════
# THE 504
# ══════════════════════════════════════════════════════════════════════
def test_the_grid_size_is_computed_from_the_live_flow_yaml():
    """504 is derived, never typed. Grow the flow and coverage goes incomplete.

    This is the property that keeps the whole claim from rotting: a 64th step
    makes the expected grid 512 while the eight modules still emit 63 cells
    each, so ``test_every_cell_is_present_exactly_once`` reddens the same minute
    the yaml changes.
    """
    steps = F.step_ids()
    assert len(steps) == len({F.normalize_id(s) for s in steps}), (
        f"the flow yaml declares duplicate step ids: "
        f"{[s for s in steps if [F.normalize_id(x) for x in steps].count(F.normalize_id(s)) > 1]}"
    )
    assert len(DIMENSIONS) == 8, f"DIMENSIONS is {DIMENSIONS!r}, expected 8"
    assert sorted(DIMENSIONS) == list(range(1, 9))
    expected = len(steps) * len(DIMENSIONS)
    assert expected == len(steps) * 8
    # And the value is the one every other test in this file uses.
    assert expected_cells() == expected

    # The review gate. Everything above is computed; this is the one place the
    # SIZE of the grid is compared against a number a human signed off on.
    measured = (len(steps), len(DIMENSIONS), expected)
    assert measured == GRID_AS_MEASURED, (
        f"the coverage grid changed: measured {measured} "
        f"(steps, dimensions, cells), pinned {GRID_AS_MEASURED}.\n"
        f"The eight dimension modules read the flow yaml LIVE, so they have "
        f"already grown to match and the census below will keep partitioning "
        f"tidily — which is precisely why this must fail here. "
        f"{abs(measured[0] - GRID_AS_MEASURED[0])} step(s) changed means "
        f"{abs(measured[2] - GRID_AS_MEASURED[2])} cell(s) whose predicates "
        f"nobody has reviewed.\n"
        f"Steps now in the flow but not when this was measured: "
        f"{sorted(set(F.normalize_id(s) for s in steps) - set(STEP_IDS_AS_MEASURED))}; "
        f"steps removed: "
        f"{sorted(set(STEP_IDS_AS_MEASURED) - set(F.normalize_id(s) for s in steps))}.\n"
        f"Review the new cells in all eight dimensions, then update "
        f"GRID_AS_MEASURED and STEP_IDS_AS_MEASURED in the same change."
    )
    assert tuple(F.normalize_id(s) for s in steps) == STEP_IDS_AS_MEASURED, (
        f"the flow's step LIST changed without the count changing (a step was "
        f"renamed, or one was added and another removed): measured "
        f"{[F.normalize_id(s) for s in steps]!r}"
    )
    assert F.FLOW_YAML.is_file(), f"flow yaml missing: {F.FLOW_YAML}"
    assert os.environ.get(F.FLOW_YAML_ENV) is None, (
        f"{F.FLOW_YAML_ENV}={os.environ.get(F.FLOW_YAML_ENV)!r} — the grid "
        f"would be sized from a file nobody reviewed"
    )


def expected_cells() -> int:
    """The size of the grid, recomputed from the live yaml on every call."""
    return len(F.step_ids()) * len(DIMENSIONS)


def test_eight_dimension_modules_own_the_eight_dimensions():
    """One module per dimension, no gaps, no two modules owning one dimension."""
    mods = dimension_modules()
    assert sorted(mods) == list(range(1, 9)), (
        f"dimension modules found: "
        f"{ {d: Path(m.__file__).name for d, m in mods.items()} }; "
        f"dimensions with no module: {sorted(set(range(1, 9)) - set(mods))}. "
        f"A dimension with no module contributes 63 UNCOVERED cells."
    )
    for dim, mod in mods.items():
        assert DIMENSION_NAMES[dim], f"dimension {dim} has no declared name"
        for attr in ("matrix_cell_state", "matrix_na_precondition"):
            assert callable(getattr(mod, attr, None)), (
                f"{Path(mod.__file__).name} does not expose {attr}(); this "
                f"file cannot ask the owning module what state its cells are in"
            )


def test_every_cell_is_present_exactly_once():
    """All 504 cells collected by pytest: none missing, none doubled.

    ``missing`` is the important half. A cell with no collected item is NOT
    covered no matter what any module's docstring says, and that is precisely
    the silent absence this campaign exists to make impossible.
    """
    cells = collected_cells()
    live_steps = [F.normalize_id(s) for s in F.step_ids()]
    grid = {(s, d) for s in live_steps for d in DIMENSIONS}

    missing = sorted(grid - set(cells))
    assert not missing, (
        f"{len(missing)} of the {len(grid)} cells have NO collected pytest "
        f"item — they are uncovered, whatever the modules report: "
        f"{missing[:20]}"
    )

    extra = sorted(set(cells) - grid)
    assert not extra, (
        f"{len(extra)} collected cell(s) name a (step, dimension) outside the "
        f"grid: {extra[:20]}"
    )

    # "Doubled" is per cell-test FUNCTION: dimension 8 legitimately runs two
    # different cell-complete sweeps over the same 63 steps, and that is two
    # measurements of one cell, not two cells. What must never happen is the
    # SAME function parametrizing one step twice — that is a duplicate param
    # silently masking a missing one.
    for dim, funcs in cell_functions().items():
        for func, steps in funcs.items():
            dupes = sorted({s for s in steps if steps.count(s) > 1})
            assert not dupes, (
                f"{func} (dimension {dim}) parametrizes step(s) {dupes} more "
                f"than once; a duplicated param can hide an absent one and "
                f"keep the arithmetic looking right"
            )

    assert len(cells) == expected_cells() == len(grid), (
        f"collected {len(cells)} distinct cells, grid is {len(grid)}, "
        f"{len(F.step_ids())} steps x {len(DIMENSIONS)} dimensions = "
        f"{expected_cells()}"
    )


def test_every_dimension_has_a_cell_complete_test_function():
    """Each module must carry at least one sweep that covers all 63 steps.

    Without this, a dimension could reach 63 collected cells by splitting them
    across several partial sweeps whose union happens to be complete while no
    single predicate is applied uniformly.
    """
    funcs = cell_functions()
    for dim in DIMENSIONS:
        assert funcs.get(dim), (
            f"dimension {dim} "
            f"({Path(dimension_modules()[dim].__file__).name}) has NO test "
            f"function parametrized over all {len(F.step_ids())} flow steps; "
            f"its cells are covered only by partial sweeps"
        )


# ══════════════════════════════════════════════════════════════════════
# EXACTLY ONE STATE PER CELL, AND THE THREE SOURCES MUST AGREE
# ══════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def state_census() -> Dict[Tuple[str, int], str]:
    return {(sid, dim): _state(dim, sid)
            for (sid, dim) in collected_cells()}


def test_every_cell_resolves_to_exactly_one_state():
    """ENFORCED + WAIVED + NA == 504, decided by the module that owns the cell."""
    census = state_census()
    assert len(census) == expected_cells()
    counts = {s: sum(1 for v in census.values() if v == s) for s in VALID_STATES}
    assert sum(counts.values()) == expected_cells(), counts
    # A dimension that waived or NA'd everything has stopped enforcing; say so
    # rather than letting a 504/504 headline carry it.
    for dim in DIMENSIONS:
        per = [v for (s, d), v in census.items() if d == dim]
        enforced = per.count("ENFORCED")
        assert enforced > len(per) / 2, (
            f"dimension {dim} ({DIMENSION_NAMES[dim]}) has only {enforced} "
            f"ENFORCED cells out of {len(per)}: "
            f"{ {s: per.count(s) for s in VALID_STATES} }. More than half its "
            f"grid is waived or inapplicable, so a green run says almost "
            f"nothing about it."
        )
    assert counts["ENFORCED"] + counts["WAIVED"] + counts["NA"] == expected_cells()


def test_state_agrees_with_the_waiver_registry_and_the_collected_marks():
    """The module, the registry and pytest must tell the same story.

    Three independent sources; disagreement in EITHER direction is a finding:

      * a cell the module calls WAIVED with no registry entry -> the waiver is
        invisible to anyone reading ``matrix_63x8/waivers.py``;
      * a registry entry whose cell the module calls ENFORCED -> a stale waiver
        that is silently suppressing nothing;
      * a strict xfail collected for a cell nobody calls WAIVED -> a cell
        excused at collection time with no registered reason, which is exactly
        an unlogged accepted gap.
    """
    census = state_census()
    cells = collected_cells()
    problems: List[str] = []

    for (sid, dim), state in sorted(census.items()):
        registry = W.waiver_for(sid, dim)
        marked = any(_xfail_marks(row) for row in cells[(sid, dim)])
        if state == "WAIVED":
            if registry is None:
                problems.append(
                    f"{sid}/d{dim}: the module reports WAIVED but "
                    f"matrix_63x8.waivers.WAIVERS has no entry — the accepted "
                    f"gap is invisible in the one place it is supposed to be "
                    f"published")
            if not marked:
                problems.append(
                    f"{sid}/d{dim}: reported WAIVED but pytest collected no "
                    f"xfail marker, so the cell is being RUN as if enforced")
        else:
            if registry is not None:
                problems.append(
                    f"{sid}/d{dim}: reported {state} but a waiver is "
                    f"registered for it — a stale waiver excusing nothing")
            if marked:
                problems.append(
                    f"{sid}/d{dim}: reported {state} but pytest collected an "
                    f"xfail marker for it; the cell is excused at collection "
                    f"time with no registered, evidence-backed reason")

    # And no registered waiver may name a cell outside the grid.
    grid = set(census)
    for w in W.WAIVERS:
        if w.key not in grid:
            problems.append(
                f"{w.label}: registered waiver names a (step, dimension) with "
                f"no collected cell — it excuses nothing and will never XPASS")

    assert not problems, (
        f"{len(problems)} state disagreement(s):\n  - " + "\n  - ".join(problems))


# ══════════════════════════════════════════════════════════════════════
# WAIVED: specific, evidence-backed, strict
# ══════════════════════════════════════════════════════════════════════
def test_every_waived_cell_is_specific_evidence_backed_and_strict():
    """A waiver must name a checkable obstacle and must self-destruct when fixed.

    ``strict=True`` is not a style preference. A non-strict xfail rots forever:
    the gap gets fixed, the test quietly starts passing, and nobody is told the
    waiver has become a lie. With ``strict=True`` the fix turns the suite red
    and forces the waiver's removal.
    """
    census = state_census()
    cells = collected_cells()
    waived = sorted(k for k, v in census.items() if v == "WAIVED")
    assert waived, (
        "no cell in the 504 is WAIVED. That is either genuinely perfect "
        "coverage or a registry that stopped being consulted; if the campaign "
        "really closed every gap, delete this assertion in the same change "
        "that removes the last waiver."
    )
    problems: List[str] = []
    for sid, dim in waived:
        w = W.waiver_for(sid, dim)
        if w is None:
            continue  # already reported by the agreement test
        for bad in W.validate(w):
            problems.append(f"{w.label}: {bad}")
        if not (w.reason or "").strip():
            problems.append(f"{w.label}: empty reason")
        if not (w.evidence or "").strip():
            problems.append(f"{w.label}: empty evidence")
        for row in cells[(sid, dim)]:
            marks = _xfail_marks(row)
            if not marks:
                continue
            for m in marks:
                if m.get("strict") is not True:
                    problems.append(
                        f"{w.label}: {row['nodeid']} carries a NON-STRICT "
                        f"xfail (strict={m.get('strict')!r}); it would rot "
                        f"silently the day the gap is fixed")
                reason = m.get("reason") or ""
                if not reason.strip():
                    problems.append(
                        f"{w.label}: {row['nodeid']} xfail carries no reason, "
                        f"so a failure report cannot say what is excused")
    assert not problems, (
        f"{len(problems)} waiver problem(s):\n  - " + "\n  - ".join(problems))


def test_no_waiver_reason_is_a_placeholder():
    """The forbidden-phrase list is applied to every landed waiver.

    ``waivers.validate()`` already does this; asserted again here because this
    file is the one place that reads the WHOLE registry, and a placeholder that
    slipped into a dimension nobody re-ran would otherwise be invisible.
    """
    offenders = []
    for w in W.WAIVERS:
        for phrase in W.FORBIDDEN_REASON_SUBSTRINGS:
            if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)",
                         w.reason, re.IGNORECASE):
                offenders.append(f"{w.label}: reason contains {phrase!r}")
        if len(w.reason.strip()) < W.MIN_REASON_LEN:
            offenders.append(f"{w.label}: reason under the length floor")
        if len(w.evidence.strip()) < W.MIN_EVIDENCE_LEN:
            offenders.append(f"{w.label}: evidence under the length floor")
    assert not offenders, "\n  ".join(offenders)


# ══════════════════════════════════════════════════════════════════════
# NA: a LIVE precondition, never a bare skip
# ══════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=None)
def _module_ast(dim: int) -> ast.Module:
    return ast.parse(Path(dimension_modules()[dim].__file__).read_text(
        encoding="utf-8"))


def _calls_pytest_skip(dim: int, func_name: str) -> Optional[str]:
    """Location of a ``pytest.skip`` / bare ``skip`` call inside *func_name*.

    An AST walk over THIS repository's own test module — exact by construction,
    with comments and docstrings gone, so the ``# ...pytest.skip()...`` prose in
    two of the modules' docstrings cannot be mistaken for a call site. (The
    campaign's standing rule against text scans is about the PRODUCTION tree's
    dynamic dispatch; here the target is a literal function definition in a file
    this test can parse completely.)
    """
    for node in ast.walk(_module_ast(dim)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != func_name:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            fn = call.func
            if isinstance(fn, ast.Attribute) and fn.attr == "skip":
                if isinstance(fn.value, ast.Name) and fn.value.id == "pytest":
                    return f"{func_name}: pytest.skip() at line {call.lineno}"
            if isinstance(fn, ast.Name) and fn.id == "skip":
                return f"{func_name}: skip() at line {call.lineno}"
    return None


def test_every_na_cell_asserts_a_live_precondition():
    """An NA must be self-invalidating, and must not be a skip in disguise.

    Three independent checks per NA cell:

      1. the owning module returns a NON-EMPTY precondition string for it RIGHT
         NOW, re-derived from the tree — so the day the precondition stops
         holding, the module stops calling the cell NA and this test says so;
      2. pytest collected no ``skip`` / ``skipif`` marker for the item — a
         marker-level skip never enters the test body at all;
      3. the cell test function's AST contains no ``pytest.skip`` call — a
         body-level skip would leave the cell reporting "passed" while
         asserting nothing about the precondition.
    """
    census = state_census()
    cells = collected_cells()
    funcs = cell_functions()
    na = sorted(k for k, v in census.items() if v == "NA")
    problems: List[str] = []

    for sid, dim in na:
        mod = dimension_modules()[dim]
        pre = mod.matrix_na_precondition(sid)
        if not (pre or "").strip():
            problems.append(
                f"{sid}/d{dim}: reported NA but matrix_na_precondition() "
                f"returned {pre!r} — an NA with no stated, live precondition "
                f"cannot self-invalidate")
        for row in cells[(sid, dim)]:
            if _skip_marks(row):
                problems.append(
                    f"{sid}/d{dim}: {row['nodeid']} carries "
                    f"{[m['name'] for m in _skip_marks(row)]} — an "
                    f"unconditionally skipped cell is silent absence wearing "
                    f"a hat")

    # (3) is a property of the cell FUNCTIONS, checked once per function rather
    # than once per NA cell, and checked for every dimension — including the
    # ones with no NA cell today, so a skip introduced later is caught before
    # it has an NA to hide behind.
    for dim, per_dim in funcs.items():
        for func in per_dim:
            found = _calls_pytest_skip(dim, func)
            if found:
                problems.append(
                    f"dimension {dim}: cell test {found}. A cell test may not "
                    f"skip: the three states are ENFORCED, WAIVED (strict "
                    f"xfail) and NA (asserted precondition)")

    assert not problems, (
        f"{len(problems)} NA problem(s):\n  - " + "\n  - ".join(problems))


def test_na_cells_are_a_minority_and_are_named():
    """NA is a real state, not a bucket to sweep cells into.

    No floor is asserted on the NA count — zero is a legitimate answer — but a
    dimension whose grid is mostly NA is not measuring that dimension, and the
    named census is what a reader needs in order to check the claim.
    """
    census = state_census()
    na = sorted(k for k, v in census.items() if v == "NA")
    per_dim: Dict[int, List[str]] = {}
    for sid, dim in na:
        per_dim.setdefault(dim, []).append(sid)
    for dim, sids in per_dim.items():
        assert len(sids) < len(F.step_ids()) / 2, (
            f"dimension {dim} ({DIMENSION_NAMES[dim]}) reports {len(sids)} of "
            f"{len(F.step_ids())} cells NA: {sorted(sids)}"
        )
        for sid in sids:
            pre = dimension_modules()[dim].matrix_na_precondition(sid)
            assert isinstance(pre, str) and len(pre.strip()) >= 20, (
                f"{sid}/d{dim}: NA precondition {pre!r} is too short to be "
                f"checkable by someone who has never seen the cell"
            )


# ══════════════════════════════════════════════════════════════════════
# Guards on this file's own instruments
# ══════════════════════════════════════════════════════════════════════
def test_collection_is_real_and_not_starved():
    """The collector must see a plausible suite, or every census above is
    vacuously true.

    This is the anti-starvation guard. The failure that convened this campaign
    was a checker reporting a clean run because its input had been emptied; a
    coverage meta-test whose collection silently returned zero items would
    report a tidy 0/0 partition and pass every assertion above.
    """
    items = collect_items()
    assert len(items) > expected_cells(), (
        f"pytest collected only {len(items)} items from the eight dimension "
        f"modules; the cell sweeps alone are {expected_cells()}, so collection "
        f"is starved and every census in this file is measuring nothing"
    )
    files = {row["file"] for row in items}
    for path in dimension_module_paths():
        assert path.name in files, (
            f"{path.name} contributed ZERO collected items — it either failed "
            f"to import or its parametrization produced nothing"
        )
    # Every cell item must be a real, addressable nodeid.
    for rows in collected_cells().values():
        for row in rows:
            assert "::" in row["nodeid"], row


def test_cell_ids_are_not_silently_renamed():
    """Cell ids must remain ``step<flow id>``, or the mapping goes quiet.

    If a module changed its ``ids=`` to something this file's regex does not
    match, the cells would vanish from ``collected_cells()`` and
    ``test_every_cell_is_present_exactly_once`` would report them missing —
    which is the correct, loud outcome. This test says the same thing earlier
    and more specifically, so the failure names the renamed function instead of
    63 anonymous absent cells.
    """
    by_file = _file_to_dim()
    live_steps = {F.normalize_id(s) for s in F.step_ids()}
    per_dim_cells = {dim: 0 for dim in DIMENSIONS}
    for row in collect_items():
        dim = by_file.get(row["file"])
        param = row.get("param")
        if dim is None or not param:
            continue
        m = _CELL_ID_RE.match(param)
        if m and m.group(1) in live_steps:
            per_dim_cells[dim] += 1
    starved = [d for d, n in per_dim_cells.items() if n < len(live_steps)]
    assert not starved, (
        f"dimension(s) {starved} emitted fewer than {len(live_steps)} "
        f"``step<id>`` parametrize ids: {per_dim_cells}. Either a cell sweep "
        f"lost steps, or its ``ids=`` no longer spells ``step<flow id>`` and "
        f"this file can no longer see its cells."
    )


def test_the_census_is_reported_for_humans(record_property):
    """Emit the split so a CI reader gets the number without reading the code."""
    census = state_census()
    lines = []
    for dim in DIMENSIONS:
        per = [v for (s, d), v in census.items() if d == dim]
        lines.append(
            f"d{dim} {DIMENSION_NAMES[dim]}: "
            f"ENFORCED={per.count('ENFORCED')} WAIVED={per.count('WAIVED')} "
            f"NA={per.count('NA')}")
    totals = {s: sum(1 for v in census.values() if v == s) for s in VALID_STATES}
    summary = (f"{len(census)} cells = {len(F.step_ids())} steps x "
               f"{len(DIMENSIONS)} dimensions; {totals}")
    record_property("matrix_63x8_census", summary)
    record_property("matrix_63x8_per_dimension", " | ".join(lines))
    assert len(census) == expected_cells(), summary
