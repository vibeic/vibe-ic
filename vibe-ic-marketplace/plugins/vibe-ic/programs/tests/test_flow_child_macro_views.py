"""Declared children must run before the wrapper can consume native views."""
import json
from pathlib import Path
import subprocess

import pytest

import flow_engine as engine
import flow_native_adapters as adapters


def project(root, child_config=True):
    docs = root / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "neutral_wrapper",
        "hard_macros": [{"name": "compute_tile", "hardening_required": True}]}))
    (docs / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({"pdk_target": "neutral_pdk"}))
    source = root / "input/design_src"
    source.mkdir(parents=True)
    (source / "tile.v").write_text("module compute_tile(input a, output z); assign z=a; endmodule\n")
    definitions = {k: [str(source / f"views/tile.{ext}")] for k, ext in
                   [("gds", "gds"), ("lef", "lef"), ("nl", "v")]}
    definitions.update(lib={"*": [str(source / "views/tile.lib")]},
                       spef={"min_*": [str(source / "views/tile.min.spef")]},
                       instances={"u_tile": {"location": [48, 24], "orientation": "N"}})
    (source / "wrapper.json").write_text(json.dumps({"DESIGN_NAME": "neutral_wrapper",
        "MACROS": {"compute_tile": definitions}}))
    if child_config:
        (source / "child.json").write_text(json.dumps({"DESIGN_NAME": "compute_tile",
            "VERILOG_FILES": [str(source / "tile.v")], "DEFAULT_CORNER": "nom_neutral"}))
    return source


@pytest.mark.parametrize("failure", [False, True, "crash", "metric"])
def test_child_native_production_and_failure_reach_macro_step(tmp_path, monkeypatch, failure):
    source = project(tmp_path)
    calls = []

    def public_run(commands, argv, **kwargs):
        calls.append(list(map(str, argv)))
        child = Path(argv[2])
        if failure == "crash":
            return subprocess.CompletedProcess(argv, 9, "", "public child startup failure")
        report = child / "reports/flow_engine.json"
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({"fail": int(bool(failure)), "steps": [{"name": "synthesis",
            "status": "FAIL" if failure else "PASS", "tool_exit_code": 7 if failure is True else 0,
            "detail": "native synthesis failure" if failure else "native outputs",
            "native_steps": [{"name": "Native", "ran": True, "exit_code": 0, "status": "PASS"}]}]}))
        if not failure:
            final = child / "phase3/stage4/hardmacro"
            final.mkdir(parents=True)
            state = {}
            for key, ext in [("gds", "gds"), ("lef", "lef"), ("nl", "v")]:
                path = final / f"tile.{ext}"; path.write_text(f"native {key}\n"); state[key] = str(path)
            for key, corners, ext in [("lib", ["nom_neutral", "min_neutral"], "lib"),
                                      ("spef", ["min"], "spef")]:
                state[key] = {}
                for corner in corners:
                    path = final / f"tile.{corner}.{ext}"; path.write_text(f"native {key} {corner}\n")
                    state[key][corner] = str(path)
            native_step = child / "steps/synthesis"
            native_step.mkdir(parents=True)
            (native_step / "state_out.json").write_text(json.dumps(state))
        return subprocess.CompletedProcess(argv, 1 if failure else 0, "", "")

    monkeypatch.setattr(adapters.Commands, "run", public_run)
    table = engine.read_json(engine.TABLE)
    report = engine.run(tmp_path, table=table,
        route={"delivery_target": "ip_hardmacro", "entry_step": "D1", "verify_through": "37.5ip"},
        from_name="macro_logical_and_timing_views", to_name="macro_logical_and_timing_views")
    row = report["steps"][0]
    assert row["status"] == ("FAIL" if failure else "PASS")
    assert len(calls) == 1 and "--route" in calls[0] and "ip" in calls[0]
    assert "37.5ip" in calls[0] and "compute_tile" in calls[0]
    if failure:
        assert ("public entry exited 9" if failure == "crash" else "native synthesis failure") in row["detail"]
        assert not (source / "views/tile.gds").exists()
    else:
        assert (source / "views/tile.gds").is_symlink()
        config = engine.read_json(tmp_path / "work/flow/native_overrides.json")
        macro = config["MACROS"]["compute_tile"]
        assert set(macro["lib"]) == {"nom_neutral", "min_neutral"}
        assert macro["instances"]["u_tile"] == {"location": [48, 24], "orientation": "N"}
        assert Path(macro["lib"]["min_neutral"][0]).read_text() == "native lib min_neutral\n"
        # Unchanged native outputs satisfy the consumer without another child run.
        adapters.execute(tmp_path, tmp_path / "recheck", {"adapter": "macro_views"},
                         {"delivery_target": "ip_hardmacro"})
        assert len(calls) == 1
        assert set(engine.read_json(tmp_path / "work/flow/native_overrides.json")["MACROS"]["compute_tile"]["lib"]) == {"nom_neutral", "min_neutral"}


def test_declared_child_without_its_supplied_config_is_unmeasured(tmp_path):
    project(tmp_path, child_config=False)
    result = adapters.execute(tmp_path, tmp_path / "step", {"adapter": "macro_views"},
                              {"delivery_target": "ip_hardmacro"})
    assert engine.evaluate(engine.ToolResult(**result), []) == "NOT_MEASURED"
    assert "compute_tile" in result["detail"] and "supplied" in result["detail"]


def test_existing_consumed_views_do_not_need_a_child_config_or_another_run(tmp_path):
    project(tmp_path, child_config=False)
    root = tmp_path / "input/pdk_local/tile"
    root.mkdir(parents=True)
    (root / "tile.lef").write_text("MACRO compute_tile\n CLASS BLOCK ;\nEND compute_tile\n")
    (root / "tile.gds").write_text("existing staged view\n")
    (root / "tile.lib").write_text("library(tile) { cell(compute_tile) {} }\n")
    result = adapters.execute(tmp_path, tmp_path / "step", {"adapter": "macro_views"},
                              {"delivery_target": "ip_hardmacro"})
    assert engine.evaluate(engine.ToolResult(**result), []) == "PASS"
    assert not (tmp_path / "work/flow/children").exists()
