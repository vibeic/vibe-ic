"""ORGANIC #748 REOPEN — the L6 staged-RTL FSM escape was SINGLE-KEYED on
`_class_rtl_gen_null` and LEAKED to non-sparse reused-IP PROTOCOL classes.

Root cause
==========
The v1.0.82 #748 escape (l_doc_structured_field_count_check) credits the FSM
state count harvested from staged `input/vendor_rtl/` `typedef enum`s toward the
L6 floor, gated at the call site (`if 1 <= n_states < l6_min and
_class_rtl_gen_null(ic_class):`) and inside `_l6_staged_fsm_credit`. BOTH were
keyed ONLY on `_class_rtl_gen_null` — but that predicate is True for EVERY
reused-IP class, including the non-sparse PROTOCOL classes
(digital_cmd_driven / bus_interconnect_protocol / serial_peripheral_protocol /
bus_peripheral — all rtl_gen=null but `sparse_control_timing`=False, strict
l6_min=5). So pairing a 1-state L6 doc with ANY staged FSM enum relaxed their
floor to 1 → a PASS where the strict ≥5 floor MUST FAIL.

This contradicted #605's `test_protocol_classes_keep_strict_floor` and the L6
relaxation's own doctrine (l6_min/l8_min are keyed on
`_class_sparse_control_timing`, NOT `_class_rtl_gen_null`). #605's test never
caught it because it calls `_check_l_doc` WITHOUT `project=`, never exercising
the harvest path.

Fix (chip-AGNOSTIC, §4.05 fail-closed)
======================================
Add `and _class_sparse_control_timing(ic_class)` to the L6 escape gate AND to
the `_l6_staged_fsm_credit` key set, so the staged-RTL harvest credit fires ONLY
for genuinely-sparse compute/CPU classes (processor_cpu /
digital_arithmetic_primitive / crypto_accelerator) — NEVER a rich-protocol
class. Drives the REAL gate end-to-end via main() on directly-built tmp_path
fixtures (so detect_ic_class resolves through the registry and the harvest path
actually runs).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

_PROG = Path(__file__).parent.parent / "l_doc_structured_field_count_check.py"
_spec = importlib.util.spec_from_file_location("_l_doc_sfc_748r2", _PROG)
mod = importlib.util.module_from_spec(_spec)
sys.modules["_l_doc_sfc_748r2"] = mod
_spec.loader.exec_module(mod)

main = mod.main

# A staged serial-peripheral controller with a 3-state `typedef enum` declared on
# the FSM current/next-state registers `z_fsm_cs` / `z_fsm_ns`. Strong FSM-state
# signal names → the harvester WILL credit 3 states. The point of the test is
# that the CLASS GATE — not the harvester — must refuse to relax the protocol
# floor, even though the enum is perfectly harvestable.
_SERIAL_FSM_SV = (
    "typedef enum logic [1:0] {\n"
    "  IDLE, SHIFT, DONE\n"
    "} z_e;\n"
    "module spi_ctrl;\n"
    "  z_e z_fsm_cs, z_fsm_ns;\n"
    "endmodule\n"
)

# A staged 10-state CPU controller enum on `core_fsm_cs/ns`.
_CPU_FSM_SV = (
    "typedef enum logic [3:0] {\n"
    "  IDLE, FETCH, DECODE, EX, MEM, WB, STALL, FLUSH, TRAP, DBG\n"
    "} cs_e;\n"
    "module cpu_ctrl;\n"
    "  cs_e core_fsm_cs, core_fsm_ns;\n"
    "endmodule\n"
)


def _build_project(tmp_path: Path, *, ic_class: str, vendor_sv: str | None,
                   fsm_states, extra_l6: dict | None = None) -> Path:
    """Write a runnable project. `reports/ic_class.json` makes detect_ic_class
    deterministic through the registry; optionally stage a vendor RTL file under
    input/vendor_rtl/."""
    proj = tmp_path / "p"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "reports").mkdir(parents=True)
    (proj / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": ic_class, "confidence": 0.9}))
    if vendor_sv is not None:
        vd = proj / "input" / "vendor_rtl"
        vd.mkdir(parents=True)
        (vd / "ctrl.sv").write_text(vendor_sv)
    l6 = {
        "schema_version": "1.0",
        "layer": 6,
        "doc_class": "L6_CONTROL_LOGIC",
        "ic_name": "z",
        "fsm_states": list(fsm_states),
        "no_fsm_in_input": False,
    }
    if extra_l6:
        l6.update(extra_l6)
    (proj / "phase1" / "generated_docs" / "L6_CONTROL_LOGIC.json").write_text(
        json.dumps(l6))
    return proj


def _run(proj: Path) -> int:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return main([str(proj)])


# ---------------------------------------------------------------------------
# REOPEN repro — the leaking NEGATIVE half. The escape must NOT relax the strict
# ≥5 floor for a non-sparse reused-IP PROTOCOL class.
# ---------------------------------------------------------------------------

def test_serial_protocol_staged_fsm_one_prose_state_still_fails(tmp_path):
    """REOPEN repro-現象: serial_peripheral_protocol (rtl_gen=null,
    sparse_control_timing=False, strict l6_min=5) + staged vendor_rtl/ with a
    3-state z_fsm_cs/ns enum + 1 prose state → main() MUST rc=1 (strict ≥5 floor
    restored). PRE-FIX this LEAKED rc=0 because the gate keyed only on
    _class_rtl_gen_null."""
    proj = _build_project(
        tmp_path, ic_class="serial_peripheral_protocol",
        vendor_sv=_SERIAL_FSM_SV, fsm_states=[{"name": "IDLE"}])
    assert _run(proj) == 1, (
        "serial_peripheral_protocol must keep the strict ≥5 L6 floor — the "
        "staged-RTL FSM escape is for sparse compute/CPU classes only")


def test_bus_interconnect_protocol_staged_fsm_still_fails(tmp_path):
    """bus_interconnect_protocol (rtl_gen=null, sparse_control_timing=False) also
    keeps the strict floor with a staged FSM enum + 1 prose state."""
    proj = _build_project(
        tmp_path, ic_class="bus_interconnect_protocol",
        vendor_sv=_SERIAL_FSM_SV, fsm_states=[{"name": "IDLE"}])
    assert _run(proj) == 1


def test_serial_protocol_honest_fsm_flag_still_fails(tmp_path):
    """The option-(ii) flag-only relaxation path must ALSO refuse a non-sparse
    protocol class: serial_peripheral_protocol + honest fsm_in_staged_rtl:true +
    1 prose state (no harvestable enum) → still rc=1 (≥5 floor)."""
    proj = _build_project(
        tmp_path, ic_class="serial_peripheral_protocol",
        vendor_sv="localparam IDLE = 0, RUN = 1;",
        fsm_states=[{"name": "IDLE"}],
        extra_l6={"fsm_in_staged_rtl": True})
    assert _run(proj) == 1


# ---------------------------------------------------------------------------
# §4.05 POSITIVE — the genuinely-sparse compute/CPU class must STILL PASS.
# ---------------------------------------------------------------------------

def test_processor_cpu_staged_fsm_still_passes(tmp_path):
    """processor_cpu (rtl_gen=null, sparse_control_timing=True, l6_min=2) + a
    staged 10-state controller enum + 1 prose state → main() rc=0 — the original
    #748 positive must still PASS after the sparse gate is added."""
    proj = _build_project(
        tmp_path, ic_class="processor_cpu",
        vendor_sv=_CPU_FSM_SV, fsm_states=[{"name": "IDLE"}])
    assert _run(proj) == 0, "sparse processor_cpu must still get the escape"


def test_digital_arithmetic_primitive_staged_fsm_still_passes(tmp_path):
    """A second sparse class (digital_arithmetic_primitive,
    sparse_control_timing=True) also still gets the escape."""
    proj = _build_project(
        tmp_path, ic_class="digital_arithmetic_primitive",
        vendor_sv=_CPU_FSM_SV, fsm_states=[{"name": "IDLE"}])
    assert _run(proj) == 0


# ---------------------------------------------------------------------------
# Unit-level — the two predicates split the families exactly as the gate needs.
# ---------------------------------------------------------------------------

def test_predicate_split_protocol_vs_sparse():
    """rtl_gen=null is True for BOTH families; sparse_control_timing splits them
    — proving the two-key gate is necessary and sufficient."""
    for proto in ("serial_peripheral_protocol", "bus_interconnect_protocol",
                  "digital_cmd_driven", "bus_peripheral"):
        assert mod._class_rtl_gen_null(proto) is True
        assert mod._class_sparse_control_timing(proto) is False, proto
    for sparse in ("processor_cpu", "digital_arithmetic_primitive",
                   "crypto_accelerator"):
        assert mod._class_rtl_gen_null(sparse) is True
        assert mod._class_sparse_control_timing(sparse) is True, sparse


def test_l6_staged_fsm_credit_refuses_protocol_class():
    """_l6_staged_fsm_credit (the defense-in-depth helper) returns 0 for a
    non-sparse protocol class even with a harvestable staged enum, and >0 for a
    sparse class."""
    data = {"fsm_states": [{"name": "IDLE"}]}
    import tempfile
    base = Path(tempfile.mkdtemp())
    proj = base / "vp"
    vd = proj / "input" / "vendor_rtl"
    vd.mkdir(parents=True)
    (vd / "c.sv").write_text(_SERIAL_FSM_SV)
    assert mod._l6_staged_fsm_credit(
        data, proj, "serial_peripheral_protocol") == 0
    assert mod._l6_staged_fsm_credit(
        data, proj, "processor_cpu") >= 3
