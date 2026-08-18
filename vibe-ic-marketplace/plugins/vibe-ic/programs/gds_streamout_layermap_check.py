#!/usr/bin/env python3
"""
gds_streamout_layermap_check.py — Deterministic sign-off streamout layer
conformance checker.

A GDS streamed from DEF is only sign-off-usable if every shape landed on the
GDS layer number the foundry actually assigns to that purpose. When the LEF/DEF
reader runs without a streamout layer map it invents its own compact numbering,
so routing, vias and PDN end up on layer numbers the foundry deck reads as
completely different purposes. The deck then reports violations of rules the
design never broke, and — because the geometry really is on the wrong layers —
the GDS cannot be fabricated either. The failure is silent: the streamout tool
merely notes the fallback and writes the file.

This check makes that state detectable from the ARTIFACT alone. Every
layer/datatype pair carrying shapes in the streamed GDS must be accounted for
by one of the authoritative sources:

  * the streamout layer map's own targets (the foundry's assignment),
  * the PDK standard-cell library GDS (the numbers the foundry itself draws
    the cells on),
  * layers the PDK bridge sign-off config explicitly declares (dummy fill,
    tap geometry, same-net heal, port-label / rail markers, std-cell marker).

Anything left over is an ORPHAN — a layer the flow wrote that no authority
recognises. Orphans are the fingerprint of an absent or partial map.

What it catches:
  1. NO_LAYERMAP        — sign-off streamout ran with no layer map at all
  2. ORPHAN_LAYER       — GDS layers no authority accounts for
  3. EMPTY_MAPPED_LAYER — a routed metal/via layer the map defines but that
                          received nothing (geometry went somewhere else)
  4. UNREADABLE_GDS     — the GDS is missing or not parseable

Usage:
    python3 gds_streamout_layermap_check.py --gds design.gds \\
        [--layermap streamout.map] [--lib-gds stdcells.gds] \\
        [--signoff-config bridge/signoff_config.json] [--json out.json]

Exit codes:
    0 = every populated layer is accounted for
    1 = orphan / missing-map findings
    2 = parse error / invalid arguments

Generality: no vendor, PDK or design literal. Layer numbers come from the
inputs; the GDS is parsed with a minimal record scanner so the check needs no
layout tool.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

LayerKey = Tuple[int, int]

# GDSII record types carrying a layer or a purpose number.
_REC_LAYER = 0x0D
_REC_DATATYPE = 0x0E
_REC_TEXTTYPE = 0x16
_REC_BOXTYPE = 0x2E
# DATATYPE and BOXTYPE follow shapes; TEXTTYPE follows a label. Only the first
# two carry geometry a DRC deck can measure, and only geometry can sit on the
# wrong layer in the sense this check is about. Labels are tracked separately so
# a per-metal label datatype is never mistaken for un-mapped geometry.
_GEOMETRY_RECS = (_REC_DATATYPE, _REC_BOXTYPE)
_PURPOSE_RECS = _GEOMETRY_RECS + (_REC_TEXTTYPE,)


@dataclass
class Finding:
    severity: str       # ERROR, WARNING, INFO
    category: str       # NO_LAYERMAP, ORPHAN_LAYER, EMPTY_MAPPED_LAYER
    message: str
    details: str = ""


@dataclass
class Stats:
    gds_layers: List[str] = field(default_factory=list)
    map_targets: List[str] = field(default_factory=list)
    lib_layers: List[str] = field(default_factory=list)
    macro_layers: List[str] = field(default_factory=list)
    declared_layers: List[str] = field(default_factory=list)
    orphans: List[str] = field(default_factory=list)
    layermap_applied: bool = False


def _fmt(k: LayerKey) -> str:
    return f"{k[0]}/{k[1]}"


# ---------------------------------------------------------------------------
# GDSII layer scan (minimal record walk — no layout tool needed)
# ---------------------------------------------------------------------------
def scan_gds_layers(path: Path,
                    include_text: bool = False) -> Set[LayerKey]:
    """Return every (layer, datatype) pair that carries at least one shape.

    Walks GDSII records and pairs each LAYER record with the purpose record
    that follows it inside the same element, which is how the format orders
    them. Unpaired LAYER records are ignored rather than guessed at. Text
    labels are excluded unless asked for — they carry no geometry."""
    found: Set[LayerKey] = set()
    pending: Optional[int] = None
    wanted = _PURPOSE_RECS if include_text else _GEOMETRY_RECS
    with path.open("rb") as fh:
        while True:
            head = fh.read(4)
            if len(head) < 4:
                break
            length, rtype = struct.unpack(">HBB", head)[0], head[2]
            if length < 4:
                break
            body = fh.read(length - 4)
            if len(body) < length - 4:
                break
            if rtype == _REC_LAYER and len(body) >= 2:
                pending = struct.unpack(">h", body[:2])[0]
            elif rtype in _PURPOSE_RECS and len(body) >= 2:
                if pending is not None:
                    if rtype in wanted:
                        found.add((pending, struct.unpack(">h", body[:2])[0]))
                    pending = None
    return found


# ---------------------------------------------------------------------------
# Authority sources
# ---------------------------------------------------------------------------
def parse_layermap_targets(path: Path) -> Set[LayerKey]:
    """Target layers of a streamout map — data lines shaped
    `<name> <purpose> <layer> <datatype>`. Other lines are ignored, so the
    same parser tolerates comments and vendor headers."""
    out: Set[LayerKey] = set()
    for line in path.read_text(errors="ignore").splitlines():
        s = line.strip()
        if not s or s[0] in "#/*;":
            continue
        toks = s.split()
        if (len(toks) >= 4 and toks[2].lstrip("-").isdigit()
                and toks[3].lstrip("-").isdigit()):
            out.add((int(toks[2]), int(toks[3])))
    return out


def declared_layers(cfg: Dict[str, Any]) -> Set[LayerKey]:
    """Every `L/D` string a PDK bridge sign-off config declares, wherever it
    sits in the structure. Walking the config rather than naming its keys
    keeps the check correct as new layer-bearing features are added."""
    out: Set[LayerKey] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)
        elif isinstance(node, str):
            for part in node.split(","):
                bits = part.strip().split("/")
                if (len(bits) == 2 and bits[0].isdigit()
                        and bits[1].isdigit()):
                    out.add((int(bits[0]), int(bits[1])))

    visit(cfg)
    return out


# ---------------------------------------------------------------------------
# Core audit
# ---------------------------------------------------------------------------
def audit(gds: Path, layermap: Optional[Path], lib_gds: Optional[Path],
          signoff_config: Optional[Path],
          require_layermap: bool = True,
          macro_gds: Optional[List[Path]] = None) -> Tuple[List[Finding], Stats]:
    findings: List[Finding] = []
    stats = Stats()

    if not gds.is_file():
        findings.append(Finding("ERROR", "UNREADABLE_GDS",
                                f"GDS not found: {gds}"))
        return findings, stats
    try:
        gds_layers = scan_gds_layers(gds)
    except (OSError, struct.error) as exc:
        findings.append(Finding("ERROR", "UNREADABLE_GDS",
                                f"cannot scan {gds.name}: {exc}"))
        return findings, stats

    map_targets: Set[LayerKey] = set()
    if layermap and layermap.is_file():
        map_targets = parse_layermap_targets(layermap)
        stats.layermap_applied = bool(map_targets)
    elif require_layermap:
        findings.append(Finding(
            "ERROR", "NO_LAYERMAP",
            "sign-off streamout ran without a LEF/DEF->GDS layer map",
            "DEF-sourced geometry keeps the reader's own numbering, which "
            "does not correspond to the foundry's layer assignment."))

    lib_layers: Set[LayerKey] = set()
    if lib_gds and lib_gds.is_file():
        try:
            lib_layers = scan_gds_layers(lib_gds)
        except (OSError, struct.error):
            lib_layers = set()

    # Hard-macro / IP GDS layers are legitimate library geometry too:
    # the design's own vendor macro GDS is MERGED into the streamed
    # GDS, so its layers are drawn-on-purpose, not orphans. Without
    # this, any design integrating a hard-macro GDS whose layers are
    # absent from the std-cell library GDS gets a FALSE ORPHAN_LAYER.
    # chip-AGNOSTIC: the paths come from the design's own macro GDS.
    macro_layers: Set[LayerKey] = set()
    for _mg in (macro_gds or []):
        _mgp = Path(_mg)
        if _mgp.is_file():
            try:
                macro_layers |= scan_gds_layers(_mgp)
            except Exception as _mexc:   # noqa: BLE001 — best-effort:
                # a macro-scan failure must NEVER skip the whole
                # conformance check; surface it (WARN, never swallow)
                # so a macro-contributed layer that then shows as an
                # orphan below is explained rather than mysterious.
                findings.append(Finding(
                    "WARNING", "MACRO_GDS_UNSCANNED",
                    f"could not scan macro GDS {_mgp.name}: {_mexc}",
                    "its layers were NOT added to the allowed set"))

    cfg_layers: Set[LayerKey] = set()
    if signoff_config and signoff_config.is_file():
        try:
            cfg_layers = declared_layers(
                json.loads(signoff_config.read_text(errors="ignore")))
        except (OSError, ValueError):
            cfg_layers = set()

    allowed = map_targets | lib_layers | macro_layers | cfg_layers
    orphans = sorted(gds_layers - allowed) if allowed else []

    stats.gds_layers = [_fmt(k) for k in sorted(gds_layers)]
    stats.map_targets = [_fmt(k) for k in sorted(map_targets)]
    stats.lib_layers = [_fmt(k) for k in sorted(lib_layers)]
    stats.macro_layers = [_fmt(k) for k in sorted(macro_layers)]
    stats.declared_layers = [_fmt(k) for k in sorted(cfg_layers)]
    stats.orphans = [_fmt(k) for k in orphans]

    if orphans:
        findings.append(Finding(
            "ERROR", "ORPHAN_LAYER",
            f"{len(orphans)} GDS layer(s) match no streamout-map target, "
            f"library-GDS layer, hard-macro-GDS layer or declared "
            f"sign-off layer",
            "orphans: " + ", ".join(_fmt(k) for k in orphans)))

    # A map target that names a routing purpose but received nothing is the
    # other half of the same fault: the geometry exists, it just went to a
    # layer the foundry does not read.
    if map_targets and gds_layers:
        drawn_layers = {k[0] for k in gds_layers}
        empty_targets = sorted(
            k for k in map_targets
            if k[0] not in drawn_layers and k[0] in {j[0] for j in lib_layers})
        if empty_targets:
            findings.append(Finding(
                "WARNING", "EMPTY_MAPPED_LAYER",
                f"{len(empty_targets)} mapped layer(s) the library draws on "
                f"received no geometry",
                "empty: " + ", ".join(_fmt(k) for k in empty_targets)))

    return findings, stats


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gds", required=True, type=Path)
    ap.add_argument("--layermap", type=Path)
    ap.add_argument("--lib-gds", type=Path)
    ap.add_argument("--macro-gds", type=Path, nargs="*", default=[],
                    help="hard-macro / IP GDS file(s) whose layers are "
                         "legitimate merged library geometry")
    ap.add_argument("--signoff-config", type=Path)
    ap.add_argument("--allow-missing-layermap", action="store_true",
                    help="do not flag an absent map (non-sign-off streamout)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    try:
        findings, stats = audit(args.gds, args.layermap, args.lib_gds,
                                args.signoff_config,
                                require_layermap=not args.allow_missing_layermap,
                                macro_gds=args.macro_gds)
    except Exception as exc:                       # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    errors = [f for f in findings if f.severity == "ERROR"]
    payload = {
        "gds": str(args.gds),
        "verdict": "FAIL" if errors else "PASS",
        "findings": [asdict(f) for f in findings],
        "stats": asdict(stats),
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2))

    print(f"streamout layermap conformance: {payload['verdict']}")
    print(f"  populated GDS layers : {len(stats.gds_layers)}")
    print(f"  map targets          : {len(stats.map_targets)}")
    print(f"  library GDS layers   : {len(stats.lib_layers)}")
    print(f"  macro GDS layers     : {len(stats.macro_layers)}")
    print(f"  declared layers      : {len(stats.declared_layers)}")
    for f in findings:
        print(f"  [{f.severity}] {f.category}: {f.message}")
        if f.details:
            print(f"      {f.details}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
