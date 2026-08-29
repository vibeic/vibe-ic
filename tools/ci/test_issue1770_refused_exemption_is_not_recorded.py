"""A refused exemption must not be RECORDED as if it had been granted.

THE DEFECT, MEASURED ON `b2f38774587f` (vibe-ic#1770)
=====================================================
`_dispatch` consumes the pending `uncheckable_until` first and unconditionally,
then judges the wiring.  For a dispatcher-owned population refusal
(`tolerate == 2`) it REFUSES the date -- "an unknown denominator must remain
blocking" -- and then fell through to the append that every other arm shares::

      elif [ "$tolerate" -eq 2 ] && [ -n "$ex_until" ]; then
        _gate_wiring_error "... cannot consume an uncheckable exemption ..."
      fi
      GATE_EX_UNTIL+=("$ex_until"); GATE_EX_WHY+=("$ex_why")   # <-- ran anyway

So the console said one thing and the record said the other:

    ^^ NOT CHECKED (rc 2, BLOCKING; no exemption): corpus "..." is EMPTY
    record:  "exempt_until": "2999-01-01", "exemption_expired": false,
             "not_checked_unexempted": []

`not_checked_unexempted` is the key `gatekeeper_review.py` documents as the
FAIL-SAFE derivation of "which NOT CHECKED rows still block this landing".  A
row that quietly carries a date nobody was allowed to grant leaves that list --
i.e. the one blocking NOT CHECKED row of an unknown population is bought off
with a date the dispatcher had just declared unspendable, by a human who only
has to write the line the dispatcher already prints a WIRING ERROR about.

The arms below are a pair on purpose.  Arm A pins the refusal.  Arm B is the
control: a genuine `run_tolerating_uncheckable` gate must still record its date,
so "record no exemption anywhere" cannot satisfy Arm A.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

_CI = Path(__file__).resolve().parent
_LIB = _CI / "_gate_dispatch.sh"

_EMPTY_POPULATION = (
    '_body() { run "per item ($1)" "$ROOT" true; }\n'
    'gate_dispatch_over "an empty corpus" _body printf ""\n')


def _run(root: Path, body: str):
    """Drive one real sweep through the shipped dispatcher and read its record."""
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    script = root / "tools" / "ci" / "gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + body + "\ngate_dispatch_finish\n")
    rec = root / "record.json"
    env = os.environ.copy()
    env["GATE_DISPATCH_ATTEST_POPULATION"] = "1"
    proc = subprocess.run(
        ["bash", str(script), "--summary-json", str(rec)],
        cwd=str(root), env=env, capture_output=True, text=True)
    doc = json.loads(rec.read_text()) if rec.is_file() and rec.stat().st_size else None
    return proc, doc


def _population_row(doc):
    rows = [g for g in doc["gates"] if "EMPTY" in g["label"]]
    assert len(rows) == 1, doc["gates"]
    return rows[0]


def test_the_refused_date_reaches_the_console_as_refused(tmp_path):
    """The precondition: this wiring IS refused, out loud."""
    proc, doc = _run(tmp_path, 'uncheckable_until 2999-01-01 "not spendable here"\n'
                     + _EMPTY_POPULATION)
    text = proc.stdout + proc.stderr

    assert doc is not None, text
    assert any("cannot consume an uncheckable exemption" in w
               for w in doc["wiring_errors"]), doc["wiring_errors"]
    assert "BLOCKING; no exemption" in text, text
    assert proc.returncode != 0, (
        f"a refused population exemption did not block the sweep:\n{text}")


def test_a_refused_exemption_is_not_written_into_the_record(tmp_path):
    """ARM A. Console and record must not disagree about the same row."""
    _, doc = _run(tmp_path, 'uncheckable_until 2999-01-01 "not spendable here"\n'
                  + _EMPTY_POPULATION)
    row = _population_row(doc)

    assert row["exempt_until"] is None, (
        "the dispatcher REFUSED this date and recorded it anyway: "
        f"{row!r}")
    assert row["exempt_reason"] is None, row
    assert row["exemption_expired"] is False, row


def test_the_refused_row_stays_in_not_checked_unexempted(tmp_path):
    """ARM A, at the key a landing consumer actually reads.

    `gatekeeper_review.py` names this list as the FAIL-SAFE derivation; a
    refused date that empties it defeats the derivation itself.
    """
    _, doc = _run(tmp_path, 'uncheckable_until 2999-01-01 "not spendable here"\n'
                  + _EMPTY_POPULATION)
    row = _population_row(doc)

    assert row["state"] == "NOT_CHECKED", row
    assert row["label"] in doc["not_checked_unexempted"], (
        "the one blocking NOT CHECKED row was bought off with a date the "
        f"dispatcher refused: {doc['not_checked_unexempted']!r} / {row!r}")
    assert doc["exemptions_expired"] == [], doc["exemptions_expired"]


def test_an_expired_refused_date_does_not_leave_the_record_either(tmp_path):
    """Same row, a date already past: it must not be recorded as an expiry.

    Recording it as an EXPIRED exemption would also be a grant -- the row would
    still leave `not_checked_unexempted`, and the only thing left naming it
    would be a reminder to re-date it.
    """
    _, doc = _run(tmp_path, 'uncheckable_until 2000-01-01 "not spendable here"\n'
                  + _EMPTY_POPULATION)
    row = _population_row(doc)

    assert row["exempt_until"] is None, row
    assert row["exemption_expired"] is False, row
    assert row["label"] in doc["not_checked_unexempted"], doc


def test_a_legitimately_bought_exemption_is_still_recorded(tmp_path):
    """ARM B -- the control.

    Arm A is satisfiable by a dispatcher that stopped recording exemptions at
    all, which would silently delete the #584 disclosure for every gate that
    legitimately bought one.  This is the arm that goes red if it does.
    """
    _, doc = _run(tmp_path,
                  'uncheckable_until 2999-01-01 "a declared missing prerequisite"\n'
                  'run_tolerating_uncheckable "a tolerated gate" "$ROOT" '
                  'bash -c "exit 2"\n')
    rows = [g for g in doc["gates"] if g["label"] == "a tolerated gate"]
    assert len(rows) == 1, doc["gates"]
    row = rows[0]

    assert row["state"] == "NOT_CHECKED", row
    assert row["exempt_until"] == "2999-01-01", row
    assert row["exempt_reason"] == "a declared missing prerequisite", row
    assert doc["not_checked_unexempted"] == [], doc
    assert doc["wiring_errors"] == [], doc


# --------------------------------------------------------------------------
# vibe-ic#1789 -- the same row, at the field that says whether a PROCESS ran
# --------------------------------------------------------------------------
# The empty-corpus population refusal above EXECUTES a gate: `_dispatch` mode 2
# runs `_gate_dispatch_population_refusal` and the run writes one process
# attestation for it. The phase-1 legacy synthetic row for the same empty corpus
# executes nothing and writes none -- and until now the record could not tell
# them apart, because they share the label, the `EXPANDED` expansion, `items: 0`
# and `gates: 1`. `repo_hygiene_parallel._legacy_empty_without_process` read
# that shape, answered "no process here" for the attested row too, and the
# parallel run then reported its own gate as an "unassigned gate label in
# attestation progress" and refused itself (5 of 80 wiring errors on clean main
# fd8dec469, every run).
#
# Arm A pins the flag on the refusal. Arm B is the control and is the reason
# Arm A cannot be satisfied by writing `true` everywhere.
def test_the_population_refusal_records_that_it_is_one(tmp_path):
    """ARM A. The row a process attestation is expected for says so."""
    _, doc = _run(tmp_path, _EMPTY_POPULATION)
    row = _population_row(doc)

    assert row["blocking_refusal"] is True, (
        "the dispatcher ran a process for this row and the record does not "
        f"say so, leaving the consumer nothing to read: {row!r}")
    assert row["state"] == "NOT_CHECKED", row


def test_an_ordinary_gate_is_not_recorded_as_a_population_refusal(tmp_path):
    """ARM B -- the control.

    A dispatcher that wrote `blocking_refusal: true` for every gate would pass
    Arm A and would make the field useless, so the ordinary gate is asserted
    too. Both spellings of an ordinary gate are covered: a plain `run` and one
    that legitimately bought an exemption.
    """
    _, doc = _run(tmp_path,
                  'run "an ordinary gate" "$ROOT" true\n'
                  'uncheckable_until 2999-01-01 "a declared missing prerequisite"\n'
                  'run_tolerating_uncheckable "a tolerated gate" "$ROOT" '
                  'bash -c "exit 2"\n')
    by_label = {g["label"]: g for g in doc["gates"]}

    assert by_label["an ordinary gate"]["blocking_refusal"] is False, by_label
    assert by_label["a tolerated gate"]["blocking_refusal"] is False, by_label
    assert doc["wiring_errors"] == [], doc


def test_every_gate_row_carries_the_flag(tmp_path):
    """It is ALWAYS present, so an absent key is never ambiguous.

    A key written only for the refusal would leave a reader unable to tell "not
    a refusal" from "written by an older script" -- the same reason
    `exempt_until` and `scope` are unconditional.
    """
    _, doc = _run(tmp_path, 'run "an ordinary gate" "$ROOT" true\n'
                  + _EMPTY_POPULATION)

    assert doc["gates"], doc
    assert all("blocking_refusal" in g for g in doc["gates"]), doc["gates"]
    assert all(isinstance(g["blocking_refusal"], bool) for g in doc["gates"]), \
        doc["gates"]
