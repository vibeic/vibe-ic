"""#3373: frontend manifest emission obeys the selected Step 5 window."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import design_one_shot_runner as runner  # noqa: E402
import step_preflight  # noqa: E402


RUNNER_SOURCE = PROGRAMS / "design_one_shot_runner.py"


def _main_node():
    tree = ast.parse(RUNNER_SOURCE.read_text())
    return next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "main")


def _step_requested_by_real_window(entry, exit_step, step):
    sites = step_preflight.RUNNER_PLANS["design_one_shot_runner"].sites
    entry_site = (step_preflight.site_for_step(
        "design_one_shot_runner", entry) if entry else None)
    pruned = runner._exit_pruned_sites(sites, exit_step) if exit_step else []
    names = {"_site_order", "_before_entry", "_after_exit", "_step_requested"}
    helpers = [node for node in _main_node().body
               if isinstance(node, ast.FunctionDef) and node.name in names]
    env = {
        "_spf": step_preflight,
        "_entry_site": entry_site,
        "_exit_pruned": pruned,
        "_bounded": runner.run_is_bounded(
            entry_site, pruned, [name for name, _ in sites]),
        "args": SimpleNamespace(entry_step=entry, exit_step=exit_step),
    }
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=helpers, type_ignores=[])), str(RUNNER_SOURCE), "exec"), env)
    return env["_step_requested"](step)


@pytest.mark.parametrize("entry,exit_step,formal_selected", [
    ("2", "3", False),
    ("4", "4", False),
    ("4", "5", True),
    (None, None, True),
])
def test_real_numeric_window_decides_step5_ownership(
        entry, exit_step, formal_selected):
    assert _step_requested_by_real_window(entry, exit_step, "5") is formal_selected


def test_main_passes_step5_ownership_to_the_manifest_emitter():
    calls = [node for node in ast.walk(_main_node())
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)
             and node.func.id == "_complete_phase2_frontend"]
    assert len(calls) == 1
    keyword = next((kw.value for kw in calls[0].keywords
                    if kw.arg == "emit_formal"), None)
    assert isinstance(keyword, ast.Call)
    assert isinstance(keyword.func, ast.Name)
    assert keyword.func.id == "_step_requested"
    assert len(keyword.args) == 1
    assert isinstance(keyword.args[0], ast.Constant)
    assert keyword.args[0].value == "5"


def test_unselected_formal_is_byte_preserved_and_never_imports_tools(
        tmp_path, monkeypatch):
    formal = runner._pl.formal_dir(tmp_path)
    task = formal / "task_reset"
    task.mkdir(parents=True)
    files = {
        formal / "results.json": b'{"verdict":"FAIL","counterexamples":1}\n',
        formal / "property_contract.json": b'{"obligations":["reset"]}\n',
        task / "engine_0.log": b'DONE (FAIL)\n',
        task / "trace.vcd": b'$date retained $end\n',
    }
    for path, data in files.items():
        path.write_bytes(data)

    class Bomb:
        def __getattr__(self, name):
            raise AssertionError(f"formal tool imported outside Step 5: {name}")

    for name in ("formal_proof_evidence_check", "formal_harness_gen",
                 "formal_property_run"):
        monkeypatch.setitem(sys.modules, name, Bomb())

    result = runner.step_emit_phase2_manifests(
        tmp_path, [], top_name="unit", container="unused",
        emit_formal=False)

    assert result.status == "PASS"
    index = json.loads((tmp_path / "steps/index.json").read_text())
    retained_ids = {str(row["id"]) for row in index["steps"]}
    assert "5" not in retained_ids
    assert {"6", "39"}.issubset(retained_ids)
    assert {path: path.read_bytes() for path in files} == files
    assert sorted(path.relative_to(formal).as_posix()
                  for path in formal.rglob("*") if path.is_file()) == [
                      "property_contract.json", "results.json",
                      "task_reset/engine_0.log", "task_reset/trace.vcd"]


def test_selected_formal_still_invokes_generator_and_native_runner(
        tmp_path, monkeypatch):
    calls = []
    rtl = runner._pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    source = rtl / "unit.v"
    source.write_text("module unit(input clk); endmodule\n")
    harness = tmp_path / "generated_formal_harness.sv"
    harness.write_text("module unit_formal; endmodule\n")

    def generate(**kwargs):
        calls.append(("generate", kwargs["top"], kwargs["container"]))
        return {"verdict": "EMITTED", "harness_path": str(harness),
                "rtl_files": [str(source)], "harness_module": "unit_formal"}

    def run(project, **kwargs):
        calls.append(("run", kwargs["top"], kwargs["container"]))
        formal = runner._pl.formal_dir(project)
        formal.mkdir(parents=True, exist_ok=True)
        (formal / "results.json").write_text(json.dumps({
            "verdict": "PASS", "all_proved": True}) + "\n")
        return {"verdict": "PASS"}

    import formal_harness_gen
    import formal_property_run
    monkeypatch.setattr(formal_harness_gen, "generate", generate)
    monkeypatch.setattr(formal_property_run, "run", run)

    result = runner.step_emit_phase2_manifests(
        tmp_path, [], top_name="unit", container="pinned-image",
        emit_formal=True)

    assert result.status == "PASS"
    assert calls == [("generate", "unit", "pinned-image"),
                     ("run", "unit_formal", "pinned-image")]
    expected = (runner._pl.formal_dir(tmp_path) / "results.json").relative_to(
        tmp_path).as_posix()
    assert expected in result.output_files
