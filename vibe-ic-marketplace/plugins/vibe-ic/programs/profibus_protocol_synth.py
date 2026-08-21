"""PROFIBUS (Process Field Bus) protocol synth helper.

ic_class-gated overlay for `bus_interconnect_protocol` / `unknown`-shaped
specs that exhibit the PROFIBUS-DP structural signature: an industrial
fieldbus over RS-485 (DP) or MBP/IEC 61158-2 (PA) with a HYBRID
medium-access control (token passing between masters + master-slave
polling of the slaves), the byte-oriented telegram (frame) family
selected by Start Delimiters SD1=0x10 / SD2=0x68 / SD3=0xA2 / SD4=0xDC
plus the SC=0xE5 short acknowledgement and ED=0x16 end delimiter, the
DA/SA/FC/DSAP/SSAP/FCS telegram fields, the DP service levels
DPV0/DPV1/DPV2, the GSD (General Station Description) device-description
mechanism, station diagnostics, baud rates 9.6 kbit/s..12 Mbit/s and
station addresses 0..126. Applies IEC 61158 (Type 3) / IEC 61784-1
(CPF 3) PROFIBUS-DP spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL
wire-level signatures (the hybrid token+master-slave MAC, the SD1-SD4
telegram delimiters, the DP service levels, GSD, DSAP/SSAP) read from the
L1/L2 CONTENT blob. It NEVER reads the input-document filename or the
benchmark folder name.

Sibling disambiguation — PROFIBUS-DP runs over RS-485, so a generic
RS-485 PHY guide (electrical-only EIA-485) would superficially overlap.
The detector REQUIRES PROFIBUS-specific structure (DP/PA + token-passing
hybrid + SD1-SD4 telegram delimiters + DPVx + GSD + DSAP/SSAP) so it does
NOT fire on:
  * Modbus-primary specs (Function Code 01-06, holding/input registers,
    coils, simple master-slave RTU/ASCII/TCP with NO token passing, NO
    SD1-SD4, NO DPVx/GSD/DSAP),
  * PROFINET-primary specs (Ethernet-based, IO-Controller/IO-Device,
    GSDML, RT/IRT — a parallel agent owns PROFINET; defer to it),
  * EtherCAT-primary specs (EtherCAT datagram, EtherType 0x88A4,
    Distributed Clocks, FMMU, SyncManager, ESC),
  * generic RS-485 electrical-only guides (just the differential PHY,
    no fieldbus MAC / telegram / service layer).

SIGNATURE (the runner wires the module-level `is_profibus`; evaluated on
the L1/L2 content blob, never on a filename):

    is_profibus(blob) -> bool   (see the function below)

Public entry: `apply_profibus_synth(generated_docs_dir, is_profibus,
profibus_ic_name)`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _ensure_dict(d: dict, key: str) -> dict:
    v = d.get(key)
    if not isinstance(v, dict):
        v = {}
        d[key] = v
    return v


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _word(blob: str, token: str) -> bool:
    """Word-boundary, case-insensitive token presence."""
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(token)
                     + r"(?![A-Za-z0-9])", blob, re.IGNORECASE) is not None


_MAIN_DOCS = [
    "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
    "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
    "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
    "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
    "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
    "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
]

_FIELDS_DOCS = [
    "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
    "L16_COMPLIANCE_PROPERTIES.json", "L17_CHANNEL_SIGNAL_CATALOG.json",
    "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
    "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
    "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
]

# Canonical PROFIBUS-DP facts (IEC 61158 Type 3 / IEC 61784-1 CPF 3).
_BAUD_RATES_KBPS = [9.6, 19.2, 45.45, 93.75, 187.5, 500, 1500, 3000, 6000,
                    12000]
_MAX_BAUD_MBPS = 12
_START_DELIMITERS = {"SD1": "0x10", "SD2": "0x68", "SD3": "0xA2",
                     "SD4": "0xDC"}
_SHORT_ACK = "0xE5"
_END_DELIMITER = "0x16"
_SERVICE_LEVELS = ["DPV0", "DPV1", "DPV2"]
_MAX_STATION_ADDR = 126
_MAX_STATIONS_PER_SEGMENT = 32
_FCS_BITS = 8
_TELEGRAM_FIELDS = ["DA", "SA", "FC", "DSAP", "SSAP", "DU", "FCS"]


# ======================================================================
# MODULE-LEVEL DETECTOR — content-only, structural, with sibling MUTEX.
# ======================================================================
def is_profibus(blob: str) -> bool:
    """Content-only PROFIBUS-DP detector with Modbus / PROFINET / EtherCAT /
    plain-RS-485 sibling MUTEX.

    Fires on the PROFIBUS structural signature: the DP (Decentralized
    Periphery) / PA profile over RS-485 or MBP + the HYBRID token-passing
    (between masters) + master-slave (slave polling) MAC + the SD1/SD2/SD3/SD4
    telegram start delimiters + the DPV0/DPV1/DPV2 service levels + the GSD
    device description + DSAP/SSAP service access points. Defers if the doc is
    Modbus-primary (Function Code + coils/holding registers, simple
    master-slave RTU/ASCII with NO token passing / SD1-SD4 / DPVx / GSD),
    PROFINET-primary (Ethernet-based IO-Controller/IO-Device + GSDML + RT/IRT),
    EtherCAT-primary (EtherCAT datagram + 0x88A4 + Distributed Clocks + FMMU +
    SyncManager), or a generic RS-485 electrical-only PHY guide. Reads ONLY the
    spec text `blob` — never a filename or benchmark name.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- PROFIBUS-only structural tokens. ---
    name_token = "profibus" in low or "process field bus" in low
    dp_profile = ("profibus-dp" in low or "decentralized periphery" in low
                  or "decentralised periphery" in low)
    pa_profile = ("profibus-pa" in low or "process automation" in low)
    # Hybrid MAC: token passing between masters + master-slave polling.
    token_passing = ("token passing" in low or "token-passing" in low
                     or ("token" in low and "logical token ring" in low)
                     or ("token" in low and "target rotation time" in low))
    master_slave = ("master-slave" in low or "master slave" in low
                    or ("master" in low and "slave" in low and "poll" in low))
    hybrid_mac = token_passing and master_slave
    # Telegram start delimiters (the PROFIBUS-only frame signature).
    sd_delims = sum(t in blob for t in ("SD1", "SD2", "SD3", "SD4"))
    sd_hex = ("0x68" in blob and "0xA2" in blob.upper()) or (
        "0x10" in blob and "0xdc" in low)
    telegram_sig = sd_delims >= 3 or (sd_delims >= 2 and sd_hex)
    # DP service levels.
    dpv = sum(t in blob for t in ("DPV0", "DPV1", "DPV2"))
    service_levels = dpv >= 2
    # GSD device description.
    gsd = ("gsd" in low and ("general station description" in low
                             or "device database" in low
                             or "device description" in low
                             or "ident_number" in low
                             or "ident number" in low))
    # Service access points.
    sap = "dsap" in low and "ssap" in low

    profibus_structure = (
        name_token
        and (dp_profile or pa_profile)
        and (
            # Require at least TWO independent PROFIBUS-only structural
            # features so a passing mention of the word never fires.
            sum([hybrid_mac, telegram_sig, service_levels, gsd, sap]) >= 2
        )
    )

    # --- Sibling MUTEX: Modbus-primary. ---
    modbus_primary = (
        ("function code" in low
         and ("holding register" in low or "input register" in low
              or "coil" in low))
        and ("modbus" in low)
        and not (dp_profile or pa_profile or hybrid_mac or telegram_sig
                 or service_levels or gsd or sap)
    )
    if modbus_primary:
        return False

    # --- Sibling MUTEX: PROFINET-primary (defer to the PROFINET agent). ---
    profinet_primary = (
        "profinet" in low
        and ("io-controller" in low or "io controller" in low
             or "io-device" in low or "gsdml" in low
             or ("real-time" in low and "ethernet" in low))
        and not (dp_profile or telegram_sig or service_levels)
    )
    if profinet_primary:
        return False

    # --- Sibling MUTEX: EtherCAT-primary. ---
    ethercat_primary = (
        "ethercat" in low
        and ("0x88a4" in low or "distributed clock" in low
             or "fmmu" in low or "syncmanager" in low
             or "sync manager" in low or "on-the-fly" in low)
        and not (dp_profile or telegram_sig or service_levels or gsd)
    )
    if ethercat_primary:
        return False

    # --- Sibling MUTEX: generic RS-485 electrical-only PHY guide. ---
    rs485_primary = (
        ("rs-485" in low or "rs485" in low or "eia-485" in low
         or " tia-485" in low)
        and ("electrical-only" in low or "electrical only" in low
             or "differential" in low)
        and not (name_token or dp_profile or pa_profile or hybrid_mac
                 or telegram_sig or service_levels or gsd or sap)
    )
    if rs485_primary:
        return False

    return bool(
        profibus_structure
        or (name_token and hybrid_mac and telegram_sig)
        or (name_token and dp_profile and service_levels and (gsd or sap))
    )


def apply_profibus_synth(generated_docs_dir: Path, is_profibus_flag: bool,
                         profibus_ic_name: Optional[str]) -> None:
    """Apply IEC 61158/61784 PROFIBUS-DP synth when the signature matched."""
    if not is_profibus_flag:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if profibus_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = profibus_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = profibus_ic_name
                d["ic_name"] = profibus_ic_name
                _write(q, d)

    _l1(gd)
    _l2(gd)
    _l3(gd)
    _l4(gd)
    _l5(gd)
    _l6(gd)
    _l7(gd)
    _l8_rtl(gd)
    _l8_timing(gd)
    _l9(gd)
    _l10(gd)
    _l11(gd)
    _l12(gd)
    _l13(gd)
    _l14(gd)
    _l15(gd)
    _l16(gd)
    _l17(gd)
    _l18(gd)
    _l19(gd)
    _l20(gd)
    _l21(gd)
    _l22(gd)
    _l23(gd)


# ----------------------------------------------------------------------
# L1 — datasheet header + PHY / MAC facts.
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "PROFIBUS-DP (Process Field Bus, Decentralized Periphery) "
        "Specification")
    d["version"] = "IEC 61158 (Type 3) / IEC 61784-1 (CPF 3)"
    d["revised_date"] = "IEC 61158 / IEC 61784 (former EN 50170 / DIN 19245)"
    d["manufacturer"] = "PROFIBUS & PROFINET International (PI)"
    d["copyright"] = "© PROFIBUS & PROFINET International (PI) / IEC"
    d["abstract"] = (
        "PROFIBUS (Process Field Bus) is an open industrial fieldbus "
        "standardized internationally as the IEC 61158 Type 3 fieldbus and "
        "IEC 61784-1 Communication Profile Family 3 (CPF 3), formerly EN "
        "50170 / DIN 19245. It connects a central controller (a DP master) to "
        "distributed field devices (DP slaves). The dominant profile is "
        "PROFIBUS-DP (Decentralized Periphery), a fast cyclic master-slave "
        "protocol over an RS-485 (or fiber) line at 9.6 kbit/s..12 Mbit/s; "
        "PROFIBUS-PA (Process Automation) uses the same DP protocol on a "
        "bus-powered, intrinsically-safe MBP (Manchester Bus Powered, IEC "
        "61158-2) physical layer at 31.25 kbit/s for hazardous areas; "
        "PROFIBUS-FMS is a legacy peer-to-peer profile. The medium-access "
        "control is HYBRID: active masters pass a token in a logical ring and "
        "the token holder polls its passive slaves (multi-master). Telegrams "
        "are byte-oriented and selected by a Start Delimiter (SD1=0x10, "
        "SD2=0x68, SD3=0xA2, SD4=0xDC), with a Frame Control (FC), "
        "destination/source addresses (DA/SA), optional service access points "
        "(DSAP/SSAP), an 8-bit Frame Check Sequence (FCS) and an End Delimiter "
        "(ED=0x16); a single-byte short acknowledgement is SC=0xE5. DP layers "
        "into DPV0 (cyclic I/O), DPV1 (acyclic read/write + alarms), and DPV2 "
        "(isochronous + slave-to-slave). Devices are described by a GSD file.")
    d["keywords"] = [
        "PROFIBUS", "PROFIBUS-DP", "PROFIBUS-PA", "Process Field Bus",
        "Decentralized Periphery", "IEC 61158", "IEC 61784-1", "fieldbus",
        "RS-485", "MBP", "token passing", "master-slave", "telegram",
        "SD1", "SD2", "SD3", "SD4", "FCS", "DSAP", "SSAP",
        "DPV0", "DPV1", "DPV2", "GSD", "diagnostics", "12 Mbit/s",
    ]
    d["external_pins"] = [
        "A-line / B-line (RS-485 differential pair, RxD/TxD-N pin 8 and "
        "RxD/TxD-P pin 3 on the 9-pin D-sub) — half-duplex differential NRZ "
        "data, 9.6 kbit/s..12 Mbit/s (PROFIBUS-DP).",
        "DGND (pin 5) — data ground / signal reference.",
        "VP (pin 6, +5 V) — supply for the active bus-termination network "
        "(220 ohm with 390 ohm pull-up/pull-down).",
        "Shield — cable screen / protective earth.",
        "MBP bus (PROFIBUS-PA): two-wire Manchester, bus-powered (data + DC "
        "supply on the same pair), 31.25 kbit/s, intrinsically safe.",
        "RTS / direction control — transmit-enable for the RS-485 driver "
        "(half-duplex turnaround).",
    ]
    d["supported_baud_rates_kbps"] = list(_BAUD_RATES_KBPS)
    d["max_baud_rate_Mbps"] = _MAX_BAUD_MBPS
    d["start_delimiters"] = dict(_START_DELIMITERS)
    d["short_acknowledge"] = _SHORT_ACK
    d["end_delimiter"] = _END_DELIMITER
    d["service_levels"] = list(_SERVICE_LEVELS)
    d["max_station_address"] = _MAX_STATION_ADDR
    d["max_stations_per_segment"] = _MAX_STATIONS_PER_SEGMENT
    d["modes_of_operation"] = [
        {"name": "PROFIBUS-DP (Decentralized Periphery)",
         "physical_layer": "RS-485 (IEC 61158-2 Type 3) differential 2-wire "
                           "or fiber",
         "baud_rate": "9.6 kbit/s .. 12 Mbit/s",
         "note": "Fast cyclic master-slave I/O exchange between a DP master "
                 "and distributed slaves; the dominant profile."},
        {"name": "PROFIBUS-PA (Process Automation)",
         "physical_layer": "MBP / IEC 61158-2, Manchester, bus-powered, "
                           "intrinsically safe",
         "baud_rate": "31.25 kbit/s (fixed)",
         "note": "Same DP protocol; bus-powered intrinsically-safe PHY for "
                 "hazardous (Ex) process-industry areas, coupled to the DP "
                 "backbone via a DP/PA coupler or link."},
        {"name": "PROFIBUS-FMS (Fieldbus Message Specification)",
         "physical_layer": "RS-485",
         "baud_rate": "9.6 kbit/s .. 12 Mbit/s",
         "note": "Legacy peer-to-peer profile, largely superseded by DP."},
    ]
    d["key_features"] = [
        "Open industrial fieldbus standardized as IEC 61158 Type 3 / IEC "
        "61784-1 CPF 3 (former EN 50170 / DIN 19245).",
        "PROFIBUS-DP over RS-485 (or fiber) at 9.6 kbit/s..12 Mbit/s; "
        "PROFIBUS-PA over MBP/IEC 61158-2 (Manchester, bus-powered, "
        "intrinsically safe) at 31.25 kbit/s.",
        "Hybrid medium access: token passing among active masters (logical "
        "token ring, Target Rotation Time) + master-slave polling of passive "
        "slaves; multi-master.",
        "Byte-oriented telegrams selected by Start Delimiter SD1=0x10 (fixed, "
        "no data), SD2=0x68 (variable data), SD3=0xA2 (fixed 8-octet data), "
        "SD4=0xDC (token); SC=0xE5 short ACK; ED=0x16 end delimiter.",
        "Telegram fields: DA (destination addr), SA (source addr), FC (frame "
        "control with FCB/FCV frame-count bits), DSAP/SSAP (service access "
        "points), DU (data unit), and an 8-bit arithmetic-checksum FCS.",
        "DP service levels: DPV0 (cyclic I/O data exchange), DPV1 (acyclic "
        "read/write + alarms), DPV2 (isochronous + slave-to-slave DXB).",
        "GSD (General Station Description) device-description file enables "
        "driverless engineering configuration via an Ident_Number.",
        "Standardized layered diagnostics (station / module / channel / "
        "device).",
        "Station addresses 0..126 (127 = broadcast); up to 32 stations per "
        "RS-485 segment, up to 126 per network with repeaters.",
        "Reduced OSI model: PHY (Layer 1) + Fieldbus Data Link FDL (Layer 2) "
        "+ Application Layer (Layer 7); Layers 3-6 empty.",
    ]
    d["topology_summary"] = (
        "Linear bus (daisy-chain) over RS-485 with active termination at both "
        "segment ends; up to 32 stations per segment, extended with repeaters "
        "to up to 126 addressable stations. PROFIBUS-PA uses a trunk-and-spur "
        "/ tree topology bridged to the DP backbone through a DP/PA coupler.")
    d["package_summary"] = (
        "PROFIBUS is a fieldbus communication standard, not a packaged IC. It "
        "is implemented by ASIC / FPGA fieldbus controllers (DP master or DP "
        "slave protocol chips) driving an RS-485 transceiver, typically via a "
        "9-pin D-sub connector.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — functional requirements.
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Industrial fieldbus (IEC 61158 Type 3 / IEC 61784-1 CPF 3). "
        "PROFIBUS-DP is a cyclic master-slave protocol with a hybrid "
        "token-passing + master-slave medium-access control over RS-485 (DP) "
        "or MBP (PA).")
    po["duplex"] = (
        "Half-duplex on the shared RS-485 bus (one differential pair); only "
        "the token holder transmits and a polled slave responds within the "
        "slot time. PROFIBUS-PA is half-duplex on the bus-powered MBP pair.")
    po["multi_master"] = True
    po["medium_access"] = (
        "Hybrid: active stations (masters) pass a token in a logical ring "
        "(ascending address order, bounded by the Target Rotation Time TTR); "
        "the token holder polls its passive stations (slaves), which only "
        "respond when addressed.")
    po["physical_layers"] = [
        {"profile": "DP", "phy": "RS-485 (IEC 61158-2 Type 3), differential "
         "2-wire, half-duplex NRZ", "baud": "9.6 kbit/s .. 12 Mbit/s"},
        {"profile": "PA", "phy": "MBP / IEC 61158-2, Manchester, bus-powered, "
         "intrinsically safe", "baud": "31.25 kbit/s"},
    ]
    po["character_format"] = (
        "11-bit UART character: 1 start bit + 8 data bits + 1 even parity bit "
        "+ 1 stop bit.")
    po["telegram_delimiters"] = dict(_START_DELIMITERS)
    po["short_acknowledge"] = _SHORT_ACK
    po["end_delimiter"] = _END_DELIMITER
    po["telegram_fields"] = list(_TELEGRAM_FIELDS)
    po["fcs"] = "8-bit arithmetic checksum (modulo-256 sum of DA+SA+FC+data)"
    po["service_levels"] = list(_SERVICE_LEVELS)
    po["baud_rates_kbps"] = list(_BAUD_RATES_KBPS)
    po["max_baud_Mbps"] = _MAX_BAUD_MBPS
    po["station_addresses"] = "0..126 (127 = broadcast/global)"
    po["device_description"] = "GSD (General Station Description) file"
    d["functional_requirements"] = [
        {"id": "FR-PHY-01", "text": "PROFIBUS-DP provides a balanced "
         "differential RS-485 two-wire line (A-line / B-line) in a linear "
         "bus, half-duplex NRZ, at selectable baud rates 9.6/19.2/45.45/93.75/"
         "187.5/500 kbit/s and 1.5/3/6/12 Mbit/s, with active 220 ohm bus "
         "termination at both segment ends."},
        {"id": "FR-PHY-02", "text": "PROFIBUS-PA provides an MBP / IEC "
         "61158-2 Manchester-encoded, bus-powered, intrinsically-safe "
         "physical layer at a fixed 31.25 kbit/s for hazardous (Ex) areas, "
         "coupled to the DP backbone via a DP/PA coupler or link."},
        {"id": "FR-MAC-03", "text": "The data-link layer (FDL) uses a hybrid "
         "medium-access method: active masters pass a token in a logical ring "
         "ordered by station address (bounded by the Target Rotation Time "
         "TTR), and the token holder polls its passive slaves in a "
         "master-slave manner; this supports multi-master operation."},
        {"id": "FR-FRAME-04", "text": "Telegrams are byte-oriented and "
         "selected by a Start Delimiter: SD1=0x10 (fixed length, no data), "
         "SD2=0x68 (variable length with data), SD3=0xA2 (fixed length with 8 "
         "data octets), SD4=0xDC (token). A single-byte short acknowledgement "
         "is SC=0xE5; data/fixed telegrams end with an 8-bit FCS and the End "
         "Delimiter ED=0x16."},
        {"id": "FR-FIELD-05", "text": "A telegram carries a Destination "
         "Address (DA), Source Address (SA), Frame Control (FC, including the "
         "Frame Count Bit FCB and FCB-Valid FCV for duplicate detection), "
         "optional Destination/Source Service Access Points (DSAP/SSAP, "
         "present when the address EXT bit is set), a Data Unit (DU, 0..246 "
         "octets), and the 8-bit Frame Check Sequence (FCS)."},
        {"id": "FR-DPV0-06", "text": "DPV0 provides deterministic cyclic data "
         "exchange: the DP Class-1 master parameterizes (Set_Prm) and checks "
         "configuration (Chk_Cfg) of each slave, then cyclically writes "
         "outputs to and reads inputs from the slaves (Data_Exchange), plus "
         "standard diagnostics and Global_Control SYNC/FREEZE."},
        {"id": "FR-DPV1-07", "text": "DPV1 adds acyclic read/write of slave "
         "data records addressed by Slot and Index (MSAC_C1 from a Class-1 "
         "master and MSAC_C2 via an explicit Class-2 connection: "
         "Initiate/Data_Transport/Abort) and acknowledged alarm handling "
         "(process / diagnostic / pull-plug / status / update alarms)."},
        {"id": "FR-DPV2-08", "text": "DPV2 adds isochronous (clock-"
         "synchronous, equidistant) operation and slave-to-slave Data "
         "Exchange Broadcast (DXB, publisher/subscriber), plus time stamping "
         "and redundancy services."},
        {"id": "FR-GSD-09", "text": "Each station is described by a GSD "
         "(General Station Description) file declaring vendor / model / "
         "Ident_Number, supported baud rates and bus timing, the module / "
         "configuration (Cfg) identifier bytes, and the user parameter "
         "bytes, so an engineering tool configures the device driverlessly."},
        {"id": "FR-DIAG-10", "text": "A slave returns layered diagnostics in "
         "response to Slave_Diag (Get_Diag): station-related (6 mandatory "
         "bytes incl. master address and Ident_Number), module/identifier-"
         "related, channel-related (per-channel error type), and "
         "device/extended (manufacturer-specific)."},
        {"id": "FR-FSM-11", "text": "A DP slave follows the startup state "
         "machine POWER_ON -> Wait_Prm -> Wait_Cfg -> Data_Exchange driven by "
         "the master; a watchdog supervises the master's cyclic access and a "
         "Global_Control CLEAR or watchdog timeout forces a safe/cleared "
         "output state."},
        {"id": "FR-ADDR-12", "text": "Station addresses span 0..126 (7-bit DA/"
         "SA; 127 = broadcast). Up to 32 stations attach per RS-485 segment "
         "without a repeater and up to 126 addressable stations per network "
         "with repeaters; address 126 is the delivery default used with "
         "Set_Slave_Address."},
    ]
    d["error_response_conditions"] = [
        "FCS (8-bit checksum) mismatch — the telegram is rejected (no/wrong "
        "response).",
        "Slot-time (TSL) expiry — the responder did not answer in time; the "
        "master retries.",
        "Frame Count Bit (FCB/FCV) mismatch — duplicate or lost telegram "
        "detection.",
        "Parameterization (Set_Prm) or configuration (Chk_Cfg) mismatch — the "
        "slave does not enter Data_Exchange (stays in Wait_Prm / Wait_Cfg).",
        "Watchdog timeout — the slave loses cyclic access from its master and "
        "goes to a safe/cleared output state.",
        "New diagnostics available — the slave flags it and the master "
        "re-reads the full diagnostic telegram (Slave_Diag).",
    ]
    d["compliance_requirements"] = [
        "RS-485 (DP) and/or MBP (PA) physical layer per IEC 61158-2.",
        "Hybrid token-passing (masters) + master-slave (slave polling) MAC.",
        "Telegram family SD1/SD2/SD3/SD4 + SC short ACK + ED=0x16; "
        "DA/SA/FC/DSAP/SSAP/DU/FCS fields; 8-bit checksum FCS.",
        "Baud rates 9.6 kbit/s..12 Mbit/s (DP); 31.25 kbit/s (PA).",
        "DP service levels DPV0 (cyclic) and, where claimed, DPV1 (acyclic + "
        "alarms) and DPV2 (isochronous + slave-to-slave).",
        "GSD device description with a PI-assigned Ident_Number.",
        "Standardized layered diagnostics (station/module/channel/device).",
        "Station addressing 0..126 (127 broadcast); <=32 per segment, <=126 "
        "per network.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — command / protocol model.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Byte-oriented, telegram-based master-slave fieldbus protocol with a "
        "hybrid token-passing medium-access control. The token holder (a "
        "master) sends a request telegram to a slave (selected by Destination "
        "Address and Service Access Point); the slave responds with a data "
        "telegram or a short acknowledgement within the slot time. Each "
        "telegram is framed by a Start Delimiter (SD1/SD2/SD3/SD4), carries "
        "DA/SA/FC and optional DSAP/SSAP, and (for data/fixed telegrams) ends "
        "with an 8-bit FCS and ED=0x16.")
    d["medium_access_control"] = {
        "token_passing": "Active stations (masters) form a logical token ring "
                         "in ascending station-address order; only the token "
                         "holder may initiate message cycles, bounded by the "
                         "Target Rotation Time (TTR). The Token telegram (SD4) "
                         "passes the token; GAP/Live-List maintenance admits "
                         "or removes stations.",
        "master_slave": "While holding the token a master polls its assigned "
                        "slaves (request -> response within the slot time "
                        "TSL); passive slaves never initiate transmission.",
        "classes": "DP Class-1 master (DPM1) runs the cyclic data exchange; "
                   "DP Class-2 master (DPM2) is an engineering/diagnostic/"
                   "configuration device.",
    }
    d["telegram_types"] = [
        {"name": "SD1 fixed-length, no data", "start_delimiter": "0x10",
         "format": "SD1 | DA | SA | FC | FCS | ED",
         "purpose": "Poll, FDL status request, diagnostic request."},
        {"name": "SD2 variable-length with data", "start_delimiter": "0x68",
         "format": "SD2 | LE | LEr | SD2 | DA | SA | FC | (DSAP | SSAP) | "
                   "DU... | FCS | ED",
         "purpose": "Normal data telegram (cyclic I/O, acyclic services); LE "
                    "is the length, repeated as LEr."},
        {"name": "SD3 fixed-length with 8 data octets", "start_delimiter":
         "0xA2", "format": "SD3 | DA | SA | FC | DU(8) | FCS | ED",
         "purpose": "Fixed 8-octet data telegram."},
        {"name": "SD4 token", "start_delimiter": "0xDC",
         "format": "SD4 | DA | SA",
         "purpose": "Token pass between masters (no FC/FCS/ED)."},
        {"name": "SC short acknowledgement", "start_delimiter": "0xE5",
         "format": "single byte (0xE5)",
         "purpose": "Positive short ACK with no data."},
    ]
    d["telegram_fields"] = [
        {"name": "DA", "full": "Destination Address",
         "purpose": "Station address 0..127 of the receiver; bit 7 (EXT) "
                    "indicates a DSAP byte follows."},
        {"name": "SA", "full": "Source Address",
         "purpose": "Station address of the sender; EXT bit indicates an SSAP "
                    "byte follows."},
        {"name": "FC", "full": "Frame Control",
         "purpose": "Frame type (SRD/SDN/Request-FDL-Status/Token), Frame "
                    "Count Bit (FCB) + FCB-Valid (FCV), and station type / "
                    "FDL state."},
        {"name": "DSAP", "full": "Destination Service Access Point",
         "purpose": "Selects the DP service at the receiver (present when "
                    "DA.EXT=1)."},
        {"name": "SSAP", "full": "Source Service Access Point",
         "purpose": "Selects the service at the sender (present when SA.EXT=1)."
                    " Default SAP is used for cyclic Data_Exchange."},
        {"name": "DU", "full": "Data Unit",
         "purpose": "The application payload / PDU, 0..246 octets."},
        {"name": "FCS", "full": "Frame Check Sequence",
         "purpose": "8-bit arithmetic checksum (modulo-256 sum of "
                    "DA+SA+FC+data); NOT a CRC."},
        {"name": "ED", "full": "End Delimiter",
         "purpose": "End of telegram = 0x16."},
    ]
    d["service_access_points"] = [
        {"sap": 54, "service": "Master-to-Master (DPM2)"},
        {"sap": 55, "service": "Set_Slave_Address"},
        {"sap": 56, "service": "Read_Inputs"},
        {"sap": 57, "service": "Read_Outputs"},
        {"sap": 58, "service": "Global_Control (Sync / Freeze)"},
        {"sap": 59, "service": "Get_Configuration"},
        {"sap": 60, "service": "Slave_Diagnosis (Get_Diag)"},
        {"sap": 61, "service": "Set_Parameters (Set_Prm)"},
        {"sap": 62, "service": "Check_Configuration (Chk_Cfg)"},
        {"sap": "Default", "service": "Data_Exchange (cyclic I/O)"},
    ]
    d["dp_services"] = [
        {"service": "Set_Prm", "level": "DPV0",
         "purpose": "Parameterize a slave at startup."},
        {"service": "Chk_Cfg", "level": "DPV0",
         "purpose": "Check the slave's I/O configuration."},
        {"service": "Data_Exchange", "level": "DPV0",
         "purpose": "Cyclic write-outputs / read-inputs."},
        {"service": "Slave_Diag (Get_Diag)", "level": "DPV0",
         "purpose": "Read layered slave diagnostics."},
        {"service": "Global_Control", "level": "DPV0",
         "purpose": "Broadcast SYNC (freeze outputs) / FREEZE (freeze "
                    "inputs) to slave groups."},
        {"service": "Acyclic Read / Write", "level": "DPV1",
         "purpose": "Read/write a data record by Slot and Index "
                    "(MSAC_C1 / MSAC_C2)."},
        {"service": "Alarm", "level": "DPV1",
         "purpose": "Acknowledged process / diagnostic / pull-plug / status / "
                    "update alarms."},
        {"service": "Isochronous", "level": "DPV2",
         "purpose": "Clock-synchronous equidistant cycle."},
        {"service": "Data Exchange Broadcast (DXB)", "level": "DPV2",
         "purpose": "Slave-to-slave publisher/subscriber."},
    ]
    d["fcs"] = {
        "fcs_bits": _FCS_BITS,
        "algorithm": "arithmetic checksum (modulo-256 sum of DA+SA+FC+data)",
        "note": "PROFIBUS uses an 8-bit arithmetic FCS, not a polynomial CRC.",
    }
    d["addressing"] = {
        "station_addresses": "0..126 (7-bit); 127 = broadcast/global",
        "service_access_points": "DSAP / SSAP select the L7 service when the "
                                "address EXT bit is set; default SAP = "
                                "cyclic Data_Exchange.",
    }
    d["byte_oriented"] = True
    d["frame_oriented"] = True
    d["connection_oriented"] = False
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — register / configuration parameter model.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "PROFIBUS is a fieldbus protocol rather than a fixed memory-mapped "
        "register IC. A slave's behaviour is configured by the master via the "
        "Set_Prm (parameter) and Chk_Cfg (configuration) telegrams whose "
        "contents derive from the device's GSD file; status is read with "
        "Slave_Diag. The groups below are the canonical PROFIBUS "
        "configuration / status surfaces.")
    d["register_access"] = {
        "transport": "Set_Prm / Chk_Cfg / Slave_Diag DP services (cyclic "
                     "startup) + DPV1 acyclic Read/Write by Slot/Index",
        "purpose": "Parameterize and configure a slave; read its layered "
                   "diagnostics and data records.",
    }
    d["register_groups"] = [
        {"group": "Parameterization (Set_Prm, SAP 61)", "fields": [
            "Station status / watchdog enable and time",
            "Min TSDR (station delay of responder)",
            "Ident_Number (PI-assigned 16-bit device identity)",
            "Group assignment (for Global_Control SYNC/FREEZE groups)",
            "User parameter bytes (device/GSD-defined), DPV1/DPV2 enable "
            "flags"]},
        {"group": "Configuration (Chk_Cfg, SAP 62)", "fields": [
            "Module configuration (Cfg) identifier bytes",
            "Per-module input/output data length and consistency",
            "Module list (must match the GSD)"]},
        {"group": "Diagnostics (Slave_Diag, SAP 60)", "fields": [
            "Station status 1/2/3",
            "Master address (parameterizing master)",
            "Ident_Number",
            "Module/identifier diagnostics (bit per module)",
            "Channel-related diagnostics (per-channel error type)",
            "Device/extended (manufacturer) diagnostics"]},
        {"group": "DPV1 data records", "fields": [
            "Acyclic Read/Write addressed by Slot and Index",
            "Alarm acknowledge"]},
    ]
    d["protocol_fields"] = {
        "fcs_bits": _FCS_BITS,
        "service_levels": list(_SERVICE_LEVELS),
        "baud_rates_kbps": list(_BAUD_RATES_KBPS),
        "max_station_address": _MAX_STATION_ADDR,
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — analog / physical signaling spec.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "PROFIBUS-DP uses a balanced (differential) RS-485 two-wire line "
        "(A-line / B-line), half-duplex NRZ, with active 220 ohm termination "
        "at both segment ends (390 ohm pull-up to VP/+5 V and 390 ohm "
        "pull-down to DGND). The transceiver direction is switched per "
        "telegram (RTS). PROFIBUS-PA uses MBP / IEC 61158-2: a "
        "Manchester-encoded, bus-powered signal (current modulation +-9 mA "
        "around a DC base current) at 31.25 kbit/s, intrinsically safe.")
    d["modulation"] = (
        "DP: differential NRZ on RS-485 (A-line / B-line), half-duplex. "
        "PA: Manchester-encoded current modulation on the bus-powered MBP "
        "pair.")
    d["clocking"] = (
        "Asynchronous UART character timing on RS-485 (DP): 11-bit character "
        "(1 start + 8 data + 1 even parity + 1 stop), baud-rate-selected. "
        "PA: synchronous Manchester self-clocking at 31.25 kbit/s.")
    d["transmitter_specs_canonical"] = {
        "dp_phy": "RS-485 (EIA-485 / IEC 61158-2 Type 3), differential 2-wire",
        "dp_signaling": "differential NRZ, half-duplex",
        "dp_baud_rates_kbps": list(_BAUD_RATES_KBPS),
        "dp_max_baud_Mbps": _MAX_BAUD_MBPS,
        "termination": "220 ohm with 390 ohm pull-up to +5 V (VP) and 390 ohm "
                      "pull-down to DGND at both segment ends",
        "character_format": "1 start + 8 data + 1 even parity + 1 stop "
                            "(11 bits)",
        "pa_phy": "MBP / IEC 61158-2, Manchester, bus-powered, intrinsically "
                  "safe",
        "pa_baud": "31.25 kbit/s",
    }
    d["receiver_specs_canonical"] = {
        "dp_signaling": "differential RS-485 receiver",
        "fail_safe": "active termination provides a defined idle level",
        "max_stations_per_segment": _MAX_STATIONS_PER_SEGMENT,
    }
    d["baud_rates_kbps"] = list(_BAUD_RATES_KBPS)
    d["max_baud_rate_Mbps"] = _MAX_BAUD_MBPS
    d["cable_and_distance"] = {
        "cable": "shielded twisted pair (PROFIBUS cable type A)",
        "segment_length": "up to 1200 m at 9.6-187.5 kbit/s; down to 100 m at "
                          "12 Mbit/s; repeaters extend the network",
        "stations": "up to 32 per segment without a repeater; up to 126 "
                   "addressable per network with repeaters",
    }
    d["encoding_role_in_analog"] = (
        "DP relies on standard RS-485 differential NRZ with an 11-bit UART "
        "character (even parity per character) and active bus termination for "
        "signal integrity; frame integrity comes from the 8-bit FCS checksum. "
        "PA uses Manchester encoding for self-clocking and DC balance on the "
        "bus-powered, intrinsically-safe MBP line.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — control logic / FSMs.
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_slave"] = [
        {"name": "POWER_ON", "description": "Slave powered; awaiting the "
         "master."},
        {"name": "Wait_Prm", "description": "Waiting for Set_Parameters "
         "(Set_Prm) from the master."},
        {"name": "Wait_Cfg", "description": "Parameterized; waiting for "
         "Check_Configuration (Chk_Cfg)."},
        {"name": "Data_Exchange", "description": "Configured; cyclic I/O "
         "exchange running with watchdog supervision."},
    ]
    d["fsm_states_mac_master"] = [
        {"name": "Listen_Token", "description": "Listening for the token / GAP "
         "maintenance; not yet in the logical ring."},
        {"name": "Active_Idle", "description": "In the ring, waiting to "
         "receive the token."},
        {"name": "Use_Token", "description": "Holding the token; polling "
         "slaves and initiating message cycles until the token-hold time "
         "expires."},
        {"name": "Pass_Token", "description": "Forwarding the token (SD4) to "
         "the successor in ascending address order."},
    ]
    d["fsm_hints"] = {
        "trigger": "Slave: POWER_ON -> Wait_Prm (Set_Prm) -> Wait_Cfg "
        "(Chk_Cfg) -> Data_Exchange. Master MAC: Listen_Token -> Active_Idle "
        "-> Use_Token (poll) -> Pass_Token (SD4).",
        "rule": "Only the token holder transmits; a polled slave must respond "
        "within the slot time (TSL); the slave watchdog supervises the "
        "master's cyclic access.",
        "abort": "A Global_Control CLEAR, a parameterization/configuration "
        "mismatch, or a watchdog timeout returns the slave to a safe/cleared "
        "output state (back toward Wait_Prm).",
    }
    d["anti_deadlock_rule"] = (
        "The Target Rotation Time (TTR) bounds one token rotation so no master "
        "can monopolize the bus; each master must forward the token (SD4) when "
        "its token-hold time expires. GAP/Live-List maintenance detects "
        "added/removed stations and reforms the logical ring after a lost "
        "token (timeout) so the ring cannot stall indefinitely.")
    d["exit_from_reset_or_poweron"] = (
        "On power-up / reset a slave enters POWER_ON then Wait_Prm and waits "
        "for the master to parameterize (Set_Prm) and configure (Chk_Cfg) it "
        "before cyclic Data_Exchange begins; outputs stay in the safe/cleared "
        "state until configuration completes.")
    d["default_ready_state_recommendation"] = {
        "slave": "Hold outputs in the safe/cleared state until Set_Prm + "
                 "Chk_Cfg complete and Data_Exchange begins.",
        "master": "Maintain the logical token ring (GAP maintenance) and poll "
                  "slaves only while holding the token.",
    }
    d["configurations"] = [
        {"name": "Single-master", "description": "One DP Class-1 master "
         "polling its slaves (pure master-slave)."},
        {"name": "Multi-master", "description": "Several masters share the bus "
         "via token passing; each polls its own slaves."},
        {"name": "DPM1 + DPM2", "description": "A Class-1 master runs cyclic "
         "I/O; a Class-2 master performs engineering/diagnostics."},
        {"name": "DP/PA coupled", "description": "A DP/PA coupler or link "
         "bridges a 31.25 kbit/s PA segment onto the RS-485 DP backbone."},
    ]
    d["timing_dependency_rule"] = (
        "The slot time (TSL) bounds how long a master waits for a response; "
        "TSDR (station delay of responder) bounds how soon a responder may "
        "reply; TID1/TID2 are idle times; TTR bounds the token rotation. These "
        "timers scale with baud rate and are derived from the slaves' GSD bus "
        "timing.")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — test / debug / observability.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "Slave_Diag (Get_Diag)", "purpose": "Reads layered slave "
         "diagnostics: station status 1/2/3, master address, Ident_Number, "
         "module and channel diagnostics."},
        {"name": "FDL status request (SD1)", "purpose": "Queries a station's "
         "FDL state (e.g. ready to enter the ring / slave)."},
        {"name": "Get_Configuration", "purpose": "Reads back the slave's "
         "current module configuration."},
        {"name": "Live List / GAP maintenance", "purpose": "Observes which "
         "stations are present on the bus."},
        {"name": "FCS / response status", "purpose": "Telegram checksum "
         "pass/fail and presence/absence of the expected response."},
    ]
    d["error_detection_mechanisms"] = [
        "8-bit FCS checksum per data/fixed telegram detects corruption.",
        "Per-character even parity (the 11-bit UART character).",
        "Frame Count Bit (FCB/FCV) detects duplicate or lost telegrams.",
        "Slot-time (TSL) timeout detects a missing response.",
        "Watchdog timeout detects loss of cyclic master access at the slave.",
        "Layered diagnostics (station/module/channel/device) report device "
        "faults.",
    ]
    d["test_modes"] = [
        {"name": "Bus monitor / analyzer", "purpose": "Capture and decode "
         "telegrams (SD1-SD4) on the wire for protocol debug."},
        {"name": "Live List scan", "purpose": "Enumerate present stations and "
         "their FDL state."},
        {"name": "Diagnostic polling", "purpose": "Repeatedly Get_Diag a slave "
         "to track station/module/channel faults."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "New diagnostics available", "trigger": "A slave flags it; "
         "the master re-reads the full diagnostic telegram."},
        {"event": "DPV1 alarm", "trigger": "Process / diagnostic / pull-plug / "
         "status / update alarm (acknowledged)."},
        {"event": "Response timeout", "trigger": "No response within the slot "
         "time (TSL)."},
        {"event": "Watchdog timeout", "trigger": "Loss of cyclic access at the "
         "slave."},
        {"event": "Token lost", "trigger": "Ring reform via GAP maintenance."},
    ]
    d["notes"] = (
        "PROFIBUS exposes its protocol-level test/debug surface through "
        "Slave_Diag (layered diagnostics), the FDL status request, "
        "Get_Configuration, the Live List, per-telegram FCS/parity, and the "
        "MAC timers. Chip-level JTAG/scan/BIST remain controller-vendor / SoC "
        "concerns.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    wp.update({
        "PROFIBUS_STANDARD": "IEC 61158 (Type 3) / IEC 61784-1 (CPF 3)",
        "DP_PHY": "RS-485 (differential 2-wire, half-duplex NRZ)",
        "PA_PHY": "MBP / IEC 61158-2 (Manchester, bus-powered, 31.25 kbit/s)",
        "CHARACTER_BITS": 11,
        "CHARACTER_FORMAT": "1 start + 8 data + 1 even parity + 1 stop",
        "BAUD_RATES_KBPS": list(_BAUD_RATES_KBPS),
        "MAX_BAUD_MBPS": _MAX_BAUD_MBPS,
        "SD1": _START_DELIMITERS["SD1"],
        "SD2": _START_DELIMITERS["SD2"],
        "SD3": _START_DELIMITERS["SD3"],
        "SD4": _START_DELIMITERS["SD4"],
        "SC_SHORT_ACK": _SHORT_ACK,
        "ED_END_DELIMITER": _END_DELIMITER,
        "FCS_BITS": _FCS_BITS,
        "TELEGRAM_FIELDS": list(_TELEGRAM_FIELDS),
        "SERVICE_LEVELS": list(_SERVICE_LEVELS),
        "MAX_STATION_ADDRESS": _MAX_STATION_ADDR,
        "MAX_STATIONS_PER_SEGMENT": _MAX_STATIONS_PER_SEGMENT,
        "MAX_DATA_UNIT_OCTETS": 246,
        "MULTI_MASTER": True,
        "HALF_DUPLEX": True,
        "MEDIUM_ACCESS": "hybrid token-passing + master-slave",
    })
    d["frame_format_constants"] = {
        "start_delimiters": dict(_START_DELIMITERS),
        "short_ack": _SHORT_ACK,
        "end_delimiter": _END_DELIMITER,
        "fcs_bits": _FCS_BITS,
        "fcs_algorithm": "8-bit arithmetic checksum (modulo-256)",
        "max_data_unit_octets": 246,
    }
    d["fcs_constants"] = {
        "telegram_fcs": {"width_bits": _FCS_BITS,
                         "algorithm": "arithmetic checksum (modulo-256 sum of "
                         "DA+SA+FC+data)"},
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    kc.update({
        "is_serial": True,
        "is_differential": True,
        "is_half_duplex": True,
        "is_multi_master": True,
        "is_connection_oriented": False,
        "medium_access": "hybrid token-passing (masters) + master-slave "
                         "(slaves)",
        "character_bits": 11,
        "parity": "even",
        "baud_rates_kbps": list(_BAUD_RATES_KBPS),
        "max_baud_Mbps": _MAX_BAUD_MBPS,
        "start_delimiters": dict(_START_DELIMITERS),
        "short_ack": _SHORT_ACK,
        "end_delimiter": _END_DELIMITER,
        "telegram_fields": list(_TELEGRAM_FIELDS),
        "fcs_bits": _FCS_BITS,
        "service_levels": list(_SERVICE_LEVELS),
        "max_station_address": _MAX_STATION_ADDR,
        "gsd_device_description": True,
    })
    d["default_signal_values_when_idle"] = {
        "bus_idle": "Active RS-485 termination holds a defined idle level "
                    "between telegrams.",
        "no_token": "A master does not transmit unless it holds the token.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing waveform.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["bit_waveform"] = {
        "dp_modulation": "differential NRZ on RS-485 (A-line / B-line), "
                         "half-duplex",
        "character": "11-bit UART character: 1 start + 8 data + 1 even parity "
                     "+ 1 stop",
        "baud_rates_kbps": list(_BAUD_RATES_KBPS),
        "pa_modulation": "Manchester self-clocking on the MBP pair at 31.25 "
                         "kbit/s",
    }
    d["telegram_waveform"] = {
        "sd1": "SD1(0x10) | DA | SA | FC | FCS | ED(0x16)",
        "sd2": "SD2(0x68) | LE | LEr | SD2 | DA | SA | FC | (DSAP|SSAP) | "
               "DU... | FCS | ED(0x16)",
        "sd3": "SD3(0xA2) | DA | SA | FC | DU(8) | FCS | ED(0x16)",
        "sd4": "SD4(0xDC) | DA | SA  (token; no FC/FCS/ED)",
        "sc": "SC(0xE5) single-byte short acknowledgement",
    }
    d["mac_waveform"] = {
        "token_pass": "A master holding the token polls slaves, then passes "
                      "the token (SD4) to its successor when the token-hold "
                      "time expires.",
        "poll_response": "Request telegram -> slave responds within the slot "
                         "time (TSL); TSDR bounds the responder's earliest "
                         "reply.",
        "timers": ["TSL (slot time)", "TSDR (station delay of responder)",
                   "TID1/TID2 (idle times)", "TTR (target rotation time)"],
    }
    d["general_timing_rule"] = (
        "Only the token holder transmits; a polled slave must respond within "
        "TSL and not before TSDR. The Target Rotation Time (TTR) bounds one "
        "token rotation so the bus stays deterministic; all timers scale with "
        "the configured baud rate.")
    d["data_rate_waveform"] = {
        "dp_baud_rates_kbps": list(_BAUD_RATES_KBPS),
        "dp_max_Mbps": _MAX_BAUD_MBPS,
        "pa_baud_kbps": 31.25,
        "modulation": {"DP": "differential NRZ (RS-485)",
                       "PA": "Manchester (MBP)"},
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — integration spec.
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Industrial fieldbus controller: a PROFIBUS-DP master or slave "
        "implementing the RS-485 (DP) / MBP (PA) physical layer, the Fieldbus "
        "Data Link (FDL) with hybrid token-passing + master-slave MAC, the "
        "SD1/SD2/SD3/SD4 telegram framing with DA/SA/FC/DSAP/SSAP/FCS, and the "
        "DP application services (DPV0 cyclic, DPV1 acyclic + alarms, DPV2 "
        "isochronous + slave-to-slave) — connecting a central controller to "
        "distributed field I/O over a linear bus.")
    d["topology_description"] = (
        "Master / slave stations on a linear RS-485 bus (daisy-chain) with "
        "active termination at both ends; up to 32 stations per segment, "
        "extended with repeaters to up to 126 addressable stations. PA "
        "segments (MBP, 31.25 kbit/s) attach via a DP/PA coupler or link.")
    io = _ensure_dict(d, "integration_overview")
    io.update({
        "profibus_standard": "IEC 61158 (Type 3) / IEC 61784-1 (CPF 3)",
        "profiles": ["PROFIBUS-DP", "PROFIBUS-PA", "PROFIBUS-FMS (legacy)"],
        "dp_phy": "RS-485, 9.6 kbit/s..12 Mbit/s",
        "pa_phy": "MBP / IEC 61158-2, Manchester, 31.25 kbit/s, intrinsically "
                  "safe",
        "medium_access": "hybrid token-passing (masters) + master-slave "
                         "(slaves)",
        "telegram_delimiters": dict(_START_DELIMITERS),
        "service_levels": list(_SERVICE_LEVELS),
        "device_description": "GSD (General Station Description)",
        "max_station_address": _MAX_STATION_ADDR,
        "multi_master": True,
        "interfaces": {"bus": "RS-485 A-line/B-line (or MBP)",
                       "host": "controller I/O / process image",
                       "engineering": "GSD-driven configuration tool (DPM2)"},
    })
    d["interface_categories"] = [
        "Bus interface — RS-485 differential pair (DP) or MBP pair (PA).",
        "MAC interface — token ring (masters) + slave polling.",
        "Service interface — DPV0 cyclic / DPV1 acyclic+alarm / DPV2 "
        "isochronous.",
        "Engineering interface — GSD-based configuration (Set_Prm / Chk_Cfg).",
    ]
    d["interconnect_topologies_supported"] = [
        "Linear bus (daisy-chain) RS-485 with active termination.",
        "Single-master (one DPM1 polling slaves).",
        "Multi-master (token passing among masters).",
        "Repeated/segmented network (repeaters extend reach and station "
        "count).",
        "DP backbone with coupled PA (MBP) segments via DP/PA coupler.",
    ]
    d["default_signal_values_when_omitted"] = (
        "Bus idle is held at a defined level by the active termination; a "
        "slave keeps outputs in the safe/cleared state until Set_Prm + "
        "Chk_Cfg complete; a master transmits only while holding the token.")
    d["soc_dependent_items"] = [
        "Master vs slave role (DPM1 / DPM2 / DP slave).",
        "Station address (0..126) and group assignment.",
        "Supported baud rate(s) and derived bus timing (from GSD).",
        "Module / I/O configuration (Cfg bytes) and user parameters.",
        "DPV1 / DPV2 capability.",
        "RS-485 transceiver, connector, termination and (for PA) DP/PA "
        "coupler hardware.",
    ]
    d["device_classes_examples"] = [
        "DP Class-1 master (DPM1) — PLC / controller",
        "DP Class-2 master (DPM2) — engineering / diagnostic tool",
        "DP slave — distributed remote I/O / drive / sensor",
        "DP/PA coupler or link",
        "Repeater",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — derived test cases.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the specification defines protocol behaviors rather than an "
        "embedded testbench; the categories below are derived from the spec.")
    d["derived_compliance_test_categories"] = [
        "PHY: RS-485 differential signaling at each baud rate (9.6 kbit/s..12 "
        "Mbit/s); active termination; 11-bit character with even parity.",
        "PA PHY: MBP Manchester, bus-powered, intrinsically-safe at 31.25 "
        "kbit/s.",
        "MAC token passing: logical-ring formation, GAP/Live-List, Target "
        "Rotation Time, token loss / ring reform.",
        "MAC master-slave: polling, slot-time (TSL) response, TSDR.",
        "Telegram framing: SD1(0x10) / SD2(0x68) / SD3(0xA2) / SD4(0xDC) / "
        "SC(0xE5) / ED(0x16); LE/LEr length consistency.",
        "Telegram fields: DA / SA / FC (FCB/FCV) / DSAP / SSAP / FCS.",
        "FCS: 8-bit checksum error injection and detection.",
        "DPV0: Set_Prm, Chk_Cfg, Data_Exchange cyclic loop, Global_Control "
        "SYNC/FREEZE.",
        "DPV1: acyclic Read/Write by Slot/Index; alarm handling.",
        "DPV2: isochronous cycle; slave-to-slave DXB.",
        "Slave startup FSM: POWER_ON -> Wait_Prm -> Wait_Cfg -> "
        "Data_Exchange.",
        "Diagnostics: station / module / channel / device; new-diagnostics "
        "flag.",
        "Addressing: 0..126; Set_Slave_Address (default 126); broadcast 127.",
        "GSD: Ident_Number match; module/Cfg consistency with Chk_Cfg.",
        "Watchdog timeout -> safe/cleared output state.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — OTP / factory-burned equivalents.
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "Ident_Number (16-bit)",
         "location": "device firmware / GSD",
         "note": "PI-assigned device identity matched at Set_Prm; "
                 "manufacturer-fixed, not a protocol OTP concept."},
        {"field": "Station address",
         "location": "device configuration (DIP switches / Set_Slave_Address)",
         "note": "0..126; delivery default 126; set by switches or "
                 "Set_Slave_Address (SAP 55)."},
        {"field": "Supported baud rates / bus timing",
         "location": "GSD file",
         "note": "Declared in the GSD; the master derives bus timing from it."},
        {"field": "Module / Cfg identifier bytes",
         "location": "GSD file",
         "note": "Describe I/O lengths and consistency; checked by Chk_Cfg."},
    ]
    d["notes"] = (
        "PROFIBUS does not define OTP/fuse content as a protocol concept. The "
        "Ident_Number, supported baud rates / bus timing, and module "
        "configuration are device attributes declared in the GSD file; the "
        "station address is set by switches or Set_Slave_Address. An "
        "implementation may store these in non-volatile memory, but the "
        "standard only requires they be configurable / discoverable.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — behavioral sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["slave_startup_sequence"] = [
        "1. POWER_ON: the slave powers up and waits for its master.",
        "2. Wait_Prm: the master sends Set_Parameters (Set_Prm, SAP 61) — "
        "watchdog, min TSDR, group, Ident_Number, user parameters.",
        "3. Wait_Cfg: the master sends Check_Configuration (Chk_Cfg, SAP 62); "
        "the slave's module list must match.",
        "4. Data_Exchange: cyclic write-outputs / read-inputs begins; the "
        "watchdog supervises the master's access.",
    ]
    d["token_pass_sequence"] = [
        "1. A master receives the token (SD4) from its predecessor.",
        "2. While holding the token it initiates message cycles (polls "
        "slaves) until its token-hold time expires.",
        "3. It passes the token (SD4) to the successor in ascending "
        "station-address order; the highest master wraps to the lowest.",
        "4. GAP/Live-List maintenance periodically checks for added/removed "
        "stations.",
    ]
    d["cyclic_data_exchange_sequence"] = [
        "1. The DP Class-1 master sends a Data_Exchange request telegram "
        "(default SAP) carrying the output data for a slave.",
        "2. The slave applies the outputs and responds with its input data "
        "within the slot time (TSL).",
        "3. The master repeats this for each slave every bus cycle.",
        "4. If a slave flags new diagnostics, the master issues Slave_Diag "
        "(Get_Diag, SAP 60) to read the full diagnostic telegram.",
    ]
    d["dpv1_acyclic_sequence"] = [
        "1. In the gaps of the cyclic cycle the master issues an acyclic "
        "READ or WRITE addressed by Slot and Index (MSAC_C1).",
        "2. A Class-2 master first opens an explicit connection (Initiate), "
        "transfers data (Data_Transport), then aborts/closes it (Abort).",
        "3. Alarms (process/diagnostic/pull-plug/status/update) are "
        "transported and acknowledged.",
    ]
    d["global_control_sequence"] = [
        "1. The master broadcasts Global_Control (SAP 58) to a slave group.",
        "2. SYNC freezes the outputs (apply simultaneously); FREEZE freezes "
        "the inputs (sample simultaneously).",
        "3. UNSYNC / UNFREEZE release the respective freeze.",
    ]
    d["fault_recovery_sequence"] = [
        "1. A slot-time (TSL) timeout or FCS error makes the master retry the "
        "telegram.",
        "2. A watchdog timeout at the slave forces outputs to the "
        "safe/cleared state and the slave drops back toward Wait_Prm.",
        "3. A lost token triggers GAP-maintenance ring reform among the "
        "masters.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — lab calibration / measurement targets.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "RS-485 signal levels / eye per baud", "purpose": "Verify "
         "the differential A/B levels and timing at each baud rate up to 12 "
         "Mbit/s."},
        {"name": "Bus termination", "purpose": "Confirm the 220 ohm active "
         "termination (390 ohm pull-up/pull-down) at both segment ends."},
        {"name": "Character timing / parity", "purpose": "Validate the 11-bit "
         "UART character with even parity at the selected baud."},
        {"name": "MAC timers", "purpose": "Measure slot time (TSL), TSDR, "
         "idle times and Target Rotation Time (TTR)."},
        {"name": "PA MBP signaling", "purpose": "Measure the Manchester "
         "current modulation (+-9 mA), DC supply and intrinsic-safety power "
         "budget at 31.25 kbit/s."},
        {"name": "FCS coverage", "purpose": "Inject telegram errors and "
         "confirm the 8-bit FCS detects them."},
        {"name": "Segment length / station count", "purpose": "Verify reach "
         "vs baud and up to 32 stations per segment."},
    ]
    d["notes"] = (
        "PROFIBUS characterization centers on the RS-485 differential "
        "signaling and termination at each baud rate (and the MBP current "
        "signaling / intrinsic-safety budget for PA), the 11-bit character "
        "with even parity, the MAC timers (TSL/TSDR/TTR), and the 8-bit FCS. "
        "Conformance is established by PI (PROFIBUS & PROFINET International) "
        "certification testing.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — protocol versioning.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "PROFIBUS — IEC 61158 (Type 3) / IEC 61784-1 (CPF 3); DP service "
        "levels DPV0 / DPV1 / DPV2")
    f["previous_versions"] = [
        "DIN 19245 (German national standard) — original PROFIBUS (FMS/DP/PA).",
        "EN 50170 (European standard) — PROFIBUS.",
        "IEC 61158 / IEC 61784 — international fieldbus standardization "
        "(PROFIBUS = Type 3 / CPF 3).",
    ]
    f["key_changes"] = [
        {"version": "DPV0", "summary": "Base level: cyclic master-slave I/O "
         "data exchange (Set_Prm / Chk_Cfg / Data_Exchange), standard "
         "diagnostics, Global_Control SYNC/FREEZE."},
        {"version": "DPV1", "summary": "Adds acyclic Read/Write by Slot/Index "
         "(MSAC_C1 / MSAC_C2) and acknowledged alarm handling; extended "
         "diagnostics."},
        {"version": "DPV2", "summary": "Adds isochronous (clock-synchronous, "
         "equidistant) operation, slave-to-slave Data Exchange Broadcast "
         "(DXB), time stamping and redundancy."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "PROFINET (industry successor)", "summary": "Ethernet-"
         "based industrial communication from PI; PROFIBUS-DP devices map "
         "into PROFINET via proxies. PROFINET is a SEPARATE protocol (a "
         "parallel agent owns it) and is NOT this PROFIBUS class."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "DP_service_levels_are_layered",
         "rule": "DPV1/DPV2 are backward-compatible extensions of DPV0; a "
                 "device may support only DPV0.",
         "trap": "Assuming every PROFIBUS-DP slave supports DPV1/DPV2 "
                 "acyclic/isochronous services is wrong."},
        {"trap_name": "FCS_is_an_8bit_checksum_not_CRC",
         "rule": "The PROFIBUS FCS is an 8-bit arithmetic checksum (modulo-256 "
                 "sum), not a polynomial CRC.",
         "trap": "Treating the FCS as a CRC is wrong."},
        {"trap_name": "Hybrid_MAC_not_pure_master_slave",
         "rule": "Multiple masters share the bus by token passing; the token "
                 "holder then polls slaves.",
         "trap": "Modeling PROFIBUS as pure master-slave ignores the "
                 "multi-master token ring."},
        {"trap_name": "Not_Modbus_not_PROFINET_not_EtherCAT",
         "rule": "PROFIBUS-DP has DP/PA profiles, a token+master-slave MAC, "
                 "SD1-SD4 telegrams, DPV0/1/2 service levels, GSD, and "
                 "DSAP/SSAP. Modbus has Function Codes + coils/registers over "
                 "simple master-slave; PROFINET is Ethernet-based "
                 "(IO-Controller/GSDML); EtherCAT uses an Ethernet datagram "
                 "(0x88A4) + Distributed Clocks + FMMU.",
         "trap": "Applying Modbus, PROFINET, or EtherCAT semantics to "
                 "PROFIBUS is wrong."},
    ]
    f["version_naming_history_note"] = (
        "PROFIBUS (Process Field Bus) originated as the German DIN 19245 "
        "standard, became the European EN 50170 standard, and is "
        "internationally standardized as the IEC 61158 Type 3 fieldbus and "
        "IEC 61784-1 Communication Profile Family 3 (CPF 3). It is maintained "
        "by PROFIBUS & PROFINET International (PI). The DP profile is layered "
        "into the backward-compatible service levels DPV0 (cyclic), DPV1 "
        "(acyclic + alarms) and DPV2 (isochronous + slave-to-slave).")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — encoding / parameter tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["start_delimiter_table"] = {
        "header_columns": ["Delimiter", "Value", "Telegram"],
        "rows": [
            ["SD1", "0x10", "fixed length, no data"],
            ["SD2", "0x68", "variable length with data"],
            ["SD3", "0xA2", "fixed length, 8 data octets"],
            ["SD4", "0xDC", "token (master-to-master)"],
            ["SC", "0xE5", "short acknowledgement"],
            ["ED", "0x16", "end delimiter"],
        ],
    }
    f["baud_rate_table"] = {
        "header_columns": ["Baud rate", "Max segment length (type-A cable)"],
        "rows": [
            ["9.6 kbit/s", "1200 m"],
            ["19.2 kbit/s", "1200 m"],
            ["45.45 kbit/s", "1200 m"],
            ["93.75 kbit/s", "1200 m"],
            ["187.5 kbit/s", "1000 m"],
            ["500 kbit/s", "400 m"],
            ["1.5 Mbit/s", "200 m"],
            ["3 Mbit/s", "100 m"],
            ["6 Mbit/s", "100 m"],
            ["12 Mbit/s", "100 m"],
        ],
    }
    f["service_level_table"] = {
        "header_columns": ["Level", "Services"],
        "rows": [
            ["DPV0", "cyclic Data_Exchange, Set_Prm, Chk_Cfg, Slave_Diag, "
             "Global_Control SYNC/FREEZE"],
            ["DPV1", "acyclic Read/Write (Slot/Index), alarms, extended "
             "diagnostics"],
            ["DPV2", "isochronous mode, slave-to-slave DXB, time stamping, "
             "redundancy"],
        ],
    }
    f["sap_table"] = {
        "header_columns": ["SAP", "Service"],
        "rows": [
            ["54", "Master-to-Master (DPM2)"],
            ["55", "Set_Slave_Address"],
            ["56", "Read_Inputs"],
            ["57", "Read_Outputs"],
            ["58", "Global_Control (Sync/Freeze)"],
            ["59", "Get_Configuration"],
            ["60", "Slave_Diagnosis (Get_Diag)"],
            ["61", "Set_Parameters (Set_Prm)"],
            ["62", "Check_Configuration (Chk_Cfg)"],
            ["Default", "Data_Exchange (cyclic)"],
        ],
    }
    f["character_format_table"] = {
        "header_columns": ["Bit", "Meaning"],
        "rows": [
            ["1", "start bit"],
            ["8", "data bits"],
            ["1", "even parity bit"],
            ["1", "stop bit"],
        ],
    }
    f["encoding_note"] = (
        "PROFIBUS-DP uses RS-485 differential NRZ with an 11-bit UART "
        "character (1 start + 8 data + 1 even parity + 1 stop). Telegrams are "
        "selected by a Start Delimiter (SD1=0x10, SD2=0x68, SD3=0xA2, "
        "SD4=0xDC), with SC=0xE5 short ACK and ED=0x16, and protected by an "
        "8-bit arithmetic-checksum FCS. PROFIBUS-PA uses Manchester encoding "
        "at 31.25 kbit/s.")
    f["tables"] = [
        "Start-delimiter table (SD1/SD2/SD3/SD4/SC/ED)",
        "Baud-rate / segment-length table (9.6 kbit/s..12 Mbit/s)",
        "Service-level table (DPV0/DPV1/DPV2)",
        "Service-Access-Point (SAP) table",
        "Character-format table (11-bit, even parity)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — compliance properties.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "RS-485 (DP) differential 2-wire half-duplex PHY at 9.6 kbit/s..12 "
        "Mbit/s with active 220 ohm termination, and/or MBP (PA) Manchester "
        "bus-powered PHY at 31.25 kbit/s.",
        "11-bit UART character (1 start + 8 data + 1 even parity + 1 stop).",
        "Hybrid token-passing (masters) + master-slave (slave polling) MAC; "
        "multi-master.",
        "Telegram family SD1=0x10 / SD2=0x68 / SD3=0xA2 / SD4=0xDC + SC=0xE5 + "
        "ED=0x16; DA/SA/FC/DSAP/SSAP/DU/FCS fields; 8-bit checksum FCS.",
        "DP service level DPV0 (cyclic Set_Prm / Chk_Cfg / Data_Exchange / "
        "Slave_Diag / Global_Control), with DPV1 (acyclic + alarms) and DPV2 "
        "(isochronous + slave-to-slave) where claimed.",
        "GSD device description with a PI-assigned Ident_Number.",
        "Layered diagnostics (station / module / channel / device).",
        "Station addresses 0..126 (127 = broadcast); <=32 per segment.",
    ]
    f["must_not_have_properties"] = [
        "Function-Code + coils/holding-registers framing over simple "
        "master-slave RTU/ASCII/TCP with no token passing (that is Modbus, "
        "not PROFIBUS).",
        "Ethernet-based IO-Controller/IO-Device communication with GSDML and "
        "RT/IRT (that is PROFINET, not PROFIBUS).",
        "An Ethernet datagram with EtherType 0x88A4, Distributed Clocks, "
        "FMMU and SyncManager (that is EtherCAT, not PROFIBUS).",
        "A purely electrical-only RS-485 link with no fieldbus MAC, telegram "
        "framing or service layer (that is plain RS-485, not PROFIBUS).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "FCS mismatch", "trigger": "8-bit checksum fails; the "
         "telegram is rejected and the master retries."},
        {"mode": "Slot-time timeout", "trigger": "No response within TSL; the "
         "master retries / marks the slave absent."},
        {"mode": "Parameterization/configuration mismatch", "trigger": "Set_Prm "
         "or Chk_Cfg rejected; the slave stays in Wait_Prm / Wait_Cfg."},
        {"mode": "Watchdog timeout", "trigger": "Loss of cyclic access; the "
         "slave goes to a safe/cleared output state."},
        {"mode": "Token lost", "trigger": "Ring reform via GAP maintenance."},
    ]
    f["min_link_constraint"] = (
        "A working PROFIBUS-DP link requires a master and at least one slave "
        "on a terminated RS-485 segment at a common baud rate; the master "
        "must parameterize (Set_Prm) and configure (Chk_Cfg) the slave — with "
        "a matching Ident_Number and module configuration — before cyclic "
        "Data_Exchange.")
    f["reset_behavior_compliance"] = (
        "On power-up / reset a slave enters Wait_Prm with outputs in the "
        "safe/cleared state and does not exchange cyclic data until Set_Prm + "
        "Chk_Cfg complete; a watchdog timeout returns it to that safe state.")
    f["profibus_distinguishers"] = (
        "PROFIBUS-DP is identified by ALL of: a fieldbus over RS-485 (DP) or "
        "MBP (PA, intrinsically safe) at 9.6 kbit/s..12 Mbit/s (DP) / 31.25 "
        "kbit/s (PA); a hybrid token-passing + master-slave MAC (multi-"
        "master, Target Rotation Time); the telegram family SD1=0x10 / "
        "SD2=0x68 / SD3=0xA2 / SD4=0xDC + SC=0xE5 + ED=0x16 with DA/SA/FC/"
        "DSAP/SSAP/FCS (8-bit checksum); the DP service levels DPV0/DPV1/"
        "DPV2; the GSD device description with an Ident_Number; and layered "
        "diagnostics. This is distinct from Modbus (Function Codes + coils/"
        "registers over plain master-slave RTU/ASCII/TCP), PROFINET "
        "(Ethernet-based IO-Controller/IO-Device with GSDML and RT/IRT), "
        "EtherCAT (Ethernet datagram 0x88A4 + Distributed Clocks + FMMU + "
        "SyncManager), and plain RS-485 (an electrical-only PHY with no "
        "fieldbus MAC / telegram / service layer).")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — channel / signal catalog.
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "A-line / B-line (RS-485 differential pair)",
         "direction": "bidirectional (half-duplex)",
         "purpose": "PROFIBUS-DP differential NRZ telegram data; shared bus.",
         "active_levels": "differential", "idle_level": "defined by active "
         "termination"},
        {"name": "VP (+5 V) / DGND",
         "direction": "supply / reference",
         "purpose": "Powers the active 220 ohm termination network (390 ohm "
                    "pull-up/pull-down).",
         "active_levels": "DC", "idle_level": "DC"},
        {"name": "MBP bus (PROFIBUS-PA)",
         "direction": "bidirectional (half-duplex)",
         "purpose": "Bus-powered Manchester signal (data + DC supply) at "
                    "31.25 kbit/s; intrinsically safe.",
         "active_levels": "current modulation +-9 mA", "idle_level": "DC base "
         "current"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Bus idle", "meaning": "No telegram; termination holds the "
         "defined idle level between transmissions."},
        {"name": "Telegram active", "meaning": "A station transmits a telegram "
         "(token holder or polled slave)."},
    ]
    f["packet_types_summary"] = [
        {"class": "Fixed telegram", "members": ["SD1 (0x10)", "SD3 (0xA2)"],
         "count": 2},
        {"class": "Variable telegram", "members": ["SD2 (0x68)"], "count": 1},
        {"class": "Token", "members": ["SD4 (0xDC)"], "count": 1},
        {"class": "Short ACK", "members": ["SC (0xE5)"], "count": 1},
    ]
    cc = _ensure_dict(f, "channel_counts")
    cc.update({
        "rs485_differential_pairs": 1,
        "start_delimiter_count": len(_START_DELIMITERS),
        "service_level_count": len(_SERVICE_LEVELS),
        "telegram_field_count": len(_TELEGRAM_FIELDS),
        "fcs_bits": _FCS_BITS,
        "max_baud_Mbps": _MAX_BAUD_MBPS,
        "max_station_address": _MAX_STATION_ADDR,
        "max_stations_per_segment": _MAX_STATIONS_PER_SEGMENT,
    })
    f["global_signals"] = [
        {"name": "Token", "purpose": "Right to transmit; passed (SD4) among "
         "masters in a logical ring."},
        {"name": "Station address (0..126)", "purpose": "Identifies each "
         "station in DA/SA; 127 = broadcast."},
        {"name": "Service Access Point (DSAP/SSAP)", "purpose": "Selects the "
         "DP service at sender/receiver."},
    ]
    f["dependency_graph"] = {
        "common_rule": "Only the token holder transmits; a master must hold "
        "the token before polling slaves, and a slave must be parameterized "
        "(Set_Prm) and configured (Chk_Cfg) before it joins cyclic "
        "Data_Exchange.",
        "data_dependency": "A cyclic Data_Exchange telegram requires: (1) the "
        "master holding the token, (2) the slave in the Data_Exchange state, "
        "(3) a response within the slot time (TSL). Each telegram is "
        "FCS-checked.",
    }
    f["handshake_pairs"] = [
        {"name": "Token pass", "from": "master", "to": "successor master",
         "rule": "SD4 passes the token in ascending station-address order."},
        {"name": "Poll / response", "from": "master", "to": "slave",
         "rule": "Request telegram -> slave responds within TSL (or SC short "
                 "ACK)."},
        {"name": "Set_Prm / Chk_Cfg", "from": "master", "to": "slave",
         "rule": "Parameterize then configure before Data_Exchange."},
        {"name": "Global_Control", "from": "master", "to": "slave group",
         "rule": "Broadcast SYNC/FREEZE to synchronize outputs/inputs."},
    ]
    f["ordering_rules"] = {
        "bit_order_on_wire": "RS-485 differential NRZ, 11-bit UART characters "
        "(LSB first), even parity per character.",
        "telegram_order": "Telegrams are framed SD..FCS..ED; SD2 repeats the "
        "length (LE/LEr) and the SD2 byte for robustness.",
        "token_order": "Token passes in ascending station-address order; the "
        "highest master wraps to the lowest.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — interconnect topology.
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Multi-drop linear bus (daisy-chain) over a shared RS-485 differential "
        "pair with active termination at both segment ends; repeaters extend "
        "reach and station count. PROFIBUS-PA adds a trunk-and-spur / tree MBP "
        "topology bridged to the DP backbone. There is no point-to-point "
        "serial fabric — all stations share one bus.")
    f["supported_topologies"] = [
        {"name": "Linear bus segment", "description": "Up to 32 stations on a "
         "terminated RS-485 segment."},
        {"name": "Repeated network", "description": "Repeaters join segments "
         "to reach up to 126 addressable stations."},
        {"name": "Single-master", "description": "One DPM1 polling its "
         "slaves."},
        {"name": "Multi-master", "description": "Several masters share the bus "
         "via token passing."},
        {"name": "DP backbone + PA segments", "description": "DP/PA couplers "
         "or links bridge 31.25 kbit/s PA (MBP) segments onto the DP "
         "backbone."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "DP Class-1 master (DPM1)", "description": "Runs the cyclic "
         "I/O data exchange with its assigned slaves (e.g. a PLC)."},
        {"role": "DP Class-2 master (DPM2)", "description": "Engineering / "
         "diagnostic / configuration device; master-to-master services."},
        {"role": "DP slave", "description": "Passive station; responds only "
         "when polled (remote I/O, drive, sensor)."},
        {"role": "Repeater", "description": "Regenerates the RS-485 signal "
         "and counts as a station load."},
        {"role": "DP/PA coupler / link", "description": "Bridges a PA (MBP) "
         "segment to the DP backbone."},
    ]
    f["interconnect_role"] = (
        "PROFIBUS is a shared-medium fieldbus. Active masters arbitrate the "
        "bus by passing a token in a logical ring; the token holder polls its "
        "passive slaves in a master-slave manner. Stations are addressed 0..126 "
        "and selected by Destination Address + Service Access Point. PA "
        "segments are bridged to the DP backbone.")
    f["routing_methods"] = ["shared bus (no routing)",
                            "repeater segment extension",
                            "DP/PA coupler bridging"]
    f["ordering_guarantees"] = {
        "token": "Exactly one master holds the token and transmits at a time "
        "(deterministic, bounded by TTR).",
        "poll": "A master polls its slaves in a defined cyclic order each bus "
        "cycle.",
        "broadcast": "Global_Control SYNC/FREEZE reaches a slave group "
        "simultaneously.",
    }
    f["memory_vs_peripheral_regions"] = (
        "PROFIBUS is not memory-mapped; stations and services are addressed by "
        "station address (DA/SA) and Service Access Point (DSAP/SSAP), and "
        "DPV1 data records by Slot and Index — not by a memory or peripheral "
        "address.")
    dc = _ensure_dict(f, "device_classification")
    dc["dpm1"] = "DP Class-1 master: cyclic I/O data exchange."
    dc["dpm2"] = "DP Class-2 master: engineering / diagnostics."
    dc["dp_slave"] = "Passive station; responds when polled."
    dc["repeater"] = "Signal regenerator / segment extender."
    dc["dp_pa_coupler"] = "Bridges a PA (MBP) segment to the DP backbone."
    f["default_signal_values_evidence_tables"] = [
        "PROFIBUS reduced OSI layering (PHY / FDL / Application)",
        "Linear-bus topology with active termination figure",
        "Token-ring + master-slave MAC figure",
        "Telegram-format figure (SD1/SD2/SD3/SD4)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — constraints / PDK.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["electrical_channel_constraints"] = {
        "dp_phy": "RS-485 differential 2-wire (A-line/B-line), half-duplex NRZ",
        "dp_baud_rates_kbps": list(_BAUD_RATES_KBPS),
        "dp_max_baud_Mbps": _MAX_BAUD_MBPS,
        "termination": "220 ohm active termination (390 ohm pull-up to +5 V / "
                      "390 ohm pull-down to DGND) at both segment ends",
        "character_format": "1 start + 8 data + 1 even parity + 1 stop "
                            "(11 bits)",
        "pa_phy": "MBP / IEC 61158-2, Manchester, bus-powered, intrinsically "
                  "safe, 31.25 kbit/s",
        "cable": "shielded twisted pair (type A)",
        "max_stations_per_segment": _MAX_STATIONS_PER_SEGMENT,
        "max_station_address": _MAX_STATION_ADDR,
        "fcs_bits": _FCS_BITS,
        "service_levels": list(_SERVICE_LEVELS),
    }
    f["notes"] = (
        "PROFIBUS is a fieldbus communication standard (IEC 61158 Type 3 / IEC "
        "61784-1 CPF 3): it fixes the RS-485 (DP) / MBP (PA) physical layer, "
        "the active bus termination, the 11-bit character with even parity, "
        "the baud-rate-dependent segment length and timing, the hybrid "
        "token+master-slave MAC, the telegram family, the DP service levels, "
        "the GSD device description, and the 8-bit FCS. It does NOT impose "
        "PDK-specific SDC / floorplan constraints; the RS-485 transceiver, "
        "connector, termination and (for PA) intrinsic-safety design are "
        "board / physical-layer concerns.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — DFT / scan topology.
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "Slave_Diag (Get_Diag)", "purpose": "Layered station / "
         "module / channel / device diagnostics."},
        {"name": "FDL status request (SD1)", "purpose": "Station FDL-state "
         "observability."},
        {"name": "Live List / GAP maintenance", "purpose": "Present-station "
         "enumeration."},
        {"name": "Get_Configuration", "purpose": "Read back the slave's "
         "module configuration."},
        {"name": "FCS / parity / response status", "purpose": "Telegram-level "
         "error observability."},
    ]
    f["internal_diagnostics_observability"] = [
        "Slave startup state (POWER_ON / Wait_Prm / Wait_Cfg / "
        "Data_Exchange).",
        "Station status 1/2/3 and master address.",
        "Module and channel diagnostics.",
        "MAC timers and token-ring membership.",
        "FCS / parity / slot-time / watchdog status.",
    ]
    f["out_of_band_test_facilities"] = [
        "PI (PROFIBUS & PROFINET International) certification / "
        "interoperability testing.",
        "Bus monitors / protocol analyzers (implementation tooling).",
    ]
    f["notes"] = (
        "PROFIBUS's protocol-level DFT surface is Slave_Diag (layered "
        "diagnostics), the FDL status request, the Live List, "
        "Get_Configuration, and per-telegram FCS/parity/timeout status. "
        "Chip-level JTAG / scan / BIST remain controller-vendor / SoC "
        "concerns; conformance is established by PI certification testing.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — power intent.
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["power_management_states"] = [
        {"state": "Active", "name": "Active", "description": "Station "
         "transmitting/receiving telegrams on the bus."},
        {"state": "Idle", "name": "Idle", "description": "Station present but "
         "not currently transmitting (waiting for token / poll)."},
    ]
    f["wakeup_mechanism"] = (
        "PROFIBUS does not define a protocol low-power sleep/wake handshake; a "
        "station is either in the ring / being polled or absent. For "
        "PROFIBUS-PA the MBP line is bus-powered, so the field device draws "
        "its operating power from the bus.")
    f["power_rails"] = [
        {"rail": "VDD (controller / RS-485 transceiver)",
         "purpose": "Logic and line-driver supply for a DP station."},
        {"rail": "VP (+5 V) / DGND",
         "purpose": "Active bus-termination supply / reference (DP)."},
        {"rail": "MBP bus power (PA)",
         "purpose": "PROFIBUS-PA field devices are powered from the "
                    "intrinsically-safe MBP bus (FISCO power budget)."},
    ]
    f["profibus_power_considerations"] = (
        "PROFIBUS-DP power is a board-level concern (controller + RS-485 "
        "transceiver + termination). PROFIBUS-PA is bus-powered: the same MBP "
        "pair carries data and the DC supply, within an intrinsic-safety "
        "(FISCO) power limit so the bus cannot ignite an explosive "
        "atmosphere.")
    f["notes"] = (
        "The protocol-level power intent is mainly the PROFIBUS-PA bus-powered "
        "/ intrinsically-safe MBP model; PROFIBUS-DP has no protocol sleep "
        "state and its supply is an implementation/board concern.")
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — verification plan.
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "PHY (DP) — RS-485 differential signaling and termination at each baud "
        "rate (9.6 kbit/s..12 Mbit/s); 11-bit character, even parity.",
        "PHY (PA) — MBP Manchester, bus-powered, intrinsically safe, 31.25 "
        "kbit/s.",
        "MAC token passing — ring formation, GAP/Live-List, TTR, token loss / "
        "reform.",
        "MAC master-slave — poll/response, slot time TSL, TSDR.",
        "Telegram framing — SD1/SD2/SD3/SD4/SC/ED; LE/LEr consistency; "
        "DA/SA/FC/DSAP/SSAP/FCS fields.",
        "FCS — 8-bit checksum error injection and detection.",
        "DPV0 — Set_Prm, Chk_Cfg, Data_Exchange, Slave_Diag, Global_Control "
        "SYNC/FREEZE.",
        "DPV1 — acyclic Read/Write (Slot/Index); alarm handling.",
        "DPV2 — isochronous cycle; slave-to-slave DXB.",
        "Slave startup FSM — POWER_ON -> Wait_Prm -> Wait_Cfg -> "
        "Data_Exchange.",
        "Diagnostics — station/module/channel/device; new-diagnostics flag.",
        "Addressing — 0..126; Set_Slave_Address; broadcast 127.",
        "GSD — Ident_Number match and module/Cfg consistency.",
        "Watchdog — timeout -> safe/cleared output state.",
    ]
    f["notes"] = (
        "PROFIBUS does not ship an embedded testbench, but the standard "
        "implies a verification plan spanning the physical layer (RS-485 / "
        "MBP signaling, termination, character/parity), the hybrid MAC "
        "(token + master-slave timers), the telegram family and 8-bit FCS, "
        "the DP service levels (DPV0/1/2), diagnostics, addressing, and GSD "
        "consistency. PI certification testing supplies the formal suite.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — security requirements.
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "8-bit FCS (arithmetic checksum) per data/fixed telegram detects "
        "corruption.",
        "Per-character even parity (11-bit UART character).",
        "Frame Count Bit (FCB/FCV) detects duplicate or lost telegrams.",
        "Slot-time (TSL) timeout and watchdog detect missing responses / lost "
        "master access.",
        "LE/LEr length redundancy and the repeated SD2 byte harden the SD2 "
        "telegram start.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "PROFIBUS's base protocol provides no cryptographic confidentiality "
        "or authentication on the bus; the FCS and parity are anti-corruption "
        "only.",
        "Industrial-network security (segmentation, firewalls/DMZ, IEC 62443) "
        "is layered around the fieldbus rather than inside the PROFIBUS "
        "telegram.",
    ]
    f["notes"] = (
        "PROFIBUS is an industrial fieldbus: its built-in protections are "
        "anti-corruption (8-bit FCS, even parity, FCB/FCV, slot-time/watchdog "
        "timeouts) only. The bus carries plaintext telegrams. Cryptographic "
        "confidentiality / authentication are NOT part of the protocol; "
        "security is provided by network segmentation and IEC-62443-style "
        "controls around the fieldbus.")
    _write(p, d)
