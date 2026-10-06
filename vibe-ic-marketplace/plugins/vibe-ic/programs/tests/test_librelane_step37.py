"""Step-37 DRC selection consumes measured LibreLane step outputs."""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
contract = importlib.import_module("librelane_contract")
step37 = importlib.import_module("librelane_step37")


def _put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


@pytest.mark.parametrize("second_metric,expected", [(2, 6), (None, None)])
def test_drc_requires_both_tool_measurements(tmp_path, monkeypatch,
                                             second_metric, expected):
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    project = tmp_path / "project"
    source = project / "source"
    source.mkdir(parents=True)
    views = {}
    for key in ("odb", "def", "nl", "sdc", "gds"):
        path = source / key
        path.write_bytes(key.encode())
        views[key] = str(path)
    state = _put(project / "state.json", {**views, "metrics": {}})
    config_root = project / "config"
    configs = {step: _put(config_root / (step + ".json"),
                          {"meta": {"step": step}})
               for step in ("Magic.DRC", "KLayout.DRC")}
    pdk_root = tmp_path / "pdk"
    (pdk_root / "processA").mkdir(parents=True)

    def tool_writes(cmd, **kwargs):
        folder = Path(cmd[cmd.index("-o") + 1])
        step = cmd[cmd.index("--id") + 1]
        incoming = json.loads(Path(cmd[cmd.index("-i") + 1]).read_text())
        key, value = (("magic__drc_error__count", 4) if step == "Magic.DRC"
                      else ("klayout__drc_error__count", second_metric))
        if value is not None:
            incoming.setdefault("metrics", {})[key] = value
        _put(folder / "state_out.json", incoming)
        return SimpleNamespace(returncode=0, stdout="tool output", stderr="")

    monkeypatch.setattr(contract, "image_capability", lambda *args: None)
    monkeypatch.setattr(contract.subprocess, "run", tool_writes)
    if expected is None:
        with pytest.raises(contract.Refusal, match="LL_DRC_NOT_MEASURED"):
            step37._measured_drc(project, "candidate", pdk_root, "processA",
                                 state, "37-probe", configs)
    else:
        measured = step37._measured_drc(project, "candidate", pdk_root,
                                        "processA", state, "37-probe", configs)
        assert measured == {"magic": 4, "klayout": 2, "total": expected,
                            "report": str(project / "phase3/librelane/37-probe/drc_judgment.json")}


def test_promoted_librelane_bytes_are_declared_as_klayout(tmp_path, monkeypatch):
    runner = importlib.import_module("phase3_one_shot_runner")
    pnr = tmp_path / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    gds = pnr / "core.gds"
    gds.write_bytes(b"streamed bytes")
    promotion = tmp_path / "phase3/librelane/37-promotion.json"
    _put(promotion, {"canonical": str(gds),
                     "canonical_sha256": contract.digest(gds)})
    seen = []
    monkeypatch.setattr(runner, "_restamp_provenance_output",
                        lambda *args, **kwargs: seen.append((args, kwargs)))
    runner._step37_declare_streamout_gds_provenance(tmp_path, "core")
    assert seen[0][0][3] == "klayout"


def test_each_finished_stream_runs_both_existing_gds_gates(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    pdk_root = tmp_path / "pdks"
    (pdk_root / "processA").mkdir(parents=True)
    gds = project / "candidate.gds"
    gds.write_bytes(b"tool output")
    routed = project / "routed.def"
    routed.write_text("DESIGN core ;\nEND DESIGN\n")
    config = _put(project / "magic.json", {"MAGIC_TECH": "/pdk/processA/magic.tech"})
    calls = []

    def tool_writes(cmd, **kwargs):
        calls.append((cmd, kwargs))
        report = Path(cmd[cmd.index("--json") + 1])
        substance = any(str(part).endswith("gds_substance_check.py") for part in cmd)
        _put(report, {"verdict": "PASS" if substance else "FINDINGS"})
        return SimpleNamespace(returncode=0 if substance else 1,
                               stdout="tool result", stderr="")

    monkeypatch.setattr(step37, "run_container", tool_writes)
    result = step37._vibeic_gds_gates(project, "candidate", pdk_root, "processA",
                                     gds, routed, "magic", config)
    assert result["substance"]["rc"] == 0
    assert result["port_labels"]["rc"] == 1
    assert all(row["sha256"] for row in result.values())
    assert len(calls) == 2
    assert "--pdk-tech" in calls[1][0]
    assert all(kw["supervised"] is True for _cmd, kw in calls)
    assert {Path(kw["log"]).name for _cmd, kw in calls} == {
        "37-magic-substance.log", "37-magic-port_labels.log"}


@pytest.mark.parametrize("stage", ["stream", "dual_measurement"])
@pytest.mark.parametrize("code,status,reason", [
    ("LL_TOOL_STALLED", "NOT_MEASURED", "stalled"),
    ("LL_TOOL_DEADLINE", "NOT_MEASURED", "budget_exhausted"),
    ("LL_STEP_FAILED", "FAIL", ""),
])
def test_step37_books_supervisor_stop_without_a_design_failure(
        tmp_path, monkeypatch, stage, code, status, reason):
    runner = importlib.import_module("phase3_one_shot_runner")
    feedback = importlib.import_module("drc_feedback_repair")
    project = tmp_path / "project"
    pnr = runner._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    routed = pnr / "routed.def"
    routed.write_text("VERSION 5.8 ;\nDESIGN core ;\nEND DESIGN\n")
    (pnr / "core.def").write_bytes(routed.read_bytes())
    gds = pnr / "core.gds"
    monkeypatch.setattr(contract, "selected_mode", lambda *_a: (
        "dual" if stage == "dual_measurement" else "librelane"))
    monkeypatch.setattr(contract, "resolve_image", lambda *_a: "candidate")
    monkeypatch.setattr(contract, "resolve_pdk_root", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(runner, "_layout_basis", lambda *_a: ("basis", None))
    monkeypatch.setattr(runner._ga, "gate_passed", lambda *_a: True)
    monkeypatch.setattr(runner, "_vacuous_on_unrouted", lambda *_a: None)
    monkeypatch.setattr(feedback, "has_reviewed_rule", lambda *_a: False)
    monkeypatch.setattr(runner, "_streamout_top", lambda *_a: ("core", ""))
    monkeypatch.setattr(runner, "publish_database_unit_declaration",
                        lambda *_a: None)
    monkeypatch.setattr(runner, "publish_tapeout_declarations",
                        lambda *_a: None)

    def refused(*_a, **_k):
        raise contract.Refusal(code, "the tool did not complete")

    if stage == "stream":
        monkeypatch.setattr(step37, "run", refused)
    else:
        def direct(*_a, **_k):
            gds.write_bytes(b"direct stream")
            return runner.StepResult("gds", "PASS", 0, "direct stream")

        monkeypatch.setattr(runner, "_step_gds_direct", direct)
        monkeypatch.setattr(step37, "run", lambda *_a: {
            "gds": gds, "engine": "klayout", "state": project / "state.json"})
        monkeypatch.setattr(runner, "_gds_substance_gate", lambda *_a: None)
        monkeypatch.setattr(contract, "resolve_step_configs", lambda *_a, **_k: {})
        monkeypatch.setattr(contract, "execute_dual", refused)
    row = runner.step_gds(
        project, "core", SimpleNamespace(name="processA", drc_deck=None),
        "unused-container")
    assert row.status == status
    assert row.reason_class == reason
    assert code in row.detail
