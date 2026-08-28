"""Tests for the cocotb-2.0.1 scorer fix in score_cocotb_mcp.py.

Two coupled gaps, fixed in the scorer (our disclosed §3 substitution adapter),
NEVER in the hidden per-project harness:

  Layer 1 — cocotb 2.0.1 runner.py L508 does `int(os.getenv("WAVES", waves))`.
    The nvidia/cvdp-sim harness (written for cocotb 1.x) passes waves=None when
    WAVE is unset, so int(None) -> TypeError before any test runs (TESTS=0). The
    scorer now exports WAVES=0/GUI=0 so int() always sees "0".

  Layer 2 — after the functional tests run+pass, the xcelium coverage gate
    (covt_report_check()/imc reading /code/rundir/coverage.log) crashes under the
    icarus substitution, swallowing pytest's TESTS= line. The scorer now reads
    cocotb's OWN results.xml (flushed BEFORE the coverage step) as the
    authoritative functional verdict, and records the coverage crash as a
    SEPARATE, non-blocking coverage-only Cat-D `coverage_gate` field — so a
    genuine functional PASS is no longer masked.

Honesty: the parser scans ONLY cocotb-emitted XML under the scorer's work_dir
and the coverage classifier scans ONLY the scorer stdout/stderr — never
score/src/harness_library.py or test_runner.py. The blind rule holds.

PART 1/2 (parser + classifier unit tests) are pure-python and ALWAYS run.
PART 3 (end-to-end) requires the vibeic-eda container and skips cleanly otherwise.
"""
import importlib.util
import shutil
import subprocess
import json
from pathlib import Path

import pytest

from _hostpaths import require_corpus

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_cocotb_mcp.py")


def _load():
    spec = importlib.util.spec_from_file_location("score_cocotb_mcp", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk_cocotb_work(tmp_path: Path) -> Path:
    w = tmp_path / "cocotb_work"
    (w / "sim_build").mkdir(parents=True)
    return w


# ---------------------------------------------------------------------------
# PART 1 — _parse_cocotb_results_xml (pure python, always runs)
# ---------------------------------------------------------------------------

def test_passing_bare_testcase(tmp_path):
    mod = _load()
    w = _mk_cocotb_work(tmp_path)
    (w / "sim_build" / "test_foo.result.xml").write_text(
        '<testsuites><testsuite>'
        '<testcase classname="test_foo" name="test_foo"/>'
        '</testsuite></testsuites>')
    assert mod._parse_cocotb_results_xml(w) == (1, 1, 0, 0)


def test_failing_testcase_with_failure_child(tmp_path):
    mod = _load()
    w = _mk_cocotb_work(tmp_path)
    (w / "sim_build" / "test_foo.result.xml").write_text(
        '<testsuites><testsuite>'
        '<testcase classname="t" name="t"><failure error_type="x"/></testcase>'
        '</testsuite></testsuites>')
    assert mod._parse_cocotb_results_xml(w) == (1, 0, 1, 0)


def test_error_child_counts_as_failed(tmp_path):
    mod = _load()
    w = _mk_cocotb_work(tmp_path)
    (w / "sim_build" / "test_foo.result.xml").write_text(
        '<testsuites><testsuite>'
        '<testcase classname="t" name="t"><error/></testcase>'
        '</testsuite></testsuites>')
    assert mod._parse_cocotb_results_xml(w) == (1, 0, 1, 0)


def test_skipped_child(tmp_path):
    mod = _load()
    w = _mk_cocotb_work(tmp_path)
    (w / "sim_build" / "test_foo.result.xml").write_text(
        '<testsuites><testsuite>'
        '<testcase classname="t" name="t"><skipped/></testcase>'
        '</testsuite></testsuites>')
    assert mod._parse_cocotb_results_xml(w) == (1, 0, 0, 1)


def test_legacy_results_xml_name(tmp_path):
    """cocotb's default/legacy file name in the run cwd (no sim_build)."""
    mod = _load()
    w = tmp_path / "cocotb_work"
    w.mkdir(parents=True)
    (w / "results.xml").write_text(
        '<testsuites><testsuite>'
        '<testcase classname="t" name="t"/>'
        '</testsuite></testsuites>')
    assert mod._parse_cocotb_results_xml(w) == (1, 1, 0, 0)


def test_dedup_across_two_files(tmp_path):
    """Same (classname,name) in both sim_build/*.result.xml and results.xml
    counts ONCE — no double counting."""
    mod = _load()
    w = _mk_cocotb_work(tmp_path)
    xml = ('<testsuites><testsuite>'
           '<testcase classname="t" name="t"/>'
           '</testsuite></testsuites>')
    (w / "sim_build" / "test_t.result.xml").write_text(xml)
    (w / "results.xml").write_text(xml)
    assert mod._parse_cocotb_results_xml(w) == (1, 1, 0, 0)


def test_returns_none_when_no_xml(tmp_path):
    mod = _load()
    w = _mk_cocotb_work(tmp_path)
    assert mod._parse_cocotb_results_xml(w) is None


def test_non_xml_results_xml_is_skipped_not_crash(tmp_path):
    """A Vibe-IC sim/results.xml is JSON, not cocotb XML. If one lands under
    work_dir it must be skipped (ParseError guard), NOT crash the scorer."""
    mod = _load()
    w = tmp_path / "cocotb_work"
    w.mkdir(parents=True)
    (w / "results.xml").write_text('{"verdict":"PASS"}')
    assert mod._parse_cocotb_results_xml(w) is None


def test_mixed_pass_fail_skip(tmp_path):
    mod = _load()
    w = _mk_cocotb_work(tmp_path)
    (w / "sim_build" / "test_mix.result.xml").write_text(
        '<testsuites><testsuite>'
        '<testcase classname="m" name="a"/>'
        '<testcase classname="m" name="b"><failure/></testcase>'
        '<testcase classname="m" name="c"><skipped/></testcase>'
        '</testsuite></testsuites>')
    assert mod._parse_cocotb_results_xml(w) == (3, 1, 1, 1)


# ---------------------------------------------------------------------------
# PART 2 — coverage-gate classifier + harness-error interaction (always runs)
# ---------------------------------------------------------------------------

def test_detect_coverage_gate_matches_coverage_log():
    mod = _load()
    out = "FileNotFoundError: [Errno 2] No such file or directory: '/code/rundir/coverage.log'"
    assert mod._detect_coverage_gate(out) == "coverage.log"


def test_detect_coverage_gate_matches_imc():
    mod = _load()
    assert mod._detect_coverage_gate("Running command imc -load /code/rundir/...") == "imc"


def test_detect_coverage_gate_matches_covt_report_check():
    mod = _load()
    sig = mod._detect_coverage_gate("hrs_lb.covt_report_check()\nfoo")
    assert sig == "covt_report_check"


def test_detect_coverage_gate_false_on_clean_log():
    mod = _load()
    assert mod._detect_coverage_gate("1 passed in 0.39s\nall ok") is None


def test_harness_error_short_circuits_when_tests_gt_zero():
    """The single most important ordering rule: once results.xml proves the
    functional tests ran (tests>0), a coverage-gate crash (even one carrying the
    old WAVES TypeError text) is NOT a blocking harness error."""
    mod = _load()
    out = ("...coverage.log... TypeError: int() argument must be a string, "
           "a bytes-like object or a real number, not 'NoneType'")
    assert mod._detect_harness_error(out, tests=1, returncode=1) is None


def test_harness_error_still_fires_when_tests_zero():
    """Backward-compat: a genuine pre-test harness crash (tests==0) is still
    classified Cat-D."""
    mod = _load()
    out = ("E       TypeError: int() argument must be a string, a bytes-like "
           "object or a real number, not 'NoneType'")
    he = mod._detect_harness_error(out, tests=0, returncode=1)
    assert he is not None and he["kind"] == "cocotb-tools-typeerror"


def test_harness_error_detects_float_coercion_pretest():
    """Safety net: a harness float(os.getenv("TARGET")) crash with no TARGET set
    that fires BEFORE any test ran is classified Cat-D, not left unknown."""
    mod = _load()
    out = ("E       TypeError: float() argument must be a string or a real "
           "number, not 'NoneType'")
    he = mod._detect_harness_error(out, tests=0, returncode=1)
    assert he is not None and he["kind"] == "harness-float-coercion-typeerror"


def test_float_coercion_short_circuits_when_tests_gt_zero():
    """A float() coercion crash INSIDE the coverage gate (after functional tests
    passed, tests>0) is NOT a blocking harness error — it is a coverage-only
    Cat-D handled by the coverage_gate field."""
    mod = _load()
    out = ("hrs_lb.covt_report_check()\n"
           "TypeError: float() argument must be a string or a real number, "
           "not 'NoneType'")
    assert mod._detect_harness_error(out, tests=1, returncode=1) is None
    # ...but the coverage gate is still detected (covt_report_check token).
    assert mod._detect_coverage_gate(out) == "covt_report_check"


# ---------------------------------------------------------------------------
# PART 3 — end-to-end: coverage-gate crash must NOT mask a functional PASS
#          (requires the vibeic-eda container; skips cleanly otherwise)
# ---------------------------------------------------------------------------

def _need_iic_eda():
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    # --type=container: a bare `docker inspect vibeic-eda` also resolves the
    # IMAGE of that name, so on any host with the image pulled this guard
    # passed and the test failed inside `docker exec` instead of skipping.
    r = subprocess.run(["docker", "inspect", "--type=container",
                        "-f", "{{.State.Running}}", "vibeic-eda"],
                       capture_output=True, text=True)
    if r.returncode != 0 or r.stdout.strip() != "true":
        pytest.skip("vibeic-eda container not available or not running")


def _find_encoder_project():
    """Resolve a priority_encoder Shape-D project on the host, version-agnostic.
    Skips if none present so the test stays host-portable (no hardcoded version)."""
    root = require_corpus()
    cands = sorted(root.glob("_vibeic_cvdp_v*/cvdp_agentic_8x3_priority_encoder_0003"))
    if not cands:
        pytest.skip("no priority_encoder Shape-D project on host")
    return cands[-1]


def test_priority_encoder_functional_pass_with_coverage_gate_flagged(tmp_path):
    _need_iic_eda()
    proj = _find_encoder_project()
    r = _pr.run(
        ["python3", str(SCRIPT), "--project", str(proj),
         "--top", "priority_encoder_8x3",
         "--mount-root", str(require_corpus())],
        capture_output=True, text=True)
    score_json = proj / "reports" / "cocotb_score.json"
    assert score_json.is_file(), r.stdout + r.stderr
    d = json.loads(score_json.read_text())
    # The functional cocotb test passes (from results.xml), the coverage gate is
    # flagged but non-blocking, and the overall verdict is NOT masked to FAIL.
    assert d["functional_verdict"] == "PASS", d
    assert d["functional_source"] == "results.xml", d
    assert d["coverage_gate"] is not None and d["coverage_gate"]["detected"] is True, d
    assert d["coverage_gate"]["blocking"] is False, d
    assert d["verdict"] == "PASS", d
    assert d["harness_error"] is None, d
