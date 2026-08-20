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

import ast
import json
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
import _published_corpus as _pc  # noqa: E402

# THE RATCHET WAS OFF ON EVERY HOST, AND SAID `skipped`.
#
# This module resolved the corpus as `REPO / "benchmark-data" / "ic"`. v1.10.56
# moved the published cells into their own repository, so that path has not
# existed since — and the guard below is a `skipif`, so the whole file reported
# `9 passed, 12 skipped`. MEASURED on clean main, with and without a corpus
# clone present:
#
#     VIBE_IC_BENCHMARK_DATA unset       9 passed, 12 skipped
#     VIBE_IC_BENCHMARK_DATA=<a clone>   9 passed, 12 skipped
#
# Byte-identical. The twelve tests that ARE the ratchet — the ones that would
# notice a fourteenth gate starting to forge a green, or a thirteenth quietly
# stopping — could not run anywhere, and their skip was indistinguishable from
# a pass. `_published_corpus` is the repo's one answer to "where did the corpus
# go", and it refuses loudly when somebody names a corpus that is not one.
_CORPUS = _pc.corpus_root()
IC = (_CORPUS / "ic") if _CORPUS is not None else Path("/nonexistent-corpus")
CELL = IC / "spm" / "v1.9.96_gf180mcuD"
DONOR = IC / "sha256" / "clean_run_v1427_20260715"
OLDER = IC / "sha256" / "clean_run_v1422_20260715"

#: The gate that NOTICES, measured. Keeping the pair small keeps the test quick
#: while preserving the only property that matters: one of each colour.
FORGEABLE = ("drc_report_check", (".",))
DEFENDING = ("sta_report_check", (".", "--mode", "sta"))

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

_corpus = pytest.mark.skipif(
    not (CELL.is_dir() and DONOR.is_dir()), reason=_pc.SKIP_REASON)


# ===========================================================================
# THE INSTRUMENT MUST STILL BE ABLE TO REPORT SUCCEEDED
#
# The thirteen findings this module recorded are CLOSED: the sign-off gates now
# bind every report they consume to the digest the run recorded producing it
# (`_run_evidence_binding`). That closure creates a NEW way for this file to
# become worthless — every verdict going DEFENDED because the attack broke
# reads exactly like every verdict going DEFENDED because the flow got safe.
#
# So the finding assertions below no longer point at the published cell. They
# point at a run that recorded NOTHING, which is not a contrivance: the binding
# defends a run that declared its outputs, and a run that declared none is
# genuinely unprotected — that is the honest limit of the fix, and it is
# asserted here rather than described. The published cell then supplies the
# other colour, with the SAME instrument, in the PAIRED tests.
# ===========================================================================
_UNBOUND_GATE = ("antenna_report_check", (".", "--mode", "antenna"))

_UNBOUND_RPT = (
    "# openroad antenna check (gate-oxide protection)\n"
    "# Tool: openroad / check_antennas (ANT).\n"
    "# A complete, clean, tool-signed report — the kind a substitution\n"
    "# attack uses, because a report that is GONE is a failure and a report\n"
    "# that still parses is the forgery.\n"
    "antenna check: 0 net violations, 0 pin violations\n"
    "antenna clean: YES\n"
    "[INFO ANT-0002] Found 0 net violations.\n"
    "[INFO ANT-0001] Found 0 pin violations.\n"
    "# run marker: {marker}\n"
)


def _unbound_cell(root: Path, marker: str) -> Path:
    """A green cell that recorded NOTHING about what produced its reports.

    No `provenance.jsonl`, no `steps/**/STEP_RECORD.json`. Nothing here can
    answer "whose report is this", which is the state every published cell was
    in from the gate's point of view before the binding landed.
    """
    d = root / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "antenna.rpt").write_text(_UNBOUND_RPT.format(marker=marker),
                                   encoding="utf-8")
    return root


# ===========================================================================
# THE FINDING, AND ITS DISCRIMINATING TWIN
# ===========================================================================
def test_the_adversary_finds_the_cross_design_forgery(tmp_path):
    """A gate certifies THIS design using ANOTHER design's reports.

    Measured on v1.10.33 against the published cell: six of seven sign-off
    gates stayed green after 149 artefacts were substituted from a different
    IC. Those six are closed. The attack is not: a run that recorded nothing
    about what produced its reports still has no way to tell, and this asserts
    the instrument can still SEE that.
    """
    cell = _unbound_cell(tmp_path / "cell", "A")
    donor = _unbound_cell(tmp_path / "donor", "B")
    got = AA.attack_cross_design(PLUGIN, cell, donor, gates=(_UNBOUND_GATE,))
    assert len(got) == 1, got
    a = got[0]
    assert a.verdict == AA.SUCCEEDED, (
        f"substituting another run's report did not forge a green even on a "
        f"cell that recorded nothing: {a}. The attack itself has broken, and "
        f"every DEFENDED this file reports is now unfalsifiable.")
    assert a.evidence["rc_before"] == 0 and a.evidence["rc_after"] == 0, a
    assert a.evidence["substituted"] > 0, "nothing was substituted"


@_corpus
def test_PAIRED_the_same_attack_on_a_run_that_RECORDED_its_outputs_is_DEFENDED():
    """THE TWIN, and the closure. Same attack, same instrument, same gate —
    the only difference is that the published cell declared the digests of the
    reports it produced, so the substituted bytes have something to disagree
    with.

    If this ever reports SUCCEEDED, the binding stopped being consulted.
    """
    got = AA.attack_cross_design(PLUGIN, CELL, DONOR, gates=(FORGEABLE,))
    assert len(got) == 1, got
    assert got[0].verdict == AA.DEFENDED, (
        f"a published cell that records its own outputs was forged again: "
        f"{got[0]}. Thirteen findings closed on this property.")


@_corpus
def test_PAIRED_a_gate_that_DOES_notice_is_reported_DEFENDED():
    """The historical twin, kept: `sta_report_check` objected to the
    cross-design substitution before any binding existed."""
    got = AA.attack_cross_design(PLUGIN, CELL, DONOR, gates=(DEFENDING,))
    assert len(got) == 1, got
    assert got[0].verdict == AA.DEFENDED, (
        f"the one gate measured to notice this attack no longer does: {got[0]}. "
        f"An attack that succeeds against everything measures nothing.")


def test_the_stale_replay_is_a_separate_finding_from_cross_design(tmp_path):
    """A2 — an EARLIER run of the same design, which is harder to notice.

    Distinct from A3 on purpose: the artefact belongs to this design, so a check
    keyed on design identity still passes and only a check keyed on WHICH RUN
    produced it can object. Asserted on the unbound cell for the same reason as
    its A3 sibling above.
    """
    cell = _unbound_cell(tmp_path / "cell", "A")
    older = _unbound_cell(tmp_path / "older", "A-earlier")
    got = AA.attack_stale_replay(PLUGIN, cell, older, gates=(_UNBOUND_GATE,))
    assert len(got) == 1 and got[0].verdict == AA.SUCCEEDED, got
    assert got[0].evidence["substituted"] > 0, got


@_corpus
def test_PAIRED_the_stale_replay_is_DEFENDED_on_a_run_that_recorded_its_outputs():
    got = AA.attack_stale_replay(PLUGIN, CELL, OLDER, gates=(FORGEABLE,))
    assert len(got) == 1 and got[0].verdict == AA.DEFENDED, got


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


def test_the_report_publishes_the_fraction_that_was_attempted(tmp_path):
    cell = _unbound_cell(tmp_path / "cell", "A")
    donor = _unbound_cell(tmp_path / "donor", "B")
    rc, report = AA.run_campaign(PLUGIN, cell, donor, None,
                                 gates=(_UNBOUND_GATE,))
    cov = report["coverage"]
    assert cov["attacks_declared"] > cov["attacks_with_an_attempt"], (
        "every declared attack was attempted, so the coverage figure is not "
        f"telling a reader anything: {cov}")
    assert rc == 1, "the measured forgery did not make the campaign fail"
    assert report["findings"], report["counts"]


@_corpus
def test_PAIRED_the_campaign_PASSES_on_the_published_cell():
    """Prove-by-run of the closure, through the same entry point. The campaign
    that reported thirteen forged greens against this cell now reports none —
    and `attempted` is unchanged, so nothing was closed by going UNAVAILABLE."""
    rc, report = AA.run_campaign(PLUGIN, CELL, DONOR, OLDER)
    assert rc == 0, (rc, report["findings"])
    assert not report["findings"], report["findings"]
    assert report["counts"]["attempted"] == 21, (
        f"the campaign attempted {report['counts']['attempted']} attacks, not "
        f"the 21 that produced the thirteen findings. A finding count that "
        f"fell because fewer attacks ran is not progress.")
    assert report["verdict"] == "ALL_DEFENDED", report["verdict"]


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


def test_the_cli_reports_the_forgery_and_exits_1(tmp_path):
    """The shipped CLI, in a subprocess, because the exit code is the product."""
    cell = _unbound_cell(tmp_path / "cell", "A")
    donor = _unbound_cell(tmp_path / "donor", "B")
    r = subprocess.run(
        [sys.executable, str(PROG), str(cell), "--donor", str(donor)],
        capture_output=True, text=True, timeout=_CLI_BOUND_S)
    assert r.returncode == 1, (r.returncode, r.stdout[-800:], r.stderr[-400:])
    assert "FORGED GREEN" in r.stdout, r.stdout[-800:]
    assert "P0 integrity defect" in r.stdout, r.stdout[-800:]
    # ...and the UNAVAILABLE count is always disclosed, never left implicit.
    assert "UNAVAILABLE and therefore" in r.stdout, r.stdout[-400:]


def test_the_json_report_round_trips(tmp_path):
    out = tmp_path / "r.json"
    cell = _unbound_cell(tmp_path / "cell", "A")
    donor = _unbound_cell(tmp_path / "donor", "B")
    r = subprocess.run(
        [sys.executable, str(PROG), str(cell), "--donor", str(donor),
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
    ic = IC
    cell = ic / led["cell"]
    donor = ic / led["donor"]
    older = ic / led["older_run"]
    out = []
    out += AA.attack_cross_design(PLUGIN, cell, donor)
    out += AA.attack_stale_replay(PLUGIN, cell, older)
    out += AA.attack_tamper_destructive(PLUGIN, cell)
    return led, out


@_corpus
def test_the_findings_ratchet_holds_in_BOTH_directions():
    """13 forged greens are recorded. A fourteenth is a regression; a twelfth is
    progress that must be adjudicated, not absorbed."""
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
    assert len(d["held"]) == len(led["forging"]), (
        f"{len(d['held'])} of {len(led['forging'])} recorded findings still "
        f"reproduce; the rest were neither closed nor unproven, which means the "
        f"comparison itself is broken")


def test_PAIRED_the_ratchet_can_SEE_a_new_forgery(tmp_path):
    """The twin. A ratchet that reports zero on everything is not one.

    THIS TEST USED TO REQUIRE THE REPO TO STILL BE BROKEN. It re-ran the recorded
    attacks against the published cell and demanded `>= 6` of them still
    SUCCEEDED — so the moment the findings closed, the only control proving the
    ratchet can SEE a forgery became impossible to run. A non-vacuity control
    that depends on the defect it guards dies with the fix and takes the
    guarantee with it.

    It now manufactures a REAL forgery instead: a run that recorded nothing about
    its outputs, attacked with the shipped attack, producing genuine SUCCEEDED
    attempts. The ratchet must report every one of them as newly forging against
    an empty record.
    """
    cell = _unbound_cell(tmp_path / "cell", "A")
    donor = _unbound_cell(tmp_path / "donor", "B")
    attempts = AA.attack_cross_design(PLUGIN, cell, donor, gates=(_UNBOUND_GATE,))
    live_succeeded = [a for a in attempts if a.verdict == AA.SUCCEEDED]
    assert live_succeeded, (
        "the attack produced no forgery at all, so this control cannot say "
        "whether the ratchet would see one")
    d = AA.ratchet_diff({"forging": []}, attempts)
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


def _python_references(path: Path, name: str) -> bool:
    """Does this .py file REFER to `name` in code, as opposed to in prose?

    A RAW SUBSTRING SCAN READ A COMMENT AS A CALL SITE — MEASURED.
    This predicate used to be `if name in p.read_text()`. Two files that merely
    DESCRIBE the adversarial campaign in their module docstrings — the shared
    evidence-binding helper and the sign-off guard written from its findings —
    were reported as wiring, and the test demanded the honest "NOT WIRED YET"
    disclosure be deleted on the strength of two prose sentences.

    That is the exact shape `matrix_63x8/README.md` rule 3 forbids: *"If you
    scan source text: strip comments and strings first — a `# e.g. "foo_check"`
    comment was once counted as a call site."* The rule was written down in this
    campaign's own substrate and then violated by this campaign's own test.

    So: parse, and count only what could actually reach the program — an import
    of it, a name/attribute spelling it, or a NON-docstring string literal that
    names it (which is how a subprocess argv or a program path is spelled).
    """
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return False
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(name in (a.name or "") for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if name in (node.module or ""):
                return True
        elif isinstance(node, ast.Name) and name in node.id:
            return True
        elif isinstance(node, ast.Attribute) and name in node.attr:
            return True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            if name in node.value:
                return True
    return False


def test_PAIRED_prose_is_not_wiring_but_a_call_is(tmp_path):
    """THE TWIN for `_python_references`. Both directions, on the same token.

    A predicate that answered "no" to everything would make the disclosure
    permanent and unfalsifiable, which is the same silence the raw substring
    scan produced in the other direction.
    """
    name = "adversarial_agent"
    prose = tmp_path / "prose.py"
    prose.write_text(
        '''"""A module docstring that DESCRIBES adversarial_agent findings."""\n'''
        "# adversarial_agent is named here in a comment only\n"
        "VALUE = 1\n", encoding="utf-8")
    assert _python_references(prose, name) is False

    for spelling in (
            "import adversarial_agent\n",
            "from adversarial_agent import run_campaign\n",
            'CMD = ["python3", "adversarial_agent.py"]\n',
            "def f(mod):\n    return mod.adversarial_agent\n"):
        code = tmp_path / "code.py"
        code.write_text(spelling, encoding="utf-8")
        assert _python_references(code, name) is True, spelling


def test_the_unwired_state_is_disclosed_or_gone():
    """Wiring is MEASURED, and the disclosure dies with it.

    This author required exactly this of #1092 and had not applied it here.
    Both directions: while nothing invokes this program the docstring must carry
    the NOT WIRED section, and the moment somebody wires it this test fails and
    forces the section out.
    """
    name = "adversarial_agent"
    own = {"adversarial_agent.py", "test_adversarial_agent.py",
           "adversarial_findings.json", "INDEX.md"}
    callers = []
    for d in (PLUGIN / "flow", PLUGIN / "benchmark", PLUGIN / "programs"):
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.name in own:
                continue
            # `.md` is dropped entirely: a markdown file cannot invoke a
            # program, so a mention in one is documentation, never wiring.
            if p.suffix == ".py":
                if _python_references(p, name):
                    callers.append(p.relative_to(PLUGIN).as_posix())
                continue
            if p.suffix not in (".yaml", ".yml", ".json"):
                continue
            # A declaration file naming the program IS the wiring — that is
            # what `flow/*.yaml` and `benchmark/CAPTURE_ROUTING.json` are for.
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
