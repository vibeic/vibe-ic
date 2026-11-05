#!/usr/bin/env python3
"""Issue #3384: a discovered IO library list is not a selected timing scene."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import io_pad_chip_top_gen as producer  # noqa: E402


def _liberty(path: Path, *, library: str, process: float = 1.0,
             voltage: float = 1.0, temperature: float = 25.0,
             cells: tuple[str, ...] = ("pad",), cap_unit: str = "pf",
             rails: tuple[tuple[str, float], ...] = (("VDD", 1.0),
                                                     ("VSS", 0.0))) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''library ({library}) {{
  time_unit : "1ns";
  capacitive_load_unit (1, {cap_unit});
  default_operating_conditions : active;
  operating_conditions (active) {{
    process : {process}; voltage : {voltage}; temperature : {temperature};
    {" ".join(f'power_rail ({name}, {value});' for name, value in rails)}
  }}
  {" ".join(f'voltage_map ({name}, {value});' for name, value in rails)}
'''
        + "".join(f"  cell ({cell}) {{ }}\n" for cell in cells)
        + "}\n")
    return path




def _scene_fixture(tmp_path: Path) -> tuple[dict, Path, list[Path], Path]:
    root = tmp_path / "pdk-root"
    tree = root / "testpdk"
    lib_dir = tree / "libs.ref/test_io/lib"
    core = _liberty(tmp_path / "active_core_slow.lib", library="core",
                    voltage=0.9, temperature=125,
                    cells=("stdcell",), rails=(("CORE", 0.9), ("VSS", 0)))
    pad = _liberty(lib_dir / "model_alpha.lib", library="pad_model",
                   voltage=0.9, temperature=125,
                   cells=("pad", "supply"),
                   rails=(("CORE", 0.9), ("IO", 1.8), ("VSS", 0)))
    connector = _liberty(lib_dir / "model_beta.lib",
                         library="connector_model", voltage=0.9,
                         temperature=125, cells=("connector",),
                         rails=(("CORE", 0.9), ("IO", 1.8), ("VSS", 0)))
    config = tree / "libs.tech/librelane/test_io/config.tcl"
    config.parent.mkdir(parents=True)
    config.write_text(
        "set ::env(PAD_LIBS) [dict create]\n"
        'dict set ::env(PAD_LIBS) "*_core_slow" "\\\n'
        f"  {pad} \\\n  {connector} \\\n"
        '"\n')
    receipt = producer.bind_io_timing_scenes(
        str(root), "testpdk", {"SS": str(core)},
        ["pad", "supply", "connector"], [pad, connector])
    return receipt, core, [pad, connector], config






















def test_producer_refuses_missing_reachable_master(tmp_path: Path) -> None:
    receipt, core, models, _config = _scene_fixture(tmp_path)
    assert receipt["required_masters"]
    with pytest.raises(producer.Refusal, match="population"):
        producer.bind_io_timing_scenes(
            str(tmp_path / "pdk-root"), "testpdk", {"SS": str(core)},
            ["pad", "master_absent_from_every_model"], models)


def test_producer_refuses_wrong_content_pvt_even_when_pattern_matches(
        tmp_path: Path) -> None:
    _receipt, core, models, _config = _scene_fixture(tmp_path)
    models[0].write_text(models[0].read_text().replace(
        "temperature : 125", "temperature : 25"))
    with pytest.raises(producer.Refusal, match="incompatible PVT"):
        producer.bind_io_timing_scenes(
            str(tmp_path / "pdk-root"), "testpdk", {"SS": str(core)},
            ["pad", "connector"], models)


def test_producer_refuses_unusable_model_units(tmp_path: Path) -> None:
    _receipt, core, models, _config = _scene_fixture(tmp_path)
    models[0].write_text(models[0].read_text().replace(
        "capacitive_load_unit (1, pf);", ""))
    with pytest.raises(producer.Refusal, match="capacitive_load_unit"):
        producer.bind_io_timing_scenes(
            str(tmp_path / "pdk-root"), "testpdk", {"SS": str(core)},
            ["pad", "connector"], models)


def test_producer_refuses_two_source_declared_compatible_rosters(
        tmp_path: Path) -> None:
    _receipt, core, models, _config = _scene_fixture(tmp_path)
    duplicate = _liberty(
        tmp_path / "pdk-root/testpdk/libs.ref/other_io/lib/model_gamma.lib",
        library="other_pad_model", voltage=0.9, temperature=125,
        cells=("pad", "supply", "connector"),
        rails=(("CORE", 0.9), ("IO", 1.8), ("VSS", 0)))
    config = (tmp_path /
              "pdk-root/testpdk/libs.tech/librelane/other_io/config.tcl")
    config.parent.mkdir(parents=True)
    config.write_text(
        "set ::env(PAD_LIBS) [dict create]\n"
        f'dict set ::env(PAD_LIBS) "*_core_slow" "{duplicate}"\n')
    with pytest.raises(producer.Refusal, match="2 compatible"):
        producer.bind_io_timing_scenes(
            str(tmp_path / "pdk-root"), "testpdk", {"SS": str(core)},
            ["pad", "supply", "connector"], [*models, duplicate])
