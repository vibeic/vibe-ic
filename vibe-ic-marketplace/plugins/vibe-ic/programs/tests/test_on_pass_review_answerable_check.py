#!/usr/bin/env python3
"""An on-pass gate must be able to REFUSE, or it is a comment with a gate's name.

MEASURED on main at v1.13.40: six enabled `on_pass_review:` stages, nine rules,
and every declared gate command carried neither `--compliance` nor
`--stage-verdict`. `stage_on_pass_review.stage_passed()` then returns
UNESTABLISHED and the program exits 2 before consulting a single rule -- on
every input, forever.

The proof that this is about the INVOCATION and not the engine is
`test_the_engine_rejects_the_same_fixture_the_declared_command_could_not_judge`
below: the repo's own known-BAD stage-3 fixture returns rc 2 under the old
declared command and rc 1 REJECT under the same command plus a verdict source.
Same fixture, same engine, same rule.

The subject is pinned by IDENTITY, not by size: `ENABLED_ON_PASS_STAGES`
below names the stages themselves, because a count stays green through a swap
and would let this module judge a population nobody chose. The "six" in the
paragraph above is a measurement taken at v1.13.40, not the pin.

Every rule is proved on a purpose-built flow that VIOLATES it and again on the
repaired copy of that same flow, so no test here can pass for the reason the
check is absent. The shipped flow is the control that must stay green in both
arms. rc 2 is asserted as a DISTINCT outcome throughout: it means the question
could not be put, and it is never accepted as a pass.
"""
import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAM = PLUGIN / "programs" / "on_pass_review_answerable_check.py"
ENGINE = PLUGIN / "programs" / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
FIXTURES = PLUGIN / "programs" / "tests" / "fixtures" / "stage3_on_pass_review"
REPO = PLUGIN.parents[2]
HYGIENE = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
#: The label `tools/ci/repo_hygiene_gates.sh` declares this gate under.
GATE_LABEL = "on-pass gates can establish a verdict"

#: The report `final_gate` writes and every on-pass gate reads.
REPORT = "reports/flow_compliance.json"

#: WHICH stages the shipped flow declares an ENABLED on-pass gate for.
#:
#: This was `len(...) == 6`, and a count is invariant under a SWAP: one stage
#: arriving in the same batch as another departs holds the number at six while
#: the population this module judges has become a DIFFERENT SET, and the
#: assertion stays green over it. The answer a reader needs is never how many,
#: it is which -- so the identities are pinned, and every comparison against
#: them below reports the two directions apart: a member that DEPARTED and a
#: member that ARRIVED are different facts and must not share one number.
ENABLED_ON_PASS_STAGES = {
    "stage_phase1",
    "stage1",
    "stage2",
    "stage_analog",
    "stage3",
    "stage4",
}


def _run(flow: Path):
    r = subprocess.run([sys.executable, str(PROGRAM), "--flow", str(flow)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _flow_doc():
    return yaml.safe_load(FLOW.read_text(encoding="utf-8"))


def _write(tmp_path: Path, doc, name="flow.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


def _reviews(doc):
    return [s for s in doc["stages"] if isinstance(s.get("on_pass_review"), dict)]


def _enabled_with_gate(doc):
    out = []
    for s in _reviews(doc):
        r = s["on_pass_review"]
        if r.get("enabled", True) is not False and (r.get("gate") or {}).get(
                "program_exit_zero"):
            out.append(s)
    return out


# ── the control ──────────────────────────────────────────────────────────────
def test_the_shipped_flow_is_green():
    rc, out = _run(FLOW)
    assert rc == 0, f"the shipped flow must satisfy this check:\n{out}"
    assert "[PASS]" in out


def test_the_shipped_flow_declares_exactly_these_enabled_on_pass_gates():
    """The check must not be green because the subject moved underneath it.

    A count cannot distinguish a swap from no change, so it cannot establish
    that the six stages judged today are the six that were judged when this
    number was written. The set can, and it names the difference in both
    directions when it moves.
    """
    got = {s["id"] for s in _enabled_with_gate(_flow_doc())}
    assert got == ENABLED_ON_PASS_STAGES, (
        "the enabled on-pass population is not the one pinned here.\n"
        f"  departed (pinned, no longer enabled with a gate): "
        f"{sorted(ENABLED_ON_PASS_STAGES - got)}\n"
        f"  arrived  (enabled with a gate, never pinned):     "
        f"{sorted(got - ENABLED_ON_PASS_STAGES)}\n"
        "if the axis legitimately changed, update the identities above "
        "deliberately -- a count would not have shown you this line.")


def test_every_shipped_gate_reads_the_report_the_final_gate_writes():
    doc = _flow_doc()
    written = doc["final_gate"]["args"]
    assert f"--json {REPORT}" in written, (
        f"final_gate must write the compliance report the gates read: {written}")
    for s in _enabled_with_gate(doc):
        cmd = s["on_pass_review"]["gate"]["program_exit_zero"]
        assert f"--compliance {REPORT}" in cmd, (
            f"{s['id']} cannot establish a stage verdict: {cmd}")


# ── P1: a gate with no verdict source ────────────────────────────────────────
def test_p1_a_gate_with_no_verdict_source_is_refused_by_name(tmp_path):
    doc = _flow_doc()
    victim = _enabled_with_gate(doc)[0]
    gate = victim["on_pass_review"]["gate"]
    gate["program_exit_zero"] = gate["program_exit_zero"].replace(
        f" --compliance {REPORT}", "")
    rc, out = _run(_write(tmp_path, doc))
    assert rc == 1, f"planting P1 must FAIL, got rc={rc}:\n{out}"
    assert "P1 CANNOT REJECT" in out
    assert victim["id"] in out, "the finding must NAME the offending stage"
    assert rc != 2, "rc 2 is 'the question could not be put', never a verdict"


def test_p1_the_same_flow_passes_once_the_verdict_source_is_restored(tmp_path):
    """The negative control's other arm: repairing it must go green."""
    doc = _flow_doc()
    victim = _enabled_with_gate(doc)[0]
    gate = victim["on_pass_review"]["gate"]
    original = gate["program_exit_zero"]
    gate["program_exit_zero"] = original.replace(f" --compliance {REPORT}", "")
    assert _run(_write(tmp_path, doc, "broken.yaml"))[0] == 1
    gate["program_exit_zero"] = original
    rc, out = _run(_write(tmp_path, doc, "repaired.yaml"))
    assert rc == 0, f"restoring the flag must PASS, got rc={rc}:\n{out}"


def test_p1_fires_on_every_offending_stage_not_just_the_first(tmp_path):
    doc = _flow_doc()
    for s in _enabled_with_gate(doc):
        g = s["on_pass_review"]["gate"]
        g["program_exit_zero"] = g["program_exit_zero"].replace(
            f" --compliance {REPORT}", "")
    rc, out = _run(_write(tmp_path, doc))
    assert rc == 1
    named = {sid for sid in ENABLED_ON_PASS_STAGES if sid in out}
    assert named == ENABLED_ON_PASS_STAGES, (
        f"every offending stage must be NAMED, not merely counted; the "
        f"finding is silent about {sorted(ENABLED_ON_PASS_STAGES - named)}:"
        f"\n{out}")
    assert out.count("P1 CANNOT REJECT") == len(ENABLED_ON_PASS_STAGES), (
        f"one finding per offending stage, not just the first:\n{out}")


# ── P2: the report nothing writes ────────────────────────────────────────────
def test_p2_a_gate_reading_a_report_the_flow_never_writes_is_refused(tmp_path):
    doc = _flow_doc()
    doc["final_gate"]["args"] = doc["final_gate"]["args"].replace(
        f" --json {REPORT}", "")
    rc, out = _run(_write(tmp_path, doc))
    assert rc == 1, f"planting P2 must FAIL, got rc={rc}:\n{out}"
    assert "P2 NAMES A REPORT THE FLOW NEVER WRITES" in out


def test_p2_a_gate_reading_a_different_report_is_refused_by_name(tmp_path):
    doc = _flow_doc()
    victim = _enabled_with_gate(doc)[0]
    gate = victim["on_pass_review"]["gate"]
    gate["program_exit_zero"] = gate["program_exit_zero"].replace(
        f"--compliance {REPORT}", "--compliance reports/typo_compliance.json")
    rc, out = _run(_write(tmp_path, doc))
    assert rc == 1, f"planting a path typo must FAIL, got rc={rc}:\n{out}"
    assert "P2 READS A DIFFERENT REPORT THAN THE FLOW WRITES" in out
    assert victim["id"] in out


def test_p2_repairs_green(tmp_path):
    doc = _flow_doc()
    original = doc["final_gate"]["args"]
    doc["final_gate"]["args"] = original.replace(f" --json {REPORT}", "")
    assert _run(_write(tmp_path, doc, "broken.yaml"))[0] == 1
    doc["final_gate"]["args"] = original
    assert _run(_write(tmp_path, doc, "repaired.yaml"))[0] == 0


# ── P3: a disabled clause that still carries a gate ──────────────────────────
def test_p3_a_disabled_clause_carrying_a_gate_is_refused(tmp_path):
    doc = _flow_doc()
    disabled = [s for s in _reviews(doc)
                if s["on_pass_review"].get("enabled") is False]
    assert disabled, "the flow no longer ships a disabled clause to test P3 on"
    disabled[0]["on_pass_review"]["gate"] = {
        "program_exit_zero": (f"stage_on_pass_review . --stage "
                              f"{disabled[0]['id']} --compliance {REPORT}")}
    rc, out = _run(_write(tmp_path, doc))
    assert rc == 1, f"planting P3 must FAIL, got rc={rc}:\n{out}"
    assert "P3 DISABLED CLAUSE CARRIES A GATE" in out
    assert disabled[0]["id"] in out


def test_p3_repairs_green(tmp_path):
    doc = _flow_doc()
    disabled = [s for s in _reviews(doc)
                if s["on_pass_review"].get("enabled") is False][0]
    disabled["on_pass_review"]["gate"] = {
        "program_exit_zero": "stage_on_pass_review . --stage x --compliance y"}
    assert _run(_write(tmp_path, doc, "broken.yaml"))[0] == 1
    del disabled["on_pass_review"]["gate"]
    assert _run(_write(tmp_path, doc, "repaired.yaml"))[0] == 0


# ── unreadable input is rc 2, never a silent PASS ────────────────────────────
def test_an_unreadable_flow_is_rc2_and_not_a_pass(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("stages: [oh no: : :\n", encoding="utf-8")
    rc, out = _run(bad)
    assert rc == 2, f"unreadable input must be rc 2, got {rc}:\n{out}"
    assert "[PASS]" not in out


def test_a_missing_flow_is_rc2_and_not_a_pass(tmp_path):
    rc, out = _run(tmp_path / "nope.yaml")
    assert rc == 2
    assert "[PASS]" not in out


# ── WHY this check exists, proved on the engine itself ───────────────────────
def _stage3_run(tmp_path, fixture: str, with_report: bool) -> Path:
    import shutil
    root = tmp_path / fixture
    shutil.copytree(FIXTURES / fixture, root)
    if with_report:
        rep = root / REPORT
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text('{"steps": [{"id": 30, "name": "sta", '
                       '"stage": "stage3", "status": "PASS"}]}\n',
                       encoding="utf-8")
    return root


def _engine(root: Path, *extra):
    r = subprocess.run(
        [sys.executable, str(ENGINE), ".", "--stage", "stage3",
         "--flow-def", str(FLOW), *extra],
        cwd=str(root), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.skipif(not (FIXTURES / "reject_sgmii").is_dir(),
                    reason="stage3 on-pass fixtures not present")
def test_the_engine_rejects_the_same_fixture_the_declared_command_could_not_judge(tmp_path):
    """The defect in one assertion: identical engine, identical fixture.

    Without a verdict source the review cannot put the question (rc 2). With
    one it puts it and the answer is REJECT (rc 1). Nothing about the rule,
    the artefact or the intent changed between the two calls.
    """
    blind = _stage3_run(tmp_path, "reject_sgmii", with_report=False)
    rc_blind, out_blind = _engine(blind)
    assert rc_blind == 2, f"expected the old shape to be rc 2:\n{out_blind}"
    assert "unestablished" in out_blind

    seeing = _stage3_run(tmp_path / "b", "reject_sgmii", with_report=True)
    rc_see, out_see = _engine(seeing, "--compliance", REPORT)
    assert rc_see == 1, f"expected a proven REJECT:\n{out_see}"
    assert "R3_SIGNOFF_CLOCK_SLOWER_THAN_INTENT" in out_see


@pytest.mark.skipif(not (FIXTURES / "accept_subservient").is_dir(),
                    reason="stage3 on-pass fixtures not present")
def test_the_fixed_invocation_still_accepts_a_clean_run(tmp_path):
    """The green arm: the fix must not turn every stage into a rejection."""
    root = _stage3_run(tmp_path, "accept_subservient", with_report=True)
    rc, out = _engine(root, "--compliance", REPORT)
    assert rc == 0, f"a clean stage-3 run must still ACCEPT:\n{out}"
    assert "ACCEPT" in out


# ── the gate is wired where CI reads it ──────────────────────────────────────
@pytest.mark.skipif(not HYGIENE.is_file(), reason="hygiene gate file absent")
def test_the_check_is_wired_into_the_hygiene_gates():
    text = HYGIENE.read_text(encoding="utf-8")
    assert GATE_LABEL in text, (
        f"a check nothing runs is the defect it exists to prevent; declare it "
        f"in {HYGIENE.relative_to(REPO)}")
    assert "on_pass_review_answerable_check.py" in text
