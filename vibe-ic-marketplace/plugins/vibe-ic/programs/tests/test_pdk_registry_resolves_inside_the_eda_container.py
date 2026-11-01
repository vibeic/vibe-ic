"""A registry-declared PDK must resolve when the runner is INSIDE the image.

MEASURED DEFECT (2026-09-06, subservient x gf180mcuD, canonical front door
`vibe_ic_one_shot_runner.py` running inside ghcr.io/vibeic/vibeic-eda 0.3.46).
Phase 2 reached PASS_WITH_WAIVERS and Phase 3 halted on its very first act:

    [FAIL] --pdk gf180mcuD: declared in pdk_registry.json but its assets could
    not be resolved inside container 'vibeic-eda'
    (container_path='/foss/pdks/gf180mcuD'). REFUSING to fall back to sky130A

The refusal is CORRECT policy and stays.  What was wrong is that the assets
were there.  All six of that registry entry's declared paths matched exactly
one file each, at the exact path the probe was asking about, on the process's
OWN filesystem.  `_registry_glob_one` and `_pdk_config_from_registry` reached
the PDK only through `docker exec`, and there is no `docker` binary inside the
image, so every probe returned 127, every asset resolved to None, and a fully
present PDK was reported absent.

The repo already settled this exact question one layer over: `_read_pdk_text`
reads "Host read first (so a staged/host-local copy still wins), then the
container", for the same reason.  The registry resolver never got that order.

FIX (v1.17.79, then CORRECTED here).  v1.17.79 answered this by giving
`_registry_glob_one` its OWN local resolver, consulted before the container
and unconditionally.  That resolved the in-image case and broke the contract
one layer up: a second, container-blind oracle answers from whatever this
filesystem happens to carry, so three tests pinning "a DECLARED asset that
does not resolve is a REFUSAL" went `DID NOT RAISE SystemExit`.  A refusal
that depends on what the image happens to ship is not a refusal.

The route now lives at the ONE exec seam instead: `_local_exec_mode()` asks
whether a route to a container exists at all, and `_docker_exec_raw` runs the
same `bash -lc` probe on THIS filesystem when none does.  So every assertion
below still holds — a present asset resolves without docker — while the
resolver keeps asking the container it was handed, and a mocked container
still decides the answer.

§4.05 NO-LEAK — resolution can never be laxer than the container branch:
  * an absent root still resolves to None, so the caller still REFUSES;
  * a glob that matches nothing still resolves to None;
  * a candidate outside the PDK root is rejected, textually AND after
    symlink/`..` resolution — now on BOTH routes, because the predicate
    (`_registry_path_under_root`) sits at the one place both pass through.
    (The literal container branch had no containment at all before this.)
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

# A container name that cannot exist, so the docker branch is guaranteed to
# fail: the ONLY way a path comes back is the local branch under test.
_NO_SUCH_CONTAINER = "cza-no-such-container-000"


@pytest.fixture
def in_image(monkeypatch):
    """STAGE the in-image condition; never inherit it from the host.

    vibe-ic#2100.  Every assertion below is about the LOCAL branch, and that
    branch is selected by exactly one predicate — `_container_exec.
    no_container_route()`, i.e. "there is no `docker` client on PATH".  This
    file used to state that condition only in its prose and then take whatever
    the machine happened to be, which made it a test about the HOST:

      * on a bare host with no Docker CLI it measured the local branch;
      * under `tools/ci/run_suite_in_eda_image.sh`, which BINDS the host's
        docker binary and socket into the container on purpose, `shutil.which`
        answers `/usr/bin/docker`, the CONTAINER branch runs, the deliberately
        absent `cza-no-such-container-000` is unreachable, and a present asset
        resolves to None.  MEASURED 2026-09-07 on 8HD-4 in both env arms:
        `test_glob_resolves_from_the_local_filesystem_without_docker` and
        `test_literal_path_resolves_from_the_local_filesystem` red, with
        "a present asset resolved to None" — a message about the harness.

    The NO-LEAK tests were worse off than the two reds: on such a host they
    PASSED for the wrong reason.  `None` came back because the container was
    unreachable, not because the local branch had refused, so the containment
    they exist to pin was never exercised.  Staging the condition is therefore
    a STRENGTHENING of this file, not a relaxation of it.

    `shutil.which` is substituted on `_container_exec`, which is where the one
    predicate reads it, and the phase-3 module's memoised answer is cleared on
    both sides of the test so no ordering can leak a cached route.
    """
    import _container_exec as _cex
    m = _p3()
    real_which = shutil.which

    def _no_docker(name, *a, **k):
        return None if name == "docker" else real_which(name, *a, **k)

    monkeypatch.setattr(_cex.shutil, "which", _no_docker)
    monkeypatch.setattr(m, "_LOCAL_EXEC_MODE", None, raising=False)
    monkeypatch.setattr(_cex, "_ANNOUNCED", set(), raising=False)
    assert m._local_exec_mode() is True, (
        "the in-image condition was not staged; these tests would measure the "
        "host instead of the local branch")
    yield
    m._LOCAL_EXEC_MODE = None


@pytest.fixture
def beside_a_container(monkeypatch):
    """The other route, staged the same way: a docker client IS on PATH."""
    import _container_exec as _cex
    m = _p3()
    real_which = shutil.which
    monkeypatch.setattr(
        _cex.shutil, "which",
        lambda n, *a, **k: ("/usr/bin/docker" if n == "docker"
                            else real_which(n, *a, **k)))
    monkeypatch.setattr(m, "_LOCAL_EXEC_MODE", None, raising=False)
    assert m._local_exec_mode() is False
    yield
    m._LOCAL_EXEC_MODE = None


def _p3():
    key = "p3_pdkreg"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        key, PROGRAMS / "phase3_one_shot_runner.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[key] = m
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def _fake_pdk(tmp_path: Path) -> Path:
    """A minimal PDK tree with the directory shape a registry entry declares."""
    root = tmp_path / "pdks" / "testpdkA"
    lib = root / "libs.ref" / "scl" / "lib"
    lef = root / "libs.ref" / "scl" / "lef"
    tlef = root / "libs.ref" / "scl" / "techlef"
    for d in (lib, lef, tlef):
        d.mkdir(parents=True, exist_ok=True)
    (lib / "scl__tt_025C_1v80.lib").write_text("library (scl) { }\n")
    (lef / "scl.lef").write_text("SITE unit_site\n")
    (tlef / "scl__nom.tlef").write_text("LAYER li1 ;\n  TYPE ROUTING ;\n")
    return root


def test_glob_resolves_from_the_local_filesystem_without_docker(in_image, tmp_path):
    """THE DEFECT: the assets are right here, and no docker is needed to see
    them."""
    m = _p3()
    root = _fake_pdk(tmp_path)
    got = m._registry_glob_one(
        _NO_SUCH_CONTAINER, str(root), "libs.ref/scl/lib/*tt*.lib")
    assert got is not None, "a present asset resolved to None"
    assert got.endswith("scl__tt_025C_1v80.lib"), got


def test_literal_path_resolves_from_the_local_filesystem(in_image, tmp_path):
    """The non-glob branch too — registry entries use both forms."""
    m = _p3()
    root = _fake_pdk(tmp_path)
    got = m._registry_glob_one(
        _NO_SUCH_CONTAINER, str(root), "libs.ref/scl/lef/scl.lef")
    assert got is not None and got.endswith("scl.lef"), got


def test_absent_root_still_resolves_to_none(in_image, tmp_path):
    """NO-LEAK: the caller must still be able to REFUSE."""
    m = _p3()
    got = m._registry_glob_one(
        _NO_SUCH_CONTAINER, str(tmp_path / "not_a_pdk"),
        "libs.ref/scl/lib/*tt*.lib")
    assert got is None, got


def test_glob_matching_nothing_still_resolves_to_none(in_image, tmp_path):
    """NO-LEAK: a present root does not excuse an absent asset."""
    m = _p3()
    root = _fake_pdk(tmp_path)
    got = m._registry_glob_one(
        _NO_SUCH_CONTAINER, str(root), "libs.ref/scl/lib/*nothing*.lib")
    assert got is None, got


def test_a_candidate_outside_the_pdk_root_is_rejected(tmp_path):
    """NO-LEAK: resolution is confined to the declared PDK root."""
    m = _p3()
    root = _fake_pdk(tmp_path)
    outside = tmp_path / "outside.lef"
    outside.write_text("x\n")
    assert m._registry_path_under_root(str(root) + "/", str(outside)) is False


def test_a_dotdot_pattern_that_starts_under_the_root_is_rejected(in_image, tmp_path):
    """NO-LEAK: the half a textual prefix test cannot make — end to end, on
    the route the resolver actually takes."""
    m = _p3()
    root = _fake_pdk(tmp_path)
    outside = tmp_path / "outside.lef"
    outside.write_text("x\n")
    escaped = f"{root}/../outside.lef"
    assert escaped.startswith(str(root) + "/"), "arm must be textually under root"
    assert m._registry_path_under_root(str(root) + "/", escaped) is False
    # and the resolver itself refuses it, though the file is right there
    assert m._registry_glob_one(
        _NO_SUCH_CONTAINER, str(root), "../outside.lef") is None


@pytest.mark.parametrize("route", ["in_image", "beside_a_container"])
def test_a_root_that_is_not_on_this_filesystem_resolves_to_none(
        route, request, tmp_path):
    """A PDK root that is not here resolves to nothing, whichever route runs:
    beside a container the named container decides, and in-image the probe runs
    on this filesystem and finds no such directory. Either way the caller
    REFUSES.

    BOTH routes are now STAGED and both are RUN (vibe-ic#2100).  The sentence
    above was already claiming both; what the file did was take one of them by
    accident and never name which."""
    request.getfixturevalue(route)
    m = _p3()
    assert m._registry_glob_one(
        _NO_SUCH_CONTAINER, "/foss/pdks/definitely_not_here",
        "libs.ref/x/*.lib") is None


@pytest.fixture
def declared_local_pdk(tmp_path, monkeypatch):
    """Real registry contract, neutral asset contents, explicit LOCAL route."""
    from _hostpaths import require_repo

    registry = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                            "programs", "pdk_registry.json")
    entry = next(row for row in json.loads(registry.read_text())["pdks"]
                 if row.get("container_path_glob"))
    root = tmp_path / "declared-root"
    pdk = root / entry["name"]
    for key, text in (("liberty_glob", "library (neutral) {}\n"),
                      ("tech_lef_glob", "LAYER route1\n TYPE ROUTING ;\n"),
                      ("cell_lef_glob", "SITE neutral_site\n")):
        path = pdk / entry[key].replace("*", "neutral")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("VIBEIC_LIBRELANE_ROUTE", "LOCAL")
    monkeypatch.setenv("VIBEIC_LIBRELANE_PDK_ROOT", str(root))
    calls = []

    def absent_container(container, command, timeout=1800):
        calls.append(command)
        return 1, "", "the LOCAL provider has no named Docker container"

    monkeypatch.setattr(_p3(), "_docker_exec_raw", absent_container)
    return project, root, entry, calls


@pytest.mark.parametrize("declaration", ["environment", "switch"])
def test_declared_local_pdk_resolves_without_a_container(
        declared_local_pdk, monkeypatch, declaration):
    project, root, entry, calls = declared_local_pdk
    if declaration == "switch":
        switch = project / "phase3/librelane_switch.json"
        switch.parent.mkdir()
        switch.write_text(json.dumps({"route": "LOCAL", "pdk_root_host": str(root)}))
        monkeypatch.setenv("VIBEIC_LIBRELANE_PDK_ROOT", str(root / "wrong-root"))
    config = _p3()._pdk_config_from_registry(project, entry)
    assert config is not None, "present declared LOCAL assets must resolve"
    assert config.name == entry["name"]
    for field, key in (("liberty", "liberty_glob"), ("tech_lef", "tech_lef_glob"),
                       ("cell_lef", "cell_lef_glob")):
        assert getattr(config, field) == str(
            root / entry["name"] / entry[key].replace("*", "neutral"))
    assert _p3()._detect_pdk(project, override=entry["name"]) == config
    assert calls == [], "an explicit LOCAL route must not probe Docker"


def test_declared_local_pdk_container_route_keeps_container_authority(
        declared_local_pdk, monkeypatch):
    from test_issue211_registry_driven_pdk_refuse import _FakeContainer

    project, root, entry, _ = declared_local_pdk
    monkeypatch.setenv("VIBEIC_LIBRELANE_ROUTE", "CONTAINER")
    container_root = '/foss/pdks/' + entry["container_path_glob"].replace("*", "selected")
    existing = {container_root}
    existing.update(str(Path(container_root) / entry[key].replace("*", "neutral")) for key in
                    ("liberty_glob", "tech_lef_glob", "cell_lef_glob"))
    fake = _FakeContainer(existing)
    monkeypatch.setattr(_p3(), "_docker_exec_raw", fake)
    config = _p3()._pdk_config_from_registry(project, entry)
    assert config.name == entry["name"]
    assert config.liberty == str(
        Path(container_root) / entry["liberty_glob"].replace("*", "neutral"))
    assert not config.liberty.startswith(str(root))
    assert fake.calls, "the container route must still ask its container"


@pytest.mark.parametrize("missing", ["undeclared", "absent", "wrong-pdk"])
def test_declared_local_pdk_missing_root_refuses_by_name(
        declared_local_pdk, monkeypatch, missing):
    project, root, entry, calls = declared_local_pdk
    if missing == "undeclared":
        monkeypatch.delenv("VIBEIC_LIBRELANE_PDK_ROOT")
    elif missing == "absent":
        monkeypatch.setenv("VIBEIC_LIBRELANE_PDK_ROOT", str(root / "absent"))
    else:
        monkeypatch.setenv("VIBEIC_LIBRELANE_PDK_ROOT", str(root / entry["name"]))
    with pytest.raises(SystemExit, match=entry["name"]):
        _p3()._detect_pdk(project, override=entry["name"])
    assert calls == [], "a missing LOCAL root must not fall back to Docker"


def test_declared_local_pdk_missing_asset_refuses_by_name(declared_local_pdk):
    project, root, entry, calls = declared_local_pdk
    (root / entry["name"] / entry["liberty_glob"].replace("*", "neutral")).unlink()
    with pytest.raises(SystemExit, match=entry["name"]):
        _p3()._detect_pdk(project, override=entry["name"])
    assert calls == []


def test_declared_local_pdk_ambiguous_asset_refuses_by_name(
        declared_local_pdk, monkeypatch):
    project, root, entry, calls = declared_local_pdk
    directory = Path(entry["tech_lef_glob"]).parent
    (root / entry["name"] / directory / "another.tlef").write_text("LAYER route1\n TYPE ROUTING ;\n")
    entry = dict(entry, tech_lef_glob=str(directory / "*.tlef"))
    reader = _p3()._pdk_registry_entry
    reader("")  # Preserve the registry reader and its normal named-PDK census.
    monkeypatch.setattr(reader, "_cache", {**reader._cache, entry["name"]: entry})
    with pytest.raises(SystemExit, match=entry["name"] + ".*ambiguous"):
        _p3()._detect_pdk(project, override=entry["name"])
    assert calls == []


def test_declared_local_pdk_asset_outside_root_is_refused(declared_local_pdk):
    project, root, entry, calls = declared_local_pdk
    outside = root / "foreign.lib"
    outside.write_text("library (foreign) {}\n")
    asset = root / entry["name"] / entry["liberty_glob"].replace("*", "neutral")
    asset.unlink()
    asset.symlink_to(outside)
    with pytest.raises(SystemExit, match=entry["name"]):
        _p3()._detect_pdk(project, override=entry["name"])
    assert calls == []


@pytest.mark.parametrize('route', ['LOCAL', 'CONTAINER'])
@pytest.mark.parametrize('count', [1, 5])
def test_registry_complete_liberty_roster_on_both_routes(
        declared_local_pdk, monkeypatch, route, count):
    from test_issue211_registry_driven_pdk_refuse import _FakeContainer
    project, parent, entry, _ = declared_local_pdk
    root = parent / entry['name']
    directory = root / 'models'
    directory.mkdir()
    paths = []
    for i in reversed(range(count)):
        path = directory / f'group_{i}_RVT_TT.lib'
        path.write_text(f'library (group_{i}) {{\n cell (cell_{i}) {{ area : 1; }}\n}}\n')
        paths.append(str(path))
    entry = dict(entry, liberty_glob='models/*_RVT_TT.lib')
    monkeypatch.setenv('VIBEIC_LIBRELANE_ROUTE', route)
    if route == 'CONTAINER':
        monkeypatch.setattr(_p3(), '_registry_container_root', lambda *_: str(root))
        fake = _FakeContainer({str(root)} | {str(p) for p in root.rglob('*')})
        monkeypatch.setattr(_p3(), '_docker_exec_raw', fake)
    try:
        result = _p3()._pdk_config_from_registry(project, entry)
        observed = result.liberty if result is not None else 'UNRESOLVED'
    except SystemExit as exc:
        observed = str(exc)
    expected = sorted(paths) if count > 1 else paths[0]
    assert observed == expected
    # Legacy one-file APIs must see every cell; never a selected group.
    model = getattr(_p3(), '_liberty_model_path', lambda value, **_: value)(observed, project=project)
    if count == 1:
        assert model == expected
    text = Path(model).read_text()
    assert all(f'cell_{i}' in text for i in range(count))


@pytest.mark.parametrize('route', ['LOCAL', 'CONTAINER'])
def test_registry_ambiguous_single_asset_names_pdk_key_candidates(
        declared_local_pdk, monkeypatch, route):
    from test_issue211_registry_driven_pdk_refuse import _FakeContainer
    project, parent, entry, _ = declared_local_pdk
    root = parent / entry['name']
    directory = root / 'technology'
    directory.mkdir()
    candidates = [directory / name for name in ('a.tlef', 'b.tlef')]
    for path in candidates:
        path.write_text('LAYER route1\n TYPE ROUTING ;\n')
    entry = dict(entry, tech_lef_glob='technology/*.tlef')
    monkeypatch.setenv('VIBEIC_LIBRELANE_ROUTE', route)
    if route == 'CONTAINER':
        monkeypatch.setattr(_p3(), '_registry_container_root', lambda *_: str(root))
        monkeypatch.setattr(_p3(), '_docker_exec_raw', _FakeContainer(
            {str(root)} | {str(p) for p in root.rglob('*')}))
    try:
        _p3()._pdk_config_from_registry(project, entry)
        observed = 'CONFIG_RESOLVED'
    except SystemExit as exc:
        observed = str(exc)
    assert 'REGISTRY_ASSET_AMBIGUOUS' in observed, observed
    assert entry['name'] in observed and 'tech_lef_glob' in observed
    assert all(str(path) in observed for path in candidates)


def test_split_liberty_reaches_native_lib_config_and_sta_reader(tmp_path):
    import inspect
    import librelane_contract as contract
    from test_librelane_contract import design
    project = design(tmp_path)
    rtl = project / 'phase2/stage1/rtl/neutral.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module neutral(input clk, output y); assign y=clk; endmodule\n')
    paths = [str(project / f'group_{i}.lib') for i in range(5)]
    for path in paths:
        Path(path).write_text('library (neutral) {}\n')
    config = contract.emit_synthesis_config(project, 'processA', project / 'synth.json',
        [rtl], [], False, synth_liberty=paths)
    assert config['LIB']['*'] == paths
    # Drive the existing full PnR Tcl builder, rather than a new helper alone.
    builder = _p3()._build_pnr_tcl_text
    values = {name: '' for name, param in inspect.signature(builder).parameters.items()
              if param.default is inspect.Parameter.empty}
    values.update(tech_lef_c='technology.lef', cell_lef_c='cells.lef', liberty_c=paths,
                  top='neutral', metal_prefix='route', die_w=100, die_h=100,
                  core_pad=10, core_w=80, core_h=80, util=40)
    text = builder(**values)
    assert all(f'read_liberty {path}\n' in text for path in paths)


@pytest.mark.parametrize('name', ['sky130A', 'gf180mcuD', 'ihp-sg13g2', 'nangate45'])
def test_single_file_registry_config_bytes(tmp_path, monkeypatch, name):
    """Real registry data, neutral files; publish exact bytes for arm comparison."""
    from dataclasses import asdict
    import os
    from _hostpaths import require_repo
    registry = json.loads(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                                      'programs', 'pdk_registry.json').read_text())
    entry = next(row for row in registry['pdks'] if row['name'] == name)
    parent = tmp_path / 'pdks'
    root = parent / name
    for key, text in (('liberty_glob', 'library (neutral) {}\n'),
                      ('tech_lef_glob', 'LAYER route1\n TYPE ROUTING ;\n'),
                      ('cell_lef_glob', 'SITE neutral_site\n'),
                      ('cell_gds_glob', 'neutral test bytes')):
        path = root / entry[key].replace('*', 'neutral')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    project = tmp_path / 'project'
    project.mkdir()
    monkeypatch.setenv('VIBEIC_LIBRELANE_ROUTE', 'LOCAL')
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', str(parent))
    config = _p3()._pdk_config_from_registry(project, entry)
    assert isinstance(config.liberty, str)
    assert config.liberty == str(root / entry['liberty_glob'].replace('*', 'neutral'))
    destination = os.environ.get('PDK_CONFIG_SNAPSHOT')
    if destination:
        target = Path(destination)
        records = json.loads(target.read_text()) if target.exists() else {}
        records[name] = json.dumps(asdict(config), sort_keys=True, separators=(',', ':'))
        target.write_text(json.dumps(records, sort_keys=True, indent=2) + '\n')


@pytest.mark.parametrize('case', ['declared', 'missing_declaration', 'missing_distribution',
                                 'one_glob', 'ambiguous_glob', 'dotdot'])
def test_container_registry_root_is_bound_to_runtime_declaration(tmp_path, monkeypatch, case):
    from test_issue211_registry_driven_pdk_refuse import _FakeContainer
    parent = str(tmp_path / 'declared')
    name = 'neutral_pdk'
    expected = parent + '/' + name
    existing = {expected}
    entry = {'name': name, 'container_path': '/legacy/layout/neutral_pdk'}
    declared = parent
    if case == 'missing_declaration':
        declared = None
    elif case == 'missing_distribution':
        existing.clear()
    elif case in ('one_glob', 'ambiguous_glob'):
        entry['container_path_glob'] = '*/' + name
        expected = parent + '/selected/' + name
        existing = {expected}
        if case == 'ambiguous_glob':
            existing.add(parent + '/other/' + name)
    elif case == 'dotdot':
        entry['container_path_glob'] = '../' + name
    fake = _FakeContainer(existing, pdk_root=declared)
    monkeypatch.setattr(_p3(), '_docker_exec_raw', fake)
    try:
        observed = _p3()._registry_container_root('container', entry)
    except SystemExit as exc:
        observed = str(exc)
    if case in ('declared', 'one_glob'):
        assert observed == expected
    else:
        code = {'missing_declaration': 'REGISTRY_PDK_ROOT_UNDECLARED',
                'missing_distribution': 'REGISTRY_PDK_DISTRIBUTION_MISSING',
                'ambiguous_glob': 'REGISTRY_PDK_ROOT_AMBIGUOUS',
                'dotdot': 'REGISTRY_PDK_ROOT_GLOB_INVALID'}[case]
        assert code in observed and name in observed, observed
        if case == 'ambiguous_glob':
            assert all(path in observed for path in existing)


@pytest.fixture
def resolved_store_pdk(tmp_path, monkeypatch):
    store = tmp_path / 'store'
    bundle = store / ('0' * 32 + '-bundle')
    models = store / ('1' * 32 + '-models')
    foreign = store / ('2' * 32 + '-foreign')
    root = bundle / 'neutral_pdk'
    root.mkdir(parents=True)
    asset = models / 'libs.ref/scl/lef/technology.lef'
    asset.parent.mkdir(parents=True)
    asset.write_text('LAYER route1\n TYPE ROUTING ;\n')
    (root / 'libs.ref').symlink_to(models / 'libs.ref', target_is_directory=True)
    foreign.mkdir()
    outside = foreign / 'unowned.lef'
    outside.write_text('outside declared PDK tree\n')
    monkeypatch.setenv('PDK_ROOT', str(bundle))
    return root, asset, outside


def test_root_owned_sibling_store_tree_is_admitted(in_image, resolved_store_pdk):
    root, target, _ = resolved_store_pdk
    path = root / 'libs.ref/scl/lef/technology.lef'
    assert path.resolve() == target and path.is_file()
    assert _p3()._registry_path_under_root(str(root) + '/', str(path)) is True
    assert _p3()._registry_glob_one(_NO_SUCH_CONTAINER, str(root),
                                   'libs.ref/scl/lef/technology.lef') == str(path)


@pytest.mark.parametrize('escape', ['etc_file', 'etc_directory', 'foreign_store', 'nested_foreign'])
def test_root_owned_tree_does_not_enroll_planted_symlinks(
        in_image, resolved_store_pdk, escape):
    root, target, outside = resolved_store_pdk
    if escape == 'etc_directory':
        (root / 'system').symlink_to('/etc', target_is_directory=True)
        path = root / 'system/passwd'
    elif escape == 'nested_foreign':
        path = root / 'libs.ref/scl/lef/planted.lef'
        path.symlink_to(outside)
    else:
        path = root / 'planted.lef'
        path.symlink_to('/etc/passwd' if escape == 'etc_file' else outside)
    assert path.is_file(), 'escape must exist, not pass because absent'
    assert _p3()._registry_path_under_root(str(root) + '/', str(path)) is False
    assert _p3()._registry_glob_one(_NO_SUCH_CONTAINER, str(root), str(path.relative_to(root))) is None


def test_lexical_dotdot_is_refused_even_when_it_normalizes_inside_root(in_image, tmp_path):
    root = _fake_pdk(tmp_path)
    (root / 'subdirectory').mkdir()
    path = str(root) + '/subdirectory/../libs.ref/scl/lib/scl__tt_025C_1v80.lib'
    assert Path(path).is_file()
    assert _p3()._registry_path_under_root(str(root) + '/', path) is False


def test_real_installed_ihp_tech_lef_resolves_without_alias(in_image):
    import os
    from _hostpaths import require_repo
    registry = json.loads(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                                      'programs', 'pdk_registry.json').read_text())
    entry = next(row for row in registry['pdks'] if row['name'] == 'ihp-sg13g2')
    root = Path(os.environ['PDK_ROOT']) / entry['name']
    path = root / entry['tech_lef_glob']
    assert path.is_file() and (root / 'libs.ref').is_symlink()
    assert _p3()._registry_path_under_root(str(root) + '/', str(path)) is True
    assert _p3()._registry_glob_one(_NO_SUCH_CONTAINER, str(root), entry['tech_lef_glob']) == str(path)


@pytest.mark.parametrize('split', [False, True])
def test_clock_plan_and_ties_consume_complete_timing_view(tmp_path, split):
    from types import SimpleNamespace
    import _physical_current as physical
    paths = []
    for cell in ('tie_hi', 'tie_lo'):
        path = tmp_path / f'{cell}_TT.lib'
        path.write_text(f'library (neutral) {{\n cell ({cell}) {{\n pin (Y) {{ '
                        'direction : output; } } }\n')
        paths.append(str(path))
    selected = paths if split else paths[0]
    pdk = SimpleNamespace(liberty=selected, macro_libs=[paths[-1]])
    assert physical.clock_plan_liberty_paths(pdk) == paths
    ties = _p3()._v1_6_596_discover_tie_cells(selected, '')
    assert ties['hi_cell'] == 'tie_hi'
    assert ties['lo_cell'] == ('tie_lo' if split else None)
    directive = _p3()._v1_6_596_build_hilomap_directive(selected, '')
    if split:
        assert 'tie_hi Y' in directive
        assert 'tie_lo Y' in directive
    else:
        assert directive == ''


@pytest.mark.parametrize('invalid', [None, [], ['', 'valid.lib'], [42]])
def test_clock_plan_refuses_invalid_primary_roster(invalid):
    from types import SimpleNamespace
    import _physical_current as physical
    with pytest.raises(ValueError, match='CLOCK_PLAN_LIBERTY_MISSING'):
        physical.clock_plan_liberty_paths(SimpleNamespace(liberty=invalid))


@pytest.mark.parametrize('route', ['local', 'container', 'staged'])
@pytest.mark.parametrize('split', [False, True])
@pytest.mark.parametrize('layout', ['shared', 'separate'])
def test_process_corner_discovery_keeps_original_sources_and_groups(tmp_path, monkeypatch, route, split, layout):
    from types import SimpleNamespace
    import glob
    import shlex
    runner = _p3()
    installed = tmp_path / 'installed/libs.ref/scl/lib'
    installed.mkdir(parents=True)
    primary = []
    groups = ('logic', 'ties') if split else ('logic',)
    for group in groups:
        directory = installed / group if layout == 'separate' else installed
        directory.mkdir(exist_ok=True)
        for label in ('SS', 'TT', 'FF'):
            path = directory / f'{group}_{label}.lib'
            path.write_text(f'library (neutral) {{\n cell ({group}_{label}) {{ area : 1; }}\n }}\n')
            if label == 'TT':
                primary.append(str(path))
    if route == 'staged':
        staged = tmp_path / 'input/pdk/liberty'
        staged.mkdir(parents=True)
        for path in installed.rglob('*.lib'):
            shutil.copyfile(path, staged / path.name)
    def transport(container, command, **kwargs):
        if command.startswith('ls '):
            return 0, '\n'.join(sorted(glob.glob(shlex.split(command)[1]))), ''
        if command.startswith('cat '):
            return 1, '', 'neutral fixture has no reference config'
        raise AssertionError(command)
    monkeypatch.setattr(runner, '_docker_exec', transport)
    pdk = SimpleNamespace(liberty=primary if split else primary[0])
    corners = runner._resolve_signoff_corner_libs(tmp_path, pdk, 'fixture' if route == 'container' else '')
    assert set(corners) == {'SS', 'TT', 'FF'}
    for label, model in corners.items():
        text = Path(model).read_text()
        assert runner._classify_corner_from_name(Path(model).name) == label
        assert all(f'cell ({group}_{label})' in text for group in groups)
        assert all(f'cell ({group}_{other})' not in text
                   for group in groups for other in ('SS', 'TT', 'FF') if other != label)
        if not split:
            assert Path(model).name == f'logic_{label}.lib'


def test_split_corner_roster_refuses_partial_process_group(tmp_path):
    from types import SimpleNamespace
    paths = []
    for group in ('logic', 'ties'):
        path = tmp_path / f'{group}_TT.lib'
        path.write_text(f'library (n) {{ cell ({group}) {{}} }}\n')
        paths.append(str(path))
    (tmp_path / 'logic_SS.lib').write_text('library (n) { cell (slow_logic) {} }\n')
    with pytest.raises(ValueError, match='PDK_CORNER_GROUP_INCOMPLETE: SS'):
        _p3()._resolve_signoff_corner_libs(tmp_path, SimpleNamespace(liberty=paths), '')


def test_split_ties_preserve_real_checked_in_cell_vocabulary(tmp_path):
    from _hostpaths import require_repo
    fixture = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                           'tests', 'fixtures', 'real_benchmark', 'pdk_liberty_tie_cell_block.lib')
    extra = tmp_path / 'empty.lib'
    extra.write_text('library (empty) {}\n')
    scalar = _p3()._v1_6_596_discover_tie_cells(str(fixture), '')
    split = _p3()._v1_6_596_discover_tie_cells([str(fixture), str(extra)], '')
    assert scalar['hi_cell'] or scalar['lo_cell']
    assert split == scalar


def test_split_corners_keep_reference_operating_condition_preference(tmp_path, monkeypatch):
    from types import SimpleNamespace
    primary = []
    for group in ('logic', 'ties'):
        for corner in ('tt_025C_1v80', 'ss_100C_1v40', 'ss_100C_1v60', 'ff_n40C_1v95'):
            path = tmp_path / f'{group}_{corner}.lib'
            path.write_text(f'library (neutral) {{\n cell ({group}_{corner}) {{}}\n}}\n')
            if corner.startswith('tt_'):
                primary.append(str(path))
    runner = _p3()
    monkeypatch.setattr(runner, '_pdk_reference_signoff_corner_stems',
                        lambda *args: {'ss_100c_1v60', 'tt_025c_1v80', 'ff_n40c_1v95'})
    corners = runner._resolve_signoff_corner_libs(tmp_path, SimpleNamespace(liberty=primary), '')
    text = Path(corners['SS']).read_text()
    assert all(f'cell ({group}_ss_100C_1v60)' in text for group in ('logic', 'ties'))
    assert '1v40' not in text


def test_split_staged_corners_refuse_ambiguous_group(tmp_path):
    from types import SimpleNamespace
    staged = tmp_path / 'input/pdk/liberty'
    staged.mkdir(parents=True)
    paths = []
    for group in ('logic', 'ties'):
        path = staged / f'{group}_tt_025C_1v80.lib'
        path.write_text('library (neutral) {}\n')
        paths.append(str(path))
    for voltage in ('1v40', '1v60'):
        (staged / f'logic_ss_100C_{voltage}.lib').write_text('library (neutral) {}\n')
    with pytest.raises(ValueError, match='PDK_CORNER_GROUP_AMBIGUOUS: SS'):
        _p3()._resolve_signoff_corner_libs(tmp_path, SimpleNamespace(liberty=paths), '')
