"""Tests for tool_substitution_disclose.py (open-benchmark-methodology § 3)."""
from __future__ import annotations

import tool_substitution_disclose as mod


def test_all_emits_full_table_pass():
    rc = mod.main(["--all"])
    assert rc == 0


def test_mandated_matches_vcs_and_xcelium_pass():
    rows, unmatched = mod._rows_for("Synopsys VCS,Xcelium")
    names = [r["mandated"] for r in rows]
    assert "Synopsys VCS sim" in names
    assert "Cadence Xcelium" in names
    assert unmatched == []
    rc = mod.main(["--mandated", "Synopsys VCS,Xcelium"])
    assert rc == 0


def test_unknown_mandated_tool_honest_fail():
    # No canonical row for a tool we have no entry for → FAIL, emit nothing.
    rc = mod.main(["--mandated", "MentorQuesta"])
    assert rc == 1


def test_render_table_contains_caveats():
    rows, _ = mod._rows_for(None)
    table = mod.render_table(rows)
    assert "We substitute" in table
    assert "iverilog 12" in table
    assert "yosys + OpenROAD" in table.replace("\n", " ")


def test_verify_missing_result_md_fail(tmp_path):
    rc = mod.main(["--verify", str(tmp_path / "nope.md"), "--mandated", "VCS"])
    assert rc == 1


def test_verify_empty_result_md_fail(tmp_path):
    p = tmp_path / "RESULT.md"
    p.write_text("   \n")
    rc = mod.main(["--verify", str(p), "--mandated", "VCS"])
    assert rc == 1


def test_verify_present_disclosure_pass(tmp_path):
    p = tmp_path / "RESULT.md"
    p.write_text("We substitute iverilog 12 for Synopsys VCS sim.\n")
    rc = mod.main(["--verify", str(p), "--mandated", "Synopsys VCS"])
    assert rc == 0


def test_verify_missing_disclosure_fail(tmp_path):
    # Used VCS but the substitute string is absent → FAIL.
    p = tmp_path / "RESULT.md"
    p.write_text("This run used the golden testbench only.\n")
    rc = mod.main(["--verify", str(p), "--mandated", "Synopsys VCS"])
    assert rc == 1


def test_json_report_written(tmp_path):
    out = tmp_path / "r.json"
    rc = mod.main(["--all", "--json", str(out)])
    assert rc == 0
    import json
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
    assert "Synopsys VCS sim" in rep["emitted_rows"]
