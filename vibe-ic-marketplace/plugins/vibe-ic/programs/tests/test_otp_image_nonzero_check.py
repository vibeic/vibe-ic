"""Wave 72 — verify upgraded 3-case messaging in otp_image_nonzero_check.py.

The gate must distinguish:
    1. present + non-zero at payload addrs → PASS
    2. present + all-zero at payload addrs → FAIL (stub-shape message)
    3. missing entirely (layout declared)  → FAIL (stage vendor data hint)
    4. no layout declared                  → SKIP
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PROGRAM = Path(__file__).resolve().parent.parent / "otp_image_nonzero_check.py"


def _scaffold(tmp_path: Path, layout: bool, image_bytes: bytes | None) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    if layout:
        l11 = {
            "doc_class": "otp_content",
            "otp_bytes": [
                {"addr": 0, "section": "ID[0]", "value": 0xF2},
                {"addr": 1, "section": "ID[1]", "value": 0x01},
            ],
        }
        (proj / "phase1" / "generated_docs" / "L11_OTP_CONTENT.json").write_text(
            json.dumps(l11))
    if image_bytes is not None:
        (proj / "input" / "otp").mkdir(parents=True)
        # Write as $readmemh hex (one byte per line)
        text = "\n".join(f"{b:02x}" for b in image_bytes) + "\n"
        (proj / "input" / "otp" / "image.hex").write_text(text)
    return proj


def _run(proj: Path) -> tuple[int, str]:
    cp = subprocess.run([sys.executable, str(PROGRAM), str(proj)],
                        capture_output=True, text=True, timeout=30)
    return cp.returncode, cp.stdout + cp.stderr


def test_present_nonzero_pass(tmp_path):
    proj = _scaffold(tmp_path, layout=True, image_bytes=bytes([0xF2, 0x01]))
    rc, out = _run(proj)
    assert rc == 0
    assert "[PASS]" in out


def test_present_all_zero_fail_with_stub_hint(tmp_path):
    proj = _scaffold(tmp_path, layout=True, image_bytes=bytes(64))  # 64 zeros
    rc, out = _run(proj)
    assert rc == 1
    assert "[FAIL]" in out
    # Stub-shape hint
    assert "stub" in out.lower() or "all-zero stub" in out.lower()
    assert "input/otp/" in out


def test_missing_image_fails_with_actionable_hint(tmp_path):
    """Layout declared but no .hex/.mif exists — used to SKIP, now FAILs."""
    proj = _scaffold(tmp_path, layout=True, image_bytes=None)
    rc, out = _run(proj)
    assert rc == 1
    assert "[FAIL]" in out
    assert "no .hex" in out or "no image is staged" in out
    assert "input/otp/" in out


def test_no_layout_skips(tmp_path):
    proj = _scaffold(tmp_path, layout=False, image_bytes=None)
    rc, out = _run(proj)
    assert rc == 0
    assert "[SKIP]" in out


# ---------------------------------------------------------------------------
# ORGANIC-20260530-otp-image-check-symlink-crash
# When the project's input/ tree is a symlink to a shared location OUTSIDE
# the project subtree (a space-saving staging pattern), the resolved image
# path lands outside `project`, so the old f.relative_to(project) report-line
# call raised ValueError and crashed the gate with a traceback (false-negative
# masking a perfectly valid non-zero image). The gate must now degrade
# gracefully and return its real verdict.
# ---------------------------------------------------------------------------


def _scaffold_symlinked_input(tmp_path: Path, image_bytes: bytes) -> Path:
    """Build a project where input/ is a symlink to a sibling dir that lives
    OUTSIDE the project root. Layout is declared; a .hex is staged through the
    symlink. Returns the project dir."""
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    l11 = {
        "doc_class": "otp_content",
        "otp_bytes": [
            {"addr": 0, "section": "ID[0]", "value": 0xF2},
            {"addr": 1, "section": "ID[1]", "value": 0x01},
        ],
    }
    (proj / "phase1" / "generated_docs" / "L11_OTP_CONTENT.json").write_text(
        json.dumps(l11))

    # Shared source dir is a SIBLING of proj (outside the project subtree).
    shared = tmp_path / "shared_input"
    (shared / "otp").mkdir(parents=True)
    text = "\n".join(f"{b:02x}" for b in image_bytes) + "\n"
    (shared / "otp" / "image.hex").write_text(text)

    # proj/input -> ../shared_input  (so proj/input/otp/image.hex resolves
    # to tmp_path/shared_input/otp/image.hex, outside proj).
    os.symlink(shared, proj / "input")
    return proj


def test_symlinked_input_nonzero_pass_no_crash(tmp_path):
    """input/ symlinked outside project, valid non-zero image → PASS (exit 0),
    NOT a ValueError traceback."""
    proj = _scaffold_symlinked_input(tmp_path, bytes([0xF2, 0x01]))
    rc, out = _run(proj)
    assert "Traceback" not in out, out
    assert "ValueError" not in out, out
    assert rc == 0, out
    assert "[PASS]" in out, out


def test_symlinked_input_all_zero_still_fails(tmp_path):
    """Verdict logic unchanged: an all-zero image staged through the same
    symlinked input/ must still FAIL (exit 1) — the fix only hardens path
    formatting, it does not relax the check."""
    proj = _scaffold_symlinked_input(tmp_path, bytes(64))  # 64 zeros
    rc, out = _run(proj)
    assert "Traceback" not in out, out
    assert rc == 1, out
    assert "[FAIL]" in out, out
