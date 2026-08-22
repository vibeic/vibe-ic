"""ORGANIC #748 — L6 ≥2-FSM-state floor was UNSATISFIABLE for a reused-IP
processor_cpu whose control FSM lives in STAGED vendor RTL (n_states==1 dead
zone).

`l_doc_structured_field_count_check.py` is a NO-waiver gate
(`l_doc_structured_*` is on the forbidden-waiver prefix list). For a REUSED-IP
processor_cpu (sparse_control_timing=True → l6_min=2) the real multi-state
control FSMs live in staged vendor RTL (controller / LSU `typedef enum {...}
..._e;` state machines) and the doc prose honestly names ≤1 state:

  - the #462 `_has_honest_no_fsm` escape requires n_states==0;
  - the ≥2 floor catches n_states>=2;
  - the legitimate n_states==1 reused-IP case is a DEAD ZONE with no escape;
  - the forbidden-waiver prefix blocks any waiver → hard-FAIL despite the FSM
    PROVABLY existing in the staged RTL.

Fix (chip-AGNOSTIC, Bucket B, DOUBLE-KEYED per the #428/#419/#641/#708
doctrine): when the doc honestly extracts ≥1 prose state AND the class is
registry rtl_gen=null AND staged vendor_rtl/ carries an FSM-typed `typedef enum`
(or the doc carries an honest `fsm_in_staged_rtl: true` flag), credit the FSM
state count harvested from the staged RTL toward the L6 floor.

§4.05 FAIL-CLOSED (load-bearing NEGATIVE half): bare_fpga / unknown stay strict;
a class with NO staged RTL and NO honest flag keeps the ≥2 floor; n_states==0
with no honest no-FSM flag still FAILs; a generic (non-FSM) enum never relaxes
the floor. Keyed on the registry rtl_gen=null flag + vendor_rtl/ presence +
typedef-enum grammar — NEVER a design SKU.

This test drives the REAL gate end-to-end via main() (so detect_ic_class runs
through the registry) on directly-built tmp_path fixtures.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

_PROG = Path(__file__).parent.parent / "l_doc_structured_field_count_check.py"
_spec = importlib.util.spec_from_file_location("_l_doc_sfc_748", _PROG)
mod = importlib.util.module_from_spec(_spec)
sys.modules["_l_doc_sfc_748"] = mod
_spec.loader.exec_module(mod)

main = mod.main

# A staged controller with a 6-state `typedef enum {...} state_e;` declared on
# the FSM current/next-state registers `core_fsm_cs` / `core_fsm_ns`.
_VENDOR_CONTROLLER_SV = (
    "typedef enum logic [2:0] {\n"
    "  IDLE, FETCH, DECODE, EXEC, MEM, WB\n"
    "} state_e;\n"
    "module controller;\n"
    "  state_e core_fsm_cs, core_fsm_ns;\n"
    "endmodule\n"
)


def _build_cpu_project(tmp_path: Path, *, vendor_sv: str | None,
                       fsm_states, extra_l6: dict | None = None) -> Path:
    """Write a runnable processor_cpu project. `reports/ic_class.json` makes
    detect_ic_class deterministic through the registry; optionally stage a
    vendor RTL file under input/vendor_rtl/."""
    proj = tmp_path / "x"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "reports").mkdir(parents=True)
    (proj / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": "processor_cpu", "confidence": 0.9}))
    if vendor_sv is not None:
        vd = proj / "input" / "vendor_rtl"
        vd.mkdir(parents=True)
        (vd / "controller.sv").write_text(vendor_sv)
    l6 = {
        "schema_version": "1.0",
        "layer": 6,
        "doc_class": "L6_CONTROL_LOGIC",
        "ic_name": "riscv_core",
        "fsm_states": list(fsm_states),
        "no_fsm_in_input": False,
    }
    if extra_l6:
        l6.update(extra_l6)
    (proj / "phase1" / "generated_docs" / "L6_CONTROL_LOGIC.json").write_text(
        json.dumps(l6))
    return proj


def _run(proj: Path) -> int:
    """Invoke the real gate main(), swallowing its stdout, return the rc."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return main([str(proj)])


# ---------------------------------------------------------------------------
# POSITIVE — the dead-zone case now PASSES through the REAL main() entry point.
# ---------------------------------------------------------------------------

def test_reused_ip_cpu_staged_fsm_now_passes(tmp_path):
    """processor_cpu, fsm_states=[IDLE] (n_states==1), staged vendor_rtl/ with a
    6-state typedef-enum FSM → the gate now PASSES (escape credits ≥2 from the
    staged RTL). Pre-fix this was a hard EXIT 1 dead zone."""
    proj = _build_cpu_project(
        tmp_path, vendor_sv=_VENDOR_CONTROLLER_SV, fsm_states=[{"name": "IDLE"}])
    assert _run(proj) == 0, "reused-IP CPU with staged FSM must PASS"


def test_honest_fsm_in_staged_rtl_flag_one_hot(tmp_path):
    """A one-hot / localparam FSM the harvester can't parse to a typedef-enum
    still PASSES when the doc carries the honest `fsm_in_staged_rtl: true` flag
    (option ii relaxes the floor to ≥1 with 1 prose state)."""
    proj = _build_cpu_project(
        tmp_path, vendor_sv="localparam IDLE = 0, RUN = 1;",
        fsm_states=[{"name": "IDLE"}],
        extra_l6={"fsm_in_staged_rtl": True})
    assert _run(proj) == 0


# ---------------------------------------------------------------------------
# §4.05 FAIL-CLOSED — load-bearing NEGATIVE half. The escape must NEVER let an
# empty / unconfirmed / wrong-class doc through.
# ---------------------------------------------------------------------------

def test_control_no_staged_rtl_one_state_still_fails(tmp_path):
    """CONTROL: NO staged RTL + 1 prose state keeps the strict ≥2 floor → FAIL.
    (This is the dead-zone case WITHOUT the staged-RTL evidence — proving the
    relaxation is gated on the staged content, not on the class alone.)"""
    proj = _build_cpu_project(
        tmp_path, vendor_sv=None, fsm_states=[{"name": "IDLE"}])
    assert _run(proj) == 1, "no staged RTL → ≥2 floor stays in force"


def test_n_states_zero_with_staged_enum_no_honest_flag_still_fails(tmp_path):
    """n_states==0 (empty fsm_states) + staged enum but NO honest no-FSM flag →
    still FAILs: the harvest requires the doc's OWN ≥1 prose state, so an empty
    L6 can never ride the staged RTL into a pass."""
    proj = _build_cpu_project(
        tmp_path, vendor_sv=_VENDOR_CONTROLLER_SV, fsm_states=[])
    assert _run(proj) == 1


def test_bare_fpga_with_staged_enum_stays_strict(tmp_path):
    """§4.05 — bare_fpga stays strict (≥5) even with a staged 6-state enum and
    a prose state: an unclassified / no-protocol-fabric class earns no
    relaxation."""
    proj = _build_cpu_project(
        tmp_path, vendor_sv=_VENDOR_CONTROLLER_SV, fsm_states=[{"name": "IDLE"}])
    (proj / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": "bare_fpga", "confidence": 0.9}))
    assert _run(proj) == 1


def test_unknown_class_with_staged_enum_stays_strict(tmp_path):
    """§4.05 — unknown_protocol_class stays fail-closed."""
    proj = _build_cpu_project(
        tmp_path, vendor_sv=_VENDOR_CONTROLLER_SV, fsm_states=[{"name": "IDLE"}])
    (proj / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": "unknown_protocol_class", "confidence": 0.9}))
    assert _run(proj) == 1


def test_non_fsm_enum_does_not_relax(tmp_path):
    """A generic non-FSM enum (a request-kind enum on a non-FSM-named signal)
    must NOT relax the floor: mere presence of a vendor file / any enum is not
    FSM confirmation."""
    proj = _build_cpu_project(
        tmp_path,
        vendor_sv="typedef enum { RD, WR, NOP } req_e; req_e cmd;",
        fsm_states=[{"name": "IDLE"}])
    assert _run(proj) == 1


def test_vendor_file_no_enum_no_flag_still_fails(tmp_path):
    """A staged vendor file with NO FSM enum and NO honest flag, 1 prose state →
    still FAILs (presence of a .sv is not confirmation of an FSM)."""
    proj = _build_cpu_project(
        tmp_path, vendor_sv="module foo; endmodule",
        fsm_states=[{"name": "IDLE"}])
    assert _run(proj) == 1


def test_honest_no_fsm_zero_states_still_passes_462(tmp_path):
    """Regression guard — the pre-existing #462 n_states==0 honest-no-FSM escape
    is untouched: empty fsm_states + no_fsm_in_input:true still PASSES."""
    proj = _build_cpu_project(
        tmp_path, vendor_sv=_VENDOR_CONTROLLER_SV, fsm_states=[],
        extra_l6={"no_fsm_in_input": True})
    assert _run(proj) == 0


# ---------------------------------------------------------------------------
# Unit-level harvester checks (the typedef-enum grammar, chip-AGNOSTIC).
# ---------------------------------------------------------------------------

def test_harvest_counts_fsm_typed_enum():
    n = mod._harvest_staged_fsm_state_count(_VENDOR_CONTROLLER_SV)
    assert n == 6, f"6-state state_e on core_fsm_cs/ns should harvest 6, got {n}"


def test_harvest_ignores_non_fsm_enum():
    n = mod._harvest_staged_fsm_state_count(
        "typedef enum { RD, WR, NOP } req_e; req_e cmd;")
    assert n == 0, "an enum on a non-FSM-named signal must not be harvested"


def test_harvest_max_across_two_fsms():
    """controller enum (10 states) + LSU enum (5 states) → MAX widest FSM."""
    txt = (
        "typedef enum logic [3:0] { S0,S1,S2,S3,S4,S5,S6,S7,S8,S9 } ctrl_e;\n"
        "ctrl_e ctrl_fsm_cs;\n"
        "typedef enum logic [2:0] { L0,L1,L2,L3,L4 } lsu_e;\n"
        "lsu_e lsu_state;\n")
    assert mod._harvest_staged_fsm_state_count(txt) == 10


# ── adversarial-review remediation guards (#748) ─────────────────────────────
def test_commented_out_enum_not_counted():
    """MEDIUM: a commented-out / dead FSM enum (the only enum) must NOT be
    harvested as a live FSM."""
    dead = ("/* typedef enum { IDLE, FETCH, DECODE, EXEC } state_e; "
            "state_e core_fsm_cs; */\nlogic [1:0] cnt;\n")
    assert mod._harvest_staged_fsm_state_count(dead) == 0


def test_generic_enum_on_weak_state_name_without_case_not_counted():
    """MEDIUM: a generic (non-FSM) enum bound to a coincidentally-`_state`-named
    signal with NO `case (<signal>)` transition must NOT be credited as an FSM."""
    opcode = ("typedef enum logic[3:0]{ADD,SUB,AND,OR,XOR,SLL,SRL,SLT}opcode_e;\n"
              "opcode_e req_state;\n")
    assert mod._harvest_staged_fsm_state_count(opcode) == 0
    # WITH a case transition it is confirmed as an FSM.
    assert mod._harvest_staged_fsm_state_count(
        opcode + "always_comb case(req_state) ADD: x=1; default: x=0; endcase\n") == 8


def test_degenerate_one_member_enum_not_counted():
    """LOW: a 1-member enum is not a multi-state control FSM."""
    one = "typedef enum { ONLY } s_e; s_e core_fsm_cs;\n"
    assert mod._harvest_staged_fsm_state_count(one) == 0
