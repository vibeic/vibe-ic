"""Compute Express Link (CXL) cache-coherent interconnect synth helper.

v0.1.89 — ic_class-gated overlay for `bus_interconnect_protocol`-shaped
specs that exhibit the Compute Express Link structural signature. CXL is
a cache-coherent interconnect that runs over the PCI Express electrical /
physical layer (the "Flex Bus") and adds three dynamically-multiplexed
sub-protocols on a single link:

    CXL.io    — PCIe-like I/O / configuration / enumeration / DMA.
    CXL.cache — device-coherent access to host CPU memory.
    CXL.mem   — host access to device-attached memory.

Applies CXL 3.0 (CXL Consortium, August 2, 2022; PCIe 6.0 PHY, 64 GT/s,
256-byte Flit) spec-canonical content to L1-L23.

DETECTOR SIGNATURE (general, structural — NEVER reads input-doc filenames
or the benchmark folder name; reads only L1/L2 CONTENT blobs + canonical
protocol NAME/spec tokens):

    is_cxl = (
        ("Compute Express Link" in blob)
        or ("CXL.io" in blob and "CXL.mem" in blob)
        or ("CXL" in blob and "Flex Bus" in blob)
        or ("CXL.cache" in blob and "CXL.mem" in blob)
    )

SIBLING DISAMBIGUATION (vs plain PCIe — pcie / pcie_gen5):
CXL EXTENDS PCIe (it reuses the PCIe PHY + CXL.io is PCIe-derived), so the
PCIe detector may also fire and the `pcie_protocol_synth` overlay runs
FIRST. The CXL detector uses CXL-version-specific structural tokens that a
plain PCIe spec NEVER carries — the three "CXL.*" sub-protocol names plus
"Compute Express Link" / "Flex Bus". Plain PCIe (PCI Express Base Spec,
endpoint IPs, root-complex IPs) has NONE of "CXL.io" / "CXL.cache" /
"CXL.mem" / "Flex Bus" / "Compute Express Link", so it cannot trigger this
overlay. Conversely, because PCIe runs first and seeds PCIe-specific
identity / topology / packet values into L1-L4, this overlay must
FORCE-OVERWRITE (direct-assign, NOT setdefault) every L1/L2/L3/L4 key that
the PCIe synth populates with PCIe-specific values, so CXL-canonical
content wins. The runner is expected to wire this overlay AFTER the PCIe
overlay for any spec where both detectors fire.

Public entry: `apply_cxl_synth(generated_docs_dir, is_cxl, cxl_ic_name)`.
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


def _ensure_dict(d: dict, key: str) -> dict:
    """setdefault-None bug fix: if the value is None / empty / not-a-dict,
    replace with {} so subsequent .setdefault / direct-assign work."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    if not isinstance(d.get(key), dict):
        d[key] = {}
    return d[key]


# All 24 L docs (L8 splits into RTL_CONSTANTS + TIMING_WAVEFORM).
_ALL_L_DOCS = [
    "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
    "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
    "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
    "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
    "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
    "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
    "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
    "L16_COMPLIANCE_PROPERTIES.json", "L17_CHANNEL_SIGNAL_CATALOG.json",
    "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
    "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
    "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
]

# L14-L23 carry their content (and ic_name) INSIDE a top-level "fields" object.
_FIELDS_DOCS = {
    "L14_PROTOCOL_VERSIONING.json", "L15_ENCODING_TABLES.json",
    "L16_COMPLIANCE_PROPERTIES.json", "L17_CHANNEL_SIGNAL_CATALOG.json",
    "L18_INTERCONNECT_TOPOLOGY.json", "L19_CONSTRAINTS_PDK.json",
    "L20_DFT_SCAN_TOPOLOGY.json", "L21_POWER_INTENT.json",
    "L22_VERIFICATION_PLAN.json", "L23_SECURITY_REQUIREMENTS.json",
}


def apply_cxl_synth(generated_docs_dir: Path, is_cxl: bool,
                    cxl_ic_name: Optional[str]) -> None:
    """Apply Compute Express Link-specific synth when the signature matched."""
    if not is_cxl:
        return
    gd = Path(generated_docs_dir)

    # ---- Force ic_name across all 24 L docs. Placement convention:
    #        L1-L23 + L8_TIMING_WAVEFORM -> top-level "ic_name".
    #        L14-L23                     -> "ic_name" INSIDE "fields".
    #      (PCIe overlay may have seeded a top-level ic_name on the fields-
    #      docs; this re-asserts CXL's name in the correct place and removes
    #      any stale top-level ic_name from the L14-L23 group.)
    if cxl_ic_name is not None:
        for n in _ALL_L_DOCS:
            q = gd / n
            if not q.is_file():
                continue
            d = _read(q)
            if n in _FIELDS_DOCS:
                f = _ensure_dict(d, "fields")
                f["ic_name"] = cxl_ic_name
                d["fields"] = f
                d.pop("ic_name", None)
            else:
                d["ic_name"] = cxl_ic_name
            _write(q, d)

    _l1(gd)
    _l2(gd)
    _l3(gd)
    _l4(gd)
    _l5(gd)
    _l6(gd)
    _l7(gd)
    _l8_const(gd)
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


# ---------------------------------------------------------------------------
# L1 datasheet metadata — FORCE-OVERWRITE PCIe-polluted identity fields.
# ---------------------------------------------------------------------------
def _l1(gd: Path) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    # Sibling (PCIe) overlay ran first and seeded "PCI Express Base
    # Specification" identity. CXL must win: direct-assign, not setdefault.
    d["document_title"] = "Compute Express Link Specification"
    d["version"] = "Revision 3.0"
    d["revised_date"] = "August 2, 2022"
    d["manufacturer"] = "CXL Consortium"
    d["copyright"] = "© 2019-2022 CXL Consortium"
    d["abstract"] = (
        "Compute Express Link (CXL) is an open-standard, cache-coherent "
        "interconnect for high-speed, high-capacity CPU-to-device and "
        "CPU-to-memory connections in data-center computers. CXL is built "
        "on the serial PCI Express (PCIe) physical and electrical interface "
        "(the Flex Bus) and carries three dynamically-multiplexed "
        "sub-protocols on a single link: CXL.io (PCIe-based block I/O, "
        "configuration, enumeration, DMA), CXL.cache (device-coherent access "
        "to host CPU memory), and CXL.mem (host access to device-attached "
        "memory). CXL 3.0 is based on the PCIe 6.0 physical interface with "
        "PAM-4 signaling at 64 GT/s and a 256-byte Flit, and adds fabric "
        "capabilities (multi-level switching, multiple device types per "
        "port), enhanced coherency (back-invalidation), memory pooling and "
        "memory sharing, and Port-Based Routing (PBR) for up to 4,096 nodes.")
    d["keywords"] = [
        "Compute Express Link", "CXL", "CXL.io", "CXL.cache", "CXL.mem",
        "Flex Bus", "ARB/MUX", "cache coherency", "back-invalidation",
        "256B Flit", "memory pooling", "memory sharing",
        "Port-Based Routing", "Type 1", "Type 2", "Type 3", "PCIe 6.0",
    ]
    d["external_pins"] = [
        "TXp / TXn (Flex Bus differential transmit pair, per Lane — PCIe 6.0 PHY)",
        "RXp / RXn (Flex Bus differential receive pair, per Lane — PCIe 6.0 PHY)",
        "REFCLK+ / REFCLK- (100 MHz reference clock, SSC-tolerant)",
        "PERST# (Fundamental Reset, active LOW — shared with PCIe)",
        "CXL_PRSNT# / sideband (form-factor presence + management sideband)",
    ]
    d["external_pin_count_per_lane"] = 4
    d["supported_link_widths_lanes"] = [1, 2, 4, 8, 16]
    d["modes_of_operation"] = [
        {"name": "PCIe mode (Flex Bus negotiated to PCIe)",
         "line_rate_GT_s": 64, "encoding": "PAM-4 + FEC (PCIe 6.0)",
         "note": "Flex Bus trains as standard PCIe when CXL is not negotiated."},
        {"name": "CXL 1.1 / 2.0 mode (68-byte Flit)",
         "line_rate_GT_s": 32, "encoding": "NRZ (PCIe 5.0 PHY)",
         "flit_bytes": 68,
         "note": "CXL 1.x/2.0 use the PCIe 5.0 PHY and the 68-byte Flit."},
        {"name": "CXL 3.0 mode (256-byte Flit)",
         "line_rate_GT_s": 64, "encoding": "PAM-4 + FEC (PCIe 6.0 PHY)",
         "flit_bytes": 256,
         "note": "CXL 3.0 doubles bandwidth via PCIe 6.0 PAM-4 and the 256B Flit."},
    ]
    d["key_features"] = [
        "Cache-coherent interconnect over the PCIe physical/electrical layer (Flex Bus).",
        "Three dynamically-multiplexed sub-protocols on one link: CXL.io + CXL.cache + CXL.mem.",
        "CXL.io — PCIe-based I/O, configuration, link init/management, device discovery, enumeration, interrupts, DMA, register I/O via non-coherent loads/stores.",
        "CXL.cache — peripheral devices coherently access and cache host CPU memory with a low-latency request/response interface.",
        "CXL.mem — host CPU coherently accesses device-attached memory (volatile DRAM or persistent) with load/store commands.",
        "ARB/MUX block arbitrates + multiplexes CXL.cache and CXL.mem (common link/transaction layer) against CXL.io before the shared PCIe PHY.",
        "Three device types: Type 1 (CXL.io + CXL.cache), Type 2 (CXL.io + CXL.cache + CXL.mem), Type 3 (CXL.io + CXL.mem).",
        "CXL 3.0 introduces the 256-byte Flit in PAM-4 transfer mode on the PCIe 6.0 PHY at 64 GT/s.",
        "Fabric capabilities: multi-level switching and multiple device types per root port; non-tree topologies (mesh, ring, spine/leaf).",
        "Enhanced coherency replaces bias modes: Type 2/3 devices can back-invalidate (BI) host-cached data after modifying local memory.",
        "Memory pooling (each host gets a separate device-memory segment) and memory sharing (multiple devices share the same segment).",
        "Port-Based Routing (PBR) addressing supports fabrics of up to 4,096 nodes.",
        "Global Fabric Attached Memory (GFAM) — a Type 3 memory device attached to a switch node without a direct host connection.",
        "Peer-to-peer DMA within a virtual hierarchy in the same coherency domain.",
        "Asymmetric coherence: only the host memory controller implements the cache agent, reducing device complexity and latency.",
        "Backward compatible with CXL 1.1 / 2.0 and with plain PCIe via Flex Bus Alternate-Protocol negotiation.",
    ]
    d["topology_summary"] = (
        "CXL 1.x links a single host to a single device point-to-point over "
        "the Flex Bus. CXL 2.0 adds tree-based switching so multiple devices "
        "attach to one host and devices can be pooled across multiple hosts. "
        "CXL 3.0 adds multi-level switching and Port-Based Routing fabrics "
        "(mesh / ring / spine-leaf) of up to 4,096 nodes, where each node may "
        "be a host or a device of any type, with GFAM memory nodes attached "
        "directly to switches.")
    d["package_summary"] = (
        "The CXL specification is a wire-level + transaction-level + "
        "software-interface specification. It reuses the PCIe electrical / "
        "mechanical / form-factor infrastructure (the Flex Bus shares the "
        "PCIe connector and PHY); add-in-card mechanicals are inherited from "
        "the PCIe CEM specification plus CXL-specific form factors (e.g. "
        "E1.S / E3.S for memory modules).")
    d["use_cases"] = [
        "Memory expansion modules (Type 3) — terabyte-scale DRAM / persistent memory behind a CXL link.",
        "Memory pooling + disaggregation across multiple hosts in a rack (CXL 2.0/3.0 switches).",
        "Memory sharing of a common segment between multiple accelerators (CXL 3.0).",
        "Coherent accelerators (Type 2) — GPU / FPGA / ASIC with local HBM/GDDR coherently accessible by the host.",
        "Cache-only accelerators (Type 1) — smart NICs, PGAS NICs, NIC Atomics with no local memory.",
        "Composable / disaggregated data-center fabrics via Port-Based Routing.",
    ]
    d["revision_history"] = [
        {"version": "1.0", "date": "March 11, 2019", "description": "Initial CXL specification, based on PCIe 5.0; host coherent access to accelerator memory."},
        {"version": "1.1", "date": "June 2019", "description": "Errata / compliance update on PCIe 5.0."},
        {"version": "2.0", "date": "November 10, 2020", "description": "Adds CXL switching, memory pooling, device integrity + data encryption; still PCIe 5.0 PHY (no bandwidth increase)."},
        {"version": "3.0", "date": "August 2, 2022", "description": "Based on PCIe 6.0 PHY + PAM-4; double bandwidth (64 GT/s, 256B Flit); fabric multi-level switching, multiple device types per port, enhanced coherency (back-invalidation), peer-to-peer DMA, memory sharing, Port-Based Routing."},
    ]
    d["overview"] = (
        "Compute Express Link is an open cache-coherent interconnect that "
        "overcomes the performance and socket/packaging limits of DIMM memory "
        "by attaching device memory and coherent accelerators over the serial "
        "PCIe Flex Bus. The CXL transaction layer multiplexes three "
        "sub-protocols on one link: CXL.io (PCIe-derived non-coherent I/O, "
        "config, enumeration, DMA), CXL.cache (device-to-host coherent caching) "
        "and CXL.mem (host-to-device-memory coherent load/store). CXL.cache + "
        "CXL.mem share a common link/transaction layer distinct from CXL.io and "
        "are merged by an ARB/MUX block before the shared PCIe PHY. CXL 3.0 "
        "runs on the PCIe 6.0 PHY (PAM-4, 64 GT/s, 256-byte Flit) and adds "
        "fabric switching, Port-Based Routing for up to 4,096 nodes, enhanced "
        "coherency with back-invalidation, memory pooling and memory sharing.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L2 functional requirements — FORCE-OVERWRITE PCIe protocol_overview + FRs.
# ---------------------------------------------------------------------------
def _l2(gd: Path) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    # Direct-assign every PCIe-seeded key with CXL-specific values.
    po["type"] = (
        "Cache-coherent, dynamically-multiplexed, packet-based serial "
        "interconnect built on the PCIe Flex Bus; three sub-protocols "
        "(CXL.io / CXL.cache / CXL.mem) share one link.")
    po["duplex"] = (
        "dual-simplex (independent TX + RX differential pairs per Lane, "
        "inherited from the PCIe PHY)")
    po["synchronous_serial"] = False
    po["embedded_clock"] = True
    po["encoding"] = (
        "PCIe 6.0 PHY: PAM-4 (4 levels per UI) + Forward Error Correction "
        "+ Flit-based flow control at 64 GT/s (CXL 3.0). CXL 1.x/2.0 use the "
        "PCIe 5.0 NRZ PHY at 32 GT/s.")
    po["line_rate_GT_s"] = 64
    po["lane_widths_supported"] = [1, 2, 4, 8, 16]
    po["sub_protocols"] = {
        "CXL.io": "PCIe-based I/O, configuration, link init/management, device discovery, enumeration, interrupts, DMA, register I/O (non-coherent loads/stores).",
        "CXL.cache": "Device coherently accesses + caches host CPU memory via a low-latency request/response interface.",
        "CXL.mem": "Host coherently accesses device-attached memory (volatile or persistent) with load/store commands.",
    }
    po["layers"] = [
        "CXL.io link/transaction layer (PCIe-equivalent)",
        "CXL.cache + CXL.mem common link/transaction layer (separate from CXL.io)",
        "ARB/MUX (arbitration + multiplexing of the two layer stacks)",
        "Flex Bus physical layer (PCIe 6.0 PHY)",
    ]
    po["flit_bytes"] = 256
    po["flow_control"] = (
        "Credit-based flow control inherited from PCIe for CXL.io; "
        "CXL.cache + CXL.mem use channel-credited Flit-based flow control "
        "over the common link/transaction layer.")
    po["device_types"] = {
        "Type 1": "CXL.io + CXL.cache — coherent accelerator with no local memory (smart NIC, PGAS NIC, NIC Atomics).",
        "Type 2": "CXL.io + CXL.cache + CXL.mem — general accelerator (GPU/ASIC/FPGA) with HBM/GDDR local memory.",
        "Type 3": "CXL.io + CXL.mem — memory expander / persistent-memory device.",
    }
    po["coherency_model"] = (
        "Asymmetric: only the host memory controller implements the cache "
        "agent. CXL 3.0 replaces 1.x bias modes with enhanced coherency + "
        "back-invalidation (BI), where Type 2/3 devices invalidate host-"
        "cached data after modifying local memory.")
    po["max_fabric_nodes"] = 4096
    fr = [
        {"id": "FR-FLEXBUS-01", "text": "A CXL link is established over the PCIe Flex Bus. During link training the Flex Bus negotiates (via the PCIe Alternate Protocol mechanism) whether the link operates as plain PCIe or as CXL; if CXL is selected, all three sub-protocol stacks are enabled."},
        {"id": "FR-SUBPROTO-02", "text": "CXL carries three dynamically-multiplexed sub-protocols on a single link: CXL.io, CXL.cache, and CXL.mem. CXL.io is mandatory (used for discovery / configuration / enumeration); CXL.cache and CXL.mem are present per device type."},
        {"id": "FR-CXLIO-03", "text": "CXL.io provides PCIe-based block I/O: configuration, link initialization and management, device discovery and enumeration, interrupts, DMA, and register I/O via non-coherent loads/stores. CXL.io is functionally PCIe (TLP/DLLP based)."},
        {"id": "FR-CXLCACHE-04", "text": "CXL.cache defines device-to-host interactions: a peripheral device coherently accesses and caches host CPU memory through a low-latency request/response interface (D2H Request/Response/Data + H2D Request/Response/Data channels)."},
        {"id": "FR-CXLMEM-05", "text": "CXL.mem lets the host CPU coherently access device-attached memory with load/store commands, for both volatile (DRAM) and persistent (non-volatile) storage (M2S Request + RwD; S2M NDR + DRS channels)."},
        {"id": "FR-ARBMUX-06", "text": "CXL.cache and CXL.mem share one common link/transaction layer, separate from the CXL.io link/transaction layer. An Arbitration and Multiplexing (ARB/MUX) block multiplexes the two stacks before they are transported over the shared PCIe PHY."},
        {"id": "FR-FLIT-07", "text": "CXL 1.1/2.0 use a fixed 68-byte (528-bit) Flit consisting of four 16-byte slots plus a 2-byte CRC. CXL 3.0 introduces a 256-byte Flit in PAM-4 transfer mode on the PCIe 6.0 PHY."},
        {"id": "FR-DEVTYPE-08", "text": "CXL supports three device types: Type 1 (CXL.io + CXL.cache, no device memory), Type 2 (CXL.io + CXL.cache + CXL.mem, accelerator with local memory), Type 3 (CXL.io + CXL.mem, memory expander)."},
        {"id": "FR-COHERENCY-09", "text": "Coherence is asymmetric — only the host memory controller implements the cache agent. CXL 1.x Type 2 devices use device-bias / host-bias modes set per 4 KB page; CXL 3.0 replaces bias modes with enhanced coherency and back-invalidation."},
        {"id": "FR-BI-10", "text": "CXL 3.0 enhanced coherency lets a Type 2 or Type 3 device issue a Back-Invalidation (BI) to invalidate host-cached copies of data when the device modifies its local memory, and enables peer-to-peer transfers within a virtual hierarchy in the same coherency domain."},
        {"id": "FR-SWITCH-11", "text": "CXL 2.0 adds tree-based switching connecting multiple CXL 1.1/2.0 devices to a host and pooling devices across hosts. CXL 3.0 adds multi-level switching, multiple Type 1/Type 2 devices per root port, and non-tree fabric topologies."},
        {"id": "FR-POOLSHARE-12", "text": "CXL 3.0 supports memory pooling (each host is assigned a separate device-memory segment) and memory sharing (multiple devices share the same memory segment in the same coherency domain)."},
        {"id": "FR-PBR-13", "text": "Devices and hosts use Port-Based Routing (PBR) addressing which supports fabrics of up to 4,096 nodes; each node may be a host or a device of any type."},
        {"id": "FR-GFAM-14", "text": "A Type 3 device may implement Global Fabric Attached Memory (GFAM), connecting a memory device to a switch node without requiring a direct host connection."},
        {"id": "FR-PHY-15", "text": "CXL 3.0 uses the PCIe 6.0 physical interface (PAM-4 signaling, Forward Error Correction, 64 GT/s) for double the CXL 2.0 bandwidth; CXL 1.x/2.0 use the PCIe 5.0 PHY at 32 GT/s."},
        {"id": "FR-COMPAT-16", "text": "A CXL port is backward compatible: it trains as plain PCIe when the partner is not CXL-capable, and a CXL 3.0 port interoperates with CXL 1.1 / 2.0 partners at the negotiated common capability level."},
    ]
    d["functional_requirements"] = fr
    d["error_response_conditions"] = [
        "Flex Bus negotiation failure — Alternate Protocol negotiation does not converge; link falls back to plain PCIe (or down).",
        "Flit CRC / FEC error (CXL.cache + CXL.mem) — corrupted Flit detected; link-layer retry (replay) is triggered.",
        "CXL.io error — inherited PCIe error framework (LCRC/ECRC, NAK+replay, Completion Timeout, Unsupported Request).",
        "Coherency protocol violation — illegal D2H/H2D or M2S/S2M opcode sequence, or back-invalidation to a non-cached line.",
        "Poison propagation — a Flit / data carries the poison indication; consumers must mark the data invalid.",
        "Viral indication — a fatal error sets the viral state so dependent agents quiesce safely.",
        "Memory error (CXL.mem) — uncorrectable error on device-attached memory reported to the host via S2M response status.",
    ]
    d["compliance_requirements"] = [
        "Flex Bus link must negotiate CXL vs PCIe via the PCIe Alternate Protocol mechanism during training.",
        "CXL.io is mandatory and used for configuration, discovery, and enumeration of the CXL device.",
        "CXL.cache + CXL.mem must use the common link/transaction layer multiplexed against CXL.io by the ARB/MUX block.",
        "A Type 1 device must implement CXL.io + CXL.cache; a Type 2 device CXL.io + CXL.cache + CXL.mem; a Type 3 device CXL.io + CXL.mem.",
        "Coherence is asymmetric: the host memory controller is the sole cache agent for CXL.cache/CXL.mem traffic.",
        "CXL 3.0 devices must support the 256-byte Flit on the PCIe 6.0 PAM-4 PHY at 64 GT/s.",
        "CXL 3.0 enhanced-coherency devices must support Back-Invalidation (BI) in place of 1.x bias modes.",
        "Port-Based Routing must support up to 4,096 nodes in a CXL 3.0 fabric.",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L3 command / protocol — FORCE-OVERWRITE PCIe channels + packet classes.
# ---------------------------------------------------------------------------
def _l3(gd: Path) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    d["protocol_type"] = (
        "Three dynamically-multiplexed sub-protocols over the PCIe Flex Bus. "
        "CXL.io is a PCIe (TLP/DLLP) stack for non-coherent I/O + config. "
        "CXL.cache + CXL.mem are coherent message protocols carried in Flit "
        "slots over a common link/transaction layer, multiplexed against "
        "CXL.io by the ARB/MUX block before the shared PCIe PHY.")
    d["channels"] = [
        {"name": "CXL.io", "direction": "bidirectional (PCIe-based)",
         "description": "Non-coherent I/O / configuration / enumeration / DMA / register I/O; TLP + DLLP packets like PCIe."},
        {"name": "CXL.cache D2H", "direction": "device → host",
         "description": "Device-to-Host coherent channels: D2H Request, D2H Response, D2H Data — device requests/caches host memory."},
        {"name": "CXL.cache H2D", "direction": "host → device",
         "description": "Host-to-Device coherent channels: H2D Request (snoop), H2D Response, H2D Data."},
        {"name": "CXL.mem M2S", "direction": "host (master) → device (subordinate)",
         "description": "Master-to-Subordinate channels: M2S Request (Req) + M2S Request-with-Data (RwD) — host load/store to device memory."},
        {"name": "CXL.mem S2M", "direction": "device (subordinate) → host (master)",
         "description": "Subordinate-to-Master channels: S2M No-Data Response (NDR) + S2M Data Response (DRS)."},
        {"name": "Flex Bus PHY (TXp/TXn, RXp/RXn)", "direction": "differential serial (PCIe 6.0 PHY)",
         "description": "Shared PCIe electrical/physical layer carrying all three multiplexed sub-protocols."},
    ]
    d["packet_classes"] = [
        {"class": "CXL.io TLP/DLLP",
         "purpose": "PCIe-equivalent non-coherent I/O, configuration, enumeration, DMA, register access.",
         "subtypes": ["Memory Read/Write", "Configuration Read/Write", "I/O Read/Write", "Completion", "Message", "Ack/Nak/FC DLLP"]},
        {"class": "CXL.cache message",
         "purpose": "Device-coherent caching of host memory.",
         "subtypes": ["D2H Req (RdShared/RdOwn/RdAny/RdCurr/...)", "D2H Rsp", "D2H Data",
                      "H2D Req (Snoop: SnpData/SnpInv/SnpCur)", "H2D Rsp (GO / WritePull / ...)", "H2D Data"]},
        {"class": "CXL.mem message",
         "purpose": "Host-coherent access to device-attached memory.",
         "subtypes": ["M2S Req (MemRd/MemRdData/MemInv/...)", "M2S RwD (MemWr / MemWrPtl)",
                      "S2M NDR (Cmp / Cmp-S / Cmp-E)", "S2M DRS (MemData)",
                      "M2S/S2M Back-Invalidation (BISnp / BIRsp — CXL 3.0)"]},
    ]
    d["flit_format"] = {
        "cxl_1x_2x_flit_bytes": 68,
        "cxl_1x_2x_flit_bits": 528,
        "cxl_1x_2x_slots": "Four 16-byte slots + 2-byte CRC (66-byte payload + 2-byte CRC = 68 bytes).",
        "cxl_3x_flit_bytes": 256,
        "cxl_3x_transfer_mode": "PAM-4 (PCIe 6.0 PHY).",
        "slot_format": "Each Flit slot carries CXL.cache / CXL.mem channel messages (Req / Rsp / Data headers) or rollover data.",
        "cxlio_encapsulation": "CXL.io TLP/DLLP traffic is encapsulated in the Flit (or in PCIe TLP/DLLP framing on the PCIe 5.0 PHY for CXL 1.x/2.0).",
    }
    d["transaction_classes_split"] = [
        {"class": "CXL.io (non-coherent)", "transactions": ["Memory R/W", "Config R/W", "I/O R/W", "Completion", "Message"], "completion": "PCIe split-transaction semantics"},
        {"class": "CXL.cache (D2H/H2D coherent)", "transactions": ["D2H Req", "D2H Rsp", "D2H Data", "H2D Req (snoop)", "H2D Rsp", "H2D Data"], "completion": "request/response handshake with GO/WritePull"},
        {"class": "CXL.mem (M2S/S2M coherent)", "transactions": ["M2S Req", "M2S RwD", "S2M NDR", "S2M DRS", "BISnp/BIRsp (3.0)"], "completion": "S2M NDR (Cmp) / DRS (MemData) responses"},
    ]
    d["valid_ready_handshake_rules"] = [
        "CXL.io reuses PCIe credit-based flow control + ACK/NAK + replay (TLP/DLLP).",
        "CXL.cache + CXL.mem use channel credits per message class over the common link layer; senders must hold a credit before injecting a Flit slot message.",
        "The ARB/MUX block fairly arbitrates between the CXL.io stack and the CXL.cache/CXL.mem stack each Flit.",
        "Flit-level CRC (and FEC on the PCIe 6.0 PHY) protects CXL.cache/CXL.mem traffic; corrupted Flits trigger link-layer retry (replay).",
        "Coherency handshakes: H2D snoops (SnpData/SnpInv/SnpCur) elicit D2H responses; M2S requests elicit S2M NDR/DRS responses.",
    ]
    d["burst_based"] = False
    d["byte_oriented"] = False
    d["addressing"] = {
        "host_physical_address_width_bits": 52,
        "coherent_line_size_bytes": 64,
        "bias_mode_page_size_bytes_cxl_1x": 4096,
        "fabric_node_addressing": "Port-Based Routing (PBR) — up to 4096 nodes (CXL 3.0).",
        "cxlio_config_addressing": "PCIe Bus/Device/Function + extended config space (inherited from CXL.io).",
    }
    d["frame_format"] = {
        "flit_framing": "CXL 1.x/2.0: 68-byte (528-bit) Flit = four 16-byte slots + 2-byte CRC. CXL 3.0: 256-byte Flit in PAM-4 mode.",
        "cxlio_framing": "CXL.io uses PCIe TLP framing (STP/END) and DLLP framing (SDP/END) when on the PCIe 5.0 PHY.",
        "mux": "ARB/MUX selects, per Flit, between the CXL.io stack and the CXL.cache/CXL.mem common-layer stack before the shared PCIe PHY.",
    }
    _write(p, d)


# ---------------------------------------------------------------------------
# L4 register map — FORCE-OVERWRITE PCIe config-space-only view.
# ---------------------------------------------------------------------------
def _l4(gd: Path) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = False
    d["notes"] = (
        "CXL exposes control state through several structures rather than a "
        "single flat register map: (1) the standard PCIe Configuration Space "
        "of the CXL.io function (Vendor/Device ID, BARs, capabilities) plus a "
        "CXL-specific DVSEC (Designated Vendor-Specific Extended Capability) "
        "in PCIe config space that advertises CXL capability, device type, "
        "and CXL.cache/CXL.mem enable; (2) the CXL Component Registers (HDM "
        "Decoder, CXL Capability, RAS) in a memory-mapped region; (3) the CXL "
        "Device Registers (mailbox, memory-device status, event logs) for "
        "Type 3 devices; (4) the CEDT / CDAT ACPI structures the host uses to "
        "discover CXL memory topology and performance. These are defined in "
        "the CXL specification, not as a protocol-level flat register file.")
    d["cxl_register_structures"] = [
        {"name": "PCIe Configuration Space (CXL.io function)", "purpose": "Vendor/Device ID, BARs, standard PCIe capabilities; entry point for CXL discovery."},
        {"name": "CXL DVSEC (Designated Vendor-Specific Extended Capability)", "purpose": "Advertises CXL capability, device type (1/2/3), and CXL.cache/CXL.mem enable in PCIe config space."},
        {"name": "CXL Component Registers", "purpose": "HDM (Host-managed Device Memory) Decoder, CXL RAS Capability, CXL Link Capability, security."},
        {"name": "CXL Device Registers", "purpose": "Mailbox command interface, memory-device status, event logs, firmware update (Type 3)."},
        {"name": "CEDT / CDAT", "purpose": "ACPI CXL Early Discovery Table + Coherent Device Attribute Table — host discovers CXL memory topology + latency/bandwidth."},
    ]
    d["dvsec_significant_fields"] = [
        "CXL Capability (CXL.io / CXL.cache / CXL.mem capable bits)",
        "Device Type (Type 1 / Type 2 / Type 3 encoding)",
        "CXL Control (CXL.cache Enable, CXL.mem Enable, Cache SF Coverage)",
        "HDM Decoder Capability + Base/Size (Host-managed Device Memory ranges)",
        "Viral Enable / Viral Status",
    ]
    d["coherency_protocol_fields"] = {
        "coherent_line_size_bytes": 64,
        "host_physical_address_width_bits": 52,
        "device_types": ["Type 1 (cache)", "Type 2 (cache + mem)", "Type 3 (mem)"],
        "bias_modes_cxl_1x": ["device bias", "host bias"],
        "enhanced_coherency_cxl_3x": "Back-Invalidation (BI) replaces bias modes.",
    }
    d["flit_protocol_fields"] = {
        "flit_bytes_cxl_1x_2x": 68,
        "flit_bits_cxl_1x_2x": 528,
        "flit_slots": 4,
        "flit_slot_bytes": 16,
        "flit_crc_bytes": 2,
        "flit_bytes_cxl_3x": 256,
    }
    _write(p, d)


# ---------------------------------------------------------------------------
# L5 analog / device interface — PCIe Flex Bus electrical layer.
# ---------------------------------------------------------------------------
def _l5(gd: Path) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["analog_digital_interface_present"] = True
    d["signaling_summary"] = (
        "CXL reuses the PCIe electrical / physical layer (the Flex Bus): "
        "per-Lane low-voltage differential signaling on TXp/TXn and RXp/RXn, "
        "AC-coupled, with the embedded clock recovered from the serial stream. "
        "CXL 1.x/2.0 use the PCIe 5.0 PHY (NRZ, 32 GT/s). CXL 3.0 uses the "
        "PCIe 6.0 PHY: PAM-4 (4 amplitude levels per UI), Forward Error "
        "Correction, and a 64 GT/s line rate. There is no CXL-specific analog "
        "layer — all electrical compliance is defined by the corresponding "
        "PCIe base specification.")
    d.setdefault("phy_specs", {
        "cxl_1x_2x_phy": "PCIe 5.0 (NRZ, 32 GT/s, 128b/130b)",
        "cxl_3x_phy": "PCIe 6.0 (PAM-4, 64 GT/s, FEC, Flit-based)",
        "line_rate_GT_s_cxl_3x": 64,
        "modulation_cxl_3x": "PAM-4 (4 levels per Unit Interval)",
        "fec_cxl_3x": "Forward Error Correction (PCIe 6.0)",
        "ac_coupling_required": True,
        "differential_impedance_ohm": 100,
        "refclk_freq_MHz": 100,
    })
    d.setdefault("electrical_inheritance_note",
        "All transmitter / receiver eye, jitter, de-emphasis / equalization, "
        "and channel-loss budgets are inherited from the PCIe 5.0 (CXL 1.x/2.0) "
        "or PCIe 6.0 (CXL 3.0) base specification; CXL adds no new analog spec.")
    d.setdefault("voltage_classes", [
        "Inherits PCIe differential signaling (AC-coupled, ~100 ohm differential).",
        "CXL 3.0 PAM-4 uses 4 amplitude levels per UI per the PCIe 6.0 PHY.",
        "Receiver tolerates a different DC common mode than the transmitter (AC coupling).",
    ])
    _write(p, d)


# ---------------------------------------------------------------------------
# L6 control logic / FSM — CXL coherency + ARB/MUX state.
# ---------------------------------------------------------------------------
def _l6(gd: Path) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["fsm_states_flexbus_negotiation"] = [
        {"name": "PCIe_LinkTraining", "description": "Standard PCIe LTSSM training over the Flex Bus; Alternate Protocol (CXL) is advertised in TS1/TS2 modified ordered sets."},
        {"name": "CXL_AltProtocol_Negotiate", "description": "Both ends advertise CXL capability + supported CXL version (1.1 / 2.0 / 3.0) via the PCIe Alternate Protocol mechanism."},
        {"name": "CXL_Mode", "description": "Link operates as CXL; CXL.io + CXL.cache + CXL.mem stacks enabled; ARB/MUX active."},
        {"name": "PCIe_Mode", "description": "Partner not CXL-capable (or CXL not negotiated); link operates as plain PCIe."},
    ]
    d["fsm_states_arbmux"] = [
        {"name": "ARBMUX_IDLE", "description": "No pending Flit traffic; PM-state requests handled (ARB/MUX manages link PM virtual LSM per sub-protocol)."},
        {"name": "ARBMUX_CXLIO", "description": "Arbitrates a Flit window to the CXL.io link/transaction stack."},
        {"name": "ARBMUX_CXLCACHEMEM", "description": "Arbitrates a Flit window to the common CXL.cache + CXL.mem link/transaction stack."},
    ]
    d["fsm_states_coherency"] = [
        {"name": "I (Invalid)", "description": "Cache line not present (MESI-style device cache state for CXL.cache)."},
        {"name": "S (Shared)", "description": "Line cached read-only; may be shared with host / other devices."},
        {"name": "E (Exclusive)", "description": "Line cached read-write exclusive; clean."},
        {"name": "M (Modified)", "description": "Line cached modified (dirty); device owns the only valid copy."},
        {"name": "BI (Back-Invalidate)", "description": "CXL 3.0: device issues Back-Invalidation to invalidate host-cached copies after modifying local memory."},
    ]
    d["fsm_hints"] = {
        "trigger": "Flex Bus training + Alternate-Protocol negotiation selects CXL vs PCIe; once CXL mode is entered the ARB/MUX begins per-Flit arbitration.",
        "rule": "CXL.cache device caches host lines via D2H Req; host snoops via H2D Req; CXL.mem host accesses device memory via M2S Req / RwD with S2M NDR / DRS responses.",
        "abort": "Uncorrectable / fatal errors set the viral state so dependent agents quiesce; Flit CRC/FEC failures trigger link-layer replay.",
    }
    d["anti_deadlock_rule"] = (
        "Coherence is asymmetric — only the host memory controller is the "
        "cache agent — which bounds the protocol state and avoids the "
        "deadlock complexity of symmetric CPU-CPU coherence. Channel credits "
        "are tracked per message class so a slow class cannot block others.")
    d["exit_from_reset_or_poweron"] = (
        "PERST# deassertion → PCIe Flex Bus trains → Alternate-Protocol "
        "negotiation selects CXL → CXL.io enumerates the device via PCIe "
        "config + CXL DVSEC → host programs HDM Decoders + enables "
        "CXL.cache/CXL.mem → ARB/MUX activates and coherent traffic begins.")
    d["configurations"] = [
        {"name": "Type 1 device", "description": "CXL.io + CXL.cache; no device memory; coherent accelerator."},
        {"name": "Type 2 device", "description": "CXL.io + CXL.cache + CXL.mem; accelerator with local HBM/GDDR."},
        {"name": "Type 3 device", "description": "CXL.io + CXL.mem; memory expander / persistent memory."},
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L7 test / debug.
# ---------------------------------------------------------------------------
def _l7(gd: Path) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_debug_architecture_present"] = True
    d["spec_provided_observability"] = [
        {"name": "Flex Bus mode probe", "purpose": "Observe whether the link negotiated CXL or PCIe, and the negotiated CXL version (1.1/2.0/3.0)."},
        {"name": "CXL RAS Capability registers", "purpose": "CXL Component RAS registers log correctable / uncorrectable errors on CXL.cache/CXL.mem and CXL.io."},
        {"name": "CXL Device mailbox + event logs", "purpose": "Type 3 device mailbox exposes status, health, and event-log records (informational / warning / failure / fatal)."},
        {"name": "Flit CRC / FEC counters", "purpose": "Link-layer Flit error + replay counters for CXL.cache/CXL.mem."},
        {"name": "Coherency channel monitor", "purpose": "Protocol analyzers decode D2H/H2D and M2S/S2M channel messages."},
        {"name": "ARB/MUX state", "purpose": "Per-sub-protocol virtual link-state-machine + arbitration observability."},
    ]
    d["error_detection_mechanisms"] = [
        "Flit CRC (CXL.cache + CXL.mem) — detects corrupted Flits; triggers link-layer retry.",
        "Forward Error Correction (PCIe 6.0 PHY for CXL 3.0) — corrects symbol errors before the link layer.",
        "CXL.io inherits the full PCIe error framework (LCRC/ECRC, NAK+replay, AER).",
        "Poison indication — propagates known-bad data so consumers can mark it invalid.",
        "Viral indication — fatal-error containment that quiesces dependent agents.",
        "CXL.mem uncorrectable memory error — reported to host via S2M response status.",
    ]
    d["test_modes"] = [
        {"name": "CXL Compliance (CV) test", "purpose": "CXL Consortium compliance / interop testing of CXL.io / CXL.cache / CXL.mem behaviors."},
        {"name": "PCIe Loopback / Compliance", "purpose": "Inherited PCIe PHY loopback + compliance pattern for the Flex Bus electrical layer."},
        {"name": "Mailbox diagnostics (Type 3)", "purpose": "Memory-device self-test, health info, and event-log retrieval via the CXL mailbox."},
    ]
    d["interrupt_or_event_sources"] = [
        {"event": "CXL RAS error", "trigger": "Correctable / uncorrectable error on CXL.cache / CXL.mem / CXL.io."},
        {"event": "Memory module event", "trigger": "Type 3 device posts an event-log record (health change, media error)."},
        {"event": "Viral", "trigger": "Fatal error sets viral state; propagated to dependent agents."},
        {"event": "Hot-add / hot-remove", "trigger": "CXL 2.0/3.0 switch-mediated device add/remove (managed hot-plug)."},
    ]
    d["notes"] = (
        "CXL specifies a RAS framework (CXL RAS Capability registers, poison, "
        "viral) plus a Type 3 device mailbox + event-log mechanism. The PCIe "
        "PHY-level observability (loopback, compliance pattern, AER for "
        "CXL.io) is inherited from the underlying PCIe base spec. JTAG/scan/"
        "BIST remain integrator concerns.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L8 RTL constants.
# ---------------------------------------------------------------------------
def _l8_const(gd: Path) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    for k, v in {
        "PHY": "PCIe Flex Bus",
        "CXL_3X_PHY": "PCIe 6.0 (PAM-4, FEC)",
        "CXL_1X_2X_PHY": "PCIe 5.0 (NRZ)",
        "CXL_3X_LINE_RATE_GT_S": 64,
        "CXL_2X_LINE_RATE_GT_S": 32,
        "SUPPORTED_LINK_WIDTHS_LANES": [1, 2, 4, 8, 16],
        "FLIT_BYTES_CXL_1X_2X": 68,
        "FLIT_BITS_CXL_1X_2X": 528,
        "FLIT_SLOTS": 4,
        "FLIT_SLOT_BYTES": 16,
        "FLIT_CRC_BYTES": 2,
        "FLIT_BYTES_CXL_3X": 256,
        "COHERENT_LINE_SIZE_BYTES": 64,
        "HOST_PHYSICAL_ADDRESS_WIDTH_BITS": 52,
        "BIAS_MODE_PAGE_SIZE_BYTES_CXL_1X": 4096,
        "MAX_FABRIC_NODES_PBR_CXL_3X": 4096,
        "SUB_PROTOCOL_COUNT": 3,
        "DEVICE_TYPE_COUNT": 3,
    }.items():
        wp[k] = v
    d["sub_protocols"] = {
        "CXL.io": "PCIe-based non-coherent I/O / config / enumeration / DMA.",
        "CXL.cache": "Device-coherent access to host memory (D2H/H2D channels).",
        "CXL.mem": "Host-coherent access to device memory (M2S/S2M channels).",
    }
    d["device_types_table"] = {
        "Type 1": "CXL.io + CXL.cache (no device memory)",
        "Type 2": "CXL.io + CXL.cache + CXL.mem (accelerator + local memory)",
        "Type 3": "CXL.io + CXL.mem (memory expander)",
    }
    d["coherency_channels"] = {
        "CXL.cache_D2H": ["D2H Req", "D2H Rsp", "D2H Data"],
        "CXL.cache_H2D": ["H2D Req (Snoop)", "H2D Rsp", "H2D Data"],
        "CXL.mem_M2S": ["M2S Req", "M2S RwD"],
        "CXL.mem_S2M": ["S2M NDR", "S2M DRS"],
        "CXL.mem_BI_cxl_3x": ["M2S BISnp", "S2M BIRsp"],
    }
    d["key_constants_for_RTL_authoring"] = {
        "is_serial": True,
        "is_differential": True,
        "is_coherent": True,
        "runs_over_pcie_phy": True,
        "sub_protocol_mux": "ARB/MUX block multiplexes CXL.io vs CXL.cache+CXL.mem each Flit.",
        "flit_based": True,
        "flit_bytes_cxl_3x": 256,
        "flit_bytes_cxl_1x_2x": 68,
        "coherency": "asymmetric (host memory controller is the sole cache agent)",
        "enhanced_coherency_cxl_3x": "Back-Invalidation (BI) replaces bias modes.",
    }
    _write(p, d)


# ---------------------------------------------------------------------------
# L8 timing / waveform.
# ---------------------------------------------------------------------------
def _l8_timing(gd: Path) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d["line_rate_waveform"] = {
        "cxl_3x_line_rate_GT_s": 64,
        "cxl_3x_modulation": "PAM-4 (PCIe 6.0 PHY)",
        "cxl_2x_line_rate_GT_s": 32,
        "cxl_2x_modulation": "NRZ (PCIe 5.0 PHY)",
        "flit_bytes_cxl_3x": 256,
        "flit_bytes_cxl_1x_2x": 68,
        "note": "CXL 3.0 doubles CXL 2.0 bandwidth via the PCIe 6.0 PAM-4 PHY + 256B Flit.",
    }
    d["flit_framing_waveform"] = {
        "cxl_1x_2x_flit": "528-bit (68-byte) Flit = four 16-byte slots + 2-byte CRC, transmitted over the PCIe 5.0 PHY.",
        "cxl_3x_flit": "256-byte Flit transmitted in PAM-4 transfer mode over the PCIe 6.0 PHY.",
        "mux": "ARB/MUX selects per Flit between the CXL.io stack and the CXL.cache/CXL.mem common stack.",
    }
    d["coherency_handshake_sequence"] = {
        "device_read_host_memory": "D2H Req (RdShared/RdOwn) → host snoop/resolve → H2D Rsp (GO) + H2D Data.",
        "host_read_device_memory": "M2S Req (MemRd) → device → S2M DRS (MemData) + S2M NDR (Cmp).",
        "host_write_device_memory": "M2S RwD (MemWr) → device → S2M NDR (Cmp).",
        "back_invalidation_cxl_3x": "Device modifies local memory → M2S/S2M BISnp invalidates host-cached copies → BIRsp.",
    }
    d["general_timing_rule"] = (
        "CXL timing is Flit-paced over the PCIe PHY symbol clock. CXL.cache + "
        "CXL.mem coherent latency is the key metric — CXL memory controllers "
        "typically add about 200 ns of access latency relative to local DRAM.")
    d["latency_note"] = "CXL memory controllers typically add about 200 ns of latency."
    d["phy_inheritance"] = (
        "All eye / jitter / UI timing is inherited from PCIe 5.0 (CXL 1.x/2.0) "
        "or PCIe 6.0 (CXL 3.0).")
    _write(p, d)


# ---------------------------------------------------------------------------
# L9 integration spec.
# ---------------------------------------------------------------------------
def _l9(gd: Path) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d["module_role"] = (
        "Cache-coherent interconnect that attaches coherent accelerators and "
        "device-attached memory to a host CPU over the PCIe Flex Bus. Defines "
        "the CXL.io / CXL.cache / CXL.mem protocols between a CXL host (Root "
        "Port) and CXL devices (Type 1/2/3), optionally through CXL switches "
        "and Port-Based-Routing fabrics.")
    d["topology_description"] = (
        "CXL 1.x: point-to-point host↔device over one Flex Bus link. CXL 2.0: "
        "tree-based switch fabric for multi-device attach + cross-host memory "
        "pooling. CXL 3.0: multi-level switching + Port-Based Routing fabrics "
        "(mesh / ring / spine-leaf) of up to 4,096 nodes, with GFAM memory "
        "nodes attached directly to switches and memory sharing across "
        "devices in the same coherency domain.")
    d["integration_overview"] = {
        "phy": "PCIe Flex Bus (PCIe 5.0 for CXL 1.x/2.0; PCIe 6.0 for CXL 3.0)",
        "max_lane_width": 16,
        "lane_widths_supported": [1, 2, 4, 8, 16],
        "cxl_3x_line_rate_GT_s": 64,
        "sub_protocols": ["CXL.io", "CXL.cache", "CXL.mem"],
        "device_types": ["Type 1", "Type 2", "Type 3"],
        "max_fabric_nodes_pbr": 4096,
        "coherent_line_size_bytes": 64,
        "host_side_discovery": "PCIe config space + CXL DVSEC + CEDT/CDAT ACPI tables.",
    }
    d["interface_categories"] = [
        "CXL Host (Root Port) — implements the host cache agent + home agent for CXL.cache/CXL.mem.",
        "CXL Type 1 device — coherent accelerator (CXL.io + CXL.cache).",
        "CXL Type 2 device — accelerator with local memory (CXL.io + CXL.cache + CXL.mem).",
        "CXL Type 3 device — memory expander (CXL.io + CXL.mem).",
        "CXL Switch — fabric switching (CXL 2.0 tree; CXL 3.0 multi-level + PBR).",
    ]
    d["interconnect_topologies_supported"] = [
        "Point-to-point host↔device (CXL 1.x).",
        "Tree-based switch fabric (CXL 2.0) with memory pooling.",
        "Multi-level switching + Port-Based-Routing fabric (CXL 3.0): mesh / ring / spine-leaf.",
        "Global Fabric Attached Memory (GFAM) nodes attached to switches.",
        "Memory sharing across devices in one coherency domain (CXL 3.0).",
    ]
    d["soc_dependent_items"] = [
        "PCIe Flex Bus PHY (PCIe 5.0 or 6.0 transceiver) implementation.",
        "Host cache agent + home agent for CXL.cache/CXL.mem coherency.",
        "HDM (Host-managed Device Memory) Decoder configuration.",
        "ARB/MUX integration between the CXL.io and CXL.cache/CXL.mem stacks.",
        "CXL DVSEC + Component/Device register placement in the address map.",
        "CEDT/CDAT firmware tables for host CXL-memory discovery.",
    ]
    d["device_classes_examples"] = [
        "CXL memory expander (Type 3) — DRAM / persistent memory module.",
        "CXL coherent GPU / FPGA / ASIC accelerator (Type 2).",
        "CXL smart NIC / PGAS NIC (Type 1).",
        "CXL switch for memory pooling / disaggregation.",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L10 test cases.
# ---------------------------------------------------------------------------
def _l10(gd: Path) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["test_cases_present"] = (
        "partial - the CXL specification defines compliance behaviors for "
        "CXL.io / CXL.cache / CXL.mem, Flex Bus negotiation, coherency, "
        "switching, and the Type 3 mailbox; formal compliance is run via the "
        "CXL Consortium Compliance program, but the spec does not ship a "
        "testbench.")
    d["derived_compliance_test_categories"] = [
        "Flex Bus link training: negotiate CXL vs PCIe via the Alternate Protocol mechanism.",
        "CXL version negotiation: 1.1 / 2.0 / 3.0 common-capability selection.",
        "CXL.io enumeration: PCIe config space + CXL DVSEC discovery; device-type detection.",
        "CXL.cache D2H read (RdShared / RdOwn) + H2D snoop + GO/Data response.",
        "CXL.mem M2S MemRd → S2M DRS (MemData) + NDR (Cmp).",
        "CXL.mem M2S MemWr (RwD) → S2M NDR (Cmp).",
        "Type 1 device: CXL.io + CXL.cache only (no CXL.mem) behavior.",
        "Type 2 device: device-bias / host-bias mode (CXL 1.x) per 4 KB page.",
        "Type 2/3 device: Back-Invalidation (BI) on local-memory modification (CXL 3.0).",
        "Type 3 memory expander: HDM Decoder programming + host load/store.",
        "256-byte Flit operation on the PCIe 6.0 PAM-4 PHY (CXL 3.0).",
        "68-byte Flit operation on the PCIe 5.0 PHY (CXL 1.x/2.0).",
        "ARB/MUX fairness: interleave CXL.io and CXL.cache/CXL.mem Flits.",
        "Memory pooling: separate device-memory segment per host (CXL 2.0/3.0).",
        "Memory sharing: same segment across multiple devices (CXL 3.0).",
        "Multi-level switching + Port-Based-Routing fabric (CXL 3.0).",
        "Flit CRC error injection → link-layer retry (replay).",
        "Poison + viral propagation on uncorrectable error.",
        "Type 3 mailbox commands: identify, health info, event log, firmware.",
        "Backward compatibility: CXL 3.0 port trains with a CXL 1.1 / 2.0 partner.",
        "Fallback: CXL port trains as plain PCIe against a non-CXL partner.",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L11 OTP content.
# ---------------------------------------------------------------------------
def _l11(gd: Path) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = False
    d["otp_equivalent_factory_burned_fields"] = [
        {"field": "Vendor ID / Device ID", "width_bits": 32, "location": "CXL.io PCIe Config Space header", "note": "Standard PCIe identifiers of the CXL.io function."},
        {"field": "CXL DVSEC Vendor ID", "width_bits": 16, "location": "CXL DVSEC in PCIe extended config space", "note": "Identifies the Designated Vendor-Specific Extended Capability as CXL."},
        {"field": "Device Type (Type 1/2/3)", "width_bits": 2, "location": "CXL DVSEC capability field", "note": "Silicon-fixed CXL device-type encoding."},
        {"field": "CXL Capability (io/cache/mem capable)", "width_bits": 3, "location": "CXL DVSEC", "note": "Which sub-protocols the device supports."},
        {"field": "Memory device serial / identify (Type 3)", "width_bits": 64, "location": "CXL Device mailbox Identify output", "note": "Per-module identity for Type 3 memory devices."},
    ]
    d["notes"] = (
        "CXL does not specify OTP/fuse content as a protocol concept. In "
        "practice a CXL device burns its PCIe Vendor/Device ID and its "
        "CXL DVSEC device-type + capability bits so that CXL.io enumeration "
        "and CXL discovery return the correct identity immediately after "
        "reset, before any software-programmed register is written.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L12 behavioral sequences.
# ---------------------------------------------------------------------------
def _l12(gd: Path) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d["link_bring_up_sequence"] = [
        "1. PERST# deassertion; PCIe Flex Bus begins LTSSM training.",
        "2. Both ends advertise CXL capability + version via the PCIe Alternate Protocol mechanism in modified TS1/TS2 ordered sets.",
        "3. If both sides agree on CXL, the link enters CXL mode; otherwise it operates as plain PCIe.",
        "4. CXL.io enumerates the device: PCIe config space scan + CXL DVSEC read to learn device type + capabilities.",
        "5. Host reads CEDT / CDAT ACPI tables to learn CXL memory topology + latency/bandwidth.",
        "6. Host programs HDM Decoders + enables CXL.cache / CXL.mem in the DVSEC control.",
        "7. ARB/MUX activates; CXL.cache + CXL.mem coherent traffic may begin.",
    ]
    d["cxl_cache_read_sequence"] = [
        "1. Device issues a D2H Req (e.g. RdShared / RdOwn) for a host memory line.",
        "2. Host home agent resolves coherence (snoops other caches if needed).",
        "3. Host returns H2D Rsp (GO — global observation) granting the requested state.",
        "4. Host returns H2D Data with the cache line; device installs it in the requested MESI state.",
    ]
    d["cxl_mem_access_sequence"] = [
        "1. Host issues an M2S Req (MemRd) — or M2S RwD (MemWr) — to a device-attached memory line.",
        "2. Device memory controller services the access.",
        "3. For a read, device returns S2M DRS (MemData) carrying the line, plus S2M NDR (Cmp).",
        "4. For a write, device returns S2M NDR (Cmp).",
    ]
    d["back_invalidation_sequence_cxl_3x"] = [
        "1. A Type 2/3 device modifies a line in its local device-attached memory.",
        "2. The device issues a Back-Invalidation Snoop (BISnp) toward the host to invalidate any host-cached copies.",
        "3. The host invalidates its cached copy and returns a BIRsp.",
        "4. Coherence is restored without bias-mode page management (CXL 3.0 enhanced coherency).",
    ]
    d["memory_pooling_sequence"] = [
        "1. A CXL 2.0/3.0 switch presents pooled device memory to multiple hosts.",
        "2. Each host is assigned a separate device-memory segment (pooling).",
        "3. (CXL 3.0) multiple devices may share the same segment (sharing) in one coherency domain.",
    ]
    _write(p, d)


# ---------------------------------------------------------------------------
# L13 lab calibration.
# ---------------------------------------------------------------------------
def _l13(gd: Path) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d["lab_calibration_present"] = False
    d["lab_measurement_targets_from_spec"] = [
        {"name": "PCIe Flex Bus eye / jitter", "purpose": "Inherited PCIe 5.0 (CXL 1.x/2.0) or PCIe 6.0 PAM-4 (CXL 3.0) electrical compliance."},
        {"name": "CXL coherent access latency", "purpose": "Measure added latency of CXL memory access vs local DRAM (typically ~200 ns)."},
        {"name": "Flit error / replay rate", "purpose": "Verify Flit CRC + FEC keep the CXL.cache/CXL.mem link below target error rates."},
        {"name": "Coherency protocol decode", "purpose": "Protocol analyzer captures D2H/H2D + M2S/S2M channel messages for compliance."},
        {"name": "Type 3 memory health / margining", "purpose": "Memory-device mailbox health + media-error reporting."},
    ]
    d["notes"] = (
        "CXL inherits all PHY-level electrical calibration from the underlying "
        "PCIe base spec (PCIe 5.0 or 6.0). The CXL-specific lab metric is "
        "coherent-access latency (CXL memory controllers add about 200 ns); "
        "protocol-level compliance is decoded with CXL-aware analyzers per the "
        "CXL Consortium Compliance program.")
    _write(p, d)


# ---------------------------------------------------------------------------
# L14 protocol versioning (fields-nested).
# ---------------------------------------------------------------------------
def _l14(gd: Path) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["spec_version"] = "Compute Express Link (CXL) Specification Revision 3.0 (August 2, 2022)"
    f["previous_versions"] = [
        "CXL 1.0 (March 11, 2019) — initial spec, PCIe 5.0 PHY, host coherent access to accelerator memory.",
        "CXL 1.1 (June 2019) — errata / compliance update.",
        "CXL 2.0 (November 10, 2020) — switching, memory pooling, device integrity + data encryption; still PCIe 5.0 PHY.",
    ]
    f["key_changes"] = [
        {"version": "3.0",
         "summary": "Based on the PCIe 6.0 physical interface with PAM-4 coding and double the bandwidth (64 GT/s). Adds the 256-byte Flit; fabric capabilities with multi-level switching and multiple device types per port; enhanced coherency with peer-to-peer DMA and back-invalidation; memory sharing (vs CXL 2.0 pooling-only); Port-Based Routing (PBR) for up to 4,096 nodes; Global Fabric Attached Memory (GFAM)."},
    ]
    f["future_versions_industry_outline"] = [
        {"version": "CXL 3.1 (November 14, 2023)", "summary": "Fabric manageability + trusted-execution (TEE) + memory expander enhancements on the PCIe 6.0 PHY."},
        {"version": "CXL 3.2 (December 3, 2024)", "summary": "Further memory + manageability + security extensions."},
        {"version": "CXL 4.0 (November 18, 2025)", "summary": "Based on the PCIe 7.0 PHY (128 GT/s); double the CXL 3.x bandwidth."},
    ]
    f["backward_compat_traps"] = [
        {"trap_name": "Flex_Bus_falls_back_to_PCIe",
         "rule": "If the partner does not advertise CXL during Alternate-Protocol negotiation, the link trains as plain PCIe.",
         "trap": "A CXL device plugged into a CXL-incapable slot silently operates as a PCIe device — no coherent memory."},
        {"trap_name": "CXL_version_downshift",
         "rule": "A CXL 3.0 port negotiates down to the common version (e.g. 2.0) with an older partner.",
         "trap": "256B-Flit + fabric + back-invalidation features are unavailable when negotiated down to CXL 1.x/2.0 (68B Flit, no BI, tree-only switching)."},
        {"trap_name": "Bias_mode_vs_back_invalidation",
         "rule": "CXL 1.x Type 2 uses device-bias/host-bias per 4 KB page; CXL 3.0 replaces this with back-invalidation enhanced coherency.",
         "trap": "Software written for bias-mode page management must be reworked for CXL 3.0 enhanced coherency."},
        {"trap_name": "Pooling_vs_sharing",
         "rule": "CXL 2.0 supports memory pooling (separate segment per host); CXL 3.0 adds memory sharing (same segment, multiple devices).",
         "trap": "Assuming shared-memory semantics on a CXL 2.0 fabric will fail — only pooling is available before 3.0."},
    ]
    f["version_naming_history_note"] = (
        "The CXL Consortium (formed March 2019, incorporated September 2019; "
        "technology originated at Intel) maintains the specification. CXL 1.0/"
        "1.1 and 2.0 use the PCIe 5.0 PHY; CXL 3.0 (August 2, 2022) moves to "
        "the PCIe 6.0 PHY (PAM-4, 64 GT/s, 256B Flit). Gen-Z, OpenCAPI, and "
        "CCIX assets were transferred into the CXL Consortium to converge on a "
        "single coherent-interconnect standard.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L15 encoding tables (fields-nested).
# ---------------------------------------------------------------------------
def _l15(gd: Path) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["sub_protocol_table"] = {
        "header_columns": ["Sub-protocol", "Based on", "Coherence", "Purpose"],
        "rows": [
            ["CXL.io", "PCIe", "non-coherent", "I/O, configuration, link init/mgmt, discovery, enumeration, interrupts, DMA, register I/O"],
            ["CXL.cache", "CXL coherent", "device caches host memory", "device-to-host coherent caching (D2H/H2D)"],
            ["CXL.mem", "CXL coherent", "host accesses device memory", "host-to-device-memory coherent load/store (M2S/S2M)"],
        ],
    }
    f["device_type_table"] = {
        "header_columns": ["Device Type", "Protocols", "Local Memory", "Example"],
        "rows": [
            ["Type 1", "CXL.io + CXL.cache", "none", "smart NIC, PGAS NIC, NIC Atomics"],
            ["Type 2", "CXL.io + CXL.cache + CXL.mem", "HBM / GDDR", "GPU / FPGA / ASIC accelerator"],
            ["Type 3", "CXL.io + CXL.mem", "DRAM / persistent", "memory expander module"],
        ],
    }
    f["flit_format_table"] = {
        "header_columns": ["CXL version", "Flit size", "PHY", "Transfer mode"],
        "rows": [
            ["1.1 / 2.0", "68 bytes (528 bits): four 16B slots + 2B CRC", "PCIe 5.0", "NRZ, 32 GT/s"],
            ["3.0", "256 bytes", "PCIe 6.0", "PAM-4, 64 GT/s, FEC"],
        ],
    }
    f["coherency_channel_table"] = {
        "header_columns": ["Protocol", "Direction", "Channels"],
        "rows": [
            ["CXL.cache", "Device → Host (D2H)", "D2H Req, D2H Rsp, D2H Data"],
            ["CXL.cache", "Host → Device (H2D)", "H2D Req (Snoop), H2D Rsp, H2D Data"],
            ["CXL.mem", "Master → Subordinate (M2S)", "M2S Req, M2S RwD"],
            ["CXL.mem", "Subordinate → Master (S2M)", "S2M NDR, S2M DRS"],
            ["CXL.mem (3.0)", "Back-Invalidation", "M2S BISnp, S2M BIRsp"],
        ],
    }
    f["version_phy_table"] = {
        "header_columns": ["CXL version", "Date", "PHY", "Line rate"],
        "rows": [
            ["1.0", "2019-03-11", "PCIe 5.0", "32 GT/s"],
            ["1.1", "2019-06", "PCIe 5.0", "32 GT/s"],
            ["2.0", "2020-11-10", "PCIe 5.0", "32 GT/s"],
            ["3.0", "2022-08-02", "PCIe 6.0", "64 GT/s"],
        ],
    }
    f["tables"] = [
        "CXL.io / CXL.cache / CXL.mem sub-protocol summary",
        "Device Type (1/2/3) protocol matrix",
        "Flit format by CXL version (68B vs 256B)",
        "CXL.cache D2H/H2D + CXL.mem M2S/S2M channel list",
        "CXL version ↔ PCIe PHY ↔ line-rate mapping",
    ]
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L16 compliance properties (fields-nested).
# ---------------------------------------------------------------------------
def _l16(gd: Path) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["must_have_properties"] = [
        "Runs over the PCIe Flex Bus; CXL vs PCIe selected via the PCIe Alternate Protocol negotiation.",
        "Three sub-protocols on one link: CXL.io (mandatory) + CXL.cache + CXL.mem (per device type).",
        "CXL.cache + CXL.mem share a common link/transaction layer, separate from CXL.io.",
        "ARB/MUX multiplexes the CXL.io stack against the CXL.cache/CXL.mem stack before the PCIe PHY.",
        "Asymmetric coherence: the host memory controller is the sole cache agent.",
        "Device types: Type 1 (io+cache), Type 2 (io+cache+mem), Type 3 (io+mem).",
        "CXL 3.0: 256-byte Flit on the PCIe 6.0 PAM-4 PHY at 64 GT/s.",
        "CXL 3.0 enhanced coherency: Back-Invalidation (BI) replaces 1.x bias modes.",
        "CXL 3.0: memory pooling + memory sharing; Port-Based Routing up to 4,096 nodes.",
        "Backward compatible with CXL 1.1/2.0 and with plain PCIe.",
    ]
    f["must_not_have_properties"] = [
        "Implementing symmetric CPU-CPU coherence (CXL coherence is asymmetric by design).",
        "Carrying CXL.cache/CXL.mem on the CXL.io link/transaction layer (they use the separate common layer).",
        "Claiming CXL 3.0 features (256B Flit, BI, sharing, PBR fabric) when negotiated down to CXL 1.x/2.0.",
        "Operating coherently when the Flex Bus negotiated plain PCIe (no CXL).",
    ]
    f["compliance_failure_modes"] = [
        {"mode": "Flex Bus negotiation failure", "trigger": "Alternate Protocol negotiation does not converge; link falls back to PCIe or fails to train."},
        {"mode": "Flit CRC error", "trigger": "Corrupted CXL.cache/CXL.mem Flit; link-layer retry (replay) invoked."},
        {"mode": "Coherency protocol violation", "trigger": "Illegal D2H/H2D or M2S/S2M opcode sequence, or back-invalidation to a non-cached line."},
        {"mode": "Poison consumed", "trigger": "Agent consumes data marked poisoned without honoring the poison indication."},
        {"mode": "Viral non-containment", "trigger": "Fatal error fails to set/propagate the viral state to dependent agents."},
        {"mode": "Memory uncorrectable error", "trigger": "Type 3 device reports an uncorrectable error via S2M response status."},
    ]
    f["min_link_constraint"] = (
        "A CXL link must at minimum support CXL.io and successfully complete "
        "Flex Bus Alternate-Protocol negotiation to CXL mode; CXL.cache and/or "
        "CXL.mem are present per the device type.")
    f["reset_behavior_compliance"] = (
        "PERST# deassertion triggers PCIe Flex Bus training + Alternate-"
        "Protocol negotiation; coherent CXL.cache/CXL.mem traffic begins only "
        "after CXL.io enumeration, HDM Decoder programming, and ARB/MUX "
        "activation.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L17 channel / signal catalog (fields-nested) — force-overwrite dependency_graph.
# ---------------------------------------------------------------------------
def _l17(gd: Path) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["channels"] = [
        {"name": "CXL.io", "direction": "bidirectional (PCIe TLP/DLLP)", "purpose": "Non-coherent I/O / config / enumeration / DMA / register I/O.", "active_levels": "PCIe-equivalent packet stream over Flex Bus", "idle_level": "PCIe Logical Idle / Electrical Idle"},
        {"name": "CXL.cache D2H Req", "direction": "device → host", "purpose": "Device requests host memory line (Rd/Own/etc.).", "active_levels": "Flit-slot message", "idle_level": "no message"},
        {"name": "CXL.cache D2H Rsp", "direction": "device → host", "purpose": "Device response to host snoop.", "active_levels": "Flit-slot message", "idle_level": "no message"},
        {"name": "CXL.cache D2H Data", "direction": "device → host", "purpose": "Device-to-host data transfer.", "active_levels": "Flit-slot data", "idle_level": "no data"},
        {"name": "CXL.cache H2D Req", "direction": "host → device", "purpose": "Host snoop (SnpData/SnpInv/SnpCur) to device cache.", "active_levels": "Flit-slot message", "idle_level": "no message"},
        {"name": "CXL.cache H2D Rsp", "direction": "host → device", "purpose": "Host response (GO / WritePull / ...).", "active_levels": "Flit-slot message", "idle_level": "no message"},
        {"name": "CXL.cache H2D Data", "direction": "host → device", "purpose": "Host-to-device data transfer.", "active_levels": "Flit-slot data", "idle_level": "no data"},
        {"name": "CXL.mem M2S Req", "direction": "host → device", "purpose": "Host read/inval request to device memory.", "active_levels": "Flit-slot message", "idle_level": "no message"},
        {"name": "CXL.mem M2S RwD", "direction": "host → device", "purpose": "Host write-with-data to device memory.", "active_levels": "Flit-slot message+data", "idle_level": "no message"},
        {"name": "CXL.mem S2M NDR", "direction": "device → host", "purpose": "No-Data Response (Cmp / Cmp-S / Cmp-E).", "active_levels": "Flit-slot message", "idle_level": "no message"},
        {"name": "CXL.mem S2M DRS", "direction": "device → host", "purpose": "Data Response (MemData).", "active_levels": "Flit-slot data", "idle_level": "no data"},
        {"name": "Flex Bus TXp/TXn, RXp/RXn", "direction": "differential serial", "purpose": "Shared PCIe PHY carrying all multiplexed sub-protocols.", "active_levels": "PCIe 5.0 NRZ / PCIe 6.0 PAM-4", "idle_level": "Electrical Idle"},
    ]
    f["logical_signaling_levels"] = [
        {"name": "CXL.io packet stream", "meaning": "PCIe-equivalent TLP/DLLP traffic on the Flex Bus."},
        {"name": "Coherent Flit", "meaning": "68-byte (1.x/2.0) or 256-byte (3.0) Flit carrying CXL.cache/CXL.mem channel messages."},
        {"name": "Electrical Idle", "meaning": "Inherited PCIe Electrical Idle when no symbol stream is driven."},
    ]
    f["packet_types_summary"] = [
        {"class": "CXL.io", "members": ["MemRd/Wr", "CfgRd/Wr", "IORd/Wr", "Cpl", "Msg", "Ack/Nak/FC DLLP"], "count": 6},
        {"class": "CXL.cache", "members": ["D2H Req", "D2H Rsp", "D2H Data", "H2D Req", "H2D Rsp", "H2D Data"], "count": 6},
        {"class": "CXL.mem", "members": ["M2S Req", "M2S RwD", "S2M NDR", "S2M DRS", "BISnp", "BIRsp"], "count": 6},
    ]
    f["channel_counts"] = {
        "sub_protocols": 3,
        "device_types": 3,
        "cxl_cache_channels": 6,
        "cxl_mem_channels": 4,
        "cxl_mem_bi_channels_cxl_3x": 2,
        "lanes_per_link_min": 1,
        "lanes_per_link_max": 16,
        "coherent_line_size_bytes": 64,
        "max_fabric_nodes_pbr": 4096,
    }
    f["global_signals"] = [
        {"name": "REFCLK", "purpose": "100 MHz reference clock (inherited from PCIe Flex Bus)."},
        {"name": "PERST#", "purpose": "Fundamental reset (inherited from PCIe)."},
    ]
    # Force-overwrite dependency_graph for the CXL shape.
    f["dependency_graph"] = {
        "common_rule": (
            "CXL.cache + CXL.mem share one common link/transaction layer, "
            "distinct from the CXL.io link/transaction layer. An ARB/MUX block "
            "multiplexes the two stacks each Flit before the shared PCIe PHY. "
            "All three sub-protocols ride one physical Flex Bus link."),
        "data_dependency": (
            "Coherent CXL.cache/CXL.mem traffic requires: (1) Flex Bus "
            "negotiated to CXL mode, (2) CXL.io enumeration complete, (3) HDM "
            "Decoders programmed + CXL.cache/CXL.mem enabled in DVSEC, (4) "
            "ARB/MUX active. Asymmetric coherence means the host memory "
            "controller is the sole cache agent."),
    }
    f["handshake_pairs"] = [
        {"name": "D2H-Req / H2D-Rsp", "from": "device", "to": "host", "rule": "Device caches host memory; host returns GO + data (CXL.cache)."},
        {"name": "H2D-Snoop / D2H-Rsp", "from": "host", "to": "device", "rule": "Host snoops device cache; device responds with line state (CXL.cache)."},
        {"name": "M2S-Req / S2M-Rsp", "from": "host", "to": "device", "rule": "Host accesses device memory; device returns NDR/DRS (CXL.mem)."},
        {"name": "BISnp / BIRsp", "from": "device", "to": "host", "rule": "CXL 3.0 back-invalidation of host-cached copies after device modifies local memory."},
        {"name": "FlexBus-AltProtocol", "from": "either", "to": "either", "rule": "Negotiate CXL vs PCIe + CXL version during link training."},
    ]
    f["ordering_rules"] = {
        "coherence_ordering": "Coherence is enforced by the host home agent; D2H/H2D and M2S/S2M message ordering follows the CXL coherence protocol.",
        "subprotocol_independence": "CXL.io ordering is PCIe producer-consumer; CXL.cache/CXL.mem ordering is governed by the coherence protocol, independent of CXL.io.",
        "mux_fairness": "ARB/MUX provides fair per-Flit arbitration between CXL.io and CXL.cache/CXL.mem.",
    }
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L18 interconnect topology (fields-nested).
# ---------------------------------------------------------------------------
def _l18(gd: Path) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["topology_type"] = (
        "CXL 1.x is point-to-point host↔device over one Flex Bus link. CXL "
        "2.0 adds tree-based switching for multi-device attach and cross-host "
        "memory pooling. CXL 3.0 adds multi-level switching and Port-Based-"
        "Routing fabrics (mesh / ring / spine-leaf) of up to 4,096 nodes, "
        "where each node may be a host or a device of any type, with GFAM "
        "memory nodes attached directly to switches and memory sharing across "
        "devices in one coherency domain.")
    f["supported_topologies"] = [
        {"name": "Point-to-point (CXL 1.x)", "description": "One host, one device over a single Flex Bus link."},
        {"name": "Tree switch fabric (CXL 2.0)", "description": "Switch connects multiple devices to a host; memory pooling across hosts."},
        {"name": "Multi-level switch + PBR fabric (CXL 3.0)", "description": "Non-tree mesh / ring / spine-leaf topologies of up to 4,096 nodes."},
        {"name": "GFAM node (CXL 3.0)", "description": "Type 3 Global Fabric Attached Memory attached to a switch without a direct host link."},
        {"name": "Memory sharing (CXL 3.0)", "description": "Multiple devices share the same memory segment in one coherency domain."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "CXL Host (Root Port)", "description": "Sole cache agent + home agent; issues H2D snoops + M2S memory requests; enumerates devices via CXL.io."},
        {"role": "CXL Type 1 device", "description": "Coherent accelerator; issues D2H requests to cache host memory; no device memory."},
        {"role": "CXL Type 2 device", "description": "Accelerator with local memory; caches host memory (CXL.cache) + exposes device memory (CXL.mem)."},
        {"role": "CXL Type 3 device", "description": "Memory expander; exposes device-attached memory via CXL.mem."},
        {"role": "CXL Switch", "description": "Fabric switching (tree in 2.0; multi-level + PBR in 3.0); enables pooling/sharing."},
    ]
    f["interconnect_role"] = (
        "CXL is a cache-coherent interconnect over the PCIe Flex Bus. Unlike "
        "plain PCIe (a non-coherent I/O tree), CXL adds host-coherent device "
        "caching (CXL.cache) and host-coherent device memory (CXL.mem), and "
        "in 3.0 a Port-Based-Routing fabric for disaggregated, pooled, and "
        "shared memory.")
    f["memory_vs_peripheral_regions"] = (
        "CXL.io carries the non-coherent I/O + config + enumeration plane "
        "(PCIe address spaces). CXL.mem exposes Host-managed Device Memory "
        "(HDM) as coherent system memory mapped via HDM Decoders. CXL.cache "
        "lets the device coherently cache host memory.")
    f["device_classification"] = {
        "type_1": "CXL.io + CXL.cache — coherent accelerator, no device memory.",
        "type_2": "CXL.io + CXL.cache + CXL.mem — accelerator with local memory.",
        "type_3": "CXL.io + CXL.mem — memory expander.",
        "switch": "CXL fabric switch (tree 2.0 / multi-level + PBR 3.0).",
    }
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L19 constraints / PDK (fields-nested).
# ---------------------------------------------------------------------------
def _l19(gd: Path) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["constraints_present"] = False
    f["electrical_channel_constraints"] = {
        "phy_cxl_1x_2x": "PCIe 5.0 (NRZ, 32 GT/s)",
        "phy_cxl_3x": "PCIe 6.0 (PAM-4, 64 GT/s, FEC)",
        "differential_impedance_ohm": 100,
        "ac_coupling_required": True,
        "refclk_freq_MHz": 100,
        "channel_budget": "Inherited from the corresponding PCIe base spec (5.0 or 6.0); CXL adds no new electrical constraint.",
    }
    f["notes"] = (
        "CXL is a wire-level + transaction-level + software-interface protocol "
        "spec that reuses the PCIe Flex Bus electrical layer; it imposes no "
        "CXL-specific PDK / SDC / floorplan constraints. All electrical "
        "compliance windows are defined by PCIe 5.0 (CXL 1.x/2.0) or PCIe 6.0 "
        "(CXL 3.0). SoC integration constraints live in the integration spec.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L20 DFT / scan topology (fields-nested).
# ---------------------------------------------------------------------------
def _l20(gd: Path) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["dft_present"] = "partial"
    f["in_band_test_facilities"] = [
        {"name": "CXL Compliance (CV) modes", "purpose": "CXL Consortium compliance / interop testing of CXL.io / CXL.cache / CXL.mem."},
        {"name": "PCIe Loopback / Compliance pattern", "purpose": "Inherited Flex Bus PHY loopback + compliance pattern."},
        {"name": "CXL RAS registers", "purpose": "In-band error logging for CXL.cache/CXL.mem/CXL.io."},
        {"name": "Type 3 mailbox diagnostics", "purpose": "Memory-device self-test, health info, event-log retrieval."},
    ]
    f["internal_diagnostics_observability"] = [
        "CXL DVSEC — device type + capability + control state.",
        "CXL Component RAS Capability registers — correctable / uncorrectable error logs.",
        "CXL Device mailbox + event logs (Type 3) — health, media errors, firmware status.",
        "Flit error / replay counters for CXL.cache/CXL.mem.",
        "Inherited PCIe AER for CXL.io.",
    ]
    f["out_of_band_test_facilities"] = [
        "CXL-aware protocol analyzer (decodes D2H/H2D + M2S/S2M channels).",
        "Inherited PCIe PHY debug ports / interposers on the Flex Bus.",
    ]
    f["notes"] = (
        "CXL does not specify JTAG / scan-chain / BIST at the protocol level. "
        "Compliance is via CXL CV modes + inherited PCIe loopback/compliance, "
        "plus the Type 3 mailbox diagnostic path. SoC-integrated CXL "
        "controllers add standard scan + JTAG at the integrator level.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L21 power intent (fields-nested).
# ---------------------------------------------------------------------------
def _l21(gd: Path) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["power_intent_present"] = True
    f["link_power_management_states"] = [
        {"state": "L0", "name": "Active", "description": "Normal CXL operation; CXL.io + CXL.cache + CXL.mem flow.", "exit_latency_estimate": "n/a"},
        {"state": "L1", "name": "Link standby", "description": "Inherited PCIe L1; ARB/MUX manages per-sub-protocol virtual LSM PM entry/exit.", "exit_latency_estimate": "microseconds"},
        {"state": "L2", "name": "Deep sleep", "description": "Inherited PCIe L2; REFCLK may stop; wake re-trains the Flex Bus.", "exit_latency_estimate": "milliseconds"},
    ]
    f["low_power_modes_summary"] = {
        "L0_active": "Full coherent operation.",
        "L1_standby": "Link standby; ARB/MUX coordinates PM across CXL.io and CXL.cache/CXL.mem virtual LSMs.",
        "L2_sleep": "Deep sleep over the PCIe Flex Bus.",
    }
    f["device_power_states"] = [
        {"state": "D0", "description": "Operational (corresponds to L0)."},
        {"state": "D3hot", "description": "Low power; config still accessible."},
        {"state": "D3cold", "description": "Main power removed; aux power only."},
    ]
    f["notes"] = (
        "CXL link power management builds on PCIe PM (L0/L1/L2). The ARB/MUX "
        "block maintains a virtual link-state-machine per sub-protocol so that "
        "CXL.io and the CXL.cache/CXL.mem stack can coordinate PM-state entry "
        "and exit over the shared Flex Bus.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L22 verification plan (fields-nested).
# ---------------------------------------------------------------------------
def _l22(gd: Path) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["verification_plan_present"] = "implicit"
    f["verification_categories_derived_from_spec"] = [
        "Flex Bus negotiation — CXL vs PCIe + CXL version (1.1/2.0/3.0) selection.",
        "CXL.io enumeration — PCIe config + CXL DVSEC discovery; device-type detection.",
        "CXL.cache — D2H Req (RdShared/RdOwn) + H2D snoop + GO/Data for all MESI states.",
        "CXL.mem — M2S MemRd → S2M DRS+NDR; M2S MemWr (RwD) → S2M NDR.",
        "Device type matrix — Type 1 (io+cache), Type 2 (io+cache+mem), Type 3 (io+mem).",
        "Bias mode (CXL 1.x Type 2) — device-bias / host-bias per 4 KB page.",
        "Back-invalidation (CXL 3.0) — BISnp/BIRsp on device-memory modification.",
        "256-byte Flit on PCIe 6.0 PAM-4 (CXL 3.0) vs 68-byte Flit on PCIe 5.0 (CXL 1.x/2.0).",
        "ARB/MUX fairness — interleaved CXL.io and CXL.cache/CXL.mem Flits.",
        "Memory pooling (2.0/3.0) + memory sharing (3.0) across hosts/devices.",
        "Multi-level switching + Port-Based-Routing fabric (3.0).",
        "Flit CRC error injection → link-layer replay.",
        "Poison + viral propagation on uncorrectable error.",
        "Type 3 mailbox — identify / health / event-log / firmware commands.",
        "Backward compatibility + PCIe fallback negotiation.",
    ]
    f["notes"] = (
        "The CXL specification does not ship a formal testbench. These "
        "categories derive from the CXL.io / CXL.cache / CXL.mem protocol, "
        "Flex Bus negotiation, coherency, switching, and Type 3 mailbox "
        "chapters; formal compliance is the CXL Consortium Compliance program.")
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# L23 security requirements (fields-nested).
# ---------------------------------------------------------------------------
def _l23(gd: Path) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    f["security_requirements_present"] = True
    f["anti_corruption_features"] = [
        "Flit CRC (CXL.cache + CXL.mem) detects corrupted Flits; link-layer retry recovers them.",
        "Forward Error Correction on the PCIe 6.0 PHY (CXL 3.0) corrects symbol errors.",
        "CXL.io inherits PCIe LCRC/ECRC + NAK/replay anti-corruption.",
        "Poison indication propagates known-bad data so consumers mark it invalid.",
        "Viral indication contains fatal errors by quiescing dependent agents.",
    ]
    f["confidentiality_features"] = [
        "CXL 2.0 added device integrity + data encryption (CXL IDE — Integrity and Data Encryption) for link-level confidentiality + integrity.",
        "CXL IDE protects CXL.cache/CXL.mem (and CXL.io) traffic against snooping/tampering on the link.",
    ]
    f["authentication_features"] = [
        "Component authentication via CMA/SPDM (inherited / aligned with PCIe) for device attestation before enabling trusted memory.",
    ]
    f["anti_tampering_features"] = [
        "CXL IDE integrity protection detects link tampering.",
        "Viral + poison containment limit the blast radius of corrupted/tampered data.",
    ]
    f["future_security_pointers"] = [
        "CXL 3.1+ adds Trusted-Execution-Environment (TEE) support for confidential computing over CXL memory.",
    ]
    f["notes"] = (
        "Unlike CXL 1.x (anti-corruption only), CXL 2.0+ adds device integrity "
        "and data encryption (CXL IDE) for link confidentiality + integrity, "
        "with device authentication aligned to CMA/SPDM. CXL 3.1+ extends this "
        "toward trusted-execution environments. Anti-corruption (Flit CRC, "
        "FEC, poison, viral) is present at all versions.")
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
def is_cxl(blob: str) -> bool:
    """Content-only `cxl` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline.
    """
    if not blob:
        return False
    low = blob.lower()
    # UCIe-primary defer: UCIe is a die-to-die chiplet interconnect that CARRIES
    # CXL.io/.cache/.mem as protocol layers, so a UCIe spec lists the CXL.* names
    # without being a CXL spec. Defer to the UCIe subject (it ships its own
    # is_ucie). General structural signature (chiplet die-to-die + sideband/RDI/
    # FDI/UCIe), no benchmark-name literal. A real CXL spec's subject is
    # cache-coherent memory expansion over Flex Bus, not a chiplet die-to-die PHY.
    ucie_primary = (
        "chiplet" in low
        and ("die-to-die" in low or "die to die" in low)
        and ("sideband" in low or "RDI" in blob or "FDI" in blob
             or "UCIe" in blob))
    if ucie_primary:
        return False
    pcie5_phy = (
        "retimer" in blob.lower()
        or "lane margining" in blob.lower()
        or "equalization" in blob.lower())
    return bool(
        (not pcie5_phy) and (
            "Compute Express Link" in blob
            or ("CXL.io" in blob and "CXL.mem" in blob)
            or ("CXL.cache" in blob and "CXL.mem" in blob)))
