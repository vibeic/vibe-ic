"""Explicit L10 byte-signature contracts and their cocotb commit observer.

The producer copies this small module into the generated bundle. No port role
or expected result is inferred from an expert hook's Python implementation.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path


def resolve_cases(rows: list, ports: list, clock: dict) -> list:
    """Validate only explicitly selected memory_signature cases; never coerce."""
    selected = [row for row in rows if isinstance(row, dict)
                and row.get("category") == "memory_signature"]
    by_name = {port["name"]: port for port in ports}
    cases = []
    ids = set()
    for row in selected:
        cid = row.get("id")
        if not isinstance(cid, str) or not cid.isidentifier() or cid in ids:
            raise ValueError("memory_signature needs a unique coroutine case.id")
        ids.add(cid)
        interface = row.get("interface")
        required = {"clock", "edge", "write_enable", "active_level",
                    "write_address", "write_data"}
        if not isinstance(interface, dict) or set(interface) != required:
            raise ValueError(f"{cid}: memory_signature interface is incomplete or unsupported")
        roles = [interface[key] for key in
                 ("clock", "write_enable", "write_address", "write_data")]
        if any(not isinstance(name, str) or name not in by_name for name in roles):
            raise ValueError(f"{cid}: memory_signature role names an absent L9 port")
        if len(set(roles)) != len(roles):
            raise ValueError(f"{cid}: memory_signature port roles must be distinct")
        for key, direction, width in (("clock", "input", 1),
                                      ("write_enable", "output", 1),
                                      ("write_data", "output", 8)):
            port = by_name[interface[key]]
            if (port["dir"] != direction or type(port.get("numeric_width")) is not int
                    or port["numeric_width"] != width):
                raise ValueError(f"{cid}: unsupported {key} direction/width")
        address = by_name[interface["write_address"]]
        address_width = address.get("numeric_width")
        if (address["dir"] != "output" or type(address_width) is not int
                or not 1 <= address_width <= 64):
            raise ValueError(f"{cid}: unresolved byte-address port")
        if (interface["clock"] != clock.get("clk")
                or interface["edge"] not in ("posedge", "negedge")
                or interface["edge"] != clock.get("edge")):
            raise ValueError(f"{cid}: commit clock/edge does not match current L9 clock")
        if type(interface["active_level"]) is not int or interface["active_level"] not in (0, 1):
            raise ValueError(f"{cid}: write-enable active_level must be 0 or 1")
        expected = row.get("expected_bytes")
        if not isinstance(expected, dict) or not expected:
            raise ValueError(f"{cid}: memory_signature needs nonempty expected_bytes")
        normalized = {}
        for raw_address, value in expected.items():
            if not isinstance(raw_address, str) or not raw_address.isdecimal():
                raise ValueError(f"{cid}: expected byte addresses must be decimal strings")
            addr = int(raw_address)
            if addr >= 1 << address_width or str(addr) in normalized:
                raise ValueError(f"{cid}: duplicate or out-of-range expected byte address")
            if type(value) is not int or not 0 <= value <= 255:
                raise ValueError(f"{cid}: expected byte values must be integers in 0..255")
            normalized[str(addr)] = value
        cases.append({"id": cid, "interface": dict(interface),
                      "expected_bytes": normalized})
    return cases


def seed_memory_signature(expected_bytes: dict) -> dict:
    """Initial external storage for a resolved byte-signature contract.

    An expert reference applies this before starting its clock. Each owed
    byte starts different from its expected result, so a skipped zero store
    cannot satisfy the reference's final memory comparison. Other storage is
    owned by the reference; this does not change the commit observer.
    """
    return {int(address): (~value) & 0xff
            for address, value in expected_bytes.items()}


def receipt_name(cid: str) -> str:
    return f"memory_signature_{cid}.json"


def check_observation(case: dict, observation: dict) -> None:
    """Every owed address needs a real commit, including zero-valued bytes."""
    assert observation.get("case") == case, "memory signature contract changed"
    actual = observation.get("observed_bytes")
    assert isinstance(actual, dict), "memory signature observations missing"
    missing = sorted(set(case["expected_bytes"]) - set(actual), key=int)
    assert not missing, f"memory signature missing store at byte addresses {missing}"
    mismatches = {addr: {"actual": actual[addr], "expected": value}
                  for addr, value in case["expected_bytes"].items()
                  if type(actual[addr]) is not int or actual[addr] != value}
    assert not mismatches, f"memory signature committed-byte mismatch: {mismatches}"


def read_observations(out: Path, cases: list) -> None:
    for case in cases:
        observed = json.loads((out / receipt_name(case["id"])).read_text())
        check_observation(case, observed)


def checked(case: dict):
    """Wrap one declared expert coroutine with its actual external write port.

    Sampling immediately on the declared edge reads the previous registered
    transaction, exactly when external synchronous byte storage commits it.
    Post-edge/NBA sampling would observe the next transaction instead.
    """
    def decorate(test):
        @functools.wraps(test)
        async def run(dut, *args, **kwargs):
            import cocotb
            from cocotb.triggers import FallingEdge, RisingEdge

            interface = case["interface"]
            observation = {"case": case, "observed_bytes": {},
                           "commit_count": 0, "sampled_edges": 0}

            async def observe():
                edge = RisingEdge if interface["edge"] == "posedge" else FallingEdge
                while True:
                    await edge(getattr(dut, interface["clock"]))
                    observation["sampled_edges"] += 1
                    if int(getattr(dut, interface["write_enable"]).value) == interface["active_level"]:
                        address = int(getattr(dut, interface["write_address"]).value)
                        value = int(getattr(dut, interface["write_data"]).value)
                        observation["observed_bytes"][str(address)] = value
                        observation["commit_count"] += 1

            monitor = cocotb.start_soon(observe())
            try:
                result = await test(dut, *args, **kwargs)
                check_observation(case, observation)
                return result
            finally:
                monitor.cancel()
                Path(receipt_name(case["id"])).write_text(
                    json.dumps(observation, indent=2) + "\n")
        return run
    return decorate
