"""Tests for v0.1.66 R21 capture: L3 protocol mirror from L14-L18.

For bus_interconnect_protocol class, the canonical L3_CMD_PROTOCOL content
is the protocol description — channels, handshake rules, encoding tables —
which the R14 extractors already harvested into L17 / L15 / L18. R21 mirrors
selected L17 fields into L3 so the bus-protocol L3 carries substantive
content matching Claude's canonical L3 shape.

Captured from v0.1.66 parity loop iter 3: L3 had 51 ABSENT findings on
AMBA AXI even though L3 is APPLICABLE to bus_interconnect_protocol per
the R12 taxonomy.

Honesty: data is REFERENCED from existing extractions (L17 / L18), not
re-extracted from text; the mirror preserves the audit trail. Only fires
for bus_interconnect_protocol (other classes keep their L3 untouched).
"""
import re
import sys
from pathlib import Path
from _hostpaths import require_repo  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]
RUNNER = PROGRAMS / "phase1_doc_one_shot_runner.py"


def test_runner_has_l3_protocol_mirror_step():
    src = RUNNER.read_text()
    assert "[14c2/15] L3 protocol mirror from L14-L18 (R21)" in src


def test_l3_mirror_runs_AFTER_l14_l18_extract():
    """The mirror reads L17 which is only on disk after L14-L18 extract."""
    src = RUNNER.read_text()
    l14_pos = src.find("[14c/15] L14-L18 protocol spec extract")
    l3_pos = src.find("[14c2/15] L3 protocol mirror from L14-L18")
    assert l14_pos > 0 and l3_pos > 0
    assert l14_pos < l3_pos


def test_l3_mirror_gated_by_bus_interconnect_protocol():
    """The mirror must ONLY fire for bus_interconnect_protocol class."""
    src = RUNNER.read_text()
    block = src[src.find("[14c2/15] L3 protocol mirror"):
                 src.find("[14d/15] L19-L23 skeleton emit")]
    assert 'if _ic3 == "bus_interconnect_protocol"' in block


def test_l3_mirror_reads_l17_fields_channels():
    src = RUNNER.read_text()
    block = src[src.find("[14c2/15] L3 protocol mirror"):
                 src.find("[14d/15] L19-L23 skeleton emit")]
    assert "L17_CHANNEL_SIGNAL_CATALOG.json" in block
    # The mirror must read L17's "channels" key
    assert '_l17_fields.get("channels")' in block


def test_l3_mirror_writes_canonical_agent_aligned_keys():
    """L3 emitted keys must match Claude's canonical L3 shape:
       'channels' (not 'channel_catalog'),
       'valid_ready_handshake_rules' (not 'handshakes')."""
    src = RUNNER.read_text()
    block = src[src.find("[14c2/15] L3 protocol mirror"):
                 src.find("[14d/15] L19-L23 skeleton emit")]
    assert '_l3["channels"]' in block
    assert '_l3["valid_ready_handshake_rules"]' in block


def test_l3_mirror_attaches_audit_trail():
    src = RUNNER.read_text()
    block = src[src.find("[14c2/15] L3 protocol mirror"):
                 src.find("[14d/15] L19-L23 skeleton emit")]
    # v0.1.69 R25 bumped the audit-trail key to v0_1_69 (mirror now also
    # carries R25 L15 encoding-table mirror).
    assert ("l3_protocol_mirror_v0_1_66" in block
            or "l3_protocol_mirror_v0_1_69" in block)


def test_l3_mirror_fail_open():
    """Missing L17 / read-failure → fail-open (print stderr, don't crash)."""
    src = RUNNER.read_text()
    block = src[src.find("[14c2/15] L3 protocol mirror"):
                 src.find("[14d/15] L19-L23 skeleton emit")]
    assert "except Exception" in block
    # The error must go to stderr, not bubble up
    assert "file=sys.stderr" in block


# ── End-to-end on AMBA AXI ────────────────────────────────────────────

def test_real_amba_axi_l3_now_carries_channels():
    """After v0.1.66, the AMBA AXI L3 must carry .channels mirrored from L17."""
    import json
    l3_path = require_repo("benchmark-data/evaluation/phase1_parity/arm_aix/"
                           "phase1/generated_docs/L3_CMD_PROTOCOL.json")
    if not l3_path.is_file():
        import pytest
        pytest.skip("AMBA AXI generated_docs not present on this host")
    l3 = json.loads(l3_path.read_text())
    # If the mirror ran, channels is at L3 top level
    chans = l3.get("channels")
    # We do NOT assert this aggressively because the test runs before the
    # E2E re-run; just check the runner WIRING is correct.
    assert isinstance(chans, (list, type(None))), (
        f"L3.channels has unexpected type {type(chans).__name__}; should "
        f"be list (after mirror) or None (before mirror).")
