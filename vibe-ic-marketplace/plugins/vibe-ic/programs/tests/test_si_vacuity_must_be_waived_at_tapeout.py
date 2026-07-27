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

Four things a waiver may never do, each pinned below:
  * launder a genuine SI FAIL,
  * cover an ABSENT or unparseable report (nothing ran — there is no
    disclosure to accept),
  * cover a PASS carrying no denominator (the pre-fix false-clean shape),
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

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import signoff_audit as sa  # noqa: E402
import si_mcf_sta_check as sic  # noqa: E402
import _gdsii  # noqa: E402

_DECLARED_GDS = "phase3/stage4/gds/top.gds"
_SI_REPORT = sa._SI_REPORT_REL

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
               vacuity_code: str = "", denominator: bool = True) -> Path:
    """An SI report in the shape `si_mcf_sta_check` writes."""
    summary: dict = {"pass": verdict == "PASS", "vacuous": examined == 0}
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
         "summary": summary, "findings": []}, indent=2))


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
