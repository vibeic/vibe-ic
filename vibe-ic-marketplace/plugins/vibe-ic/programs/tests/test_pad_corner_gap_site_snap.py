"""Ruling #75: the unmodified native symmetric placer owns feasibility."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

import _pad_ring as pads
import test_pad_ring as ring
from not_verified_tier import not_verified_reason


FIXTURE = Path(__file__).parent / "fixtures/pad_corner_gap_site_snap"
FEASIBLE_COUNTS = [1, 2, 3, 4, 5, 7, 9, 10, 11]


@pytest.mark.parametrize("count", [5, 7, 8])
def test_half_site_corner_remainders_keep_the_native_refusal(count):
    assert pads.side_spacing(count * 80_000, count, 929_000, 1_000) is None


def test_six_pad_refusal_cannot_be_fixed_by_postprocessing_the_gaps():
    assert pads.side_spacing(480_000, 6, 940_000, 1_000) is None
    # 66/65/65 would close geometrically, but the native input has no knob
    # selecting 66: it recomputes floor((460 / 7) / 1) * 1 = 65 instead.
    assert (460_000 // 7 // 1_000) * 1_000 == 65_000
    assert (460_000 - 5 * 65_000) // 2 == 67_500


def test_a_remainder_off_the_site_grid_has_no_placement():
    assert pads.side_spacing(560_000, 7, 929_001, 1_000) is None


def test_existing_centred_integer_def_bytes_are_unchanged(tmp_path):
    provenance = json.loads((FIXTURE / "PROVENANCE.json").read_text())
    expected = (FIXTURE / "centered.def").read_bytes()
    assert hashlib.sha256(expected).hexdigest() == provenance["centered_def_sha256"]
    root = ring._project(tmp_path)
    assert ring._gen(root) == 0
    assert ring._ring_def(root).read_bytes() == expected
    assert ring._chk(root) == 0



def test_original_four_side_population_keeps_declared_geometry_and_refuses(tmp_path):
    counts = {"S": 4, "E": 7, "N": 5, "W": 8}
    names = {s: [f"pad_{s}_{i}" for i in range(n)] for s, n in counts.items()}
    signals = {name: name + "_signal" for side in names.values() for name in side}
    config = ring._config(
        PAD_EDGE_SPACING=5.5, PAD_FILLERS=["pad_fill1"], SIGNAL_MAP=signals,
        **{pads.SIDE_VAR[s]: names[s] for s in pads.SIDES})
    root = ring._project(
        tmp_path, config=config,
        floorplan=ring._floorplan(pins=list(signals.values()),
                                 instances=list(signals), die=1_300_000),
        site_w=1.0, pad_w=80.0, corner_w=180.0)
    before = (root / pads.ASSIGNMENT_REL).read_bytes()
    assert ring._gen(root) == 1
    assert (root / pads.ASSIGNMENT_REL).read_bytes() == before
    assert "PAD_CORNER_SPACING_NOT_SITE_MULTIPLE" in ring._rules(root)
    assert not ring._ring_def(root).exists()

def _native_script():
    package = importlib.util.find_spec("librelane")
    if package is None or not shutil.which("openroad"):
        pytest.skip(not_verified_reason(
            "native LibreLane/OpenROAD not installed",
            "run in the pinned EDA image"))
    script = Path(package.origin).parent / "scripts/openroad/common/pad_cfg.tcl"
    assert script.is_file(), script
    return script


def _native_case(tmp_path, count):
    names = {s: [f"pad_{s}_{i}" for i in range(count)] for s in pads.SIDES}
    signals = {name: name + "_signal" for side in names.values() for name in side}
    config = ring._config(
        PAD_EDGE_SPACING=0, PAD_FILLERS=["pad_fill1"], SIGNAL_MAP=signals,
        **{pads.SIDE_VAR[s]: names[s] for s in pads.SIDES})
    root = ring._project(
        tmp_path, config=config,
        floorplan=ring._floorplan(pins=list(signals.values()),
                                 instances=list(signals), die=1_300_000),
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
    wrapper = root / "native-run.tcl"
    wrapper.write_text(f"""read_lef {{{tech}}}
read_lef {{{lef}}}
read_def {{{root / pads.FLOORPLAN_DEF_REL}}}
set ::env(SCRIPTS_DIR) {{{script.parents[2]}}}
set ::env(PDN_CONNECT_MACROS_TO_GRID) 0
set ::env(DIE_AREA) {{0 0 1300 1300}}
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


@pytest.mark.parametrize("count", range(1, 13))
def test_native_symmetric_geometry_preserves_original_feasible_counts(tmp_path, count):
    script = _native_script()
    root, config, lef = _native_case(tmp_path, count)
    result = _run_native(root, config, lef, script)
    native_rc = 0 if count < 12 else 1
    producer_rc = 0 if count in FEASIBLE_COUNTS else 1
    assert result.returncode == native_rc, result.stdout + result.stderr
    assert ring._gen(root) == producer_rc
    if native_rc == 0:
        native = pads.read_def(root / "native.def")
        xs = sorted(c.x for name, c in native.components.items()
                    if name.startswith("pad_S_"))
        gaps = [xs[0] - 180_000, 1_120_000 - xs[-1] - 80_000]
        record_path = root / "native-result.json"
        record = json.loads(record_path.read_text())
        record.update(native_corner_gaps_dbu=gaps, producer_rc=producer_rc)
        record_path.write_text(json.dumps(record, indent=2))
        if count in FEASIBLE_COUNTS:
            assert gaps[0] == gaps[1]
        else:
            # Native Tcl integer arithmetic truncates the half-site corner
            # gap. rc=0 alone must not authorize asymmetric placement (#75).
            assert gaps == ([67_000, 68_000] if count == 6 else [34_000, 35_000])
    if producer_rc == 0:
        assert (root / "native.def").is_file()
        # The producer's declared symmetric spacing equals the native DB's
        # placement, not just another implementation of the arithmetic.
        native = pads.read_def(root / "native.def")
        report = ring._report(root)
        for pad in report["pads"]:
            placed = native.components[pad["instance"]]
            assert (placed.x, placed.y) == (pad["x"], pad["y"])
    else:
        assert (root / "native.def").exists() == (native_rc == 0)
        rule = ("PAD_RING_DOES_NOT_FIT" if count == 12 else
                "PAD_CORNER_SPACING_NOT_SITE_MULTIPLE")
        assert rule in ring._rules(root)
        if count != 12:
            refusals = [f for f in ring._report(root)["findings"]
                        if f["rule"] == rule]
            assert all(f["feasible_pad_counts"] == FEASIBLE_COUNTS for f in refusals)
