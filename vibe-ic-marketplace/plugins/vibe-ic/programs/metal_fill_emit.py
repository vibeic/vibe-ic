#!/usr/bin/env python3
"""metal_fill_emit.py — per-layer density metal fill on the streamed GDS.

WHAT GAP THIS CLOSES
--------------------
The flow could only MEASURE per-layer metal density (`metal_layer_density_check`,
`erc_density_check`, `dfm_screen_check`) and, when a PDK bridge declared one, lay
down a fixed dummy-fill PATTERN. Nothing computed how much fill a sparse layer
actually needs. A die under the foundry's CMP density floor was therefore flagged
and left sparse — the foundry rejects that tapeout.

This wires the KLayout fork's density-targeted fill engine
(`metal_fill/metal_fill.py`): for each configured layer it measures the worst
density window and inserts fill, iterating until the layer reaches its target or
the pass budget runs out. It is DRC-safe by construction (keep-out + per-layer
`space`/`width` from the config), so the sign-off DRC deck still verifies it —
nothing is waived.

Two modes:
  * EMIT (default) — run the fill and write the filled GDS. The runner calls this
    at streamout, AFTER the GDS is written and BEFORE the density checks and
    sign-off DRC consume it, so those see the FILLED layout.
  * `--verify-only` — read the report a previous emit wrote and re-report its
    verdict WITHOUT re-running the fill. The Step-34 flow gate uses this, so
    auditing a finished project never mutates its GDS.

HONEST DEGRADATION (§4.05)
--------------------------
A missing KLayout, a missing engine, or a PDK that declares no fill config is a
NAMED, DISCLOSED skip (rc 2 + the `VACUOUS_PASS:` sentinel -> VACUOUS-PASS in the
flow report), never a silent "filled". A run that cannot reach the target on some
layer is PARTIAL -> FAIL with the achieved worst-window density disclosed. Note
the exit-code remap versus the fork's reference wrapper: rc 3 is this plugin's
PASS_WITH_WAIVERS code, so the disclosed skip is rc 2 here.

chip/PDK-AGNOSTIC: layer numbers, density targets and spacing all come from the
caller's config; no vendor, foundry or design literal appears here.

    metal_fill_emit <project_dir> [--gds G] [--config C] [--out O | --in-place]
                    [--cell TOP] [--report R] [--json J] [--verify-only]
    main(argv) -> int : 0 PASS / 1 FAIL(partial|error) / 2 DISCLOSED SKIP
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from . import _klayout_launch as _kl                     # type: ignore
except ImportError:                                          # standalone gate
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _klayout_launch as _kl                            # type: ignore

PASS, FAIL, SKIP = 0, 1, 2

_GDS_GLOBS = (
    "phase3/stage4/gds/*.gds",
    "phase3/stage3/pnr/*.gds",
    "**/*.gds",
)
_BRIDGE_CFG = "input/pdk/bridge/signoff_config.json"
_BRIDGE_KEY = "metal_fill_density"
# Same collision class as the report name below: `metal_layer_density_check`
# rglobs `*metal*density*.json` project-wide and would ingest this fill CONFIG
# as if it were a per-layer density measurement report.
_CFG_GLOBS = (
    "signoff/cmp_fill_targets.json",
    "input/pdk/bridge/cmp_fill_targets.json",
)
# NAMING IS LOAD-BEARING: `metal_layer_density_check` rglobs
# `*metal*density*.json` and would consume this emitter's report as if it were
# the per-layer density MEASUREMENT report. Nothing written here may match that.
_REPORT_REL = "reports/phase3/cmp_fill_emit.json"
_MATERIALISED_CFG_NAME = "cmp_fill_emit_config.json"


def _first(project: Path, globs) -> Optional[Path]:
    for g in globs:
        hits = sorted(p for p in project.glob(g)
                      if p.is_file() and not p.name.endswith(".filled.gds"))
        if hits:
            return hits[0]
    return None


def _resolve_config(project: Path, explicit: Optional[str]) -> tuple:
    """Return (config_path, cfg_dict, source); cfg_dict None when undeclared."""
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = project / p
        if not p.is_file():
            return None, None, f"config not found: {explicit}"
        return p, json.loads(p.read_text()), f"--config {explicit}"
    bridge = project / _BRIDGE_CFG
    if bridge.is_file():
        try:
            declared = json.loads(bridge.read_text()).get(_BRIDGE_KEY)
        except (ValueError, OSError):
            declared = None
        if isinstance(declared, dict):
            return None, declared, f"{_BRIDGE_CFG}:{_BRIDGE_KEY} (inline)"
        if isinstance(declared, str):
            p = (bridge.parent / declared).resolve()
            if p.is_file():
                return p, json.loads(p.read_text()), \
                    f"{_BRIDGE_CFG}:{_BRIDGE_KEY} -> {declared}"
            return None, None, (f"{_BRIDGE_CFG}:{_BRIDGE_KEY} points at a "
                                f"missing fill config: {declared}")
    found = _first(project, _CFG_GLOBS)
    if found:
        return found, json.loads(found.read_text()), \
            str(found.relative_to(project))
    return None, None, "no per-layer density fill config declared for this PDK"


def _skip(reason: str, **extra) -> Dict[str, Any]:
    return {"verdict": "DISCLOSED_SKIP", "reason": reason,
            "check": "per_layer_density_metal_fill", **extra}


def verify_only(project: Path, report: Optional[str]) -> Dict[str, Any]:
    """Re-report a previous emit's verdict without re-running the fill."""
    rep = Path(report) if report else (project / _REPORT_REL)
    if not rep.is_absolute():
        rep = project / rep
    if not rep.is_file():
        return _skip("no density-fill report — metal_fill_emit has not run on "
                     f"this project (looked for {rep})")
    try:
        res = json.loads(rep.read_text())
    except (ValueError, OSError) as exc:
        return {"verdict": "FAIL", "check": "per_layer_density_metal_fill",
                "reason": f"density-fill report unreadable: {exc}"}
    res.setdefault("check", "per_layer_density_metal_fill")
    res["mode"] = "verify-only"
    res["report"] = str(rep)
    return res


def run(project: Path, gds: Optional[str], config: Optional[str],
        out: Optional[str], in_place: bool, cell: Optional[str],
        report: Optional[str]) -> Dict[str, Any]:
    engine = _kl.find_engine("metal_fill", "metal_fill.py")
    if engine is None:
        return _skip("density fill engine not found (metal_fill/metal_fill.py "
                     "missing; set $VIBEIC_KLAYOUT_TOOLS to a KLayout-fork "
                     "checkout)")

    cfg_path, cfg, cfg_src = _resolve_config(project, config)
    if cfg is None:
        return _skip(cfg_src, config_source=cfg_src)

    gds_path = Path(gds) if gds else _first(project, _GDS_GLOBS)
    if gds_path is not None and not gds_path.is_absolute():
        gds_path = project / gds_path
    if gds_path is None or not gds_path.is_file():
        return _skip("no streamed GDS to fill "
                     f"(looked for {', '.join(_GDS_GLOBS)})",
                     config_source=cfg_src)

    runner = _kl.find_runner()
    if runner is None:
        return _skip("no KLayout runner available (no strmrun/klayout on PATH "
                     "and no KLayout in $VIBEIC_EDA_CONTAINER) — no fill was "
                     "inserted", config_source=cfg_src, gds=str(gds_path))

    rep = Path(report) if report else (project / _REPORT_REL)
    if not rep.is_absolute():
        rep = project / rep
    rep.parent.mkdir(parents=True, exist_ok=True)

    if in_place:
        # Fill into a sibling, then swap, so a failed run never truncates the
        # only copy of the streamed GDS.
        dest = gds_path
        staged = gds_path.with_suffix(".filled.gds")
    else:
        dest = (Path(out) if out else gds_path.with_suffix(".filled.gds"))
        if not dest.is_absolute():
            dest = project / dest
        staged = dest

    if cfg_path is None or not runner.covers(cfg_path):
        cfg_path = rep.parent / _MATERIALISED_CFG_NAME
        cfg_path.write_text(json.dumps(cfg, indent=2))
    for label, p in (("GDS", gds_path), ("engine", engine),
                     ("output", staged.parent), ("report dir", rep.parent)):
        if not runner.covers(p):
            return _skip(f"{label} path is not reachable by the KLayout runner "
                         f"({runner.kind}: {runner.detail}): {p}",
                         config_source=cfg_src)

    env = {"FILL_GDS": str(gds_path), "FILL_CONFIG": str(cfg_path),
           "FILL_OUT": str(staged), "FILL_REPORT": str(rep)}
    if cell:
        env["FILL_CELL"] = cell
    if rep.is_file():
        rep.unlink()
    rc, sout, serr = runner.run(
        engine, env,
        path_keys=("FILL_GDS", "FILL_CONFIG", "FILL_OUT", "FILL_REPORT"),
        timeout=3600)
    if not rep.is_file():
        return {"verdict": "FAIL", "check": "per_layer_density_metal_fill",
                "reason": "density fill produced no report",
                "config_source": cfg_src, "gds": str(gds_path),
                "runner": f"{runner.kind}:{runner.detail}", "rc": rc,
                "stderr": (serr or "")[-600:], "stdout": (sout or "")[-600:]}

    res = json.loads(rep.read_text())
    res["check"] = "per_layer_density_metal_fill"
    res["config_source"] = cfg_src
    res["runner"] = f"{runner.kind}:{runner.detail}"
    res["gds_in"] = str(gds_path)
    if res.get("verdict") == "PASS" and staged.is_file():
        if in_place:
            staged.replace(dest)
        res["gds_out"] = str(dest)
    elif staged.is_file() and staged != dest:
        res["gds_out_partial"] = str(staged)
    # Re-persist so `--verify-only` sees the same annotated verdict.
    rep.write_text(json.dumps(res, indent=2))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Per-layer density metal fill on the streamed GDS.")
    ap.add_argument("project_dir", nargs="?", default=".")
    ap.add_argument("--gds", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--in-place", action="store_true",
                    help="replace the streamed GDS with the filled layout")
    ap.add_argument("--cell", default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--verify-only", action="store_true",
                    help="re-report a previous emit's verdict; never re-fill")
    ap.add_argument("--strict", action="store_true",
                    help="treat a disclosed skip as a FAIL (tapeout sign-off)")
    ns = ap.parse_args(argv)

    project = Path(ns.project_dir).resolve()
    try:
        if ns.verify_only:
            res = verify_only(project, ns.report)
        else:
            res = run(project, ns.gds, ns.config, ns.out, ns.in_place,
                      ns.cell, ns.report)
    except Exception as exc:                                 # noqa: BLE001
        res = {"verdict": "FAIL", "check": "per_layer_density_metal_fill",
               "reason": f"gate error: {exc}"}

    if ns.json_out:
        out = Path(ns.json_out)
        if not out.is_absolute():
            out = project / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=2))

    verdict = res.get("verdict")
    if verdict == "DISCLOSED_SKIP" and ns.strict:
        verdict = "FAIL"
        res["reason"] = f"--strict: {res.get('reason')}"
    if verdict == "DISCLOSED_SKIP":
        print(f"VACUOUS_PASS: metal_fill_emit did NOT run — {res.get('reason')}")
        print(json.dumps(res, indent=2))
        return SKIP
    print(json.dumps(res, indent=2))
    if verdict == "PASS":
        return PASS
    if verdict == "PARTIAL":
        print("metal_fill_emit: FAIL — density target NOT reached on every "
              "layer (achieved densities disclosed above); the foundry CMP "
              "floor is not met")
        return FAIL
    print(f"metal_fill_emit: FAIL — {res.get('reason') or res.get('error')}")
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
