#!/usr/bin/env python3
"""A metric that does not move when the design does is a measurement that never happened.

WHAT THIS GUARDS, AND WHY IT IS NOT COVERED BY THE PER-MODULE SUITES
====================================================================
Every other PPA test in this tree asks "is this number RIGHT" against a known
answer. None of them asks "is this number a FUNCTION OF THE DESIGN AT ALL".
Those are different questions and the second one has a failure mode the first
cannot see: an extractor that returns a constant passes every known-answer test
whose fixture happens to be that constant.

The class is real and it has been here. `_ppa/feasibility.py` records the purest
instance in its own words -- both `timing.setup.wns_ns` and `timing.hold.wns_ns`
were NOT_MEASURED on every view, because the multi-corner sign-off emitters call
`report_worst_slack` and `report_tns` and never `report_wns`, so:

    the hold axis was STRUCTURALLY unprovable: no run of this flow could
    produce the evidence it proved from, on any design, ever.

That was found by reading. This file makes the same question a RUN: give the
extractor two designs that differ, and require the output to differ.

THE FOUR WAYS A PROBE LIKE THIS LIES, EACH PINNED BY ITS OWN ASSERTION
=====================================================================
All four were MEASURED while this file was being written -- every one of them
produced a wrong verdict before it was closed, and each is the same disease the
file exists to catch:

1. THE PROBE DID NOT MOVE THE INPUT IT TESTS. `timing.*.worst_path_slack_ns` is
   parsed from the per-path `slack (MET)` line, not from the `worst slack`
   summary. A mutation that edits only the summary reports it INERT and the
   extractor is innocent. `_assert_really_mutated` requires every input the
   assertions read to have actually changed.

2. THE PROBE COMPARED A SUBSET AND CALLED IT ALL. Joining records with
   `setdefault` collapsed 24 power records to 4 and reported clean on the 4. A
   probe that checks 4 of 24 IS the defect it is hunting, so the join asserts it
   covers every record on both sides.

3. ABSENT COMPARED EQUAL TO ABSENT. Two `None` digests are not "the same
   digest", they are "I could not look" twice -- exactly what
   `ppa_metric_extract`'s own SCOPE_SENTINEL refusal exists to prevent. Every
   comparison here refuses to conclude from a pair of missing values.

4. TWO UNMEASURED DESIGNS AGREED. An all-NOT_MEASURED document is identical for
   every design, correctly. Concluding "inert" from it is wrong, so the
   end-to-end arm asserts `census.measured > 0` on BOTH arms before comparing.

EQUAL OUTPUT FOR EQUAL INPUT IS NOT A DEFECT. A design with no macros reports
zero macro power on every run. These arms only ever compare metrics whose INPUT
was changed.

chip/PDK/vendor-AGNOSTIC: the fixtures under `fixtures/ppa/` only.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))

from _ppa import power as P      # noqa: E402
from _ppa import timing as T     # noqa: E402

_STA_FIX = _TESTS / "fixtures" / "ppa" / "sta" / "known_answer" / "views"
_PWR_FIX = _TESTS / "fixtures" / "ppa" / "power" / "activity_basis_pair"

#: A visible, non-zero shift. Not 0 (which would move nothing) and not a value
#: that could collide with a real number in the fixture.
_SHIFT = 3.25


# ---------------------------------------------------------------------------
# timing
# ---------------------------------------------------------------------------
def _bump_every_slack(text: str) -> str:
    """Move EVERY number the timing assertions read.

    The summary lines AND the per-path `slack (MET)` line. Moving only the
    summary is failure mode 1 in this file's header.
    """
    def add(m):
        return f"{m.group(1)}{float(m.group(2)) + _SHIFT:.2f}"
    text = re.sub(r"(worst slack \w+ )(-?\d+\.\d+)", add, text)
    text = re.sub(r"(tns \w+ )(-?\d+\.\d+)", add, text)
    text = re.sub(r"( {2,})(-?\d+\.\d+)(\s+slack \()",
                  lambda m: f"{m.group(1)}{float(m.group(2)) + _SHIFT:.2f}{m.group(3)}",
                  text)
    return text


def _sta_project(root: Path, mutate) -> Path:
    d = root / "phase3" / "stage3" / "sta"
    d.mkdir(parents=True, exist_ok=True)
    srcs = sorted(_STA_FIX.glob("*.rpt"))
    assert srcs, f"no STA fixture under {_STA_FIX}; nothing would be checked"
    for src in srcs:
        (d / f"sta_{src.name}").write_text(mutate(src.read_text()))
    return root


def _assert_really_mutated(a: Path, b: Path) -> None:
    """The probe's own non-vacuity: the two trees must actually differ."""
    fa = sorted((a / "phase3" / "stage3" / "sta").glob("*.rpt"))
    fb = sorted((b / "phase3" / "stage3" / "sta").glob("*.rpt"))
    assert fa and len(fa) == len(fb), (fa, fb)
    changed = sum(1 for x, y in zip(fa, fb) if x.read_text() != y.read_text())
    assert changed == len(fa), (
        f"the mutation changed {changed} of {len(fa)} artefact(s); an arm that "
        f"did not move its own input cannot conclude anything about the tool")


def _key(row):
    return (row["metric"], json.dumps(row.get("scope"), sort_keys=True))


def test_timing_rows_move_when_the_reported_slack_moves(tmp_path):
    a = _sta_project(tmp_path / "a", lambda t: t)
    b = _sta_project(tmp_path / "b", _bump_every_slack)
    _assert_really_mutated(a, b)

    ra, na = T.timing_rows(a)
    rb, nb = T.timing_rows(b)
    assert ra and rb, f"no rows; nothing was checked. notes={na} {nb}"

    ka = {_key(r): r for r in ra}
    kb = {_key(r): r for r in rb}
    common = sorted(set(ka) & set(kb))
    assert common, "no (metric, scope) key is common to both designs"

    inert, moved, absent = [], [], []
    for k in common:
        va, vb = ka[k].get("value"), kb[k].get("value")
        if va is None and vb is None:
            # ABSENT IS NOT EQUAL -- failure mode 3. Never a finding.
            absent.append(k)
            continue
        (moved if va != vb else inert).append((k, va, vb))

    assert moved, (
        "not one valued metric moved when every reported slack in the artefact "
        "moved; the timing extractor is not reading the design")
    assert not inert, (
        "metric(s) held the SAME value for two designs whose every reported "
        "slack differs -- a measurement that never happened: "
        + "; ".join(f"{m} A={va!r} B={vb!r}" for (m, _s), va, vb in inert))


def test_a_timing_row_without_a_value_says_why(tmp_path):
    """The other half: a metric with no number must DISCLOSE, not go quiet.

    `NOT_MEASURED` with a reason is honest. A row that simply carries no value
    and no reason is the same silence in a new place.
    """
    a = _sta_project(tmp_path / "a", lambda t: t)
    rows, _ = T.timing_rows(a)
    assert rows, "no rows; nothing was checked"
    quiet = [r for r in rows
             if r.get("value") is None and not (r.get("reason") or "").strip()]
    assert not quiet, (
        "row(s) carry no value and no reason, so a reader cannot tell "
        "'not measured' from 'measured as nothing': "
        + ", ".join(sorted(r["metric"] for r in quiet)))


# ---------------------------------------------------------------------------
# power
# ---------------------------------------------------------------------------
def _power_pair():
    a = (_PWR_FIX / "vectorless_sdc.rpt")
    b = (_PWR_FIX / "vector_vcd.rpt")
    assert a.is_file() and b.is_file(), f"power fixture pair missing under {_PWR_FIX}"
    ta, tb = a.read_text(), b.read_text()
    assert ta != tb, "the two fixture reports are identical; nothing would be checked"
    return ta, tb


def _joined(recs):
    """Index by full scope MINUS activity_basis, refusing to collapse.

    Failure mode 2: a join that silently drops records reports clean on the
    survivors.
    """
    out = {}
    for r in recs:
        sc = dict(r.get("scope") or {})
        sc.pop("activity_basis", None)
        k = (r["metric"], json.dumps(sc, sort_keys=True))
        assert k not in out, f"join would collapse two records at {k}"
        out[k] = r
    return out


def test_power_records_move_where_the_reported_numbers_move():
    ta, tb = _power_pair()
    ma = P.metric_records(P.parse_power_report(ta, path="a.rpt"), stage="signoff")
    mb = P.metric_records(P.parse_power_report(tb, path="b.rpt"), stage="signoff")
    assert ma and mb, "no power records; nothing was checked"

    ka, kb = _joined(ma), _joined(mb)
    common = sorted(set(ka) & set(kb))
    assert len(common) == len(ma) == len(mb), (
        f"the comparison covers {len(common)} of {len(ma)}/{len(mb)} records; a "
        f"probe that skips records and reports clean is the defect it hunts")

    moved = [k for k in common
             if ka[k].get("value") is not None
             and ka[k].get("value") != kb[k].get("value")]
    assert moved, (
        "not one power metric differs between two reports of DIFFERENT activity "
        "basis whose totals differ; the power extractor is not reading the "
        "artefact")

    # The groups that agree must agree because their INPUT agrees. Equal output
    # for equal input is a measurement; this asserts that and nothing stricter.
    same = [k for k in common
            if ka[k].get("value") is not None
            and ka[k].get("value") == kb[k].get("value")]
    for k in same:
        g = (ka[k].get("scope") or {}).get("group")
        assert ka[k].get("value") == 0.0, (
            f"{k[0]} (group={g!r}) is identical across two different reports at "
            f"a NON-zero value {ka[k].get('value')!r}. A shared non-zero number "
            f"is not explained by 'this design has none of those'.")


def test_a_group_the_artefact_never_mentions_is_not_reported_as_zero():
    """ABSENT IS NOT ZERO.

    If the artefact carries no `Macro` row and the extractor emits
    `power.*{group: Macro} = 0.0`, a reader cannot tell "this design has no
    macros" from "nobody looked at the macros".
    """
    ta, _ = _power_pair()
    stripped = "\n".join(l for l in ta.splitlines()
                         if not re.match(r"^\s*Macro\s", l)) + "\n"
    assert stripped != ta, "the Macro row was not removed; nothing would be checked"
    assert not re.search(r"^\s*Macro\s", stripped, re.M), "Macro row still present"

    full = P.metric_records(P.parse_power_report(ta, path="f.rpt"), stage="signoff")
    less = P.metric_records(P.parse_power_report(stripped, path="s.rpt"), stage="signoff")

    def groups(recs):
        return {(r.get("scope") or {}).get("group") for r in recs}

    assert "Macro" in groups(full), (
        "the unmodified fixture carries no Macro group, so removing it proves "
        "nothing -- this arm needs a fixture that has one")
    bad = [r for r in less
           if (r.get("scope") or {}).get("group") == "Macro"
           and r.get("status") == "MEASURED"]
    assert not bad, (
        "a group the artefact does NOT mention is reported as a MEASURED value "
        "-- an invented measurement: "
        + ", ".join(f"{r['metric']}={r.get('value')!r}" for r in bad))


# ---------------------------------------------------------------------------
# end to end, on the wired chain
# ---------------------------------------------------------------------------
def _signoff_design(root: Path, drc_violations: int) -> Path:
    """A sign-off tree whose DRC count is the thing that varies.

    `summary.real_violation_total` > 0 is MEASURED outright (read_drc rule 1:
    "items cannot be reported by a deck that never ran"), so both arms carry a
    real measured number without dragging in the zero-is-earned vacuity
    machinery, which is a different question with its own fixtures.
    """
    d = root / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "drc_signoff.json").write_text(json.dumps(
        {"summary": {"real_violation_total": drc_violations,
                     "categories_found": ["a", "b"]},
         "deck": "open.drc", "tool": "klayout"}))
    (d / "lvs_verdict.json").write_text(json.dumps(
        {"status": "PASS", "finding": "LVS_MATCH"}))
    return root


def _chain_at(run_dir: Path, work: Path, drc_violations: int):
    """Build a design AT `run_dir` and push it through the wired chain.

    THE RUN DIRECTORY IS A PARAMETER AND BOTH ARMS PASS THE SAME ONE. Measured
    while writing this file: the bundle digest of two BYTE-IDENTICAL designs
    differs when they sit at different paths, because NOT_MEASURED reasons and
    source fields carry the run path. An arm that built its two designs at
    `tmp/a` and `tmp/b` would therefore go green with every metric pinned to a
    constant -- it would be measuring the directory name. The negative control
    below fails loudly if that ever becomes true again.
    """
    if run_dir.exists():
        shutil.rmtree(run_dir)
    _signoff_design(run_dir, drc_violations)
    recs = work / "rec.json"
    if recs.exists():
        recs.unlink()
    r1 = subprocess.run(
        [sys.executable, str(_PROGRAMS / "ppa_signoff_records.py"),
         str(run_dir), "--json", str(recs), "--quiet"],
        capture_output=True, text=True)
    assert recs.is_file(), (
        f"ppa_signoff_records wrote no bundle (rc={r1.returncode}): "
        f"{(r1.stdout or '') + (r1.stderr or '')}")
    doc = json.loads(recs.read_text())
    bundle = work / "bun.json"
    if bundle.exists():
        bundle.unlink()
    r2 = subprocess.run(
        [sys.executable, str(_PROGRAMS / "ppa_metric_extract.py"),
         "--records", str(recs), "--out", str(bundle)],
        capture_output=True, text=True)
    assert bundle.is_file(), (
        f"ppa_metric_extract wrote no bundle (rc={r2.returncode}): "
        f"{(r2.stdout or '') + (r2.stderr or '')}")
    b = json.loads(bundle.read_text())
    measured = {r["metric"]: r.get("value") for r in b.get("records", [])
                if r.get("status") == "MEASURED"}
    return doc.get("census") or {}, b.get("records_digest"), measured


def test_two_identical_designs_agree_the_negative_control(tmp_path):
    """THE CONTROL THAT MAKES THE NEXT ARM MEAN ANYTHING.

    If two byte-identical designs at ONE path disagree, the bundle depends on
    something that is not the design, and "the digest moved" stops being
    evidence that the design moved. This is the arm that caught exactly that:
    the digest is path-dependent, so the two designs must share a run
    directory.
    """
    run = tmp_path / "run"
    ca, da, ma = _chain_at(run, tmp_path, 3)
    cb, db, mb = _chain_at(run, tmp_path, 3)
    assert ca.get("measured", 0) > 0, f"nothing measured; census={ca}"
    assert da and db, f"no records_digest (A={da!r} B={db!r})"
    assert ma == mb, (
        f"two byte-identical designs produced different MEASURED values: "
        f"{ma} vs {mb}")
    assert da == db, (
        f"two byte-identical designs at the same path produced DIFFERENT "
        f"bundle digests ({da} vs {db}); the bundle depends on something that "
        f"is not the design, so a digest change cannot be read as a design "
        f"change")


def test_the_signoff_bundle_digest_moves_with_the_design(tmp_path):
    """The whole chain, in the shape the flow actually wires it:

        sign-off artefacts -> ppa_signoff_records -> ppa_metric_extract
                           -> vibeic.ppa.metric_bundle.v1 records_digest

    Same run directory, same everything, ONE number different. If the bundle
    does not move, every comparison built on it is inert.
    """
    run = tmp_path / "run"
    ca, da, ma = _chain_at(run, tmp_path, 3)
    cb, db, mb = _chain_at(run, tmp_path, 11)

    # Failure mode 4: two designs nobody measured agree, correctly.
    assert ca.get("measured", 0) > 0 and cb.get("measured", 0) > 0, (
        f"NOTHING WAS MEASURED on one or both arms (A={ca}, B={cb}); two "
        f"all-NOT_MEASURED documents are identical for every design and this "
        f"arm must not read that as a finding about the tool")

    # The measured population must itself move, or the digest could be moving
    # on something incidental.
    assert ma != mb, (
        f"no MEASURED value differs between a design with 3 DRC violations and "
        f"one with 11: {ma} vs {mb}")
    assert ma.get("physical.drc.violations") == 3, ma
    assert mb.get("physical.drc.violations") == 11, mb

    # Failure mode 3: absent is not equal.
    assert da and db, (
        f"the bundle carries no records_digest (A={da!r} B={db!r}); the digest "
        f"could not be read, which is not the same as two digests agreeing")
    assert da != db, (
        f"two designs with different DRC violation counts produced the SAME "
        f"bundle digest {da} -- the bundle does not depend on the design")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
