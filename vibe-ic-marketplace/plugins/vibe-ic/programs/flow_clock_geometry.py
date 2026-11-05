"""Derive native clock-wire repair length from the core capacitance budget."""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
import fnmatch
import gzip
import math
import re

from flow_pdn_current import matching, paths
from sdc_environment import _liberty_blocks, _own_attrs
from spice_correlation_check import parse_liberty_header


def _attribute(body, name):
    found = re.search(r"\b" + name + r'\s*:\s*(?:"([^"]*)"|([^;]+))\s*;', body)
    return next((value.strip() for value in found.groups() if value is not None), None) if found else None


def _buffer_input_caps(text, excluded):
    if not re.search(r"\bcapacitive_load_unit\s*\(\s*[\d.]+\s*,\s*(?:ff|pf|nf)\s*\)", text, re.I):
        return None
    scale = parse_liberty_header(text)["cap_unit_pf"]
    values = []
    for cell, body in _liberty_blocks(text, "cell"):
        if (any(fnmatch.fnmatchcase(cell, pattern) for pattern in excluded)
                or _attribute(_own_attrs(body), "dont_use") == "true"):
            continue
        pins = {name: _own_attrs(pin) for name, pin in _liberty_blocks(body, "pin")}
        inputs = [name for name, attrs in pins.items() if _attribute(attrs, "direction") == "input"]
        outputs = [attrs for attrs in pins.values() if _attribute(attrs, "direction") == "output"]
        if len(inputs) != 1 or len(outputs) != 1:
            continue
        function = (_attribute(outputs[0], "function") or "").strip("() ")
        if function != inputs[0] or _attribute(outputs[0], "three_state") is not None:
            continue
        caps = [_attribute(pins[inputs[0]], name)
                for name in ("capacitance", "rise_capacitance", "fall_capacitance")]
        caps = [float(value) * scale for value in caps if value is not None]
        if not caps or any(not math.isfinite(value) or value < 0 for value in caps):
            return None
        values.append(max(caps))
    return values


def clock_settings(config):
    if (config.get("PNR_SDC_FILE") or config.get("SIGNOFF_SDC_FILE")
            or float(config.get("CTS_CLK_MAX_WIRE_LENGTH") or 0) != 0):
        return {}
    limit = config.get("MAX_CAPACITANCE_CONSTRAINT")
    corners = config.get("STA_CORNERS") or []
    layers = config.get("CLOCK_WIRE_RC_LAYERS") or []
    if limit is None or not corners or not layers:
        return {}
    wire_caps = []
    for corner in corners:
        views = [view for pattern, view in (config.get("LAYERS_RC") or {}).items()
                 if fnmatch.fnmatchcase(corner, pattern)]
        for layer in layers:
            caps = [view[layer].get("cap") for view in views if layer in view]
            if not caps or any(value is None for value in caps):
                return {}
            wire_caps.extend(float(value) for value in caps)
    excluded = list(config.get("EXTRA_EXCLUDED_CELLS") or [])
    try:
        for path in paths(config.get("PNR_EXCLUDED_CELL_FILE")):
            excluded.extend(word for line in path.read_text().splitlines()
                            for word in line.split("#", 1)[0].split())
        libraries = {path for corner in corners for path in matching(config.get("LIB") or {}, corner)}
        if not libraries or any(not matching(config.get("LIB") or {}, corner) for corner in corners):
            return {}
        input_caps = []
        for path in libraries:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt") as stream:
                values = _buffer_input_caps(stream.read(), excluded)
            if values is None:
                return {}
            input_caps.extend(values)
        grids = []
        for path in set(paths(config.get("TECH_LEFS"))):
            grid = re.search(r"\bMANUFACTURINGGRID\s+([0-9.eE+-]+)\s*;", path.read_text(), re.I)
            if grid is None:
                return {}
            grids.append(Decimal(grid[1]))
    except OSError:
        return {}
    if (not input_caps or not grids or any(not value.is_finite() or value <= 0 for value in grids)
            or any(not math.isfinite(value) or value <= 0 for value in wire_caps)
            or not math.isfinite(float(limit))):
        return {}
    remaining = Decimal(str(limit)) - Decimal(str(max(input_caps)))
    if remaining <= 0:
        return {}
    quantum = max(grids)
    length = remaining / Decimal(str(max(wire_caps)))
    length = (length / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum
    return {"CTS_CLK_MAX_WIRE_LENGTH": float(length)} if length > 0 else {}
