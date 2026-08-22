"""`absence verdicts name where they looked` — a refusal that says nothing.

THE MUTATION IS THE MEASURED DEFECT ITSELF, in the gate's own words: a step
refused a thing the distribution declares, in a view it never opened, and the
sentence it printed carried a count instead of a search space. "Not found" and
"not looked for" then print the same way.

BOTH TREES CARRY TWO ABSENCE VERDICTS, and the mutation changes ONE of them.
Nothing is deleted: the population the gate walks is identical in both
directions (same files, same verdict count), so the direction that goes red
goes red because an ANSWER changed and not because a corpus vanished. A subject
with no absence verdict in it at all is rc 2 by this gate's own rule — that
refusal is the empty-corpus path, and proving it would prove nothing about the
predicate under test.

WHY THE SILENT MESSAGE IS WORDED THE WAY IT IS. The gate's locus vocabulary is
deliberately generous (`--explain` prints it), and it matches on SUBSTRINGS: a
sentence carrying `name`, `loc` or `abs` anywhere in it already discloses a
locus by the rule as written. The can-fail sentence is therefore chosen to
contain none of them — a mutation that accidentally kept a locus would report a
green the gate did not earn.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "absence verdicts name where they looked"

_PROGRAMS_REL = "programs"

#: A refusal that DOES say where it looked: the search space is interpolated
#: from the variable that holds it, which is the shape the gate accepts.
_DISCLOSING = '''"""A synthetic emitter that refuses and says where it looked."""


def _emit(rule_id, detail):
    return {"rule": rule_id, "detail": detail}


def resolve_site(site, lef_paths):
    for candidate in lef_paths:
        if candidate.get(site):
            return candidate[site]
    return _emit("SITE_NOT_FOUND",
                 f"no entry for {site} in any of {lef_paths}")


def resolve_corner(corner, view_paths):
    for candidate in view_paths:
        if candidate.get(corner):
            return candidate[corner]
    return _emit("CORNER_CELL_ABSENT",
                 f"no entry for {corner} in any of {view_paths}")
'''

#: The SAME two refusals, one of which now discloses nothing. Same file, same
#: two verdicts, same rule ids — only the sentence changed.
_SILENT = '''"""A synthetic emitter that refuses and says where it looked."""


def _emit(rule_id, detail):
    return {"rule": rule_id, "detail": detail}


def resolve_site(site, lef_paths):
    for candidate in lef_paths:
        if candidate.get(site):
            return candidate[site]
    return _emit("SITE_NOT_FOUND",
                 f"no entry for {site} in any of {lef_paths}")


def resolve_corner(corner, entries):
    for item in entries:
        if item.get(corner):
            return item[corner]
    return _emit("CORNER_CELL_ABSENT",
                 "there is no entry for it among the twenty we hold")
'''


def _tree(work: Path, source: str) -> Path:
    root = work / "subject"
    programs = root / _PROGRAMS_REL
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "synthetic_site_resolver.py").write_text(source,
                                                         encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Two absence verdicts, both naming the views they read."""
    return _tree(work, _DISCLOSING)


def can_fail(work: Path):
    """The same two verdicts; the second one now names no search space."""
    root = _tree(work, _SILENT)
    return root, "absence verdict(s) name no search space"
