"""A proved-point count read out of a COMMENT the tool echoed back.

FOUND BY THE FLOW'S OWN GATE, and RED on clean `origin/main` before this
(dd85b42cee, v1.17.69 — same message byte for byte in a second checkout):

    [FAIL] 1 declaration regex(es) newly scan text no stripper touched:
       lec_run::lec_proved_points_from_output::_INDUCT_FOUND_RE(raw)

The gate's model is exact here. `_INDUCT_FOUND_RE` matches

    Found 35 unproven $equiv cells in module equiv:

against TOOL OUTPUT, and tool output can contain SOURCE the tool quoted back:
yosys echoes offending lines in its errors. A design carrying

    // Found 999 unproven $equiv cells in module equiv:

therefore had a path into the count. And this is NOT evidence-only debt:
`parse_equiv_output` uses the SAME pattern as its unproven FALLBACK whenever no
`equiv_status` line was emitted — which is exactly the killed-mid-proof case —
so a spoofed residual would reach a VERDICT, not just the telemetry.

Two independent closures, because either alone leaves a hole:
  * the pattern is ANCHORED to the start of a line, so a comment's `//` prefix
    (or any other prefix) makes it unmatchable. Verified against every fixture
    in this suite and four real logs on 8HD-9: yosys prints the line at column
    0, so no real match is lost;
  * `lec_proved_points_from_output` STRIPS echoed HDL line comments before
    counting. Anchored at line start so an absolute path (`/foss/pdks/...`)
    survives — measured on a 2.23 MB real LEC log: 18,472 lines in, 18,472 out.

The gate then reports 160 unstripped scans against a baseline of 166: the
population SHRANK. No baseline was rewritten, and no exemption was added.
"""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "lec_run.py"
sys.path.insert(0, str(SCRIPT.parent))
import lec_run  # noqa: E402

_REAL = "Found 35 unproven $equiv cells in module equiv:\n"
_ECHOED_COMMENT = "// Found 999 unproven $equiv cells in module equiv:\n"


def test_the_real_tool_line_still_matches():
    """POSITIVE CONTROL FIRST. An anchor that lost the real line would make
    every one of the negatives below pass for the wrong reason."""
    m = lec_run._INDUCT_FOUND_RE.findall(_REAL)
    assert m == ["35"], m
    # ...and indented, in case a future yosys indents it.
    assert lec_run._INDUCT_FOUND_RE.findall("   " + _REAL) == ["35"]
    # ...and mid-log, not only as the whole string.
    assert lec_run._INDUCT_FOUND_RE.findall(
        "equiv_induct: Proving $equiv cells in module equiv.\n" + _REAL) == ["35"]


def test_a_commented_out_line_is_not_a_count():
    assert lec_run._INDUCT_FOUND_RE.findall(_ECHOED_COMMENT) == [], (
        "a Verilog comment the tool echoed back was read as this run's "
        "residual count")
    assert lec_run._INDUCT_FOUND_RE.findall(
        "  //  Found 999 unproven $equiv cells in module equiv:\n") == []


def test_the_probe_reports_the_run_not_the_comment():
    """End to end through the probe, with the comment AFTER the real line so a
    last-match reader would take the comment if the anchor did not hold."""
    log = _REAL + _ECHOED_COMMENT
    assert lec_run.lec_proved_points_from_output(log) == {"unproven": 35}
    assert lec_run.lec_proved_points_from_output(_ECHOED_COMMENT) is None, (
        "a log whose ONLY count is a commented-out sentence must be "
        "NOT_MEASURED, never a number")


def test_the_verdict_path_cannot_be_spoofed_either():
    """`parse_equiv_output` falls back to this pattern when the run was killed
    before any equiv_status, so the spoof reached a VERDICT and not only the
    telemetry. Driven at that exact shape."""
    killed = ("equiv_make: Creating equivalence miter.\n"
              "Found 40 $equiv cells in equiv:\n"
              "Proved 33 previously unproven $equiv cells.\n"
              + _ECHOED_COMMENT
              + lec_run._TIMEOUT_MARKER + " (rc=124)\n")
    p = lec_run.parse_equiv_output(killed)
    assert p["unproven"] != 999, (
        "the killed-mid-proof verdict took its unproven count from a comment")
    real = killed.replace(_ECHOED_COMMENT, "Found 7 unproven $equiv cells "
                                           "in module equiv:\n")
    assert lec_run.parse_equiv_output(real)["unproven"] == 7, (
        "POSITIVE CONTROL: a REAL residual line must still reach the verdict")


def test_the_stripper_keeps_paths_and_mid_line_slashes():
    """The strip is line-anchored on purpose. A log is full of `/` and a
    stripper that ate `//` anywhere would corrupt the evidence it guards."""
    log = ("Liberty: /foss/pdks/sky130A/libs.ref/x.lib\n"
           "note: see https://example.invalid/docs for the pass\n"
           "  // this line is a quoted comment\n")
    out = lec_run.strip_echoed_hdl_comments(log)
    assert "/foss/pdks/sky130A/libs.ref/x.lib" in out
    assert "https://example.invalid/docs" in out
    assert "quoted comment" not in out
    assert lec_run.strip_echoed_hdl_comments("") == ""


def test_the_flow_gate_that_found_this_is_green_on_this_tree():
    """The gate itself, run as the flow runs it. RED on origin/main naming
    exactly one regex; this asserts it is green here — and it is the gate, not
    this file, that decides."""
    import subprocess
    proc = subprocess.run(
        [sys.executable,
         str(SCRIPT.parent / "hdl_declaration_scan_strips_comments_check.py")],
        capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "newly scan text no stripper touched" not in proc.stdout
