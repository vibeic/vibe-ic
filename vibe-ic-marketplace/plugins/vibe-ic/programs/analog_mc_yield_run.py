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
        [--n 100] [--container vibeic-eda] [--pdk sky130]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import analog_real_corner_sweep as _ars  # noqa: E402  (docker/ngspice helpers)
import _designs_root as _dr  # noqa: E402  (host mount root, measured)

# PDK Monte-Carlo model sections — the corner section that ENABLES device
# MISMATCH resampling (the foundry's own mismatch distribution). ORGANIC #142
# (corrected): a typical corner section HARDCODES `mc_mm_switch=0`, so a
# deck-level override is ignored (the section wins) and every run returns the
# IDENTICAL value (sigma≈0). The proven idiom is the MISMATCH corner section:
# sky130 `tt_mm` sets `mc_mm_switch=1` (verified: LDO vout sigma 6.8e-16 → 9.81
# mV). The `mc` section (mc_mm_switch=0, mc_pr_switch=1) does NOT resample
# mismatch and additionally lacks the base device-model include. PDK-family
# namespaced, never chip-specific. The degeneracy guard below is the
# family-agnostic backstop: if the chosen section still yields no spread the run
# is flagged UNSCOREABLE rather than reporting a fabricated 100%/0% yield.
_MC_SECTION = {"sky130": "tt_mm", "gf180": "statistical"}

# ORGANIC #142 — a MC result is only scoreable when the samples actually vary.
# < this many DISTINCT measured values for a spec ⇒ degenerate (no statistical
# spread) ⇒ that spec is UNSCOREABLE, never a fabricated yield.
_MIN_DISTINCT_MC_VALUES = 2

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


# ORGANIC #142 — a MC iteration is only scoreable against a deck that
# actually RUNS an analysis. A bare `.subckt … .ends` library (the A3
# canonical artefact) instantiates nothing → every wrapped run loads a model
# set and runs no analysis → 0 scoreable measures. Rank candidate decks so a
# RUNNABLE deck (top-level analysis card / TB harness — e.g. the sizing_loop
# decks) always wins over a bare subckt library, searching subdirs too.
_ANALYSIS_CARD_RE = re.compile(
    r"(?im)^\s*\.(control|tran|ac|dc|op|meas|noise|four|disto|pz|sens|tf)\b")
_ECHO_MEAS_RE = re.compile(r"(?im)^\s*echo\s+.*\bMEAS\b")
_MEAS_CARD_RE = re.compile(r"(?im)^\s*\.meas")
_SUBCKT_RE = re.compile(r"(?im)^\s*\.subckt\b")


def _deck_rank(text: str) -> int:
    """Rank a candidate .sp for MC-yield scoreability (higher = better):
      3  runnable AND emits a scoreable measure (.meas / echo MEAS)
      2  runnable (has a top-level analysis card) but no explicit measure
      0  NOT runnable (bare `.subckt … .ends` library / no analysis card)
    chip-AGNOSTIC: keyed on standard ngspice analysis-card syntax only."""
    # An analysis card that sits INSIDE a `.control … .endc` block still
    # counts; the regex is line-anchored and `.control`/`.meas`/`echo MEAS`
    # are the load-bearing tokens. A bare subckt library has none of them.
    runnable = bool(_ANALYSIS_CARD_RE.search(text)) or bool(
        _ECHO_MEAS_RE.search(text))
    if not runnable:
        return 0
    scoreable = bool(_MEAS_CARD_RE.search(text)) or bool(
        _ECHO_MEAS_RE.search(text))
    return 3 if scoreable else 2


def _find_deck(project: Path, block: str):
    """Return (deck_path, rank) for the best RUNNABLE deck, or (None, 0) when
    only bare `.subckt` libraries exist. Searches `phase{2,3}/analog/<block>/`
    recursively (incl. `sizing_loop/`). Deterministic: rank desc, then the
    shallowest path, then lexical."""
    cands: list[tuple[int, int, str, Path]] = []
    for base in (project / "phase2" / "analog" / block,
                 project / "phase3" / "analog" / block):
        if not base.is_dir():
            continue
        for sp in base.rglob("*.sp"):
            if not sp.is_file():
                continue
            try:
                text = sp.read_text(errors="replace")
            except OSError:
                continue
            rank = _deck_rank(text)
            depth = len(sp.relative_to(base).parts)
            cands.append((rank, depth, str(sp), sp))
    if not cands:
        return None, 0
    # rank DESC (higher better), then depth ASC (shallow first), then path ASC.
    best = min(cands, key=lambda c: (-c[0], c[1], c[2]))
    return (best[3] if best[0] > 0 else None), best[0]


# ── ORGANIC #150 — native custom-PDK Monte-Carlo consumption ────────────────
# When the L19 target resolves to a rung-1/2 NATIVE custom PDK
# (analog_pdk_availability), the MC deck must load the RESOLVED native
# statistical/mismatch lib — never overlay the open-PDK (sky130 tt_mm) mismatch
# section on a native deck. That hybrid both (1) trips analog_netlist_pdk_check
# PDK_MISMATCH and (2) applies sky130 statistics to native devices → no real
# spread (sigma≈0). If the native family stages NO mc/mismatch lib → honest
# UNSCOREABLE (the degeneracy-guard family), NEVER a cross-family overlay.

# A `.lib <section>` name that enables device MISMATCH resampling in a native
# mismatch lib (family-agnostic name hint; the resolver already narrowed to the
# mismatch LIB — this only picks the mismatch SECTION inside it).
_NATIVE_MC_SECTION_HINT = re.compile(
    r"(?i)(mismatch|_mm(?:_|\b)|statistical|stat|agauss|montecarlo)")

# An include-FORM model line: `.lib <path> <section>` or `.include <path>` where
# the path token carries a directory separator. Distinct from a `.lib <section>`
# section-DEFINITION line (no path) that lives INSIDE a model lib. Stripping this
# from the deck body lets the MC wrapper own the SINGLE model source (no mixing).
_INCLUDE_FORM_MODEL_RE = re.compile(
    r"(?im)^\s*\.(?:lib\s+\S*[\\/]\S+\s+\S+|include\s+\S*[\\/]\S+)\s*$")


def _pick_native_mc_section(mc_lib: str):
    """The `.lib <section>` name the MC wrapper loads out of the native mismatch
    lib: a mismatch/statistical-hinted section, else a typ section, else the
    first. None ⇒ the lib carries no `.lib <section>` definitions ⇒ the wrapper
    loads the whole file with `.include` instead. Reads the staged host path
    (rung-1 mc_libs are host paths); returns None on any read failure."""
    try:
        txt = Path(mc_lib).read_text(errors="replace")
    except OSError:
        return None
    try:
        import analog_pdk_deck_context as _apdc
        secs = _apdc.parse_sections(txt)
    except Exception:
        secs = []
    if not secs:
        return None
    for s in secs:
        if _NATIVE_MC_SECTION_HINT.search(s):
            return s
    for s in secs:
        if s in ("tt", "typ", "nom", "tm") or s.startswith(("tt", "typ")):
            return s
    return secs[0]


def _resolve_native_mc(project: Path, container: str):
    """Resolve the NATIVE MC model include for a rung-1/2 resolved custom PDK.

    Returns one of:
      * None                        — no native resolution (rung 3 / no L19
                                      target / a known open family) → the caller
                                      keeps the open-PDK (sky130/gf180) path.
      * {"mc_lib", "mc_section",…}  — a resolved native mismatch lib to load.
      * {"unscoreable": <reason>}   — native family resolved but stages NO
                                      mc/mismatch lib → honest UNSCOREABLE
                                      (never a cross-family overlay).
    chip-AGNOSTIC; NDA-safe (paths only)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import analog_pdk_availability as _apa
        import analog_netlist_pdk_check as _npc
    except Exception:
        return None
    # vibe-ic#576 — see `analog_one_shot_runner._try_native_a6_pv`: the
    # resolver tries the project-staged rung before it needs a target, so an
    # undeclared but fully staged project must be allowed to reach it.
    declared = _npc._declared_pdk_target(Path(project))
    try:
        res = _apa.resolve_pdk(declared, project=str(project),
                               container=container)
    except Exception:
        return None
    if not res.get("available"):
        return None
    src = res.get("source")
    if src not in ("project_custom_pdk", "container_installed"):
        return None
    # a KNOWN open family installed in the container keeps the open-PDK fast
    # path (sky130 tt_mm regression preserved) — only a NATIVE custom / unknown
    # installed family takes the resolved-mc_libs path.
    matched = (res.get("matched_dir") or "").lower()
    if src == "container_installed" and any(
            k in matched for k in ("sky130", "gf180")):
        return None
    mc_libs = res.get("mc_libs") or []
    if not mc_libs:
        return {"unscoreable": (
            f"L19 target {declared!r} resolves to a native custom PDK "
            f"(source={src}) but stages NO Monte-Carlo / mismatch model lib "
            f"(resolved mc_libs is empty). Refusing to overlay an open-PDK "
            f"(sky130) mismatch section on a native deck — MC yield is honestly "
            f"UNSCOREABLE until the family's statistical/mismatch lib is staged "
            f"under input/pdk/. (degeneracy-guard family; NDA: paths only.)")}
    mc_lib = mc_libs[0]
    return {"mc_lib": mc_lib, "mc_section": _pick_native_mc_section(mc_lib),
            "family": res.get("family"), "source": src}


def _assert_single_model_family(wrap_text: str, mc_include_line: str) -> None:
    """Structural guard (#150): after the wrapper prepends its single native
    model include and strips any caller-side include from the deck body, EXACTLY
    ONE include-form model line may remain — the one we prepended. A second
    (e.g. a leftover open-PDK sky130 overlay) is a forbidden cross-family hybrid;
    raise so the bug can never ship silently."""
    lines = _INCLUDE_FORM_MODEL_RE.findall(wrap_text)
    assert len(lines) == 1, (
        f"cross-family MC deck: expected exactly 1 model include "
        f"({mc_include_line!r}), found {len(lines)}: {lines}")
    low = wrap_text.lower()
    assert "/foss/pdks/sky130" not in low and "/foss/pdks/gf180" not in low, (
        "native MC deck must not overlay an open-PDK (sky130/gf180) model lib")


def run_block(project: Path, block: str, container: str, pdk: str,
              n: int) -> dict:
    """Entry point. A path the container cannot be shown to see is a structured
    SKIP naming what IS mounted — never a traceback, never a guessed path."""
    try:
        return _run_block(project, block, container, pdk, n)
    except _dr.MountRootUnresolved as exc:
        st = exc.status
        return {"verdict": st["verdict"], "rc": 2, "mc_runs": 0,
                "error_code": st["error_code"],
                "needs_user_decision": st["needs_user_decision"],
                "reason": st["reason"], "options": st["options"]}


def _run_block(project: Path, block: str, container: str, pdk: str,
               n: int) -> dict:
    deck, deck_rank = _find_deck(project, block)
    if deck is None:
        # ORGANIC #142 — distinguish "no deck at all" from "only a bare
        # `.subckt` library (no analysis card)". The latter must NOT be run N
        # times to score 0 every iteration — it is honestly UNSCOREABLE: MC
        # yield cannot be computed until a runnable deck (TB harness with a
        # `.control`/`.meas` analysis) exists for the block.
        any_sp = any(
            (project / ph / "analog" / block).is_dir()
            and any((project / ph / "analog" / block).rglob("*.sp"))
            for ph in ("phase2", "phase3"))
        if any_sp:
            return {"verdict": "UNSCOREABLE", "rc": 2,
                    "reason": (f"block {block!r} has only bare .subckt "
                               f"libraries (no top-level analysis card / TB "
                               f"harness) — MC yield is not scoreable until a "
                               f"runnable deck (e.g. sizing_loop/*.sp with a "
                               f".control/.meas analysis) exists. Not running "
                               f"{n} empty iterations.")}
        return {"verdict": "SKIP", "rc": 2,
                "reason": f"no .sp deck found for block {block!r}"}
    specs, spec_src = _load_specs(project, block)
    if not specs:
        return {"verdict": "SKIP", "rc": 2,
                "reason": (f"no numeric spec limits (min/max) for block "
                           f"{block!r} — nothing to score yield against")}

    # ORGANIC #150 — native custom-PDK resolution BEFORE the open-PDK path. A
    # native family that stages no mc/mismatch lib is honestly UNSCOREABLE (a
    # structural verdict — no ngspice probe needed), never a cross-family
    # overlay.
    native = _resolve_native_mc(project, container)
    if native and native.get("unscoreable"):
        return {"verdict": "UNSCOREABLE", "rc": 2,
                "reason": native["unscoreable"], "mc_runs": 0}

    if not _ars._ngspice_available(container):
        return {"verdict": "SKIP", "rc": 2,
                "reason": f"ngspice not available in container {container!r}"}

    # The HOST MOUNT ROOT for docker path mapping — MEASURED from the
    # container's own mount table via the designs-root ladder, never guessed
    # from a directory NAME found in the path (that test is False on every
    # machine whose design tree is called something else, and the fall-through
    # emitted container paths the container cannot see).
    host_root = _dr.resolve_host_root(project, container)

    if native:
        # native mismatch lib → the wrapper's SINGLE model source.
        mc_lib_ct = _ars._container_path(container, host_root,
                                         Path(native["mc_lib"]))
        mc_section = native["mc_section"]
        mc_include_line = (f".lib {mc_lib_ct} {mc_section}" if mc_section
                           else f".include {mc_lib_ct}")
        mc_model_section = mc_section or f"(whole lib {Path(native['mc_lib']).name})"
    else:
        mc_section = _MC_SECTION.get(pdk)
        if not mc_section:
            return {"verdict": "SKIP", "rc": 2,
                    "reason": f"no statistical model section known for pdk {pdk!r}"}
        pdk_lib = _ars.PDK_LIB.get(pdk)
        if not pdk_lib:
            return {"verdict": "SKIP", "rc": 2,
                    "reason": f"no ngspice model lib known for pdk {pdk!r}"}
        mc_include_line = f".lib {pdk_lib} {mc_section}"
        mc_model_section = mc_section

    mc_dir = deck.parent / "mc_runs"
    mc_dir.mkdir(parents=True, exist_ok=True)
    deck_body = deck.read_text(errors="replace")
    if native:
        # strip ANY caller-side include-form model line (native corner OR a stray
        # open lib) so the wrapper owns the SINGLE native model source — no
        # cross-family mixing (the _assert_single_model_family guard below is the
        # structural backstop).
        deck_body = _INCLUDE_FORM_MODEL_RE.sub(
            "* (.lib moved to MC wrapper)", deck_body)
    else:
        # open-PDK path unchanged — strip only the open model lib by name.
        deck_body = re.sub(
            rf"^\s*\.lib\s+\S*{re.escape(Path(pdk_lib).name)}\s+\S+\s*$",
            "* (.lib moved to MC wrapper)", deck_body,
            flags=re.MULTILINE | re.IGNORECASE)

    per_run = []
    for i in range(1, n + 1):
        wrap = mc_dir / f"mc_{i:04d}.sp"
        wrap_text = (
            f"* MC iteration {i}/{n} — {self_name()} (foundry statistical "
            f"section '{mc_model_section}')\n"
            f".option seed={i}\n"
            f"{mc_include_line}\n"
            + deck_body + ("\n.end\n" if ".end" not in deck_body.lower()
                           else "\n"))
        if native:
            _assert_single_model_family(wrap_text, mc_include_line)
        wrap.write_text(wrap_text)
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
    degenerate_specs = []
    for name, lim in specs.items():
        # #464 — a nulled metric is present-as-None; it is NOT a scored value
        # (skip it rather than crash the min/max comparison or count it).
        scored = [r for r in per_run
                  if r.get("ok") and r.get(name) is not None]
        if not scored:
            spec_yield[name] = {"runs_scored": 0, "yield_pct": None}
            continue
        # ORGANIC #142 — degeneracy guard. A yield off N IDENTICAL samples is
        # meaningless (the corner section did not resample device mismatch). If
        # fewer than _MIN_DISTINCT_MC_VALUES distinct measured values were seen,
        # the spec is UNSCOREABLE — never a fabricated 100%/0%.
        distinct = len({round(float(r[name]), 12) for r in scored})
        if distinct < _MIN_DISTINCT_MC_VALUES:
            spec_yield[name] = {
                "runs_scored": len(scored), "distinct_values": distinct,
                "yield_pct": None, "degenerate": True}
            degenerate_specs.append(name)
            continue
        passed = sum(
            1 for r in scored
            if (lim.get("min") is None or r[name] >= lim["min"])
            and (lim.get("max") is None or r[name] <= lim["max"]))
        spec_yield[name] = {
            "runs_scored": len(scored), "distinct_values": distinct,
            "passed": passed,
            "yield_pct": round(100.0 * passed / len(scored), 2)}
    scoreable = [v["yield_pct"] for v in spec_yield.values()
                 if v.get("yield_pct") is not None]
    if not scoreable:
        # ORGANIC #142 — distinguish "MC produced NO statistical spread"
        # (degenerate — the mismatch corner section was not selected / mismatch
        # not resampled) from "no scoreable measure at all". The degenerate case
        # is an honest UNSCOREABLE with a fix hint, NOT a fabricated yield.
        if degenerate_specs:
            return {"verdict": "UNSCOREABLE", "rc": 2,
                    "reason": (
                        f"MC produced NO statistical spread for "
                        f"{degenerate_specs} (sigma≈0 / <"
                        f"{_MIN_DISTINCT_MC_VALUES} distinct values). The "
                        f"variation was not resampled — either the wrong CORNER "
                        f"SECTION (a typical section hardcodes mc_mm_switch=0, "
                        f"e.g. sky130 'tt' vs 'tt_mm') OR the wrong DEVICE "
                        f"VARIANT (a deterministic device subckt overlaid with "
                        f"an MC switch silently wins → sigma 0). Select the "
                        f"PDK's statistical/mismatch section AND its MC device "
                        f"variant; refusing to report a fabricated 100%/0% "
                        f"yield. (family-agnostic backstop.)"),
                    "mc_runs": n, "spec_yield": spec_yield}
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
        "mc_model_section": mc_model_section,
        "mc_pdk_source": (native.get("source") if native else pdk),
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
    ap.add_argument("--container", default="vibeic-eda")
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
