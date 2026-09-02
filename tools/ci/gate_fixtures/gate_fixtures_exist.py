"""`gate fixtures exist` — a declared gate with no fixture and no debt entry.

THE MUTATION IS THE CENSUS'S OWN HEADLINE CASE, stated by its docstring: "a NEW
gate is outside the baseline by construction, so a gate added without both
FAILS". That is the shape a fixture pair for this row has to reach, and it is
the one the EXECUTING row beside it cannot see — a gate with no fixture has no
pair to run, so the executor reports nothing about it and passes. The two rows
fail on different things and neither implies the other.

BOTH ARMS HAVE THE SAME DENOMINATOR, and here it takes two declared gates to
build one. A subject with a single gate and no fixture at all would also give a
non-empty `gate_fixtures/` nothing to load, and an empty fixture directory is a
different refusal from a gate that is missing ITS fixture — the arms would then
differ in two things and the pair would not name which one it proved. So both
arms declare TWO gates and carry a fixture for the first; what moves is whether
the SECOND gate has one.

WHAT IS DELIBERATELY THE SAME. A present, well-formed, shrink-only
`gate_fixture_debt.json` with an empty `entries` list — present in both, so the
refusal is never "the baseline could not be read", and empty in both, so the
can-fail arm cannot be excused into a pass by a debt entry the can-pass arm
lacks. A fixture module that is a real module with both callables. A
declaration script in the dispatcher's real shape.

THE ENGINE IS NOT COPIED IN. The declaration spells the program
`$RUNTIME_ROOT/tools/ci/gate_mutation_fixture_check.py` and the three subject
artefacts through `$ROOT` — `--script`, `--fixtures`, `--debt`, all of which the
program already ships. So the parser, the slug rule and their import closure are
the REAL ones and only the judged tree is synthetic. Nothing here can drift from
the program, because nothing here is a copy of it.

THE FIXTURE MODULES IN THE SUBJECT ARE NEVER EXECUTED by this gate — the census
imports them to ask which callables they define, and stops. They are still
written as real, callable fixtures rather than empty stubs, because the census
checks `callable(...)` and a stub that satisfied that check while doing nothing
would be the same false evidence this whole regime exists to refuse.

chip-AGNOSTIC: two invented gate names. No IC, vendor, PDK or process.
"""
from pathlib import Path
import json

GATE = "gate fixtures exist"

#: The two gates the synthetic dispatcher declares. The FIRST always has its
#: fixture; the second is the variable.
_FIRST, _SECOND = "toy alpha", "toy beta"

_SCRIPT = '''#!/usr/bin/env bash
# Synthetic declaration script — a fixture subject, not a runnable sweep.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_ROOT="$(cd "$HERE/../.." && pwd)"
ROOT="${VIBEIC_SUBJECT_ROOT:-$RUNTIME_ROOT}"
. "$HERE/_gate_dispatch.sh"
gate_dispatch_init "$@"
run "%s" "$ROOT" python3 "$ROOT/toy_alpha_check.py" "$ROOT"
run "%s" "$ROOT" python3 "$ROOT/toy_beta_check.py" "$ROOT"
''' % (_FIRST, _SECOND)

_FIXTURE = '''"""Synthetic fixture for {gate!r} — a real pair, never a stub."""
from pathlib import Path

GATE = {gate!r}


def can_pass(work: Path) -> Path:
    root = work / "accepted"
    root.mkdir(parents=True, exist_ok=True)
    return root


def can_fail(work: Path):
    root = work / "refused"
    root.mkdir(parents=True, exist_ok=True)
    (root / "REFUSE_ME").write_text("x", encoding="utf-8")
    return root, "REFUSED"
'''

#: An empty debt register, in the real file's shape. `entries: []` in BOTH
#: arms, so a missing fixture is never excused in one and not the other.
_DEBT = {
    "schema": 1,
    "kind": "gate-fixture-debt",
    "baseline_taken_at": "synthetic-fixture-subject",
    "note": "Synthetic, empty on purpose: this subject exists to show a gate "
            "with no fixture being refused, and a debt entry is exactly what "
            "would excuse it.",
    "entries": [],
}


def _tree(work: Path, leaf: str, second_has_fixture: bool) -> Path:
    root = work / leaf
    ci = root / "tools" / "ci"
    fixtures = ci / "gate_fixtures"
    fixtures.mkdir(parents=True)
    (ci / "repo_hygiene_gates.sh").write_text(_SCRIPT, encoding="utf-8")
    (ci / "gate_fixture_debt.json").write_text(
        json.dumps(_DEBT, indent=2) + "\n", encoding="utf-8")
    (fixtures / "toy_alpha.py").write_text(
        _FIXTURE.format(gate=_FIRST), encoding="utf-8")
    if second_has_fixture:
        (fixtures / "toy_beta.py").write_text(
            _FIXTURE.format(gate=_SECOND), encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Two declared gates, two fixtures, an empty debt register: rc 0."""
    return _tree(work, "accepted", second_has_fixture=True)


def can_fail(work: Path):
    """The same two gates, and the second one's fixture never written — a gate
    that landed without a pair and is in no baseline. Same denominator,
    opposite answer."""
    return _tree(work, "refused", second_has_fixture=False), _SECOND
