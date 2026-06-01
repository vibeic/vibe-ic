#!/usr/bin/env python3
"""Re-run phase1 doc generation + L-doc parity for every benchmark IC.

For each <bench>/ under benchmark_phase1/:
  1. regenerate phase1/generated_docs via phase1_doc_one_shot_runner.py
     (--skip-text-extract: reuse existing input_doc text extraction)
  2. l_doc_parity_diff.py generated_docs vs claude_extracted (gold)
  3. compute GATED parity = sum(absent + hallucinated + value_mismatch)
     over docs where gold present (agent_bytes>0). SHAPE_MISMATCH excluded
     (R28/R32). L19-L23 skeleton-only docs (no gold) excluded automatically.

Emits _sweep_parity_result.json + prints a summary table.
Parallelised with a process pool.
"""
from __future__ import annotations
import json, os, subprocess, sys, concurrent.futures as cf
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROG = Path("/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs")
RUNNER = PROG / "phase1_doc_one_shot_runner.py"
PARITY = PROG / "l_doc_parity_diff.py"

def benches():
    for d in sorted(ROOT.iterdir()):
        if d.is_dir() and (d / "phase1" / "claude_extracted").is_dir() \
           and (d / "input" / "docs").is_dir():
            yield d

def src_for(bench: Path):
    idir = bench / "phase1" / "input_doc"
    if idir.is_dir():
        txts = sorted(idir.glob("*.txt"))
        if txts:
            return txts[0]
    return None

def run_one(bench: Path, regen: bool):
    name = bench.name
    res = {"name": name, "regen_rc": None, "gated": None,
           "absent": 0, "halluc": 0, "vmismatch": 0, "shape": 0,
           "per_doc": [], "error": None}
    try:
        if regen:
            r = subprocess.run(
                [sys.executable, str(RUNNER), str(bench), "--skip-text-extract"],
                cwd=str(bench), capture_output=True, text=True, timeout=600,
                env={**os.environ, "PYTHONPATH": str(PROG)})
            res["regen_rc"] = r.returncode
            if r.returncode != 0:
                res["error"] = "regen_fail: " + (r.stderr or r.stdout)[-400:]
        src = src_for(bench)
        cmd = [sys.executable, str(PARITY),
               "--program-dir", str(bench / "phase1" / "generated_docs"),
               "--agent-dir", str(bench / "phase1" / "claude_extracted"),
               "--out-json", f"/tmp/parity_{name}.json"]
        if src:
            cmd += ["--source", str(src)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                           env={**os.environ, "PYTHONPATH": str(PROG)})
        d = json.load(open(f"/tmp/parity_{name}.json"))
        g = a = h = v = sm = 0
        for s in d["stats"]:
            if s["agent_bytes"] > 0:
                sub = s["absent_in_program"] + s["hallucinated"] + s["value_mismatch"]
                g += sub
                a += s["absent_in_program"]; h += s["hallucinated"]; v += s["value_mismatch"]
                sm += s["shape_mismatch"]
                if sub:
                    res["per_doc"].append({
                        "doc": s["name"], "absent": s["absent_in_program"],
                        "halluc": s["hallucinated"], "vmismatch": s["value_mismatch"]})
        res.update(gated=g, absent=a, halluc=h, vmismatch=v, shape=sm)
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"
    return res

def main():
    regen = "--no-regen" not in sys.argv
    bl = list(benches())
    print(f"sweeping {len(bl)} benchmarks (regen={regen}) ...", flush=True)
    results = []
    with cf.ProcessPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(run_one, b, regen): b.name for b in bl}
        for f in cf.as_completed(futs):
            r = f.result(); results.append(r)
            tag = "ERR" if r["error"] else ("OK" if r["gated"] == 0 else "GAP")
            print(f"  [{tag}] {r['name']:<22} gated={r['gated']} "
                  f"(a={r['absent']} h={r['halluc']} v={r['vmismatch']})"
                  + (f"  !! {r['error'][:80]}" if r["error"] else ""), flush=True)
    results.sort(key=lambda x: (-(x["gated"] or 0), x["name"]))
    out = ROOT / "_sweep_parity_result.json"
    out.write_text(json.dumps(results, indent=2))
    total_gap = sum(1 for r in results if (r["gated"] or 0) > 0)
    total_err = sum(1 for r in results if r["error"])
    total_halluc = sum(r["halluc"] for r in results)
    print(f"\n=== SUMMARY ===")
    print(f"benchmarks: {len(results)}  clean(gated=0): {len(results)-total_gap-total_err}"
          f"  with-gap: {total_gap}  errors: {total_err}  total-hallucinations: {total_halluc}")
    print("\nNON-ZERO / ERROR:")
    for r in results:
        if (r["gated"] or 0) > 0 or r["error"]:
            print(f"  {r['name']:<22} gated={r['gated']} a={r['absent']} h={r['halluc']} v={r['vmismatch']}"
                  + (f"  ERR={r['error'][:60]}" if r["error"] else ""))
    print(f"\nwrote {out}")

if __name__ == "__main__":
    main()
