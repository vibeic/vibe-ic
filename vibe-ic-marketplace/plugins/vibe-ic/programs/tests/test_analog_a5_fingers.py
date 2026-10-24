"""Explicit SPICE fingers reach the PDK's own geometry converter."""
import copy
from types import SimpleNamespace

import pytest

import _plugin_tree
import analog_a5_layout_emit as layout


def device(path, suffix="ng=2"):
    path.write_text(".subckt cell d g s b\n"
                    f"xunit d g s b native_mos w=16u l=0.5u m=3 {suffix}\n.ends cell\n")
    return layout.parse_netlist(path)[2][0]


def facts(*fingers):
    return SimpleNamespace(gencells={"native_mos": {
        "namespace": "provider", "params": ["w", "l", "m", "guard", *fingers]}})


@pytest.mark.parametrize("key", ["ng", "nf"])
def test_source_fingers_use_native_spice_conversion_and_preserve_total_width(tmp_path, key):
    dev = device(tmp_path / "source.sp", key + "=2")
    assert dev["pars"][key] == 2
    call = layout.gencell_call(dev, "drawn", facts(key))
    assert "provider::native_mos_convert" in call
    assert "w 16u l 0.5u m 3 " + key + " 2" in call
    assert "{*}$a5_finger_parameters" in call
    assert "native converter dropped or duplicated finger count" in call


def test_finger_geometry_cannot_reuse_a_different_native_probe(tmp_path):
    first = device(tmp_path / "source.sp")
    second = copy.deepcopy(first)
    second["pars"]["ng"] = 4
    assert layout.config_key(first) != layout.config_key(second)
    del second["pars"]["ng"]
    assert layout.config_key(first) != layout.config_key(second)


@pytest.mark.parametrize("count", ["0", "-1", "1.5", "nan", "inf", "2u", "unknown"])
def test_invalid_source_fingers_are_named_before_native_execution(tmp_path, count):
    with pytest.raises(ValueError, match="finger count must be a positive integer"):
        device(tmp_path / "source.sp", "ng=" + count)


def test_no_fingers_keeps_the_existing_native_call(tmp_path):
    dev = device(tmp_path / "source.sp", "")
    assert layout.gencell_call(dev, "drawn", facts("ng")) == (
        "magic::gencell provider::native_mos drawn w 16 l 0.5 m 3 guard 1")


def test_missing_pcell_support_refuses_instead_of_dropping_fingers(tmp_path):
    dev = device(tmp_path / "source.sp")
    with pytest.raises(layout.Refusal, match="declares no finger parameter"):
        layout.gencell_call(dev, "drawn", facts())


def test_ambiguous_finger_fields_refuse_before_native_execution(tmp_path):
    dev = device(tmp_path / "source.sp", "ng=2 nf=2")
    with pytest.raises(layout.Refusal, match="exactly one"):
        layout.gencell_call(dev, "drawn", facts("ng", "nf"))
