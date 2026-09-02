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


def test_repository_has_no_benchmark_specific_entry_surface():
    report = entry_check.audit(PLUGIN)
    assert report["verdict"] == "PASS", report


def test_general_router_decides_before_the_runner_is_invoked():
    """`--solve` is the lifecycle verb, not permission to skip routing."""
    # ``cmd_solve`` now owns only the run-root coordinator lock.  Routing and
    # runner invocation remain together in the locked implementation; inspect
    # that body so the ordering assertion still measures the production path.
    tree = ast.parse(textwrap.dedent(
        inspect.getsource(dispatch._cmd_solve_locked)))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]

    route = next(
        node for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "tnr"
        and node.func.attr == "classify_task_nature")
    runner = next(
        node for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "runner_budget"
        and node.func.attr == "run")

    assert route.lineno < runner.lineno


def test_retired_setup_is_not_a_public_command(tmp_path):
    result = subprocess.run(
        [sys.executable, str(PROGRAMS / "benchmark_dispatch.py"),
         "verilogeval-v2", "--setup", "--dataset", str(tmp_path / "ds"),
         "--run", str(tmp_path / "run")],
        capture_output=True, text=True)
    assert result.returncode == 2
    assert "unrecognized arguments: --setup" in result.stderr


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
