#!/usr/bin/env python3
"""Tests for assertion_property_check.py"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "assertion_property_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_valid_assertion(tmp_path):
    sva = tmp_path / "assertions.sv"
    sva.write_text("module assert_mod;\n  property p_valid;\n    @(posedge clk) req |-> ##[1:3] ack;\n  endproperty\n  assert property (p_valid);\n  property p_reset;\n    @(posedge clk) disable iff (!rst_n) data_valid |-> !data_err;\n  endproperty\n  assert property (p_reset);\n  wire a, b, c, d;\n  wire e, f;\nendmodule\n")
    r = _run([str(tmp_path), "--json"])
    assert r.returncode == 0

def test_no_assertion_candidate_is_inapplicable_not_a_defect(tmp_path):
    """DFT_FCC / 5-d1 — CORRECTED EXPECTATION (was `assert rc == 1`, under
    the name test_fail_no_assertion_files).

    The old expectation was written while this program was an ORPHAN:
    declared in step 5's `programs:` list but invoked by nothing, so its
    exit code had no gate consequence and "1 for everything unhappy" cost
    nothing.  Now that the program is WIRED into step 5's gate `all_of`,
    rc=1 means "step 5 FAILS".  Applying it to a project that simply has
    no assertion candidate anywhere would convert the #608 honest
    SKIPPED-CONDITION (no formal/assertion harness authored yet) into a
    hard FAIL — a different defect, not a fix.  rc=2 is the flow-wide
    "input not applicable" convention that `_check_program_exit_zero`
    maps to VACUOUS_PASS.

    This is NOT a relaxation: `test_candidate_without_property_is_still_a_
    defect` below pins rc == 1 the moment any candidate file exists.
    """
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 2, r.stdout + r.stderr

def test_fail_stub_file(tmp_path):
    sva = tmp_path / "stub.sva"
    sva.write_text("// stub\nassert property (p);\n")
    r = _run([str(tmp_path), "--json"])
    assert r.returncode == 1


# ---------------------------------------------------------------------------
# DFT_FCC / 5-d1 — discriminators for the rc split and the --json path form.
# ---------------------------------------------------------------------------
_VALID = (
    "module m_sva;\n"
    "  property p_a;\n    @(posedge clk) req |-> ##[1:3] ack;\n  endproperty\n"
    "  assert property (p_a);\n"
    "  property p_b;\n    @(posedge clk) x |-> y;\n  endproperty\n"
    "  assert property (p_b);\n"
    "  wire a, b, c, d;\n  wire e, f, g;\n"
    "endmodule\n"
)


def test_candidate_without_property_is_still_a_defect(tmp_path):
    """DIRECTION-1 GUARD + discriminator.

    The moment an assertion candidate EXISTS, a missing `property`
    declaration / `assert property` statement stays rc=1.  rc=2 must never
    leak into this case — that would be exactly the loosening the rc split
    exists to avoid.
    """
    (tmp_path / "sva.sv").write_text(
        "module m;\n"
        + "".join(f"  wire w{i};\n" for i in range(14))
        + "  always @(posedge clk) assert (w0 == 1'b0);\n"
        "endmodule\n"
    )
    r = _run([str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert ("NO_ASSERT_PROPERTY" in r.stdout) or ("NO_PROPERTY_DECL" in r.stdout)


def test_json_path_form_writes_a_dereferenceable_artefact(tmp_path):
    """`--json <path>` must write the report where the gate declares it.

    Every WIRED gate in the flow yaml writes an evidence artefact; while
    `--json` was a bare stdout boolean, wiring this gate would have
    produced a verdict with no dereferenceable evidence behind it.
    """
    (tmp_path / "sva.sv").write_text(_VALID)
    out = tmp_path / "reports/phase2/gates/assertion_property.json"
    r = _run([str(tmp_path), "--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.is_file(), "gate evidence artefact was not written"
    payload = json.loads(out.read_text())
    assert payload["program"] == "assertion_property_check"
    assert payload["passed"] is True
    assert payload["applicable"] is True


def test_json_path_relative_to_project(tmp_path):
    """A relative --json path resolves under the audited project — the shape
    the yaml gate uses (`assertion_property_check . --json reports/…`,
    invoked with cwd=<project>)."""
    (tmp_path / "sva.sv").write_text(_VALID)
    r = _run([".", "--json", "reports/phase2/gates/assertion_property.json"],
             cwd=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "reports/phase2/gates/assertion_property.json").is_file()


def test_bare_json_flag_still_prints_to_stdout(tmp_path):
    """DIRECTION-1 GUARD — the historical bare `--json` stdout form must keep
    working; it is what the docstring and the sibling tests document."""
    (tmp_path / "sva.sv").write_text(_VALID)
    r = _run([str(tmp_path), "--json"])
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["program"] == "assertion_property_check"


def test_inapplicable_report_records_applicable_false(tmp_path):
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    out = tmp_path / "a.json"
    r = _run([str(tmp_path), "--json", str(out)])
    assert r.returncode == 2
    payload = json.loads(out.read_text())
    assert payload["applicable"] is False
    assert payload["passed"] is False


def test_missing_project_dir_is_a_defect_not_an_inapplicable_input(tmp_path):
    """DIRECTION-1 GUARD — a non-existent project directory stays rc=1.
    Routing it through rc=2 would let a mis-pathed gate vacuously pass."""
    r = _run([str(tmp_path / "does_not_exist")])
    assert r.returncode == 1, r.stdout + r.stderr
