"""Regression tests for the Phase-2 Step-7 producer seam."""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as D  # noqa: E402
import step_preflight as S  # noqa: E402
import execution_policy as EP  # noqa: E402
from _ppa import timing as T  # noqa: E402


def test_phase2_declares_and_wires_canonical_step7_site():
    sites = dict(S.RUNNER_PLANS["design_one_shot_runner"].sites)
    assert sites["asic_sdc"] == ("7",)
    source = (PROGRAMS / "design_one_shot_runner.py").read_text()
    tree = ast.parse(source)
    names = {node.name for node in ast.walk(tree)
             if isinstance(node, ast.FunctionDef)}
    assert "step_asic_sdc" in names
    main = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "main")
    calls = [node for node in ast.walk(main)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and node.func.attr == "gate"]
    assert any(any(isinstance(arg, ast.Constant)
                   and arg.value == "asic_sdc" for arg in call.args)
               for call in calls)


def test_step7_direct_path_uses_single_canonical_emitter(tmp_path, monkeypatch):
    calls = []
    pdk = SimpleNamespace(name="test", liberty="/pdk/nom.lib")
    monkeypatch.setattr(EP, "dispatch_fixed_step",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(D, "_phase2_pdk_config", lambda project: pdk)
    monkeypatch.setattr(D._pl, "constraints_dir",
                        lambda project: Path(project) / "constraints")
    fake = {
        "path": "constraints/chip_top.asic.sdc",
        "sha256": "a" * 64,
        "design_staged": False,
    }
    def emit(*args, **kwargs):
        calls.append((args, kwargs))
        path = Path(args[1]) / fake["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("create_clock -period 10 [get_ports clk]\n")
        return fake
    monkeypatch.setattr(T, "emit_step7_asic_sdc", emit)
    def pvt(project, _pdk, _container):
        path = Path(project) / "constraints/pvt_matrix.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"corners": [{"label": "TT"}, {"label": "SS"}]}\n')
        return path, 2
    monkeypatch.setattr(D, "_emit_step7_pvt_matrix", pvt)
    result = D.step_asic_sdc(tmp_path, "chip_top", "container")
    assert result.status == "PASS", result.detail
    assert len(calls) == 1
    assert (tmp_path / fake["path"]).is_file()
    assert (tmp_path / "constraints/pvt_matrix.json").is_file()


def test_default_not_measured_frontend_result_falls_through_to_emitter(
        tmp_path, monkeypatch):
    """A source-bound placeholder cannot strand the canonical default path."""
    pdk = SimpleNamespace(name="test", liberty="/pdk/nom.lib")
    monkeypatch.setattr(EP, "dispatch_fixed_step",
                        lambda *args, **kwargs: {
                            "status": "NOT_MEASURED",
                            "reason": "generic frontend gate is unmeasured"})
    monkeypatch.setattr(EP, "_ordinary_runtime",
                        {"policy": {"mode": "default"}})
    monkeypatch.setattr(D, "_phase2_pdk_config", lambda project: pdk)
    monkeypatch.setattr(D._pl, "constraints_dir",
                        lambda project: Path(project) / "constraints")
    called = []
    from _ppa import timing as T
    def emit(*args, **kwargs):
        called.append(True)
        path = Path(args[1]) / "constraints/chip_top.asic.sdc"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("create_clock -period 10 [get_ports clk]\n")
        return {"path": "constraints/chip_top.asic.sdc", "sha256": "a" * 64}
    monkeypatch.setattr(T, "emit_step7_asic_sdc", emit)
    monkeypatch.setattr(D, "_emit_step7_pvt_matrix", lambda project, pdk, container: (
        (Path(project) / "constraints/pvt_matrix.json").write_text("{}\n") and
        (Path(project) / "constraints/pvt_matrix.json", 2)))
    result = D.step_asic_sdc(tmp_path, "chip_top", "container")
    assert result.status == "PASS"
    assert called
