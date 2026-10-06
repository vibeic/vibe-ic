"""F25: every step reads the image and the PDK root through the contract's resolvers.

`librelane_contract.resolve_image` and `pdk_root_resolution` answer declared >
resolved at run time > refused by name (T89, F14). Before F25 these steps read
`image` / `pdk_root_host` STRAIGHT from `phase3/librelane_switch.json`, so a
project that declared neither refused (or ran on no root) even though the
resolvers would answer:

- step 2 lint (`step_rtl_lint_tool`): the root;
- step 3 CDC netlist (`_cdc_netlist.build`): the image;
- step 8 synthesis (`_step_synth_librelane`): the root;
- steps 7/8/10 pre-layout signoff (`_prelayout_librelane`): image and root;
- step 13 EQY (`_lec_eqy_arm`): image and root;
and these asked the resolver without the design's PDK, so an undeclared
project refused `LL_PDK_UNDECLARED` and the message dropped the cause:
- steps 19/20 (`librelane_cts_hold.execute`, T98), 24/26/26.5ic
  (`_librelane_step_ctx`), 29 and 30 (`_step29/30_tool_arm`).

For each step: an undeclared project resolves; a declared value wins (and the
host is never asked); a refusal names the resolver's cause.

F25 also prunes the PDK-root cache: copies whose image is no longer on this
host go, keeping the current copy and one previous, never one in use.

Every test STATES its environment (the rfi/rfl pattern): the image identity
(`_stated_eda_image`), the cache directory, and docker, a fake that performs
only docker's file writes. The step's tool is intercepted at the first call
past the resolution, which records what it was handed and stops the step.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import librelane_contract as contract  # noqa: E402
from _stated_eda_image import stated_image, state_the_image  # noqa: E402

IMAGE_ID = 'sha256:' + '5a' * 32
GUEST_ROOT = '/opt/stated/pdks'
PDK = 'stated_pdk'
CACHE_ENV = getattr(contract, 'PDK_ROOT_CACHE_ENV', 'VIBEIC_PDK_ROOT_CACHE')
MARKER = getattr(contract, 'PDK_ROOT_MARKER', '.vibeic_pdk_root.json')
STOP = 'F25_STOP'


class FakeDocker:
    """docker over a stated host: `image inspect/ls`, `create`, `cp`, `rm`,
    `ps` and container `inspect`. Anything else is an unexpected call."""

    def __init__(self, images, trees):
        self.images, self.trees, self.calls = images, set(trees), []
        self.held = {image_id for image_id, _ in images.values()}
        self.mounts: list[str] = []          # sources bound by running containers
        self.broken: set[str] = set()        # verbs that fail

    def __call__(self, argv, **_kw):
        argv = list(argv)
        self.calls.append(argv)
        verb = ' '.join(argv[1:3]) if argv[1] == 'image' else argv[1]
        if verb in self.broken:
            return subprocess.CompletedProcess(argv, 1, '', 'stated failure')
        if verb == 'image inspect':
            if argv[-1] not in self.images:
                return subprocess.CompletedProcess(argv, 1, '', f'No such image: {argv[-1]}')
            image_id, env = self.images[argv[-1]]
            return subprocess.CompletedProcess(argv, 0, f'{json.dumps(image_id)} {json.dumps(env)}\n', '')
        if verb == 'image ls':
            return subprocess.CompletedProcess(argv, 0, ''.join(f'{i}\n' for i in self.held), '')
        if verb == 'ps':
            return subprocess.CompletedProcess(argv, 0, 'c0\n' if self.mounts else '', '')
        if verb == 'inspect':
            return subprocess.CompletedProcess(argv, 0, ''.join(f'{m}\n' for m in self.mounts), '')
        if verb == 'create':
            return subprocess.CompletedProcess(argv, 0, 'cid0\n', '')
        if verb == 'cp':
            src, dest = argv[-2].split(':', 1)[1], Path(argv[-1])
            if src not in self.trees:
                return subprocess.CompletedProcess(argv, 1, '', f'Could not find {src}')
            (dest / 'libs.tech').mkdir(parents=True)
            # Synthesis now verifies that the selected staged library exists
            # before calling its config resolver. Model that copied input too.
            library = dest / 'lib/stated_sc__tt.lib'
            library.parent.mkdir()
            library.write_text('library(stated_sc) {}\n')
            return subprocess.CompletedProcess(argv, 0, '', '')
        if verb == 'rm':
            return subprocess.CompletedProcess(argv, 0, '', '')
        raise AssertionError(f'unexpected docker call {argv}')


@pytest.fixture
def env(tmp_path, monkeypatch):
    """The stated world: an image carrying `stated_pdk` under GUEST_ROOT."""
    monkeypatch.delenv('VIBEIC_LIBRELANE_PDK_ROOT', raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_IMAGE', raising=False)
    monkeypatch.setenv(CACHE_ENV, str(tmp_path / 'cache'))
    image = state_the_image(monkeypatch)
    fake = FakeDocker({image: (IMAGE_ID, ['PATH=/bin', f'PDK_ROOT={GUEST_ROOT}'])},
                      [f'{GUEST_ROOT}/{PDK}'])
    # This fixture models a Docker host, even when pytest itself runs inside
    # the EDA image. Keep real LOCAL attestation outside this fake transport.
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: False)
    monkeypatch.setattr(contract.subprocess, 'run', fake)
    project = tmp_path / 'proj'
    (project / 'phase3').mkdir(parents=True)
    _switch(project)
    yield SimpleNamespace(project=project, image=image, fake=fake, tmp=tmp_path,
                          resolved_root=tmp_path / 'cache' / IMAGE_ID.split(':')[1])
    runner = sys.modules.get('phase3_one_shot_runner')
    if runner is not None:
        runner.set_invocation_provenance_sink(None)


def _switch(project, **values):
    """The switch selects every step under test; image/root only if given.

    No `pdk` either: the phase-3 steps must hand the resolver the DESIGN's PDK.
    Steps 2 and 13 read their PDK from the switch by contract (`_switch_pdk`)."""
    doc = {'steps': {s: 'librelane' for s in ('2', '3', '7', '8', '10', '13', '19', '20',
                                             '24', '26', '29', '30')}, **values}
    (project / 'phase3/librelane_switch.json').write_text(json.dumps(doc))


def _switch_pdk(project):
    path = project / 'phase3/librelane_switch.json'
    path.write_text(json.dumps({**json.loads(path.read_text()), 'pdk': PDK}))


def _declare(env):
    root = env.tmp / 'declared_root'
    (root / PDK).mkdir(parents=True)
    _switch(env.project, image='declared/eda@sha256:' + '1d' * 32, pdk_root_host=str(root))
    return 'declared/eda@sha256:' + '1d' * 32, root


def _break_the_image(env):
    env.fake.images.clear()        # the stated image is not on this host


def _stop(**seen):
    raise contract.Refusal(STOP, json.dumps({k: str(v) for k, v in seen.items()}))


def _bound_root(mounts):
    """The host directory a step binds to /pdk."""
    roots = [Path(host) for host, guest in (mounts or []) if guest == '/pdk']
    return roots[0] if roots else None


def _rtl(project):
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / 'top.v').write_text('module top(input wire a, output wire y);\n'
                               '  assign y = a;\nendmodule\n')
    return rtl / 'top.v'


def _pdk():
    return SimpleNamespace(name=PDK, liberty=f'{GUEST_ROOT}/{PDK}/lib/stated_sc__tt.lib',
                           macro_libs=[], macro_lefs=[], macro_v=[])


# ---------------------------------------------------------- the step drivers ---
# Each returns (image, host root) the step handed its tool, or raises / returns
# the step's own refusal text.

def step2(env, monkeypatch):
    runner = importlib.import_module('design_one_shot_runner')
    _switch_pdk(env.project)
    (env.project / 'input').mkdir(exist_ok=True)
    (env.project / 'input/project.json').write_text(json.dumps({'pdk': PDK}))
    _rtl(env.project)
    (env.project / 'phase1/generated_docs').mkdir(parents=True)
    (env.project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json').write_text(
        json.dumps({'top_module': 'top'}))
    seen = {}

    def resolve_step_config(project, image, *_a, mounts=None, **_k):
        seen.update(image=image, root=_bound_root(mounts))
        _stop()
    monkeypatch.setattr(contract, 'resolve_step_config', resolve_step_config)
    row = runner.step_rtl_lint_tool(env.project)
    return seen, row.detail


def step3(env, monkeypatch):
    import _cdc_netlist as cn
    monkeypatch.setattr(cn.shutil, 'which', lambda _n: None)     # no host yosys
    seen = {}

    def run(argv, **_k):
        seen.update(image=argv[argv.index('--entrypoint') + 2], root=None)
        _stop()
    monkeypatch.setattr(cn.subprocess, 'run', run)
    try:
        cn.build(env.project, [_rtl(env.project)], 'top')
    except (cn.Refusal, contract.Refusal) as exc:
        return seen, str(exc)
    return seen, ''


def step8(env, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')
    _rtl(env.project)

    def emit(project, pdk, output, *_a, **_k):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.with_suffix('.provenance.json').write_text('{}')
        return {}
    monkeypatch.setattr(contract, 'emit_synthesis_config', emit)
    seen = {}

    def resolve_step_config(project, image, *_a, mounts=None, **_k):
        seen.update(image=image, root=_bound_root(mounts))
        _stop()
    monkeypatch.setattr(contract, 'resolve_step_config', resolve_step_config)
    row = runner._step_synth_librelane(env.project, 'top', _pdk(), 'c')
    return seen, row.detail


def prelayout(env, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')
    import librelane_prelayout as llp
    seen = {}

    def run_prelayout(project, image, pdk, *_a, mounts=None, **_k):
        seen.update(image=image, root=_bound_root(mounts))
        _stop()
    monkeypatch.setattr(llp, 'run_prelayout', run_prelayout)
    sdc = env.project / 'x.sdc'
    sdc.write_text('create_clock -period 10 [get_ports clk]\n')
    try:
        runner._prelayout_librelane(env.project, 'top', _pdk(), sdc, True,
                                    {'7': 'librelane', '8': 'librelane', '10': 'librelane'}, [])
    except contract.Refusal as exc:
        return seen, str(exc)
    return seen, ''


def step13(env, monkeypatch):
    runner = importlib.import_module('design_one_shot_runner')
    import librelane_eqy as eqy
    _switch_pdk(env.project)
    _rtl(env.project)
    seen = {}

    def run_eqy(project, image, pdk, *_a, mounts=None, **_k):
        seen.update(image=image, root=_bound_root(mounts))
        _stop()
    monkeypatch.setattr(eqy, 'run_eqy', run_eqy)
    arm_a = runner.StepResult('lec_equivalence', 'PASS', 1.0, 'arm A')
    rows = runner._lec_eqy_arm(env.project, 'top', 'n.v', [arm_a])
    return seen, rows[-1].detail


def step_ctx(env, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')
    try:
        try:
            image, root = runner._librelane_step_ctx(env.project, '24', PDK)
        except TypeError:                     # the pre-F25 signature takes no PDK
            image, root = runner._librelane_step_ctx(env.project, '24')
    except contract.Refusal as exc:
        return {}, str(exc)
    return {'image': image, 'root': Path(root)}, ''


def step29(env, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')
    import librelane_postroute as lp
    seen = {}

    def gls(project, top, image, pdk_root, pdk, **_k):
        seen.update(image=image, root=Path(pdk_root))
        _stop()
    monkeypatch.setattr(lp, 'gate_level_sim', gls)
    notes = []
    runner._step29_tool_arm(env.project, 'top', _pdk(), 'librelane', env.tmp / 'sim',
                            env.tmp / 'd.sdf', [], notes)
    return seen, ' '.join(notes)


def step30(env, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')
    import path_spice_tool as pst
    import librelane_postroute as postroute
    # The current Step30 caller reads Step23's bound state before resolving
    # its PDK. Supply that input; keep its actual state/digest reader running.
    folder = env.project / 'phase3/librelane/f25-stapostpnr'
    state = folder / 'state_out.json'
    contract.write_json(state, {})
    contract.write_json(folder / 'config.json',
                        {'meta': {'step': 'OpenROAD.STAPostPNR'}, 'PDK': PDK})
    contract.write_json(env.project / postroute.STEP23_RECORD,
                        {'sta_state': str(state), 'sta_state_sha256': contract.digest(state)})
    seen = {}

    def run_step30(project, image, pdk_root, pdk, **_k):
        seen.update(image=image, root=Path(pdk_root))
        _stop()
    monkeypatch.setattr(pst, 'run_current_step30', run_step30)
    notes = []
    runner._step30_tool_arm(env.project, _pdk(), [], notes)
    return seen, ' '.join(notes)


def step19_20(env, monkeypatch):
    """Steps 19/20 (T98 `librelane_cts_hold.execute`): the direct deck's head
    session is stated (it writes the pre-CTS checkpoint); the tool is stopped
    at `resolve_step_configs`, which receives the image and the host root."""
    runner = importlib.import_module('phase3_one_shot_runner')
    cts = importlib.import_module('librelane_cts_hold')
    out_dir = env.project / 'phase3/stage3/pnr'
    out_dir.mkdir(parents=True)
    (out_dir / 'constraint.sdc').write_text('create_clock -period 24 clk\n')
    pnr_tcl = out_dir / 'pnr.tcl'
    pnr_tcl.write_text(
        'read_lef /t.lef\nread_liberty /l.lib\nread_verilog /n.v\nlink_design chip_top\n'
        f'read_sdc {out_dir}/constraint.sdc\n{runner._PNR_RESUME_ELIDE_BEGIN}\n'
        f'global_placement\n{runner._PNR_CTS_HOLD_BEGIN}\nclock_tree_synthesis\n'
        f'repair_timing -hold\n{runner._PNR_CTS_HOLD_END}\ndetailed_route\n'
        f'{runner._PNR_RESUME_ELIDE_END}\nwrite_def {out_dir}/routed.def\n')

    def docker_exec(container, cmd, *a, **k):
        for ext in ('odb', 'def', 'nl.v', 'insts'):
            (out_dir / f'cts_hold_split/pre_cts.{ext}').write_text('x\n')
        return 0, '', ''
    monkeypatch.setattr(runner, '_docker_exec', docker_exec)
    monkeypatch.setattr(runner, '_after_restore_tcl', lambda *a, **k: '')
    monkeypatch.setattr(runner, '_container_mounts', lambda c: [])
    seen = {}

    def resolve_step_configs(project, image, pdk, ids, *, pdk_root=None, **_k):
        seen.update(image=image, root=Path(pdk_root))
        _stop()
    monkeypatch.setattr(contract, 'resolve_step_configs', resolve_step_configs)
    _rc, out, _ = cts.execute(
        runner, project=env.project, pdk=SimpleNamespace(name=PDK), container='c',
        out_dir=out_dir, out_dir_c=str(out_dir), pnr_tcl=pnr_tcl,
        modes={'19': 'librelane', '20': 'librelane'},
        cmd=f'openroad {pnr_tcl} | tee {out_dir}/openroad.log', spare_plan=None,
        overlay={}, exec_kwargs={})
    return seen, out


STEPS = {'2 lint': step2, '8 synth': step8, '7/8/10 pre-layout signoff': prelayout,
         '13 eqy': step13, '19/20 cts+hold': step19_20, '24/26/26.5ic ctx': step_ctx, '29 gls': step29,
         '30 path spice': step30}
ROOT_STEPS = pytest.mark.parametrize('drive', STEPS.values(), ids=list(STEPS))


# ------------------------------------------------------------------ root+image ---

@ROOT_STEPS
def test_an_undeclared_project_resolves(env, monkeypatch, drive):
    seen, detail = drive(env, monkeypatch)
    assert (seen.get('image'), seen.get('root')) == (env.image, env.resolved_root), detail
    assert (env.resolved_root / PDK).is_dir()


@ROOT_STEPS
def test_a_declared_image_and_root_win_and_the_host_is_not_asked(env, monkeypatch, drive):
    image, root = _declare(env)
    seen, detail = drive(env, monkeypatch)
    assert (seen.get('image'), seen.get('root')) == (image, root), detail
    assert env.fake.calls == []


@ROOT_STEPS
def test_a_refusal_names_the_resolvers_cause(env, monkeypatch, drive):
    _break_the_image(env)
    seen, detail = drive(env, monkeypatch)
    assert seen == {}, 'the tool must not run without a resolved root'
    assert 'LL_PDK_ROOT_NOT_RESOLVABLE' in detail and 'LL_IMAGE_NOT_INSPECTABLE' in detail, detail


# ------------------------------------------------------- step 3: image only ---

def test_step3_undeclared_project_resolves_the_image(env, monkeypatch):
    seen, detail = step3(env, monkeypatch)
    assert seen.get('image') == env.image, detail


def test_step3_declared_image_wins(env, monkeypatch):
    image, _ = _declare(env)
    seen, detail = step3(env, monkeypatch)
    assert seen.get('image') == image, detail


def test_step3_refusal_names_the_resolvers_cause(env, monkeypatch):
    import _eda_pin

    def unresolvable(*_a, **_k):
        raise _eda_pin.ImageNotResolvable('stated: no released image on this host')
    monkeypatch.setattr(_eda_pin, 'image_reference', unresolvable)
    seen, detail = step3(env, monkeypatch)
    assert seen == {}
    assert 'CDC_NETLIST_TOOL_UNAVAILABLE' in detail and 'LL_IMAGE_NOT_RESOLVABLE' in detail, detail


# ------------------------------------------------------------------- pruning ---

def _copy(env, image_id, age):
    """A finished cache copy for `image_id`, made `age` seconds ago."""
    d = env.tmp / 'cache' / image_id.split(':')[1]
    (d / PDK).mkdir(parents=True)
    marker = d / f'{PDK}{MARKER}'
    marker.write_text(json.dumps({'image_id': image_id, 'pdk': PDK}))
    t = marker.stat().st_mtime - age
    os.utime(marker, (t, t))
    return d


def _prune(env):
    fn = getattr(contract, 'prune_pdk_root_cache', None)
    return fn(IMAGE_ID) if fn else {'removed': [], 'kept': [], 'refused': 'absent'}


OLD = ['sha256:' + c * 64 for c in '123']


def test_prune_keeps_current_and_one_previous_and_removes_gone_images(env):
    current = _copy(env, IMAGE_ID, 0)
    prev, old1, old2 = (_copy(env, i, age) for i, age in zip(OLD, (10, 20, 30)))
    record = _prune(env)
    assert sorted(p.name for p in (env.tmp / 'cache').iterdir() if p.is_dir()) == \
        sorted([current.name, prev.name])
    assert sorted(r['image_id'] for r in record['removed']) == sorted(OLD[1:])
    log = [json.loads(l) for l in (env.tmp / 'cache/pdk_root_prune.log.jsonl').read_text().splitlines()]
    assert [sorted(r['image_id'] for r in e['removed']) for e in log] == [sorted(OLD[1:])]


def test_prune_keeps_a_copy_whose_image_is_still_on_the_host(env):
    _copy(env, IMAGE_ID, 0)
    _copy(env, OLD[0], 10)
    held = _copy(env, OLD[1], 20)
    env.fake.held.add(OLD[1])
    record = _prune(env)
    assert held.is_dir() and record['removed'] == []
    assert {'image_id': OLD[1], 'why': 'image still on this host'} in record['kept']


def test_prune_never_removes_a_copy_in_use(env):
    _copy(env, IMAGE_ID, 0)
    _copy(env, OLD[0], 10)
    used = _copy(env, OLD[1], 20)
    env.fake.mounts.append(str(used / PDK))
    record = _prune(env)
    assert used.is_dir() and record['removed'] == []
    assert {'image_id': OLD[1], 'why': 'bound by a running container'} in record['kept']


def test_prune_never_removes_a_copy_being_made(env):
    _copy(env, IMAGE_ID, 0)
    _copy(env, OLD[0], 10)
    busy = _copy(env, OLD[1], 20)
    (busy / f'.{PDK}.partial-x').mkdir()
    _prune(env)
    assert busy.is_dir()


@pytest.mark.parametrize('verb', ['image ls', 'ps', 'inspect'])
def test_prune_removes_nothing_when_docker_cannot_look(env, verb):
    _copy(env, IMAGE_ID, 0)
    _copy(env, OLD[0], 10)
    old = _copy(env, OLD[1], 20)
    env.fake.mounts.append('/elsewhere')          # a running container, so `inspect` is asked
    env.fake.broken.add(verb)
    record = _prune(env)
    assert old.is_dir() and record['removed'] == [] and record['refused'], record


def test_a_new_copy_prunes_and_records_it_in_the_provenance(env):
    for i, age in zip(OLD, (10, 20)):
        _copy(env, i, age)
    answer = contract.pdk_root_resolution(env.project, PDK)
    assert answer['derivation']['cache'] == 'copied'
    pruned = answer['derivation'].get('cache_prune') or {}
    assert [r['image_id'] for r in pruned.get('removed', [])] == [OLD[1]]
    assert not (env.tmp / 'cache' / OLD[1].split(':')[1]).exists()
    assert (env.tmp / 'cache' / OLD[0].split(':')[1]).is_dir()


def test_a_reused_copy_does_not_prune(env):
    contract.pdk_root_resolution(env.project, PDK)
    for i, age in zip(OLD, (10, 20)):
        _copy(env, i, age)
    answer = contract.pdk_root_resolution(env.project, PDK)
    assert answer['derivation']['cache'] == 'reused'
    assert all((env.tmp / 'cache' / i.split(':')[1]).is_dir() for i in OLD[:2])
