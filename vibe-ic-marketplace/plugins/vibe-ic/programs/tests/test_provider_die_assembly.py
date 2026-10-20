"""Provider continuation source contracts; no native geometry or PV claims."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import die_finishing_gen as finishing
import execution_policy as policy
import tapeout_readiness_check as readiness
import tapeout_precheck as precheck


def profile(project):
    path = project / finishing.PROVIDER_TARGET_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provider": "wafer.space", "technical_target": {
        "slot": "1x1", "dimensions_um": [400, 500],
        "packaging": "bare_die", "purchase_or_reserved_slot": False},
        "precheck_source": "input/submission_template/official"}))
    return path


def test_provider_target_uses_existing_frozen_input_directory(tmp_path):
    parameters = {}
    runtime = {"project": tmp_path, "policy": {"mode": "default"}}
    absent = policy._fixed_inputs(runtime, "37.5ic", parameters=parameters)
    assert finishing.PROVIDER_TARGET_REL not in absent
    path = profile(tmp_path)
    official = path.parent / "official"
    official.mkdir()
    entry = official / "precheck.py"
    entry.write_text("# neutral official source dependency\n")
    selected = policy._fixed_inputs(runtime, "37.5ic", parameters=parameters)
    assert selected[finishing.PROVIDER_TARGET_REL] == path
    assert parameters["resolved_input_manifest"]["files"][finishing.PROVIDER_TARGET_REL] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert selected.keys() - absent.keys() == {
        finishing.PROVIDER_TARGET_REL, str(entry.relative_to(tmp_path))}
    assert parameters["resolved_input_manifest"]["files"][str(entry.relative_to(tmp_path))] == hashlib.sha256(entry.read_bytes()).hexdigest()


def test_normal_finishing_uses_declared_engineering_target(tmp_path):
    routed = tmp_path / "phase3/stage3/pnr/routed.def"
    routed.parent.mkdir(parents=True)
    routed.write_text("UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 100000 100000 ) ;\nEND DESIGN\n")
    assert finishing.die_size(tmp_path, tmp_path / "a.gds", None, None)[:2] == (100, 100)
    path = profile(tmp_path)
    before = path.read_bytes()
    assert finishing.die_size(tmp_path, tmp_path / "a.gds", None, None)[:2] == (400, 500)
    assert finishing.die_size(tmp_path, tmp_path / "a.gds", 600, 700)[:2] == (600, 700)
    state = finishing.die_id_state({}, {}, tmp_path)
    assert state["state"] == "NOT_APPLICABLE"
    assert "non-CoB" in state["reason"] and "no operator" not in state["reason"]
    assert path.read_bytes() == before


def test_normal_native_service_entry_uses_official_adapter_without_skip(tmp_path):
    profile(tmp_path)
    gds = tmp_path / "chip_top.gds"
    gds.write_bytes(b"neutral source-only layout placeholder")
    d = tmp_path / finishing._DEF_REL
    d.parent.mkdir(parents=True)
    d.write_text("DIEAREA ( 0 0 ) ( 400000 500000 ) ;\nEND DESIGN\n")
    seen = []
    def runner(command, timeout):
        seen.append(command)
        return 1, "neutral tool refusal", ""
    def image_resolver(*args):
        pytest.fail("an explicit native official checkout does not dispatch another image")
    result = readiness.evaluate(tmp_path, layout=gds, top="chip_top", runner=runner,
                                image_resolver=image_resolver)
    assert result.verdict != "PASS"
    command, = seen
    assert command[:2] == [sys.executable, str(Path(readiness.__file__).with_name("wafer_space_precheck.py"))]
    assert command[command.index("--official-source") + 1] == str(tmp_path / "input/submission_template/official")
    assert "--with-initial-state" in command
    assert not {"--skip", "--from", "--to", "--cob", "--id"}.intersection(command)
    state = json.loads(Path(command[command.index("--with-initial-state") + 1]).read_text())
    assert state["def"] == str(d)


def test_malformed_engineering_dimensions_refuse(tmp_path):
    path = profile(tmp_path)
    value = json.loads(path.read_text())
    value["technical_target"]["dimensions_um"] = ["400", 500]
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="positive finite"):
        finishing.die_size(tmp_path, tmp_path / "a.gds", None, None)


@pytest.mark.parametrize("operator_verdict", ["PASS", "FAIL", "NOT_DETERMINED"])
def test_normal_wrapper_uses_new_provider_over_retained_self_catalogue(
        tmp_path, monkeypatch, operator_verdict):
    from test_owner_self_tapeout_catalogue import fixture
    import submission_template_check as catalogue
    project, _, _ = fixture(tmp_path)
    assert catalogue.catalogue_selects_self_tapeout(project)[0]
    switch = project / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True)
    switch.write_text(json.dumps({"steps": {step: "direct" for step in ("26", "31", "34", "37")}}))
    (project / "input/project.json").write_text(json.dumps({"pdk": "gf180mcuD"}))
    profile(project)
    seen = []
    def run(command, timeout):
        # Neutral subprocess leaves only; the real normal wrapper/merge/main
        # selects and invokes the authority and preserves its actual verdict.
        operator = command[1].endswith("tapeout_readiness_check.py")
        if operator:
            seen.append(command)
        verdict = operator_verdict if operator else "PASS"
        dest = Path(command[command.index("--json") + 1])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({"verdict": verdict, "steps": [],
                                   "reason": "neutral source-only authority transport"}))
        return (0 if verdict == "PASS" else 1), "neutral transport", ""
    monkeypatch.setattr(precheck, "default_runner", run)
    dest = project / "merged.json"
    rc = precheck.main([str(project), "--json", str(dest)])
    report = json.loads(dest.read_text())
    operator = next(arm for arm in report["arms"] if arm["arm"] == "operator")
    assert operator["state"] == "RAN", "selected provider was hidden by old SELF catalogue"
    command, = seen
    assert command[command.index("--slot") + 1] == "1x1"
    assert operator["verdict"] == operator_verdict
    assert report["verdict"] == operator_verdict
    assert rc == (0 if operator_verdict == "PASS" else 1)
    assert "engineering" in operator["reason"]
    assert "purchased" not in operator["reason"]


@pytest.mark.parametrize("case", ["current", "changed_gds", "refused_precheck", "missing_step"])
def test_release_reader_requires_current_complete_operator_evidence(tmp_path, case):
    def evidence(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return finishing._release_file(path)
    gds = evidence("neutral.gds", {"neutral": True})
    files = {name: evidence(name + ".json", {}) for name in [
        "source_admission", "source_stream", "raw_gds", "seal_report", "sealed_gds",
        "instruction", "finished_def"]}
    steps = []
    for i in range(16):
        state = evidence(f"state-{i}.json", {"metrics": {}})
        files[f"official_state_{i + 1}"] = state
        steps.append({"state_out": state})
    precheck = {"verdict": "FAIL" if case == "refused_precheck" else "PASS",
                "returncode": 0, "all_steps_requested": True, "input_unchanged": True,
                "steps": steps[:-1] if case == "missing_step" else steps, "output": gds}
    files["official_precheck"] = evidence("operator.json", precheck)
    record = {"producer": "die_finishing_gen", "kind": "provider_die_assembly",
              "verdict": "PASS", "source_project": str(tmp_path), "output": gds,
              "basis": {"files": files}}
    path = tmp_path / "release.json"
    path.write_text(json.dumps(record))
    if case == "changed_gds":
        (tmp_path / "neutral.gds").write_text("changed")
    if case == "current":
        assert finishing.read_admitted_release(tmp_path, path)["gds"] == tmp_path / "neutral.gds"
    else:
        with pytest.raises(ValueError):
            finishing.read_admitted_release(tmp_path, path)


@pytest.mark.parametrize("case,expected", [("timestamps", "PASS"), ("native_red", "FAIL"),
                                          ("changed_geometry", "NOT_MEASURED"),
                                          ("missing_count", "NOT_MEASURED")])
def test_provider_pv_reader_binds_real_gds_records_and_preserves_native_counts(
        tmp_path, case, expected):
    from test_gds_canonical_digest import _stream, _RUN_A, _RUN_B
    from wafer_space_precheck import read_signoff_evidence
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return finishing._release_file(path)
    # Neutral source-control GDS records, not claimed native PV receipts.
    subject, final = tmp_path / "subject.gds", tmp_path / "delivered.gds"
    subject.write_bytes(_stream(_RUN_A, _RUN_A, width=1400 if case == "changed_geometry" else 1000))
    final.write_bytes(_stream(_RUN_B, _RUN_B))
    files = {name: write(tmp_path / (name + ".json"), {}) for name in [
        "source_admission", "source_stream", "raw_gds", "seal_report", "sealed_gds",
        "instruction", "finished_def"]}
    ids = ["ReadLayout", "Hierarchy", "Size", "GenerateID", "Render", "KLayout.Density",
           "Checker.KLayoutDensity", "ZeroArea", "CheckerZero", "KLayout.Antenna",
           "Checker.KLayoutAntenna", "Magic.DRC", "Checker.MagicDRC", "KLayout.DRC",
           "Checker.KLayoutDRC", "WriteLayout"]
    count = 3 if case == "native_red" else None if case == "missing_count" else 0
    metrics = {"klayout__density_error__count": 0, "klayout__antenna_error__count": 0,
               "klayout__drc_error__count": count, "magic__drc_error__count": 7}
    steps = []
    for i, sid in enumerate(ids):
        folder = tmp_path / f"{i + 1:02d}-stage"
        write(folder / "state_in.json", {"gds": str(subject)})
        state = write(folder / "state_out.json", {"gds": str(subject), "metrics": metrics})
        write(folder / "config.json", {"meta": {"step": sid}, "ERROR_ON_MAGIC_DRC": False})
        (folder / "COMMANDS").write_text("neutral source-control invocation; no EDA was run\n")
        for kind in ("density", "antenna", "drc"):
            write(folder / "reports" / (kind + ".klayout.json"), {"total": count if kind == "drc" else 0})
        files[f"official_state_{i + 1}"] = state
        steps.append({"folder": str(folder), "state_out": state})
    output = finishing._release_file(final)
    files["official_precheck"] = write(tmp_path / "operator.json", {
        "verdict": "PASS", "returncode": 0, "all_steps_requested": True,
        "input_unchanged": True, "steps": steps, "expected_steps": ids, "output": output})
    release = tmp_path / "release.json"
    write(release, {"producer": "die_finishing_gen", "kind": "provider_die_assembly",
                    "verdict": "PASS", "source_project": str(tmp_path), "output": output,
                    "basis": {"files": files}})
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()}
    result = read_signoff_evidence(tmp_path, release)
    assert result["verdict"] == expected
    assert result["gds_sha256"] == output["sha256"]
    row = result["rows"]["drc"]
    if case == "native_red":
        assert row["value"] == 3 and row["verdict"] == "FAIL"
    elif case == "timestamps":
        assert row["value"] == 0 and row["verdict"] == "PASS"
        assert row["equivalence"]["input"]["sha256"] != output["sha256"]
        assert row["equivalence"]["input"]["canonical_digest"] == row["equivalence"]["output"]["canonical_digest"]
        assert result["disclosures"][0]["value"] == 7
        assert result["disclosures"][0]["error_on_magic_drc"] is False
    else:
        assert row["verdict"] == "NOT_MEASURED"
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after, "the PV consumer must be read-only"


@pytest.mark.parametrize("case,expected", [
    ("reordered_cells", "PASS"), ("shape", "NOT_MEASURED"),
    ("text", "NOT_MEASURED"), ("units", "NOT_MEASURED"),
    ("reference", "NOT_MEASURED")])
def test_provider_pv_reader_uses_strict_native_semantic_comparison(tmp_path, case, expected):
    import struct
    import pya
    from _gds_geometry import _iter_records
    from wafer_space_precheck import read_signoff_evidence

    def layout(change=None):
        result = pya.Layout()
        result.dbu = 0.002 if change == "units" else 0.001
        top, leaf = result.create_cell("top"), result.create_cell("leaf")
        layer = result.layer(1, 0)
        leaf.shapes(layer).insert(pya.Box(0, 0, 11 if change == "shape" else 10, 10))
        top.insert(pya.CellInstArray(leaf.cell_index(), pya.Trans(11 if change == "reference" else 10, 20)))
        top.shapes(layer).insert(pya.Text("changed" if change == "text" else "electrical_label", pya.Trans()))
        return result

    subject, final = tmp_path / "subject.gds", tmp_path / "delivered.gds"
    layout().write(str(final))
    if case == "reordered_cells":
        header, cells, tail, current = [], [], [], None
        for rt, dt, payload in _iter_records(final.read_bytes()):
            record = struct.pack(">HBB", len(payload) + 4, rt, dt) + payload
            if rt == 5:
                current = []
            if current is not None:
                current.append(record)
                if rt == 7:
                    cells.append(b"".join(current))
                    current = None
            elif cells:
                tail.append(record)
            else:
                header.append(record)
        subject.write_bytes(b"".join(header + cells[::-1] + tail))
    else:
        layout(case).write(str(subject))

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return finishing._release_file(path)

    files = {name: write(tmp_path / (name + ".json"), {}) for name in [
        "source_admission", "source_stream", "raw_gds", "seal_report", "sealed_gds",
        "instruction", "finished_def"]}
    ids = ["ReadLayout", "Hierarchy", "Size", "GenerateID", "Render", "KLayout.Density",
           "Checker.KLayoutDensity", "ZeroArea", "CheckerZero", "KLayout.Antenna",
           "Checker.KLayoutAntenna", "Magic.DRC", "Checker.MagicDRC", "KLayout.DRC",
           "Checker.KLayoutDRC", "WriteLayout"]
    metrics = {"klayout__density_error__count": 0, "klayout__antenna_error__count": 0,
               "klayout__drc_error__count": 0, "magic__drc_error__count": 0}
    steps = []
    for i, sid in enumerate(ids):
        folder = tmp_path / f"{i + 1:02d}-stage"
        write(folder / "state_in.json", {"gds": str(subject)})
        state = write(folder / "state_out.json", {"gds": str(subject), "metrics": metrics})
        write(folder / "config.json", {"meta": {"step": sid}, "ERROR_ON_MAGIC_DRC": False})
        (folder / "COMMANDS").write_text("neutral source-control record; no physical verification run\n")
        for kind in ("density", "antenna", "drc"):
            write(folder / "reports" / (kind + ".klayout.json"), {"total": 0})
        files[f"official_state_{i + 1}"] = state
        steps.append({"folder": str(folder), "state_out": state})
    output = finishing._release_file(final)
    files["official_precheck"] = write(tmp_path / "operator.json", {
        "verdict": "PASS", "returncode": 0, "all_steps_requested": True,
        "input_unchanged": True, "steps": steps, "expected_steps": ids, "output": output})
    release = tmp_path / "release.json"
    write(release, {"producer": "die_finishing_gen", "kind": "provider_die_assembly",
                    "verdict": "PASS", "source_project": str(tmp_path), "output": output,
                    "basis": {"files": files}})
    result = read_signoff_evidence(tmp_path, release)
    assert result["verdict"] == expected
    assert all(row["verdict"] == expected for row in result["rows"].values())
    if expected == "PASS":
        assert all("KLayout.LayoutDiff" in row["equivalence"]["method"] for row in result["rows"].values())
    for row in result["rows"].values():
        if "KLayout.LayoutDiff" in row["equivalence"]["method"]:
            assert row["equivalence"]["flags"] == int(pya.LayoutDiff.Silent)


@pytest.mark.parametrize("provider", [None, "wafer.space", "other.provider"])
def test_normal_density_materializes_selected_provider_encoding(tmp_path, monkeypatch, provider):
    import copy
    import librelane_fill_dfm as fill

    if provider is not None:
        target = profile(tmp_path)
        value = json.loads(target.read_text())
        value["provider"] = provider
        target.write_text(json.dumps(value))
    original = {"boundary_layer": [235, 0], "window_um": None, "max_passes": 8,
                "mfg_grid_um": 0.005, "keepout_edge_um": 1.0,
                "_derivation": {"density_floor_pct": 30}, "layers": [
                    {"name": "metal1", "layer": [34, 0], "target": 0.34,
                     "max": 0.95, "space": 0.98, "space_to_metal": 2.0,
                     "width": 1.4, "fill_datatype": 4}]}
    monkeypatch.setattr(fill, "_density_source", lambda *a: ({}, "map", "lef", "deck"))
    monkeypatch.setattr(fill, "build_metal_fill_config", lambda *a: copy.deepcopy(original))
    routed = tmp_path / "routed.def"
    routed.write_text("neutral placed-instance source control\n")
    monkeypatch.setattr(fill, "_placed_keepout_boxes", lambda *a: {
        "dbu": 1000, "total": 0, "boxes": [], "source": str(routed)})

    class ReachedNative(Exception):
        pass

    observed = []
    def native_leaf(command, log):
        config_path = Path(command[command.index("--config") + 1])
        observed.append(json.loads(config_path.read_text()))
        raise ReachedNative("configuration reached the existing native filler")
    monkeypatch.setattr(fill, "_run_logged", native_leaf)
    with pytest.raises(ReachedNative):
        fill.top_up_density(tmp_path, "neutral-image", tmp_path, "open-pdk",
                            tmp_path / "source.gds", tmp_path / "density.json", "normal-fill")
    config, = observed
    expected = copy.deepcopy(original["layers"][0])
    expected["fill_datatype"] = 0 if provider == "wafer.space" else 4
    assert config["layers"] == [expected]
    assert config["keepout_edge_um"] == original["keepout_edge_um"]
    assert config["window_um"] == original["window_um"]
    assert config["mfg_grid_um"] == original["mfg_grid_um"]
    assert config["_derivation"]["density_floor_pct"] == original["_derivation"]["density_floor_pct"]
    assert bool(config["_derivation"].get("provider_fill_encoding")) == (provider == "wafer.space")


@pytest.fixture
def bond_geometry(tmp_path):
    """Native neutral geometry; the operator transport below is source-only."""
    import klayout.db as k
    path = profile(tmp_path)
    pdk = tmp_path / 'input/pdk'
    pdk.mkdir()
    (pdk / 'layers.lyp').write_text('<layer-properties><properties>'
        '<source>BondOpening 73/4@1</source></properties></layer-properties>')
    (pdk / 'io.lef').write_text('MACRO neutral_pad\n CLASS PAD INOUT ;\n'
                               ' SIZE 40 BY 50 ;\nEND neutral_pad\n')
    value = json.loads(path.read_text())
    value.pop('precheck_source', None)
    value['technical_target']['origin_um'] = [0, 0]
    value['bond_pad_edge_distance'] = {
        'opening_layer': {'name': 'BondOpening', 'layer_properties': 'input/pdk/layers.lyp'},
        'io_lefs': ['input/pdk/io.lef']}
    path.write_text(json.dumps(value))
    layout = k.Layout(); layout.dbu = 0.001
    top = layout.create_cell('neutral_top')
    pad = layout.create_cell('neutral_pad')
    opening = layout.create_cell('neutral_opening')
    layer = layout.layer(73, 4)
    opening.shapes(layer).insert(k.Box(0, 0, 10000, 20000))
    pad.insert(k.CellInstArray(opening.cell_index(), k.Trans()))
    # Hierarchical openings + rotation + an array: all must reach top coordinates.
    top.insert(k.CellInstArray(pad.cell_index(), k.Trans(20000, 30000)))
    top.insert(k.CellInstArray(pad.cell_index(), k.Trans(k.Trans.R90, 300000, 290000)))
    top.insert(k.CellInstArray(pad.cell_index(), k.Trans(150000, 120000),
                              k.Vector(20000, 0), k.Vector(0, 30000), 2, 2))
    # Neither a large non-pad polygon nor an overhanging label is a pad opening.
    top.shapes(layer).insert(k.Box(-500000, -500000, 800000, 900000))
    opening.shapes(layer).insert(k.Text('not geometry', k.Trans(900000, 900000)))
    gds = tmp_path / 'neutral.gds'; layout.write(str(gds))
    return tmp_path, path, gds


def _bond_readiness(project, gds, runroot):
    def transport(command, timeout):
        # Only the operator subprocess is substituted. Exercise the real
        # readiness consumer, real evidence parser, and native pad measurement.
        for i, step in enumerate(readiness.SHUTTLES[readiness.DEFAULT_SHUTTLE].ladder, 1):
            if step.cob_only:
                continue
            folder = runroot / f'{i:02d}-{readiness._slug(step.step_id)}'
            folder.mkdir(parents=True)
            (folder / 'state_out.json').write_text('{}')
        return 0, 'neutral operator transport, no native PV claim', ''
    return readiness.evaluate(project, layout=gds, top='neutral_top', rundir=runroot,
                              image_resolver=lambda image, pull: image, runner=transport)


@pytest.mark.parametrize('case,expected', [
    ('missing_limit', 'NOT_DETERMINED'), ('declared_pass', 'PASS'),
    ('declared_fail', 'FAIL'), ('missing_layer', 'NOT_DETERMINED'),
    ('missing_master', 'NOT_DETERMINED'), ('invalid_limit', 'NOT_DETERMINED'),
    ('missing_authority', 'NOT_DETERMINED')])
def test_bond_opening_geometry_reaches_provider_precheck(bond_geometry, case, expected):
    project, path, gds = bond_geometry
    value = json.loads(path.read_text()); rule = value['bond_pad_edge_distance']
    if case == 'declared_pass':
        rule['max_distance_um'] = 200
    elif case == 'declared_fail':
        rule['max_distance_um'] = 199
    elif case == 'missing_layer':
        rule['opening_layer']['name'] = 'AbsentOpening'
    elif case == 'missing_master':
        (project / 'input/pdk/io.lef').write_text('MACRO not_a_pad\n CLASS CORE ;\nEND not_a_pad\n')
    elif case == 'invalid_limit':
        rule['max_distance_um'] = True
    elif case == 'missing_authority':
        del value['bond_pad_edge_distance']
    path.write_text(json.dumps(value))
    before = gds.read_bytes()
    report = _bond_readiness(project, gds, project / 'operator')
    assert report.verdict == expected, report.reason
    measured = report.as_dict()['bond_pad_edge_distance']
    assert measured == json.loads((project / 'operator/bond_pad_edge_distance.json').read_text())
    assert gds.read_bytes() == before
    if case in ('missing_limit', 'declared_pass', 'declared_fail', 'invalid_limit'):
        assert measured['distances_um'] == {'left': 20, 'bottom': 30, 'right': 100, 'top': 200}
        assert measured['opening_count'] == 6
        assert measured['assembly']['strategy'] == 'preserve_source_placement'
        assert measured['assembly']['applied_offset_um'] == [0, 0]
        assert measured['input']['sha256'] == hashlib.sha256(before).hexdigest()
        assert measured['verdict'] == {'missing_limit': 'MANUAL_REVIEW', 'declared_pass': 'PASS',
                                       'declared_fail': 'FAIL', 'invalid_limit': 'NOT_MEASURED'}[case]
    else:
        assert measured['verdict'] == 'NOT_MEASURED'
        assert measured['reason']


def test_bond_measurement_preserves_real_operator_refusal(bond_geometry):
    from _hostpaths import require_repo
    project, _, gds = bond_geometry
    repo = require_repo()
    import shutil
    retained = project / 'retained-refusal'
    shutil.copytree(repo / 'vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/shuttle_precheck_refusal', retained)
    report = readiness.evaluate(project, layout=gds, top='neutral_top', rundir=retained,
                               image_resolver=lambda image, pull: image,
                               runner=lambda command, timeout: (1, '', ''))
    assert report.verdict == 'FAIL'
    assert report.failed_steps == ['KLayout.CheckSize']
    # Keep retained operator evidence immutable; local geometry report is written
    # separately when replaying read-only captured receipts.


@pytest.fixture
def bond_assembly(bond_geometry):
    """Neutral technical lineage with actual native opening geometry."""
    import _gds_admission as admission
    project, path, gds = bond_geometry
    reports = project / 'reports/phase3'; reports.mkdir(parents=True)
    routed = project / 'phase3/stage3/pnr/routed.def'; routed.parent.mkdir(parents=True)
    routed.write_text('UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 400000 500000 ) ;\nEND DESIGN\n')
    raw = routed.with_name('raw.gds'); raw.write_bytes(gds.read_bytes())
    def write(dest, data):
        dest.write_text(json.dumps(data)); return finishing._release_file(dest)
    write(reports / 'prestream_gate.json', {'verdict': 'PASS', 'layout_digest': 'neutral-source-control'})
    admission.admit_gds(project, raw, 'neutral-source-control', [routed])
    write(reports / 'fill_librelane.json', {'default_stream': {
        'stream': str(raw), 'stream_sha256': finishing._release_file(raw)['sha256']}})
    seal = reports / 'seal.json'
    extent = {'outer': {'um': [0, 0, 400, 500]}, 'inner': {'um': [5, 5, 395, 495]}}
    write(seal, {'seal_ring': {'state': 'PASS', 'gds_in': str(raw), 'gds_out': str(gds),
        'core_clearance': {'state': 'MEASURED', 'population_empty': False, 'encroaching_polygons': 0},
        'ring_check': {'ring_extent': extent}}, 'artefacts': {'routed_def_in': str(routed)}})
    steps = [{'state_out': write(reports / f'state-{i}.json', {'scope': 'neutral source control'})}
             for i in range(16)]
    operator = reports / 'operator.json'
    write(operator, {'producer': 'wafer_space_precheck', 'returncode': 0, 'verdict': 'PASS',
        'all_steps_requested': True, 'input_unchanged': True, 'expected_steps': list(range(16)),
        'steps': steps, 'input': finishing._release_file(gds), 'output': finishing._release_file(gds),
        'slot': '1x1', 'packaging': 'bare_die', 'assigned_id': None, 'official_entry': {'neutral': True}})
    dest = reports / 'assembly.json'
    return project, path, gds, operator, seal, dest


@pytest.mark.parametrize('limit,expected', [(None, 'MANUAL_REVIEW'), (199, 'FAIL'), (200, 'PASS')])
def test_provider_assembly_does_not_admit_unreviewed_bond_geometry(bond_assembly, limit, expected):
    project, path, gds, operator, seal, dest = bond_assembly
    value = json.loads(path.read_text())
    if limit is not None:
        value['bond_pad_edge_distance']['max_distance_um'] = limit
    path.write_text(json.dumps(value))
    try:
        admitted = finishing.publish_provider_release(project, dest, source_project=project,
            instruction=path, precheck=operator, finishing=seal)
        actual = 'PASS'
    except ValueError as exc:
        actual = next((state for state in ('MANUAL_REVIEW', 'FAIL')
                       if 'bond_pad_edge_distance: ' + state in str(exc)), str(exc))
    assert actual == ('PASS' if expected == 'MANUAL_REVIEW' else expected)
    edge_path = project / 'reports/phase3/bond_pad_edge_distance.json'
    if expected in ('PASS', 'MANUAL_REVIEW'):
        readback = finishing.read_admitted_release(project, dest)
        assert readback['basis'] == admitted['basis']
        assert readback['basis']['bond_pad_edge_distance']['verdict'] == expected
        assert readback['basis']['bond_pad_edge_distance']['distances_um']['top'] == 200
        assert readback['basis']['files']['bond_pad_edge_distance'] == finishing._release_file(edge_path)
        assert readback['basis']['platform_accepted'] is False
        assert readback['basis']['provider_precheck']['accepted'] is False
        final = _bond_readiness(project, gds, project / 'final-readiness')
        assert final.verdict == ('NOT_DETERMINED' if expected == 'MANUAL_REVIEW' else 'PASS')
        assert final.bond_pad_edge_distance['verdict'] == expected
    else:
        assert not dest.exists()
        assert json.loads(edge_path.read_text())['verdict'] == 'FAIL'


def test_normal_native_precheck_retains_manual_bond_assembly(bond_assembly):
    project, path, gds, operator, seal, dest = bond_assembly
    value = json.loads(path.read_text()); value['precheck_source'] = 'input/official'
    path.write_text(json.dumps(value))
    finished = project / finishing._DEF_REL
    finished.write_bytes((finished.parent / 'routed.def').read_bytes())
    (project / finishing._REPORT_REL).write_bytes(seal.read_bytes())
    runroot = project / 'operator-run'
    def transport(command, timeout):
        # Only the official subprocess is substituted; actual readiness,
        # technical producer/reader and native opening measurement execute.
        for i, step in enumerate(readiness.SHUTTLES[readiness.DEFAULT_SHUTTLE].ladder, 1):
            if step.cob_only:
                continue
            folder = runroot / f'{i:02d}-{readiness._slug(step.step_id)}'
            folder.mkdir(parents=True)
            (folder / 'state_out.json').write_text('{}')
        output = runroot / 'processed.gds'; output.write_bytes(gds.read_bytes())
        receipt = json.loads(operator.read_text())
        receipt['output'] = finishing._release_file(output)
        (runroot / 'provider_precheck.json').write_text(json.dumps(receipt))
        return 0, 'neutral operator source transport, no native PV claim', ''
    final = readiness.evaluate(project, layout=gds, top='neutral_top', rundir=runroot, runner=transport)
    assert final.verdict == 'NOT_DETERMINED'
    assert final.bond_pad_edge_distance['verdict'] == 'MANUAL_REVIEW'
    admitted = finishing.read_admitted_release(project, Path('reports/phase3/provider_die_assembly.json'))
    edge_path = project / 'reports/phase3/bond_pad_edge_distance.json'
    assert admitted['basis']['bond_pad_edge_distance']['verdict'] == 'MANUAL_REVIEW'
    assert admitted['basis']['bond_pad_edge_distance']['distances_um'] == final.bond_pad_edge_distance['distances_um']
    assert admitted['basis']['files']['bond_pad_edge_distance'] == finishing._release_file(edge_path)
    assert admitted['basis']['platform_accepted'] is False
    assert admitted['basis']['provider_precheck']['accepted'] is False


@pytest.mark.parametrize('final_present', [True, False])
def test_native_provider_bond_measurement_uses_actual_final_output(bond_geometry, final_present):
    import klayout.db as k
    project, path, gds = bond_geometry
    value = json.loads(path.read_text()); value['precheck_source'] = 'input/official'
    path.write_text(json.dumps(value))
    finished = project / finishing._DEF_REL; finished.parent.mkdir(parents=True)
    finished.write_text('DIEAREA ( 0 0 ) ( 400000 500000 ) ;\nEND DESIGN\n')
    runroot = project / 'operator'
    def transport(command, timeout):
        for i, step in enumerate(readiness.SHUTTLES[readiness.DEFAULT_SHUTTLE].ladder, 1):
            if step.cob_only:
                continue
            folder = runroot / f'{i:02d}-{readiness._slug(step.step_id)}'; folder.mkdir(parents=True)
            (folder / 'state_out.json').write_text('{}')
        if final_present:
            layout = k.Layout(); layout.read(str(gds))
            layout.top_cell().transform(k.Trans(10000, 15000))
            layout.write(str(runroot / 'processed.gds'))
        return 0, 'neutral operator source transport, no native PV claim', ''
    report = readiness.evaluate(project, layout=gds, top='neutral_top', rundir=runroot, runner=transport)
    assert report.verdict == 'NOT_DETERMINED'
    edge = report.as_dict()['bond_pad_edge_distance']
    if final_present:
        assert edge['distances_um'] == {'left': 30, 'bottom': 45, 'right': 90, 'top': 185}
        assert edge['input']['sha256'] != hashlib.sha256(gds.read_bytes()).hexdigest()
        assert edge['verdict'] == 'MANUAL_REVIEW'
    else:
        assert edge['verdict'] == 'NOT_MEASURED'
        assert edge['distances_um'] is None
