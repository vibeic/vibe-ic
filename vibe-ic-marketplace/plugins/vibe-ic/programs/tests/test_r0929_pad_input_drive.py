"""R-0929-PAD-INPUT-DRIVE: a bond-pad input is never driven by the core
library's synthesis driving cell.

MEASURED (subservient, gf180mcuD, DIE route, 2026-09-29): the auto sign-off
SDC applied the pinned PDK's LibreLane SYNTH_DRIVING_CELL (core inv_1) to
`[all_inputs]` of the pad-ring top. Each input is a bond pad, so a tiny
core inverter "drove" 3.1 pF of pad: 50.8 ns on the clock port, SS setup
-55.854 ns / hold -11.180 ns (9/9 and 6/9 scenes red). One-variable replay
without that line: all 18 checks positive (+1.622 / +0.085 ns), which is an
ideal edge and so optimistic, not sign-off.

THE RULE (root ruling, RULINGS.md):
* On a DIE (pad-ring) top the off-chip drive is the design's DECLARED driver
  or input transition, else a PDK IO-tier value with its source.
* Never the core synthesis driving cell; never an ideal edge at sign-off.
* With neither, the drive is NOT_MEASURED with its reason, and a sign-off
  STA PASS measured on the resulting ideal edges becomes NOT_MEASURED; a FAIL
  stays FAIL.
* Core / HARDMACRO runs keep the synthesis driving cell.

The pinned-PDK config read (a container file read) is replaced by its values
exactly as the CR8 tests do; the SDC builder, the pad-ring predicate and the
verdict fold are the shipped code. Neutral cell/library names only.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3  # noqa: E402
import _tapeout_declaration as TD  # noqa: E402

_CORE_CELL = ("quartz_sc__inv_1/ZN", "pinned PDK default /pdk/x/config.tcl:SYNTH_DRIVING_CELL")
_PDK_VALUES = {
    "set_clock_uncertainty": ("0.25", "pinned PDK default cfg:CLOCK_UNCERTAINTY_CONSTRAINT"),
    "set_driving_cell": _CORE_CELL,
    "set_load": ("72.91", "pinned PDK default cfg:OUTPUT_CAP_LOAD"),
}
_REPORT = "reports/phase3/pad_input_drive.json"


def _die(tmp_path: Path, name: str = "die") -> Path:
    """A self-tape-out die: SELF_TAPEOUT.txt present, no HARDMACRO
    declaration, so the shipped `requests_pad_ring` answers True."""
    p = tmp_path / name
    marker = p / TD.SELF_TAPEOUT_REL
    marker.parent.mkdir(parents=True)
    marker.write_text(TD.SELF_TAPEOUT_MARKER + "\n")
    assert TD.requests_pad_ring(p) is True
    return p


def _core(tmp_path: Path) -> Path:
    p = tmp_path / "core"
    p.mkdir()
    assert TD.requests_pad_ring(p) is False
    return p


def _sdc(project: Path, monkeypatch, values=None, *, top: str = "") -> str:
    vals = dict(_PDK_VALUES if values is None else values)
    monkeypatch.setattr(p3, "_sdc_environment_values", lambda *_: (dict(vals), []))
    monkeypatch.setattr(p3, "_synth_max_fanout", lambda *_: (None, "", []))
    return p3._build_auto_silicon_sdc(
        project, top=top, pdk_name="famxD",
        liberty_path="/pdk/libs.ref/quartz_sc/lib/slow.lib")


def _commands(text: str, name: str):
    return [ln for ln in text.splitlines() if ln.startswith(name + " ")]


def _record(project: Path) -> dict:
    return json.loads((project / _REPORT).read_text())


# -- the SDC --------------------------------------------------------------

def test_die_top_never_carries_the_core_driving_cell(tmp_path, monkeypatch):
    text = _sdc(_die(tmp_path), monkeypatch)
    assert _commands(text, "set_driving_cell") == []
    assert "NOT_MEASURED: OFFCHIP_INPUT_DRIVE" in text
    assert "quartz_sc__inv_1/ZN" in text  # the refusal names what it refused
    # the other environment commands are untouched
    assert _commands(text, "set_load") == ["set_load 0.07291 [all_outputs]"]


def test_die_drive_is_recorded_not_measured_with_the_refused_cell(tmp_path, monkeypatch):
    project = _die(tmp_path)
    _sdc(project, monkeypatch)
    rec = _record(project)
    assert rec["verdict"] == "NOT_MEASURED"
    assert rec["refused_core_driving_cell"]["value"] == "quartz_sc__inv_1/ZN"
    assert "IO-tier" in rec["reason"]


def test_a_declared_input_transition_drives_the_die_inputs(tmp_path, monkeypatch):
    project = _die(tmp_path)
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L9_constraints.md").write_text("| `set_input_transition` | **1.5** |\n")
    text = _sdc(project, monkeypatch)
    assert _commands(text, "set_input_transition") == [
        "set_input_transition 1.5 [all_inputs]"]
    assert _commands(text, "set_driving_cell") == []
    rec = _record(project)
    assert rec["verdict"] == "DECLARED" and rec["value"] == "1.5"
    assert rec["source"].startswith("design doc ")


def test_a_design_declared_driver_is_kept_on_a_die(tmp_path, monkeypatch):
    project = _die(tmp_path)
    vals = dict(_PDK_VALUES,
                set_driving_cell=("quartz_sc__buf_8/Z", "design doc L9.md:3"))
    text = _sdc(project, monkeypatch, vals)
    assert _commands(text, "set_driving_cell") == [
        "set_driving_cell -lib_cell quartz_sc__buf_8 -pin Z [all_inputs]"]
    assert _record(project)["verdict"] == "DECLARED"


def test_control_a_core_run_keeps_the_synthesis_driving_cell(tmp_path, monkeypatch):
    text = _sdc(_core(tmp_path), monkeypatch)
    assert _commands(text, "set_driving_cell") == [
        "set_driving_cell -lib_cell quartz_sc__inv_1 -pin ZN [all_inputs]"]
    assert "OFFCHIP_INPUT_DRIVE" not in text


# -- the STA verdict ------------------------------------------------------

def _rows():
    mk = lambda n, s: p3.StepResult(n, s, 0.0, f"{n} {s}", [], {})
    return [mk("sta_signoff", "PASS"), mk("sta_corner", "FAIL"),
            mk("sta_record", "PASS"), mk("em_signoff", "PASS")]


def _fold(project, rows):
    # the runner folds its declared sign-off rows through this, in
    # step_declared_signoff_gates (the PPA ledger keeps the logic in _ppa)
    return {r.name: r for r in p3._ppa_timing.pad_drive_sta_verdict(p3, project, rows)}


def test_a_not_measured_drive_turns_sta_pass_into_not_measured(tmp_path, monkeypatch):
    project = _die(tmp_path)
    _sdc(project, monkeypatch)
    by = _fold(project, _rows())
    assert by["sta_signoff"].status == "NOT_MEASURED"
    assert "OFFCHIP_INPUT_DRIVE" in by["sta_signoff"].detail
    assert by["sta_record"].status == "NOT_MEASURED"
    assert by["sta_corner"].status == "FAIL"      # a violation stays a violation
    assert by["em_signoff"].status == "PASS"      # not an STA row


def test_control_a_declared_drive_leaves_the_sta_verdict_alone(tmp_path, monkeypatch):
    project = _die(tmp_path)
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L9_constraints.md").write_text("| `set_input_transition` | 1.5 |\n")
    _sdc(project, monkeypatch)
    by = _fold(project, _rows())
    assert by["sta_signoff"].status == "PASS"
    assert by["sta_record"].status == "PASS"


# -- the PDK IO tier (R-0929-IO-INPUT-TRANSITION and -2) --------------------
#
# MEASURED (gf180mcuD b344c97, all 12 gf180mcu_fd_io corner views): every
# bond-pad signal pin (`is_pad : true`, input on in_c/in_s, inout on
# bi_t/bi_24t) carries `max_transition : 1.0`, and every PAD->Y delay and
# transition table indexes input_net_transition at 0.08, 0.5, 1.0 ns. So a
# pad input edge is characterised from 0.08 (fast) to 1.0 ns (slow): late
# analysis takes the slow end, early/hold analysis the fast end, per scene
# from the IO view linked in that scene. The fixture copies that grammar
# with neutral names.

from not_verified_tier import skip_not_verified  # noqa: E402

_IO_LIB = """library ("quartz_io__%(corner)s") {
\ttime_unit : "%(unit)s";
\tdefault_max_capacitance : 999.000000;
\tdefault_max_fanout : 1.000000;
\tpower_lut_template ("power_inputs_1") {
\t\tvariable_1 : "input_transition_time";
\t\tindex_1("1, 2, 3");
\t}
\tlu_table_template ("del_1_3_6") {
\t\tvariable_1 : "input_net_transition";
\t\tindex_1("1, 2, 3");
\t\tvariable_2 : "total_output_net_capacitance";
\t\tindex_2("1, 2, 3, 4, 5, 6");
\t}
\tlu_table_template ("load_first") {
\t\tvariable_1 : "total_output_net_capacitance";
\t\tindex_1("1, 2");
\t\tvariable_2 : "input_net_transition";
\t\tindex_2("1, 2, 3");
\t}
\tcell ("quartz_io__in") {
\t\tpad_cell : true;
\t\tpin ("PU") {
\t\t\tmax_transition : 9.000000;
\t\t\tdirection : "input";
\t\t}
\t\tpin ("PAD") {
\t\t\tmax_transition : %(in_pad)s;
\t\t\tis_pad : true;
\t\t\tdirection : "input";
\t\t\tcapacitance : 3.080752;
\t\t}
\t\tpin ("Y") {
\t\t\tdirection : "output";
\t\t\tmax_capacitance : 0.500000;
\t\t\tinternal_power () {
\t\t\t\trelated_pin : "PAD";
\t\t\t\trise_power ("power_inputs_1") {
\t\t\t\t\tindex_1("0.001, 0.5, 1");
\t\t\t\t}
\t\t\t}
\t\t\ttiming () {
\t\t\t\trelated_pin : "PAD";
\t\t\t\tcell_rise ("del_1_3_6") {
\t\t\t\t\tindex_1("%(in_idx)s");
\t\t\t\t\tindex_2("0, 0.04, 0.1, 0.3, 0.4, 0.5");
\t\t\t\t}
\t\t\t\tfall_transition ("del_1_3_6") {
\t\t\t\t\tindex_1("%(in_idx)s");
\t\t\t\t}
\t\t\t}
\t\t\ttiming () {
\t\t\t\trelated_pin : "PU";
\t\t\t\tcell_rise ("del_1_3_6") {
\t\t\t\t\tindex_1("0.001, 5");
\t\t\t\t}
\t\t\t}
\t\t}
\t}
\tcell ("quartz_io__bi") {
\t\tpin ("PAD") {
\t\t\tmax_transition : %(bi_pad)s;
\t\t\tis_pad : true;
\t\t\tdirection : "inout";
\t\t}
\t\tpin ("A") {
\t\t\tmax_transition : 7.000000;
\t\t\tdirection : "input";
\t\t}
\t\tpin ("Y") {
\t\t\tdirection : "output";
\t\t\ttiming () {
\t\t\t\trelated_pin : "PAD";
\t\t\t\tcell_fall ("load_first") {
\t\t\t\t\tindex_1("0, 0.5");
\t\t\t\t\tindex_2("%(bi_idx)s");
\t\t\t\t}
\t\t\t}
\t\t}
\t}
\tcell ("quartz_io__vdd") {
\t\tpin ("DVDD") {
\t\t\tis_pad : true;
\t\t\tdirection : "inout";
\t\t}
\t}
}
"""


def _io_record(project: Path, libs, *, core_module: str = "",
               chip_top_module: str = "", verdict: str = "WROTE") -> None:
    rec = project / "reports" / "phase3" / "io_pad_chip_top.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    doc = {"verdict": verdict,
           "io_library_liberty": [str(x) for x in libs]}
    if core_module:
        doc["core_module"] = core_module
    if chip_top_module:
        doc["chip_top_module"] = chip_top_module
    rec.write_text(json.dumps(doc))


def _io_lib(tmp_path: Path, corner: str, in_pad="1.000000", bi_pad="1.000000",
            in_idx="0.08, 0.5, 1", bi_idx="0.08, 0.5, 1", unit="1ns") -> Path:
    lib = tmp_path / "pdk" / f"quartz_io__{corner}.lib"
    lib.parent.mkdir(parents=True, exist_ok=True)
    lib.write_text(_IO_LIB % dict(corner=corner, in_pad=in_pad, bi_pad=bi_pad,
                                  in_idx=in_idx, bi_idx=bi_idx, unit=unit))
    return lib


def _views_line(text: str) -> str:
    return next(ln for ln in text.splitlines() if ln.startswith("set _vibeic_pad_views "))


def test_the_io_liberty_brackets_the_die_inputs_per_view(tmp_path, monkeypatch):
    project = _die(tmp_path)
    # ss: in PAD 0.08..1.0 (bound 1.0); bi PAD 0.1..1.25 (bound 1.25)
    #  -> the view's common bracket: max 1.0 (no pin extrapolated), min 0.1
    slow = _io_lib(tmp_path, "ss", in_pad="1.0", bi_pad="1.25",
                   bi_idx="0.1, 0.6, 1.25")
    # ff: in PAD bound 0.6 inside a 0.08..1.0 table -> max 0.6, min 0.08
    fast = _io_lib(tmp_path, "ff", in_pad="0.6", bi_pad="0.9")
    _io_record(project, [fast, slow])
    text = _sdc(project, monkeypatch)
    assert _views_line(text) == ("set _vibeic_pad_views {{quartz_io__ff 0.6 0.08} "
                                 "{quartz_io__ss 1 0.1}}")
    # with several views linked (multi-corner PnR) the range all characterise
    assert "set _vibeic_pad_max 0.6" in text and "set _vibeic_pad_min 0.1" in text
    assert _commands(text, "set_input_transition") == [
        "set_input_transition -max $_vibeic_pad_max [all_inputs]",
        "set_input_transition -min $_vibeic_pad_min [all_inputs]"]
    assert _commands(text, "set_driving_cell") == []
    assert "NOT_MEASURED: OFFCHIP_INPUT_DRIVE" not in text
    rec = _record(project)
    assert rec["verdict"] == "PDK_IO_TIER"
    assert rec["refused_core_driving_cell"]["value"] == "quartz_sc__inv_1/ZN"
    views = {v["library"]: v for v in rec["bracket"]["views"]}
    assert (views["quartz_io__ss"]["max_ns"], views["quartz_io__ss"]["min_ns"]) == (1.0, 0.1)
    assert len(views["quartz_io__ff"]["sha256"]) == 64
    # the record names exactly the command lines the deck carries
    assert rec["sdc_lines"] and all(ln in text.splitlines() for ln in rec["sdc_lines"])
    # a PDK-tier drive is a modelled edge: the STA verdict is left alone
    assert _fold(project, _rows())["sta_signoff"].status == "PASS"


def test_current_core_boundary_keeps_on_chip_drive_until_chip_top_is_analysed(
        tmp_path, monkeypatch):
    """#3269: a future DIE request does not move the current core boundary.

    The current analysis top is the changed input.  Core -> chip -> core is the
    forward and reversal control; the pad producer's identity stays unchanged.
    """
    project = _die(tmp_path)
    _io_record(project, [_io_lib(tmp_path, "tt")],
               core_module="neutral_core", chip_top_module="neutral_chip")

    core = _sdc(project, monkeypatch, top="neutral_core")
    core_record = _record(project)
    assert core_record["verdict"] == "NOT_APPLICABLE"
    assert _commands(core, "set_driving_cell") == [
        "set_driving_cell -lib_cell quartz_sc__inv_1 -pin ZN [all_inputs]"]
    assert _commands(core, "set_input_transition") == []
    assert core_record["analysis_top"] == "neutral_core"
    assert core_record["boundary"]["chip_top_module"] == "neutral_chip"

    chip = _sdc(project, monkeypatch, top="neutral_chip")
    assert _commands(chip, "set_driving_cell") == []
    assert _commands(chip, "set_input_transition") == [
        "set_input_transition -max $_vibeic_pad_max [all_inputs]",
        "set_input_transition -min $_vibeic_pad_min [all_inputs]",
    ]
    chip_record = _record(project)
    assert chip_record["verdict"] == "PDK_IO_TIER"
    assert chip_record["analysis_top"] == "neutral_chip"

    restored = _sdc(project, monkeypatch, top="neutral_core")
    assert _commands(restored, "set_driving_cell") == [
        "set_driving_cell -lib_cell quartz_sc__inv_1 -pin ZN [all_inputs]"]
    assert _record(project)["verdict"] == "NOT_APPLICABLE"


def test_unknown_analysis_top_refuses_to_guess_core_or_pad_boundary(
        tmp_path, monkeypatch):
    """A stale caller identity cannot borrow either a core or pad model."""
    project = _die(tmp_path)
    _io_record(project, [_io_lib(tmp_path, "tt")],
               core_module="neutral_core", chip_top_module="neutral_chip")
    text = _sdc(project, monkeypatch, top="stale_top")
    rec = _record(project)
    assert rec["verdict"] == "NOT_MEASURED"
    assert _commands(text, "set_driving_cell") == []
    assert _commands(text, "set_input_transition") == []
    assert rec["analysis_top"] == "stale_top"
    assert "matches neither" in rec["reason"]


def _multi_axis_pad_lib(first: str, second: str, *, unit: str = "1ns",
                        output_limit: str = "1") -> str:
    return f'''library(neutral_io) {{
      time_unit : "{unit}";
      lu_table_template(t) {{ variable_1 : input_net_transition; }}
      cell(neutral_pad) {{
        pin(PAD) {{ direction : input; is_pad : true; max_transition : 20000; }}
        pin(Y0) {{ direction : output; function : "PAD";
          max_transition : {output_limit};
          timing() {{ related_pin : "PAD";
            cell_rise(t) {{ index_1("{first}"); values("0.1, 0.2"); }}
          }}
        }}
        pin(Y1) {{ direction : output; function : "PAD";
          max_transition : {output_limit};
          timing() {{ related_pin : "PAD";
            cell_rise(t) {{ index_1("{second}"); values("0.1, 0.2"); }}
          }}
        }}
      }}
    }}'''


def test_intersecting_active_pad_tables_use_only_the_common_axis():
    """#3270: all always-active receiver tables constrain one stimulus."""
    import sdc_environment as SE
    got = SE._io_pad_view(_multi_axis_pad_lib("0.02, 0.5", "0.2, 2"))
    assert {k: got.get(k) for k in ("fast_ns", "slow_ns")} == {
        "fast_ns": 0.2, "slow_ns": 0.5}


def test_same_axis_active_pad_tables_preserve_the_characterised_range():
    import sdc_environment as SE
    got = SE._io_pad_view(_multi_axis_pad_lib("0.02, 0.5", "0.02, 0.5"))
    assert {k: got.get(k) for k in ("fast_ns", "slow_ns")} == {
        "fast_ns": 0.02, "slow_ns": 0.5}


def test_disjoint_active_pad_tables_refuse_a_characterised_bracket():
    import sdc_environment as SE
    got = SE._io_pad_view(_multi_axis_pad_lib("0.02, 0.1", "0.2, 2"))
    assert "fast_ns" not in got and "slow_ns" not in got
    assert got["why"] == "the pad pins' characterised ranges do not overlap"


def test_axis_intersection_converts_units_and_ignores_receiver_output_limit():
    """The table axes, not a favourable receiver-output limit, choose the edge."""
    import sdc_environment as SE
    low = SE._io_pad_view(_multi_axis_pad_lib(
        "20, 500", "200, 2000", unit="1ps", output_limit="1"))
    high = SE._io_pad_view(_multi_axis_pad_lib(
        "20, 500", "200, 2000", unit="1ps", output_limit="999"))
    expected = {"fast_ns": 0.2, "slow_ns": 0.5}
    assert {k: low.get(k) for k in expected} == expected
    assert {k: high.get(k) for k in expected} == expected


def test_each_scene_takes_its_own_linked_io_view(tmp_path, monkeypatch):
    """Execute the emitted Tcl with `get_libs` answering like a one-scene
    OpenSTA process (LibreLane runs one per scene), then like a multi-corner
    one, then with no IO view linked."""
    tclsh = shutil.which("tclsh")
    if not tclsh:
        skip_not_verified("tclsh not on PATH, so the emitted per-scene Tcl "
                          "selection cannot be executed here",
                          "apt-get install tcl")
    project = _die(tmp_path)
    _io_record(project, [_io_lib(tmp_path, "ss", in_pad="1.0"),
                         _io_lib(tmp_path, "ff", in_pad="0.6")])
    text = _sdc(project, monkeypatch)
    block = [ln for ln in text.splitlines() if "_vibeic_pad_" in ln
             and not ln.startswith("#")]

    def run(linked):
        script = ("proc all_inputs {} { return P }\n"
                  f"proc get_libs {{q name}} {{ if {{[lsearch -exact {{{' '.join(linked)}}} $name] >= 0}} {{ return $name }} ; return {{}} }}\n"
                  "proc set_input_transition {mm v p} { puts \"$mm $v\" }\n"
                  + "\n".join(ln for ln in block if not ln.startswith("puts")) + "\n")
        out = subprocess.run([tclsh], input=script, capture_output=True,
                             text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        return out.stdout.split()

    assert run(["quartz_io__ss"]) == ["-max", "1", "-min", "0.08"]
    assert run(["quartz_io__ff"]) == ["-max", "0.6", "-min", "0.08"]
    assert run(["quartz_io__ss", "quartz_io__ff"]) == ["-max", "0.6", "-min", "0.08"]
    assert run([]) == ["-max", "0.6", "-min", "0.08"]


def test_the_io_liberty_time_unit_is_converted_to_ns(tmp_path, monkeypatch):
    project = _die(tmp_path)
    _io_record(project, [_io_lib(tmp_path, "tt", in_pad="1000", bi_pad="1000",
                                 in_idx="80, 500, 1000", bi_idx="80, 500, 1000",
                                 unit="1ps")])
    text = _sdc(project, monkeypatch)
    assert _views_line(text) == "set _vibeic_pad_views {{quartz_io__tt 1 0.08}}"


def test_an_unread_io_view_is_not_measured_not_a_partial_bracket(tmp_path, monkeypatch):
    project = _die(tmp_path)
    _io_record(project, [_io_lib(tmp_path, "ff"), tmp_path / "pdk" / "gone.lib"])
    text = _sdc(project, monkeypatch)
    assert _commands(text, "set_input_transition") == []
    rec = _record(project)
    assert rec["verdict"] == "NOT_MEASURED"
    assert "NOT_READ" in rec["reason"] and "gone.lib" in rec["reason"]
    assert _fold(project, _rows())["sta_signoff"].status == "NOT_MEASURED"


def test_an_io_view_without_a_pad_bound_is_not_measured(tmp_path, monkeypatch):
    project = _die(tmp_path)
    lib = tmp_path / "pdk" / "bare.lib"
    lib.parent.mkdir(parents=True)
    lib.write_text('library ("bare") {\n cell ("c") {\n  pin ("PAD") {\n'
                   '   is_pad : true;\n   direction : "input";\n  }\n }\n}\n')
    _io_record(project, [lib])
    _sdc(project, monkeypatch)
    rec = _record(project)
    assert rec["verdict"] == "NOT_MEASURED"
    assert "no bond-pad input pin with a documented bound" in rec["reason"]


def test_a_pad_without_a_characterised_fast_edge_is_not_measured(tmp_path, monkeypatch):
    """A max_transition alone gives no fastest edge: the hold end of the
    bracket is unknown, and inventing one (or reusing the slow end) is the
    optimism the bracket exists to remove."""
    project = _die(tmp_path)
    lib = tmp_path / "pdk" / "noarc.lib"
    lib.parent.mkdir(parents=True)
    lib.write_text('library ("noarc") {\n cell ("c") {\n  pin ("PAD") {\n'
                   '   max_transition : 1.0;\n   is_pad : true;\n'
                   '   direction : "input";\n  }\n }\n}\n')
    _io_record(project, [lib])
    _sdc(project, monkeypatch)
    rec = _record(project)
    assert rec["verdict"] == "NOT_MEASURED"
    assert "no fastest edge" in rec["reason"]


def test_a_declared_input_transition_outranks_the_io_tier(tmp_path, monkeypatch):
    project = _die(tmp_path)
    _io_record(project, [_io_lib(tmp_path, "ss")])
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L9_constraints.md").write_text("| `set_input_transition` | 0.4 |\n")
    text = _sdc(project, monkeypatch)
    assert _commands(text, "set_input_transition") == [
        "set_input_transition 0.4 [all_inputs]"]
    assert _record(project)["verdict"] == "DECLARED"


def test_control_a_core_run_ignores_the_io_tier(tmp_path, monkeypatch):
    project = _core(tmp_path)
    _io_record(project, [_io_lib(tmp_path, "ss")])
    text = _sdc(project, monkeypatch)
    assert _commands(text, "set_input_transition") == []
    assert _commands(text, "set_driving_cell") == [
        "set_driving_cell -lib_cell quartz_sc__inv_1 -pin ZN [all_inputs]"]


# -- the design-staged SDC branch (review_wave58 MINOR) ---------------------

def test_a_staged_sdc_without_a_drive_gets_the_ladder_and_a_fresh_record(tmp_path):
    import sdc_environment as SE
    project = _die(tmp_path)
    _io_record(project, [_io_lib(tmp_path, "ss")])
    # a stale record from an earlier auto-SDC run must not survive
    (project / _REPORT).write_text(json.dumps({"verdict": "PDK_IO_TIER"}))
    staged = "create_clock -name c -period 10 [get_ports clk]\n"
    text, rec = SE.staged_sdc_pad_input_drive(project, staged, "input/constraints/t.sdc")
    assert rec["verdict"] == "PDK_IO_TIER"
    assert text.startswith(staged)
    assert all(ln in text.splitlines() for ln in rec["sdc_lines"])
    # a staged deck with no drive and no IO tier -> NOT_MEASURED, not ideal
    bare = _die(tmp_path, "bare")
    text2, rec2 = SE.staged_sdc_pad_input_drive(bare, staged, "input/constraints/t.sdc")
    assert rec2["verdict"] == "NOT_MEASURED"
    assert "NOT_MEASURED: OFFCHIP_INPUT_DRIVE" in text2


def test_a_staged_sdc_that_sets_its_own_drive_is_declared(tmp_path):
    import sdc_environment as SE
    project = _die(tmp_path)
    staged = ("create_clock -name c -period 10 [get_ports clk]\n"
              "set_input_transition 0.3 [all_inputs]\n")
    text, rec = SE.staged_sdc_pad_input_drive(project, staged, "input/constraints/t.sdc")
    assert text == staged
    assert rec["verdict"] == "DECLARED"
    assert rec["sdc_lines"] == ["set_input_transition 0.3 [all_inputs]"]


def _core_wrapper_project(tmp_path, *, related_pin="PAD"):
    project = _die(tmp_path)
    liberty = tmp_path / "pdk" / "neutral_io.lib"
    liberty.parent.mkdir(parents=True)
    liberty.write_text(f'''library (neutral_io) {{
      delay_model : table_lookup;
      time_unit : "1ns";
      capacitive_load_unit (1, pf);
      lu_table_template (tiny) {{
        variable_1 : input_net_transition;
        variable_2 : total_output_net_capacitance;
        index_1 ("0.01, 25"); index_2 ("0.01, 5");
      }}
      cell (neutral_pad) {{
        pin (PAD) {{ direction : inout; is_pad : true; }}
        pin (IN) {{ direction : output; function : "PAD";
          timing () {{ related_pin : "{related_pin}"; timing_sense : positive_unate;
            cell_rise (tiny) {{ values ("0.1, 0.1", "0.1, 0.1"); }}
            cell_fall (tiny) {{ values ("0.1, 0.1", "0.1, 0.1"); }}
            rise_transition (tiny) {{ values ("0.1, 0.1", "0.1, 0.1"); }}
            fall_transition (tiny) {{ values ("0.1, 0.1", "0.1, 0.1"); }}
          }}
        }}
        pin (OUT) {{ direction : input; capacitance : 0.04; }}
      }}
      cell (neutral_buf) {{
        pin (A) {{ direction : input; capacitance : 0.01; }}
        pin (Y) {{ direction : output; function : "A";
          timing () {{ related_pin : "A"; timing_sense : positive_unate;
            cell_rise (tiny) {{ values ("0.1, 0.1", "0.1, 0.1"); }}
            cell_fall (tiny) {{ values ("0.1, 0.1", "0.1, 0.1"); }}
            rise_transition (tiny) {{ values ("0.1, 0.1", "0.1, 0.1"); }}
            fall_transition (tiny) {{ values ("0.1, 0.1", "0.1, 0.1"); }}
          }}
        }}
      }}
    }}''')
    _io_record(project, [liberty], core_module="neutral_core",
               chip_top_module="neutral_chip")
    path = project / "reports/phase3/io_pad_chip_top.json"
    doc = json.loads(path.read_text())
    doc["pad_instances"] = {
        "u_pad_a": {"port": "a", "master": "neutral_pad",
                    "terminal": "PAD", "core_pin": "IN", "direction": "input"},
        "u_pad_y": {"port": "y", "master": "neutral_pad",
                    "terminal": "PAD", "core_pin": "OUT", "direction": "output"},
    }
    path.write_text(json.dumps(doc))
    return project


@pytest.mark.parametrize(("declaration", "expected_pf"), [
    ("capacitive_load_unit (1, pf);", 1.0),
    ('capacitive_load_unit(1.000000, \\\n  "pf");', 1.0),
    ('capacitive_load_unit /* gap */ ( 2 , // unit follows\n "ff" );', 0.002),
    ('capacitive_load_unit(3, nf);', 3000.0),
])
def test_issue3427_real_liberty_capacitance_unit_grammar(declaration, expected_pf):
    """Quoted continued PDK syntax has the same unit authority as one-line syntax."""
    import sdc_environment as SE
    assert SE._liberty_capacitance_unit_pf(declaration) == expected_pf


@pytest.mark.parametrize("declaration", [
    'capacitive_load_unit(1, "xf");',
    'capacitive_load_unit(0, "pf");',
    'capacitive_load_unit(-1, "pf");',
    'capacitive_load_unit(1, "pf);',
])
def test_issue3427_invalid_liberty_capacitance_unit_is_refused(declaration):
    import sdc_environment as SE
    assert SE._liberty_capacitance_unit_pf(declaration) is None


def test_issue3427_quoted_continued_unit_translates_output_load(tmp_path):
    """The real sky130 IO unit spelling cannot make a present OUT cap unsourced."""
    import sdc_environment as SE
    project = _core_wrapper_project(tmp_path)
    record = json.loads((project / "reports/phase3/io_pad_chip_top.json").read_text())
    liberty = Path(record["io_library_liberty"][0])
    liberty.write_text(liberty.read_text().replace(
        "capacitive_load_unit (1, pf);",
        'capacitive_load_unit(1.000000, \\\n  "pf");'))
    staged = ("set_input_transition -max 25 [get_ports {a}]\n"
              "set_load -max 5 [get_ports {y}]\n")
    text, rec = SE.staged_sdc_pad_input_drive(
        project, staged, "input/constraints/external.sdc",
        analysis_top="neutral_core")
    assert rec["verdict"] == "PAD_TRANSLATED"
    assert rec["pad_model_basis"]["views"][0]["capacitance_unit_pf"] == 1.0
    assert "set_load -max 0.04 [get_ports {y}]" in text


def test_issue3427_core_boundary_translates_external_pad_constraints(tmp_path):
    """25 ns / 5 pF stay external facts; the core sees the selected pad."""
    import sdc_environment as SE
    project = _core_wrapper_project(tmp_path)
    staged = (
        "create_clock -period 10 [get_ports clk]\n"
        "set_input_transition -max 25.0 [get_ports {a}]\n"
        "set_input_transition -min 0.01 [get_ports {a}]\n"
        "set_load -max 5.0 [get_ports {y}]\n"
        "set_load -min 0.0 [get_ports {y}]\n")
    text, rec = SE.staged_sdc_pad_input_drive(
        project, staged, "input/constraints/external.sdc",
        analysis_top="neutral_core")
    active = [line for line in text.splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    assert rec["verdict"] == "PAD_TRANSLATED"
    assert not any(line.startswith("set_input_transition") for line in active)
    assert "set_load -max 5.0 [get_ports {y}]" not in active
    assert "set_load -min 0.0 [get_ports {y}]" not in active
    assert any(line == ("set_driving_cell -lib_cell neutral_pad -from_pin PAD -pin IN "
                        "-input_transition_rise 25 -input_transition_fall 25 "
                        "-max [get_ports {a}]") for line in active)
    assert "set_load -max 0.04 [get_ports {y}]" in active
    assert "set_load -min 0.04 [get_ports {y}]" in active
    assert len(rec["pad_model_basis"]["record_sha256"]) == 64
    assert len(rec["pad_model_basis"]["views"][0]["sha256"]) == 64
    assert {item["external_value"] for item in rec["external_pad_obligations"]} == {
        25.0, 0.01, 5.0, 0.0}


def test_issue3427_missing_pad_arc_disables_external_core_commands(tmp_path):
    """Reverse control: a named pad without the recorded arc cannot translate."""
    import sdc_environment as SE
    project = _core_wrapper_project(tmp_path, related_pin="WRONG")
    staged = ("create_clock -period 10 [get_ports clk]\n"
              "set_input_transition -max 25 [get_ports {a}]\n"
              "set_load -max 5 [get_ports {y}]\n")
    text, rec = SE.staged_sdc_pad_input_drive(
        project, staged, "input/constraints/external.sdc",
        analysis_top="neutral_core")
    active = [line for line in text.splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    assert rec["verdict"] == "NOT_MEASURED"
    assert active == ["create_clock -period 10 [get_ports clk]"]
    assert "PAD->IN" in rec["reason"]
    assert len(rec["refused_staged_sdc_lines"]) == 2


def test_issue3427_native_opensta_reads_the_translated_core_deck(tmp_path):
    """The exact emitted set_driving_cell shape is accepted by OpenSTA."""
    import sdc_environment as SE
    tool = shutil.which("sta")
    assert tool, "this native consumer test requires the EDA image"
    project = _core_wrapper_project(tmp_path)
    staged = ("set_input_transition -max 25 [get_ports {a}]\n"
              "set_input_transition -min 0.01 [get_ports {a}]\n"
              "set_load -max 5 [get_ports {y}]\n"
              "set_load -min 0 [get_ports {y}]\n")
    text, rec = SE.staged_sdc_pad_input_drive(
        project, staged, "input/constraints/external.sdc",
        analysis_top="neutral_core")
    assert rec["verdict"] == "PAD_TRANSLATED"
    liberty = Path(rec["pad_model_basis"]["views"][0]["liberty"])
    netlist = tmp_path / "core.v"
    netlist.write_text("module neutral_core(input a, output y); "
                       "neutral_buf u_buf(.A(a), .Y(y)); endmodule\n")
    sdc = tmp_path / "core.sdc"
    sdc.write_text(text)
    script = tmp_path / "read.tcl"
    script.write_text(
        f"read_liberty {{{liberty}}}\nread_verilog {{{netlist}}}\n"
        f"link_design neutral_core\nread_sdc {{{sdc}}}\n"
        "report_checks -path_delay max\nputs CORE_PAD_TRANSLATION_OK\nexit\n")
    run = subprocess.run([tool, "-no_init", "-exit", str(script)],
                         capture_output=True, text=True, timeout=120)
    output = run.stdout + run.stderr
    assert run.returncode == 0 and "CORE_PAD_TRANSLATION_OK" in output, output
    assert "Error:" not in output and "STA-" not in output, output


@pytest.mark.parametrize("header", [
    "cell (neutral_pad) { pin (PAD) { direction : input; } }",
    'cell ("neutral_pad") { pin (PAD) { direction : input; } }',
    'cell /* legal gap */ (\n "neutral_pad" // selected master\n ) { }',
])
def test_issue3440_prefilter_keeps_quoted_unquoted_selected_headers(header):
    import sdc_environment as SE
    assert SE._liberty_may_have_selected_cell(header, {"neutral_pad"}) is True


@pytest.mark.parametrize("text", [
    "/* cell (neutral_pad) { pin (PAD) {} } */\ncell (other) {}",
    'comment : "cell (neutral_pad) { not a group }";\ncell (other) {}',
    "// cell (neutral_pad) { }\ncell (other) {}",
    "cell (neutral_pad_wrapped) { pin (PAD) {} }",
])
def test_issue3440_prefilter_does_not_admit_comment_or_string_headers(text):
    import sdc_environment as SE
    assert SE._liberty_may_have_selected_cell(text, {"neutral_pad"}) is False


def test_issue3440_irrelevant_views_are_hash_bound_without_deep_parse(tmp_path):
    """The translated commands stay identical while irrelevant views are cheap."""
    import sdc_environment as SE
    project = _core_wrapper_project(tmp_path)
    staged = (
        "set_input_transition -max 25 [get_ports {a}]\n"
        "set_input_transition -min 0.01 [get_ports {a}]\n"
        "set_load -max 5 [get_ports {y}]\n"
        "set_load -min 0 [get_ports {y}]\n")
    baseline, base_rec = SE.staged_sdc_pad_input_drive(
        project, staged, "input/constraints/external.sdc",
        analysis_top="neutral_core")
    record_path = project / "reports/phase3/io_pad_chip_top.json"
    record = json.loads(record_path.read_text())
    selected = Path(record["io_library_liberty"][0])
    irrelevant = []
    for index in range(200):
        path = tmp_path / "pdk" / f"irrelevant_{index}.lib"
        extra = ("/* cell (neutral_pad) { pin (PAD) {} } */"
                 if index == 0 else
                 'note : "cell (neutral_pad) { not a group }";'
                 if index == 1 else "")
        path.write_text(
            f"library (irrelevant_{index}) {{ capacitive_load_unit (1, pf); "
            f"{extra} cell (other_{index}) {{ pin (A) {{ direction : input; }} }} }}")
        irrelevant.append(str(path))
    record["io_library_liberty"] = [str(selected), *irrelevant]
    record_path.write_text(json.dumps(record))

    optimized, rec = SE.staged_sdc_pad_input_drive(
        project, staged, "input/constraints/external.sdc",
        analysis_top="neutral_core")
    commands = lambda deck: [line for line in deck.splitlines()
                             if line.strip() and not line.lstrip().startswith("#")]
    assert base_rec["verdict"] == rec["verdict"] == "PAD_TRANSLATED"
    assert commands(optimized) == commands(baseline)
    basis = rec["pad_model_basis"]
    assert basis["read_view_count"] == 201
    assert basis["deep_parsed_view_count"] == 1
    assert basis["prefilter_skipped_view_count"] == 200
    assert len(basis["views"]) == 201
    assert all(len(view["sha256"]) == 64 for view in basis["views"])


def test_issue3440_unrelated_attribute_cannot_fabricate_selected_master(tmp_path):
    import sdc_environment as SE
    project = _core_wrapper_project(tmp_path)
    fake = tmp_path / "pdk" / "attribute_only.lib"
    fake.write_text(
        "library (attribute_only) { capacitive_load_unit (1, pf); "
        "selected_pad_master : neutral_pad; cell (other) { pin (A) { "
        "direction : input; capacitance : 0.1; } } }")
    record_path = project / "reports/phase3/io_pad_chip_top.json"
    record = json.loads(record_path.read_text())
    record["io_library_liberty"] = [str(fake)]
    record_path.write_text(json.dumps(record))
    models, basis = SE._core_pad_models(project)
    assert models is None
    assert "master neutral_pad absent" in basis["why"]
    assert basis["views"][0]["selected_masters"] == []


def test_an_absent_record_on_a_die_top_is_not_measured(tmp_path):
    import sdc_environment as SE
    assert "never resolved" in SE.pad_input_drive_not_measured(_die(tmp_path))
    assert SE.pad_input_drive_not_measured(_core(tmp_path)) is None


# -- the flow order (review_wave58 BLOCKER) ---------------------------------
#
# Step 7 authors the SDC before step_pnr's pad-ring producer writes
# io_pad_chip_top.json, so on a FRESH DIE run step 7's deck has no IO tier
# yet. asic_sdc_for_pnr must not reuse it: the digest binds the record, and
# the deck PnR and sign-off load is regenerated with the bracket.

def _step7_fixtures():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "padin_step7_fixtures",
        Path(__file__).resolve().parent / "test_step7_asic_sdc_is_authored_once_at_step7.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_fresh_die_run_carries_the_io_bracket_into_the_pnr_deck(tmp_path, monkeypatch):
    S7 = _step7_fixtures()
    from _ppa import timing as T
    proj = S7._project(tmp_path)
    marker = proj / TD.SELF_TAPEOUT_REL
    marker.parent.mkdir(parents=True)
    marker.write_text(TD.SELF_TAPEOUT_MARKER + "\n")
    assert TD.requests_pad_ring(proj) is True
    pdk = S7._pdk(monkeypatch)
    core_liberty = tmp_path / "neutral_core.lib"
    core_liberty.write_text('library(neutral) { time_unit : "1ns"; }\n')
    pdk.liberty = str(core_liberty)
    # step 7: no pad ring yet -> no drive can be resolved
    T.emit_step7_asic_sdc(p3, proj, S7.TOP, pdk, "some-container")
    assert _record(proj)["verdict"] == "NOT_MEASURED"
    step7_deck = (proj / S7._record(proj)["path"]).read_text()
    assert "NOT_MEASURED: OFFCHIP_INPUT_DRIVE" in step7_deck
    # step_pnr's pad-ring producer writes its record (the IO views it linked)
    _io_record(proj, [_io_lib(tmp_path, "ss")],
               core_module="neutral_core", chip_top_module=S7.TOP)
    got = T.asic_sdc_for_pnr(p3, proj, S7.TOP, pdk, "some-container")
    assert got["regenerated"] and "@io_pad_record" in got["regenerated"]
    rec = _record(proj)
    assert rec["verdict"] == "PDK_IO_TIER"
    assert all(ln in got["text"].splitlines() for ln in rec["sdc_lines"])
    assert "set_input_transition -min $_vibeic_pad_min [all_inputs]" in got["text"]
    # and the regenerated deck is now current: a second read reuses it
    again = T.asic_sdc_for_pnr(p3, proj, S7.TOP, pdk, "some-container")
    assert again["regenerated"] is None and again["text"] == got["text"]


def _issue3389_project(tmp_path, monkeypatch, *, libs, source):
    """A neutral ordinary Step7 core -> Step15 chip-boundary fixture."""
    S7 = _step7_fixtures()
    from _ppa import timing as T
    import sdc_environment as SE
    proj = S7._project(tmp_path)
    marker = proj / TD.SELF_TAPEOUT_REL
    marker.parent.mkdir(parents=True)
    marker.write_text(TD.SELF_TAPEOUT_MARKER + "\n")
    _io_record(proj, libs, core_module=S7.TOP,
               chip_top_module="neutral_physical_chip")
    values = {"set_driving_cell": ("quartz_sc__inv_1/ZN", source)}
    resolver = lambda *_a, **_k: (dict(values), [])
    monkeypatch.setattr(p3, "_sdc_environment_values", resolver)
    monkeypatch.setattr(SE, "_sdc_environment_values", resolver)
    pdk = S7._pdk(monkeypatch)
    core_liberty = tmp_path / "neutral_core.lib"
    core_liberty.write_text('library(neutral) { time_unit : "1ns"; }\n')
    pdk.liberty = str(core_liberty)
    T.emit_step7_asic_sdc(p3, proj, S7.TOP, pdk, "some-container")
    return S7, T, SE, proj, pdk


def test_issue3389_pnr_replaces_the_generated_core_driver_at_chip_boundary(
        tmp_path, monkeypatch):
    io_lib = _io_lib(tmp_path, "tt")
    S7, T, SE, proj, pdk = _issue3389_project(
        tmp_path, monkeypatch, libs=[io_lib],
        source="pinned PDK default /pdk/config.tcl:SYNTH_DRIVING_CELL")
    step7 = (proj / S7._record(proj)["path"]).read_text()
    assert _commands(step7, "set_driving_cell") == [
        "set_driving_cell -lib_cell quartz_sc__inv_1 -pin ZN [all_inputs]"]

    got = T.asic_sdc_for_pnr(p3, proj, S7.TOP, pdk, "some-container")
    assert _commands(got["text"], "set_driving_cell") == []
    assert _commands(got["text"], "set_input_transition") == [
        "set_input_transition -max $_vibeic_pad_max [all_inputs]",
        "set_input_transition -min $_vibeic_pad_min [all_inputs]",
    ]
    record = json.loads((proj / _REPORT).read_text())
    assert record["verdict"] == "PDK_IO_TIER"
    assert record["analysis_top"] == "neutral_physical_chip"
    assert record["refused_core_driving_cell"]["value"] == "quartz_sc__inv_1/ZN"
    derived = got["derivation"]["pad_input_drive"]
    assert derived["applied"] is True
    assert derived["logical_top"] == S7.TOP
    assert derived["analysis_top"] == "neutral_physical_chip"
    assert derived["verdict"] == "PDK_IO_TIER"
    assert derived["record"] == SE.PAD_INPUT_DRIVE_REPORT
    assert derived["record_sha256"] == T._sha256_text(
        (proj / _REPORT).read_text())
    assert derived["producer_record_sha256"] == record["boundary"]["record_sha256"]


def test_issue3389_pnr_preserves_a_design_declared_external_driver(
        tmp_path, monkeypatch):
    io_lib = _io_lib(tmp_path, "tt")
    S7, T, _SE, proj, pdk = _issue3389_project(
        tmp_path, monkeypatch, libs=[io_lib],
        source="design doc input/docs/L9_constraints.md:3")
    line = "set_driving_cell -lib_cell quartz_sc__inv_1 -pin ZN [all_inputs]"
    got = T.asic_sdc_for_pnr(p3, proj, S7.TOP, pdk, "some-container")
    assert got["text"].splitlines().count(line) == 1
    record = json.loads((proj / _REPORT).read_text())
    assert record["verdict"] == "DECLARED"
    assert record["source"] == "design doc input/docs/L9_constraints.md:3"
    assert record["analysis_top"] == "neutral_physical_chip"


def test_issue3389_missing_io_authority_removes_core_drive_and_refuses(
        tmp_path, monkeypatch):
    S7, T, _SE, proj, pdk = _issue3389_project(
        tmp_path, monkeypatch, libs=[],
        source="pinned PDK default /pdk/config.tcl:SYNTH_DRIVING_CELL")
    got = T.asic_sdc_for_pnr(p3, proj, S7.TOP, pdk, "some-container")
    assert _commands(got["text"], "set_driving_cell") == []
    assert "NOT_MEASURED: OFFCHIP_INPUT_DRIVE" in got["text"]
    record = json.loads((proj / _REPORT).read_text())
    assert record["verdict"] == "NOT_MEASURED"
    assert record["analysis_top"] == "neutral_physical_chip"


def test_issue3389_failed_pad_publication_cannot_authorize_a_boundary(
        tmp_path, monkeypatch):
    S7 = _step7_fixtures()
    from _ppa import timing as T
    import sdc_environment as SE
    proj = S7._project(tmp_path)
    marker = proj / TD.SELF_TAPEOUT_REL
    marker.parent.mkdir(parents=True)
    marker.write_text(TD.SELF_TAPEOUT_MARKER + "\n")
    _io_record(proj, [_io_lib(tmp_path, "tt")], core_module=S7.TOP,
               chip_top_module="neutral_physical_chip", verdict="FAIL")
    values = {"set_driving_cell": (
        "quartz_sc__inv_1/ZN",
        "pinned PDK default /pdk/config.tcl:SYNTH_DRIVING_CELL")}
    resolver = lambda *_a, **_k: (dict(values), [])
    monkeypatch.setattr(p3, "_sdc_environment_values", resolver)
    monkeypatch.setattr(SE, "_sdc_environment_values", resolver)
    pdk = S7._pdk(monkeypatch)
    core_liberty = tmp_path / "neutral_core.lib"
    core_liberty.write_text('library(neutral) { time_unit : "1ns"; }\n')
    pdk.liberty = str(core_liberty)
    T.emit_step7_asic_sdc(p3, proj, S7.TOP, pdk, "some-container")
    got = T.asic_sdc_for_pnr(p3, proj, S7.TOP, pdk, "some-container")
    assert _commands(got["text"], "set_driving_cell") == []
    assert got["derivation"] is None
    record = json.loads((proj / _REPORT).read_text())
    assert record["verdict"] == "NOT_MEASURED"
    assert "not a successful current publication" in record["reason"]


# -- the runner wiring of the STA fold (review_wave58 MINOR) ----------------

def test_step_declared_signoff_gates_folds_the_pad_drive(tmp_path, monkeypatch):
    project = _die(tmp_path)
    _sdc(project, monkeypatch)            # no IO tier -> NOT_MEASURED record
    seen = []

    def fake_gate(_project, name, _program, _out_rel, _argv):
        seen.append(name)
        return p3.StepResult(name, "PASS", 0.0, f"{name} PASS", [], {})
    monkeypatch.setattr(p3, "_run_declared_signoff_gate", fake_gate)
    rows = p3.step_declared_signoff_gates(project)
    by = {r.name: r for r in rows}
    assert p3._STA_VERDICT_GATE in seen
    assert by[p3._STA_VERDICT_GATE].status == "NOT_MEASURED"
    assert "OFFCHIP_INPUT_DRIVE" in by[p3._STA_VERDICT_GATE].detail


def test_step7_with_a_staged_sdc_on_a_die_resolves_and_rewrites_the_record(tmp_path, monkeypatch):
    """Through author_asic_sdc's design-staged branch (step 7): the staged
    deck sets no drive, so it gets the IO bracket, and a stale record from an
    earlier auto-SDC run is replaced."""
    S7 = _step7_fixtures()
    from _ppa import timing as T
    proj = S7._project(tmp_path)
    marker = proj / TD.SELF_TAPEOUT_REL
    marker.parent.mkdir(parents=True)
    marker.write_text(TD.SELF_TAPEOUT_MARKER + "\n")
    (proj / "input/constraints").mkdir(parents=True)
    (proj / "input/constraints/clock.sdc").write_text(
        "create_clock -name core -period 10 [get_ports clk]\n")
    _io_record(proj, [_io_lib(tmp_path, "ss")],
               core_module="neutral_core", chip_top_module=S7.TOP)
    stale = proj / _REPORT
    stale.write_text(json.dumps({"verdict": "DECLARED", "sdc_lines": ["x"]}))
    pdk = S7._pdk(monkeypatch)
    core_liberty = tmp_path / "neutral_core.lib"
    core_liberty.write_text('library(neutral) { time_unit : "1ns"; }\n')
    pdk.liberty = str(core_liberty)
    T.emit_step7_asic_sdc(p3, proj, S7.TOP, pdk, "some-container")
    rec = _record(proj)
    assert rec["verdict"] == "PDK_IO_TIER"
    deck = (proj / S7._record(proj)["path"]).read_text().splitlines()
    assert all(ln in deck for ln in rec["sdc_lines"])
    assert S7._record(proj)["pad_input_drive"] == "PDK_IO_TIER"


def test_unselected_supply_views_do_not_block_the_instantiated_input_pad(tmp_path):
    import sdc_environment as SE
    project = _die(tmp_path)
    signal = _io_lib(tmp_path, 'tt')
    supply = tmp_path / 'pdk' / 'quartz_supply.lib'
    supply.write_text('library (supply) { time_unit : "1ns"; cell (supply_pad) { '
                      'pin (BOND) { is_pad : true; direction : inout; max_transition : 1; } } }')
    _io_record(project, [supply, signal])
    path = project / SE.IO_PAD_RECORD
    doc = json.loads(path.read_text())
    doc['pad_instances'] = {'u_in': {'master': 'quartz_io__in', 'direction': 'input'},
                           'u_supply': {'master': 'supply_pad', 'direction': 'inout',
                                        'port': 'VDD', 'terminal': 'BOND', 'kind': 'power'}}
    path.write_text(json.dumps(doc))
    bracket, basis = SE._pdk_io_input_transition(project)
    assert bracket is not None, basis.get('why')
    assert bracket['common_min_ns'] == 0.08
    assert bracket['common_max_ns'] == 1.0
    assert [v['liberty'] for v in basis['views']] == [str(signal)]
    # An unmodelled instantiated input must still refuse, even with another
    # perfectly characterised library available.
    doc['pad_instances']['u_in']['master'] = 'missing_input_pad'
    path.write_text(json.dumps(doc))
    bracket, basis = SE._pdk_io_input_transition(project)
    assert bracket is None and 'missing_input_pad' in basis['why']
