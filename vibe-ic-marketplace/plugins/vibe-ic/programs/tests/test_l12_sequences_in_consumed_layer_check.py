"""Smoke tests for l12_sequences_in_consumed_layer_check.py.

NEGATIVE CONTROL IS THE POINT. The central claim — "a requirement is
only captured when it is in the layer that CONSUMES it" — is asserted by
moving one identical sequence array between two layers and requiring
opposite verdicts. Nothing about the sequence changes; only which file
holds it. A gate that could not fail would be caught by that pair alone.

All fixtures are SYNTHESISED neutral data. No real design's files, no
vendor part number, no PDK name, no pin literal from any shipped design.
"""
import json
import sys
from pathlib import Path

SCRIPT = (Path(__file__).parent.parent
          / "l12_sequences_in_consumed_layer_check.py")
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))

import l12_sequences_in_consumed_layer_check as chk  # noqa: E402
import l12_sequence_implementation_check as consumer  # noqa: E402

L12 = "L12_BEHAVIORAL_SEQUENCES.json"
OTHER = "L11_OTP_CONTENT.json"


# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------
def _docs(tmp_path):
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _good_sequence(sid="seq_widget_arm"):
    return {
        "id": sid,
        "name": sid,
        "trigger": "host asserts the arm request",
        "steps": [
            {"step": 1, "action": "drive arm request high",
             "expected_signal": "widget_ready"},
            {"step": 2, "action": "wait for acknowledge",
             "latency_us": 120, "next_state": "ARMED"},
            {"step": 3, "action": "sample the status word",
             "check": "status == 0x01"},
        ],
    }


def _write(docs, name, payload):
    (docs / name).write_text(json.dumps(payload, ensure_ascii=False))


def _cats(tmp_path):
    rep = chk.audit(_docs(tmp_path))
    return [f["category"] for f in rep["findings"] if f["severity"] == "ERROR"]


def _run(tmp_path):
    return chk.main([str(tmp_path)])


# ---------------------------------------------------------------------------
# A. STRANDING — the motivating defect, both directions
# ---------------------------------------------------------------------------
def test_sequence_in_the_consumed_layer_passes(tmp_path):
    docs = _docs(tmp_path)
    _write(docs, L12, {"behavioral_sequences": [_good_sequence()]})
    _write(docs, OTHER, {"otp_present": False, "behavioral_sequences": []})
    assert _run(tmp_path) == 0
    assert _cats(tmp_path) == []


def test_NEGATIVE_control_identical_sequence_stranded_elsewhere_fails(tmp_path):
    """GUTTED: the SAME sequence, moved into a layer nobody consumes.

    This is the measured fleet failure: the reject-rule synthesiser wrote
    its sequences into L11 and left L12 empty, so the RTL precheck
    reported 'no L12 sequences declared' and passed.
    """
    docs = _docs(tmp_path)
    _write(docs, L12, {"behavioral_sequences": []})
    _write(docs, OTHER, {"otp_present": False,
                         "behavioral_sequences": [_good_sequence()]})
    assert _run(tmp_path) == 1
    assert "SEQUENCES_STRANDED" in _cats(tmp_path)


def test_no_sequences_anywhere_passes(tmp_path):
    """A design with no behavioural protocol owes L12 nothing."""
    docs = _docs(tmp_path)
    _write(docs, L12, {"behavioral_sequences": []})
    _write(docs, OTHER, {"otp_present": False, "behavioral_sequences": []})
    assert _run(tmp_path) == 0


# ---------------------------------------------------------------------------
# B. KEY REACHABILITY — imported from the consumer, never re-spelled
# ---------------------------------------------------------------------------
def test_consumer_key_set_is_imported_not_copied(tmp_path):
    assert chk.consumer_sequence_keys() == consumer.SEQUENCE_ARRAY_KEYS
    assert "behavioral_sequences" in chk.consumer_sequence_keys()


def test_consumer_actually_reads_the_emitted_key(tmp_path):
    """Regression guard for the strengthened consumer.

    Before v1.1.0 the consumer read ONLY 'sequences', so every real run
    (which emits 'behavioral_sequences') made it answer 'no L12
    sequences declared' and PASS.
    """
    rows, key = consumer.extract_sequences(
        {"behavioral_sequences": [_good_sequence()]})
    assert key == "behavioral_sequences"
    assert len(rows) == 1


def test_NEGATIVE_control_sequences_under_unread_key_fails(tmp_path):
    """Same array, parked under a key the consumer does not read."""
    docs = _docs(tmp_path)
    _write(docs, L12, {"seq_catalogue": [_good_sequence()]})
    assert _run(tmp_path) == 1
    assert "SEQUENCES_UNDER_UNREAD_KEY" in _cats(tmp_path)


# ---------------------------------------------------------------------------
# C. ACTIONABLE SHAPE
# ---------------------------------------------------------------------------
def test_NEGATIVE_control_sequence_without_steps_fails(tmp_path):
    docs = _docs(tmp_path)
    seq = _good_sequence()
    seq.pop("steps")
    _write(docs, L12, {"behavioral_sequences": [seq]})
    assert _run(tmp_path) == 1
    assert "NO_STEPS" in _cats(tmp_path)


def test_NEGATIVE_control_single_step_sequence_fails(tmp_path):
    docs = _docs(tmp_path)
    seq = _good_sequence()
    seq["steps"] = seq["steps"][:1]
    _write(docs, L12, {"behavioral_sequences": [seq]})
    assert _run(tmp_path) == 1
    assert "DEGENERATE_STEPS" in _cats(tmp_path)


def test_NEGATIVE_control_prose_only_steps_fail(tmp_path):
    """GUTTED: strip every typed detail, leaving prose actions.

    This is the exact shape the fleet emits for auto-synthesised
    reject-coverage sequences: three steps, each an `action` string, no
    expected_signal / latency / next_state anywhere.
    """
    docs = _docs(tmp_path)
    seq = _good_sequence()
    seq["steps"] = [{"step": 1, "action": "trigger the condition"},
                    {"step": 2, "action": "observe the response window"},
                    {"step": 3, "action": "assert the part stays silent"}]
    _write(docs, L12, {"behavioral_sequences": [seq]})
    assert _run(tmp_path) == 1
    assert "UNTYPED_STEPS" in _cats(tmp_path)


def test_NEGATIVE_control_sequence_without_handle_fails(tmp_path):
    docs = _docs(tmp_path)
    seq = _good_sequence()
    seq.pop("id")
    seq.pop("name")
    _write(docs, L12, {"behavioral_sequences": [seq]})
    assert _run(tmp_path) == 1
    assert "NO_HANDLE" in _cats(tmp_path)


def test_info_only_category_is_skipped_honestly(tmp_path):
    docs = _docs(tmp_path)
    seq = _good_sequence()
    seq["category"] = "info_only"
    seq.pop("steps")
    _write(docs, L12, {"behavioral_sequences": [seq]})
    assert _run(tmp_path) == 0
    rep = chk.audit(_docs(tmp_path))
    assert rep["summary"]["l12_sequences_skipped_category"] == 1


def test_NEGATIVE_control_same_entry_without_the_category_fails(tmp_path):
    """Only the design's own `category` grants the exemption."""
    docs = _docs(tmp_path)
    seq = _good_sequence()
    seq.pop("steps")
    _write(docs, L12, {"behavioral_sequences": [seq]})
    assert _run(tmp_path) == 1
    assert "NO_STEPS" in _cats(tmp_path)


# ---------------------------------------------------------------------------
# SKIP paths must not masquerade as PASS
# ---------------------------------------------------------------------------
def test_no_l12_document_skips(tmp_path):
    _docs(tmp_path)
    assert _run(tmp_path) == 2


def test_no_docs_dir_skips(tmp_path):
    assert chk.main([str(tmp_path)]) == 2


# ---------------------------------------------------------------------------
# Waiver
# ---------------------------------------------------------------------------
def test_waiver_requires_a_real_justification(tmp_path):
    docs = _docs(tmp_path)
    _write(docs, L12, {"behavioral_sequences": []})
    _write(docs, OTHER, {"behavioral_sequences": [_good_sequence()]})
    assert _run(tmp_path) == 1
    (tmp_path / "waivers.json").write_text(json.dumps({chk.WAIVER_KEY: "meh"}))
    assert _run(tmp_path) == 1
    (tmp_path / "waivers.json").write_text(
        json.dumps({chk.WAIVER_KEY: "z" * (chk.WAIVER_MIN + 1)}))
    assert _run(tmp_path) == 0
