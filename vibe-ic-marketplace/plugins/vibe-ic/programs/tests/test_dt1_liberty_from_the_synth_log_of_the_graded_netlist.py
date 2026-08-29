"""The DT1 Liberty source must be reachable on the flow that actually runs.

MEASURED (sha256 x gf180mcuD, plugin v1.12.80, a DISCLOSED cross-PDK port):
`transition_coverage_gate.json` came back FAIL with

    gate-levelisation did not levelise: the flattened core still instantiates
    8935 cell(s) of 29 type(s) that the Liberty did not model --
    gf180mcu_fd_sc_mcu7t5v0__nand2_1 x1693 ... The Liberty read was
    /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

i.e. the exact sky130-for-a-gf180-design defect v1.12.55 exists to close, on a
tree that already carries v1.12.55.

WHY THE EXISTING FIX COULD NOT FIRE. v1.12.55 added source (3), the Liberty
recorded in `phase2/stage2/synth/stats.json`. Two different producers write
that one path:

  * `synth_area_stats_emit.build_report` — schema `synth_area_stats/1`, and it
    can carry a liberty (inside `chip_area_unit_evidence`);
  * `_yosys_stat.emit_stats_json` — the producer `design_one_shot_runner`'s
    phase-2 synth step actually calls. It writes `liberty` only when the caller
    passes one, and that call site passes `log_rel`/`netlist_rel`/`tool`/
    `frontend` and NO liberty.

So on every phase-2 run source (3) is empty and resolution falls through to the
hard-coded shared-OSS literal. The v1.12.55 regression test could not see this:
its fixture is shaped like the FIRST producer's output, and the flow writes the
SECOND producer's. `test_the_phase2_stats_artefact_really_lacks_a_liberty`
below pins the producer shape so the fixture can never drift from it again.

There is a deeper reason source (3) cannot carry the answer here. On the
measured run `stats.json` accounts for `netlist.v`, the technology-GENERIC
yosys netlist (`$_NAND_` x10424, `$_DFF_` x1579) — a netlist that by
construction loaded NO library. The netlist DT1 grades is the MAPPED one
(`gf180mcu_fd_sc_mcu7t5v0__nand2_1` x1693), and ITS synthesis log records the
library verbatim on the `dfflibmap -liberty` / `abc -liberty` / `stat -liberty`
that produced those cells. That is the source added here, and it is correct BY
CONSTRUCTION: whatever mapped the cells is what levelisation must read back.

MEASURED both ways on the real netlist (`sha256_synth.v`, 67,023 lines), using
this module's own `unresolved_cell_types`:

    Liberty resolved on main (sky130) : 30 types / 10,514 instances unresolved
    Liberty resolved with this fix    :  0 types /      0 instances

Every pre-existing source keeps its precedence — the controls pin that, and
they are green in BOTH arms.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import transition_fault_atpg_run as tdf  # noqa: E402
import _yosys_stat as ystat  # noqa: E402
import lec_run  # noqa: E402

# Measured artefacts, reproduced verbatim. EVIDENCE, never inputs to the logic.
_RIGHT_LIB = ("/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/"
              "gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib")

# The real phase-2 synth.log command line, elided in the middle. The `-liberty`
# tokens and the commands carrying them are byte-exact.
_REAL_SYNTH_LOG = (
    "-- Running command `read_verilog -sv -DSIMULATION /p/rtl/sha256.v; "
    "hierarchy -check -top sha256; proc; flatten; tribuf -logic; "
    "synth -top sha256 -flatten; "
    f"dfflibmap -liberty {_RIGHT_LIB}; "
    f"abc -liberty {_RIGHT_LIB}; "
    "setundef -zero; clean; "
    f"stat -liberty {_RIGHT_LIB}; "
    "write_verilog -noattr /p/phase2/stage2/synth/sha256_synth.v' --\n"
)


def _synth_dir(project: Path) -> Path:
    d = project / "phase2" / "stage2" / "synth"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_real_shape_stats(project: Path) -> None:
    """`stats.json` in the shape the phase-2 producer REALLY writes: the
    `_yosys_stat` payload, accounting for the technology-generic netlist, with
    no `liberty` key anywhere."""
    _synth_dir(project).joinpath("stats.json").write_text(json.dumps({
        "cells": 21081, "cells_source": "bare_cells_line",
        "top_module": "sha256", "chip_area": None,
        "cell_histogram": {"$_DFF_P_": 1579, "$_NAND_": 10424},
        "tool": "yosys", "measured_from": "phase2/stage2/synth/yosys.log",
        "netlist": "phase2/stage2/synth/netlist.v",
        "synth_frontend": "read_verilog_v2005",
    }))


# ── the pure parser ────────────────────────────────────────────────────────

def test_parser_takes_the_liberty_off_a_mapping_command():
    assert tdf.synth_log_recorded_liberty(_REAL_SYNTH_LOG) == _RIGHT_LIB


def test_parser_ignores_a_liberty_on_a_non_mapping_command():
    """A probe/report pass must not outvote the mapping that made the cells."""
    assert tdf.synth_log_recorded_liberty(
        "read_liberty -ignore_miss_func /other/probe.lib\n") == ""


def test_parser_records_nothing_when_the_log_records_nothing():
    assert tdf.synth_log_recorded_liberty("") == ""
    assert tdf.synth_log_recorded_liberty("synth -top sha256 -flatten\n") == ""


# ── the producer shape this fix exists because of ──────────────────────────

def test_the_phase2_stats_artefact_really_lacks_a_liberty():
    """PINS THE GAP. Called the way `design_one_shot_runner`'s phase-2 synth
    step calls it — no `liberty` kwarg — the payload carries no `liberty`, so
    source (3) is empty on every phase-2 run. If a later change starts passing
    one, this test fails and source (3) becomes reachable; that is a correct
    reason to revisit the ordering, not a reason to loosen this."""
    payload = ystat.build_stats_payload(
        "\n=== sha256 ===\n\n    21081 cells\n     1579   $_DFF_P_\n",
        log_rel="phase2/stage2/synth/yosys.log",
        netlist_rel="phase2/stage2/synth/netlist.v",
        tool="yosys", frontend="read_verilog_v2005")
    assert payload is not None
    assert "liberty" not in payload


# ── THE REGRESSION ─────────────────────────────────────────────────────────

def test_the_synth_log_closes_what_stats_json_cannot(tmp_path):
    """The measured run, reproduced: real-shape stats.json (no liberty), no
    project PDK glob, no pvt_matrix.json. Resolution must reach the library the
    mapping actually loaded — never the hard-coded literal."""
    _write_real_shape_stats(tmp_path)
    _synth_dir(tmp_path).joinpath("synth.log").write_text(_REAL_SYNTH_LOG)
    assert not (tmp_path / "phase2/stage2/constraints/pvt_matrix.json").exists()
    got = tdf._resolve_design_liberty(tmp_path, None)
    assert got == _RIGHT_LIB
    assert got != lec_run.DEFAULT_LIBERTY


# ── CONTROLS: green in BOTH arms; the fix must not change any of them ──────

def test_control_shipped_project_liberty_still_wins(tmp_path):
    _write_real_shape_stats(tmp_path)
    _synth_dir(tmp_path).joinpath("synth.log").write_text(_REAL_SYNTH_LOG)
    lib = tmp_path / "input" / "pdk" / "liberty"
    lib.mkdir(parents=True)
    (lib / "shipped_typ.lib").write_text("/* shipped */")
    assert tdf._resolve_design_liberty(tmp_path, None) == \
        "input/pdk/liberty/shipped_typ.lib"


def test_control_stats_recorded_liberty_still_wins(tmp_path):
    """Source (3) keeps its precedence ahead of the new source (3b)."""
    _synth_dir(tmp_path).joinpath("stats.json").write_text(json.dumps(
        {"schema": "synth_area_stats/1",
         "chip_area_unit_evidence": {"established": True,
                                     "liberty": "/ctrl/from_stats_tt.lib"}}))
    _synth_dir(tmp_path).joinpath("synth.log").write_text(_REAL_SYNTH_LOG)
    assert tdf._resolve_design_liberty(tmp_path, None) == "/ctrl/from_stats_tt.lib"


def test_control_explicit_flag_still_wins(tmp_path):
    _write_real_shape_stats(tmp_path)
    _synth_dir(tmp_path).joinpath("synth.log").write_text(_REAL_SYNTH_LOG)
    assert tdf._resolve_design_liberty(tmp_path, "/ctrl/explicit_typ.lib") == \
        "/ctrl/explicit_typ.lib"


def test_control_no_evidence_at_all_still_reaches_the_shared_default(tmp_path):
    """THE LOAD-BEARING CONTROL. A tree that records no library anywhere must
    resolve EXACTLY as it did before. Without this, the fix is satisfied by
    code that invents a library out of an empty project."""
    assert tdf._resolve_design_liberty(tmp_path, None) == lec_run.DEFAULT_LIBERTY
