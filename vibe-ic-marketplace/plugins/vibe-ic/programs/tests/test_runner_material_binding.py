"""Actual neutral subprocess/collector boundaries, without dataset or EDA."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark_dispatch as bd
import benchmark_io_adapter as bio


WIRE = "module neutral(input a,output y); assign y=a; endmodule\n"


def _invoke(tmp_path, *, generate=False, crlf=False):
    project = tmp_path / "project"
    prompt = project / "input" / "phase1_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Describe a neutral wire-through block.\n")
    context = project / "input" / "rtl" / "context.v"
    context.parent.mkdir()
    context.write_text("// Provided neutral context.\n")
    rtl = project / "phase2" / "stage1" / "rtl" / "neutral.v"
    rtl.parent.mkdir(parents=True)
    if not generate:
        rtl.write_bytes(WIRE.replace("\n", "\r\n").encode() if crlf else WIRE.encode())
    report = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"steps": [{"name": "rtl_gen", "status": "PASS",
                                             "detail": "old neutral report"}]}))
    # _RunnerBudget's positional project protocol belongs to this basename.
    # This child is neutral maintenance, not an execution of the IC flow.
    runner = tmp_path / "vibe_ic_one_shot_runner.py"
    runner.write_text("""import json, pathlib, sys
sys.path.insert(0, %r)
p = pathlib.Path(sys.argv[1])
if sys.argv[2] == 'generate':
    (p/'phase2/stage1/rtl/neutral.v').write_text(%r)
(p/'reports/orchestrator/phase2_one_shot.json').write_text(json.dumps(
    {'steps': [{'name': 'rtl_gen', 'status': 'PASS', 'detail': 'fresh neutral report'}]}))
print('complete neutral stdout')
print('bounded neutral rc1', file=sys.stderr)
raise SystemExit(1)
""" % (str(Path(__file__).resolve().parents[1]), WIRE))
    argv = [sys.executable, str(runner), str(project), "generate" if generate else "fresh"]
    process = bd._RunnerBudget(1, 1, 0).run(argv)
    assert process.rc == 1 and process.error is None
    return project, process, argv




MUTATIONS = ["prompt", "input_content", "input_added", "input_removed", "input_renamed",
             "output_content", "output_added", "output_removed", "output_renamed"]




def _freeze(tmp_path, project, process, got):
    return bd._make_ai_review_task(
        "neutral", project, got, {}, 1, tmp_path / "run", "PROGRAM",
        runner_invocation=process.invocation)


@pytest.mark.parametrize("generate,crlf", [(False, False), (True, False), (False, True)])
def test_fresh_rc1_and_runner_generated_output_remain_bound_through_freeze(
        tmp_path, generate, crlf):
    project, process, argv = _invoke(tmp_path, generate=generate, crlf=crlf)
    got = bd._collect_runner_result(process, argv, "neutral", "neutral", project)
    assert got["ok"] is True and got["completion"] == WIRE
    task = _freeze(tmp_path, project, process, got)
    assert bd._runner_reentry_reason(task, {}) is None
    frozen = Path(task["rtl_paths"][0])
    assert frozen.read_bytes() == (project / "phase2/stage1/rtl/neutral.v").read_bytes()


@pytest.mark.parametrize("kind", ["prompt", "input_added", "output_content", "output_renamed"])
def test_substitution_between_collection_and_freeze_is_refused(tmp_path, kind):
    project, process, argv = _invoke(tmp_path)
    got = bd._collect_runner_result(process, argv, "neutral", "neutral", project)
    assert got["ok"] is True




@pytest.mark.parametrize("kind", MUTATIONS + ["stdout", "stderr", "report", "frozen_name"])
def test_frozen_task_reentry_revalidates_producer_material_logs_and_report(
        tmp_path, kind):
    project, process, argv = _invoke(tmp_path)
    got = bd._collect_runner_result(process, argv, "neutral", "neutral", project)
    task = _freeze(tmp_path, project, process, got)
    assert bd._runner_reentry_reason(task, {}) is None


def test_population_changed_during_freeze_cannot_be_issued(tmp_path, monkeypatch):
    project, process, argv = _invoke(tmp_path)
    got = bd._collect_runner_result(process, argv, "neutral", "neutral", project)
    native_archive = bd._archive_candidate

    def archive(*args, **kwargs):
        candidate = native_archive(*args, **kwargs)
        frozen = Path(candidate["rtl_paths"][0])
        new = frozen.with_name("00_replacement.v")
        frozen.rename(new)
        candidate["rtl_paths"] = [str(new)]
        return candidate

    monkeypatch.setattr(bd, "_archive_candidate", archive)
    with pytest.raises(ValueError, match="frozen RTL population/content"):
        _freeze(tmp_path, project, process, got)


@pytest.mark.parametrize("failure", ["signal", "traceback"])
def test_fresh_report_cannot_authorize_a_killed_or_crashed_worker(tmp_path, failure):
    project, _, argv = _invoke(tmp_path)
    runner = Path(argv[1])
    source = runner.read_text().replace("print('bounded neutral rc1', file=sys.stderr)", "")
    termination = ("import os, signal; os.kill(os.getpid(), signal.SIGTERM)"
                   if failure == "signal" else "raise RuntimeError('neutral worker failure')")
    runner.write_text(source.replace("raise SystemExit(1)", termination))
    process = bd._RunnerBudget(1, 1, 0).run(argv)
    assert process.rc == (-15 if failure == "signal" else 1)
    assert process.error.startswith("RUNNER_WORKER_FAILED:")
    got = bd._collect_runner_result(process, argv, "neutral", "neutral", project)
    assert got["ok"] is False and "completion" not in got
    assert got["reason"].startswith("RUNNER_WORKER_FAILED:")
