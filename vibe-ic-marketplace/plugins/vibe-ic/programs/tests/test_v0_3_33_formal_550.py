"""ORGANIC #550 — formal_proof_evidence_check: sby [files] staging
(src/<basename>) resolution + multi-flag read-line parsing.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import formal_proof_evidence_check as F  # noqa: E402


# ── (b) multi-flag read line captures the FILE, not a -flag ────────────────
def test_550b_multiflag_read_captures_file():
    assert F._sby_file_refs(
        "[script]\nread_verilog -sv -DPROP1 -DPROP2 dut.sv\n") == ["dut.sv"]
    assert F._sby_file_refs("[script]\nread -formal dut.sv\n") == ["dut.sv"]
    # several reads + a files section, de-duped in order
    refs = F._sby_file_refs(
        "[script]\nread_verilog -sv a.sv\nread_verilog -formal -DX b.sv\n"
        "[files]\nrtl/c.sv\n")
    assert refs == ["a.sv", "b.sv", "rtl/c.sv"]


# ── (a) staged src/<basename> resolution ───────────────────────────────────
def _formal(tmp_path):
    d = tmp_path / "phase2" / "stage1" / "formal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_550a_staged_src_basename_resolves(tmp_path):
    fdir = _formal(tmp_path)
    # the original rtl/aes.sv was consumed; sby staged it under task/src/
    staged = fdir / "aes_proof" / "src"
    staged.mkdir(parents=True)
    (staged / "aes.sv").write_text("module aes; endmodule\n")
    # #418 signature: the .sby's OWN directory is the primary base. For a
    # top-level .sby that IS fdir, so #550(a) is unchanged by that change.
    r = F._resolve(fdir, fdir, tmp_path, "rtl/aes.sv")
    assert r is not None and r.name == "aes.sv"


def test_550a_genuinely_missing_still_none(tmp_path):
    fdir = _formal(tmp_path)
    # NEGATIVE: a ref with no source anywhere (neither original nor staged)
    assert F._resolve(fdir, fdir, tmp_path, "rtl/ghost.sv") is None


# ── end-to-end: a real staged+multi-flag proof PASSes; a bare claim FAILs ──
def test_550_end_to_end_pass(tmp_path):
    fdir = _formal(tmp_path)
    (fdir / "results.json").write_text(json.dumps({
        "verdict": "PASS", "all_proved": True,
        "property_denominator": 1, "authored_property_count": 1,
        "unresolved_obligations": [],
        "bounded_vs_unbounded_scope": ["unbounded prove"],
        "sby": "phase2/stage1/formal/p.sby",
        "elaborated_sby": "phase2/stage1/formal/p.sby",
        "evidence": "phase2/stage1/formal/p.log",
        "proof_transcript": "phase2/stage1/formal/p.log",
    }))
    (fdir / "p.sby").write_text(
        "[options]\nmode prove\n[engines]\nsmtbmc\n"
        "[script]\nread_verilog -sv -DFORMAL dut.sv\nprep -top dut\n"
        "[files]\nrtl/dut.sv\n")
    # both refs (dut.sv via read, rtl/dut.sv via files) resolve via staging
    src = fdir / "p" / "src"
    src.mkdir(parents=True)
    (src / "dut.sv").write_text("module dut; endmodule\n")
    (fdir / "p.log").write_text(
        "SBY 0.40\nsmtbmc engine_0\nsummary: Elapsed 1s\n"
        "DONE (PASS, rc=0)\n")
    rep = F.audit(tmp_path)
    assert rep["verdict"] == "PASS", rep


def test_550_negative_no_log_fails(tmp_path):
    fdir = _formal(tmp_path)
    (fdir / "results.json").write_text(json.dumps({"all_proved": True}))
    (fdir / "p.sby").write_text(
        "[script]\nread_verilog -sv dut.sv\n[files]\nrtl/dut.sv\n")
    src = fdir / "p" / "src"
    src.mkdir(parents=True)
    (src / "dut.sv").write_text("module dut; endmodule\n")
    # NEGATIVE: all_proved claimed but NO SymbiYosys PASS transcript → FAIL
    rep = F.audit(tmp_path)
    assert rep["verdict"] == "FAIL"
