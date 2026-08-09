#!/usr/bin/env python3
"""Tests for transient_signal_latch_check.py

The block after the two smoke tests pins the gate's SEVERITY TIERS, both of
them. The gate advertises ERROR and WARN, prints a count of each on its one
verdict line, and offers `--strict` whose only documented job is to fail on the
WARN count — but the WARN branch used to `continue` before the gate's single
`findings.append`, so no finding could ever carry severity="WARN". `warns` was
`[]` by construction, `N warns` was a constant 0, and `--strict` was a
tautology.

Both directions are pinned, because pinning one is half the property:

  * the WARN tier must be EMITTABLE (a mitigated pair reaches the report, is
    counted on stdout, and makes `--strict` exit 1);
  * the gate must still be able to say the OTHER things — an unlatched pair is
    still an ERROR, a mitigated pair is still exit 0 without `--strict`, and
    `--strict` on a design with no risky pair is still exit 0. A gate that can
    only ever fail is the same defect wearing the opposite sign.

Every assertion here reads a returned value: an exit code, the emitted JSON
report, or the gate's own stdout. Nothing asserts on the gate's source text.

Fixtures are synthetic and generic — two nameless modules, a handshake-gated
pulse and a bit-counter FSM. No design, PDK or part name appears in any of them.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

PROG = Path(__file__).resolve().parent.parent / "transient_signal_latch_check.py"


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_empty_rtl(tmp_path):
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    r = _run(["--rtl-dir", str(tmp_path), "--out-dir", str(tmp_path / "out")])
    assert r.returncode == 0


# ── severity tiers ──────────────────────────────────────────────────────────

_PRODUCER = """\
module pulse_source (
    input  wire clk,
    input  wire xfer_ack,
    input  wire more_data,
    output reg  alpha_flag,
    output reg  beta_flag
);
    always @(posedge clk) begin
        alpha_flag <= xfer_ack & more_data;
        beta_flag  <= xfer_ack & ~more_data;
    end
endmodule
"""


def _consumer(latch_alpha: bool, latch_beta: bool) -> str:
    """A multi-cycle FSM reading the two pulses, latching whichever we ask."""
    decls, body = "", ""
    if latch_alpha:
        decls += "    reg       cur_alpha_flag;\n"
        body += "        cur_alpha_flag <= alpha_flag;\n"
    if latch_beta:
        decls += "    reg       cur_beta_flag;\n"
        body += "        cur_beta_flag <= beta_flag;\n"
    return (
        "module pulse_sink (\n"
        "    input  wire clk,\n"
        "    input  wire alpha_flag,\n"
        "    input  wire beta_flag,\n"
        "    output reg  done\n"
        ");\n"
        "    reg [2:0] state;\n"
        "    reg [3:0] bit_cnt;\n"
        + decls +
        "    always @(posedge clk) begin\n"
        "        bit_cnt <= bit_cnt + 1;\n"
        + body +
        "        if (alpha_flag) state <= 3'd2;\n"
        "        if (beta_flag) done <= 1'b1;\n"
        "    end\n"
        "endmodule\n"
    )


def _rtl(tmp_path: Path, latch_alpha: bool, latch_beta: bool) -> Path:
    d = tmp_path / "rtl"
    d.mkdir(exist_ok=True)
    (d / "pulse_source.v").write_text(_PRODUCER)
    (d / "pulse_sink.v").write_text(_consumer(latch_alpha, latch_beta))
    return d


def _report(tmp_path: Path, rtl: Path, tag: str,
            *extra: str) -> Tuple[subprocess.CompletedProcess, Dict]:
    """Drive the gate's real CLI and return (process, its emitted JSON)."""
    out = tmp_path / f"rep_{tag}"
    r = _run(["--rtl-dir", str(rtl), "--out-dir", str(out), *extra])
    assert "Traceback" not in r.stderr, r.stderr[-800:]
    return r, json.loads(
        (out / "transient_signal_latch_check.json").read_text())


def _by_severity(report: Dict, sev: str) -> List[Dict]:
    return [f for f in report["findings"] if f["severity"] == sev]


# --- direction 1: the WARN tier must be reachable ---------------------------

def test_a_latch_mitigated_pair_is_emitted_as_a_warn(tmp_path):
    """FAILS against the unfixed gate.

    The fixture is a cross-file, multi-cycle pair whose consumer DOES latch the
    pulse, so the gate reaches its latch/no-latch decision and decides
    "mitigated". The unfixed gate dropped that pair on the floor and reported
    `0 errors, 0 warns` — identical to a design with no risky pair at all."""
    rtl = _rtl(tmp_path, latch_alpha=True, latch_beta=True)
    r, rep = _report(tmp_path, rtl, "warn")

    # The pairs really did reach the decision — otherwise this fixture would be
    # pinning nothing and the test would pass for the wrong reason.
    assert rep["denominator"]["examined"] >= 1, rep["denominator"]

    warns = _by_severity(rep, "WARN")
    assert warns, (
        "no WARN finding was emitted for a latch-mitigated pair; the gate "
        f"reported findings={rep['findings']!r}")
    assert all(f["has_latch"] is True for f in warns), warns

    # The count on the one line a human reads must be the real count.
    assert f"{len(warns)} warns" in r.stdout, r.stdout
    assert "0 warns" not in r.stdout, r.stdout
    # ...and the WARN must be listed, not just counted.
    assert "[WARN]" in r.stdout, r.stdout


def test_strict_fails_on_a_latch_mitigated_pair(tmp_path):
    """FAILS against the unfixed gate.

    `--strict`'s entire effect is `not args.strict or not warns`. With `warns`
    empty by construction that conjunct was True for every input, so the flag
    could not change any run's exit code."""
    rtl = _rtl(tmp_path, latch_alpha=True, latch_beta=True)
    r, rep = _report(tmp_path, rtl, "strict", "--strict")

    assert rep["status"] == "FAIL", rep["status"]
    assert r.returncode == 1, (r.returncode, r.stdout)
    assert _by_severity(rep, "WARN"), rep["findings"]
    # It failed FOR the warns, not because something became an error.
    assert not _by_severity(rep, "ERROR"), rep["findings"]


def test_both_tiers_are_emittable_in_one_run_errors_listed_first(tmp_path):
    """FAILS against the unfixed gate (no `[WARN]` line could ever exist).

    Also pins the listing order: the stdout listing is capped, and an advisory
    must not push a failing pair out of it."""
    rtl = _rtl(tmp_path, latch_alpha=True, latch_beta=False)
    r, rep = _report(tmp_path, rtl, "mixed")

    assert _by_severity(rep, "WARN"), rep["findings"]
    assert _by_severity(rep, "ERROR"), rep["findings"]
    assert "[ERROR]" in r.stdout and "[WARN]" in r.stdout, r.stdout
    assert r.stdout.index("[ERROR]") < r.stdout.index("[WARN]"), r.stdout


# --- direction 2: the other verdicts must survive ---------------------------

def test_a_mitigated_pair_is_not_an_error_by_default(tmp_path):
    """The mitigation is real, so the DEFAULT verdict stays green.

    This is the half that stops the fix from turning every latched design red:
    emitting the WARN must not promote it."""
    rtl = _rtl(tmp_path, latch_alpha=True, latch_beta=True)
    r, rep = _report(tmp_path, rtl, "default")

    assert rep["status"] == "PASS", rep["status"]
    assert r.returncode == 0, (r.returncode, r.stdout)
    assert not _by_severity(rep, "ERROR"), rep["findings"]
    assert "0 errors" in r.stdout, r.stdout


def test_an_unlatched_pair_is_still_an_error(tmp_path):
    """The tier that already worked must keep working."""
    rtl = _rtl(tmp_path, latch_alpha=False, latch_beta=False)
    r, rep = _report(tmp_path, rtl, "error")

    assert rep["status"] == "FAIL", rep["status"]
    assert r.returncode == 1, (r.returncode, r.stdout)
    errs = _by_severity(rep, "ERROR")
    assert errs, rep["findings"]
    assert all(f["has_latch"] is False for f in errs), errs
    assert not _by_severity(rep, "WARN"), rep["findings"]


def test_strict_still_passes_a_design_with_no_risky_pair(tmp_path):
    """`--strict` must not be a blanket FAIL.

    A gate that always fails once you give it its own flag is the same defect
    with the sign flipped."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.v").write_text("module top (input wire clk);\nendmodule\n")
    r, rep = _report(tmp_path, d, "clean", "--strict")

    assert rep["status"] == "PASS", rep["status"]
    assert r.returncode == 0, (r.returncode, r.stdout)
    assert rep["findings"] == [], rep["findings"]
    assert rep["denominator"]["examined"] == 0, rep["denominator"]
    assert "0 errors, 0 warns" in r.stdout, r.stdout


def test_the_verdict_line_counts_match_the_emitted_report(tmp_path):
    """The one line a human reads must agree with the JSON, in both tiers."""
    rtl = _rtl(tmp_path, latch_alpha=True, latch_beta=False)
    r, rep = _report(tmp_path, rtl, "counts")
    n_err = len(_by_severity(rep, "ERROR"))
    n_warn = len(_by_severity(rep, "WARN"))
    assert n_err and n_warn, rep["findings"]
    assert f"{n_err} errors, {n_warn} warns" in r.stdout, r.stdout


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
