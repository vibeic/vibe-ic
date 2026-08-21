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

import pytest
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


#: vibe-ic#1277. This assertion used to be ONE pytest item that re-drove the
#: whole CI population: 188.61s MEASURED, against the targeted subset's 180s
#: harness bound. `--timeout-method=thread` does not fail the test at that
#: bound, it takes the SESSION down — so the item could never pass, and every
#: other file in the subset lost its verdict with it. Observed live while
#: verifying #1180: both arms died at ~23% of a 50-file selection.
#:
#: The remedy is per-gate items, not a smaller assertion. Same population, same
#: judgement, same code path (`G.judge_one`, which `audit_ci` also calls) —
#: MEASURED, the slowest single gate is 31.46s, so every item now sits ~6x
#: under the bound. #1241's other option, moving the test out of the targeted
#: subset, is wrong here: this is not a fast test dodging the rule, and the
#: repo has no subset-exclusion mechanism to move it with.
_CI_SCRIPT = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
_CI_GATES = G.parse_declarations(_CI_SCRIPT) if _CI_SCRIPT.is_file() else []


@pytest.fixture(scope="module")
def _ci_scratch():
    """Built ONCE for the whole module. MEASURED at 0.07s, so rebuilding it per
    item would cost only ~5.5s over 74 gates — shared anyway, because the
    per-gate items are then measuring the gate and nothing else."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        yield G._scratch_repo(Path(td))


@pytest.mark.skipif(not _CI_GATES, reason="CI script not present")
@pytest.mark.parametrize("decl", _CI_GATES,
                         ids=[d.label[:48] for d in _CI_GATES])
def test_each_real_ci_gate_discloses_its_denominator(decl, _ci_scratch):
    """The measured state at land time, one gate at a time: every CI gate
    discloses what it examined. A zero baseline is the right shape for a
    regression guard — it can only fire on a NEW instance, and now it names
    WHICH gate rather than handing back a list."""
    finding, _why = G.judge_one(decl, _REPO, _ci_scratch)
    assert finding is None, finding


def test_the_ci_population_is_large_enough_to_be_a_denominator():
    """The split must not become a green run over an empty parametrisation —
    zero items would pass vacuously and look identical to a clean sweep."""
    if not _CI_SCRIPT.is_file():
        pytest.skip("CI script not present")
    assert len(_CI_GATES) >= 20, len(_CI_GATES)


def test_judge_one_still_FIRES_on_a_gate_that_passes_without_disclosing(tmp_path):
    """PAIRED GUARD. The split is only safe if the per-gate judgement can still
    fail. Drives a synthetic gate that exits 0 and discloses nothing, through
    the SAME entry point the parametrised test uses, and requires a finding."""
    liar = tmp_path / "liar.py"
    liar.write_text("print('[PASS] everything is fine')\n", encoding="utf-8")
    decl = G.GateDecl(label="synthetic liar", cwd_token="$ROOT",
                      cmd=f"python3 {liar}", lineno=0, runtime_expansion=None)
    finding, why = G.judge_one(decl, _REPO, tmp_path)
    assert why is None, why
    assert finding is not None and finding["kind"] == "PASS_WITHOUT_DENOMINATOR", finding
