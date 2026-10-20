"""The flow's `steps/` publication view is not authoritative RTL.

``<project>/steps/<phase>/<stage>/<id>_<name>/`` republishes each canonical step
output under its flow-step id.  Everything there is already in scope at its
canonical location if it belongs in scope at all, so scanning the tree can only
duplicate a file that is already scanned or admit a build OUTPUT whose
canonical directory ``EXCLUDED_DIR_NAMES`` already excludes.

Both happened.  The component ``synth`` in that set never matched

    steps/phase2/stage2/9_synthesis_yosys_mapped_netlist/netlist.v

because the publication view names the directory after the flow STEP, not
after the build dir.

MEASURED, edge_llm_accel x nangate45, a 3.1M-cell design whose RTL is 3 files
of 12,499 bytes: ``authoritative_rtl_files`` returned 9 files / 715,640,356
bytes -- the same 358 MB emitted gate-level netlist twice.  Its two consumers
then ran

    cdc_async_input_check            160.72 s   3,502,212 kB RSS
    clock_domain_reg_crossing_check   67.00 s   3,503,076 kB RSS

and both TIMED OUT under the P0 umbrella's per-gate budget; the P0 FAIL halted
the flow at phase 2 and Phase 3 never ran.  After the exclusion, on the same
tree: 0.04 s / 14,080 kB and 0.04 s / 15,104 kB, both with the SAME verdict.

chip-AGNOSTIC: `steps` is the flow's own directory name; no chip, PDK or vendor
literal participates.
"""
import sys
import shutil
import subprocess
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rtl_scan_scope as S  # noqa: E402
import gate_utils as G  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


def _mk(tmp_path):
    """A project with real RTL, a build output, and a steps/ view of both."""
    p = tmp_path / "proj"
    (p / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (p / "phase2" / "stage1" / "rtl" / "widget_core.v").write_text(
        "module widget_core(input clk); endmodule\n")
    (p / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (p / "phase2" / "stage2" / "synth" / "netlist.v").write_text(
        "module widget_core(); NAND2_X1 g0(); endmodule\n")
    # the publication view: the SAME two files, republished by step id
    d1 = p / "steps" / "phase2" / "stage1" / "1_spec_to_rtl"
    d2 = p / "steps" / "phase2" / "stage2" / "9_synthesis_yosys_mapped_netlist"
    d3 = p / "steps" / "phase2" / "stage2" / \
        "14_synthesis_handoff_gate_pre_pnr_yosys_script_netl"
    for d in (d1, d2, d3):
        d.mkdir(parents=True)
    (d1 / "widget_core.v").write_text("module widget_core(input clk); endmodule\n")
    (d2 / "netlist.v").write_text("module widget_core(); NAND2_X1 g0(); endmodule\n")
    (d3 / "netlist.v").write_text("module widget_core(); NAND2_X1 g0(); endmodule\n")
    return p


def test_the_steps_view_is_out_of_scope(tmp_path):
    """NEGATIVE CONTROL — fails pre-fix, passes post-fix."""
    p = _mk(tmp_path)
    rels = sorted(str(f.relative_to(p)) for f in S.authoritative_rtl_files(p))
    assert not [r for r in rels if r.startswith("steps/")], (
        "the steps/ publication view was scanned as authoritative RTL: %r"
        % (rels,))


def test_the_emitted_netlist_is_never_returned_by_either_route(tmp_path):
    """NEGATIVE CONTROL — fails pre-fix, passes post-fix.

    The canonical copy is already excluded (component `synth`); the point is
    that the republished copies are excluded too, so the build output cannot
    re-enter scope through the back door.
    """
    p = _mk(tmp_path)
    rels = sorted(str(f.relative_to(p)) for f in S.authoritative_rtl_files(p))
    assert not [r for r in rels if r.endswith("netlist.v")], rels


def test_the_real_rtl_is_still_in_scope(tmp_path):
    """The exclusion must not cost the design its own source."""
    p = _mk(tmp_path)
    rels = sorted(str(f.relative_to(p)) for f in S.authoritative_rtl_files(p))
    assert rels == ["phase2/stage1/rtl/widget_core.v"], rels


def test_a_directory_merely_starting_with_steps_is_not_excluded(tmp_path):
    """TIGHTENING GUARD — exact component match, not a prefix.

    `EXCLUDED_DIR_NAMES` is consulted by equality, and this asserts the new
    entry keeps that contract: a `stepsize/` or `steps_of_freedom/` directory
    is an ordinary directory, and #545's whole lesson was that over-broad
    matching is its own defect.
    """
    p = tmp_path / "proj"
    (p / "stepsize" / "rtl").mkdir(parents=True)
    (p / "stepsize" / "rtl" / "widget_core.v").write_text("module w(); endmodule\n")
    rels = sorted(str(f.relative_to(p)) for f in S.authoritative_rtl_files(p))
    assert rels == ["stepsize/rtl/widget_core.v"], rels


def test_the_pre_existing_exclusions_are_untouched(tmp_path):
    """#545's own cases must keep behaving: input/, sim*, dot-dirs."""
    p = tmp_path / "proj"
    for rel in ("input/vendor/ip.v",
                "sim_full_stack/flat.v",
                "sim/tb.v",
                ".fpga_stash/flat.v",
                "phase2/stage1/rtl/widget_core.v"):
        f = p / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("module w(); endmodule\n")
    rels = sorted(str(f.relative_to(p)) for f in S.authoritative_rtl_files(p))
    assert rels == ["phase2/stage1/rtl/widget_core.v"], rels


@pytest.mark.parametrize("reader", [S.authoritative_rtl_files, G.find_rtl_files])
def test_current_build_excludes_retained_producer_and_reverse_control_sources(tmp_path, reader):
    """The same checked-in source at three historical roles is not three builds."""
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                          "calibration", "cal_eqy_gate.v")
    current = tmp_path / "phase2/stage1/rtl/current.v"
    paths = [current, tmp_path / "phase2/stage1/formal_history/epoch/old.v",
             tmp_path / "catalog_local_derivative_epoch/native_parent_red/parent.v",
             tmp_path / "phase3/librelane/02-yosys-synthesis/netlist.v"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
    assert reader(tmp_path) == [current]


@pytest.mark.parametrize("reader", [S.authoritative_rtl_files, G.find_rtl_files])
def test_invalid_current_source_is_not_replaced_by_clean_history(tmp_path, reader):
    current = tmp_path / "phase2/stage1/rtl/broken.sv"
    current.parent.mkdir(parents=True)
    current.write_text("module broken(input logic clk;\n")
    history = tmp_path / "phase2/stage1/formal_history/epoch/repaired.sv"
    history.parent.mkdir(parents=True)
    history.write_text("module repaired(input logic clk); endmodule\n")
    assert reader(tmp_path) == [current]


@pytest.mark.parametrize("reader", [S.authoritative_rtl_files, G.find_rtl_files])
def test_empty_current_stage_does_not_promote_history_to_design(tmp_path, reader):
    (tmp_path / "phase2/stage1/rtl").mkdir(parents=True)
    history = tmp_path / "catalog_local_derivative_epoch/native_parent_red/old.v"
    history.parent.mkdir(parents=True)
    history.write_text("module old(); endmodule\n")
    assert reader(tmp_path) == []


@pytest.mark.parametrize("reader", [S.authoritative_rtl_files, G.find_rtl_files])
def test_legacy_source_tree_without_current_stage_keeps_its_scope(tmp_path, reader):
    paths = [tmp_path / "src/logic.v", tmp_path / "support/adapter.sv"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("module leaf(); endmodule\n")
    assert set(reader(tmp_path)) == set(paths)


def test_gate_utils_retains_its_existing_staged_macro_support(tmp_path):
    current = tmp_path / "phase2/stage1/rtl/current.v"
    macro = tmp_path / "input/pdk/macro_stub.v"
    for path in [current, macro]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("module leaf(); endmodule\n")
    assert set(G.find_rtl_files(tmp_path)) == {current, macro}
    assert S.authoritative_rtl_files(tmp_path) == [current]


def test_isolated_installed_file_load_keeps_the_current_source_scope(tmp_path):
    programs = Path(__file__).resolve().parents[1]
    installed = tmp_path / "installed/programs"
    installed.mkdir(parents=True)
    # Preserve the installed sibling-module closure, without a checkout or
    # inherited PYTHONPATH supplying dependencies for the path-based loader.
    for source in programs.glob("*.py"):
        shutil.copyfile(source, installed / source.name)
    current = tmp_path / "project/phase2/stage1/rtl/current.v"
    history = tmp_path / "project/phase2/stage1/formal_history/old.v"
    for path in [current, history]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("module leaf(); endmodule\n")
    code = (
        "import importlib.util,json,pathlib\n"
        f"source=pathlib.Path({str(installed / 'rtl_scan_scope.py')!r})\n"
        "spec=importlib.util.spec_from_file_location('isolated_scope',source)\n"
        "module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)\n"
        f"project=pathlib.Path({str(tmp_path / 'project')!r})\n"
        "print(json.dumps([str(p.relative_to(project)) for p in module.authoritative_rtl_files(project)]))\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["phase2/stage1/rtl/current.v"]
