"""Real AMBA AXI spec -> all of L14-L18 via the wired assess_spec structures.

v1.2.31 wired phase1_protocol_spec_extract into cvdp_complete_extract._structures,
but only L16 (compliance) had been exercised — on a SPI-level doc. This pins the
FULL L14-L18 path on a faithful ARM AMBA AXI spec excerpt (the real PDF-extracted
text layout the extractors target: space-separated channel-signal rows, "Table
A?-? <name>" encoding headers, a version-history table, "must/shall" compliance
sentences, and an A9 default-value table):

  L14 protocol_versioning  — Change-history rows (date / issue / Non-Confidential)
                             + a deprecated WID signal
  L15 encoding_tables      — Table A3-2 AWBURST / A3-4 RRESP 0b.. encodings
  L16 compliance           — "The master must not …" / "… shall keep ARVALID …"
  L17 channel_catalog      — AWVALID/ARREADY/RDATA … Master|Slave channel signals
  L18 interconnect         — A9 default-value rows (AWID Output Optional All zeros)

These exercise the bus_interconnect_protocol path that an AMBA/USB/PCIe spec drives;
an ordinary block leaves every facet empty (pinned in test_v1_2_31).
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import phase1_protocol_spec_extract as P   # noqa: E402
import spec_complete_extract as SCE        # noqa: E402

# A faithful AMBA AXI spec excerpt in the real ARM text layout (NOT markdown).
_AMBA = """AMBA AXI and ACE Protocol Specification

Date Issue Confidentiality Change
19 March 2004 A Non-Confidential First release
19 March 2010 C Non-Confidential First release of AXI4 and ACE
22 February 2013 E Non-Confidential Second release of ACE

The WID signal is deprecated. Write data interleaving is no longer supported in AXI4.

Table A2-2 Write address channel signals
AWADDR Master Write address.
AWLEN Master Burst length.
AWSIZE Master Burst size.
AWVALID Master Write address valid.
AWREADY Slave Write address ready.

Table A2-3 Read address channel signals
ARADDR Master Read address.
ARVALID Master Read address valid.
ARREADY Slave Read address ready.

Table A2-4 Read data channel signals
RVALID Slave Read valid.
RREADY Master Read ready.

ACLK Global Global clock signal.
ARESETn Global Global reset signal, active LOW.

Table A3-2 AWBURST encoding
0b00 FIXED
0b01 INCR
0b10 WRAP
0b11 Reserved

Table A3-4 RRESP encoding
0b00 OKAY
0b10 SLVERR
0b11 DECERR

The master must not wait for AWREADY to be asserted before asserting AWVALID.
A slave must wait for both AWVALID and WVALID to be asserted before asserting AWREADY.
The master shall keep ARVALID asserted until the rising clock edge after ARREADY is asserted.

A9.3 Default signal values
AWID Output Optional All zeros
AWADDR Output Required -
AWLEN Output Optional All zeros, Length 1
ARREGION defaults to 0b0000 when the interconnect does not support regions.
"""


# ── each extractor fires on the AMBA spec ──
def test_l14_versioning_extracts_history_and_deprecation():
    r = P.extract_l14_versioning(_AMBA)
    assert r["extraction_status"] == "EXTRACTED"
    assert len(r["fields"]["versions"]) == 3
    # the deprecated FEATURE NAME is captured (v1.2.33: skips the generic noun)
    deps = r["fields"]["deprecated_features"]
    assert any(d["feature"] == "WID" for d in deps)


def test_l15_encoding_tables_extracted():
    r = P.extract_l15_encoding_tables(_AMBA)
    assert r["extraction_status"] == "EXTRACTED"
    ids = {t["table_id"] for t in r["fields"]["tables"]}
    assert {"Table A3-2", "Table A3-4"} <= ids


def test_l16_compliance_extracted():
    r = P.extract_l16_compliance(_AMBA)
    assert r["extraction_status"] == "EXTRACTED"
    assert len(r["evidence"]) >= 3


def test_l17_channel_catalog_extracted():
    r = P.extract_l17_channels(_AMBA)
    assert r["extraction_status"] == "EXTRACTED"
    names = {e["signal"] for e in r["evidence"]}
    assert {"AWVALID", "AWREADY", "ARVALID", "RVALID"} <= names


def test_l18_interconnect_defaults_extracted():
    r = P.extract_l18_interconnect(_AMBA)
    assert r["extraction_status"] == "EXTRACTED"
    assert len(r["evidence"]) >= 3


# ── the wired general engine surfaces ALL five facets ──
def test_assess_spec_surfaces_all_protocol_facets():
    st = SCE.assess_spec(_AMBA, [], [], module_name="axi")["structures"]
    assert len(st["protocol_versioning"]) == 3
    assert len(st["encoding_tables"]) >= 2
    assert len(st["compliance"]) >= 3
    assert len(st["channel_catalog"]) >= 6
    assert len(st["interconnect"]) >= 3


def test_protocol_facets_empty_on_non_protocol_doc():
    st = SCE.assess_spec("Design `add8`: input [7:0] a, b; output [8:0] y; y = a + b.",
                         [], [], module_name="add8")["structures"]
    for k in ("protocol_versioning", "encoding_tables", "compliance",
              "channel_catalog", "interconnect"):
        assert st[k] == []
