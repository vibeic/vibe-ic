#!/usr/bin/env python3
"""A declaration written inside a COMMENT is not a declaration. vibe-ic#731/#1783.

Two scans introduced in PR 1783 read raw text:

    rtl_interface_recover::_parse_one_span::_PORT_KW(header)
    sim_hang_detect::_module_ports_from_z::_MODULE_DECL_RE(code)

`hdl_declaration_scan_strips_comments_check.py` flags the DATAFLOW — that the
string reaching the scan never passed a stripper. These tests pin the
CONSEQUENCE, so the fix cannot be satisfied by renaming a variable: the
commented-out text must not contribute a port or a module that nobody wrote,
and the real declaration standing beside it must still be recovered.

Each case is written so it FAILS on the pre-fix parsers: the commented text and
the real text disagree, and the pre-fix answer is the commented one.

Run: python3 -m pytest -q programs/tests/test_issue1783_declaration_scans_strip_comments.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import rtl_interface_recover as R  # noqa: E402
import sim_hang_detect as H  # noqa: E402


# ─── sim_hang_detect._module_ports_from_z ────────────────────────────────────
_PHANTOM_LINE_COMMENT = (
    "// module ghost_top (ghost_a, ghost_b);\n"
    "module real_top (real_a, real_b);\n"
    "  input real_a;\n"
    "  output real_b;\n"
    "endmodule\n"
)

_PHANTOM_BLOCK_COMMENT = (
    "/* superseded:\n"
    "   module ghost_top (ghost_a, ghost_b);\n"
    "*/\n"
    "module real_top (real_a, real_b);\n"
    "endmodule\n"
)


def test_module_decl_inside_a_line_comment_mints_no_ports():
    """The commented header is FIRST in the text, so a raw scan returns ITS
    ports. Only a de-commented scan reaches the real one."""
    ports = H._module_ports_from_z(_PHANTOM_LINE_COMMENT)
    assert "ghost_a" not in ports and "ghost_b" not in ports, \
        f"commented-out module minted ports: {ports!r}"
    assert ports == ["real_a", "real_b"], ports


def test_module_decl_inside_a_block_comment_mints_no_ports():
    ports = H._module_ports_from_z(_PHANTOM_BLOCK_COMMENT)
    assert "ghost_a" not in ports and "ghost_b" not in ports, \
        f"commented-out module minted ports: {ports!r}"
    assert ports == ["real_a", "real_b"], ports


def test_port_mismatch_signature_does_not_read_a_commented_module():
    """The public consumer of the scan. `real_a` IS declared, in the only
    module that exists; reading the commented header reports it missing."""
    sigs = H._port_mismatch_signatures(_PHANTOM_LINE_COMMENT,
                                       expected_ports=["real_a", "real_b"])
    assert sigs == [], f"real ports reported missing: {sigs!r}"


def test_a_commented_out_module_is_not_the_port_list_that_is_checked():
    """The mirror of the above: a port the commented header DOES list is not
    thereby declared, so requiring it must still be reported missing."""
    sigs = H._port_mismatch_signatures(_PHANTOM_LINE_COMMENT,
                                       expected_ports=["ghost_a"])
    assert len(sigs) == 1 and "ghost_a" in sigs[0], \
        f"a port that exists only in a comment was accepted: {sigs!r}"


# ─── rtl_interface_recover._parse_one_span ───────────────────────────────────
#: A NON-ANSI header (bare name list) carrying a comment that says `input`.
#: `_PORT_KW.search(header)` on the raw text sees that word and takes the ANSI
#: branch, which finds no direction on `a`/`b` and returns NOTHING.
_NONANSI_WITH_INPUT_IN_A_COMMENT = (
    "module dut (\n"
    "  a,   // input strobe, tied high in the bench\n"
    "  b\n"
    ");\n"
    "  input  [3:0] a;\n"
    "  output       b;\n"
    "endmodule\n"
)


def test_the_word_input_in_a_comment_does_not_make_a_header_ansi():
    ports = R._parse_one_span(_NONANSI_WITH_INPUT_IN_A_COMMENT, "dut")
    assert [p["name"] for p in ports] == ["a", "b"], ports
    assert ports[0]["dir"] == "input" and ports[0]["width"] == 4, ports
    assert ports[1]["dir"] == "output" and ports[1]["width"] == 1, ports


#: A comment carrying an unbalanced `)` closes the header early on a raw scan,
#: so `b` is lost entirely.
_ANSI_WITH_PAREN_IN_A_COMMENT = (
    "module dut (\n"
    "  input  wire [7:0] a,  // width chosen in rev 2) see note\n"
    "  output wire       b\n"
    ");\n"
    "endmodule\n"
)


def test_a_paren_inside_a_comment_does_not_truncate_the_header():
    ports = R._parse_one_span(_ANSI_WITH_PAREN_IN_A_COMMENT, "dut")
    assert [p["name"] for p in ports] == ["a", "b"], ports
    assert ports[0]["width"] == 8, ports


def test_a_commented_out_module_header_is_not_the_target_header():
    """`module dut (...)` written inside a comment must not be parsed as the
    declaration of `dut`."""
    span = (
        "// module dut (ghost_a, ghost_b);\n"
        "module dut (\n"
        "  input  wire real_a,\n"
        "  output wire real_b\n"
        ");\n"
        "endmodule\n"
    )
    names = [p["name"] for p in R._parse_one_span(span, "dut")]
    assert "ghost_a" not in names and "ghost_b" not in names, names
    assert names == ["real_a", "real_b"], names
