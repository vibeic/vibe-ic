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
fact is not in the bytes.  It is ``STA_REGISTER_COUNT`` and ``worst slack max
INF``, which the tool now asks for and states.  A test that only asserted "the
vacuous case is refused" would be satisfied by a gate that refuses everything;
these four cases exist so that a refusal machine fails this file.

The classifier is EXTRACTED FROM ``src/index.js`` and run under node, so
reverting the source turns these red rather than leaving a comment behind.
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


def _classify(capture: str, top_module: str = "dut", sdc=None) -> dict:
    """Run the REAL classifier out of src/index.js against one capture."""
    src = INDEX_JS.read_text()
    block = _region(src, "    const wnsMatch = result.output.match(/^wns",
                    "      staMeasured = true;\n    }")
    js = (
        'const NOT_MEASURED_BENIGN = "NOTHING_TO_MEASURE";\n'
        f"const result = {{ success: true, output: {json.dumps(capture)} }};\n"
        f"const sdc = {json.dumps(sdc)};\n"
        f"const top_module = {json.dumps(top_module)};\n"
        'const clock_port = "clk";\n'
        f"{block}\n"
        "console.log(JSON.stringify({measured: staMeasured, cls: staClass,"
        " reason: staReason, registerCount, clockPortFound,"
        " worstSlackNoPath, staAnalysed,"
        " wns: staMeasured && wnsMatch ? parseFloat(wnsMatch[1]) : null,"
        " tns: staMeasured && tnsMatch ? parseFloat(tnsMatch[1]) : null}));\n"
    )
    r = subprocess.run([NODE, "--input-type=module", "-e", js],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


pytestmark = pytest.mark.skipif(NODE is None, reason="node not available")


# ── the four constructed cases ───────────────────────────────────────────
def test_a_the_vacuous_run_is_refused_and_says_what_was_missing():
    """openroad exited 0 having linked nothing. That is not a measurement."""
    d = _classify(STA_A_VACUOUS, "dut_clk")
    assert d["staAnalysed"] is False
    assert d["measured"] is False
    assert d["cls"] == "TOOL_DID_NOT_RUN"
    # NAMING WHAT WAS MISSING is half the requirement: a refusal that does not
    # say why sends a reader back to the same 900 bytes this replaced.
    assert "ORD-2010" in d["reason"]
    assert "exit code was 0" in d["reason"]
    assert d["wns"] is None and d["tns"] is None


def test_b_a_genuine_clean_run_still_measures_and_reports_its_slack():
    """The pole that stops this being a refusal machine."""
    d = _classify(STA_B_GOOD, "dut_clk")
    assert d["measured"] is True
    assert d["cls"] is None
    assert d["registerCount"] == 4 and d["clockPortFound"] is True
    # 0.00 here is a REAL met slack and is reported as the number it is.
    assert d["wns"] == 0.0 and d["tns"] == 0.0


def test_c_nothing_to_constrain_is_honest_and_is_not_a_failure():
    """A combinational block reaches its own state, not a fabricated 0.00."""
    d = _classify(STA_C_COMBINATIONAL, "dut_noclk")
    assert d["measured"] is False
    # NOT a hard class. Refusing this refuses every combinational design, and a
    # gate that refuses everything gets bypassed -- a bypassed gate is deleted.
    assert d["cls"] == "NOTHING_TO_MEASURE"
    assert d["registerCount"] == 0
    assert d["worstSlackNoPath"] is True
    # The 0.00 is still in the tool's output (censoring tool output would be a
    # third lie); what changed is that it is no longer REPORTED as a slack.
    assert "wns max 0.00" in STA_C_COMBINATIONAL
    assert d["wns"] is None and d["tns"] is None


def test_d_a_real_timing_violation_is_still_caught():
    """The pole that proves the gate did not go blind while getting honest."""
    d = _classify(STA_D_VIOLATION, "dut_clk")
    assert d["measured"] is True
    assert d["wns"] == -3.20 and d["tns"] == -10.65


def test_b_and_c_are_byte_identical_on_the_line_a_parser_would_read():
    """The reason a bytes-parser cannot do this job, asserted rather than said."""
    line = "wns max 0.00"
    assert line in STA_B_GOOD and line in STA_C_COMBINATIONAL
    b = _classify(STA_B_GOOD, "dut_clk")
    c = _classify(STA_C_COMBINATIONAL, "dut_noclk")
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
def test_the_sta_script_asks_the_three_questions_its_verdict_depends_on():
    """A classifier reading tokens the script never prints is a dead branch.

    ``report_worst_slack`` is the load-bearing one: ``worst slack ... INF`` is
    the repo's ONLY empty-path-set sentinel (``sta_corner_record_completeness_
    check._WORST_SLACK_NO_PATH_RE``), and MEASURED 2026-08-27 this tool's TCL
    never ran the command that produces it -- so it emitted the vacuous shape
    minus the single token that detects it.
    """
    src = INDEX_JS.read_text()
    a = src.index('const staCmd = `export PATH=${TOOLS}/openroad/bin')
    script = src[a:src.index("EOF`;", a)]
    assert "all_registers" in script
    assert "get_ports -quiet ${clock_port}" in script
    assert "report_worst_slack -max" in script
    assert "report_worst_slack -min" in script
    assert "all_clocks" in script


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
