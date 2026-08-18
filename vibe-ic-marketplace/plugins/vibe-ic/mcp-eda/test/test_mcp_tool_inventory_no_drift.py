#!/usr/bin/env python3
"""Drift guard: the committed MCP_TOOL_INVENTORY.json MUST match what the code
registers. This is the single source of truth for the website/docs tool count
(vibeic.ai/#mcp), which previously hand-drifted (claimed 48 while the server
registered 47). If a tool is added/removed without regenerating the inventory,
this test fails — forcing `python3 tools/gen_mcp_tool_inventory.py` to be re-run.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "tools" / "gen_mcp_tool_inventory.py"
INV = ROOT / "MCP_TOOL_INVENTORY.json"


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_mcp_tool_inventory", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_inventory_matches_code() -> None:
    code = _load_gen().discover()
    committed = json.loads(INV.read_text())
    assert committed["all_tools"] == code["all_tools"], (
        "MCP_TOOL_INVENTORY.json is stale vs the code. Re-run "
        "`python3 tools/gen_mcp_tool_inventory.py`. "
        f"committed total={committed.get('total')} code total={code['total']}"
    )


def test_total_equals_enumeration() -> None:
    inv = json.loads(INV.read_text())
    assert inv["total"] == len(inv["all_tools"]) == len(set(inv["all_tools"]))
    assert inv["total"] == (inv["by_category"]["eda"]
                            + inv["by_category"]["device"]
                            + inv["by_category"]["other"])


def test_known_categories_present() -> None:
    inv = json.loads(INV.read_text())
    # camera device tools must be counted as device (the website omitted them)
    assert "device_camera_capture" in inv["device_tools"]
    assert "device_camera_led_diff" in inv["device_tools"]
    assert "mcp_server_health_check" in inv["other_tools"]
