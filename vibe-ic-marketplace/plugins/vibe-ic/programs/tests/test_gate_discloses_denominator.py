#!/usr/bin/env python3
"""A PASS must say how much it looked at (vibe-ic#447).

Four gates in this repo answered PASS after examining nothing, each from a
different walking bug, and all four were invisible from the output. This is the
regression guard for the fifth.

The design decision worth pinning: the discriminator is DISCLOSURE, not
verdict. A gate is allowed to PASS over zero items — `tracked_symlink_
portability_check` on a tree with no symlinks is genuinely clean — as long as a
reader can SEE it was zero. Demanding a FAIL instead would fire on legitimate
state, which is what got the orphan-capability detector (#439) deleted rather
than landed.

Measured while building: a first discriminator looked only at the LAST line for
a digit and flagged 5 of 25, four of them falsely — `tracked_symlink_
portability_check` prints `dangling ...: 0` on the line ABOVE its verdict, and
`artefact_defect_close_check` says `[SKIPPED] no issue corpus`, which IS the
disclosure. Whole-output scanning gives 0 of 25.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import gate_discloses_denominator_check as G  # noqa: E402

_REPO = _PROGRAMS.parents[3]   # plugins/vibe-ic/programs -> repo root


def _fake_repo(tmp_path: Path, gate_bodies: dict) -> Path:
    """A repo whose CI script names throwaway gates written into programs/."""
    r = tmp_path / "repo"
    (r / "tools" / "ci").mkdir(parents=True)
    lines = []
    for name, body in gate_bodies.items():
        (_PROGRAMS / f"_probe_{name}.py").write_text(body)
        lines.append(f'run "{name}" "$ROOT" python3 "$PG/_probe_{name}.py"')
    (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        "\n".join(lines) + "\n")
    return r


def _cleanup(names):
    for n in names:
        p = _PROGRAMS / f"_probe_{n}.py"
        if p.exists():
            p.unlink()


def test_a_silent_pass_over_an_empty_tree_is_caught(tmp_path):
    """THE LOAD-BEARING CASE."""
    try:
        r = _fake_repo(tmp_path, {"silent": 'print("PASS: everything is fine")\n'})
        verdict, findings = G.audit(r)
        assert verdict == "FAIL", findings
        assert findings[0]["kind"] == "PASS_WITHOUT_DENOMINATOR"
        assert findings[0]["gate"] == "silent"
    finally:
        _cleanup(["silent"])


def test_a_pass_that_states_a_count_is_accepted(tmp_path):
    """The paired half. A gate that says how many is honest even at zero."""
    try:
        r = _fake_repo(tmp_path, {
            "honest": 'print("PASS (0 item(s) examined): nothing to check")\n'})
        verdict, findings = G.audit(r)
        assert verdict == "PASS", findings
    finally:
        _cleanup(["honest"])


def test_an_explicit_nothing_to_check_is_accepted_without_a_number(tmp_path):
    """`artefact_defect_close_check` says "[SKIPPED] no issue corpus" and that
    IS the disclosure — a count is one way to be honest, not the only way."""
    try:
        r = _fake_repo(tmp_path, {
            "skipper": 'print("[SKIPPED] no issue corpus present")\n'})
        verdict, findings = G.audit(r)
        assert verdict == "PASS", findings
    finally:
        _cleanup(["skipper"])


def test_a_gate_that_FAILS_on_empty_is_not_flagged(tmp_path):
    """Only a PASS makes a claim. A non-zero exit is not a false certificate,
    whatever it prints."""
    try:
        r = _fake_repo(tmp_path, {
            "failer": 'import sys\nprint("nope")\nsys.exit(1)\n'})
        verdict, findings = G.audit(r)
        assert verdict == "PASS", findings
    finally:
        _cleanup(["failer"])


def test_an_empty_gate_list_is_NOT_a_pass(tmp_path):
    """This program's own denominator. Parsing zero gates and reporting clean
    would be the exact defect it exists to catch, one level up."""
    r = tmp_path / "repo"
    (r / "tools" / "ci").mkdir(parents=True)
    (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text("# no gates\n")
    verdict, findings = G.audit(r)
    assert verdict == "NOTHING_SCANNED", (verdict, findings)


def test_a_missing_ci_script_is_NOT_a_pass(tmp_path):
    verdict, _ = G.audit(tmp_path / "nowhere")
    assert verdict == "NOTHING_SCANNED"


def test_the_gate_list_is_PARSED_from_the_ci_script_not_duplicated():
    """A second hand-maintained list would drift, and a gate added to CI would
    silently escape this check."""
    gates = G.parse_gates(_REPO / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert len(gates) >= 20, len(gates)
    labels = {g[0] for g in gates}
    assert "chip-AGNOSTIC source guard" in labels, sorted(labels)[:5]


#: What this test is allowed to spend driving real gates, vibe-ic#1181.
#: Without it the walk is 74 gates x 120s = 148 minutes, the wait is inside
#: `subprocess.communicate` where `--timeout-method=thread` cannot reach it,
#: and the INVOCATION produces no summary line at all — so every other file in
#: the selection goes unmeasured and the run greps as neither pass nor fail.
_CI_WALK_BUDGET_S = 90.0
_CI_GATE_TIMEOUT_S = 20


def test_the_real_ci_gate_set_is_currently_clean():
    """The measured state at land time: every CI gate discloses what it
    examined. A zero baseline is the right shape for a regression guard — it
    can only fire on a NEW instance.

    BOUNDED (#1181). `BUDGET_EXHAUSTED` is accepted here and `PASS` is
    accepted; what is refused is a FINDING. Truncating the walk must not be
    able to turn a real finding green, and it cannot: a gate that answered a
    bare PASS is recorded the moment it is driven, so any finding at all fails
    this regardless of how far the walk got.
    """
    import pytest
    script = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not script.is_file():
        pytest.skip("CI script not present")
    verdict, findings = G.audit(_REPO, timeout=_CI_GATE_TIMEOUT_S,
                                budget=_CI_WALK_BUDGET_S)
    assert not findings, findings
    assert verdict in ("PASS", "BUDGET_EXHAUSTED"), verdict


def test_an_exhausted_budget_is_never_a_bare_PASS(tmp_path):
    """#1181. A walk that stopped early examined fewer gates than it declared,
    and "no findings" over a truncated population is not the same sentence as
    "no findings". The verdict has to say so, or a bounded run is
    indistinguishable from a complete one — which is this program's own
    subject."""
    import pytest
    script = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not script.is_file():
        pytest.skip("CI script not present")
    res = G.audit_ci(_REPO, timeout=5, budget=0.0)
    assert res.verdict == "BUDGET_EXHAUSTED", res.verdict
    assert res.probed < res.declared, (res.probed, res.declared)
    assert res.declared >= 20, res.declared


def test_the_skipped_gates_are_NAMED_with_the_reason(tmp_path):
    """The inverse: a bound that shrinks the denominator silently would be a
    worse defect than the hang. `not_driven` carries the label AND why."""
    import pytest
    script = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not script.is_file():
        pytest.skip("CI script not present")
    res = G.audit_ci(_REPO, timeout=5, budget=0.0)
    budgeted = [(lab, why) for lab, why in res.not_driven
                if "aggregate budget" in why]
    assert budgeted, res.not_driven[:3]
    assert len(budgeted) == res.declared - res.probed - (
        len(res.not_driven) - len(budgeted))
    for lab, why in budgeted[:3]:
        assert lab and "#1181" in why, (lab, why)
