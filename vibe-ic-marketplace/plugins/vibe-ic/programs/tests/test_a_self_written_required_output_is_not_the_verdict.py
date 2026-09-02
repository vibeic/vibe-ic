#!/usr/bin/env python3
"""A `required_outputs` entry its own refusal writes is not evidence of a pass.

THE NOTE THIS FILE EXISTS TO REPLACE. The observation below was recorded in ONE
place — the `undeclared_scope_expanded` field of
`flow_gate_enforcement_baseline.json` — and `--record-shrink` cleared that field
to `null`, after which it existed nowhere in the tree:

    sdc_syntax_check additionally carries a real hole worth its own issue:
    flow declares both required_outputs reports/phase2/sdc_check.json and
    program_exit_zero, but the program writes that JSON UNCONDITIONALLY before
    exiting 1, so a project with no valid SDC still satisfies the presence gate
    and phase 2 proceeds.

Prose in a register is not a guard. This file is the same claim as executable
rows, so the next `--record-shrink` cannot take it with it.

WHAT RE-MEASURES TRUE, at 6f781d297 (v1.16.24):
  * `sdc_syntax_check.py` on a project with NO SDC exits 1 and STILL writes
    `reports/phase2/sdc_check.json` carrying `passed: false` / `NO_SDC_FILE`.
  * With only the presence entry — the judging clause removed from a COPY of
    the flow — step 8's own verdict on that project is a PASS
    (`PASS_VOIDED_BY_DEPENDENCY`: the step passed, and only an upstream
    dependency voided it). The presence entry cannot fail.

AND THE HALF THAT DOES NOT. "and phase 2 proceeds" is FALSE at this tip. The
same `gate.all_of` carries
`program_exit_zero: "sdc_syntax_check . --json reports/phase2/sdc_check.json"`,
and with it step 8 on that same project is **FAIL**. The refusal is not lost.
So the defect is the narrower one the brief names: an entry in the denominator
that judges nothing — harmless only while its judging sibling exists.

WHY THE ENTRY IS NOT DELETED. It is not a step-8 bug and deleting it would fix
one instance of an idiom: **37 (step, output) pairs are `required_outputs`
entries that are also the `--json` target of their own gate clause**, measured
here by `test_the_self_written_output_idiom_is_declared_not_incidental`. (I
first counted 42 with a loop that appended once per MATCHING CLAUSE rather than
once per entry; 37 is the de-duplicated count and it is the one this file
asserts.) The entry is
also TRUE — the step really does produce that file, always, and that is what
`required_outputs` declares. What must never be lost is the sibling that judges
it, so that is what these rows pin.

BLOCKING: these are tests, not a gate. They fail the suite; they do not stop a
design's flow. The thing that stops a design is the `program_exit_zero` clause
whose continued existence they assert.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
_SDC_CHECK = _PROGRAMS / "sdc_syntax_check.py"
_COMPLIANCE = _PROGRAMS / "flow_compliance_check.py"

_REPORT_REL = "reports/phase2/sdc_check.json"
_CLAUSE = ('        - program_exit_zero: "sdc_syntax_check . --json '
           'reports/phase2/sdc_check.json"\n')


def _no_sdc_project(tmp_path):
    """A project with RTL and no SDC at all. Synthesised, no design literal."""
    p = tmp_path / "proj"
    (p / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (p / "reports" / "phase2").mkdir(parents=True)
    (p / "phase2" / "stage1" / "rtl" / "probe.v").write_text(
        "module probe (input clk, output out);\n"
        "  assign out = clk;\nendmodule\n", encoding="utf-8")
    return p


def _step8_verdict(project, flow_def=None):
    out = project.parent / "fc.json"
    cmd = [sys.executable, str(_COMPLIANCE), str(project), "--read-only",
           "--json", str(out)]
    if flow_def is not None:
        cmd += ["--flow-def", str(flow_def)]
    _pr.run(cmd, capture_output=True, text=True)
    doc = json.loads(out.read_text())

    def rows(o):
        if isinstance(o, list):
            for x in o:
                yield from rows(x)
        elif isinstance(o, dict):
            if ("id" in o or "step" in o) and ("verdict" in o or "status" in o):
                yield o
            for v in o.values():
                yield from rows(v)
    for x in rows(doc):
        if str(x.get("id") or x.get("step")) == "8":
            return str(x.get("verdict") or x.get("status"))
    raise AssertionError("step 8 is not in the compliance report")


@pytest.fixture(scope="module")
def flow_doc():
    return yaml.safe_load(_FLOW.read_text())


def test_the_refusal_writes_the_required_output_it_is_judged_by(tmp_path):
    """The presence entry is satisfied BY THE REFUSAL. This is the mechanism
    the deleted note described, and it is why presence is not evidence."""
    p = _no_sdc_project(tmp_path)
    r = _pr.run([sys.executable, str(_SDC_CHECK), ".", "--json", _REPORT_REL],
                cwd=str(p), capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    report = p / _REPORT_REL
    assert report.is_file(), "the refusal did not write the required output"
    doc = json.loads(report.read_text())
    assert doc["passed"] is False, doc
    assert "NO_SDC_FILE" in [f["rule"] for f in doc["findings"]], doc


def test_the_step_still_refuses_and_still_discloses_why(tmp_path):
    """BOTH halves the brief requires: the refusal reaches the step verdict AND
    the report documenting it survives. Making the program stop writing on
    failure would close the hole by deleting the only evidence of WHY —
    `phase3_one_shot_runner` relies on that report existing to disclose
    findings it does not block on."""
    p = _no_sdc_project(tmp_path)
    _pr.run([sys.executable, str(_SDC_CHECK), ".", "--json", _REPORT_REL],
            cwd=str(p), capture_output=True, text=True)
    assert _step8_verdict(p) == "FAIL"
    doc = json.loads((p / _REPORT_REL).read_text())
    assert doc["passed"] is False and doc["findings"], doc


def test_negative_arm_without_the_judging_clause_the_step_passes(tmp_path):
    """THE ARM THAT MAKES THE ROW ABOVE MEAN SOMETHING.

    Remove the `program_exit_zero` clause from a COPY of the flow and step 8's
    own verdict on a project with NO SDC becomes a pass — voided only by an
    upstream dependency, never by anything step 8 asked. That is the presence
    entry judging nothing, demonstrated rather than asserted."""
    p = _no_sdc_project(tmp_path)
    _pr.run([sys.executable, str(_SDC_CHECK), ".", "--json", _REPORT_REL],
            cwd=str(p), capture_output=True, text=True)
    text = _FLOW.read_text()
    assert text.count(_CLAUSE) == 1, "the step-8 clause moved; update _CLAUSE"
    mutated = tmp_path / "flow.yaml"
    mutated.write_text(text.replace(_CLAUSE, ""), encoding="utf-8")
    verdict = _step8_verdict(p, flow_def=mutated)
    assert verdict != "FAIL", verdict
    assert verdict.startswith("PASS"), (
        f"expected the presence entry alone to pass; got {verdict}")


def test_the_judging_clause_is_still_declared(flow_doc):
    """What must never be lost. The presence entry is harmless only while this
    clause stands beside it; delete the clause and the row above is what the
    flow does."""
    step = next(s for s in flow_doc["steps"] if str(s.get("id")) == "8")
    assert _REPORT_REL in (step.get("required_outputs") or []), step
    cmds = [c["program_exit_zero"]
            for c in (step["gate"].get("all_of") or [])
            if isinstance(c, dict) and "program_exit_zero" in c]
    assert any(_REPORT_REL in c and c.startswith("sdc_syntax_check")
               for c in cmds), cmds


def test_the_self_written_output_idiom_is_declared_not_incidental(flow_doc):
    """The population, so nobody repairs step 8 believing it is one of one.

    A `required_outputs` entry that is also its own gate clause's `--json`
    target is a flow-wide IDIOM: the entry declares what the step produces, and
    the clause is what judges it. Measured at 6f781d297: 37 such (step, output)
    pairs. Every one is presence-that-cannot-fail, and every one is accompanied
    by the clause that can — which is the invariant, not the absence of the
    entry.

    THE FLOOR HAS SLACK ON PURPOSE. An exact count would redden on any
    unrelated flow edit that adds or drops a step, which is how a census pin
    becomes something people refresh without reading. A floor of 30 under a
    measured 37 still refuses the thing this row is for: entries deleted one at
    a time on the theory that step 8's was a bug."""
    pairs = []
    for s in flow_doc["steps"]:
        cmds = [c["program_exit_zero"]
                for c in ((s.get("gate") or {}).get("all_of") or [])
                if isinstance(c, dict) and "program_exit_zero" in c]
        for out in (s.get("required_outputs") or []):
            if any(isinstance(c, str) and out in c for c in cmds):
                pairs.append((str(s.get("id")), out))
    assert len(pairs) >= 30, (
        f"the idiom has shrunk to {len(pairs)} from a measured 37; if entries "
        f"were deleted one at a time, say so — this file exists because "
        f"deleting step 8's alone would repair nothing and misdescribe the "
        f"class")
    assert ("8", _REPORT_REL) in pairs, pairs[:5]
