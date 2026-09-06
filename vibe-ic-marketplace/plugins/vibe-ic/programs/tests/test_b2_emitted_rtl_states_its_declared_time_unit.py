"""#2053, emitter half: an emitted candidate states the time unit its input
declares, and REFUSES BY NAME when nothing declares one.

MEASURED (lane brtllm, 2026-09-06, finding BR-08) on a frozen clkgenerator
candidate against its own frozen challenge, same two files both times:

    candidate first, challenge second -> FAIL ("first rising edge at time
                                         705032704, expected 5")
    challenge first, candidate second -> PASS
    candidate first + a `timescale prepended to a byte-identical COPY -> PASS

A Verilog file with no `timescale has no time unit of its own; it inherits the
unit of whatever source the simulator compiled first. The harness charged that
to the design. The fix belongs at the emitter — but a unit may never be
invented, because a guessed `1ns/1ps` silently redefines every delay in the file.
So the emitter states the unit the DESIGN INPUT declares, and otherwise leaves
the text byte-identical and says NO_DECLARED_TIME_UNIT by name.
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import rtl_timescale_stamp as T  # noqa: E402

RTL = "module dut(input clk); endmodule\n"


def _project(tmp_path, prompt):
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "phase1_prompt.md").write_text(prompt)
    return proj


def test_a_declared_unit_is_stated_on_the_emitted_rtl(tmp_path):
    proj = _project(tmp_path, "Implement a divider.\n`timescale 1ns/1ps\nGive me code.")
    res = T.stamp_rtl(RTL, proj)
    assert res["reason"] == T.DECLARED_IN_INPUT
    assert res["timescale"] == "1ns/1ps"
    assert str(res["rtl"]).startswith("`timescale 1ns/1ps\n")
    assert str(res["rtl"]).endswith(RTL)          # the design text is untouched
    assert res["source"].endswith("phase1_prompt.md")
    assert T.refusal_sentence(res) is None


def test_a_declared_unit_other_than_the_common_one_is_carried_verbatim(tmp_path):
    proj = _project(tmp_path, "`timescale 10ps / 1ps\nImplement a PLL divider.")
    res = T.stamp_rtl(RTL, proj)
    assert res["timescale"] == "10ps/1ps"
    assert str(res["rtl"]).startswith("`timescale 10ps/1ps\n")


def test_no_declared_unit_leaves_the_rtl_byte_identical_and_refuses_by_name(tmp_path):
    # The control the whole design rests on: with nothing declared, the emitted
    # text must not change at all, and the reason must be NAMED rather than a
    # silent pass or an invented 1ns/1ps.
    proj = _project(tmp_path, "Implement a clock generator with PERIOD = 10.")
    res = T.stamp_rtl(RTL, proj)
    assert res["reason"] == T.NO_DECLARED_TIME_UNIT
    assert res["rtl"] == RTL
    assert res["timescale"] is None
    sentence = T.refusal_sentence(res)
    assert sentence and sentence.startswith("NO_DECLARED_TIME_UNIT:")
    assert "may be invented" in sentence
    assert res["searched"], "a refusal must name what it searched"


def test_rtl_that_already_declares_its_unit_is_not_stamped_twice(tmp_path):
    proj = _project(tmp_path, "`timescale 1ns/1ps\nImplement a divider.")
    already = "`timescale 1us/1ns\n" + RTL
    res = T.stamp_rtl(already, proj)
    assert res["reason"] == T.ALREADY_DECLARED
    assert res["rtl"] == already          # the file's own unit wins, untouched
    assert res["timescale"] == "1us/1ns"


def test_a_period_is_not_a_time_unit(tmp_path):
    # §4.05 no-leak: "10ns" is a PERIOD. Reading it as a unit/precision pair
    # would be inventing what the design means, so it must not be stamped.
    proj = _project(tmp_path, "The clock period is 10ns and the output toggles "
                              "every 5 ns. PERIOD = 10.")
    res = T.stamp_rtl(RTL, proj)
    assert res["reason"] == T.NO_DECLARED_TIME_UNIT
    assert res["rtl"] == RTL


def test_the_search_never_opens_a_testbench_tree(tmp_path):
    # §4.05: the design INPUT only. A `timescale sitting in a sim/ or testbench
    # tree must NOT be adopted, or the emitter would be reading the harness.
    proj = _project(tmp_path, "Implement a divider.")
    for rel in ("phase2/stage1/sim", "phase2/stage1/sim_full_stack", "tb"):
        d = proj / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "tb.v").write_text("`timescale 1ns/1ns\nmodule tb; endmodule\n")
    res = T.stamp_rtl(RTL, proj)
    assert res["reason"] == T.NO_DECLARED_TIME_UNIT, res
    assert res["rtl"] == RTL
    assert not any("sim" in s or "/tb" in s for s in res["searched"]), res["searched"]


def test_the_runner_publishes_the_decision_by_name(tmp_path):
    import design_one_shot_runner as R
    proj = _project(tmp_path, "Implement a clock generator.")
    out = R._stamp_declared_timescale(proj, RTL)
    assert out == RTL
    assert R._LAST_TIMESCALE_DECISION["reason"] == T.NO_DECLARED_TIME_UNIT
    assert R._LAST_TIMESCALE_DECISION["refusal"].startswith("NO_DECLARED_TIME_UNIT:")
    proj2 = _project(tmp_path / "b", "`timescale 1ns/1ps\nImplement a divider.")
    out2 = R._stamp_declared_timescale(proj2, RTL)
    assert out2.startswith("`timescale 1ns/1ps\n")
    assert R._LAST_TIMESCALE_DECISION["reason"] == T.DECLARED_IN_INPUT


def test_the_publisher_itself_stamps_what_it_writes(tmp_path):
    """The WIRING test. Every deterministic emit goes through one publisher, so
    the stamp is applied there; a test that only calls the helper would stay
    green with the call site deleted."""
    import _path_layout as _pl
    import design_one_shot_runner as R
    proj = _project(tmp_path, "`timescale 1ns/1ps\nImplement a divider.")
    rtl_dir = _pl.rtl_dir(proj)
    rtl_dir.mkdir(parents=True, exist_ok=True)
    out = rtl_dir / "dut.v"
    pub = R._publish_phase1_rtl_no_clobber(proj, out, RTL)
    try:
        pub.require_current_chain()
    finally:
        close = getattr(pub, "close", None)
        if callable(close):
            close()
    written = out.read_text()
    assert written.startswith("`timescale 1ns/1ps\n"), written[:80]
    assert written.endswith(RTL)


def test_the_publisher_writes_an_undeclared_design_byte_identically(tmp_path):
    import _path_layout as _pl
    import design_one_shot_runner as R
    proj = _project(tmp_path, "Implement a clock generator with PERIOD = 10.")
    rtl_dir = _pl.rtl_dir(proj)
    rtl_dir.mkdir(parents=True, exist_ok=True)
    out = rtl_dir / "dut.v"
    pub = R._publish_phase1_rtl_no_clobber(proj, out, RTL)
    try:
        pub.require_current_chain()
    finally:
        close = getattr(pub, "close", None)
        if callable(close):
            close()
    assert out.read_text() == RTL
    assert R._LAST_TIMESCALE_DECISION["reason"] == T.NO_DECLARED_TIME_UNIT
