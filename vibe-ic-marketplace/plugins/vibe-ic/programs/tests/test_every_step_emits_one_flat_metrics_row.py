#!/usr/bin/env python3
"""Every step emits one flat metrics row, from the wrapper — the ORFS shape.

WHAT THIS BUYS, AND IT IS ONE THING. "Is this run better or worse than the last
one" becomes one `diff`:

    62c62
    <  "d1__flow__drc_violations": 393,
    ---
    >  "d1__flow__drc_violations": 0,

Before this, that question was answered by reading prose across a dozen
differently shaped JSONs — which is how a 393-violation DRC run and a
0-violation one came to be compared by hand, and how a `0` that meant "nothing
was measured" was read as "nothing was wrong".

WHY THE WRAPPER AND NOT 46 PROGRAMS. `step_metrics` was adopted from
OpenROAD-flow-scripts and its docstring quotes how ORFS does it: "every ORFS
stage runs through the same 21-line wrapper with `-metrics "$LOG_DIR/$1.json"`".
The stage scripts do not each learn to emit. MEASURED 2026-09-04: 4 of the 50
flow steps that declare programs emitted through `step_metrics`; converting the
other 46 by hand would have been both the un-ORFS way and a diff nobody
reviews. `check_step` is the one place every step already passes through.

WHAT MUST NOT DRIFT, and each has a test below:
  * the emit happens on BOTH the sequential and the threaded branch — which one
    runs is decided by `_compliance_workers` from the machine, not the design,
    and a row that appears only sometimes is a row no diff can rely on;
  * only SCALARS cross. A list of offenders is not a measurement; `len()` of it
    might be, and choosing that is the gate's call, not the wrapper's;
  * nothing is COMPUTED here. A number this wrapper derived would be a number
    about the run that no gate stands behind.
"""
from __future__ import annotations

import glob
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_FCC = _PROGRAMS / "flow_compliance_check.py"


def _run(project: Path) -> None:
    subprocess.run([sys.executable, str(_FCC), str(project)],
                   capture_output=True, timeout=1800)


def _merged(project: Path) -> dict:
    """`genMetrics.py` is glob-and-merge; so is this."""
    out: dict = {}
    for f in sorted(glob.glob(str(project / "reports/metrics/*.json"))):
        out.update(json.loads(Path(f).read_text()))
    return out


@pytest.fixture(scope="module")
def emitted(tmp_path_factory):
    p = tmp_path_factory.mktemp("mrun")
    _run(p)
    return _merged(p)


def test_every_step_gets_a_row(emitted):
    """68 steps, 68 rows. A step with no row is a step no diff can see."""
    assert len(emitted) >= 40, (
        f"only {len(emitted)} metric key(s) emitted; the wrapper is not "
        f"emitting for every step")
    # `step_status`, because that is the wrapper's own fact. `verdict` belongs
    # to whichever gate program measured it and the wrapper must not write it.
    assert any(k.endswith("__flow__step_status") for k in emitted)


def test_the_keys_are_flat_and_prefixed(emitted):
    """`<stage>__<domain>__<name>` — greppable and diffable, ORFS's shape."""
    for k in emitted:
        assert "__" in k, f"{k} carries no stage/domain prefix"
        assert not isinstance(emitted[k], (dict, list)), (
            f"{k} holds a nested value; the schema is FLAT because a nested "
            f"one cannot be diffed line by line")


def test_a_changed_number_is_one_line_of_diff(tmp_path):
    """THE WHOLE POINT, driven end to end rather than asserted."""
    import yaml
    doc = yaml.safe_load((_PLUGIN / "flow" / "phase1_phase2_phase3.yaml")
                         .read_text())
    target = {}

    def walk(o):
        if target:
            return
        if isinstance(o, dict):
            if "id" in o:
                for e in (o.get("required_outputs") or []):
                    rel = e.get("path") if isinstance(e, dict) else e
                    if isinstance(rel, str) and rel.endswith(".json"):
                        target.update({"id": str(o["id"]), "rel": rel})
                        return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(doc)
    assert target, "no step declares a .json output; nothing to drive"

    merged = {}
    for run, value in (("A", 393), ("B", 0)):
        p = tmp_path / run
        (p / target["rel"]).parent.mkdir(parents=True, exist_ok=True)
        (p / target["rel"]).write_text(json.dumps({"drc_violations": value}))
        _run(p)
        merged[run] = _merged(p)

    differing = [k for k in set(merged["A"]) | set(merged["B"])
                 if merged["A"].get(k) != merged["B"].get(k)]
    assert any(k.endswith("__drc_violations") for k in differing), (
        f"the changed number did not reach the metrics; differing keys were "
        f"{differing}")


def test_only_scalars_cross(tmp_path):
    """A list of offenders is not a measurement, and a sentence is not one
    either. Flattening them would put prose in a numeric schema."""
    import yaml
    doc = yaml.safe_load((_PLUGIN / "flow" / "phase1_phase2_phase3.yaml")
                         .read_text())
    rel = None

    def walk(o):
        nonlocal rel
        if rel:
            return
        if isinstance(o, dict):
            for e in (o.get("required_outputs") or []):
                p = e.get("path") if isinstance(e, dict) else e
                if isinstance(p, str) and p.endswith(".json"):
                    rel = p
                    return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(doc)
    assert rel

    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(json.dumps({
        "a_number": 12, "a_flag": True,
        "a_sentence": "this is prose", "a_list": [1, 2, 3],
        "an_object": {"nested": 1}}))
    _run(tmp_path)
    m = _merged(tmp_path)
    assert any(k.endswith("__a_number") for k in m)
    assert any(k.endswith("__a_flag") for k in m)
    for bad in ("a_sentence", "a_list", "an_object"):
        assert not any(k.endswith(f"__{bad}") for k in m), (
            f"{bad} reached the flat schema")


def test_both_branches_emit():
    """Sequential and threaded. `_compliance_workers` picks from the MACHINE,
    so a row emitted on only one branch is a row that appears or vanishes with
    the host — the worst possible property for a run-to-run diff."""
    src = _FCC.read_text()
    seq = src.index("results.append(_r)")
    par = src.index("for _step, _fut in zip(_eval_steps, _futs):")
    assert seq and par
    assert src.count("_emit_step_metrics(project,") >= 2, (
        "only one branch emits; which branch runs is not the design's choice")


def test_the_wrapper_computes_nothing_of_its_own():
    """It forwards what a gate already wrote. A derived number would be a claim
    about the run that no gate stands behind."""
    import ast
    tree = ast.parse(_FCC.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_emit_step_metrics")
    # THE CODE, not the prose. A first version grepped the whole function text
    # and matched `* ` inside its own docstring — a test that fails on its
    # explanation rather than on its subject.
    body = [n for n in fn.body if not (isinstance(n, ast.Expr)
                                       and isinstance(n.value, ast.Constant))]
    # `/` is EXCLUDED, and named rather than dropped: in this tree it is
    # `Path.__truediv__`, path joining, and `project / rel` is how every
    # program resolves a declared artefact. Forbidding it would fail this test
    # on the one operation the function cannot avoid. Add/Sub/Mult have no such
    # second meaning here.
    arith = [n for stmt in body for n in ast.walk(stmt)
             if isinstance(n, ast.BinOp)
             and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult))]
    assert not arith, (
        "the metrics wrapper does arithmetic; it may only forward values a "
        "gate already measured")
    calls = {n.func.id for stmt in body for n in ast.walk(stmt)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    aggregating = calls & {"sum", "len", "max", "min", "round", "abs"}
    assert not aggregating, (
        f"the metrics wrapper aggregates ({sorted(aggregating)}); choosing "
        f"what a list REDUCES to is the gate's call, not this wrapper's")


# --------------------------------------------------------------------------- #
# The wrapper and a program that already emits must not become two instruments
# sharing one name
# --------------------------------------------------------------------------- #
def test_the_wrapper_reports_step_status_not_a_second_verdict():
    """`StepResult.status` is NOT the gate's verdict.

    `placement_legality_check` already emits `verdict` for step 17 — its own
    gate's. The wrapper's value is the step's state AFTER evidence, waivers and
    cascade attribution. Under one name both become `17__flow__verdict`, and
    `emit`'s `prior.update` lets whoever ran last win, so the gate's own
    measurement would be silently replaced by a different quantity.
    """
    src = _FCC.read_text()
    body = src[src.index("def _emit_step_metrics("):]
    body = body[:body.index("\ndef ")]
    assert '"step_status"' in body
    assert '{"verdict"' not in body, (
        "the wrapper emits `verdict`, which a gate program already owns")


def test_the_wrapper_never_overwrites_a_key_a_program_authored(tmp_path):
    """The program measured it and stands behind it; the wrapper forwards a
    report and stands behind nothing. Where both would write a key, the one
    with an author keeps it.

    DRIVEN THROUGH A REAL COLLISION. A first version seeded `verdict` and
    relied on the rename to keep them apart — so removing the no-clobber guard
    changed nothing and the test passed on a tree with no guard at all. The
    collision has to be MADE: the program's key and the report's field must be
    the same name for the same step.
    """
    import step_metrics as sm
    import yaml
    doc = yaml.safe_load((_PLUGIN / "flow" / "phase1_phase2_phase3.yaml")
                         .read_text())
    target = {}

    def walk(o):
        if target:
            return
        if isinstance(o, dict):
            if "id" in o:
                for e in (o.get("required_outputs") or []):
                    rel = e.get("path") if isinstance(e, dict) else e
                    if isinstance(rel, str) and rel.endswith(".json"):
                        target.update({"id": str(o["id"]), "rel": rel})
                        return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(doc)
    assert target, "no step declares a .json output; no collision can be made"

    # The program's number, authored and stood behind.
    sm.emit(tmp_path, target["id"], {"violation_count": 5})
    # The SAME field, different value, in the report the wrapper forwards.
    (tmp_path / target["rel"]).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / target["rel"]).write_text(
        json.dumps({"violation_count": 999}))

    step_n = sm.normalize_step(target["id"])
    before = json.loads(
        (tmp_path / f"reports/metrics/{step_n}.json").read_text())
    _run(tmp_path)
    after = json.loads(
        (tmp_path / f"reports/metrics/{step_n}.json").read_text())

    key = f"{step_n}__flow__violation_count"
    assert after.get(key) == 5, (
        f"the wrapper overwrote an authored measurement: {key} was 5 and is "
        f"now {after.get(key)!r}. The report's 999 is what the wrapper "
        f"forwards; the 5 is what a program measured and stands behind.")
    for k, v in before.items():
        assert after.get(k) == v, f"{k} was rewritten by the wrapper"
    assert f"{step_n}__flow__step_status" in after, (
        "the wrapper contributed nothing; it must still add its own fact")
