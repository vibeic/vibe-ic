#!/usr/bin/env python3
"""analog_mc_yield_run.py — REAL Monte-Carlo yield execution for the
analog track (flow-completeness review P1-1).

The A4 gate (`analog_corner_sweep_check`) has enforced
`mc_yield_pct >= 95%` since v1.6.x — but NOTHING ever computed that
value: the MC selector existed, the gate existed, and the execution
layer was absent (the gate was decorative). This program runs the
statistical Monte-Carlo sweep for a block and writes the measured
yield into `corner_results.json` so the existing gate fires on REAL
data.

Method (chip-AGNOSTIC, PDK-namespaced):
  * the block's deck is wrapped N times with the PDK's STATISTICAL
    model section (`mc` for sky130, `statistical` for gf180 — the
    foundry's own mismatch/process distributions) and a distinct
    `.option seed=<i>` per iteration;
  * each iteration's `.meas` results are parsed (the deck's own
    measures — nothing injected);
  * per-spec yield = pass-fraction vs the block's spec.json limits
    (min/max), overall mc_yield_pct = min over specs (worst spec);
  * `corner_results.json` gains: mc_yield_pct, mc_runs, mc_pass,
    mc_seed_range, per-spec yield table, `_mc_provenance:
    real_ngspice_mc` + the per-run log directory.

No fabrication: ngspice/container/PDK-section unavailable → exit 2
with the named gap (the gate then has no mc_yield_pct and treats MC
as not-run, exactly as before). A computed yield, even 0%, is written
honestly.

Usage:
    python3 analog_mc_yield_run.py <project> --block <name>
        [--n 100] [--container iic-eda] [--pdk sky130]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import analog_real_corner_sweep as _ars  # noqa: E402  (docker/ngspice helpers)

# PDK statistical-section names — the FOUNDRY's own Monte-Carlo model
# sections (process + mismatch distributions). PDK-family namespaced,
# never chip-specific.
_MC_SECTION = {"sky130": "mc", "gf180": "statistical"}

_NATIVE_MEAS_RE = re.compile(r"^([a-zA-Z_]\w*)\s*=\s*([\-0-9.eE+]+)",
                             re.MULTILINE)


def _load_specs(project: Path, block: str):
    """Spec limits {name: {min,max}} from the A1 spec.json (no limits →
    no scoreable spec)."""
    for cand in (project / "phase1" / "analog" / block / "spec.json",
                 project / "phase3" / "analog" / block / "spec.json"):
        if cand.is_file():
            try:
                d = json.loads(cand.read_text(errors="replace"))
            except (OSError, ValueError):
                continue
            specs = {}
            for s in (d.get("specs") or d.get("spec") or []):
                if not isinstance(s, dict) or not s.get("name"):
                    continue
                lim = {k: s[k] for k in ("min", "max")
                       if isinstance(s.get(k), (int, float))}
                if lim:
                    specs[s["name"]] = lim
            if specs:
                return specs, str(cand.relative_to(project))
    return {}, None


def _find_deck(project: Path, block: str):
    for base in (project / "phase2" / "analog" / block,
                 project / "phase3" / "analog" / block):
        if base.is_dir():
            sps = sorted(base.glob("*.sp"))
            if sps:
                return sps[0]
    return None


def run_block(project: Path, block: str, container: str, pdk: str,
              n: int) -> dict:
    deck = _find_deck(project, block)
    if deck is None:
        return {"verdict": "SKIP", "rc": 2,
                "reason": f"no .sp deck found for block {block!r}"}
    specs, spec_src = _load_specs(project, block)
    if not specs:
        return {"verdict": "SKIP", "rc": 2,
                "reason": (f"no numeric spec limits (min/max) for block "
                           f"{block!r} — nothing to score yield against")}
    mc_section = _MC_SECTION.get(pdk)
    if not mc_section:
        return {"verdict": "SKIP", "rc": 2,
                "reason": f"no statistical model section known for pdk {pdk!r}"}
    if not _ars._ngspice_available(container):
        return {"verdict": "SKIP", "rc": 2,
                "reason": f"ngspice not available in container {container!r}"}
    pdk_lib = _ars.PDK_LIB.get(pdk)
    if not pdk_lib:
        return {"verdict": "SKIP", "rc": 2,
                "reason": f"no ngspice model lib known for pdk {pdk!r}"}

    host_root = (Path(str(project).split("AI_IC_design")[0]) / "AI_IC_design"
                 if "AI_IC_design" in str(project) else project)
    mc_dir = deck.parent / "mc_runs"
    mc_dir.mkdir(parents=True, exist_ok=True)
    deck_body = deck.read_text(errors="replace")
    # strip any caller-side .lib of the model file — the MC wrapper owns it
    deck_body = re.sub(rf"^\s*\.lib\s+\S*{re.escape(Path(pdk_lib).name)}\s+\S+\s*$",
                       "* (.lib moved to MC wrapper)", deck_body,
                       flags=re.MULTILINE | re.IGNORECASE)

    per_run = []
    for i in range(1, n + 1):
        wrap = mc_dir / f"mc_{i:04d}.sp"
        wrap.write_text(
            f"* MC iteration {i}/{n} — {self_name()} (foundry statistical "
            f"section '{mc_section}')\n"
            f".option seed={i}\n"
            f".lib {pdk_lib} {mc_section}\n"
            + deck_body + ("\n.end\n" if ".end" not in deck_body.lower()
                           else "\n"))
        # #464 — _run_ngspice now also returns a per-run sim_status (failed
        # sub-analyses + nulled metrics + warnings). Capture it so a Monte
        # Carlo iteration whose AC measure ERRORed is recorded as partial
        # rather than scored with bogus zeros (the nulled metric is None and
        # the spec-yield loop below already skips runs missing the metric).
        # Tolerate the legacy 3-tuple return so any pre-existing caller/mock
        # that has not yet adopted the 4-tuple keeps working.
        _ret = _ars._run_ngspice(
            container, _ars._container_path(container, host_root, wrap))
        if len(_ret) == 4:
            ok, meas, raw, sim_status = _ret
        else:
            ok, meas, raw = _ret
            sim_status = {"partial": False, "warnings": []}
        (mc_dir / f"mc_{i:04d}.log").write_text(raw)
        per_run.append({"seed": i, "ok": ok,
                        "partial_measurement": sim_status["partial"],
                        "sim_warnings": sim_status["warnings"], **meas})

    # per-spec yield
    spec_yield = {}
    for name, lim in specs.items():
        # #464 — a nulled metric is present-as-None; it is NOT a scored value
        # (skip it rather than crash the min/max comparison or count it).
        scored = [r for r in per_run
                  if r.get("ok") and r.get(name) is not None]
        if not scored:
            spec_yield[name] = {"runs_scored": 0, "yield_pct": None}
            continue
        passed = sum(
            1 for r in scored
            if (lim.get("min") is None or r[name] >= lim["min"])
            and (lim.get("max") is None or r[name] <= lim["max"]))
        spec_yield[name] = {
            "runs_scored": len(scored), "passed": passed,
            "yield_pct": round(100.0 * passed / len(scored), 2)}
    scoreable = [v["yield_pct"] for v in spec_yield.values()
                 if v["yield_pct"] is not None]
    if not scoreable:
        return {"verdict": "SKIP", "rc": 2,
                "reason": ("MC ran but no run carried a scoreable measure "
                           "— check the deck's .meas names vs spec.json"),
                "mc_runs": n, "spec_yield": spec_yield}
    mc_yield = min(scoreable)  # worst spec governs

    # write into corner_results.json so the EXISTING A4 gate fires
    cr = project / "phase3" / "analog" / block / "corner_results.json"
    cr.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(cr.read_text(errors="replace")) if cr.is_file() else {}
    except (OSError, ValueError):
        data = {}
    data.update({
        "mc_yield_pct": mc_yield,
        "mc_runs": n,
        "mc_pass": sum(1 for r in per_run if r.get("ok")),
        "mc_seed_range": [1, n],
        "mc_spec_yield": spec_yield,
        "mc_spec_source": spec_src,
        "_mc_provenance": "real_ngspice_mc",
        "mc_log_dir": str(mc_dir.relative_to(project)),
        "mc_model_section": mc_section,
    })
    cr.write_text(json.dumps(data, indent=2) + "\n")

    return {"verdict": "PASS" if mc_yield >= 95.0 else "FAIL", "rc": 0,
            "mc_yield_pct": mc_yield, "mc_runs": n,
            "spec_yield": spec_yield,
            "corner_results": str(cr.relative_to(project))}


def self_name() -> str:
    return "analog_mc_yield_run"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--block", required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--container", default="iic-eda")
    ap.add_argument("--pdk", default="sky130",
                    choices=sorted(_ars.PDK_LIB.keys()))
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project.is_dir():
        print(f"ERROR: not a directory: {args.project}", file=sys.stderr)
        return 1
    rep = run_block(args.project.resolve(), args.block, args.container,
                    args.pdk, args.n)
    rc = rep.pop("rc")
    rep = {"program": self_name(), "version": "1.0.0", **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
