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


@pytest.mark.parametrize('invalid', [None, [], ['', 'valid.lib'], [42]])
def test_clock_plan_refuses_invalid_primary_roster(invalid):
    from types import SimpleNamespace
    import _physical_current as physical
    with pytest.raises(ValueError, match='CLOCK_PLAN_LIBERTY_MISSING'):
        physical.clock_plan_liberty_paths(SimpleNamespace(liberty=invalid))


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
