#!/usr/bin/env python3
"""F-1 — the place-and-route search space gets a producer, and it is MEASURED.

THE MEASURED DEFECT
===================
`crosslayer_search_space.py` withheld eight place-and-route levers with the
reason "these are the place-and-route knobs the PnR-only search already owns".
There was no PnR-only search. No program under `programs/` emitted a space
containing those levers, so a downloaded plugin that wanted to search the knobs
its own runner exposes had nothing to feed `ppa_search_run.py`, and the sentence
named an owner a reader could not find. A sixty-point search ran anyway, over a
hand-authored space that nothing could re-emit -- so the published record cited
a space nobody else could draw from.

WHAT THE TESTS HOLD
===================
    positive   a space is emitted, it names the flag that applies every
               admitted lever, and it FEEDS `ppa_search_run.py` -- the last
               part is the whole point and is asserted end to end
    negative   a value the runner would silently CHANGE is refused (rc=1), and
               a lever the runner exposes no flag for cannot be opened by a
               caller asking for it
    vacuous    a runner that cannot be read, and a runner that parses to no
               CLI at all, are rc=2 with a marker -- never a confident
               "every lever NOT_EXPOSED"

chip-AGNOSTIC: the runner's CLI surface and ordinary PnR vocabulary only.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import crosslayer_search_space as X                 # noqa: E402
import ppa_pnr_search_space as P                    # noqa: E402
import ppa_search_run as R                          # noqa: E402
from _ppa import search as S                        # noqa: E402


@pytest.fixture
def out(tmp_path):
    return tmp_path / "space.json"


def _emit(out, *extra):
    rc = P.main(["--json", str(out), *extra])
    doc = json.loads(out.read_text()) if out.exists() else {}
    return rc, doc


def _lever(doc, name):
    return [l for l in doc["levers"] if l["lever"] == name][0]


# ---------------------------------------------------------------------------
# positive
# ---------------------------------------------------------------------------
def test_a_space_is_emitted_and_admits_what_the_runner_exposes(out):
    rc, doc = _emit(out)
    assert rc == P.RC_PASS
    assert doc["status"] == "MEASURED"
    assert doc["self_audit_problems"] == []
    assert doc["admitted_count"] >= 1, (
        "the runner exposes place-and-route flags; a space admitting none of "
        "them is not measuring this runner")


def test_every_admitted_lever_cites_the_flag_that_applies_it(out):
    """A lever nobody can point at in the runner is a lever this flow cannot
    apply. The citation is path:line so a reader can go and open it."""
    _, doc = _emit(out)
    runner = _PROGRAMS / P.RUNNER_REL
    lines = runner.read_text(encoding="utf-8").splitlines()
    for l in doc["levers"]:
        if not l["admitted"]:
            continue
        c = l["citation"]
        assert c["path"] == P.RUNNER_REL
        assert c["literal"] in lines[c["line"] - 1], (l["lever"], c)


def test_every_refused_lever_names_the_flags_it_looked_for(out):
    """"this flow cannot search cell padding" is a fact a reader of a search
    record needs, and an ABSENT row does not state it."""
    _, doc = _emit(out)
    for l in doc["levers"]:
        if l["admitted"]:
            continue
        assert l["status"] == P.STATUS_NOT_EXPOSED
        assert l["flags_looked_for"]
        assert l["applies_via"] is None


def test_the_space_records_the_runner_it_was_measured_against(out):
    """Two spaces citing `phase3_one_shot_runner.py` may have been measured
    against two different files. The digest is the fact; the path is not."""
    _, doc = _emit(out)
    m = doc["measured_against"]
    assert m["path"] == P.RUNNER_REL
    assert m["sha256"].startswith("sha256:")
    assert m["sha256"] == P._sha256(
        (_PROGRAMS / P.RUNNER_REL).read_text(encoding="utf-8"))


def test_caller_values_are_recorded_as_the_callers(out):
    """The program proposes no value. When the caller supplies them the space
    says so, and says what the runner would do with each one."""
    rc, doc = _emit(out, "--values", "placement_density=0.30,0.20")
    assert rc == P.RC_PASS
    lev = _lever(doc, "placement_density")
    assert lev["values_source"] == "caller"
    assert lev["domain"] == "0.30 | 0.20"
    chk = lev["values_checked_against_runner"]
    assert chk["checked"] is True
    assert [r["value"] for r in chk["values"]] == ["0.30", "0.20"]
    assert all(r["unchanged"] for r in chk["values"])


def test_a_lever_with_no_caller_values_says_it_was_not_enumerated(out):
    _, doc = _emit(out)
    lev = _lever(doc, "placement_density")
    assert lev["values_source"] == "not_enumerated"
    assert "--values" in lev["values_hint"]


# ---------------------------------------------------------------------------
# THE POINT: the emitted space feeds the search
# ---------------------------------------------------------------------------
def test_the_emitted_space_drives_ppa_search_run(out, tmp_path):
    """F-1 in one assertion. Before this program existed there was no document
    a reader could re-emit to feed this search."""
    rc, _ = _emit(out, "--values", "placement_density=0.30,0.20",
                  "--values", "spare_cell_density=0.02,0.00")
    assert rc == P.RC_PASS
    man_path = tmp_path / "manifest.json"
    assert R.main([str(out), "--max-trials", "4", "--json", str(man_path)]) \
        == R.RC_PASS
    man = json.loads(man_path.read_text())
    knobs = [json.dumps(c["knobs"], sort_keys=True) for c in man["candidates"]]
    assert man["budget_spent"]["trials_proposed"] == 4
    assert len(set(knobs)) == 4, "a search must not propose the same point twice"
    assert man["space_digest"].startswith("sha256:")
    # And a PLAN over this space is still refused as a RESULT: the space being
    # real does not make a set of proposed points into a search that ran.
    assert R.main(["--verify", str(man_path)]) == R.RC_REFUSED


def test_the_first_candidate_is_the_callers_first_value_on_every_axis(
        out, tmp_path):
    """`_ppa.search.propose` puts the baseline first, so a caller who lists the
    runner's own defaults first gets the DEFAULT RUN as the reference point
    rather than a lucky draw."""
    _emit(out, "--values", "placement_density=0.30,0.20",
          "--values", "spare_cell_density=0.02,0.00")
    man_path = tmp_path / "m.json"
    R.main([str(out), "--max-trials", "4", "--json", str(man_path)])
    man = json.loads(man_path.read_text())
    assert man["candidates"][0]["knobs"] == {
        "placement_density": "0.30", "spare_cell_density": "0.02"}
    assert man["candidates"][0]["note"] == "baseline"


def test_a_space_with_no_values_is_read_as_not_enumerable_not_as_empty(
        out, tmp_path):
    """The honest degrade. A space that proposes no value must not look like a
    space with no levers -- the search records the lever and says it did not
    vary it."""
    _emit(out)
    man_path = tmp_path / "m.json"
    assert R.main([str(out), "--max-trials", "4", "--json", str(man_path)]) \
        == R.RC_PASS
    man = json.loads(man_path.read_text())
    notes = {n["lever"]: n["status"] for n in man["lever_notes"]}
    assert notes.get("placement_density") == S.NOT_ENUMERABLE
    assert man["budget_spent"]["trials_proposed"] == 1


# ---------------------------------------------------------------------------
# negative -- the runner's own guard is the discriminator
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("spec,applied", [
    ("placement_density=0.3,1.5", 0.015),        # read as a PERCENTAGE
    ("spare_cell_density=0.02,0.5", 0.2),        # clamped to the ceiling
    ("spare_cell_density=0.02,-1", 0.0),         # clamped to the floor
])
def test_a_value_the_runner_would_change_is_refused(out, capsys, spec, applied):
    """THE DEFECT. `--util 1.5` is not an error -- the runner reads it as 1.5 %
    and uses 0.015. Two candidates that differ only there are the same run
    wearing two names, and the manifest would publish the knob, not the value."""
    rc = P.main(["--json", str(out), "--values", spec])
    err = capsys.readouterr().err
    assert rc == P.RC_REFUSED
    assert P.MARK_REFUSE in err
    assert str(applied) in err
    assert not out.exists(), "a refused space must not be published"


def test_a_value_the_runner_uses_unchanged_is_accepted(out):
    """The other side of the same fixture, so "it refuses everything" cannot
    pass for "it discriminates"."""
    assert P.main(["--json", str(out), "--values",
                   "placement_density=0.3,0.45,1.0"]) == P.RC_PASS


def test_a_caller_may_not_open_a_lever_the_runner_cannot_apply(out, capsys):
    rc = P.main(["--json", str(out), "--values", "cell_padding=1,2,3"])
    assert rc == P.RC_REFUSED
    assert "exposes no flag" in capsys.readouterr().err


def test_an_unknown_lever_name_is_refused_not_invented(out, capsys):
    rc = P.main(["--json", str(out), "--values", "wishful_thinking=1,2"])
    assert rc == P.RC_REFUSED
    assert "not a lever this program knows" in capsys.readouterr().err


def test_a_repeated_value_is_refused(out, capsys):
    """A search that proposes the same point twice reports a trial count that
    is not a count of distinct configurations."""
    rc = P.main(["--json", str(out), "--values",
                 "placement_density=0.30,0.30"])
    assert rc == P.RC_REFUSED
    assert "repeats a value" in capsys.readouterr().err


def test_malformed_values_is_rc3_not_a_finding(out, capsys):
    assert P.main(["--json", str(out), "--values", "no-equals-sign"]) == \
        P.RC_BAD_INVOCATION
    assert P.main(["--json", str(out), "--values", "lever="]) == \
        P.RC_BAD_INVOCATION


# ---------------------------------------------------------------------------
# vacuous -- the arm that is not paperwork
# ---------------------------------------------------------------------------
def test_an_absent_runner_is_rc2_with_a_marker(tmp_path, capsys):
    """A space measured against a runner nobody looked at describes nothing.
    rc=2, and NOT a confident space listing every lever as NOT_EXPOSED."""
    rc = P.main(["--programs-dir", str(tmp_path),
                 "--json", str(tmp_path / "s.json")])
    err = capsys.readouterr().err
    assert rc == P.RC_UNDETERMINED
    assert P.MARK_CANNOT_CHECK in err
    assert not (tmp_path / "s.json").exists()


def test_an_unparseable_runner_is_rc2(tmp_path, capsys):
    (tmp_path / P.RUNNER_REL).write_text("def main(: pass\n")
    rc = P.main(["--programs-dir", str(tmp_path),
                 "--json", str(tmp_path / "s.json")])
    assert rc == P.RC_UNDETERMINED
    assert P.MARK_CANNOT_CHECK in capsys.readouterr().err


def test_a_runner_that_parses_to_no_cli_is_rc2_not_an_all_refused_space(
        tmp_path, capsys):
    """The subtle vacuity. A runner with zero flags is far more likely a
    surface this program failed to read than a runner with no CLI, and
    publishing "every lever NOT_EXPOSED" from it would be a confident wrong
    answer dressed as a measurement."""
    (tmp_path / P.RUNNER_REL).write_text("x = 1\n")
    rc = P.main(["--programs-dir", str(tmp_path),
                 "--json", str(tmp_path / "s.json")])
    err = capsys.readouterr().err
    assert rc == P.RC_UNDETERMINED
    assert P.MARK_CANNOT_CHECK in err
    assert "declares no command-line option" in err
    assert not (tmp_path / "s.json").exists()


def test_verify_of_an_absent_space_is_rc2(tmp_path, capsys):
    assert P.main(["--verify", str(tmp_path / "nope.json")]) == \
        P.RC_UNDETERMINED
    assert P.MARK_CANNOT_CHECK in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --verify -- the half that applies to a space somebody else published
# ---------------------------------------------------------------------------
def test_a_space_this_program_emitted_verifies_clean(out):
    _emit(out, "--values", "placement_density=0.30,0.20")
    assert P.main(["--verify", str(out)]) == P.RC_PASS


def test_a_space_admitting_a_flag_this_runner_does_not_have_is_rc1(
        out, capsys):
    _, doc = _emit(out)
    lev = _lever(doc, "placement_density")
    lev["applies_via"] = "--a-flag-that-does-not-exist"
    lev["citation"]["literal"] = "--a-flag-that-does-not-exist"
    out.write_text(json.dumps(doc))
    assert P.main(["--verify", str(out)]) == P.RC_REFUSED
    assert "not on" in capsys.readouterr().err


def test_a_space_refusing_a_lever_the_runner_does_expose_is_rc1(out, capsys):
    """The other direction, and the one that rots: a space that says a lever
    is unavailable after the runner grew the flag."""
    _, doc = _emit(out)
    lev = _lever(doc, "placement_density")
    lev.update({"admitted": False, "status": P.STATUS_NOT_EXPOSED,
                "applies_via": None, "citation": None})
    out.write_text(json.dumps(doc))
    assert P.main(["--verify", str(out)]) == P.RC_REFUSED
    assert "IS on" in capsys.readouterr().err


def test_the_self_audit_catches_an_admitted_lever_with_no_citation():
    problems = P.audit_space({"levers": [
        {"lever": "x", "admitted": True, "applies_via": None,
         "citation": None}]})
    assert problems and "cannot apply" in problems[0]


def test_the_self_audit_refuses_an_empty_lever_list():
    assert P.audit_space({"levers": []})
    assert P.audit_space({})


# ---------------------------------------------------------------------------
# the sentence in the other program, and the owner it names
# ---------------------------------------------------------------------------
def test_the_crosslayer_exclusion_reason_names_an_owner_that_exists(tmp_path):
    """THE F-1 SECOND HALF. The reason used to claim "the PnR-only search
    already owns" these levers when no such search existed."""
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text(
        "The implementation is free to choose the FSM encoding.\n")
    assert X.main([str(tmp_path), "--json", "cl.json"]) == 0
    doc = json.loads((tmp_path / "cl.json").read_text())
    assert doc["pnr_owner"] == X.PNR_OWNER
    assert (_PROGRAMS / X.PNR_OWNER).is_file()
    assert "UNOWNED" not in doc["pnr_exclusion_reason"]


def test_the_excluded_names_are_the_owners_own_lever_names(tmp_path):
    """Not a remembered copy. A name listed here that the owner never emits is
    a lever no program owns, which is the state this pair was in."""
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text("does not specify the FSM encoding\n")
    X.main([str(tmp_path), "--json", "cl.json"])
    doc = json.loads((tmp_path / "cl.json").read_text())
    assert doc["pnr_levers_excluded_on_purpose"] == \
        sorted(str(l["lever"]) for l in P.LEVERS)


def test_with_the_owner_absent_the_reason_says_unowned_not_delegated(
        monkeypatch, tmp_path):
    """The honest arm. If the owner is not on the tree, the sentence may not
    claim one -- which is exactly the bug, generalised."""
    monkeypatch.setattr(X, "PNR_OWNER", "no_such_program_at_all.py")
    row = X._pnr_exclusion()
    assert row["pnr_owner"] is None
    assert "UNOWNED" in row["pnr_exclusion_reason"]
    assert row["pnr_levers_excluded_on_purpose"] == \
        list(X._PNR_LEVERS_FALLBACK)
