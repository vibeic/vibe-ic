"""R-0915-154 — four STA stamps the phase-3 runner writes get a READER in the
program that actually consumes the report, each proven in both directions:
the stamp present changes the verdict / record, the stamp absent leaves
today's behaviour.

    STA_PARASITICS_PROVENANCE  sta_signoff_rigor_check  never a sign-off source
                               spice_correlation_check  (tested beside its own
                                                         writer fixtures in
                                                         test_spice_correlation_
                                                         sta_slack_parse.py)
    STA_ALIAS_BASIS            sta_signoff_rigor_check  judged AS its basis
    STA_CORNER_BINDING_REFUSED sta_signoff_rigor_check  never credited
    STA_BASIS_SDC              _ppa/backends/opensta.py + _ppa/timing.py:
                               the constraints' CONTENT digest is a timing
                               scope axis, so head-to-head parity refuses two
                               slacks timed under different SDCs.

MEASURED before the change, on the shipped code:
  * a tree holding only `phase3/stage3/pnr/sta.rpt` (which declares
    `PNR_SESSION_UNVERIFIED`) resolved through the rigor gate's `sta.rpt` /
    `*sta*.rpt` fallback and was GRADED as sign-off timing;
  * `spice_correlation_check._pick_sta_report` added that same file as a
    correlation candidate unconditionally.
Chip-, PDK- and vendor-AGNOSTIC: every name below is a fixture.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import sta_signoff_rigor_check as RIG            # noqa: E402
from _ppa.backends import opensta as OSTA        # noqa: E402

#: A report body the rigor gate PASSes: derate, the three check types and a
#: worst path behind the slack.
_RIGOROUS = (
    "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
    "report_check_types -recovery -removal -min_pulse_width\n"
    "SIGNOFF_CHECK_TYPES_REPORTED: recovery removal min_pulse_width\n"
    "Startpoint: a\nEndpoint: b\n  1.00 data arrival time\n"
    "  0.50 slack (MET)\n"
)
_UNVERIFIED = "STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED\n"


def _put(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# ── STA_PARASITICS_PROVENANCE: never a sign-off source ────────────────────

def test_the_premise_rigorous_body_passes():
    assert RIG.evaluate(_RIGOROUS)["verdict"] == "PASS", RIG.evaluate(_RIGOROUS)


def test_an_in_session_report_alone_is_not_graded_as_signoff(tmp_path):
    _put(tmp_path, "phase3/stage3/pnr/sta.rpt", _UNVERIFIED + _RIGOROUS)
    res = RIG.check(tmp_path)
    assert res["verdict"] == "IO_ERROR", res
    assert "PNR_SESSION_UNVERIFIED" in res["error"], res
    assert res["unverified_session_reports"], res


def test_without_the_stamp_the_same_report_is_graded(tmp_path):
    _put(tmp_path, "phase3/stage3/pnr/sta.rpt", _RIGOROUS)
    res = RIG.check(tmp_path)
    assert res["verdict"] == "PASS", res


def test_a_stamped_file_target_is_refused(tmp_path):
    rpt = _put(tmp_path, "sta.rpt", _UNVERIFIED + _RIGOROUS)
    assert RIG.check(rpt)["verdict"] == "IO_ERROR"


def test_a_real_signoff_report_beside_it_is_the_one_graded(tmp_path):
    _put(tmp_path, "phase3/stage3/pnr/sta.rpt", _UNVERIFIED + _RIGOROUS)
    real = _put(tmp_path, "phase3/stage3/sta/sta_spef_based.rpt", _RIGOROUS)
    res = RIG.check(tmp_path)
    assert res["verdict"] == "PASS", res
    assert res["report"] == str(real), res
    assert res["unverified_session_reports_skipped"], res


# ── STA_ALIAS_BASIS: a copy is judged as its basis ────────────────────────

_ALIAS_OF_MCORNER = "# STA_ALIAS_BASIS: sta_mcorner_ocv.rpt\n"
#: the basis LACKS min-pulse-width evidence; the copy's own bytes do not.
_BASIS_WITHOUT_MPW = _RIGOROUS.replace(
    "report_check_types -recovery -removal -min_pulse_width\n",
    "report_check_types -recovery -removal\n").replace(
    "SIGNOFF_CHECK_TYPES_REPORTED: recovery removal min_pulse_width\n",
    "SIGNOFF_CHECK_TYPES_REPORTED: recovery removal\n")


def test_an_alias_is_judged_as_its_basis_and_says_so(tmp_path):
    alias = _put(tmp_path, "pnr/post_route_timing.rpt",
                 _ALIAS_OF_MCORNER + _RIGOROUS)
    basis = _put(tmp_path, "pnr/sta_mcorner_ocv.rpt", _BASIS_WITHOUT_MPW)
    assert RIG.evaluate(_BASIS_WITHOUT_MPW)["verdict"] == "FAIL"
    res = RIG.check(alias)
    assert res["verdict"] == "FAIL", res
    assert res["alias_of"] == "sta_mcorner_ocv.rpt", res
    assert res["alias_basis_report"] == str(basis), res
    assert "judged as that basis" in res["alias_note"], res


def test_without_the_stamp_the_report_is_judged_on_its_own_bytes(tmp_path):
    rpt = _put(tmp_path, "pnr/post_route_timing.rpt", _RIGOROUS)
    _put(tmp_path, "pnr/sta_mcorner_ocv.rpt", _BASIS_WITHOUT_MPW)
    res = RIG.check(rpt)
    assert res["verdict"] == "PASS", res
    assert "alias_of" not in res, res


def test_an_alias_whose_basis_is_absent_says_what_it_judged(tmp_path):
    alias = _put(tmp_path, "pnr/post_route_timing.rpt",
                 _ALIAS_OF_MCORNER + _RIGOROUS)
    res = RIG.check(alias)
    assert res["alias_of"] == "sta_mcorner_ocv.rpt", res
    assert res["alias_basis_report"] is None, res
    assert "attributed to sta_mcorner_ocv.rpt" in res["alias_note"], res


# ── STA_CORNER_BINDING_REFUSED: never credited ────────────────────────────

def test_a_path_with_no_attributable_corner_is_not_credited():
    text = ("STA_CORNER_BINDING_REFUSED: missing_unknown_or_conflicting_"
            "setup_basis\n" + _RIGOROUS)
    res = RIG.evaluate(text)
    assert res["verdict"] == "FAIL", res
    assert res["corner_binding_refused"] == 1, res
    assert any("STA_CORNER_BINDING_REFUSED" in m for m in res["missing"]), res


def test_without_the_refusal_the_same_body_passes():
    res = RIG.evaluate(_RIGOROUS)
    assert res["corner_binding_refused"] == 0, res
    assert not any("corner attribution" in m for m in res["missing"]), res


# ── STA_BASIS_SDC: the constraints are a timing scope axis ────────────────

def _process_report(sdc_named: str) -> str:
    return ("=== SETUP corner: process=SS ===\n"
            "STA_BASIS: POST_ROUTE_SPEF\n"
            "STA_BASIS_LIBERTY: /pdk/cells__ss_100C_1v60.lib\n"
            + (f"STA_BASIS_SDC: {sdc_named}\n" if sdc_named else "")
            + "STA_BASIS_SPEF: /x/design.spef\nSTA_BASIS_CORNER: nom\n"
            "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
            "worst slack max 0.25\ntns max 0.00\n")




def _slack_scope(rows):
    r = next(r for r in rows if r["metric"] == "timing.setup.worst_slack_ns")
    return r["scope"], r.get("scope_gaps") or {}


def test_the_sdc_stamp_is_parsed_per_section():
    rep = OSTA.parse_report(_process_report("/foss/designs/p/c/top.sdc"))
    assert rep.sections[0].sdc == "/foss/designs/p/c/top.sdc"










def _arm(flow: str, sdc: str) -> dict:
    scope = {"stage": "post_route_extracted", "mode": "func", "process": "ss",
             "voltage_v": 1.6, "temperature_c": 100.0, "rc_corner": "nom",
             "check": "setup"}
    if sdc:
        scope["sdc"] = sdc
    return {"flow": flow, "ppa": {
        "area_um2": {"scope": {"stage": "post_route_extracted"}},
        "timing_wns_ns": {"scope": scope},
        "power_mw": {"scope": {"stage": "post_route_extracted", "mode": "func",
                               "process": "ss", "voltage_v": 1.6,
                               "temperature_c": 100.0,
                               "activity_basis": "vectorless"}}}}






# ── the stamp lines are a closed grammar, not prose (prose-polarity ratchet) ──

_POLARITY_TOKENS = ["not", "no", "none", "without", "excluding", "never", "non",
                    "removed", "obsolete", "superseded", "n/a", "inapplicable",
                    "deprecated", "no longer", "does not apply",
                    "非", "无", "無", "不", "否"]


def test_a_denial_spliced_into_the_stamp_lines_is_not_read():
    """THE FALSIFIER for the `_NOT_PROSE` entry on `sta_signoff_rigor_check::
    check`. Every `_prose_polarity` token is spliced before, inside and after
    each stamp's field; none of the resulting lines may be read as a stamp.
    The controls: the two stamps exactly as the runner writes them ARE read."""
    import _prose_polarity as pp
    for tok in _POLARITY_TOKENS:
        assert pp.NEGATION_RE.search(tok), tok      # the vocabulary, not my list
    alias_ok = "# STA_ALIAS_BASIS: sta_mcorner_ocv.rpt\n"
    unv_ok = "STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED\n"
    assert RIG._ALIAS_BASIS_RE.search(alias_ok).group(1) == "sta_mcorner_ocv.rpt"
    assert RIG._PNR_SESSION_UNVERIFIED_RE.search(unv_ok)
    read = []
    for tok in _POLARITY_TOKENS:
        for sp in (f"{tok} ", f" {tok}", f"{tok}"):
            for line in (f"# STA_ALIAS_BASIS: {sp}sta_mcorner_ocv.rpt\n",
                         f"# STA_ALIAS_BASIS: sta_mcorner_ocv.rpt {tok}\n",
                         f"# STA_ALIAS_BASIS: {tok}\n",
                         f"the report is {tok} STA_ALIAS_BASIS: sta_mcorner_ocv.rpt\n"):
                if RIG._ALIAS_BASIS_RE.search(line):
                    read.append(line)
            for line in (f"STA_PARASITICS_PROVENANCE: {sp}PNR_SESSION_UNVERIFIED\n",
                         f"STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED {tok}\n",
                         f"it is {tok} STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED\n"):
                if RIG._PNR_SESSION_UNVERIFIED_RE.search(line):
                    read.append(line)
    assert read == [], read


def test_a_free_text_mention_of_the_token_is_not_an_alias(tmp_path):
    """End to end: a report whose PROSE mentions the token is judged on its own
    bytes, exactly as if the token were absent."""
    rpt = _put(tmp_path, "pnr/post_route_timing.rpt",
               "# this report is not a STA_ALIAS_BASIS: sta_mcorner_ocv.rpt copy\n"
               + _RIGOROUS)
    _put(tmp_path, "pnr/sta_mcorner_ocv.rpt", _BASIS_WITHOUT_MPW)
    res = RIG.check(rpt)
    assert res["verdict"] == "PASS" and "alias_of" not in res, res
