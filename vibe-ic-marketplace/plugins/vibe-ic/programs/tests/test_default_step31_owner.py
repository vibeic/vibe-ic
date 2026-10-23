"""Actual bounded Default31 and consumers, with neutral native transports.

The invented transcripts exercise source ownership and ordering only. They
are not a native physical-verification result or an IC PASS claim.
"""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import execution_backend_producers as B
import execution_backend_worker as W
import execution_policy as P
import phase3_one_shot_runner as R
import step_output_collector as V
import flow_declared_producer_run as D
from test_backend_input_contract_sdc import _project
from test_default_physical_composed import _step31_control
from test_lvs_report_check import _PRIMARY_MATCH
from test_drc_vacuous_pass_check import _write_gds


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


LAYOUT = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100000 100000 ) ;
COMPONENTS 1 ;
- u logic + PLACED ( 2000 2000 ) N ;
END COMPONENTS
PINS 2 ;
- a + NET signal + DIRECTION INPUT + USE SIGNAL ;
- b + NET signal + DIRECTION OUTPUT + USE SIGNAL ;
END PINS
NETS 2 ;
- n ( u Y ) ;
- signal ( PIN a ) ( PIN b ) + ROUTED met1 ( 1000 1000 ) ( 9000 1000 ) ;
END NETS
SPECIALNETS 2 ;
- PWR ( * VPWR ) + USE POWER + ROUTED met1 1000 ( 0 0 ) ( 10000 0 ) ;
- GND ( * VGND ) + USE GROUND + ROUTED met1 1000 ( 0 1000 ) ( 10000 1000 ) ;
END SPECIALNETS
END DESIGN
"""



def post_stream_transport(project, pdk, monkeypatch, calls):
    """Real plan/capture/census/judge; only tool and synthetic-PDK I/O is neutral.

    LOCAL identity is the launcher's actual current-CID proof. No fixture CID,
    image digest, plan identity, census classification or verdict is supplied.
    """
    import contextlib
    import io
    import subprocess
    import _eda_image
    import drv_capture_plan as planner
    import drv_run_identity
    import drv_signoff_capture as capture
    import drv_signoff_judge as drv
    import flow_compliance_check as fcc
    import librelane_contract as ll
    from test_drv_signoff_judge import _report, _stage_receipts, _install_test_freeze

    image = os.environ["VIBEIC_EDA_IMAGE"]
    image_id = ll.local_image_attestation(image)["image_id"]
    root = project / "input/pdk"
    lib = put(root, "open_fixture/libs.ref/neutral/lib/std_typ.lib", '''library(std) {
 time_unit : "1ns"; capacitive_load_unit (1,pf);
 nom_process : 1; nom_voltage : 5; nom_temperature : 25;
 default_max_transition : 20; default_max_capacitance : 20;
 cell (logic) { pin (Y) { direction : output;
 max_transition : 20; max_capacitance : 20; } }
}''')
    pdk.liberty = str(lib)
    put(root, "open_fixture/libs.ref/neutral/lef/std.lef",
        "MACRO logic\n CLASS CORE ;\n PIN Y\n DIRECTION OUTPUT ;\n USE SIGNAL ;\n END Y\nEND logic\n")
    config = put(root, "open_fixture/libs.tech/librelane/neutral/config.tcl",
        "set ::env(MAX_FANOUT_CONSTRAINT) 4\n"
        "set ::env(MAX_TRANSITION_CONSTRAINT) 3\n"
        "set ::env(MAX_CAPACITANCE_CONSTRAINT) 0.2\n")
    put(project, "input/docs/L7_design.md", "neutral source-control verification plan\n")
    put(project, "input/docs/L9_constraints_floorplan.md", "| SYNTH_MAX_FANOUT | 4 |\n")
    sdc = put(project, "phase3/stage3/sta/signoff.sdc",
        "create_clock -name clk -period 24 [get_ports a]\n"
        "set_input_delay 4.8 -clock clk [all_inputs]\n"
        "set_output_delay 4.8 -clock clk [all_outputs]\n"
        "set_max_fanout 4 [current_design]\n"
        "set_max_transition 3 [current_design]\n"
        "set_max_capacitance 0.2 [current_design]\n")
    profile = put(project, "input/neutral_drv_scenes.json", json.dumps({
        "open_fixture": {"pvt": {"typ": {"nom_voltage": 5,
         "nom_temperature": 25}}, "rc_corners": ["nom", "max"]}}))
    monkeypatch.setattr(planner, "_SCENE_PROFILES", profile)
    monkeypatch.setattr(drv, "_SCENE_PROFILES", profile)
    monkeypatch.setattr(_eda_image, "resolve", lambda: image)
    monkeypatch.setattr(ll, "resolve_image", lambda *a, **k: image)
    monkeypatch.setattr(ll, "resolve_pdk_root", lambda *a, **k: str(root))
    put(project, "phase3/librelane_pdk_root.provenance.json", json.dumps({
        "path": str(root), "derivation": {"image_id": image_id}}))
    refs = {}
    for kind, rc in (("setup", "nom"), ("hold", "max")):
        spef = put(project, f"phase3/stage3/rcx/{rc}/top.{rc}.spef", f"*SPEF neutral {rc}\n")
        refs[f"{rc}/top.{rc}.spef"] = sha(spef)
        put(project, f"phase3/stage3/sta/sta_mcorner_ocv_{kind}.tcl",
            f"read_liberty {lib}\n"
            f"read_verilog {project / 'phase3/stage3/pnr/chip_top_pnr.v'}\n"
            "link_design chip_top\n"
            f"read_sdc {sdc}\n"
            "set_timing_derate -early 0.95\nset_timing_derate -late 1.05\n"
            f"read_spef {spef}\n")
    put(project, "phase3/stage3/rcx/COMMANDS", "SOURCE_CONTROL RCX transport\n")
    put(project, "phase3/stage3/rcx/vibeic_receipt.json", json.dumps({
        "input": {"step": "OpenROAD.RCX", "image": image,
        "state_files": {str(project / "phase3/stage3/pnr/routed.def"):
                        sha(project / "phase3/stage3/pnr/routed.def")}}, "sha256": refs}))
    drv_run_identity.record(project)
    _stage_receipts(project)
    plan = planner.build(project)
    _install_test_freeze(plan, project, monkeypatch)
    anchor = {"path": str(config), "sha256": sha(config),
              "pdk_commit": "SOURCE_CONTROL_synthetic_PDK"}
    monkeypatch.setattr(capture, "image_pdk_anchor", lambda *a: anchor)
    monkeypatch.setattr(drv, "image_pdk_anchor", lambda *a: anchor)
    monkeypatch.setattr(capture, "openroad_identity", lambda image:
                        {"commit": "SOURCE_CONTROL_openroad_transport"})

    def fresh(script, roots, *, image):
        calls.append("drv_" + script.name)
        folder = script.parent
        control = script.name == "positive_control.tcl"
        prefix = "positive_control_" if control else ""
        limits = dict(fanout=2, fanout_limit=1, cap_limit=1e-6,
                      slew_limit=1e-6) if control else dict(fanout=2)
        put(folder, prefix + "all_limits.rpt",
            _report(**limits))
        put(folder, "positive_control.rpt" if control else "violators.rpt",
            _report(**limits, violators=True))
        put(folder, prefix + "counters.log", "".join(
            f"DRV_COUNTER {kind} {int(control)}\n" for kind in drv.KINDS))
        if not control:
            put(folder, "pin_census.tsv",
                "u/Y\tpin\toutput\t1\tu\tlogic\tY\tn\tinput\t0.1\t0.1\t0\tX\t0\n")
            put(folder, "net_census.rpt", "Net n\n Total capacitance: 0.1\n"
                " Number of drivers: 1\n Number of loads: 0\n Number of pins: 1\n"
                "\nDriver pins\n u/Y output (logic)\n\n")
            put(folder, "disabled_edges.rpt", "")
            put(folder, "annotation.rpt", "Found 0 unannotated drivers.\n")
            put(folder, "clocks.rpt", "propagated\n")
        return "OpenSTA SOURCE_CONTROL aaaaaaaaaa\n"

    monkeypatch.setattr(capture, "_run_fresh", fresh)
    real_process = R._pr.run
    real_supervised = fcc._watchdog.run_host_supervised

    def process(argv, **kwargs):
        if len(argv) > 1 and Path(str(argv[1])).name == "drv_signoff_judge.py":
            # Same actual CLI main and project judge; in-process dispatch keeps
            # the explicit synthetic PDK/owner I/O boundaries local to this test.
            stdout, stderr = io.StringIO(), io.StringIO()
            with monkeypatch.context() as env:
                if kwargs.get("cwd") is not None:
                    env.chdir(kwargs["cwd"])
                for name, value in (kwargs.get("env") or {}).items():
                    env.setenv(name, value)
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    rc = drv.main([str(value) for value in argv[2:]])
            return subprocess.CompletedProcess(argv, rc, stdout.getvalue(), stderr.getvalue())
        return real_process(argv, **kwargs)

    def supervised(argv, **kwargs):
        if len(argv) > 1 and Path(str(argv[1])).name == "drv_signoff_judge.py":
            done = process(argv, **kwargs)
            return fcc._watchdog.SupervisedResult(
                done.returncode, done.stdout, done.stderr, "natural", 0)
        return real_supervised(argv, **kwargs)

    monkeypatch.setattr(R._pr, "run", process)
    monkeypatch.setattr(fcc._watchdog, "run_host_supervised", supervised)


def fixture(tmp_path, monkeypatch, case, local_image):
    """Full current finished-stream fixture; native leaves remain explicit controls."""
    import librelane_contract as lc
    from test_default_pnr_row_boundaries import _full_gds_lvs_transport
    project, pdk, selected, calls, attempt = _checkpoint31_fixture(
        tmp_path, monkeypatch, local_image)
    attempt['first'] = False
    _full_gds_lvs_transport(monkeypatch, project, pdk, selected,
                           'lvs_error' if case == 'lvs_fail' else 'current', calls)
    observed = []
    real_declared, real_gate = D.run_for_step, W.evaluate

    def declared(root, sid, *args, **kwargs):
        result = real_declared(root, sid, *args, **kwargs)
        observed.append(('declared', str(sid), result))
        if case == 'missing_erc':
            (root / 'reports/phase3/erc.rpt').unlink(missing_ok=True)
        elif case == 'changed_perc':
            path = root / 'reports/phase3/perc_sweep.json'
            path.write_text(path.read_text() + '\nchanged after producer\n')
        return result

    def consume(root, row):
        observed.append(('consumer', str(row['id']), None))
        return real_gate(root, row)

    monkeypatch.setattr(D, 'run_for_step', declared)
    monkeypatch.setattr(W, 'evaluate', consume)
    monkeypatch.setattr(P, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(P, '_ordinary_runtime', None)
    import _flow_yaml
    row = next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == '31')
    for name in row['required_outputs']:
        (project / name).unlink(missing_ok=True)
    assert all(not (project / name).exists() for name in row['required_outputs'])
    calls.clear()
    return project, pdk, calls, observed, row


def _assert_full_gds_chain(project, calls):
    import librelane_contract as lc
    rows = [row for row in calls if isinstance(row, dict) and 'native_step' in row]
    assert [row['native_step'] for row in rows] == ['Magic.SpiceExtraction', 'Netgen.LVS']
    for row in rows:
        receipt = lc.validate_step_receipt(Path(row['folder']), row['native_step'])
        assert receipt['input']['step'] == row['native_step']
    extraction, compare = rows
    assert compare['input_state']['spice'] == str(Path(extraction['folder']) / 'layout.spice')
    assert Path(compare['input_state']['pnl']).is_file()
    assert sum('erc' in row for row in calls if isinstance(row, dict)) == 1


def current_window(tmp_path, monkeypatch, local_image):
    """Real current Default owner/declared writers/full thirteen-output consumer."""
    project, pdk, calls, observed, row = fixture(
        tmp_path, monkeypatch, 'current', local_image)
    before = {name: (R._pl.pnr_dir(project) / name).read_bytes()
              for name in ('routed.def', 'spm.gds')}
    selected = R._phase3_window_sites('31', '31')
    assert selected == ['default_backend']
    args = SimpleNamespace(entry_step='31', exit_step='31',
                           container='', die_um=None,
                           util=None, spare_density=None)
    rc = R._run_phase3_window(project, 'spm', pdk, args, selected)
    assert rc == 0
    assert [value[:2] for value in observed] == [('declared', '31'), ('consumer', '31')]
    _assert_full_gds_chain(project, calls)
    assert observed[0][2]['verdict'] == 'PRODUCED'
    current = V.latest_pass(project, '31')
    assert current and current['canonical_pass'] and current['current_inputs']
    assert len(row['required_outputs']) == 13
    assert all((project / name).is_file() for name in row['required_outputs'])
    for name, payload in before.items():
        assert (R._pl.pnr_dir(project) / name).read_bytes() == payload
    return project, pdk, calls, observed, args


@pytest.mark.parametrize("case", ["current", "missing_erc", "changed_perc", "lvs_fail"])
def test_bounded_default31_owns_all_current_outputs_before_the_consumer(
        tmp_path, monkeypatch, local_image, case):
    project, pdk, calls, observed, definition = fixture(
        tmp_path, monkeypatch, case, local_image)
    selected = R._phase3_window_sites("31", "31")
    put(project, "ROUTE_OBSERVATION.json", json.dumps({"selected": selected,
        "required_owner": "Default31 native producer and current-step declared writers"}))
    assert selected == ["default_backend"], selected
    args = SimpleNamespace(entry_step="31", exit_step="31", container="",
                           die_um=None, util=None, spare_density=None)
    rc = R._run_phase3_window(project, "spm", pdk, args, selected)
    result = V.latest_pass(project, "31")
    receipt_path = project / "reports/phase3/default_steps/31/backend_result.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else None
    observation = {"case": case, "rc": rc, "selected": selected, "calls": calls,
        "observed": observed, "latest": result, "receipt": receipt,
        "required_outputs": {name: sha(project / name) if (project / name).is_file() else None
                             for name in definition["required_outputs"]},
        "scope": "source-only neutral native instruments; complete real Default31 consumer"}
    put(project, "API_OBSERVATION.json", json.dumps(observation, indent=2))
    _assert_full_gds_chain(project, calls)
    order = [x[:2] for x in observed]
    if case == "lvs_fail":
        assert rc != 0
        assert receipt["verdict"] == "FAIL", receipt
        assert receipt["producer_verdict"] == "FAIL", receipt
        assert order == [], "a measured producer FAIL must stop before declared writers or consumers"
        assert result is None
        return
    assert order == [("declared", "31"), ("consumer", "31")]
    census = observed[0][2]
    assert census["executed"] > 0, census
    if case == "current":
        assert order == [("declared", "31"), ("consumer", "31")]
        assert census["verdict"] == "PRODUCED", census
        assert rc == 0
        assert result and result["canonical_pass"] is True
        assert len(observation["required_outputs"]) == 13
        assert calls.count("drv_measure.tcl") == 2
        assert calls.count("drv_positive_control.tcl") == 2
        plan = json.loads((project / "reports/phase3/sta/drv_capture_plan.json").read_text())
        assert plan["identity"]["capture_point"] == "post_stream"
        assert all(observation["required_outputs"].values())
        perc = json.loads((project / "reports/phase3/perc_sweep.json").read_text())
        assert perc["program"] == perc["sweep"] == "perc_corpus_sweep"
        assert perc["invoked_as"] == "producer"
    else:
        assert rc != 0
        assert result is None or result["current_inputs"] is not True
        if case == "missing_erc":
            assert observation["required_outputs"]["reports/phase3/erc.rpt"] is None
        else:
            report = project / "reports/phase3/perc_sweep.json"
            producer = next(row for row in census["results"]
                            if row["program"] == "perc_corpus_sweep")
            assert sha(report) != producer["target_sha256"]


def test_ultra_keeps_its_existing_step31_sites(monkeypatch):
    monkeypatch.setattr(P, "request", lambda: {"mode": "ultra"})
    assert R._phase3_window_sites("31", "31") == ["drc", "lvs"]


@pytest.mark.parametrize("case", ["current", "changed_pdk", "changed_gds", "refused_restore"])
def test_resumed_default31_uses_fresh_admission_basis_before_physical_views(
        tmp_path, monkeypatch, local_image, case):
    """Real admission/restore/producer/full consumer; native leaves are neutral."""
    import copy

    project, pdk, calls, observed, row = fixture(
        tmp_path, monkeypatch, "current", local_image)
    pnr = R._pl.pnr_dir(project)
    macro = put(project, "input/pdk/recorded_macro.lef",
                "MACRO recorded_macro\n CLASS BLOCK ;\n SIZE 1 BY 1 ;\nEND recorded_macro\n")
    put(project, R.PHYSICAL_VIEW_INVENTORY_REL, json.dumps({
        "read_lef_paths": [pdk.tech_lef, pdk.cell_lef, str(macro)]}))
    fresh_basis, error = R._layout_basis(project, "spm", pdk, "")
    assert not error
    assert R._ga.admitted_gds(project, pnr / "spm.gds", fresh_basis)
    restored_pdk = copy.deepcopy(pdk)
    restored = R._restore_recorded_physical_views(project, restored_pdk, "")
    assert restored["macro_lefs"] == [str(macro)]
    restored_basis, error = R._layout_basis(
        project, "spm", restored_pdk, "")
    assert not error and restored_basis != fresh_basis
    assert not R._ga.admitted_gds(project, pnr / "spm.gds", restored_basis)
    before = {str(path.relative_to(project)): path.read_bytes() for path in
              [*R._layout_basis_paths(project, "spm"), pnr / "spm.gds",
               R._ga.admission_path(project), project / R.PHYSICAL_VIEW_INVENTORY_REL]}
    if case == "changed_pdk":
        path = Path(pdk.liberty)
        path.write_text(path.read_text() + "\n/* changed source material */\n")
    elif case == "changed_gds":
        _write_gds(pnr / "spm.gds", n_shapes=13, cell="spm")
    elif case == "refused_restore":
        put(project, "reports/pdk_via_patch_legalization.json", json.dumps({
            "status": "APPLIED", "derived_tech_lef": "input/pdk/missing_recorded.lef",
            "derived_sha256": "0" * 64}))
    # Model the bounded entry's fresh process, rather than retaining hashes
    # memoized while the neutral fixture published its original admission.
    monkeypatch.setattr(R, "_STEP_PDK_HASH_CACHE", {})
    calls.clear()
    args = SimpleNamespace(entry_step="31", exit_step="31", container="",
                           die_um=None, util=None, spare_density=None)
    rc = R._run_phase3_window(project, "spm", pdk, args,
                              R._phase3_window_sites("31", "31"))
    receipt = json.loads((project / "reports/phase3/default_steps/31/backend_result.json").read_text())
    current = V.latest_pass(project, "31")
    put(project, "BASIS_ORDER_OBSERVATION.json", json.dumps({
        "case": case, "fresh_basis": fresh_basis, "restored_basis": restored_basis,
        "restored_macro_lefs": pdk.macro_lefs, "rc": rc, "calls": calls,
        "observed": observed, "receipt": receipt, "current": current,
        "scope": "real bounded Default31 admission and consumer; neutral native leaves"}, indent=2))
    if case != "current":
        assert rc != 0 and receipt["producer_verdict"] == "NOT_MEASURED", receipt
        assert calls == [] and observed == [], "refusal must precede all native instruments"
        assert current is None
        if case == "refused_restore":
            assert "via-legalized tech LEF" in receipt["detail"]
        else:
            assert "unadmitted routed GDS" in receipt["detail"]
        return
    assert rc == 0 and receipt["producer_verdict"] == "PASS", receipt
    assert [x[:2] for x in observed] == [("declared", "31"), ("consumer", "31")]
    _assert_full_gds_chain(project, calls)
    assert str(macro) in pdk.macro_lefs, "instruments still require restored physical views"
    assert current and current["canonical_pass"] and current["current_inputs"]
    assert len(row["required_outputs"]) == 13
    for name, payload in before.items():
        assert (project / name).read_bytes() == payload


# Native Step31 coupled-owner controls share retained finished-stream fixtures;
# native owners and validators execute unchanged.
def _public_native31_window(project, pdk, monkeypatch, *, case, native_processes, file_top="spm"):
    """Executable public-entry skeleton shared by the new native-leaf controls."""
    import _flow_yaml
    import execution_policy as policy
    import gds_xor_check as xor

    original_geometry = json.loads((project / xor.REPORT_REL).read_text())
    monkeypatch.setattr(policy, "request", lambda: {"mode": "default"})
    monkeypatch.setattr(policy, "_ordinary_runtime", None)
    rows = [row for row in _flow_yaml.load()["steps"] if str(row["id"]) == "31"]
    assert len(rows) == 1
    args = SimpleNamespace(entry_step="31", exit_step="31", container="",
                           die_um=None, util=None, spare_density=None)
    selected = R._phase3_window_sites("31", "31")
    assert selected == ["default_backend"]
    rc = R._run_phase3_window(project, file_top, pdk, args, selected)
    # Observe the actual composed reader before any post-window assertion. A
    # pre-fix/red run must retain its real diagnostic drift instead of failing
    # before that evidence is recorded.
    gxc_rc, gxc_reason, gxc_report = xor.judge_receipt(project, xor.REPORT_REL)
    captured = sorted(project.glob("steps/phase3/stage4/31_*/outputs.json"))
    record = json.loads(captured[-1].read_text()) if captured else None
    before_conn = original_geometry.get("connectivity")
    fresh_conn = xor.gds_connectivity(
        project, original_geometry["shipped_sha256_live"], original_geometry)
    post31_connectivity = {
        "rc": gxc_rc, "reason": gxc_reason,
        "oldconn": before_conn, "freshconn": fresh_conn,
        "returned_conn": gxc_report.get("connectivity"),
        "changed": before_conn != fresh_conn,
        "current31_record_path": str(captured[-1]) if captured else None,
        "current31_receipt": record,
        "scope": "Observed actual composed reader; original receipt not rewritten"}
    put(project, "NATIVE_OWNER_OBSERVATION.json", json.dumps({
        "case": case, "rc": rc, "record": record,
        "native_processes": native_processes,
        "post31_original_gxc": post31_connectivity,
        "scope": "source-control neutral process leaves; actual public Step31 owners"}, indent=2))
    assert captured, "the actual bounded driver must capture its result"
    return rc, record, V.latest_pass(project, "31"), rows[0], post31_connectivity


def _native31_retained_stream(tmp_path, monkeypatch, local_image):
    """Existing whole/LOCAL373 fixture, with functional input before publication.

    Only the fixture's initial upstream netlist bytes are seeded here. The
    whole-stream/three-stage owners, receipt validators and current readers are
    the existing implementations; no signoff invocation is written by this test.
    """
    import re
    import test_default_stream_epoch_order as epoch
    import librelane_fill_dfm as fill
    import librelane_contract as lc
    from test_default_finishing import refresh_receipt

    # The reused antecedent has a fixed lexical fixture_pdk name. Establish
    # its input location before any material, LC receipt or stream is built;
    # existing material/root validators still resolve and hash the real files.
    project_root = tmp_path / "project"
    external_pdk = project_root / "input/native31-pdk-input"
    project_root.mkdir(parents=True, exist_ok=True)
    external_pdk.mkdir(parents=True)
    (project_root / "fixture_pdk").symlink_to(external_pdk, target_is_directory=True)
    captured = {}
    real_subject = epoch._native373_boundary_subject
    real_stream = fill.default_stream
    real_fill_record = epoch.BF.fill_record

    def initial_pg_geometry(project, *args, **kwargs):
        # The calibration DEF deliberately has rail-only declarations. Supply
        # this coupled positive's normal routed rails before the original fill
        # constructor creates its first input state, fingerprint or receipt.
        for name in ("top.def", "routed.def"):
            path = project / "phase3/stage3/pnr" / name
            text = path.read_text()
            head, marker, body = text.partition("SPECIALNETS")
            rails, end, tail = body.partition("END SPECIALNETS")
            rails = re.sub(r"(\+\s+USE\s+POWER)\s*;",
                r"\1 + ROUTED Metal2 1000 ( 1000 1000 ) ( 79000 1000 ) ;", rails)
            rails = re.sub(r"(\+\s+USE\s+GROUND)\s*;",
                r"\1 + ROUTED Metal2 1000 ( 1000 79000 ) ( 79000 79000 ) ;", rails)
            path.write_text(head + marker + rails + end + tail)
        return real_fill_record(project, *args, **kwargs)

    def initial_sources(project, file_top, pdk, container):
        # This hook runs before the first real whole-stream publication, while
        # the reused upstream fixture is still being constructed.
        doc = json.loads((project / fill.RECORD_REL).read_text())
        odb = doc["odb"]
        tool = odb["tool"]
        state_path = Path(tool["state"])
        state = json.loads(state_path.read_text())
        text = Path(state["def"]).read_text()
        design = lc._def_design_name(Path(state["def"]))
        match = re.search(r"(?m)^\s*-\s+(\S+)\s+(\S+)\s+\+\s+PLACED", text)
        assert match, "the original checked-in subject must contain a cell"
        inst, master = match.groups()
        nl = Path(state["nl"])
        nl.write_text(f"module {design}(input a, output y); wire n;\n"
                      f"{master} {inst} (.I(a), .Z(n)); assign y = n; endmodule\n")
        Path(state["sdc"]).write_text(
            "create_clock -name clk -period 24 [get_ports a]\n")
        # Establish the original upstream STA parent before any whole-stream
        # or native373 publication. The fill output is functionally equal but
        # has different bytes; the source/current owners bind both roles.
        parent_nl = put(project, "phase3/stage3/pnr/spm_pnr.v",
            "// SOURCE_CONTROL original pre-fill netlist input\n"
            f"module {design}(input a, output y); wire n;\n"
            f"{master} {inst} (.I(a), .Z(n)); assign y = n; endmodule\n")
        initial_path = Path(tool["binding"]["input_state"])
        initial = json.loads(initial_path.read_text())
        initial["nl"] = str(parent_nl)
        epoch.BF.put(initial_path, initial)
        epoch.BF.put(state_path.parent / "state_in.json", initial)
        fingerprint_path = state_path.parent / "input_fingerprint.json"
        fingerprint = json.loads(fingerprint_path.read_text())
        fingerprint["state"] = sha(initial_path)
        fingerprint["state_files"] = {str(path): sha(path)
            for path in fill._walk_input_views(initial)}
        epoch.BF.put(fingerprint_path, fingerprint)
        config = json.loads(Path(tool["binding"]["config"]).read_text())
        tool["census"] = fill.fill_census(Path(initial["def"]).read_text(),
            Path(state["def"]).read_text(), fill.cell_patterns(config))
        # The upstream neutral fixture already owns these initial files. Its
        # existing receipt helper is used before the whole-stream owner binds
        # them, never to restamp a signoff report or a completed current result.
        refresh_receipt(state_path.parent)
        tool["binding"]["receipt_sha256"] = sha(state_path.parent / "vibeic_receipt.json")
        epoch.BF.consume_fill(project, tool)
        fill.update_record(project, "odb", odb)
        captured.update(design=design, master=master, inst=inst, parent_netlist=parent_nl)
        return real_stream(project, file_top, pdk, container)

    def observe_subject(*args, **kwargs):
        project, pdk, root, stream, calls = real_subject(*args, **kwargs)
        # The original LOCAL producer consumes this returned root. Select its
        # canonical input path before it generates any three-stage fingerprint
        # so producer and current reader bind identical material path keys.
        result = project, pdk, root.resolve(), stream, calls
        captured["subject"] = result
        return result

    # The existing LOCAL regression goes through real LC.run_chain and the
    # actual ShippedXorRunner, not its whole-method synthetic alternative.
    # All its setup process patches are removed before the new Step31 window.
    with monkeypatch.context() as setup:
        setup.setattr(epoch.BF, "fill_record", initial_pg_geometry)
        setup.setattr(fill, "default_stream", initial_sources)
        setup.setattr(epoch, "_native373_boundary_subject", observe_subject)
        epoch.test_normal373_local_receipts_reach_original_connectivity_consumer(
            tmp_path, setup, local_image, "local_runner")
    return captured


def _native31_process_leaf(project, selected, case, calls):
    """Only the costly P3 supervised native process edge is neutralized."""
    import re
    import shlex
    from test_a_magic_receipt_binds_to_the_layout_it_read import _GOOD

    def leaf(container, command, marker, **kwargs):
        argv = shlex.split(command)
        observed = {"command": command, "marker": marker}
        calls.append(observed)
        if "SPICE_OUT=" in command and "magic" in argv:
            assignments = dict(re.findall(r"\b(DEF|TOP|SPICE_OUT|FEEDBACK_OUT)=([^\s;&]+)", command))
            observed["extraction"] = {"def": assignments["DEF"],
                                      "top": assignments["TOP"]}
            output = Path(assignments["SPICE_OUT"])
            output.write_text(
                f".subckt {selected['design']} a y VDD VSS\n"
                "Rsignal a y 1\n.ends\n")
            Path(assignments["FEEDBACK_OUT"]).write_text("")
            transcript = ("0 errors\nPORTS_PROMOTED 1..4\n"
                          f"MAGIC_EXT2SPICE_DONE {output}\n")
            # The real shell pipeline tees this transcript; emulate that
            # process write at its actual argv path, leaving the logger real.
            log = Path(argv[argv.index("tee") + 1])
            observed["extraction"].update(tee=str(log), log_path=str(kwargs["log_path"]))
            log.write_text(transcript)
            return 0, transcript, ""
        if "netgen" in argv and "lvs" in argv:
            offset = argv.index("netgen")
            layout_arg, schematic_arg = argv[offset + 3:offset + 5]
            layout, layout_top = layout_arg.rsplit(" ", 1)
            schematic, schematic_top = schematic_arg.rsplit(" ", 1)
            observed["comparison"] = {"layout": layout, "layout_top": layout_top,
                "schematic": schematic, "schematic_top": schematic_top,
                "schematic_exists": Path(schematic).is_file()}
            # Keep actual arguments as observations until the public window
            # has captured its own result; a red source must reach its owner.
            if "pwraware" in Path(schematic).name:
                observed["comparison"]["power_aware_text"] = (
                    Path(schematic).read_text() if Path(schematic).is_file() else "")
            report = Path(argv[offset + 6])
            text = _PRIMARY_MATCH.replace("user_project_wrapper", selected["design"])
            if case == "netgen_mismatch":
                text = text.replace("Final result: Circuits match uniquely.",
                    "Netlists do not match.\nFinal result: Top level cell failed pin matching.\n"
                    "Net: functional_signal | (no matching net)\n")
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(text)
            return 0, "Netgen neutral process completed\n" + text, ""
        if "klayout" in argv:
            values = dict(token.split("=", 1) for token in argv if "=" in token)
            observed["drc"] = {"input": values["input"], "top_cell": values["top_cell"]}
            report = Path(values["report"])
            count = int(case == "drc_error")
            item = (f"<item><cell>{values['top_cell']}</cell><category>'met2.short'</category>"
                    "<multiplicity>1</multiplicity></item>") if count else ""
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                f"<report-database><generator>drc: script = '{selected['deck']}'</generator>"
                f"<top-cell>{selected['design']}</top-cell><description>"
                f"KLayout total violations: {count}\nspacing width density antenna via enclosure "
                + "SOURCE_CONTROL " * 200
                + f"</description><cells><cell><name>{values['top_cell']}</name></cell></cells>"
                + "<categories><category><name>met2.short</name>"
                  "<description>Neutral routing-metal short rule</description>"
                  "</category></categories>"
                + f"<items>{item}</items></report-database>\n")
            return 0, "KLayout neutral full-deck process completed\n", ""
        if "magic" in argv:
            report = project / R._MAGIC_SIGNOFF_DRC_REL
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(_GOOD.replace("ab" * 32, sha(selected["gds"])))
            return 0, report.read_text(), ""
        if "openroad" in argv and any("erc_" in token for token in argv):
            transcript = "0 floating nets\n0 floating pins\nERC_NATIVE_DONE\n"
            # Match the native shell tee before the real logger hashes output.
            log = Path(argv[argv.index("tee") + 1])
            log.write_text(transcript)
            observed['erc'] = {'tee': str(log)}
            return 0, transcript, ""
        raise AssertionError("unexpected expensive native process: " + command)
    return leaf


@pytest.mark.parametrize("case", ["current", "missing_report", "changed_log",
    "changed_extraction", "changed_material", "changed_alias", "drc_error",
    "netgen_mismatch", "legacy_feedback"])
def test_public_default31_native_owner_closes_retained_subject(
        tmp_path, monkeypatch, local_image, case):
    """Public window + true native logger/PA/transform/current/full consumer.

    Neutral process transcripts test ownership, not physical verification.
    No current validator, provenance reader, PA emitter or declared publisher
    is replaced by this control.
    """
    import _physical_current as current
    import librelane_fill_dfm as fill

    project, pdk, selected, calls, attempt = _checkpoint31_fixture(
        tmp_path, monkeypatch, local_image, case)
    attempt['first'] = False
    before = {role: path.read_bytes() for role, path in selected.items()
              if role in ("def", "netlist", "sdc", "gds")}
    closure_calls = (_observe_native31_closure_calls(monkeypatch)
                     if case == "current" else None)
    rc, record, retained, row, post31_connectivity = _public_native31_window(
        project, pdk, monkeypatch, case=case, native_processes=calls)
    if closure_calls is not None:
        observation_path = project / "NATIVE_OWNER_OBSERVATION.json"
        observation = json.loads(observation_path.read_text())
        observation["same_call_closure_counts"] = closure_calls
        observation_path.write_text(json.dumps(observation, indent=2))
    if case in ("drc_error", "netgen_mismatch", "legacy_feedback"):
        assert rc != 0 and record["result"]["producer_verdict"] == "FAIL", record
        assert not record["canonical_pass"] and retained is None
        if case == "legacy_feedback":
            assert 'FEEDBACK_LAYOUT_DIGEST_MISMATCH_OR_UNMEASURED' in record['result']['detail']
            assert 'LL_PV_VIEW_MISSING' in record['result']['detail']
        return
    assert rc == 0 and record["canonical_pass"] is True, record
    assert record["result"]["producer_verdict"] == "PASS"
    assert record["result"]["canonical_step_result"]["status"] == "PASS"
    assert retained and retained["current_inputs"] and retained["canonical_pass"]
    assert len(row["required_outputs"]) == 13
    assert all((project / path).is_file() for path in row["required_outputs"])
    assert current.read_direct_half(project, "drc")["verdict"] == "CURRENT"
    import librelane_contract as lc
    import librelane_signoff_evidence as native_evidence
    assert native_evidence.obligation(project, 'lvs')['verdict'] == 'PASS'
    _assert_full_gds_chain(project, calls)
    for call in (item for item in calls if isinstance(item, dict)):
        if 'native_step' in call:
            state = call['input_state']
            assert Path(state['gds']) == selected['gds']
            assert Path(state['def']) == selected['def']
        if 'drc' in call:
            assert Path(call['drc']['input']) == selected['gds']
            assert call['drc']['top_cell'] == selected['design']
    inputs_path = project / 'reports/phase3/lvs_inputs.json'
    inputs = json.loads(inputs_path.read_text())
    assert selected['design'] != 'spm'
    for role, field in (('def', 'layout_def'), ('netlist', 'schematic_netlist'), ('gds', 'layout_gds')):
        assert inputs[field]['path'] == str(selected[role].resolve())
        assert inputs[field]['sha256'] == sha(selected[role])
    verdict = json.loads((project / 'reports/phase3/lvs_verdict.json').read_text())
    assert verdict['lvs_inputs']['sha256'] == sha(inputs_path)
    power_aware = Path(inputs['powered_reference']['path']).read_text()
    assert '.VDD(' in power_aware and '.VSS(' in power_aware
    extraction = next(Path(call['folder']) for call in calls
                      if isinstance(call, dict) and call.get('native_step') == 'Magic.SpiceExtraction')
    comparison = next(Path(call['folder']) for call in calls
                      if isinstance(call, dict) and call.get('native_step') == 'Netgen.LVS')
    native_state = json.loads((comparison / 'state_in.json').read_text())
    assert Path(native_state['pnl']) == Path(inputs['powered_reference']['path'])
    assert Path(native_state['spice']) == Path(inputs['extracted_spice']['path'])
    for role, payload in before.items():
        assert selected[role].read_bytes() == payload
    if case == "current":
        assert post31_connectivity["rc"] == 0, post31_connectivity
        assert sha(selected["sta_parent"]) != sha(selected["netlist"])
        assert sha(project / "phase3/stage3/pnr/routed.def") != sha(selected["def"])
        # An existing different netlist is not the native fill receipt's STA
        # parent. Keep its path/hash mutually consistent so the real bridge,
        # rather than an absent-file check, has to reject this association.
        import copy
        import drv_signoff_judge as drv
        bundle = json.loads((project / "reports/phase3/sta/drv_signoff_bundle.json").read_text())
        wrong = copy.deepcopy(bundle)
        wrong["identity"]["sta_netlist"] = sha(selected["netlist"])
        wrong["identity"]["artifacts"]["sta_netlist"] = {
            "path": str(selected["netlist"]), "sha256": sha(selected["netlist"])}
        wrong_result = drv.judge(wrong, project=project)
        observation_path = project / "NATIVE_OWNER_OBSERVATION.json"
        observation = json.loads(observation_path.read_text())
        observation["wrong_parent_sta"] = {
            "actual_parent": str(selected["sta_parent"]),
            "actual_parent_sha256": sha(selected["sta_parent"]),
            "different_existing_parent": str(selected["netlist"]),
            "different_existing_parent_sha256": sha(selected["netlist"]),
            "judge": wrong_result,
            "scope": "In-memory negative only; original bundle/artifacts not rewritten"}
        observation_path.write_text(json.dumps(observation, indent=2))
        assert wrong_result["verdict"] == "FAIL", wrong_result
        assert "LVS compared a layout DEF other than the judged DEF" in wrong_result["failures"]
        return
    if case == "missing_report":
        target = comparison / 'reports/lvs.netgen.rpt'
        target.unlink()
    elif case == "changed_log":
        target = comparison / 'invocation.log'
        target.write_text(target.read_text() + "\nchanged native transcript\n")
    elif case == "changed_extraction":
        inputs = json.loads((project / "reports/phase3/lvs_inputs.json").read_text())
        target = Path(inputs["extracted_spice"]["path"])
        target.write_text(target.read_text() + "\n* changed extraction after compare\n")
    elif case == "changed_material":
        target = selected["material"]
        target.write_text(target.read_text() + "\n# changed native material\n")
    else:
        assert case == "changed_alias"
        import drc_report_check as drc
        native_report = project / "phase3/reports/drc.rpt"
        native_bytes = native_report.read_bytes()
        provenance_bytes = (project / "provenance.jsonl").read_bytes()
        summary = json.loads((project / "reports/phase3/drc_signoff.json").read_text())["summary"]
        canonical = project / "reports/phase3/drc_signoff.rpt"
        canonical.write_text(canonical.read_text() + "\nchanged canonical DRC publication\n")
        evidence = drc._recorded_layout_evidence(project, summary["producers"])
        observation_path = project / "NATIVE_OWNER_OBSERVATION.json"
        observation = json.loads(observation_path.read_text())
        observation["changed_drc_canonical_copy"] = evidence
        observation_path.write_text(json.dumps(observation, indent=2))
        assert evidence is not None
        assert evidence["tier"] == drc._sdf.TIER_NONE, evidence
        assert "canonical DRC copy" in evidence["witness"], evidence
        assert native_report.read_bytes() == native_bytes
        assert (project / "provenance.jsonl").read_bytes() == provenance_bytes
        assert current.read_direct_half(project, "drc")["verdict"] != "CURRENT"
        import drc_vacuous_pass_check as vacuous
        vacuity_path = project / "NATIVE_ALIAS_VACUITY.json"
        vacuity_rc = vacuous.main([str(project), "--under",
            str(canonical.relative_to(project)), "--json", str(vacuity_path)])
        vacuity = json.loads(vacuity_path.read_text())
        observation = json.loads(observation_path.read_text())
        observation["changed_drc_current_vacuity"] = {"rc": vacuity_rc, "report": vacuity}
        observation_path.write_text(json.dumps(observation, indent=2))
        assert vacuity_rc == 1 and vacuity["verdict"] == "INCONCLUSIVE", vacuity
        assert any(item["rule"] == "DRC_CURRENT_LAYOUT_REFUSED"
                   for item in vacuity["findings"]), vacuity
        assert any(item.get("current_layout_refusal")
                   for item in vacuity["summary"]["per_file"]), vacuity
        target = project / "reports/phase3/lvs.rpt"
        target.write_text(target.read_text() + "\nchanged canonical publication\n")
    if case == 'changed_alias':
        # Native comparison remains valid; the changed publication must fail
        # its separate, unchanged provenance consumer.
        import provenance_check
        assert native_evidence.obligation(project, 'lvs')['verdict'] == 'PASS'
        assert provenance_check.main([str(project), '--output', 'reports/phase3/lvs.rpt',
            '--tool', 'netgen,magic,klayout', '--require-measured']) == 1
    else:
        assert native_evidence.obligation(project, 'lvs')['verdict'] != 'PASS'
    assert W.evaluate(project, row)["status"] != "PASS"


def _native31_drv_peripheral(project, pdk, monkeypatch, calls, *, root, master):
    """Existing unrelated DRV data/leaf only; preserve the selected LF root.

    LOCAL identity is the launcher's actual current-CID proof. No fixture CID,
    image digest, plan identity, census classification or verdict is supplied.
    """
    import contextlib
    import io
    import subprocess
    import _eda_image
    import drv_capture_plan as planner
    import drv_run_identity
    import drv_signoff_capture as capture
    import drv_signoff_judge as drv
    import flow_compliance_check as fcc
    import librelane_contract as ll
    from test_drv_signoff_judge import _report, _stage_receipts, _install_test_freeze

    image = os.environ["VIBEIC_EDA_IMAGE"]
    image_id = ll.local_image_attestation(image)["image_id"]
    lib = put(root, "neutral/libs.ref/neutral/lib/std_typ.lib", '''library(std) {
 time_unit : "1ns"; capacitive_load_unit (1,pf);
 nom_process : 1; nom_voltage : 5; nom_temperature : 25;
 default_max_transition : 20; default_max_capacitance : 20;
 cell (logic) { pin (Y) { direction : output;
 max_transition : 20; max_capacitance : 20; } }
}''')
    # Retain the old stage-control cell and add the actual selected output cell.
    text = lib.read_text()
    text = text.rsplit("}", 1)[0] + (" cell (" + master + ") { pin (Z) { direction : output; "
        "max_transition : 20; max_capacitance : 20; } } }\n")
    lib.write_text(text)
    pdk.liberty = str(lib)
    put(root, "neutral/libs.ref/neutral/lef/std.lef",
        "MACRO logic\n CLASS CORE ;\n PIN Y\n DIRECTION OUTPUT ;\n USE SIGNAL ;\n END Y\nEND logic\n")
    config = put(root, "neutral/libs.tech/librelane/neutral/config.tcl",
        "set ::env(MAX_FANOUT_CONSTRAINT) 4\n"
        "set ::env(MAX_TRANSITION_CONSTRAINT) 3\n"
        "set ::env(MAX_CAPACITANCE_CONSTRAINT) 0.2\n")
    put(project, "input/docs/L7_design.md", "neutral source-control verification plan\n")
    put(project, "input/docs/L9_constraints_floorplan.md", "| SYNTH_MAX_FANOUT | 4 |\n")
    sdc = put(project, "phase3/stage3/sta/signoff.sdc",
        "create_clock -name clk -period 24 [get_ports a]\n"
        "set_input_delay 4.8 -clock clk [all_inputs]\n"
        "set_output_delay 4.8 -clock clk [all_outputs]\n"
        "set_max_fanout 4 [current_design]\n"
        "set_max_transition 3 [current_design]\n"
        "set_max_capacitance 0.2 [current_design]\n")
    profile = put(project, "input/neutral_drv_scenes.json", json.dumps({
        "neutral": {"pvt": {"typ": {"nom_voltage": 5,
         "nom_temperature": 25}}, "rc_corners": ["nom", "max"]}}))
    monkeypatch.setattr(planner, "_SCENE_PROFILES", profile)
    monkeypatch.setattr(drv, "_SCENE_PROFILES", profile)
    monkeypatch.setattr(_eda_image, "resolve", lambda: image)
    put(project, "phase3/stage3/pnr/routed.odb",
        "SOURCE_CONTROL neutral routed database input\n")
    refs = {}
    for kind, rc in (("setup", "nom"), ("hold", "max")):
        spef = put(project, f"phase3/stage3/rcx/{rc}/top.{rc}.spef", f"*SPEF neutral {rc}\n")
        refs[f"{rc}/top.{rc}.spef"] = sha(spef)
        put(project, f"phase3/stage3/sta/sta_mcorner_ocv_{kind}.tcl",
            f"read_liberty {lib}\n"
            f"read_verilog {project / 'phase3/stage3/pnr/spm_pnr.v'}\n"
            "link_design cal_pg\n"
            f"read_sdc {sdc}\n"
            "set_timing_derate -early 0.95\nset_timing_derate -late 1.05\n"
            f"read_spef {spef}\n")
    put(project, "phase3/stage3/rcx/COMMANDS", "SOURCE_CONTROL RCX transport\n")
    put(project, "phase3/stage3/rcx/vibeic_receipt.json", json.dumps({
        "input": {"step": "OpenROAD.RCX", "image": image,
        "state_files": {str(project / "phase3/stage3/pnr/routed.def"):
                        sha(project / "phase3/stage3/pnr/routed.def")}}, "sha256": refs}))
    # This retained peripheral supplies direct-STA decks, not a LibreLane
    # STAPostPNR arm. Declare that original supported route before recording
    # the checkpoint; the actual post-stream DRV capture and judge still run.
    switch_path = project / "phase3/librelane_switch.json"
    switch = json.loads(switch_path.read_text())
    switch.setdefault("steps", {})["23"] = "direct"
    # Declare the canonical installed root, not the project-local fixture_pdk
    # symlink that merely selects it.  The production authority intentionally
    # rejects symlink roots because their target can change after declaration.
    switch["pdk_root_host"] = str(Path(root).resolve())
    switch_path.write_text(json.dumps(switch))
    # The retained LOCAL producer published its authority before this helper
    # added the DRV Liberty/LEF/config bytes.  Publish the current root through
    # the real producer seam after those additions; the current capture path
    # reads the receipt directly and does not call resolve_pdk_root itself.
    authority = ll.pdk_root_resolution(project, pdk.name)
    assert authority["source"] == "declared"
    assert authority["declared_by"] == "phase3/librelane_switch.json pdk_root_host"
    assert authority["pdk"] == pdk.name
    assert Path(authority["path"]) == Path(root).resolve()
    assert not Path(authority["path"]).is_symlink()
    drv_run_identity.record(project)
    _stage_receipts(project)
    plan = planner.build(project)
    _install_test_freeze(plan, project, monkeypatch)
    anchor = {"path": str(config), "sha256": sha(config),
              "pdk_commit": "SOURCE_CONTROL_synthetic_PDK"}
    monkeypatch.setattr(capture, "image_pdk_anchor", lambda *a: anchor)
    monkeypatch.setattr(drv, "image_pdk_anchor", lambda *a: anchor)
    monkeypatch.setattr(capture, "openroad_identity", lambda image:
                        {"commit": "SOURCE_CONTROL_openroad_transport"})

    def fresh(script, roots, *, image):
        calls.append("drv_" + script.name)
        folder = script.parent
        control = script.name == "positive_control.tcl"
        prefix = "positive_control_" if control else ""
        limits = dict(fanout=2, fanout_limit=1, cap_limit=1e-6,
                      slew_limit=1e-6) if control else dict(fanout=2)
        put(folder, prefix + "all_limits.rpt",
            _report(**limits).replace("u/Y", "u0/Z"))
        put(folder, "positive_control.rpt" if control else "violators.rpt",
            _report(**limits, violators=True).replace("u/Y", "u0/Z"))
        put(folder, prefix + "counters.log", "".join(
            f"DRV_COUNTER {kind} {int(control)}\n" for kind in drv.KINDS))
        if not control:
            put(folder, "pin_census.tsv",
                f"u0/Z\tpin\toutput\t1\tu0\t{master}\tZ\tn\tinput\t0.1\t0.1\t0\tX\t0\n")
            put(folder, "net_census.rpt", "Net n\n Total capacitance: 0.1\n"
                " Number of drivers: 1\n Number of loads: 0\n Number of pins: 1\n"
                f"\nDriver pins\n u0/Z output ({master})\n\n")
            put(folder, "disabled_edges.rpt", "")
            put(folder, "annotation.rpt", "Found 0 unannotated drivers.\n")
            put(folder, "clocks.rpt", "propagated\n")
        return "OpenSTA SOURCE_CONTROL aaaaaaaaaa\n"

    monkeypatch.setattr(capture, "_run_fresh", fresh)
    real_process = subprocess.run
    real_supervised = fcc._watchdog.run_host_supervised
    import lvs_report_check
    import drc_report_check
    import drc_vacuous_pass_check
    checkers = {"drv_signoff_judge.py": drv.main,
                "lvs_report_check.py": lvs_report_check.run,
                "drc_report_check.py": drc_report_check.run,
                "drc_vacuous_pass_check.py": drc_vacuous_pass_check.main}

    def process(argv, **kwargs):
        program = Path(str(argv[1])).name if len(argv) > 1 else None
        if program in checkers:
            # Same actual CLI main and project judge; in-process dispatch keeps
            # the explicit synthetic PDK/owner I/O boundaries local to this test.
            stdout, stderr = io.StringIO(), io.StringIO()
            with monkeypatch.context() as env:
                if kwargs.get("cwd") is not None:
                    env.chdir(kwargs["cwd"])
                for name, value in (kwargs.get("env") or {}).items():
                    env.setenv(name, value)
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    rc = checkers[program]([str(value) for value in argv[2:]])
            return subprocess.CompletedProcess(argv, rc, stdout.getvalue(), stderr.getvalue())
        return real_process(argv, **kwargs)

    def supervised(argv, **kwargs):
        if len(argv) > 1 and Path(str(argv[1])).name in checkers:
            done = process(argv, **kwargs)
            return fcc._watchdog.SupervisedResult(
                done.returncode, done.stdout, done.stderr, "natural", 0)
        return real_supervised(argv, **kwargs)

    monkeypatch.setattr(R._pr, "run", process)
    monkeypatch.setattr(D.subprocess, "run", process)
    monkeypatch.setattr(fcc._watchdog, "run_host_supervised", supervised)



from test_librelane_contract import local_image


def _native31_runtime_fixture(tmp_path, monkeypatch, local_image, case):
    import re
    import shutil
    import librelane_contract as lc
    import librelane_fill_dfm as fill
    import _native373_current as native373
    import _flow_yaml
    import l24_signoff_requirements_extract as requirements

    subject = _native31_retained_stream(tmp_path, monkeypatch, local_image)
    project, original_pdk, root, stream, _ = subject["subject"]
    shutil.copytree(_project(tmp_path / "native31-dependencies"), project,
        dirs_exist_ok=True, ignore=shutil.ignore_patterns("provenance.jsonl"))
    pnr = R._pl.pnr_dir(project)
    # Use owners already present on base40 so the red arm reaches the actual
    # Step31 window, rather than failing on a helper introduced by this patch.
    monkeypatch.setattr(P, "request", lambda: {"mode": "default"})
    checked_stream = fill.validate_default_stream(project)
    selected = native373._source_inputs(project, native373._source_def(project))
    selected["gds"] = Path(checked_stream["canonical"])
    selected["design"] = subject["design"]
    selected["material"] = root / "neutral/stream.lef"
    selected["sta_parent"] = subject["parent_netlist"]
    assert selected["def"] == Path(stream["filled_def"])
    assert selected["gds"] == Path(stream["canonical"])
    master = subject["master"]
    cell_lef = put(root, "neutral/native31-cells.lef",
        f"MACRO {master}\n CLASS CORE ;\n"
        " PIN I\n DIRECTION INPUT ;\n USE SIGNAL ;\n END I\n"
        " PIN Z\n DIRECTION OUTPUT ;\n USE SIGNAL ;\n END Z\n"
        " PIN VDD\n USE POWER ;\n END VDD\n"
        " PIN VSS\n USE GROUND ;\n END VSS\n"
        " PIN VNW\n USE POWER ;\n END VNW\n"
        f" PIN VPW\n USE GROUND ;\n END VPW\nEND {master}\n")
    reviewed = json.loads((Path(R.__file__).parent / "router_invisible_rules.json").read_text())
    deck = put(root, "neutral/" + reviewed["decks"][0]["deck_basename"],
               "# SOURCE_CONTROL full native deck input\n")
    selected["deck"] = deck
    pdk = R.PdkConfig("neutral", "", str(original_pdk.tech_lef), str(cell_lef),
                     original_pdk.cell_gds, "neutral", str(deck))
    pdk.bridge_magicrc = str(put(root, "neutral/native31.magicrc", "# neutral tech input\n"))
    pdk.bridge_netgen_setup = str(put(root, "neutral/native31_setup.tcl", "# neutral PDK comparison setup\n"))
    for name, role in [("spm.def", "def"),
                       ("spm.gds", "gds"), ("constraint.sdc", "sdc")]:
        (pnr / name).write_bytes(selected[role].read_bytes())
    put(project, "phase2/stage2/synth/netlist_yosys.v", selected["netlist"].read_text())
    put(project, "phase2/stage1/rtl/spm.v", "module spm(input a, output y); assign y=a; endmodule\n")
    put(project, "reports/density.json", json.dumps({"tool": "klayout neutral density instrument",
        "layers": [{"name": "metal1", "density_pct": 40.0}, {"name": "metal2", "density_pct": 40.0}]}))
    assert json.loads((project / "reports/phase3/technology_units.json").read_text())["pdk"] == "neutral"
    put(project, "reports/phase3/antenna.json", json.dumps({"routing_incomplete": False}))
    put(project, "input/docs/native31.md",
        "The design requires DRC clean with both Magic and KLayout.\n")
    put(project, "phase1/generated_docs/L24_SIGNOFF.json", json.dumps({
        "doc_id": "L24_SIGNOFF", "fields": requirements.extract_signoff_requirements(project)}))
    # The unchanged, separately qualified DRV peripheral keeps its real
    # plan/census/judge. It adds no replacement LF root or stream configuration.
    calls = []
    # Same neutral public input as the original Step31 fixture; freeze it
    # before the original DRV checkpoint records the specification.
    put(project, "input/step_0_5ic_answers.json", "{}\n")
    put(project, "phase1/generated_docs/L8_TIMING_WAVEFORM.json", json.dumps({
        "doc_id": "L8_TIMING_WAVEFORM", "clock_domains": [
            {"role": "primary", "source_pin": "a", "period_ns": 24}]}))
    put(project, "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", json.dumps({
        "doc_id": "L19_CONSTRAINTS_PDK", "constraint_declarations": []}))
    _native31_synthesis_handoff(project, pdk, selected["netlist"])
    _native31_drv_peripheral(project, pdk, monkeypatch, calls, root=root, master=master)
    monkeypatch.setattr(lc._ce, "no_container_route", lambda: True)
    monkeypatch.setattr(R, "_PROV_SINK", project)
    monkeypatch.setattr(R, "_STEP_PDK_HASH_CACHE", {})
    monkeypatch.setattr(R, "_backend_parameter_values", lambda *_: {
        "pdk_root": str(root), "image_id": local_image.image})
    monkeypatch.setattr(B, "_parameters", lambda *_: (R, lc, pdk, ""))
    # Only short capability/version metadata probes are controlled here. The
    # physical signoff paths retain _docker_exec and its real logger.
    def probe(container, command, timeout=1800):
        import shlex
        argv = shlex.split(command)
        if len(argv) == 3 and argv[:1] == ["test"] and argv[1] in ("-f", "-d", "-e"):
            path = Path(argv[2])
            present = {"-f": path.is_file, "-d": path.is_dir, "-e": path.exists}[argv[1]]()
            return (0 if present else 1), "", ""
        if len(argv) == 2 and argv[0] == "cat":
            try:
                return 0, Path(argv[1]).read_text(), ""
            except OSError as error:
                return 1, "", str(error)
        if len(argv) == 2 and argv[0] == "printenv":
            value = os.environ.get(argv[1])
            return (0, value + "\n", "") if value is not None else (1, "", "")
        assert ("command -v" in command or "--version" in command
                or "-version" in command or command.endswith(" -v")), command
        return 0, "SOURCE_CONTROL neutral installed tool 1.0\n", ""
    monkeypatch.setattr(R, "_docker_exec_raw", probe)
    monkeypatch.setattr(R._dwd, "run_docker_supervised",
                        _native31_process_leaf(project, selected, case, calls))
    # Original admission is a fixture precondition, published through its
    # existing API, not a handcrafted signoff invocation or current record.
    basis, error = R._layout_basis(project, "spm", pdk, "")
    assert not error, error
    put(project, "reports/phase3/prestream_gate.json", json.dumps({
        "verdict": "PASS", "layout_digest": basis,
        "scope": "SOURCE_CONTROL retained upstream prestream fixture"}))
    R._ga.admit_gds(project, pnr / "spm.gds", basis,
                    R._layout_basis_paths(project, "spm"))
    from test_default_pnr_row_boundaries import _full_gds_lvs_transport
    _full_gds_lvs_transport(monkeypatch, project, pdk, selected,
        'lvs_error' if case == 'netgen_mismatch' else 'current', calls)
    # The real declaration emitter reads the actual L8/L9/L19 documents.
    cfg = lc.emit_config(project, pdk.name, project / 'phase3/native31_declared_config.json')
    assert cfg['CLOCK_PERIOD'] == 24 and cfg['CLOCK_PORT'] == 'a'
    if case == "legacy_feedback":
        (project / fill.DEFAULT_STREAM_REL).unlink()
    return project, pdk, selected, calls


def _native31_synthesis_handoff(project, pdk, source_netlist):
    """Existing Step14 transport-fixture pattern, with its real publisher.

    As in test_step14_report_producer_authorship.project_fixture, the neutral
    antecedent supplies synthesis-shaped materials and a digest-bound receipt;
    publish_handoff and bound_handoff validate them unchanged. No Step31
    provenance, native result, canonical report or current verdict is seeded.
    """
    import re
    import synth_handoff_netlist_check as handoff

    rtl = project / "phase2/stage1/rtl/spm.v"
    put(project, "input/project.json", json.dumps({"pdk": pdk.name}))
    put(project, "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
        json.dumps({"top_module": "spm"}))
    folder = project / "phase3/librelane/native31-antecedent-synthesis"
    text = re.sub(r"\bmodule\s+[A-Za-z_][A-Za-z0-9_$]*", "module spm",
                  source_netlist.read_text(), count=1)
    raw = put(folder, "spm.nl.v", text)
    mapped = put(project, "phase2/stage2/synth/spm_synth.v", text)
    prior = put(project, "phase3/librelane/native31-antecedent-header/spm.h.json",
                json.dumps({"module": "spm"}))
    cfg = {"meta": {"step": "Yosys.Synthesis"}, "PDK": pdk.name,
           "DESIGN_NAME": "spm", "VERILOG_FILES": [str(rtl)],
           "SYNTH_TIEHI_CELL": "TIE_H/Y", "SYNTH_TIELO_CELL": "TIE_L/Y"}
    resolved = put(project, "phase3/librelane/synthesis_resolved.json", json.dumps(cfg))
    put(folder, "config.json", json.dumps(cfg))
    put(folder, "state_out.json", json.dumps({"nl": str(raw), "metrics": {
        "design__instance_unmapped__count": 0, "synthesis__check_error__count": 0}}))
    put(folder, "reports/stat.json", json.dumps({"modules": {"\\spm": {"num_submodules": 0}}}))
    # CHECK reports are actual Yosys measurements of this neutral antecedent.
    # Mapping remains a software fixture; no native synthesis PASS is claimed.
    import subprocess
    masters = set(re.findall(r"(?m)^\s*(\w+)\s+\w+\s*\(", text)) - {"module"}
    assert len(masters) == 1, masters
    cells = put(folder, "neutral_cells.v", "\n".join(
        f"module {master}(input I, output Z); assign Z = I; endmodule" for master in masters))
    for name, sources in (("pre_synth_chk.rpt", [rtl]), ("chk.rpt", [cells, raw])):
        report = folder / "reports" / name
        script = '; '.join([
            'read_verilog ' + ' '.join('"' + str(path) + '"' for path in sources),
            'hierarchy -check -top spm', 'proc',
            'tee -o "' + str(report) + '" check'])
        done = subprocess.run(['yosys', '-Q', '-T', '-p', script],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stdout + done.stderr
        assert 'Found and reported 0 problems.' in report.read_text()
    put(folder, "pdk_root.json", json.dumps({"cli_pdk_root": "/pdk",
        "stated_by": "run_chain(pdk_root=...)", "mounts_under_it": []}))
    inputs = {"step": "Yosys.Synthesis", "config": sha(resolved),
              "config_files": {str(rtl): sha(rtl)}, "state_files": {str(prior): sha(prior)}}
    put(folder, "input_fingerprint.json", json.dumps(inputs))
    put(folder, "vibeic_receipt.json", json.dumps({"input": inputs, "sha256": {
        str(path.relative_to(folder)): sha(path) for path in folder.rglob("*") if path.is_file()}}))
    put(mapped.parent, "synth_inputs.json", json.dumps({"netlist": mapped.name}))
    handoff.publish_handoff(project, folder, mapped, "spm")
    assert handoff.bound_handoff(project)["verdict"] == "PASS"


def _observe_native31_closure_calls(monkeypatch):
    """Count real validator entries; no verdict, material or timing substitute."""
    import _physical_current as current
    import _native373_current as streams
    import librelane_fill_dfm as fill
    observed = {"totals": {"whole_stream": 0, "native_current": 0},
                "resolver_calls": []}
    original_fill = fill.validate_default_stream
    original_native = streams.read_current
    original_resolver = current.default_signoff_inputs

    def whole_stream(*args, **kwargs):
        observed["totals"]["whole_stream"] += 1
        return original_fill(*args, **kwargs)

    def native_current(*args, **kwargs):
        observed["totals"]["native_current"] += 1
        return original_native(*args, **kwargs)

    def resolver(*args, **kwargs):
        before = dict(observed["totals"])
        try:
            return original_resolver(*args, **kwargs)
        finally:
            observed["resolver_calls"].append({
                key: observed["totals"][key] - before[key] for key in before})

    monkeypatch.setattr(fill, "validate_default_stream", whole_stream)
    monkeypatch.setattr(streams, "read_current", native_current)
    monkeypatch.setattr(current, "default_signoff_inputs", resolver)
    return observed


def _checkpoint31_fixture(tmp_path, monkeypatch, local_image, case="current"):
    """Supply a normal installed Magic path before the original fixture freezes."""
    import shlex
    import sys
    from test_a_magic_receipt_binds_to_the_layout_it_read import _GOOD

    original_stream = _native31_retained_stream

    def installed_magic(*args, **kwargs):
        subject = original_stream(*args, **kwargs)
        _, pdk, root, _, _ = subject["subject"]
        cell_gds = root / "neutral/libs.ref/neutral/gds/cells.gds"
        cell_gds.parent.mkdir(parents=True, exist_ok=True)
        cell_gds.write_bytes(Path(pdk.cell_gds).read_bytes())
        pdk.cell_gds = str(cell_gds)
        put(root, "neutral/libs.tech/magic/neutral.magicrc", "# neutral native input\n")
        put(root, "neutral/libs.tech/magic/neutral.tech", "tech\n format 32\nend\n")
        return subject

    monkeypatch.setattr(sys.modules[__name__], "_native31_retained_stream", installed_magic)
    project, pdk, selected, calls = _native31_runtime_fixture(
        tmp_path, monkeypatch, local_image, case)
    attempt = {"first": True}

    def leaf(container, command, marker, **kwargs):
        process = _native31_process_leaf(project, selected,
            "netgen_mismatch" if attempt["first"] else case, calls)
        result = process(container, command, marker, **kwargs)
        argv = shlex.split(command)
        if "magic" in argv and "SPICE_OUT=" not in command:
            # The native recipe prints its actual design, layout and technology.
            # This is a neutral process write, before the real logger hashes it.
            report = project / R._MAGIC_SIGNOFF_DRC_REL
            text = (_GOOD.replace("chip_top", selected["design"])
                    .replace("ab" * 32, sha(selected["gds"]))
                    .replace("/pdk/t.tech", str(Path(R._pdk_magicrc(pdk)).with_suffix(".tech")))
                    .replace("/c/" + selected["design"] + ".gds", str(selected["gds"])))
            report.write_text(text)
            return result[0], text, result[2]
        return result

    monkeypatch.setattr(R._dwd, "run_docker_supervised", leaf)
    from test_default_pnr_row_boundaries import _full_gds_lvs_transport
    _full_gds_lvs_transport(monkeypatch, project, pdk, selected,
        lambda: 'lvs_error' if attempt['first'] or case == 'netgen_mismatch' else 'current', calls)
    return project, pdk, selected, calls, attempt


@pytest.mark.parametrize("case", ["current", "changed_report", "missing_magic"])
def test_public_default31_retains_valid_drc_across_failed_lvs(
        tmp_path, monkeypatch, local_image, case):
    """Two real public windows; only costly native process leaves are neutral."""
    import shlex
    import _physical_current as current

    project, pdk, selected, calls, attempt = _checkpoint31_fixture(
        tmp_path, monkeypatch, local_image)

    def native_counts(items):
        rows = [shlex.split(x["command"]) for x in items if isinstance(x, dict)]
        return {"klayout": sum("klayout" in row for row in rows),
                "magic_drc": sum("magic" in row and
                    not any("SPICE_OUT=" in arg for arg in row) for row in rows)}

    first_rc, first, _, _, _ = _public_native31_window(
        project, pdk, monkeypatch, case="first_lvs_mismatch", native_processes=calls)
    first_calls = list(calls)
    checkpoint = project / "reports/phase3/direct_current_drc.json"
    checkpoint_bytes = checkpoint.read_bytes()
    first_observation = json.loads((project / "NATIVE_OWNER_OBSERVATION.json").read_text())
    assert first_rc != 0 and first["result"]["producer_verdict"] == "FAIL", first
    assert not first["canonical_pass"]
    assert current.read_direct_half(project, "drc")["verdict"] == "CURRENT"
    assert native_counts(first_calls) == {"klayout": 1, "magic_drc": 1}
    magic = json.loads((project / R._MAGIC_SIGNOFF_DRC_JSON_REL).read_text())
    assert magic["passed"] and magic["summary"]["layout_evidence_tier"] == "invocation"
    if case == "changed_report":
        path = project / "reports/phase3/drc_signoff.rpt"
        path.write_text(path.read_text() + "\nchanged canonical report\n")
    elif case == "missing_magic":
        (project / R._MAGIC_SIGNOFF_DRC_REL).unlink()
    attempt["first"] = False
    offset = len(calls)
    second_rc, second, retained, _, _ = _public_native31_window(
        project, pdk, monkeypatch, case=case, native_processes=calls)
    adopted = next((receipt['retained_drc_checkpoint']
                    for receipt in second['result']['canonical_receipts']
                    if receipt.get('retained_drc_checkpoint')), None)
    observed = {"case": case, "first": first_observation,
        "second": json.loads((project / "NATIVE_OWNER_OBSERVATION.json").read_text()),
        "first_native_calls": native_counts(first_calls),
        "second_native_calls": native_counts(calls[offset:]),
        "original_checkpoint_sha256": hashlib.sha256(checkpoint_bytes).hexdigest(),
        "adopted": adopted,
        "scope": "Source-only neutral native leaves, not physical DRC/LVS acceptance"}
    put(project, "DRC_CHECKPOINT_OBSERVATION.json", json.dumps(observed, indent=2))
    assert second_rc == 0 and second["canonical_pass"] is True, second
    assert second["result"]["producer_verdict"] == "PASS"
    assert second["result"]["canonical_step_result"]["status"] == "PASS"
    assert retained and retained["current_inputs"]
    assert current.read_direct_half(project, "drc")["verdict"] == "CURRENT"
    if adopted:
        assert case == "current"
        assert checkpoint.read_bytes() == checkpoint_bytes
        assert adopted["origin"]["sha256"] == observed["original_checkpoint_sha256"]
        assert adopted["declared_engines"] == ["klayout", "magic"]
        assert observed["second_native_calls"] == {"klayout": 0, "magic_drc": 0}
        assert all(row["original_native_invocation"]["measured"] is True
                   and row["original_native_invocation"]["exit_code"] == 0
                   for row in adopted["evidence"])
    else:
        assert observed["second_native_calls"] == {"klayout": 1, "magic_drc": 1}
    assert any(x.get('native_step') == 'Netgen.LVS' for x in calls[offset:] if isinstance(x, dict))
