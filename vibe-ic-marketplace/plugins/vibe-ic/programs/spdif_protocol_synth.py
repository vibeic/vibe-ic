"""S/PDIF-class protocol synth helper.

v0.1.84 — ic_class-gated overlay for `serial_peripheral_protocol`
specs that exhibit the S/PDIF / IEC 60958 type II structural
signature (BMC + subframe + X/Y/Z preambles OR IEC 60958 + audio OR
S/PDIF + Toslink). Applies Sony/Philips Digital Interface spec-canonical
content to L1-L18 + L21.

Doctrine: structural-keyword detection IS general within an ic_class
(mirrors AMBA-AXI / SPI / I2C / UART / CAN / USB / I2S synth approach).
Any S/PDIF variant (consumer IEC 60958 type II coaxial RCA / BNC /
Toslink optical, IEC 61937 compressed-audio encapsulation, SCMS
copy-protection variants, IEC 958 pre-1998 naming) exhibits the same
signature: Biphase Mark Code line encoding + 32-bit subframe with
4-bit X / Y / Z preamble + 20-bit (24-bit with Aux) audio + V / U / C
/ P bits + 192-frame block + 192-bit channel-status word.

Public entry: `apply_spdif_synth(generated_docs_dir, is_spdif, spdif_ic_name)`.
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


def apply_spdif_synth(generated_docs_dir: Path, is_spdif: bool,
                      spdif_ic_name: Optional[str]) -> None:
    """Apply S/PDIF-specific synth when the structural signature matched.

    Detection (caller's responsibility) is one of:
      (a) "SPDIF" + "biphase" + ("subframe" OR "preamble") OR
      (b) "IEC 60958" + "audio" OR
      (c) "S/PDIF" + "Toslink"
    matched in the source design documents.
    """
    if not is_spdif:
        return
    gd = generated_docs_dir

    # Force ic_name across the 14 main L docs (mirroring the I2S pattern;
    # L14-L23 use a different schema with "fields" so they do not get a
    # top-level ic_name override).
    if spdif_ic_name is not None:
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
                d["ic_name"] = spdif_ic_name
                _write(q, d)

    # L1 — Datasheet
    p = gd / "L1_DATASHEET.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("document_title", "S/PDIF — Sony/Philips Digital Interface (IEC 60958 type II consumer digital audio interface)")
        d.setdefault("document_number", "IEC 60958 type II (formerly IEC 958, renamed in 1998)")
        d.setdefault("version", "Wikipedia compilation reflecting IEC 60958-1/-3 + IEC 61937 industry practice")
        d.setdefault("revised_date", "Reflects S/PDIF industry usage as captured by Wikipedia spec excerpt provided as input")
        d.setdefault("original_release_date", "Developed alongside AES3 (1985 / IEC 60958 / IEC 958 type II); originally designed by Sony and Philips")
        d.setdefault("manufacturer", "Sony Corporation + Philips (co-designers); standardized by IEC as IEC 60958 type II")
        d.setdefault("copyright", "Industry-standard interface; Wikipedia spec excerpt licensed under CC-BY-SA; original IEC 60958 is the IEC normative source")
        d.setdefault("abstract",
            "S/PDIF (Sony/Philips Digital Interface) is the consumer variant of the IEC 60958 digital audio interface. It carries two channels of uncompressed PCM audio (16 / 20 / 24-bit) or compressed 5.1 surround sound (per IEC 61937 — Dolby AC-3 / DTS / MP3 etc.) over a single coaxial RCA / BNC cable (75 Ω, 0.5–0.6 Vpp) or a Toslink optical fibre link. It shares the bi-phase mark code (BMC) frame structure with AES3 (professional/balanced), differing only in connector, signal level, max distance, and channel-status word interpretation (in particular: Bit 0 = 0 for Consumer, copy-protection / SCMS bits, sample-frequency / clock-accuracy / word-length encoding).")
        d.setdefault("keywords", [
            "S/PDIF", "Sony/Philips Digital Interface", "IEC 60958",
            "IEC 60958 type II", "IEC 958", "AES3", "biphase mark code",
            "BMC", "Manchester", "Toslink", "RCA", "BNC", "75 ohm",
            "consumer digital audio", "PCM", "IEC 61937", "Dolby AC-3",
            "DTS", "SCMS", "channel status", "subframe", "preamble",
            "X", "Y", "Z", "V", "U", "C", "P",
        ])
        d.setdefault("external_pins", [
            "Single-ended coaxial RCA / BNC pin (75 Ω, 0.5–0.6 Vpp peak-to-peak) for electrical S/PDIF, OR",
            "Toslink fibre-optic transmitter/receiver pair (JIS F05 / EIAJ optical) for optical S/PDIF",
        ])
        d.setdefault("external_pin_count", 1)
        d.setdefault("key_features", [
            "Consumer variant of the IEC 60958 digital audio interface; designed by Sony and Philips.",
            "Standardized as IEC 60958 type II (formerly IEC 958, renamed in 1998).",
            "Carries two channels of uncompressed PCM audio (16 / 20 / 24-bit) OR compressed multi-channel audio (IEC 61937: Dolby AC-3 / DTS / MP3 / AAC / ATRAC / WMA Pro / Dolby TrueHD / E-AC-3).",
            "Coaxial electrical S/PDIF: 75 Ω cable, 0.5–0.6 V peak-to-peak output, 0.2 V minimum input level, RCA or BNC connector (RCA typically colour-coded orange to distinguish from composite video).",
            "Optical S/PDIF: Toslink (JIS F05 / EIAJ) fibre-optic connection; identical content to coaxial, provides electrical isolation against ground loops.",
            "Maximum cable distance: ~10 m (coaxial), ~10 m (Toslink); compared with AES3 unbalanced 100 m / balanced 1000 m.",
            "Bi-phase Mark Code (BMC) line coding — Manchester-style — embeds clock + data so the receiver can recover the bit clock from the signal itself; one or two transitions per bit period.",
            "Subframe = 32 bits: 4-bit Preamble + 4-bit Aux + 20-bit Audio sample + V (Validity) + U (User) + C (Channel status) + P (Parity).",
            "Frame = 2 subframes (channel A + channel B); Block = 192 frames per channel.",
            "Three preamble types: X (= channel A subframe start), Y (= channel B subframe start), Z (= block-start variant of X). All three deliberately violate BMC encoding rules so they are unambiguously detectable.",
            "192-bit channel-status word accumulated 1 bit/subframe per channel, used to convey sample rate / word length / copy-protection / category / source-number / EAN-13 / ISRC info.",
            "Audio bit depth: 20-bit standard with 4-bit aux yielding optional 24-bit (consumer); AES3 alternative carries 24-bit directly.",
            "Supports standard audio sample rates 32 / 44.1 / 48 / 88.2 / 96 / 176.4 / 192 kHz; bit clock = 64 × Fs because each frame = 64 BMC-cell periods.",
            "Embeds SCMS (Serial Copy Management System) flags in the consumer channel-status word for copy protection (consumer only — professional AES3 does not).",
            "IEC 61937 reuses the IEC 60958 frame container to tunnel compressed bitstreams (AC-3, DTS, MP3, AAC, ATRAC, WMA Pro, etc.) using sync-word + bitstream-number framing inside the audio-sample field.",
            "Receiver does NOT control the data rate — it must synchronize via clock recovery from the BMC stream; receivers commonly suffer jitter that can degrade analog reconstruction in the downstream DAC.",
        ])
        d.setdefault("topology_summary",
            "Point-to-point unidirectional digital audio link from a single source (transmitter) to a single sink (receiver) over a 75 Ω coaxial cable or Toslink fibre. The BMC line encoding embeds the bit clock; the receiver recovers the word clock from the bit clock and from the X/Y/Z preamble pattern. No back-channel and no flow control — the receiver must accept the source's nominal rate.")
        d.setdefault("revision_history", [
            {"version": "IEC 958 (pre-1998)",        "date": "1985 era", "description": "Initial joint IEC standardization of the digital audio interface, with AES3 (professional, type I) and S/PDIF (consumer, type II) sharing the frame structure but differing in connector and channel-status interpretation."},
            {"version": "IEC 60958 (1998 renaming)", "date": "1998",     "description": "IEC 958 renumbered to IEC 60958; type I = AES3 (professional/balanced/XLR/110 Ω) and type II = S/PDIF (consumer/unbalanced/RCA-or-Toslink/75 Ω)."},
            {"version": "IEC 61937",                 "date": "Mid-1990s onwards", "description": "Companion standard defining how to encapsulate compressed multi-channel audio bitstreams (Dolby AC-3, DTS, etc.) inside the IEC 60958 frame for transport over S/PDIF."},
        ])
        d.setdefault("use_cases", [
            "Connecting a CD player to an amplifying receiver (two channels of uncompressed PCM audio).",
            "Connecting a Blu-ray / DVD player or PC to a home-theatre A/V receiver carrying compressed 5.1 surround (Dolby Digital / DTS / Dolby TrueHD) per IEC 61937.",
            "Sound card digital output (PC → external DAC or receiver).",
            "Set-top box / Digital TV → AVR audio link.",
            "Digital interconnect between consumer audio components in home theatre / high-fidelity systems where electrical isolation (via Toslink) is needed to break ground loops.",
        ])
        d.setdefault("overview",
            "S/PDIF (Sony/Philips Digital Interface) is a type of digital audio interface used in consumer audio equipment to output audio over relatively short distances. The signal is transmitted over either a coaxial cable using RCA or BNC connectors, or a fibre-optic cable using Toslink connectors. S/PDIF interconnects components in home theatres and other digital high-fidelity systems. S/PDIF is based on the AES3 interconnect standard; both are standardized in IEC 60958 — AES3 as type I (professional) and S/PDIF as type II (consumer). S/PDIF is a data link layer protocol as well as a set of physical layer specifications for carrying digital audio signals over either optical or electrical cable. The name stands for Sony/Philips Digital Interconnect Format, but is also known as Sony/Philips Digital Interface. Sony and Philips were the primary designers of S/PDIF. S/PDIF is standardized in IEC 60958 as IEC 60958 type II (IEC 958 before 1998).")
        _write(p, d)

    # L2 — FRS
    p = gd / "L2_FRS.json"
    if p.is_file():
        d = _read(p)
        # Pre-existing None / "" / [] for protocol_overview → reset to dict
        if d.get("protocol_overview") in (None, "", []):
            d["protocol_overview"] = {}
        po = d["protocol_overview"]
        if isinstance(po, dict):
            po.setdefault("type", "Single-wire (coax or optical) unidirectional self-clocked digital audio link carrying two channels of audio (PCM or IEC 61937-encapsulated compressed) per IEC 60958 type II.")
            po.setdefault("duplex", "simplex — point-to-point from a single transmitter to a single receiver; no back-channel")
            po.setdefault("synchronous", True)
            po.setdefault("self_clocked", True)
            po.setdefault("line_encoding", "Bi-phase Mark Code (BMC) — Manchester variant. Two BMC cells per data bit, transition at every bit boundary, transition mid-bit = 1, no mid-bit transition = 0.")
            po.setdefault("wire_names", ["S/PDIF signal (single-ended on coax OR single optical lane via Toslink)"])
            po.setdefault("wire_count", 1)
            po.setdefault("channels_carried", "Two — channel A + channel B (typically left + right of a stereo pair, or compressed bitstream carrier in IEC 61937 mode)")
            po.setdefault("data_format", "20-bit audio sample (LSB-first within the audio field) plus 4-bit Aux field that may extend it to a 24-bit sample; PCM or IEC-61937-compressed payload; Validity (V), User (U), Channel status (C), Parity (P) flags per subframe")
            po.setdefault("frame_structure", "Subframe (32 BMC-bit-times) = Preamble (4 BMC cells / 8 transitions, deliberately BMC-rule-violating) + Aux (4 bits) + Audio sample (20 bits) + V + U + C + P. Frame = 2 subframes. Block = 192 frames.")
            po.setdefault("transmitter_role", "Generates BMC-encoded stream, injects X / Y / Z preambles, accumulates channel-status bits across the 192-frame block, computes per-subframe even parity over bits 4-30.")
            po.setdefault("receiver_role", "Recovers clock from BMC transitions, detects X / Y / Z preambles to align subframe/frame/block boundaries, reassembles the 192-bit channel-status word per channel, applies parity check, and reconstructs left/right audio samples.")
        fr = [
            {"id": "FR-LINE-CODING-01",     "text": "S/PDIF shall use Bi-phase Mark Code (BMC) line encoding so that the bit clock can be recovered from the received signal. The encoding has either one or two transitions for every bit, allowing the original word clock to be extracted from the signal itself."},
            {"id": "FR-SUBFRAME-32-02",      "text": "Each S/PDIF subframe shall be 32 BMC-bit-times long: 4 bits of Preamble + 4 bits of Aux + 20 bits of Audio sample + 1 bit V (Validity) + 1 bit U (User) + 1 bit C (Channel status) + 1 bit P (Parity)."},
            {"id": "FR-FRAME-2SUB-03",       "text": "Each S/PDIF frame shall consist of exactly two subframes (channel A then channel B)."},
            {"id": "FR-BLOCK-192-04",         "text": "Each S/PDIF block shall consist of exactly 192 frames (= 384 subframes; = 192 bits of channel-status word per channel)."},
            {"id": "FR-PREAMBLE-XYZ-05",     "text": "Three preamble types shall be used: X = start of a channel-A subframe within a block (non-first frame); Y = start of a channel-B subframe; Z = start of a channel-A subframe at the beginning of a block. The preambles deliberately violate normal BMC encoding rules so a receiver can detect them unambiguously to align to subframe/frame/block boundaries."},
            {"id": "FR-AUDIO-FIELD-06",      "text": "The audio sample shall occupy 20 bits of the subframe. Optional 24-bit operation uses the 4-bit Aux field as the lowest 4 LSBs of the audio sample (yielding a 24-bit sample). For sample widths below 20 bits, the unused LSBs shall be set to zero and the channel-status 'word length' / 'sample length' field shall declare the actual width."},
            {"id": "FR-VALIDITY-V-07",        "text": "Bit V (Validity) shall be 0 when the sample is a valid PCM audio sample suitable for D/A conversion. V = 1 indicates the sample is not valid for D/A conversion (e.g. when carrying IEC 61937 compressed data or signalling a fault)."},
            {"id": "FR-USER-U-08",            "text": "Bit U (User) shall be available as one user-data bit per subframe. Aggregated across subframes it forms a user-data channel parallel to the audio (used e.g. for ISRC, ancillary text)."},
            {"id": "FR-CHANNEL-STATUS-C-09", "text": "Bit C (Channel status) shall be one bit per subframe. Aggregated across the 192 subframes of a block per channel, it forms the 192-bit channel-status word that conveys the consumer / professional flag, audio / data flag, copy-protection flag, sample rate, clock accuracy, word length, source category, source number, channel number, EAN-13 code, ISRC, and reserved bytes."},
            {"id": "FR-PARITY-P-10",          "text": "Bit P (Parity) shall be even parity over bits 4–30 of the same subframe (i.e. over the Aux + Audio sample + V + U + C fields). The receiver shall check parity and may report or recover from violations."},
            {"id": "FR-CONSUMER-PRO-11",     "text": "Bit 0 of the 192-bit channel-status word shall encode the interface type: 0 = Consumer (S/PDIF), 1 = Professional (AES3). When this bit changes meaning, the subsequent channel-status structure shall be interpreted per the appropriate type."},
            {"id": "FR-CS-AUDIO-DATA-12",    "text": "Byte 0, bit 1 of the channel-status word shall encode PCM/compressed: 0 = normal PCM audio, 1 = compressed (IEC 61937) data."},
            {"id": "FR-CS-COPY-13",          "text": "Byte 0, bit 2 of the channel-status word shall encode SCMS copy state: 0 = copy restricted, 1 = copy permitted (consumer S/PDIF only)."},
            {"id": "FR-CS-CHCOUNT-14",       "text": "Byte 0, bit 3 of the channel-status word shall encode channel count: 0 = 2 channels, 1 = 4 channels."},
            {"id": "FR-CS-EMPHASIS-15",      "text": "Byte 0, bit 5 of the channel-status word shall encode pre-emphasis: 0 = no pre-emphasis, 1 = 50/15 µs pre-emphasis."},
            {"id": "FR-CS-MODE-16",           "text": "Byte 0, bits 6–7 of the channel-status word shall encode the channel-status mode (defines subsequent bytes); values other than zero are reserved/undefined."},
            {"id": "FR-CS-CATEGORY-17",      "text": "Byte 1, bits 0–6 of the channel-status word shall encode the audio source category (general / CD-DA / DAT / DVD etc.) and bit 7 shall be the L-bit (original / copy distinction, defined only when copy-restrict bit = 0)."},
            {"id": "FR-CS-SOURCE-CHAN-18",   "text": "Byte 2 of the channel-status word shall encode bits 0–3 = source number, bits 4–7 = channel number."},
            {"id": "FR-CS-FS-CLKACC-19",     "text": "Byte 3 of the channel-status word shall encode bits 0–3 = sampling frequency (0000 = 44.1 kHz, 0100 = 48 kHz, 1100 = 32 kHz, etc.) and bits 4–5 = clock accuracy (10 = 50 ppm, 00 = 1000 ppm, 01 = variable pitch). Bits 6–7 are undefined / reserved."},
            {"id": "FR-CS-WORDLEN-20",        "text": "Byte 4 of the channel-status word shall encode bit 0 = word length (0 = 20-bit, 1 = 24-bit), bits 1–3 = sample length (0 = undefined, 1–4 = word length minus 1–4 bits, 5 = full word length), bits 4–7 = undefined."},
            {"id": "FR-CS-EAN-21",            "text": "Bytes 5–10 (bits 0–7) plus byte 11 (bits 0–3) of the channel-status word shall optionally carry an EAN-13 code (possibly binary-coded decimal). Byte 11 bits 4–7 are undefined / padding."},
            {"id": "FR-CS-ISRC-22",           "text": "Bytes 14 (bits 4–7) through byte 21 of the channel-status word shall optionally carry an ISRC (International Standard Recording Code: 2 alphabetic + 3 alphanumeric + 7 numeric characters, fitting into ~7.5 bytes). Bytes 12–13 and bytes 22–23 are undefined."},
            {"id": "FR-PHY-COAX-23",          "text": "Electrical (coaxial) S/PDIF shall use a 75 Ω characteristic-impedance cable terminated in 75 Ω, with an RCA or BNC connector, transmitting at 0.5–0.6 V peak-to-peak (typically 500 mV at the source) and accepting a minimum 0.2 V input level at the receiver."},
            {"id": "FR-PHY-TOSLINK-24",      "text": "Optical S/PDIF shall use a Toslink (JIS F05 / EIAJ optical) connector and fibre-optic cable, with content identical to the coaxial form. Optical isolation eliminates ground-loop currents."},
            {"id": "FR-PHY-DISTANCE-25",     "text": "Maximum cable distance shall be approximately 10 m for both coaxial and Toslink S/PDIF."},
            {"id": "FR-AUDIO-BITDEPTH-26",   "text": "S/PDIF audio bit depth shall be 20 bits standard, optionally 24 bits using the Aux field. Sources with fewer than 20 bits of accuracy shall zero-pad the superfluous LSBs and update byte-4 sample-length accordingly."},
            {"id": "FR-IEC61937-27",          "text": "When transporting compressed audio (Dolby AC-3, DTS, MP3, AAC, ATRAC, WMA Pro, Dolby TrueHD, Dolby E-AC-3 etc.), S/PDIF shall follow IEC 61937: channel-status bit 1 = 1 (data, not PCM); each data block shall be prefixed with an IEC 61937 preamble carrying two 16-bit sync words and indicating the bitstream type / validity / number / length; symbol rate shall be set so the carrier rate ≈ 64 × symbol rate; padding shall be inserted to match the IEC 60958 block timing."},
            {"id": "FR-CLOCK-RECOVERY-28",   "text": "The receiver shall recover the data rate from the BMC line transitions; it does not control the source rate. Implementations shall tolerate or filter clock jitter to limit downstream DAC degradation."},
        ]
        if _empty(d.get("functional_requirements")):
            d["functional_requirements"] = fr
        d.setdefault("configurations", [
            {"name": "Coaxial electrical S/PDIF (RCA orange)", "description": "75 Ω coaxial cable terminated in 75 Ω RCA connectors, 0.5–0.6 Vpp signal, ~10 m max, RCA typically coloured orange to differentiate from composite video."},
            {"name": "Coaxial electrical S/PDIF (BNC)",       "description": "Same 75 Ω 0.5–0.6 Vpp signal but with BNC connectors (preferred where a locking connector is required)."},
            {"name": "Toslink optical S/PDIF",                 "description": "Fibre-optic JIS F05 / EIAJ Toslink connector and short polymer fibre; identical content to coaxial; provides electrical isolation to break ground loops."},
            {"name": "PCM stereo mode",                        "description": "Channel-status byte 0 bit 1 = 0; subframes carry uncompressed PCM left/right samples (20-bit standard, 24-bit optional)."},
            {"name": "IEC 61937 compressed mode",              "description": "Channel-status byte 0 bit 1 = 1; subframes encapsulate Dolby AC-3 / DTS / etc. bitstreams framed by IEC 61937 preambles + sync words + padding."},
        ])
        d.setdefault("error_response_conditions", [
            "Parity violation in bit P of a subframe — receiver shall flag the subframe as suspect; behaviour depends on the implementation (mute / repeat-last-sample / report).",
            "Preamble (X / Y / Z) not detected in the expected position — receiver loses subframe/frame/block alignment; must re-synchronize on the next valid preamble.",
            "Validity bit V = 1 — receiver shall NOT pass the sample to a PCM D/A converter; instead treat as data (e.g. IEC 61937 carrier) or mute.",
            "Bit slip due to receiver/source clock mismatch — receiver should re-clock with an internal stable reference to minimize jitter at the DAC.",
            "Channel-status consistency mismatch between channel A and channel B — receivers should report inconsistency (S/PDIF channel-status word is identical between the two channels in consumer mode).",
        ])
        if _empty(d.get("compliance_requirements")):
            d["compliance_requirements"] = [
                "Use Bi-phase Mark Code with transitions at every bit boundary and a mid-bit transition encoding '1'.",
                "Emit X / Y / Z preambles that deliberately violate BMC rules (long-pulse patterns) so receivers can lock to them.",
                "Subframe length must be exactly 32 BMC bit-times; frame = 2 subframes; block = 192 frames.",
                "Parity bit P must be even over bits 4–30 of the same subframe.",
                "Channel-status byte 0 bit 0 = 0 to mark a frame as Consumer S/PDIF; setting it to 1 changes interpretation to Professional AES3.",
                "Coaxial S/PDIF transmitter output: 0.5–0.6 V peak-to-peak into 75 Ω.",
                "Coaxial S/PDIF receiver minimum input level: 0.2 V.",
                "Optical S/PDIF: Toslink (JIS F05 / EIAJ optical) connector and fibre.",
                "Sample frequencies must be declared via channel-status byte-3 bits 0–3 using the defined codes (44.1 / 48 / 32 kHz etc.).",
                "Word length must be declared via channel-status byte-4 bit 0 (20 vs 24 bit) and bits 1–3 (sample length code).",
            ]
        _write(p, d)

    # L3 — Cmd protocol
    p = gd / "L3_CMD_PROTOCOL.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("protocol_type",
            "Streaming framed digital-audio link with self-clocked Bi-phase Mark Code line encoding; no command / opcode protocol — control metadata is conveyed via the 192-bit channel-status word distributed 1 bit per subframe.")
        d.setdefault("opcodes", [])
        d.setdefault("channels", [
            {"name": "S/PDIF (coax or Toslink)", "direction": "transmitter output → receiver input", "description": "Single unidirectional BMC-encoded electrical or optical signal carrying the full IEC 60958 subframe / frame / block stream. No separate clock, chip-select, or back-channel."},
        ])
        d.setdefault("valid_ready_handshake_rules", [
            "There is no handshake / ACK / framing at the wire level beyond the X / Y / Z preambles — S/PDIF is a continuous self-clocked streaming bus.",
            "Synchronization is purely by BMC transitions and by preamble pattern detection. The X / Y / Z preambles deliberately VIOLATE BMC's 'transition at every bit boundary' rule, generating long pulses that are unique within the bitstream and so locate subframe/frame/block boundaries unambiguously.",
            "Validity bit V = 0 declares the audio sample suitable for D/A conversion; V = 1 forbids D/A use (e.g. for IEC 61937 compressed-data carriers).",
            "Parity bit P provides even-parity sanity over bits 4–30; mismatch flags the subframe as suspect.",
        ])
        d.setdefault("burst_based", True)
        d.setdefault("byte_oriented", False)
        d.setdefault("frame_format", {
            "subframe_layout": "Subframe = 32 BMC-bit-times: bits 0-3 = Preamble (X/Y/Z, BMC-violating long pulses); bits 4-7 = Aux (4 LSBs of optional 24-bit sample OR ancillary); bits 8-27 = 20-bit Audio sample (LSB-first within the audio field, MSB at bit 27); bit 28 = V (Validity, 0 = valid for D/A); bit 29 = U (User data, one bit per subframe); bit 30 = C (Channel status, one bit per subframe); bit 31 = P (Parity, even over bits 4-30).",
            "frame_layout":    "Frame = 2 subframes: subframe 1 = channel A (typically left, preamble X or Z), subframe 2 = channel B (typically right, preamble Y).",
            "block_layout":    "Block = 192 frames = 384 subframes; the first frame of a block has preamble Z on its channel-A subframe (instead of X) and Y on its channel-B subframe.",
            "channel_status_word": "Accumulating 1 bit/subframe per channel, the 192-bit channel-status word per channel is reconstructed once per block (block boundary marked by preamble Z).",
            "preamble_table": {
                "X": "Channel-A subframe start (frames 2–192 of the block).",
                "Y": "Channel-B subframe start (every frame).",
                "Z": "Channel-A subframe start of frame 1 (= block boundary).",
            },
        })
        d.setdefault("channel_status_word_layout_consumer", {
            "summary": "Consumer (S/PDIF) 192-bit channel-status word. Note: in consumer S/PDIF the channel-status word is identical for channel A and channel B; the entire 192-bit word is divided into 12 sub-words of 16 bits each, with the first 16 bits being a control code.",
            "bytes": [
                {"byte": 0, "bits": {"0": "Consumer (0) / Professional (1) — 1 changes the meaning of subsequent bytes to AES3 channel-status interpretation", "1": "Normal PCM (0) / Compressed data per IEC 61937 (1)", "2": "Copy restrict (0) / Copy permit (1) — SCMS", "3": "2 channels (0) / 4 channels (1)", "4": "Reserved (—)", "5": "No pre-emphasis (0) / Pre-emphasis 50/15 µs (1)", "6-7": "Mode — defines subsequent bytes; values other than zero are undefined"}},
                {"byte": 1, "bits": {"0-6": "Audio source category code (general, CD-DA, DAT, DVD, etc.)", "7": "L-bit — original / copy distinction; only meaningful when byte 0 bit 2 = 0 (copy-restricted)"}},
                {"byte": 2, "bits": {"0-3": "Source number", "4-7": "Channel number"}},
                {"byte": 3, "bits": {"0-3": "Sampling frequency (0000 = 44.1 kHz, 0100 = 48 kHz, 1100 = 32 kHz, ...)", "4-5": "Clock accuracy (10 = 50 ppm, 00 = 1000 ppm, 01 = variable pitch — requires compatible receiver)", "6-7": "Undefined / reserved"}},
                {"byte": 4, "bits": {"0": "Word length (0 = 20-bit, 1 = 24-bit)", "1-3": "Sample length code (0 = undefined; 1-4 = word length minus 1-4 bits; 5 = full word length)", "4-7": "Undefined / reserved"}},
                {"bytes": "5-10 + 11.0-3", "purpose": "EAN-13 code (possibly in BCD); byte 11 bits 4-7 = undefined / padding on 13-digit EAN."},
                {"bytes": "12-13",          "purpose": "Undefined / reserved."},
                {"byte": 14, "bits": {"0-3": "Undefined", "4-7": "ISRC field — encoding unclear; ISRC = 2 alphabetic + 3 alphanumeric + 7 numeric (~7.5 bytes naive fit)."}},
                {"bytes": "15-21",          "purpose": "Remaining ISRC bytes."},
                {"bytes": "22-23",          "purpose": "Undefined / reserved."},
            ],
        })
        d.setdefault("iec_61937_encapsulation", {
            "purpose": "IEC 61937 defines how to transmit compressed multi-channel audio (Dolby AC-3, DTS, etc.) over S/PDIF.",
            "rules": [
                "Channel-status word byte 0 bit 1 shall be 1 to indicate the presence of non-linear PCM (compressed) data.",
                "Symbol rate shall be set so the carrier rate (Fs) ≈ 64 × symbol rate (this matches the IEC 60958 framing of 64 BMC-cells per frame).",
                "Compressed data shall be packed into blocks; each block shall start with an IEC 61937 preamble carrying two 16-bit sync words and indicating bitstream type, validity, bitstream number, and length.",
                "Padding shall be inserted to make each compressed-data block match the IEC 60958 block timing.",
            ],
            "supported_encodings": [
                "Dolby Digital (AC-3)", "Dolby Digital Plus (E-AC-3)",
                "Dolby TrueHD", "DTS", "MP3", "AAC", "ATRAC", "WMA Pro",
            ],
        })
        _write(p, d)

    # L4 — Wire-level; no protocol register map
    p = gd / "L4_REGMAP.json"
    if p.is_file():
        d = _read(p)
        d["register_map_present"] = False
        d["notes"] = (
            "S/PDIF (IEC 60958 type II) is a wire-level streaming protocol; "
            "it does not define an MCU-visible register map at the protocol "
            "layer. Concrete S/PDIF transmitter / receiver IP blocks define "
            "their own register file at the SoC-integration level — "
            "typically: TX/RX FIFO control, sample-rate / bit-clock divisor, "
            "channel-status word write/read buffers (consumer 192-bit), "
            "user-data buffer (192-bit per channel), validity / "
            "parity-error counters, lock-status, IEC 61937 burst detection "
            "and bitstream-type readback, mute control. Those are covered "
            "by individual IP block guides, not by IEC 60958 itself.")
        _write(p, d)

    # L5 — ADI / signaling
    p = gd / "L5_ADI_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("analog_digital_interface_present", False)
        d["signaling_summary"] = (
            "Although S/PDIF is the data path to and from audio D/A and A/D "
            "converters, the S/PDIF link itself is purely digital. Two "
            "physical-layer flavours are defined: (a) coaxial electrical "
            "S/PDIF over a 75 Ω cable with 0.5–0.6 V peak-to-peak output "
            "level at the transmitter and 0.2 V minimum input level at the "
            "receiver, terminated in RCA (typically orange-coded) or BNC; "
            "(b) optical S/PDIF over a Toslink JIS F05 / EIAJ fibre-optic "
            "link, identical in content to the coaxial form, which "
            "inherently provides electrical isolation that breaks ground "
            "loops. The analog characteristics of any DAC or ADC connected "
            "to the S/PDIF link (sample rate, dynamic range, SNR, jitter "
            "sensitivity) are separate from the S/PDIF protocol itself.")
        _write(p, d)

    # L6 — Control logic / FSM
    p = gd / "L6_CONTROL_LOGIC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("fsm_states_transmitter", [
            {"name": "TX_IDLE",        "description": "Transmitter is enabled but no audio source is feeding it; output may continuously emit valid IEC 60958 frames with audio = 0 and validity bit V = 1 to indicate non-audio, or pause the line entirely (implementation-defined)."},
            {"name": "TX_PREAMBLE_X",  "description": "Emit preamble X = channel-A subframe start within a block (frames 2-192); this 4-cell pattern deliberately violates BMC rules so receivers can detect it."},
            {"name": "TX_PREAMBLE_Y",  "description": "Emit preamble Y = channel-B subframe start (every frame)."},
            {"name": "TX_PREAMBLE_Z",  "description": "Emit preamble Z = channel-A subframe start of frame 1 of a block (= block boundary). Only one Z per 192 frames."},
            {"name": "TX_AUX_FIELD",   "description": "Drive Aux field (4 bits) — either 4 LSBs of a 24-bit audio sample, or ancillary data."},
            {"name": "TX_AUDIO_SAMPLE","description": "Drive the 20-bit audio sample (bits 8-27), MSB at bit 27."},
            {"name": "TX_V_BIT",       "description": "Drive Validity bit at bit 28 (0 = valid for D/A, 1 = not valid / IEC 61937 / fault)."},
            {"name": "TX_U_BIT",       "description": "Drive User-data bit at bit 29 (one bit per subframe of the user-data channel)."},
            {"name": "TX_C_BIT",       "description": "Drive Channel-status bit at bit 30 (one bit per subframe; bit position within the 192-bit channel-status word = subframe index modulo 384 / 2 per channel)."},
            {"name": "TX_P_BIT",       "description": "Drive Parity bit at bit 31 = even parity over bits 4-30 of the same subframe."},
            {"name": "TX_BMC_ENCODE",  "description": "Every emitted data bit is passed through the Bi-phase Mark encoder: ensure a transition at every bit boundary; insert a mid-bit transition for a '1', omit it for a '0'. Preamble bits override this rule to produce the long-pulse X/Y/Z patterns."},
        ])
        d.setdefault("fsm_states_receiver", [
            {"name": "RX_BMC_LOCK",        "description": "Lock onto BMC transitions and recover bit clock from the received signal."},
            {"name": "RX_PREAMBLE_HUNT",   "description": "Scan for X / Y / Z preamble pattern (long pulses that violate BMC rules) to align to subframe / frame / block boundaries."},
            {"name": "RX_PREAMBLE_DECODE", "description": "Classify detected preamble as X (channel-A start, mid-block), Y (channel-B start), or Z (channel-A start at block boundary). Update block / frame / channel counters accordingly."},
            {"name": "RX_AUX_LATCH",       "description": "Capture 4-bit Aux field (bits 4-7)."},
            {"name": "RX_AUDIO_LATCH",     "description": "Capture 20-bit audio sample (bits 8-27)."},
            {"name": "RX_V_LATCH",         "description": "Capture Validity bit (bit 28). If V = 0, the audio sample is valid for D/A; if V = 1, the receiver shall not pass the sample to a PCM DAC."},
            {"name": "RX_U_LATCH",         "description": "Capture User bit (bit 29) and append to the per-channel user-data stream."},
            {"name": "RX_C_LATCH",         "description": "Capture Channel-status bit (bit 30) and append to the per-channel 192-bit channel-status word."},
            {"name": "RX_P_CHECK",         "description": "Latch Parity bit (bit 31) and verify even parity over bits 4-30. On mismatch, flag the subframe and either mute, repeat the last sample, or report depending on policy."},
            {"name": "RX_BLOCK_COMPLETE",  "description": "After 192 frames since the last Z preamble, the per-channel 192-bit channel-status word is complete and may be parsed for sample rate / word length / copy / category / etc."},
        ])
        d.setdefault("fsm_hints", {
            "trigger": "Continuous self-clocked BMC stream; no start / stop framing. X / Y / Z preambles + frame counters drive all alignment.",
            "rule":    "Each subframe must contain 32 BMC-bit-times; preamble must be one of X / Y / Z; parity P must be even over bits 4-30.",
            "abort":   "There is no formal abort signal at the protocol level. Loss of signal (no transitions) drops BMC lock; receiver retries from RX_BMC_LOCK.",
        })
        d.setdefault("anti_deadlock_rule",
            "S/PDIF is a single-transmitter / single-receiver point-to-point link with no arbitration; deadlocks at the protocol layer are not possible. The receiver simply re-syncs on the next valid preamble after any glitch.")
        d.setdefault("exit_from_reset_or_poweron",
            "On power-on / reset, the transmitter (a) initializes its 192-bit channel-status word per consumer S/PDIF defaults (byte 0 bit 0 = 0 → Consumer), (b) prepares to emit Z at the next block boundary, (c) begins driving BMC transitions. The receiver enters RX_BMC_LOCK on detection of edges, advances to RX_PREAMBLE_HUNT, and aligns on the first detected X / Y / Z preamble.")
        d.setdefault("default_ready_state_recommendation", {
            "transmitter_idle":   "If no audio source, emit IEC 60958 frames with audio = 0 and V = 1, OR mute the line (implementation-defined).",
            "receiver_lost_sync": "Mute the analog output until BMC lock + preamble alignment are both re-established.",
        })
        d.setdefault("configurations", [
            {"name": "Consumer PCM stereo (default)",      "description": "Channel-status byte 0 bit 0 = 0 (Consumer), bit 1 = 0 (PCM), bit 3 = 0 (2 channels). Subframes carry left and right 20-bit (or 24-bit via Aux) PCM samples."},
            {"name": "Consumer IEC 61937 compressed",      "description": "Channel-status byte 0 bit 0 = 0 (Consumer), bit 1 = 1 (data). Audio-sample field carries IEC 61937-framed Dolby AC-3 / DTS / MP3 / AAC / Dolby TrueHD bitstream with preamble + sync words + padding."},
            {"name": "Professional AES3 (out of S/PDIF scope but same bitstream)", "description": "Channel-status byte 0 bit 0 = 1 (Professional). Frame structure is identical to S/PDIF but the channel-status word is re-interpreted per AES3."},
        ])
        d.setdefault("timing_dependency_rule",
            "All timing is referenced to the bit clock recovered from the BMC stream itself. The receiver's local oscillator (if used to drive the DAC) must track the recovered clock to avoid bit-slip; many practical S/PDIF receivers add jitter that can be audible if the DAC has no stable internal reference. The transmitter is the rate master; the receiver is the rate slave.")
        d.setdefault("biphase_mark_encoding_rule", {
            "summary": "Bi-phase Mark Code (BMC) — a Manchester variant — has TWO cells per data bit. Cell 1 of a data bit always toggles relative to the previous cell (= transition at every bit boundary). For a '1', cell 2 toggles again mid-bit (= mid-bit transition). For a '0', cell 2 does not toggle (= no mid-bit transition).",
            "consequences": "Direct guarantees: (a) DC-balanced signal (no DC offset bias), (b) embedded bit clock (can be recovered without separate clock line), (c) polarity-independent decode (inverting the stream gives the same data).",
            "preamble_rule": "The X / Y / Z preambles INTENTIONALLY violate BMC's 'transition every bit boundary' rule, generating multi-cell-long pulses. These long pulses are guaranteed not to appear in valid BMC-encoded data and therefore unambiguously locate subframe / frame / block boundaries.",
        })
        _write(p, d)

    # L7 — Test / debug
    p = gd / "L7_TEST_DEBUG.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("test_debug_architecture_present", False)
        d.setdefault("spec_provided_observability", [
            {"name": "Parity bit P (bit 31 of each subframe)",   "purpose": "Even parity over bits 4-30; receiver may report any mismatch, providing per-subframe error detection."},
            {"name": "Validity bit V (bit 28 of each subframe)", "purpose": "V = 0 → sample valid for D/A; V = 1 → sample not valid (e.g. IEC 61937 carrier or fault). Receiver can report V transitions as a coarse error indicator."},
            {"name": "X / Y / Z preamble pattern",                "purpose": "Loss of expected preamble periodicity signals loss of BMC lock or subframe alignment, useful for receiver lock-status reporting."},
            {"name": "Channel-status byte 0 bit 0 (Consumer / Professional)", "purpose": "Receiver can verify the link is in the expected mode (Consumer = S/PDIF). Mismatch indicates either misconfigured transmitter or wrong-type cable / interface."},
            {"name": "Channel-status byte 3 sampling frequency code", "purpose": "Receiver can compare declared rate (44.1 / 48 / 32 / 88.2 / 96 / 176.4 / 192 kHz) against measured BMC rate; mismatch indicates channel-status corruption or transmitter misconfiguration."},
            {"name": "Channel-status byte 4 word-length code",        "purpose": "Lets receiver decide how many LSBs of the 20-bit audio field carry meaningful data (and whether to use the Aux field for the 21-24 LSBs of a 24-bit sample)."},
            {"name": "Receiver-measured jitter",                       "purpose": "S/PDIF is widely known to inject jitter into recovered clocks; measuring jitter at the recovered clock or downstream DAC clock identifies link quality."},
        ])
        d.setdefault("notes",
            "IEC 60958 does not specify a formal observability architecture beyond V / P / preamble / channel-status. Concrete S/PDIF receiver IPs typically expose: lock-status, BMC bit-error counter, parity-error counter, validity-fault counter, channel-status snapshot register, IEC 61937 bitstream-type detect, sample-rate measurement, and jitter accumulator — all per-implementation and beyond the IEC 60958 normative content.")
        _write(p, d)

    # L8 — RTL constants
    p = gd / "L8_RTL_CONSTANTS.json"
    if p.is_file():
        d = _read(p)
        wp = d.setdefault("width_parameters", {})
        if isinstance(wp, dict):
            for k, v in {
                "SPDIF_LINE_WIDTH":                    1,
                "EXTERNAL_PIN_COUNT":                  1,
                "SUBFRAME_BIT_WIDTH":                 32,
                "SUBFRAMES_PER_FRAME":                 2,
                "FRAMES_PER_BLOCK":                  192,
                "SUBFRAMES_PER_BLOCK":               384,
                "PREAMBLE_BIT_FIELD_WIDTH":            4,
                "PREAMBLE_BMC_CELL_WIDTH":             8,
                "AUX_FIELD_BIT_WIDTH":                 4,
                "AUDIO_SAMPLE_BIT_WIDTH":             20,
                "AUDIO_SAMPLE_BIT_WIDTH_24BIT_MODE":  24,
                "V_BIT_WIDTH":                         1,
                "U_BIT_WIDTH":                         1,
                "C_BIT_WIDTH":                         1,
                "P_BIT_WIDTH":                         1,
                "CHANNEL_STATUS_WORD_BIT_WIDTH_PER_CHANNEL": 192,
                "USER_DATA_WORD_BIT_WIDTH_PER_CHANNEL":      192,
                "CHANNELS":                             2,
                "BMC_CELLS_PER_BIT":                    2,
                "BMC_CELLS_PER_SUBFRAME":              64,
                "BMC_CELLS_PER_FRAME":                128,
            }.items():
                wp.setdefault(k, v)
        d.setdefault("voltage_levels", {
            "coax_transmitter_output_Vpp": "0.5 to 0.6 V peak-to-peak (typical 500 mV)",
            "coax_receiver_min_input_V":   "0.2 V minimum",
            "coax_cable_impedance_ohm":    75,
            "coax_max_distance_m":         10,
            "optical_connector":           "Toslink (JIS F05 / EIAJ)",
            "optical_max_distance_m":      10,
        })
        d.setdefault("preamble_table_bmc_cells", {
            "X_following_logic_low":  "11100010 (channel-A subframe start, mid-block)",
            "X_following_logic_high": "00011101 (channel-A subframe start, mid-block; inverted polarity)",
            "Y_following_logic_low":  "11100100 (channel-B subframe start)",
            "Y_following_logic_high": "00011011 (channel-B subframe start; inverted polarity)",
            "Z_following_logic_low":  "11101000 (channel-A subframe start of block / block boundary)",
            "Z_following_logic_high": "00010111 (channel-A subframe start of block; inverted polarity)",
            "note": "Each preamble is 8 BMC cells = 4 bit-times. The three patterns intentionally break BMC's 'transition every bit boundary' rule with three-cell-long pulses, guaranteeing they cannot appear in regular BMC-coded data and so locate subframe / frame / block boundaries unambiguously.",
        })
        d.setdefault("key_constants_for_RTL_authoring", {
            "subframe_layout_bits": {
                "preamble_bits":      "0-3 (X / Y / Z, BMC-violating long pulses)",
                "aux_bits":           "4-7 (optional 4 LSBs of 24-bit sample OR ancillary)",
                "audio_sample_bits":  "8-27 (20-bit, MSB at bit 27)",
                "validity_bit":       28,
                "user_data_bit":      29,
                "channel_status_bit": 30,
                "parity_bit":         31,
            },
            "parity_polynomial":              "Even parity over bits 4-30 (Aux + Audio + V + U + C). Receiver verifies; transmitter computes.",
            "bit_clock_to_sample_rate_ratio": 64,
            "valid_for_DAC_when":              "Validity bit V = 0",
            "data_byte_order_within_audio":    "20-bit audio is LSB-first within bits 8-27 (LSB at bit 8, MSB at bit 27)",
            "channel_A_preamble_mid_block":    "X",
            "channel_A_preamble_block_start":  "Z",
            "channel_B_preamble":              "Y",
            "channel_status_aggregation":      "1 bit per subframe; aggregated 192 bits per channel per block. Channel-status word is identical between channel A and channel B in consumer S/PDIF.",
            "user_data_aggregation":           "1 bit per subframe; aggregated 192 bits per channel per block.",
        })
        d.setdefault("consumer_channel_status_byte_layout", {
            "byte_0": {"bit_0": "0 = Consumer / 1 = Professional (changes byte 0 onward to AES3 channel-status word)", "bit_1": "0 = Normal PCM / 1 = Compressed data (IEC 61937)", "bit_2": "0 = Copy restrict / 1 = Copy permit (SCMS)", "bit_3": "0 = 2 channels / 1 = 4 channels", "bit_4": "Reserved", "bit_5": "0 = No pre-emphasis / 1 = 50/15 µs pre-emphasis", "bits_6_7": "Mode (defines subsequent bytes; non-zero values undefined)"},
            "byte_1": {"bits_0_6": "Audio source category (general, CD-DA, DAT, DVD, etc.)", "bit_7": "L-bit (original / copy, only defined when copy restrict = 0)"},
            "byte_2": {"bits_0_3": "Source number", "bits_4_7": "Channel number"},
            "byte_3": {"bits_0_3": "Sampling frequency (0000 = 44.1 kHz, 0100 = 48 kHz, 1100 = 32 kHz, etc.)", "bits_4_5": "Clock accuracy (10 = 50 ppm, 00 = 1000 ppm, 01 = variable pitch)", "bits_6_7": "Undefined / reserved"},
            "byte_4": {"bit_0": "Word length 0 = 20 bits / 1 = 24 bits", "bits_1_3": "Sample length (0 = undefined, 1-4 = word length minus 1-4 bits, 5 = full word length)", "bits_4_7": "Undefined / reserved"},
            "bytes_5_10_plus_byte_11_bits_0_3": "EAN-13 code (possibly in BCD); byte 11 bits 4-7 = undefined / padding on 13-digit EAN.",
            "bytes_12_13":                       "Undefined.",
            "byte_14": {"bits_0_3": "Undefined", "bits_4_7": "ISRC start"},
            "bytes_15_21":                       "Continuation of ISRC (ISRC = 2 alphabetic + 3 alphanumeric + 7 numeric, fitting in ~7.5 bytes).",
            "bytes_22_23":                       "Undefined.",
        })
        d.setdefault("supported_sample_rates_kHz", [32, 44.1, 48, 88.2, 96, 176.4, 192])
        d.setdefault("carrier_to_sample_rate_relationship",
            "Frame rate = sample rate (one frame per sample period). Bit clock = 64 × sample rate (because each frame = 64 BMC cells × 2 = 128 BMC cells; 64 data bits per frame across two subframes). The IEC 61937 carrier rate is usually 64 × the underlying symbol rate of the compressed bitstream.")
        d.setdefault("default_signal_values_when_idle", {
            "transmitter_no_audio": "Continue emitting valid IEC 60958 frames with audio sample = 0 and Validity bit V = 1, OR pause / drop the line — implementation-defined.",
            "receiver_lost_sync":    "Mute analog output and wait for BMC lock + preamble alignment to be re-established.",
        })
        _write(p, d)

    # L8 — Timing / waveforms
    p = gd / "L8_TIMING_WAVEFORM.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("biphase_mark_code_waveform", {
            "summary":           "Bi-phase Mark Code is a Manchester variant with TWO cells per data bit. Cell 1 of every data bit toggles relative to the previous cell (= transition at every bit boundary). For a '1', cell 2 also toggles (= mid-bit transition). For a '0', cell 2 does not toggle (= no mid-bit transition).",
            "transitions_per_1_bit": 2,
            "transitions_per_0_bit": 1,
            "dc_balance":            "DC-balanced over time because every bit boundary has a transition.",
            "polarity_independence": "Inverting the BMC stream yields the same decoded data — the receiver can lock without knowing absolute polarity.",
            "clock_recovery":        "The bit clock can be recovered from the BMC transitions themselves; no separate clock line is required.",
        })
        d.setdefault("preamble_waveforms_bmc_cells", {
            "Z": {"following_logic_low": "11101000", "following_logic_high": "00010111", "purpose": "Channel-A subframe start of frame 1 of a block — block boundary."},
            "X": {"following_logic_low": "11100010", "following_logic_high": "00011101", "purpose": "Channel-A subframe start — frames 2-192 within a block."},
            "Y": {"following_logic_low": "11100100", "following_logic_high": "00011011", "purpose": "Channel-B subframe start — every frame."},
            "rule": "Each preamble is 8 BMC cells = 4 data-bit times wide. The three patterns each contain a three-cell-long pulse, deliberately violating BMC's 'transition every bit boundary' rule; this guarantees they cannot collide with valid BMC data and serve as unambiguous frame markers.",
        })
        d.setdefault("subframe_timing", {
            "total_bit_times_per_subframe":  32,
            "bmc_cells_per_subframe":        64,
            "field_bit_offsets": [
                {"field": "Preamble",        "bits": "0-3",   "purpose": "X / Y / Z BMC-violating long pulses for subframe alignment"},
                {"field": "Aux",             "bits": "4-7",   "purpose": "Optional 4 LSBs of 24-bit audio sample, or ancillary data"},
                {"field": "Audio sample",    "bits": "8-27",  "purpose": "20-bit audio (LSB at bit 8, MSB at bit 27)"},
                {"field": "Validity V",      "bits": "28",    "purpose": "0 = valid for D/A; 1 = not valid"},
                {"field": "User data U",     "bits": "29",    "purpose": "One user-data bit (aggregates to 192 bits/channel/block)"},
                {"field": "Channel status C","bits": "30",    "purpose": "One channel-status bit (aggregates to 192 bits/channel/block)"},
                {"field": "Parity P",        "bits": "31",    "purpose": "Even parity over bits 4-30 of the same subframe"},
            ],
        })
        d.setdefault("frame_timing", {
            "subframes_per_frame": 2,
            "channel_A_subframe":  {"position": "first subframe of the frame",  "preamble_mid_block": "X", "preamble_block_start": "Z"},
            "channel_B_subframe":  {"position": "second subframe of the frame", "preamble": "Y"},
        })
        d.setdefault("block_timing", {
            "frames_per_block":            192,
            "subframes_per_block":         384,
            "block_boundary_marker":       "Preamble Z appears on the channel-A subframe of frame 1 of every block; X appears on the channel-A subframe of frames 2-192.",
            "channel_status_word_complete":"After 192 successive C-bits per channel, the 192-bit channel-status word for that channel is reassembled.",
            "user_data_word_complete":     "After 192 successive U-bits per channel, the 192-bit user-data word for that channel is reassembled.",
        })
        d.setdefault("carrier_bit_rate_examples", {
            "fs_44_1_kHz_PCM_stereo": {"sample_rate_Hz":  44100, "frame_rate_Hz":  44100, "bit_clock_MHz_data":  2.8224,  "bmc_cell_rate_MHz":  5.6448,  "use_case": "CD-audio"},
            "fs_48_kHz_PCM_stereo":   {"sample_rate_Hz":  48000, "frame_rate_Hz":  48000, "bit_clock_MHz_data":  3.072,   "bmc_cell_rate_MHz":  6.144,   "use_case": "DAT / DVD"},
            "fs_32_kHz_PCM_stereo":   {"sample_rate_Hz":  32000, "frame_rate_Hz":  32000, "bit_clock_MHz_data":  2.048,   "bmc_cell_rate_MHz":  4.096,   "use_case": "Broadcast / low-rate"},
            "fs_88_2_kHz_PCM_stereo": {"sample_rate_Hz":  88200, "frame_rate_Hz":  88200, "bit_clock_MHz_data":  5.6448,  "bmc_cell_rate_MHz": 11.2896,  "use_case": "High-resolution"},
            "fs_96_kHz_PCM_stereo":   {"sample_rate_Hz":  96000, "frame_rate_Hz":  96000, "bit_clock_MHz_data":  6.144,   "bmc_cell_rate_MHz": 12.288,   "use_case": "DVD-Audio"},
            "fs_176_4_kHz_PCM_stereo":{"sample_rate_Hz": 176400, "frame_rate_Hz": 176400, "bit_clock_MHz_data": 11.2896,  "bmc_cell_rate_MHz": 22.5792,  "use_case": "High-resolution"},
            "fs_192_kHz_PCM_stereo":  {"sample_rate_Hz": 192000, "frame_rate_Hz": 192000, "bit_clock_MHz_data": 12.288,   "bmc_cell_rate_MHz": 24.576,   "use_case": "DVD-Audio / Blu-ray"},
        })
        d.setdefault("electrical_levels", {
            "coax_transmitter_output_Vpp_min": 0.5,
            "coax_transmitter_output_Vpp_max": 0.6,
            "coax_receiver_min_input_V":       0.2,
            "coax_cable_impedance_ohm":        75,
            "coax_max_distance_m":             10,
            "optical_connector":               "Toslink (JIS F05 / EIAJ optical)",
            "optical_max_distance_m":          10,
        })
        d.setdefault("general_timing_rule",
            "All timing is scaled to the sample rate. The frame rate equals the sample rate (one frame per sample). The data bit rate equals 64 × sample rate (64 data bits per frame: 2 subframes × 32 bits). The BMC cell rate equals 128 × sample rate (2 BMC cells per data bit). The receiver recovers clock from the BMC transitions and uses the X / Y / Z preambles to align subframe / frame / block boundaries.")
        _write(p, d)

    # L9 — Integration spec
    p = gd / "L9_INTEGRATION_SPEC.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("module_role",
            "Wire-level single-wire (coax or fibre) self-clocked digital-audio link between a single transmitter IC and a single receiver IC. Defines a consumer-grade digital audio interface per IEC 60958 type II carrying two channels of PCM or compressed (IEC 61937) audio. Concrete S/PDIF transmitter / receiver IP blocks implement this protocol behind an MCU register interface for SoC integration.")
        d.setdefault("integration_overview", {
            "wire_count":             1,
            "wire_direction":         "Unidirectional from transmitter to receiver",
            "no_chip_select":         "There is no chip-select / select / strobe line.",
            "no_addressing":          "There is no device addressing; the bus is point-to-point.",
            "no_back_channel":        "Receiver has no flow control over the transmitter; rate master is unambiguously the transmitter.",
            "no_clock_line":          "Bit clock is recovered from the BMC line transitions; no separate clock pin.",
            "self_clocked":           "BMC line encoding guarantees ≥ 1 transition per bit, so a PLL or digital clock-recovery loop in the receiver can lock to the embedded clock.",
            "physical_layer_options": "Coaxial 75 Ω (RCA or BNC connector, 0.5–0.6 Vpp) OR Toslink fibre-optic (JIS F05 / EIAJ).",
            "max_distance":           "Approximately 10 m for both coax and Toslink.",
        })
        d.setdefault("interface_categories", [
            "Transmitter (drives the BMC stream onto the coax or optical link).",
            "Receiver (recovers clock from BMC transitions, decodes preambles, and reconstructs audio samples + V/U/C/P bits + 192-bit channel-status word).",
            "Transceiver (combines both — uncommon for S/PDIF; receiver-only and transmitter-only ICs are typical).",
        ])
        d.setdefault("interconnect_topologies_supported", [
            "Point-to-point single link (most common case).",
            "Daisy-chain re-clocking via a transceiver (rare; introduces additional jitter).",
        ])
        d.setdefault("default_signal_values_when_omitted",
            "Transmitter with no audio source may either pause the line entirely or emit IEC 60958 frames with audio = 0 and V = 1 (implementation-defined). Receiver mutes its DAC until BMC lock and preamble alignment are both established.")
        d.setdefault("soc_dependent_items", [
            "S/PDIF transmitter / receiver IP register file: TX/RX FIFO control, sample-rate divisor, channel-status word write/read buffers, user-data buffers, parity/validity error counters, lock-status, IEC 61937 burst detection, mute control.",
            "Audio sample-rate clock generation (PLL / fractional divider producing 64 × Fs at the transmitter side).",
            "Clock recovery loop in the receiver (digital DPLL or analog PLL on the BMC edges).",
            "Optional master clock (MCLK) for connected DACs — beyond the S/PDIF protocol but commonly co-routed.",
            "Pad selection: coax transformer-coupled driver / receiver, OR Toslink LED driver and photodiode receiver IC.",
            "Interrupt routing for parity errors, lock loss, and IEC 61937 bitstream-type changes.",
            "DMA-controller wiring for streaming audio data into and out of the audio subsystem.",
        ])
        d.setdefault("common_audio_sample_rate_examples", [
            {"rate_kHz":  32,    "bits": 16, "bit_clock_MHz":  2.048},
            {"rate_kHz":  44.1,  "bits": 16, "bit_clock_MHz":  2.8224, "note": "CD-DA"},
            {"rate_kHz":  48,    "bits": 20, "bit_clock_MHz":  3.072,  "note": "DAT / DVD"},
            {"rate_kHz":  48,    "bits": 24, "bit_clock_MHz":  3.072,  "note": "Uses Aux field for 24-bit; same bit clock"},
            {"rate_kHz":  88.2,  "bits": 24, "bit_clock_MHz":  5.6448},
            {"rate_kHz":  96,    "bits": 24, "bit_clock_MHz":  6.144},
            {"rate_kHz": 176.4, "bits": 24, "bit_clock_MHz": 11.2896},
            {"rate_kHz": 192,   "bits": 24, "bit_clock_MHz": 12.288, "note": "DVD-Audio / Blu-ray PCM"},
        ])
        d.setdefault("low_power_modes", {
            "Mute":              "Transmitter may emit silence frames with V = 1 or pause the line; receiver mutes its DAC.",
            "Stop_carrier":      "Transmitter may stop driving the line entirely; receiver loses BMC lock and reports loss-of-signal.",
            "IEC_61937_dormant": "Periodic null bursts in IEC 61937 mode keep the channel-status word valid while the compressed encoder is dormant.",
        })
        _write(p, d)

    # L10 — Test cases
    p = gd / "L10_TEST_CASES.json"
    if p.is_file():
        d = _read(p)
        d["test_cases_present"] = (
            "partial - the spec defines frame / subframe structure, "
            "preamble waveforms, BMC encoding rules, parity definition, "
            "channel-status byte layout, IEC 61937 encapsulation rules, "
            "and physical-layer electrical/optical specifications that map "
            "directly to compliance test scenarios, but does not provide a "
            "formal testbench.")
        d.setdefault("derived_compliance_test_categories", [
            "Bi-phase Mark Code encoding: every data bit has a transition at the bit boundary; '1' has an additional mid-bit transition, '0' does not; receiver locks to the recovered clock.",
            "Preamble X (8 BMC cells) correctly emitted at the start of every channel-A subframe outside frame 1 of a block.",
            "Preamble Y (8 BMC cells) correctly emitted at the start of every channel-B subframe.",
            "Preamble Z (8 BMC cells) correctly emitted at the start of the channel-A subframe of frame 1 of every block (one Z per 192 frames).",
            "Preamble patterns intentionally violate BMC rules (three-cell-long pulse) so the receiver can detect them unambiguously.",
            "Subframe length = exactly 32 BMC-bit-times.",
            "Frame length = exactly 2 subframes = 64 data bits = 128 BMC cells.",
            "Block length = exactly 192 frames = 384 subframes.",
            "Audio sample (bits 8-27) reconstructed correctly as a 20-bit value with the MSB at bit 27.",
            "Optional 24-bit mode: receiver concatenates Aux (bits 4-7) with audio (bits 8-27) to form a 24-bit sample.",
            "Validity bit V (bit 28) = 0 ⇒ sample valid for D/A; V = 1 ⇒ receiver does NOT pass sample to PCM DAC.",
            "User-data bit U (bit 29) correctly accumulated into the 192-bit user-data word per channel per block.",
            "Channel-status bit C (bit 30) correctly accumulated into the 192-bit channel-status word per channel per block (identical between channel A and channel B in consumer S/PDIF).",
            "Parity bit P (bit 31) = even parity over bits 4-30 of the same subframe.",
            "Channel-status byte 0 bit 0 = 0 ⇒ Consumer (S/PDIF); receiver applies consumer interpretation.",
            "Channel-status byte 0 bit 1 = 0 ⇒ Normal PCM; bit 1 = 1 ⇒ Compressed data (IEC 61937).",
            "Channel-status byte 0 bit 2 SCMS copy flag honored.",
            "Channel-status byte 0 bit 3 channel-count encoding (0 = 2 channels, 1 = 4 channels) correctly decoded.",
            "Channel-status byte 0 bit 5 pre-emphasis flag detected.",
            "Channel-status byte 1 bits 0-6 audio source category code passed through.",
            "Channel-status byte 2 source number + channel number correctly parsed.",
            "Channel-status byte 3 sampling frequency code matches measured BMC rate (44.1 / 48 / 32 / 88.2 / 96 / 176.4 / 192 kHz).",
            "Channel-status byte 3 clock-accuracy code (50 ppm / 1000 ppm / variable pitch) correctly reported.",
            "Channel-status byte 4 word-length code (20-bit vs 24-bit and sample-length 0-5) correctly reported.",
            "EAN-13 code (bytes 5-10 + byte 11 bits 0-3) carried through end-to-end.",
            "ISRC field (byte 14 bits 4-7 through byte 21) carried through end-to-end.",
            "IEC 61937 encapsulation: channel-status bit 1 = 1, two 16-bit sync words at burst start, bitstream type + length + validity decoded.",
            "Coaxial transmitter output level: 0.5–0.6 V peak-to-peak into 75 Ω.",
            "Coaxial receiver input level minimum: 0.2 V.",
            "Toslink optical link content matches coaxial content bit-for-bit.",
            "Max cable distance ~10 m for both coax and Toslink.",
            "Receiver re-syncs cleanly after a brief BMC interruption (loss-of-lock recovery test).",
            "Parity mismatch handled per implementation policy (mute / repeat / report) without losing channel-status alignment.",
            "Variable-pitch (consumer pitch shift) declared via byte 3 bits 4-5 = 01 — receiver tracks the drifting BMC rate.",
        ])
        _write(p, d)

    # L11 — OTP
    p = gd / "L11_OTP_CONTENT.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("otp_present", False)
        d["notes"] = (
            "S/PDIF (IEC 60958 type II) is a wire-level streaming "
            "digital-audio protocol; it does not define any OTP / fuse "
            "content at the protocol layer. Individual S/PDIF transmitter "
            "/ receiver ICs may use OTP for analog-trim of the Toslink LED "
            "bias, coax driver level calibration, or device serial-number "
            "storage, but those are per-device implementation choices and "
            "are not part of the IEC 60958 spec.")
        _write(p, d)

    # L12 — Behavioral sequences
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("typical_streaming_sequence", [
            "1. Source software (or audio FIFO) latches a stereo audio sample (left + right, 16 / 20 / 24-bit) at sample rate Fs.",
            "2. Transmitter constructs channel-A subframe: chooses preamble X (or Z if this is frame 1 of a block) + Aux + 20-bit left sample + V + U + C + P (even parity over bits 4-30).",
            "3. BMC encoder turns the 32 data bits into 64 BMC cells, intentionally substituting the BMC sequence for bits 0-3 with the long-pulse Z / X pattern.",
            "4. Transmitter constructs channel-B subframe with preamble Y + Aux + 20-bit right sample + V + U + C + P; BMC encodes it.",
            "5. The two subframes form one frame; 192 successive frames form one block. Within a block, the channel-status (C) and user-data (U) bits accumulate to form 192-bit per-channel words.",
            "6. Receiver's BMC clock recovery locks to the bit-rate-period transitions and scans for X / Y / Z preambles (long pulses that break BMC).",
            "7. On detecting a preamble, the receiver classifies it (X / Y / Z) and uses it to align subframe / frame / block counters.",
            "8. Each subframe: receiver captures Aux + 20-bit audio + V + U + C + P; verifies even parity; appends C to the per-channel 192-bit channel-status accumulator; appends U to the per-channel 192-bit user-data accumulator.",
            "9. When V = 0, the recovered 20-bit (or 24-bit using Aux) sample is passed to the DAC. When V = 1, the receiver routes the audio-sample field to its IEC 61937 demux instead of the PCM DAC.",
            "10. Once 192 frames have elapsed since the last Z preamble, the receiver parses the 192-bit channel-status word: Consumer/Pro, PCM/Compressed, SCMS, channel count, pre-emphasis, mode, category, source/channel number, sampling frequency, clock accuracy, word length, sample length, EAN-13, ISRC, etc.",
        ])
        d.setdefault("iec_61937_compressed_sequence", [
            "1. Source delivers a compressed bitstream (Dolby AC-3 / DTS / MP3 / AAC / Dolby TrueHD / E-AC-3 / ATRAC / WMA Pro) at the underlying symbol rate.",
            "2. Transmitter sets channel-status byte 0 bit 1 = 1 (compressed data) and forces V = 1 on every audio subframe so receivers do not feed the data to a PCM DAC.",
            "3. Transmitter packs the bitstream into blocks; each block is prefixed with an IEC 61937 preamble carrying two 16-bit sync words and indicating bitstream type, validity, bitstream number, and length.",
            "4. The bitstream symbols are placed into the audio-sample field of consecutive subframes; padding (zeros) is inserted to make each compressed-data block match the IEC 60958 block timing.",
            "5. The frame carrier rate is chosen so it equals approximately 64 × the symbol rate of the compressed data.",
            "6. Receiver detects channel-status bit 1 = 1, routes the audio-sample field through its IEC 61937 demux, detects the sync words + preamble, recovers bitstream type and length, and forwards the bitstream to a Dolby / DTS / MP3 / etc. decoder.",
        ])
        d.setdefault("lock_acquisition_sequence", [
            "1. Receiver detects BMC transitions on the coax or Toslink input; locks its clock recovery loop to the recovered bit clock.",
            "2. Receiver scans for the next long-pulse pattern matching X / Y / Z.",
            "3. On detecting any one of X / Y / Z, the receiver knows which subframe class is active and starts a 32-bit subframe counter.",
            "4. On the next preamble, the receiver confirms the expected pattern (X→Y or Y→X or Y→Z). After two consecutive correctly classified preambles, the receiver declares 'subframe lock'.",
            "5. Once a Z preamble is detected, the receiver declares 'block lock' and begins accumulating the 192-bit channel-status word.",
            "6. After 192 frames, the channel-status word is parsed and the recovered sample rate / word length / Consumer-or-Pro / PCM-or-Compressed flags are reported to the host.",
        ])
        d.setdefault("lock_loss_and_recovery_sequence", [
            "1. BMC transitions stop (cable unplugged, transmitter muted) → clock recovery loop drops lock → 'loss-of-signal' interrupt.",
            "2. Audio output is muted automatically.",
            "3. When BMC transitions resume, clock recovery re-locks on a few hundred bit periods, then preamble hunt finds the next X / Y / Z.",
            "4. Block alignment is restored on the next Z preamble.",
            "5. Audio output un-mutes once block lock is regained (some receivers add a 192-frame settling time).",
        ])
        d.setdefault("channel_status_change_sequence", [
            "1. Transmitter updates its 192-bit channel-status word (e.g. on a sample-rate change).",
            "2. The new word is shifted out 1 bit per subframe over the next 192 frames.",
            "3. Receiver accumulates the new word and reports the updated sample rate / word length on the next block boundary (Z preamble).",
            "4. Implementations may delay applying the new rate until the next block boundary to keep the DAC clean.",
        ])
        _write(p, d)

    # L13 — Lab calibration
    p = gd / "L13_LAB_CALIBRATION.json"
    if p.is_file():
        d = _read(p)
        d.setdefault("lab_calibration_present", False)
        d["notes"] = (
            "IEC 60958 type II (S/PDIF) is a digital wire-level protocol; "
            "it does not define an analog reference / trim / calibration "
            "loop at the protocol layer. Connected audio DACs and ADCs may "
            "have their own factory or live calibration (DC offset trim, "
            "gain trim, dither shaping), and S/PDIF transmitter/receiver "
            "ICs may calibrate Toslink LED drive current, coax-driver "
            "output level (0.5–0.6 Vpp) or PLL VCO tuning, but those are "
            "per-device implementation choices, not part of the IEC 60958 "
            "protocol.")
        _write(p, d)

    # L14 — Protocol versioning
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("spec_version",
            "S/PDIF — Sony/Philips Digital Interface; standardized as IEC 60958 type II (formerly IEC 958, renamed in 1998); companion compressed-audio encapsulation per IEC 61937.")
        if _empty(f.get("previous_versions")):
            f["previous_versions"] = [
                "IEC 958 (pre-1998) — Original joint IEC standardization; S/PDIF was 'IEC 958 type II' (consumer), AES3 was 'IEC 958 type I' (professional/balanced).",
                "IEC 60958 (1998 renaming) — IEC 958 renumbered to IEC 60958; the only change was the document number; protocol bits remained the same.",
                "IEC 61937 (mid-1990s onwards) — Companion standard defining how to encapsulate compressed multi-channel audio bitstreams (Dolby AC-3 / DTS / MP3 / AAC / Dolby TrueHD / E-AC-3 / ATRAC / WMA Pro) inside the IEC 60958 frame for transport over S/PDIF or AES3.",
            ]
        if _empty(f.get("key_changes")):
            f["key_changes"] = [
                {"version": "IEC 958 → IEC 60958 (1998)", "summary": "Renaming only; no protocol change. S/PDIF references in older equipment may say 'IEC 958 type II'."},
                {"version": "IEC 61937 superposition",     "summary": "Re-uses the IEC 60958 frame container to tunnel compressed bitstreams. Channel-status byte 0 bit 1 = 1 distinguishes IEC 61937 mode from PCM mode; receivers see V = 1 on every audio sample."},
            ]
        if _empty(f.get("backward_compat_traps")):
            f["backward_compat_traps"] = [
                {"trap_name": "consumer_vs_professional_bit",
                 "rule": "Channel-status byte 0 bit 0 = 0 means Consumer (S/PDIF). Setting it to 1 switches interpretation to Professional AES3, which re-uses bytes 0-23 with completely different semantics.",
                 "trap": "A Consumer S/PDIF transmitter wired into a Professional AES3 receiver (or vice-versa) often appears to lock at the BMC layer but produces wrong channel-status interpretation (e.g. wrong sample rate readout, wrong word-length code). Symptoms include muted audio or wrong sample-rate display."},
                {"trap_name": "PCM_vs_IEC_61937_flag",
                 "rule": "Channel-status byte 0 bit 1 = 0 means PCM, = 1 means IEC 61937 compressed data. Receivers MUST honour V = 1 on subframes in compressed mode.",
                 "trap": "Some legacy receivers ignore byte 0 bit 1 and pass compressed data straight to the PCM DAC, producing loud digital noise. Modern receivers must mute the DAC when V = 1 to avoid speaker damage."},
                {"trap_name": "24-bit_aux_extension",
                 "rule": "Optional 24-bit audio uses the Aux field (bits 4-7) as the lowest 4 LSBs; declared via channel-status byte 4 bit 0 = 1.",
                 "trap": "Many consumer receivers ignore Aux entirely, producing 20-bit playback even when 24-bit content is being sent. Equipment marketed as '24-bit S/PDIF capable' must explicitly opt-in to Aux."},
                {"trap_name": "iec_958_renaming_mismatch",
                 "rule": "IEC 958 (pre-1998) and IEC 60958 (1998+) refer to the same standard.",
                 "trap": "Older equipment / documentation references 'IEC 958' and may not be searchable by the post-1998 name. Treat them as synonymous."},
                {"trap_name": "consumer_channel_status_identical_both_channels",
                 "rule": "In consumer S/PDIF the 192-bit channel-status word is identical for channel A and channel B.",
                 "trap": "Some implementations carelessly send different bits on the two channels' C lines; conforming receivers may report inconsistency and refuse lock. AES3 (professional) does NOT have this constraint — bytes can differ between channels."},
                {"trap_name": "biphase_polarity",
                 "rule": "BMC is polarity-independent — inverting the line produces the same decoded data.",
                 "trap": "However, the preamble TABLE in the spec assumes a starting polarity; implementations that hard-code one of the two preamble patterns may fail to lock when the line is inverted by an intermediate buffer/transformer. Robust decoders look for BOTH the 'following logic low' AND the 'following logic high' preamble forms."},
                {"trap_name": "jitter_at_receiver_clock",
                 "rule": "Receiver does not control the data rate; it must recover clock from BMC transitions.",
                 "trap": "Implementations that drive DAC clocks directly from the recovered S/PDIF clock are widely known to inject audible jitter. Best practice: re-clock the audio data through a stable local crystal-referenced FIFO + asynchronous sample-rate converter."},
            ]
        f.setdefault("version_naming_history_note",
            "S/PDIF was designed by Sony and Philips and standardized in IEC 958 (renamed IEC 60958 in 1998); it is the consumer counterpart (type II) of AES3 (type I). The two share the wire-level frame structure (BMC, subframe, frame, block, preamble) but differ in physical layer (75 Ω coax 0.5 Vpp or Toslink optical vs 110 Ω balanced XLR 2-7 Vpp) and in channel-status word interpretation. IEC 61937 (companion standard) defines compressed-bitstream encapsulation over both AES3 and S/PDIF.")
        d["fields"] = f
        _write(p, d)

    # L15 — Encoding tables
    p = gd / "L15_ENCODING_TABLES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("biphase_mark_encoding_rule", {
            "summary": "Two BMC cells per data bit. A transition always occurs at every bit boundary (cell 1 vs previous-cell). For a '1', cell 2 also toggles (mid-bit transition). For a '0', cell 2 does not toggle.",
            "rules_table": {
                "header_columns": ["Data bit", "Transition at bit boundary", "Mid-bit transition", "BMC cells (example, starting from logic LOW)"],
                "rows": [
                    ["0", "yes (always)", "no",  "11 or 00 — two like cells per bit-time"],
                    ["1", "yes (always)", "yes", "10 or 01 — two opposite cells per bit-time"],
                ],
            },
        })
        f.setdefault("preamble_table", {
            "header_columns": ["Preamble", "BMC cells (following logic LOW)", "BMC cells (following logic HIGH)", "Marks"],
            "rows": [
                ["Z (block start)",          "11101000", "00010111", "Channel-A subframe start of frame 1 of a block (= block boundary)"],
                ["X (channel-A mid-block)",  "11100010", "00011101", "Channel-A subframe start of frames 2-192 within a block"],
                ["Y (channel-B)",            "11100100", "00011011", "Channel-B subframe start (every frame)"],
            ],
        })
        f.setdefault("subframe_field_layout_table", {
            "header_columns": ["Field", "Bit offset", "Width (bits)", "Purpose"],
            "rows": [
                ["Preamble",         "0",  4,  "X / Y / Z — BMC-violating long pulse for alignment"],
                ["Aux",              "4",  4,  "Optional 4 LSBs of 24-bit audio sample OR ancillary"],
                ["Audio sample",     "8",  20, "20-bit audio (LSB at bit 8, MSB at bit 27)"],
                ["Validity (V)",     "28", 1,  "0 = valid for D/A; 1 = not valid (e.g. IEC 61937)"],
                ["User data (U)",    "29", 1,  "One user-data bit (aggregates to 192 bits/channel/block)"],
                ["Channel status (C)", "30", 1, "One channel-status bit (aggregates to 192 bits/channel/block)"],
                ["Parity (P)",       "31", 1,  "Even parity over bits 4-30 of the same subframe"],
            ],
        })
        f.setdefault("frame_and_block_structure_table", {
            "header_columns": ["Unit", "Composition"],
            "rows": [
                ["Subframe", "32 BMC-bit-times = 64 BMC cells"],
                ["Frame",    "2 subframes = channel-A + channel-B"],
                ["Block",    "192 frames = 384 subframes; first frame's channel-A subframe uses preamble Z (block boundary)"],
            ],
        })
        f.setdefault("channel_status_word_layout_consumer", {
            "summary": "S/PDIF (Consumer) 192-bit channel-status word; the entire word is identical for channel A and channel B in consumer mode. The 192-bit word is divided into 12 sub-words of 16 bits each, with the first 16 bits being a control code.",
            "header_columns": ["Byte", "Bit(s)", "Unset (0)", "Set (1)"],
            "rows": [
                [0,    0,      "Consumer (S/PDIF)",                       "Professional (AES3) — changes meaning to AES3 channel-status word"],
                [0,    1,      "Normal PCM",                              "Compressed data"],
                [0,    2,      "Copy restrict",                           "Copy permit"],
                [0,    3,      "2 channels",                              "4 channels"],
                [0,    4,      "—",                                       "—"],
                [0,    5,      "No pre-emphasis",                         "Pre-emphasis 50/15 µs"],
                [0,    "6-7",  "Mode — defines subsequent bytes; values other than zero are undefined", "—"],
                [1,    "0-6",  "Audio source category code (general, CD-DA, DVD, etc.)", "—"],
                [1,    7,      "L-bit — original / copy (only defined when byte 0 bit 2 = 0). Polarity depends on category: DVD-R / DVD-RW: allow recording if 1; CD-R / CD-RW / DVD: allow if 0; plain CD-DA: L-bit undefined, recording prevented by alternating bit 2 at 4-10 Hz.", "—"],
                [2,    "0-3",  "Source number", "—"],
                [2,    "4-7",  "Channel number", "—"],
                [3,    "0-3",  "Sampling frequency code (0000 = 44.1 kHz, 0100 = 48 kHz, 1100 = 32 kHz, etc.)", "—"],
                [3,    "4-5",  "Clock accuracy (10 = 50 ppm, 00 = 1000 ppm, 01 = variable pitch — requires compatible receiver)", "—"],
                [3,    "6-7",  "Undefined", "—"],
                [4,    0,      "Word length 20 bits",                     "Word length 24 bits"],
                [4,    "1-3",  "Sample length (0 = undefined; 1-4 = word length minus 1-4 bits; 5 = full word length)", "—"],
                [4,    "4-7",  "Undefined", "—"],
                ["5-10","0-7", "EAN-13 code (possibly in binary-coded decimal)", "—"],
                [11,   "0-3",  "EAN-13 continuation", "—"],
                [11,   "4-7",  "Undefined / padding on 13-digit EAN code", "—"],
                ["12-13","0-7","Undefined", "—"],
                [14,   "0-3",  "Undefined", "—"],
                [14,   "4-7",  "ISRC start (ISRC = 2 alphabetic + 3 alphanumeric + 7 numeric characters ≈ 7.5 bytes)", "—"],
                ["15-21","0-7","ISRC continuation", "—"],
                ["22-23","0-7","Undefined", "—"],
            ],
        })
        f.setdefault("sample_frequency_code_table", {
            "header_columns": ["Code (byte 3 bits 0-3)", "Sampling frequency"],
            "rows": [
                ["0000", "44.1 kHz"],
                ["0100", "48 kHz"],
                ["1100", "32 kHz"],
            ],
            "note": "Other codes (88.2 / 96 / 176.4 / 192 kHz) are defined by the underlying IEC 60958 spec but not enumerated in the Wikipedia consumer-channel-status excerpt; receivers typically implement the full table.",
        })
        f.setdefault("clock_accuracy_code_table", {
            "header_columns": ["Code (byte 3 bits 4-5)", "Accuracy"],
            "rows": [
                ["10",   "50 ppm"],
                ["00",   "1000 ppm"],
                ["01",   "Variable pitch (requires compatible receiver)"],
            ],
        })
        f.setdefault("word_length_code_table", {
            "header_columns": ["Code (byte 4 bit 0)", "Word length"],
            "rows": [
                ["0", "20 bits"],
                ["1", "24 bits"],
            ],
        })
        f.setdefault("sample_length_code_table", {
            "header_columns": ["Code (byte 4 bits 1-3)", "Sample length"],
            "rows": [
                ["000", "Undefined"],
                ["001", "Word length minus 1 bit"],
                ["010", "Word length minus 2 bits"],
                ["011", "Word length minus 3 bits"],
                ["100", "Word length minus 4 bits"],
                ["101", "Full word length"],
            ],
        })
        f.setdefault("comparison_aes3_vs_spdif_table", {
            "header_columns": ["Parameter", "AES3 Balanced", "AES3 Unbalanced", "S/PDIF Copper (coax)", "S/PDIF Optical (Toslink)"],
            "rows": [
                ["Cabling",            "110 Ω STP",       "75 Ω coaxial",    "75 Ω coaxial",   "Optical fibre"],
                ["Connector",          "3-pin XLR",       "BNC",             "RCA or BNC",     "TOSLINK"],
                ["Output level",       "2–7 V peak-to-peak", "1.0–1.2 V peak-to-peak", "0.5–0.6 V peak-to-peak", "—"],
                ["Min. input level",   "0.2 V",           "0.32 V",          "0.2 V",          "—"],
                ["Max. distance",      "1000 m",          "100 m",           "10 m",           "10 m"],
                ["Modulation",         "Biphase mark code", "Biphase mark code", "Biphase mark code", "Biphase mark code"],
                ["Subcode information","ASCII id. text",  "ASCII id. text",  "SCMS copy protection info", "SCMS copy protection info"],
                ["Audio bit depth",    "24 bits",         "24 bits",         "20 bits (24 bits optionally)", "20 bits (24 bits optionally)"],
            ],
        })
        f.setdefault("iec_61937_encapsulation_table", {
            "header_columns": ["Field", "Purpose"],
            "rows": [
                ["Channel-status byte 0 bit 1 = 1", "Indicates non-linear-PCM (compressed) data."],
                ["V (Validity) = 1 on every audio subframe", "Forbids feeding the audio-sample field directly to a PCM DAC."],
                ["IEC 61937 preamble (two 16-bit sync words)", "Marks the start of each compressed-data burst."],
                ["Bitstream type / validity / number / length", "Encoded inside the IEC 61937 preamble for downstream decoder routing."],
                ["Padding (zeros)", "Fills the IEC 60958 block so timing matches the IEC 60958 carrier rate."],
                ["Carrier rate ≈ 64 × symbol rate", "Maintains the same 64-cells-per-frame relationship as PCM mode."],
            ],
        })
        if _empty(f.get("tables")):
            f["tables"] = [
                "Bi-phase Mark Code rule (one transition per bit boundary; mid-bit transition encodes '1')",
                "Preamble table (X / Y / Z, 8 BMC cells each, in both starting-polarity variants)",
                "Subframe field layout (Preamble + Aux + Audio + V + U + C + P, 32 bit-times)",
                "Frame / block structure (2 subframes / 192 frames)",
                "Consumer channel-status word byte layout (24 bytes × 8 bits = 192 bits)",
                "Sample-frequency code table (byte 3 bits 0-3)",
                "Clock-accuracy code table (byte 3 bits 4-5)",
                "Word-length code table (byte 4 bit 0)",
                "Sample-length code table (byte 4 bits 1-3)",
                "AES3-vs-S/PDIF physical-layer comparison",
                "IEC 61937 compressed-audio encapsulation rules",
            ]
        d["fields"] = f
        _write(p, d)

    # L16 — Compliance properties
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("must_have_properties", [
            "Bi-phase Mark Code line encoding with a transition at every data-bit boundary, mid-bit transition for '1', no mid-bit transition for '0'.",
            "Subframe length exactly 32 BMC bit-times = 64 BMC cells.",
            "Frame = 2 subframes (channel A + channel B); block = 192 frames.",
            "Preamble X at start of channel-A subframe (frames 2-192 of a block).",
            "Preamble Y at start of channel-B subframe (every frame).",
            "Preamble Z at start of channel-A subframe of frame 1 of every block (one Z per 192 frames).",
            "Each preamble = 8 BMC cells that deliberately violate BMC's 'transition at every bit boundary' rule (three-cell-long pulse).",
            "Audio sample occupies bits 8-27 (20-bit field); MSB at bit 27.",
            "Optional 24-bit mode uses Aux (bits 4-7) as the 4 lowest LSBs of the audio sample.",
            "Validity bit V (bit 28) = 0 for samples valid for D/A conversion.",
            "User-data bit U (bit 29) aggregates over 192 subframes per channel into a 192-bit user-data word.",
            "Channel-status bit C (bit 30) aggregates over 192 subframes per channel into a 192-bit channel-status word.",
            "Channel-status word is IDENTICAL between channel A and channel B in consumer S/PDIF.",
            "Parity bit P (bit 31) = even parity over bits 4-30 of the same subframe.",
            "Channel-status byte 0 bit 0 = 0 for consumer S/PDIF (= 1 for professional AES3).",
            "Channel-status byte 0 bit 1 = 0 for PCM (= 1 for IEC 61937 compressed data).",
            "Coaxial S/PDIF: 75 Ω cable, 0.5-0.6 Vpp transmitter output, 0.2 V minimum receiver input, RCA or BNC connector.",
            "Optical S/PDIF: Toslink (JIS F05 / EIAJ) connector and fibre, identical content to coaxial.",
            "Maximum cable distance ~10 m for both coax and Toslink.",
            "Sample frequency declared via channel-status byte 3 bits 0-3 (0000 = 44.1 kHz, 0100 = 48 kHz, 1100 = 32 kHz, ...).",
            "Word length declared via channel-status byte 4 bit 0 (0 = 20-bit, 1 = 24-bit).",
            "IEC 61937 compressed payload uses two 16-bit sync words in the preamble + bitstream type/length/validity + padding to match IEC 60958 block timing; channel-status bit 1 = 1; V = 1 on every audio subframe.",
        ])
        f.setdefault("must_not_have_properties", [
            "Subframes with arbitrary length other than 32 bit-times.",
            "Blocks with arbitrary length other than 192 frames.",
            "Audio sample passed to PCM DAC when V = 1 (must be muted or routed to IEC 61937 demux).",
            "Different 192-bit channel-status words on channel A vs channel B in CONSUMER mode (allowed in professional AES3 only).",
            "Parity violation (parity bit P not equal to the even-parity sum of bits 4-30) without flagging.",
            "Coax transmitter output below 0.5 V or above 0.6 V peak-to-peak (out of consumer S/PDIF range).",
            "Coax receiver minimum input below 0.2 V (must accept down to 0.2 V).",
            "Hard-coded preamble polarity that fails to lock on an inverted line (BMC is polarity-independent — both starting-polarity variants of each preamble must be detected).",
            "Direct routing of recovered S/PDIF clock into a DAC without re-clocking (induces jitter).",
        ])
        f.setdefault("compliance_failure_modes", [
            {"mode": "Preamble misdetection",            "trigger": "BMC bit errors or transmitter inserting a non-spec preamble pattern → receiver loses subframe alignment."},
            {"mode": "Parity error storm",                "trigger": "Cable too long / impedance mismatch / poor optical alignment → repeated bit errors → continuous P-bit mismatches; audio drops or mutes."},
            {"mode": "Sample-rate mis-declaration",       "trigger": "Channel-status byte 3 bits 0-3 inconsistent with the measured BMC rate → receiver displays wrong sample rate / refuses lock."},
            {"mode": "IEC 61937 mis-routing",             "trigger": "Channel-status bit 1 = 1 but V = 0 (or vice-versa) → receiver may either pass compressed data to PCM DAC (loud noise) or fail to demux the compressed stream."},
            {"mode": "Channel-A / channel-B status mismatch", "trigger": "Consumer S/PDIF transmitter erroneously sends different bits in C on channel A vs channel B → conforming receiver flags inconsistency."},
            {"mode": "Excessive jitter",                  "trigger": "Receiver clocks DAC directly from recovered S/PDIF clock → audible jitter, harmonic distortion in the analog output."},
            {"mode": "Toslink LED-fall jitter",            "trigger": "Toslink LED's slow turn-off introduces edge jitter that BMC clock recovery does not fully suppress → propagates into recovered audio."},
        ])
        f.setdefault("min_clock_constraint",
            "Minimum bit-rate = 64 × 32 kHz = 2.048 Mb/s data (4.096 MBMC cells/s). Maximum standard rate = 64 × 192 kHz = 12.288 Mb/s data (24.576 MBMC cells/s). Frame carrier rate equals sample rate. Variable-pitch operation (byte 3 bits 4-5 = 01) requires a compatible receiver.")
        f.setdefault("reset_behavior_compliance",
            "IEC 60958 does not mandate a specific reset state; receivers must tolerate startup transients, lock to BMC transitions on power-on, re-acquire subframe alignment on the next valid preamble, and mute the DAC until block alignment (next Z) is achieved.")
        d["fields"] = f
        _write(p, d)

    # L17 — Channel / signal catalog (force-overwrite for S/PDIF shape)
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["channels"] = [
            {"name": "SPDIF_TX (coax)",   "direction_transmitter": "output", "direction_receiver": "input", "purpose": "Single-wire 75 Ω coaxial output carrying BMC-encoded IEC 60958 type II stream.",                   "active_levels": "0.5-0.6 V peak-to-peak at the transmitter; 0.2 V minimum at the receiver", "idle_level": "Implementation-defined (often continuous BMC stream with audio = 0 and V = 1; otherwise driven LOW or HIGH)"},
            {"name": "SPDIF_RX (coax)",   "direction_transmitter": "—",       "direction_receiver": "input", "purpose": "Single-wire 75 Ω coaxial input; the receiver-side counterpart of SPDIF_TX (in transceiver ICs, the same pin or its differential).", "active_levels": "0.2 V minimum input level; 75 Ω termination at the receiver", "idle_level": "Implementation-defined"},
            {"name": "SPDIF (Toslink Tx)", "direction_transmitter": "output", "direction_receiver": "input", "purpose": "Toslink (JIS F05 / EIAJ optical) LED driver carrying BMC-encoded IEC 60958 type II stream.",   "active_levels": "Optical ON / OFF; light pulses correspond to BMC cell levels", "idle_level": "Implementation-defined (LED stays modulating with silence frames or turns off)"},
            {"name": "SPDIF (Toslink Rx)", "direction_transmitter": "—",      "direction_receiver": "input", "purpose": "Toslink optical receiver photodiode + comparator; converts optical pulses back to digital BMC stream.", "active_levels": "Light pulses; receiver thresholds the photodiode output to recover the BMC signal", "idle_level": "Implementation-defined"},
        ]
        f["global_signals"] = []
        f["channel_counts"] = {
            "wire_count_per_link":     1,
            "data_lines":              1,
            "clock_lines":             0,
            "control_lines":           0,
            "audio_channels_per_link": 2,
            "external_pins_total":     1,
            "comment":                 "S/PDIF is a single-wire (coax) or single-fibre (optical) self-clocked link. The bit clock is embedded in the BMC line code; no separate clock or chip-select pin exists.",
        }
        f.setdefault("ordering_rules", {
            "bit_order_within_audio_sample": "LSB at bit 8, MSB at bit 27 of the subframe (audio is LSB-first within the 20-bit field).",
            "subframe_order_within_frame":   "Channel A (preamble X or Z) first, then channel B (preamble Y).",
            "frame_order_within_block":      "Frame 1 (Z preamble on channel A) → Frame 2 (X) → ... → Frame 192 (X); next block starts with Z again.",
            "channel_status_bit_order":      "Bit 0 of byte 0 is the FIRST C-bit emitted after the block boundary (Z); bit 7 of byte 23 is the LAST C-bit of the block.",
        })
        f["dependency_graph"] = {
            "common_rule": "Transmitter drives BMC-encoded subframes continuously. Each subframe carries Preamble + Aux + Audio + V + U + C + P, computed by the transmitter and verified by the receiver. The receiver recovers bit clock from BMC transitions and uses X / Y / Z preambles to align subframe / frame / block boundaries.",
            "data_dependency": "Each subframe must end with a parity bit P that is even over bits 4-30; each block must start with a Z preamble; the 192-bit channel-status word is reassembled at every block boundary.",
        }
        f["handshake_pairs"] = [
            {"name": "BMC_CLK_RECOVERY",       "from": "transmitter", "to": "receiver", "rule": "Transmitter inserts ≥ 1 transition per data-bit; receiver recovers the bit clock from these transitions."},
            {"name": "PREAMBLE_ALIGN",         "from": "transmitter", "to": "receiver", "rule": "Transmitter emits one of X / Y / Z at every subframe start; receiver pattern-matches the long pulse to align subframe + frame + block counters."},
            {"name": "PARITY_CHECK",            "from": "transmitter", "to": "receiver", "rule": "Transmitter sets P so that bits 4-30 + P have even parity; receiver verifies and reports."},
            {"name": "VALIDITY_GATE",           "from": "transmitter", "to": "receiver", "rule": "Transmitter sets V = 1 to forbid PCM DAC consumption (e.g. for IEC 61937 mode or fault); receiver mutes its DAC and routes the audio-sample field accordingly."},
            {"name": "CHANNEL_STATUS_ACCUM",    "from": "transmitter", "to": "receiver", "rule": "Transmitter emits 1 channel-status bit per subframe; receiver shifts them into a 192-bit channel-status accumulator per channel and re-parses on every block boundary."},
        ]
        d["fields"] = f
        _write(p, d)

    # L18 — Interconnect / topology (force-overwrite for S/PDIF shape)
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f["topology_type"] = (
            "Point-to-point single-wire (coax) or single-fibre (optical) "
            "unidirectional self-clocked digital-audio link. One transmitter "
            "drives one receiver per link; bit clock is embedded in the BMC "
            "line code and recovered by the receiver.")
        f["supported_topologies"] = [
            {"name": "Single coaxial S/PDIF link (RCA orange or BNC)",        "description": "Most common consumer setup: one 75 Ω coaxial cable between source (e.g. CD / Blu-ray / DVD player, sound card) and sink (A/V receiver / DAC). RCA connector typically colour-coded orange to distinguish from composite video. Max distance ~10 m."},
            {"name": "Single Toslink optical S/PDIF link",                    "description": "One Toslink (JIS F05 / EIAJ) fibre-optic cable; identical content to coax; provides electrical isolation that breaks ground loops. Max distance ~10 m."},
            {"name": "Daisy-chained receiver-then-transmitter",                "description": "An S/PDIF transceiver IC may receive the stream, re-clock it, and re-transmit it onwards. Each hop introduces additional jitter; chaining beyond 1-2 hops is uncommon for high-fidelity audio."},
            {"name": "Coax-to-optical converter",                              "description": "A passive (or buffered) RCA-to-Toslink converter changes the physical medium without altering the bitstream content."},
            {"name": "Optical splitter",                                      "description": "Optical Y-splitter or dual-output Toslink transmitter can drive multiple receivers; each receiver locks independently to the same BMC stream."},
        ]
        f["master_slave_role_summary"] = [
            {"role": "Transmitter (source)", "description": "Rate master. Generates BMC-encoded subframes, accumulates 192-bit channel-status and user-data words, computes parity, and drives the coax line or Toslink LED."},
            {"role": "Receiver (sink)",      "description": "Rate slave. Recovers bit clock from BMC transitions, detects X / Y / Z preambles, captures audio + V + U + C + P bits, parses the 192-bit channel-status word per block, and forwards PCM samples to a DAC (or compressed bitstream to an IEC 61937 demux)."},
            {"role": "Transceiver",          "description": "Combines transmitter and receiver functions in a single IC; can re-clock a received stream and emit it onwards, or implement bidirectional audio links (uncommon for pure consumer S/PDIF)."},
        ]
        f["interconnect_role"] = (
            "There is no protocol-layer interconnect (no router / bridge / "
            "arbiter). The link is a single point-to-point connection "
            "between one transmitter and one receiver. Multi-source mixing "
            "is done outside the S/PDIF protocol (a sound card or A/V "
            "receiver does the mixing internally and re-encodes a single "
            "S/PDIF stream).")
        f["ordering_guarantees"] = {
            "within_an_audio_sample":     "Audio sample is sent LSB-first within bits 8-27 of the subframe; receiver reassembles into a 20-bit (or 24-bit with Aux) value with the MSB in the highest bit position.",
            "within_a_subframe":          "Bit 0 (preamble start) first, bit 31 (parity) last.",
            "across_subframes_in_frame":  "Channel-A subframe first (preamble X or Z), then channel-B subframe (preamble Y).",
            "across_frames_in_block":     "Frame 1 (Z preamble on channel A) → Frame 192 (X preamble on channel A); 192 C-bits per channel per block.",
            "channel_status_word":        "Bit 0 of byte 0 = first C-bit after Z preamble; bit 7 of byte 23 = last C-bit of the block. Identical between channel A and channel B in consumer mode.",
        }
        f.setdefault("memory_vs_peripheral_regions",
            "Not applicable — S/PDIF is a streaming-only protocol; no addressable memory or peripheral regions.")
        f.setdefault("device_classification", {
            "CD_DVD_BluRay_player":   "Transmitter. Drives a coax or Toslink output carrying PCM (CD) or IEC 61937 compressed (DVD / BD).",
            "PC_sound_card_or_DAW":   "Transmitter and/or receiver. Provides S/PDIF I/O for digital audio interchange.",
            "AV_receiver":            "Receiver. Accepts multiple S/PDIF inputs and a Dolby/DTS decoder; demuxes IEC 61937 bursts.",
            "external_DAC":           "Receiver. Reconstructs analog audio from PCM S/PDIF, often with re-clocking to suppress jitter.",
            "TV_or_set_top_box":      "Transmitter. Emits Dolby Digital / DTS bitstreams over S/PDIF to an external A/V receiver.",
            "audio_codec_chip":       "Receiver + S/PDIF transceiver IP combined with an internal DAC + ADC.",
        })
        f.setdefault("default_signal_values_evidence_tables", [
            "Spec excerpt — 'Hardware specifications' (coaxial RCA / BNC 75 Ω 0.5-0.6 Vpp; Toslink optical; max distance ~10 m)",
            "Spec excerpt — 'Protocol specifications' (BMC line coding; subframe / frame / block; X / Y / Z preambles)",
            "Spec excerpt — S/PDIF control word components table (192-bit channel-status word layout)",
            "Spec excerpt — 'Data framing' (block = 192 frames; subframe = 20 / 24-bit audio)",
            "Spec excerpt — 'IEC 61937 encapsulation' (compressed audio rules)",
            "Spec excerpt — 'Limitations' (receiver does not control data rate; clock recovery induces jitter)",
        ])
        d["fields"] = f
        _write(p, d)

    # L19 — PDK constraints
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("constraints_present", False)
        f["notes"] = (
            "S/PDIF (IEC 60958 type II) is a wire-level streaming protocol; "
            "it does not specify PDK / SDC / floorplan constraints at the "
            "protocol layer. Per-IP integration constraints (pad type, "
            "transformer-coupled coax driver, Toslink LED driver, PLL "
            "placement / clock-tree budget for BMC clock recovery, "
            "receiver impedance matching at 75 Ω) live in the SoC "
            "integration spec and the chosen S/PDIF transmitter / receiver "
            "IP, not in IEC 60958 itself.")
        d["fields"] = f
        _write(p, d)

    # L20 — DFT / scan
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("dft_present", False)
        f["notes"] = (
            "IEC 60958 type II (S/PDIF) does not specify DFT / scan / "
            "BIST. Concrete S/PDIF transmitter / receiver IPs from modern "
            "vendors add standard scan + JTAG at the integrator level. "
            "Useful design-for-test hooks for S/PDIF specifically include: "
            "a loopback path from internal TX BMC stream into RX "
            "clock-recovery for self-test, a PRBS / sine-wave PCM test "
            "pattern generator, a BMC bit-error injector for receiver "
            "tolerance test, and snapshot registers for the 192-bit "
            "channel-status word.")
        d["fields"] = f
        _write(p, d)

    # L21 — Power intent
    p = gd / "L21_POWER_INTENT.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("power_intent_present", False)
        f["low_power_modes_summary"] = {
            "Mute_with_carrier":     "Transmitter continues emitting BMC frames but with audio = 0 and V = 1, keeping the receiver locked. Saves source DSP work but not link power.",
            "Stop_carrier":           "Transmitter halts BMC transitions entirely. Receiver loses lock and reports loss-of-signal. Lowest link power but largest re-lock latency on resume.",
            "IEC_61937_null_burst":  "In IEC 61937 mode, when the compressed encoder has no payload, transmitter inserts null bursts that keep the channel-status word valid and the receiver locked without consuming compressed-decoder cycles.",
        }
        f["notes"] = (
            "IEC 60958 does not define formal sleep / suspend modes. "
            "Power management is deferred to the SoC plus the connected "
            "transmitter / receiver IPs. Toslink LED driving dominates "
            "transmitter power; coax driver-level (0.5-0.6 Vpp into 75 Ω) "
            "is comparatively modest. Receivers can save power by gating "
            "the PLL / clock-recovery loop when no signal is present, and "
            "by clock-gating the channel-status decoder between block "
            "boundaries.")
        d["fields"] = f
        _write(p, d)

    # L23 — Security
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if p.is_file():
        d = _read(p)
        f = d.get("fields") or {}
        f.setdefault("security_requirements_present", False)
        f["notes"] = (
            "S/PDIF (IEC 60958 type II) and the companion IEC 61937 "
            "compressed-audio encapsulation do not provide confidentiality, "
            "integrity, or authentication at the protocol layer. The audio "
            "payload is in plaintext (PCM) or in standardized compressed "
            "formats (Dolby AC-3 / DTS / MP3 / AAC / Dolby TrueHD / E-AC-3 "
            "/ ATRAC / WMA Pro) that are not encrypted at the S/PDIF "
            "level. The only access-control-like mechanism is SCMS "
            "(Serial Copy Management System): channel-status byte 0 bit 2 "
            "= copy restrict / copy permit, byte 1 bit 7 = L-bit (original "
            "/ copy), and the CD-DA convention of alternating byte 0 bit 2 "
            "at 4-10 Hz to prevent recording. SCMS is an advisory "
            "rights-management hint, not a cryptographic protection — "
            "non-compliant receivers can simply ignore the flags.")
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
def is_spdif(blob: str) -> bool:
    """Content-only `spdif` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT S/PDIF). ---
    # The structural S/PDIF signature below — in particular the loose
    # "IEC 60958" + "audio" branch — is necessary but NOT sufficient: A2B
    # (Analog Devices Automotive Audio Bus, AD24xx) is an audio-family bus
    # that cites IEC 60958 / S/PDIF (and AES3) as comparison interfaces and
    # tunnels local audio, so its generated L-docs carry incidental
    # "IEC 60958" + "audio" tokens that trip that branch and have the generic
    # S/PDIF synth inject biphase-mark / subframe / preamble text into an A2B
    # spec. Defer when the blob's DOMINANT subject is A2B (a sibling MUTEX,
    # mirroring is_a2b's own S/PDIF-primary defer — general, content-only, no
    # chip/SKU/benchmark literal as detection logic).
    #
    # A2B's distinctive structural signature (absent from every real S/PDIF
    # spec): a sample-rate-locked SUPERFRAME with downstream + upstream
    # portions, a MAIN/SUB node hierarchy with node discovery/addressing,
    # PHANTOM POWER over the bus, and the AD24xx transceiver family. S/PDIF is
    # a point-to-point biphase-mark link with NONE of these — no superframe,
    # no node discovery, no phantom power, no daisy-chain transceiver — so
    # deferring on this conjunction never suppresses a real S/PDIF spec.
    _a2b_name = "automotive audio bus" in low
    _a2b_xcvr = ("ad24xx" in low or "ad242x" in low
                 or "ad2410" in low or "ad2420" in low or "ad2425" in low)
    _a2b_superframe = ("superframe" in low
                       and "downstream" in low and "upstream" in low)
    _a2b_node_hier = (("main node" in low or "master node" in low)
                      and ("sub node" in low or "sub nodes" in low
                           or "slave node" in low or "slave nodes" in low)
                      and ("node discovery" in low or "node address" in low
                           or "discovery" in low))
    _a2b_phantom = "phantom power" in low
    a2b_primary = (
        (_a2b_name or _a2b_xcvr)
        and (_a2b_superframe or _a2b_node_hier or _a2b_phantom))
    if a2b_primary:
        return False

    return bool(
        ("SPDIF" in blob.upper() and "biphase" in low
         and "subframe" in low
         and "preamble" in low)
        or ("IEC 60958" in blob and "audio" in low)
        or ("S/PDIF" in blob and "Toslink" in blob))
