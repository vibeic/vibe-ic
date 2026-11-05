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
IMPLEMENTATION_SETTINGS = {"RUN_POST_GRT_RESIZER_TIMING", "RUN_POST_GRT_DESIGN_REPAIR",
                           "FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT"}


def implementation_setting(key: str) -> bool:
    return key in IMPLEMENTATION_SETTINGS or key.startswith(("CTS_", "PDN_", "GRT_DESIGN_REPAIR_"))


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
    result: dict[str, Any] = {"PDN_SKIPTRIM": True, "PDN_CORE_RING": True,
                              "PDN_CORE_RING_CONNECT_TO_PADS": True}
    for field, keys in {
        "layers": ("PDN_CORE_VERTICAL_LAYER", "PDN_CORE_HORIZONTAL_LAYER"),
        "widths": ("PDN_CORE_RING_VWIDTH", "PDN_CORE_RING_HWIDTH"),
        "spacings": ("PDN_CORE_RING_VSPACING", "PDN_CORE_RING_HSPACING"),
    }.items():
        result.update(zip(keys, ring.get(field, [])))
    if ring.get("core_offset_um") is not None:
        result.update(PDN_CORE_RING_VOFFSET=ring["core_offset_um"],
                      PDN_CORE_RING_HOFFSET=ring["core_offset_um"])
        for axis, width in zip(("V", "H"), ring.get("widths", [])):
            result[f"PDN_{axis}OFFSET"] = ring["core_offset_um"] + width / 2
    script = project / "work/flow/pdn_cfg.tcl"
    script.parent.mkdir(parents=True, exist_ok=True)
    lines = ["source $::env(SCRIPTS_DIR)/openroad/common/pdn_cfg.tcl"]
    for layers in ring.get("connects", []):
        lines.append("add_pdn_connect -grid stdcell_grid -layers {" + " ".join(layers) + "}")
    script.write_text("\n".join(lines) + "\n")
    result["PDN_CFG"] = str(script)
    return result


def _input_docs(project: Path) -> dict[str, str]:
    paths = [project / "input/phase1_prompt.md"]
    paths += sorted((project / "input/docs").rglob("*"))
    return {str(path.relative_to(project)): path.read_text(errors="replace")
            for path in paths if path.is_file()
            and path.suffix.lower() in {".md", ".rst", ".txt", ".markdown"}}


def _resolve_rtl_inputs(project: Path, sources: dict) -> tuple[list[Path], str]:
    from _rtl_include_hub import silicon_rtl_selection
    from _design_module_set import module_names_in_text

    rtl_root = project / "phase2/stage1/rtl"
    rtl = silicon_rtl_selection(rtl_root)
    canonical_modules = set().union(*(module_names_in_text(path.read_text(errors="replace"))
                                     for path in rtl))
    for directory in sorted(path for path in rtl_root.rglob("*") if path.is_dir()):
        for path in silicon_rtl_selection(directory):
            names = module_names_in_text(path.read_text(errors="replace"))
            # The producer's flat sources win over nested copies. A mixed file
            # stays for the native compiler to diagnose without losing modules.
            if len(names) == 1 and names <= canonical_modules:
                continue
            rtl.append(path)
    if not rtl:
        raise FileNotFoundError("No produced RTL in phase2/stage1/rtl")
    docs = project / "phase1/generated_docs"
    l9 = _load(docs / "L9_INTEGRATION_SPEC.json")
    l1 = _load(docs / "L1_DATASHEET.json")
    top = l9.get("top_module") or l1.get("tapeout_metadata", {}).get("top_cell")
    modules = set().union(*(module_names_in_text(path.read_text(errors="replace"))
                            for path in rtl))
    if top not in modules:
        from phase1_doc_one_shot_runner import _extract_top_module_from_docs

        for source, text in _input_docs(project).items():
            declared = _extract_top_module_from_docs({source: text})
            if declared in modules:
                top = declared
                sources["DESIGN_NAME"] = source
                break
    if not top or top not in modules:
        raise FileNotFoundError(f"Declared top module {top} is absent from produced RTL")
    return rtl, top


def resolve_rtl_inputs(project: Path | str) -> tuple[list[Path], str]:
    """Pure source and declared-top selection shared by native tool callers."""
    return _resolve_rtl_inputs(Path(project).resolve(), {})


def build_config(project: Path | str, *, route: str | None = None, pdk: str | None = None) -> dict[str, Any]:
    """Read L documents and produced RTL; route is supplied by the Router caller."""
    project = Path(project).resolve()
    docs = project / "phase1/generated_docs"
    l8 = _load(docs / "L8_TIMING_WAVEFORM.json")
    l19 = _load(docs / "L19_CONSTRAINTS_PDK.json")
    fields = l19.get("fields", {})
    pdk = pdk or fields.get("pdk_target") or l19.get("pdk_target")
    rtl_root = project / "phase2/stage1/rtl"
    inputs = _input_docs(project)
    sources: dict[str, Any] = {}
    rtl, top = _resolve_rtl_inputs(project, sources)
    assumptions = []
    if not pdk:
        from parametric_spec_extractor import extract_pdk_target

        for source, text in inputs.items():
            target = extract_pdk_target(text)
            if target:
                pdk = target["pdk"]
                sources["PDK"] = source
                break
    if not pdk:
        raise FileNotFoundError("Top module and PDK must be declared in design documents")
    registered = [row["name"] for row in _load(PROGRAMS / "pdk_registry.json").get("pdks", [])]
    pdk = next((name for name in registered if name.casefold() == str(pdk).strip().casefold()), str(pdk).strip())
    config: dict[str, Any] = {"DESIGN_NAME": top, "PDK": pdk,
                              "VERILOG_FILES": [str(path) for path in rtl]}
    config["VERILOG_INCLUDE_DIRS"] = sorted({str(path.parent) for path in
                                           rtl_root.rglob("*") if path.is_file()})
    if any(re.search(r"\bpackage\s+\w+|\bimport\s+\w+::", path.read_text())
           for path in rtl if path.suffix == ".sv"):
        config["USE_SLANG"] = True
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
    if not clocks:
        from phase1_doc_one_shot_runner import _v638_comportable_interface_harvest

        for source, text in inputs.items():
            for row in _v638_comportable_interface_harvest(text):
                if (row.get("extraction_strategy") == "comportable_clock_bullet_v638"
                        and re.search(r"Primary\s+Clock", row["source_row"], re.I)):
                    clocks.append({"source_pin": row["name"]})
                    sources["CLOCK_PORT"] = source
    if clocks:
        ports = [clock.get("source_pin") or clock.get("name") for clock in clocks]
        config["CLOCK_PORT"] = ports[0] if len(ports) == 1 else ports
        period = fields.get("clock_target", {}).get("period_ns") or clocks[0].get("period_ns")
        if period is None and clocks[0].get("freq_mhz"):
            period = 1000 / clocks[0]["freq_mhz"]
        if period is not None:
            config["CLOCK_PERIOD"] = period
    if "CLOCK_PERIOD" not in config:
        assumptions.append("CLOCK_PERIOD is undeclared; use LibreLane's native default. "
                           "It is an implementation assumption, not a design timing target.")
    if "CLOCK_PORT" not in config:
        assumptions.append("CLOCK_PORT is undeclared; timing is NOT_MEASURED.")
    if route in {"ic", "DIE"}:
        config.update(_chip_pdn(project, pdk))
    implementation = _load(project / "plugin_output/declaration.json")
    config.update({key: value for key, value in implementation.items()
                   if implementation_setting(key)})
    config.update(_settings(fields, pdk))
    sdc = project / "phase3/stage3/pnr/constraint.sdc"
    if sdc.is_file():
        config.update(PNR_SDC_FILE=str(sdc), SIGNOFF_SDC_FILE=str(sdc))
    notes = project / "work/flow/config_sources.json"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(json.dumps({"sources": sources, "assumptions": assumptions}, indent=2) + "\n")
    return config


def build_native_config(project: Path | str, *, route: str | None = None, pdk: str | None = None,
                        on_tool_run=None) -> dict[str, Any]:
    config = build_config(project, route=route, **({"pdk": pdk} if pdk else {}))
    if route in {"ic", "DIE"}:
        from flow_chip_inputs import prepare
        config = prepare(Path(project).resolve(), config,
                         **({"on_tool_run": on_tool_run} if on_tool_run is not None else {}))
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
    parser.add_argument("--set", action="append", default=[], metavar="KEY=JSON",
                        help="Record an implementation setting in the existing declaration.")
    parser.add_argument("--unset", action="append", default=[], metavar="KEY",
                        help="Remove an implementation setting from the existing declaration.")
    args = parser.parse_args()
    previous = None
    if args.set or args.unset:
        declaration = args.project.resolve() / "plugin_output/declaration.json"
        previous = declaration.read_bytes() if declaration.exists() else None
        choices = _load(declaration)
        for key in args.unset:
            if not implementation_setting(key):
                parser.error(f"Unsupported implementation setting: {key}")
            choices.pop(key, None)
        for item in args.set:
            key, separator, raw = item.partition("=")
            if not separator or not implementation_setting(key):
                parser.error(f"Unsupported implementation setting: {item}")
            try:
                choices[key] = json.loads(raw)
            except json.JSONDecodeError as exc:
                parser.error(f"Invalid JSON for {key}: {exc}")
        declaration.parent.mkdir(parents=True, exist_ok=True)
        declaration.write_text(json.dumps(choices, indent=2) + "\n")
    try:
        output = write_config(args.project, route=args.route, output=args.output)
    except Exception:
        if args.set or args.unset:
            if previous is None:
                declaration.unlink()
            else:
                declaration.write_bytes(previous)
        raise
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
