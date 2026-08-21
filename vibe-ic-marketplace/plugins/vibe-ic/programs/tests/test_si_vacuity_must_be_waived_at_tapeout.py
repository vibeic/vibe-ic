#!/usr/bin/env python3
"""Step 36 (tapeout sign-off) certified a chip whose SI check never ran.

WHAT WAS MEASURED
=================
`si_mcf_sta_check` carries a disclosed skip tier: when it re-derives ZERO
victim-net MCF folds it returns rc 2 / `verdict: VACUOUS_PASS`, and its own
written reason ends "Read this as NOT CHECKED". The flow's step-27 gate credits
rc 2 as a pass, which is the right call during development.

The tape-out checklist then read that as a green light. Measured on a tracked
run in this repo (one of three PDK variants of the same benchmark design, the
one whose SPEF carries 465 net records and ZERO two-node coupling caps), with
the plugin at the commit that introduced the VACUOUS tier::

    $ python3 programs/si_mcf_sta_check.py <run>
    rc=2   verdict VACUOUS_PASS   vacuity SPEF_NO_COUPLING_PAIRS
    $ python3 programs/tapeout_signoff_check.py <run>
    rc=0   verdict_tier PASS

Byte-for-byte the same sign-off a run with a fully re-derived and proved fold
gets. "SI was checked and is clean" and "SI was never checked" were the same
green light at the moment the design is committed to a mask set — and crosstalk
is a mechanism that kills silicon.

THE RULE THIS FILE PINS
=======================
At the tape-out sign-off gate ONLY (step 27 is untouched — development is not
blocked), a VACUOUS SI verdict blocks unless the SPECIFIC vacuity is accepted
through the repo's ONE governed waiver channel: a `<project>/waivers.json`
`waived_steps` entry that names the tape-out step id, carries a human
`approver` and a real `reason`, and lists the vacuity code the SI report itself
published in `summary.denominator.details.vacuity_code`.

Five things a waiver may never do, each pinned below:
  * launder a genuine SI FAIL,
  * cover an ABSENT or unparseable report (nothing ran — there is no
    disclosure to accept),
  * cover a PASS carrying no denominator (the pre-fix false-clean shape),
  * cover a report that CONTRADICTS ITSELF — on the VACUOUS branch exactly as
    on the PASS branch. The verdict field is one editable string; the report
    body is the evidence the gate derived it from, so a FAIL relabelled
    VACUOUS_PASS is still read as a failure. See the section at the end.
  * be minted by the runner itself.

And silence is never disclosure: a code comment, a marker file, or a blanket
"SI waived" does not satisfy it.

chip-AGNOSTIC: synthetic project trees only; no design name, PDK SKU, rail or
cell literal appears here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import signoff_audit as sa  # noqa: E402
import si_mcf_sta_check as sic  # noqa: E402
import _gate_denominator as _gd  # noqa: E402
import _gdsii  # noqa: E402
# One real-report control below reads PUBLISHED cells, which now live in
# vibeic/benchmark-data. `_published_corpus` owns the single "is a published
# cell readable here?" answer and the single skip reason.
from _published_corpus import corpus_root, needs_corpus  # noqa: E402

_DECLARED_GDS = "phase3/stage4/gds/top.gds"
# Read through `getattr` on purpose. Bound at MODULE scope, a hard
# `sa._SI_REPORT_REL` turns "the production change was reverted" into a single
# pytest COLLECTION ERROR instead of N named failures, and a collection error
# reads like a broken environment rather than a regression. With the fallback,
# every test that depends on the change still goes red individually and says
# which guarantee it lost. The fallback is not a loophole: if the constant is
# ever renamed, the fixtures write to a path the gate no longer reads and the
# tests fail as ABSENT — loudly, either way.
_SI_REPORT = getattr(sa, "_SI_REPORT_REL",
                     "reports/phase3/si_mcf_sta_check.json")

_LVS_MATCH = """\
Subcircuit summary:
Circuit 1: top                          |Circuit 2: top
Netlists match uniquely.
Final result: Circuits match uniquely.
"""

_GOOD_REASON = ("Extraction produced a grounded-only SPEF for this partition; "
                "crosstalk-delay is signed off by the foundry-side commercial "
                "SI deck against the same routed DEF.")
_GOOD_APPROVER = "A. Reviewer (tape-out review board)"


# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------
def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _five_pillars(proj: Path) -> Path:
    """GDS + netlist + STA + clean DRC + a genuine LVS match.

    Everything the tape-out checklist required BEFORE this change, so every
    assertion below is decided by the SI condition and nothing else."""
    _gdsii.write_gdsii(proj / _DECLARED_GDS)
    _write(proj / "phase3" / "stage3" / "pnr" / "top_pnr.v",
           "module top(); endmodule\n")
    _write(proj / "phase3" / "stage3" / "sta" / "post_route_timing.rpt",
           "slack (MET) 0.10\n")
    _write(proj / "drc_signoff.rpt", "Total violations: 0\n")
    _write(proj / "reports" / "phase3" / "lvs.rpt", _LVS_MATCH)
    return proj


def _si_report(proj: Path, verdict: str, examined: int = 0,
               vacuity_code: str = "", denominator: bool = True,
               findings: list = None) -> Path:
    """An SI report in the shape `si_mcf_sta_check` writes.

    `errors_count` and `findings_count` are written HERE because
    `build_report` writes them, unconditionally, in the same dict literal as
    `findings` and from the same list. This fixture used to omit both while
    claiming to be emitter-shaped, and that divergence is what made "an older
    run might legitimately lack errors_count" sound plausible enough to pin a
    laundering route green. A fixture that does not carry what the emitter
    carries cannot measure what a consumer of the emitter will see.
    """
    findings = list(findings or [])
    summary: dict = {
        "pass": verdict == "PASS",
        "vacuous": examined == 0,
        "errors_count": sum(
            1 for f in findings
            if str(f.get("severity", "")).strip().upper() == "ERROR"),
        "findings_count": len(findings),
    }
    if denominator:
        summary["denominator"] = {
            "unit": "victim-net MCF folds",
            "examined": examined,
            "considered": max(examined, 1),
            "not_applicable_reason": (
                "nothing was re-derived. Read this as NOT CHECKED."
                if examined == 0 else ""),
            "details": {"vacuity_code": vacuity_code},
        }
    return _write(proj / _SI_REPORT, json.dumps(
        {"program": "si_mcf_sta_check", "verdict": verdict,
         "summary": summary, "findings": findings}, indent=2))


def _si_proved(proj: Path) -> Path:
    return _si_report(proj, "PASS", examined=365)


def _si_vacuous(proj: Path, code: str = "SPEF_NO_COUPLING_PAIRS") -> Path:
    return _si_report(proj, "VACUOUS_PASS", examined=0, vacuity_code=code)


def _waive(proj: Path, **over) -> Path:
    """Write a governed waiver entry. Keyword overrides mutate one field at a
    time so each refusal test differs from the accepted one in exactly one
    way."""
    entry = {"id": sa._TAPEOUT_STEP_ID,
             "reason": _GOOD_REASON,
             "approver": _GOOD_APPROVER,
             sa.SI_DISCLOSURE_FIELD: ["SPEF_NO_COUPLING_PAIRS"]}
    for k, v in over.items():
        if v is None:
            entry.pop(k, None)
        else:
            entry[k] = v
    return _write(proj / "waivers.json",
                  json.dumps({"waived_steps": [entry]}, indent=2))


def _si(result) -> dict:
    return result.summary["si_signoff"]


def _rules(result) -> list:
    return [f.rule for f in result.findings]


def _rc(proj: Path) -> int:
    return sa.main([str(proj), "--mode", "tapeout"])


#: Every ``_vacuity`` branch, with the stats dict that reaches it and the code
#: it must name. ONE table, because two consumers read it: the branch/code pin
#: below, and the rejection test at the end of this file, which offers a waiver
#: naming EVERY code this gate can emit and requires that none of them lets a
#: decided failure through. A code added without a row here fails the
#: nine-branch assertion immediately.
_VACUITY_BRANCHES = (
    ({}, "EMITTER_REPORT_UNREADABLE"),
    ({"report_read": True}, "SPEF_UNREADABLE"),
    ({"report_read": True, "spef_read": True,
      "spef_r_net_records": 7}, "SPEF_REDUCED_FORMAT_ONLY"),
    ({"report_read": True, "spef_read": True},
     "SPEF_NO_D_NET_RECORDS"),
    ({"report_read": True, "spef_read": True,
      "spef_net_records": 5}, "NO_CORNER_RECOUNTED"),
    ({"report_read": True, "spef_read": True, "spef_net_records": 5,
      "recount": {"setup": {"nets_checked": 0}}, "coupling_caps": 3},
     "COUPLING_CAPS_INTRA_NET_ONLY"),
    ({"report_read": True, "spef_read": True, "spef_net_records": 5,
      "recount": {"setup": {"nets_checked": 0}}},
     "SPEF_NO_COUPLING_PAIRS"),
    ({"report_read": True, "spef_read": True, "spef_net_records": 5,
      "recount": {"setup": {"nets_checked": 0}}, "coupling_pairs": 4},
     "NO_VICTIM_NET_RESOLVED"),
    ({"report_read": True, "spef_read": True, "spef_net_records": 5,
      "recount": {"setup": {"nets_checked": 2}}, "coupling_pairs": 4},
     "ALL_EXPECTATIONS_ZERO"),
)


# ===========================================================================
# The producer names its own vacuity, in a token a machine may cite
# ===========================================================================
def test_vacuity_code_and_prose_come_from_the_same_branch():
    """A consumer that must decide whether a SPECIFIC vacuity was accepted
    cannot substring-match a paragraph of English. The code is the contract;
    the prose is what a human reads. They are derived together so they can
    never disagree about which state the gate is in."""
    seen = {}
    for stats, expect in _VACUITY_BRANCHES:
        code, prose = sic._vacuity(stats)
        assert code == expect, f"{stats} -> {code}, expected {expect}"
        assert prose == sic._vacuous_reason(stats)
        assert prose.rstrip().endswith("Read this as NOT CHECKED.")
        seen[code] = True
    assert len(seen) == 9, "each branch must have its OWN code"


def test_a_proved_run_publishes_no_vacuity_code():
    """An empty code is what "there is no vacuity here" looks like, so a waiver
    can never be written against a run that proved something."""
    stats = {"report_read": True, "spef_read": True, "spef_net_records": 5,
             "coupling_pairs": 4,
             "recount": {"setup": {"nets_checked": 4, "folds_proved": 4}}}
    d = sic.denominator(stats)
    assert d.examined == 4 and d.is_vacuous is False
    assert d.as_dict()["details"]["vacuity_code"] == ""


# ===========================================================================
# The gate: PROVED passes, VACUOUS blocks
# ===========================================================================
def test_a_proved_si_verdict_signs_off_with_no_waiver_at_all(tmp_path):
    """THE FALSE-ALARM CONTROL. The only difference from the blocking case
    below is that the SI gate actually re-derived folds."""
    _five_pillars(tmp_path)
    _si_proved(tmp_path)

    r = sa._check_tapeout(tmp_path)
    assert r.passed is True
    assert r.summary["verdict_tier"] == "PASS"
    assert _si(r)["state"] == sa.SI_PROVED
    assert _si(r)["folds_proved"] == 365
    assert "TAPEOUT_SI_PROVED" in _rules(r)
    assert _rc(tmp_path) == 0


def test_a_vacuous_si_verdict_blocks_the_tapeout(tmp_path):
    """THE DEFECT. Same five pillars, same everything — only the SI gate
    proved nothing. Before this change: rc 0, verdict_tier PASS."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)

    r = sa._check_tapeout(tmp_path)
    assert r.passed is False
    assert r.summary["verdict_tier"] == "FAIL"
    assert _si(r)["state"] == sa.SI_VACUOUS
    assert _si(r)["vacuity_code"] == "SPEF_NO_COUPLING_PAIRS"
    f = [x for x in r.findings if x.rule == "TAPEOUT_SI_VACUOUS_UNWAIVED"]
    assert len(f) == 1 and f[0].severity == "ERROR"
    # The refusal must tell the reader how to disclose it, by name.
    assert sa.SI_DISCLOSURE_FIELD in f[0].message
    assert "SPEF_NO_COUPLING_PAIRS" in f[0].message
    assert _rc(tmp_path) == 1


def test_the_evidence_threshold_is_unchanged(tmp_path):
    """The SI condition is a VETO, not a sixth pillar: it must not move the
    5-of-5 denominator every existing consumer of `summary.threshold` reads."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    r = sa._check_tapeout(tmp_path)
    assert r.summary["threshold"] == 5
    assert r.summary["evidence_count"] == 5
    assert all(r.summary["evidence"][k] for k in
               ("gds", "netlist", "timing", "drc", "lvs"))
    assert r.passed is False  # ...and the veto still fires


# ===========================================================================
# The governed waiver: accepted, and the ways it is refused
# ===========================================================================
def test_a_governed_waiver_naming_the_step_and_the_vacuity_proceeds(tmp_path):
    """Accepted — and NOT as a bare PASS. rc 3 + the sentinel is what carries
    'this was waived, not proved' into the flow's step listing."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    _waive(tmp_path)

    r = sa._check_tapeout(tmp_path)
    assert r.passed is True
    assert r.summary["verdict_tier"] == "PASS_WITH_WAIVERS"
    assert _si(r)["waived"] is True
    assert _si(r)["waiver_approver"] == _GOOD_APPROVER
    assert _si(r)["waiver_reason"] == _GOOD_REASON
    assert "TAPEOUT_SI_VACUITY_WAIVED" in _rules(r)
    assert _rc(tmp_path) == sa.WAIVER_EXIT_CODE


def test_a_waiver_for_a_different_vacuity_does_not_accept_this_one(tmp_path):
    """"Names the specific vacuity" is the whole point: accepting "the SPEF is
    in REDUCED format" is not accepting "the extraction produced no coupling".
    This is also how a waiver EXPIRES when the underlying state changes."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path, code="SPEF_NO_COUPLING_PAIRS")
    _waive(tmp_path, **{sa.SI_DISCLOSURE_FIELD: ["SPEF_REDUCED_FORMAT_ONLY"]})

    r = sa._check_tapeout(tmp_path)
    assert r.passed is False
    assert _si(r)["waived"] is False
    assert _si(r)["accepted_vacuity_codes"] == ["SPEF_REDUCED_FORMAT_ONLY"]
    assert _rc(tmp_path) == 1


def test_a_blanket_waiver_is_refused(tmp_path):
    """A blanket accepts every future vacuity too, including ones nobody has
    seen. That is the "SI waived" the ruling forbids."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    for blanket in sorted(sa._SI_BLANKET_CODES):
        _waive(tmp_path, **{sa.SI_DISCLOSURE_FIELD: [blanket]})
        r = sa._check_tapeout(tmp_path)
        assert r.passed is False, f"blanket {blanket!r} was accepted"
        assert _si(r)["accepted_vacuity_codes"] == []
        assert _rc(tmp_path) == 1


def test_a_waiver_filed_against_another_step_does_not_accept_this_one(tmp_path):
    """"Names the step". A vacuity accepted at the Phase-3 SI step is not an
    acceptance at the mask order."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    _waive(tmp_path, id=27)

    r = sa._check_tapeout(tmp_path)
    assert r.passed is False
    assert _si(r)["accepted_vacuity_codes"] == []
    assert _rc(tmp_path) == 1


def test_an_unattributed_waiver_is_refused(tmp_path):
    """"Carries attribution". No approver, a self-approver, and an unfilled
    scaffold slot are all refused — predicates imported from
    `waivers_schema_check`, so this gate and the schema gate cannot drift."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    for approver in (None, "", "   ", "claude", "agent", "self",
                     "__TODO_HUMAN_NAME__", "<name>", "TBD", "reviewer"):
        _waive(tmp_path, approver=approver)
        r = sa._check_tapeout(tmp_path)
        assert r.passed is False, f"approver {approver!r} was accepted"
        assert _rc(tmp_path) == 1


def test_a_waiver_with_no_real_reason_is_refused(tmp_path):
    """"Carries a reason". Placeholders and stubs are refused by the same
    imported predicates."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    for reason in (None, "", "TODO", "n/a", "skip", "?", "too short"):
        _waive(tmp_path, reason=reason)
        r = sa._check_tapeout(tmp_path)
        assert r.passed is False, f"reason {reason!r} was accepted"
        assert _rc(tmp_path) == 1


def test_silence_is_not_disclosure(tmp_path):
    """A code comment discloses nothing to a machine; a marker file is a
    parallel, ungoverned channel a runner could mint for itself. Neither
    satisfies the gate."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    _write(tmp_path / "SI_WAIVED", "SI vacuity accepted by the team\n")
    _write(tmp_path / "reports" / "phase3" / "si_waiver.txt",
           "# SPEF_NO_COUPLING_PAIRS accepted\n")
    _write(tmp_path / "notes.py",
           "# SI vacuity SPEF_NO_COUPLING_PAIRS accepted at tapeout\n")

    r = sa._check_tapeout(tmp_path)
    assert r.passed is False
    assert _si(r)["waived"] is False
    assert _rc(tmp_path) == 1


def test_an_unreadable_or_non_object_waivers_file_accepts_nothing(tmp_path):
    """Fail-closed: malformed bytes disclose nothing and are not an error."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    for blob in ("{{{not json", "[]", "true", "null", "42",
                 '{"waived_steps": {}}', '{"waived_steps": [null, 7]}'):
        _write(tmp_path / "waivers.json", blob)
        assert sa._si_vacuity_disclosures(tmp_path) == {}
        assert sa._check_tapeout(tmp_path).passed is False
        assert _rc(tmp_path) == 1


# ===========================================================================
# What a waiver may NEVER do
# ===========================================================================
def _permissive_waiver(proj: Path) -> Path:
    """A properly formed, correctly attributed waiver accepting EVERY vacuity
    code the SI gate can publish. The strongest laundering attempt available."""
    codes = sorted({sic._vacuity(s)[0] for s in (
        {}, {"report_read": True},
        {"report_read": True, "spef_read": True},
        {"report_read": True, "spef_read": True, "spef_r_net_records": 7},
        {"report_read": True, "spef_read": True, "spef_net_records": 5},
        {"report_read": True, "spef_read": True, "spef_net_records": 5,
         "recount": {"setup": {"nets_checked": 0}}},
        {"report_read": True, "spef_read": True, "spef_net_records": 5,
         "recount": {"setup": {"nets_checked": 0}}, "coupling_caps": 3},
        {"report_read": True, "spef_read": True, "spef_net_records": 5,
         "recount": {"setup": {"nets_checked": 0}}, "coupling_pairs": 4},
        {"report_read": True, "spef_read": True, "spef_net_records": 5,
         "recount": {"setup": {"nets_checked": 2}}, "coupling_pairs": 4},
    )})
    return _waive(proj, **{sa.SI_DISCLOSURE_FIELD: codes})


def test_a_waiver_cannot_launder_a_genuine_si_failure(tmp_path):
    """A vacuity waiver accepts a check that proved NOTHING. It never accepts
    a check that proved something WRONG — and the refusal is recorded, so the
    attempt leaves a trace instead of vanishing."""
    _five_pillars(tmp_path)
    _si_report(tmp_path, "FAIL", examined=0, vacuity_code="")
    _permissive_waiver(tmp_path)

    r = sa._check_tapeout(tmp_path)
    assert r.passed is False
    assert r.summary["verdict_tier"] == "FAIL"
    assert _si(r)["state"] == sa.SI_VIOLATION
    assert _si(r)["waived"] is False
    assert "not a vacuity" in _si(r)["waiver_refused"]
    assert "TAPEOUT_SI_VIOLATION" in _rules(r)
    assert _rc(tmp_path) == 1


def test_a_waiver_cannot_cover_an_absent_report(tmp_path):
    """Absence is not vacuity. Vacuity is a gate that RAN and disclosed that it
    proved nothing; an absent report is a gate that did not run, and there is
    no disclosure to accept."""
    _five_pillars(tmp_path)
    _permissive_waiver(tmp_path)
    assert not (tmp_path / _SI_REPORT).exists()

    r = sa._check_tapeout(tmp_path)
    assert r.passed is False
    assert _si(r)["state"] == sa.SI_ABSENT
    assert _si(r)["waived"] is False
    assert _si(r)["waiver_refused"]
    assert "TAPEOUT_SI_ABSENT" in _rules(r)
    assert _rc(tmp_path) == 1


def test_a_waiver_cannot_cover_an_unparseable_report(tmp_path):
    """Same tier as absent, for the same reason."""
    _five_pillars(tmp_path)
    _permissive_waiver(tmp_path)
    for blob in ("{{{ not json", "[]", "true", "null", '"a string"'):
        _write(tmp_path / _SI_REPORT, blob)
        r = sa._check_tapeout(tmp_path)
        assert r.passed is False, f"{blob!r} was accepted"
        assert _si(r)["state"] == sa.SI_ABSENT
        assert _rc(tmp_path) == 1


def test_a_pass_with_no_denominator_is_not_creditable(tmp_path):
    """The pre-fix false-clean shape: `verdict: PASS` with nothing saying how
    many folds were proved. This consumer cannot tell such a report apart from
    one produced before the SI gate was fixed, so it is refused — and it is
    refused as UNDISCLOSED, which no vacuity waiver covers."""
    _five_pillars(tmp_path)
    _permissive_waiver(tmp_path)
    _si_report(tmp_path, "PASS", examined=99, denominator=False)

    r = sa._check_tapeout(tmp_path)
    assert r.passed is False
    assert _si(r)["state"] == sa.SI_UNDISCLOSED
    assert _si(r)["waived"] is False
    assert _rc(tmp_path) == 1


def test_a_pass_over_a_zero_or_non_integer_denominator_is_not_creditable(
        tmp_path):
    """A PASS whose denominator says it examined nothing is internally
    inconsistent (the gate emits VACUOUS_PASS for that state), so it is a
    forged or corrupt report, not a vacuity to accept."""
    _five_pillars(tmp_path)
    _permissive_waiver(tmp_path)
    for examined in (0, -1):
        _si_report(tmp_path, "PASS", examined=examined)
        assert sa._check_tapeout(tmp_path).passed is False
        assert _rc(tmp_path) == 1
    for bogus in ("365", True, None, 3.5, [1]):
        doc = json.loads((tmp_path / _SI_REPORT).read_text())
        doc["verdict"] = "PASS"
        doc["summary"]["denominator"]["examined"] = bogus
        _write(tmp_path / _SI_REPORT, json.dumps(doc))
        assert sa._check_tapeout(tmp_path).passed is False, f"{bogus!r}"
        assert _rc(tmp_path) == 1


def test_a_vacuous_verdict_that_names_no_vacuity_is_not_waivable(tmp_path):
    """An acceptance cannot name a vacuity the report refuses to identify."""
    _five_pillars(tmp_path)
    _permissive_waiver(tmp_path)
    for code in ("", "   ", None):
        _si_report(tmp_path, "VACUOUS_PASS", examined=0,
                   vacuity_code=code if code is not None else "")
        if code is None:
            doc = json.loads((tmp_path / _SI_REPORT).read_text())
            doc["summary"]["denominator"]["details"] = {}
            _write(tmp_path / _SI_REPORT, json.dumps(doc))
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_UNDISCLOSED, f"code {code!r}"
        assert r.passed is False
        assert _rc(tmp_path) == 1


def test_an_unrecognised_verdict_is_not_read_as_a_pass(tmp_path):
    _five_pillars(tmp_path)
    _permissive_waiver(tmp_path)
    for verdict in ("pass", "OK", "WAIVED", "", None):
        doc = {"verdict": verdict, "summary": {}, "findings": []}
        _write(tmp_path / _SI_REPORT, json.dumps(doc))
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_UNDISCLOSED, f"verdict {verdict!r}"
        assert _rc(tmp_path) == 1


def test_only_the_vacuous_state_is_waivable():
    """Pinned as a set so a future verdict tier cannot become waivable by
    accident — the way `rc 2` silently became a pass at step 27."""
    assert sa._SI_WAIVABLE_STATES == frozenset({sa.SI_VACUOUS})


# ===========================================================================
# The VACUOUS branch is defended against a self-contradicting report, exactly
# as the PASS branch is
# ===========================================================================
# WHY THIS SECTION EXISTS. The PASS branch refused `verdict: PASS` with
# `denominator.examined == 0` from the start — pinned above — and the VACUOUS
# branch refused nothing about its own body. That asymmetry ran the dangerous
# way round. A self-contradictory PASS that slips through gets BLOCKED at the
# next gate; a self-contradictory VACUOUS_PASS gets WAIVED, because VACUOUS is
# the one state this whole condition lets a waiver through. Measured on the
# unfixed tree, with a well-formed governed waiver in place:
#
#     real FAIL from the real emitter, `verdict` relabelled VACUOUS_PASS
#         -> rc 3  PASS_WITH_WAIVERS  (state VACUOUS, waived)
#     real VACUOUS run, `denominator.examined` forged to 7
#         -> rc 3  PASS_WITH_WAIVERS
#     real VACUOUS run with ERROR findings injected
#         -> rc 3  PASS_WITH_WAIVERS
#     real VACUOUS run, `summary.pass` true / `summary.vacuous` false
#         -> rc 3  PASS_WITH_WAIVERS
#
# One edited string laundered a genuine SI failure into a signed-off tapeout.
#: Sentinel for "delete this key" in `_si_contradictory`.
_DROP = object()


def _si_contradictory(proj: Path, over: dict) -> Path:
    """A VACUOUS_PASS report, then field(s) mutated so it disagrees with
    itself. `over` maps a dotted path to its new value (or `_DROP`).

    Everything not named stays the shape the emitter writes, so each case below
    differs from the ACCEPTED one in exactly one way."""
    _si_vacuous(proj)
    doc = json.loads((proj / _SI_REPORT).read_text())
    for path, value in over.items():
        parts = path.split(".")
        node = doc
        for key in parts[:-1]:
            node = node.setdefault(key, {})
        if value is _DROP:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    return _write(proj / _SI_REPORT, json.dumps(doc, indent=2))


def test_a_vacuous_verdict_whose_denominator_says_work_was_examined_blocks(
        tmp_path):
    """THE MIRROR of `test_a_pass_over_a_zero_...`. VACUOUS_PASS is the claim
    "the rule was never applied to anything"; the emitter reaches it ONLY when
    `examined == 0` (`_gate_denominator.Denominator.is_vacuous`). A report
    claiming vacuity while its own denominator says 7 folds were examined is
    forged or corrupt, not a disclosed skip."""
    _five_pillars(tmp_path)
    _waive(tmp_path)  # the waiver that ACCEPTS this exact code, well-formed
    for examined in (1, 7, 365, -1):
        _si_contradictory(tmp_path,
                          {"summary.denominator.examined": examined})
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_UNDISCLOSED, f"examined={examined}"
        assert _si(r)["waived"] is False
        assert r.summary["verdict_tier"] == "FAIL"
        assert _rc(tmp_path) == 1
    for bogus in ("0", True, False, None, 0.0, [0]):
        _si_contradictory(tmp_path, {"summary.denominator.examined": bogus})
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_UNDISCLOSED, f"examined={bogus!r}"
        assert _rc(tmp_path) == 1


def test_a_vacuous_verdict_carrying_error_findings_is_read_as_a_violation(
        tmp_path):
    """The emitter's OWN precedence: `if not no_errors: verdict = "FAIL"`
    outranks the vacuity tier. A body carrying an ERROR is a failure whatever
    the verdict field was edited to say — and it lands in VIOLATION, not merely
    UNDISCLOSED, so the refusal names what it actually is."""
    _five_pillars(tmp_path)
    _waive(tmp_path)
    _si_contradictory(tmp_path, {"findings": [
        {"severity": "ERROR", "rule": "MCF_FOLD_MISSING",
         "message": "the bounded SPEF never applied the fold on 12 nets"}]})

    r = sa._check_tapeout(tmp_path)
    assert _si(r)["state"] == sa.SI_VIOLATION
    assert _si(r)["waived"] is False
    assert _si(r)["vacuity_code"] == ""      # never offered to the waiver
    assert "not a vacuity" in _si(r)["waiver_refused"]
    assert "TAPEOUT_SI_VIOLATION" in _rules(r)
    assert _rc(tmp_path) == 1


def test_a_vacuous_verdict_whose_own_error_count_is_positive_is_a_violation(
        tmp_path):
    """The second, independent channel: the report's own `errors_count`. An
    attacker who strips `findings` still has to strip this too."""
    _five_pillars(tmp_path)
    _waive(tmp_path)
    for count in (1, 2, 99):
        _si_contradictory(tmp_path, {"summary.errors_count": count,
                                     "findings": []})
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_VIOLATION, f"errors_count={count}"
        assert _rc(tmp_path) == 1


def test_a_relabelled_fail_cannot_walk_into_the_waivable_branch(tmp_path):
    """THE ATTACK, end to end. Take the report a genuine SI FAILURE produces —
    a real vacuity code included, because `denominator()` computes one whenever
    `examined == 0` REGARDLESS of verdict — and edit the single word
    `verdict`. Pair it with a waiver naming that exact code.

    Before: rc 3, PASS_WITH_WAIVERS. That one-word edit was the exploit."""
    _five_pillars(tmp_path)
    _waive(tmp_path, **{sa.SI_DISCLOSURE_FIELD: ["SPEF_UNREADABLE"]})
    genuine_fail = {
        "program": "si_mcf_sta_check", "verdict": "FAIL",
        "summary": {
            "pass": False, "vacuous": True, "errors_count": 1,
            "denominator": {
                "unit": "victim-net MCF folds", "examined": 0, "considered": 0,
                "not_applicable_reason": (
                    "the coupling SPEF the report names could not be read, so "
                    "no fold was re-derived. Read this as NOT CHECKED."),
                "details": {"vacuity_code": "SPEF_UNREADABLE"}}},
        "findings": [{"severity": "ERROR", "rule": "NO_SPEF",
                      "message": "original coupling SPEF missing"}]}

    _write(tmp_path / _SI_REPORT, json.dumps(genuine_fail, indent=2))
    assert sa._classify_si(tmp_path)[0] == sa.SI_VIOLATION   # control
    assert _rc(tmp_path) == 1

    laundered = dict(genuine_fail, verdict="VACUOUS_PASS")
    _write(tmp_path / _SI_REPORT, json.dumps(laundered, indent=2))
    r = sa._check_tapeout(tmp_path)
    assert _si(r)["state"] == sa.SI_VIOLATION, "a relabelled FAIL was waived"
    assert _si(r)["waived"] is False
    assert r.summary["verdict_tier"] == "FAIL"
    assert _rc(tmp_path) == 1


def test_the_body_outranks_the_label_for_every_verdict_string(tmp_path):
    """Branch-ORDER independence. The refusal must not rest on FAIL happening
    to be tested before VACUOUS_PASS: a body carrying a defect is a VIOLATION
    whichever label it wears, so reordering the branches cannot make a real SI
    failure waivable."""
    _five_pillars(tmp_path)
    _permissive_waiver(tmp_path)
    for verdict in ("FAIL", "VACUOUS_PASS", "PASS", "SKIPPED", "OK", ""):
        _si_report(tmp_path, verdict, examined=0,
                   vacuity_code="SPEF_NO_COUPLING_PAIRS")
        doc = json.loads((tmp_path / _SI_REPORT).read_text())
        doc["findings"] = [{"severity": "ERROR", "rule": "R", "message": "m"}]
        _write(tmp_path / _SI_REPORT, json.dumps(doc))
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_VIOLATION, f"verdict {verdict!r}"
        assert _si(r)["waived"] is False
        assert _rc(tmp_path) == 1


def test_summary_flags_that_contradict_the_vacuous_verdict_are_refused(
        tmp_path):
    """`summary.pass` is `verdict == "PASS"` and `summary.vacuous` is
    `denom.is_vacuous` — both computed in the same breath as the verdict, so
    neither can legitimately disagree with it."""
    _five_pillars(tmp_path)
    _waive(tmp_path)
    for field, value in (("summary.pass", True), ("summary.vacuous", False)):
        _si_contradictory(tmp_path, {field: value})
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_UNDISCLOSED, f"{field}={value}"
        assert _rc(tmp_path) == 1


def test_a_vacuity_with_no_written_reason_did_not_come_from_the_gate(tmp_path):
    """`Denominator.__post_init__` RAISES on a zero denominator with no
    `not_applicable_reason`, so a report in that shape cannot have been emitted
    by the gate — and the reason is the only thing a human reviewing the waiver
    would read."""
    _five_pillars(tmp_path)
    _waive(tmp_path)
    for value in ("", "   ", None, 7, _DROP):
        _si_contradictory(
            tmp_path,
            {"summary.denominator.not_applicable_reason": value})
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_UNDISCLOSED, f"reason={value!r}"
        assert _rc(tmp_path) == 1
    # ...and the emitter's own type agrees, so this is not a rule invented here
    with pytest.raises(ValueError):
        _gd.Denominator(unit="u", examined=0, not_applicable_reason="")


def test_a_vacuous_verdict_with_no_denominator_at_all_is_refused(tmp_path):
    """The mirror of "a PASS with no denominator is not creditable": a vacuity
    that never states its own zero is indistinguishable from a report that
    disclosed nothing, and a code smuggled in beside the denominator is not the
    code the gate publishes.

    BLOCKING here already held — the code lookup needed the denominator to
    reach the code. What did NOT hold is the DIAGNOSIS: the refusal told the
    reader "you did not name WHICH vacuity", sending them to add a
    `vacuity_code` to a report that has no denominator to put it in. A refusal
    that names the wrong missing thing is how a real fix gets postponed."""
    _five_pillars(tmp_path)
    _waive(tmp_path)
    _write(tmp_path / _SI_REPORT, json.dumps({
        "program": "si_mcf_sta_check", "verdict": "VACUOUS_PASS",
        # Differs from an ACCEPTED report in exactly one way: no denominator.
        # Everything else the emitter writes is present, so the refusal this
        # test reads is the denominator one and not an earlier complaint about
        # some other field the fixture forgot.
        "summary": {"pass": False, "vacuous": True,
                    "errors_count": 0, "findings_count": 0,
                    "details": {"vacuity_code": "SPEF_NO_COUPLING_PAIRS"}},
        "findings": []}, indent=2))
    r = sa._check_tapeout(tmp_path)
    assert _si(r)["state"] == sa.SI_UNDISCLOSED
    why = _si(r)["why"]
    assert "denominator" in why
    assert "vacuity_code" not in why, (
        "the refusal blames the missing code, not the missing denominator")
    assert _rc(tmp_path) == 1


def test_both_verdict_branches_refuse_the_same_contradiction(tmp_path):
    """The asymmetry itself, pinned. Whatever a future edit does to either
    branch, the two must stay mirrors: a verdict whose denominator contradicts
    it is refused on BOTH, and neither refusal is waivable."""
    _five_pillars(tmp_path)
    _permissive_waiver(tmp_path)
    for verdict, examined in (("PASS", 0), ("VACUOUS_PASS", 42)):
        _si_report(tmp_path, verdict, examined=examined,
                   vacuity_code="SPEF_NO_COUPLING_PAIRS")
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_UNDISCLOSED, verdict
        assert _si(r)["waived"] is False, verdict
        assert _rc(tmp_path) == 1


def test_reshaping_the_body_out_of_view_is_not_read_as_no_defect(tmp_path):
    """`_si_defect_evidence` reads only POSITIVE evidence, which leaves the
    move of DISABLING the evidence channel: turn `findings` into an object, or
    its entries into strings, or `errors_count` into `"1"`, and a scan looking
    for ERROR dicts finds none. "The defect channel is unreadable" must not
    read as "there is no defect"."""
    _five_pillars(tmp_path)
    _waive(tmp_path)
    for label, over in (
            ("findings is an object",
             {"findings": {"0": {"severity": "ERROR", "rule": "R"}}}),
            ("findings entries are strings",
             {"findings": ["ERROR NO_SPEF: coupling SPEF missing"]}),
            ("findings entries are numbers", {"findings": [1, 2]}),
            ("errors_count is a string",
             {"summary.errors_count": "1", "findings": []}),
            ("errors_count is a float",
             {"summary.errors_count": 1.0, "findings": []}),
            ("errors_count is a bool",
             {"summary.errors_count": True, "findings": []}),
    ):
        _si_contradictory(tmp_path, over)
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] != sa.SI_VACUOUS, label
        assert _si(r)["waived"] is False, label
        assert _rc(tmp_path) == 1, label


def test_an_error_finding_is_seen_whatever_case_it_is_written_in(tmp_path):
    """Severity is compared case-folded: `"error"` must not slip past a scan
    written for `"ERROR"`."""
    _five_pillars(tmp_path)
    _waive(tmp_path)
    for sev in ("ERROR", "error", "Error", " error "):
        _si_contradictory(tmp_path, {"findings": [
            {"severity": sev, "rule": "NO_SPEF", "message": "m"}]})
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_VIOLATION, f"severity {sev!r}"
        assert _rc(tmp_path) == 1


def test_the_consistency_checks_do_not_fire_on_a_report_the_gate_emitted(
        tmp_path):
    """THE FALSE-ALARM CONTROL for this whole section, and the reason each
    clause above re-derives an emitter invariant instead of inventing a rule.
    Reports built the way `si_mcf_sta_check.build_report` builds them — across
    every vacuity branch it has — must classify exactly as before: PROVED signs
    off at rc 0, and a consistent vacuity is still waivable at rc 3."""
    codes = sorted({sic._vacuity(s)[0] for s in (
        {"report_read": True, "spef_read": True, "spef_net_records": 5,
         "recount": {"setup": {"nets_checked": 0}}},
        {"report_read": True, "spef_read": True, "spef_net_records": 5,
         "recount": {"setup": {"nets_checked": 0}}, "coupling_caps": 3},
        {"report_read": True, "spef_read": True, "spef_net_records": 5,
         "recount": {"setup": {"nets_checked": 0}}, "coupling_pairs": 4},
        {"report_read": True, "spef_read": True, "spef_net_records": 5,
         "recount": {"setup": {"nets_checked": 2}}, "coupling_pairs": 4},
    )})
    assert codes, "no vacuity codes enumerated — control is vacuous itself"
    _five_pillars(tmp_path)
    for code in codes:
        _si_vacuous(tmp_path, code=code)
        assert sa._si_defect_evidence(
            json.loads((tmp_path / _SI_REPORT).read_text()),
            json.loads((tmp_path / _SI_REPORT).read_text())["summary"]) == ""
        _waive(tmp_path, **{sa.SI_DISCLOSURE_FIELD: [code]})
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_VACUOUS, code
        assert _si(r)["waived"] is True, code
        assert r.summary["verdict_tier"] == "PASS_WITH_WAIVERS", code
        assert _rc(tmp_path) == sa.WAIVER_EXIT_CODE, code

    # ...and the same for a legitimate body that merely differs in the ways an
    # older or noisier run legitimately differs.
    #
    # TWO CONTROLS THAT USED TO SIT HERE HAVE BEEN REMOVED, because they were
    # not observed shapes and they PINNED A LOOPHOLE GREEN:
    #
    #   "no errors_count key" asserted that a vacuity with
    #   `summary.errors_count` deleted is still waivable at rc 3, on the
    #   grounds that an older run might lack it. No such run exists: all six
    #   commits that have ever touched `si_mcf_sta_check.py` write
    #   `errors_count`, `findings_count` and `findings` unconditionally in one
    #   dict literal, and every checker-output report in the tree carries all
    #   three. Tolerating the absence bought zero false-alarm protection and
    #   cost the cheapest laundering route there was — see
    #   `test_a_creditable_verdict_must_expose_its_defect_channel`.
    #
    #   "WARNING and INFO findings" replaced `findings` with a two-entry list
    #   while leaving `summary.findings_count` at 0 — itself a shape the
    #   emitter cannot write. The same control, built the way the emitter
    #   builds it, is below and still passes.
    for label, over in (
            ("no pass/vacuous flags", {"summary.pass": _DROP,
                                       "summary.vacuous": _DROP}),
            ("WARNING and INFO findings, counts consistent", {
                "findings": [
                    {"severity": "WARNING", "category": "W", "message": "m"},
                    {"severity": "INFO", "category": "I", "message": "m"}],
                "summary.findings_count": 2,
                "summary.errors_count": 0}),
            ("considered >> examined",
             {"summary.denominator.considered": 732}),
    ):
        _si_contradictory(tmp_path, over)
        _waive(tmp_path)
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_VACUOUS, label
        assert _si(r)["waived"] is True, label
        assert _rc(tmp_path) == sa.WAIVER_EXIT_CODE, label

    _si_proved(tmp_path)
    r = sa._check_tapeout(tmp_path)
    assert _si(r)["state"] == sa.SI_PROVED
    assert r.summary["verdict_tier"] == "PASS"
    assert _rc(tmp_path) == 0


def test_the_documented_waiver_example_satisfies_its_sibling_gates(tmp_path):
    """The entry shape the block comment tells a human to write must be one
    the OTHER waiver gates accept. Measured on the four-field entry the comment
    used to show: `waiver_growth_check` rc 1 (`UNJUSTIFIED_WAIVER_GROWTH` — no
    `growth_rationale`) and `waiver_staleness_check` rc 2 (no parseable
    `approved_at`, so the entry can never AGE). An example this gate accepts
    and its siblings reject sends a reviewer to write a waiver that cannot be
    aged or closed — a permanent one.

    vibe-ic#922 added `growth_rationale_covers` to that sibling contract: a
    rationale must record the waiver population it was written against, or it
    authorises unlimited growth forever. The documented block comment carries
    the field, so this fixture does too — that is the whole point of this
    test, and it fails here first if the comment and the gates drift."""
    import datetime
    import subprocess

    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    _write(tmp_path / "waivers.json", json.dumps({
        "growth_rationale": ("One SI vacuity disclosed for this release; the "
                             "extraction rerun is tracked."),
        "growth_rationale_covers": 1,
        "waived_steps": [{
            "id": sa._TAPEOUT_STEP_ID,
            "reason": _GOOD_REASON,
            "approver": _GOOD_APPROVER,
            "approved_at": datetime.datetime.now().isoformat(
                timespec="seconds"),
            "review_required": True,
            "ticket": "TRACKER-1234",
            sa.SI_DISCLOSURE_FIELD: ["SPEF_NO_COUPLING_PAIRS"]}]}, indent=2))

    assert _rc(tmp_path) == sa.WAIVER_EXIT_CODE       # this gate accepts it
    for gate in ("waivers_schema_check", "waiver_legitimacy_check",
                 "waiver_growth_check", "waiver_staleness_check"):
        prog = _PROGRAMS / f"{gate}.py"
        if not prog.is_file():                        # pragma: no cover
            pytest.skip(f"{gate} not present in this tree")
        r = subprocess.run([sys.executable, str(prog), str(tmp_path)],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"{gate} rc={r.returncode}\n{r.stdout}"


# ===========================================================================
# The runner may not mint its own SI waiver
# ===========================================================================
def test_the_runners_own_auto_waiver_entry_cannot_accept_an_si_vacuity(
        tmp_path):
    """`_emit_tapeout_waiver_entry` writes a `waived_steps` entry keyed on the
    SAME step id when a DRC/LVS slot is waived. It must never be readable as an
    SI acceptance — otherwise the runner mints the waiver the ruling requires a
    human to sign. It carries no `si_vacuity_accepted` field, and this pins
    that."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    r = sa._check_tapeout(tmp_path)
    sa._emit_tapeout_waiver_entry(tmp_path, r)

    doc = json.loads((tmp_path / "waivers.json").read_text())
    minted = [e for e in doc["waived_steps"]
              if str(e.get("id")) == str(sa._TAPEOUT_STEP_ID)]
    assert minted, "the auto-emitter did not write its entry — test is stale"
    assert all(sa.SI_DISCLOSURE_FIELD not in e for e in minted)
    assert sa._si_vacuity_disclosures(tmp_path) == {}
    assert sa._check_tapeout(tmp_path).passed is False
    assert _rc(tmp_path) == 1


def test_a_second_run_does_not_inherit_a_pass_from_the_first(tmp_path):
    """The blocked run writes nothing that would unblock the next one."""
    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    assert _rc(tmp_path) == 1
    assert _rc(tmp_path) == 1
    assert _rc(tmp_path) == 1


# ===========================================================================
# Step 27 is untouched: development is not blocked
# ===========================================================================
def test_the_phase3_si_step_still_credits_a_vacuous_verdict(tmp_path):
    """The disclosed-skip tier keeps its meaning where it belongs. rc 2 is the
    SI gate's own contract and this change does not touch it; only the tape-out
    consumer reads it differently."""
    assert sic.RC_VACUOUS == 2
    proj = tmp_path
    (proj / "reports" / "phase3").mkdir(parents=True)
    # No emitter report at all -> the SI gate's own vacuous/failing contract is
    # unchanged by this file's work; what changed is only who may credit it.
    assert sa._classify_si(proj)[0] == sa.SI_ABSENT


# ===========================================================================
# A CREDITABLE VERDICT MUST EXPOSE THE CHANNEL IT WAS DERIVED FROM
# ===========================================================================
# WHY THIS SECTION EXISTS. The body-outranks-the-label check reads only
# POSITIVE evidence and the malformed check tolerates ABSENCE, so between them
# a report could have its defect channel DELETED and then be read as "no
# defect found". Measured on the tree before this section existed, with all
# five evidence pillars and a well-formed governed waiver in place:
#
#   real emitter FAIL (1 ERROR finding, errors_count 1), `verdict` relabelled
#   VACUOUS_PASS, then `del findings` and `del summary.errors_count`
#       -> rc 3  PASS_WITH_WAIVERS  (state VACUOUS, waived)
#
#   the SAME report relabelled PASS instead, same two deletions, NO WAIVER
#   ANYWHERE
#       -> rc 0  PASS  (state PROVED)
#
# The second is the worse of the two and was named by nobody: a genuine SI
# defect over 365 examined folds signed off clean with no waiver at all.
#
# "Absence is not evidence of a defect" is right. "Absence is not evidence of
# a CLEAN RUN" is the half that was missing.

def _si_emitter_shaped(proj: Path, verdict: str, examined: int,
                       findings: list) -> Path:
    """A report with the defect channel exactly as `build_report` writes it."""
    return _si_report(proj, verdict, examined=examined,
                      vacuity_code=("SPEF_NO_COUPLING_PAIRS"
                                    if examined == 0 else ""),
                      findings=findings)


_AN_ERROR = {"severity": "ERROR", "category": "NO_SPEF",
             "message": "original coupling SPEF missing"}
_A_WARNING = {"severity": "WARNING", "category": "W", "message": "m"}


@pytest.mark.parametrize("label,over", [
    ("findings deleted", {"findings": _DROP}),
    ("errors_count deleted", {"summary.errors_count": _DROP}),
    ("findings_count deleted", {"summary.findings_count": _DROP}),
    ("all three deleted", {"findings": _DROP,
                           "summary.errors_count": _DROP,
                           "summary.findings_count": _DROP}),
    ("findings nulled", {"findings": None, "summary.errors_count": None}),
    ("findings_count contradicts findings",
     {"summary.findings_count": 1}),
    # The ONE shape that reaches the errors_count cross-check: a count below
    # the ERROR findings in the body. Any count ABOVE is refused earlier by
    # the defect read, so this is the whole of that clause's reachable input.
    ("errors_count below what sum() can produce",
     {"summary.errors_count": -1}),
])
def test_a_creditable_verdict_must_expose_its_defect_channel(
        tmp_path, label, over):
    """A vacuity whose defect channel is absent or self-contradicting is not
    waivable. The emitter writes `findings`, `errors_count` and
    `findings_count` unconditionally, in one dict literal, from one list."""
    _five_pillars(tmp_path)
    _waive(tmp_path)          # accepts this exact vacuity code, well-formed
    _si_contradictory(tmp_path, over)
    r = sa._check_tapeout(tmp_path)
    assert _si(r)["state"] != sa.SI_VACUOUS, label
    assert _si(r)["waived"] is False, label
    assert r.summary["verdict_tier"] == "FAIL", label
    assert _rc(tmp_path) == 1, label


@pytest.mark.parametrize("label,over", [
    ("findings deleted", {"findings": _DROP}),
    ("errors_count deleted", {"summary.errors_count": _DROP}),
    ("findings_count contradicts findings", {"summary.findings_count": 3}),
])
def test_a_proved_verdict_must_expose_its_defect_channel_too(
        tmp_path, label, over):
    """The route that needs NO waiver at all, and so is the more dangerous of
    the two: relabel a genuine FAIL `PASS` and delete the defect channel."""
    _five_pillars(tmp_path)
    _si_proved(tmp_path)
    doc = json.loads((tmp_path / _SI_REPORT).read_text())
    for path, value in over.items():
        parts = path.split(".")
        node = doc
        for key in parts[:-1]:
            node = node.setdefault(key, {})
        if value is _DROP:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    _write(tmp_path / _SI_REPORT, json.dumps(doc, indent=2))

    r = sa._check_tapeout(tmp_path)
    assert _si(r)["state"] == sa.SI_UNDISCLOSED, label
    assert r.summary["verdict_tier"] == "FAIL", label
    assert _rc(tmp_path) == 1, label


def test_a_real_defect_survives_relabelling_plus_channel_deletion(tmp_path):
    """The end-to-end shape, on both creditable verdicts.

    A report carrying a genuine ERROR finding is laundered by relabelling the
    verdict and deleting the two keys the defect read looks at. Neither
    destination is creditable.
    """
    _five_pillars(tmp_path)
    for verdict, examined in (("VACUOUS_PASS", 0), ("PASS", 365)):
        _si_emitter_shaped(tmp_path, "FAIL", examined, [_AN_ERROR])
        _waive(tmp_path)
        assert _rc(tmp_path) == 1, verdict          # honest FAIL blocks

        doc = json.loads((tmp_path / _SI_REPORT).read_text())
        doc["verdict"] = verdict
        del doc["findings"]
        del doc["summary"]["errors_count"]
        _write(tmp_path / _SI_REPORT, json.dumps(doc, indent=2))

        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_UNDISCLOSED, verdict
        assert _si(r)["waived"] is False, verdict
        assert _rc(tmp_path) == 1, verdict


def test_the_channel_check_does_not_fire_on_a_body_the_emitter_wrote(tmp_path):
    """THE FALSE-ALARM CONTROL, built the way the emitter builds it.

    A vacuity and a proved run may both legitimately carry WARNING and INFO
    findings; what they cannot do is disagree with their own counts. Both
    directions are asserted here so the check is not a blanket refusal of any
    report with a findings list.
    """
    _five_pillars(tmp_path)
    for findings in ([], [_A_WARNING], [_A_WARNING, {"severity": "INFO",
                                                     "category": "I",
                                                     "message": "m"}]):
        _si_emitter_shaped(tmp_path, "VACUOUS_PASS", 0, findings)
        _waive(tmp_path)
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_VACUOUS, findings
        assert _si(r)["waived"] is True, findings
        assert _rc(tmp_path) == sa.WAIVER_EXIT_CODE, findings

        _si_emitter_shaped(tmp_path, "PASS", 365, findings)
        r = sa._check_tapeout(tmp_path)
        assert _si(r)["state"] == sa.SI_PROVED, findings
        assert _rc(tmp_path) == 0, findings


@needs_corpus
def test_the_channel_check_is_silent_on_every_real_report_in_the_tree(
        tmp_path):
    """The strongest false-alarm evidence available: the emitter's own output.

    Not a fixture — every checker-output SI report in the PUBLISHED cells, in
    every verdict state. A clause that fires on one of these would be blocking
    correct work.

    The old guard asked whether `benchmark-data/` was a directory. It still is
    in this repo — it holds the design INPUT — so the guard passed and the
    control then failed on an empty `rglob`, reporting a defect where the only
    fact was that the result cells had moved to vibeic/benchmark-data.
    """
    corpus = corpus_root()
    reports = sorted(corpus.rglob("reports/phase3/si_mcf_sta_check.json"))
    assert reports, "corpus present but empty — this control measures nothing"
    for path in reports:
        doc = json.loads(path.read_text())
        assert sa._si_defect_channel_unauditable(
            doc, doc.get("summary", {})) == "", path


def test_the_defect_prose_names_the_finding_the_emitter_actually_wrote(
        tmp_path):
    """`si_mcf_sta_check.Finding` is severity / category / message.

    Citing only `rule`/`code` degraded the refusal prose to a literal `?` on
    every report the real gate produces, with the name sitting in the file.
    """
    _five_pillars(tmp_path)
    _si_emitter_shaped(tmp_path, "VACUOUS_PASS", 0, [_AN_ERROR])
    _waive(tmp_path)
    r = sa._check_tapeout(tmp_path)
    why = _si(r)["why"]
    assert "NO_SPEF" in why, why
    assert "first: ?" not in why, why


@pytest.mark.parametrize("key,value", [
    ("summary.pass", 1),         # JSON int, not the bool singleton
    ("summary.vacuous", 0),
])
def test_summary_flags_contradict_in_their_integer_spelling_too(
        tmp_path, key, value):
    """`x is True` misses `1` and `x is False` misses `0`.

    The PASS branch's `examined` clause was already written to avoid exactly
    this type miss; its mirror was not.
    """
    _five_pillars(tmp_path)
    _waive(tmp_path)
    _si_contradictory(tmp_path, {key: value})
    r = sa._check_tapeout(tmp_path)
    assert _si(r)["state"] == sa.SI_UNDISCLOSED, (key, value)
    assert _rc(tmp_path) == 1


@pytest.mark.parametrize("key,value", [
    ("summary.pass", 0),         # agrees with VACUOUS_PASS
    ("summary.vacuous", 1),
])
def test_the_integer_spelling_of_an_AGREEING_flag_is_not_refused(
        tmp_path, key, value):
    """The false-alarm control: an integer flag that AGREES must stay waivable."""
    _five_pillars(tmp_path)
    _waive(tmp_path)
    _si_contradictory(tmp_path, {key: value})
    r = sa._check_tapeout(tmp_path)
    assert _si(r)["state"] == sa.SI_VACUOUS, (key, value)
    assert _rc(tmp_path) == sa.WAIVER_EXIT_CODE


def test_the_refusal_NAMES_the_keys_that_were_removed(tmp_path):
    """Diagnosability, and the discriminator for the absent-keys clause.

    Deleting a key is also caught by the type clauses below it (`None` is not
    a list, `None` is not an int), so without this the absent-keys branch
    could be removed and every rc-based test would still pass while the
    reviewer got "`findings` is NoneType, not a list" instead of the name of
    the field somebody deleted.
    """
    _five_pillars(tmp_path)
    _waive(tmp_path)
    _si_contradictory(tmp_path, {"findings": _DROP,
                                 "summary.errors_count": _DROP,
                                 "summary.findings_count": _DROP})
    why = _si(sa._check_tapeout(tmp_path))["why"]
    assert "does not carry" in why, why
    for key in ("`findings`", "`summary.errors_count`",
                "`summary.findings_count`"):
        assert key in why, (key, why)
    assert _rc(tmp_path) == 1


@pytest.mark.parametrize("entry,label", [
    ({"level": "ERROR", "category": "NO_SPEF", "message": "m"},
     "severity key renamed to `level`"),
    ({"category": "NO_SPEF", "message": "m"}, "severity key removed"),
    ({"severity": 1, "category": "NO_SPEF", "message": "m"},
     "severity is not a string"),
    ("just a string", "entry is not an object"),
])
def test_a_findings_entry_without_a_severity_is_not_a_finding(
        tmp_path, entry, label):
    """Blinding the severity read while keeping the counts agreeing.

    `findings` is `[asdict(f) for f in findings]` over a dataclass whose
    fields are severity / category / message, so every entry has a string
    `severity`. Renaming the key to `level` left the ERROR prose legible in
    the file and still reached a waived rc 3 once the counts were made to
    agree.
    """
    _five_pillars(tmp_path)
    _waive(tmp_path)
    _si_contradictory(tmp_path, {"findings": [entry],
                                 "summary.findings_count": 1,
                                 "summary.errors_count": 0})
    r = sa._check_tapeout(tmp_path)
    assert _si(r)["state"] == sa.SI_UNDISCLOSED, label
    assert _si(r)["waived"] is False, label
    assert _rc(tmp_path) == 1, label


def test_a_findings_entry_the_emitter_wrote_is_not_refused(tmp_path):
    """The false-alarm control: the exact three-key shape `asdict` produces,
    at every severity the gate emits."""
    _five_pillars(tmp_path)
    for sev in ("ERROR", "WARNING", "INFO"):
        entry = {"severity": sev, "category": "C", "message": "m"}
        _si_emitter_shaped(tmp_path, "VACUOUS_PASS", 0, [entry])
        _waive(tmp_path)
        r = sa._check_tapeout(tmp_path)
        if sev == "ERROR":
            # A real ERROR is a VIOLATION — read, not refused as unauditable.
            assert _si(r)["state"] == sa.SI_VIOLATION, sev
            assert "NO_SPEF" not in _si(r)["why"] or True
        else:
            assert _si(r)["state"] == sa.SI_VACUOUS, sev
            assert _rc(tmp_path) == sa.WAIVER_EXIT_CODE, sev


# ===========================================================================
# A REJECTED ARTEFACT IS NOT A VACUITY AND PUBLISHES NO CODE TO WAIVE
# ===========================================================================
# WHY THIS SECTION EXISTS.
#
# ``examined == 0`` has TWO causes and they are not the same event. The gate
# ran and reached nothing (a vacuity — waivable here, by name). Or the gate
# REJECTED the artefact it was handed and therefore never got as far as a fold
# (a decided FAILURE — never waivable). Three ERROR categories land in the
# second: ``SPEF_NO_NET_RECORDS``, ``COUPLING_LOST_SINCE_EMIT`` and
# ``FOLD_WITHOUT_SOURCE``, each reachable from the shipped fixture and each
# exercised below through the real CLI.
#
# ``_rejected_reason`` already separates the two in PROSE. `vacuity_code` is
# the MACHINE half of the same disclosure, and it has to make the same split:
# a code published on a rejected run is a name an operator can copy into
# ``si_vacuity_accepted`` — an acceptance recorded against a genuine SI defect,
# in a field whose entire contract is "this check proved nothing". That is the
# false certificate this feature exists to close, arriving through the
# disclosure channel meant to close it.
#
# Both properties are pinned: the producer publishes nothing, AND the consumer
# refuses even when the waiver names every code the gate can emit. Either alone
# would leave the guarantee resting on the other's continued good behaviour.
#
# EVERY PATH HERE STAYS INSIDE THE REPOSITORY. The projects are copies of
# ``programs/tests/fixtures/si_mcf_zero_coupling/`` under pytest's `tmp_path`,
# with the emitter report rewritten to absolute paths INSIDE that copy. No
# assertion depends on a file this checkout does not carry, so the branch a
# reviewer measures is the branch these tests measure.

_SI_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "si_mcf_zero_coupling"
_SI_GATE = _PROGRAMS / "si_mcf_sta_check.py"


def _materialise_si_project(tmp_path: Path, name: str,
                            case: str = "grounded_only") -> Path:
    """A runnable copy of the shipped fixture, with the five tapeout pillars.

    The emitter report's relative paths are rewritten to absolute paths inside
    the COPY — the shape the real emitter writes — so the gate is driven the
    way a real run drives it and the tracked bytes are never touched."""
    import shutil
    dst = tmp_path / name
    shutil.copytree(_SI_FIXTURE / case, dst)
    rp = dst / "reports" / "phase3" / "si_mcf_sta.json"
    doc = json.loads(rp.read_text())
    doc["spef"] = str(dst / doc["spef"])
    for corner in doc["corners"].values():
        corner["bounded_spef"] = str(dst / corner["bounded_spef"])
    rp.write_text(json.dumps(doc, indent=2))
    _five_pillars(dst)
    return dst


def _run_si_gate(project: Path) -> tuple:
    """Run the shipped SI gate with NO ``--json``, so it writes its report to
    its own default path — which IS the slot the tapeout gate reads. Nothing
    between the producer and the consumer is hand-written."""
    import subprocess
    r = subprocess.run([sys.executable, str(_SI_GATE), str(project)],
                       capture_output=True, text=True, timeout=60)
    report = project / _SI_REPORT
    assert report.is_file(), (
        f"the gate wrote no report to {_SI_REPORT}\n{r.stdout}\n{r.stderr}")
    return r.returncode, json.loads(report.read_text())


def _rejected_projects(tmp_path: Path) -> list:
    """One project per REJECTED-with-a-zero-denominator category.

    Each perturbation is the one the sibling transition test uses to reach that
    category, applied to a private copy."""
    out = []

    # (1) the named SPEF resolves to no net under any reading.
    p = _materialise_si_project(tmp_path, "no_net_records")
    spef = p / "design.spef"
    spef.write_text(spef.read_text().split("*D_NET", 1)[0])
    out.append(("SPEF_NO_NET_RECORDS", p))

    # (2) the emitter says it read coupling out of this path; the gate
    #     re-parses the same path with the same parser and finds none.
    p = _materialise_si_project(tmp_path, "coupling_lost")
    rp = p / "reports" / "phase3" / "si_mcf_sta.json"
    doc = json.loads(rp.read_text())
    doc["coupling_pairs"] = 1558
    rp.write_text(json.dumps(doc, indent=2))
    out.append(("COUPLING_LOST_SINCE_EMIT", p))

    # (3) nothing to fold, yet the bounded SPEF carries MORE grounded charge
    #     than the original — the two files are not a matched pair.
    p = _materialise_si_project(tmp_path, "fold_without_source")
    bounded = p / "design.mcf_setup.spef"
    bounded.write_text(bounded.read_text().replace("1 ua:Z 0.1", "1 ua:Z 0.9"))
    out.append(("FOLD_WITHOUT_SOURCE", p))

    return out


def _waive_every_vacuity(project: Path) -> Path:
    """A governed, well-formed waiver accepting EVERY code the gate can name.

    The strongest form of "no acceptance can consume this": not merely that the
    operator guessed the wrong code, but that no code exists which would have
    worked."""
    return _write(project / "waivers.json", json.dumps({
        "waived_steps": [{
            "id": sa._TAPEOUT_STEP_ID,
            "reason": _GOOD_REASON,
            "approver": _GOOD_APPROVER,
            sa.SI_DISCLOSURE_FIELD: sorted(
                {code for _, code in _VACUITY_BRANCHES}),
        }]}, indent=2))


def test_a_rejected_artefact_reaches_a_zero_denominator_at_all(tmp_path):
    """THE PREMISE, measured before anything is built on it.

    `examined == 0` co-occurring with a substantive defect is not hypothetical:
    it is the documented behaviour of three categories, and all three are
    reachable from the shipped fixture. If this ever stops holding, the guard
    below is protecting a state that cannot happen and should be removed rather
    than maintained — so the premise is asserted, not assumed."""
    cases = _rejected_projects(tmp_path)
    assert len(cases) == 3, "the premise must be measured on every category"
    for category, project in cases:
        rc, doc = _run_si_gate(project)
        den = doc["summary"]["denominator"]
        errors = [f["category"] for f in doc["findings"]
                  if f["severity"] == "ERROR"]
        assert den["examined"] == 0, (category, den)
        assert category in errors, (category, errors)
        assert doc["verdict"] == "FAIL", (category, doc["verdict"])
        assert rc == sic.RC_FAIL, (category, rc)


def test_a_rejected_artefact_publishes_no_vacuity_code(tmp_path):
    """THE GUARD. `vacuity_code` is the token an acceptance must quote, so a
    state that is not a vacuity must publish none — there is then nothing for
    an operator to copy into `si_vacuity_accepted`."""
    for category, project in _rejected_projects(tmp_path):
        _, doc = _run_si_gate(project)
        details = doc["summary"]["denominator"]["details"]
        assert details["vacuity_code"] == "", (
            f"{category}: the gate REJECTED this artefact and still named it "
            f"as vacuity {details['vacuity_code']!r} — a code an operator can "
            f"record in {sa.SI_DISCLOSURE_FIELD} against a genuine SI defect")


def test_a_rejected_zero_reports_the_rejection_not_the_vacuity(tmp_path):
    """THE #506 REGRESSION, on landed work.

    One answer per artefact: a zero the gate reached by REJECTING its input
    owes the rejection's reason, never the skip's "Read this as NOT CHECKED".
    Asserted here because the change this file is part of rewrote the very
    branch that decides it, and reverting to the pre-#506 single-reason form
    passes every other assertion in this section."""
    for category, project in _rejected_projects(tmp_path):
        _, doc = _run_si_gate(project)
        reason = doc["summary"]["denominator"]["not_applicable_reason"]
        assert reason.strip(), f"{category}: a zero must still say why"
        assert "REJECTED" in reason, (category, reason)
        assert category in reason, (category, reason)
        assert not reason.rstrip().endswith("Read this as NOT CHECKED."), (
            f"{category}: a DECIDED FAILURE is carrying the skip tier's "
            f"disclaimer — the #506 contradiction, restored")


def test_no_si_vacuity_acceptance_can_consume_a_rejected_artefact(tmp_path):
    """THE CONSUMER HALF. Producer and consumer are pinned separately: a guard
    that holds only because the other side happens to be careful is one edit
    from being the only thing left.

    The waiver here is fully governed and names EVERY code the gate can emit,
    so the refusal cannot be an operator naming the wrong one."""
    for category, project in _rejected_projects(tmp_path):
        _run_si_gate(project)
        _waive_every_vacuity(project)

        r = sa._check_tapeout(project)
        assert _si(r)["state"] == sa.SI_VIOLATION, (category, _si(r))
        assert _si(r)["waived"] is False, category
        assert r.passed is False, category
        assert r.summary["verdict_tier"] == "FAIL", category
        assert sa.main([str(project), "--mode", "tapeout"]) == 1, category
        # ...and not merely blocked: never routed into the waivable tier at
        # all, whatever the acceptance list says.
        assert sa.SI_VIOLATION not in sa._SI_WAIVABLE_STATES


def test_the_same_plumbing_still_waives_a_genuine_vacuity(tmp_path):
    """THE TWO-SIDED CONTROL, and it is what makes the three tests above mean
    anything. Identical fixture, identical driver, identical waiver — only the
    perturbation is absent. The unperturbed grounded-only project is a REAL
    vacuity, so it publishes its code and the same acceptance carries it."""
    project = _materialise_si_project(tmp_path, "genuine_vacuity")
    rc, doc = _run_si_gate(project)
    den = doc["summary"]["denominator"]
    assert (rc, doc["verdict"]) == (sic.RC_VACUOUS, "VACUOUS_PASS")
    assert den["examined"] == 0
    assert den["details"]["vacuity_code"] == "SPEF_NO_COUPLING_PAIRS"
    assert den["not_applicable_reason"].rstrip().endswith(
        "Read this as NOT CHECKED.")

    # Unwaived it blocks...
    assert sa._classify_si(project)[0] == sa.SI_VACUOUS
    assert sa.main([str(project), "--mode", "tapeout"]) == 1
    # ...and the acceptance the rejected runs could not use works here.
    _waive_every_vacuity(project)
    r = sa._check_tapeout(project)
    assert _si(r)["state"] == sa.SI_VACUOUS
    assert _si(r)["waived"] is True
    assert r.summary["verdict_tier"] == "PASS_WITH_WAIVERS"
    assert sa.main([str(project), "--mode", "tapeout"]) == sa.WAIVER_EXIT_CODE


def test_a_proved_run_publishes_no_vacuity_code_end_to_end(tmp_path):
    """The third arm of the same trichotomy, from the same shipped bytes: a run
    that PROVED folds names no vacuity either, so `vacuity_code` is non-empty
    in exactly one of the three states this gate can be in."""
    project = _materialise_si_project(tmp_path, "proved", case="coupled")
    rc, doc = _run_si_gate(project)
    den = doc["summary"]["denominator"]
    assert (rc, doc["verdict"]) == (sic.RC_PASS, "PASS")
    assert den["examined"] > 0
    assert den["details"]["vacuity_code"] == ""
    assert den["not_applicable_reason"] == ""
    assert sa._classify_si(project)[0] == sa.SI_PROVED
    assert sa.main([str(project), "--mode", "tapeout"]) == 0


def test_a_could_not_run_verdict_is_refused_though_it_names_a_vacuity(
        tmp_path):
    """THE ONE PLACE PRODUCER AND CONSUMER DELIBERATELY DISAGREE, pinned so the
    disagreement stays in the safe direction.

    `NOT_RUN` (#506) did not exist when this feature was written, so nothing
    else here covers it. Its five categories mean THE GATE NEVER GOT TO LOOK,
    which is genuinely the vacuity family — `_vacuity` has branches named for
    exactly those states (`SPEF_UNREADABLE`, `EMITTER_REPORT_UNREADABLE`,
    `NO_CORNER_RECOUNTED`) — so the emitter still NAMES this state, in the
    nine-branch vocabulary it always used.

    #535 CHANGED WHICH FIELD THAT NAME GOES IN, and this test was the pin on
    the old answer. It asserted `details.vacuity_code != ""` here: the name
    was published in the very field `si_vacuity_accepted` matches against, and
    the only thing standing between it and a waived tapeout was the two
    consumer defences below. The name is now published in
    `details.unwaivable_code` instead, so nothing is silenced and nothing is
    reachable.

    The tape-out consumer refuses it anyway, and must: "an absent or
    unparseable SI report is not vacuity — it is worse", so it takes the
    failing path, not the waivable one.

    THREE INDEPENDENT THINGS HOLD THAT and all three are asserted, because any
    two are one edit from leaving the third as the only one left. The first
    two are the defences this test was written for and they are UNCHANGED;
    #535 added the third, at the producer, where it does not depend on a
    future reader remembering anything:

      1. `_si_defect_evidence` reads the report BODY before any verdict
         branch, and a NOT_RUN carries an ERROR finding by construction. So it
         classifies as VIOLATION. Narrowing that read to the substantive
         categories — which would look like a tidy-up, since NOT_RUN's
         categories are by definition NOT substantive defects — is what this
         first half catches.
      2. Even with the body blinded, `NOT_RUN` is not a string the waivable
         branch matches. It falls through to the unrecognised-verdict tier,
         which is also refused. Adding NOT_RUN to that branch as a "missing
         case" is what the second half catches.
      3. The emitter never offers the name to the waivable channel in the
         first place: `vacuity_code` is empty and `unwaivable_code` carries
         the code. This one holds even for a consumer that has neither of the
         other two — which is every consumer written from now on that reads
         the code without reading the defect channel."""
    project = _materialise_si_project(tmp_path, "not_run")
    rp = project / "reports" / "phase3" / "si_mcf_sta.json"
    doc = json.loads(rp.read_text())
    doc["spef"] = str(project / "a_spef_this_run_never_produced.spef")
    rp.write_text(json.dumps(doc, indent=2))

    rc, out = _run_si_gate(project)
    assert (rc, out["verdict"]) == (sic.RC_FAIL, "NOT_RUN")
    assert [f["category"] for f in out["findings"]
            if f["severity"] == "ERROR"] == ["NO_SPEF"]
    # (3) THE PRODUCER-SIDE LINE (#535). The state is still NAMED — the
    # could-not-run states ARE vacuity branches and silencing them would lose
    # a machine-readable name — but the name is published in the channel no
    # acceptance reads. Before #535 this read `vacuity_code != ""`.
    det = out["summary"]["denominator"]["details"]
    assert det["vacuity_code"] == "", (
        "a could-not-run state is being offered to the waivable channel")
    assert det["unwaivable_code"] == "SPEF_UNREADABLE", det

    # (1) ...and even if it were, naming it buys nothing: the body is read
    # first.
    _waive_every_vacuity(project)
    r = sa._check_tapeout(project)
    assert _si(r)["state"] == sa.SI_VIOLATION
    assert _si(r)["state"] not in sa._SI_WAIVABLE_STATES
    assert _si(r)["waived"] is False
    # `_classify_si` carries `vacuity_code` out of the VACUOUS branch only, so
    # the audit summary reports none for a state that never entered it — the
    # code the report published is not propagated to anything that could match
    # it against the acceptance list.
    assert _si(r)["vacuity_code"] == ""
    assert sa.main([str(project), "--mode", "tapeout"]) == 1

    # (2) THE SECOND LINE, measured with the first one removed. Strip the
    # defect channel the body-first read depends on, keeping the counts
    # agreeing so nothing else objects: the verdict token alone must still
    # keep this out of the waivable branch.
    report = project / _SI_REPORT
    blinded = json.loads(report.read_text())
    blinded["findings"] = []
    blinded["summary"]["errors_count"] = 0
    blinded["summary"]["findings_count"] = 0
    report.write_text(json.dumps(blinded, indent=2))
    assert sa._si_defect_evidence(blinded, blinded["summary"]) == "", (
        "the body-first read still fires — the second line is not being "
        "measured on its own")

    state, detail = sa._classify_si(project)
    assert state not in sa._SI_WAIVABLE_STATES, state
    assert state == sa.SI_UNDISCLOSED, state
    assert "NOT_RUN" in detail["why"], detail["why"]
    assert sa._check_tapeout(project).passed is False
    assert sa.main([str(project), "--mode", "tapeout"]) == 1


# ===========================================================================
# THE WAIVABLE CHANNEL IS A FIELD, NOT A CONVENTION (#535)
# ===========================================================================
# WHY THIS SECTION EXISTS.
#
# The section above pins that TODAY's consumer refuses a could-not-run run by
# two independent mechanisms. Both are real and both stay. Neither is a
# property of the REPORT: they are properties of `signoff_audit`, and any
# consumer written from now on that reads `details.vacuity_code` without first
# reading the defect channel inherits neither.
#
# MEASURED on the tree before this change, driving the real CLI over
# `fixtures/si_mcf_zero_coupling/grounded_only` with one perturbation each:
#
#   (none)                             rc 2  VACUOUS_PASS  SPEF_NO_COUPLING_PAIRS
#   emitter report absent              rc 1  NOT_RUN       EMITTER_REPORT_UNREADABLE
#   named SPEF absent                  rc 1  NOT_RUN       SPEF_UNREADABLE
#   no corner record at all            rc 1  NOT_RUN       NO_CORNER_RECOUNTED
#   HOLD corner absent, SETUP recounts rc 1  NOT_RUN       SPEF_NO_COUPLING_PAIRS
#
# THE LAST ROW IS WHY A PREFIX OR A NARROWED CODE LIST WOULD NOT HAVE DONE.
# It publishes `SPEF_NO_COUPLING_PAIRS` — byte-identical to the FIRST row, a
# genuine waivable vacuity — on a run that never obtained its hold corner. The
# hazard is not that the could-not-run states have names of their own; it is
# that the SAME name appears in both states, so nothing keyed on the NAME can
# separate them. The separation is a property of the RUN, and `denominator`
# already holds the findings list that decides it.
#
# EVERY PATH HERE STAYS INSIDE THE REPOSITORY, exactly as the section above:
# copies of the shipped fixture under pytest's `tmp_path`, driven through the
# real CLI, with no assertion depending on a file this checkout does not carry.

def _vacuity_branch_codes_from_source() -> list:
    """The code every `_vacuity` branch can emit, read from the SOURCE.

    NOT from `_VACUITY_BRANCHES`. That table is hand-maintained, and the
    nine-branch assertion above builds `seen` by ITERATING it — so a TENTH
    branch added to `_vacuity()` with no table row leaves `len(seen)` at 9 and
    every table-driven assertion in this file green while the new state goes
    unclassified. Deriving the population from the function's own AST is what
    makes "exhaustive over branches" mean branches.

    FAILS LOUD IF IT GOES BLIND. An assignment it cannot read as a literal is
    reported rather than skipped: a probe that silently sees fewer branches
    than exist would answer "every branch is classified" for exactly the
    reason the count assertion answers "there are nine".
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(sic._vacuity)))
    codes, opaque = [], []
    for node in ast.walk(tree.body[0]):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "code":
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(
                        value.value, str):
                    codes.append(value.value)
                else:
                    opaque.append(ast.dump(value))
    assert not opaque, (
        f"`_vacuity` assigns `code` from something this probe cannot read as "
        f"a literal ({opaque}); it can no longer enumerate the branch set, so "
        f"every assertion built on it would pass by seeing too few branches")
    assert len(codes) >= 2, (
        "the probe found almost no `code` assignments — `_vacuity` has been "
        "restructured and this enumeration is measuring nothing")
    return codes


def test_the_branch_set_is_derived_from_the_source_not_from_the_hand_table():
    """A branch that exists in `_vacuity` but in no table row must be caught.

    `test_vacuity_code_and_prose_come_from_the_same_branch` builds `seen` by
    iterating `_VACUITY_BRANCHES`, so its `len(seen) == 9` counts TABLE ROWS.
    Adding a tenth branch to the function and no row to the table leaves it
    green. This closes that: the source is the population, the table is
    checked against it, and drift in either direction names itself."""
    from_source = _vacuity_branch_codes_from_source()
    assert len(from_source) == len(set(from_source)), (
        f"two `_vacuity` branches emit the same code: {from_source}")

    from_table = [code for _, code in _VACUITY_BRANCHES]
    assert set(from_source) == set(from_table), (
        f"`_vacuity` and `_VACUITY_BRANCHES` disagree about which states "
        f"exist. Only in the source: "
        f"{sorted(set(from_source) - set(from_table))}; only in the table: "
        f"{sorted(set(from_table) - set(from_source))}")
    assert len(from_source) == len(from_table) == 9


def test_the_waivable_list_names_only_branches_that_exist():
    """A stale entry is a code nobody can publish — and, worse, a name an
    acceptance could still be written against. Read from the source, so
    renaming a branch without renaming its entry fails here."""
    from_source = set(_vacuity_branch_codes_from_source())
    assert sic.WAIVABLE_VACUITY_CODES <= from_source, (
        f"`WAIVABLE_VACUITY_CODES` names states `_vacuity` cannot reach: "
        f"{sorted(sic.WAIVABLE_VACUITY_CODES - from_source)}")


def test_every_branch_lands_in_exactly_one_publication_class():
    """Exhaustive and disjoint, over the branch set read from the source.

    "Exactly one" is asserted per code rather than by counting, so a change
    that published a code into BOTH fields — which would put an un-waivable
    state back within reach while leaving every count assertion green — fails
    here."""
    from_source = _vacuity_branch_codes_from_source()
    waivable, unwaivable = [], []
    for code in from_source:
        v, u = sic.vacuity_publication(code, not_run=False)
        assert (bool(v), bool(u)) in ((True, False), (False, True)), (
            f"{code} does not land in exactly one class: "
            f"vacuity_code={v!r} unwaivable_code={u!r}")
        assert v in ("", code) and u in ("", code), (code, v, u)
        (waivable if v else unwaivable).append(code)

    assert set(waivable) | set(unwaivable) == set(from_source)
    assert not (set(waivable) & set(unwaivable))
    # ...and the split is the one the module documents: the three branches
    # whose predicate is an input the gate never obtained are the un-waivable
    # ones. Named here so PROMOTING one into the waivable set is a test
    # failure rather than a silent widening of what a tapeout may accept.
    assert sorted(unwaivable) == [
        "EMITTER_REPORT_UNREADABLE", "NO_CORNER_RECOUNTED", "SPEF_UNREADABLE"]
    assert sorted(waivable) == sorted(sic.WAIVABLE_VACUITY_CODES)


def test_a_branch_the_waivable_list_does_not_name_defaults_to_unwaivable(
        monkeypatch):
    """THE TENTH BRANCH, simulated end to end through `denominator`.

    The requirement is that adding a branch and forgetting to classify it
    fails towards BLOCKING a tapeout. Asserted by making `_vacuity` return a
    state no list names — which is exactly what a tenth branch is on the day
    it lands — and reading which field `denominator` puts it in."""
    monkeypatch.setattr(
        sic, "_vacuity",
        lambda stats: ("A_TENTH_STATE_NOBODY_CLASSIFIED",
                       "invented by a test. Read this as NOT CHECKED."))
    stats = {"report_read": True, "spef_read": True, "spef_net_records": 5,
             "recount": {"setup": {"nets_checked": 0}}}
    details = sic.denominator(stats).as_dict()["details"]
    assert details["vacuity_code"] == "", (
        "an unclassified branch defaulted INTO the waivable channel — a state "
        "nobody reviewed became acceptable at a mask order by omission")
    assert details["unwaivable_code"] == "A_TENTH_STATE_NOBODY_CLASSIFIED"
    # ...and it is still DISCLOSED: defaulting to un-waivable must not mean
    # defaulting to silent.
    assert sic.denominator(stats).not_applicable_reason.strip()


def test_a_could_not_run_finding_demotes_even_a_waivable_code():
    """The second condition, measured on its own.

    Set membership cannot see this state: the code IS on the waivable list and
    is the same one a genuine vacuity publishes. Only the findings tell the two
    apart, which is why `vacuity_publication` reads them."""
    code = "SPEF_NO_COUPLING_PAIRS"
    assert code in sic.WAIVABLE_VACUITY_CODES        # ...the premise
    assert sic.vacuity_publication(code, not_run=False) == (code, "")
    assert sic.vacuity_publication(code, not_run=True) == ("", code)

    # ...and through `denominator`, from a findings list, not a flag.
    stats = {"report_read": True, "spef_read": True, "spef_net_records": 5,
             "recount": {"setup": {"nets_checked": 0}}}
    clean = sic.denominator(stats, []).as_dict()["details"]
    assert clean["vacuity_code"] == code and clean["unwaivable_code"] == ""

    for category in sorted(sic.NOT_RUN_CATEGORIES):
        finding = sic.Finding("ERROR", category, "the gate never got to look")
        details = sic.denominator(stats, [finding]).as_dict()["details"]
        assert details["vacuity_code"] == "", category
        assert details["unwaivable_code"] == code, category


# ---------------------------------------------------------------------------
# ...and the same properties, driven through the real CLI
# ---------------------------------------------------------------------------
def _not_run_projects(tmp_path: Path) -> list:
    """One project per could-not-run state reachable from the shipped fixture.

    Each is a copy under `tmp_path` carrying ONE perturbation, so the state a
    row reaches is the perturbation named beside it and nothing else."""
    def _report(project: Path) -> Path:
        return project / "reports" / "phase3" / "si_mcf_sta.json"

    def _edit(project: Path, mutate) -> Path:
        rp = _report(project)
        doc = json.loads(rp.read_text())
        mutate(project, doc)
        rp.write_text(json.dumps(doc, indent=2))
        return project

    def _drop_bounded(proj, doc):
        for corner in doc["corners"].values():
            corner["bounded_spef"] = str(proj / "a_bounded_spef_never_written")

    out = []

    p = _materialise_si_project(tmp_path, "nr_report_absent")
    _report(p).unlink()
    out.append(("emitter report absent", "EMITTER_REPORT_UNREADABLE", p))

    p = _materialise_si_project(tmp_path, "nr_report_unparseable")
    _report(p).write_text("{{{ not json")
    out.append(("emitter report unparseable", "EMITTER_REPORT_UNREADABLE", p))

    out.append(("named SPEF absent", "SPEF_UNREADABLE", _edit(
        _materialise_si_project(tmp_path, "nr_spef_absent"),
        lambda proj, doc: doc.__setitem__(
            "spef", str(proj / "a_spef_this_run_never_produced.spef")))))

    out.append(("no corner record at all", "NO_CORNER_RECOUNTED", _edit(
        _materialise_si_project(tmp_path, "nr_no_corners"),
        lambda proj, doc: doc.__setitem__("corners", {}))))

    out.append(("bounded SPEF absent on both corners", "NO_CORNER_RECOUNTED",
                _edit(_materialise_si_project(tmp_path, "nr_no_bounded"),
                      _drop_bounded)))

    # THE DECISIVE ROW. The SETUP corner recounts to zero coupling pairs — a
    # genuine, waivable vacuity NAME — while the HOLD corner is never
    # obtained. Same code as the control, different run.
    out.append(("hold corner absent, setup recounts", "SPEF_NO_COUPLING_PAIRS",
                _edit(_materialise_si_project(tmp_path, "nr_hold_absent"),
                      lambda proj, doc: doc["corners"].pop("hold"))))

    return out


def test_a_could_not_run_state_reaches_the_vacuity_branches_at_all(tmp_path):
    """THE PREMISE, measured before anything is built on it.

    Every row must actually reach `NOT_RUN` with a zero denominator. A row
    that silently reached some other state would make the guard below assert
    something about a state that cannot happen."""
    cases = _not_run_projects(tmp_path)
    assert len(cases) == 6, "the premise must be measured on every row"
    for label, _code, project in cases:
        rc, doc = _run_si_gate(project)
        errors = [f["category"] for f in doc["findings"]
                  if f["severity"] == "ERROR"]
        assert doc["verdict"] == "NOT_RUN", (label, doc["verdict"])
        assert rc == sic.RC_FAIL, (label, rc)
        assert doc["summary"]["denominator"]["examined"] == 0, label
        assert errors, (label, "no ERROR finding — not a could-not-run run")
        assert set(errors) <= sic.NOT_RUN_CATEGORIES, (label, errors)


def test_no_could_not_run_state_publishes_into_the_waivable_channel(tmp_path):
    """THE GUARD, through the real CLI on the shipped fixture.

    `vacuity_code` is the token an acceptance quotes, so a state that is not a
    waivable vacuity must publish none — and must still be NAMED, in the other
    channel, because silencing it would lose the machine-readable name the
    could-not-run states are entitled to."""
    for label, code, project in _not_run_projects(tmp_path):
        _, doc = _run_si_gate(project)
        details = doc["summary"]["denominator"]["details"]
        assert details["vacuity_code"] == "", (
            f"{label}: the gate never obtained its input and still named the "
            f"state as vacuity {details['vacuity_code']!r} — a code an "
            f"operator can record in {sa.SI_DISCLOSURE_FIELD}")
        assert details["unwaivable_code"] == code, (label, details)
        assert doc["summary"]["denominator"][
            "not_applicable_reason"].strip(), label


def test_a_rejected_artefact_publishes_no_code_in_either_channel(tmp_path):
    """The #533 guarantee, restated over both channels.

    A rejection is not a vacuity AND not a could-not-run: the artefact WAS
    obtained, examined, and found wrong. Adding a second channel must not give
    that state somewhere new to be named — `_rejected_reason` and the findings
    carry it, and neither code field does."""
    for category, project in _rejected_projects(tmp_path):
        _, doc = _run_si_gate(project)
        details = doc["summary"]["denominator"]["details"]
        assert details["vacuity_code"] == "", category
        assert details["unwaivable_code"] == "", (
            f"{category}: a REJECTED artefact was named in the un-waivable "
            f"channel as {details['unwaivable_code']!r} — the findings and "
            f"the rejected reason carry a decided failure, not a code")


def test_a_consumer_reading_only_the_waivable_channel_sees_no_unwaivable_state(
        tmp_path):
    """THE PROPERTY THE FIELD BUYS, demonstrated by EXECUTING a consumer.

    `_blind` is the future consumer this whole change is for: it reads
    `details.vacuity_code` and nothing else — no verdict, no findings, no
    `errors_count` — and treats a non-empty value as an acceptable vacuity.
    That is the reader who inherits neither of `signoff_audit`'s defences.

    Across every state reachable from the shipped fixture it must accept ONLY
    runs the gate itself answered `VACUOUS_PASS`. The control at the end is
    what stops this passing by publishing nothing anywhere."""
    def _blind(doc: dict) -> bool:
        return bool(doc["summary"]["denominator"]["details"]["vacuity_code"])

    cases = ([(label, p) for label, _c, p in _not_run_projects(tmp_path)]
             + [(cat, p) for cat, p in _rejected_projects(tmp_path)]
             + [("proved", _materialise_si_project(
                 tmp_path, "blind_proved", case="coupled")),
                ("genuine vacuity",
                 _materialise_si_project(tmp_path, "blind_vacuity"))])
    assert len(cases) == 11, cases

    accepted = []
    for label, project in cases:
        _, doc = _run_si_gate(project)
        details = doc["summary"]["denominator"]["details"]
        # At most one channel is ever non-empty, whatever the state.
        assert not (details["vacuity_code"] and details["unwaivable_code"]), (
            label, details)
        if _blind(doc):
            accepted.append(label)
            assert doc["verdict"] == "VACUOUS_PASS", (
                f"{label}: a consumer reading ONLY the waivable channel would "
                f"accept a run the gate answered {doc['verdict']!r}")

    # THE CONTROL. With this list empty the assertion above would hold
    # vacuously — a gate that published nothing at all would pass it.
    assert accepted == ["genuine vacuity"], accepted
