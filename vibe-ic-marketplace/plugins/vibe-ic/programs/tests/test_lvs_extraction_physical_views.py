"""Step 31 extracts the layout with the physical views place-and-route used.

MEASURED on a pad-ring die (gf180mcuD, IC path, 2026-09-29): a step-31 LVS in
a process that had not run place-and-route (a bounded `--entry-step 31`
window starts from `_detect_pdk`) read no IO LEF and the distribution tech LEF
instead of the via-legalized one.  Magic then loaded every pad master from the
PDK's `mag/` library as a full transistor-level layout, both power-aware
compares mismatched and the plain compare crashed netgen (rc 139).  The same
DEF matched uniquely inside the run that routed it.

Pinned here:
* the bounded window restores the tech LEF, the LEFs PnR read and the pad
  library GDS views from the run's own records before anything reads the PDK
  (the GDS admission basis hashes it; step 31 extracts with it);
* a tech-LEF record that does not verify refuses the window (NOT_MEASURED,
  named) and the unverified file never becomes a macro LEF;
* a window that routes again (`pnr`, `enclosing_pnr`, `enclosing_phase3`)
  restores nothing;
* an extraction that read a placed master from a library path stops before
  netgen with NOT_MEASURED naming the master; a clean extraction reaches it.
"""
from __future__ import annotations

import hashlib
import importlib
import json

import pytest
from pathlib import Path
from types import SimpleNamespace

mod = importlib.import_module("phase3_one_shot_runner")

_MOVED = "/elsewhere/run/proj"          # where the records were written
_IO_LEF = "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__fill1.lef"
_IO_GDS = "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/gds/gf180mcu_fd_io.gds"


def _pdk():
    """A PDK object as `_detect_pdk` returns it: distribution views only."""
    return mod.PdkConfig(name="calpdk", liberty="/pdk/lib/cells.lib",
                         tech_lef="/pdk/techlef/cells__nom.tlef",
                         cell_lef="/pdk/lef/cells.lef", cell_gds=None,
                         site="core", drc_deck=None)


def _recorded_run(tmp_path: Path, *, sha_ok: bool = True):
    project = tmp_path / "proj"
    pnr = mod._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    staged = pnr / "active_via_legalized.tlef"
    staged.write_text("VERSION 5.8 ;\nEND LIBRARY\n")
    sha = hashlib.sha256(staged.read_bytes()).hexdigest()
    pdk = _pdk()
    reports = project / "reports"
    (reports / "phase3").mkdir(parents=True)
    moved_tlef = f"{_MOVED}/phase3/stage3/pnr/active_via_legalized.tlef"
    (reports / "pdk_via_patch_legalization.json").write_text(json.dumps({
        "status": "APPLIED", "source_tech_lef": pdk.tech_lef,
        "derived_tech_lef": moved_tlef,
        "derived_sha256": sha if sha_ok else "0" * 64}))
    (reports / "phase3/physical_view_inventory.json").write_text(json.dumps({
        "schema": "vibe-ic/physical-view-inventory/1",
        "read_lef_paths": [moved_tlef, pdk.cell_lef, _IO_LEF]}))
    (reports / "phase3/io_pad_chip_top.json").write_text(json.dumps({
        "verdict": "WROTE", "chip_top_verilog": "phase3/chip_top_io.v"}))
    return project, pdk


def _window(tmp_path, monkeypatch, *, sha_ok=True):
    """A real `--entry-step 31 --exit-step 31` window over the recorded run.
    Faked: the pad-library resolver's container query, the PDK hasher's
    container query and the site's EDA dispatch -- each captures the PDK
    object it is handed."""
    project, pdk = _recorded_run(tmp_path, sha_ok=sha_ok)
    # Reuse the current caller's original-input fixture. Only dependency
    # selection and the expensive native transport are substituted.
    _default_reroute_control(project, pdk, monkeypatch, '31')
    import copy
    import execution_backend_producers as producers
    import librelane_contract as ll
    producer_pdk = copy.deepcopy(pdk)
    monkeypatch.setattr(producers, '_parameters', lambda *_:
                        (mod, ll, producer_pdk, 'SOURCE_CONTROL_NOT_EXECUTED'))
    monkeypatch.setenv("VIBEIC_PHASE3_WINDOW_RUN_ID", "lvsfix31")
    monkeypatch.setattr(mod, "_discover_padring_io_views",
                        lambda pdk, container: ([_IO_LEF], [_IO_GDS]))
    seen = {}

    def snapshot(view):
        return {"tech_lef": view.tech_lef, "macro_lefs": list(view.macro_lefs),
                "macro_gds": list(view.macro_gds)}

    def basis(project_, top, view, container):
        seen.setdefault("basis", snapshot(view))
        return "", "stop at admission (captured)"

    def dispatch(project_, top, view, args, site, gate, run_id):
        seen[site] = snapshot(view)
        return mod.StepResult(site, "NOT_MEASURED", 0.0, "captured",
                              reason_class="not_executed")

    monkeypatch.setattr(mod, "_layout_basis", basis)
    monkeypatch.setattr(mod, "_direct_flow_window", dispatch)
    args = SimpleNamespace(entry_step="31", exit_step="31", container="c",
                           die_um=None, util=None, spare_density=None)
    mod._run_phase3_window(project, "spm", pdk, args,
                           mod._phase3_window_sites("31", "31"))
    seen["project"] = project
    return seen


def test_a_step31_window_reads_the_views_pnr_used(tmp_path, monkeypatch):
    seen = _window(tmp_path, monkeypatch)
    # Admission is deliberately over the fresh distribution identity that
    # admitted the stream. The Step-31 producer then restores the recorded
    # extraction views on its own PDK object before either native instrument;
    # the coupled owner controls exercise that second endpoint.
    view = seen["basis"]
    assert view == {"tech_lef": "/pdk/techlef/cells__nom.tlef",
                    "macro_lefs": [], "macro_gds": []}


def test_local_checkpoint_restores_installed_pad_gds(tmp_path, monkeypatch):
    project, pdk = _recorded_run(tmp_path)
    calls = []

    def discover(view, container):
        calls.append(container)
        return [_IO_LEF], [_IO_GDS]

    monkeypatch.setattr(mod, "_discover_padring_io_views", discover)
    result = mod._restore_recorded_physical_views(project, pdk, "")
    assert calls == [""]
    assert _IO_GDS in pdk.macro_gds
    assert result["macro_gds"] == [_IO_GDS]


def test_a_tech_lef_record_that_does_not_verify_refuses_the_window(tmp_path, monkeypatch):
    """PnR routed with a tech LEF this tree cannot prove it still holds: the
    window measures with neither LEF, and the unverified file never enters
    the PDK as a macro LEF through the inventory."""
    seen = _window(tmp_path, monkeypatch, sha_ok=False)
    assert seen["basis"]["tech_lef"] == "/pdk/techlef/cells__nom.tlef"
    assert "lvs" not in seen and "drc" not in seen
    doc = json.loads(next((seen["project"] / "reports/orchestrator/windows")
                          .glob("*/phase3_one_shot.json")).read_text())
    row = doc["steps"][0]
    assert row["status"] == "NOT_MEASURED"
    assert "via-legalized tech LEF PnR used" in row["detail"]
    project, pdk = _recorded_run(tmp_path / "direct", sha_ok=False)
    monkeypatch.setattr(mod, "_discover_padring_io_views",
                        lambda pdk, container: ([_IO_LEF], [_IO_GDS]))
    done = mod._restore_recorded_physical_views(project, pdk, "c")
    assert done["refused"]
    assert not any(p.endswith("active_via_legalized.tlef") for p in pdk.macro_lefs)
    assert not str(pdk.tech_lef).endswith("active_via_legalized.tlef")


@pytest.mark.parametrize("entry,exit_", [
    ("15", "22"), ("17", "20"), ("20", "22"),
])
def test_a_window_that_routes_again_does_not_restore(tmp_path, monkeypatch, entry, exit_):
    """Default contract migration: exact current-row dispatch, not an alias.

    The real window/row driver/producer reaches a controlled non-PASS native
    boundary. SOURCE_CONTROL ancestors are not physical routing evidence.
    """
    project, pdk = _recorded_run(tmp_path)
    monkeypatch.setenv("VIBEIC_PHASE3_WINDOW_RUN_ID", f"lvsfix{entry}{exit_}")
    seen = _default_reroute_control(project, pdk, monkeypatch, entry)
    selected = mod._phase3_window_sites(entry, exit_)
    ids = mod._phase3_window_steps(entry, exit_)
    # Step 32 now belongs between detailed routing and Step 22 in the one
    # canonical order; a span crossing it uses the shared native row driver.
    if exit_ == '22':
        assert ids.index('21') < ids.index('32') < ids.index('22')
    assert selected == (["default_backend"] if '32' in ids else ["default_pnr"]), selected
    args = SimpleNamespace(entry_step=entry, exit_step=exit_, container="c",
                           die_um="100,100", util=0.4)
    rc = mod._run_phase3_window(project, "view_unit", pdk, args, selected)
    _save_reroute_control(project, seen, rc)
    assert seen["restore_calls"] == 0, seen
    assert seen["producer_steps"] == [entry], seen
    assert seen["launcher_steps"] == [entry], seen
    assert rc == 1, seen
    assert seen["consumer_steps"] == (['15'] if entry == '15' else []), seen
    assert seen["macro_lefs"] == []
    assert seen["tech_lef"] == "/pdk/techlef/cells__nom.tlef"


# --- the extraction guard ----------------------------------------------------

_DEF = ("VERSION 5.8 ;\nDESIGN top ;\nCOMPONENTS 2 ;\n"
        "    - u_inv gf180mcu_fd_sc_mcu7t5v0__inv_1 + PLACED ( 0 0 ) N ;\n"
        "    - u_fill gf180mcu_fd_io__fill1 + FIXED ( 0 0 ) N ;\n"
        "END COMPONENTS\nPINS 1 ;\n- a + NET a ;\nEND PINS\n"
        "NETS 1 ;\n- a + ROUTED met1 ;\nEND NETS\nEND DESIGN\n")
#: Magic's own line, as the calibration log `cal_views_magic_positive.log`
#: records it for the same master.
_LIBRARY_READ = ("Cell gf180mcu_fd_io__fill1 read from path "
                 "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/mag\n")


def _extract(tmp_path, monkeypatch, magic_says: str):
    project = tmp_path / "proj"
    pdk = _pdk()
    ext_dir = mod._pl.extracted_dir(project)
    ext_dir.mkdir(parents=True)
    spice_out = ext_dir / "top_extracted.sp"
    pnr = mod._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    def_file = pnr / "top.def"
    def_file.write_text(_DEF)
    netlist = pnr / "top_pnr.v"
    netlist.write_text("module top(input a); endmodule\n")
    calls = []

    def fake_docker_exec(container, cmd, timeout=None, **_):
        if "magic -dnull" in cmd:
            calls.append("magic")
            spice_out.write_text(".subckt top a\n.ends\n")
            (ext_dir / mod._mio.FEEDBACK_NAMES[0]).write_text("")
            return (0, magic_says + "0 errors\nMAGIC_EXT2SPICE_DONE", "")
        if "netgen -batch lvs" in cmd:
            calls.append("netgen")
            rpt = project / "reports/phase3/lvs.rpt"
            rpt.parent.mkdir(parents=True, exist_ok=True)
            rpt.write_text("Final result: Circuits match uniquely.\n")
            return (0, "", "")
        return (0, "", "")

    monkeypatch.setattr(mod, "_docker_exec", fake_docker_exec)
    res = mod._run_extraction_lvs(project, "top", pdk, "c", def_file, netlist,
                                  "/nonexistent.magicrc", "/setup.tcl", 0.0)
    return res, calls, project


def test_an_extraction_of_library_layouts_never_reaches_netgen(tmp_path, monkeypatch):
    res, calls, project = _extract(tmp_path, monkeypatch, _LIBRARY_READ)
    assert "netgen" not in calls
    assert res.status == "NOT_MEASURED", res.detail
    assert res.extras["finding"] == "LVS_EXTRACTION_VIEW_NOT_ABSTRACT"
    assert set(res.extras["library_layout_masters"]) == {"gf180mcu_fd_io__fill1"}
    verdict = json.loads((project / "reports/phase3/lvs_verdict.json").read_text())
    assert verdict["finding"] == "LVS_EXTRACTION_VIEW_NOT_ABSTRACT"
    assert verdict["status"] != "PASS"


def test_an_abstract_extraction_reaches_netgen(tmp_path, monkeypatch):
    _res, calls, _ = _extract(tmp_path, monkeypatch, "")
    assert calls[-1] == "netgen"


@pytest.mark.parametrize("control,directory,placed", [
    ("plain", "library_plain", "neutral_master"),
    ("space_path", "library root", "neutral_master"),
    ("unplaced", "library root", "other_master"),
])
def test_native_magic_library_log_reaches_current_extraction_refusal(
        tmp_path, monkeypatch, control, directory, placed):
    """Real Magic log/parser component; runner tool transport is SOURCE_CONTROL.

    Built-in scmos and authored MAG geometry supply no PDK/PV/signoff credit.
    The DEF is the helper's authored population, not a native DEF-read claim.
    """
    import hashlib
    import subprocess
    import sys
    import lvs_layout_view_census as census
    library = tmp_path / directory
    library.mkdir()
    work = tmp_path / "native_work"
    work.mkdir()
    mag = library / "neutral_master.mag"
    mag.write_text("magic\ntech scmos\ntimestamp 0\n<< metal1 >>\n"
                   "rect 0 0 10 10\n<< end >>\n")
    rcfile = tmp_path / "empty.magicrc"
    rcfile.write_text("")
    script = ("tech load scmos\nload " + json.dumps(str(mag)) +
              "\nselect top cell\nextract all\nputs {OWN_TOY_LOAD_END}\nquit -noprompt\n")
    (tmp_path / "native.tcl").write_text(script)
    argv = ["magic", "-dnull", "-noconsole", "-rcfile", str(rcfile)]
    native = subprocess.run(argv, input=script, cwd=work, text=True,
                            capture_output=True, timeout=30)
    log = native.stdout + native.stderr
    (tmp_path / "magic.stdout").write_text(native.stdout)
    (tmp_path / "magic.stderr").write_text(native.stderr)
    (tmp_path / "magic.log").write_text(log)
    # The existing owning runner fixture now consumes this actual log and its
    # declared current population. Its native Magic/netgen transport stays
    # controlled; no successful netgen/PV measurement is invented.
    def_text = ("VERSION 5.8 ;\nDESIGN top ;\nCOMPONENTS 1 ;\n"
                f"- u0 {placed} + PLACED ( 0 0 ) N ;\nEND COMPONENTS\n"
                "PINS 1 ;\n- a + NET a ;\nEND PINS\nNETS 1 ;\n"
                "- a + ROUTED met1 ;\nEND NETS\nEND DESIGN\n")
    monkeypatch.setattr(sys.modules[__name__], "_DEF", def_text)
    parsed = census.masters_read_from_library(log, census.def_component_masters(def_text))
    result, calls, project = _extract(tmp_path, monkeypatch, log)
    verdict = json.loads((project / "reports/phase3/lvs_verdict.json").read_text())
    ext = library / "neutral_master.ext"
    observed = {"control": control, "scope": "native Magic log/parser; runner SOURCE_CONTROL, not PV",
                "native_argv": argv, "native_rc": native.returncode,
                "mag_sha256": hashlib.sha256(mag.read_bytes()).hexdigest(),
                "DEF_sha256": hashlib.sha256(def_text.encode()).hexdigest(),
                "log_sha256": hashlib.sha256(log.encode()).hexdigest(),
                "ext_present": ext.is_file(),
                "actual_read_lines": [line for line in log.splitlines() if "read from path" in line],
                "census": parsed, "step_status": result.status,
                "next_netgen_count": calls.count("netgen"), "current_verdict": verdict}
    (tmp_path / "native_census_observed.json").write_text(json.dumps(observed, indent=2) + "\n")
    assert native.returncode == 0 and ext.is_file(), observed
    assert f"Cell neutral_master read from path {library}" in log, observed
    if control == "unplaced":
        assert parsed == {}, observed
        assert calls.count("netgen") == 1, observed
    else:
        assert parsed == {"neutral_master": str(library)}, observed
        assert result.status == "NOT_MEASURED", observed
        assert result.extras["finding"] == "LVS_EXTRACTION_VIEW_NOT_ABSTRACT", observed
        assert calls.count("netgen") == 0, observed
        assert verdict["status"] != "PASS", observed


def _default_reroute_control(project, pdk, monkeypatch, first, *, missing=False):
    """SOURCE_CONTROL context/config/ancestor data; real input/producer bodies.

    The existing launcher is refused. No measured native result or successful
    physical ancestor is supplied by this neutral transport.
    """
    import execution_policy
    import execution_backend_producers as producers
    import execution_backend_worker as worker
    import librelane_contract as ll
    import drv_stage_receipts as stages
    from _ppa import timing
    for name in (execution_policy.ENV, execution_policy._CAPABILITY_FD_ENV,
                 'VIBEIC_EXECUTION_AUTH_SOCKET'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    sdc = 'create_clock -name clk -period 10 [get_ports clk]\n'
    files = {
        'input/step_0_5ic_answers.json': '{}\n',
        'input/submission_template/neutral.json': '{}\n',
        'phase2/stage2/synth/post_dft_netlist.v':
            'module view_unit(input clk); endmodule\n',
        'phase2/stage2/synth/view_unit_synth.v':
            'module view_unit(input clk); endmodule\n',
        'phase2/stage2/constraints/current.sdc': sdc,
        'phase3/stage3/pnr/constraint.sdc': sdc,
        'phase3/stage3/pnr/step15.constraint.sdc': sdc,
        'phase3/stage3/pnr/floorplan.def': 'VERSION 5.8 ;\nDESIGN view_unit ;\nEND DESIGN\n',
        'phase3/stage3/pnr/routed.def': 'VERSION 5.8 ;\nDESIGN view_unit ;\nEND DESIGN\n',
        'phase3/stage3/pnr/pdn.done': '{"scope":"SOURCE_CONTROL predecessor"}\n',
        'phase3/stage3/pnr/post_cts.def': 'VERSION 5.8 ;\nDESIGN view_unit ;\nEND DESIGN\n',
        'source_control_state.json': '{"scope":"SOURCE_CONTROL predecessor"}\n',
    }
    if missing:
        files.pop('phase3/stage3/pnr/post_cts.def')
    for rel, text in files.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    if not missing:
        # Step 20 consumes Step 19's immutable, hash-bound CTS handoff, not a
        # bare post_cts.def. Model the owning producer's actual receipt shape
        # so the 20->22 positive reaches its controlled native boundary.  The
        # missing control deliberately creates neither this receipt nor its
        # source/state, and therefore still proves launch refusal.
        import librelane_contract as ll
        cts_rel = Path('phase3/librelane/source-control-cts/00-openroad-cts')
        cts_root = project / cts_rel
        cts_root.mkdir(parents=True)
        cts_source = cts_root / 'view_unit.def'
        cts_source.write_bytes(
            (project / 'phase3/stage3/pnr/post_cts.def').read_bytes())
        cts_state = cts_root / 'state_out.json'
        cts_state.write_text(json.dumps({
            'def': str(cts_source.resolve()),
            'metrics': {'vibeic__cts__max_fanout': 3}}))
        fingerprint = {'step': 'OpenROAD.CTS', 'config': '0' * 64,
                       'config_files': {}, 'state_files': {}}
        (cts_root / 'input_fingerprint.json').write_text(json.dumps(fingerprint))
        (cts_root / 'pdk_root.json').write_text(
            json.dumps({'scope': 'SOURCE_CONTROL neutral PDK'}))
        (cts_root / 'invocation.log').write_text(
            'SOURCE_CONTROL native-owner receipt; tool not executed\n')
        cts_report = cts_root / 'cts.rpt'
        cts_report.write_text('Total number of Clock Roots: 1.\n'
                              'Total number of Buffers Inserted: 2.\n'
                              'Total number of Sinks: 9.\n')
        (cts_root / 'openroad-cts.log').write_text(
            'SOURCE_CONTROL CTS transcript; tool not executed\n')
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        ll.write_json(cts_root / 'vibeic_receipt.json', {
            'input': fingerprint,
            'sha256': {str(path.relative_to(cts_root)): digest(path)
                       for path in cts_root.iterdir() if path.is_file()}})
        handoff = project / 'reports/phase3/librelane_cts_handoff.json'
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text(json.dumps({
            'program': 'execution_backend_producers._cts_split',
            'selected': 'librelane',
            'scope': 'SOURCE_CONTROL native-owner handoff; no native CTS claim',
            'chain': {'OpenROAD.CTS': str(cts_rel)},
            'measured_state': str(cts_state.relative_to(project)),
            'measured_state_sha256': digest(cts_state),
            'views': {'post_cts_def': {
                'source': str(cts_source.resolve()),
                'source_sha256': digest(cts_source),
                'dest': 'phase3/stage3/pnr/post_cts.def',
                'dest_sha256': digest(
                    project / 'phase3/stage3/pnr/post_cts.def')},
                'cts_rpt': {
                    'source': str(cts_report.resolve()),
                    'source_sha256': digest(cts_report),
                    'dest': str(cts_report.relative_to(project)),
                    'dest_sha256': digest(cts_report)}}}))
    seen = {'scope': 'SOURCE_CONTROL launcher reachability, not native PnR',
            'restore_calls': 0, 'producer_steps': [], 'launcher_steps': [], 'consumer_steps': [],
            'input_sha256': {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(project.rglob('*')) if p.is_file()}}
    restore = mod._restore_recorded_physical_views
    def observed_restore(*args, **kwargs):
        seen['restore_calls'] += 1
        return restore(*args, **kwargs)
    monkeypatch.setattr(mod, '_restore_recorded_physical_views', observed_restore)
    monkeypatch.setattr(mod, '_discover_padring_io_views',
                        lambda *args: ([_IO_LEF], [_IO_GDS]))
    def legacy(*args, **kwargs):
        pytest.fail('Default reached a legacy enclosing/direct window')
    monkeypatch.setattr(mod, '_direct_flow_window', legacy)
    monkeypatch.setattr(mod, '_phase3_window_enclosing', legacy)
    # Resolve the supplied neutral PDK/context, not a real installed PDK.
    monkeypatch.setattr(mod, '_backend_parameter_values', lambda *args: {
        'pdk_name': pdk.name, 'pdk_root': str(project),
        'image_id': 'SOURCE_CONTROL_NOT_EXECUTED',
        'state_in': str(project / 'source_control_state.json')})
    monkeypatch.setattr(mod, '_detect_pdk', lambda *args: pdk)
    monkeypatch.setattr(producers, '_parameters', lambda *args:
                        (mod, ll, pdk, 'SOURCE_CONTROL_NOT_EXECUTED'))
    produce = producers.produce
    def observed_produce(proj, params):
        seen['producer_steps'].append(str(params['step_id']))
        return produce(proj, params)
    monkeypatch.setattr(producers, 'produce', observed_produce)
    consume = worker.execute_current_step
    def observed_consume(*args, **kwargs):
        seen['consumer_steps'].append(str(kwargs['step_id']))
        return consume(*args, **kwargs)
    monkeypatch.setattr(worker, 'execute_current_step', observed_consume)
    monkeypatch.setattr(ll, 'flow_segment', lambda *args, **kwargs: [
        'OpenROAD.GlobalPlacement', 'OpenROAD.RepairDesignPostGPL',
        'OpenROAD.DetailedPlacement'])
    def configs(proj, image, name, ids, **kwargs):
        folder = proj / 'phase3/librelane' / kwargs['folder']
        folder.mkdir(parents=True, exist_ok=True)
        result = {sid: folder / (sid + '.json') for sid in ids}
        for path in result.values():
            path.write_text(json.dumps({'DESIGN_NAME': 'view_unit', 'STA_CORNERS': ['nom'],
                                        'scope': 'SOURCE_CONTROL configuration'}))
        return result
    monkeypatch.setattr(ll, 'resolve_step_configs', configs)
    monkeypatch.setattr(mod, '_resolved_cell_policy', lambda configs, *args, **kwargs: (configs, {}))
    def refused(*args, **kwargs):
        seen['macro_lefs'] = list(pdk.macro_lefs)
        seen['tech_lef'] = pdk.tech_lef
        seen['launcher_steps'].append(first)
        if first == '15':
            return (mod.StepResult('source_control_floorplan_stop', 'FAIL', 0,
                                   'SOURCE_CONTROL named launcher refusal; no native PnR'), {})
        raise ll.Refusal('LL_STEP_FAILED', 'SOURCE_CONTROL named launcher refusal; no native PnR')
    monkeypatch.setattr(ll, 'run_chain', refused)
    monkeypatch.setattr(mod, '_prepare_librelane_floorplan_for_route', refused)
    if first == '15':
        # Existing synthesis-before-floorplan unit transport, not native PASS.
        monkeypatch.setattr(mod, 'step_prepnr', lambda *args: mod.StepResult(
            'source_control_preparation', 'PASS', 0, 'SOURCE_CONTROL preparation only'))
        monkeypatch.setattr(mod, '_chip_path_requests_pad_ring', lambda *args: True)
        deck = project / 'phase2/stage2/constraints/current.sdc'
        monkeypatch.setattr(timing, 'asic_sdc_for_pnr', lambda *args: {
            'text': sdc, 'path': str(deck), 'step7_sha256': hashlib.sha256(deck.read_bytes()).hexdigest(),
            'deck_sha256': hashlib.sha256(sdc.encode()).hexdigest(),
            'regenerated': None, 'derivation': 'SOURCE_CONTROL current SDC'})
        monkeypatch.setattr(stages, 'synth_stage_supervised', lambda *args, **kwargs: None)
    return seen


def _save_reroute_control(project, seen, rc):
    seen['rc'] = rc
    reports = list((project / 'reports/orchestrator/windows').glob('*/phase3_one_shot.json'))
    seen['bounded_report'] = json.loads(reports[0].read_text()) if reports else None
    (project.parent / 'reroute_observed.json').write_text(json.dumps(seen, indent=2) + '\n')


def test_default_reroute_missing_current_input_stops_before_launcher(tmp_path, monkeypatch):
    project, pdk = _recorded_run(tmp_path)
    seen = _default_reroute_control(project, pdk, monkeypatch, '20', missing=True)
    monkeypatch.setenv('VIBEIC_PHASE3_WINDOW_RUN_ID', 'missing_current_cts')
    selected = mod._phase3_window_sites('20', '22')
    assert selected == ['default_backend']
    assert mod._phase3_window_steps('20', '22') == ['20', '21', '32', '22']
    args = SimpleNamespace(entry_step='20', exit_step='22', container='c',
                           die_um='100,100', util=0.4)
    rc = mod._run_phase3_window(project, 'view_unit', pdk, args, selected)
    _save_reroute_control(project, seen, rc)
    assert rc == 1 and seen['restore_calls'] == 0, seen
    assert seen['producer_steps'] == seen['launcher_steps'] == [], seen
    assert seen['consumer_steps'] == [], seen
    assert seen['bounded_report']['verdict'] == 'NOT_MEASURED', seen
    assert 'post_cts.def' in seen['bounded_report']['steps'][0]['detail'], seen


@pytest.mark.parametrize('entry,exit_,expected', [
    ('15', '22', 'enclosing_phase3'), ('17', '20', 'enclosing_pnr'),
    ('20', '22', 'enclosing_phase3'),
], ids=['15-22-pnr', '17-20-enclosing_pnr', '20-22-enclosing_pnr'])
def test_legacy_reroute_window_preserves_no_restore_contract(
        tmp_path, monkeypatch, entry, exit_, expected):
    """Explicit legacy transport coverage; Default cases above never mode-escape."""
    import execution_policy
    project, pdk = _recorded_run(tmp_path)
    for name in (execution_policy.ENV, execution_policy._CAPABILITY_FD_ENV,
                 'VIBEIC_EXECUTION_AUTH_SOCKET'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    original_request = execution_policy.request
    monkeypatch.setattr(execution_policy, 'request', lambda: dict(original_request(), mode='ultra'))
    monkeypatch.setattr(execution_policy, 'dispatch_ordinary_rows', lambda *args: None)
    monkeypatch.setenv('VIBEIC_PHASE3_WINDOW_RUN_ID', f'legacy{entry}{exit_}')
    selected = mod._phase3_window_sites(entry, exit_)
    assert selected == [expected], selected
    if exit_ == '22':
        assert '32' in mod._phase3_window_steps(entry, exit_)
    seen = []
    def dispatch(*args, **kwargs):
        seen.append((list(pdk.macro_lefs), pdk.tech_lef))
        return mod.StepResult('pnr', 'NOT_MEASURED', 0, 'SOURCE_CONTROL legacy transport',
                              reason_class='not_executed')
    monkeypatch.setattr(mod, '_direct_flow_window', dispatch)
    monkeypatch.setattr(mod, '_phase3_window_enclosing', dispatch)
    monkeypatch.setattr(mod, '_restore_recorded_physical_views', lambda *args:
                        pytest.fail('Legacy rerouting restored prior views'))
    monkeypatch.setattr(mod, '_phase3_window_full_gate_audit', lambda project, ids: {
        sid: {'status': 'NOT_MEASURED', 'reasons': ['SOURCE_CONTROL legacy transport only']}
        for sid in ids})
    args = SimpleNamespace(entry_step=entry, exit_step=exit_, container='c')
    assert mod._run_phase3_window(project, 'view_unit', pdk, args, selected) == 1
    assert seen == [([], '/pdk/techlef/cells__nom.tlef')]
