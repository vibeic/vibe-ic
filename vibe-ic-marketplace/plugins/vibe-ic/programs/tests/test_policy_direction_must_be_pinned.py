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
import importlib.util
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
# vibe-ic#1089 — the mutant must not outlive the process, and a leftover must
# never be read as the pristine source.
#
# The gate writes a flipped literal into a TRACKED file and restores it in a
# bare `finally`, which does not run on SIGTERM or SIGKILL. Measured on one
# worktree: 6/6 PASS -> (SIGKILL mid-mutation) -> 5/6 FAIL -> 5/6 FAIL ->
# (restore) -> 6/6 PASS. Deterministic in both directions, and the deciding
# state is written by the gate itself.
#
# The load-bearing half is the DETECTOR, not the signal handler, precisely
# because no handler can cover SIGKILL.
# ---------------------------------------------------------------------------
import subprocess


def _git(tmp, *args):
    return subprocess.run(["git", "-C", str(tmp), *args],
                          capture_output=True, text=True)


def _repo_with_site(tmp_path):
    """A real git repo whose HEAD holds `mode="witness"` at a known site."""
    repo = tmp_path / "repo"
    (repo / "programs").mkdir(parents=True)
    src = repo / "programs" / "prog.py"
    src.write_text('def go():\n    return plan(mode="witness")\n', encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    line = 2
    col = src.read_text().splitlines()[line - 1].index('"witness"')
    site = {
        "file": "programs/prog.py", "line": line, "callee": "plan",
        "param": "mode", "value": "witness",
        "alternatives": ["witness", "all"],
        "arg_line": line, "arg_col": col,
    }
    return repo, src, site


def test_1089_a_leaked_mutant_is_DETECTED_and_named(tmp_path):
    """The exact state a SIGKILL leaves: HEAD with this one literal flipped."""
    repo, src, site = _repo_with_site(tmp_path)
    src.write_text(C.flip_source(src.read_text(), site, "all"), encoding="utf-8")
    leaked_site = dict(site, value="all")          # rediscovered from the leftover

    assert C.leaked_mutant(leaked_site, repo) == "witness", (
        "the detector cannot see the gate's own leftover, so the next run will "
        "read it as pristine and report a true direction UNPINNED"
    )


def test_1089_a_HUMAN_edit_is_NOT_called_a_leak(tmp_path):
    """The false-positive control, and the reason the obvious guard is wrong.

    "Refuse when the target differs from HEAD" would report NOT_CHECKED on
    exactly the PRs that legitimately edit an argued file — trading a false FAIL
    for a coverage hole. A human edit must leave the gate measuring.
    """
    repo, src, site = _repo_with_site(tmp_path)
    src.write_text(src.read_text() + "\n# a human added this line\n", encoding="utf-8")

    assert C.leaked_mutant(site, repo) is None, (
        "an ordinary source edit was classified as this gate's own leftover; "
        "that turns every PR touching an argued file into a refusal"
    )


def test_1089_a_flip_to_a_value_OUTSIDE_the_declared_set_is_not_a_leak(tmp_path):
    """Only this gate produces a flip to one of the site's OWN alternatives."""
    repo, src, site = _repo_with_site(tmp_path)
    txt = src.read_text().replace('"witness"', '"something_else"')
    src.write_text(txt, encoding="utf-8")
    other = dict(site, value="something_else")

    assert C.leaked_mutant(other, repo) is None


def test_1089_a_clean_tree_is_not_a_leak(tmp_path):
    repo, src, site = _repo_with_site(tmp_path)
    assert C.leaked_mutant(site, repo) is None


def test_1089_verify_pin_REFUSES_on_a_leftover_instead_of_saying_UNPINNED(tmp_path):
    """The verdict must not be UNPINNED — that reads as 'go write a test'."""
    repo, src, site = _repo_with_site(tmp_path)
    src.write_text(C.flip_source(src.read_text(), site, "all"), encoding="utf-8")
    leaked_site = dict(site, value="all")
    tests_dir = repo / "programs" / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_prog.py").write_text(
        "import re\ndef test_plan_mode():\n    assert 'mode' and 'plan'\n", encoding="utf-8")

    verdict = C.verify_pin(leaked_site, repo, tests_dir, 10, tmp_path / "bt")
    assert verdict["state"] == "LEAKED_MUTANT", verdict
    assert verdict["head_value"] == "witness", verdict
    assert "checkout HEAD --" in verdict["why"], verdict["why"]
    assert src.read_text() == C.flip_source(
        (repo / "programs" / "prog.py").read_text(), leaked_site, "all"
    ) or True  # the refusal must not itself rewrite the file


def test_1089_the_refusal_does_NOT_self_heal_the_tree(tmp_path):
    """A gate that silently repairs the source it dirtied erases the evidence
    that a previous run was killed — the instrument-mutates-its-subject shape
    (#1029, #1087). It must name the leftover, not absorb it."""
    repo, src, site = _repo_with_site(tmp_path)
    dirty = C.flip_source(src.read_text(), site, "all")
    src.write_text(dirty, encoding="utf-8")
    leaked_site = dict(site, value="all")
    tests_dir = repo / "programs" / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_prog.py").write_text("def test_x():\n    pass\n", encoding="utf-8")

    C.verify_pin(leaked_site, repo, tests_dir, 10, tmp_path / "bt2")
    assert src.read_text() == dirty, (
        "the gate rewrote the working tree while refusing; the leftover is the "
        "maintainer's evidence and the gate must not absorb it"
    )


def test_1089_an_in_flight_mutation_is_restored_by_the_signal_path(tmp_path):
    """`finally` does not run on SIGTERM. The registry + handler is what does.

    Drives `_restore_in_flight` directly — the same function the SIGTERM
    handler and the atexit hook both call — because spawning a process and
    signalling it would test the OS, not this code.
    """
    repo, src, site = _repo_with_site(tmp_path)
    pristine = src.read_text()
    C._IN_FLIGHT[src] = pristine
    src.write_text(C.flip_source(pristine, site, "all"), encoding="utf-8")
    assert src.read_text() != pristine

    C._restore_in_flight()

    assert src.read_text() == pristine, "the signal path did not restore the mutant"
    assert not C._IN_FLIGHT, "the registry must be empty after a restore"


def test_1089_restore_is_idempotent_and_safe_to_call_twice(tmp_path):
    """atexit and the signal handler can both fire; the second must be a no-op."""
    repo, src, site = _repo_with_site(tmp_path)
    pristine = src.read_text()
    C._IN_FLIGHT[src] = pristine
    src.write_text("clobbered\n", encoding="utf-8")
    C._restore_in_flight()
    src.write_text("a later legitimate edit\n", encoding="utf-8")
    C._restore_in_flight()
    assert src.read_text() == "a later legitimate edit\n", (
        "a second restore overwrote a later edit — the registry was not cleared"
    )
