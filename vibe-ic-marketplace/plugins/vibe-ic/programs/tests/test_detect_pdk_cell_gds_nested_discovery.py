"""Regression: _detect_pdk must discover a commercial PDK's std-cell GDS even
when it lives in a NESTED subdir (the commercial PDK layout:
input/pdk/gds/<lib>_gds_<date>/<lib>.gds).

The bug (pre-fix): cell_gds was computed as
    next(iter(sorted(_pl.gds_dir(pdk_dir).glob("*.gds"))), None)
which (a) called the OUTPUT-dir helper `_pl.gds_dir` on the PDK dir -> the
nonexistent path input/pdk/phase3/stage4/gds, and (b) used a NON-recursive
glob. Both made cell_gds=None for every commercial staged PDK, so the DEF->GDS
streamout fell back to a LEF-ABSTRACT GDS with no std-cell metal -> sign-off
DRC ran on incomplete geometry. This test pins the corrected discovery
(gds_dir = pdk_dir/"gds" + rglob, largest = the std-cell library GDS).
"""
import importlib.util
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1] / "phase3_one_shot_runner.py"


def _load():
    spec = importlib.util.spec_from_file_location("p3_detectpdk", _PROG)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def _stage_pdk(root: Path, gds_rel: str, extra_gds=None):
    """Build a minimal staged input/pdk with liberty + tech/cell LEF + a GDS
    at `gds_rel` (relative to input/pdk/gds). Returns the project dir."""
    pdk = root / "input" / "pdk"
    (pdk / "liberty").mkdir(parents=True)
    (pdk / "liberty" / "lib_tt_25C.lib").write_text("library(x){}\n")
    lef = pdk / "lef"
    lef.mkdir(parents=True)
    (lef / "foo_tech_v1.lef").write_text("LAYER MET1\n  TYPE ROUTING ;\nEND MET1\n")
    (lef / "foo_macro_v1.lef").write_text("MACRO CELL\n  SITE unit ;\nEND CELL\n")
    gds = pdk / "gds" / gds_rel
    gds.parent.mkdir(parents=True, exist_ok=True)
    gds.write_bytes(b"\x00\x06\x00\x02\x00\x00" + b"A" * 4000)  # bigger = std-cell lib
    for name, size in (extra_gds or []):
        g = pdk / "gds" / name
        g.parent.mkdir(parents=True, exist_ok=True)
        g.write_bytes(b"\x00\x06\x00\x02\x00\x00" + b"B" * size)
    return root


def test_cell_gds_discovered_from_nested_subdir(tmp_path):
    m = _load()
    proj = _stage_pdk(tmp_path, "mylib_gds_210820/mylib_210820.gds")
    pdk = m._detect_pdk(proj)
    assert pdk is not None, "PDK should be detected from input/pdk"
    assert pdk.cell_gds is not None, "cell_gds must be discovered (was None: the bug)"
    cg = Path(str(pdk.cell_gds))
    assert cg.is_file() and cg.name == "mylib_210820.gds", cg
    # It must be the real nested library GDS, never the OUTPUT-dir mispath.
    assert "phase3/stage4/gds" not in str(cg)
    assert cg.parent.name == "mylib_gds_210820"


def test_cell_gds_picks_largest_when_multiple(tmp_path):
    m = _load()
    # a small stray GDS at top level + the big std-cell library nested deeper
    proj = _stage_pdk(tmp_path, "lib_gds/lib.gds", extra_gds=[("stray.gds", 50)])
    pdk = m._detect_pdk(proj)
    assert pdk is not None and pdk.cell_gds is not None
    assert Path(str(pdk.cell_gds)).name == "lib.gds", "must pick the LARGEST (std-cell lib), not the stray"


def test_no_gds_dir_leaves_cell_gds_none(tmp_path):
    """A PDK with LEF+liberty but no gds/ dir must still detect (cell_gds None,
    no crash) -- the streamout then legitimately uses the LEF path."""
    m = _load()
    pdk_root = tmp_path / "input" / "pdk"
    (pdk_root / "liberty").mkdir(parents=True)
    (pdk_root / "liberty" / "x_tt.lib").write_text("library(x){}\n")
    lef = pdk_root / "lef"
    lef.mkdir(parents=True)
    (lef / "t_tech.lef").write_text("LAYER MET1\n  TYPE ROUTING ;\nEND MET1\n")
    (lef / "c_macro.lef").write_text("MACRO C\nEND C\n")
    pdk = m._detect_pdk(tmp_path)
    assert pdk is not None
    assert pdk.cell_gds is None
