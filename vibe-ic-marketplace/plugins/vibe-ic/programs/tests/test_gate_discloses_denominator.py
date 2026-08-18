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
    """A repo whose CI script names throwaway gates, written INSIDE that repo.

    THE PROBES USED TO GO INTO THE LIVE `programs/` DIR. The CI line said
    `python3 "$PG/_probe_<name>.py"`, `$PG` resolves to this checkout's real
    programs directory, so each of these tests planted a `.py` there for the
    duration of its body and unlinked it in a `finally`. Serially nothing sees
    it. The landing gate's per-file parallel path runs one pytest session per
    file over ONE shared checkout, so every concurrent session enumerating
    `programs/` counted the probes — and reported the count as a property of
    the branch. The `finally` means `git status --porcelain` is clean
    afterwards, so the manufactured red leaves nothing to follow.

    `$ROOT/` resolves against the fake repo, which is under `tmp_path`. That is
    already the shape `test_a_host_excluded_gate_is_not_indirectly_launched_by_
    the_meta_sweep` uses below (`python3 "$ROOT/remote.py"`), so the resolver
    path is the one this file already exercises — and the probes now live in a
    tree this test owns.
    """
    r = tmp_path / "repo"
    (r / "tools" / "ci").mkdir(parents=True)
    (r / "programs").mkdir(parents=True, exist_ok=True)
    lines = []
    for name, body in gate_bodies.items():
        (r / "programs" / f"_probe_{name}.py").write_text(body)
        lines.append(
            f'run "{name}" "$ROOT" python3 "$ROOT/programs/_probe_{name}.py"')
    (r / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        "\n".join(lines) + "\n")
    return r


def _no_probe_reached_the_live_tree():
    """Nothing this module writes may land in the shipped programs dir."""
    strays = sorted(p.name for p in _PROGRAMS.glob("_probe_*.py"))
    assert not strays, (
        f"this test planted {strays} into the live programs dir; a concurrent "
        f"session enumerating programs/ would count them as the branch's")


def test_a_silent_pass_over_an_empty_tree_is_caught(tmp_path):
    """THE LOAD-BEARING CASE."""
    r = _fake_repo(tmp_path, {"silent": 'print("PASS: everything is fine")\n'})
    verdict, findings = G.audit(r)
    assert verdict == "FAIL", findings
    assert findings[0]["kind"] == "PASS_WITHOUT_DENOMINATOR"
    assert findings[0]["gate"] == "silent"
    _no_probe_reached_the_live_tree()


def test_a_pass_that_states_a_count_is_accepted(tmp_path):
    """The paired half. A gate that says how many is honest even at zero."""
    r = _fake_repo(tmp_path, {
        "honest": 'print("PASS (0 item(s) examined): nothing to check")\n'})
    verdict, findings = G.audit(r)
    assert verdict == "PASS", findings
    _no_probe_reached_the_live_tree()


def test_an_explicit_nothing_to_check_is_accepted_without_a_number(tmp_path):
    """`artefact_defect_close_check` says "[SKIPPED] no issue corpus" and that
    IS the disclosure — a count is one way to be honest, not the only way."""
    r = _fake_repo(tmp_path, {
        "skipper": 'print("[SKIPPED] no issue corpus present")\n'})
    verdict, findings = G.audit(r)
    assert verdict == "PASS", findings
    _no_probe_reached_the_live_tree()


def test_a_gate_that_FAILS_on_empty_is_not_flagged(tmp_path):
    """Only a PASS makes a claim. A non-zero exit is not a false certificate,
    whatever it prints."""
    r = _fake_repo(tmp_path, {
        "failer": 'import sys\nprint("nope")\nsys.exit(1)\n'})
    verdict, findings = G.audit(r)
    assert verdict == "PASS", findings
    _no_probe_reached_the_live_tree()


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


def test_a_host_excluded_gate_is_not_indirectly_launched_by_the_meta_sweep(
        tmp_path):
    """An adjacent host-independence exclusion is transitive.

    The host probe drives this meta-gate.  If the meta-gate then launches the
    excluded network subject, the supposedly hermetic two-tree comparison has
    reached the network through one level of indirection.
    """
    root = tmp_path / "repo"
    (root / "tools" / "ci").mkdir(parents=True)
    marker = tmp_path / "remote-was-launched"
    (root / "remote.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\n"
        "print('[PASS] remote response: 1 item')\n")
    (root / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        "# host-independence: EXCLUDE — reaches a remote service whose answer "
        "can move independently of this commit\n"
        'run "remote report" "$ROOT" python3 "$ROOT/remote.py"\n')

    res = G.audit_ci(root, timeout=10, budget=20,
                     skip_host_excluded=True)
    assert not marker.exists(), (
        "the denominator meta-sweep launched a gate explicitly excluded from "
        "host-independence")
    assert any(label == "remote report" and "EXCLUDED" in why
               for label, why in res.not_driven), res.not_driven


def test_the_gate_list_is_PARSED_from_the_ci_script_not_duplicated():
    """A second hand-maintained list would drift, and a gate added to CI would
    silently escape this check."""
    gates = G.parse_gates(_REPO / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert len(gates) >= 20, len(gates)
    labels = {g[0] for g in gates}
    assert "chip-AGNOSTIC source guard" in labels, sorted(labels)[:5]


#: Aggregate wall-clock budget for the CI sweep in this suite (vibe-ic#1181).
#: 600s against a measured 192.9s idle: generous enough that an ordinary run is
#: never truncated, small enough that a pathological one cannot outlive the
#: harness. It is a CEILING, not a target — a run that hits it is disclosed as
#: NOT_CHECKED rather than quietly reported clean.
_CI_SWEEP_BUDGET_S = 600.0


def test_the_real_ci_gate_set_is_currently_clean():
    """The measured state at land time: every CI gate discloses what it
    examined. A zero baseline is the right shape for a regression guard — it
    can only fire on a NEW instance.

    BOUNDED, because unbounded it hung the whole suite (vibe-ic#1181).
    `audit_ci` drives 74 declared gates with a 120s timeout EACH and nothing
    capped the sum: measured on an idle host at a38902d1, 50 driven in 192.9s
    — already past the suite's own `--timeout=180`, worst case 50 x 120s. The
    wait is inside `subprocess.run`, which `--timeout-method=thread` cannot
    interrupt, so pytest printed its stack dump and the invocation still never
    finished. The whole run then produced NO SUMMARY LINE, which greps as
    neither pass nor fail and silently unmeasured every other file in the
    selection.

    WHAT IS ASSERTED IS UNCHANGED, and is asserted more directly. `verdict ==
    "PASS"` was a proxy for "no gate answered PASS without disclosing its
    denominator"; `findings == []` is that claim itself, and it holds whether
    or not the budget truncated the sweep. The truncation is then asserted to
    be DISCLOSED rather than tolerated — a partial sweep may not read as a
    clean one, which is why `audit_ci` returns NOT_CHECKED and not PASS.
    """
    import pytest
    script = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not script.is_file():
        pytest.skip("CI script not present")
    res = G.audit_ci(_REPO, budget=_CI_SWEEP_BUDGET_S)

    # THE CLAIM. Any gate that passes over an empty tree without disclosing it
    # is a finding, and a finding is a finding however far the sweep got.
    assert res.findings == [], res.findings

    # NON-VACUITY. A budget so small that nothing ran would satisfy the line
    # above by examining nothing — the exact shape this program exists to
    # remove from everybody else.
    assert res.declared >= 20, res.declared
    assert res.probed >= 1, (res.probed, res.declared)

    # AND THE TRUNCATION, IF ANY, IS DISCLOSED — never folded into a pass.
    if res.truncated:
        assert res.verdict == "NOT_CHECKED", res.verdict
        assert any("aggregate budget" in w for _g, w in res.not_driven)
    else:
        assert res.verdict == "PASS", res.findings
