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
layer is PARTIAL, with the achieved worst-window density disclosed. PARTIAL ->
FAIL (and the filled GDS is NOT promoted) when any layer is below the FOUNDRY
floor the config was derived from; PARTIAL -> PASS with an explicit
`PARTIAL-ABOVE-FLOOR` disclosure when the miss is only against this plugin's own
floor+margin target and every layer still clears the foundry rule, because
shipping the UNFILLED GDS to sign-off in that case manufactures density
violations a DRC-clean filled layout would not have. Note
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


def _foundry_floor(cfg: Dict[str, Any]) -> Optional[float]:
    """The FOUNDRY density rule threshold (fraction) the config was derived
    from, or None when the config does not declare one.

    `metal_fill_config_gen` parses the sign-off deck's own coverage rule
    (`… * 100 < 30`) and records it as `_derivation.density_floor_pct`, then
    sets every layer's `target` to `floor + margin`. Only the FLOOR is the
    foundry's rule; the target is this plugin's own headroom. A config that
    declares no floor (a hand-written PDK-bridge one) returns None and keeps
    the strict promote-on-target behaviour — an absent floor is not evidence
    that some lower number would pass."""
    der = cfg.get("_derivation")
    if not isinstance(der, dict):
        return None
    pct = der.get("density_floor_pct")
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        return None
    if not (0.0 < float(pct) < 100.0):
        return None
    return float(pct) / 100.0


def _clears_foundry_floor(res: Dict[str, Any],
                          cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Disclosure dict when a PARTIAL fill nonetheless clears the FOUNDRY floor
    on EVERY layer, else None.

    Why this exists — the defect it removes
    ---------------------------------------
    Promotion used to require `verdict == PASS`, i.e. every layer reaching
    `floor + margin`. MEASURED on an organic gf180mcuD run: metal3 reached
    0.3497 against a 0.35 target — short of this plugin's own headroom by
    0.0003, and 0.0497 ABOVE the foundry's 0.30 rule. The whole fill was
    therefore left unpromoted, and the sign-off DRC consumed the UNFILLED GDS:
    6 density violations (M1.4 M2.4 M3.4 M4.4 M5.4 MT.3) on a layout whose
    filled sibling is DRC-CLEAN. Discarding the better artefact and shipping
    the worse one to sign-off is not conservatism — it manufactures the very
    violations the fill exists to prevent.

    This does NOT widen any constraint: the foundry's own DRC deck is
    untouched and still judges whatever is promoted. It only stops the flow
    from throwing away a layout that satisfies that deck.

    FAIL-CLOSED, so "has a density number" can never become the pass
    condition:
      * no `_derivation.density_floor_pct` in the config  -> None
      * a layer missing a numeric achieved density        -> None
      * ANY layer still below the floor                   -> None
      * ANY layer `over_max`                              -> None
    The achieved density used per layer is the WORST of the whole-die and
    worst-window figures, so a layer that clears the rule on average while
    failing it in some window does not promote."""
    floor = _foundry_floor(cfg)
    if floor is None:
        return None
    layers = res.get("layers")
    if not isinstance(layers, list) or not layers:
        return None
    worst_name, worst_val = None, None
    for lay in layers:
        if not isinstance(lay, dict):
            return None
        if lay.get("over_max"):
            return None
        vals = [lay.get(k) for k in ("density_after", "worst_window_after")]
        vals = [v for v in vals
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if not vals:
            return None                      # no measured density -> refuse
        got = min(float(v) for v in vals)
        if got < floor:
            return None
        if worst_val is None or got < worst_val:
            worst_name, worst_val = lay.get("name"), got
    return {
        "foundry_floor": round(floor, 6),
        "worst_layer": worst_name,
        "worst_layer_density": round(worst_val, 6) if worst_val is not None
        else None,
        "note": ("target (floor+margin) not reached on every layer, but every "
                 "layer clears the FOUNDRY floor the config was derived from "
                 "— promoted so the sign-off DRC judges the FILLED layout"),
    }


def _is_monotone_improvement(res: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Disclosure dict when the filled layout is no worse than the unfilled one
    on EVERY layer and strictly better on at least one, else None.

    Used only on the BELOW-floor PARTIAL branch, where the fill did not reach
    the foundry rule everywhere. The question there is not "is this compliant"
    (it is not, and the verdict says so) but "which of the two layouts the flow
    is holding should the sign-off DRC measure". Shipping the unfilled one makes
    the DRC report violations the flow had already fixed.

    FAIL-CLOSED — anything unmeasured refuses:
      * no layer list                              -> None
      * a layer with no numeric before/after pair  -> None
      * ANY layer whose achieved density DROPPED   -> None
      * ANY layer `over_max` (fill overshot a rule)-> None
      * no layer improved at all                   -> None (nothing to gain)
    Before/after are compared on the WORST of the whole-die and worst-window
    figures, the same basis `_clears_foundry_floor` uses."""
    layers = res.get("layers")
    if not isinstance(layers, list) or not layers:
        return None

    def _worst(lay, keys):
        vals = [lay.get(k) for k in keys]
        vals = [float(v) for v in vals
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return min(vals) if vals else None

    improved, moved = [], False
    for lay in layers:
        if not isinstance(lay, dict):
            return None
        if lay.get("skipped"):
            continue
        if lay.get("over_max"):
            return None
        before = _worst(lay, ("density_before", "worst_window_before"))
        after = _worst(lay, ("density_after", "worst_window_after"))
        if before is None or after is None:
            return None
        if after < before:
            return None                      # a regression -> refuse
        if after > before:
            moved = True
        improved.append({"layer": lay.get("name"),
                         "before": round(before, 6), "after": round(after, 6)})
    if not improved or not moved:
        return None
    return {
        "layers": improved,
        "note": ("at least one layer is BELOW the foundry floor, so the verdict "
                 "stays FAIL — but no layer REGRESSED and at least one improved, "
                 "so the FILLED layout is promoted and the sign-off DRC judges "
                 "the better of the two layouts this run produced"),
    }


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
    # SAME MATERIALISATION AS `cfg_path` JUST ABOVE, and for the identical
    # reason: `engine` resolves to a HOST path under the plugin's OWN
    # installation (`find_engine`'s vendored-copy branch), which a per-run
    # container mounts only if the caller happened to bind-mount the plugin
    # tree too. MEASURED (spm x gf180mcuD/sky130A/ihp-sg13g2, 2026-08-07): a
    # container whose ONLY mount is the project directory — the flow's own
    # default, `phase3_one_shot_runner._container_mounts` never mounts the
    # plugin install path — makes `runner.covers(engine)` False on every
    # single default run, so density fill silently DISCLOSED_SKIPped on
    # every PDK and no design this session ever got filled. `metal_fill.py`
    # is a single self-contained KLayout batch script (env-var driven, no
    # sibling imports at runtime — see its own module docstring), so copying
    # it beside the already-materialised config costs nothing semantically
    # and makes the SAME default container that already runs DRC/LVS/STA
    # able to run this too.
    if not runner.covers(engine):
        materialised_engine = rep.parent / engine.name
        materialised_engine.write_text(engine.read_text())
        engine = materialised_engine
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
    promote = res.get("verdict") == "PASS"
    if not promote and res.get("verdict") == "PARTIAL":
        # Target missed somewhere — promote anyway IFF every layer still
        # clears the foundry's own rule (see _clears_foundry_floor).
        above = _clears_foundry_floor(res, cfg)
        if above is not None:
            res["promoted_on_foundry_floor"] = above
            promote = True
        else:
            # Below the foundry floor on some layer. The pre-fix policy shipped
            # the UNFILLED GDS to sign-off in this case — which is the same
            # mistake `_clears_foundry_floor` was written to remove, only
            # partial. MEASURED (subservient x gf180mcuD, r7, the PDK's own
            # KLayout deck, three runs of the same command): the unfilled GDS
            # carries 5 density violations (M2.4 M3.4 M4.4 M5.4 MT.3) and the
            # filled sibling carries 2 (M2.4 M3.4) — the flow computed the fill
            # that closes M4.4/M5.4/MT.3 and then discarded it, so sign-off
            # reported three violations that do not exist in the layout the
            # flow had already produced.
            #
            # So promote a fill that is a MONOTONE IMPROVEMENT: no layer's
            # achieved density is lower than before the fill. This does NOT
            # touch the VERDICT — it stays PARTIAL/FAIL below the floor, and
            # the foundry's own deck still judges whatever is promoted. It only
            # stops the flow from choosing the worse of two layouts it holds.
            better = _is_monotone_improvement(res)
            if better is not None:
                res["promoted_on_monotone_improvement"] = better
                promote = True
    if promote and staged.is_file():
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
        above = res.get("promoted_on_foundry_floor")
        if above:
            # Disclosed, never silent: the target was missed, the FOUNDRY floor
            # was not. The filled GDS is promoted and the sign-off DRC — which
            # is not modified by any of this — judges it.
            print("metal_fill_emit: PARTIAL-ABOVE-FLOOR — this plugin's own "
                  "target (floor+margin) was NOT reached on every layer, but "
                  "every layer clears the FOUNDRY floor "
                  f"{above.get('foundry_floor')} (worst: "
                  f"{above.get('worst_layer')} at "
                  f"{above.get('worst_layer_density')}); the FILLED GDS is "
                  "promoted and the sign-off DRC judges it")
            return PASS
        mono = res.get("promoted_on_monotone_improvement")
        print("metal_fill_emit: FAIL — density target NOT reached on every "
              "layer (achieved densities disclosed above), and at least one "
              "layer is BELOW the foundry floor"
              + (" — the FILLED GDS is promoted anyway because no layer "
                 "regressed and at least one improved, so the sign-off DRC "
                 "judges the better of the two layouts; the VERDICT is "
                 "unchanged: this fill does NOT meet the foundry rule"
                 if mono else " — the filled GDS is NOT promoted"))
        return FAIL
    print(f"metal_fill_emit: FAIL — {res.get('reason') or res.get('error')}")
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
