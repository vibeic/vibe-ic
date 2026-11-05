"""Native pad, package, CVC and test-interface measurements."""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

import _pad_ring
import dft_atpg_coverage_check
import pad_bterm_coincidence_check
import pad_side_constraint_check
import perc_signoff_check
import provider_bond_pad_edge
import tapeout_readiness_check
import librelane_contract as contract
from _staged_pdk_tech_lef import discover_staged_tech_lefs, select_staged_tech_lef

IO_REPORT = Path("reports/phase3/io_pad_chip_top.json")
PAD_DEF = Path(_pad_ring.PADRING_DEF_REL)



class D75Refusal(ValueError):
    def __init__(self, code, detail, *, failed=False):
        self.code, self.detail, self.failed = code, detail, failed
        super().__init__(f"{code}: {detail}")


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
        if isinstance(value, dict):
            return value
    except (OSError, ValueError):
        pass
    raise D75Refusal("D75_REQUIRED_INPUT_ABSENT_OR_INVALID", str(path))


def _record(project, path):
    path = contract.project_path(project, path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path)}


def _native_folder(project, state_path=None):
    if state_path:
        selected = contract.project_path(project, state_path)
        if not selected.is_file():
            raise FileNotFoundError(selected)
        return selected.parent
    from librelane_postroute import stapostpnr_state
    try:
        return stapostpnr_state(project)[0]
    except contract.Refusal as exc:
        if exc.code == 'LL_STAPOSTPNR_STATE_ABSENT':
            return None
        raise


def _pdk_path(project, raw, config):
    path = contract.project_path(project, raw)
    if path.is_file():
        return path
    selected = contract.resolve_state_pdk_asset(raw, pdk=config.get("PDK"))
    if selected is None:
        raise FileNotFoundError(raw)
    return selected


def _io_lefs(project, report, folder=None):
    config = _read(folder / "config.json") if folder else {}
    values = config.get("PAD_LEFS") or report.get("io_library_lefs")
    if not isinstance(values, list) or not values:
        raise D75Refusal("D75_IO_LIBRARY_ABSENT", str(IO_REPORT))
    return list(dict.fromkeys(_pdk_path(project, raw, config) for raw in values))



def _tech_lef(project):
    root = project / "input/pdk"
    selected = select_staged_tech_lef(root, discover_staged_tech_lefs(root))
    if selected is None:
        raise D75Refusal("D75_TECH_LEF_UNBOUND", str(root))
    return selected.path


def _current_native_geometry(project, io_lefs, folder=None):
    """Use the DEF and technology named by this run's final STA State."""
    if folder is None:
        return None
    state, config = _read(folder / "state_out.json"), _read(folder / "config.json")
    current_def = contract.project_path(project, state["def"])
    corner = config.get("DEFAULT_CORNER", "")
    choices = [raw for pattern, raw in config.get("TECH_LEFS", {}).items()
               if fnmatch.fnmatch(corner, pattern)]
    if len(choices) != 1:
        raise D75Refusal("D75_TECH_LEF_UNBOUND", str(choices))
    tech = _pdk_path(project, choices[0], config)
    inputs = [_record(project, current_def), _record(project, tech)]
    detail = {"source": str(folder / "state_out.json"), "top": config.get("DESIGN_NAME"),
              "def": inputs[0], "tech": inputs[1]}
    result = {"def": current_def, "tech": tech, "inputs": inputs, "detail": detail}
    for key, state_key in (("odb", "odb"), ("netlist", "nl")):
        if state.get(state_key):
            result[key] = contract.project_path(project, state[state_key])
            detail[key] = _record(project, result[key])
    return result


def _check(name, status, detail):
    return {"check": name, "status": status, "detail": detail}


def _aggregate(checks):
    statuses = [row.get("status") for row in checks]
    return ("FAIL" if "FAIL" in statuses else "NOT_MEASURED"
            if not statuses or any(s not in ("PASS", "NOT_APPLICABLE") for s in statuses) else "PASS")


def execute(project, context):
    project = Path(project).resolve()
    checks, inputs = [], []
    try:
        features = context.get("features") or {}
        io = _read(project / IO_REPORT) if (project / IO_REPORT).is_file() else {}
        folder = _native_folder(project, context.get("state_path"))
        io_lefs = _io_lefs(project, io, folder)
        native = _current_native_geometry(project, io_lefs, folder)
        def_path, tech = ((native["def"], native["tech"]) if native else
                         (project / PAD_DEF, _tech_lef(project)))
        inputs.extend(_record(project, path) for path in (def_path, tech, *io_lefs))
        side = pad_side_constraint_check.check(project, def_path)
        checks.append(_check("pad_side_constraint_check", side.get("verdict", "NOT_MEASURED"), side))
        rc, pads = pad_bterm_coincidence_check.run(def_path.read_text(), tech.read_text(), io_lefs)
        pad_status = ("FAIL" if pads.get("not_connected_nets") else "NOT_MEASURED"
                      if rc or pads.get("undecided_nets") or not pads.get("connected_nets") else "PASS")
        checks.append(_check("pad_bterm_coincidence_check", pad_status, pads))
        independent = context.get("provider_not_applicable")
        if isinstance(independent, str) and independent.strip():
            checks.append(_check("provider_bond_pad_edge", "NOT_APPLICABLE", {"contract": independent}))
        else:
            layouts = ([contract.project_path(project, context["layout"])] if context.get("layout")
                       else tapeout_readiness_check.discover_layouts(project))
            if len(layouts) != 1:
                raise D75Refusal("D75_FINAL_GEOMETRY_ABSENT_OR_AMBIGUOUS", str(layouts))
            edge = provider_bond_pad_edge.measure(project, layouts[0], top=io.get("chip_top_module") or "")
            checks.append(_check("provider_bond_pad_edge", edge.get("verdict", "NOT_MEASURED"), edge))
        if features.get("requires_dft"):
            dft = dft_atpg_coverage_check.audit(project)
            checks.append(_check("dft_atpg_coverage_check", dft.get("verdict", "NOT_MEASURED"), dft))
        if features.get("requires_perc"):
            path = project / "reports/phase3/perc_equivalent.json"
            perc = _read(path) if path.is_file() else {}
            cvc = perc.get("native_cvc")
            if isinstance(cvc, dict):
                checks.append(_check("perc_signoff_check", cvc.get("native_result", "NOT_MEASURED"), cvc))
            else:
                perc = perc_signoff_check.audit(project)
                checks.append(_check("perc_signoff_check", perc.get("verdict", "NOT_MEASURED"), perc))
        if features.get("package_model_required"):
            package = _read(contract.project_path(project, context["package_report"]))
            status = package.get("component_status", package.get("status", "NOT_MEASURED"))
            checks.append(_check("package_electrical_feedback", status, package))
    except (D75Refusal, OSError, ValueError, KeyError, TypeError, contract.Refusal) as exc:
        checks.append(_check("missing_input", "NOT_MEASURED", str(exc)))
    return {"component_status": _aggregate(checks), "checks": checks, "inputs": inputs,
            "scope": "Native pad geometry, provider edge and selected package/test checks"}
