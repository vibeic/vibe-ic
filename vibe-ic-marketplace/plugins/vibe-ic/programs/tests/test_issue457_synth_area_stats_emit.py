"""#457 — the synthesis step declares an area artefact nothing ever wrote.

The figure was never missing: a liberty-aware `stat` pass already prints it
into the synthesis log. Lifting it out is only safe because of two properties
MEASURED against real yosys 0.67 output (both fixtures below are verbatim
excerpts of runs performed while fixing this issue):

  * A hierarchical design prints one block PER MODULE whose figure is that
    module's LOCAL area EXCLUDING submodules, then a `design hierarchy`
    roll-up whose figure INCLUDES them. On the measured three-level design the
    per-module lines read 0.0 / 0.0 / 28.7776 while the true total was
    115.1104 — so "last line", "biggest line" and "line naming the top" are
    all wrong.
  * The same design synthesised flat prints ONE block, no roll-up, and the
    local figure IS the total. Both shapes must yield the same number.

Test files may name designs and PDKs; the gate source may not.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1] / "synth_area_stats_emit.py"


def _load():
    spec = importlib.util.spec_from_file_location("synth_area_stats_emit",
                                                  PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PROG.parent))
    spec.loader.exec_module(mod)
    return mod


M = _load()


# ---------------------------------------------------------------------------
# Fixtures — verbatim yosys 0.67 output shapes
# ---------------------------------------------------------------------------
# Hierarchy retained: per-module locals (top reads 0.0!) + design roll-up.
HIER_LOG = """\
-- Running command `read_verilog dut.v; synth -top top_dut; \
stat -liberty x.lib; write_verilog -noattr netlist.v' --

7. Printing statistics.

=== top_dut ===

        3        - wires
        0        - cells
        2        - submodules
        2        -   mid

   Chip area for module '\\top_dut': 0.000000
     of which used for sequential elements: 0.000000 (-nan%)

=== mid ===

        0        - cells
        2        - submodules
        2        -   leaf

   Chip area for module '\\mid': 0.000000
     of which used for sequential elements: 0.000000 (-nan%)

=== leaf ===

        2   28.778 cells
        1   20.019   sky130_fd_sc_hd__dfxtp_1
        1    8.758   sky130_fd_sc_hd__xnor2_1

   Chip area for module '\\leaf': 28.777600
     of which used for sequential elements: 20.019200 (69.57%)

=== design hierarchy ===

        8   115.11 top_dut
        2   28.778   leaf

        8   115.11 cells
        4   80.077   sky130_fd_sc_hd__dfxtp_1
        4   35.034   sky130_fd_sc_hd__xnor2_1
        2   115.11 submodules
        2   115.11   mid

   Chip area for top module '\\top_dut': 115.110400
     of which used for sequential elements: 80.076800 (69.57%)

8. Executing Verilog backend.
Yosys 0.67+ (git sha1 baf347249, Release, GNU /usr/bin/c++ 13.3.0)
"""

# Same design, synthesised flat: ONE block, no roll-up, local == total.
FLAT_LOG = """\
-- Running command `read_verilog dut.v; synth -top top_dut -flatten; \
stat -liberty x.lib; write_verilog -noattr netlist.v' --

7. Printing statistics.

=== top_dut ===

        8   115.11 cells
        4   80.077   sky130_fd_sc_hd__dfxtp_1
        4   35.034   sky130_fd_sc_hd__xnor2_1

   Chip area for module '\\top_dut': 115.110400
     of which used for sequential elements: 80.076800 (69.57%)

Yosys 0.67+ (git sha1 baf347249, Release, GNU /usr/bin/c++ 13.3.0)
"""

# Hierarchy retained but NO top module identified, so no roll-up is printed.
# The design total is simply not in this log.
NO_ROLLUP_LOG = HIER_LOG.split("=== design hierarchy ===")[0]

FLAT_NETLIST = """\
module top_dut(clk, d, o);
""" + "".join(
    f"  sky130_fd_sc_hd__dfxtp_1 _{i}_ (.CLK(clk), .D(d), .Q(o));\n"
    for i in range(4)
) + "".join(
    f"  sky130_fd_sc_hd__xnor2_1 _x{i}_ (.A(d), .B(d), .Y(o));\n"
    for i in range(4)
) + "endmodule\n"


def _write(tmp_path, log_text, netlist_text=None, netlist_name="netlist.v"):
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True, exist_ok=True)
    log = synth / "synth.log"
    log.write_text(log_text)
    nl = None
    if netlist_text is not None:
        nl = synth / netlist_name
        nl.write_text(netlist_text)
    return tmp_path, log, nl


def _run(project, *extra):
    return subprocess.run(
        [sys.executable, str(PROG), str(project), *extra],
        capture_output=True, text=True)


# ---------------------------------------------------------------------------
# The selection rule
# ---------------------------------------------------------------------------
def test_rollup_is_selected_not_the_last_or_biggest_local_area():
    """The whole point: naive picks return a confidently wrong number."""
    blocks = M.parse_blocks(HIER_LOG)
    block, rule, _ = M.select_block(blocks)
    assert block.area == 115.1104
    assert rule == "DESIGN_HIERARCHY_ROLLUP"
    assert block.area_is_rollup is True

    locals_only = [b for b in blocks if not b.area_is_rollup]
    # "take the last `Chip area for module`" -> the deepest leaf, 4x too small
    assert locals_only[-1].area == 28.7776
    # "take the biggest local" -> same wrong answer
    assert max(b.area for b in locals_only) == 28.7776
    # "take the line naming the top module" -> zero, because a local figure
    # EXCLUDES submodules and this top has all its logic in children
    named_top = [b for b in locals_only if b.area_module == "top_dut"]
    assert named_top[0].area == 0.0


def test_flat_and_hierarchical_logs_of_one_design_agree():
    """Independent validation: two log SHAPES, one design, one number."""
    hier, _, _ = M.select_block(M.parse_blocks(HIER_LOG))
    flat, rule, _ = M.select_block(M.parse_blocks(FLAT_LOG))
    assert hier.area == flat.area == 115.1104
    assert rule == "SINGLE_MODULE_NO_HIERARCHY"


def test_rollup_rows_exclude_the_submodule_category():
    """The roll-up block tabulates cells AND submodules; only cells are area
    rows. Swallowing the submodule rows would double the sum."""
    block, _, _ = M.select_block(M.parse_blocks(HIER_LOG))
    names = [c for _n, _a, c in block.rows]
    assert "mid" not in names and "submodules" not in names
    assert block.row_cell_sum == 8


# ---------------------------------------------------------------------------
# Refusal — the #454 principle: no figure beats a wrong figure
# ---------------------------------------------------------------------------
def test_refuses_and_writes_nothing_when_no_rollup_exists(tmp_path):
    project, _log, _ = _write(tmp_path, NO_ROLLUP_LOG)
    r = _run(project)
    assert r.returncode == 2, r.stdout
    assert "REFUSED" in r.stderr
    assert not (project / "phase2" / "stage2" / "synth" / "stats.json").exists()


def test_refusal_does_not_satisfy_the_declared_output(tmp_path):
    """Emitting the artefact with a null area would satisfy the step's
    existence check while carrying no number — switching off the signal the
    check exists to raise. Absence must be preserved."""
    project, _log, _ = _write(tmp_path, NO_ROLLUP_LOG)
    _run(project)
    synth = project / "phase2" / "stage2" / "synth"
    assert list(synth.glob("stats.json")) == []
    assert list(synth.glob("area.rpt")) == []


def test_log_with_no_area_at_all_refuses(tmp_path):
    project, _log, _ = _write(tmp_path, "=== m ===\n   0 cells\nno area here\n")
    r = _run(project)
    assert r.returncode == 2
    assert not (project / "phase2" / "stage2" / "synth" / "stats.json").exists()


# ---------------------------------------------------------------------------
# Corroboration must have teeth (no vacuous agreement)
# ---------------------------------------------------------------------------
def test_emits_with_all_corroborations_agreeing(tmp_path):
    project, _log, _ = _write(tmp_path, FLAT_LOG, FLAT_NETLIST)
    r = _run(project)
    assert r.returncode == 0, r.stderr
    rep = json.loads(
        (project / "phase2" / "stage2" / "synth" / "stats.json").read_text())
    assert rep["chip_area"] == 115.1104
    assert rep["cell_count"] == 8
    c = rep["corroboration"]
    assert c["r0_completeness"]["status"] == "AGREE"
    assert c["r1_internal"]["status"] == "AGREE"
    assert c["r2_external"]["status"] == "AGREE"
    assert c["r2_external"]["netlist_instantiations"] == 8


def test_netlist_that_disagrees_refutes_the_figure(tmp_path):
    """R2 has teeth: a netlist that does not contain the tabulated cells
    discards the figure rather than publishing it."""
    wrong = FLAT_NETLIST.replace("sky130_fd_sc_hd__dfxtp_1",
                                 "sky130_fd_sc_hd__dfxtp_2")
    project, _log, _ = _write(tmp_path, FLAT_LOG, wrong)
    r = _run(project)
    assert r.returncode == 2, r.stdout
    assert not (project / "phase2" / "stage2" / "synth" / "stats.json").exists()


def test_zero_parsed_rows_is_refuted_not_vacuously_agreed(tmp_path):
    """A parser that silently collects NO rows would make both corroborations
    compare zero against zero and 'agree'. That vacuous pass is the failure
    this test pins: no rows means no corroboration, which means no emit."""
    # An area line with a summary the row parser cannot attribute to it.
    log = ("=== m ===\n"
           "        7        - cells\n"
           "   Chip area for module '\\m': 999.000000\n")
    project, _l, _ = _write(tmp_path, log)
    r = _run(project)
    assert r.returncode == 2, r.stdout
    assert not (project / "phase2" / "stage2" / "synth" / "stats.json").exists()


def test_every_corroboration_reports_refuted_not_na_when_it_has_no_rows():
    """Each corroboration is pinned INDEPENDENTLY. 'Not applicable' means the
    comparison does not apply here; having nothing to compare is a different
    thing and must not borrow that word, or a source with no evidence reads as
    a source that agreed."""
    empty = M.Block("m")
    empty.area = 42.0
    empty.cells_n = 7
    checks = M.corroborate(empty, None)
    assert checks["r0_completeness"]["status"] == "REFUTED"
    assert checks["r1_internal"]["status"] == "REFUTED"
    assert checks["r2_external"]["status"] == "REFUTED"


def test_truncated_row_list_is_refuted_by_the_completeness_check(tmp_path):
    """R0: the block states how many cells it tabulated. If the rows parsed do
    not add up, the list was mis-read and every derived figure is suspect."""
    log = FLAT_LOG.replace("        8   115.11 cells",
                           "       99   115.11 cells")
    project, _l, _ = _write(tmp_path, log, FLAT_NETLIST)
    r = _run(project)
    assert r.returncode == 2, r.stdout
    assert not (project / "phase2" / "stage2" / "synth" / "stats.json").exists()


def test_area_that_contradicts_its_own_rows_is_refuted(tmp_path):
    """R1: a figure lifted from a different block than the rows fails."""
    log = FLAT_LOG.replace("115.110400", "9999.000000")
    project, _l, _ = _write(tmp_path, log, FLAT_NETLIST)
    r = _run(project)
    assert r.returncode == 2, r.stdout


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
def test_report_says_which_line_the_figure_came_from(tmp_path):
    project, _l, _ = _write(tmp_path, HIER_LOG, None)
    r = _run(project)
    assert r.returncode == 0, r.stderr
    rep = json.loads(
        (project / "phase2" / "stage2" / "synth" / "stats.json").read_text())
    sel = rep["selection"]
    lines = HIER_LOG.splitlines()
    assert lines[sel["source_line"] - 1] == sel["source_text"]
    assert "for top module" in sel["source_text"]
    assert sel["area_lines_in_log"] == 4      # 3 locals + the roll-up
    assert sel["source_block"] == "design hierarchy"
    assert rep["includes_submodules"] is True


def test_does_not_invent_an_area_unit(tmp_path):
    """The tool prints the figure in the cell library's own unit and never
    restates it; naming a concrete unit here would be an invention."""
    project, _l, _ = _write(tmp_path, FLAT_LOG, FLAT_NETLIST)
    _run(project)
    rep = json.loads(
        (project / "phase2" / "stage2" / "synth" / "stats.json").read_text())
    assert "um" not in rep["chip_area_unit"].lower()
    assert "chip_area_um2" not in rep


# ---------------------------------------------------------------------------
# Self-anchored netlist resolution
# ---------------------------------------------------------------------------
def test_corroborates_against_the_netlist_the_log_itself_named(tmp_path):
    """A synthesis dir can hold a netlist from an OLDER tool invocation.
    Comparing against that one would refute a correct figure, so the netlist
    is resolved from the log's own write pass."""
    log = FLAT_LOG + (
        "\n-- Running command `stat -liberty x.lib; "
        "write_verilog -noattr /somewhere/top_dut_synth.v' --\n")
    project, _l, _ = _write(tmp_path, log, FLAT_NETLIST,
                            netlist_name="top_dut_synth.v")
    # a stale netlist sits alongside and must NOT be the one compared
    (project / "phase2" / "stage2" / "synth" / "netlist.v").write_text(
        "module top_dut(); endmodule\n")
    r = _run(project)
    assert r.returncode == 0, r.stderr
    rep = json.loads(
        (project / "phase2" / "stage2" / "synth" / "stats.json").read_text())
    assert rep["corroboration"]["r2_external"]["netlist"] == "top_dut_synth.v"


def test_multi_module_netlist_marks_r2_not_applicable(tmp_path):
    """Instance counts in a roll-up are not comparable to a per-module
    netlist's text; R2 must say so rather than pretend to agree."""
    project, _l, _ = _write(tmp_path, HIER_LOG,
                            "module a(); endmodule\nmodule b(); endmodule\n")
    r = _run(project)
    assert r.returncode == 0, r.stderr
    rep = json.loads(
        (project / "phase2" / "stage2" / "synth" / "stats.json").read_text())
    assert rep["corroboration"]["r2_external"]["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------------------
# Retry-appended logs
# ---------------------------------------------------------------------------
def test_last_elaboration_wins_when_the_log_concatenates_retries(tmp_path):
    """A frontend fallback appends a whole second transcript to the same file.
    The surviving netlist came from the last elaboration."""
    second = FLAT_LOG.replace("115.110400", "230.220800") \
                     .replace("115.11 cells", "230.22 cells") \
                     .replace("80.077 ", "160.154 ") \
                     .replace("35.034 ", "70.068 ") \
                     .replace("        4 ", "        8 ")
    combined = FLAT_LOG + "\n=== SLANG FALLBACK FRONTEND ===\n" + second
    block, rule, _ = M.select_block(M.parse_blocks(combined))
    assert rule == "SINGLE_MODULE_NO_HIERARCHY"
    assert block.area == 230.2208


# ---------------------------------------------------------------------------
# Wiring: the artefact is produced INSIDE the run
# ---------------------------------------------------------------------------
def test_runner_calls_the_emitter_in_the_synthesis_step():
    """#447 class: a post-hoc scraper works where the run happened and finds
    nothing in a fresh clone, because the log is not necessarily published.
    The emit must be a step output."""
    src = (PROG.parent / "phase3_one_shot_runner.py").read_text()
    assert "import synth_area_stats_emit as _sas" in src
    # The CALL, not one exact spelling of its argument list. This used to pin
    # `_sas.emit_for_run(project, log, netlist)` verbatim and broke the moment
    # the emitter gained the library argument — a coupled change, not a
    # regression. What must stay true is that the synthesis step calls the
    # emitter with the run it just produced.
    import ast as _ast
    fn = next((n for n in _ast.walk(_ast.parse(src))
               if isinstance(n, _ast.FunctionDef) and n.name == "step_synth"), None)
    assert fn is not None, "phase3_one_shot_runner.step_synth is gone"
    body = _ast.get_source_segment(src, fn) or ""
    assert "_sas.emit_for_run(" in body, (
        "step_synth no longer calls the emitter, so the artefact is back to "
        "being scraped after the fact — the #447 defect this test is about")
    for arg in ("project", "log", "netlist"):
        assert arg in body.split("_sas.emit_for_run(", 1)[1][:400], arg


def test_flow_declaration_is_untouched():
    """#404 class: a repair must not rewrite the input of the gate that
    detects it. The declared outputs stay as they are; the producer is what
    changes."""
    flow = (PROG.parent.parent / "flow"
            / "phase1_phase2_phase3.yaml").read_text()
    assert ('- "phase2/stage2/synth/area.rpt OR '
            'phase2/stage2/synth/stats.json"') in flow


def test_emit_for_run_returns_none_on_refusal(tmp_path):
    project, log, _ = _write(tmp_path, NO_ROLLUP_LOG)
    assert M.emit_for_run(project, log, None) is None
    assert not (project / "phase2" / "stage2" / "synth" / "stats.json").exists()


def test_emit_for_run_writes_the_declared_path(tmp_path):
    project, log, nl = _write(tmp_path, FLAT_LOG, FLAT_NETLIST)
    out = M.emit_for_run(project, log, nl)
    assert out == project / "phase2" / "stage2" / "synth" / "stats.json"
    assert json.loads(out.read_text())["chip_area"] == 115.1104


# ---------------------------------------------------------------------------
# Generality
# ---------------------------------------------------------------------------
def test_no_design_or_vendor_literal_in_the_gate():
    src = PROG.read_text()
    body = src.split('"""', 2)[-1]
    banned = ("sky130", "gf180", "ihp-sg13", "nangate", "asap7", "ibex",
              "caravel", "spm", "subservient", "sha256", "opentitan",
              "user_project_wrapper", "chip_top", "top_dut")
    for tok in banned:
        assert tok not in body, f"design/PDK literal {tok!r} leaked into gate"


def test_cell_names_come_from_the_log_not_a_builtin_list():
    """Generality: an unseen library's cell names must work untouched."""
    log = (FLAT_LOG.replace("sky130_fd_sc_hd__dfxtp_1", "zz_made_up_ff")
                   .replace("sky130_fd_sc_hd__xnor2_1", "zz_made_up_xnor"))
    net = (FLAT_NETLIST.replace("sky130_fd_sc_hd__dfxtp_1", "zz_made_up_ff")
                       .replace("sky130_fd_sc_hd__xnor2_1", "zz_made_up_xnor"))
    block, _, _ = M.select_block(M.parse_blocks(log))
    assert block.row_cell_sum == 8
    _per, total = M.count_netlist_cells(net, [c for _n, _a, c in block.rows])
    assert total == 8
