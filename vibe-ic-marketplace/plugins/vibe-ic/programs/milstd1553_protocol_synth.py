"""MIL-STD-1553B protocol synth helper.

v0.1.83 — ic_class-gated overlay for `serial_peripheral_protocol` specs
that exhibit the MIL-STD-1553B structural signature (Bus Controller +
Remote Terminal + Command/Status/Data words + Manchester II + dual
redundant bus). Applies MIL-STD-1553B-canonical content to L1-L18 + L21
+ L22 + L23.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S synth approach).
Any 1553-family variant (1553A / 1553B / 1553C / MIL-STD-1773 / STANAG
3838 / STANAG 3910 EFABus / Def-Stan 00-18 Part 2) exhibits the same
signature (BC + RT + Manchester II + Command/Status/Data + dual-redundant
twinax).

Public entry: `apply_milstd1553_synth(generated_docs_dir, is_milstd1553,
milstd1553_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def apply_milstd1553_synth(generated_docs_dir: Path, is_milstd1553: bool,
                           milstd1553_ic_name: Optional[str]) -> None:
    """Apply MIL-STD-1553B-specific synth when the structural signature
    matched."""
    if not is_milstd1553:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs.
    if milstd1553_ic_name is not None:
        for n in [
            "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
            "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
            "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
            "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
            "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
            "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
        ]:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = milstd1553_ic_name
                _write(q, d)

    # L1 DATASHEET
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title",
                     "MIL-STD-1553 — Aircraft Internal Time Division Command/Response Multiplex Data Bus")
        d.setdefault("version",
                     "MIL-STD-1553B (1978); Notice 2 (1986) renamed it 'Digital time division command/response multiplex data bus'; MIL-STD-1553C (Feb 2018) graphics-and-tables refresh, functionally equivalent to B.")
        d.setdefault("manufacturer",
                     "United States Department of Defense (USAF originator) / SAE Aerospace AS-1A Avionic Networks Subcommittee (current co-maintainer)")
        d.setdefault("revised_date",
                     "1978-09-21 (original 1553B); 1986 (Notice 2 retitled); February 2018 (Revision C)")
        d.setdefault("copyright",
                     "U.S. Department of Defense military standard; STANAG 3838 AVS in NATO use; Def-Stan 00-18 Part 2 (UK MoD).")
        d.setdefault("document_layout", [
            "Conceptual description — Bus Controller (BC), Remote Terminal (RT), Bus Monitor (BM), dual-redundant bus pair.",
            "Bus protocol — Manchester-coded 16-bit words; 3 word types (Command / Status / Data); transfer formats and broadcasts.",
            "Bus hardware characteristics — twinax cable, isolation transformers, terminators, bus couplers, stubs.",
            "Word formats — Command Word, Status Word, Data Word, sync patterns, odd parity.",
            "Transactions — 6 BC↔RT message formats + 4 broadcast formats.",
            "Mode commands — 10 named codes for bus control.",
            "Timing — 4 µs inter-message gap, 4-12 µs RT response, 14 µs RT no-response timeout.",
            "Notice 2 (1986) — extended retitle and clarifications; aligned 1553B with digital-bus terminology.",
        ])
        d.setdefault("key_features", [
            "Differential serial data bus over 70-85 Ω twinax (78 Ω nominal characteristic impedance).",
            "1.0 Mbit/s bit rate (1 µs / bit), Manchester II bi-phase encoding (logical 1 = high-then-low; logical 0 = low-then-high).",
            "Half-duplex command/response on a single shared bus (multiplex).",
            "Time-division multiplex — Bus Controller (BC) initiates every transfer.",
            "Dual-redundant bus (Bus A + Bus B); messages on only one bus at a time; failover under BC control.",
            "Up to 31 Remote Terminals (RTs) per bus; address 31 is reserved for broadcast.",
            "20-bit word framing: 3 µs sync (3-bit equivalent) + 16 data bits + 1 odd-parity bit.",
            "3 word types: Command Word (BC→RT), Status Word (RT→BC), Data Word (BC↔RT payload).",
            "Distinct sync patterns: Command/Status sync = high 1.5 µs then low 1.5 µs; Data sync = low 1.5 µs then high 1.5 µs (cannot occur in Manchester payload).",
            "Odd parity computed over 16 data bits per word.",
            "Inter-message gap ≥ 4 µs; RT must start its status response within 4-12 µs of the last command word; receiver considers a command lost after 14 µs of no response.",
            "Bus Controller hand-off via Backup Bus Controller (BBC) using Status-Word flags and Dynamic Bus Control Mode Code.",
            "Bus Monitor (BM) — passive listener for telemetry; cannot transmit.",
            "Transformer-coupled or direct-coupled stubs (transformer preferred; 20 ft / 6.1 m max for transformer coupling; 1 ft max for direct).",
            "Peak-to-peak transmitter output voltage 18-27 V on a twinax bus.",
            "Bit-rate long-term stability ±0.1 %; short-term clock stability ±0.01 %.",
            "Optical-fibre variant = MIL-STD-1773; high-rate dual variant = STANAG 3910 / EFABus.",
        ])
        d.setdefault("modes_of_operation", [
            {"name": "Bus Controller (BC)",
             "description": "Single master of the bus at a time; sources every Command Word; one BC per bus per cycle."},
            {"name": "Backup Bus Controller (BBC / BUBC)",
             "description": "Standby BC capable of assuming bus control via Dynamic Bus Control mode code or discrete failover."},
            {"name": "Remote Terminal (RT)",
             "description": "Responds to BC commands within 4-12 µs; up to 31 RTs per bus (addresses 0-30); address 31 = broadcast."},
            {"name": "Bus Monitor (BM)",
             "description": "Passive listener; records every transaction for telemetry / off-line analysis; cannot initiate transfers."},
            {"name": "Bus A / Bus B (dual redundant)",
             "description": "Two independent physical buses; the BC selects which bus carries the next message; provides alternate data path against damage / failure."},
        ])
        d.setdefault("domain_of_application", [
            "Military avionics data bus on F-16 Falcon (first deployment, 1973), F-15 Eagle, F-18 Hornet, AH-64 Apache, P-3C Orion, F-20 Tigershark.",
            "Spacecraft on-board data handling (OBDH) — civil and military, including the James Webb Space Telescope.",
            "NATO standard STANAG 3838 AVS (UK MoD Def-Stan 00-18 Part 2) — Panavia Tornado, BAE Systems Hawk (Mk 100 and later), Eurofighter Typhoon, Saab JAS 39 Gripen, MiG-35 (Russian implementation).",
            "Co-deployed with STANAG 3910 'EFABus' for high-rate avionics traffic that piggybacks on the same physical layer.",
            "Optical-fibre derivative MIL-STD-1773 used where EMI / EMP robustness or weight savings matter.",
        ])
        d.setdefault("layered_structure", [
            {"layer": "Application Layer",
             "scope": "Schedule-of-transfers and subsystem semantics; cyclic-executive frames + acyclic Vector-Word polling. Defined by the system integrator, not by 1553B."},
            {"layer": "Message Layer",
             "scope": "10 mode codes + 6 BC↔RT transfer formats + 4 broadcast formats; Service-Request and Status-bit semantics."},
            {"layer": "Word Layer",
             "scope": "3 word types (Command / Status / Data); 20-bit framing (3-bit sync + 16 data + 1 odd parity)."},
            {"layer": "Encoding Layer",
             "scope": "Manchester II bi-phase encoding at 1.0 Mbit/s; distinct sync patterns for Command/Status vs Data."},
            {"layer": "Physical Layer",
             "scope": "78 Ω twinax (70-85 Ω range), isolation transformers, terminators (≥ 75 % shield), transformer-coupled or direct-coupled stubs, 18-27 Vp-p transmitter, dual-redundant bus pair."},
        ])
        d.setdefault("overview",
            "MIL-STD-1553 is the U.S. Department of Defense standard that defines the mechanical, electrical, and functional characteristics of a serial multiplex data bus for military avionics and spacecraft. A 1553 system consists of one active Bus Controller (BC), an optional Backup Bus Controller, an optional Bus Monitor (BM), and up to 31 Remote Terminals (RTs) per bus, all sharing a dual-redundant differential twinax bus operating at 1.0 Mbit/s with Manchester II encoding. All communication is half-duplex command/response: the BC issues a 16-bit Command Word and the addressed RT must respond with a Status Word (and optionally Data Words) within 4-12 µs. The standard is intentionally tight on electrical compatibility so that hardware from any conformant vendor can interoperate on the same bus.")
        d.setdefault("compatibility_note",
            "1553A was the 1975 predecessor that left many options to the user, causing incompatibility; 1553B (1978) defines the options explicitly to ensure electrical/functional compatibility across vendors. 1553B + Notice 2 (1986) retitled to 'Digital time division command/response multiplex data bus' and tightened terminology. 1553C (2018) is functionally equivalent to 1553B; it refreshes graphics and tables for readability. STANAG 3838 (NATO) and Def-Stan 00-18 Part 2 (UK) closely mirror 1553B. The optical variant MIL-STD-1773 is wire-compatible at the protocol layer.")
        _write(p, d)

    # L2 FRS
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        po = d.setdefault("protocol_overview", {})
        if isinstance(po, dict):
            po.setdefault("type",
                "Command/response time-division multiplex serial bus; single Bus Controller (BC) drives every transfer; up to 31 Remote Terminals (RTs) respond; Bus Monitors (BMs) passively log.")
            po.setdefault("duplex",
                "half-duplex on a single shared differential twinax bus (dual-redundant pair: Bus A + Bus B)")
            po.setdefault("synchronous", False)
            po.setdefault("bus_arbitration",
                "No arbitration — single master (BC) per cycle; BC initiates every transfer and selects which RT(s) respond by addressing.")
            po.setdefault("physical_layer",
                "78 Ω characteristic impedance twinax (70-85 Ω range); 18-27 Vp-p transmitter; transformer-coupled stubs preferred (20 ft / 6.1 m max), direct-coupled stubs allowed (1 ft / 0.3 m max); ≥ 75 % shielded couplers; bus terminated at both ends.")
            po.setdefault("bit_coding",
                "Manchester II bi-phase: logical 1 = high-half then low-half within bit time; logical 0 = low-half then high-half. Auto-clocked, no DC component (transformer-friendly).")
            po.setdefault("bus_values",
                "Differential signalling on twinax; transmitter voltage 18-27 Vp-p; ≥ 4 µs minimum inter-message gap; ≥ 14 µs absent-response timeout.")
            po.setdefault("multimaster", False)
            po.setdefault("multicast", True)
            po.setdefault("addressing",
                "5-bit Remote Terminal address (0-30 valid; 31 = broadcast); plus 5-bit Subaddress / Mode field that selects the data buffer inside the RT or selects Mode Code (subaddress 0 and 31 are reserved for Mode Codes).")
        fr = [
            {"id": "FR-WORD-01",
             "text": "All bus transactions exchange 20-bit words composed of: 3 µs sync field (3-bit equivalent) + 16 data bits + 1 odd-parity bit."},
            {"id": "FR-TYPE-02",
             "text": "There are exactly 3 word types: Command Word (BC → RT), Status Word (RT → BC), Data Word (BC ↔ RT payload). Each is 16 bits plus framing."},
            {"id": "FR-SYNC-03",
             "text": "Command/Status sync = high for 1.5 µs then low for 1.5 µs (3 µs total). Data sync = low for 1.5 µs then high for 1.5 µs (inverted polarity). The sync field is non-Manchester and cannot be confused with any payload."},
            {"id": "FR-CMD-04",
             "text": "Command Word layout (16 data bits): RT address [5b, MSB-first, bits 1-5] + T/R [1b, bit 6: 1=transmit-from-RT, 0=receive-to-RT] + Subaddress / Mode [5b, bits 7-11] + Data Word Count / Mode Code [5b, bits 12-16]. Subaddress 00000 and 11111 (0 and 31) select a Mode Code in the bottom 5 bits."},
            {"id": "FR-STATUS-05",
             "text": "Status Word layout (16 data bits): RT address [5b, bits 1-5] + Message Error [1b, bit 6] + Instrumentation [1b, bit 7] + Service Request [1b, bit 8] + 3 reserved bits [bits 9-11] + Broadcast Command Received [1b, bit 12] + Busy [1b, bit 13] + Subsystem Flag [1b, bit 14] + Dynamic Bus Acceptance [1b, bit 15] + Terminal Flag [1b, bit 16]. A '1' means the condition is true; more than one bit may be true simultaneously."},
            {"id": "FR-DATA-06",
             "text": "Data Word carries 16 bits of subsystem payload. Up to 32 data words per message (word count field of 1-32; all-zero word count = 32 words; 0 valid only for mode commands)."},
            {"id": "FR-PARITY-07",
             "text": "Each word terminates in 1 odd-parity bit computed over the 16 data bits. Parity = 1 if there is an even number of '1' data bits, ensuring the total number of '1' bits (data + parity) is odd."},
            {"id": "FR-BITRATE-08",
             "text": "Bit rate is 1.0 Mbit/s (1 µs per bit). Bit-rate long-term accuracy / stability ±0.1 %; short-term clock stability within ±0.01 %."},
            {"id": "FR-FMT-09",
             "text": "Six BC↔RT transfer formats are defined: (1) Controller-to-RT (BC sends Cmd + N×Data; RT responds Status); (2) RT-to-Controller (BC sends Cmd; RT responds Status + N×Data); (3) RT-to-RT (BC sends Receive-Cmd + Transmit-Cmd; transmitting RT responds Status + Data; receiving RT responds Status); (4) Mode Command Without Data Word; (5) Mode Command With Data Word (Transmit); (6) Mode Command With Data Word (Receive)."},
            {"id": "FR-BCAST-10",
             "text": "Four broadcast formats are defined for RT-address 31 (broadcast): Controller-to-RT(s) Transfer; RT-to-RT(s) Transfer; Mode Command Without Data Word (Broadcast); Mode Command With Data Word (Broadcast). Receiving RTs accept the data but DO NOT transmit a Status Word in response (to prevent bus contention)."},
            {"id": "FR-GAP-11",
             "text": "Inter-message gap is ≥ 4 µs minimum, but may legally be much longer (up to 1 ms in some legacy BCs)."},
            {"id": "FR-RESP-12",
             "text": "Response Time: an addressed RT must begin transmitting its Status Word within 4 µs to 12 µs after the last bit of the BC's command word. After 14 µs of bus quiet, the BC considers the command 'no-response' (timeout)."},
            {"id": "FR-MODE-13",
             "text": "10 Mode Codes are defined: Dynamic Bus Control (00000), Synchronize without data word (00001), Transmit Status Word (00010), Initiate Self Test (00011), Transmitter Shutdown (00100), Override Transmitter Shutdown (00101), Inhibit Terminal Flag Bit (00110), Override Inhibit Terminal Flag Bit (00111), Reset Remote Terminal (01000), Transmit Vector Word (10000, with data), Synchronize with data word (10001), Transmit Last Command (10010), Transmit BIT Word (10011), Selected Transmitter Shutdown (10100), Override Selected Transmitter Shutdown (10101)."},
            {"id": "FR-DUALBUS-14",
             "text": "Dual-redundant bus (Bus A + Bus B): a 1553 message travels on only one bus at a time, as selected by the BC; the standby bus is available for immediate retry under retry policy."},
            {"id": "FR-RETRY-15",
             "text": "If an RT fails to respond, or responds with Message Error / Subsystem Flag / etc., the BC may retry on the same bus or immediately on the redundant bus."},
            {"id": "FR-BCHANDOFF-16",
             "text": "Bus Controller handoff to Backup BC may be requested via the Dynamic Bus Control mode code; the targeted backup acknowledges by setting Dynamic Bus Acceptance in its Status Word."},
            {"id": "FR-MAXRT-17",
             "text": "Up to 31 distinct RT addresses (0-30) per bus; address 31 = broadcast. Practically each bus carries 31 RTs + 1 BC + possibly BBC + BMs."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("error_response_conditions", [
            "PARITY ERROR — received word has even parity over (16 data bits + parity bit); receiver discards word.",
            "MANCHESTER ENCODING ERROR — bi-phase mid-bit transition missing or wrong polarity; receiver discards word.",
            "SYNC PATTERN ERROR — sync field does not match the Command/Status (HL) or Data (LH) sync pattern.",
            "MESSAGE ERROR — RT detects any error in the BC's command sequence (word count mismatch, illegal command, parity, encoding); RT sets MESSAGE ERROR bit in its Status Word and SHALL NOT transmit data.",
            "NO-RESPONSE TIMEOUT — BC observes no RT Status Word within 14 µs of the last command word; BC may retry on same or redundant bus.",
            "WORD-COUNT MISMATCH — number of Data Words received ≠ word count in Command Word; receiver flags MESSAGE ERROR.",
            "ILLEGAL COMMAND — RT receives a command for a subaddress / mode it does not implement; RT sets MESSAGE ERROR + does not transmit data.",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "Conform to MIL-STD-1553B (1978) or 1553C (2018, functionally equivalent).",
                "Notice 2 (1986) compliant terminology when relevant (digital time-division multiplex bus).",
                "Twinax characteristic impedance 70-85 Ω; transmitter peak-to-peak output 18-27 V.",
                "Manchester II bi-phase encoding at 1.0 Mbit/s ± 0.1 % long-term stability / ± 0.01 % short-term clock stability.",
                "Inter-message gap ≥ 4 µs; RT response 4-12 µs; BC timeout 14 µs.",
                "Word count of 0 in a non-mode command interpreted as 32 data words.",
                "RT address 31 reserved for broadcast; broadcasting RTs SHALL NOT respond with a Status Word.",
                "Bus Monitor (BM) SHALL NOT transmit on the bus.",
                "Implement at least the mandatory Mode Codes: Transmit Status Word (00010), Transmit Last Command (10010), Transmit BIT Word (10011) — per AS-15531 / 1553B Notice 2.",
                "Transformer-coupled stubs preferred; if direct-coupled, stub length ≤ 1 ft (0.3 m).",
            ]
        d.setdefault("performance_of_error_detection", [
            "Per-word odd-parity catches all single-bit data errors within a word.",
            "Manchester encoding catches all bit-cell encoding violations (missing mid-bit transition or wrong polarity).",
            "Sync-pattern check rejects any out-of-band noise that doesn't match the 3 µs HL or LH sync.",
            "Word-count + message-error framing catches truncated or extended messages.",
            "Response-time window (4-12 µs) catches RT timing faults.",
            "Dual-redundant bus provides immediate retry path against media damage / single-bus failure.",
            "Differential twinax with isolation transformers gives strong common-mode and lightning-strike tolerance.",
        ])
        _write(p, d)

    # L3 CMD_PROTOCOL
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type",
            "Command/response time-division multiplex serial bus. The Bus Controller (BC) issues a Command Word (BC → RT); the addressed Remote Terminal (RT) responds with a Status Word (RT → BC) and optionally Data Words.")
        # Force overwrite when opcodes is missing/None/[] — the L3 base
        # extractor (gen_l3_cmd_protocol) pre-fills opcodes=[] when its
        # parser finds no opcode evidence in the raw spec; setdefault would
        # be a no-op against an existing empty list.
        if _empty(d.get("opcodes")):
            d["opcodes"] = [
            {"code": "00000", "mnemonic": "DYNAMIC_BUS_CONTROL",          "description": "Mode Code: requests handoff of bus control to the addressed RT (target acknowledges by setting Dynamic Bus Acceptance bit).", "has_data_word": False},
            {"code": "00001", "mnemonic": "SYNCHRONIZE_NO_DATA",          "description": "Mode Code: forces the addressed RT to synchronize to the BC (no data word).", "has_data_word": False},
            {"code": "00010", "mnemonic": "TRANSMIT_STATUS_WORD",         "description": "Mode Code: re-issue last Status Word (Mode Code 00010, mandatory).", "has_data_word": False},
            {"code": "00011", "mnemonic": "INITIATE_SELF_TEST",           "description": "Mode Code: command the RT to initiate its built-in self test (BIT).", "has_data_word": False},
            {"code": "00100", "mnemonic": "TRANSMITTER_SHUTDOWN",         "description": "Mode Code: shut down the redundant bus transmitter on the addressed RT (used for fault containment).", "has_data_word": False},
            {"code": "00101", "mnemonic": "OVERRIDE_TRANSMITTER_SHUTDOWN","description": "Mode Code: re-enable the previously-shut-down transmitter.", "has_data_word": False},
            {"code": "00110", "mnemonic": "INHIBIT_TERMINAL_FLAG_BIT",    "description": "Mode Code: mask the Terminal Flag bit in the Status Word.", "has_data_word": False},
            {"code": "00111", "mnemonic": "OVERRIDE_INHIBIT_TERMINAL_FLAG","description": "Mode Code: un-mask the Terminal Flag bit in the Status Word.", "has_data_word": False},
            {"code": "01000", "mnemonic": "RESET_REMOTE_TERMINAL",        "description": "Mode Code: force the addressed RT to reset its state.", "has_data_word": False},
            {"code": "10000", "mnemonic": "TRANSMIT_VECTOR_WORD",         "description": "Mode Code with Data: RT sends a 16-bit Vector Word (acyclic service-request data).", "has_data_word": True},
            {"code": "10001", "mnemonic": "SYNCHRONIZE_WITH_DATA_WORD",   "description": "Mode Code with Data: BC sends a data word for synchronization use.", "has_data_word": True},
            {"code": "10010", "mnemonic": "TRANSMIT_LAST_COMMAND",        "description": "Mode Code with Data: RT echoes the last Command Word it received (mandatory).", "has_data_word": True},
            {"code": "10011", "mnemonic": "TRANSMIT_BIT_WORD",            "description": "Mode Code with Data: RT sends its Built-In-Test (BIT) word (mandatory).", "has_data_word": True},
            {"code": "10100", "mnemonic": "SELECTED_TRANSMITTER_SHUTDOWN","description": "Mode Code with Data: shut down a specifically-selected transmitter (data word identifies which).", "has_data_word": True},
            {"code": "10101", "mnemonic": "OVERRIDE_SELECTED_TRANSMITTER_SHUTDOWN","description": "Mode Code with Data: re-enable specifically-selected transmitter.", "has_data_word": True},
            ]
        d.setdefault("channels", [
            {"name": "Bus A (primary)",     "direction": "BC↔RT differential twinax (half-duplex)",
             "description": "Primary 78 Ω twinax bus carrying Manchester II 1 Mbit/s; selected by BC for each message; transformer-coupled stubs."},
            {"name": "Bus B (redundant)",   "direction": "BC↔RT differential twinax (half-duplex)",
             "description": "Standby 78 Ω twinax bus identical to Bus A; selected by BC for retry or failover; messages travel on only one of A/B at a time."},
        ])
        d.setdefault("frame_types", [
            {"name": "Command Word",   "purpose": "BC → RT control word: addresses an RT, selects T/R, names a Subaddress / Mode Code, and gives Word Count or Mode Code value."},
            {"name": "Status Word",    "purpose": "RT → BC response word: echoes RT address and reports up to 9 status bits (Message Error, Service Request, Busy, Terminal Flag, etc.)."},
            {"name": "Data Word",      "purpose": "16-bit payload word; 0..32 per message; carries subsystem application data or mode-command data."},
        ])
        d.setdefault("data_frame_fields", [
            {"field": "SYNC",          "size": "3 µs (3-bit equivalent)",  "value": "Command/Status: HIGH 1.5µs → LOW 1.5µs ; Data: LOW 1.5µs → HIGH 1.5µs"},
            {"field": "RT_ADDRESS",    "size": "5 bits (bits 1-5, MSB-first)", "components": "0-30 valid; 31 = broadcast (Command Word only). Echoed in Status Word."},
            {"field": "T/R_BIT",       "size": "1 bit (bit 6)", "components": "Command Word only. 1 = RT transmits to BC; 0 = RT receives from BC."},
            {"field": "SUBADDRESS",    "size": "5 bits (bits 7-11)", "components": "Command Word: 1-30 = data subaddress; 0 or 31 = Mode Code (selector). Status Word: status bits at the same offsets."},
            {"field": "WORD_COUNT_OR_MODE_CODE", "size": "5 bits (bits 12-16)", "components": "Command Word: when Subaddress ≠ 0/31 → Word Count (1-32; 0=32). When Subaddress = 0/31 → Mode Code (00000 .. 10101)."},
            {"field": "DATA_PAYLOAD",  "size": "16 bits", "components": "Data Word payload. 0..32 Data Words per message."},
            {"field": "PARITY",        "size": "1 bit",   "value": "odd parity over the 16 data bits of the same word"},
        ])
        d.setdefault("data_length_code_encoding", {
            "header": ["Word Count Field (binary)", "Data Word Count", "Note"],
            "rows": [
                ["00000", "32", "All-zero word-count = 32 data words (special interpretation)."],
                ["00001", "1",  "Single data word."],
                ["00010", "2",  ""],
                ["00011", "3",  ""],
                ["00100", "4",  ""],
                ["00101", "5",  ""],
                ["00110", "6",  ""],
                ["00111", "7",  ""],
                ["01000", "8",  ""],
                ["10000", "16", ""],
                ["11000", "24", ""],
                ["11111", "31", "Maximum non-zero count; 32 is encoded as all-zero."],
            ],
            "note": "5-bit Word Count field encodes 1..32 data words; binary value 00000 is interpreted as 32 (max-data shortcut).",
        })
        d.setdefault("remote_frame_rules", [
            "A Command Word with T/R = 1 ('transmit') is a 'remote' / pull request to the addressed RT.",
            "The addressed RT responds: Status Word + N Data Words within 4-12 µs.",
            "If the RT cannot satisfy the request, it sets MESSAGE ERROR + does not transmit data.",
            "Broadcast (RT address 31) inhibits the Status Word response — the receiving RTs accept data silently.",
        ])
        d.setdefault("valid_ready_handshake_rules", [
            "There is no AMBA-style per-cycle VALID/READY handshake.",
            "Per-message handshake: BC sends Command (+ Data) → RT sends Status (+ Data) within 4-12 µs.",
            "The Status Word's MESSAGE ERROR bit + BUSY bit + SERVICE REQUEST bit + BROADCAST COMMAND RECEIVED bit provide message-level back-pressure / error signalling.",
            "BC enforces the 4 µs minimum inter-message gap before launching the next Command Word.",
            "No-response timeout = 14 µs of bus quiet after the last command word → BC declares 'no response' and may retry on Bus B.",
        ])
        d.setdefault("burst_based", False)
        d.setdefault("byte_oriented_within_data_field", False)
        d.setdefault("byte_order_within_data_field",
            "MSB-first (bit 1 of the 16-bit data word is the most significant bit). Multi-word payload ordering is application-defined.")
        d.setdefault("interframe_space", {
            "minimum_inter_message_gap": "≥ 4 µs",
            "rt_response_window":        "4 µs to 12 µs after the last bit of the BC's command word",
            "rt_no_response_timeout":    "14 µs (BC declares no-response after this)",
            "broadcast_gap":             "Same 4 µs minimum; no RT status response in broadcast",
        })
        _write(p, d)

    # L4 wire-level — no register map
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = False
        d["notes"] = (
            "MIL-STD-1553B is a wire-level protocol specification — it "
            "defines the bus, the word framing, the message formats, and "
            "the bus-controller / remote-terminal / bus-monitor roles. "
            "There is no architectural register map at the protocol layer. "
            "Concrete 1553 controller and Remote-Terminal IP (e.g. Data "
            "Device Corporation BU-65170 / BU-61580 series, Holt HI-6130 "
            "/ HI-1573, UTMC UT69151, AIM ABC Bus Cards, FPGA cores) each "
            "define their own SoC-facing register file — typically: "
            "bus-A/bus-B configuration, RT address strap, status-word "
            "programmable bits (Busy / Subsystem Flag / Terminal Flag), "
            "subaddress descriptor table, 32-word transmit and receive "
            "data buffers per subaddress, mode-code mask, BIT word, "
            "IRQ-enable / IRQ-status, and message-time-stamp counters. "
            "Those register files are documented in each device's data "
            "sheet, not in MIL-STD-1553B itself.")
        _write(p, d)

    # L5 — analog interface IS defined explicitly in 1553B
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        # Force True (overwrite): SPI-class _apply_universal runs FIRST and
        # sets this to False; 1553 explicitly defines analog signalling
        # (differential Manchester II on transformer-coupled 78Ω twinax)
        # so we must override the universal-class default.
        d["analog_digital_interface_present"] = True
        d["signaling_summary"] = (
            "MIL-STD-1553B defines the analog signalling explicitly so "
            "that any conformant transmitter / receiver can interoperate "
            "on the same bus. Bus medium = 78 Ω characteristic-impedance "
            "twinax (cable spec 70-85 Ω). Signalling is differential "
            "Manchester II bi-phase: logical 1 = positive-then-negative "
            "half-bit; logical 0 = negative-then-positive half-bit; bit "
            "rate 1.0 Mbit/s (1 µs per bit). Sync field is a "
            "NON-Manchester 3 µs pattern (Command/Status: HIGH-1.5µs "
            "then LOW-1.5µs ; Data: LOW-1.5µs then HIGH-1.5µs) that "
            "cannot appear in any Manchester payload. Transmitter "
            "peak-to-peak output 18-27 V (transformer-coupled stub). "
            "Receiver must detect signals as low as 0.86-2.5 Vp-p "
            "(depending on coupling). Bit-rate accuracy ±0.1 % "
            "long-term, ±0.01 % short-term. Transformer coupling "
            "provides DC isolation, ≥ 75 % shielding, common-mode "
            "rejection, and lightning-strike tolerance. Stub lengths: "
            "transformer-coupled ≤ 20 ft / 6.1 m; direct-coupled ≤ 1 "
            "ft / 0.3 m. Isolation transformer turns ratio 1:1.41 ± 3 "
            "%, isolation resistors 0.75 × Zo ± 2 % (each); "
            "direct-coupled isolation resistors 55 Ω ± 2 %. Bus "
            "terminated at both ends in characteristic impedance.")
        _write(p, d)

    # L6 control logic
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("device_role_states", [
            {"name": "Bus Controller (BC)",
             "description": "Active master of the bus this cycle. Issues Command Words, schedules transfers, receives Status Words, and decides retry policy. Exactly one BC active per bus at any time."},
            {"name": "Backup Bus Controller (BBC)",
             "description": "Standby BC. Becomes active via Dynamic Bus Control mode-code handoff or via discrete failover line + bus-quiescent detection."},
            {"name": "Remote Terminal (RT)",
             "description": "Slave / responder. Decodes each Command Word; if addressed and able, responds with Status Word (+ Data Words) within 4-12 µs."},
            {"name": "Bus Monitor (BM)",
             "description": "Passive listener. Records every word for telemetry / off-line analysis. SHALL NOT transmit on the bus."},
        ])
        d.setdefault("fsm_hints_bus_controller", [
            {"name": "BC_IDLE",              "description": "Bus quiescent (no message in flight). BC selects next message from its schedule (cyclic-executive or acyclic)."},
            {"name": "BC_SELECT_BUS",        "description": "BC chooses Bus A or Bus B for this message; redundancy is per-message."},
            {"name": "BC_TX_COMMAND",        "description": "BC transmits Command Word (3 µs Command/Status sync + 16 bits + odd parity)."},
            {"name": "BC_TX_DATA",           "description": "(BC→RT message only) BC transmits 1..32 Data Words back-to-back (each 3 µs Data sync + 16 bits + parity), then transitions to wait-for-status."},
            {"name": "BC_WAIT_RT_RESPONSE",  "description": "BC waits 4-12 µs for the addressed RT's Status Word; after 14 µs of bus quiet, declares no-response."},
            {"name": "BC_RX_STATUS",         "description": "BC receives and validates Status Word; checks RT-address echo + MESSAGE ERROR + BUSY + SERVICE REQUEST + BROADCAST COMMAND RECEIVED + SUBSYSTEM FLAG + DYNAMIC BUS ACCEPTANCE + TERMINAL FLAG."},
            {"name": "BC_RX_DATA",           "description": "(RT→BC message only) BC receives 1..32 Data Words from the RT immediately after the RT's Status Word."},
            {"name": "BC_GAP",               "description": "BC enforces ≥ 4 µs inter-message gap before launching the next Command Word."},
            {"name": "BC_RETRY",             "description": "On no-response or error Status, BC retries on the same bus or immediately on the redundant bus per retry policy."},
        ])
        d.setdefault("fsm_hints_remote_terminal", [
            {"name": "RT_IDLE",              "description": "Bus quiet. RT continuously samples the bus for a Command/Status sync field."},
            {"name": "RT_RX_COMMAND",        "description": "RT decodes Command Word; checks Manchester encoding + odd parity + sync polarity + RT-address match (or broadcast)."},
            {"name": "RT_DECODE",            "description": "RT classifies the command: receive-data, transmit-data, mode-without-data, mode-with-data. Subaddress 0/31 routes to Mode Code path."},
            {"name": "RT_RX_DATA",           "description": "(receive-message only) RT receives the BC's Data Words (count = Word Count field), buffering each into the addressed subaddress data buffer."},
            {"name": "RT_RESPONSE_GAP",      "description": "RT waits the response delay (≥ 4 µs from end of last received word) before transmitting Status."},
            {"name": "RT_TX_STATUS",         "description": "RT transmits Status Word echoing its address + status bits (Message Error / Service Request / Busy / Subsystem Flag / Terminal Flag / etc.). Broadcast (RT address 31): RT SHALL NOT transmit Status."},
            {"name": "RT_TX_DATA",           "description": "(transmit-message or mode-with-data-transmit) RT transmits 1..32 Data Words from the addressed subaddress / Vector Word."},
            {"name": "RT_SUPERSEDE",         "description": "If during RT's own response a new sync from BC arrives, RT supersedes its own message (BC reassertion)."},
        ])
        d.setdefault("fsm_hints_bus_monitor", [
            {"name": "BM_IDLE_LISTEN",       "description": "Continuously samples both Bus A and Bus B for sync activity; records every Manchester word with its time stamp."},
            {"name": "BM_DECODE",            "description": "BM decodes each word into Command / Status / Data based on sync polarity + position in the message; logs to local memory."},
            {"name": "BM_FILTER",            "description": "Optional acceptance filter by RT address / subaddress / message type to bound storage."},
            {"name": "BM_NEVER_TX",          "description": "BM transmitter SHALL be permanently disabled."},
        ])
        d.setdefault("synchronization_rules", [
            "Each word starts with a 3 µs SYNC field. Command/Status sync = HIGH 1.5 µs then LOW 1.5 µs. Data sync = LOW 1.5 µs then HIGH 1.5 µs (inverted).",
            "Sync field is NON-Manchester — it cannot occur in the Manchester-coded payload and is unambiguous against bit-cell encoding.",
            "Receivers sample at mid-bit (Manchester mid-bit transition); a missing or wrong-polarity transition is a Manchester encoding error and the word is discarded.",
            "All 1553 nodes share the same 1 Mbit/s bit clock; long-term ±0.1 % accuracy / short-term ±0.01 % stability bounds free-running clock drift across a message.",
        ])
        d.setdefault("arbitration_rule",
            "No bitwise arbitration. The Bus Controller is the single transmitter at any given time (master/slave). All bus access is initiated by the BC's Command Word; RTs may only respond when explicitly addressed.")
        d.setdefault("anti_deadlock_rule",
            "BC enforces the 14 µs no-response timeout and retries on the redundant bus. A misbehaving RT cannot lock the bus because (a) RT has no autonomous TX rights and (b) the BC may shut down a specific RT transmitter via the Transmitter Shutdown / Selected Transmitter Shutdown mode codes.")
        d.setdefault("exit_from_reset_or_wakeup",
            "On power-up or after a Reset Remote Terminal mode code (01000), the RT initializes its subaddress descriptor table, clears Status-Word condition bits, performs power-on BIT, and enters RT_IDLE listening for the next Command Word.")
        d.setdefault("default_signal_state_when_bus_free",
            "Bus is quiescent (no Manchester transitions). Inter-message gap ≥ 4 µs of no activity. The bus is differentially terminated at both ends; differential voltage is near zero when idle.")
        d.setdefault("wake_up_message_identifier",
            "Not applicable in the protocol — 1553 has no protocol-level sleep / wake state machine. BC simply resumes transfers when subsystems are ready. Some integrators implement a BC heartbeat (e.g. Transmit Status Word polling) as a wake-up surrogate.")
        _write(p, d)

    # L7 test/debug
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", True)
        d.setdefault("spec_provided_observability", [
            {"name": "STATUS WORD (RT → BC)",         "purpose": "Per-message observability of the addressed RT. 9 condition bits: Message Error, Instrumentation, Service Request, Broadcast Command Received, Busy, Subsystem Flag, Dynamic Bus Acceptance, Terminal Flag (+ RT address echo for verification)."},
            {"name": "MESSAGE ERROR bit (Status Word bit 6)", "purpose": "RT signals to BC that an error was detected in the BC's preceding command sequence; RT will not transmit data when this bit is set."},
            {"name": "SERVICE REQUEST bit (bit 8)",   "purpose": "RT requests an acyclic / out-of-schedule transfer; BC typically responds by issuing the Transmit Vector Word mode code."},
            {"name": "BUSY bit (bit 13)",             "purpose": "RT cannot service the command this cycle (subsystem not ready); BC may retry later."},
            {"name": "SUBSYSTEM FLAG bit (bit 14)",   "purpose": "RT signals subsystem-level fault (driven from subsystem behind the RT interface)."},
            {"name": "TERMINAL FLAG bit (bit 16)",    "purpose": "RT-internal fault (e.g. BIT failure); can be inhibited via Inhibit Terminal Flag mode code."},
            {"name": "DYNAMIC BUS ACCEPTANCE bit (bit 15)", "purpose": "Acknowledgement of Dynamic Bus Control mode code — RT accepts BC role."},
            {"name": "BROADCAST COMMAND RECEIVED bit (bit 12)", "purpose": "RT confirms (out-of-band on next Transmit Status query) that the last command was a broadcast."},
            {"name": "BIT WORD (mode code 10011)",   "purpose": "Mandatory Built-In-Test word — RT-defined 16-bit health vector returned on request."},
            {"name": "TRANSMIT LAST COMMAND (mode code 10010)", "purpose": "Mandatory — RT echoes the last Command Word it received; lets BC diagnose lost / corrupted commands."},
            {"name": "TRANSMIT STATUS WORD (mode code 00010)", "purpose": "Mandatory — RT re-issues its current Status Word without performing a data transfer; used by BC to poll RT health."},
            {"name": "BUS MONITOR",                   "purpose": "Passive node that records every word on both Bus A and Bus B (with time stamps) for off-line analysis."},
        ])
        d.setdefault("self_check_mechanisms", [
            "Per-word odd parity (catches single-bit errors).",
            "Manchester encoding self-clocked check (catches missing / wrong-polarity mid-bit transitions).",
            "Sync polarity check (catches misframed words; cannot mistake Command/Status for Data).",
            "Word-count vs received-Data-Word count cross-check (catches truncated / extended messages).",
            "4-12 µs RT response window + 14 µs no-response timeout (catches missing or slow responses).",
            "Initiate Self Test mode code (00011) triggers RT-internal BIT.",
            "Transmit BIT Word mode code (10011) returns 16-bit RT health vector to BC.",
            "Inter-message gap ≥ 4 µs sanity check on BC.",
            "Dual-redundant bus retry (Bus A ↔ Bus B) provides single-fault tolerance.",
        ])
        d.setdefault("error_count_thresholds", [
            {"threshold": "Application-defined",
             "consequence": "1553B does not standardize a fault-confinement counter scheme like CAN. Integrators define their own retry limit + bus-error counters in the host BC software (typical: 3 retries before declaring an RT 'failed', plus immediate retry on redundant bus)."},
        ])
        d.setdefault("recovery_from_bus_off",
            "Not applicable — 1553B has no bus-off state. A defective RT can be commanded into Transmitter Shutdown (mode code 00100) or Selected Transmitter Shutdown (10100). A defective BC is replaced by the Backup BC via Dynamic Bus Control (mode code 00000) or discrete failover.")
        d.setdefault("rt_validation_test_plan",
            "SAE AS4111 — RT Validation Test Plan (formerly MIL-HDBK-1553A Section 100, originally MIL-HDBK-1553 Appendix A). Comprehensive design-verification suite maintained by the SAE AS-1A Avionic Networks Subcommittee for RTs designed to AS 15531 and 1553B Notice 2.")
        d.setdefault("rt_production_test_plan",
            "SAE AS4112 — RT Production Test Plan. Simplified subset of AS4111 intended for in-line production testing of Remote Terminals.")
        d.setdefault("notes",
            "MIL-STD-1553B does not specify scan / JTAG / BIST at the silicon level. Protocol-level self-checking (parity + Manchester + sync polarity + word-count + response timing + Status Word condition bits + BIT Word mode code) plus dual-bus retry plus passive Bus Monitor + SAE AS4111 / AS4112 industry test plans give a comprehensive observability and validation envelope.")
        _write(p, d)

    # L8 RTL constants
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "WORD_TOTAL_WIDTH_bits": 20,
                "WORD_SYNC_WIDTH_bit_equivalent": 3,
                "WORD_DATA_WIDTH_bits": 16,
                "WORD_PARITY_WIDTH_bits": 1,
                "RT_ADDRESS_WIDTH_bits": 5,
                "TR_BIT_WIDTH_bits": 1,
                "SUBADDRESS_WIDTH_bits": 5,
                "WORD_COUNT_WIDTH_bits": 5,
                "MODE_CODE_WIDTH_bits": 5,
                "STATUS_BITS_WIDTH_bits": 11,
                "MAX_DATA_WORDS_PER_MESSAGE": 32,
                "MIN_DATA_WORDS_PER_MESSAGE": 0,
                "BROADCAST_RT_ADDRESS": 31,
                "RT_ADDRESS_MIN_VALID": 0,
                "RT_ADDRESS_MAX_VALID": 30,
                "MODE_CODE_SUBADDRESS_RESERVED_A": 0,
                "MODE_CODE_SUBADDRESS_RESERVED_B": 31,
                "MAX_RTS_PER_BUS": 31,
                "REDUNDANT_BUS_COUNT": 2,
                "STUB_LENGTH_MAX_TRANSFORMER_COUPLED_FEET": 20,
                "STUB_LENGTH_MAX_DIRECT_COUPLED_FEET": 1,
                "ISOLATION_RESISTOR_DIRECT_COUPLED_OHMS": 55,
            }.items():
                wp.setdefault(k, v)
        d.setdefault("manchester_encoding", {
            "name": "Manchester II bi-phase",
            "bit_period_us": 1.0,
            "half_bit_period_us": 0.5,
            "logical_one_encoding": "high half then low half within bit-cell (positive transition at mid-bit absent; falling edge mid-bit)",
            "logical_zero_encoding": "low half then high half within bit-cell (rising edge mid-bit)",
            "mid_bit_transition_required": True,
            "no_dc_component": True,
            "clock_recovery": "from mid-bit transitions in the Manchester-coded payload.",
        })
        d.setdefault("sync_patterns", {
            "command_status_sync": {
                "shape":      "HIGH for 1.5 µs then LOW for 1.5 µs",
                "duration_us": 3.0,
                "bit_equivalent": 3,
                "non_manchester": True,
                "use": "First field of every Command Word AND every Status Word.",
            },
            "data_sync": {
                "shape":      "LOW for 1.5 µs then HIGH for 1.5 µs",
                "duration_us": 3.0,
                "bit_equivalent": 3,
                "non_manchester": True,
                "use": "First field of every Data Word; cannot occur in Manchester payload, so sync is unambiguous.",
            },
        })
        d.setdefault("bit_timing_constants", {
            "BIT_RATE_Mbps": 1.0,
            "BIT_TIME_us": 1.0,
            "HALF_BIT_TIME_us": 0.5,
            "BIT_RATE_LONG_TERM_TOLERANCE_percent": 0.1,
            "BIT_RATE_SHORT_TERM_TOLERANCE_percent": 0.01,
            "WORD_DURATION_us": 20.0,
            "INTER_MESSAGE_GAP_MIN_us": 4.0,
            "RT_RESPONSE_TIME_MIN_us": 4.0,
            "RT_RESPONSE_TIME_MAX_us": 12.0,
            "BC_NO_RESPONSE_TIMEOUT_us": 14.0,
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "word_format": {
                "sync_field":   "3 µs non-Manchester pattern (Command/Status: HL ; Data: LH)",
                "data_field":   "16 bits, MSB-first, Manchester II bi-phase",
                "parity_field": "1 bit, odd parity over the 16 data bits",
            },
            "command_word_layout": {
                "bits_1_to_5":   "RT_ADDRESS",
                "bit_6":         "T_R (1=transmit-from-RT, 0=receive-to-RT)",
                "bits_7_to_11":  "SUBADDRESS_OR_MODE (0 or 31 selects Mode Code)",
                "bits_12_to_16": "WORD_COUNT_OR_MODE_CODE",
            },
            "status_word_layout": {
                "bits_1_to_5":   "RT_ADDRESS_ECHO",
                "bit_6":         "MESSAGE_ERROR",
                "bit_7":         "INSTRUMENTATION",
                "bit_8":         "SERVICE_REQUEST",
                "bits_9_to_11":  "RESERVED (must be 0)",
                "bit_12":        "BROADCAST_COMMAND_RECEIVED",
                "bit_13":        "BUSY",
                "bit_14":        "SUBSYSTEM_FLAG",
                "bit_15":        "DYNAMIC_BUS_ACCEPTANCE",
                "bit_16":        "TERMINAL_FLAG",
            },
            "parity_rule":        "odd parity → (XOR of 16 data bits XOR parity bit) = 1",
            "broadcast_address":  31,
            "all_zero_word_count_means": 32,
            "mode_code_subaddresses": [0, 31],
            "max_data_words_per_message": 32,
            "redundant_bus_select": "Per-message; BC chooses Bus A or Bus B; messages traverse only one bus at a time.",
        })
        d.setdefault("mode_code_constants", {
            "DYNAMIC_BUS_CONTROL":                       "00000",
            "SYNCHRONIZE_NO_DATA":                       "00001",
            "TRANSMIT_STATUS_WORD":                      "00010",
            "INITIATE_SELF_TEST":                        "00011",
            "TRANSMITTER_SHUTDOWN":                      "00100",
            "OVERRIDE_TRANSMITTER_SHUTDOWN":             "00101",
            "INHIBIT_TERMINAL_FLAG_BIT":                 "00110",
            "OVERRIDE_INHIBIT_TERMINAL_FLAG_BIT":        "00111",
            "RESET_REMOTE_TERMINAL":                     "01000",
            "TRANSMIT_VECTOR_WORD":                      "10000",
            "SYNCHRONIZE_WITH_DATA_WORD":                "10001",
            "TRANSMIT_LAST_COMMAND":                     "10010",
            "TRANSMIT_BIT_WORD":                         "10011",
            "SELECTED_TRANSMITTER_SHUTDOWN":             "10100",
            "OVERRIDE_SELECTED_TRANSMITTER_SHUTDOWN":    "10101",
        })
        d.setdefault("electrical_constants", {
            "BUS_CHARACTERISTIC_IMPEDANCE_OHMS_NOMINAL": 78,
            "BUS_CHARACTERISTIC_IMPEDANCE_OHMS_RANGE":   [70, 85],
            "TX_OUTPUT_PEAK_TO_PEAK_VOLTS_MIN":          18,
            "TX_OUTPUT_PEAK_TO_PEAK_VOLTS_MAX":          27,
            "ISOLATION_TRANSFORMER_TURNS_RATIO":         "1:1.41",
            "ISOLATION_TRANSFORMER_TOLERANCE_percent":   3.0,
            "STUB_ISOLATION_RESISTOR_VALUE_TIMES_Zo":    0.75,
            "STUB_ISOLATION_RESISTOR_TOLERANCE_percent": 2.0,
            "DIRECT_COUPLED_ISOLATION_RESISTOR_OHMS":    55,
            "BUS_COUPLER_SHIELDING_MIN_percent":         75,
            "TYPICAL_CABLE_PROPAGATION_DELAY_ns_per_foot": 1.6,
        })
        _write(p, d)

    # L8_TIMING
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("word_format_structure", {
            "TOTAL_DURATION":   "20 µs per word (3 µs sync + 16 µs data + 1 µs parity)",
            "SYNC_FIELD":       "3 µs, NON-Manchester. Command/Status: HIGH 1.5 µs then LOW 1.5 µs. Data: LOW 1.5 µs then HIGH 1.5 µs.",
            "DATA_FIELD":       "16 bits × 1 µs = 16 µs. Manchester II bi-phase, MSB-first.",
            "PARITY_FIELD":     "1 bit × 1 µs = 1 µs. Odd parity over the 16 data bits.",
            "BIT_PERIOD":       "1 µs (1.0 Mbit/s). Half-bit period 0.5 µs.",
        })
        d.setdefault("manchester_encoding_waveform", {
            "LOGICAL_1":  "First half-bit HIGH (0.5 µs) then second half-bit LOW (0.5 µs).",
            "LOGICAL_0":  "First half-bit LOW (0.5 µs) then second half-bit HIGH (0.5 µs).",
            "MID_BIT_TRANSITION": "Mandatory mid-bit edge; receivers recover clock from this transition.",
            "NO_DC_COMPONENT":    "Average voltage over any bit-cell is zero (transformer-friendly).",
        })
        d.setdefault("sync_waveform", {
            "COMMAND_STATUS_SYNC": "3 µs total: HIGH for 1.5 µs immediately followed by LOW for 1.5 µs. Cannot occur in Manchester payload (no payload sequence produces 1.5 µs sustained high then 1.5 µs sustained low).",
            "DATA_SYNC":           "3 µs total: LOW for 1.5 µs immediately followed by HIGH for 1.5 µs. Inverse polarity of Command/Status sync. Cannot occur in Manchester payload.",
        })
        d.setdefault("message_waveform", {
            "BC_TO_RT_TRANSFER": "BC: Receive-Command-Word (20 µs) → BC: N×Data-Word (20 µs each) → 4-12 µs response gap → RT: Status-Word (20 µs) → ≥ 4 µs inter-message gap.",
            "RT_TO_BC_TRANSFER": "BC: Transmit-Command-Word (20 µs) → 4-12 µs response gap → RT: Status-Word (20 µs) → RT: N×Data-Word (20 µs each) → ≥ 4 µs inter-message gap.",
            "RT_TO_RT_TRANSFER": "BC: Receive-Command (to RT2) (20 µs) → BC: Transmit-Command (to RT1) (20 µs) → 4-12 µs gap → RT1: Status (20 µs) → RT1: N×Data (20 µs each) → 4-12 µs gap → RT2: Status (20 µs) → ≥ 4 µs inter-message gap.",
            "MODE_WITHOUT_DATA": "BC: Mode-Command (20 µs) → 4-12 µs gap → RT: Status (20 µs) → ≥ 4 µs gap.",
            "MODE_WITH_DATA_TRANSMIT": "BC: Mode-Command (20 µs) → 4-12 µs gap → RT: Status (20 µs) → RT: 1×Data (20 µs) → ≥ 4 µs gap.",
            "MODE_WITH_DATA_RECEIVE":  "BC: Mode-Command (20 µs) → BC: 1×Data (20 µs) → 4-12 µs gap → RT: Status (20 µs) → ≥ 4 µs gap.",
            "BROADCAST_TRANSFER":      "Same as BC-to-RT format but RT address = 31. RTs DO NOT transmit Status Word.",
        })
        d.setdefault("timing_intervals", {
            "BIT_PERIOD_us":              1.0,
            "WORD_PERIOD_us":             20.0,
            "INTER_MESSAGE_GAP_MIN_us":   4.0,
            "RT_RESPONSE_TIME_MIN_us":    4.0,
            "RT_RESPONSE_TIME_MAX_us":    12.0,
            "BC_NO_RESPONSE_TIMEOUT_us":  14.0,
            "BIT_RATE_LONG_TERM_PPM":     1000,
            "BIT_RATE_SHORT_TERM_PPM":    100,
        })
        d.setdefault("broadcast_waveform_special",
            "Broadcast (RT address 31): receiving RTs accept the Data Word(s) but DO NOT transmit a Status Word — the Status Word slot is left silent to prevent multiple-RT collision on the bus.")
        d.setdefault("dual_redundant_bus_waveform",
            "Bus A and Bus B carry the same protocol independently. A message is launched on only one of the two buses; the redundant bus is electrically idle. On no-response or error, the BC may retransmit the same message immediately on the redundant bus.")
        d.setdefault("rt_supersede_rule",
            "If the BC asserts a new Command/Status sync while an RT is still transmitting its response, the RT must abort its own transmission and treat the new BC word as the next command (supersede).")
        d.setdefault("max_message_length_us",
            "Command (20 µs) + 32 × Data (640 µs) + 12 µs gap + Status (20 µs) ≈ 692 µs for max-payload RT-to-BC or BC-to-RT (excluding final inter-message gap).")
        _write(p, d)

    # L9 integration
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "Half-duplex command/response time-division multiplex avionics data bus. A 1553B system integrates a Bus Controller (BC) + up to 31 Remote Terminals (RTs) + optional Backup Bus Controller (BBC) + optional Bus Monitor (BM) onto a dual-redundant 78 Ω twinax differential bus, with all protocol semantics captured in 20-bit Manchester II words and 9 message formats (6 BC↔RT + 4 broadcast).")
        d.setdefault("layered_structure_summary", [
            "Application Layer — schedule of transfers (cyclic-executive frames + acyclic Vector-Word polling); subsystem semantics; integrator's responsibility.",
            "Message Layer — 6 BC↔RT formats + 4 broadcast formats; 10 mode codes; Service-Request / Vector-Word handshake for acyclic transfers.",
            "Word Layer — 3 word types (Command / Status / Data); 20-bit framing (3 µs sync + 16 data + 1 odd parity).",
            "Encoding Layer — Manchester II at 1.0 Mbit/s; sync polarity distinguishes Command/Status from Data.",
            "Physical Layer — 78 Ω twinax (70-85 Ω), 18-27 Vp-p tx, isolation transformers (1:1.41 ± 3 %), 0.75 × Zo isolation resistors, ≥ 75 % shielded couplers, transformer-coupled stubs (≤ 20 ft) or direct-coupled stubs (≤ 1 ft), dual-redundant bus pair.",
        ])
        d.setdefault("integration_overview", {
            "topology":                    "Linear multidrop twinax bus; up to 31 RTs + 1 BC per bus; dual-redundant bus pair (Bus A + Bus B).",
            "drive_type":                  "Differential Manchester II; transformer-coupled stubs preferred for DC isolation + lightning tolerance.",
            "addressing":                  "5-bit RT address (0-30); RT address 31 = broadcast; subaddress 0/31 = Mode Code.",
            "uniform_bit_rate":            "1.0 Mbit/s for every node on the bus.",
            "bus_role_assignment":         "Exactly one BC active per bus per cycle; standby = Backup BC; passive = Bus Monitor.",
            "max_baud":                    "1 Mbit/s (the protocol is fixed-rate; no variable baud).",
        })
        d.setdefault("interface_categories", [
            "BUS CONTROLLER (BC) — originates every transfer; one active per bus.",
            "BACKUP BUS CONTROLLER (BBC / BUBC) — standby BC; assumes role via Dynamic Bus Control or discrete failover.",
            "REMOTE TERMINAL (RT) — slave / responder; up to 31 distinct addresses (0-30 valid; 31 = broadcast).",
            "BUS MONITOR (BM) — passive recorder; cannot transmit.",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Single linear twinax bus — common in older avionics installations.",
            "Dual-redundant twinax bus pair (Bus A + Bus B) — standard 1553B configuration.",
            "Tri-redundant or higher bus — implementation-defined extension (used on some spacecraft).",
            "Optical-fibre variant — MIL-STD-1773 (same protocol, fibre PHY).",
            "Coexistence with STANAG 3910 / EFABus — high-speed data piggybacked on the same 1553 wire pair.",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "Bus quiescent (no Manchester transitions; near-zero differential voltage on twinax). Inter-message gap ≥ 4 µs of no activity. The bus is terminated at both ends in characteristic impedance.")
        d.setdefault("soc_dependent_items", [
            "Choice of 1553 controller / RT IP (DDC BU-65170 / BU-61580; Holt HI-6130 / HI-1573; UTMC UT69151; AIM ABC; FPGA cores).",
            "5-bit RT address strap pins (parity-protected so the RT can self-verify its address).",
            "Subaddress descriptor table programming (which subaddress maps to which TX / RX data buffer).",
            "Programmable Status-Word bits: Busy / Subsystem Flag / Terminal Flag driven by subsystem-level signals.",
            "Power-on BIT word + Initiate Self Test mode-code handling.",
            "Bus-A / Bus-B transceiver pairing; redundancy steering at silicon level.",
            "Isolation-transformer + stub-coupler box design (mechanical + EMC).",
            "Interrupt routing for: message-received / message-transmitted / illegal-command / no-response / parity-error events.",
            "Time-stamp counter for Bus Monitor logging.",
            "BC's cyclic-executive scheduler implementation (50 Hz / 25 Hz / 12.5 Hz / etc. minor cycles).",
        ])
        d.setdefault("low_power_modes", {
            "sleep_mode":         "Not defined at the protocol layer. 1553 nodes are typically always-on in avionics.",
            "wake_up":            "Not applicable. Integrators implement subsystem-level power management outside 1553.",
            "transmitter_shutdown_mode_code": "Mode Code 00100 (Transmitter Shutdown) effectively powers down a redundant transmitter; override via 00101.",
        })
        _write(p, d)

    # L10 test cases
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        # Force overwrite (not setdefault): SPI-class _apply_universal runs
        # FIRST and pre-sets a generic "spec provides functional description"
        # string; 1553 has explicit mandatory behaviours + AS4111/AS4112
        # industry test plans, so we override with the 1553-specific text.
        d["test_cases_present"] = (
            "partial - the spec defines mandatory protocol behaviors "
            "(word framing, sync polarity, parity, message formats, RT "
            "response timing) that map directly to compliance test "
            "scenarios; the SAE AS-1A Avionic Networks Subcommittee "
            "publishes the formal RT Validation Test Plan (AS4111) and "
            "RT Production Test Plan (AS4112).")
        if _empty(d.get("derived_compliance_test_categories")):
            d["derived_compliance_test_categories"] = [
                "Command Word with each valid Word Count (1..32; 0 encodes 32) — verify RT receives / transmits exactly the expected count.",
                "Status Word RT-address echo verification — ensure response carries the same RT address as the Command Word.",
                "Each of the 6 BC↔RT message formats: Controller-to-RT, RT-to-Controller, RT-to-RT, Mode Without Data, Mode With Data (Transmit), Mode With Data (Receive).",
                "Each of the 4 broadcast formats: Controller-to-RT(s), RT-to-RT(s), Mode Without Data (Broadcast), Mode With Data (Broadcast) — verify NO Status Word response from broadcast targets.",
                "All 10 standard Mode Codes (00000..01000 + 10000..10011 + 10100..10101) — verify expected RT response per spec.",
                "Mandatory Mode Codes Transmit Status Word (00010), Transmit Last Command (10010), Transmit BIT Word (10011) — verify implementation.",
                "Sync polarity discrimination — verify RT distinguishes Command/Status sync (HL) from Data sync (LH).",
                "Odd parity verification — inject even-parity corrupted words; RT must detect and set MESSAGE ERROR.",
                "Manchester encoding error injection — missing mid-bit transition; RT must reject the word.",
                "Word count mismatch injection — send fewer or more Data Words than declared; RT must flag MESSAGE ERROR.",
                "Illegal command — send RT a command for a subaddress / Mode Code it does not implement; RT must set MESSAGE ERROR + must NOT transmit data.",
                "RT response timing window — verify RT begins Status Word transmission within 4-12 µs after the last command word.",
                "BC no-response timeout — verify BC declares no-response after 14 µs of bus quiet.",
                "Inter-message gap — verify BC respects ≥ 4 µs minimum gap.",
                "Dual-redundant retry — inject Bus A fault; verify BC immediately retries on Bus B.",
                "Dynamic Bus Control handoff (Mode Code 00000) — verify backup BC sets Dynamic Bus Acceptance.",
                "Service Request → Vector Word — RT sets Service Request bit in Status; BC responds with Transmit Vector Word (10000) Mode Code.",
                "Busy bit — RT signals Busy; verify BC accepts and retries later.",
                "Subsystem Flag — RT's subsystem-driven fault signal correctly propagates.",
                "Terminal Flag inhibit / override — verify Mode Codes 00110 / 00111 mask / unmask Terminal Flag bit.",
                "Transmitter Shutdown / Override — verify Mode Codes 00100 / 00101 disable / re-enable the redundant transmitter.",
                "Reset Remote Terminal — verify Mode Code 01000 returns RT to initialized state.",
                "Power-on Built-In-Test → BIT word return on Mode Code 10011.",
                "RT supersede — issue a new Command/Status sync during an RT's response; RT must abort its own transmission.",
                "Cable propagation delay — verify protocol behavior at maximum cable length (100 ft typical, ~160 ns end-to-end).",
                "Industry test plans: SAE AS4111 (RT Validation), AS4112 (RT Production), ISO STANAG 3838 conformance suite.",
            ]
        _write(p, d)

    # L11 OTP
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "MIL-STD-1553B is a wire-level protocol spec; there is no OTP "
            "/ fuse / configuration ROM at the protocol layer. Concrete "
            "1553 Remote Terminal IP commonly uses straps or OTP to set "
            "the 5-bit RT address (often with a 6th parity-protect bit). "
            "Some RTs also use OTP to lock the BIT word, the Subaddress "
            "descriptor table defaults, or the redundant-bus assignment, "
            "but those are per-device design choices outside the scope "
            "of 1553B.")
        _write(p, d)

    # L12 behavioral
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("controller_to_rt_transfer_sequence", [
            "1. BC selects Bus A or Bus B for this message (from schedule).",
            "2. BC transmits Receive Command Word (RT address + T/R=0 + Subaddress + Word Count); 20 µs.",
            "3. BC immediately transmits N Data Words back-to-back (1..32 words, 20 µs each).",
            "4. After 4-12 µs response gap, RT transmits Status Word (RT address echo + status bits); 20 µs.",
            "5. BC enforces ≥ 4 µs inter-message gap.",
            "6. If RT does not respond by 14 µs, BC declares no-response; may retry on the redundant bus.",
        ])
        d.setdefault("rt_to_controller_transfer_sequence", [
            "1. BC selects bus.",
            "2. BC transmits Transmit Command Word (RT address + T/R=1 + Subaddress + Word Count); 20 µs.",
            "3. After 4-12 µs response gap, RT transmits Status Word (20 µs).",
            "4. RT immediately transmits N Data Words from the addressed subaddress buffer (1..32 words, 20 µs each).",
            "5. BC validates Status Word (MESSAGE ERROR + BUSY + etc.) and verifies Data Word count.",
            "6. BC enforces ≥ 4 µs inter-message gap.",
        ])
        d.setdefault("rt_to_rt_transfer_sequence", [
            "1. BC transmits Receive Command Word to RT2 (the data destination).",
            "2. BC immediately transmits Transmit Command Word to RT1 (the data source).",
            "3. After 4-12 µs gap, RT1 transmits Status Word.",
            "4. RT1 transmits N Data Words (read from its TX subaddress) on the bus.",
            "5. RT2 captures the Data Words into its RX subaddress buffer.",
            "6. After 4-12 µs gap, RT2 transmits its Status Word.",
            "7. BC validates both Status Words and enforces ≥ 4 µs inter-message gap.",
        ])
        d.setdefault("mode_command_without_data_sequence", [
            "1. BC transmits Mode Command Word (Subaddress = 0 or 31; bottom 5 bits = Mode Code) — e.g. Reset Remote Terminal (01000).",
            "2. After 4-12 µs gap, RT transmits Status Word.",
            "3. RT executes the mode action (reset / shutdown / etc.).",
            "4. BC enforces ≥ 4 µs inter-message gap.",
        ])
        d.setdefault("mode_command_with_data_transmit_sequence", [
            "1. BC transmits Mode Command Word (T/R=1; Mode Code = 10000 Transmit Vector Word, or 10010 Transmit Last Command, or 10011 Transmit BIT Word).",
            "2. After 4-12 µs gap, RT transmits Status Word.",
            "3. RT immediately transmits exactly 1 Data Word containing the requested mode-specific value.",
            "4. BC enforces ≥ 4 µs inter-message gap.",
        ])
        d.setdefault("mode_command_with_data_receive_sequence", [
            "1. BC transmits Mode Command Word (T/R=0; e.g. Synchronize with Data Word = 10001).",
            "2. BC immediately transmits exactly 1 Data Word (the mode-specific value).",
            "3. After 4-12 µs gap, RT transmits Status Word.",
            "4. RT executes the mode action using the received data.",
            "5. BC enforces ≥ 4 µs inter-message gap.",
        ])
        d.setdefault("broadcast_transfer_sequence", [
            "1. BC transmits Command Word with RT address = 31 (broadcast).",
            "2. BC transmits Data Words (if any) for the receive direction.",
            "3. Receiving RTs accept the data but DO NOT transmit a Status Word (to prevent bus contention).",
            "4. BC must move on to the next message after the appropriate inter-message gap.",
            "5. If BC needs to confirm broadcast reception, it polls each RT individually with Transmit Status Word (00010); the BROADCAST COMMAND RECEIVED bit reports success.",
        ])
        d.setdefault("service_request_acyclic_transfer_sequence", [
            "1. RT detects a need for an unscheduled transfer (subsystem event).",
            "2. RT sets the SERVICE REQUEST bit (bit 8) in its next Status Word.",
            "3. BC notices the SERVICE REQUEST bit during normal polling.",
            "4. BC issues a Transmit Vector Word (10000) Mode Command to that RT.",
            "5. RT responds with Status + 1 Data Word (the Vector Word) identifying the requested action.",
            "6. BC schedules the requested acyclic transfer in the next available slot.",
        ])
        d.setdefault("dynamic_bus_control_handoff_sequence", [
            "1. Current BC issues Dynamic Bus Control (Mode Code 00000) to the backup BC.",
            "2. Backup BC responds with Status Word; if it accepts the role, it sets DYNAMIC BUS ACCEPTANCE bit (bit 15).",
            "3. Current BC observes acceptance → relinquishes bus control after the current cycle.",
            "4. Backup BC begins issuing Command Words on its own schedule.",
            "5. (If the backup rejects the role, DYNAMIC BUS ACCEPTANCE is 0; current BC stays in control.)",
        ])
        d.setdefault("no_response_retry_sequence", [
            "1. BC transmits Command Word on Bus A.",
            "2. Bus is quiet for 14 µs after the last command word.",
            "3. BC declares no-response; logs in BC-internal error counter.",
            "4. BC immediately retries the same message on Bus B (redundant).",
            "5. If RT responds on Bus B, message succeeds.",
            "6. If both buses fail repeatedly, BC marks the RT failed and reports up to the host application.",
        ])
        d.setdefault("rt_supersede_sequence", [
            "1. RT is in the middle of transmitting its Status or Data response.",
            "2. BC asserts a new Command/Status sync (sync mid-stream).",
            "3. RT detects the sync, immediately aborts its own transmission, and starts decoding the new Command Word.",
            "4. This mechanism lets the BC recover authority on a misbehaving RT.",
        ])
        _write(p, d)

    # L13
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "MIL-STD-1553B is a wire-level protocol; there is no analog "
            "reference / trim / calibration loop in the protocol itself. "
            "Bit-rate tolerance (±0.1 % long-term / ±0.01 % short-term) "
            "is a system-integration concern. Physical layer parameters "
            "are pinned to fixed tolerances (78 Ω twinax 70-85 Ω, "
            "transmitter 18-27 Vp-p, isolation transformer 1:1.41 ± 3 %, "
            "isolation resistor 0.75 × Zo ± 2 % or 55 Ω ± 2 % "
            "direct-coupled) so no calibration loop is needed. Production "
            "lab verification is performed via the SAE AS4112 RT "
            "Production Test Plan + waveform-quality measurement against "
            "MIL-HDBK-1553A.")
        _write(p, d)

    # L14 versioning
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("spec_version",
            "MIL-STD-1553B (1978) — superseded by MIL-STD-1553C (Feb 2018; functionally equivalent, graphics/tables refresh).")
        if _empty(f.get("previous_versions")):
            f["previous_versions"] = [
                "MIL-STD-1553 (1973) — first publication; U.S. Air Force standard; first used on F-16 Falcon.",
                "MIL-STD-1553A (1975) — first revision; left many options to the user, causing inter-vendor incompatibility.",
                "MIL-STD-1553B (1978) — defines all options explicitly to ensure cross-vendor electrical / functional compatibility; primary current revision.",
                "MIL-STD-1553B Notice 1 (1980) — early clarifications.",
                "MIL-STD-1553B Notice 2 (1986) — retitled to 'Digital time division command/response multiplex data bus'; tightened terminology; aligned with AS 15531.",
                "MIL-STD-1553B Notices 3-6 (subsequent change notices through the 1990s and 2000s).",
                "MIL-STD-1553C (Feb 2018) — last revision; functionally equivalent to B; updated graphics and tables for readability.",
            ]
        if _empty(f.get("key_changes")):
            f["key_changes"] = [
                {"version": "1553 → 1553A",   "summary": "Initial revision (1975); left options open; inter-vendor implementations diverged."},
                {"version": "1553A → 1553B",  "summary": "Explicitly defined all electrical / functional options; introduced the dual-redundant bus pair as standard; established the 10 standard Mode Codes; mandated transformer-coupled stubs as preferred."},
                {"version": "1553B → 1553B Notice 2", "summary": "Retitled to 'Digital time division command/response multiplex data bus'; tightened wording; cross-referenced AS 15531."},
                {"version": "1553B → 1553C",  "summary": "Refreshed graphics and tables for readability; no functional change. Maintained jointly by US DoD and SAE."},
                {"version": "MIL-STD-1773",   "summary": "Optical-fibre variant; same protocol, fibre PHY; used in EMI/EMP-hardened applications. NASA AS 1773 experiment ran at 1 / 20 Mbit/s — likely predecessor of STANAG 3910."},
                {"version": "STANAG 3910 / EFABus", "summary": "High-rate (20 Mbit/s) data piggybacked on the 1553B physical layer; used by Eurofighter Typhoon."},
                {"version": "STANAG 3838 AVS / Def-Stan 00-18 Part 2", "summary": "NATO / UK MoD adoption of 1553B; functionally equivalent."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "1553A_to_1553B_optional_features",
                 "1553A_node":  "Implements options the integrator picked (Status-Word bit usage, mode-code subset, retry policy varied).",
                 "1553B_node":  "All electrical + functional options are explicitly fixed.",
                 "trap": "Mixed 1553A / 1553B fleets are NOT guaranteed to interoperate because of 1553A's optional Status bits + mode-code subset. Most fleets re-qualify all hardware to 1553B."},
                {"trap_name": "notice_2_terminology",
                 "pre_notice2": "Document title 'Aircraft internal time division command/response multiplex data bus'.",
                 "post_notice2": "Document title 'Digital time division command/response multiplex data bus'.",
                 "trap": "Old documentation references may use the pre-Notice-2 title and slightly different terminology for the same protocol; verify the latest notice."},
                {"trap_name": "stub_coupling_change",
                 "1553A":  "Direct-coupled stubs allowed without restriction.",
                 "1553B":  "Transformer-coupled stubs preferred; direct-coupled discouraged, limited to ≤ 1 ft stub length.",
                 "trap": "1553A direct-coupled installations may not meet 1553B electrical compatibility; couplers may need retrofit."},
                {"trap_name": "broadcast_optional_in_1553B",
                 "spec_required":     "Broadcast (RT address 31) is optional in 1553B — RTs may or may not implement it.",
                 "receiver_required": "BC schedule must not rely on broadcast if any RT on the bus does not implement it.",
                 "trap": "Mixed broadcast / non-broadcast RTs on the same bus break broadcast-based schedules."},
                {"trap_name": "1773_optical_dual_use",
                 "without_modification":  "1553B copper PHY.",
                 "with_1773_mods":   "Optical fibre PHY (DC isolated, EMP-hard); same protocol.",
                 "trap": "Mixed 1553 + 1773 segments need optical-to-copper media converters; bit-rate accuracy and timing tolerances are the same but waveform shape and amplitude detection differ."},
                {"trap_name": "stanag_3910_coexistence",
                 "spec_required":     "STANAG 3910 piggybacks 20 Mbit/s data on top of 1553 wiring.",
                 "receiver_required": "Pure-1553 nodes must filter out 3910 traffic; 3910-capable nodes must arbitrate between low-speed 1553 frames and high-speed 3910 bursts.",
                 "trap": "Pure-1553 RTs on a 3910-active bus may interpret 3910 traffic as noise / Manchester errors; co-deployment requires careful electrical filtering."},
            ]
        f.setdefault("version_naming_history_note",
            "MIL-STD-1553 originated as a U.S. Air Force standard in 1973 (F-16); revision A came in 1975 (option-rich, inter-vendor incompatible); revision B in 1978 froze all options for vendor-independence; Notice 2 (1986) refined terminology; revision C in 2018 is graphics-refreshed and functionally equivalent to B. NATO and SAE Aerospace co-maintain the standard (SAE AS 15531). The fibre variant is MIL-STD-1773; high-rate companion is STANAG 3910 / EFABus. New U.S. avionics designs may use IEEE 1394 (FireWire) in place of 1553.")
        d["fields"] = f
        _write(p, d)

    # L15 encoding tables
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("word_format_table", {
            "header_columns": ["Field", "Width", "Form"],
            "rows": [
                ["SYNC (Command/Status)", "3 µs (3-bit equivalent)", "Non-Manchester: HIGH 1.5 µs → LOW 1.5 µs"],
                ["SYNC (Data)",           "3 µs (3-bit equivalent)", "Non-Manchester: LOW 1.5 µs → HIGH 1.5 µs"],
                ["DATA",                  "16 bits",                  "Manchester II bi-phase, MSB-first"],
                ["PARITY",                "1 bit",                    "Odd parity over the 16 data bits"],
            ],
        })
        f.setdefault("command_word_bit_layout_table", {
            "header_columns": ["Field", "Bit Position (1-16)", "Width", "Purpose"],
            "rows": [
                ["RT_ADDRESS",                   "1-5",   "5 bits", "0-30 valid; 31 = broadcast (Command only)."],
                ["T_R_BIT",                      "6",     "1 bit",  "1 = RT transmits to BC; 0 = RT receives from BC."],
                ["SUBADDRESS_OR_MODE",           "7-11",  "5 bits", "1-30 = data subaddress; 0 or 31 = Mode Code selector."],
                ["WORD_COUNT_OR_MODE_CODE",      "12-16", "5 bits", "1-31 = data word count; 0 = 32 words; if Subaddress = 0/31 → Mode Code (00000..10101)."],
            ],
        })
        f.setdefault("status_word_bit_layout_table", {
            "header_columns": ["Field", "Bit Position (1-16)", "Width", "Purpose"],
            "rows": [
                ["RT_ADDRESS_ECHO",              "1-5",   "5 bits", "Echoes the RT address that is responding."],
                ["MESSAGE_ERROR",                "6",     "1 bit",  "RT detected an error in the preceding command (RT will NOT transmit data when set)."],
                ["INSTRUMENTATION",              "7",     "1 bit",  "Always 0 in modern 1553B; reserved for instrumentation use."],
                ["SERVICE_REQUEST",              "8",     "1 bit",  "RT requests an acyclic transfer (BC follows up with Transmit Vector Word)."],
                ["RESERVED",                     "9-11",  "3 bits", "Reserved (must be 0)."],
                ["BROADCAST_COMMAND_RECEIVED",   "12",    "1 bit",  "RT confirms it received the last command as broadcast."],
                ["BUSY",                         "13",    "1 bit",  "RT cannot service the command this cycle; BC may retry later."],
                ["SUBSYSTEM_FLAG",               "14",    "1 bit",  "Subsystem-level fault driven from behind the RT interface."],
                ["DYNAMIC_BUS_ACCEPTANCE",       "15",    "1 bit",  "Acknowledges Dynamic Bus Control mode code."],
                ["TERMINAL_FLAG",                "16",    "1 bit",  "RT-internal fault; can be inhibited via Inhibit Terminal Flag mode code."],
            ],
        })
        f.setdefault("data_length_code_table", {
            "header_columns": ["Word Count Field (binary)", "Decimal Word Count Interpreted", "Note"],
            "rows": [
                {"binary": "00000", "count": 32, "note": "All-zero shortcut = 32 data words (max)."},
                {"binary": "00001", "count": 1,  "note": ""},
                {"binary": "00010", "count": 2,  "note": ""},
                {"binary": "00100", "count": 4,  "note": ""},
                {"binary": "01000", "count": 8,  "note": ""},
                {"binary": "10000", "count": 16, "note": ""},
                {"binary": "11111", "count": 31, "note": "Maximum non-zero count."},
            ],
            "note": "5-bit field encodes 1..32 data words. Binary 00000 = 32 (special case).",
        })
        f.setdefault("mode_code_table", {
            "header_columns": ["Mode Code (binary)", "Name", "Has Data Word", "T/R", "Mandatory?"],
            "rows": [
                ["00000", "DYNAMIC_BUS_CONTROL",                       "No",  "1", "No"],
                ["00001", "SYNCHRONIZE_NO_DATA",                       "No",  "1", "No"],
                ["00010", "TRANSMIT_STATUS_WORD",                      "No",  "1", "Yes"],
                ["00011", "INITIATE_SELF_TEST",                        "No",  "1", "No"],
                ["00100", "TRANSMITTER_SHUTDOWN",                      "No",  "1", "No"],
                ["00101", "OVERRIDE_TRANSMITTER_SHUTDOWN",             "No",  "1", "No"],
                ["00110", "INHIBIT_TERMINAL_FLAG_BIT",                 "No",  "1", "No"],
                ["00111", "OVERRIDE_INHIBIT_TERMINAL_FLAG_BIT",        "No",  "1", "No"],
                ["01000", "RESET_REMOTE_TERMINAL",                     "No",  "1", "No"],
                ["10000", "TRANSMIT_VECTOR_WORD",                      "Yes", "1", "No"],
                ["10001", "SYNCHRONIZE_WITH_DATA_WORD",                "Yes", "0", "No"],
                ["10010", "TRANSMIT_LAST_COMMAND",                     "Yes", "1", "Yes"],
                ["10011", "TRANSMIT_BIT_WORD",                         "Yes", "1", "Yes"],
                ["10100", "SELECTED_TRANSMITTER_SHUTDOWN",             "Yes", "0", "No"],
                ["10101", "OVERRIDE_SELECTED_TRANSMITTER_SHUTDOWN",    "Yes", "0", "No"],
            ],
        })
        f.setdefault("message_format_table", {
            "header_columns": ["Format", "Composition (BC and RT exchanges)"],
            "rows": [
                ["1. Controller-to-RT Transfer",            "BC: Cmd → BC: N×Data → RT: Status"],
                ["2. RT-to-Controller Transfer",            "BC: Cmd → RT: Status → RT: N×Data"],
                ["3. RT-to-RT Transfer",                    "BC: RxCmd → BC: TxCmd → RT_tx: Status → RT_tx: N×Data → RT_rx: Status"],
                ["4. Mode Command Without Data Word",       "BC: Cmd(SA=0/31) → RT: Status"],
                ["5. Mode Command With Data Word (Transmit)","BC: Cmd(SA=0/31, T/R=1) → RT: Status → RT: 1×Data"],
                ["6. Mode Command With Data Word (Receive)", "BC: Cmd(SA=0/31, T/R=0) → BC: 1×Data → RT: Status"],
                ["7. Broadcast Controller-to-RT(s)",        "BC: Cmd(RT_addr=31) → BC: N×Data → (no Status)"],
                ["8. Broadcast RT-to-RT(s)",                "BC: RxCmd(RT_addr=31) → BC: TxCmd(specific) → RT_tx: Status → RT_tx: N×Data → (no Status from broadcast RTs)"],
                ["9. Broadcast Mode Without Data Word",     "BC: Cmd(RT_addr=31, SA=0/31) → (no Status)"],
                ["10. Broadcast Mode With Data Word",       "BC: Cmd(RT_addr=31, SA=0/31) → BC: 1×Data → (no Status)"],
            ],
        })
        f.setdefault("sync_pattern_table", {
            "header_columns": ["Word Type", "Sync Shape", "Duration"],
            "rows": [
                ["Command Word", "HIGH 1.5 µs → LOW 1.5 µs",  "3 µs"],
                ["Status Word",  "HIGH 1.5 µs → LOW 1.5 µs",  "3 µs"],
                ["Data Word",    "LOW 1.5 µs → HIGH 1.5 µs",  "3 µs"],
            ],
        })
        f.setdefault("manchester_encoding_table", {
            "header_columns": ["Logical Value", "First Half-Bit (0.5 µs)", "Second Half-Bit (0.5 µs)"],
            "rows": [
                ["1", "HIGH", "LOW"],
                ["0", "LOW",  "HIGH"],
            ],
        })
        f.setdefault("parity_rule",
            "Odd parity over the 16 data bits of the same word; parity bit = 1 if there are an even number of '1' data bits.")
        f.setdefault("broadcast_address_encoding",
            "RT address field = 31 (binary 11111) selects broadcast; receivers SHALL NOT transmit Status Word.")
        f.setdefault("mode_code_subaddress_encoding",
            "Subaddress field = 0 (00000) or 31 (11111) routes the bottom-5-bits as Mode Code instead of Word Count.")
        if _empty(f.get("tables")):
            f["tables"] = [
                "Word formats (Command, Status, Data) — Figures 3-5 of MIL-STD-1553B.",
                "Information transfer formats — Figure 6 (BC↔RT) and Figure 7 (broadcast).",
                "Command Word bit usage (RT address / T/R / Subaddress / Word Count).",
                "Status Word bit usage (RT address echo / 9 status bits + 3 reserved).",
                "Mode Code definitions — 10 standard codes + reserved range.",
            ]
        d["fields"] = f
        _write(p, d)

    # L16 compliance
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "Conform to MIL-STD-1553B (1978) or MIL-STD-1553C (Feb 2018, functionally equivalent).",
            "Bit coding: Manchester II bi-phase at 1.0 Mbit/s.",
            "Word framing: 3 µs sync + 16 data bits + 1 odd-parity bit = 20 µs per word.",
            "Distinct sync polarity: Command/Status sync = HIGH 1.5 µs then LOW 1.5 µs; Data sync = LOW 1.5 µs then HIGH 1.5 µs.",
            "Odd parity computed over the 16 data bits of each word.",
            "Command Word layout: bits 1-5 = RT address (5 bits); bit 6 = T/R; bits 7-11 = Subaddress or Mode Code selector; bits 12-16 = Word Count or Mode Code.",
            "Status Word layout: bits 1-5 = RT address echo; bit 6 = Message Error; bit 7 = Instrumentation; bit 8 = Service Request; bits 9-11 = Reserved (0); bit 12 = Broadcast Command Received; bit 13 = Busy; bit 14 = Subsystem Flag; bit 15 = Dynamic Bus Acceptance; bit 16 = Terminal Flag.",
            "Word Count field of 5 bits encoding 1..32 data words; binary 00000 = 32 (special).",
            "RT address range 0-30 valid; address 31 reserved for broadcast.",
            "Subaddress 0 and 31 reserved for Mode Codes.",
            "Inter-message gap ≥ 4 µs minimum.",
            "RT response time 4-12 µs after the last bit of the command word.",
            "BC no-response timeout = 14 µs.",
            "Implement mandatory Mode Codes: Transmit Status Word (00010), Transmit Last Command (10010), Transmit BIT Word (10011).",
            "Bus is dual-redundant (Bus A + Bus B); a message travels on only one bus at a time.",
            "Twinax bus characteristic impedance 70-85 Ω (78 Ω nominal); transmitter 18-27 Vp-p.",
            "Manchester encoding requires a mid-bit transition; missing or wrong-polarity transition is an encoding error.",
            "Broadcast (RT address 31): receiving RTs accept data but SHALL NOT transmit a Status Word.",
        ])
        f.setdefault("must_not_have_properties", [
            "Transmitting on more than one redundant bus simultaneously (a message must travel on Bus A or Bus B, not both).",
            "Allowing more than one Bus Controller active per bus at any time.",
            "RT transmitting on the bus without being explicitly addressed by the BC.",
            "Bus Monitor (BM) transmitting on the bus (BM is permanently passive).",
            "Using RT address 31 as a unicast address (it is reserved for broadcast).",
            "Allowing a Word Count > 32 (5-bit field, maximum binary value 11111 = 31; 00000 means 32).",
            "Generating a Manchester encoding without a mid-bit transition.",
            "Mixing Command/Status sync polarity (HL) with Data sync polarity (LH).",
            "Direct-coupled stub length exceeding 1 ft (0.3 m) or causing main-bus waveform distortion.",
            "Transformer-coupled stub length exceeding 20 ft (6.1 m) unless explicitly justified.",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "PARITY ERROR",          "trigger": "Even parity computed over the received 16 data bits + parity bit; receiver discards the word."},
            {"mode": "MANCHESTER ENCODING ERROR","trigger": "Mid-bit transition missing or wrong polarity inside a bit-cell; receiver discards the word."},
            {"mode": "SYNC POLARITY ERROR",   "trigger": "Sync field shape does not match the expected Command/Status or Data sync; receiver rejects the word."},
            {"mode": "WORD COUNT MISMATCH",   "trigger": "Number of Data Words received differs from the Word Count field of the Command Word; receiver flags Message Error."},
            {"mode": "ILLEGAL COMMAND",       "trigger": "RT receives a command for a subaddress or Mode Code that it does not implement; RT sets Message Error and does NOT transmit data."},
            {"mode": "NO-RESPONSE TIMEOUT",   "trigger": "BC observes no RT Status Word within 14 µs of the last command word; BC retries on the redundant bus or marks the RT failed."},
            {"mode": "BC TIMING VIOLATION",   "trigger": "BC issues a new Command Word with less than 4 µs inter-message gap; bus is non-compliant."},
        ])
        f.setdefault("performance_of_error_detection", [
            "All single-bit data errors per word are detected by odd parity.",
            "All bit-cell encoding errors are detected by Manchester mid-bit-transition check.",
            "All sync misframing is detected by sync-polarity discrimination.",
            "All truncated / extended messages are detected by Word Count cross-check.",
            "All response-timing faults are detected by the 4-12 µs window + 14 µs no-response timeout.",
            "Dual-redundant bus provides single-fault tolerance against media damage / single-bus failure.",
        ])
        f.setdefault("recovery_time_bound",
            "On a no-response event, BC retries the same message on the redundant bus within typically < 100 µs (limited by BC schedule slack), giving < 200 µs total worst-case before message success or declared failure.")
        d["fields"] = f
        _write(p, d)

    # L17
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels"] = [
            {
                "name": "Bus A (primary)",
                "direction": "bidirectional differential twinax (half-duplex)",
                "purpose": "Primary 78 Ω twinax bus carrying Manchester II 1.0 Mbit/s; one BC + up to 31 RTs share it.",
                "physical_realization": "Twinax cable (Zo 70-85 Ω, 78 Ω nominal); transformer-coupled or direct-coupled stubs; ≥ 75 % shielded bus couplers; terminated at both ends in Zo.",
            },
            {
                "name": "Bus B (redundant)",
                "direction": "bidirectional differential twinax (half-duplex)",
                "purpose": "Standby 78 Ω twinax bus identical to Bus A; used for retry / failover; messages travel on only one of A/B at a time.",
                "physical_realization": "Same construction as Bus A; independent run + terminators.",
            },
        ]
        f["logical_signal_states"] = [
            {"name": "Manchester logical 1",  "value": "high-then-low half-bit",  "rule": "First half-bit (0.5 µs) HIGH, second half-bit (0.5 µs) LOW. Mid-bit falling edge."},
            {"name": "Manchester logical 0",  "value": "low-then-high half-bit",  "rule": "First half-bit (0.5 µs) LOW, second half-bit (0.5 µs) HIGH. Mid-bit rising edge."},
            {"name": "Command/Status sync",   "value": "non-Manchester HL",       "rule": "HIGH 1.5 µs then LOW 1.5 µs over a 3 µs sync field; unambiguously marks a Command or Status Word."},
            {"name": "Data sync",             "value": "non-Manchester LH",       "rule": "LOW 1.5 µs then HIGH 1.5 µs over a 3 µs sync field; unambiguously marks a Data Word."},
            {"name": "Bus idle",              "value": "differential ≈ 0 V",      "rule": "No Manchester transitions; inter-message gap ≥ 4 µs."},
        ]
        f["frame_fields_as_signal_segments"] = [
            {"name": "WORD_SYNC",                "type": "delimiter / sync",        "form": "3 µs non-Manchester; HL = Command/Status; LH = Data"},
            {"name": "RT_ADDRESS",               "type": "addressing",              "form": "5 bits MSB-first; 0-30 + 31 broadcast"},
            {"name": "T_R_BIT",                  "type": "direction",               "form": "1 bit: 1 = RT transmits; 0 = RT receives"},
            {"name": "SUBADDRESS_OR_MODE",       "type": "subaddress / mode selector","form": "5 bits; 0 or 31 routes to Mode Code"},
            {"name": "WORD_COUNT_OR_MODE_CODE",  "type": "count / mode code",       "form": "5 bits; 1-31 + 0=32 OR 5-bit Mode Code"},
            {"name": "DATA_PAYLOAD",             "type": "payload",                 "form": "16 bits MSB-first per Data Word"},
            {"name": "PARITY",                   "type": "integrity",               "form": "1 bit odd parity over 16 data bits"},
            {"name": "MESSAGE_ERROR_BIT",        "type": "status flag",             "form": "1 bit in Status Word; RT signals command-side error"},
            {"name": "SERVICE_REQUEST_BIT",      "type": "status flag",             "form": "1 bit in Status Word; RT requests acyclic transfer"},
            {"name": "BUSY_BIT",                 "type": "status flag",             "form": "1 bit in Status Word; RT cannot service this cycle"},
            {"name": "SUBSYSTEM_FLAG_BIT",       "type": "status flag",             "form": "1 bit in Status Word; subsystem-level fault"},
            {"name": "TERMINAL_FLAG_BIT",        "type": "status flag",             "form": "1 bit in Status Word; RT-internal fault"},
            {"name": "DYNAMIC_BUS_ACCEPTANCE",   "type": "status flag",             "form": "1 bit in Status Word; ACK to Dynamic Bus Control mode code"},
            {"name": "BROADCAST_COMMAND_RECEIVED","type": "status flag",            "form": "1 bit in Status Word; RT acknowledges last command was broadcast"},
            {"name": "INSTRUMENTATION_BIT",      "type": "status flag",             "form": "1 bit in Status Word; reserved / instrumentation use"},
            {"name": "INTER_MESSAGE_GAP",        "type": "interframe space",        "form": "≥ 4 µs of bus quiet between messages"},
            {"name": "RT_RESPONSE_GAP",          "type": "interframe space",        "form": "4-12 µs from end of last command word to start of RT Status Word"},
        ]
        f["channel_counts"] = {
            "logical_channels":           2,
            "physical_buses":             2,
            "logical_bit_values":         2,
            "sync_polarities":            2,
            "word_types":                 3,
            "message_formats_bc_to_rt":   6,
            "message_formats_broadcast":  4,
            "mode_codes_total":           15,
            "rt_addresses_valid":         31,
            "data_words_per_message_max": 32,
            "bits_per_word":              20,
        }
        # Force-overwrite dependency_graph (earlier steps may have written
        # AXI-leaning content; 1553 shape is BC-driven command/response).
        f["dependency_graph"] = {
            "command_response":  "Every BC Command Word must be followed by exactly one RT Status Word (per addressed RT) within 4-12 µs, except broadcast (no Status).",
            "data_word_ordering":"For BC→RT: BC's Data Words follow the Command Word immediately. For RT→BC: RT's Data Words follow its Status Word immediately. For RT→RT: source RT's Data Words follow its Status; destination RT's Status follows.",
            "redundant_bus_select":"Per-message: BC chooses Bus A or Bus B before transmitting; the other bus is electrically idle for that message.",
        }
        f["handshake_pairs"] = [
            {"name": "COMMAND_TO_STATUS",        "from": "BC", "to": "RT", "rule": "RT responds with Status Word 4-12 µs after the last command word; broadcast (RT addr 31) suppresses Status."},
            {"name": "SERVICE_REQUEST_TO_VECTOR","from": "RT", "to": "BC", "rule": "RT sets Service Request bit in Status Word; BC issues Transmit Vector Word (Mode Code 10000) to acquire the request data."},
            {"name": "DYNAMIC_BUS_CONTROL",      "from": "BC", "to": "backup BC", "rule": "Mode Code 00000; backup RT/BC acknowledges with Dynamic Bus Acceptance bit (Status Word bit 15)."},
            {"name": "BIT_WORD_PROBE",           "from": "BC", "to": "RT", "rule": "BC issues Transmit BIT Word (Mode Code 10011); RT returns Status + 1 Data Word."},
        ]
        f.setdefault("ordering_rules", {
            "within_a_word":   "MSB-first across the 16 data bits.",
            "within_a_message":"Command Word always first (BC source); Status Word follows after response gap; Data Words flow either before (BC→RT) or after (RT→BC) the Status Word.",
            "global_ordering": "BC's schedule is deterministic (cyclic-executive frames at typically 50 / 25 / 12.5 Hz minor rates); acyclic transfers slot into reserved slots after Service Request.",
        })
        d["fields"] = f
        _write(p, d)

    # L18
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = (
            "Multidrop, dual-redundant differential twinax bus with a "
            "single Bus Controller per cycle and up to 31 Remote "
            "Terminals + optional Bus Monitors. Command/response "
            "time-division multiplex with no bus arbitration.")
        f["supported_topologies"] = [
            {"name": "Single linear twinax bus",        "description": "Older 1553 installations; all nodes tap onto one 78 Ω cable terminated at both ends; transformer-coupled stubs preferred."},
            {"name": "Dual-redundant twinax bus pair",  "description": "Standard 1553B configuration: independent Bus A + Bus B; BC selects which bus carries each message; standby bus is the immediate retry path."},
            {"name": "Tri-redundant or higher",          "description": "Implementation-defined extension; common in spacecraft for additional fault tolerance."},
            {"name": "Optical-fibre (MIL-STD-1773)",    "description": "Same protocol on optical PHY; chosen for EMI / EMP / lightning hardening, especially in composite-skin aircraft and spacecraft."},
            {"name": "STANAG 3910 / EFABus coexistence","description": "20 Mbit/s high-rate companion piggybacked on the same 1553B copper; used on Eurofighter Typhoon for high-bandwidth payloads."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "BUS_CONTROLLER",        "description": "Single active master per bus per cycle. Sources every Command Word; schedules every transfer; receives every Status Word."},
            {"role": "BACKUP_BUS_CONTROLLER", "description": "Standby BC. Inherits master role via Dynamic Bus Control mode code or discrete failover line."},
            {"role": "REMOTE_TERMINAL",       "description": "Slave / responder. Decodes each Command Word; if addressed and able, responds within 4-12 µs."},
            {"role": "BUS_MONITOR",           "description": "Passive listener / data recorder. Cannot transmit."},
        ]
        f["interconnect_role"] = (
            "There is no protocol-layer routing or bridging — the bus is "
            "a flat shared medium. The Bus Controller's schedule "
            "deterministically time-multiplexes RT-to-RT, RT-to-BC, and "
            "BC-to-RT transfers on the single shared bus. Dual-redundant "
            "Bus A + Bus B selection happens per-message under BC "
            "control. Cross-bus bridging (between two independent 1553 "
            "buses) is implemented by an RT acting as a bridge — that RT "
            "is a slave on each bus and the BCs on each bus schedule the "
            "bridge.")
        f["ordering_guarantees"] = {
            "command_response":      "Every Command Word is followed by exactly one RT Status Word (except in broadcast), in a deterministic 4-12 µs window; the BC sees results in the order it scheduled them.",
            "no_in_flight_overlap":  "Bus is half-duplex; only one transmitter at a time on the active bus. The BC schedule guarantees no overlapping messages on the same bus.",
            "redundancy":            "Bus A and Bus B are independent; a message is launched on only one bus; the standby bus is the immediate-retry path.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Not applicable — 1553B is wire-level. Per-RT data buffers are mapped to subaddress descriptors (1-30); subaddress 0 / 31 are mode-code selectors. The buffer layout (TX buffer at SA=x, RX buffer at SA=y, dual-buffered TX/RX, etc.) lives in each RT controller's data sheet, not in 1553B itself.")
        f.setdefault("slave_classification", {
            "addressable_target":   "RT address 0-30 (31 = broadcast); plus Subaddress 1-30 selects the data buffer; Subaddress 0/31 selects Mode Code.",
            "data_producer":        "Any RT may transmit Data Words from a TX subaddress (Cmd with T/R = 1).",
            "data_consumer":        "Any RT may receive Data Words into a RX subaddress (Cmd with T/R = 0); broadcast RTs accept without acknowledging.",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Bus protocol — Section 'Bus protocol' (Manchester encoding + word formats + transfer formats).",
            "Bus hardware characteristics — Section 'Bus hardware characteristics' (cabling, stubs, couplers, terminators).",
            "Conceptual description — Section 'Conceptual description' (BC / BBC / BM / RT roles + dual-redundant bus pair).",
        ])
        f.setdefault("wake_up_topology", {
            "wake_up_trigger": "Not applicable — 1553B has no protocol-level sleep / wake state machine. Subsystems are assumed always-on or managed by SoC-level power schemes outside 1553.",
            "wake_up_message": "Not defined. Transmitter Shutdown mode code (00100) approximates a low-power state for the redundant transmitter; Override (00101) re-enables it.",
            "post_wake_sync":  "On Reset Remote Terminal (Mode Code 01000), RT re-initializes its descriptor table + Status Word + BIT and listens for the next Command Word.",
        })
        d["fields"] = f
        _write(p, d)

    # L19 PDK
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("constraints_present", False)
        f["notes"] = (
            "MIL-STD-1553B is a wire-level protocol spec; there are no "
            "PDK / SDC / floorplan / power-grid constraints at the "
            "protocol layer. Per-RT controller IP (DDC BU-65170 / "
            "BU-61580, Holt HI-6130 / HI-1573, UTMC UT69151, FPGA cores) "
            "has its own integration constraints — typical: 16 / 20 MHz "
            "protocol clock domain ± 0.01 % short-term stability, "
            "RT-address strap pins parity-protected, isolation-"
            "transformer pad ring, common-mode rejection at the "
            "differential PHY, 18-27 Vp-p transmitter driver, ≥ 75 % "
            "shielded couplers. Those constraints live in the silicon "
            "vendor's data sheet and the avionics-box mechanical "
            "specification, not in MIL-STD-1553B.")
        d["fields"] = f
        _write(p, d)

    # L20 DFT
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("dft_present", False)
        f["notes"] = (
            "MIL-STD-1553B does not specify silicon-level DFT / scan / "
            "BIST. Protocol-level self-checking (parity + Manchester + "
            "sync polarity + word-count + 4-12 µs response window + "
            "Status Word condition bits + mandatory BIT word mode code) "
            "plus dual-bus retry plus passive Bus Monitor + SAE AS4111 "
            "(Validation) / AS4112 (Production) industry test plans "
            "provide system-level diagnostics. SoC-integrated 1553 "
            "controllers from Data Device Corporation, Holt, UTMC, etc. "
            "add standard scan / JTAG insertion at the integrator level.")
        d["fields"] = f
        _write(p, d)

    # L21 power
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("power_intent_present", False)
        f["low_power_modes_summary"] = {
            "sleep_mode":         "Not defined at the protocol layer. 1553 nodes in avionics are typically always-on for the entire mission cycle.",
            "transmitter_shutdown_mode_code":          "Mode Code 00100: BC commands an RT to shut down its redundant-bus transmitter (fault containment / approximate low-power state).",
            "override_transmitter_shutdown_mode_code": "Mode Code 00101: BC commands the RT to re-enable the previously-shut-down transmitter.",
            "selected_transmitter_shutdown_mode_code": "Mode Code 10100 (with data): shut down a specifically-selected transmitter (data word identifies which).",
            "reset_remote_terminal_mode_code":         "Mode Code 01000: BC commands an RT to reset; RT may use this as a power-cycle approximation.",
        }
        f["notes"] = (
            "Power-domain partitioning is deferred to SoC + transceiver "
            "IP. The only protocol-defined power features in 1553B are "
            "the Transmitter Shutdown / Override + Selected Transmitter "
            "Shutdown / Override mode codes (used for fault containment, "
            "not strictly power management) plus Reset Remote Terminal.")
        d["fields"] = f
        _write(p, d)

    # L22 verification plan
    p = gd / "L22_VERIFICATION_PLAN.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        # Force overwrite (not setdefault): SPI-class _apply_universal runs
        # FIRST and sets verification_plan_present="implicit" + a SPI-flavoured
        # notes string. 1553 has explicit industry validation plans (AS4111 /
        # AS4112) maintained by SAE AS-1A, so we override with "explicit" plus
        # 1553-specific notes.
        f["verification_plan_present"] = "explicit"
        f.setdefault("industry_validation_plan",
            "SAE AS4111 — RT Validation Test Plan (formerly MIL-HDBK-1553A Section 100, originally MIL-HDBK-1553 Appendix A). Comprehensive design-verification suite for Remote Terminals designed to AS 15531 / MIL-STD-1553B Notice 2.")
        f.setdefault("industry_production_plan",
            "SAE AS4112 — RT Production Test Plan. Simplified subset of AS4111 intended for in-line production testing of Remote Terminals.")
        if _empty(f.get("verification_categories_derived_from_spec")):
            f["verification_categories_derived_from_spec"] = [
                "Word framing — 3 µs sync + 16 data bits + odd parity = 20 µs per word; verify all 3 word types.",
                "Sync polarity discrimination — Command/Status (HL) vs Data (LH); inject inverted sync; expect rejection.",
                "Manchester II encoding — logical 1 = high-then-low; logical 0 = low-then-high; inject missing mid-bit transition; expect encoding error.",
                "Odd parity verification — inject even parity; expect MESSAGE ERROR.",
                "Bit rate 1.0 Mbit/s with ±0.1 % long-term / ±0.01 % short-term tolerance — sweep at corner clock rates.",
                "Each BC↔RT message format (6) — verify field sequence and response.",
                "Each broadcast format (4) — verify NO Status Word from broadcast targets.",
                "All 10 standard Mode Codes (00000..01000 + 10000..10011 + 10100..10101) — verify per-spec response.",
                "Mandatory mode codes: TRANSMIT_STATUS_WORD, TRANSMIT_LAST_COMMAND, TRANSMIT_BIT_WORD — mandatory implementation.",
                "RT address strap — all 31 valid addresses (0-30); verify address 31 not used as unicast.",
                "Subaddress 0/31 routes to Mode Code selector — verify against subaddress 1-30 (data path).",
                "Word Count field — all values 1-31 + 0=32 special case.",
                "RT response time 4-12 µs from end of last command word — verify timing window.",
                "BC no-response timeout 14 µs — verify retry on redundant bus.",
                "Inter-message gap ≥ 4 µs — verify BC compliance.",
                "Service Request → Transmit Vector Word — verify acyclic acquisition flow.",
                "Dynamic Bus Control (Mode Code 00000) → Dynamic Bus Acceptance (bit 15) — verify handoff.",
                "Initiate Self Test (00011) + BIT word return on (10011) — verify health-reporting chain.",
                "Transmitter Shutdown (00100) + Override (00101) — verify fault-containment hooks.",
                "Reset Remote Terminal (01000) — verify clean reinitialization.",
                "Dual-redundant bus retry — inject Bus A fault; verify immediate Bus B retry.",
                "Status Word condition bits: Message Error, Busy, Subsystem Flag, Terminal Flag, Service Request, Dynamic Bus Acceptance, Broadcast Command Received, Instrumentation — verify each independently.",
                "RT supersede — issue new Command/Status sync mid-RT-response; verify RT aborts and decodes new command.",
                "Cable / stub corner cases — max transformer-coupled stub (20 ft), max direct-coupled stub (1 ft), 100 ft main bus.",
                "Electrical envelope — transmitter 18-27 Vp-p, characteristic impedance 70-85 Ω, isolation transformer 1:1.41 ± 3 %, isolation resistor 0.75×Zo ± 2 % (transformer-coupled) or 55 Ω ± 2 % (direct-coupled).",
                "Waveform quality per MIL-HDBK-1553A (rise/fall time, overshoot, zero-crossing distortion).",
            ]
        # Force overwrite (not setdefault): SPI-class _apply_universal sets a
        # SPI-flavoured "Spec does not include a formal verification plan ..."
        # notes string FIRST; we override with 1553-specific notes pointing
        # at AS4111 / AS4112 / SAE AS-1A maintenance.
        f["notes"] = (
            "MIL-STD-1553B is paired with the SAE AS4111 RT Validation "
            "Test Plan and AS4112 RT Production Test Plan, maintained by "
            "the SAE AS-1A Avionic Networks Subcommittee. The above "
            "categories are derived from the standard's mandatory "
            "behaviors + Notice 2 + AS 15531.")
        d["fields"] = f
        _write(p, d)

    # L23 security
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f["notes"] = (
            "MIL-STD-1553B (1978) is a wire-level protocol spec; it has "
            "no confidentiality / integrity / authentication features at "
            "the protocol layer. The bus is broadcast — every node sees "
            "every word on the active bus, and the passive Bus Monitor "
            "can record every transaction. Built-in integrity primitives "
            "are odd parity (single-bit data error) + Manchester encoding "
            "check + sync polarity check + word-count cross-check — "
            "these protect against accidental corruption, NOT against "
            "tampering. Modern bus-security overlays (e.g. 1553 anomaly-"
            "detection IDS, periodic-pattern fingerprinting, "
            "redundant-bus voting, message-authentication-code MAC "
            "overlays) are layered on top by integrators (Lockheed "
            "Martin, BAE Systems, Curtiss-Wright, etc.), not part of "
            "1553B itself. Military-classified deployments rely on "
            "physical-security (LRU lockdown, twinax inside metal-"
            "shielded boxes) plus mission-system-level encryption above "
            "1553.")
        d["fields"] = f
        _write(p, d)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def is_milstd1553(blob: str) -> bool:
    """Content-only `milstd1553` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text).

    FOREIGN-PRIMARY DEFER (mirrors `is_mipi`'s doctrine): the structural
    MIL-STD-1553 signature below (MIL-STD-1553 + Bus Controller + Remote
    Terminal) is necessary but NOT sufficient — a SpaceWire spec cites
    MIL-STD-1553 as a heritage/comparison data bus (its generated L-docs
    carry incidental "MIL-STD-1553" / "Bus Controller" / "Remote Terminal"
    tokens) and would otherwise trip the first branch and let the generic
    1553 synth inject command/status/data-word content into a SpaceWire spec.

    Guard (general, content-only, no chip/SKU/benchmark literal): defer when
    the blob's DOMINANT subject is SpaceWire — detected by SpaceWire's own
    distinctive ESA/ECSS-E-ST-50-12C structural signature, which is ABSENT
    from every genuine MIL-STD-1553 spec:
      - Data-Strobe (DS) encoding over LVDS (the clock = Data XOR Strobe
        two-signal scheme; 1553 is Manchester II over twinax, never DS/LVDS);
      - the SpaceWire control-character set: FCT (Flow Control Token) plus
        EOP/EEP (End / Error-End of Packet) — 1553 has no token/packet chars.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER: the blob's true subject is SpaceWire. ---
    _sw_ds = (
        "data-strobe" in low or "data strobe" in low or "ds encoding" in low
        or ("data" in low and "strobe" in low
            and ("xor" in low or "exclusive-or" in low
                 or "exclusive or" in low)))
    _sw_lvds = (
        "lvds" in low or "low-voltage differential" in low
        or "low voltage differential" in low)
    _sw_fct = "fct" in low or "flow control token" in low
    _sw_eop_eep = (
        "eop" in low or "end of packet" in low
        or "eep" in low or "error end of packet" in low)
    spacewire_primary = _sw_ds and _sw_lvds and _sw_fct and _sw_eop_eep
    if spacewire_primary:
        return False

    return bool(
        ("MIL-STD-1553" in blob
         and "Bus Controller" in blob
         and "Remote Terminal" in blob)
        or ("1553" in blob and "Manchester" in blob
            and "Bus Controller" in blob)
        or ("MIL-STD-1553" in blob
            and "Command Word" in blob
            and "Status Word" in blob))
