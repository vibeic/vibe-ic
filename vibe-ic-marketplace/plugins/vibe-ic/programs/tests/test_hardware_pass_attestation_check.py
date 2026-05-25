"""Tests for hardware_pass_attestation_check.py."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "hardware_pass_attestation_check.py"

sys.path.insert(0, str(PROG.parent))
import hardware_pass_attestation_check as _gate  # noqa: E402


def _setup(tmp: Path, l13: dict | None):
    d = tmp / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    if l13 is not None:
        (d / "L13_LAB_CALIBRATION.json").write_text(json.dumps(l13))
    return tmp


def _run(proj: Path):
    r = subprocess.run([sys.executable, str(PROG), str(proj)],
                       capture_output=True, text=True)
    try:
        return r.returncode, json.loads(r.stdout)
    except Exception:
        return r.returncode, {"_raw": r.stdout, "_err": r.stderr}


def test_known_pass_with_real_bytes_passes(tmp_path):
    _setup(tmp_path, {
        "tester": "USB-HID tester",
        "known_pass_bitstream": {"sof_path": "v037v2.sof", "sha256": "abc"},
        "known_pass_transcript": {
            "hid_tool_rx_bytes": "F2 02 02 02 02 02 BE AB BA D1 CD D0 D1 D2 AF CD CD D1 B5 AC D2 C1 B8 02 02 FA",
        },
    })
    code, out = _run(tmp_path)
    assert out.get("pass") is True, out
    assert code == 0


def test_padding_only_fails(tmp_path):
    _setup(tmp_path, {
        "tester": "USB-HID tester",
        "known_pass_bitstream": {"sof_path": "sim.sof"},
        "known_pass_transcript": {
            "hid_tool_rx_bytes": "00 00 0E 3A 02 02 02 02 02 02 02 02 02 02",
        },
    })
    code, out = _run(tmp_path)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "known_pass_transcript" in rules
    msg = next(f["message"] for f in out["findings"]
               if f["rule"] == "known_pass_transcript")
    assert "padding" in msg.lower()


def test_missing_l13_fails(tmp_path):
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    code, out = _run(tmp_path)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "l13_exists" in rules


def test_missing_bitstream_identity_fails(tmp_path):
    _setup(tmp_path, {
        "tester": "USB-HID tester",
        "known_pass_bitstream": {"capture_date": "2026-04-24"},   # no sof/sha/gds
        "known_pass_transcript": {
            "hid_tool_rx_bytes": "F2 BE AB BA D1 CD D0 D1 D2 FA",
        },
    })
    code, out = _run(tmp_path)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "known_pass_bitstream_identity" in rules


def test_missing_tester_warns_but_passes(tmp_path):
    _setup(tmp_path, {
        "known_pass_bitstream": {"sof_path": "v037v2.sof"},
        "known_pass_transcript": {
            "hid_tool_rx_bytes": "F2 BE AB BA D1 CD D0 D1 D2 FA",
        },
    })
    code, out = _run(tmp_path)
    # WARN only — should still pass
    assert out.get("pass") is True
    rules = [f.get("severity") for f in out["findings"]]
    # tester warning recorded
    assert any(sev == "WARN" for sev in rules)


# ---------------------------------------------------------------------------
# v0.56 B4: criterion registry — non-default criteria
# ---------------------------------------------------------------------------
def test_criterion_distinct_non_padding_explicit():
    tx = {"criterion": "distinct_non_padding_bytes",
          "hid_tool_rx_bytes": "F2 BE AB BA D1 CD"}
    ok, _ = _gate._known_pass_transcript_ok(tx)
    assert ok is True


def test_criterion_distinct_non_padding_padding_only_fails():
    tx = {"criterion": "distinct_non_padding_bytes",
          "hid_tool_rx_bytes": "02 02 02 02 02"}
    ok, msg = _gate._known_pass_transcript_ok(tx)
    assert ok is False and "padding" in msg


def test_criterion_distinct_non_padding_custom_padding_byte():
    tx = {"criterion": "distinct_non_padding_bytes",
          "criterion_params": {"padding_byte": "FF",
                                "min_distinct_non_padding": 3},
          "hid_tool_rx_bytes": "FF AA BB CC FF FF"}
    ok, _ = _gate._known_pass_transcript_ok(tx)
    assert ok is True


def test_criterion_monotonic_adc_sweep_pass():
    tx = {"criterion": "monotonic_adc_sweep",
          "samples_v_in_code_out": [
              [0.0, 0], [0.5, 16384], [1.0, 32767], [1.5, 49152], [2.0, 65535],
          ]}
    ok, _ = _gate._known_pass_transcript_ok(tx)
    assert ok is True


def test_criterion_monotonic_adc_sweep_non_monotonic_fails():
    tx = {"criterion": "monotonic_adc_sweep",
          "samples_v_in_code_out": [
              [0.0, 0], [0.5, 16384], [1.0, 8000], [1.5, 49152], [2.0, 65535],
          ]}
    ok, msg = _gate._known_pass_transcript_ok(tx)
    assert ok is False and "non-monotonic" in msg


def test_criterion_monotonic_adc_sweep_flat_fails():
    """All-same-code samples (DC input) must be rejected."""
    tx = {"criterion": "monotonic_adc_sweep",
          "samples_v_in_code_out": [
              [0.0, 12345], [0.5, 12345], [1.0, 12345],
              [1.5, 12345], [2.0, 12345],
          ]}
    ok, msg = _gate._known_pass_transcript_ok(tx)
    assert ok is False and "flat" in msg


def test_criterion_monotonic_adc_sweep_too_few_samples_fails():
    tx = {"criterion": "monotonic_adc_sweep",
          "samples_v_in_code_out": [[0.0, 0], [1.0, 100]]}
    ok, msg = _gate._known_pass_transcript_ok(tx)
    assert ok is False and "5" in msg


def test_criterion_memory_readback_match_pass():
    tx = {"criterion": "memory_readback_match",
          "write_readback_pairs": [
              {"written": "DE AD BE EF", "readback": "DE AD BE EF"},
              {"written": "CA FE 00 11", "readback": "CA FE 00 11"},
          ]}
    ok, _ = _gate._known_pass_transcript_ok(tx)
    assert ok is True


def test_criterion_memory_readback_mismatch_fails():
    tx = {"criterion": "memory_readback_match",
          "write_readback_pairs": [
              {"written": "DE AD BE EF", "readback": "DE AD BE FF"},
          ]}
    ok, msg = _gate._known_pass_transcript_ok(tx)
    assert ok is False and "mismatch" in msg


def test_criterion_register_roundtrip_pass():
    tx = {"criterion": "register_write_read_roundtrip",
          "register_roundtrip": [
              {"addr": "0x01", "written": "0xAA", "readback": "0xAA"},
              {"addr": "0x02", "written": "0x55", "readback": "0x55"},
          ]}
    ok, _ = _gate._known_pass_transcript_ok(tx)
    assert ok is True


def test_criterion_register_roundtrip_mismatch_fails():
    tx = {"criterion": "register_write_read_roundtrip",
          "register_roundtrip": [
              {"addr": "0x01", "written": "0xAA", "readback": "0xBB"},
          ]}
    ok, msg = _gate._known_pass_transcript_ok(tx)
    assert ok is False and ("mismatch" in msg or "wrote" in msg)


def test_criterion_comparator_alert_pass():
    tx = {"criterion": "comparator_alert_on_threshold",
          "threshold_events": [
              {"input_v": 0.0, "alert_state": 0},
              {"input_v": 1.5, "alert_state": 1},
              {"input_v": 0.5, "alert_state": 0},
          ]}
    ok, _ = _gate._known_pass_transcript_ok(tx)
    assert ok is True


def test_criterion_comparator_alert_never_assert_fails():
    tx = {"criterion": "comparator_alert_on_threshold",
          "threshold_events": [
              {"input_v": 0.0, "alert_state": 0},
              {"input_v": 0.1, "alert_state": 0},
          ]}
    ok, msg = _gate._known_pass_transcript_ok(tx)
    assert ok is False and "asserted" in msg


def test_unknown_criterion_fails_loud():
    tx = {"criterion": "no_such_criterion",
          "samples_v_in_code_out": []}
    ok, msg = _gate._known_pass_transcript_ok(tx)
    assert ok is False and "unknown criterion" in msg.lower()


def test_default_criterion_when_unspecified():
    """Backwards compat: omitting `criterion` falls back to
    distinct_non_padding_bytes (preserves v0.50-v0.55 L13 semantics)."""
    tx = {"hid_tool_rx_bytes": "F2 BE AB BA D1 CD"}
    ok, _ = _gate._known_pass_transcript_ok(tx)
    assert ok is True
