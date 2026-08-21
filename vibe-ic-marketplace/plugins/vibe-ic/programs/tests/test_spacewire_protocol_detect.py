"""Regression tests for the SpaceWire (ECSS-E-ST-50-12C) protocol detector.

SpaceWire is a spacecraft-onboard serial link / network: LVDS signalling with
Data-Strobe (DS) encoding (clock = Data XOR Strobe), a 10-bit data / 4-bit
control character set (FCT/EOP/EEP/ESC + NULL + Time-Code), the exchange-level
ErrorReset -> ErrorWait -> Ready -> Started -> Connecting -> Run state machine,
credit-based flow control, packets <address><cargo><EOP/EEP>, and wormhole
routing through routers.

These tests pin:
  * the STRUCTURAL signature requirement (general-not-keyword) — the name token
    "SpaceWire" alone never fires; a DS-encoding + FCT/EOP/EEP + exchange-FSM +
    LVDS signature is required;
  * the sibling MUTEX against MIL-STD-1553 / ARINC-429 / Ethernet (which lack
    the SpaceWire structural signature) so the detector cannot false-fire;
  * the no-misfire property against the real 57+ benchmark contents — the
    detector fires ONLY on the spacewire benchmark.

This guards the v0.1.89 KEY LESSON: a detector that over-fires on a sibling /
foreign doc silently overwrites its output, and force-overwrite-to-0 hides it
from parity. The fixture layer is the structural backstop.
"""
import glob
import os
from pathlib import Path

import pytest

from spacewire_protocol_synth import is_spacewire
from _plugin_tree import repo_path_or_missing

# flow #486: benchmark_phase1/ is a repo-root-only private corpus absent on
# the flattened cache; resolve defensively so the existing skipif guards fire.
BP = repo_path_or_missing("benchmark-data", "evaluation", "phase1_parity")


# --------------------------------------------------------------------------- unit
def test_empty_blob_never_fires():
    assert is_spacewire("") is False
    assert is_spacewire(None) is False  # type: ignore[arg-type]


def test_fires_on_full_structural_signature_without_name():
    # No "SpaceWire" token — only the structure. Must still fire.
    blob = (
        "The link signals over LVDS using Data-Strobe encoding so the clock is "
        "Data XOR Strobe; the Strobe signal toggles whenever the Data signal "
        "does not. Control characters FCT, EOP, EEP and ESC are used; NULL is "
        "ESC plus FCT. The link initialization runs ErrorReset, ErrorWait, "
        "Ready, Started, Connecting and Run with credit-based flow control "
        "where each FCT grants eight N-Chars (max 56 outstanding)."
    )
    assert is_spacewire(blob) is True


def test_fires_with_name_and_signature():
    blob = (
        "SpaceWire (ECSS-E-ST-50-12C): a low-voltage differential signalling "
        "(LVDS) link using Data-Strobe encoding (clock = Data XOR Strobe) with "
        "Data and Strobe pairs. Control characters FCT, EOP, EEP, ESC; "
        "exchange state machine ErrorReset, ErrorWait, Started, Connecting, "
        "Run; credit-based flow control with FCTs."
    )
    assert is_spacewire(blob) is True


def test_name_token_alone_never_fires():
    # general-not-keyword: a bare mention with no structure must NOT fire.
    assert is_spacewire("This board has a SpaceWire connector for telemetry.") \
        is False


def test_bare_lvds_does_not_fire():
    blob = (
        "This serial link uses low-voltage differential signalling (LVDS) to "
        "ANSI/TIA/EIA-644 for high-speed low-power signalling over "
        "differential pairs."
    )
    assert is_spacewire(blob) is False


def test_generic_router_does_not_fire():
    blob = (
        "A packet router with input ports and output ports forwards packets "
        "using a routing table and wormhole routing across the network."
    )
    assert is_spacewire(blob) is False


def test_mutex_milstd1553():
    blob = (
        "MIL-STD-1553B dual-redundant 1 Mbps transformer-coupled bus with "
        "Manchester encoding; a Bus Controller commands Remote Terminals in a "
        "command/response protocol with command, data and status words."
    )
    assert is_spacewire(blob) is False


def test_mutex_arinc429():
    blob = (
        "ARINC 429 is a one-way, single-source, multiple-sink avionics data "
        "bus carrying 32-bit words with a label, SDI, data and parity at low "
        "or high speed."
    )
    assert is_spacewire(blob) is False


def test_mutex_ethernet():
    blob = (
        "Ethernet MAC/PHY: the MII connects the MAC to the PHY; frames carry a "
        "preamble, destination MAC address, source MAC address, type/length, "
        "payload and FCS."
    )
    assert is_spacewire(blob) is False


# ------------------------------------------------------------------------- fixture
def _blob(name: str) -> str:
    gd = BP / name / "phase1" / "generated_docs"
    txt = ""
    if gd.is_dir():
        for n in ("L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json"):
            q = gd / n
            if q.is_file():
                txt += q.read_text()
    docs = BP / name / "input" / "docs"
    if docs.is_dir():
        for f in docs.glob("*.txt"):
            txt += f.read_text()
    return txt


@pytest.mark.skipif(not (BP / "spacewire").is_dir(),
                    reason="spacewire benchmark absent")
def test_fires_on_own_benchmark():
    assert is_spacewire(_blob("spacewire")) is True


@pytest.mark.parametrize("sibling", ["milstd1553", "arinc429", "ethernet"])
def test_no_misfire_on_aerospace_siblings(sibling):
    if not (BP / sibling).is_dir():
        pytest.skip(f"{sibling} benchmark absent")
    assert is_spacewire(_blob(sibling)) is False


def test_no_misfire_across_all_benchmarks():
    """The detector must fire on spacewire and on NOTHING else."""
    if not BP.is_dir():
        pytest.skip("benchmark_phase1 absent")
    fired = []
    for d in sorted(BP.iterdir()):
        if not d.is_dir():
            continue
        b = _blob(d.name)
        if b and is_spacewire(b):
            fired.append(d.name)
    assert fired == ["spacewire"], f"is_spacewire fired on: {fired}"
