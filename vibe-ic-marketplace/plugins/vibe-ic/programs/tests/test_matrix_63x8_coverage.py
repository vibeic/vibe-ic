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
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

import pytest

from matrix_63x8 import flowref as F
from matrix_63x8 import substitution as SUB
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
#:     census table in ``matrix_63x8/README.md`` must be regenerated in the same
#:     change rather than left asserting a number that no longer reproduces.
#:
#: Seven dimensions are deliberately NOT here. The question is open for them and
#: is not answerable from outside the module that built the predicate — see
#: ``matrix_63x8/substitution.py``, "WHY UNDECLARED IS A STATE AND NOT A
#: DEFAULT". Their cells are published as UNDECLARED, never folded into either
#: answer.
DIMENSIONS_DECLARING_SUBSTITUTION: Tuple[int, ...] = (8,)

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
STEP_IDS_AS_MEASURED: Tuple[str, ...] = (
    'D1', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', 'FS1',
    'DT1', '12', '13', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8',
    'A9', '14', '15', '16', '17', '18', '19', '20', '21', '22', 'DT2',
    'DT3', '23', '24', '25', '26', '27', '28', '29', '30', '31', '32',
    '33', '34', '35', '36', '37', '38', '39', 'M1', 'M2', 'M3', 'M4',
    '40', '41', '42', '43', '44', 'P0',
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
_COLLECTION_PROGRESS_POLL_S = 0.1
_collection_invocation = 0


def _collect_items_from_paths(paths: Tuple[Path, ...],
                              cwd: Path) -> Tuple[Dict, ...]:
    """Collect paths through the nonce/FSM supervisor and complete manifest."""
    global _collection_invocation
    assert paths, "the collection question has an empty path selection"
    _collection_invocation += 1
    progress_scope = f"matrix-live-collection-{_collection_invocation}"
    scratch = Path(tempfile.mkdtemp(prefix="matrix_cov_collect_"))
    try:
        plugin = scratch / "matrix_cell_collector.py"
        plugin.write_text(_COLLECTOR_PLUGIN, encoding="utf-8")
        out = scratch / "collected.json"
        meta = scratch / "collect-supervisor.json"
        spec = scratch / "collect-spec.json"
        relay = scratch / "semantic-progress.relay"
        relay.touch(mode=0o600)
        env = dict(os.environ)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["MATRIX_CELL_COLLECT_OUT"] = str(out)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(scratch)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        spec.write_text(json.dumps({
            "schema": 1,
            "test_files": [str(path) for path in paths],
            "meta": str(meta),
            "stall_after": _COLLECTION_PROGRESS_STALL_S,
            "poll_s": min(
                _COLLECTION_PROGRESS_POLL_S,
                _COLLECTION_PROGRESS_STALL_S / 4),
            "cwd": str(cwd),
            "progress_relay": str(relay),
            "pytest_argv": [
                sys.executable, "-m", "pytest", "-q", "--tb=no",
                "-p", "no:randomly", "-p", "no:cacheprovider",
                "-p", "matrix_cell_collector",
                "--basetemp", str(scratch / "pytest_tmp"),
            ],
        }, sort_keys=True) + "\n", encoding="utf-8")
        driver = TESTS_DIR.parent / "pytest_per_file_junit.py"
        log = scratch / "collect-supervisor.log"
        relay_offset = 0
        relay_tail = b""
        last_score = 0
        relay_error = ""

        def publish_relay(*, final: bool = False) -> None:
            nonlocal relay_offset, relay_tail, last_score, relay_error
            if relay_error:
                return
            try:
                size = relay.stat().st_size
                if size < relay_offset:
                    relay_error = "relay truncated"
                    return
                with relay.open("rb") as relay_file:
                    relay_file.seek(relay_offset)
                    chunk = relay_file.read()
            except OSError as exc:
                relay_error = f"relay unreadable: {exc}"
                return
            relay_offset += len(chunk)
            records = (relay_tail + chunk).split(b"\n")
            relay_tail = records.pop()
            for payload in records:
                if not payload:
                    relay_error = "empty relay score"
                    return
                try:
                    score = int(payload.decode("ascii"))
                except (UnicodeDecodeError, ValueError):
                    relay_error = f"malformed relay score {payload!r}"
                    return
                if not last_score < score <= _NESTED_PROGRESS_RELAY_TOTAL:
                    relay_error = (
                        f"non-monotonic relay {last_score} -> {score}")
                    return
                last_score = score
                _domain_progress(
                    progress_scope, score, _NESTED_PROGRESS_RELAY_TOTAL)
            if final and relay_tail:
                relay_error = "truncated final relay score"

        with log.open("w+", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                [sys.executable, str(driver), "--_collect-worker-spec",
                 str(spec)],
                cwd=str(cwd), stdout=log_file, stderr=subprocess.STDOUT,
                text=True, env=env)
            while proc.poll() is None:
                publish_relay()
                time.sleep(0.1)
            publish_relay(final=True)
            log_file.flush()
            log_file.seek(0)
            diagnostic = log_file.read()
        assert not relay_error, (
            f"collection semantic relay is invalid: {relay_error}\n"
            f"{diagnostic[-5000:]}")
        try:
            worker = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssertionError(
                "collection supervisor published no usable terminal metadata "
                f"(worker rc={proc.returncode}): {exc}\n"
                f"{diagnostic[-5000:]}") from exc
        assert (isinstance(worker, dict)
                and set(worker) == {
                    "schema", "complete", "pytest_rc",
                    "semantic_record_complete", "norecord_reason",
                }
                and worker.get("schema") == 1
                and worker.get("complete") is True
                and isinstance(worker.get("semantic_record_complete"), bool)
                and isinstance(worker.get("norecord_reason"), str)), (
            f"collection supervisor metadata has the wrong shape: {worker!r}")
        assert proc.returncode == 0 and worker["pytest_rc"] == 0 \
            and worker["semantic_record_complete"], (
                "pytest collection produced no complete nonce-bound lifecycle "
                f"record (worker rc={proc.returncode}, pytest "
                f"rc={worker['pytest_rc']}): "
                f"{worker['norecord_reason']}\n{diagnostic[-5000:]}")
        assert out.is_file(), (
            f"pytest collection produced no complete manifest (worker "
            f"rc={proc.returncode}).\n"
            f"A dimension module that fails to IMPORT contributes zero cells "
            f"and would otherwise look like a tidy green.\n"
            f"diagnostic tail:\n{diagnostic[-5000:]}"
        )
        try:
            manifest = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssertionError(
                f"collection manifest is unreadable/truncated: {exc}") from exc
        assert (isinstance(manifest, dict)
                and set(manifest) == {
                    "schema", "complete", "selected_items", "rows"}
                and manifest.get("schema") == 1
                and manifest.get("complete") is True
                and isinstance(manifest.get("selected_items"), int)
                and isinstance(manifest.get("rows"), list)
                and manifest["selected_items"] == len(manifest["rows"])), (
            f"collection manifest has no exact completion/count proof: "
            f"{manifest!r}")
        assert manifest["rows"], (
            "pytest collected zero items; an empty live census is not proof "
            "that every matrix cell exists")
        # This checkpoint is emitted only after the nonce-bound nested pytest
        # lifecycle and its complete row/count manifest both validated.  The
        # BASE-owned outer schedule permits it only for the exact census item;
        # stdout, CPU use, and partial collection cannot renew that lease.
        _domain_progress("matrix-collection-runs", 1, 1)
        return tuple(manifest["rows"])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


@lru_cache(maxsize=1)
def collect_items() -> Tuple[Dict, ...]:
    """Every item pytest really collects from the eight dimension modules."""
    paths = dimension_module_paths()
    assert paths, f"no dimension module matched {DIMENSION_MODULE_GLOB!r}"
    return _collect_items_from_paths(paths, PLUGIN_ROOT)


def test_live_collection_relays_finite_semantic_progress_past_old_bound(
        monkeypatch, tmp_path):
    """Several completed collections may outlive a former total deadline."""
    old_fixed_bound = 0.3
    seen = []
    monkeypatch.setattr(
        sys.modules[__name__], "_domain_progress",
        lambda scope, completed, total:
        seen.append((scope, completed, total)))
    monkeypatch.setattr(
        sys.modules[__name__], "_COLLECTION_PROGRESS_STALL_S",
        old_fixed_bound)
    paths = []
    for index in range(7):
        path = tmp_path / f"test_collect_progress_{index}.py"
        path.write_text(
            "import time\ntime.sleep(.14)\n\n"
            f"def test_{index}(): assert True\n", encoding="utf-8")
        paths.append(path)

    started = time.monotonic()
    rows = _collect_items_from_paths(tuple(paths), tmp_path)
    elapsed = time.monotonic() - started

    assert elapsed > 0.8, elapsed
    assert {row["file"] for row in rows} == {path.name for path in paths}
    assert seen[-1] == ("matrix-collection-runs", 1, 1)
    assert seen.count(("matrix-collection-runs", 1, 1)) == 1


def test_live_collection_chatty_import_without_events_fails_closed(
        monkeypatch, tmp_path):
    """Collection stdout cannot impersonate a nonce-bound FSM transition."""
    monkeypatch.setattr(
        sys.modules[__name__], "_COLLECTION_PROGRESS_STALL_S", 0.25)
    monkeypatch.setenv("PYTEST_ADDOPTS", "-s")
    path = tmp_path / "test_chatty_collect.py"
    path.write_text(
        "import time\n"
        "deadline=time.monotonic()+3\n"
        "while time.monotonic() < deadline:\n"
        "    print('COLLECT_CHATTER', flush=True)\n"
        "    time.sleep(.02)\n"
        "def test_never(): assert True\n", encoding="utf-8")

    started = time.monotonic()
    with pytest.raises(AssertionError) as caught:
        _collect_items_from_paths((path,), tmp_path)
    elapsed = time.monotonic() - started
    message = str(caught.value)
    assert elapsed < 3, elapsed
    assert "WATCHDOG_STALLED:" in message
    assert "COLLECT_CHATTER" in message


def test_live_collection_refuses_missing_complete_manifest(
        monkeypatch, tmp_path):
    """A complete lifecycle cannot substitute for the collector's record."""
    path = tmp_path / "test_green_collect.py"
    path.write_text("def test_green(): assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        sys.modules[__name__], "_COLLECTOR_PLUGIN",
        "def pytest_collection_modifyitems(session, config, items): pass\n")

    with pytest.raises(AssertionError, match="no complete manifest"):
        _collect_items_from_paths((path,), tmp_path)


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
    """``{(step, dim): state}`` — the CONFIGURATION axis, and only that.

    NOT A COVERAGE CLAIM ON ITS OWN. This answers "how is the cell set up",
    which is what the waiver-registry and NA-precondition cross-checks below
    need. It does NOT answer "does the cell's predicate pass": every value
    here is derived from ``matrix_cell_state`` plus a ``--collect-only`` run,
    and neither ever executes a predicate.

    Quoting ``ENFORCED: N`` from this dict is what ORGANIC-20260808 reported —
    on 2026-08-08 it read 481 while 26 of those 481 cells were failing. Use
    :func:`enforcement_census` for anything a reader will quote; it joins this
    axis against the live outcome and is guarded by
    :func:`test_no_cell_is_counted_enforced_while_its_predicate_is_red`.
    """
    return {(sid, dim): _state(dim, sid)
            for (sid, dim) in collected_cells()}


@lru_cache(maxsize=1)
def substitution_census() -> Dict[Tuple[str, int], str]:
    """``{(step, dim): "OWN" | "SUBSTITUTED" | "UNDECLARED"}`` for every ENFORCED
    cell. Cells that are WAIVED or NA are absent — they already say they are not
    enforcing, and giving them a substitution bucket would double-count them.

    Live on every call, like :func:`state_census`: the owning module re-derives
    its answer from the current tree, and this file only sorts the answers into
    published columns.
    """
    out: Dict[Tuple[str, int], str] = {}
    enforced = [(key, state) for key, state in state_census().items()
                if state == "ENFORCED"]
    for completed, ((sid, dim), state) in enumerate(enforced, start=1):
        mod = dimension_modules()[dim]
        out[(sid, dim)] = SUB.bucket(SUB.disclosure_for(mod, sid, state))
        _domain_progress(
            "matrix-substitution-census", completed, len(enforced))
    return out


def test_a_substituted_cell_is_never_counted_as_enforcing_its_own_mechanism():
    """The finding this contract closes, asserted rather than described.

    Dimension 8 holds every step's gate at a known tier by substituting a
    stand-in for it, discloses that at length in its own docstring, and until
    2026-08-09 fed the census a plain ``ENFORCED`` for all 61 cells anyway. One
    number reached the README; the caveat did not.

    Three properties are pinned here, all live:

      1. every ENFORCED cell lands in exactly one published bucket;
      2. a bucket is only ever assigned by the module that OWNS the cell —
         a dimension that has not declared reads UNDECLARED, never OWN, so
         silence can never be published as a clean bill of health;
      3. the set of dimensions that HAVE declared matches
         :data:`DIMENSIONS_DECLARING_SUBSTITUTION`, in both directions.

    (3) is what stops the erasure from coming back: deleting dimension 8's hook
    would move 45 cells out of the SUBSTITUTED column and back into the number a
    reader quotes, and it would do so with every other test in this file green.
    """
    census = substitution_census()
    states = state_census()
    enforced = {k for k, v in states.items() if v == "ENFORCED"}
    assert set(census) == enforced, (
        f"substitution census covers {len(census)} cells but "
        f"{len(enforced)} are ENFORCED; "
        f"unbucketed: {sorted(enforced - set(census))[:10]}, "
        f"over-bucketed: {sorted(set(census) - enforced)[:10]}"
    )
    bad = {k: v for k, v in census.items() if v not in SUB.BUCKETS}
    assert not bad, f"cells in no published bucket: {bad}"

    declared = tuple(sorted(
        d for d in DIMENSIONS if SUB.declares(dimension_modules()[d])))
    assert declared == DIMENSIONS_DECLARING_SUBSTITUTION, (
        f"the dimensions declaring {SUB.HOOK}() changed: measured "
        f"{list(declared)}, pinned {list(DIMENSIONS_DECLARING_SUBSTITUTION)}.\n"
        f"Dropped: {sorted(set(DIMENSIONS_DECLARING_SUBSTITUTION) - set(declared))} "
        f"— those cells' substituted enforcement stops being published and "
        f"folds back into the total a reader quotes.\n"
        f"Added: {sorted(set(declared) - set(DIMENSIONS_DECLARING_SUBSTITUTION))} "
        f"— good, and the generated census in matrix_63x8/README.md must be "
        f"regenerated in the same change "
        f"(`python3 tools/gen_matrix_63x8_census.py`)."
    )
    # A declared dimension whose every cell reads OWN has an inert hook: the
    # disclosure mechanism exists and reports nothing, which looks identical to
    # not having it and is how this kind of contract rots.
    for dim in declared:
        buckets = [v for (s, d), v in census.items() if d == dim]
        assert SUB.SUBSTITUTED in buckets or SUB.UNDECLARED_BUCKET in buckets, (
            f"dimension {dim} declares {SUB.HOOK}() but reports every one of "
            f"its {len(buckets)} ENFORCED cells as OWN. Either the dimension "
            f"stopped substituting — in which case say so in its docstring and "
            f"remove it from DIMENSIONS_DECLARING_SUBSTITUTION — or the hook "
            f"has been neutralised and is now disclosing nothing."
        )


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


def _is_skip_call(node: ast.AST) -> bool:
    """``True`` for a ``pytest.skip(...)`` or bare ``skip(...)`` call node."""
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute) and fn.attr == "skip":
        return isinstance(fn.value, ast.Name) and fn.value.id == "pytest"
    return isinstance(fn, ast.Name) and fn.id == "skip"


def _skip_calls(dim: int, func_name: str) -> Tuple[Tuple[int, bool], ...]:
    """``(line, guarded)`` for every skip call inside *func_name*.

    An AST walk over THIS repository's own test module — exact by construction,
    with comments and docstrings gone, so the ``# ...pytest.skip()...`` prose in
    two of the modules' docstrings cannot be mistaken for a call site. (The
    campaign's standing rule against text scans is about the PRODUCTION tree's
    dynamic dispatch; here the target is a literal function definition in a file
    this test can parse completely.)

    ``guarded`` is ``True`` when the call sits under an ``if`` inside the
    function. THE TWO ARE DIFFERENT FINDINGS and used to be one:

    * an UNGUARDED skip runs on every host, so the cell never executes
      anywhere. That is silent absence wearing a hat and stays forbidden.
    * a GUARDED skip names a resource this checkout could not reach. The
      two-axis census has modelled exactly that since ``_join_axes`` grew the
      ``-SKIPPED`` labels: such a cell is neither folded into ENFORCED nor
      filed as a CONTRADICTION, it is published in its own column (44
      ENFORCED-SKIPPED + 3 WAIVED-SKIPPED at the time of writing). A flat ban
      on the call therefore contradicted this file's own join, and the file
      failed against itself: the corpus-absent skip landed in the d3 and d7
      cell predicates on 2026-08-16 (``c8c2ab0f7``) and
      ``test_every_na_cell_asserts_a_live_precondition`` has been red ever
      since, while the census next to it published the same cells as a
      disclosed, named population.

    Narrowing the ban is only honest if the case it stops covering is covered
    somewhere stricter, so it is: a guarded skip now has to be DECLARED by the
    owning module through ``matrix_skip_precondition`` and that declaration is
    checked live, per cell, in both directions by
    ``test_every_skipping_cell_names_the_resource_it_could_not_reach``.
    """
    out: List[Tuple[int, bool]] = []

    def walk(node: ast.AST, guarded: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if _is_skip_call(child):
                out.append((child.lineno, guarded))
            walk(child, guarded or isinstance(child, ast.If))

    for node in ast.walk(_module_ast(dim)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != func_name:
            continue
        walk(node, False)
    return tuple(out)


def test_every_na_cell_asserts_a_live_precondition():
    """An NA must be self-invalidating, and must not be a skip in disguise.

    Three independent checks per NA cell:

      1. the owning module returns a NON-EMPTY precondition string for it RIGHT
         NOW, re-derived from the tree — so the day the precondition stops
         holding, the module stops calling the cell NA and this test says so;
      2. pytest collected no ``skip`` / ``skipif`` marker for the item — a
         marker-level skip never enters the test body at all;
      3. the cell test function's AST contains no UNGUARDED ``pytest.skip``
         call, and any guarded one is declared by the module through
         ``matrix_skip_precondition`` — an unconditional body-level skip would
         leave the cell asserting nothing about the precondition on every
         host, while a guarded one is the ``-SKIPPED`` outcome ``_join_axes``
         publishes and is held to its own live, bidirectional check by
         ``test_every_skipping_cell_names_the_resource_it_could_not_reach``.
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
        mod = dimension_modules()[dim]
        for func in per_dim:
            calls = _skip_calls(dim, func)
            for line, guarded in calls:
                if not guarded:
                    problems.append(
                        f"dimension {dim}: cell test {func}: an UNGUARDED skip "
                        f"at line {line}. A cell test may not skip "
                        f"unconditionally: the three states are ENFORCED, "
                        f"WAIVED (strict xfail) and NA (asserted "
                        f"precondition), and a skip nothing can switch off "
                        f"means the cell never runs on any host")
            if calls and not callable(
                    getattr(mod, "matrix_skip_precondition", None)):
                problems.append(
                    f"dimension {dim}: cell test {func} skips at line(s) "
                    f"{[line for line, _ in calls]} but the module exports no "
                    f"matrix_skip_precondition() — a guarded skip is only "
                    f"admissible while the module states, live and per cell, "
                    f"which resource it could not reach")

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
    """Emit the split so a CI reader gets the number without reading the code.

    ENFORCED is reported BROKEN DOWN, never as one figure. A single
    ``ENFORCED=61`` is what let dimension 8's 45 substituted cells travel as
    enforcement of the gates they name; the caveat existed, in that module's
    docstring, and this line is where it stopped existing.
    """
    census = state_census()
    subs = substitution_census()
    lines = []
    for dim in DIMENSIONS:
        per = [v for (s, d), v in census.items() if d == dim]
        buckets = [v for (s, d), v in subs.items() if d == dim]
        lines.append(
            f"d{dim} {DIMENSION_NAMES[dim]}: "
            f"ENFORCED={per.count('ENFORCED')}"
            f"(own={buckets.count(SUB.OWN_MECHANISM)},"
            f"substituted={buckets.count(SUB.SUBSTITUTED)},"
            f"undeclared={buckets.count(SUB.UNDECLARED_BUCKET)}) "
            f"WAIVED={per.count('WAIVED')} "
            f"NA={per.count('NA')}")
    totals = {s: sum(1 for v in census.values() if v == s) for s in VALID_STATES}
    split = {b: sum(1 for v in subs.values() if v == b) for b in SUB.BUCKETS}
    summary = (f"{len(census)} cells = {len(F.step_ids())} steps x "
               f"{len(DIMENSIONS)} dimensions; {totals}; "
               f"ENFORCED splits {split}")
    record_property("matrix_63x8_census", summary)
    record_property("matrix_63x8_per_dimension", " | ".join(lines))
    assert len(census) == expected_cells(), summary


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
STATE_EXPECTS_OUTCOME: Dict[str, str] = {
    "ENFORCED": "passed",
    "WAIVED": "xfailed",
    "NA": "passed",
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


def _domain_progress(scope: str, completed: int, total: int) -> None:
    """Emit one finite semantic checkpoint when the landing plugin is loaded."""
    plugin = sys.modules.get("_pytest_progress_plugin")
    progress = getattr(plugin, "domain_progress", None)
    if progress is not None:
        progress(scope, completed, total)


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


def _run_outcome_reports(
        paths: Tuple[Path, ...],
        cwd: Optional[Path] = None) -> Dict[str, List[Dict]]:
    """``{nodeid: [raw phase reports]}`` from really RUNNING ``paths``.

    ONE SUBPROCESS PER PATH, and that is load-bearing rather than tidy. See
    Each thread launches a SEPARATE ``pytest_per_file_junit.py`` process.  That
    process owns its own subreaper, semantic-progress sidecar and descendant
    census.  Calling the driver's private supervisor directly from these
    threads would be wrong: its active-job slot and ``waitpid(-1)`` ownership
    are process-global, so sibling module sessions could reap or kill each
    other.

    CONCURRENT, at the width ``_outcome_worker_count`` derives, and that is
    load-bearing too: the subprocesses are independent by construction — each
    gets its own scratch dir, its own manifest path and its own env — so the
    only thing sequence was buying was serial wall time inside one test item.
    Nothing about WHAT is measured changes: the same modules, the same command,
    the same manifests, and the merge below still walks ``paths`` in order so
    a collision names the same pair whichever module happened to finish first.

    Unlike :func:`collect_items` this does NOT assert ``returncode == 0``: a
    non-zero exit is the normal, expected result of a suite that is reporting
    findings, and demanding zero here would make this instrument unable to
    observe the very thing it exists to observe. What IS asserted is that the
    manifest was written and is non-empty — PER MODULE now, which is stricter
    than before: one module contributing nothing used to be invisible behind
    the seven that did.

    A nodeid observed twice is refused rather than merged. Two modules cannot
    own the same nodeid, so a collision means the merge is losing reports, and
    a silently-lost report is a cell that reads outcome-less — the shape this
    file exists to refuse.
    """
    assert paths, "no module paths given to the outcome run"
    _width = _outcome_worker_count(len(paths), _outcome_worker_cap())
    per_path: Dict[Path, Dict[str, List[Dict]]] = {}
    completed_paths = 0
    for start in range(0, len(paths), _width):
        wave = paths[start:start + _width]
        relay_queue: queue.Queue = queue.Queue()
        with ThreadPoolExecutor(max_workers=len(wave)) as pool:
            # `_width` is diagnostic only. It changes no liveness rule.
            futures = [pool.submit(
                _run_one_module_outcome, p, cwd, len(wave), relay_queue)
                       for p in wave]
            # Inner supervisors have their own private sidecars. Relay their
            # VALIDATED monotonic scores back to this outer pytest item via a
            # Queue, then emit from this MAIN thread only. Worker-thread writes
            # would race the plugin's global sequence and could corrupt the
            # outer protocol. A finite total prevents an infinite heartbeat.
            relay_seen: Dict[Path, int] = {path: 0 for path in wave}
            while not all(future.done() for future in futures):
                try:
                    path, score = relay_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                previous = relay_seen[path]
                assert previous < score <= _NESTED_PROGRESS_RELAY_TOTAL, (
                    f"invalid nested semantic relay for {path.name}: "
                    f"{previous} -> {score}")
                for completed in range(previous + 1, score + 1):
                    _domain_progress(
                        f"matrix-outcome-child:{path.name}", completed,
                        _NESTED_PROGRESS_RELAY_TOTAL)
                relay_seen[path] = score
            while True:
                try:
                    path, score = relay_queue.get_nowait()
                except queue.Empty:
                    break
                previous = relay_seen[path]
                assert previous < score <= _NESTED_PROGRESS_RELAY_TOTAL, (
                    f"invalid nested semantic relay for {path.name}: "
                    f"{previous} -> {score}")
                for completed in range(previous + 1, score + 1):
                    _domain_progress(
                        f"matrix-outcome-child:{path.name}", completed,
                        _NESTED_PROGRESS_RELAY_TOTAL)
                relay_seen[path] = score
            # Read results in declaration order after every process in this
            # wave ended, so the same first error wins on both arms.
            first: Optional[BaseException] = None
            for path, future in zip(wave, futures):
                try:
                    per_path[path] = future.result()
                    completed_paths += 1
                    _domain_progress(
                        "matrix-outcome-modules", completed_paths, len(paths))
                except BaseException as exc:
                    if first is None:
                        first = exc
            if first is not None:
                raise first
    merged: Dict[str, List[Dict]] = {}
    for path in paths:
        for nodeid, reports in per_path[path].items():
            assert nodeid not in merged, (
                f"nodeid {nodeid!r} was reported by more than one module run; "
                f"merging would drop one of them and the cell it belongs to "
                f"would read outcome-less")
            merged[nodeid] = reports
    assert merged, (
        f"the outcome runs recorded ZERO test reports across {len(paths)} "
        f"module(s) — an empty second axis passes every join vacuously.")
    return merged


def _run_one_module_outcome(path: Path,
                            cwd: Optional[Path],
                            width: int = 1,
                            progress_queue=None) -> Dict[str, List[Dict]]:
    """The single-module half of :func:`_run_outcome_reports`.

    ``--basetemp`` is REQUIRED, not tidiness, and it is what makes the
    concurrency in :func:`_run_outcome_reports` safe. pytest's default
    ``tmp_path`` root is a SHARED, numbered directory per user
    (``/tmp/pytest-of-<user>/pytest-<n>``) and each session garbage-collects
    the older numbers in it. Two sessions running at the same time therefore
    delete each other's ``tmp_path`` mid-run, and what that looks like is a
    wandering ``FileNotFoundError`` in whichever module lost — a red that
    belongs to no change and does not reproduce. Each module run gets its own
    root inside its own scratch dir, which is removed with it.
    """
    scratch = Path(tempfile.mkdtemp(prefix="matrix_cov_outcome_"))
    try:
        plugin = scratch / "matrix_cell_outcomes.py"
        plugin.write_text(_OUTCOME_PLUGIN, encoding="utf-8")
        out = scratch / "outcomes.json"
        selection = scratch / "selection.txt"
        selection.write_text(str(path) + "\n", encoding="utf-8")
        junit = scratch / "outcome-junit.xml"
        relay = scratch / "semantic-progress.relay"
        relay.touch(mode=0o600)
        env = dict(os.environ)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["MATRIX_CELL_OUTCOME_OUT"] = str(out)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(scratch)]
            + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        driver = TESTS_DIR.parent / "pytest_per_file_junit.py"
        cmd = [sys.executable, str(driver),
             "--selection", str(selection), "--junit", str(junit),
             "--aggregate-only", "--aggregate-stall-after",
             str(_OUTCOME_PROGRESS_STALL_S),
             "--progress-relay", str(relay),
             "--cwd", str(cwd or PLUGIN_ROOT), "--",
             sys.executable, "-m", "pytest", "-q", "--tb=no",
             "-p", "no:randomly", "-p", "no:cacheprovider",
             "-p", "matrix_cell_outcomes",
             "--basetemp", str(scratch / "pytest_tmp")]
        log = scratch / "driver.log"
        relay_offset = 0
        relay_tail = b""
        last_score = 0
        relay_error = ""

        def _publish_relay(*, final: bool = False) -> None:
            nonlocal relay_offset, relay_tail, last_score, relay_error
            if relay_error:
                return
            try:
                size = relay.stat().st_size
                if size < relay_offset:
                    relay_error = "relay truncated"
                    return
                with relay.open("rb") as relay_file:
                    relay_file.seek(relay_offset)
                    chunk = relay_file.read()
            except OSError as exc:
                relay_error = f"relay unreadable: {exc}"
                return
            relay_offset += len(chunk)
            records = (relay_tail + chunk).split(b"\n")
            relay_tail = records.pop()
            for payload in records:
                if not payload:
                    relay_error = "empty relay score"
                    return
                try:
                    score = int(payload.decode("ascii"))
                except (UnicodeDecodeError, ValueError):
                    relay_error = f"malformed relay score {payload!r}"
                    return
                if not last_score < score <= _NESTED_PROGRESS_RELAY_TOTAL:
                    relay_error = f"non-monotonic relay {last_score} -> {score}"
                    return
                last_score = score
                if progress_queue is not None:
                    progress_queue.put((path, score))
            if final and relay_tail:
                relay_error = "truncated final relay score"

        with log.open("w+", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                cmd, cwd=str(cwd or PLUGIN_ROOT), stdout=log_file,
                stderr=subprocess.STDOUT, text=True, env=env)
            while proc.poll() is None:
                _publish_relay()
                time.sleep(0.1)
            _publish_relay(final=True)
            log_file.flush()
            log_file.seek(0)
            diagnostic = log_file.read()
        assert not relay_error, (
            f"the semantic relay for {path.name} is invalid: {relay_error}\n"
            f"{diagnostic[-5000:]}")
        assert proc.returncode in (0, 1), (
            f"the outcome run for {path.name} produced no complete semantic "
            f"pytest lifecycle record (driver rc={proc.returncode}, "
            f"{width}-way concurrent). Output and CPU activity are not "
            f"progress; only validated collection/test transitions renew the "
            f"stall window.\n{diagnostic[-5000:]}"
        )
        assert junit.is_file(), (
            f"the semantic supervisor for {path.name} returned "
            f"rc={proc.returncode} without its JUnit attestation.\n"
            f"{diagnostic[-5000:]}"
        )
        assert out.is_file(), (
            f"the outcome run for {path.name} produced no manifest "
            f"(rc={proc.returncode}); every cell it owns would look "
            f"outcome-less and this file's second axis would be measuring "
            f"nothing.\n"
            f"diagnostic tail:\n{diagnostic[-5000:]}"
        )
        rows = json.loads(out.read_text(encoding="utf-8"))
        assert rows, (
            f"the outcome run for {path.name} recorded ZERO test reports "
            f"(rc={proc.returncode}) — an empty second axis passes every join "
            f"vacuously.\ndiagnostic tail:\n{diagnostic[-5000:]}"
        )
        if proc.returncode == 1:
            represented_red = any(
                _reduce_outcome(reports) in {"failed", "error", "xpassed"}
                for reports in rows.values())
            assert represented_red, (
                f"the outcome run for {path.name} exited rc=1 but every raw "
                "test report is non-red. This is an unrepresented session-"
                "level refusal, not cell evidence, so the census is "
                f"NORECORD.\n{diagnostic[-5000:]}")
        return rows
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress(
        monkeypatch, tmp_path):
    """Completed pytest items, not elapsed wall time, keep the child alive."""
    old_fixed_bound = 0.45
    monkeypatch.setattr(
        sys.modules[__name__], "_OUTCOME_PROGRESS_STALL_S", old_fixed_bound)
    paths = tuple(tmp_path / f"test_nested_{i}.py" for i in range(4))
    paths[0].write_text(
        "import time\n" + "\n".join(
            f"def test_progress_{i}():\n    time.sleep(0.45)"
            for i in range(12)) + "\n",
        encoding="utf-8",
    )
    for path in paths[1:]:
        path.write_text(
            "import time\n\ndef test_fast():\n    time.sleep(0.05)\n",
            encoding="utf-8",
        )

    started = time.monotonic()
    reports = _run_outcome_reports(paths, cwd=tmp_path)
    elapsed = time.monotonic() - started

    assert elapsed > old_fixed_bound, (
        f"the nested run lasted only {elapsed:.2f}s, so it did not prove that "
        f"work may cross the old {old_fixed_bound}s wall bound")
    expected = {
        *(f"{paths[0].name}::test_progress_{i}" for i in range(12)),
        *(f"{path.name}::test_fast" for path in paths[1:]),
    }
    assert set(reports) == expected
    assert all(_reduce_outcome(rows) == "passed"
               for rows in reports.values())


def test_nested_outcome_chatty_import_without_pytest_events_fails_closed(
        monkeypatch, tmp_path):
    """Captured chatter cannot impersonate a completed pytest transition."""
    monkeypatch.setattr(
        sys.modules[__name__], "_OUTCOME_PROGRESS_STALL_S", 0.45)
    monkeypatch.setenv("PYTEST_ADDOPTS", "-s")
    path = tmp_path / "test_chatty_import.py"
    path.write_text(
        "import time\n"
        "deadline = time.monotonic() + 6\n"
        "while time.monotonic() < deadline:\n"
        "    print('CHATTY_SENTINEL', flush=True)\n"
        "    time.sleep(0.02)\n\n"
        "def test_after_import():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    started = time.monotonic()
    with pytest.raises(AssertionError) as caught:
        _run_one_module_outcome(path, tmp_path)
    elapsed = time.monotonic() - started
    message = str(caught.value)
    assert elapsed < 6, elapsed
    assert "WATCHDOG_STALLED:" in message
    assert "validated pytest lifecycle progress" in message
    assert "CHATTY_SENTINEL" in message


def test_nested_outcome_refuses_unrepresented_session_level_red(tmp_path):
    """A green raw manifest cannot erase a sessionfinish refusal."""
    (tmp_path / "conftest.py").write_text(
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    session.exitstatus = 1\n",
        encoding="utf-8",
    )
    path = tmp_path / "test_green.py"
    path.write_text("def test_green():\n    assert True\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="unrepresented session-level"):
        _run_one_module_outcome(path, tmp_path)


#: Seconds each synthetic module sleeps in the concurrency probe below. Small
#: enough that the probe costs one wave of it, large enough to dominate the
#: interpreter start it is measured against.
_PROBE_SLEEP_S = 2

_PROBE_MODULE = "import time\n\n\ndef test_probe():\n    time.sleep(%d)\n"


def test_the_outcome_loop_cannot_outlive_the_pytest_harness(tmp_path):
    """A stalled child reports before the harness; progressing work may finish.

    The historical node id is intentionally retained for base/candidate
    differential stability.  The old implementation multiplied a guessed
    per-process wall timeout by a wave count.  That estimate was the defect:
    healthy work crossed 60 s under parallel Landing Gate load.  The current
    contract instead proves two independent facts:

    * a child with no validated pytest lifecycle progress is named before the
      enclosing ordinary harness can kill the whole session;
    * the real loop actually uses its declared concurrency.  A sequential
      implementation cannot finish the synthetic sleeps below their summed
      lower bound.

    There is deliberately no ``waves * seconds`` total-runtime assertion.  A
    module that keeps completing pytest lifecycle transitions is making
    measurable progress, regardless of how many wall-clock windows it needs.
    """
    import ci_harness_timeout_ceiling_check as CEIL

    repo_root = CEIL.find_repo_root(TESTS_DIR)
    harness = (CEIL.ci_harness_timeout_seconds(repo_root)
               if repo_root is not None else None)
    assert harness is not None, (
        f"CANNOT DETERMINE: no pytest harness bound could be read from "
        f"{repo_root} — and that is NOT this test passing. An unreadable bound "
        f"is a bound this test did not check against; recording it as green is "
        f"the could-not-look-scored-as-nothing-found shape the census campaign "
        f"exists to refuse.")

    per_call_ceiling = harness // CEIL.CEILING_DIVISOR
    assert _OUTCOME_PROGRESS_STALL_S <= per_call_ceiling, (
        f"one outcome process may make no pytest lifecycle progress for "
        f"{_OUTCOME_PROGRESS_STALL_S}s, above the ordinary landing lane's "
        f"{per_call_ceiling}s diagnostic window")
    n = len(dimension_module_paths())
    assert n, "no dimension modules found; the loop under test has no input"
    workers = _outcome_worker_count(n)

    probe = tmp_path / "probe"
    probe.mkdir()
    paths = tuple(probe / f"test_probe_{i}.py" for i in range(n))
    for path in paths:
        path.write_text(_PROBE_MODULE % _PROBE_SLEEP_S, encoding="utf-8")
    started = time.monotonic()
    reports = _run_outcome_reports(paths, cwd=probe)
    elapsed = time.monotonic() - started
    assert len(reports) == n, (
        f"the probe ran {n} module(s) and got {len(reports)} report(s) back; "
        f"a loop that drops a module measures nothing about the loop")
    sequential_floor = n * _PROBE_SLEEP_S
    assert elapsed < sequential_floor, (
        f"{n} module(s) sleeping {_PROBE_SLEEP_S}s each took {elapsed:.1f}s, "
        f"which is not under the {sequential_floor}s a SEQUENTIAL run must "
        f"spend sleeping alone. The configured pool width is {workers}, so "
        f"this says the parallel schedule is not the code that ran.")


def test_the_outcome_pool_waits_at_each_wave_boundary(monkeypatch, tmp_path):
    """A width without a barrier is the pre-fix work-conserving queue.

    When a light module finishes it starts a later heavy module while the
    current heavy one is still live, so the three measured-heavy dimensions
    overlap despite arithmetic that calls them separate waves. Drive the real
    scheduler with a cheap stand-in and prove no next-wave start precedes the
    last prior-wave finish.
    """
    paths = tuple(tmp_path / f"test_wave_{i}.py" for i in range(8))
    started: Dict[Path, float] = {}
    finished: Dict[Path, float] = {}

    def fake(path, _cwd, _width, _progress_queue=None):
        started[path] = time.monotonic()
        time.sleep(0.05)
        finished[path] = time.monotonic()
        return {f"{path.name}::test_probe": []}

    monkeypatch.setattr(sys.modules[__name__],
                        "_run_one_module_outcome", fake)
    reports = _run_outcome_reports(paths, cwd=tmp_path)
    assert len(reports) == len(paths)
    width = _outcome_worker_count(len(paths))
    for boundary in range(width, len(paths), width):
        prior = paths[boundary - width:boundary]
        following = paths[boundary:boundary + width]
        assert min(started[p] for p in following) >= max(
            finished[p] for p in prior), (
                f"wave beginning at {boundary} started before the preceding "
                f"{len(prior)} module(s) all finished")


@lru_cache(maxsize=1)
def cell_outcomes() -> Dict[Tuple[str, int], Tuple[str, ...]]:
    """``{(step, dim): (outcome, ...)}`` for every CELL item, live.

    Keyed exactly like :func:`collected_cells` and by the same rule — a
    parametrize id of exactly ``step<declared flow step id>`` — so the two
    axes are joinable cell for cell and a mismatch in either direction is
    visible rather than silently dropped.
    """
    return _cell_outcomes_from_reports(
        _run_outcome_reports(dimension_module_paths()),
        _file_to_dim(),
        {F.normalize_id(s) for s in F.step_ids()},
    )


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
    assert not dropped_red, (
        "the nested outcome run produced red test report(s) outside the "
        "matrix cell join. Its rc=1 is not completely represented by the "
        f"cell census, so this run is NORECORD: {dropped_red[:8]}")
    return {k: tuple(v) for k, v in out.items()}


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


@lru_cache(maxsize=1)
def enforcement_census() -> Dict[Tuple[str, int], CellVerdict]:
    """The two-axis census. THIS is the one to quote."""
    return _join_axes(state_census(), cell_outcomes())


def test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved():
    """Anti-starvation guard for the second axis, mirroring the first's.

    ``test_collection_is_real_and_not_starved`` protects the state axis. This
    protects the outcome axis, and it matters more: a collection that returns
    nothing makes the census obviously absurd (0 cells), whereas an outcome
    run that returns nothing would leave the state census intact and every
    contradiction check vacuously satisfied — a green "no red cells found"
    produced by having looked at no cells. That is the exact failure shape the
    campaign was opened to remove.
    """
    outcomes = cell_outcomes()
    states = state_census()
    assert len(outcomes) == expected_cells(), (
        f"the outcome run observed {len(outcomes)} of {expected_cells()} "
        f"cells; the second axis is starved and cannot contradict anything")
    missing = sorted(set(states) - set(outcomes))
    extra = sorted(set(outcomes) - set(states))
    assert not missing and not extra, (
        f"the two axes do not describe the same grid — "
        f"{len(missing)} cell(s) have a state but no observed outcome "
        f"{missing[:8]}; {len(extra)} have an outcome but no state {extra[:8]}")
    for key, obs in sorted(outcomes.items()):
        assert obs, f"{key}: observed outcome tuple is empty"
        assert all(o != "unrun" for o in obs), (
            f"{key}: pytest reported the item but it never ran ({obs})")


def test_no_cell_is_counted_enforced_while_its_predicate_is_red():
    """A red predicate may not be counted as proof of enforcement.

    This is the whole of ORGANIC-20260808. Before it existed the census said
    ENFORCED 481 while 26 of those cells were failing, and the number was
    reproducible, published and quotable.

    Two doors out of a failure here, both already built:
      * fix the cell's predicate (or the defect it found), or
      * WAIVE it — registry entry + evidence-backed reason + ``strict=True`` —
        which the three cross-checks above then hold you to.
    Editing this test is not a third door.
    """
    joined = enforcement_census()
    counts = enforcement_counter(joined)
    broken = sorted((k for k, v in joined.items() if not v.agrees),
                    key=lambda k: (k[1], k[0]))
    if broken:
        #: Outcomes that mean THE PREDICATE NEVER GAVE AN ANSWER, as opposed to
        #: giving a red one. `agrees` folds both into "contradicted" — correctly,
        #: since neither is evidence of enforcement — but the two have different
        #: causes and different owners, and the message must not conflate them.
        #:
        #: MEASURED (vibe-ic#1348): the same tree, same commit, reported 16
        #: contradictions on a host with every repo dependency installed and 54
        #: in a container missing `pyyaml`. The extra 38 were predicates that
        #: could not RUN. A reader given one number cannot tell a repo defect
        #: from a missing dependency, and "16" is not reproducible without
        #: knowing which host produced it.
        _UNMEASURED = ("error", "unrun", "skipped")
        measured, unmeasured = [], []
        for sid, dim in broken:
            verdict = joined[(sid, dim)]
            line = (
                f"  {sid}/d{dim} ({DIMENSION_NAMES[dim]}): reported "
                f"{verdict.state} — which claims its predicate "
                f"{STATE_EXPECTS_OUTCOME[verdict.state]} — but the live run "
                f"says {', '.join(verdict.outcomes) or '<never observed>'}")
            (unmeasured if (not verdict.outcomes
                            or all(o in _UNMEASURED for o in verdict.outcomes))
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
        pytest.fail(
            f"{len(broken)} of {len(joined)} cells are reported in a state "
            f"their own live predicate contradicts "
            f"({len(measured)} measured red, {len(unmeasured)} not measured):\n"
            + "\n".join(lines)
            + f"\n\nSTATE-ONLY census (what used to be published): "
              f"{state_only}"
            + f"\nTWO-AXIS census (what is true): {counts}"
            + "\n\nA cell in this list is counted as coverage and is not "
              "covering anything. Fix the predicate or waive it on the "
              "record; see matrix_63x8/README.md, 'The three-state rule'.")


def test_every_skipping_cell_names_the_resource_it_could_not_reach():
    """A ``-SKIPPED`` cell is DECLARED by its own module, live, in both
    directions.

    This is the guard that lets clause (3) of the test above stop banning the
    call outright. The ban was a static, blunt "no skip anywhere"; this is a
    live, per-cell equality between what the run DID and what the module SAYS
    it would do, so a module cannot satisfy it with a constant:

      * ``matrix_skip_precondition`` that always answers -> reddens on the
        ~457 cells the run did not skip;
      * one that never answers -> reddens on the ones it did;
      * one that answers for the wrong cells -> reddens on both sides.

    A dimension whose cells never skip does not need the function at all, and
    is not asked for it — the requirement follows the observed behaviour, not
    a list somebody has to remember to update.

    MEASURED at the time of writing: 47 of 504 cells report ``skipped``, 46 in
    dimension 3 and 1 in dimension 7, and both of those modules reach their
    skip through ``corpus_root() is None`` — the published cells left this
    repository (vibe-ic#1703) and no pointer to a clone was offered here.

    IT SITS WITH THE OTHER CENSUS CONSUMERS, not beside the NA test whose
    clause it discharges, because it reads :func:`enforcement_census` and the
    first consumer of that pays for the nested outcome run — roughly two and a
    half minutes that belongs in this section of the file rather than in the
    middle of the static checks.

    IT COSTS ~20 s, and where that goes is measured, not guessed: dimension
    7's ``matrix_skip_precondition`` reaches ``G.findings_for``, whose first
    call builds the AST index the whole module shares (20.5 s over the 63
    cells; 19.7 s with the four conditions reordered cheapest-first, so the
    reorder was measured and dropped).

    ONE NEIGHBOUR IS FLAKY AND IT IS NOT THIS ONE.
    ``test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress``
    drives 12 child tests that each sleep exactly its 0.45 s forward-progress
    stall bound, so on a busy host it is killed as hung. MEASURED here, that
    test ALONE, ten runs per tree: 4/10 red on unmodified ``origin/main`` and
    3/10 red on this branch. Whole-file runs correlate with the branch only
    because the branch's file runs 18 s longer; the isolated rate is where the
    attribution lives, and it says pre-existing. Do not charge it to a diff
    without re-running it alone first.
    """
    census = enforcement_census()
    problems: List[str] = []
    skipped_cells, declared_cells = [], []
    for (sid, dim), verdict in sorted(census.items(), key=lambda kv: kv[0][1]):
        mod = dimension_modules()[dim]
        fn = getattr(mod, "matrix_skip_precondition", None)
        did_skip = bool(verdict.outcomes) and all(
            o == "skipped" for o in verdict.outcomes)
        if did_skip:
            skipped_cells.append(f"{sid}/d{dim}")
        if not callable(fn):
            if did_skip:
                problems.append(
                    f"{sid}/d{dim}: the live run skipped this cell but "
                    f"dimension {dim} exports no matrix_skip_precondition() — "
                    f"a cell that declined to run must name the resource it "
                    f"could not reach")
            continue
        says = (fn(sid) or "").strip()
        if says:
            declared_cells.append(f"{sid}/d{dim}")
        if did_skip and not says:
            problems.append(
                f"{sid}/d{dim}: the live run skipped this cell "
                f"({verdict.label}) but matrix_skip_precondition() returned "
                f"{says!r} — an undeclared skip is silence, and silence is "
                f"what the second axis exists to refuse")
        if says and not did_skip:
            problems.append(
                f"{sid}/d{dim}: matrix_skip_precondition() claims this cell "
                f"declines to run ({says!r}) but the live run reports "
                f"{verdict.outcomes or ('<never observed>',)} — the module's "
                f"account of its own silence is wrong in the direction that "
                f"would let a real skip hide behind a standing excuse")
    assert not problems, (
        f"{len(problems)} skip-declaration problem(s) over {len(census)} "
        f"cells (live-skipped {len(skipped_cells)}: {skipped_cells}; declared "
        f"{len(declared_cells)}: {declared_cells}):\n  - "
        + "\n  - ".join(problems))


def test_the_enforcement_census_is_reported_for_humans(record_property):
    """Emit the TWO-AXIS split, so the quotable number is the honest one."""
    joined = enforcement_census()
    counts = enforcement_counter(joined)
    lines = []
    for dim in DIMENSIONS:
        per = [v.label for (s, d), v in joined.items() if d == dim]
        lines.append(f"d{dim} {DIMENSION_NAMES[dim]}: "
                     + " ".join(f"{lab}={per.count(lab)}"
                                for lab in sorted(set(per))))
    summary = (f"{len(joined)} cells = {len(F.step_ids())} steps x "
               f"{len(DIMENSIONS)} dimensions; {counts}")
    record_property("matrix_63x8_enforcement_census", summary)
    record_property("matrix_63x8_enforcement_per_dimension", " | ".join(lines))
    assert len(joined) == expected_cells(), summary
    assert sum(counts.values()) == expected_cells(), counts


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


def test_the_second_axis_downgrades_a_red_cell_that_the_state_axis_counts():
    """The mutation control for this whole section.

    Runs a synthetic module whose three cells have KNOWN outcomes, then joins
    them against a state census that calls two of them ENFORCED — exactly the
    situation the state axis cannot see. The state axis reports ENFORCED 2.
    The joined census must report ENFORCED 1 and name the other.

    Without this, `test_no_cell_is_counted_enforced_while_its_predicate_is_red`
    would be a test whose green could mean "no contradictions" or "the
    instrument cannot detect a contradiction", and those are not the same
    fact.
    """
    scratch = Path(tempfile.mkdtemp(prefix="matrix_cov_axis_control_"))
    try:
        mod = scratch / "test_matrix_d99_synthetic_cells.py"
        mod.write_text(_SYNTHETIC_CELL_MODULE, encoding="utf-8")
        reports = _run_outcome_reports((mod,), cwd=scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    observed = {}
    for nodeid, reps in reports.items():
        if "[" not in nodeid:
            continue
        observed[nodeid.rsplit("[", 1)[1].rstrip("]")] = _reduce_outcome(reps)
    assert observed == {
        "stepGREEN": "passed",
        "stepRED": "failed",
        "stepWAIVED": "xfailed",
    }, (f"the outcome instrument cannot tell a passing cell from a failing "
        f"one on a module whose outcomes are known by construction: "
        f"{observed}")

    states = {("GREEN", 99): "ENFORCED",
              ("RED", 99): "ENFORCED",
              ("WAIVED", 99): "WAIVED"}
    outcomes = {("GREEN", 99): ("passed",),
                ("RED", 99): ("failed",),
                ("WAIVED", 99): ("xfailed",)}

    # This is the defect, reproduced in miniature: the state axis alone counts
    # the red cell as enforcing.
    assert sum(1 for v in states.values() if v == "ENFORCED") == 2

    joined = _join_axes(states, outcomes)
    assert joined[("GREEN", 99)].agrees
    assert joined[("WAIVED", 99)].agrees
    assert not joined[("RED", 99)].agrees, (
        "a cell configured ENFORCED whose predicate FAILED was still reported "
        "as enforcing — this is the defect ORGANIC-20260808 named")

    counts = enforcement_counter(joined)
    assert counts.get("ENFORCED") == 1, counts
    assert counts.get("ENFORCED-CONTRADICTED") == 1, counts
    assert counts.get("WAIVED") == 1, counts

    # And an unobserved cell is a contradiction, not a pass: the second axis
    # must not be satisfiable by having looked at nothing.
    starved = _join_axes({("GONE", 99): "ENFORCED"}, {})
    assert not starved[("GONE", 99)].agrees
    assert starved[("GONE", 99)].label == "ENFORCED-CONTRADICTED"


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
