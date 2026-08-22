"""`reports/spare_cell_coverage.json` has ONE declaring producer.

Step 18 declares `spare_cell_coverage_check` as the producer of
`reports/spare_cell_coverage.json`. `phase3_one_shot_runner` wrote it too.
The two payloads graded the SAME run against DIFFERENT floors — the runner
against the run's own `--spare-density`, the gate against its fixed
readiness minimum — so one path carried two verdicts and whichever writer
ran last decided what `benchmark_verify_report` Pillar 6 read as `status`.
A run invoked with `--spare-density 0` published `status: PASS` with a zero
ECO budget.

These tests go RED if the second writer comes back, in either of the two
ways it can:

  1. SOMETHING ELSE WRITES THE PATH — a source-level scan over every
     program, so a third writer trips it too, not only the runner.
  2. SOMETHING WRITTEN AT THE PATH REACHES THE VERDICT — a behavioural
     check. The gate used to read its own output back and prefer its
     `actual_density` over the current plan's, so a re-run carried a stale
     density forward: 10 spares in 10000 cells reported
     `actual_density: 0.02` beside `count: 10` and exited 0.

docs/decisions/2026-08-22-spare-cell-coverage-declaring-producer.md
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import spare_cell_coverage_check as cov  # noqa: E402

PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
COV_SCRIPT = PROGRAMS / "spare_cell_coverage_check.py"
DECLARED_PATH = "reports/spare_cell_coverage.json"
DECLARING_PRODUCER = "spare_cell_coverage_check.py"


# ──────────────────────────────────────────────────────────────────
# 1) Only the declaring producer names the path as a write target
# ──────────────────────────────────────────────────────────────────
_WRITE_METHODS = {"write_text", "write_bytes", "writelines", "write",
                  "write_json", "replace", "rename"}
_WRITE_FUNCS = {"open"}                     # open(path, "w")
_WRITE_2ND_ARG = {"dump", "copy", "copy2", "copyfile", "move",
                  "write_text"}             # json.dump(obj, fh) / shutil.copy


def _mentions_path(node) -> bool:
    """True when this expression subtree builds the declared path."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and sub.value in (
                "spare_cell_coverage.json", DECLARED_PATH):
            return True
    return False


def _writes_the_declared_path(src: str) -> bool:
    """True when `src` writes through an expression that builds the path.

    READING the path is fine and is what several reports legitimately do
    (`benchmark_verify_report` grades Pillar 6 from it). Only a WRITE makes
    a second producer, so the path expression has to reach a write target,
    directly or through one assignment hop:

        cov_path = project / "reports" / "spare_cell_coverage.json"
        cov_path.write_text(...)                       <- offender
        (project / "reports" / "..." ).write_text(...) <- offender
        cov = _load_json(project / "reports" / "...")  <- reader, not a writer
    """
    tree = ast.parse(src)
    # one assignment hop: names bound to an expression that builds the path
    tainted = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            if not _mentions_path(node.value):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    tainted.add(t.id)

    def _is_path_expr(node) -> bool:
        if _mentions_path(node):
            return True
        return isinstance(node, ast.Name) and node.id in tainted

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # receiver.write_text(...) / receiver.replace(...)
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in _WRITE_METHODS and _is_path_expr(node.func.value):
                return True
            # json.dump(obj, fh) / shutil.copy(src, dst): the path is arg 2
            if node.func.attr in _WRITE_2ND_ARG and len(node.args) >= 2:
                if _is_path_expr(node.args[1]):
                    return True
        # open(path, "w")
        if isinstance(node.func, ast.Name) and node.func.id in _WRITE_FUNCS:
            if node.args and _is_path_expr(node.args[0]):
                mode = node.args[1] if len(node.args) > 1 else None
                if mode is None:
                    continue                    # open(p) -> read
                if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
                    if any(c in mode.value for c in "wax+"):
                        return True
                else:
                    return True                 # non-literal mode: look at it
    return False


def test_the_runner_does_not_write_the_gates_declared_output():
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    lines = [ln for ln in src.splitlines()
             if "spare_cell_coverage.json" in ln
             and not ln.lstrip().startswith("#")]
    assert lines == [], (
        "phase3_one_shot_runner names reports/spare_cell_coverage.json in "
        "non-comment code again; step 18 declares "
        "spare_cell_coverage_check as that path's producer and the runner's "
        "payload grades the run against its own --spare-density:\n  "
        + "\n  ".join(lines))


def test_no_program_but_the_declaring_one_writes_the_declared_path():
    offenders = []
    for py in sorted(PROGRAMS.glob("*.py")):
        if py.name == DECLARING_PRODUCER:
            continue
        try:
            src = py.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - unreadable file
            continue
        if "spare_cell_coverage.json" not in src:
            continue
        try:
            if _writes_the_declared_path(src):
                offenders.append(py.name)
        except SyntaxError:  # pragma: no cover - not our concern here
            continue
    assert offenders == [], (
        f"{DECLARED_PATH} has exactly one declaring producer "
        f"({DECLARING_PRODUCER}); these also write it: {offenders}")


# ──────────────────────────────────────────────────────────────────
# 2) Nothing at the declared path can reach the verdict
# ──────────────────────────────────────────────────────────────────
def _plan(count, placed, actual_density):
    return {
        "count": count,
        "placed_cells_est": placed,
        "target_density": 0.02,
        "actual_density": actual_density,
        "tied_off": True,
        "instances": [{"name": f"spare_{i}", "llx": 10 * i, "lly": 10 * i,
                       "keep": True} for i in range(count)],
    }


def _project(tmp_path, plan, planted=None):
    proj = tmp_path / "proj"
    (proj / "phase3" / "stage3" / "pnr").mkdir(parents=True, exist_ok=True)
    (proj / "reports").mkdir(parents=True, exist_ok=True)
    (proj / "phase3" / "stage3" / "pnr" / "spare_cells.json").write_text(
        json.dumps(plan, indent=2))
    if planted is not None:
        (proj / "reports" / "spare_cell_coverage.json").write_text(
            json.dumps(planted, indent=2))
    return proj


def _run(proj):
    r = subprocess.run(
        [sys.executable, str(COV_SCRIPT), "."],
        cwd=str(proj), capture_output=True, text=True)
    out = json.loads((proj / "reports" / "spare_cell_coverage.json")
                     .read_text())
    return r.returncode, out


STARVED = _plan(10, 10000, 0.001)   # 0.1% — a twentieth of the 2% floor
HEALTHY_VERDICT = {
    "program": "spare_cell_coverage (runner-emit)",
    "target_density": 0.001, "actual_density": 0.02, "count": 200,
    "distribution_ok": True, "tie_off_ok": True,
    "verdict": "PASS", "status": "PASS",
}


def test_a_planted_pass_at_the_declared_path_does_not_rescue_a_starved_plan(
        tmp_path):
    """The exact shape the second writer produced: a PASS payload sitting at
    the declared path, graded against a laxer floor, while the plan on disk
    is starved."""
    proj = _project(tmp_path, STARVED, planted=HEALTHY_VERDICT)
    rc, out = _run(proj)
    assert rc == 1, (
        f"gate exited {rc} on a plan with 10 spares in 10000 cells "
        f"(0.001 < 0.02); a payload planted at its own output path "
        f"rescued it. Verdict written: {out}")
    assert out["verdict"] == "FAIL"
    assert out["actual_density"] == 0.001, (
        f"gate reported actual_density {out['actual_density']} for a plan "
        f"recording 0.001 — it read the planted file, not the plan")
    assert out["count"] == 10


def test_the_verdict_is_identical_with_and_without_a_file_at_the_output_path(
        tmp_path):
    """Same plan, two projects: one with the declared path empty, one with a
    contradicting payload already there. Same verdict, same numbers."""
    clean = _project(tmp_path / "a", STARVED)
    dirty = _project(tmp_path / "b", STARVED, planted=HEALTHY_VERDICT)
    rc_a, out_a = _run(clean)
    rc_b, out_b = _run(dirty)
    assert rc_a == rc_b == 1
    graded = ("target_density", "actual_density", "count",
              "distinct_positions", "distribution_ok", "tie_off_ok",
              "density_ok", "verdict", "reasons", "status")
    assert {k: out_a[k] for k in graded} == {k: out_b[k] for k in graded}


def test_re_running_the_gate_does_not_carry_its_own_density_forward(
        tmp_path):
    """The staleness this defect actually produced. Run 1 grades a healthy
    plan; the plan is then replaced by a starved one and the gate re-runs
    over the SAME project — as a resumed run with a cached PnR does, since
    the cached branch skips the insertion step entirely."""
    proj = _project(tmp_path, _plan(200, 10000, 0.02))
    rc1, out1 = _run(proj)
    assert (rc1, out1["verdict"]) == (0, "PASS")
    (proj / "phase3" / "stage3" / "pnr" / "spare_cells.json").write_text(
        json.dumps(STARVED, indent=2))
    rc2, out2 = _run(proj)
    assert rc2 == 1, (
        f"re-run exited {rc2}: the gate carried run 1's density over run "
        f"2's plan. Verdict written: {out2}")
    assert out2["actual_density"] == 0.001
    assert out2["count"] == 10


def test_the_evaluator_takes_the_plan_and_nothing_else():
    """The second input is the mechanism. `evaluate_coverage` must not grow
    one back — a positional second argument here is a coverage summary
    again."""
    import inspect
    params = list(inspect.signature(cov.evaluate_coverage).parameters)
    assert params == ["spare_plan", "target_density"], (
        f"evaluate_coverage takes {params}; the only inputs are the plan "
        f"and the gate's floor")


def test_the_reported_inputs_are_exhaustive_and_exclude_the_output_path(
        tmp_path):
    proj = _project(tmp_path, STARVED, planted=HEALTHY_VERDICT)
    _rc, out = _run(proj)
    assert out["inputs"] == ["phase3/stage3/pnr/spare_cells.json"]
    assert "coverage_summary_json" not in out, (
        "the verdict names its own output path as an input again")


# ──────────────────────────────────────────────────────────────────
# 3) The declaration still says what the code now does
# ──────────────────────────────────────────────────────────────────
def test_step_18_declares_the_path_and_names_its_producer():
    doc = FLOW.read_text(encoding="utf-8")
    marker = '  - id: 18\n'
    start = doc.index(marker)
    end = doc.index('\n  - id: 19', start)
    step18 = doc[start:end]
    assert f'- "{DECLARED_PATH}"' in step18
    assert "spare_cell_coverage_check" in step18
