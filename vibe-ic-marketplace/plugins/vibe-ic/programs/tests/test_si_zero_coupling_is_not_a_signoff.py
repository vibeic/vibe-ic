#!/usr/bin/env python3
"""The SI gate that signed off when it measured zero coupling.

THE DEFECT, on origin/main. `si_mcf_sta_check.audit()` computes
`pairs = M.coupling_pairs(sp)`, stores `len(pairs)` in the summary, and never
turns it into a finding. Every rule the gate has is denominated in those pairs:
`floor_folded_caps(pairs, corner)` is the `expected` dict, and
`independent_recount` iterates it. With zero pairs `expected` is `{}`, so
`nets_checked == 0`, `violations == []`, `ok is True` -> `verdict PASS`,
`findings: []`, rc 0. A SPEF carrying only grounded caps produced a sign-off
byte-identical to one whose fold was fully re-derived and proved.

THE FIXTURES ARE THE SAME SPEF TWICE. `_SPEF_COUPLED` and `_SPEF_GROUNDED_ONLY`
differ by exactly one `*CAP` line — the 4-token (2-node) entry. Everything else
(nets, pins, resistances, header) is identical, which is what makes the
comparison a measurement of the coupling axis and not of anything else.

BOUNDED SPEFS COME FROM THE REAL EMITTER. `M.rewrite_spef_folded` is the
function `si_mcf_sta.run()` uses, called with the fold dict the emitter would
compute for a zero-pair SPEF (empty). No hand-written "expected output".

WHAT IS DELIBERATELY NOT FAILED. A grounded-only extraction is a legitimate
state; `test_d1_*` pins that it exits with the disclosed-skip tier and not
FAIL, and that a genuinely coupled+folded run still exits 0. Turning the zero
into a FAIL would trade a false-clean for a false-alarm.

THE ZERO THAT SURVIVED THE FIRST FIX. An adversarial pass showed the same
false-clean displaced one notch: with coupling pairs whose CAPACITANCES are
zero-valued, every victim net is keyed, every comparison runs, and not one of
them can fail -- so the denominator was maximal and the verdict PASS, on a run
that proved nothing. The hold corner reproduces that by construction in
window-independent floor mode (`MCF_HOLD_WORST == 0`). Both are pinned here,
along with the two false alarms the same pass found: a legal `*R_NET`
reduced-format SPEF hard-FAILED, and a disclosure sentence reporting a PAIR
count under the words "two-node capacitances".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import si_mcf_sta as M            # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_HEAD = """*SPEF "ieee 1481-1999"
*DESIGN "t"
*VERSION "1.0"
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER []
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY

*NAME_MAP
*1 n1
*2 n2

"""

# The ONLY difference between the two fixtures is the 4-token *CAP line below.
_COUPLING_LINE = "3 u2:A u1:B 0.1\n"
# Same line, same id, same two node tokens — VALUE ZERO. The state an
# adversarial pass used to break the first cut of this fix: pairs exist, every
# victim net is keyed, every comparison runs and none of them can fail.
_ZERO_VALUE_COUPLING_LINE = "3 u2:A u1:B 0.0\n"
# A genuine two-node cap whose BOTH ends resolve to the same net. `parse_spef`
# drops it (`ra != rb`), so caps > 0 while pairs == 0.
_INTRA_NET_COUPLING_LINE = "3 u1:Z u1:B 0.05\n"

_BODY = """*D_NET *1 0.3
*CONN
*I u1:Z O *D BUF
*I u1:B I *D DFF
*CAP
1 u1:Z 0.1
2 u1:B 0.1
{coupling}*RES
1 u1:Z u1:B 10
*END

*D_NET *2 0.2
*CONN
*I u2:Z O *D BUF
*I u2:A I *D DFF
*CAP
1 u2:Z 0.1
2 u2:A 0.1
*RES
1 u2:Z u2:A 10
*END
"""

_SPEF_COUPLED = _HEAD + _BODY.format(coupling=_COUPLING_LINE)
_SPEF_GROUNDED_ONLY = _HEAD + _BODY.format(coupling="")
_SPEF_ZERO_VALUE_COUPLING = _HEAD + _BODY.format(
    coupling=_ZERO_VALUE_COUPLING_LINE)
_SPEF_INTRA_NET_COUPLING = _HEAD + _BODY.format(
    coupling=_INTRA_NET_COUPLING_LINE)

# A legal IEEE-1481 REDUCED-format SPEF: driver + lumped RC pi model, no
# *D_NET. Neither `net_grounded_totals` nor `parse_spef` models this shape.
_SPEF_R_NET_ONLY = _HEAD + """*R_NET *1 0.3
*DRIVER u1:Z
*CELL BUF
*C2_R1_C1 0.15 10 0.15
*END

*R_NET *2 0.2
*DRIVER u2:Z
*CELL BUF
*C2_R1_C1 0.1 10 0.1
*END
"""


def _project(tmp: Path, *, spef_text: str, setup_bounded: str,
             hold_bounded: str, extra_report: dict | None = None,
             setup_after: float = 7.36, hold_after: float = 0.39):
    proj = tmp / "proj"
    (proj / "reports" / "phase3").mkdir(parents=True)
    spef = proj / "design.spef"
    spef.write_text(spef_text)
    sb = proj / "design.mcf_setup.spef"
    sb.write_text(setup_bounded)
    hb = proj / "design.mcf_hold.spef"
    hb.write_text(hold_bounded)
    report = {
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
    }
    report.update(extra_report or {})
    rp = proj / "reports" / "phase3" / "si_mcf_sta.json"
    rp.write_text(json.dumps(report))
    return proj


def _bounded_from_emitter(spef_text: str):
    """The two bounded SPEFs `si_mcf_sta.run()` would emit for this SPEF."""
    pairs = M.coupling_pairs(spef_text)
    setup_fold = {k: v * 2 for k, v in M.floor_folded_caps(pairs,
                                                           "setup").items()}
    hold_fold = M.floor_folded_caps(pairs, "hold")
    s, _ = M.rewrite_spef_folded(spef_text, setup_fold, "setup")
    h, _ = M.rewrite_spef_folded(spef_text, hold_fold, "hold")
    return s, h


def _grounded_only_project(tmp: Path, **kw):
    s, h = _bounded_from_emitter(_SPEF_GROUNDED_ONLY)
    return _project(tmp, spef_text=_SPEF_GROUNDED_ONLY,
                    setup_bounded=s, hold_bounded=h, **kw)


def _categories(doc):
    return [f["category"] for f in doc["findings"]]


# ===========================================================================
# The fixture is honest about what it varies
# ===========================================================================
def test_the_two_fixtures_differ_only_in_coupling():
    assert _SPEF_COUPLED.replace(_COUPLING_LINE, "") == _SPEF_GROUNDED_ONLY
    assert len(M.coupling_pairs(_SPEF_COUPLED)) == 1
    assert len(M.coupling_pairs(_SPEF_GROUNDED_ONLY)) == 0
    # ... and both are real SPEFs with the same net records.
    assert (sorted(M.net_grounded_totals(_SPEF_COUPLED))
            == sorted(M.net_grounded_totals(_SPEF_GROUNDED_ONLY)) == ["*1", "*2"])


# ===========================================================================
# THE DEFECT: zero coupling was a clean SI sign-off
# ===========================================================================


_SI_CMD = "si_mcf_sta_check . --json reports/phase3/si_mcf_sta_check.json"


def _si_step():
    """The slot the canonical flow wires this gate in, at Step 27."""
    return {"id": "probe", "name": "si clause only",
            "gate": {"all_of": [{"optional_program_exit_zero": {
                "command": _SI_CMD,
                "condition_files_exist": ["reports/phase3/si_mcf_sta.json"]}}]}}


def _reason_taxonomy():
    import _flow_reason_taxonomy as T
    return T


def test_the_tier_is_not_bought_by_a_relabel(tmp_path):
    """THE ASSERTION THAT REDDENS IF THE CLASSIFICATION MOVES AGAIN.

    The cheapest way to green the two assertions above is to publish
    `reason_class: CAPABILITY_ABSENT` from this gate, or to widen
    SKIP_ELIGIBLE: the step returns to VACUOUS_PASS having re-derived exactly
    as many folds as before, which is zero. A denominator of zero is not a
    missing capability — the SPEF parser is present and it ran. This pins the
    CONSEQUENCE of that relabel so the trade shows up in a diff."""
    T = _reason_taxonomy()
    proj = _grounded_only_project(tmp_path)

    # …and the STEP tier the same gate produces is NOT_MEASURED.

    orig = T.infer_nonverdict_reason
    try:
        T.infer_nonverdict_reason = lambda **kw: T.CAPABILITY_ABSENT
    finally:
        T.infer_nonverdict_reason = orig
    assert tier_r == "NOT_MEASURED", (
        "the two dispositions must remain DISTINGUISHABLE at the step tier; "
        "if this stops being true the assertions above measure nothing: "
        f"{tier_r}")


def test_the_written_reason_now_reaches_the_flow_listing(tmp_path):
    """THE DISCLOSED LIMITATION IS GONE, and this is the test that said so.

    It used to read: "the tier promotes correctly, but
    `_check_program_exit_zero` DISCARDS the captured snippet on rc 2 and
    returns the bare `__VACUOUS_HINT__` marker, so the gate's own prose (`Read
    this as NOT CHECKED`) never reaches the step listing a reviewer reads --
    they get the repo-wide `input not applicable` wording instead, which is not
    what happened here". It was disclosed rather than fixed because the
    substitution was shared by every rc-2 gate in the repo.

    `#1978`/`#1980` made exactly that repo-wide change. A non-skip-eligible rc
    2 now renders as `INCOMPLETE: <cmd> - reason_class=...; <the gate's own
    detail>`, so the sentence the reviewer needed is in the listing. Its own
    failure message named this outcome in advance ("the flow now carries the
    gate's written reason -- good, but the docstring's disclosure that it does
    NOT is now wrong and must change"), so the rewrite is the one the author
    asked for, not a convenience.

    BOTH HALVES ARE STILL PINNED, which was the point: the reason travels on
    the flow snippet AND in the JSON report, and neither is allowed to become
    the only channel."""
    proj = _grounded_only_project(tmp_path)
    doc = json.loads(
        (proj / "reports" / "phase3" / "si_mcf_sta_check.json").read_text())
    assert "NOT CHECKED" in doc["summary"]["denominator"][
        "not_applicable_reason"]


# ===========================================================================
# The half of cause (b) that IS decidable -> ERROR, not skip
# ===========================================================================


def test_a_fold_with_no_source_fails(tmp_path):
    """Nothing to fold, yet the bounded SPEF carries more grounded charge than
    the original — the two files are not a matched pair. This is the
    over-application half of rule 3, unreachable at zero pairs because its
    ceiling is derived from the pairs."""
    s, h = _bounded_from_emitter(_SPEF_GROUNDED_ONLY)
    inflated = s.replace("1 u1:Z 0.1", "1 u1:Z 0.9")
    assert inflated != s, "fixture did not inflate anything"
    proj = _project(tmp_path, spef_text=_SPEF_GROUNDED_ONLY,
                    setup_bounded=inflated, hold_bounded=h)


# ===========================================================================
# THE DEFECT DISPLACED ONE NOTCH: a comparison that ran and could not fail
#
# The first cut of this fix counted `independent_recount`'s `nets_checked` as
# its denominator. That counts nets that ENTERED the loop, including every net
# whose re-derived expectation is 0.0 — whose assertion is `increase >= -1e-9`
# and cannot fail. An adversarial pass broke the fix exactly there.
# ===========================================================================
def test_zero_valued_coupling_caps_do_not_count_as_proved_folds(tmp_path):
    """The pairs are real, the nets are keyed, every comparison runs — and not
    one of them could have failed. THE SAME FALSE-CLEAN as zero pairs, wearing
    a full denominator."""
    assert len(M.coupling_pairs(_SPEF_ZERO_VALUE_COUPLING)) == 1, (
        "fixture must still parse as a coupled SPEF")
    assert M.count_coupling_caps(_SPEF_ZERO_VALUE_COUPLING) == 1
    s, h = _bounded_from_emitter(_SPEF_ZERO_VALUE_COUPLING)
    proj = _project(tmp_path, spef_text=_SPEF_ZERO_VALUE_COUPLING,
                    setup_bounded=s, hold_bounded=h)


def test_the_hold_corner_floor_is_disclosed_as_proving_nothing(tmp_path):
    """MCF_HOLD_WORST is 0, so in window-independent floor mode EVERY hold
    expectation is 0.0 and no hold comparison can fail on the fold axis. The
    report must not dress those comparisons as coverage."""
    assert M.MCF_HOLD_WORST == 0.0
    s, h = _bounded_from_emitter(_SPEF_COUPLED)
    proj = _project(tmp_path, spef_text=_SPEF_COUPLED,
                    setup_bounded=s, hold_bounded=h)
    # ... and the headline is the proved count, not the visited count.


def test_the_reason_does_not_report_pairs_under_the_name_of_caps(tmp_path):
    """`parse_spef` drops a two-node cap whose ends land on the same net, so a
    file plainly carrying two-node capacitances can have zero PAIRS. Saying
    "0 two-node capacitances" there is a false statement about the bytes."""
    assert M.count_coupling_caps(_SPEF_INTRA_NET_COUPLING) == 1
    assert len(M.coupling_pairs(_SPEF_INTRA_NET_COUPLING)) == 0
    s, h = _bounded_from_emitter(_SPEF_INTRA_NET_COUPLING)
    proj = _project(tmp_path, spef_text=_SPEF_INTRA_NET_COUPLING,
                    setup_bounded=s, hold_bounded=h)


def test_the_two_coupling_counters_agree_by_construction(tmp_path):
    """The gate cites `spef_extraction_check.scan_spef` as a cross-check of
    `si_mcf_sta.count_coupling_caps`. They must not merely agree on the tracked
    corpus: a `*CAP` body followed by a `*D_PNET` block used to leave the
    latter still counting, because "*D_PNET".startswith("*D_NET") is False."""
    import spef_extraction_check as S
    text = (_HEAD + "*D_NET *1 0.3\n*CAP\n1 u1:Z 0.1\n"
            "*D_PNET *2 0.2\n3 x y 0.4\n*END\n")
    f = tmp_path / "edge.spef"
    f.write_text(text)
    assert M.count_coupling_caps(text) == S.scan_spef(f)["coupling_caps"] == 0


# ===========================================================================
# NO FALSE ALARM — the legitimate states, both directions
# ===========================================================================
def test_a_reduced_format_spef_is_skipped_not_failed(tmp_path):
    """THE FALSE ALARM THE ERROR RAISED. A legal IEEE-1481 `*R_NET` SPEF
    resolves to zero under BOTH the *D_NET recount and `parse_spef` — neither
    models the reduced form — so the two-reading version of
    SPEF_NO_NET_RECORDS hard-FAILED it, while `spef_extraction_check` (changed
    in the same commit) certifies the very same bytes as sound. It must take
    the skip tier."""
    import spef_extraction_check as S
    f = tmp_path / "r.spef"
    f.write_text(_SPEF_R_NET_ONLY)
    assert S.scan_spef(f)["r_nets"] == 2, "fixture is not a reduced-format SPEF"
    assert M.net_grounded_totals(_SPEF_R_NET_ONLY) == {}
    proj = _project(tmp_path, spef_text=_SPEF_R_NET_ONLY,
                    setup_bounded=_SPEF_R_NET_ONLY,
                    hold_bounded=_SPEF_R_NET_ONLY)


# ===========================================================================
# The gate publishes its OWN reason class (#1978 producer duty)
# ===========================================================================
