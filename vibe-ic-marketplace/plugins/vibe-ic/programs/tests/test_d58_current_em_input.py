"""D58 consumes the already-validated current D57/STA physical subject."""
import hashlib
import io
import json
import os
import re
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

import em_current_density_check as E
import em_peak_current_authority_check as A
import execution_backend_producers as B
import flow_declared_producer_run as FDP
import flow_compliance_check as FC
import phase3_one_shot_runner as R
from test_default_step24_current_adoption import _external_current_primary
from test_default_step25_em_owner import (DHEADER, HEADER, TECH, _ready,
                                          _transport_fixture)
from test_pad_connected_pdn_ring import _pdk


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _supply_basis(folder):
    rows = {
        "PWR": [{"pad": "power_pad", "bterm": "PWR", "layer": "met5",
                 "x": 10.0, "y": 20.0, "size": 4.0}],
    }
    volts = {"PWR": 5.0}
    result = {}
    folder.mkdir(parents=True, exist_ok=True)
    for net, values in rows.items():
        content = "".join(
            f"{r['x']:.4f},{r['y']:.4f},{r['size']:.4f},{volts[net]:g}\n"
            for r in values)
        path = folder / f"{net}.vsrc"
        path.write_text(content)
        result[net] = {"path": str(path), "voltage_v": volts[net],
                       "sha256": _sha(path)}
    return {"model": "declared supply pads through VSRC_LOC_FILES; source control",
            "vsrc": result}


def _run_step25(project, tmp_path, monkeypatch, pdk, calls):
    def controlled_em(*_args, **kwargs):
        calls.append(kwargs.get("layout_basis"))
        return True, True

    monkeypatch.setattr(B, "_parameters",
                        lambda *_a, **_k: (R, None, pdk, "SOURCE_CONTROL_ONLY"))
    monkeypatch.setattr(R, "_emit_ir_em_reports", controlled_em)
    monkeypatch.setattr(R, "_emit_em_current_authority", lambda *_a, **_k: None)
    return B.produce_signoff(project, {
        "step_id": "25", "top": "neutral", "pdk_root": str(tmp_path),
        "image_id": "SOURCE_CONTROL_ONLY", "execution_mode": "default",
    })


def test_default_step25_hands_exact_current_owner_views_to_native_em(
        tmp_path, monkeypatch):
    project, _, selected, paths, _ = _external_current_primary(tmp_path, monkeypatch)
    legacy = project / "phase3/stage3/pnr/neutral.def"
    legacy.unlink()
    calls = []
    result = _run_step25(project, tmp_path, monkeypatch, _pdk(tmp_path, ring=None), calls)
    assert result["verdict"] == "PASS"
    assert len(calls) == 1
    basis = calls[0]
    observed_source = "current-owner" if basis is not None else "legacy-default"
    assert observed_source == "current-owner"
    observed_paths = {role: Path(basis[role]["path"]) for role in
                      ("odb", "def", "netlist", "sdc", "spef")}
    expected_paths = {
        "odb": paths["odb"], "def": paths["def"], "netlist": paths["nl"],
        "sdc": paths["sdc"], "spef": paths["spef"],
    }
    assert observed_paths == expected_paths
    assert all(basis[role]["sha256"] == selected["records"][role]["sha256"]
               for role in ("odb", "def", "sdc", "spef"))
    assert basis["netlist"]["sha256"] == selected["records"]["netlist"]["sha256"]
    assert set(basis["supply_sources"]["vsrc"]) == {"VDD", "VSS"}
    assert basis["supply_sources"]["vsrc"]["VDD"]["voltage_v"] == 5.0
    assert basis["supply_sources"]["vsrc"]["VSS"]["voltage_v"] == 0.0
    assert not legacy.exists()


@pytest.mark.parametrize("damage", ["missing", "changed", "wrong_role", "symlink"])
def test_default_step25_refuses_damaged_current_owner_without_legacy_fallback(
        tmp_path, monkeypatch, damage):
    project, report, selected, paths, _ = _external_current_primary(tmp_path, monkeypatch)
    legacy = project / "phase3/stage3/pnr/neutral.def"
    if damage == "missing":
        paths["def"].unlink()
    elif damage == "changed":
        paths["def"].write_text(paths["def"].read_text() + "changed\n")
    elif damage == "wrong_role":
        doc = json.loads(report.read_text())
        doc["inputs"]["def"] = dict(selected["records"]["netlist"])
        report.write_text(json.dumps(doc))
    else:
        text = paths["def"].read_text()
        paths["def"].unlink()
        target = tmp_path / "foreign-final.def"
        target.write_text(text)
        paths["def"].symlink_to(target)
    calls = []
    result = _run_step25(project, tmp_path, monkeypatch, _pdk(tmp_path, ring=None), calls)
    assert result["verdict"] == "NOT_MEASURED"
    assert calls == []
    assert legacy.is_file(), "a present invalid owner must not select the legacy DEF"


def test_default_step25_preserves_primary_measured_fail_after_current_selection(
        tmp_path, monkeypatch):
    project, _, _, _, _ = _external_current_primary(tmp_path, monkeypatch, "native_fail")
    calls = []
    result = _run_step25(project, tmp_path, monkeypatch, _pdk(tmp_path, ring=None), calls)
    assert len(calls) == 1
    assert result["verdict"] == "FAIL"
    assert "current Step-24 IR measurement failed" in result["detail"]


@pytest.mark.parametrize("case,ir_verdict", [
    ("current", "PASS"), ("native_fail", "FAIL"),
])
def test_missing_em_source_model_does_not_revoke_d57_but_stops_d58(
        tmp_path, monkeypatch, case, ir_verdict):
    project, report, _, _, _ = _external_current_primary(
        tmp_path, monkeypatch, case)
    doc = json.loads(report.read_text())
    doc["record"]["source_model"] = "PSM default supply BTerms"
    doc["record"].pop("sources", None)
    doc["record"]["cross_check"].pop("vsrc", None)
    report.write_text(json.dumps(doc))
    ir = E.validate_primary_ir(project)
    assert ir["valid"] is True, ir
    assert ir["verdict"] == ir_verdict
    assert "supply_sources" not in ir["current_em_basis"]
    calls = []
    em = _run_step25(project, tmp_path, monkeypatch,
                     _pdk(tmp_path, ring=None), calls)
    assert em["verdict"] == "NOT_MEASURED"
    assert "VSRC" in em["detail"]
    assert calls == []


@pytest.mark.parametrize("damage", [
    "missing", "changed", "symlink", "wrong_role", "wrong_model",
])
def test_default_step25_refuses_changed_current_vsrc_without_bterm_fallback(
        tmp_path, monkeypatch, damage):
    project, report, _, _, _ = _external_current_primary(tmp_path, monkeypatch)
    doc = json.loads(report.read_text())
    paths = {net: Path(path) for net, path in
             doc["record"]["cross_check"]["vsrc"].items()}
    if damage == "missing":
        paths["VDD"].unlink()
    elif damage == "changed":
        paths["VDD"].write_text(paths["VDD"].read_text() + "1,1,1,5\n")
    elif damage == "symlink":
        contents = paths["VDD"].read_text()
        paths["VDD"].unlink()
        foreign = tmp_path / "foreign-vdd.vsrc"
        foreign.write_text(contents)
        paths["VDD"].symlink_to(foreign)
    elif damage == "wrong_role":
        doc["record"]["cross_check"]["vsrc"] = {
            "VDD": str(paths["VSS"]), "VSS": str(paths["VDD"])}
        report.write_text(json.dumps(doc))
    else:
        doc["record"]["source_model"] = "PSM default promoted BTerms"
        report.write_text(json.dumps(doc))
    calls = []
    result = _run_step25(project, tmp_path, monkeypatch,
                         _pdk(tmp_path, ring=None), calls)
    assert result["verdict"] == "NOT_MEASURED"
    assert calls == []
    assert "VSRC" in result["detail"] or "native basis changed" in result["detail"]


def test_default_step25_without_current_owner_keeps_legacy_em_basis(
        tmp_path, monkeypatch):
    project, pdk, _, _ = _ready(tmp_path, monkeypatch)
    calls = []
    result = _run_step25(project, tmp_path, monkeypatch, pdk, calls)
    assert result["verdict"] == "PASS"
    assert calls == [None]


@pytest.mark.parametrize("damage", [
    "changed", "missing", "symlink", "changed_tech", "changed_model",
])
def test_native_em_current_basis_refuses_before_tool(tmp_path, monkeypatch, damage):
    project, pdk, calls = _transport_fixture(tmp_path, monkeypatch, direct=True)
    switch = project / "phase3/librelane_switch.json"
    switch.write_text(json.dumps({"steps": {"24": "direct", "25": "direct"}}))
    pnr = R._pl.pnr_dir(project)
    current = tmp_path / "current-owner"
    current.mkdir()
    source_def = pnr / "unit.def"
    paths = {
        "def": current / "final.def", "odb": current / "final.odb",
        "netlist": current / "final.v", "sdc": current / "final.sdc",
        "spef": current / "final.spef",
    }
    paths["def"].write_bytes(source_def.read_bytes())
    paths["odb"].write_text("current native ODB\n")
    paths["netlist"].write_text("module unit; endmodule\n")
    paths["sdc"].write_text("set_load 0.02 [get_ports output]\n")
    paths["spef"].write_text('*SPEF "IEEE 1481-1998"\n*DESIGN "unit"\n')
    source_def.unlink()
    basis = {role: {"path": str(path), "sha256": _sha(path)}
             for role, path in paths.items()}
    basis["tech_lef"] = {"path": str(pdk.tech_lef), "sha256": _sha(pdk.tech_lef)}
    basis["liberties"] = [{"path": str(pdk.liberty), "sha256": _sha(pdk.liberty)}]
    basis["supply_sources"] = _supply_basis(current / "vsrc")
    target = {"changed_tech": Path(pdk.tech_lef),
              "changed_model": Path(pdk.liberty)}.get(damage, paths["def"])
    if damage == "changed":
        target.write_text(target.read_text() + "changed\n")
    elif damage == "missing":
        target.unlink()
    else:
        text = target.read_text()
        target.unlink()
        foreign = tmp_path / "foreign.def"
        foreign.write_text(text)
        target.symlink_to(foreign)
    notes = []
    assert R._emit_ir_em_reports(
        project, "unit", pdk, "offline",
        project / "reports/phase3/ir_drop.rpt",
        project / "reports/phase3/em.rpt", notes,
        em_only=True, layout_basis=basis) == (False, False)
    assert calls == []
    assert any("basis changed" in note for note in notes)


def test_native_em_command_reads_exact_current_odb_without_legacy_def(
        tmp_path, monkeypatch):
    project, pdk, calls = _transport_fixture(tmp_path, monkeypatch, direct=True)
    switch = project / "phase3/librelane_switch.json"
    switch.write_text(json.dumps({"steps": {"24": "direct", "25": "direct"}}))
    pnr = R._pl.pnr_dir(project)
    current = tmp_path / "current-owner"
    current.mkdir()
    paths = {
        "def": current / "final.def", "odb": current / "final.odb",
        "netlist": current / "final.v", "sdc": current / "final.sdc",
        "spef": current / "final.spef",
    }
    paths["def"].write_bytes((pnr / "unit.def").read_bytes())
    paths["odb"].write_text("current native ODB\n")
    paths["netlist"].write_text("module unit; endmodule\n")
    paths["sdc"].write_text("set_load 0.02 [get_ports output]\n")
    paths["spef"].write_text('*SPEF "IEEE 1481-1998"\n*DESIGN "unit"\n')
    (pnr / "unit.def").unlink()
    basis = {role: {"path": str(path), "sha256": _sha(path)}
             for role, path in paths.items()}
    basis["tech_lef"] = {"path": str(pdk.tech_lef), "sha256": _sha(pdk.tech_lef)}
    basis["liberties"] = [{"path": str(pdk.liberty), "sha256": _sha(pdk.liberty)}]
    basis["supply_sources"] = _supply_basis(current / "vsrc")
    notes = []
    assert R._emit_ir_em_reports(
        project, "unit", pdk, "offline",
        project / "reports/phase3/ir_drop.rpt",
        project / "reports/phase3/em.rpt", notes,
        em_only=True, layout_basis=basis) == (True, True)
    command = next(call for call in calls if "check_current_density -net PWR" in call)
    assert f"read_db {paths['odb']}" in command
    assert "read_def" not in command
    assert "analyze_power_grid -net PWR -vsrc " in command
    assert str(current / "vsrc/PWR.vsrc") in command
    density = json.loads((project / "reports/phase3/em_openroad_density.json").read_text())
    assert density["inputs"]["layout"]["sha256"] == _sha(paths["def"])
    assert density["inputs"]["librelane_odb"]["sha256"] == _sha(paths["odb"])
    assert density["inputs"]["netlist"]["sha256"] == _sha(paths["netlist"])
    for net in ("PWR",):
        assert density["inputs"][f"vsrc_{net}"]["sha256"] == basis["supply_sources"]["vsrc"][net]["sha256"]
        assert f"EM_BOUND_BEFORE vsrc_{net} " in command
        assert f"EM_BOUND_AFTER vsrc_{net} " in command
    assert density["source_model"] == basis["supply_sources"]["model"]
    assert E.validate_native_density(project)["valid"] is True
    assert not (pnr / "unit.def").exists()


def _install_two_rail_transport(project, monkeypatch):
    rpt = project / "reports/phase3"
    calls = []
    monkeypatch.setattr(R, "_to_container_path", lambda path, _container: path)
    monkeypatch.setattr(R, "_sta_extra_liberties", lambda *_args: [])
    monkeypatch.setattr(R._ppa_presweep, "finalize", lambda *_args: None)
    monkeypatch.setattr(R, "_discover_power_nets",
                        lambda _path: (["VDD"], ["VSS"]))

    def transport(_container, _cmd, **_kwargs):
        tcl = (rpt / "ir_em_neutral.tcl").read_text()
        calls.append(tcl)
        markers = []
        for stage, role, path in re.findall(
                r'EM_BOUND_(BEFORE|AFTER) (\w+) \[lindex \[exec sha256sum (.*?)\] 0\]',
                tcl):
            markers.append(f"EM_BOUND_{stage} {role} {_sha(Path(path.strip('{}')))}")
        geometry = ["net\tlayer\tx0_um\ty0_um\tx1_um\ty1_um\tsource"]
        log_rows = []
        for index, net in enumerate(("VDD", "VSS")):
            current = 0.000001 + index * 0.0000001
            (rpt / f"em_segments_{net}.csv").write_text(
                HEADER + f"wireA,0,0,wireA,1,0,{current}\n")
            density = rpt / f"em_openroad_density_{net}.csv"
            density.write_text(DHEADER +
                f"wireA,0,0,1,0,{current},1,{current},0.0009,{current / 0.0009:.3f},OK,0,AREAL\n")
            markers += [f"EM_DENSITY_DONE {net}",
                        f"EM_BOUND_OUTPUT {density.name} {_sha(density)}"]
            geometry.append(f"{net}\twireA\t0\t-0.5\t2\t0.5\tspecial_wire")
            log_rows += [f"=== PSM_NET {net} ===",
                         f"[INFO PSM-0040] All shapes on net {net} are connected.",
                         f"Net : {net}", "Total power : 2 W", "Supply voltage : 5 V",
                         "Worstcase IR drop: 0.00001 V",
                         f"Maximum current : {current} A"]
        (rpt / "em_pg_geometry.tsv").write_text("\n".join(geometry) + "\n")
        log = "\n".join([*markers, *log_rows,
            "=== EM_POWER_BASIS ===", "Total 0 0 0 2 100%",
            "=== EM_POWER_BASIS_END ===",
            "PSM_SOURCE_MODEL: promoted_supply_pins_excluded=0 placed_pads=727"]) + "\n"
        (rpt / "ir_em.log").write_text(log)
        return 0, log, ""

    monkeypatch.setattr(R, "_docker_exec", transport)
    return calls


def _carry_real_authority_in_process(monkeypatch):
    """Keep the real declared checker while retaining the fixture owner stub.

    The current-owner fixture deliberately substitutes only its source-side
    owner resolver.  The normal row otherwise launches declared checkers in a
    child, where that source fixture cannot exist.  Carry this one command
    through the same ``main`` entry point in-process; every other declared
    command keeps the production subprocess path.
    """
    real_run = subprocess.run
    real_supervised = FC._watchdog.run_host_supervised

    def authority(argv, cwd):
        script_index = next(index for index, part in enumerate(argv)
                            if str(part).endswith("em_peak_current_authority_check.py"))
        before = Path.cwd()
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            os.chdir(cwd)
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = A.main([str(part) for part in argv[script_index + 1:]])
        finally:
            os.chdir(before)
        return rc, stdout.getvalue(), stderr.getvalue()

    def run(argv, **kwargs):
        if not any(str(part).endswith("em_peak_current_authority_check.py")
                   for part in argv):
            return real_run(argv, **kwargs)
        rc, out, err = authority(argv, kwargs["cwd"])
        return subprocess.CompletedProcess(argv, rc, out, err)

    def supervised(argv, **kwargs):
        if not any(str(part).endswith("em_peak_current_authority_check.py")
                   for part in argv):
            return real_supervised(argv, **kwargs)
        rc, out, err = authority(argv, kwargs["cwd"])
        return FC._watchdog.SupervisedResult(
            rc, out, err, "natural", scope={"fixture": "in_process"})

    monkeypatch.setattr(FDP.subprocess, "run", run)
    monkeypatch.setattr(FC._watchdog, "run_host_supervised", supervised)


def test_current_vsrc_producer_validates_from_absolute_and_project_dot(
        tmp_path, monkeypatch):
    project, report, _, _, _ = _external_current_primary(tmp_path, monkeypatch)
    pdk = _pdk(tmp_path, ring=None)
    doc = json.loads(report.read_text())
    doc["record"]["def_sha256"] = doc["inputs"]["def"]["sha256"]
    tech = Path(doc["native_basis"]["tech_lef"]["path"])
    tech.write_text(TECH)
    pdk.tech_lef = str(tech)
    doc["native_basis"]["tech_lef"]["sha256"] = _sha(tech)
    doc["artifacts"][str(tech.relative_to(project))] = _sha(tech)
    report.write_text(json.dumps(doc))
    (project / "phase3/librelane_switch.json").write_text(json.dumps(
        {"steps": {"24": "dual", "25": "direct"}}))
    calls = _install_two_rail_transport(project, monkeypatch)
    _carry_real_authority_in_process(monkeypatch)
    monkeypatch.setattr(B, "_parameters",
                        lambda *_a, **_k: (R, None, pdk, "offline"))
    legacy = R._pl.pnr_dir(project)
    (legacy / "neutral.def").unlink()
    row = R._default_pnr_rows(project, "neutral", pdk, "offline", ["25"])
    assert row.status == "PASS", row.detail
    assert len(calls) == 1
    absolute = E.validate_native_density(project)
    assert absolute["valid"] is True, absolute
    authority = json.loads(
        (project / "reports/phase3/em_current_authority.json").read_text())
    assert authority["verdict"] == "PASS", authority
    assert authority["jmax_screen"]["summary"]["odb_pg_geometry_width_uses"] > 0
    assert not (legacy / "neutral.def").exists()
    monkeypatch.chdir(project)
    lexical_dot = E.validate_native_density(Path("."))
    assert lexical_dot["valid"] is True, lexical_dot
    assert lexical_dot["verdict"] == absolute["verdict"]
    dot_authority = A.jmax_tier(
        Path("."), None, Path(absolute["authority"]), E._DEFAULT_MARGIN)
    assert dot_authority["verdict"] == "PASS", dot_authority


def test_current_external_subject_same_bytes_wrong_owner_refuses(
        tmp_path, monkeypatch):
    test_current_vsrc_producer_validates_from_absolute_and_project_dot(
        tmp_path, monkeypatch)
    project = Path.cwd()
    rpt = project / "reports/phase3"
    density_path = rpt / "em_openroad_density.json"
    density = json.loads(density_path.read_text())
    subject_path = rpt / "em.json"
    subject = json.loads(subject_path.read_text())
    foreign = tmp_path / "foreign-final.def"
    foreign.write_bytes(Path(subject["subject_def"]).read_bytes())
    subject["subject_def"] = str(foreign)
    subject_path.write_text(json.dumps(subject))
    density["outputs"]["reports/phase3/em.json"] = _sha(subject_path)
    density_path.write_text(json.dumps(density))
    result = E.validate_native_density(Path("."))
    assert result["valid"] is False
    assert result["reason"] == "DEF or power basis disagrees with the measurement"
    refused = A.jmax_tier(
        Path("."), None, Path(density["authority"]["snapshot"]),
        E._DEFAULT_MARGIN)
    assert refused["verdict"] == "NOT_MEASURED"
    assert refused["native_density"]["valid"] is False


@pytest.mark.parametrize("damage", ["changed_geometry", "missing_geometry"])
def test_current_external_geometry_reader_refuses_damaged_evidence(
        tmp_path, monkeypatch, damage):
    test_current_vsrc_producer_validates_from_absolute_and_project_dot(
        tmp_path, monkeypatch)
    project = Path.cwd()
    density_path = project / "reports/phase3/em_openroad_density.json"
    density = json.loads(density_path.read_text())
    geometry = project / "reports/phase3/em_pg_geometry.tsv"
    if damage == "changed_geometry":
        geometry.write_text(geometry.read_text() + "VDD\twireA\t9\t9\t10\t9\tforeign\n")
    elif damage == "missing_geometry":
        geometry.unlink()
    refused = A.jmax_tier(
        Path("."), None, Path(density["authority"]["snapshot"]),
        E._DEFAULT_MARGIN)
    assert refused["verdict"] == "NOT_MEASURED", (damage, refused)
    assert refused["native_density"]["valid"] is False, (damage, refused)


def test_final_state_stale_source_is_judged_natively(tmp_path, monkeypatch):
    test_current_vsrc_producer_validates_from_absolute_and_project_dot(
        tmp_path, monkeypatch)
    project = Path.cwd()
    # #62b: screen intact final-State currents/geometry against PDK Jmax.
    # Non-final source refusal remains in test_nonfinal_em_retains_source_refusal.
    import _prestream_native as native
    assert native.final_state(project) is not None
    density_path = project / "reports/phase3/em_openroad_density.json"
    density = json.loads(density_path.read_text())
    density["source_identity"]["em_peak_current_authority_check.py"] = "0" * 64
    density_path.write_text(json.dumps(density))
    judged = A.jmax_tier(
        Path("."), None, Path(density["authority"]["snapshot"]),
        E._DEFAULT_MARGIN)
    assert judged["verdict"] == "PASS", judged
    assert judged["native_density"]["valid"] is True, judged
