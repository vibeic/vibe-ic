"""ORGANIC #591 — l9_rtl_pin_consistency_check's PASS line printed only
the deduped pin count ("agree on 46 pins" against a 47-entry contract):
the silent per-entry skip made the evidence line disagree with the
artifact it certifies, and at larger drift a real one-pin mismatch could
hide inside a PASS.

Fix: extract_l9_ports_with_audit() returns (ports, skipped[{entry,
reason}]); the PASS line reads "agree on N/TOTAL pins (K skipped:
duplicate 'x'; ...)"; unknown-reason skips WARN.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import l9_rtl_pin_consistency_check as G  # noqa: E402


def test_audit_reports_duplicate():
    ports, skipped = G.extract_l9_ports_with_audit({
        "top_ports": [
            {"name": "clk_i", "direction": "input"},
            {"name": "clk_i", "direction": "input"},   # duplicate
            {"name": "rst_ni", "direction": "input"},
        ],
    })
    assert len(ports) == 2
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "duplicate 'clk_i'"


def test_audit_reports_unparseable():
    ports, skipped = G.extract_l9_ports_with_audit({
        "top_ports": [
            {"name": "a", "direction": "input"},
            {"direction": "output"},            # no name
            "just_a_string",                    # not a dict
        ],
    })
    assert len(ports) == 1
    reasons = sorted(s["reason"] for s in skipped)
    assert any("no name field" in r for r in reasons)
    assert any("not a dict" in r for r in reasons)


def test_dual_key_mirror_counts_as_duplicate():
    """The #490 dual-write (same pins under two keys) is the canonical
    benign-duplicate source — audit names it, port set unchanged."""
    pins = [{"name": "d", "direction": "input"}]
    ports, skipped = G.extract_l9_ports_with_audit({
        "top_ports": pins, "top_module_pins": pins,
    })
    assert len(ports) == 1
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "duplicate 'd'"


def test_extract_l9_ports_wrapper_unchanged():
    """#490 regression: the legacy single-return API yields the same
    deduped port set (one parser, no drift)."""
    l9 = {"top_ports": [{"name": "x", "direction": "input"},
                        {"name": "x", "direction": "input"}]}
    assert G.extract_l9_ports(l9) == G.extract_l9_ports_with_audit(l9)[0]


# ── end-state: the PASS evidence line is honest ─────────────────────────────

def _project(tmp_path: Path) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    # The issue's exact shape: 47-entry-style contract with one
    # duplicate (here 4 entries, 1 dup → compared 3, total 4) + a
    # whitespace-variant name (distinct → compared, per the issue's
    # fixture request).
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [
            {"name": "clk_i", "direction": "input"},
            {"name": "clk_i", "direction": "input"},      # duplicate
            {"name": "rst_ni", "direction": "input"},
            {"name": "data_o ", "direction": "output"},   # ws-variant
        ],
    }))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.v").write_text(
        "module chip_top (\n"
        "  input wire clk_i,\n"
        "  input wire rst_ni,\n"
        "  output wire [7:0] data_o \n"
        ");\n"
        "endmodule\n"
    )
    return tmp_path


def test_pass_line_reports_total_and_skips(tmp_path):
    proj = _project(tmp_path)
    result = subprocess.run(
        [sys.executable, str(PROG / "l9_rtl_pin_consistency_check.py"),
         str(proj)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout
    out = result.stdout
    assert "PASS" in out
    # honest count: compared/total + the named duplicate
    assert "/4 pins" in out, out
    assert "duplicate 'clk_i'" in out, out
