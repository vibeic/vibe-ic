"""Universal Chiplet Interconnect Express (UCIe 1.1) protocol synth helper.

v0.1.89 — ic_class-gated overlay for `bus_interconnect_protocol`-shaped
specs that exhibit the UCIe structural signature: an OPEN DIE-TO-DIE (D2D)
chiplet interconnect on a single package built as a THREE-LAYER stack
(Physical Layer die-to-die I/O + Die-to-Die Adapter + Protocol Layer)
with the version/name tokens "UCIe" / "Universal Chiplet Interconnect
Express" together with the UCIe-only structural features (chiplet /
die-to-die / D2D Adapter / FDI / RDI / Flit framing with 16-bit CRC +
Retry / always-on sideband / Advanced + Standard Package / module-based
single-ended source-synchronous NRZ mainband). Applies UCIe Consortium
Specification Revision 1.1 (2023) spec-canonical content to L1-L23.

Doctrine — GENERAL not keyword: detection uses canonical STRUCTURAL
wire-level signatures (the three-layer D2D stack, FDI/RDI, Flit/CRC/Retry,
sideband, modules) PLUS the canonical protocol NAME / spec-id token read
from L1/L2/L3 CONTENT. It NEVER reads the input-document filename or the
benchmark folder name (a code review flagged exactly that as a HIGH defect
on the AHB+APB detector; this module does not repeat it — the runner-side
detector predicate in the SIGNATURE section below is evaluated on the
L-doc CONTENT blob `_spi_blob` only).

Sibling disambiguation — UCIe EXTENDS the PCI Express family. The UCIe
Protocol Layer maps PCIe and CXL, and the L-docs name "PCIe"/"CXL", so
the PCI Express structural signature matches and `pcie_gen5_protocol_synth`
(and/or the base `pcie_protocol_synth`) fires FIRST, populating
PCIe-specific L1/L2/L3/L4 values (32 GT/s NRZ, 128b/130b, TLP/DLLP, lane
margining, retimers, four-phase EQ, Config Space, etc.). Because UCIe is a
DIFFERENT protocol that merely CARRIES PCIe/CXL, this module
FORCE-OVERWRITES (direct-assign, NOT setdefault) every L1/L2/L3/L4 key the
PCIe sibling populates, replacing the SerDes/PCIe values with the
UCIe-canonical die-to-die values (module-based single-ended
source-synchronous NRZ mainband, no line code, forwarded clock, Flit +
16-bit CRC + Retry, FDI/RDI, sideband, Standard/Advanced Package,
4-32 GT/s). The UCIe detector REQUIRES the UCIe chiplet/D2D tokens so it
does NOT false-fire on a plain PCIe 5.0 or CXL spec, and the PCIe
detector (which keys on PCI Express SerDes tokens) is harmless here
because UCIe runs last and wins via direct assignment.

Sibling-version disambiguation note: UCIe 1.1 vs UCIe 1.0/2.0 is
distinguished by the spec-version token in L1/L14 content ("Revision 1.1"
/ "UCIe 1.1"); this module writes the 1.1 spec-version/revision-history
while keeping the 1.0-introduced architecture facts (which 1.1 carries
forward unchanged).

SIGNATURE (the runner wires this; evaluated on the L1/L2/L3 content
blob `_spi_blob`, never on a filename):

    is_ucie = (
        ("UCIe" in _spi_blob)
        or ("chiplet" in _spi_blob.lower()
            and "die-to-die" in _spi_blob.lower())
        or ("UCIe" in _spi_blob and "D2D" in _spi_blob)
    )

    Distinct from PCIe/CXL: the predicate REQUIRES the UCIe chiplet /
    die-to-die / D2D tokens, so it cannot fire on a plain PCI Express or
    CXL board-level spec (those have no "UCIe"/"chiplet"+"die-to-die"
    signature). When is_ucie is True the runner should call the PCIe
    sibling synth(s) FIRST (they fire on the carried PCIe/CXL tokens) and
    then call apply_ucie_synth (this module) LAST so the UCIe
    force-overwrites win.

Public entry: `apply_ucie_synth(generated_docs_dir, is_ucie, ucie_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _ensure_dict(d: dict, key: str) -> dict:
    """Return d[key] as a dict, replacing a pre-existing None/empty/non-dict.

    Mirrors the i2s/_l2 setdefault-None fix: a plain setdefault on a key
    whose existing value is None is a no-op and would leave the subkey
    synth skipped, so coerce to an empty dict first.
    """
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

# Canonical UCIe structural facts (UCIe Consortium Spec Rev 1.1, 2023).
_DATA_RATES = [4, 8, 12, 16, 24, 32]
_MODULES_PER_LINK = [1, 2, 4]
_FLIT_SIZES = [64, 256]


def apply_ucie_synth(generated_docs_dir: Path, is_ucie: bool,
                     ucie_ic_name: Optional[str]) -> None:
    """Apply UCIe 1.1 synth when the UCIe signature matched.

    Because UCIe CARRIES PCIe/CXL, the PCIe sibling synth(s) fire first and
    populate PCIe-specific L1/L2/L3/L4 values. This routine
    FORCE-OVERWRITES (direct assignment) every L1/L2/L3/L4 key the PCIe
    sibling populates with the UCIe-canonical die-to-die value.
    """
    if not is_ucie:
        return
    gd = Path(generated_docs_dir)

    # --- Force ic_name across ALL 24 docs FIRST (main + fields docs). ---
    if ucie_ic_name is not None:
        for n in _MAIN_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                d["ic_name"] = ucie_ic_name
                _write(q, d)
        for n in _FIELDS_DOCS:
            q = gd / n
            if q.is_file():
                d = _read(q)
                f = _ensure_dict(d, "fields")
                f["ic_name"] = ucie_ic_name
                d["ic_name"] = ucie_ic_name  # belt-and-braces top-level
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
# L1 — FORCE-OVERWRITE the PCIe-sibling datasheet header + rate facts with
# the UCIe die-to-die chiplet datasheet (UCIe Spec Rev 1.1).
# ----------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d["document_title"] = (
        "Universal Chiplet Interconnect Express (UCIe) Specification")
    d["version"] = "Revision 1.1"
    d["revised_date"] = "2023"
    d["manufacturer"] = "UCIe Consortium"
    d["copyright"] = "© 2023 UCIe Consortium"
    d["abstract"] = (
        "Universal Chiplet Interconnect Express (UCIe) is an open, layered "
        "die-to-die (D2D) interconnect standard for connecting chiplets on a "
        "single package. UCIe defines a three-layer stack — a Physical Layer "
        "(the die-to-die I/O: electrical AFE, bump map, clocking, link "
        "training, lane repair/reversal, sideband), a Die-to-Die Adapter "
        "(reliable delivery: Flit framing, CRC + retry, link-state "
        "management, parameter negotiation, Arb/Mux for multiple protocols), "
        "and a Protocol Layer (maps PCIe, CXL.io/CXL.cache/CXL.mem, and a "
        "generic Streaming/Raw mode carrying protocols such as "
        "AXI/CHI/SFI/CPI). The Adapter exposes the Flit-Aware Die-to-Die "
        "Interface (FDI) to the Protocol Layer and the Raw Die-to-Die "
        "Interface (RDI) to the Physical Layer. UCIe 1.1 is an incremental "
        "revision over UCIe 1.0 (2022). The physical link is built from "
        "uni-directional modules (1, 2, or 4 modules per Link); a Standard "
        "Package module is 16 single-ended data lanes and an Advanced "
        "Package module is 64. Per-lane data rates are 4/8/12/16/24/32 GT/s.")
    d["keywords"] = [
        "UCIe", "Universal Chiplet Interconnect Express", "chiplet",
        "die-to-die", "D2D", "D2D Adapter", "FDI", "RDI", "Flit", "sideband",
        "Advanced Package", "Standard Package", "2.5D interposer", "Raw Mode",
        "Streaming", "PCIe", "CXL", "32 GT/s", "module", "bump pitch",
    ]
    d["external_pins"] = [
        "Mainband data lanes (single-ended, per module): N=16 for Standard "
        "Package, N=64 for Advanced Package, uni-directional, NRZ at "
        "4-32 GT/s",
        "Valid lane (1 single-ended lane per module, per direction) — frames "
        "mainband data",
        "Track / Clock lane (forwarded clock; 1 SE calibration/track lane per "
        "module) — source-synchronous strobe for the mainband",
        "Sideband data + clock (txdatasb / txcksb / rxdatasb / rxcksb): "
        "always-on, 2 lanes/direction @ 800 MHz, for training / debug / "
        "management / register access",
        "vccaon / vccio / vss (always-on power, IO power, ground rails on the "
        "bump map)",
        "RESET / link-init bumps (per-Link reset and initialization)",
    ]
    # Remove the PCIe-sibling lane-rate keys that do not apply.
    d.pop("external_pin_count_per_lane", None)
    d.pop("supported_link_widths_lanes", None)
    d["external_pin_count_per_module_std"] = 16
    d["external_pin_count_per_module_adv"] = 64
    d["supported_modules_per_link"] = list(_MODULES_PER_LINK)
    d["supported_data_rates_GT_s"] = list(_DATA_RATES)
    d["modes_of_operation"] = [
        {"name": "Standard Package (UCIe-S)",
         "package_type": "2D organic substrate", "bump_pitch_um": "100-130",
         "lanes_per_module": 16, "channel_reach_mm": "<= 25",
         "bandwidth_per_module_per_dir_GB_s": 64,
         "note": "Cost-effective, longer reach; mainstream organic "
                 "packaging."},
        {"name": "Advanced Package (UCIe-A)",
         "package_type": "2.5D silicon interposer / bridge (e.g. CoWoS, "
                         "EMIB)",
         "bump_pitch_um": "25-55", "lanes_per_module": 64,
         "channel_reach_mm": "<= 2",
         "bandwidth_per_module_per_dir_GB_s": 256,
         "note": "Power-efficient, high-density; fine bump pitch; spare "
                 "lanes for reliability."},
        {"name": "Raw Mode", "package_type": "either",
         "note": "Protocol Layer connects directly to the Physical Layer "
                 "(RDI), bypassing the D2D Adapter's Flit/CRC/Retry; used "
                 "when the protocol supplies its own reliability."},
    ]
    d["key_features"] = [
        "Open, layered die-to-die (D2D) chiplet interconnect on a single "
        "package — Physical Layer + D2D Adapter + Protocol Layer.",
        "Two package classes: Standard Package (2D organic, bump pitch "
        "100-130 um, reach <=25 mm) and Advanced Package (2.5D "
        "interposer/bridge, 25-55 um, reach <=2 mm).",
        "Per-lane data rates 4/8/12/16/24/32 GT/s; a component must support "
        "all data rates up to its advertised maximum for interoperability.",
        "Module-based Physical Layer: a module is uni-directional with 16 "
        "(Standard) or 64 (Advanced) single-ended data lanes; 1, 2, or 4 "
        "modules form a Link for 1x/2x/4x bandwidth.",
        "Per module a dedicated Valid lane frames the data and a forwarded "
        "Track/clock lane provides the source-synchronous strobe.",
        "Always-on Sideband channel: 2 lanes/direction @ 800 MHz (data + "
        "clock) for training, debug, management, and configuration-register "
        "access.",
        "Flit-based transport in the D2D Adapter — adds a 2B Flit Header and "
        "2B CRC; 64B and 256B Flit formats (256B latency-optimized Flit for "
        "CXL 3.0 / PCIe 6.0 / Streaming).",
        "Reliable delivery in the D2D Adapter: CRC + Retry (replay) and "
        "Link-state management; bypassed in Raw Mode.",
        "Arb/Mux in the Adapter multiplexes multiple protocols over one "
        "physical Link.",
        "Protocol Layer maps PCIe, CXL.io/CXL.cache/CXL.mem, and a generic "
        "Streaming/Raw mode for AXI/CHI/SFI/CPI.",
        "Standardized interfaces: FDI (Flit-Aware Die-to-Die Interface, "
        "Adapter <-> Protocol) and RDI (Raw Die-to-Die Interface, PHY <-> "
        "Adapter) enable plug-and-play IP.",
        "Lane Repair / Lane Reversal on the Physical Layer; spare lanes "
        "(Advanced) or width degradation (Standard) for reliability.",
        "Low end-to-end latency: Tx + Rx < 2 ns (FDI to bump and back); "
        "power efficiency target 0.5 pJ/b (Standard) / 0.25 pJ/b "
        "(Advanced).",
    ]
    d["topology_summary"] = (
        "On-package point-to-point die-to-die Link between two chiplets. "
        "Each Link is built from 1, 2, or 4 uni-directional modules. An SoC "
        "composed of multiple chiplets contains multiple UCIe Links. The "
        "Protocol Layer can also build switched fabrics (e.g. CXL switches) "
        "on top of UCIe-attached chiplets.")
    d["package_summary"] = (
        "UCIe is an on-package chiplet interconnect specification — it "
        "defines the die-to-die electrical bump-out, the link-layer "
        "Flit/CRC/Retry, and the protocol mappings. Mechanical packaging "
        "(Standard 2D organic vs Advanced 2.5D interposer/bridge such as "
        "CoWoS or EMIB) is part of the spec only at the bump-map / "
        "bump-pitch / channel-reach level; full assembly is an OSAT/foundry "
        "concern. The bump-out is specified for interoperability even as bump "
        "pitches shrink.")
    d["use_cases"] = [
        "Heterogeneous chiplet SoCs mixing process nodes / fabs / vendors on "
        "one package",
        "CPU + accelerator + memory chiplet disaggregation (symmetric "
        "coherency mapped over FDI)",
        "CXL.mem memory-expander chiplets mapped on UCIe through FDI",
        "PCIe/CXL accelerator chiplets for volume attach and plug-and-play",
        "Co-packaged optics and partitionable networking-switch dies "
        "connected over on-package UCIe",
        "Reticle-size escape: build a large logical die from multiple smaller "
        "economical chiplets",
    ]
    d["revision_history"] = [
        {"version": "1.0", "date": "2022",
         "description": "Initial UCIe release: three-layer D2D stack (PHY + "
                        "D2D Adapter + Protocol Layer), Standard + Advanced "
                        "Packages, 4-32 GT/s, FDI/RDI, 64B Flit, "
                        "PCIe/CXL/Streaming mappings, sideband."},
        {"version": "1.1", "date": "2023",
         "description": "Incremental revision over 1.0: clarifications and "
                        "errata, register/compliance and RDI/FDI interface "
                        "improvements, reliability and automotive-grade "
                        "enhancements; same layered architecture, package "
                        "classes, data rates, and protocol mappings."},
    ]
    d["overview"] = (
        "Universal Chiplet Interconnect Express (UCIe) is an open industry "
        "standard for connecting chiplets (dies) on a single package, "
        "enabling a mix-and-match chiplet ecosystem across process nodes, "
        "fabs, and vendors. UCIe is organized as three layers. The Physical "
        "Layer is the die-to-die I/O: the electrical analog front end, the "
        "bump map/bump-out, forwarded clocking, link "
        "initialization/training, lane repair and lane reversal, and the "
        "always-on sideband. The D2D Adapter provides reliable delivery: it "
        "frames protocol data into Flits, adds a Flit Header and CRC, "
        "performs retry/replay, manages link state, negotiates parameters, "
        "and (via Arb/Mux) multiplexes multiple protocols; it is bypassed in "
        "Raw Mode. The Protocol Layer maps the actual transport — PCIe, CXL "
        "(CXL.io/CXL.cache/CXL.mem) for volume plug-and-play attach, and a "
        "generic Streaming/Raw mode for protocols like AXI/CHI/SFI/CPI. The "
        "Adapter presents FDI to the Protocol Layer and RDI to the Physical "
        "Layer so IP can be assembled plug-and-play. UCIe supports a "
        "cost-effective Standard Package (2D organic, 16-lane modules, "
        "<=25 mm reach) and a high-density Advanced Package (2.5D "
        "interposer, 64-lane modules, <=2 mm reach), at per-lane rates from "
        "4 to 32 GT/s, delivering Tx+Rx latency under 2 ns. UCIe 1.1 refines "
        "the 1.0 baseline with errata, compliance, and reliability/"
        "automotive enhancements.")
    _write(p, d)


# ----------------------------------------------------------------------
# L2 — FORCE-OVERWRITE the PCIe protocol_overview + FRS with the UCIe
# three-layer D2D model (no line code, forwarded clock, Flit/CRC/Retry).
# ----------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    po["type"] = (
        "Open, layered, point-to-point die-to-die (D2D) chiplet interconnect "
        "on a single package. Three layers: Physical Layer (die-to-die I/O), "
        "Die-to-Die Adapter (Flit framing + CRC/Retry + link-state "
        "management + Arb/Mux), Protocol Layer (PCIe / CXL / Streaming-Raw "
        "mapping). Per-lane rates 4-32 GT/s.")
    po["duplex"] = (
        "full-duplex at the Link level via separate uni-directional modules "
        "(each module is uni-directional; a Link pairs transmit and receive "
        "modules so both directions are simultaneous and continuous). "
        "Sideband is full-duplex (2 lanes/direction).")
    po["synchronous_serial"] = False
    po["source_synchronous"] = True
    po["embedded_clock"] = False
    po["forwarded_clock"] = True
    po["encoding"] = (
        "Unencoded NRZ on the mainband (no 8b/10b or 128b/130b line code); "
        "data integrity is provided at the Adapter by a per-Flit 16-bit CRC "
        "+ retry, not by a DC-balancing line code. A per-module forwarded "
        "Track/clock lane provides the strobe and a Valid lane frames the "
        "data.")
    po["modulation"] = "NRZ (two-level)."
    # Remove PCIe-sibling SerDes keys that do not apply to UCIe.
    for stale in ("line_rate_GT_s", "x16_bandwidth_per_direction_GB_s",
                  "lane_widths_supported", "retimers_max_per_link",
                  "lane_margining_at_receiver",
                  "alternate_protocol_negotiation",
                  "packet_classes_per_layer", "split_transaction",
                  "address_spaces", "max_payload_sizes_bytes_negotiated",
                  "virtual_channels_max", "traffic_classes_max",
                  "flow_control"):
        po.pop(stale, None)
    po["data_rates_GT_s"] = list(_DATA_RATES)
    po["lanes_per_module"] = {"standard_package": 16, "advanced_package": 64}
    po["modules_per_link_supported"] = list(_MODULES_PER_LINK)
    po["bandwidth_per_module_per_dir_GB_s"] = {
        "standard_package": 64, "advanced_package": 256}
    po["layers"] = [
        "Protocol Layer (maps PCIe / CXL.io / CXL.cache / CXL.mem / "
        "Streaming(AXI/CHI/SFI/CPI))",
        "Die-to-Die Adapter (Flit framing, 16-bit CRC, Retry/replay, "
        "link-state management, parameter negotiation, Arb/Mux) — exposes "
        "FDI up, RDI down",
        "Physical Layer = die-to-die I/O (AFE, bump map, forwarded clock, "
        "training, lane repair/reversal, sideband)",
    ]
    po["interfaces"] = {
        "FDI": "Flit-Aware Die-to-Die Interface — between the Protocol Layer "
               "and the D2D Adapter.",
        "RDI": "Raw Die-to-Die Interface — between the D2D Adapter and the "
               "Physical Layer.",
    }
    po["flit_based"] = True
    po["flit_formats"] = [
        "64-byte Flit (2B Flit Header + 62B payload + 2B CRC region)",
        "256-byte Flit",
        "256-byte Latency-Optimized Flit (CXL 3.0 / PCIe 6.0 / Streaming)",
    ]
    po["reliable_delivery"] = (
        "D2D Adapter adds a 2-byte Flit Header and a 2-byte (16-bit) CRC per "
        "Flit and performs retry/replay; bypassed in Raw Mode.")
    po["raw_mode"] = (
        "Protocol Layer talks straight to the Physical Layer over RDI, "
        "bypassing the Adapter's Flit/CRC/Retry (the protocol supplies its "
        "own reliability).")
    po["sideband"] = (
        "Always-on auxiliary channel; 2 lanes per direction at 800 MHz "
        "(data + clock); carries training, debug, management, and "
        "configuration-register access.")
    po["packages_supported"] = [
        "Standard Package (2D organic, bump pitch 100-130 um, reach <=25 mm)",
        "Advanced Package (2.5D interposer/bridge, bump pitch 25-55 um, reach "
        "<=2 mm)",
    ]
    po["protocols_mapped"] = [
        "PCIe", "CXL.io", "CXL.cache", "CXL.mem",
        "Streaming / Raw (AXI, CHI, SFI, CPI, ...)",
    ]
    po["latency_tx_plus_rx_ns"] = "< 2"
    po["power_efficiency_pJ_per_bit"] = {
        "standard_package": 0.5, "advanced_package": 0.25}
    d["functional_requirements"] = [
        {"id": "FR-LAYER-01", "text": "UCIe is organized as three layers — "
         "Physical Layer (die-to-die I/O), D2D Adapter (reliable delivery), "
         "and Protocol Layer (protocol mapping) — with FDI between Protocol "
         "and Adapter and RDI between Adapter and Physical Layer."},
        {"id": "FR-PKG-02", "text": "Two package classes are supported per "
         "implementation choice: Standard Package (2D organic, 100-130 um "
         "bump pitch, channel reach <=25 mm, 16-lane module) and Advanced "
         "Package (2.5D interposer/bridge, 25-55 um bump pitch, reach "
         "<=2 mm, 64-lane module)."},
        {"id": "FR-RATE-03", "text": "Per-lane data rate is one of 4, 8, 12, "
         "16, 24, or 32 GT/s. A component MUST support all data rates up to "
         "its advertised maximum for interoperability (e.g. a 12G device "
         "must also support 4/8/12 GT/s)."},
        {"id": "FR-MODULE-04", "text": "The Physical Layer unit is one module "
         "(uni-directional); 1, 2, or 4 modules form a Link, scaling "
         "bandwidth 1x/2x/4x. A Standard module is 16 single-ended data "
         "lanes; an Advanced module is 64."},
        {"id": "FR-VALIDCLK-05", "text": "Each module carries, per direction, "
         "the data lanes plus 1 Valid lane (frames the data) and a forwarded "
         "Track/clock lane (source-synchronous strobe)."},
        {"id": "FR-SIDEBAND-06", "text": "An always-on Sideband channel "
         "(2 lanes/direction @ 800 MHz, data + clock) is used for training, "
         "debug, management, and configuration-register access; it does not "
         "carry mainband data."},
        {"id": "FR-FLIT-07", "text": "The D2D Adapter frames protocol data "
         "into Flits, adding a 2-byte Flit Header and a 2-byte (16-bit) CRC. "
         "64-byte and 256-byte Flit formats are defined, including a "
         "256-byte Latency-Optimized Flit for CXL 3.0 / PCIe 6.0 / "
         "Streaming."},
        {"id": "FR-CRCRETRY-08", "text": "The D2D Adapter provides reliable "
         "delivery via per-Flit CRC and a Retry/replay mechanism, plus "
         "link-state management; these are bypassed in Raw Mode."},
        {"id": "FR-ARBMUX-09", "text": "When multiple protocols share one "
         "physical Link, the D2D Adapter's Arb/Mux multiplexes and "
         "arbitrates between them."},
        {"id": "FR-RAW-10", "text": "In Raw Mode the Protocol Layer connects "
         "directly to the Physical Layer over RDI, bypassing the Adapter's "
         "Flit/CRC/Retry; the protocol must then supply its own "
         "reliability."},
        {"id": "FR-PROTO-11", "text": "The Protocol Layer maps PCIe and CXL "
         "(CXL.io/CXL.cache/CXL.mem) for volume plug-and-play attach, and a "
         "generic Streaming/Raw mode for arbitrary protocols (e.g. AXI, CHI, "
         "SFI, CPI)."},
        {"id": "FR-REPAIR-12", "text": "The Physical Layer supports Lane "
         "Repair and Lane Reversal; reliability is achieved with spare lanes "
         "(Advanced Package) or width degradation (Standard Package)."},
        {"id": "FR-INTEROP-13", "text": "Interoperability is achieved by a "
         "fixed, specified bump-out, RDI/FDI interface conformance, and a "
         "compliance program; bump-out is specified to interoperate across "
         "bump pitches and future pitch reductions."},
    ]
    d["error_response_conditions"] = [
        "Flit CRC mismatch at the D2D Adapter — triggers Retry/replay of the "
        "Flit.",
        "Retry threshold exceeded — link-state management escalates "
        "(re-train or link down).",
        "Lane failure detected during training — Lane Repair (use a spare "
        "lane in Advanced) or width degradation (Standard).",
        "Sideband training/handshake failure — link initialization does not "
        "complete.",
        "Parameter-negotiation mismatch over sideband — incompatible data "
        "rate / width / protocol; link falls back or fails to bring up.",
        "Raw Mode integrity error — not detected by UCIe (no Adapter CRC); "
        "the mapped protocol's own mechanisms must handle it.",
    ]
    d["compliance_requirements"] = [
        "Three-layer stack with conformant FDI (Adapter<->Protocol) and RDI "
        "(Adapter<->PHY).",
        "Specified bump-out for the chosen package class (Standard or "
        "Advanced) at the specified bump pitch.",
        "Support all data rates up to the advertised maximum (4..max GT/s).",
        "Always-on Sideband (2 lanes/direction @ 800 MHz) for "
        "training/management/registers.",
        "Flit framing with 2B Flit Header + 16-bit CRC + Retry in the D2D "
        "Adapter (except Raw Mode).",
        "Link-state management and parameter negotiation over the "
        "Adapter/sideband.",
        "Lane Repair / Lane Reversal in the Physical Layer; spare-lane or "
        "width-degradation reliability.",
        "At least one Protocol Layer mapping: PCIe, CXL, or Streaming.",
        "End-to-end Tx+Rx latency target < 2 ns; configuration registers "
        "exposed for discovery and run-time.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L3 — FORCE-OVERWRITE the PCIe channels / framing / addressing with the
# UCIe module + Flit + FDI/RDI model.
# ----------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Layered die-to-die packet/Flit protocol. The Protocol Layer hands "
        "protocol traffic (PCIe / CXL / Streaming) to the D2D Adapter over "
        "FDI; the Adapter frames it into Flits (2B Flit Header + payload + "
        "2B/16-bit CRC), performs Retry/replay and link-state management, "
        "optionally Arb/Muxes multiple protocols, and passes the Flit stream "
        "to the Physical Layer over RDI; the Physical Layer serializes it as "
        "unencoded NRZ across the module's data lanes with a Valid lane and "
        "a forwarded Track/clock, at 4-32 GT/s. In Raw Mode the Adapter is "
        "bypassed and the Protocol Layer drives the Physical Layer "
        "directly.")
    d["channels"] = [
        {"name": "Mainband data lanes",
         "direction": "uni-directional per module (TX module + RX module "
                      "form a Link)",
         "description": "16 single-ended data lanes (Standard Package) or 64 "
         "(Advanced Package), unencoded NRZ at 4-32 GT/s, source-synchronous "
         "to the forwarded Track/clock; framed by the Valid lane."},
        {"name": "Valid lane", "direction": "per module, per direction",
         "description": "1 single-ended lane that frames/qualifies the "
         "mainband data on the module."},
        {"name": "Track / Clock lane",
         "direction": "per module, per direction",
         "description": "Forwarded clock / calibration-track lane providing "
         "the source-synchronous strobe for the mainband data lanes."},
        {"name": "Sideband (txdatasb/txcksb, rxdatasb/rxcksb)",
         "direction": "full-duplex (2 lanes/direction)",
         "description": "Always-on auxiliary channel @ 800 MHz (data + clock "
         "per direction) for link training, debug, management, and "
         "configuration-register access."},
        {"name": "Power / ground (vccaon, vccio, vss)",
         "direction": "supply",
         "description": "Always-on power, IO power, and ground rails "
         "interleaved in the bump map."},
    ]
    d["layer_stack"] = [
        {"layer": "Protocol Layer",
         "purpose": "Maps the carried protocol onto UCIe. Volume protocols "
         "PCIe and CXL (CXL.io/CXL.cache/CXL.mem) for plug-and-play; "
         "Streaming/Raw mode for arbitrary protocols (AXI/CHI/SFI/CPI).",
         "interface_down": "FDI (Flit-Aware Die-to-Die Interface)"},
        {"layer": "Die-to-Die Adapter",
         "purpose": "Reliable delivery: Flit framing (2B header), 16-bit CRC "
         "+ Retry/replay, link-state management, parameter negotiation, "
         "Arb/Mux when multiple protocols share a Link. Bypassed in Raw "
         "Mode.",
         "interface_up": "FDI",
         "interface_down": "RDI (Raw Die-to-Die Interface)"},
        {"layer": "Physical Layer",
         "purpose": "Die-to-die I/O: analog front end / clocking, bump map / "
         "bump-out, link initialization & training, lane repair / lane "
         "reversal, sideband, per-module Valid + Track/clock + data lanes.",
         "interface_up": "RDI"},
    ]
    d["flit_format"] = {
        "flit_64B": {"size_bytes": 64, "flit_header_bytes": 2,
                     "crc_bytes": 2, "crc_width_bits": 16, "payload_bytes": 60,
                     "note": "Adapter adds a 2-byte Flit Header and a 2-byte "
                     "CRC; example shows 62B of Flit-1 payload with "
                     "header+CRC across the 64-byte boundary."},
        "flit_256B": {"size_bytes": 256, "usage": "CXL 3.0 / PCIe 6.0"},
        "flit_256B_latency_optimized": {
            "size_bytes": 256, "usage": "CXL 3.0 / Streaming",
            "note": "Latency-optimized 256-byte Flit format."},
    }
    d["flit_header_fields"] = [
        "Protocol / format identifier",
        "Sequence number (for retry/replay tracking)",
        "Reserved (Rsvd) bits",
    ]
    d["crc_retry"] = {
        "crc_width_bits": 16,
        "crc_location": "appended per Flit by the D2D Adapter",
        "retry": "On CRC failure the Adapter replays the Flit(s); sample RTL "
                 "code for the CRC is provided in the spec.",
        "bypassed_in_raw_mode": True,
    }
    d["raw_mode"] = {
        "definition": "Protocol Layer connects directly to the Physical "
                      "Layer over RDI, bypassing the D2D Adapter's "
                      "Flit/CRC/Retry.",
        "use": "When the carried protocol provides its own reliability and "
               "lowest latency is required.",
    }
    d["arb_mux"] = {
        "purpose": "Arbitrate and multiplex multiple protocols (e.g. CXL.io "
                   "+ CXL.cache + CXL.mem, or PCIe + Streaming) over a single "
                   "physical Link.",
        "location": "D2D Adapter",
    }
    d["protocols_mapped"] = [
        {"protocol": "PCIe", "via": "FDI",
         "use": "Volume attach, plug-and-play with existing software."},
        {"protocol": "CXL.io", "via": "FDI",
         "use": "I/O / discovery / config."},
        {"protocol": "CXL.cache", "via": "FDI",
         "use": "Coherent accelerator caching."},
        {"protocol": "CXL.mem", "via": "FDI",
         "use": "Memory expander / pooling."},
        {"protocol": "Streaming / Raw", "via": "FDI or RDI(raw)",
         "use": "Arbitrary protocols: AXI / CHI / SFI / CPI / symmetric "
                "coherency."},
    ]
    d["valid_ready_handshake_rules"] = [
        "FDI and RDI define valid/credit handshakes between "
        "Protocol<->Adapter and Adapter<->PHY.",
        "The Valid lane frames mainband data on each module so the receiver "
        "knows which UI carry valid data.",
        "Reliable delivery is guaranteed by the Adapter's per-Flit CRC + "
        "Retry (sequence-number tracked).",
        "Link bring-up, parameter exchange (data rate, width, protocol), and "
        "state changes are negotiated over the always-on sideband.",
        "Arb/Mux arbitrates when multiple protocols are active on one Link.",
    ]
    # FORCE-OVERWRITE the PCIe-sibling burst/header/addressing keys.
    d["burst_based"] = False
    d["byte_oriented"] = False
    d["flit_oriented"] = True
    d.pop("tlp_header_format", None)
    d.pop("transaction_classes_split", None)
    d.pop("packet_classes", None)
    d.pop("physical_layer_block_format", None)
    d.pop("alternate_protocol_negotiation", None)
    d["addressing"] = {
        "note": "UCIe itself is an addressless transport layer; addressing "
                "belongs to the carried protocol (PCIe/CXL/Streaming) above "
                "FDI. The Adapter tracks Flits by sequence number for retry, "
                "not by address.",
        "sequence_number_in_flit_header": True,
    }
    d["frame_format"] = {
        "mainband_framing": "Per module: data lanes + 1 Valid lane (frames "
        "the data) + forwarded Track/clock lane providing the strobe; "
        "unencoded NRZ, no line-code framing tokens.",
        "flit_framing": "D2D Adapter packs protocol bytes into 64B/256B "
        "Flits with a 2B Flit Header and 2B (16-bit) CRC.",
        "sideband_framing": "Separate always-on 800 MHz sideband (2 "
        "lanes/direction) carries training/management/register packets, not "
        "mainband Flits.",
        "note": "UCIe does NOT use an 8b/10b or 128b/130b line code; "
        "integrity is at the Flit/CRC level, and clocking is "
        "source-synchronous (forwarded clock), not embedded.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L4 — FORCE-OVERWRITE the PCIe Config-Space regmap with the UCIe
# sideband-accessible D2D register model.
# ----------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    d["notes"] = (
        "UCIe defines configuration/status registers (accessed over the "
        "always-on sideband) for discovery and run-time control of the Link: "
        "capabilities, data-rate/width/protocol negotiation, link-state, "
        "training/repair status, and CRC/Retry status. These are UCIe's own "
        "D2D registers, separate from the carried protocol's register space "
        "(e.g. PCIe Config Space, CXL registers) which live above the "
        "Protocol Layer.")
    # Remove PCIe-sibling Config-Space keys that do not apply to UCIe.
    for stale in ("configuration_space_overview",
                  "type0_header_significant_fields",
                  "type1_header_significant_fields",
                  "pcie_capability_structure_offsets_relative",
                  "pcie_extended_capability_structures",
                  "gen5_specific_register_fields",
                  "data_link_layer_protocol_fields",
                  "transaction_layer_protocol_fields"):
        d.pop(stale, None)
    d["register_access"] = {
        "transport": "Always-on Sideband (2 lanes/direction @ 800 MHz)",
        "purpose": "Discovery, capability advertisement, parameter "
                   "negotiation, link-state control, run-time management and "
                   "debug.",
        "available_before_mainband_up": True,
    }
    d["register_groups"] = [
        {"group": "Capability / Discovery Registers", "fields": [
            "Supported package class (Standard / Advanced)",
            "Supported maximum data rate (4..32 GT/s) and all lower rates",
            "Module count / width capability (1/2/4 modules; 16 or 64 "
            "lanes/module)",
            "Supported protocols (PCIe / CXL.io / CXL.cache / CXL.mem / "
            "Streaming)",
            "Flit format support (64B / 256B / 256B latency-optimized)",
            "Raw Mode support",
            "Lane Repair / spare-lane capability"]},
        {"group": "Link Control Registers", "fields": [
            "Target data rate select",
            "Link width / module-count select",
            "Protocol select / Arb-Mux enable",
            "Raw Mode enable (bypass Adapter Flit/CRC/Retry)",
            "Link-state request (reset, training, active, low-power "
            "entry/exit)"]},
        {"group": "Link Status Registers", "fields": [
            "Current link state (per link-state FSM)",
            "Negotiated data rate / width / protocol",
            "Training / initialization status",
            "Lane Repair / Lane Reversal status (which lanes remapped)",
            "CRC error / Retry counters"]},
        {"group": "Reliability / Debug Registers", "fields": [
            "Per-lane error / margin status",
            "Spare-lane usage (Advanced) / width-degradation status "
            "(Standard)",
            "FIT / reliability counters (UCIe Flit Mode)",
            "Sideband loopback / debug controls"]},
    ]
    d["carried_protocol_register_spaces"] = {
        "note": "The Protocol Layer's carried protocol keeps its own "
                "software-visible register/config space, untouched by UCIe.",
        "examples": [
            "PCIe: 256 B PCI-compatible Config Space + up to 4096 B Extended "
            "Config Space",
            "CXL: CXL.io DVSEC + CXL.cache/CXL.mem registers",
            "Streaming: protocol-defined (e.g. AXI/CHI control)"],
    }
    d["flit_protocol_fields"] = {
        "flit_header_bytes": 2, "crc_width_bits": 16, "crc_bytes": 2,
        "sequence_number_present": True,
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L5 — overwrite the PCIe SerDes analog spec with UCIe single-ended
# source-synchronous die-to-die signaling.
# ----------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "Per-module single-ended (not differential) data lanes carrying "
        "unencoded NRZ at 4/8/12/16/24/32 GT/s, source-synchronous to a "
        "per-module forwarded Track/clock lane, with a per-module Valid lane "
        "framing the data. The very short, low-loss on-package channel "
        "(Advanced <=2 mm, Standard <=25 mm) and fine bump pitch permit "
        "single-ended signaling without a DC-balancing line code; integrity "
        "is provided at the D2D Adapter by a 16-bit per-Flit CRC + Retry. A "
        "separate always-on sideband (2 lanes/direction @ 800 MHz) handles "
        "training, management, and registers. UCIe targets Tx+Rx latency "
        "< 2 ns and power efficiency 0.5 pJ/b (Standard) / 0.25 pJ/b "
        "(Advanced).")
    d["modulation"] = "NRZ (two-level), single-ended, unencoded mainband."
    d["clocking"] = (
        "Source-synchronous forwarded clock (Track lane), NOT an "
        "embedded/recovered clock. The receiver samples the data lanes "
        "against the forwarded clock; a calibration/track lane maintains "
        "alignment.")
    # Remove PCIe-sibling SerDes/EQ/retimer/margining keys.
    for stale in ("transmitter_specs_canonical", "receiver_specs_canonical",
                  "retimers", "equalization_phases", "lane_margining",
                  "electrical_idle"):
        d.pop(stale, None)
    d["transmitter_specs_canonical"] = {
        "data_rates_GT_s": list(_DATA_RATES),
        "modulation": "NRZ",
        "signaling": "single-ended",
        "line_encoding": "none (unencoded; integrity via Adapter 16-bit Flit "
                         "CRC + Retry)",
        "lanes_per_module_standard": 16,
        "lanes_per_module_advanced": 64,
        "per_module_extra_lanes": "1 Valid lane + 1 forwarded Track/clock "
                                  "lane (per direction)",
        "forwarded_clock": True,
        "interop_rule": "Must support all data rates up to the advertised "
                        "maximum.",
    }
    d["receiver_specs_canonical"] = {
        "data_rates_GT_s": list(_DATA_RATES),
        "clock_strobe": "Samples data lanes against the per-module forwarded "
                        "Track/clock.",
        "valid_framing": "Uses the Valid lane to qualify mainband data.",
        "lane_repair": "Can remap a failing data lane to a spare lane "
                       "(Advanced) or degrade width (Standard).",
        "calibration": "Per-module track/calibration lane maintains receiver "
                       "sampling alignment.",
    }
    d["packages"] = {
        "standard_package": {
            "type": "2D organic substrate", "bump_pitch_um": "100-130",
            "channel_reach_mm": "<= 25", "lanes_per_module": 16,
            "bandwidth_per_module_per_dir_GB_s": 64,
            "bump_out": "UCIe-S (Standard) bump-out, stacked or unstacked "
                        "variants"},
        "advanced_package": {
            "type": "2.5D silicon interposer / bridge (e.g. CoWoS, EMIB, "
                    "FoCoS)",
            "bump_pitch_um": "25-55", "channel_reach_mm": "<= 2",
            "lanes_per_module": 64,
            "bandwidth_per_module_per_dir_GB_s": 256,
            "bump_out": "UCIe-A (Advanced) bump-out; supports spare lanes for "
                        "repair"},
    }
    d["sideband"] = {
        "always_on": True, "lanes_per_direction": 2, "frequency_MHz": 800,
        "carries": "data + clock; used for training, debug, management, "
                   "configuration registers.",
        "note": "Leverages depopulated bumps so it adds no extra shoreline.",
    }
    d["bandwidth_shoreline"] = {
        "standard_package_GB_s_per_mm": "28-224",
        "advanced_package_GB_s_per_mm": "165-1317"}
    d["bandwidth_density"] = {
        "standard_package_GB_s_per_mm2": "22-125",
        "advanced_package_GB_s_per_mm2": "188-1350"}
    d["power_efficiency_pJ_per_bit"] = {
        "standard_package": 0.5, "advanced_package": 0.25}
    d["latency"] = {
        "tx_plus_rx_ns": "< 2",
        "scope": "Includes D2D Adapter and PHY (FDI to bump and back).",
        "low_power_entry_exit_latency": "0.5 ns at <=16 GT/s; 0.5-1 ns at "
                                        ">=24 GT/s.",
    }
    d["reliability"] = {
        "fit_target": "0 < FIT << 1 (~1E-10 failures/hour) with UCIe Flit "
                      "Mode",
        "mechanism": "Spare lanes (Advanced) / width degradation (Standard) "
                     "+ Flit CRC/Retry.",
    }
    d["encoding_role_in_analog"] = (
        "Because the on-package channel is extremely short and low-loss, "
        "UCIe omits a line code (no 8b/10b / 128b/130b) and uses a forwarded "
        "clock; transition density and DC balance are not required for clock "
        "recovery. Data integrity is instead handled digitally by the 16-bit "
        "Flit CRC + Retry in the D2D Adapter.")
    _write(p, d)


# ----------------------------------------------------------------------
# L6 — overwrite the PCIe LTSSM FSM with the UCIe link-state-management
# FSM (SBINIT/MBINIT/MBTRAIN/LINKINIT/ACTIVE).
# ----------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    # Remove PCIe-sibling FSM keys.
    for stale in ("fsm_states_ltssm", "fsm_states_equalization",
                  "fsm_states_data_link_layer", "fsm_states_tlp_transmitter",
                  "fsm_states_tlp_receiver"):
        d.pop(stale, None)
    d["fsm_states_link_state_management"] = [
        {"name": "RESET", "description": "Initial state after power-up / "
         "reset assertion. PHY and Adapter held; sideband prepared for "
         "bring-up."},
        {"name": "SBINIT", "description": "Sideband initialization — the "
         "always-on 800 MHz sideband (2 lanes/direction) is brought up first "
         "to carry training and parameter exchange."},
        {"name": "MBINIT", "description": "Mainband initialization — detect/"
         "repair lanes, establish the forwarded Track/clock and Valid "
         "framing per module, calibrate the data lanes."},
        {"name": "MBTRAIN", "description": "Mainband training — per-lane "
         "timing/voltage calibration at the negotiated data rate (4-32 "
         "GT/s); lane repair/reversal applied; data rate may step up toward "
         "the advertised maximum."},
        {"name": "LINKINIT", "description": "Link initialization — D2D "
         "Adapter parameter negotiation (data rate, width/module-count, "
         "protocol, Flit format, Raw vs Flit mode) completes; Adapter "
         "reaches operational."},
        {"name": "ACTIVE (L0)", "description": "Operational state — Flits "
         "flow across the mainband with CRC/Retry (unless Raw Mode); both "
         "directions active and continuous."},
        {"name": "L1", "description": "Link power-saving standby; fast "
         "entry/exit (0.5 ns <=16G, 0.5-1 ns >=24G); link state preserved."},
        {"name": "L2", "description": "Deeper low-power / sleep; re-entry "
         "requires re-training of the mainband."},
        {"name": "TRAINERROR / REPAIR", "description": "Recovery state on "
         "training failure or lane fault — invoke Lane Repair (spare lane, "
         "Advanced) or width degradation (Standard), then re-train."},
    ]
    d["fsm_states_d2d_adapter"] = [
        {"name": "ADAPTER_RESET", "description": "Adapter held in reset; "
         "FDI/RDI idle."},
        {"name": "PARAM_EXCHANGE", "description": "Negotiate data rate, "
         "width, protocol, Flit format, Raw vs Flit, and CRC/Retry "
         "parameters over the sideband."},
        {"name": "ADAPTER_ACTIVE", "description": "Flit framing + 16-bit CRC "
         "+ Retry + Arb/Mux running; reliable delivery in effect (or "
         "bypassed in Raw Mode)."},
        {"name": "RETRY", "description": "CRC mismatch detected — replay the "
         "failed Flit(s) from the retry buffer using the Flit-header "
         "sequence number."},
    ]
    d["fsm_states_tx_flit"] = [
        {"name": "TX_MAP", "description": "Protocol Layer presents protocol "
         "data over FDI."},
        {"name": "TX_FRAME", "description": "Adapter builds the Flit: 2B Flit "
         "Header + payload + 16-bit CRC."},
        {"name": "TX_RDI", "description": "Adapter hands the Flit stream to "
         "the PHY over RDI."},
        {"name": "TX_SERIAL", "description": "PHY serializes NRZ across the "
         "module data lanes with Valid framing + forwarded clock at the "
         "negotiated rate."},
        {"name": "TX_RETRY", "description": "Retry buffer holds transmitted "
         "Flits until acknowledged; replay on CRC NAK."},
    ]
    d["fsm_states_rx_flit"] = [
        {"name": "RX_SAMPLE", "description": "PHY samples data lanes against "
         "the forwarded clock, qualified by Valid."},
        {"name": "RX_DEFRAME", "description": "Adapter recovers Flits from "
         "the RDI stream and checks the 16-bit CRC."},
        {"name": "RX_CRC", "description": "Good CRC -> accept + advance "
         "sequence; bad CRC -> request Retry."},
        {"name": "RX_FDI", "description": "Adapter delivers accepted protocol "
         "data to the Protocol Layer over FDI."},
    ]
    d["fsm_hints"] = {
        "trigger": "Reset deassertion triggers RESET -> SBINIT (sideband "
        "first) -> MBINIT -> MBTRAIN -> LINKINIT -> ACTIVE. Sideband must be "
        "up before mainband training because parameter negotiation and "
        "register access ride the sideband.",
        "rule": "Each transmitted Flit is held in the retry buffer and freed "
        "when acknowledged; a 16-bit CRC mismatch triggers replay tracked by "
        "the Flit-header sequence number.",
        "abort": "Persistent training failure or exhausted lane-repair "
        "resources escalates to TRAINERROR/REPAIR; if unrecoverable the link "
        "stays down or degrades width/rate.",
    }
    d["anti_deadlock_rule"] = (
        "Credit/valid-based flow control on FDI and RDI prevents buffer "
        "overflow; the Arb/Mux fairly arbitrates multiple protocols so no "
        "single protocol can starve the Link; the retry buffer is bounded "
        "and replays in sequence-number order.")
    d["exit_from_reset_or_poweron"] = (
        "On reset deassertion the link brings up the sideband (SBINIT), then "
        "initializes and trains the mainband (MBINIT, MBTRAIN) including lane "
        "repair/reversal, then the D2D Adapter negotiates parameters "
        "(LINKINIT) and reaches ACTIVE, at which point Flits flow with "
        "CRC/Retry. Data rate ramps from a low rate up to the advertised "
        "maximum during MBTRAIN.")
    d["default_ready_state_recommendation"] = {
        "TX_idle": "Hold Valid de-asserted (no valid mainband data) while "
        "keeping the forwarded clock running; sideband stays always-on.",
        "TX_active": "Assert Valid and drive Flits when the Adapter has data "
        "and the link is ACTIVE.",
        "RX_idle": "Sample but discard when Valid is de-asserted; sideband "
        "always monitored for management/register traffic.",
    }
    d["configurations"] = [
        {"name": "1-module Link", "description": "Single uni-directional "
         "module per direction; 1x bandwidth (16 lanes Std / 64 lanes Adv)."},
        {"name": "2-module Link", "description": "Two modules per direction; "
         "2x bandwidth."},
        {"name": "4-module Link", "description": "Four modules per direction; "
         "4x bandwidth."},
    ]
    d["timing_dependency_rule"] = (
        "Each module is source-synchronous: data lanes are sampled against "
        "that module's forwarded Track/clock with the Valid lane qualifying "
        "data. Multi-module Links must align/de-skew the modules. The "
        "sideband runs continuously at 800 MHz independent of the mainband "
        "data rate (4-32 GT/s).")
    _write(p, d)


# ----------------------------------------------------------------------
# L7 — overwrite the PCIe observability with the UCIe sideband/register/
# CRC-Retry observability.
# ----------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "Sideband management / register access", "purpose": "The "
         "always-on 800 MHz sideband (2 lanes/direction) provides in-band "
         "controllability and observability for training, debug, and "
         "configuration-register read/write before and during operation."},
        {"name": "Lane Repair / Lane Reversal status", "purpose": "Config "
         "registers report which data lanes were remapped to spare lanes "
         "(Advanced) or which width-degradation occurred (Standard)."},
        {"name": "CRC error / Retry counters", "purpose": "The D2D Adapter "
         "exposes Flit CRC-error and Retry counts as run-time reliability "
         "observability."},
        {"name": "Link-state observability", "purpose": "Current "
         "link-state-FSM state, negotiated data rate / width / protocol, and "
         "training status are register-readable over the sideband."},
        {"name": "Per-lane margin / error status", "purpose": "Training and "
         "run-time per-lane status supports signal-integrity debug at the "
         "bump level."},
        {"name": "Sideband loopback / debug", "purpose": "Loopback and debug "
         "controls allow characterization of the link without the carried "
         "protocol."},
    ]
    d["error_detection_mechanisms"] = [
        "16-bit per-Flit CRC at the D2D Adapter detects mainband bit errors "
        "(Flit Mode).",
        "Retry/replay corrects detected Flit errors using the Flit-header "
        "sequence number.",
        "Lane-failure detection during training triggers Lane Repair (spare "
        "lane) or width degradation.",
        "Sideband handshake/parameter mismatch detection during bring-up.",
        "Raw Mode has no UCIe-level CRC; the carried protocol's own "
        "integrity mechanisms apply.",
    ]
    d["test_modes"] = [
        {"name": "Compliance / Interoperability test", "purpose": "UCIe "
         "Compliance Program validates electrical, logical, protocol, and "
         "software conformance against the spec for plug-and-play "
         "interoperability."},
        {"name": "Sideband loopback", "purpose": "Exercise the always-on "
         "sideband independently for bring-up debug."},
        {"name": "Mainband training / pattern test", "purpose": "Per-lane "
         "calibration and pattern checking during MBTRAIN at the target data "
         "rate."},
        {"name": "Lane repair test", "purpose": "Force a lane fault and "
         "verify spare-lane remap (Advanced) or width degradation "
         "(Standard)."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "Link Up / Link Down", "trigger": "Link-state FSM "
         "enters/exits ACTIVE."},
        {"event": "Lane repair invoked", "trigger": "A data lane fails and "
         "is remapped to a spare / width degrades."},
        {"event": "CRC error / Retry", "trigger": "Flit CRC mismatch "
         "triggers replay; counters increment."},
        {"event": "Low-power entry/exit", "trigger": "Link transitions "
         "to/from L1/L2."},
        {"event": "Parameter renegotiation", "trigger": "Data rate / width / "
         "protocol change requested over sideband."},
    ]
    d["notes"] = (
        "UCIe builds in-system observability around the always-on sideband "
        "(registers, link-state, counters) and the D2D Adapter's CRC/Retry "
        "telemetry. Conformance is established through the UCIe Compliance "
        "Program (electrical, logical, protocol, software). Chip-level "
        "JTAG/scan/BIST remain SoC-integrator concerns; UCIe's protocol-level "
        "test surface is the sideband + configuration registers + Flit "
        "CRC/Retry counters.")
    _write(p, d)


# ----------------------------------------------------------------------
# L8 RTL constants — overwrite PCIe 128b/130b constants with UCIe module +
# Flit + sideband constants.
# ----------------------------------------------------------------------
def _l8_rtl(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    # Remove PCIe-sibling SerDes/Config-Space constants.
    for stale in ("GEN5_LINE_RATE_GT_S", "ENCODING", "BLOCK_SIZE_BITS",
                  "SYNC_HEADER_BITS", "BLOCK_PAYLOAD_BITS", "UNIT_INTERVAL_PS",
                  "GEN5_PER_LANE_RAW_BW_Gbps",
                  "GEN5_PER_LANE_EFFECTIVE_BW_Gbps",
                  "X16_BW_PER_DIRECTION_GB_S",
                  "LANE_WIDTH_PER_DIRECTION_DIFF_PAIRS",
                  "SUPPORTED_LINK_WIDTHS_LANES", "BACKWARD_COMPAT_RATES_GT_S",
                  "RETIMERS_MAX_PER_LINK", "EQUALIZATION_PHASES",
                  "TX_PRESET_COUNT", "TX_PRESET_RANGE",
                  "LANE_MARGINING_AT_RECEIVER",
                  "TLP_SEQUENCE_NUMBER_WIDTH_BITS", "TLP_LCRC_WIDTH_BITS",
                  "DLLP_CRC_WIDTH_BITS", "ECRC_WIDTH_BITS_OPTIONAL",
                  "FMT_FIELD_WIDTH_BITS", "TYPE_FIELD_WIDTH_BITS",
                  "TC_FIELD_WIDTH_BITS", "ATTR_FIELD_WIDTH_BITS",
                  "TLP_DATA_PAYLOAD_LENGTH_FIELD_WIDTH_BITS",
                  "MAX_PAYLOAD_SIZE_NEGOTIATED_BYTES",
                  "REQUESTER_ID_WIDTH_BITS", "COMPLETER_ID_WIDTH_BITS",
                  "TAG_WIDTH_BITS", "MAX_VIRTUAL_CHANNELS",
                  "MAX_TRAFFIC_CLASSES", "FLOW_CONTROL_CREDIT_TYPES",
                  "PCI_CFG_SPACE_BYTES", "PCIE_EXT_CFG_SPACE_BYTES"):
        wp.pop(stale, None)
    wp.update({
        "UCIE_SPEC_VERSION": "1.1",
        "MODULATION": "NRZ",
        "SIGNALING": "single-ended",
        "MAINBAND_LINE_ENCODING": "none (unencoded; integrity via Adapter "
                                  "16-bit Flit CRC + Retry)",
        "DATA_RATES_GT_S": list(_DATA_RATES),
        "MAX_DATA_RATE_GT_S": 32,
        "LANES_PER_MODULE_STANDARD": 16,
        "LANES_PER_MODULE_ADVANCED": 64,
        "VALID_LANES_PER_MODULE_PER_DIR": 1,
        "TRACK_CLOCK_LANES_PER_MODULE_PER_DIR": 1,
        "MODULES_PER_LINK_SUPPORTED": list(_MODULES_PER_LINK),
        "SIDEBAND_LANES_PER_DIRECTION": 2,
        "SIDEBAND_FREQ_MHZ": 800,
        "FLIT_SIZE_BYTES_OPTIONS": list(_FLIT_SIZES),
        "FLIT_HEADER_BYTES": 2,
        "FLIT_CRC_BYTES": 2,
        "FLIT_CRC_WIDTH_BITS": 16,
        "BW_PER_MODULE_PER_DIR_GB_S_STANDARD": 64,
        "BW_PER_MODULE_PER_DIR_GB_S_ADVANCED": 256,
        "BUMP_PITCH_UM_STANDARD": "100-130",
        "BUMP_PITCH_UM_ADVANCED": "25-55",
        "CHANNEL_REACH_MM_STANDARD": 25,
        "CHANNEL_REACH_MM_ADVANCED": 2,
        "POWER_EFFICIENCY_PJ_PER_BIT_STANDARD": 0.5,
        "POWER_EFFICIENCY_PJ_PER_BIT_ADVANCED": 0.25,
        "LATENCY_TX_PLUS_RX_NS_MAX": 2,
        "FORWARDED_CLOCK": True,
        "EMBEDDED_CLOCK": False,
        "RAW_MODE_SUPPORTED": True,
    })
    # Remove PCIe block/EQ/poly objects.
    for stale in ("block_encoding_128b130b", "equalization_constants",
                  "lcrc_polynomial", "ecrc_polynomial"):
        d.pop(stale, None)
    d["flit_format_constants"] = {
        "flit_64B": {"size_bytes": 64, "flit_header_bytes": 2, "crc_bytes": 2,
                     "payload_bytes": 60},
        "flit_256B": {"size_bytes": 256, "usage": "CXL 3.0 / PCIe 6.0"},
        "flit_256B_latency_optimized": {"size_bytes": 256,
                                        "usage": "CXL 3.0 / Streaming"},
        "crc_width_bits": 16,
        "note": "Sample RTL code for the Flit CRC is provided in the UCIe "
                "specification.",
    }
    d["crc_constants"] = {
        "name": "UCIe Flit CRC (16-bit)", "width_bits": 16,
        "scope": "per Flit, computed by the D2D Adapter", "retry": True,
        "bypassed_in_raw_mode": True,
    }
    kc = _ensure_dict(d, "key_constants_for_RTL_authoring")
    # Remove PCIe-sibling RTL-authoring keys.
    for stale in ("is_differential", "is_dual_simplex", "embedded_clock",
                  "encoding", "line_rate_GT_s", "lane_data_striping",
                  "scrambling_polynomial", "precoding_optional",
                  "refclk_freq_MHz_nominal", "clock_tolerance_ppm",
                  "retimers_max_per_link", "lane_margining_mandatory"):
        kc.pop(stale, None)
    kc.update({
        "is_serial": True,
        "is_single_ended": True,
        "is_source_synchronous": True,
        "forwarded_clock": True,
        "embedded_clock": False,
        "modulation": "NRZ",
        "mainband_line_encoding": "none",
        "max_data_rate_GT_s": 32,
        "lanes_per_module_standard": 16,
        "lanes_per_module_advanced": 64,
        "modules_per_link": list(_MODULES_PER_LINK),
        "valid_lane_per_module": True,
        "track_clock_lane_per_module": True,
        "sideband_always_on": True,
        "sideband_freq_MHz": 800,
        "flit_header_bytes": 2,
        "flit_crc_width_bits": 16,
        "retry_enabled": True,
        "raw_mode_bypasses_adapter": True,
        "lane_repair": True,
        "lane_reversal": True,
        "interop_rule": "support all data rates up to the advertised "
                        "maximum",
    })
    d["default_signal_values_when_idle"] = {
        "mainband_idle": "Valid de-asserted (no valid data); forwarded "
                         "Track/clock kept running.",
        "sideband_idle": "Always-on at 800 MHz; idle when no "
                         "management/register traffic.",
        "raw_mode": "Adapter Flit/CRC/Retry bypassed; Protocol Layer drives "
                    "RDI directly.",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L8 timing — overwrite the PCIe 32 GT/s ordered-set waveform with the
# UCIe module/Flit/sideband timing.
# ----------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    # Remove PCIe-sibling waveform keys.
    for stale in ("block_framing_waveform", "ordered_sets",
                  "equalization_waveform", "ltssm_transition_trigger_waveform",
                  "clock_tolerance_compensation", "line_rate_waveform"):
        d.pop(stale, None)
    d["mainband_waveform"] = {
        "signaling": "single-ended NRZ, unencoded, per data lane.",
        "framing": "Per module: N data lanes (16 Std / 64 Adv) + 1 Valid "
                   "lane (qualifies data) + 1 forwarded Track/clock lane "
                   "(strobe).",
        "clocking": "Source-synchronous: receiver samples data against the "
                    "forwarded Track/clock; NOT clock-data-recovery.",
        "data_rate_GT_s": list(_DATA_RATES),
        "note": "No 8b/10b or 128b/130b line code; integrity is at the "
                "Flit/CRC level.",
    }
    d["flit_waveform"] = {
        "flit_64B": "2-byte Flit Header + 60-byte payload + 2-byte (16-bit) "
                    "CRC = 64 bytes; the Adapter inserts header at the start "
                    "and CRC at the end of each Flit.",
        "flit_256B": "256-byte Flit for CXL 3.0 / PCIe 6.0.",
        "flit_256B_latency_optimized": "256-byte latency-optimized Flit for "
                                       "CXL 3.0 / Streaming.",
        "all_zeros_idle": "When the Protocol Layer has no Flit, the Adapter "
                          "may send all-zero payload Flits to keep the link "
                          "framed.",
    }
    d["sideband_waveform"] = {
        "always_on": True, "frequency_MHz": 800, "lanes_per_direction": 2,
        "carries": "data + clock; training, debug, management, register "
                   "access.",
        "independent_of_mainband_rate": True,
    }
    d["link_state_transition_trigger_waveform"] = {
        "RESET_to_SBINIT": "Reset deasserted; bring up the always-on "
        "sideband first.",
        "SBINIT_to_MBINIT": "Sideband trained; begin mainband detect/repair "
        "and clock/Valid setup.",
        "MBINIT_to_MBTRAIN": "Mainband lanes detected/repaired; per-lane "
        "training begins.",
        "MBTRAIN_to_LINKINIT": "Per-lane timing/voltage calibrated at the "
        "negotiated data rate; data rate stepped up toward the advertised "
        "maximum.",
        "LINKINIT_to_ACTIVE": "D2D Adapter parameter negotiation "
        "(rate/width/protocol/Flit format/Raw-vs-Flit) complete; Flits "
        "flow.",
        "ACTIVE_to_L1": "Low-power entry (fast: 0.5 ns <=16G, 0.5-1 ns "
        ">=24G); link state preserved.",
        "L1_to_ACTIVE": "Low-power exit; resume Flit flow.",
        "ACTIVE_to_TRAINERROR": "Persistent CRC/Retry failure or lane fault; "
        "invoke Lane Repair / width degradation and re-train.",
    }
    d["lane_repair_waveform"] = {
        "advanced": "Spare data lanes are available; a failing lane is "
                    "remapped to a spare with no width loss.",
        "standard": "No spare lanes; the link degrades to a reduced width.",
        "lane_reversal": "Transmit-side lane reversal supported for routing "
                         "flexibility.",
    }
    d["general_timing_rule"] = (
        "UCIe mainband is source-synchronous at the per-module forwarded "
        "clock; the unit interval is set by the negotiated data rate (e.g. "
        "31.25 ps UI at 32 GT/s, 62.5 ps at 16 GT/s). The Adapter's Flit "
        "framing, CRC, Retry, and link-state FSM are clocked at the internal "
        "die clock, decoupled from the per-lane UI. The sideband runs at a "
        "fixed 800 MHz regardless of mainband rate.")
    d["voltage_levels"] = {
        "modulation": "NRZ single-ended; short on-package channel needs no "
                      "equalization line code.",
        "termination": "On-package controlled-impedance microbump/interposer "
                       "routing (Advanced) or organic substrate (Standard).",
        "reach": "Advanced <= 2 mm; Standard <= 25 mm.",
    }
    d["data_rate_waveform"] = {
        "data_rates_GT_s": list(_DATA_RATES),
        "ui_ps": {"4": 250.0, "8": 125.0, "12": 83.33, "16": 62.5,
                  "24": 41.67, "32": 31.25},
        "modulation": "NRZ (two-level)",
        "encoding": "unencoded mainband; 16-bit Flit CRC at the Adapter",
        "bandwidth_per_module_per_dir_GB_s": {"standard": 64,
                                              "advanced": 256},
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L9 — overwrite the PCIe integration spec with the UCIe die-to-die
# chiplet integration model.
# ----------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "On-package die-to-die (D2D) chiplet interconnect: a three-layer "
        "stack (Physical Layer die-to-die I/O + D2D Adapter reliable-delivery "
        "+ Protocol Layer mapping) that connects two chiplets on one package "
        "and carries PCIe / CXL / Streaming protocols over a module-based, "
        "source-synchronous, single-ended NRZ link with always-on sideband, "
        "at 4-32 GT/s.")
    d["topology_description"] = (
        "Point-to-point die-to-die Link between two chiplets on a package. "
        "Each Link is composed of 1, 2, or 4 uni-directional modules per "
        "direction (16-lane Standard or 64-lane Advanced modules). A "
        "multi-chiplet SoC has multiple UCIe Links; switched fabrics (e.g. "
        "CXL switches) are built by the carried protocol on top of "
        "UCIe-attached chiplets.")
    io = _ensure_dict(d, "integration_overview")
    # Remove PCIe-sibling integration keys.
    for stale in ("gen5_line_rate_GT_s", "encoding",
                  "x16_bandwidth_per_direction_GB_s",
                  "backward_compat_rates_GT_s", "retimers_max_per_link",
                  "lane_margining_at_receiver", "refclk_sharing",
                  "host_count_per_hierarchy", "max_lane_width",
                  "lane_widths_supported", "wire_count_per_lane_per_dir",
                  "ac_coupling_required", "refclk_freq_MHz"):
        io.pop(stale, None)
    io.update({
        "ucie_spec_version": "1.1",
        "max_data_rate_GT_s": 32,
        "data_rates_GT_s": list(_DATA_RATES),
        "modulation": "NRZ (single-ended, unencoded mainband)",
        "clocking": "source-synchronous forwarded clock (per module)",
        "lanes_per_module_standard": 16,
        "lanes_per_module_advanced": 64,
        "modules_per_link_supported": list(_MODULES_PER_LINK),
        "valid_lane_per_module_per_dir": 1,
        "track_clock_lane_per_module_per_dir": 1,
        "sideband_lanes_per_direction": 2,
        "sideband_freq_MHz": 800,
        "flit_header_bytes": 2,
        "flit_crc_width_bits": 16,
        "flit_sizes_bytes": list(_FLIT_SIZES),
        "raw_mode_supported": True,
        "bandwidth_per_module_per_dir_GB_s": {"standard": 64,
                                              "advanced": 256},
        "channel_reach_mm": {"standard": 25, "advanced": 2},
        "bump_pitch_um": {"standard": "100-130", "advanced": "25-55"},
        "latency_tx_plus_rx_ns": "< 2",
        "interfaces": {"FDI": "Adapter <-> Protocol Layer",
                       "RDI": "Adapter <-> Physical Layer"},
        "host_side_register_spec": "UCIe D2D configuration/status registers "
        "over the always-on sideband (discovery, parameter negotiation, "
        "link-state, repair, CRC/Retry status); the carried protocol keeps "
        "its own register space above the Protocol Layer.",
    })
    d["interface_categories"] = [
        "Protocol Layer — maps PCIe / CXL.io / CXL.cache / CXL.mem / "
        "Streaming (AXI/CHI/SFI/CPI) onto FDI.",
        "Die-to-Die Adapter — Flit framing, 16-bit CRC + Retry, link-state "
        "management, parameter negotiation, Arb/Mux; FDI up, RDI down.",
        "Physical Layer — AFE/clocking, bump map, training, lane "
        "repair/reversal, sideband; RDI up.",
        "FDI (Flit-Aware Die-to-Die Interface) — Protocol <-> Adapter "
        "plug-and-play interface.",
        "RDI (Raw Die-to-Die Interface) — Adapter <-> Physical Layer "
        "plug-and-play interface (also the Raw-Mode path).",
    ]
    d["interconnect_topologies_supported"] = [
        "Single die-to-die Link (1 module per direction) between two "
        "chiplets.",
        "2-module or 4-module Link for 2x/4x bandwidth between two chiplets.",
        "Multiple UCIe Links across a multi-chiplet SoC.",
        "Protocol-level fabric (e.g. CXL switch) built on UCIe-attached "
        "chiplets.",
        "Co-packaged optics / partitionable switch dies connected via "
        "on-package UCIe.",
    ]
    d["default_signal_values_when_omitted"] = (
        "Mainband Valid de-asserted (no valid data) with the forwarded clock "
        "running; sideband always-on at 800 MHz. In Raw Mode the Adapter "
        "Flit/CRC/Retry is bypassed and the Protocol Layer drives RDI "
        "directly.")
    d["soc_dependent_items"] = [
        "Package class selection (Standard 2D organic vs Advanced 2.5D "
        "interposer/bridge) and the matching UCIe bump-out.",
        "Module count per Link (1/2/4) and target maximum data rate (up to "
        "32 GT/s).",
        "Protocol selection (PCIe / CXL / Streaming) and Flit vs Raw mode.",
        "PHY AFE / forwarded-clock / lane-repair implementation.",
        "Sideband routing (depopulated bumps, no extra shoreline).",
        "FDI/RDI integration of third-party Protocol-Layer / Adapter / PHY "
        "IP.",
        "Reliability strategy: spare lanes (Advanced) or width degradation "
        "(Standard).",
        "Power/clock domains, vccaon/vccio rails, and low-power (L1/L2) "
        "policy.",
    ]
    d["low_power_modes"] = {
        "ACTIVE_L0": "Full operation; Flits flow at the negotiated rate.",
        "L1": "Standby; fast entry/exit (0.5 ns <=16G, 0.5-1 ns >=24G); state "
              "preserved.",
        "L2": "Deeper low-power; re-entry re-trains the mainband.",
    }
    d["device_classes_examples"] = [
        "CPU / SoC base die connecting accelerator and IO chiplets",
        "Accelerator chiplet (PCIe/CXL mapped over FDI)",
        "CXL.mem memory-expander chiplet",
        "IO / SerDes chiplet exposing external PCIe/CXL on a separate die",
        "Co-packaged optics or partitionable networking-switch die",
        "Symmetric-coherency processor chiplets (coherency protocol over "
        "FDI)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L10 — overwrite PCIe compliance categories with UCIe categories.
# ----------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the spec defines compliance/interoperability behaviors "
        "(electrical, logical, protocol, software) mapped to the UCIe "
        "Compliance Program; the tutorial overview itself does not include a "
        "full testbench, though sample CRC RTL is provided.")
    d["derived_compliance_test_categories"] = [
        "Sideband bring-up: always-on 800 MHz sideband (2 lanes/direction) "
        "trains before the mainband.",
        "Mainband initialization + training (MBINIT/MBTRAIN) at each "
        "supported data rate 4/8/12/16/24/32 GT/s.",
        "Interop rule: a component supports all data rates up to its "
        "advertised maximum (e.g. 4/8/12 for a 12G device).",
        "Module-count scaling: 1-, 2-, and 4-module Links deliver 1x/2x/4x "
        "bandwidth.",
        "Valid-lane framing + forwarded Track/clock sampling per module.",
        "Flit framing: 2B Flit Header + 16-bit CRC; 64B and 256B (and 256B "
        "latency-optimized) Flit formats.",
        "CRC error injection -> Retry/replay using the Flit-header sequence "
        "number.",
        "Raw Mode: bypass the D2D Adapter (no Flit/CRC/Retry); Protocol Layer "
        "drives RDI directly.",
        "Arb/Mux: multiplex multiple protocols (e.g. CXL.io + CXL.cache + "
        "CXL.mem) on one Link.",
        "Protocol mappings over FDI: PCIe, CXL.io/CXL.cache/CXL.mem, "
        "Streaming (AXI/CHI/SFI/CPI).",
        "Lane Repair: force a lane fault, verify spare-lane remap (Advanced) "
        "or width degradation (Standard).",
        "Lane Reversal on the transmit side.",
        "Link-state FSM coverage: RESET -> SBINIT -> MBINIT -> MBTRAIN -> "
        "LINKINIT -> ACTIVE -> L1/L2.",
        "Parameter negotiation over sideband: data rate, width, protocol, "
        "Flit format, Raw vs Flit.",
        "Configuration-register discovery and run-time access over sideband.",
        "Standard vs Advanced Package: bump pitch (100-130 vs 25-55 um), "
        "reach (<=25 vs <=2 mm), width (16 vs 64 lanes).",
        "Latency target Tx+Rx < 2 ns; power efficiency 0.5 / 0.25 pJ/b.",
        "Reliability/FIT: 0 < FIT << 1 with Flit Mode.",
        "Compliance/interoperability: electrical + logical + protocol + "
        "software conformance.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L11 — overwrite the PCIe OTP-equivalent fields with UCIe capability
# fields.
# ----------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "UCIe Version / Capability",
         "width_bits": "implementation-defined",
         "location": "UCIe capability register (sideband-accessible)",
         "note": "Advertises the supported UCIe spec version (1.1) and "
                 "capability set."},
        {"field": "Package Class", "width_bits": 1,
         "location": "UCIe capability register",
         "note": "Standard Package vs Advanced Package; fixed by the silicon "
                 "bump-out."},
        {"field": "Maximum Data Rate",
         "width_bits": "implementation-defined",
         "location": "UCIe capability register",
         "note": "Advertised maximum lane rate (4..32 GT/s); the device must "
                 "support all lower rates."},
        {"field": "Module Width / Count Capability",
         "width_bits": "implementation-defined",
         "location": "UCIe capability register",
         "note": "Lanes per module (16 or 64) and supported module counts "
                 "(1/2/4)."},
        {"field": "Supported Protocols",
         "width_bits": "implementation-defined",
         "location": "UCIe capability register",
         "note": "PCIe / CXL.io / CXL.cache / CXL.mem / Streaming support "
                 "bits."},
        {"field": "Spare-Lane / Repair Capability",
         "width_bits": "implementation-defined",
         "location": "UCIe capability register",
         "note": "Number of spare lanes (Advanced) or width-degradation "
                 "capability (Standard)."},
    ]
    d["notes"] = (
        "UCIe does not define OTP/fuse content as a protocol concept. The "
        "interoperability-relevant facts (package class, maximum data rate, "
        "module width/count, supported protocols, Flit format, spare-lane "
        "capability) are hardware-determined and advertised through "
        "sideband-accessible capability registers used during discovery and "
        "parameter negotiation; an implementation may back some of these "
        "with fuses, but the spec only requires they be discoverable.")
    _write(p, d)


# ----------------------------------------------------------------------
# L12 — overwrite the PCIe bring-up/EQ sequences with UCIe link bring-up
# + Flit/Retry/Raw/Arb-Mux/lane-repair sequences.
# ----------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    # Remove PCIe-sibling sequence keys.
    for stale in ("link_bring_up_sequence_ltssm",
                  "equalization_sequence_phase0_3",
                  "alternate_protocol_negotiation_sequence",
                  "lane_margining_sequence", "tlp_transmission_sequence",
                  "nak_replay_sequence", "low_power_l1_entry_exit_sequence",
                  "hot_reset_sequence"):
        d.pop(stale, None)
    d["link_bring_up_sequence"] = [
        "1. Reset deassertion. Link-state FSM enters RESET.",
        "2. SBINIT — bring up the always-on 800 MHz sideband (2 "
        "lanes/direction) first.",
        "3. Parameter exchange over sideband begins (capabilities, package "
        "class, max data rate, width, protocol).",
        "4. MBINIT — detect mainband lanes, run lane repair/reversal, "
        "establish per-module forwarded Track/clock and Valid framing.",
        "5. MBTRAIN — per-lane timing/voltage calibration; step the data "
        "rate up toward the advertised maximum (4 -> ... -> 32 GT/s).",
        "6. LINKINIT — D2D Adapter finalizes negotiated parameters (data "
        "rate, module count, protocol, Flit format, Raw vs Flit, CRC/Retry).",
        "7. ACTIVE (L0) — Flits flow across the mainband with 16-bit CRC + "
        "Retry (unless Raw Mode).",
        "8. Run-time: configuration registers and management continue over "
        "the sideband; low-power L1/L2 entered/exited as needed.",
    ]
    d["flit_transmission_sequence"] = [
        "1. Protocol Layer presents protocol data to the D2D Adapter over "
        "FDI.",
        "2. Adapter builds a Flit: prepend a 2-byte Flit Header (incl. "
        "sequence number), append a 2-byte (16-bit) CRC.",
        "3. Adapter stores the Flit in the retry buffer and hands the Flit "
        "stream to the PHY over RDI.",
        "4. PHY serializes the Flit as single-ended NRZ across the module's "
        "data lanes, with Valid framing and the forwarded Track/clock, at "
        "the negotiated rate.",
        "5. Far-end PHY samples the data against the forwarded clock "
        "(qualified by Valid) and reconstructs the Flit over RDI.",
        "6. Far-end Adapter checks the 16-bit CRC: good -> accept and "
        "advance the sequence; bad -> request Retry.",
        "7. On acknowledgment the transmitter frees the Flit from the retry "
        "buffer; the accepted protocol data is delivered up over FDI.",
    ]
    d["retry_sequence"] = [
        "1. Receiver Adapter detects a Flit CRC mismatch.",
        "2. Receiver signals a Retry for the failing sequence number.",
        "3. Transmitter Adapter replays the failed Flit(s) from the retry "
        "buffer in sequence-number order.",
        "4. Repeated failure escalates via link-state management (re-train / "
        "lane repair / width degradation).",
    ]
    d["raw_mode_sequence"] = [
        "1. During parameter exchange both ends agree to Raw Mode for a "
        "protocol.",
        "2. The Protocol Layer connects directly to the Physical Layer over "
        "RDI, bypassing the Adapter's Flit/CRC/Retry.",
        "3. The carried protocol supplies its own reliability; UCIe provides "
        "only the raw lane transport.",
    ]
    d["arb_mux_sequence"] = [
        "1. Multiple protocols (e.g. CXL.io + CXL.cache + CXL.mem) are "
        "enabled on one Link.",
        "2. The D2D Adapter's Arb/Mux arbitrates and interleaves their Flits "
        "over the shared mainband.",
        "3. The receiver demuxes by protocol/format identifier in the Flit "
        "Header and delivers each to its Protocol-Layer instance.",
    ]
    d["lane_repair_sequence"] = [
        "1. During MBINIT/MBTRAIN a data lane is found faulty.",
        "2. Advanced Package: remap the failing lane to a spare lane (no "
        "width loss).",
        "3. Standard Package: degrade to a reduced width (no spare lanes).",
        "4. Re-train and continue; repair status is recorded in "
        "configuration registers.",
    ]
    d["low_power_entry_exit_sequence"] = [
        "1. Link in ACTIVE requests L1 entry.",
        "2. Mainband quiesces; link state preserved; fast exit latency "
        "(0.5 ns <=16G, 0.5-1 ns >=24G).",
        "3. Exit: resume Flit flow; deeper L2 requires re-training the "
        "mainband.",
    ]
    d["reset_sequence"] = [
        "1. Reset asserted -> RESET state; mainband and Adapter held.",
        "2. Reset deasserted -> SBINIT -> MBINIT -> MBTRAIN -> LINKINIT -> "
        "ACTIVE, re-running training and parameter negotiation.",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L13 — overwrite PCIe lab targets with UCIe characterization targets.
# ----------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "Per-lane data eye at the target rate", "purpose": "Verify "
         "single-ended NRZ data lanes meet the eye/timing budget against the "
         "forwarded clock at 4-32 GT/s (e.g. 31.25 ps UI at 32 GT/s)."},
        {"name": "Forwarded-clock / Track alignment", "purpose": "Confirm "
         "the source-synchronous strobe and per-module track/calibration "
         "lane keep the receiver sampling point aligned."},
        {"name": "Sideband bring-up", "purpose": "Validate the always-on "
         "800 MHz sideband (2 lanes/direction) trains and carries "
         "management/register traffic before the mainband."},
        {"name": "Flit CRC / Retry", "purpose": "Inject errors and confirm "
         "the 16-bit Flit CRC detects them and Retry replays correctly."},
        {"name": "Lane repair / reversal", "purpose": "Verify spare-lane "
         "remap (Advanced) or width degradation (Standard) and transmit-side "
         "lane reversal."},
        {"name": "Bandwidth / shoreline density", "purpose": "Measure "
         "BW/module/dir (64 GB/s Std, 256 GB/s Adv) and shoreline density vs "
         "bump pitch."},
        {"name": "Latency budget", "purpose": "Confirm Tx+Rx end-to-end "
         "latency < 2 ns (FDI to bump and back)."},
        {"name": "Power efficiency", "purpose": "Confirm 0.5 pJ/b (Standard) "
         "/ 0.25 pJ/b (Advanced) energy targets."},
    ]
    d["notes"] = (
        "UCIe characterization centers on the source-synchronous "
        "single-ended channel (very short on-package reach), the always-on "
        "sideband, and the D2D Adapter's Flit/CRC/Retry. Conformance is "
        "established by the UCIe Compliance Program (electrical, logical, "
        "protocol, software). Per-implementation PHY calibration (impedance, "
        "forwarded-clock phase, per-lane de-skew, lane repair) is done at "
        "bring-up.")
    _write(p, d)


# ----------------------------------------------------------------------
# L14 — overwrite PCIe versioning with UCIe 1.1 versioning + traps.
# ----------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = (
        "Universal Chiplet Interconnect Express (UCIe) Specification Revision "
        "1.1 (2023)")
    f["previous_versions"] = [
        "UCIe 1.0 (2022) — initial release: three-layer D2D stack (PHY + D2D "
        "Adapter + Protocol Layer), Standard + Advanced Packages, 4-32 GT/s, "
        "FDI/RDI, 64B Flit, PCIe/CXL/Streaming, sideband.",
    ]
    f["key_changes"] = [
        {"version": "1.1", "summary": "Incremental revision over UCIe 1.0: "
         "clarifications and errata, configuration-register / compliance / "
         "RDI-FDI interface improvements, and reliability / automotive-grade "
         "enhancements. The layered architecture (PHY / D2D Adapter / "
         "Protocol Layer), package classes (Standard / Advanced), data rates "
         "(4-32 GT/s), module model (16/64-lane, 1/2/4 modules), "
         "Flit/CRC/Retry, sideband, and PCIe/CXL/Streaming mappings are "
         "carried forward unchanged."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "UCIe 2.0 (2024)", "summary": "Adds a standardized "
         "manageability/system architecture and 3D packaging (vertical die "
         "stacking) support, with further compliance and DFx enhancements; "
         "same three-layer foundation."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Support_all_rates_up_to_max",
         "rule": "A component must support all data rates up to its "
                 "advertised maximum (e.g. 4/8/12 for a 12G device).",
         "trap": "Assuming a high-rate device can only run at its top rate "
                 "breaks interop with a lower-rate partner; negotiation lands "
                 "at the highest common rate."},
        {"trap_name": "Package_class_is_fixed_by_bumpout",
         "rule": "Standard (16-lane module, 100-130 um pitch, <=25 mm) and "
                 "Advanced (64-lane module, 25-55 um pitch, <=2 mm) have "
                 "different bump-outs.",
         "trap": "Standard and Advanced bump-outs are not interchangeable; "
                 "the package class is a hardware property, not a runtime "
                 "mode."},
        {"trap_name": "Raw_mode_has_no_UCIe_CRC",
         "rule": "Raw Mode bypasses the D2D Adapter's Flit/CRC/Retry.",
         "trap": "Relying on UCIe for integrity in Raw Mode is wrong — the "
                 "carried protocol must supply its own reliability."},
        {"trap_name": "Sideband_is_always_on_and_separate",
         "rule": "The 800 MHz sideband (2 lanes/direction) is always-on and "
                 "carries no mainband data.",
         "trap": "Treating the sideband as part of the data path, or "
                 "assuming it can be powered down, breaks management/register "
                 "access."},
        {"trap_name": "Forwarded_clock_not_CDR",
         "rule": "UCIe mainband is source-synchronous (forwarded "
                 "Track/clock), not clock-data-recovery; the mainband is "
                 "unencoded.",
         "trap": "Designing for an embedded-clock 8b/10b or 128b/130b line "
                 "code (as in PCIe/USB SerDes) is wrong for the UCIe "
                 "die-to-die PHY."},
        {"trap_name": "Flit_format_must_match",
         "rule": "Both ends must agree on the Flit format (64B / 256B / 256B "
                 "latency-optimized).",
         "trap": "A 256B-only partner cannot interoperate with a 64B-only "
                 "partner without a common format."},
    ]
    f["version_naming_history_note"] = (
        "UCIe is maintained by the UCIe Consortium (120+ member companies). "
        "UCIe 1.0 (2022) established the open die-to-die chiplet "
        "interconnect; UCIe 1.1 (2023) is an incremental revision adding "
        "errata, compliance/register/interface improvements, and "
        "reliability/automotive enhancements. Facts here are grounded in the "
        "public UCIe Consortium tutorial overview (Hot Chips 2023) and the "
        "UCIe 1.x specification structure (three layers, Standard/Advanced "
        "Packages, 4-32 GT/s, FDI/RDI, Flit/CRC/Retry, sideband, "
        "PCIe/CXL/Streaming mappings).")
    _write(p, d)


# ----------------------------------------------------------------------
# L15 — overwrite PCIe encoding tables with UCIe data-rate / package /
# Flit / module / sideband / interface tables.
# ----------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # Remove PCIe-sibling tables.
    for stale in ("block_encoding_128b130b_table", "data_rate_identifier_note",
                  "equalization_preset_table", "equalization_phases_table",
                  "lcrc_polynomial_table", "ecrc_polynomial_table",
                  "special_symbols_table"):
        f.pop(stale, None)
    f["data_rate_table"] = {
        "header_columns": ["Data Rate (GT/s)", "UI (ps)", "Modulation",
                           "Mainband Encoding"],
        "rows": [
            ["4", "250.0", "NRZ", "unencoded (16-bit Flit CRC)"],
            ["8", "125.0", "NRZ", "unencoded (16-bit Flit CRC)"],
            ["12", "83.33", "NRZ", "unencoded (16-bit Flit CRC)"],
            ["16", "62.5", "NRZ", "unencoded (16-bit Flit CRC)"],
            ["24", "41.67", "NRZ", "unencoded (16-bit Flit CRC)"],
            ["32", "31.25", "NRZ", "unencoded (16-bit Flit CRC)"],
        ],
    }
    f["package_comparison_table"] = {
        "header_columns": ["Characteristic", "Standard Package",
                           "Advanced Package"],
        "rows": [
            ["Package type", "2D organic", "2.5D interposer / bridge"],
            ["Lanes per module", "16", "64"],
            ["Bump pitch (um)", "100-130", "25-55"],
            ["Channel reach (mm)", "<= 25", "<= 2"],
            ["B/W per module/dir (GB/s)", "64", "256"],
            ["B/W shoreline (GB/s/mm)", "28-224", "165-1317"],
            ["B/W density (GB/s/mm2)", "22-125", "188-1350"],
            ["Power efficiency (pJ/b)", "0.5", "0.25"],
            ["Reliability", "width degradation", "spare lanes"],
        ],
    }
    f["flit_format_table"] = {
        "header_columns": ["Flit Format", "Size (bytes)", "Header (bytes)",
                           "CRC (bits)", "Usage"],
        "rows": [
            ["64-byte Flit", "64", "2", "16",
             "Baseline (e.g. PCIe/CXL/Streaming)"],
            ["256-byte Flit", "256", "2", "16", "CXL 3.0 / PCIe 6.0"],
            ["256-byte Latency-Optimized Flit", "256", "2", "16",
             "CXL 3.0 / Streaming"],
        ],
    }
    f["module_lane_table"] = {
        "header_columns": ["Signal", "Standard (per module/dir)",
                           "Advanced (per module/dir)"],
        "rows": [
            ["Data lanes", "16", "64"],
            ["Valid lane", "1", "1"],
            ["Track / forwarded clock", "1", "1"],
            ["Spare data lanes", "0 (width degradation)", "yes (repair)"],
        ],
    }
    f["sideband_table"] = {
        "header_columns": ["Property", "Value"],
        "rows": [
            ["Lanes per direction", "2 (data + clock)"],
            ["Frequency", "800 MHz"],
            ["Always-on", "yes"],
            ["Purpose", "training / debug / management / config registers"],
        ],
    }
    f["interface_table"] = {
        "header_columns": ["Interface", "Between", "Role"],
        "rows": [
            ["FDI", "Protocol Layer <-> D2D Adapter",
             "Flit-Aware Die-to-Die Interface"],
            ["RDI", "D2D Adapter <-> Physical Layer",
             "Raw Die-to-Die Interface (also Raw-Mode path)"],
        ],
    }
    f["encoding_note"] = (
        "UCIe's mainband is unencoded single-ended NRZ with a "
        "source-synchronous forwarded clock — there is NO 8b/10b or "
        "128b/130b line code. Data integrity is provided digitally by a "
        "16-bit per-Flit CRC + Retry in the D2D Adapter (Flit Mode); Raw "
        "Mode carries the protocol's own framing/integrity.")
    f["tables"] = [
        "Data-rate / UI table (4-32 GT/s)",
        "Standard vs Advanced Package comparison table",
        "Flit-format table (64B / 256B / 256B latency-optimized)",
        "Per-module lane table (data + Valid + Track)",
        "Sideband table (2 lanes/dir @ 800 MHz)",
        "FDI / RDI interface table",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L16 — overwrite PCIe compliance properties with UCIe ones.
# ----------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    # Remove PCIe-sibling distinguisher key.
    f.pop("gen5_distinguishers", None)
    f["must_have_properties"] = [
        "Three-layer stack: Physical Layer (die-to-die I/O) + D2D Adapter "
        "(reliable delivery) + Protocol Layer (mapping).",
        "FDI between Protocol Layer and D2D Adapter; RDI between D2D Adapter "
        "and Physical Layer.",
        "A specified bump-out for the chosen package class (Standard 16-lane "
        "module / Advanced 64-lane module).",
        "Single-ended, unencoded NRZ mainband with a per-module forwarded "
        "Track/clock and a Valid lane.",
        "Support for all data rates up to the advertised maximum (subset of "
        "4/8/12/16/24/32 GT/s).",
        "Module model: 1, 2, or 4 uni-directional modules per Link "
        "(1x/2x/4x bandwidth).",
        "Always-on sideband: 2 lanes/direction @ 800 MHz for training, "
        "management, and config registers.",
        "Flit framing in the D2D Adapter: 2-byte Flit Header + 16-bit CRC + "
        "Retry (Flit Mode).",
        "Link-state management and parameter negotiation "
        "(rate/width/protocol/Flit format).",
        "Lane Repair / Lane Reversal; spare lanes (Advanced) or width "
        "degradation (Standard).",
        "At least one Protocol-Layer mapping: PCIe, CXL "
        "(CXL.io/CXL.cache/CXL.mem), or Streaming.",
        "Configuration registers for discovery and run-time control.",
    ]
    f["must_not_have_properties"] = [
        "An 8b/10b or 128b/130b mainband line code (UCIe mainband is "
        "unencoded; integrity is via Flit CRC).",
        "An embedded/recovered mainband clock (UCIe is source-synchronous / "
        "forwarded-clock).",
        "Reliance on UCIe-level CRC in Raw Mode (Raw Mode bypasses the "
        "Adapter's CRC/Retry).",
        "Mixing Standard and Advanced bump-outs on a single Link.",
        "A powered-down sideband during operation (the sideband is "
        "always-on).",
        "Differential mainband signaling (UCIe mainband data lanes are "
        "single-ended).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Sideband bring-up failure", "trigger": "The always-on "
         "800 MHz sideband fails to train; no parameter exchange."},
        {"mode": "Mainband training failure", "trigger": "MBINIT/MBTRAIN "
         "cannot calibrate lanes at the negotiated rate."},
        {"mode": "Data-rate interop violation", "trigger": "A device does "
         "not support all rates up to its advertised maximum."},
        {"mode": "Flit CRC error storm", "trigger": "Persistent CRC "
         "mismatches exhaust Retry; link re-trains or degrades."},
        {"mode": "Lane-repair exhaustion", "trigger": "More failing lanes "
         "than spares (Advanced) or unacceptable width loss (Standard)."},
        {"mode": "Flit-format mismatch", "trigger": "Two ends cannot agree "
         "on 64B vs 256B Flit format."},
        {"mode": "Raw-mode integrity assumption", "trigger": "Expecting UCIe "
         "CRC in Raw Mode where none exists."},
    ]
    f["min_link_constraint"] = (
        "A Link must train at least one module to ACTIVE at the lowest common "
        "supported data rate, with the sideband up and the D2D Adapter (or "
        "Raw Mode) operational; otherwise it must repair/reverse lanes, "
        "degrade width, or fail to bring up.")
    f["reset_behavior_compliance"] = (
        "Reset deassertion drives RESET -> SBINIT (sideband first) -> MBINIT "
        "-> MBTRAIN -> LINKINIT -> ACTIVE, re-running lane repair/reversal "
        "and parameter negotiation. The link reaches a low data rate first "
        "and steps up to the advertised maximum during MBTRAIN.")
    f["ucie_distinguishers"] = (
        "UCIe is identified by ALL of: an open die-to-die (D2D) chiplet "
        "interconnect on a single package; the three-layer Physical Layer / "
        "D2D Adapter / Protocol Layer architecture; FDI + RDI interfaces; "
        "module-based single-ended source-synchronous NRZ mainband (16 or 64 "
        "data lanes/module, 1/2/4 modules) with a Valid lane and forwarded "
        "Track/clock; an always-on 800 MHz sideband; Flit framing with "
        "16-bit CRC + Retry (bypassed in Raw Mode); Standard vs Advanced "
        "Package classes; and PCIe/CXL/Streaming protocol mapping. This is "
        "distinct from PCIe/CXL board-level serial links (which use "
        "differential, embedded-clock, line-coded SerDes) — UCIe carries "
        "those protocols over a die-to-die package interconnect.")
    _write(p, d)


# ----------------------------------------------------------------------
# L17 — overwrite PCIe channels + dependency graph with UCIe module +
# sideband + Flit channels.
# ----------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "Mainband data lanes",
         "direction": "uni-directional per module (output on TX module, "
                      "input on RX module)",
         "purpose": "Carry Flit (or Raw) data across the die-to-die "
                    "channel.",
         "active_levels": "single-ended NRZ at 4-32 GT/s; 16 lanes "
         "(Standard) or 64 lanes (Advanced) per module",
         "idle_level": "Valid de-asserted; forwarded clock kept running"},
        {"name": "Valid lane", "direction": "per module, per direction",
         "purpose": "Frames/qualifies the mainband data on the module.",
         "active_levels": "single-ended; asserted when data lanes carry "
         "valid data", "idle_level": "de-asserted"},
        {"name": "Track / Clock lane",
         "direction": "per module, per direction",
         "purpose": "Forwarded source-synchronous clock / calibration-track "
                    "for the mainband.",
         "active_levels": "single-ended forwarded clock at the lane rate",
         "idle_level": "kept running"},
        {"name": "txdatasb / rxdatasb (sideband data)",
         "direction": "full-duplex (per direction)",
         "purpose": "Sideband data lane for training/management/registers.",
         "active_levels": "800 MHz, always-on",
         "idle_level": "always-on; idle frames when no traffic"},
        {"name": "txcksb / rxcksb (sideband clock)",
         "direction": "full-duplex (per direction)",
         "purpose": "Sideband forwarded clock.", "active_levels": "800 MHz",
         "idle_level": "always-on"},
        {"name": "vccaon / vccio / vss", "direction": "supply",
         "purpose": "Always-on power, IO power, ground rails interleaved in "
                    "the bump map.",
         "active_levels": "DC rails", "idle_level": "n/a; always driven"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "Active mainband", "meaning": "Single-ended NRZ data on the "
         "module's data lanes, framed by Valid, strobed by the forwarded "
         "Track/clock."},
        {"name": "Mainband idle", "meaning": "Valid de-asserted; no valid "
         "data; forwarded clock continues."},
        {"name": "Sideband traffic", "meaning": "Always-on 800 MHz "
         "management/register/training packets, independent of the "
         "mainband."},
    ]
    f["packet_types_summary"] = [
        {"class": "Flit", "members": ["64-byte Flit", "256-byte Flit",
                                      "256-byte Latency-Optimized Flit"],
         "count": 3},
        {"class": "Mapped protocol",
         "members": ["PCIe", "CXL.io", "CXL.cache", "CXL.mem",
                     "Streaming (AXI/CHI/SFI/CPI)"], "count": 5},
    ]
    cc = _ensure_dict(f, "channel_counts")
    # Remove PCIe-sibling channel-count keys.
    for stale in ("lanes_per_link_min", "lanes_per_link_max",
                  "differential_pairs_per_lane", "wires_per_lane",
                  "shared_signals_per_link", "retimers_max_per_link",
                  "max_vc_per_link", "max_tc_per_link",
                  "flow_control_credit_types", "tlp_packet_class_count",
                  "dllp_packet_class_count", "line_rate_GT_s",
                  "equalization_phases", "tx_preset_count"):
        cc.pop(stale, None)
    cc.update({
        "data_lanes_per_module_standard": 16,
        "data_lanes_per_module_advanced": 64,
        "valid_lanes_per_module_per_dir": 1,
        "track_clock_lanes_per_module_per_dir": 1,
        "modules_per_link_min": 1,
        "modules_per_link_max": 4,
        "sideband_lanes_per_direction": 2,
        "sideband_freq_MHz": 800,
        "data_rates_GT_s": list(_DATA_RATES),
        "flit_header_bytes": 2,
        "flit_crc_width_bits": 16,
        "flit_format_count": 3,
        "mapped_protocol_count": 5,
    })
    f["global_signals"] = [
        {"name": "Sideband", "purpose": "Always-on 800 MHz "
         "management/training/register channel for the whole Link."},
        {"name": "RESET", "purpose": "Per-Link reset / initialization."},
        {"name": "vccaon", "purpose": "Always-on power rail (keeps sideband "
         "alive)."},
    ]
    f["dependency_graph"] = {
        "common_rule": "Each module is source-synchronous: data lanes are "
        "sampled against that module's forwarded Track/clock, qualified by "
        "the Valid lane. The sideband must be up before the mainband can be "
        "trained/negotiated. Multi-module Links de-skew and align modules. "
        "TX and RX modules are independent (a Link pairs them for "
        "full-duplex).",
        "data_dependency": "Flit transmission requires: (1) sideband up, "
        "(2) mainband trained at the negotiated rate, (3) D2D Adapter ACTIVE "
        "(or Raw Mode agreed). Reliable delivery requires the Adapter's CRC "
        "+ Retry; Raw Mode requires the carried protocol's own reliability.",
    }
    f["handshake_pairs"] = [
        {"name": "FDI valid/credit", "from": "Protocol Layer",
         "to": "D2D Adapter", "rule": "Flit-Aware Die-to-Die Interface flow "
         "control between Protocol and Adapter."},
        {"name": "RDI valid/credit", "from": "D2D Adapter",
         "to": "Physical Layer", "rule": "Raw Die-to-Die Interface flow "
         "control between Adapter and PHY (also the Raw-Mode data path)."},
        {"name": "Flit-CRC-Retry", "from": "receiver Adapter",
         "to": "transmitter Adapter", "rule": "16-bit CRC check; on mismatch "
         "request Retry of the sequence-numbered Flit."},
        {"name": "Sideband-param-exchange", "from": "either", "to": "either",
         "rule": "Negotiate data rate / width / protocol / Flit format over "
         "the always-on sideband."},
        {"name": "Valid-framing", "from": "transmitter module",
         "to": "receiver module", "rule": "Valid lane qualifies which UI "
         "carry mainband data."},
        {"name": "Lane-repair", "from": "PHY", "to": "PHY", "rule": "Remap "
         "failing lane to a spare (Advanced) or degrade width (Standard) "
         "during training."},
    ]
    f["ordering_rules"] = {
        "bit_order_on_wire": "Single-ended NRZ per data lane, "
        "source-synchronous to the forwarded clock; no line-code block "
        "boundaries.",
        "flit_order": "Flits are ordered by the Flit-header sequence number "
        "for retry/replay.",
        "lane_striping": "Mainband data is striped across the module's data "
        "lanes (16 Std / 64 Adv); multi-module Links de-skew across modules.",
        "tx_rx_simultaneity": "Full-duplex: TX and RX modules operate "
        "independently and simultaneously; the sideband is full-duplex (2 "
        "lanes/direction).",
    }
    _write(p, d)


# ----------------------------------------------------------------------
# L18 — overwrite PCIe topology with UCIe die-to-die topology.
# ----------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "Point-to-point die-to-die (D2D) Link between two chiplets on a "
        "single package, built from 1, 2, or 4 uni-directional modules per "
        "direction. A multi-chiplet SoC contains multiple UCIe Links. "
        "Switched fabrics (e.g. CXL switches) are constructed by the carried "
        "protocol on top of UCIe-attached chiplets, not by UCIe itself.")
    f["supported_topologies"] = [
        {"name": "Single-module Link", "description": "One uni-directional "
         "module per direction between two chiplets; 1x bandwidth (16 lanes "
         "Std / 64 lanes Adv)."},
        {"name": "Two-module Link", "description": "Two modules per "
         "direction; 2x bandwidth."},
        {"name": "Four-module Link", "description": "Four modules per "
         "direction; 4x bandwidth."},
        {"name": "Multi-Link SoC", "description": "Several independent UCIe "
         "Links interconnecting multiple chiplets on one package."},
        {"name": "Protocol-level fabric", "description": "CXL/PCIe switches "
         "and pooled memory built by the carried protocol over UCIe-attached "
         "chiplets (e.g. CXL switch chiplets, co-packaged optics)."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Protocol Layer", "description": "Originates/terminates the "
         "carried protocol (PCIe/CXL/Streaming); presents Flits over FDI."},
        {"role": "Die-to-Die Adapter", "description": "Reliable delivery: "
         "Flit framing, 16-bit CRC + Retry, link-state management, parameter "
         "negotiation, Arb/Mux; FDI up, RDI down."},
        {"role": "Physical Layer", "description": "Die-to-die I/O: "
         "AFE/clocking, bump map, training, lane repair/reversal, sideband; "
         "RDI up."},
        {"role": "Module", "description": "Uni-directional physical unit (16 "
         "or 64 data lanes + Valid + Track); 1/2/4 modules form a Link."},
        {"role": "Sideband", "description": "Always-on 800 MHz auxiliary "
         "channel for the whole Link (management/training/registers)."},
    ]
    f["interconnect_role"] = (
        "UCIe is a die-to-die transport between two chiplets. The D2D Adapter "
        "guarantees per-Link delivery via CRC + Retry (Flit Mode); the "
        "Physical Layer carries the bits source-synchronously over a very "
        "short on-package channel. UCIe is transparent to the carried "
        "protocol's transactions — it transports PCIe/CXL/Streaming, it does "
        "not route or reorder them above the Flit level.")
    f["ordering_guarantees"] = {
        "flit_sequence": "Flits are delivered in order per Link; the "
        "Flit-header sequence number drives retry/replay.",
        "protocol_ordering": "Transaction-level ordering is the carried "
        "protocol's responsibility (e.g. PCIe/CXL ordering rules) above FDI.",
        "arb_mux_fairness": "When multiple protocols share a Link, the "
        "Adapter's Arb/Mux arbitrates fairly so none is starved.",
        "raw_mode": "In Raw Mode UCIe provides no Flit-level "
        "ordering/integrity; the protocol owns it.",
    }
    f["memory_vs_peripheral_regions"] = (
        "UCIe itself is addressless transport; address spaces belong to the "
        "carried protocol — PCIe (Memory/IO/Config/Message), CXL.mem (HDM "
        "coherent memory), CXL.cache (coherent caching), CXL.io (I/O), or a "
        "Streaming protocol's own address model. UCIe's own control plane is "
        "the sideband-accessible configuration registers.")
    dc = _ensure_dict(f, "device_classification")
    # Remove PCIe-sibling device classes.
    for stale in ("root_complex", "switch", "pci_express_endpoint",
                  "retimer", "cxl_device"):
        dc.pop(stale, None)
    dc["base_die"] = ("Central SoC die hosting multiple UCIe Links to "
                      "satellite chiplets.")
    dc["accelerator_chiplet"] = "PCIe/CXL accelerator mapped over FDI."
    dc["memory_chiplet"] = "CXL.mem memory expander mapped over FDI."
    dc["io_chiplet"] = "IO/SerDes chiplet exposing external PCIe/CXL."
    dc["streaming_chiplet"] = ("Chiplet carrying AXI/CHI/SFI/CPI or symmetric "
                               "coherency over Streaming/Raw.")
    dc["switch_chiplet"] = ("CXL/PCIe switch or co-packaged-optics die "
                            "connected via on-package UCIe.")
    f["default_signal_values_evidence_tables"] = [
        "UCIe Consortium tutorial overview (Hot Chips 2023) — three-layer "
        "stack, FDI/RDI, packages, data rates",
        "UCIe 1.0 characteristics/KPI table (data rate, width, bump pitch, "
        "reach, BW, power, latency, FIT)",
        "UCIe Flit-mapping figures (64B/256B Flit, 2B header + 2B CRC)",
        "UCIe Consortium specification structure (PHY / D2D Adapter / "
        "Protocol Layer, sideband, lane repair)",
    ]
    _write(p, d)


# ----------------------------------------------------------------------
# L19 — overwrite PCIe channel constraints with UCIe die-to-die channel
# constraints.
# ----------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = True
    f["electrical_channel_constraints"] = {
        "signaling": "single-ended NRZ (mainband), source-synchronous "
                     "forwarded clock",
        "mainband_line_encoding": "none (16-bit Flit CRC for integrity)",
        "data_rates_GT_s": list(_DATA_RATES),
        "max_data_rate_GT_s": 32,
        "lanes_per_module": {"standard": 16, "advanced": 64},
        "modules_per_link": list(_MODULES_PER_LINK),
        "sideband_freq_MHz": 800,
        "sideband_lanes_per_direction": 2,
        "package_standard": {
            "type": "2D organic substrate", "bump_pitch_um": "100-130",
            "channel_reach_mm": "<= 25",
            "bandwidth_per_module_per_dir_GB_s": 64,
            "reliability": "width degradation (no spare lanes)"},
        "package_advanced": {
            "type": "2.5D silicon interposer / bridge (CoWoS / EMIB / "
                    "FoCoS)",
            "bump_pitch_um": "25-55", "channel_reach_mm": "<= 2",
            "bandwidth_per_module_per_dir_GB_s": 256,
            "reliability": "spare lanes for repair"},
        "power_efficiency_pJ_per_bit": {"standard": 0.5, "advanced": 0.25},
        "latency_tx_plus_rx_ns": "< 2",
        "low_power_entry_exit_latency": "0.5 ns <=16 GT/s; 0.5-1 ns >=24 "
                                        "GT/s",
        "reliability_FIT": "0 < FIT << 1 (~1E-10 /hour) with UCIe Flit Mode",
        "bump_out_note": "Bump-out specified for interoperability across bump "
        "pitches and future pitch reductions; UCIe-S (Standard) and UCIe-A "
        "(Advanced) bump-outs, stacked/unstacked variants.",
    }
    f["notes"] = (
        "UCIe is a die-to-die interconnect specification; it fixes the "
        "electrical channel model (single-ended NRZ, forwarded clock, very "
        "short on-package reach), the bump map / bump pitch per package "
        "class, the module width, the sideband, and the Flit/CRC/Retry. It "
        "does NOT impose PDK-specific SDC/floorplan constraints — those "
        "(bump placement, AFE characterization, interposer routing, power "
        "delivery) are SoC/packaging-integrator concerns. The "
        "interoperability-critical constraints are the specified bump-out "
        "and the RDI/FDI interface conformance.")
    _write(p, d)


# ----------------------------------------------------------------------
# L20 — overwrite PCIe DFT facilities with UCIe sideband/register/CRC DFT.
# ----------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "Always-on Sideband", "purpose": "2 lanes/direction @ "
         "800 MHz; primary in-band controllability/observability path for "
         "training, debug, management, and configuration-register access — "
         "available before the mainband is up."},
        {"name": "Configuration registers", "purpose": "Discovery + run-time "
         "status: link-state, negotiated rate/width/protocol, "
         "lane-repair/reversal status, CRC/Retry counters, per-lane "
         "status."},
        {"name": "Flit CRC / Retry telemetry", "purpose": "The D2D Adapter "
         "exposes CRC-error and Retry counters for run-time signal-integrity "
         "monitoring (Flit Mode)."},
        {"name": "Lane Repair / Lane Reversal", "purpose": "Test and report "
         "spare-lane remap (Advanced) or width degradation (Standard) and "
         "transmit-side lane reversal."},
        {"name": "Sideband loopback / debug", "purpose": "Loopback and debug "
         "modes to characterize the link independently of the carried "
         "protocol."},
        {"name": "Mainband training patterns", "purpose": "Per-lane "
         "pattern/calibration during MBTRAIN for eye/timing characterization "
         "at the target rate."},
    ]
    f["internal_diagnostics_observability"] = [
        "Link-state FSM state (RESET/SBINIT/MBINIT/MBTRAIN/LINKINIT/"
        "ACTIVE/L1/L2).",
        "Negotiated data rate / module count / protocol / Flit format.",
        "Per-lane training and repair status (which lanes remapped).",
        "Flit CRC-error and Retry counters.",
        "Sideband health / bring-up status.",
        "Power-state (L0/L1/L2) and low-power exit-latency telemetry.",
    ]
    f["out_of_band_test_facilities"] = [
        "UCIe Compliance test tools (electrical / logical / protocol / "
        "software) per the UCIe Compliance Program.",
        "Vendor PHY bring-up / characterization probes — "
        "implementation-defined, not in the base spec.",
    ]
    f["notes"] = (
        "UCIe's protocol-level DFT surface is the always-on sideband plus "
        "configuration registers and the D2D Adapter's CRC/Retry telemetry, "
        "complemented by Lane Repair/Reversal. Chip-level JTAG / scan-chain / "
        "BIST and bump-level probing remain SoC/packaging-integrator "
        "concerns. Conformance and interoperability are established by the "
        "UCIe Compliance Program.")
    _write(p, d)


# ----------------------------------------------------------------------
# L21 — overwrite PCIe power states with UCIe ACTIVE/L1/L2 + vccaon.
# ----------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    # Remove PCIe-sibling power keys.
    for stale in ("device_states_d0_d3", "active_state_power_management_aspm",
                  "gen5_power_considerations"):
        f.pop(stale, None)
    f["link_power_management_states"] = [
        {"state": "ACTIVE (L0)", "name": "Active", "description": "Full "
         "operation; Flits flow at the negotiated data rate across all "
         "modules; sideband always-on.",
         "exit_latency_estimate": "n/a (already active)"},
        {"state": "L1", "name": "Standby", "description": "Low-power "
         "standby; mainband quiesced; link state preserved; fast resume.",
         "exit_latency_estimate": "0.5 ns at <=16 GT/s; 0.5-1 ns at >=24 "
         "GT/s"},
        {"state": "L2", "name": "Deep low-power", "description": "Deeper "
         "sleep; re-entry re-trains the mainband (MBTRAIN); sideband remains "
         "the wake/management path.",
         "exit_latency_estimate": "training-dominated (longer than L1)"},
    ]
    f["low_power_modes_summary"] = {
        "L0_active": "Full operational power; energy 0.5 pJ/b (Standard) / "
                     "0.25 pJ/b (Advanced).",
        "L1_standby": "Fast-exit standby (0.5 ns <=16G, 0.5-1 ns >=24G); "
                      "state preserved; power savings >= 85% target.",
        "L2_deep": "Deep low-power; re-train on exit; sideband stays alive "
                   "on vccaon.",
    }
    f["power_rails"] = [
        {"rail": "vccaon", "purpose": "Always-on power — keeps the sideband "
         "and link-management alive across low-power states."},
        {"rail": "vccio", "purpose": "IO power for the mainband/sideband "
         "drivers."},
        {"rail": "vss", "purpose": "Ground."},
    ]
    f["power_efficiency_targets_pJ_per_bit"] = {
        "standard_package": 0.5, "advanced_package": 0.25}
    f["power_savings_target"] = ">= 85% in low-power entry/exit"
    f["ucie_power_considerations"] = (
        "UCIe's very short on-package channel and single-ended "
        "source-synchronous signaling (no SerDes equalization, no line code) "
        "yield low energy-per-bit (0.5 / 0.25 pJ/b). The always-on sideband "
        "sits on vccaon so management/wake survives mainband power-down. Fast "
        "L1 entry/exit (sub-ns) keeps the chiplet link responsive; deeper L2 "
        "trades exit latency (re-training) for more savings.")
    f["notes"] = (
        "UCIe provides a link power-management framework (ACTIVE / L1 / L2) "
        "with an always-on sideband on a vccaon rail. Energy efficiency is a "
        "headline KPI (0.5 pJ/b Standard, 0.25 pJ/b Advanced) with >= 85% "
        "low-power savings. Exit latency is data-rate-dependent (0.5 ns "
        "<=16 GT/s, 0.5-1 ns >=24 GT/s for L1).")
    _write(p, d)


# ----------------------------------------------------------------------
# L22 — overwrite PCIe verification categories with UCIe ones.
# ----------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "Sideband bring-up — always-on 800 MHz sideband (2 lanes/direction) "
        "trains before the mainband.",
        "Link-state FSM — RESET -> SBINIT -> MBINIT -> MBTRAIN -> LINKINIT "
        "-> ACTIVE -> L1/L2 coverage.",
        "Mainband training — per-lane calibration at each supported rate "
        "4/8/12/16/24/32 GT/s.",
        "Interop rule — support all data rates up to the advertised "
        "maximum.",
        "Module scaling — 1/2/4-module Links deliver 1x/2x/4x bandwidth; "
        "multi-module de-skew.",
        "Valid framing + forwarded clock — per-module data sampling "
        "correctness.",
        "Flit framing — 2B header + 16-bit CRC; 64B / 256B / 256B "
        "latency-optimized formats.",
        "CRC error injection -> Retry/replay by sequence number.",
        "Raw Mode — Adapter bypass; protocol-supplied reliability.",
        "Arb/Mux — multiple protocols multiplexed on one Link.",
        "Protocol mappings over FDI — PCIe, CXL.io/CXL.cache/CXL.mem, "
        "Streaming (AXI/CHI/SFI/CPI).",
        "Lane Repair / Reversal — spare-lane remap (Advanced) / width "
        "degradation (Standard).",
        "Parameter negotiation — rate/width/protocol/Flit format over "
        "sideband.",
        "Configuration-register discovery + run-time access.",
        "Package classes — Standard vs Advanced (bump pitch, reach, width, "
        "BW).",
        "Power management — ACTIVE/L1/L2; low-power entry/exit latency.",
        "Latency — Tx+Rx < 2 ns; reliability — 0 < FIT << 1.",
        "Compliance / interoperability — electrical + logical + protocol + "
        "software.",
    ]
    f["notes"] = (
        "UCIe does not ship a formal testbench, but the "
        "tutorial/specification implies a verification plan spanning the "
        "three layers (PHY training + lane repair, D2D Adapter "
        "Flit/CRC/Retry + Arb/Mux + link-state, Protocol-Layer "
        "PCIe/CXL/Streaming mappings) and the sideband. The UCIe Compliance "
        "Program supplies the formal electrical/logical/protocol/software "
        "conformance suite; sample CRC RTL is provided in the spec.")
    _write(p, d)


# ----------------------------------------------------------------------
# L23 — overwrite PCIe security with UCIe anti-corruption + carried-protocol
# security pointers.
# ----------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = False
    f["anti_corruption_features"] = [
        "16-bit per-Flit CRC at the D2D Adapter detects mainband bit errors "
        "(Flit Mode).",
        "Retry/replay corrects detected Flit errors using the Flit-header "
        "sequence number.",
        "Lane Repair (spare lanes, Advanced) / width degradation (Standard) "
        "preserves the link through lane faults.",
        "Link-state management escalates on persistent errors (re-train / "
        "degrade) instead of passing corruption upward.",
        "Reliability target 0 < FIT << 1 (~1E-10 failures/hour) with UCIe "
        "Flit Mode.",
    ]
    f["anti_tampering_features"] = []
    f["confidentiality_features"] = []
    f["authentication_features"] = []
    f["future_security_pointers"] = [
        "Carried-protocol link security: when UCIe transports CXL or PCIe, "
        "those protocols' own IDE (Integrity & Data Encryption, AES-GCM) and "
        "CMA/SPDM attestation layer above the UCIe Protocol Layer.",
        "Later UCIe revisions add a standardized manageability/system "
        "architecture (e.g. UCIe 2.0) that can host management security.",
        "Streaming/Raw protocols carry their own security model; UCIe "
        "provides the transport, not cryptography.",
    ]
    f["notes"] = (
        "UCIe is a die-to-die transport: its built-in protections are "
        "anti-corruption only (Flit CRC + Retry, lane repair, "
        "reliability/FIT targets). The mainband is plaintext on the package. "
        "Cryptographic confidentiality/integrity/authentication are NOT part "
        "of the base UCIe data path; they are provided by the carried "
        "protocol (e.g. CXL IDE, PCIe IDE, CMA/SPDM) layered above the "
        "Protocol Layer. The on-package, in-package nature of die-to-die "
        "links also narrows the physical attack surface compared with "
        "board-level interconnects.")
    _write(p, d)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Re-exports the canonical single-source predicate (same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
# Single source of truth: tier_d_interconnect_detect (the runner imports the
# same callable). We empty-guard then delegate, so behaviour is identical and
# the no-misfire guard auto-discovers is_ucie here.
from tier_d_interconnect_detect import is_ucie as _det_ucie  # noqa: E402


def is_ucie(blob: str) -> bool:
    """Content-only `ucie` detector (re-export of the canonical predicate).

    FOREIGN-PRIMARY DEFER (mirrors the `is_mipi` doctrine — general,
    content-only, no chip/SKU/benchmark-name literal as detection logic):
    if the blob's DOMINANT subject is a foreign protocol, defer (return
    False) BEFORE delegating to the canonical UCIe predicate, so the
    generic UCIe synth never fires on a foreign spec that only mentions
    "UCIe" incidentally.

      - JESD204 (JESD204B/C converter-to-logic serial interface). The
        canonical UCIe predicate fires on a bare ``"UCIe" in blob``; a
        JESD204 spec cites UCIe ONCE as a contrast example ("a forwarded/
        source-synchronous lane clock as in DDR or UCIe is wrong for
        JESD204"), tripping that loose branch even though the document's
        true subject is JESD204. JESD204's DISTINCTIVE structural
        signature (the converter data-converter domain + Initial Lane
        Alignment Sequence + Code-Group Synchronization + multiframe/LMFC
        + SYSREF deterministic latency + the L/M/F/S converter-frame
        parameter set, or a dense ``jesd204`` name density) is ENTIRELY
        absent from a real UCIe die-to-die chiplet spec, so deferring on
        it is safe and does not touch own-fire. This mirrors the JESD204
        structural core in `jesd204_protocol_synth.is_jesd204`.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT UCIe). ---
    # JESD204B/C converter-link structural signature (converter domain +
    # ILAS + multiframe + deterministic-latency SYSREF/SYNC~ + the
    # converter-frame parameter or code-group-sync evidence), OR a dense
    # JESD204 name density. Either marks JESD204 as the dominant subject.
    _jesd_named_dense = (low.count("jesd204") + low.count("jesd 204")) >= 5
    _jesd_converter = (
        "data converter" in low
        or ("converter device" in low and "logic device" in low)
        or ("adc" in low and "dac" in low and "converter" in low))
    _jesd_ilas = ("ilas" in low or "initial lane alignment" in low)
    _jesd_multiframe = ("multiframe" in low or "lmfc" in low
                        or "local multiframe clock" in low)
    _jesd_det_latency = ("sysref" in low or "sync~" in low
                         or "sync_n" in low or "subclass" in low)
    _jesd_cgs_or_frameparams = (
        "code group synchronization" in low or "cgs" in low
        or "k28.5" in low or "/k/" in low
        or "octets per frame" in low or "octets/frame" in low
        or "frames per multiframe" in low or "frames/multiframe" in low
        or "samples per converter" in low or "l/m/f/s" in low)
    jesd204_primary = (
        _jesd_named_dense
        or (_jesd_converter and _jesd_ilas and _jesd_multiframe
            and _jesd_det_latency and _jesd_cgs_or_frameparams))
    if jesd204_primary:
        return False

    return bool(_det_ucie(blob))
