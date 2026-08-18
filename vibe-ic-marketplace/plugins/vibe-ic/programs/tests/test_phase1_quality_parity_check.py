"""Tests for phase1_quality_parity_check.py (v0.50).

Covers: floor detection, fuzzy submodule match, pass path, fail paths.
"""
from __future__ import annotations
import json, subprocess, sys, tempfile, textwrap, os
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "phase1_quality_parity_check.py"
PLUGIN_ROOT = PROG.parent.parent.parent  # vibe-ic-marketplace/plugins


def _write_docs(tmp: Path, layers: dict):
    """Dump {'L3_CMD_PROTOCOL': {...}} mapping to json files under tmp/generated_docs."""
    docs = tmp / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    for name, obj in layers.items():
        (docs / f"{name}.json").write_text(json.dumps(obj))
    return docs


def _run(docs_dir: Path, class_path: str = "cable-side-id-ic"):
    result = subprocess.run(
        [sys.executable, str(PROG), str(docs_dir), "--class-path", class_path],
        capture_output=True, text=True,
    )
    # Take the trailing JSON object (stdout dump)
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        parsed = {"_raw": result.stdout, "_stderr": result.stderr}
    return result.returncode, parsed


def test_all_floors_met_passes(tmp_path):
    layers = {
        "L3_CMD_PROTOCOL": {
            "commands": [{"opcode": f"0x{i:02X}"} for i in range(8)],
            "crc": {"poly": "0x31"},
        },
        "L4_REGMAP": {
            "otp_map_128x8": [{"addr": i, "name": f"B{i}"} for i in range(128)],
            "registers": [{"name": f"R{i}"} for i in range(8)],
        },
        "L6_CONTROL_LOGIC": {
            "submodule_control_logic": {
                n: {} for n in [
                    "pad_ctrl", "dclk", "drst", "rx_phy", "tx_phy",
                    "rx_chk", "rx_cmd", "mac", "otp_ctrl", "gen_wake",
                ]
            }
        },
        "L9_INTEGRATION_SPEC": {
            "top_level_ports": [{"name": f"P{i}"} for i in range(20)],
            "internal_wires": [{"name": f"W{i}"} for i in range(40)],
            "submodules": [
                "pad_ctrl", "dclk", "drst", "rx_phy", "tx_phy",
                "rx_chk", "rx_cmd", "mac", "otp_ctrl", "gen_wake",
            ],
        },
    }
    docs = _write_docs(tmp_path, layers)
    code, out = _run(docs)
    assert out.get("pass") is True, out
    assert code == 0


def test_low_opcode_count_fails(tmp_path):
    layers = {
        "L3_CMD_PROTOCOL": {
            "commands": [{"opcode": "0x70"}, {"opcode": "0x72"}],
            "crc": {"poly": "0x31"},
        },
        "L4_REGMAP": {"otp_map_128x8": [{"addr": i} for i in range(128)]},
        "L6_CONTROL_LOGIC": {
            "submodule_control_logic": {
                n: {} for n in [
                    "pad_ctrl", "dclk", "drst", "rx_phy", "tx_phy",
                    "rx_chk", "rx_cmd", "mac", "otp_ctrl", "gen_wake",
                ]
            }
        },
        "L9_INTEGRATION_SPEC": {
            "top_level_ports": [{"name": f"P{i}"} for i in range(20)],
            "internal_wires": [{"name": f"W{i}"} for i in range(40)],
            "submodules": ["pad_ctrl", "dclk", "drst", "rx_phy", "tx_phy",
                           "rx_chk", "rx_cmd", "mac", "otp_ctrl", "gen_wake"],
        },
    }
    docs = _write_docs(tmp_path, layers)
    code, out = _run(docs)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "L3_opcode_count_min" in rules


def test_disallowed_crc_poly_fails(tmp_path):
    layers = {
        "L3_CMD_PROTOCOL": {
            "commands": [{"opcode": f"0x{i:02X}"} for i in range(10)],
            "crc": {"poly": "0xAB"},
        },
        "L4_REGMAP": {"otp_map_128x8": [{"addr": i} for i in range(128)]},
        "L6_CONTROL_LOGIC": {
            "submodule_control_logic": {
                n: {} for n in [
                    "pad_ctrl", "dclk", "drst", "rx_phy", "tx_phy",
                    "rx_chk", "rx_cmd", "mac", "otp_ctrl", "gen_wake",
                ]
            }
        },
        "L9_INTEGRATION_SPEC": {
            "top_level_ports": [{"name": f"P{i}"} for i in range(20)],
            "internal_wires": [{"name": f"W{i}"} for i in range(40)],
            "submodules": ["pad_ctrl", "dclk", "drst", "rx_phy", "tx_phy",
                           "rx_chk", "rx_cmd", "mac", "otp_ctrl", "gen_wake"],
        },
    }
    docs = _write_docs(tmp_path, layers)
    code, out = _run(docs)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "L3_crc_poly_allowed" in rules


def test_fuzzy_submodule_match_with_u_prefix(tmp_path):
    """L9 submodule names with 'u_' prefix should still match class names."""
    layers = {
        "L3_CMD_PROTOCOL": {
            "commands": [{"opcode": f"0x{i:02X}"} for i in range(10)],
            "crc": {"poly": "0x31"},
        },
        "L4_REGMAP": {
            "otp_map_128x8": [{"addr": i} for i in range(128)],
            "registers": [{"name": f"R{i}"} for i in range(8)],
        },
        "L6_CONTROL_LOGIC": {
            "submodule_control_logic": {
                n: {} for n in [
                    "u_pad_ctrl", "u_dclk", "u_drst", "u_rx_phy", "u_tx_phy",
                    "u_rx_chk", "u_rx_cmd", "u_mac", "u_otp_ctrl", "u_gen_wake",
                ]
            }
        },
        "L9_INTEGRATION_SPEC": {
            "top_level_ports": [{"name": f"P{i}"} for i in range(20)],
            "internal_wires": [{"name": f"W{i}"} for i in range(40)],
            "submodules": ["u_pad_ctrl", "u_dclk", "u_drst", "u_rx_phy",
                           "u_tx_phy", "u_rx_chk", "u_rx_cmd", "u_mac",
                           "u_otp_ctrl", "u_gen_wake"],
        },
    }
    docs = _write_docs(tmp_path, layers)
    code, out = _run(docs)
    # Floors met even with u_ prefix
    assert out.get("pass") is True, out
    assert code == 0


def test_small_otp_fails(tmp_path):
    layers = {
        "L3_CMD_PROTOCOL": {
            "commands": [{"opcode": f"0x{i:02X}"} for i in range(10)],
            "crc": {"poly": "0x31"},
        },
        "L4_REGMAP": {"otp_map_128x8": [{"addr": i} for i in range(16)]},  # 16 < 64
        "L6_CONTROL_LOGIC": {
            "submodule_control_logic": {
                n: {} for n in [
                    "pad_ctrl", "dclk", "drst", "rx_phy", "tx_phy",
                    "rx_chk", "rx_cmd", "mac", "otp_ctrl", "gen_wake",
                ]
            }
        },
        "L9_INTEGRATION_SPEC": {
            "top_level_ports": [{"name": f"P{i}"} for i in range(20)],
            "internal_wires": [{"name": f"W{i}"} for i in range(40)],
            "submodules": ["pad_ctrl", "dclk", "drst", "rx_phy", "tx_phy",
                           "rx_chk", "rx_cmd", "mac", "otp_ctrl", "gen_wake"],
        },
    }
    docs = _write_docs(tmp_path, layers)
    code, out = _run(docs)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "L4_otp_bytes_min" in rules


def test_missing_required_submodule_fails(tmp_path):
    """v0.56 (B3): named-submodule requirement was moved out of the
    generic `cable-side-id-ic` parent into the `cable-side-id-ic-maxim-style`
    sub-class — so the L6_required_submodules floor only fires when the
    Maxim-style sub-class is explicitly chosen. Test now drives the
    sub-class to confirm the floor still fires when applicable."""
    layers = {
        "L3_CMD_PROTOCOL": {
            "commands": [{"opcode": f"0x{i:02X}"} for i in range(10)],
            "crc": {"poly": "0x31"},
        },
        "L4_REGMAP": {"otp_map_128x8": [{"addr": i} for i in range(128)]},
        "L6_CONTROL_LOGIC": {
            "submodule_control_logic": {
                n: {} for n in ["pad_ctrl", "dclk", "drst", "rx_phy", "tx_phy",
                                "rx_chk", "rx_cmd", "otp_ctrl", "gen_wake"]  # mac missing
            }
        },
        "L9_INTEGRATION_SPEC": {
            "top_level_ports": [{"name": f"P{i}"} for i in range(20)],
            "internal_wires": [{"name": f"W{i}"} for i in range(40)],
            "submodules": ["pad_ctrl", "dclk", "drst", "rx_phy", "tx_phy",
                           "rx_chk", "rx_cmd", "otp_ctrl", "gen_wake"],
        },
    }
    docs = _write_docs(tmp_path, layers)
    code, out = _run(docs, class_path="cable-side-id-ic-maxim-style")
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "L6_required_submodules" in rules


# ---------------------------------------------------------------------------
# v0.56 A1: auto-resolve class_path from L1 + WARN on vacuous PASS
# ---------------------------------------------------------------------------
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).parent.parent))
import phase1_quality_parity_check as _parity  # noqa: E402


def test_resolve_class_path_from_l1_returns_leaf_lowercase(tmp_path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps(
        {"class_path": "any-ic > digital-ic > MEMORY-CONTROLLER"}))
    assert _parity._resolve_class_path_from_l1(docs) == "memory-controller"


def test_resolve_class_path_returns_none_when_l1_missing(tmp_path):
    assert _parity._resolve_class_path_from_l1(tmp_path) is None


def test_resolve_class_path_handles_unparseable_l1(tmp_path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_DATASHEET.json").write_text("not json at all")
    assert _parity._resolve_class_path_from_l1(docs) is None


def test_vacuous_pass_warning_emitted_when_no_spec_floor(tmp_path):
    """Class template with no spec_floor → run is a vacuous PASS but
    must surface a WARNING so the user/agent knows nothing was checked."""
    layers = {
        "L3_CMD_PROTOCOL": {"protocol_present": False, "reason": "ADC"},
        "L4_REGMAP": {"registers": []},
    }
    docs = _write_docs(tmp_path, layers)
    code, out = _run(docs, class_path="any-ic")
    # any-ic has no spec_floor → no findings (vacuous) but a WARN entry
    assert out.get("pass") is True
    assert out.get("spec_floor_present") is False
    warnings = out.get("warnings") or []
    assert any(w["rule"] == "vacuous_pass_no_spec_floor" for w in warnings)


def test_l3_no_protocol_sentinel_skips_l3_floors(tmp_path):
    """Class with L3_opcode_count_min must NOT fire when L3 declares
    protocol_present=false (memory / register-pointer / analog ICs)."""
    layers = {
        "L3_CMD_PROTOCOL": {"protocol_present": False,
                             "reason": "register-pointer access only"},
        "L4_REGMAP": {"otp_map_128x8": [{"addr": i} for i in range(128)],
                      "registers": [{"name": f"R{i}"} for i in range(4)]},
        "L6_CONTROL_LOGIC": {
            "submodule_control_logic": {n: {} for n in
                ["a", "b", "c", "d", "e", "f"]}
        },
        "L9_INTEGRATION_SPEC": {
            "top_level_ports": [{"name": f"P{i}"} for i in range(20)],
            "internal_wires": [{"name": f"W{i}"} for i in range(40)],
            "submodules": ["a", "b", "c", "d", "e", "f"],
        },
    }
    docs = _write_docs(tmp_path, layers)
    code, out = _run(docs, class_path="cable-side-id-ic")
    rules = [f["rule"] for f in out.get("findings", [])]
    # L3 floor checks must be skipped — sentinel is in effect
    assert "L3_opcode_count_min" not in rules
    assert "L3_crc_poly_allowed" not in rules
    measured = out.get("measured", {})
    assert measured.get("L3_protocol_present") is False


# ---------------------------------------------------------------------------
# v0.56 B1: count_l9_ports() descends into dtop_top_level.ports
# ---------------------------------------------------------------------------
def test_count_l9_ports_descends_into_dtop_top_level():
    l9 = {"dtop_top_level": {"ports": [{"name": f"P{i}"} for i in range(15)]}}
    assert _parity.count_l9_ports(l9) == 15


def test_count_l9_ports_descends_into_dtop_alias():
    l9 = {"dtop": {"ports": [{"name": f"P{i}"} for i in range(7)]}}
    assert _parity.count_l9_ports(l9) == 7


def test_count_l9_ports_legacy_root_keys_still_work():
    l9 = {"top_level_ports": [{"name": f"P{i}"} for i in range(5)]}
    assert _parity.count_l9_ports(l9) == 5


def test_count_l9_ports_returns_zero_when_no_ports():
    assert _parity.count_l9_ports({}) == 0
    assert _parity.count_l9_ports({"unrelated_key": "x"}) == 0


def test_generic_cable_side_class_does_not_require_named_submodules(tmp_path):
    """B3 regression test: the generic `cable-side-id-ic` parent class
    no longer demands IC-A-specific submodule names. A design with
    arbitrary submodule names that meets the structural minimum
    (>= 6 submodules) passes the parent class floor — only the
    Maxim-style sub-class enforces specific names."""
    layers = {
        "L3_CMD_PROTOCOL": {
            "commands": [{"opcode": f"0x{i:02X}"} for i in range(10)],
            "crc": {"poly": "0x31"},
        },
        "L4_REGMAP": {"otp_map_128x8": [{"addr": i} for i in range(128)],
                      "registers": [{"name": f"R{i}"} for i in range(4)]},
        "L6_CONTROL_LOGIC": {
            "submodule_control_logic": {
                n: {} for n in ["custom_pad", "decoder_a", "encoder_b",
                                "state_machine", "command_lookup",
                                "memory_iface", "reset_block"]
            }
        },
        "L9_INTEGRATION_SPEC": {
            "top_level_ports": [{"name": f"P{i}"} for i in range(16)],
            "internal_wires": [{"name": f"W{i}"} for i in range(28)],
            "submodules": ["custom_pad", "decoder_a", "encoder_b",
                           "state_machine", "command_lookup",
                           "memory_iface", "reset_block"],
        },
    }
    docs = _write_docs(tmp_path, layers)
    code, out = _run(docs, class_path="cable-side-id-ic")
    rules = [f["rule"] for f in out["findings"]]
    # The named-submodule floor must NOT fire for the generic parent.
    assert "L6_required_submodules" not in rules


# ---------------------------------------------------------------------------
# UNKNOWN-CLASS fallback: a class leaf not in the KB must pull a NEUTRAL
# generic floor, NEVER a protocol-specific (cable-side-id-ic) one.
# Regression for the mis-scoring defect (unknown class -> SERIAL-ID-IC floors).
# ---------------------------------------------------------------------------
def _run_no_classpath(docs_dir: Path):
    """Invoke WITHOUT --class-path so the program auto-resolves from L1."""
    result = subprocess.run(
        [sys.executable, str(PROG), str(docs_dir)],
        capture_output=True, text=True,
    )
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        parsed = {"_raw": result.stdout, "_stderr": result.stderr}
    return result.returncode, parsed


def test_unknown_class_uses_generic_not_protocol_floor(tmp_path):
    """A made-up class leaf must NOT inherit opcode/CRC/OTP (protocol) floors;
    it must pull the neutral generic-ic floor + surface an advisory note."""
    layers = {
        "L1_DATASHEET": {"class_path": "digital > accelerator > totally-made-up-xyz"},
    }
    docs = _write_docs(tmp_path, layers)
    code, out = _run_no_classpath(docs)
    assert out.get("template_used") == "generic-ic", out
    rules = {f["rule"] for f in out.get("findings", [])}
    # Protocol-specific floors must be ABSENT (the defect was applying these).
    assert "L3_opcode_count_min" not in rules
    assert "L3_crc_poly_allowed" not in rules
    assert "L4_otp_bytes_min" not in rules
    assert "L4_regmap_reg_count_min" not in rules
    # The neutral class-agnostic floor IS what got applied.
    assert "L6_submodule_count_min" in rules
    assert "L9_top_level_port_count_min" in rules
    # And a clear "unknown class -> generic floor" note is surfaced.
    warn_rules = {w["rule"] for w in out.get("warnings", [])}
    assert "unknown_class_generic_floor" in warn_rules


def test_unknown_class_generic_floor_passes_for_reasonable_design(tmp_path):
    """A real (if unclassified) design that meets the neutral floor PASSES —
    the generic floor only rejects degenerate 0-submodule / 0-port output."""
    layers = {
        "L1_DATASHEET": {"class_path": "digital > accelerator > totally-made-up-xyz"},
        "L6_CONTROL_LOGIC": {
            "submodule_control_logic": {n: {} for n in ("datapath", "ctrl", "top")}
        },
        "L9_INTEGRATION_SPEC": {
            "top_level_ports": [{"name": f"P{i}"} for i in range(4)],
            "submodules": ["datapath", "ctrl", "top"],
        },
    }
    docs = _write_docs(tmp_path, layers)
    code, out = _run_no_classpath(docs)
    assert out.get("template_used") == "generic-ic", out
    assert out.get("pass") is True, out
    assert code == 0
