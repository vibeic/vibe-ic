"""Protocol-extractor generality: two AXI-specific quirks fixed + USB/PCIe reach.

Running USB 2.0 and PCIe specs through phase1_protocol_spec_extract confirmed the
L14/L15/L17/L18 extractors were tuned to ARM's exact AMBA text layout, so only
L16 (shall/must compliance) was general. This widens the safe-to-generalize parts
and fixes two AXI-only quirks the AMBA test had to document:

  (a) L17 `_L17_SIG_RE` required a >=11-char semantics field, dropping a short
      legitimate row ("RDATA Slave Read data."). Lowered to >=4.
  (a) L14 deprecation captured the generic noun before the verb ("WID signal is
      deprecated" -> "signal"); now skips an optional noun + the is/are/was/were
      auxiliary so the real NAME (WID / PID) is captured, across "deprecated",
      "no longer supported", "removed in", "obsolete".
  (b) L15 encoding-table header accepted only `Table A2-3` (ARM section letter);
      now also `Table 8-1` / `Table 2-3` (USB / PCIe numeric ids), still gated on
      an encoding-shape body row or encoding-keyword title (no generic table leak).

HONEST SCOPE: L17 channel signals (AXI AW/AR/R/W/B) and the L14 version-history
ROW format / L18 default-value tables remain AMBA-AXI-specific — a USB/PCIe spec
exercises L15 (encoding) + L16 (compliance) + L14 deprecation, not the AXI-channel
catalog. That is faithfully asserted below rather than over-claimed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import phase1_protocol_spec_extract as P  # noqa: E402


# ── (a) L17 short-semantics quirk ──
def test_l17_short_semantics_signal_now_matches():
    for line, sig in [("RDATA Slave Read data.", "RDATA"),
                      ("RID Slave Read data ID.", "RID"),
                      ("AWVALID Master Write address valid.", "AWVALID")]:
        m = P._L17_SIG_RE.match(line)
        assert m and m.group("sig") == sig, line


def test_l17_still_rejects_too_short_semantics():
    assert P._L17_SIG_RE.match("RID Slave Hi") is None


# ── (a) L14 deprecation name capture across verb forms ──
def test_l14_deprecation_captures_name_not_noun():
    cases = {
        "The WID signal is deprecated.": "WID",
        "The PRE PID is no longer supported in USB 3.0.": "PID",
        "AWUSER was removed in issue F.": "AWUSER",
        "Feature X is obsolete.": "X",
    }
    for text, name in cases.items():
        deps = P.extract_l14_versioning(text)["fields"]["deprecated_features"]
        assert any(d["feature"] == name for d in deps), (text, deps)


# ── (b) L15 numeric table ids (USB / PCIe) ──
def test_l15_numeric_table_id_usb_pcie():
    usb = ("Table 8-1 PID Types\n0b0001 OUT\n0b1001 IN\n0b1101 SETUP\n")
    pcie = ("Table 2-3 TLP Type Encodings\n0b00000 MRd\n0b00001 MRdLk\n")
    for doc, tid in [(usb, "Table 8-1"), (pcie, "Table 2-3")]:
        r = P.extract_l15_encoding_tables(doc)
        assert r["extraction_status"] == "EXTRACTED"
        assert tid in {t["table_id"] for t in r["fields"]["tables"]}


def test_l15_arm_letter_table_still_works():
    amba = "Table A3-2 AWBURST encoding\n0b00 FIXED\n0b01 INCR\n"
    r = P.extract_l15_encoding_tables(amba)
    assert "Table A3-2" in {t["table_id"] for t in r["fields"]["tables"]}


def test_l15_numeric_non_encoding_table_not_promoted():
    # §4.05: a numeric table with NO encoding rows + a non-encoding title stays out
    plain = "Table 1-1 Document structure\nChapter 1 Introduction\nChapter 2 Scope\n"
    assert P.extract_l15_encoding_tables(plain)["extraction_status"] == \
        "EXTRACTION_FOUND_NOTHING"


# ── (b) USB / PCIe reach the GENERAL facets (compliance + encoding), honestly ──
_USB = (
    "Universal Serial Bus Specification Revision 2.0\n"
    "The PRE PID is no longer supported in USB 3.0.\n"
    "Table 8-1 PID Types\n0b0001 OUT\n0b1001 IN\n0b1101 SETUP\n"
    "A device must respond to a SETUP packet within the bus turnaround time.\n"
    "A function shall return a STALL handshake when an endpoint is halted.\n")
_PCIE = (
    "PCI Express Base Specification Revision 5.0\n"
    "Table 2-3 TLP Type Encodings\n0b00000 MRd\n0b00001 MRdLk\n"
    "A Requester must not issue a Memory Read that crosses a 4 KB boundary.\n")


def test_usb_general_facets():
    assert P.extract_l15_encoding_tables(_USB)["extraction_status"] == "EXTRACTED"
    assert len(P.extract_l16_compliance(_USB)["evidence"]) >= 2
    deps = P.extract_l14_versioning(_USB)["fields"]["deprecated_features"]
    assert any(d["feature"] == "PID" for d in deps)
    # HONEST: USB has no AXI channel catalog
    assert P.extract_l17_channels(_USB)["extraction_status"] == "EXTRACTION_FOUND_NOTHING"


def test_pcie_general_facets():
    assert P.extract_l15_encoding_tables(_PCIE)["extraction_status"] == "EXTRACTED"
    assert len(P.extract_l16_compliance(_PCIE)["evidence"]) >= 1
    assert P.extract_l17_channels(_PCIE)["extraction_status"] == "EXTRACTION_FOUND_NOTHING"
