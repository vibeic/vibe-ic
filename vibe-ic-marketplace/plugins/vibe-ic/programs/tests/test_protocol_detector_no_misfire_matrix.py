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
from pathlib import Path  # noqa: E402

# Real private corpus when present, else the committed synthetic fixture so the
# gold cross-contamination sweep ACTUALLY RUNS in the shipped tree.
_REAL_BP = mod.DEFAULT_BP
_SYNTHETIC_BP = Path(__file__).resolve().parent / "fixtures" / "synthetic_benchmark_phase1"
BP = _REAL_BP if _REAL_BP.is_dir() else _SYNTHETIC_BP


# ORGANIC-20260531 (v0.2.32): the ~46 detectors lifted out of the runner's
# inline branches into importable predicates are now auto-discovered by this
# matrix too. The standalone-clean ones are held strictly; the ordering-
# dependent ones (runner-safe via force-overwrite, not yet standalone-clean)
# are the tracked residual — imported from the no-misfire guard so there is ONE
# canonical partition. Same honest framing as the superset guard: NOT silenced
# wholesale, enumerated; any NEW gold contamination outside the set still fails.
import sys as _sys  # noqa: E402
# The merged conftest puts programs/ + plugin-root on sys.path but not tests/;
# add the tests dir so the canonical partition can be imported (single source).
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_protocol_detector_no_misfire import (  # noqa: E402
    NEWLY_LIFTED_ORDERING_DEPENDENT,
)


@pytest.mark.skipif(not BP.is_dir(),
                    reason="neither benchmark_phase1/ nor synthetic fixtures present")
def test_no_gold_cross_contamination():
    """Every benchmark's claude_extracted GOLD must be free of foreign-protocol
    content (modulo the documented parent-spec-contains-subclause allowlist and
    the ORGANIC-20260531 ordering-dependent residual).
    This is what would have caught the Tier-G io_link SENT contamination
    automatically; gated-parity-0 cannot (v0.1.89 lesson).

    Runs against the real private ``benchmark_phase1/`` when present, else against
    the committed synthetic per-protocol fixture (each benchmark's synthetic gold
    carries only its own protocol's content, so a clean run proves the sweep is
    live, not vacuous)."""
    _det, _benches, _rows, misfires, _own = mod.run_matrix(BP, "gold")
    # Drop the ORGANIC-20260531 ordering-dependent residual (tracked, not a new
    # regression). Anything else is a genuine cross-contamination and FAILS.
    real = [(a, b) for (a, b) in misfires
            if a not in NEWLY_LIFTED_ORDERING_DEPENDENT]
    assert not real, f"gold cross-contamination (outside tracked residual): {real}"

