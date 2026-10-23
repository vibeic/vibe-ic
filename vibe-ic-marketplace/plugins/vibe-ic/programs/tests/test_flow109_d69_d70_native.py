"""Opt-in native Default control. Inputs are copied real SPM/GF180 artefacts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import librelane_signoff as signoff
import flow109_final_extract as d69
import flow109_final_electrical as d70
from spef_extraction_check import scan_spef


def test_native_failure_precedence_is_not_relabelled_unmeasured():
    assert d69._native_refusal_status('LL_STEP_FAILED') == 'FAIL'
    assert d70._native_refusal_status('LL_STEP_FAILED') == 'FAIL'
    assert d69._native_refusal_status('LL_LOCAL_IMAGE_UNATTESTED') == 'NOT_MEASURED'
    assert d70._native_refusal_status('LL_DIRECT_SPEF_MISSING') == 'NOT_MEASURED'


def test_final_filled_odb_runs_rcx_then_all_declared_stapostpnr_corners():
    control_path = Path('/tmp/vibeic-d69d70-native-control.json')
    if not control_path.is_file():
        pytest.skip('place the bounded native-control manifest in /tmp')
    control = json.loads(control_path.read_text())
    project = Path(control['project']).resolve()
    pnr = project / 'phase3/stage3/pnr'
    image = control['image']
    pdk_root = Path(control['pdk_root']).resolve()
    result = signoff.run(project, image, pdk_root, 'gf180mcuD',
        routed_def=pnr / 'filled.def', routed_odb=pnr / 'filled.odb',
        netlist=pnr / 'spm_pnr.v', sdc=pnr / 'constraint.sdc',
        extract=True, time=True, lane='flow109-d69-d70-native')
    binding = signoff.bind_rcx_spefs(result['rcx'], result['rcx'] / 'state_in.json')
    scans = {corner: scan_spef(path) for corner, path in result['spef'].items()}
    assert binding['route_sha256']['odb']
    assert all(f['has_header'] and f['has_design'] and f['d_nets'] > 0 for f in scans.values())
    corners = signoff.corner_timing(result['sta'])
    declared = json.loads(result['configs']['OpenROAD.STAPostPNR'].read_text())['STA_CORNERS']
    state = json.loads((result['sta'] / 'state_out.json').read_text())
    assert set(corners) == set(declared)
    assert set(state.get('sdf') or {}) == set(declared)
    summary = {'scope': 'developer native control, not product qualification',
               'rcx': str(result['rcx']), 'sta': str(result['sta']),
               'spef_scan': scans, 'declared_corners': declared,
               'timing_judgment': signoff.judge_timing(corners),
               'odb_sha256': binding['route_sha256']['odb']}
    (project / 'd69-d70-native-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
