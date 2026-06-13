# Contributing — NEW_DEVICE

This is a focused per-topic guide. For the umbrella partner-plugin layout
+ submission workflow, see [`CONTRIBUTING_PARTNER_PLUGIN.md`](./CONTRIBUTING_PARTNER_PLUGIN.md).

## What you ship

```
mcp-eda/src/devices/<class>/<vendor>/
  manifest.json               REQUIRED
  driver.py | driver.js | driver.go | ... — exec'd by MCP server
  README.md                   REQUIRED
  test/test_<vendor>.py       REQUIRED — at least one smoke test
```

## manifest.json schema (subset)

```json
{
  "vendor": "vendor",
  "vendor_full_name": "Vendor (example)",
  "device_class": "tester",
  "supported_models": ["Model-1234"],
  "permissions": ["require_group:plugdev"],
  "tools": [
    {
      "name": "device_<class>_<vendor>_<verb>",
      "description": "What this tool does and when to use it.",
      "driver": "driver.py",
      "tool_mode": "<verb>",
      "mode": "hw",
      "timeout_sec": 15,
      "schema": {
        "<arg>": {"type": "<type>", "description": "..."}
      }
    }
  ]
}
```

## Auto-registration

`mcp-eda/src/devices/_registry.js` walks `src/devices/**/manifest.json` at MCP server start. Drop your manifest, restart the server, your tools appear in Claude Code's MCP toolset. No edits to `src/index.js` required.

## Driver contract

- Read `--mode <verb>` and `--json-args '<json>'` from CLI
- Write a single JSON object to stdout (`{"success": bool, "mode": "...", ...}`)
- Exit 0 on PASS, 1 on FAIL, 2 on input error

The reference implementation is `mcp-eda/src/devices/tester/vendor-usb_hid_tester/driver.py`.
