"""Run the native mixed-signal candidate, merge, final and signoff owners."""
from __future__ import annotations
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

from _atomic_artefact import write_json
HERE = Path(__file__).resolve().parent
ROWS = {'M06', 'M07', 'M08', 'M09'}


class Refusal(RuntimeError):
    def __init__(self, code, detail, *, status="NOT_MEASURED"):
        self.code, self.status = code, status
        super().__init__(f"{code}: {detail}")


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise Refusal("MIXED_ROW_EVIDENCE_ABSENT_OR_INVALID", str(path)) from exc
    if not isinstance(value, dict):
        raise Refusal("MIXED_ROW_EVIDENCE_INVALID", str(path))
    return value


def _local(project, name):
    if (not isinstance(name, str) or not name or Path(name).is_absolute()
            or ".." in Path(name).parts):
        raise Refusal("MIXED_ROW_INPUT_PATH_INVALID", str(name))
    path = (project / name).resolve()
    if not path.is_relative_to(project):
        raise Refusal("MIXED_ROW_INPUT_PATH_INVALID", name)
    return path


def _bound_ref(project, value, label):
    ref = value.get('path') if isinstance(value, dict) else value
    path = Path(ref) if isinstance(ref, str) else None
    if path is None:
        raise Refusal('MIXED_ROW_REQUIRED_INPUT_ABSENT', label)
    path = path if path.is_absolute() else project / path
    path = path.resolve()
    if not path.is_file():
        raise Refusal('MIXED_ROW_REQUIRED_INPUT_ABSENT', label)
    return path


def _final_parasitic_binding(project, manifest):
    """Bind M08 to D69's validated final geometry and selected RC scene."""
    import _mixed_signal_native as native
    import flow109_final_extract as final_extract

    ref = manifest.get("final_parasitics")
    if not ref:
        raise Refusal("MIXED_ROW_FINAL_PARASITICS_ABSENT", "final parasitic report")
    try:
        final = final_extract.validate_final_parasitics(project, ref)
        contract = native.contract(project, manifest["top"])
    except Exception as exc:
        raise Refusal("MIXED_ROW_FINAL_PARASITICS_INVALID", str(exc)) from exc
    selected_spef = _local(project, (contract.get("si") or {}).get("spef", ""))
    selected_netlist = _local(project, (contract.get("digital") or {}).get("netlist", ""))
    final_spefs = final.get("final_spefs") or {}
    matched = [corner for corner, candidate in final_spefs.items()
               if _bound_ref(project, candidate, "D69 final SPEF").resolve() == selected_spef.resolve()]
    adopted = final.get("adopted_views") or {}
    if (len(matched) != 1
            or _bound_ref(project, adopted.get("netlist"), "D69 adopted netlist").resolve()
            != selected_netlist.resolve()):
        raise Refusal("MIXED_ROW_FINAL_PARASITICS_NOT_CONSUMED",
                      "M3 must consume one current D69 final SPEF and adopted netlist")
    return {"selected_corner": matched[0], "final_geometry": final["final_geometry"],
            "final_spefs": final_spefs,
            "fill_sensitive_parasitics": final.get("fill_sensitive_parasitics")}



def _m09_prerequisites(project, manifest, runtime_image=None):
    import mixed_signal_m3_run as m3
    import analog_hardmacro_check as hardmacro
    for kind in ('cosim', 'si'):
        audit = m3.audit(project, kind)
        if audit.get('verdict') != 'PASS':
            raise Refusal('MIXED_ROW_FINAL_AMS_NOT_MEASURED', str(audit),
                          status='FAIL' if audit.get('verdict') == 'FAIL' else 'NOT_MEASURED')
    final = _final_parasitic_binding(project, manifest)
    blocks = hardmacro._load_block_list(project)
    status = _read(project / 'reports/analog_native/status.json')
    rows = [row for row in status.get('steps', ()) if isinstance(row, dict) and row.get('step') == 'A19']
    if not blocks or sorted(row.get('block') for row in rows) != sorted(blocks):
        raise Refusal('MIXED_ROW_A19_POPULATION_INVALID', str(blocks))
    packages = {}
    for row in rows:
        block = row['block']
        if row.get('status') != 'PASS':
            raise Refusal('MIXED_ROW_A19_INCOMPLETE', block,
                          status='FAIL' if row.get('status') == 'FAIL' else 'NOT_MEASURED')
        signoff = _read(project / 'phase3/analog' / block / 'signoff.json')
        if (signoff.get('block') != block or signoff.get('status') != 'PASS'
                or len(signoff.get('steps') or ()) != 18 or len(signoff.get('deliverables') or {}) != 4):
            raise Refusal('MIXED_ROW_A19_PACKAGE_INVALID', block)
        packages[block] = {'deliverables': signoff['deliverables']}
    audit = hardmacro.run_audit(project)
    if not audit.passed or audit.summary.get('total_blocks') != len(blocks):
        raise Refusal('MIXED_ROW_A19_PACKAGE_INVALID', 'native hardmacro audit')
    return {'final_parasitics': final, 'a19_packages': packages}


def _command_plan(project, step, manifest, attempt):
    python = str(Path(sys.executable).resolve())
    top, pdk = manifest["top"], manifest["pdk"]
    if step in ("M06", "M08"):
        producer = [python, str(HERE / "mixed_signal_m3_run.py"), str(project),
                    "--top", top, "--container", "host", "--json", str(attempt / "producer.json")]
        gates = [
            [python, str(HERE / "mixed_signal_cosim_check.py"), str(project),
             "--require-current-production", "--json", str(attempt / "cosim.json")],
            [python, str(HERE / "mixed_signal_interface_si_check.py"), str(project),
             "--require-current-production", "--json", str(attempt / "si.json")],
        ]
    elif step == "M07":
        producer = [python, str(HERE / "mixed_signal_top_lvs_run.py"), str(project),
                    "--top", top, "--container", "host", "--pdk", pdk,
                    "--json", str(attempt / "producer.json")]
        gates = [[python, str(HERE / "mixed_signal_merge_check.py"), str(project),
                  "--json", str(attempt / "merge.json")]]
    else:
        producer = [python, str(HERE / "mixed_signal_signoff_run.py"), str(project),
                    "--top", top, "--json", str(attempt / "producer.json")]
        gates = [[python, str(HERE / "mixed_signal_signoff_check.py"), str(project),
                  "--require-current-production", "--json", str(attempt / "signoff.json")]]
    return producer, gates


def _run(argv, log):
    done = subprocess.run(argv, text=True, capture_output=True)
    log.write_text(done.stdout + done.stderr)
    return {'argv': argv, 'returncode': done.returncode, 'log': str(log)}


def _semantic_pass(project, step, manifest):
    if step in ("M06", "M08"):
        import mixed_signal_m3_run as m3
        cosim, si = m3.audit(project, "cosim"), m3.audit(project, "si")
        receipt = _read(project / m3.RECEIPT)
        scenarios = receipt.get("scenario_ids")
        required = manifest.get("required_scenarios")
        if (not isinstance(required, list) or not required or scenarios != required
                or len(set(required)) != len(required)):
            raise Refusal("MIXED_ROW_SCENARIO_POPULATION_MISMATCH", str((required, scenarios)))
        if cosim.get("verdict") != "PASS" or si.get("verdict") != "PASS":
            raise Refusal("MIXED_ROW_CURRENT_CONSUMER_REFUSED", str((cosim, si)), status="FAIL")
        evidence = {"cosim": cosim, "si": si, "scenario_ids": scenarios,
                    "geometry": str(project / "phase3/mixed_signal/top_merged.gds")}
        if step == "M08":
            evidence["final_parasitics"] = _final_parasitic_binding(project, manifest)
            evidence["final_parasitics"].pop("inputs", None)
        return evidence
    if step == "M07":
        import mixed_signal_top_lvs_run as m1
        top_lvs = _read(project / "reports/analog/mixed_signal/top_lvs.json")
        merge = _read(project / "reports/analog/mixed_signal/merge.json")
        if top_lvs.get("verdict") != "PASS" or merge.get("verdict") != "PASS":
            raise Refusal("MIXED_ROW_CURRENT_LVS_REFUSED", str((merge, top_lvs)), status="FAIL")
        _, macros, _views, _netlist, detail, _hashes = m1.current_merge_inputs(project, manifest["top"])
        population = [(item["inst"], cell) for cell, items in detail["placements"].items()
                      for item in items]
        if not macros or len(population) != len({item[0] for item in population}):
            raise Refusal("MIXED_ROW_MACRO_POPULATION_INVALID", str(population), status="FAIL")
        return {"mixed_gds": str(project / "phase3/mixed_signal/top_merged.gds"),
                "macro_instances": population, "missing_duplicate_macro_instances": 0}
    import mixed_signal_signoff_run as signoff
    audit = signoff.audit(project)
    current = signoff.verify(project)
    if audit.get("verdict") != "PASS" or audit.get("ready_for_tapeout") is not True:
        raise Refusal("MIXED_ROW_CURRENT_SIGNOFF_REFUSED", str(audit), status="FAIL")
    prerequisites = _m09_prerequisites(project, manifest)
    prerequisites.pop("inputs", None)
    return {"signoff": current, "prerequisites": prerequisites,
            "final_geometry": str(project / "phase3/mixed_signal/top_merged.gds")}


def execute(project, context):
    project = Path(project).resolve()
    step = str(context.get('step_id') or context.get('requested_step') or '')
    if step not in ROWS:
        raise ValueError('Choose the native candidate, assembly, final or signoff mixed-signal row')
    attempt = project / 'reports/native_tools/mixed' / step / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    result = {'component_status': 'NOT_MEASURED', 'commands': []}
    try:
        import mixed_signal_m3_run as m3
        manifest = dict(context)
        if not manifest.get('top'):
            from _mixed_signal_native import CONTRACT
            manifest['top'] = m3.read(project / CONTRACT)['top']
        manifest.setdefault('pdk', (context.get('config') or {}).get('PDK'))
        manifest.setdefault('required_scenarios', [row['id'] for row in m3.plan(project)])
        producer, gates = _command_plan(project, step, manifest, attempt)
        for index, argv in enumerate([producer, *gates]):
            record = _run(argv, attempt / ('command-%02d.log' % index))
            result['commands'].append(record)
            if record['returncode'] != 0:
                raise Refusal('MIXED_ROW_NATIVE_COMMAND_FAILED', str(argv),
                              status='FAIL' if record['returncode'] == 1 else 'NOT_MEASURED')
        result.update(component_status='PASS', evidence=_semantic_pass(project, step, manifest))
    except Refusal as exc:
        result.update(component_status=exc.status, reason=exc.code, detail=str(exc))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(reason='MIXED_ROW_NATIVE_UNAVAILABLE_OR_UNSUPPORTED', detail=str(exc))
    write_json(attempt / 'result.json', result)
    return result
