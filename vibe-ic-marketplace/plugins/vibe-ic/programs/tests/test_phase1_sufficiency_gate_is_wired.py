"""The Phase-1 sufficiency gate must be WIRED, not merely present.

MEASURED DEFECT
---------------
``phase1_sufficiency_check.py`` describes itself as "the SUFFICIENCY GATE of
the Phase-1 dialogue dual-track convergence" and works correctly when invoked.
It was wired into NOTHING: not ``phase1_doc_one_shot_runner``, not
``phase1_one_shot_runner``, not ``flow/phase1_phase2_phase3.yaml``. Its only
references in the tree were its own tests.

Because it was absent from the flow definition, ``flow_gate_enforcement_audit``
could not classify it as orphaned either — that audit walks the flow, and this
gate was not in the flow to be walked. It was invisible to the very tool that
exists to find gates that cannot block.

Measured consequence on a natural-language-only Phase-1: all 27 layers emitted,
``ports=0``, Phase-1 reported **PASS** — while the unwired gate, run by hand
over that same ``generated_docs``, reported
``insufficient / MISSING required: ['ports']``. Phase-2 then FAILed with
``rtl/ missing``: there was no interface for RTL to be built to.

These tests pin the WIRING. They fail against the pre-fix runner (no reference
exists) and pass after. chip-AGNOSTIC: source-structure assertions only.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

_RUNNER = PROG_DIR / "phase1_doc_one_shot_runner.py"

#: The advisory post-checks the Phase-1 doc runner must invoke.
_REQUIRED_ADVISORIES = ("phase1_sufficiency_check",
                        "phase1_input_corpus_purity_check")


@pytest.fixture(scope="module")
def runner_src() -> str:
    return _RUNNER.read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("name", _REQUIRED_ADVISORIES)
def test_advisory_program_exists(name):
    assert (PROG_DIR / f"{name}.py").is_file(), f"{name}.py missing"


@pytest.mark.parametrize("name", _REQUIRED_ADVISORIES)
def test_runner_references_the_advisory(runner_src, name):
    """The NEGATIVE CONTROL: pre-fix the runner names neither program."""
    assert name in runner_src, (
        f"{name} is not referenced by phase1_doc_one_shot_runner — it is "
        f"orphaned, so a blind run never invokes it")


@pytest.mark.parametrize("name", _REQUIRED_ADVISORIES)
def test_advisory_is_not_in_the_blocking_gate_table(runner_src, name):
    """The blocking table documents itself as blocking; an advisory member
    would make that contract false. Keep them separate."""
    m = re.search(r"_SEMANTIC_LAYER_GATES\s*=\s*\((.*?)\n    \)",
                  runner_src, re.S)
    assert m, "could not locate _SEMANTIC_LAYER_GATES"
    assert name not in m.group(1), (
        f"{name} is ADVISORY but was added to the BLOCKING gate table")


def test_advisory_table_declares_its_enforcement(runner_src):
    """§5: the enforcement level is stated, not left to an unstated default."""
    m = re.search(r"_ADVISORY_POST_CHECKS\s*=\s*\((.*?)\n    \)",
                  runner_src, re.S)
    assert m, "no _ADVISORY_POST_CHECKS table in the runner"
    for name in _REQUIRED_ADVISORIES:
        assert name in m.group(1), f"{name} not in _ADVISORY_POST_CHECKS"
    assert "ADVISORY" in runner_src


def test_runner_still_parses(runner_src):
    ast.parse(runner_src)


def test_sufficiency_check_reports_insufficient_on_a_portless_layer_set(
        tmp_path):
    """The gate's own verdict on the shape that reached Phase-2 empty.

    A layer set with a name but ZERO ports is exactly what a
    natural-language-only Phase-1 emits, and it is NOT sufficient to author
    RTL. Synthesized neutral data — no design/PDK/vendor literal.
    """
    import json
    import phase1_sufficiency_check as suff

    d = tmp_path / "generated_docs"
    d.mkdir(parents=True)
    (d / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "unit_under_test",
        "pin_table": [],
        "no_pin_table_in_input": True,
    }), encoding="utf-8")
    (d / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "ic_name": "unit_under_test",
        "top_module": "chip_top",
        "ports": [], "top_ports": [],
    }), encoding="utf-8")

    assert suff._load_layers(d), "fixture layers did not load"
    rec = suff.check(d)
    assert rec["verdict"] == "insufficient", rec
    assert "ports" in rec["missing_required"], rec
