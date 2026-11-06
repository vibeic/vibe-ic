#!/usr/bin/env python3
"""ORGANIC #887 — a scan that examined ZERO files must not be a plain PASS,
AND the disclosure that says so must survive the consumer's fixed-width cut.

THE ORIGINAL DEFECT. Every exec-type clause the flow declares, run against ONE
empty directory: 27 exit 0, and 24 of those disclose why. Three do not.

    step 3   cdc_async_input_check        rc 0, 0 bytes on either stream
    step 3   reset_dependency_check       rc 0, 0 bytes on either stream
    step 14  yosys_script_template_check  rc 0, disclosure emitted but UNREAD

Their siblings on the SAME step-3 `all_of` answered the identical tree with
rc 1 (`cdc_crossing_check`) and rc 2 (`clock_domain_reg_crossing_check`).

THE REFUTATION VECTOR THIS FILE EXISTS TO PIN
=============================================
The FIRST fix made the two step-3 gates print a `VACUOUS_PASS:` sentinel — on a
line that interpolated the resolved project path. The consumer keeps only a
FIXED-WIDTH TAIL of each stream (`flow_compliance_check._OUTPUT_SNIPPET_CHARS`,
300) and matches the token AT LINE START, so once that line passed 300
characters the cut sliced the token off the front and the gate went silent
again. MEASURED — one gate, one empty project, ONE variable:

    cdc_async_input_check    path 123 chars: SEEN | 124: GONE, scored plain PASS
    reset_dependency_check   path 131 chars: SEEN | 132: GONE, scored plain PASS

Whether a blocking gate told the truth was a function of how deep the checkout
happened to sit. A test written against a short `tmp_path` PASSES on that fix.
That is why every case below is driven across the measured flip points, and why
the structural cases assert the property that makes the length irrelevant
rather than measuring the length that happens to fit today.

The third gate fails the same invariant from the other side: it printed a
recognised `VACUOUS_PASS_UNCONFIRMED:` line FIRST and then ~194 further
characters, so the 300-char tail kept the trailing note and dropped the token —
at EVERY path length, on a short `tmp_path` as surely as on a deep one.

THE INVARIANT, stated once: the stream that carries a gate's disclosure must
carry nothing whose length the caller controls. Then the tail cut is a no-op on
it, and the gate is honest at every checkout depth instead of at the depths its
message happens to fit under.

Chip-AGNOSTIC: no design, PDK, vendor or cell name appears anywhere below.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(PROGRAMS))
import _vacuous_exit as _vx  # noqa: E402

#: The two step-3 gates, with the gate-output JSON path step 3 gives each one.
STEP3_GATES = [
    ("cdc_async_input_check", "reports/phase2/gates/cdc_async_input.json"),
    ("reset_dependency_check", "reports/phase2/gates/cdc_reset_dep.json"),
]

#: Absolute project-path lengths to drive each gate at. 123/124 and 131/132 are
#: the MEASURED flip points of the refuted fix — one character apart, one on
#: each side of each. 400 is past any window the consumer could plausibly use.
#: Skipped (never silently passed) when `tmp_path` is already longer than the
#: target; `test_disclosure_survives_a_path_deeper_than_any_window` is built
#: RELATIVE to `tmp_path` and therefore can never be skipped.
FLIP_POINT_LENGTHS = [123, 124, 131, 132, 200, 400]

#: Minimal, correctly-synchronised RTL. Its only job is to be a NON-empty
#: authoritative scan corpus that both step-3 gates pass cleanly.
CLEAN_RTL = """\
module top(input clk, input rst_n, input data_pad);
  reg sync1, sync2;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin sync1 <= 0; sync2 <= 0; end
    else begin sync1 <= data_pad; sync2 <= sync1; end
  wire safe = sync2;
endmodule
"""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _dir_of_exact_length(base: Path, total: int) -> Path:
    """A freshly-created directory whose ABSOLUTE path is exactly `total` chars.

    Grows in DEPTH once a component approaches the 255-byte filename limit, so
    the lengths driven here are not capped by NAME_MAX.
    """
    stem = str(base / "p")
    pad = total - len(stem)
    if pad < 0:
        pytest.skip(f"tmp_path is already {len(stem)} chars; cannot build a "
                    f"{total}-char project path")
    comps: list[str] = []
    while pad > 0:
        take = min(pad, 200)
        # The first component is appended straight onto the stem; every later
        # one costs one extra character for the "/" separator.
        comps.append("x" * (take if not comps else take - 1))
        pad -= take
    proj = Path(stem + (comps[0] if comps else ""))
    for c in comps[1:]:
        proj = proj / c
    proj.mkdir(parents=True)
    assert len(str(proj)) == total, (len(str(proj)), total)
    return proj


def _run(gate: str, json_rel: str, root: Path) -> subprocess.CompletedProcess:
    """Invoke the gate exactly as its flow clause does: cwd = the project dir,
    positional `.`, `--json <path>` so the report goes to a FILE and stdout is
    left free."""
    return subprocess.run(
        [sys.executable, str(PROGRAMS / f"{gate}.py"), ".", "--json", json_rel],
        cwd=root, capture_output=True, text=True,
    )




def _step3_clause(gate: str, json_rel: str) -> dict:
    return {"program_exit_zero": f"{gate} . --json {json_rel}"}






#: The disclosure markers that take a step OUT of the executed-PASS numerator.
#: TWO since #1978 split the non-verdict reasons: a zero-file scan is
#: `ZERO_DENOMINATOR`, which that taxonomy puts in `INCOMPLETE` rather than in
#: `SKIP_ELIGIBLE` precisely because it "leave[s] the executed-PASS population
#: and require[s] follow-up". Naming both is not a widening — the assertion
#: that carries the weight is the `check_step` tier below, which is the
#: consumer this file's docstring is actually about.


# ---------------------------------------------------------------------------
# 1. THE REFUTATION VECTOR — path length must not decide whether a gate is
#    honest.
# ---------------------------------------------------------------------------






@pytest.mark.parametrize("gate", [g for g, _ in STEP3_GATES])
def test_the_emitter_is_bounded_at_import_time(gate):
    """The same property asked of the emitter directly, with no subprocess.

    It takes no project path — that omission IS the fix — so there is no
    argument through which a caller could grow the line. Pin that: one
    line-start sentinel, nothing after it, and a length fixed by module
    constants.
    """
    mod = __import__(gate)
    buf = io.StringIO()
    mod._emit_vacuous_disclosure(stream=buf)

    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 1, (
        f"{gate}'s disclosure stream is not a single line: {lines}")
    assert lines[0].lstrip().startswith(_vx.VACUOUS_STDOUT_SENTINEL), (
        f"{gate} emitted no line-start sentinel: {lines[0]!r}")


# ---------------------------------------------------------------------------
# 2. THE ORIGINAL DEFECT — end to end, through the production clause evaluator.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gate,json_rel", STEP3_GATES)
def test_exit_code_is_the_shared_input_missing_code(gate, json_rel, tmp_path):
    """rc 2, and the reason it is not merely cosmetic.

    `flow_compliance_check` reads these gates through TWO consumers.
    `__check_program_exit_zero` reads a truncated snippet on the rc-0 path but
    NOT on the rc-2 path (which returns `__VACUOUS_HINT__` without consulting
    the output at all), and the P0 structural-RTL umbrella's `_eval_gate_worker`
    classifies rc 0 as a plain PASS record WITHOUT READING EITHER STREAM. A
    printed sentinel alone leaves that second consumer misinformed, so the
    exit code has to carry it too.
    """
    proc = _run(gate, json_rel, tmp_path)
    assert proc.returncode == _vx.RC_VACUOUS, (
        f"{gate} answered a zero-file scan with rc={proc.returncode}; the P0 "
        f"umbrella records rc 0 as a plain PASS without reading any output")


@pytest.mark.parametrize("gate,json_rel", STEP3_GATES)
def test_report_json_records_the_verdict_it_printed(gate, json_rel, tmp_path):
    """The artefact must not certify a scan that never happened. The finding
    named this shape exactly: `files_scanned: 0` and `passed: true` in one
    object, with the evidence and the verdict never compared."""
    _run(gate, json_rel, tmp_path)
    report = json.loads((tmp_path / json_rel).read_text())
    assert report["summary"]["files_scanned"] == 0
    assert report.get("verdict") == "VACUOUS_PASS", (
        f"{gate} wrote files_scanned=0 beside passed={report.get('passed')!r} "
        f"with verdict={report.get('verdict')!r}")


# ---------------------------------------------------------------------------
# 3. THE DISCLOSURE MUST NOT OVER-FIRE.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("gate,json_rel", STEP3_GATES)
def test_real_rtl_is_still_a_plain_pass(gate, json_rel, tmp_path):
    """A gate that cried vacuous on every run would be exactly as uninformative
    as one that never did."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(CLEAN_RTL)
    # Setup only: this is the REGEX arm's check, which a project selects by
    # naming step 3 `direct` since the netlist became the default
    # (R-0929-TOOL-DEFAULT); the netlist arm's twin is below.
    (tmp_path / "phase3").mkdir()
    (tmp_path / "phase3" / "librelane_switch.json").write_text(
        json.dumps({"steps": {"3": "direct"}}))

    proc = _run(gate, json_rel, tmp_path)
    assert proc.returncode == _vx.RC_PASS

    report = json.loads((tmp_path / json_rel).read_text())
    assert report["summary"]["files_scanned"] >= 1
    assert report.get("verdict") == "PASS"



@pytest.mark.parametrize("gate,json_rel", STEP3_GATES)
def test_a_real_finding_still_fails(gate, json_rel, tmp_path):
    """FAIL beats VACUOUS. A gate that answered rc 2 for a tree it found a
    violation in would have hidden the violation behind the new tier."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    # Unsynchronised async input AND a self-referential reset combine: one of
    # the two gates fires on each. Whichever it is, the answer must be rc 1.
    (rtl / "top.v").write_text(
        "module top(input clk, input rst_n, input data_pad);\n"
        "  reg q;\n"
        "  always @(posedge clk) q <= data_pad;\n"
        "endmodule\n")
    proc = _run(gate, json_rel, tmp_path)
    report = json.loads((tmp_path / json_rel).read_text())
    if report["passed"]:
        pytest.skip(f"{gate} finds nothing in this fixture; the FAIL path is "
                    f"pinned by its own gate test")
    assert proc.returncode == _vx.RC_FAIL, (
        f"{gate} reached a FAIL verdict but exited {proc.returncode}")
    assert report.get("verdict") == "FAIL"


# ---------------------------------------------------------------------------
# 4. THE THIRD SILENT GATE — same invariant, opposite cause.
# ---------------------------------------------------------------------------
def _yosys_project(tmp_path: Path, path_len: int | None = None) -> Path:
    """A tree in step 14's own reachable shape: `phase2/stage2/synth` EXISTS
    (so the optional clause's `condition_files_exist` fires and the gate runs)
    but holds no `.ys` script and no handoff netlist."""
    proj = (_dir_of_exact_length(tmp_path, path_len)
            if path_len is not None else tmp_path)
    (proj / "phase2" / "stage2" / "synth").mkdir(parents=True)
    return proj


def _run_yosys(proj: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "yosys_script_template_check.py"), ".",
         "--json", "reports/phase2/gates/yosys_script_template.json"],
        cwd=proj, capture_output=True, text=True)


@pytest.mark.parametrize("path_len", [None] + FLIP_POINT_LENGTHS)
def test_yosys_script_template_disclosure_reaches_the_consumer(
        path_len, tmp_path):
    """It ALWAYS emitted a recognised token; the consumer never saw it, because
    ~194 characters of trailing note evicted the ~249-char sentinel line from
    the 300-char tail. Path-length INDEPENDENT, so `None` — an ordinary short
    `tmp_path` — is itself a failing case on the unfixed program."""
    proj = _yosys_project(tmp_path, path_len)
    proc = _run_yosys(proj)

    assert proc.returncode == 0
    full = (proc.stdout or "") + "\n" + (proc.stderr or "")






def test_yosys_does_not_disclose_when_it_audited_a_real_script(tmp_path):
    """Over-fire control. A project with a genuine synthesis recipe is examined,
    not skipped, and must stay a plain PASS."""
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "synth.ys").write_text(
        "read_verilog -sv top.v\n"
        "synth -top top -flatten\n"
        "dfflibmap -liberty lib.lib\n"
        "hilomap -hicell TIEHI Y -locell TIELO Y\n"
        "write_verilog netlist.v\n")
    (synth / "netlist.v").write_text("module top(); endmodule\n")
    proc = _run_yosys(tmp_path)
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# 5. THE SIBLINGS THAT WERE ALREADY HONEST — a control, so a change that broke
#    them would not be read as this fix working.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("gate,expected_rc", [
    ("cdc_crossing_check", 1),
    ("clock_domain_reg_crossing_check", 2),
])
def test_the_honest_siblings_are_unchanged(gate, expected_rc, tmp_path):
    proc = _run(gate, "reports/phase2/gates/x.json", tmp_path)
    assert proc.returncode == expected_rc, (
        f"{gate} answered the empty tree with rc={proc.returncode}, not "
        f"rc={expected_rc}; the four step-3 clauses no longer agree the way "
        f"the finding measured them")


def _bound_clean_netlist(tmp_path):
    """Replay the source-owned native capture through production build/binding.

    Only the Yosys execution seam is substituted; this fixture does not claim
    live EDA. Discovery, source hashes, manifest and both gate CLIs are real.
    """
    from test_t91_step3_cdc_netlist_front_end import _produce
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(CLEAN_RTL)
    fix = PROGRAMS / "tests" / "fixtures" / "cdc_netlist" / "clean_sync.json"
    return _produce(tmp_path, fix)


@pytest.mark.parametrize("gate,json_rel", STEP3_GATES)
def test_real_rtl_with_its_netlist_is_a_plain_pass_by_default(gate, json_rel,
                                                             tmp_path):
    """Default frontend: current bound CLEAN_RTL capture is nonvacuous PASS."""
    _bound_clean_netlist(tmp_path)
    proc = _run(gate, json_rel, tmp_path)
    assert proc.returncode == _vx.RC_PASS, proc.stdout + proc.stderr
    report = json.loads((tmp_path / json_rel).read_text())
    assert report["summary"]["files_scanned"] >= 1
    assert report["summary"]["front_end"] == "netlist"
    assert report.get("verdict") == "PASS"


@pytest.mark.parametrize("gate,json_rel", STEP3_GATES)
@pytest.mark.parametrize("fault", ["unbound", "changed-source", "partial-read"])
def test_captured_clean_netlist_needs_current_complete_binding(gate, json_rel, tmp_path, fault):
    import _cdc_netlist as cn
    netlist = _bound_clean_netlist(tmp_path)
    before = netlist.read_bytes()
    manifest = tmp_path / cn.NETLIST_MANIFEST_REL
    if fault == "unbound":
        manifest.unlink()
    elif fault == "changed-source":
        source = tmp_path / "phase2/stage1/rtl/top.v"
        source.write_text(source.read_text() + "\n// current input changed\n")
    else:
        rec = json.loads(manifest.read_text())
        rec["producer"]["read_order"] = []
        manifest.write_text(json.dumps(rec))
    proc = _run(gate, json_rel, tmp_path)
    assert proc.returncode != _vx.RC_PASS
    report = json.loads((tmp_path / json_rel).read_text())
    assert report.get("verdict") == "FAIL"
    assert report["summary"]["netlist_read"] is False
    assert netlist.read_bytes() == before
