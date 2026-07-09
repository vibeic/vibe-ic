"""test_pdk_device_map.py — R13 generic->foundry device-map accessor (v1.3.54).

Covers: the real IHP SG13G2 map is populated + consistent (device_map values
all present in device_models), the accessor resolves a generic role, and the
registry-wide validate() is clean (regression guard for future drift). No
chip/SKU literal — only PDK family names + generic role tokens.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pdk_device_map as pdm

PROG = Path(__file__).resolve().parent.parent / "pdk_device_map.py"


def test_ihp_sg13g2_map_populated():
    dm = pdm.device_map("ihp-sg13g2")
    assert dm.get("nmos") == "sg13_lv_nmos"
    assert dm.get("pmos") == "sg13_lv_pmos"
    assert dm.get("cap_mim") == "cap_cmim"
    # generic, PDK-agnostic accessor resolves a single role too
    assert pdm.foundry_model("ihp-sg13g2", "nmos_hv") == "sg13_hv_nmos"


def test_map_values_are_in_device_models():
    """Every mapped foundry model must be a legal token in device_models."""
    models = set(pdm.device_models("ihp-sg13g2"))
    assert models, "ihp-sg13g2 should have a device_models flat set"
    for generic, foundry in pdm.device_map("ihp-sg13g2").items():
        assert foundry in models, f"{generic}->{foundry} not in device_models"


def test_validate_registry_clean():
    """Regression guard — the whole registry's device_map<->device_models
    consistency holds (empty problem list)."""
    assert pdm.validate() == []


def test_unknown_pdk_and_role_are_empty_not_crash():
    assert pdm.device_map("no-such-pdk") == {}
    assert pdm.foundry_model("ihp-sg13g2", "no-such-role") is None
    # a PDK with no device_map (sky130A stays as-is) returns {}
    assert pdm.device_map("sky130A") == {}


def test_cli_validate_exit0(tmp_path: Path):
    r = subprocess.run([sys.executable, str(PROG), "--validate"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_cli_resolve_generic():
    r = subprocess.run(
        [sys.executable, str(PROG), "--pdk", "ihp-sg13g2",
         "--generic", "pmos"], capture_output=True, text=True)
    assert r.returncode == 0
    assert r.stdout.strip() == "sg13_lv_pmos"
