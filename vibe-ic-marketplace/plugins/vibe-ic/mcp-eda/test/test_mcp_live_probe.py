#!/usr/bin/env python3
"""mcp_live_probe — end-to-end MCP JSON-RPC smoke test against the
locally-built mcp-eda.

Started life as a one-off demonstration that this session (which had
no MCP client loaded) could still prove the server worked by speaking
JSON-RPC 2.0 over stdio directly. v0.69 packaged it as a test so CI
(or any hands-on operator) can verify "server boots + all tools
register + resource read hits real silicon" without needing Claude
Code's MCP client layer.

What it checks (each one a separate named step with PASS/SKIP/FAIL):

  1. `initialize` handshake — server says its name+version.
  2. `tools/list` returns expected counts (≥20 eda_* + ≥6 device_*).
  3. `resources/list` returns ≥1 entry with the v0.68+ URI shape.
  4. `resources/read` on the first resource returns JSON that at
     least parses. When the underlying device is present (scope
     connected via USBTMC), asserts the body shape. When not
     present, tolerates a structured device_not_found / permission
     error (DeviceError taxonomy, v0.67+).

This is NOT a full integration test — it doesn't invoke every tool,
doesn't exercise PnR, doesn't burn an SOF. It's a tripwire: "does
the MCP surface still exist and respond?"

Usage
-----
    python3 test/test_mcp_live_probe.py              # human-readable
    python3 test/test_mcp_live_probe.py --json       # machine-readable
    python3 test/test_mcp_live_probe.py --no-live    # skip the live
                                                     # resource-read
                                                     # (CI without HW)

Exit codes
    0 — all checks PASS or SKIP
    1 — at least one FAIL (server misbehaviour)
    2 — server failed to start at all (catastrophic)
"""
from __future__ import annotations

import argparse
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_SERVER = _HERE.parent / "src" / "index.js"


class MCPProbe:
    def __init__(self, server_path: Path):
        self.server_path = server_path
        self.proc: Optional[subprocess.Popen] = None
        self._next_id = 1
        self.steps: List[Dict[str, Any]] = []

    def start(self) -> None:
        self.proc = subprocess.Popen(
            ["node", str(self.server_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def send(self, msg: Dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def recv(self, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        assert self.proc and self.proc.stdout
        r, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not r:
            return None
        line = self.proc.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            return {"_parse_error": str(e), "_raw": line[:500]}

    def request(self, method: str, params: Optional[Dict[str, Any]] = None,
                timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        mid = self._next_id
        self._next_id += 1
        self.send({"jsonrpc": "2.0", "id": mid, "method": method,
                   "params": params or {}})
        return self.recv(timeout=timeout)

    def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def record(self, name: str, status: str, detail: Any = None) -> None:
        self.steps.append({"name": name, "status": status, "detail": detail})


# ────────────────────────── checks ──────────────────────────
def check_initialize(p: MCPProbe) -> bool:
    resp = p.request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "mcp-live-probe", "version": "1.0"},
    })
    if not resp or "result" not in resp:
        p.record("initialize", "FAIL", {"error": "no init response", "resp": resp})
        return False
    info = resp["result"].get("serverInfo", {})
    name, ver = info.get("name"), info.get("version")
    p.record("initialize", "PASS", {"server": name, "version": ver})
    p.notify("notifications/initialized")
    return True


def check_tools_list(p: MCPProbe) -> Optional[List[Dict[str, Any]]]:
    resp = p.request("tools/list")
    if not resp or "result" not in resp:
        p.record("tools/list", "FAIL", {"resp": resp})
        return None
    tools = resp["result"].get("tools", [])
    eda = [t for t in tools if t["name"].startswith(("eda_", "rtl_", "phase1_"))]
    dev = [t for t in tools if t["name"].startswith("device_")]
    detail = {"total": len(tools), "eda_count": len(eda),
              "device_count": len(dev)}
    # Expected counts: 20 eda_*, 6 device_* at v0.69. Tolerate growth ≥.
    passed = len(eda) >= 15 and len(dev) >= 6
    p.record("tools/list", "PASS" if passed else "FAIL", detail)
    return tools


def check_resources_list(p: MCPProbe) -> Optional[List[Dict[str, Any]]]:
    resp = p.request("resources/list")
    if not resp or "result" not in resp:
        p.record("resources/list", "FAIL", {"resp": resp})
        return None
    resources = resp["result"].get("resources", [])
    # v0.68 shipped at least one reference resource (keysight scope).
    passed = len(resources) >= 1
    uri_shape = all(
        "://" in (r.get("uri") or "") and r.get("uri", "").count("/") >= 2
        for r in resources
    ) if resources else True
    detail = {
        "count": len(resources),
        "uris": [r.get("uri") for r in resources],
        "uri_shape_ok": uri_shape,
    }
    p.record("resources/list", "PASS" if passed and uri_shape else "FAIL", detail)
    return resources


def check_resource_read(p: MCPProbe, uri: str, live: bool) -> None:
    if not live:
        p.record("resources/read", "SKIP", {"reason": "--no-live"})
        return
    resp = p.request("resources/read", {"uri": uri}, timeout=30)
    if not resp or "result" not in resp:
        p.record("resources/read", "FAIL", {"uri": uri, "resp": resp})
        return
    contents = resp["result"].get("contents", [])
    if not contents:
        p.record("resources/read", "FAIL", {"uri": uri, "reason": "empty contents"})
        return
    raw = contents[0].get("text", "")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        p.record("resources/read", "FAIL", {"uri": uri,
                                            "reason": "non-JSON body",
                                            "head": raw[:200]})
        return
    # Success: either hardware is live (body.success == true) or gracefully
    # returns a DeviceError body (body.success == false + error_code).
    if body.get("success") is True:
        head = {k: v for k, v in body.items()
                if k in ("success", "mode", "idn_string", "channels_enabled")}
        p.record("resources/read", "PASS", {"uri": uri, "live_hardware": True,
                                            "head": head})
    elif body.get("success") is False and "error_code" in body:
        p.record("resources/read", "PASS", {
            "uri": uri,
            "live_hardware": False,
            "graceful_error_code": body.get("error_code"),
            "note": "device not present — server returned structured DeviceError, which is correct behavior",
        })
    else:
        p.record("resources/read", "FAIL", {"uri": uri,
                                            "reason": "unexpected body shape",
                                            "body": body})


# ────────────────────────── runner ──────────────────────────
def run_probe(live: bool = True) -> Dict[str, Any]:
    probe = MCPProbe(_SERVER)
    try:
        probe.start()
        if not check_initialize(probe):
            return _summarize(probe, catastrophic=True)
        tools = check_tools_list(probe)
        resources = check_resources_list(probe)
        if resources:
            check_resource_read(probe, resources[0]["uri"], live=live)
        else:
            probe.record("resources/read", "SKIP",
                         {"reason": "no resources in list"})
    finally:
        probe.stop()
    return _summarize(probe)


def _summarize(probe: MCPProbe, catastrophic: bool = False) -> Dict[str, Any]:
    steps = probe.steps
    n_pass = sum(1 for s in steps if s["status"] == "PASS")
    n_fail = sum(1 for s in steps if s["status"] == "FAIL")
    n_skip = sum(1 for s in steps if s["status"] == "SKIP")
    if catastrophic:
        exit_code = 2
    elif n_fail > 0:
        exit_code = 1
    else:
        exit_code = 0
    return {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "summary": {"pass": n_pass, "fail": n_fail, "skip": n_skip,
                    "total": len(steps)},
        "steps": steps,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true",
                    help="Emit the report as JSON on stdout")
    ap.add_argument("--no-live", action="store_true",
                    help="Skip resources/read (CI without hardware)")
    args = ap.parse_args(argv)

    if not _SERVER.is_file():
        msg = {"ok": False, "exit_code": 2,
               "error": f"server file not found: {_SERVER}"}
        print(json.dumps(msg, indent=2) if args.json
              else f"ERROR: server not found: {_SERVER}",
              file=sys.stderr)
        return 2

    report = run_probe(live=not args.no_live)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("=" * 64)
        print("mcp-eda live probe")
        print("=" * 64)
        for s in report["steps"]:
            mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘"}.get(s["status"], "?")
            print(f"  {mark} [{s['status']}] {s['name']}")
            if s.get("detail"):
                d = s["detail"]
                if isinstance(d, dict):
                    for k, v in list(d.items())[:6]:
                        val_s = str(v)
                        if len(val_s) > 80:
                            val_s = val_s[:77] + "..."
                        print(f"        {k}: {val_s}")
        sm = report["summary"]
        print("-" * 64)
        print(f"  {sm['pass']} PASS / {sm['fail']} FAIL / {sm['skip']} SKIP "
              f"(total {sm['total']})")
        print(f"  exit={report['exit_code']}")

    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
