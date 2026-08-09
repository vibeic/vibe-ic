"""`frame_end_gap_in_l8_check` could not reach its FAIL verdict from the caller
that runs it.

THE UNREACHABLE VERDICT
=======================
The gate's `main` ends::

    passed = not any(f.severity == "ERROR" for f in findings) or not args.strict
    ...
    return 1 if args.strict and not passed else 0

so rc 1 requires `--strict`. Its docstring names the caller that is supposed to
supply it ("use `--strict` to fail flow_compliance"). The P0 umbrella builds
this gate's argv in `flow_compliance_check._structural_gate_argv`, which for a
positional gate produced exactly `[python, <gate>.py, <project>]` — no
`--strict`, ever. `_eval_gate_worker` then reads rc 0 as the `PASS` tier. So on
a project the gate itself declares broken it printed
`[ERROR] L8_FRAME_END_GAP_MISSING` and was recorded as a passing checker. The
FAIL verdict was not rare; it was unreachable.

The seam for this already existed — `_STRUCTURAL_GATE_BARE_FLAGS`, written for
`fpga_wrapper_input_polluter_check` with the note that without `--strict` it
"would have added a checker that cannot fail for the reason it exists". But
`_structural_gate_argv` appended those flags ONLY inside the adapter branch, so
for any positional gate the table was inert: an entry would have read like a
wiring and done nothing. Both halves are fixed, and this test drives the REAL
builder rather than re-typing an argv, because a re-typed argv agrees with the
umbrella by coincidence.

WHY THE SEVERITY IS TIERED, AND WHY THAT IS NOT A WAY OUT OF THE BLAST RADIUS
============================================================================
Measured over the 137 tracked project directories before wiring anything: with
`--strict` and the gate as it stood, 12 went red. Every one of the 12 was
detected by the L1 free-text keyword arm alone — 0 of the 137 declare a
tSRS/ibt field at any depth in L2, 0 declare a command table with response
payloads — and 8 of the 12 matched one copied datasheet phrase. The gate's own
remedy is `frame_end_gap_us = L2.ibt_us[1] + margin`, which on those projects
is arithmetic on a value that does not exist, so the demand was for an invented
number: the exact defect the gate was written to prevent. Severity is therefore
decided by the detection tier — STRUCTURAL errors and can fail the flow,
keyword-only warns and is labelled `detection_strength: keyword` in the report.

POSITIVE (this file's second direction): a structurally-detected half-duplex
project that DOES carry the constant still exits 0 and still says PASS. A gate
that can only ever say FAIL is the same defect pointing the other way.

chip-AGNOSTIC: every fixture below is synthetic — no design, PDK or part
number, in the fixtures or in the assertions.
"""
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import flow_compliance_check as F  # noqa: E402

GATE = "frame_end_gap_in_l8_check"


def _docs(project: Path) -> Path:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _structural_half_duplex(project: Path) -> None:
    """L2 carrying BOTH a slave-response slot and an inter-byte-gap range —
    the arm that gives the gate a value to derive the constant from."""
    (_docs(project) / "L2_TIMING.json").write_text(json.dumps({
        "tSRS_min_us": 20.0,
        "ibt_us": [18.0, 22.0],
    }))


def _keyword_only_half_duplex(project: Path) -> None:
    """Free text alone: no timing range, no command table. A suspicion the
    gate cannot turn into a number."""
    (_docs(project) / "L1_DATASHEET.json").write_text(json.dumps({
        "modes": ["the link may operate half-duplex when negotiated"],
    }))


def _l8(project: Path, content: dict) -> None:
    (_docs(project) / "L8_RTL_CONSTANTS.json").write_text(json.dumps(content))


def _run_as_the_umbrella_does(project: Path, report: Path):
    """Run the gate through the argv the P0 umbrella itself constructs."""
    argv = F._structural_gate_argv(GATE, project, rtl_dir=project)
    argv += ["--json", str(report)]
    return subprocess.run(argv, cwd=project, capture_output=True, text=True,
                          timeout=60)


# ── direction 1: the FAIL verdict is now reachable from the real caller ──────

def test_umbrella_argv_reaches_the_fail_verdict(tmp_path):
    """FAILS against the unfixed program+caller: the same project produced
    rc 0 and a `passed: true` report while the gate printed an ERROR."""
    project = tmp_path / "proj"
    _structural_half_duplex(project)
    _l8(project, {"internal_clock_MHz": 50, "tSRS_min_ticks_50MHz": 1500})

    report = tmp_path / "rep.json"
    r = _run_as_the_umbrella_does(project, report)

    assert r.returncode == 1, (
        "the umbrella's own argv must be able to reach rc 1 on a project the "
        f"gate calls broken; got rc {r.returncode}\n{r.stdout}")
    rep = json.loads(report.read_text())
    assert rep["passed"] is False
    assert rep["verdict"] == "FAIL"
    assert rep["summary"]["detection_strength"] == "structural"
    assert [f["severity"] for f in rep["findings"]] == ["ERROR"]
    assert [f["rule"] for f in rep["findings"]] == ["L8_FRAME_END_GAP_MISSING"]


def test_the_fail_the_umbrella_records_names_the_rule(tmp_path):
    """`_eval_gate_worker` keeps a failing gate's FIRST stdout line as the
    evidence for the FAIL. A first line that only repeats the program name is
    a failure naming nothing."""
    project = tmp_path / "proj"
    _structural_half_duplex(project)  # no L8 at all

    r = _run_as_the_umbrella_does(project, tmp_path / "rep.json")

    assert r.returncode == 1
    first_line = r.stdout.strip().split("\n")[0]
    assert "FAIL" in first_line
    assert "L8_RTL_CONSTANTS_MISSING" in first_line


# ── direction 2: the gate did not become always-fail ─────────────────────────
#
# These three assert ONLY on fields that exist on both sides of the fix (rc,
# `passed`, `findings`, `summary.skipped_reason`), so they hold against the
# unfixed program as well. That is deliberate: a "still passes" test that
# fails on the old build proves nothing about always-failing — it just proves
# it was rewritten. The invariant is that these inputs return 0 BEFORE and
# AFTER.

def test_a_structural_project_that_carries_the_constant_still_passes(tmp_path):
    """Same detection arm, same argv, same `--strict` — the only difference is
    that the constant is present."""
    project = tmp_path / "proj"
    _structural_half_duplex(project)
    _l8(project, {"internal_clock_MHz": 50, "frame_end_gap_us": 27.0})

    report = tmp_path / "rep.json"
    r = _run_as_the_umbrella_does(project, report)

    assert r.returncode == 0, r.stdout
    rep = json.loads(report.read_text())
    assert rep["passed"] is True
    assert rep["findings"] == []
    assert rep["summary"]["frame_end_keys"] == ["frame_end_gap_us"]
    assert "PASS" in r.stdout


def test_a_project_with_no_half_duplex_indicator_still_passes(tmp_path):
    """The overwhelmingly common corpus shape — 125 of the 137 tracked project
    directories. Wiring `--strict` must not turn the untouched majority red."""
    project = tmp_path / "proj"
    (_docs(project) / "L1_DATASHEET.json").write_text(json.dumps(
        {"summary": "a parallel-bus peripheral"}))

    report = tmp_path / "rep.json"
    r = _run_as_the_umbrella_does(project, report)

    assert r.returncode == 0, r.stdout
    rep = json.loads(report.read_text())
    assert rep["summary"]["is_half_duplex"] is False
    assert rep["findings"] == []
    assert rep["summary"]["skipped_reason"] == "non-half-duplex project"


def test_the_declared_escape_hatches_survive_strict(tmp_path):
    """A project whose L3 delimits frames without a gap timeout is silent even
    with `--strict`, exactly as before."""
    project = tmp_path / "proj"
    _structural_half_duplex(project)
    (_docs(project) / "L3_CMD_PROTOCOL.json").write_text(json.dumps(
        {"frame_end_mechanism": "length_field"}))

    report = tmp_path / "rep.json"
    r = _run_as_the_umbrella_does(project, report)

    assert r.returncode == 0, r.stdout
    rep = json.loads(report.read_text())
    assert rep["findings"] == []
    assert "length_field" in rep["summary"]["skipped_reason"]


def test_the_waiver_escape_hatch_survives_strict(tmp_path):
    project = tmp_path / "proj"
    _structural_half_duplex(project)
    project.mkdir(parents=True, exist_ok=True)
    (project / "waivers.json").write_text(json.dumps({"waivers": [{
        "id": "frame_end_gap_alternative",
        "rationale": "framing is length-prefixed per the protocol spec",
    }]}))

    report = tmp_path / "rep.json"
    r = _run_as_the_umbrella_does(project, report)

    assert r.returncode == 0, r.stdout
    rep = json.loads(report.read_text())
    assert rep["findings"] == []
    assert "frame_end_gap_alternative" in rep["summary"]["skipped_reason"]


# ── the blast-radius guard: loud only where the evidence is ──────────────────

def test_keyword_only_detection_warns_and_does_not_fail_the_flow(tmp_path):
    """The 12/137 shape. Detected, disclosed, labelled — and not a FAIL,
    because the gate has no value it could tell the author to write down."""
    project = tmp_path / "proj"
    _keyword_only_half_duplex(project)

    report = tmp_path / "rep.json"
    r = _run_as_the_umbrella_does(project, report)

    assert r.returncode == 0, r.stdout
    rep = json.loads(report.read_text())
    assert rep["summary"]["is_half_duplex"] is True
    assert rep["summary"]["detection_strength"] == "keyword"
    assert rep["verdict"] == "WARN"
    assert [f["severity"] for f in rep["findings"]] == ["WARNING"]
    # Disclosed, not swallowed: the finding is still in the report and still
    # names the rule.
    assert rep["findings"][0]["rule"] == "L8_RTL_CONSTANTS_MISSING"


def test_keyword_text_plus_a_real_timing_range_is_structural(tmp_path):
    """The tier is decided by the evidence, not by which file mentioned it —
    a project with both the phrase AND the range fails."""
    project = tmp_path / "proj"
    _keyword_only_half_duplex(project)
    _structural_half_duplex(project)

    report = tmp_path / "rep.json"
    r = _run_as_the_umbrella_does(project, report)

    assert r.returncode == 1, r.stdout
    rep = json.loads(report.read_text())
    assert rep["summary"]["detection_strength"] == "structural"


# ── the caller-side mechanism, asserted on the built argv ────────────────────

def test_bare_flags_reach_a_positional_gate(tmp_path):
    """`_STRUCTURAL_GATE_BARE_FLAGS` was inert for every gate without an
    adapter. Asserted on the argv the builder RETURNS, not on its source."""
    argv = F._structural_gate_argv(GATE, tmp_path, rtl_dir=tmp_path)
    assert argv[-1] == "--strict"
    assert str(tmp_path) in argv          # still positional
    assert "--rtl-dir" not in argv        # still no adapter

    # and the adapter shape it already served is unchanged
    other = F._structural_gate_argv(
        "fpga_wrapper_input_polluter_check", tmp_path, rtl_dir=tmp_path)
    assert other[-1] == "--strict"
    assert "--rtl" in other


def test_a_gate_with_no_bare_flag_gets_none(tmp_path):
    """The append must not leak onto every gate."""
    for gate in ("self_rx_mask_check", "packet_length_check_present"):
        argv = F._structural_gate_argv(gate, tmp_path, rtl_dir=tmp_path)
        assert "--strict" not in argv, gate
