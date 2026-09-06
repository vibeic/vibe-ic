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

FIX: try the local filesystem first, then fall through to the container.
Host-side behaviour is unchanged by construction — `/foss/pdks/...` does not
exist on a host filesystem, so the local branch finds nothing and the docker
branch runs exactly as before.

§4.05 NO-LEAK — a resolution can never be laxer than the container branch:
  * an absent root still resolves to None, so the caller still REFUSES;
  * a glob that matches nothing still resolves to None;
  * a candidate outside the PDK root is rejected, textually AND after
    symlink/`..` resolution.  (That last one was caught by this file's own
    no-leak arm: the first draft returned `/etc/passwd` through the literal
    branch while its docstring claimed the root was enforced.)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]

# A container name that cannot exist, so the docker branch is guaranteed to
# fail: the ONLY way a path comes back is the local branch under test.
_NO_SUCH_CONTAINER = "cza-no-such-container-000"


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


def test_glob_resolves_from_the_local_filesystem_without_docker(tmp_path):
    """THE DEFECT: the assets are right here, and no docker is needed to see
    them."""
    m = _p3()
    root = _fake_pdk(tmp_path)
    got = m._registry_glob_one(
        _NO_SUCH_CONTAINER, str(root), "libs.ref/scl/lib/*tt*.lib")
    assert got is not None, "a present asset resolved to None"
    assert got.endswith("scl__tt_025C_1v80.lib"), got


def test_literal_path_resolves_from_the_local_filesystem(tmp_path):
    """The non-glob branch too — registry entries use both forms."""
    m = _p3()
    root = _fake_pdk(tmp_path)
    got = m._registry_glob_one(
        _NO_SUCH_CONTAINER, str(root), "libs.ref/scl/lef/scl.lef")
    assert got is not None and got.endswith("scl.lef"), got


def test_absent_root_still_resolves_to_none(tmp_path):
    """NO-LEAK: the caller must still be able to REFUSE."""
    m = _p3()
    got = m._registry_glob_one(
        _NO_SUCH_CONTAINER, str(tmp_path / "not_a_pdk"),
        "libs.ref/scl/lib/*tt*.lib")
    assert got is None, got


def test_glob_matching_nothing_still_resolves_to_none(tmp_path):
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
    assert m._registry_glob_one_local(
        str(root) + "/", str(outside)) is None


def test_a_dotdot_pattern_that_starts_under_the_root_is_rejected(tmp_path):
    """NO-LEAK: the half a textual prefix test cannot make."""
    m = _p3()
    root = _fake_pdk(tmp_path)
    outside = tmp_path / "outside.lef"
    outside.write_text("x\n")
    escaped = f"{root}/../outside.lef"
    assert escaped.startswith(str(root) + "/"), "arm must be textually under root"
    assert m._registry_glob_one_local(str(root) + "/", escaped) is None


def test_host_side_order_is_unchanged_when_the_root_is_not_local(tmp_path):
    """The local branch is a no-op whenever the PDK is not on this filesystem,
    which is the ordinary host case — so the docker branch still decides."""
    m = _p3()
    assert m._registry_glob_one_local(
        "/foss/pdks/definitely_not_here/", 
        "/foss/pdks/definitely_not_here/libs.ref/x/*.lib") is None
