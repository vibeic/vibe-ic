#!/usr/bin/env python3
"""
readme_class_detector.py — README-token IC class detector (v1.6.522).

v1.6.522 — for #358 P2 ORGANIC. (1) Add `digital_arithmetic_primitive`
            class signature covering the pure digital data-transform IP
            family (multiplier / adder / FIR-IIR-CIC filter / Reed–Solomon
            / Hamming / BCH / Huffman / run-length / priority encoder /
            sort network / non-crypto hash CRC-Murmur-FNV-xxHash-CityHash).
            Listed AFTER crypto / memory / storage / serdes / network so
            specific tokens (SHA / AES / DDR4 / JESD204 / …) still win
            their existing class. (2) Add `detect_class_with_fallback`
            wrapper that codifies the correct default-fallback semantic
            at the README-detector level: positive-class match wins,
            else positive-analog marker → `pure_analog`, else →
            `unknown_protocol_class` (NOT a silent `pure_analog`
            default — `pure_analog` has rtl_gen=null AND
            fallback_skill=null, so the silent default caused
            reference_tb / yosys / qsf cascade FAIL on the pure
            digital arithmetic primitive family). `pure_analog`
            now REQUIRES positive markers (PMIC / LDO / bandgap /
            op-amp / SAR-ADC / sigma-delta DAC / AVDD-AVSS / VREF /
            VBG / IBIAS / bias network / analog block-circuit-front-end).
            `detect_class_from_readme` legacy API still returns
            (None, None) on no-match — v1.6.102 callers unchanged.

v1.6.111 — issue #39 P2 narrows serdes_link signature + adds PHY-demotion
            guard. v1.6.104 over-broadened serdes_link with PHY-layer
            terms (Gbps, gearbox, transceiver, inter-chip link) that
            legitimately appear in any serial-protocol IP's PHY
            description. SATA storage controllers and multi-protocol
            networking transport libraries were misrouted to serdes_link
            because their READMEs describe their SerDes PHY underneath.
            Fix: (1) demote/remove generic PHY tokens, (2) keep CPRI /
            OBSAI / 64B66B / JESD204 / SerWB / GTx high-weight,
            (3) when a higher-level class (storage_controller /
            network_transport_library / memory_controller) AND
            serdes_link both score and serdes_link < 2x the higher-
            level score, demote serdes_link below it.
v1.6.104 — issue #36 Bug 7 extends serdes_link signature with FPGA-SerDes
            primitives (GTP/GTX/GTH/GTY/MGT, SerWB, 8B/10B, Gbps line
            rate, Etherbone, gearbox, transceiver, comma alignment,
            inter-chip link) so liteiclink-class IPs no longer mis-
            classify as memory_controller.
            issue #36 Bug 6 adds detect_interface_types_from_readme:
            multi-protocol list extracted from README literal mentions.
v1.6.103 — issue #35 weighted per-class scoring + example-list heuristic.
v1.6.102 — issue #34 first-cut README-token detector (first-match-wins).

The v1.6.102 detector classified per-line first-match-wins. Field-agent
issue #35 caught the regression that, on a SerDes/JESD204 IP whose
README opens with a motivating-example list ("of components used in
today's SoC such as Ethernet, SATA, PCIe, SDRAM Controller, ..."),
the first-match was ``SDRAM`` → ``memory_controller``. The IP's actual
class (serdes_link, evidenced 4+ times later) lost.

v1.6.103 fix structure:

    1. Per-class weighted token signatures. Unambiguous tokens (AES,
       JESD204, eMMC, NVMe, signaltap) carry weight 3. Specific tokens
       (DDR4, SerDes, SATA, individual block-cipher names) carry
       weight 2. Generic tokens that commonly appear in motivating
       lists (Ethernet, PCIe, SDRAM, generic memory controller
       phrasing, hash core, scope IP) carry weight 1.

    2. Example-list-context heuristic. Lines whose text matches
       ``such as | for example | e.g. | including`` halve every token
       weight on that line — those tokens are referenced as examples,
       not as the IP's own subject.

    3. Detector sums per-class scores across the entire README and
       returns the highest-scoring class above
       ``_MIN_CONFIDENCE_THRESHOLD = 1.0``. A single weight-1 token
       inside an example-list line scores 0.5 → below threshold →
       returns (None, None) rather than producing a noisy default.

Backward compat: the evidence dict retains the v1.6.102 keys
(``source``, ``line``, ``matched_token``, ``extraction_strategy``)
and adds ``score`` + ``all_scores`` for audit.

Chip-AGNOSTIC: weights are properties of token classes, not of
specific projects / chips. Threshold is one tunable constant.

Public API
----------
    detect_class_from_readme(readme_text) -> (class_label, evidence_dict)
        v1.6.102 contract. Returns (None, None) on no positive marker.
    detect_class_with_fallback(readme_text) -> (class_label, evidence_dict)
        v1.6.522. Returns (`unknown_protocol_class`, ev) on no positive
        marker AND no positive analog marker; (`pure_analog`, ev) when
        positive-analog markers fire. class_label is NEVER None.
    default_interface_type_for(class_label) -> Optional[str]
"""
from __future__ import annotations

import collections
import re
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Per-class weighted README signatures.
#
# Format: list of (class_label, [(token_pattern, weight), ...]).
#
# Weight scale (per field-agent issue #35):
#   3 — unambiguous: token uniquely identifies the class (AES, JESD204,
#       eMMC, NVMe, signaltap, chipscope).
#   2 — specific: strongly associated with the class but could surface
#       in other contexts (DDR4, SerDes, SATA, individual cipher names,
#       Ethernet+speed prefix, PCIe+Gen suffix).
#   1 — generic / motivational: common in opening / motivating prose,
#       does NOT alone justify a class verdict (SDRAM, PCIe-bare,
#       Ethernet-bare, generic "memory controller", "hash core",
#       "scope IP").
#
# ORDER NOTE: when two classes tie on score, the class listed earlier
# in this list wins (deterministic tie-break via dict-insertion order).
# ---------------------------------------------------------------------------
_CLASS_SIGNATURES: List[Tuple[str, List[Tuple[str, int]]]] = [
    # v1.6.273 — for #133 ORGANIC. Processor / CPU / microcontroller-core
    # signatures. Listed FIRST so the order-based tie-break favours the
    # processor class when a CPU README also mentions auxiliary crypto /
    # hash extensions (which is common — many open-source RV cores
    # enumerate `SHA256`/`AES`-extension plugin bullets). Pre-v1.6.273
    # the detector had no processor class and any CPU mentioning crypto
    # auxiliary functionality misrouted to crypto_hash /
    # crypto_block_cipher, corrupting all downstream schema descent.
    #
    # Chip-AGNOSTIC: tokens are architecture / pipeline-style vocabulary,
    # not chip identifiers.
    ("processor_cpu", [
        # High-weight unambiguous identifiers — ISA names.
        (r"\bRV32[EIMACFDPVB]+\b", 3),
        (r"\bRV64[EIMACFDPVB]+\b", 3),
        (r"\bRISC[-_\s]?V\b", 3),
        # Pipeline-stage vocabulary — almost exclusive to CPU/processor
        # cores. A document that mentions "pipeline stage", "instruction
        # fetch", "decode stage", "writeback stage" is a CPU IP.
        (r"\b(?:register\s+file|pipeline\s+stage|instruction\s+fetch"
         r"|decode\s+stage|writeback\s+stage|execute\s+stage|fetch\s+stage)\b", 2),
        # Direct CPU/microcontroller-core noun phrases.
        (r"\b(?:CPU|microprocessor|microcontroller)\s+core\b", 2),
        # Datapath structural vocabulary — ALU + PC + regfile are
        # near-exclusive CPU terms.
        (r"\b(?:arithmetic\s+logic\s+unit|ALU|program\s+counter"
         r"|PC\s+register|branch\s+predictor)\b", 2),
        # CSR / IRQ vocabulary canonical to processor IPs.
        (r"\b(?:CSR|machine\s+mode|interrupt\s+controller"
         r"|trap\s+vector|mtvec|mstatus|mepc|mcause)\b", 2),
    ]),
    ("crypto_block_cipher", [
        (r"\bAES\b", 3),
        (r"\bDES\b", 2),
        (r"\bBlowfish\b", 3),
        (r"\bsymmetric\s+block\s+cipher\b", 2),
    ]),
    ("crypto_stream_cipher", [
        (r"\bChaCha\d*\b", 3),
        (r"\bSalsa\d+\b", 3),
        (r"\bstream\s+cipher\b", 2),
    ]),
    ("crypto_hash", [
        (r"\bSHA[-_]?\d+\b", 3),
        (r"\bMD\d\b", 2),
        (r"\bhash\s+(?:core|engine)\b", 1),
    ]),
    ("memory_controller", [
        (r"\bDDR\d\b", 2),
        (r"\bLPDDR\d?\b", 2),
        (r"\bSDRAM\b", 1),
        (r"\bmemory\s+controller\b", 1),
    ]),
    ("storage_controller", [
        (r"\bSATA\s*\d?[GBb]?\b", 2),
        (r"\bSD[-\s]?card\b", 2),
        (r"\beMMC\b", 3),
        (r"\bNVMe\b", 3),
    ]),
    ("serdes_link", [
        # HIGH (weight 3) — unambiguous standalone-SerDes IP subjects.
        (r"\bJESD204[A-Z]?\b", 3),
        (r"\b(?:GTP|GTX|GTH|GTY|MGT)\b", 3),     # FPGA SerDes primitives
        (r"\bSerWB\b", 3),                        # SerDes Wishbone
        (r"\bEtherbone\b", 3),                    # LiteX SerDes signaller
        (r"\bXAUI\b", 3),
        (r"\bCEI\b", 3),
        (r"\bCPRI\b", 3),                         # Common Public Radio Interface
        (r"\bOBSAI\b", 3),                        # Open Base Station Architecture
        (r"\b64[Bb]/66[Bb]\b", 3),                # 64B/66B encoding (more specific)
        (r"\bcomma\s+alignment\b", 3),
        # MID (weight 2) — strongly associated SerDes signals.
        (r"\b8[Bb]/10[Bb]\b", 2),                 # demote — appears in many PHY descs
        (r"\bSerDes\b", 2),                       # name match
        # v1.6.111: REMOVED tokens (per issue #39) that legitimately
        # appear in storage / networking / memory IP PHY descriptions
        # and caused misrouting:
        #   (r"\b\d+(?:\.\d+)?\s*Gbps\b", 2)  — any high-speed serial PHY
        #   (r"\bgearbox\b", 2)               — generic SerDes PHY term
        #   (r"\btransceiver\b", 1)           — too generic
        #   (r"\binter[-\s]?chip\s+link\b", 3) — appears in storage/network too
    ]),
    ("logic_analyzer_debug", [
        (r"\blogic\s+analyz(?:er|or)\b", 2),
        (r"\bsignaltap\b", 3),
        (r"\bchipscope\b", 3),
        (r"\bscope\s+IP\b", 1),
    ]),
    ("network_transport_library", [
        (r"\b(?:1G|10G|25G|100G)\s*Ethernet\b", 2),
        (r"\bPCIe\s+Gen\d\b", 2),
        (r"\bIEEE\s+1588\b", 2),
    ]),
    # v1.6.522 — for #358 P2 ORGANIC. Pure digital data-transform IP
    # family: deterministic combinational / sequential transforms with
    # no SW-visible protocol, no register map, no calibration. L2 fully
    # describes the transform; L4/L5/L6 are legitimately N/A. Examples:
    # multipliers, adders, filters (digital FIR/IIR/CIC), encoders,
    # decoders, error-correcting codecs (Reed–Solomon, Hamming, BCH),
    # data-compression (Huffman, run-length), priority encoders, sort
    # networks, CRC computation cores, non-cryptographic hashes.
    #
    # ORDER NOTE: listed AFTER crypto / memory / storage / serdes /
    # network classes so cryptographic primitives (SHA / AES / etc.)
    # and explicit protocol IPs still win their existing class — the
    # `digital_arithmetic_primitive` family is the LAST positive-
    # match resort before fall-through. This guarantees no regression
    # to v1.6.102 tests (`crypto_block_cipher` / `crypto_hash` /
    # `memory_controller` etc. still win their specific tokens).
    #
    # Pattern weights mirror v1.6.103 scale: weight 3 = unambiguous
    # arithmetic-primitive token (modulo multiplier, FIR filter,
    # carry-save adder, Reed–Solomon codec, Hamming codec); weight 2
    # = specific (bit-width-qualified multiplier, sort network,
    # non-crypto hash family name); weight 1 = generic (bare
    # `multiplier` / `adder` / `datapath`).
    #
    # Chip-AGNOSTIC: tokens are open-domain IP-class vocabulary, not
    # chip identifiers. Mirrors the open-source IP ecosystem (OpenLane
    # spm, Sky130 arithmetic test designs, generic CRC / hash blocks).
    ("digital_arithmetic_primitive", [
        # Weight 3 — unambiguous arithmetic-primitive subjects.
        (r"\bmodulo\s+multiplier\b", 3),
        (r"\b(?:carry[-\s]?save|carry[-\s]?lookahead|carry[-\s]?propagate|"
         r"ripple[-\s]?carry|Kogge[-\s]?Stone|Brent[-\s]?Kung)\s+adder\b", 3),
        (r"\b(?:FIR|IIR|CIC|polyphase)\s+filter\b", 3),
        (r"\bReed[-\s]?Solomon\b", 3),
        (r"\bHamming\s+(?:code|codec|encoder|decoder)\b", 3),
        (r"\bBCH\s+(?:code|codec|encoder|decoder)\b", 3),
        (r"\bHuffman\s+(?:encoder|decoder|codec)\b", 3),
        (r"\brun[-\s]?length\s+(?:encoder|decoder|codec)\b", 3),
        # Weight 2 — specific arithmetic-primitive subjects.
        (r"\b(?:8|12|16|24|32|48|64|128|256)[-\s]?bit\s+multiplier\b", 2),
        (r"\bpriority\s+encoder\b", 2),
        (r"\bsort(?:ing)?\s+network\b", 2),
        # Non-cryptographic hash family names (CRC, Murmur, FNV, xxHash,
        # CityHash) — distinct from SHA/MD/Blake which mark crypto_hash.
        (r"\bCRC\d+\b", 2),
        (r"\bMurmur(?:Hash)?\b", 2),
        (r"\bFNV(?:[-_]?1a)?\b", 2),
        (r"\bxxHash\b", 2),
        (r"\bCityHash\b", 2),
        # Generic data-transform-block phrasing.
        (r"\barithmetic\s+(?:primitive|sub[-\s]?block|datapath|core|"
         r"unit|block)\b", 2),
        (r"\bdata[-\s]?transform\s+(?:primitive|core|block|unit)\b", 2),
        # Weight 1 — generic / motivational. These alone seldom justify
        # the class; they corroborate when other tokens fire. The
        # `_MIN_CONFIDENCE_THRESHOLD = 1.0` keeps a single weight-1
        # match alive at full score but a single weight-1 match inside
        # an example-list line still scores 0.5 → below threshold.
        (r"\bmultiplier\b", 1),
        (r"\b(?:full|half)[-\s]?adder\b", 1),
        (r"\bdatapath\b", 1),
    ]),
]


# ---------------------------------------------------------------------------
# v1.6.522 — for #358 P2 ORGANIC. Positive-analog README markers.
#
# Vocabulary that indicates the README's subject is a pure-analog IC
# (PMIC / LDO / op-amp / bandgap / DAC / ADC / oscillator / reference /
# bias / sensor front-end). Used by `detect_class_with_fallback` to
# decide between two no-positive-class-match outcomes:
#
#   * positive analog marker fires → `pure_analog`
#   * else                          → `unknown_protocol_class`
#
# This codifies the v1.6.102 contract at the README detector level so
# downstream callers can pass `unknown_protocol_class` (which has a
# `spec-to-rtl` fallback skill) instead of the silent `pure_analog`
# default (which has `rtl_gen=null` AND `fallback_skill=null`, causing
# a cascade FAIL through reference_tb / yosys / qsf). Field-agent
# evidence: a 32-bit modulo-multiplier IP run produced PASS
# detect_ic_class pure_analog with NO positive analog marker present,
# then cascaded reference_tb FAIL / yosys FAIL / qsf FAIL.
#
# Chip-AGNOSTIC: pure analog-domain IP vocabulary, no chip identifiers.
# ---------------------------------------------------------------------------
_POSITIVE_ANALOG_PATTERNS: List[Tuple[str, int]] = [
    # Pure-analog IP families.
    (r"\bPMIC\b", 3),
    (r"\bLDO\b", 3),
    (r"\bbandgap\b", 3),
    (r"\boperational\s+amplifier\b", 3),
    (r"\bop[-\s]?amp\b", 3),
    (r"\bvoltage\s+reference\b", 3),
    (r"\bcurrent\s+reference\b", 3),
    (r"\b(?:relaxation|ring|crystal|LC)\s+oscillator\b", 3),
    (r"\b(?:Pierce|Colpitts|Hartley)\s+oscillator\b", 3),
    (r"\bbias\s+(?:generator|current|network)\b", 2),
    (r"\bcomparator\s+IP\b", 2),
    # Pure-analog supply / port-level evidence (these appear in
    # analog IC port tables / READMEs).
    (r"\bAVDD\b", 2),
    (r"\bAVSS\b", 2),
    (r"\bVREF[-_]?(?:P|N|H|L)?\b", 2),
    (r"\bVBG\b", 2),  # bandgap reference voltage
    (r"\bIBIAS\b", 2),
    # Analog-domain phrasing.
    (r"\banalog\s+(?:block|circuit|front[-\s]?end|sub[-\s]?block)\b", 2),
    (r"\bsensor\s+front[-\s]?end\b", 2),
    # Pure-analog data converters (when standalone IP, NOT mixed-signal
    # with digital control logic — that lands on `mixed_signal_otp` or
    # similar via L3/L4 detection).
    (r"\b(?:SAR|sigma[-\s]?delta|pipelined|flash|delta[-\s]?sigma)\s+"
     r"(?:ADC|DAC)\b", 3),
]


_COMPILED_POSITIVE_ANALOG_PATTERNS: List[Tuple["re.Pattern[str]", float]] = [
    (re.compile(pat, re.IGNORECASE), float(weight))
    for pat, weight in _POSITIVE_ANALOG_PATTERNS
]


# Minimum cumulative positive-analog score on a README to call
# `pure_analog` over `unknown_protocol_class`. One weight-3 hit OR
# two weight-2 hits will cross 1.0.
_POSITIVE_ANALOG_THRESHOLD = 1.0


def _has_positive_analog_marker(readme_text: Optional[str]) -> bool:
    """v1.6.522 — for #358 P2 ORGANIC. Return True iff the README text
    carries at least one positive-analog signal above
    ``_POSITIVE_ANALOG_THRESHOLD``.

    The example-list / motivating-list context multiplier from
    `_line_weight_multiplier` is applied so that a "such as PMIC /
    LDO / bandgap" enumeration in a wider-system motivating sentence
    does NOT trip the positive-analog gate. This mirrors the v1.6.103
    weight-halving for example lists.

    Chip-AGNOSTIC: pure pattern scan over analog-domain vocabulary.
    """
    if not readme_text:
        return False
    score = 0.0
    for line in readme_text.split("\n"):
        ctx_mult = _line_weight_multiplier(line)
        for rx, weight in _COMPILED_POSITIVE_ANALOG_PATTERNS:
            if rx.search(line):
                score += weight * ctx_mult
                if score >= _POSITIVE_ANALOG_THRESHOLD:
                    return True
    return False


# Best-effort default L9.interface_type per class. None means "too
# varied to default — leave L9.interface_type null + flag".
_CLASS_DEFAULT_INTERFACE: dict[str, Optional[str]] = {
    # v1.6.273 — for #133. Default interface for processor cores is None
    # because CPU IPs span memory-mapped peripherals via AXI/AHB/APB AND
    # custom instruction-bus interfaces; the detector should not pick one
    # default and silently misroute SoC integrators.
    "processor_cpu":               None,
    "crypto_block_cipher":         "register_mapped",
    "crypto_stream_cipher":        "register_mapped",
    "crypto_hash":                 "register_mapped",
    "memory_controller":           "axi",   # common default; wishbone also seen
    "storage_controller":          None,
    "serdes_link":                 None,
    "logic_analyzer_debug":        None,
    "network_transport_library":   None,
    # v1.6.522 — for #358 P2 ORGANIC. Pure digital data-transform IP
    # family is too varied (parallel-load multiplier, serial-stream
    # filter, ECC codec, …) to default L9.interface_type. The class
    # leaves interface_type null + the no_interface_type_in_input flag
    # set, so downstream extractors / human review fill it from L8
    # port-table content.
    "digital_arithmetic_primitive": None,
    "aid_class_half_duplex":       "single_wire_half_duplex",
}


# Minimum total score for a class to be returned. A single weight-1
# token inside an example-list line scores 0.5 — below this threshold
# → detector returns (None, None) and caller emits null + flag.
_MIN_CONFIDENCE_THRESHOLD = 1.0


# Example-list / motivating-list context detector. Matches the typical
# README opening prose that name-drops unrelated IP classes:
#   "such as Ethernet, SATA, PCIe, ..."
#   "for example, AES and DES ..."
#   "e.g. SDRAM controller"
#   "supported protocols including 10G Ethernet"
_EXAMPLE_LIST_CONTEXT = re.compile(
    r"(?i)\b(?:such\s+as|for\s+example|e\.g\.|including)\b"
)


# Pre-compile token patterns once.
_COMPILED_SIGNATURES: List[Tuple[str, List[Tuple["re.Pattern[str]", float]]]] = [
    (cls, [(re.compile(pat, re.IGNORECASE), float(weight))
           for pat, weight in sigs])
    for cls, sigs in _CLASS_SIGNATURES
]


def _line_weight_multiplier(line: str) -> float:
    """Halve every token weight on a line that reads like an
    example/motivating list. Returns 0.5 for example-list lines, 1.0
    otherwise.
    """
    return 0.5 if _EXAMPLE_LIST_CONTEXT.search(line) else 1.0


# ---------------------------------------------------------------------------
# v1.6.111 (#39 P2) — PHY-demotion guard.
#
# When a higher-level class (storage_controller / network_transport_library
# / memory_controller) has positive evidence AND serdes_link also scores,
# the higher-level class wins because the SerDes is the IP's PHY-layer
# dependency, not the IP's subject. The guard only engages when
# serdes_link is NOT dominant — specifically, serdes_link < 2x the
# competing class's score. This preserves pure SerDes IPs (e.g.
# liteiclink: lots of JESD204/SerWB/GTx tokens, minimal storage tokens)
# while demoting hybrid IPs whose SerDes evidence is incidental to their
# higher-level subject (e.g. a SATA controller whose README mentions its
# SerDes PHY a few times).
# ---------------------------------------------------------------------------
_HIGHER_LEVEL_CLASSES = {
    "storage_controller",
    "network_transport_library",
    "memory_controller",
}


def _apply_serdes_phy_demotion(scores: dict) -> dict:
    """If serdes_link AND a higher-level class both score, and
    serdes_link is not dominant (< 2x the highest higher-level score),
    demote serdes_link below the higher-level class so the higher-level
    class wins. Returns adjusted scores dict (unmodified original is
    safe).
    """
    serdes_score = scores.get("serdes_link", 0)
    if serdes_score == 0:
        return scores
    highest_higher = 0
    highest_higher_class = None
    for cls in _HIGHER_LEVEL_CLASSES:
        if scores.get(cls, 0) > highest_higher:
            highest_higher = scores[cls]
            highest_higher_class = cls
    if highest_higher_class is None:
        return scores  # no higher-level class active
    if serdes_score < 2 * highest_higher:
        # SerDes is the PHY, not the subject. Demote it below the
        # higher-level class.
        adjusted = dict(scores)
        adjusted["serdes_link"] = highest_higher - 0.5
        return adjusted
    return scores


def detect_class_from_readme(
    readme_text: Optional[str],
) -> Tuple[Optional[str], Optional[dict]]:
    """Return ``(class_label, evidence_dict)`` for the highest-scoring
    class above ``_MIN_CONFIDENCE_THRESHOLD``, else ``(None, None)``.

    Scoring walk:
      * For every README line, compute a context multiplier (0.5 if the
        line reads as an example/motivating list, else 1.0).
      * For every (class, token_pattern, weight) signature, on a match
        add ``weight * ctx_mult`` to that class's running score and
        record evidence.
      * After the walk, pick the highest-scoring class. If its score is
        below the threshold → return (None, None).
      * Tie-break by class order in ``_CLASS_SIGNATURES`` — first-class-
        encountered wins. Deterministic across runs.

    The returned ``evidence_dict`` carries the v1.6.102 keys
    (``source``, ``line``, ``matched_token``, ``extraction_strategy``)
    pinned to the EARLIEST evidence for the winning class — so audit
    UIs that quote a single line still work — and adds ``score``
    (winner's total) plus ``all_scores`` (every class with non-zero
    score, for transparency).

    Chip-AGNOSTIC: scoring uses class-domain tokens, not project-
    specific identifiers.
    """
    if not readme_text:
        return None, None

    scores: dict[str, float] = collections.defaultdict(float)
    evidence: dict[str, list[dict]] = collections.defaultdict(list)

    for line_num, line in enumerate(readme_text.split("\n"), start=1):
        ctx_mult = _line_weight_multiplier(line)
        for cls, sigs in _COMPILED_SIGNATURES:
            for rx, weight in sigs:
                m = rx.search(line)
                if m:
                    contribution = weight * ctx_mult
                    scores[cls] += contribution
                    evidence[cls].append({
                        "line": line_num,
                        "matched_token": m.group(0),
                        "weight": contribution,
                    })

    if not scores:
        return None, None

    # v1.6.111 (#39 P2): demote serdes_link below any active higher-level
    # class (storage / networking / memory) when serdes_link is not
    # dominant. The SerDes is the PHY, not the IP's subject.
    scores = _apply_serdes_phy_demotion(scores)

    # Tie-break: when two classes tie, prefer the one that appears
    # earlier in _CLASS_SIGNATURES (deterministic).
    class_order = {cls: idx for idx, (cls, _) in enumerate(_CLASS_SIGNATURES)}
    winner = max(scores.keys(), key=lambda c: (scores[c], -class_order[c]))

    if scores[winner] < _MIN_CONFIDENCE_THRESHOLD:
        return None, None

    first_ev = evidence[winner][0]
    return winner, {
        # v1.6.102 evidence keys preserved for backward compat.
        "source": "input/docs/README.md",
        "line": first_ev["line"],
        "extraction_strategy": "readme_class_token_match",
        "matched_token": first_ev["matched_token"],
        # v1.6.103 audit additions.
        "score": round(scores[winner], 2),
        "all_scores": {c: round(s, 2) for c, s in scores.items()},
    }


def default_interface_type_for(class_label: Optional[str]) -> Optional[str]:
    """Return the best-effort default L9.interface_type for the class.

    Returns ``None`` when:
      * ``class_label`` itself is None, or
      * the class is too varied to default (storage_controller,
        serdes_link, logic_analyzer_debug, network_transport_library).

    Caller should treat None as "leave L9.interface_type null and
    set L9.no_interface_type_in_input=true".
    """
    if not class_label:
        return None
    return _CLASS_DEFAULT_INTERFACE.get(class_label)


# ---------------------------------------------------------------------------
# v1.6.104 (#36 Bug 6) — multi-protocol interface detection.
#
# Replaces the single-string `interface_type` field with a LIST of every
# protocol the README mentions. The singular field is preserved for
# backward compat (sdc_gen / downstream consumers still read it) and is
# set to the highest-occurrence detected protocol.
#
# ORDER NOTE: more-specific patterns (axi-stream, axi-lite) are listed
# BEFORE less-specific ones (axi). When a line matches multiple, the
# more-specific match wins via per-pattern occurrence counting (each
# pattern walks the line independently, so axi-lite + axi may both
# fire — that's intentional, the consumer decides which to surface).
# ---------------------------------------------------------------------------
_INTERFACE_TOKEN_PATTERNS: List[Tuple[str, str]] = [
    ("axi-stream", r"\bAXI[-\s]?Stream\b"),
    ("axi-lite",   r"\bAXI[-\s]?Lite\b"),
    # AXI generic: AXI, AXI3, AXI4, AXI-MM, AXI-Full. Exclude lite/stream
    # via negative lookahead so they're attributed to the specific bucket.
    ("axi",        r"\bAXI(?![-\s]?(?:Stream|Lite))(?:[-\s]?(?:Full|MM|3|4))?\b"),
    ("wishbone",   r"\bWishbone\b"),
    ("apb",        r"\bAPB\b"),
    ("pcie",       r"\bPCIe(?:\s+Gen\d)?\b"),
    ("sata",       r"\bSATA(?:\s*\d?(?:\.\d)?\s*[GMK]?bps?)?\b|\bSATA\s+host\b"),
    ("sdcard",     r"\bSD[-\s]?card\b|\bSDIO\b"),
    ("i2c",        r"\bI2C\b"),
    ("uart",       r"\bUART\b"),
    ("serwb",      r"\bSerWB\b"),
    ("ethernet",   r"\b(?:1G|10G|25G|100G)?\s*Ethernet\b"),
    # v1.6.126 (#48) — extend vocabulary to cover SerDes-class IPs
    # (liteiclink-style multi-protocol transceiver libraries).
    # All chip-AGNOSTIC: each token is an industry-standard IP /
    # transceiver primitive name, not a chip identifier.
    ("etherbone",  r"\bEtherbone\b"),
    ("lvds",       r"\bLVDS\b"),
    ("8b10b",      r"\b8B[/-]?10B\b"),
    ("cpri",       r"\bCPRI\b"),
    ("jesd204b",   r"\bJESD204B\b"),
    ("jesd204c",   r"\bJESD204C\b"),
    # Generic transceiver / SerDes IP family. The "such as" prose
    # strip from v1.6.112 still neutralises enumeration-only matches.
    ("serdes",     r"\bSerDes\b"),
    # Xilinx transceiver primitive families. Each in its own bucket
    # so downstream consumers can identify the FPGA family target.
    ("gtp",        r"\bGTP\b"),
    ("gtx",        r"\bGTX\b"),
    ("gth",        r"\bGTH\b"),
    ("gty",        r"\bGTY\b"),
    ("gtw",        r"\bGTW\b"),
    ("gtm",        r"\bGTM\b"),
    # v1.6.289 — for #168 ORGANIC. Open-standard bus protocols used
    # widely by open-source CPU IPs and SoC integrations. Each is
    # defined by an industry consortium or open-source foundation:
    #   * OBI       — Open Bus Interface (PULP / OpenHW)
    #   * TileLink  — open-standard SiFive / Chips Alliance bus
    #   * AHB       — open-standard ARM AMBA AHB
    #   * AHB-Lite  — open-standard AMBA AHB-Lite single-master variant
    #   * OCP       — open-standard Open Core Protocol
    # ORDER NOTE: "ahb-lite" appears BEFORE "ahb" so the more-specific
    # variant wins. The "ahb" pattern carries a negative look-ahead so
    # `AHB-Lite` is never matched by the "ahb" bucket as well.
    ("obi",        r"\bOBI\b"),
    ("tilelink",   r"\bTileLink\b"),
    ("ahb-lite",   r"\bAHB[-\s]?Lite\b"),
    ("ahb",        r"\bAHB(?![-\s]?Lite)\b"),
    ("ocp",        r"\bOCP\b"),
]

_INTERFACE_LITERAL_THRESHOLD = 1  # any single mention counts

_COMPILED_INTERFACE_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    (name, re.compile(pat, re.IGNORECASE))
    for name, pat in _INTERFACE_TOKEN_PATTERNS
]

# v1.6.112 (#36 minor side-observation) — enumeration-prose markers.
# When a README sentence introduces a list of unrelated example
# components via "such as ...", "e.g., ...", "for example", or
# "for instance", tokens inside that enumeration are illustrative —
# they describe sibling components in a wider system, NOT interfaces
# of THIS IP. The field-agent verified-on-10-IC report observed this
# on litedram (sentence wraps across lines):
#   "Useful for connecting components in modern SoCs such as
#    Ethernet, SATA, PCIe, SDRAM Controller."
# pulled spurious ethernet/sata/pcie into a memory_controller's
# interface_types.
#
# Fix: track an "in-enumeration" range that starts at the marker and
# extends until the next sentence terminator (period followed by
# whitespace / end-of-line / blank line / section heading). Token
# matches whose start position falls inside that range are skipped.
# Tokens BEFORE the marker on the same line, and tokens after the
# enumeration ends, are still counted.
#
# Chip-AGNOSTIC: pure prose-pattern filter, no project identifiers.
_ENUMERATION_PROSE_MARKER_RE = re.compile(
    r"\b(?:such\s+as|e\.?\s*g\.?|for\s+example|for\s+instance)\b",
    re.IGNORECASE,
)
_SENTENCE_TERMINATOR_RE = re.compile(r"\.(?:\s|$)")


def detect_interface_types_from_readme(
    readme_text: Optional[str],
) -> List[dict]:
    """v1.6.104 (#36 Bug 6) — extract multi-protocol interface list.

    Walks the README and counts occurrences of every interface-protocol
    token in ``_INTERFACE_TOKEN_PATTERNS``. Returns a list of dicts:

        [{
            "name":          "axi",
            "occurrences":   N,
            "first_line":    L,        # 1-indexed line of first hit
            "matched_token": "AXI4",  # exact text of first hit
        }, ...]

    Sorted by ``occurrences`` desc, then alphabetical by ``name``.
    Empty list when no protocol meets ``_INTERFACE_LITERAL_THRESHOLD``.

    Chip-AGNOSTIC: pure regex over README prose. No project-specific
    identifiers. Designed to handle the field-agent's verbatim cases
    (taxi: ~100 AXI mentions; litesata: SATA-heavy; litesdcard: SD-heavy).

    v1.6.112 (#36 side-observation): tokens that appear AFTER an
    enumeration-prose marker ("such as", "e.g.", "for example",
    "for instance") on the same line are skipped — they describe
    sibling components in a wider SoC, not interfaces of THIS IP.
    """
    if not readme_text:
        return []

    counts: dict[str, int] = collections.defaultdict(int)
    first_hits: dict[str, dict] = {}

    # Multi-line enumeration tracking: when a sentence opens an
    # enumeration ("such as ...") but does not terminate on the same
    # line, the next line(s) remain inside the enumeration until a
    # sentence terminator or blank line is seen.
    in_enumeration = False
    for line_num, line in enumerate(readme_text.split("\n"), start=1):
        if not line.strip():
            in_enumeration = False  # blank line ends any pending enum
            continue

        # Determine where the enumeration STARTS on this line:
        if in_enumeration:
            enum_active_start = 0  # carryover — entire line is enum
        else:
            marker = _ENUMERATION_PROSE_MARKER_RE.search(line)
            enum_active_start = marker.start() if marker else None

        # Determine where the enumeration ENDS on this line:
        if enum_active_start is not None:
            terminator = _SENTENCE_TERMINATOR_RE.search(line, enum_active_start)
            if terminator:
                enum_active_end = terminator.end()
                in_enumeration = False
            else:
                enum_active_end = len(line)
                in_enumeration = True
        else:
            enum_active_end = -1  # no enum on this line

        for name, rx in _COMPILED_INTERFACE_PATTERNS:
            for m in rx.finditer(line):
                if (enum_active_start is not None
                        and enum_active_start <= m.start() < enum_active_end):
                    # match falls inside an enumeration phrase;
                    # treat as illustrative, not a real interface.
                    continue
                counts[name] += 1
                if name not in first_hits:
                    first_hits[name] = {
                        "first_line": line_num,
                        "matched_token": m.group(0),
                    }

    results: List[dict] = []
    for name, n in counts.items():
        if n < _INTERFACE_LITERAL_THRESHOLD:
            continue
        entry = {
            "name":          name,
            "occurrences":   n,
            "first_line":    first_hits[name]["first_line"],
            "matched_token": first_hits[name]["matched_token"],
        }
        results.append(entry)

    # Sort by occurrences desc, then alphabetical by name (deterministic).
    results.sort(key=lambda e: (-e["occurrences"], e["name"]))
    return results


# ---------------------------------------------------------------------------
# v1.6.522 — for #358 P2 ORGANIC. Default-fallback wrapper.
#
# `detect_class_from_readme` returns `(None, None)` when no class
# signature scores above threshold (back-compat v1.6.102 contract).
# Field-agent issue #358 documented the downstream cascade when
# callers treat None as `pure_analog` (the silent default in some
# code paths): pure_analog has `rtl_gen=null` AND `fallback_skill=null`,
# so reference_tb / yosys / qsf all FAIL with no recovery path.
#
# This wrapper codifies the correct default-fallback semantic at the
# detector level:
#
#   1. Try the per-class README-token detector. Positive match wins.
#   2. No positive match → check for positive analog markers:
#      * `_has_positive_analog_marker(readme_text) is True`
#        → return `pure_analog` (genuinely analog IC).
#      * Otherwise
#        → return `unknown_protocol_class` (runner falls through to
#          `spec-to-rtl` skill, AI fallback path produces RTL).
#
# `unknown_protocol_class` is the correct residual default for any
# IC whose L4 (no opcode) / L5 (no register map) / L6 (no calibration)
# are legitimately N/A — for example the pure digital data-transform
# IP family this version newly registers as `digital_arithmetic_primitive`.
# Without this wrapper, those ICs misroute to `pure_analog`.
#
# Chip-AGNOSTIC: pure default-fallback wrapper over the existing
# v1.6.102 detector + the v1.6.522 positive-analog gate.
# ---------------------------------------------------------------------------
def detect_class_with_fallback(
    readme_text: Optional[str],
) -> Tuple[str, Optional[dict]]:
    """v1.6.522 — for #358 P2 ORGANIC. Return ``(class_label, evidence)``
    with an explicit default-fallback so the caller never has to default
    to ``pure_analog`` on a no-positive-marker outcome.

    Semantics (in order):
      1. Positive-class match → return ``(class_label, evidence)`` from
         the v1.6.102 detector.
      2. No positive-class match AND positive analog markers fire
         (``_has_positive_analog_marker`` True) → return
         ``("pure_analog", evidence)`` where ``evidence`` carries
         ``extraction_strategy="positive_analog_marker_fallback"``.
      3. Otherwise → return
         ``("unknown_protocol_class", evidence)`` where ``evidence``
         carries ``extraction_strategy="default_fallback_v1_6_522"``.
         The runner consults the registry and dispatches to the
         class's ``fallback_skill`` (``spec-to-rtl``), unblocking
         the pure digital data-transform IP family that previously
         cascaded to FAIL on ``pure_analog``'s null rtl_gen + null
         fallback_skill.

    The class_label is NEVER None — callers that need the v1.6.102
    None-return semantic should keep using ``detect_class_from_readme``.

    Chip-AGNOSTIC.
    """
    cls, ev = detect_class_from_readme(readme_text)
    if cls is not None:
        return cls, ev
    # No positive-class match. Decide between pure_analog and
    # unknown_protocol_class based on positive-analog markers.
    if _has_positive_analog_marker(readme_text):
        return "pure_analog", {
            "source": "input/docs/README.md",
            "extraction_strategy": "positive_analog_marker_fallback",
            "matched_token": None,
            "score": 0.0,
            "all_scores": {},
        }
    return "unknown_protocol_class", {
        "source": "input/docs/README.md",
        "extraction_strategy": "default_fallback_v1_6_522",
        "matched_token": None,
        "score": 0.0,
        "all_scores": {},
    }


__all__ = [
    "detect_class_from_readme",
    "detect_class_with_fallback",
    "default_interface_type_for",
    "detect_interface_types_from_readme",
]
