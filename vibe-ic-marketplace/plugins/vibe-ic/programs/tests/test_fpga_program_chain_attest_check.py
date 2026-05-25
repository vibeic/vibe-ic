"""Tests for fpga_program_chain_attest_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "fpga_program_chain_attest_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _write_manifest(tmp_path: Path, entries):
    p = tmp_path / "latest_results.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return p


def _good_chain(session="abcd-1234", sha="sha256:" + "f" * 64):
    return [
        {"timestamp": "2026-04-27T10:00:00Z",
         "step": "fpga_compile", "status": "PASS",
         "session_id": session, "compiled_artifact_sha256": sha},
        {"timestamp": "2026-04-27T10:01:00Z",
         "step": "fpga_program", "status": "PASS",
         "session_id": session, "programmed_artifact_sha256": sha,
         "compile_artifact_sha256": sha,
         "program_matches_compile": True},
        {"timestamp": "2026-04-27T10:02:00Z",
         "step": "device_tester_md905_connect_test", "status": "PASS",
         "session_id": session},
    ]


def test_good_chain_passes(tmp_path):
    p = _write_manifest(tmp_path, _good_chain())
    rc, out, err = _run(["--manifest", str(p)])
    assert rc == 0, f"stdout={out} stderr={err}"


def test_missing_compile_fails(tmp_path):
    chain = _good_chain()
    chain = [e for e in chain if e["step"] != "fpga_compile"]
    p = _write_manifest(tmp_path, chain)
    rc, out, err = _run(["--manifest", str(p)])
    assert rc == 1
    assert "missing_compile_pass" in out


def test_missing_program_fails(tmp_path):
    chain = _good_chain()
    chain = [e for e in chain if e["step"] != "fpga_program"]
    p = _write_manifest(tmp_path, chain)
    rc, out, err = _run(["--manifest", str(p)])
    assert rc == 1
    assert "missing_program_pass" in out


def test_session_mismatch_fails(tmp_path):
    chain = _good_chain()
    chain[1]["session_id"] = "different-session"
    p = _write_manifest(tmp_path, chain)
    rc, out, err = _run(["--manifest", str(p)])
    assert rc == 1
    assert "session_mismatch" in out


def test_artifact_hash_mismatch_fails(tmp_path):
    chain = _good_chain()
    chain[1]["programmed_artifact_sha256"] = "sha256:" + "0" * 64
    p = _write_manifest(tmp_path, chain)
    rc, out, err = _run(["--manifest", str(p)])
    assert rc == 1
    assert "artifact_hash_mismatch" in out


def test_connect_test_before_program_fails(tmp_path):
    """The killer case: connect_test PASSes before our program ran."""
    chain = _good_chain()
    # Move connect_test to BEFORE program (i.e. it was a stale rig PASS)
    chain[2]["timestamp"] = "2026-04-27T09:00:00Z"
    p = _write_manifest(tmp_path, chain)
    rc, out, err = _run(["--manifest", str(p)])
    assert rc == 1
    assert "connect_test_before_program" in out


def test_json_output(tmp_path):
    p = _write_manifest(tmp_path, _good_chain())
    out_path = tmp_path / "report.json"
    rc, _, _ = _run(["--manifest", str(p), "--json", str(out_path)])
    assert rc == 0
    data = json.loads(out_path.read_text())
    assert data["verdict"] == "PASS"
    assert data["errors"] == 0


def test_json_stdout(tmp_path):
    p = _write_manifest(tmp_path, _good_chain())
    rc, out, _ = _run(["--manifest", str(p), "--json"])
    assert rc == 0
    data = json.loads(out)
    assert data["verdict"] == "PASS"
