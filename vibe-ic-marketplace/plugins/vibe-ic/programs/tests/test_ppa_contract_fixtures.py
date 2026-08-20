#!/usr/bin/env python3
"""Shared fixture builder for the PPA contract lane — and a canary over itself.

WHY A CANARY IN A FIXTURE FILE
==============================
Every red case in this lane is a green case with ONE field changed. That design
is what stops "the gate refuses everything" from passing for "the gate
discriminates" -- but it makes the BASE fixture load-bearing: if the base
declaration stopped producing a clean contract, every negative test would still
go red, for the wrong reason, and the suite would report a healthy lane while
measuring nothing.

`test_the_base_fixture_is_actually_clean` is that canary. It is the one test in
this file and it asserts the thing every other file in the lane assumes.

chip-AGNOSTIC: synthetic paths and synthetic content. Nothing here is a real
design, PDK, tool output or vendor artefact -- the contract lane never needs to
parse one, it hashes bytes and reads declared policy.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
SCHEMA_DIR = PLUGIN_ROOT / "schemas" / "ppa"

BUILD = PROGRAMS / "ppa_contract_build.py"
CHECK = PROGRAMS / "ppa_contract_check.py"
INTEGRITY = PROGRAMS / "ppa_problem_integrity_check.py"

#: Bound for every CLI subprocess. These programs hash a handful of small files
#: and touch no network with `--no-image-labels`; measured well under a second
#: each. Kept far under the repo's 60 s harness ceiling.
CLI_TIMEOUT_S = 45

#: A syntactically valid digest reference that names nothing real, so no test
#: can accidentally depend on a registry being reachable.
FAKE_IMAGE = ("ghcr.io/vibeic-test/contract-fixture@sha256:"
              + "1" * 64)


def make_run_tree(root: Path) -> Path:
    """Four synthetic artefacts under one root, with stable bytes."""
    (root / "spec").mkdir(parents=True, exist_ok=True)
    (root / "rtl").mkdir(parents=True, exist_ok=True)
    (root / "sta").mkdir(parents=True, exist_ok=True)
    (root / "spec" / "constraints.sdc").write_text(
        "create_clock -name clk -period 10.0 [get_ports clk]\n")
    (root / "spec" / "L19.json").write_text('{"clock_period_ns": 10.0}\n')
    (root / "rtl" / "top.v").write_text("module top(input clk); endmodule\n")
    (root / "sta" / "setup.rpt").write_text("wns -0.124\n")
    return root


def base_declaration() -> Dict[str, Any]:
    """A declaration that builds a CLEAN contract. Mutate a copy, never this."""
    return {
        "schema": "vibeic.ppa.contract_declaration.v1",
        "run_label": "fixture",
        "root_label": "run",
        "problem": {
            "artefacts": [
                {"role": "sdc", "path": "spec/constraints.sdc"},
                {"role": "l19_spec", "path": "spec/L19.json"},
            ],
            "facts": [
                {"key": "constraints.clk.period_ns", "value": 10.0,
                 "source": "sdc", "source_path": "spec/constraints.sdc"},
                {"key": "constraints.clk.period_ns", "value": 10.0,
                 "source": "l19_spec", "source_path": "spec/L19.json"},
            ],
        },
        "implementation": {
            "artefacts": [{"role": "rtl_top", "path": "rtl/top.v"}],
        },
        "analysis": {
            "artefacts": [{"role": "sta_setup", "path": "sta/setup.rpt"}],
            "facts": [{"key": "analysis.corner", "value": "slow",
                       "source": "runner"}],
        },
        "toolchain": {
            "images": [{"role": "eda", "ref": FAKE_IMAGE,
                        "verdict_bearing": True}],
            "tools": [{"name": "static_timing", "status": "MEASURED",
                       "version": "fixture"}],
        },
        "agent_execution": {
            "facts": [{"key": "agent.autonomy", "value": "advisory",
                       "source": "declared"}],
        },
        "policy": {
            "missing_power_basis": "REFUSE",
            "mutation_allow_list": ["pnr.*", "synth.strategy"],
            "mutation_forbidden": ["constraints.*", "pdk.*"],
        },
        "candidate": {"mutations": []},
        "metrics": [{
            "schema": "vibeic.ppa.metric.v1",
            "metric": "timing.setup.wns_ns",
            "status": "MEASURED",
            "value": -0.124,
            "unit": "ns",
            "scope": {"stage": "post_route_extracted", "check": "setup"},
            "source": {"path": "sta/setup.rpt", "tool": "static_timing"},
        }],
    }


def variant(**edits: Any) -> Dict[str, Any]:
    """A deep copy of the base declaration with top-level keys replaced."""
    decl = copy.deepcopy(base_declaration())
    decl.update(copy.deepcopy(edits))
    return decl


def write_json(path: Path, obj: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")
    return path


def run_cli(program: Path, *args: str) -> subprocess.CompletedProcess:
    """Drive the REAL entry point as a subprocess.

    Deliberately not `main(argv)` in-process: the flow acts on the EXIT CODE,
    and a test that calls a function measures the finding while leaving the
    verdict-to-exit-code mapping unmeasured. That gap is exactly what this
    repo's `gate_cli_mutation_probe` exists to find.
    """
    return subprocess.run(
        [sys.executable, str(program), *args],
        capture_output=True, text=True, timeout=CLI_TIMEOUT_S,
        cwd=str(PLUGIN_ROOT))


def build_contract(tmp_path: Path, declaration: Dict[str, Any],
                   name: str = "contract.json") -> subprocess.CompletedProcess:
    """Make the tree, write the declaration, build. Returns the process."""
    root = make_run_tree(tmp_path / "run")
    decl_path = write_json(tmp_path / "declaration.json", declaration)
    return run_cli(BUILD, "--declaration", str(decl_path),
                   "--root", str(root), "--out", str(tmp_path / name),
                   "--no-image-labels")


def codes(process: subprocess.CompletedProcess) -> List[str]:
    """Every `PPA-C-nnn` the program printed, in order."""
    import re
    return re.findall(r"PPA-C-\d{3}", process.stdout + process.stderr)


def test_the_base_fixture_is_actually_clean(tmp_path):
    """The canary. Every negative test in this lane is this fixture with ONE
    field changed, so a base that had quietly stopped being clean would make
    all of them red for the wrong reason and the lane would look healthy while
    measuring nothing."""
    built = build_contract(tmp_path, base_declaration())
    assert built.returncode == 0, (
        f"the BASE fixture no longer builds a clean contract "
        f"(rc={built.returncode}); every negative test in this lane is now "
        f"measuring the base rather than its own mutation.\n"
        f"stdout:\n{built.stdout}\nstderr:\n{built.stderr}")
    checked = run_cli(CHECK, "--contract", str(tmp_path / "contract.json"))
    assert checked.returncode == 0, (
        f"the base contract does not validate (rc={checked.returncode}):\n"
        f"{checked.stdout}\n{checked.stderr}")
