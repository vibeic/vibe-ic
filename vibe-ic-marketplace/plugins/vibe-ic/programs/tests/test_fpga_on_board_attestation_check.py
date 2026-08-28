"""Unit tests for fpga_on_board_attestation_check.py."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

SCRIPT = Path(__file__).parent.parent / "fpga_on_board_attestation_check.py"
assert SCRIPT.exists()


def _run(project: Path):
    return _pr.run(
        [sys.executable, str(SCRIPT), str(project)],
        capture_output=True, text=True)


def _sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _setup_full(project: Path, n_scen: int = 4, bad_hash: bool = False):
    """Create the full set of required evidence. Optional: bad_hash to flip one field."""
    (project / "phase2" / "stage1" / "fpga" / "final").mkdir(parents=True)
    sof = project / "phase2" / "stage1" / "fpga" / "final" / "design.sof"
    sof.write_bytes(b"MOCK_BITSTREAM" * 500)
    real_sha = _sha(sof.read_bytes())

    (project / "reports" / "phase2" / "fpga").mkdir(parents=True)
    (project / "reports" / "phase2" / "fpga" / "on_board_pass.json").write_text(json.dumps({
        "all_scenarios_passed": True,
        "bitstream_path": "phase2/stage1/fpga/final/design.sof",
        "bitstream_sha": real_sha if not bad_hash else "sha256:ffff",
        "board": "DE10-Lite 10M50DAF484C7G",
        "programmed_at": "2026-04-22T10:00:00Z",
        "scenarios": [{"name": f"scen{i}", "result": "pass"} for i in range(n_scen)],
    }))
    # Tool log
    (project / "reports" / "phase2" / "fpga" / "quartus_pgm.log").write_text(
        "Quartus Prime Programmer was successful\n"
        "Info: JTAG chain detected: USB-Blaster\n"
        "Info: Device detected: 10M50DAF484\n"
        "Info: Configuration succeeded\n"
    )
    # Non-JSON evidence
    (project / "reports" / "phase2" / "fpga" / "on_board_evidence").mkdir(parents=True)
    (project / "reports" / "phase2" / "fpga" / "on_board_evidence" / "led_pass.jpg").write_bytes(
        b"\xff\xd8\xff\xe0mock-jpg"
    )


def test_full_evidence_passes(tmp_path):
    _setup_full(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_pure_json_fails(tmp_path):
    """Only on_board_pass.json with JSON claim — classic cheating pattern."""
    (tmp_path / "reports" / "phase2" / "fpga").mkdir(parents=True)
    (tmp_path / "reports" / "phase2" / "fpga" / "on_board_pass.json").write_text(json.dumps({
        "all_scenarios_passed": True,
        "bitstream_path": "fpga/final/design.sof",
        "bitstream_sha": "sha256:fake",
        "board": "DE10-Lite",
        "programmed_at": "2026-04-22T10:00:00Z",
        "scenarios": [{"name": "s1", "result": "pass"}],
    }))
    r = _run(tmp_path)
    assert r.returncode == 1


def test_hash_mismatch_fails(tmp_path):
    _setup_full(tmp_path, bad_hash=True)
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "hash" in (r.stdout + r.stderr).lower()


def test_missing_programmer_log_fails(tmp_path):
    _setup_full(tmp_path)
    (tmp_path / "reports" / "phase2" / "fpga" / "quartus_pgm.log").unlink()
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "programmer" in (r.stdout + r.stderr).lower()


def test_missing_hardware_evidence_fails(tmp_path):
    _setup_full(tmp_path)
    for p in (tmp_path / "reports" / "phase2" / "fpga" / "on_board_evidence").glob("*"):
        p.unlink()
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "evidence" in (r.stdout + r.stderr).lower()


def test_missing_scenarios_field_fails(tmp_path):
    _setup_full(tmp_path)
    pj = tmp_path / "reports" / "phase2" / "fpga" / "on_board_pass.json"
    data = json.loads(pj.read_text())
    del data["scenarios"]
    pj.write_text(json.dumps(data))
    r = _run(tmp_path)
    assert r.returncode == 1
