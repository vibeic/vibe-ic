"""The d7 write-detector must see `_atomic_output.atomic_write_text(p, ...)`.

#1082 converts verdict-bearing programs from `p.write_text(...)` to a
module-level atomic helper. The walk knew only the RECEIVER form, so a
converted program read as writing nothing and its declared output looked
unproduced — #1265, measured d7 10 -> 11 on 24ff9530.

The trap this pins: adding the name to the `fn.attr in ("write_text", ...)`
tuple resolves `fn.value`, which for a module-level call is the imported
MODULE, not the path. That would keep detecting nothing while looking fixed —
so the module case is asserted explicitly, not just "some path was found".
"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matrix_d7_artifact_graph as G  # noqa: E402


def _written(src: str):
    return {"/".join(t) for t in G._collect_writes(ast.parse(src))}


def test_the_receiver_form_still_resolves():
    assert "reports/a.json" in _written(
        'from pathlib import Path\n'
        'Path("reports/a.json").write_text("x")\n')


def test_the_module_level_atomic_form_resolves_to_the_PATH():
    got = _written(
        'from pathlib import Path\nimport _atomic_output\n'
        '_atomic_output.atomic_write_text(Path("reports/b.json"), "x")\n')
    assert "reports/b.json" in got, (
        "the atomic writer's destination is its FIRST ARGUMENT and was not seen")


def test_it_does_NOT_resolve_to_the_MODULE():
    """The failure mode of the obvious one-line fix, asserted directly."""
    got = _written(
        'from pathlib import Path\nimport _atomic_output\n'
        '_atomic_output.atomic_write_text(Path("reports/c.json"), "x")\n')
    assert not any("_atomic_output" in p for p in got), (
        "resolved the imported module instead of the path — this is what "
        "adding the name to the receiver tuple would do")


def test_both_in_flight_helpers_are_known():
    """Two helpers are in flight for #1082; knowing only one re-opens the hole."""
    for mod in ("_atomic_output", "_atomic_artefact"):
        assert "reports/d.json" in _written(
            f'from pathlib import Path\nimport {mod}\n{mod}.atomic_write_text(Path("reports/d.json"), "x")\n'), mod
