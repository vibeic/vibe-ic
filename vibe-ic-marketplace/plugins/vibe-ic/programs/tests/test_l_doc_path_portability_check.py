#!/usr/bin/env python3
"""vibe-ic#518 — the gate that keeps an absolute path out of an L document.

``shipped_path_portability_check`` states the doctrine but the landing
sequence points it at the PLUGIN ROOT, so the rule was enforced over
plugin source and never over the artefacts that actually carry the paths.
Two independent live emitters reintroduced it and nothing noticed.

The predicate here is CALIBRATED on the real corpus, and both failure
directions are pinned, because both were measured on the way in:

  * "starts with a slash" FAILs 80 correct values in the tracked corpus —
    8b/10b control-code notation and embedded HDL comment lines;
  * "personal home directory only" (the shape the sibling guard detects)
    MISSES the defect that motivated the gate, because a run under
    ``/tmp`` or a CI run under ``/var`` emits an absolute path with no
    home directory in it.

The fixtures below are verbatim values from the tracked L corpus for the
first, and real emitter output shapes for the second. 8b/10b control-code
notation is technology vocabulary, the same class of literal as "MHz" —
no design, PDK or vendor name appears here. chip-AGNOSTIC.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

from l_doc_path_portability_check import (  # noqa: E402
    absolute_path_reason,
    iter_l_docs,
    scan_tree,
)

_CHECK = _PROGRAMS / "l_doc_path_portability_check.py"
_RUNNER_SRC = _PROGRAMS / "phase1_doc_one_shot_runner.py"

# ── Verbatim non-path leading-slash values from the tracked L corpus. ──
# Every one of these is in a real L document today and every one must stay
# clean, or the gate cannot be enabled at all.
CORPUS_NON_PATH_VALUES = [
    # 8b/10b ordered sets and control characters
    "/K28.5/", "/K23.7/", "/K27.7/", "/K29.7/", "/K30.7/",
    "/I1/", "/I2/", "/A/", "/C/", "/F/", "/K/", "/Q/", "/R/", "/S/",
    "/T/", "/V/", "/WP",
    "/K/(K28.5)", "/R/(K28.0)", "/A/(K28.3)", "/Q/(K28.4)", "/F/(K28.7)",
    "/K28.5/ /D5.6/", "/K28.5/ /D16.2/",
    "/K28.5/ /D21.5/+Config, /K28.5/ /D2.2/+Config",
    "/R/(K28.0) ... /A/(K28.3)",
    "/R/(K28.0) /Q/(K28.4) <link config octets + FCHK> ... /A/(K28.3)",
    "/I/ idle", "/S/ Start_of_Packet", "/T/ Terminate", "/R/ Carrier_Extend",
    "/C/ (Config_Reg) during Auto-Negotiation",
    "/T/ Terminate then /R/ Carrier_Extend close the frame.",
    "/S/ replaces the first preamble octet at Start_of_Packet.",
    "/A/ at multiframe and /F/ at frame boundaries maintain alignment (204B).",
    "/HOLD or /RESET",
    # table headings
    "/ 14", "/ 18", "/ 29 bit identifier",
    "/ 6        0.625      Receive 10       1.25 / 0",
    "/ 22      8.75     Send 10        8.75 / 6.25",
    # embedded HDL / C comment lines
    "/* End of Test Data */",
    "/* ************************* DECLARATIONS ************************ */",
    "/* CRC16 Polynomial, logically inverted 0x1021 for x^16+x^15+x^5+x^0 */",
    "// not in HDR Mode",
    "// Restart is from SCL then rising",
    "// so uses one common clock in scan.",
]

# ── Real non-portable provenance shapes. ──
CORPUS_ABSOLUTE_PATHS = [
    # the two published shapes
    "/home/someuser/vibe-ic/benchmark-data/ic/x/input/constraints/clock.sdc",
    "/home/someuser/work/_bench/x/input/constraints/constraint.sdc",
    # what the emitters actually produced on a scratch / CI run — NO home
    # directory, which is exactly what a home-only predicate misses
    "/tmp/scratch-1000/run/design/phase1/input_doc/verification.txt",
    "/var/lib/ci/workspace/build-1234/design/phase1/input_doc/spec.txt",
    "/Users/someuser/proj/phase1/input_doc/spec.txt",
    "C:\\Users\\someuser\\proj\\phase1\\input_doc\\spec.txt",
]


def _mk_l_doc(project: Path, name: str, payload: dict) -> Path:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    p = gd / name
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_CHECK), str(root), *extra],
        capture_output=True, text=True)


# ────────────────────────────────────── the predicate, both directions ──
@pytest.mark.parametrize("value", CORPUS_NON_PATH_VALUES)
def test_corpus_non_path_values_are_not_flagged(value):
    """Calibration regression.

    Every value here is in a tracked L document. A predicate that flags any
    of them cannot be turned on, and 'starts with a slash' flags 80 of
    them."""
    assert absolute_path_reason(value) is None, (
        f"{value!r} is 8b/10b notation or a comment line, not a filesystem "
        f"path — flagging it would FAIL a correct document")


@pytest.mark.parametrize("value", CORPUS_ABSOLUTE_PATHS)
def test_real_absolute_provenance_paths_are_flagged(value):
    assert absolute_path_reason(value) is not None, (
        f"{value!r} is a non-portable absolute path and was not detected")


def test_a_non_home_absolute_path_is_caught():
    """The clause a home-only predicate would not have.

    The defect that motivated this gate was emitted under /tmp. Restricting
    the rule to `shipped_path_portability_check`'s personal-home shape
    catches 3 of 5 known-bad values and misses the actual one."""
    value = "/tmp/scratch/run/design/phase1/input_doc/verification.txt"
    reason = absolute_path_reason(value)
    assert reason is not None, (
        "a /tmp provenance path was not detected — the predicate has "
        "collapsed to the personal-home shape and no longer covers the "
        "defect it was built for")
    assert "home" not in reason, (
        f"expected the structural clause to fire, got {reason!r}")


def test_relative_paths_are_never_flagged():
    for value in ("phase1/input_doc/a.txt", "input/constraints/clock.sdc",
                  "input/docs/spec.rst", "<outside-project>/spec.txt"):
        assert absolute_path_reason(value) is None, value


# ─────────────────────────────────────────── the gate, end to end ──
def test_fires_on_an_absolute_path_planted_in_an_l_doc(tmp_path):
    _mk_l_doc(tmp_path, "L22_VERIFICATION_PLAN.json", {
        "fields": {"coverage_goals": [
            {"name": "coverage", "target_pct": 100.0,
             "source": "/tmp/somewhere/run/design/phase1/input_doc/v.txt",
             "line": 86},
        ]},
    })
    cp = _run(tmp_path)
    assert cp.returncode == 1, (
        f"an L document carrying an absolute path did not FAIL the gate.\n"
        f"stdout: {cp.stdout}\nstderr: {cp.stderr}")
    assert "L22_VERIFICATION_PLAN.json" in cp.stdout
    assert "coverage_goals.[0].source" in cp.stdout, cp.stdout


def test_does_not_fire_on_relative_paths(tmp_path):
    _mk_l_doc(tmp_path, "L22_VERIFICATION_PLAN.json", {
        "fields": {"coverage_goals": [
            {"name": "coverage", "target_pct": 100.0,
             "source": "phase1/input_doc/v.txt", "line": 86},
        ]},
    })
    cp = _run(tmp_path)
    assert cp.returncode == 0, f"{cp.stdout}\n{cp.stderr}"
    assert "PASS" in cp.stdout


def test_finds_the_path_at_any_depth_and_names_it(tmp_path):
    """Nested lists and dicts — provenance is not always at the top level."""
    _mk_l_doc(tmp_path, "L8_RTL_CONSTANTS.json", {
        "clock_domains": [
            {"name": "clk"},
            {"name": "clk2",
             "evidence": "/var/lib/ci/build/design/input/constraints/c.sdc"},
        ],
    })
    cp = _run(tmp_path)
    assert cp.returncode == 1, cp.stdout
    assert "clock_domains.[1].evidence" in cp.stdout, cp.stdout


def test_a_run_report_beside_the_l_docs_is_never_read(tmp_path):
    """The false-positive population, structurally excluded.

    464 tracked JSON files under benchmark-data carry a personal home path;
    every one is a benchmark RUN OUTPUT recording where a run happened,
    which is provenance rather than a defect. The gate must not open them."""
    _mk_l_doc(tmp_path, "L22_VERIFICATION_PLAN.json",
              {"fields": {"coverage_goals": []}})
    reports = tmp_path / "reports" / "phase1"
    reports.mkdir(parents=True)
    (reports / "cocotb_score.json").write_text(
        json.dumps({"log": "/home/someuser/runs/build-9/sim.log"}),
        encoding="utf-8")
    (tmp_path / "phase1" / "generated_docs" / "extraction_patterns.json"
     ).write_text(json.dumps({"root": "/home/someuser/runs/build-9"}),
                  encoding="utf-8")

    read = {p.name for p in iter_l_docs(tmp_path)}
    assert read == {"L22_VERIFICATION_PLAN.json"}, (
        f"the gate opened something that is not an L document: {read}")
    cp = _run(tmp_path)
    assert cp.returncode == 0, (
        f"a run report or a non-L JSON beside the L documents was scanned:\n"
        f"{cp.stdout}")


def test_only_generated_docs_l_files_are_in_scope(tmp_path):
    """Both halves of the scope matter: the directory AND the name."""
    _mk_l_doc(tmp_path, "L1_DATASHEET.json", {"a": "phase1/x.txt"})
    gd = tmp_path / "phase1" / "generated_docs"
    (gd / "summary.json").write_text(
        json.dumps({"p": "/home/someuser/a/b/c"}), encoding="utf-8")
    elsewhere = tmp_path / "phase2"
    elsewhere.mkdir()
    (elsewhere / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"p": "/home/someuser/a/b/c"}), encoding="utf-8")

    assert {p.name for p in iter_l_docs(tmp_path)} == {"L1_DATASHEET.json"}
    assert _run(tmp_path).returncode == 0


def test_symlinked_generated_docs_is_counted_once(tmp_path):
    """A design may expose its documents twice.

    The legacy root-level `generated_docs` is routinely a symlink to
    `phase1/generated_docs` — one corpus design carries exactly that, and
    before the dedup it lifted the census from 2554 to 2582 and would have
    reported every finding twice."""
    _mk_l_doc(tmp_path, "L1_DATASHEET.json",
              {"evidence": "/var/lib/ci/build/design/input/spec.txt"})
    (tmp_path / "generated_docs").symlink_to(
        tmp_path / "phase1" / "generated_docs", target_is_directory=True)

    rep = scan_tree(tmp_path)
    assert rep["documents_read"] == 1, (
        f"the same document was counted {rep['documents_read']} times — a "
        f"denominator that counts symlinks twice measures nothing")
    assert rep["count"] == 1, rep["findings"]


def test_empty_scan_is_vacuous_not_a_pass(tmp_path):
    """A clean verdict over nothing is how a gate ends up measuring nothing."""
    (tmp_path / "phase1").mkdir()
    cp = _run(tmp_path)
    assert cp.returncode == 2, (
        f"scanning zero L documents exited {cp.returncode}; a PASS with no "
        f"denominator cannot be told apart from a wrong root")
    assert "VACUOUS" in cp.stdout


def test_census_is_always_reported(tmp_path):
    _mk_l_doc(tmp_path, "L1_DATASHEET.json", {"a": "input/docs/x.txt"})
    _mk_l_doc(tmp_path, "L2_FRS.json", {"a": "input/docs/y.txt"})
    rep = scan_tree(tmp_path)
    assert rep["documents_read"] == 2, rep
    cp = _run(tmp_path)
    assert "2 L document(s) examined" in cp.stdout, cp.stdout


def test_unreadable_document_is_reported_not_silently_skipped(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text("{not json", encoding="utf-8")
    rep = scan_tree(tmp_path)
    assert rep["documents_read"] == 1
    assert rep["unreadable"], "an unparseable L document vanished silently"


def test_json_report_is_written(tmp_path):
    _mk_l_doc(tmp_path, "L1_DATASHEET.json",
              {"evidence": "/var/lib/ci/build/design/input/spec.txt"})
    out = tmp_path / "reports" / "portability.json"
    cp = _run(tmp_path, "--json", str(out))
    assert cp.returncode == 1
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL" and rep["count"] == 1
    assert rep["findings"][0]["pointer"] == "evidence"


def test_missing_root_is_an_argument_error(tmp_path):
    cp = _run(tmp_path / "nope")
    assert cp.returncode == 2


# ───────────────────────────────────────────────────── the wiring ──
def _main_body() -> ast.FunctionDef:
    tree = ast.parse(_RUNNER_SRC.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("phase1_doc_one_shot_runner.main() not found")


def _blocking_gate_names() -> list:
    """The gate names in main()'s blocking post-emit gate tuple."""
    for node in ast.walk(_main_body()):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "_SEMANTIC_LAYER_GATES":
                return [e.elts[0].value for e in node.value.elts]
    raise AssertionError("_SEMANTIC_LAYER_GATES not found in main()")


def test_the_gate_is_wired_into_the_runner():
    """A gate nothing runs is not a gate.

    The rule was already implemented and already enforced — over plugin
    source, by `shipped_path_portability_check <plugin-root>`. Being
    implemented is what it was; being pointed at the artefacts is the fix."""
    names = _blocking_gate_names()
    assert "l_doc_path_portability_check" in names, (
        f"the L-doc portability gate is not in the runner's blocking "
        f"post-emit gate list; found {names}")


def test_the_gate_file_exists_where_the_runner_looks_for_it():
    """The runner resolves `<programs>/<gate_name>.py` — a name that does
    not resolve is skipped in SILENCE by the loop's `continue`."""
    assert _CHECK.is_file(), f"{_CHECK} is missing"


def test_the_gate_speaks_the_cli_the_runner_loop_uses(tmp_path):
    """`[python, gate.py, project, --json, report]`, rc 1 == blocking."""
    _mk_l_doc(tmp_path, "L22_VERIFICATION_PLAN.json",
              {"fields": {"coverage_goals": [
                  {"source": "/var/lib/ci/b/design/phase1/input_doc/v.txt"}]}})
    out = tmp_path / "reports" / "phase1" / "l_doc_path_portability.json"
    cp = subprocess.run(
        [sys.executable, str(_CHECK), str(tmp_path), "--json", str(out)],
        capture_output=True, text=True, timeout=60)
    assert cp.returncode == 1, (
        f"the runner treats rc==1 as blocking; got {cp.returncode}")
    assert out.is_file(), "the runner writes the report path it passes in"
