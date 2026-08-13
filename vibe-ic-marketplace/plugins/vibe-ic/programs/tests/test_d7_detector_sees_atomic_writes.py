#!/usr/bin/env python3
"""The d7 write-detector must see an ATOMIC write — vibe-ic#1265.

A durable write goes through a helper that writes a temp sibling and
``os.replace``s it into place, so the DESTINATION is the helper's FIRST
ARGUMENT rather than the receiver:

    p.write_text(text)              destination is the receiver
    atomic_write_text(p, text)      destination is args[0]

The detector knew only the first form. So a program made MORE durable read as
writing nothing, its declared artefact lost its producer, and dimension 7
reported the step's `required_outputs` as incomplete. MEASURED on #1265:
`test_argv_forwarding_wrapper_flags_resolve_through_the_delegate` failed on that
branch and on no other, and cleared only when the detector learned the family.

THE VOCABULARY LIVES IN ONE PLACE. There are two write detectors in this module
— `_collect_writes` and the delegate/argv walk — and each carried its own copy
of the idiom list. Teaching only the first is not enough; that is measured below,
because it is the mistake this fix was written after making.

Fixtures are synthesized: neutral names, no design, PDK or vendor literal.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent.parent


def _graph():
    path = _PLUGIN / "programs" / "tests" / "matrix_d7_artifact_graph.py"
    spec = importlib.util.spec_from_file_location("_d7g", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_d7g"] = mod
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True          # never write into the shipped tree
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


G = _graph()

_ATOMIC = [
    'atomic_write_text(Path("reports/out/alpha.json"), text)',
    '_atomic_output.atomic_write_text(Path("reports/out/alpha.json"), text)',
    'write_json(Path("reports/out/alpha.json"), obj)',
    '_atomic_artefact.write_json(Path("reports/out/alpha.json"), obj)',
]


@pytest.mark.parametrize("call", _ATOMIC, ids=lambda c: c.split("(")[0])
def test_an_atomic_write_is_seen_as_a_write(call):
    """Both import spellings, both helper families, destination first."""
    tree = ast.parse(f"from pathlib import Path\ndef f(text, obj):\n    {call}\n")
    writes = G._collect_writes(tree)
    assert any(w and w[-1] == "alpha.json" for w in writes), (
        f"{call} was not recognised as a write — a program made MORE durable "
        f"would read as writing nothing")


def test_the_receiver_form_still_works():
    """The fix must not cost the idiom that already worked."""
    tree = ast.parse('from pathlib import Path\n'
                     'def f(t):\n    Path("reports/out/beta.json").write_text(t)\n')
    assert any(w and w[-1] == "beta.json" for w in G._collect_writes(tree))


def test_a_context_manager_is_NOT_a_write():
    """`atomic_output(p)` opens a transaction; it is not itself a path write.

    An `atomic_*` PREFIX rule was rejected for exactly this: it would invent a
    producer for a call that writes nothing on its own. Measured over 3632
    modules when the rule was chosen.
    """
    tree = ast.parse('from pathlib import Path\n'
                     'def f():\n    with atomic_output(Path("reports/out/gamma.json")) as fh:\n'
                     '        pass\n')
    assert not any(w and w[-1] == "gamma.json" for w in G._collect_writes(tree)), (
        "atomic_output is a context manager, not a write — matching it would "
        "invent a producer")


def test_a_NON_write_call_is_not_a_write():
    """Guards against the family being widened into 'any call with a path'."""
    tree = ast.parse('from pathlib import Path\n'
                     'def f():\n    read_json(Path("reports/out/delta.json"))\n')
    assert not any(w and w[-1] == "delta.json" for w in G._collect_writes(tree))


def test_BOTH_detectors_share_ONE_vocabulary():
    """The delegate walk carried its own copy; teaching one is not enough.

    This is the regression that cost a measurement: the first fix taught
    `_collect_writes` only, and #1265's failure survived it unchanged. Pinned
    structurally — both sites must consult the same name — so a future editor
    cannot teach one and leave the other blind.
    """
    src = (_PLUGIN / "programs" / "tests" / "matrix_d7_artifact_graph.py").read_text()
    assert src.count("ATOMIC_WRITE_FUNCS") >= 3, (
        "the atomic-write family must be ONE definition consulted by BOTH the "
        "collector and the delegate walk; a second copy is the drift #527/#530 "
        "removed elsewhere")
    assert "atomic_write_text" in G.ATOMIC_WRITE_FUNCS
