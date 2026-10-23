"""Steps 15 / 15.5ic on LibreLane get the die the run itself settled on.

THE DEFECT (cmp3 D1, 3 of 4 chip-path runs). `resolve_step_configs` built the
15-config from declared tapeout answers only. spm and subservient declare
`die_area_um` NOT_DETERMINED, so design.json carried no DIE_AREA, CORE_AREA or
FP_SIZING; LibreLane's Floorplan fell back to `relative` sizing (a 162x180 um
utilisation die for spm) and PadRing's pad_cfg.tcl died on
`can't read "::env(DIE_AREA)": no such variable`, rc 255 -- while the runner's
own `reports/phase3/floorplan_rectangles.json` said `[0, 0, 3162, 3162]`, on
disk 40 s before the config was emitted.

Real `librelane_contract.resolve_step_configs` throughout. The only
substitution is the image's resolver (a `docker run`), whose file writes are
modelled here with LibreLane's own default of `FP_SIZING = relative`.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
contract = importlib.import_module('librelane_contract')
DD = importlib.import_module('_declared_die')
from test_t95_mig_front import design, put, _def  # noqa: E402

CHAIN = ['OpenROAD.Floorplan', 'OpenROAD.PadRing']
PADS = {'PAD_SOUTH': ['u_a'], 'PAD_NORTH': ['u_b'], 'PAD_EAST': [], 'PAD_WEST': []}
#: The spm record exactly as `step_pnr` wrote it on the failing run.
RECORD = {'program': 'phase3_one_shot_runner.step_pnr',
          'die_rect_um': [0, 0, 3162, 3162],
          'die_source': '--die-um 3162x3162 at the origin',
          'floorplan_rect_um': None, 'floorplan_rect_is_the_die': True,
          'core_pad_um': 393}


@pytest.fixture
def resolver(monkeypatch):
    """The image's resolver, modelled: each requested step sees the design's
    DIE_AREA / CORE_AREA, and LibreLane's own `relative` when no FP_SIZING is
    given -- the configuration the failing runs actually resolved."""
    calls = []

    def run(cmd, **_kw):
        boundary = cmd.index('--entrypoint')
        assert cmd[boundary + 1] == 'python3'
        assert cmd[boundary + 3] == '-c'
        formal = cmd[boundary + 5:]
        assert len(formal) == 6, formal
        design_json, requested, root = map(Path, formal[:3])
        d = json.loads(design_json.read_text())
        calls.append(d)
        for s in json.loads(requested.read_text()):
            put(root / f'{s}.json', {'DIE_AREA': d.get('DIE_AREA'),
                                     'CORE_AREA': d.get('CORE_AREA'),
                                     'FP_SIZING': d.get('FP_SIZING', 'relative'),
                                     'meta': {'step': s}})
            put(root / f'{s}.views.json', {'step': s, 'inputs': [], 'outputs': []})
        put(root / 'flow_gates.json', {})
        return contract.subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr(contract, 'image_capability', lambda *a, **k: {})
    monkeypatch.setattr(contract.subprocess, 'run', run)
    return calls


def chip(tmp_path, record=RECORD, **answers):
    p = design(tmp_path, {'deliverable': 'DIE', 'top_cell': 'core',
                          'die_area_um': 'NOT_DETERMINED', **answers}, pads=PADS)
    if record is not None:
        put(p / DD.FLOORPLAN_RECTANGLES_REL, record)
    (tmp_path / 'pdkroot' / 'processA').mkdir(parents=True)
    return p


def resolve(tmp_path, p, steps=CHAIN, overlay=None):
    configs = contract.resolve_step_configs(p, 'img', 'processA', steps,
                                            pdk_root=tmp_path / 'pdkroot',
                                            folder='15-config', overlay=overlay)
    root = p / 'phase3/librelane/15-config'
    return ({s: json.loads(c.read_text()) for s, c in configs.items()},
            json.loads((root / 'design.provenance.json').read_text()))


# ── red on main ──────────────────────────────────────────────────────────────

def test_a_chip_floorplan_without_a_declared_die_takes_the_runners_die(tmp_path, resolver):
    p = chip(tmp_path)
    configs, sources = resolve(tmp_path, p)
    assert configs['OpenROAD.PadRing']['DIE_AREA'] == [0, 0, 3162, 3162]
    fp = configs['OpenROAD.Floorplan']
    assert fp['FP_SIZING'] == 'absolute'
    assert fp['DIE_AREA'] == [0, 0, 3162, 3162]
    # The direct deck's -core_area: core_pad .. die - core_pad.
    assert fp['CORE_AREA'] == [393, 393, 2769, 2769]
    for key in ('DIE_AREA', 'FP_SIZING'):
        assert DD.FLOORPLAN_RECTANGLES_REL + '.die_rect_um' in sources[key], sources[key]
        # The record's own die_source, verbatim -- whatever it says.
        assert RECORD['die_source'] in sources[key], sources[key]
    assert 'core_pad_um' in sources['CORE_AREA'], sources['CORE_AREA']


def test_a_slot_record_takes_its_floorplan_rectangle_as_the_core(tmp_path, resolver):
    slot = dict(RECORD, die_rect_um=[0, 0, 1936, 2531], die_source='shuttle slot s1 DIE_AREA',
                floorplan_rect_um=[442, 442, 1494, 2089], floorplan_rect_is_the_die=False)
    p = chip(tmp_path, slot)
    configs, sources = resolve(tmp_path, p)
    assert configs['OpenROAD.Floorplan']['DIE_AREA'] == [0, 0, 1936, 2531]
    assert configs['OpenROAD.Floorplan']['CORE_AREA'] == [442, 442, 1494, 2089]
    assert sources['CORE_AREA'].startswith(DD.FLOORPLAN_RECTANGLES_REL + '.floorplan_rect_um')


def test_no_declared_and_no_derived_die_is_refused_before_the_tool(tmp_path, resolver):
    p = chip(tmp_path, record=None)
    with pytest.raises(contract.Refusal, match='LL_PADRING_DIE_UNDERIVABLE') as exc:
        resolve(tmp_path, p)
    assert DD.FLOORPLAN_RECTANGLES_REL in str(exc.value)
    assert resolver == []


def test_a_declared_die_the_runner_disagrees_with_is_refused(tmp_path, resolver):
    p = chip(tmp_path, die_area_um=[0, 0, 2000, 2000])
    with pytest.raises(contract.Refusal, match='LL_DERIVED_DIE_CONFLICT'):
        resolve(tmp_path, p)
    assert resolver == []


def test_a_source_bound_provisional_slot_may_replace_its_declared_target(
        tmp_path):
    old = [0, 0, 2000, 2100]
    new = [0, 0, 2600, 2300]
    p = chip(tmp_path, die_area_um=old)
    source = p / 'input/submission_template_source/larger.json'
    put(source, '{"SLOT":"larger","DIE_AREA":"0 0 2600 2300"}\n')
    source_hash = contract.digest(source)
    slot = {"slot": "larger", "source_relpath": "larger.json",
            "source_sha256": source_hash,
            "die_area": {"rect": [str(v) for v in new]}}
    put(p / 'input/submission_template/slots/larger.yaml', json.dumps(slot))
    record = dict(RECORD, die_rect_um=new,
                  die_intent={
                      "intent": "DERIVED_PROVISIONAL_SLOT",
                      "declared_slot": "small",
                      "declared_die_um": "2000x2100",
                      "resolved_slot": "larger",
                      "resolved_die_um": "2600x2300",
                      "source_relpath": "larger.json",
                      "source_sha256": source_hash})
    put(p / DD.FLOORPLAN_RECTANGLES_REL, record)
    config = {'DIE_AREA': old}
    sources = {'DIE_AREA': 'input declaration'}
    contract._apply_runner_floorplan(p, config, sources, CHAIN)
    assert config['DIE_AREA'] == new
    assert 'source-bound provisional slot small -> larger' in sources['DIE_AREA']


def test_a_provisional_slot_with_stale_source_keeps_conflict_fail_closed(
        tmp_path):
    old = [0, 0, 2000, 2100]
    new = [0, 0, 2600, 2300]
    p = chip(tmp_path, die_area_um=old)
    source = p / 'input/submission_template_source/larger.json'
    put(source, 'changed\n')
    slot = {"slot": "larger", "source_relpath": "larger.json",
            "source_sha256": "0" * 64, "die_area": {"rect": new}}
    put(p / 'input/submission_template/slots/larger.yaml', json.dumps(slot))
    record = dict(RECORD, die_rect_um=new,
                  die_intent={"intent": "DERIVED_PROVISIONAL_SLOT",
                              "declared_slot": "small",
                              "declared_die_um": "2000x2100",
                              "resolved_slot": "larger",
                              "resolved_die_um": "2600x2300",
                              "source_relpath": "larger.json",
                              "source_sha256": "0" * 64})
    put(p / DD.FLOORPLAN_RECTANGLES_REL, record)
    with pytest.raises(contract.Refusal, match='LL_DERIVED_DIE_CONFLICT'):
        contract._apply_runner_floorplan(
            p, {'DIE_AREA': old}, {'DIE_AREA': 'input declaration'}, CHAIN)


def test_a_declared_relative_sizing_cannot_carry_a_pad_ring(tmp_path, resolver):
    p = chip(tmp_path, fp_sizing='relative')
    with pytest.raises(contract.Refusal, match='LL_PADRING_DIE_RELATIVE_DECLARED'):
        resolve(tmp_path, p)
    assert resolver == []


def test_a_slot_template_that_disagrees_with_the_runners_die_is_refused(tmp_path, resolver):
    p = chip(tmp_path)
    put(p / 'input/submission_template/slots/slot_1x1.yaml',
        'FP_DEF_TEMPLATE: ../template/slot.def\n')
    put(p / 'input/submission_template/template/slot.def', _def([0, 0, 2000000, 2000000]))
    with pytest.raises(contract.Refusal, match='LL_DEF_TEMPLATE_DIE_MISMATCH'):
        resolve(tmp_path, p)
    # The same template stating the record's die is accepted.
    put(p / 'input/submission_template/template/slot.def', _def([0, 0, 3162000, 3162000]))
    configs, _ = resolve(tmp_path, p)
    assert configs['OpenROAD.PadRing']['DIE_AREA'] == [0, 0, 3162, 3162]


def test_a_derived_core_outside_the_die_is_refused(tmp_path, resolver):
    p = chip(tmp_path, dict(RECORD, floorplan_rect_um=[100, 100, 3200, 3000],
                            floorplan_rect_is_the_die=False))
    with pytest.raises(contract.Refusal, match='LL_DERIVED_CORE_OUTSIDE_DIE'):
        resolve(tmp_path, p)


# ── controls: green on main and on the fix ───────────────────────────────────

def test_a_declared_die_equal_to_the_record_keeps_its_declared_source(tmp_path, resolver):
    p = chip(tmp_path, die_area_um=[0, 0, 3162, 3162], core_area_um=[400, 400, 2700, 2700])
    configs, sources = resolve(tmp_path, p)
    assert configs['OpenROAD.PadRing']['DIE_AREA'] == [0, 0, 3162, 3162]
    assert configs['OpenROAD.Floorplan']['CORE_AREA'] == [400, 400, 2700, 2700]
    assert sources['DIE_AREA'].endswith('answers.die_area_um')
    assert sources['CORE_AREA'].endswith('answers.core_area_um')
    assert configs['OpenROAD.Floorplan']['FP_SIZING'] == 'absolute'


@pytest.mark.parametrize('overlay', [None, {'PL_TARGET_DENSITY': (0.5, 'test overlay')}])
def test_a_chain_without_floorplan_or_padring_is_not_given_the_die(tmp_path, resolver, overlay):
    # With an overlay the config is rewritten, so the step gate itself decides.
    p = chip(tmp_path)
    configs, sources = resolve(tmp_path, p, ['OpenROAD.GlobalPlacement'], overlay)
    assert configs['OpenROAD.GlobalPlacement']['DIE_AREA'] is None
    assert 'DIE_AREA' not in sources and 'FP_SIZING' not in sources


def test_an_explicit_overlay_still_outranks_the_derived_die(tmp_path, resolver):
    p = chip(tmp_path)
    contract.resolve_step_configs(p, 'img', 'processA', CHAIN,
                                  pdk_root=tmp_path / 'pdkroot', folder='15-config',
                                  overlay={'PDN_CFG': ('/x/pdn.tcl', 'test overlay')})
    d = json.loads((p / 'phase3/librelane/15-config/design.json').read_text())
    assert d['PDN_CFG'] == '/x/pdn.tcl' and d['DIE_AREA'] == [0, 0, 3162, 3162]
