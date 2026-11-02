"""The real Phase-3 GDS and SPEF finishing call sites retain tool bytes."""
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402
import provenance_output_hash_completeness_check as C  # noqa: E402
import foundry_handoff_package_check as H  # noqa: E402


def _sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _rows(project):
    return [json.loads(line) for line in (project / "provenance.jsonl").read_text().splitlines()]


def _project(tmp_path):
    project = tmp_path / "run"
    pnr = project / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    minimal_def = (
        "VERSION 5.8 ;\nDIVIDERCHAR \"/\" ;\nBUSBITCHARS \"[]\" ;\n"
        "DESIGN unit ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "DIEAREA ( 0 0 ) ( 1000 1000 ) ;\n"
        "COMPONENTS 0 ;\nEND COMPONENTS\nPINS 0 ;\nEND PINS\n"
        "NETS 0 ;\nEND NETS\nEND DESIGN\n")
    (pnr / "unit.def").write_text(minimal_def)
    (pnr / "routed.def").write_text(minimal_def)
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"steps": {"34": "direct"}}))
    (project / "provenance.jsonl").write_text("")
    R.set_invocation_provenance_sink(project)
    return project


def _immutable_chain(tmp_path):
    """Use the shipped transform writer to build two retained links."""
    project = _project(tmp_path)
    pnr = project / "phase3/stage3/pnr"
    source, middle, head = (pnr / name for name in
                            ("raw.gds", "filled.gds", "final.gds"))
    for path, data in ((source, b"stream"), (middle, b"stream + fill"),
                       (head, b"stream + fill + finish")):
        path.write_bytes(data)
    (project / "provenance.jsonl").write_text(json.dumps({
        "record": "invocation", "tool": "layout", "exit_code": 0,
        "outputs": {source.relative_to(project).as_posix(): _sha(source.read_bytes())},
    }) + "\n")
    assert R._declare_immutable_transform(
        project, source, middle, "fill", "layout", "fill")
    assert R._declare_immutable_transform(
        project, middle, head, "finish", "layout", "finish")
    assert C.audit(project)[0] == "PASS"
    return project, source, middle, head


@pytest.mark.parametrize("damage", [
    "missing_source", "wrong_input_hash", "reversed_order",
    "undeclared_middle", "failed_source", "missing_inputs",
    "redeclared_source_before_input", "changed_retained_source",
    "missing_retained_middle", "failed_transform", "missing_transform_status",
])
def test_transform_input_requires_earlier_successful_retained_output(
        tmp_path, damage):
    project, source, middle, _head = _immutable_chain(tmp_path)
    rows = _rows(project)
    source_rel = source.relative_to(project).as_posix()
    if damage == "missing_source":
        rows.pop(0)
    elif damage == "wrong_input_hash":
        rows[1]["inputs"][source_rel] = _sha(b"different input")
    elif damage == "reversed_order":
        rows[0], rows[1] = rows[1], rows[0]
    elif damage == "undeclared_middle":
        rows.pop(1)
    elif damage == "failed_source":
        rows[0]["exit_code"] = 1
    elif damage == "missing_inputs":
        rows[1]["inputs"] = {}
    elif damage == "redeclared_source_before_input":
        newer = _sha(b"new stream")
        source.write_bytes(b"new stream")
        rows.insert(1, {"tool": "layout", "exit_code": 0,
                        "outputs": {source_rel: newer}})
    elif damage == "changed_retained_source":
        source.write_bytes(b"new stream")
        rows.append({"tool": "layout", "exit_code": 0,
                     "outputs": {source_rel: _sha(source.read_bytes())}})
    elif damage == "missing_retained_middle":
        rows.pop(1)
        middle.unlink()
    elif damage == "failed_transform":
        rows[2]["exit_code"] = 1
    elif damage == "missing_transform_status":
        rows[2].pop("exit_code")
    (project / "provenance.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows))
    verdict, findings = C.audit(project)
    assert verdict == "FAIL", damage
    assert "PROVENANCE_TRANSFORM_INPUT_INVALID" in {f.rule for f in findings}, damage


def test_magic_fill_retains_stream_and_declares_finished_head(tmp_path, monkeypatch):
    project = _project(tmp_path)
    import execution_policy
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "ultra"})
    pdk = SimpleNamespace(name="neutral", drc_deck=None, stdcell_marker_layer=None,
                          dummy_fill=None, same_net_heal=None,
                          port_label_restore=None, metal_fill_density=None)
    monkeypatch.setattr(R, "_layout_basis", lambda *a: ("basis", None))
    monkeypatch.setattr(R._ga, "gate_passed", lambda *a: True)
    monkeypatch.setattr(R, "_vacuous_on_unrouted", lambda *a: None)
    monkeypatch.setattr(R, "_streamout_top", lambda *a: ("unit", ""))
    monkeypatch.setattr(R, "publish_database_unit_declaration",
                        lambda *a: {"verdict": "PASS", "reason": "fixture"})
    monkeypatch.setattr(R, "publish_tapeout_declarations",
                        lambda *a: {"published": [], "not_determined": [],
                                    "already_answered": []})

    def magic(_project, _top, _pdk, _container, path):
        path.write_bytes(b"streamed layout")
        R._log_invocation("magic gds write", 0, 1, outputs=[path])
        return True, "streamed"

    def fill(_project, _top, _pdk, path, _container):
        path.write_bytes(path.read_bytes() + b" + fill")
        return True, "filled"

    monkeypatch.setattr(R, "_magic_def_to_gds", magic)
    monkeypatch.setattr(R, "_gds_grid_snap", lambda *a: (False, "no snap"))
    monkeypatch.setattr(R, "_die_finishing", lambda *a: (False, "no seal"))
    monkeypatch.setattr(R, "_step34_gds_tool_arm", lambda *a: None)
    monkeypatch.setattr(R, "_density_metal_fill", fill)
    monkeypatch.setattr(R, "_die_density_fill", lambda *a: (False, "no die fill"))
    monkeypatch.setattr(R, "_restore_port_labels_if_missing",
                        lambda *a: (False, "no labels"))
    monkeypatch.setattr(R, "_gds_substance_gate", lambda *a: None)
    try:
        result = R._step_gds_direct(project, "unit", pdk, "fake")
    finally:
        R.set_invocation_provenance_sink(None)
    assert result.status == "PASS", result.detail
    rows = _rows(project)
    tool = next(r for r in rows if r.get("record") == "invocation")
    source, source_hash = next(iter(tool["outputs"].items()))
    target = "phase3/stage3/pnr/unit.gds"
    assert source != target, (source, target)
    chain = [r for r in rows if r.get("record") == "declared_transform"]
    assert [r["producing_step"] for r in chain] == [
        "gds:density_metal_fill", "gds:finishing"]
    assert chain[0]["inputs"] == {source: source_hash}
    assert chain[1]["inputs"] == chain[0]["outputs"]
    assert (project / source).read_bytes() == b"streamed layout"
    assert (project / target).read_bytes() == b"streamed layout + fill"
    assert chain[-1]["outputs"] == {target: _sha(b"streamed layout + fill")}
    assert H.layout_member_sources(project) == {"unit.gds": project / target}
    assert C.audit(project)[0] == "PASS"
    (project / target).write_bytes(b"edited without a transform")
    assert "PROVENANCE_HASH_MISMATCH" in {f.rule for f in C.audit(project)[1]}


def test_partial_failing_fill_cannot_publish_a_finished_gds(tmp_path, monkeypatch):
    project = _project(tmp_path)
    import execution_policy
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "ultra"})
    pdk = SimpleNamespace(name="neutral", drc_deck=None, stdcell_marker_layer=None,
                          dummy_fill=None, same_net_heal=None,
                          port_label_restore=None,
                          metal_fill_density={"layers": [{"layer": [7, 0]}]})
    monkeypatch.setattr(R, "_layout_basis", lambda *a: ("basis", None))
    monkeypatch.setattr(R._ga, "gate_passed", lambda *a: True)
    monkeypatch.setattr(R, "_vacuous_on_unrouted", lambda *a: None)
    monkeypatch.setattr(R, "_streamout_top", lambda *a: ("unit", ""))
    monkeypatch.setattr(R, "publish_database_unit_declaration",
                        lambda *a: {"verdict": "PASS", "reason": "fixture"})
    monkeypatch.setattr(R, "publish_tapeout_declarations",
                        lambda *a: {"published": [], "not_determined": [],
                                    "already_answered": []})

    def stream(_project, _top, _pdk, _container, path):
        path.write_bytes(b"streamed layout")
        R._log_invocation("layout gds write", 0, 1, outputs=[path])
        return True, "streamed"

    def partial_fill_tool(argv, **_kwargs):
        assert Path(argv[1]).name == "metal_fill_emit.py"
        path = Path(argv[argv.index("--gds") + 1])
        path.write_bytes(path.read_bytes() + b" + incomplete fill")
        return SimpleNamespace(returncode=1, stdout="partial geometry written",
                               stderr="tool exited 1")

    monkeypatch.setattr(R, "_magic_def_to_gds", stream)
    monkeypatch.setattr(R, "_gds_grid_snap", lambda *a: (False, "no snap"))
    monkeypatch.setattr(R, "_die_finishing", lambda *a: (False, "no seal"))
    monkeypatch.setattr(R, "_step34_gds_tool_arm", lambda *a: None)
    monkeypatch.setattr(R._pr, "run_best_effort", partial_fill_tool)
    monkeypatch.setattr(R, "_die_density_fill", lambda *a: (False, "no die fill"))
    monkeypatch.setattr(R, "_restore_port_labels_if_missing",
                        lambda *a: (False, "no labels"))
    monkeypatch.setattr(R, "_gds_substance_gate", lambda *a: None)
    try:
        result = R._step_gds_direct(project, "unit", pdk, "fake")
    finally:
        R.set_invocation_provenance_sink(None)

    assert result.status == "FAIL", result.detail
    assert "gds:density_metal_fill" in result.detail
    assert "rc=1" in result.detail
    assert (project / "phase3/stage3/pnr/unit.gds").read_bytes().endswith(
        b"incomplete fill")
    assert not any(row.get("record") == "declared_transform"
                   for row in _rows(project))


def test_reextracted_spef_retains_openrcx_bytes_and_declares_augmentation(tmp_path,
                                                                         monkeypatch):
    project = _project(tmp_path)
    extracted = project / "phase3/stage3/extracted"
    extracted.mkdir(parents=True)
    output = extracted / "unit.spef"
    pdk = SimpleNamespace(tech_lef=str(tmp_path / "tech.lef"),
                          cell_lef=str(tmp_path / "cell.lef"),
                          liberty=str(tmp_path / "cells.lib"), metal_prefix="metal")
    (tmp_path / "tech.lef").write_text("VERSION 5.8 ;")
    monkeypatch.setattr(R, "_to_container_path", lambda path, *a: str(path))
    monkeypatch.setattr(R, "_def_reopen_extra_lefs_c", lambda *a: [])
    monkeypatch.setattr(R, "_extra_lef_read_block", lambda *a: "")
    monkeypatch.setattr(R, "_openrcx_ruleset_declaration",
                        lambda *a: {"status": "ABSENT", "detail": "fixture"})
    monkeypatch.setattr(R, "_write_rcx_declaration_record", lambda *a: None)

    emitted = []

    def fake_openroad(_container, _cmd, *, marker, outputs):
        deck = Path(marker).read_text()
        path = Path(re.findall(r"write_spef\s+([^\s}]+)", deck)[-1])
        data = f"raw parasitics {len(emitted) + 1}".encode()
        emitted.append(data)
        path.write_bytes(data)
        R._log_invocation("openroad extraction", 0, 1, outputs=outputs)
        return 0, "", ""

    def augment(_def, _lef, path, _notes):
        path.write_bytes(path.read_bytes() + b" + coupling")
        return True

    monkeypatch.setattr(R, "_docker_exec", fake_openroad)
    monkeypatch.setattr(R, "_emit_spef_coupling_augment", augment)
    try:
        assert R._emit_spef(project, "unit", pdk, "fake", output, [])
    finally:
        R.set_invocation_provenance_sink(None)
    rows = _rows(project)
    tool = next(r for r in rows if r.get("record") == "invocation")
    source, source_hash = next(iter(tool["outputs"].items()))
    target = "phase3/stage3/extracted/unit.spef"
    assert source != target, (source, target)
    finished = next(r for r in rows if r.get("producing_step") == "spef:extraction_finishing")
    assert (project / source).read_bytes() == b"raw parasitics 1"
    assert output.read_bytes() == b"raw parasitics 1 + coupling"
    assert finished["inputs"] == {source: source_hash}
    assert finished["outputs"] == {target: _sha(output.read_bytes())}
    assert sorted(p.name for p in extracted.glob("*.spef")) == ["unit.spef"]
    assert C.audit(project)[0] == "PASS"
    R.set_invocation_provenance_sink(project)
    try:
        assert R._emit_spef(project, "unit", pdk, "fake", output, [])
    finally:
        R.set_invocation_provenance_sink(None)
    newer = _rows(project)[-1]
    newer_source = next(iter(newer["inputs"]))
    assert newer_source != source
    assert (project / source).read_bytes() == b"raw parasitics 1"
    assert (project / newer_source).read_bytes() == b"raw parasitics 2"
    assert output.read_bytes() == b"raw parasitics 2 + coupling"
    assert C.audit(project)[0] == "PASS"
    output.write_bytes(b"unlogged rewrite")
    assert "PROVENANCE_HASH_MISMATCH" in {f.rule for f in C.audit(project)[1]}


def test_historical_transform_reads_exact_managed_before_version(tmp_path):
    import step_output_collector as versions
    from flow_artifact_paths import gate_parameters

    project, source, _middle, head = _immutable_chain(tmp_path)
    with gate_parameters(project, {'top': 'unit'}):
        attempt = versions.begin_step(project, '37')
        with versions.active_steps(project, [attempt]):
            versions.retain_before(project, '37', [source])
        versions.finish_step(project, attempt, verdict='FAIL')
    epoch = project / attempt['storage_root'] / attempt['folder']
    metadata = epoch / 'before/outputs.json'
    before = json.loads(metadata.read_text())
    source_rel = source.relative_to(project).as_posix()
    row = next(row for row in before['outputs'] if row['rel'] == source_rel)
    snapshot = metadata.parent / row['snapshot']
    saved_metadata, saved_snapshot = metadata.read_bytes(), snapshot.read_bytes()
    rows = _rows(project)
    source.write_bytes(b'new producer version')
    rows.append({'tool': 'layout', 'exit_code': 0,
                 'outputs': {source_rel: _sha(source.read_bytes())}})
    ledger = project / 'provenance.jsonl'
    ledger.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    saved_ledger = ledger.read_bytes()
    report = tmp_path / 'history-check.json'
    rc = C.main([str(project), '--json', str(report)])
    assert rc == 0, 'the exact managed before-version did not retain the historical input'
    payload = json.loads(report.read_text())
    disclosures = [f for f in payload['findings']
                   if f['rule'] == 'PROVENANCE_TRANSFORM_INPUT_RETAINED']
    assert len(disclosures) == 1 and str(snapshot) in disclosures[0]['detail']
    assert disclosures[0]['severity'] == 'DISCLOSED'
    assert ledger.read_bytes() == saved_ledger
    head_bytes = head.read_bytes()
    for damage in ('wrong_rel', 'wrong_hash', 'changed_snapshot', 'missing_snapshot',
                   'missing_before', 'failed_prior', 'missing_prior',
                   'latest_output_changed', 'missing_current_input', 'wrong_owner'):
        metadata.write_bytes(saved_metadata)
        snapshot.write_bytes(saved_snapshot)
        ledger.write_bytes(saved_ledger)
        head.write_bytes(head_bytes)
        source.write_bytes(b'new producer version')
        original_owner = (epoch / 'outputs.json').read_bytes()
        if damage in ('wrong_rel', 'wrong_hash'):
            broken = json.loads(saved_metadata)
            target = next(r for r in broken['outputs'] if r['rel'] == source_rel)
            target['rel' if damage == 'wrong_rel' else 'sha256'] = (
                'unrelated/file.gds' if damage == 'wrong_rel' else '0' * 64)
            metadata.write_text(json.dumps(broken))
        elif damage == 'changed_snapshot':
            snapshot.write_bytes(b'changed retained material')
        elif damage == 'missing_snapshot':
            snapshot.unlink()
        elif damage == 'missing_before':
            metadata.unlink()
        elif damage in ('failed_prior', 'missing_prior'):
            broken = json.loads('[' + ','.join(saved_ledger.decode().splitlines()) + ']')
            if damage == 'failed_prior':
                broken[0]['exit_code'] = 1
            else:
                broken.pop(0)
            ledger.write_text(''.join(json.dumps(r) + '\n' for r in broken))
        elif damage == 'latest_output_changed':
            head.write_bytes(b'unlogged latest output edit')
        elif damage == 'missing_current_input':
            source.unlink()
        else:
            broken = json.loads(original_owner)
            broken['folder'] = 'another/owner/folder'
            (epoch / 'outputs.json').write_text(json.dumps(broken))
        assert C.main([str(project), '--json', str(report)]) == 1, damage
        assert json.loads(report.read_text())['errors_count'] > 0, damage
        print('HISTORICAL_INPUT_REFUSED', damage)
        (epoch / 'outputs.json').write_bytes(original_owner)
    metadata.write_bytes(saved_metadata)
    snapshot.write_bytes(saved_snapshot)
    source.write_bytes(b'new producer version')
    head.write_bytes(head_bytes)
    ledger.write_bytes(saved_ledger)
    assert C.main([str(project), '--json', str(report)]) == 0
    assert ledger.read_bytes() == saved_ledger


def test_default_publication_retains_independent_versions(tmp_path, monkeypatch):
    import librelane_fill_dfm as fill

    project = _project(tmp_path)
    source = project / 'phase3/librelane/reusable/finished.gds'
    source.parent.mkdir(parents=True)
    pnr = project / 'phase3/stage3/pnr/unit.gds'
    canonical = project / 'phase3/stage4/gds/unit.gds'
    canonical.parent.mkdir(parents=True)
    record = {}
    # Only the already-qualified native/material leaf is substituted. Real
    # publication, copying, declaration, collector and checker are exercised.
    monkeypatch.setattr(fill, 'validate_default_stream', lambda _p: record)
    monkeypatch.setattr(fill, 'current_metal_density', lambda *_a: {'verdict': 'PASS'})
    monkeypatch.setattr(fill, '_load', lambda _p: {'gds': {'librelane': {fill.DENSITY_METRIC: 0}}})
    report = tmp_path / 'publication-check.json'
    retained = []
    try:
        for data in (b'first qualified source fixture', b'second qualified source fixture'):
            for path in (source, pnr, canonical):
                path.write_bytes(data)
            digest = _sha(data)[7:]
            record.update(file_top='unit', pnr_gds=str(pnr), canonical=str(canonical),
                          source=str(source), source_sha256=digest,
                          pnr_gds_sha256=digest, canonical_sha256=digest)
            R._step37_declare_streamout_gds_provenance(project, 'unit', default_finishing=True)
            transforms = [r for r in _rows(project) if r.get('record') == 'declared_transform']
            version = project / next(iter(transforms[-1]['inputs']))
            assert version != source, 'native publication still points a transform at its mutable source'
            assert version.read_bytes() == data
            retained.append((version, data))
            assert all(path.read_bytes() == old for path, old in retained)
            assert C.main([str(project), '--json', str(report)]) == 0
        assert retained[0][0] != retained[1][0]
        artefacts = [r for r in _rows(project) if r.get('record') == 'artefact']
        assert len(artefacts) == 2
        assert all(r['reconstructed'] is True and r['duration_ms'] is None and
                   'no tool invocation' in r['marker'] for r in artefacts)
        ledger = (project / 'provenance.jsonl').read_bytes()
        R._step37_declare_streamout_gds_provenance(project, 'unit', default_finishing=True)
        assert (project / 'provenance.jsonl').read_bytes() == ledger
        assert len(list(pnr.parent.glob('streamout/*.gds'))) == 2
        retained[0][0].write_bytes(b'changed immutable source')
        assert C.main([str(project), '--json', str(report)]) == 1
        print('IMMUTABLE_PUBLICATION_REFUSED', 'changed_retained_source')
    finally:
        R.set_invocation_provenance_sink(None)


@pytest.mark.parametrize('population', ['outputs', 'written_files', 'input_files'])
def test_historical_transform_reads_exact_managed_report_version(tmp_path, population):
    import step_output_collector as versions

    project = _project(tmp_path)
    reports = project / 'reports/phase3'
    reports.mkdir(parents=True)
    source = reports / ('lvs.rpt' if population == 'outputs' else 'lvs_power_aware.rpt')
    head = reports / 'published.rpt'
    old, new = b'first measured report\n', b'next measured report\n'
    rel = source.relative_to(project).as_posix()
    if population == 'input_files':
        source.write_bytes(old)
        attempt = versions.begin_step(project, '36', inputs={rel: _sha(old)[7:]})
    else:
        attempt = versions.begin_step(project, '31')
        source.write_bytes(old)
    ledger = project / 'provenance.jsonl'
    ledger.write_text(json.dumps({'tool': 'netgen', 'exit_code': 0,
                                 'outputs': {rel: _sha(old)}}) + '\n')
    head.write_bytes(old)
    assert R._declare_immutable_transform(project, source, head, 'publish', 'netgen',
                                         'publish unchanged measured report')
    epoch = project / attempt['storage_root'] / attempt['folder']
    report = tmp_path / 'report-version-check.json'

    def next_version():
        source.write_bytes(new)
        rows = _rows(project)
        rows.append({'tool': 'netgen', 'exit_code': 0, 'outputs': {rel: _sha(new)}})
        ledger.write_text(''.join(json.dumps(row) + '\n' for row in rows))

    if population == 'input_files':
        next_version()
        rc = C.main([str(project), '--json', str(report)])
        assert rc == 0, (
            'running managed input copy did not retain the historical report')
    versions.finish_step(project, attempt, verdict='FAIL')
    metadata = epoch / 'outputs.json'
    owner = json.loads(metadata.read_text())
    row = next(row for row in owner[population] if row['rel'] == rel)
    snapshot = epoch / row['snapshot']
    assert snapshot.read_bytes() == old
    assert not any(row['rel'] == rel for row in
                   json.loads((epoch / 'before/outputs.json').read_text())['outputs'])
    if population != 'input_files':
        next_version()
    saved_ledger, saved_owner, saved_snapshot = (
        ledger.read_bytes(), metadata.read_bytes(), snapshot.read_bytes())
    rc = C.main([str(project), '--json', str(report)])
    assert rc == 0, (
        'managed report copy did not retain the historical transform input')
    findings = json.loads(report.read_text())['findings']
    assert any(f['rule'] == 'PROVENANCE_TRANSFORM_INPUT_RETAINED' and
               str(snapshot) in f['detail'] and f['severity'] == 'DISCLOSED'
               for f in findings)
    for damage in ('wrong_rel', 'wrong_hash', 'wrong_size', 'wrong_role',
                   'changed_snapshot', 'missing_snapshot', 'wrong_owner',
                   'failed_prior', 'latest_output_changed'):
        metadata.write_bytes(saved_owner)
        snapshot.write_bytes(saved_snapshot)
        ledger.write_bytes(saved_ledger)
        head.write_bytes(old)
        broken = json.loads(saved_owner)
        target = next(row for row in broken[population] if row['rel'] == rel)
        # finish_step may save the same bytes in outputs and written_files.
        # Isolate this negative's role; another valid copy must remain usable.
        for other in ('outputs', 'written_files', 'input_files'):
            if other != population:
                broken[other] = [r for r in broken.get(other, [])
                                 if not (r['rel'] == rel and r['sha256'] == _sha(old)[7:])]
        metadata.write_text(json.dumps(broken))
        if damage in ('wrong_rel', 'wrong_hash', 'wrong_size', 'wrong_role'):
            field, value = {
                'wrong_rel': ('rel', 'reports/phase3/unrelated.rpt'),
                'wrong_hash': ('sha256', '0' * 64),
                'wrong_size': ('size', len(old) + 1),
                'wrong_role': ('snapshot', 'other/' + snapshot.name),
            }[damage]
            target[field] = value
            if damage == 'wrong_role':
                other = epoch / value
                other.parent.mkdir(exist_ok=True)
                other.write_bytes(old)
            metadata.write_text(json.dumps(broken))
        elif damage == 'changed_snapshot':
            snapshot.write_bytes(b'changed retained report')
        elif damage == 'missing_snapshot':
            snapshot.unlink()
        elif damage == 'wrong_owner':
            broken['folder'] = 'another/owner/folder'
            metadata.write_text(json.dumps(broken))
        elif damage == 'failed_prior':
            rows = _rows(project)
            rows[0]['exit_code'] = 1
            ledger.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        else:
            head.write_bytes(b'unlogged newest output')
        assert C.main([str(project), '--json', str(report)]) == 1, damage
        assert json.loads(report.read_text())['errors_count'] > 0, damage
        print('MANAGED_REPORT_VERSION_REFUSED', population, damage)
    metadata.write_bytes(saved_owner)
    snapshot.write_bytes(saved_snapshot)
    head.write_bytes(old)
    ledger.write_bytes(saved_ledger)
    assert C.main([str(project), '--json', str(report)]) == 0
    assert ledger.read_bytes() == saved_ledger
