"""Tests for the Interlaken protocol synth + the generic auto-dispatch contract.

Interlaken is a drop-in protocol added via the v0.2.13 generic auto-dispatch.
These tests pin the auto-dispatch contract, the detector (no cross-fire on the
Ethernet / AXI-Stream siblings), and the canonical content application.
"""
import importlib
import json

mod = importlib.import_module("interlaken_protocol_synth")


class TestAutoDispatchContract:
    def test_opts_in(self):
        assert getattr(mod, "AUTO_DISPATCH", False) is True

    def test_exposes_detector_and_applier(self):
        assert callable(getattr(mod, "is_interlaken", None))
        assert callable(getattr(mod, "apply_interlaken_synth", None))

    def test_exposes_ic_name(self):
        assert isinstance(getattr(mod, "IC_NAME", None), str)
        assert "Interlaken" in mod.IC_NAME


class TestIsInterlakenDetector:
    ILKN = ("Interlaken Protocol Definition. A channelized chip-to-chip packet "
            "interface over multiple bonded SerDes lanes using 64B/67B word "
            "encoding (bit 64 control/data, bit 65 scrambled, bit 66 inversion). "
            "Bursts are delimited by a Burst Control Word (SOP, channel number, "
            "flow-control calendar, CRC-24) and an Idle Control Word (EOP, "
            "EOP_Format). The metaframe inserts a Synchronization word (sync "
            "word 0x78f6), a Scrambler State word, a Skip word, and a "
            "Diagnostic word every MetaFrameLength words. In-band flow control "
            "via XON/XOFF calendar. CRC-32 per diagnostic word.")

    def test_fires_on_interlaken(self):
        assert mod.is_interlaken(self.ILKN) is True

    def test_empty_blob_false(self):
        assert mod.is_interlaken("") is False
        assert mod.is_interlaken(None) is False

    def test_requires_name_token(self):
        no_token = self.ILKN.replace("Interlaken Protocol Definition", "A protocol")
        no_token = no_token.replace("Interlaken", "it")
        assert mod.is_interlaken(no_token) is False

    def test_defers_on_ethernet(self):
        eth = ("IEEE 802.3 Ethernet MAC. Frame = preamble + SFD + 48-bit "
               "destination/source MAC addresses + length/type + payload + FCS "
               "(CRC-32). CSMA/CD media access control. 64B/66B PCS on the PHY. "
               "No metaframe, no Burst/Idle control words, no 64B/67B.")
        assert mod.is_interlaken(eth) is False

    def test_defers_on_axi_stream(self):
        axis = ("AXI4-Stream: TVALID, TREADY, TDATA, TLAST, TKEEP, TUSER "
                "handshake for streaming data between IP blocks. No SerDes, no "
                "64B/67B, no metaframe, no bursts with CRC-24.")
        assert mod.is_interlaken(axis) is False


class TestApplyInterlakenSynth:
    def _docs(self, tmp_path):
        gd = tmp_path / "generated_docs"
        gd.mkdir()
        (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(
            {"ic_name": "UNKNOWN", "schema_version": 2}))
        (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps(
            {"fields": {"channels": []}, "schema_version": "x"}))
        return gd

    def test_noop_when_flag_false(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_interlaken_synth(gd, False, None)
        l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())
        assert l8["ic_name"] == "UNKNOWN"

    def test_applies_canonical_content(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_interlaken_synth(gd, True, None)
        l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())
        kc = l8.get("key_constants") or l8.get("width_parameters") or {}
        assert kc.get("WORD_PAYLOAD_BITS") == 64
        assert kc.get("WORD_WIRE_BITS") == 67
        assert l8["ic_name"] == mod.IC_NAME
        assert l8["schema_version"] == 2

    def test_preserves_fields_metadata(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_interlaken_synth(gd, True, None)
        l17 = json.loads((gd / "L17_CHANNEL_SIGNAL_CATALOG.json").read_text())
        assert l17["schema_version"] == "x"
