"""Read native tool result carriers for later Stage B execution.

Preparing inputs runs no optimization and carries no previous PASS verdicts.
The caller selects the final Stage A result; this reader does not rank trials.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil

import vibeic_temp

from flow_ppa_variants import pinned_settings
from librelane_contract import _copy_state_views


def _one(paths, description):
    paths = sorted(set(paths))
    if len(paths) != 1:
        raise ValueError(f"Select one native {description}; found {len(paths)}: {paths}")
    return paths[0]


def native_views(folder, backend):
    folder = Path(folder).resolve()
    if backend == "orfs":
        odb = _one(folder.glob("results/**/6_final.odb"), "ORFS final database")
        suffixes = {"odb": ".odb", "def": ".def", "nl": ".v", "sdc": ".sdc", "gds": ".gds"}
        views = {key: odb.with_suffix(suffix) for key, suffix in suffixes.items()
                 if odb.with_suffix(suffix).is_file()}
        original_spef = odb.with_suffix(".spef")
    elif backend == "librelane":
        odb = _one(folder.glob("**/final/odb/*.odb"), "LibreLane final database")
        final = odb.parent.parent
        extensions = {"def": "def", "nl": "nl.v", "sdc": "sdc", "gds": "gds", "pnl": "pnl.v"}
        views = {"odb": odb}
        for key, extension in extensions.items():
            paths = list((final / key).glob("*." + extension))
            if paths:
                views[key] = _one(paths, "LibreLane " + key)
        original_spef = None
    else:
        raise ValueError("Native handoff backend must be orfs or librelane")
    return views, original_spef if original_spef and original_spef.is_file() else None


def native_settings(folder, backend):
    folder = Path(folder)
    settings, notes = {}, []
    if backend == "librelane":
        paths = list(folder.glob("runs/*/resolved.json")) or list(folder.glob("resolved.json"))
        resolved = json.loads(_one(paths, "LibreLane resolved configuration").read_text())
        from flow_config import implementation_setting
        local_files = {"FALLBACK_SDC", "PNR_SDC_FILE", "SIGNOFF_SDC_FILE", "FP_DEF_TEMPLATE", "PDN_CFG"}
        settings = {key: value for key, value in resolved.items()
                    if implementation_setting(key) and key not in local_files}
        notes.extend("Use project-native input instead of the worker path in " + key
                     for key in sorted(local_files) if resolved.get(key))
    else:
        parameters = json.loads((folder / "design.json").read_text()).get("parameters", {})
        for old, new, multiplier in (
            ("CELL_PAD_IN_SITES_GLOBAL_PLACEMENT", "GPL_CELL_PADDING", 2),
            ("CELL_PAD_IN_SITES_DETAIL_PLACEMENT", "DPL_CELL_PADDING", 2),
            ("CTS_CLUSTER_SIZE", "CTS_SINK_CLUSTERING_SIZE", 1),
            ("CTS_CLUSTER_DIAMETER", "CTS_SINK_CLUSTERING_MAX_DIAMETER", 1),
            ("_FR_LAYER_ADJUST", "GRT_ADJUSTMENT", 1),
        ):
            if old in parameters:
                settings[new] = parameters[old] * multiplier
        logs = list(folder.glob("logs/**/3_3_place_gp.log"))
        if logs:
            text = _one(logs, "ORFS global-placement log").read_text()
            values = re.findall(r"^global_placement\b[^\n]*?-density\s+([\d.eE+\-]+)", text, re.M)
            if values:
                settings["PL_TARGET_DENSITY_PCT"] = float(values[-1]) * 100
        if "PLACE_DENSITY_LB_ADDON" in parameters:
            notes.append("Density addon is retained in the ORFS source; the imported density is the actual native GPL argument when available")
    return settings, notes


def prepare_import(project, folder, backend):
    """Copy real views using the surviving native State bridge's copy kernel."""
    project, folder = Path(project).resolve(), Path(folder).resolve()
    views, spef = native_views(folder, backend)
    destination = project / "work/flow/stage_a"
    destination.mkdir(parents=True, exist_ok=True)
    targets = {key: destination / path.name for key, path in views.items()}
    with vibeic_temp.TemporaryDirectory(prefix="ppa-native-state-") as temporary:
        source_state = Path(temporary) / "state.json"
        source_state.write_text(json.dumps({**{key: str(path) for key, path in views.items()}, "metrics": {}}))
        copied = _copy_state_views(source_state, targets)
    state = {key: str(path) for key, path in targets.items()}
    state["metrics"] = {}
    state_path = destination / "state.json"
    state_path.write_text(json.dumps(state, indent=2) + "\n")
    original_spef = None
    if spef is not None:
        original_spef = destination / spef.name
        shutil.copyfile(spef, original_spef)
    settings, notes = native_settings(folder, backend)
    pinned = pinned_settings(project)
    excluded = {key: value for key, value in settings.items() if key in pinned}
    report = {"backend": backend, "native_state": str(state_path), "views": copied["views"],
              "native_overrides": {key: value for key, value in settings.items() if key not in pinned},
              "document_fixed_settings_excluded": excluded, "notes": notes,
              "original_spef": str(original_spef) if original_spef else None,
              "timing": "Re-extract declared RC corners before timing; the source SPEF is retained with its original native scope",
              "execution": "Inputs prepared only; no candidate or signoff executed"}
    (destination / "inputs.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
