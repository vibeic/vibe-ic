"""Security rows use supplied security proofs and retain unmeasured targets."""
import pytest

import flow_engine as engine
import flow_native_adapters as adapters


@pytest.mark.parametrize("failures,status", [(0, "NOT_MEASURED"), (1, "FAIL"), (None, "NOT_MEASURED")])
def test_security_row_uses_native_formal_count(tmp_path, monkeypatch, failures, status):
    root = tmp_path / "phase2/stage1/formal/security"
    root.mkdir(parents=True)
    deck = root / "access_control.sby"
    deck.write_text("")
    calls = []

    def formal(project, directory, tool, commands):
        calls.append(tool)
        assert tool["properties"] == [deck]
        return {"ran": True, "exit_code": 0,
                "metrics": {"unproved_required_properties": failures} if failures is not None else {},
                "detail": "Native SBY result"}

    monkeypatch.setattr(adapters, "formal", formal)
    row = next(row for row in engine.read_json(engine.TABLE)["steps"]
               if row["name"] == "requirement_derived_security_verification")
    tool = engine.choose_tool(row["tool"], {"has_analog": False, "has_digital": True})
    native = engine.ToolResult(**adapters.execute(tmp_path, tmp_path / "step", tool, {}))
    assert len(calls) == 1
    assert "security_metric_targets" not in native.metrics
    measured = engine.measure(row["checks"], native.metrics, {}, {"requires_security": True})
    assert engine.evaluate(native, measured) == status


def test_security_row_does_not_substitute_generic_formal(tmp_path, monkeypatch):
    root = tmp_path / "phase2/stage1/formal"
    root.mkdir(parents=True)
    (root / "reset.sby").write_text("")
    monkeypatch.setattr(adapters, "formal", lambda *args: pytest.fail("Generic reset proof was selected"))
    row = next(row for row in engine.read_json(engine.TABLE)["steps"]
               if row["name"] == "requirement_derived_security_verification")
    tool = engine.choose_tool(row["tool"], {"has_analog": False, "has_digital": True})
    result = adapters.execute(tmp_path, tmp_path / "step", tool, {})
    assert not result["ran"] and result["metrics"] == {}
