"""v1.4.70 — the phase3 LVS gate must dispatch to the registry's device-level LVS
route (asap7 -> asap7_finfet_lvs.py) instead of printing the FALSE
'no magic/netgen setup -> ENV_UNAVAILABLE' for a PDK that ships a device_lvs_program.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402

_ASAP7_REG = {
    "device_lvs_program": "asap7_finfet_lvs.py",
    "cdl_netlist": "libs.tech/cdl/asap7sc7p5t_28_R.cdl",
    "klayout_lvs_tech": "libs.tech/klayout/lvs/asap7.lyt",
    "device_lvs_verified": {"compared": 208, "match": 159, "proven_negative": True},
}


def test_asap7_uses_device_lvs_route_not_false_env_unavailable(monkeypatch):
    monkeypatch.setattr(R, "_pdk_registry_entry",
                        lambda n: _ASAP7_REG if n == "asap7" else None)
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: True)  # klayout present
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    res = R.step_lvs(Path("/tmp/proj"), "top", pdk, "vibeic-eda", upstream_pnr=None)
    assert res.status == "WAIVED"
    assert res.extras.get("finding") == "LVS_DEVICE_LEVEL_AVAILABLE"
    assert res.extras.get("device_lvs_program") == "asap7_finfet_lvs.py"
    assert res.extras.get("lvs_method") == "klayout_device_geometric"
    # the shipped library verification is surfaced, and it is NOT the false ENV msg
    assert "159/208" in res.detail
    assert "NOT an ENV gap" in res.detail
    assert "netgen setup" not in res.detail  # the old misleading wording is gone


def test_device_route_klayout_missing_names_klayout_not_netgen(monkeypatch):
    monkeypatch.setattr(R, "_pdk_registry_entry",
                        lambda n: _ASAP7_REG if n == "asap7" else None)
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: False)  # klayout absent
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    res = R.step_lvs(Path("/tmp/proj"), "top", pdk, "vibeic-eda", upstream_pnr=None)
    assert res.status == "ENV_UNAVAILABLE"
    assert res.extras.get("missing_tool") == "klayout"  # klayout, NOT magic/netgen


def test_non_device_pdk_does_not_take_device_route(monkeypatch):
    # a PDK with no device_lvs_program must NOT hit the device route; it falls
    # through to the netgen path (here: magic/netgen absent -> the old ENV branch).
    monkeypatch.setattr(R, "_pdk_registry_entry", lambda n: {})
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: False)
    pdk = types.SimpleNamespace(name="sky130A", calibre_lvs=None)
    res = R.step_lvs(Path("/tmp/proj"), "top", pdk, "vibeic-eda", upstream_pnr=None)
    assert res.extras.get("finding") != "LVS_DEVICE_LEVEL_AVAILABLE"


def test_upstream_pnr_fail_still_skips_before_device_route(monkeypatch):
    # the upstream-pnr SKIP guard stays first (device route must not mask a dead pnr)
    monkeypatch.setattr(R, "_pdk_registry_entry", lambda n: _ASAP7_REG)
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: True)
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    bad = types.SimpleNamespace(status="ROUTE_NOT_CONVERGED", detail="died")
    res = R.step_lvs(Path("/tmp/proj"), "top", pdk, "vibeic-eda", upstream_pnr=bad)
    assert res.status == "SKIP"
