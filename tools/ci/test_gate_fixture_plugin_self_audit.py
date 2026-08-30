"""The claims `gate_fixtures/plugin_self_audit.py` makes about its own pair.

`test_gate_fixtures_discriminate` runs that pair and asks only whether the two
directions differ. That is not enough here. `plugin self-audit` is a
DISPATCHER over seven checkers, so "rc 0 then rc 1" is satisfied by any of
seven refusals — including a checker dying of a missing file, which is the
shape the first draft of this fixture actually had (`ModuleNotFoundError: No
module named '_commercial_pdk'`, reported by the loop as a gate FAILING).

So this file measures the three things the fixture's prose asserts:

  * exactly ONE dispatched gate changes verdict between the arms, and it is
    the one the mutation is aimed at;
  * the fabricated number is genuinely absent from the subject's source, which
    is what makes the metric unreproducible rather than merely unrecognised —
    the subject carries copies of the shipped checkers, so this is a
    measurement and not a definition;
  * no gate refuses in either arm for want of a file the subject failed to
    carry.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import gate_mutation_fixtures as F  # noqa: E402

sys.path.insert(0, str(F.PROGRAMS))
import changelog_metric_reproducibility_check as _metric  # noqa: E402

_FIXTURE = F.load_fixtures()["plugin_self_audit"]
_DECL = {d.label: d for d in F.declarations()}[_FIXTURE.gate]
_TARGET = "changelog_metric_reproducibility_check"

#: `=== <gate> ===` then that gate's own output, up to the next header.
_SECTION = re.compile(r"^=== (?P<gate>\S+) ===$")


def _verdicts(output: str) -> dict:
    """{gate: its block of output}, in the dispatcher's own framing."""
    out, cur = {}, None
    for line in output.splitlines():
        m = _SECTION.match(line)
        if m:
            cur = m.group("gate")
            out[cur] = []
            continue
        if cur is not None and not line.startswith("==> "):
            out[cur].append(line)
    return {g: "\n".join(v).strip() for g, v in out.items()}


@pytest.fixture(scope="module")
def arms():
    """Both directions, run once, kept for every assertion below.

    The output is returned with each arm's own scratch path rewritten to
    `<SUBJECT>`. Without that, `unanchored_process_kill_check` names the tree
    it walked and its two blocks differ in every run — a text difference that
    is not a verdict difference, and it would make
    `test_exactly_one_dispatched_gate_moves_between_the_arms` red for a reason
    that has nothing to do with the mutation."""
    with tempfile.TemporaryDirectory(prefix="sa-pass-") as a, \
            tempfile.TemporaryDirectory(prefix="sa-fail-") as b:
        good_root = Path(_FIXTURE.module.can_pass(Path(a)))
        good = F.invoke(_DECL, good_root)
        bad_root, _ = _FIXTURE.module.can_fail(Path(b))
        bad = F.invoke(_DECL, Path(bad_root))
        yield (good._replace(output=good.output.replace(str(good_root),
                                                        "<SUBJECT>")),
               bad._replace(output=bad.output.replace(str(bad_root),
                                                      "<SUBJECT>")))


def test_the_two_arms_are_rc_0_and_rc_1(arms):
    good, bad = arms
    assert good.rc == 0, good.output
    assert bad.rc == 1, good.output + "\n----\n" + bad.output


def test_exactly_one_dispatched_gate_moves_between_the_arms(arms):
    """Six of the seven are the control, and they are named."""
    good, bad = arms
    g, b = _verdicts(good.output), _verdicts(bad.output)
    assert set(g) == set(b), (sorted(g), sorted(b))
    assert len(g) >= 7, sorted(g)
    moved = sorted(k for k in g if g[k] != b[k])
    assert moved == [_TARGET], moved
    unchanged = sorted(k for k in g if g[k] == b[k])
    assert len(unchanged) == len(g) - 1, unchanged


def test_no_gate_refuses_for_want_of_a_file_the_subject_did_not_carry(arms):
    """The failure mode this file exists for.

    A dispatcher whose checker cannot be imported reports rc 1 and prints
    `-> FAIL`, which is indistinguishable at the exit code from finding the
    mutation. Both arms are checked: the good one because a subject that
    cannot run the gates proves nothing by passing them, the mutated one
    because that is where a coincidental refusal would hide."""
    for name, got in zip(("can_pass", "can_fail"), arms):
        for bad in ("No such file or directory", "ModuleNotFoundError",
                    "Traceback (most recent call last)", "(rc=2)"):
            assert bad not in got.output, f"{name}: {bad}\n{got.output}"


def test_the_mutated_number_is_absent_from_the_subject_corpus(arms):
    """MEASURED, not defined: the subject ships copies of real checkers."""
    with tempfile.TemporaryDirectory(prefix="sa-corpus-") as t:
        subject, _ = _FIXTURE.module.can_fail(Path(t))
        corpus = "\n".join(
            p.read_text(encoding="utf-8", errors="replace")
            for p in sorted((Path(subject) / "programs").rglob("*.py")))
        fabricated = _FIXTURE.module._FABRICATED_MARGIN
        true_value = _FIXTURE.module._TRUE_MARGIN
        # THE GATE'S OWN PREDICATE, not a substring test. `98.7` DOES occur in
        # the corpus, inside `98.72 %` in a copied checker's own prose, and a
        # substring test called that a match; the gate does not, because
        # `_number_present` anchors on digit boundaries. Re-deriving the rule
        # here would make this test disagree with the thing it is checking.
        assert not _metric._number_present(fabricated, corpus), (
            f"{fabricated!r} is reproducible from the subject's own source, "
            f"so the can-fail arm would be green for the wrong reason")
        assert _metric._number_present(true_value, corpus), (
            f"{true_value!r} is NOT reproducible from the subject's source, "
            f"so the can-pass arm is not passing because the metric traces back")
