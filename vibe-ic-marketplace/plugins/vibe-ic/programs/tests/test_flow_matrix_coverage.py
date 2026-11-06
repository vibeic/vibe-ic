"""test_flow_matrix_coverage.py — the meta-test that makes "full coverage" a
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

     * the central waiver registry (``flow_matrix.waivers.WAIVERS``), and
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

#: MEASURED at b309595f06, in the digest-pinned image
#: (ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2...d0d01ff), one file per process,
#: single bind mount, `PYTHONDONTWRITEBYTECODE=1`, this file alone:
#:
#:     4 failed, 29 passed, 2 warnings in 956.01s (0:15:56)
#:     --- programs/tests/test_flow_matrix_coverage.py  rc=1 cases=33 red=4
#:
#: It COMPLETED. It was never hung. Run under the per-file driver's base
#: silence grace of 300 s it is reported instead as
#: "STALLED after 300 s with no validated pytest lifecycle progress" and given
#: NO verdict -- which is how the four red tests above spent the 2026-09-03
#: census invisible underneath an UNKNOWN.
#:
#: AND ON A GIT-RESET CLEAN CHECKOUT, post-fix, at --stall-after 300:
#:
#:     32 passed, 1 skipped, 2 warnings in 408.38s (0:06:48)
#:     --- programs/tests/test_flow_matrix_coverage.py  rc=0 cases=33 red=0
#:
#: TWO RUNS, TWO VERDICTS, AND THE DIFFERENCE IS THE TREE, NOT THE FIX. The
#: 956 s / 4-red run above was taken on a checkout with uncommitted edits in
#: it; this file's census reads the tree it runs in, so four of its cells went
#: red on the modification rather than on anything it is testing. That is worth
#: knowing on its own -- this file's verdict is a function of the working tree
#: -- and it is recorded here rather than tidied away, because the number below
#: has to cover the SLOWER of the two.
#:
#: 956 s IS AN UPPER BOUND ON ANY SINGLE SILENT GAP IN IT, because the whole
#: file ran in that. 1800 is that bound with room for a loaded host: the run
#: above was measured at load average 17-22 on a shared machine, so the number
#: must not be the one that only holds when the host is quiet. A wedge is still
#: killed and still NORECORD -- 1800 s later, not never.
#:
#: THIS FILE ALREADY RELAYS SEMANTIC PROGRESS for its nested live-collection
#: phase (`_domain_progress` / `_NESTED_PROGRESS_RELAY_TOTAL`), which is the
#: better repair and the one that needs no number at all. Extending that relay
#: to the outcome-report waves would let this declaration shrink; until it does,
#: the declaration is what stops the file from being unmeasurable.
VIBEIC_SILENCE_BUDGET_S = 1800

import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

import pytest

from flow_matrix import flowref as F
from flow_matrix import waivers as W
from flow_matrix.cells import DIMENSIONS, DIMENSION_NAMES

TESTS_DIR = Path(__file__).resolve().parent

#: The dimension modules, DISCOVERED not listed. A tenth appearing, or one
#: going missing, changes this set and reddens the census below.
#:
#: The range moved 1-8 -> 1-9 when dimension 9 (`verdict_consumed`) was added.
#: It is a CHARACTER CLASS, not a count: `d10` would not match it, so the day a
#: tenth dimension lands this glob must be widened deliberately rather than
#: silently admitting a two-digit spelling.
DIMENSION_MODULE_GLOB = "test_matrix_d[1-9]_*.py"

#: A cell test's parametrize id is exactly ``step<flow step id>``. Anything with
#: a suffix (dimension 8's ``step8-out0`` per-entry sweep) is a finer-grained
#: probe, not a cell, and is not counted as one.
_CELL_ID_RE = re.compile(r"^step(.+)$")

#: THE GRID HAS FOUR STATES, and the fourth was added by owner ruling on
#: 2026-08-21 after this file spent a release insisting on three.
#:
#: The three-state rule was right about the danger and wrong about the
#: inventory. Its danger is real: a fourth state IS an escape hatch if a cell
#: can enter it by saying nothing. But forcing every cell into ENFORCED /
#: WAIVED / NA meant a cell whose evidence THIS REPOSITORY DOES NOT HOLD had to
#: come out as one of them, and each of those three is a statement about the
#: DESIGN. "I could not look" is not a verdict about the design, and the grid
#: had no way to say it.
#:
#: MEASURED, and this is what forced the ruling: six dimension-3 cells (steps
#: 15, 17, 19, 20, 30, 32) declare outputs whose manifest record cites a
#: `home`-kind campaign run root that no corpus can supply on any host. They
#: were reported ENFORCED — which claims their predicate passed — while their
#: live predicate failed, and `test_no_cell_is_counted_enforced_while_its
#: _predicate_is_red` named all six. Neither ENFORCED nor WAIVED nor NA was
#: true of them. NOT_MEASURED is.
#:
#: WHAT STOPS IT BEING THE ESCAPE HATCH: the reason is REQUIRED. A cell may
#: enter NOT_MEASURED only by naming the evidence that is missing, through
#: `matrix_not_measured_reason(step_id)`, and a cell in this state with no
#: reason is a bug in the emitter rather than a NOT_MEASURED cell —
#: `test_every_not_measured_cell_names_the_evidence_it_lacks` refuses it. And
#: NOT_MEASURED never counts as a pass: see
#: `test_a_not_measured_cell_is_never_counted_as_enforced`.
VALID_STATES = ("ENFORCED", "WAIVED", "NA", "NOT_MEASURED")

#: The one state that is neither enforcement nor a decision about the design.
NOT_MEASURED = "NOT_MEASURED"

#: Dimensions that have answered ``matrix_cell_substitution`` — "was this cell's
#: ENFORCED verdict measured against the step's own mechanism, or against a
#: stand-in?" — as MEASURED 2026-08-09.
#:
#: Pinned in BOTH directions, which is the whole anti-rot mechanism:
#:
#:   * a dimension DROPPING its declaration would silently move its substituted
#:     cells out of the published SUBSTITUTED column and back into the total a
#:     reader quotes — the exact erasure this contract closes;
#:   * a dimension GAINING one changes the published split, so the generated
#:     census table in ``flow_matrix/README.md`` must be regenerated in the same
#:     change rather than left asserting a number that no longer reproduces.
#:
#: Dimension 9 joined on 2026-08-21: its L3 leg holds 68 of 69 steps' gates at a
#: known tier with a `files_exist` stand-in and measures the consumption path
#: rather than the step's own gate, so those cells are SUBSTITUTED. The one
#: gate-less step (P0) is driven through its own structural umbrella and reads
#: OWN. Declaring is what keeps that 68/1 split in the published table instead of
#: dying inside a single "ENFORCED 69".
#:
#: The remaining dimensions are deliberately NOT here. The question is open for them and
#: is not answerable from outside the module that built the predicate — see
#: ``flow_matrix/substitution.py``, "WHY UNDECLARED IS A STATE AND NOT A
#: DEFAULT". Their cells are published as UNDECLARED, never folded into either
#: answer.
DIMENSIONS_DECLARING_SUBSTITUTION: Tuple[int, ...] = (8, 9)

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
#: MOVED BY HAND 2026-08-21, (67, 8, 536) -> (69, 9, 621). The derivation, so a
#: reviewer can re-run it rather than trust it:
#:
#:   * DIMENSIONS 8 -> 9: `verdict_consumed` added
#:     (`programs/tests/test_matrix_d9_verdict_consumed.py`).
#:   * STEPS: the pin said 67 while `STEP_IDS_AS_MEASURED` beside it listed 68
#:     ids — the pair is meant to move together and had been moved half-way, so
#:     the count was already wrong before this change. Measured live:
#:       `python3 -c "from flow_matrix import flowref as F; print(len(F.step_ids()))"`
#:       -> 69, ids delta against the old list: +'0.5ic', +'1.6x', -'37.5self'
#:     (68 + 2 - 1 = 69). '1.6x' landed in v1.11.15, '37.5self' was retired in
#:     v1.11.18; '0.5ic' predates both.
#:   * CELLS: 69 * 9 = 621, recomputed here and by `expected_cells()`.
#:
#: This number is DELIBERATELY not derived from the yaml. Deriving a tripwire
#: from the same source the assertion reads makes the assertion tautological —
#: see `flow_matrix/README.md`. It is moved by hand, once, with the measurement
#: above recorded beside it.
# 2026-08-24: the former 1.6x contract is now a Step-2 clause, so the
# independently reviewed flow population is again 68 x 9.
#: 2026-09-02: (68, 9, 612) -> (69, 9, 621). ONE step arrives -- 37.4,
#: sign-off metrics aggregation -- and its nine cells were reviewed in every
#: dimension in the same change: D1 wiring (its gate names
#: `signoff_metrics_aggregate --check`, which resolves), D3 outputs (recorded
#: ENFORCED, both entries UNPROVEN because the producer is new), D5 deps (the
#: edge 37.5ic -> 37.4 was MISSING and this dimension found it), D7 output
#: list, and the remaining dimensions read the yaml live. No step left.
#: 2026-09-23: (69, 9, 621) -> (70, 9, 630). ONE step arrives -- canonical 37.3,
#: GDS stream-out / finishing fidelity (R-0915-129 metric 2) -- and its NINE cells
#: were reviewed in every dimension in this same change, which is the condition
#: the 37.4 move above set for a rising pin. No step left: measured against
#: origin/main, arrived ['37.3'], departed [].
#:
#: D1 wiring: its gate names `gds_xor_check . --json reports/phase3/gds_xor.json`,
#: which resolves to a program in this tree and to the step's own declared output.
#: D2 falsifiability: the gate's one blocking clause reaches FAIL on a broken
#: project -- it did NOT on the first draft, which exited rc 2 on a refusal and so
#: landed on VACUOUS_PASS, a non-FAIL tier, and this dimension named it in its own
#: words ("step 37.3 gate CANNOT FAIL on anything a project DID"); all eight
#: refusals now exit 1.
#: D3 outputs: recorded ENFORCED; the declaration is UNPROVEN because the producer
#: is new, and the D3 replay is ALREADY_RED for exactly that reason.
#: D4 criteria: two mutations REDDENED it (D4-UNGATED-DELIVERABLE, D4-CLI-CONTRACT).
#: D5 deps: this dimension found a real defect -- the step read
#: `phase3/stage4/gds/*.gds` with no edge to its producer (D5-MISSING-EDGE) -- and
#: the repair is the condition on step 21's `routed.def` with `blocks_on: [21]`.
#: D6 skip discipline: it found the OTHER real defect -- the original trigger, the
#: run's pad-ring route attestation, was a SELF-DISABLING CONDITION whose absence
#: is loud nowhere (T7/T3/T5 all None) and which the runner writes only on the chip
#: pad-ring path.
#: D7 output list: REDDENED after the two W2 declarations step 37 gained here
#: (`phase3/stage3/pnr/stream_out.log` and the route attestation); it was
#: ALREADY_RED before them, and that was the finding.
#: D8 missing caught: REDDENED, and the step is in the measured single-entry
#: population re-derived in this change.
#: D9 verdict consumed: the receipt's `verdict` field is read by
#: `signoff_metrics_aggregate`, which is why a refusal keeps NOT_DETERMINED
#: distinguishable from a measured FAIL.
GRID_AS_MEASURED: Tuple[int, int, int] = (70, 9, 630)

#: The flow's step ids, in declaration order, as measured 2026-07-28. Pinned
#: alongside the count so a rename or an add-plus-remove — which leaves the
#: count at 63 — is caught too.
#:
#: RE-MEASURED 2026-07-28 for the dimension-5 waiver closures. The POPULATION is
#: unchanged — same 63 ids, no add, no remove, no rename; only the DECLARATION
#: ORDER of three of them moved, and the move IS the fix:
#:   * A6 was declared at index 52, after step 39, while A7 (`blocks_on: [A6]`)
#:     sat at 23 — the flow's only FORWARD edge, which #503 cascade attribution
#:     (`for sid in order:`) can never cut. A6 now sits between A5 and A7.
#:   * DT2 / DT3 were declared at 14/15 while DT2's own condition names step
#:     22's SPEF (index 34), so `blocks_on: [DT1, 22]` was unwritable. They now
#:     sit directly after step 22 and DT2 declares that edge.
#: Both are verified by `test_matrix_d5_deps_correct.py`'s D5-FORWARD-EDGE and
#: D5-MISSING-EDGE clauses, and the graph is still acyclic (D5-CYCLE, plus
#: `test_d5_runtime_ordering_guard_loads_the_same_edges`).
#: `37.5self` (General Precheck) joined after 37.5ic and before 38: the chip
#: path with NO operator. 37.5ic's condition wants the shuttle's slot template
#: and 37.5ip is the IP/hardmacro terminal, so a design taping ITSELF out
#: matched neither and reached tape-out having passed no submission check.
#: Declared where it runs — after step 37 writes the chip GDS, beside the two
#: routes it is mutually exclusive with.
STEP_IDS_AS_MEASURED: Tuple[str, ...] = (
    'D1',
    '0.5ic',
    '1',
    'P0',
    '2',
    '3',
    '4',
    '5',
    '6',
    '7',
    '8',
    '9',
    '10',
    '11',
    'FS1',
    'DT1',
    '12',
    '13',
    'A1',
    'A2',
    'A3',
    'A4',
    'A5',
    'A6',
    'A7',
    'A8',
    'A9',
    '14',
    '15',
    '15.5ic',
    '16',
    '17',
    '18',
    '19',
    '20',
    '21',
    '32',
    '22',
    '23',
    'DT2',
    'DT3',
    '24',
    '25',
    '26',
    '27',
    '28',
    '29',
    '30',
    '33',
    '37',
    '26.5ic',
    '34',
    '35',
    '37.3',
    '31',
    '37.4',
    '36',
    '37.5ip',
    '37.5ic',
    '38',
    '39',
    'M1',
    'M2',
    'M3',
    'M4',
    '40',
    '41',
    '42',
    '43',
    '44',
)

#: Written to a scratch dir and loaded with ``-p``; dumps what pytest really
#: collected. Kept deliberately tiny — it must not be able to change a verdict.
_COLLECTOR_PLUGIN = '''
import json
import os

_ROWS = []

def pytest_collection_finish(session):
    global _ROWS
    rows = []
    for it in session.items:
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
    _ROWS = rows


def pytest_sessionfinish(session, exitstatus):
    if int(exitstatus) != 0:
        return
    out = os.environ["MATRIX_CELL_COLLECT_OUT"]
    temporary = out + ".tmp." + str(os.getpid())
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump({
            "schema": 1,
            "complete": True,
            "selected_items": len(session.items),
            "rows": _ROWS,
        }, fh, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temporary, out)
'''

#: The OUTCOME collector. Same discipline as the plugin above and for the same
#: reason: it records pytest's RAW per-phase reports and reduces nothing. The
#: reduction to a single outcome happens in :func:`_reduce_outcome`, in this
#: file, where it is unit-testable — a plugin that decided what "red" meant
#: would be a verdict-forming instrument living outside the file that is
#: supposed to be auditable.
_OUTCOME_PLUGIN = '''
import json
import os

_ROWS = {}


def pytest_runtest_logreport(report):
    _ROWS.setdefault(report.nodeid, []).append({
        "when": report.when,
        "outcome": report.outcome,
        "wasxfail": hasattr(report, "wasxfail"),
        "longrepr": str(getattr(report, "longrepr", "") or "")[:240],
    })


def pytest_sessionfinish(session, exitstatus):
    out = os.environ["MATRIX_CELL_OUTCOME_OUT"]
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(_ROWS, fh)
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
_COLLECTION_PROGRESS_STALL_S = 60

#: How far the generated collection work must overshoot the enclosing lease.
#: This is what the literal `files = 21` encoded while the outer bound was
#: always exactly 2x `old_fixed_bound`: 21 files of `old/6` is `3.5 x old`,
#: i.e. 1.75 outer bounds.  Named so the count can be derived from it when the
#: outer bound stops being a fixed multiple (vibe-ic#2219).
_OUTER_CROSSING_MARGIN = 1.75
_COLLECTION_PROGRESS_POLL_S = 0.1
_collection_invocation = 0


























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
    assert len(DIMENSIONS) == 9, f"DIMENSIONS is {DIMENSIONS!r}, expected 9"
    assert sorted(DIMENSIONS) == list(range(1, 10))
    expected = len(steps) * len(DIMENSIONS)
    assert expected == len(steps) * 9
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


def test_every_dimension_module_owns_exactly_one_dimension():
    """One module per dimension, no gaps, no two modules owning one dimension."""
    mods = dimension_modules()
    assert sorted(mods) == list(range(1, 10)), (
        f"dimension modules found: "
        f"{ {d: Path(m.__file__).name for d, m in mods.items()} }; "
        f"dimensions with no module: {sorted(set(range(1, 10)) - set(mods))}. "
        f"A dimension with no module contributes 63 UNCOVERED cells."
    )
    for dim, mod in mods.items():
        assert DIMENSION_NAMES[dim], f"dimension {dim} has no declared name"
        for attr in ("matrix_cell_state", "matrix_na_precondition"):
            assert callable(getattr(mod, attr, None)), (
                f"{Path(mod.__file__).name} does not expose {attr}(); this "
                f"file cannot ask the owning module what state its cells are in"
            )






# ══════════════════════════════════════════════════════════════════════
# EXACTLY ONE STATE PER CELL, AND THE THREE SOURCES MUST AGREE
# ══════════════════════════════════════════════════════════════════════










# ══════════════════════════════════════════════════════════════════════
# WAIVED: specific, evidence-backed, strict
# ══════════════════════════════════════════════════════════════════════


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












# ══════════════════════════════════════════════════════════════════════
# Guards on this file's own instruments
# ══════════════════════════════════════════════════════════════════════






# ══════════════════════════════════════════════════════════════════════
# THE SECOND AXIS — WHAT THE CELL'S PREDICATE ACTUALLY DID
# ══════════════════════════════════════════════════════════════════════
# ORGANIC-20260808 (P1), closed here.
#
# Everything above this line measures how a cell is CONFIGURED. Nothing above
# it ever asked whether the cell's predicate PASSES. The two are independent,
# and the gap between them was the one number in this system a reader is
# invited to quote:
#
#     MEASURED 2026-08-09 on commit dee025059, before this section existed:
#       state census        ENFORCED 481   WAIVED 11   NA 12   (504 cells)
#       live suite          32 failed, 797 passed, 11 xfailed
#       ENFORCED cells whose own pytest item was RED at that moment:  26
#
# `ENFORCED` is defined by this package's README as "a live predicate runs AND
# PASSES". A red ENFORCED cell is therefore not a fourth category, it is a
# CONTRADICTION between the state the owning module reports and what the tree
# does when you run it — a cell counted as proof of enforcement at the exact
# moment its enforcement is broken.
#
# The state axis could not have caught this and was never going to:
# `collect_items()` runs pytest with `--collect-only`, so it can learn that a
# cell EXISTS, is parametrized, is not skipped and carries (or does not carry)
# an xfail marker — and nothing whatsoever about whether it passes. This
# section runs the same eight modules FOR REAL, joins the two axes, and
# `test_no_cell_is_counted_enforced_while_its_predicate_is_red` refuses the
# contradiction.
#
# THE REMEDY FOR A RED CELL IS NOT TO SILENCE THIS TEST. The three-state rule
# already has a home for "this enforcement is currently broken": WAIVED, with
# a registry entry, an evidence-backed reason and a strict xfail — all three
# cross-checked by `test_state_agrees_with_the_waiver_registry_and_the_
# collected_marks` and `test_every_waived_cell_is_specific_evidence_backed_
# and_strict`. Fix the cell or waive it on the record. Those are the two
# doors, and neither of them is a green census over a red predicate.

#: What each state PREDICTS the live run will do. This is what makes a state a
#: CHECKABLE CLAIM rather than a label: the module says how the cell is set up,
#: and this says what that setup obliges the cell to do when pytest runs it.
#:
#: ``WAIVED`` expects ``xfailed`` and not ``passed`` on purpose — a waiver is a
#: strict xfail, so a WAIVED cell that PASSES is an XPASS, which is the
#: anti-rot mechanism firing and must be reported, not absorbed.
#: ``NOT_MEASURED`` expects ``skipped``, and that pairing is the whole point of
#: the fourth state. The cell says "I could not look" on the configuration axis
#: and the run must actually decline to look — a NOT_MEASURED cell that PASSES
#: has measured something after all and the state is a lie; one that FAILS is
#: charging the design with a defect on evidence it just said it does not have.
STATE_EXPECTS_OUTCOME: Dict[str, str] = {
    "ENFORCED": "passed",
    "WAIVED": "xfailed",
    "NA": "passed",
    NOT_MEASURED: "skipped",
}


class CellVerdict(NamedTuple):
    """One cell on both axes at once."""

    state: str                    # how the owning module has it configured
    outcomes: Tuple[str, ...]     # what its pytest item(s) really did
    agrees: bool                  # does the second axis bear out the first
    label: str                    # what may be REPORTED for this cell


def _reduce_outcome(reports: List[Dict]) -> str:
    """Collapse one item's setup/call/teardown reports into ONE outcome.

    Deliberately explicit about xfail rather than trusting a single field:
    pytest signals an expected failure as ``skipped`` + ``wasxfail`` on the
    call report, but a STRICT xfail that unexpectedly PASSES arrives as
    ``failed`` and, depending on the pytest version, without ``wasxfail`` —
    only its ``longrepr`` says ``[XPASS(strict)]``. Collapsing that to plain
    "failed" would hide an XPASS, which is the exact rot the strict waivers
    exist to surface.
    """
    call = next((r for r in reports if r["when"] == "call"), None)
    if call is None:
        setup = next((r for r in reports if r["when"] == "setup"), None)
        if setup is None:
            return "unrun"
        if setup["outcome"] == "failed":
            return "error"
        if setup["outcome"] == "skipped":
            return "xfailed" if setup["wasxfail"] else "skipped"
        return "unrun"

    if call["outcome"] == "passed":
        label = "xpassed" if call["wasxfail"] else "passed"
    elif call["outcome"] == "skipped":
        label = "xfailed" if call["wasxfail"] else "skipped"
    elif "XPASS" in call["longrepr"]:
        label = "xpassed"
    else:
        label = "xfailed" if call["wasxfail"] else "failed"

    # A green call with a red setup/teardown is not a green cell.
    if label in ("passed", "xfailed") and any(
            r["outcome"] == "failed" for r in reports if r["when"] != "call"):
        return "error"
    return label


#: Liveness window for ONE dimension module's outcome run.  This is NOT a
#: total-runtime timeout.  The child is supervised by pytest's validated
#: collection/test lifecycle: every strict forward transition renews the
#: window, so a healthy module may run for arbitrarily many windows.  Output
#: and CPU activity do not renew it; an import loop that prints or burns CPU
#: forever is still NORECORD.  The value is below the enclosing 180 s pytest
#: guard so a genuine lifecycle stall is named and cleaned before that guard
#: can take the whole aggregate session down.
_OUTCOME_PROGRESS_STALL_S = 60

#: Keep the eight independent module sessions in three waves.  The wave count
#: controls resource multiplication only; it is no longer multiplied by a
#: guessed wall-clock duration to manufacture a total-runtime promise.
_OUTCOME_MAX_WAVES = 3

# The official Landing Gate already owns liveness through validated semantic
# progress and returns NORECORD on a stall.  Disable pytest-timeout's fixed
# per-item wall clock here: this module intentionally runs a nested live census,
# and killing a healthy item because host contention crossed an estimate is the
# false differential this file must not recreate.
pytestmark = pytest.mark.timeout(0)

# Optional cap for a caller that owns a broader resource schedule.  It changes
# scheduling only: paths, manifests, merge order and verdict rules are
# identical.  The Landing Gate deliberately does not force this knob; the
# semantic supervisor removes load-sensitive fixed wall-clock failures instead
# of making both differential arms slower in the hope that they fail alike.
_OUTCOME_WORKER_CAP_ENV = "VIBEIC_MATRIX_OUTCOME_WORKERS"
_NESTED_PROGRESS_RELAY_TOTAL = 10_000






def _outcome_worker_count(n_paths: int, cap: Optional[int] = None) -> int:
    """Derive a bounded process fan-out while retaining three ordered waves.

    The width is derived from the discovered module count, never fixed, so a
    ninth dimension cannot silently turn the intended three-wave schedule into
    four.  This is a resource/concurrency policy, not a runtime estimate.

    `_run_outcome_reports` also enforces a barrier between groups of this width;
    without it a finished light job starts a later heavy job while the current
    heavy one is still live, recreating the I/O contention that made the old
    fixed wall deadline load-dependent.
    """
    assert n_paths >= 1, "no module paths to size the outcome pool for"
    derived = -(-n_paths // _OUTCOME_MAX_WAVES)  # ceil, without importing math
    if cap is None:
        return derived
    assert 1 <= cap <= n_paths, (
        f"{_OUTCOME_WORKER_CAP_ENV} must be within 1..{n_paths}, got {cap}")
    return min(derived, cap)


#: What the LAST `_run_outcome_reports` actually did: the width it ran at and the
#: greatest number of module runs it ever had in flight at once. Published so a
#: test can assert on the schedule that RAN rather than on one it re-derives, and
#: so a load-narrowed width does not make a wave-boundary check red for being
#: right. Reset on entry to every run, so a stale pair can never be read as this
#: run's.
_LAST_OUTCOME_RUN: Dict[str, int] = {"width": 0, "peak_in_flight": 0}


def _load_bounded_width(ceiling: int) -> int:
    """Narrow `ceiling` to what THIS host can actually run at once.

    A BUDGET OF PROCESSES, NEVER OF SECONDS. `_outcome_worker_count` derives a
    ceiling from the MODULE COUNT — eight dimension modules in three waves is
    three — and reads neither the size of the host nor what else is on it. That
    is right as a ceiling and wrong as a floor: MEASURED on 8hd-3 (32 cores) on
    2026-09-07, one census item's own descendant tree peaked at 47 concurrent
    processes, because each of the three nested pytest sessions reaches modules
    whose own fan-out is another hard-coded eight (`matrix_d4_probe._PROBE_FANOUT`,
    `test_matrix_d6_skip_discipline`'s `min(8, len(todo))`). At a 1-minute load
    average of 60 the same file took 765 s against 431 s alone -- 1.78x -- and it
    contributed about 20 to that load itself.

    THE CEILING IS NEVER RAISED, only lowered. A load-aware width that could grow
    would change what an idle host does, and `_outcome_worker_count(8) == 3` is a
    property other tests assert; this is a strict narrowing, so on an unloaded
    host every schedule is exactly the one that ran before.

    "COULD NOT LOOK" IS NOT "LOOKED AND FOUND AN IDLE HOST". A host with no
    `getloadavg` and a host whose core count is unknown both keep the full
    ceiling rather than being handed a made-up figure -- the same refusal
    `NOT_MEASURED` carries elsewhere in this campaign, in the one place where
    defaulting would be invisible.

    NOT A DEADLINE, AND NOTHING HERE KILLS. A worker that is slow because the
    host is busy still finishes; what changes is how many of them are started.
    """
    cpus = os.cpu_count()
    if not cpus:
        return ceiling
    try:
        load = os.getloadavg()[0]
    except (OSError, AttributeError):
        return ceiling
    return max(1, min(ceiling, int(cpus - load)))


def _outcome_worker_cap() -> Optional[int]:
    raw = os.environ.get(_OUTCOME_WORKER_CAP_ENV)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise AssertionError(
            f"{_OUTCOME_WORKER_CAP_ENV} must be an integer, got {raw!r}") from exc


def test_outcome_worker_cap_reduces_nested_width_without_changing_default(
        monkeypatch):
    assert _outcome_worker_count(8) == 3
    monkeypatch.setenv(_OUTCOME_WORKER_CAP_ENV, "1")
    assert _outcome_worker_count(8, _outcome_worker_cap()) == 1
    monkeypatch.setenv(_OUTCOME_WORKER_CAP_ENV, "0")
    with pytest.raises(AssertionError, match="within 1..8"):
        _outcome_worker_count(8, _outcome_worker_cap())
    monkeypatch.setenv(_OUTCOME_WORKER_CAP_ENV, "not-an-int")
    with pytest.raises(AssertionError, match="must be an integer"):
        _outcome_worker_cap()


















#: Seconds each synthetic module sleeps in the concurrency probe below. Small
#: enough that the probe costs one wave of it, large enough to dominate the
#: interpreter start it is measured against.
_PROBE_SLEEP_S = 2

_PROBE_MODULE = "import time\n\n\ndef test_probe():\n    time.sleep(%d)\n"






def test_the_process_budget_narrows_under_load_and_never_widens(monkeypatch):
    """A budget of PROCESSES, from the host's own capacity and its 1-min load.

    Both directions, on the arithmetic, because the load of a real host cannot
    be arranged: an idle host must get the ceiling UNCHANGED, and a host with
    less spare capacity than the ceiling must get less.
    """
    mod = sys.modules[__name__]
    monkeypatch.setattr(mod.os, "cpu_count", lambda: 32)

    # Idle: the ceiling survives byte-for-byte. This is the direction that keeps
    # every existing schedule identical on a quiet machine.
    monkeypatch.setattr(mod.os, "getloadavg", lambda: (5.0, 5.0, 5.0))
    assert _load_bounded_width(3) == 3
    assert _load_bounded_width(8) == 8

    # Busy: narrowed to the spare capacity, and never below one -- a host with
    # no spare capacity still makes progress, one process at a time.
    monkeypatch.setattr(mod.os, "getloadavg", lambda: (30.0, 30.0, 30.0))
    assert _load_bounded_width(3) == 2
    monkeypatch.setattr(mod.os, "getloadavg", lambda: (60.0, 60.0, 60.0))
    assert _load_bounded_width(3) == 1
    assert _load_bounded_width(64) == 1

    # It NARROWS. It can never hand back more processes than it was given, which
    # is what keeps `_outcome_worker_count` the ceiling it is asserted to be.
    monkeypatch.setattr(mod.os, "getloadavg", lambda: (0.0, 0.0, 0.0))
    assert _load_bounded_width(3) == 3, (
        "an idle 32-core host must not be handed a WIDER pool than the "
        "module-count ceiling; a load-aware width that can grow changes what "
        "every quiet host does")


def test_a_host_that_cannot_be_measured_keeps_the_ceiling(monkeypatch):
    """COULD NOT LOOK is not LOOKED AND FOUND AN IDLE HOST.

    Neither refusal may invent a figure. Keeping the ceiling is the only answer
    that is honest about having measured nothing: it is exactly the schedule the
    tree had before any of this, so nothing is decided by a number nobody read.
    """
    mod = sys.modules[__name__]

    def _no_loadavg():
        raise OSError("this host does not report a load average")

    monkeypatch.setattr(mod.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(mod.os, "getloadavg", _no_loadavg)
    assert _load_bounded_width(3) == 3

    monkeypatch.setattr(mod.os, "cpu_count", lambda: None)
    monkeypatch.setattr(mod.os, "getloadavg", lambda: (60.0, 60.0, 60.0))
    assert _load_bounded_width(3) == 3



    # WHAT THIS RECORDER MEASURES, said plainly so nobody reads more into the
    # assertion it backs: runs SUBMITTED AND NOT YET RETURNED. That is the
    # schedule's real width — a submit-then-wait loop peaks at 1 however fast
    # the work is, which is the whole claim — and it is deliberately NOT a
    # measure of how much work overlapped inside those runs.


def norecord_foreign_red_reason(foreign_reds) -> str:
    """The ONE sentence every NORECORD-on-a-foreign-red refusal prints.

    Extracted so the assertion below and the CENSUS GENERATOR cannot drift
    apart in what they call this condition. `tools/gen_flow_matrix_census.py`
    has to refuse for the same reason without going through the assertion —
    see :func:`cell_outcomes_with_record` — and a second sentence written
    there would be a second vocabulary for one state (vibe-ic#2004).
    """
    return (
        "the nested outcome run produced red test report(s) outside the "
        "matrix cell join. Its rc=1 is not completely represented by the "
        f"cell census, so this run is NORECORD: {list(foreign_reds)[:8]}")








def _join_cell_reports(
        reports: Dict[str, List[Dict]],
        by_file: Dict[str, int],
        live_steps: Set[str],
) -> Tuple[Dict[Tuple[str, int], Tuple[str, ...]], List[Tuple[str, str]]]:
    """``(cells, foreign reds)`` — the join, with nothing decided about it.

    The join and the VERDICT about the join were one function until
    vibe-ic#2004, so the only way to obtain the cells was to accept the
    refusal. :func:`_cell_outcomes_from_reports` is that refusal and is
    unchanged; this is the same computation with the dropped reds handed back
    instead of asserted on, for the repair tool that has to write an artefact
    before it is entitled to refuse.
    """
    out: Dict[Tuple[str, int], List[str]] = {}
    consumed: Set[str] = set()
    for nodeid, phase_reports in reports.items():
        head, sep, tail = nodeid.partition("::")
        if not sep or "[" not in tail:
            continue
        dim = by_file.get(os.path.basename(head))
        if dim is None:
            continue
        param = tail.rsplit("[", 1)[1].rstrip("]")
        m = _CELL_ID_RE.match(param)
        if not m or m.group(1) not in live_steps:
            continue
        consumed.add(nodeid)
        out.setdefault((m.group(1), dim), []).append(
            _reduce_outcome(phase_reports))
    dropped_red = sorted(
        (nodeid, _reduce_outcome(phase_reports))
        for nodeid, phase_reports in reports.items()
        if nodeid not in consumed
        and _reduce_outcome(phase_reports) in {"failed", "error", "xpassed"}
    )
    return {k: tuple(v) for k, v in out.items()}, dropped_red


def _cell_outcomes_from_reports(
        reports: Dict[str, List[Dict]],
        by_file: Dict[str, int],
        live_steps: Set[str],
) -> Dict[Tuple[str, int], Tuple[str, ...]]:
    """Join raw reports into cells without silently dropping a red item.

    Dimension modules contain both the parametrized matrix predicates and
    supporting tests.  A supporting test that turns red is still a refusal of
    the nested pytest session; discarding it here would let that rc=1 pose as
    fully represented cell evidence.  Green non-cell helpers may be ignored,
    but every red report must enter the exact cell join below or the census is
    NORECORD.
    """
    out, dropped_red = _join_cell_reports(reports, by_file, live_steps)
    assert not dropped_red, norecord_foreign_red_reason(dropped_red)
    return out


def test_a_red_non_cell_helper_cannot_represent_the_nested_session_rc():
    """A helper failure may not disappear behind one green cell report."""
    passed = [{"when": "call", "outcome": "passed", "wasxfail": False,
               "longrepr": ""}]
    failed = [{"when": "call", "outcome": "failed", "wasxfail": False,
               "longrepr": "supporting check refused the session"}]
    reports = {
        "test_matrix_d1_example.py::test_cell[stepD1]": passed,
        "test_matrix_d1_example.py::test_non_cell_helper": failed,
    }
    with pytest.raises(AssertionError, match="outside the matrix cell join"):
        _cell_outcomes_from_reports(
            reports, {"test_matrix_d1_example.py": 1}, {"D1"})


def _join_axes(
        states: Dict[Tuple[str, int], str],
        outcomes: Dict[Tuple[str, int], Tuple[str, ...]],
) -> Dict[Tuple[str, int], CellVerdict]:
    """Join the configuration axis against the live-outcome axis.

    A cell with NO observed outcome does NOT agree. That is deliberate: an
    unobserved cell is precisely the shape this whole file exists to refuse,
    and defaulting it to "fine" would rebuild the defect one level up.
    """
    joined: Dict[Tuple[str, int], CellVerdict] = {}
    for key, state in states.items():
        assert state in STATE_EXPECTS_OUTCOME, (
            f"{key}: state {state!r} has no expected outcome; a state whose "
            f"claim about the live run is undefined cannot be checked")
        observed = tuple(outcomes.get(key, ()))
        want = STATE_EXPECTS_OUTCOME[state]
        agrees = bool(observed) and all(o == want for o in observed)
        # A CELL THAT WAS NEVER ASKED DID NOT DISAGREE.
        #
        # `-CONTRADICTED` means the cell RAN and the live outcome refuted the
        # configured claim — a finding about the tree. A cell whose every observed
        # outcome is `skipped` produced no such finding: its check declined to run,
        # naming a resource it could not reach (an absent tool, an absent published
        # corpus). Filing that as a contradiction reports a defect where there is
        # only an inability to look, which is the exact conflation this file's
        # two-axis design exists to remove one level down.
        #
        # It is NOT folded into agreement either. A skipped cell has not been
        # enforced, and calling it ENFORCED would be the erasure #888 closed.
        skipped = bool(observed) and all(o == "skipped" for o in observed)
        if agrees:
            label = state
        elif skipped:
            label = f"{state}-SKIPPED"
        else:
            label = f"{state}-CONTRADICTED"
        joined[key] = CellVerdict(
            state=state,
            outcomes=observed,
            agrees=agrees,
            label=label,
        )
    return joined


def enforcement_counter(
        joined: Dict[Tuple[str, int], CellVerdict]) -> Dict[str, int]:
    """The REPORTABLE shape. ``ENFORCED`` here has earned the word."""
    counts: Dict[str, int] = {}
    for verdict in joined.values():
        counts[verdict.label] = counts.get(verdict.label, 0) + 1
    return counts






#: THE TWO VERDICTS A DISAGREEING CENSUS CAN REACH, and they are not the same
#: finding. Extracted out of the test body on purpose: a three-valued verdict
#: whose middle value is only reachable through a 400 s live nested run is a
#: verdict nobody can falsify, and an unfalsifiable verdict is what this file
#: exists to refuse.
_VERDICT_FAIL = "fail"
_VERDICT_REFUSE = "refuse"

#: Outcomes that mean THE PREDICATE NEVER GAVE AN ANSWER, as opposed to
#: giving a red one. `agrees` folds both into "contradicted" — correctly,
#: since neither is evidence of enforcement — but the two have different
#: causes and different owners, and the verdict must not conflate them.
#:
#: MEASURED (vibe-ic#1348): the same tree, same commit, reported 16
#: contradictions on a host with every repo dependency installed and 54 in a
#: container missing `pyyaml`. The extra 38 were predicates that could not
#: RUN. A reader given one number cannot tell a repo defect from a missing
#: dependency, and "16" is not reproducible without knowing which host
#: produced it.
_UNMEASURED_OUTCOMES = ("error", "unrun", "skipped")


def _disagreement_verdict(
        joined: Dict[Tuple[str, int], CellVerdict],
        counts: Dict[str, int],
) -> Tuple[Optional[str], str]:
    """``(verdict, message)`` for a joined census; ``(None, "")`` when clean.

    Splits the disagreeing cells into the two classes the message has printed
    since #1348 and returns which of them decides the outcome:

      * ``_VERDICT_FAIL`` — at least one cell was MEASURED RED. The message is
        the one this check has always emitted, unchanged, and it is reached
        whether or not not-measured cells sit beside it.
      * ``_VERDICT_REFUSE`` — nothing was measured red and the whole
        disagreement is cells that never returned a verdict.
      * ``None`` — no cell disagrees.

    Every disagreeing cell is enumerated in BOTH messages. The verdict decides
    what the enumeration MEANS, never which cells appear in it.
    """
    broken = sorted((k for k, v in joined.items() if not v.agrees),
                    key=lambda k: (k[1], k[0]))
    if not broken:
        return None, ""

    measured, unmeasured = [], []
    for sid, dim in broken:
        verdict = joined[(sid, dim)]
        line = (
            f"  {sid}/G{dim} ({DIMENSION_NAMES[dim]}): reported "
            f"{verdict.state} — which claims its predicate "
            f"{STATE_EXPECTS_OUTCOME[verdict.state]} — but the live run "
            f"says {', '.join(verdict.outcomes) or '<never observed>'}")
        (unmeasured if (not verdict.outcomes
                        or all(o in _UNMEASURED_OUTCOMES
                               for o in verdict.outcomes))
         else measured).append(line)
    lines = []
    if measured:
        lines.append(
            f"MEASURED RED — the predicate ran and contradicted the state "
            f"({len(measured)}). These are repo defects:")
        lines.extend(measured)
    if unmeasured:
        lines.append(
            f"NOT MEASURED — the predicate never returned a verdict "
            f"({len(unmeasured)}). NOT evidence of enforcement either, but "
            f"a missing dependency or a collection error is a HOST problem, "
            f"not a repo defect. Fix the environment and re-run before "
            f"reading these as findings:")
        lines.extend(unmeasured)
    state_only = {s: sum(1 for v in joined.values() if v.state == s)
                  for s in VALID_STATES}
    enumeration = (
        f"{len(broken)} of {len(joined)} cells are reported in a state "
        f"their own live predicate contradicts "
        f"({len(measured)} measured red, {len(unmeasured)} not measured):\n"
        + "\n".join(lines)
        + f"\n\nSTATE-ONLY census (what used to be published): "
          f"{state_only}"
        + f"\nTWO-AXIS census (what is true): {counts}")

    if measured:
        # UNCHANGED, byte for byte, from before the refusal existed. One
        # measured red is a finding about this tree however many not-measured
        # cells stand beside it, and it is reported the same way it always was.
        return _VERDICT_FAIL, (
            enumeration
            + "\n\nA cell in this list is counted as coverage and is not "
              "covering anything. Fix the predicate or waive it on the "
              "record; see flow_matrix/README.md, 'The three-state rule'.")

    return _VERDICT_REFUSE, (
        f"REFUSED — 0 measured red, {len(unmeasured)} NOT MEASURED. This "
        f"check has no finding about this tree to report, and it has not "
        f"passed either. Every one of the {len(unmeasured)} cells is "
        f"enumerated below and NOT ONE of them is counted as enforcing "
        f"anything.\n\n"
        + enumeration
        + "\n\nWHY THIS IS A REFUSAL AND NOT A PASS: 'a gate that could not "
          "run has not passed' (tools/ci/J63B_63X8_RED_SET.md) — and it has "
          "not failed either. Every cell above DECLINED TO LOOK; that is a "
          "statement about what this checkout holds, not about what the flow "
          "does. `benchmark-data` was moved OUT of this repository and large "
          "raw geometry (*.def, *.gds, *.spef, *.oas over the ceiling) is not "
          "committed, both by design, and a check that reddens because the "
          "repository followed its own rules is measuring the policy and "
          "reporting it as a defect."
        + "\n\nIT SELF-INVALIDATES: point VIBE_IC_BENCHMARK_DATA at a clone "
          "that carries the artefact, or publish the run, and the predicate "
          "returns a verdict and every cell above re-enters the measured half "
          "of this check. And ONE measured red still FAILS, beside any number "
          "of these — `test_a_single_measured_red_still_fails_beside_any_"
          "number_of_not_measured_cells` is the control that says so.")




def test_a_single_measured_red_still_fails_beside_any_number_of_not_measured_cells():
    """The control for the refusal, in BOTH directions.

    A refusal that also absorbed a measured red would be strictly worse than
    the failure it replaced: the one class this check exists to surface would
    disappear behind the class it exists to excuse. These four constructed
    censuses pin the polarity without paying for the live 612-cell run, and
    the middle one — 1 measured red beside 47 not measured — is the exact
    shape the refusal could have broken.
    """
    def _census(cells):
        """``{cell: (state, outcomes)}`` -> a joined census, via the real join."""
        return _join_axes({k: v[0] for k, v in cells.items()},
                          {k: v[1] for k, v in cells.items()})

    # (1) MEASURED RED ALONE -> FAIL.
    red_only = _census({("R", 1): ("ENFORCED", ("failed",))})
    verdict, message = _disagreement_verdict(
        red_only, enforcement_counter(red_only))
    assert verdict == _VERDICT_FAIL, (verdict, message)
    assert "1 measured red, 0 not measured" in message, message
    assert "R/G1" in message, message

    # (2) NOT MEASURED ALONE -> REFUSE, still enumerating every cell.
    skipped_only = _census({
        (f"S{i}", 3): ("ENFORCED", ("skipped",)) for i in range(47)})
    verdict, message = _disagreement_verdict(
        skipped_only, enforcement_counter(skipped_only))
    assert verdict == _VERDICT_REFUSE, (verdict, message)
    assert "0 measured red, 47 not measured" in message, message
    assert "MEASURED RED —" not in message, message
    for i in range(47):
        assert f"S{i}/G3" in message, f"cell S{i} vanished from the refusal"

    # (3) THE MIXED CASE — the one this change could have broken. One measured
    #     red hiding behind 47 not-measured cells must still FAIL, and the
    #     message must report BOTH counts and enumerate BOTH classes.
    mixed = dict(skipped_only)
    mixed.update(_census({("R", 1): ("ENFORCED", ("failed",))}))
    verdict, message = _disagreement_verdict(
        mixed, enforcement_counter(mixed))
    assert verdict == _VERDICT_FAIL, (verdict, message)
    assert "48 of 48 cells" in message, message
    assert "1 measured red, 47 not measured" in message, message
    assert "MEASURED RED — the predicate ran" in message, message
    assert "NOT MEASURED — the predicate never" in message, message
    assert "R/G1" in message and "S0/G3" in message, message
    # and the closing paragraph is the pre-refusal one, unchanged
    assert "counted as coverage and is not covering anything" in message
    assert "Fix the predicate or waive it on the record" in message

    # (4) A CLEAN CENSUS IS STILL A PASS, so the refusal is not a check that
    #     refuses everything.
    clean = _census({("G", 1): ("ENFORCED", ("passed",))})
    assert _disagreement_verdict(clean, enforcement_counter(clean)) == (None, "")




# ── The control: prove the second axis can tell red from green ────────
#: A throwaway dimension-shaped module. Three cells, three known outcomes.
_SYNTHETIC_CELL_MODULE = '''
import pytest

DIM = 99


@pytest.mark.parametrize("step_id", ["GREEN"], ids=["stepGREEN"])
def test_synthetic_cell_green(step_id):
    assert True


@pytest.mark.parametrize("step_id", ["RED"], ids=["stepRED"])
def test_synthetic_cell_red(step_id):
    assert False, "synthetic red predicate"


@pytest.mark.xfail(strict=True, reason="synthetic waiver")
@pytest.mark.parametrize("step_id", ["WAIVED"], ids=["stepWAIVED"])
def test_synthetic_cell_waived(step_id):
    assert False, "synthetic waived predicate"
'''




def test_the_outcome_reducer_names_a_strict_xpass_rather_than_a_failure():
    """An XPASS must not be laundered into a plain failure.

    A strict xfail that starts passing is the anti-rot mechanism firing — the
    waiver's gap is fixed and the waiver must now be deleted. If
    :func:`_reduce_outcome` folded it into "failed" it would still be red, but
    the census would say "a WAIVED cell whose predicate failed", i.e. exactly
    the healthy state, and the XPASS would vanish from the report.
    """
    assert _reduce_outcome([
        {"when": "call", "outcome": "failed", "wasxfail": False,
         "longrepr": "[XPASS(strict)] the gap this waiver names is fixed"},
    ]) == "xpassed"
    assert _reduce_outcome([
        {"when": "call", "outcome": "skipped", "wasxfail": True,
         "longrepr": "reason: still broken"},
    ]) == "xfailed"
    assert _reduce_outcome([
        {"when": "setup", "outcome": "failed", "wasxfail": False,
         "longrepr": "fixture blew up"},
    ]) == "error"
    assert _reduce_outcome([
        {"when": "call", "outcome": "passed", "wasxfail": False,
         "longrepr": ""},
        {"when": "teardown", "outcome": "failed", "wasxfail": False,
         "longrepr": "teardown blew up"},
    ]) == "error"
    # And a WAIVED cell that XPASSes is a contradiction, not a healthy waiver.
    assert not _join_axes(
        {("X", 9): "WAIVED"}, {("X", 9): ("xpassed",)})[("X", 9)].agrees
