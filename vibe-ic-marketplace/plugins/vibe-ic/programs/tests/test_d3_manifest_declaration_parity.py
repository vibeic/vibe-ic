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


def _tree(root: Path, declared: dict, measured: dict, body=None) -> Path:
    """A minimal plugin root: {step_id: [paths]} declared, {step_id: [paths]} measured.

    *body* is the JSON value recorded UNDER each measured path. It defaults to a
    record dimension 3 can decide from, because every test that predates the
    hollow-entry finding is about WHICH PATHS are covered and would otherwise be
    asserting two properties at once.
    """
    (root / "flow").mkdir(parents=True, exist_ok=True)
    (root / "programs" / "tests" / "fixtures").mkdir(parents=True, exist_ok=True)
    steps = [{"id": sid, "required_outputs": list(paths)}
             for sid, paths in declared.items()]
    (root / "flow" / "phase1_phase2_phase3.yaml").write_text(
        yaml.safe_dump({"steps": steps}), encoding="utf-8")
    if body is None:
        body = {"status": "PRODUCED_BY_RUN"}
    manifest = {"steps": {sid: {"verdict": "ENFORCED",
                                "entries": {p: body for p in paths}}
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


# ══════════════════════════════════════════════════════════════════════
# A DUPLICATED STEP ID IS NOT A PARSE DETAIL (measured on main, 2026-08-20)
#
# `json.loads` keeps the LAST of two same-named keys and reports nothing. The
# shipped manifest carried `15.5ic`, `26.5ic`, `37.5ip` and `37.5ic` twice, and
# the two copies of each disagreed: `"verdict": "ENFORCED"` in the first,
# `"verdict": "NA_DORMANT_CONDITION"` in the second. Programs read the second.
# A human reading the file top-down read the first. Both were reading the same
# committed bytes, so there was no disagreement for anyone to notice.
#
# The pairing rule of this module applies: the _PASSES half below is worthless
# alone — the check that never fires also clears every tree — so it exists only
# next to the _FAILS half that proves the refusal fires on the real shape.
# ══════════════════════════════════════════════════════════════════════
#: The status here is a REAL one (`UNPROVEN`) and not the arbitrary "X" it used
#: to be. The property these two tests are named for is the DUPLICATE KEY, and
#: an unrecognised status is now a finding in its own right — so the placeholder
#: would have made `..._PASSES` below fail for a reason that has nothing to do
#: with duplicate keys, and the control would have stopped controlling anything.
_DUP_MANIFEST = """{
  "steps": {
    "S1": {"verdict": "ENFORCED",
           "entries": {"out/a.json": {"status": "UNPROVEN"}}},
    "S1": {"verdict": "NA_DORMANT_CONDITION",
           "entries": {"out/a.json": {"status": "UNPROVEN"}}}
  }
}"""


def _tree_with_raw_manifest(root: Path, declared: dict, raw: str) -> Path:
    (root / "flow").mkdir(parents=True, exist_ok=True)
    (root / "programs" / "tests" / "fixtures").mkdir(parents=True, exist_ok=True)
    steps = [{"id": sid, "required_outputs": list(paths)}
             for sid, paths in declared.items()]
    (root / "flow" / "phase1_phase2_phase3.yaml").write_text(
        yaml.safe_dump({"steps": steps}), encoding="utf-8")
    (root / "programs" / "tests" / "fixtures"
     / "matrix_d3_output_manifest.json").write_text(raw, encoding="utf-8")
    return root


def test_a_step_id_recorded_twice_FAILS(tmp_path):
    """Two records for one step -> REFUSE, and the message names the ids."""
    root = _tree_with_raw_manifest(tmp_path, {"S1": ["out/a.json"]}, _DUP_MANIFEST)
    import io
    import contextlib
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = G.main([str(root)])
    assert rc == G.RC_REFUSE, (
        f"a manifest recording S1 twice returned rc={rc}. json.loads keeps the "
        f"LAST copy silently, so anything short of a refusal lets two "
        f"contradicting records ship as one.")
    assert "S1" in err.getvalue(), (
        f"the refusal must NAME the duplicated id so the fix is mechanical; "
        f"it said: {err.getvalue()!r}")


def test_the_same_tree_with_one_record_PASSES(tmp_path):
    """The control: identical tree, the duplicate merged away -> rc 0.

    Without this the test above would also pass if the gate refused every
    manifest, which is the failure mode the module docstring names.
    """
    single = _DUP_MANIFEST.replace(
        '    "S1": {"verdict": "ENFORCED",\n'
        '           "entries": {"out/a.json": {"status": "UNPROVEN"}}},\n',
        "")
    root = _tree_with_raw_manifest(tmp_path, {"S1": ["out/a.json"]}, single)
    assert G.main([str(root)]) == G.RC_OK


def test_the_real_manifest_carries_no_duplicate_key():
    """The shipped fixture itself — the reason this refusal exists."""
    path = (_PLUGIN / "programs" / "tests" / "fixtures"
            / "matrix_d3_output_manifest.json")
    G._load_manifest_no_duplicate_keys(path)      # raises if any key repeats


# ──────────────────────────────────────────────────────────────────────
# THE KEY IS NOT THE PROPERTY
# ──────────────────────────────────────────────────────────────────────
# Found while closing the ONE finding this gate reported on main, 2026-08-21:
# step 31's `reports/phase3/drc_signoff.json`. The cheapest edit that turns that
# report green is to paste the path back into the manifest with an empty body —
# the gate asked `path in entries` and an entry was whatever sat under the key.
#
# MEASURED against the gate as it stood, on synthesized one-step trees: `{}`,
# `{"status": null}` and `{"status": "LOOKS_FINE"}` ALL returned rc 0. Each one
# clears the finding while recording that nothing was ever looked for, and each
# leaves dimension 3 to decide the cell through its `unrecognised manifest
# status` fall-through. A green bought that way is worth less than the red it
# replaces, because the red at least named the path that had never been
# measured.
#
# The FAILS/PASSES pairing of this module applies here too: the PASSES case is
# vacuous alone, so it is parametrized over the three statuses the dimension
# really implements, and it is what proves the new refusal is not simply
# refusing everything.
_UNDECIDABLE_BODIES = [
    pytest.param({}, "records no `status`", id="empty-object"),
    pytest.param({"status": None}, "records no `status`", id="null-status"),
    pytest.param({"status": "LOOKS_FINE"}, "cannot decide from", id="made-up-status"),
    pytest.param({"run": "somewhere", "size_bytes": 12}, "records no `status`",
                 id="evidence-shaped-but-statusless"),
]


@pytest.mark.parametrize("body,expected", _UNDECIDABLE_BODIES)
def test_an_entry_the_dimension_cannot_decide_from_does_NOT_close_it(
        tmp_path, capsys, body, expected):
    """Covering a declared path with an unusable record must still FAIL."""
    root = _tree(tmp_path,
                 declared={"S1": ["out/alpha.json"]},
                 measured={"S1": ["out/alpha.json"]},
                 body=body)
    assert G.main([str(root)]) == G.RC_FAIL
    err = capsys.readouterr().err
    assert "out/alpha.json" in err, "the gate must NAME the offending path"
    assert expected in err, err


def test_a_non_object_entry_does_NOT_close_it(tmp_path, capsys):
    """`"out/alpha.json": "measured"` — a key with prose under it, not a record."""
    root = _tree(tmp_path,
                 declared={"S1": ["out/alpha.json"]},
                 measured={"S1": ["out/alpha.json"]},
                 body="measured")
    assert G.main([str(root)]) == G.RC_FAIL
    assert "not an object" in capsys.readouterr().err


@pytest.mark.parametrize("status", ["PRODUCED_BY_RUN", "PRODUCED_LIVE", "UNPROVEN"])
def test_each_status_the_dimension_CAN_decide_from_PASSES(tmp_path, status):
    """The control for the four refusals above.

    Without this the new check would also "pass" its own tests by refusing every
    entry ever written, which is the failure mode this module's docstring names.
    Parametrized over the real vocabulary so a status quietly dropped from
    `_RECOGNISED_STATUSES` reddens here rather than in the shipped manifest.
    """
    root = _tree(tmp_path,
                 declared={"S1": ["out/alpha.json"]},
                 measured={"S1": ["out/alpha.json"]},
                 body={"status": status})
    assert G.main([str(root)]) == G.RC_OK


def test_the_recognised_vocabulary_is_exactly_what_the_dimension_implements():
    """`_RECOGNISED_STATUSES` must not drift from dimension 3's own branches.

    The gate's list is a COPY of the statuses `check_entry` implements in
    `test_matrix_d3_outputs_produced.py`; a status added there and not here
    would be refused in the manifest that ships, and one removed there and left
    here would be waved through into the fall-through this check exists to stop.
    Read out of that module's source rather than restated, so the two cannot
    disagree silently.
    """
    src = (_PLUGIN / "programs" / "tests"
           / "test_matrix_d3_outputs_produced.py").read_text(encoding="utf-8")
    implemented = {s for s in ("PRODUCED_BY_RUN", "PRODUCED_LIVE", "UNPROVEN")
                   if f'status == "{s}"' in src}
    assert implemented == set(G._RECOGNISED_STATUSES), (
        f"dimension 3 branches on {sorted(implemented)} but this gate accepts "
        f"{sorted(G._RECOGNISED_STATUSES)}")


def test_the_real_manifest_records_a_decidable_status_for_EVERY_declared_entry():
    """The shipped pair — the reason the refusal above is affordable.

    Measured 2026-08-21: 122 PRODUCED_BY_RUN, 40 UNPROVEN, 2 PRODUCED_LIVE and
    no entry without a status, so this costs the tree that ships nothing.
    """
    _declared, uncovered, hollow, _per_step = G.audit(_PLUGIN)
    assert not hollow, hollow
    assert not uncovered, uncovered
