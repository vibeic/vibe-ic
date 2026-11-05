#!/usr/bin/env python3
"""Translate generated design documents into native LibreLane configuration."""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
from pathlib import Path
from typing import Any


PROGRAMS = Path(__file__).resolve().parent
SETTING_ALIASES = {
    "SYNTH_MAX_FANOUT": "MAX_FANOUT_CONSTRAINT",
    "PL_TARGET_DENSITY": "PL_TARGET_DENSITY_PCT",
    "FP_PDN_VOFFSET": "PDN_VOFFSET",
    "FP_PDN_HOFFSET": "PDN_HOFFSET",
    "FP_PDN_SKIPTRIM": "PDN_SKIPTRIM",
}
SETTINGS = {
    "MAX_FANOUT_CONSTRAINT", "MAX_TRANSITION_CONSTRAINT",
    "MAX_CAPACITANCE_CONSTRAINT", "FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT",
    "PDN_VOFFSET", "PDN_HOFFSET", "PDN_SKIPTRIM", "PDN_CORE_RING",
    "PDN_CORE_RING_CONNECT_TO_PADS", "PDN_VWIDTH", "PDN_HWIDTH",
    "PDN_VPITCH", "PDN_HPITCH", "PDN_VSPACING", "PDN_HSPACING",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text()) if path.is_file() else {}


def _value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if re.match(r"^true(?:\b|\()", text, re.I):
        return True
    if re.match(r"^false(?:\b|\()", text, re.I):
        return False
    try:
        number = float(text.rstrip("%"))
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _settings(fields: dict, pdk: str) -> dict:
    chosen: dict[str, tuple[int, Any]] = {}
    for row in fields.get("constraint_declarations", []):
        token = row.get("token")
        key = SETTING_ALIASES.get(token, token)
        if row.get("kind") != "flow_setting" or key not in SETTINGS:
            continue
        scope = row.get("scope")
        if scope and not (fnmatch.fnmatch(pdk.lower(), str(scope).lower())
                          or pdk.lower().startswith(str(scope).lower().rstrip("*_"))):
            continue
        value = _value(row.get("value"))
        if value is None:
            continue
        if token == "PL_TARGET_DENSITY":
            value *= 100
        priority = int(bool(scope))
        if key in chosen and chosen[key][0] == priority and chosen[key][1] != value:
            raise ValueError(f"Conflicting L19 declarations for {key}")
        if key not in chosen or priority >= chosen[key][0]:
            chosen[key] = priority, value
    return {key: value for key, (_, value) in chosen.items()}


def _chip_pdn(project: Path, pdk: str) -> dict:
    registry = _load(PROGRAMS / "pdk_registry.json")
    ring = next((row.get("pdn_ring", {}) for row in registry.get("pdks", [])
                 if row.get("name") == pdk), {})
    result: dict[str, Any] = {
        "PDN_VOFFSET": 7, "PDN_HOFFSET": 7, "PDN_SKIPTRIM": True,
    }
    if ring:
        result.update(PDN_CORE_RING=True,
                      PDN_CORE_RING_CONNECT_TO_PADS=bool(ring.get("connect_to_pad_layers")))
    for field, keys in {
        "layers": ("PDN_CORE_VERTICAL_LAYER", "PDN_CORE_HORIZONTAL_LAYER"),
        "widths": ("PDN_CORE_RING_VWIDTH", "PDN_CORE_RING_HWIDTH"),
        "spacings": ("PDN_CORE_RING_VSPACING", "PDN_CORE_RING_HSPACING"),
    }.items():
        result.update(zip(keys, ring.get(field, [])))
    if ring.get("core_offset_um") is not None:
        result.update(PDN_CORE_RING_VOFFSET=ring["core_offset_um"],
                      PDN_CORE_RING_HOFFSET=ring["core_offset_um"])
    script = project / "work/flow/pdn_cfg.tcl"
    script.parent.mkdir(parents=True, exist_ok=True)
    lines = ["source $::env(SCRIPTS_DIR)/openroad/common/pdn_cfg.tcl"]
    for layers in ring.get("connects", []):
        lines.append("add_pdn_connect -grid stdcell_grid -layers {" + " ".join(layers) + "}")
    script.write_text("\n".join(lines) + "\n")
    result["PDN_CFG"] = str(script)
    return result


def build_config(project: Path | str, *, route: str | None = None) -> dict[str, Any]:
    """Read L documents and produced RTL; route is supplied by the Router caller."""
    project = Path(project).resolve()
    docs = project / "phase1/generated_docs"
    l1 = _load(docs / "L1_DATASHEET.json")
    l8 = _load(docs / "L8_TIMING_WAVEFORM.json")
    l9 = _load(docs / "L9_INTEGRATION_SPEC.json")
    l19 = _load(docs / "L19_CONSTRAINTS_PDK.json")
    fields = l19.get("fields", {})
    top = l9.get("top_module") or l1.get("tapeout_metadata", {}).get("top_cell")
    pdk = fields.get("pdk_target") or l19.get("pdk_target")
    if not top or not pdk:
        raise FileNotFoundError("L9 top_module and L19 pdk_target are required")
    from _chip_synth_read import chip_rtl_files

    rtl = chip_rtl_files(project / "phase2/stage1/rtl")
    if not rtl:
        raise FileNotFoundError("No produced RTL in phase2/stage1/rtl")
    config: dict[str, Any] = {"DESIGN_NAME": top, "PDK": pdk,
                              "VERILOG_FILES": [str(path) for path in rtl]}
    for field, key in {"die_area_um": "DIE_AREA", "core_area_um": "CORE_AREA"}.items():
        if fields.get(field) is not None:
            config[key] = fields[field]
    if "DIE_AREA" in config:
        config["FP_SIZING"] = "absolute"
    clocks = [clock for clock in l8.get("clock_domains", [])
              if (clock.get("domain_kind") == "primary"
                  or clock.get("role") in {"primary", "master"})
              and clock.get("pdk_scoped_target") in {None, pdk}]
    if not clocks:
        clocks = _load(docs / "L8_RTL_CONSTANTS.json").get("clock_domains", [])
    if clocks:
        ports = [clock.get("source_pin") or clock.get("name") for clock in clocks]
        config["CLOCK_PORT"] = ports[0] if len(ports) == 1 else ports
        period = fields.get("clock_target", {}).get("period_ns") or clocks[0].get("period_ns")
        if period is None and clocks[0].get("freq_mhz"):
            period = 1000 / clocks[0]["freq_mhz"]
        if period is not None:
            config["CLOCK_PERIOD"] = period
    if route in {"ic", "DIE"}:
        config.update(_chip_pdn(project, pdk))
    config.update(_settings(fields, pdk))
    sdc = project / "phase3/stage3/pnr/constraint.sdc"
    if sdc.is_file():
        config.update(PNR_SDC_FILE=str(sdc), SIGNOFF_SDC_FILE=str(sdc))
    if "MAX_FANOUT_CONSTRAINT" in config:
        config["CTS_SINK_CLUSTERING_SIZE"] = config["MAX_FANOUT_CONSTRAINT"]
    return config


def write_config(project: Path | str, *, route: str | None = None,
                 output: Path | None = None) -> Path:
    project = Path(project).resolve()
    output = output or project / "work/flow/config.json"
    config = build_config(project, route=route)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(config, indent=2) + "\n")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--route", choices=("ic", "ip", "DIE", "HARDMACRO"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(write_config(args.project, route=args.route, output=args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
