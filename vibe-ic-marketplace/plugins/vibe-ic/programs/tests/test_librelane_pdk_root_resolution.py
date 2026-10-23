"""F14: the LibreLane PDK root is resolved at run time, like the image.

Precedence: declared (switch ``pdk_root_host`` > ``VIBEIC_LIBRELANE_PDK_ROOT``)
> resolved from the RESOLVED image's own ``PDK_ROOT`` and the design's PDK >
refused by name. Before F14 a project with no switch had no PDK root, so every
LibreLane arm refused ``LL_PDK_ROOT_NOT_DECLARED`` even though the image it runs
carries the PDK.

Every test STATES its environment: the image identity (`_stated_eda_image`),
the cache directory, and docker itself, which is a fake that performs only
docker's file writes (`docker cp` writes the tree). Nothing is asked of the
host's docker.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin  # noqa: E402
import librelane_contract as contract  # noqa: E402
from _stated_eda_image import STATED_DIGEST, stated_image, state_the_image  # noqa: E402

IMAGE_ID = 'sha256:' + '5a' * 32
# getattr, so the pre-F14 contract RUNS these tests and answers wrongly (a
# control that dies on AttributeError observes nothing).
CACHE_ENV = getattr(contract, 'PDK_ROOT_CACHE_ENV', 'VIBEIC_PDK_ROOT_CACHE')
MARKER = getattr(contract, 'PDK_ROOT_MARKER', '.vibeic_pdk_root.json')
PROVENANCE_REL = getattr(contract, 'PDK_ROOT_PROVENANCE_REL',
                         'phase3/librelane_pdk_root.provenance.json')


def resolution(project, pdk=None, **kwargs):
    """`pdk_root_resolution`; on a contract without it, the old resolver's answer."""
    if hasattr(contract, 'pdk_root_resolution'):
        return contract.pdk_root_resolution(project, pdk, **kwargs)
    path = contract.resolve_pdk_root(project)
    if not path:
        raise contract.Refusal('LL_PDK_ROOT_NOT_DECLARED', 'pre-F14 resolver')
    return {'path': path, 'source': None, 'declared_by': None, 'derivation': {}}


def resolve(project, pdk=None):
    try:
        return contract.resolve_pdk_root(project, pdk)
    except TypeError:                   # pre-F14 signature
        return contract.resolve_pdk_root(project)
GUEST_ROOT = '/opt/stated/pdks'


class FakeDocker:
    """`docker image inspect / create / cp / rm` over a stated image.

    `images` maps a reference to (image id, Config.Env); `trees` lists the
    directories the image holds, relative to nothing (guest paths).
    """

    def __init__(self, images, trees):
        self.images, self.trees, self.calls = images, set(trees), []

    def __call__(self, argv, **_kw):
        self.calls.append(list(argv))
        verb = argv[1:3] if argv[1] == 'image' else argv[1:2]
        if verb == ['image', 'inspect']:
            ref = argv[-1]
            if ref not in self.images:
                return subprocess.CompletedProcess(argv, 1, '', f'No such image: {ref}')
            image_id, env = self.images[ref]
            return subprocess.CompletedProcess(argv, 0, f'{json.dumps(image_id)} {json.dumps(env)}\n', '')
        if verb == ['create']:
            assert '--memory' in argv, 'docker create must carry the memory ceiling'
            return subprocess.CompletedProcess(argv, 0, 'cid0\n', '')
        if verb == ['cp']:
            src, dest = argv[-2].split(':', 1)[1], Path(argv[-1])
            if src not in self.trees:
                return subprocess.CompletedProcess(argv, 1, '', f'Could not find the file {src}')
            (dest / 'libs.tech' / 'librelane').mkdir(parents=True)
            (dest / 'libs.tech' / 'librelane' / 'config.tcl').write_text('# stated\n')
            return subprocess.CompletedProcess(argv, 0, '', '')
        if verb == ['rm']:
            return subprocess.CompletedProcess(argv, 0, '', '')
        raise AssertionError(f'unexpected docker call {argv}')

    def verbs(self):
        return [c[1] if c[1] != 'image' else 'inspect' for c in self.calls]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """The stated world: an image carrying `stated_pdk` under GUEST_ROOT."""
    # These fakes exercise the container-backed resolver.  Pin the route so
    # the result does not depend on whether the test image happens to contain
    # a docker client; native-handoff controls below explicitly pin LOCAL.
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_PDK_ROOT', raising=False)
    monkeypatch.delenv('VIBEIC_LIBRELANE_IMAGE', raising=False)
    monkeypatch.setenv(CACHE_ENV, str(tmp_path / 'cache'))
    image = state_the_image(monkeypatch)
    fake = FakeDocker({image: (IMAGE_ID, ['PATH=/bin', f'PDK_ROOT={GUEST_ROOT}'])},
                      [f'{GUEST_ROOT}/stated_pdk'])
    monkeypatch.setattr(contract.subprocess, 'run', fake)
    project = tmp_path / 'proj'
    (project / 'phase3').mkdir(parents=True)
    return SimpleNamespace(project=project, image=image, fake=fake, tmp=tmp_path)


def _switch(project, **values):
    (project / 'phase3/librelane_switch.json').write_text(json.dumps(values))


# ------------------------------------------------------------ precedence ---

def test_declared_switch_wins_over_env_and_the_image(env, monkeypatch):
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', '/declared/by/env')
    _switch(env.project, pdk_root_host='/declared/by/switch')
    answer = resolution(env.project, 'stated_pdk')
    assert answer['path'] == '/declared/by/switch'
    assert answer['source'] == 'declared'
    assert answer['declared_by'] == 'phase3/librelane_switch.json pdk_root_host'
    assert env.fake.calls == []            # the image was never asked


def test_declared_env_wins_over_the_image(env, monkeypatch):
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', '/declared/by/env')
    answer = resolution(env.project, 'stated_pdk')
    assert (answer['path'], answer['declared_by']) == ('/declared/by/env',
                                                       'env VIBEIC_LIBRELANE_PDK_ROOT')
    assert env.fake.calls == []


def test_ordinary_declared_root_survives_native_probe_without_handoff(env, monkeypatch):
    """The image-root rule is scoped to the production handoff seam."""
    foreign_root = env.tmp / 'foreign-cache'
    foreign_root.mkdir()
    _switch(env.project, pdk_root_host=str(foreign_root))
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: True)

    answer = resolution(env.project, 'stated_pdk')
    assert answer['path'] == str(foreign_root)
    assert answer['source'] == 'declared'


def test_native_handoff_uses_attested_image_root_and_container_keeps_declared(
        env, monkeypatch):
    image_root = env.tmp / 'image-pdks'
    (image_root / 'stated_pdk').mkdir(parents=True)
    foreign_root = env.tmp / 'foreign-cache'
    foreign_root.mkdir()
    _switch(env.project, image=env.image, pdk_root_host=str(foreign_root))
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: True)
    monkeypatch.setattr(contract, 'local_image_attestation',
                        lambda _image: {'image': env.image, 'image_id': IMAGE_ID,
                                        'repo_digests': [env.image]})
    monkeypatch.setenv('PDK_ROOT', str(image_root))

    local = resolution(env.project, 'stated_pdk', native_handoff=True)
    assert local['path'] == str(image_root)
    assert local['source'] == 'resolved'
    assert local['derivation']['cache'] == 'native'

    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: False)
    container = resolution(env.project, 'stated_pdk', native_handoff=True)
    assert container['path'] == str(foreign_root)
    assert container['source'] == 'declared'


@pytest.mark.parametrize('route_key', ['execution_route', 'provider_route'])
def test_native_handoff_refuses_explicit_remote_without_container(env, monkeypatch,
                                                                   route_key):
    foreign_root = env.tmp / 'foreign-cache'
    foreign_root.mkdir()
    _switch(env.project, image=env.image, pdk_root_host=str(foreign_root),
            **{route_key: 'REMOTE'})
    monkeypatch.setattr(contract._ce, 'no_container_route', lambda: True)
    monkeypatch.setattr(contract, 'local_image_attestation',
                        lambda _image: pytest.fail(
                            'REMOTE native route must refuse before image resolution'))

    with pytest.raises(contract.Refusal, match='LL_LOCAL_REMOTE_MISMATCH'):
        resolution(env.project, 'stated_pdk', native_handoff=True)


def test_production_host_pdk_marks_the_native_handoff(monkeypatch, tmp_path):
    import execution_production as production

    root = tmp_path / 'root'
    (root / 'stated_pdk').mkdir(parents=True)
    seen = {}

    def resolve(project, pdk, *, image=None, native_handoff=False, **_kw):
        seen.update(project=project, pdk=pdk, image=image,
                    native_handoff=native_handoff)
        return {'path': str(root)}

    monkeypatch.setattr(production, '_regular', lambda path: False)
    monkeypatch.setattr(contract, 'pdk_root_resolution', resolve)
    pdk = type('Pdk', (), {'name': 'stated_pdk'})()

    result = production._host_pdk(tmp_path, pdk, 'sha256:' + 'ab' * 32)
    assert result['pdk_root_host'] == str((root / 'stated_pdk').resolve())
    assert seen['native_handoff'] is True


# ------------------------------------------------------------ resolution ---

def test_undeclared_root_resolves_from_the_images_own_pdk_root(env):
    answer = resolution(env.project, 'stated_pdk')
    root = Path(answer['path'])
    assert root == env.tmp / 'cache' / IMAGE_ID.split(':')[1]
    assert (root / 'stated_pdk/libs.tech/librelane/config.tcl').is_file()
    assert answer['source'] == 'resolved'
    d = answer['derivation']
    assert d['image'] == stated_image() and d['image_id'] == IMAGE_ID
    assert d['image_pdk_root'] == GUEST_ROOT
    assert d['guest_path'] == f'{GUEST_ROOT}/stated_pdk'
    assert d['host_path'] == str(root / 'stated_pdk')
    assert d['pdk'] == 'stated_pdk' and d['pdk_from'].startswith('caller')
    assert d['cache'] == 'copied'
    # the copy is taken FROM the image's PDK_ROOT, never from a guessed path
    cp = [c for c in env.fake.calls if c[1] == 'cp']
    assert cp and cp[0][-2].endswith(f':{GUEST_ROOT}/stated_pdk')
    # the provenance is recorded in the project, and says where the root came from
    recorded = json.loads((env.project / PROVENANCE_REL).read_text())
    assert recorded == answer
    assert resolve(env.project, 'stated_pdk') == str(root)


def test_the_design_pdk_can_come_from_the_switch(env):
    _switch(env.project, pdk='stated_pdk')
    answer = resolution(env.project)
    assert answer['source'] == 'resolved'
    assert answer['derivation']['pdk_from'] == 'phase3/librelane_switch.json pdk'


def test_a_finished_copy_is_reused_and_a_different_image_is_not(env, monkeypatch):
    first = resolution(env.project, 'stated_pdk')
    before = list(env.fake.verbs())
    again = resolution(env.project, 'stated_pdk')
    assert again['path'] == first['path'] and again['derivation']['cache'] == 'reused'
    assert env.fake.verbs()[len(before):] == ['inspect']      # no create, no cp
    # a new image (new id) gets its own root: a stale copy is never borrowed
    other = 'sha256:' + '6b' * 32
    env.fake.images[stated_image()] = (other, [f'PDK_ROOT={GUEST_ROOT}'])
    third = resolution(env.project, 'stated_pdk')
    assert third['path'].endswith(other.split(':')[1]) and third['derivation']['cache'] == 'copied'


def test_an_unfinished_copy_is_not_reused(env):
    first = resolution(env.project, 'stated_pdk')
    (Path(first['path']) / f'stated_pdk{MARKER}').unlink()
    assert resolution(env.project, 'stated_pdk')['derivation']['cache'] == 'copied'


def test_the_image_is_found_by_digest_under_another_repository(env, monkeypatch):
    """#2170: the digest is the identity. The configured repository may not be
    the name this host holds the bytes under."""
    held = f'mirror.example/vibeic-eda@{STATED_DIGEST}'
    env.fake.images = {held: env.fake.images[stated_image()]}
    monkeypatch.setattr(_eda_pin, 'local_references_for_digest',
                        lambda digest: ((held,) if digest == STATED_DIGEST else (), ''))
    answer = resolution(env.project, 'stated_pdk')
    # The image RUN is the name this host holds: `image_reference` no longer
    # composes the configured repository with the digest (lane migf14).
    assert answer['source'] == 'resolved' and answer['derivation']['image'] == held


# --------------------------------------------------------------- refusal ---

@pytest.mark.parametrize('mutate,pdk,inner', [
    (lambda f: f.images.clear(), 'stated_pdk', 'LL_IMAGE_NOT_INSPECTABLE'),
    (lambda f: f.images.update({stated_image(): (IMAGE_ID, ['PATH=/bin'])}),
     'stated_pdk', 'LL_IMAGE_PDK_ROOT_UNDECLARED'),
    (lambda f: None, 'other_pdk', 'LL_IMAGE_PDK_ABSENT'),
    (lambda f: None, None, 'LL_PDK_UNDECLARED'),
    (lambda f: None, '../escape', 'LL_PDK_NAME_INVALID'),
])
def test_neither_declared_nor_resolved_refuses_by_name(env, monkeypatch, mutate, pdk, inner):
    # Held under the configured name only, so the image resolves and each
    # mutation of the (fake) daemon is what refuses. Holding NOTHING would
    # refuse earlier, at `image_reference` (IMAGE_NOT_PRESENT), and never
    # reach the inner cause this test names.
    monkeypatch.setattr(_eda_pin, 'local_references_for_digest',
                        lambda digest: ((stated_image(),), ''))
    mutate(env.fake)
    with pytest.raises(contract.Refusal) as caught:
        resolution(env.project, pdk)
    assert caught.value.code == 'LL_PDK_ROOT_NOT_RESOLVABLE' and inner in str(caught.value)
    assert resolve(env.project, pdk) is None
    assert not list((env.tmp / 'cache').glob('*/*.partial-*'))    # no half copy left


def test_an_unresolvable_image_refuses_the_pdk_root_by_name(env, monkeypatch):
    def unresolvable(env=None, *, allow_pull=False):
        raise _eda_pin.ImageNotResolvable(['this host: none'])
    monkeypatch.setattr(_eda_pin, 'resolved_image_digest', unresolvable)
    with pytest.raises(contract.Refusal, match='LL_PDK_ROOT_NOT_RESOLVABLE.*LL_IMAGE_NOT_RESOLVABLE'):
        resolution(env.project, 'stated_pdk')


# ------------------------------------------------- the runner's consumers ---

def test_signoff_runs_on_the_resolved_root_with_no_declaration(env, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')
    import librelane_signoff
    seen = {}

    def fake_run(project, image, pdk_root, pdk, **_kw):
        seen.update(image=image, root=pdk_root, pdk=pdk)
        return {'status': 'PASS'}
    monkeypatch.setattr(librelane_signoff, 'run', fake_run)
    monkeypatch.setattr(runner, '_LL_SIGNOFF_RUNS', {})
    runner._librelane_signoff_run(env.project, 'top', SimpleNamespace(name='stated_pdk'),
                                  extract=True, time=False)
    assert seen['root'] == env.tmp / 'cache' / IMAGE_ID.split(':')[1]
    assert (seen['root'] / seen['pdk']).is_dir() and seen['image'] == stated_image()


def test_floorplan_passes_the_pdk_root_gate_with_no_declaration(env, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')

    class Reached(Exception):
        pass

    def producer(*_a, **_k):
        raise Reached
    monkeypatch.setattr(runner, '_padring_chip_top_record', lambda project: None)
    monkeypatch.setattr(runner, 'step_io_pad_chip_top_gen', producer)
    pdk = SimpleNamespace(name='stated_pdk')
    with pytest.raises(Reached):
        runner._prepare_librelane_floorplan_for_route(
            env.project, pdk, 'c', env.project / 'phase3/stage3/pnr', None,
            {'15': 'librelane', '15.5ic': 'librelane'}, bounded_state=True)


def test_step_27_corner_mounts_the_resolved_root_with_no_declaration(env):
    runner = importlib.import_module('phase3_one_shot_runner')
    import test_librelane_signoff as landed
    project, corner, _spef, _nl = landed._step23_tool_record(env.tmp)
    _switch(project, steps={'23': 'librelane'})           # no pdk_root_host
    env.fake.trees.add(f'{GUEST_ROOT}/gfx')
    tool = runner._librelane_si_corner_inputs(project)
    root = env.tmp / 'cache' / IMAGE_ID.split(':')[1]
    assert tool is not None and tool['corner'] == corner
    assert tool['mounts'] == [(root / 'gfx', '/pdk/gfx')] and (root / 'gfx').is_dir()


def test_opt_in_step_37_uses_the_resolved_root_with_no_declaration(env, monkeypatch):
    runner = importlib.import_module('phase3_one_shot_runner')
    import librelane_step37
    import drc_feedback_repair
    import execution_policy
    # This is the retained opt-in tool seam. Ordinary Default now owns its
    # single fill-aware streamer and is covered at that existing boundary.
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'ultra'})

    class Reached(Exception):
        pass
    seen = {}

    def fake_run(project, image, pdk_root, pdk, *_a, **_k):
        seen.update(image=image, root=pdk_root, pdk=pdk)
        raise Reached
    _switch(env.project, steps={'37': 'librelane'})
    pnr = runner._pl.pnr_dir(env.project)
    pnr.mkdir(parents=True, exist_ok=True)
    for name in ('top.def', 'routed.def'):
        (pnr / name).write_text('DESIGN top ;\n')
    monkeypatch.setattr(runner, '_layout_basis', lambda *a, **k: ('digest', None))
    monkeypatch.setattr(runner._ga, 'gate_passed', lambda *a, **k: True)
    monkeypatch.setattr(runner, '_vacuous_on_unrouted', lambda *a, **k: None)
    monkeypatch.setattr(drc_feedback_repair, 'has_reviewed_rule', lambda *a, **k: False)
    monkeypatch.setattr(runner, '_streamout_top', lambda def_file, top: (top, ''))
    monkeypatch.setattr(runner, 'publish_database_unit_declaration', lambda *a, **k: None)
    monkeypatch.setattr(runner, 'publish_tapeout_declarations', lambda *a, **k: None)
    monkeypatch.setattr(librelane_step37, 'run', fake_run)
    pdk = SimpleNamespace(name='stated_pdk', drc_deck=None)
    with pytest.raises(Reached):
        runner.step_gds(env.project, 'top', pdk, 'c')
    assert Path(seen['root']) == env.tmp / 'cache' / IMAGE_ID.split(':')[1]
    assert seen['image'] == stated_image() and seen['pdk'] == 'stated_pdk'
