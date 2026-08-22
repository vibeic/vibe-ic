#!/usr/bin/env python3
"""ORGANIC #410 — an unattributed netlist must not be handed another PDK's
cell model.

The ATPG step sniffs the netlist head to pick a PDK. An IHP-mapped netlist
names its cells `sg13g2_*`, which matched none of the branches, so the flag
was OMITTED — and `fault_atpg_run`'s own default then resolved a DIFFERENT
library's Verilog cell model while the caller's artefact recorded
`generic_unmapped`. Neither the PDK the design was built on nor the one
actually used appeared anywhere: #389's sentence reached through a second
table.

CORRECTION TO THE REPORT, measured here: `fault_atpg_run.PDK_CONFIG` has
carried an `ihp-sg13g2` entry all along (17 references in that file). The
issue's table said its keys were only `gf180` / `sky130`. The support existed;
only the sniff could not reach it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import fault_atpg_run as F  # noqa: E402

_RUNNER = (_PROGRAMS / "design_one_shot_runner.py").read_text()


def _sniff(head: str) -> str:
    """Call the SHIPPED sniff. This used to RE-IMPLEMENT the runner's branch
    chain inside the test, under a docstring claiming it was "read out of its
    source so this test cannot drift from what actually ships" — it was not
    read out of the source, it was a hand-copied duplicate, so every test
    below would have passed with the real sniff deleted entirely. A control
    that cannot fail when the thing it guards is removed is not a control."""
    import tempfile
    import design_one_shot_runner as _R
    d = Path(tempfile.mkdtemp())
    (d / "n.v").write_text(head)
    return _R._dft_atpg_sniff_pdk(d, "n.v")[1]

def test_the_ihp_branch_is_in_the_shipped_sniff():
    """EXPECTATION CHANGED, deliberately, and this is the record of it.

    This used to assert a REGEX LITERAL was present in the runner's source:
        assert r'\\bsg13g2_[a-z0-9_]+\\b' in _RUNNER
    That pins an IMPLEMENTATION, not the property #410 is about. The sniff no
    longer carries a hand-written branch per PDK; it derives the libraries
    from `fault_atpg_run.PDK_CONFIG` and scans the WHOLE netlist — which is
    what this file's own docstring already said was right: "the support
    existed; only the sniff could not reach it". #410 answered that by adding
    a row to the second table; deriving from the config deletes the table.

    So this now asserts the PROPERTY: an IHP netlist resolves to a supported
    entry, wherever in the file its cells appear. It fails if IHP support
    regresses, and it does NOT fail merely because the code was rewritten."""
    assert _sniff("module t; sg13g2_dfrbp_1 u1(.D(d));") == "ihp-sg13g2"
    # ...and at an offset the old 20 KB head could never have reached.
    late = ("module t;\n" + "  MY_MACRO u(.a(x));\n" * 12000
            + "  sg13g2_dfrbp_1 ff(.D(d));\nendmodule\n")
    assert len(late) > 200_000
    assert _sniff(late) == "ihp-sg13g2"


def test_an_ihp_netlist_resolves_to_a_supported_entry():
    pdk = _sniff("module t; sg13g2_dfrbp_1 u1(.D(d)); sg13g2_inv_1 u2(.A(a));")
    assert pdk == "ihp-sg13g2"
    assert pdk in F.PDK_CONFIG, "the entry existed all along; only the sniff " \
                                "could not reach it"


def test_the_existing_branches_are_unchanged():
    """The paired half: a sniff that answered ihp for everything would pass
    the case above and break every other design."""
    assert _sniff("module t; sky130_fd_sc_hd__dfxtp_1 u1(.D(d));") == "sky130"
    assert _sniff("module t; gf180mcu_fd_sc_mcu7t5v0__dffq_1 u1();") == "gf180"


def test_an_unattributed_netlist_stays_unattributed():
    assert _sniff("module t; foo_cell u1(.A(a));") == ""


def test_the_runner_never_omits_the_pdk_flag_now():
    """Omitting it is what let the callee substitute. It now says `unmapped`
    explicitly, which is not a PDK, so the engine refuses instead of
    guessing."""
    assert 'cmd += ["--pdk", "unmapped"]' in _RUNNER


def test_unmapped_is_not_a_pdk_so_the_engine_refuses():
    assert "unmapped" not in F.PDK_CONFIG


def test_the_default_is_no_longer_a_real_pdk():
    """The defect itself: `default=(COMMERCIAL_PDK_ID or "sky130")` meant a
    caller who could not attribute its netlist silently got a real library."""
    src = (_PROGRAMS / "fault_atpg_run.py").read_text()
    assert 'default=(_cpdk.COMMERCIAL_PDK_ID or "sky130")' not in src
    assert 'p.add_argument("--pdk", default="unmapped"' in src


def test_an_unsupported_pdk_returns_rc2_with_the_supported_list():
    """A refusal must NAME what is supported, or the caller cannot act on it.

    Checked on every live emission site, with comments and docstrings removed
    first. This used to take `src.index("unsupported pdk:")` — the FIRST
    occurrence anywhere in the file — and a later change that merely QUOTED the
    old message in a comment moved that index onto the quotation and broke the
    test while the invariant still held. A guard that matches its subject being
    discussed is the defect it exists to catch, and this repo has now fixed
    three of those; this is the third.
    """
    import io
    import tokenize

    raw = (_PROGRAMS / "fault_atpg_run.py").read_text()
    # Strip comments; keep strings, since the message itself IS a string.
    out, prev_end = [], (1, 0)
    for tok in tokenize.generate_tokens(io.StringIO(raw).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.start[0] > prev_end[0]:
            out.append("\n" * (tok.start[0] - prev_end[0]))
        out.append(tok.string)
        prev_end = tok.end
    code = "".join(out)

    sites = [i for i in range(len(code))
             if code.startswith("unsupported pdk:", i)]
    assert sites, "the refusal message is gone — did it stop naming the case?"
    for i in sites:
        window = code[i:i + 300]
        assert "Supported:" in window and "PDK_CONFIG.keys()" in window, (
            f"an 'unsupported pdk:' refusal at offset {i} does not name the "
            f"supported set: {window[:160]!r}")
