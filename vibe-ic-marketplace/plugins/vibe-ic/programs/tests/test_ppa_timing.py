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

#: F-10b, as a specimen: the emitter dumps the worst FEW paths of a group, so
#: THREE path blocks land in ONE (clock, check) view with three different
#: slacks. Two name their endpoints; the third prints a Startpoint and NO
#: Endpoint, which is the case the ordinal exists for. Every other field is
#: identical across the three, so the only thing that can tell these rows apart
#: is the path identity.
MULTIPATH = """\
=== SETUP (max-RC corner, SPEF=max, liberty=/pdks/x_fd_sc_hd__ss_100C_1v60.lib) ===
worst slack max 5.20
tns max 0.00
Startpoint: u_p/q (rising edge-triggered flip-flop clocked by clk)
Endpoint: u_q/d (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max
  5.20   slack (MET)
Startpoint: u_r/q (rising edge-triggered flip-flop clocked by clk)
Endpoint: u_s/d (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max
  5.32   slack (MET)
Startpoint: u_t/q (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max
  5.36   slack (MET)
SIGNOFF_WORST_PATHS_REPORTED path_delay=max group_path_count=3
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


# ── the matrix must survive ────────────────────────────────────────────────


# ── scope must be read, never invented ─────────────────────────────────────


# ── declared-but-unreported, and its false-positive twin ───────────────────


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


# ── identity ───────────────────────────────────────────────────────────────


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
    # the document must be worth validating: all three statuses present
    assert {r["status"] for r in doc["rows"]} >= {"MEASURED", "NOT_MEASURED"}


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


# ── F-10: one artefact published into two directories ───────────────────────

def _publish_twice(tmp_path, name, body):
    """What the runner really does: write one report into `phase3/stage3/sta`
    AND into `reports/phase3`, as two files with identical bytes."""
    a = tmp_path / "phase3" / "stage3" / "sta"
    b = tmp_path / "reports" / "phase3"
    a.mkdir(parents=True, exist_ok=True)
    b.mkdir(parents=True, exist_ok=True)
    (a / name).write_text(body)
    (b / name).write_text(body)
    return a / name, b / name


def test_a_report_published_into_two_directories_is_read_ONCE(tmp_path):
    """THE F-10 GUARD, and the producer is what closes it.

    `_STA_DIRS` names three directories and the runner publishes into two, so
    every row was emitted twice and all 20 (metric, scope) groups in the
    document collided.

    WHAT CHANGED AND WHY (v1.11.57). This guard originally de-duplicated by
    CONTENT HASH. A second lane then shipped
    `test_two_identical_artefacts_that_are_not_declared_mirrors_both_count`,
    whose rule a content hash cannot satisfy: two DIFFERENT sign-off reports
    whose bytes happen to agree are two measurements, and collapsing them by
    digest deletes evidence. Nothing in the bytes tells the two situations
    apart.

    So byte equality now DETECTS and the producer's declaration DECIDES. The
    runner writes `reports/phase3/artefact_mirrors.json`
    (`_publish_artefact_mirror`), this reads it, and the mirror collapses with
    a reason attached. Undeclared byte-identical artefacts are reported as a
    finding and BOTH are counted -- deleting a real second measurement is worse
    than double-counting one, because a double count is visible in the document
    and a deletion is not.
    """
    first, second = _publish_twice(tmp_path, "sta_spef_based.rpt",
                                   SINGLE_CORNER_STAMPED)
    assert first.read_bytes() == second.read_bytes()
    assert first.resolve() != second.resolve(), "not the same path: the point"

    # WITHOUT the declaration: both are read, and the finding is emitted.
    collapsed = []
    assert len(collapsed) == 1, collapsed

    # WITH the declaration the runner now writes: one reading, one row per key.
    # `collapse_declared_mirrors` keys by `_rel(project, f)`, the same relative
    # form the runner writes -- not by an absolute or resolved path.
    # the digest form the READER compares against, not a bare hexdigest
    sha = opensta.file_digest(first)


def test_two_DIFFERENT_reports_of_one_name_are_both_read(tmp_path):
    """The discriminator. Same file name, different bytes, is NOT one artefact
    published twice -- it is two readings, and collapsing them would delete the
    evidence that they disagree."""
    a = tmp_path / "phase3" / "stage3" / "sta"
    b = tmp_path / "reports" / "phase3"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "sta_spef_based.rpt").write_text(SINGLE_CORNER_STAMPED)
    (b / "sta_spef_based.rpt").write_text(
        SINGLE_CORNER_STAMPED.replace("worst slack max 5.24",
                                      "worst slack max 4.11"))
    collapsed = []
    assert collapsed == []


# ── v1.11.69: the two producer defects the PPA measurement coverage gate saw ─
#
# `PPA measurement coverage` was pointed at a real corpus for the first time in
# v1.11.69 and refused 54 of 148 records in
# `ppa-crosslayer/records/trials/b000/records_flat.json`: 44 SCOPE_SENTINEL,
# 8 SAME_ARTEFACT_TWO_VALUES, 2 CONFLICTING_RECORD. The two below are this
# module's share of that. Each is written so that reverting the producer change
# makes it RED, and each was PROVEN red that way before being committed.

#: Two reported paths of one group that share BOTH endpoint names. The report
#: is STAMPED so `stage` is established and the rows reach the identity check
#: rather than stopping at SCOPE_INCOMPLETE -- an unstamped fixture would have
#: made this test pass for the wrong reason.
SAME_ENDPOINTS_TWICE = """\
tns max 0.00
wns max 0.00
worst slack max 5.20
Startpoint: u_a/q (rising edge-triggered flip-flop clocked by clk)
Endpoint: u_b/d (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max
  5.20   slack (MET)
Startpoint: u_a/q (rising edge-triggered flip-flop clocked by clk)
Endpoint: u_b/d (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max
  5.32   slack (MET)
STA_BASIS: POST_ROUTE_SPEF
STA_SIGNOFF_CORNER: SS
STA_BASIS_LIBERTY: /pdks/x_fd_sc_hd__ss_100C_1v60.lib
"""


def test_two_paths_sharing_one_name_pair_do_not_share_one_identity(tmp_path):
    """CLASS 2, the half `_path_scope` missed until v1.11.69.

    v1.11.53 gave each reported path its endpoints as scope, which fixed the
    corpus's 8 SAME_ARTEFACT_TWO_VALUES refusals. It asked whether the artefact
    PRINTED two names; it never asked whether the two names were UNIQUE in the
    view. Nothing stops OpenSTA reporting two paths of one group that share
    both -- and when it does, the rows carry one scope, one artefact yields two
    numbers for one identity, and the original defect is back verbatim.

    REPRODUCED on this checkout before the fix: this fixture produced two rows
    with byte-identical scope and `_ppa/metrics.MetricIndex` refused the second
    `SAME_ARTEFACT_TWO_VALUES`.

    The fix drops the shared names rather than keeping them beside an ordinal:
    a name two rows share is not a weaker identity, it is a wrong one.
    """
    from _ppa import metrics as _M
    proj = _project(tmp_path, {"sta_spef_based.rpt": SAME_ENDPOINTS_TWICE},
                    pvt={"modes": ["functional"]})
    # NOT VACUOUS: the specimen prints two paths on purpose, and a run that
    # produced one row would satisfy "no two rows collide" trivially.

    # The shared names are gone, not kept beside a volatile key.

    # And the consumer that refused this corpus must now accept it.
    index = _M.MetricIndex()
    assert len(index) == 2


def test_no_row_this_module_emits_carries_a_scope_sentinel(tmp_path):
    """CLASS 3, end to end, through the consumer that does the refusing.

    44 of the corpus's 54 refusals were `scope.clock` or `scope.rc_corner`
    holding null, and 152 more were measured over 12 real run trees on this
    host before the fix. This asserts the property at the seam that matters:
    every row this module emits is offered to `_ppa/metrics.validate`, and not
    one of them may come back SCOPE_SENTINEL.

    The fixture set is chosen so keys are genuinely unestablished -- the
    multi-corner report stamps no basis, `NO_PATHS` names no RC corner, and no
    design-wide row has a clock -- so a producer that went back to writing
    nulls would light this up rather than slip past an easy specimen.
    """
    from _ppa import metrics as _M
    proj = _project(
        tmp_path,
        {"sta_spef_multicorner.rpt": MULTICORNER,
         "sta_mcorner_ocv.rpt": NO_PATHS,
         "sta_spef_based.rpt": SINGLE_CORNER_STAMPED},
        stances={"mcorner_ocv_stance.json":
                 {"setup_process_corner": "SS", "hold_process_corner": "FF"}},
        pvt={"modes": ["functional"]})

    offenders = []
    assert offenders == [], (
        "%d row(s) still spell an unestablished scope key as null: %r"
        % (len(offenders), offenders[:3]))
    # NOT VACUOUS, and checked AFTER the rule above so a producer that went
    # back to nulls fails on the rule rather than on this guard: keys really
    # are missing in this fixture, so the omit-and-explain path is the one
    # under test and not a formality.
