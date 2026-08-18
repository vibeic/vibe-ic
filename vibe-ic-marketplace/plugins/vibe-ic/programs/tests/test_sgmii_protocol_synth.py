"""Tests for the SGMII protocol synth + the generic auto-dispatch contract.

SGMII (Serial Gigabit Media Independent Interface, Cisco ENG-46158) is added via
the v0.2.13 generic drop-in auto-dispatch (AUTO_DISPATCH=True + is_<base> +
apply_<base>_synth + IC_NAME). These tests pin both the detector (NAME-TOKEN
gated, no cross-fire on the Ethernet-MAC / RGMII siblings) and the module-level
auto-dispatch contract every drop-in must satisfy.
"""
import importlib
import json

mod = importlib.import_module("sgmii_protocol_synth")


class TestAutoDispatchContract:
    def test_opts_in(self):
        assert getattr(mod, "AUTO_DISPATCH", False) is True

    def test_exposes_detector_and_applier(self):
        assert callable(getattr(mod, "is_sgmii", None))
        assert callable(getattr(mod, "apply_sgmii_synth", None))

    def test_exposes_ic_name(self):
        assert isinstance(getattr(mod, "IC_NAME", None), str)
        assert ("SGMII" in mod.IC_NAME
                or "Serial Gigabit Media Independent" in mod.IC_NAME)


class TestIsSgmiiDetector:
    SGMII = ("Serial-GMII (SGMII) carries GMII between an Ethernet MAC and PHY "
             "over a single differential pair per direction, serialized at "
             "1.25 GBd. The line code is 8B/10B with running disparity and a "
             "/K28.5/ comma for alignment. Auto-Negotiation reuses the "
             "1000BASE-X Clause 37 PCS with a redefined 16-bit Config_Reg: "
             "Link Speed in bits 11:10 (00=10 Mbps, 10=1000 Mbps), Duplex in "
             "bit 12, ACK in bit 14, Link in bit 15.")

    def test_fires_on_sgmii(self):
        assert mod.is_sgmii(self.SGMII) is True

    def test_empty_blob_false(self):
        assert mod.is_sgmii("") is False
        assert mod.is_sgmii(None) is False

    def test_requires_name_token(self):
        # Same structural facts but the 'sgmii' name token removed -> defer.
        no_token = self.SGMII.replace("Serial-GMII (SGMII)", "the interface")
        no_token = no_token.replace("SGMII", "it")
        assert mod.is_sgmii(no_token) is False

    def test_defers_on_ethernet_mac(self):
        eth = ("Ethernet MAC: every frame carries a 7-octet preamble, a 1-octet "
               "Start Frame Delimiter (SFD), a 48-bit destination MAC address, a "
               "48-bit source MAC address, an EtherType/Length field, the payload "
               "(46-1500 bytes), and a 32-bit FCS (CRC-32). GMII connects MAC to "
               "PHY. Auto-Negotiation per Clause 28. Duplex full or half.")
        assert mod.is_sgmii(eth) is False

    def test_defers_on_automotive_ethernet(self):
        ae = ("Automotive Ethernet 100BASE-T1 / 1000BASE-T1 over a single "
              "unshielded twisted pair (PAM3 / PAM4). Master-slave PHY timing, "
              "EEE low-power idle, MAC frame with preamble/SFD/MAC-address/FCS. "
              "Duplex full. GMII to the MAC.")
        assert mod.is_sgmii(ae) is False

    def test_defers_on_800g_ethernet(self):
        e800 = ("800 Gigabit Ethernet (800GbAUI-8) uses eight 106.25 Gbps lanes "
                "with PAM4 signaling, RS-FEC (KP4), and a 64B/66B PCS. MAC frame "
                "with preamble/SFD/MAC-address/FCS, duplex full.")
        assert mod.is_sgmii(e800) is False

    def test_defers_on_rgmii(self):
        rgmii = ("RGMII reduced-pin GMII uses two 4-bit DDR data buses (TXD[3:0] "
                 "and RXD[3:0]) at 125 MHz with TX_CTL/RX_CTL, carrying 1000 Mbps "
                 "Ethernet in parallel between MAC and PHY. Duplex full.")
        # RGMII names GMII + duplex but has no 'sgmii' token, no 1.25 GBd serial
        # lane, no 8B/10B, and no Config_Reg ordered-set negotiation.
        assert mod.is_sgmii(rgmii) is False

    def test_subject_dominance_defers_on_ethernet_with_buried_sgmii(self):
        # v0.2.13 regression: "SGMII" is referenced inside the full IEEE 802.3
        # spec (a recognised PHY interface), so a whole-blob name scan fired on
        # the ethernet benchmark. The detector must DEFER when the SGMII mention
        # is buried (name token NOT in the head), else a re-run of ethernet
        # would auto-dispatch apply_sgmii_synth over its gold-scored docs.
        eth = ("IEEE 802.3 Ethernet MAC and PHY. " + ("CSMA/CD media access "
               "control, MAC frame with preamble, SFD, 48-bit addresses, "
               "length/type, payload and FCS (CRC-32). GMII connects MAC to "
               "PHY; 8B/10B PCS; Auto-Negotiation Config_Reg with link speed "
               "11:10 and duplex. 1.25 GBd serialized. ") * 40
               + " A PHY may expose an SGMII serial-gmii interface.")
        assert "sgmii" in eth.lower()
        assert "sgmii" not in eth[:3500].lower()
        assert mod.is_sgmii(eth) is False


class TestApplySgmiiSynth:
    def _docs(self, tmp_path):
        gd = tmp_path / "generated_docs"
        gd.mkdir()
        (gd / "L4_REGMAP.json").write_text(json.dumps(
            {"ic_name": "UNKNOWN", "registers": [], "schema_version": 2}))
        (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps(
            {"fields": {"channels": []}, "schema_version": "x"}))
        return gd

    def test_noop_when_flag_false(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_sgmii_synth(gd, False, None)
        l4 = json.loads((gd / "L4_REGMAP.json").read_text())
        assert l4["registers"] == []  # untouched

    def test_applies_canonical_content(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_sgmii_synth(gd, True, None)
        l4 = json.loads((gd / "L4_REGMAP.json").read_text())
        # Config_Reg speed/duplex/link encoding present.
        assert "11:10" in l4["config_reg_bits"]
        assert "Link Speed" in l4["config_reg_bits"]["11:10"]
        names = {r["name"] for r in l4["registers"]}
        assert {"tx_config_reg", "rx_config_reg"} <= names
        assert l4["ic_name"] == mod.IC_NAME
        # metadata preserved (merge, not overwrite)
        assert l4["schema_version"] == 2
        l17 = json.loads((gd / "L17_CHANNEL_SIGNAL_CATALOG.json").read_text())
        assert l17["fields"]["channel_counts"]["differential_pairs"] == 4
        assert l17["fields"]["channel_counts"]["data_lanes"] == 2

    def test_preserves_fields_metadata(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_sgmii_synth(gd, True, None)
        l17 = json.loads((gd / "L17_CHANNEL_SIGNAL_CATALOG.json").read_text())
        assert l17["schema_version"] == "x"
