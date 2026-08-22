#!/usr/bin/env python3
"""The adversary must find a real forgery, and must not find one everywhere. #1119.

An instrument whose every verdict is SUCCEEDED measures nothing, so every
finding assertion here is paired with a DEFENDED twin taken from the same run:
`sta_report_check` notices all three substitution attacks and the other six
sign-off gates notice none of them. That contrast is the evidence the attack is
discriminating; either half alone would be worthless.

The findings are backed by PUBLISHED artefacts — two run trees from the corpus —
and not by fixtures authored beside this file, so a reader can re-run the attack
by hand and get the same answer. Those trees are no longer IN this repository:
`c5d7f2d00` moved the published results to `vibeic/benchmark-data`, so the cells
resolve through `$VIBE_IC_BENCHMARK_DATA` like every other corpus check here.
This sentence used to read "two published cells this repository carries", and
went on saying it for the whole span in which the ratchet could not run.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[2]
PROG = PLUGIN / "programs" / "adversarial_agent.py"

sys.path.insert(0, str(PLUGIN / "programs"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import adversarial_agent as AA  # noqa: E402
from _published_corpus import SKIP_REASON as CORPUS_SKIP_REASON  # noqa: E402
from _published_corpus import named_cell as _corpus_cell  # noqa: E402

# THE RATCHET RESOLVES ITS CORPUS THROUGH THE ONE HELPER, and did not always.
# These four names were `REPO / "benchmark-data" / "ic" / ...` until the corpus
# left this repository at `c5d7f2d00`. From that commit every test below skipped
# on EVERY host, including one with a readable clone at $VIBE_IC_BENCHMARK_DATA,
# because the path was spelled here instead of asked for. Measured on
# `053eecd27` before the change, pointer set and readable: `9 passed, 12
# skipped`. The thirteen recorded findings were adjudicated by nothing for that
# whole span, in either direction — which is the failure `adversarial_agent`'s
# own docstring predicted and placed a verdict (UNAVAILABLE) against, one layer
# below where a pytest skip could act on it.
CELL = _corpus_cell("spm", "v1.9.96_gf180mcuD")
DONOR = _corpus_cell("sha256", "clean_run_v1427_20260715")
OLDER = _corpus_cell("sha256", "clean_run_v1422_20260715")

#: One of each colour, measured, because a probe that succeeds against
#: everything measures nothing. Keeping the pair small keeps the test quick.
#:
#: BOTH HALVES MOVED when the design binding landed. `drc_report_check` was the
#: FORGEABLE half and now DEFENDS: its report declares `<top-cell>` and the gate
#: reads it, so another design's evidence is refused by name. It replaces
#: `sta_report_check` as the DEFENDING half, and that is an improvement in what
#: this pair proves rather than a relabelling — sta's defence was INCIDENTAL. It
#: tripped `STA_REAL_VIOLATION_FOUND` on a negative slack in the donor's numbers
#: and `STA_REPORT_TOO_SMALL` on one donor file; it never looked at whose design
#: it was reading, and a clean donor would have walked straight past it. The
#: campaign's own note read as though sta had caught the forgery. It had not.
#:
#: `antenna_report_check` is the FORGEABLE half, and it is the harder kind of
#: open finding: its evidence is not merely missing an identity, it is
#: IDENTICAL across designs. `reports/phase3/antenna.rpt` is byte-for-byte the
#: same file in the published cell and in the sha256 donor — two designs on two
#: PDKs — because it is a 487-byte summary the runner writes, carrying
#: "0 net violations, 0 pin violations" and naming as its source
#: `phase3/stage3/pnr/openroad.log`, which is not in the published cell at all.
#: No gate-side check can bind that to a design; the producer has to emit one.
#:
#: `lvs_report_check` held this slot briefly and now defends: netgen's
#: "Device classes X and X are equivalent." line, taken LAST, is the top-level
#: comparison.
FORGEABLE = ("antenna_report_check", (".", "--mode", "antenna"))
DEFENDING = ("drc_report_check", (".",))

#: The bound on every CLI subprocess below (vibe-ic#1241).
#:
#: WHY NOT 1500. `--timeout-method=thread` kills the SESSION rather than
#: the test, so an inner bound above the harness's own can never fire:
#: pytest ends the run at 180 s first and every other file in the subset
#: loses its verdict. `ci_harness_timeout_ceiling_check` resolves the
#: ceiling from the workflow bounds as `180 // 3` = 60 s. 1500 s was 25x
#: the harness itself.
#:
#: WHY 45 AND NOT 60. Chosen from the clock, not by lowering 1500 until
#: the gate went quiet — these tests DO real work (the CLI runs
#: `FORGEABLE` over a published cell), so the measurement is the point.
#: Measured twice, on two hosts: the whole 21-test file runs in 33.57 s
#: and 29.25 s, and its slowest bounded call is 9.28 s and 7.70 s, so
#: 45 s is ~5x the slowest measurement. It stays clear of the ceiling
#: rather than sitting on it: the `// 3` divisor exists so one file can
#: afford more than a single bounded call, and a bound placed exactly AT
#: the ceiling is one workflow edit away from being a violation again.
_CLI_BOUND_S = 45

#: The reason is the SUITE'S one reason, not a private spelling of it. A reader
#: who greps for why corpus checks are quiet finds this one with the other 54.
_corpus = pytest.mark.skipif(
    CELL is None or DONOR is None, reason=CORPUS_SKIP_REASON)


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
def test_the_stale_replay_refuses_a_donor_that_is_a_different_design():
    """A2's premise is CHECKED, because the recorded campaign's was false.

    A2 is supposed to be distinct from A3: the artefact belongs to this design,
    so a check keyed on design identity still passes and only a check keyed on
    WHICH RUN produced it can object. The run it was given is not that::

        cell   spm/v1.9.96_gf180mcuD            top-cell chip_top   gf180mcuD
        older  sha256/clean_run_v1422_20260715  top-cell sha256     sky130A

    So A2 was A3 with a second foreign donor, its six SUCCEEDED verdicts were
    six duplicates, and the run-identity property it exists to measure has never
    been measured. This test used to assert that SUCCEEDED — it pinned the
    duplicate as though it were the distinct finding.
    """
    got = AA.attack_stale_replay(PLUGIN, CELL, OLDER, gates=(FORGEABLE,))
    assert len(got) == 1, got
    assert got[0].verdict == AA.UNAVAILABLE, (
        f"A2 ran against a donor that is not an earlier run of this design; "
        f"whatever it reports is A3 measured twice: {got}")
    assert got[0].evidence["cell_design"] != got[0].evidence["older_design"], got
    assert "staleness" in got[0].detail, got[0].detail


@_corpus
def test_PAIRED_the_stale_replay_still_runs_when_its_premise_HOLDS(tmp_path):
    """The twin. A precondition that refuses everything is a disabled attack.

    The `older` run here is a copy of the cell, so it declares the same design
    and the premise is satisfied. What the attack then REPORTS is not asserted —
    replaying a tree over itself is a degenerate replay and its verdict is not
    the point. That it is ATTEMPTED is.
    """
    older = tmp_path / "older_run"
    shutil.copytree(CELL, older)
    got = AA.attack_stale_replay(PLUGIN, CELL, older, gates=(FORGEABLE,))
    assert len(got) == 1, got
    assert got[0].verdict != AA.UNAVAILABLE, (
        f"A2 refused a donor declaring the SAME design as the cell, so the "
        f"premise check is a blanket refusal rather than a precondition: {got}")
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
        capture_output=True, text=True, timeout=_CLI_BOUND_S)
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
         "--json", str(out)], capture_output=True, text=True, timeout=_CLI_BOUND_S)
    assert r.returncode == 1, r.stdout[-400:]
    doc = json.loads(out.read_text())
    assert doc["schema"] == AA.SCHEMA
    assert doc["findings"], doc["counts"]
    for f in doc["findings"]:
        assert f["verdict"] == AA.SUCCEEDED
        assert f["objective"], "a finding must say what green it forged"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ===========================================================================
# A FINDING IS A DEFECT, NOT A SUGGESTION — SO IT IS RATCHETED
#
# The first version of this feature PRINTED its findings. Nothing failed when a
# fourteenth gate started accepting foreign evidence, and nothing noticed when
# one stopped, so "a finding is a P0 defect" was a sentence rather than a
# mechanism. These tests are the mechanism.
# ===========================================================================
def _live_recorded_attacks():
    """Re-run exactly the attacks the ledger records, over the cells it names."""
    led = AA.load_findings_ledger()
    cell = _corpus_cell(led["cell"])
    donor = _corpus_cell(led["donor"])
    older = _corpus_cell(led["older_run"])
    # The ledger names its own subject. A corpus that answers for the CELL but
    # not for what the ledger named is not the tree these findings were measured
    # on, and re-running the attacks against a different one would republish the
    # verdicts under a subject nobody chose.
    assert cell is not None, (
        f"the findings ledger names cell {led['cell']!r}; the resolved corpus "
        f"does not carry it. This is UNPROVEN, not closed.")
    out = []
    out += AA.attack_cross_design(PLUGIN, cell, donor)
    out += AA.attack_stale_replay(PLUGIN, cell, older)
    out += AA.attack_tamper_destructive(PLUGIN, cell)
    return led, out


@_corpus
def test_the_findings_ratchet_holds_in_BOTH_directions():
    """One more forged green than the ledger records is a regression; one fewer
    is progress that must be adjudicated, not absorbed.

    The count is READ FROM THE LEDGER, never typed here. It was typed here — as
    13 — and the number outlived the measurement: 6 of those 13 closed when the
    sign-off gates learned to read the design their evidence names, and a
    hard-coded 13 in a docstring is the same rot this campaign exists to find.
    """
    led, attempts = _live_recorded_attacks()
    d = AA.ratchet_diff(led, attempts)
    assert not d["newly_forging"], (
        f"a gate started forging a green: {d['newly_forging']}. That is a P0 "
        f"integrity regression, not a number to update — find what changed, then "
        f"re-run tools/gen_adversarial_findings.py.")
    assert not d["closed"], (
        f"these findings CLOSED: {d['closed']}. That is real progress and it "
        f"must be adjudicated rather than absorbed: name the fix that closed "
        f"them in the PR, then re-run tools/gen_adversarial_findings.py.")
    assert not d["unproven"], (
        f"these findings went UNAVAILABLE: {d['unproven']}. The cell they need "
        f"is gone, so they are UNPROVEN, not fixed. A corpus prune must never "
        f"read as security progress.")
    assert not d["newly_attemptable"], (
        f"these attacks are recorded UNPROVEN and now produce a verdict: "
        f"{d['newly_attemptable']}. Whatever stopped them being attempted is "
        f"gone, so what they say now is new information — adjudicate it and "
        f"re-run tools/gen_adversarial_findings.py. An attack that comes back "
        f"into range and reports nothing is the same silence in the other "
        f"direction.")
    assert len(d["held"]) == len(led["forging"]), (
        f"{len(d['held'])} of {len(led['forging'])} recorded findings still "
        f"reproduce; the rest were neither closed nor unproven, which means the "
        f"comparison itself is broken")


@_corpus
def test_PAIRED_the_ratchet_can_SEE_a_new_forgery():
    """The twin. A ratchet that reports zero on everything is not one.

    Plants a finding the record does not contain by pretending the ledger is
    empty, and requires the diff to report every live SUCCEEDED as newly forging.
    """
    # A SYNTHETIC forgery first, so this twin does not depend on how many REAL
    # findings are open. It used to assert `>= 6` live SUCCEEDED, which was a
    # sample-size assumption dressed as a property: it was true at 13 findings,
    # and closing 9 of them turned the twin red for measuring the defect count
    # instead of the ratchet. At 0 open findings it would have had no way to
    # demonstrate anything at all.
    planted = AA.Attempt(
        "A3_CROSS_DESIGN", "a gate certifies this design using another "
        "design's reports", AA.SUCCEEDED,
        "synthetic: this attempt was never run", "no_such_cell:no_such_gate")
    seen = AA.ratchet_diff({"forging": []}, [planted])
    assert seen["newly_forging"] == ["A3_CROSS_DESIGN no_such_cell:no_such_gate"], (
        f"the ratchet did not report a planted SUCCEEDED pair that the record "
        f"does not contain: {seen}")

    _led, attempts = _live_recorded_attacks()
    d = AA.ratchet_diff({"forging": []}, attempts)
    live_succeeded = [a for a in attempts if a.verdict == AA.SUCCEEDED]
    assert len(d["newly_forging"]) == len(live_succeeded), (
        f"the ratchet reported {len(d['newly_forging'])} new forgeries against "
        f"an empty record but {len(live_succeeded)} attacks SUCCEEDED; it cannot "
        f"see what it is supposed to catch")
    assert not d["held"], d["held"]


@_corpus
def test_PAIRED_the_ratchet_tells_CLOSED_apart_from_UNPROVEN():
    """The distinction the whole design turns on.

    A recorded finding that now DEFENDS is progress. A recorded finding whose
    cell disappeared is not. Both make the pair vanish from the SUCCEEDED set, so
    a ratchet that only compared sets would score a corpus prune as a security
    win — the publication-schedule defect, one layer up.
    """
    fake_led = {"forging": [{"attack": "A3_CROSS_DESIGN", "target": "X:gate_a"},
                            {"attack": "A3_CROSS_DESIGN", "target": "X:gate_b"}]}
    attempts = [
        AA.Attempt("A3_CROSS_DESIGN", "o", AA.DEFENDED, "gate learned", "X:gate_a"),
        AA.Attempt("A3_CROSS_DESIGN", "o", AA.UNAVAILABLE, "cell gone", "X:gate_b"),
    ]
    d = AA.ratchet_diff(fake_led, attempts)
    assert d["closed"] == ["A3_CROSS_DESIGN X:gate_a"], d
    assert d["unproven"] == ["A3_CROSS_DESIGN X:gate_b"], d


def test_the_ledger_is_generated_not_hand_written():
    """A hand-edited finding list is an allowlist, and #1119 exists to stop
    findings being negotiable."""
    led = AA.load_findings_ledger()
    assert led.get("schema") == "vibe-ic/adversarial-findings/v1", led.get("schema")
    assert led.get("measured_on"), "the ledger does not say which commit it was measured on"
    blob = " ".join(led["_comment"])
    assert "never hand-edited" in blob, blob[:200]
    assert (REPO / "tools" / "gen_adversarial_findings.py").is_file(), (
        "the ledger claims to be generated and its generator is not in the tree")


def test_the_unwired_state_is_disclosed_or_gone():
    """Wiring is MEASURED, and the disclosure dies with it.

    This author required exactly this of #1092 and had not applied it here.
    Both directions: while nothing invokes this program the docstring must carry
    the NOT WIRED section, and the moment somebody wires it this test fails and
    forces the section out.
    """
    name = "adversarial_agent"
    # `own` is the set that may NAME the program without being a caller: the
    # program, its tests, its finding ledger, and the program index. The
    # question this test asks is whether the FLOW invokes it — a file that
    # merely guards the guard has not wired anything, and reading a mention in
    # one as evidence of wiring would delete a disclosure that is still true.
    own = {"adversarial_agent.py", "test_adversarial_agent.py",
           "adversarial_findings.json", "INDEX.md",
           "test_the_adversarial_ratchet_follows_the_corpus_pointer.py",
           "test_a_signoff_report_must_be_about_this_design.py"}
    callers = []
    for d in (PLUGIN / "flow", PLUGIN / "benchmark", PLUGIN / "programs"):
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.name in own:
                continue
            if p.suffix not in (".py", ".yaml", ".yml", ".json", ".md"):
                continue
            try:
                if name in p.read_text(errors="replace"):
                    callers.append(p.relative_to(PLUGIN).as_posix())
            except OSError:
                continue
    disclosed = "NOT WIRED YET" in AA.__doc__
    if callers:
        assert not disclosed, (
            f"{name} is now referenced by {sorted(callers)} — it is wired. "
            f"Delete the 'NOT WIRED YET' section; a stale disclosure is worse "
            f"than none because a reader trusts it.")
    else:
        assert disclosed, (
            f"nothing invokes {name}, so it cannot block anything, and the "
            f"docstring does not say so. That is the D9 defect this campaign "
            f"removes, and this author required the same disclosure of #1092.")
