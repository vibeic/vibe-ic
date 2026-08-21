"""tests/test_phase1_issue8_v1676_bare_bullet_residual.py — v1.6.76

Closes the bare-bullet residual surfaced by field agent on v1.6.75.
v1.6.75's 3 interface-for-PROTOCOL regexes work for lines with the
word `interface`; bullet-list module catalogs like `*  I2C master`
have no `interface` token and bypass the rejects. v1.6.76 adds a
HYBRID fix: structural-anchor requirement on path-#2 + targeted
bare-bullet reject.
"""
from __future__ import annotations
import json
from pathlib import Path
from programs.phase1_one_shot_runner import gen_l2_frs

_GEN_DIR = Path("phase1") / "generated_docs"


def _seed(tmp_path):
    project = tmp_path
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    return project


def _read(project, name):
    return json.loads((project / _GEN_DIR / f"{name}.json").read_text())


def test_l2_rejects_bare_axi_bullet(tmp_path):
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi\n\nIncluded modules:\n\n"
            "*  AXI\n*  AXI lite\n*  APB\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_rejects_i2c_master_slave_bullets(tmp_path):
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi\n\nI2C variants:\n\n"
            "*  I2C master\n*  I2C slave\n*  I2C slave APB master\n"
            "*  I2C slave AXI lite master\n*  I2C single register\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_rejects_apb_to_axi_lite_adapter_bullet(tmp_path):
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi\n\nBridges:\n\n"
            "*  APB to AXI lite adapter\n*  AXI to AXI lite adapter\n"
            "*  AXI lite to AXI adapter\n*  AXI lite to APB adapter\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_rejects_xfcp_i2c_master_module(tmp_path):
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi\n\nXFCP variants:\n\n"
            "*  XFCP I2C master module\n*  UART\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


def test_l2_aid_class_rich_input_still_emits_dict_v1676(tmp_path):
    """Positive control: rich-input single-wire EXAMPLE_PROTOCOL command bus
    must STILL emit dict in v1.6.76. The line `single-wire EXAMPLE_PROTOCOL
    command bus` has BOTH `bus` and `command` anchors — passes
    path-#2 structural gate."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP ID IC over a single-wire EXAMPLE_PROTOCOL command bus.\n"
            "Half-duplex frames carry opcodes and responses.\n"
            "Wake pulse required before each command.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po["half_duplex"] is True
    assert po["wire_count"] == 1


def test_l2_real_protocol_with_anchor_still_emits(tmp_path):
    """Sentence-level protocol claim with structural anchor must
    still pass path-#2 (don't over-correct)."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "The IC speaks I2C protocol over the SDA / SCL bus.\n"
            "Frames are half-duplex; opcodes follow command bytes.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    # Should emit dict (real claim with bus/protocol anchors).
    # half_duplex may be True (sentence-anchored).
    po = l2.get("protocol_overview")
    assert po is not None


def test_l2_aggregate_v1676_taxi_no_leak(tmp_path_factory):
    """All 13 taxi v1.6.75 leak lines must emit null in v1.6.76."""
    cases = [
        ("l80",  "*  APB to AXI lite adapter\n"),
        ("l85",  "*  AXI\n"),
        ("l87",  "*  AXI to AXI lite adapter\n"),
        ("l96",  "*  AXI lite\n"),
        ("l98",  "*  AXI lite to AXI adapter\n"),
        ("l99",  "*  AXI lite to APB adapter\n"),
        ("l175", "*  I2C master\n"),
        ("l176", "*  I2C single register\n"),
        ("l177", "*  I2C slave\n"),
        ("l178", "*  I2C slave APB master\n"),
        ("l179", "*  I2C slave AXI lite master\n"),
        ("l181", "*  UART\n"),
        ("l213", "*  XFCP I2C master module\n"),
    ]
    leaked = []
    for label, src in cases:
        proj = _seed(tmp_path_factory.mktemp(label))
        gen_l2_frs(proj, {"spec.txt": src})
        l2 = _read(proj, "L2_FRS")
        if l2.get("protocol_overview") is not None:
            leaked.append(label)
    assert not leaked, f"v1.6.76 bare-bullet leak: {leaked}"
