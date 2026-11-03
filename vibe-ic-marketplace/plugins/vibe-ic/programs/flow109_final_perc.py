"""Final native CVC electrical screen using this run's LibreLane views.

CVC owns the electrical verdict. Device-physics ESD and substrate/latch-up
coverage remains explicitly outside this open-source screen.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from _atomic_artefact import write_json, write_text
from flow109_admission import AdmissionRefusal
import librelane_contract
import librelane_postroute
import phase3_one_shot_runner as phase3_runner

SCHEMA = "vibeic.flow109.final-perc.v1"
INPUT = "input/flow109/D66.json"
OUTPUTS = ("reports/phase3/perc_equivalent.json", "reports/phase3/perc_equivalent.rpt",
           "reports/phase3/PERC_SIGNOFF_MEMO.md")
REQUIRED_MANUAL = {"ESD protection presence", "io_supply_pad_sufficiency",
                   "Latch-up / well-tap (spacing + device-physics)"}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path, code="D66_REQUIRED_INPUT_INVALID"):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal(code, str(path)) from exc


def _record(project, path):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(project)), "sha256": _sha(path)}


def operation_sources():
    return {"programs/" + name: _sha(HERE / name) for name in
            ("flow109_final_perc.py", "phase3_one_shot_runner.py", "librelane_postroute.py")}


def execute(project, context):
    project = Path(project).resolve()
    result = {"schema": SCHEMA, "step_id": "D66", "producer": "flow109_final_perc",
              "component_status": "NOT_MEASURED", "default_row_status": "NOT_MEASURED",
              "completed": False, "native_started": False,
              "context_sha256": context.get("context_sha256")}
    try:
        folder, state = librelane_postroute.stapostpnr_state(project)
        config = _read(folder / "config.json")
        top, pdk = config["DESIGN_NAME"], config["PDK"]
        image = librelane_contract.resolve_image(project)
        root = librelane_contract.resolve_pdk_root(project, pdk, image=image)
        netlist = Path(state["nl"])
        report = _read(project / "reports/phase3/librelane_pv_lvs.json")
        extraction = report["metrics"]["magic__illegal_overlap__count"]["folder"]
        extracted_state = _read(librelane_contract.project_path(project, extraction) / "state_out.json")
        if _sha(librelane_contract.project_path(project, extracted_state["nl"])) != _sha(netlist):
            raise ValueError("Native extraction does not use the final netlist")
        extracted = librelane_contract.project_path(project, extracted_state["spice"])
        result["native_started"] = True
        native = phase3_runner._native_cvc_category(project, top, None, image,
            adopted_netlist=netlist, extracted_netlist=extracted, pdk_dir=str(Path(root) / pdk),
            library=config["STD_CELL_LIBRARY"], power_nets=config.get("VDD_NETS", []),
            ground_nets=config.get("GND_NETS", []))
        native['native_result'] = native['result']
        status = native["result"] if native["result"] in {"PASS", "FAIL"} else "NOT_MEASURED"
        summary = {"verdict": "PERC_EQUIV_" + (status if status != "NOT_MEASURED" else "INCOMPLETE"),
            "native_cvc": native, "categories": [native],
            "automated_failed": [native["category"]] if status == "FAIL" else [],
            "automated_incomplete": [native["category"]] if status == "NOT_MEASURED" else [],
            "commercial_calibre_perc_run": False,
            "manual_review_pending": sorted(REQUIRED_MANUAL),
            "geometry_foundry_data_residual": "CVC does not measure ESD or substrate/latch-up device physics."}
        write_json(project / OUTPUTS[0], summary)
        write_text(project / OUTPUTS[1], "Native CVC electrical screen: " + status + "\n" + native.get("note", "") + "\n")
        write_text(project / OUTPUTS[2], summary["geometry_foundry_data_residual"] + "\n")
        result.update(component_status=status, automated_component_status=status,
            default_row_status=status, completed=status == "PASS", native_cvc=native,
            perc_summary=summary, reason="D66_NATIVE_CVC_" + status,
            manual_review_pending=sorted(REQUIRED_MANUAL),
            final_subjects={"netlist": str(netlist), "extracted_netlist": str(extracted)},
            outputs=[_record(project, project / rel) for rel in OUTPUTS])
    except Exception as exc:
        result.update(reason="D66_NATIVE_CVC_UNAVAILABLE", detail=f"{type(exc).__name__}: {exc}")
    path = project / "reports/flow109/components/D66.json"
    write_json(path, result)
    result["receipt"] = _record(project, path)
    return result


def validate_final_perc(project, receipt_ref):
    project = Path(project).resolve()
    path = librelane_contract.project_path(project, receipt_ref["path"])
    record = _read(path)
    report = project / "reports/phase3/cvc_native/report.rpt"
    native = phase3_runner._parse_native_cvc_report(report.read_text())
    status = native["result"] if native["result"] in {"PASS", "FAIL"} else "NOT_MEASURED"
    return {"component_status": status, "automated_component_status": status,
            "manual_review_pending": record.get("manual_review_pending", []),
            "final_subjects": record.get("final_subjects"), "perc_receipt": receipt_ref}


def consume_default_row_completion(project, context, component):
    status = component.get("component_status", "NOT_MEASURED")
    return {"step_id": "D66", "context_sha256": context.get("context_sha256"),
            "default_row_status": status, "completed": status == "PASS",
            "reason": component.get("reason"), "flow109_acceptance": status}


def metric_measurements(project, receipt_ref):
    current = validate_final_perc(project, receipt_ref)
    return {name: {"status": "NOT_MEASURED", "reason": "Native CVC is an electrical screen; device physics is outside its scope."}
            for name in ("final_perc.final_esd_supply_topology", "final_perc.final_perc_latchup_errors")}
