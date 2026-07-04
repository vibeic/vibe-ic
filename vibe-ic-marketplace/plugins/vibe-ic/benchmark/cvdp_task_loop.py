#!/usr/bin/env python3
r"""cvdp_task_loop.py — deterministic driver for the 224 NON-spec-gen CVDP records.

Companion to `cvdp_phase1_entry.py` (which drives the 78 spec_generation records
through Phase-1). This driver takes every `plugin_loop` record (completion /
functional-modification / optimization / debug — see `cvdp_task_router.py`) and
runs the DETERMINISTIC-FIRST steps of its plugin loop, reading ONLY the INPUT
side (`input.prompt` + `input.context`), NEVER `output`/`harness` (the oracle):

  completion / modify:
    1. cvdp_context_interface_recover  → recover the TARGET port interface from
       the input.context module header (header-only, §4.05 — the interface is
       the spec, never the golden body);
    2. modify_complete_synth.solve     → emit RTL for the standard deterministic
       algorithms it covers (SKIP → None otherwise);
    3. iverilog -g2012                 → prove the emitted RTL compiles.
  debug:
    1. cvdp_context_interface_recover  → recover interface;
    2. (deterministic bug-pattern first-pass is a stub today) → flag AI-backup.
  optimization:
    1. rtl_hygiene_lint over the context RTL is the deterministic lever;
       the area/PPA optimization body is AI-led.

Each record is classified: `deterministic_solved` (RTL emitted AND iverilog rc=0)
vs `needs_ai_backup` (the loop's AI skill — spec-to-rtl / rtl-repair / ... — must
author the body, then the verify gates re-fire). The AI-backup body is the ONLY
non-deterministic insert; this driver establishes the deterministic half + the
exact AI-backup work-list, and emits the deterministically-solved RTL for the
official cvdp_gate → run_benchmark.py scoring path.

CLI:
    python3 cvdp_task_loop.py --dataset <cvdp.jsonl> --run <dir>
                              [--limit N] [--ids a,b] [--natures completion,debug]
Exit 0 always; exit 2 on dataset/IO error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve()
_PLUGIN = _HERE.parents[1]
_PROGRAMS = _PLUGIN / "programs"
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_PROGRAMS))

from cvdp_task_router import route_record  # noqa: E402


def _load(mod_path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, mod_path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


_IR = _load(_PROGRAMS / "cvdp_context_interface_recover.py",
            "cvdp_context_interface_recover")
_MS = _load(_PROGRAMS / "modify_complete_synth.py", "modify_complete_synth")

_MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")


def _context_target(record: Dict[str, Any]) -> Optional[str]:
    """The target module name = the module declared under an `rtl/*.sv|v` context
    file (the file the scorer's TOPLEVEL derives from). Deterministic, input-only."""
    inp = record.get("input") or {}
    ctx = inp.get("context") if isinstance(inp, dict) else None
    if not isinstance(ctx, dict):
        return None
    for path, src in sorted(ctx.items()):
        if not isinstance(path, str) or not isinstance(src, str):
            continue
        if re.search(r"(^|/)rtl/.*\.(s?v)$", path):
            m = _MODULE_RE.search(src)
            if m:
                return m.group(1)
    return None


def _iverilog_ok(rtl: str, work: Path) -> bool:
    if not shutil.which("iverilog"):
        return False
    work.mkdir(parents=True, exist_ok=True)
    f = work / "emit.sv"
    f.write_text(rtl)
    r = subprocess.run(["iverilog", "-g2012", "-o", str(work / "a.out"), str(f)],
                       capture_output=True, text=True)
    return r.returncode == 0


def run_loop_case(record: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    route = route_record(record)
    cid = route.get("cid")
    nature = route.get("nature")
    entry = (route.get("plugin_entry") or {}).get("name")
    cidir = run_dir / "cases" / str(record.get("id"))
    res: Dict[str, Any] = {"id": record.get("id"), "cid": cid,
                           "nature": nature, "plugin_entry": entry,
                           "iface_ports": 0, "det_rtl": False,
                           "iverilog_ok": False, "emit_path": "needs_ai_backup"}

    # STEP 1 — deterministic interface recovery (completion/modify/debug).
    if "cvdp_context_interface_recover.py" in \
            (route.get("plugin_entry") or {}).get("deterministic_first", []):
        tgt = _context_target(record)
        try:
            iface = _IR.recover_interface(record, target=tgt) if tgt \
                else _IR.recover_interface(record)
        except Exception:
            iface = []
        res["iface_ports"] = len(iface or [])
        res["target_module"] = tgt

    # STEP 2 — deterministic body solve (completion/modify only).
    if "modify_complete_synth.py" in \
            (route.get("plugin_entry") or {}).get("deterministic_first", []):
        try:
            rtl = _MS.solve(record)
        except Exception:
            rtl = None
        if rtl:
            cidir.mkdir(parents=True, exist_ok=True)
            (cidir / "rtl.sv").write_text(rtl)
            res["det_rtl"] = True
            res["iverilog_ok"] = _iverilog_ok(rtl, cidir / "iv")
            res["emit_path"] = ("deterministic"
                                if res["iverilog_ok"] else "deterministic_uncompiled")
    return res


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    ap.add_argument("--natures", default="",
                    help="comma-list filter: completion,functional_modification,"
                         "optimization,debug")
    ap.add_argument("--report", default="")
    a = ap.parse_args(argv)

    ds = Path(a.dataset)
    if not ds.is_file():
        print(f"cvdp_task_loop: dataset not found: {ds}", file=sys.stderr)
        return 2
    run_dir = Path(a.run)
    run_dir.mkdir(parents=True, exist_ok=True)
    if run_dir.exists():
        for c in (run_dir / "cases").glob("*"):
            if c.is_dir():
                shutil.rmtree(c, ignore_errors=True)

    id_allow = {s.strip() for s in a.ids.split(",") if s.strip()}
    nat_allow = {s.strip() for s in a.natures.split(",") if s.strip()}

    results: List[Dict[str, Any]] = []
    with ds.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            route = route_record(rec)
            if route.get("route") != "plugin_loop":
                continue  # spec_generation → cvdp_phase1_entry, not here
            if id_allow and rec.get("id") not in id_allow:
                continue
            if nat_allow and route.get("nature") not in nat_allow:
                continue
            results.append(run_loop_case(rec, run_dir))
            if a.limit and len(results) >= a.limit:
                break

    # Summary by nature.
    by_nat: Dict[str, Dict[str, int]] = {}
    for r in results:
        b = by_nat.setdefault(r["nature"], {"n": 0, "det": 0, "iface": 0})
        b["n"] += 1
        b["det"] += 1 if r["iverilog_ok"] else 0
        b["iface"] += 1 if r["iface_ports"] > 0 else 0
    report = {"dataset": str(ds), "n": len(results),
              "by_nature": by_nat, "cases": results}
    out = Path(a.report) if a.report else (run_dir / "task_loop_report.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                   encoding="utf-8")

    print(f"cvdp_task_loop: {len(results)} plugin_loop record(s)")
    print(f"  {'nature':26} {'n':>4} {'iface✓':>7} {'det-RTL+iverilog✓':>18}")
    for nat in sorted(by_nat):
        b = by_nat[nat]
        print(f"  {nat:26} {b['n']:>4} {b['iface']:>7} {b['det']:>18}")
    print(f"  report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
