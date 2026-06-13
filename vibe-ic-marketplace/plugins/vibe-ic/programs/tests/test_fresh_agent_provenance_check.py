"""Unit tests for fresh_agent_provenance_check.py."""
import sys
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "fresh_agent_provenance_check.py"
assert SCRIPT.exists()


def _run(rtl_dir: Path, ref_dir: Path) -> str:
    return subprocess.check_output(
        [sys.executable, str(SCRIPT), str(rtl_dir), str(ref_dir)],
        text=True,
    )


def test_identical_copy_labeled_copied(tmp_path):
    ref = tmp_path / "ref"
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    ref.mkdir(parents=True, exist_ok=True); rtl.mkdir(parents=True, exist_ok=True)
    (ref / "mod.v").write_text("module mod; endmodule\n")
    (rtl / "mod.v").write_text("module mod; endmodule\n")
    out = _run(rtl, ref)
    assert "[COPIED]" in out
    assert "reference-reuse" in out.lower()


def test_modified_label(tmp_path):
    ref = tmp_path / "ref"
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    ref.mkdir(parents=True, exist_ok=True); rtl.mkdir(parents=True, exist_ok=True)
    (ref / "m.v").write_text(
        "\n".join([f"assign x{i} = 1'b0;" for i in range(20)]) + "\n"
    )
    # Modify 1 line out of 20 → 95% overlap
    modified = "\n".join([f"assign x{i} = 1'b0;" for i in range(19)]) + "\nassign y = 1'b1;\n"
    (rtl / "m.v").write_text(modified)
    out = _run(rtl, ref)
    assert "[MODIFIED" in out


def test_fully_distinct_labeled_spec_generated(tmp_path):
    ref = tmp_path / "ref"
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    ref.mkdir(parents=True, exist_ok=True); rtl.mkdir(parents=True, exist_ok=True)
    (ref / "alpha.v").write_text("module alpha; reg [7:0] data; endmodule\n")
    (rtl / "beta.v").write_text("module beta; reg [31:0] counter; assign out = counter == 0; endmodule\n")
    out = _run(rtl, ref)
    assert "[SPEC-GENERATED]" in out
    assert "spec-generation PASS" in out or "hybrid PASS" in out


def test_empty_rtl_dir_is_ok(tmp_path):
    ref = tmp_path / "ref"
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    ref.mkdir(parents=True, exist_ok=True); rtl.mkdir(parents=True, exist_ok=True)
    (ref / "x.v").write_text("module x; endmodule\n")
    # No RTL files → no records → summary "for 0 files"
    out = _run(rtl, ref)
    assert "Provenance summary for 0 files" in out
