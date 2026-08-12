#!/usr/bin/env python3
"""The adversary must find a real forgery, and must not find one everywhere. #1119.

An instrument whose every verdict is SUCCEEDED measures nothing, so every
finding assertion here is paired with a DEFENDED twin taken from the same run:
`sta_report_check` notices all three substitution attacks and the other six
sign-off gates notice none of them. That contrast is the evidence the attack is
discriminating; either half alone would be worthless.

The findings are backed by COMMITTED artefacts — two published cells this
repository carries — and not by fixtures authored beside this file, so a reader
can re-run the attack by hand and get the same answer.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[2]
PROG = PLUGIN / "programs" / "adversarial_agent.py"

sys.path.insert(0, str(PLUGIN / "programs"))
import adversarial_agent as AA  # noqa: E402

IC = REPO / "benchmark-data" / "ic"
CELL = IC / "spm" / "v1.9.96_gf180mcuD"
DONOR = IC / "sha256" / "clean_run_v1427_20260715"
OLDER = IC / "sha256" / "clean_run_v1422_20260715"

#: The gate that NOTICES, measured. Keeping the pair small keeps the test quick
#: while preserving the only property that matters: one of each colour.
FORGEABLE = ("drc_report_check", (".",))
DEFENDING = ("sta_report_check", (".", "--mode", "sta"))

_corpus = pytest.mark.skipif(
    not (CELL.is_dir() and DONOR.is_dir()),
    reason="published cells absent from this checkout")


# ===========================================================================
# THE FINDING, AND ITS DISCRIMINATING TWIN
# ===========================================================================
@_corpus
def test_the_adversary_finds_the_cross_design_forgery():
    """A gate certifies THIS design using ANOTHER design's reports.

    Measured on v1.10.33: six of seven sign-off gates stay green after 149
    artefacts are substituted from a different IC. A gate that cannot tell whose
    report it read is signing a statement about a design it never examined.
    """
    got = AA.attack_cross_design(PLUGIN, CELL, DONOR, gates=(FORGEABLE,))
    assert len(got) == 1, got
    a = got[0]
    assert a.verdict == AA.SUCCEEDED, (
        f"substituting another design's reports did not forge a green: {a}. "
        f"Either the gate learned to check provenance — in which case this "
        f"finding closed and the docstring must say so — or the attack broke.")
    assert a.evidence["rc_before"] == 0 and a.evidence["rc_after"] == 0, a
    assert a.evidence["substituted"] > 0, "nothing was substituted"


@_corpus
def test_PAIRED_a_gate_that_DOES_notice_is_reported_DEFENDED():
    """THE TWIN. Without it, SUCCEEDED could be a constant.

    Same attack, same cell, same donor, one gate apart. `sta_report_check`
    objects; if this ever reports SUCCEEDED too, the attack has stopped
    discriminating and its findings are worth nothing.
    """
    got = AA.attack_cross_design(PLUGIN, CELL, DONOR, gates=(DEFENDING,))
    assert len(got) == 1, got
    assert got[0].verdict == AA.DEFENDED, (
        f"the one gate measured to notice this attack no longer does: {got[0]}. "
        f"An attack that succeeds against everything measures nothing.")


@_corpus
def test_the_stale_replay_is_a_separate_finding_from_cross_design():
    """A2 — an EARLIER run of the same design, which is harder to notice.

    Distinct from A3 on purpose: the artefact belongs to this design, so a check
    keyed on design identity still passes and only a check keyed on WHICH RUN
    produced it can object.
    """
    got = AA.attack_stale_replay(PLUGIN, CELL, OLDER, gates=(FORGEABLE,))
    assert len(got) == 1 and got[0].verdict == AA.SUCCEEDED, got
    assert got[0].evidence["substituted"] > 0, got


# ===========================================================================
# THE TRI-STATE. "could not attack" must never read as "attack failed"
# ===========================================================================
@_corpus
def test_an_attack_with_no_donor_is_UNAVAILABLE_not_DEFENDED():
    got = AA.attack_cross_design(PLUGIN, CELL, None, gates=(FORGEABLE,))
    assert len(got) == 1 and got[0].verdict == AA.UNAVAILABLE, got
    assert "donor" in got[0].detail.lower(), got[0].detail


@_corpus
def test_violation_deletion_on_a_PASSING_gate_is_UNAVAILABLE():
    """There was nothing to delete is not deleting it would not have worked.

    The most tempting place to record a false DEFENDED: the gate is green, the
    attack changes nothing, and calling that "defended" would credit the flow
    with resisting an attack that never happened.
    """
    got = AA.attack_violation_deletion(PLUGIN, CELL, gates=(FORGEABLE,))
    assert len(got) == 1, got
    assert got[0].verdict == AA.UNAVAILABLE, got[0]
    assert "no violation" in got[0].detail.lower(), got[0].detail


def test_nothing_attempted_exits_2_and_says_so(tmp_path):
    """An adversary that could not attack anything has said nothing.

    rc 0 would mean "no forgery found", which is a claim. rc 2 means "I could not
    look", which is the truth. They must not share an exit code — that
    conflation is the one this repo keeps paying for.
    """
    empty = tmp_path / "not_a_cell"
    empty.mkdir()
    rc, report = AA.run_campaign(PLUGIN, empty, None, None, gates=())
    assert rc == 2, (rc, report["counts"])
    assert report["verdict"] == "NOTHING_ATTEMPTED", report["verdict"]
    assert "not a pass" in report["disclosure"].lower(), report["disclosure"]


def test_the_container_bound_attacks_are_DECLARED_not_omitted():
    """The denominator is published, because the imagination is the denominator.

    Three of the issue's nine attacks need an EDA container or a simulator. An
    attack missing from the report is indistinguishable from an attack that
    found nothing, so they are listed UNAVAILABLE with the reason.
    """
    got = AA.unavailable_container_attacks()
    assert len(got) == 3, got
    names = {a.attack for a in got}
    assert names == {"A4_TOOL_VERSION_MISMATCH", "A6_RTL_FAULT_INJECTION",
                     "A7_CONSTRAINT_WEAKENING"}, names
    for a in got:
        assert a.verdict == AA.UNAVAILABLE and len(a.detail) > 20, a
        assert "needs" in a.detail.lower(), a.detail


@_corpus
def test_the_report_publishes_the_fraction_that_was_attempted():
    rc, report = AA.run_campaign(PLUGIN, CELL, DONOR, None,
                                 gates=(FORGEABLE, DEFENDING))
    cov = report["coverage"]
    assert cov["attacks_declared"] > cov["attacks_with_an_attempt"], (
        "every declared attack was attempted, so the coverage figure is not "
        f"telling a reader anything: {cov}")
    assert rc == 1, "the measured forgery did not make the campaign fail"
    assert report["findings"], report["counts"]


# ===========================================================================
# THE ASYMMETRY, AS A MECHANISM
# ===========================================================================
def test_the_finder_may_not_resolve_its_own_finding():
    f = {"found_by": "adversarial-agent", "attack": "A3_CROSS_DESIGN"}
    with pytest.raises(AA.SelfResolutionRefused) as e:
        AA.mark_resolved(f, "adversarial-agent")
    assert "cannot be its own refutation" in str(e.value)


def test_PAIRED_a_DIFFERENT_party_may_resolve_it():
    """The twin. A refusal that refuses everyone is a ban, not an asymmetry."""
    f = {"found_by": "adversarial-agent", "attack": "A3_CROSS_DESIGN"}
    out = AA.mark_resolved(f, "repo-gatekeeper")
    assert out["resolved_by"] == "repo-gatekeeper"
    assert out["found_by"] == "adversarial-agent", "the finder must be preserved"


@pytest.mark.parametrize("finding,who", [
    ({"found_by": "x"}, ""),
    ({}, "somebody"),
    ({"found_by": ""}, "somebody"),
])
def test_an_unattributable_resolution_is_refused(finding, who):
    """No found_by means the asymmetry cannot be CHECKED, which is not the same
    as it being satisfied. Refusing is the only answer that does not guess."""
    with pytest.raises(AA.SelfResolutionRefused):
        AA.mark_resolved(finding, who)


# ===========================================================================
# THE SHIPPED TREE IS NEVER TOUCHED
# ===========================================================================
@_corpus
def test_the_adversary_never_writes_into_the_repository():
    """Every attack runs in a throwaway copy, asserted rather than intended.

    `gate_cli_mutation_probe`'s docstring records two runs killed inside its
    mutation window that left SHIPPED gates carrying an injected early return —
    and a neutered gate exits 0, which the flow reads as PASS. A `finally` does
    not run on SIGKILL, so the only safe design is never to write in the tree at
    all. This measures the tree before and after a campaign that mutates 149
    artefacts in its copy.
    """
    def snapshot():
        out = {}
        for p in sorted(CELL.rglob("*")):
            if p.is_file():
                st = p.stat()
                out[str(p.relative_to(CELL))] = (st.st_size, int(st.st_mtime))
        return out

    before = snapshot()
    assert before, "the probe itself is broken: the cell looks empty"
    AA.run_campaign(PLUGIN, CELL, DONOR, OLDER, gates=(FORGEABLE,))
    after = snapshot()
    assert before == after, (
        "the campaign changed the shipped tree: "
        f"{sorted(set(before) ^ set(after))[:5]} differ, and "
        f"{[k for k in before if k in after and before[k] != after[k]][:5]} moved")


@_corpus
def test_the_cli_reports_the_forgery_and_exits_1():
    """The shipped CLI, in a subprocess, because the exit code is the product."""
    r = subprocess.run(
        [sys.executable, str(PROG), str(CELL), "--donor", str(DONOR)],
        capture_output=True, text=True, timeout=1500)
    assert r.returncode == 1, (r.returncode, r.stdout[-800:], r.stderr[-400:])
    assert "FORGED GREEN" in r.stdout, r.stdout[-800:]
    assert "P0 integrity defect" in r.stdout, r.stdout[-800:]
    # ...and the UNAVAILABLE count is always disclosed, never left implicit.
    assert "UNAVAILABLE and therefore" in r.stdout, r.stdout[-400:]


@_corpus
def test_the_json_report_round_trips(tmp_path):
    out = tmp_path / "r.json"
    AA.run_campaign(PLUGIN, CELL, DONOR, None, gates=(FORGEABLE,))
    r = subprocess.run(
        [sys.executable, str(PROG), str(CELL), "--donor", str(DONOR),
         "--json", str(out)], capture_output=True, text=True, timeout=1500)
    assert r.returncode == 1, r.stdout[-400:]
    doc = json.loads(out.read_text())
    assert doc["schema"] == AA.SCHEMA
    assert doc["findings"], doc["counts"]
    for f in doc["findings"]:
        assert f["verdict"] == AA.SUCCEEDED
        assert f["objective"], "a finding must say what green it forged"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
