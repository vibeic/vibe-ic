"""Bounded native candidates for public exploration, reusing the PPA kernels.

The baseline-first Cartesian ordering and private seeded shuffle are ported from
pre-cutover _ppa/search.py:propose. This module proposes native settings only;
flow_explore owns execution, native results and adoption.
"""
from __future__ import annotations

import random
from pathlib import Path

from constraint_prose_tokens import scan_inputs
from flow_config import _input_docs, _load, _value, native_excluded_cells
from _prose_polarity import is_denied


RECOVERY = "VIBEIC_PRR_RECOVER_POWER_PCT"
SAMPLE_SEED = 42
MAX_UTIL = ("PL_RESIZER_SETUP_MAX_UTIL_PCT", "PL_RESIZER_HOLD_MAX_UTIL_PCT",
            "VIBEIC_PRR_MAX_UTIL_PCT")
SIZING = {"VIBEIC_PRR_LIMIT_SIZING_AREA": 1, "VIBEIC_PRR_LIMIT_SIZING_LEAKAGE": 1}


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
    return {row["token"] for row in [*collect(project), *fields.get("constraint_declarations", [])]
            if row.get("kind") == "flow_setting" and row.get("token")}


def native_candidates(project: Path, original: dict, resolved: dict, *, level: int,
                      seed: int = SAMPLE_SEED) -> list[tuple[str, dict]]:
    """Reference first; six bounded Level1 moves or sixteen native combinations.

    A document-pinned setting is never changed to manufacture another trial.
    The population can therefore be smaller than its budget; publish that fact.
    Level3 is owned by the native-tool lane, not an algorithm in this module.
    """
    pinned = pinned_settings(project)
    base = {key: value for key, value in original.items() if key not in pinned}
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
        values = {"drive": [None, toggle], "recover": [None, 50, 100],
                  "util": [None, 80, 90], "sizing": [None, SIZING]}
        grid = [{}]
        for axis in sorted(values):
            grid = [dict(point, **{axis: value}) for point in grid for value in values[axis]]
        reference = {axis: values[axis][0] for axis in sorted(values)}
        rest = [point for point in grid if point != reference]
        random.Random(seed).shuffle(rest)
        proposals = [("reference", base)]
        for i, point in enumerate(rest, 1):
            settings = {}
            if point["drive"] is not None:
                settings["EXTRA_EXCLUDED_CELLS"] = point["drive"]
            if point["recover"] is not None:
                settings[RECOVERY] = point["recover"]
            if point["util"] is not None:
                settings.update({key: point["util"] for key in MAX_UTIL})
            if point["sizing"] is not None:
                settings.update(point["sizing"])
            proposals.append((f"native_{i:03d}", settings))
    candidates = []
    for name, settings in proposals:
        effective = {**base, **{key: value for key, value in settings.items() if key not in pinned}}
        if not any(effective == previous for _, previous in candidates):
            candidates.append((name, effective))
        if len(candidates) == (7 if level == 1 else 16):
            break
    return candidates
