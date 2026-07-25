#!/usr/bin/env python3
"""Bidirectional tests for l1_param_bus_width_resolve.py.

NEGATIVE CONTROL IS THE POINT OF THIS FILE. The headline assertion is
run in BOTH directions against the REAL consumer gate
(`l1_pin_bus_width_actionable_check`):

    defect  — a parametric-width bus pin + its declared parameter
              default, with the resolver NOT run  => gate FAILs (rc 1)
    fixed   — the byte-identical fixture with the resolver run
              first                                => gate PASSes (rc 0)

Either assertion alone is a rubber stamp, so both are asserted on the
same fixture.

The refusal paths are asserted too, because a resolver that resolves
too eagerly is worse than one that does not resolve at all: a wrong
bus width propagates silently into the netlist, whereas an unresolved
one still trips the gate.

All fixtures are SYNTHESIZED neutral data — invented parameter and
port names on an invented block. No real design's files are copied,
and no design name, PDK name or vendor part number appears anywhere.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "l1_param_bus_width_resolve.py"
_GATE = _HERE.parent / "l1_pin_bus_width_actionable_check.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


mod = _load(_PROG, "l1_param_bus_width_resolve")

# The consumer gate is what makes this test bidirectional. It was added
# in a later plugin version than some checkouts carry; when it is absent
# the gate-coupled assertions skip LOUDLY rather than silently passing.
_gate = _load(_GATE, "l1_pin_bus_width_actionable_check") \
    if _GATE.is_file() else None
_needs_gate = pytest.mark.skipif(
    _gate is None,
    reason=f"consumer gate absent from this checkout: {_GATE.name}")


# ---------------------------------------------------------------- fixture
def _mk(project: Path, *, pin_table, parameters, iface_text):
    """Write a minimal but REALISTIC phase1 output tree.

    `iface_text` lands under input/ because the gate derives which pins
    are buses from the design's OWN inputs — without it the gate
    VACUOUS_PASSes and the test would prove nothing."""
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "synth_block", "pin_table": pin_table},
                   ensure_ascii=False), encoding="utf-8")
    (gd / "L8_RTL_CONSTANTS.json").write_text(
        json.dumps({"parameters": parameters}, ensure_ascii=False),
        encoding="utf-8")
    src = project / "input" / "docs"
    src.mkdir(parents=True, exist_ok=True)
    (src / "L3_iface.md").write_text(iface_text, encoding="utf-8")


def _parametric_pin():
    return [
        {"name": "clk_in", "mode": "input", "width": 1, "msb": 0, "lsb": 0},
        {"name": "operand_bus", "mode": "input",
         "width": "N-bit(`[dwid-1:0]`, parameter `dwid` default 24)",
         "width_symbolic": "dwid-1:0",
         "extraction_strategy": "synth_table"},
    ]


# Realistic input shape: an interface table AND a pad-placement table that
# names the bus with its range attached (`operand_bus[dwid-1:0]`). Real
# vendor docs carry both, and the gate derives bus evidence from the
# SECOND form. A fixture with only the first form is not representative —
# it makes the gate VACUOUS_PASS and the test proves nothing.
_IFACE = (
    "| signal | width | dir | desc |\n"
    "| `clk_in` | 1-bit | input | clock |\n"
    "| `operand_bus` | N-bit(`[dwid-1:0]`) | input | operand |\n"
    "\n| Parameter | Default |\n| `dwid` | 24 |\n"
    "\n| Pad edge | signals |\n"
    "| North | `operand_bus[dwid-1:0]` whole bus, one pad per bit |\n"
)

# The SAME design documented WITHOUT the pad-placement table, so a pin's
# only bus evidence is L1's own prose width field. This is the shape that
# exposes the gate blind spot the resolver would otherwise create.
_IFACE_PROSE_ONLY = (
    "| signal | width | dir | desc |\n"
    "| `clk_in` | 1-bit | input | clock |\n"
    "| `operand_bus` | N-bit | input | operand |\n"
    "\n| Parameter | Default |\n| `dwid` | 24 |\n"
)


def _run_gate(project: Path):
    return _gate.evaluate(project)


def _read_pin(project: Path, name: str):
    d = json.loads((project / "phase1" / "generated_docs"
                    / "L1_DATASHEET.json").read_text(encoding="utf-8"))
    return next(p for p in d["pin_table"] if p["name"] == name)


# ============================================================ BIDIRECTIONAL
@_needs_gate
def test_defect_direction_gate_fails_without_resolver(tmp_path):
    """DEFECT: parametric width + available binding, resolver NOT run."""
    _mk(tmp_path, pin_table=_parametric_pin(),
        parameters=[{"name": "dwid", "default": "24"}], iface_text=_IFACE)
    v = _run_gate(tmp_path)
    assert v["verdict"] == "FAIL", v
    assert v["rc"] == 1
    assert any(x["pin"] == "operand_bus" for x in v["violations"]), v


@_needs_gate
def test_fixed_direction_gate_passes_after_resolver(tmp_path):
    """FIXED: byte-identical fixture, resolver run first."""
    _mk(tmp_path, pin_table=_parametric_pin(),
        parameters=[{"name": "dwid", "default": "24"}], iface_text=_IFACE)
    rep = mod.run(tmp_path)
    assert rep["resolved_count"] == 1, rep
    v = _run_gate(tmp_path)
    assert v["verdict"] == "PASS", v
    assert v["rc"] == 0
    assert v["violations"] == []


@_needs_gate
def test_resolution_does_not_blind_the_gate(tmp_path):
    """REGRESSION: the repair must not destroy the gate's own evidence.

    When a pin's ONLY bus evidence is L1's prose `width` string, binding
    the parameter rewrites width/msb/lsb to integers and that evidence
    disappears. Unless the gate also consults the typed `width_symbolic`
    field — which SURVIVES resolution — it drops to VACUOUS_PASS and
    silently stops asserting on the very pin just repaired.

    Measured before the gate was taught about `width_symbolic`:
    FAIL -> VACUOUS_PASS (bus_confirmed 1 -> 0). Required: FAIL -> PASS.
    """
    _mk(tmp_path, pin_table=_parametric_pin(),
        parameters=[{"name": "dwid", "default": "24"}],
        iface_text=_IFACE_PROSE_ONLY)
    before = _run_gate(tmp_path)
    assert before["verdict"] == "FAIL", before
    assert before["bus_confirmed"] == 1, before

    mod.run(tmp_path)

    after = _run_gate(tmp_path)
    assert after["bus_confirmed"] == 1, (
        "gate lost its grip on the repaired pin: %r" % after)
    assert after["verdict"] == "PASS", after


def test_resolver_binds_to_declared_default(tmp_path):
    _mk(tmp_path, pin_table=_parametric_pin(),
        parameters=[{"name": "dwid", "default": "24"}], iface_text=_IFACE)
    mod.run(tmp_path)
    pin = _read_pin(tmp_path, "operand_bus")
    assert pin["width"] == 24 and pin["msb"] == 23 and pin["lsb"] == 0, pin


def test_parametric_form_is_preserved_not_discarded(tmp_path):
    """Resolution is ADDITIVE — an elaboration-time consumer can re-bind."""
    _mk(tmp_path, pin_table=_parametric_pin(),
        parameters=[{"name": "dwid", "default": "24"}], iface_text=_IFACE)
    mod.run(tmp_path)
    pin = _read_pin(tmp_path, "operand_bus")
    assert pin["width_symbolic"] == "dwid-1:0", pin
    assert "param_bound" in pin["extraction_strategy"], pin


# ================================================================= REFUSALS
def test_refuses_when_no_binding_exists(tmp_path):
    """No declared default => the program must NOT invent a width."""
    _mk(tmp_path, pin_table=_parametric_pin(), parameters=[],
        iface_text=_IFACE)
    rep = mod.run(tmp_path)
    assert rep["resolved_count"] == 0, rep
    assert rep["unresolved"][0]["status"] == "unbound"
    assert rep["unresolved"][0]["unbound_parameters"] == ["dwid"]
    assert _read_pin(tmp_path, "operand_bus").get("msb") is None


@_needs_gate
def test_gate_still_fails_when_binding_absent(tmp_path):
    """The refusal must remain VISIBLE — not silently downgraded."""
    _mk(tmp_path, pin_table=_parametric_pin(), parameters=[],
        iface_text=_IFACE)
    mod.run(tmp_path)
    assert _run_gate(tmp_path)["verdict"] == "FAIL"


def test_refuses_conflicting_defaults_across_docs(tmp_path):
    """Two docs disagreeing on a default => refuse, never pick one."""
    _mk(tmp_path, pin_table=_parametric_pin(),
        parameters=[{"name": "dwid", "default": "24"}], iface_text=_IFACE)
    gd = tmp_path / "phase1" / "generated_docs"
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"parameters": [{"name": "dwid", "default": "32"}]},
                   ensure_ascii=False), encoding="utf-8")
    rep = mod.run(tmp_path)
    assert rep["resolved_count"] == 0, rep
    assert rep["ambiguous_bindings"], rep
    assert rep["ambiguous_bindings"][0]["parameter"] == "dwid"
    assert "dwid" not in rep["bindings"]


def test_never_overwrites_an_already_resolved_width(tmp_path):
    pins = [{"name": "operand_bus", "mode": "input", "width": 8,
             "msb": 7, "lsb": 0, "width_symbolic": "dwid-1:0"}]
    _mk(tmp_path, pin_table=pins,
        parameters=[{"name": "dwid", "default": "24"}], iface_text=_IFACE)
    rep = mod.run(tmp_path)
    assert rep["resolved_count"] == 0, rep
    pin = _read_pin(tmp_path, "operand_bus")
    assert pin["width"] == 8 and pin["msb"] == 7


def test_dry_run_writes_nothing(tmp_path):
    _mk(tmp_path, pin_table=_parametric_pin(),
        parameters=[{"name": "dwid", "default": "24"}], iface_text=_IFACE)
    rep = mod.run(tmp_path, dry_run=True)
    assert rep["resolved_count"] == 1
    assert rep["docs_written"] == []
    assert _read_pin(tmp_path, "operand_bus").get("msb") is None


def test_l9_mirror_is_repaired_too(tmp_path):
    """phase2 and l9_rtl_pin_consistency read the L9 mirror, not L1."""
    _mk(tmp_path, pin_table=_parametric_pin(),
        parameters=[{"name": "dwid", "default": "24"}], iface_text=_IFACE)
    gd = tmp_path / "phase1" / "generated_docs"
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_ports": _parametric_pin()}, ensure_ascii=False),
        encoding="utf-8")
    mod.run(tmp_path)
    l9 = json.loads((gd / "L9_INTEGRATION_SPEC.json").read_text(
        encoding="utf-8"))
    tp = next(p for p in l9["top_ports"] if p["name"] == "operand_bus")
    assert tp["width"] == 24 and tp["msb"] == 23, tp


# ============================================================== SAFE EVAL
@pytest.mark.parametrize("expr,binds,want", [
    ("dwid-1", {"dwid": 24}, 23),
    ("2*n", {"n": 8}, 16),
    ("(a+b)-1", {"a": 4, "b": 4}, 7),
    ("n//2", {"n": 9}, 4),
    ("7", {}, 7),
])
def test_safe_eval_arithmetic(expr, binds, want):
    assert mod.safe_eval(expr, binds) == want


@pytest.mark.parametrize("expr", [
    "__import__('os').system('true')",
    "open('/etc/passwd').read()",
    "[].__class__",
    "lambda: 1",
    "a if b else c",
    "unbound_name-1",
    "x" * 300,
])
def test_safe_eval_rejects_non_arithmetic(expr):
    assert mod.safe_eval(expr, {"b": 1, "c": 2}) is None


def test_safe_eval_rejects_division_by_zero():
    assert mod.safe_eval("n//0", {"n": 8}) is None


@pytest.mark.parametrize("raw,want", [
    ("32", 32), ("  16 ", 16), ("0x20", 32), ("8'd12", 12),
    ("wide", None), ("", None), (None, None), (True, None), (-4, None),
])
def test_default_value_parsing(raw, want):
    assert mod._as_int(raw) == want
