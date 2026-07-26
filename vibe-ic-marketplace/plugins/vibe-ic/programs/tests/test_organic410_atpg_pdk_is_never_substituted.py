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
    """The runner's own branch chain, read out of its source so this test
    cannot drift from what actually ships."""
    import _commercial_pdk as _cpdk
    if "sky130_fd_sc_hd__" in head:
        return "sky130"
    if "gf180mcu" in head:
        return "gf180"
    if re.search(r"\bsg13g2_[a-z0-9_]+\b", head):
        return "ihp-sg13g2"
    if re.search(r"\bDFFHQD\d|\bAOI211D1\b", head):
        return _cpdk.COMMERCIAL_PDK_ID
    return ""


def test_the_ihp_branch_is_in_the_shipped_sniff():
    assert r'\bsg13g2_[a-z0-9_]+\b' in _RUNNER


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
    src = (_PROGRAMS / "fault_atpg_run.py").read_text()
    i = src.index("unsupported pdk:")
    window = src[i:i + 300]
    assert "Supported:" in window and "PDK_CONFIG.keys()" in window
