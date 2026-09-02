"""ppa_pr_scope_check is wired where a merge condition can refuse a merge.

vibe-ic#1347. The program landed with a unit test and nothing else, so its
verdict -- which is literally the PPA Appendix-C merge condition -- reached no
decision anywhere.

WHY `gatekeeper_review` AND NOT `tools/ci/repo_hygiene_gates.sh`. The checker
needs a base and a head. That script's own contract excludes exactly that:
"anything needing a commit RANGE or a base SHA ... stays inline in the workflow
that has the context". `.github/workflows/` is disabled in this repository, so
the one live place that holds the change-set under review is the pre-push merge
gate.

THE PART THAT IS EASY TO FAKE. A gate that never passes `--answers` can only
observe `answers_document_present: false`. While that arm was advisory such a
gate would read as wired and could never fail. So the tests below do not check
that a call exists -- they drive a real two-commit repository through every arm
and assert that the DOCUMENT moves the verdict.

EVERY ARM BLOCKS NOW, THE ABSENT ONE INCLUDED (2026-08-31, `ac3232ddeb`). The
advisory branch carried its own expiry -- "THE MOMENT an answers-document
convention exists in this repository ... the `not present` arm becomes
blocking" -- and `gatekeeper_review.py` records both halves as satisfied in
the comment block above `_PPA_ANSWERS_REL` ("THE ABSENT ARM USED TO BE
ADVISORY, AND IT STOPPED BEING SO BY ITS OWN WRITTEN CONDITION"): the path is
declared, and the repository carries a real document at it. That commit
flipped the gate and re-fixtured `test_gatekeeper_review`; the tests in this
file still encoded the old contract (no document => green, "REPORTED, not
blocking") and went red for the honest reason. The arms are therefore:

    no document            rc 1  VIOLATED, naming `_PPA_ANSWERS_REL` + the count
    a document that lies   rc 1  AUTHOR_OVERRIDE_REFUSED
    a document that holds  rc 0  merge condition met

and the control for "the flip is attributable to this gate" is the third arm,
not the first. No change-set with ZERO applicable questions can stand in for
it: questions 1-5 are catalogued `mode: always`, so even a docs-only change
applies five, and a green control has to ANSWER rather than avoid a surface
(measured in `test_no_answers_document_is_reported_with_the_count_...`).
"""
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import gatekeeper_review as G  # noqa: E402
import _hostpaths  # noqa: E402
import _watchdog  # noqa: E402


def _supervised(cmd, **kw):
    """`subprocess.run(cmd, capture_output=True, text=True, check=False)` with
    the wall-clock budget REPLACED by forward-progress supervision.

    These call sites used to carry a fixed `timeout=`. That number is not a
    property of the subject — it is a guess about a HOST — and when the guess is
    wrong on a loaded machine `TimeoutExpired` propagates out of the test and is
    recorded as the SUBJECT being broken. The verdict is then manufactured by
    the machine rather than measured on the program; the owner hit exactly that
    on a module nobody had changed.

    `_watchdog.run_host_supervised` bounds NO FORWARD PROGRESS instead — CPU and
    I/O summed over the child's whole /proc tree, plus the growth of its
    captured output — so a child that is merely slow runs to completion however
    long that legitimately takes, while one that is genuinely hung is still
    killed. A kill arrives as rc `_watchdog.RC_STALLED` with WATCHDOG_STALLED on
    stderr: a distinct code none of these subjects produces itself, so a hang
    can never be misread as an ordinary non-zero exit."""
    res = _watchdog.run_host_supervised(cmd, **kw)
    return _watchdog.completed_process(cmd, res)


def _repo_with_a_surface() -> tuple[Path, str]:
    """A two-commit repo whose second commit acquires an action surface.

    mkdtemp, not tmp_path: a pytest tmp_path carries a newline under the EDA
    container image.
    """
    d = Path(tempfile.mkdtemp(prefix="ppa1347_"))

    def git(*a):
        subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (d / "README.md").write_text("base\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d,
                          capture_output=True, text=True).stdout.strip()
    p = d / "programs"
    p.mkdir()
    (p / "thing_check.py").write_text(
        "import subprocess\n"
        "def run(cmd):\n"
        "    return subprocess.run(cmd, shell=True)\n")
    # Its test travels with it. Questions 4, 5, 11 and 19 accept ONLY `test`
    # evidence, so the arm where a document HOLDS needs a test that exists.
    # The file adds no token: measured through the checker's own report, the
    # applicable set is {1,2,3,4,5,11,19} with this file and without it.
    (p / "tests").mkdir()
    (p / "tests" / "test_thing_check.py").write_text(
        "def test_thing_runs():\n    assert True\n")
    git("add", "-A")
    git("commit", "-qm", "add a surface")
    return d, base


#: What `_repo_with_a_surface` changes, as the checker sees it: the path arm
#: reads `programs/thing_check.py` as a gate program, the content arm reads
#: `shell=True` and a non-literal argv. Tokens {gate, security, tool} make 11
#: and 19 apply on top of the five `always` questions.
_SURFACE_SRC = "programs/thing_check.py"
_SURFACE_TEST = "programs/tests/test_thing_check.py::test_thing_runs"
_SURFACE_QUESTIONS = (1, 2, 3, 4, 5, 11, 19)


def _answers(d: Path, doc: dict) -> None:
    (d / ".github").mkdir(exist_ok=True)
    (d / G._PPA_ANSWERS_REL).write_text(json.dumps(doc))


def _answers_that_hold(repo: Path, questions, src_rel: str,
                       test_ref: str) -> dict:
    """An answers document every entry of which a machine can re-verify.

    Each answered question carries all three verifiable kinds -- `path`,
    `artefact` with a sha256 COMPUTED from the file rather than typed, and a
    `test` naming a function that exists -- so whichever kind the catalogue's
    `min_evidence_kinds` accepts for that question, one entry satisfies it.
    Nothing here is asserted into existence: a ref that did not resolve, or a
    hash that did not match, would leave the gate red, which is the point.
    """
    digest = "sha256:" + hashlib.sha256((repo / src_rel).read_bytes()).hexdigest()
    return {"schema": "vibeic.ppa.pr_answers.v1",
            "answers": [{"question": q,
                         "evidence": [{"kind": "path", "ref": src_rel},
                                      {"kind": "artefact", "ref": src_rel,
                                       "sha256": digest},
                                      {"kind": "test", "ref": test_ref}]}
                        for q in questions]}


def _checker_report(d: Path, base: str) -> dict:
    """The checker's OWN report over the fixture, document withheld -- so a
    count asserted below is read from the subject, never typed here."""
    out = Path(tempfile.mkdtemp(prefix="ppa1347rep_")) / "ppa_pr_scope.json"
    r = _supervised([sys.executable, str(PROG / "ppa_pr_scope_check.py"),
                     "--repo", str(d), "--base", base, "--head", "HEAD",
                     "--json", str(out)])
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    return json.loads(out.read_text(encoding="utf-8"))


# No per-call wall-clock bound: see `_supervised` below. "The slowest child is
# ~22s so 60 has headroom" describes the host that was measured, not
# `ppa_pr_scope_check.py`; on a busier one the bound fires and the test reports
# the checker as broken.

# --------------------------------------------------------------------------- #
# the verdict is actually consulted
# --------------------------------------------------------------------------- #
def test_review_appends_the_gate_to_the_verdict():
    """A gate function nothing calls is the same orphan one directory over."""
    src = (PROG / "gatekeeper_review.py").read_text(encoding="utf-8")
    fn = [n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef) and n.name == "review"][0]
    called = {ast.unparse(c.func) for c in ast.walk(fn)
              if isinstance(c, ast.Call)}
    assert "ppa_pr_scope_gate" in called


def test_a_non_green_gate_reaches_the_blocking_list():
    """`review` derives REQUEST_CHANGES from `green`, so a red GateResult from
    this gate is a refused merge."""
    red = G.GateResult("ppa_pr_scope_check", 1, "violated")
    assert red.green is False
    assert G.GateResult("ppa_pr_scope_check", -1, "not checked").green is True


# --------------------------------------------------------------------------- #
# and it can go red
# --------------------------------------------------------------------------- #
def test_an_answers_document_that_overrides_the_detector_is_REFUSED():
    """The author does not get to say N/A. This is the arm that blocks."""
    d, base = _repo_with_a_surface()
    _answers(d, {"schema": "vibeic.ppa.pr_answers.v1",
                 "answers": [{"question": 1, "applicability": "N/A"}]})
    g = G.ppa_pr_scope_gate(d, base, "HEAD")
    assert g.green is False and g.rc == 1
    assert "AUTHOR_OVERRIDE_REFUSED" in g.summary


def test_the_blocking_arm_is_reachable_from_the_declared_answers_path():
    """The whole point of `_PPA_ANSWERS_REL`: it is where the gate picks the
    document up, so the document -- and only the document -- decides the
    verdict over ONE repository and ONE change-set.

    Until 2026-08-31 this test's control was "no document => green", because
    the absent arm was advisory. `ac3232ddeb` made it blocking by the expiry
    condition written into `gatekeeper_review.py` (the block above
    `_PPA_ANSWERS_REL`), so the honest pair is now: absent => VIOLATED naming
    the path; a document that HOLDS => green; a document that LIES => refused.
    Four states of the same repo, each read from the gate, and the two red
    ones are asserted DISTINGUISHABLE -- absent, empty and lying are three
    different refusals, and a reader acting on the summary needs to know
    which one they got.
    """
    d, base = _repo_with_a_surface()

    absent = G.ppa_pr_scope_gate(d, base, "HEAD")
    assert absent.rc == 1 and absent.green is False, absent.summary
    assert G._PPA_ANSWERS_REL in absent.summary
    assert "NO answers document was supplied" in absent.summary
    assert f"{len(_SURFACE_QUESTIONS)} of the 20 Appendix-C questions apply" \
        in absent.summary

    _answers(d, _answers_that_hold(d, _SURFACE_QUESTIONS, _SURFACE_SRC,
                                   _SURFACE_TEST))
    holds = G.ppa_pr_scope_gate(d, base, "HEAD")
    assert holds.rc == 0 and holds.green is True, holds.summary
    assert f"merge condition met ({len(_SURFACE_QUESTIONS)} applicable)" \
        in holds.summary

    _answers(d, _ANSWERS_THAT_LIE)
    lies = G.ppa_pr_scope_gate(d, base, "HEAD")
    assert lies.rc == 1 and lies.green is False, lies.summary
    assert "AUTHOR_OVERRIDE_REFUSED" in lies.summary
    assert G._PPA_ANSWERS_REL not in lies.summary    # not the absent refusal

    # present but answering nothing is a THIRD state: a finding about the
    # document, never a claim that no document was supplied.
    _answers(d, {"schema": "vibeic.ppa.pr_answers.v1", "answers": []})
    empty = G.ppa_pr_scope_gate(d, base, "HEAD")
    assert empty.rc == 1 and empty.green is False, empty.summary
    assert f"MISSING_EVIDENCE={len(_SURFACE_QUESTIONS)}" in empty.summary
    assert "NO answers document" not in empty.summary
    assert "AUTHOR_OVERRIDE_REFUSED" not in empty.summary


def test_no_answers_document_is_reported_with_the_count_not_silently_passed():
    """The absent arm is RED, and its summary carries the count a reader
    needs -- how many questions this change-set has to answer -- read from
    the checker's own report rather than typed into the assertion.

    This arm returned rc 0 with "REPORTED, not blocking" until 2026-08-31;
    `ac3232ddeb` flipped it (see the block above `_PPA_ANSWERS_REL` in
    gatekeeper_review.py). The second half of the test is why no fixture can
    dodge the document instead of answering it: every question the catalogue
    marks `mode: always` is in the applicable set, so the count is never zero
    for any change-set and "no document" is never silently a pass.
    """
    d, base = _repo_with_a_surface()
    g = G.ppa_pr_scope_gate(d, base, "HEAD")
    assert g.rc == 1 and g.green is False, g.summary
    assert "REPORTED, not blocking" not in g.summary
    assert f"NO answers document was supplied at {G._PPA_ANSWERS_REL}" \
        in g.summary

    rep = _checker_report(d, base)
    assert rep["answers_document_present"] is False
    applicable = {q["question"] for q in rep["questions"]
                  if q["applicability"] == "APPLICABLE"}
    assert applicable == set(_SURFACE_QUESTIONS), applicable
    assert f"{len(applicable)} of the 20 Appendix-C questions apply" \
        in g.summary
    catalogue = json.loads((PROG / "ppa_pr_scope_checklist.v1.json")
                           .read_text(encoding="utf-8"))
    always = {int(q["id"]) for q in catalogue["questions"]
              if q.get("applies", {}).get("mode") == "always"}
    assert always, "the catalogue declares no `always` question"
    assert always <= applicable, (
        f"`always` questions {sorted(always - applicable)} were not applied")


def test_an_unreadable_change_set_is_NOT_CHECKED_never_a_pass():
    """rc 2 is "I could not look", which must not wear the same verdict as
    "I looked and it was clean"."""
    d, _ = _repo_with_a_surface()
    g = G.ppa_pr_scope_gate(d, "no-such-ref", "HEAD")
    assert g.rc == -1 and "NOT CHECKED" in g.summary


# --------------------------------------------------------------------------- #
# PROVE-BY-RUN: the verdict, not the gate list
# --------------------------------------------------------------------------- #
# `flow-change-acceptance` §3, and the reason it is a criterion: #306 is a gate
# that was wired, tested, and FAILing on the same cell across three plugin
# versions while the flow shipped a 181 MB routed.def every time. Reading the
# aggregation and concluding "this must block" is exactly the inference that
# produced 62 of 72 gates that cannot stop anything.
#
# So this drives the REAL `review()` over the SAME synthetic repository, where
# the only difference is the answers document -- withheld, one that HOLDS, one
# that LIES -- and asserts the verdict itself moves. The control matters as
# much as the subject: it is what makes the flip attributable to this gate
# rather than to the fixture being generally unhappy. Since the absent arm
# became blocking (2026-08-31) the control is the document that holds; the
# withheld fixture is the OTHER red arm, not the baseline.

import subprocess as _sp  # noqa: E402

_ANSWERS_THAT_LIE = {"schema": "vibeic.ppa.pr_answers.v1",
                     "answers": [{"question": 1, "applicability": "N/A"}]}

#: `_reviewable_repo`'s change-set is the whole synthetic plugin, so the path
#: arm reads its stand-in gate programs and the flow YAML: tokens
#: {blast_radius, controller, flow_step, gate}, which is 11 on top of the five
#: `always` questions (measured: "6 of the 20 ... apply" with no document).
_REVIEWABLE_SRC = "vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"
_REVIEWABLE_TEST = ("vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
                    "test_widget.py::test_go")
_REVIEWABLE_QUESTIONS = (1, 2, 3, 4, 5, 11)


def _reviewable_repo(document):
    """A clean synthetic plugin (every other machine gate green) with real git
    history, so nothing is stubbed and the whole chain runs.

    `document` is None (withheld), "lies" (an applicable question marked N/A)
    or "holds" (every applicable question backed by re-verifiable evidence).
    Whichever it is, the document is committed as part of "the change", so the
    change-set has the same shape on every arm and only the content differs.
    """
    import test_gatekeeper_review as TG
    tmp = Path(tempfile.mkdtemp(prefix="ppareview_"))
    repo, plugin = TG._build_clean_plugin(tmp, version="1.0.96")

    def git(*a):
        _sp.run(["git", *a], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (repo / "README.md").write_text("base\n")
    git("add", "README.md")
    git("commit", "-qm", "base")
    base = _sp.run(["git", "rev-parse", "HEAD"], cwd=repo,
                   capture_output=True, text=True).stdout.strip()
    if document == "lies":
        doc = _ANSWERS_THAT_LIE
    elif document == "holds":
        doc = _answers_that_hold(repo, _REVIEWABLE_QUESTIONS, _REVIEWABLE_SRC,
                                 _REVIEWABLE_TEST)
    elif document is None:
        doc = None
    else:
        raise ValueError(f"document must be None, 'lies' or 'holds': {document!r}")
    if doc is not None:
        (repo / ".github").mkdir(exist_ok=True)
        (repo / G._PPA_ANSWERS_REL).write_text(json.dumps(doc))
    git("add", "-A")
    git("commit", "-qm", "the change")
    return repo, plugin, base


def _verdict(document):
    repo, plugin, base = _reviewable_repo(document)
    return G.review(
        base, "HEAD", repo=repo, plugin_root=plugin, role="core-agent",
        pytest_cmd="python3 -m pytest -q programs/tests",
        commit_cmds=["git commit -m 'fix'", "git push origin main"],
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.0.96", override_prev="1.0.95")


def test_the_control_repo_is_MERGE_OK_so_the_flip_is_attributable():
    """The control ANSWERS the merge condition; it does not avoid it.

    Until 2026-08-31 the control was the fixture with NO document, because the
    absent arm was advisory. `ac3232ddeb` made that arm blocking (the block
    above `_PPA_ANSWERS_REL` in gatekeeper_review.py), so that fixture now
    REQUEST_CHANGES on this gate alone and can attribute nothing. The control
    is the fixture whose document HOLDS -- and it is asserted green because the
    gate RAN and PASSED (rc 0), since rc -1 "not checked" would also read as
    green and would make MERGE_OK a skip rather than a pass. The withheld
    fixture is driven alongside it: same repo, same change-set shape, and the
    document is the one variable in both directions.
    """
    v = _verdict("holds")
    gate = {g.name: g for g in v.gates}["ppa_pr_scope_check"]
    assert gate.rc == 0 and gate.green is True, gate.summary
    assert f"merge condition met ({len(_REVIEWABLE_QUESTIONS)} applicable)" \
        in gate.summary
    assert v.verdict == "MERGE_OK", v.blocking
    assert v.blocking == []

    withheld = _verdict(None)
    gate = {g.name: g for g in withheld.gates}["ppa_pr_scope_check"]
    assert gate.rc == 1 and gate.green is False, gate.summary
    assert G._PPA_ANSWERS_REL in gate.summary
    assert withheld.verdict == "REQUEST_CHANGES"
    assert any("ppa_pr_scope_check" in b for b in withheld.blocking)
    # and it is the ONLY thing blocking — the document is the whole difference
    assert [b for b in withheld.blocking if "ppa_pr_scope_check" not in b] == []


def test_a_refused_author_override_turns_the_whole_review_REQUEST_CHANGES():
    v = _verdict("lies")
    assert v.verdict == "REQUEST_CHANGES"
    gate = {g.name: g for g in v.gates}["ppa_pr_scope_check"]
    assert gate.rc == 1 and gate.green is False
    assert any("ppa_pr_scope_check" in b for b in v.blocking)
    # and it is the ONLY thing blocking — same repo, one file added
    assert [b for b in v.blocking if "ppa_pr_scope_check" not in b] == []


# --------------------------------------------------------------------------- #
# the convention has to be discoverable, and then it has to stay one path
# --------------------------------------------------------------------------- #
# A path only the gate knows is not a convention; it is a private variable that
# happens to be reported. The gate says "no answers document was supplied at
# <path>" on every review, and the arm that is not blocking yet becomes
# blocking when the convention is adopted — so an author has to be able to
# find out that the file exists and what shape it takes.
#
# Documenting it creates the classic second list. This pins the two together.

def _pr_template() -> Path:
    return _hostpaths.require_repo(".github", "PULL_REQUEST_TEMPLATE.md")


def test_the_answers_path_is_documented_where_a_pr_author_will_see_it():
    body = _pr_template().read_text(encoding="utf-8")
    assert G._PPA_ANSWERS_REL in body, (
        f"{G._PPA_ANSWERS_REL} is the path the merge gate looks for and names "
        "in its own output, but no PR author is told it exists")


def test_the_documented_path_and_the_gates_constant_have_not_drifted():
    """One path, asserted from both ends. If someone moves the constant, this
    fails; if someone edits the template, this fails."""
    import re
    body = _pr_template().read_text(encoding="utf-8")
    found = set(re.findall(r"\.github/ppa_pr_answers[\w.]*\.json", body))
    assert found == {G._PPA_ANSWERS_REL}, (
        f"template mentions {found}, the gate uses {G._PPA_ANSWERS_REL!r}")


def test_the_documented_schema_string_is_the_one_the_checker_accepts():
    """The example in the template must not be a shape the checker rejects."""
    body = _pr_template().read_text(encoding="utf-8")
    assert "vibeic.ppa.pr_answers.v1" in body
    checker = (PROG / "ppa_pr_scope_check.py").read_text(encoding="utf-8")
    assert "vibeic.ppa.pr_answers.v1" in checker


# --------------------------------------------------------------------------- #
# the gate this branch exists to close, asked locally
# --------------------------------------------------------------------------- #
# Same reasoning as the flow half: `machine_runners`, not absence from
# `test_only`, because a SKILL mention would empty the latter and satisfy
# nothing. This program's venue is PROG — `gatekeeper_review` spawns it — and
# NOT the flow, because a change-set is not a design.

def _wiring_audit_report() -> dict:
    """In-process: as a spawned child this scan takes ~23s against a 60s
    harness ceiling, and that headroom measurably failed under load."""
    import checker_execution_wiring_audit as C
    plugin = PROG.parent
    return C.audit(plugin, plugin.parents[2])


def test_the_wiring_audit_credits_a_machine_runner_not_a_skill_mention():
    rep = _wiring_audit_report()
    runners = rep["machine_runners"].get("ppa_pr_scope_check.py")
    assert runners, (
        "checker_execution_wiring_audit credits NO machine runner for "
        "ppa_pr_scope_check — a skill mention does not count")
    assert "PROG" in runners, f"gatekeeper_review is not credited: {runners}"


def test_the_pr_scope_check_is_not_wired_into_the_design_flow():
    """It answers a question about a CHANGE-SET. The flow reviews a DESIGN and
    has no notion of one, so crediting FLOW here would mean it had been wired
    somewhere it cannot be evaluated."""
    rep = _wiring_audit_report()
    runners = rep["machine_runners"].get("ppa_pr_scope_check.py") or []
    assert "FLOW" not in runners, (
        f"the PR-scope check is wired into the design flow: {runners}")
    assert "ppa_pr_scope_check.py" not in (rep.get("test_only") or [])


# --------------------------------------------------------------------------- #
# rc 3 — a bad invocation is THIS WIRING's bug, and it must not read as clean
# --------------------------------------------------------------------------- #
# Found by mutation: flipping the rc-3 arm from blocking to green left every
# test in this module passing. The claim "rc 3 blocks" was in the commit
# message and in the gate, and nothing measured it.
#
# It matters because rc 3 is the ONE exit code that indicts the wiring rather
# than the PR. If a future edit passes a flag the checker does not accept, the
# gate would report green forever and the merge condition would never be
# evaluated again — a gate that cannot fail, arrived at by accident instead of
# by design. The two halves are pinned separately so neither can drift: the
# program's contract, and this gate's reading of it.

def test_the_checker_really_exits_3_on_a_bad_invocation():
    """Half one: the contract this gate depends on. argparse would exit 2,
    which in this program means UNDETERMINED — the checker overrides that
    precisely so "you typed it wrong" and "the evidence was not there" stay
    apart."""
    r = _supervised([sys.executable, str(PROG / "ppa_pr_scope_check.py"),
                     "--not-a-real-flag"])
    assert r.returncode == 3, (
        f"expected rc 3 (bad invocation), got {r.returncode}")


def test_a_bad_invocation_BLOCKS_and_is_never_reported_as_clean(monkeypatch):
    """Half two: this gate's classification. rc 3 is not the PR's fault and it
    is not a skip — it is this wiring being broken, which must be loud."""
    def _rc3(prog, args, **kw):
        return 3, "", "bad invocation: unrecognized arguments"
    monkeypatch.setattr(G, "_run_program", _rc3)
    g = G.ppa_pr_scope_gate(Path("."), "BASE", "HEAD")
    assert g.rc == 1 and g.green is False, (
        f"a bad invocation reported {g.rc}/{g.green} — a wiring that cannot "
        f"run must never read as a wiring that passed: {g.summary}")
    assert "bad invocation" in g.summary


def test_the_four_exit_codes_map_to_four_distinct_gate_readings(monkeypatch):
    """0 PASS / 1 VIOLATED / 2 NOT CHECKED / 3 BAD INVOCATION. Collapsing any
    two of them loses a distinction the checker went to trouble to make."""
    seen = {}
    for rc in (0, 1, 2, 3):
        monkeypatch.setattr(G, "_run_program",
                            lambda p, a, _rc=rc, **kw: (_rc, "", ""))
        g = G.ppa_pr_scope_gate(Path("."), "BASE", "HEAD")
        seen[rc] = (g.rc, g.green)
    assert seen[2] == (-1, True), f"rc 2 must be NOT CHECKED: {seen[2]}"
    assert seen[3] == (1, False), f"rc 3 must block: {seen[3]}"
    assert seen[0][1] is True and seen[3][1] is False
    # a skip and a broken wiring are not the same fact
    assert seen[2] != seen[3]


# --------------------------------------------------------------------------- #
# this gate declares its own intent, and no program can check that for it
# --------------------------------------------------------------------------- #
# `flow_gate_enforcement_audit` reads `ENFORCEMENT:` declarations out of the
# FLOW definition. This checker is not a flow gate — it judges a change-set,
# not a design — so that audit never sees it, and the doctrine's own promotion
# list still has "every gate declares BLOCKING vs ADVISORY" as a program that
# does not exist yet. Found by mutation: deleting the declaration left all 16
# tests green.
#
# Anchored at line start, which is the #886 rule: a declaration must OPEN its
# line. Several gates MENTION the word in prose while declaring nothing, and an
# unanchored pattern read each of those as a declaration.

def test_the_checker_declares_its_enforcement_intent_on_its_own_line():
    """Asked through the AUDIT'S OWN READER, not a regex re-typed here.

    The first version of this test re-implemented the pattern, and a test that
    re-implements the rule it checks cannot see the rule's real limits. One of
    those limits is a 4000-byte window (`declared_intent` searches only
    `text[:4000]`), which a re-typed regex does not have — so prose added above
    the line would un-declare the gate while this test stayed green. That
    exact failure happened to the sibling gate on this branch.
    """
    import flow_gate_enforcement_audit as A
    assert A.declared_intent(PROG, "ppa_pr_scope_check") == "blocking", (
        "the audit's own reader does not see this gate's declaration. Silence "
        "is not neutral: an unstated default of advisory is how 62 of 72 gates "
        "ended up unable to stop anything.")


def test_the_declaration_stays_inside_the_readers_window():
    """The bound is invisible from inside the docstring, so it needs a test
    that names it. Measured on the sibling gate: two paragraphs of prose moved
    the line to byte 4371 and the gate silently went UNDECLARED."""
    import flow_gate_enforcement_audit as A
    src = (PROG / "ppa_pr_scope_check.py").read_text(encoding="utf-8")
    idx = src.find("ENFORCEMENT:")
    assert 0 <= idx < A.DECL_WINDOW_BYTES, (
        f"the ENFORCEMENT declaration sits at byte {idx}; `declared_intent` "
        f"reads only the first {A.DECL_WINDOW_BYTES}. Present and unread "
        f"reports as UNDECLARED — move it above the prose.")


def test_the_declaration_matches_what_the_gate_actually_does(monkeypatch):
    """A declaration nothing cross-checks is the unenforced-declaration shape
    the doctrine tells you to refuse. Bind it to observed behaviour: it says
    blocking, so a finding must actually block."""
    import re
    doc = (PROG / "ppa_pr_scope_check.py").read_text(encoding="utf-8")
    declared = re.search(r"^ENFORCEMENT:\s*(\w+)\s*$", doc, re.M).group(1)
    monkeypatch.setattr(G, "_run_program", lambda p, a, **kw: (3, "", "bad"))
    blocks = G.ppa_pr_scope_gate(Path("."), "BASE", "HEAD").green is False
    assert (declared == "blocking") == blocks, (
        f"declares {declared!r} but blocking={blocks}")


# --------------------------------------------------------------------------- #
# a review artefact must not be mistakable for a step artefact
# --------------------------------------------------------------------------- #
# The gate writes its report to a TemporaryDirectory, and the reason is in the
# code: the report declares `verdict: FAIL`, and a `reports/**/*.json` carrying
# that is exactly what `step_internal_fail_bubble_up_check` refuses. Round-4
# mutation redirected the write into the repo and all 18 tests passed — the
# justification was written down and never measured.

def test_the_gate_leaves_no_artefact_in_the_repository():
    repo, base = _repo_with_a_surface()
    _answers(repo, _ANSWERS_THAT_LIE)
    before = {p.relative_to(repo) for p in repo.rglob("*") if ".git" not in p.parts}
    g = G.ppa_pr_scope_gate(repo, base, "HEAD")
    after = {p.relative_to(repo) for p in repo.rglob("*") if ".git" not in p.parts}
    assert g.rc == 1                      # it really ran and really found something
    assert after == before, f"the review wrote into the repo: {sorted(after - before)}"


def test_it_writes_no_verdict_FAIL_json_anywhere_under_reports():
    """The specific cascade: `step_internal_fail_bubble_up_check` reads any
    `reports/**/*.json` whose verdict is FAIL or MISSING as an unacknowledged
    step-internal failure."""
    import json as _j
    repo, base = _repo_with_a_surface()
    _answers(repo, _ANSWERS_THAT_LIE)
    G.ppa_pr_scope_gate(repo, base, "HEAD")
    for p in repo.rglob("reports/**/*.json"):
        v = _j.loads(p.read_text()).get("verdict")
        assert v not in ("FAIL", "MISSING"), f"{p} declares verdict={v}"
    assert not list(repo.glob("ppa_pr_scope.json"))


# --------------------------------------------------------------------------- #
# this branch's own answers document must not go stale silently
# --------------------------------------------------------------------------- #
# Committing `.github/ppa_pr_answers.json` moved THIS branch into the gate's
# blocking arm. That buys enforcement and costs upkeep: the document names a
# sha256 of the flow definition and a set of test IDs, and any of them can be
# invalidated by an ordinary later commit — edit the flow, rename a test, move
# a file.
#
# Without this test the staleness surfaces only at the MERGE GATE, i.e. to the
# lander, long after the commit that caused it. That is the #306 shape one more
# time: a check that describes a change already made instead of refusing it at
# the point it is made. The author should learn it from their own test run.
#
# Asked through `verify_evidence` — the checker's OWN verifier — rather than by
# re-deriving what "valid evidence" means. Measured: it resolves the test NAME,
# not merely the file, so a renamed test reports UNVERIFIED.

def test_this_branchs_own_answers_document_is_still_valid():
    import ppa_pr_scope_check as P
    doc = _hostpaths.require_repo(".github", "ppa_pr_answers.json")
    repo = _hostpaths.repo_path(".")
    answers = json.loads(doc.read_text(encoding="utf-8"))
    assert answers.get("schema") == "vibeic.ppa.pr_answers.v1"

    stale = []
    checked = 0
    for a in answers["answers"]:
        for e in a.get("evidence", []):
            rec = P.verify_evidence(repo, e)
            checked += 1
            if rec["status"] != "VERIFIED":
                stale.append(f"Q{a['question']} {e.get('kind')} "
                             f"{e.get('ref')} -> {rec['status']}: "
                             f"{rec.get('reason', '')}")
    assert checked, "the answers document carries no evidence at all"
    assert not stale, (
        "this branch answers its own merge gate, and that answer has gone "
        "stale — the gate will refuse the landing:\n  " + "\n  ".join(stale))


def test_every_answered_question_carries_at_least_one_entry():
    """An answer with an empty `evidence` list satisfies nothing; the checker
    reports MISSING_EVIDENCE for it. Catching that here means the author sees
    an empty answer they meant to fill in, not the lander."""
    doc = _hostpaths.require_repo(".github", "ppa_pr_answers.json")
    answers = json.loads(doc.read_text(encoding="utf-8"))
    empty = [a["question"] for a in answers["answers"] if not a.get("evidence")]
    assert not empty, f"questions answered with no evidence: {empty}"


def test_the_reader_actually_honours_the_named_window():
    """`DECL_WINDOW_BYTES` has to be the number `declared_intent` USES, not a
    constant sitting beside a hardcoded one.

    The two guards on this branch import it and assert an offset against it.
    That pins THEM to the constant — it does not pin the READER to it. If
    someone inlined `text[:4000]` back into `declared_intent` while leaving the
    constant defined, both guards would keep passing over a window that no
    longer existed, and the gate they protect could go silently UNDECLARED
    again. This is the third time on this branch that a number kept in two
    places has been the defect; this asserts there is only one.

    Behavioural, not textual: a synthetic gate whose declaration sits at byte
    11 must be READ at the shipped window and NOT read when the window is
    narrowed below it."""
    import flow_gate_enforcement_audit as A
    probe = Path(tempfile.mkdtemp(prefix="declwin_")) / "probe_check.py"
    probe.write_text('"""probe.\n\nENFORCEMENT: blocking\n'
                     '=====================\n"""\n' + "# pad\n" * 50)
    assert probe.read_text().find("ENFORCEMENT:") < 20

    original = A.DECL_WINDOW_BYTES
    try:
        assert A.declared_intent(probe.parent, "probe_check") == "blocking"
        A.DECL_WINDOW_BYTES = 10          # narrower than the declaration's offset
        assert A.declared_intent(probe.parent, "probe_check") is None, (
            "`declared_intent` ignored DECL_WINDOW_BYTES — the window is "
            "hardcoded somewhere and the constant is decorative, so every "
            "guard that imports it is measuring the wrong thing")
    finally:
        A.DECL_WINDOW_BYTES = original
    # and the restore really restored it, or later tests inherit a broken audit
    assert A.declared_intent(probe.parent, "probe_check") == "blocking"


def test_the_merge_gates_composed_programs_list_is_complete():
    """`gatekeeper_review`'s docstring says it AGGREGATES existing programs and
    then lists them: "The existing programs it COMPOSES (import or subprocess —
    never re-implemented)". A list that claims that and omits entries is a
    catalogue a reader cannot trust — and the merge gate is exactly where
    someone goes to learn what a landing is checked against.

    MEASURED on origin/main before this branch touched it: FOUR programs were
    spawned by a gate and absent from the list. Wiring this branch's checker in
    made it five. Adding only my own entry would have documented mine and left
    four untrue lines standing.

    Derived from the source both ways rather than from a hand-kept list: the
    spawned set comes from `_PROGRAMS_DIR / "<name>.py"` inside each `*_gate`
    function, the listed set from the docstring's bullets."""
    import ast
    import re
    src = (PROG / "gatekeeper_review.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    spawned = set()
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name.endswith("_gate")]:
        body = ast.get_source_segment(src, fn) or ""
        spawned |= {m.group(1) for m in
                    re.finditer(r'_PROGRAMS_DIR / "([a-z0-9_]+\.py)"', body)}
    assert spawned, "no gate spawns a program — the extractor is broken"
    listed = {m.group(1) for m in
              re.finditer(r'\*\s+([a-z0-9_]+\.py)', ast.get_docstring(tree) or "")}
    missing = sorted(spawned - listed)
    assert not missing, (
        "these programs are spawned by a gate and absent from the docstring's "
        "list of what it composes:\n  " + "\n  ".join(missing))
