"""Every fixture in the tree is EXECUTED here, in both directions.

`gate_mutation_fixture_check` asks whether the two fixtures exist. A fixture
that exists and is never run is the same shape of evidence as a gate that is
declared and never invoked — which is the defect the whole exercise is about.
So the census and the execution are two programs, and this file is what makes
the second one block a landing.

The gate is driven EXACTLY as `repo_hygiene_gates.sh` declares it. See
`gate_mutation_fixtures` for why the fixture may choose the input and never the
argv, and for the measurement (`container exec deadlines`) that made the rule
necessary.
"""
import sys
import tempfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import gate_mutation_fixtures as F  # noqa: E402
import gate_fixture_runner as RUNNER  # noqa: E402

_DECLS = {d.label: d for d in F.declarations()}
_FIXTURES = sorted(F.load_fixtures().values(), key=lambda f: f.slug)


def test_there_is_at_least_one_fixture_to_run():
    """A suite that executed zero fixtures would report green over nothing."""
    assert _FIXTURES, "no fixture module under tools/ci/gate_fixtures"


@pytest.mark.parametrize("fx", _FIXTURES, ids=[f.slug for f in _FIXTURES])
def test_fixture_pair_discriminates(fx):
    decl = _DECLS.get(fx.gate)
    assert decl is not None, f"{fx.path.name} names an undeclared gate {fx.gate!r}"
    ok_pass, ok_fail = F.run_pair(decl, fx)
    assert ok_pass.ok, f"{fx.gate}: {ok_pass.detail}"
    assert ok_fail.ok, f"{fx.gate}: {ok_fail.detail}"


def test_the_runner_catches_a_mutation_that_does_not_move_the_verdict():
    """The engine's own discrimination, proved by weakening a fixture.

    A can-fail fixture that returns a CLEAN subject is the exact way this
    mechanism could be made to pass without checking anything — write the
    function, skip the mutation. The runner must refuse it, and refuse it for
    saying so rather than for crashing.
    """
    real = next(f for f in _FIXTURES if f.slug == "tracked_json_yaml_parses")
    decl = _DECLS[real.gate]

    class _Weak:
        can_pass = staticmethod(real.module.can_pass)

        @staticmethod
        def can_fail(work):
            # The mutation is omitted. The subject is the GOOD one.
            return real.module.can_pass(work), "do not parse"

    weak = real._replace(module=_Weak)
    with tempfile.TemporaryDirectory() as t:
        v = F.run_can_fail(decl, weak, Path(t))
    assert not v.ok
    assert "was ACCEPTED (rc 0)" in v.detail
    assert "does not move the gate's verdict" in v.detail


def test_the_runner_catches_a_refusal_for_the_wrong_reason():
    """rc != 0 is not enough: the refusal has to be the declared one.

    A gate that refuses because its argument was garbage looks identical, at
    the exit code, to one that refused because it found the mutation. That is
    the forged-input shape of vibe-ic#1745 one level up, and it is why the
    can-fail direction carries an expected message at all.
    """
    real = next(f for f in _FIXTURES if f.slug == "tracked_json_yaml_parses")
    decl = _DECLS[real.gate]

    class _Wrong:
        can_pass = staticmethod(real.module.can_pass)

        @staticmethod
        def can_fail(work):
            subject, _ = real.module.can_fail(work)
            return subject, "a sentence this gate never prints"

    wrong = real._replace(module=_Wrong)
    with tempfile.TemporaryDirectory() as t:
        v = F.run_can_fail(decl, wrong, Path(t))
    assert not v.ok
    assert "NOT for the declared reason" in v.detail
    assert "a coincidence, not a check" in v.detail


def test_the_runner_refuses_an_empty_selection(capsys):
    """Running no fixture is NOT_CHECKED (rc 2), never a pass."""
    rc = RUNNER.main(["--gate", "a gate that does not exist"])
    out = capsys.readouterr().err
    assert rc == 2, out
    assert "NOT CHECKED" in out
    assert "not a pass" in out


def test_a_fixture_may_not_redirect_the_gates_OWN_code():
    """`$PG` stays the real programs tree; only the subject is redirected.

    Redirecting it would run a fixture's copy of the gate, which proves
    nothing about the gate that lands.
    """
    argv = F._resolve_argv(
        'python3 "$PG/x_check.py" --root "$ROOT" "$PLUGIN"', Path("/subject"))
    assert argv[1] == str(F.PROGRAMS / "x_check.py")
    assert argv[3] == "/subject" and argv[4] == "/subject"
