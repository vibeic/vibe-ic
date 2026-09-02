#!/usr/bin/env python3
"""`_rtl_fsm_extract` — the structural state-enum rule, written ONCE.

Every case below is a minimal pair. The rule this module implements already
existed twice (in `l6_fsm_scaffold_actionable_check` and in
`l_doc_structured_field_count_check`) with NO producer reading either, which is
how `opentitan_aes` published `no_fsm_in_input: true` against a staged tree
declaring four closed state enums. These tests pin the rule AND the fact that
there is now one implementation of it.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _rtl_fsm_extract as R  # noqa: E402


BOUND = """
package p;
  typedef enum logic [1:0] {S_IDLE = 2'b00, S_RUN = 2'b01, S_DONE = 2'b10} st_e;
endpackage
module m;
  st_e m_fsm_cs, m_fsm_ns;
  always_comb begin
    m_fsm_ns = m_fsm_cs;
    case (m_fsm_cs)
      S_IDLE: begin
        m_fsm_ns = S_RUN;
      end
      S_RUN: begin
        m_fsm_ns = go ? S_DONE : S_IDLE;
      end
      S_DONE: begin
        m_fsm_ns = S_IDLE;
      end
    endcase
  end
endmodule
"""

#: The SAME enum, declared on a signal no name makes a state register.
UNBOUND = BOUND.replace("m_fsm_cs, m_fsm_ns", "colour_a, colour_b").replace(
    "case (m_fsm_cs)", "case (colour_a)").replace("m_fsm_ns", "colour_b")


def test_a_bound_enum_is_a_declared_state_machine():
    machines = R.declared_state_machines({"m.sv": BOUND})
    assert [m["type_name"] for m in machines] == ["st_e"]
    assert [s["name"] for s in machines[0]["states"]] == [
        "S_IDLE", "S_RUN", "S_DONE"]
    assert machines[0]["states"][0]["literal"] == "2'b00"


def test_an_unbound_enum_is_not_a_state_machine():
    """The negative control. Without it the rule is 'every enum is an FSM',
    which would put a colour table in L6.fsm_states."""
    assert R.declared_state_machines({"m.sv": UNBOUND}) == []


def test_a_weak_suffix_needs_a_case_over_it():
    weak = BOUND.replace("m_fsm_cs", "req_state").replace(
        "m_fsm_ns", "req_state_d")
    assert R.declared_state_machines({"m.sv": weak})          # has `case (req_state)`
    no_case = weak.replace("case (req_state)", "case (unrelated)")
    assert R.declared_state_machines({"m.sv": no_case}) == []


def test_a_commented_out_enum_is_not_harvested():
    hidden = "\n".join("// " + line for line in BOUND.splitlines())
    assert R.declared_state_machines({"m.sv": hidden}) == []


def test_transitions_come_from_the_arm_the_assignment_is_in():
    machines = R.declared_state_machines({"m.sv": BOUND})
    edges = {(t["from"], t["to"]) for t in machines[0]["transitions"]}
    assert ("S_IDLE", "S_RUN") in edges
    assert ("S_DONE", "S_IDLE") in edges
    # BOTH arms of the ternary in the S_RUN arm are targets.
    assert ("S_RUN", "S_DONE") in edges
    assert ("S_RUN", "S_IDLE") in edges
    # A self-edge asserts no movement and is not emitted.
    assert not any(f == t for f, t in edges)


def test_a_ternary_target_is_not_read_as_a_case_arm():
    """MEASURED before the label anchor existed: `cond ? A : B` matched the
    `MEMBER:` arm-label pattern, so an assignment further down the SAME arm was
    attributed to `A`. On aes_cipher_control_fsm.sv that invented
    CLEAR_S -> INIT and CLEAR_S -> ERROR, two edges the design does not have."""
    machines = R.declared_state_machines({"m.sv": BOUND})
    edges = {(t["from"], t["to"]) for t in machines[0]["transitions"]}
    # `S_DONE` appears only as a ternary target inside the S_RUN arm, never as
    # a label before the S_DONE arm's own assignment.
    assert ("S_DONE", "S_IDLE") in edges
    assert ("S_DONE", "S_DONE") not in edges


def test_the_assignment_target_is_the_wider_typed_set_not_the_bound_one():
    """MEASURED: eligibility credits `*_cs` (the `case`-ed register) while every
    next-state assignment writes `*_ns`, whose weak `_ns` suffix has no `case`
    over it. Reading edges off the eligible subset alone found ZERO transitions
    in a file carrying twelve."""
    split = BOUND.replace("m_fsm_cs", "m_state").replace(
        "m_fsm_ns", "m_state_d")
    machines = R.declared_state_machines({"m.sv": split})
    # `m_state` is `case`-ed, so the WEAK `_state` suffix credits it.
    # `m_state_d` is weak and has no `case` over it, so it is NOT eligible —
    # and it is where every next-state assignment goes.
    assert machines[0]["state_signals"] == ["m_state"]
    assert machines[0]["transitions"], "edges must still be found on *_state_d"


def test_a_package_declared_type_bound_in_another_file_is_found():
    pkg = BOUND.split("module m;")[0]
    mod = "module m;" + BOUND.split("module m;")[1]
    machines = R.declared_state_machines({"pkg.sv": pkg, "m.sv": mod})
    assert len(machines) == 1
    assert machines[0]["source_file"] == "pkg.sv"
    assert machines[0]["binding_files"] == ["m.sv"]


def test_a_one_member_enum_is_not_a_state_machine():
    one = """
module m;
  typedef enum logic {ONLY} solo_e;
  solo_e m_fsm_cs;
endmodule
"""
    assert R.declared_state_machines({"m.sv": one}) == []


def test_the_gate_and_the_ldoc_check_share_this_implementation():
    """Not a style point. Three readers with two copies is exactly what let one
    gate credit an FSM the other contradicted on the same tree."""
    import l6_fsm_scaffold_actionable_check as gate
    import l_doc_structured_field_count_check as ldoc

    assert gate._enum_fsm_state_count is R.enum_fsm_state_count
    assert gate._TYPEDEF_ENUM_RE is R.TYPEDEF_ENUM_RE
    assert gate._strip_verilog_comments is R.strip_verilog_comments
    assert ldoc._TYPEDEF_ENUM_RE is R.TYPEDEF_ENUM_RE
    assert ldoc._strip_v_comments is R.strip_verilog_comments
    assert ldoc._FSM_SIGNAL_TOKENS_STRONG is R.FSM_SIGNAL_STRONG


def test_enum_fsm_state_count_agrees_with_the_machine_harvest():
    assert R.enum_fsm_state_count(BOUND) == 3
    assert R.enum_fsm_state_count(UNBOUND) == 0


def test_read_rtl_tree_is_relative_and_deterministic(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.sv").write_text(BOUND)
    (tmp_path / "b.v").write_text("module b; endmodule\n")
    tree = R.read_rtl_tree(tmp_path)
    assert set(tree) == {"sub/a.sv", "b.v"}
    assert R.machines_from_tree(tmp_path)[0]["source_file"] == "sub/a.sv"
    assert R.read_rtl_tree(tmp_path / "nope") == {}
