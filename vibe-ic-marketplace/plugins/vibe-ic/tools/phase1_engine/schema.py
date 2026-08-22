"""Fact graph schema.

A fact graph is an unordered collection of Fact entries. Each fact is an
atomic truth about the target IC, identified by a UUID and a dotted path
into the unified design namespace.

Layer JSONs (L1..L9) are *views* over the fact graph — not authoritative.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

SCHEMA_VERSION = 1


def _deterministic_uuid(path: str, value: Any) -> str:
    """Stable short ID from (path, value) — lets reverse-extract produce
    reproducible UUIDs for the same input."""
    canon = f"{path}={json.dumps(value, sort_keys=True, default=str)}"
    h = hashlib.sha256(canon.encode()).hexdigest()
    return f"f-{h[:8]}"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
PROVENANCE_SOURCES = {
    "user_stated",      # user wrote this verbatim
    "defaulted",        # lifted from K3 (industry_std / class_reference)
    "derived",          # computed from other facts (e.g. bit_period_cycles)
    "retrieved",        # pulled from top-K nearest trained IC
    "class_floor",      # raised to class spec_floor minimum
    "class_required",   # required by class template (e.g. submodule set)
    "inferred",         # LLM inference, lowest trust
}


@dataclass
class Provenance:
    source: str                                # one of PROVENANCE_SOURCES
    origin: str = ""                           # citation / pointer
    confidence: float = 1.0                    # 0..1
    trust_score: Optional[float] = None        # populated by Phase 2/3 feedback
    auto_decided: bool = False                 # True unless user_stated
    reasoning: str = ""                        # human-readable explanation

    def __post_init__(self):
        if self.source not in PROVENANCE_SOURCES:
            raise ValueError(
                f"unknown provenance source {self.source!r}; "
                f"allowed: {sorted(PROVENANCE_SOURCES)}"
            )
        if self.source != "user_stated":
            self.auto_decided = True


# ---------------------------------------------------------------------------
# Fact
# ---------------------------------------------------------------------------
@dataclass
class Fact:
    """One atomic truth about the IC.

    Attributes
    ----------
    path   : dot-path into the unified design namespace, e.g.
             "overview.purpose", "electrical_characteristics.supply_vbus",
             "commands[0x70].name"
    value  : atomic or structured value (str/int/float/bool/dict/list)
    views  : list of layer codes this fact renders into ("L1","L3","L8R",...).
             A fact may render into multiple layers (e.g. CRC poly → L3+L8R).
    provenance : how we know this
    uuid   : stable short ID
    tags   : free-form labels for filtering (e.g. "required","opcode","otp")
    """
    path: str
    value: Any
    views: List[str]
    provenance: Provenance
    uuid: str = ""
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.uuid:
            self.uuid = _deterministic_uuid(self.path, self.value)
        if not isinstance(self.views, list):
            raise TypeError("views must be a list of layer codes")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "path": self.path,
            "value": self.value,
            "views": list(self.views),
            "tags": list(self.tags),
            "provenance": dataclasses.asdict(self.provenance),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Fact":
        prov = Provenance(**d["provenance"])
        return cls(
            path=d["path"],
            value=d["value"],
            views=list(d["views"]),
            provenance=prov,
            uuid=d.get("uuid", ""),
            tags=list(d.get("tags", [])),
        )


# ---------------------------------------------------------------------------
# Fact graph
# ---------------------------------------------------------------------------
@dataclass
class FactGraph:
    """Collection of facts plus IC metadata."""
    ic_name: str
    class_path: str
    facts: List[Fact] = field(default_factory=list)
    version: int = SCHEMA_VERSION
    metadata: Dict[str, Any] = field(default_factory=dict)

    # -- build -------------------------------------------------------------
    def add(self, fact: Fact) -> None:
        # Replace if same (path, views) tuple already present.
        for i, existing in enumerate(self.facts):
            if existing.path == fact.path and set(existing.views) == set(fact.views):
                self.facts[i] = fact
                return
        self.facts.append(fact)

    def add_fact(
        self,
        path: str,
        value: Any,
        views: Iterable[str],
        source: str,
        origin: str = "",
        confidence: float = 1.0,
        reasoning: str = "",
        tags: Iterable[str] = (),
    ) -> Fact:
        """Convenience wrapper — build Fact + Provenance in one call."""
        prov = Provenance(
            source=source,
            origin=origin,
            confidence=confidence,
            reasoning=reasoning,
        )
        fact = Fact(
            path=path,
            value=value,
            views=list(views),
            provenance=prov,
            tags=list(tags),
        )
        self.add(fact)
        return fact

    # -- query -------------------------------------------------------------
    def by_view(self, view: str) -> List[Fact]:
        return [f for f in self.facts if view in f.views]

    def by_path(self, path: str) -> Optional[Fact]:
        for f in self.facts:
            if f.path == path:
                return f
        return None

    def by_prefix(self, prefix: str) -> List[Fact]:
        return [f for f in self.facts if f.path == prefix or f.path.startswith(prefix + ".") or f.path.startswith(prefix + "[")]

    def paths(self) -> Set[str]:
        return {f.path for f in self.facts}

    # -- persist -----------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "ic_name": self.ic_name,
            "class_path": self.class_path,
            "metadata": self.metadata,
            "facts": [f.to_dict() for f in self.facts],
        }

    def to_yaml(self) -> str:
        try:
            import yaml
        except ImportError:
            raise RuntimeError("PyYAML not installed")
        return yaml.safe_dump(
            self.to_dict(),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FactGraph":
        if d.get("version", 1) != SCHEMA_VERSION:
            raise ValueError(f"unsupported fact-graph version {d.get('version')}")
        fg = cls(
            ic_name=d["ic_name"],
            class_path=d["class_path"],
            metadata=dict(d.get("metadata", {})),
        )
        for entry in d.get("facts", []):
            fg.facts.append(Fact.from_dict(entry))
        return fg

    @classmethod
    def load(cls, path: Path) -> "FactGraph":
        text = Path(path).read_text()
        if str(path).endswith((".yaml", ".yml")):
            import yaml
            d = yaml.safe_load(text)
        else:
            d = json.loads(text)
        return cls.from_dict(d)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if str(path).endswith((".yaml", ".yml")):
            path.write_text(self.to_yaml())
        else:
            path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Canonical layer codes
# ---------------------------------------------------------------------------
LAYER_CODES = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L8R", "L9"]
EXTENSION_LAYER_CODES = ["L10", "L11", "L12", "L13"]
ALL_LAYER_CODES = LAYER_CODES + EXTENSION_LAYER_CODES

# OPT-IN advanced layers — generatable (a caller passes them to render_layers and
# facts tagged with their view render into them) but NOT part of the REQUIRED
# ALL_LAYER_CODES set, so a simple digital block is never forced to carry them and
# the existing "all L docs present" gates (which key on ALL_LAYER_CODES) are
# unaffected. L14-L24 are the advanced/protocol layers; L25-L27 close the
# all-chip-classes coverage gaps (reliability/mission-profile, MEMS/transduction,
# memory-module SPD) found by the cited L1-L24-completeness survey.
ADVANCED_LAYER_CODES = ["L14", "L15", "L16", "L17", "L18", "L19", "L20",
                        "L21", "L22", "L23", "L24", "L25", "L26", "L27"]
GENERATABLE_LAYER_CODES = ALL_LAYER_CODES + ADVANCED_LAYER_CODES

LAYER_FILE_NAMES = {
    "L1":  "L1_DATASHEET.json",
    "L2":  "L2_FRS.json",
    "L3":  "L3_CMD_PROTOCOL.json",
    "L4":  "L4_REGMAP.json",
    # L5 "ADI" = ANALOG-DIGITAL INTERFACE — the analog↔digital boundary spec
    # (ADC/DAC interfaces, mixed-signal pads, PHY analog front-end, reference
    # voltages, sense/trim/test pads). It is a FUNCTIONAL layer, NOT the vendor
    # "Analog Devices Inc." (the acronym unfortunately collides). For a pure-
    # digital design this layer is correctly empty. The human-readable,
    # disambiguated name is in LAYER_TITLES below; the L5_ADI_SPEC.json file name
    # is retained for back-compat (149 references across the plugin).
    "L5":  "L5_ADI_SPEC.json",
    "L6":  "L6_CONTROL_LOGIC.json",
    "L7":  "L7_TEST_DEBUG.json",
    "L8":  "L8_TIMING_WAVEFORM.json",
    "L8R": "L8_RTL_CONSTANTS.json",
    "L9":  "L9_INTEGRATION_SPEC.json",
    "L10": "L10_TEST_CASES.json",
    # L11: the emitted filename is L11_OTP_CONTENT.json — measured in 136/136
    # Phase-1 runs across the fleet, and the name l_doc_taxonomy has always
    # declared. The previous value "L11_CALIBRATION.json" existed in ZERO runs,
    # so every consumer that resolved L11 through this map opened a file that
    # was never written and silently no-opped. Same failure shape as scoring a
    # requirement in a layer the backend does not read.
    #
    # RE-FIXED at the MASTER (tools/phase1_engine) after v1.6.0's bundle-drift
    # rsync overwrote #323's bundled-side fix with this stale master value —
    # the drift test and the declarations-agree test both fired, correctly.
    # The master is the only side that survives a sync; fixing the bundle
    # alone is how this regressed once already.
    "L11": "L11_OTP_CONTENT.json",
    "L12": "L12_BEHAVIORAL_SEQUENCES.json",
    # v0.59 H2: aligned with hardware_pass_attestation_check.py and the
    # v0.50-v0.55 canonical filename. L13 has TWO sections:
    #   • CONTRACT (Phase 1)   — criterion + criterion_params + tester
    #   • EVIDENCE (Phase 2)  — known_pass_bitstream + known_pass_transcript
    # Both live in the same file; Phase 1 fills the contract block and the
    # evidence block stays empty until real-hardware testing happens.
    # The previous v0.58 name `L13_HARDWARE_OBSERVED.json` made the gate
    # silently fail with file-not-found.
    "L13": "L13_LAB_CALIBRATION.json",
    # Advanced / coverage-completeness layers (opt-in, see ADVANCED_LAYER_CODES).
    "L14": "L14_PROTOCOL_VERSIONING.json",
    "L15": "L15_ENCODING_TABLES.json",
    "L16": "L16_COMPLIANCE.json",
    "L17": "L17_CHANNEL_SIGNAL_CATALOG.json",
    "L18": "L18_INTERCONNECT.json",
    "L19": "L19_CONSTRAINTS_PDK.json",
    "L20": "L20_DFT_SCAN.json",
    "L21": "L21_POWER_INTENT.json",
    "L22": "L22_VERIFICATION_PLAN.json",
    "L23": "L23_SECURITY.json",
    "L24": "L24_SIGNOFF.json",
    "L25": "L25_RELIABILITY_MISSION_PROFILE.json",
    "L26": "L26_MECHANICAL_TRANSDUCTION.json",
    "L27": "L27_MEMORY_MODULE_SPD.json",
}

# Human-readable, DISAMBIGUATED layer titles — the authoritative source for any
# report / human-doc that renders a layer name, so cryptic file-name acronyms
# (esp. L5 "ADI") never read as a vendor or get misinterpreted. chip-AGNOSTIC:
# every title is a FUNCTIONAL dimension, never a vendor/SKU.
LAYER_TITLES = {
    "L1":  "Datasheet (top-level function, parameters, pinout)",
    "L2":  "Functional Requirements Specification",
    "L3":  "Command / Protocol (opcodes, handshake, bus protocols)",
    "L4":  "Register Map",
    "L5":  "Analog-Digital Interface (ADC/DAC, mixed-signal pads, PHY AFE) "
           "— NOT the vendor 'Analog Devices Inc.'",
    "L6":  "Control Logic / FSM",
    "L7":  "Test & Debug",
    "L8":  "Timing / Waveform",
    "L8R": "RTL Constants (ports, reset, enums, magic numbers)",
    "L9":  "Integration Specification (sub-modules, file layout)",
    "L10": "Test Cases / Vectors",
    "L11": "Calibration",
    "L12": "Behavioral Sequences",
    "L13": "Lab / Hardware Calibration (contract + evidence)",
    # ── Advanced / protocol layers (L14-L24) — formalized here from the
    # *_protocol_synth.py producers; emitted only when a design carries such
    # content (a simple block leaves them empty). ──────────────────────────
    "L14": "Protocol Versioning",
    "L15": "Encoding / Parameter Tables",
    "L16": "Compliance Properties",
    "L17": "Channel / Signal Catalog",
    "L18": "Interconnect Topology",
    "L19": "Constraints / PDK",
    "L20": "DFT / Scan Topology",
    "L21": "Power Intent (UPF / IEEE 1801)",
    "L22": "Verification Plan",
    "L23": "Security Requirements",
    "L24": "Signoff / Tapeout Checklist",
    # ── Coverage-completeness layers (L25-L27) — added per the L1-L24
    # all-chip-classes survey (cited research): the L1-L24 set is complete for
    # digital/SoC/processor classes but MISSED three whole spec dimensions that
    # some chip classes require. These close that gap; chip-AGNOSTIC and empty
    # for any design that does not need them. ─────────────────────────────────
    "L25": "Reliability / Qualification & Mission-Profile "
           "(JESD47, AEC-Q100/Q200; lifetime-weighted environmental loads "
           "— temperature, humidity, drop/shock, vibration)",
    "L26": "Mechanical / Transduction (MEMS & analog-physical: movable "
           "membranes/cantilevers/springs, transduction principle, stiction "
           "and mechanical failure modes — not captured by any RTL layer)",
    "L27": "Memory-Module Self-Describing Config "
           "(JEDEC SPD — EE1004-v / TSE2004av / SPD5118; module-level metadata "
           "distinct from the on-die register map)",
}
