#!/usr/bin/env python3
"""v0.1.83 — L6/L8 floors are IC-class-aware. Datapath/compute + CPU classes
(specs delegate internal micro-arch to implementation) use ≥2 FSM / ≥3 timing;
command/protocol/unknown classes keep the strict ≥5 / ≥10 (fail-closed)."""
from __future__ import annotations
import sys
from pathlib import Path
PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import l_doc_structured_field_count_check as G  # noqa: E402

_FSM2 = {"fsm_states": [{"name": "idle"}, {"name": "active"}]}
_FSM4 = {"fsm_states": [{"name": n} for n in ("a", "b", "c", "d")]}
_T3 = {"timing_parameters": {"clk_ns": 25.9, "cycles": 66, "lat": 80}}
_T10 = {"timing_parameters": {f"t{i}": i + 1 for i in range(10)}}


def test_datapath_l6_relaxed_to_2():
    assert G._check_l_doc(6, _FSM2, {}, "digital_arithmetic_primitive")[0] is True


def test_cpu_l6_relaxed_to_2():
    assert G._check_l_doc(6, _FSM2, {}, "processor_cpu")[0] is True


def test_datapath_l8_relaxed_to_3():
    assert G._check_l_doc(8, _T3, {}, "digital_arithmetic_primitive")[0] is True


def test_datapath_l6_still_floors_at_2():
    # zero FSM states must STILL fail even for datapath (it's a floor, not a skip)
    assert G._check_l_doc(6, {"fsm_states": []}, {}, "digital_arithmetic_primitive")[0] is False


def test_command_driven_l6_stays_strict():
    assert G._check_l_doc(6, _FSM2, {}, "digital_cmd_driven")[0] is False
    assert G._check_l_doc(6, _FSM4, {}, "digital_cmd_driven")[0] is False  # <5


def test_command_driven_l8_stays_strict():
    assert G._check_l_doc(8, _T3, {}, "digital_cmd_driven")[0] is False


def test_unknown_stays_strict():
    assert G._check_l_doc(6, _FSM4, {}, "unknown")[0] is False
    assert G._check_l_doc(8, _T3, {}, "unknown")[0] is False


def test_protocol_stays_strict():
    assert G._check_l_doc(8, _T3, {}, "bus_interconnect_protocol")[0] is False
    # but a protocol chip with full ≥10 timing still passes
    assert G._check_l_doc(8, _T10, {}, "bus_interconnect_protocol")[0] is True
