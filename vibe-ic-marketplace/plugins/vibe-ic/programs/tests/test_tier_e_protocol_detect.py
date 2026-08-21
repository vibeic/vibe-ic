"""Regression tests for the v0.1.92 Tier-E protocol detectors.

Four new protocol classes were added in v0.1.92:
  * FlexRay      (ISO 17458 / Bosch 2.1A) — dual-channel TDMA automotive bus
  * DisplayPort  (VESA DP 1.4a/2.x)       — Main Link + AUX + DPCD
  * JESD204B/C   (JEDEC)                  — data-converter ↔ logic serial interface
  * SMBus/PMBus  (SMBus 3.x / PMBus 1.3)  — power-management bus derived from I2C

Each detector is content-only and carries a sibling MUTEX. These tests pin the
MUTEX behaviour so a future edit cannot reintroduce the masking risk from the
v0.1.89 KEY LESSON (a detector that over-fires on a sibling doc silently
overwrites the sibling's output, and force-overwrite-to-0 hides it from parity).

Two layers:
  * unit    — synthetic minimal strings exercising each signature + each mutex branch;
  * fixture — the real 52 benchmark contents; asserts each detector fires ONLY on its
              own benchmark (the v0.1.92 no-misfire sweep), skipped if dirs are absent.
"""
import glob
import os
from pathlib import Path

import pytest

from flexray_protocol_synth import is_flexray
from displayport_protocol_synth import is_displayport
from jesd204_protocol_synth import is_jesd204
from smbus_pmbus_protocol_synth import is_smbus_pmbus

DETS = {
    "flexray": is_flexray,
    "displayport": is_displayport,
    "jesd204": is_jesd204,
    "smbus_pmbus": is_smbus_pmbus,
}

# Derived-sibling cross-fires that are CORRECT base-on-derived detection, handled by
# force-overwrite ordering (the derived synth runs last). eDP (v0.1.94) extends
# DisplayPort, so is_displayport legitimately fires on the edp benchmark — same doctrine
# as I3C-extends-I2C / NVMe-on-PCIe.
# CANONICAL SOURCE: protocol_detector_lib.DERIVED_SIBLING_CROSS_FIRES (v0.1.95).
from protocol_detector_lib import (  # noqa: E402
    DERIVED_SIBLING_CROSS_FIRES as _DERIVED_SIBLING_ALLOW,
)
from _plugin_tree import repo_path_or_missing  # noqa: E402
from _published_corpus import corpus_root, needs_corpus  # noqa: E402

# flow #486: benchmark_phase1/ is a repo-root-only private corpus absent on
# the flattened cache; resolve defensively so the existing skipif guards fire.
#
# The parity RUNS (`<bench>/phase1/input_doc/` + `<bench>/phase1/generated_docs/`)
# are PUBLISHED RESULTS and moved with the rest of them to vibeic/benchmark-data;
# only `<bench>/input/docs/` — the design input the flow reads — stayed here. So
# the sweep resolves its corpus the way every other published-cell check in this
# suite does: an explicit VIBE_IC_BENCHMARK_DATA pointer wins, and the in-repo
# path remains the fallback for a checkout that still carries the runs.
_CORPUS = corpus_root()
BP = ((_CORPUS / "evaluation" / "phase1_parity") if _CORPUS is not None
      else repo_path_or_missing("benchmark-data", "evaluation", "phase1_parity"))


# --------------------------------------------------------------------------- unit
def test_empty_blob_never_fires():
    for det in DETS.values():
        assert det("") is False
        assert det(None) is False  # type: ignore[arg-type]


def test_flexray_fires_on_signature():
    blob = ("FlexRay communication cycle with a static segment and a dynamic "
            "segment; macrotick and microtick timing; dual channel A and "
            "channel B; POC NORMAL_ACTIVE state; TDMA minislot")
    assert is_flexray(blob) is True


def test_flexray_defers_to_can_primary():
    # CAN-primary: bitwise arbitration / CAN identifier / bit stuffing, none of
    # the FlexRay slot/cycle/macrotick structure -> must NOT fire.
    blob = ("CAN 2.0B controller: bitwise arbitration on the CAN identifier, "
            "bit stuffing after 5 equal bits, CSMA/CR bus access")
    assert is_flexray(blob) is False


def test_displayport_fires_on_signature():
    blob = ("DisplayPort Main Link with 4 lanes at HBR2; AUX channel native "
            "transactions to the DPCD; I2C-over-AUX EDID read; link training "
            "clock recovery and channel equalization; LINK_BW_SET")
    assert is_displayport(blob) is True


def test_displayport_defers_to_hdmi_and_dsi():
    hdmi = "HDMI TMDS link with CEC and DDC, HDCP content protection"  # no AUX/DPCD
    dsi = "MIPI DSI over D-PHY, high-speed and low-power escape mode lanes"
    assert is_displayport(hdmi) is False
    assert is_displayport(dsi) is False


def test_jesd204_fires_on_signature():
    blob = ("JESD204B link between a data converter and a logic device; code "
            "group synchronization with K28.5; initial lane alignment sequence "
            "(ILAS) of 4 multiframes; LMFC local multiframe clock; subclass 1 "
            "deterministic latency with SYSREF; octets per frame F and frames "
            "per multiframe K")
    assert is_jesd204(blob) is True


def test_jesd204_silent_on_generic_serdes():
    blob = "PCIe Gen5 SerDes lane at 32 GT/s with 8b/10b legacy and 128b/130b"
    assert is_jesd204(blob) is False


def test_smbus_pmbus_fires_on_signature():
    blob = ("System Management Bus over SMBCLK/SMBDAT with Packet Error Code "
            "(PEC, CRC-8); SMBALERT# and Alert Response Address; PMBus "
            "OPERATION and VOUT_COMMAND commands; STATUS_WORD and PAGE; "
            "LINEAR11 and DIRECT data formats; CONTROL pin")
    assert is_smbus_pmbus(blob) is True


def test_smbus_pmbus_defers_to_plain_i2c():
    blob = ("I2C two-wire bus on SDA and SCL; 7-bit slave address; START "
            "condition and STOP condition; master/slave; repeated start")
    assert is_smbus_pmbus(blob) is False


# ------------------------------------------------------------------------ fixture
def _blob_for(b: str) -> str:
    parts = []
    for p in glob.glob(str(BP / b / "phase1" / "input_doc" / "*")):
        try:
            parts.append(Path(p).read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    for p in glob.glob(str(BP / b / "phase1" / "generated_docs" / "*.json")):
        try:
            parts.append(Path(p).read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    return "\n".join(parts)


@needs_corpus
@pytest.mark.skipif(not BP.is_dir(), reason="benchmark_phase1 fixtures absent")
def test_no_misfire_across_all_benchmarks():
    """Each Tier-E detector must fire ONLY on its own benchmark's full content.

    Uses a content SUPERSET (input_doc + every generated L-doc) — strictly larger
    than the runner's actual _spi_blob — so this is a conservative over-approximation
    of the mis-fire surface. Zero foreign fires here ⇒ zero in the runner.
    """
    benches = sorted(
        d for d in os.listdir(BP) if (BP / d).is_dir()
    )
    misfires = []
    own_fires = set()
    scanned = 0
    for b in benches:
        blob = _blob_for(b)
        if not blob:
            continue
        scanned += 1
        for name, fn in DETS.items():
            fired = fn(blob)
            if fired and b != name and (name, b) not in _DERIVED_SIBLING_ALLOW:
                misfires.append((name, b))
            if fired and b == name:
                own_fires.add(name)
    assert scanned >= len(DETS), f"too few benchmarks scanned ({scanned})"
    assert not misfires, f"Tier-E detector mis-fires: {misfires}"
    # Each of the 4 own benchmarks (if present) must self-fire.
    for name in DETS:
        if (BP / name).is_dir() and _blob_for(name):
            assert name in own_fires, f"{name} detector failed to fire on own benchmark"
