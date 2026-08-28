#!/usr/bin/env python3
"""`eda_sta` must actually USE the evidence channels, not merely ship them.

`sta_evidence.mjs` is fully unit-tested, and every one of those tests would
still pass if the `eda_sta` tool never called it. That is the gap this file
closes: it asserts the wiring at the call site.

RE-AUTHORED 2026-08-27 onto the file-script tree. The measurement that forced
the move: our `-exit` had NEVER taken effect. `Main.cc:467`'s
`exit_after_cmd_file` applies only when a script FILE ARGUMENT is present, and
this tool fed Tcl on stdin, so OpenROAD fell into the REPL and
`tcl_readline_setup.cc:78-82` called `std::exit(EXIT_SUCCESS)` at EOF. Measured
on one failing script in the pinned image:

    openroad -exit bad.tcl      -> rc=1
    openroad -exit << EOF ...   -> rc=0, and it kept executing past the error

Three properties below therefore changed MECHANISM. None was dropped, and each
is now pinned at least as tightly as before:

  1. `-metrics` is still required, but the flag is now emitted by the shared
     `openroadScriptCmd` builder instead of being spelled out at this call
     site. The test pins BOTH that this call goes through the builder AND that
     the builder emits the flag — pinning only the call site would let the flag
     be deleted from the builder unnoticed.
  2. the stale-metrics-file `rm -f` is GONE, and its property is met more
     strongly: the sidecar's path is derived from a per-run `mktemp`, so no
     earlier run can even NAME the file. A fixed name someone must remember to
     delete is replaced by a name nobody else holds.
  3. absent / empty / unparseable stays a three-way distinction, but it is
     answered by a PRESENT/ABSENT sentinel inside the same in-container script
     rather than by a second `dockerExec` read-back. The read-back became
     redundant the moment the sidecar started riding home in the run's own
     output — and it read a fixed path that no longer exists.

Two properties are ADDED, because the defect above must not come back: the
invocation must be a file argument (never a heredoc, never a pipe), and a
constrained run that MISSED timing must not be manifested PASS.

The rest are unchanged: the linkage metric is emitted after `link_design`, the
reported `success` is the conjunction, the manifest is gated on that
conjunction, and wns/tns are withheld from a run that produced no evidence.
"""
from __future__ import annotations

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "src" / "index.js"
SRC = INDEX.read_text(encoding="utf-8")

LINK_METRIC = "sta__design__port__count"


def _eda_sta_block() -> str:
    """The source of the eda_sta tool registration, up to the next tool."""
    start = SRC.index('// ─── Tool: eda_sta ───')
    nxt = SRC.index('// ─── Tool: eda_lvs ───', start)
    return SRC[start:nxt]


def _script_builder() -> str:
    """The shared builder that stages Tcl to a file and runs it as an ARGUMENT."""
    start = SRC.index("function openroadScriptCmd(")
    return SRC[start:SRC.index("\n}\n", start)]


def _run_parser() -> str:
    start = SRC.index("function parseOpenroadRun(")
    return SRC[start:SRC.index("\n}\n", start)]


def test_openroad_is_invoked_with_a_metrics_file():
    """Without -metrics no sidecar is ever written, every metric is ABSENT, and
    every run comes back UNMEASURED — which looks like the guard "working"
    while actually measuring nothing."""
    block = _eda_sta_block()
    assert re.search(r"openroadScriptCmd\(\{\s*tcl:\s*staTcl", block), (
        "eda_sta no longer builds its command with openroadScriptCmd, so "
        "nothing guarantees the run is a file script or that -metrics is asked "
        "for at all")
    assert "metrics: false" not in block, (
        "eda_sta opted out of the metrics sidecar; the metrics channel is dead "
        "and every run reports UNMEASURED regardless of what happened")
    builder = _script_builder()
    assert '`-metrics "$_vic_m" `' in builder, (
        "openroadScriptCmd stopped requesting -metrics. Every caller's metrics "
        "channel dies with it, silently.")


def test_the_tcl_is_a_file_argument_never_stdin():
    """THE DEFECT ITSELF. `-exit` is honoured only for a script FILE ARGUMENT
    (Main.cc:467). Fed on stdin, OpenROAD enters the REPL, runs on past every
    failure, and exits 0 at EOF — which is why every report could fail while
    the tool returned success:true."""
    block = _eda_sta_block()
    assert "-exit <<" not in block and "<< 'EOF'" not in block, (
        "eda_sta is feeding Tcl on stdin again; -exit does not apply there and "
        "the exit code goes back to being a constant 0")
    assert "| openroad" not in block, "Tcl piped into openroad is the same defect"
    builder = _script_builder()
    assert '-exit ${metricsArg}"$_vic_s"' in builder, (
        "the staged script is no longer passed as the ARGUMENT; without that "
        "`exit_after_cmd_file` never fires")


def test_the_metrics_file_cannot_be_a_leftover_from_an_earlier_run():
    """Was `test_a_stale_metrics_file_is_removed_before_the_run`. The property
    is the same — a sidecar left by an earlier run must not satisfy the
    presence term with another design's numbers — but it is now met by
    construction rather than by remembering to delete: the path comes from a
    per-run mktemp, so no earlier run holds that name."""
    builder = _script_builder()
    assert "mktemp /tmp/vibeic_" in builder, (
        "the script path is no longer a fresh mktemp; a fixed path can be "
        "satisfied by a file an earlier run left behind")
    assert ".metrics.json" in builder, (
        "the metrics path is no longer derived from the per-run script path")
    assert 'rm -f "$_vic_s" "$_vic_m"' in builder, (
        "the staged script and its sidecar are no longer cleaned up")


def test_absent_is_distinguished_from_empty_and_from_unparseable():
    """`cat` of a missing file prints exactly what an empty one prints. The
    three cases must stay apart, because ABSENT means UNMEASURED and must never
    be read as "zero errors" (ORFS `checkMetadata.py:103-111` sys.exit(1)s on a
    missing required metric; LibreLane's warn-only checker is the anti-pattern).
    MEASURED: the sidecar really is absent after an unwritable -metrics path
    (rc=1, UTL-0010) and after a SIGKILL (rc=137)."""
    builder = _script_builder()
    assert "===VIBEIC_METRICS_PRESENT===" in builder
    assert "===VIBEIC_METRICS_ABSENT===" in builder, (
        "the presence sentinel is gone; an absent sidecar is now "
        "indistinguishable from an empty one")
    parser = _run_parser()
    assert "const metricsPresent =" in parser
    assert "metricsRaw" in parser, (
        "the raw sidecar text is no longer surfaced, so the evaluator cannot "
        "tell an unparseable file from a missing one")
    block = _eda_sta_block()
    assert "metricsFileExists: staRun.metricsPresent" in block
    assert "metricsRaw: staRun.metricsRaw" in block


def test_the_evidence_is_evaluated_on_the_real_exit_code():
    """The exit-code term was worthless while the Tcl went in on stdin — it was
    a constant 0. It is a real term only against the file-script run's status."""
    block = _eda_sta_block()
    assert "exitCode: staRun.rc," in block, (
        "the evidence conjunction is not reading the run's real exit code")
    assert "exitCode: result.success ? 0 : 1" not in block, (
        "the exit-code term fell back to dockerExec's own view instead of the "
        "status openroad actually returned")


def test_the_linkage_metric_is_emitted_after_link_design():
    block = _eda_sta_block()
    assert "${staEvidenceTcl()}" in block, (
        "the linkage-metric emission was dropped from the Tcl; the metric is "
        "then absent on every run and the rule can never distinguish a linked "
        "design from an unlinked one")
    link_at = block.index("link_design ")
    emit_at = block.index("${staEvidenceTcl()}")
    assert link_at < emit_at, (
        "the linkage metric must be emitted AFTER link_design — before it, "
        "get_ports would report the pre-link network")
    # and before the reports, so an unlinked network raises here first
    assert emit_at < block.index("report_checks"), block[link_at:emit_at + 200]


def test_the_reported_success_is_the_conjunction_not_the_exit_code():
    block = _eda_sta_block()
    assert "evaluateStaEvidence(" in block, "eda_sta never calls the evaluator"
    assert re.search(r"\bsuccess:\s*staPass\b", block), (
        "eda_sta's reported success is not the conjunction. `success: "
        "result.success` is the ORIGINAL BUG — openroad exits 0 having linked "
        "no design and the tool reports true.")
    assert not re.search(r"\bsuccess:\s*result\.success\b", block), (
        "eda_sta still reports the raw exit code as success")
    assert "const staPass = staAnalysed && staEvidence.pass;" in block, (
        "the conjunction was demoted to a single channel")


def test_the_manifest_status_is_gated_on_the_conjunction():
    """The gate on `staPass` is what this test exists to pin: writing PASS on
    the bare exit code is how the original bug reached the manifest.

    WIDENED 2026-08-27. The status expression this used to spell out literally
    — `status: clockConstrained ? "PASS" : "UNCONSTRAINED"` — was too narrow to
    be true: a constrained run that MISSED timing was manifested PASS by it. It
    is now a three-way expression, and this test requires the TIMING_VIOLATED
    arm rather than forbidding it. See
    `test_a_constrained_run_that_missed_timing_is_not_manifested_pass`.

    WIDENED AGAIN 2026-08-28, the same way and for the same reason. The
    measurement contract adds a FOURTH outcome the three could not express: a
    run that legitimately had nothing to measure. Its own arm is REQUIRED here,
    not permitted — folding it back into "UNCONSTRAINED" makes this gate refuse
    every purely combinational design, and a gate that refuses everything gets
    bypassed. Requiring four arms is strictly harder to satisfy than three."""
    block = _eda_sta_block()
    m = re.search(
        r'if \(staPass\) \{\s*const dir[^}]*?status: clockConstrained\s*'
        r'\?\s*\(wns !== null && wns < 0 \? "TIMING_VIOLATED" : "PASS"\)\s*'
        r':\s*\(staClass === NOT_MEASURED_BENIGN\s*\?\s*"NOTHING_TO_MEASURE"\s*'
        r':\s*"UNCONSTRAINED"\)',
        block, re.S)
    assert m, (
        'the manifest still writes status:"PASS" on something other than the '
        'conjunction, or its status expression lost an arm. Writing PASS on '
        'the bare exit code is how the original bug reached the manifest, and '
        'collapsing NOTHING_TO_MEASURE into UNCONSTRAINED is the same lie '
        'pointing the other way.')


def test_a_constrained_run_that_missed_timing_is_not_manifested_pass():
    """MEASURED 2026-08-27: a 40-deep nand chain at 0.5 ns returned
    wns -12.10 ns and still wrote manifest status:"PASS", because the manifest
    keyed only on whether a clock had been found. Downstream flow steps read
    the manifest, so the violation has to reach it — and a run that PASSES the
    evidence conjunction is exactly the run whose slack must then be judged."""
    block = _eda_sta_block()
    i = block.index('step: "sta",')
    manifest = block[i:block.index("});", i)]
    assert '"TIMING_VIOLATED"' in manifest, (
        "the STA manifest cannot record a missed slack at all")
    assert 'status: clockConstrained ? "PASS"' not in manifest, (
        "a constrained run with negative slack is manifested PASS again")


def test_wns_is_withheld_when_the_run_produced_no_evidence():
    """A source-less clock prints `wns max 0.00`, byte-identical to a genuinely
    clean result. Reporting that number on a run that failed its evidence
    checks hands the caller a fabricated timing result."""
    block = _eda_sta_block()
    assert re.search(r"wns:\s*staPass \? wns : null", block), (
        "wns is reported without regard to the evidence verdict")
    assert re.search(r"tns:\s*staPass \? tns : null", block)


def test_the_module_is_imported():
    assert 'from "./lib/sta_evidence.mjs"' in SRC
