"""Exercise table dispatch without running a benchmark or external EDA job."""
from copy import deepcopy

import pytest

import flow_engine as engine
import flow_native_adapters as adapters
from flow_engine_frontend import OwnerSession


TABLE = engine.read_json(engine.TABLE)


def leaves(tool):
    if tool.get("kind") == "profiles":
        for profile in tool["profiles"]:
            yield from leaves(profile["tool"])
    else:
        yield tool


CASES = [(row, index, tool) for row in TABLE["steps"]
         for index, tool in enumerate(leaves(row["tool"]))]


@pytest.mark.parametrize("row,index,tool", CASES,
                         ids=[f"{row['name']}:{index}" for row, index, _ in CASES])
def test_every_table_tool_dispatches_or_reports_unmeasured_reason(tmp_path, monkeypatch, row, index, tool):
    ran = engine.ToolResult(True, 0)
    called = []

    def executed(*args, **kwargs):
        called.append(True)
        return ran

    monkeypatch.setattr(engine.NativeChain, "execute", executed)
    monkeypatch.setattr(engine.NativeChain, "snapshot", executed)
    monkeypatch.setattr(engine, "command_tool", executed)
    monkeypatch.setattr(OwnerSession, "result", lambda *args, **kwargs: vars(executed()))
    native_adapter = adapters.execute

    def adapter(project, directory, selected, route, **kwargs):
        if selected.get("adapter") in {*adapters.ADAPTERS, "eqy", "xor", "gls", "implemented_cdc",
                                       "ir_drop", "tapeout_precheck", "physical_declarations", "functional_activity"}:
            return vars(executed())
        return native_adapter(project, directory, selected, route, **kwargs)

    monkeypatch.setattr(adapters, "execute", adapter)
    neutral = {"name": row["name"], "title": row["title"], "when": "always", "legacy_id": {},
               "tool": {**deepcopy(tool), "parallel": False}, "checks": []}
    route = {"entry_step": row["name"], "verify_through": row["name"],
             "delivery_target": "rtl", "input_contract": "structured"}
    result = engine.run(tmp_path, table={"steps": [neutral]}, route=route)["steps"][0]
    if (not called and tool["kind"] not in {"aggregate", "native_report"}) or not result["tool_ran"]:
        assert not result["tool_ran"], (row["name"], index, result)
        assert result["status"] == "NOT_MEASURED", (row["name"], index, result)
        assert result["detail"].strip(), (row["name"], index, result)
    else:
        assert result["status"] == "PASS", (row["name"], index, result)


@pytest.mark.parametrize("row", [row for row in TABLE["steps"]
    if row["when"] is False or str(row["when"]).strip().lower() == "false"], ids=lambda row: row["name"])
def test_disabled_table_rows_name_their_replacement_steps(row):
    names = {row["name"] for row in TABLE["steps"]}
    replacements = row.get("merged_into", [])
    assert replacements, f"{row['name']}: when False must name merged_into steps"
    assert isinstance(replacements, list) and all(
        name in names and name != row["name"] for name in replacements), row["name"]
    assert row.get("applicability_reason", "").strip(), row["name"]
