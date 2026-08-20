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
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

import _published_corpus as _pc

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[2]
PROG = PLUGIN / "programs" / "adversarial_agent.py"

sys.path.insert(0, str(PLUGIN / "programs"))
import adversarial_agent as AA  # noqa: E402

from _published_corpus import CORPUS_ENV, corpus_root  # noqa: E402


def _ic_root():
    """The `ic/` directory of whichever published corpus is offered HERE.

    THIS FUNCTION IS THE FIX, AND ITS ABSENCE IS WHY THE RATCHET WAS DEAD.
    The module used to spell the corpus as a constant::

        IC = REPO / "benchmark-data" / "ic"

    v1.10.56 moved `benchmark-data/` out of this repository entirely -- `git
    ls-tree -r HEAD -- benchmark-data` now matches nothing -- so that path has
    not resolved on any checkout since. It never consulted the pointer every
    other corpus-backed module in this directory reads, so even a host WITH a
    clone could not switch the checks on. Measured on `49d2b3328`, both with and
    without `VIBE_IC_BENCHMARK_DATA` set to a real clone::

        9 passed, 12 skipped in 0.79s

    Twelve of the twenty-one tests here are the corpus-backed ones, and the
    ratchet that makes a finding a P0 defect rather than a printed line is among
    them. So for forty versions the thirteen recorded forgeries were guarded by
    nothing: a fourteenth gate could have started accepting foreign evidence and
    the suite would have stayed green, which is the precise failure the RATCHET
    section of `adversarial_agent` was written to prevent.

    `corpus_root()` raises when the pointer is SET and broken, and that is
    deliberate -- see `_published_corpus.corpus_root`. A named corpus that is not
    there is a different fact from no corpus at all, and only the second one may
    skip.
    """
    root = corpus_root()
    return (root / "ic") if root is not None else None


IC = _ic_root()

#: The cells the campaign was measured against. Read from the LEDGER rather than
#: re-typed here: the ledger is the record these tests exist to defend, and a
#: second spelling of the same cell name is a second thing to keep in step. It
#: also keeps the process identifiers out of this module (NDA).
_LEDGER = AA.load_findings_ledger()
CELL = (IC / _LEDGER["cell"]) if IC else None
DONOR = (IC / _LEDGER["donor"]) if IC else None
OLDER = (IC / _LEDGER["older_run"]) if IC else None

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
    not (CELL and DONOR and CELL.is_dir() and DONOR.is_dir()),
    reason=f"published cells absent here; point {CORPUS_ENV} at a clone of "
           f"vibeic/benchmark-data to run the ratchet. This is 'could not "
           f"look', not 'nothing was wrong'.")


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
    ic = _ic_root()
    assert ic is not None, (
        "the corpus vanished between collection and execution; the `_corpus` "
        "mark should have skipped this test")
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


@_corpus
def test_PAIRED_the_ratchet_can_SEE_a_new_forgery():
    """The twin. A ratchet that reports zero on everything is not one.

    Plants a finding the record does not contain by pretending the ledger is
    empty, and requires the diff to report every live SUCCEEDED as newly forging.
    """
    _led, attempts = _live_recorded_attacks()
    d = AA.ratchet_diff({"forging": []}, attempts)
    live_succeeded = [a for a in attempts if a.verdict == AA.SUCCEEDED]
    assert len(d["newly_forging"]) == len(live_succeeded) >= 6, (
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


def _executable_python(text: str):
    """`text` with comments and docstrings removed, or None if it will not parse.

    Every OTHER string literal is KEPT, because that is how a real caller spells
    one: `subprocess.run([..., "adversarial_agent.py"])` is a wiring and a line
    crediting the program in a comment is not.

    TOKEN FILTERING, NOT `str.replace`, AND THE REASON IS MEASURED. The first
    version removed each comment span with `text.replace(span, "")`. One span in
    `eda_report_audit.py` is the bare string `"#"`, so that call stripped the `#`
    from EVERY comment in the file -- including the one being searched for --
    and the comment's words then survived as bare text. The file was reported as
    a caller on the strength of a comment the function believed it had removed.
    """
    import io
    import tokenize as _tk
    try:
        toks = list(_tk.generate_tokens(io.StringIO(text).readline))
        tree = ast.parse(text)
    except (_tk.TokenError, IndentationError, SyntaxError, ValueError):
        # FAIL SAFE: a file we cannot parse reads as a CALLER. The expensive
        # direction of an error here is a disclosure claiming nothing invokes a
        # program that something does.
        return None
    docstrings = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            c = body[0].value
            docstrings.add((c.lineno, c.col_offset))
    keep = []
    for tok in toks:
        if tok.type == _tk.COMMENT:
            continue
        if tok.type == _tk.STRING and tok.start in docstrings:
            continue
        keep.append(tok.string)
    return "\n".join(keep)


def _names_it_outside_prose(path: Path, name: str) -> bool:
    """Does this file name the program somewhere that could REACH it?

    THE DEFECT THIS REPLACES. The predicate was `name in p.read_text()`, over
    every .py/.yaml/.json/.md under flow/, benchmark/ and programs/. That is not
    the question the disclosure makes: `adversarial_agent`'s docstring claims it
    "appears in no flow/*.yaml step, no benchmark/CAPTURE_ROUTING.json entry, no
    runner, and none of flow_compliance_check.py's registered gates". A COMMENT
    naming the program is none of those things.

    MEASURED, and the reason this is being changed rather than worked around:
    citing the campaign in the code it produced made this test declare the
    program wired --

        AssertionError: adversarial_agent is now referenced by
        ['programs/eda_report_audit.py',
         'programs/tests/test_evidence_binding_belongs_to_this_run.py']
        -- it is wired. Delete the 'NOT WIRED YET' section

    -- when both mentions are prose crediting where a finding came from. Under
    the old predicate the only way to keep the suite green is to stop attributing
    findings in comments, which is a worse repository.

    IT IS NOT LOOSER WHERE IT MATTERS. Only Python comments and docstrings are
    removed. Ordinary string literals stay, so `subprocess.run([...,
    "adversarial_agent.py"])` and `import adversarial_agent` both still count,
    and yaml/json/md are searched whole -- a flow step or a routing entry naming
    the program is exactly the wiring this is looking for.
    `test_PAIRED_the_wiring_detector_still_catches_a_REAL_caller` holds that.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    if name not in text:
        return False
    if path.suffix != ".py":
        return True
    code = _executable_python(text)
    if code is None:
        return True
    return name in code


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
            if p.suffix not in (".py", ".yaml", ".yml", ".json", ".md"):
                continue
            if _names_it_outside_prose(p, name):
                callers.append(p.relative_to(PLUGIN).as_posix())
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


# ===========================================================================
# THE RATCHET MUST BE ON, AND THAT IS ITSELF MEASURED
#
# Everything above is worth exactly nothing on a host where the corpus does not
# resolve, and for forty versions that was EVERY host. A skip is the honest
# rendering of "could not look" and this suite is right to use one -- but a skip
# nobody can switch OFF is indistinguishable from a check that was deleted, and
# it reads as a green suite either way.
#
# So the resolution itself is now under test, with a SYNTHESIZED corpus, so the
# guard is decidable on a bare checkout with no clone anywhere near it.
# ===========================================================================
def _reimport_with_pointer(root: Path):
    """This module, re-executed with `CORPUS_ENV` naming `root`.

    Re-execution rather than `importlib.reload` so the probe cannot disturb the
    module object the running session collected its tests from.
    """
    spec = importlib.util.spec_from_file_location(
        "adversarial_ratchet_probe", Path(__file__).resolve())
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synthetic_corpus(tmp_path: Path) -> Path:
    """A corpus shaped like a published one, holding the three cells the ledger
    names. Empty directories: `_corpus` asks `is_dir()` and nothing more, and
    the property under test is WHICH ROOT was consulted, not what is in it."""
    led = AA.load_findings_ledger()
    root = tmp_path / "benchmark-data"
    for key in ("cell", "donor", "older_run"):
        (root / "ic" / led[key]).mkdir(parents=True, exist_ok=True)
    return root


def test_the_corpus_is_resolved_through_the_shared_POINTER(tmp_path, monkeypatch):
    """Point at a corpus and this module must look in it.

    THE PRE-FIX VALUE THIS OBSERVES: the module resolved `IC` to
    `<repo>/benchmark-data/ic` -- a path v1.10.56 emptied -- no matter what the
    caller pointed at, so the assertion below reports two concrete paths that
    differ rather than something being absent.
    """
    root = _synthetic_corpus(tmp_path)
    monkeypatch.setenv(CORPUS_ENV, str(root))
    mod = _reimport_with_pointer(root)
    assert mod.IC == root / "ic", (
        f"this module resolved its corpus to {mod.IC}, but the caller pointed "
        f"{CORPUS_ENV} at {root}. A corpus-backed suite that ignores the "
        f"pointer cannot be switched on, and every check in it reports "
        f"'skipped' forever -- which is how thirteen recorded forgeries went "
        f"forty versions with nothing guarding them.")


def test_PAIRED_the_corpus_marker_actually_SELECTS_when_a_corpus_is_there(
        tmp_path, monkeypatch):
    """The twin, and the half that matters.

    Resolving the root is not the property; SELECTING the tests is. A marker
    still keyed on something else would satisfy the test above and skip
    everything anyway, so this one reads the mark's own condition.
    """
    root = _synthetic_corpus(tmp_path)
    monkeypatch.setenv(CORPUS_ENV, str(root))
    mod = _reimport_with_pointer(root)
    skipped = mod._corpus.args[0]
    assert skipped is False, (
        f"the corpus mark still evaluates to skip={skipped!r} with a corpus "
        f"present at {root}. Resolving the root is not enough: the mark decides "
        f"whether a single one of these checks ever runs.")


def test_PAIRED_no_corpus_still_SKIPS_rather_than_inventing_one(
        tmp_path, monkeypatch):
    """The other direction, so the fix cannot be 'never skip'.

    Making the suite unconditionally run would satisfy both tests above and
    would fail every corpus check on a plain checkout, which is the error
    `_published_corpus` exists to prevent: a check that cannot measure must not
    report that it measured.
    """
    monkeypatch.delenv(CORPUS_ENV, raising=False)
    monkeypatch.setattr(_pc, "_REPO", tmp_path / "no-such-repo")
    mod = _reimport_with_pointer(tmp_path)
    assert mod.IC is None, mod.IC
    assert mod._corpus.args[0] is True, (
        "with no corpus offered anywhere the mark must skip; a suite that runs "
        "these checks against nothing reports absence as a defect")


def test_PAIRED_the_wiring_detector_still_catches_a_REAL_caller(tmp_path):
    """The half that stops the fix above from being "check less".

    Three spellings a genuine wiring uses, each in a file whose ONLY other
    mention of the program is prose. If any of them stops counting, the
    disclosure could go stale while something really did invoke it.
    """
    name = "adversarial_agent"
    real = {
        "an import": f"# credit: {name}\nimport {name}\n",
        "a subprocess path": (
            f'"""Docstring mentioning {name}."""\n'
            f'import subprocess\n'
            f'subprocess.run(["python3", "{name}.py"])\n'),
        "an attribute call": (
            f"# see {name}\nimport importlib\n"
            f"m = importlib.import_module('{name}')\nm.run_campaign()\n"),
    }
    for label, body in real.items():
        p = tmp_path / f"caller_{abs(hash(label))}.py"
        p.write_text(body, encoding="utf-8")
        assert _names_it_outside_prose(p, name) is True, (
            f"{label}: a real caller stopped being detected, so the "
            f"NOT WIRED disclosure could go stale while something invokes it")

    prose_only = {
        "a module docstring": f'"""This closes a finding {name} reported."""\n',
        "a comment": f"# measured by {name}\nx = 1\n",
        "a comment inside a function": f"def f():\n    # {name} found it\n    return 1\n",
    }
    for label, body in prose_only.items():
        p = tmp_path / f"prose_{abs(hash(label))}.py"
        p.write_text(body, encoding="utf-8")
        assert _names_it_outside_prose(p, name) is False, (
            f"{label}: attributing a finding in prose still reads as wiring")


def test_a_flow_or_routing_file_naming_it_ALWAYS_counts(tmp_path):
    """yaml / json / md are searched whole and deliberately so: those are the
    three places the disclosure names, and there is no executable-vs-prose
    distinction to draw in a flow declaration."""
    name = "adversarial_agent"
    for suffix in (".yaml", ".json", ".md"):
        p = tmp_path / f"decl{suffix}"
        p.write_text(f"# {name}\n", encoding="utf-8")
        assert _names_it_outside_prose(p, name) is True, suffix


def test_an_unparseable_python_file_is_treated_as_a_caller(tmp_path):
    """Fail SAFE. A file this cannot tokenize must read as wiring, never as
    prose: the expensive direction of this test's error is a stale disclosure
    that says nothing invokes a program something does."""
    p = tmp_path / "broken.py"
    p.write_text("def f(:\n  # adversarial_agent\n", encoding="utf-8")
    assert _names_it_outside_prose(p, "adversarial_agent") is True
