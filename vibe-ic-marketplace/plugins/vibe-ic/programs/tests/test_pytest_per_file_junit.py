"""Unit tests for pytest_per_file_junit.py (vibe-ic#1654).

THE DEFECT, in one sentence: `--timeout-method=thread` cannot interrupt a
blocking `waiter.acquire()`, so pytest-timeout takes the whole PROCESS down and
the process never writes its `--junitxml` — one hanging file therefore used to
cost the entire run's machine-readable record, including files that had already
PASSED.

Pinned here in the order the driver can be wrong:

  * FALSIFIABILITY, both directions and on the same bytes: the SAME three
    fixture files, md5-identical, lose the whole record under one pytest session
    and keep every completed file's record under the driver;
  * a file with no record is NAMED (`NORECORD`) and is kept OUT of the merged
    report — absence is what the merge gate refuses on, and a synthetic red
    would be scored PRE-EXISTING when both arms hang on the same file;
  * the outer bound catches the shape pytest-timeout cannot see at all, a hang
    during module IMPORT, where no test is running for a per-test timer to bound;
  * the merged report is xunit1 and carries the `file` attribute, because that
    is what `landing_merge_verdict` derives the ran-file set from;
  * an empty selection is rc 3 (`the question could not be put`), never rc 0 —
    an empty corpus is not evidence that anything passed;
  * `--stop-after-failures` NAMES what it did not launch instead of leaving it
    to look clean.

Every bound in this file is `_T` (or `_KILL`, which is smaller), which the last
test asserts is inside the ceiling `ci_harness_timeout_ceiling_check` computes —
a test file that policed the corpus while breaking the rule would be its own
counter-example.
"""
import hashlib
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import pytest_per_file_junit as D                              # noqa: E402

_PROG = _PROGRAMS / "pytest_per_file_junit.py"

#: Inner bound for every subprocess this file launches. Each one runs at most
#: three trivial pytest sessions plus one deliberately-killed one, measured at
#: well under 20 s on this host, so 50 s is generous and inside the 60 s ceiling
#: the harness gate publishes for a 180 s lane.
_T = 50

#: The driver's own outer per-file bound inside these tests. Small on purpose:
#: the hanging fixtures below sleep far longer than any of them, so the bound
#: is what ends them, and a test suite that waited out the SHIPPED default would
#: be its own hang.
_KILL = 8

#: pytest-timeout's per-test bound inside these tests. Must be BELOW `_KILL` for
#: the "pytest-timeout fires first" fixture and ABOVE it for the import-hang
#: fixture, which is the whole distinction the two shapes exist to draw.
_INNER_TIMEOUT = 4

_GREEN = "def test_i_am_green():\n    assert 1 == 1\n"

_GREEN_AFTER = "def test_i_am_also_green():\n    assert 2 == 2\n"

#: The #1654 shape verbatim: `Future.result` -> `Condition.wait` ->
#: `waiter.acquire`. `--timeout-method=thread` cannot interrupt it.
_HANGS_IN_TEST = (
    "from concurrent.futures import ThreadPoolExecutor\n"
    "import time\n"
    "\n"
    "\n"
    "def _sleeper():\n"
    "    time.sleep(3600)\n"
    "\n"
    "\n"
    "def test_hangs_in_waiter_acquire():\n"
    "    with ThreadPoolExecutor(max_workers=1) as ex:\n"
    "        ex.submit(_sleeper).result(timeout=3600)\n"
)

#: A hang at module IMPORT. pytest-timeout bounds test EXECUTION, so no per-test
#: timer exists yet and `--timeout` can never fire here at all.
_HANGS_AT_IMPORT = (
    "import time\n"
    "\n"
    "time.sleep(3600)\n"
    "\n"
    "\n"
    "def test_never_reached():\n"
    "    assert True\n"
)

_RED = "def test_i_am_red():\n    assert False\n"


def _tree(tmp_path: Path, files: dict) -> Path:
    """A directory of test files plus the selection naming them, in order."""
    d = tmp_path / "corpus"
    d.mkdir(exist_ok=True)
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    (d / "selection.txt").write_text(
        "".join(f"{n}\n" for n in files), encoding="utf-8")
    return d


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _pytest_cmd():
    """The harness command, pinned the way the landing gate pins it."""
    return [sys.executable, "-m", "pytest", "-q", "-p", "pytest_timeout",
            f"--timeout={_INNER_TIMEOUT}", "--timeout-method=thread",
            "-p", "no:cacheprovider"]


def _run_driver(corpus: Path, junit: Path, *extra):
    return subprocess.run(
        [sys.executable, str(_PROG),
         "--selection", str(corpus / "selection.txt"),
         "--junit", str(junit),
         "--kill-after", str(_KILL), *extra,
         "--"] + _pytest_cmd(),
        cwd=str(corpus), capture_output=True, text=True, timeout=_T)


def _files_in(junit: Path):
    root = ET.parse(str(junit)).getroot()
    return sorted({tc.get("file") for tc in root.iter("testcase")})


# ── the defect, and the fix, on bytes proved identical ───────────────────────

def test_one_session_loses_the_whole_record_and_per_file_does_not(tmp_path):
    """THE BOTH-DIRECTIONS PROOF, on the same tree.

    Arm 1 is what `main` does today: one pytest session, one `--junitxml`. Arm 2
    is the driver. The corpus is built once and its md5s are asserted unchanged
    between the arms, so the difference cannot be the input.
    """
    corpus = _tree(tmp_path, {"test_green_neighbour.py": _GREEN,
                              "test_hangs_like_replay.py": _HANGS_IN_TEST,
                              "test_green_after.py": _GREEN_AFTER})
    before = {p.name: _md5(p) for p in sorted(corpus.glob("test_*.py"))}

    # ---- ARM 1: one session, exactly the shape gatekeeper-land.sh used ----
    single = tmp_path / "single.xml"
    subprocess.run(
        _pytest_cmd() + ["-o", "junit_family=xunit1", f"--junitxml={single}",
                         "test_green_neighbour.py", "test_hangs_like_replay.py",
                         "test_green_after.py"],
        cwd=str(corpus), capture_output=True, text=True, timeout=_T)
    assert not single.exists(), (
        "the single-session arm wrote a junit — the hang fixture no longer "
        "reproduces #1654 and this test proves nothing")

    # ---- ARM 2: the driver, same bytes ----
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)

    after = {p.name: _md5(p) for p in sorted(corpus.glob("test_*.py"))}
    assert before == after, ("the corpus changed between the arms, so the two "
                            f"results are not comparable: {before} vs {after}")

    assert merged.is_file(), proc.stdout + proc.stderr
    got = _files_in(merged)
    assert got == ["test_green_after.py", "test_green_neighbour.py"], got
    assert "test_hangs_like_replay.py" not in got, (
        "the hanging file appears in the merged report — an absent record must "
        "stay absent, or the merge gate stops refusing on it")
    assert proc.returncode == D.RC_NORECORD, proc.stdout


def test_the_file_with_no_record_is_named(tmp_path):
    """`NORECORD  <path>` is the whole point: a 91-file run whose record is
    short by one must say WHICH one, or the reader is back to a stack dump."""
    corpus = _tree(tmp_path, {"test_green_neighbour.py": _GREEN,
                              "test_hangs_like_replay.py": _HANGS_IN_TEST})
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)
    lines = [l for l in proc.stdout.splitlines() if l.startswith("NORECORD")]
    assert len(lines) == 1, proc.stdout
    assert "test_hangs_like_replay.py" in lines[0], lines
    assert "not clean" in lines[0], (
        "the marker must say what the absence MEANS; a bare path reads as a "
        "note rather than as 'this file's result is unknown'")


def test_the_outer_bound_catches_a_hang_pytest_timeout_cannot_see(tmp_path):
    """A hang during module IMPORT.

    pytest-timeout bounds test execution, so this shape has no per-test timer at
    all and `--timeout` can never fire — the process would wait forever. This is
    the case the outer SIGKILL exists for, and it is asserted rather than
    assumed because `--kill-after` looks redundant next to `--timeout`.
    """
    corpus = _tree(tmp_path, {"test_green_neighbour.py": _GREEN,
                              "test_hangs_at_import.py": _HANGS_AT_IMPORT,
                              "test_green_after.py": _GREEN_AFTER})
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)
    assert proc.returncode == D.RC_NORECORD, proc.stdout
    assert _files_in(merged) == ["test_green_after.py",
                                 "test_green_neighbour.py"]
    marker = [l for l in proc.stdout.splitlines() if l.startswith("NORECORD")]
    assert len(marker) == 1 and "test_hangs_at_import.py" in marker[0], marker
    assert f"KILLED at the {_KILL} s outer bound" in marker[0], (
        "the marker must distinguish a KILL at the outer bound from a session "
        "that merely exited without a report — they need different fixes")


# ── the report the merge gate has to be able to read ─────────────────────────

def test_the_merged_report_is_xunit1_and_carries_the_file_attribute(tmp_path):
    """`landing_merge_verdict._file_of` prefers the `file` attribute and only
    falls back to the dotted classname. xunit2 — pytest's default — drops it, so
    a merged report without it cannot answer 'did every selected file run'."""
    corpus = _tree(tmp_path, {"test_green_neighbour.py": _GREEN,
                              "test_green_after.py": _GREEN_AFTER})
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)
    assert proc.returncode == D.RC_OK, proc.stdout
    root = ET.parse(str(merged)).getroot()
    cases = list(root.iter("testcase"))
    assert len(cases) == 2, ET.tostring(root)
    assert all(tc.get("file") for tc in cases), ET.tostring(root)
    # NAMED BY FILE. pytest calls every suite "pytest"; a merged report of N
    # identically-named blocks cannot be read back to its arms.
    assert sorted(s.get("name") for s in root.iter("testsuite")) == [
        "test_green_after.py", "test_green_neighbour.py"]


def test_a_red_test_is_a_red_run_not_a_missing_record(tmp_path):
    """The two must not collapse into each other. An ordinary failure keeps its
    record and reports rc 1; only a missing record reports rc 2."""
    corpus = _tree(tmp_path, {"test_green_neighbour.py": _GREEN,
                              "test_red.py": _RED})
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)
    assert proc.returncode == D.RC_RED, proc.stdout
    assert not [l for l in proc.stdout.splitlines()
                if l.startswith("NORECORD")], proc.stdout
    assert _files_in(merged) == ["test_green_neighbour.py", "test_red.py"]


def test_an_empty_selection_is_refused_and_never_a_pass(tmp_path):
    """An empty corpus is a VACUOUS pass, not a pass — the same rule
    `gatekeeper-land.sh` applies to its own discovery."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "selection.txt").write_text("", encoding="utf-8")
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)
    assert proc.returncode == D.RC_CANNOT_ASK, proc.stdout + proc.stderr
    assert "EMPTY" in proc.stderr.upper()


def test_files_not_launched_are_named_rather_than_looking_clean(tmp_path):
    """`--stop-after-failures` truncates on purpose. A truncated run has no
    failed SET, only a prefix of one, so what it did not launch must be legible
    — `landing_merge_verdict` refuses on exactly that."""
    corpus = _tree(tmp_path, {"test_red.py": _RED,
                              "test_green_after.py": _GREEN_AFTER})
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged, "--stop-after-failures", "1")
    assert proc.returncode == D.RC_RED, proc.stdout
    notrun = [l for l in proc.stdout.splitlines() if l.startswith("NOTRUN")]
    assert len(notrun) == 1 and "test_green_after.py" in notrun[0], proc.stdout
    assert _files_in(merged) == ["test_red.py"], (
        "a file that was never launched must not appear in the report")


# ── the unit-level rules, asked directly ─────────────────────────────────────

@pytest.mark.parametrize("body,why", [
    ("", "an empty file is not a partial answer"),
    ("<testsuites", "a half-written XML left by a killed process"),
    ("<?xml version='1.0'?><testsuites name='pytest tests' />",
     "a well-formed report with no testsuite in it"),
])
def test_every_unreadable_report_is_no_record_not_an_empty_one(tmp_path, body,
                                                               why):
    p = tmp_path / "r.xml"
    p.write_text(body, encoding="utf-8")
    assert D._load_suites(p) is None, why


def test_a_missing_report_is_no_record(tmp_path):
    assert D._load_suites(tmp_path / "absent.xml") is None


def test_the_merge_omits_files_that_have_no_record(tmp_path):
    """Asked of `merge` directly, because this is the property a well-meaning
    change is most likely to 'improve' by inserting a placeholder suite."""
    suite = ET.fromstring(
        "<testsuite name='pytest' tests='1'>"
        "<testcase classname='c' name='t' file='kept.py'/></testsuite>")
    results = [D.FileResult("kept.py", 0, False, [suite], 1, 0),
               D.FileResult("lost.py", None, True, None, 0, 0)]
    out = tmp_path / "m.xml"
    assert D.merge(results, out) == 1
    root = ET.parse(str(out)).getroot()
    assert [s.get("name") for s in root.iter("testsuite")] == ["kept.py"]


# ── the driver is the instrument BOTH arms use ───────────────────────────────

def _repo_root() -> Path:
    return _PROGRAMS.parents[3]


def test_both_landing_arms_run_through_this_driver():
    """#1417's law — a differential is only a differential if the two arms were
    measured the same way. Read off the scripts rather than trusted."""
    root = _repo_root()
    land = root / "tools" / "gatekeeper-land.sh"
    verify = root / "tools" / "gatekeeper-verify-merge.sh"
    if not land.is_file() or not verify.is_file():
        pytest.skip("the landing scripts are not shipped in this tree")
    land_src = land.read_text(errors="replace")
    verify_src = verify.read_text(errors="replace")
    assert "programs/pytest_per_file_junit.py" in land_src, (
        "arm B does not run through the per-file driver, so one hanging file "
        "still costs the candidate's whole record")
    assert "programs/pytest_per_file_junit.py" in verify_src, (
        "arm A1 does not run through the per-file driver; an unmeasurable base "
        "arm is the permissive direction — see vibe-ic#1443")
    assert "xargs -a" not in land_src.split("run_pytest()")[-1].split(
        "run_repo_tools_pytest")[0], (
        "the single-session `xargs` invocation is still in run_pytest")


def test_the_harness_bound_is_still_declared_where_the_gate_reads_it():
    """The pytest command is passed to the driver VERBATIM so `--timeout=180`
    stays in `tools/gatekeeper-land.sh`, which `ci_harness_timeout_ceiling_check`
    lists in `EXTRA_HARNESS_RELS`. A bound moved into Python would vanish from
    that resolver and the ceiling would come from a different file."""
    import ci_harness_timeout_ceiling_check as C
    root = _repo_root()
    if not (root / "tools" / "gatekeeper-land.sh").is_file():
        pytest.skip("the landing scripts are not shipped in this tree")
    bounds = [b for b in C.harness_bounds(root)
              if b.workflow == "gatekeeper-land.sh"]
    assert bounds, (
        "gatekeeper-land.sh no longer declares any pytest harness bound the "
        "ceiling gate can read")
    assert min(b.seconds for b in bounds) == 180, [b.as_dict() for b in bounds]


def test_this_files_own_bounds_are_inside_the_ceiling():
    import ci_harness_timeout_ceiling_check as C
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no repo root in reach")
    ceiling = C.inner_timeout_ceiling(root)
    if ceiling is None:
        pytest.skip("no harness bound in reach")
    assert _T <= ceiling, (_T, ceiling)
    assert _KILL <= ceiling, (_KILL, ceiling)
