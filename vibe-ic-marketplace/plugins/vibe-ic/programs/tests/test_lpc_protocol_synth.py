"""Tests for the LPC protocol synth + the generic auto-dispatch contract.

LPC (Intel Low Pin Count Interface Specification 1.1) is added via the
v0.2.13 generic drop-in auto-dispatch (AUTO_DISPATCH=True + is_<base> +
apply_<base>_synth + IC_NAME), so these tests pin both the detector (no
cross-fire on eSPI / SPI / QSPI siblings; LPC is the PARALLEL predecessor that
eSPI replaces, so an eSPI spec naming "low pin count" must NOT fire is_lpc)
and the module-level auto-dispatch contract every drop-in must satisfy.
"""
import importlib
import json

mod = importlib.import_module("lpc_protocol_synth")


class TestAutoDispatchContract:
    def test_opts_in(self):
        assert getattr(mod, "AUTO_DISPATCH", False) is True

    def test_exposes_detector_and_applier(self):
        assert callable(getattr(mod, "is_lpc", None))
        assert callable(getattr(mod, "apply_lpc_synth", None))

    def test_exposes_ic_name(self):
        assert isinstance(getattr(mod, "IC_NAME", None), str)
        assert "LPC" in mod.IC_NAME or "Low Pin Count" in mod.IC_NAME


class TestIsLpcDetector:
    LPC = ("Low Pin Count (LPC) Interface Specification. LAD[3:0] multiplexed "
           "address/data bus, LFRAME# frame/abort, LCLK is the 33 MHz PCI clock, "
           "LRESET#. Each cycle: START field while LFRAME# low, then CYCTYPE+DIR "
           "(cycle type I/O read/write, Memory read/write, DMA read/write, "
           "direction), ADDR nibbles, TAR turnaround, SYNC field (0000 ready, "
           "0101 short wait, 0110 long wait, 1010 error), DATA nibbles. Firmware "
           "Memory cycles use a 28-bit address and IDSEL.")

    def test_fires_on_lpc(self):
        assert mod.is_lpc(self.LPC) is True

    def test_empty_blob_false(self):
        assert mod.is_lpc("") is False
        assert mod.is_lpc(None) is False

    def test_defers_on_espi(self):
        # An eSPI spec NAMES "low pin count"/"LPC" as the predecessor it
        # replaces — the eSPI four-channel + negotiation signature must win.
        espi = ("Enhanced Serial Peripheral Interface eSPI replaces the Low Pin "
                "Count (LPC) bus. Four logical channels: Peripheral Channel, "
                "Virtual Wire, OOB (Out-Of-Band), Flash Access. GET_CONFIGURATION "
                "/ SET_CONFIGURATION negotiate frequency. ESPI_ALERT# signals "
                "service. Each transaction has a turnaround (TAR) before the "
                "response. Cycle type I/O, Memory, DMA, firmware. START / SYNC.")
        assert mod.is_lpc(espi) is False

    def test_defers_on_classic_spi(self):
        spi = ("SPI serial peripheral interface with SCK, MOSI, MISO and CS. "
               "CPOL and CPHA select the clock mode. Full-duplex shift register.")
        assert mod.is_lpc(spi) is False

    def test_defers_on_qspi_flash(self):
        qspi = ("Quad SPI / Octal SPI NOR flash. Instruction phase, address "
                "phase, dummy cycles, data phase over IO0..IO7. Read opcode 0x03, "
                "fast read 0xEB. Single/Dual/Quad/Octal IO lanes. DQS strobe.")
        assert mod.is_lpc(qspi) is False

    def test_name_token_necessary(self):
        # A blob with the structural quorum but NO LPC name token must defer.
        no_name = ("Some bus with LAD signals and a frame signal and a clock and "
                   "I/O memory dma firmware cycles and start sync fields.")
        # No "low pin count" and no standalone 'lpc' token, no LAD[3:0]/LFRAME#.
        assert mod.is_lpc(no_name) is False


class TestApplyLpcSynth:
    def _docs(self, tmp_path):
        gd = tmp_path / "generated_docs"
        gd.mkdir()
        (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(
            {"ic_name": "UNKNOWN", "schema_version": 2}))
        (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps(
            {"fields": {"channels": []}, "schema_version": "x"}))
        return gd

    def test_noop_when_flag_false(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_lpc_synth(gd, False, None)
        l3 = json.loads((gd / "L3_CMD_PROTOCOL.json").read_text())
        assert l3["ic_name"] == "UNKNOWN"  # untouched
        assert "start_field_encodings" not in l3

    def test_applies_canonical_content(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_lpc_synth(gd, True, None)
        l3 = json.loads((gd / "L3_CMD_PROTOCOL.json").read_text())
        starts = {o["name"] for o in l3["start_field_encodings"]}
        assert {"TARGET", "FW_READ", "STOP_ABORT"} <= starts
        syncs = {o["name"] for o in l3["sync_field_encodings"]}
        assert {"READY", "ERROR", "LONG_WAIT"} <= syncs
        assert l3["ic_name"] == mod.IC_NAME
        # metadata preserved (merge, not overwrite)
        assert l3["schema_version"] == 2
        l17 = json.loads((gd / "L17_CHANNEL_SIGNAL_CATALOG.json").read_text())
        assert l17["fields"]["signal_counts"]["lad_width"] == 4

    def test_preserves_fields_metadata(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_lpc_synth(gd, True, None)
        l17 = json.loads((gd / "L17_CHANNEL_SIGNAL_CATALOG.json").read_text())
        assert l17["schema_version"] == "x"
