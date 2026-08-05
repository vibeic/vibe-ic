"""BEHAVIOURAL CONTROL for the classified blocker list — the report's content.

WHY THIS IS A SEPARATE MODULE, and it is the whole point of the file.

The unit tests in `test_blocker_list_beside_the_tally.py` import
`_blocker_classification`, which this change introduces. Run against the
pre-change tree they do not fail on behaviour — they fail at COLLECTION, on
`ModuleNotFoundError`. A missing symbol fails whatever the behaviour is, so a
negative control counted from those tests measures nothing. That criticism was
made of another PR in this repo and it was correct.

This module imports NOTHING the change introduces. It drives
`flow_compliance_check` through its public CLI on an invented, PDK-free project
(pure DEF/JSON grammar, names chosen here) and asserts on the report the
program writes. On the pre-change tree it collects cleanly and every assertion
below fails on CONTENT: the report has no classified blocker list, stdout has
no block beside the tally, and no field names a root cause. Those are
behavioural failures, and they are what the PR's negative control is counted
from.

The last test is the hard constraint stated as a measurement rather than a
promise: with the classifier forced to raise, `overall`, `counts` and the exit
code must be byte-identical to the clean run. If a classification could ever
move a verdict, the classification would immediately be worth gaming — which
is the disease this whole change exists to diagnose.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

_PROGRAMS = Path(__file__).resolve().parents[1]
_FCC = _PROGRAMS / "flow_compliance_check.py"


_TINY_FLOW = {
    "version": "test",
    "flow_name": "blocker_list_probe",
    "total_steps": 3,
    "stages": {"stage_probe": "probe"},
    "steps": [
        {"id": 1, "name": "Emit netlist", "stage": "stage_probe",
         "required_outputs": ["build/netlist.json"],
         "gate": {"files_exist": ["build/netlist.json"]}, "blocks_on": []},
        {"id": 2, "name": "Emit floorplan", "stage": "stage_probe",
         "required_outputs": ["build/floorplan.def"],
         "gate": {"files_exist": ["build/floorplan.def"]}, "blocks_on": [1]},
        {"id": 3, "name": "Emit report", "stage": "stage_probe",
         "required_outputs": ["build/summary.json"],
         "gate": {"files_exist": ["build/summary.json"]}, "blocks_on": [2]},
    ],
}


def _run_probe(tmp_path, make_step1_pass: bool):
    """Drive `flow_compliance_check` through its CLI on an invented,
    PDK-free project: pure LEF/DEF/JSON grammar, names chosen here."""
    proj = tmp_path / ("pass" if make_step1_pass else "fail")
    (proj / "build").mkdir(parents=True)
    if make_step1_pass:
        (proj / "build" / "netlist.json").write_text('{"cells": []}\n')
    flow = tmp_path / "probe_flow.yaml"
    flow.write_text(yaml.safe_dump(_TINY_FLOW))
    out = proj / "report.json"
    proc = subprocess.run(
        [sys.executable, str(_FCC), str(proj), "--flow-def", str(flow),
         "--json", str(out)],
        capture_output=True, text=True, cwd=str(_PROGRAMS), timeout=300)
    return proc, json.loads(out.read_text())


# BEHAVIOURAL-CONTROL 1
def test_the_report_carries_a_classified_blocker_list(tmp_path):
    """The whole point, asserted on the artifact a consumer reads. Fails on the
    pre-change tree because the key is not there — a statement about the
    report's CONTENT, not about a symbol this change introduces."""
    proc, doc = _run_probe(tmp_path, make_step1_pass=False)
    assert "blockers" in doc, "the report publishes no classified blocker list"
    ids = [b["step_id"] for b in doc["blockers"]]
    assert ids == [1, 2, 3]
    for b in doc["blockers"]:
        assert b["classification"] in ("PLUGIN_DEFECT", "DESIGN_FACT",
                                       "MISSING_CAPABILITY", "UNCLASSIFIED")
        assert b["basis"].strip()
        assert b["measures"].strip()
    assert doc["blocker_class_counts"]["UNCLASSIFIED"] == 3
    assert doc["blocker_list_error"] == ""


# BEHAVIOURAL-CONTROL 2
def test_the_blocker_list_is_printed_beside_the_tally(tmp_path):
    """Beside the tally, on stdout, where the operator reads the verdict.
    Fails pre-change because the block is not printed."""
    proc, _ = _run_probe(tmp_path, make_step1_pass=False)
    assert "Blocker list (classified)" in proc.stdout
    assert re.search(r"PLUGIN_DEFECT=\d+\s+DESIGN_FACT=\d+\s+"
                     r"MISSING_CAPABILITY=\d+\s+UNCLASSIFIED=\d+",
                     proc.stdout), proc.stdout


# BEHAVIOURAL-CONTROL 3
def test_downstream_entries_name_their_root_cause(tmp_path):
    """41 blockers of which 36 are consequences of 4 is a different backlog
    from 41 independent ones. Fails pre-change: no report field carries it."""
    proc, doc = _run_probe(tmp_path, make_step1_pass=True)
    by_id = {b["step_id"]: b for b in doc["blockers"]}
    assert 1 not in by_id, "step 1 passed and must not be listed"
    assert by_id[2]["derived_from"] == []
    assert by_id[3]["derived_from"] == ["2"]


# BEHAVIOURAL-CONTROL 4
def test_no_classification_can_move_a_verdict(tmp_path):
    """THE HARD CONSTRAINT, measured rather than asserted in prose.

    The same run with the classifier forced to raise: `overall`, `counts` and
    the exit code must be byte-identical, and the report must SAY the list is
    empty because of the failure rather than letting an empty list read as a
    clean one.
    """
    proc_ok, doc_ok = _run_probe(tmp_path / "ok", make_step1_pass=False)

    sitecustomize = tmp_path / "boom"
    sitecustomize.mkdir()
    (sitecustomize / "usercustomize.py").write_text(
        "import _blocker_classification as b\n"
        "def _boom(*a, **k):\n"
        "    raise RuntimeError('forced classifier failure')\n"
        "b.build_blockers = _boom\n")
    proj = tmp_path / "boomproj"
    (proj / "build").mkdir(parents=True)
    flow = tmp_path / "probe_flow2.yaml"
    flow.write_text(yaml.safe_dump(_TINY_FLOW))
    out = proj / "report.json"
    env_path = f"{sitecustomize}:{_PROGRAMS}"
    proc_boom = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import usercustomize; "
         "sys.argv = ['flow_compliance_check.py', %r, '--flow-def', %r, "
         "'--json', %r]; "
         "import runpy; runpy.run_path(%r, run_name='__main__')"
         % (str(sitecustomize), str(proj), str(flow), str(out), str(_FCC))],
        capture_output=True, text=True, cwd=str(_PROGRAMS), timeout=300,
        env={"PYTHONPATH": env_path, "PATH": "/usr/bin:/bin"})
    doc_boom = json.loads(out.read_text())

    assert doc_boom["overall"] == doc_ok["overall"]
    assert doc_boom["counts"] == doc_ok["counts"]
    assert proc_boom.returncode == proc_ok.returncode
    assert doc_boom["blockers"] == []
    assert "forced classifier failure" in doc_boom["blocker_list_error"]
    assert "WARN" in proc_boom.stderr
