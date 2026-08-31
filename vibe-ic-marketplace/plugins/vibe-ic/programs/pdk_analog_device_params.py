#!/usr/bin/env python3
"""pdk_analog_device_params.py — the target PDK's ELECTRICAL device constants,
read out of `programs/pdk_registry.json` for whatever family is asked for.

WHAT WAS BROKEN
===============
`analog_device_params` carried three hand-typed numbers per family — two
threshold voltages and a supply — and nothing else. Everything a sizing pass
actually solves with is a transconductance parameter, a sheet resistance or a
capacitance density, so every analog-sizing invocation on every PDK re-derived
those by hand, in the session, from ad-hoc ngspice decks that were thrown away
with the session (vibe-ic#1962). The same four measurements were repeated per
design, per PDK, with no provenance and no way to tell a measured number from a
remembered one.

WHAT THIS MODULE IS
===================
One generic reader over the MEASURED half of that registry field. Given a PDK
selector it returns the family's measured record — a flat `{param: value}` map
per process corner, plus the provenance stating which device each number was
measured on, at which bias, from which model lib and section, with which
simulator. `programs/pdk_analog_characterize.py` PRODUCES that record; nothing
else may write it, and no consumer may retype a number this reader can answer.

The DECLARED half (`vth_n_v` / `vth_p_v` / `nominal_supply_v` / `note`) is
returned separately and is left exactly as it was, so every existing consumer
of that field is byte-identical whether a family has been characterized or
not.

chip-AGNOSTIC: no PDK family, foundry, vendor or device name appears below.
Everything family-specific is DATA in `pdk_registry.json` (or in a
project-local record for a PDK that may not be published at all), and it
behaves
identically for a family it has never seen.

WHERE A RECORD MAY LIVE, AND WHY THERE ARE TWO PLACES
=====================================================
  * `programs/pdk_registry.json` — for a family the plugin SHIPS. Only an
    `open_source` family may be published here; measuring a PDK is reading it,
    and a proprietary process's constants are not the plugin's to distribute.
  * `<project>/analog/_pdk_char/analog_device_params.json` — for a PDK STAGED
    INTO A PROJECT, which is the shape vibe-ic#1962 was reported on. The record
    stays inside the design that is entitled to it. A project-local record for
    the SAME family WINS over the shipped one: the staged PDK is the one the
    design's decks load, so it is the one whose constants describe them.

RECORD SHAPE (under a PDK entry's `analog_device_params`)
=========================================================
    "measured": {
      "_schema": 1,
      "_generated_by": "programs/pdk_analog_characterize.py",
      "_method": "<how each family of numbers was extracted>",
      "nominal_corner": "typ",
      "simulator": {"tool": ..., "version": ..., "container_image": ...},
      "conditions": {<the testbench conditions every corner shares>},
      "corners": {
        "typ": {
          "sections":  [[<model lib path>, <section>], ...],
          "devices":   {<role>: <the primitive the number describes>},
          "temp_c":    27,
          "supply_v":  1.8,
          "bias":      {<mos role>: {"vgs_v": [...], "basis": ..., ...}},
          "deck_idiom":{<role>: {"geometry_units": ..., "terminals": ...}},
          "params":    {<param name incl. its unit>: <number>},
          "fit":       {<the residual saying how well the model fits>},
          "not_measured": {<param or role>: <why, in the simulator's words>}
        }
      }
    }

`params` is deliberately PARTIAL. A key appears only when it was measured on
this family; an ABSENT key means NOT MEASURED — never "this process has no such
constant" and never a default. `not_measured` says which and why, so a consumer
can tell a gap from a silence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pdk_analog_layout_minima as _minima

_REGISTRY = Path(__file__).resolve().parent / "pdk_registry.json"

PARAMS_KEY = "analog_device_params"
MEASURED_KEY = "measured"
RECORD_SCHEMA = 1

# Where a project-staged PDK's own record is written and read. Relative to the
# project root; the same path the characterizer writes when handed a project.
PROJECT_RECORD = "analog/_pdk_char/analog_device_params.json"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# ── family resolution ─────────────────────────────────────────────────────
# Deliberately NOT a second matcher. `pdk_analog_layout_minima.resolve_family`
# is the one the analog producers already share; the electrical constants and
# the layout minima are two records of the SAME registry entry, and resolving
# them through two copies of the ladder is how one of them silently ends up
# read off a different family than the other.
resolve_family = _minima.resolve_family


def _project_record(project: Optional[Path]) -> Dict[str, Any]:
    """The project-staged record, or {} when the project stages none."""
    if project is None:
        return {}
    return _read_json(Path(project) / PROJECT_RECORD)


def declared_params(selector: str, path: Optional[Path] = None
                    ) -> Tuple[Optional[str], Dict[str, Any]]:
    """`(family, the DECLARED constants)` — the field exactly as it was before
    anything was measured, with the measured sub-record removed.

    Consumers that quoted `vth_n_v` / `nominal_supply_v` keep quoting exactly
    what they quoted; characterizing a family must not move a number a reader
    was already relying on."""
    fam, ent = resolve_family(selector, path)
    params = ent.get(PARAMS_KEY)
    if not isinstance(params, dict):
        return fam, {}
    return fam, {k: v for k, v in params.items() if k != MEASURED_KEY}


def measured_record(selector: str, path: Optional[Path] = None,
                    project: Optional[Path] = None
                    ) -> Tuple[Optional[str], Dict[str, Any]]:
    """`(family, the whole measured record)`, or `(family, {})` when this
    family has not been characterized.

    A project-staged record for the same family WINS: the staged PDK is the one
    the design's decks load."""
    fam, ent = resolve_family(selector, path)
    local = _project_record(project)
    if local:
        lf = str(local.get("family") or "")
        rec = local.get(MEASURED_KEY)
        if isinstance(rec, dict) and (not fam or not lf or lf == fam):
            return (fam or lf or None), rec
    params = ent.get(PARAMS_KEY)
    if not isinstance(params, dict):
        return fam, {}
    rec = params.get(MEASURED_KEY)
    return fam, (rec if isinstance(rec, dict) else {})


def nominal_corner(record: Dict[str, Any]) -> Optional[str]:
    """The corner a consumer that asks for no corner in particular gets."""
    c = record.get("nominal_corner")
    return str(c) if isinstance(c, str) and c else None


def corner_record(record: Dict[str, Any], corner: Optional[str] = None
                  ) -> Tuple[Optional[str], Dict[str, Any]]:
    """`(corner_name, that corner's record)`. `corner=None` asks for the
    nominal one. An unknown corner returns `(None, {})` — never the nominal
    one under the asked-for name, which would answer a question about the slow
    corner with the typical corner's numbers."""
    corners = record.get("corners")
    if not isinstance(corners, dict) or not corners:
        return None, {}
    want = corner or nominal_corner(record)
    if want is None:
        return None, {}
    rec = corners.get(want)
    return (want, rec) if isinstance(rec, dict) else (None, {})


def measured_values(selector: str, corner: Optional[str] = None,
                    path: Optional[Path] = None,
                    project: Optional[Path] = None) -> Dict[str, float]:
    """The flat `{param: number}` map for one corner — the form a consumer
    seeds into an expression environment.

    `{}` is the honest answer for a family that has not been characterized. A
    consumer must record that it evaluated with NO measured constants, not
    assume the process had none."""
    _fam, rec = measured_record(selector, path, project)
    _name, cr = corner_record(rec, corner)
    params = cr.get("params")
    if not isinstance(params, dict):
        return {}
    return {str(k): float(v) for k, v in params.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def measured_provenance(selector: str, corner: Optional[str] = None,
                        path: Optional[Path] = None,
                        project: Optional[Path] = None) -> Dict[str, Any]:
    """What a reader needs to audit those numbers without re-deriving them:
    which corner, which model lib sections, which primitive per role, the bias
    and temperature they were taken at, how well the extracted model fits, what
    could NOT be measured and why, and which simulator said so.

    `{"measured": False}` for a family with no record — an artefact must be
    able to state that it quoted nothing, distinguishably from quoting zero."""
    fam, rec = measured_record(selector, path, project)
    name, cr = corner_record(rec, corner)
    if not cr:
        return {"measured": False, "family": fam,
                "reason": ("no measured `analog_device_params.measured` "
                           "record resolves for this family"
                           if not rec else
                           f"this family carries no `{corner}` corner")}
    return {
        "measured": True,
        "family": fam,
        "corner": name,
        "schema": rec.get("_schema"),
        "generated_by": rec.get("_generated_by"),
        "method": rec.get("_method"),
        "sections": cr.get("sections") or [],
        "devices": cr.get("devices") or {},
        "temp_c": cr.get("temp_c"),
        "supply_v": cr.get("supply_v"),
        "bias": cr.get("bias") or {},
        "deck_idiom": cr.get("deck_idiom") or {},
        "fit": cr.get("fit") or {},
        "not_measured": cr.get("not_measured") or {},
        "simulator": rec.get("simulator") or {},
        "conditions": rec.get("conditions") or {},
    }


def available_corners(selector: str, path: Optional[Path] = None,
                      project: Optional[Path] = None) -> list:
    """The corner names this family was characterized at, in record order."""
    _fam, rec = measured_record(selector, path, project)
    corners = rec.get("corners")
    return list(corners) if isinstance(corners, dict) else []


def main(argv: Optional[list] = None) -> int:
    """Read-only CLI. Prints one family's measured record as JSON."""
    import argparse
    ap = argparse.ArgumentParser(
        description="Read the measured analog device constants for a PDK.")
    ap.add_argument("--pdk", required=True)
    ap.add_argument("--corner", default=None)
    ap.add_argument("--project", default=None)
    ap.add_argument("--registry", default=None)
    a = ap.parse_args(argv)
    reg = Path(a.registry) if a.registry else None
    proj = Path(a.project) if a.project else None
    fam, rec = measured_record(a.pdk, reg, proj)
    out = {
        "family": fam,
        "declared": declared_params(a.pdk, reg)[1],
        "corners": available_corners(a.pdk, reg, proj),
        "values": measured_values(a.pdk, a.corner, reg, proj),
        "provenance": measured_provenance(a.pdk, a.corner, reg, proj),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if rec else 2


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
