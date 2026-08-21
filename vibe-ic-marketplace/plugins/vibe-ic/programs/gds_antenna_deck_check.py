#!/usr/bin/env python3
"""gds_antenna_deck_check.py — independent GDS-geometry process-antenna sign-off.

WHAT GAP THIS CLOSES
--------------------
Step 26 (antenna) previously had exactly ONE opinion: `antenna_report_check.py`,
which parses the count OpenROAD's own `check_antennas` wrote. That is a
ROUTER-REPORT consumer — it can only repeat what the router already believed. If
the router's antenna model misses a violation, the report is clean and the gate
passes, with no second opinion anywhere in the flow.

This gate adds the missing INDEPENDENT, authoritative opinion: it runs the
KLayout fork's GDS-geometry antenna deck (`gds_antenna/antenna_check.py`) on the
STREAMED GDS and computes, per metal layer, the per-net antenna ratio
    ratio = (connected metal area) / (connected gate area)
from the as-fabricated geometry, using STAGED connectivity (at the layer-k etch
stage only layers 1..k exist, so an upper-metal jumper cannot relieve a
lower-stage antenna — a relief the router's final-netlist view credits) plus
cumulative-antenna-area (CAA) charge sharing, which no per-layer check can see.

It does NOT replace `antenna_report_check` — both run at Step 26. Where a router
report exists, the two independent counts are CROSS-CHECKED
(`gds_antenna/xcheck_router.py`): a clean/dirty DISAGREEMENT is a hard FAIL, so a
router-vs-geometry inconsistency is SURFACED rather than averaged away.

HONEST DEGRADATION (§4.05)
--------------------------
A step that passes because the checker never ran is a false PASS. Every
non-execution here is a NAMED, DISCLOSED skip written into the report JSON and
printed with the plugin's `VACUOUS_PASS:` sentinel at rc 2, which
`flow_compliance_check` renders as VACUOUS-PASS — never a bare PASS. Note the
exit-code remap versus the fork's reference wrapper: the fork used rc 3 for
honest-skip, but rc 3 is this plugin's PASS_WITH_WAIVERS code and a rc 3 without
the waiver sentinel reads as FAIL, so the disclosed skip is rc 2 here.

A deck config that IS present but matches no gate geometry is a FAIL, not a skip:
the PDK declared an antenna deck and it did not work, which is exactly the
"checker didn't run" case that must never read as clean. `--strict` additionally
turns every disclosed skip into a FAIL (tapeout use).

chip/PDK-AGNOSTIC: the layer stack and the per-metal ratio bounds come entirely
from the caller's deck config; no vendor, foundry or design literal appears here.

    gds_antenna_deck_check <project_dir> [--gds G] [--config C] [--router R]
                           [--cell TOP] [--json OUT] [--strict]
    main(argv) -> int : 0 PASS / 1 FAIL / 2 DISCLOSED SKIP
"""
from __future__ import annotations

import argparse
import importlib.util
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

# Where a streamed GDS lands, most-final first. Globs only — no design literal.
_GDS_GLOBS = (
    "phase3/stage4/gds/*.gds",
    "phase3/stage3/pnr/*.gds",
    "**/*.gds",
)
# Where the per-PDK antenna deck config may be declared.
_BRIDGE_CFG = "input/pdk/bridge/signoff_config.json"
_BRIDGE_KEY = "antenna_deck"
# The CONFIG filename is subject to the same collision as the report filenames
# (see the naming note in run()): `antenna_report_check` rglobs `*antenna*.json`
# across the WHOLE project and would ingest this deck config as if it were a
# router antenna report — it carries no violation count, so a project that
# adopted the deck would see spurious ANTENNA_VIOLATION_COUNT errors and, with
# no genuine antenna.rpt present, a hard FAIL of the sibling gate. Hence
# "gate_oxide", not "antenna".
_CFG_GLOBS = (
    "signoff/gate_oxide_deck.json",
    "input/pdk/bridge/gate_oxide_deck.json",
)
_ROUTER_GLOBS = (
    "reports/phase3/antenna.rpt",
    "**/antenna*.rpt",
)
# See the naming note in run(): these must NOT match `*antenna*.json`.
_RAW_REPORT_NAME = "gate_oxide_geom_deck_raw.json"
_MATERIALISED_CFG_NAME = "gate_oxide_geom_deck_config.json"


def _first(project: Path, globs) -> Optional[Path]:
    for g in globs:
        hits = sorted(p for p in project.glob(g) if p.is_file())
        if hits:
            return hits[0]
    return None


def _resolve_config(project: Path, explicit: Optional[str]) -> tuple:
    """Return (config_path, deck_dict, source) — deck_dict None when absent.

    A bridge `signoff_config.json` may declare `antenna_deck` either INLINE (a
    dict) or as a path relative to the PDK dir.
    """
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
                                f"missing deck: {declared}")
    found = _first(project, _CFG_GLOBS)
    if found:
        return found, json.loads(found.read_text()), \
            str(found.relative_to(project))
    return None, None, "no antenna deck config declared for this PDK"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                             # type: ignore
    return mod


def run(project: Path, gds: Optional[str], config: Optional[str],
        router: Optional[str], cell: Optional[str]) -> Dict[str, Any]:
    """Return a verdict dict. Verdicts: PASS / FAIL / DISCLOSED_SKIP."""
    def skip(reason: str, **extra) -> Dict[str, Any]:
        return {"verdict": "DISCLOSED_SKIP", "reason": reason,
                "check": "gds_geometry_antenna_deck", **extra}

    engine = _kl.find_engine("gds_antenna", "antenna_check.py")
    if engine is None:
        return skip("GDS-geometry antenna engine not found "
                    "(gds_antenna/antenna_check.py missing; set "
                    "$VIBEIC_KLAYOUT_TOOLS to a KLayout-fork checkout)")

    cfg_path, deck, cfg_src = _resolve_config(project, config)
    if deck is None:
        return skip(cfg_src, config_source=cfg_src)

    gds_path = (Path(gds) if gds else _first(project, _GDS_GLOBS))
    if gds_path is not None and not gds_path.is_absolute():
        gds_path = project / gds_path
    if gds_path is None or not gds_path.is_file():
        return skip("no streamed GDS to check "
                    f"(looked for {', '.join(_GDS_GLOBS)})",
                    config_source=cfg_src)

    runner = _kl.find_runner()
    if runner is None:
        return skip("no KLayout runner available (no strmrun/klayout on PATH "
                    "and no KLayout in $VIBEIC_EDA_CONTAINER) — the antenna "
                    "geometry deck did NOT run",
                    config_source=cfg_src, gds=str(gds_path))

    work = project / "reports" / "phase3"
    work.mkdir(parents=True, exist_ok=True)
    # NAMING IS LOAD-BEARING: `antenna_report_check` (eda_report_audit --mode
    # antenna) rglobs `*antenna*.json` / `*antenna*.rpt` and treats every hit as
    # a ROUTER antenna report — it would swallow this gate's geometry JSON, find
    # no OpenROAD violation count in it and fail its own authenticity check. So
    # nothing this gate writes may contain the substring "antenna".
    out_json = work / _RAW_REPORT_NAME
    # An inline deck (or a config outside the runner's reach) is materialised
    # beside the output so the runner can always see it.
    if cfg_path is None or not runner.covers(cfg_path):
        cfg_path = work / _MATERIALISED_CFG_NAME
        cfg_path.write_text(json.dumps(deck, indent=2))
    for label, p in (("GDS", gds_path), ("engine", engine),
                     ("report dir", work)):
        if not runner.covers(p):
            return skip(f"{label} path is not reachable by the KLayout runner "
                        f"({runner.kind}: {runner.detail}): {p}",
                        config_source=cfg_src)

    env = {"ANT_GDS": str(gds_path), "ANT_CONFIG": str(cfg_path),
           "ANT_OUT": str(out_json)}
    if cell:
        env["ANT_CELL"] = cell
    if out_json.is_file():
        out_json.unlink()
    rc, out, err = runner.run(engine, env,
                              path_keys=("ANT_GDS", "ANT_CONFIG", "ANT_OUT"),
                              timeout=1800)
    if not out_json.is_file():
        return {"verdict": "FAIL", "check": "gds_geometry_antenna_deck",
                "reason": "antenna geometry deck produced no report",
                "config_source": cfg_src, "gds": str(gds_path),
                "runner": f"{runner.kind}:{runner.detail}", "rc": rc,
                "stderr": (err or "")[-600:], "stdout": (out or "")[-600:]}
    deck_res = json.loads(out_json.read_text())

    res: Dict[str, Any] = {
        "check": "gds_geometry_antenna_deck",
        "runner": f"{runner.kind}:{runner.detail}",
        "config_source": cfg_src, "gds": str(gds_path),
        "worst_ratio": deck_res.get("worst_ratio"),
        "violations": deck_res.get("violations"),
        "deck": deck_res,
    }
    dv = deck_res.get("verdict")
    if dv == "PASS":
        res["verdict"] = "PASS"
    elif dv == "FAIL":
        res["verdict"] = "FAIL"
        res["reason"] = (f"{deck_res.get('violations')} antenna violation(s) in "
                         f"the GDS geometry; worst ratio "
                         f"{deck_res.get('worst_ratio')}")
    else:
        # HONEST_SKIP / ERROR from the engine: the deck was DECLARED but did not
        # produce a usable measurement. Never a pass — see module docstring.
        res["verdict"] = "FAIL"
        res["reason"] = ("antenna deck ran but produced no usable measurement "
                         f"({dv}): {deck_res.get('note') or deck_res.get('error')}"
                         " — a declared deck that cannot measure is not clean")

    # Independent cross-check against the router's own count.
    xtool = _kl.find_engine("gds_antenna", "xcheck_router.py")
    rpt = Path(router) if router else _first(project, _ROUTER_GLOBS)
    if rpt is not None and not rpt.is_absolute():
        rpt = project / rpt
    if xtool is not None and rpt is not None and rpt.is_file():
        try:
            xr = _load_module(xtool, "_vibeic_xcheck_router")
            x = xr.cross_check(out_json, rpt)                # type: ignore
        except Exception as exc:                             # noqa: BLE001
            x = {"verdict": "ERROR", "detail": f"cross-check failed: {exc}"}
        x["router_report"] = str(rpt)
        res["cross_check"] = x
        if x.get("verdict") == "DISAGREE":
            res["verdict"] = "FAIL"
            res["reason"] = (
                "router-vs-geometry antenna DISAGREEMENT — one of the two is "
                f"wrong: {x.get('detail')}")
    else:
        res["cross_check"] = {
            "verdict": "NOT_RUN",
            "reason": ("no router antenna report to cross-check against"
                       if rpt is None or not rpt.is_file()
                       else "xcheck_router.py engine not found")}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Independent GDS-geometry process-antenna sign-off gate.")
    ap.add_argument("project_dir", nargs="?", default=".")
    ap.add_argument("--gds", default=None)
    ap.add_argument("--config", default=None,
                    help="antenna deck config (per-PDK layer stack + ratios)")
    ap.add_argument("--router", default=None,
                    help="router antenna report to cross-check against")
    ap.add_argument("--cell", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="treat a disclosed skip as a FAIL (tapeout sign-off)")
    ns = ap.parse_args(argv)

    project = Path(ns.project_dir).resolve()
    try:
        res = run(project, ns.gds, ns.config, ns.router, ns.cell)
    except Exception as exc:                                 # noqa: BLE001
        res = {"verdict": "FAIL", "check": "gds_geometry_antenna_deck",
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
        # Plugin disclosed-skip tier: rc 2 + sentinel -> VACUOUS-PASS, so the
        # flow report SHOWS the checker did not run instead of reading clean.
        print(f"VACUOUS_PASS: gds_antenna_deck_check did NOT run — "
              f"{res.get('reason')}")
        print(json.dumps(res, indent=2))
        return SKIP
    print(json.dumps(res, indent=2))
    if verdict == "PASS":
        print("gds_antenna_deck_check: PASS "
              f"(0 geometry antenna violations, worst ratio "
              f"{res.get('worst_ratio')})")
        return PASS
    print(f"gds_antenna_deck_check: FAIL — {res.get('reason')}")
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
