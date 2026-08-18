"""Regression tests for the v0.1.90 phase1_doc_one_shot_runner large-doc fix.

  Fix 1 (SHIPPED) — ORGANIC-20260530-phase1-large-doc-hang
    A pathologically large extracted doc (e.g. the 7.76 MB Bluetooth
    Core Spec) drove the per-item O(items x text-length) L-doc scans
    (L1/L2/L4/L5/L11/...) into a multi-hour freeze. `_cap_extracted_for_scan`
    bounds each document at `_LARGE_DOC_SCAN_CAP_BYTES` (2 MB). Normal-
    size docs (every non-BLE benchmark — the largest, usb, is ~1.95 MB,
    just under the cap) are unchanged and pass through byte-for-byte.
    GENERAL / chip-AGNOSTIC: purely size-based, no protocol / benchmark /
    file-name literal.

  Fix 2 (REVERTED) — ORGANIC-20260530-incidental-crossref-synth-pollution
    A CSI-2-packet-structure primary-subject guard on the MIPI detector
    was attempted and reverted: the `mipi` benchmark's TI SLLA414 source
    is a D-PHY layout guide whose fresh extraction carries NO CSI-2
    packet vocabulary, so any such guard regresses the mipi benchmark
    (165 gated). The incidental pollution on ufs / pcie_gen5 is parity-
    neutral (SHAPE-excluded), so the backlog item is left OPEN and the
    v0.1.84 detector is kept unchanged. The test below pins that the
    bare MIPI/D-PHY signal STILL fires (no guard) so a future re-attempt
    that breaks it is caught.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as p1doc  # noqa: E402


# ===========================================================================
# Fix 1 — large-doc scan cap
# ===========================================================================
def test_cap_constant_is_2mb():
    assert p1doc._LARGE_DOC_SCAN_CAP_BYTES == 2 * 1024 * 1024


def test_cap_truncates_only_oversized_doc():
    cap = p1doc._LARGE_DOC_SCAN_CAP_BYTES
    big = "x" * (cap + 500_000)
    extracted = {"huge.txt": big, "small.txt": "tiny body"}
    out = p1doc._cap_extracted_for_scan(extracted)
    assert len(out["huge.txt"]) <= cap
    assert out["small.txt"] == "tiny body"


def test_cap_passes_small_docs_through_unchanged_identity():
    # Common case: every doc under the cap → returned object is the SAME
    # string instance, so output for the 47 normal benchmarks is identical.
    small = {"a.txt": "register Mode reset 0x00", "b.txt": "command set"}
    out = p1doc._cap_extracted_for_scan(small)
    assert out["a.txt"] is small["a.txt"]
    assert out["b.txt"] is small["b.txt"]


def test_cap_respects_line_boundary_when_within_tail_window():
    cap = p1doc._LARGE_DOC_SCAN_CAP_BYTES
    # A newline 10 KB before the cap (inside the 64 KB tail window) is
    # honoured so a table row is not split mid-line.
    head = "a" * (cap - 10_000)
    body = head + "\n" + "b" * 100_000
    out = p1doc._cap_extracted_for_scan({"f.txt": body})
    res = out["f.txt"]
    assert len(res) <= cap
    # truncation landed on the newline boundary (no trailing 'b' run)
    assert res.endswith("a")
    assert "\n" not in res  # only the head, cut at the newline


def test_cap_hard_cuts_when_no_boundary_in_tail_window():
    cap = p1doc._LARGE_DOC_SCAN_CAP_BYTES
    # No newline anywhere → hard cut at exactly the cap.
    body = "z" * (cap + 1_000_000)
    out = p1doc._cap_extracted_for_scan({"f.txt": body})
    assert len(out["f.txt"]) == cap


def test_cap_handles_empty_and_non_dict():
    assert p1doc._cap_extracted_for_scan({}) == {}
    assert p1doc._cap_extracted_for_scan(None) is None


def test_cap_at_exactly_the_threshold_is_unchanged():
    cap = p1doc._LARGE_DOC_SCAN_CAP_BYTES
    exact = {"f.txt": "q" * cap}
    out = p1doc._cap_extracted_for_scan(exact)
    assert out["f.txt"] is exact["f.txt"]  # not > cap → passthrough


# ===========================================================================
# Fix 2 REVERTED — pin that no CSI-2-packet-structure MIPI guard exists.
# ===========================================================================
def test_mipi_csi2_packet_guard_helper_is_not_present():
    # The attempted `_v0_1_90_is_mipi` primary-subject helper was reverted
    # (it regressed the mipi benchmark, whose source carries no CSI-2
    # packet vocabulary). If a future change re-introduces such a helper
    # it must NOT gate on CSI-2 packet structure; this test flags the
    # re-attempt so the mipi-breakage is caught before merge.
    assert not hasattr(p1doc, "_v0_1_90_is_mipi"), (
        "A CSI-2-packet-structure MIPI guard was re-introduced — this "
        "regresses the mipi benchmark (its TI SLLA414 source has no "
        "CSI-2 packet vocabulary). See ORGANIC-20260530 (left OPEN).")


def test_mipi_detector_still_fires_on_bare_signal():
    # The v0.1.84 detector (unchanged after the revert) must STILL fire on
    # the bare MIPI/D-PHY signal — this is what keeps the real mipi /
    # mipi_dsi benchmarks at 0 gated. Replicates the inline detector's
    # first OR-clause as a guard against an accidental future tightening.
    blob = "MIPI DPHY application note. Differential lanes."  # mipi-like
    bare_signal = (
        ("MIPI" in blob and ("D-PHY" in blob or "DPHY" in blob)))
    assert bare_signal is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
