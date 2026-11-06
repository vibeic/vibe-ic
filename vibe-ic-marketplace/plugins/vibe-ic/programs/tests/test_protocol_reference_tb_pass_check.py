#!/usr/bin/env python3
"""Tests for protocol_reference_tb_pass_check.py — Wave 28 gate."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import _watchdog


PLUGIN_TB = (Path(__file__).resolve().parent.parent.parent
             / "tools" / "protocol_tb" / "aid_class_reference_tb.v")







# Wave 34: a minimal "responder" stub that passes the new EXAMPLE_PROTOCOL-class
# reference TB.  Drives ONLY response bits (no device-side BR) +
# opcode 0x75 + 6 ID bytes + correct CRC for any host BR seen on
# id_bus.  Wave 28 stubs that emitted a 14us DUT BR before the bits
# now violate Wave 34 PROTOCOL_VIOLATION_DEVICE_BR and will FAIL.

# Wave 34: stub that emits a leading device BR (14us LOW) before
# response bits.  Should now FAIL the Wave 34 TB with
# PROTOCOL_VIOLATION_DEVICE_BR.

# A "silent" stub: declares an inout id_bus port but never drives it.

# A "wrong opcode" stub: drives 0x55 instead of 0x75.























def test_plugin_tb_present():
    """Sanity: the plugin reference TB ships with the package."""
    assert PLUGIN_TB.is_file(), (
        f"plugin reference TB not found at {PLUGIN_TB} — "
        "Wave 28 install incomplete")
    txt = PLUGIN_TB.read_text()
    assert "aid_class_reference_tb" in txt
    assert "PROTOCOL_REFERENCE_TB_PASS" in txt
    assert "PROTOCOL_REFERENCE_TB_FAIL" in txt


def test_wave35_extended_scenarios_present():
    """Wave 35 (v0.119.67): extended diagnostic scenarios are wired
    into the TB.  Each scenario has a task definition and is driven
    in the main initial block.
    """
    txt = PLUGIN_TB.read_text()
    # Scenario tasks
    for scen in (
        "run_scenario_get_otp_byte",
        "run_scenario_set_state",
        "run_scenario_crc_corruption",
        "run_scenario_frame_timeout",
        "run_scenario_multi_byte_cmd",
        "run_scenario_wake_then_get_id",
    ):
        assert scen in txt, f"missing scenario task: {scen}"
    # Per-scenario verdict markers
    for marker in (
        "PASS_GET_OTP_BYTE", "SKIP_GET_OTP_BYTE",
        "PASS_SET_STATE", "SKIP_SET_STATE",
        "PASS_CRC_CORRUPTION",
        "PASS_FRAME_TIMEOUT", "WARN_FRAME_TIMEOUT",
        "SKIP_MULTI_BYTE_CMD",
        "PASS_WAKE_THEN_GET_ID", "WARN_WAKE_THEN_GET_ID",
    ):
        assert marker in txt, f"missing scenario verdict marker: {marker}"
