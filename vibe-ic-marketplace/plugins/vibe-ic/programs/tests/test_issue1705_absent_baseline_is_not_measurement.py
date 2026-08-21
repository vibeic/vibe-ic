#!/usr/bin/env python3
"""vibe-ic#1705 — a ratchet cannot compare against a baseline it never read.

All four programs below derive their verdict from ``current - baseline``.  The
load-bearing distinction is therefore between an explicitly measured empty
set and no measurement at all:

* absent / unreadable / truncated baseline -> rc 2, NOT CHECKED, path named;
* an explicitly valid empty baseline -> a first offender is NEW and rc 1.

The four sites, in the order the issue probed them, and what each did when the
baseline was moved aside on `main` ee849c19e (re-measured at v1.10.75):

    flow_gate_enforcement_audit.py           FABRICATED 116 findings, rc 1
    checker_execution_wiring_audit.py        FABRICATED  31 findings, rc 1
    silent_decline_audit.py                  PASSED SILENTLY over 15,   rc 0
    tracked_symlink_target_present_check.py  INCONCLUSIVE in this tree —
        its corpus moved to its own repository at v1.10.56, so the run reaches
        NO_CORPUS before any verdict. Given the corpus it did not have (built
        here as a synthetic git repo), it FABRICATES too: rc 0 with the
        register, rc 1 and "1 NEW committed pointer(s)" with it absent.

The pairs exercise the programs through their CLIs on small synthetic trees.
That keeps the control behavioural: before the fix the first half returns rc 1
(or, for `silent_decline_audit`, rc 0) and misattributes the pre-existing
offender, while the second half already proves the ratchet must keep its teeth.
An over-correction that simply refuses everything fails that second half.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parent.parent
FLOW_AUDIT = PROGRAMS / "flow_gate_enforcement_audit.py"
WIRING_AUDIT = PROGRAMS / "checker_execution_wiring_audit.py"


def _baseline(path: Path, state: str) -> Path:
    if state == "unreadable":
        # A directory exists but cannot be read as the baseline artefact.  This
        # is deterministic under every test uid, unlike chmod-based fixtures.
        path.mkdir()
    elif state == "truncated":
        path.write_text('{"known": [', encoding="utf-8")
    elif state == "invalid_utf8":
        path.write_bytes(b'{"known": ["sample_check.py\xff"]}')
    elif state == "invalid_schema":
        path.write_text('{"known": [null]}', encoding="utf-8")
    else:
        assert state == "absent"
        assert not path.exists()
    return path


def _flow_tree(root: Path) -> tuple[Path, Path]:
    programs = root / "programs"
    programs.mkdir(parents=True)
    (programs / "sample_check.py").write_text(
        '"""No enforcement declaration."""\n', encoding="utf-8")
    flow = root / "flow.yaml"
    flow.write_text(
        "steps:\n"
        "  - gate:\n"
        "      program_exit_zero: sample_check.py\n",
        encoding="utf-8")
    return flow, programs


def _wiring_tree(root: Path) -> None:
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    for rel in ("programs/tests", "flow", "skills", "agents", "commands",
                "tests"):
        (plugin / rel).mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "tools").mkdir()
    (plugin / "programs" / "sample_check.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8")
    (plugin / "programs" / "tests" / "test_sample_check.py").write_text(
        "import sample_check\n", encoding="utf-8")


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *argv], capture_output=True, text=True, check=False)


@pytest.mark.parametrize(
    "state", ("absent", "unreadable", "truncated", "invalid_utf8",
              "invalid_schema"))
def test_flow_enforcement_audit_refuses_a_baseline_it_cannot_read(
        tmp_path: Path, state: str) -> None:
    flow, programs = _flow_tree(tmp_path)
    baseline = _baseline(tmp_path / "flow-baseline.json", state)

    got = _run(str(FLOW_AUDIT), "--flow", str(flow), "--programs",
               str(programs), "--baseline", str(baseline))
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript, transcript
    assert str(baseline) in transcript, transcript
    assert "[PASS]" not in transcript and "[FAIL]" not in transcript, transcript


def test_flow_enforcement_audit_keeps_an_explicit_empty_measurement_blocking(
        tmp_path: Path) -> None:
    flow, programs = _flow_tree(tmp_path)
    baseline = tmp_path / "flow-baseline.json"
    baseline.write_text(json.dumps({
        "known": [], "undeclared_known": [],
    }), encoding="utf-8")

    got = _run(str(FLOW_AUDIT), "--flow", str(flow), "--programs",
               str(programs), "--baseline", str(baseline))
    transcript = got.stdout + got.stderr

    assert got.returncode == 1, transcript
    assert "[FAIL]" in transcript and "sample_check.py" in transcript, transcript
    assert "NOT CHECKED" not in transcript, transcript


def test_flow_enforcement_audit_does_not_overwrite_a_truncated_measurement(
        tmp_path: Path) -> None:
    flow, programs = _flow_tree(tmp_path)
    baseline = tmp_path / "flow-baseline.json"
    truncated = '{"known": ['
    baseline.write_text(truncated, encoding="utf-8")

    got = _run(str(FLOW_AUDIT), "--flow", str(flow), "--programs",
               str(programs), "--baseline", str(baseline), "--write-baseline")
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript and str(baseline) in transcript, transcript
    assert baseline.read_text(encoding="utf-8") == truncated


@pytest.mark.parametrize(
    "state", ("absent", "unreadable", "truncated", "invalid_utf8",
              "invalid_schema"))
def test_checker_wiring_audit_refuses_a_baseline_it_cannot_read(
        tmp_path: Path, state: str) -> None:
    _wiring_tree(tmp_path)
    baseline = _baseline(tmp_path / "wiring-baseline.json", state)

    got = _run(str(WIRING_AUDIT), "--repo-root", str(tmp_path),
               "--baseline", str(baseline))
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript, transcript
    assert str(baseline) in transcript, transcript
    assert "[PASS]" not in transcript and "[FAIL]" not in transcript, transcript


def test_checker_wiring_audit_keeps_an_explicit_empty_measurement_blocking(
        tmp_path: Path) -> None:
    _wiring_tree(tmp_path)
    baseline = tmp_path / "wiring-baseline.json"
    baseline.write_text(json.dumps({"known": []}), encoding="utf-8")

    got = _run(str(WIRING_AUDIT), "--repo-root", str(tmp_path),
               "--baseline", str(baseline))
    transcript = got.stdout + got.stderr

    assert got.returncode == 1, transcript
    assert "[FAIL]" in transcript and "sample_check.py" in transcript, transcript
    assert "NOT CHECKED" not in transcript, transcript


def test_checker_wiring_audit_does_not_overwrite_a_truncated_measurement(
        tmp_path: Path) -> None:
    _wiring_tree(tmp_path)
    baseline = tmp_path / "wiring-baseline.json"
    truncated = '{"known": ['
    baseline.write_text(truncated, encoding="utf-8")

    got = _run(str(WIRING_AUDIT), "--repo-root", str(tmp_path),
               "--baseline", str(baseline), "--write-baseline")
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript and str(baseline) in transcript, transcript
    assert baseline.read_text(encoding="utf-8") == truncated


# ───────────────────────────────────────────────────────────────────────────
# silent_decline_audit — the OTHER direction of the same defect.
#
# The two audits above FABRICATE: with nothing to subtract they report the
# whole inherited population as regressions. This one did the reverse. Its
# comparison was gated behind `--ratchet`, so the DEFAULT invocation printed
# every finding it had just measured and returned 0 without opening the
# baseline at all — and returned the same 0 with the baseline present. rc 0
# therefore meant both "compared, and at or below the record" and "never
# compared", which is a pass over a comparison that never happened.
#
# Probed on main ee849c19e (and reproduced at v1.10.75): 15 live findings,
# rc 0 with the baseline in place, rc 0 with it moved aside.
# ───────────────────────────────────────────────────────────────────────────

SILENT_AUDIT = PROGRAMS / "silent_decline_audit.py"

# One remedy-semantic call whose decline path records nothing. `loosen` is in
# the audit's own remedy vocabulary and the `if ... is not None:` has no else,
# which is the exact shape #313 §6 defines.
_ONE_SILENT_DECLINE = """\
def loosen_die(x):
    return None


def run(x):
    lf = loosen_die(x)
    if lf is not None:
        apply_it(lf)
"""


def _silent_tree(root: Path) -> Path:
    src = root / "src"
    src.mkdir()
    (src / "m.py").write_text(_ONE_SILENT_DECLINE, encoding="utf-8")
    return src


def _count_baseline(path: Path, state: str) -> Path:
    """The same unreadable states as `_baseline`, in this program's schema."""
    if state == "unreadable":
        path.mkdir()
    elif state == "truncated":
        path.write_text('{"count": ', encoding="utf-8")
    elif state == "not_an_object":
        path.write_text("[0]", encoding="utf-8")
    elif state == "count_absent":
        path.write_text('{"scanned": 1}', encoding="utf-8")
    elif state == "count_is_bool":
        # `True` is an `int` in Python; without an explicit bool guard this
        # ratchets against 1 while claiming to have read a measurement.
        path.write_text('{"count": true}', encoding="utf-8")
    elif state == "count_is_negative":
        # No scan can produce one, so it is a corrupt record, not a measurement.
        path.write_text('{"count": -1}', encoding="utf-8")
    else:
        assert state == "absent"
        assert not path.exists()
    return path


@pytest.mark.parametrize("ratchet_flag", ([], ["--ratchet"]))
@pytest.mark.parametrize(
    "state", ("absent", "unreadable", "truncated", "not_an_object",
              "count_absent", "count_is_bool", "count_is_negative"))
def test_silent_decline_audit_refuses_a_baseline_it_cannot_read(
        tmp_path: Path, state: str, ratchet_flag: list) -> None:
    """Parametrised over the flag ON PURPOSE.

    `--ratchet` already refused an absent baseline; the DEFAULT run did not
    consult one at all. Asserting only the flagged form is what let the
    default keep passing. Both invocations must now refuse identically.
    """
    src = _silent_tree(tmp_path)
    baseline = _count_baseline(tmp_path / "silent-baseline.json", state)

    got = _run(str(SILENT_AUDIT), str(src), "--baseline", str(baseline),
               *ratchet_flag)
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript, transcript
    assert str(baseline) in transcript, transcript
    assert "[PASS]" not in transcript and "[FAIL]" not in transcript, transcript


@pytest.mark.parametrize("ratchet_flag", ([], ["--ratchet"]))
def test_silent_decline_audit_keeps_an_explicit_zero_measurement_blocking(
        tmp_path: Path, ratchet_flag: list) -> None:
    """A recorded 0 IS a measurement — of a clean tree — and the first silent
    decline against it is NEW. Without this half the fix above is satisfied by
    a program that refuses unconditionally and never ratchets again."""
    src = _silent_tree(tmp_path)
    baseline = tmp_path / "silent-baseline.json"
    baseline.write_text(json.dumps({"count": 0}), encoding="utf-8")

    got = _run(str(SILENT_AUDIT), str(src), "--baseline", str(baseline),
               *ratchet_flag)
    transcript = got.stdout + got.stderr

    assert got.returncode == 1, transcript
    assert "GREW 0 -> 1" in transcript, transcript
    assert "NOT CHECKED" not in transcript, transcript


@pytest.mark.parametrize("ratchet_flag", ([], ["--ratchet"]))
def test_silent_decline_audit_still_passes_at_or_below_its_record(
        tmp_path: Path, ratchet_flag: list) -> None:
    """The negative control for the two above: a readable record the tree does
    not exceed is a genuine PASS, so neither assertion is satisfied merely by
    making the program red."""
    src = _silent_tree(tmp_path)
    baseline = tmp_path / "silent-baseline.json"
    baseline.write_text(json.dumps({"count": 1}), encoding="utf-8")

    got = _run(str(SILENT_AUDIT), str(src), "--baseline", str(baseline),
               *ratchet_flag)
    transcript = got.stdout + got.stderr

    assert got.returncode == 0, transcript
    assert "[PASS]" in transcript, transcript
    assert "NOT CHECKED" not in transcript, transcript


def test_silent_decline_audit_default_run_reports_the_same_verdict_as_ratchet(
        tmp_path: Path) -> None:
    """The defect stated directly: the two invocations disagreed on rc.

    With the comparison gated behind the flag, the bare run returned 0 on a
    tree the flagged run refused. Pinning them to the same rc is what stops
    the gate being reintroduced by moving the comparison back behind an
    opt-in, which the parametrisation above would not catch on its own.
    """
    src = _silent_tree(tmp_path)
    absent = tmp_path / "never-written.json"

    bare = _run(str(SILENT_AUDIT), str(src), "--baseline", str(absent))
    flagged = _run(str(SILENT_AUDIT), str(src), "--baseline", str(absent),
                   "--ratchet")

    assert bare.returncode == flagged.returncode == 2, (
        f"bare rc={bare.returncode} flagged rc={flagged.returncode}\n"
        f"{bare.stdout}{bare.stderr}")


def test_silent_decline_audit_names_the_findings_it_declines_to_attribute(
        tmp_path: Path) -> None:
    """NOT CHECKED must not also mean SILENT. The measured findings are still
    printed and counted; what the program refuses is only the attribution of
    them to `new` or `recorded`."""
    src = _silent_tree(tmp_path)
    got = _run(str(SILENT_AUDIT), str(src),
               "--baseline", str(tmp_path / "never-written.json"))
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "silent declines: 1" in transcript, transcript
    assert "loosen_die" in transcript, transcript


# ───────────────────────────────────────────────────────────────────────────
# tracked_symlink_target_present_check — the site #1705 could only record as
# INCONCLUSIVE.
#
# Its register is read before the population, and an UNREADABLE one already
# refused with the words "a missing register is not an empty one". An ABSENT
# one skipped that branch entirely and left `recorded` at `[]` — the value
# that means measured-and-empty — so `hard - recorded` reported every
# inherited pointer as NEW.
#
# The published corpus left this repository at v1.10.56, so a run here reaches
# NO_CORPUS before ever computing a verdict, which is why the issue's probe saw
# rc 2 with and without the register and could not tell. These tests build the
# corpus the probe did not have, and the fabrication is immediate.
# ───────────────────────────────────────────────────────────────────────────

SYMLINK_CHECK = PROGRAMS / "tracked_symlink_target_present_check.py"


def _git(root: Path, *argv: str) -> None:
    subprocess.run(["git", "-C", str(root), *argv], check=True,
                   capture_output=True, text=True)


def _corpus_with_one_broken_pointer(root: Path) -> Path:
    """A git repo whose index carries one symlink at a file that is nowhere.

    `git` is asked rather than the filesystem because the program under test
    reads the index; a walk would answer a different question.
    """
    cell = root / "bd" / "cell"
    cell.mkdir(parents=True)
    (cell / "real.txt").write_text("present\n", encoding="utf-8")
    (cell / "dangling.lnk").symlink_to("../missing/nowhere.txt")
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "guard@example.invalid")
    _git(root, "config", "user.name", "guard")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "corpus")
    return root


def _register(path: Path, state: str) -> Path:
    if state == "unreadable":
        path.mkdir()
    elif state == "truncated":
        path.write_text('{"known": [', encoding="utf-8")
    elif state == "not_an_object":
        path.write_text('["bd/cell/dangling.lnk"]', encoding="utf-8")
    elif state == "known_absent":
        path.write_text('{"_comment": "no register here"}', encoding="utf-8")
    elif state == "known_not_strings":
        path.write_text('{"known": [null]}', encoding="utf-8")
    else:
        assert state == "absent"
        assert not path.exists()
    return path


@pytest.mark.parametrize(
    "state", ("absent", "unreadable", "truncated", "not_an_object",
              "known_absent", "known_not_strings"))
def test_symlink_check_refuses_a_register_it_cannot_read(
        tmp_path: Path, state: str) -> None:
    root = _corpus_with_one_broken_pointer(tmp_path / "repo")
    register = _register(tmp_path / "register.json", state)

    got = _run(str(SYMLINK_CHECK), "--root", str(root), "--subdir", "bd",
               "--baseline", str(register))
    transcript = got.stdout + got.stderr

    assert got.returncode == 2, transcript
    assert "NOT CHECKED" in transcript, transcript
    assert str(register) in transcript, transcript
    assert "[FAIL]" not in transcript and "[PASS]" not in transcript, transcript


def test_symlink_check_keeps_an_explicit_empty_register_blocking(
        tmp_path: Path) -> None:
    """`{"known": []}` is a measurement — of a corpus with no broken pointer —
    and the first one against it is NEW. Without this half the refusal above is
    satisfied by a gate that never adjudicates anything again."""
    root = _corpus_with_one_broken_pointer(tmp_path / "repo")
    register = tmp_path / "register.json"
    register.write_text(json.dumps({"known": []}), encoding="utf-8")

    got = _run(str(SYMLINK_CHECK), "--root", str(root), "--subdir", "bd",
               "--baseline", str(register))
    transcript = got.stdout + got.stderr

    assert got.returncode == 1, transcript
    assert "NEW committed pointer" in transcript, transcript
    assert "bd/cell/dangling.lnk" in transcript, transcript
    assert "NOT CHECKED" not in transcript, transcript


def test_symlink_check_passes_when_the_register_records_the_pointer(
        tmp_path: Path) -> None:
    """The negative control the FABRICATE direction needs: with the pointer on
    the record the identical tree is rc 0, so the rc 1 above is attributable to
    the register and not to the corpus."""
    root = _corpus_with_one_broken_pointer(tmp_path / "repo")
    register = tmp_path / "register.json"
    register.write_text(json.dumps({"known": ["bd/cell/dangling.lnk"]}),
                        encoding="utf-8")

    got = _run(str(SYMLINK_CHECK), "--root", str(root), "--subdir", "bd",
               "--baseline", str(register))
    transcript = got.stdout + got.stderr

    assert got.returncode == 0, transcript
    assert "[PASS]" in transcript, transcript
    assert "NOT CHECKED" not in transcript, transcript


def test_symlink_check_write_baseline_bootstraps_but_does_not_overwrite(
        tmp_path: Path) -> None:
    """Creating the register must stay possible; destroying the evidence that
    one was corrupt must not."""
    root = _corpus_with_one_broken_pointer(tmp_path / "repo")

    fresh = tmp_path / "bootstrap.json"
    wrote = _run(str(SYMLINK_CHECK), "--root", str(root), "--subdir", "bd",
                 "--baseline", str(fresh), "--write-baseline")
    assert wrote.returncode == 0, wrote.stdout + wrote.stderr
    assert json.loads(fresh.read_text())["known"] == ["bd/cell/dangling.lnk"]

    corrupt = tmp_path / "corrupt.json"
    truncated = '{"known": ['
    corrupt.write_text(truncated, encoding="utf-8")
    refused = _run(str(SYMLINK_CHECK), "--root", str(root), "--subdir", "bd",
                   "--baseline", str(corrupt), "--write-baseline")
    transcript = refused.stdout + refused.stderr

    assert refused.returncode == 2, transcript
    assert "NOT CHECKED" in transcript, transcript
    assert corrupt.read_text(encoding="utf-8") == truncated
