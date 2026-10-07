"""Regression tests for the Phase-2 canonical producer seams."""
from __future__ import annotations

import ast
import json
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


def test_default_step1_preflight_reaches_one_producer_and_rtl_consumer(
        tmp_path, monkeypatch):
    """Default must publish the ordinary producer's bytes before consumption."""
    project = tmp_path / "project"
    spec = project / "input/rtl_spec.json"
    spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({
        "module": "neutral_top", "inputs": ["a", "b"], "outputs": ["y"],
        "gates": [{"op": "and", "out": "y", "in": ["a", "b"]}]}))
    monkeypatch.setattr(EP, "_ordinary_runtime", {
        "project": project.resolve(), "phase1_only": False,
        "policy": {"mode": "default"}})
    controller_calls = []
    placeholder = D._preflight_refusal("rtl_gen")(
        "Ultra fixed-row provider dispatch", {"execution_results": [{
            "status": "NOT_MEASURED", "candidate_statuses": {
                "frontend_1": "NOT_MEASURED"}}]})

    def controller(*args):
        controller_calls.append(args)
        return placeholder

    monkeypatch.setattr(EP, "dispatch_ordinary_rows", controller)
    # Input admission is independent of this routing seam and is exercised by
    # the real bounded front-door run. Keep its positive decision fixed here.
    monkeypatch.setattr(S, "decide", lambda *a, **k: S.Decision(
        "design_one_shot_runner", "rtl_gen", ["1"], verdict="READY"))
    producer_calls = []

    def producer(subject, ic_class):
        producer_calls.append((subject, ic_class))
        return D.step_rtl_gen(subject, ic_class)

    result = S.gate(project, "design_one_shot_runner", "rtl_gen",
                    D._preflight_refusal("rtl_gen"), producer,
                    project, "digital_logic")
    assert result.status == "PASS", result
    assert producer_calls == [(project, "digital_logic")]
    assert controller_calls == []
    rtl = list((project / "phase2/stage1/rtl").glob("*.sv"))
    assert [path.name for path in rtl] == ["neutral_top.sv"]
    assert "a & b" in rtl[0].read_text()
    import flow_step_output_content_check as consumer
    assert consumer.check(project, "rtl") == []


@pytest.mark.parametrize("status", ["NOT_MEASURED", "FAIL", "PASS"])
@pytest.mark.parametrize("mode,phase1_only", [
    ("ultra", False), ("default", True)])
def test_step1_keeps_ultra_and_phase1_only_controller_outcomes(
        tmp_path, monkeypatch, status, mode, phase1_only):
    runtime = {"project": tmp_path.resolve(), "phase1_only": phase1_only,
               "policy": {"mode": mode}}
    monkeypatch.setattr(EP, "_ordinary_runtime", runtime)
    row = SimpleNamespace(status=status, extras={"execution_results": [{
        "status": status, "reason": "NO_REGISTERED_PROVIDER"}]})
    monkeypatch.setattr(EP, "dispatch_ordinary_rows", lambda *args: row)
    result = EP.dispatch_ordinary_site(
        tmp_path, "design_one_shot_runner", "rtl_gen", lambda *args: None)
    assert result is row
    assert result.status == status
    assert "program_first_fallback_sites" not in runtime


def test_default_step1_producer_bypass_refuses_other_project(tmp_path, monkeypatch):
    monkeypatch.setattr(EP, "_ordinary_runtime", {
        "project": (tmp_path / "admitted").resolve(), "phase1_only": False,
        "policy": {"mode": "default"}})
    monkeypatch.setattr(EP, "dispatch_ordinary_rows", lambda *args: None)
    with pytest.raises(EP.Refusal, match="ORDINARY_PROJECT_UNBOUND"):
        EP.dispatch_ordinary_site(
            tmp_path / "other", "design_one_shot_runner", "rtl_gen", lambda *args: None)


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
    step7 = next(call for call in calls
                 if any(isinstance(arg, ast.Constant)
                        and arg.value == "asic_sdc" for arg in call.args))
    assert any(kw.arg == "_use_controller"
               and isinstance(kw.value, ast.Constant)
               and kw.value.value is False
               for kw in step7.keywords)


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
                            "reason": "NO_RUNNABLE_ADAPTER"})
    monkeypatch.setattr(EP, "_ordinary_runtime",
                        {"policy": {"mode": "default",
                                     "request_receipt": {"request_digest": "d" * 64}},
                         "project": tmp_path.resolve()})
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


def test_default_ordinary_step7_placeholder_releases_preflight_gate(
        tmp_path, monkeypatch):
    """The live Controller seam must let Default reach the canonical fn.

    ``step_preflight.gate`` asks ``dispatch_ordinary_site`` first.  A
    source-bound Step-7 adapter is intentionally NOT_MEASURED, so returning
    that row would strand the direct producer forever.  Ultra and measured
    failures remain owned by the Controller.
    """
    monkeypatch.setattr(EP, "_ordinary_runtime",
                        {"policy": {"mode": "default"}})
    runtime = {"policy": {"mode": "default",
                           "request_receipt": {"request_digest": "d" * 64}},
               "project": tmp_path.resolve()}
    monkeypatch.setattr(EP, "_ordinary_runtime", runtime)
    monkeypatch.setattr(EP, "dispatch_ordinary_rows",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("Default Step 7 must use canonical producer")))
    assert EP.dispatch_ordinary_site(tmp_path, "design_one_shot_runner",
                                     "asic_sdc", lambda *a: None) is None

    placeholder = SimpleNamespace(
        status="NOT_MEASURED",
        extras={"execution_results": [{
            "status": "NOT_MEASURED", "reason": "NO_RUNNABLE_ADAPTER"}]})
    monkeypatch.setattr(EP, "dispatch_ordinary_rows",
                        lambda *args, **kwargs: placeholder)
    monkeypatch.setattr(EP, "_ordinary_runtime",
                        {"policy": {"mode": "ultra"}})
    assert EP.dispatch_ordinary_site(tmp_path, "design_one_shot_runner",
                                     "asic_sdc", lambda *a: None) is placeholder

    measured_fail = SimpleNamespace(status="FAIL", extras={})
    monkeypatch.setattr(EP, "dispatch_ordinary_rows",
                        lambda *args, **kwargs: measured_fail)
    monkeypatch.setattr(EP, "_ordinary_runtime",
                        {"policy": {"mode": "default",
                                     "request_receipt": {"request_digest": "d" * 64}},
                         "project": tmp_path.resolve()})
    assert EP.dispatch_ordinary_site(tmp_path, "design_one_shot_runner",
                                     "asic_sdc", lambda *a: None) is None


def test_default_ordinary_step9_placeholder_releases_preflight_gate(
        tmp_path, monkeypatch):
    """The Default Step-9 source arm must release to the Yosys producer."""
    placeholder = SimpleNamespace(
        status="NOT_MEASURED",
        extras={"execution_results": [{
            "status": "NOT_MEASURED", "reason": "NO_RUNNABLE_ADAPTER"}]})
    monkeypatch.setattr(EP, "dispatch_ordinary_rows",
                        lambda *args, **kwargs: placeholder)
    monkeypatch.setattr(EP, "_ordinary_runtime",
                        {"policy": {"mode": "default",
                                     "request_receipt": {"request_digest": "d" * 64}},
                         "project": tmp_path.resolve()})
    assert EP.dispatch_ordinary_site(tmp_path, "design_one_shot_runner",
                                     "yosys_synth", lambda *a: None) is None

    monkeypatch.setattr(EP, "_ordinary_runtime",
                        {"policy": {"mode": "ultra"}})
    assert EP.dispatch_ordinary_site(tmp_path, "design_one_shot_runner",
                                     "yosys_synth", lambda *a: None) is placeholder

    measured_fail = SimpleNamespace(status="FAIL", extras={})
    monkeypatch.setattr(EP, "dispatch_ordinary_rows",
                        lambda *args, **kwargs: measured_fail)
    monkeypatch.setattr(EP, "_ordinary_runtime",
                        {"policy": {"mode": "default"}})
    assert EP.dispatch_ordinary_site(tmp_path, "design_one_shot_runner",
                                     "yosys_synth", lambda *a: None) is measured_fail


def test_default_step9_placeholder_marks_canonical_producer_fallback(
        tmp_path, monkeypatch):
    """The released Step-9 placeholder must suppress Controller re-entry."""
    placeholder = SimpleNamespace(
        status="NOT_MEASURED",
        extras={"execution_results": [{
            "status": "NOT_MEASURED", "reason": "NO_RUNNABLE_ADAPTER"}]})
    runtime = {"policy": {"mode": "default",
                           "request_receipt": {"request_digest": "d" * 64}},
               "project": tmp_path.resolve()}
    monkeypatch.setattr(EP, "dispatch_ordinary_rows",
                        lambda *args, **kwargs: placeholder)
    monkeypatch.setattr(EP, "_ordinary_runtime", runtime)
    assert EP.dispatch_ordinary_site(tmp_path, "design_one_shot_runner",
                                     "yosys_synth", lambda *a: None) is None
    assert runtime["program_first_fallback_sites"] == {
        ("yosys_synth", str(tmp_path.resolve()), "d" * 64)}
    handoff = EP.consume_program_first_fallback(tmp_path, "yosys_synth")
    assert handoff is not None
    assert EP.is_program_first_fallback_handoff(handoff, tmp_path,
                                                "yosys_synth") is True
    assert EP.consume_program_first_fallback(tmp_path, "yosys_synth") is None
    assert EP.is_program_first_fallback_handoff(handoff, tmp_path / "other",
                                                "yosys_synth") is False
    EP.release_program_first_fallback(handoff)


def test_default_step9_fallback_marker_is_not_consumed_by_ultra(
        tmp_path, monkeypatch):
    runtime = {"policy": {"mode": "ultra"}, "project": tmp_path.resolve(),
               "program_first_fallback_sites": {
                   ("yosys_synth", str(tmp_path.resolve()))}}
    monkeypatch.setattr(EP, "_ordinary_runtime", runtime)
    assert EP.consume_program_first_fallback(tmp_path, "yosys_synth") is None
    assert runtime["program_first_fallback_sites"]


def test_default_step9_worker_error_does_not_release_to_native_producer(
        tmp_path, monkeypatch):
    worker_error = SimpleNamespace(
        status="NOT_MEASURED",
        extras={"execution_results": [{
            "status": "NOT_MEASURED", "reason": "ADAPTER_ERROR"}]})
    runtime = {"policy": {"mode": "default",
                           "request_receipt": {"request_digest": "d" * 64}},
               "project": tmp_path.resolve()}
    monkeypatch.setattr(EP, "dispatch_ordinary_rows",
                        lambda *args, **kwargs: worker_error)
    monkeypatch.setattr(EP, "_ordinary_runtime", runtime)
    assert EP.dispatch_ordinary_site(tmp_path, "design_one_shot_runner",
                                     "yosys_synth", lambda *a: None) is worker_error
    assert "program_first_fallback_sites" not in runtime


def test_default_step9_fallback_requires_placeholder_reason(tmp_path, monkeypatch):
    for reason in ("ADAPTER_ERROR", "PROCESS_ERROR", "GATE_FAIL", "worker error"):
        worker_error = SimpleNamespace(
            status="NOT_MEASURED",
            extras={"execution_results": [{
                "status": "NOT_MEASURED", "reason": reason}]})
        runtime = {"policy": {"mode": "default",
                               "request_receipt": {"request_digest": "d" * 64}},
                   "project": tmp_path.resolve()}
        monkeypatch.setattr(EP, "dispatch_ordinary_rows",
                            lambda *args, _row=worker_error, **kwargs: _row)
        monkeypatch.setattr(EP, "_ordinary_runtime", runtime)
        assert EP.dispatch_ordinary_site(tmp_path, "design_one_shot_runner",
                                         "yosys_synth", lambda *a: None) is worker_error
        assert "program_first_fallback_sites" not in runtime


def test_default_step9_fallback_requires_request_digest(tmp_path, monkeypatch):
    placeholder = SimpleNamespace(
        status="NOT_MEASURED",
        extras={"execution_results": [{
            "status": "NOT_MEASURED", "reason": "NO_RUNNABLE_ADAPTER"}]})
    runtime = {"policy": {"mode": "default"}, "project": tmp_path.resolve()}
    monkeypatch.setattr(EP, "dispatch_ordinary_rows",
                        lambda *args, **kwargs: placeholder)
    monkeypatch.setattr(EP, "_ordinary_runtime", runtime)
    assert EP.dispatch_ordinary_site(tmp_path, "design_one_shot_runner",
                                     "yosys_synth", lambda *a: None) is placeholder
    assert "program_first_fallback_sites" not in runtime


def test_phase3_step9_consumes_default_fallback_marker():
    """Phase-3 synth must have an explicit one-shot producer bypass."""
    import phase3_one_shot_runner as P3
    source = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(source)
    fn = next(node for node in ast.walk(tree)
              if isinstance(node, ast.FunctionDef) and node.name == "step_synth")
    segment = ast.get_source_segment(source, fn)
    assert segment is not None
    assert "_fallback_handoff" in segment
    assert P3.step_synth.__name__ == "step_synth"
    retry = [node for node in ast.walk(fn)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)
             and node.func.id == "step_synth"]
    assert any(any(kw.arg == "_fallback_handoff" for kw in call.keywords)
               for call in retry)


def test_phase3_step9_rejects_forged_fallback_handoff(tmp_path, monkeypatch):
    """An arbitrary private-looking value must keep Controller dispatch on."""
    import execution_production as production
    import phase3_one_shot_runner as P3
    runtime = {"policy": {"mode": "default",
                           "request_receipt": {"request_digest": "d" * 64}},
               "project": tmp_path.resolve()}
    monkeypatch.setattr(EP, "_ordinary_runtime", runtime)
    calls = []
    monkeypatch.setattr(production, "dispatch_site",
                        lambda *args, **kwargs: (
                            calls.append((args, kwargs)) or
                            {"status": "ADOPTED", "reason": "controller"}))
    result = P3.step_synth(tmp_path, "top", None, "container",
                           _fallback_handoff=True)
    assert result.status == "PASS"
    assert calls, "forged handoff must not bypass Controller"


def test_live_preflight_gate_calls_step7_fn_after_default_placeholder(
        tmp_path, monkeypatch):
    """Exercise the actual gate seam, not only its dispatch helper."""
    decision = S.Decision("design_one_shot_runner", "asic_sdc", ["7"],
                          verdict="READY", allow=True, detail="ready")
    monkeypatch.setattr(S, "decide", lambda *args, **kwargs: decision)
    monkeypatch.setattr(S, "record", lambda *args, **kwargs: None)
    monkeypatch.setattr(EP, "_ordinary_runtime",
                        {"policy": {"mode": "default",
                                     "request_receipt": {"request_digest": "d" * 64}},
                         "project": tmp_path.resolve()})
    monkeypatch.setattr(EP, "dispatch_ordinary_rows",
                        lambda *args, **kwargs: SimpleNamespace(
                            status="NOT_MEASURED",
                            extras={"execution_results": [{
                                "status": "NOT_MEASURED",
                                "reason": "NO_RUNNABLE_ADAPTER"}]}))
    called = []
    sentinel = SimpleNamespace(status="NOT_MEASURED")

    def direct(*args, **kwargs):
        called.append((args, kwargs))
        return sentinel

    got = S.gate(tmp_path, "design_one_shot_runner", "asic_sdc",
                 lambda *args: None, direct, tmp_path)
    assert got is sentinel
    assert called and called[0][0] == (tmp_path,)
