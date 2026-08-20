#!/usr/bin/env python3
"""The Appendix C checklist gate — every property it is allowed to be trusted for.

Each test here is named after the thing that would be true if the property were
absent, because that is the failure a future author has to be stopped from
reintroducing. The four fixtures the PPA interface freeze requires
(`docs/PPA_INTERFACES.md` §7) are marked in their docstrings: POSITIVE,
NEGATIVE, VACUOUS, MUTATION.

The tests build real git repositories in `tmp_path` rather than mocking the
change-set. The whole claim of this program is that it reads what a PR actually
did; a test that handed it a hand-written list of "changed paths" would be
asserting against the author's idea of a diff, not against a diff.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
from pathlib import Path

import pytest

mod = importlib.import_module("ppa_pr_scope_check")


# --------------------------------------------------------------------------
# Fixture plumbing.
# --------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo),
         "-c", "user.name=t", "-c", "user.email=t@t",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True)
    assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc.stdout


def _write(repo: Path, rel: str, text: str) -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def make_repo(tmp_path: Path, base: dict, head: dict) -> Path:
    """A two-commit repo. `base` is the world before the PR, `head` after."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _write(repo, ".keep", "")
    for rel, text in base.items():
        _write(repo, rel, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    for rel, text in head.items():
        _write(repo, rel, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "head")
    return repo


def run(repo: Path, answers: dict | None = None, extra: list | None = None,
        base: str = "HEAD~1", head: str = "HEAD") -> tuple[int, dict]:
    """Invoke the gate the way CI would, and return (rc, report)."""
    out = repo / "_report.json"
    argv = ["--repo", str(repo), "--json", str(out)]
    if base and head:
        argv += ["--base", base, "--head", head]
    if answers is not None:
        ans = repo / "_answers.json"
        ans.write_text(json.dumps(answers), encoding="utf-8")
        argv += ["--answers", str(ans)]
    argv += extra or []
    rc = mod.main(argv)
    report = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    return rc, report


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def status_of(report: dict, qid: int) -> str:
    for row in report["questions"]:
        if row["question"] == qid:
            return row["status"]
    raise AssertionError(f"question {qid} absent from the report")


def applicability_of(report: dict, qid: int) -> str:
    for row in report["questions"]:
        if row["question"] == qid:
            return row["applicability"]
    raise AssertionError(f"question {qid} absent from the report")


#: A helper whose PATH no rule watches. The point of every test that uses it is
#: that the path arm is blind to it and something else has to see it.
UNWATCHED = "vibe-ic-marketplace/plugins/vibe-ic/programs/helper_utility.py"

DOC = "vibe-ic-marketplace/plugins/vibe-ic/docs/notes.md"


# --------------------------------------------------------------------------
# The catalogue is the contract; check it before checking anything that reads it.
# --------------------------------------------------------------------------
class TestCatalogue:
    def test_twenty_questions_with_the_spec_numbering(self):
        """C.1's numbering is non-contiguous ON PURPOSE.

        6, 7, 11, 12, 16, 18, 19 and 20 live in C.2. A future reader who
        "tidies" the gap would silently move eight questions from
        scope-conditional to always-required, or lose them.
        """
        cat = mod._load_catalogue(None)
        ids = [q["id"] for q in cat["questions"]]
        assert ids == list(range(1, 21))
        c2 = sorted(q["id"] for q in cat["questions"] if q["section"] == "C.2")
        assert c2 == [6, 7, 11, 12, 16, 18, 19, 20]

    def test_the_c1_release_clause_is_joint_not_per_question(self):
        """C.1: 'For a PR that touches neither AI nor closure, questions 8-10,
        13-15 and 17 may be marked N/A.' The permission is granted by the
        ABSENCE OF BOTH, so all seven carry the same token set. Splitting them
        per question would be an invention, and would let a PR that touches AI
        skip the actuator questions."""
        cat = mod._load_catalogue(None)
        by_id = {q["id"]: q for q in cat["questions"]}
        for qid in (8, 9, 10, 13, 14, 15, 17):
            assert by_id[qid]["applies"]["tokens"] == ["ai", "agent", "closure"]

    def test_every_scoped_question_names_a_machine_checkable_na_reason(self):
        """The merge condition requires a machine-checkable reason for every
        inapplicable question. A question with no `na_reason_code` could only
        produce a generic one, which is the prose answer this gate exists to
        refuse."""
        cat = mod._load_catalogue(None)
        for q in cat["questions"]:
            if q["applies"]["mode"] == "any_token":
                assert q["applies"].get("na_reason_code")

    def test_questions_that_ask_whether_something_was_exercised_demand_a_test(self):
        cat = mod._load_catalogue(None)
        by_id = {q["id"]: q for q in cat["questions"]}
        for qid in (4, 5, 11, 19):
            assert by_id[qid]["min_evidence_kinds"] == ["test"]
        assert by_id[3]["min_evidence_kinds"] == ["artefact"]


# --------------------------------------------------------------------------
# POSITIVE.
# --------------------------------------------------------------------------
class TestPositive:
    def test_a_fully_evidenced_documentation_change_is_green(self, tmp_path):
        """POSITIVE FIXTURE. Green when it should be green.

        A documentation-only PR: no AI, no closure, no gate. Twelve of the
        twenty questions are N/A by the detector, six are applicable, and each
        applicable one carries evidence a machine re-verified. That is the
        merge condition, and it exits 0.
        """
        repo = make_repo(
            tmp_path,
            base={"evidence/measured.rpt": "wns 0.031\n",
                  "t/test_thing.py": "def test_placeholder():\n    pass\n"},
            head={DOC: "The extractor reads one report and records its hash.\n",
                  "t/test_thing.py":
                      "def test_placeholder():\n    pass\n\n\n"
                      "def test_absent_input_exits_two():\n    pass\n\n\n"
                      "def test_rc_two_is_not_mapped_to_pass():\n    pass\n"},
        )
        art = sha(repo / "evidence/measured.rpt")
        answers = {
            "schema": mod.ANSWERS_SCHEMA,
            "answers": [
                {"question": 1, "evidence": [
                    {"kind": "path", "ref": DOC}]},
                {"question": 2, "evidence": [
                    {"kind": "path", "ref": DOC}]},
                {"question": 3, "evidence": [
                    {"kind": "artefact", "ref": "evidence/measured.rpt",
                     "sha256": art}]},
                {"question": 4, "evidence": [
                    {"kind": "test",
                     "ref": "t/test_thing.py::test_absent_input_exits_two"}]},
                {"question": 5, "evidence": [
                    {"kind": "test",
                     "ref": "t/test_thing.py::test_rc_two_is_not_mapped_to_pass"}]},
                {"question": 12, "evidence": [
                    {"kind": "path", "ref": DOC}]},
            ],
        }
        rc, report = run(repo, answers)
        assert rc == mod.RC_PASS, report["missing_evidence"]
        assert report["verdict"] == "PASS"
        assert report["summary"]["undetermined"] == 0
        # and the N/A ones each carry a code a machine can re-derive
        for row in report["questions"]:
            if row["applicability"] == "NOT_APPLICABLE":
                assert row["applicability_reason_code"].startswith(
                    ("NO_", "NEITHER_"))
                assert row["searched_tokens"]


# --------------------------------------------------------------------------
# NEGATIVE — the fixture the lane brief says is the one that matters.
# --------------------------------------------------------------------------
class TestNegative:
    def test_an_agent_action_surface_without_the_security_answer_is_red(
            self, tmp_path):
        """NEGATIVE FIXTURE. Red when it should be red.

        The PR adds an agent action surface and answers everything except
        question 19. The gate must call that out specifically — not merely
        exit non-zero for some other reason.
        """
        agent_policy = ("vibe-ic-marketplace/plugins/vibe-ic/programs/"
                        "_ppa/agent_policy.py")
        repo = make_repo(
            tmp_path, base={},
            head={agent_policy: "ALLOWLIST = ('remeasure',)\n"},
        )
        answers = {"schema": mod.ANSWERS_SCHEMA,
                   "answers": [{"question": 19, "evidence": []}]}
        rc, report = run(repo, answers)
        assert rc == mod.RC_FAIL
        assert applicability_of(report, 19) == "APPLICABLE"
        assert status_of(report, 19) == "MISSING_EVIDENCE"
        assert 19 in [m["question"] for m in report["missing_evidence"]]

    def test_the_detector_is_not_fooled_by_moving_the_code_to_an_unwatched_file(
            self, tmp_path):
        """The finding this lane was told to design against.

        The identical action surface is written into a program whose filename
        no path rule watches. If the gate only knew a list of filenames, the
        security question would go N/A here and the PR would merge.

        The first assertion is the load-bearing one: it proves the PATH arm
        really is blind to this file, so the second assertion is about the
        content arm and not about a path rule that happened to match.
        """
        repo = make_repo(
            tmp_path, base={},
            head={UNWATCHED:
                  "import subprocess\n\n\n"
                  "def apply(step):\n"
                  "    subprocess.run(step['cmd'], shell=True)\n"},
        )
        rc, report = run(repo, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        watched = [h for h in report["detector"]["path_hits"]
                   if h["path"] == UNWATCHED]
        assert watched == [], "the path arm was supposed to be blind to this file"
        assert "security" in report["detector"]["detected_tokens"]
        assert applicability_of(report, 19) == "APPLICABLE"
        assert status_of(report, 19) == "MISSING_EVIDENCE"
        assert rc == mod.RC_FAIL
        rules = {h["rule"] for h in report["detector"]["content_hits"]}
        assert "shell_true" in rules

    def test_prose_never_satisfies_a_question(self, tmp_path):
        """'Twenty long answers' is exactly what the merge condition is not."""
        repo = make_repo(tmp_path, base={},
                         head={DOC: "A note about the extractor.\n"})
        answers = {"schema": mod.ANSWERS_SCHEMA, "answers": [
            {"question": 1, "evidence": [
                {"kind": "prose",
                 "text": "Yes, it measures a metric, at post-route, under "
                         "the functional mode, and we thought about it a lot."}]},
        ]}
        rc, report = run(repo, answers)
        assert rc == mod.RC_FAIL
        assert status_of(report, 1) == "MISSING_EVIDENCE"
        kinds = [e["status"] for e in
                 [r for r in report["questions"] if r["question"] == 1][0]
                 ["evidence"]]
        assert kinds == ["UNVERIFIABLE_BY_DESIGN"]

    def test_an_artefact_whose_hash_does_not_match_is_a_finding(self, tmp_path):
        """Question 3 asks for the artifact AND its hash. A link to a file that
        is not the file the number came from is worse than no link: it looks
        like provenance."""
        repo = make_repo(tmp_path,
                         base={"evidence/m.rpt": "wns 0.031\n"},
                         head={DOC: "note\n"})
        answers = {"schema": mod.ANSWERS_SCHEMA, "answers": [
            {"question": 3, "evidence": [
                {"kind": "artefact", "ref": "evidence/m.rpt",
                 "sha256": "sha256:" + "0" * 64}]}]}
        rc, report = run(repo, answers)
        assert rc == mod.RC_FAIL
        row = [r for r in report["questions"] if r["question"] == 3][0]
        assert row["evidence"][0]["status"] == "MISMATCH"

    def test_an_evidence_link_cannot_point_outside_the_repository(self, tmp_path):
        """An evidence link is written by the author of the PR under review, so
        it is precisely the traversal input question 19 asks about."""
        repo = make_repo(tmp_path, base={}, head={DOC: "note\n"})
        answers = {"schema": mod.ANSWERS_SCHEMA, "answers": [
            {"question": 1, "evidence": [
                {"kind": "path", "ref": "../../../etc/passwd"}]}]}
        rc, report = run(repo, answers)
        assert rc == mod.RC_FAIL
        row = [r for r in report["questions"] if r["question"] == 1][0]
        assert row["evidence"][0]["status"] == "INVALID"

    def test_an_answers_document_that_answers_nothing_is_a_finding_not_a_skip(
            self, tmp_path):
        """Hard rule 9, first half. The document was READ and it was empty; that
        is a fact about the PR, and rc=1 is where facts about the PR go."""
        repo = make_repo(tmp_path, base={}, head={DOC: "note\n"})
        rc, report = run(repo, {})
        assert rc == mod.RC_FAIL
        assert report["answers_document_present"] is True


# --------------------------------------------------------------------------
# The author does not get to decide applicability.
# --------------------------------------------------------------------------
class TestAuthorCannotSkip:
    def test_marking_an_applicable_question_na_is_refused(self, tmp_path):
        """If this passed, the checklist would be exactly as strong as the
        least careful author's self-assessment."""
        repo = make_repo(
            tmp_path, base={},
            head={UNWATCHED: "import subprocess\n\n\n"
                             "def go(c):\n    subprocess.run(c, shell=True)\n"})
        answers = {"schema": mod.ANSWERS_SCHEMA, "answers": [
            {"question": 19, "applicability": "N/A",
             "evidence": [{"kind": "prose", "text": "not a security change"}]}]}
        rc, report = run(repo, answers)
        assert rc == mod.RC_FAIL
        assert status_of(report, 19) == "AUTHOR_OVERRIDE_REFUSED"
        assert "detector" in [r for r in report["questions"]
                              if r["question"] == 19][0]["detail"]

    def test_a_declared_scope_can_add_a_question_but_never_remove_one(
            self, tmp_path):
        """Declaring scope is allowed to widen the checklist because a widening
        is always safe. It is not allowed to narrow it, because a narrowing is
        the same act as marking a question N/A with extra steps."""
        repo = make_repo(
            tmp_path, base={},
            head={UNWATCHED: "import subprocess\n\n\n"
                             "def go(c):\n    subprocess.run(c, shell=True)\n"})
        # narrowing attempt: declare an unrelated scope and nothing else
        _, narrow = run(repo, {"schema": mod.ANSWERS_SCHEMA,
                               "declared_scope": ["docs"], "answers": []})
        assert applicability_of(narrow, 19) == "APPLICABLE"
        assert narrow["detector"]["detected_not_declared"]
        # widening: a token the detector did not find still switches a question on
        _, wide = run(repo, {"schema": mod.ANSWERS_SCHEMA,
                             "declared_scope": ["casebook"], "answers": []})
        assert applicability_of(wide, 18) == "APPLICABLE"
        assert wide["detector"]["declared_only_tokens"] == ["casebook"]


# --------------------------------------------------------------------------
# VACUOUS.
# --------------------------------------------------------------------------
class TestVacuous:
    def test_a_missing_change_set_is_rc2_with_a_printed_marker(
            self, tmp_path, capsys):
        """VACUOUS FIXTURE. Missing input gives rc=2 and says so.

        Not rc=0: a run that never saw a change-set has not established that the
        checklist is satisfied. Not rc=1: it has not established that it is
        violated either.
        """
        rc = mod.main(["--repo", str(tmp_path),
                       "--changed-file", str(tmp_path / "nope.txt")])
        err = capsys.readouterr().err
        assert rc == mod.RC_UNDETERMINED
        assert "[CANNOT CHECK]" in err
        assert "VACUOUS_PASS:" in err

    def test_an_empty_change_set_is_rc2_and_not_a_clean_bill(
            self, tmp_path, capsys):
        cf = tmp_path / "changed.txt"
        cf.write_text("\n  \n", encoding="utf-8")
        rc = mod.main(["--repo", str(tmp_path), "--changed-file", str(cf)])
        assert rc == mod.RC_UNDETERMINED
        assert "[CANNOT CHECK]" in capsys.readouterr().err

    def test_a_missing_answers_file_and_an_empty_one_get_different_verdicts(
            self, tmp_path, capsys):
        """HARD RULE 9, both halves in one assertion pair.

        'I could not read it' is rc=2. 'I read it and it was empty' is rc=1. A
        gate that answered the same thing to both would be unable to tell a
        broken invocation from an unanswered PR, and this repository has been
        bitten by exactly that three times in one day.
        """
        repo = make_repo(tmp_path, base={}, head={DOC: "note\n"})
        rc_missing = mod.main(["--repo", str(repo), "--base", "HEAD~1",
                               "--head", "HEAD",
                               "--answers", str(repo / "absent.json")])
        assert rc_missing == mod.RC_UNDETERMINED
        assert "[CANNOT CHECK]" in capsys.readouterr().err
        rc_empty, _ = run(repo, {})
        assert rc_empty == mod.RC_FAIL
        assert rc_missing != rc_empty

    def test_a_bad_invocation_is_rc3_and_never_rc2(self, tmp_path, capsys):
        """argparse's own default for a usage error is 2, and 2 already means
        UNDETERMINED here. Leaving that in place would make 'you typed it wrong'
        indistinguishable from 'the evidence was not there to read'."""
        with pytest.raises(SystemExit) as exc:
            mod.main(["--repo", str(tmp_path)])
        assert exc.value.code == mod.RC_BAD_INVOCATION
        assert "[REFUSE]" in capsys.readouterr().err

    def test_rc2_is_the_verdict_when_an_arm_did_not_run(self, tmp_path, capsys):
        """A one-armed run reports UNDETERMINED, never N/A.

        Given only a list of paths there is no diff, so the content arm did not
        look for the surfaces it alone can see. Reporting those questions as
        N/A would be the gate stating an absence it never established.
        """
        cf = tmp_path / "changed.txt"
        cf.write_text(DOC + "\n", encoding="utf-8")
        ans = tmp_path / "a.json"
        ans.write_text(json.dumps({
            "schema": mod.ANSWERS_SCHEMA,
            "answers": [{"question": q, "evidence": [
                {"kind": "path", "ref": "changed.txt"}]} for q in (1, 2, 12)] +
                [{"question": 3, "evidence": [
                    {"kind": "artefact", "ref": "changed.txt",
                     "sha256": sha(cf)}]}],
        }), encoding="utf-8")
        out = tmp_path / "r.json"
        rc = mod.main(["--repo", str(tmp_path), "--changed-file", str(cf),
                       "--answers", str(ans), "--json", str(out)])
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["detector"]["arms"]["content"] == "NOT_RUN"
        assert report["summary"]["undetermined"] > 0
        assert applicability_of(report, 19) == "UNDETERMINED"
        assert status_of(report, 19) == "UNDETERMINED"
        # and the report says WHY, rather than implying the absence was checked
        assert "NOT LOOKED FOR" in report["detector"]["content_arm_note"]
        assert rc in (mod.RC_FAIL, mod.RC_UNDETERMINED)

    def test_a_finding_outranks_an_undetermined(self, tmp_path):
        """FAIL beats UNDETERMINED, the same precedence `_vacuous_exit` uses. A
        real finding is never silenced by something the run could not decide."""
        cf = tmp_path / "changed.txt"
        cf.write_text(DOC + "\n", encoding="utf-8")
        out = tmp_path / "r.json"
        rc = mod.main(["--repo", str(tmp_path), "--changed-file", str(cf),
                       "--json", str(out)])
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["summary"]["undetermined"] > 0
        assert rc == mod.RC_FAIL


# --------------------------------------------------------------------------
# The detector's own precision — the fix that made it usable.
# --------------------------------------------------------------------------
class TestMasking:
    def test_a_string_that_mentions_a_surface_does_not_create_one(
            self, tmp_path):
        """MUTATION TARGET. A regex table, a docstring or an assertion that
        names `shell=True` has not acquired a shell. Measured on this lane's own
        PR: without masking the content arm fired 44 times on its own rule
        table, which is how a gate gets ignored."""
        repo = make_repo(
            tmp_path, base={},
            head={UNWATCHED:
                  '"""A note that mentions shell=True in prose."""\n'
                  'PATTERN = "shell=True"\n'
                  'OTHER = "os.system("\n'},
        )
        _, report = run(repo, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        rules = {h["rule"] for h in report["detector"]["content_hits"]}
        assert "shell_true" not in rules
        assert "os_system" not in rules
        assert applicability_of(report, 19) == "NOT_APPLICABLE"
        assert report["detector"]["content_masking"][UNWATCHED] == "APPLIED"

    def test_masking_a_mention_does_not_mask_the_real_thing_on_the_same_file(
            self, tmp_path):
        """The paired half. A file may both DESCRIBE the surface and HAVE it;
        masking must remove only the description. Without this case, a test
        suite would pass against a detector that had simply been switched off
        for any file containing a string."""
        repo = make_repo(
            tmp_path, base={},
            head={UNWATCHED:
                  'import subprocess\n'
                  'PATTERN = "shell=True"\n\n\n'
                  'def go(c):\n'
                  '    subprocess.run(c, shell=True)\n'},
        )
        _, report = run(repo, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        hits = [h for h in report["detector"]["content_hits"]
                if h["rule"] == "shell_true"]
        assert len(hits) == 1, hits
        assert hits[0]["line"] == 6
        assert applicability_of(report, 19) == "APPLICABLE"

    def test_an_untokenizable_file_is_scanned_unmasked_and_says_so(
            self, tmp_path):
        """'I could not read it' must not look like 'I read it and it was
        clean'. A file that does not tokenize gets no masking, every match
        stands, and the report records that masking was NOT applied."""
        repo = make_repo(
            tmp_path, base={},
            head={UNWATCHED: 'def broken(:\n    x = "shell=True"\n'},
        )
        _, report = run(repo, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        assert report["detector"]["content_masking"][UNWATCHED] == \
            "NOT_APPLIED_UNTOKENIZABLE"
        rules = {h["rule"] for h in report["detector"]["content_hits"]}
        assert "shell_true" in rules

    def test_a_literal_argv_is_not_a_dynamic_one(self, tmp_path):
        """`subprocess.run(["git", ...])` is the safe form and this repository
        uses it everywhere. A rule that fired on it would put question 19 on
        every PR, and a question that is always on is a question nobody reads."""
        repo = make_repo(
            tmp_path, base={},
            head={UNWATCHED: 'import subprocess\n\n\n'
                             'def go():\n'
                             '    subprocess.run(["git", "status"])\n'},
        )
        _, report = run(repo, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        rules = {h["rule"] for h in report["detector"]["content_hits"]}
        assert "dynamic_argv" not in rules

    def test_a_config_field_name_is_a_vocabulary_not_a_surface(self, tmp_path):
        """A checklist that lists the word "pareto" has not acquired a Pareto
        frontier. This is the file-class rule; without it the catalogue file in
        this very lane put eight tokens on its own PR."""
        cfg = "vibe-ic-marketplace/plugins/vibe-ic/programs/some_data.json"
        repo = make_repo(tmp_path, base={},
                         head={cfg: json.dumps({"tokens": ["pareto",
                                                           "casebook"]})})
        _, report = run(repo, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        assert "pareto" not in report["detector"]["detected_tokens"]
        # but a capability a config genuinely grants still fires
        repo2 = make_repo(tmp_path / "b", base={},
                          head={cfg: json.dumps({"allowlist": ["rm"]})})
        _, r2 = run(repo2, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        assert "action_registry" in r2["detector"]["detected_tokens"]


# --------------------------------------------------------------------------
# The C.3 auto-fill emissions.
# --------------------------------------------------------------------------
class TestEmissions:
    def test_it_names_the_changed_flow_steps_not_merely_the_flow_file(
            self, tmp_path):
        """'the flow file changed' is a much weaker statement than 'step 37.5
        changed', and the checklist is about the latter."""
        flow = "vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml"
        repo = make_repo(
            tmp_path,
            base={flow: "steps:\n  - id: 12.0\n    gate: a\n"},
            head={flow: "steps:\n  - id: 12.0\n    gate: a\n"
                        "  - id: 37.5ic\n    gate: b\n"},
        )
        _, report = run(repo, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        assert report["flow_steps"]["status"] == "DETERMINED"
        assert "37.5ic" in report["flow_steps"]["steps"]
        assert "flow_step" in report["detector"]["detected_tokens"]

    def test_a_flow_change_without_a_git_range_says_not_determined(
            self, tmp_path):
        flow = "vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml"
        cf = tmp_path / "c.txt"
        cf.write_text(flow + "\n", encoding="utf-8")
        out = tmp_path / "r.json"
        mod.main(["--repo", str(tmp_path), "--changed-file", str(cf),
                  "--json", str(out)])
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["flow_steps"]["status"] == "NOT_DETERMINED"
        assert report["flow_steps"]["steps"] == []

    def test_a_gate_change_declares_all_four_required_fixtures(self, tmp_path):
        gate = ("vibe-ic-marketplace/plugins/vibe-ic/programs/"
                "widget_alignment_check.py")
        repo = make_repo(tmp_path, base={}, head={gate: "RC = 0\n"})
        _, report = run(repo, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        assert report["required_fixtures"]["required"] is True
        assert [f["fixture"] for f in report["required_fixtures"]["fixtures"]] \
            == ["positive", "negative", "vacuous", "mutation"]

    def test_a_non_gate_change_does_not_invent_a_fixture_requirement(
            self, tmp_path):
        repo = make_repo(tmp_path, base={}, head={DOC: "note\n"})
        _, report = run(repo, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        assert report["required_fixtures"]["required"] is False
        assert report["required_mutation_tests"]["required"] is False

    def test_a_gate_change_asks_for_the_mutation_test_by_name(self, tmp_path):
        gate = ("vibe-ic-marketplace/plugins/vibe-ic/programs/"
                "widget_alignment_check.py")
        repo = make_repo(
            tmp_path,
            base={"t/test_w.py": "def test_placeholder():\n    pass\n"},
            head={gate: "RC = 0\n",
                  "t/test_w.py": "def test_placeholder():\n    pass\n\n\n"
                                 "def test_widget_negative_turns_red():\n"
                                 "    pass\n"})
        answers = {"schema": mod.ANSWERS_SCHEMA, "answers": [
            {"question": 11, "evidence": [
                {"kind": "test",
                 "ref": "t/test_w.py::test_widget_negative_turns_red"}]}]}
        _, report = run(repo, answers)
        assert status_of(report, 11) == "SATISFIED"
        assert report["required_mutation_tests"]["tests"] == \
            ["t/test_w.py::test_widget_negative_turns_red"]

    def test_a_named_test_that_does_not_exist_is_not_evidence(self, tmp_path):
        """A test id is only evidence if the file defines it. Otherwise the
        strongest-looking answer in the document is a string."""
        gate = ("vibe-ic-marketplace/plugins/vibe-ic/programs/"
                "widget_alignment_check.py")
        repo = make_repo(tmp_path,
                         base={"t/test_w.py": "def test_other():\n    pass\n"},
                         head={gate: "RC = 0\n"})
        answers = {"schema": mod.ANSWERS_SCHEMA, "answers": [
            {"question": 11, "evidence": [
                {"kind": "test", "ref": "t/test_w.py::test_does_not_exist"}]}]}
        rc, report = run(repo, answers)
        assert rc == mod.RC_FAIL
        row = [r for r in report["questions"] if r["question"] == 11][0]
        assert row["evidence"][0]["status"] == "UNVERIFIED"

    def test_the_classified_change_set_separates_tests_from_programs(
            self, tmp_path):
        repo = make_repo(
            tmp_path, base={},
            head={"vibe-ic-marketplace/plugins/vibe-ic/programs/a_check.py":
                  "RC = 0\n",
                  "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
                  "test_a_check.py": "def test_x():\n    pass\n"})
        _, report = run(repo, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        changed = report["change_set"]["changed"]
        assert len(changed["programs"]) == 1
        assert len(changed["tests"]) == 1

    def test_the_report_carries_a_canonical_digest_of_itself(self, tmp_path):
        """`_ppa/canonical_json` is the only serializer, so this document can be
        re-derived and compared by a later reader."""
        from _ppa.canonical_json import digest_of
        repo = make_repo(tmp_path, base={}, head={DOC: "note\n"})
        _, report = run(repo, {"schema": mod.ANSWERS_SCHEMA, "answers": []})
        recomputed = digest_of({k: v for k, v in report.items()
                                if k != "digest"})
        assert report["digest"] == recomputed
        assert report["schema"] == mod.REPORT_SCHEMA
        assert report["catalogue"]["digest"].startswith("sha256:")


# --------------------------------------------------------------------------
# The exit-code contract itself.
# --------------------------------------------------------------------------
class TestExitCodes:
    def test_the_four_codes_are_the_frozen_ones(self):
        assert (mod.RC_PASS, mod.RC_FAIL, mod.RC_UNDETERMINED,
                mod.RC_BAD_INVOCATION) == (0, 1, 2, 3)

    def test_the_verdict_and_the_exit_code_come_from_the_same_object(self):
        """A gate that prints one verdict and exits with another is the drift
        `_vacuous_exit` was written to end."""
        for statuses, expected in (
                (["SATISFIED", "NOT_APPLICABLE"], (0, "PASS")),
                (["SATISFIED", "UNDETERMINED"], (2, "UNDETERMINED")),
                (["MISSING_EVIDENCE", "UNDETERMINED"], (1, "FAIL")),
                (["AUTHOR_OVERRIDE_REFUSED"], (1, "FAIL")),
        ):
            rows = [{"question": i, "status": s}
                    for i, s in enumerate(statuses, 1)]
            assert mod.verdict_of({"questions": rows}) == expected


# --------------------------------------------------------------------------
# A refusal has to be recordable, not only printable.
# --------------------------------------------------------------------------
class TestRefusalIsRecorded:
    def test_a_refusal_writes_a_report_that_says_it_refused(
            self, tmp_path, capsys):
        """'No report was written' cannot be told apart from a crash, and the
        two need different responses. A refusal writes its own document."""
        out = tmp_path / "r.json"
        rc = mod.main(["--repo", str(tmp_path),
                       "--changed-file", str(tmp_path / "nope.txt"),
                       "--json", str(out)])
        capsys.readouterr()
        assert rc == mod.RC_UNDETERMINED
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["verdict"] == "UNDETERMINED"
        assert doc["rc"] == 2
        assert doc["refusal"]["code"] == "CHANGE_SET_MISSING"
        assert doc["questions"] == []

    def test_a_refusal_document_is_never_mistakable_for_a_verdict(
            self, tmp_path, capsys):
        """It carries no question rows at all, so a consumer that counts
        satisfied questions counts zero rather than inheriting a stale set."""
        out = tmp_path / "r.json"
        mod.main(["--repo", str(tmp_path),
                  "--changed-file", str(tmp_path / "nope.txt"),
                  "--json", str(out)])
        capsys.readouterr()
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["schema"] == mod.REPORT_SCHEMA
        assert "summary" not in doc
        assert doc["digest"].startswith("sha256:")


class TestChangeSetChannels:
    def test_the_repository_change_set_env_var_is_honoured(
            self, tmp_path, monkeypatch, capsys):
        """`GATEKEEPER_CHANGED_PATHS` is the channel `tools/ci/_gate_dispatch.sh`
        already uses. Reading it means this gate needs no new plumbing to join
        the dispatcher."""
        cf = tmp_path / "changed.txt"
        cf.write_text(DOC + "\n", encoding="utf-8")
        out = tmp_path / "r.json"
        monkeypatch.setenv("GATEKEEPER_CHANGED_PATHS", str(cf))
        rc = mod.main(["--repo", str(tmp_path), "--json", str(out)])
        capsys.readouterr()
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["change_set"]["path_count"] == 1
        assert rc in (mod.RC_FAIL, mod.RC_UNDETERMINED)

    def test_an_env_var_naming_a_file_that_is_not_there_refuses(
            self, tmp_path, monkeypatch, capsys):
        """The fallback must not become a way to be checked by nothing."""
        monkeypatch.setenv("GATEKEEPER_CHANGED_PATHS", str(tmp_path / "gone.txt"))
        rc = mod.main(["--repo", str(tmp_path)])
        assert rc == mod.RC_UNDETERMINED
        assert "[CANNOT CHECK]" in capsys.readouterr().err

    def test_an_explicit_flag_beats_the_environment(
            self, tmp_path, monkeypatch, capsys):
        cf = tmp_path / "explicit.txt"
        cf.write_text(DOC + "\n", encoding="utf-8")
        monkeypatch.setenv("GATEKEEPER_CHANGED_PATHS", str(tmp_path / "gone.txt"))
        out = tmp_path / "r.json"
        mod.main(["--repo", str(tmp_path), "--changed-file", str(cf),
                  "--json", str(out)])
        capsys.readouterr()
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["change_set"]["path_count"] == 1
