"""Deleting a producer must change an answer somewhere.

Measured on the 68x9 matrix (mutation probe, plugin v1.12.33): 122 of
dimension D3's 166 entries ask whether a run tree committed into
`benchmark-data` still carries a file matching the declared glob. So the probe
deleted the WRITER of step A8's declared `.gds` and D3 stayed green in every
configuration -- the artefact was still in the corpus.

The gate under test asks the other question: does the SOURCE still write it.
The can-fail arm below is that same deletion, performed on a producer this
repo really ships.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import declared_output_has_a_live_producer_check as D

_PROGRAMS = Path(D.__file__).resolve().parent
_ROOT = _PROGRAMS.parents[3]


# ---------------------------------------------------------------- can FAIL --
def test_deleting_the_only_producer_downgrades_the_answer():
    """MUT-B1, on a live single-producer path: the writer goes, the answer moves."""
    before = D.audit(_ROOT)
    singles = [(p, r["producers"][0]) for p, r in before["rows"].items()
               if r["state"] == "WRITE-SITE" and len(r["producers"]) == 1]
    assert singles, "no single-producer declared output to delete"
    path, producer = sorted(singles)[0]
    after = D.audit(_ROOT, exclude_modules=[producer])
    assert before["rows"][path]["state"] == "WRITE-SITE"
    assert after["rows"][path]["state"] != "WRITE-SITE", (
        f"{producer} was the only writer of {path}, and removing it changed "
        f"nothing — the check is reading something other than the producer")


def test_a_declaration_cannot_prove_itself():
    """The flow's own `required_outputs` list is not evidence of a producer."""
    flow = ("steps:\n"
            "  - id: '1'\n"
            "    required_outputs:\n"
            "      - reports/only_declared.json\n"
            "    command: echo hi\n")
    kept = D._flow_commands(flow)
    assert "only_declared.json" not in kept
    assert "command: echo hi" in kept


# ---------------------------------------------------------------- can PASS --
def test_the_repo_has_no_untraceable_declared_output():
    """A guard that fires on the state it ships with is a bug, not a guard."""
    out = subprocess.run(
        [sys.executable, str(_PROGRAMS / "declared_output_has_a_live_producer_check.py"),
         "--root", str(_ROOT), "--strict"],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stdout[-3000:]


def test_an_unresolved_destination_matches_nothing():
    """`*/` alone is a variable this scanner could not read, not a producer."""
    assert not D._matches("*", "phase3/gds/chip.gds")
    assert not D._matches("*/*", "phase3/gds/chip.gds")


def test_a_glob_declaration_matches_a_computed_destination():
    assert D._matches("*/hardmacro/*/*.gds", "phase3/analog/hardmacro/*/*.gds")
    assert not D._matches("*/lessons.md", "phase3/analog/hardmacro/*/*.gds")


def test_an_extension_only_glob_falls_back_to_its_directory():
    assert D._tokens("sim_spice/*.sp") == {"sim_spice"}
    assert "perc_sweep.json" in D._tokens("reports/phase3/perc_sweep.json")


def test_a_missing_flow_is_cannot_check_not_pass():
    rc = D.main(["--root", "/nonexistent-root-for-this-test"])
    assert rc == 2


# ─────────────────────────────────────────────────────────────────────────────
# THE REAL MUTATION, after the synthetic fixture said the gate worked and a
# real tree said it did not. MEASURED 2026-08-29: deleting the sole writer of
# `phase2/stage1/formal/*.sby` left this gate at rc 0 PASS, because it blocked
# only on NO-TRACE — and NO-TRACE is unreachable here. Using the gate's own
# `exclude_modules` hook to delete the ENTIRE sole producer of all 34
# single-producer paths, not one reached NO-TRACE; every one landed in
# TOKEN-TRACE, because the path's name is still written in the source by its
# READERS.
# ─────────────────────────────────────────────────────────────────────────────
def test_no_trace_is_unreachable_so_it_cannot_be_the_only_blocker():
    """The measurement that condemned the old blocking condition, kept live."""
    before = D.audit(_ROOT)
    singles = [(p, r["producers"][0]) for p, r in before["rows"].items()
               if r["state"] == "WRITE-SITE" and len(r["producers"]) == 1]
    assert singles, "no single-producer path to reason about"
    reached_no_trace = 0
    for path, producer in singles:
        after = D.audit(_ROOT, exclude_modules=[producer])
        if after["rows"][path]["state"] == "NO-TRACE":
            reached_no_trace += 1
    assert reached_no_trace == 0, (
        f"{reached_no_trace} of {len(singles)} sole-producer deletions now reach "
        f"NO-TRACE. If that is deliberate, this test is the place to say so — "
        f"but while it is zero, NO-TRACE alone blocks nothing")


def test_losing_a_write_site_is_the_blocking_condition(tmp_path):
    """The real defect: a path this tree resolved to a writer stops having one."""
    before = D.audit(_ROOT)
    live = sorted(p for p, r in before["rows"].items() if r["state"] == "WRITE-SITE")
    assert live, "no write site to lose"
    victim = live[0]
    producer = before["rows"][victim]["producers"][0]
    after = D.audit(_ROOT, exclude_modules=[producer])
    assert after["rows"][victim]["state"] != "WRITE-SITE"

    # the baseline says it WAS resolved; the gate must call that a regression
    inv = tmp_path / "baseline.json"
    inv.write_text(json.dumps({"write_site": live}), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(_PROGRAMS / "declared_output_has_a_live_producer_check.py"),
         "--root", str(_ROOT), "--inventory", str(inv), "--strict"],
        capture_output=True, text=True)
    assert out.returncode == 0, ("the unmutated tree must satisfy its own "
                                 "baseline\n" + out.stdout[-1500:])


def test_a_synthetic_fixture_is_not_a_producer():
    """MEASURED: one gate-mutation fixture was the SOLE credited producer of 23
    declared flow outputs — drc_signoff.rpt, lvs.rpt, erc.rpt, ir_drop.rpt among
    them. A fixture writes those paths to BUILD a subject tree; nothing in the
    flow is thereby shown to write them."""
    walked = [str(f) for f in D._venue_files(_ROOT)]
    assert not [f for f in walked if "gate_fixtures" in f], \
        "a gate fixture is being walked as a production venue"
    report = D.audit(_ROOT)
    credited = {m for r in report["rows"].values() for m in (r.get("producers") or [])}
    assert not [m for m in credited if "fixture" in m or m.startswith("test_")], \
        sorted(credited)


def test_an_unreadable_baseline_is_refused_not_treated_as_empty(tmp_path):
    """An empty baseline would silently forgive every regression."""
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(_PROGRAMS / "declared_output_has_a_live_producer_check.py"),
         "--root", str(_ROOT), "--inventory", str(bad), "--strict"],
        capture_output=True, text=True)
    assert out.returncode == 2, out.stdout + out.stderr
    assert "never treated as empty" in out.stderr
