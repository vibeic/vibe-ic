"""v1.1.60 — waveform_table_conformance_check must SKIP (never block) when the
prompt EXPLICITLY attributes the waveform to a named SUB-module that is not the top
(e.g. 'Module B can be described by the following simulation waveform' while the top
is a structural composition of A/B submodules — Prob131_mt2015_q4). Replaying a
sub-module's table against the top false-blocked a correct design.

§4.05 no-leak: the guard fires ONLY on an explicit 'Module <X> ... waveform' with
X != top; the circuitN family (waveform describes the TOP) is unaffected.
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import waveform_table_conformance_check as w  # noqa: E402

PROMPT_SUBMODULE = """
Module A implements the boolean function z = (x^y) & x.

Module B can be described by the following simulation waveform:

  time  x  y  z
  0ns   0  0  1
  25ns  1  0  0
  35ns  0  1  0
  45ns  1  1  1

Now consider a top-level module with inputs x, y and output z, built from two A
submodules and two B submodules connected through OR/AND/XOR gates.
"""

PROMPT_TOP_CIRCUITN = """
This is a combinational circuit. Read the simulation waveform to determine its
function, then implement it.

  time  a  b  q
  0ns   0  0  0
  5ns   0  1  1
  10ns  1  0  1
  15ns  1  1  0
"""


def test_submodule_attributed_waveform_detected():
    assert w.table_scoped_to_other_module(PROMPT_SUBMODULE, "TopModule") == "B"


def test_topdescribing_waveform_not_scoped_away():  # no-leak
    assert w.table_scoped_to_other_module(PROMPT_TOP_CIRCUITN, "TopModule") is None


def test_top_named_module_is_not_other():
    # a prompt that names the TOP itself before 'waveform' must NOT be scoped away
    p = "Module TopModule can be described by the following waveform:\n time a q\n 0 0 0\n"
    assert w.table_scoped_to_other_module(p, "TopModule") is None
