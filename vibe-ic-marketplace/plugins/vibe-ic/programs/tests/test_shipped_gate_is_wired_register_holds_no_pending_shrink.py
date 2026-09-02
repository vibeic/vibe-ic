#!/usr/bin/env python3
"""The shipped wiring register recorded twice the debt the tree owed.

THE FINDING, MEASURED at 7670d6ff7 (v1.16.5), a clean checkout of `origin/main`.
`gate_is_wired_check.py` run with no arguments prints:

    gates: 649   unwired: 26 (baseline 53)   of those named in a skill: 23
    [TIGHTENED] unwired: 27 entries left the recorded set (53 -> 26) —
      analog_adc_enob_corner_check, analog_hardmacro_pinname_consistency_check,
      analog_hil_convergence_log_check, ...
             now wired, so they no longer belong in the register.
             Record it with:  gate_is_wired_check.py --record-shrink
    [PASS] gate_is_wired: no gate newly unwired; the baseline has not grown.

Twenty-seven gates had genuinely been wired since the register was last written
and one had left `skill_only`, and nobody wrote the tightening back — so
`programs/gate_is_wired_baseline.json` recorded 53 unwired gates over a tree
whose real count is 26, and 24 `skill_only` over a real 23. More than twice the
debt the tree owed, shipped, with the gate printing `[PASS]`.

WHY NOTHING STOPPED IT. An unrecorded SHRINK is deliberately not a failure —
`gate_is_wired_check.py` says so where it reports one: failing it would make
"fix nothing" the cheapest way to stay green, and the remedy an operator would
reach for is `--write-baseline`, the one write that ALSO records every NEW
finding of the same run as accepted debt. So the check exits 0 with the
tightening merely REPORTED, and it stays reported until a human reads one line
in a 150-gate log and acts on it.

WHAT `test_gate_is_wired.py` DOES NOT COVER. It is 27 tests and nine of them
assert an exact set — but every one is built on a synthetic fixture root
(`giw.unwired(root, root)`), so not one compares the SHIPPED register against
what the SHIPPED tree measures. The sibling register
`flow_gate_enforcement_baseline.json` had the identical shape at #2014 G6 and
there the drift DID redden two tests, because two of them assert
`computed == recorded` over the real tree. Here nothing did, which is why this
one was invisible.

THIS FILE READS THE CLI'S OWN REPORT — exit status and stdout of the shipped
argv, default root and default register — rather than re-deriving the set
in-process. The CLI is the surface `tools/ci/repo_hygiene_gates.sh` and an
operator see, and it is the only place the un-acted-on remedy line is printed.

NOT ONE ASSERTION IS VACUOUS. Every positive claim has a negative arm that
re-runs the same argv against a mutated COPY and requires the claim to break.
The shipped tree is never written.

IT COSTS TWO SHIPPED-TREE RUNS, AND THE SECOND ONE IS DELIBERATE. Each
invocation scans ~1500 wiring sources and takes ~15 s; the first version of
this file made SEVEN, so the unmutated run is module-scoped and shared and the
two arms that are about the RATCHET rather than about the shipped tree drive a
synthetic root instead — 127 s to 67 s. What is NOT traded away: every claim
about the shipped register is still measured against the shipped register, and
the arm that falsifies the headline claim still mutates a copy of the SHIPPED
register and re-runs against the SHIPPED tree.

A COST I SUSPECTED THIS FILE OF AND MEASURED IT OUT OF. In the hygiene sweep
`an argued direction is pinned` went 417 s -> 804 s and `gates are
host-independent` fell from PASS to PARALLEL_INCOMPLETE, "worker 0 exceeded its
600s process budget", naming that gate. `policy_direction_pin_check
--verify-pins` re-runs candidate tests per pin, so this file was the obvious
suspect. It is not the cause. MEASURED standalone on clean clones of both
trees, nothing else running:

    7670d6ff7 (control)   11m02.8s
    this branch           11m21.8s     +19 s, +2.9%

and none of the seven argued pin sites is in `gate_is_wired_check.py` — the
candidate sets are tests=1,1,2,3,3,15,40 and this file is in none of them. The
gate costs ~660 s on the CONTROL tree too, already past the 600 s worker
budget, so whether the probe fits is a property of host load and not of this
commit. The optimisation above is kept because 67 s is better than 127 s, not
because it repaired anything.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_CHECK = _PROGRAMS / "gate_is_wired_check.py"
_BASELINE = _PROGRAMS / "gate_is_wired_baseline.json"

#: One of the twenty-seven the tree had paid and the register still recorded.
#: Putting it back is the negative arm for the pending-tightening claim.
_PAID_DOWN = "analog_adc_enob_corner_check"

#: The helper G16 moved out of `programs/`. It raises `pytest.skip` and
#: `pytest.fail`, so it can only run inside a pytest process; in `programs/`
#: its `_guard` suffix put it in this gate's population and it measured as
#: unwired — correctly, because `programs/tests/` is not a wiring source. It
#: must not come back as a RECORDED entry, which would also make the gate
#: exit 0.
_MOVED_HELPER = "corpus_guard"


def _run(*extra, baseline=None):
    cmd = [sys.executable, str(_CHECK)]
    if baseline is not None:
        cmd += ["--baseline", str(baseline)]
    return _pr.run(cmd + list(extra), capture_output=True, text=True)


def _tightened_lines(out: str):
    """Every `[TIGHTENED] <register>: ...` line the check printed."""
    return [ln.strip() for ln in out.splitlines() if "[TIGHTENED]" in ln]


@pytest.fixture(scope="module")
def shipped(tmp_path_factory):
    """ONE unmutated run of the shipped argv, shared by every positive claim.

    Module-scoped because the invocation costs ~15 s and this file used to pay
    it seven times — see the note in the docstring for what that cost the
    hygiene sweep. Returns (CompletedProcess, the --json payload)."""
    out = tmp_path_factory.mktemp("giw") / "giw.json"
    r = _run("--json", str(out))
    return r, json.loads(out.read_text())


def _synthetic_root(tmp_path, gates, recorded):
    """A tiny plugin under a repo root that carries `tools/ci/`.

    The check REFUSES a root with no repo-root wiring corpus above it —
    "a failed look is not a finding" — so the ancestor is real, not implied.
    Used only by the arms whose subject is the RATCHET (does it refuse growth,
    can the shrink path add?), never by a claim about the shipped register."""
    repo = tmp_path / "repo"
    (repo / "tools" / "ci").mkdir(parents=True)
    (repo / "tools" / "ci" / "placeholder.sh").write_text(
        "# a repo-root wiring corpus that names nothing\n", encoding="utf-8")
    plugin = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / "programs").mkdir(parents=True)
    for g in gates:
        (plugin / "programs" / f"{g}.py").write_text(
            f'#!/usr/bin/env python3\n"""{g} — synthetic."""\n', encoding="utf-8")
    bl = plugin / "programs" / "gate_is_wired_baseline.json"
    bl.write_text(json.dumps(
        {"_comment": "synthetic fixture register", "unwired": sorted(recorded),
         "skill_only": []}, indent=2) + "\n", encoding="utf-8")
    return plugin, bl


# --------------------------------------------------------------------------
# 1. the register owes no unrecorded paydown
# --------------------------------------------------------------------------

def test_the_shipped_check_reports_no_pending_tightening(shipped):
    """RED before the shrink was recorded: the check printed
    `[TIGHTENED] unwired: 27 entries left the recorded set (53 -> 26)` and
    named the remedy nobody ran."""
    r, _ = shipped
    both = r.stdout + r.stderr
    assert r.returncode == 0, both
    assert not _tightened_lines(both), (
        "the shipped register records debt the tree no longer owes; run "
        "`gate_is_wired_check.py --record-shrink`:\n"
        + "\n".join(_tightened_lines(both)))
    assert "--record-shrink" not in r.stdout, r.stdout


def test_the_shipped_register_is_exactly_what_the_shipped_tree_measures(shipped):
    """Not `<=` and not `does not contain X` — the SAME SET, both directions,
    for BOTH registers.

    `len(recorded) <= previous` and "does not contain X" are each satisfied by
    a register that has drifted some other way, and that is precisely how this
    one stayed green while recording 53 over a tree owing 26."""
    doc = json.loads(_BASELINE.read_text())
    r, measured = shipped
    assert r.returncode == 0, r.stdout + r.stderr
    for key, computed_key in (("unwired", "unwired"),
                              ("skill_only", "skill_only")):
        recorded = doc[key]
        assert len(recorded) == len(set(recorded)), f"duplicate entries in {key}"
        assert sorted(recorded) == sorted(measured[computed_key]), (
            f"{key}: register records {len(recorded)} and the tree measures "
            f"{len(measured[computed_key])}; "
            f"only recorded={sorted(set(recorded) - set(measured[computed_key]))} "
            f"only measured={sorted(set(measured[computed_key]) - set(recorded))}")
    # The printed summary must agree with both, or the line an operator reads
    # is not the line the register holds.
    m = re.search(r"unwired: (\d+) \(baseline (\d+)\)", r.stdout)
    assert m, r.stdout
    assert int(m.group(1)) == int(m.group(2)) == len(doc["unwired"]), r.stdout


def test_the_moved_helper_is_not_paid_by_recording_it(shipped):
    """The control the sibling register already had.

    `corpus_guard` shipped in `programs/` at G15 imported only by two test
    files and measured as newly unwired, so the check exited 1. RECORDING it
    would also make the check exit 0 — the register's own comment forbids that
    ("MAY ONLY SHRINK"), and this file must refuse it even though the gate
    would not."""
    doc = json.loads(_BASELINE.read_text())
    for key in ("unwired", "skill_only"):
        assert _MOVED_HELPER not in doc[key], (
            f"{_MOVED_HELPER} was recorded as debt in {key} instead of being "
            f"moved out of the gate population")
    _r, measured = shipped
    assert _MOVED_HELPER not in measured["unwired"], measured["unwired"]
    assert not (_PROGRAMS / f"{_MOVED_HELPER}.py").exists(), (
        f"{_MOVED_HELPER}.py is back in programs/, where its `_guard` suffix "
        f"puts it in this gate's population")
    assert (_TESTS / f"_{_MOVED_HELPER}.py").is_file()


# --------------------------------------------------------------------------
# 2. negative arms — every claim above must break when the fix is undone
# --------------------------------------------------------------------------

def test_negative_arm_returning_a_paid_entry_restores_the_tightening(tmp_path):
    """Put a paid-down entry back into a COPY and the pending-tightening claim
    must fail, or the positive claim proves nothing."""
    doc = json.loads(_BASELINE.read_text())
    assert _PAID_DOWN not in doc["unwired"], "fixture entry is still recorded"
    doc["unwired"] = sorted(set(doc["unwired"]) | {_PAID_DOWN})
    mutated = tmp_path / "baseline.json"
    mutated.write_text(json.dumps(doc, ensure_ascii=False))
    r = _run(baseline=mutated)
    both = r.stdout + r.stderr
    assert r.returncode == 0, both
    lines = _tightened_lines(both)
    assert lines, both
    assert any("unwired" in ln for ln in lines), lines


def test_negative_arm_the_register_still_refuses_growth(tmp_path):
    """The property the write must not have cost. Drop an entry the tree DOES
    still owe from a COPY: the check must then see it as NEW and exit 1."""
    root, bl = _synthetic_root(tmp_path, ["probe_alpha_check", "probe_beta_check"],
                               recorded=["probe_alpha_check"])
    r = _pr.run([sys.executable, str(_CHECK), "--root", str(root),
                 "--baseline", str(bl)], capture_output=True, text=True)
    both = r.stdout + r.stderr
    assert r.returncode == 1, both
    assert "probe_beta_check" in both, both


def test_negative_arm_the_shrink_path_cannot_add(tmp_path):
    """`--record-shrink` is the write this fix used. Prove it can only remove:
    a COPY missing an entry the tree DOES owe must not gain it back."""
    root, bl = _synthetic_root(tmp_path, ["probe_alpha_check", "probe_beta_check"],
                               recorded=["probe_alpha_check"])
    r = _pr.run([sys.executable, str(_CHECK), "--root", str(root),
                 "--baseline", str(bl), "--record-shrink"],
                capture_output=True, text=True)
    after = json.loads(bl.read_text())
    assert "probe_beta_check" not in after["unwired"], (
        "--record-shrink ADDED probe_beta_check, which the tree owes but the "
        "register did not record; it may only remove")
    assert r.returncode in (0, 1), r.stdout + r.stderr
