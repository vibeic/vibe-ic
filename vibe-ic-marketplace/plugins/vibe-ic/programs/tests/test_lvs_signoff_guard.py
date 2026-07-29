"""Tests for lvs_signoff_guard — the defensive gate against a SILENT FALSE-POSITIVE LVS.

Pins the v0.2.1 capture (session-review §5): a netgen "match" against a PORTLESS extracted
top .subckt is vacuous and must RAISE, never silently pass. Chip-agnostic SPICE parse.
"""
import pytest

from lvs_signoff_guard import (
    subckt_ports,
    has_top_level_ports,
    verdict_claims_match,
    assert_lvs_trustworthy,
    PortlessExtractionError,
)

PORTED = """\
* extracted layout
.subckt widget clk rst_n din[0] din[1] dout
M0 dout din[0] VPWR VPWR sky130_fd_pr__pfet_01v8_hvt
.ends
"""

PORTLESS = """\
* magic flat extraction with no promoted labels
.subckt widget
M0 a_123# a_456# VGND VGND sky130_fd_pr__nfet_01v8
.ends
"""

CONTINUATION = """\
.subckt big_top clk rst
+ a b c
+ d e f
M0 a b c d sky130_fd_pr__nfet_01v8
.ends
"""

NO_SUBCKT = """\
* just a flat device dump, no subckt at all
M0 n1 n2 n3 n4 sky130_fd_pr__nfet_01v8
"""


# --------------------------------------------------------------- subckt_ports
def test_ported_subckt_returns_ports():
    assert subckt_ports(PORTED) == ["clk", "rst_n", "din[0]", "din[1]", "dout"]


def test_portless_subckt_returns_empty_list_not_none():
    assert subckt_ports(PORTLESS) == []          # exists but no ports
    assert subckt_ports(NO_SUBCKT) is None        # no subckt at all


def test_named_top_selection_and_case_insensitivity():
    assert subckt_ports(PORTED, top="widget") == ["clk", "rst_n", "din[0]", "din[1]", "dout"]
    assert subckt_ports(PORTED, top="WIDGET") == ["clk", "rst_n", "din[0]", "din[1]", "dout"]
    assert subckt_ports(PORTED, top="nonexistent") is None


def test_line_continuation_splices_ports():
    assert subckt_ports(CONTINUATION) == ["clk", "rst", "a", "b", "c", "d", "e", "f"]


def test_params_tail_not_counted_as_ports():
    txt = ".subckt cell a b c params: w=1 l=2\n.ends\n"
    assert subckt_ports(txt) == ["a", "b", "c"]
    txt2 = ".subckt cell a b M=2\n.ends\n"
    assert subckt_ports(txt2) == ["a", "b"]


def test_comment_and_blank_lines_ignored():
    txt = "*comment\n\n.subckt c x y\n*mid comment\n.ends\n"
    assert subckt_ports(txt) == ["x", "y"]


# ----------------------------------------------------------- has_top_level_ports
def test_has_top_level_ports():
    assert has_top_level_ports(PORTED) is True
    assert has_top_level_ports(PORTLESS) is False
    assert has_top_level_ports(NO_SUBCKT) is False


# ------------------------------------------------------------ verdict_claims_match
def test_verdict_phrases():
    assert verdict_claims_match("Circuits match uniquely.") is True
    assert verdict_claims_match("Netlists match uniquely") is True
    assert verdict_claims_match("Final result: Top level cell failed pin matching.") is False
    assert verdict_claims_match("") is False


# --------------------------------------------------- assert_lvs_trustworthy (the gate)
def test_ported_extraction_is_trustworthy():
    ports = assert_lvs_trustworthy(PORTED, verdict_text="Circuits match uniquely.")
    assert ports == ["clk", "rst_n", "din[0]", "din[1]", "dout"]


def test_portless_match_raises_silent_false_positive_defense():
    # the core defense: portless extraction + a "match" claim => RAISE
    with pytest.raises(PortlessExtractionError):
        assert_lvs_trustworthy(PORTLESS, verdict_text="Circuits match uniquely.")


def test_portless_without_verdict_raises_by_default():
    # no verdict given => assume a match could be claimed => guard trips
    with pytest.raises(PortlessExtractionError):
        assert_lvs_trustworthy(PORTLESS)


def test_portless_but_already_failed_does_not_raise():
    # an honest FAIL on a portless extraction needs no extra guard (not a false positive)
    ports = assert_lvs_trustworthy(
        PORTLESS, verdict_text="Final result: Top level cell failed pin matching.")
    assert ports == []


def test_missing_subckt_always_raises():
    with pytest.raises(PortlessExtractionError):
        assert_lvs_trustworthy(NO_SUBCKT, verdict_text="Circuits match uniquely.")
    with pytest.raises(PortlessExtractionError):
        assert_lvs_trustworthy(NO_SUBCKT)


def test_error_message_is_actionable():
    try:
        assert_lvs_trustworthy(PORTLESS)
    except PortlessExtractionError as e:
        msg = str(e)
        assert "PORTLESS" in msg
        assert "port makeall" in msg          # points to the canonical fix
        assert "magic_port_extract_emit" in msg or "lvs_def_port_seed" in msg


# --- the exit code is what the caller reads, and no test drove main()

def test_main_exits_non_zero_on_a_portless_extraction(tmp_path):
    """`gate_cli_mutation_probe` reported this guard SILENT.

    The tests above call `assert_lvs_trustworthy()` and assert the exception;
    the caller reads the EXIT CODE, and nothing exercised `main()`'s mapping —
    so the guard could have started exiting 0 on a portless extraction, which
    is the one thing it exists to stop.

    Driven by real SPICE and a real verdict file rather than stubs: the guard's
    whole subject is what those two say.
    """
    import lvs_signoff_guard as L
    sp = tmp_path / "layout.spice"
    sp.write_text(".subckt top\nM1 a b c d nfet\n.ends\n")
    vf = tmp_path / "netgen.log"
    vf.write_text("Circuits match uniquely.\n")
    assert L.main(["--spice", str(sp), "--verdict-file", str(vf)]) == 1


def test_main_exits_zero_when_the_top_has_ports(tmp_path):
    """The other direction, or the test above is met by always failing."""
    import lvs_signoff_guard as L
    sp = tmp_path / "layout.spice"
    sp.write_text(".subckt top vdd vss in out\nM1 a b c d nfet\n.ends\n")
    vf = tmp_path / "netgen.log"
    vf.write_text("Circuits match uniquely.\n")
    assert L.main(["--spice", str(sp), "--verdict-file", str(vf)]) == 0


def test_main_refuses_on_a_missing_netlist(tmp_path):
    """rc 2 — could not ask, which is not a pass."""
    import lvs_signoff_guard as L
    assert L.main(["--spice", str(tmp_path / "nope.spice")]) == 2
