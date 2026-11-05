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
    "MAX_FANOUT_CONSTRAINT", "MAX_TRANSITION_CONSTRAINT",
    "MAX_CAPACITANCE_CONSTRAINT", "FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT",
    "PDN_VOFFSET", "PDN_HOFFSET", "PDN_SKIPTRIM", "PDN_CORE_RING",
    "PDN_CORE_RING_CONNECT_TO_PADS", "PDN_VWIDTH", "PDN_HWIDTH",
    "PDN_VPITCH", "PDN_HPITCH", "PDN_VSPACING", "PDN_HSPACING",
}
IMPLEMENTATION_SETTINGS = {"RUN_POST_GRT_RESIZER_TIMING", "RUN_POST_GRT_DESIGN_REPAIR",
                           "EXTRA_EXCLUDED_CELLS", "FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT"}


def implementation_setting(key: str) -> bool:
    return key in IMPLEMENTATION_SETTINGS or key.startswith(("CTS_", "PDN_", "GRT_DESIGN_REPAIR_"))


def native_defaults(config):
    """Exclude delay-cell families through LibreLane's native wildcard setting."""
    excluded = [*(config.get("EXTRA_EXCLUDED_CELLS") or []), "*dly*", "*delay*"]
    return config.copy(EXTRA_EXCLUDED_CELLS=list(dict.fromkeys(excluded)))


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


_POWER_UNIT_EXPONENTS = {"W": 0, "mW": -3, "uW": -6, "µW": -6, "μW": -6}
_POWER_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_POWER_BOUND = re.compile(
    rf"(?P<operator><=|>=|<|>|≤|≥|under\b|below\b|at\s+most\b|at\s+least\b|"
    rf"no\s+more\s+than\b|no\s+less\s+than\b)\s*"
    rf"(?P<value>{_POWER_NUMBER})\s*(?P<unit>[mµμu]?W)\b", re.I)
_POWER_INFORMATIONAL = re.compile(
    r"informational|information[- ]only|non[- ]sign[- ]?off|non[- ]gating|"
    r"not\s+(?:a\s+)?(?:sign[- ]?off\s+)?gate|資訊性|信息性|❌", re.I)
_POWER_PARTIAL_SCOPE = re.compile(
    r"\b(?:per[- ]rail|(?:core|rail)[- ]only|(?:core|rail|domain|block)\s+(?:total\s+)?power|"
    r"(?:core|rail|domain|block)\s+budget|power\s*\(\s*(?:core|rail)\b|"
    r"(?:VDD\w*|VCC\w*)\s+power\s+budget|power\s+budget\s+(?:for|of)\s+"
    r"(?:core|rail|domain|block|VDD\w*|VCC\w*))",
    re.I)


def _power_watts(raw: str | int | float | Decimal, unit: str) -> Decimal | None:
    """Shift the decimal exponent without rounding the declared coefficient."""
    value = Decimal(str(raw))
    if not value.is_finite() or value < 0:
        return None
    sign, digits, exponent = value.as_tuple()
    return Decimal((sign, digits, exponent + _POWER_UNIT_EXPONENTS[unit]))


def _power_limits(text: str, unit: str | None = None) -> dict | None:
    limits = {}
    if unit and not re.search(r"[mµμu]?W\b", text):
        text += " " + unit
    for match in _POWER_BOUND.finditer(text.replace("*", "")):
        original_unit = match["unit"]
        if original_unit not in _POWER_UNIT_EXPONENTS:
            continue
        value = _power_watts(match["value"], original_unit)
        if value is None:
            return None
        operator = " ".join(match["operator"].lower().split())
        side = "min" if operator in {">", ">=", "≥", "at least", "no less than"} else "max"
        exclusive = operator in {"<", ">", "under", "below"}
        if side in limits and limits[side] != value:
            return None
        limits[side] = value
        if exclusive:
            limits[side + "_exclusive"] = True
    if not limits and unit:
        scalar = re.fullmatch(rf"({_POWER_NUMBER})\s*([mµμu]?W)", text.strip())
        if scalar:
            value = _power_watts(scalar[1], scalar[2])
            if value is not None:
                limits["max"] = value
    return limits or None


def _power_check(source: dict, limits: dict | None, tt: bool = False) -> dict:
    check = {
        "metric": "power__total__corner:" + ("*tt*" if tt else "*"),
        "operator": "within_declared_bounds", "limit": limits, "unit": "W",
        "source": source,
        "scope": "Native estimated total power of the current netlist, including die pads. "
                 "The estimate uses the native activity assumptions.",
    }
    if limits is None:
        check["missing"] = ("Declared total-power bound could not be parsed or its scope is ambiguous "
                            "in the cited source.")
    return check


def _structured_power_limits(raw: Any, unit: str) -> dict | None:
    if isinstance(raw, dict):
        unit = raw.get("unit", unit)
        if not isinstance(unit, str) or unit not in _POWER_UNIT_EXPONENTS:
            return None
        limits = {}
        for side in ("min", "max"):
            if side not in raw:
                continue
            value = raw[side]
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                return None
            value = _power_watts(value, unit)
            if value is None:
                return None
            limits[side] = value
            if raw.get(side + "_exclusive") is True:
                limits[side + "_exclusive"] = True
        return limits or None
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
        return None
    return _power_limits(str(raw), unit)


def _power_scope(text: str) -> str:
    subject = re.split(r"\b(?:including|includes)\b", text.replace("_", " "), maxsplit=1, flags=re.I)[0]
    total = re.search(r"\b(?:total[ -]+(?:power|netlist)|(?:whole|entire|full)[ -]+"
                      r"(?:netlist|design|chip|die))\b", subject, re.I)
    partial = _POWER_PARTIAL_SCOPE.search(subject)
    if partial:
        return "ambiguous" if total and partial.start() >= total.end() else "partial"
    if re.search(r"\b(?:core|rail|domain|block)\b", subject, re.I):
        return "ambiguous" if total else "partial"
    return "total"


def _power_metadata_excluded(holder: dict) -> bool:
    return (holder.get("informational") is True
            or any(holder.get(key) is False for key in ("signoff_gate", "signoff", "gating"))
            or bool(holder.get("rail"))
            or _power_scope(str(holder.get("scope", ""))) == "partial")


def _json_field_offsets(text: str, start: int = 0) -> dict[str, tuple[int, int]]:
    """Locate immediate JSON keys and values without confusing nested names."""
    decoder = json.JSONDecoder()
    position = text.index("{", start) + 1
    offsets = {}
    while True:
        position += len(text[position:]) - len(text[position:].lstrip())
        if text[position] == "}":
            return offsets
        key, end = decoder.raw_decode(text, position)
        value_start = text.index(":", end) + 1
        value_start += len(text[value_start:]) - len(text[value_start:].lstrip())
        offsets[key] = position, value_start
        _, position = decoder.raw_decode(text, value_start)
        position += len(text[position:]) - len(text[position:].lstrip())
        if text[position] == ",":
            position += 1


def declared_power_checks(project: Path) -> list[dict]:
    """Read explicit total-power bounds without running tools or writing artifacts.

    Supports direct comparisons in source text and total-budget fields at the
    root or fields object of generated L documents. Relative baseline formulas
    are retained as unparsed declarations unless a direct ceiling is present.
    """
    checks = []
    for file, text in _input_docs(project).items():
        gate_column = None
        for line_number, line in enumerate(text.splitlines(), 1):
            columns = [column.strip() for column in line.strip().strip("|").split("|")]
            if "|" in line and any(re.search(r"sign[- ]?off\s+gate|是否.*gate", column, re.I)
                                   for column in columns):
                gate_column = next(index for index, column in enumerate(columns)
                                   if re.search(r"sign[- ]?off\s+gate|是否.*gate", column, re.I))
            if "|" not in line:
                gate_column = None
            if (gate_column is not None and len(columns) > gate_column
                    and re.fullmatch(r"(?:no|false|否|❌(?:\s*否)?)", columns[gate_column], re.I)):
                continue
            scope = _power_scope(line)
            if (_POWER_INFORMATIONAL.search(line) or scope == "partial"
                    or not re.search(r"\b(?:total[ _-]+power|power[ _-]+budget)\b", line, re.I)):
                continue
            limits = _power_limits(line) if scope == "total" else None
            if limits is None and not re.search(
                    r"[|<>≤≥]|\b(?:budget|target|limit|under|below|baseline|shall|must)\b", line, re.I):
                continue
            matches = list(_POWER_BOUND.finditer(line.replace("*", "")))
            checks.append(_power_check({
                "file": file, "line": line_number, "text": line,
                "bound": [match[0] for match in matches] or line,
                "unit": [match["unit"] for match in matches],
            }, limits, bool(re.search(r"\bTT\b", line, re.I))))
    for path in sorted((project / "phase1/generated_docs").glob("L*.json")):
        text = path.read_text()
        document = json.loads(text, parse_float=Decimal)
        if not isinstance(document, dict) or _power_metadata_excluded(document):
            continue
        root_offsets = _json_field_offsets(text)
        for prefix, holder in (("", document), ("fields.", document.get("fields", {}))):
            if not isinstance(holder, dict) or not holder:
                continue
            if _power_metadata_excluded(holder):
                continue
            offsets = (_json_field_offsets(text, root_offsets["fields"][1])
                       if prefix else root_offsets)
            for field, unit in (("power_budget_uw", "uW"), ("power_budget_mw", "mW"),
                                ("total_power_mw", "mW")):
                raw = holder.get(field)
                if raw is None or raw == "":
                    continue
                if field == "total_power_mw" and not isinstance(raw, dict):
                    continue
                if isinstance(raw, dict) and _power_metadata_excluded(raw):
                    continue
                line_number = text.count("\n", 0, offsets[field][0]) + 1
                scopes = [document.get("scope", ""), holder.get("scope", "")]
                if isinstance(raw, dict):
                    scopes.append(raw.get("scope", ""))
                ambiguous = any(_power_scope(str(scope)) == "ambiguous" for scope in scopes)
                checks.append(_power_check({
                    "file": str(path.relative_to(project)), "line": line_number,
                    "text": text.splitlines()[line_number - 1], "field": prefix + field,
                    "bound": raw, "unit": raw.get("unit", unit) if isinstance(raw, dict) else unit,
                }, None if ambiguous else _structured_power_limits(raw, unit),
                    str(raw.get("corner", holder.get("corner", "")) if isinstance(raw, dict)
                        else holder.get("corner", "")).casefold() == "tt"))
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
        from sdc_constraints import create_clocks_in_text

        config.update(FALLBACK_SDC=str(sdc), PNR_SDC_FILE=str(sdc), SIGNOFF_SDC_FILE=str(sdc))
        declared = create_clocks_in_text(sdc.read_text())
        ports = list(dict.fromkeys(clock["port_name"] for clock in declared if clock["port_name"]))
        periods = [clock["period_ns"] for clock in declared if clock["period_ns"] is not None]
        if ports:
            config["CLOCK_PORT"] = ports[0] if len(ports) == 1 else ports
        if periods:
            config["CLOCK_PERIOD"] = min(periods)
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
