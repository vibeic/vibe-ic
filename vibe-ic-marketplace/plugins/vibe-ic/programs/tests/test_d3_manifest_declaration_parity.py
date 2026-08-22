#!/usr/bin/env python3
"""The flow declaration and the d3 evidence manifest must move together.

Guard for `d3_manifest_declaration_parity_check`. Every fixture here is
SYNTHESIZED — neutral step ids and neutral paths, no design, PDK or vendor
literal — except `test_the_real_repository_tree_is_clean`, which drives the
check with the repository's OWN flow yaml and manifest so the suite cannot pass
in a tree where the property is actually broken.

The pairing that matters is `..._FAILS` / `..._PASSES`: the second is vacuous on
its own (a check that never fires also "clears" every finding), so it is only
meaningful next to a sibling that proves the finding fires at all.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent.parent


def _gate():
    path = _PLUGIN / "programs" / "d3_manifest_declaration_parity_check.py"
    spec = importlib.util.spec_from_file_location("_d3parity", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_d3parity"] = mod
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True          # never write into the shipped tree
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


G = _gate()


def _tree(root: Path, declared: dict, measured: dict) -> Path:
    """A minimal plugin root: {step_id: [paths]} declared, {step_id: [paths]} measured."""
    (root / "flow").mkdir(parents=True, exist_ok=True)
    (root / "programs" / "tests" / "fixtures").mkdir(parents=True, exist_ok=True)
    steps = [{"id": sid, "required_outputs": list(paths)}
             for sid, paths in declared.items()]
    (root / "flow" / "phase1_phase2_phase3.yaml").write_text(
        yaml.safe_dump({"steps": steps}), encoding="utf-8")
    manifest = {"steps": {sid: {"verdict": "ENFORCED",
                                "entries": {p: {"status": "PRODUCED_BY_RUN"}
                                            for p in paths}}
                          for sid, paths in measured.items()}}
    (root / "programs" / "tests" / "fixtures"
     / "matrix_d3_output_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    return root


def test_the_real_repository_tree_is_clean():
    """Drive the gate with the repo's OWN two files — not a fixture.

    A suite made only of fixtures authored beside the check cannot tell the
    check from its own absence (vibe-ic#400). This is the one test that would
    notice if the property broke in the tree that ships.
    """
    assert G.main([str(_PLUGIN)]) == G.RC_OK


def test_a_declaration_the_manifest_never_measured_FAILS(tmp_path, capsys):
    """The vibe-ic#1131/#1170 shape: a path added to the yaml alone.

    MEASURED on those two branches: `uncovered=2`, both
    `reports/phase1/extraction_coverage_report.{md,json}` on step D1 — which is
    the declared witness for D3-UNDECLARED-ARTEFACT, so the desync also disables
    that mutation's proof.
    """
    root = _tree(tmp_path,
                 declared={"S1": ["out/alpha.json", "out/beta.json"]},
                 measured={"S1": ["out/alpha.json"]})       # beta never measured
    assert G.main([str(root)]) == G.RC_FAIL
    err = capsys.readouterr().err
    assert "out/beta.json" in err, "the gate must NAME the offending path"
    assert "out/alpha.json" not in err, "it must not indict the covered path"


def test_the_paired_change_PASSES(tmp_path):
    """Same edit, applied to BOTH files — the shape vibe-ic#1235 uses.

    Vacuous alone; meaningful only next to `..._FAILS` above, which proves the
    finding can fire in the first place.
    """
    root = _tree(tmp_path,
                 declared={"S1": ["out/alpha.json", "out/beta.json"]},
                 measured={"S1": ["out/alpha.json", "out/beta.json"]})
    assert G.main([str(root)]) == G.RC_OK


def test_a_step_absent_from_the_manifest_ENTIRELY_is_caught(tmp_path, capsys):
    """A wholly new step must not slip through as "no entry, nothing to check"."""
    root = _tree(tmp_path,
                 declared={"S1": ["out/alpha.json"], "S2": ["out/gamma.json"]},
                 measured={"S1": ["out/alpha.json"]})
    assert G.main([str(root)]) == G.RC_FAIL
    assert "out/gamma.json" in capsys.readouterr().err


def test_zero_declarations_REFUSES_rather_than_passing(tmp_path, capsys):
    """A flow that declares nothing has not been checked.

    rc=2, never rc=0: a gate that has never met an artefact reporting success is
    the vacuous shape this repository refuses, and REFUSE is a distinct outcome
    from FAIL precisely so "could not run" is never read as "found nothing".
    """
    root = _tree(tmp_path, declared={"S1": []}, measured={})
    rc = G.main([str(root)])
    assert rc == G.RC_REFUSE
    assert rc != G.RC_OK and rc != G.RC_FAIL
    assert "REFUSE" in capsys.readouterr().err


def test_a_tree_without_the_pair_REFUSES(tmp_path, capsys):
    """No flow yaml / manifest anywhere above: cannot run, so not a pass."""
    (tmp_path / "empty").mkdir()
    assert G.main([str(tmp_path / "empty")]) == G.RC_REFUSE
    assert "REFUSE" in capsys.readouterr().err


def test_unreadable_manifest_REFUSES_and_does_not_crash(tmp_path, capsys):
    """Malformed input is refused, not silently treated as "measured nothing"."""
    root = _tree(tmp_path, declared={"S1": ["out/alpha.json"]},
                 measured={"S1": ["out/alpha.json"]})
    (root / "programs" / "tests" / "fixtures"
     / "matrix_d3_output_manifest.json").write_text("{not json", encoding="utf-8")
    assert G.main([str(root)]) == G.RC_REFUSE
    assert "REFUSE" in capsys.readouterr().err


@pytest.mark.parametrize("rc_name", ["RC_OK", "RC_FAIL", "RC_REFUSE"])
def test_the_three_outcomes_are_distinct(rc_name):
    """Guards the guard: if these collapse, every assertion above is satisfiable
    by the wrong outcome and this whole module stops measuring anything."""
    assert len({G.RC_OK, G.RC_FAIL, G.RC_REFUSE}) == 3
    assert isinstance(getattr(G, rc_name), int)
