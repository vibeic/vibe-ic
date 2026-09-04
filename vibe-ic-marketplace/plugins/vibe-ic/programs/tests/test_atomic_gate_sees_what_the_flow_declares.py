#!/usr/bin/env python3
"""The atomic-write gate's population is the FLOW's declaration, not a CLI flag.

WHAT WAS BLIND. `atomic_artifact_write_check` found a program's report
destination by reading its argparse flags (`--json`, `--out`, `--output`,
`--report`) and returned immediately when there were none:

    dests = _dest_arg_names(tree)
    if not dests:
        return []

MEASURED 2026-09-04: the flow declares 185 `required_outputs` across 67 steps,
produced by 116 programs — and 14 of those 116 declare no CLI report flag at
all. Every one of them was skipped whole. They produce artefacts a `check_step`
reads as "the step produced this", which is precisely the population this gate
exists for, and it could not see them.

The CLI flag was always a PROXY for "this program writes something a later
reader treats as evidence". The flow yaml is the AUTHORITY on that, so the
population is read from the authority and the flag stays as the second channel.

WHAT THE WIDENING FOUND, and it is why the widening is not cosmetic — both are
real and neither was visible before:

    testbench_gen.py:1048     `results.xml`, the FUNCTIONAL-TEST DENOMINATOR.
                              Step 4's bridge opens it to substantiate
                              `functional_verified`; a writer that dies mid-XML
                              leaves a truncated file under the final name and
                              the bridge counts it.
    die_finishing_gen.py:813  a DISCLOSED_SKIP marker — a ROUTER whose mere
                              existence tells downstream that die finishing did
                              not run. A truncated one still exists and still
                              routes.

Zero false positives in the sweep: those two were the only new findings, and
both were converted rather than baselined.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import atomic_artifact_write_check as G                        # noqa: E402


def test_the_flow_is_read_as_the_population():
    """The declaration must actually resolve to programs, not to nothing."""
    by_prog = G.declared_outputs_by_program(_PLUGIN)
    assert by_prog, (
        "the flow declares no outputs for any program — the widened population "
        "collapsed to the CLI channel and this gate is blind again")
    assert len(by_prog) >= 50, (
        f"only {len(by_prog)} program(s) resolved from the flow's "
        f"required_outputs; the measurement that motivated this was 116")


def _prog(src: str) -> Path:
    p = Path(__import__("tempfile").mkdtemp()) / "prog.py"
    p.write_text(src)
    return p


#: A program shaped like the 14: it produces a flow-declared artefact and takes
#: no `--json`/`--out`/`--report` at all.
_NO_CLI_FLAG = (
    'from pathlib import Path\n'
    'def main(project):\n'
    '    out = Path(project) / "reports/phase1/thing.json"\n'
    '    out.write_text("{}")\n'
)


def test_scan_program_uses_the_flow_declaration_end_to_end():
    """THE WIRING, not the part. A test that calls `_literal_dest_names`
    directly passes even when `scan_program` has stopped calling it — which is
    exactly what a mutation proved, so this drives the real entry point."""
    p = _prog(_NO_CLI_FLAG)
    hits = G.scan_program(p, {"reports/phase1/thing.json"})
    assert hits, (
        "a program with no CLI report flag that writes a FLOW-DECLARED output "
        "non-atomically was not caught — the widened population is not wired "
        "into scan_program")
    assert hits[0]["form"].startswith(".write_text")


def test_the_same_program_is_invisible_without_the_declaration():
    """The control: it is the DECLARATION that makes it visible, nothing else.

    Without this, the test above would pass for a scanner that flagged every
    write in every file.
    """
    assert G.scan_program(_prog(_NO_CLI_FLAG), set()) == []


def test_the_flow_resolves_programs_that_have_no_cli_flag():
    """And the tree really does contain the case — otherwise the widening is
    machinery for a population of zero."""
    by_prog = G.declared_outputs_by_program(_PLUGIN)
    blind = []
    for stem in by_prog:
        f = _PROGRAMS / f"{stem}.py"
        if not f.is_file():
            continue
        try:
            tree = ast.parse(f.read_text(errors="replace"))
        except SyntaxError:
            continue
        if not G._dest_arg_names(tree):
            blind.append(stem)
    assert blind, (
        "no program declares a flow output without a CLI report flag, so the "
        "widening cannot be shown to reach anything in this tree")


def test_a_literal_the_flow_does_not_declare_is_not_a_destination():
    """The widening must not become "every string in the file".

    A rule that fires on any path literal would flag scratch files, temp
    directories and staging areas — writes no consumer resolves — and a gate
    that reports those gets waived wholesale.
    """
    src = ('def main():\n'
           '    scratch = "/tmp/whatever.json"\n'
           '    open(scratch, "w").write("x")\n')
    tmp = Path(__import__("tempfile").mkdtemp()) / "prog.py"
    tmp.write_text(src)
    assert G.scan_program(tmp, {"reports/phase3/real_output.json"}) == []


def test_the_two_findings_this_widening_produced_stay_atomic():
    """The conversions, pinned by behaviour rather than by a baseline entry.

    Baselining them would have recorded the defect instead of removing it, and
    both write artefacts a later reader treats as evidence.
    """
    for stem, needle in (("testbench_gen", "results.xml"),
                         ("die_finishing_gen", "Die finishing did not run")):
        src = (_PROGRAMS / f"{stem}.py").read_text(errors="replace")
        assert needle in src, f"{stem} no longer writes {needle!r}"
        by_prog = G.declared_outputs_by_program(_PLUGIN)
        hits = G.scan_program(_PROGRAMS / f"{stem}.py", by_prog.get(stem))
        assert not hits, (
            f"{stem} writes a flow-declared output non-atomically again: "
            f"{hits}")


def test_an_unreadable_flow_falls_back_to_the_cli_channel_not_to_nothing():
    """A population that could not be READ must not become a population of ZERO.

    This repo's most repeated defect in one line: "could not look" and "there
    was nothing to look at" must not produce the same artefact. Here the
    consequence would be a gate that silently stops examining 116 programs.

    DRIVEN WITH `declared=None`, which is exactly what `audit` passes for a
    program the flow names nowhere. An earlier version passed `set()` and a
    scanner that switched itself off on `None` still looked healthy.
    """
    assert G.declared_outputs_by_program(Path("/nonexistent")) == {}
    cli = _prog('import argparse\n'
                'def main():\n'
                '    p = argparse.ArgumentParser()\n'
                '    p.add_argument("--json")\n'
                '    a = p.parse_args()\n'
                '    a.json.write_text("x")\n')
    assert G.scan_program(cli, None), (
        "with no flow declaration the CLI channel must still catch a direct "
        "write to --json")
