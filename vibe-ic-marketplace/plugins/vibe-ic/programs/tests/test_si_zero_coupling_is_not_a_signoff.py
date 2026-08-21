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
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "si_mcf_sta_check.py"
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import si_mcf_sta as M            # noqa: E402
import si_mcf_sta_check as G      # noqa: E402

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


def _run(proj: Path):
    out = proj / "out.json"
    r = subprocess.run([sys.executable, str(_PROG), str(proj),
                        "--json", str(out)],
                       capture_output=True, text=True, timeout=60)
    return r, json.loads(out.read_text())


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
def test_zero_coupling_is_not_a_pass(tmp_path):
    """origin/main: rc 0, verdict PASS, findings []. The whole denominator of
    the re-derivation was zero and the verdict did not say so."""
    proj = _grounded_only_project(tmp_path)
    r, doc = _run(proj)
    assert doc["summary"]["coupling_pairs"] == 0, doc["summary"]
    assert doc["verdict"] != "PASS", (
        "a gate that re-derived nothing signed off as if it had: "
        f"{doc['verdict']}")
    assert doc["verdict"] == "VACUOUS_PASS", doc["verdict"]
    assert r.returncode == G.RC_VACUOUS, (r.returncode, r.stdout[-400:])


def test_zero_coupling_does_not_set_summary_pass(tmp_path):
    """`summary.pass` is what a consumer reads when it reads one field."""
    proj = _grounded_only_project(tmp_path)
    _, doc = _run(proj)
    assert doc["summary"]["pass"] is False
    assert doc["summary"]["vacuous"] is True


def test_the_zero_is_disclosed_with_a_written_reason(tmp_path):
    proj = _grounded_only_project(tmp_path)
    _, doc = _run(proj)
    denom = doc["summary"]["denominator"]
    assert denom["examined"] == 0, denom
    assert denom["unit"].strip(), denom
    reason = denom["not_applicable_reason"]
    # The reason must name the count it MEANS. This fixture genuinely has zero
    # two-node *CAP entries, and the reason has to say so from the cap counter,
    # not from the pair counter wearing the cap counter's words — see
    # `test_the_reason_does_not_report_pairs_under_the_name_of_caps`.
    assert denom["details"]["coupling_caps"] == 0, denom["details"]
    assert "0 two-node (coupling) *CAP entries" in reason, reason
    assert "NOT CHECKED" in reason, (
        "the tier must state what a reader may not conclude from it")


def test_the_report_is_disclosure_contract_compliant(tmp_path):
    """Checked against the shared contract, not re-typed here."""
    import _gate_denominator as gd
    proj = _grounded_only_project(tmp_path)
    _, doc = _run(proj)
    assert gd.disclosure_violations(doc["summary"]) == []


def test_the_vacuous_token_reaches_the_flow(tmp_path):
    """`flow_compliance_check` scans the COMBINED stdout+stderr snippet for a
    line-start `VACUOUS_PASS` token, and separately credits rc 2. Both channels
    must carry it, and stdout must stay parseable JSON."""
    proj = _grounded_only_project(tmp_path)
    r, _ = _run(proj)
    assert r.returncode == G.RC_VACUOUS
    assert any(ln.lstrip().startswith("VACUOUS_PASS")
               for ln in r.stderr.splitlines()), r.stderr
    json.loads(r.stdout)          # stdout is the report and nothing else


def test_step_27_sees_the_disclosure_and_not_a_pass(tmp_path):
    """END TO END through the slot the flow actually uses. Step 27 wires this
    gate as `optional_program_exit_zero`, whose rc handling is
    `_check_program_exit_zero`: rc 2 becomes the `__VACUOUS_HINT__` marker that
    promotes the step to the VACUOUS-PASS tier. Without that promotion the step
    renders as an ordinary PASS, which is the defect wearing a different hat."""
    import flow_compliance_check as F
    cmd = "si_mcf_sta_check . --json reports/phase3/si_mcf_sta_check.json"

    vac = _grounded_only_project(tmp_path / "vacuous")
    ok, out = F._check_program_exit_zero(vac, cmd)
    assert ok and out.startswith(F._VACUOUS_HINT_PREFIX), out[:200]

    s, h = _bounded_from_emitter(_SPEF_COUPLED)
    real = _project(tmp_path / "real", spef_text=_SPEF_COUPLED,
                    setup_bounded=s, hold_bounded=h)
    ok, out = F._check_program_exit_zero(real, cmd)
    assert ok and not out.startswith(F._VACUOUS_HINT_PREFIX), out[:200]


def test_the_written_reason_does_not_reach_the_flow_listing(tmp_path):
    """A DISCLOSED LIMITATION, pinned so it stays a decision and not a belief.

    The tier promotes correctly, but `_check_program_exit_zero` DISCARDS the
    captured snippet on rc 2 and returns the bare `__VACUOUS_HINT__` marker, so
    the gate's own prose ("Read this as NOT CHECKED") never reaches the step
    listing a reviewer reads -- they get the repo-wide "input not applicable"
    wording instead, which is not what happened here (the input was present and
    parsed; it simply carried no coupling). That convention is shared by every
    rc-2 gate in this repo and changing it is a repo-wide behaviour change, so
    it is disclosed rather than altered. The reason IS in the JSON report, and
    this test pins both halves so a future reader is not misled about which
    channel carries it."""
    import flow_compliance_check as F
    proj = _grounded_only_project(tmp_path)
    ok, out = F._check_program_exit_zero(
        proj, "si_mcf_sta_check . --json reports/phase3/si_mcf_sta_check.json")
    assert ok and out.startswith(F._VACUOUS_HINT_PREFIX)
    assert "NOT CHECKED" not in out, (
        "the flow now carries the gate's written reason -- good, but the "
        "docstring's disclosure that it does NOT is now wrong and must change")
    doc = json.loads(
        (proj / "reports" / "phase3" / "si_mcf_sta_check.json").read_text())
    assert "NOT CHECKED" in doc["summary"]["denominator"][
        "not_applicable_reason"]


# ===========================================================================
# The half of cause (b) that IS decidable -> ERROR, not skip
# ===========================================================================
def test_a_spef_with_no_net_records_fails(tmp_path):
    """The report carries corner slacks; the file it names has no *D_NET at
    all. Those numbers cannot have come from it."""
    proj = _project(tmp_path, spef_text=_HEAD,
                    setup_bounded=_HEAD, hold_bounded=_HEAD)
    r, doc = _run(proj)
    assert r.returncode == G.RC_FAIL, (r.returncode, doc["verdict"])
    assert "SPEF_NO_NET_RECORDS" in _categories(doc), doc["findings"]


def test_a_spef_the_recount_cannot_key_but_the_parser_can_is_only_skipped(
        tmp_path):
    """THE FALSE-ALARM THE NEW ERROR MUST NOT RAISE. `net_grounded_totals` keys
    on `*D_NET`; the shared `parse_spef` also models `*D_PNET`. A physical-net
    SPEF resolves to 0 under the first reading and >0 under the second, so it
    must take the disclosed-skip tier, NOT `SPEF_NO_NET_RECORDS` — which is why
    the ERROR requires BOTH readings to find nothing."""
    pnet = _HEAD + (
        "*D_PNET *1 0.3\n*CONN\n*I u1:Z O *D BUF\n*CAP\n1 u1:Z 0.1\n*END\n")
    proj = _project(tmp_path, spef_text=pnet,
                    setup_bounded=pnet, hold_bounded=pnet)
    r, doc = _run(proj)
    assert "SPEF_NO_NET_RECORDS" not in _categories(doc), doc["findings"]
    assert doc["verdict"] == "VACUOUS_PASS", doc["verdict"]
    assert r.returncode == G.RC_VACUOUS
    assert doc["summary"]["denominator"]["details"]["spef_parsed_nets"] > 0


def test_coupling_lost_since_the_numbers_were_emitted_fails(tmp_path):
    """The emitter recorded the pairs IT parsed. The gate re-parses the same
    path with the same parser and finds none: the bytes changed."""
    proj = _grounded_only_project(tmp_path,
                                  extra_report={"coupling_pairs": 7})
    r, doc = _run(proj)
    assert r.returncode == G.RC_FAIL, (r.returncode, doc["verdict"])
    assert "COUPLING_LOST_SINCE_EMIT" in _categories(doc), doc["findings"]


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
    r, doc = _run(proj)
    assert r.returncode == G.RC_FAIL, (r.returncode, doc["verdict"])
    assert "FOLD_WITHOUT_SOURCE" in _categories(doc), doc["findings"]


def test_pairs_present_but_none_attributable_is_also_vacuous():
    """The same hole one level in: coupling parsed, but no victim net resolves
    to a *D_NET block, so `nets_checked` is 0 and nothing was measured. Pinned
    on the pure function because the state is not constructible from a
    well-formed SPEF."""
    denom = G.denominator({
        "report_read": True, "spef_read": True,
        "coupling_pairs": 4, "coupling_nets": 3, "spef_net_records": 12,
        "recount": {"setup": {"nets_checked": 0},
                    "hold": {"nets_checked": 0}},
    })
    assert denom.is_vacuous
    assert "none of their victim" in denom.not_applicable_reason


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
    r, doc = _run(proj)
    denom = doc["summary"]["denominator"]
    assert denom["considered"] > 0, (
        "the comparisons DID run — that is the whole point of the trap")
    assert denom["examined"] == 0, denom
    assert doc["verdict"] == "VACUOUS_PASS", doc["verdict"]
    assert r.returncode == G.RC_VACUOUS
    assert "expectation of 0.0" in denom["not_applicable_reason"]


def test_a_zero_charge_run_is_not_byte_identical_to_a_proved_one(tmp_path):
    """The defect statement's own words, applied to the fix: a run that proved
    nothing must not emit the denominator block of one that proved 366 folds."""
    zs, zh = _bounded_from_emitter(_SPEF_ZERO_VALUE_COUPLING)
    zero = _project(tmp_path / "zero", spef_text=_SPEF_ZERO_VALUE_COUPLING,
                    setup_bounded=zs, hold_bounded=zh)
    gs, gh = _bounded_from_emitter(_SPEF_COUPLED)
    real = _project(tmp_path / "real", spef_text=_SPEF_COUPLED,
                    setup_bounded=gs, hold_bounded=gh)
    _, zdoc = _run(zero)
    _, rdoc = _run(real)
    assert (zdoc["summary"]["denominator"]
            != rdoc["summary"]["denominator"]), "the two are indistinguishable"
    assert zdoc["verdict"] != rdoc["verdict"]


def test_the_hold_corner_floor_is_disclosed_as_proving_nothing(tmp_path):
    """MCF_HOLD_WORST is 0, so in window-independent floor mode EVERY hold
    expectation is 0.0 and no hold comparison can fail on the fold axis. The
    report must not dress those comparisons as coverage."""
    assert M.MCF_HOLD_WORST == 0.0
    s, h = _bounded_from_emitter(_SPEF_COUPLED)
    proj = _project(tmp_path, spef_text=_SPEF_COUPLED,
                    setup_bounded=s, hold_bounded=h)
    _, doc = _run(proj)
    det = doc["summary"]["denominator"]["details"]
    assert doc["summary"]["windows_exact"] is False, "fixture must be floor mode"
    assert det["nets_compared_per_corner"]["hold"] > 0, det
    assert det["folds_proved_per_corner"]["hold"] == 0, det
    assert det["folds_proved_per_corner"]["setup"] > 0, det
    # ... and the headline is the proved count, not the visited count.
    assert (doc["summary"]["denominator"]["examined"]
            == det["folds_proved_per_corner"]["setup"])


def test_the_reason_does_not_report_pairs_under_the_name_of_caps(tmp_path):
    """`parse_spef` drops a two-node cap whose ends land on the same net, so a
    file plainly carrying two-node capacitances can have zero PAIRS. Saying
    "0 two-node capacitances" there is a false statement about the bytes."""
    assert M.count_coupling_caps(_SPEF_INTRA_NET_COUPLING) == 1
    assert len(M.coupling_pairs(_SPEF_INTRA_NET_COUPLING)) == 0
    s, h = _bounded_from_emitter(_SPEF_INTRA_NET_COUPLING)
    proj = _project(tmp_path, spef_text=_SPEF_INTRA_NET_COUPLING,
                    setup_bounded=s, hold_bounded=h)
    r, doc = _run(proj)
    reason = doc["summary"]["denominator"]["not_applicable_reason"]
    assert doc["verdict"] == "VACUOUS_PASS", doc["verdict"]
    assert "0 two-node (coupling) *CAP entries" not in reason, reason
    assert "1 two-node (coupling) *CAP" in reason, reason
    assert "single net" in reason, reason
    assert doc["summary"]["denominator"]["details"]["coupling_caps"] == 1


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
    r, doc = _run(proj)
    assert "SPEF_NO_NET_RECORDS" not in _categories(doc), doc["findings"]
    assert r.returncode == G.RC_VACUOUS, (r.returncode, doc["verdict"])
    assert doc["verdict"] == "VACUOUS_PASS"
    assert "*R_NET" in doc["summary"]["denominator"]["not_applicable_reason"]


def test_the_two_gates_in_this_change_agree_about_the_same_bytes(tmp_path):
    """Cross-gate control: no artefact may be certified by one half of this
    change and called the wrong file by the other. Run both over the same four
    SPEFs; wherever `spef_extraction_check` reports nets, the SI gate must not
    raise SPEF_NO_NET_RECORDS."""
    import spef_extraction_check as S
    for name, text in (("coupled", _SPEF_COUPLED),
                       ("grounded", _SPEF_GROUNDED_ONLY),
                       ("rnet", _SPEF_R_NET_ONLY),
                       ("intra", _SPEF_INTRA_NET_COUPLING)):
        d = tmp_path / name
        d.mkdir()
        f = d / "x.spef"
        f.write_text(text)
        facts = S.scan_spef(f)
        has_nets = bool(facts["d_nets"] or facts["r_nets"])
        proj = _project(d, spef_text=text, setup_bounded=text,
                        hold_bounded=text)
        _, doc = _run(proj)
        raised = "SPEF_NO_NET_RECORDS" in _categories(doc)
        assert not (has_nets and raised), (
            f"{name}: spef_extraction_check sees "
            f"{facts['d_nets']} *D_NET / {facts['r_nets']} *R_NET, "
            f"si_mcf_sta_check calls it the wrong artefact")



def test_d1_a_genuine_fold_still_signs_off(tmp_path):
    """CONTROL, green on origin/main too, and it is meant to be: the fix must
    not move a real coupled+folded run off its PASS."""
    s, h = _bounded_from_emitter(_SPEF_COUPLED)
    proj = _project(tmp_path, spef_text=_SPEF_COUPLED,
                    setup_bounded=s, hold_bounded=h)
    r, doc = _run(proj)
    assert r.returncode == 0, (r.returncode, doc["findings"])
    assert doc["verdict"] == "PASS"


def test_a_genuine_fold_discloses_a_non_zero_denominator(tmp_path):
    s, h = _bounded_from_emitter(_SPEF_COUPLED)
    proj = _project(tmp_path, spef_text=_SPEF_COUPLED,
                    setup_bounded=s, hold_bounded=h)
    _, doc = _run(proj)
    denom = doc["summary"]["denominator"]
    assert denom["examined"] > 0, denom
    assert denom["considered"] >= denom["examined"], denom
    assert denom["not_applicable_reason"] == ""


def test_d1_a_dropped_fold_still_fails(tmp_path):
    """CONTROL, green on origin/main too: the rule the gate was written for
    must still fire. A vacuous tier that swallowed real FAILs would be worse
    than the defect."""
    cheat, _ = M.rewrite_spef_folded(_SPEF_COUPLED, {"*1": 0.0, "*2": 0.0},
                                     "setup")
    _, h = _bounded_from_emitter(_SPEF_COUPLED)
    proj = _project(tmp_path, spef_text=_SPEF_COUPLED,
                    setup_bounded=cheat, hold_bounded=h)
    r, doc = _run(proj)
    assert r.returncode == 1
    assert "FOLD_NOT_APPLIED" in _categories(doc)


def test_a_grounded_only_run_is_never_reported_as_a_failure(tmp_path):
    """The other direction of the same requirement: a legitimate grounded-only
    extraction must not be turned into a defect."""
    proj = _grounded_only_project(tmp_path)
    r, doc = _run(proj)
    assert doc["verdict"] != "FAIL"
    assert doc["summary"]["errors_count"] == 0, doc["findings"]
    assert r.returncode != 1


def test_a_refused_invocation_is_not_credited_as_a_skip(tmp_path):
    """rc 2 now MEANS the disclosed skip, and `flow_compliance_check` credits
    rc 2 as a pass unconditionally. A run that never started must therefore
    not exit 2."""
    r = subprocess.run([sys.executable, str(_PROG),
                        str(tmp_path / "does-not-exist")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == G.RC_FAIL, r.returncode
