#!/usr/bin/env python3
"""Tests for foundry_handoff_pack_gen.py (v1.6.36 — Step 35 skeleton)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "foundry_handoff_pack_gen.py")


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def test_emits_all_skeleton_artefacts(tmp_path):
    """Verifies that the generator emits the canonical handoff files.
    #446: NO fabricated scribe .gds — the foundry-supplied need is a
    plainly-named TODO note instead."""
    r = _run(tmp_path)
    assert r.returncode == 0
    handoff = tmp_path / "phase3/stage4/foundry_handoff"
    assert (handoff / "mask_spec.json").is_file()
    assert (handoff / "wat_plan.json").is_file()
    assert (handoff / "corner_test_vectors.json").is_file()
    assert not (handoff / "scribe_line_layout.gds").exists()
    assert (handoff / "scribe_line_layout.PENDING_FOUNDRY.txt").is_file()
    assert (handoff / "README.txt").is_file()


def test_emits_audit_summary(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    audit = tmp_path / "reports/phase3/foundry_handoff_audit.json"
    assert audit.is_file()
    payload = json.loads(audit.read_text())
    assert payload["verdict"] == "SKELETON_EMITTED"
    assert "design_facts" in payload


def test_includes_design_facts_from_synth_log(tmp_path):
    """Number-of-cells from synth.log lands in design_facts."""
    (tmp_path / "phase2/stage2/synth").mkdir(parents=True)
    (tmp_path / "phase2/stage2/synth/synth.log").write_text(
        "Yosys 0.62\nNumber of cells: 12345\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    audit = json.loads(
        (tmp_path / "reports/phase3/foundry_handoff_audit.json").read_text())
    assert audit["design_facts"]["cell_count"] == 12345


def test_detects_process_node_from_pdk_lib(tmp_path):
    """180 in lib filename → process_nm = 180."""
    (tmp_path / "input/pdk/liberty").mkdir(parents=True)
    (tmp_path / "input/pdk/liberty/commercial_pdk_180nm_typ.lib").write_text("library(x);")
    r = _run(tmp_path)
    audit = json.loads(
        (tmp_path / "reports/phase3/foundry_handoff_audit.json").read_text())
    assert audit["design_facts"]["process_nm"] == 180


def test_mask_spec_includes_pending_foundry_markers(tmp_path):
    """#449: foundry-supplied fields use the structured
    PENDING_FOUNDRY_* namespace (the checker lists them as open items)
    — never TODO_*, which the checker rightly ERRORs as design-derivable
    residue."""
    r = _run(tmp_path)
    mask = json.loads(
        (tmp_path / "phase3/stage4/foundry_handoff/mask_spec.json").read_text())
    assert "PENDING_FOUNDRY_mask_layers" in mask
    assert "PENDING_FOUNDRY_reticle_steppers" in mask
    assert not any(k.startswith("TODO_") for k in mask)


def test_vacuous_pass_when_project_missing():
    r = subprocess.run(
        [sys.executable, str(PROG), "/no/such/foundry/project"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# Physical identity is measured from released layout bytes, independently of
# the design's marketing/project label. These are neutral GDS streams only.
import hashlib
import struct
import pytest


def _physical_gds(roots=('physical_root',), leaf=True):
    def record(kind, value=b'', dtype=0):
        return struct.pack('>HBB',len(value)+4,kind,dtype)+value
    def string(value):
        raw=value.encode('ascii');return raw+b'\0'*(len(raw)%2)
    stamp=struct.pack('>12h',*([2026,1,1,0,0,0]*2))
    raw=record(0,struct.pack('>h',600),2)+record(1,stamp,2)+record(2,string('neutral'),6)
    for name in (*roots, 'primitive_cell') if leaf else roots:
        raw+=record(5,stamp,2)+record(6,string(name),6)
        if leaf and name in roots:
            raw+=(record(10)+record(18,string('primitive_cell'),6)
                  +record(16,struct.pack('>2i',0,0),3)+record(17))
        else:
            raw+=(record(8)+record(13,struct.pack('>h',1),2)
                  +record(14,struct.pack('>h',0),2)
                  +record(16,struct.pack('>10i',0,0,10,0,10,10,0,10,0,0),3)
                  +record(17))
        raw+=record(7)
    return raw+record(4)


def _labelled_layout(tmp_path, data):
    project=tmp_path/'release_project';project.mkdir()
    docs=project/'phase1/generated_docs';docs.mkdir(parents=True)
    (docs/'L1_DATASHEET.json').write_text(json.dumps({'ic_name':'product_label'}))
    gd=project/'phase3/stage4/gds';gd.mkdir(parents=True)
    # The canonical publication alias intentionally differs from STRNAME.
    layout=gd/'product_label.gds';layout.write_bytes(data)
    return project,layout


@pytest.mark.parametrize('root',['physical_root','chip_wrapper'])
def test_release_uses_gds_root_and_preserves_design_label(tmp_path,root):
    project,layout=_labelled_layout(tmp_path,_physical_gds((root,)))
    original=layout.read_bytes()
    # This comparison-only artefact must not become the physical identity.
    (layout.parent/'a.prefinish.gds').write_bytes(_physical_gds(('not_the_release',)))
    result=_run(project)
    assert result.returncode == 0,result.stdout+result.stderr
    spec=json.loads((project/'phase3/stage4/foundry_handoff/mask_spec.json').read_text())
    assert spec['design_top'] == root,spec
    assert spec['design_label'] == 'product_label'
    assert spec['physical_top']['root_candidates'] == [root]
    assert spec['physical_top']['source'] == 'phase3/stage4/gds/product_label.gds'
    assert spec['gds_path'] == spec['physical_top']['source']
    assert spec['layout_members']['product_label.gds']['bytes'] == len(original)
    assert layout.read_bytes() == original
    assert (project/'phase3/stage4/foundry_handoff/product_label.gds').read_bytes() == original
    print('PHYSICAL_ROOT',json.dumps({'root':spec['design_top'],'label':spec['design_label'],'source':spec['physical_top']}))


@pytest.mark.parametrize('requested',['product_label','primitive_cell'])
def test_explicit_top_cannot_rename_the_measured_root(tmp_path,requested):
    project,layout=_labelled_layout(tmp_path,_physical_gds())
    original=layout.read_bytes()
    result=subprocess.run([sys.executable,str(PROG),str(project),'--top',requested],capture_output=True,text=True)
    assert result.returncode == 1,(result.returncode,result.stdout,result.stderr)
    assert 'differs from final GDS root' in result.stderr
    assert not (project/'phase3/stage4/foundry_handoff/mask_spec.json').exists()
    assert layout.read_bytes() == original
    accepted=subprocess.run([sys.executable,str(PROG),str(project),'--top','physical_root'],capture_output=True,text=True)
    assert accepted.returncode == 0,accepted.stdout+accepted.stderr
    spec=json.loads((project/'phase3/stage4/foundry_handoff/mask_spec.json').read_text())
    assert spec['design_top'] == 'physical_root'
    print('EXPLICIT_TOP_REFUSAL',requested,result.returncode)


def test_unknown_root_is_disclosed_without_guessing_or_new_gate(tmp_path):
    for kind,data in (('multiple',_physical_gds(('root_a','root_b'),leaf=False)),
                      ('legacy_non_gds',b'\x00\x04\x08\x00legacy metadata fixture'),
                      ('not_streamed',None)):
        case=tmp_path/kind;case.mkdir()
        project,layout=_labelled_layout(case,data or _physical_gds())
        if data is None:layout.unlink()
        result=_run(project)
        assert result.returncode == 0,(kind,result.stdout,result.stderr)
        spec=json.loads((project/'phase3/stage4/foundry_handoff/mask_spec.json').read_text())
        assert spec['design_top'] is None,(kind,spec)
        assert spec['design_label'] == 'product_label'
        assert spec['physical_top']['reason'],(kind,spec)
        print('UNKNOWN_ROOT',kind,json.dumps(spec['physical_top']))


def test_rerun_rebuilds_only_the_owned_package_directory(tmp_path):
    project, layout = _labelled_layout(tmp_path, _physical_gds())
    first = _run(project)
    assert first.returncode == 0, first.stdout + first.stderr
    handoff = project / 'phase3/stage4/foundry_handoff'
    (handoff / 'old_layout.gds').write_bytes(_physical_gds(('old_layout',)))
    old_archive = handoff / 'archive/project/phase3/stage4/gds/old_layout.gds'
    old_archive.parent.mkdir(parents=True, exist_ok=True)
    old_archive.write_bytes(_physical_gds(('old_layout',)))
    (handoff / 'old_metadata.json').write_text('{"old_attempt": true}')
    external = tmp_path / 'external'
    external.mkdir()
    (external / 'preserve.txt').write_text('outside the owned output\n')
    (handoff / 'old_external_link').symlink_to(external, target_is_directory=True)
    retained = project / 'steps/001_previous/retained.txt'
    retained.parent.mkdir(parents=True)
    retained.write_text('retained previous row output\n')
    protected = {p: p.read_bytes() for p in (layout, retained, external / 'preserve.txt')}

    rerun = _run(project)
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
    assert not (handoff / 'old_layout.gds').exists()
    assert not old_archive.exists()
    assert not (handoff / 'old_metadata.json').exists()
    assert not (handoff / 'old_external_link').exists()
    assert not (handoff / 'release_manifest.json').exists()
    assert (handoff / layout.name).read_bytes() == layout.read_bytes()
    assert {hashlib.sha256(p.read_bytes()).hexdigest() for p in handoff.rglob('*.gds')} == {
        hashlib.sha256(layout.read_bytes()).hexdigest()}
    assert all(p.read_bytes() == data for p, data in protected.items())


def test_fresh_timestamp_output_preserves_the_canonical_package(tmp_path):
    project, layout = _labelled_layout(tmp_path, _physical_gds())
    first = _run(project)
    assert first.returncode == 0, first.stdout + first.stderr
    handoff = project / 'phase3/stage4/foundry_handoff'
    marker = handoff / 'prior_attempt.txt'
    marker.write_text('canonical package is outside this timestamp destination\n')
    destination = project / 'release_versions/new_attempt'
    result = subprocess.run([sys.executable, str(PROG), str(project),
                             '--out-dir', str(destination)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text() == 'canonical package is outside this timestamp destination\n'
    assert (destination / layout.name).read_bytes() == layout.read_bytes()
    assert not (destination / marker.name).exists()


def test_handoff_never_adds_a_differently_named_pnr_layout_to_final_gds(tmp_path):
    project, layout = _labelled_layout(tmp_path, _physical_gds())
    old = project / 'phase3/stage3/pnr/previous_name.gds'
    old.parent.mkdir(parents=True)
    old.write_bytes(_physical_gds(('old_physical_root',)))
    original = old.read_bytes()
    result = _run(project)
    assert result.returncode == 0, result.stdout + result.stderr
    handoff = project / 'phase3/stage4/foundry_handoff'
    spec = json.loads((handoff / 'mask_spec.json').read_text())
    assert set(spec['layout_members']) == {layout.name}
    assert spec['layout_members'][layout.name]['source'] == str(layout)
    assert {hashlib.sha256(p.read_bytes()).hexdigest() for p in handoff.rglob('*.gds')} == {
        hashlib.sha256(layout.read_bytes()).hexdigest()}
    assert old.read_bytes() == original
