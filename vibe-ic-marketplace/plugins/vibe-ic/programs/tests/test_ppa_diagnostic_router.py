#!/usr/bin/env python3
"""The router's value is measured by what it does NOT hand over.

Invariant 12 says the program has the first right to decide. A test suite for a
router naturally drifts toward proving that handoffs work, because that is the
visible feature -- and a router that hands over everything passes every one of
those tests. So the load-bearing tests here are the negative ones: a battery of
situations the deterministic rules CAN settle, each asserting that no handoff
was built at all.
"""
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import agent_policy, agent_router  # noqa: E402

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
CLI = PROGRAMS / "ppa_diagnostic_router.py"


def situation(**kw):
    base = {"schema": "vibeic.ppa.situation.v1", "question": "root_cause"}
    base.update(kw)
    return base


def gates(**by_domain):
    return [{"domain": d, "verdict": v} for d, v in sorted(by_domain.items())]


# --------------------------------------------------------------------------
# THE NEGATIVE TEST. Everything the rules can settle must stop at the program.
# --------------------------------------------------------------------------

DECIDABLE = [
    pytest.param(
        situation(domains_in_scope=["timing_hold"],
                  gates=gates(timing_hold="FAIL")),
        "R2_SINGLE_DOMAIN_KNOWN_REMEDY",
        id="one-domain-with-a-known-remedy"),
    pytest.param(
        situation(domains_in_scope=["drc", "area"],
                  gates=gates(drc="PASS", area="PASS")),
        "R1_NO_VIOLATION",
        id="nothing-is-wrong"),
    pytest.param(
        situation(domains_in_scope=["drc", "antenna"],
                  gates=gates(drc="FAIL", antenna="FAIL")),
        "R11_MULTI_DOMAIN_COMPOSABLE",
        id="two-violations-whose-remedies-do-not-fight"),
    pytest.param(
        situation(domains_in_scope=["drc", "antenna", "em"],
                  gates=gates(drc="FAIL", antenna="FAIL", em="FAIL")),
        "R11_MULTI_DOMAIN_COMPOSABLE",
        id="three-violations-still-composable"),
    pytest.param(
        situation(domains_in_scope=["timing_hold", "area"],
                  gates=gates(timing_hold="FAIL", area="PASS")),
        "R2_SINGLE_DOMAIN_KNOWN_REMEDY",
        id="one-violation-beside-a-clean-domain"),
    pytest.param(
        situation(domains_in_scope=["drc"],
                  gates=[{"domain": "drc", "verdict": "TOOL_ERROR",
                          "signature": "timeout"},
                         {"domain": "drc", "verdict": "FAIL"}]),
        "R2_SINGLE_DOMAIN_KNOWN_REMEDY",
        id="a-tool-failure-this-system-already-understands"),
]


@pytest.mark.parametrize("sit,expected_rule", DECIDABLE)
def test_a_case_the_program_can_decide_never_reaches_the_agent(sit,
                                                               expected_rule):
    """Invariant 12. An unnecessary handoff is a defect, not a feature.

    It replaces a verdict anyone can reproduce from the bytes with one that
    depends on which model answered -- and it does it invisibly, because a
    handoff looks like the system working.
    """
    diag = agent_router.diagnose(sit)
    assert diag.outcome == "PROGRAM_DECIDED", (
        f"expected the rules to settle this; got {diag.outcome} "
        f"via {diag.rule}")
    assert diag.rule == expected_rule
    assert diag.handoff is None, (
        f"the program decided via {diag.rule} and STILL built a handoff")
    assert diag.as_report()["reached_agent"] is False
    assert diag.rc == 0


def test_a_decided_case_produces_a_remedy_a_program_could_act_on():
    """A decision with no remedy is a handoff wearing a decision's label."""
    diag = agent_router.diagnose(
        situation(domains_in_scope=["antenna"], gates=gates(antenna="FAIL")))
    assert diag.outcome == "PROGRAM_DECIDED"
    assert diag.remedy.strip()
    assert diag.root_cause.strip()


# --------------------------------------------------------------------------
# The positive side: a genuine waive still works, and says why.
# --------------------------------------------------------------------------

WAIVES = [
    pytest.param(
        situation(domains_in_scope=["timing_setup", "area"],
                  gates=gates(timing_setup="FAIL", area="FAIL")),
        "MULTI_DOMAIN_CONFLICT",
        id="remedies-that-would-undo-each-other"),
    pytest.param(
        situation(domains_in_scope=["timing_setup"],
                  gates=gates(timing_setup="FAIL")),
        "AMBIGUOUS_ROOT_CAUSE",
        id="one-domain-with-no-deterministic-remedy"),
    pytest.param(
        situation(domains_in_scope=["drc"],
                  gates=[{"domain": "drc", "verdict": "TOOL_ERROR",
                          "signature": "segfault_in_a_new_place"}]),
        "NOVEL_TOOL_FAILURE",
        id="the-tool-ran-and-failed-in-a-way-we-do-not-know"),
    pytest.param(
        situation(domains_in_scope=["drc", "equivalence"],
                  gates=gates(drc="FAIL", equivalence="FAIL")),
        "CROSS_LAYER_REQUIRED",
        id="violations-that-span-layers"),
    pytest.param(
        situation(domains_in_scope=["drc"], gates=gates(drc="FAIL"),
                  human_requested_review=True),
        "HUMAN_REQUESTED_REVIEW",
        id="a-human-asked"),
    pytest.param(
        situation(domains_in_scope=["drc"], gates=gates(drc="FAIL"),
                  search_space_exhausted=True),
        "SEARCH_SPACE_EXHAUSTED",
        id="the-candidate-space-ran-out"),
]


@pytest.mark.parametrize("sit,reason", WAIVES)
def test_an_explicit_waive_emits_a_handoff_with_a_reason_from_the_closed_set(
        sit, reason):
    diag = agent_router.diagnose(sit)
    assert diag.outcome == "HANDOFF"
    assert diag.handoff is not None
    assert diag.handoff["reason"] == reason
    assert diag.handoff["reason"] in agent_policy.HANDOFF_REASONS
    assert diag.rc == 0, "a legal handoff is the router working, not a finding"


def test_a_plateau_is_three_identical_iterations_and_not_two():
    """The threshold is a constant, so it is worth pinning both sides of it."""
    metrics = [{"metric": "timing.setup.wns_ns", "domain": "timing_setup",
                "status": "MEASURED", "value": -0.2}]
    two = situation(domains_in_scope=["drc"], gates=gates(drc="FAIL"),
                    history=[{"metrics": metrics}] * 2)
    assert agent_router.diagnose(two).outcome == "PROGRAM_DECIDED"

    three = situation(domains_in_scope=["drc"], gates=gates(drc="FAIL"),
                      history=[{"metrics": metrics}] * 3)
    diag = agent_router.diagnose(three)
    assert diag.outcome == "HANDOFF"
    assert diag.handoff["reason"] == "PLATEAU"


def test_a_moving_search_is_not_a_plateau():
    hist = [{"metrics": [{"metric": "m", "domain": "drc",
                          "status": "MEASURED", "value": v}]}
            for v in (-0.3, -0.2, -0.1)]
    diag = agent_router.diagnose(
        situation(domains_in_scope=["drc"], gates=gates(drc="FAIL"),
                  history=hist))
    assert diag.outcome == "PROGRAM_DECIDED", "the measurement is moving"


def test_every_handoff_carries_what_the_program_had_already_decided():
    """So a reviewer can ask the only question that matters about a handoff:
    could a rule have decided this?"""
    diag = agent_router.diagnose(
        situation(domains_in_scope=["timing_setup", "area", "drc"],
                  gates=gates(timing_setup="FAIL", area="FAIL", drc="PASS")))
    decided = diag.handoff["program_already_decided"]
    assert decided["clean"] == ["drc"]
    assert decided["violated"] == ["area", "timing_setup"]


def test_a_handoff_is_identified_by_a_hash_of_itself():
    diag = agent_router.diagnose(
        situation(domains_in_scope=["timing_setup", "area"],
                  gates=gates(timing_setup="FAIL", area="FAIL")))
    assert diag.handoff["handoff_sha256"].startswith("sha256:")
    assert len(diag.handoff["handoff_sha256"]) == len("sha256:") + 64


# --------------------------------------------------------------------------
# "I could not look" is never "clean", and never an agent question either.
# --------------------------------------------------------------------------

def test_an_unmeasured_domain_is_undetermined_not_clean():
    diag = agent_router.diagnose(
        situation(domains_in_scope=["drc", "lvs"], gates=gates(drc="PASS")))
    assert diag.outcome == "UNDETERMINED"
    assert diag.rc == 2
    assert diag.undetermined == ["lvs"]
    assert "lvs" not in diag.clean


def test_an_unmeasured_domain_is_not_handed_to_the_agent():
    """The distinction the whole router turns on. A hole in the EVIDENCE is
    fixed by producing the evidence; promoting it to a question about the
    DESIGN hides the only signal that it is missing."""
    diag = agent_router.diagnose(
        situation(domains_in_scope=["drc"], gates=[]))
    assert diag.outcome == "UNDETERMINED"
    assert diag.handoff is None
    assert diag.as_report()["reached_agent"] is False


def test_a_gate_that_says_undetermined_leaves_its_domain_undetermined():
    diag = agent_router.diagnose(
        situation(domains_in_scope=["drc"], gates=gates(drc="UNDETERMINED")))
    assert diag.outcome == "UNDETERMINED"
    assert diag.handoff is None


def test_a_known_tool_failure_leaves_the_domain_unmeasured_not_passing():
    """An understood failure is still a failure to measure. If this returned
    clean, a licence outage would read as a clean DRC."""
    diag = agent_router.diagnose(
        situation(domains_in_scope=["drc"],
                  gates=[{"domain": "drc", "verdict": "TOOL_ERROR",
                          "signature": "license_unavailable"}]))
    assert diag.outcome == "UNDETERMINED"
    assert diag.undetermined == ["drc"]
    assert diag.handoff is None


def test_a_situation_with_no_declared_scope_is_undetermined_not_clean():
    """Without a declared scope, a domain that is absent from the evidence is
    indistinguishable from one nobody meant to check -- so the router would
    report clean over a hole."""
    with pytest.raises(agent_router.SituationIncomplete):
        agent_router.diagnose(situation(gates=gates(drc="PASS")))


# --------------------------------------------------------------------------
# Refusals. rc=1 territory: the request, not the evidence, is wrong.
# --------------------------------------------------------------------------

def test_a_never_delegated_question_can_never_reach_a_handoff():
    """No reason in the closed set makes such a question delegable, so this
    must hold on a situation that would otherwise waive."""
    for question in sorted(agent_policy.NEVER_DELEGATED):
        sit = situation(question=question,
                        domains_in_scope=["timing_setup", "area"],
                        gates=gates(timing_setup="FAIL", area="FAIL"))
        with pytest.raises(agent_policy.PolicyError):
            agent_router.diagnose(sit)


def test_a_never_delegated_question_is_refused_even_when_a_human_asks():
    """HUMAN_REQUESTED_REVIEW is the reason most likely to be treated as a
    master key. It is not one."""
    sit = situation(question="pass_fail_undetermined",
                    domains_in_scope=["drc"], gates=gates(drc="FAIL"),
                    human_requested_review=True)
    with pytest.raises(agent_policy.PolicyError):
        agent_router.diagnose(sit)


def test_a_domain_outside_the_closed_set_is_refused_not_ignored():
    """An ignored domain is a violation the router reports clean."""
    with pytest.raises(agent_router.RouterRefused):
        agent_router.diagnose(
            situation(domains_in_scope=["drc", "vibes"],
                      gates=gates(drc="PASS")))


def test_a_gate_verdict_outside_the_closed_set_is_refused():
    with pytest.raises(agent_router.RouterRefused):
        agent_router.diagnose(
            situation(domains_in_scope=["drc"],
                      gates=[{"domain": "drc", "verdict": "PROBABLY_FINE"}]))


def test_an_unactivated_autonomy_level_is_refused():
    for level in ("A1", "A2", "A3"):
        policy = agent_policy.default_policy()
        policy["autonomy_level"] = level
        with pytest.raises(agent_policy.PolicyError):
            agent_router.diagnose(
                situation(domains_in_scope=["drc"], gates=gates(drc="PASS")),
                policy)


# --------------------------------------------------------------------------
# Metric records: threshold comparison is a program's job and lives here.
# --------------------------------------------------------------------------

def test_a_non_measured_record_never_enters_a_comparison():
    """PPA_INTERFACES.md 2. NOT_MEASURED carries a reason, not a value, and a
    status that is not MEASURED must not be silently read as zero."""
    for status in ("NOT_MEASURED", "NOT_APPLICABLE", "INVALID", "ESTIMATED"):
        assert agent_router._is_violation(
            {"metric": "timing.setup.wns_ns", "status": status,
             "value": -1.0}) is None


def test_a_negative_slack_is_a_violation_by_the_metrics_own_definition():
    assert agent_router._is_violation(
        {"metric": "timing.setup.wns_ns", "status": "MEASURED",
         "value": -0.124}) is True
    assert agent_router._is_violation(
        {"metric": "timing.setup.wns_ns", "status": "MEASURED",
         "value": 0.05}) is False


def test_a_limit_is_honoured_in_the_sense_it_declares():
    over = {"metric": "area.core_um2", "status": "MEASURED",
            "value": 120.0, "limit": 100.0, "limit_sense": "max"}
    assert agent_router._is_violation(over) is True
    under = dict(over, value=90.0)
    assert agent_router._is_violation(under) is False


def test_a_boolean_is_not_a_number():
    """`True` is an int in Python, so a record carrying it would compare as 1
    and silently become a measurement."""
    assert agent_router._is_violation(
        {"metric": "x.wns", "status": "MEASURED", "value": True}) is None


def test_a_metric_record_drives_the_verdict_without_any_gate():
    diag = agent_router.diagnose(
        situation(domains_in_scope=["timing_hold"],
                  metrics=[{"metric": "timing.hold.wns_ns",
                            "domain": "timing_hold",
                            "status": "MEASURED", "value": -0.03}]))
    assert diag.outcome == "PROGRAM_DECIDED"
    assert diag.violated == ["timing_hold"]


# --------------------------------------------------------------------------
# The CLI: the four fixtures on the declared invocation.
# --------------------------------------------------------------------------

def _run(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True)


def test_cli_positive_exits_zero_and_says_no_handoff(tmp_path):
    sit = tmp_path / "s.json"
    sit.write_text(json.dumps(
        situation(domains_in_scope=["timing_hold"],
                  gates=gates(timing_hold="FAIL"))))
    out = tmp_path / "r.json"
    proc = _run(str(sit), "--json", str(out))
    assert proc.returncode == 0, proc.stderr
    assert "HANDOFF     : none" in proc.stdout
    report = json.loads(out.read_text())
    assert report["reached_agent"] is False


def test_cli_negative_a_refusal_exits_one_with_a_marker(tmp_path):
    sit = tmp_path / "s.json"
    sit.write_text(json.dumps(
        situation(question="threshold_comparison",
                  domains_in_scope=["timing_setup", "area"],
                  gates=gates(timing_setup="FAIL", area="FAIL"))))
    proc = _run(str(sit))
    assert proc.returncode == 1
    assert "[REFUSE]" in proc.stderr


def test_cli_vacuous_missing_input_is_two_with_a_marker(tmp_path):
    """Not 0 and not 1. A gate whose declared invocation exits 2 on absent
    input can never fail; one that exits 1 reports a finding from a run that
    never opened its input."""
    proc = _run(str(tmp_path / "does_not_exist.json"))
    assert proc.returncode == 2
    assert "[CANNOT CHECK]" in proc.stderr


def test_cli_an_empty_file_is_undetermined_and_says_so_differently(tmp_path):
    """'I could not read it' and 'I read it and it was empty' are both rc=2,
    but the message must distinguish them or nobody can tell whether the
    producer ever ran."""
    sit = tmp_path / "s.json"
    sit.write_text("   \n")
    proc = _run(str(sit))
    assert proc.returncode == 2
    assert "empty" in proc.stderr


def test_cli_bad_invocation_is_three_not_two(tmp_path):
    """A flow that retries on 2 would loop forever on a caller's mistake."""
    proc = _run()
    assert proc.returncode == 3


def test_cli_writes_the_handoff_only_when_one_was_emitted(tmp_path):
    decided = tmp_path / "d.json"
    decided.write_text(json.dumps(
        situation(domains_in_scope=["timing_hold"],
                  gates=gates(timing_hold="FAIL"))))
    ho = tmp_path / "handoff.json"
    assert _run(str(decided), "--handoff-out", str(ho)).returncode == 0
    assert not ho.exists(), "a decided case wrote a handoff document"

    waived = tmp_path / "w.json"
    waived.write_text(json.dumps(
        situation(domains_in_scope=["timing_setup", "area"],
                  gates=gates(timing_setup="FAIL", area="FAIL"))))
    assert _run(str(waived), "--handoff-out", str(ho)).returncode == 0
    assert json.loads(ho.read_text())["reason"] == "MULTI_DOMAIN_CONFLICT"
