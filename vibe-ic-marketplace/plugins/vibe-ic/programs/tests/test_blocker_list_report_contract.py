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
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

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
    proc = _pr.run(
        [sys.executable, str(_FCC), str(proj), "--flow-def", str(flow),
         "--json", str(out)],
        capture_output=True, text=True, cwd=str(_PROGRAMS))
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
    assert "blockers" in doc, ("the report carries no blocker list, so nothing "
                               "names a root cause")
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

    The injected shim TOLERATES the classifier being absent on purpose, so
    that on the pre-change tree this test still runs the program to completion
    and fails on the two CONTENT assertions at the bottom rather than on an
    import — a control that dies of a missing module measures the module's
    existence, not the behaviour.
    """
    proc_ok, doc_ok = _run_probe(tmp_path / "ok", make_step1_pass=False)

    sitecustomize = tmp_path / "boom"
    sitecustomize.mkdir()
    (sitecustomize / "usercustomize.py").write_text(
        "try:\n"
        "    import _blocker_classification as b\n"
        "except Exception:\n"
        "    b = None\n"
        "def _boom(*a, **k):\n"
        "    raise RuntimeError('forced classifier failure')\n"
        "if b is not None:\n"
        "    b.build_blockers = _boom\n")
    proj = tmp_path / "boomproj"
    (proj / "build").mkdir(parents=True)
    flow = tmp_path / "probe_flow2.yaml"
    flow.write_text(yaml.safe_dump(_TINY_FLOW))
    out = proj / "report.json"
    env_path = f"{sitecustomize}:{_PROGRAMS}"
    proc_boom = _pr.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import usercustomize; "
         "sys.argv = ['flow_compliance_check.py', %r, '--flow-def', %r, "
         "'--json', %r]; "
         "import runpy; runpy.run_path(%r, run_name='__main__')"
         % (str(sitecustomize), str(proj), str(flow), str(out), str(_FCC))],
        capture_output=True, text=True, cwd=str(_PROGRAMS),
        env={"PYTHONPATH": env_path, "PATH": "/usr/bin:/bin"})
    doc_boom = json.loads(out.read_text())

    # the verdict half — true on BOTH trees, which is the point: a classifier
    # that could move a verdict would break these, and nothing else would.
    assert doc_boom["overall"] == doc_ok["overall"]
    assert doc_boom["counts"] == doc_ok["counts"]
    assert proc_boom.returncode == proc_ok.returncode
    # the disclosure half — content, and the part that fails pre-change
    assert doc_boom.get("blockers") == [], (
        "a run whose classifier raised must still publish an explicit empty "
        "list, not silence")
    assert "forced classifier failure" in doc_boom.get("blocker_list_error", ""), (
        "an empty list produced by a crash must not be indistinguishable from "
        "a clean one")
    assert "WARN" in proc_boom.stderr


# BEHAVIOURAL-CONTROL 5 — the commercial-tool narrowing, end to end.
#
# The review of this PR named the gap: reverting the producer's `_oss_deferred`
# construction from the run's OWN deferral decisions to bare membership of
# `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS` passed the whole suite, even though it
# is a change in the fabricating direction (a step whose gate reached a verdict,
# or a downstream cascade, flips to MISSING_CAPABILITY/commercial-tool-required).
# This drives the REAL producer CLI so the narrowing wiring in
# `flow_compliance_check.main` is what is under test, not a re-statement of it.
_OSS_MEMBER_FLOW = {
    "version": "test",
    "flow_name": "oss_membership_probe",
    "total_steps": 3,
    "stages": {"stage_probe": "probe"},
    "steps": [
        {"id": 1, "name": "Emit netlist", "stage": "stage_probe",
         "required_outputs": ["build/netlist.json"],
         "gate": {"files_exist": ["build/netlist.json"]}, "blocks_on": []},
        # id 2 is NOT a key in _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS. Its own
        # artefact is absent, keeping a NON-blocked failure on the run so the
        # PASS_WITH_OPEN_SOURCE_CONSTRAINTS promotion cannot fire — which means
        # step 13 below is a plain blocker this run did NOT defer, not a genuine
        # open-source deferral.
        {"id": 2, "name": "Emit floorplan", "stage": "stage_probe",
         "required_outputs": ["build/floorplan.def"],
         "gate": {"files_exist": ["build/floorplan.def"]}, "blocks_on": []},
        # id 13 IS a key in _OPEN_SOURCE_CONTAINER_BLOCKED_STEPS. It is absent
        # here for an ordinary reason — the artefact was not produced — NOT
        # because this run routed it into the open-source deferral.
        {"id": 13, "name": "Emit equivalence proof", "stage": "stage_probe",
         "required_outputs": ["build/equiv.json"],
         "gate": {"files_exist": ["build/equiv.json"]}, "blocks_on": []},
    ],
}


def test_membership_in_the_oss_table_alone_does_not_make_a_blocker_a_missing_capability(tmp_path):
    """OVER-CORRECTION CONTROL, through the real producer CLI.

    Step 13's id is a key in `_OPEN_SOURCE_CONTAINER_BLOCKED_STEPS`, but this
    run did not route it into the open-source deferral — its artefact is simply
    absent. The producer's narrowing (`_oss_deferred` is built from
    `oss_blocked_skipped` + `os_constraints_deferrals`, the run's own decisions,
    never from bare table membership) means step 13 classifies on the evidence
    it actually has: `declared-artefact-absent` / UNCLASSIFIED.

    Reverting that construction to iterate the table makes step 13 flip to
    MISSING_CAPABILITY / commercial-tool-required and fails this test; the
    narrowed wiring passes it. On the pre-change tree the program writes no
    `blockers` key at all, so this fails on CONTENT there too, not on a symbol.
    """
    proj = tmp_path / "member"
    (proj / "build").mkdir(parents=True)
    (proj / "build" / "netlist.json").write_text('{"cells": []}\n')  # step 1 PASS
    flow = tmp_path / "member_flow.yaml"
    flow.write_text(yaml.safe_dump(_OSS_MEMBER_FLOW))
    out = proj / "report.json"
    proc = _pr.run(
        [sys.executable, str(_FCC), str(proj), "--flow-def", str(flow),
         "--json", str(out)],
        capture_output=True, text=True, cwd=str(_PROGRAMS))
    doc = json.loads(out.read_text())
    assert "blockers" in doc, "the report publishes no classified blocker list"
    by_id = {b["step_id"]: b for b in doc["blockers"]}
    assert 13 in by_id, "the table-member step must still be ON the list"
    assert by_id[13]["classification"] != "MISSING_CAPABILITY", (
        "mere membership of the open-source table fabricated a capability gap "
        "on a step this run did not defer")
    assert by_id[13]["classification"] == "UNCLASSIFIED"
    assert by_id[13]["basis"] == "declared-artefact-absent"
    assert by_id[13]["basis"] != "commercial-tool-required"
