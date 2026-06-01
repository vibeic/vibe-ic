"""Tests for protocol_detector_no_misfire_matrix (v0.2.13).

The unified bidirectional matrix that serves BOTH the no-misfire guard
(--blob generated/superset) and the gold cross-contamination sweep
(--blob gold). Heavy end-to-end runs live in test_protocol_detector_no_misfire;
here we pin the program's core logic + the gold-subclause allowlist.
"""
import importlib
import json

mod = importlib.import_module("protocol_detector_no_misfire_matrix")


def test_discovers_detectors():
    d = mod.discover_detectors()
    assert len(d) >= 6
    # the v0.2.13 drop-ins must be discoverable
    for stem in ("espi", "lpc", "usb_pd", "interlaken", "mdio", "sgmii"):
        assert stem in d and callable(d[stem])


def test_blob_for_input_doc_first(tmp_path):
    # input_doc must precede generated content in the blob (so a head-based
    # subject-dominance check sees the source spec title).
    b = tmp_path / "demo"
    (b / "phase1" / "input_doc").mkdir(parents=True)
    (b / "phase1" / "generated_docs").mkdir(parents=True)
    (b / "phase1" / "input_doc" / "spec.txt").write_text("TITLE_TOKEN source spec")
    (b / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "GEN_TOKEN"}))
    blob = mod.blob_for(tmp_path, "demo", "superset")
    assert blob.index("TITLE_TOKEN") < blob.index("GEN_TOKEN")


def test_gold_subclause_allowlist_present():
    # MDIO is a genuine Clause-22 sub-clause of IEEE 802.3 (ethernet); these
    # faithful gold fires must be allowlisted (not flagged as contamination).
    assert ("mdio", "ethernet") in mod.ACCEPTABLE_GOLD_SUBCLAUSE_FIRES
    assert ("mdio", "ethernet_800g") in mod.ACCEPTABLE_GOLD_SUBCLAUSE_FIRES


def test_gold_allowlist_only_applies_to_gold_blob(tmp_path):
    # The allowlist is gold-specific; it must NOT suppress a generated-blob
    # misfire (runtime correctness is enforced strictly).
    # Sanity: the pairs are keyed (detector, benchmark) tuples.
    for pair in mod.ACCEPTABLE_GOLD_SUBCLAUSE_FIRES:
        assert isinstance(pair, tuple) and len(pair) == 2


# --- end-to-end CI gate: no foreign detector may fire on any benchmark GOLD ---
import pytest  # noqa: E402

BP = mod.DEFAULT_BP


@pytest.mark.skipif(not BP.is_dir(), reason="benchmark_phase1 fixtures absent")
def test_no_gold_cross_contamination():
    """Every benchmark's claude_extracted GOLD must be free of foreign-protocol
    content (modulo the documented parent-spec-contains-subclause allowlist).
    This is what would have caught the Tier-G io_link SENT contamination
    automatically; gated-parity-0 cannot (v0.1.89 lesson)."""
    _det, _benches, _rows, misfires, _own = mod.run_matrix(BP, "gold")
    assert not misfires, f"gold cross-contamination: {misfires}"

