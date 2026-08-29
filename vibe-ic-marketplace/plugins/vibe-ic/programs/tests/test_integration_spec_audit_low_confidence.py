#!/usr/bin/env python3
"""A producer's own hedge must not be read as a design defect.

MEASURED 2026-08-29 on subservient/gf180mcuD at v1.12.65: `integration_spec_audit`
exited 1 on `phase1/generated_docs/L9_INTEGRATION_SPEC.json` with six
`INVALID_SUBMODULE: submodules[N]: missing 'ports'` errors. Every one of the six
entries carries, from its own producer:

    "type": "markdown submodule-contract heading"
    "role": "documented submodule"
    "low_confidence": true

The emitter scraped them out of headings in a prose document and said so in the
artefact -- one of the six is a noun phrase, not an identifier. The gate never
read `low_confidence` (zero occurrences in the file) and hard-errored on all
six. Six errors, none of which names anything the design got wrong.

The repair is NOT to drop the rule. A submodule the producer is CONFIDENT about
still owes a port list, and that stays an ERROR. Only an entry its own producer
flagged as uncertain is reported instead of refused -- the finding is still
emitted and still printed. Degrade loudly, never silently.
"""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
PROG = PROGRAMS / "integration_spec_audit.py"


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


def _project(tmp_path: Path, name: str, doc: dict) -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "integration.json").write_text(json.dumps(doc), encoding="utf-8")
    return proj


def _doc(submodules):
    """A spec that is complete apart from the one variable under test."""
    return {"top_module": "chip_top", "internal_wires": ["w_a"],
            "submodules": submodules}


# --------------------------------------------------------------------------
# THE DEFECT
# --------------------------------------------------------------------------
def test_hedged_submodule_without_ports_is_reported_not_refused(tmp_path):
    """Pre-fix this exits 1. The producer said it was unsure; the gate refused."""
    proj = _project(tmp_path, "hedged", _doc([
        {"name": "ALU block", "instances": 1, "low_confidence": True}]))
    res = _run(proj)
    assert res.returncode == 0, (
        "an entry its own producer flagged low_confidence must not be hard-"
        f"failed for lacking ports; got rc={res.returncode}\n{res.stdout}")


def test_the_hedged_finding_is_still_emitted(tmp_path):
    """Reported, not dropped. A silent downgrade would be the wrong repair."""
    proj = _project(tmp_path, "still", _doc([
        {"name": "ALU block", "instances": 1, "low_confidence": True}]))
    out = _run(proj).stdout
    assert "INVALID_SUBMODULE" in out
    assert "missing 'ports'" in out
    assert "low_confidence" in out, f"the reason must be stated:\n{out}"


# --------------------------------------------------------------------------
# CONTROLS -- the fix must NOT change these answers
# --------------------------------------------------------------------------
def test_control_confident_submodule_without_ports_still_refused(tmp_path):
    """THE load-bearing control. Without it the fix is satisfied by code that
    simply stops refusing anything."""
    proj = _project(tmp_path, "confident", _doc([{"name": "alu", "instances": 1}]))
    res = _run(proj)
    assert res.returncode == 1, f"a confident submodule still owes ports\n{res.stdout}"
    assert "submodules[0]: missing 'ports'" in res.stdout
    assert "low_confidence" not in res.stdout


def test_control_hedged_with_ports_passes(tmp_path):
    proj = _project(tmp_path, "hedged_ok", _doc([
        {"name": "alu", "instances": 1, "low_confidence": True,
         "ports": ["i_a", "o_z"]}]))
    assert _run(proj).returncode == 0


def test_control_confident_with_ports_passes(tmp_path):
    proj = _project(tmp_path, "conf_ok", _doc([
        {"name": "alu", "instances": 1, "ports": ["i_a", "o_z"]}]))
    assert _run(proj).returncode == 0


def test_control_hedged_missing_name_still_refused(tmp_path):
    """The hedge buys the PORTS rule only. A nameless entry is still an error."""
    proj = _project(tmp_path, "noname", _doc([
        {"instances": 1, "low_confidence": True, "ports": ["i_a"]}]))
    res = _run(proj)
    assert res.returncode == 1
    assert "missing 'name'" in res.stdout


def test_control_missing_top_still_refused(tmp_path):
    proj = _project(tmp_path, "notop", {
        "internal_wires": ["w_a"],
        "submodules": [{"name": "alu", "instances": 1, "ports": ["i_a"],
                        "low_confidence": True}]})
    res = _run(proj)
    assert res.returncode == 1
    assert "MISSING_TOP" in res.stdout


def test_control_empty_submodules_still_refused(tmp_path):
    proj = _project(tmp_path, "empty", _doc([]))
    assert _run(proj).returncode == 1


def test_control_low_confidence_false_is_treated_as_confident(tmp_path):
    """Only a TRUE hedge buys anything; an explicit false must not."""
    proj = _project(tmp_path, "false", _doc([
        {"name": "alu", "instances": 1, "low_confidence": False}]))
    res = _run(proj)
    assert res.returncode == 1
    assert "low_confidence" not in res.stdout
