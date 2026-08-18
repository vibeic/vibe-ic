#!/usr/bin/env python3
"""Tests for reported_figure_artifact_backing_check.py — the artifact-backing gate.

These tests drive the program through its PUBLIC surface only: the CLI (argv,
stdout, exit code) and the `--json` verdict document. No test reaches into a
regex, a helper, or an internal data structure, so the implementation stays free
to change as long as the observable behaviour holds.

The four load-bearing fixtures, all built from the MEASURED 2026-07-21 defect:

  (1) FAIL  a report quoting a byte size no file has        -> UNBACKED_FIGURE
  (2) FAIL  an input-only run dir with a verdict reported   -> NO_OUTPUTS_ONLY_INPUTS
  (3) FAIL  a figure that resolves only in a SIBLING run    -> CROSS_RUN_IMPORT
  (4) PASS  a report whose every figure resolves at home    -> BACKED / rc 0

Fixture (4) is not optional: a checker that cannot return clean is an alarm,
not a checker. Several tests below exist purely to keep the gate from becoming
one — they assert it stays SILENT on legitimately-clean reports.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent
        / "reported_figure_artifact_backing_check.py")


def _run(args: list) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + [str(a) for a in args],
                          capture_output=True, text=True)


def _verdict(args: list, tmp_path: Path) -> dict:
    """Run the CLI and return the parsed --json verdict document."""
    out = tmp_path / f"verdict_{abs(hash(tuple(map(str, args))))}.json"
    r = _run(list(args) + ["--json", out])
    assert out.is_file(), f"no verdict json written; stdout={r.stdout}\n{r.stderr}"
    d = json.loads(out.read_text())
    d["_rc"] = r.returncode
    d["_stdout"] = r.stdout
    return d


# ---------------------------------------------------------------------------
# Fixture builders — a "run dir" is just a directory layout, no IC involved.
# ---------------------------------------------------------------------------
def _make_run(root: Path, name: str, *, gds_bytes: int | None = None,
              drc_items: int = 0, with_inputs: bool = True) -> Path:
    """A run dir with real artifacts: a GDS of an EXACT byte size and a KLayout
    DRC report-database carrying exactly `drc_items` <item> elements."""
    run = root / name
    (run / "phase3" / "gds").mkdir(parents=True, exist_ok=True)
    if with_inputs:
        (run / "input" / "docs").mkdir(parents=True, exist_ok=True)
        for i in range(3):
            (run / "input" / "docs" / f"L{i}.md").write_text(f"spec {i}\n")
    if gds_bytes is not None:
        (run / "phase3" / "gds" / "top.gds").write_bytes(b"\0" * gds_bytes)
    items = "\n".join("  <item><value>v</value></item>" for _ in range(drc_items))
    (run / "phase3" / "drc.rpt").write_text(
        "<?xml version='1.0'?>\n<report-database>\n"
        "<description>deck</description>\n<items>\n" + items + "\n</items>\n"
        "</report-database>\n")
    return run


def _input_only_run(root: Path, name: str) -> Path:
    """The caravel shape: every file confined to input/, zero outputs."""
    run = root / name
    (run / "input" / "docs").mkdir(parents=True, exist_ok=True)
    for i in range(27):
        (run / "input" / "docs" / f"L{i}.md").write_text(f"spec {i}\n")
    return run


def _report(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


# ---------------------------------------------------------------------------
# (4) THE CONTROL THAT ACTUALLY CONTROLS — a clean report returns CLEAN.
# ---------------------------------------------------------------------------
def test_report_whose_every_figure_resolves_is_clean(tmp_path):
    run = _make_run(tmp_path, "run_a", gds_bytes=4096, drc_items=0)
    _report(run / "RESULT.md",
            "# RESULT\n\n"
            "GDS `top.gds` is 4096 B.\n"
            "DRC violations: 0\n"
            "LVS: PASS\n")
    (run / "phase3" / "lvs.rpt").write_text("lvs comparison result: PASS\n")

    d = _verdict([run], tmp_path)
    assert d["_rc"] == 0
    assert d["verdict"] == "CLEAN"
    assert d["state"] == "BACKED"
    assert d["evidence"]["figures_unresolved"] == 0
    assert d["evidence"]["figures_imported"] == 0
    assert d["evidence"]["figures_resolved"] >= 2


def test_clean_run_names_the_artifact_each_figure_resolved_to(tmp_path):
    """Evidence emission: a verdict must carry what it judged on, so an
    independent track can re-derive the same conclusion."""
    run = _make_run(tmp_path, "run_a", gds_bytes=8192, drc_items=0)
    _report(run / "RESULT.md", "# R\n\nGDS is 8192 B.\nDRC = 0\n")

    d = _verdict([run], tmp_path)
    assert d["verdict"] == "CLEAN"
    byte_figs = [f for f in d["figures"] if f["kind"] == "BYTE_SIZE_EXACT"]
    assert byte_figs, "the byte size figure was not recognised at all"
    f = byte_figs[0]
    assert f["status"] == "RESOLVED"
    assert f["resolved_path"].endswith("top.gds")
    assert f["resolved_value"] == 8192


def test_rounded_byte_magnitude_is_ignored_not_resolved(tmp_path):
    """A ROUNDED magnitude ("2.6 GB") is an order of magnitude, not an artifact
    identifier — many unrelated files round to it, and in the real corpus these
    described peak memory / docker images / files outside the run dir. It must
    be IGNORED and COUNTED as such, never resolved and never failed on."""
    run = _make_run(tmp_path, "run_a", gds_bytes=64, drc_items=0)
    _report(run / "RESULT.md", "# R\n\nGDS is 64 B. The image is 2.6 GB.\n")

    d = _verdict([run], tmp_path)
    assert d["_rc"] == 0 and d["verdict"] == "CLEAN"
    assert not [f for f in d["figures"] if "2.6" in f["raw"]], \
        "a rounded magnitude must not be recognised as a resolvable figure"
    assert d["evidence"]["numeric_inventory"]["ignored_rounded_magnitude"] >= 1


def test_byte_size_in_a_memory_context_is_not_a_file_claim(tmp_path):
    """`killed, 3700000 bytes RSS` measures a footprint, not an artifact.
    Resolving it against files would measure the wrong thing."""
    run = _make_run(tmp_path, "run_a", gds_bytes=64, drc_items=0)
    _report(run / "RESULT.md",
            "# R\n\nGDS is 64 B.\nLEC did not converge (killed, 3700000 bytes RSS).\n")
    d = _verdict([run], tmp_path)
    assert d["_rc"] == 0 and d["verdict"] == "CLEAN"


def test_simulation_mismatch_count_is_not_a_drc_count(tmp_path):
    """'NIST self-verify, 0 mismatch' is a SIMULATION result. Resolving it
    against a DRC database is the adjacent-measurement error this gate exists
    to prevent — so the gate must not commit it itself."""
    run = _make_run(tmp_path, "run_a", gds_bytes=64, drc_items=42)
    _report(run / "RESULT.md", "# R\n\nGDS is 64 B.\nNIST self-verify, 0 mismatch\n")
    d = _verdict([run], tmp_path)
    assert d["_rc"] == 0 and d["verdict"] == "CLEAN"


def test_zero_count_is_never_attributed_as_a_cross_run_import(tmp_path):
    """IMPORTED is a specific accusation. Zero matches every clean sibling, so
    it cannot prove an import — the figure must still FAIL, but as UNRESOLVED
    rather than by naming a culprit the evidence does not support."""
    _make_run(tmp_path, "run_sib", gds_bytes=4096, drc_items=0)
    here = _make_run(tmp_path, "run_here", gds_bytes=4096, drc_items=5)
    _report(here / "RESULT.md", "# R\n\nGDS is 4096 B.\nDRC violations: 0\n")

    d = _verdict([here], tmp_path)
    assert d["_rc"] == 1
    assert d["state"] == "UNBACKED_FIGURE"
    assert d["evidence"]["figures_imported"] == 0


def test_prose_without_figures_is_clean_not_an_alarm(tmp_path):
    """A report with no quantitative claims has nothing to betray. The gate must
    stay silent rather than invent a failure."""
    run = _make_run(tmp_path, "run_a", gds_bytes=512, drc_items=0)
    _report(run / "RESULT.md",
            "# RESULT\n\nThe flow completed and the design was reviewed.\n"
            "See section 3 for the narrative and step 2 for the method.\n")
    d = _verdict([run], tmp_path)
    assert d["_rc"] == 0 and d["verdict"] == "CLEAN"


# ---------------------------------------------------------------------------
# (1) FAIL — a report quoting a byte size no file has.
# ---------------------------------------------------------------------------
def test_byte_size_matching_no_file_is_unbacked(tmp_path):
    run = _make_run(tmp_path, "run_a", gds_bytes=91_152_610 % 100_000, drc_items=0)
    _report(run / "RESULT.md", "# R\n\nGDS `top.gds` is 91,520,898 B.\n")

    d = _verdict([run], tmp_path)
    assert d["_rc"] == 1
    assert d["verdict"] == "FAIL"
    assert d["state"] == "UNBACKED_FIGURE"


def test_unbacked_figure_is_named_in_the_output(tmp_path):
    """'the gate fails and names the untraceable figure' — the operator must be
    told WHICH number is unbacked, not merely that something is."""
    run = _make_run(tmp_path, "run_a", gds_bytes=1024, drc_items=0)
    _report(run / "RESULT.md", "# R\n\nGDS is 91,520,898 B.\n")

    d = _verdict([run], tmp_path)
    assert "91,520,898" in d["_stdout"]
    assert any("91,520,898" in b for b in d["blocking"])
    bad = [f for f in d["figures"] if f["status"] == "UNRESOLVED"]
    assert len(bad) == 1 and bad[0]["value"] == 91_520_898
    assert bad[0]["looked_in"], "must record WHERE it looked, not just that it failed"


def test_drc_count_not_matching_the_drc_database_is_unbacked(tmp_path):
    """A DRC item count must equal the count in THIS run's DRC XML."""
    run = _make_run(tmp_path, "run_a", gds_bytes=256, drc_items=130)
    _report(run / "RESULT.md", "# R\n\nGDS is 256 B.\nDRC violations: 0\n")

    d = _verdict([run], tmp_path)
    assert d["_rc"] == 1 and d["state"] == "UNBACKED_FIGURE"
    bad = [f for f in d["figures"] if f["status"] == "UNRESOLVED"]
    assert any(f["kind"] == "DRC_COUNT" and f["value"] == 0 for f in bad)


def test_drc_count_matching_the_drc_database_is_clean(tmp_path):
    """The direct control for the test above: the SAME shape, correct number."""
    run = _make_run(tmp_path, "run_a", gds_bytes=256, drc_items=130)
    _report(run / "RESULT.md", "# R\n\nGDS is 256 B.\nDRC violations: 130\n")
    d = _verdict([run], tmp_path)
    assert d["_rc"] == 0 and d["verdict"] == "CLEAN"


# ---------------------------------------------------------------------------
# (2) FAIL — an input-only run dir with a verdict reported.
# ---------------------------------------------------------------------------
def test_input_only_run_dir_with_reported_verdict_fails(tmp_path):
    run = _input_only_run(tmp_path, "run_v1467")
    ledger = _report(tmp_path / "LEDGER.md",
                     "# Campaign\n\n## run_v1467\nVerdict: PASS. GDS 91,520,898 B.\n")

    d = _verdict([run, "--report", ledger], tmp_path)
    assert d["_rc"] == 1
    assert d["state"] == "NO_OUTPUTS_ONLY_INPUTS"
    assert d["evidence"]["run_dir_files_total"] == 27
    assert d["evidence"]["run_dir_files_outside_input"] == 0


def test_report_living_inside_the_run_dir_cannot_vouch_for_itself(tmp_path):
    """A RESULT.md sitting in an otherwise input-only run dir is the CLAIM, not
    an output. It must not count as the output that proves the run produced
    something."""
    run = _input_only_run(tmp_path, "run_v1467")
    _report(run / "RESULT.md", "# R\n\nVerdict: PASS. DRC = 0\n")

    d = _verdict([run], tmp_path)
    assert d["_rc"] == 1
    assert d["state"] == "NO_OUTPUTS_ONLY_INPUTS"


def test_run_dir_with_even_one_real_output_is_not_input_only(tmp_path):
    """The boundary: one genuine output is enough to leave the zero-output
    class. Keeps the check from firing on real runs."""
    run = _input_only_run(tmp_path, "run_x")
    (run / "reports").mkdir(parents=True, exist_ok=True)
    (run / "reports" / "final_summary.md").write_text("done\n")
    _report(run / "RESULT.md", "# R\n\nThe run completed.\n")

    d = _verdict([run], tmp_path)
    assert d["state"] != "NO_OUTPUTS_ONLY_INPUTS"
    assert d["_rc"] == 0


# ---------------------------------------------------------------------------
# (3) FAIL — a figure that resolves only in a SIBLING run dir (the import).
# ---------------------------------------------------------------------------
def test_figure_resolving_only_in_sibling_run_is_cross_run_import(tmp_path):
    _make_run(tmp_path, "run_v1462", gds_bytes=91_152_610 % 1_000_003, drc_items=7)
    here = _make_run(tmp_path, "run_v1467", gds_bytes=4096, drc_items=0)
    sib_size = (tmp_path / "run_v1462" / "phase3" / "gds" / "top.gds").stat().st_size
    _report(here / "RESULT.md", f"# R\n\nGDS is {sib_size} B.\n")

    d = _verdict([here], tmp_path)
    assert d["_rc"] == 1
    assert d["state"] == "CROSS_RUN_IMPORT"


def test_cross_run_import_names_both_paths(tmp_path):
    """'Flag it with both paths' — the whole value of this signal is that it
    names the wrong run, not merely that a number is missing."""
    _make_run(tmp_path, "run_v1462", gds_bytes=777_777, drc_items=0)
    here = _make_run(tmp_path, "run_v1467", gds_bytes=4096, drc_items=0)
    _report(here / "RESULT.md", "# R\n\nGDS is 777777 B.\n")

    d = _verdict([here], tmp_path)
    imported = [f for f in d["figures"] if f["status"] == "IMPORTED"]
    assert len(imported) == 1
    f = imported[0]
    assert "run_v1467" in f["source_report"]          # where it was CLAIMED
    assert "run_v1462" in f["imported_from"]          # where it actually LIVES
    assert "run_v1462" in d["_stdout"]
    assert any("run_v1462" in b for b in d["blocking"])


def test_import_is_distinguished_from_plain_absence(tmp_path):
    """The two failure classes must not collapse into one another: a number that
    exists nowhere is UNBACKED_FIGURE; a number that exists in the wrong run is
    CROSS_RUN_IMPORT. Same run dir, same shape, different diagnosis."""
    _make_run(tmp_path, "run_sib", gds_bytes=555_555, drc_items=0)
    here = _make_run(tmp_path, "run_here", gds_bytes=4096, drc_items=0)

    _report(here / "RESULT.md", "# R\n\nGDS is 555555 B.\n")
    imported = _verdict([here], tmp_path)

    _report(here / "RESULT.md", "# R\n\nGDS is 424242 B.\n")
    absent = _verdict([here], tmp_path)

    assert imported["state"] == "CROSS_RUN_IMPORT"
    assert absent["state"] == "UNBACKED_FIGURE"


def test_sibling_scan_can_be_disabled(tmp_path):
    """With the scan off the import degrades to plain absence — it still FAILS
    (fails safe), it just loses the diagnosis."""
    _make_run(tmp_path, "run_sib", gds_bytes=888_888, drc_items=0)
    here = _make_run(tmp_path, "run_here", gds_bytes=4096, drc_items=0)
    _report(here / "RESULT.md", "# R\n\nGDS is 888888 B.\n")

    d = _verdict([here, "--no-sibling-scan"], tmp_path)
    assert d["_rc"] == 1
    assert d["state"] == "UNBACKED_FIGURE"


# ---------------------------------------------------------------------------
# The gate's own trap: coverage must be stated, never implied.
# ---------------------------------------------------------------------------
def test_clean_verdict_publishes_how_much_it_actually_checked(tmp_path):
    """The defect being fixed came from a checker that measured something
    adjacent and was read as if it answered the question. A CLEAN verdict here
    must therefore carry the count of numbers it did NOT speak for, so nobody
    can read it as 'every number verified'."""
    run = _make_run(tmp_path, "run_a", gds_bytes=64, drc_items=0)
    _report(run / "RESULT.md",
            "# R\n\nGDS is 64 B.\n"
            "Built on 2026-07-21 with plugin v1.4.83.\n"
            "See step 7 and table 12 for the 42 remaining notes.\n")

    d = _verdict([run], tmp_path)
    assert d["verdict"] == "CLEAN"
    inv = d["evidence"]["numeric_inventory"]
    assert inv["recognised_as_figures"] >= 1
    assert inv["numeric_tokens_seen"] > inv["recognised_as_figures"]
    assert inv["ignored_unclassified"] >= 1
    assert "coverage_note" in inv


def test_evidence_records_which_reports_were_read(tmp_path):
    run = _make_run(tmp_path, "run_a", gds_bytes=64, drc_items=0)
    _report(run / "RESULT.md", "# R\n\nGDS is 64 B.\n")
    d = _verdict([run], tmp_path)
    assert any(r.endswith("RESULT.md") for r in d["evidence"]["reports_read"])


# ---------------------------------------------------------------------------
# Shapes deliberately IGNORED — these must NOT be treated as figures.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("body", [
    "# R\n\nRun dated 20260721 completed.\n",
    "# R\n\nPlugin version v1.4.83 was used.\n",
    "# R\n\nSee https://example.com/run/91520898 for detail.\n",
    "# R\n\nSection 4 lists 17 open items across 3 categories.\n",
    "# R\n\n```\nstat -c %s /some/path/top.gds   # prints 91520898\n```\n",
])
def test_ignored_shapes_do_not_fail_the_gate(tmp_path, body):
    """Dates, versions, URLs, bare counts and shell COMMANDS are identifiers or
    instructions, not claims about an artifact. Treating them as figures would
    make the gate noise; the module docstring states this contract."""
    run = _make_run(tmp_path, "run_a", gds_bytes=64, drc_items=0)
    _report(run / "RESULT.md", body)
    d = _verdict([run], tmp_path)
    assert d["_rc"] == 0, f"gate wrongly fired on an ignored shape: {body!r}"


# ---------------------------------------------------------------------------
# Section slicing (a multi-design ledger) + CLI contract.
# ---------------------------------------------------------------------------
def test_section_filter_judges_only_the_named_designs_figures(tmp_path):
    run = _make_run(tmp_path, "run_a", gds_bytes=4096, drc_items=0)
    ledger = _report(tmp_path / "LEDGER.md",
                     "# Campaign\n\n"
                     "## alpha\nGDS is 4096 B.\n\n"
                     "## beta\nGDS is 91,520,898 B.\n")

    good = _verdict([run, "--report", ledger, "--section", "alpha"], tmp_path)
    bad = _verdict([run, "--report", ledger, "--section", "beta"], tmp_path)
    assert good["_rc"] == 0
    assert bad["_rc"] == 1 and bad["state"] == "UNBACKED_FIGURE"


def test_help_exits_zero():
    assert _run(["--help"]).returncode == 0


def test_missing_run_dir_is_usage_error(tmp_path):
    assert _run([tmp_path / "nope"]).returncode == 2


def test_failure_emits_a_capture_candidate(tmp_path):
    run = _make_run(tmp_path, "run_a", gds_bytes=64, drc_items=0)
    _report(run / "RESULT.md", "# R\n\nGDS is 91,520,898 B.\n")
    d = _verdict([run], tmp_path)
    cc = d["capture_candidate"]
    assert cc and cc["component"] == "orchestration/figure-artifact-backing"
    assert cc["detected_by"] == "reported_figure_artifact_backing_check.py"


def test_no_report_present_is_clean_not_a_crash(tmp_path):
    """A run dir with outputs but no report yet has made no claims to betray."""
    run = _make_run(tmp_path, "run_a", gds_bytes=64, drc_items=0)
    d = _verdict([run], tmp_path)
    assert d["_rc"] == 0


# ---------------------------------------------------------------------------
# The AUGMENT to run_output_completeness_check.py — the measured escape.
# ---------------------------------------------------------------------------
RUNOUT = (Path(__file__).resolve().parent.parent
          / "run_output_completeness_check.py")


def _run_runout(args: list) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUNOUT)] + [str(a) for a in args],
                          capture_output=True, text=True)


def _complete_result_body() -> str:
    lines = ["# RESULT — signoff", "", "## Verdict", "PASS.", ""]
    lines += [f"Narrative line {i}: the flow completed and closed nominally."
              for i in range(12)]
    return "\n".join(lines) + "\n"


def test_runout_input_only_dir_with_complete_result_now_fails(tmp_path):
    """MEASURED ESCAPE (2026-07-21): this exact shape returned COMPLETE / rc 0.
    `require_artifacts` defaults to empty, so the artifact check was vacuously
    true and the verdict reduced to 'RESULT.md is >=400 B' — prose alone
    cleared it."""
    run = _input_only_run(tmp_path, "run_v1467")
    (run / "RESULT.md").write_text(_complete_result_body())

    r = _run_runout([run, "--claimed-verdict", "PASS"])
    assert r.returncode == 1
    assert "NO_OUTPUTS_ONLY_INPUTS" in r.stdout


def test_runout_same_result_with_a_real_output_still_passes(tmp_path):
    """The control for the augment: identical deliverable, one real output ->
    unchanged PASS. The new state keys off OUTPUTS, not off the report."""
    run = _input_only_run(tmp_path, "run_ok")
    (run / "RESULT.md").write_text(_complete_result_body())
    (run / "reports").mkdir(parents=True, exist_ok=True)
    (run / "reports" / "final_summary.md").write_text("done\n")

    r = _run_runout([run, "--claimed-verdict", "PASS"])
    assert r.returncode == 0
    assert "COMPLETE" in r.stdout


def test_runout_dir_without_an_input_subtree_is_untouched(tmp_path):
    """A run dir with no input/ subtree at all can never be 'input only' — the
    prior RUN_DIED_EARLY / STUB semantics must be preserved exactly."""
    r = _run_runout([tmp_path])
    assert r.returncode == 1
    assert "RUN_DIED_EARLY" in r.stdout
