#!/usr/bin/env python3
"""The PDK-revision refusal was real, blocking, and had no NAME.

vibe-ic#2069, second half.

WHAT WAS ALREADY TRUE ON THE FROZEN BASE, measured before writing a line
=======================================================================
`pdk_revision_resolve` already reads the revision from the RESOLVED tree, the
one-shot runner already writes `reports/pdk_revision.json` at finalize, and
`benchmark_evidence_publish` already REFUSES to stage a run whose record names
no revision. That landed in `13cbb4858` and it is in this base. Measured on the
run the issue cites (lane rbaes2, 8HD-8): the record exists, says
`resolved: false`, and its `revision` is `null` — and that run has NO `phase3/`
directory at all, so it opened no PDK and "NOT DETERMINED" is the correct
answer for it rather than a defect. The refusal was working.

WHAT WAS NOT
============
The refusal had no name. Three places state the same fact in three different
English sentences:

    pdk_revision_resolve  stderr  "FAIL — the run's PDK revision is not
                                   recorded: ..."
    vibe_ic_one_shot_runner        "PDK revision NOT RECORDED: ..."   (advisory)
    benchmark_evidence_publish     "the run records no PDK revision (...)"
                                   / "... does not name a PDK revision"

`grep -rn PDK_REVISION_NOT_RECORDED` over the whole tree returned NOTHING, so
no consumer could key on "this run was refused for a missing PDK revision"
without matching prose, and a reader of the record FILE alone saw
`resolved: false` with no statement of what that costs. #2069: refuse BY NAME,
never a default.

THE ONE THING THAT MUST NOT HAPPEN is the name becoming a place to put a
value. The token names an ABSENCE; `revision` stays `None`. A record that said
`revision: "PDK_REVISION_NOT_RECORDED"` — or `"unknown"` — would satisfy every
prose reader and re-create the exact gap one layer up, so the tests below pin
both halves: the token appears, and the field it explains stays empty.

Fixtures are the shared synthesized tree (`_pdk_revision_fixture`): no process,
foundry, node or vendor identifier appears here.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdk_revision_resolve as prr                  # noqa: E402
import benchmark_evidence_publish as BEP            # noqa: E402
import _pdk_revision_fixture as fix                 # noqa: E402

RESOLVER = PROGRAMS / "pdk_revision_resolve.py"
RUNNER = PROGRAMS / "vibe_ic_one_shot_runner.py"


def _complete_record(tmp_path):
    """A record the resolver itself produced from a tree that states its own
    revision. Never hand-written — a hand-written record tests the fixture."""
    run = tmp_path / "run"
    run.mkdir()
    fix.write_run_pdk_revision(run)
    rec, err = prr.load_record(run)
    assert err is None and rec is not None, err
    return run, rec


# ── the token exists, once ────────────────────────────────────────────────
def test_the_refusal_has_the_name_the_issue_names():
    assert prr.REFUSAL_NOT_RECORDED == "PDK_REVISION_NOT_RECORDED"


def test_the_runners_literal_is_the_same_string():
    """The one place the token is SPELLED rather than imported — the runner's
    except-branch, where the import that owns it is what just failed. Pinned
    here so the two cannot drift into two tokens."""
    src = RUNNER.read_text(encoding="utf-8")
    spelled = set(re.findall(r'"(PDK_REVISION[A-Z_]*)"', src))
    assert spelled == {prr.REFUSAL_NOT_RECORDED}, spelled


# ── record_refusal, both directions ───────────────────────────────────────
def test_a_complete_record_is_not_refused(tmp_path):
    """THE NEGATIVE CONTROL. A run that named its revision must pass, or the
    token below is a guard that refuses everything and proves nothing."""
    _run, rec = _complete_record(tmp_path)
    assert rec["revision"] == fix.FIXTURE_REVISION_STR, rec["revision"]
    assert prr.record_gaps(rec) == []
    assert prr.record_refusal(rec) is None
    # and the record says so about itself, rather than leaving the key absent
    assert "refusal" in rec and rec["refusal"] is None


def test_an_unresolved_record_is_refused_by_name_and_says_so_in_the_file():
    """The rbaes2 shape: no tree offered a revision."""
    rec = prr.build_record([], "host", "run tool logs")
    assert rec["resolved"] is False
    assert rec["revision"] is None
    assert rec["refusal"] == prr.REFUSAL_NOT_RECORDED
    assert prr.record_refusal(rec) == prr.REFUSAL_NOT_RECORDED


def test_an_absent_record_is_the_strongest_form_of_not_recorded():
    """`None` is "no record at all". Returning `None` for it would make an
    absent record read like a complete one."""
    assert prr.record_refusal(None) == prr.REFUSAL_NOT_RECORDED
    assert prr.record_refusal("not a record") == prr.REFUSAL_NOT_RECORDED


def test_a_placeholder_in_the_revision_field_is_still_refused():
    """THE NAME MUST NOT BECOME A VALUE. Every spelling of "we could not tell"
    is refused, including the token itself."""
    for placeholder in ("unknown", "UNKNOWN", "none", "n/a", "TBD",
                        prr.REFUSAL_NOT_RECORDED, "SRAM_BUILD_COMMIT"):
        rec = {"schema": prr.SCHEMA, "resolved": True,
               "revision": placeholder, "trees": [{"tree": "/x"}]}
        assert prr.record_refusal(rec) == prr.REFUSAL_NOT_RECORDED, placeholder


def test_a_record_naming_no_tree_is_refused_even_if_it_claims_a_revision():
    rec = {"schema": prr.SCHEMA, "resolved": True,
           "revision": fix.FIXTURE_REVISION, "trees": []}
    assert prr.record_refusal(rec) == prr.REFUSAL_NOT_RECORDED


def test_the_refusal_and_the_gap_list_agree_on_every_shape(tmp_path):
    """One decision, two renderings: `record_gaps` says WHICH field,
    `record_refusal` says what the refusal is CALLED. They must never
    disagree — that split is how three prose refusals happened."""
    _run, complete = _complete_record(tmp_path)
    shapes = [
        complete,
        prr.build_record([], "host", "x"),
        None,
        {"schema": 1, "resolved": True, "revision": "unknown",
         "trees": [{"tree": "/x"}]},
        {"schema": 1, "resolved": False, "revision": None, "trees": []},
    ]
    for rec in shapes:
        expected = (prr.REFUSAL_NOT_RECORDED if prr.record_gaps(rec) else None)
        assert prr.record_refusal(rec) == expected, rec


# ── the publish gate refuses BY NAME and names the missing field ──────────
def test_publish_refuses_an_absent_record_by_name(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    try:
        BEP._pdk_revision(run)
    except BEP.Refuse as exc:
        msg = str(exc)
    else:                                            # pragma: no cover
        raise AssertionError("publish did not refuse a run with no record")
    assert msg.startswith(prr.REFUSAL_NOT_RECORDED), msg[:200]
    assert prr.RECORD_REL in msg, msg[:300]


def test_publish_refuses_a_record_that_names_no_revision_by_name(tmp_path):
    run = tmp_path / "run"
    (run / "reports").mkdir(parents=True)
    rec = prr.build_record([], "host", "run tool logs")
    (run / prr.RECORD_REL).write_text(json.dumps(rec), encoding="utf-8")
    try:
        BEP._pdk_revision(run)
    except BEP.Refuse as exc:
        msg = str(exc)
    else:                                            # pragma: no cover
        raise AssertionError("publish did not refuse an unresolved record")
    assert msg.startswith(prr.REFUSAL_NOT_RECORDED), msg[:200]
    # the missing field is NAMED, not merely implied
    assert "resolved is not true" in msg and "revision:" in msg, msg[:400]


def test_publish_accepts_a_run_that_carries_a_revision(tmp_path):
    """THE OTHER DIRECTION — a gate that refuses every run is not a gate."""
    run, _rec = _complete_record(tmp_path)
    got = BEP._pdk_revision(run)
    assert got["revision"] == fix.FIXTURE_REVISION_STR
    assert got["refusal"] is None


# ── the CLI states the name on its own refusal path ───────────────────────
def test_the_resolver_cli_names_the_refusal_on_rc_1(tmp_path):
    """rc 1 is NOT DETERMINED. Driven, not asserted: a `--tree` that exists and
    declares nothing is the shape a third of the shipped trees are in."""
    bare = tmp_path / "bare_tree"
    (bare / "libs.ref").mkdir(parents=True)
    out = tmp_path / "rec.json"
    r = subprocess.run(
        [sys.executable, str(RESOLVER), "--tree", str(bare),
         "--json", str(out)],
        capture_output=True, text=True, timeout=300)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert prr.REFUSAL_NOT_RECORDED in r.stderr, r.stderr
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["refusal"] == prr.REFUSAL_NOT_RECORDED
    assert rec["revision"] is None, "the token names an absence, never fills it"


def test_the_resolver_cli_is_silent_about_the_refusal_when_it_resolves(
        tmp_path):
    tree = fix.synth_pdk_tree(tmp_path / "pdks")
    out = tmp_path / "rec.json"
    r = subprocess.run(
        [sys.executable, str(RESOLVER), "--tree", str(tree),
         "--json", str(out)],
        capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert prr.REFUSAL_NOT_RECORDED not in r.stderr + r.stdout
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["refusal"] is None
    assert rec["revision"] == fix.FIXTURE_REVISION_STR
