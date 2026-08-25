"""`registry is the iteration domain` — a finding loop that walks the opt-in
list instead of filtering with it.

THE MUTATION IS THE MEASURED DEFECT ITSELF, in the gate's own words:

    for row in ledger:            <- the registry is the iteration target
        if bad(row): findings.append(...)          THE DEFECT

    for cand in derived_population():              the correct filter
        if cand.id in registry: continue
        if bad(cand): findings.append(...)

Both subjects carry the SAME two enforcement modules, the SAME two tracked
registries, and the SAME two loops in each. `waiver_filter_check` iterates its
derived population in one loop and its registry in the other in BOTH arms. What
the mutation changes is which of those two loops EMITS A FINDING — the answer,
not the corpus.

THE DENOMINATORS THE GATE PRINTS ARE IDENTICAL IN BOTH DIRECTIONS, and that is
deliberate rather than incidental. Measured:

    modules parsed                        2   ->   2
    modules reading a tracked registry    2   ->   2
    of those, within the clause's reach   2   ->   2
    finding-emitting registry loops       1   ->   2      <- the answer
    inventory rows applied                1   ->   1

Holding the THIRD line still is what costs something. The obvious can-pass —
`waiver_filter_check` appending its findings from the derived loop, which is
the textbook remedy shape — would EXCULPATE that module by the clause's own
rule and drop the reach to 1, so the red arm would differ from the green one in
a printed population as well as in the verdict. Making the registry loop a
COUNTING loop instead keeps the module in reach in both arms, so the ONLY line
that moves between them is the finding count. An empty subject prints
`modules parsed: 0` and is the vacuity path this fixture must not take.

THE SHIPPED INVENTORY IS PART OF THE SUBJECT'S CONTRACT. `$PG` stays the real
programs tree, so the gate reads its REAL
`registry_iteration_domain_inventory.json` — whose single row names
`gate_red_since_check.py::gate_red_since.json::ledger::row`. An inventory row
that matches nothing is rc 1 by this gate's design, so a subject that simply
omitted that module would go red for STALENESS and prove nothing about the
predicate. Both arms therefore reproduce that row's shape exactly, which is
also what makes the green arm green.

chip-AGNOSTIC: nothing here names any IC, vendor, SKU or process.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402,F401 — the protocol's home

GATE = "registry is the iteration domain"

_PROGRAMS_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"

#: The module the SHIPPED inventory already names, reproduced at the relative
#: path and with the loop identity that row keys on. Present, unchanged, in
#: BOTH arms: without it the real inventory row is stale and the gate is rc 1
#: for a reason that has nothing to do with the mutation.
_INVENTORIED = '''#!/usr/bin/env python3
"""A check whose only finding-emitting loop iterates its acknowledgement ledger."""
import json
from pathlib import Path


def _tree(root):
    """The population this module CAN see — and never asks a finding about."""
    return sorted(Path(root).rglob("*.py"))


def scan(root):
    ledger = json.loads((Path(root) / "gate_red_since.json").read_text())
    failures = []
    for row in ledger:
        failures.append(row)
    return failures
'''

#: Two loops, one over a derived population and one over the registry. In this
#: arm NEITHER emits a finding: the registry loop counts. The module is a
#: registry reader and is within the clause's reach, so it holds both of those
#: denominators up without contributing a finding.
_FILTER = '''#!/usr/bin/env python3
"""A check that uses its registry as a FILTER over a derived population."""
import json
from pathlib import Path


def _population(root):
    return sorted(Path(root).rglob("*.py"))


def scan(root):
    waived = json.loads((Path(root) / "fixture_waivers.json").read_text())
    failures = []
    seen = 0
    for cand in _population(root):
        if cand.name in waived:
            continue
        seen += 1
    for row in waived:
        seen += 1
    return failures, seen
'''

#: THE MUTATION. Same file, same two loops, same registry, same derived
#: population. The finding emission moves onto the registry loop, so the only
#: question this module now answers is one about entries somebody volunteered.
_ITERATES = _FILTER.replace(
    "    for row in waived:\n"
    "        seen += 1\n",
    "    for row in waived:\n"
    "        failures.append(row)\n",
)
assert _ITERATES != _FILTER, "the mutation did not apply"


def _tree(work: Path, waiver_module: str) -> Path:
    root = work / "subject"
    programs = root / _PROGRAMS_REL
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "gate_red_since_check.py").write_text(_INVENTORIED,
                                                      encoding="utf-8")
    (programs / "waiver_filter_check.py").write_text(waiver_module,
                                                     encoding="utf-8")
    # The registries themselves. A `.json` name that resolves to nothing on
    # disk is an OUTPUT name by this gate's rule, not a registry, so these have
    # to EXIST for either module to count as a registry reader at all.
    (programs / "gate_red_since.json").write_text("[]\n", encoding="utf-8")
    (programs / "fixture_waivers.json").write_text("[]\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """One registry-iterating finding loop, and it is the inventoried one."""
    return _tree(work, _FILTER)


def can_fail(work: Path):
    """A SECOND one arrives, outside the inventory, from the same population."""
    return _tree(work, _ITERATES), \
        "finding-emitting loop(s) iterate an opt-in registry"
