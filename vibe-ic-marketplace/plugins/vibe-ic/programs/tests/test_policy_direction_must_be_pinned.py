#!/usr/bin/env python3
"""A direction argued in prose must die when it is flipped.

Two halves:

  * THE PIN (`test_auto_detect_...`) -- the one argued direction this gate found
    in `programs/`, asserted at its own call site. It is the fix; the rest of
    the file is the gate that finds the next one.
  * THE GATE'S OWN TESTS -- the predicate, its abstentions, and the
    over-corrections it must NOT make.

Fixtures are pure Python grammar with invented names, plus the three PUBLIC PDK
names the runner already ships (`sky130A`, `asap7`, `nangate45`). No vendor,
foundry, SKU, node or part number appears anywhere in this file.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
CHECK = PROGRAMS / "policy_direction_pin_check.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    spec.loader.exec_module(mod)
    return mod


C = _load("_pdpc_under_test", CHECK)


def test_isolated_worker_never_recovers_a_live_peer_journal(tmp_path):
    """Parallel children may inspect only their keyed crash record.

    ``recover_all_journals`` is correct for the locked parent and destructive
    for a child: it would restore another worker's live mutant underneath that
    worker's pytest process.  This is the exact race the parallel mode must not
    reintroduce.
    """
    own = tmp_path / "own" / "programs"
    peer = tmp_path / "peer" / "programs"
    (own / "tests").mkdir(parents=True)
    peer.mkdir(parents=True)
    target = peer / "subject.py"
    target.write_text("mutant\n", encoding="utf-8")
    journal = C.journal_for(peer)
    C._write_private_atomic(journal, json.dumps({
        "schema": 2, "file": str(target), "original": "original\n",
        "mutated_sha256": hashlib.sha256(b"mutant\n").hexdigest(),
    }))
    prior_cohort = os.environ.get(C._COHORT_ENV)
    try:
        rc = C.main([str(own), "--verify-pins", "--isolated-worker"])
        assert rc == 0
        assert os.environ.get(C._COHORT_ENV) == "1"
        assert target.read_text(encoding="utf-8") == "mutant\n"
        assert journal.is_file(), "the child consumed a live peer's journal"
    finally:
        journal.unlink(missing_ok=True)
        if prior_cohort is None:
            os.environ.pop(C._COHORT_ENV, None)
        else:
            os.environ[C._COHORT_ENV] = prior_cohort


# ---------------------------------------------------------------------------
# THE PIN -- the argued direction the sweep found in programs/
# ---------------------------------------------------------------------------
# `phase3_one_shot_runner._detect_pdk` ends its resolution chain with
#
#     # fallback (AUTO-detect only): sky130A in container
#     return _detect_pdk(project, override="sky130A")
#
# and the comment block above it argues, at length, that a fallback is
# legitimate for AUTO-detection and illegitimate for a name the operator did
# give. That argument is about WHETHER to fall back. WHICH PDK it falls back to
# was, until this test, decided by a word no test could see: flipping it to
# `nangate45` or `asap7` left 31 test files naming this program and this
# function entirely green -- including the one called
# `test_v1_4_62_vacuous_tb_and_pdk_fallback_guards.py`.
#
# The consequence is not cosmetic. That literal picks the liberty, the tech LEF,
# the cell LEF/GDS, the DRC deck, the site name, the metal prefix and the
# tapcell master for EVERY auto-detected Phase 3 run. A flip re-targets the
# whole back end.

def _detect_pdk_module():
    return _load("_pdpc_phase3", PROGRAMS / "phase3_one_shot_runner.py")


def test_auto_detect_fallback_resolves_to_sky130A_and_not_merely_to_some_pdk(tmp_path):
    """With nothing declared, auto-detect must land on sky130A specifically."""
    m = _detect_pdk_module()
    project = tmp_path / "empty_project"
    project.mkdir()

    cfg = m._detect_pdk(project)          # no override at all: the AUTO lane
    assert cfg is not None, "auto-detect must resolve a PDK, not SKIP"

    # Asserted on the OBSERVABLE configuration, not on the source text: the
    # identity AND two independent fields that no other PDK this runner knows
    # shares. Naming only `cfg.name` would still die under the flip, but it
    # would not say that the whole back-end target moves with it.
    assert cfg.name == "sky130A"
    assert cfg.site == m._detect_pdk(project, override="sky130A").site
    assert cfg.metal_prefix == m._detect_pdk(project, override="sky130A").metal_prefix
    assert "sky130A" in cfg.tech_lef and "sky130A" in cfg.drc_deck


def test_the_other_pdks_this_runner_knows_are_genuinely_different_targets(tmp_path):
    """The flip the gate performs has to be a real change, or the pin is empty.

    A pin that dies only because two configurations differ by their `name`
    string would be pinning a label. These are different back ends.
    """
    m = _detect_pdk_module()
    project = tmp_path / "empty_project"
    project.mkdir()
    sky = m._detect_pdk(project, override="sky130A")
    other = m._detect_pdk(project, override="nangate45")
    assert other is not None
    assert other.name != sky.name
    assert other.site != sky.site
    assert other.tech_lef != sky.tech_lef


# ---------------------------------------------------------------------------
# THE GATE: D1 / D2 / D3, on synthetic corpora
# ---------------------------------------------------------------------------

def _corpus(root: Path, files: dict) -> Path:
    (root / "tests").mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return root


ARGUED_CALLEE = '''
    _WAYS = ("keep_wider", "keep_narrower")

    def reconcile(records, *, on_tie: str = "keep_wider"):
        """Fold records.

        Parameters
        ----------
        on_tie :
            ``"keep_wider"`` (default) keeps the larger record, ``"keep_narrower"``
            the smaller. Which way to break the tie is domain-dependent.
        """
        if on_tie not in _WAYS:
            raise ValueError("bad on_tie")
        return records[-1] if on_tie == "keep_wider" else records[0]
'''


def test_gate_finds_a_defaulted_closed_set_literal_whose_docstring_argues(tmp_path):
    root = _corpus(tmp_path / "c1", {
        "helper.py": ARGUED_CALLEE,
        "user.py": '''
            from helper import reconcile

            def go(records):
                return reconcile(records, on_tie="keep_wider")
        ''',
    })
    rep = C.build_report(root)
    argued = rep["argued"]
    assert [(s["file"], s["param"], s["value"]) for s in argued] == \
        [("user.py", "on_tie", "keep_wider")]
    assert argued[0]["argued_by_doc"] is True


def test_gate_ignores_a_required_parameter_however_closed_its_set(tmp_path):
    """D1. `report_path(p, "final_summary.md")` names WHICH report it wants.

    The call site had no choice but to speak, so speaking is not a decision.
    This is the clause that keeps the gate off ordinary lookup arguments, and
    it is the difference between a finding and a wall of noise.
    """
    root = _corpus(tmp_path / "c2", {
        "helper.py": '''
            ROOT_FILES = ("final_summary.md", "chip_specific_summary.md")

            def report_path(project, filename):
                """Route a report.

                `final_summary.md` and `chip_specific_summary.md` are the two
                whitelisted root-level files.
                """
                if filename in ROOT_FILES:
                    return project / filename
                return project / "audit" / filename
        ''',
        "user.py": '''
            from helper import report_path

            def go(p):
                return report_path(p, "final_summary.md")
        ''',
    })
    rep = C.build_report(root)
    assert rep["argued"] == []
    assert rep["policy_params_defined"] == 0


def test_gate_ignores_a_defaulted_choice_nobody_wrote_an_argument_for(tmp_path):
    """D3. No prose names the road not taken, so no decision is on record.

    This is the gate's honest hole, asserted rather than hidden: an author who
    deletes the comment deletes the finding.
    """
    root = _corpus(tmp_path / "c3", {
        "helper.py": '''
            _WAYS = ("keep_wider", "keep_narrower")

            def reconcile(records, *, on_tie: str = "keep_wider"):
                """Fold records."""
                if on_tie not in _WAYS:
                    raise ValueError("bad on_tie")
                return records[-1] if on_tie == "keep_wider" else records[0]
        ''',
        "user.py": '''
            from helper import reconcile

            def go(records):
                return reconcile(records, on_tie="keep_wider")
        ''',
    })
    rep = C.build_report(root)
    assert rep["literal_sites_production"] == 1
    assert rep["argued"] == []


def test_a_comment_beside_the_call_can_carry_the_argument_instead(tmp_path):
    root = _corpus(tmp_path / "c4", {
        "helper.py": '''
            _WAYS = ("keep_wider", "keep_narrower")

            def reconcile(records, *, on_tie: str = "keep_wider"):
                """Fold records."""
                if on_tie not in _WAYS:
                    raise ValueError("bad on_tie")
                return records[-1] if on_tie == "keep_wider" else records[0]
        ''',
        "user.py": '''
            from helper import reconcile

            def go(records):
                # on_tie stays wide here and NOT keep_narrower: this consumer
                # blocks, and an under-read here loses a real finding.
                return reconcile(records, on_tie="keep_wider")
        ''',
    })
    rep = C.build_report(root)
    assert len(rep["argued"]) == 1
    assert rep["argued"][0]["argued_by_comment"] is True


def test_an_argument_made_in_a_different_function_does_not_travel(tmp_path):
    """A comment 400 lines away must not excuse -- or accuse -- a call site."""
    root = _corpus(tmp_path / "c5", {
        "helper.py": '''
            _WAYS = ("keep_wider", "keep_narrower")

            def reconcile(records, *, on_tie: str = "keep_wider"):
                """Fold records."""
                if on_tie not in _WAYS:
                    raise ValueError("bad on_tie")
                return records[-1] if on_tie == "keep_wider" else records[0]
        ''',
        "user.py": '''
            from helper import reconcile

            def elsewhere():
                # on_tie could be keep_narrower for a blocking consumer.
                return None

            def go(records):
                return reconcile(records, on_tie="keep_wider")
        ''',
    })
    rep = C.build_report(root)
    assert rep["argued"] == []


def test_a_literal_outside_the_declared_set_is_not_a_direction(tmp_path):
    """D2. The callee must state that these values are alternatives."""
    root = _corpus(tmp_path / "c6", {
        "helper.py": '''
            def label(text, *, style: str = "plain"):
                """Render.

                style :
                    ``"plain"`` or ``"loud"``.
                """
                if style == "loud":
                    return text.upper()
                if style == "plain":
                    return text
                return text
        ''',
        "user.py": '''
            from helper import label

            def go(t):
                return label(t, style="whisper")
        ''',
    })
    rep = C.build_report(root)
    assert rep["literal_sites_production"] == 0


def test_call_sites_inside_tests_are_counted_separately_not_demanded(tmp_path):
    """A test passing a literal IS the test; demanding it pin itself is noise."""
    root = _corpus(tmp_path / "c7", {
        "helper.py": ARGUED_CALLEE,
        "tests/test_x.py": '''
            from helper import reconcile

            def test_both_ways():
                assert reconcile([1, 2], on_tie="keep_wider") == 2
                assert reconcile([1, 2], on_tie="keep_narrower") == 1
        ''',
    })
    rep = C.build_report(root)
    assert rep["literal_sites_production"] == 0
    assert rep["literal_sites_total"] == 2
    assert rep["argued"] == []


# ---------------------------------------------------------------------------
# THE GATE: pin verification, by execution
# ---------------------------------------------------------------------------

PINNABLE = {
    "helper.py": ARGUED_CALLEE,
    "user.py": '''
        from helper import reconcile

        def go(records):
            return reconcile(records, on_tie="keep_wider")
    ''',
}


def _verify_one(root: Path, tmp_path: Path, max_files: int = 40):
    rep = C.build_report(root)
    assert len(rep["argued"]) == 1, rep["argued"]
    site = rep["argued"][0]
    bt = tmp_path / "bt"
    bt.mkdir(parents=True, exist_ok=True)
    return site, C.verify_pin(site, root, root / "tests", max_files, bt,
                              extra=["-p", "no:cacheprovider"])


def test_a_test_that_only_exercises_the_helper_does_not_pin_the_call_site(tmp_path):
    """THE FINDING, reproduced in miniature.

    The helper is asserted correct under BOTH directions -- a real property
    test, and the more thorough it gets the greener it stays under the flip.
    Nothing asserts which direction `go` chooses.
    """
    root = _corpus(tmp_path / "p1", dict(PINNABLE, **{
        "tests/test_user.py": '''
            import sys
            sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
            from helper import reconcile
            import user

            def test_reconcile_on_tie_behaves_under_both_policies():
                assert reconcile([1, 22], on_tie="keep_wider") == 22
                assert reconcile([1, 22], on_tie="keep_narrower") == 1

            def test_go_returns_one_of_the_records():
                assert user.go([1, 22]) in (1, 22)
        ''',
    }))
    site, verdict = _verify_one(root, tmp_path)
    assert verdict["state"] == "UNPINNED", verdict
    assert verdict["survivors"] == ["keep_narrower"]


def test_a_test_at_the_call_site_pins_it(tmp_path):
    root = _corpus(tmp_path / "p2", dict(PINNABLE, **{
        "tests/test_user.py": '''
            import sys
            sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
            from helper import reconcile
            import user

            def test_go_keeps_the_wider_record():
                assert user.go([1, 22]) == 22
        ''',
    }))
    site, verdict = _verify_one(root, tmp_path)
    assert verdict["state"] == "PINNED", verdict
    assert [k["flipped_to"] for k in verdict["killed_by"]] == ["keep_narrower"]
    assert verdict["baseline_rc"] == 0


def test_a_test_that_merely_mentions_the_value_does_not_pin_it(tmp_path):
    """The over-correction a static gate would make.

    "There is a test naming `keep_wider` for this program" is satisfied by a
    test that asserts nothing about it. Verification is by execution for
    exactly this reason.
    """
    root = _corpus(tmp_path / "p3", dict(PINNABLE, **{
        "tests/test_user.py": '''
            """Exercises user.go and its on_tie direction."""
            import sys
            sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
            import user

            ON_TIE_UNDER_TEST = "keep_wider"

            def test_go_runs():
                assert user.go([1, 22]) is not None
        ''',
    }))
    site, verdict = _verify_one(root, tmp_path)
    assert verdict["candidate_tests"], "the test WAS selected -- and still did not pin"
    assert verdict["state"] == "UNPINNED", verdict


def test_no_covering_test_at_all_is_unpinned_not_pinned(tmp_path):
    root = _corpus(tmp_path / "p4", dict(PINNABLE))
    site, verdict = _verify_one(root, tmp_path)
    assert verdict["state"] == "UNPINNED"
    assert verdict["candidate_tests"] == []


def test_an_already_red_test_suite_does_not_count_as_a_pin(tmp_path):
    """THE GATE'S OWN FALSE-CLEAN, closed.

    A red candidate test kills every mutant, including one nobody wrote a pin
    for. Without the baseline check this gate would hand out the same
    unearned green it was written to end.
    """
    root = _corpus(tmp_path / "p5", dict(PINNABLE, **{
        "tests/test_user.py": '''
            """Exercises user.go and its on_tie direction."""
            import sys
            sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
            import user

            def test_something_unrelated_and_broken():
                assert user.go([1, 22]) == 999
        ''',
    }))
    site, verdict = _verify_one(root, tmp_path)
    assert verdict["state"] == "ABSTAIN", verdict
    assert "RED before any flip" in verdict["why"]


def test_too_many_candidates_abstains_rather_than_guessing(tmp_path):
    root = _corpus(tmp_path / "p6", dict(PINNABLE, **{
        f"tests/test_user_{i}.py": '''
            """Exercises user.go and its on_tie direction."""
            import sys
            sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
            import user

            def test_go_runs():
                assert user.go([1, 22]) == 22
        ''' for i in range(3)
    }))
    site, verdict = _verify_one(root, tmp_path, max_files=2)
    assert verdict["state"] == "ABSTAIN"
    assert "--max-test-files" in verdict["why"]


def test_an_abstention_is_not_a_pass(tmp_path):
    """rc=2, not rc=0. A gate that goes green by declining to look is the
    shape this gate was written against, and that includes this gate."""
    root = _corpus(tmp_path / "p7", dict(PINNABLE, **{
        f"tests/test_user_{i}.py": '''
            """Exercises user.go and its on_tie direction."""
            import sys
            sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
            import user

            def test_go_runs():
                assert user.go([1, 22]) == 22
        ''' for i in range(3)
    }))
    rc = C.main([str(root), "--verify-pins", "--max-test-files", "2",
                 "--basetemp", str(tmp_path / "bt7")])
    assert rc == C.RC_UNDETERMINED


# ---------------------------------------------------------------------------
# THE REVERSE CASES -- over-corrections that must still pass
# ---------------------------------------------------------------------------

def test_the_flip_rewrites_exactly_one_literal_and_not_its_twin(tmp_path):
    """Over-correction: a textual substitution that also hits the argument's
    own name, a neighbouring string, or the callee's default."""
    src = ('x = reconcile(rs, tag="keep_wider", on_tie="keep_wider")  '
           '# keep_wider stays in this comment\n')
    site = {"arg_line": 1, "arg_col": src.index('"keep_wider"', src.index("on_tie")),
            "value": "keep_wider"}
    out = C.flip_source(src, site, "keep_narrower")
    assert out == ('x = reconcile(rs, tag="keep_wider", on_tie="keep_narrower")  '
                   '# keep_wider stays in this comment\n')


def test_the_flip_refuses_a_column_that_is_not_the_recorded_literal(tmp_path):
    src = 'x = reconcile(rs, on_tie="keep_wider")\n'
    with pytest.raises(ValueError):
        C.flip_source(src, {"arg_line": 1, "arg_col": 4, "value": "keep_wider"}, "keep_narrower")


def test_baseline_rechecks_only_what_actually_died(tmp_path):
    """The kill has to be traced to a file that WAS green, not to the fact
    that something somewhere in the selection went red."""
    out = ("....F...\n"
           "=========================== short test summary info ============================\n"
           "FAILED programs/tests/test_a.py::test_one - AssertionError\n"
           "ERROR programs/tests/test_b.py\n"
           "1 failed, 7 passed\n")
    assert C.failing_files(out) == ["programs/tests/test_a.py",
                                    "programs/tests/test_b.py"]
    assert C.failing_files("8 passed in 1.00s") == []


def test_selection_under_reads_toward_unpinned_never_toward_pinned(tmp_path):
    """The direction of the gate's own error, pinned.

    `select_tests` is textual and therefore a LOWER bound on coverage. A
    missed test can only leave a site looking UNPINNED. There is no path by
    which missing a test turns an unpinned site green -- and this asserts it
    on the real function rather than in a comment.
    """
    root = _corpus(tmp_path / "r1", dict(PINNABLE, **{
        "tests/test_user.py": '''
            """Exercises user.go and its on_tie direction."""
            import sys
            sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
            import user

            def test_go_keeps_the_wider_record():
                assert user.go([1, 22]) == 22
        ''',
        # Names neither the parameter nor the callee, so selection misses it.
        "tests/test_unrelated_but_covering.py": '''
            import sys
            sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
            import user

            def test_wider_wins():
                assert user.go([1, 22]) == 22
        ''',
    }))
    rep = C.build_report(root)
    site = rep["argued"][0]
    chosen = [p.name for p in C.select_tests(site, root / "tests")]
    assert "test_user.py" in chosen
    assert "test_unrelated_but_covering.py" not in chosen
    # And the verdict computed from the SMALLER selection is still PINNED,
    # never the reverse: dropping a test can lose a kill, not invent one.
    bt = tmp_path / "btr1"; bt.mkdir()
    v = C.verify_pin(site, root, root / "tests", 40, bt, extra=["-p", "no:cacheprovider"])
    assert v["state"] == "PINNED"


def test_selection_prioritises_the_densest_call_site_evidence(tmp_path):
    """Ordering buys runtime only; this pins the general ranking, not a name."""
    root = _corpus(tmp_path / "rank", dict(PINNABLE, **{
        "tests/test_sparse.py": '''
            # user reconcile on_tie keep_wider
        ''',
        "tests/test_dense.py": '''
            # user reconcile on_tie keep_wider
            # user reconcile on_tie keep_wider
        ''',
    }))
    site = C.build_report(root)["argued"][0]
    assert [p.name for p in C.select_tests(site, root / "tests")] == [
        "test_dense.py", "test_sparse.py"]


def test_focused_nodes_require_both_the_decision_and_authored_value(tmp_path):
    candidate = tmp_path / "test_focus.py"
    candidate.write_text(textwrap.dedent('''
        def test_exact_pin():
            assert merge_records([], on_conflict="richer") == "richer"

        def test_names_only_the_helper():
            assert merge_records([])

        class TestNested:
            def test_nested_pin(self):
                assert on_conflict == "richer"
    '''), encoding="utf-8")
    site = {"callee": "merge_records", "param": "on_conflict",
            "value": "richer"}
    assert [node.rsplit("::", 2)[-1]
            for node in C.focused_test_nodes(site, candidate)] == [
                "test_exact_pin", "test_nested_pin"]


def test_a_focused_node_kill_avoids_the_same_whole_file(tmp_path,
                                                        monkeypatch):
    root, tests, site = _pin_fixture(tmp_path, red_first=False)
    pin_file = tests / "test_b_pins_the_site.py"
    focused_body = pin_file.read_text(encoding="utf-8").replace(
        'def test_the_call_site_hands_over_on_conflict_richer():',
        'def test_helper_accepts_the_other_on_conflict_richer_mode():\n'
        '    # merge_records receives on_conflict="richer" explicitly\n'
        '    assert merge_records([], on_conflict="richer") == "richer"\n\n'
        'def test_the_call_site_hands_over_on_conflict_richer():')
    pin_file.write_text(focused_body.replace(
        'assert go([]) == "richer"',
        '# merge_records receives on_conflict="richer" here\n'
        '    assert go([]) == "richer"'), encoding="utf-8")
    real = C.run_pytest
    calls = []

    def traced(paths, *args, **kwargs):
        calls.append([str(path) for path in paths])
        return real(paths, *args, **kwargs)

    monkeypatch.setattr(C, "run_pytest", traced)
    out = C.verify_pin(site, root, tests, 40, tmp_path / "bt")
    pin_calls = [call for call in calls
                 if any(str(pin_file) in item for item in call)]
    helper = str(pin_file) \
        + "::test_helper_accepts_the_other_on_conflict_richer_mode"
    pin = str(pin_file) \
        + "::test_the_call_site_hands_over_on_conflict_richer"
    assert out["state"] == "PINNED", out
    assert pin_calls == [[helper], [pin], [pin]], calls
    assert [str(pin_file)] not in calls


def test_a_boolean_flag_is_out_of_scope_by_declaration(tmp_path):
    """The over-correction that buries the finding.

    `strict=True` is a two-valued decision by any honest reading, and demanding
    a pin for every defaulted boolean keyword in this corpus would produce a
    wall of noise nobody reads. Named string alternatives are the shape where
    somebody bothered to name the directions. Out of scope, and asserted so
    that widening it is a deliberate edit rather than a drift.
    """
    root = _corpus(tmp_path / "r2", {
        "helper.py": '''
            def audit(rows, *, strict: bool = False):
                """Audit.

                strict :
                    ``True`` refuses on a soft finding, ``False`` reports it.
                """
                return [r for r in rows if not strict or r]
        ''',
        "user.py": '''
            from helper import audit

            def go(rows):
                # strict stays False here and not True: a refusal would stop a
                # clean run.
                return audit(rows, strict=False)
        ''',
    })
    rep = C.build_report(root)
    assert rep["argued"] == []


def test_include_required_widens_the_population_and_the_default_does_not(tmp_path):
    """D1's cost, made inspectable rather than argued about in a comment.

    The same corpus, both ways: `report_path(p, "final_summary.md")` is a
    required parameter and is silent by default. `--include-required` shows it,
    because a clause that removes 48 of 50 sites on the real corpus should be
    something a reviewer can look at.
    """
    root = _corpus(tmp_path / "r4", {
        "helper.py": '''
            ROOT_FILES = ("final_summary.md", "chip_specific_summary.md")

            def report_path(project, filename):
                """Route a report.

                filename :
                    `final_summary.md` and `chip_specific_summary.md` are the
                    two whitelisted root-level files.
                """
                if filename in ROOT_FILES:
                    return project / filename
                return project / "audit" / filename
        ''',
        "user.py": '''
            from helper import report_path

            def go(p):
                return report_path(p, "final_summary.md")
        ''',
    })
    assert C.build_report(root)["argued_sites"] == 0
    wide = C.build_report(root, require_default=False)
    assert wide["argued_sites"] == 1
    assert wide["argued"][0]["param"] == "filename"


def test_the_gate_reports_its_own_denominator(tmp_path):
    """D3 selects from a population, and the population is the honest upper
    bound on what the gate could ever have looked at. A gate that printed only
    its findings would hide how much it declined to consider."""
    root = _corpus(tmp_path / "r3", {
        "helper.py": ARGUED_CALLEE,
        "user.py": '''
            from helper import reconcile

            def argued(records):
                return reconcile(records, on_tie="keep_wider")
        ''',
        "quiet.py": '''
            from helper import reconcile

            def unargued(records):
                return reconcile(records, on_tie="keep_narrower")
        ''',
    })
    rep = C.build_report(root)
    assert rep["policy_params_defined"] == 1
    assert rep["literal_sites_production"] == 2
    assert rep["argued_sites"] == 2   # both are argued: the DOC carries it


def test_param_doc_entry_does_not_borrow_a_neighbouring_parameters_prose(tmp_path):
    doc = textwrap.dedent('''
        Fold.

        Parameters
        ----------
        content :
            ``richer`` and ``sparser`` are discussed here for another reason.
        on_tie :
            keeps something.
        ''')
    entry = C.param_doc_entry(doc, "on_tie")
    assert "keeps something" in entry
    assert "richer" not in entry


# ---------------------------------------------------------------------------
# THE CORPUS SWEEP -- and it has to fire
# ---------------------------------------------------------------------------

def test_the_sweep_actually_runs_over_the_real_corpus():
    rep = C.build_report(PROGRAMS)
    assert rep["files_swept"] > 3000, rep["files_swept"]
    assert rep["policy_params_defined"] >= 1
    assert rep["argued_sites"] >= 1, (
        "the sweep found nothing at all -- either the corpus changed or the "
        "predicate stopped selecting; a gate whose population is empty is a "
        "gate that cannot fire")


def test_the_real_argued_site_is_still_the_pdk_fallback():
    """Names the SITE this PR pinned, so that losing it is loud rather than
    silent. If a future change removes it, this fails and says so.

    Deliberately does NOT assert the VALUE. Asserting it here would pin the
    fallback with a claim about the gate's own inventory -- a source-text
    assertion dressed as a behavioural one -- and the gate would then report
    the site PINNED on the strength of a test that never ran the runner. The
    pin lives in `test_auto_detect_fallback_resolves_to_sky130A_...`, which
    calls `_detect_pdk` and reads what comes back.
    """
    rep = C.build_report(PROGRAMS)
    found = {(s["file"], s["param"]) for s in rep["argued"]}
    assert ("phase3_one_shot_runner.py", "override") in found, sorted(found)


def test_cli_inventory_mode_runs_and_exits_zero(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(CHECK), str(PROGRAMS), "--json", str(tmp_path / "r.json")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert proc.returncode == 0, proc.stdout
    assert "ARGUED" in proc.stdout


def test_the_checker_is_agnostic_of_chip_pdk_and_vendor():
    """No design, PDK, vendor, process or part literal in the gate's logic.

    The three public PDK names appear in this corpus's DATA, never in the
    gate; a gate that named one would stop being reusable the moment the
    corpus changed.
    """
    src = CHECK.read_text(encoding="utf-8")
    tree = ast.parse(src)
    literals = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for banned in ("sky130A", "sky130", "asap7", "nangate45", "gf180"):
        assert not any(banned.lower() in lit.lower() for lit in literals), banned


# ---------------------------------------------------------------------------
# THE VERDICT MUST NOT DEPEND ON WHICH FAILURE CAME FIRST
#
# `run_pytest` passed `-x`, so the mutant run stopped at the first failing
# file and `failing_files()` could name only that one. Which file that is
# depends on collection order across the candidate selection, not on the call
# site — so on any tree carrying unrelated red (i.e. every tree this gate runs
# on during a repair) a site whose pin was intact could report ABSTAIN.
#
# MEASURED on origin/main @ 3febf537: `matrix_mutation_ledger.py:2380` reports
# PINNED, killed by `tests/test_matrix_mutation_ledger.py`, which sorts SECOND
# in its three-file selection. Appending one failing test to the file that
# sorts FIRST — touching neither the call site nor the pinning test — flipped
# the whole gate to `0/0 (abstained 1 of 1)`.
#
# These two tests are the fixture form of that measurement, so the property
# survives a rename of the corpus site that demonstrated it.
# ---------------------------------------------------------------------------
def _pin_fixture(tmp_path, red_first: bool):
    """A corpus with a real pin, and optionally an unrelated red test that
    sorts BEFORE the file carrying it."""
    root = tmp_path / "programs"
    tests = root / "tests"
    tests.mkdir(parents=True)
    # the callee: a closed set of two alternatives, with a default
    (root / "callee_mod.py").write_text(textwrap.dedent('''
        MODES = ("richer", "sparser")
        def merge_records(data, on_conflict="richer"):
            assert on_conflict in MODES
            return on_conflict
    '''), encoding="utf-8")
    # the call site: writes the default back, which is the recorded decision
    (root / "site_mod.py").write_text(textwrap.dedent('''
        from callee_mod import merge_records
        def go(data):
            return merge_records(data, on_conflict="richer")
    '''), encoding="utf-8")
    site = {
        "file": "site_mod.py", "arg_line": 4, "arg_col": 42,
        "callee": "merge_records", "param": "on_conflict",
        "value": "richer", "alternatives": ["richer", "sparser"],
    }
    line = (root / "site_mod.py").read_text().splitlines(keepends=True)[3]
    site["arg_col"] = line.index('"richer"')

    # sorts SECOND under select_tests (it does not name the VALUE, so it lands
    # in bucket 1 alongside the other; `a_...` vs `b_...` then decides)
    (tests / "test_b_pins_the_site.py").write_text(textwrap.dedent('''
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        from site_mod import go
        from callee_mod import merge_records          # names the callee
        def test_the_call_site_hands_over_on_conflict_richer():
            assert go([]) == "richer"
    '''), encoding="utf-8")
    # names site_mod (so select_tests picks it up) AND the value "richer" (so
    # it lands in the same primary sort bucket as the pinning file, where the
    # filename then puts it FIRST — which is the whole point of the fixture)
    body = '''
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        import site_mod                               # names the site module
        from callee_mod import merge_records          # names the callee
        def test_unrelated_to_the_call_site():
            """Nothing here says which way site_mod passes on_conflict="richer"."""
            assert %s
    ''' % ("False, 'stands in for one of main\\'s failures'" if red_first else "True")
    (tests / "test_a_unrelated.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return root, tests, site


def test_a_kill_in_a_GREEN_file_is_believed_even_when_another_file_is_red(tmp_path):
    """The regression. One unrelated red file must not abstain a live pin."""
    root, tests, site = _pin_fixture(tmp_path, red_first=True)
    out = C.verify_pin(site, root, tests, 40, tmp_path / "bt")
    assert out["state"] == "PINNED", out
    assert any("test_b_pins_the_site.py" in f for f in out.get("kills_believed", [])), out
    assert any("test_a_unrelated.py" in f for f in out.get("red_at_baseline", [])), out


def test_a_kill_ONLY_in_an_already_red_file_still_abstains(tmp_path):
    """The paired direction, and the reason the baseline check exists at all.

    A red test kills every mutant, including one nobody wrote a pin for.
    Crediting that would hand out exactly the false clean bill of health this
    gate exists to end — so when the ONLY file that died was already red, the
    gate must still refuse to decide.
    """
    root, tests, site = _pin_fixture(tmp_path, red_first=True)
    # remove the genuine pin, leaving only the unrelated red file
    (tests / "test_b_pins_the_site.py").write_text(textwrap.dedent('''
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        from callee_mod import merge_records          # names the callee
        def test_says_nothing_about_the_call_site():
            assert merge_records([], on_conflict="sparser") == "sparser"
    '''), encoding="utf-8")
    out = C.verify_pin(site, root, tests, 40, tmp_path / "bt")
    assert out["state"] == "ABSTAIN", out
    assert "already RED before any flip" in out["why"], out


def test_cross_file_only_pin_is_kept_by_the_aggregate_fallback(tmp_path):
    """The fast per-file lane must not erase shared-session semantics."""
    root, tests, site = _pin_fixture(tmp_path, red_first=False)
    (tests / "test_a_unrelated.py").write_text(textwrap.dedent('''
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        import site_mod
        from callee_mod import merge_records
        # Names the authored value so this seed sorts before the pin in both
        # the per-file lane and the aggregate fallback: on_conflict="richer".
        def test_seed_only():
            site_mod._aggregate_seen = True
            assert True
    '''), encoding="utf-8")
    (tests / "test_b_pins_the_site.py").write_text(textwrap.dedent('''
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        import site_mod
        from site_mod import go
        from callee_mod import merge_records
        def test_pin_only_after_the_other_file_ran():
            if getattr(site_mod, "_aggregate_seen", False):
                assert go([]) == "richer"
    '''), encoding="utf-8")
    out = C.verify_pin(site, root, tests, 40, tmp_path / "bt")
    assert out["state"] == "PINNED", out
    assert any("test_b_pins_the_site.py" in f
               for f in out.get("kills_believed", [])), out


def test_nonzero_process_without_a_failed_testcase_abstains(tmp_path, monkeypatch):
    """A session hook/process refusal is not evidence that the mutant died."""
    root = _corpus(tmp_path / "session", dict(PINNABLE, **{
        "tests/test_user.py": '''
            # user reconcile on_tie keep_wider
            def test_body_was_green():
                assert True
        ''',
    }))
    site = C.build_report(root)["argued"][0]
    monkeypatch.setattr(
        C, "run_pytest",
        lambda *a, **k: (1, "all testcase bodies passed; session hook refused\n"))
    out = C.verify_pin(site, root, root / "tests", 40, tmp_path / "bt")
    assert out["state"] == "ABSTAIN", out
    assert out["kills_believed"] == [], out
    assert "process failure" in out["why"], out


def test_the_mutant_run_is_exhaustive_and_not_stopped_at_the_first_failure(tmp_path):
    """A behavioural check, not a ban on the flag.

    Asserting `"-x" not in cmd` would be a ban: it forbids one spelling and
    says nothing about the property. This drives the real runner over two
    failing files and asserts BOTH are reported — which is false for `-x`,
    for `--exitfirst`, for `--maxfail=1`, and for any future way of writing
    the same mistake.
    """
    d = tmp_path / "t"
    d.mkdir()
    for name in ("test_one.py", "test_two.py"):
        (d / name).write_text("def test_dies():\n    assert False\n", encoding="utf-8")
    rc, out = C.run_pytest([d / "test_one.py", d / "test_two.py"], tmp_path,
                           tmp_path / "bt")
    assert rc != 0, out
    named = C.failing_files(out)
    assert len(named) == 2, (named, out)
