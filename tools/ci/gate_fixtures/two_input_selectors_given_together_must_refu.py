"""`two input selectors given together must refu` — a parser that offers two
ways to name its input and decides neither.

THE SUBJECT
===========
The gate walks `<root>/vibe-ic-marketplace/plugins/vibe-ic/programs/**/*.py`
and, for every parser offering BOTH a single-target selector and a collection
selector, asks whether the both-given case is refused (one
`add_mutually_exclusive_group()`) or decided (an `if` test naming both, as a
conjunction). Anything else is a finding, and a finding is a FAIL unless the
inventory beside the gate already carries its key.

THE INVENTORY IS READ FROM THE GATE'S OWN DIRECTORY, NOT FROM THE SUBJECT.
`$PG` stays the real programs tree, so `dual_input_selector_inventory.json`
that applies is the REAL one. A subject that does not reproduce every row in it
is refused for STALE ROWS — a refusal about the inventory, not about the
predicate. So both arms synthesise one parser per inventory row, at the row's
own relative path, with the row's own selector names, generated FROM the
inventory at run time rather than frozen here.

THE MUTATION
============
A ninth parser — `fixture_dual_selector_probe.py`, offering `--record` and
`--corpus` — is present in BOTH arms. In `can_pass` its two selectors sit in
one `add_mutually_exclusive_group()`, so the parser itself refuses the
both-given case and it is not a finding. In `can_fail` the same two selectors
are added as INDEPENDENT options and nothing decides the case, so it becomes a
NEW finding.

SAME DENOMINATOR, BOTH ARMS: 9 modules parsed, 9 dual-selector parsers. Only
`neither refuse nor decide` moves, 8 -> 9. The mutation changes the ANSWER for
one parser; it does not change the size of the population, and it does not
reach its refusal by emptying the corpus.

chip-AGNOSTIC: no IC, vendor, SKU or process appears here.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "two input selectors given together must refu"

_PROGRAMS_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"
_PROBE_REL = _PROGRAMS_REL + "/fixture_dual_selector_probe.py"
_INVENTORY = "dual_input_selector_inventory.json"


def _gate_module():
    """The gate's OWN `_SINGLE` set, live. A frozen copy here would drift.

    `_SINGLE` decides whether a selector name is spelled `--name` or as a
    positional: a name outside the set only counts as a single-target selector
    when it is positional, and getting that backwards would silently change the
    key this fixture reproduces.
    """
    p = str(F.PROGRAMS)
    if p not in sys.path:
        sys.path.insert(0, p)
    return importlib.import_module(
        "two_input_selectors_given_together_must_refuse")


def _inventory_keys():
    raw = (F.PROGRAMS / _INVENTORY).read_text(encoding="utf-8")
    return [r["key"] for r in json.loads(raw).get("known", [])]


def _parser_source(singles, colls, exclusive: bool) -> str:
    single_set = _gate_module()._SINGLE
    holder = "grp" if exclusive else "ap"
    out = ["#!/usr/bin/env python3",
           '"""Synthetic parser. Its only reader is the dual-selector gate."""',
           "import argparse",
           "",
           "",
           "def main():",
           "    ap = argparse.ArgumentParser()"]
    if exclusive:
        out.append("    grp = ap.add_mutually_exclusive_group()")
    for s in singles:
        if s in single_set:
            out.append(f'    {holder}.add_argument("--{s}", default=None)')
        else:
            out.append(f'    {holder}.add_argument("{s}", nargs="?")')
    for c in colls:
        out.append(f'    {holder}.add_argument("--{c}", default=None)')
    out += ["    return ap.parse_args()",
            "",
            "",
            'if __name__ == "__main__":',
            "    main()",
            ""]
    return "\n".join(out)


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _tree(work: Path, probe_is_exclusive: bool) -> Path:
    root = work / "subject"
    for key in _inventory_keys():
        rel, singles, colls = key.split("::")
        _write(root, rel, _parser_source(
            [x for x in singles.split(",") if x],
            [x for x in colls.split(",") if x],
            exclusive=False))
    _write(root, _PROBE_REL,
           _parser_source(["record"], ["corpus"], exclusive=probe_is_exclusive))
    return root


def can_pass(work: Path) -> Path:
    return _tree(work, probe_is_exclusive=True)


def can_fail(work: Path):
    return (_tree(work, probe_is_exclusive=False),
            "accept two ways to name the input and decide neither")
