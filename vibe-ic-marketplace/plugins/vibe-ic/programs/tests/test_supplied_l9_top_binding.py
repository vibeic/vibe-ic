"""Front-door top binding for supplied wrapper RTL."""

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vibe_ic_one_shot_runner as RUNNER  # noqa: E402
import design_one_shot_runner as DESIGN  # noqa: E402


def _project(tmp_path: Path, *, l9_top: Optional[str] = "chip_top") -> Path:
    project = tmp_path / "subservient"
    rtl = project / "input" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.v").write_text(
        "module chip_top(input clk, output q);\n"
        "  subservient u_dut(.clk(clk), .q(q));\n"
        "endmodule\n"
    )
    (rtl / "subservient.v").write_text(
        "module subservient(input clk, output q); assign q = clk; endmodule\n"
    )
    if l9_top is not None:
        gd = project / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
            "top_module": l9_top,
            "top_module_status": "declared_in_input",
        }))
    return project


def test_l9_wrapper_does_not_override_explicit_top(tmp_path):
    project = _project(tmp_path)
    top, note = RUNNER._resolve_top_name(
        project, "subservient", "subservient", explicit=True)
    assert (top, note) == ("subservient", "")


def test_explicit_supplied_top_is_kept_without_source_bound_l9(tmp_path):
    project = _project(tmp_path, l9_top="not_declared")
    top, note = RUNNER._resolve_top_name(
        project, "product", "subservient", explicit=True)
    assert (top, note) == ("subservient", "")


def test_source_wrapper_binds_before_l9_is_emitted(tmp_path):
    project = _project(tmp_path, l9_top=None)
    top, note = RUNNER._resolve_top_name(
        project, "subservient", "subservient", explicit=True)
    assert top == "chip_top"
    assert "L9 not yet emitted" in note


def test_genuinely_different_explicit_top_is_kept(tmp_path):
    project = _project(tmp_path)
    top, note = RUNNER._resolve_top_name(
        project, "product", "subservient", explicit=True)
    assert (top, note) == ("subservient", "")


def test_stale_l9_declaration_fails_closed(tmp_path):
    project = _project(tmp_path, l9_top=None)
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "subservient",
    }))
    top, note = RUNNER._resolve_top_name(
        project, "subservient", "subservient", explicit=True)
    assert (top, note) == ("subservient", "")


def test_declared_leaf_l9_does_not_override_explicit_top(tmp_path):
    project = _project(tmp_path, l9_top=None)
    rtl = project / "input" / "rtl"
    (rtl / "chip_top.v").write_text(
        "module chip_top(input clk, output q); assign q = clk; endmodule\n"
    )
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_module_status": "declared_in_input",
    }))
    top, note = RUNNER._resolve_top_name(
        project, "subservient", "subservient", explicit=True)
    assert (top, note) == ("subservient", "")


def test_leaf_chip_top_is_not_inferred_as_a_wrapper(tmp_path):
    project = _project(tmp_path, l9_top=None)
    rtl = project / "input" / "rtl"
    (rtl / "chip_top.v").write_text(
        "module chip_top(input clk, output q); assign q = clk; endmodule\n"
    )
    (rtl / "subservient.v").write_text(
        "module subservient(input clk, output q); assign q = clk; endmodule\n"
    )
    top, note = RUNNER._resolve_top_name(
        project, "subservient", "subservient", explicit=True)
    assert (top, note) == ("subservient", "")


def test_sibling_child_does_not_make_leaf_chip_top_a_wrapper(tmp_path):
    project = _project(tmp_path, l9_top=None)
    rtl = project / "input" / "rtl"
    (rtl / "chip_top.v").write_text(
        "module chip_top(input clk, output q); assign q = clk; endmodule\n"
        "module helper(input clk, output q);\n"
        "  subservient u_dut(.clk(clk), .q(q));\n"
        "endmodule\n"
    )
    top, note = RUNNER._resolve_top_name(
        project, "subservient", "subservient", explicit=True)
    assert (top, note) == ("subservient", "")


def test_consume_keeps_source_bound_wrapper_in_cone(tmp_path):
    project = _project(tmp_path, l9_top=None)
    top, _ = RUNNER._resolve_top_name(
        project, "subservient", "subservient", explicit=True)
    result = DESIGN.step_reused_ip_consume(project, top)
    staged = project / "phase2" / "stage1" / "rtl"
    moved = project / "phase2" / "stage1" / "rtl_out_of_cone"
    assert result.status == "PASS"
    assert result.extras["cone_root"] == "chip_top"
    assert (staged / "chip_top.v").is_file()
    assert not (moved / "chip_top.v").exists()
