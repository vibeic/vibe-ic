"""programs/oracle_self_consistency_sweep.py — both directions, on every verdict.

The program answers "is this problem winnable, and does its testbench verify
anything" for a whole dataset. Every claim it can make is planted here in a
SYNTHETIC dataset and a SYNTHETIC scorer, so each verdict is proven to appear
when it should AND to be absent when it should not. Nothing here reads a real
benchmark, so the tests carry no golden content and need no simulator.

THE MUTATION THAT MATTERS
=========================
`test_mutation_dropping_arm_s_makes_the_vacuous_case_read_ok` runs the
judgement with ARM S removed and asserts the vacuous fixture then reads OK.
That is the failure the stub arm exists to prevent: without it, a testbench
that verifies nothing is indistinguishable from a healthy one, and a
theoretical-max number computed from ARM G alone would silently count it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

import oracle_self_consistency_sweep as S


# ───────────────────────────── synthetic fixtures ─────────────────────────────
# A whole benchmark, invented: two problems, a registry entry of our own, and a
# scorer that reports whatever the fixture tells it to. No real dataset, no
# real scorer, no simulator.
_FAKE_BENCH = "fixture-bench"

_FAKE_SCORER = '''\
import json, sys, pathlib
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
run = pathlib.Path(a["--run"])
table = json.loads((pathlib.Path(a["--dataset"]) / "verdicts.json").read_text())
probs = [l.strip() for l in (run / "problems.list").read_text().splitlines() if l.strip()]
results = []
for p in probs:
    text = (run / "samples" / (p + "_sample01.sv")).read_text()
    arm = "S1" if "= '1;" in text else ("S0" if "= '0;" in text and "GOLDEN" not in text else "G")
    v = table[p][arm]
    results.append(dict({"problem": p}, **v))
(run / "pass_at_1.json").write_text(json.dumps({"results": results}))
'''


class _FixtureAdapter:
    """The whole adapter contract, for an invented dataset layout."""

    @staticmethod
    def problems(dataset, entry):
        return sorted(p.stem[:-7] for p in Path(dataset).glob("*_prompt.txt"))

    @staticmethod
    def golden_candidate(dataset, pid, entry):
        text = (Path(dataset) / f"{pid}_ref.sv").read_text()
        return (f"{pid}_sample01.sv", text, text)


def _make_dataset(tmp_path, verdicts, golden_body=None):
    ds = tmp_path / "ds"
    ds.mkdir()
    for pid in verdicts:
        (ds / f"{pid}_prompt.txt").write_text("do a thing\n")
        (ds / f"{pid}_ref.sv").write_text(
            golden_body or "// GOLDEN\nmodule TopModule (input a, output y);\n"
                           "  assign y = a;\nendmodule\n")
    (ds / "verdicts.json").write_text(json.dumps(verdicts))
    return ds


def _install_fixture_bench(monkeypatch, tmp_path, shape="C"):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"benchmarks": {_FAKE_BENCH: {
        "shape": shape, "layout": {"prompt_suffix": "_prompt.txt"},
        "scorer_args": {}}}}))
    scorer = tmp_path / "fake_scorer.py"
    scorer.write_text(_FAKE_SCORER)
    monkeypatch.setitem(S._ADAPTER_MODULES, _FAKE_BENCH, "unused")
    monkeypatch.setattr(S, "_adapter_for", lambda bench: _FixtureAdapter)
    return registry, scorer


_PASS = {"verdict": "PASS"}


def _fail(reason="functional_mismatch"):
    return {"verdict": "FAIL", "reason": reason}


# ─────────────────────────────── the four verdicts ───────────────────────────────
def test_a_healthy_problem_reads_ok(tmp_path, monkeypatch):
    registry, scorer = _install_fixture_bench(monkeypatch, tmp_path)
    ds = _make_dataset(tmp_path, {"P1": {"G": _PASS, "S0": _fail(), "S1": _fail()}})
    res = S.sweep(_FAKE_BENCH, ds, tmp_path / "out", work_root=tmp_path / "w",
                  scorer=scorer, registry=registry)
    assert res["per_problem"]["P1"]["verdict"] == S.OK
    assert res["theoretical_max"]["max"] == 1
    assert res["theoretical_max"]["broken"] == []


def test_a_planted_failing_golden_reads_broken_golden(tmp_path, monkeypatch):
    registry, scorer = _install_fixture_bench(monkeypatch, tmp_path)
    ds = _make_dataset(tmp_path, {
        "P1": {"G": _PASS, "S0": _fail(), "S1": _fail()},
        "P2": {"G": _fail("compile_error"), "S0": _fail(), "S1": _fail()}})
    res = S.sweep(_FAKE_BENCH, ds, tmp_path / "out", work_root=tmp_path / "w",
                  scorer=scorer, registry=registry)
    assert res["per_problem"]["P2"]["verdict"] == S.BROKEN_GOLDEN
    tm = res["theoretical_max"]
    assert tm["total"] == 2 and tm["max"] == 1
    # The evidence is the scorer's OWN line, and nothing else.
    assert [b["id"] for b in tm["broken"]] == ["P2"]
    assert "compile_error" in tm["broken"][0]["evidence"]


def test_a_planted_stub_accepting_tb_reads_vacuous(tmp_path, monkeypatch):
    registry, scorer = _install_fixture_bench(monkeypatch, tmp_path)
    ds = _make_dataset(tmp_path, {
        "P1": {"G": _PASS, "S0": _fail(), "S1": _fail()},
        "P2": {"G": _PASS, "S0": _PASS, "S1": _PASS}})
    res = S.sweep(_FAKE_BENCH, ds, tmp_path / "out", work_root=tmp_path / "w",
                  scorer=scorer, registry=registry)
    assert res["per_problem"]["P2"]["verdict"] == S.VACUOUS_TB
    assert [b["id"] for b in res["theoretical_max"]["broken"]] == ["P2"]
    assert res["theoretical_max"]["max"] == 1


def test_one_stub_passing_is_not_vacuous_and_is_said_out_loud(tmp_path, monkeypatch):
    """The other direction of the vacuity rule: a problem whose correct answer
    IS a constant is passed by that stub legitimately, so ONE stub passing must
    never be charged as a defect — but it is reported."""
    registry, scorer = _install_fixture_bench(monkeypatch, tmp_path)
    ds = _make_dataset(tmp_path, {"P1": {"G": _PASS, "S0": _PASS, "S1": _fail()}})
    res = S.sweep(_FAKE_BENCH, ds, tmp_path / "out", work_root=tmp_path / "w",
                  scorer=scorer, registry=registry)
    assert res["per_problem"]["P1"]["verdict"] == S.OK
    assert res["per_problem"]["P1"]["single_stub_pass"] == S.ARM_S0
    assert res["theoretical_max"]["broken"] == []


def test_a_missing_scorer_reads_not_measured_never_broken(tmp_path, monkeypatch):
    registry, scorer = _install_fixture_bench(monkeypatch, tmp_path)
    ds = _make_dataset(tmp_path, {"P1": {"G": _PASS, "S0": _fail(), "S1": _fail()}})
    res = S.sweep(_FAKE_BENCH, ds, tmp_path / "out", work_root=tmp_path / "w",
                  scorer=tmp_path / "no_such_scorer.py", registry=registry)
    assert res["per_problem"]["P1"]["verdict"] == S.NOT_MEASURED
    tm = res["theoretical_max"]
    assert tm["broken"] == [], "a scorer that never ran is not evidence of a defect"
    assert [b["id"] for b in tm["not_measured"]] == ["P1"]
    assert tm["max"] == 1, "NOT_MEASURED is not subtracted: we do not know"


def test_a_skipped_arm_reads_not_measured(tmp_path, monkeypatch):
    registry, scorer = _install_fixture_bench(monkeypatch, tmp_path)
    ds = _make_dataset(tmp_path, {
        "P1": {"G": {"verdict": "SKIP", "reason": "iverilog_absent"},
               "S0": _fail(), "S1": _fail()}})
    res = S.sweep(_FAKE_BENCH, ds, tmp_path / "out", work_root=tmp_path / "w",
                  scorer=scorer, registry=registry)
    v = res["per_problem"]["P1"]
    assert v["verdict"] == S.NOT_MEASURED and "iverilog_absent" in v["reason"]


# ────────────────────────────────── the mutation ──────────────────────────────────
def test_mutation_dropping_arm_s_makes_the_vacuous_case_read_ok():
    """ARM S is load-bearing: remove it and the vacuous fixture goes green."""
    vacuous = ({"verdict": "PASS"}, {"verdict": "PASS"}, {"verdict": "PASS"})
    assert S.classify(*vacuous)["verdict"] == S.VACUOUS_TB

    def mutant(golden, _s0, _s1, **kw):        # ARM G only — the mutation
        return {"verdict": S.OK if golden.get("verdict") == "PASS"
                else S.BROKEN_GOLDEN}

    assert mutant(*vacuous)["verdict"] == S.OK, (
        "if this ever stops reading OK the mutation is no longer the mutation "
        "and this test has stopped proving ARM S matters")


def test_classify_refuses_to_decide_vacuity_without_both_stub_arms():
    assert S.classify({"verdict": "PASS"}, None, {"verdict": "PASS"})["verdict"] \
        == S.NOT_MEASURED
    assert S.classify({"verdict": "PASS"}, {"verdict": "PASS"}, None)["verdict"] \
        == S.NOT_MEASURED


# ──────────────────────────────── the constant stubs ────────────────────────────────
@pytest.mark.parametrize("header", [
    "module m (input a, output y);\n  assign y = a;\nendmodule\n",
    "module m #(parameter W = 4) (input [W-1:0] a, output [W-1:0] y);\n"
    "  assign y = a;\nendmodule\n",
    "module m (a, y);\n  input a;\n  output reg y;\n  always @* y = a;\nendmodule\n",
])
def test_both_constant_stubs_are_built_for_every_header_dialect(header):
    s0 = S.constant_stub(header, 0)
    s1 = S.constant_stub(header, 1)
    assert s0 and s1 and s0 != s1
    assert "'0;" in s0 and "'1;" in s1
    for s in (s0, s1):
        assert s.lstrip().startswith("module m") and "endmodule" in s
        assert "assign a" not in s, "an INPUT must never be driven by the stub"


def test_a_header_no_dialect_parses_yields_no_stub_rather_than_a_guess():
    assert S.constant_stub("// no module here at all\n", 0) is None
    assert S.constant_stub("module m (input a);\n endmodule\n", 0) is None


def test_stub_level_is_only_zero_or_one():
    with pytest.raises(S.SweepError):
        S.constant_stub("module m (input a, output y); endmodule", 2)


# ─────────────────────────────────── the boundary ───────────────────────────────────
def test_the_sweep_refuses_to_run_inside_a_solve_run_directory(tmp_path, monkeypatch):
    registry, scorer = _install_fixture_bench(monkeypatch, tmp_path)
    ds = _make_dataset(tmp_path, {"P1": {"G": _PASS, "S0": _fail(), "S1": _fail()}})
    run = tmp_path / "solve_run"
    (run / "nested").mkdir(parents=True)
    (run / ".bench_config.json").write_text("{}")
    with pytest.raises(S.SweepError, match="REFUSING TO RUN"):
        S.sweep(_FAKE_BENCH, ds, run / "nested", work_root=tmp_path / "w",
                scorer=scorer, registry=registry)
    # …and the same output path is accepted once it is NOT inside a solve run.
    assert S.refuse_reason(tmp_path / "elsewhere", ds) is None


def test_the_report_carries_ids_and_scorer_lines_but_no_golden_content(
        tmp_path, monkeypatch):
    """The output of a golden-READING program is what a solver could ever see.
    It must carry ids, verdicts and the scorer's own lines — never the golden."""
    registry, scorer = _install_fixture_bench(monkeypatch, tmp_path)
    secret = ("// GOLDEN\nmodule TopModule (input a, output y);\n"
              "  assign y = ~a; // UNIQUE_GOLDEN_TOKEN_9f3\nendmodule\n")
    ds = _make_dataset(tmp_path, {"P1": {"G": _fail(), "S0": _fail(), "S1": _fail()},
                                  "P2": {"G": _PASS, "S0": _fail(), "S1": _fail()}},
                       golden_body=secret)
    res = S.sweep(_FAKE_BENCH, ds, tmp_path / "out", work_root=tmp_path / "w",
                  scorer=scorer, registry=registry)
    rendered = (json.dumps(res["theoretical_max"])
                + S.render_markdown(_FAKE_BENCH, res, ds))
    assert "UNIQUE_GOLDEN_TOKEN_9f3" not in rendered
    assert "assign y" not in rendered
    # …and it does carry what the reader came for.
    assert "P1" in rendered and "P2" in rendered
    assert "functional_mismatch" in rendered
