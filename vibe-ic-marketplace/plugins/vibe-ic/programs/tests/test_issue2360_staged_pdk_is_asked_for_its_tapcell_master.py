"""vibe-ic#2360 — a staged PDK is ASKED for its tapcell master, never assumed tapless.

`PdkConfig.tapcell_master = None` is not a neutral default: the tapcell step
reads it as TAPCELL_SKIPPED and the PERC latch-up gate reads it as a
TAPLESS-CELL PDK. Of the five `PdkConfig(...)` sites in `_detect_pdk`, the one
that serves a project-local `input/pdk/` did not pass the field, so every
staged PDK was silently tapless — including one whose cell LEF ships a
`CLASS CORE WELLTAP` master.

Measured on main dfdb3e8d2 before the fix: a staged PDK whose cell LEF carries
`MACRO TAPX1 ... CLASS CORE WELLTAP` resolved to `tapcell_master=None`.

The fix is ONE derivation (`_derive_tapcell_master`) used by the registry, asap7
and staged sites: declared key first (null = stated tapless), else the PDK's
own LEF, else a measured NONE that names the LEFs it read. An unreadable LEF is
a refusal, not a NONE.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

_TECH = "LAYER MET1\n  TYPE ROUTING ;\nEND MET1\nEND LIBRARY\n"
_INV = "MACRO INVX1\n  CLASS CORE ;\n  SITE core ;\nEND INVX1\n"
_TAP = "MACRO TAPX1\n  CLASS CORE WELLTAP ;\n  SITE core ;\nEND TAPX1\n"




@pytest.fixture(autouse=True)
def _no_container(monkeypatch):
    # A host-staged PDK must be answered from the host; never shell out.
    monkeypatch.delenv("EDA_CONTAINER", raising=False)


















# ── ONE derivation ─────────────────────────────────────────────────────────
_TREE = ast.parse((PROGRAMS / "phase3_one_shot_runner.py").read_text(
    encoding="utf-8"))


def _functions():
    return [n for n in ast.walk(_TREE) if isinstance(n, ast.FunctionDef)]


def test_every_pdkconfig_site_passes_tapcell_master():
    calls = [n for n in ast.walk(_TREE) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "PdkConfig"]
    assert len(calls) >= 5, len(calls)
    missing = [c.lineno for c in calls
               if "tapcell_master" not in {k.arg for k in c.keywords}]
    assert not missing, f"PdkConfig(...) without tapcell_master at {missing}"


def test_every_derived_value_comes_from_the_one_function():
    """A non-literal `tapcell_master=` is the name bound by a
    `_derive_tapcell_master(...)` call in the SAME function. A literal is a
    hand-written named-branch declaration (pinned against the registry by the
    #586 drift test)."""
    offenders = []
    for fn in _functions():
        bound = set()
        for n in ast.walk(fn):
            if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                    and getattr(n.value.func, "id", None)
                    == "_derive_tapcell_master"
                    and isinstance(n.targets[0], ast.Tuple)):
                bound.add(n.targets[0].elts[0].id)
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "PdkConfig":
                for k in n.keywords:
                    if k.arg != "tapcell_master":
                        continue
                    if isinstance(k.value, ast.Constant) and isinstance(
                            k.value.value, str):
                        continue
                    if isinstance(k.value, ast.Name) and k.value.id in bound:
                        continue
                    offenders.append((fn.name, n.lineno, ast.dump(k.value)))
    assert not offenders, offenders


def test_the_staged_site_is_one_of_the_derived_sites():
    staged = [n for n in ast.walk(_TREE) if isinstance(n, ast.Call)
              and getattr(n.func, "id", None) == "PdkConfig"
              and any(k.arg == "name" and isinstance(k.value, ast.JoinedStr)
                      and "custom:" in ast.unparse(k.value)
                      for k in n.keywords)]
    assert len(staged) == 1, len(staged)
    kw = {k.arg: k.value for k in staged[0].keywords}
    assert isinstance(kw.get("tapcell_master"), ast.Name), (
        "the staged input/pdk site does not derive tapcell_master")
    assert "tapcell_master_source" in kw


def test_no_site_spells_its_own_registry_lookup():
    """`reg.get("tapcell_master")` is the per-site copy #2360 removed: an
    omitted key and a stated null both arrive as None through it."""
    hits = [n.lineno for n in ast.walk(_TREE)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get" and n.args
            and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "tapcell_master"]
    assert not hits, f'.get("tapcell_master") at {hits}'
