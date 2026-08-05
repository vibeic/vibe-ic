#!/usr/bin/env python3
"""A per-corner record must not merge — or MIX — datapoints across the PnR
boundary.

`sta_corner_record_completeness_check` keyed its records on (axis, corner) and
merged every datapoint for that key with `min()`. A PRE-PnR estimate and a
post-route SPEF measurement of the SAME corner are two measurements of two
different things, so the merge reported the pre-layout number as the corner's
SIGN-OFF slack — wrong by as much as the resizer is effective.

Measured on a two-report fixture: a corner whose post-route setup slack is
-0.50 ns was reported as -50.00 ns, a 100x error, on a row that cited BOTH
reports as its source.

The FIRST shape of the fix resolved PER FIELD, and that was wrong twice over —
both measured on one fixture, both fixed here, both pinned below:

  * it published a cross-PnR MIXTURE: a post-route `setup_wns_ns` of +1.75 on
    the same row as a pre-layout `tns_ns` of -9000.00. Labelling a mixture is
    not removing it — every consumer reads the number, not the label.
  * it let the whole-run BLOCKING verdict go FAIL(exit 1) -> PASS(exit 0) on a
    GOVERNING hold number the gate itself labelled `PRE_LAYOUT`.

So the contract is ONE ROW, ONE BASIS, and the stamp is read through
`_sta_basis` — the single reader in this tree — never through a local copy of
its regex, which diverged on 7 of 18 stamp spellings, every divergence in the
promote-to-sign-off direction.

The rules here are the contract, and the REVERSE cases are the load-bearing
half. Each of the five over-corrections at the bottom of this file is a way the
fix could have been written that passes every forward test and breaks the
corpus: demote anything stamped, let the PATH decide the basis, prefer the
number that passes, fail every pre-PnR-stage run, or label a healthy run.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "sta_corner_record_completeness_check.py"
STA = "phase3/stage3/sta/"

# A post-route multi-corner OCV report. The flow's emitter stamps no
# STA_BASIS on this one; its sections carry the SPEF in the header.
OCV_VIOLATES = (
    "=== SETUP corner: process=SS liberty=/pdk/lib/slow.lib, SPEF=top.spef ===\n"
    "worst slack max -0.50\n"
    "tns max -1.00\n"
)
OCV_MEETS = (
    "=== SETUP corner: process=SS liberty=/pdk/lib/slow.lib, SPEF=top.spef ===\n"
    "worst slack max 1.75\n"
    "tns max 0.00\n"
)
# A pre-layout sweep report. This one DISCLOSES ITS OWN BASIS, and that
# self-disclosure is the only thing the fix keys on.
PRELAYOUT_VIOLATES = (
    "Startpoint: ff1\n"
    "          -50.00   slack (VIOLATED)\n"
    "tns max -9000.00\n"
    "wns max -50.00\n"
    "STA_BASIS: PRE_LAYOUT_ESTIMATE\n"
    "STA_BASIS_NOTE: PRE-PnR netlist, NO parasitics. NOT post-route sign-off.\n"
)
PRELAYOUT_MEETS = (
    PRELAYOUT_VIOLATES.replace("-50.00", "5.00").replace("-9000.00", "0.00")
)


def _invoke(tmp_path, files):
    proj = tmp_path / "project"
    proj.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    out = proj / "out.json"
    res = subprocess.run([sys.executable, str(PROG), ".", "--json", str(out)],
                         cwd=str(proj), capture_output=True, text=True, timeout=60)
    doc = json.loads(out.read_text()) if out.exists() else {}
    return res, doc


def _run(tmp_path, files):
    res, doc = _invoke(tmp_path, files)
    rows = {f"{c['axis']}:{c['corner']}": c for c in doc.get("corners", [])}
    return res.returncode, rows


def _run_full(tmp_path, files):
    """The whole verdict document, for the rules that are about the RUN."""
    res, doc = _invoke(tmp_path, files)
    doc["_rc"] = res.returncode
    return doc


def test_signoff_supersedes_prelayout_for_the_same_corner(tmp_path):
    """FORWARD: the sign-off datapoint is the one the corner row reports."""
    rc, rows = _run(tmp_path, {STA + "sta_mcorner_ocv.rpt": OCV_VIOLATES,
                               STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    ss = rows["process:SS"]
    assert ss["setup_wns_ns"] == -0.50, (
        "the corner's sign-off setup slack must come from the post-route "
        f"report, not the pre-layout estimate; got {ss['setup_wns_ns']}")
    # Still a violation: correcting the number must not clear the finding.
    assert rc == 1


def test_superseded_prelayout_value_is_disclosed_not_discarded(tmp_path):
    """The pre-layout estimate stays ON the row. A silent correction is a
    different defect from the one being fixed."""
    _, rows = _run(tmp_path, {STA + "sta_mcorner_ocv.rpt": OCV_VIOLATES,
                              STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    ss = rows["process:SS"]
    assert ss["basis_used"]["setup_wns_ns"] == "SIGNOFF"
    assert ss["pre_layout_superseded_ns"]["setup_wns_ns"] == -50.00


def test_prelayout_ONLY_project_is_unchanged(tmp_path):
    """REVERSE — the load-bearing case, and it asserts BEHAVIOUR ONLY.

    With no sign-off datapoint available the pre-layout number is still the
    record and still violates. This test must pass against the PRE-FIX file
    too: that is what makes it a control rather than a restatement of the fix.
    """
    rc, rows = _run(tmp_path, {STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    assert rows["process:SS"]["setup_wns_ns"] == -50.00
    assert rc == 1


def test_prelayout_only_row_is_labelled_prelayout(tmp_path):
    """The disclosure half of the case above, kept SEPARATE so the control
    above stays a pure behaviour assertion."""
    _, rows = _run(tmp_path, {STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    assert rows["process:SS"]["basis_used"]["setup_wns_ns"] == "PRE_LAYOUT"


def test_prelayout_only_and_meeting_is_unchanged(tmp_path):
    """REVERSE — the fix must not invent a violation either."""
    _, rows = _run(tmp_path, {STA + "per_corner/sta_SS.rpt": PRELAYOUT_MEETS})
    assert rows["process:SS"]["setup_wns_ns"] == 5.00


def test_signoff_only_project_is_unchanged(tmp_path):
    """REVERSE — an unstamped/post-route report keeps exactly its old standing."""
    rc, rows = _run(tmp_path, {STA + "sta_mcorner_ocv.rpt": OCV_VIOLATES})
    assert rows["process:SS"]["setup_wns_ns"] == -0.50
    assert rc == 1


def test_a_violating_signoff_corner_is_never_cleared_by_the_fix(tmp_path):
    """REVERSE — the anti-greening case. When BOTH bases violate, the corner
    stays violated. Tightening a filter until the count reaches zero is how a
    real defect gets swallowed; this is the test that would catch it."""
    rc, rows = _run(tmp_path, {STA + "sta_mcorner_ocv.rpt": OCV_VIOLATES,
                               STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    assert rows["process:SS"]["setup_wns_ns"] < 0
    assert rc == 1


def test_a_row_fed_two_bases_publishes_only_the_post_route_one(tmp_path):
    """A row fed a pre-layout SETUP and a post-route HOLD publishes the HOLD
    and NOT the setup.

    This test previously asserted the opposite — that the row carried both
    numbers and merely LABELLED which side each came from. That was the defect
    one field over: a labelled cross-PnR mixture is still a cross-PnR mixture,
    and every downstream consumer of `setup_wns_ns` reads the number, not the
    label. Per-FIELD resolution is gone; a row resolves from ONE pool.
    """
    ocv_hold = ("=== HOLD corner: process=SS liberty=/pdk/lib/fast.lib, "
                "SPEF=top.spef ===\nworst slack min 0.20\ntns max 0.00\n")
    _, rows = _run(tmp_path, {STA + "sta_mcorner_ocv.rpt": ocv_hold,
                              STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    ss = rows["process:SS"]
    assert ss["hold_wns_ns"] == 0.20, "the post-route hold is the row's hold"
    assert ss["setup_wns_ns"] is None, (
        "the pre-layout -50.00 must NOT be published as this row's setup "
        f"slack beside a post-route hold; got {ss['setup_wns_ns']}")


def test_the_excluded_pre_layout_number_is_disclosed_not_discarded(tmp_path):
    """The disclosure companion: refusing to PUBLISH the pre-layout number is
    not the same as losing it. It stays on the row and in the run-level list.
    A silent drop would be a worse record than the merge this replaced."""
    ocv_hold = ("=== HOLD corner: process=SS liberty=/pdk/lib/fast.lib, "
                "SPEF=top.spef ===\nworst slack min 0.20\ntns max 0.00\n")
    doc = _run_full(tmp_path, {STA + "sta_mcorner_ocv.rpt": ocv_hold,
                               STA + "per_corner/sta_SS.rpt": PRELAYOUT_VIOLATES})
    ss = {f"{c['axis']}:{c['corner']}": c for c in doc["corners"]}["process:SS"]
    assert ss["pre_layout_only_ns"]["setup_wns_ns"] == -50.00
    assert ss["pre_layout_sources"] == [STA + "per_corner/sta_SS.rpt"]
    run_level = {(e["corner"], e["field"]): e
                 for e in doc["pre_layout_per_corner_excluded"]}
    assert run_level[("SS", "setup_wns_ns")]["pre_layout_ns"] == -50.00


# ════════════════════════════════════════════════════════════════════════════
# The three findings the outgoing gatekeeper measured on this change, and the
# over-corrections each fix could turn into. Every fixture below is pure
# grammar with invented corner names — no design, no PDK, no vendor.
# ════════════════════════════════════════════════════════════════════════════

_DRV_OK = ("SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew "
           "min_pulse_width max_capacitance\n")
_LIB = "/pdk/lib/cells__ss_100C_1v60.lib"

# The flow declares SS as BOTH the setup and the hold corner: a single-corner
# sign-off stance, which is what makes the hold number GOVERNING.
_STANCE_SS_BOTH = json.dumps({"setup_process_corner": "SS",
                              "hold_process_corner": "SS",
                              "corner_library_resolution": {"SS": _LIB}})

# A post-route report that carries SETUP only, and MEETS.
_POST_ROUTE_SETUP_ONLY_MEETS = (
    "# Multi-corner OCV STA\n"
    f"# corner_liberty: SS={_LIB}\n"
    "# STA_BASIS: POST_ROUTE_SPEF\n"
    f"=== SETUP corner: process=SS liberty={_LIB}, SPEF=top.spef ===\n"
    "worst slack max 1.75\n" + _DRV_OK)
# A post-route report that carries BOTH roles and meets both.
_POST_ROUTE_BOTH_MEET = (
    "# Multi-corner OCV STA\n"
    f"# corner_liberty: SS={_LIB}\n"
    "# STA_BASIS: POST_ROUTE_SPEF\n"
    f"=== SETUP corner: process=SS liberty={_LIB}, SPEF=top.spef ===\n"
    "worst slack max 1.75\ntns max 0.00\n"
    f"=== HOLD corner: process=SS liberty={_LIB}, SPEF=top.spef ===\n"
    "worst slack min 0.31\n" + _DRV_OK)
# The pre-layout estimate of the SAME corner: it is the only thing in the tree
# carrying a HOLD number, and that hold number MEETS.
_PRE_LAYOUT_HOLD_MEETS = (
    "STA_BASIS: PRE_LAYOUT_ESTIMATE\n"
    "STA_BASIS_NOTE: PRE-PnR netlist, NO parasitics. NOT post-route sign-off.\n"
    "wns max -50.00\ntns max -9000.00\nworst slack min 0.20\n")


def _b1_fixture(post_route=_POST_ROUTE_SETUP_ONLY_MEETS,
                pre_layout=_PRE_LAYOUT_HOLD_MEETS):
    files = {"reports/phase3/mcorner_ocv_stance.json": _STANCE_SS_BOTH,
             STA + "sta_mcorner_ocv.rpt": post_route}
    if pre_layout is not None:
        files[STA + "per_corner/sta_SS.rpt"] = pre_layout
    return files


# ── BLOCKING 1 — the verdict may not go green on a pre-layout number ────────
def test_the_verdict_does_not_go_green_on_a_pre_layout_governing_number(tmp_path):
    """The measured shape, exactly.

    Sign-off SETUP is promoted to +1.75 and MEETS. The corner's HOLD number
    exists only in a report stamped PRE_LAYOUT, and it also "meets" (+0.20).
    Under per-field resolution the run's BLOCKING verdict went FAIL(exit 1) ->
    PASS(exit 0), and the number that GOVERNED — the worst on the row, the one
    that decided MET — was the +0.20 the gate itself labelled PRE_LAYOUT.

    A sign-off gate must not go green on a number from the wrong side of PnR.
    """
    doc = _run_full(tmp_path, _b1_fixture())
    assert doc["_rc"] == 1, (
        "the run must not exit 0 while its governing hold number is a "
        f"pre-layout estimate; verdict={doc.get('verdict')}")
    row = doc["corners"][0]
    assert row["hold_wns_ns"] is None, (
        "the pre-layout +0.20 must not be published as this sign-off corner's "
        f"hold slack; got {row['hold_wns_ns']}")


def test_a_signoff_role_backed_only_by_a_pre_layout_estimate_is_blocking(tmp_path):
    """...and it FAILs under its own rule, naming what is actually wrong.

    'carries no worst hold slack' would send the reader hunting for a report
    that is right there in the tree. The finding has to say the number exists
    and is from the wrong side of place-and-route.
    """
    doc = _run_full(tmp_path, _b1_fixture())
    assert "R2_SIGNOFF_ROLE_PRE_LAYOUT_ONLY" in doc["rules_violated"]
    said = " ".join(doc["reasons"])
    assert "PRE-LAYOUT estimate (+0.200 ns" in said, said


# ── BLOCKING 3 — no NEW cross-PnR mixture in any published row ──────────────
def test_tns_is_never_published_from_the_other_side_of_pnr(tmp_path):
    """`tns_ns` is the field per-field resolution mixed in silence.

    Sign-off answers setup and not TNS; the pre-layout report answers TNS. The
    published row carried a post-route setup of +1.75 beside a pre-layout TNS
    of -9000.00 — a cross-PnR mixture in a published row, which is the very
    defect this change exists to prevent, re-entering one field over.
    """
    doc = _run_full(tmp_path, _b1_fixture())
    row = doc["corners"][0]
    assert row["setup_wns_ns"] == 1.75
    assert row["tns_ns"] is None, (
        "a pre-layout TNS must not be published beside a post-route setup "
        f"slack on one row; got {row['tns_ns']}")
    assert row["pre_layout_only_ns"]["tns_ns"] == -9000.00   # disclosed


def test_no_published_row_ever_carries_two_bases(tmp_path):
    """The structural invariant, asserted over EVERY row rather than over the
    one field that happened to be noticed.

    A guard written per field is a guard that the next field walks around.
    `basis_used` may name at most one basis per row, and it must agree with
    the row-level `row_basis`.
    """
    doc = _run_full(tmp_path, _b1_fixture())
    for row in doc["corners"]:
        bases = set((row.get("basis_used") or {}).values())
        assert len(bases) <= 1, (
            f"corner {row['corner']} publishes numbers from {sorted(bases)} "
            f"on ONE row: {row}")
        if bases:
            assert bases == {row["row_basis"]}, row


# ── BLOCKING 2 — ONE reader of the stamp, prefix-normalised ─────────────────
def test_the_stamp_reader_is_the_shared_one_over_its_whole_token_table():
    """`report_basis` must agree with `_sta_basis` on EVERY spelling the one
    token table knows, not just on the literal `PRE_LAYOUT` prefix.

    MEASURED: the deleted byte-copy of the regex agreed on 11 of the 18 stamp
    spellings the table generates and disagreed on SEVEN — `PRE_PNR`,
    `PREPNR`, `PRELAYOUT`, `PRE_ROUTE`, `PRE_FLOORPLAN` and their dashed forms
    — EVERY disagreement in the promote-to-sign-off direction, i.e. a report
    that had disclosed itself as pre-layout being taken as sign-off evidence.
    The missing step is PREFIX NORMALISATION against the shared table.
    """
    sys.path.insert(0, str(PROG.parent))
    import importlib
    import _sta_basis                                    # noqa: E402
    gate = importlib.import_module("sta_corner_record_completeness_check")

    checked = 0
    for basis, tokens in _sta_basis.BASIS_TOKENS.items():
        for tok in tokens:
            stamp = f"# STA_BASIS: {tok.replace('-', '_').upper()}_ESTIMATE\n"
            want = "PRE_LAYOUT" if basis == "PRE_LAYOUT" else "SIGNOFF"
            got = gate.report_basis(stamp)
            assert got == want, (
                f"stamp {stamp.strip()!r} names the {basis} side of PnR but "
                f"this gate read it as {got}")
            checked += 1
    assert checked == sum(len(t) for t in _sta_basis.BASIS_TOKENS.values())

    # ...and there is no SECOND compiled reader left in this program to drift.
    assert not hasattr(gate, "_STA_BASIS_STAMP_RE"), (
        "a private stamp regex is back in this program; the single reader is "
        "_sta_basis.STAMP_RE and a corrected copy diverges again the next time "
        "the emitter grows a suffix — it has grown one twice")


def test_a_pre_pnr_stamped_report_is_demoted_like_any_other_pre_layout(tmp_path):
    """The divergence above, as OBSERVED VERDICT BEHAVIOUR rather than as a
    unit answer: a report stamped `PRE_PNR_ESTIMATE` is a pre-layout report,
    so its -50.00 may not stand as a sign-off corner's setup slack."""
    pre_pnr = _PRE_LAYOUT_HOLD_MEETS.replace("PRE_LAYOUT_ESTIMATE",
                                             "PRE_PNR_ESTIMATE")
    doc = _run_full(tmp_path, _b1_fixture(pre_layout=pre_pnr))
    row = doc["corners"][0]
    assert row["setup_wns_ns"] == 1.75, (
        "a PRE_PNR-stamped report is pre-layout; its -50.00 must not be "
        f"merged into the sign-off setup number; got {row['setup_wns_ns']}")
    assert row["hold_wns_ns"] is None
    assert doc["_rc"] == 1


# ── over-corrections: the reverse cases that must STILL pass ───────────────
def test_a_post_route_stamped_report_is_NOT_demoted(tmp_path):
    """OVER-CORRECTION 1 — demoting anything that carries a stamp.

    `POST_ROUTE_SPEF` is a SUFFIXED value the emitter actually ships. A reader
    that demoted it, or that failed to normalise it and fell through to a
    default, would gut every post-route run in the corpus.
    """
    doc = _run_full(tmp_path, _b1_fixture(post_route=_POST_ROUTE_BOTH_MEET,
                                          pre_layout=None))
    row = doc["corners"][0]
    assert (row["setup_wns_ns"], row["hold_wns_ns"]) == (1.75, 0.31)
    assert row["row_basis"] == "SIGNOFF"
    assert doc["_rc"] == 0 and doc["verdict"] == "PASS"


def test_an_unstamped_report_is_NOT_demoted_by_the_path_it_sits_under(tmp_path):
    """OVER-CORRECTION 2 — letting the PATH decide the basis.

    This repo has already measured that trap once: `_scope_declared_basis` read
    tokens out of directory names, and a checkout under a directory containing
    `post_route` made every scope look post-route. The basis is a property of
    the REPORT'S OWN DISCLOSURE. An unstamped report living under a directory
    named `pre_layout` keeps exactly the standing it has today.
    """
    files = {"reports/phase3/mcorner_ocv_stance.json": _STANCE_SS_BOTH,
             STA + "sta_mcorner_ocv.rpt":
                 _POST_ROUTE_BOTH_MEET.replace(
                     "# STA_BASIS: POST_ROUTE_SPEF\n", ""),
             "pre_layout/estimates/notes.txt": "pre_layout scratch\n"}
    doc = _run_full(tmp_path, files)
    row = doc["corners"][0]
    assert (row["setup_wns_ns"], row["hold_wns_ns"]) == (1.75, 0.31)
    assert row["row_basis"] == "SIGNOFF"
    assert doc["_rc"] == 0


def test_the_basis_rule_never_CLEARS_a_real_post_route_violation(tmp_path):
    """OVER-CORRECTION 3 — "prefer the number that passes".

    A fix aimed at "stop the pre-layout number governing" that reached for the
    BETTER number instead of the POST-ROUTE one would clear a real violation.
    Post-route setup VIOLATES at -0.50; the pre-layout estimate meets at +5.00.
    The corner stays violated and the run stays FAIL.
    """
    post_viol = _POST_ROUTE_BOTH_MEET.replace(
        "worst slack max 1.75", "worst slack max -0.50")
    doc = _run_full(tmp_path, _b1_fixture(post_route=post_viol,
                                          pre_layout=PRELAYOUT_MEETS))
    row = doc["corners"][0]
    assert row["setup_wns_ns"] == -0.50, row
    assert doc["_rc"] == 1
    assert "R3_SIGNOFF_CORNER_VIOLATION" in doc["rules_violated"]


def test_a_pre_layout_ONLY_signoff_corner_is_not_FAILED_but_is_not_a_bare_PASS(
        tmp_path):
    """OVER-CORRECTION 4 — failing every run that has not reached post-route.

    A corner reported ONLY by pre-layout reports keeps its numbers and is NOT a
    FAIL: a run that has legitimately not reached post-route STA cannot do
    better, and failing it fabricates a violation on every such run — the same
    error the R1 nominal exemption exists to avoid. But it may not read as
    sign-off closure either, so the verdict STRING carries the limitation,
    exactly as SINGLE_CORNER_ONLY does.
    """
    files = {"reports/phase3/mcorner_ocv_stance.json": _STANCE_SS_BOTH,
             STA + "per_corner/sta_SS.rpt":
                 "STA_BASIS: PRE_LAYOUT_ESTIMATE\n"
                 "wns max 5.00\ntns max 0.00\nworst slack min 0.20\n"}
    doc = _run_full(tmp_path, files)
    row = doc["corners"][0]
    assert (row["setup_wns_ns"], row["hold_wns_ns"]) == (5.00, 0.20), row
    assert row["row_basis"] == "PRE_LAYOUT"
    assert doc["_rc"] == 0, "a pre-PnR-stage run is not a fabricated failure"
    assert doc["verdict"] == "PRE_LAYOUT_ONLY", (
        f"must not read as sign-off closure; got {doc['verdict']}")


def test_a_clean_post_route_run_is_still_a_bare_PASS(tmp_path):
    """OVER-CORRECTION 5 — the limitation label leaking onto healthy runs.

    A run whose sign-off corners are reported by post-route reports and which
    meets timing is a PASS, with no qualifier and nothing excluded. If this
    ever reads PRE_LAYOUT_ONLY the label has stopped meaning anything.
    """
    doc = _run_full(tmp_path, _b1_fixture(post_route=_POST_ROUTE_BOTH_MEET,
                                          pre_layout=None))
    assert doc["verdict"] == "PASS" and doc["_rc"] == 0
    assert doc["pre_layout_only"] is False
    assert doc["pre_layout_per_corner_excluded"] == []
