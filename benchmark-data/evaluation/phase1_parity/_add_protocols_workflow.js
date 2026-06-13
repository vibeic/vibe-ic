export const meta = {
  name: 'add-phase1-protocols',
  description: 'Add 5 new phase1 benchmark protocols (LPC/USB-PD/Interlaken/MDIO/SGMII) each closed-looped to gated parity 0 via the generic auto-dispatch, then adversarially reviewed',
  phases: [
    { title: 'Author', detail: 'spec + 24-doc gold + drop-in synth, close-loop to gated 0 + self no-misfire' },
    { title: 'Review', detail: 'adversarial: gold substance + detector strictness + content faithfulness' },
  ],
}

const REPO = '/home/reyerchu/vibe-ic'
const PROG = `${REPO}/vibe-ic-marketplace/plugins/vibe-ic/programs`
const BENCH = `${REPO}/benchmark_phase1`

const COMMON = `
You are adding ONE new protocol benchmark to the Vibe-IC phase1 corpus and driving it to
gated L-doc parity 0 via the generic drop-in auto-dispatch shipped in v0.2.13.

ABSOLUTE PATHS:
  REPO  = ${REPO}
  PROG  = ${PROG}                (plugin programs dir; put the synth helper here)
  BENCH = ${BENCH}               (benchmark folder root)

STUDY THE EXEMPLAR FIRST (do this before writing anything):
  - ${PROG}/espi_protocol_synth.py        (the reference drop-in synth: AUTO_DISPATCH=True,
      IC_NAME, is_espi(blob) strict detector with sibling MUTEX, apply_espi_synth merging
      canonical content into _FLAT_DOCS and _FIELDS_DOCS)
  - ${BENCH}/espi/phase1/claude_extracted/*.json   (the 24-doc gold shape per L-doc)
  - ${BENCH}/espi/phase1/input_doc/Intel_eSPI_Base_Specification.txt  (input spec shape)
  - ${PROG}/tests/test_espi_protocol_synth.py      (the test shape)

WHAT "gold" MEANS: claude_extracted/L*.json is a FAITHFUL, INDEPENDENT extraction of the spec
into the 24 L-docs (L1,L2,L3,L4,L5,L6,L7,L8_RTL_CONSTANTS,L8_TIMING_WAVEFORM,L9,L10,L11,L12,L13
flat; L14..L23 under a "fields" wrapper). Author the gold FROM THE SPEC, as a careful engineer
would — real protocol facts only, NEVER fabricated, NEVER under-authored to trivially match.
The synth then reproduces the same canonical facts. Both must be faithful to the real protocol.

STEP-BY-STEP:
1. Create dirs:
     mkdir -p ${BENCH}/<proto>/input/docs ${BENCH}/<proto>/phase1/input_doc ${BENCH}/<proto>/phase1/claude_extracted ${BENCH}/<proto>/phase1/generated_docs
2. Write the input spec text (a faithful, substantial technical spec — sections, signals, frame
   format, encodings, timing) to BOTH:
     ${BENCH}/<proto>/input/docs/<SpecName>.txt   AND   ${BENCH}/<proto>/phase1/input_doc/<SpecName>.txt
3. Author the 24-doc gold into ${BENCH}/<proto>/phase1/claude_extracted/ (match the espi gold
   shapes: flat docs vs "fields"-wrapped docs exactly). Validate every file is valid JSON.
4. Author ${PROG}/<proto>_protocol_synth.py modeled on espi_protocol_synth.py:
     - AUTO_DISPATCH = True ; IC_NAME = "<canonical name>"
     - is_<proto>(blob): content-only detector. MUST require a protocol-specific NAME TOKEN as a
       NECESSARY condition (so it can never fire on another protocol's spec), PLUS a structural
       quorum. Include explicit MUTEX deferral vs the named siblings in the brief.
     - apply_<proto>_synth(gd, flag, ic_name): no-op if not flag; else merge canonical content into
       the flat docs (top level) and fields docs (under "fields"), set ic_name. Same _FLAT_DOCS /
       _FIELDS_DOCS split as espi.
5. Close the loop:
     cd ${BENCH}/<proto> && PYTHONPATH=${PROG} python3 ${PROG}/phase1_doc_one_shot_runner.py "$PWD"
     (first run extracts text from input/docs/; confirm the runner prints
      "auto-dispatch fired: <proto>". then:)
     PYTHONPATH=${PROG} python3 ${PROG}/l_doc_parity_diff.py \\
        --program-dir ${BENCH}/<proto>/phase1/generated_docs \\
        --agent-dir   ${BENCH}/<proto>/phase1/claude_extracted \\
        --source ${BENCH}/<proto>/phase1/input_doc/<SpecName>.txt --out-json /tmp/p_<proto>.json
     Compute GATED = sum over docs with agent_bytes>0 of (absent_in_program+hallucinated+value_mismatch).
     Iterate: for each ABSENT_IN_PROGRAM finding, add the missing key to the synth canonical content
     (or align its value); for HALLUCINATED, remove the fabricated key from the synth; for
     VALUE_MISMATCH, fix the synth value to match the spec/gold. Re-run until GATED == 0.
     (SHAPE_MISMATCH and list-only diffs are NOT gated — ignore per R28/R32.)
6. Self no-misfire: confirm is_<proto>(blob) returns False for these sibling specs (read each
   sibling's phase1/input_doc/*.txt): <SIBLINGS>. If it fires on any, tighten the detector.
7. Write ${PROG}/tests/test_<proto>_protocol_synth.py modeled on test_espi_protocol_synth.py
   (auto-dispatch contract + detector fires-on-self / defers-on-siblings + apply merges canonical).
   Run: PYTHONPATH=${PROG} python3 -m pytest ${PROG}/tests/test_<proto>_protocol_synth.py -q

DO NOT edit phase1_doc_one_shot_runner.py or any other protocol's files. Your synth is a pure
drop-in. Keep the detector NAME-TOKEN-gated so concurrent sibling agents cannot cross-fire.

Return STRICTLY this JSON: {proto, ic_name, gated, misfire_siblings_fired (list), tests_passed (int),
spec_file, notes}. gated MUST be 0 and misfire_siblings_fired MUST be [] for success.
`

const PROTOS = [
  {
    proto: 'lpc', specName: 'Intel_LPC_Interface_Specification',
    siblings: ['espi','spi','qspi_ospi'],
    brief: `LPC = Intel Low Pin Count Interface Specification 1.1 (2002). The PARALLEL predecessor that
eSPI replaces. Signals: LAD[3:0] multiplexed address/data, LFRAME# (frame/abort), LCLK (33 MHz PCI
clock), LRESET#. Optional: LDRQ# (DMA request), SERIRQ (serialized IRQ), CLKRUN#, PME#, LSMI#.
Each cycle: START field (4 bits on LAD; 0x0000 = target cycle, 0x0010/0x0011 = bus-master grant,
0x1111 = firmware, 0x1110 = stop/abort) driven while LFRAME# low, then CYCTYPE+DIR (cycle type:
I/O read/write, memory read/write, DMA read/write, plus direction), ADDR nibbles, TAR (turnaround),
SYNC field (ready/short-wait/long-wait/error: 0000 ready, 0101 short, 0110 long, 1010 error), DATA
nibbles (LSN then MSN), final TAR. Cycle types: I/O (16-bit addr), Memory (32-bit addr), DMA
(8237-compatible, DMA channels via LDRQ#), Bus Master, Firmware Memory (28-bit addr, IDSEL).
MUTEX vs eSPI: eSPI is the SERIAL successor with 4 logical channels (Peripheral/VW/OOB/Flash),
GET/SET_CONFIGURATION, ESPI_ALERT#, CRC — LPC has NONE of those. is_lpc MUST require name token
("low pin count" or "lpc") AND the LAD[3:0]+LFRAME# signal pair AND the START/CYCTYPE/SYNC field
model, and MUST defer if the eSPI four-channel signature is present.`,
  },
  {
    proto: 'usb_pd', specName: 'USB_Power_Delivery_Specification',
    siblings: ['usb','usb4','i2c'],
    brief: `USB-PD = USB Power Delivery Specification Rev 3.1 (USB-IF). Power/data-role negotiation over the
USB Type-C CC (Configuration Channel) wire — DISTINCT from USB 2.0 data (D+/D-) and USB4 tunneling.
Signals: CC1/CC2 (configuration channel), VBUS, VCONN. Line code: BMC (Biphase Mark Coding) on CC at
300 kbaud. Packet framing: SOP / SOP' / SOP'' ordered sets (K-codes Sync-1/Sync-2/Sync-3, RST-1/RST-2),
then 16-bit Message Header, data objects, CRC-32, EOP. Roles: Source / Sink (power), DFP/UFP and
later Port Data Role swaps via DR_Swap, PR_Swap, VCONN_Swap. Power: PDO (Power Data Object) advertised
by Source (Fixed Supply, Variable Supply, Battery, Programmable Power Supply / PPS / APDO); Sink issues
RDO (Request Data Object) selecting a PDO + operating current. Message classes: Control (GoodCRC,
Accept, Reject, PS_RDY, Get_Source_Cap, Soft_Reset…), Data (Source_Capabilities, Request, Sink_Cap,
Vendor_Defined_Message/VDM), Extended. Hard Reset / Soft Reset / Cable Reset. Contract negotiation:
Source_Capabilities -> Request -> Accept -> PS_RDY. MUTEX: NOT USB 2.0 (D+/D-, NRZI, PID, endpoints,
SOF) and NOT USB4 (40 Gbps, tunneling, routers). is_usb_pd MUST require name token ("power delivery"
or "usb-pd" or "usb pd") AND the CC line + BMC + PDO/RDO + Source/Sink role model, and defer if the
spec is USB-2.0-data-primary (D+/D-, endpoints, PID with no CC/PDO) or USB4-primary.`,
  },
  {
    proto: 'interlaken', specName: 'Interlaken_Protocol_Definition',
    siblings: ['ethernet','ethernet_800g','axi_stream'],
    brief: `Interlaken = Interlaken Protocol Definition Rev 1.2 (Cortina Systems + Cisco). A channelized
chip-to-chip packet interface over multiple bonded SerDes lanes. Encoding: 64B/67B (64 payload bits +
3 framing bits; bit 66 = inversion, bit 65 = scrambled, bit 64 = control/data type). Words are either
Control Words (framing layer) or Data Words (payload). Burst framing: each packet segment is delimited
by Control Words — Burst Control Word at start (SOP, channel number, flow-control status) and an
Idle/Burst Control Word at end (EOP, error, EOP_Format with valid-byte count). BurstMax / BurstShort /
BurstMin parameters. Metaframe: the framing layer inserts, every MetaFrameLength words on EACH lane,
four control words — Synchronization Word (0x78f678f6...), Scrambler State Word, Skip Word (for
lane deskew / clock comp), and Diagnostic Word (per-lane CRC-32 + lane health/status). Per-burst
integrity: CRC-24 carried in the Burst/Idle Control Word covering the burst. In-band flow control:
a calendar of per-channel XON/XOFF status carried in Control Words (out-of-band via separate LVDS
also defined). Lane bonding/striping across N SerDes lanes. MUTEX vs Ethernet: Ethernet has MAC
frames, preamble/SFD, MAC addresses, 8B/10B or 64B/66B PCS — Interlaken has 64B/67B, metaframe,
BURST/IDLE control words, channelized bursts. is_interlaken MUST require name token ("interlaken")
AND the 64B/67B + metaframe (sync/scrambler/skip/diagnostic) + Burst/Idle control word + CRC-24
signature, and defer if the spec is Ethernet-primary.`,
  },
  {
    proto: 'mdio', specName: 'IEEE_802.3_MDIO_Clause22_45',
    siblings: ['i2c','spi','jtag'],
    brief: `MDIO = IEEE 802.3 Management Data Input/Output (Clause 22 + Clause 45). A 2-wire low-speed
management bus between a Station Management entity (STA, the MAC) and PHY devices (MMD). Signals:
MDC (management clock, driven by STA, up to 2.5 MHz) + MDIO (bidirectional data, open-drain with
pull-up). Clause 22 frame (32 bits after preamble): PRE (32 ones) + ST (start = 01) + OP (read=10,
write=01) + PHYAD (5-bit PHY address, 0..31) + REGAD (5-bit register address, 0..31) + TA
(turnaround, 2 bits: 10 for write, Z0 for read) + DATA (16 bits, MSB first). Clause 45 frame
(for >1G PHYs): ST = 00, OP = address(00)/write(01)/read(11)/read-increment(10), PRTAD (5-bit port)
+ DEVAD (5-bit MMD device: PMA/PMD=1, WIS=2, PCS=3, PHY XS=4, DTE XS=5, Auto-Neg=7, ...), then an
ADDRESS frame sets a 16-bit register address, and subsequent read/write frames use it (indirect
addressing). MUTEX vs I2C (SDA/SCL, START/STOP conditions, 7-bit device address, ACK per byte — MDIO
has NO start/stop conditions, NO ACK, fixed 32-bit frame) and vs SPI/JTAG. is_mdio MUST require name
token ("mdio" or "management data") AND the MDC+MDIO pair AND the ST/OP/PHYAD/REGAD/TA frame-field
model, and defer if the spec is I2C-primary (SDA/SCL + START/STOP + slave address).`,
  },
  {
    proto: 'sgmii', specName: 'Cisco_SGMII_Specification',
    siblings: ['ethernet','automotive_ethernet','ethernet_800g'],
    brief: `SGMII = Serial Gigabit Media Independent Interface (Cisco ENG-46158). A SerDes link that carries
GMII (10/100/1000 Mbps Ethernet MAC<->PHY) over a single differential pair per direction, replacing
the 10-bit parallel GMII data pins. Electrical: 1.25 Gbaud LVDS/CML differential (TX+/TX-, RX+/RX-),
625 MHz DDR clock optional. Line code: 8B/10B with running disparity and K28.5 (/K/, comma) for code-
group alignment; ordered sets /C/ (Configuration), /I/ (Idle /I1/,/I2/), /R/,/S/,/T/. Auto-negotiation
reuses the 1000BASE-X (Clause 37) PCS but redefines the 16-bit Config_Reg ("tx_config_reg"): for SGMII
the link partner (PHY) encodes link speed (bits 11:10: 00=10M,01=100M,10=1000M), duplex (bit 12), and
link-up (bit 15) instead of the 1000BASE-X ability fields; the MAC ACKs. At 10/100 Mbps the GMII byte
is replicated 100x/10x to keep the 1.25 Gbaud rate. MUTEX: SGMII is the MAC<->PHY SERDES link, NOT the
Ethernet MAC frame layer (no preamble/SFD/MAC-address/CRC-32 framing here) and NOT RGMII (parallel DDR
4-bit). is_sgmii MUST require name token ("sgmii") AND the 1.25 Gbaud + 8B/10B + GMII-over-SerDes +
auto-neg config word with embedded speed/duplex/link signature, and defer if the spec is
Ethernet-MAC-primary.`,
  },
]

const AUTHOR_SCHEMA = {
  type: 'object',
  required: ['proto','ic_name','gated','misfire_siblings_fired','tests_passed','notes'],
  properties: {
    proto: { type: 'string' },
    ic_name: { type: 'string' },
    gated: { type: 'integer' },
    misfire_siblings_fired: { type: 'array', items: { type: 'string' } },
    tests_passed: { type: 'integer' },
    spec_file: { type: 'string' },
    notes: { type: 'string' },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['proto','verdict','gold_substantive','detector_strict','content_faithful','issues'],
  properties: {
    proto: { type: 'string' },
    verdict: { type: 'string', enum: ['PASS','NEEDS_FIX'] },
    gold_substantive: { type: 'boolean' },
    detector_strict: { type: 'boolean' },
    content_faithful: { type: 'boolean' },
    issues: { type: 'array', items: { type: 'string' } },
  },
}

const results = await pipeline(
  PROTOS,
  // Stage 1 — author + close-loop to gated 0
  (p) => agent(
    `${COMMON}\n\nYOUR PROTOCOL: ${p.proto}\nSPEC FILE NAME: ${p.specName}.txt\nSIBLINGS to no-misfire-check: ${p.siblings.join(', ')}\n\nPROTOCOL BRIEF (author the spec + gold + synth from these REAL facts; expand faithfully):\n${p.brief}\n\nReplace <proto>=${p.proto}, <SpecName>=${p.specName}, <SIBLINGS>=[${p.siblings.join(', ')}] in the instructions. Drive GATED to 0 and misfire to []. Return the JSON.`,
    { label: `author:${p.proto}`, phase: 'Author', schema: AUTHOR_SCHEMA }
  ),
  // Stage 2 — adversarial review (independent agent)
  (r, p) => {
    if (!r) return null
    return agent(
      `Adversarially review the newly-added phase1 benchmark protocol "${p.proto}" at ${BENCH}/${p.proto}/ and its synth ${PROG}/${p.proto}_protocol_synth.py.\n\nYou are a skeptic. Try to find why this should NOT be accepted. Check exactly three things and report:\n1. gold_substantive: Is ${BENCH}/${p.proto}/phase1/claude_extracted/ a SUBSTANTIVE, faithful extraction of the real ${p.proto} protocol — NOT under-authored stubs that trivially match the synth, and NOT fabricated facts that contradict the real protocol? Open several L-docs (L1,L3,L8_RTL_CONSTANTS,L15,L17) and judge.\n2. detector_strict: Read is_${p.proto} in the synth. Does it REQUIRE a protocol-specific name token AND a structural quorum? Construct the sibling specs' text (${p.siblings.join(', ')}: read ${BENCH}/<sib>/phase1/input_doc/*.txt) and call is_${p.proto} on each (PYTHONPATH=${PROG} python3 -c "import ${p.proto}_protocol_synth as m; print(m.is_${p.proto}(open('...').read()))"). It must return False on every sibling. Also try to craft a plausible OTHER-protocol blob that wrongly trips it.\n3. content_faithful: Spot-check that the synth's canonical content matches the spec/gold and the real protocol (no invented opcodes/encodings). Confirm the actual gated parity is 0 by re-running l_doc_parity_diff.py.\n\nReturn the JSON verdict. verdict=PASS only if all three are true and gated==0 and no sibling misfire.`,
      { label: `review:${p.proto}`, phase: 'Review', schema: REVIEW_SCHEMA }
    ).then(v => ({ author: r, review: v }))
  }
)

const clean = results.filter(Boolean)
return {
  count: clean.length,
  protocols: clean.map(x => ({
    proto: x.author?.proto,
    gated: x.author?.gated,
    misfire: x.author?.misfire_siblings_fired,
    tests: x.author?.tests_passed,
    review: x.review?.verdict,
    issues: x.review?.issues,
  })),
}
