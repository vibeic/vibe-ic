"""`reports/spare_cell_coverage.json` has exactly one writer, and it is the
program step 18 declares.

WHAT WAS DECIDED, AND WHY IT IS A TEST
======================================
Two programs wrote `reports/spare_cell_coverage.json`:

  * `spare_cell_coverage_check` — the program step 18 of
    `flow/phase1_phase2_phase3.yaml` names in its `programs:` list, for the
    path that same step declares in `required_outputs`;
  * `phase3_one_shot_runner` — which emitted a "convenience summary" at the
    same path from inside the PnR step.

The decision (`docs/decisions/2026-08-22-spare-cell-coverage-declaring-producer.md`)
is that the checker is the declaring producer and the runner's write is
removed. This module is the guard that keeps it removed, plus the guard on the
half of the defect that removing it would otherwise have hidden.

WHY A SECOND WRITER IS NOT COSMETIC HERE
========================================
`benchmark_verify_report` Pillar 6 grades this literal path and reads exactly
one field from it, `status`. It cannot tell the writers apart, so the
sign-off verdict was whichever writer ran last. And the two verdicts were not
the same verdict: the runner graded `actual_density` against the RUN'S OWN
configured target and called a spare set distributed at more than one distinct
position, while the gate applies a fixed 0.02 floor and requires distinct
positions >= half the spare count. Three plans measured PASS at the runner and
FAIL at the gate:

    self-target 0.005, met                 runner PASS / gate FAIL
    200 spares on 2 distinct positions     runner PASS / gate FAIL
    0 spares, self-target 0.0              runner PASS / gate FAIL

MEASURED, BEFORE THE REMOVAL
============================
The runner's write never survived a single run. Its payload marker
`"spare_cell_coverage (runner-emit)"` appeared in NO published artefact — of
the 30 published copies of `spare_cell_coverage.json` under `benchmark-data/`,
all 30 carry `"program": "spare_cell_coverage_check"`. The two published runs
that carry a `write_ledger.json` record the path as a declared output with
`producer: null` and `producer_confidence: "unwitnessed"`, at an mtime 48.3s
and 86.2s AFTER the `spare_cells.json` the runner writes in the same `try`
block microseconds earlier. The checker ran later and clobbered it every time.

THE HALF THAT REMOVING THE WRITE WOULD HAVE HIDDEN
==================================================
`spare_cell_coverage_check.audit()` READ the path it writes, as a
"runner-emitted coverage summary", and PREFERRED that file's
`actual_density` over the `spare_cells.json` in front of it. The runner's
clobber was the only thing keeping that read fresh: with the runner writing
first each run, the checker read a current number and the bug was invisible.
Remove the runner's write alone and the checker reads its OWN previous
verdict, on every re-run, forever. Measured on one project directory before
the fix:

    RUN 1  spare_cells.json count=203 actual=0.020022  -> rc=0 PASS 0.020022
    RUN 2  spare_cells.json count=5   actual=0.000493  -> rc=0 PASS 0.020022
    RUN 2 with the report deleted first                -> rc=1 FAIL 0.000493

RUN 2 is a design 40x under the readiness floor being signed off PASS on a
density from the previous run, with the contradicting `"count": 5` in the same
file. That is why the clobber and the self-read had to land together, and why
`test_the_checker_does_not_read_the_path_it_writes` is in this module and not
a separate one.

WHAT THIS MODULE DOES NOT DO
============================
It does not implement the general rule "no path declared by one step may be
written by another step's program". That rule is right and it is a different
row: its blast radius over the flow's 67 output-declaring steps has not been
measured here, and a rule that reddens paths nobody has decided about would be
a worse artefact than the one red cell this replaces. The scanner below is
general; only this one path is asserted on.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

from matrix_63x8 import flowref as F

DECLARED_PATH = "reports/spare_cell_coverage.json"
DECLARING_STEP = "18"
DECLARING_PRODUCER = "spare_cell_coverage_check"

PROGRAMS = Path(__file__).resolve().parent.parent

# A call that puts bytes on disk. `.open` is included and then filtered on its
# mode argument, because `open(p)` is a read and `open(p, "w")` is not.
_WRITE_ATTRS = {"write_text", "write_bytes", "open"}


# ──────────────────────────────────────────────────────────────────────
# The scanner
# ──────────────────────────────────────────────────────────────────────
def path_tail(node: ast.AST) -> Optional[str]:
    """Render ``"a/b/c"`` from ``X / "a" / "b/c"`` or from a bare string.

    Returns None for anything whose trailing components are not string
    literals — a computed path is not something this scanner can claim to
    have read, and it says so by declining rather than by guessing.
    """
    parts: List[str] = []
    cur = node
    while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
        right = cur.right
        if not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
            return None
        parts.append(right.value)
        cur = cur.left
    if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
        parts.append(cur.value)
    if not parts:
        return None
    parts.reverse()
    return "/".join(p.strip("/") for p in parts if p.strip("/"))


def _targets(node: ast.AST, want: str) -> bool:
    tail = path_tail(node)
    return bool(tail) and tail.endswith(want)


def _is_write_mode(call: ast.Call) -> bool:
    """`.open(...)` is a write only when its mode says so."""
    args = list(call.args) + [kw.value for kw in call.keywords
                              if kw.arg == "mode"]
    for a in args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            if any(c in a.value for c in "wxa+"):
                return True
    return False


def writers_of(source: str, want: str) -> bool:
    """True iff `source` contains a call that WRITES a path ending in `want`.

    Recognises three shapes, all of which occur in this plugin:
      1. ``p = <project> / "reports" / "x.json"`` then ``p.write_text(...)``
      2. ``(<project> / "reports" / "x.json").write_text(...)``
      3. ``helper.write_text(<project> / "reports" / "x.json", data)``
         — the atomic-artefact helper `_atomic_artefact.write_text`.
      4. the builtin ``open(<project> / "reports" / "x.json", "w")``.
    A read (`_load_json(p)`, `p.read_text()`, `open(p)`) is NOT a write, which
    is what keeps `benchmark_verify_report` — a legitimate CONSUMER of this
    path — out of the writer set. `.open()` and `open()` are separated from
    reads by their MODE argument, not by their name.
    """
    tree = ast.parse(source)
    bound: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            if value is not None and _targets(value, want):
                for t in targets:
                    if isinstance(t, ast.Name):
                        bound.add(t.id)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # shape 4 — the builtin `open(path, "w")`, which is a Name call and
        # would otherwise slip past the attribute test below.
        if isinstance(func, ast.Name) and func.id == "open":
            if (node.args and _targets(node.args[0], want)
                    and _is_write_mode(node)):
                return True
            if (node.args and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in bound and _is_write_mode(node)):
                return True
            continue
        if not isinstance(func, ast.Attribute) or func.attr not in _WRITE_ATTRS:
            continue
        if func.attr == "open" and not _is_write_mode(node):
            continue
        recv = func.value
        # shapes 1 and 2 — the receiver is the path
        if isinstance(recv, ast.Name) and recv.id in bound:
            return True
        if _targets(recv, want):
            return True
        # shape 3 — the path is the first argument of a write helper
        if node.args and _targets(node.args[0], want):
            return True
    return False


def scan_plugin_writers(want: str) -> Dict[str, Path]:
    """``{module basename: path}`` for every non-test program that writes
    `want`. Discovered, not listed: a new helper is in scope the day it is
    added."""
    found: Dict[str, Path] = {}
    for py in sorted(PROGRAMS.rglob("*.py")):
        if "tests" in py.relative_to(PROGRAMS).parts:
            continue
        try:
            src = py.read_text(encoding="utf-8")
        except Exception:
            continue
        if want.rsplit("/", 1)[-1] not in src:
            continue
        try:
            if writers_of(src, want):
                found[py.stem] = py
        except SyntaxError:  # pragma: no cover - a program that will not parse
            continue
    return found


# ──────────────────────────────────────────────────────────────────────
# L1 — the decision, over the shipped tree
# ──────────────────────────────────────────────────────────────────────
def test_exactly_one_program_writes_the_declared_report():
    """RED the moment a second writer of this path lands."""
    writers = scan_plugin_writers(DECLARED_PATH)
    assert sorted(writers) == [DECLARING_PRODUCER], (
        f"{DECLARED_PATH} is step {DECLARING_STEP}'s declared required_output "
        f"and only {DECLARING_PRODUCER} may write it; found writers "
        f"{sorted(writers)}"
    )


def test_the_flow_still_names_that_producer_for_that_path():
    """The decision is anchored in the yaml, not in this file.

    Both halves must hold, and each reddens on its own: step 18 declaring the
    path, and step 18 naming the checker. If step 18 stops declaring the path
    the assertion above is about nothing; if it stops naming the checker, the
    checker is no longer the declaring producer and this whole module is the
    wrong answer.
    """
    assert DECLARED_PATH in F.required_outputs(DECLARING_STEP)
    assert DECLARING_PRODUCER in F.declared_programs(DECLARING_STEP)


# ──────────────────────────────────────────────────────────────────────
# L2 — negative controls: the scanner is not passing over an empty set
# ──────────────────────────────────────────────────────────────────────
def test_the_scanner_finds_the_declaring_producer():
    """Without this, a scanner that matched NOTHING would satisfy L1.

    A single-writer assertion is exactly the shape that goes quietly green
    when its detector stops working: no writers found, no second writer, PASS.
    """
    writers = scan_plugin_writers(DECLARED_PATH)
    assert DECLARING_PRODUCER in writers, (
        "the scanner did not find the one writer that is definitely there — "
        "it is broken, and L1 above is meaningless")
    assert writers[DECLARING_PRODUCER].is_file()


def test_the_scanner_FIRES_on_the_removed_runner_write():
    """PAIRED GUARD: the exact code removed from `phase3_one_shot_runner`.

    Verbatim in shape from the deleted block — a local bound to the path, a
    `mkdir` on its parent, a `write_text`. If the scanner cannot see this it
    cannot see the write coming back.
    """
    removed = (
        "cov_path = project / \"reports\" / \"spare_cell_coverage.json\"\n"
        "cov_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "cov_path.write_text(json.dumps(coverage_payload) + \"\\n\")\n"
    )
    assert writers_of(removed, DECLARED_PATH)


def test_the_scanner_does_not_call_a_reader_a_writer():
    """`benchmark_verify_report` reads this path and must stay out of the set.

    A scanner that flagged every mention would make L1 red for a legitimate
    consumer, and the fix for that red would be to weaken L1.
    """
    reader = (
        "cov = _load_json(project / \"reports\" / \"spare_cell_coverage.json\")\n"
        "raw = (project / \"reports\" / \"spare_cell_coverage.json\").read_text()\n"
        "with open(project / \"reports\" / \"spare_cell_coverage.json\") as fh:\n"
        "    pass\n"
    )
    assert not writers_of(reader, DECLARED_PATH)
    assert "benchmark_verify_report" not in scan_plugin_writers(DECLARED_PATH)


def test_the_scanner_sees_a_write_through_the_builtin_open():
    """Shape 4, and its mode discrimination: `open(p, "w")` is a writer,
    `open(p)` is not. Without this leg a helper could reintroduce the second
    write through the plainest call in the language and go unseen."""
    writing = (
        "with open(project / \"reports\" / \"spare_cell_coverage.json\", \"w\") as fh:\n"
        "    json.dump(payload, fh)\n"
    )
    reading = (
        "with open(project / \"reports\" / \"spare_cell_coverage.json\") as fh:\n"
        "    payload = json.load(fh)\n"
    )
    assert writers_of(writing, DECLARED_PATH)
    assert not writers_of(reading, DECLARED_PATH)


def test_the_scanner_sees_a_write_through_the_atomic_helper():
    """Shape 3. The plugin's atomic-artefact helper takes the path as its
    first argument, so a writer that routes through it is still a writer."""
    via_helper = (
        "_aa.write_text(project / \"reports\" / \"spare_cell_coverage.json\",\n"
        "               json.dumps(payload))\n"
    )
    assert writers_of(via_helper, DECLARED_PATH)


# ──────────────────────────────────────────────────────────────────────
# L3 — the other half: the producer does not read its own output
# ──────────────────────────────────────────────────────────────────────
def _project(tmp_path, count: int, placed: int) -> Path:
    (tmp_path / "phase3/stage3/pnr").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(exist_ok=True)
    plan = {
        "count": count,
        "placed_cells_est": placed,
        "actual_density": round(count / placed, 6),
        "target_density": 0.02,
        "tied_off": True,
        "instances": [{"llx": i * 10, "lly": i * 10} for i in range(count)],
    }
    (tmp_path / "phase3/stage3/pnr/spare_cells.json").write_text(
        json.dumps(plan))
    return tmp_path


def _run_checker(project: Path):
    cp = subprocess.run(
        [sys.executable, str(PROGRAMS / "spare_cell_coverage_check.py"),
         str(project)],
        capture_output=True, text=True)
    report = json.loads(
        (project / "reports" / "spare_cell_coverage.json").read_text())
    return cp.returncode, report


def test_the_checker_does_not_read_the_path_it_writes(tmp_path):
    """The RUN 1 / RUN 2 measurement in this module's docstring, as a test.

    Two invocations against ONE project directory. The second sees a collapsed
    spare set and must fail on it, with its OWN density — not the one its
    first invocation left at the report path.
    """
    proj = _project(tmp_path, count=203, placed=10139)
    rc, first = _run_checker(proj)
    assert (rc, first["verdict"], first["actual_density"]) == (0, "PASS", 0.020022)

    _project(proj, count=5, placed=10139)          # the same tree, re-run
    rc, second = _run_checker(proj)
    assert second["count"] == 5
    assert second["actual_density"] == 0.000493, (
        "the checker took actual_density from a file it wrote itself: "
        f"{second['actual_density']!r} is the PREVIOUS run's number")
    assert (rc, second["verdict"]) == (1, "FAIL")


def test_the_verdict_does_not_depend_on_what_sits_at_the_output_path(tmp_path):
    """Same input, with and without a stale report present: same verdict.

    This is the general statement of the leg above, and it stays true for any
    stale content, not only the one value that happened to be measured.
    """
    proj = _project(tmp_path, count=5, placed=10139)
    (proj / "reports" / "spare_cell_coverage.json").write_text(json.dumps(
        {"program": "whatever", "verdict": "PASS", "status": "PASS",
         "actual_density": 0.99, "count": 99999}))
    rc_stale, stale = _run_checker(proj)

    (proj / "reports" / "spare_cell_coverage.json").unlink()
    rc_clean, clean = _run_checker(proj)

    assert (rc_stale, stale["verdict"], stale["actual_density"]) == \
           (rc_clean, clean["verdict"], clean["actual_density"])
    assert rc_clean == 1


def test_the_declared_report_carries_the_runners_measurement(tmp_path):
    """Removing the runner's write may not lose what it carried.

    The runner's summary held `placed_cells_est` and the measured `tie_off`
    evidence. Both now travel from `spare_cells.json` into the one file at the
    declared path, so the removal costs a reader nothing.
    """
    proj = _project(tmp_path, count=203, placed=10139)
    plan_p = proj / "phase3/stage3/pnr/spare_cells.json"
    plan = json.loads(plan_p.read_text())
    plan["tie_off"] = {"tied_off": True, "sinks": 203, "source": "openroad-log"}
    plan["target_density"] = 0.005          # the run's own, laxer, self-target
    plan_p.write_text(json.dumps(plan))

    _rc, report = _run_checker(proj)
    assert report["placed_cells_est"] == 10139
    assert report["tie_off"] == {"tied_off": True, "sinks": 203,
                                 "source": "openroad-log"}
    # The plan's own target is provenance and is kept apart from the gate
    # floor, so neither can be read as the other. This is the exact confusion
    # the removed runner summary shipped: it published the run's self-target
    # under the key the gate floor uses, and graded against it.
    assert report["plan_target_density"] == 0.005
    assert report["target_density"] == 0.02


# ──────────────────────────────────────────────────────────────────────
# L4 — the declared output is still PRODUCED, not merely single-writered
# ──────────────────────────────────────────────────────────────────────
# L1 asks "who may write this path". It cannot ask the other question, and
# the two are not the same: a path with exactly one permitted writer that
# nothing ever runs is single-writered and absent.
#
# That is not hypothetical — it is what the first cut of this decision did.
# Removing the runner's write left `spare_cell_coverage_check` as the sole
# writer, invoked only by step 18's gate clause. But `phase3_one_shot_runner`
# also runs `flow_compliance_check --strict` on its own output, and that
# grades `required_outputs` by PRESENCE. On a RUNNER-ONLY invocation — no
# orchestrator gate pass — nobody produced the file. MEASURED on a published
# tree carrying a real spare plan, the report being the only difference:
#
#   with it     ⊘ [PASS-VOIDED] Step 18: Spare-cell + ECO-prep insertion
#   without it  · [MISSING     ] Step 18: Spare-cell + ECO-prep insertion
#                  └─ required_outputs missing:
#                     ['reports/spare_cell_coverage.json'] (satisfied: 1/2 —
#                      the gate passed, but every declared output must be
#                      produced, not just one)
#
# The runner now INVOKES the declaring producer instead of formatting a rival
# payload, which is the shape step 8 already uses for `sdc_syntax_check`. L1
# stays green because the writing program is still the declared one.
RUNNER = "phase3_one_shot_runner"


def _programs_invoked_by(source: str) -> Set[str]:
    """Module stems for every ``"<name>.py"`` string literal in `source`.

    Deliberately PERMISSIVE — any `.py` literal counts, whether or not this
    scanner can prove it reaches a subprocess. A permissive reading can only
    make the assertion below easier to satisfy, so a false positive here
    cannot manufacture a pass for a path that genuinely has no producer,
    which is the only thing this leg claims.
    """
    return {n.value[:-3] for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.endswith(".py")}


def test_every_declared_output_of_step_18_is_produced_on_a_runner_only_run():
    """RED if step 18 declares an output nothing in the runner's own run
    produces — the regression that removing the second write introduced."""
    runner_src = (PROGRAMS / f"{RUNNER}.py").read_text(encoding="utf-8")
    reachable = {RUNNER} | _programs_invoked_by(runner_src)
    declared = F.required_outputs(DECLARING_STEP)
    assert declared, "step 18 declares no outputs — the flow loader is broken"
    checked: List[str] = []
    unresolved: List[str] = []
    for path in declared:
        # BASENAME, not the full declared path. `path_tail` declines on a
        # path built from a variable directory — the runner writes
        # `out_dir / "spare_cells.json"` — and a decline is the scanner
        # being honest, not a missing writer. Matching the basename widens
        # the writer set, which can only make the assertion below easier to
        # satisfy; the vacuity guard after the loop is what stops that
        # widening from turning into a free pass.
        writers = set(scan_plugin_writers(path.rsplit("/", 1)[-1]))
        if not writers:
            unresolved.append(path)
            continue
        checked.append(path)
        assert writers & reachable, (
            f"step {DECLARING_STEP} declares {path} but nothing the runner "
            f"runs produces it: its writers are {sorted(writers)}, and the "
            f"runner neither writes it nor invokes any of them. A runner-only "
            f"invocation leaves that declared output MISSING.")
    # NEVER VACUOUS on the path this module is about. If the scanner stops
    # resolving it, this leg has stopped asking its question and says so
    # rather than reporting a pass over an empty set.
    assert DECLARED_PATH in checked, (
        f"this leg never actually checked {DECLARED_PATH}; it resolved "
        f"{checked} and declined on {unresolved}")
    # And the fix for that must not be a relapse into a second writer.
    assert RUNNER not in scan_plugin_writers(DECLARED_PATH), (
        f"{RUNNER} produces {DECLARED_PATH} by WRITING it again, not by "
        f"invoking {DECLARING_PRODUCER}")


def test_that_leg_FIRES_when_the_runner_stops_invoking_the_producer():
    """PAIRED GUARD: without this, the leg above passes on any runner that
    happens to mention enough `.py` names."""
    runner_src = (PROGRAMS / f"{RUNNER}.py").read_text(encoding="utf-8")
    assert f'"{DECLARING_PRODUCER}.py"' in runner_src, (
        f"{RUNNER} no longer invokes {DECLARING_PRODUCER} by name — the leg "
        f"above is asserting over a shape that is gone")
    stripped = runner_src.replace(f'"{DECLARING_PRODUCER}.py"',
                                  '"_a_program_that_is_not_it.py"')
    reachable = {RUNNER} | _programs_invoked_by(stripped)
    writers = set(scan_plugin_writers(DECLARED_PATH))
    assert not (writers & reachable), (
        "the invocation was removed and the leg above would still have "
        "passed — it is not measuring what it claims")
