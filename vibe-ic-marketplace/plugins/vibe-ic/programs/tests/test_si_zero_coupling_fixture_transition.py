#!/usr/bin/env python3
"""test_si_zero_coupling_fixture_transition.py — the SI zero, on a fixture that
ships with the repository.

WHY THIS FILE EXISTS AND ITS SIBLING IS NOT ENOUGH
--------------------------------------------------
``test_si_zero_coupling_is_not_a_signoff.py`` pins the gate's behaviour AFTER
the fix. It cannot show the TRANSITION, and the transition is the whole claim:
that the same artefact used to come out of this gate as a clean sign-off.

That claim was originally stated against
``benchmark-data/ic/spm/v1.5.58_ihp-sg13g2/reports/phase3/si_mcf_sta.json``,
whose ``coupling_pairs: 0`` sits next to ``verdict: PASS``. The report is real,
but its ``spef`` field is an ABSOLUTE PATH inside the authoring machine's
campaign directory. On any other host ``Path(orig_spef).exists()`` is False, the
gate exits down its missing-SPEF branch, and the coupling-count decision is
never reached — so a reviewer re-running the published before/after measures a
DIFFERENT BRANCH OF THE SAME GATE and gets rc 1 on both trees. The finding was
right and the numbers were unverifiable, which for a repository whose subject is
false certificates is not a distinction worth keeping.

So the demonstration is moved onto ``fixtures/si_mcf_zero_coupling/``: two
complete project directories, tracked, carrying no absolute path, differing by
exactly one 4-token coupling ``*CAP`` line.

THE MEASUREMENT THIS FILE PINS (real CLI, emitted JSON, both directories)

    grounded_only   pre-fix: rc 0  PASS   |  this tree: rc 2  VACUOUS_PASS
    coupled         pre-fix: rc 0  PASS   |  this tree: rc 0  PASS

and — the part that is the defect rather than the fix — on the PRE-FIX gate the
two directories produced summaries whose every verdict-bearing field was
IDENTICAL: ``pass: True``, ``errors_count: 0``, ``findings_count: 0``. The only
field that differed was ``coupling_pairs`` (0 vs 1), which the gate counted,
printed, and never turned into a finding.

HOW THE PRE-FIX ANSWER IS OBTAINED WITHOUT CHECKING OUT THE PRE-FIX TREE
------------------------------------------------------------------------
It is not re-implemented and no source text is read. ``build_report`` before the
fix was one predicate over the SAME findings this gate still emits —
``all(f.severity != "ERROR")`` — with ``PASS``/rc 0 on True. Every input to that
predicate is in the JSON the current CLI writes (``summary.errors_count``,
``summary.findings_count``, ``findings``), so the tests below apply it to the
emitted report rather than to a copy of the old code. What is asserted is
therefore a property of TODAY's run: *this artefact yields zero ERROR findings*,
which under the old rule is a clean PASS and under the new one is a disclosed
skip.

MEASURED, both trees, by hand, before this file was written (identical to what
the assertions below encode):

    origin/main  9dd8b0aab   grounded_only -> rc 0  PASS  {pass:True, errors:0}
    origin/main  9dd8b0aab   coupled       -> rc 0  PASS  {pass:True, errors:0}
    this branch              grounded_only -> rc 2  VACUOUS_PASS  examined 0/0
    this branch              coupled       -> rc 0  PASS          examined 2/4

The fixture is a faithful miniature of the tracked artefact on the axis that
matters: ``folds_proved_per_corner`` is ``{"setup": 2, "hold": 0}`` here and
``{"setup": 365, "hold": 0}`` on the 1,558-pair tracked sibling — the same
structural hold-corner hole, at a scale a reviewer can read.

THE ARMS, EACH WITH ITS OWN CASE
--------------------------------
Zero coupling pairs is not automatically a defect, so the change is a three-way
judgement and every arm is pinned here from the same shipped bytes:

    grounded-only, well-formed              -> VACUOUS_PASS, rc 2  (undecidable)
    SPEF resolves to no net at all          -> ERROR SPEF_NO_NET_RECORDS,   rc 1
    emitter saw pairs, gate re-parses none  -> ERROR COUPLING_LOST_SINCE_EMIT,rc 1
    no coupling, yet bounded gained charge  -> ERROR FOLD_WITHOUT_SOURCE,   rc 1
    genuinely coupled and folded            -> PASS, rc 0        (must stay one)

The last line is load-bearing: without it the change could become a blanket FAIL
on the coupling axis and every test above would still be green.

WHAT IS DELIBERATELY NOT FIXED HERE
------------------------------------
The dangling absolute path in the tracked report. ``shipped_path_portability_
check`` covers plugin source and does not look at ``benchmark-data`` reports, so
a committed sign-off artefact may still name ``/home/<user>/...`` and be
un-re-derivable by anyone else. This file pins that THIS fixture is portable
(``test_the_shipped_fixture_names_no_absolute_path``); making the emitter or the
publisher enforce it repo-wide is a separate change.

chip-AGNOSTIC: the fixture carries ``net_a`` / ``net_b`` / ``ua`` / ``ub`` /
``BUF`` / ``DFF``. No design, PDK, foundry, vendor or cell-library literal
appears in this file or in the fixture it drives.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PROG = _PROGRAMS / "si_mcf_sta_check.py"
_FIXTURE = _TESTS / "fixtures" / "si_mcf_zero_coupling"
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import si_mcf_sta as M            # noqa: E402
import _gate_denominator as _gd   # noqa: E402

_CASES = ("grounded_only", "coupled")
#: The one line that is the whole experiment.
_COUPLING_LINE = "3 ub:A ua:B 0.1\n"


# ---------------------------------------------------------------------------
# helpers — every one of them drives the REAL CLI and reads the emitted JSON
# ---------------------------------------------------------------------------
def _run(project_dir: Path, out_json: Path, cwd: Path | None = None):
    """Run the shipped gate. ``--json`` ALWAYS points outside the repository:
    without it the gate writes into ``reports/phase3/`` of the project it was
    handed, and for the shipped fixture that project is tracked."""
    r = subprocess.run([sys.executable, str(_PROG), str(project_dir),
                        "--json", str(out_json)],
                       capture_output=True, text=True, timeout=60,
                       cwd=str(cwd) if cwd else None)
    return r, json.loads(out_json.read_text())


def _run_shipped(case: str, tmp_path: Path):
    """Drive the tracked fixture in place, cwd = the fixture directory (its
    ``si_mcf_sta.json`` names ``design.spef``, relative, on purpose)."""
    return _run(Path("."), tmp_path / f"{case}.json", cwd=_FIXTURE / case)


def _materialise(case: str, tmp_path: Path) -> Path:
    """Copy the shipped fixture into ``tmp_path`` and rewrite its report to
    ABSOLUTE paths — the shape the real emitter writes. Perturbations for the
    ERROR arms are applied to the copy, never to the tracked bytes."""
    dst = tmp_path / case
    shutil.copytree(_FIXTURE / case, dst)
    rp = dst / "reports" / "phase3" / "si_mcf_sta.json"
    doc = json.loads(rp.read_text())
    doc["spef"] = str(dst / doc["spef"])
    for corner in doc["corners"].values():
        corner["bounded_spef"] = str(dst / corner["bounded_spef"])
    rp.write_text(json.dumps(doc))
    return dst


def _denom(doc) -> dict:
    return doc["summary"][_gd.DENOMINATOR_KEY]


def _pre_fix_verdict(doc) -> str:
    """The gate's verdict under the rule that stood BEFORE this fix.

    ``build_report`` was ``ok = all(f.severity != "ERROR" for f in findings)``
    followed by ``"PASS" if ok else "FAIL"``, and ``main`` returned
    ``0 if pass else 1``. Applied here to the findings the CURRENT run emits —
    the predicate's only input — so this is a measurement of today's artefact
    under yesterday's rule, not a copy of yesterday's code."""
    errors = [f for f in doc["findings"] if f["severity"] == "ERROR"]
    return "FAIL" if errors else "PASS"


def _verdict_bearing(doc) -> dict:
    """The summary fields the PRE-FIX gate's verdict was a function of."""
    s = doc["summary"]
    return {"pass": _pre_fix_verdict(doc) == "PASS",
            "errors_count": s["errors_count"],
            "findings_count": s["findings_count"]}


# ---------------------------------------------------------------------------
# the fixture is honest about what it varies
# ---------------------------------------------------------------------------
def test_the_shipped_fixtures_differ_only_in_one_coupling_cap_line():
    grounded = (_FIXTURE / "grounded_only" / "design.spef").read_text()
    coupled = (_FIXTURE / "coupled" / "design.spef").read_text()
    assert coupled != grounded
    assert coupled.replace(_COUPLING_LINE, "") == grounded, (
        "the two shipped SPEFs must differ by exactly the coupling *CAP line, "
        "or the before/after measures something other than the coupling axis")
    assert len(M.coupling_pairs(grounded)) == 0
    assert len(M.coupling_pairs(coupled)) == 1
    # ...and both are real SPEFs carrying the SAME net records, so the zero is
    # a zero of COUPLING and not of substance.
    assert (sorted(M.net_grounded_totals(grounded))
            == sorted(M.net_grounded_totals(coupled)) == ["*1", "*2"])


def test_the_shipped_bounded_spefs_are_what_the_real_emitter_produces():
    """No hand-written answer key. Both bounded SPEFs are re-derived from the
    shipped ``design.spef`` with ``si_mcf_sta.rewrite_spef_folded`` — the very
    function ``si_mcf_sta.run()`` calls — and pinned byte-for-byte."""
    for case in _CASES:
        d = _FIXTURE / case
        spef = (d / "design.spef").read_text()
        pairs = M.coupling_pairs(spef)
        setup_fold = {k: v * 2
                      for k, v in M.floor_folded_caps(pairs, "setup").items()}
        hold_fold = M.floor_folded_caps(pairs, "hold")
        sb, _ = M.rewrite_spef_folded(spef, setup_fold, "setup")
        hb, _ = M.rewrite_spef_folded(spef, hold_fold, "hold")
        assert (d / "design.mcf_setup.spef").read_text() == sb, (
            f"{case}/design.mcf_setup.spef has drifted from the emitter — a "
            f"committed bounded SPEF that no longer matches the code that "
            f"produced it is a hand-maintained expectation, not a fixture")
        assert (d / "design.mcf_hold.spef").read_text() == hb


def test_the_shipped_fixture_names_no_absolute_path():
    """The reason this demonstration lives here at all.

    The tracked benchmark report this finding started from names
    ``/home/<user>/campaign_.../spm.spef``; on any other host the gate never
    reaches the decision under test. Nothing in this fixture may repeat that.

    SCOPE, stated rather than assumed: the ARTEFACT files — the ones the gate
    opens and whose paths it must resolve. The README is prose that quotes both
    the defect (`/home/<user>/...`) and an output path outside the repository
    (`--json /tmp/...`, which is the correct instruction, not a hazard), and
    judging documentation by the rule for inputs would fail it for describing
    the thing accurately."""
    offenders = []
    scanned = 0
    for path in sorted(_FIXTURE.rglob("*")):
        if not path.is_file() or path.suffix not in (".spef", ".json"):
            continue
        scanned += 1
        for m in re.finditer(r"(?<![\w.-])/(?:home|Users|tmp|var|opt)/[\w./-]+",
                             path.read_text(errors="replace")):
            offenders.append(f"{path.relative_to(_FIXTURE)}: {m.group(0)}")
    # A guard that stopped finding files would report "no absolute paths"
    # forever — the falsely-clean verdict this whole change is about.
    assert scanned == 8, f"expected 8 fixture artefacts, scanned {scanned}"
    assert not offenders, (
        "a fixture carrying a host-absolute path is not reproducible by "
        "anyone else — that is the hazard this fixture replaces: "
        + "; ".join(offenders))


# ---------------------------------------------------------------------------
# THE TRANSITION — the defect, and the fix, on the same shipped bytes
# ---------------------------------------------------------------------------
def test_the_pre_fix_rule_called_both_directories_a_clean_pass(tmp_path):
    """THE DEFECT. Under the rule that stood before this fix, the run that
    re-derived nothing and the run that re-derived every fold are
    indistinguishable in every verdict-bearing field."""
    _, grounded = _run_shipped("grounded_only", tmp_path)
    _, coupled = _run_shipped("coupled", tmp_path)

    assert _pre_fix_verdict(grounded) == "PASS"
    assert _pre_fix_verdict(coupled) == "PASS"
    assert _verdict_bearing(grounded) == _verdict_bearing(coupled) == {
        "pass": True, "errors_count": 0, "findings_count": 0}
    # The one field that DID differ, and that the old gate never consulted.
    assert grounded["summary"]["coupling_pairs"] == 0
    assert coupled["summary"]["coupling_pairs"] == 1


def test_the_grounded_only_fixture_now_exits_vacuous(tmp_path):
    """THE FIX, first half: rc 0 -> rc 2 on the artefact that proved nothing."""
    r, doc = _run_shipped("grounded_only", tmp_path)
    assert r.returncode == 2, r.stderr
    assert doc["verdict"] == "VACUOUS_PASS"
    assert doc["summary"]["pass"] is False
    assert doc["summary"]["vacuous"] is True
    den = _denom(doc)
    assert den["examined"] == 0
    assert den["considered"] == 0
    assert "0 inter-net coupling pairs" in den["not_applicable_reason"]
    assert "NOT CHECKED" in den["not_applicable_reason"]
    assert "VACUOUS_PASS:" in r.stderr


def test_the_coupled_sibling_still_signs_off(tmp_path):
    """THE FIX, second half — and the arm that MUST NOT move. A change that
    turned the coupling axis into a blanket FAIL would leave every assertion
    above green."""
    r, doc = _run_shipped("coupled", tmp_path)
    assert r.returncode == 0, r.stderr
    assert doc["verdict"] == "PASS"
    assert doc["summary"]["pass"] is True
    assert doc["summary"]["vacuous"] is False
    den = _denom(doc)
    assert den["examined"] > 0
    assert den["not_applicable_reason"] == ""


def test_the_two_directories_are_no_longer_verdict_identical(tmp_path):
    """The single sentence the whole change is worth: the empty sign-off and
    the proved one now disagree, at the exit code AND in the report."""
    rg, grounded = _run_shipped("grounded_only", tmp_path)
    rc, coupled = _run_shipped("coupled", tmp_path)
    assert (rg.returncode, grounded["verdict"]) == (2, "VACUOUS_PASS")
    assert (rc.returncode, coupled["verdict"]) == (0, "PASS")
    assert _denom(grounded)["examined"] != _denom(coupled)["examined"]


def test_the_disclosure_contract_holds_on_both_directories(tmp_path):
    for case in _CASES:
        _, doc = _run_shipped(case, tmp_path)
        assert _gd.disclosure_violations(doc["summary"]) == [], case


def test_the_hold_corner_is_disclosed_as_proving_nothing(tmp_path):
    """The fixture is a miniature of the tracked artefact on the axis that
    matters. ``MCF_HOLD_WORST`` is 0, so in window-independent floor mode every
    hold expectation is 0.0 and no hold comparison can fail. The gate says so
    per corner instead of reporting the visits as coverage."""
    _, doc = _run_shipped("coupled", tmp_path)
    den = _denom(doc)
    assert den["details"]["folds_proved_per_corner"] == {"setup": 2, "hold": 0}
    assert den["details"]["nets_compared_per_corner"] == {"setup": 2, "hold": 2}
    assert (den["considered"], den["examined"]) == (4, 2)


def test_absolute_paths_reach_the_same_verdict(tmp_path):
    """The fixture's relative paths are a portability choice, not a special
    case: rewritten to the absolute form the real emitter writes, and run from
    an unrelated cwd, both directories answer identically."""
    for case, want_rc, want_verdict in (("grounded_only", 2, "VACUOUS_PASS"),
                                        ("coupled", 0, "PASS")):
        proj = _materialise(case, tmp_path)
        r, doc = _run(proj, tmp_path / f"abs_{case}.json")
        assert (r.returncode, doc["verdict"]) == (want_rc, want_verdict), r.stderr


# ---------------------------------------------------------------------------
# the three DECIDABLE causes of a zero — ERROR, not a skip
# ---------------------------------------------------------------------------
def test_a_spef_resolving_to_no_net_is_an_error(tmp_path):
    proj = _materialise("grounded_only", tmp_path)
    spef = proj / "design.spef"
    head = spef.read_text().split("*D_NET", 1)[0]
    spef.write_text(head)                       # header only: no net, any form
    r, doc = _run(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert doc["verdict"] == "FAIL"
    assert [f["category"] for f in doc["findings"]] == ["SPEF_NO_NET_RECORDS"]


def test_coupling_lost_since_the_numbers_were_emitted_is_an_error(tmp_path):
    """The emitter's own report says it read coupling out of this path; the
    gate re-parses the SAME path with the SAME parser and finds none."""
    proj = _materialise("grounded_only", tmp_path)
    rp = proj / "reports" / "phase3" / "si_mcf_sta.json"
    doc = json.loads(rp.read_text())
    doc["coupling_pairs"] = 1558
    rp.write_text(json.dumps(doc))
    r, out = _run(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert out["verdict"] == "FAIL"
    assert "COUPLING_LOST_SINCE_EMIT" in [f["category"] for f in out["findings"]]


def test_a_fold_with_no_source_is_an_error(tmp_path):
    """Nothing to fold, yet the bounded SPEF carries MORE grounded charge than
    the original — the two files are not a matched pair."""
    proj = _materialise("grounded_only", tmp_path)
    bounded = proj / "design.mcf_setup.spef"
    bounded.write_text(bounded.read_text().replace("1 ua:Z 0.1", "1 ua:Z 0.9"))
    r, doc = _run(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert doc["verdict"] == "FAIL"
    assert "FOLD_WITHOUT_SOURCE" in [f["category"] for f in doc["findings"]]


def test_a_dropped_fold_on_the_coupled_fixture_still_fails(tmp_path):
    """Direction-1 guard: the rule this gate was WRITTEN for must survive the
    change. Hand the coupled fixture a bounded SPEF that never folded, and the
    original FOLD_NOT_APPLIED failure must still fire."""
    proj = _materialise("coupled", tmp_path)
    unfolded = (proj / "design.spef").read_text()
    (proj / "design.mcf_setup.spef").write_text(unfolded)
    (proj / "design.mcf_hold.spef").write_text(unfolded)
    r, doc = _run(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert doc["verdict"] == "FAIL"
    assert "FOLD_NOT_APPLIED" in [f["category"] for f in doc["findings"]]


def test_a_run_that_never_started_is_not_credited_as_a_skip(tmp_path):
    """rc 2 is the disclosed-skip tier and the flow credits it as a pass. A
    mis-invoked run must not land in it."""
    r = subprocess.run([sys.executable, str(_PROG),
                        str(tmp_path / "does_not_exist")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
