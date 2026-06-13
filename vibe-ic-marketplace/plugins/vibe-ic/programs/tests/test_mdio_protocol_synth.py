"""Tests for the MDIO protocol synth + the generic auto-dispatch contract.

MDIO (IEEE 802.3 Clause 22 + Clause 45) is added via the v0.2.13 generic
drop-in auto-dispatch (AUTO_DISPATCH=True + is_<base> + apply_<base>_synth +
IC_NAME), so these tests pin both the detector (no cross-fire on I2C/SPI/JTAG
siblings) and the module-level auto-dispatch contract every drop-in satisfies.
"""
import importlib
import json

mod = importlib.import_module("mdio_protocol_synth")


class TestAutoDispatchContract:
    def test_opts_in(self):
        assert getattr(mod, "AUTO_DISPATCH", False) is True

    def test_exposes_detector_and_applier(self):
        assert callable(getattr(mod, "is_mdio", None))
        assert callable(getattr(mod, "apply_mdio_synth", None))

    def test_exposes_ic_name(self):
        assert isinstance(getattr(mod, "IC_NAME", None), str)
        assert "MDIO" in mod.IC_NAME or "Management Data" in mod.IC_NAME


class TestIsMdioDetector:
    MDIO = ("IEEE 802.3 Management Data Input/Output (MDIO) interface. Two "
            "wires: MDC (management clock driven by the STA, up to 2.5 MHz) and "
            "MDIO (bidirectional open-drain data with a pull-up). Clause 22 "
            "frame after a 32-bit preamble: ST + OP + PHYAD + REGAD + TA + "
            "16-bit DATA. ST=01, OP=10 read / 01 write. Clause 45 uses ST=00 "
            "with PRTAD, DEVAD and indirect addressing (read-and-increment).")

    def test_fires_on_mdio(self):
        assert mod.is_mdio(self.MDIO) is True

    def test_empty_blob_false(self):
        assert mod.is_mdio("") is False
        assert mod.is_mdio(None) is False

    def test_defers_on_i2c(self):
        # I2C: 2-wire SDA/SCL with START/STOP + 7-bit slave address + ACK,
        # no MDC/MDIO pair and no MDIO frame-field model.
        i2c = ("I2C-bus specification: a two-wire bus with a serial data line "
               "SDA and a serial clock line SCL. A master issues a START "
               "condition, sends a 7-bit slave address, the addressed slave "
               "drives an acknowledge (ACK), then bytes are transferred, ended "
               "by a STOP condition.")
        assert mod.is_mdio(i2c) is False

    def test_defers_on_spi(self):
        spi = ("SPI serial peripheral interface with SCK, MOSI, MISO and CS. "
               "CPOL and CPHA select the clock mode. Full-duplex shift "
               "register. No turnaround and no in-frame address.")
        assert mod.is_mdio(spi) is False

    def test_defers_on_jtag(self):
        jtag = ("JTAG IEEE 1149.1 boundary scan. Test Access Port (TAP) with "
                "TCK, TMS, TDI, TDO and optional TRST. A 16-state TAP "
                "controller state machine, an instruction register, and "
                "boundary-scan cells.")
        assert mod.is_mdio(jtag) is False

    def test_requires_name_token(self):
        # MDC + frame-field words but no MDIO name token => defer.
        nameless = ("A two-wire clock-and-data link with a preamble, a "
                    "register address and a turnaround. mdc only.")
        # 'mdc' alone is not the MDIO name token without 'mdio'.
        assert mod.is_mdio(nameless) is False

    def test_subject_dominance_defers_on_ethernet_with_buried_mdio(self):
        # v0.2.13 regression (the adversarial-review + matrix catch): MDIO is a
        # genuine IEEE 802.3 sub-clause (22.2.2.11/.12), so the FULL Ethernet
        # spec contains MDC+MDIO + all the frame fields — but it is ABOUT the
        # Ethernet MAC/PHY, not MDIO. The detector must DEFER when the MDIO
        # content is a buried minority clause (name token NOT in the head),
        # else a re-run of the ethernet benchmark would auto-dispatch
        # apply_mdio_synth and clobber its gold-scored docs.
        eth = ("IEEE 802.3 Ethernet. " + ("Carrier Sense Multiple Access with "
               "Collision Detection (CSMA/CD) Media Access Control sublayer. "
               "MAC frame: preamble, SFD, 48-bit destination and source "
               "addresses, length/type, payload, FCS (CRC-32). 1000BASE-T, "
               "100BASE-TX physical layers. ") * 40
               + " Clause 22 management: MDC clock and MDIO data line, "
                 "ST OP PHYAD REGAD TA preamble, register address. management "
                 "data input/output.")
        assert "mdio" in eth.lower()              # token present (buried)
        assert "mdio" not in eth[:3500].lower()   # but not in the head
        assert mod.is_mdio(eth) is False          # subject-dominance defers


class TestApplyMdioSynth:
    def _docs(self, tmp_path):
        gd = tmp_path / "generated_docs"
        gd.mkdir()
        (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(
            {"ic_name": "UNKNOWN", "opcodes": [], "schema_version": 2}))
        (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps(
            {"fields": {"channels": []}, "schema_version": "x"}))
        return gd

    def test_noop_when_flag_false(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_mdio_synth(gd, False, None)
        l3 = json.loads((gd / "L3_CMD_PROTOCOL.json").read_text())
        assert l3["opcodes"] == []  # untouched

    def test_applies_canonical_content(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_mdio_synth(gd, True, None)
        l3 = json.loads((gd / "L3_CMD_PROTOCOL.json").read_text())
        names = {o["name"] for o in l3["opcodes"]}
        assert {"READ", "WRITE", "ADDRESS", "READ_INC"} <= names
        assert l3["start_of_frame"]["clause22"] == "01"
        assert l3["start_of_frame"]["clause45"] == "00"
        assert l3["ic_name"] == mod.IC_NAME
        # metadata preserved (merge, not overwrite)
        assert l3["schema_version"] == 2
        l17 = json.loads((gd / "L17_CHANNEL_SIGNAL_CATALOG.json").read_text())
        assert l17["fields"]["channel_counts"]["physical_signals"] == 2

    def test_preserves_fields_metadata(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_mdio_synth(gd, True, None)
        l17 = json.loads((gd / "L17_CHANNEL_SIGNAL_CATALOG.json").read_text())
        assert l17["schema_version"] == "x"
