"""v0.1.50 — Half-duplex protocol turnaround cocotb TB generator (Type-A).

Doctrine: user audit (2026-05-29) flagged `skills/protocol-timeline-assert/`
as a Type-A skill (codegen from L2 JSON, zero LLM judgment). Moves the
generator to programs/; the skill is retired.

Emit shape verbatim from the retired SKILL.md § "Required Constants" +
the cocotb template.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# Field-name catalog — same as protocol_turnaround_audit
DELIMITER_TYP_KEYS = ("delimiter.typical_ns", "delimiter_typical_ns",
                      "break.typical_ns", "break_typical_ns",
                      "delimiter_typical")
TURNAROUND_MIN_KEYS = ("turnaround.min_ns", "turnaround_min_ns",
                       "t_turnaround_min", "tSRS.min_ns", "tSRS_min")
TURNAROUND_MAX_KEYS = ("turnaround.max_ns", "turnaround_max_ns",
                       "t_turnaround_max", "tSRS.max_ns", "tSRS_max")
CLOCK_PERIOD_KEYS = ("clock.period_ns", "clock_period_ns", "clk_period_ns",
                     "period_ns")
SPEC_REF_KEYS = ("spec_ref", "spec_reference", "section", "spec_section")


@dataclass
class TurnaroundParams:
    clock_period_ns: float
    delimiter_typical_ns: float
    t_turnaround_min_ns: float
    t_turnaround_max_ns: float
    tx_start_signal: str
    spec_section: str

    def is_complete(self) -> bool:
        return (self.clock_period_ns > 0
                and self.delimiter_typical_ns > 0
                and self.t_turnaround_min_ns > 0
                and self.t_turnaround_max_ns >= self.t_turnaround_min_ns
                and self.tx_start_signal)


def _lookup(data: Dict[str, Any], keys) -> Optional[float]:
    if not isinstance(data, dict):
        return None
    for k in keys:
        if "." in k:
            h, t = k.split(".", 1)
            if h in data and isinstance(data[h], dict):
                r = _lookup(data[h], (t,))
                if r is not None:
                    return r
        elif k in data:
            v = data[k]
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, dict):
                for ik in ("min_ns", "max_ns", "typical_ns",
                           "ns", "value"):
                    if ik in v and isinstance(v[ik], (int, float)):
                        return float(v[ik])
    for v in data.values():
        if isinstance(v, dict):
            r = _lookup(v, keys)
            if r is not None:
                return r
    return None


def _lookup_str(data: Dict[str, Any], keys) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    for k in keys:
        if k in data and isinstance(data[k], str):
            return data[k]
    for v in data.values():
        if isinstance(v, dict):
            r = _lookup_str(v, keys)
            if r is not None:
                return r
    return None


def extract_params(
    l2: Dict[str, Any],
    tx_start_signal: str = "tx_start",
) -> TurnaroundParams:
    return TurnaroundParams(
        clock_period_ns=_lookup(l2, CLOCK_PERIOD_KEYS) or 0,
        delimiter_typical_ns=_lookup(l2, DELIMITER_TYP_KEYS) or 0,
        t_turnaround_min_ns=_lookup(l2, TURNAROUND_MIN_KEYS) or 0,
        t_turnaround_max_ns=_lookup(l2, TURNAROUND_MAX_KEYS) or 0,
        tx_start_signal=tx_start_signal,
        spec_section=_lookup_str(l2, SPEC_REF_KEYS) or "unspecified",
    )


COCOTB_TEMPLATE = '''\
"""Auto-generated turnaround timeline assertion.
Emitted by `protocol_timeline_assert_gen.py` (Vibe-IC plugin v__PLUGIN_VERSION__).
Do not edit; regenerate from L2 timing JSON.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer
import cocotb.utils

CLOCK_PERIOD_NS                = __CLOCK_PERIOD_NS__
DELIMITER_TYPICAL_DURATION_NS  = __DELIM_TYP_NS__
T_TURNAROUND_MIN_NS            = __TURN_MIN_NS__
T_TURNAROUND_MAX_NS            = __TURN_MAX_NS__
TX_START_SIGNAL                = "__TX_START_SIGNAL__"
SPEC_SECTION                   = "__SPEC_SECTION__"
TIMEOUT_NS                     = T_TURNAROUND_MAX_NS * 4


async def drive_inbound_frame(dut):
    # Project-specific frame model. This stub fires a single edge so a
    # reviewer immediately knows the runner-side glue is needed.
    await RisingEdge(dut.clk)


async def drive_delimiter(dut, ns):
    await Timer(int(ns), units="ns")


async def wait_for_tx_start(dut, signal, timeout_ns):
    deadline = cocotb.utils.get_sim_time(units="ns") + timeout_ns
    while cocotb.utils.get_sim_time(units="ns") < deadline:
        if int(getattr(dut, signal).value) == 1:
            return cocotb.utils.get_sim_time(units="ns")
        await RisingEdge(dut.clk)
    raise AssertionError(
        "TX start never asserted within {} ns".format(timeout_ns))


@cocotb.test()
async def test_rx_tx_turnaround(dut):
    """Assert turnaround gap between RX frame end and TX response start."""
    clock = Clock(dut.clk, CLOCK_PERIOD_NS, units="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 0
    await Timer(100, units="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    await drive_inbound_frame(dut)
    await drive_delimiter(dut, DELIMITER_TYPICAL_DURATION_NS)
    delimiter_release_ns = cocotb.utils.get_sim_time(units="ns")
    tx_start_ns = await wait_for_tx_start(
        dut, TX_START_SIGNAL, TIMEOUT_NS)

    turnaround_ns = tx_start_ns - delimiter_release_ns
    assert T_TURNAROUND_MIN_NS <= turnaround_ns <= T_TURNAROUND_MAX_NS, (
        "Turnaround = {} ns, expected in [{}, {}] ns (spec_ref: {})".format(
            turnaround_ns, T_TURNAROUND_MIN_NS,
            T_TURNAROUND_MAX_NS, SPEC_SECTION))
'''


def emit_tb(params: TurnaroundParams) -> str:
    return (COCOTB_TEMPLATE
            .replace("__PLUGIN_VERSION__", _pmd.running_plugin_version())
            .replace("__CLOCK_PERIOD_NS__", str(int(params.clock_period_ns)))
            .replace("__DELIM_TYP_NS__", str(int(params.delimiter_typical_ns)))
            .replace("__TURN_MIN_NS__", str(int(params.t_turnaround_min_ns)))
            .replace("__TURN_MAX_NS__", str(int(params.t_turnaround_max_ns)))
            .replace("__TX_START_SIGNAL__", params.tx_start_signal)
            .replace("__SPEC_SECTION__", params.spec_section))


def _cli() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--l2-json", type=Path, required=True)
    p.add_argument("--tx-start-signal", default="tx_start")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--strict", action="store_true",
                   help="Fail if L2 params incomplete")
    args = p.parse_args()

    if not args.l2_json.exists():
        print(f"L2 JSON not found: {args.l2_json}", file=sys.stderr)
        return 2
    l2 = json.loads(args.l2_json.read_text(encoding="utf-8"))
    params = extract_params(l2, tx_start_signal=args.tx_start_signal)
    if not params.is_complete():
        msg = (f"L2 incomplete: clock={params.clock_period_ns} "
               f"delim={params.delimiter_typical_ns} "
               f"min={params.t_turnaround_min_ns} "
               f"max={params.t_turnaround_max_ns}")
        print(f"WARN: {msg}", file=sys.stderr)
        if args.strict:
            return 1
    tb = emit_tb(params)
    if args.out:
        args.out.write_text(tb, encoding="utf-8")
    else:
        print(tb, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
