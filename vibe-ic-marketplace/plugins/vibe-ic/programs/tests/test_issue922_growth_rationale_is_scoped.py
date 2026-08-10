"""#922 — a growth rationale covers the waivers it NAMES, and no others.

`growth_rationale` was ONE top-level string, and `len(rationale.strip()) >= 30`
set `growth_justified` for any growth of any size, permanently. Measured on the
unfixed gate, all three properties, verbatim:

    ARM A  1 waiver, growth_rationale = "x" * 32   -> [PASS] rc 0
    ARM B  50 waivers, the SAME "x" * 32           -> [PASS] rc 0, net_growth 50
    ARM C  rationale about the LVS waiver, an unrelated ANTENNA waiver added
           three lines later                       -> [PASS] rc 0

Unbounded, unscoped, non-expiring — while the gate's own `details` text says it
exists to stop "every release accumulating more deferred work until the project
has more open waivers than executed steps".

The fix scopes the authorisation to the waiver identities it names. The tests
below pin BOTH arms, because a gate that refuses everything would satisfy the
FAIL arm alone and is not correct:

  * growth the rationale legitimately names must still PASS, and
  * growth beyond what it names must FAIL.

Tests marked REGRESSION GUARD do NOT discriminate against the unfixed gate.
They pin behaviour the fix must not break, so the fix cannot be satisfied by
breaking the gate, and each says so.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PROG = PROGRAMS / "waiver_growth_check.py"

STATE_DIR = ".vibe-ic-state"
BASELINE_NAME = "waivers_baseline.json"

#: A rationale long enough to clear the substantive-text bar. Its LENGTH was
#: the entire old predicate; here it is incidental, and what matters is the
#: identity it is filed under.
GOOD_TEXT = ("Device-level extraction is scheduled for the next release; "
             "deferral accepted at sign-off.")


def _run(project: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project), *extra],
                          capture_output=True, text=True, timeout=60)


def _run_json(project: Path, *extra: str):
    """``(rc, parsed_json)``. The parse is asserted rather than assumed so a
    gate that dies before emitting cannot be mistaken for one that passed."""
    proc = _run(project, "--json", *extra)
    assert proc.stdout.strip(), (
        f"gate produced no JSON; rc={proc.returncode} stderr={proc.stderr!r}")
    return proc.returncode, json.loads(proc.stdout)


def _project(tmp_path: Path, doc, baseline=None) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / "waivers.json").write_text(json.dumps(doc))
    if baseline is not None:
        state = proj / STATE_DIR
        state.mkdir(exist_ok=True)
        (state / BASELINE_NAME).write_text(json.dumps(baseline))
    return proj


def _categories(result) -> set:
    return {f["category"] for f in result["findings"]}


def _entry(step, ticket, phase="3"):
    return {"step": step, "phase": phase, "ticket": ticket,
            "rationale": "deferred to a dedicated flow",
            "review_required": True}


#: The identity `_entry("lvs", "T-1")` is reported under. Written out as a
#: LITERAL rather than recomputed from `_WAIVERS_IDENTITY_FIELDS`, so that a
#: change to the identity format is CAUGHT here instead of being silently
#: followed by a test that recomputes whatever the program currently does.
LVS_IDENTITY = "waivers:step='lvs';phase='3';ticket='T-1'"


def test_the_identity_format_this_file_hardcodes_is_the_one_the_gate_prints(
        tmp_path):
    """Anchors every scoped-key literal below to the program's real output. If
    the identity rendering ever moves, this fails first and names the reason,
    rather than leaving the scoped tests silently keyed on nothing."""
    proj = _project(tmp_path, {"waivers": [_entry("lvs", "T-1")]})
    _rc, result = _run_json(proj)
    assert result["summary"]["new_waivers"] == [LVS_IDENTITY]


# ----------------------------------------------------------------------
# the reported defect — each arm reproduced above
# ----------------------------------------------------------------------
def test_a_blanket_string_no_longer_authorises_growth(tmp_path):
    """ARM A. Thirty characters of anything is not a justification for
    anything; it names no waiver, so it covers no waiver."""
    proj = _project(tmp_path, {"waivers": [_entry("lvs", "T-1")],
                               "growth_rationale": "x" * 32})
    rc, result = _run_json(proj)
    assert result["summary"]["growth_rationale_shape"] == "blanket"
    assert result["summary"]["growth_justified"] is False
    assert "UNJUSTIFIED_WAIVER_GROWTH" in _categories(result)
    assert rc == 1


def test_a_blanket_string_does_not_scale_to_fifty_waivers(tmp_path):
    """ARM B — unboundedness. The string that 'justified' one waiver justified
    fifty, because `net_growth` was never compared against anything in the arm
    the rationale switched off."""
    proj = _project(tmp_path, {
        "waivers": [_entry(f"role{i}", f"T-{i}") for i in range(50)],
        "growth_rationale": "x" * 32})
    rc, result = _run_json(proj)
    assert result["summary"]["net_growth"] == 50
    assert len(result["summary"]["uncovered_new_waivers"]) == 50
    assert rc == 1


def test_a_rationale_written_for_one_waiver_does_not_cover_another(tmp_path):
    """ARM C — unscopedness. A sentence about LVS must not silently authorise
    an antenna waiver nobody wrote it about. The covered one stays covered:
    the finding names the antenna waiver and only the antenna waiver."""
    proj = _project(
        tmp_path,
        {"waivers": [_entry("lvs", "T-1"), _entry("antenna", "T-99")],
         "growth_rationale": {LVS_IDENTITY: GOOD_TEXT}},
        baseline={"waivers": []})
    rc, result = _run_json(proj)
    assert result["summary"]["uncovered_new_waivers"] == [
        "waivers:step='antenna';phase='3';ticket='T-99'"]
    assert LVS_IDENTITY not in result["summary"]["uncovered_new_waivers"]
    assert rc == 1


# ----------------------------------------------------------------------
# the other arm — a fix that only ever refuses is not a fix
# ----------------------------------------------------------------------
def test_growth_the_rationale_names_is_still_authorised(tmp_path):
    """THE PASS ARM. The escape hatch still opens; it just has to say which
    waiver it is about. Without this, a gate that refused every rationale
    would satisfy every other test in this file."""
    proj = _project(tmp_path,
                    {"waivers": [_entry("lvs", "T-1")],
                     "growth_rationale": {LVS_IDENTITY: GOOD_TEXT}})
    rc, result = _run_json(proj)
    assert result["summary"]["net_growth"] == 1, "there must be growth to authorise"
    assert result["summary"]["growth_justified"] is True
    assert result["summary"]["uncovered_new_waivers"] == []
    assert "UNJUSTIFIED_WAIVER_GROWTH" not in _categories(result)
    assert rc == 0


def test_two_new_waivers_each_with_their_own_sentence_pass(tmp_path):
    """The PASS arm at n>1: scoping is not a cap on how much growth can be
    authorised, only on authorising growth nobody wrote about."""
    proj = _project(tmp_path, {
        "waivers": [_entry("lvs", "T-1"), _entry("antenna", "T-99")],
        "growth_rationale": {
            LVS_IDENTITY: GOOD_TEXT,
            "waivers:step='antenna';phase='3';ticket='T-99'":
                "Antenna repair is deferred to the next tapeout window.",
        }})
    rc, result = _run_json(proj)
    assert result["summary"]["net_growth"] == 2
    assert result["summary"]["growth_justified"] is True
    assert rc == 0


def test_the_remedy_the_gate_prints_actually_passes(tmp_path):
    """The failure message tells the operator to paste an object keyed by the
    identities it printed. That promise is executed here rather than trusted:
    the keys come from the PROGRAM's own reported `new_waivers`, and the
    second run must pass. A remedy nobody ran is the shape this repo removes."""
    doc = {"waivers": [_entry("lvs", "T-1"), _entry("drc", "T-2")]}
    proj = _project(tmp_path, doc)
    rc, result = _run_json(proj)
    assert rc == 1, "precondition: the gate must be failing before the remedy"

    doc["growth_rationale"] = {ident: GOOD_TEXT
                               for ident in result["summary"]["new_waivers"]}
    (proj / "waivers.json").write_text(json.dumps(doc))
    rc2, result2 = _run_json(proj)
    assert result2["summary"]["growth_justified"] is True
    assert rc2 == 0


# ----------------------------------------------------------------------
# the scope has to mean something
# ----------------------------------------------------------------------
def test_a_named_identity_with_no_real_text_is_not_justification(tmp_path):
    """Naming the waiver is necessary, not sufficient — the per-waiver text
    carries the same substantive bar the document-level string used to."""
    proj = _project(tmp_path, {"waivers": [_entry("lvs", "T-1")],
                               "growth_rationale": {LVS_IDENTITY: "ok"}})
    rc, result = _run_json(proj)
    assert result["summary"]["uncovered_new_waivers"] == [LVS_IDENTITY]
    assert rc == 1


def test_an_unmatched_key_covers_nothing_rather_than_everything(tmp_path):
    """A key naming no real waiver — a typo, or a wildcard someone hoped would
    work — must fail CLOSED. Matching loosely to be helpful is how an
    authorisation re-acquires the reach this issue removed."""
    proj = _project(tmp_path, {"waivers": [_entry("lvs", "T-1")],
                               "growth_rationale": {"*": GOOD_TEXT,
                                                    "lvs": GOOD_TEXT}})
    rc, result = _run_json(proj)
    assert result["summary"]["uncovered_new_waivers"] == [LVS_IDENTITY]
    assert rc == 1


def test_a_scope_naming_a_closed_waiver_is_reported_as_stale(tmp_path):
    """The non-expiring half, made visible: prose left behind for a waiver
    that has since closed. WARN, not ERROR — under the scoped contract it
    authorises nothing, so it is litter rather than a false green."""
    proj = _project(tmp_path,
                    {"waivers": [_entry("lvs", "T-1")],
                     "growth_rationale": {
                         LVS_IDENTITY: GOOD_TEXT,
                         "waivers:step='gone';phase='3';ticket='T-0'": GOOD_TEXT}})
    rc, result = _run_json(proj)
    assert "GROWTH_RATIONALE_STALE_SCOPE" in _categories(result)
    assert rc == 0, "stale prose must not fail a project whose growth is covered"


# ----------------------------------------------------------------------
# REGRESSION GUARDS — these pass against the UNFIXED gate too, on purpose.
# They pin behaviour the fix must not break, so the fix cannot be satisfied by
# making the gate refuse or crash more.
# ----------------------------------------------------------------------
def test_growth_with_no_rationale_at_all_still_fails_the_same_way(tmp_path):
    """REGRESSION GUARD. The pre-existing failure mode keeps its category —
    `signoff_audit`'s block comment cites `UNJUSTIFIED_WAIVER_GROWTH` by name."""
    proj = _project(tmp_path, {"waivers": [_entry("lvs", "T-1")]})
    rc, result = _run_json(proj)
    assert "UNJUSTIFIED_WAIVER_GROWTH" in _categories(result)
    assert result["summary"]["growth_justified"] is False
    assert rc == 1


def test_a_flat_waiver_count_still_passes_with_no_rationale(tmp_path):
    """REGRESSION GUARD. No growth, no authorisation needed. A gate that
    started demanding a rationale for zero growth would pass every FAIL arm
    above and be worse than what it replaced."""
    proj = _project(tmp_path, {"waivers": [_entry("lvs", "T-1")]},
                    baseline={"waivers": [_entry("lvs", "T-1")]})
    rc, result = _run_json(proj)
    assert result["summary"]["net_growth"] == 0
    assert "UNJUSTIFIED_WAIVER_GROWTH" not in _categories(result)
    assert rc == 0


def test_a_shrinking_waiver_count_still_passes(tmp_path):
    """REGRESSION GUARD. Closing waivers must never need justifying."""
    proj = _project(tmp_path, {"waivers": [_entry("lvs", "T-1")]},
                    baseline={"waivers": [_entry("lvs", "T-1"),
                                          _entry("drc", "T-2")]})
    rc, result = _run_json(proj)
    assert result["summary"]["net_growth"] == -1
    assert rc == 0


def test_an_unreadable_document_is_still_reported_not_passed(tmp_path):
    """REGRESSION GUARD (#525). Reading an unreadable document as zero waivers
    is the failure this gate was previously fixed for; the scoped rationale
    must not reintroduce it by fail-softing the new lookup."""
    proj = _project(tmp_path, "text")
    rc, result = _run_json(proj)
    assert "WAIVER_DOCUMENT_UNREADABLE" in _categories(result)
    assert rc == 1


def test_a_corrupt_document_still_exits_two(tmp_path):
    """REGRESSION GUARD. A corrupt waivers.json must stay rc 2, never become
    'no waivers, and no rationale needed'."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "waivers.json").write_text("{not json")
    assert _run(proj).returncode == 2
