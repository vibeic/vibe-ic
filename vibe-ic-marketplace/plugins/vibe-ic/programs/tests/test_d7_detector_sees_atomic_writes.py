#!/usr/bin/env python3
"""The d7 write-detector must not go blind when a program writes ATOMICALLY.

WHAT WAS MEASURED
=================
`matrix_d7_artifact_graph._collect_writes` recognised `open()`, `p.open("w")`,
`p.write_text`, `p.write_bytes` and the shutil destinations. An atomic write is
none of those — the path is an ARGUMENT to a free function, not the receiver of
a method:

    from _atomic_artefact import write_text as atomic_write_text
    atomic_write_text(out_path, payload)

So a converted program looked, to d7, like a program that writes nothing. d7 is
the dimension that asks whether a declared output has a producer, and it would
have gone quiet on every converted program at once — the failure mode this
repository exists to remove, arriving through a change whose whole purpose was
to make writes SAFER.

On clean main nothing imports `_atomic_artefact`, so this cost nothing yet.
Measured on the conversion stack: #1110 takes it from 1 program to 12, #1138 to
54. The detector had to learn the form BEFORE the conversion lands, or the
blindness lands with it and no test says so.

WHY BINDINGS AND NOT A NAME
===========================
52 of the 54 programs bind the helper LOCALLY
(`from _atomic_artefact import write_text as atomic_write_text`) and 8 bind the
module (`import _atomic_artefact as _aa`). A detector keyed on the literal string
"atomic_write_text" would be matching a convention, not a fact, and the next
program to pick a different alias would be invisible again. The module's own
standard is "structurally (never by name matching)", so the bindings are read off
the import statements.
"""
from __future__ import annotations

import ast

import matrix_d7_artifact_graph as G


def _writes(src: str):
    return {"/".join(t) for t in G._collect_writes(ast.parse(src))}


# ---------------------------------------------------------------------------
# The forms the conversion actually uses — both measured on #1138's head.
# ---------------------------------------------------------------------------

def test_the_aliased_function_import_is_seen():
    """52 of the 54 converted programs use exactly this shape."""
    src = (
        "from _atomic_artefact import write_text as atomic_write_text\n"
        "atomic_write_text(out_dir / 'reports/phase3/drc_signoff.json', body)\n"
    )
    assert "reports/phase3/drc_signoff.json" in _writes(src), (
        "an atomic write through a locally-aliased import was not seen as a "
        "write — d7 would report this program as producing nothing")


def test_the_module_alias_import_is_seen():
    """The other 8 bind the module instead of the function."""
    src = (
        "import _atomic_artefact as _aa\n"
        "_aa.write_text(out_dir / 'reports/phase3/lvs_signoff.json', body)\n"
    )
    assert "reports/phase3/lvs_signoff.json" in _writes(src)


def test_write_json_and_write_bytes_are_seen_too():
    """`__all__` exports three writers; catching one of them is not enough."""
    src = (
        "from _atomic_artefact import write_json, write_bytes\n"
        "write_json(d / 'reports/audit/a.json', obj)\n"
        "write_bytes(d / 'reports/audit/b.json', blob)\n"
    )
    got = _writes(src)
    assert "reports/audit/a.json" in got and "reports/audit/b.json" in got


# ---------------------------------------------------------------------------
# PAIRED GUARD — the detector must not have become a rubber stamp.
# ---------------------------------------------------------------------------

def test_the_classic_write_forms_still_register():
    """Teaching it a new form must not disturb the ones it already knew."""
    src = (
        "p = out / 'reports/phase3/sta.json'\n"
        "p.write_text(body)\n"
        "q = out / 'reports/phase3/ir.json'\n"
        "open(q, 'w').write(body)\n"
    )
    got = _writes(src)
    assert "reports/phase3/sta.json" in got, "p.write_text stopped registering"
    assert "reports/phase3/ir.json" in got, "open(..., 'w') stopped registering"


def test_a_call_that_is_not_a_write_is_still_not_a_write():
    """The name alone must not be enough — without the import it is some other
    function, and treating it as a write would be the mirror-image defect."""
    src = "atomic_write_text(d / 'reports/phase3/nope.json', body)\n"
    assert _writes(src) == set(), (
        "a bare call with no `_atomic_artefact` import was counted as an atomic "
        "write; the detector is matching a NAME, which is what it must not do")


def test_reading_the_module_is_not_writing_it():
    """An import without a call writes nothing."""
    src = (
        "from _atomic_artefact import write_text as atomic_write_text\n"
        "data = (d / 'reports/phase3/in.json').read_text()\n"
    )
    assert _writes(src) == set()
