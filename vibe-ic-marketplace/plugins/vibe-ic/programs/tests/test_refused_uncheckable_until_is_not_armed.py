"""An `uncheckable_until` the dispatcher REFUSED must not be armed anyway.

WHY THIS TEST EXISTS
====================
`uncheckable_until` refuses three things in words — an exemption left over from
a previous gate, a review date that is not ISO-8601, and an exemption with no
stated reason — and then arms the exemption regardless::

    if ! [[ "$until" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
      _gate_wiring_error "'uncheckable_until …': the review date must be \
ISO-8601 YYYY-MM-DD"
    fi
    …
    GATE_PENDING_UNTIL="$until"; GATE_PENDING_WHY="$why"    # <-- runs anyway

`_gate_wiring_error` appends to `GATE_WIRING_ERRORS` and RETURNS; it does not
exit. So the assignment on the last line is reached on every path, and the date
the dispatcher has just declared unusable is handed to the next gate as though
it had been accepted.

This is the same shape as vibe-ic#1770 — a write that sits outside the branch
deciding whether it should happen — found by sweeping the file that #1770 is
about. It is NOT the same instance, and #1770's fix does not touch it: that fix
clears the refused value on `_dispatch`'s mode-2 arm, while this one arms a
pending exemption that then reaches an ordinary `run_tolerating_uncheckable`
gate and is recorded through the granted path. Measured 2026-08-22 against both
the shipped dispatcher and a locally fixed one: identical records.

WHY IT IS WORSE THAN THE INSTANCE THAT WAS FILED
================================================
#1770's combination — an `uncheckable_until` in front of a dispatcher-owned
population refusal — is armed nowhere in the tree today. A mistyped date or a
forgotten reason is available at every wiring site in every gate script.

And the refused value does not merely get recorded, it becomes PERMANENT.
Expiry is a lexicographic compare against today::

    if [ -n "${GATE_EX_UNTIL[$i]}" ] \
       && [[ "${GATE_EX_UNTIL[$i]}" < "$GATE_DISPATCH_TODAY" ]]; then

A refused non-ISO string such as `never` sorts ABOVE every real YYYY-MM-DD, so
the exemption appears in neither `exemptions_expired` nor
`not_checked_unexempted`, and no future date will ever put it there. The
ISO-8601 rule exists precisely so that "the expiry comparison can be a plain
string compare"; refusing a string in words and then feeding it to that compare
anyway is what removes the expiry half of the mechanism.

Nothing is unsafe today only because the run still exits 2 on `wiring_errors`.
`test_a_properly_bought_exemption_is_still_accepted` is the measurement that
makes that dependency visible rather than assumed: with a VALID exemption the
same probe exits 0, so `wiring_errors` is the only thing separating a refused
purchase from a granted one.

Driven through the REAL `tools/ci/_gate_dispatch.sh` — the verdicts are read out
of a live shell, not reasoned about from the source.

chip-AGNOSTIC: pure dispatcher plumbing. No design, PDK, vendor or SKU literal.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"

#: Natural completion is the evidence; a clock expiry would prove nothing about
#: whether the pending exemption was armed.
pytestmark = pytest.mark.timeout(0)

#: The gate the exemption is armed in front of. It reports rc 2, so it is the
#: one gate in the probe whose verdict an exemption can change.
_PROBE = "the gate under probe"


def _run(root: Path, declaration: str):
    """Drive the real dispatcher with `declaration` armed, return (proc, doc)."""
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    script = root / "tools" / "ci" / "gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        run "an ordinary decided gate" "$ROOT" true
        {declaration}
        run_tolerating_uncheckable "{_PROBE}" "$ROOT" bash -c "exit 2"
        gate_dispatch_finish
        """))
    rec = root / "record.json"
    proc = subprocess.run(
        ["bash", str(script), "--summary-json", str(rec)],
        cwd=str(root), env=os.environ.copy(), capture_output=True, text=True)
    doc = (json.loads(rec.read_text(encoding="utf-8"))
           if rec.is_file() and rec.stat().st_size else None)
    return proc, doc


def _probe_row(doc):
    assert doc is not None, "the dispatcher wrote no summary record"
    rows = [g for g in (doc.get("gates") or []) if g.get("label") == _PROBE]
    assert len(rows) == 1, json.dumps(doc.get("gates"), indent=1)
    return rows[0]


def test_a_malformed_review_date_is_refused_in_words(tmp_path):
    """ARM A — the refusal the end state is asserted against must actually fire.

    Without this, the xfail arm below could be satisfied one day by a
    dispatcher that had stopped refusing malformed dates at all, which is the
    opposite of the intended repair.
    """
    proc, doc = _run(tmp_path, 'uncheckable_until never "a stated reason"')
    text = proc.stdout + proc.stderr

    assert any("must be ISO-8601" in ln for ln in text.splitlines()), text
    assert any("must be ISO-8601" in str(err)
               for err in (doc.get("wiring_errors") or [])), doc
    assert proc.returncode != 0, (
        "a run carrying a refused exemption certified the tree\n" + text)


def test_an_exemption_with_no_stated_reason_is_refused_in_words(tmp_path):
    """ARM A' — the second refusal, same construction, same requirement."""
    proc, doc = _run(tmp_path, 'uncheckable_until 2999-01-01 ""')
    text = proc.stdout + proc.stderr

    assert any("must state WHY" in ln for ln in text.splitlines()), text
    assert any("must state WHY" in str(err)
               for err in (doc.get("wiring_errors") or [])), doc
    assert proc.returncode != 0, text


def test_a_properly_bought_exemption_is_still_accepted(tmp_path):
    """ARM B — the control without which ARM A proves nothing.

    A guard that refuses everything satisfies every refusal assertion above. A
    correctly declared exemption must still be granted, be recorded, and let
    the run exit 0 — and that exit code is also the measurement showing that
    `wiring_errors` is the ONLY thing refusing the runs in ARM A and ARM A'.
    """
    proc, doc = _run(
        tmp_path, 'uncheckable_until 2999-01-01 "a stated reason"')
    text = proc.stdout + proc.stderr

    assert not (doc.get("wiring_errors") or []), doc["wiring_errors"]
    row = _probe_row(doc)
    assert row["state"] == "NOT_CHECKED", row
    assert row["exempt_until"] == "2999-01-01", row
    assert row["exempt_reason"] == "a stated reason", row
    assert proc.returncode == 0, (
        "a correctly bought exemption no longer lets the run certify, so the "
        "refused arms above are not measuring the exemption\n" + text)


@pytest.mark.xfail(strict=True, reason=(
    "MEASURED DEFECT 2026-08-22, found by sweeping tools/ci/_gate_dispatch.sh "
    "for the shape vibe-ic#1770 reports. `uncheckable_until` raises the wiring "
    "error for a malformed date and for a missing reason and then arms "
    "GATE_PENDING_UNTIL/GATE_PENDING_WHY anyway, because the assignment sits "
    "outside every `if`. The record is byte-identical to a properly bought "
    "exemption: exempt_until is set, the row leaves not_checked_unexempted, "
    "and for a non-ISO string the lexicographic expiry compare can never fire, "
    "so the exemption is immortal. Nothing is unsafe TODAY only because the "
    "run still exits 2 on wiring_errors -- see "
    "test_a_properly_bought_exemption_is_still_accepted for that dependency "
    "measured rather than asserted. The fix is the same one line in shape as "
    "#1770's (clear the value in the branch that refused it), but "
    "tools/ci/_gate_dispatch.sh is inside REQUIRED_AUTHORITY_PATHS in "
    "protected_landing_transition.py, so it can only move through a "
    "base-authorised PREPARE/ACTIVATE transition -- and at ae78abb28 no "
    "transition can be built at all: build_receipt refuses a NULL transition "
    "(base == candidate == main) because the live 47-tuple matches neither "
    "authorised state on 12 paths. #1770's own fix does NOT close this: it "
    "clears _dispatch's mode-2 arm, measured to leave both records here "
    "unchanged. STRICT: when it is fixed this XPASSes and this marker must be "
    "deleted. See "
    "docs/findings/2026-08-22-a-refused-exemption-is-recorded-as-a-granted-one.md."))
@pytest.mark.parametrize("declaration,refusal", [
    ('uncheckable_until never "a stated reason"', "must be ISO-8601"),
    ('uncheckable_until 2999-01-01 ""', "must state WHY"),
])
def test_the_record_does_not_arm_an_exemption_the_dispatcher_refused(
        tmp_path, declaration, refusal):
    """ARM C — the record must agree with the sentence the dispatcher printed.

    The steelman for today's behaviour is that the record faithfully reports
    what the wiring site DECLARED and that the adjudication of it lives in
    `wiring_errors`. It does not hold. `not_checked_unexempted` is not a
    declaration record; it is the derived verdict `gatekeeper_review`,
    `repo_hygiene_parallel` and `hygiene_finding_delta` each read to decide
    whether an unbought refusal blocks, and gatekeeper_review's own comment
    documents it as the FAIL-SAFE derivation. Here a date that was never
    granted defeats it.
    """
    proc, doc = _run(tmp_path, declaration)
    assert any(refusal in str(err) for err in (doc.get("wiring_errors") or [])), (
        "the probe did not reach the refusal it is about, so its verdict on "
        f"the record would mean nothing: {doc.get('wiring_errors')}")

    row = _probe_row(doc)
    assert not row.get("exempt_until"), (
        "the dispatcher refused this exemption in words and armed it anyway, "
        "so to every record-reading consumer the gate bought its tolerance: "
        f"{row}")
    assert row["label"] in (doc.get("not_checked_unexempted") or []), (
        "the gate whose exemption was refused is absent from "
        "not_checked_unexempted, which is the list every landing consumer "
        "reads to decide whether an unbought refusal blocks: "
        f"{doc.get('not_checked_unexempted')}")
