"""`explicit argument outranks the env pointer` — a checker that can redirect
its subject from the environment and never says so.

THE MUTATION IS THE MEASURED DEFECT ITSELF. The gate's docstring records it in
one sentence: a checker handed an explicit two-path subject answered about a
shared tree of 8309 paths, because it read the corpus pointer AFTER parsing its
location argument and let the pointer win. The caller's fixture was never
examined and the verdict was complete and confident about a tree the caller had
not named.

The gate deliberately does NOT arbitrate whether the pointer may win — that
contract split is live and argued on both sides in this repository. What it
enforces is the half every side agrees on and the half that would have caught
the measured failure:

    a site that reads the corpus pointer and can redirect its subject with it
    MUST say so on its output.

So the mutation is exactly that: one in-scope module keeps its
`os.environ.get("VIBE_IC_BENCHMARK_DATA")`, keeps the redirect it performs with
it, keeps its place in the scanned tree — and loses the ANNOUNCEMENT. A caller
who named a location can no longer tell which tree was walked.

THE DENOMINATOR IS THE SAME IN BOTH ARMS
========================================
Both subjects contain the same one module at the same in-scope path, and the
gate prints its denominator on every run:

    in-scope corpus-pointer readers:   1   (both arms)
    silent readers outside the scope:  0   (both arms)

Nothing is added to the corpus and nothing is removed from it. The module is
still found, still parsed, still recognised as a pointer reader — `audit()`
increments `readers` BEFORE it asks the announcement question, so both arms
count it. What moves is the ANSWER for that one module.

WHY THE MODULE SITS WHERE IT DOES
=================================
`audit()` scopes the refusal to `vibe-ic-marketplace/plugins/vibe-ic/programs/`
— the rule's measured subject is a CHECKER handed a named subject that answered
about another tree — and everything outside it is DISCLOSED rather than
refused. A fixture module written anywhere else would be counted as disclosed,
never as a finding, and the can-fail arm would go green. It also must not sit
under `tests/` or be named `test_*`: `_skip()` excludes those on purpose,
because a test that sets the pointer to build a fixture is not a consumer.

The recognition is by AST at MODULE granularity, not by text: `_reads_pointer`
wants a real `.get(<pointer name>)` call or subscript, and `_announces` wants a
real `print` whose literal text carries one of the announcement tokens or the
pointer's own name. Both arms satisfy the first; only `can_pass` satisfies the
second.

chip-AGNOSTIC: no IC, vendor, SKU or process appears here.
"""
from pathlib import Path

GATE = "explicit argument outranks the env pointer"

#: The scope `audit()` refuses in. Outside it a reader is disclosed, not failed.
_IN_SCOPE = ("vibe-ic-marketplace", "plugins", "vibe-ic", "programs")

_MODULE = "corpus_scope_reader.py"

#: A consumer that resolves its subject and CAN redirect it from the pointer.
#: `{announce}` is the only moving part.
_READER = '''\
#!/usr/bin/env python3
"""A checker that resolves the tree it will walk, argument or pointer."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def resolve_subject(named: str) -> Path:
    """The tree this run will ACTUALLY walk."""
    pointer = os.environ.get("VIBE_IC_BENCHMARK_DATA")
    if pointer:
{announce}
        return Path(pointer)
    return Path(named)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    subject = resolve_subject(argv[0] if argv else ".")
    for path in sorted(subject.rglob("*.json")):
        print(path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

#: The announcement the rule requires: the redirect, named on the output.
_ANNOUNCES = ('        print("note: VIBE_IC_BENCHMARK_DATA is set and "\n'
              '              "overrides the location named on the command "\n'
              '              "line; scanning %s instead" % pointer)')

#: The redirect, silent. Everything else about the module is unchanged.
_SILENT = "        pass"


def _tree(work: Path, announce: bool) -> Path:
    root = work / "subject"
    programs = root.joinpath(*_IN_SCOPE)
    programs.mkdir(parents=True)
    (programs / _MODULE).write_text(
        _READER.format(announce=_ANNOUNCES if announce else _SILENT),
        encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The reader redirects, and names the pointer and the tree it took."""
    return _tree(work, announce=True)


def can_fail(work: Path):
    """The same module, the same read of the pointer, the same redirect — and
    nothing on its output naming the tree it scanned."""
    return (_tree(work, announce=False),
            "reads the corpus pointer and can redirect its subject with it")
