"""ROUND-3 (subservient x gf180mcuD, 2026-09-02): the PDK-root derivation
must survive the via-patch legalizer re-pointing `pdk.tech_lef` into the
project.

MEASURED, two arms on one host, one netlist, one image:
  control (no legalizer)   : spef_corners/{min,nom,max}.spef present, the
                             post-route real-SPEF repair ran and SHIPPED
                             (SS setup -1.57 -> +0.22 ns), die_finishing.json
                             present.
  proof / candidate        : `tech_lef` = <project>/phase3/stage3/pnr/
                             active_via_legalized.tlef; NO spef_corners/, the
                             SS-corner sign-off STA read `subservient.spef`
                             (nominal RC) while `mcorner_ocv_stance.json`
                             still said "SETUP @ SS + max-RC"; the repair
                             recorded `precondition_unmet` ("the PDK
                             max-captable value could not be resolved"); no
                             die_finishing.json; hardmacro_gen: "no magicrc
                             under PDK_ROOT ''".
Every one of those consumers derived the PDK root as
`tech_lef.find("/libs.ref/")` and returned "" once the path moved. The PnR
TCL already carried a cell-LEF fallback for the identical hole (PR-B2b); the
Python side did not.

FALSIFICATION (two-tree): on the pre-fix tree `_pdk_root_c` does not exist
(AttributeError) and `_pdk_dir_of` returns "" for the legalized shape, so
`test_pdk_dir_of_survives_a_project_tech_lef` and
`test_max_captable_root_and_openrcx_discovery_use_the_shared_root` fail
there (MEASURED 2026-09-02 on 8f3755d9f: 6 of 8 fail, the two CONTROL tests
pass). The two `test_control_*` tests pass on BOTH trees — they pin that a
tech LEF still under the PDK derives exactly what it always did through the
pre-existing entry point, and that a PDK without the marker still yields "".

chip-AGNOSTIC: synthetic paths; no PDK name is asserted.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent


def _p3():
    spec = importlib.util.spec_from_file_location(
        "_p3_round3_root", _PROGRAMS / "phase3_one_shot_runner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p3_round3_root"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def p3():
    return _p3()




















def test_legalizer_records_the_source_it_derived_from(p3):
    """`PdkConfig` carries `tech_lef_source` (default None) so the legalizer can
    record where the derived copy came from."""
    import dataclasses
    names = {f.name for f in dataclasses.fields(p3.PdkConfig)}
    assert "tech_lef_source" in names
    f = next(f for f in dataclasses.fields(p3.PdkConfig) if f.name == "tech_lef_source")
    assert f.default is None
