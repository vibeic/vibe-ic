#!/usr/bin/env python3
"""Who owes a per-module unit testbench, and for which modules.

MEASURED on opentitan_aes, plugin v1.15.66: 11 candidates, 11 missing, and the
FAIL blocked step 4. Every one of the 11 was a module that ARRIVED with the
design — the flow authored no RTL for a reused-IP design — and the gate's own
wiring note says it was made advisory so it would "not block a landing on debt
it did not create". Its FAIL blocked it anyway.

Two independent defects were behind the 11:

  1. THE DENOMINATOR. A per-module unit testbench is a demand on the modules
     THIS RUN AUTHORED. The RTL-staging step already records which modules
     arrived with the design, in `SOURCE_MANIFEST.json.ip_list`; the gate had
     never asked. The exclusion is per MODULE, so a design that mixes staged
     IP with modules it authored keeps every authored module in the
     denominator and cannot silence the gate by staging one vendor file.

  2. A ROLE NAME MATCHED AS A BARE SUBSTRING. The 11th candidate was
     `prim_flop_macros.sv`, credited because "mac" occurs inside "macros".
     `_MUST_TB_NAMES` is a set of module ROLES, and a role is a whole token in
     a module name.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import rtl_unit_test_coverage_check as C  # noqa: E402


FSM_RTL = """
module m;
  localparam S_IDLE = 0;
  localparam S_RUN  = 1;
  reg [1:0] state;
  always @(posedge clk) case (state)
    S_IDLE: state <= S_RUN;
    default: state <= S_IDLE;
  endcase
endmodule
"""


def _tree(tmp_path: Path, mods: dict[str, str],
          manifest: dict | None = None) -> tuple[Path, Path, Path]:
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    sim = proj / "sim_unit"
    rtl.mkdir(parents=True)
    sim.mkdir(parents=True)
    for name, text in mods.items():
        (rtl / name).write_text(text)
    if manifest is not None:
        (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    return proj, rtl, sim


# ── 2. the role token ─────────────────────────────────────────────────────
def test_a_role_name_inside_a_longer_word_is_not_a_role():
    """The measured 11th candidate: "mac" inside "macros"."""
    need, _ = C.needs_tb(Path("prim_flop_macros.sv"))
    assert need is False


def test_a_role_name_that_is_a_whole_token_is_still_a_role():
    """REGRESSION CONTROL. Every module credited by name before is still
    credited — including the multi-token entries."""
    for stem in ("aid_mac.sv", "rx_phy.sv", "aid_rx_phy.sv",
                 "cmd_dispatcher.sv", "ctl_top.sv", "main_fsm.sv"):
        need, reasons = C.needs_tb(Path(stem))
        assert need is True, (stem, reasons)


# ── 1. the denominator ────────────────────────────────────────────────────
def test_a_staged_ip_module_is_not_in_the_denominator(tmp_path):
    proj, rtl, sim = _tree(
        tmp_path, {"aes_control_fsm.sv": FSM_RTL},
        manifest={"reused_ip": True, "ip_list": ["aes_control_fsm"]})
    r = C.check(proj, rtl, sim)
    assert r["pass"] is True, r
    assert r["candidates_total"] == 0
    assert r["reused_ip_modules_not_in_denominator"] == ["aes_control_fsm.sv"]
    # Said out loud, not silently dropped.
    assert "arrived with the design as staged IP" in r["denominator_note"]


def test_a_module_this_run_authored_stays_in_the_denominator(tmp_path):
    """DIRECTIONAL CONTROL. The gate must still be able to refuse, and a
    design cannot silence it by staging ONE vendor file."""
    proj, rtl, sim = _tree(
        tmp_path,
        {"aes_control_fsm.sv": FSM_RTL, "my_ctrl_fsm.sv": FSM_RTL},
        manifest={"reused_ip": True, "ip_list": ["aes_control_fsm"]})
    r = C.check(proj, rtl, sim)
    assert r["pass"] is False, r
    assert r["candidates_total"] == 1
    assert [f["module"] for f in r["findings"]] == ["my_ctrl_fsm.sv"]


def test_no_manifest_excuses_nothing(tmp_path):
    """REGRESSION CONTROL. Every design without a staged-IP manifest is
    byte-unchanged — the exemption cannot fire by absence."""
    proj, rtl, sim = _tree(tmp_path, {"aes_control_fsm.sv": FSM_RTL})
    r = C.check(proj, rtl, sim)
    assert r["pass"] is False
    assert r["candidates_total"] == 1
    assert r["reused_ip_modules_not_in_denominator"] == []


def test_a_manifest_that_does_not_declare_reused_ip_excuses_nothing(tmp_path):
    proj, rtl, sim = _tree(
        tmp_path, {"aes_control_fsm.sv": FSM_RTL},
        manifest={"reused_ip": False, "ip_list": ["aes_control_fsm"]})
    assert C.check(proj, rtl, sim)["candidates_total"] == 1


def test_an_unreadable_manifest_excuses_nothing(tmp_path):
    proj, rtl, sim = _tree(tmp_path, {"aes_control_fsm.sv": FSM_RTL})
    (rtl / "SOURCE_MANIFEST.json").write_text("{not json")
    assert C.check(proj, rtl, sim)["candidates_total"] == 1


def test_a_covered_staged_module_needs_no_special_casing(tmp_path):
    """A design that DOES write a unit TB for a staged module still passes —
    the exemption removes an obligation, it never removes evidence."""
    proj, rtl, sim = _tree(
        tmp_path, {"aes_control_fsm.sv": FSM_RTL},
        manifest={"reused_ip": True, "ip_list": ["aes_control_fsm"]})
    (sim / "tb_aes_control_fsm.v").write_text("// tb\n")
    assert C.check(proj, rtl, sim)["pass"] is True
