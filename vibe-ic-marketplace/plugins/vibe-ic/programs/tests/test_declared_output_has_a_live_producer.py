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
