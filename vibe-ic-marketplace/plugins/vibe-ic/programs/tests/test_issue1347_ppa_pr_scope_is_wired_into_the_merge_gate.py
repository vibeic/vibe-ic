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
observe `answers_document_present: false`, which is the arm that does not
block. It would read as wired and could never fail. So the tests below do not
check that a call exists -- they drive a real two-commit repository through
both arms and assert one of them is RED.
"""
import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import gatekeeper_review as G  # noqa: E402


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
    git("add", "-A")
    git("commit", "-qm", "add a surface")
    return d, base


def _answers(d: Path, doc: dict) -> None:
    (d / ".github").mkdir(exist_ok=True)
    (d / G._PPA_ANSWERS_REL).write_text(json.dumps(doc))


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
    """The whole point of `_PPA_ANSWERS_REL`: without it the gate would never
    pass `--answers`, would only ever see the non-blocking arm, and could not
    fail for any input at all."""
    d, base = _repo_with_a_surface()
    before = G.ppa_pr_scope_gate(d, base, "HEAD")
    assert before.green is True                      # no document yet
    _answers(d, {"schema": "vibeic.ppa.pr_answers.v1", "answers": []})
    after = G.ppa_pr_scope_gate(d, base, "HEAD")
    assert after.green is False                      # same repo, document added
    assert G._PPA_ANSWERS_REL in before.summary


def test_no_answers_document_is_reported_with_the_count_not_silently_passed():
    d, base = _repo_with_a_surface()
    g = G.ppa_pr_scope_gate(d, base, "HEAD")
    assert g.green is True
    assert "REPORTED, not blocking" in g.summary
    assert "of the 20 Appendix-C questions apply" in g.summary


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
# So this drives the REAL `review()` twice over the SAME synthetic repository,
# where the only difference is the presence of the answers document, and
# asserts the verdict itself moves. The control matters as much as the subject:
# it is what makes the flip attributable to this gate rather than to the
# fixture being generally unhappy.

import subprocess as _sp  # noqa: E402

_ANSWERS_THAT_LIE = {"schema": "vibeic.ppa.pr_answers.v1",
                     "answers": [{"question": 1, "applicability": "N/A"}]}


def _reviewable_repo(with_answers: bool):
    """A clean synthetic plugin (every other machine gate green) with real git
    history, so nothing is stubbed and the whole chain runs."""
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
    if with_answers:
        (repo / ".github").mkdir(exist_ok=True)
        (repo / G._PPA_ANSWERS_REL).write_text(json.dumps(_ANSWERS_THAT_LIE))
    git("add", "-A")
    git("commit", "-qm", "the change")
    return repo, plugin, base


def _verdict(with_answers: bool):
    repo, plugin, base = _reviewable_repo(with_answers)
    return G.review(
        base, "HEAD", repo=repo, plugin_root=plugin, role="core-agent",
        pytest_cmd="python3 -m pytest -q programs/tests",
        commit_cmds=["git commit -m 'fix'", "git push origin main"],
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.0.96", override_prev="1.0.95")


def test_the_control_repo_is_MERGE_OK_so_the_flip_is_attributable():
    v = _verdict(with_answers=False)
    assert v.verdict == "MERGE_OK", v.blocking
    assert v.blocking == []


def test_a_refused_author_override_turns_the_whole_review_REQUEST_CHANGES():
    v = _verdict(with_answers=True)
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
    import _hostpaths
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
    import subprocess
    import tempfile as _tf
    out = Path(_tf.mkdtemp(prefix="cewppa_")) / "cew.json"
    subprocess.run([sys.executable,
                    str(PROG / "checker_execution_wiring_audit.py"),
                    "--json", str(out)],
                   capture_output=True, text=True, timeout=600)
    return json.loads(out.read_text())


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
    import subprocess as _s
    r = _s.run([sys.executable, str(PROG / "ppa_pr_scope_check.py"),
                "--not-a-real-flag"], capture_output=True, text=True, timeout=120)
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
