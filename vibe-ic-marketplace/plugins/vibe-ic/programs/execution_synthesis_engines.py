"""Source-owned Step 9 synthesis identities and evidence boundary.

This module deliberately contains no fixture producer. A Step 9 producer is
eligible only when the production adapter has bound the current source tree,
the measured LibreLane image and the canonical declaration/RTL input set.
"""
from __future__ import annotations
# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess

import execution_modes as em

STEP_ID = "9"
RECEIPT_CONTRACT = "librelane-mapped-synthesis-v1"
REQUIRED_GATES = (
    "synth_netlist_check", "provenance_check",
    "area_total_vs_budget_check", "pdk_consistency_check",
)
CANONICAL_NETLIST = "phase2/stage2/synth/netlist.v"
CANONICAL_AREA = "phase2/stage2/synth/area.rpt"
CANONICAL_STATS = "phase2/stage2/synth/stats.json"
CANONICAL_AREA_ANY = f"{CANONICAL_AREA} OR {CANONICAL_STATS}"
NETLIST = "project/" + CANONICAL_NETLIST
AREA = "project/" + CANONICAL_AREA
STATS = "project/" + CANONICAL_STATS
PRODUCER_RECEIPT = "producer.json"
NATIVE_COMMANDS = "native_commands.jsonl"


@dataclass(frozen=True)
class SynthesisEngine:
    arm_id: str
    tool_id: str
    mapping_family: str
    engine_families: tuple[str, ...]
    native_entrypoint: str
    provenance_tool: str
    native_steps: tuple[str, ...]

    def contract(self) -> dict:
        return {
            "schema": 1, "arm_id": self.arm_id, "tool_id": self.tool_id,
            "mapping_family": self.mapping_family,
            "engine_families": list(self.engine_families),
            "native_entrypoint": self.native_entrypoint,
            "provenance_tool": self.provenance_tool,
            "native_steps": list(self.native_steps),
            "receipt_contract": RECEIPT_CONTRACT,
        }


LIBRELANE = SynthesisEngine(
    "librelane-mapped-synthesis", "librelane", "yosys+abc", ("yosys", "abc"),
    "phase3_one_shot_runner._step_synth_librelane", "yosys",
    ("Yosys.JsonHeader", "Yosys.Synthesis", "Checker.YosysUnmappedCells",
     "Checker.YosysSynthChecks", "Checker.NetlistAssignStatements"),
)
DIRECT_YOSYS = SynthesisEngine(
    "yosys-direct-wrapper", "yosys", "yosys+abc", ("yosys", "abc"),
    LIBRELANE.native_entrypoint, LIBRELANE.provenance_tool,
    LIBRELANE.native_steps,
)


def source_sha() -> str:
    """Return the actual checked-out source identity, never a caller claim."""
    root = Path(__file__).resolve()
    cp = subprocess.run(["git", "-C", str(root.parent), "rev-parse", "HEAD"],
                        capture_output=True, text=True, timeout=10)
    value = cp.stdout.strip() if cp.returncode == 0 else ""
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise em.Refusal("PRODUCTION_SOURCE_NOT_VERSIONED", cp.stderr[-300:])
    return value


def population() -> dict:
    return {
        "schema": 1, "providers": [LIBRELANE.contract()],
        "independent_mapping_families": [LIBRELANE.mapping_family],
        "source_provider_count": 1, "native_qualification": "NOT_MEASURED",
        "same_engine_wrappers": ["direct", "librelane", "slang"],
        "unavailable_independent_engine": {
            "state": "NOT_MEASURED",
            "reason": "SECOND_INDEPENDENT_ENGINE_UNAVAILABLE",
            "missing": [
                "independent RTL-to-mapped-netlist engine identity",
                "source-owned synthesis entrypoint and exact native command",
                "current RTL/top/PDK/liberty input mapping",
                "usable licence entitlement and aggregate licence cost",
                "native image/tool/source identity qualification",
                "mapped-netlist/stat/state/checker/provenance output contract",
                "engine-specific primary consumer and canonical importer",
            ],
        },
    }


def require_engine(arm_id: str = LIBRELANE.arm_id) -> SynthesisEngine:
    if arm_id != LIBRELANE.arm_id:
        raise em.Refusal("PRODUCTION_SYNTH_ENGINE_UNAVAILABLE", json.dumps(
            {"requested": arm_id, **population()}, sort_keys=True))
    return LIBRELANE


def lease_reservation(quota: dict) -> dict:
    fields = ("cpus", "ram_mb", "host_ram_mb", "container_ram_mb")
    if (any(type(quota.get(name)) is not int or quota[name] <= 0 for name in fields)
            or quota["host_ram_mb"] + quota["container_ram_mb"] != quota["ram_mb"]):
        raise em.Refusal("PRODUCTION_SYNTH_LEASE_BUDGET_UNBOUND", repr(quota))
    return {"cpus": quota["cpus"], "ram_mb": quota["ram_mb"]}


def require_spec(spec: dict) -> SynthesisEngine:
    contract = spec.get("synthesis_engine") if isinstance(spec, dict) else None
    if not isinstance(contract, dict):
        raise em.Refusal("PRODUCTION_SYNTH_ENGINE_CONTRACT_MISSING", "request.json")
    engine = require_engine(contract.get("arm_id"))
    if contract != engine.contract():
        raise em.Refusal("PRODUCTION_SYNTH_ENGINE_CONTRACT_CHANGED", engine.arm_id)
    return engine


def consume_producer(spec: dict, producer: dict) -> SynthesisEngine:
    """Bind producer identity before any primary gate is consumed."""
    engine = require_spec(spec)
    if (producer.get("synthesis_engine") != engine.contract()
            or producer.get("native_entrypoint") != engine.native_entrypoint
            or producer.get("status") not in ("PASS", "FAIL", "NOT_MEASURED")):
        raise em.Refusal("PRODUCTION_SYNTH_ENGINE_PRODUCER_CHANGED", engine.arm_id)
    return engine


def native_entrypoint_is_real(value: object) -> bool:
    return value == LIBRELANE.native_entrypoint


def build_registry(**kwargs):
    """Compatibility seam for callers moving to ``execution_production``.

    Registration remains production-owned; this wrapper does not expose a
    fixture producer or a second policy/controller implementation.
    """
    from execution_production import build_registry as _build
    registry = kwargs.pop("registry", None)
    if registry is None:
        registry = em.Registry()
    return _build(registry=registry, **kwargs)
