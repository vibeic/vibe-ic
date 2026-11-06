#!/usr/bin/env python3
"""Translate generated design documents into native LibreLane configuration."""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
from decimal import Decimal
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
    "SYNTH_STRATEGY",
    "MAX_FANOUT_CONSTRAINT", "MAX_TRANSITION_CONSTRAINT",
    "MAX_CAPACITANCE_CONSTRAINT", "FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT",
    "PDN_VOFFSET", "PDN_HOFFSET", "PDN_SKIPTRIM", "PDN_CORE_RING",
    "PDN_CORE_RING_CONNECT_TO_PADS", "PDN_VWIDTH", "PDN_HWIDTH",
    "PDN_VPITCH", "PDN_HPITCH", "PDN_VSPACING", "PDN_HSPACING",
}
IMPLEMENTATION_SETTINGS = {"RUN_POST_GRT_RESIZER_TIMING", "RUN_POST_GRT_DESIGN_REPAIR",
                           "CLOCK_PORT", "FP_DEF_TEMPLATE", "FALLBACK_SDC", "PNR_SDC_FILE", "SIGNOFF_SDC_FILE",
                           "SYNTH_STRATEGY", "EXTRA_EXCLUDED_CELLS", "DECAP_CELLS", "FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT"}


def implementation_setting(key: str) -> bool:
    return key in IMPLEMENTATION_SETTINGS or key.startswith(("CTS_", "PDN_", "GRT_DESIGN_REPAIR_"))


def native_excluded_cells(config):
    excluded = [*(config.get("EXTRA_EXCLUDED_CELLS") or []), "*dly*", "*delay*"]
    if str(config.get("PDK", "")).lower().startswith("gf180mcu"):
        # OpenROAD-flow-scripts flow/platforms/gf180/config.mk sets DONT_USE_CELLS = *_1.
        excluded.append("*_1")
    return list(dict.fromkeys(excluded))


def native_defaults(config):
    """Apply platform defaults, then the project's explicit native overrides."""
    from flow_clock_geometry import cts_settings

    changes = {"EXTRA_EXCLUDED_CELLS": native_excluded_cells(config)}
    caps = [value for value in (config.get("MAX_CAPACITANCE_CONSTRAINT"),
                               config.get("CTS_MAX_CAP") or None) if value is not None]
    slews = [value for value in (config.get("MAX_TRANSITION_CONSTRAINT"),
                                config.get("CTS_MAX_SLEW") or None) if value is not None]
    # Zero requests native auto; CTS resets both axes when either is unspecified.
    if caps and slews:
        changes.update(CTS_MAX_CAP=min(caps), CTS_MAX_SLEW=min(slews))
    changes.update(cts_settings(config))
    if config.get("DESIGN_DIR"):
        changes.update(_load(Path(config["DESIGN_DIR"]) / "work/flow/native_overrides.json"))
    return config.copy(**changes)


def explore_synthesis(config, state, directory, on_tool_run=None):
    """Choose from LibreLane's own exploration results at the configured timing."""
    import os
    import time
    from librelane.flows import Flow

    directory = Path(directory).resolve()
    explorer = Flow.factory.get("SynthesisExploration")(config)
    started, code = time.monotonic(), 1
    directory.mkdir(parents=True, exist_ok=True)
    cwd = Path.cwd()
    try:
        os.chdir(directory)
        explorer.start(with_initial_state=state, _force_run_dir=str(directory))
        code = 0
    finally:
        os.chdir(cwd)
        if on_tool_run is not None:
            on_tool_run({"name": "LibreLane.SynthesisExploration", "ran": True,
                "exit_code": code, "status": "FAIL" if code else "PASS",
                "tool_seconds": time.monotonic() - started, "reports": str(directory)})
    results = {step.id.removeprefix("sta-"): step.state_out.metrics
               for step in explorer.step_objects
               if step.id.startswith("sta-") and step.state_out is not None}
    eligible = [strategy for strategy, metrics in results.items()
                if metrics["timing__setup__ws"] >= 0]
    chosen = min(eligible, key=lambda strategy: results[strategy]["design__instance__area"],
                 default=None)
    (directory / "selection.json").write_text(json.dumps({
        "strategy": chosen, "clock_period_ns": config["CLOCK_PERIOD"],
        "results": {strategy: {key: metrics[key] for key in (
            "design__instance__area", "timing__setup__ws", "timing__setup__tns")}
            for strategy, metrics in results.items()},
        "detail": "Minimum area meeting setup timing." if chosen else
                  "No timing-feasible strategy; the configured strategy remains for native evaluation."
    }, indent=2, default=str) + "\n")
    return chosen


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
        value = row.get("value")
        value = (str(value).strip() if value is not None else None) if key == "SYNTH_STRATEGY" else _value(value)
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


def declared_fanout_checks(project: Path, *, config: dict | None = None, metrics: dict | None = None) -> list[dict]:
    """Require zero native fanout violations only for a document-declared bound."""
    path = Path(project) / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    fields = _load(path).get("fields", {})
    pdk = (config or {}).get("PDK") or fields.get("pdk_target") or ""
    declared = _settings(fields, pdk).get("MAX_FANOUT_CONSTRAINT")
    if declared is None:
        return []
    return [{"metric": "design__max_fanout_violation__count*", "operator": "==", "limit": 0,
             "unit": "count", "declared_max_fanout": declared,
             "source": {"file": str(path.relative_to(project)), "field": "fields.constraint_declarations"}}]


def declared_power_checks(project: Path, *, config: dict | None = None, metrics: dict | None = None) -> list[dict]:
    config, metrics = config or {}, metrics or {}
    number = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    pattern = re.compile(rf"(<=|>=|<|>|≤|≥|under\b|below\b|at\s+most\b|at\s+least\b)?\s*({number})\s*([mµμu]?W)\b", re.I)
    scales, inputs = {"W": 0, "mW": -3, "uW": -6, "µW": -6, "μW": -6}, []
    for path in sorted((project / "phase1/generated_docs").glob("L*.json")):
        text = path.read_text(); document = json.loads(text, parse_float=Decimal)
        for prefix, holder in (("", document), ("fields.", document.get("fields", {}))):
            for key, unit in (("power_budget_uw", "uW"), ("power_budget_mw", "mW"), ("total_power_mw", "mW")):
                raw = holder.get(key); spec = raw if isinstance(raw, dict) else {"max": raw}
                metadata = {**document, **holder, **holder.get("clock_target", {}), **spec}
                if raw is None or (key == "total_power_mw" and not isinstance(raw, dict)) or metadata.get("informational") or any(metadata.get(k) is False for k in ("signoff", "signoff_gate", "gating")) or metadata.get("rail"):
                    continue
                if re.search(r"\b(?:core|rail|domain|block)\b", str(metadata.get("scope", "")), re.I) and not re.search(r"\bincluding\b", str(metadata.get("scope", "")), re.I):
                    continue
                statement = " ".join(f"{('>' if side == 'min' else '<') + ('' if spec.get(side + '_exclusive') else '=')} {spec[side]} {spec.get('unit', unit)}" for side in ("min", "max") if isinstance(spec.get(side), (int, float, Decimal)) and not isinstance(spec[side], bool))
                statement = raw if isinstance(raw, str) else statement
                context = " ".join(f"{value} ns" if field in {"period_ns", "clock_period_ns", "CLOCK_PERIOD"} else f"{field}={value}" for field, value in metadata.items() if not isinstance(value, (dict, list)))
                hits = list(re.finditer(rf'"{key}"\s*:', text)); line = text.count("\n", 0, hits[0].start()) + 1 if len(hits) == 1 else None
                inputs.append(({"file": str(path.relative_to(project)), "field": prefix + key, "line": line, "bound": raw, "unit": spec.get("unit", unit)}, statement, context))
    inputs = [entry for entry in inputs if pattern.search(entry[1])]
    if not inputs:
        for file, text in _input_docs(project).items():
            context = ""
            for line_number, line in enumerate(text.splitlines(), 1):
                if re.match(r"^##\s", line):
                    context = ""
                if line.lstrip().startswith(("#", ">")):
                    context += "\n" + line
                if not re.search(r"\btotal[ _-]+power\b", line, re.I) or (re.search(r"\b(?:core|rail|domain|block)\b", line, re.I) and not re.search(r"\bincluding\b", line, re.I)) or re.search(r"informational|not.*gate|❌|資訊|(?:core|rail)[ -](?:only|total)|per[- ]rail|power\s*\(\s*(?:core|rail)\b|\|\s*(?:no|false|否)\s*\|", line, re.I):
                    continue
                inputs.append(({"file": file, "line": line_number, "text": line}, line, context + "\n" + line))
    checks, pdks = [], "|".join(re.escape(row["name"]) for row in _load(PROGRAMS / "pdk_registry.json").get("pdks", []))
    actual_corners = list(config.get("STA_CORNERS") or []) + [key.split("__corner:")[-1] for key in metrics if key.startswith("power__total__corner:")]
    for source, text, context in inputs:
        values = []
        for match in (item for item in pattern.finditer(text.replace("*", "")) if item[3] in scales):
            value = Decimal(match[2]); sign, digits, exponent = value.as_tuple()
            values.append((" ".join((match[1] or "").lower().split()), Decimal((sign, digits, exponent + scales[match[3]])), match[3]))
        if not values:
            continue
        limits = {("min" if op in {">", ">=", "≥", "at least"} else "max"): value for op, value, _ in values if op}
        limits.update({("min" if op == ">" else "max") + "_exclusive": True for op, _, _ in values if op in {"<", ">", "under", "below"}})
        source = {**source, "bound": source.get("bound", [match[0] for match in pattern.finditer(text.replace("*", ""))]), "unit": source.get("unit", [unit for _, _, unit in values])}
        mismatches = []
        for key, condition in (("PDK", rf"(?:PDK|pdk_target)\s*=\s*([\w.-]+)|\b({pdks})\b"), ("STD_CELL_LIBRARY", r"(?:STD_CELL_LIBRARY|scl)\s*=\s*([\w.-]+)|\b(\w+_fd_sc_\w+)\b"), ("CLOCK_PERIOD", rf"({number})\s*ns\b")):
            stated = {item.casefold() for groups in re.findall(condition, context, re.I) for item in (groups if isinstance(groups, tuple) else (groups,)) if item}
            actual = str(config.get(key, "")).casefold()
            if stated and (actual not in stated if key != "CLOCK_PERIOD" else any(Decimal(value) != Decimal(actual or 'NaN') for value in stated)):
                mismatches.append(key)
        corners = set(re.findall(r"\b(tt|ff|ss)\b", context, re.I))
        if corners and not all(any(re.search(rf"(?:^|_){corner}(?:_|$)", actual, re.I) for actual in actual_corners) for corner in corners):
            mismatches.append("corner")
        metric = "power__total__corner:" + ("*" + next(iter(corners)).lower() + "*" if len(corners) == 1 else "*")
        check = {"metric": metric, "operator": "within_declared_bounds", "limit": limits, "unit": "W", "source": source, "scope": "Native estimated total current netlist power including die pads and native activity assumptions."}
        if mismatches or not limits:
            check.update(applicable=False, reason="Run conditions differ or are unknown: " + ", ".join(mismatches) if mismatches else "Source number has no comparator; it is not a limit.", value=[value for _, value, _ in values])
        checks.append(check)
    return checks


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
    top = (_load(project / "plugin_output/declaration.json").get("top_module")
           or l9.get("top_module") or l1.get("tapeout_metadata", {}).get("top_cell"))
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


def _pdk_name(value: str) -> str:
    from pdk_family_identity import canonical_family
    value = str(value).strip()
    family = canonical_family(value)
    return family if family and family.casefold().startswith(value.casefold()) else value


def declared_clocks(project: Path, pdk: str) -> list[dict]:
    docs = project / "phase1/generated_docs"
    clocks = [clock for clock in _load(docs / "L8_TIMING_WAVEFORM.json").get("clock_domains", [])
              if (clock.get("domain_kind") == "primary" or clock.get("role") in {"primary", "master"})
              and (clock.get("pdk_scoped_target") is None
                   or _pdk_name(clock["pdk_scoped_target"]) == _pdk_name(pdk))]
    return clocks or _load(docs / "L8_RTL_CONSTANTS.json").get("clock_domains", [])


def clock_period_ns(clock: dict):
    return (float(clock["period_ns"]) if clock.get("period_ns") is not None else
            1000 / float(clock["freq_mhz"]) if clock.get("freq_mhz") else None)


def build_config(project: Path | str, *, route: str | None = None, pdk: str | None = None) -> dict[str, Any]:
    """Read L documents and produced RTL; route is supplied by the Router caller."""
    project = Path(project).resolve()
    docs = project / "phase1/generated_docs"
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
    pdk = _pdk_name(pdk)
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
    clocks = declared_clocks(project, pdk)
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
        periods = [value for clock in clocks if (value := clock_period_ns(clock)) is not None]
        override = fields.get("clock_target", {}).get("period_ns") if len(clocks) == 1 else None
        period = override or (min(periods) if periods else None)
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
    config.update({key: value for key, value in implementation.items() if key.startswith("PDN_")})
    from sdc_constraints import collect_sdc_files

    sdcs = collect_sdc_files(project)
    sdc = sdcs[0] if sdcs else project / "phase3/stage3/pnr/constraint.sdc"
    if sdc.is_file():
        from sdc_constraints import create_clocks_in_text

        config.update(FALLBACK_SDC=str(sdc), PNR_SDC_FILE=str(sdc), SIGNOFF_SDC_FILE=str(sdc))
        declared = create_clocks_in_text(sdc.read_text())
        ports = list(dict.fromkeys(clock["port_name"] for clock in declared if clock["port_name"]))
        periods = [clock["period_ns"] for clock in declared if clock["period_ns"] is not None]
        if ports:
            config["CLOCK_PORT"] = ports[0] if len(ports) == 1 else ports
        if periods:
            config["CLOCK_PERIOD"] = min(periods)
    config.update(_load(project / "work/flow/native_overrides.json"))
    notes = project / "work/flow/config_sources.json"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(json.dumps({"sources": sources, "assumptions": assumptions}, indent=2) + "\n")
    return config


def build_native_config(project: Path | str, *, route: str | None = None, pdk: str | None = None,
                        on_tool_run=None) -> dict[str, Any]:
    config = build_config(project, route=route, **({"pdk": pdk} if pdk else {}))
    config = _native_pdn_numbers(config)
    if route in {"ic", "DIE"}:
        from flow_chip_inputs import prepare
        config = prepare(Path(project).resolve(), config,
                         **({"on_tool_run": on_tool_run} if on_tool_run is not None else {}))
    return _native_pdn_numbers(config)


def _native_pdn_numbers(config):
    return {key: Decimal(str(value)) if key.startswith("PDN_") and isinstance(value, float)
            else value for key, value in config.items()}


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
