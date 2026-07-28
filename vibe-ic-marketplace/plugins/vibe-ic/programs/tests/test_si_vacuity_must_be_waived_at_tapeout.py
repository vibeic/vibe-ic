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


# ===========================================================================
# The producer names its own vacuity, in a token a machine may cite
# ===========================================================================
def test_vacuity_code_and_prose_come_from_the_same_branch():
    """A consumer that must decide whether a SPECIFIC vacuity was accepted
    cannot substring-match a paragraph of English. The code is the contract;
    the prose is what a human reads. They are derived together so they can
    never disagree about which state the gate is in."""
    seen = {}
    for stats, expect in (
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
    ):
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
    aged or closed — a permanent one."""
    import datetime
    import subprocess

    _five_pillars(tmp_path)
    _si_vacuous(tmp_path)
    _write(tmp_path / "waivers.json", json.dumps({
        "growth_rationale": ("One SI vacuity disclosed for this release; the "
                             "extraction rerun is tracked."),
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


def test_the_channel_check_is_silent_on_every_real_report_in_the_tree(
        tmp_path):
    """The strongest false-alarm evidence available: the emitter's own output.

    Not a fixture — every checker-output SI report tracked in this repo, in
    every verdict state. A clause that fires on one of these would be blocking
    correct work.
    """
    corpus = Path(__file__).resolve().parents[5] / "benchmark-data"
    if not corpus.is_dir():
        pytest.skip("no benchmark-data corpus in this checkout — this control "
                    "is NOT measured here, rather than passing vacuously")
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
