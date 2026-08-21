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
_PACK = _load(_PROGRAMS / "ic_expert_backup_pack.py", "ic_expert_backup_pack")

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


def _stage_context_rtl(record: Dict[str, Any], dest: Path) -> List[Path]:
    """Write the record's input.context `rtl/*.sv|v` files to `dest` (input-only,
    never output/harness). Returns the written paths."""
    inp = record.get("input") or {}
    ctx = inp.get("context") if isinstance(inp, dict) else None
    written: List[Path] = []
    if not isinstance(ctx, dict):
        return written
    for path, src in sorted(ctx.items()):
        if not isinstance(path, str) or not isinstance(src, str):
            continue
        if re.search(r"\.(s?v)$", path):
            p = dest / Path(path).name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src)
            written.append(p)
    return written


def _iface_to_contract_v(iface: List[Dict[str, Any]], target: str) -> str:
    """Header-only interface CONTRACT — delegates to the general core."""
    return _PACK.iface_to_contract_v(iface, target)


def _run_json(cmd: List[str], json_path: Path) -> Optional[dict]:
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    if json_path.is_file():
        try:
            return json.loads(json_path.read_text())
        except Exception:
            return None
    return None


def _lint_baseline(files: List[Path], work: Path) -> Dict[str, Any]:
    """Part C — deterministic optimization-loop first step: rtl_hygiene_lint over
    the context RTL to establish the current hygiene/lint baseline (the metric an
    optimization task must improve). Returns {findings, clean}."""
    if not files:
        return {"ran": False}
    work.mkdir(parents=True, exist_ok=True)
    jp = work / "lint.json"
    cmd = [sys.executable, str(_PROGRAMS / "rtl_hygiene_lint.py"),
           "--json", str(jp), "--severity", "WARN", *[str(f) for f in files]]
    data = _run_json(cmd, jp)
    if data is None:
        return {"ran": False}
    findings = data.get("findings") if isinstance(data, dict) else None
    n = len(findings) if isinstance(findings, list) else 0
    return {"ran": True, "findings": n, "clean": n == 0}


def _conformance(rtl_dir: Path, iface: List[Dict[str, Any]], target: str,
                 work: Path) -> Dict[str, Any]:
    """Part D — gate an emitted body against the recovered interface CONTRACT."""
    if not iface or not target:
        return {"ran": False}
    work.mkdir(parents=True, exist_ok=True)
    spec = work / "contract.v"
    spec.write_text(_iface_to_contract_v(iface, target))
    jp = work / "conformance.json"
    cmd = [sys.executable, str(_PROGRAMS / "spec_conformance_check.py"),
           "--rtl-dir", str(rtl_dir), "--spec", str(spec),
           "--top", target, "--json", str(jp)]
    data = _run_json(cmd, jp)
    if data is None:
        return {"ran": False}
    verdict = data.get("verdict") if isinstance(data, dict) else None
    findings = data.get("findings") if isinstance(data, dict) else None
    n = len(findings) if isinstance(findings, list) else 0
    return {"ran": True, "verdict": verdict, "findings": n,
            "conforms": (verdict == "PASS") or (n == 0 and verdict is None)}


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
    det_first = (route.get("plugin_entry") or {}).get("deterministic_first", [])
    iface: List[Dict[str, Any]] = []
    tgt: Optional[str] = None

    # STEP 1 — deterministic interface recovery (completion/modify/debug).
    if "cvdp_context_interface_recover.py" in det_first:
        tgt = _context_target(record)
        try:
            iface = _IR.recover_interface(record, target=tgt) if tgt \
                else _IR.recover_interface(record)
        except Exception:
            iface = []
        res["iface_source"] = "context" if iface else None
        # FALLBACK — a cid002 completion usually ships the partial RTL (the real
        # `module (...)` header = the interface) INSIDE the prompt, not in
        # input.context. Recover it from the prompt's own real declaration
        # (header-only, §4.05 — the interface the author is given, not the body).
        if not iface:
            prompt = (record.get("input") or {}).get("prompt") or ""
            # try EVERY `module <name> (` header declared in the prompt; keep the
            # recovery with the most ports (the target is the richest header, a
            # helper stub has few/none). Header-only, §4.05 — the interface the
            # author is given, never the golden body.
            best_top = None
            for m in _MODULE_RE.finditer(prompt):
                nm = m.group(1)
                try:
                    cand = _IR.recover_interface_from_text(prompt, nm)
                except Exception:
                    cand = []
                if len(cand) > len(iface):
                    iface, best_top = cand, nm
            if iface:
                res["iface_source"] = "in_prompt_header"
                tgt = tgt or best_top
        res["iface_ports"] = len(iface or [])
        res["target_module"] = tgt

    # STEP 2 — deterministic body solve (completion/modify only).
    if "modify_complete_synth.py" in det_first:
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

    # STEP 3 (Part D) — gate the emitted body against the recovered interface
    # CONTRACT (spec_conformance_check). Wired to fire for the AI-backup body too;
    # here it runs whenever there IS an emitted RTL to check (the det-solved cases
    # give real evidence the gate fires; the AI cases will re-fire it on emit).
    if ("spec_conformance_check.py" in (route.get("plugin_entry") or {})
            .get("verify", []) and iface and tgt
            and (cidir / "rtl.sv").is_file()):
        res["conformance"] = _conformance(cidir, iface, tgt, cidir / "conf")

    # STEP-OPT (Part C) — optimization has no interface/solve step; its
    # deterministic-first lever is a hygiene/lint BASELINE over the context RTL
    # (the metric an optimization task must not regress). rtl_hygiene_lint.
    if "rtl_hygiene_lint.py" in det_first:
        staged = _stage_context_rtl(record, cidir / "ctx")
        res["lint_baseline"] = _lint_baseline(staged, cidir / "lint")

    # STEP 4 (AI-BACKUP) — the deterministic track did not author the body, so let
    # the AI act AS the IC Expert Agent, USING its two expert assets: the
    # expert-SKILLS digest (lessons.md) and the class-matched expert-DB
    # (ic_expert_db.md), plus the recovered interface CONTRACT. Assemble the
    # dual-track hand-off pack (deterministic); the LLM authoring is the
    # vibe-ic:ic-expert-agent subagent invocation the hand-off names. Input-only.
    if res["emit_path"] == "needs_ai_backup":
        pe = route.get("plugin_entry") or {}
        prompt = (record.get("input") or {}).get("prompt") or ""
        # input.context file keys — for the context-sibling collision advisory
        # (never inline a verbatim copy of a separately-compiled context module).
        ctx_keys = list(((record.get("input") or {}).get("context") or {}).keys())
        try:
            handoff = _PACK.assemble(
                prompt, iface, tgt,
                pe.get("ai_backup", []), pe.get("verify", []),
                cidir / "ai_backup", context_keys=ctx_keys)
        except Exception:
            handoff = None
        if handoff:
            res["ai_backup"] = {
                "subagent_type": handoff["subagent_type"],
                "expert_skills": handoff["expert_skills"],
                "db_classes": [c["ic_class"] for c in handoff["db_classes"]],
                "n_skills": handoff["dual_track"]["track1_general_blind"]["n_skills"],
                "n_db_lessons": handoff["dual_track"]["track2_db_informed"]["n_db_lessons"],
                "handoff": "ai_backup/ic_expert_agent_handoff.json",
            }

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
        b = by_nat.setdefault(
            r["nature"],
            {"n": 0, "det": 0, "iface": 0, "conf": 0, "lint": 0, "aibk": 0})
        b["n"] += 1
        b["det"] += 1 if r["iverilog_ok"] else 0
        b["iface"] += 1 if r["iface_ports"] > 0 else 0
        if (r.get("conformance") or {}).get("conforms"):
            b["conf"] += 1
        if (r.get("lint_baseline") or {}).get("ran"):
            b["lint"] += 1
        if r.get("ai_backup"):
            b["aibk"] += 1
    report = {"dataset": str(ds), "n": len(results),
              "by_nature": by_nat, "cases": results}
    out = Path(a.report) if a.report else (run_dir / "task_loop_report.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                   encoding="utf-8")

    print(f"cvdp_task_loop: {len(results)} plugin_loop record(s)")
    print(f"  {'nature':26} {'n':>4} {'iface✓':>7} {'det-RTL✓':>9}"
          f" {'conform✓':>9} {'lint-base':>9} {'ai-backup':>9}")
    for nat in sorted(by_nat):
        b = by_nat[nat]
        print(f"  {nat:26} {b['n']:>4} {b['iface']:>7} {b['det']:>9}"
              f" {b['conf']:>9} {b['lint']:>9} {b['aibk']:>9}")
    print(f"  report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
