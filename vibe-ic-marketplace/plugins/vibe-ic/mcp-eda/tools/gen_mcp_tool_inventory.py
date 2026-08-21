#!/usr/bin/env python3
"""
gen_mcp_tool_inventory.py — single source of truth for the MCP tool count.

The website (vibeic.ai/#mcp) historically hand-maintained the tool
count and drifted (claimed 48 while the server actually registered 47).
This script derives the authoritative inventory DIRECTLY from the code
so the number can never drift again:

  * src/index.js          — every `server.tool("<name>", ...)` registration
  * devices_registry.json — every device class's `tools_exposed[]`
  * src/devices/_registry.js — the static `eda_device_list` introspection tool

It writes MCP_TOOL_INVENTORY.json (the artifact the website/docs should read) and
prints the total + category breakdown. `--check` fails (exit 1) if the committed
inventory is stale vs the code — wire it into CI to catch drift.

Usage:
  python3 tools/gen_mcp_tool_inventory.py            # regenerate + print
  python3 tools/gen_mcp_tool_inventory.py --check    # verify committed == code
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # mcp-eda/
INDEX_JS = ROOT / "src" / "index.js"
REGISTRY_JSON = ROOT / "devices_registry.json"
REGISTRY_JS = ROOT / "src" / "devices" / "_registry.js"
OUT = ROOT / "MCP_TOOL_INVENTORY.json"


def discover() -> dict:
    tools: set[str] = set()
    src_index = INDEX_JS.read_text()
    # server.tool("name", ...) — name on the same or next line after the paren.
    tools |= set(re.findall(r'server\.tool\(\s*"([a-z0-9_]+)"', src_index))
    tools |= set(re.findall(r'server\.tool\(\s*\n\s*"([a-z0-9_]+)"', src_index))

    # device tools auto-registered per manifest (devices_registry.json snapshot).
    reg = json.loads(REGISTRY_JSON.read_text())
    for dev in reg.get("devices", []):
        tools |= set(dev.get("tools_exposed", []))

    # static introspection tool registered in _registry.js (not in index.js).
    if REGISTRY_JS.exists() and 'eda_device_list' in REGISTRY_JS.read_text():
        tools.add("eda_device_list")

    eda = sorted(t for t in tools if t.startswith("eda_"))
    device = sorted(t for t in tools if t.startswith("device_"))
    other = sorted(t for t in tools if not t.startswith(("eda_", "device_")))
    return {
        "schema_version": 1,
        "_comment": "AUTHORITATIVE MCP tool inventory — generated from code by "
                    "tools/gen_mcp_tool_inventory.py. Do NOT hand-edit; the website "
                    "tool count must read `total` from here.",
        "total": len(tools),
        "by_category": {"eda": len(eda), "device": len(device), "other": len(other)},
        "eda_tools": eda,
        "device_tools": device,
        "other_tools": other,
        "all_tools": sorted(tools),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if committed MCP_TOOL_INVENTORY.json != code-derived")
    a = ap.parse_args()
    inv = discover()

    if a.check:
        if not OUT.exists():
            print(f"FAIL: {OUT.name} missing — run without --check to generate"); sys.exit(1)
        committed = json.loads(OUT.read_text())
        if committed.get("all_tools") != inv["all_tools"]:
            cset, iset = set(committed.get("all_tools", [])), set(inv["all_tools"])
            print(f"FAIL: inventory drift. total committed={committed.get('total')} "
                  f"code={inv['total']}")
            if iset - cset: print(f"  in code but not committed: {sorted(iset - cset)}")
            if cset - iset: print(f"  committed but not in code: {sorted(cset - iset)}")
            sys.exit(1)
        print(f"OK: inventory matches code — {inv['total']} tools "
              f"({inv['by_category']})"); sys.exit(0)

    OUT.write_text(json.dumps(inv, indent=2) + "\n")
    print(f"wrote {OUT}")
    print(f"TOTAL MCP TOOLS = {inv['total']}  "
          f"(eda={inv['by_category']['eda']}, device={inv['by_category']['device']}, "
          f"other={inv['by_category']['other']})")
    print("device_tools:", inv["device_tools"])
    print("other_tools :", inv["other_tools"])


if __name__ == "__main__":
    main()
