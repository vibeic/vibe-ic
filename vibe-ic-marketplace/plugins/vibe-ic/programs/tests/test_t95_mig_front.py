"""T95 mig-front: D1 / 0.5ic config emitter, step-1 catalog pins, step-6 word.

Real consumers throughout. The only substitutions are an EDA tool's file
writes (Yosys's ``write_json``, replayed from a recorded real run) and a
local git repository standing in for a catalog IP's upstream.
"""
import importlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
contract = importlib.import_module('librelane_contract')
query = importlib.import_module('ip_catalog_query')
frontend = importlib.import_module('p0_tool_frontend_check')
CAL = PROGRAMS / 'calibration'
DECL = 'input/submission_template/tapeout_declaration.json'


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj) if not isinstance(obj, str) else obj)
    return path


def design(tmp_path, answers, provenance=None, pads=None):
    p = tmp_path / 'design'
    put(p / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json', {'clock_domains': [
        {'role': 'primary', 'period_ns': 20, 'source_pin': 'clk'}]})
    put(p / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'core'})
    put(p / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': {'pdk_target': 'processA'}})
    doc = {'schema': 'vibe-ic/tapeout_declaration/1', 'answers': answers}
    if provenance:
        doc['answer_provenance'] = provenance
    put(p / DECL, doc)
    if pads is not None:
        put(p / 'phase3/stage3/pnr/pad_assignment.json', pads)
    return p


def emit(p):
    out = p / 'phase3/librelane/config.json'
    result = contract.emit_config(p, 'processA', out)
    return result, json.loads(out.with_suffix('.provenance.json').read_text())


OWNER = {'answered_by': 'owner', 'citation': 'ruling R-test'}


# ── 0.5ic: tapeout_declaration.json -> LibreLane config ──────────────────────

def test_hardmacro_takes_its_own_rectangle_not_a_die_it_does_not_owe(tmp_path):
    p = design(tmp_path, {'deliverable': 'HARDMACRO', 'top_cell': 'core',
                          'die_area_um': [0, 0, 999, 999],
                          'macro_area_um': [0, 0, 120, 80]},
               {'deliverable': OWNER})
    result, sources = emit(p)
    assert result['DIE_AREA'] == [0, 0, 120, 80]
    assert 'macro_area_um' in sources['DIE_AREA']
    assert result['FP_SIZING'] == 'absolute'


def test_an_unattested_owner_answer_is_not_a_declaration(tmp_path):
    # deliverable is owner-only; without the owner it is NOT_DETERMINED, so
    # the HARDMACRO branch must not be taken on an agent's reading.
    p = design(tmp_path, {'deliverable': 'HARDMACRO', 'die_area_um': [0, 0, 50, 50],
                          'macro_area_um': [0, 0, 10, 10]},
               {'deliverable': {'answered_by': 'agent'}})
    result, _ = emit(p)
    assert result['DIE_AREA'] == [0, 0, 50, 50]


def test_relative_sizing_is_not_emitted_as_an_absolute_die(tmp_path):
    p = design(tmp_path, {'die_area_um': [0, 0, 100, 100],
                          'core_area_um': [10, 10, 90, 90], 'fp_sizing': 'relative'})
    result, sources = emit(p)
    assert result['FP_SIZING'] == 'relative'
    assert 'DIE_AREA' not in result and 'CORE_AREA' not in result
    assert sources['FP_SIZING'].endswith('answers.fp_sizing')


@pytest.mark.parametrize('answers,code', [
    ({'die_area_um': [0, 0, 100, 100], 'core_area_um': [10, 10, 120, 90]},
     'LL_DECLARATION_CORE_OUTSIDE_DIE'),
    ({'die_area_um': [5, 0, 100, 100], 'die_origin_um': [0, 0]},
     'LL_DECLARATION_ORIGIN_MISMATCH'),
    ({'die_area_um': [0, 0, 100]}, 'LL_DECLARATION_RECT_INVALID'),
    ({'fp_sizing': 'guess'}, 'LL_DECLARATION_FP_SIZING_INVALID'),
])
def test_inconsistent_declared_geometry_is_refused(tmp_path, answers, code):
    p = design(tmp_path, answers)
    with pytest.raises(contract.Refusal, match=code):
        emit(p)


PAD_ANSWERS = {'pad_order_by_side': {'south': ['u_a'], 'east': [], 'north': ['u_b'],
                                     'west': []},
               'pad_site_name': 'siteA', 'pad_corner_site_name': 'cornerSiteA',
               'pad_edge_spacing_um': 12.5, 'pad_corner_master': 'cornerA',
               'pad_fillers': ['fillA'],
               'pad_rotations': {'horizontal': 'R0', 'vertical': 'R90', 'corner': 'R0'}}


def test_declared_pads_are_emitted_without_the_producer_artefact(tmp_path):
    p = design(tmp_path, dict(PAD_ANSWERS))
    result, sources = emit(p)
    assert result['PAD_SOUTH'] == ['u_a'] and result['PAD_NORTH'] == ['u_b']
    assert result['PAD_CORNER'] == ['cornerA']
    assert result['PAD_EDGE_SPACING'] == 12.5
    assert result['PAD_ROTATION_VERTICAL'] == 'R90'
    assert sources['PAD_SOUTH'].endswith('answers.pad_order_by_side.south')


def test_declaration_and_pad_producer_must_agree(tmp_path):
    agreeing = {'PAD_SOUTH': ['u_a'], 'PAD_NORTH': ['u_b'], 'PAD_SITE_NAME': 'siteA',
                'PAD_EDGE_SPACING': '12.5', 'PAD_CORNER': 'cornerA'}
    p = design(tmp_path, dict(PAD_ANSWERS), pads=agreeing)
    result, sources = emit(p)
    assert sources['PAD_SOUTH'].endswith('answers.pad_order_by_side.south')
    assert result['PAD_EDGE_SPACING'] == 12.5
    put(p / 'phase3/stage3/pnr/pad_assignment.json', dict(agreeing, PAD_SOUTH=['u_b', 'u_a']))
    with pytest.raises(contract.Refusal, match='LL_PAD_DECLARATION_CONFLICT'):
        emit(p)


def _def(die):
    return (f'VERSION 5.8 ;\nDESIGN chip_top ;\nUNITS DISTANCE MICRONS 1000 ;\n'
            f'DIEAREA ( {die[0]} {die[1]} ) ( {die[2]} {die[3]} ) ;\nEND DESIGN\n')


def test_operator_def_template_is_emitted_and_must_match_the_declared_die(tmp_path):
    p = design(tmp_path, {'die_area_um': [0, 0, 100, 100]})
    put(p / 'input/submission_template/slots/slot_1x1.yaml',
        'DIE_AREA: [0, 0, 100, 100]\nFP_DEF_TEMPLATE: ../template/slot.def\n')
    put(p / 'input/submission_template/template/slot.def', _def([0, 0, 100000, 100000]))
    result, sources = emit(p)
    assert result['FP_DEF_TEMPLATE'] == 'dir::input/submission_template/template/slot.def'
    assert 'slots/slot_1x1.yaml.FP_DEF_TEMPLATE (sha256:' in sources['FP_DEF_TEMPLATE']
    put(p / 'input/submission_template/template/slot.def', _def([0, 0, 90000, 100000]))
    with pytest.raises(contract.Refusal, match='LL_DEF_TEMPLATE_DIE_MISMATCH'):
        emit(p)


# ── D1: L-docs by exact name ──────────────────────────────────────────────────

def test_a_missing_ldoc_is_refused_by_its_exact_name(tmp_path):
    p = design(tmp_path, {})
    (p / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json').unlink()
    put(p / 'phase1/generated_docs/L9_INTEGRATION.json', {'top_module': 'core'})
    with pytest.raises(contract.Refusal, match='LL_LDOC_MISSING: L9_INTEGRATION_SPEC.json'):
        emit(p)


# ── step 1: catalog clone pinned by sha ──────────────────────────────────────

def _upstream(tmp_path):
    repo = tmp_path / 'upstream'
    repo.mkdir()
    env = ['-c', 'user.email=t@t', '-c', 'user.name=t']
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'rtl').mkdir()
    (repo / 'LICENSE').write_text('ISC License\n')
    (repo / 'rtl/core.v').write_text('module core; /* pinned */ endmodule\n')
    subprocess.run(['git', *env, '-C', str(repo), 'add', '-A'], check=True)
    subprocess.run(['git', *env, '-C', str(repo), 'commit', '-qm', 'one'], check=True)
    subprocess.run(['git', '-C', str(repo), 'tag', '1.4.0'], check=True)
    (repo / 'rtl/core.v').write_text('module core; /* tip */ endmodule\n')
    subprocess.run(['git', *env, '-C', str(repo), 'commit', '-qam', 'two'], check=True)
    return repo


def _match(repo, name):
    return query.CatalogMatch(ip_name=name, category='cpu', version='1.4.0',
                              license='ISC', canonical_url=f'file://{repo}',
                              canonical_commit='1.4.0', matched_pattern='t',
                              confidence=1.0, manifest_path='', rtl_files=['rtl/core.v'])


def test_clone_fallback_checks_out_the_pinned_commit(tmp_path, monkeypatch):
    repo = _upstream(tmp_path)
    name = 'pin' + uuid.uuid4().hex[:10]
    project = tmp_path / 'proj'
    assert '/* pinned */' in (project / 'phase2/stage1/rtl/core.v').read_text()
    tag = subprocess.run(['git', '-C', str(repo), 'rev-parse', '1.4.0^{commit}'],
                         capture_output=True, text=True, check=True).stdout.strip()


# ── step 1: synth-safe parameters, judged on Yosys's elaboration ─────────────

def _catalog_project(tmp_path, recorded):
    p = tmp_path / 'proj'
    rtl = p / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    shutil.copy(CAL / 'cal_catalog_ip.v', rtl / 'ip.v')
    shutil.copy(CAL / 'cal_catalog_glue_unsafe.v', rtl / 'glue.v')
    put(p / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'top'})
    # serv's real manifest declares synth_safe_params sim=0.
    put(p / 'plugin_output/declaration.json', {'ip_catalog_used': [
        {'ip_name': 'serv', 'status': 'PASS', 'files_copied': [{'dest': str(rtl / 'ip.v')}]}]})
    calls = []

    def yosys_writes(project, image, script, out_dir):
        calls.append(script)
        out = Path(script.rsplit('write_json ', 1)[1])
        assert out.parent == out_dir
        if recorded is not None:
            shutil.copy(CAL / recorded, out)
        return subprocess.CompletedProcess(['yosys'], 0 if recorded else 1, '', '')
    return p, calls, yosys_writes


@pytest.mark.parametrize('recorded,rc,verdict', [
    ('catalog_synth_safe_unsafe_positive.json', 1, 'FAIL'),
    ('catalog_synth_safe_pinned_negative.json', 0, 'PASS'),
    (None, 1, 'NOT_MEASURED')])
def test_the_gate_judges_the_elaborated_parameter(tmp_path, monkeypatch, recorded, rc, verdict):
    p, calls, fake = _catalog_project(tmp_path, recorded)
    gate = importlib.import_module('catalog_synth_safe_params_check')
    monkeypatch.setattr(gate, '_yosys', fake)
    assert gate.main([str(p)]) == rc
    report = json.loads((p / gate.REPORT_REL).read_text())
    assert report['verdict'] == verdict
    script = calls[0]
    assert 'hierarchy -check -top top' in script and 'read_verilog -sv' in script
    if verdict == 'FAIL':
        # both the wrapper and the core it passes sim=1 to are named
        assert {r['hdlname'] for r in report['instances'] if not r['safe']} == {'ipcore', 'ipwrap'}


def test_the_gate_is_not_applicable_without_a_pinned_catalog_ip(tmp_path, monkeypatch):
    p, calls, fake = _catalog_project(tmp_path, 'catalog_synth_safe_unsafe_positive.json')
    put(p / 'plugin_output/declaration.json', {'ip_catalog_used': []})
    gate = importlib.import_module('catalog_synth_safe_params_check')
    monkeypatch.setattr(gate, '_yosys', fake)
    assert gate.main([str(p)]) == 0
    assert json.loads((p / gate.REPORT_REL).read_text())['verdict'] == 'NOT_APPLICABLE'
    assert calls == []


def test_synth_parameters_pin_a_catalogued_top_only(tmp_path):
    p, _, _ = _catalog_project(tmp_path, None)
    for name in ('L8_TIMING_WAVEFORM.json', 'L19_CONSTRAINTS_PDK.json'):
        put(p / 'phase1/generated_docs' / name,
            {'clock_domains': [{'role': 'primary', 'period_ns': 10, 'source_pin': 'clk'}]}
            if name.startswith('L8') else {'fields': {'pdk_target': 'processA'}})
    put(p / DECL, {'answers': {}})
    rtl = sorted((p / 'phase2/stage1/rtl').glob('*.v'))
    top_ip = contract.emit_synthesis_config(p, 'processA', p / 's.json', rtl, [], False,
                                            top='ipwrap')
    assert top_ip['SYNTH_PARAMETERS'] == ['sim=0']
    assert 'synth_safe_params' in json.loads(p.joinpath('s.provenance.json').read_text())[
        'SYNTH_PARAMETERS']
    glue_top = contract.emit_synthesis_config(p, 'processA', p / 's.json', rtl, [], False,
                                              top='top')
    assert 'SYNTH_PARAMETERS' not in glue_top


# ── step 6: a board-absent audit is never a PASS ─────────────────────────────
