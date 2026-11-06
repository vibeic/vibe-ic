"""Ruling #75b: match unmodified native pad_cfg.tcl, including its asymmetry.

The prior ruling75/adc-native-counts.log measures native rc=0 for 1..11.
This module replays that evidence and compares every pad, corner and gap.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

import _pad_ring as pads
import test_pad_ring as ring
from _tool_probes import not_verified_reason


FIXTURE = Path(__file__).parent / "fixtures/pad_corner_gap_site_snap"
FEASIBLE_COUNTS = list(range(1, 12))


@pytest.mark.parametrize("count,between,start,end", [
    (4, 121_000, 123_000, 123_000),
    (7, 46_000, 46_000, 47_000),
    (5, 88_000, 88_000, 89_000),
    (8, 32_000, 32_000, 33_000),
])
def test_corner_gaps_use_the_native_low_end_truncation(count, between, start, end):
    assert pads.side_spacing(80_000 * count, count, 929_000, 1_000) == (between, start)
    assert 929_000 - 80_000 * count - between * (count - 1) - start == end


def test_six_pads_keep_native_65_um_between_and_67_68_um_ends():
    assert pads.side_spacing(480_000, 6, 940_000, 1_000) == (65_000, 67_000)


def _native_script():
    package = importlib.util.find_spec("librelane")
    if package is None or not shutil.which("openroad"):
        pytest.skip(not_verified_reason(
            "native LibreLane/OpenROAD not installed",
            "run in the pinned EDA image"))
    script = Path(package.origin).parent / "scripts/openroad/common/pad_cfg.tcl"
    assert script.is_file(), script
    return script


def _native_case(tmp_path, count, *, edge=0, die=1_300_000):
    names = {s: [f"pad_{s}_{i}" for i in range(count)] for s in pads.SIDES}
    signals = {name: name + "_signal" for side in names.values() for name in side}
    config = ring._config(
        PAD_EDGE_SPACING=edge, PAD_FILLERS=["pad_fill1"], SIGNAL_MAP=signals,
        **{pads.SIDE_VAR[s]: names[s] for s in pads.SIDES})
    root = ring._project(
        tmp_path, config=config,
        floorplan=ring._floorplan(pins=list(signals.values()),
                                 instances=list(signals), die=die),
        site_w=1.0, pad_w=80.0, corner_w=180.0)
    # The native row requires the pad height and corner height to agree.
    # This new neutral fixture has the original test's exact along-row widths,
    # sites and die, with square corners and matching 180-unit-high IO rows.
    lef = root / "pdk/proc/libs.ref/proc_io/lef/io.lef"
    lef.write_text(lef.read_text().replace("350", "180").replace(
        "END LIBRARY", "MACRO CORE_MACRO\n CLASS BLOCK ;\n SIZE 1 BY 1 ;\n"
        "END CORE_MACRO\nEND LIBRARY"))
    return root, config, lef


def _run_native(root, config, lef, script):
    tech = root / "native-tech.lef"
    tech.write_text("""VERSION 5.8 ;
UNITS
 DATABASE MICRONS 1000 ;
END UNITS
MANUFACTURINGGRID 0.001 ;
LAYER met2
 TYPE ROUTING ;
 DIRECTION HORIZONTAL ;
 PITCH 1 ;
 WIDTH 0.1 ;
END met2
END LIBRARY
""")
    # Serialize the producer's exact declaration, with no spacing override or
    # geometry edits. Native pad_cfg.tcl alone computes and places the pads.
    assignment = json.loads((root / pads.ASSIGNMENT_REL).read_text())
    assert assignment == config
    declarations = []
    for key, value in assignment.items():
        if key == "SIGNAL_MAP":
            continue
        raw = " ".join(value) if isinstance(value, list) else str(value)
        declarations.append(f"set ::env({key}) {{{raw}}}")
    config_path = root / "native-config.tcl"
    config_path.write_text("\n".join(declarations) + "\n")
    die = pads.read_def(root / pads.FLOORPLAN_DEF_REL)
    area = " ".join(f"{v / die.units:g}" for v in die.box)
    wrapper = root / "native-run.tcl"
    wrapper.write_text(f"""read_lef {{{tech}}}
read_lef {{{lef}}}
read_def {{{root / pads.FLOORPLAN_DEF_REL}}}
set ::env(SCRIPTS_DIR) {{{script.parents[2]}}}
set ::env(PDN_CONNECT_MACROS_TO_GRID) 0
set ::env(DIE_AREA) {{{area}}}
source {{{config_path}}}
source {{{script}}}
write_def {{{root / 'native.def'}}}
""")
    before = hashlib.sha256(script.read_bytes()).hexdigest()
    result = subprocess.run(["openroad", "-no_init", "-exit", str(wrapper)],
                            capture_output=True, text=True, timeout=90)
    (root / "native.log").write_text(result.stdout + result.stderr)
    (root / "native-result.json").write_text(json.dumps({
        "rc": result.returncode, "script": str(script), "sha256": before,
        "config": assignment,
    }, indent=2))
    assert hashlib.sha256(script.read_bytes()).hexdigest() == before
    return result


@pytest.mark.parametrize("edge", [0, 5.5])
@pytest.mark.parametrize("count", range(1, 13))
def test_native_accepted_counts_have_identical_producer_geometry(tmp_path, count, edge):
    root, config, lef = _native_case(tmp_path, count, edge=edge)
    result = _run_native(root, config, lef, _native_script())
    expected = 0 if count in FEASIBLE_COUNTS else 1
    assert result.returncode == expected, result.stdout + result.stderr


def test_original_four_side_population_matches_native_without_rebalance(tmp_path):
    root, config, lef = _native_case(tmp_path, 8, edge=5.5)
    counts = {"S": 4, "E": 7, "N": 5, "W": 8}
    for side, count in counts.items():
        config[pads.SIDE_VAR[side]] = config[pads.SIDE_VAR[side]][:count]
    keep = {n for side in pads.SIDES for n in config[pads.SIDE_VAR[side]]}
    config["SIGNAL_MAP"] = {n: v for n, v in config["SIGNAL_MAP"].items() if n in keep}
    (root / pads.ASSIGNMENT_REL).write_text(json.dumps(config, indent=2))
    (root / pads.FLOORPLAN_DEF_REL).write_text(ring._floorplan(
        pins=list(config["SIGNAL_MAP"].values()), instances=sorted(keep), die=1_300_000))
    before = (root / pads.ASSIGNMENT_REL).read_bytes()
    result = _run_native(root, config, lef, _native_script())
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / pads.ASSIGNMENT_REL).read_bytes() == before
