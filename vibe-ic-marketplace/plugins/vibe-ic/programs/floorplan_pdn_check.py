#!/usr/bin/env python3
"""
floorplan_pdn_check.py — Step 15 (Floorplan + PDN) SUBSTANCE gate.

Anti-fabrication hardening
--------------------------
The flow gate for Step 15 historically passed the moment
``phase3/stage3/pnr/floorplan.def`` *existed* — zero verification of its
CONTENT. An empty / truncated / zero-area floorplan, or one with no power
grid, would sail through and only blow up at routing / IR-drop signoff.

This program parses the REAL OpenROAD floorplan artefacts and verifies
substance:

  1. DIEAREA — ``floorplan.def`` must declare a non-degenerate die:
       ``DIEAREA ( x1 y1 ) ( x2 y2 ) ;`` with x2 > x1, y2 > y1 (positive
       area). A missing / zero-area DIEAREA is a structural FAIL.
  2. CORE / ROWs — at least one ``ROW`` site array must exist (the
       placeable core region). A floorplan with no rows has nowhere to
       place standard cells → FAIL.
  3. COMPONENTS — at least one instance must be declared in the
       COMPONENTS section (the design has cells to place). Zero is a FAIL.
       (A pre-placement floorplan legitimately leaves most instances
       UNPLACED — that is NOT checked here; placement state is Step 17's
       job. We only require that instances EXIST.)
  4. Core utilization — verified ONLY when an OpenROAD log provides a
       *measured* utilization (IFP-0104 "Effective utilization" or
       GPL-0019 "Utilization: NN %"). When present it must lie in
       (0, 100] % — a universal structural sanity bound (you cannot place
       more cell area than the core holds, and 0 % means nothing was
       placed). We do NOT fabricate a utilization from the DEF alone:
       cell areas require the LEF, which the floorplan DEF does not carry,
       so when no log value is available we fall back to the COMPONENTS
       count > 0 check (rule 3) and record that utilization was not
       independently derivable.
  5. PDN straps — power/ground grid evidence MUST be present in one of:
       (a) ``pnr.tcl`` containing ``add_pdn_stripe`` / ``add_pdn_ring`` /
           ``pdngen`` / ``define_pdn_grid``, OR
       (b) a DEF (floorplan or any later stage in pnr/) carrying a
           ``SPECIALNETS`` section with a power/ground net
           (VDD/VSS/VPWR/VGND/vccd*/vssd* …).
       A bare ``pdn.done`` marker with NO strap evidence anywhere does
       NOT satisfy this — "no PG straps" is a real FAIL.

Verdicts
--------
* PASS  (rc=0) — DIEAREA non-degenerate + >=1 ROW + >=1 COMPONENT +
                 utilization (if measured) in (0,100]% + PDN strap
                 evidence present.
* FAIL  (rc=1) — required floorplan.def absent / empty / unparseable,
                 degenerate DIEAREA, no ROWs, zero COMPONENTS, absurd
                 utilization (<=0 or >100 %), or no PG strap evidence.
                 The step blocks_on synth+LEC, so an absent floorplan at
                 this gate is a real failure, never a vacuous pass.
* WAIVED (rc=0) — waivers.json declares the step waived (ticket + reason).
* SKIP  (rc=2) — project dir not found (operational, not a chip failure).

chip-AGNOSTIC. No vendor / IC / tool-specific number is hard-coded; the
only bounds applied are universal structural facts (positive die area,
utilization in (0,100]%, >=1 row, >=1 instance). Utilization is read from
the artefact, never invented.

Usage
-----
    python3 floorplan_pdn_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import _path_layout as _pl

import sys as _sys                                             # noqa: E402
from pathlib import Path as _Path                              # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _declared_die as _dd                                    # noqa: E402


_GATE_NAME = "floorplan_pdn_check"
_GATE_LABEL = "floorplan_pdn"

# Power / ground net-name tokens used to recognise a PG SPECIALNET. These
# are the universal industry / sky130 / generic-PDK conventions, not a
# chip-specific literal: VDD/VSS (generic), VPWR/VGND + VPB/VNB (sky130
# std-cell), vccd*/vssd* (Caravel user/power domains). Matched case-
# insensitively as whole tokens.
_PG_NET_TOKENS = (
    "vdd", "vss", "vpwr", "vgnd", "vccd", "vssd", "vdda", "vssa",
    "vccpst", "vsspst", "vpb", "vnb", "power", "ground",
)

# pnr.tcl PDN command tokens (OpenROAD pdngen flow).
_PDN_TCL_TOKENS = (
    "add_pdn_stripe", "add_pdn_ring", "pdngen", "define_pdn_grid",
    "add_pdn_connect",
)

# OpenROAD log utilization patterns. Values are *measured* and parsed
# verbatim — never fabricated.
#   IFP-0104  Effective utilization:   0.181        (fraction → ×100)
#   GPL-0019  Utilization:             20.499 %     (already percent)
_RE_IFP_UTIL = re.compile(
    r"Effective utilization:\s*([0-9]*\.?[0-9]+)", re.IGNORECASE)
_RE_GPL_UTIL = re.compile(
    r"Utilization:\s*([0-9]*\.?[0-9]+)\s*%", re.IGNORECASE)

_RE_UNITS = re.compile(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)")
_RE_DIEAREA = re.compile(
    r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)")


# ---------------------------------------------------------------------------
# waiver plumbing (mirrors wafer_sort_yield_check.py)
# ---------------------------------------------------------------------------
def _load_waivers(project: Path):
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text()).get("waived_steps") or []
    except Exception:  # noqa: BLE001
        return []


def _step_waived(project: Path, step_label: str):
    for w in _load_waivers(project):
        sid = str(w.get("id", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or step_label in ticket:
            return w
    return None


# ---------------------------------------------------------------------------
# DEF parsing
# ---------------------------------------------------------------------------
def _parse_floorplan_def(path: Path):
    """Return dict with diearea/rows/components/has_specialnets_pg parsed
    from a floorplan DEF. Raises ValueError on absent/empty/unparseable."""
    try:
        text = path.read_text(errors="replace")
    except OSError as e:
        raise ValueError(f"cannot read {path.name}: {e}") from e
    if not text.strip():
        raise ValueError(f"{path.name} is empty")

    out = {
        "diearea": None,         # (x1, y1, x2, y2) in DEF units
        "die_area_units": None,  # x*y
        "n_rows": 0,
        "n_components": None,    # from COMPONENTS <n> ; header
        "n_component_lines": 0,  # counted "- inst cell" lines
        "has_specialnets_pg": False,
        # The DEF's own grid. Needed to compare its rectangle against the
        # run's declared die, which is in microns. None means the DEF did not
        # state one — reported as None, never defaulted here.
        "units_per_um": None,
    }

    in_components = False
    in_specialnets = False
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue

        if out["units_per_um"] is None:
            mu = _RE_UNITS.search(s)
            if mu:
                try:
                    out["units_per_um"] = int(mu.group(1)) or None
                except ValueError:                        # pragma: no cover
                    out["units_per_um"] = None

        if out["diearea"] is None:
            m = _RE_DIEAREA.search(s)
            if m:
                x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
                out["diearea"] = (x1, y1, x2, y2)
                out["die_area_units"] = (x2 - x1) * (y2 - y1)

        if s.startswith("ROW "):
            out["n_rows"] += 1
            continue

        if s.startswith("COMPONENTS"):
            mm = re.match(r"COMPONENTS\s+(\d+)\s*;", s)
            if mm:
                out["n_components"] = int(mm.group(1))
            in_components = True
            continue
        if s.startswith("END COMPONENTS"):
            in_components = False
            continue
        if in_components and s.startswith("-"):
            out["n_component_lines"] += 1
            continue

        if s.startswith("SPECIALNETS"):
            in_specialnets = True
            continue
        if s.startswith("END SPECIALNETS"):
            in_specialnets = False
            continue
        if in_specialnets and s.startswith("-"):
            # "- VDD ( ... )" → first token after the dash is the net name.
            parts = s.split()
            if len(parts) >= 2:
                net = parts[1].strip().lower()
                if any(tok in net for tok in _PG_NET_TOKENS):
                    out["has_specialnets_pg"] = True

    return out


def _any_def_has_pg_specialnets(pnr: Path):
    """Scan every *.def under pnr/ for a SPECIALNETS section with a PG net.
    Returns (found: bool, def_name|None)."""
    for defp in sorted(pnr.glob("*.def")):
        try:
            text = defp.read_text(errors="replace")
        except OSError:
            continue
        in_sn = False
        for raw in text.splitlines():
            s = raw.strip()
            if s.startswith("SPECIALNETS"):
                in_sn = True
                continue
            if s.startswith("END SPECIALNETS"):
                in_sn = False
                continue
            if in_sn and s.startswith("-"):
                parts = s.split()
                if len(parts) >= 2:
                    net = parts[1].strip().lower()
                    if any(tok in net for tok in _PG_NET_TOKENS):
                        return True, defp.name
    return False, None


def _pdn_tcl_evidence(pnr: Path):
    """Scan pnr.tcl (and any *.tcl) for PDN strap/ring commands.
    Returns (found: bool, tcl_name|None, matched_tokens: list)."""
    candidates = []
    pdn_tcl = pnr / "pdn.tcl"
    if pdn_tcl.is_file():
        candidates.append(pdn_tcl)
    pnr_tcl = pnr / "pnr.tcl"
    if pnr_tcl.is_file():
        candidates.append(pnr_tcl)
    # Fall back to any remaining tcl in the dir.
    for t in sorted(pnr.glob("*.tcl")):
        if t not in candidates:
            candidates.append(t)
    for tcl in candidates:
        try:
            text = tcl.read_text(errors="replace").lower()
        except OSError:
            continue
        matched = [tok for tok in _PDN_TCL_TOKENS if tok in text]
        if matched:
            return True, tcl.name, matched
    return False, None, []


def _measured_utilization(pnr: Path):
    """Return (util_pct: float|None, source: str|None) parsed from an
    OpenROAD log under pnr/. Prefers GPL-0019 (explicit percent), falls
    back to IFP-0104 (fraction). Never fabricates."""
    gpl_val = ifp_val = None
    gpl_src = ifp_src = None
    for log in sorted(pnr.glob("*.log")):
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            mg = _RE_GPL_UTIL.search(line)
            if mg and gpl_val is None:
                try:
                    gpl_val = float(mg.group(1))
                    gpl_src = f"{log.name}: '{line.strip()}'"
                except ValueError:
                    pass
            mi = _RE_IFP_UTIL.search(line)
            if mi and ifp_val is None:
                try:
                    # IFP value is a fraction (0.181) → percent.
                    ifp_val = float(mi.group(1)) * 100.0
                    ifp_src = f"{log.name}: '{line.strip()}'"
                except ValueError:
                    pass
    if gpl_val is not None:
        return gpl_val, gpl_src
    if ifp_val is not None:
        return ifp_val, ifp_src
    return None, None


# ---------------------------------------------------------------------------
def _emit(args, project, verdict, findings, extra):
    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": _GATE_LABEL,
        "findings": findings,
    }
    out.update(extra)
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    for f in findings:
        if f["severity"] in ("FAIL", "WAIVED"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}",
              file=sys.stderr)
        return 2

    pnr = _pl.pnr_dir(project)
    floorplan = pnr / "floorplan.def"
    findings = []
    extra = {
        "floorplan_def": str(floorplan.relative_to(project))
        if floorplan.exists() else None,
        "die_area_units": None,
        "n_rows": None,
        "n_components": None,
        "utilization_pct": None,
        "utilization_source": None,
        "pdn_evidence": None,
    }

    waiver = _step_waived(project, _GATE_LABEL)

    # ---- Waiver path ----------------------------------------------------
    if waiver and not floorplan.is_file():
        findings.append({
            "severity": "WAIVED", "rule": "STEP_WAIVED",
            "message": f"waiver={waiver.get('ticket', '?')}: "
                       f"{waiver.get('reason', '?')}",
        })
        extra["waiver"] = waiver
        _emit(args, project, "WAIVED", findings, extra)
        return 0

    # ---- Honest FAIL on absent required artefact ------------------------
    if not floorplan.is_file():
        findings.append({
            "severity": "FAIL", "rule": "FLOORPLAN_DEF_MISSING",
            "message": "phase3/stage3/pnr/floorplan.def not found — "
                       "Step 15 (synth+LEC complete) must emit a floorplan; "
                       "absent floorplan is a real failure, not a pass",
        })
        _emit(args, project, "FAIL", findings, extra)
        return 1

    # ---- Parse the floorplan DEF ---------------------------------------
    try:
        fp = _parse_floorplan_def(floorplan)
    except ValueError as e:
        findings.append({
            "severity": "FAIL", "rule": "FLOORPLAN_DEF_UNPARSEABLE",
            "message": str(e),
        })
        _emit(args, project, "FAIL", findings, extra)
        return 1

    # The ONE derivation of the die, asked once for this report.
    _da = fp["diearea"]
    _u = fp.get("units_per_um")
    # NO DEFAULT GRID. Without `UNITS DISTANCE MICRONS` the DEF's integers are
    # not convertible to microns, so the DEF rectangle is simply not offered as
    # a fallback rather than offered at a guessed scale.
    _die = _dd.resolve(
        project,
        def_rect_um=([_da[0] / _u, _da[1] / _u, _da[2] / _u, _da[3] / _u]
                     if _da and _u else None))
    extra["die_area_units"] = fp["die_area_units"]
    extra["n_rows"] = fp["n_rows"]
    extra["n_components"] = (
        fp["n_components"] if fp["n_components"] is not None
        else fp["n_component_lines"])

    fail = False

    # Rule 1 — DIEAREA non-degenerate.
    if fp["diearea"] is None:
        findings.append({
            "severity": "FAIL", "rule": "NO_DIEAREA",
            "message": "floorplan.def declares no DIEAREA — no die outline",
        })
        fail = True
    elif fp["die_area_units"] is None or fp["die_area_units"] <= 0:
        x1, y1, x2, y2 = fp["diearea"]
        findings.append({
            "severity": "FAIL", "rule": "DEGENERATE_DIEAREA",
            "message": f"DIEAREA ({x1} {y1}) ({x2} {y2}) has non-positive "
                       f"area {fp['die_area_units']} — degenerate floorplan",
        })
        fail = True
    else:
        x1, y1, x2, y2 = fp["diearea"]
        # RULE 1 IS ABOUT THE DEF RECORD, and stays about it: a floorplan that
        # declares no outline, or a degenerate one, is a structural defect
        # whatever the die is. What is DISCLOSED here is that the record and
        # the die need not be the same rectangle (vibe-ic#2058 FP-15): on a
        # SLOT run `DIEAREA` states the placeable CORE. Naming both stops this
        # INFO line from being quoted as the die size, which is what it read
        # as when it was the only rectangle in the report.
        extra["die_source"] = _die.source
        extra["die_basis"] = _die.basis
        extra["die_rect_um"] = list(_die.rect) if _die.rect else None
        _also = ""
        if _die.is_declared and _die.rect is not None:
            _also = (f"; the run declares the DIE as "
                     f"{_die.width_um():g} x {_die.height_um():g} um "
                     f"({_die.basis})")
        findings.append({
            "severity": "INFO", "rule": "DIEAREA_OK",
            "message": f"DIEAREA ({x1} {y1}) ({x2} {y2}) "
                       f"= {fp['die_area_units']} DEF-units^2 — this is the "
                       f"DEF's own record, which on a slot run states the "
                       f"placeable core{_also}",
        })

    # Rule 2 — at least one ROW (placeable core region).
    if fp["n_rows"] <= 0:
        findings.append({
            "severity": "FAIL", "rule": "NO_CORE_ROWS",
            "message": "floorplan.def has no ROW lines — empty core region, "
                       "nowhere to place standard cells",
        })
        fail = True
    else:
        findings.append({
            "severity": "INFO", "rule": "CORE_ROWS_OK",
            "message": f"{fp['n_rows']} ROW site array(s) present",
        })

    # Rule 3 — at least one COMPONENT instance.
    n_inst = (fp["n_components"] if fp["n_components"] is not None
              else fp["n_component_lines"])
    if not n_inst or n_inst <= 0:
        findings.append({
            "severity": "FAIL", "rule": "NO_COMPONENTS",
            "message": "floorplan.def has zero COMPONENTS — no design "
                       "instances to place",
        })
        fail = True
    else:
        findings.append({
            "severity": "INFO", "rule": "COMPONENTS_OK",
            "message": f"{n_inst} COMPONENT instance(s) declared",
        })

    # Rule 4 — utilization, ONLY when measured by the tool (never invented).
    util, util_src = _measured_utilization(pnr)
    extra["utilization_pct"] = round(util, 4) if util is not None else None
    extra["utilization_source"] = util_src
    if util is not None:
        if util <= 0 or util > 100.0:
            findings.append({
                "severity": "FAIL", "rule": "ABSURD_UTILIZATION",
                "message": f"measured core utilization {util:.3f}% is outside "
                           f"the structural bound (0, 100]% — {util_src}",
            })
            fail = True
        else:
            findings.append({
                "severity": "INFO", "rule": "UTILIZATION_OK",
                "message": f"measured core utilization {util:.3f}% in "
                           f"(0,100]% — {util_src}",
            })
    else:
        findings.append({
            "severity": "INFO", "rule": "UTILIZATION_NOT_DERIVABLE",
            "message": "no measured utilization in any pnr log (cell areas "
                       "need the LEF, which the floorplan DEF lacks); fell "
                       "back to COMPONENTS>0 (rule 3) — utilization NOT "
                       "fabricated",
        })

    # Rule 5 — PDN strap/ring evidence.
    tcl_found, tcl_name, tcl_tokens = _pdn_tcl_evidence(pnr)
    sn_found, sn_def = (False, None)
    if not tcl_found:
        sn_found, sn_def = _any_def_has_pg_specialnets(pnr)
    if tcl_found:
        extra["pdn_evidence"] = f"{tcl_name}: {tcl_tokens}"
        findings.append({
            "severity": "INFO", "rule": "PDN_STRAPS_OK",
            "message": f"PDN grid commands in {tcl_name}: {tcl_tokens}",
        })
    elif sn_found:
        extra["pdn_evidence"] = f"{sn_def}: SPECIALNETS PG net"
        findings.append({
            "severity": "INFO", "rule": "PDN_STRAPS_OK",
            "message": f"power/ground SPECIALNETS present in {sn_def}",
        })
    else:
        findings.append({
            "severity": "FAIL", "rule": "NO_PDN_STRAPS",
            "message": "no PDN evidence: pnr.tcl/pdn.tcl carry no "
                       "add_pdn_stripe/add_pdn_ring/pdngen, and no DEF "
                       "carries a power/ground SPECIALNETS section. A bare "
                       "pdn.done marker is not strap evidence.",
        })
        fail = True

    verdict = "FAIL" if fail else "PASS"
    _emit(args, project, verdict, findings, extra)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
