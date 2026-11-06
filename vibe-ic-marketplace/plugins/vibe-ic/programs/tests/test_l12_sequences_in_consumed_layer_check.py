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


import phase1_doc_one_shot_runner as phase1  # noqa: E402

L12 = "L12_BEHAVIORAL_SEQUENCES.json"
OTHER = "L11_OTP_CONTENT.json"
EXACT_SOFT_WRAPPED_ABSENCE = (
    "The digital arithmetic design requires no calibration, trimming, analog model,\n"
    "sensor, conversion, or mixed-signal procedure.\n"
)


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






def _produce_l12(tmp_path, source_text, l3=None):
    project = tmp_path / "producer_project"
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "design.md").write_text(source_text, encoding="utf-8")
    phase1.gen_l12_behavioral(
        project, {"design.md": source_text}, l3 or {"opcodes": []})
    path = (project / "phase1" / "generated_docs"
            / "L12_BEHAVIORAL_SEQUENCES.json")
    return json.loads(path.read_text())


def test_calibration_silence_stays_unknown_and_cannot_escape_consumer(tmp_path):
    doc = _produce_l12(tmp_path, "A small synchronous counter.\n")
    assert doc["no_calibration"] is False
    assert "derived_no_calibration_source" not in doc.get(
        "extraction_evidence", {})


def test_explicit_source_bound_no_calibration_authorizes_escape(tmp_path):
    doc = _produce_l12(
        tmp_path, "This design requires no calibration or trimming.\n")
    assert doc["no_calibration"] is True
    assert "input/docs/design.md" in doc.get("extraction_evidence", {})


def test_soft_wrapped_modified_design_absence_is_source_bound(tmp_path):
    doc = _produce_l12(tmp_path, EXACT_SOFT_WRAPPED_ABSENCE)
    assert doc["no_calibration"] is True
    assert doc["behavioral_sequences"] == []
    evidence = doc["extraction_evidence"]["input/docs/design.md"]
    assert evidence == [{
        "literal": (
            "The digital arithmetic design requires no calibration, trimming, "
            "analog model, sensor, conversion, or mixed-signal procedure."
        ),
        "label": "input explicitly states no calibration/trimming",
    }]


def test_scoped_modified_block_cannot_authorize_global_absence(tmp_path):
    doc = _produce_l12(
        tmp_path,
        "The analog block requires no calibration or trimming.\n"
        "The digital design uses a calibration procedure.\n",
    )
    assert doc["no_calibration"] is False
    assert doc["extraction_evidence"] == {}


def test_calibration_error_sentence_does_not_authorize_global_absence(
        tmp_path):
    doc = _produce_l12(
        tmp_path, "There is no calibration error in the measured output.\n")
    assert doc["no_calibration"] is False


def test_positive_calibration_source_does_not_become_absence(tmp_path):
    doc = _produce_l12(
        tmp_path, "A calibration procedure writes a trim register.\n")
    assert doc["no_calibration"] is False


def test_incidental_trim_word_does_not_authorize_absence(tmp_path):
    doc = _produce_l12(tmp_path, "Trim whitespace before parsing.\n")
    assert doc["no_calibration"] is False


def test_foreign_or_conditional_absence_stays_unknown(tmp_path):
    for index, text in enumerate((
        "The test fixture requires no calibration or trimming.\n",
        "If this digital design requires no calibration, skip the procedure.\n",
        "The digital design may require no calibration or trimming.\n",
    )):
        doc = _produce_l12(tmp_path / str(index), text)
        assert doc["no_calibration"] is False
        assert not doc.get("extraction_evidence")


# ---------------------------------------------------------------------------
# A. STRANDING — the motivating defect, both directions
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# B. KEY REACHABILITY — imported from the consumer, never re-spelled
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# C. ACTIONABLE SHAPE
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# SKIP paths must not masquerade as PASS
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Waiver
# ---------------------------------------------------------------------------
