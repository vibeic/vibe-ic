#!/usr/bin/env python3
"""die_density_fill_gen.py — DIE-WIDE dummy fill, by the PDK's OWN generator.

WHAT GAP THIS CLOSES
--------------------
Foundry minimum-density rules are written "over the entire die". The flow's own
fill and its own density measurement were both scoped to the BOUNDING BOX OF
THE STREAMED GEOMETRY, which on a slot submission is the routed CORE sitting
inside a much larger die. Those are different denominators, and on a sparse
design they disagree by the ratio between them.

MEASURED 2026-08-20 on a gf180mcuD 0.5x0.5-slot die (1936 x 2531 um) whose core
occupies 1052 x 1647 um -- 35.4 % of the die -- with the flow's existing fill
already applied and reporting success:

    reports/phase3/cmp_fill_emit.json   metal2 0.0036 -> 0.4330  "reached": true
    reports/phase3/metal_density.json   "die_area_um2": 1732693   <- the CORE

    the shuttle operator's own precheck, same GDS, sealed, 8 density errors:
      DCF.1b  PL.8  M1.4  M2.4  M3.4  M4.4  M5.4  MT.3
      every one reported against the whole die polygon (0,0;1936,2531)

    measured over the DIE instead of over the core bbox:
      COMP+dummy 3.04 %   Poly2+dummy 0.12 %   Metal1 8.26 %
      Metal2 18.21 %  Metal3 17.97 %  Metal4 18.45 %  Metal5 18.48 %

The fill was not missing. It was scoped to the wrong rectangle, and nothing
measured the right one, so a die that was 64.6 % bare metal-free silicon
reported "reached target on every layer".

WHY THE PDK'S OWN GENERATOR, AND NOTHING OF THIS PROGRAM'S OWN
---------------------------------------------------------------
Dummy fill is foundry data: the fill cell size, the lattice pitch, the
keep-outs to active metal / poly fuses / OTP markers / the scribe line, and the
per-layer minimum space are all in the foundry's design manual. gf180mcuD ships
exactly that as `libs.tech/klayout/tech/scripts/fill_all.rb`, which drives
`fill_comp.rb`, `fill_poly2.rb` and `fill_metal.rb`, depositing on the very
dummy datatypes the PDK's own density deck counts (`metalN = drawn + dummy`).

This program CALLS that script. It contains no fill cell, no pitch, no keep-out
and no density target -- and no layer number. What it adds is everything the
PDK script deliberately leaves to its caller:

  * it finds the generator, and NAMES every location it looked in when there is
    none, so "this PDK ships no filler" is a checkable statement;
  * it measures the die BEFORE and AFTER, over the DIE rectangle the slot
    declares, not over whatever bounding box exists;
  * it does not trust the exit code. The PDK's sibling `sealring.py` was
    measured exiting 0 having written nothing (a bare `sys.exit()` after a
    failed import); `fill_all.rb` writes its output on its last line, so an
    early raise leaves the same silence. The output layout is verified to
    exist, to be readable and to have GAINED geometry;
  * it checks the one thing the PDK script cannot check about itself: its fill
    frame is `$ly.top_cell().dbbox()`, so it can only ever fill the bounding
    box it is given. When that bounding box does not cover the declared die,
    the fill CANNOT satisfy a die-wide rule, and this program says so instead
    of reporting the fill it did do as if it were die-wide.

ORDER IS PART OF THE FIX. The generator's frame is the layout bounding box, and
its scribe keep-out is measured inward from that frame. So it must run AFTER
the seal ring (which is what makes the bounding box the die) and BEFORE the
density checks and the sign-off DRC read the GDS -- LibreLane's own chip-flow
order, SealRing -> Filler -> Density.

NO FLOOR IS APPLIED HERE. Which layers must reach what coverage is the PDK's
density rule deck's to say, and the sign-off DRC step already runs it. This
program reports measured coverage per layer over both denominators and lets the
deck judge. A second, independently-written floor would be a second opinion
about foundry data.

HONEST DEGRADATION (S4.05)
--------------------------
A PDK that ships no fill generator, a missing KLayout, or no streamed GDS is a
NAMED, DISCLOSED skip (rc 2 + the `VACUOUS_PASS:` sentinel), never a silent
"filled". A generator that ran and deposited nothing, and a fill whose frame
did not cover the die, are FAILs with the measurement in the report -- the GDS
is left untouched in the first case and disclosed as core-only in the second.

chip/PDK-AGNOSTIC: the generator path, the die rectangle and the top-cell name
are all INPUTS. No foundry, PDK, vendor, layer number or design literal appears
in this file.

    die_density_fill_gen <project_dir> [--gds G] [--script S] [--pdk-root R]
                         [--pdk P] [--die-width W] [--die-height H]
                         [--cell TOP] [--threads N] [--ignore-active]
                         [--out O | --in-place] [--report R] [--json J]
    main(argv) -> int : 0 filled / 1 FAIL / 2 DISCLOSED SKIP
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _atomic_artefact import write_json as atomic_write_json  # vibe-ic#1082

try:
    from . import _klayout_launch as _kl                     # type: ignore
except ImportError:                                          # standalone gate
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _klayout_launch as _kl                            # type: ignore

PASS, FAIL, SKIP = 0, 1, 2

_CHECK = "die_density_fill"
#: Written by this program on EVERY path; read, never overwritten, by the gate.
_PRODUCER = "die_density_fill_gen"

#: Same order and same reason as `die_finishing_gen`: `phase3/stage3/pnr` is the
#: artefact the sign-off DRC and LVS actually read, and the stage-4 copy is only
#: published when it is byte-identical to it. Filling the published copy would
#: fill the die AFTER its evidence.
_GDS_GLOBS = (
    "phase3/stage3/pnr/*.gds",
    "phase3/stage4/gds/*.gds",
)
#: The path a PDK that ships a KLayout density filler puts it at. This is PDK
#: STRUCTURE, not a PDK name: it resolves for any PDK laid out that way and for
#: none that is not. Same directory `die_finishing_gen` reads `sealring.py` from.
_PDK_SCRIPT_REL = "libs.tech/klayout/tech/scripts/fill_all.rb"
#: A project/PDK-bridge may declare a different one; an environment already set
#: up for the canonical flow may export it.
_ENV_SCRIPT = "KLAYOUT_FILL_SCRIPT"
_BRIDGE_CFG = "input/pdk/bridge/signoff_config.json"
_BRIDGE_KEY = "die_density_fill"
#: NAMING IS LOAD-BEARING: `metal_layer_density_check` rglobs
#: `*metal*density*.json` project-wide, so this report must NOT match that.
_REPORT_REL = "reports/phase3/die_density_fill.json"

#: The two engines shipped beside this program. Neither carries foundry data:
#: the driver only types the PDK script's globals, the measurement only counts
#: what the layout carries.
_DRIVER_REL = "density_fill/pdk_fill_driver.rb"
_MEASURE_REL = "density_fill/die_density_measure.py"


def _bridge(project: Path) -> Dict[str, Any]:
    """The PDK-bridge declaration for this step, or {}."""
    p = project / _BRIDGE_CFG
    try:
        cfg = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    sub = cfg.get(_BRIDGE_KEY) if isinstance(cfg, dict) else None
    return sub if isinstance(sub, dict) else {}


def _first(project: Path, globs) -> Optional[Path]:
    for g in globs:
        hits = sorted(p for p in project.glob(g) if p.is_file())
        if hits:
            return hits[0]
    return None


def _skip(reason: str, **extra) -> Dict[str, Any]:
    out: Dict[str, Any] = {"state": "DISCLOSED_SKIP", "reason": reason}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def resolve_script(project: Path, explicit: Optional[str],
                   pdk_root: Optional[str],
                   pdk: Optional[str]) -> Tuple[Optional[str], str, List[str]]:
    """(script, source, tried) — the PDK's density-fill generator.

    Order, first hit wins, every step named in `tried`, so an absence is a
    STATEMENT about specific locations rather than a shrug. Existence is NOT
    checked here: the script lives wherever KLayout lives, which may be inside
    a container with no host counterpart, so only the resolved runner can
    answer that.
    """
    tried: List[str] = []
    if explicit:
        return explicit, "--script", tried
    cfg = _bridge(project)
    tried.append(f"{_BRIDGE_CFG}:{_BRIDGE_KEY}.script")
    if isinstance(cfg.get("script"), str) and cfg["script"]:
        return cfg["script"], f"{_BRIDGE_CFG}:{_BRIDGE_KEY}.script", tried
    tried.append(f"${_ENV_SCRIPT}")
    env_script = os.environ.get(_ENV_SCRIPT)
    if env_script:
        return env_script, f"${_ENV_SCRIPT}", tried
    root = pdk_root or os.environ.get("PDK_ROOT")
    name = pdk or os.environ.get("PDK")
    if root and name:
        cand = f"{root.rstrip('/')}/{name}/{_PDK_SCRIPT_REL}"
        tried.append(cand)
        return cand, "$PDK_ROOT/$PDK/" + _PDK_SCRIPT_REL, tried
    tried.append("$PDK_ROOT/$PDK/" + _PDK_SCRIPT_REL + " (PDK_ROOT/PDK not set)")
    return None, "", tried


def measure(runner, engine: Path, gds: Path, out_json: Path,
            die: Optional[List[float]], die_source: str,
            cell: Optional[str], timeout: int) -> Tuple[Optional[Dict[str, Any]], str]:
    """Run the measurement engine in the runner's environment; parse its JSON."""
    spec = {"die": die, "die_source": die_source, "layers": None}
    env = {"DENS_GDS": str(gds), "DENS_OUT": str(out_json),
           "DENS_SPEC": json.dumps(spec)}
    if cell:
        env["DENS_CELL"] = cell
    rc, out, err = runner.run(engine, env,
                              path_keys=("DENS_GDS", "DENS_OUT"),
                              timeout=timeout)
    if not out_json.is_file():
        return None, (f"the density measurement wrote no report (rc={rc}): "
                      + ((err or out or "").strip().splitlines() or [""])[-1][:300])
    try:
        res = json.loads(out_json.read_text())
    except (OSError, ValueError) as exc:
        return None, f"the density measurement report is unreadable: {exc}"
    if isinstance(res, dict) and res.get("error"):
        return None, str(res["error"])
    return res, ""


def census(runner, engine: Path, gds, out_json: Path,
           cell: Optional[str], timeout: int) -> Optional[Dict[str, int]]:
    """{"<layer>/<datatype>": shape_count} for `gds`, in the runner's environment.

    A COUNT, not an area: the only question it answers is WHICH layers carry
    geometry, and merging a filled die's polygons to answer that costs tens of
    seconds where counting costs two.
    """
    env = {"DENS_GDS": str(gds), "DENS_OUT": str(out_json),
           "DENS_COUNT_ONLY": "1"}
    if cell:
        env["DENS_CELL"] = cell
    runner.run(engine, env, path_keys=("DENS_GDS", "DENS_OUT"), timeout=timeout)
    if not out_json.is_file():
        return None
    try:
        return (json.loads(out_json.read_text()) or {}).get("shape_census")
    except (OSError, ValueError):
        return None


def _layers_with_geometry(cen: Dict[str, int]) -> Dict[int, int]:
    """GDS layer number -> total shape count across its datatypes."""
    out: Dict[int, int] = {}
    for spec, n in (cen or {}).items():
        try:
            layer = int(str(spec).split("/")[0])
        except (TypeError, ValueError):
            continue
        out[layer] = out.get(layer, 0) + int(n)
    return out


def _grew(before: Dict[str, int], after: Dict[str, int]) -> set:
    """GDS layer numbers that gained shapes between two censuses."""
    b, a = _layers_with_geometry(before), _layers_with_geometry(after)
    return {layer for layer, n in a.items() if n > b.get(layer, 0)}


_REQUIRE_RE = re.compile(r"""require_relative\s*\(?\s*['"]([^'"]+)['"]""")


def sibling_passes(runner, script: str, timeout: int) -> List[str]:
    """The per-layer-family scripts the PDK's top-level generator pulls in.

    READ out of the PDK's own file, never listed here: a top-level filler is a
    sequence of `require_relative` calls, one per family, and which families a
    PDK ships is PDK data. Returns [] when the file cannot be read or names
    none, which is the honest answer for a single-file generator.
    """
    rc, out, _err = runner.run_argv(["cat", script], {}, timeout=timeout)
    if rc != 0 or not out:
        return []
    seen: List[str] = []
    for name in _REQUIRE_RE.findall(out):
        if name not in seen:
            seen.append(name)
    return seen


def _coverage_table(before: Dict[str, Any],
                    after: Dict[str, Any]) -> Dict[str, Any]:
    """Per GDS layer number: coverage over the die before and after, and the
    dummy area this fill added. Sorted by layer so the table is stable."""
    tab: Dict[str, Any] = {}
    b = before.get("by_layer") or {}
    a = after.get("by_layer") or {}
    for layer in sorted(set(b) | set(a), key=lambda s: int(s)):
        rb, ra = b.get(layer) or {}, a.get(layer) or {}
        tab[layer] = {
            "over_die_before": rb.get("over_die"),
            "over_die_after": ra.get("over_die"),
            "over_bbox_before": rb.get("over_bbox"),
            "over_bbox_after": ra.get("over_bbox"),
            "area_um2_added": (
                (ra.get("area_um2") or 0.0) - (rb.get("area_um2") or 0.0)),
            "datatypes_after": ra.get("datatypes"),
        }
    return tab


def run(project: Path, gds: Optional[str], script: Optional[str],
        pdk_root: Optional[str], pdk: Optional[str],
        width: Optional[float], height: Optional[float],
        cell: Optional[str], threads: Optional[int], ignore_active: bool,
        out: Optional[str], in_place: bool, report: Optional[str],
        timeout: int,
        skip_passes: Optional[List[str]] = None,
        owned_layers: Optional[List[int]] = None) -> Dict[str, Any]:
    rep = Path(report) if report else (project / _REPORT_REL)
    if not rep.is_absolute():
        rep = project / rep

    def done(fill: Dict[str, Any]) -> Dict[str, Any]:
        res = {"producer": _PRODUCER, "check": _CHECK, "fill": fill}
        try:
            rep.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(rep, res)
        except OSError as exc:                               # noqa: BLE001
            res.setdefault("report_unwritable", str(exc))
        return res

    here = Path(__file__).resolve().parent
    driver, engine = here / _DRIVER_REL, here / _MEASURE_REL
    for p in (driver, engine):
        if not p.is_file():
            return done({"state": "FAIL",
                         "reason": f"this program's own engine is missing: {p}"})

    script, src, tried = resolve_script(project, script, pdk_root, pdk)
    if not script:
        named = pdk or os.environ.get("PDK") or "this PDK"
        return done(_skip(
            f"no density-fill generator is declared for the {named} PDK — "
            "die-wide dummy fill may not be supported for it, so this step is "
            "SKIPPED and no fill is claimed (looked for: "
            + "; ".join(tried) + ")", pdk=named, tried=tried))

    gds_path = Path(gds) if gds else _first(project, _GDS_GLOBS)
    if gds_path is not None and not gds_path.is_absolute():
        gds_path = project / gds_path
    if gds_path is None or not gds_path.is_file():
        return done(_skip(
            "no streamed GDS to fill (looked for " + ", ".join(_GDS_GLOBS) + ")",
            script=script, script_source=src))

    runner = _kl.find_runner()
    if runner is None:
        return done(_skip(
            "no KLayout runner available (no strmrun/klayout on PATH and no "
            "KLayout in $VIBEIC_EDA_CONTAINER) — no fill was deposited",
            script=script, script_source=src))
    if not runner.covers(gds_path):
        return done(_skip(
            f"the GDS at {gds_path} is not reachable from the {runner.kind} "
            f"KLayout environment ({runner.detail}) — no fill was deposited",
            script=script, script_source=src))
    if not runner.exists(script):
        # Same distinction `die_finishing_gen` draws, and for the same reason:
        # a path the PDK/project DECLARED and that is not there is a broken
        # declaration; the conventional `$PDK_ROOT/$PDK/...` path is one this
        # program constructed, and its absence means only that this PDK ships
        # no KLayout density filler.
        constructed = src.startswith("$PDK_ROOT/$PDK/")
        named = pdk or os.environ.get("PDK") or "this PDK"
        return done(_skip(
            (f"no density-fill generator for the {named} PDK: nothing at the "
             f"conventional {script} in the {runner.kind} environment "
             f"({runner.detail}). Die-wide dummy fill may not be supported for "
             f"{named}; this step is SKIPPED and no fill is claimed"
             if constructed else
             f"the density-fill generator declared by {src} ({script}) does "
             f"not exist in the {runner.kind} environment ({runner.detail}) — "
             f"die-wide dummy fill is SKIPPED for the {named} PDK and no fill "
             "is claimed"),
            pdk=named, script=script, script_source=src, tried=tried))

    die: Optional[List[float]] = None
    die_source = "the layout's own bounding box (no die rectangle was declared)"
    if width and height:
        die = [0.0, 0.0, float(width), float(height)]
        die_source = "--die-width/--die-height"

    skip_passes = [p for p in (skip_passes or []) if p]
    owned_layers = sorted({int(v) for v in (owned_layers or [])})
    common = {"script": script, "script_source": src,
              "runner": f"{runner.kind}:{runner.detail}",
              "gds_in": str(gds_path),
              "die_um": die, "die_source": die_source,
              "skipped_passes": skip_passes,
              "skipped_passes_reason": (
                  "these layer families are filled by this flow's own "
                  "density-targeted engine; running a second generator over a "
                  "dummy layer that already carries fill produces geometry "
                  "neither generator checked against the other's"
                  if skip_passes else None)}

    tmpdir = gds_path.parent
    before_json = tmpdir / (gds_path.stem + ".density_before.json")
    after_json = tmpdir / (gds_path.stem + ".density_after.json")
    filled = tmpdir / (gds_path.stem + ".filled.gds")

    before, why = measure(runner, engine, gds_path, before_json, die,
                          die_source, cell, timeout)
    if before is None:
        return done(dict(common, state="FAIL",
                         reason=f"could not measure the die BEFORE filling: {why}"))
    if die is None:
        die = list(before.get("bbox_um") or [])
        common["die_um"] = die

    # THE ONE CHECK THE PDK SCRIPT CANNOT MAKE ABOUT ITSELF. Its fill frame is
    # `$ly.top_cell().dbbox()`. If that bounding box does not cover the die, no
    # invocation of it can put a single fill shape on the part of the die it
    # never sees, and a die-wide minimum-density rule will fail on exactly that
    # part. Measured, not assumed, and reported as the reason rather than as a
    # fill that "reached target".
    covers = before.get("bbox_covers_die")
    bbox_frac = before.get("bbox_area_over_die_area")

    def generate(out_gds: Path, skip: List[str]):
        """Run the PDK generator into `out_gds`, skipping the named passes."""
        if out_gds.exists():
            try:
                out_gds.unlink()
            except OSError:
                pass
        env = {"VIBEIC_FILL_SCRIPT": script,
               "VIBEIC_FILL_IN": str(gds_path),
               "VIBEIC_FILL_OUT": str(out_gds)}
        if threads:
            env["VIBEIC_FILL_THREADS"] = str(int(threads))
        if ignore_active:
            env["VIBEIC_FILL_IGNORE_ACTIVE"] = "1"
        if skip:
            env["VIBEIC_FILL_SKIP"] = ",".join(skip)
        rc, sout, serr = runner.run(
            driver, env,
            # VIBEIC_FILL_SCRIPT is deliberately NOT translated: a PDK inside
            # the container has no host counterpart, so rewriting its path
            # would corrupt a perfectly valid one.
            path_keys=("VIBEIC_FILL_IN", "VIBEIC_FILL_OUT"), timeout=timeout)
        return rc, ((sout or "") + ("\n" + serr if serr else "")).strip()

    # ── ONE WRITER PER DUMMY LAYER ────────────────────────────────────────
    # A layer this flow has ALREADY filled must not be filled a second time by
    # the PDK's generator. The PDK's per-layer keep-out is computed from the
    # DRAWN datatype alone -- its design manual assumes its filler is the only
    # one -- so it cannot see, and cannot avoid, fill that is already there.
    # MEASURED on gf180mcuD, one die filled by both: 234437 KLayout DRC errors
    # (min-space and min-width on the merged metal) where each filler ALONE was
    # DRC-clean. Neither filler is wrong; running both over one layer is.
    #
    # WHICH PASS to leave out is DISCOVERED, not declared: the top-level
    # generator's own `require_relative` list names its per-family passes, and
    # running each skip once says which layers that family contributes. A shape
    # CENSUS answers it in ~2 s per probe, so this costs one extra generator run
    # per family and nothing is guessed about a PDK's file names.
    contested: List[int] = []
    probe_log: Dict[str, Any] = {}
    cen_in = census(runner, engine, gds_path, tmpdir / (gds_path.stem + ".census_in.json"),
                    cell, timeout)
    if owned_layers and cen_in is not None:
        have = _layers_with_geometry(cen_in)
        contested = [l for l in owned_layers if have.get(l)]
    common["owned_layers"] = owned_layers
    common["contested_layers"] = contested

    rc, transcript = generate(filled, skip_passes)
    if filled.is_file() and contested and not skip_passes:
        cen_full = census(runner, engine, filled,
                          tmpdir / (gds_path.stem + ".census_full.json"),
                          cell, timeout)
        touched = _grew(cen_in or {}, cen_full or {}) if cen_full else set()
        clash = sorted(set(contested) & touched)
        probe_log["layers_the_whole_generator_writes"] = sorted(touched)
        probe_log["clash"] = clash
        if clash:
            siblings = sibling_passes(runner, script, timeout)
            probe_log["sibling_passes"] = siblings
            per_pass: Dict[str, List[int]] = {}
            probe_out = tmpdir / (gds_path.stem + ".probe.gds")
            keep_probe = None
            for sib in siblings:
                prc, _ptx = generate(probe_out, [sib])
                if not probe_out.is_file():
                    continue
                cen_p = census(runner, engine, probe_out,
                               tmpdir / (gds_path.stem + ".census_probe.json"),
                               cell, timeout)
                without = _grew(cen_in or {}, cen_p or {}) if cen_p else touched
                per_pass[sib] = sorted(touched - without)
                if sorted(set(contested) & set(per_pass[sib])) == clash:
                    keep_probe = (sib, probe_out.read_bytes())
            probe_log["layers_per_pass"] = per_pass
            skip_passes = [sib for sib, layers in per_pass.items()
                           if set(layers) & set(contested)]
            probe_log["chosen_skip"] = skip_passes
            if not skip_passes:
                return done(dict(
                    common, state="FAIL", probe=probe_log,
                    reason=("this flow has already filled layer(s) "
                            + ", ".join(str(l) for l in clash) + ", and the PDK "
                            "generator writes them too, but no single pass of it "
                            "could be identified as the one that does. Running "
                            "both fillers over one dummy layer produces geometry "
                            "neither checked against the other's, so no fill was "
                            "promoted. Declare the pass to leave out with "
                            "--skip-pass (the generator's passes are: "
                            + ", ".join(siblings or ["<none found>"]) + ")")))
            if keep_probe and [keep_probe[0]] == skip_passes:
                filled.write_bytes(keep_probe[1])      # already computed
                rc, transcript = 0, transcript
            else:
                rc, transcript = generate(filled, skip_passes)
            common["skipped_passes"] = skip_passes
            common["skipped_passes_reason"] = (
                "these layer families are already filled by this flow's own "
                "density-targeted engine (layer(s) "
                + ", ".join(str(l) for l in clash)
                + "); a second generator over a dummy layer that already "
                  "carries fill produces geometry neither generator checked "
                  "against the other's")
    if probe_log:
        common["probe"] = probe_log
    common["generator_rc"] = rc
    common["generator_output"] = transcript[-2000:]

    # DO NOT TRUST THE EXIT CODE. Measured on this PDK's sibling generator
    # (`sealring.py`): a failed import ends in a bare `sys.exit()`, which exits
    # 0 and writes nothing. `fill_all.rb` writes its output on its LAST line,
    # so anything that stops it early leaves the same silence behind a rc the
    # caller would read as success.
    if not filled.is_file():
        return done(dict(
            common, state="FAIL",
            reason=("the PDK density-fill generator produced no output layout "
                    f"at {filled} — it exited {rc} and said: "
                    + (transcript[-400:] or "<nothing>")
                    + ". No fill was deposited; the GDS is unchanged.")))

    after, why = measure(runner, engine, filled, after_json, die, die_source,
                         cell, timeout)
    if after is None:
        return done(dict(common, state="FAIL",
                         reason=f"could not measure the filled die: {why}"))

    table = _coverage_table(before, after)
    added = sum(v["area_um2_added"] for v in table.values()
                if (v.get("area_um2_added") or 0) > 0)
    gained = sorted((int(k) for k, v in table.items()
                     if (v.get("area_um2_added") or 0) > 0))
    common.update({
        "gds_out": str(filled),
        "bbox_um_before": before.get("bbox_um"),
        "bbox_um_after": after.get("bbox_um"),
        "bbox_covers_die": covers,
        "bbox_area_over_die_area": bbox_frac,
        "layers_gained_fill": gained,
        "area_um2_added": added,
        "coverage_over_die": table,
        "measurement_before": str(before_json),
        "measurement_after": str(after_json),
    })

    if not gained:
        return done(dict(
            common, state="FAIL",
            reason=("the PDK density-fill generator ran and wrote a layout, "
                    "but not one layer gained area — no dummy fill was "
                    "deposited. The GDS is unchanged.")))

    # Promote only a layout that actually gained fill.
    dest = Path(out) if out else (gds_path if in_place else filled)
    if dest != filled:
        try:
            dest.write_bytes(filled.read_bytes())
            common["promoted_to"] = str(dest)
        except OSError as exc:                               # noqa: BLE001
            return done(dict(common, state="FAIL",
                             reason=f"could not promote the filled layout: {exc}"))

    if covers is False:
        return done(dict(
            common, state="FAIL",
            reason=(
                "the PDK density-fill generator filled its frame, but that "
                "frame is the layout's bounding box "
                f"{before.get('bbox_um')} and it does NOT cover the declared "
                f"die {die}. It covers "
                f"{(bbox_frac or 0.0) * 100:.1f} % of the die area, so "
                f"{(1.0 - (bbox_frac or 0.0)) * 100:.1f} % of the die carries "
                "no fill and cannot satisfy a die-wide minimum-density rule. "
                "The fill that WAS deposited is real and is kept; what is "
                "refused is the claim that the die is filled. Seal the die to "
                "its declared size first — the ring is what makes the "
                "bounding box the die.")))

    return done(dict(
        common, state="PASS",
        reason=("the PDK's own density-fill generator filled the declared die: "
                f"{len(gained)} layer(s) gained {added:.0f} um2 of dummy fill "
                f"over a {die[2] - die[0]:.0f} x {die[3] - die[1]:.0f} um die")))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="die_density_fill_gen",
        description="Die-wide dummy fill by the PDK's own generator.")
    ap.add_argument("project")
    ap.add_argument("--gds")
    ap.add_argument("--script")
    ap.add_argument("--pdk-root")
    ap.add_argument("--pdk")
    ap.add_argument("--die-width", type=float)
    ap.add_argument("--die-height", type=float)
    ap.add_argument("--cell")
    ap.add_argument("--threads", type=int)
    ap.add_argument("--owned-layer", action="append", type=int, default=[],
                    help="a GDS layer number this flow's own filler already "
                         "writes (repeatable). When the PDK generator would "
                         "write it too, the pass that does is DISCOVERED and "
                         "left out, so no dummy layer has two authors.")
    ap.add_argument("--skip-pass", action="append", default=[],
                    help="a sibling script the PDK generator require_relatives "
                         "and THIS FLOW is providing itself (repeatable). Two "
                         "generators writing one dummy layer produce fill "
                         "neither checked against the other; naming the pass "
                         "the flow already owns is how that is avoided.")
    ap.add_argument("--ignore-active", action="store_true",
                    help="set the PDK generator's own $Metal<N>_ignore_active "
                         "switches (drops its fill-to-adjacent-metal spacing)")
    ap.add_argument("--timeout", type=int, default=3600)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--out")
    g.add_argument("--in-place", action="store_true")
    ap.add_argument("--report")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    project = Path(args.project).resolve()
    res = run(project, args.gds, args.script, args.pdk_root, args.pdk,
              args.die_width, args.die_height, args.cell, args.threads,
              args.ignore_active, args.out, args.in_place, args.report,
              args.timeout, skip_passes=args.skip_pass,
              owned_layers=args.owned_layer)
    if args.json:
        o = Path(args.json)
        if not o.is_absolute():
            o = project / o
        try:
            o.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(o, res)
        except OSError:                                      # noqa: BLE001
            pass

    fill = res.get("fill") or {}
    state = fill.get("state")
    reason = fill.get("reason", "")
    if state == "DISCLOSED_SKIP":
        print(f"VACUOUS_PASS: {_PRODUCER}: {reason}")
        return SKIP
    if state == "PASS":
        print(f"{_PRODUCER}: {reason}")
        return PASS
    print(f"{_PRODUCER}: {reason}")
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
