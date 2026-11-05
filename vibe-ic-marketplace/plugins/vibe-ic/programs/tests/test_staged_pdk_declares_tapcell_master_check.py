"""Tests for staged_pdk_declares_tapcell_master_check.py — the guard that a
load-bearing sentinel default may not be INHERITED.

THE LOAD-BEARING ARMS ARE THE ONES THAT MAKE IT NOT-GREEN. A guard that cannot
fail is not a guard, and one that fires in both directions is worse than none:
every arm that asserts a PASS is paired with an arm that asserts a FAIL or a
REFUSAL on the same fixture, one edit apart.

An rc is not a verdict. `rc 1` is also what a Python traceback exits with and
`rc 2` is what argparse exits with, so every non-zero arm asserts the LINE that
names the site as well, through `_assert_is_a_finding_not_a_crash` /
`_assert_is_a_refusal_not_a_crash`.

THREE ARMS EXIST BECAUSE THIS CLASS OF GUARD HAS FAILED BEFORE
  * a comment / a string literal naming the field must not buy a PASS, and a
    comment-only edit must not trip the gate either — a grep-shaped rule is
    satisfiable by prose, in both directions;
  * the guard ships INTO the directory it scans and its own docstring names the
    contracted class, so a gate that found itself would FAIL the day it landed;
  * scanning nothing and finding nothing is what a wrong root looks like, and
    must not be reported the way a clean sweep is.

AND FOUR ARE THE BUY-GREEN AUDIT, PINNED
  * `C(**d)`, `C(*a)` and `C(x, ...)` are CANNOT-CHECK, never PASS: each is a
    one-token edit to a guarded call that leaves the omission exactly where it
    was, so rc 0 over any of them would be a gate you switch off by typing two
    braces;
  * `PdkConfig = None` in dead code must not cancel the rule — an alias can be
    rebound out of the set, the class's own name never can.

The fixtures are REAL MODULES, not snippets: module docstring, `__future__`
import, a dataclass with many fields, a resolver with branches and an early
`return None`, comments interleaved through a call that spans many lines. The
site this gate was written for carries 34 keyword arguments over 50-odd lines.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_GUARD = _PROGRAMS / "staged_pdk_declares_tapcell_master_check.py"

sys.path.insert(0, str(_PROGRAMS))





_CLS = "PdkConfig"
_FIELD = "tapcell_master"

_HEADER = '''"""A resolver module, in the shape the real one has.

Docstring, imports, a dataclass, a function with branches. The contracted
field is named right here in prose — which must change nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PdkConfig:
    name: str
    liberty: str
    tech_lef: str
    cell_lef: str
    site: str
    metal_prefix: str = "met"
    tapcell_master: Optional[str] = None
    tapcell_distance_um: float = 14.0
    antenna_diode_cell: Optional[str] = None
    macro_lefs: List[str] = field(default_factory=list)


def _derive(_src):
    """Ask the library itself; returns (value, why)."""
    return None, "NONE: nothing declared it"
'''

_REGISTRY_SITE = '''

def _from_registry(reg) -> Optional[PdkConfig]:
    if not reg:
        return None
    tap, _why = _derive(reg)
    return PdkConfig(
        name=reg["name"],
        liberty=reg["liberty"],
        tech_lef=reg["tech_lef"],
        cell_lef=reg["cell_lef"],
        site=reg.get("site") or "unit",
        metal_prefix=reg.get("metal_prefix") or "met",
        # Declared, or asked of the library's own abstract view.
        tapcell_master=tap,
        tapcell_distance_um=float(reg.get("distance_um") or 14.0),
    )
'''














# ---------------------------------------------------------------------------
# THE DEFECT, AND ITS CORRECTION. These two arms are the whole gate: same
# fixture, one keyword argument apart, opposite verdicts.
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# PROSE MUST NOT MOVE THE VERDICT (the grep-shaped-rule defect class).
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# VENUE. A fixture is not production.
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# THE BUY-GREEN AUDIT, PINNED. Each of these is ONE token away from the
# FAILing fixture and leaves the omission exactly where it was, so rc 0 would
# be a gate anybody can switch off. CANNOT-CHECK is the answer, not PASS.
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# WHAT COUNTS AS A CONSTRUCTION SITE: the name, the attribute, ONE hop.
# ---------------------------------------------------------------------------


_SITE_SHAPES = [
    ("", "defs.PdkConfig", "attribute call"),
    ("Cfg = defs.PdkConfig\n", "Cfg", "one hop from an attribute"),
    (f"from defs import {_CLS} as Cfg\n", "Cfg", "one hop from an import"),
]






# ---------------------------------------------------------------------------
# THE DOCUMENTED CONSERVATISMS, PINNED SO THAT WIDENING IS A DELIBERATE EDIT.
# Each of these is a FALSE NEGATIVE the docstring names under KNOWN
# CONSERVATISM. They are here so the boundary cannot move by accident — and
# each is paired above with the FP it exists to prevent.
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# CANNOT-CHECK IS NOT PASS.
# ---------------------------------------------------------------------------




_SECOND_CLASS = '''"""An unrelated class that happens to share the name."""
from __future__ import annotations


class PdkConfig:
    def __init__(self, a=None):
        self.a = a


def make():
    return PdkConfig(a=1)
'''












# ---------------------------------------------------------------------------
# THE SUBJECT SHIPS INTO THE TREE IT SCANS.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# THE SHIPPED TREE. Asserts the VERDICT and non-vacuity, never a site count —
# a count is a bet on code that is allowed to change.
# ---------------------------------------------------------------------------






@pytest.mark.parametrize('worker_name',['frontend','native'])
@pytest.mark.parametrize('tap',['omitted',None,'neutral_tap'])
def test_allocated_pdk_kwargs_preserve_typed_default_and_selected_value(tmp_path,monkeypatch,worker_name,tap):
    from dataclasses import asdict
    import phase3_one_shot_runner as phase3
    import execution_frontend_worker as frontend
    import execution_native_worker as native
    observed=[];original=phase3.PdkConfig.__init__
    def init(self,*args,**kwargs):
        observed.append(dict(kwargs));original(self,*args,**kwargs)
    monkeypatch.setattr(phase3.PdkConfig,'__init__',init)
    values={'name':'neutral','liberty':'input/neutral.lib','site':'neutral_site'}
    if tap!='omitted':values['tapcell_master']=tap
    got=frontend._step7_pdk(values,tmp_path,tmp_path/'out') if worker_name=='frontend' else native._pdk_config(values,tmp_path/'pdk',tmp_path,tmp_path/'out')
    expected=None if tap=='omitted' else tap
    assert got.tapcell_master==expected
    assert observed[0].get('tapcell_master','implicit-default')==expected
    assert asdict(got)['tapcell_master']==expected and got.name=='neutral' and got.liberty=='input/neutral.lib'
    assert got.tech_lef=='' and got.cell_lef=='' and got.cell_gds is None
