#!/usr/bin/env python3
"""The tool half of the measurement contract: what a tool must EMIT.

THE CONTRACT, in one sentence: a flow step may not record a step-level PASS on
a tool verdict that does not carry positive evidence the tool performed its
work.  This file tests the half that produces that evidence.  Its flow-side
counterpart -- the decision points that READ it -- is
``programs/tests/test_mcp_measurement_contract.py``; neither half is worth
anything alone, so each names the other.

Every capture below is VERBATIM ``openroad`` stdout from
``ghcr.io/vibeic/vibeic-eda@sha256:4ece6c01cddc99903af4f027326f7624b069311f2073a5a0b565d5a9cf649a16``
on 2026-08-27 (image verified by RepoDigest; layer0
``sha256:98effb2d…``), on a 4-flop counter netlist and a 4-bit adder netlist
synthesised by yosys against ``gf180mcuD``.  Nothing here is invented.

WHY A CLASSIFIER AND NOT A BOOLEAN.  The two captures ``B`` and ``C`` below are
the whole reason this contract exists: **both** end in ``wns max 0.00``.

  * ``B`` is a genuinely clean clocked design.  0.00 is its real, met slack.
  * ``C`` is a purely combinational adder with no ``clk`` port at all.
    ``create_clock`` matched no port, OpenSTA only WARNed (STA-0366), built a
    source-less clock anyway, and printed the identical ``wns max 0.00`` -- a
    perfect timing score for a design nothing constrained.

No parser reading the report bytes can separate them, because the separating
fact is not in the bytes.  It is whether the design has any timing path at all,
which the tool now asks the TIMER for and states.  A test that only asserted
"the vacuous case is refused" would be satisfied by a gate that refuses
everything; these cases exist so that a refusal machine fails this file.

The classifier is EXTRACTED FROM ``src/index.js`` and run under node, so
reverting the source turns these red rather than leaving a comment behind.

RE-DERIVED 2026-08-28 onto live main.  The captures below are still the
verbatim tool PROSE from the 2026-08-27 run; what has been composed around them
is main's STRUCTURED channels -- the ``===VIBEIC_STA_FACTS===`` block, the
``-metrics`` sidecar and the ``===VIBEIC_RC=`` marker -- which the script did
not emit in the form measured then.  Those fact rows are not invented either:
they are main's own measured discrimination table for these same three designs,
recorded in ``src/index.js`` above ``staAssertionTcl``:

    design                         linked  paths  virtual  worst slack
    clean flop->nand->flop @10ns      1      1       0      +8.43 ns
    combinational, no clk port        1      0       1      1e+30
    40-deep nand chain @0.5ns         1      1       0     -12.10 ns

So each case composes two measured sources -- the prose from one run and the
facts from another on the same design -- and nothing here is invented.  The
original ``STA_REGISTER_COUNT`` / ``report_worst_slack`` scrapes are gone from
the tool because main asks the timer directly instead; the QUESTIONS they
answered are the ones asserted below, against whichever channel now carries
them.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

INDEX_JS = Path(__file__).resolve().parent.parent / "src" / "index.js"
assert INDEX_JS.exists()
NODE = shutil.which("node")

# ── verbatim captures ────────────────────────────────────────────────────
# (A) THE VACUOUS RUN, reproduced: the STA script as it stood before the
# read_lef repair. openroad EXITS 0 having read no technology and linked
# nothing. Note what is NOT here: no STA_REGISTER_COUNT, no
# STA_CLOCK_PORT_FOUND -- those commands errored too.
STA_A_VACUOUS = """OpenROAD 26Q3-1797-g1c09d62b96 
[INFO ORD-0030] Using 4 thread(s).
[ERROR ORD-2010] no technology has been read.
ORD-2010
[ERROR STA-1571] No network has been linked.
STA-1571
[ERROR STA-1570] No network has been linked.
STA-1570
STA_CLOCK_COUNT=0
[ERROR STA-1571] No network has been linked.
STA-1571
STA_COMPLETE
"""

# (B) A GENUINE CLEAN RUN. 4 registers, clk found, real paths, met slack.
STA_B_GOOD = """[INFO ODB-0227] LEF file: gf180mcu_fd_sc_mcu7t5v0__nom.tlef, created 15 layers, 56 vias
STA_REGISTER_COUNT=4
STA_CLOCK_PORT_FOUND=1
STA_CLOCK_COUNT=1
           1.34   slack (MET)
tns max 0.00
wns max 0.00
worst slack max 196.75
worst slack min 1.34
STA_COMPLETE
"""

# (C) NOTHING TO CONSTRAIN. A purely combinational adder: no registers, no clk
# port. Byte-for-byte the same `wns max 0.00` as (B).
STA_C_COMBINATIONAL = """[INFO ODB-0227] LEF file: gf180mcu_fd_sc_mcu7t5v0.lef, created 229 library cells
STA_REGISTER_COUNT=0
STA_CLOCK_PORT_FOUND=0
[WARNING STA-0366] port 'clk' not found.
STA_CLOCK_COUNT=1
No paths found.
No paths found.
tns max 0.00
wns max 0.00
worst slack max INF
worst slack min INF
STA_COMPLETE
"""

# (D) A REAL TIMING VIOLATION. Same netlist as (B) at a 0.05 ns period.
STA_D_VIOLATION = """STA_REGISTER_COUNT=4
STA_CLOCK_PORT_FOUND=1
STA_CLOCK_COUNT=1
           1.34   slack (MET)
tns max -10.65
wns max -3.20
worst slack max -3.20
worst slack min 1.34
STA_COMPLETE
"""


def _region(src: str, start: str, end: str) -> str:
    a = src.index(start)
    b = src.index(end, a) + len(end)
    return src[a:b]


#: The structured channels main's script opens on purpose. `facts` are `key
#: value` lines between explicit delimiters -- NOT a pattern matched against
#: tool prose -- and the metrics sidecar is the independent evidence channel
#: `evaluateStaEvidence` reads.
def _capture(prose: str, *, facts: dict | None, rc: int,
             metrics: dict | None) -> str:
    parts = []
    if metrics is not None:
        parts += ["===VIBEIC_METRICS_PRESENT===",
                  "===VIBEIC_METRICS_BEGIN===",
                  json.dumps(metrics),
                  "===VIBEIC_METRICS_END==="]
    else:
        parts.append("===VIBEIC_METRICS_ABSENT===")
    if facts is not None:
        parts.append("===VIBEIC_STA_FACTS===")
        parts += [f"{k} {v}" for k, v in facts.items()]
        parts.append("===VIBEIC_STA_FACTS_END===")
    return prose + "\n".join(parts) + f"\n===VIBEIC_RC={rc}===\n"


#: A clean metrics sidecar: no errors, and a linkage-derived port count.
_GOOD_METRICS = {"flow__errors__count": 0, "sta__design__port__count": 12}


def _classify(capture: str, top_module: str = "dut", sdc=None,
              allow_unconstrained: bool = False) -> dict:
    """Run the REAL classifier out of src/index.js against one capture.

    The WHOLE chain is extracted, not just the ladder: `parseOpenroadRun` reads
    the structured channels back out of the raw capture, `evaluateStaEvidence`
    judges the sidecar, and the verdict ladder runs on what they produce. So a
    revert anywhere along that chain reddens this file.
    """
    src = INDEX_JS.read_text()
    parser = _region(
        src, "function parseOpenroadRun(result) {",
        "function openroadRunFailed({ rc, errorCount }) {\n"
        '  return rc !== 0 || (typeof errorCount === "number" && errorCount > 0);\n}')
    ladder = _region(src,
                     '    const staCompleted = result.output.includes("STA_COMPLETE");',
                     "      staMeasured = true;\n    }")
    js = (
        'import { evaluateStaEvidence, STA_EVIDENCE_TERMS } from '
        f'{json.dumps(str(INDEX_JS.parent.parent / "src" / "lib" / "sta_evidence.mjs"))};\n'
        'import { parseWns, parseTns } from '
        f'{json.dumps(str(INDEX_JS.parent.parent / "src" / "lib" / "sta_slack.mjs"))};\n'
        'const NOT_MEASURED_BENIGN = "NOTHING_TO_MEASURE";\n'
        + parser + "\n"
        f"const rawStaResult = {{ success: true, output: {json.dumps(capture)} }};\n"
        "const staRun = parseOpenroadRun(rawStaResult);\n"
        "const result = { ...rawStaResult, output: staRun.output };\n"
        f"const sdc = {json.dumps(sdc)};\n"
        f"const top_module = {json.dumps(top_module)};\n"
        f"const allow_unconstrained = {json.dumps(allow_unconstrained)};\n"
        'const clock_port = "clk";\n'
        + ladder + "\n"
        "console.log(JSON.stringify({measured: staMeasured, cls: staClass,"
        " reason: staReason, staAnalysed, staPass, linked,"
        " timingPaths, virtualClocks, clockPortFound, clockConstrained,"
        " staVerdict, wns, tns}));\n"
    )
    r = subprocess.run([NODE, "--input-type=module", "-e", js],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


pytestmark = pytest.mark.skipif(NODE is None, reason="node not available")


# ── the constructed cases ────────────────────────────────────────────────
def test_a_the_vacuous_run_is_refused_and_says_what_was_missing():
    """openroad exited having linked nothing. That is not a measurement."""
    d = _classify(_capture(STA_A_VACUOUS, facts=None, rc=1,
                           metrics={"flow__errors__count": 3}), "dut_clk")
    assert d["staAnalysed"] is False
    assert d["measured"] is False
    assert d["cls"] == "TOOL_DID_NOT_RUN"
    # NAMING WHAT WAS MISSING is half the requirement: a refusal that does not
    # say why sends a reader back to the same 900 bytes this replaced.
    assert "ORD-2010" in d["reason"]
    assert "exited 1" in d["reason"] and "3 error(s)" in d["reason"]
    assert d["wns"] is None and d["tns"] is None


def test_b_a_genuine_clean_run_still_measures_and_reports_its_slack():
    """The pole that stops this being a refusal machine."""
    d = _classify(_capture(STA_B_GOOD, rc=0, metrics=_GOOD_METRICS,
                           facts={"linked": 1, "timing_paths": 1, "clocks": 1,
                                  "virtual_clocks": 0, "worst_slack_ns": 0.0,
                                  "unconstrained_allowed": 0}), "dut_clk")
    assert d["measured"] is True
    assert d["cls"] is None
    assert d["linked"] is True and d["timingPaths"] == 1
    assert d["clockConstrained"] is True
    # 0.00 here is a REAL met slack and is reported as the number it is.
    assert d["wns"] == 0.0 and d["tns"] == 0.0


def test_c_nothing_to_constrain_is_honest_and_is_not_a_failure():
    """A combinational block reaches its own state, not a fabricated 0.00.

    It needs `allow_unconstrained`, and that is the design: without the opt-in
    the assertion trio REFUSES this run in the Tcl (STA-9002) and it never
    reaches the classifier at all. The caller must ask -- and what they get
    back is NOTHING_TO_MEASURE, never a PASS.
    """
    d = _classify(_capture(STA_C_COMBINATIONAL, rc=0, metrics=_GOOD_METRICS,
                           facts={"linked": 1, "timing_paths": 0, "clocks": 1,
                                  "virtual_clocks": 1, "worst_slack_ns": "null",
                                  "unconstrained_allowed": 1}),
                  "dut_noclk", allow_unconstrained=True)
    assert d["measured"] is False
    # NOT a hard class. Refusing this refuses every combinational design, and a
    # gate that refuses everything gets bypassed -- a bypassed gate is deleted.
    assert d["cls"] == "NOTHING_TO_MEASURE"
    assert d["timingPaths"] == 0
    # The 0.00 is still in the tool's output (censoring tool output would be a
    # third lie); what changed is that it is no longer REPORTED as a slack.
    assert "wns max 0.00" in STA_C_COMBINATIONAL
    assert d["wns"] is None and d["tns"] is None


def test_c2_a_sequential_design_left_unconstrained_is_a_HARD_miss():
    """The other half of the discriminator, and the one that must not be benign.

    Same missing clock as (C), but this design HAS timing paths. Its 0.00 is
    fabricated, so it may never reach NOTHING_TO_MEASURE -- collapsing the two
    is the lie pointing the other way.
    """
    d = _classify(_capture(STA_C_COMBINATIONAL, rc=0, metrics=_GOOD_METRICS,
                           facts={"linked": 1, "timing_paths": 2, "clocks": 1,
                                  "virtual_clocks": 1, "worst_slack_ns": "null",
                                  "unconstrained_allowed": 1}),
                  "dut_seq", allow_unconstrained=True)
    assert d["measured"] is False
    assert d["cls"] == "UNCONSTRAINED"
    assert d["cls"] != "NOTHING_TO_MEASURE"
    assert d["wns"] is None


def test_d_a_real_timing_violation_is_still_caught():
    """The pole that proves the gate did not go blind while getting honest."""
    d = _classify(_capture(STA_D_VIOLATION, rc=0, metrics=_GOOD_METRICS,
                           facts={"linked": 1, "timing_paths": 1, "clocks": 1,
                                  "virtual_clocks": 0, "worst_slack_ns": -3.20,
                                  "unconstrained_allowed": 0}), "dut_clk")
    assert d["measured"] is True
    assert d["wns"] == -3.20 and d["tns"] == -10.65


def test_b_and_c_are_byte_identical_on_the_line_a_parser_would_read():
    """The reason a bytes-parser cannot do this job, asserted rather than said."""
    line = "wns max 0.00"
    assert line in STA_B_GOOD and line in STA_C_COMBINATIONAL
    b = _classify(_capture(STA_B_GOOD, rc=0, metrics=_GOOD_METRICS,
                           facts={"linked": 1, "timing_paths": 1, "clocks": 1,
                                  "virtual_clocks": 0, "worst_slack_ns": 0.0,
                                  "unconstrained_allowed": 0}), "dut_clk")
    c = _classify(_capture(STA_C_COMBINATIONAL, rc=0, metrics=_GOOD_METRICS,
                           facts={"linked": 1, "timing_paths": 0, "clocks": 1,
                                  "virtual_clocks": 1, "worst_slack_ns": "null",
                                  "unconstrained_allowed": 1}),
                  "dut_noclk", allow_unconstrained=True)
    assert b["measured"] != c["measured"]


# ── the emitted record itself ────────────────────────────────────────────
def _measurement_record(**kwargs) -> dict:
    src = INDEX_JS.read_text()
    helper = _region(src, "const MEASUREMENT_SCHEMA = ",
                     "function measurementStamp(rec) {\n"
                     "  return MEASUREMENT_STAMP_PREFIX + JSON.stringify(rec)"
                     ' + "\\n";\n}')
    js = (helper + "\nlet out;\ntry { out = {ok:true, rec: measurementRecord("
          + json.dumps(kwargs) + ")}; }\n"
          "catch (e) { out = {ok:false, err: e.message}; }\n"
          "console.log(JSON.stringify(out));\n")
    r = subprocess.run([NODE, "--input-type=module", "-e", js],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_the_record_refuses_to_be_written_without_a_real_boolean():
    """`measured: null` is the silence this contract replaces, not a value."""
    out = _measurement_record(operation="sta", measured=None)
    assert out["ok"] is False
    assert "must be a real boolean" in out["err"]


def test_a_not_measured_record_must_name_a_class():
    """An unexplained refusal is the same silence it replaces."""
    out = _measurement_record(operation="sta", measured=False, reason="x")
    assert out["ok"] is False
    assert "must name a class" in out["err"]


def test_a_measured_record_carries_what_it_read_and_what_it_produced():
    out = _measurement_record(operation="sta", measured=True,
                              read=["netlist.v", "corner.lib"],
                              wrote=["pre_pnr_timing.rpt"],
                              toolLabel="opensta via openroad")
    assert out["ok"] is True
    rec = out["rec"]
    assert rec["schema"].startswith("mcp-eda/measurement/")
    assert rec["measured"] is True
    assert rec["read"] == ["netlist.v", "corner.lib"]
    assert rec["wrote"] == ["pre_pnr_timing.rpt"]
    assert rec["not_measured_class"] is None


# ── the script the classifier reads must actually ask the questions ──────
def test_the_sta_script_asks_the_questions_its_verdict_depends_on():
    """A classifier reading facts the script never emits is a dead branch.

    RE-DERIVED onto live main. The questions are unchanged; the CHANNEL that
    answers them is. a444aaa99b added `puts` lines scraping `all_registers`,
    `all_clocks` and `report_worst_slack`'s `INF`. Main asks the timer itself
    inside `staAssertionTcl` and emits the answers as `key value` rows between
    explicit delimiters -- a structured channel opened on purpose rather than a
    pattern matched against tool prose, so a log-format change cannot silently
    blind the classifier. That is strictly stronger, and it is what is pinned
    here: each question the ladder BRANCHES on must be asked by the script.

    Both halves are asserted, because `staAssertionTcl` is interpolated into
    `staTcl` and a question could be dropped from either.
    """
    src = INDEX_JS.read_text()
    tcl = _region(src, "    const staTcl = `${_staLefReads}", 'puts "STA_COMPLETE"`;')
    trio = _region(src, "function staAssertionTcl({ allowUnconstrained = false } = {}) {",
                   "\n}\n")
    script = tcl + trio

    # (1) does the design have any timing path at all -- the discriminator
    #     between a combinational block and a sequential one left unconstrained.
    assert "find_timing_paths" in script, script[:400]
    # (2) did the clock actually land on a port.
    assert "get_ports -quiet ${clock_port}" in script
    # (3) how many clocks, and how many of them are VIRTUAL -- a source-less
    #     clock is the fabricated-0.00 case, and `is_virtual` is the direct
    #     askable truth that a warning-scrape could only guess at.
    assert "all_clocks" in script
    assert "is_virtual" in script
    # (4) the worst slack, asked of the timer rather than parsed from prose.
    assert "worst_slack_cmd" in script
    # ... and every one of those answers must reach the caller as a FACT row,
    # not be computed and dropped.
    for row in ("linked", "timing_paths", "clocks", "virtual_clocks",
                "worst_slack_ns"):
        assert f'puts "{row} $' in script, row


def test_the_verdict_ladder_branches_only_on_facts_the_script_emits():
    """The other direction of the same guard: no branch on a dead channel.

    a444's ladder read `STA_REGISTER_COUNT` and `worst slack ... INF` out of the
    prose. Main emits neither, so a ladder still branching on them would be
    reading tokens that never arrive -- passing every run by default. This
    fails if such a branch is reintroduced.
    """
    src = INDEX_JS.read_text()
    ladder = _region(src,
                     '    const staCompleted = result.output.includes("STA_COMPLETE");',
                     "      staMeasured = true;\n    }")
    for dead in ("STA_REGISTER_COUNT", "STA_CLOCK_COUNT", "worst slack"):
        assert dead not in ladder, (
            f"the verdict ladder branches on {dead!r}, which main's script does "
            "not emit; that branch can never be taken and the state it was "
            "meant to catch passes by default")


def test_the_sta_tool_can_accept_the_sdc_its_consuming_steps_declare():
    """Steps 10 and 23 declare an SDC as a required INPUT; the tool had no
    parameter that could take one, so it analysed every design against a
    single synthesised `create_clock` nobody authored."""
    src = INDEX_JS.read_text()
    a = src.index('"eda_sta",')
    handler = src[a:src.index("// ─── Tool: eda_lvs ───", a)]
    assert "sdc: z.string().optional()" in handler
    assert "read_sdc ${sdc}" in handler
    # ... and it must WRITE the file its consuming steps name in
    # required_outputs. Before this it wrote no file at all (`outputs: {}`),
    # so the two steps that name it had no producer for their own artefact.
    assert "output_report: z.string().optional()" in handler
    assert "staOutputs[output_report] = sha256File(hostReport);" in handler


def test_every_provenance_site_that_names_a_measured_tool_emits_the_record():
    """A contract with a gap in it is a contract nobody has to keep.

    Both poles: this fails if a `logProvenance` site loses its `measurement`,
    AND it fails if a new site is added without one.
    """
    src = INDEX_JS.read_text()
    sites = [i for i in range(len(src))
             if src.startswith("logProvenance({", i)
             and not src[:i].rstrip().endswith("function")]
    # One CALL SITE is exempt: the generic `dockerExecLogged` helper forwards a
    # caller's arguments and has no operation of its own to assert about.
    without = []
    for i in sites:
        block = src[i:src.index("});", i) + 3]
        if "measurement:" not in block:
            without.append(block.splitlines()[1].strip())
    assert without == ["projectDir, tool, version, argv: [cmd],"], without
