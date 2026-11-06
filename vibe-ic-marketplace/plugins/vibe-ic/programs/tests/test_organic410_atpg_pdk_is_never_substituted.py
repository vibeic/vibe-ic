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
