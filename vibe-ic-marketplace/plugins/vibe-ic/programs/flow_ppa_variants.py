"""Bounded native candidates for public exploration, reusing the PPA kernels.

The baseline-first Cartesian ordering and private seeded shuffle are ported from
pre-cutover _ppa/search.py:propose. This module proposes native settings only;
flow_explore owns execution, native results and adoption.
"""
from __future__ import annotations

import random
import math
from decimal import Decimal, InvalidOperation
from pathlib import Path

from constraint_prose_tokens import scan_inputs
from flow_config import SETTING_ALIASES, _input_docs, _load, _value, native_excluded_cells
from _prose_polarity import is_denied


RECOVERY = "VIBEIC_PRR_RECOVER_POWER_PCT"
SAMPLE_SEED = 42
MAX_UTIL = ("PL_RESIZER_SETUP_MAX_UTIL_PCT", "PL_RESIZER_HOLD_MAX_UTIL_PCT",
            "VIBEIC_PRR_MAX_UTIL_PCT")
SIZING = {"VIBEIC_PRR_LIMIT_SIZING_AREA": 1, "VIBEIC_PRR_LIMIT_SIZING_LEAKAGE": 1}
L2_SETTINGS = {"GPL_CELL_PADDING", "DPL_CELL_PADDING", "PL_TARGET_DENSITY_PCT",
               "PL_TIMING_DRIVEN", "PL_ROUTABILITY_DRIVEN", "GRT_ADJUSTMENT",
               "GRT_LAYER_ADJUSTMENTS", "CTS_SINK_CLUSTERING_SIZE",
               "CTS_SINK_CLUSTERING_MAX_DIAMETER", "PL_RESIZER_SETUP_REPAIR_TNS_PCT",
               "GRT_RESIZER_SETUP_REPAIR_TNS_PCT", "GRT_RESIZER_SETUP_MAX_UTIL_PCT",
               "GRT_RESIZER_HOLD_MAX_UTIL_PCT"}


def selected_level(project: Path, requested: int | None = None) -> tuple[int, str]:
    """CLI overrides a document PPA_LEVEL; ordinary exploration defaults to two."""
    if requested is not None:
        if type(requested) is not int or requested not in range(5):
            raise ValueError("PPA level must be an integer from 0 through 4")
        return requested, "CLI"
    fields = _load(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").get("fields", {})
    declarations = [(fields["ppa_level"], "L19 fields.ppa_level")] if "ppa_level" in fields else []
    rows = fields.get("constraint_declarations", [])
    rows += scan_inputs(_input_docs(project).items())["settings"]
    declarations += [(row["value"], f"{row.get('source', 'L19')}:{row.get('line', '')}")
                     for row in rows if row.get("token") == "PPA_LEVEL"
                     and not is_denied(str(row.get("evidence", "")))]
    levels = []
    for value, source in declarations:
        value = _value(value)
        if type(value) is not int or value not in range(5):
            raise ValueError(f"Invalid document PPA_LEVEL at {source}: {value!r}")
        levels.append((value, source))
    if len({level for level, _ in levels}) > 1:
        raise ValueError("Conflicting document PPA_LEVEL declarations")
    return levels[0] if levels else (2, "default")


def pinned_settings(project: Path) -> set[str]:
    """Reuse the existing input-domain declaration reader before proposing edits."""
    from l19_constraint_token_emit import collect

    fields = _load(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").get("fields", {})
    return {SETTING_ALIASES.get(row["token"], row["token"])
            for row in [*collect(project), *fields.get("constraint_declarations", [])]
            if row.get("kind") == "flow_setting" and row.get("token")}


def _normalized(value):
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return value


def _effective(settings):
    values = {key: _normalized(value) for key, value in settings.items()}
    for key in ("GPL_CELL_PADDING", "DPL_CELL_PADDING"):
        if values.get(key) is not None:
            values[key] = int(values[key]) // 2
    layers = values.get("GRT_LAYER_ADJUSTMENTS")
    if layers and values.get("GRT_ADJUSTMENT") is not None:
        values["GRT_LAYER_ADJUSTMENTS"] = [value or values["GRT_ADJUSTMENT"] for value in layers]
        values.pop("GRT_ADJUSTMENT")
    return values


def level_two_axes(resolved, activity):
    """Native names/units from ppa_pnr_search_space and the reference tool run."""
    active = set(activity.get("steps", []))
    axes, skipped = {}, {}
    if "OpenROAD.GlobalPlacement" in active:
        axes["placement"] = [None, *[
            {"GPL_CELL_PADDING": global_pad, "DPL_CELL_PADDING": detailed_pad}
            for global_pad, detailed_pad in ((0, 0), (2, 0), (2, 2), (4, 0), (4, 2), (4, 4))]]
        axes["density"] = [None, *[{"PL_TARGET_DENSITY_PCT": v} for v in (40, 50, 60)]]
        axes["placement_mode"] = [None, {"PL_TIMING_DRIVEN": True},
                                  {"PL_ROUTABILITY_DRIVEN": True}]
    else:
        skipped["placement"] = "Reference has no executed native GlobalPlacement"
    if "OpenROAD.GlobalRouting" in active:
        axes["routing"] = [None, *[{"GRT_ADJUSTMENT": v} for v in (.1, .3, .5)]]
        layers = resolved.get("GRT_LAYER_ADJUSTMENTS")
        if layers:
            axes["routing"] += [{"GRT_LAYER_ADJUSTMENTS": [v] * len(layers)} for v in (.1, .3, .5)]
            if all(_normalized(value) != 0 for value in layers):
                axes["routing"] = [v for v in axes["routing"] if not v or "GRT_ADJUSTMENT" not in v]
    else:
        skipped["routing"] = "Reference has no executed native GlobalRouting"
    for step, prefix in (("OpenROAD.ResizerTimingPostGPL", "PL"),
                         ("OpenROAD.ResizerTimingPostGRT", "GRT")):
        if step in active:
            axes[prefix + "_resizer"] = [None,
                {prefix + "_RESIZER_SETUP_REPAIR_TNS_PCT": 50},
                {prefix + "_RESIZER_SETUP_MAX_UTIL_PCT": 80,
                 prefix + "_RESIZER_HOLD_MAX_UTIL_PCT": 80}]
    if activity.get("cts_preclustering") is True:
        limit = resolved.get("MAX_FANOUT_CONSTRAINT")
        sizes = sorted({min(size, int(Decimal(str(limit)))) if limit else size for size in (2, 4, 8)})
        axes["cts"] = [None, *[{"CTS_SINK_CLUSTERING_SIZE": size,
                                "CTS_SINK_CLUSTERING_MAX_DIAMETER": diameter}
                               for size in sizes for diameter in (25, 50, 100)]]
    else:
        skipped["CTS clustering"] = "Reference native log has no executed preclustering solution"
    skipped["density addon"] = "LibreLane consumes a density target; native ORFS addon stays in Stage A"
    return axes, skipped


def native_candidates(project: Path, original: dict, resolved: dict, *, level: int,
                      seed: int = SAMPLE_SEED, activity=None) -> list[tuple[str, dict]]:
    """Reference first; six bounded Level1 moves or up to24 native combinations.

    A document-pinned setting is never changed to manufacture another trial.
    The population can therefore be smaller than its budget; publish that fact.
    Level3 is owned by the native-tool lane, not an algorithm in this module.
    """
    pinned = pinned_settings(project)
    base = {}
    for key, value in original.items():
        canonical = SETTING_ALIASES.get(key, key)
        if canonical not in pinned:
            base[canonical] = float(value) * 100 if key == "PL_TARGET_DENSITY" else value
    if level == 0:
        return [("reference", base)]
    if level not in (1, 2):
        raise ValueError("Levels3/4 require the native-tool result handoff; they are not knob enumeration")
    excluded = resolved.get("EXTRA_EXCLUDED_CELLS")
    if excluded is None:
        excluded = native_excluded_cells(original)
    toggle = ([cell for cell in excluded if cell != "*_1"] if "*_1" in excluded
              else [*excluded, "*_1"])
    utilization = {key: 80 for key in MAX_UTIL}
    proposals = [
        ("reference", base),
        ("allow_min_drive" if "*_1" in excluded else "exclude_min_drive", {"EXTRA_EXCLUDED_CELLS": toggle}),
        ("recover_power_50", {RECOVERY: 50}),
        ("recover_power_100", {RECOVERY: 100}),
        ("resizer_util_80", utilization),
        ("power_sizing", {RECOVERY: 100, **SIZING}),
        ("power_util_80", {RECOVERY: 100, **utilization}),
    ]
    if level == 2:
        # Port the old proposer without Candidate identities, digests or receipts.
        # The axes are bounded native settings, so the complete grid is small.
        values = {"drive": [None, {"EXTRA_EXCLUDED_CELLS": toggle}],
                  "recover": [None, {RECOVERY: 50}, {RECOVERY: 100}],
                  "util": [None, *[{key: value for key in MAX_UTIL} for value in (80, 90)]],
                  "sizing": [None, SIZING]}
        extra, _ = level_two_axes(resolved, activity or {})
        values.update(extra)
        # Remove document-pinned axes before constructing the Cartesian grid.
        # Keep distinct effective settings, including native padding/route aliases.
        reference_settings = {**resolved, **base}
        for axis, options in values.items():
            filtered = [None]
            for option in options:
                setting = {key: value for key, value in (option or {}).items() if key not in pinned}
                if (setting and _effective({**reference_settings, **setting}) != _effective(reference_settings)
                        and setting not in filtered):
                    filtered.append(setting)
            values[axis] = filtered
        axes = sorted(values)
        total = math.prod(len(values[axis]) for axis in axes)
        # Sample Cartesian indices without materializing a large product.
        indices = random.Random(seed).sample(range(1, total), min(total - 1, 96))
        rest = []
        for index in indices:
            point = {}
            for axis in reversed(axes):
                index, digit = divmod(index, len(values[axis]))
                point[axis] = values[axis][digit]
            rest.append(point)
        # Keep the high-value Level1 moves and one isolated move per new axis.
        for axis, options in sorted(values.items()):
            proposals.extend((f"{axis}_{i}", value) for i, value in enumerate(options[1:2], 1))
        for i, point in enumerate(rest, 1):
            settings = {key: value for axis in sorted(point)
                        for key, value in (point[axis] or {}).items()}
            proposals.append((f"native_{i:03d}", settings))
    candidates = []
    effective_seen = []
    for name, settings in proposals:
        effective = {**base, **{key: value for key, value in settings.items() if key not in pinned}}
        signature = _effective({**resolved, **effective})
        if signature not in effective_seen:
            candidates.append((name, effective))
            effective_seen.append(signature)
        if len(candidates) == (7 if level == 1 else 24):
            break
    return candidates
