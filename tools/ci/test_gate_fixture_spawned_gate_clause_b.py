"""The `spawned gate whose status is discarded` fixture must keep clause B LOOKING.

WHY THIS FILE EXISTS, and it is not a duplicate of
`test_gate_fixtures_discriminate.py`.

That file asks one question of every fixture: does the pair MOVE THE VERDICT —
can_pass accepted, can_fail refused. For this fixture the verdict is moved by
CLAUSE A alone (a gate spawn whose status is discarded), so the pair keeps
discriminating whether or not clause B has a subject at all.

That leaves a hole with a name. Clause B's population in the real tree is ONE
module, `full_suite_run_check.py`, and the fixture reproduces it in BOTH arms so
the printed denominators differ in exactly one number. Delete that stub and the
fixture still passes `test_fixture_pair_discriminates` — green because clause B
had nothing to look at, which is the same shape of evidence as a gate that is
declared and never invoked.

The register moved underneath this fixture once already. It was written when
`spawned_gate_status_inventory.json` carried one row naming that file, so the
stub was deliberately TOKEN-FREE to reproduce the row; the owner-level ruling of
2026-08-31 PAID that row off (`"known": []`), and from that moment the token-free
stub manufactured an UNACCOUNTED finding and the CAN-PASS arm could not pass.
The stub is now the post-shrink shape — in the population, and observing a run.

So this asserts what the pair cannot: clause B has EXACTLY ONE subject and ZERO
findings, in BOTH directions. A regression to the token-free shape reddens it,
and so does dropping the stub — which is the case nothing else notices.
"""
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import gate_mutation_fixtures as F  # noqa: E402

GATE = "spawned gate whose status is discarded"

_POPULATION = re.compile(r"^\s*clause B population:\s+(\d+)", re.MULTILINE)
_FINDINGS = re.compile(r"^\s*run-subject, cannot run \(B\):\s+(\d+)", re.MULTILINE)


def _denominators(text: str):
    pop, found = _POPULATION.search(text or ""), _FINDINGS.search(text or "")
    assert pop and found, (
        "the gate did not print clause B's denominators, so nothing here is "
        f"measured — output was:\n{text}")
    return int(pop.group(1)), int(found.group(1))


@pytest.fixture(scope="module")
def arms():
    decls = {d.label: d for d in F.declarations()}
    fixtures = {f.gate: f for f in F.load_fixtures().values()}
    assert GATE in decls, f"{GATE!r} is not a declared gate"
    assert GATE in fixtures, f"no fixture names {GATE!r}"
    ok_pass, ok_fail = F.run_pair(decls[GATE], fixtures[GATE])
    return ok_pass, ok_fail


def test_clause_b_has_a_subject_and_no_finding_in_BOTH_arms(arms):
    """The population is the load-bearing number.

    `1` says the clause had something to judge. `0` says it judged it clean.
    A `0` population would be a green earned by having no subject, and the
    pair-discrimination test cannot tell that from a real pass.
    """
    for name, verdict in zip(("can_pass", "can_fail"), arms):
        assert verdict.outcome is not None, f"{name}: the gate did not run"
        population, findings = _denominators(verdict.outcome.output)
        assert population == 1, (
            f"{name}: clause B's population is {population}, not 1 — the "
            f"fixture no longer gives clause B a subject, so a green arm here "
            f"means nothing was looked at")
        assert findings == 0, (
            f"{name}: clause B reports {findings} finding(s) — the fixture's "
            f"run-subject stub cannot observe a run. The inventory row it used "
            f"to reproduce was PAID OFF on 2026-08-31 and `known` is now empty, "
            f"so an unaccounted finding here is rc 1 in both directions")


def test_only_clause_A_moves_between_the_two_arms(arms):
    """The fixture's stated contract: one number changes, and it is clause A's."""
    ok_pass, ok_fail = arms
    assert ok_pass.outcome and ok_fail.outcome
    assert _denominators(ok_pass.outcome.output) == \
        _denominators(ok_fail.outcome.output), (
        "clause B's denominators MOVED between the arms; the mutation is "
        "supposed to touch clause A only")
    assert ok_pass.outcome.rc == 0, ok_pass.detail
    assert ok_fail.outcome.rc == 1, ok_fail.detail
