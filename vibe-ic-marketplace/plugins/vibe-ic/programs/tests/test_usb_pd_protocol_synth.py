"""Tests for the USB-PD protocol synth + the generic auto-dispatch contract.

USB-PD is added via the v0.2.13 generic drop-in auto-dispatch
(AUTO_DISPATCH=True + is_<base> + apply_<base>_synth + IC_NAME), so these tests
pin both the detector (NAME-token-gated, no cross-fire on the USB 2.0 / USB4 /
I2C siblings) and the module-level auto-dispatch contract every drop-in must
satisfy.
"""
import importlib
import json

mod = importlib.import_module("usb_pd_protocol_synth")


class TestAutoDispatchContract:
    def test_opts_in(self):
        assert getattr(mod, "AUTO_DISPATCH", False) is True

    def test_exposes_detector_and_applier(self):
        assert callable(getattr(mod, "is_usb_pd", None))
        assert callable(getattr(mod, "apply_usb_pd_synth", None))

    def test_exposes_ic_name(self):
        assert isinstance(getattr(mod, "IC_NAME", None), str)
        assert "USB-PD" in mod.IC_NAME or "Power Delivery" in mod.IC_NAME


class TestIsUsbPdDetector:
    USB_PD = (
        "USB Power Delivery (USB-PD) negotiates power and data roles over the "
        "USB Type-C Configuration Channel (CC1/CC2) using Biphase Mark Coding "
        "(BMC) at 300 kbaud. The Source advertises a Power Data Object (PDO) "
        "list via Source_Capabilities; the Sink replies with a Request carrying "
        "a Request Data Object (RDO). The handshake is Source_Capabilities -> "
        "Request -> Accept -> PS_RDY. Roles swap via PR_Swap, DR_Swap, "
        "VCONN_Swap. Packets use SOP / SOP' / SOP'' ordered sets over CC, VBUS "
        "and VCONN.")

    def test_fires_on_usb_pd(self):
        assert mod.is_usb_pd(self.USB_PD) is True

    def test_empty_blob_false(self):
        assert mod.is_usb_pd("") is False
        assert mod.is_usb_pd(None) is False

    def test_requires_name_token(self):
        # All the structural marks but NO USB-PD name token -> defer.
        no_name = (
            "Biphase Mark Coding on the configuration channel CC1/CC2 with a "
            "Power Data Object PDO and Request Data Object RDO; Source and Sink "
            "negotiate VBUS and VCONN with PS_RDY and PR_Swap over SOP'.")
        assert mod.is_usb_pd(no_name) is False

    def test_defers_on_usb2_data(self):
        usb2 = (
            "Universal Serial Bus 2.0. Differential D+/D- data pair with NRZI "
            "line coding and bit stuffing. Packet ID (PID) fields, endpoints, "
            "SOF tokens, IN/OUT/SETUP transactions. Basic power delivery of "
            "500 mA at 5 V over VBUS, but no CC channel and no PDO objects.")
        assert mod.is_usb_pd(usb2) is False

    def test_defers_on_usb4(self):
        usb4 = (
            "USB4 tunnels USB 3.x, DisplayPort and PCI Express through routers "
            "at 20, 40 and 80 Gbit/s over USB-C. The Type-C CC pins and the USB "
            "Power Delivery specification handle connector setup, but USB4 "
            "itself defines the high-speed tunneling fabric. clampdown teardown.")
        assert mod.is_usb_pd(usb4) is False

    def test_defers_on_i2c(self):
        i2c = (
            "I2C-bus specification. Two wires SDA and SCL, 7-bit addressing, "
            "START and STOP conditions, ACK/NACK, multi-master arbitration. "
            "Standard-mode 100 kbit/s, Fast-mode 400 kbit/s.")
        assert mod.is_usb_pd(i2c) is False


class TestApplyUsbPdSynth:
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
        mod.apply_usb_pd_synth(gd, False, None)
        l3 = json.loads((gd / "L3_CMD_PROTOCOL.json").read_text())
        assert l3["opcodes"] == []  # untouched

    def test_applies_canonical_content(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_usb_pd_synth(gd, True, None)
        l3 = json.loads((gd / "L3_CMD_PROTOCOL.json").read_text())
        names = {o["name"] for o in l3["opcodes"]}
        assert {"Source_Capabilities", "Request", "PS_RDY", "PR_Swap"} <= names
        assert l3["ic_name"] == mod.IC_NAME
        # metadata preserved (merge, not overwrite)
        assert l3["schema_version"] == 2
        l17 = json.loads((gd / "L17_CHANNEL_SIGNAL_CATALOG.json").read_text())
        assert l17["fields"]["channel_counts"]["cc_wires"] == 2

    def test_preserves_fields_metadata(self, tmp_path):
        gd = self._docs(tmp_path)
        mod.apply_usb_pd_synth(gd, True, None)
        l17 = json.loads((gd / "L17_CHANNEL_SIGNAL_CATALOG.json").read_text())
        assert l17["schema_version"] == "x"
