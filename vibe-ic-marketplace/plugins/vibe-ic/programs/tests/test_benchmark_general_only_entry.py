"""Every benchmark uses the general IC-design entry; formats stay adapters."""
from __future__ import annotations

import ast
import inspect
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
BENCHMARK = PLUGIN / "benchmark"
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(BENCHMARK))

import benchmark_dispatch as dispatch  # noqa: E402
import benchmark_entry_surface_check as entry_check  # noqa: E402
import benchmark_io_adapter as adapter  # noqa: E402
import score_cvdp_open as cvdp_score  # noqa: E402
import task_nature_route as general_route  # noqa: E402
import rtl_final_bundle_integrity as bundle_gate  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


@pytest.mark.parametrize("entry,exit_step", [
    ("D1", "D1"), ("D1", "4"), ("2", "2"), ("11", "13"), ("15", "31"),
])
@pytest.mark.parametrize("supplied_rtl", [False, True])
def test_open_runner_declares_ip_without_changing_the_task_window(
        tmp_path, entry, exit_step, supplied_rtl):
    argv = dispatch._resume_solver_argv(
        PROGRAMS / "vibe_ic_one_shot_runner.py", tmp_path,
        supplied_rtl, entry, exit_step)
    assert argv[argv.index("--route") + 1] == "ip", argv
    assert argv[argv.index("--exit-step") + 1] == exit_step
    effective_entry = "2" if supplied_rtl else entry
    if effective_entry == "D1":
        assert "--entry-step" not in argv
    else:
        assert argv[argv.index("--entry-step") + 1] == effective_entry
    assert ("--skip-phase3" in argv) == (entry != "15")


def test_phase1_provenance_frontdoor_supplies_the_same_delivery_route(tmp_path):
    prompt = tmp_path / "input" / "phase1_prompt.md"
    prompt.parent.mkdir()
    prompt.write_text("Design a combinational module with one input and output.")
    calls = []
    # A real Python fixture child models only the D1 report boundary. Its
    # actual argv/source, delivery admission and emitted bytes are bound by
    # the production budget; it does not claim a native Phase-1 gate PASS.
    runner = tmp_path / "fixture-runner" / "vibe_ic_one_shot_runner.py"
    runner.parent.mkdir()
    runner.write_text('''import json, pathlib, sys
sys.path.insert(0, %r)
p = pathlib.Path(sys.argv[1]).resolve()
docs = p/'phase1/generated_docs'
docs.mkdir(parents=True)
(docs/'L1_DATASHEET.json').write_text('{"schema": 1}\\n')
out = p/'reports/orchestrator/phase1_one_shot.json'
out.parent.mkdir(parents=True, exist_ok=True)
summary = {'project':str(p), 'verdict':'NOT_MEASURED',
           'measurement_scope':'SOURCE_ONLY_FIXTURE'}
out.write_text(json.dumps(summary))
''' % str(PROGRAMS))

    class RunnerBudget(dispatch._RunnerBudget):
        def run(self, argv):
            calls.append(argv)
            return super().run(argv)

    budget = RunnerBudget(1, 1, 1)

    result = dispatch._ensure_phase1_frontdoor(
        runner, tmp_path, budget)
    assert result["status"] == "GENERATED", result
    assert result["runner_rc"] == 0
    assert calls[0][calls[0].index("--exit-step") + 1] == "D1"
    assert "--entry-step" not in calls[0]
    assert calls[0][calls[0].index("--route") + 1] == "ip"
    reused = dispatch._ensure_phase1_frontdoor(runner, tmp_path, budget)
    assert reused["status"] == "REUSED"
    assert len(calls) == 1


def test_shipped_open_registry_all_uses_the_explicit_ip_entry(tmp_path):
    registry_path = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "benchmark",
        "BENCHMARK_REGISTRY.json")
    registry = json.loads(registry_path.read_text())
    for bench in dispatch._BENCH_FORMAT:
        row = registry["benchmarks"][bench]
        assert set(row["shape"].split("/")) & {"B", "C"}
        runner = row["solve_entry"]["runner"].split()[0]
        assert runner == "programs/vibe_ic_one_shot_runner.py"
        argv = dispatch._solver_argv(
            PLUGIN / runner, tmp_path, "D1", "4")
        assert argv[argv.index("--route") + 1] == "ip", (bench, argv)


def test_repository_has_no_benchmark_specific_entry_surface():
    report = entry_check.audit(PLUGIN)
    assert report["verdict"] == "PASS", report


def test_general_router_decides_before_the_runner_is_invoked():
    tree = ast.parse(textwrap.dedent(inspect.getsource(dispatch._cmd_solve_locked)))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    route = next(node for node in calls if isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name)
                 and node.func.value.id == "tnr" and node.func.attr == "classify_task_nature")
    launch = next(node for node in calls if isinstance(node.func, ast.Attribute)
                  and isinstance(node.func.value, ast.Name)
                  and node.func.value.id == "runner_budget" and node.func.attr == "run")
    frontdoor = next(node for node in calls if isinstance(node.func, ast.Name)
                     and node.func.id == "_ensure_phase1_frontdoor")
    assert isinstance(frontdoor.args[2], ast.Name)
    assert frontdoor.args[2].id == "runner_budget"
    assert route.lineno < frontdoor.lineno < launch.lineno


def test_retired_setup_is_not_a_public_command(tmp_path):
    result = subprocess.run(
        [sys.executable, str(PROGRAMS / "benchmark_dispatch.py"),
         "verilogeval-v2", "--setup", "--dataset", str(tmp_path / "ds"),
         "--run", str(tmp_path / "run")],
        capture_output=True, text=True)
    assert result.returncode == 2
    assert "unrecognized arguments: --setup" in result.stderr


@pytest.mark.parametrize("spelling,canonical", [
    ("cvdp", "cvdp-open"),
    ("cvdp-open", "cvdp-open"),
    ("ve-human", "verilogeval-human"),
])
def test_operational_main_resolves_alias_before_dispatch(
        tmp_path, monkeypatch, spelling, canonical):
    calls = []

    def solve_spy(bench, dataset, run, **kwargs):
        calls.append((bench, dataset, run, kwargs))
        return 0

    monkeypatch.setattr(dispatch, "cmd_solve", solve_spy)
    monkeypatch.setattr(dispatch, "_install_orphan_guard", lambda: None)
    monkeypatch.setattr(sys, "argv", [
        "benchmark_dispatch.py", spelling, "--solve",
        "--dataset", str(tmp_path / "unread-dataset"),
        "--run", str(tmp_path / "uncreated-run"),
    ])
    with pytest.raises(SystemExit) as exc:
        dispatch.main()
    assert exc.value.code == 0
    assert [call[:3] for call in calls] == [(
        canonical, str(tmp_path / "unread-dataset"),
        str(tmp_path / "uncreated-run"))]


def test_show_preserves_exact_historical_registry_key(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "benchmark_dispatch.py", "cvdp", "--show"])
    dispatch.main()
    shown = json.loads(capsys.readouterr().out)
    assert list(shown) == ["cvdp"]
    assert shown["cvdp"]["status"].startswith("SUPERSEDED by cvdp-open")


def test_unknown_benchmark_still_refuses_before_dispatch(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "benchmark_dispatch.py", "not-a-real-benchmark", "--show"])
    with pytest.raises(SystemExit, match="unknown benchmark"):
        dispatch.main()


@pytest.mark.parametrize(
    "bench", ["verilogeval-v2", "verilogeval-human", "rtllm", "cvdp-open"])
def test_every_open_plan_names_only_the_general_solve_front_door(
        bench, capsys):
    dispatch.cmd_show(bench)
    text = capsys.readouterr().out
    assert f"benchmark_dispatch.py {bench} --solve" in text
    assert "task_router.py" not in text
    assert "task_loop.py" not in text
    assert "gates_atomic.py" not in text


def test_benchmark_ic_policy_is_the_normal_whole_chip_runner():
    registry = json.loads(
        (BENCHMARK / "BENCHMARK_REGISTRY.json").read_text())
    policy = registry["benchmarks"]["benchmark_clean"]["entry_policy"]
    assert policy == {
        "front_door": "commands/vibe-ic-all.md",
        "runner": "programs/vibe_ic_one_shot_runner.py",
        "verify": "skills/benchmark-verify/SKILL.md",
        "benchmark_specific_solver": False,
    }


def test_cvdp_category_metadata_cannot_select_the_route(tmp_path):
    prompt = "Complete the following module: module m(input a, output y);"
    verdicts = []
    for cid in ("cid003", "cid016"):
        dataset = tmp_path / f"{cid}.jsonl"
        dataset.write_text(json.dumps({
            "id": cid, "cid": cid,
            "input": {"prompt": prompt, "context": {}},
            "output": {"context": {"rtl/m.sv": "hidden"}},
        }) + "\n")
        problem = next(adapter.problems("cvdp", dataset))
        project = tmp_path / f"project_{cid}"
        adapter.stage("cvdp", problem, project)
        visible = (project / "input" / "phase1_prompt.md").read_text()
        verdicts.append(general_route.classify_task_nature(
            visible, has_context=False, nature=None))
    assert verdicts[0] == verdicts[1]


def test_cvdp_scorer_contract_reads_paths_but_not_reference_values(tmp_path):
    dataset = tmp_path / "cvdp.jsonl"
    dataset.write_text(json.dumps({
        "id": "p",
        "input": {"prompt": "make p", "context": {}},
        "output": {"context": {
            "rtl/a.sv": {"secret": object().__class__.__name__},
            "rtl/b.sv": "REFERENCE_BYTES_MUST_NOT_BE_EXPORTED",
        }},
        "harness": {"secret": "also ignored"},
    }) + "\n")
    assert adapter.cvdp_scorer_contracts(dataset) == {
        "p": ["rtl/a.sv", "rtl/b.sv"]}


def test_cvdp_multifile_package_maps_exact_accepted_modules(tmp_path):
    snap_a, snap_b = tmp_path / "00.sv", tmp_path / "01.sv"
    snap_a.write_text("module a(input x, output y); assign y=x; endmodule\n")
    snap_b.write_text("module b(input x, output y); assign y=~x; endmodule\n")
    packed = adapter.cvdp_package_response(
        [snap_a, snap_b],
        [Path("/runner/rtl/a.sv"), Path("/runner/rtl/b.sv")],
        ["rtl/a.sv", "rtl/b.sv"])
    payload = json.loads(packed)
    assert payload == {"code": [
        {"rtl/a.sv": snap_a.read_text()},
        {"rtl/b.sv": snap_b.read_text()},
    ]}


def test_cvdp_multifile_package_maps_one_unique_residual_module(tmp_path):
    snap = tmp_path / "00_combined.sv"
    snap.write_text(
        "module accepted_wrapper; endmodule\n"
        "module leaf_a; endmodule\n"
        "module leaf_b; endmodule\n")
    packed = adapter.cvdp_package_response(
        [snap], [Path("/runner/rtl/combined_source.sv")],
        ["rtl/scorer_wrapper_name.sv", "rtl/leaf_a.sv", "rtl/leaf_b.sv"])
    code = json.loads(packed)["code"]
    assert "module accepted_wrapper" in code[0]["rtl/scorer_wrapper_name.sv"]
    assert "module leaf_a" in code[1]["rtl/leaf_a.sv"]
    assert "module leaf_b" in code[2]["rtl/leaf_b.sv"]


def test_cvdp_package_keeps_a_reviewed_private_dependency(tmp_path):
    snap = tmp_path / "00_combined.v"
    snap.write_text(
        "module encoder__inner(input x, output y); assign y=x; endmodule\n"
        "module encoder(input x, output y); "
        "encoder__inner u_inner(.x(x), .y(y)); endmodule\n"
        "module single_port_ram(input x, output y); assign y=x; endmodule\n")
    packed = adapter.cvdp_package_response(
        [snap], [Path("/runner/rtl/combined.v")],
        ["rtl/encoder.sv", "rtl/single_port_ram.sv"])
    code = json.loads(packed)["code"]
    encoder = code[0]["rtl/encoder.sv"]
    ram = code[1]["rtl/single_port_ram.sv"]
    assert "module encoder__inner" in encoder
    assert "module encoder(" in encoder
    assert "module single_port_ram" not in encoder
    assert "module single_port_ram" in ram
    if bundle_gate.shutil.which("iverilog") is not None:
        assert bundle_gate.check_final_bundle(
            [snap], adapter.cvdp_response_file_map(
                packed, ["rtl/encoder.sv", "rtl/single_port_ram.sv"])
        )["status"] == "PASS"


def test_cvdp_package_refuses_duplicate_reviewed_module_ownership(tmp_path):
    top = tmp_path / "00_top.sv"
    helper = tmp_path / "01_helper.sv"
    top.write_text(
        "module top; helper u(); endmodule\nmodule helper; endmodule\n")
    helper.write_text("module helper; endmodule\n")
    with pytest.raises(ValueError, match="duplicate module.*helper"):
        adapter.cvdp_package_response(
            [top, helper],
            [Path("/runner/rtl/top.sv"), Path("/runner/rtl/helper.sv")],
            ["rtl/top.sv", "rtl/helper.sv"])


def test_cvdp_export_blocks_a_noncompiling_final_bundle(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    snapshot = tmp_path / "snapshot" / "top.sv"
    snapshot.parent.mkdir()
    snapshot.write_text("module top; missing_dependency u(); endmodule\n")
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(json.dumps({
        "id": "p", "input": {"prompt": "make top", "context": {}},
        "output": {"context": {"rtl/top.sv": "hidden"}},
    }) + "\n")
    task = {
        "id": "p",
        "candidate_snapshot": {
            "rtl_paths": [str(snapshot)],
            "source_rtl_paths": ["/runner/rtl/top.sv"],
        },
        "rtl_sha256": "fixture",
    }
    (run / dispatch._REVIEW_WORKLIST).write_text(json.dumps(task) + "\n")
    (run / "solve_report.json").write_text(json.dumps({
        "results": [{"id": "p", "accepted": True}],
    }) + "\n")
    monkeypatch.setattr(dispatch, "_shape_c_task_binding_reasons",
                        lambda *_args: [])
    monkeypatch.setattr(dispatch, "_validate_ai_review",
                        lambda _task: {"status": "ACCEPTED"})
    monkeypatch.setattr(dispatch, "_validate_candidate_snapshot",
                        lambda *_args: [])
    monkeypatch.setattr(bundle_gate, "check_final_bundle",
                        lambda *_args: {
                            "status": "BLOCKED",
                            "reasons": ["missing_dependency"],
                            "compile": {"status": "BLOCKED"},
                        })

    with pytest.raises(SystemExit, match="final RTL bundle integrity is BLOCKED"):
        dispatch._export_accepted_cvdp_responses("cvdp-open", dataset, run)
    assert not (run / "responses" / "accepted_cvdp.jsonl").exists()


def test_cvdp_multifile_package_refuses_to_guess_a_missing_file(tmp_path):
    snap = tmp_path / "00.sv"
    snap.write_text("module unrelated; endmodule\n")
    with pytest.raises(ValueError, match="cannot be mapped exactly"):
        adapter.cvdp_package_response(
            [snap], [Path("/runner/rtl/unrelated.sv")],
            ["rtl/a.sv", "rtl/b.sv"])


def test_cvdp_official_scorer_runs_only_on_complete_response_set(
        tmp_path, monkeypatch):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(json.dumps({
        "id": "p", "input": {"prompt": "module p", "context": {}},
        "output": {"context": {"rtl/p.sv": "hidden"}},
        "harness": {},
    }) + "\n")
    responses = tmp_path / "responses.jsonl"
    responses.write_text(json.dumps({
        "id": "p", "completion": "module p; endmodule"}) + "\n")
    scorer_root = tmp_path / "official"
    scorer_root.mkdir()
    (scorer_root / "run_benchmark.py").write_text("# fixture\n")
    run = tmp_path / "run"

    def fake_run(cmd, **kwargs):
        cmd = [str(x) for x in cmd]
        if "run_benchmark.py" in " ".join(cmd):
            prefix = Path(cmd[cmd.index("--prefix") + 1])
            prefix.mkdir(parents=True, exist_ok=True)
            (prefix / "raw_result.json").write_text(json.dumps({
                "p": {"tests": [{"result": 0}]}}))
        if "verify_fail_triage.py" in " ".join(cmd):
            out = Path(cmd[cmd.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"total_fails": 0, "records": []}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cvdp_score.subprocess, "run", fake_run)
    rc = cvdp_score.score(
        dataset, responses, run, scorer_root,
        "sim:image", "pnr:image", 2)
    assert rc == 0
    result = json.loads((run / "pass_at_1.json").read_text())
    assert result["passed"] == 1
    assert result["total"] == 1
    assert result["pass_at_1"] == 1.0
