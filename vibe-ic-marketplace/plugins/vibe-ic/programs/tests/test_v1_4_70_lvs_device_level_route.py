"""v1.4.70 — the phase3 LVS gate must dispatch to the registry's device-level LVS
route (asap7 -> asap7_finfet_lvs.py) instead of printing the FALSE
'no magic/netgen setup -> ENV_UNAVAILABLE' for a PDK that ships a device_lvs_program.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402
from _finished_gds_fixture import publish_finished_gds

_ASAP7_REG = {
    "device_lvs_program": "asap7_finfet_lvs.py",
    "cdl_netlist": "libs.tech/cdl/asap7sc7p5t_28_R.cdl",
    "klayout_lvs_tech": "libs.tech/klayout/lvs/asap7.lyt",
    "device_lvs_verified": {"compared": 208, "match": 159, "proven_negative": True},
}


def _state_project(tmp_path):
    views = {}
    for name in ("gds", "def", "nl"):
        view = tmp_path / ("final." + name)
        view.write_text("native " + name)
        views[name] = str(view)
    (tmp_path / "state_out.json").write_text(json.dumps(views))
    publish_finished_gds(tmp_path)
    return tmp_path


def test_asap7_uses_device_lvs_route_not_false_env_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_pdk_registry_entry", lambda n: _ASAP7_REG)
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: True)
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    monkeypatch.setattr(R, "_docker_exec", lambda *a, **kw: (
        0, 'A7_DESIGN_LVS {"verdict":"MATCH","power_shorts":0}', ""))
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    res = R.step_lvs(_state_project(tmp_path), "top", pdk, "vibeic-eda", _direct=True)
    assert res.status == "PASS"
    assert res.extras["finding"] == "LVS_MATCH"
    assert res.extras["device_lvs_program"] == "asap7_finfet_lvs.py"
    assert res.extras["lvs_engine"] == "asap7_device_klayout"


def test_device_route_klayout_missing_names_klayout_not_netgen(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_pdk_registry_entry", lambda n: _ASAP7_REG)
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: False)
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    res = R.step_lvs(_state_project(tmp_path), "top", pdk, "vibeic-eda", _direct=True)
    assert res.status == "NOT_MEASURED"
    assert res.extras["missing_tool"] == "klayout"


def test_non_device_pdk_does_not_take_device_route(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_pdk_registry_entry", lambda n: {})
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: False)
    pdk = types.SimpleNamespace(name="sky130A", calibre_lvs=None)
    res = R.step_lvs(_state_project(tmp_path), "top", pdk, "vibeic-eda", _direct=True)
    assert res.extras.get("finding") != "LVS_DEVICE_LEVEL_AVAILABLE"


def test_upstream_pnr_fail_still_skips_before_device_route(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_pdk_registry_entry", lambda n: _ASAP7_REG)
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: True)
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    bad = types.SimpleNamespace(status="FAIL", detail="ROUTE_NOT_CONVERGED: died", extras={})
    res = R.step_lvs(tmp_path, "top", pdk, "vibeic-eda", upstream_pnr=bad, _direct=True)
    assert res.status == "NOT_MEASURED"
    assert res.reason_class == "upstream_failed"
