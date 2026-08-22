"""Regression tests for the v0.1.93 Tier-F protocol detectors.

Five new protocol classes were added in v0.1.93:
  * SAS            (INCITS T10)            — Serial Attached SCSI storage interconnect
  * Avalon         (Intel/Altera)          — FPGA-SoC memory-mapped / streaming interface
  * HyperBus       (Cypress/Infineon)      — HyperRAM/HyperFlash DDR memory interface
  * QSPI/OSPI      (JEDEC xSPI JESD251)    — quad/octal SPI flash interface (extends SPI)
  * MIPI SPMI/RFFE (MIPI Alliance)         — 2-wire power-mgmt / RF-front-end control bus

Each detector is content-only and carries a sibling MUTEX. These tests pin the
MUTEX behaviour so a future edit cannot reintroduce the masking risk from the
v0.1.89 KEY LESSON (a detector that over-fires on a sibling/foreign doc silently
overwrites its output, and force-overwrite-to-0 hides it from parity).

The is_avalon hardening (v0.1.93) is explicitly pinned: it must require an
Avalon-specific signal signature (waitrequest+readdatavalid, or
startofpacket+endofpacket), NOT merely the token "Avalon" appearing in a generic
bus-vocabulary enumeration — the bug the no-misfire sweep caught on
ethercat/hdlc/modbus.

Two layers:
  * unit    — synthetic strings exercising each signature + each mutex branch;
  * fixture — the real 57 benchmark contents; asserts each detector fires ONLY on
              its own benchmark, skipped if dirs are absent.
"""
import glob
import os
from pathlib import Path

import pytest

from sas_protocol_synth import is_sas
from avalon_protocol_synth import is_avalon
from hyperbus_protocol_synth import is_hyperbus
from qspi_ospi_protocol_synth import is_qspi_ospi
from mipi_spmi_rffe_protocol_synth import is_mipi_spmi_rffe

DETS = {
    "sas": is_sas,
    "avalon": is_avalon,
    "hyperbus": is_hyperbus,
    "qspi_ospi": is_qspi_ospi,
    "mipi_spmi_rffe": is_mipi_spmi_rffe,
}

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


def test_sas_fires_on_signature():
    blob = ("Serial Attached SCSI: SSP, STP and SMP transport protocols over a "
            "phy; expander (edge and fanout); wide port bundles phys with the same "
            "64-bit SAS address; OPEN address frame and connection management")
    assert is_sas(blob) is True


def test_sas_defers_to_sata_and_nvme():
    sata = ("Serial ATA AHCI host bus adapter: register FIS and DMA FIS over a "
            "single host-device link")  # no expander/SSP/SMP/SAS-address
    nvme = ("NVMe over PCI Express: submission queue and completion queue with a "
            "doorbell register per namespace")
    assert is_sas(sata) is False
    assert is_sas(nvme) is False


def test_avalon_fires_only_on_signal_signature():
    mm = ("Avalon-MM agent with address, read, write, readdata, writedata, "
          "byteenable, waitrequest and readdatavalid; burstcount pipelined")
    st = ("Avalon-ST source/sink with data, valid, ready, startofpacket, "
          "endofpacket, empty and channel; ready-latency backpressure")
    assert is_avalon(mm) is True
    assert is_avalon(st) is True


def test_avalon_does_not_fire_on_name_token_in_bus_list():
    # v0.1.93 hardening: the literal "Avalon" inside a generic bus-vocabulary
    # enumeration (the masking bug caught on ethercat/hdlc/modbus) must NOT fire
    # without a real Avalon signal signature.
    blob = ("Supported host interfaces include AXI, APB, AHB, Wishbone, Avalon, "
            "TileLink and OCP. The core is memory-mapped and host/agent ready, "
            "with a streaming option (ready/valid).")  # no waitrequest+readdatavalid / sop+eop
    assert is_avalon(blob) is False


def test_avalon_defers_to_axi_and_wishbone():
    axi = "AXI4 manager: ARVALID/ARREADY, AWVALID, WVALID, RVALID, BVALID channels"
    wb = "Wishbone B4: CYC_O, STB_O, ACK_I, ADR_O, DAT_O classic handshake"
    assert is_avalon(axi) is False
    assert is_avalon(wb) is False


def test_hyperbus_fires_on_signature():
    blob = ("HyperBus HyperRAM: CK/CK# differential clock, CS#, DQ[7:0] 8-bit DDR "
            "bus, RWDS read-write data strobe; 48-bit Command-Address (CA) "
            "sequence; configurable initial latency; CR0/CR1 configuration registers")
    assert is_hyperbus(blob) is True


def test_hyperbus_defers_to_spi():
    blob = "SPI master with SCLK, MOSI, MISO and SS#; CPOL/CPHA modes; shift register"
    assert is_hyperbus(blob) is False


def test_qspi_ospi_fires_on_signature():
    blob = ("Quad/Octal SPI xSPI (JESD251): IO0..IO7 multi-IO data lines; 1-4-4 and "
            "8D-8D-8D protocol modes; instruction/address/dummy-cycles/data phases; "
            "Fast Read 0x0B, Quad I/O Read 0xEB, Read SFDP; DDR with DQS")
    assert is_qspi_ospi(blob) is True


def test_qspi_ospi_defers_to_plain_spi():
    blob = ("Motorola SPI: SCLK, MOSI, MISO, SS#; CPOL and CPHA; full-duplex shift "
            "register; no multi-IO or flash command set")
    assert is_qspi_ospi(blob) is False


def test_mipi_spmi_rffe_fires_on_signature():
    spmi = ("MIPI SPMI: 2-wire SCLK and SDATA; Sequence Start Condition (SSC); odd "
            "parity command frames; MASTER_ID and SLAVE_ID; multi-master arbitration; "
            "Device Descriptor Block (DDB)")
    rffe = ("MIPI RFFE: 2-wire SCLK and SDATA; Sequence Start Condition (SSC); parity; "
            "USID and GSID; RF front-end slaves (PA, LNA, switch); Masked Write and "
            "Mapped Register Write")
    assert is_mipi_spmi_rffe(spmi) is True
    assert is_mipi_spmi_rffe(rffe) is True


def test_mipi_spmi_rffe_defers_to_i2c_spi_smbus():
    i2c = "I2C two-wire: SDA and SCL; 7-bit address; START and STOP conditions"
    spi = "SPI: SCLK, MOSI, MISO, SS#; CPOL/CPHA"
    smb = "SMBus with PEC CRC-8 and SMBALERT#; PMBus OPERATION and VOUT_COMMAND"
    assert is_mipi_spmi_rffe(i2c) is False
    assert is_mipi_spmi_rffe(spi) is False
    assert is_mipi_spmi_rffe(smb) is False


# ------------------------------------------------------------------------ fixture
def _blob_for(b: str) -> str:
    parts = []
    for p in (glob.glob(str(BP / b / "phase1" / "input_doc" / "*"))
              + glob.glob(str(BP / b / "phase1" / "generated_docs" / "*.json"))):
        try:
            parts.append(Path(p).read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    return "\n".join(parts)


@needs_corpus
@pytest.mark.skipif(not BP.is_dir(), reason="benchmark_phase1 fixtures absent")
def test_no_misfire_across_all_benchmarks():
    """Each Tier-F detector must fire ONLY on its own benchmark's full content.

    Content SUPERSET (input_doc + every generated L-doc) — strictly larger than
    the runner's _spi_blob — so zero foreign fires here ⇒ zero in the runner.
    """
    benches = sorted(d for d in os.listdir(BP) if (BP / d).is_dir())
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
            if fired and b != name:
                misfires.append((name, b))
            if fired and b == name:
                own_fires.add(name)
    assert scanned >= len(DETS), f"too few benchmarks scanned ({scanned})"
    assert not misfires, f"Tier-F detector mis-fires: {misfires}"
    for name in DETS:
        if (BP / name).is_dir() and _blob_for(name):
            assert name in own_fires, f"{name} detector failed to fire on own benchmark"
