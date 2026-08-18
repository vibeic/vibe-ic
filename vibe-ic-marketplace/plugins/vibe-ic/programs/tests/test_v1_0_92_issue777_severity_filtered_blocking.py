"""ORGANIC #777 (P1) — rtl_hygiene_lint main() computed rc=1 from `all_findings`
(severity-INDEPENDENT) while stdout + the --json artifact use `filtered`
(>= --severity). At `--severity ERROR` (the canonical Step-2 lint gate) a
block-eligible WARN was FILTERED OUT of stdout+JSON yet STILL tripped rc=1 — an
INVISIBLE FAIL ('0 errors, 0 warnings, 0 info' + JSON '[]' + rc=1) that
cascade-blocked ~25 downstream steps with zero evidence. Regression of #770-r2
(commit 166e6aa05, which introduced the all_findings blocking line).

Fix: compute `blocking` from `filtered`, so rc=1 ALWAYS corresponds to a
printed + JSON'd finding.

§4.05 (this relaxes a gate — load-bearing): a real ERROR at --severity ERROR
still rc=1+visible; a block-eligible WARN at --severity WARN still rc=1+visible.
Only the below-threshold + invisible combination stops tripping a silent rc=1.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_LINT = _PROGRAMS / "rtl_hygiene_lint.py"

# A design whose only block-eligible finding is a WARN (uninit registered output
# + a clocked case-no-default). NO ERROR-severity finding.
_WARN_ONLY = (
    "module d(input clk, input [1:0] sel, output reg [3:0] o);\n"
    "  reg [3:0] acc;\n"
    "  always @(posedge clk) begin\n"
    "    case (sel)\n"
    "      2'd0: acc <= 4'd1;\n"
    "      2'd1: acc <= 4'd2;\n"
    "    endcase\n"
    "    o <= acc;\n"
    "  end\nendmodule\n")

# A design with a real ERROR-severity finding (undriven wire).
_ERROR_DESIGN = (
    "module e(input a, output b);\n"
    "  wire dangling;\n"
    "  assign b = a;\nendmodule\n")


def _run(tmp_path, src, severity, name="d.sv"):
    p = tmp_path / name
    p.write_text(src)
    jp = tmp_path / "out.json"
    proc = subprocess.run(
        [sys.executable, str(_LINT), "--severity", severity,
         "--json", str(jp), str(p)], capture_output=True, text=True)
    findings = json.loads(jp.read_text()) if jp.exists() else []
    return proc, findings


# ── NEW-PATH: a block-eligible WARN at --severity ERROR no longer trips a
# silent rc=1 (rc agrees with the empty stdout+JSON) ─────────────────────────
def test_777_warn_at_severity_error_no_invisible_rc1(tmp_path):
    proc, findings = _run(tmp_path, _WARN_ONLY, "ERROR")
    assert proc.returncode == 0, proc.stdout          # was an invisible rc=1
    assert findings == []                             # nothing printed/JSON'd
    assert "0 errors, 0 warnings, 0 info" in proc.stdout


# ── §4.05 no-leak A: the SAME WARN at --severity WARN is visible AND blocks ──
def test_777_noleak_warn_at_severity_warn_blocks_and_visible(tmp_path):
    proc, findings = _run(tmp_path, _WARN_ONLY, "WARN")
    assert proc.returncode == 1, proc.stdout
    warn = [f for f in findings if f["severity"] == "WARN" and f["block_eligible"]]
    assert warn, findings                             # rc=1 has a JSON'd finding


# ── §4.05 no-leak B: a real ERROR at --severity ERROR still blocks + visible ─
def test_777_noleak_real_error_at_severity_error_blocks(tmp_path):
    proc, findings = _run(tmp_path, _ERROR_DESIGN, "ERROR", name="e.sv")
    assert proc.returncode == 1, proc.stdout
    err = [f for f in findings if f["severity"] == "ERROR" and f["block_eligible"]]
    assert err, findings
    assert "undriven-wire" in proc.stdout


# ── invariant: every rc=1 corresponds to >=1 finding in the printed/JSON set ─
@pytest.mark.parametrize("src,sev,name", [
    (_WARN_ONLY, "ERROR", "a.sv"),
    (_WARN_ONLY, "WARN", "b.sv"),
    (_ERROR_DESIGN, "ERROR", "c.sv"),
    (_ERROR_DESIGN, "INFO", "d.sv"),
])
def test_777_rc1_implies_visible_finding(tmp_path, src, sev, name):
    proc, findings = _run(tmp_path, src, sev, name=name)
    if proc.returncode == 1:
        blocking = [f for f in findings
                    if f["block_eligible"] and f["severity"] in ("ERROR", "WARN")]
        assert blocking, (sev, findings)              # never an invisible rc=1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
