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
