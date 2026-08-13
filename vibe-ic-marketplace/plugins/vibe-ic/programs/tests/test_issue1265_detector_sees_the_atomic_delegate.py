"""#1265 — a module that adopted the crash-safe writer stopped being seen to write.

`eda_report_audit.py` swapped `write_text` for
`_atomic_output.atomic_write_text(path, payload)`. The d7 write-detector
(`matrix_d7_artifact_graph._collect_writes`) recognises write positions
STRUCTURALLY, and the two shapes are not the same structure:

    p.write_text(payload)                     Attribute, path is the RECEIVER
    atomic_write_text(p, payload)             path is the FIRST ARGUMENT

So the delegate could not be recognised by adding a name to the
`("write_text", "write_bytes")` tuple — the detector would look at `fn.value`,
which for a module-level call is the MODULE, not a path. The delegate walk
therefore saw NO write at all, and a change that made the write SAFER was
measured as a module that stopped writing.

That is the failure this repository exists to remove, arriving from the good
direction: the artefact got better and the ruler stopped seeing it.

THE REVERSE MATTERS AS MUCH. A recogniser that fires on any call whose first
argument is a path would count `json.load(p)` as a write. The vocabulary is a
closed set of names, and the test below drives a reader with the same shape to
prove the set is not "anything with a path in front".
"""
from __future__ import annotations

import ast
import pathlib

import matrix_d7_artifact_graph as G  # noqa: E402  (sibling module, as elsewhere)

_TESTS = pathlib.Path(__file__).resolve().parent


def _writes(src: str):
    return G._collect_writes(ast.parse(src))


def test_the_qualified_delegate_is_seen_as_a_write():
    """`_atomic_output.atomic_write_text(path, ...)` — the exact call #1265 makes."""
    seen = _writes(
        "import _atomic_output\n"
        "def emit(args, body):\n"
        "    _atomic_output.atomic_write_text('reports/phase3/summary.json', body)\n")
    assert any(t and t[-1] == "summary.json" for t in seen), (
        "the detector did not see a write through the qualified delegate; a module "
        f"that adopted the crash-safe writer reads as writing nothing. saw={seen}")


def test_the_bare_imported_delegate_is_seen_as_a_write():
    """`from _atomic_output import atomic_write_text` is the same call, spelled
    as an ast.Name — a recogniser that only handles the Attribute form catches
    one import style and silently misses the other."""
    seen = _writes(
        "from _atomic_output import atomic_write_text\n"
        "def emit(body):\n"
        "    atomic_write_text('reports/phase3/summary.json', body)\n")
    assert any(t and t[-1] == "summary.json" for t in seen), (
        f"bare-name delegate not recognised; saw={seen}")


def test_write_text_still_recognised_by_its_RECEIVER():
    """THE DIRECTION THAT MUST NOT MOVE. The delegate takes its path from
    `args[0]`; `write_text` takes it from the receiver. If a future tidy-up
    merges the two branches, this is what notices."""
    seen = _writes(
        "from pathlib import Path\n"
        "def emit(body):\n"
        "    Path('reports/phase3/legacy.json').write_text(body)\n")
    assert any(t and t[-1] == "legacy.json" for t in seen), (
        f"the receiver form regressed; saw={seen}")


def test_REVERSE_a_reader_with_the_same_shape_is_NOT_a_write():
    """The recogniser must be a closed vocabulary, not "any call with a path
    first". A reader is the counter-example that proves it."""
    seen = _writes(
        "import json\n"
        "def load(p):\n"
        "    return json.load(open('reports/phase3/input.json'))\n")
    assert not any(t and t[-1] == "input.json" for t in seen), (
        "a READ was counted as a write — the vocabulary has become "
        f"'anything with a path argument'. saw={seen}")


def test_the_vocabulary_is_defined_once():
    """Two recognisers sit ~200 lines apart in that module. Teaching one and
    not the other is how a detector comes to disagree with itself, which is
    precisely how #1265 survived: the production change was visible to a
    reader and invisible to the walk."""
    assert hasattr(G, "_DELEGATE_WRITERS"), (
        "the delegate names must be one shared constant, not two literals")
    src = (_TESTS / "matrix_d7_artifact_graph.py").read_text(encoding="utf-8")
    assert src.count("_DELEGATE_WRITERS") >= 4, (
        "the shared vocabulary is not consulted at both recogniser sites; "
        "one of them still cannot see a delegate write")
