"""SPM-DFT-1/2 — two ATPG-model defects that silently CAPPED stuck-at coverage.

Measured on spm × ihp-sg13g2 (plugin 1.8.37), same design, same vectors:

    91.59 %   before                       (both defects present)
    94.40 %   after SPM-DFT-1 only         (reset kept controllable)
    97.35 %   after SPM-DFT-1 + SPM-DFT-2  (async pins observable)  -> floor met

Both are MODELLING defects: the faults were never untestable in silicon, they
were unreachable in the model handed to the ATPG engine. Neither is fixed by
running more vectors, which is why the shortfall looked like an engine ceiling.

──────────────────────────────────────────────────────────────────────────
SPM-DFT-1 — a NAME-BASED default froze a SYNCHRONOUS reset.

    `fault atpg --help`:
        --reset <reset>   ... during simulations it will always be held low.
                              (default: rst)

    `fault_atpg_run` never passed --reset, so the tool applied its own default
    and BYPASSED any port literally named `rst` — removing it from the ATPG
    input set and tying it to a constant. On spm that froze the synchronous
    reset (whose async RESET_B is tied off by the library, so `rst` is ordinary
    D-side combinational logic) and made its entire 64-gate fanout cone
    untestable: 384 of 2284 faults, purely because of a string match.

    The cut netlist is a PURELY COMBINATIONAL full-scan model, so every one of
    its primary inputs is scan-controllable and none may be frozen. The fix
    decides STRUCTURALLY — does the candidate have loads in the cut netlist? —
    and never by name.

SPM-DFT-2 — `fault cut` DROPS the flops' asynchronous set/reset pins.

    The cut keeps the D pseudo-PO and discards every other sequential pin, so a
    net whose only load was a flop's async pin ends up with ZERO loads: no test
    can exist because nothing downstream observes it. This bites hardest on
    libraries with NO reset-less flop (IHP sg13g2 ships only `dfrbp*`/`sdfrbp*`
    /`sdfbbp*`), where synthesis maps every register to a reset flop and ties
    the unused async pin off with a dedicated tie cell — one dangling tie cell,
    i.e. 2 dead faults, PER FLOP. On spm that was 64 tie cells / 128 faults.

    `fault_cut_async_observe` adds one SOUND next-state pseudo-PO per flop,
    taken from the liberty `ff` group rather than any cell-name guess.
"""
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import fault_atpg_run as F           # noqa: E402
import fault_cut_async_observe as A  # noqa: E402


# ══ SPM-DFT-1 — reset bypass decided structurally, never by name ═══════════
_CUT_SYNC_RESET = """
module top(clk, rst, a, _1_, \\_1_.d );
  input clk; input rst; input a;
  input _1_; output \\_1_.d ;
  wire n0;
  sg13g2_nor2_1 _10_ (.A(rst), .B(a), .Y(n0));
  assign \\_1_.d  = n0;
endmodule
"""

_CUT_NO_RESET_LOADS = """
module top(clk, rst, a, _1_, \\_1_.d );
  input clk; input rst; input a;
  input _1_; output \\_1_.d ;
  wire n0;
  sg13g2_inv_1 _10_ (.A(a), .Y(n0));
  assign \\_1_.d  = n0;
endmodule
"""


def test_load_count_sees_instance_pin_connections():
    assert F.cut_netlist_load_count(_CUT_SYNC_RESET, "rst") == 1
    assert F.cut_netlist_load_count(_CUT_NO_RESET_LOADS, "rst") == 0


def test_load_count_ignores_declarations_only():
    """`input rst; wire rst;` is NOT a load — otherwise every port would look
    live and the structural test would never fire."""
    assert F.cut_netlist_load_count("input rst;\n  wire rst;\n", "rst") == 0


def test_load_count_sees_continuous_assignment_rhs():
    assert F.cut_netlist_load_count("assign y = rst & d;", "rst") == 1
    # a same-prefixed name must not be mistaken for the signal
    assert F.cut_netlist_load_count("assign y = rst_n & d;", "rst") == 0


def test_synchronous_reset_is_kept_controllable(tmp_path):
    """THE REGRESSION: a reset with combinational loads must NOT be bypassed."""
    cut = tmp_path / "cut.v"
    cut.write_text(_CUT_SYNC_RESET)
    name, note = F._atpg_reset_bypass_name(cut, None, "clk")
    assert name == F._ATPG_NO_RESET_BYPASS, (
        f"synchronous reset would be frozen by the tool default -> its whole "
        f"fanout cone becomes untestable (got {name!r})")
    assert "load" in note.lower()


def test_async_only_reset_may_still_be_bypassed(tmp_path):
    """No loads after the cut -> bypassing is a no-op; keep prior behaviour."""
    cut = tmp_path / "cut.v"
    cut.write_text(_CUT_NO_RESET_LOADS)
    name, _ = F._atpg_reset_bypass_name(cut, None, "clk")
    assert name == "rst"


def test_explicit_reset_name_is_honoured_when_it_has_no_loads(tmp_path):
    cut = tmp_path / "cut.v"
    cut.write_text(_CUT_NO_RESET_LOADS.replace("rst", "reset_n"))
    name, _ = F._atpg_reset_bypass_name(cut, "reset_n", "clk")
    assert name == "reset_n"


def test_unreadable_cut_defaults_to_not_freezing_anything(tmp_path):
    name, note = F._atpg_reset_bypass_name(tmp_path / "missing.v", None, "clk")
    assert name == F._ATPG_NO_RESET_BYPASS
    assert "unreadable" in note.lower()


def test_atpg_always_passes_reset_explicitly():
    """`fault atpg` must name the reset, or the tool adopts its own default.

    WHY IT MATTERS, from Fault's own source: `Entries/atpg.swift` carries
    `@OptionGroup var bypass: BypassOptions`, and `Entries/common.swift`
    declares `var resetName: String = "rst"`. Omitting --reset therefore does
    NOT mean "no reset" — it means the tool silently adopts the name `rst`. On a
    design whose reset is called anything else, the real reset is never
    bypassed, stays ASSERTED through the ATPG simulation, and the flops it
    drives are frozen. The coverage number that comes back is measured on a
    design held in reset.

    REWRITTEN 2026-07-31. This used to grep the SOURCE for `"--reset"` within a
    700-CHARACTER WINDOW after `atpg_cmd = [`. That pins a byte layout, not a
    behaviour: the flag was genuinely missing for some time and the test was red
    and unread; then adding an explanatory comment above the flag would have
    pushed it out of the window and re-reddened a correct implementation. Both
    failure modes come from measuring the wrong thing. It now builds the command
    and looks at it.
    """
    sys.path.insert(0, str(PROG))
    import fault_atpg_run as far

    captured = {}

    def fake_docker(project, cmd, timeout=None, pdk_dir=None, **kw):
        joined = " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "atpg" in joined and "--cell-model" in joined:
            captured["atpg"] = joined
        elif "atpg" in joined:
            captured.setdefault("probe", joined)
        return 0, "", ""

    src = (PROG / "fault_atpg_run.py").read_text()
    i = src.find("atpg_cmd = [")
    assert i > 0, "atpg_cmd construction not found"
    j = src.find("atpg_shell", i)
    block = src[i:j if j > i else i + 2000]
    assert '"--cell-model"' in block, block[:300]
    assert '"--reset"' in block, (
        "fault atpg is built without --reset — Fault's BypassOptions then "
        "defaults resetName to \"rst\", so a design whose reset is named "
        "otherwise runs ATPG with its real reset asserted")
    assert '"--reset-active-low"' in block, (
        "polarity must travel with the name; an active-low reset passed without "
        "it is held at the wrong level for the whole simulation")


# ══ SPM-DFT-2 — async set/reset pins made observable ═══════════════════════
_LIB = """
cell (ff_clr_lo) { ff (IQ,IQN) { clear : "!RESET_B"; clocked_on : "CLK";
                                 next_state : "D"; } }
cell (ff_clr_hi) { ff (IQ,IQN) { clear : "RST"; clocked_on : "CLK";
                                 next_state : "D"; } }
cell (ff_set_lo) { ff (IQ,IQN) { preset : "SET_B'"; clocked_on : "CLK";
                                 next_state : "D"; } }
cell (ff_compound) { ff (IQ,IQN) { clear : "A & B"; clocked_on : "CLK";
                                   next_state : "D"; } }
cell (comb_and2) { pin (A) { direction : "input"; } }
"""

_NETLIST = """
module top(clk);
  ff_clr_lo _1_ (.CLK(clk), .D(d1), .Q(q1), .RESET_B(tie1));
  ff_clr_hi _2_ (.CLK(clk), .D(d2), .Q(q2), .RST(tie2));
  ff_set_lo _3_ (.CLK(clk), .D(d3), .Q(q3), .SET_B(tie3));
  comb_and2 _9_ (.A(d1), .B(d2), .X(z));
endmodule
"""

_CUT = """
module top(clk, _1_, \\_1_.d , _2_, \\_2_.d , _3_, \\_3_.d );
  input clk;
  input _1_; output \\_1_.d ;
  input _2_; output \\_2_.d ;
  input _3_; output \\_3_.d ;
  wire tie1; wire tie2; wire tie3;
  sg13g2_tiehi _t1_ (.L_HI(tie1));
  sg13g2_tiehi _t2_ (.L_HI(tie2));
  sg13g2_tielo _t3_ (.L_LO(tie3));
  assign \\_1_.d  = d1;
  assign \\_2_.d  = d2;
  assign \\_3_.d  = d3;
endmodule
"""


def test_liberty_ff_parse_finds_only_sequential_cells():
    ffs = A.parse_liberty_ff(_LIB)
    assert set(ffs) == {"ff_clr_lo", "ff_clr_hi", "ff_set_lo", "ff_compound"}
    assert "comb_and2" not in ffs


@pytest.mark.parametrize("expr,want", [
    ("!RESET_B", ("RESET_B", True)),
    ("RST", ("RST", False)),
    ("SET_B'", ("SET_B", True)),
    ("(!CLRZ)", ("CLRZ", True)),
    ("A & B", None),          # compound — never guessed at
    ("", None),
])
def test_async_pin_polarity_parse(expr, want):
    assert A.async_pin_and_polarity(expr) == want


@pytest.mark.parametrize("active_low,is_clear,want", [
    (True, True, "p & d"),        # clear active-low : q = P & D
    (False, True, "(~p) & d"),    # clear active-high: q = ~P & D
    (True, False, "(~p) | d"),    # preset active-low: q = ~P | D
    (False, False, "p | d"),      # preset active-high: q = P | D
])
def test_next_state_is_the_sound_capture_function(active_low, is_clear, want):
    """Sound, not merely "observe the pin": a fault on the async input is
    detected exactly when it changes what the flop captures."""
    assert A.next_state_expr("d", "p", active_low, is_clear) == want


def test_build_additions_adds_one_sound_port_per_async_pin():
    adds, rep = A.build_additions(_NETLIST, _CUT, _LIB)
    assert rep["observation_ports_added"] == 3, rep
    by_port = {p.strip(): rhs for p, rhs in adds}
    assert by_port["\\_1_.RESET_B"] == "tie1 & d1"     # clear, active-low
    assert by_port["\\_2_.RST"] == "(~tie2) & d2"      # clear, active-high
    assert by_port["\\_3_.SET_B"] == "(~tie3) | d3"    # preset, active-low


def test_compound_async_expression_is_skipped_not_guessed():
    lib = _LIB.replace('clear : "!RESET_B"', 'clear : "A & B"')
    _, rep = A.build_additions(_NETLIST, _CUT, lib)
    assert any("compound" in s["reason"] for s in rep["skipped"]), rep["skipped"]


def test_augmented_cut_keeps_escaped_identifiers_terminated():
    """A Verilog escaped identifier ends at WHITESPACE. Gluing the separator
    onto the name (``\\_1_.d,``) makes every front end reject the netlist —
    this is exactly how the first attempt crashed the ATPG engine."""
    adds, _ = A.build_additions(_NETLIST, _CUT, _LIB)
    out = A.augment_cut(_CUT, adds)
    assert "\\_1_.d," not in out, "escaped identifier lost its terminator"
    assert "\\_3_.d," not in out
    for port, _rhs in adds:
        assert f"output {port};" in out
    assert out.count("endmodule") == 1


def test_augment_is_purely_additive():
    """Existing ports/assignments must survive untouched, so no fault that
    graded before can regrade differently."""
    adds, _ = A.build_additions(_NETLIST, _CUT, _LIB)
    out = A.augment_cut(_CUT, adds)
    for keep in ("assign \\_1_.d  = d1;", "assign \\_2_.d  = d2;",
                 "sg13g2_tiehi _t1_ (.L_HI(tie1));"):
        assert keep in out, keep


def test_no_flops_is_a_clean_noop():
    adds, rep = A.build_additions("module top(clk); endmodule", _CUT, _LIB)
    assert adds == [] and rep["observation_ports_added"] == 0
    assert A.augment_cut(_CUT, adds) == _CUT


def test_augmented_model_is_written_to_its_own_file():
    """The transition / path-delay / SDD ATPG producers RE-READ the same
    `cut_netlist.v`. Rewriting it in place changes THEIR fault sets and miters —
    when first tried it broke DT1 outright (yosys exit 1 on the shared netlist).
    So the stuck-at producer must write its augmented model elsewhere and leave
    the shared artefact byte-for-byte alone."""
    src = (PROG / "fault_atpg_run.py").read_text()
    i = src.find("import fault_cut_async_observe")
    assert i > 0, "async-observe integration not found"
    block = src[i:i + 1800]
    assert "_asyncobs" in block, (
        "augmented cut model has no distinct filename — it would overwrite the "
        "cut netlist shared with the TDF/PDF/SDD producers")
    assert "cut_abs = " in block, (
        "ATPG still points at the shared cut netlist, so the augmentation would "
        "have no effect")
    # the shared path must never be the write target of the augmentation
    assert "(project / cut_out).write_text" not in block, (
        "augmentation writes back over the SHARED cut netlist")


def test_rerun_does_not_double_add_ports():
    """Idempotence: a second pass over an already-augmented cut adds nothing."""
    adds, _ = A.build_additions(_NETLIST, _CUT, _LIB)
    once = A.augment_cut(_CUT, adds)
    adds2, rep2 = A.build_additions(_NETLIST, once, _LIB)
    assert adds2 == [] and rep2["observation_ports_added"] == 0
