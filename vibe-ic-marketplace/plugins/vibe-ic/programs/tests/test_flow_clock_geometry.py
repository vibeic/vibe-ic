import gzip
from pathlib import Path

import pytest

from flow_clock_geometry import clock_settings


def buffer(name, cap, *, function="I", extra=""):
    return f'''cell ({name}) {{
        {extra}
        pin (I) {{ direction : input; capacitance : {cap}; }}
        pin (Z) {{ direction : output; function : "{function}"; }}
    }}'''


@pytest.fixture
def native(tmp_path):
    slow = tmp_path / "slow.lib"
    fast = tmp_path / "fast.lib.gz"
    slow.write_text('library (slow) { capacitive_load_unit (1,pf);'
                    + buffer("tree_root", .01) + buffer("repair_driver", .04)
                    + buffer("unavailable_driver", .19)
                    + buffer("disabled_driver", .19, extra="dont_use : true;")
                    + buffer("inverter", .19, function="!I") + "}")
    with gzip.open(fast, "wt") as stream:
        stream.write('library (fast) { capacitive_load_unit (1,ff);'
                     + buffer("tree_root", 10) + buffer("repair_driver", 20) + "}")
    lef = tmp_path / "technology.lef"
    lef.write_text("MANUFACTURINGGRID 0.005 ;")
    excluded = tmp_path / "excluded.txt"
    excluded.write_text("# native unavailable cells\nunavailable_driver\n")
    return {"CTS_CLK_MAX_WIRE_LENGTH": 0, "MAX_CAPACITANCE_CONSTRAINT": .2,
            "STA_CORNERS": ["max_fast", "max_slow"],
            "CLOCK_WIRE_RC_LAYERS": ["lower", "upper"],
            "LAYERS_RC": {"*fast": {"lower": {"cap": .001}, "upper": {"cap": .0015}},
                          "*slow": {"lower": {"cap": .0018}, "upper": {"cap": .002},
                                    "signal_only": {"cap": 1}}},
            "LIB": {"*fast": [str(fast)], "*slow": [str(slow)], "unused": ["absent.lib"]},
            "TECH_LEFS": {"*": str(lef)}, "PNR_EXCLUDED_CELL_FILE": str(excluded)}


def test_clock_wire_budget_uses_repair_buffers_and_all_matching_corners(native):
    assert clock_settings(native) == {"CTS_CLK_MAX_WIRE_LENGTH": 80}


def test_clock_wire_budget_rounds_down_to_native_grid(native):
    native["MAX_CAPACITANCE_CONSTRAINT"] = .200007
    assert clock_settings(native) == {"CTS_CLK_MAX_WIRE_LENGTH": 80}


def test_clock_wire_budget_respects_extra_native_cell_exclusions(native):
    native["EXTRA_EXCLUDED_CELLS"] = ["repair_*"]
    assert clock_settings(native) == {"CTS_CLK_MAX_WIRE_LENGTH": 95}


def test_clock_wire_budget_accepts_supplemental_liberty_without_buffers(native, tmp_path):
    path = tmp_path / "other.lib"
    path.write_text('library (other) { capacitive_load_unit (1,pf);'
                    + buffer("inverter", .19, function="!I") + "}")
    native["LIB"]["*slow"].append(str(path))
    assert clock_settings(native) == {"CTS_CLK_MAX_WIRE_LENGTH": 80}


@pytest.mark.parametrize("attribute", ["is_level_shifter", "is_pad"])
def test_clock_wire_budget_excludes_native_nonbuffer_identity_cells(native, attribute):
    path = Path(native["LIB"]["*slow"][0])
    text = buffer("identity_interface", .21, extra=f"{attribute} : true;")
    path.write_text(path.read_text().rsplit("}", 1)[0] + text + "}")
    assert clock_settings(native) == {"CTS_CLK_MAX_WIRE_LENGTH": 80}


def test_clock_wire_budget_excludes_identity_cells_with_extra_inout(native):
    path = Path(native["LIB"]["*slow"][0])
    text = buffer("identity_interface", .21,
                  extra="pin (external) { direction : inout; }")
    path.write_text(path.read_text().rsplit("}", 1)[0] + text + "}")
    assert clock_settings(native) == {"CTS_CLK_MAX_WIRE_LENGTH": 80}


@pytest.mark.parametrize("comment", ["block", "line"])
def test_clock_wire_budget_ignores_commented_buffers(native, comment):
    path = Path(native["LIB"]["*slow"][0])
    text = buffer("documented_buffer", .21)
    text = f"/* {text} */" if comment == "block" else "\n".join(
        "// " + line for line in text.splitlines())
    path.write_text(path.read_text().rsplit("}", 1)[0] + text + "\n}")
    assert clock_settings(native) == {"CTS_CLK_MAX_WIRE_LENGTH": 80}


@pytest.mark.parametrize("description", ["literal // text", r'literal \" // text',
                                         "literal /* text */ // text"])
def test_clock_wire_budget_preserves_comment_markers_in_quoted_attributes(native, description):
    path = Path(native["LIB"]["*slow"][0])
    path.write_text(path.read_text().replace(
        "direction : input; capacitance : 0.04;",
        f'comment : "{description}"; direction : input; capacitance : 0.04;'))
    assert clock_settings(native) == {"CTS_CLK_MAX_WIRE_LENGTH": 80}


@pytest.mark.parametrize("override", [{"CTS_CLK_MAX_WIRE_LENGTH": 12},
                                      {"CTS_CLK_MAX_WIRE_LENGTH": -1},
                                      {"PNR_SDC_FILE": "operator.sdc"},
                                      {"SIGNOFF_SDC_FILE": "operator.sdc"}])
def test_clock_wire_budget_preserves_explicit_settings(native, override):
    native.update(override)
    assert clock_settings(native) == {}


@pytest.mark.parametrize("missing", ["MAX_CAPACITANCE_CONSTRAINT", "STA_CORNERS",
                                     "CLOCK_WIRE_RC_LAYERS", "LAYERS_RC", "LIB", "TECH_LEFS"])
def test_missing_native_clock_budget_data_keeps_native_default(native, missing):
    native.pop(missing)
    assert clock_settings(native) == {}


def test_clock_wire_budget_never_invents_room_for_a_buffer(native):
    native["MAX_CAPACITANCE_CONSTRAINT"] = .03
    assert clock_settings(native) == {}


def test_clock_wire_budget_requires_known_native_capacitance_units(native):
    path = Path(native["LIB"]["*slow"][0])
    path.write_text(path.read_text().replace("(1,pf)", "(1,unknown)"))
    assert clock_settings(native) == {}
