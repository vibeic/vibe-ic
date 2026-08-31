"""A red landing lane must NAME what went red, not only count it.

MEASURED, twice, on the 2026-08-31 full tiers (trees 7d1acc6e85 and 411c0ac735,
same image digest, same orchestrator):

  * `targeted tests (119 file(s))` reported `aggregate complete rc=1 cases=3324
    red=89` and printed NOT ONE node id. The earlier run, whose aggregate
    TRUNCATED at its failure bound, printed 136 `TRUNCATED_RED` lines carrying
    117 unique ids. So the run that measured MORE said LESS: the names reach
    the log only on the truncated path, and the only other copy was the
    `mktemp` merged JUnit, which `docker run --rm` destroyed with the container.
  * `repo tools tests (65 file(s))` reported `NORECORD 2` in BOTH runs, and
    neither log names either file. `run_repo_tools_pytest` and
    `run_unselectable_pytest` printed `tail -6` of the driver's stdout, and
    `tail -6` is exactly the six lines of the summary block, so the `NORECORD`
    lines the driver prints ABOVE it -- the one thing a reader of a 143-file run
    cannot reconstruct from a tail -- were computed and thrown away. (They are
    `tools/ci/test_dispatch_shell_harnesses.py` and
    `tools/test_gatekeeper_land_lanes.py`; recovering them cost a re-run.)

`GATEKEEPER_PYTEST_JUNIT` / `GATEKEEPER_REPO_TOOLS_JUNIT` /
`GATEKEEPER_UNSELECTABLE_JUNIT` already let a caller KEEP the report, and the
landing orchestrator did not pass them. A record that exists only when somebody
remembers an environment variable is not a record, which is why the fix is in
the two places that always run.

This file lives under `tools/` so the repo-tools lane covers it.
"""
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_LAND = _ROOT / "tools" / "gatekeeper-land.sh"
_DRIVER = (_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
           / "pytest_per_file_junit.py")
_ENTRY = _DRIVER.parent / "trusted_pytest_entry.py"
_LANES = ("run_pytest", "run_repo_tools_pytest", "run_unselectable_pytest")


def _src() -> list:
    return _LAND.read_text(encoding="utf-8").splitlines()


def _extract_fn(name: str) -> str:
    """Pull `name() { ... }` out of the script, brace-matched at column 0."""
    src = _src()
    start = next(i for i, l in enumerate(src) if l.startswith(f"{name}() {{"))
    end = next(i for i in range(start + 1, len(src)) if src[i] == "}")
    return "\n".join(src[start:end + 1])


def _trusted_runtime_available() -> bool:
    probe = subprocess.run([sys.executable, "-I", "-c", "import pytest"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)
    return probe.returncode == 0


_NEEDS_TRUSTED_RUNTIME = pytest.mark.skipif(
    not _trusted_runtime_available(),
    reason=("the protected landing runtime is unavailable on this host: "
            "`python3 -I` cannot import pytest. UNVERIFIED here, not verified "
            "— run it in the digest-pinned runner image."))


# ── the shared reporter, driven ───────────────────────────────────────────

_SYNTHETIC = "\n".join([
    "=== [aggregate] 2 file(s) in one pytest process",
    "NORECORD  tools/test_a.py  session finished before every selected item "
    "completed (1/2) — this file's result is UNKNOWN, not clean",
    "RED  tools.test_b::test_that_went_red",
    "some noise the reader does not need",
    "=== pytest junit summary",
    "  mode       aggregate-first",
    "  asked      2",
    "  recorded   1",
    "  NORECORD   1",
    "  NOTRUN     0",
    "  red cases  1",
])


def _run_reporter(out: str):
    script = ("set -uo pipefail\n" + _extract_fn("lane_report_out") + "\n"
              'lane_report_out "$1"\n')
    # NO `timeout=`. `ci_harness_timeout_ceiling_check` scans `tools/` with its
    # narrow glob and MEASURED two 600 s bounds in the first draft of this file:
    # a fixed elapsed bound in a test is an elapsed verdict, which is the one
    # thing this harness refuses ("elapsed time is not a test verdict"). The
    # sibling `test_repo_tools_tests_gate.py` drives the same script the same
    # way and passes no bound either.
    p = subprocess.run(["bash", "-c", script, "reporter", out],
                       capture_output=True, text=True)
    return p.stdout


def test_the_reporter_prints_the_norecord_name_and_the_red_name():
    """The two classes a tail can never recover, both present."""
    got = _run_reporter(_SYNTHETIC)
    assert "tools/test_a.py" in got, got
    assert "tools.test_b::test_that_went_red" in got, got


def test_the_reporter_still_prints_the_summary_block():
    """The counts a reader already relies on are NOT replaced by the names."""
    got = _run_reporter(_SYNTHETIC)
    assert "red cases  1" in got, got
    assert "NORECORD   1" in got, got


def test_the_reporter_keeps_the_write_guards_own_verdict():
    """MEASURED 2026-08-31: `unselectable tests` FAILED three landing tiers with
    `aggregate complete rc=1 cases=1341 red=0` — a refusal with no red case
    behind it. The only things in this tree that set a session status with a
    green XML are `suite_write_guard` and `not_verified_tier`, and the guard
    PRINTS the offending paths. `tail -6` is the summary block, so the paths
    never reached the log and the cause had to be chased with a `git status`
    watcher across a whole instrumented tier."""
    guarded = "\n".join([
        "[FAIL] suite_write_guard: this pytest session wrote 1 path(s) that "
        "`git add -A` would ship:",
        "    vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md",
        "    ^ written by tests/test_x.py::test_y: programs/INDEX.md",
        "=== pytest junit summary",
        "  red cases  0",
        "  aggregate  complete rc=1 cases=1341 red=0",
    ])
    got = _run_reporter(guarded)
    assert "suite_write_guard" in got, got
    assert "INDEX.md" in got, got


def test_the_reporter_is_silent_about_names_when_there_are_none():
    """CONTROL. A lane that fails for a reason with no per-case name must not
    grow invented `RED`/`NORECORD` lines — otherwise the assertions above pass
    on a reporter that prints its input twice."""
    quiet = "\n".join(["=== pytest junit summary", "  red cases  0",
                       "  aggregate  complete rc=1 cases=10 red=0"])
    got = _run_reporter(quiet)
    assert "RED  " not in got, got
    assert "NORECORD  " not in got, got
    assert "suite_write_guard" not in got, got
    assert "red cases  0" in got, got


# ── every lane uses it, and none of them tails on its own ─────────────────

def test_every_pytest_lane_reports_through_the_shared_reporter():
    for fn in _LANES:
        body = _extract_fn(fn)
        assert "lane_report_out " in body, (
            f"{fn} does not report through lane_report_out, so its NORECORD "
            f"and RED names go nowhere — that is the hole this file closes")


def test_no_lane_tails_the_driver_output_on_its_own():
    """STRUCTURAL, and it is the half that keeps the hole from reopening in ONE
    lane. `tail -6` on the driver's stdout is exactly the summary block; a lane
    that goes back to doing its own tail silently drops the names again."""
    offenders = []
    for fn in _LANES:
        for line in _extract_fn(fn).splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r'"\$out"\s*\|\s*tail', stripped):
                offenders.append(f"{fn}: {stripped}")
    assert not offenders, offenders


# ── the driver half, for real ─────────────────────────────────────────────

@_NEEDS_TRUSTED_RUNTIME
def test_the_driver_names_every_red_case_without_truncating(tmp_path):
    """The behavioural arm, and the one that was red before this change.

    A selection whose failure count is BELOW the driver's own failure bound
    completes — which is exactly the shape that used to print no name at all.
    """
    work = tmp_path / "w"
    (work / "t").mkdir(parents=True)
    (work / "t" / "test_green.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    (work / "t" / "test_red.py").write_text(
        "def test_this_one_is_red():\n    assert False\n", encoding="utf-8")
    sel = tmp_path / "sel.txt"
    sel.write_text("t/test_green.py\nt/test_red.py\n", encoding="utf-8")
    junit = tmp_path / "merged.xml"
    p = subprocess.run(
        [sys.executable, str(_DRIVER), "--selection", str(sel),
         "--junit", str(junit), "--cwd", str(work), "--aggregate-check",
         "--stop-after-failures", "0",
         "--", sys.executable, "-I", "-B", str(_ENTRY), "-q",
         "-p", "no:cacheprovider"],
        cwd=str(work), capture_output=True, text=True)
    out = p.stdout + p.stderr
    assert "test_this_one_is_red" in out, (
        "the driver measured a red case and never named it:\n" + out)
    assert re.search(r"^RED  .*test_this_one_is_red", out, re.M), out
    # CONTROL: the green case must NOT be named. Printing every case would
    # satisfy the assertion above while saying nothing.
    assert not re.search(r"^RED  .*test_ok", out, re.M), out


@_NEEDS_TRUSTED_RUNTIME
def test_a_fully_green_selection_names_nothing(tmp_path):
    """CONTROL for the arm above: no red case, no `RED` line, rc 0."""
    work = tmp_path / "w"
    (work / "t").mkdir(parents=True)
    (work / "t" / "test_green.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    sel = tmp_path / "sel.txt"
    sel.write_text("t/test_green.py\n", encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(_DRIVER), "--selection", str(sel),
         "--junit", str(tmp_path / "m.xml"), "--cwd", str(work),
         "--aggregate-check", "--stop-after-failures", "0",
         "--", sys.executable, "-I", "-B", str(_ENTRY), "-q",
         "-p", "no:cacheprovider"],
        cwd=str(work), capture_output=True, text=True)
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert not re.search(r"^RED  ", out, re.M), out
