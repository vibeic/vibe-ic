#!/usr/bin/env python3
"""A provenance declaration is only as durable as the artefact it names.

#443 declared outputs at phase-3 tool-run call sites and stated the rule
correctly in its own description: attesting a TRANSIENT is a false accusation,
worse than the honest gap it replaces. It rejected three sites on exactly that
ground — an intermediate a later step renames into place, a report a later
invocation rewrites, and a log the runner rather than the tool writes.

The rule was right and its application was incomplete. Found at land time,
statically, in the same functions:

  merged   declared, then `merged.replace(gds_path)` THREE LINES LATER. By
           audit time the declared path does not exist -> FILE_MISSING, and the
           gate accuses a tool that worked. Identical to the `snapped.gds`
           case #443 rejected.

  netlist  declared at five call sites, then `netlist.write_text(...)` twice
           afterwards in `step_synth`, guarded by `if n_renamed > 0`. The
           recorded digest no longer matches -> HASH_MISMATCH. Identical to the
           `power.rpt` case #443 rejected — and CONDITIONAL, so it would fire
           only on designs carrying named tie nets. An intermittent false
           accusation is worse than a constant one: it reads as a real defect
           in whichever design happens to trip it.

Six declarations removed. This test makes the rule EXECUTABLE, because until
now it existed only in a pull-request description, where the next person to add
a declaration will not find it.

WHAT THIS TEST DOES NOT DO: prove a declaration is durable. It catches the
mechanical, checkable shape — a declared name that is renamed, moved or
rewritten later in the same function. A transient established some other way
still needs a person. Narrow and honest beats broad and wrong; a check that
fired on every declaration would simply be turned off.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
_RUNNER = _PROGRAMS / "phase3_one_shot_runner.py"

_MUTATORS = ("rename", "replace", "unlink", "write_text", "write_bytes")


def _functions(tree: ast.AST) -> list[ast.AST]:
    return [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _declared_names(tree: ast.AST) -> list[tuple[str, int]]:
    """(name, lineno) for every `outputs=[<Name>]` keyword argument.

    Scoped per FUNCTION by the caller. A first version matched by name across
    the whole module and reported three false positives: `out_json` is a local
    in each of `_emit_si_timing_json`, `_emit_metal_density_report` and
    `_emit_aging_sta_report`, and one function's write was blamed on another's
    declaration. A check that fires on legitimate code is worse than no check.
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "outputs" or not isinstance(kw.value, ast.List):
                continue
            for el in kw.value.elts:
                if isinstance(el, ast.Name):
                    out.append((el.id, el.lineno))
    return out


def _mutated_after(tree: ast.AST, name: str, after: int) -> list[int]:
    """Lines after `after` where `<name>.<mutator>(...)` is called."""
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _MUTATORS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == name):
            continue
        if node.lineno > after:
            hits.append(node.lineno)
    return sorted(hits)


def test_no_declared_output_is_renamed_or_rewritten_later():
    """THE RULE, made executable."""
    tree = ast.parse(_RUNNER.read_text(errors="replace"))
    offenders = []
    # Per FUNCTION: a name is only the same artefact inside one scope.
    for fn in _functions(tree):
        for name, line in _declared_names(fn):
            after = _mutated_after(fn, name, line)
            if after:
                offenders.append((fn.name, name, line, after[:3]))
    assert offenders == [], (
        "declared output(s) that a later statement renames or rewrites; the "
        "recorded digest cannot survive to audit time: %r" % (offenders,))


def test_the_runner_still_declares_outputs_at_all():
    """The paired half, and the one that keeps the test above from passing
    vacuously: removing every declaration would also satisfy it. #443's whole
    point is that #432's recorder had no declarations to record."""
    tree = ast.parse(_RUNNER.read_text(errors="replace"))
    assert len(_declared_names(tree)) >= 10, _declared_names(tree)


def test_the_detector_finds_a_planted_transient(tmp_path):
    """Control on a fixture, so a green result above is evidence rather than
    the detector failing to look."""
    src = tmp_path / "m.py"
    src.write_text(
        "def f(x, out):\n"
        "    tmp = out / 'a.gds'\n"
        "    run(cmd, outputs=[tmp])\n"
        "    tmp.replace(out / 'final.gds')\n")
    tree = ast.parse(src.read_text())
    names = _declared_names(tree)
    assert [n for n, _ in names] == ["tmp"]
    assert _mutated_after(tree, "tmp", names[0][1]) != []


def test_the_detector_does_not_fire_on_a_durable_declaration(tmp_path):
    """The other direction: a declaration that is merely READ afterwards is
    durable, and flagging it would make the rule unusable."""
    src = tmp_path / "m.py"
    src.write_text(
        "def f(x, out):\n"
        "    rpt = out / 'sta.rpt'\n"
        "    run(cmd, outputs=[rpt])\n"
        "    if rpt.is_file():\n"
        "        text = rpt.read_text()\n")
    tree = ast.parse(src.read_text())
    names = _declared_names(tree)
    assert _mutated_after(tree, "rpt", names[0][1]) == []
