"""A dispatcher-owned population refusal must not be purchasable with a date.

WHY THIS TEST EXISTS
====================
On 2026-08-22, `origin/main` carried exactly one BLOCKING NOT_CHECKED row with
no exemption::

    ^^ NOT CHECKED (rc 2, BLOCKING; no exemption): corpus "published cells
       carrying a routed DEF" is EMPTY — nothing was checked over it
       [population: producer rc 0, 0 item(s) over ...]

`docs/findings/2026-08-22-routed-def-corpus-adjudication.md` adjudicates it: the
population is zero because the published-corpus repository WITHDREW all four
published cells on 2026-08-20, and the row is the correct verdict and should
stay red until one is republished. That adjudication explicitly declines to buy
the row off with `uncheckable_until`, and the reason it can decline is not
taste — it is that `_dispatch` REFUSES the purchase by construction:

    "<label>" is a dispatcher-owned population refusal and cannot consume an
    uncheckable exemption — an unknown denominator must remain blocking

WHAT THIS FILE ADDS, STATED AFTER MEASURING IT
=============================================
An earlier revision of this docstring said the refusal was UNPINNED. **It is
not, on this base.** `test_routed_def_corpus_dispatch.py::
test_a_population_refusal_cannot_buy_an_uncheckable_exemption` landed in
`e1b98d8f9` (2026-08-22 00:06, closing #1763) and pins exactly that arm. The
claim was true of the tree the earlier lineage measured and false of this one,
so it is replaced here by what was measured rather than assumed.

MEASURED by deleting the mode-2 `elif` from the TRACKED dispatcher and restoring
it with a reverse edit (`sha256 e4088103...` identical before and after):

    test                                              control   arm deleted
    base test_a_population_refusal_cannot_buy_...       pass        FAIL
    ARM A  test_an_exemption_cannot_buy_off_...         pass        FAIL
    ARM C  test_a_refused_exemption_does_not_leak_...   pass        pass

So, honestly:

* ARM A2 is new subject matter. It states the record/console contradiction as a
  DEFECT to be repaired rather than as behaviour to be characterised, and is
  filed as vibe-ic#1770. The base test asserts the SAME hazard as today's
  behaviour, from the opposite direction, so the two move together: the repair
  reddens the base test and XPASSes this one.
* ARM C is new subject matter and is NOT about this arm -- it survives the
  mutation, as the third row says. It pins the #584 no-leak property on the
  mode-2 path specifically.
* ARMs A and B OVERLAP the base test. They drive the dispatcher without
  `--shard`, so they are an independent driver of the same subject, kept as
  controls. They are not coverage this file introduced and are not claimed as
  such.

The half of the original claim that survives: the general empty-corpus tests
(`test_empty_corpus_gate_keeps_the_array_invariant`,
`test_issue1025_empty_corpus_sweep_blocks`, `test_issue1075_...`) do all drive
the loop with NO exemption armed and are verdict-identical across the mutation.
That is why the base test had to be written at all.

Deleting it is a one-line change with a silent blast radius: an
`uncheckable_until` written at the wiring site would then be CONSUMED by the
structural row, the roll-up would print `(exempt until <date>)` instead of
`(NO EXEMPTION DECLARED)`, `nunexempted` would stay 0, and the sweep would exit
0. The one row on the board that says post-route geometry is checked over
nothing would go quiet with a date on it — which is precisely the shape
`repo_hygiene_gates.sh` already records against THIS corpus, where four
per-cell gates were once absorbed under exemptions whose stated reasons were
all false.

Driven through the REAL `tools/ci/_gate_dispatch.sh` — the verdicts are read
out of a live shell, not reasoned about from the source.

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

#: The real corpus this test is about. Named so a reader of a failure lands on
#: the adjudication rather than on an abstract "some corpus".
_CORPUS = "published cells carrying a routed DEF"

#: Natural completion is the evidence; a clock expiry would prove nothing about
#: whether the structural row was recorded.
pytestmark = pytest.mark.timeout(0)


def _run(root: Path, body: str):
    """Drive the real dispatcher over `body` and return (proc, record)."""
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
    doc = (json.loads(rec.read_text(encoding="utf-8"))
           if rec.is_file() and rec.stat().st_size else None)
    return proc, doc


#: An attested-population loop whose producer prints nothing: rc 0, zero items.
#: This is byte-for-byte the state `routed_def_corpus.py` reports today.
_EMPTY_LOOP = (
    'run "a flat gate" "$ROOT" true\n'
    '_body() { run "per item ($1)" "$ROOT" true; }\n'
    f'gate_dispatch_over "{_CORPUS}" _body printf ""\n')

_ARMED_EMPTY_LOOP = (
    'run "a flat gate" "$ROOT" true\n'
    '_body() { run "per item ($1)" "$ROOT" true; }\n'
    'uncheckable_until 2999-01-01 "the published corpus is empty right now"\n'
    f'gate_dispatch_over "{_CORPUS}" _body printf ""\n')


def _row(doc, corpus=_CORPUS):
    """The structural population row out of the summary record."""
    assert doc is not None, "the dispatcher wrote no summary record"
    rows = [g for g in (doc.get("gates") or [])
            if corpus in str(g.get("label", "")) and "EMPTY" in str(g.get("label", ""))]
    assert len(rows) == 1, json.dumps(doc.get("gates"), indent=1)
    return rows[0]


def test_an_exemption_cannot_buy_off_an_empty_population_refusal(tmp_path):
    """ARM A — the guard the adjudication actually leans on.

    An `uncheckable_until` armed in front of an attested-population loop whose
    corpus is empty must be REFUSED, in those words, and the run must not
    certify. This is what makes "not an exemption" a structural fact rather
    than a preference.
    """
    proc, doc = _run(tmp_path, _ARMED_EMPTY_LOOP)
    text = proc.stdout + proc.stderr

    wiring = [ln for ln in text.splitlines() if "WIRING ERROR" in ln]
    assert wiring, (
        "an uncheckable_until was armed in front of a dispatcher-owned "
        "population refusal and the dispatcher accepted it in silence; the "
        "one blocking row can now be bought off with a date\n" + text)
    assert any("population refusal" in ln and "uncheckable exemption" in ln
               for ln in wiring), wiring

    row = _row(doc)
    assert row["state"] == "NOT_CHECKED", row
    assert proc.returncode != 0, (
        "the sweep certified a run in which the only population it declared "
        "was never examined\n" + text)
    # The refusal must also survive into the record, because that is what the
    # landing consumers read. `wiring_errors` is the channel every one of them
    # (`gatekeeper_review`, `repo_hygiene_parallel`, `hygiene_finding_delta`)
    # refuses on.
    assert doc.get("wiring_errors"), (
        "the console refused the purchase and the record kept no trace of it, "
        f"so a record-reading consumer cannot see it: {json.dumps(doc)[:400]}")


@pytest.mark.xfail(strict=True, reason=(
    "MEASURED DEFECT 2026-08-22, filed as vibe-ic#1770, not fixed. "
    "`_dispatch` raises the "
    "wiring error for a mode-2 population refusal and then appends the date "
    "to GATE_EX_UNTIL anyway, so the record states the refused exemption as a "
    "GRANTED one: exempt_until=2999-01-01, exemption_expired=false, and "
    "not_checked_unexempted=[] for the very row the dispatcher had just "
    "declared unexemptable. The printed line for the same row says "
    "'BLOCKING; no exemption' — the console and the record give opposite "
    "answers about the same gate. Nothing is unsafe TODAY only because every "
    "consumer independently refuses on `wiring_errors`; the field NAMED for "
    "this question is wrong, and gatekeeper_review's own comment documents "
    "not_checked_unexempted as the FAIL-SAFE derivation. The fix is one line "
    "in _dispatch (append \"\" instead of $ex_until on the refused branch) "
    "and is strictly tightening, but tools/ci/_gate_dispatch.sh is inside "
    "REQUIRED_AUTHORITY_PATHS in protected_landing_transition.py, so it can "
    "only move through a base-authorised PREPARE/ACTIVATE transition and not "
    "through this candidate. STRICT: when it is fixed this XPASSes and this "
    "marker must be deleted -- AND SO MUST THE LAST TWO ASSERTIONS OF "
    "test_a_population_refusal_cannot_buy_an_uncheckable_exemption, which "
    "pins the same hazard as CURRENT behaviour and reddens on the repair. "
    "See vibe-ic#1770 and "
    "docs/findings/2026-08-22-routed-def-corpus-adjudication.md."))
def test_the_record_does_not_state_a_refused_exemption_as_a_granted_one(tmp_path):
    """ARM A2 — the record must agree with the sentence the dispatcher printed.

    The steelman for today's behaviour is that the record faithfully reports
    what the wiring site DECLARED, and that the adjudication of it lives in
    `wiring_errors`. It does not hold: `not_checked_unexempted` is not a
    declaration record, it is the derived verdict every landing consumer reads
    to answer exactly this question, and it currently answers "bought".
    """
    _, doc = _run(tmp_path, _ARMED_EMPTY_LOOP)
    row = _row(doc)

    assert not row.get("exempt_until"), (
        "the population refusal carries an exemption date, so to every "
        f"record-reading consumer an empty corpus is a bought refusal: {row}")
    assert row["label"] in (doc.get("not_checked_unexempted") or []), (
        "the row the dispatcher declared unexemptable is absent from "
        "not_checked_unexempted, which is the list gatekeeper_review, "
        "repo_hygiene_parallel and hygiene_finding_delta each read to decide "
        f"whether an unbought refusal blocks: {doc.get('not_checked_unexempted')}")


def test_the_refusal_is_caused_by_the_exemption_and_not_by_the_shape(tmp_path):
    """ARM B — the control ARM A is worthless without.

    The same empty loop with NO exemption armed must still block, and must NOT
    report a wiring error. Without this, ARM A is satisfied by a dispatcher
    that has started calling every attested-population loop mis-wired.
    """
    proc, doc = _run(tmp_path, _EMPTY_LOOP)
    text = proc.stdout + proc.stderr

    assert "WIRING ERROR" not in text, (
        "an ordinary attested-population loop is now reported as mis-wired, "
        "so ARM A proves nothing about the exemption\n" + text)
    row = _row(doc)
    assert row["state"] == "NOT_CHECKED", row
    assert not row.get("exempt_until"), row
    assert proc.returncode != 0, text
    assert any("UNEXEMPTED NOT_CHECKED" in ln for ln in text.splitlines()), (
        "the empty population no longer reaches the roll-up as an unexempted "
        "blocking refusal\n" + text)


def test_a_refused_exemption_does_not_leak_onto_the_next_gate(tmp_path):
    """ARM C — refusing the purchase must not leave the exemption armed.

    `_dispatch` consumes the pending exemption FIRST and unconditionally
    (vibe-ic#584) precisely so an exemption written for gate N cannot silently
    excuse gate N+1. If the refusal branch ever returns before that consume,
    the date written for the population row would land on whatever gate runs
    next — a refusal bought for a gate nobody wrote it for.
    """
    proc, doc = _run(
        tmp_path,
        _ARMED_EMPTY_LOOP +
        'run_tolerating_uncheckable "the next gate along" "$ROOT" '
        'bash -c "exit 2"\n')
    text = proc.stdout + proc.stderr
    assert doc is not None, text

    following = [g for g in (doc.get("gates") or [])
                 if g.get("label") == "the next gate along"]
    assert len(following) == 1, json.dumps(doc.get("gates"), indent=1)
    assert not following[0].get("exempt_until"), (
        "the exemption refused by the population row leaked onto the gate "
        f"after it: {following[0]}")
    # It is itself mis-wired (a tolerating wrapper with no exemption of its
    # own), which is the correct complaint and is what proves the leak did not
    # happen.
    assert any("tolerance has to be bought, not defaulted into" in ln
               for ln in text.splitlines()), text
