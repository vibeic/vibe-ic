"""Regression tests for the PROFINET IO protocol detector.

PROFINET (IEC 61158 Type 10 / IEC 61784-2 CPF 3) is the open Industrial Ethernet
standard for automation. Because a PROFINET spec necessarily mentions the
standard IEEE 802.3 Ethernet base layer (MII/MDIO/PHY/802.3), the inline
Ethernet sub-detector in the runner fires first and populates the base L-docs;
the PROFINET synth runs AFTER it and force-overwrites with PROFINET-canonical
content. The detector must therefore fire on the PROFINET structural signature
WITHOUT false-firing on a plain-Ethernet, EtherCAT, or PROFIBUS sibling doc.

These tests pin:
  * the PROFINET structural-signature fire (device roles + GSDML/DCP/AR-CR +
    cyclic PNIO IOPS/IOCS / RT EtherType 0x8892);
  * the EtherCAT MUTEX (datagram / FMMU / SyncManager / distributed-clock / ESC
    primary with no PROFINET structure -> defer);
  * the PROFIBUS MUTEX (RS-485 token-passing / SD1-SD4 / DPV1 / GSD-not-GSDML
    primary with no PROFINET structure -> defer);
  * content-only behaviour (no filename reads) and the real-benchmark no-misfire
    sweep (fires only on its own benchmark, skipped if dirs absent).
"""
import glob
import os
from pathlib import Path

import pytest

from profinet_protocol_synth import is_profinet


# ----------------------------------------------------------------------
# Unit — synthetic strings exercising the signature + each MUTEX branch.
# ----------------------------------------------------------------------
def test_profinet_full_structure_fires():
    blob = (
        "PROFINET IO over standard IEEE 802.3 Ethernet. The IO-Controller (PLC) "
        "establishes an Application Relation (AR) to each IO-Device; an "
        "IO-Supervisor handles engineering. Each IO-Device ships a GSDML file. "
        "Stations are addressed by NameOfStation via DCP. The AR carries an "
        "IO-CR (cyclic), a Record-Data-CR, and an Alarm-CR. Cyclic PNIO data "
        "carries IOPS and IOCS per object with an APDU Cycle Counter, sent on "
        "EtherType 0x8892. Conformance Class CC-C adds IRT and PTCP."
    )
    assert is_profinet(blob) is True


def test_profinet_minimal_roles_plus_engineering():
    blob = ("The IO-Controller and IO-Device exchange data; the device is "
            "described by a GSDML file and addressed via DCP.")
    assert is_profinet(blob) is True


def test_profinet_name_plus_gsdml_plus_dcp():
    blob = ("PROFINET uses GSDML device descriptions and DCP for station "
            "naming and IP assignment.")
    assert is_profinet(blob) is True


def test_profinet_rt_ethertype_with_provider_consumer():
    blob = ("IO-Controller and IO-Device cyclic frames use EtherType 0x8892; "
            "provider status IOPS and consumer status IOCS with a Cycle "
            "Counter; conformance class CC-B.")
    assert is_profinet(blob) is True


def test_empty_blob_does_not_fire():
    assert is_profinet("") is False
    assert is_profinet(None) is False  # type: ignore[arg-type]


def test_plain_ethernet_does_not_fire():
    blob = ("IEEE 802.3 Ethernet MAC with MII and MDIO to the PHY. Frames have "
            "a preamble, SFD, destination MAC, source MAC, EtherType, payload "
            "and FCS. Auto-negotiation selects 100BASE-TX or 1000BASE-T.")
    assert is_profinet(blob) is False


def test_ethercat_primary_mutex_defers():
    blob = ("EtherCAT processes telegrams on the fly. Each EtherCAT datagram "
            "is read/written by the EtherCAT Slave Controller (ESC) using the "
            "FMMU and SyncManager. Distributed Clock synchronizes the "
            "SubDevices. There is no IO-Controller / GSDML / DCP here.")
    assert is_profinet(blob) is False


def test_profibus_primary_mutex_defers():
    blob = ("PROFIBUS DP is an RS-485 fieldbus using token passing between the "
            "DP master and DP slave. Telegrams use SD1, SD2, SD3, SD4 start "
            "delimiters. Devices are described by a GSD file; DPV1 provides "
            "acyclic services. No PROFINET roles here.")
    assert is_profinet(blob) is False


def test_profinet_beats_ethernet_when_structure_present():
    # A doc that has the Ethernet base AND the PROFINET structure must fire
    # (PROFINET, not deferred), since PROFINET runs after Ethernet.
    blob = ("Standard IEEE 802.3 Ethernet with MII/MDIO/PHY base. On top, "
            "PROFINET IO: IO-Controller, IO-Device, GSDML, DCP, "
            "Application Relation with IO-CR / Alarm-CR, IOPS/IOCS, "
            "Cycle Counter, EtherType 0x8892, conformance class CC-C, PTCP.")
    assert is_profinet(blob) is True


def test_content_only_no_filename_dependency():
    # Same content fires regardless of any path/filename context.
    blob = ("IO-Controller, IO-Device, GSDML, DCP, IO-CR, IOPS, IOCS, "
            "cycle counter, 0x8892, conformance class CC-A.")
    assert is_profinet(blob) is True


# ----------------------------------------------------------------------
# Fixture — real benchmark contents: profinet fires, siblings do not.
# ----------------------------------------------------------------------
def _find_benchmark_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "benchmark-data" / "evaluation" / "phase1_parity"
        if cand.is_dir():
            return cand
    # flow #486: fall back to the repo-root location when on the source
    # monorepo; on the flattened cache this resolves to a non-existent path
    # so the existing `(_BENCH/...).is_dir()` skip guards fire (no IndexError).
    from _plugin_tree import repo_path_or_missing
    return repo_path_or_missing("benchmark-data", "evaluation", "phase1_parity")


_BENCH = _find_benchmark_root()


def _read_benchmark_blob(name: str) -> str:
    blob = ""
    for sub in ("input/docs", "phase1/input_doc"):
        d = _BENCH / name / sub
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix.lower() in (".txt", ".md", ".json"):
                    try:
                        blob += "\n" + f.read_text(errors="ignore")
                    except Exception:
                        continue
    return blob


@pytest.mark.skipif(not (_BENCH / "profinet").is_dir(),
                    reason="profinet benchmark dir absent")
def test_real_profinet_benchmark_fires():
    blob = _read_benchmark_blob("profinet")
    if not blob.strip():
        pytest.skip("profinet benchmark has no extractable text")
    assert is_profinet(blob) is True


@pytest.mark.parametrize("sibling", [
    "ethernet", "ethercat", "ethernet_800g", "profibus", "modbus", "can",
    "canfd", "spi", "i2c", "uart", "pcie", "sas", "spacewire",
])
def test_real_siblings_do_not_misfire(sibling):
    d = _BENCH / sibling
    if not d.is_dir():
        pytest.skip(f"{sibling} benchmark dir absent")
    blob = _read_benchmark_blob(sibling)
    if not blob.strip():
        pytest.skip(f"{sibling} has no extractable text")
    assert is_profinet(blob) is False, f"profinet detector misfired on {sibling}"
