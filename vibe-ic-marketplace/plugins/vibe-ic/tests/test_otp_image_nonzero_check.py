"""Wave 72 — verify upgraded 3-case messaging in otp_image_nonzero_check.py.

The gate must distinguish:
    1. present + non-zero at payload addrs → PASS
    2. present + all-zero at payload addrs → FAIL (stub-shape message)
    3. missing entirely (layout declared)  → FAIL (stage vendor data hint)
    4. no layout declared                  → SKIP
"""
import json
import subprocess
import sys
from pathlib import Path

PROGRAM = Path(__file__).resolve().parent.parent / "programs" / "otp_image_nonzero_check.py"


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
