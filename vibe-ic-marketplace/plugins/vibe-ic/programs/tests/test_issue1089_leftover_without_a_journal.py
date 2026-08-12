"""A leftover mutant with NO journal must be refused, not measured. vibe-ic#1089.

#1090 gives this gate crash-durability: a journal written outside the tree
before the mutation reaches disk, so the next run can repair what a killed run
left. That closes the crash THIS gate causes. It does not close the population
#1089 was filed about, because a leftover can exist with no journal beside it:

  * it pre-dates the journal — every checkout carrying one today;
  * `/tmp` was cleared by a reboot or a tmp reaper while the tree survived;
  * the journal is keyed by `sha256(root.resolve())`, so MOVING or renaming a
    worktree orphans it while the leftover stays exactly where it was.

In each of those `recover_journal` returns "nothing to repair", which is true
and useless: the sweep then re-derives the argued value FROM the leftover, flips
*that*, watches the candidate tests pass, and reports the site UNPINNED.

MEASURED 2026-08-12 against the FIXED tool (`4b22e36e` + #1090), journal
confirmed absent, one site (`--only matrix_mutation_ledger`):

    clean      md5 f572930bc14f3f1143419ba8bf8df4ea  [PINNED]   mode='witness'  rc 0
    leftover   md5 28b755fecaaa0c211a721896ff7a8963  [UNPINNED] mode='all'      rc 1

The second line names `mode='all'` — the leftover, reported as the authored
value. `UNPINNED` reads as "this argued direction is unprotected, go write a
test". The direction is fine. The tree is dirty.

WHY REFUSE AND NOT REPAIR: without a journal the gate cannot prove the
difference is its own — an author editing that literal produces byte-identical
evidence — and `recover_journal` already draws exactly this line for the case it
CAN see. So the false FINDING becomes a named REFUSAL (rc 2), which is what
`run` at `repo_hygiene_gates.sh:964` should block on.

WHY THE SIGNATURE IS NARROW: refusing on "the file differs from HEAD" would go
red for anyone mid-edit anywhere in a 2000-line module — the failure mode
`run_tolerating_uncheckable` exists to avoid. It fires only when the difference
is AT THE ARGUED LITERAL and HEAD's value is one of the closed alternatives this
gate itself flips between. The two controls below hold that boundary from both
sides.
"""
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"

sys.path.insert(0, str(PROGRAMS))
import policy_direction_pin_check as pdpc  # noqa: E402


def _repo(tmp_path: Path, body: str) -> Path:
    """A throwaway git repo with one committed module."""
    r = tmp_path / "repo"
    (r / "programs").mkdir(parents=True)
    (r / "programs" / "mod.py").write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    return r


#: `arg_col` is the column of the opening quote, which is what `_literal_span`
#: is given. Computed rather than typed so the fixture cannot drift.
LINE = '    plan = replay_plan("witness")\n'
COL = LINE.index('"')


def _site(value: str, alternatives=("all", "witness")) -> dict:
    return {"file": "mod.py", "line": 1, "arg_line": 1, "arg_col": COL,
            "value": value, "alternatives": list(alternatives)}


def test_a_journal_less_leftover_is_refused_and_not_reported_unpinned(tmp_path):
    """The defect, at the unit the whole verdict turns on."""
    r = _repo(tmp_path, LINE)
    (r / "programs" / "mod.py").write_text(
        LINE.replace("witness", "all"), encoding="utf-8")
    why = pdpc.leftover_signature(r / "programs", _site("all"))
    assert why is not None, (
        "a file differing from HEAD at exactly the argued literal, into "
        "another of this gate's own alternatives, was accepted as the authored "
        "source — that is the false UNPINNED #1089 measured")
    assert "git checkout HEAD --" in why, (
        f"the refusal does not tell the reader how to clear it:\n{why}")
    assert "'witness'" in why and "mod.py" in why, why


def test_a_clean_tree_is_not_refused(tmp_path):
    """False-positive control. Without this the check could be `return True`."""
    r = _repo(tmp_path, LINE)
    assert pdpc.leftover_signature(r / "programs", _site("witness")) is None


def test_an_in_flight_edit_elsewhere_in_the_same_file_is_not_refused(tmp_path):
    """The boundary from the permissive side.

    A maintainer mid-change has the file dirty. Refusing on "differs from HEAD"
    would make this gate permanently red for them, and a permanently red gate
    is one people learn to route around.
    """
    r = _repo(tmp_path, LINE + "# unrelated\n")
    (r / "programs" / "mod.py").write_text(
        LINE + "# unrelated, and now edited\n", encoding="utf-8")
    assert pdpc.leftover_signature(r / "programs", _site("witness")) is None


def test_an_edit_to_the_literal_outside_the_closed_set_is_not_refused(tmp_path):
    """The boundary from the other side.

    Someone changed that literal to something this gate never writes. It is not
    a leftover this gate could have produced, so it is not this check's subject
    and claiming it would be a guess.
    """
    r = _repo(tmp_path, LINE)
    (r / "programs" / "mod.py").write_text(
        LINE.replace("witness", "something_nobody_argued"), encoding="utf-8")
    assert pdpc.leftover_signature(
        r / "programs", _site("something_nobody_argued")) is None


def test_a_moved_line_is_not_guessed_at(tmp_path):
    """HEAD has something else at that position. The difference is then not a
    bare literal flip, and inventing a verdict from it would be the same
    over-claiming this whole gate exists to remove."""
    r = _repo(tmp_path, "# a line that was later inserted above\n" + LINE)
    (r / "programs" / "mod.py").write_text(
        LINE.replace("witness", "all"), encoding="utf-8")
    assert pdpc.leftover_signature(r / "programs", _site("all")) is None


def test_a_subject_outside_git_proceeds_and_says_so(tmp_path):
    """"I could not look" must never reach a reader as "I looked and it
    matched" — so it does not block, and it does not stay quiet either."""
    d = tmp_path / "notarepo" / "programs"
    d.mkdir(parents=True)
    (d / "mod.py").write_text(LINE, encoding="utf-8")
    before = len(pdpc._HEAD_BLIND)
    assert pdpc.leftover_signature(d, _site("witness")) is None
    assert len(pdpc._HEAD_BLIND) == before + 1, (
        "a site whose HEAD copy could not be read was measured silently")


def test_the_write_path_and_the_read_head_path_share_one_parser():
    """`flip_source` and `leftover_signature` must not drift into two ideas of
    where the literal is — the second would then vouch for a position the first
    does not write to."""
    src = LINE
    lines, idx, start, end = pdpc._literal_span(src, 1, COL)
    assert lines[idx][start:end] == "witness"
    flipped = pdpc.flip_source(src, _site("witness"), "all")
    assert flipped == LINE.replace("witness", "all")
