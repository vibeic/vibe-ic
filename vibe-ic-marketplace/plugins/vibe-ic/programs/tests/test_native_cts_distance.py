from decimal import Decimal
import shutil
import subprocess

import pytest


@pytest.fixture
def geometry(tmp_path):
    pytest.importorskip("odb")
    pytest.importorskip("librelane")
    from librelane.config import Config

    tech = tmp_path / "technology.lef"
    tech.write_text("""VERSION 5.8 ;
UNITS DATABASE MICRONS 2000 ; END UNITS
MANUFACTURINGGRID 0.005 ;
LAYER metal TYPE ROUTING ; DIRECTION HORIZONTAL ; PITCH 0.2 ;
WIDTH 0.1 ; SPACING 0.1 ; END metal
END LIBRARY
""")
    cells = tmp_path / "cells.lef"
    cells.write_text("""VERSION 5.8 ;
MACRO clock_small CLASS CORE ; SIZE 1 BY 2 ; END clock_small
MACRO clock_large CLASS CORE ; SIZE 1 BY 4 ; END clock_large
MACRO unrelated CLASS CORE ; SIZE 1 BY 0.5 ; END unrelated
END LIBRARY
""")
    return Config({"DEFAULT_CORNER": "nominal", "TECH_LEFS": {"nom*": str(tech)},
                   "CELL_LEFS": [str(cells)], "CTS_CLK_BUFFERS": ["clock_*"],
                   "MAX_FANOUT_CONSTRAINT": Decimal(4),
                   "CTS_DISTANCE_BETWEEN_BUFFERS": Decimal(0)})


@pytest.mark.parametrize("distance,expected", [(None, 10), (0, 10), (2, 2), (100, 10), (-1, -1)])
def test_native_cts_distance_bounds_every_candidate_characterization_unit(geometry, distance, expected):
    from flow_config import native_defaults

    config = geometry.copy(CTS_DISTANCE_BETWEEN_BUFFERS=distance)
    result = native_defaults(config)
    assert result["CTS_DISTANCE_BETWEEN_BUFFERS"] == expected
    assert native_defaults(result)["CTS_DISTANCE_BETWEEN_BUFFERS"] == expected
    assert config["CTS_DISTANCE_BETWEEN_BUFFERS"] == distance


@pytest.mark.parametrize("fanout", [None, 0, -1, Decimal("NaN"), Decimal("Infinity")])
def test_native_cts_distance_leaves_unbounded_or_invalid_fanout_to_native(geometry, fanout):
    from flow_config import native_defaults

    result = native_defaults(geometry.copy(MAX_FANOUT_CONSTRAINT=fanout))
    assert result["CTS_DISTANCE_BETWEEN_BUFFERS"] == 0


@pytest.mark.parametrize("missing", ["TECH_LEFS", "CELL_LEFS", "CTS_CLK_BUFFERS"])
def test_native_cts_distance_keeps_auto_when_geometry_is_unavailable(geometry, missing):
    from flow_config import native_defaults

    result = native_defaults(geometry.copy(**{missing: None}))
    assert result["CTS_DISTANCE_BETWEEN_BUFFERS"] == 0


def test_native_cts_distance_requires_every_candidate_selector_to_resolve(geometry):
    from flow_config import native_defaults

    result = native_defaults(geometry.copy(CTS_CLK_BUFFERS=["clock_*", "missing"]))
    assert result["CTS_DISTANCE_BETWEEN_BUFFERS"] == 0


def test_native_cts_distance_uses_only_selected_master_heights(geometry):
    from flow_config import native_defaults

    result = native_defaults(geometry.copy(CTS_CLK_BUFFERS=["clock_large"]))
    assert result["CTS_DISTANCE_BETWEEN_BUFFERS"] == 20


@pytest.mark.parametrize("count,layout", [(64, "horizontal"), (64, "vertical"), (64, "grid"), (2, "grid")])
def test_native_cts_reports_every_clock_output_within_fanout(tmp_path, count, layout):
    tool = shutil.which("openroad")
    if not tool:
        pytest.skip("native OpenROAD required")
    pytest.importorskip("librelane")
    from librelane.config import Config
    from flow_config import native_defaults
    from _cts_fanout_fixture import write_clock_fixture

    write_clock_fixture(tmp_path, count, layout)
    config = native_defaults(Config({
        "DEFAULT_CORNER": "nominal", "TECH_LEFS": {"nom*": str(tmp_path / "technology.lef")},
        "CELL_LEFS": [str(tmp_path / "cells.lef")], "CTS_CLK_BUFFERS": ["allowed"],
        "MAX_FANOUT_CONSTRAINT": Decimal(4), "CTS_DISTANCE_BETWEEN_BUFFERS": Decimal(0)}))
    distance = config["CTS_DISTANCE_BETWEEN_BUFFERS"]
    option = f"-distance_between_buffers {distance}" if distance else ""
    script = f"""set_thread_count 2
read_lef technology.lef
read_lef cells.lef
read_liberty cells.lib
read_def input.def
create_clock -period 24 [get_ports clk]
set_max_fanout 4 [current_design]
set_max_capacitance 0.2 [current_design]
set_max_transition 3 [current_design]
set_dont_use excluded
set_wire_rc -clock -layer M2
set_wire_rc -signal -layer M1
configure_cts_characterization -max_cap 2e-13 -max_slew 3e-9
clock_tree_synthesis -root_buf allowed -buf_list allowed -sink_clustering_enable {option}
set_propagated_clock [all_clocks]
estimate_parasitics -placement
report_check_types -max_fanout -max_count 100000 -no_line_splits > fanout.rpt
"""
    (tmp_path / "clock.tcl").write_text(script)
    run = subprocess.run([tool, "-exit", "-no_splash", "clock.tcl"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=60)
    (tmp_path / "native.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    report = (tmp_path / "fanout.rpt").read_text()
    assert "clkbuf_0_clk/Z" in report, report
    assert "VIOLATED" not in report, report
