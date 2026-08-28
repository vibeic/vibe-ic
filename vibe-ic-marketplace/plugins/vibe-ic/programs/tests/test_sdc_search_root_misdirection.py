"""`[SKIP] no .sdc files` must mean the project ships none — not "I looked in
the wrong place".

The defect
----------
`sdc_validator_check` globs `*.sdc` from exactly two roots resolved off its
positional (`phase2/stage1/fpga`, `phase2/stage2/constraints`). When that glob
came back empty it printed

    [SKIP] sdc_validator_check: no .sdc files

and exited 0 — the SAME line at the SAME exit code for two situations that mean
opposite things:

  * the project genuinely ships no SDC (correct: step 8's first all_of member,
    `sdc_syntax_check`, is what blocks that case), and
  * the project DOES ship an SDC, but not where this program looked.

The second case is a certification of step 8 built out of files nobody read.
It arises two ways, both observed:

  * the gate is handed something that is not the project root — the 8/d2
    declaration defect, where `sdc_validator_check phase2/stage2/constraints`
    resolved `phase2/stage2/constraints/phase2/stage2/constraints`; and
  * the SDC producer writes outside the declared constraints directory — e.g.
    only the `steps/7_constraint_setup_sdc_pvt_matrix/` publish copy exists.
    That one survives the declaration fix, so the declaration fix alone does
    not close this hole.

Measured on the real completed run (~/campaign_pr427/spm/converge_ihp-sg13g2,
pure-digital spm x ihp-sg13g2), `sdc_validator_check phase2/stage2/constraints`:

    origin/main : [SKIP] sdc_validator_check: no .sdc files          rc=0
    this branch : [FAIL] SDC_SEARCH_ROOT_MISDIRECTED ... spm.sdc     rc=1

while the shipped step-8 command (`sdc_validator_check .`) is byte-for-byte
unchanged on that project: rc=1 for the pre-existing L8 clock contradiction
with `--l8`, and `[PASS] ... 2 SDC file(s) OK` rc=0 without it.

What is asserted here
---------------------
Observable properties only — an exit code and whether two runs are
distinguishable. The one place a literal is asserted is the diagnostic NAME,
because naming the failure is itself the requirement: a reviewer has to be able
to tell a misdirected search root from an unconstrained design without reading
the source.

Direction-1 guards pin what must NOT change: a project with no SDC anywhere
still does not FAIL; an SDC in either declared root is still validated and
still fails for its own reason; a stray copy alongside a properly-placed SDC
changes nothing (this is the reference run's shape); and the pre-existing
L8-self-contradiction exit still fires on a project with no SDC at all.

EXIT CODES (see `sdc_validator_check`'s module docstring): 0 PASS, 1 FAIL,
2 NOT CHECKED. Every path that reads nothing exits 2. The skip cases here
therefore assert rc 2, not rc 0 — at rc 0 they were recorded as ordinary
PASSes of a program that never opened a file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent
for _p in (str(_PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import flow_compliance_check as _fcc                      # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = _PROGRAMS / "sdc_validator_check.py"
FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

_GOOD_SDC = """\
create_clock -name clk -period 20 [get_ports clk]
set_input_delay  -clock clk 2 [get_ports din]
set_output_delay -clock clk 2 [get_ports dout]
"""
_UNCONSTRAINED_SDC = "create_clock -name clk -period 20 [get_ports clk]\n"

#: The publish copy the flow writes for step 7. A project that has only this
#: one has produced an SDC that the declared search roots cannot see.
_PUBLISH_REL = Path("steps") / "7_constraint_setup_sdc_pvt_matrix" / "spm.sdc"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _project(tmp_path: Path, name: str = "proj", *, constraints=None,
             fpga=None, stray: dict | None = None,
             l8: str | None = '{"clocks": []}') -> Path:
    project = tmp_path / name
    project.mkdir(parents=True, exist_ok=True)
    if l8 is not None:
        _write(project / "phase1" / "generated_docs" /
               "L8_TIMING_WAVEFORM.json", l8)
    if constraints is not None:
        _write(project / "phase2" / "stage2" / "constraints" / "top.sdc",
               constraints)
    if fpga is not None:
        _write(project / "phase2" / "stage1" / "fpga" / "board.sdc", fpga)
    for rel, text in (stray or {}).items():
        _write(project / rel, text)
    return project


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True)


# ── discriminators ───────────────────────────────────────────────────────────

def test_an_sdc_the_search_roots_cannot_see_is_not_reported_as_absent(tmp_path):
    """The producer-side shape, which survives the declaration fix: the SDC was
    written only to the step-7 publish copy. Pre-fix this exited 0."""
    project = _project(tmp_path, stray={_PUBLISH_REL: _GOOD_SDC})
    cp = _run([str(project)])
    assert cp.returncode == 1, (
        "a project that carries an SDC the declared roots do not see must not "
        f"exit 0 — that certifies step 8 off files nobody read. {cp.stdout!r}")
    assert "[SKIP]" not in cp.stdout, cp.stdout


def test_a_misdirected_root_is_distinguishable_from_an_empty_project(tmp_path):
    """The 8/d2 shape. The whole defect was that these two produced identical
    output at an identical exit code."""
    real = _project(tmp_path, "real", constraints=_GOOD_SDC)
    misdirected = _run([str(real / "phase2" / "stage2" / "constraints")])
    empty = _run([str(_project(tmp_path, "empty"))])
    assert empty.returncode == 2 and "[SKIP]" in empty.stdout, empty.stdout
    assert misdirected.returncode != empty.returncode, (
        "misdirected and genuinely-empty must not share an exit code: "
        f"{misdirected.returncode} vs {empty.returncode}")
    assert misdirected.stdout.strip() != empty.stdout.strip(), (
        f"misdirected={misdirected.stdout!r} empty={empty.stdout!r}")


def test_an_sdc_nested_below_the_constraints_dir_is_not_reported_as_absent(
        tmp_path):
    """The roots are globbed with `*.sdc`, not `**/*.sdc`, so a constraints
    directory that keeps its SDC one level down is read by nobody. That must be
    reported, not skipped."""
    project = _project(tmp_path, stray={
        Path("phase2/stage2/constraints/corner_ss/top.sdc"): _GOOD_SDC})
    cp = _run([str(project)])
    assert cp.returncode == 1, cp.stdout
    assert "SDC_SEARCH_ROOT_MISDIRECTED" in cp.stdout, cp.stdout


def test_the_diagnostic_names_the_roots_searched_and_the_file_found(tmp_path):
    """Naming the failure is the requirement, not a nicety: the reviewer must
    be able to act without reading this program's source."""
    project = _project(tmp_path, stray={_PUBLISH_REL: _GOOD_SDC})
    cp = _run([str(project)])
    assert "SDC_SEARCH_ROOT_MISDIRECTED" in cp.stdout, cp.stdout
    assert "phase2/stage2/constraints" in cp.stdout, cp.stdout
    assert "phase2/stage1/fpga" in cp.stdout, cp.stdout
    assert str(_PUBLISH_REL) in cp.stdout, (
        "the diagnostic must cite the file it found, or it cannot be acted "
        f"on: {cp.stdout!r}")


def test_the_json_report_records_the_roots_and_the_failure(tmp_path):
    """The gate declares `--json`; on this failure the JSON is the only
    durable evidence, so it must carry the verdict and the searched roots."""
    project = _project(tmp_path, stray={_PUBLISH_REL: _GOOD_SDC})
    out = tmp_path / "rep.json"
    cp = _run([str(project), "--json", str(out)])
    assert cp.returncode == 1, cp.stdout
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "FAIL", doc
    assert doc["sdc_files_checked"] == [], doc
    roots = " ".join(doc.get("search_roots", []))
    assert "phase2/stage2/constraints" in roots, doc
    assert "phase2/stage1/fpga" in roots, doc
    assert any("SDC_SEARCH_ROOT_MISDIRECTED" in i for i in doc["issues"]), doc


def test_the_shipped_step8_gate_fails_a_misplaced_sdc(tmp_path):
    """End-to-end through flow_compliance_check's own resolver + runner, using
    the literal command parsed out of the shipped yaml — the gate must go red,
    not merely the program."""
    doc = yaml.safe_load(FLOW.read_text())
    cmd = None
    for st in doc.get("steps", []):
        if str(st.get("id")) != "8":
            continue
        for member in (st.get("gate") or {}).get("all_of", []):
            spec = (member or {}).get("optional_program_exit_zero")
            if isinstance(spec, dict) and str(spec.get("command", "")).startswith(
                    "sdc_validator_check"):
                cmd = spec["command"]
    assert cmd, ("premise: step 8 no longer declares an sdc_validator_check "
                 "gate — this test scans nothing")
    project = _project(tmp_path, stray={_PUBLISH_REL: _GOOD_SDC})
    passed, out = _fcc._check_program_exit_zero(project, cmd)
    assert not passed, (
        "step 8 must not pass on a project whose only SDC sits outside the "
        f"declared constraints directory. output: {out!r}")


# ── direction-1 guards: behaviour that must NOT change ──────────────────────

def test_guard_no_sdc_anywhere_still_skips_without_failing(tmp_path):
    """Still not a FAIL — but it is NOT CHECKED (rc 2), not a bare PASS.
    `sdc_syntax_check`, step 8's first all_of member, is what blocks a design
    that needs constraints and ships none."""
    cp = _run([str(_project(tmp_path))])
    assert cp.returncode == 2, cp.stdout
    assert "[SKIP]" in cp.stdout, cp.stdout


def test_guard_sdc_in_the_declared_constraints_dir_still_passes(tmp_path):
    cp = _run([str(_project(tmp_path, constraints=_GOOD_SDC))])
    assert cp.returncode == 0, cp.stdout
    assert "[PASS]" in cp.stdout and "1 SDC file(s) OK" in cp.stdout, cp.stdout


def test_guard_sdc_in_the_fpga_early_dir_still_passes(tmp_path):
    cp = _run([str(_project(tmp_path, fpga=_GOOD_SDC))])
    assert cp.returncode == 0, cp.stdout
    assert "[PASS]" in cp.stdout, cp.stdout


def test_guard_both_declared_roots_are_still_read(tmp_path):
    cp = _run([str(_project(tmp_path, constraints=_GOOD_SDC, fpga=_GOOD_SDC))])
    assert cp.returncode == 0, cp.stdout
    assert "2 SDC file(s) OK" in cp.stdout, cp.stdout


def test_guard_a_stray_copy_alongside_a_placed_sdc_changes_nothing(tmp_path):
    """The reference run's own shape: 4 .sdc on disk, 2 of them under the
    declared roots. The stray scan must not run at all once the roots have
    produced files, or every real project would go red."""
    project = _project(tmp_path, constraints=_GOOD_SDC, fpga=_GOOD_SDC,
                       stray={_PUBLISH_REL: _GOOD_SDC,
                              Path("phase3/stage3/pnr/constraint.sdc"):
                                  _UNCONSTRAINED_SDC})
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stdout
    assert "2 SDC file(s) OK" in cp.stdout, cp.stdout
    assert "SDC_SEARCH_ROOT_MISDIRECTED" not in cp.stdout, cp.stdout


def test_guard_a_broken_sdc_in_the_roots_still_fails_for_its_own_reason(
        tmp_path):
    """The misdirection check must never hijack the structural verdict."""
    project = _project(tmp_path, constraints=_UNCONSTRAINED_SDC,
                       stray={_PUBLISH_REL: _GOOD_SDC})
    cp = _run([str(project)])
    assert cp.returncode == 1, cp.stdout
    assert "set_input_delay" in cp.stdout and "set_output_delay" in cp.stdout
    assert "SDC_SEARCH_ROOT_MISDIRECTED" not in cp.stdout, cp.stdout


def test_guard_l8_self_contradiction_with_no_sdc_anywhere_still_fails(tmp_path):
    """The pre-existing exit-1 path for a contradictory L8 on a project with no
    SDC at all — evaluated before the skip — must survive."""
    project = _project(tmp_path)
    l8 = tmp_path / "l8.json"
    l8.write_text(json.dumps({"clocks": [{"name": "clk", "period_ns": 10.0},
                                         {"name": "clk", "period_ns": 8.0}]}))
    cp = _run([str(project), "--l8", str(l8)])
    assert cp.returncode == 1, cp.stdout
    assert "conflicting periods" in cp.stdout, cp.stdout


def test_guard_tool_metadata_directories_are_not_scanned(tmp_path):
    """A `.sdc` inside `.git` / `__pycache__` is not the project's constraint
    set and must not turn a genuinely-empty project red."""
    project = _project(tmp_path, stray={Path(".git") / "x.sdc": _GOOD_SDC,
                                        Path("__pycache__") / "y.sdc": _GOOD_SDC})
    cp = _run([str(project)])
    assert cp.returncode == 2, cp.stdout
    assert "[SKIP]" in cp.stdout, cp.stdout


# INVERTED — this used to assert rc 0.
#
# `test_guard_a_nonexistent_positional_still_skips` asserted that a positional
# which does not exist exits 0. That is the false certificate itself, written
# down as a guard: the program resolved two search roots under a path that is
# not there, opened nothing, and the compliance report recorded an ordinary
# PASS with no `__VACUOUS_HINT__`. A guard that pins a defect prevents the fix
# rather than protecting anything, so it is inverted here rather than kept.
@pytest.mark.parametrize("positional", ["does/not/exist", "not/a/dir/parent"])
def test_a_nonexistent_positional_is_not_checked_not_passed(tmp_path,
                                                            positional):
    cp = _run([str(tmp_path / positional)])
    assert cp.returncode == 2, (
        "a positional that does not exist read ZERO files; exit 0 records "
        f"that as an ordinary PASS. {cp.stdout!r}")
    assert "NOT CHECKED" in cp.stdout, cp.stdout


def test_a_positional_that_is_a_file_is_not_checked(tmp_path):
    f = tmp_path / "top.sdc"
    f.write_text(_GOOD_SDC)
    cp = _run([str(f)])
    assert cp.returncode == 2, (
        "a positional that is a file is not a project root; nothing was "
        f"validated. {cp.stdout!r}")
    assert "NOT CHECKED" in cp.stdout, cp.stdout
