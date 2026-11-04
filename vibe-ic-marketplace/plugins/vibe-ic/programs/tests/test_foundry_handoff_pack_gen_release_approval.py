import hashlib
import json

import pytest
import foundry_handoff_pack_gen as release


def test_one_owner_input_approves_the_exact_final_gds(tmp_path):
    gds = tmp_path / 'final.gds'
    gds.write_bytes(b'original final GDS')
    approval = {'approved': True, 'approved_by': 'Accountable owner',
                'gds': 'final.gds', 'gds_sha256': hashlib.sha256(gds.read_bytes()).hexdigest()}
    path = tmp_path / release.RELEASE_APPROVAL_REL
    path.parent.mkdir()
    path.write_text(json.dumps(approval))
    assert release.read_release_approval(tmp_path, gds) == approval
    assert release.RELEASE_APPROVAL_REL == 'input/release_approval.json'
    gds.write_bytes(b'new release bytes')
    with pytest.raises(ValueError, match='final GDS bytes'):
        release.read_release_approval(tmp_path, gds)


def test_release_generates_existing_documents_before_building_manifest(tmp_path, monkeypatch):
    from _ic_release_kit import build_project, DESIGN
    project = build_project(tmp_path / 'project', releases=(DESIGN,))
    gds = project / 'phase3/stage4/gds' / (DESIGN + '.gds')
    approval = {'approved': True, 'approved_by': 'Source fixture owner',
                'gds': str(gds.relative_to(project)),
                'gds_sha256': hashlib.sha256(gds.read_bytes()).hexdigest()}
    path = project / release.RELEASE_APPROVAL_REL
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(approval))
    # Native physical acceptance is outside this source wiring test.
    monkeypatch.setattr(release._fhpc, 'main', lambda args: 0)
    result = release.execute(project, {'context_sha256': 'source-fixture'})
    assert result['default_row_status'] == 'PASS', result
    docs = list((project / 'phase3/stage4/documentation/ic').rglob('*.md'))
    html = list((project / 'reports/phase3/docs').glob('*.html'))
    assert docs and len(html) == 2
    package = project / 'phase3/stage4/foundry_handoff'
    manifest = json.loads((package / 'release_manifest.json').read_text())
    members = {entry['source']: entry for entry in manifest['files']}
    for document in [*docs, *html]:
        member = members[str(document)]
        assert 'release_documentation' in member['roles']
        assert (package / member['path']).read_bytes() == document.read_bytes()


def test_document_refusal_stops_release_before_packaging(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace
    project = tmp_path
    monkeypatch.setattr(release, 'read_release_approval', lambda *args: {'approved': True})
    import tapeout_declaration_gen
    monkeypatch.setattr(tapeout_declaration_gen, 'final_gds', lambda project: project / 'final.gds')
    calls = []
    monkeypatch.setattr(release, 'subprocess', SimpleNamespace(run=
        lambda command, **kwargs: calls.append(command) or subprocess.CompletedProcess(command, 1)), raising=False)
    monkeypatch.setattr(release, 'main', lambda args: calls.append('package') or 0)
    monkeypatch.setattr(release._fhpc, 'main', lambda args: 0)
    result = release.execute(project, {'context_sha256': 'source-fixture'})
    assert result['default_row_status'] == 'FAIL' and result['exit_code'] == 1, result
    assert len(calls) == 1 and 'tapeout_docs_gen.py' in calls[0][2]


def test_unapproved_release_does_not_generate_documents(tmp_path, monkeypatch):
    import tapeout_declaration_gen
    monkeypatch.setattr(tapeout_declaration_gen, 'final_gds', lambda project: project / 'final.gds')
    from types import SimpleNamespace
    monkeypatch.setattr(release, 'subprocess', SimpleNamespace(run=
        lambda *args, **kwargs: pytest.fail('approval must run first')), raising=False)
    result = release.execute(tmp_path, {'context_sha256': 'source-fixture'})
    assert result['default_row_status'] == 'NOT_MEASURED'
