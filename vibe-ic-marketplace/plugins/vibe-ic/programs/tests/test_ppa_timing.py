#!/usr/bin/env python3
"""The timing lane: per-VIEW rows out of STA artefacts.

Each test here is the negative of a way this could quietly go wrong. The ones
that matter most are not "does it parse" — they are the ones that would still
pass if the module started publishing a number nothing measured, because that
is the failure this lane exists to prevent and it is invisible from the output
of a single run.
"""
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import canonical_json as cj          # noqa: E402
from _ppa import timing                        # noqa: E402
from _ppa.backends import opensta              # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]

# ── report bodies, in the dialects `phase3_one_shot_runner.py` really emits ──

MULTICORNER = """\
# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
# SETUP corner: max-RC   HOLD corner: min-RC
# corners_available: max,min,nom
# corner_liberty: max=/pdks/x_fd_sc_hd__ss_100C_1v60.lib
# corner_liberty: min=/pdks/x_fd_sc_hd__ff_n40C_1v95.lib
# distinct_corner_libraries: 2 across 2 reported corner(s)
=== SETUP (max-RC corner, SPEF=max, liberty=/pdks/x_fd_sc_hd__ss_100C_1v60.lib) ===
worst slack max -1.71
tns max -12.34
Startpoint: u_a/q (rising edge-triggered flip-flop clocked by clk)
Endpoint: u_b/d (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max
  -1.71   slack (VIOLATED)
SIGNOFF_WORST_PATHS_REPORTED path_delay=max group_path_count=3
=== HOLD (min-RC corner, SPEF=min, liberty=/pdks/x_fd_sc_hd__ff_n40C_1v95.lib) ===
worst slack min 0.54
tns min 0.00
"""

#: The exact shape of the three published reports that founded this defect:
#: nothing was analysed, and the summary lines read 0.00 BECAUSE of that.
NO_PATHS = """\
=== HOLD (min-RC corner, SPEF=min, liberty=/pdks/x_fd_sc_hd__ff_n40C_1v95.lib) ===
No paths found.
tns min 0.00
wns min 0.00
worst slack min INF
"""

SINGLE_CORNER_STAMPED = """\
tns max 0.00
wns max 0.00
worst slack max 5.24
STA_BASIS: POST_ROUTE_SPEF
STA_SIGNOFF_CORNER: SS
STA_BASIS_LIBERTY: /pdks/x_fd_sc_hd__ss_100C_1v60.lib
STA_SIGNOFF_CORNER_COUNT: 1
"""


def _project(tmp_path, reports=None, stances=None, pvt=None):
    """A project tree with STA artefacts where the flow really puts them."""
    sta = tmp_path / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    for name, body in (reports or {}).items():
        (sta / name).write_text(body)
    rp = tmp_path / "reports" / "phase3"
    rp.mkdir(parents=True)
    for name, obj in (stances or {}).items():
        (rp / name).write_text(json.dumps(obj))
    if pvt is not None:
        c = tmp_path / "phase2" / "stage2" / "constraints"
        c.mkdir(parents=True)
        (c / "pvt_matrix.json").write_text(json.dumps(pvt))
    return tmp_path


def _by_metric(rows, metric, **scope):
    out = []
    for r in rows:
        if r["metric"] != metric:
            continue
        if all(r["scope"].get(k) == v for k, v in scope.items()):
            out.append(r)
    return out


# ── NEGATIVE: the fixture that must come out RED if the rule is removed ─────

def test_a_view_that_analysed_no_paths_is_not_a_passing_row(tmp_path):
    """THE founding defect of this corpus, in one assertion.

    `worst_slack` starts at infinity and takes the min over analysed paths, so
    it is still infinity exactly when the path set was EMPTY. The `wns 0.00` and
    `tns 0.00` printed beside it are `min(0, INF)` — arithmetic ABOUT infinity.
    Publishing them as met +0.000 ns is "an unreported view is
    indistinguishable from a met one" reproduced inside the reader.
    """
    proj = _project(tmp_path, {"sta_mcorner_ocv.rpt": NO_PATHS})
    rows, _ = timing.timing_rows(proj)

    for metric in ("timing.hold.worst_slack_ns", "timing.hold.wns_ns",
                   "timing.hold.tns_ns"):
        got = _by_metric(rows, metric)
        assert got, "%s must appear as a row, not be omitted" % metric
        assert all(r["status"] == timing.NOT_MEASURED for r in got), \
            "%s was published as measured out of a report that analysed " \
            "nothing: %r" % (metric, got)
        assert all("value" not in r for r in got), \
            "a NOT_MEASURED row must carry no value at all -- not 0, not null"
    assert not [r for r in rows if r["status"] == timing.MEASURED]


def test_a_negative_summary_beside_the_sentinel_is_never_withheld(tmp_path):
    """The mirror, and the more dangerous direction to get wrong.

    A NEGATIVE wns cannot be an echo of infinity, so it is real evidence of a
    violation. Suppressing it would be the one error worse than publishing a
    phantom pass: this module would be hiding a miss.
    """
    body = NO_PATHS.replace("tns min 0.00", "tns min -3.25")
    proj = _project(tmp_path, {"sta_mcorner_ocv.rpt": body})
    rows, _ = timing.timing_rows(proj)
    tns = _by_metric(rows, "timing.hold.tns_ns")
    assert len(tns) == 1
    assert tns[0]["status"] == timing.MEASURED
    assert tns[0]["value"] == -3.25


# ── the matrix must survive ────────────────────────────────────────────────

def test_the_matrix_is_not_collapsed_to_one_row(tmp_path):
    """A design has a timing MATRIX, not a WNS.

    Collapsing it is how a multi-corner claim becomes a single-corner claim
    without anyone deciding to make it: the slow-corner row is simply not in
    the table any more.
    """
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER})
    rows, _ = timing.timing_rows(proj)

    setup = _by_metric(rows, "timing.setup.worst_slack_ns", check="setup")
    hold = _by_metric(rows, "timing.hold.worst_slack_ns", check="hold")
    assert len(setup) == 1 and len(hold) == 1
    assert setup[0]["value"] == -1.71
    assert hold[0]["value"] == 0.54
    # and the two rows are DIFFERENT views, not one number wearing two names
    assert setup[0]["scope"]["process"] == "ss"
    assert hold[0]["scope"]["process"] == "ff"
    assert setup[0]["scope"]["rc_corner"] == "max"
    assert hold[0]["scope"]["rc_corner"] == "min"
    assert setup[0]["scope"] != hold[0]["scope"]


def test_every_row_carries_all_eight_scope_keys(tmp_path):
    """A number without its scope cannot be compared with anything.

    All eight keys are always present: an omitted key and a null key are
    different claims to a reader, and only one of them is true.
    """
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER,
                               "sta_spef_based.rpt": SINGLE_CORNER_STAMPED})
    rows, _ = timing.timing_rows(proj)
    assert rows
    for r in rows:
        assert set(r["scope"]) == set(timing._SCOPE_KEYS), r
        assert r["schema"] == "vibeic.ppa.metric.v1"
        assert r["status"] in (timing.MEASURED, timing.NOT_MEASURED,
                               timing.INVALID)
        assert "source" in r and r["source"]["tool"] == "opensta"


def test_the_per_view_metric_set_is_complete_not_absent(tmp_path):
    """An omitted row and a met row look the same to anything scanning for
    violations. The multi-corner emitter never calls `report_wns`, so wns must
    appear as NOT_MEASURED rather than vanish."""
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER})
    rows, _ = timing.timing_rows(proj)
    wns = _by_metric(rows, "timing.setup.wns_ns", check="setup")
    assert len(wns) == 1
    assert wns[0]["status"] == timing.NOT_MEASURED
    assert "not_reported" in wns[0]["reason"]


def test_wns_is_never_derived_from_worst_slack(tmp_path):
    """OpenSTA's `wns` is `min(0, worst_slack)`. Computing it here would make a
    DERIVED number wear a MEASURED status, and §3 says hash the value you
    PARSED."""
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER})
    rows, _ = timing.timing_rows(proj)
    for r in _by_metric(rows, "timing.setup.wns_ns"):
        assert r["status"] != timing.MEASURED
        assert "value" not in r


# ── scope must be read, never invented ─────────────────────────────────────

def test_the_stage_is_never_guessed_when_the_report_does_not_stamp_it(tmp_path):
    """MEASURED on this checkout: the two MULTI-corner sign-off emitters stamp
    no `STA_BASIS`, while the single-corner one does. Inferring a stage from a
    filename would let a pre-layout estimate be compared against sign-off
    evidence, which is exactly what `scope` exists to stop."""
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER})
    rows, _ = timing.timing_rows(proj)
    assert rows
    for r in rows:
        assert r["scope"]["stage"] is None
        assert "stage" in r.get("scope_gaps", {}), \
            "an absent stage must say WHY it is absent"


def test_a_stamped_report_yields_its_stage_and_its_corner(tmp_path):
    proj = _project(tmp_path, {"sta_spef_based.rpt": SINGLE_CORNER_STAMPED})
    rows, _ = timing.timing_rows(proj)
    ws = _by_metric(rows, "timing.setup.worst_slack_ns")
    assert len(ws) == 1
    assert ws[0]["value"] == 5.24
    assert ws[0]["scope"]["stage"] == "post_route_extracted"
    assert ws[0]["scope"]["process"] == "ss"
    assert ws[0]["scope"]["voltage_v"] == 1.60
    assert ws[0]["scope"]["temperature_c"] == 100.0


def test_scope_case_does_not_split_one_view_in_two(tmp_path):
    """The process stance spells `SS`; the liberty stem spells `ss`. Under §2
    those would be two incomparable views of one corner."""
    proj = _project(tmp_path, {"sta_spef_based.rpt": SINGLE_CORNER_STAMPED})
    rows, _ = timing.timing_rows(proj)
    assert all(r["scope"]["process"] in (None, "ss") for r in rows), \
        [r["scope"]["process"] for r in rows]


def test_the_mode_is_not_chosen_when_the_run_declares_several(tmp_path):
    """The reports carry no mode marker. With two declared modes, picking one
    would be invention."""
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER},
                    pvt={"modes": ["functional", "scan"]})
    rows, _ = timing.timing_rows(proj)
    assert all(r["scope"]["mode"] is None for r in rows)
    assert any("mode" in r.get("scope_gaps", {}) for r in rows)

    proj2 = _project(tmp_path / "one", {"sta_spef_multicorner.rpt": MULTICORNER},
                     pvt={"modes": ["functional"]})
    rows2, _ = timing.timing_rows(proj2)
    assert all(r["scope"]["mode"] == "functional" for r in rows2)


# ── declared-but-unreported, and its false-positive twin ───────────────────

def test_a_declared_view_with_no_report_at_all_becomes_a_not_measured_row(tmp_path):
    """A view the run was CONFIGURED to analyse and never did is the defect
    this lane exists to make visible. It gets a row, not a silence."""
    proj = _project(
        tmp_path, {"sta_spef_based.rpt": SINGLE_CORNER_STAMPED},
        stances={"mcorner_ocv_stance.json":
                 {"setup_process_corner": "SS", "hold_process_corner": "FF"}})
    rows, _ = timing.timing_rows(proj)
    hold = [r for r in rows if r["scope"]["check"] == "hold"
            and r["scope"]["process"] == "ff"]
    assert len(hold) == 1
    assert hold[0]["status"] == timing.NOT_MEASURED
    assert "declared_but_not_reported" in hold[0]["reason"]


def test_a_reported_view_is_never_called_declared_but_not_reported(tmp_path):
    """The false-positive twin, and a bug this module actually had.

    A hold corner that WAS analysed and found no paths already carries a row
    saying exactly that. A second row claiming it was never reported would be
    FALSE -- and it is the kind of false finding that gets a whole gate ignored.
    """
    proj = _project(
        tmp_path, {"sta_mcorner_ocv.rpt": NO_PATHS},
        stances={"multi_corner_spef_stance.json":
                 {"setup_corner": "max", "hold_corner": "min"}})
    rows, _ = timing.timing_rows(proj)
    false_rows = [r for r in rows
                  if "declared_but_not_reported" in (r.get("reason") or "")
                  and r["scope"]["check"] == "hold"]
    assert not false_rows, \
        "the min-RC hold view WAS reported; it analysed no paths, and that is " \
        "already on the table with the accurate reason"
    # the control: setup@max really WAS declared and never reported, so that
    # row MUST be there. Without it this test would pass on a module that had
    # simply stopped emitting declared-view rows altogether.
    assert [r for r in rows
            if "declared_but_not_reported" in (r.get("reason") or "")
            and r["scope"]["check"] == "setup"]


def test_availability_is_not_configuration(tmp_path):
    """`corners_available` lists what could be analysed; `nom` is extracted on
    every run and deliberately never analysed, because setup signs off at the
    slow corner and hold at the fast one. Demanding a row for it would fire on
    every healthy run -- the mirror of the defect, and just as useless."""
    proj = _project(
        tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER},
        stances={"multi_corner_spef_stance.json":
                 {"setup_corner": "max", "hold_corner": "min",
                  "corners_extracted": ["max", "min", "nom"]}})
    rows, _ = timing.timing_rows(proj)
    assert not [r for r in rows if r["scope"]["rc_corner"] == "nom"]


# ── number grammar: the two traps already paid for in this repository ──────

def test_the_infinity_sentinel_is_not_scraped_as_the_digit_one():
    """A regex of the shape `-?\\d+(\\.\\d+)?` matches `1` inside `1e+30`.
    That turns "nothing was analysed" into a comfortable +1 ns of slack."""
    r = opensta.parse_report("worst slack max 1e+30\n")
    m = r.sections[0].measurements
    assert len(m) == 1
    assert m[0].no_paths is True
    assert m[0].value is None


@pytest.mark.parametrize("spelling", ["INF", "inf", "Infinity", "1e+30",
                                      "1.0e30", "-1e+30"])
def test_every_infinity_spelling_is_one_case(spelling):
    """The sentinel test is made on the parsed VALUE, not on a spelling, so a
    build that prints a different one needs no change here."""
    r = opensta.parse_report("worst slack max %s\n" % spelling)
    assert r.sections[0].measurements[0].no_paths is True


def test_a_genuine_exponent_value_is_not_truncated():
    """The same regex bug in its other direction: `-1.5e-3` must not become
    -1.5, which is a thousand-fold overstatement of a violation."""
    r = opensta.parse_report("wns max -1.5e-3\n")
    m = [x for x in r.sections[0].measurements if x.kind == "wns"]
    assert len(m) == 1
    assert m[0].value == pytest.approx(-0.0015)
    assert m[0].no_paths is False


def test_voltage_is_not_scraped_from_the_library_family_name():
    """`gf180mcu_fd_sc_mcu7t5v0__ss_125C_4v50.lib` is a 4.50 V corner. The
    family fragment `5v0` looks exactly like a supply voltage, and an
    undelimited search returns 5.0 -- a confident wrong number in a scope."""
    pvt = opensta.parse_liberty_pvt(
        "/pdks/gf180mcu_fd_sc_mcu7t5v0__ss_125C_4v50.lib")
    assert pvt.voltage_v == 4.50
    assert pvt.temperature_c == 125.0
    assert pvt.process == "ss"


@pytest.mark.parametrize("stem,proc,volt,temp", [
    ("sky_fd_sc_hd__ss_100C_1v60.lib", "ss", 1.60, 100.0),
    ("sky_fd_sc_hd__ff_n40C_1v95.lib", "ff", 1.95, -40.0),
    ("sg13g2_stdcell_typ_1p20V_25C.lib", "typ", 1.20, 25.0),
])
def test_both_open_pdk_pvt_spellings_are_read(stem, proc, volt, temp):
    """Two orders, two voltage spellings, and `n` for a negative temperature.
    This is the ONLY place P, V and T exist in this flow -- no JSON carries
    them."""
    pvt = opensta.parse_liberty_pvt("/pdks/" + stem)
    assert (pvt.process, pvt.voltage_v, pvt.temperature_c) == (proc, volt, temp)


def test_an_ambiguous_stem_refuses_rather_than_picking():
    """Two delimited candidates is a stem this cannot read. Picking one would
    put a confident wrong corner condition into a scope, and a wrong scope is
    worse than an absent one -- it makes two incomparable numbers look
    comparable."""
    pvt = opensta.parse_liberty_pvt("/pdks/lib_1v80_ss_100C_1v60.lib")
    assert pvt.voltage_v is None
    assert "ambiguous" in pvt.gaps["voltage_v"]


# ── per-clock rows come only from per-clock evidence ───────────────────────

def test_the_design_wide_worst_is_not_attributed_to_a_clock(tmp_path):
    """`report_worst_slack` is design-wide within a corner. Attributing it to
    whichever clock appears first in the 3-path dump would be fabrication, so
    its `scope.clock` is null -- meaning "aggregate over all clocks", never
    "unknown clock"."""
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER})
    rows, _ = timing.timing_rows(proj)
    for r in _by_metric(rows, "timing.setup.worst_slack_ns"):
        assert r["scope"]["clock"] is None


def test_a_per_clock_row_exists_only_where_a_path_group_names_one(tmp_path):
    """The path blocks are the only per-clock evidence a report has, and they
    are a PARTIAL census -- so they carry their own metric name and can never
    be mistaken for the design-wide worst."""
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER})
    rows, _ = timing.timing_rows(proj)
    per_clock = _by_metric(rows, "timing.setup.worst_path_slack_ns")
    assert len(per_clock) == 1
    assert per_clock[0]["scope"]["clock"] == "clk"
    assert per_clock[0]["value"] == -1.71
    # the HOLD section carries no path dump, so it gets no per-clock row
    assert not _by_metric(rows, "timing.hold.worst_path_slack_ns")


# ── identity ───────────────────────────────────────────────────────────────

def test_a_row_hashes_through_the_one_serializer(tmp_path):
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER})
    rows, _ = timing.timing_rows(proj)
    r = rows[0]
    assert timing.row_digest(r) == cj.digest_of(r)
    assert timing.row_digest(r).startswith("sha256:")


def test_the_source_hash_is_of_the_artefact_bytes(tmp_path):
    """An auditor must be able to reproduce it with `sha256sum`."""
    import hashlib
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER})
    rows, _ = timing.timing_rows(proj)
    want = "sha256:" + hashlib.sha256(
        (proj / "phase3/stage3/sta/sta_spef_multicorner.rpt").read_bytes()
    ).hexdigest()
    assert {r["source"]["sha256"] for r in rows
            if r["source"]["path"]} == {want}


def test_the_row_order_is_stable_across_runs(tmp_path):
    """Row order feeds document identity; an unsorted glob would make one tree
    hash two ways."""
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER,
                               "sta_mcorner_ocv.rpt": NO_PATHS})
    a, _ = timing.timing_rows(proj)
    b, _ = timing.timing_rows(proj)
    assert [timing.row_digest(x) for x in a] == [timing.row_digest(x) for x in b]


# ── VACUOUS: missing input is rc=2 with a marker, never 0 and never 1 ──────

def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "_ppa.timing", *[str(a) for a in args]],
        capture_output=True, text=True,
        env={"PYTHONPATH": str(_PROGRAMS), "PATH": "/usr/bin:/bin",
             "HOME": "/tmp"})


def test_missing_input_is_rc2_with_a_printed_marker(tmp_path):
    """A gate whose declared invocation exits 2 on absent input can never fail,
    and this repository has shipped that twice -- so the 2 is checked here
    against a REAL run of the CLI, not against a return value."""
    empty = tmp_path / "empty"
    empty.mkdir()
    p = _cli(empty)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "[CANNOT CHECK]" in p.stderr
    assert "0 STA artefact" in p.stderr


def test_a_bad_invocation_is_rc3_and_never_a_design_finding(tmp_path):
    """rc=1 is a claim about silicon. A path that does not exist is not one."""
    p = _cli(tmp_path / "nope")
    assert p.returncode == 3, p.stdout + p.stderr
    assert "[REFUSE]" in p.stderr


def test_an_empty_artefact_is_undetermined_not_clean(tmp_path):
    """"I could not read it" and "I read it and it was empty" must never
    produce the same verdict as "I read it and it was fine"."""
    proj = _project(tmp_path, {"sta_spef_based.rpt": ""})
    p = _cli(proj)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "[CANNOT CHECK]" in p.stderr
    rows, _ = timing.timing_rows(proj)
    assert [r["status"] for r in rows] == [timing.INVALID]


def test_the_extractor_never_returns_one(tmp_path):
    """It makes no claim about the design, so it must never emit the exit code
    that means one. Whether timing is CLOSED is asked by `_ppa.feasibility` and
    by `sta_corner_record_completeness_check.py`."""
    cases = [
        _project(tmp_path / "a", {"sta_spef_multicorner.rpt": MULTICORNER}),
        _project(tmp_path / "b", {"sta_mcorner_ocv.rpt": NO_PATHS}),
        _project(tmp_path / "c", {"sta_spef_based.rpt": SINGLE_CORNER_STAMPED}),
        _project(tmp_path / "d", {}),
    ]
    codes = {_cli(c).returncode for c in cases}
    assert 1 not in codes, codes
    assert codes <= {0, 2}


def test_the_json_document_is_written_and_counts_its_rows(tmp_path):
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER})
    out = tmp_path / "rows.json"
    p = _cli(proj, "--json", out)
    assert p.returncode == 0, p.stdout + p.stderr
    doc = json.loads(out.read_text())
    assert doc["schema"] == "vibeic.ppa.timing_rows.v1"
    assert doc["row_count"] == len(doc["rows"]) == len(doc["row_digests"])
    assert doc["measured_count"] + doc["not_measured_count"] + \
        doc["invalid_count"] == doc["row_count"]


# ── the split itself: a backend that starts deciding is the drift ──────────

def test_the_backend_holds_no_threshold_and_no_verdict():
    """A backend parses one tool's output and does nothing else, so that adding
    a second timing engine never changes a rule. A threshold that lands here is
    one that has to be re-agreed for every tool added afterwards, and the two
    copies drift where nobody is looking."""
    src = (_PROGRAMS / "_ppa" / "backends" / "opensta.py").read_text()
    code = "\n".join(
        ln for ln in src.splitlines()
        if not ln.lstrip().startswith("#"))
    body = code.split('"""', 2)[-1]          # drop the module docstring
    # NOT a ban on the words PASS / FAIL / VIOLATED. Those are the TOOL's own
    # output grammar -- `(VIOLATED)` is what OpenSTA prints on a path line and
    # `SIGNOFF_WORST_PATHS_FAILED` is a marker the emitter writes -- and a
    # parser that could not match them would not be a parser. What must not
    # appear is the vocabulary of DECIDING.
    for banned in ("NOT_MEASURED", "MEASURED", "verdict", "threshold",
                   "_ppa.timing", "from _ppa import timing"):
        assert banned not in body, \
            "%r appears in the parsing backend -- that is policy, and policy " \
            "belongs in _ppa.timing" % banned


def test_the_document_leads_with_its_schema_key(tmp_path):
    """§5: every instance document carries `schema` as its FIRST key.

    Sorting the document would bury it under `invalid_count`. The identities
    inside it still go through `canonical_json`, which sorts -- key ORDER and
    key IDENTITY are two different questions and only one of them is a hash.
    """
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER})
    out = tmp_path / "rows.json"
    assert _cli(proj, "--json", out).returncode == 0
    text = out.read_text()
    assert json.loads(text)["schema"] == "vibeic.ppa.timing_rows.v1"
    assert text.lstrip().startswith('{\n  "schema"'), text[:80]


def test_the_document_is_byte_stable_across_runs(tmp_path):
    """Two runs over one tree must produce one document, or nothing built on
    its hash means anything."""
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": MULTICORNER,
                               "sta_mcorner_ocv.rpt": NO_PATHS})
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert _cli(proj, "--json", a).returncode == 0
    assert _cli(proj, "--json", b).returncode == 0
    assert a.read_bytes() == b.read_bytes()


# ── the schema for this domain (PPA_INTERFACES.md §5) ──────────────────────

_SCHEMA_PATH = (_PROGRAMS.parent / "schemas" / "ppa"
                / "timing_rows.v1.schema.json")


def test_the_domain_schema_exists_and_is_draft7():
    """§5: each domain author writes the schema for their own domain, at
    `schemas/ppa/<name>.v1.schema.json`. No jsonschema needed to check THIS."""
    assert _SCHEMA_PATH.is_file(), _SCHEMA_PATH
    doc = json.loads(_SCHEMA_PATH.read_text())
    assert doc["$id"] == "vibeic.ppa.timing_rows.v1"
    assert "draft-07" in doc["$schema"]


def test_every_emitted_document_validates_against_that_schema(tmp_path):
    """A schema nobody validates against is decoration.

    The engine is RESOLVED (`_ppa/schema_validation.py`), not imported: this
    used to `importorskip("jsonschema")` and therefore ran only where somebody
    happened to have the library. With the validator bundled it runs on a bare
    install too, and the skip arm survives for the case where no engine can
    apply the schema at all -- a skip is visible in the summary line and a
    silent pass is not. The shape itself is ALSO asserted without any engine,
    by the scope/value tests above, so this is reinforcement not the only guard.
    """
    from _ppa import schema_validation as _SV
    schema = json.loads(_SCHEMA_PATH.read_text())
    proj = _project(
        tmp_path,
        {"sta_spef_multicorner.rpt": MULTICORNER,
         "sta_mcorner_ocv.rpt": NO_PATHS,
         "sta_spef_based.rpt": SINGLE_CORNER_STAMPED},
        stances={"mcorner_ocv_stance.json":
                 {"setup_process_corner": "SS", "hold_process_corner": "FF"}},
        pvt={"modes": ["functional"]})
    out = tmp_path / "rows.json"
    assert _cli(proj, "--json", out).returncode == 0
    doc = json.loads(out.read_text())
    assert _SV.engine_or_skip(schema).errors(doc) == []
    # the document must be worth validating: all three statuses present
    assert {r["status"] for r in doc["rows"]} >= {"MEASURED", "NOT_MEASURED"}


def test_the_schema_rejects_a_not_measured_row_that_carries_a_value():
    """The no-sentinel rule, proven to BITE.

    A schema that accepts the thing it exists to forbid is worse than no
    schema: it is a green check over the exact defect. So this feeds it the
    forbidden shape and requires a rejection.
    """
    from _ppa import schema_validation as _SV
    schema = json.loads(_SCHEMA_PATH.read_text())
    bad = {
        "schema": "vibeic.ppa.metric.v1",
        "metric": "timing.hold.wns_ns",
        "status": "NOT_MEASURED",
        "value": 0.0,                     # <- the forbidden sentinel
        "unit": "ns",
        "reason": "no paths analysed",
        "scope": {k: None for k in timing._SCOPE_KEYS},
        "source": {"path": None, "sha256": None, "tool": "opensta",
                   "tool_commit": None, "parser": "x", "parser_sha256": None},
    }
    # The row schema plus the pocket its `$ref`s point into, so the subschema
    # is self-contained and no engine needs a resolver bolted on.
    validator = _SV.engine_or_skip(
        {**schema["definitions"]["metric_row"],
         "definitions": schema["definitions"]})
    assert validator.errors(bad), (
        "the schema accepted the sentinel it exists to forbid")
    # positive control: the same row without the value must be ACCEPTED, or
    # this test would pass against a schema that rejects everything.
    ok = dict(bad)
    del ok["value"]
    assert validator.errors(ok) == []


# ── fixtures captured from the REAL tool, not reconstructed ────────────────
#
# Produced on this host by running OpenSTA 2.7.0 f21d4a3878 (from the image
# family this checkout anchors) over two designs built from the same open PDK
# liberty (sky130A `..__ss_100C_1v60.lib`) with one 1.0 ns clock:
#
#   A: two dfxtp_1 flops in series      -> real register-to-register paths
#   B: one buf_1, no sequential element -> no timing paths at all
#
# Everything above this line is a reconstruction of the emitter's format. These
# two are what the tool actually printed.

REAL_WITH_PATHS = """\
tns max 0.00
wns max 0.00
worst slack max 0.19
worst slack min 0.64
Startpoint: r1 (rising edge-triggered flip-flop clocked by clk)
Endpoint: r2 (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
---------------------------------------------------------
   0.00    0.00   clock clk (rise edge)
   0.00    0.00   clock network delay (ideal)
   0.00    0.00 ^ r1/CLK (sky130_fd_sc_hd__dfxtp_1)
   0.53    0.53 v r1/Q (sky130_fd_sc_hd__dfxtp_1)
   0.00    0.53 v r2/D (sky130_fd_sc_hd__dfxtp_1)
           0.53   data arrival time

   1.00    1.00   clock clk (rise edge)
   0.00    1.00   clock network delay (ideal)
   0.00    1.00   clock reconvergence pessimism
           1.00 ^ r2/CLK (sky130_fd_sc_hd__dfxtp_1)
  -0.28    0.72   library setup time
           0.72   data required time
---------------------------------------------------------
           0.72   data required time
          -0.53   data arrival time
---------------------------------------------------------
           0.19   slack (MET)
"""

REAL_NO_PATHS = """\
tns max 0.00
wns max 0.00
worst slack max INF
worst slack min INF
"""


def test_met_timing_and_nothing_analysed_print_the_same_summary():
    """The measurement that justifies this whole module, from the real tool.

    A design that MET timing with +0.19 ns of slack, and a design where nothing
    was analysed at all, print BYTE-IDENTICAL `tns`/`wns` summary lines --
    because `wns = min(0, worst_slack)` clamps both to zero. Anything that reads
    those two lines and stops has no way to tell a closed design from an empty
    analysis. The `worst slack` line is the only discriminator there is.
    """
    def summary(text):
        return [l.strip() for l in text.splitlines()
                if l.strip().startswith(("tns ", "wns "))]
    assert summary(REAL_WITH_PATHS) == summary(REAL_NO_PATHS) == [
        "tns max 0.00", "wns max 0.00"]
    # ...and the module tells them apart anyway
    a = opensta.parse_report(REAL_WITH_PATHS).sections[0]
    b = opensta.parse_report(REAL_NO_PATHS).sections[0]
    a_ws = [m for m in a.measurements if m.kind == "worst_slack"]
    b_ws = [m for m in b.measurements if m.kind == "worst_slack"]
    assert [m.no_paths for m in a_ws] == [False, False]
    assert [m.no_paths for m in b_ws] == [True, True]


def test_real_tool_output_parses_to_the_numbers_it_printed(tmp_path):
    """The reconstructions above are read out of the emitter. This one is what
    OpenSTA actually wrote, and the parsed numbers must be its numbers."""
    proj = _project(tmp_path, {"sta_spef_based.rpt": REAL_WITH_PATHS})
    rows, _ = timing.timing_rows(proj)
    assert _by_metric(rows, "timing.setup.worst_slack_ns")[0]["value"] == 0.19
    assert _by_metric(rows, "timing.hold.worst_slack_ns")[0]["value"] == 0.64
    assert _by_metric(rows, "timing.setup.wns_ns")[0]["value"] == 0.0
    per_clock = _by_metric(rows, "timing.setup.worst_path_slack_ns")
    assert len(per_clock) == 1
    assert per_clock[0]["scope"]["clock"] == "clk"
    assert per_clock[0]["value"] == 0.19


def test_real_no_path_output_yields_no_measured_row(tmp_path):
    proj = _project(tmp_path, {"sta_spef_based.rpt": REAL_NO_PATHS})
    rows, _ = timing.timing_rows(proj)
    assert rows
    assert not [r for r in rows if r["status"] == timing.MEASURED]


def test_an_empty_hold_view_does_not_suppress_a_real_setup_measurement(tmp_path):
    """Withholding is PER CHECK. This module's first shape keyed it on the
    whole section, so an unbannered report carrying a real setup slack beside
    an empty hold analysis had its setup measurement suppressed -- inventing an
    unmeasured view out of one that was measured. Both directions are wrong and
    this is the one that loses evidence.
    """
    body = ("tns max 0.00\nwns max 0.00\n"
            "worst slack max 0.19\nworst slack min INF\n")
    proj = _project(tmp_path, {"sta_spef_based.rpt": body})
    rows, _ = timing.timing_rows(proj)

    setup_ws = _by_metric(rows, "timing.setup.worst_slack_ns")
    assert setup_ws[0]["status"] == timing.MEASURED
    assert setup_ws[0]["value"] == 0.19
    # the setup SUMMARY lines are real evidence too: setup analysed paths
    assert _by_metric(rows, "timing.setup.wns_ns")[0]["status"] == timing.MEASURED
    assert _by_metric(rows, "timing.setup.tns_ns")[0]["status"] == timing.MEASURED
    # and hold is still honestly unmeasured
    assert _by_metric(rows, "timing.hold.worst_slack_ns")[0]["status"] \
        == timing.NOT_MEASURED
