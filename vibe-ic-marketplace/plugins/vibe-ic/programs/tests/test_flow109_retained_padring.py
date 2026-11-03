"""The public row reads native pad/PDN results without replaying placement."""
import copy
import json
from types import SimpleNamespace

import pytest

import _delivery_route
import flow109


def _write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))


def _case(project, *, pad_errors=0, pdn_errors=0, connectivity_errors=0):
    features = copy.deepcopy(next(p["features"] for p in flow109.load_registry()["reference_profiles"]
        if p["name"] == "Small digital IC without DFT"))
    manifest = project / "manifest.json"
    _write(manifest, {"features": features})
    assert _delivery_route.admit(project, "ic") is None
    states = []
    for step, errors in (("OpenROAD.PadRing", pad_errors), ("OpenROAD.GeneratePDN", pdn_errors)):
        path = project / "native" / step / "state_out.json"
        values = {"flow__errors__count": errors}
        if step == "OpenROAD.GeneratePDN":
            values["design__power_grid_violation__count"] = connectivity_errors
        _write(path, {"metrics": values})
        states.append({"step": step, "state": str(path)})
    _write(project / "reports/phase3/execution-backend-15.json", {"states": states})
    return SimpleNamespace(flow="109", flow109_manifest=manifest, flow109_plan_only=False,
        execution_mode="default", entry_step="D32", exit_step="D32", container="")


@pytest.mark.parametrize("counts,rc,status", [
    ({}, 0, "PASS"),
    ({"pad_errors": 1}, 1, "FAIL"),
    ({"pdn_errors": 2}, 1, "FAIL"),
    ({"connectivity_errors": 1}, 1, "FAIL"),
    ({"connectivity_errors": None}, 2, "NOT_MEASURED"),
    ({"connectivity_errors": -1}, 2, "NOT_MEASURED"),
    ({"connectivity_errors": True}, 2, "NOT_MEASURED"),
])
def test_public_padring_row_uses_native_error_limit(tmp_path, counts, rc, status):
    args = _case(tmp_path, **counts)
    assert flow109.prepare_front_door(args, tmp_path) == rc
    row = json.loads((tmp_path / "reports/flow109/default_rows/D32.json").read_text())
    assert row["default_row_status"] == status
    if status == 'NOT_MEASURED':
        assert row['reason'] == 'D32_NATIVE_REPORT_UNAVAILABLE'
    assert row["completed"] is (status == "PASS")
    assert not (tmp_path / "reports/phase3/default_steps/15.5ic/backend_result.json").exists()


def test_native_failure_survives_a_missing_later_report(tmp_path):
    args = _case(tmp_path, pad_errors=1)
    (tmp_path / "native/OpenROAD.GeneratePDN/state_out.json").unlink()
    assert flow109.prepare_front_door(args, tmp_path) == 1


def test_unmeasured_native_report_stays_open(tmp_path):
    args = _case(tmp_path)
    (tmp_path / "native/OpenROAD.GeneratePDN/state_out.json").unlink()
    assert flow109.prepare_front_door(args, tmp_path) == 2


def test_fresh_padring_keeps_the_native_execution_path(tmp_path):
    args = _case(tmp_path)
    (tmp_path / "reports/phase3/execution-backend-15.json").unlink()
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert args.entry_step == args.exit_step == "15.5ic"


@pytest.mark.parametrize("row", ["D31", "D35", "D37", "D40"])
@pytest.mark.parametrize("bad", [False, True])
def test_public_backend_rows_read_completed_native_steps(tmp_path, row, bad):
    args = _case(tmp_path)
    args.entry_step = args.exit_step = row
    manifest = json.loads(args.flow109_manifest.read_text())
    manifest["features"]["requires_spares"] = True
    _write(args.flow109_manifest, manifest)
    plan = flow109.resolve_plan(manifest["features"])
    spec = flow109.resolve_step(plan, row)
    steps = spec["profile"]["native_steps"]
    root = tmp_path / "native"
    anchor = root / "OpenROAD.Floorplan/state_out.json"
    _write(anchor, {"metrics": {"flow__errors__count": 0}})
    for step in steps:
        values = {"flow__errors__count": 0, "design__violations": 0,
            "vibeic__spare__planned": 8, "vibeic__spare__inserted": 8,
            "vibeic__spare__tieoff__candidates": 16, "vibeic__spare__tieoff__connected": 16,
            "vibeic__spare__pg__unconnected": 0,
            "vibeic__spare__check_placement__violations": 0,
            "route__drc_errors_final": 0, "design__critical_disconnected_pin__count": 0}
        if step == steps[-1] and bad:
            values["flow__errors__count"] = 1
        _write(root / step / "state_out.json", {"metrics": values})
        _write(root / step / "config.json", {"meta": {"step": step}})
    _write(tmp_path / "reports/phase3/execution-backend-15.json",
           {"states": [{"step": "OpenROAD.Floorplan", "state": str(anchor)}]})
    assert flow109.prepare_front_door(args, tmp_path) == (1 if bad else 0)
    record = json.loads((tmp_path / f"reports/flow109/default_rows/{row}.json").read_text())
    assert record["default_row_status"] == ("FAIL" if bad else "PASS")


@pytest.mark.parametrize("row", ["D38", "D39"])
@pytest.mark.parametrize("bad", [None, "setup", "hold"])
def test_cts_and_repair_use_their_own_sta_and_report_interim_drv(tmp_path, row, bad):
    args = _case(tmp_path)
    args.entry_step = args.exit_step = row
    root = tmp_path / "native"
    anchor = root / "00-floorplan/state_out.json"
    _write(anchor, {"metrics": {"flow__errors__count": 0}})
    stages = ["OpenROAD.STAMidPNR", "OpenROAD.CTS", "OpenROAD.STAMidPNR",
              "OpenROAD.ResizerTimingPostCTS", "OpenROAD.STAMidPNR", "OpenROAD.STAMidPNR"]
    own = 3 if row == "D38" else 5
    for ordinal, step in enumerate(stages, 1):
        folder = root / f"{ordinal:02}-{step}"
        values = {"flow__errors__count": 0, "timing__setup__ws": 2.0, "timing__hold__ws": 0.2,
                  "design__max_slew_violation__count": 17, "design__max_cap_violation__count": 11,
                  "design__max_fanout_violation__count": 5}
        if ordinal in (1, 6):
            values["timing__setup__ws"] = -100.0
        if ordinal == own and bad:
            values[f"timing__{bad}__ws"] = -0.1
        _write(folder / "config.json", {"meta": {"step": step}})
        _write(folder / "state_out.json", {"metrics": values})
        if step == "OpenROAD.CTS":
            (folder / "cts.rpt").write_text(
                "Total number of Buffers Inserted: 2.\nTotal number of Sinks: 3.\n")
    _write(tmp_path / "reports/phase3/execution-backend-15.json",
           {"states": [{"step": "OpenROAD.Floorplan", "state": str(anchor)}]})
    assert flow109.prepare_front_door(args, tmp_path) == (1 if bad else 0)
    record = json.loads((tmp_path / f"reports/flow109/default_rows/{row}.json").read_text())
    assert record["intermediate_drv"]["slew"] == 17
    assert record["intermediate_drv"]["cap"] == 11
    assert record["intermediate_drv"]["fanout"] == 5
    assert record["timing"]["report"] == str(root / f"{own:02}-OpenROAD.STAMidPNR/state_out.json")


@pytest.mark.parametrize("row", ["D35", "D37", "D38", "D39", "D40"])
def test_an_earlier_native_chain_does_not_prevent_fresh_backend_execution(tmp_path, row):
    args = _case(tmp_path)
    manifest = json.loads(args.flow109_manifest.read_text())
    manifest["features"]["requires_spares"] = True
    _write(args.flow109_manifest, manifest)
    args.entry_step = args.exit_step = row
    assert flow109.prepare_front_door(args, tmp_path) is None


@pytest.mark.parametrize("metric", ["max_slew_vio", "max_cap_vio", "max_fanout_vio"])
def test_final_electrical_keeps_its_native_drv_limits(metric):
    import librelane_signoff as signoff
    context = flow109.execution_context(flow109.resolve_plan(
        next(p["features"] for p in flow109.load_registry()["reference_profiles"]
             if p["name"] == "Small digital IC without DFT")), "D70", "D70")
    assert flow109.source_owned_native_dispatch(context["resolved_row"])["adapter"] == "flow109_final_electrical"
    corner = {name: 0 for name in signoff.TIMING_METRICS}
    corner.update(setup_ws=1.0, hold_ws=0.1, ideal_clocks=[], derate={"declared": False})
    corner[metric] = 1
    assert signoff.judge_timing({"nominal": corner})["verdict"] == "FAIL"
