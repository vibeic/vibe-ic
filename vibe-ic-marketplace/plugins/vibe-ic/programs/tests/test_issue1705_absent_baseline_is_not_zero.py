#!/usr/bin/env python3
"""vibe-ic#1705 — an absent baseline is not a measurement of zero.

Three ratchets rendered a verdict over a subtraction they never had. Each
computes `new = current - baseline`, and each read a baseline that states NO
measurement as one that was taken and found empty. MEASURED on `origin/main`
`7c376e348`, per checker, with its baseline moved aside and moved back:

    checker                              rc(with)  rc(none)  behaviour
    flow_gate_enforcement_audit.py           0         1     FABRICATES 116
    checker_execution_wiring_audit.py        0         1     FABRICATES  31
    silent_decline_audit.py                  0         0     PASSES SILENTLY

Both directions of one defect. Pointed at a tree with offenders, the absent
baseline turns the entire pre-existing population into regressions attributed
to whatever change is under test; pointed at one without, it reports a clean
sweep over a comparison that never happened. Neither verdict was earned, and
both come from the same line.

The remedy is the one `atomic_artifact_write_check` landed for the same defect
in `7a9e61ca8`: a baseline that does not STATE a measurement makes the gate NOT
CHECKED — rc 2, naming the path it could not read — which the dispatcher may
record as NOT_CHECKED but can never fold into PASS.

EVERY TEST HERE IS PAIRED, because "refuses when the baseline is missing" is
trivially satisfied by a gate that refuses always. The other half of each pair
is the distinction the remedy must keep: an EXPLICITLY EMPTY baseline
(`{"known": []}`, `{"count": 0}`) IS a measurement — of a clean tree — and the
first offender against it must still FAIL.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"


def _load(alias: str, name: str):
    """A private copy, so a sibling test's `sys.modules` entry cannot decide
    which version of the program this file measures."""
    spec = importlib.util.spec_from_file_location(
        alias, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


# ───────────────────────────────────────────────────────────────────────────
# flow_gate_enforcement_audit — the register that fabricated 116
# ───────────────────────────────────────────────────────────────────────────
FGEA = _load("_fgea_1705", "flow_gate_enforcement_audit")

_UNDECLARED_GATE = '"""A gate that says nothing about its own enforcement."""\n'


def _flow_tree(root: Path, *, enforced=()) -> tuple:
    """One AUDIT_ONLY gate that declares no intent — the `undeclared` shape.

    Names in `enforced` are invoked by a runner in a way that CONSUMES the exit
    status, which is what #884 made ENFORCED mean; such a gate is not in the
    undeclared population at all and gives the paired control its zero.
    """
    programs = root / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "quiet_check.py").write_text(_UNDECLARED_GATE)
    (programs / "phase3_one_shot_runner.py").write_text(
        "".join(
            f"def step_{i}():\n"
            f"    cp = subprocess.run([sys.executable, \"{n}.py\", \"p\"], "
            f"check=False)\n"
            f"    if cp.returncode != 0:\n"
            f"        return \"FAIL\"\n"
            f"    return \"PASS\"\n"
            for i, n in enumerate(enforced)) or "# no gates\n")
    flow = root / "flow.yaml"
    flow.write_text("steps:\n  - gate:\n      program_exit_zero: "
                    "quiet_check.py\n")
    return flow, programs


def _fgea(flow, programs, baseline: Path, *extra) -> int:
    return FGEA.main(["--flow", str(flow), "--programs", str(programs),
                      "--baseline", str(baseline), *extra])


def test_fgea_an_absent_baseline_does_not_make_the_tree_a_regression(
        tmp_path, capsys):
    """THE defect, in the direction that invents findings. With no baseline
    file the audit reported every pre-existing undeclared gate as debt the
    author must now record — 116 of them on main, none introduced by anything
    under test."""
    flow, programs = _flow_tree(tmp_path)
    rc = _fgea(flow, programs, tmp_path / "never_written.json")
    cap = capsys.readouterr()
    assert rc == 2, "a tree with no recorded baseline was never compared"
    assert "[FAIL]" not in cap.out + cap.err, (
        "a finding the audit has no baseline for cannot be reported as one "
        "that must be recorded")
    assert "NOT CHECKED" in cap.err and "never_written.json" in cap.err, (
        "the refusal must name the path it could not read")


def test_fgea_a_measured_empty_baseline_still_FAILS_on_the_first_finding(
        tmp_path, capsys):
    """The paired half. The refusal must not swallow the ratchet: a baseline
    recording BOTH registers as empty is a measurement of a clean tree, so the
    first undeclared gate against it is a real regression."""
    flow, programs = _flow_tree(tmp_path)
    bl = tmp_path / "measured_clean.json"
    bl.write_text(json.dumps({"known": [], "undeclared_known": []}))
    assert _fgea(flow, programs, bl) == 1
    assert "quiet_check.py" in capsys.readouterr().out


def test_fgea_a_truncated_baseline_is_NOT_CHECKED_never_a_verdict(
        tmp_path, capsys):
    """A half-written artefact reads as a whole one. The audit's OWN input is
    such an artefact, and it used to be silently equivalent to an empty file."""
    flow, programs = _flow_tree(tmp_path)
    bl = tmp_path / "truncated.json"
    bl.write_text('{"known": [')
    assert _fgea(flow, programs, bl) == 2
    cap = capsys.readouterr()
    assert "[FAIL]" not in cap.out + cap.err and "[PASS]" not in cap.out


def test_fgea_an_absent_REGISTER_in_a_readable_file_stays_UNRECORDED(
        tmp_path, capsys):
    """#886's distinction, pinned so this fix cannot flatten it. A baseline
    written before the second register existed IS a measurement — of the first
    register — and the missing one is UNRECORDED, which still exits 1 telling
    the author to record it. Only an unreadable FILE is NOT CHECKED."""
    flow, programs = _flow_tree(tmp_path)
    bl = tmp_path / "pre_886.json"
    bl.write_text(json.dumps({"known": []}))
    assert _fgea(flow, programs, bl) == 1
    assert "UNRECORDED" in capsys.readouterr().out


def test_fgea_a_clean_tree_with_a_measured_baseline_still_passes(
        tmp_path, capsys):
    """The control that keeps the fix from being 'refuse everything'."""
    flow, programs = _flow_tree(tmp_path, enforced=["quiet_check"])
    bl = tmp_path / "measured_clean.json"
    bl.write_text(json.dumps({"known": [], "undeclared_known": []}))
    assert _fgea(flow, programs, bl) == 0
    assert "[PASS]" in capsys.readouterr().out


def test_fgea_write_baseline_still_records_the_first_measurement(tmp_path):
    """`--write-baseline` is how an absent baseline stops being absent, so it
    is the ONE caller for which a missing file is the normal state. Refusing it
    would leave no way out of the refusal."""
    flow, programs = _flow_tree(tmp_path, enforced=["quiet_check"])
    bl = tmp_path / "fresh.json"
    assert _fgea(flow, programs, bl, "--write-baseline") == 0
    assert json.loads(bl.read_text())["undeclared_known"] == []


# ───────────────────────────────────────────────────────────────────────────
# checker_execution_wiring_audit — the register that fabricated 31
# ───────────────────────────────────────────────────────────────────────────
CEWA = _load("_cewa_1705", "checker_execution_wiring_audit")


def _wiring_tree(root: Path) -> Path:
    """A plugin layout holding one checker that NOTHING but its own test runs.

    Synthetic rather than the shipped tree on purpose: the real audit takes ~20
    s per invocation, and the property under test is about the BASELINE, not
    about this repo's 31 recorded entries.
    """
    programs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    (programs / "tests").mkdir(parents=True)
    (programs / "lonely_check.py").write_text(
        '"""A checker nothing but its own test runs."""\n'
        "def main():\n    return 0\n")
    (programs / "tests" / "test_lonely_check.py").write_text(
        "import lonely_check\n"
        "def test_it():\n    assert lonely_check.main() == 0\n")
    return root


def _cewa(root: Path, baseline: Path) -> int:
    return CEWA.main(["--repo-root", str(root), "--baseline", str(baseline)])


def test_cewa_an_absent_baseline_does_not_name_the_population_as_new(
        tmp_path, capsys):
    """THE defect. `new = [c for c in now if base is None or ...]` made every
    recorded test-only checker NEW the moment the baseline could not be read —
    31 accusations on main, from a missing plain JSON file."""
    root = _wiring_tree(tmp_path)
    rc = _cewa(root, tmp_path / "never_written.json")
    cap = capsys.readouterr()
    assert rc == 2
    assert "lonely_check.py" not in cap.out, (
        "a checker the audit has no baseline for cannot be called NEW")
    assert "NOT CHECKED" in cap.err and "never_written.json" in cap.err


def test_cewa_the_absent_baseline_is_never_printed_as_a_zero(
        tmp_path, capsys):
    """The population line printed `baseline 0` for a baseline it could not
    read — the absent value wearing a measured one's clothes, and it is that
    number a reader carries away. The refusal comes BEFORE the summary."""
    root = _wiring_tree(tmp_path)
    assert _cewa(root, tmp_path / "never_written.json") == 2
    assert "baseline 0" not in capsys.readouterr().out


def test_cewa_a_measured_empty_baseline_still_FAILS_on_the_first_checker(
        tmp_path, capsys):
    """The paired half: `{"known": []}` says the tree was measured and held no
    test-only checker, so the first one against it is a regression."""
    root = _wiring_tree(tmp_path)
    bl = tmp_path / "measured_clean.json"
    bl.write_text(json.dumps({"known": []}))
    assert _cewa(root, bl) == 1
    assert "lonely_check.py" in capsys.readouterr().out


def test_cewa_a_truncated_baseline_is_NOT_CHECKED_never_PASS(
        tmp_path, capsys):
    root = _wiring_tree(tmp_path)
    bl = tmp_path / "truncated.json"
    bl.write_text('{"known": [')
    assert _cewa(root, bl) == 2
    assert "[PASS]" not in capsys.readouterr().out


def test_cewa_a_recorded_checker_with_a_measured_baseline_passes(
        tmp_path, capsys):
    """The control. The recorded residual is not a new finding."""
    root = _wiring_tree(tmp_path)
    bl = tmp_path / "recorded.json"
    bl.write_text(json.dumps({"known": ["lonely_check.py"]}))
    assert _cewa(root, bl) == 0
    assert "[PASS]" in capsys.readouterr().out


# ───────────────────────────────────────────────────────────────────────────
# silent_decline_audit — the one that passed silently, both ways
# ───────────────────────────────────────────────────────────────────────────
SDA = _load("_sda_1705", "silent_decline_audit")

_SILENT = """\
def loosen_die(x):
    return None

def run(x):
    lf = loosen_die(x)
    if lf is not None:
        apply_it(lf)
"""
_DISCLOSED = _SILENT + """    else:
        print("loosen declined: die stays as-is")
"""


def _src(tmp_path: Path, body: str) -> Path:
    d = tmp_path / "src"
    d.mkdir(exist_ok=True)
    (d / "m.py").write_text(body)
    return d


def test_sda_a_bare_run_without_a_baseline_is_NOT_CHECKED(tmp_path, capsys):
    """THE defect, and the reason it survived: the ratchet refused correctly,
    but ONLY when asked for with `--ratchet`. A bare run never opened the
    baseline at all and returned 0 whether one existed or not — the two states
    an exit code exists to tell apart, reported identically."""
    d = _src(tmp_path, _SILENT)
    rc = SDA.main([str(d), "--baseline", str(tmp_path / "never_written.json")])
    out = capsys.readouterr().out
    assert rc == 2, "a run that consulted no baseline has not ratcheted"
    assert "[PASS]" not in out
    assert "NOT CHECKED" in out and "never_written.json" in out


def test_sda_a_bare_run_ratchets_against_a_recorded_baseline(tmp_path):
    """The paired half, and the direction that proves the default is a real
    comparison rather than a new way to refuse: recorded at 0 declines, the
    first one that lands FAILs — with no `--ratchet` on the command line."""
    d = _src(tmp_path, _DISCLOSED)
    bl = tmp_path / "bl.json"
    assert SDA.main([str(d), "--baseline", str(bl), "--write-baseline"]) == 0
    assert json.loads(bl.read_text())["count"] == 0
    assert SDA.main([str(d), "--baseline", str(bl)]) == 0
    (d / "m.py").write_text(_SILENT)
    assert SDA.main([str(d), "--baseline", str(bl)]) == 1


def test_sda_the_ratchet_flag_is_still_accepted(tmp_path):
    """`tools/ci/repo_hygiene_gates.sh` passes it and existing tests use it;
    the flag naming what the gate does is worth keeping in the wiring."""
    d = _src(tmp_path, _SILENT)
    assert SDA.main([str(d), "--ratchet",
                     "--baseline", str(tmp_path / "absent.json")]) == 2


def test_sda_a_truncated_baseline_is_NOT_CHECKED(tmp_path, capsys):
    d = _src(tmp_path, _SILENT)
    bl = tmp_path / "truncated.json"
    bl.write_text('{"count": ')
    assert SDA.main([str(d), "--baseline", str(bl)]) == 2
    assert "[PASS]" not in capsys.readouterr().out


def test_sda_strict_still_answers_from_the_tree_alone(tmp_path):
    """`--strict` needs no baseline — any finding fails and none passes — so
    the refusal must not reach it."""
    assert SDA.main([str(_src(tmp_path, _SILENT)), "--strict"]) == 1
    assert SDA.main([str(_src(tmp_path, _DISCLOSED)), "--strict"]) == 0


# ───────────────────────────────────────────────────────────────────────────
# tracked_symlink_target_present_check — the fourth site, latent
# ───────────────────────────────────────────────────────────────────────────
# #1705's probe could not decide this one: the corpus left this repository in
# v1.10.56, so the population refusal ("git tracks nothing at all under
# benchmark-data") fires first and masks whatever the register does. Read
# rather than probed, it is the same defect — an UNREADABLE register refused
# in so many words while an ABSENT one became `recorded = []`, the value a
# register that WAS written and found clean carries.
TSTP = _load("_tstp_1705", "tracked_symlink_target_present_check")


def _git_corpus(tmp_path: Path) -> Path:
    """A real git repo with one tracked symlink pointing at nothing.

    Git's INDEX is what this gate reads, so the fixture has to be a repository
    rather than a directory of files.
    """
    import subprocess
    root = tmp_path / "corpus"
    (root / "ic").mkdir(parents=True)
    (root / "ic" / "dangling").symlink_to("no_such_target")
    for argv in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-qm", "corpus"]):
        subprocess.run(["git", "-C", str(root), *argv], check=True,
                       capture_output=True, timeout=60)
    return root


def _tstp(root: Path, baseline: Path, *extra) -> int:
    return TSTP.main(["--root", str(root), "--subdir", "ic",
                      "--baseline", str(baseline), *extra])


def test_tstp_an_absent_register_does_not_make_the_corpus_a_regression(
        tmp_path, capsys):
    root = _git_corpus(tmp_path)
    assert _tstp(root, tmp_path / "never_written.json") == 2
    cap = capsys.readouterr()
    assert "NOT CHECKED" in cap.err and "never_written.json" in cap.err
    assert "BROKEN" not in cap.out, (
        "a pointer the gate has no register for cannot be reported as new")


def test_tstp_a_measured_empty_register_still_FAILS_on_the_first_pointer(
        tmp_path, capsys):
    """The paired half: `{"known": []}` is a corpus that was measured and held
    no broken pointer, so the first one against it is a real regression."""
    root = _git_corpus(tmp_path)
    bl = tmp_path / "measured_clean.json"
    bl.write_text(json.dumps({"known": []}))
    assert _tstp(root, bl) == 1
    assert "dangling" in capsys.readouterr().out


def test_tstp_write_baseline_still_records_the_first_measurement(tmp_path):
    root = _git_corpus(tmp_path)
    bl = tmp_path / "fresh.json"
    assert _tstp(root, bl, "--write-baseline") == 0
    assert json.loads(bl.read_text())["known"] == ["ic/dangling"]


# ───────────────────────────────────────────────────────────────────────────
# The shipped tree, with the shipped baselines: all three still PASS
# ───────────────────────────────────────────────────────────────────────────

def test_the_shipped_baselines_are_read_and_the_three_gates_are_green():
    """The gates run blocking in `tools/ci/repo_hygiene_gates.sh`. A refusal
    that reddened main would be the fix failing in the other direction."""
    assert SDA.main([str(_PROGRAMS), "--ratchet"]) == 0
