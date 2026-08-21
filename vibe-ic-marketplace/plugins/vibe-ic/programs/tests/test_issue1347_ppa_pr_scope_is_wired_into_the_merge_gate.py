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
