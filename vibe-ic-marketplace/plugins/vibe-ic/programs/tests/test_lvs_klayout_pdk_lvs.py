"""Unit tests for `klayout_pdk_lvs.py`.

The extraction core (`setup_extraction`, `finalize`, `cmd_*`, `write_named_spice`)
requires KLayout's `pya` and is NOT exercised on a CI host that lacks it. This
file pins the pure-Python, deterministic helpers that run WITHOUT `pya`:
  * `_net_name`  — net-name sanitisation + UNCONN counter;
  * `_default_threads` — $KLVS_THREADS override / cpu_count fallback;
  * `_load_lm` — default (generic) map vs a JSON override;
  * `DEFAULT_LAYERMAP` — the PDK-agnostic layer-key contract;
  * `_require_pya` — the disclosed exit-3 fallback (only when pya is absent).

Chip- and PDK-AGNOSTIC; the layermap is data, not hardcoded chip logic.
"""
import importlib
import json
import os

import pytest

mod = importlib.import_module("klayout_pdk_lvs")

try:
    import pya  # noqa: F401
    _HAS_PYA = True
except Exception:
    _HAS_PYA = False


class _FakeNet:
    """Stand-in for a pya Net: only `.name` and `.expanded_name()` are used."""
    def __init__(self, name=None, expanded="0"):
        self.name = name
        self._expanded = expanded

    def expanded_name(self):
        return self._expanded


class TestNetName:
    def test_none_yields_unconn_and_increments(self):
        counter = [0]
        assert mod._net_name(None, counter) == "UNCONN_1"
        assert mod._net_name(None, counter) == "UNCONN_2"
        assert counter[0] == 2

    def test_bus_bracket_to_dot(self):
        assert mod._net_name(_FakeNet("a[3]"), [0]) == "a.3"
        assert mod._net_name(_FakeNet("bus[10]"), [0]) == "bus.10"

    def test_comma_and_space_sanitised(self):
        # commas -> '_', spaces removed (netgen-safe token).
        assert mod._net_name(_FakeNet("x, y z"), [0]) == "x_yz"

    def test_plain_named_net_kept(self):
        assert mod._net_name(_FakeNet("VDD"), [0]) == "VDD"

    def test_empty_name_falls_back_to_expanded(self):
        assert mod._net_name(_FakeNet(name="", expanded="3:7"), [0]) == "n3_7"

    def test_whitespace_only_name_falls_back_to_expanded(self):
        assert mod._net_name(_FakeNet(name="   ", expanded="9"), [0]) == "n9"


class TestDefaultThreads:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("KLVS_THREADS", "5")
        assert mod._default_threads() == 5

    def test_cpu_count_fallback(self, monkeypatch):
        monkeypatch.delenv("KLVS_THREADS", raising=False)
        assert mod._default_threads() == (os.cpu_count() or 8)

    def test_non_numeric_env_falls_back_to_8(self, monkeypatch):
        monkeypatch.setenv("KLVS_THREADS", "not_a_number")
        assert mod._default_threads() == 8


class TestLoadLayerMap:
    def test_none_returns_default(self):
        assert mod._load_lm(None) is mod.DEFAULT_LAYERMAP

    def test_empty_string_returns_default(self):
        assert mod._load_lm("") is mod.DEFAULT_LAYERMAP

    def test_json_override(self, tmp_path):
        custom = {"poly": [99, 0], "metal": [[1, 0]]}
        p = tmp_path / "mypdk.json"
        p.write_text(json.dumps(custom))
        loaded = mod._load_lm(str(p))
        assert loaded == custom
        assert loaded is not mod.DEFAULT_LAYERMAP


class TestHp18e80Layermap:
    def test_has_all_required_keys(self):
        lm = mod.DEFAULT_LAYERMAP
        for key in ("poly", "nwell", "nactive", "pactive", "cont", "text",
                    "metal", "via", "vdd_rail_marker", "vss_rail_marker"):
            assert key in lm, f"missing layermap key {key}"

    def test_rail_markers_match_restore_pass(self):
        # These must line up with def_gds_port_power_restore.RAIL_MARKER (901/902).
        assert mod.DEFAULT_LAYERMAP["vdd_rail_marker"] == [901, 0]
        assert mod.DEFAULT_LAYERMAP["vss_rail_marker"] == [902, 0]

    def test_metal_and_via_are_layer_lists(self):
        lm = mod.DEFAULT_LAYERMAP
        assert all(isinstance(m, list) for m in lm["metal"])
        assert all(isinstance(v, list) for v in lm["via"])


@pytest.mark.skipif(_HAS_PYA, reason="exit-3 disclosure only fires when pya is absent")
class TestRequirePyaGate:
    def test_require_pya_exits_3_when_absent(self):
        with pytest.raises(SystemExit) as ei:
            mod._require_pya()
        assert ei.value.code == 3
