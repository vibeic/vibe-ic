"""v0.1.51 — L-doc taxonomy single source of truth.

Doctrine: the user (2026-05-29) flagged that L1-L13 is insufficient for
bus/interconnect/protocol specs (AMBA AXI surfaced ~13 facts with no
home). Follow-ups added two more questions:

  (Q2) Is L1-L18 enough for the FULL design flow downstream
       (RTL gen, PnR, DFT, signoff)?
  (Q3) How to handle SoC ICs that span MULTIPLE classes simultaneously
       (e.g. CPU + bus + DRAM controller + analog + OTP all in one die)?

This program codifies the EXTENDED taxonomy + the ic_class → applicable
L-doc map. v0.1.51 ships L1-L23 + a `soc_multi_block` ic_class that
declares an array of sub-block classes.

Design summary
==============

  L1-L13     (v1)  chip-centric data — datasheet, regmap, OTP, lab cal
  L14-L18    (v2)  protocol-spec data — versioning, encoding tables,
                   compliance, channel catalog, interconnect topology
  L19-L23    (v2)  FUTURE-FLOW data — PnR constraints, DFT scan,
                   power intent, verification plan, security

  ic_class
    chip_otp_centric          — original L1-L13 IC
    bus_interconnect_protocol — AXI/USB/PCIe/DDR family
    cpu_core_isa              — RISC-V / ARM / custom CPU ISA
    memory_controller         — DRAM / SRAM / NVM controller
    analog_block              — LDO / PLL / ADC / sensor block
    soc_multi_block           — SoC composed of multiple sub-blocks,
                                each with its own ic_class
    unknown                   — fallback: emit everything

Pure-function module; no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Canonical L-doc taxonomy
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LDocSpec:
    """One L-doc category in the taxonomy."""
    code: str           # canonical short id, e.g. "L1" / "L17"
    full_name: str      # full filename stem, e.g. "L1_DATASHEET"
    title: str          # human title
    description: str    # one-paragraph scope


# v1 (L1..L13) — original chip-centric taxonomy
L_DOCS_V1: Tuple[LDocSpec, ...] = (
    LDocSpec("L1", "L1_DATASHEET", "Datasheet",
             "Overview: purpose, function, electrical, packaging summary."),
    LDocSpec("L2", "L2_FRS", "Functional Requirements Spec",
             "What the design must do; handshake/ordering/addressing rules."),
    LDocSpec("L3", "L3_CMD_PROTOCOL", "Command Protocol",
             "Per-command/transaction protocol (opcodes, signal tuples)."),
    LDocSpec("L4", "L4_REGMAP", "Register Map",
             "Memory-mapped registers + bit field definitions."),
    LDocSpec("L5", "L5_ADI_SPEC", "Analog/Digital Interface",
             "Analog electrical specs, ADC/DAC, analog-digital boundary."),
    LDocSpec("L6", "L6_CONTROL_LOGIC", "Control Logic",
             "FSM hints, control-path dependencies."),
    LDocSpec("L7", "L7_TEST_DEBUG", "Test/Debug",
             "Test pins, debug architecture, scan/JTAG."),
    LDocSpec("L8C", "L8_RTL_CONSTANTS", "RTL Constants",
             "Width parameters, encoding constants."),
    LDocSpec("L8T", "L8_TIMING_WAVEFORM", "Timing Waveform",
             "Setup/hold, clock-to-Q, handshake waveforms."),
    LDocSpec("L9", "L9_INTEGRATION_SPEC", "Integration Spec",
             "System-level integration rules."),
    LDocSpec("L10", "L10_TEST_CASES", "Test Cases",
             "Compliance/protocol-check scenarios."),
    LDocSpec("L11", "L11_OTP_CONTENT", "OTP Content",
             "One-time-programmable fuse content + layout."),
    LDocSpec("L12", "L12_BEHAVIORAL_SEQUENCES", "Behavioral Sequences",
             "Typical/edge-case sequences as transaction traces."),
    LDocSpec("L13", "L13_LAB_CALIBRATION", "Lab Calibration",
             "Lab/measurement calibration content."),
)

# v2 EXTENSIONS (L14..L18) — needed for protocol/bus/interconnect specs.
# Surfaced by the 2026-05-29 AMBA AXI parity loop (iter1 found ~13 facts
# with no L1-L13 home).
L_DOCS_V2_PROTOCOL_EXT: Tuple[LDocSpec, ...] = (
    LDocSpec("L14", "L14_PROTOCOL_VERSIONING", "Protocol Versioning",
             "Version deltas + backward-compat traps "
             "(AXI3 vs AXI4; USB 2/3; PCIe gens; DDR3/4/5)."),
    LDocSpec("L15", "L15_ENCODING_TABLES", "Encoding Tables",
             "Dense lookup tables: BURST/RESP for bus protocols, ISA "
             "opcodes for CPUs, status-reg bit definitions."),
    LDocSpec("L16", "L16_COMPLIANCE_PROPERTIES", "Compliance Properties",
             "Formal-shape invariants: assertion-level rules a "
             "compliance checker would verify."),
    LDocSpec("L17", "L17_CHANNEL_SIGNAL_CATALOG", "Channel Signal Catalog",
             "Per-channel signal catalog for protocols with many "
             "sideband signals (AXI 50+, USB 30+, DDR 100+)."),
    LDocSpec("L18", "L18_INTERCONNECT_TOPOLOGY", "Interconnect Topology",
             "Interconnect ID propagation, default signal values, "
             "multi-copy atomicity, NoC routing."),
)

# v2 EXTENSIONS (L19..L23) — needed for the FULL downstream design flow
# (RTL gen → PnR → DFT → signoff). Surfaced by the user's follow-up
# question: "is L1-L18 enough for future IC design flow?"
L_DOCS_V2_FLOW_EXT: Tuple[LDocSpec, ...] = (
    LDocSpec("L19", "L19_CONSTRAINTS_PDK", "Constraints + PDK",
             "PDK target, area / power budgets, SDC timing "
             "constraints, floorplan hints. Feeds phase3 PnR."),
    LDocSpec("L20", "L20_DFT_SCAN_TOPOLOGY", "DFT Scan Topology",
             "Scan-chain configuration, BIST/MBIST plan, test "
             "compression, JTAG TAP. Feeds DFT insertion."),
    LDocSpec("L21", "L21_POWER_INTENT", "Power Intent",
             "Power domains, isolation cells, level shifters, "
             "retention. UPF/CPF-shaped. Feeds low-power flow."),
    LDocSpec("L22", "L22_VERIFICATION_PLAN", "Verification Plan",
             "Coverage goals, formal-property targets, regression "
             "matrix. Richer than L10 (test cases) — full vplan."),
    LDocSpec("L23", "L23_SECURITY_REQUIREMENTS", "Security Requirements",
             "Key handling, attack surface, side-channel mitigation, "
             "secure boot. For security-sensitive ICs."),
)

# Full taxonomy v2 = v1 + protocol extensions + flow extensions = 24 entries
L_DOCS_V2: Tuple[LDocSpec, ...] = (
    L_DOCS_V1 + L_DOCS_V2_PROTOCOL_EXT + L_DOCS_V2_FLOW_EXT
)


# ---------------------------------------------------------------------------
# Sub-block declaration (for SoC ic_class)
# ---------------------------------------------------------------------------
@dataclass
class SubBlock:
    """One sub-block of an SoC. The SoC top level emits L1/L2/L9/L18/
    L19/L21 for the whole die; each sub-block emits its own subset of
    L docs into a sub-directory (e.g. `phase1/generated_docs/cpu/L15.json`).
    """
    block_name: str                  # e.g. "cpu", "axi_fabric"
    ic_class: str                    # any ic_class id from this taxonomy
    instances: int = 1               # how many copies are instantiated

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


# ---------------------------------------------------------------------------
# ic_class → applicable L-doc set
# ---------------------------------------------------------------------------
# Each entry maps the canonical ic_class id to the L-doc codes that
# legitimately apply. L-docs NOT in the applicable set must emit a
# `{"applicability": "N/A", "rationale": "..."}` stub rather than empty
# content (or, worse, hallucinated content like the AMBA AXI 'SUCH ARM
# TECHNOLOGY' ic_name from license boilerplate).
IC_CLASS_APPLICABILITY: Dict[str, Dict[str, List[str]]] = {
    "bus_interconnect_protocol": {
        "applicable": [
            "L1", "L2", "L3", "L6", "L8C", "L8T", "L9", "L10", "L12",
            "L14", "L15", "L16", "L17", "L18",
            "L19", "L22",
        ],
        "not_applicable": [
            "L4", "L5", "L7", "L11", "L13",
            "L20", "L21", "L23",
        ],
        "rationale_not_applicable": {
            "L4": "Bus protocols expose channels, not memory-mapped registers",
            "L5": "No analog interface; pure digital protocol",
            "L7": "No test/debug architecture; this is a protocol spec",
            "L11": "No OTP fuses",
            "L13": "No lab calibration",
            "L20": "DFT scan is per-implementation, not protocol-level",
            "L21": "Power intent is per-implementation, not protocol-level",
            "L23": "Security is per-implementation, not protocol-level",
        },
    },
    "cpu_core_isa": {
        "applicable": [
            "L1", "L2", "L6", "L8C", "L8T", "L9", "L10", "L12",
            "L14", "L15", "L16",
            "L19", "L20", "L22", "L23",
        ],
        "not_applicable": [
            "L3", "L4", "L5", "L7", "L11", "L13",
            "L17", "L18", "L21",
        ],
        "rationale_not_applicable": {
            "L3": "ISA opcodes go in L15 encoding tables, not L3 transactions",
            "L4": "CPU register file is in L15 encoding tables, not L4 regmap",
            "L5": "No analog",
            "L7": "Test/debug is per-implementation, not ISA-level",
            "L11": "No OTP",
            "L13": "No lab calibration",
            "L17": "ISA spec has no multi-channel external bus catalog",
            "L18": "Interconnect topology is system-level, not ISA-level",
            "L21": "Power intent is per-implementation, not ISA-level",
        },
    },
    "chip_otp_centric": {
        # The original L1-L13 design target. New L14-L23 mostly not relevant.
        "applicable": [
            "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8C", "L8T",
            "L9", "L10", "L11", "L12", "L13",
            "L19", "L20", "L21", "L22",
        ],
        "not_applicable": [
            "L14", "L15", "L16", "L17", "L18",
            "L23",
        ],
        "rationale_not_applicable": {
            "L14": "Chip-level products don't usually carry protocol versioning",
            "L15": "Encoding lives in L4 regmap for this class",
            "L16": "Compliance properties are subsumed by L2 FRS",
            "L17": "No multi-channel external bus to catalog",
            "L18": "No interconnect topology at this level",
            "L23": "Security not in scope for this chip class",
        },
    },
    "memory_controller": {
        "applicable": [
            "L1", "L2", "L3", "L6", "L7", "L8C", "L8T", "L9",
            "L10", "L12",
            "L14", "L15", "L16", "L17", "L18",
            "L19", "L20", "L22",
        ],
        "not_applicable": [
            "L4", "L5", "L11", "L13",
            "L21", "L23",
        ],
        "rationale_not_applicable": {
            "L4": "DRAM-side register set goes in L15 encoding tables",
            "L5": "I/O is pseudo-differential not pure analog (use L8T)",
            "L11": "No OTP",
            "L13": "No lab calibration",
            "L21": "Power intent is system-level, not controller-level",
            "L23": "Security not in scope for raw memory controller",
        },
    },
    "analog_block": {
        "applicable": [
            "L1", "L2", "L5", "L6", "L8C", "L8T", "L9", "L10", "L11",
            "L12", "L13",
            "L19",
        ],
        "not_applicable": [
            "L3", "L4", "L7",
            "L14", "L15", "L16", "L17", "L18",
            "L20", "L21", "L22", "L23",
        ],
        "rationale_not_applicable": {
            "L3": "No command protocol; this is a continuous-time block",
            "L4": "No memory-mapped register interface",
            "L7": "Test/debug captured in L13 lab calibration",
            "L14": "No protocol versioning",
            "L15": "No encoding tables",
            "L16": "No formal compliance properties",
            "L17": "No multi-channel bus",
            "L18": "No interconnect topology",
            "L20": "DFT scan does not apply to pure analog blocks",
            "L21": "Power intent is system-level, not analog-block-level",
            "L22": "Verification is SPICE/PVT (lives in L13), not vplan",
            "L23": "Security not in scope for raw analog block",
        },
    },
    "soc_multi_block": {
        # SoC top-level. Top-level L docs cover the whole die; per
        # sub-block L docs (under {project}/phase1/generated_docs/{sub_name}/)
        # emit per the sub_block's own ic_class applicability. Top-level
        # applicable is the UNION of categories that ARE meaningful at
        # die scope (datasheet, integration, power intent, security,
        # verification plan are top-level concerns).
        "applicable": [
            "L1", "L2", "L4", "L7", "L9",
            "L18",
            "L19", "L20", "L21", "L22", "L23",
        ],
        "not_applicable": [
            "L3", "L5", "L6", "L8C", "L8T", "L10", "L11", "L12", "L13",
            "L14", "L15", "L16", "L17",
        ],
        "rationale_not_applicable": {
            # All these are PER-SUB-BLOCK concerns, not top-level SoC concerns.
            "L3": "Per-sub-block (each block has its own protocol)",
            "L5": "Per-sub-block (analog blocks individually)",
            "L6": "Per-sub-block (each block has its own FSM)",
            "L8C": "Per-sub-block (RTL constants)",
            "L8T": "Per-sub-block (timing waveforms)",
            "L10": "Per-sub-block (block-level test cases)",
            "L11": "Per-sub-block (OTP block)",
            "L12": "Per-sub-block (block sequences)",
            "L13": "Per-sub-block (lab cal per analog block)",
            "L14": "Per-sub-block (per-protocol versioning)",
            "L15": "Per-sub-block (per-block encoding)",
            "L16": "Per-sub-block (per-protocol compliance)",
            "L17": "Per-sub-block (per-bus channel catalog)",
        },
    },
}


# Default fallback when ic_class is unknown — emit ALL L1..L23 (legacy
# behavior was L1..L13). The runner can choose to be conservative here
# and emit L14..L23 as N/A-with-rationale until ic_class is detected.
DEFAULT_IC_CLASS = "unknown"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def all_l_doc_codes() -> List[str]:
    """All known L-doc canonical codes in canonical order."""
    return [spec.code for spec in L_DOCS_V2]


def all_l_doc_full_names() -> List[str]:
    """All known L-doc full names (file-stem form) in canonical order."""
    return [spec.full_name for spec in L_DOCS_V2]


def l_doc_spec(code_or_name: str) -> LDocSpec:
    """Look up the LDocSpec by canonical code or full name."""
    for spec in L_DOCS_V2:
        if spec.code == code_or_name or spec.full_name == code_or_name:
            return spec
    raise KeyError(f"unknown L doc: {code_or_name!r}")


def applicable_l_docs(ic_class: str) -> Set[str]:
    """Return the set of L-doc codes that apply to the given ic_class.

    Unknown ic_class → returns all codes (legacy-compatible behavior).
    """
    entry = IC_CLASS_APPLICABILITY.get(ic_class)
    if entry is None:
        return set(all_l_doc_codes())
    return set(entry["applicable"])


def not_applicable_l_docs(ic_class: str) -> Set[str]:
    """Return the set of L-doc codes that DO NOT apply to the ic_class."""
    entry = IC_CLASS_APPLICABILITY.get(ic_class)
    if entry is None:
        return set()
    return set(entry["not_applicable"])


def is_applicable(ic_class: str, l_doc: str) -> bool:
    """Is `l_doc` (code or full name) applicable to `ic_class`?

    Unknown ic_class → True (legacy-compatible — emit everything).
    Unknown l_doc → raises KeyError so callers don't silently typo.
    """
    spec = l_doc_spec(l_doc)
    if ic_class not in IC_CLASS_APPLICABILITY:
        return True
    return spec.code in IC_CLASS_APPLICABILITY[ic_class]["applicable"]


def na_rationale(ic_class: str, l_doc: str) -> str:
    """Why is `l_doc` not applicable to `ic_class`?

    Returns the canonical rationale string, or a generic fallback.
    """
    spec = l_doc_spec(l_doc)
    entry = IC_CLASS_APPLICABILITY.get(ic_class, {})
    return entry.get("rationale_not_applicable", {}).get(
        spec.code,
        f"L-doc {spec.code} is marked not-applicable for ic_class={ic_class}",
    )


def na_stub(ic_class: str, l_doc: str) -> Dict[str, str]:
    """Build the canonical 'not applicable' stub a runner should emit
    when the L doc is skipped due to ic_class applicability.

    The stub is honest: it surfaces ic_class and rationale so a future
    audit can see WHY the doc is empty (vs the silent-empty pre-v0.1.51
    behaviour that downstream gates couldn't distinguish from genuine
    extraction failure).
    """
    spec = l_doc_spec(l_doc)
    return {
        "doc_id": spec.code,
        "doc_name": spec.full_name,
        "applicability": "N/A",
        "ic_class": ic_class,
        "rationale": na_rationale(ic_class, l_doc),
        "emitted_by": "l_doc_taxonomy.na_stub v0.1.51",
    }


# ---------------------------------------------------------------------------
# SoC composition support
# ---------------------------------------------------------------------------
def soc_applicable_top_level(sub_blocks: List[SubBlock]) -> Set[str]:
    """For an SoC, top-level L docs = union of `soc_multi_block` applicable.

    The sub-block list does NOT change the top-level applicable set —
    top-level is FIXED by the soc_multi_block entry. Sub-blocks emit
    their own L docs in sub-directories per their individual ic_class.
    """
    return applicable_l_docs("soc_multi_block")


def soc_applicable_per_sub_block(
    sub_blocks: List[SubBlock],
) -> Dict[str, Set[str]]:
    """Return {sub_block_name: applicable_L_doc_codes} for an SoC.

    Each sub-block's applicability comes from its own ic_class.
    """
    out: Dict[str, Set[str]] = {}
    for sb in sub_blocks:
        out[sb.block_name] = applicable_l_docs(sb.ic_class)
    return out


def soc_union_applicable(sub_blocks: List[SubBlock]) -> Set[str]:
    """Return the UNION of all L-doc codes covered across top-level +
    every sub-block. This is what an SoC audit gate needs to know to
    decide "did the project cover everything its sub-blocks need".
    """
    out = soc_applicable_top_level(sub_blocks)
    for sb in sub_blocks:
        out = out | applicable_l_docs(sb.ic_class)
    return out
