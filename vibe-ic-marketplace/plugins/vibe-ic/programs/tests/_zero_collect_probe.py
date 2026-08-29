"""A pytest plugin that records, for EVERY module pytest discovers, how many
test nodes it actually collected — including the modules that collected none.

WHY A PLUGIN AND NOT A GLOB. The question "does this file collect any tests"
has exactly one authority, and it is pytest's own collector. Every cheaper
proxy is a SECOND definition of the question that drifts from the first, and
the direction it drifts in is always the same one: a file nobody runs, reported
as a file that passed. Three drifts were MEASURED on 03ea6f5ad9 against the
glob+regex this plugin replaces, and all three stayed green:

  * a zero-collect module in a tier the glob did not walk (the glob was
    non-recursive and single-directory; 128 of 3028 discovered modules lie
    outside it — mcp-eda/test 39, skills/*/tests 81, tools/phase1_engine 8);
  * a module spelled `*_test.py`, which pytest discovers by default and a
    `test_*.py` glob does not;
  * a NESTED `def test_`, which `^\\s*def test_` matches because of the `\\s*`
    while pytest collects nothing from it.

`pytest_collectreport` has none of those blind spots by construction: it fires
for the modules pytest DECIDED to collect, so `norecursedirs`, `python_files`,
a conftest's `collect_ignore`, and every other real discovery rule are already
applied by the time this plugin sees a row.

THE COUNT IS OF LEAF ITEMS, NOT OF DIRECT CHILDREN, and that is a fourth blind
spot rather than a detail. `report.result` for a Module holds its direct
children, so a module whose only content is

    class TestNothing:
        def helper(self): ...

reports ONE child (the Class) and collects ZERO tests — measured. Counting
`pytest_itemcollected` instead counts the things that would actually run.

IT ALSO CLASSIFIES, and the three classes are different defects that a bare
count cannot tell apart:

    outcome == "failed"     the module raised while being imported. A COLLECTION
                            ERROR — pytest reports it separately and a `-q`
                            summary line can swallow it.
    outcome == "skipped"    a module-level skip fired — `pytest.importorskip`
                            or `pytest.skip(allow_module_level=True)`. The
                            module is not-measured ON THIS HOST, and what is
                            missing is stated by the skip reason.
    outcome == "passed"     the module imported cleanly and genuinely defines
                            no test function: a body was deleted, the functions
                            are not named `test_*`, or they are nested inside
                            something pytest does not descend into.

OUTPUT. `ZERO_COLLECT_PROBE_OUT` names a path; one JSON object is written there
at session finish:

    {"rows": [{"file": <nodeid>, "nodes": <int>, "outcome": <str>}, ...],
     "rootdir": <str>, "exitstatus": <int>}

where `nodes` is the number of LEAF items collected from that file.

Rows are written even when collection was INTERRUPTED by an error, so a census
never silently shrinks to the modules that happened to import. They are written
TWICE — once the moment collection finishes, and again at session finish with
the exit status filled in — so a later hook that dies (a conftest's own
end-of-session guard, say) cannot take the census down with it. A caller that
finds `"exitstatus": null` is reading the early copy and knows it.

chip-AGNOSTIC / tool-AGNOSTIC / PDK-AGNOSTIC: pytest bookkeeping only.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from typing import Dict

#: Set by the caller. Absent means "not being used as a census probe", and the
#: plugin then does nothing at all rather than guessing a path to write to.
_OUT_ENV = "ZERO_COLLECT_PROBE_OUT"

#: file nodeid -> the collector outcome pytest reported for it.
_outcome: Dict[str, str] = {}
#: file nodeid -> how many LEAF items were collected from it.
_items: Counter = Counter()


def pytest_collectreport(report) -> None:
    """Discovery + classification. Fires for every module pytest DECIDED to collect."""
    nodeid = getattr(report, "nodeid", "") or ""
    if not nodeid.endswith(".py"):
        # Session / Dir / Package collectors. Only file-level rows are the
        # subject; a directory that collects nothing is a directory with no
        # test files in it, which is not the defect being looked for.
        return
    # A module reported more than once (a Package re-walk) keeps the WORST
    # outcome, so a failure can never be overwritten by a later clean report.
    prev = _outcome.get(nodeid)
    now = getattr(report, "outcome", "unknown")
    _outcome[nodeid] = now if prev is None or prev == "passed" else prev
    _items.setdefault(nodeid, 0)


def pytest_itemcollected(item) -> None:
    """The count. One call per LEAF item — the things that would actually run."""
    nodeid = getattr(item, "nodeid", "") or ""
    path = nodeid.split("::", 1)[0]
    if path.endswith(".py"):
        _items[path] += 1


def pytest_collection_finish(session) -> None:
    """Write the census as soon as it EXISTS, before anything else can fail."""
    _dump(session, None)


def pytest_sessionfinish(session, exitstatus) -> None:
    _dump(session, exitstatus)


def _dump(session, exitstatus) -> None:
    out = os.environ.get(_OUT_ENV)
    if not out:
        return
    files = set(_outcome) | set(_items)
    payload = {
        "rows": [{"file": f,
                  "nodes": int(_items.get(f, 0)),
                  "outcome": _outcome.get(f, "unreported")}
                 for f in sorted(files)],
        "rootdir": str(getattr(session.config, "rootpath", "")),
        "exitstatus": None if exitstatus is None else int(exitstatus),
    }
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
    os.replace(tmp, out)
