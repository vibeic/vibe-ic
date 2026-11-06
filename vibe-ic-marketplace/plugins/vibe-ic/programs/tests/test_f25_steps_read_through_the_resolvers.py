"""F25: every step reads the image and the PDK root through the contract's resolvers.

`librelane_contract.resolve_image` and `pdk_root_resolution` answer declared >
resolved at run time > refused by name (T89, F14). Before F25 these steps read
`image` / `pdk_root_host` STRAIGHT from `phase3/librelane_switch.json`, so a
project that declared neither refused (or ran on no root) even though the
resolvers would answer:

- step 2 lint (`step_rtl_lint_tool`): the root;
- step 3 CDC netlist (`_cdc_netlist.build`): the image;

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
















STEPS = {'2 lint': step2}
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
