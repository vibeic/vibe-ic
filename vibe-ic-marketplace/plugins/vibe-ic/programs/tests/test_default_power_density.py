"""Default Step-24/25 behavioral controls, with an explicitly offline transport.

These neutral grammar fixtures test wiring and refusals. Native proof is a
separate committed-source run; no synthetic log is presented as native evidence.
"""
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R
import em_current_density_check as E
import em_peak_current_authority_check as A
from _hostpaths import require_repo

TECH = """LAYER wireA
 TYPE ROUTING ;
 WIDTH 1 ;
 THICKNESS 1 ;
 DCCURRENTDENSITY AVERAGE 1 ;
END wireA
LAYER cutA
 TYPE CUT ;
END cutA
"""
HEADER = "Node0 Layer,Node0 X location,Node0 Y location,Node1 Layer,Node1 X location,Node1 Y location,Current\n"
DHEADER = "Layer,Node0 X,Node0 Y,Node1 X,Node1 Y,Current(A),Area(um^2),J(A/um^2),Jlimit(A/um^2),Ratio,Status,Cuts,Basis\n"
PER_CUT_TECH = TECH.replace("LAYER cutA", "LAYER Via1").replace(
    " TYPE CUT ;\nEND cutA", " TYPE CUT ;\n DCCURRENTDENSITY AVERAGE 0.18 ;\nEND Via1") + """LAYER wireB
 TYPE ROUTING ;
 WIDTH 1 ;
 THICKNESS 1 ;
 DCCURRENTDENSITY AVERAGE 1 ;
END wireB
VIA neutral_cut DEFAULT
 LAYER wireA ;
 RECT -0.2 -0.2 0.2 0.2 ;
 LAYER Via1 ;
 RECT -0.13 -0.13 0.13 0.13 ;
 LAYER wireB ;
 RECT -0.2 -0.2 0.2 0.2 ;
END neutral_cut
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(tmp_path, monkeypatch, *, via=False, stress=False, direct=False,
          per_cut=False, via_current=89.52e-6, kit=None, native_change=None):
    project = tmp_path / "run"
    pnr = R._pl.pnr_dir(project)
    rpt = R._pl.reports_phase3_dir(project)
    pnr.mkdir(parents=True); rpt.mkdir(parents=True)
    layout = "UNITS DISTANCE MICRONS 1000 ;\nSPECIALNETS 1 ;\n- PWR + USE POWER + ROUTED wireA 1000 ( 0 0 ) ( 2000 0 ) ;\nEND SPECIALNETS\n"
    for name in ("unit.def", "routed.def"):
        (pnr / name).write_text(layout)
    (pnr / "constraint.sdc").write_text("set_load 0.02 [get_ports output]\n")
    extracted = R._pl.extracted_dir(project)
    extracted.mkdir(parents=True)
    (extracted / "unit.spef").write_text('*SPEF "IEEE 1481-1998"\n*DESIGN "unit"\n')
    tech_text = PER_CUT_TECH if per_cut else TECH
    tech = tmp_path / "authority.tlef"; tech.write_text(tech_text)
    stage = project / "phase3/pdk_stage"
    stage.mkdir(); (stage / "authority.tlef").write_text(tech_text)
    cell = tmp_path / "cells.lef"; cell.write_text("VERSION 5.8 ;\n")
    lib = tmp_path / "cells.lib"; lib.write_text("library(unit) {}\n")
    pdk = SimpleNamespace(name=kit or ("gf180mcuD" if per_cut else "declared-open-kit"), tech_lef=str(tech), cell_lef=str(cell),
                          liberty=str(lib), macro_lefs=[], macro_libs=[], metal_prefix="wire")
    calls = []
    if direct:
        (project / "phase3/librelane_switch.json").write_text(json.dumps({"steps": {"24": "direct"}}))
    def ir_refusal(project, top, pdk, mode, spef, written):
        calls.append("librelane_ir")
        (rpt / R._LL_IR_RECORD).write_text(json.dumps({
            "producer": "librelane:OpenROAD.IRDropReport", "mode": mode,
            "judgment": {"verdict": "NOT_MEASURED", "reasons": ["offline fixture has no native LibreLane state"]}}))
    monkeypatch.setattr(R, "_librelane_step24_record", ir_refusal)
    monkeypatch.setattr(R, "_to_container_path", lambda path, container: path)
    monkeypatch.setattr(R, "_sta_extra_liberties", lambda *args: [])
    monkeypatch.setattr(R._ppa_presweep, "finalize", lambda *args: None)
    current = 0.002 if stress else 0.000001
    def offline_transport(container, cmd, **kwargs):
        tcl = (rpt / "ir_em_unit.tcl").read_text()
        calls.append(tcl)
        (rpt / "em_segments_PWR.csv").write_text(HEADER + f"wireA,0,0,wireA,1,0,{current}\n" +
                                                  (f"wireA,0,0,wireB,0,0,{via_current}\n" if per_cut else
                                                   "wireA,0,0,wireB,0,0,0.000001\n" if via else ""))
        (rpt / "em_pg_geometry.tsv").write_text("net\tlayer\tx0_um\ty0_um\tx1_um\ty1_um\tsource\nPWR\twireA\t0\t-0.5\t2\t0.5\tspecial_wire\n")
        native = "check_current_density -net PWR" in tcl
        if native:
            (rpt / "em_openroad_density_PWR.csv").write_text(DHEADER +
                f"wireA,0,0,1,0,{current},1,{current},0.0009,{current / 0.0009:.3f},{'VIOLATED' if stress else 'OK'},0,AREAL\n" +
                ("cutA,0,0,0,0,0.000001,1,0.000001,0,0,NO_LIMIT,1,NO_LIMIT\n" if via else ""))
            if per_cut:
                limits = (rpt / "em_openroad_limits.txt").read_text().splitlines()
                selected = next(line.split() for line in limits if line.startswith("Via1 "))
                basis = "PER_CUT" if selected[1] == "per_cut" else "AREAL"
                limit = float(selected[-1]); cuts = 8; area = cuts * 0.26 ** 2
                density = via_current / (cuts if basis == "PER_CUT" else area)
                if native_change == "zero_cuts":
                    cuts = 0
                elif native_change == "wrong_area":
                    area *= 2
                elif native_change == "wrong_density":
                    density *= 1.17
                elif native_change == "unknown_cut":
                    selected[0] = "unknown_cut"
                elif native_change == "wrong_basis":
                    basis = "AREAL"
                with (rpt / "em_openroad_density_PWR.csv").open("a") as stream:
                    stream.write(f"{selected[0]},0,0,0,0,{via_current:.3e},{area:.4e},"
                                 f"{density:.3e},{limit:.3e},{density / limit:.6f},"
                                 f"{'VIOLATED' if density > limit else 'OK'},{cuts},{basis}\n")
        markers = []
        for stage, role, path in re.findall(r'EM_BOUND_(BEFORE|AFTER) (\w+) \[lindex \[exec sha256sum (.*?)\] 0\]', tcl):
            markers.append(f"EM_BOUND_{stage} {role} {digest(Path(path.strip('{}')))}")
        if native:
            markers += ["EM_DENSITY_DONE PWR", "EM_BOUND_OUTPUT em_openroad_density_PWR.csv " + digest(rpt / "em_openroad_density_PWR.csv")]
        log = ("\n".join(markers) + "\n=== PSM_NET PWR ===\n"
               "[INFO PSM-0040] All shapes on net PWR are connected.\n"
               "Net : PWR\nTotal power : 2 W\nSupply voltage : 5 V\n"
               f"Worstcase IR drop: {0.781 if stress else 0.00001} V\nMaximum current : {max(current, via_current) if per_cut else current} A\n"
               "=== EM_POWER_BASIS ===\nTotal 0 0 0 2 100%\n=== EM_POWER_BASIS_END ===\n"
               "PSM_SOURCE_MODEL: promoted_supply_pins_excluded=0 placed_pads=0\n")
        (rpt / "ir_em.log").write_text(log)
        return 0, log, ""
    monkeypatch.setattr(R, "_docker_exec", offline_transport)
    notes = []
    assert R._emit_ir_em_reports(project, "unit", pdk, "offline", rpt / "ir_drop.rpt", rpt / "em.rpt", notes) == (True, True)
    return project, pdk, calls


def authority(project, pdk):
    return A.evaluate(project, None, Path(pdk.tech_lef), 0.1)


def test_default_invokes_native_checker_and_existing_librelane_route(tmp_path, monkeypatch):
    project, pdk, calls = build(tmp_path, monkeypatch)
    commands = [value for value in calls if "check_current_density -net PWR" in value]
    assert len(commands) == 1, calls
    assert calls.count("librelane_ir") == 1, calls
    doc = json.loads((project / "reports/phase3/em_openroad_density.json").read_text())
    assert doc["mode"] == "direct"
    assert doc["nets"]["PWR"]["checked"] == 1
    assert authority(project, pdk)[0] == "INCOMPLETE"


@pytest.mark.parametrize("subject", ["DEF", "SDC", "PDK", "CSV", "REPORT", "EXECUTION", "CONSUMER", "AUTHORITY", "LIMIT", "VIA_SUBSTITUTION", "OUTPUT_BINDING", "BASIS"])
def test_current_gate_refuses_each_reverse(tmp_path, monkeypatch, subject):
    project, pdk, _ = build(tmp_path, monkeypatch, direct=True)
    assert authority(project, pdk)[0] == "PASS"
    rpt = project / "reports/phase3"
    doc_path = rpt / "em_openroad_density.json"
    doc = json.loads(doc_path.read_text())
    if subject in ("DEF", "SDC", "PDK", "CSV", "REPORT", "AUTHORITY"):
        target = {"DEF": R._pl.pnr_dir(project) / "unit.def", "SDC": R._pl.pnr_dir(project) / "constraint.sdc",
                  "PDK": Path(pdk.tech_lef), "CSV": rpt / "em_openroad_density_PWR.csv",
                  "REPORT": rpt / "em.rpt", "AUTHORITY": rpt / "em_native_authority.tlef"}[subject]
        # On base there is no staged native authority; change its selected
        # actual authority instead, so this remains a VALUE control.
        if subject in ("AUTHORITY", "CSV") and not target.exists():
            target = Path(pdk.tech_lef)
        target.write_text(target.read_text() + "\n# changed bytes\n")
    elif subject == "EXECUTION":
        doc_path.unlink()
    elif subject == "CONSUMER":
        doc["source_identity"] = {"em_peak_current_authority_check.py": "removed"}
    elif subject in ("LIMIT", "VIA_SUBSTITUTION"):
        limit = rpt / "em_openroad_limits.txt"
        limit.write_text("wireA 999\n" if subject == "LIMIT" else "wireA 0.0009\ncutA 0.0009\n")
        if "outputs" in doc:
            doc["outputs"][str(limit.relative_to(project))] = digest(limit)
    elif subject == "OUTPUT_BINDING":
        doc.get("outputs", {}).pop("reports/phase3/em.rpt", None)
    elif subject == "BASIS":
        doc["power_basis"] = {"id": "another-power-basis"}
    if subject not in ("EXECUTION", "DEF", "SDC", "PDK", "CSV", "REPORT", "AUTHORITY"):
        doc_path.write_text(json.dumps(doc))
    verdict, rep = authority(project, pdk)
    assert verdict == "INCOMPLETE", rep


def test_cli_rejects_fake_jmax_override(tmp_path, monkeypatch):
    project, _, _ = build(tmp_path, monkeypatch, direct=True)
    fake = tmp_path / "fake.json"
    fake.write_text(json.dumps({"layers": {"wireA": {"kind": "routing", "thickness_um": 1, "jmax_mA_per_um": 999}}}))
    verdict, rep = A.evaluate(project, fake, None, 0.1)
    assert verdict == "INCOMPLETE", rep


def test_measured_stress_fail_precedes_unmeasured_vias_and_primary(tmp_path, monkeypatch):
    project, pdk, _ = build(tmp_path, monkeypatch, via=True, stress=True)
    verdict, rep = authority(project, pdk)
    assert verdict == "FAIL", rep
    assert rep["jmax_screen"]["summary"]["segments_unscreened"] == 1
    assert json.loads((project / "reports/phase3/ir_drop.json").read_text())["verdict"] == "FAIL"


def test_missing_via_limit_never_borrows_wire_authority(tmp_path, monkeypatch):
    project, pdk, _ = build(tmp_path, monkeypatch, via=True)
    verdict, rep = authority(project, pdk)
    assert verdict == "INCOMPLETE", rep
    assert rep["jmax_screen"]["summary"]["segments_screened"] == 1
    assert rep["jmax_screen"]["summary"]["segments_unscreened"] == 1


def test_real_canonical_row_runs_existing_consumer(tmp_path, monkeypatch):
    import flow_compliance_check as F
    import yaml
    project, _, _ = build(tmp_path, monkeypatch)
    row_path = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "phase1_phase2_phase3.yaml")
    row = next(row for row in yaml.safe_load(row_path.read_text())["steps"] if str(row["id"]) == "25")
    clause = next(clause for clause in row["gate"]["all_of"] if clause.get("program_exit_zero", "").startswith("em_peak_current_authority_check "))
    result = F.check_step(project, {"id": "25", "name": row["name"],
                                   "gate": {"all_of": [clause]}}, {})
    assert result.status != "PASS", result


@pytest.mark.parametrize("removed", [False, True])
def test_existing_ir_gate_refuses_missing_or_unadopted_primary(tmp_path, monkeypatch, removed):
    import ir_drop_report_check as I
    project, _, _ = build(tmp_path, monkeypatch)
    if removed:
        (project / "reports/phase3" / R._LL_IR_RECORD).unlink()
    assert I._run_and_emit([str(project), "--json", str(project / "reports/phase3/ir_drop_signoff.json")]) == 2


def test_existing_ir_gate_preserves_bound_stress_failure(tmp_path, monkeypatch):
    import ir_drop_report_check as I
    project, _, _ = build(tmp_path, monkeypatch, via=True, stress=True)
    assert I._run_and_emit([str(project)]) == 1


@pytest.mark.parametrize("current,expected", [
    (89.52e-6, "PASS"), (0.00132, "FAIL"), (0.001296, "FAIL"),
], ids=["recorded_8_cut_current", "over_limit", "margin_boundary"])
def test_selected_per_cut_authority_reaches_native_and_both_consumers(
        tmp_path, monkeypatch, current, expected):
    project, pdk, _ = build(tmp_path, monkeypatch, direct=True,
                            per_cut=True, via_current=current)
    rpt = project / "reports/phase3"
    limits = (rpt / "em_openroad_limits.txt").read_text()
    assert "Via1 per_cut 0.000162\n" in limits  # 0.18 mA/cut, one 10% margin.
    record = json.loads((rpt / "em_openroad_density.json").read_text())
    rule = record["authority"]["per_cut"]
    registry = json.loads(Path(E.__file__).with_name("pdk_registry.json").read_text())
    selected = next(row for row in registry["pdks"] if row["name"] == pdk.name)
    assert rule["source"] == selected["em_current_limits"]["source"]
    assert rule["temperature_c"] == 125
    assert rule["layers"]["via1"]["jmax_A_per_cut"] == pytest.approx(0.00018)
    snapshot = project / record["authority"]["per_cut_snapshot"]
    assert record["inputs"]["per_cut_authority"]["sha256"] == digest(snapshot)
    native = E.validate_native_density(project)
    assert native["valid"], native
    result, density = E.evaluate(rpt / "em_segments.csv", None, Path(pdk.tech_lef),
                                  0.1, 2.0, None, 20,
                                  def_path=R._pl.pnr_dir(project) / "routed.def",
                                  pg_geometry_path=rpt / "em_pg_geometry.tsv")
    assert result == expected, density
    result, report = authority(project, pdk)
    assert result == expected, report
    assert report["jmax_screen"]["summary"]["segments_screened"] == 2
    assert report["jmax_screen"]["summary"]["segments_unscreened"] == 0
    via = next(row for row in density["worst_segments"] if row["layer"] == "Via1")
    assert via["basis"] == "per_cut" and via["cuts"] == 8
    assert via["value_A_per_cut"] == pytest.approx(current / 8)
    if current == 0.001296:
        # The tool uses strict >; the existing retained >= boundary still FAILs.
        assert native["verdict"] == "PASS"


def test_unknown_pdk_keeps_literal_lef_areal_fallback(tmp_path, monkeypatch):
    project, pdk, _ = build(tmp_path, monkeypatch, direct=True,
                            per_cut=True, kit="unknown-open-kit")
    rpt = project / "reports/phase3"
    assert "Via1 0.000162\n" in (rpt / "em_openroad_limits.txt").read_text()
    assert "per_cut" not in (rpt / "em_openroad_limits.txt").read_text()
    native = E.validate_native_density(project)
    assert native["valid"] and native["verdict"] == "FAIL", native
    assert native.get("per_cut_authority") is None
    result, report = authority(project, pdk)
    assert result == "FAIL", report


@pytest.mark.parametrize("change", ["zero_cuts", "wrong_area", "wrong_density",
                                      "unknown_cut", "wrong_basis"])
def test_bound_per_cut_native_geometry_cannot_be_substituted(tmp_path, monkeypatch, change):
    project, pdk, _ = build(tmp_path, monkeypatch, direct=True,
                            per_cut=True, native_change=change)
    native = E.validate_native_density(project)
    assert native["valid"] is False, native
    result, report = authority(project, pdk)
    assert result == "INCOMPLETE", report


@pytest.mark.parametrize("changed", ["source", "snapshot", "missing_snapshot"])
def test_per_cut_authority_requires_current_invocation_binding(tmp_path, monkeypatch, changed):
    project, pdk, _ = build(tmp_path, monkeypatch, direct=True, per_cut=True)
    path = project / "reports/phase3/em_openroad_density.json"
    doc = json.loads(path.read_text())
    if changed == "source":
        doc["authority"].setdefault("per_cut", {}).setdefault("source", {})["sha256"] = "0" * 64
        path.write_text(json.dumps(doc))
    else:
        snapshot = project / doc["authority"].get(
            "per_cut_snapshot", "reports/phase3/em_native_per_cut_authority.json")
        if changed == "missing_snapshot":
            snapshot.unlink(missing_ok=True)
        else:
            snapshot.write_text("{}\n")
    result, report = authority(project, pdk)
    assert result == "INCOMPLETE", report


def test_selected_rule_refuses_unsupported_cut_dimensions(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "PER_CUT_TECH", PER_CUT_TECH.replace(
        "RECT -0.13 -0.13 0.13 0.13", "RECT -0.14 -0.14 0.14 0.14"))
    with pytest.raises(ValueError, match="cut geometry is unsupported"):
        build(tmp_path, monkeypatch, direct=True, per_cut=True)


@pytest.mark.parametrize('change,expected', [('digest_only', True), ('other_pdk', True),
                                           ('value', False), ('source', False), ('temperature', False)])
def test_native_per_cut_authority_binds_cited_content_not_registry_digest(tmp_path, monkeypatch, change, expected):
    from programs.tests._hostpaths import require_repo
    project, pdk, _ = build(tmp_path, monkeypatch, direct=True, per_cut=True)
    registry = json.loads(require_repo(
        'vibe-ic-marketplace/plugins/vibe-ic/programs/pdk_registry.json').read_text())
    selected = next(row for row in registry['pdks'] if row['name'] == pdk.name)
    if change == 'digest_only':
        registry['unrelated_description'] = 'changed outside the cited per-cut authority'
    elif change == 'other_pdk':
        next(row for row in registry['pdks'] if row['name'] != pdk.name)['unrelated_note'] = 'changed'
    elif change == 'value':
        layer = next(iter(selected['em_current_limits']['layers'].values()))
        layer['jmax_mA_per_cut'] *= 1.01
    elif change == 'source':
        selected['em_current_limits']['source']['section'] += ' changed'
    else:
        selected['em_current_limits']['temperature_c'] -= 1
    current = tmp_path / 'current-registry.json'
    current.write_text(json.dumps(registry))
    monkeypatch.setattr(E, '_PDK_REGISTRY', current)
    observed = E.validate_native_density(project)
    assert observed['valid'] == expected, observed
    assert authority(project, pdk)[0] == ('PASS' if expected else 'INCOMPLETE')
