#!/usr/bin/env python3
"""Anti-drift: the stage-5 intake gates must search the paths the flow declares.

Steps 40 (fab intake) and 42 (packaging intake) audit artefacts that are
supplied EXTERNALLY (foundry / assembly house).  Nothing in this repo
produces them, so the flow yaml's ``required_outputs`` is their single
source of truth for where they live.

Both gates had drifted to a bare ``manufacturing/`` prefix that no producer
and no other checker uses.  The measured consequence was not a loud error:
the gate returned rc=2 ("input not applicable"), ``flow_compliance_check``
mapped that to VACUOUS_PASS, and VACUOUS_PASS is added into ``pass_count``
(flow_compliance_check.py:7017) — so a project holding complete, correct fab
and packaging data was scored as a pass on the grounds that it did not
exist, while the step's own ``evidence[]`` listed the very files.

This test pins the checker's PRIMARY candidate to the yaml declaration so
the drift cannot silently return.  (Steps 41 and 43 — wafer_sort_yield_check
and final_test_attestation_check — already agreed with the yaml and are the
precedent this follows.)
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _flow_required_outputs(step_id):
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(_FLOW.read_text())
    for step in doc.get("steps", []):
        if str(step.get("id")) == str(step_id):
            return list(step.get("required_outputs") or [])
    raise AssertionError(f"step {step_id} not found in {_FLOW}")


@pytest.mark.parametrize(
    "step_id,program",
    [("40", "manufacturing_fab_intake_check"),
     ("42", "packaging_intake_check")],
)
def test_primary_search_path_equals_flow_declaration(step_id, program):
    declared = _flow_required_outputs(step_id)
    mod = _load(program)
    primary = [candidates[0] for _group, candidates in mod._REQUIRED_FILE_GROUPS]
    assert primary == declared, (
        f"step {step_id}: {program} searches {primary} first but the flow "
        f"declares {declared}. A gate that searches a path no producer writes "
        f"returns rc=2 and is scored VACUOUS_PASS — a pass for absent input — "
        f"on a project that is in fact fully compliant."
    )
    # The reported `required_files` (what a human reads in the report and what
    # `missing` names) must be the declared paths too, not a legacy alias.
    assert list(mod._REQUIRED_FILES) == declared


@pytest.mark.parametrize(
    "program,legacy_docs",
    [("manufacturing_fab_intake_check",
      {"manufacturing/mask_set_received.json":
           {"mask_set_id": "MS-1", "revision": "A1"},
       "manufacturing/wafer_lot_received.json":
           {"lot_id": "L-1", "foundry_status": "shipped"}}),
     ("packaging_intake_check",
      {"manufacturing/packaging_log.json":
           {"package_type": "QFN-48", "units": 100}})],
)
def test_legacy_prefix_retained_as_fallback(tmp_path, program, legacy_docs):
    """GUARD (direction-1), behavioural on purpose so it holds on the pre-fix
    tree too: a project still laid out with the old ``manufacturing/`` prefix
    must keep reaching the gate rather than regressing to SKIP."""
    import json as _json
    for rel, doc in legacy_docs.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(_json.dumps(doc))
    mod = _load(program)
    rc = mod.main([str(tmp_path)])
    assert rc == 0, (
        f"{program}: legacy `manufacturing/` layout regressed (rc={rc}); the "
        f"canonical path must be preferred, not the only one accepted."
    )
