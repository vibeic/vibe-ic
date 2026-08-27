#!/usr/bin/env python3
"""The two changes that make an OpenROAD/OpenSTA run able to say NO.

MEASURED 2026-08-27 in vibeic-eda@sha256:4ece6c01 (openroad
26Q3-1797-g1c09d62b96, OpenSTA 2.7.0), on one failing script:

    openroad -exit bad.tcl      -> rc=1, sentinel ABSENT,  1 error
    openroad -exit << EOF ...   -> rc=0, sentinel PRESENT, 6 errors   <- ours
    sta      -exit bad.tcl      -> rc=1, sentinel ABSENT
    sta      -exit < bad.tcl    -> rc=0, sentinel PRESENT             <- ours

`-exit` only takes effect when a script FILE ARGUMENT is present
(Main.cc:467 exit_after_cmd_file); fed on stdin the binary falls into the REPL
and exits 0 at EOF, having run on past every error. That is why every report
could fail while the tool reported success:true and wrote status:"PASS".

ITEM 1 gives all five OpenROAD/OpenSTA sites a file argument.
ITEM 2 adds a positive assertion trio to the STA template, because a truthful
exit code still only proves that nothing RAISED -- not that the work happened.

These tests are chip-AGNOSTIC: no vendor, SKU or IC name appears in any
assertion, and the fixtures below are generic OpenSTA prose.
"""
import json
import re
import shutil
import os
import tempfile
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "index.js"
NODE = shutil.which("node")


def _src() -> str:
    return SRC.read_text(encoding="utf-8")


def _extract(decl: str) -> str:
    """Pull one `const x = ...;` declaration out of the server source."""
    src = _src()
    i = src.index(decl)
    return src[i:src.index("\n", i) + 1]


def _fn(name: str) -> str:
    """Pull a whole top-level `function name(...) { ... }` out of the source.

    The parameter list is skipped by paren-matching first: several of these
    helpers destructure their argument (`function f({ rc, errorCount })`), so
    brace-counting from the function keyword would stop at the parameter.
    """
    src = _src()
    i = src.index(f"function {name}(")
    p = src.index("(", i)
    depth = 0
    for j in range(p, len(src)):            # match the parameter list
        if src[j] == "(":
            depth += 1
        elif src[j] == ")":
            depth -= 1
            if depth == 0:
                p = j
                break
    b = src.index("{", p)                   # the body opens after it
    depth = 0
    for j in range(b, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError(f"could not extract function {name}")


def _node(script: str) -> str:
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ── ITEM 1: every OpenROAD/OpenSTA invocation passes a FILE ARGUMENT ─────────

#: The five sites the audit identified, by the tag each passes to the helper.
FIVE_SITES = ["pnr", "pnr_retry", "sta", "ir_drop", "mcorner_"]


def test_all_five_sites_go_through_the_file_argument_helper():
    src = _src()
    for tag in FIVE_SITES:
        assert f'tag: "{tag}' in src or f"tag: `{tag}" in src, \
            f"site {tag!r} no longer routes through openroadScriptCmd"
    # One helper call per site, plus none left over.
    calls = src.count("openroadScriptCmd({") - src.count("function openroadScriptCmd({")
    assert calls == len(FIVE_SITES), \
        "the number of OpenROAD/OpenSTA script sites changed -- re-audit them"


def test_no_openroad_or_sta_invocation_is_fed_on_stdin():
    """The regression guard. A heredoc or an `echo |` pipe into openroad/sta
    re-introduces the exact measured defect: rc 0 on a fully-failed script."""
    src = _src()
    offenders = []
    for n, line in enumerate(src.splitlines(), 1):
        if line.lstrip().startswith("//") or line.lstrip().startswith("*"):
            continue  # the defect is DOCUMENTED in comments; that is not a use
        if re.search(r"\|\s*(openroad|sta)\s", line):
            offenders.append((n, line.strip()))
        if re.search(r"(openroad|sta)\b[^\n]*-exit[^\n]*<<", line):
            offenders.append((n, line.strip()))
    assert not offenders, f"stdin-fed OpenROAD/OpenSTA invocations: {offenders}"


@pytest.mark.skipif(not NODE, reason="node not available")
def test_script_command_passes_the_path_as_an_argument_not_on_stdin():
    script = (
        CONJ
        + _fn("openroadScriptCmd")
        + "\nconsole.log(openroadScriptCmd({tcl:'report_checks', tag:'t'}));"
    )
    cmd = _node(script)
    # The Tcl is staged to a file...
    assert "mktemp" in cmd and "cat > \"$_vic_s\"" in cmd
    # ...and that file is the ARGUMENT (quoted, after -exit), not stdin.
    assert re.search(r'openroad .*-exit .*"\$_vic_s"', cmd), cmd
    assert "| openroad" not in cmd and "openroad -exit <<" not in cmd
    # The tool's real exit code is both reported and re-raised.
    assert "===VIBEIC_RC=" in cmd and "exit $_vic_rc" in cmd


@pytest.mark.skipif(not NODE, reason="node not available")
def test_opensta_binary_gets_no_metrics_flag():
    """MEASURED: OpenSTA 2.7.0 has no `-metrics`. Passing it would break every
    multi-corner run, so the sidecar is openroad-only and its absence is
    reported as UNKNOWN rather than as zero errors."""
    script = (
        CONJ
        + _fn("openroadScriptCmd")
        + "\nconsole.log(openroadScriptCmd({tcl:'x', binary:'sta', metrics:false, tag:'m'}));"
    )
    cmd = _node(script)
    assert "-metrics" not in cmd
    assert re.search(r'sta .*-exit .*"\$_vic_s"', cmd), cmd


@pytest.mark.skipif(not NODE, reason="node not available")
def test_heredoc_terminator_in_the_tcl_is_refused():
    """The staging heredoc is quoted, so Tcl reaches the file verbatim -- but a
    payload containing the terminator itself would end the heredoc early and
    inject shell. Refuse rather than run it."""
    script = (
        CONJ
        + _fn("openroadScriptCmd")
        + "\ntry{openroadScriptCmd({tcl:'a\\nVIBEIC_TCL_EOF\\nrm -rf /', tag:'t'});"
          "console.log('NOT_REFUSED');}catch(e){console.log('REFUSED');}"
    )
    assert _node(script) == "REFUSED"


# ── the conjunction: neither signal may decide alone ─────────────────────────

CONJ = ("const TOOLS='/foss/tools';\n"
        "const TCL_HEREDOC_TAG='VIBEIC_TCL_EOF';\n"
        "function _edaOpenroadThreadsToken(){return 'max';}\n")


@pytest.mark.skipif(not NODE, reason="node not available")
@pytest.mark.parametrize(
    "rc,errors,expect_failed",
    [
        (0, 0, False),      # clean
        (1, 0, True),       # MEASURED: rc=1 with flow__errors__count=0
        (0, 6, True),       # MEASURED: the stdin form -- rc=0 with 6 errors
        (1, 6, True),
        (0, None, False),   # UNKNOWN error count must not invent a failure
        (1, None, True),    # ...nor rescue one
    ],
)
def test_exit_code_and_error_count_are_conjoined(rc, errors, expect_failed):
    script = (CONJ + _fn("openroadRunFailed")
              + f"\nconsole.log(openroadRunFailed({{rc:{rc},"
                f"errorCount:{'null' if errors is None else errors}}}));")
    assert _node(script) == ("true" if expect_failed else "false")


@pytest.mark.skipif(not NODE, reason="node not available")
def test_absent_metrics_sidecar_is_unknown_never_zero():
    """ORFS `sys.exit(1)`s on a missing metric; LibreLane's warn-only checker is
    the anti-pattern. An absent sidecar must read as UNKNOWN (null), so that it
    can never be mistaken for `0 errors` and upgrade a verdict."""
    script = (CONJ + _fn("parseOpenroadRun")
              + "\nconsole.log(JSON.stringify(parseOpenroadRun("
                "{success:true, output:'hello\\n===VIBEIC_RC=0===\\n'})));")
    got = json.loads(_node(script))
    assert got["errorCount"] is None, "absent sidecar must be UNKNOWN, not 0"
    assert got["rc"] == 0


@pytest.mark.skipif(not NODE, reason="node not available")
def test_missing_rc_marker_falls_back_to_failure_not_success():
    """If the container died before the marker printed, that is a failure. It
    must not be silently downgraded to rc 0."""
    script = (CONJ + _fn("parseOpenroadRun")
              + "\nconsole.log(JSON.stringify(parseOpenroadRun("
                "{success:false, exitCode:137, output:'killed'})));")
    got = json.loads(_node(script))
    assert got["rc"] == 137 and got["ok"] is False


# ── ITEM 2: the positive assertion trio ─────────────────────────────────────

#: Each assertion, its utl::error code, and the token its message must carry.
TRIO = [
    ("9001", "VIBEIC_STA_NOT_LINKED", "sta::network_is_linked"),
    ("9002", "VIBEIC_STA_NO_TIMING_PATHS", "find_timing_paths -path_delay max"),
    ("9003", "VIBEIC_STA_VIRTUAL_CLOCK", "is_virtual"),
]


@pytest.mark.skipif(not NODE, reason="node not available")
def test_the_trio_is_asserted_and_each_names_itself():
    tcl = _node(CONJ + _fn("staAssertionTcl")
                + "\nconsole.log(staAssertionTcl({allowUnconstrained:false}));")
    for code, token, probe in TRIO:
        assert f"vibeic_fail {code}" in tcl, f"assertion {code} missing"
        assert token in tcl, f"assertion {code} does not name itself ({token})"
        assert probe in tcl, f"assertion {code} does not ask {probe}"
    # Asserted BEFORE any report is produced -- a report from an unlinked or
    # unconstrained design must never be generated at all.
    assert tcl.index("vibeic_fail 9001") < len(tcl)


@pytest.mark.skipif(not NODE, reason="node not available")
def test_the_trio_aborts_via_utl_error_so_it_rides_the_exit_code():
    """NOT by printing something for the server to scrape back out."""
    tcl = _node(CONJ + _fn("staAssertionTcl")
                + "\nconsole.log(staAssertionTcl({}));")
    assert "utl::error STA $code $msg" in tcl
    # MEASURED: the standalone `sta` binary has no utl::error, but plain Tcl
    # `error` aborts it with rc=1 all the same.
    assert "info commands utl::error" in tcl and 'error "\\[ERROR STA-$code\\]' in tcl


@pytest.mark.skipif(not NODE, reason="node not available")
def test_sta_template_asserts_before_it_reports():
    """In the real eda_sta script the trio must sit after create_clock and
    before the first report_checks."""
    src = _src()
    i = src.index("const staTcl = `")
    tcl_block = src[i:src.index("`;", i)]
    assert "staAssertionTcl(" in tcl_block
    assert tcl_block.index("staAssertionTcl(") < tcl_block.index("report_checks"), \
        "the assertions must run BEFORE any report is produced"


# ── the opt-out, and what it is not allowed to do ───────────────────────────

@pytest.mark.skipif(not NODE, reason="node not available")
def test_opt_out_relaxes_only_the_two_constrainedness_assertions():
    tcl = _node(CONJ + _fn("staAssertionTcl")
                + "\nconsole.log(staAssertionTcl({allowUnconstrained:true}));")
    assert "vibeic_fail 9002" not in tcl, "path-count assertion must relax"
    assert "vibeic_fail 9003" not in tcl, "virtual-clock assertion must relax"
    # ...but an UNLINKED network is never legitimate, for any caller.
    assert "vibeic_fail 9001" in tcl, \
        "allow_unconstrained must NEVER relax the linkage assertion"


def test_opt_out_is_exposed_on_both_sta_tools():
    src = _src()
    assert src.count("allow_unconstrained: z.boolean().default(false)") == 2, \
        "both eda_sta and eda_sta_mcorner must offer the opt-out"


def test_opt_out_records_unconstrained_never_pass():
    """A guard that blocks legitimate work gets bypassed, and a bypassed guard
    is a deleted guard -- so the opt-out exists. But what it buys is an
    UNCONSTRAINED record, never a passing timing verdict."""
    src = _src()
    assert "status: clockConstrained" in src
    assert '(clockConstrained ? (wns !== null && wns < 0 ? "TIMING_VIOLATED" : "PASS")' in src
    assert '"UNCONSTRAINED")' in src
    # and the slack of an unconstrained run stays null, not zero
    assert "const wns = clockConstrained" in src
    # Same property, following the parser: the inline regex was superseded by
    # lib/sta_slack.mjs (whole-line anchored, reads the bare `wns <n>` form and
    # scientific notation, returns null when the tool printed no such line).
    # What is pinned is unchanged -- tns stays gated on clockConstrained, so an
    # unconstrained run reports null and never a vacuous zero.
    assert "const tns = clockConstrained ? parseTns(result.output) : null;" in src


def test_a_real_violation_reaches_the_manifest_not_just_the_json():
    """MEASURED 2026-08-27: a 40-deep chain at 0.5 ns returned wns -12.10 ns,
    the JSON said TIMING_VIOLATED -- and the MANIFEST still said "PASS",
    because it keyed only on whether a clock had been found. Downstream flow
    steps read the manifest, so the violation has to reach it. This is the
    control that the gate did not go blind while being made honest."""
    src = _src()
    i = src.index('step: "sta",')
    manifest = src[i:src.index("});", i)]
    assert '"TIMING_VIOLATED"' in manifest, \
        "the STA manifest must be able to record a missed slack"
    assert 'status: clockConstrained ? "PASS"' not in manifest, \
        "a constrained run with negative slack must not be manifested PASS"


# ── absent is not in-bounds (the multi-corner regression) ───────────────────

def test_a_corner_that_produced_no_verdict_fails_the_set():
    """Previously only `met === false` cleared overall_pass, so a corner that
    failed outright -- no slack parsed, met null -- left the multi-corner
    verdict PASS. Absent is not the same as in-bounds."""
    src = _src()
    assert "if (met !== true) overall_pass = false;" in src
    assert "if (met === false) overall_pass = false;" not in src


def test_multicorner_distinguishes_not_analysed_from_violated():
    src = _src()
    assert '"NOT_ANALYSED"' in src
    assert "const allAnalysed = cornerVals.every(v => v.analysed);" in src


def test_multicorner_opt_out_is_unconstrained_not_violated():
    """MEASURED 2026-08-27: with allow_unconstrained set, all three corners
    analysed cleanly with met=null -- and the set was labelled TIMING_VIOLATED.
    That is a lie in the other direction: it says the design MISSED timing when
    it simply has none. UNCONSTRAINED is a third state, and it is still not a
    pass."""
    src = _src()
    assert "const allUnconstrained = cornerVals.length > 0" in src
    assert "allUnconstrained ? \"UNCONSTRAINED\"" in src


def test_ir_drop_keeps_its_deliberate_warn_path():
    """MEASURED 2026-08-27 on a real routed DEF: eda_ir_drop's Tcl `catch` around
    analyze_power_grid raised PDN-0217 + PSM-0069, caught them, and printed
    `=== IR_DROP_WARN ===` with rc 0 -- exactly as designed. Conjoining the
    metrics error count there turned that working run into a failure, because
    `utl::error` increments the counter even inside a catch. A deliberately
    caught error is a warning by this tool's own design; only an UNCAUGHT one
    aborts, and the exit code reports that. This is the one site where the
    conjunction must NOT apply, and it must stay that way."""
    src = _src()
    i = src.index("const irFailed = ")
    assert src[i:src.index("\n", i)].strip() == "const irFailed = irRun.rc !== 0;", \
        "eda_ir_drop must key on the exit code alone, or its WARN path breaks"


# ── the forbidden shortcuts ─────────────────────────────────────────────────

def test_sta_continue_on_error_is_never_set():
    """OpenSTA's sta_continue_on_error (tcl/Util.tcl:563,637-645) would make
    even a correct `-exit` report success."""
    src = _src()
    assert "sta_continue_on_error" not in src


def test_the_verdict_is_not_a_log_scrape():
    """The three mature projects (ORFS, LibreLane, OpenROAD) have exactly zero
    log-pattern scraping in their verdicts. The `[ERROR ...]` list this server
    still collects is DIAGNOSTIC: it must not appear in the pass/fail decision."""
    src = _src()
    i = src.index("const staAnalysed = ")
    decision = src[i:src.index("\n", i)]
    assert "staErrors" not in decision, \
        "the STA verdict must not be computed from a log scrape"
    # the sentinel likewise only corroborates -- MEASURED, a fully-failed
    # stdin run printed it anyway
    assert "const complete = sentinel && !openroadRunFailed(pnrRun);" in src


# ── the assertion trio, RUN rather than read ────────────────────────────────
#
# ADDED 2026-08-27 while reconciling this branch with main's landed `eda_sta`.
# Measured gap: deleting the linkage assertion (9001) or the virtual-clock
# assertion (9003) outright left the whole suite GREEN. The trio is the
# mechanism that answers "did STA actually do any work", and nothing could say
# no to its removal. A guard that cannot go red is not a guard.
#
# The Tcl is generated by the shipping `staAssertionTcl` and then EXECUTED under
# tclsh against stubbed timer state, so what is checked is what the assertions
# DO, not how they are spelled. `utl::error` does not exist in plain tclsh, and
# that is deliberate: it exercises `vibeic_fail`'s documented fallback, the same
# path the standalone `sta` binary takes.

TCLSH = shutil.which("tclsh")


def _assertion_tcl(allow_unconstrained: bool) -> str:
    """The Tcl the shipping generator emits, obtained by running it."""
    src = _src()
    i = src.index("function staAssertionTcl(")
    fn = src[i:src.index("\n}\n", i) + 3]
    script = (fn + "\nprocess.stdout.write(staAssertionTcl({ allowUnconstrained: "
              + ("true" if allow_unconstrained else "false") + " }));")
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _stub(linked: int, npaths: int, clocks: list[int], slack_ns: float | None) -> str:
    """A timer stubbed to one measured design shape. `clocks` is one entry per
    clock, 1 meaning virtual."""
    lines = [
        "namespace eval sta {}",
        f"proc sta::network_is_linked {{}} {{ return {linked} }}",
        "proc find_timing_paths {args} { return [list " +
        " ".join(f"p{i}" for i in range(npaths)) + "] }",
    ]
    for n, virt in enumerate(clocks):
        lines.append(f"proc _c{n} {{sub}} {{ return {virt} }}")
    lines.append("proc sta::all_clocks {} { return [list " +
                 " ".join(f"_c{n}" for n in range(len(clocks))) + "] }")
    if slack_ns is None:
        lines.append("proc sta::worst_slack_cmd {args} { error \"no paths\" }")
    else:
        lines.append(f"proc sta::worst_slack_cmd {{args}} {{ return {slack_ns / 1e9!r} }}")
    return "\n".join(lines) + "\n"


def _run_trio(shape, allow_unconstrained=False):
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as fh:
        fh.write(_stub(*shape) + _assertion_tcl(allow_unconstrained) + "\n")
        path = fh.name
    try:
        r = subprocess.run([TCLSH, path], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(path)
    return r


# The discrimination table the trio has to reproduce. Each row is
# (network_is_linked, timing paths, [is_virtual per clock], worst slack ns).
SHAPE_CLEAN = (1, 1, [0], 8.43)
SHAPE_VIOLATING = (1, 1, [0], -12.10)
SHAPE_UNLINKED = (0, 0, [], None)
SHAPE_NO_PATHS = (1, 0, [0], None)
# MEASURED shape of the clockless netlist: `create_clock` on a port the design
# does not have emits only `[WARNING STA-0366]` and still makes a clock — and
# that clock is genuinely VIRTUAL. It has no source pin, so it constrains
# nothing and the design has no timing path either.
SHAPE_CLOCKLESS = (1, 0, [1], None)
# A virtual clock WITH timing paths against it (`set_input_delay -clock
# virtual_clk` on an I/O-only block). This is the shape that isolates 9003:
# 9002 cannot fire, so only the virtual-clock assertion stands between a
# source-less clock and a vacuous `wns max 0.00` reported as a clean result.
SHAPE_VIRTUAL_CLOCK_WITH_PATHS = (1, 1, [1], 0.0)


@pytest.mark.skipif(not (NODE and TCLSH), reason="node + tclsh required")
def test_the_assertion_trio_refuses_a_run_that_did_no_work():
    """A design that linked nothing, analysed no path, or was constrained only
    by a source-less (virtual) clock must ABORT inside the Tcl, so the refusal
    rides the exit code instead of being scraped back out of the log."""
    for name, shape, code in [
        ("unlinked network", SHAPE_UNLINKED, "STA-9001"),
        ("no timing paths", SHAPE_NO_PATHS, "STA-9002"),
        ("a source-less clock over real paths", SHAPE_VIRTUAL_CLOCK_WITH_PATHS,
         "STA-9003"),
    ]:
        r = _run_trio(shape)
        assert r.returncode != 0, (
            f"{name}: the trio let a run that did no work through with rc 0; "
            f"stdout={r.stdout!r}")
        assert code in (r.stdout + r.stderr), (
            f"{name}: aborted, but not with {code}: {r.stdout + r.stderr!r}")


@pytest.mark.skipif(not (NODE and TCLSH), reason="node + tclsh required")
def test_the_assertion_trio_is_not_a_refusal_machine():
    """THE CONTROL. A gate that refuses everything proves nothing. A clean run
    and a genuine timing VIOLATION both keep linked=1, paths=1, virtual=0, so
    both must sail through the trio and be judged on slack afterwards."""
    for name, shape in [("clean", SHAPE_CLEAN), ("real violation", SHAPE_VIOLATING)]:
        r = _run_trio(shape)
        assert r.returncode == 0, (
            f"{name}: the trio refused a run it must let through — "
            f"{(r.stdout + r.stderr)!r}")
        assert "===VIBEIC_STA_FACTS===" in r.stdout


@pytest.mark.skipif(not (NODE and TCLSH), reason="node + tclsh required")
def test_the_facts_channel_reports_the_virtual_clock_it_refused_on():
    """The facts are emitted BEFORE the assertions precisely so a refused run
    still says WHY. A virtual clock has to be visible as a number, not inferred
    from a `[WARNING STA-0366]` line in the prose."""
    r = _run_trio(SHAPE_CLOCKLESS)
    assert r.returncode != 0, "the measured clockless netlist was not refused"
    assert "virtual_clocks 1" in r.stdout, r.stdout
    assert "clocks 1" in r.stdout


@pytest.mark.skipif(not (NODE and TCLSH), reason="node + tclsh required")
def test_allow_unconstrained_relaxes_only_the_constrainedness_assertions():
    """The opt-out exists so a legitimately unconstrained design stays runnable
    — a guard that blocks real work gets bypassed, and a bypassed guard is a
    deleted guard. It relaxes 9002 and 9003 and is recorded UNCONSTRAINED, and
    it must NEVER relax 9001: an un-linked network is never a legitimate
    design, so there is no caller for whom that would be a false positive."""
    r = _run_trio(SHAPE_CLOCKLESS, allow_unconstrained=True)
    assert r.returncode == 0, (
        "allow_unconstrained did not relax the virtual-clock assertion: "
        f"{(r.stdout + r.stderr)!r}")
    assert "unconstrained_allowed 1" in r.stdout

    r2 = _run_trio(SHAPE_UNLINKED, allow_unconstrained=True)
    assert r2.returncode != 0, (
        "allow_unconstrained relaxed the LINKAGE assertion; an un-linked "
        "network is never a legitimate design and there is no caller for whom "
        "letting it through would be correct")
    assert "STA-9001" in (r2.stdout + r2.stderr)
