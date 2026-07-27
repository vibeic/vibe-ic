#!/usr/bin/env python3
"""Step 27 — the SI gate that reported PASS having measured nothing.

THE DEFECT. `si_mcf_sta_check` exists to prevent a false-clean SI sign-off: it
independently re-derives the `Cc*MCF` fold from the original coupling SPEF and
proves the bounded SPEF carries it. Every one of its checks is about coupling
caps — so an extraction that carried NONE satisfies all of them by having
nothing to measure, and the gate emitted a plain `"verdict": "PASS"`.

MEASURED on the real completed run `campaign_pr427/spm/converge_ihp-sg13g2`
(pure-digital standard cell; SPEF and STA here are digital artefacts):

    origin/main   verdict "PASS", coupling_pairs 0, findings []
    this branch   verdict "VACUOUS_NO_COUPLING", coupling_pairs 0,
                  findings [WARNING SI_MCF_VACUOUS_NO_COUPLING]
    rc            0 on both

The sibling `si_crosstalk_check` already names exactly this situation
(`ADVISORY_SCREEN_ONLY` + `SI_ADVISORY_SCREEN_ONLY`); this gate did not, so the
two halves of step 27 disagreed about whether the same run had been measured.

WHY IT STAYS rc 0. A grounded-cap-only extraction is step 22's own declared
tier 1 — a legitimate capability tier, not a design defect. Turning it into a
FAIL would fail every pure-digital run for a capability gap. A gate may EXPLAIN
an absent artefact; it may not CERTIFY the step done without one. This changes
the certification, not the exit code.

WHAT IT COSTS. One extra WARNING finding and a different verdict STRING on
zero-coupling runs. Any reader keying on `verdict == "PASS"` for such a run now
sees `VACUOUS_NO_COUPLING` instead — which is the point, and is why
`summary.pass` (the rc source) is deliberately left alone.

DIRECTION-1 GUARDS (`test_d1_*`) hold on the pre-fix tree too.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import si_mcf_sta as M          # noqa: E402
import si_mcf_sta_check as G    # noqa: E402

_HEADER = """*SPEF "ieee 1481-1999"
*DESIGN "spm"
*VERSION "1.0"
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER []
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY

*NAME_MAP
*1 vic
*2 agg

"""

# The real run's shape: every *CAP entry is a 3-field GROUNDED cap.
_GROUNDED_ONLY = _HEADER + """*D_NET *1 0.3
*CONN
*I inv1:Z O *D BUF
*I ff1:D I *D DFF
*CAP
1 inv1:Z 0.1
2 ff1:D 0.2
*RES
1 inv1:Z ff1:D 10
*END

*D_NET *2 0.2
*CONN
*I inv2:Z O *D BUF
*I agg2:A I *D DFF
*CAP
1 inv2:Z 0.1
2 agg2:A 0.1
*RES
1 inv2:Z agg2:A 10
*END
"""

# A genuinely coupled extraction (tier 2/3): a 4-field *CAP entry.
_COUPLED = _HEADER + """*D_NET *1 0.3
*CONN
*I inv1:Z O *D BUF
*I ff1:D I *D DFF
*CAP
1 inv1:Z 0.1
2 ff1:D 0.1
3 ff1:D agg2:A 0.1
*RES
1 inv1:Z ff1:D 10
*END

*D_NET *2 0.2
*CONN
*I inv2:Z O *D BUF
*I agg2:A I *D DFF
*CAP
1 inv2:Z 0.1
2 agg2:A 0.1
*RES
1 inv2:Z agg2:A 10
*END
"""


def _project(tmp_path: Path, spef_text: str, *, setup_after=7.36,
             hold_after=0.39):
    """A project whose si_mcf_sta.json is otherwise entirely well-formed."""
    proj = tmp_path / "proj"
    (proj / "reports" / "phase3").mkdir(parents=True)
    spef = proj / "spm.spef"
    spef.write_text(spef_text)

    pairs = M.coupling_pairs(spef_text)
    setup_fold = {k: v * 2 for k, v in
                  M.floor_folded_caps(pairs, "setup").items()}
    sb_text, _ = M.rewrite_spef_folded(spef_text, setup_fold, "setup")
    hb_text, _ = M.rewrite_spef_folded(
        spef_text, {k: 0.0 for k in ("*1", "*2")}, "hold")
    sb = proj / "spm.mcf_setup.spef"
    sb.write_text(sb_text)
    hb = proj / "spm.mcf_hold.spef"
    hb.write_text(hb_text)

    rp = proj / "reports" / "phase3" / "si_mcf_sta.json"
    rp.write_text(json.dumps({
        "program": "si_mcf_sta", "spef": str(spef),
        "overlap_guard_ns": 0.0,
        "nominal": {"worst_setup_slack_ns": 7.37, "worst_hold_slack_ns": 0.39},
        "corners": {
            "setup": {"bounded_spef": str(sb),
                      "worst_slack_before_ns": 7.37,
                      "worst_slack_after_ns": setup_after},
            "hold": {"bounded_spef": str(hb),
                     "worst_slack_before_ns": 0.39,
                     "worst_slack_after_ns": hold_after},
        },
    }))
    return proj, rp


def _report(proj, rp):
    findings, stats = G.audit(proj, rp)
    return G.build_report(findings, stats, str(proj))


# ===========================================================================
# The vacuous run is disclosed, not certified
# ===========================================================================
def test_zero_coupling_run_is_not_certified_as_a_plain_pass(tmp_path):
    proj, rp = _project(tmp_path, _GROUNDED_ONLY)
    rep = _report(proj, rp)
    assert rep["summary"]["coupling_pairs"] == 0, rep["summary"]
    assert rep["verdict"] != "PASS", (
        "a recount with nothing to recount is still being presented as a "
        "sign-off PASS")
    assert rep["verdict"] == "VACUOUS_NO_COUPLING", rep["verdict"]


def test_zero_coupling_run_names_its_cause(tmp_path):
    """A verdict string alone is not a disclosure — a reader has to be able to
    find out why, and where."""
    proj, rp = _project(tmp_path, _GROUNDED_ONLY)
    rep = _report(proj, rp)
    hits = [f for f in rep["findings"]
            if f["category"] == "SI_MCF_VACUOUS_NO_COUPLING"]
    assert hits, rep["findings"]
    assert hits[0]["severity"] == "WARNING", hits[0]
    assert "step 22" in hits[0]["message"], hits[0]["message"]


def test_the_vacuous_tier_stays_non_blocking(tmp_path):
    """Blocking would fail every pure-digital run for a declared capability
    tier. `summary.pass` is what main() turns into rc."""
    proj, rp = _project(tmp_path, _GROUNDED_ONLY)
    rep = _report(proj, rp)
    assert rep["summary"]["pass"] is True
    assert G.main([str(proj), "--json", str(tmp_path / "o.json")]) == 0


def test_the_two_si_checks_agree_on_what_a_vacuous_run_is(tmp_path):
    """The asymmetry that made this a defect: si_crosstalk_check already had a
    named non-certifying tier for the analogous case and this gate did not."""
    import si_crosstalk_check as X
    assert "ADVISORY_SCREEN_ONLY" in X.build_report(
        [], {"report_found": True, "format": "json", "violations": 0,
             "advisory_screen_only": True}, ".")["verdict"]
    proj, rp = _project(tmp_path, _GROUNDED_ONLY)
    assert _report(proj, rp)["verdict"] == "VACUOUS_NO_COUPLING"


# ===========================================================================
# Two-sided control — a real measurement must NOT be labelled vacuous
# ===========================================================================
def test_a_genuinely_coupled_run_is_still_a_plain_pass(tmp_path):
    proj, rp = _project(tmp_path, _COUPLED)
    rep = _report(proj, rp)
    assert rep["summary"]["coupling_pairs"] > 0, rep["summary"]
    assert rep["verdict"] == "PASS", rep
    assert rep["summary"]["vacuous_no_coupling"] is False
    assert not [f for f in rep["findings"]
                if f["category"] == "SI_MCF_VACUOUS_NO_COUPLING"]


def test_a_real_defect_still_outranks_the_vacuous_tier(tmp_path):
    """VACUOUS must never mask a FAIL. Drive a genuine coupled run whose
    report claims the bounded slack IMPROVED."""
    proj, rp = _project(tmp_path, _COUPLED, setup_after=7.50)
    rep = _report(proj, rp)
    assert rep["verdict"] == "FAIL", rep
    assert any(f["category"] == "SLACK_BETTER_THAN_BOUND"
               for f in rep["findings"])


# ===========================================================================
# DIRECTION-1 GUARDS — hold on the pre-fix tree too
# ===========================================================================
def test_d1_a_genuine_fold_still_passes(tmp_path):
    proj, rp = _project(tmp_path, _COUPLED)
    assert _report(proj, rp)["summary"]["pass"] is True


def test_d1_a_dropped_fold_still_fails(tmp_path):
    """The false-clean-proof the gate exists for."""
    proj, rp = _project(tmp_path, _COUPLED)
    cheat, _ = M.rewrite_spef_folded(_COUPLED, {"*1": 0.0, "*2": 0.0}, "setup")
    (proj / "spm.mcf_setup.spef").write_text(cheat)
    rep = _report(proj, rp)
    assert rep["verdict"] == "FAIL"
    assert any(f["category"] == "FOLD_NOT_APPLIED" for f in rep["findings"])


def test_d1_a_missing_report_still_fails(tmp_path):
    proj = tmp_path / "empty"
    (proj / "reports" / "phase3").mkdir(parents=True)
    findings, stats = G.audit(proj)
    rep = G.build_report(findings, stats, str(proj))
    assert rep["verdict"] == "FAIL"
    assert any(f["category"] == "NO_REPORT" for f in rep["findings"])


def test_d1_residual_coupling_still_fails(tmp_path):
    proj, rp = _project(tmp_path, _COUPLED)
    (proj / "spm.mcf_setup.spef").write_text(_COUPLED)
    assert _report(proj, rp)["verdict"] == "FAIL"
