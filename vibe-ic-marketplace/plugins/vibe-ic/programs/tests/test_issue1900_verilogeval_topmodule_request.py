"""Regression coverage for #1900 explicit design-request module names."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as P  # noqa: E402
import _progress_run as _pr  # noqa: E402


_INTAKE_FIXTURE = (
    Path(__file__).resolve().parent
    / "phase1_fixtures"
    / "verilogeval_v2_topmodule"
    / "Prob001_zero_prompt.txt"
)


def test_issue1900_intake_fixture_extracts_case_preserving_topmodule():
    text = _INTAKE_FIXTURE.read_text(encoding="utf-8")
    assert P._extract_top_module_from_docs({_INTAKE_FIXTURE.name: text}) == "TopModule"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Implement a module named packet_router.", "packet_router"),
        ("Please create a Verilog module called `crc_core`.", "crc_core"),
        ("Could you please write an RTL top-level module named 'BusTop'?", "BusTop"),
        ('Your task is to define the module named "ControlTop".', "ControlTop"),
    ],
)
def test_explicit_design_request_forms(text, expected):
    assert P._extract_top_module_from_docs({"prompt.txt": text}) == expected


@pytest.mark.parametrize(
    "text",
    [
        "This guide explains how to implement a module named tutorial_example.",
        "The package contains a module named subordinate_block for testing.",
        "Do not implement a module named forbidden_example.",
        "Implement a module named retired_top is no longer required.",
        "The prose asks whether one could implement a module named hypothetical.",
        "// Implement a module named commented_line_top.",
        "/* Please create a module called commented_block_top. */",
    ],
)
def test_narrative_or_negated_module_named_text_is_not_design_intent(text):
    assert P._extract_top_module_from_docs({"notes.md": text}) is None


def test_explicit_implementation_target_outranks_reference_declaration():
    docs = {
        "prompt.txt": "Please implement a module named RequestedTop.",
        "existing.sv": "module actual_top(input logic clk); endmodule",
    }
    assert P._extract_top_module_from_docs(docs) == "RequestedTop"


def test_verilogeval_reference_parent_does_not_override_requested_submodule():
    docs = {
        "prompt.txt": (
            "I would like you to implement a module named TopModule with the following\n"
            "interface.\n\n"
            "Consider this Verilog module full_module:\n"
            "module full_module(input [2:0] r, output reg [2:0] q);\n"
            "endmodule\n"
        ),
    }
    assert P._extract_top_module_from_docs(docs) == "TopModule"


def test_direct_implementation_request_outranks_conflicting_label():
    docs = {
        "prompt.txt": "Please implement a module named RequestedTop.\n"
        "Module Name: FormalTop\n",
    }
    assert P._extract_top_module_from_docs(docs) == "RequestedTop"


def test_contrastive_exclusion_does_not_negate_requested_target():
    docs = {
        "prompt.txt": (
            "Please implement a module named TopModule, not LegacyTop."
        ),
    }
    assert P._extract_top_module_from_docs(docs) == "TopModule"


def test_conflicting_direct_requests_fail_loudly_instead_of_tie_breaking():
    docs = {
        "prompt.txt": (
            "Please implement a module named AHelper.\n"
            "Please implement a module named Helper.\n"
        ),
    }
    with pytest.raises(ValueError, match="conflicting direct module targets"):
        P._extract_top_module_from_docs(docs)


def test_conflicting_direct_requests_on_one_line_fail_loudly():
    docs = {
        "prompt.txt": (
            "Please implement a module named ZTop. "
            "Please implement a module named AHelper."
        ),
    }
    with pytest.raises(ValueError, match="conflicting direct module targets"):
        P._extract_top_module_from_docs(docs)


def test_semicolon_separated_direct_requests_fail_loudly():
    docs = {
        "prompt.txt": (
            "Please implement a module named ZTop; "
            "please implement a module named AHelper."
        ),
    }
    with pytest.raises(ValueError, match="conflicting direct module targets"):
        P._extract_top_module_from_docs(docs)


def test_issue1900_phase1_emits_topmodule_into_l9(tmp_path):
    project = tmp_path / "project"
    input_dir = project / "input"
    input_dir.mkdir(parents=True)
    input_dir.joinpath("phase1_prompt.md").write_text(
        _INTAKE_FIXTURE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = _pr.run(
        [sys.executable, str(_PROGRAMS / "phase1_one_shot_runner.py"), str(project)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-1200:]

    l9_path = project / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    l9 = json.loads(l9_path.read_text(encoding="utf-8"))
    assert l9.get("top_module") == "TopModule", l9.get("top_module")
