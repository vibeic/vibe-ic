"""`sdc_validator_check` must speak the repo's THREE-value exit contract, and
must not point a design author at an oracle while doing it.

THE THREE DEFECTS
-----------------
1. THE SKIP EXITED 0.  `flow_compliance_check.py` states the contract in its
   own source: rc 0 PASS, rc 1 FAIL, rc 2 VACUOUS_PASS (the "I ran but the
   input I audit does not exist" tier, promoted with the `__VACUOUS_HINT__`
   sentinel). `[SKIP] no .sdc files` stopped at rc 0, so a run that opened no
   file was recorded as an ordinary PASS: ABSENT and READ-AND-CLEAN were
   indistinguishable at the exit-code layer, which is the same
   indistinguishability the misdirection fix was written to remove, one layer
   down. The SKIP also disclosed no denominator, while the PASS line has always
   disclosed one ("N SDC file(s) OK").

2. A POSITIONAL THAT DOES NOT EXIST EXITED 0.  Two search roots were resolved
   under a path that is not there, zero files were opened, and a certificate
   was issued. A guard test asserted exactly this (`rc == 0`) and so
   regression-locked it; it is inverted in
   `test_sdc_search_root_misdirection.py`.

3. §4.05 — THE DIAGNOSTIC NAMED THE ORACLE.  The stray scan pruned only
   `.git/.hg/.svn/__pycache__/.venv/node_modules`, so a project whose only
   constraint file is a staged upstream `.../reference_flow/pre_syn/*.sdc`
   FAILED with a message that NAMED that file — telling the author which
   golden artifact to go and copy. Reproduced on the TRACKED corpus, not on a
   fixture: 3 of the 6 positionals from which the scan can reach the corpus's
   only off-limits `.sdc` enumerated one; after the fix, 0 of 6.

WHAT IS ASSERTED HERE
---------------------
Behaviour, by DRIVING the code — every test either invokes the program as a
subprocess or calls the pure `evaluate()`. None of them asserts on this
program's source text: a source-text assertion passes while the code it names
raises at runtime, which is how a test can certify a function it never called.
The one assertion on a literal is `NOT CHECKED` / the diagnostic name, because
being able to tell the tiers apart WITHOUT reading the source is the
requirement.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent
for _p in (str(_PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import flow_compliance_check as _fcc                      # noqa: E402
import sdc_validator_check as _svc                        # noqa: E402
import _reference_flow_boundary as _rfb                   # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = _PROGRAMS / "sdc_validator_check.py"

_GOOD_SDC = """\
create_clock -name clk -period 20 [get_ports clk]
set_input_delay  -clock clk 2 [get_ports din]
set_output_delay -clock clk 2 [get_ports dout]
"""


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True)


def _write(path: Path, text: str = _GOOD_SDC) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _empty_project(tmp_path: Path, name: str = "proj") -> Path:
    p = tmp_path / name
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── 1. the exit-code contract ────────────────────────────────────────────────

def test_the_three_tiers_have_three_different_exit_codes(tmp_path):
    """PASS / FAIL / NOT-CHECKED must be separable by exit code alone — that
    is the only channel `flow_compliance_check` reads."""
    ok = _empty_project(tmp_path, "ok")
    _write(ok / "phase2" / "stage2" / "constraints" / "top.sdc")
    bad = _empty_project(tmp_path, "bad")
    _write(bad / "phase2" / "stage2" / "constraints" / "top.sdc",
           "create_clock -name clk -period 20 [get_ports clk]\n")
    empty = _empty_project(tmp_path, "empty")
    codes = {"pass": _run([str(ok)]).returncode,
             "fail": _run([str(bad)]).returncode,
             "not_checked": _run([str(empty)]).returncode}
    assert codes == {"pass": 0, "fail": 1, "not_checked": 2}, codes


def test_a_skip_reaches_the_vacuous_tier_through_the_real_gate_runner(
        tmp_path):
    """The point of rc 2. Driven through `flow_compliance_check`'s OWN runner,
    so this asserts the tier the compliance report will actually render — not
    a number this test made up."""
    empty = _empty_project(tmp_path)
    passed, out = _fcc._check_program_exit_zero(
        empty, "sdc_validator_check .")
    assert passed, out
    assert out.startswith(_fcc._VACUOUS_HINT_PREFIX), (
        "a run that opened no file must reach the VACUOUS tier; at rc 0 it "
        f"was rendered as an ordinary PASS. runner said: {out!r}")


def test_a_read_and_clean_run_is_not_promoted_to_vacuous(tmp_path):
    """The other direction: a project whose SDC WAS read must stay a plain
    PASS, or the tier stops meaning anything."""
    project = _empty_project(tmp_path)
    _write(project / "phase2" / "stage2" / "constraints" / "top.sdc")
    passed, out = _fcc._check_program_exit_zero(
        project, "sdc_validator_check .")
    assert passed, out
    assert not out.startswith(_fcc._VACUOUS_HINT_PREFIX), out
    assert "1 SDC file(s) OK" in out, out


def test_absent_and_read_and_clean_are_distinguishable_by_exit_code(tmp_path):
    """The defect in one line: these two used to share rc 0."""
    empty = _empty_project(tmp_path, "empty")
    read = _empty_project(tmp_path, "read")
    _write(read / "phase2" / "stage2" / "constraints" / "top.sdc")
    assert _run([str(empty)]).returncode != _run([str(read)]).returncode


# ── 1b. the SKIP must disclose its denominator ───────────────────────────────

def test_the_skip_discloses_how_many_roots_it_searched_and_their_state(
        tmp_path):
    """The PASS line says "N SDC file(s) OK". A skip that discloses nothing is
    indistinguishable from a skip that never looked."""
    project = _empty_project(tmp_path)
    (project / "phase2" / "stage2" / "constraints").mkdir(parents=True)
    out = _run([str(project)]).stdout
    assert "2 declared search root(s)" in out, out
    assert "phase2/stage2/constraints [empty]" in out, (
        "the root that EXISTS and holds nothing must be distinguishable from "
        f"the one that is absent: {out!r}")
    assert "phase2/stage1/fpga [absent]" in out, out


def test_the_skip_discloses_the_scope_of_its_project_wide_scan(tmp_path):
    """"0 elsewhere" is a claim about the whole project; it has to say how
    much of the project it actually walked."""
    project = _empty_project(tmp_path)
    for rel in ("a/b/c", "d/e"):
        (project / rel).mkdir(parents=True)
    out = _run([str(project)]).stdout
    # 1 root + a + a/b + a/b/c + d + d/e = 6
    assert "6 director(y/ies) scanned" in out, out


def test_the_skip_denominator_tracks_the_tree_it_is_given(tmp_path):
    """Driven, not asserted as a literal: two projects of different sizes must
    report different scan denominators."""
    small = _empty_project(tmp_path, "small")
    big = _empty_project(tmp_path, "big")
    for i in range(5):
        (big / f"d{i}").mkdir()
    n_small = _svc.scan_for_stray_sdc(small).dirs_walked
    n_big = _svc.scan_for_stray_sdc(big).dirs_walked
    assert (n_small, n_big) == (1, 6), (n_small, n_big)


def test_the_skip_json_report_records_the_not_checked_verdict(tmp_path):
    """The step-8 gate declares `--json`; on a skip that file used never to be
    written at all, so nothing downstream could see the tier."""
    project = _empty_project(tmp_path)
    out = tmp_path / "rep.json"
    cp = _run([str(project), "--json", str(out)])
    assert cp.returncode == 2, cp.stdout
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "SKIP", doc
    assert doc["exit_code"] == 2, doc
    assert doc["sdc_files_checked"] == [], doc
    assert len(doc["search_roots"]) == 2, doc


# ── 2. an unusable positional ────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["missing", "file"])
def test_an_unusable_positional_is_not_checked(tmp_path, kind):
    target = tmp_path / "target"
    if kind == "file":
        target.write_text("not a project")
    cp = _run([str(target)])
    assert cp.returncode == 2, (
        f"a positional that is {kind} resolved no search root and read no "
        f"file; exit 0 recorded that as a PASS. {cp.stdout!r}")
    assert "NOT CHECKED" in cp.stdout, cp.stdout
    assert "0 .sdc file(s) were read" in cp.stdout, (
        f"the unusable-positional skip must disclose its denominator too: "
        f"{cp.stdout!r}")


def test_an_unusable_positional_does_not_reach_a_plain_pass_in_the_gate(
        tmp_path):
    """Through the real runner: the tier must be VACUOUS, not PASS."""
    project = _empty_project(tmp_path)
    passed, out = _fcc._check_program_exit_zero(
        project, "sdc_validator_check does_not_exist")
    assert passed, out
    assert out.startswith(_fcc._VACUOUS_HINT_PREFIX), out


def test_a_subtree_positional_with_no_sdc_below_it_is_not_checked(tmp_path):
    """The other half of item 2: a positional that EXISTS but names a subtree
    holding no `.sdc`. Same false certificate, same tier."""
    project = _empty_project(tmp_path)
    _write(project / "phase2" / "stage2" / "constraints" / "top.sdc")
    sub = project / "phase3" / "stage3"
    sub.mkdir(parents=True)
    cp = _run([str(sub)])
    assert cp.returncode == 2, cp.stdout
    assert "NOT CHECKED" in cp.stdout, cp.stdout


# ── 3. §4.05 — the diagnostic must not name the oracle ───────────────────────

def _off_limits_dirs() -> list[str]:
    return sorted(_rfb.OFF_LIMITS_TREE_SEGMENTS)


@pytest.mark.parametrize("segment", ["reference_flow", "golden", "oracle",
                                     "expected", "solution", "ground_truth"])
def test_a_staged_oracle_sdc_is_neither_read_nor_named(tmp_path, segment):
    """The shape the tracked corpus carries (`<design>/input/reference_flow/
    pre_syn/*.sdc`). It used to FAIL with the staged file NAMED."""
    project = _empty_project(tmp_path)
    staged = _write(project / "input" / segment / "pre_syn" / "top.sdc")
    cp = _run([str(project)])
    assert cp.returncode == 2, (
        "a project whose only .sdc is a staged upstream artifact has produced "
        f"none; that is NOT CHECKED, not a misdirection FAIL. {cp.stdout!r}")
    assert staged.name not in cp.stdout, (
        f"§4.05: the message NAMES the staged file — it points the author at "
        f"the oracle. {cp.stdout!r}")
    assert segment not in cp.stdout.split("NOT CHECKED")[-1].replace(
        "staged reference/oracle", ""), (
        f"§4.05: the message names the staged tree. {cp.stdout!r}")


def test_the_pruned_trees_are_disclosed_by_count(tmp_path):
    """Declining to read is COMPLIANCE, not a silent hole — so it is reported,
    just never by path."""
    project = _empty_project(tmp_path)
    _write(project / "input" / "reference_flow" / "top.sdc")
    _write(project / "input" / "golden" / "top.sdc")
    out = _run([str(project)]).stdout
    assert "2 staged reference/oracle" in out, out
    assert "pruned" in out, out


def test_a_stray_outside_an_oracle_tree_still_fails(tmp_path):
    """The prune must not swallow the defect the misdirection check exists for:
    a real SDC the roots cannot see is still a FAIL that names it."""
    project = _empty_project(tmp_path)
    _write(project / "input" / "reference_flow" / "golden.sdc")
    stray = _write(project / "steps" / "7_constraint_setup" / "top.sdc")
    cp = _run([str(project)])
    assert cp.returncode == 1, cp.stdout
    assert "SDC_SEARCH_ROOT_MISDIRECTED" in cp.stdout, cp.stdout
    assert stray.name in cp.stdout, cp.stdout
    assert "golden.sdc" not in cp.stdout, (
        f"§4.05: the FAIL path leaks the staged file too. {cp.stdout!r}")


def test_pointing_the_program_into_an_oracle_tree_lists_nothing(tmp_path):
    """The one-level-deeper bypass: pruning DESCENDANTS alone leaves the leak
    reachable by handing the program the staged directory itself, where the
    walk starts inside the tree and nothing prunes it."""
    project = _empty_project(tmp_path)
    staged = _write(project / "input" / "reference_flow" / "pre_syn" /
                    "top.sdc")
    cp = _run([str(project / "input" / "reference_flow" / "pre_syn")])
    assert cp.returncode == 2, cp.stdout
    assert staged.name not in cp.stdout, (
        f"§4.05: pointed at the staged tree, the program enumerated it. "
        f"{cp.stdout!r}")


def test_a_real_project_under_an_off_limits_name_is_still_validated(tmp_path):
    """The prune is scoped so it cannot silence a real design: a project that
    merely LIVES under such a path, and ships an SDC where the flow declares
    it, is validated normally."""
    project = _empty_project(tmp_path / "reference", "proj")
    _write(project / "phase2" / "stage2" / "constraints" / "top.sdc")
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stdout
    assert "1 SDC file(s) OK" in cp.stdout, cp.stdout


def test_the_oracle_vocabulary_is_the_shared_one_not_a_third_copy(tmp_path):
    """Driven, not grepped: adding a segment to the shared module must change
    this program's behaviour, which is only true if it reads that module."""
    import floorplan_contract as _fc
    assert _rfb.OFF_LIMITS_TREE_SEGMENTS <= set(_fc._OFF_LIMITS_SEGMENTS)
    for segment in _off_limits_dirs():
        project = _empty_project(tmp_path, f"p_{segment}")
        _write(project / "input" / segment / "top.sdc")
        v = _svc.evaluate(project)
        assert v.rc == 2, (segment, v.lines)
        assert "top.sdc" not in " ".join(v.lines), (segment, v.lines)
