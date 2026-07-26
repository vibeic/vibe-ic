#!/usr/bin/env python3
"""ORGANIC #410 — registering a PDK in one table registers it in none of the
others, and nothing said so.

`pdk_registry.json` is not the only per-PDK table. Three programs carry their
own, keyed independently, and none of them knew any IHP PDK while the registry
had carried `ihp-sg13g2` all along. What that cost, measured end to end in the
issue: an IHP-mapped netlist matched none of the ATPG sniff's cell-name
patterns, so the engine got the SKY130A cell model while the artefact recorded
`generic_unmapped` — a substitution nothing disclosed because nothing knew one
had happened.

THE MAPPING IS DECLARED, NOT GUESSED. The registry names an enablement
(`sky130A`); the tables are keyed by process FAMILY (`sky130`), because the
ATPG model and the SPICE corners are shared across a family's enablements. A
checker that stripped a suffix to bridge that would be a fourth
hand-maintained rule — the exact defect #409 is about — so each registry entry
declares its own `per_pdk_table_key` and the registry stays the single source.

A GAP IS NOT AUTOMATICALLY A DEFECT: `nangate45` and `asap7` are not
manufacturable and have no supply contract to state. The gate makes each
absence RECORDED, so the next PDK cannot acquire three silent gaps the way
`ihp-sg13g2` did.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import pdk_table_coverage_check as C  # noqa: E402

_REG = _PROGRAMS / "pdk_registry.json"


def _reg_with(mutate) -> Path:
    d = json.loads(_REG.read_text())
    mutate(d)
    p = Path(tempfile.mkdtemp()) / "reg.json"
    p.write_text(json.dumps(d, indent=2))
    return p


def _run(args):
    return subprocess.run(
        [sys.executable, str(_PROGRAMS / "pdk_table_coverage_check.py")] + args,
        capture_output=True, text=True)


def test_main_is_clean_today():
    rep = C.audit()
    assert rep["verdict"] == "PASS", (rep["new_gaps"], rep["undeclared"])
    assert rep["tables"] == 3, rep["tables"]
    assert rep["gaps"], "an empty gap set would mean the check sees nothing"


def test_a_new_registry_pdk_with_no_table_entry_fails():
    """THE DEFECT, as the next person would hit it."""
    p = _reg_with(lambda d: d["pdks"].append(
        {"name": "newpdk-x", "container_path": "/foss/pdks/newpdk-x",
         "per_pdk_table_key": "newpdk-x"}))
    r = _run(["--registry", str(p)])
    assert r.returncode == 1
    assert "NEW per-PDK table gap" in r.stdout
    assert "newpdk-x" in r.stdout


def test_an_entry_with_no_declared_key_fails():
    """Silence is not coverage. Without a declared key nothing can SAY whether
    the tables cover it, and 'cannot tell' must not read as 'covered'."""
    def _strip(d):
        for e in d["pdks"]:
            if e.get("name") == "sky130A":
                e.pop("per_pdk_table_key", None)
    r = _run(["--registry", str(_reg_with(_strip))])
    assert r.returncode == 1
    assert "declare no `per_pdk_table_key`" in r.stdout


def test_the_sentinel_without_a_container_is_not_judged():
    """`custom_auto_detect` declares no directory because it is not a PDK.
    Demanding a table key from it would make the gate fire on a correct
    registry from day one, which is how a gate stops being read."""
    rep = C.audit()
    assert "custom_auto_detect" not in rep["undeclared"]
    assert not any("custom_auto_detect" in g for g in rep["gaps"])


def test_a_recorded_gap_does_not_fail():
    """Shrink-only: failing main on pre-existing gaps makes a gate people
    route around."""
    assert _run([]).returncode == 0


def test_the_baseline_refuses_to_grow():
    bl = Path(tempfile.mkdtemp()) / "bl.json"
    bl.write_text(json.dumps({"known": []}))
    r = _run(["--baseline", str(bl), "--write-baseline"])
    assert r.returncode == 1
    assert "refusing to GROW" in r.stdout


def test_an_unloadable_table_is_a_FAIL_not_a_PASS(monkeypatch):
    """A table nobody can import is a table nobody checked, and an empty set
    would silently make every PDK look covered."""
    monkeypatch.setattr(C, "_TABLES",
                        (("no_such_module_xyz", "T", "phantom"),))
    rep = C.audit()
    assert rep["verdict"] == "FAIL"
    assert rep["table_errors"]
