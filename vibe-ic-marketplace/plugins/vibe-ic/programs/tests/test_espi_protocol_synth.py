"""Tests for the eSPI protocol synth + the generic auto-dispatch contract.

eSPI is the first NEW protocol added via the v0.2.13 generic drop-in
auto-dispatch (AUTO_DISPATCH=True + is_<base> + apply_<base>_synth + IC_NAME),
so these tests pin both the detector (no cross-fire on SPI/QSPI/LPC siblings)
and the module-level auto-dispatch contract every drop-in must satisfy.
"""
import importlib
import json

mod = importlib.import_module("espi_protocol_synth")


class TestAutoDispatchContract:
    def test_opts_in(self):
        assert getattr(mod, "AUTO_DISPATCH", False) is True

    def test_exposes_detector_and_applier(self):
        assert callable(getattr(mod, "is_espi", None))
        assert callable(getattr(mod, "apply_espi_synth", None))

    def test_exposes_ic_name(self):
        assert isinstance(getattr(mod, "IC_NAME", None), str)
        assert "eSPI" in mod.IC_NAME or "Enhanced Serial Peripheral" in mod.IC_NAME


class TestIsEspiDetector:
    ESPI = ("Enhanced Serial Peripheral Interface eSPI replaces the Low Pin "
            "Count (LPC) bus. Four logical channels: Peripheral, Virtual Wire, "
            "OOB (Out-Of-Band), Flash Access. GET_CONFIGURATION / "
            "SET_CONFIGURATION negotiate frequency. ESPI_ALERT# signals service. "
            "Each transaction has a turnaround (TAR) before the response.")

    def test_fires_on_espi(self):
        assert mod.is_espi(self.ESPI) is True

    def test_empty_blob_false(self):
        assert mod.is_espi("") is False
        assert mod.is_espi(None) is False

    def test_defers_on_classic_spi(self):
        spi = ("SPI serial peripheral interface with SCK, MOSI, MISO and CS. "
               "CPOL and CPHA select the clock mode. Full-duplex shift register.")
        assert mod.is_espi(spi) is False

    def test_defers_on_qspi_flash(self):
        qspi = ("Quad SPI NOR flash. Read opcode 0x03, fast read 0xEB with "
                "dummy cycles. Single/Dual/Quad IO lanes. Page program 0x02.")
        assert mod.is_espi(qspi) is False

    def test_defers_on_lpc(self):
        lpc = ("Low Pin Count (LPC) Interface: LAD[3:0] multiplexed address/data, "
               "LFRAME# frame start, 33 MHz LCLK. I/O, memory, DMA, firmware cycles.")
        # LPC mentions 'low pin count' but lacks the eSPI four-channel signature.
        assert mod.is_espi(lpc) is False


class TestApplyEspiSynth:
    def _docs(self, tmp_path):
        gd = tmp_path / "generated_docs"
        gd.mkdir()
        # Minimal generic-runner-shaped docs for a couple of L docs.
        (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(
            {"ic_name": "UNKNOWN", "opcodes": [], "schema_version": 2}))
        (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps(
            {"fields": {"channels": []}, "schema_version": "x"}))
        return gd

    def test_noop_when_flag_false(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_espi_synth(gd, False, None)
        l3 = json.loads((gd / "L3_CMD_PROTOCOL.json").read_text())
        assert l3["opcodes"] == []  # untouched

    def test_applies_canonical_content(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_espi_synth(gd, True, None)
        l3 = json.loads((gd / "L3_CMD_PROTOCOL.json").read_text())
        names = {o["name"] for o in l3["opcodes"]}
        assert {"PUT_VWIRE", "GET_STATUS", "GET_CONFIGURATION"} <= names
        assert l3["ic_name"] == mod.IC_NAME
        # metadata preserved (merge, not overwrite)
        assert l3["schema_version"] == 2
        l17 = json.loads((gd / "L17_CHANNEL_SIGNAL_CATALOG.json").read_text())
        assert l17["fields"]["channel_counts"]["logical_channels"] == 4

    def test_preserves_fields_metadata(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_espi_synth(gd, True, None)
        l17 = json.loads((gd / "L17_CHANNEL_SIGNAL_CATALOG.json").read_text())
        assert l17["schema_version"] == "x"
