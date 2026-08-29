#!/usr/bin/env python3
"""gate_red_since_check.py — an acknowledged red must EXPIRE. vibe-ic#1025.

WHY THIS PROGRAM EXISTS
=======================
`tools/ci/_gate_dispatch.sh` states a doctrine, in a comment, at the line where
it decides to exit 0 over a gate that refused:

    a permanently red gate is a gate that gets skipped

MEASURED 2026-08-12, that sentence is enforced by nothing.

  * The only machinery created in its name is `run_tolerating_uncheckable`,
    which maps rc 2 to a non-fatal NOT_CHECKED. That is a decision about ONE
    run. It has no notion of duration, so it cannot answer — and was never
    built to answer — "has this gate been red since before anyone stopped
    reading?".
  * The record that could answer it is DESTROYED. The single production writer
    of `--summary-json` is `gatekeeper_review.repo_hygiene_gate`, which writes
    it into a `tempfile.TemporaryDirectory` and lets the directory be removed
    when the `with` block exits. Nothing compares two records; there is no
    second record to compare to.
  * `_hygiene_verdict` folds NOT_CHECKED into prose (`; N NOT CHECKED (not a
    pass): ...`) and returns rc 0 regardless.

So the doctrine is spent rather than enforced: it is quoted to JUSTIFY leniency
(exit 0) while the obligation that leniency creates — that somebody notice and
close the gap — is owed to no one and comes due never. A rule stated where it
cannot act is the same defect as a check that lies, one level up.

WHAT THIS PROGRAM DOES, AND THE ONE THING IT REFUSES TO DO
==========================================================
It reads the dispatcher's OWN record and a tracked ledger of acknowledged reds,
and it answers one question: is every red in this run either NEW, or owned by
an acknowledgement that has not yet expired?

It can only ever ADD a failure. It cannot turn a red gate green, and that is a
deliberate structural property, not a policy:

  * the hygiene suite still exits 1 for every FAIL, exactly as before. A ledger
    row grants NO leniency to the gate it names;
  * a ledger row is therefore never worth adding to silence anything — there is
    nothing to silence. The only thing a row does is start a clock that this
    program will later fail on.

That direction is the whole design. A register that can make a gate green by
gaining a row is the shape that turns a baseline into a place to hide numbers;
this one has no such power, so raising the ledger can never buy a green.

WHAT FAILS
==========
  L1 incomplete   a row without `gate` / `since` / `since_date` / `max_days`.
                  An acknowledgement with no bound is the thing being removed,
                  so it cannot be written.
  L2 stale        a row naming a gate that is now PASS (or absent from the
                  record). The fix landed and the row outlived its truth — a
                  stale acknowledgement is indistinguishable, to the next
                  reader, from a live one, and it is the row that will be
                  believed. Delete it in the commit that fixes the gate.
  L3 expired      `since` is more than `max_days` days behind the endpoint.
                  This is the deadline actually biting, and it is the only
                  reason this program exists rather than a report.
  L4 misdated     `since_date` is not the date of the commit `since` names.
                  The row states one thing about itself and its own anchor
                  states another, and a reader has no way to tell which half is
                  the typo.

AND ONE THAT IS NOT A FINDING ABOUT THE TREE — rc 2, NOT CHECKED:

  U1 unresolvable a row citing a commit this repository does not contain, or
                  one whose date cannot be read. The age cannot be computed, so
                  the bound cannot be enforced, and "I could not check the
                  deadline" must not read as "the deadline is fine" — nor as
                  "the deadline has passed". It is not graded in either
                  direction, and the row is NAMED.
  U2 superseded   a row still carrying `max_commits` and no `max_days`, written
                  under the clock this program replaced. Refusing it as
                  `incomplete` would blame a row that was correct when written.

THE CLOCK IS A DATE, AND IT USED TO BE A COMMIT COUNT (measured 2026-08-22)
==========================================================================
The age was `git rev-list --count <since>..<head>`, which is a property of the
MERGE TOPOLOGY and not of the promise. MEASURED on a 97-branch assembly: every
merged branch's commits fall inside that range, so the five shipped rows read
1590-2109 commits against bounds of 140-210 and all five would have been called
EXPIRED — by an assembly none of their authors had anything to do with. An
acknowledgement that was fine yesterday must not expire because someone else
merged 97 branches today.

`--first-parent` is not the repair: three of the five `since` shas are not on
the head's first-parent chain, so it would silently mis-age exactly those three
while looking like it had fixed the problem.

How stale a promise is, is a property of WHEN IT WAS MADE. So the row records
`since_date`, the bound is a duration in days, and the age is the elapsed time
between that date and the endpoint's own commit date. A merge moves neither.

WHY THE ENDPOINT IS STILL A REF AND NOT THE WALL CLOCK. `--head-ref` exists so
a landing counts to its BASE (see `git_age_days`), and the same tree read twice
must give the same verdict. Reading `datetime.now()` would make the answer
depend on when it was asked, which is the property this file's `_doc` block was
protecting when it chose commits in the first place. Dates keep it: two readers
of the same (tree, endpoint) pair still compute the same age.

MIGRATING THE FIVE SHIPPED ROWS CHANGED WHAT NONE OF THEM PROMISES. Each row
had already stated its bound in days in its own `bound_because` — "210 commits
is three days at the measured rate", "140 commits is two days", "200 commits is
~2.6 days" — so the duration is the row's own number, carried over unrounded.
Cross-checked against the authors' intent from the other side: the ~78
commits/day they measured is this history's FIRST-PARENT cadence, and under it
the two rows that expire by date (6.1 days old, bounds of 3 and 2) also expire
by first-parent count (432 commits, bounds of 210 and 140), while the three that
survive by date survive by first-parent count too (163, bound 200). The two
clocks agree on all five; only the 97-branch full count disagreed with both.

WHAT IS REPORTED BUT DOES NOT FAIL
==================================
The partition of this run's red gates into KNOWN (owned by a live row) and NEW
(owned by nobody). A NEW red is not failed HERE because the suite has already
failed it — reporting it twice would say nothing extra. What the partition buys
is the thing the doctrine was worried about: when N gates are red every run, a
reader can see which of them is red for the first time TODAY, instead of
scanning a wall of red that looks the same as yesterday's.

VACUITY (the rule this program is itself subject to)
====================================================
A record that declares 0 gates, or one taken under `--list` where no gate
actually ran, cannot support any judgement about redness. Both route rc 2 +
`VACUOUS_PASS:` through the shipped `_vacuous_exit` convention rather than
returning 0 — this program refuses over an empty population for the same reason
it exists to make other gates refuse over one.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import (Any, Callable, Dict, Iterable, List, Optional, Sequence,
                    Tuple)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _vacuous_exit as _vx  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

#: States the dispatcher can record. Everything that is not PASS and not LISTED
#: is RED for this program's purpose: a gate that FAILED, one that REFUSED
#: (NOT_CHECKED), and one that WROTE_CORPUS are all gates whose result a reader
#: has to act on. Lumping them is safe in the strict direction — it can only
#: keep an acknowledgement alive, never retire one early.
_PASS = "PASS"
_LISTED = "LISTED"
#: The ONE state `uncheckable_until` converts. `run_tolerating_uncheckable`
#: buys tolerance for rc 2 and for nothing else -- `_gate_dispatch.sh` maps a
#: gate's rc 2 to this, and every other non-zero rc to FAIL -- so it is also
#: the only state a dispatcher exemption can be said to OWN. See
#: `dispatcher_exemptions`.
_NOT_CHECKED = "NOT_CHECKED"
#: `_gate_dispatch.sh:711` — a gate this shard does not own. Sharding
#: (vibe-ic#1144) means a record can legitimately describe gates that did not
#: run in it.
_OTHER_SHARD = "OTHER_SHARD"

#: STATES A GATE REACHES BY ACTUALLY RUNNING A PROCESS. Mirrors
#: `hygiene_finding_delta.PROCESS_STATES`, and `test_gate_red_since_rows`
#: asserts the two agree — one name for one thing, checked rather than hoped.
#:
#: THE RULE IS "DID IT RUN", NOT A LIST OF EXCEPTIONS (measured 2026-08-22).
#: This started as `s not in (_PASS, _LISTED)`, which made `OTHER_SHARD` count
#: as red — a real shard record carries 79 of them beside 8 FAIL — and, worse,
#: let a row be reported EXPIRED for a gate that was never executed. Adding
#: `OTHER_SHARD` to the exception list fixed that instance and left the rule:
#: the dispatcher also records `OUT_OF_SCOPE` (a declared skip) and `QUEUED` (a
#: gate still waiting), and both would have fallen through the same way.
#:
#: Stated as the positive set so a state added to `_gate_dispatch.sh` later is
#: NOT adjudicable by default rather than silently overdue by default. The
#: fail-safe direction for "I do not recognise this state" is "I cannot judge
#: it", never "it is red".
_RAN = ("PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS")


def _did_not_run(state: Optional[str]) -> bool:
    """True when the record says this gate did not reach a verdict of its own.

    Neither `expired` nor `stale` is something such a record could honestly say
    about the gate, so this program says neither and names the row instead.
    """
    return state is not None and state not in _RAN

#: Ledger location, relative to the repository root.
LEDGER_REL = "tools/ci/gate_red_since.json"

_REQUIRED_KEYS = ("gate", "since", "since_date", "max_days")

#: The field the duration clock REPLACED, kept only so a row written under the
#: previous contract is recognised as such and refused as UNDETERMINED rather
#: than silently read as unbounded. See `_SUPERSEDED`.
_SUPERSEDED_BOUND_KEY = "max_commits"

#: The largest bound that is still a bound. MEASURED while probing this
#: program against itself: a row with an unreachable bound satisfies every
#: other rule here and never expires, so the mechanism can be switched off by
#: editing the file it adjudicates — the same "wired where it can never
#: block" shape it exists to catch. The ceiling does not forbid a long
#: remediation; it forbids an unattended one. A red that genuinely needs
#: longer is renewed by moving `since` forward, which is a visible act that
#: shows up in review, rather than a number nobody reads again.
#:
#: DERIVED FROM THE CEILING IT REPLACED, ROUNDED DOWN. The previous ceiling was
#: 500 commits, and the ledger's own rows measured this repository's cadence at
#: ~78 commits/day, so 500 commits is 6.41 days. It is floored to 6 rather than
#: rounded to the nearest whole day: rounding a CEILING up is a loosening, and
#: this migration is not allowed to loosen anything. Every shipped row's bound
#: is 3 days or less, so the floor binds none of them.
MAX_BOUND_DAYS = 6.0


#: Finding kinds that are NOT a judgement about the tree. A row this program
#: could not age has told it nothing, and grading it in EITHER direction is the
#: defect: "expired" invents a verdict from a failed read, "fine" hides one.
#: The CLI routes a run whose ONLY findings are these to rc 2 NOT CHECKED, and
#: names the rows. A real finding beside them still exits 1 — rc 2 is "I
#: reached no verdict", which stops being true the moment another row failed.
UNDETERMINED_KINDS = ("unresolvable", "superseded")

#: Seconds in a day. Named because the alternative is `86400` appearing in the
#: middle of an arithmetic expression that decides whether a deadline passed.
_SECONDS_PER_DAY = 86400.0


def _parse_iso(text: Optional[str]) -> Optional[datetime]:
    """An ISO-8601 timestamp WITH an offset, or None.

    A naive timestamp is refused rather than assumed to be UTC or local: this
    value is one end of a subtraction whose answer expires an acknowledgement,
    and guessing the zone would move that answer by up to a day in whichever
    direction the host happens to sit. `git` emits `%cI`, which always carries
    the offset, so the refusal costs a correctly-written row nothing.
    """
    if not text:
        return None
    raw = str(text).strip()
    if raw.endswith(("Z", "z")):            # `fromisoformat` rejects the
        raw = raw[:-1] + "+00:00"           # military form before 3.11
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _same_instant(a: Optional[str], b: Optional[str]) -> bool:
    """True when two ISO timestamps name the same moment.

    Compared as INSTANTS, not as strings: `2026-08-16T19:07:48+08:00` and
    `2026-08-16T11:07:48+00:00` are the same commit date written by two hosts
    in two zones, and failing a row over that would be a finding about
    `TZ` rather than about the acknowledgement. Unparseable on either side is
    False — a date this program cannot read is not a date it can confirm.
    """
    pa, pb = _parse_iso(a), _parse_iso(b)
    if pa is None or pb is None:
        return False
    return pa == pb


def _days(value: float) -> str:
    """A duration for humans: `3` rather than `3.0`, `2.6` rather than `2.6000000001`."""
    rounded = round(float(value), 1)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)


class Finding:
    """One reason this program fails, in the shape the CLI prints."""

    def __init__(self, kind: str, gate: str, detail: str) -> None:
        self.kind, self.gate, self.detail = kind, gate, detail

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Finding({self.kind!r}, {self.gate!r})"

    def line(self) -> str:
        return f"  [{self.kind}] {self.gate}: {self.detail}"


def load_ledger(path: Path) -> List[Dict[str, Any]]:
    """Read the acknowledgement ledger.

    An ABSENT ledger is an empty one, not an error: a tree that has never
    acknowledged a red is the normal starting state, and refusing to run
    without the file would make adopting this program a flag day.
    """
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("acknowledged")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError(f"{path}: 'acknowledged' must be a list")
    return [r for r in rows if isinstance(r, dict)]


def repository_is_shallow(repo: Path) -> Optional[int]:
    """Commit count when `repo` is a SHALLOW clone, else None.

    WHY THIS IS ASKED BEFORE ANYTHING IS ADJUDICATED (measured 2026-08-22).
    Every row dates its red by a commit, and the clock is
    `rev-list --count <since>..<head>`. In a `--depth` clone those commits are
    not present: measured on a `--depth 20` clone of this repository, BOTH the
    oldest and the newest `since` in the shipped ledger resolve to nothing.

    Adjudicated row by row that produces one `unresolvable` finding per row,
    each saying "this repository does not contain <sha>" — which is true, and
    which blames the ROWS for a truncated clone. Eight findings naming eight
    innocent commits and not one naming the cause.

    So it is asked once, up front, and refused once: rc 2, the state that means
    "I could not look", with the remedy that fixes it. That is the same shape
    as the landing runtime preflight, which refuses once rather than letting
    every arm fail the same way.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-shallow-repository"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        return None
    try:
        n = subprocess.run(["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
                           capture_output=True, text=True, timeout=30)
        return int(n.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0


def _describe_ref(repo: Path, ref: str) -> str:
    """`ref` resolved to a short sha, or a stated reason it could not be.

    Never an empty string and never a bare `ref`: a disclosure that silently
    degrades to repeating its input tells a reader nothing they did not type.
    """
    try:
        proc = subprocess.run(["git", "-C", str(repo), "rev-parse",
                               "--short", ref],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"UNRESOLVABLE: {exc}"
    if proc.returncode != 0:
        return "UNRESOLVABLE: " + (proc.stderr.strip().splitlines() or [""])[0][:80]
    return proc.stdout.strip() or "UNRESOLVABLE: empty"


class LedgerUnreadable(Exception):
    """The ledger could not be READ. Never a finding about the tree.

    SEPARATED FROM `ValueError`, WHICH THIS MODULE ALSO RAISES, BECAUSE THE TWO
    ARE GRADED DIFFERENTLY AND WERE NOT. `ValueError` here means the bytes were
    read and say something wrong -- `acknowledged` is not a list -- which is a
    defect of the tree at that ref and blocks. This means the bytes could not be
    obtained at all: no git, no repository, a ref that does not resolve. A gate
    that could not look has not found anything, and grading it BLOCKING is the
    "I could not check" -> "you fail" shape this repository has removed
    repeatedly.

    MEASURED (2026-08-22, this batch): `--ledger-ref` reads through `git show`,
    so in a fixture tree that is not a git repository the read fails and the
    whole merge gate returned REQUEST_CHANGES over a CLEAN tree --

        gate_red_since: [FAIL] unreadable ledger: cannot read
        tools/ci/gate_red_since.json at HEAD: fatal: not a git repository

    -- which is a refusal about the ENVIRONMENT wearing the words of a finding
    about the CANDIDATE. rc 2 UNDETERMINED, naming the path and the ref and
    git's own reason, is what that is. `gatekeeper_review.gate_red_since_gate`
    already routes rc 2 to `skipped`, so no caller had to change.
    """


def load_ledger_from_ref(repo: Path, ref: str) -> List[Dict[str, Any]]:
    """The ledger as it exists at `ref`, read with `git show`.

    WHY A REF AND NOT A PATH (2026-08-22). A landing adjudicates the CANDIDATE's
    reds against the BASE's ledger. Reading the candidate's own file lets a
    branch renew a row — move `since` forward — in the same commit that needs
    the renewal, which is authoring its own amnesty. `landing_merge_verdict`
    already states that rule for its copy of this ledger; this is the same rule
    on the path `gatekeeper_review` takes, which had it only for the clock
    (`--head-ref`) and not for the rows.

    A ref is used rather than a second worktree because the caller has a base
    REF and need not have a base checkout.

    A ledger that cannot be read AT THE REF IS NOT AN EMPTY ONE, unlike an
    absent ledger at a path: it is `LedgerUnreadable`, and the caller grades it
    rc 2 UNDETERMINED naming the path, the ref and git's own reason. It is NOT
    a finding — see that class for the measurement that changed this sentence.
    An empty `acknowledged` at a valid ref is still the normal starting state.
    """
    try:
        proc = _pr.run(
            ["git", "-C", str(repo), "show", f"{ref}:{LEDGER_REL}"],
            capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LedgerUnreadable(f"cannot read {LEDGER_REL} at {ref} in {repo}: "
                               f"{exc}") from exc
    if proc.returncode != 0:
        if "does not exist" in proc.stderr or "exists on disk" in proc.stderr:
            return []          # the ref predates the ledger: no acknowledgements
        raise LedgerUnreadable(f"cannot read {LEDGER_REL} at {ref} in {repo}: "
                               f"{proc.stderr.strip()[:200]}")
    doc = json.loads(proc.stdout)
    rows = doc.get("acknowledged")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError(f"{ref}:{LEDGER_REL}: 'acknowledged' must be a list")
    return [r for r in rows if isinstance(r, dict)]


def _states(record: Dict[str, Any]) -> Dict[str, str]:
    """Map gate label -> state, from the dispatcher's own record."""
    out: Dict[str, str] = {}
    for gate in record.get("gates") or []:
        if isinstance(gate, dict) and gate.get("label") is not None:
            out[str(gate["label"])] = str(gate.get("state") or "")
    return out


def dispatcher_exemptions(record: Dict[str, Any]) -> Dict[str, str]:
    """Gate label -> the dispatcher's own LIVE dated exemption, for the report.

    WHY THIS EXISTS (measured 2026-08-28, on a complete serial hygiene record
    of `main` at ae5cc4dbf). This program prints, of every red in the run:

        NEW red this run (owned by nobody): …

    and on that record it printed thirty of them. TWENTY of those thirty carry,
    IN THE SAME RECORD, an `exempt_until` of 2027-02-28 and an `exempt_reason`
    that is a written paragraph — a dated, reasoned, tracked acknowledgement
    made in `tools/ci/_gate_dispatch.sh`, which is the very thing this file's
    ledger exists to require. They are not owned by nobody. They are owned
    somewhere this program was not looking, and saying otherwise buries the
    TWELVE reds that genuinely have no owner inside a wall of thirty — which is
    the exact failure mode the NEW/KNOWN partition was built to end, one level
    up from the one it was built for.

    A LIVE EXEMPTION ONLY. `exemption_expired` is the dispatcher's own word for
    an exemption whose date has passed, and such a red belongs in the unowned
    bucket: an expired promise is the state this whole file exists to surface,
    so folding it in with the live ones would be the substitution in reverse.
    The dispatcher already refuses those separately (`not_checked_unexempted`,
    `exemptions_expired`); this only declines to double-count the live ones.

    AND ONLY OVER `NOT_CHECKED`, WHICH IS THE ONE STATE THE EXEMPTION
    CONVERTS (measured 2026-08-29). `_gate_dispatch.sh` stamps
    `exempt_until` on the row unconditionally, so a gate that FAILED carries
    the date too, and crediting that to the exemption reports a BLOCKING red
    as owned. See the branch below.

    IT CANNOT MOVE A VERDICT. The exit code is computed from `findings` alone —
    rows in the ledger, and nothing about `new` or `known` reaches it. This is
    a partition of a REPORT, and a gate that gains an exemption still fails the
    hygiene suite exactly as before, because a NOT_CHECKED red was never
    something this program failed on in the first place.
    """
    out: Dict[str, str] = {}
    for gate in record.get("gates") or []:
        if not isinstance(gate, dict) or gate.get("label") is None:
            continue
        until = gate.get("exempt_until")
        if not until or gate.get("exemption_expired"):
            continue
        if str(gate.get("state") or "") != _NOT_CHECKED:
            # AN EXEMPTION OWNS THE STATE IT CAN CONVERT, AND NO OTHER.
            #
            # `_gate_dispatch.sh` records `exempt_until` on the row
            # UNCONDITIONALLY -- the append happens beside the label, before
            # the gate has run -- so a gate wired with
            # `run_tolerating_uncheckable` carries its date whatever it then
            # returns. The TOLERANCE that date buys is rc 2 only: rc 1 is FAIL
            # and the suite exits 1 on it exactly as if no exemption had been
            # written.
            #
            # MEASURED 2026-08-29 on a real record of `L-doc field producer`,
            # wired `run_tolerating_uncheckable ... --corpus-may-be-absent`
            # under `uncheckable_until 2027-02-28`. On a host carrying the
            # published corpus it returns rc 1 and the record reads
            # `state: FAIL, exempt_until: 2027-02-28` -- and this function
            # credited it, so the CLI reported a BLOCKING red as "red, and
            # DATED by the dispatcher's own exemption". The exemption says
            # nothing about that state and could not excuse it if it did.
            #
            # This is the substitution the paragraph above forbids, arriving
            # from the other side: there an EXPIRED exemption must not read as
            # ownership; here a state the exemption never covered must not
            # either. The unowned bucket is the one that has to stay honest,
            # because it is the only one anybody acts on.
            continue
        out[str(gate["label"])] = str(until)
    return out


def record_is_vacuous(record: Dict[str, Any]) -> Optional[str]:
    """Why this record cannot support a judgement, or None if it can.

    Kept separate from `adjudicate` so the refusal is a first-class, testable
    conclusion rather than an early return buried in the adjudication.
    """
    if int(record.get("declared") or 0) == 0:
        return "the dispatch record declares 0 gate(s)"
    if record.get("listed_only"):
        return "the record was taken under --list; no gate actually ran"
    states = _states(record)
    if states and all(s == _LISTED for s in states.values()):
        return "every gate in the record is LISTED; no gate actually ran"
    return None


def adjudicate(record: Dict[str, Any],
               ledger: List[Dict[str, Any]],
               age: Callable[[str], Optional[float]],
               dated: Optional[Callable[[str], Optional[str]]] = None,
               ) -> Tuple[List[Finding], List[str], List[str]]:
    """The whole decision, as a pure function. Returns (findings, known, new).

    `age(sha) -> DAYS between that commit and the endpoint, or None if this
    repo does not contain it (or cannot date it)` is injected so every branch
    below is reachable from a test without building a git history per case —
    including U1, which by definition cannot be staged with a real commit.

    `dated(sha) -> that commit's own ISO date, or None` is optional and is used
    ONLY to cross-check the row's recorded `since_date` against its anchor. It
    cannot move the clock: the age comes from the repository either way, so a
    re-dated row buys nothing, and this check exists so a row cannot MISLEAD a
    human reader about how old it is. Absent, the cross-check is skipped and
    said to be skipped rather than reported as passed.
    """
    states = _states(record)
    findings: List[Finding] = []
    acknowledged_gates: set = set()

    for row in ledger:
        label = str(row.get("gate") or "")
        if (row.get("max_days") in (None, "")
                and row.get(_SUPERSEDED_BOUND_KEY) not in (None, "")):
            # WRITTEN UNDER THE CLOCK THIS PROGRAM REPLACED, and correct when
            # it was written. Calling it `incomplete` would blame the row for a
            # migration it could not have anticipated, and converting its
            # commit bound to days here would be this program inventing a
            # deadline nobody agreed to. It is acknowledged — so its gate does
            # not read as a NEW red owned by nobody — and NOT adjudicated.
            acknowledged_gates.add(label)
            findings.append(Finding(
                "superseded", label or "(unnamed row)",
                f"the row bounds itself with `{_SUPERSEDED_BOUND_KEY}: "
                f"{row.get(_SUPERSEDED_BOUND_KEY)!r}` and carries no "
                f"`max_days`. The clock is a duration now, because a commit "
                f"count is a property of the merge topology and expired all "
                f"five shipped rows on a 97-branch assembly. Migrate the row: "
                f"`since_date` = the date of commit {str(row.get('since'))[:12]}, "
                f"`max_days` = the duration this row's own `bound_because` "
                f"already states"))
            continue
        missing = [k for k in _REQUIRED_KEYS if row.get(k) in (None, "")]
        if missing:
            findings.append(Finding(
                "incomplete", label or "(unnamed row)",
                f"acknowledgement is missing {', '.join(missing)}. An "
                f"acknowledgement without a bound never comes due, which is "
                f"the state this ledger exists to end"))
            continue

        acknowledged_gates.add(label)
        state = states.get(label)
        if state is None:
            findings.append(Finding(
                "stale", label,
                "acknowledged, but no gate by this name ran in this record. "
                "Either the gate was removed or the label drifted; delete the "
                "row or repoint it"))
            continue
        if state == _PASS:
            findings.append(Finding(
                "stale", label,
                "acknowledged as red, but it PASSED in this run. Delete this "
                "row in the commit that fixed the gate — a row that outlives "
                "its truth is believed by the next reader"))
            continue
        if _did_not_run(state):
            # NOT ADJUDICABLE, and deliberately not a finding in either
            # direction: this record does not say whether the gate is red, so
            # neither "expired" nor "stale" is a thing it could honestly
            # report. The CLI names these rows so the silence is visible.
            continue

        since = str(row["since"])
        behind = age(since)
        if behind is None:
            findings.append(Finding(
                "unresolvable", label,
                f"the row cites commit {since[:12]}, which this repository "
                f"does not contain or cannot date, so its deadline cannot be "
                f"evaluated. NOT graded in either direction"))
            continue
        try:
            bound = float(row["max_days"])
        except (TypeError, ValueError):
            findings.append(Finding(
                "incomplete", label,
                f"max_days is not a number: {row['max_days']!r}"))
            continue
        if bound > MAX_BOUND_DAYS:
            findings.append(Finding(
                "unbounded", label,
                f"max_days is {_days(bound)}, beyond the "
                f"{_days(MAX_BOUND_DAYS)}-day ceiling. A deadline that cannot "
                f"arrive is not a deadline; renew the row by moving `since` "
                f"forward instead"))
            continue
        # THE CROSS-CHECK RUNS BEFORE THE DEADLINE, NOT INSTEAD OF IT. A row
        # whose stated date contradicts its own anchor is misreporting its age
        # to every human who reads it, and that is worth saying even on a row
        # that is comfortably inside its bound.
        stated = str(row["since_date"])
        actual = dated(since) if dated is not None else None
        if actual is not None and not _same_instant(stated, actual):
            findings.append(Finding(
                "misdated", label,
                f"the row records since_date {stated!r}, but commit "
                f"{since[:12]} is dated {actual!r}. The row and its own anchor "
                f"disagree about how old this acknowledgement is"))
            continue
        if behind > bound:
            findings.append(Finding(
                "expired", label,
                f"red since {since[:12]} ({stated}) — {_days(behind)} day(s) "
                f"ago, and the bound this row set for itself was "
                f"{_days(bound)}. {row.get('owner') or 'nobody'} owns it"))

    red = sorted(l for l, s in states.items()
                 if s != _PASS and not _did_not_run(s))
    known = [l for l in red if l in acknowledged_gates]
    new = [l for l in red if l not in acknowledged_gates]
    return findings, known, new


#: The kind, in `hygiene_finding_delta`'s vocabulary, that means a gate was
#: DISPATCHED AND BLOCKED. `WROTE_CORPUS` and `EXEMPTION_EXPIRED` are the other
#: two and neither is a red; `NOT_CHECKED` never reaches this list at all,
#: because a gate that could not look has its own dated exemption discipline in
#: `_gate_dispatch.sh`. Keying on this one string is what makes the rule below
#: apply to "declared always-run-and-BLOCKING" and to nothing else.
BLOCKING_KIND = "FAIL"


def inherited_red_reasons(
        carried: Iterable[Sequence[str]],
        ledger: List[Dict[str, Any]],
        age: Callable[[str], Optional[int]]) -> List[str]:
    """Refusal reasons for INHERITED blocking reds. For the landing verdict.

    `carried` is `hygiene_finding_delta`'s carried list — findings present on
    BOTH arms, which `landing_merge_verdict` today reports as
    "…carried (which do NOT block)". A carried `FAIL` is precisely a gate that
    was dispatched as blocking, went red, and has already survived at least one
    landing. This function is what makes surviving the SECOND one cost
    something.

    WHY THE GRACE FOR AN UNACKNOWLEDGED RED IS ZERO, AND WHY THAT IS NOT A
    CONSTANT SOMEBODY CHOSE
    -----------------------------------------------------------------------
    "Red for N commits" needs a FIRST-RED COMMIT to count from, and for a red
    nobody has acknowledged there is none: the dispatch record is written to a
    temporary directory and destroyed with the run, which is the gap this
    program's own module docstring opens with. So for an unacknowledged red the
    only honest values of N are 0 and infinity — anything in between would be a
    number computed from a history that does not exist. Infinity is the state
    being removed. Hence 0.

    The DECLARED N is `max_days`, per gate, in the row you must then write —
    required by `_REQUIRED_KEYS`, bounded by `MAX_BOUND_DAYS`, and read at the
    `bound` line below exactly as `adjudicate` reads it. Writing the row is the
    amnesty: a reason, an owner, and an expiry, all visible in a tracked file.
    Renewal is moving `since` (and `since_date` with it) forward, which is a
    visible act; raising `max_days` past the ceiling is refused, so immortality
    cannot be bought.

    Returns one string per offending gate, sorted, deduplicated by label. An
    empty list means every inherited blocking red is owned by a live, unexpired
    acknowledgement — which is the only state in which this rule is silent.
    """
    rows = {str(r.get("gate")): r for r in ledger if r.get("gate")}
    out: Dict[str, str] = {}
    for finding in carried:
        kind, label, _corpus = (list(finding) + ["", "", ""])[:3]
        if kind != BLOCKING_KIND or not label or label in out:
            continue
        row = rows.get(label)
        if row is None:
            out[label] = (
                f"AN INHERITED RED WITH NO OWNER — {label} failed on the base "
                f"too, so it is not this branch's, and no row in "
                f"{LEDGER_REL} names it. Add one with an owner and a "
                f"max_days bound, or fix the gate. A red that belongs to "
                f"nobody is the one that survives everything.")
            continue
        if (row.get("max_days") in (None, "")
                and row.get(_SUPERSEDED_BOUND_KEY) not in (None, "")):
            # The row is a real acknowledgement written under the commit clock
            # this program replaced. Its bound cannot be evaluated as a
            # duration, and converting it here would be this program inventing
            # a deadline nobody agreed to — so it refuses, and NAMES the
            # migration rather than leaving a reader to guess.
            out[label] = (
                f"AN INHERITED RED'S BOUND PREDATES THE DURATION CLOCK — "
                f"{label} still bounds itself with `{_SUPERSEDED_BOUND_KEY}` "
                f"and carries no `max_days`. A commit count is a property of "
                f"the merge topology, which is why it was replaced; migrate "
                f"the row in {LEDGER_REL} to `since_date` + `max_days`. Until "
                f"then its deadline cannot be evaluated, and that must not "
                f"read as 'the deadline is fine'.")
            continue
        missing = [k for k in _REQUIRED_KEYS if row.get(k) in (None, "")]
        if missing:
            out[label] = (
                f"AN INHERITED RED IS ACKNOWLEDGED WITHOUT A BOUND — {label} "
                f"has a row missing {', '.join(missing)}. An acknowledgement "
                f"with no deadline never comes due, which is the state this "
                f"ledger exists to end.")
            continue
        behind = age(str(row["since"]))
        if behind is None:
            out[label] = (
                f"AN INHERITED RED'S DEADLINE CANNOT BE EVALUATED — {label} "
                f"cites commit {str(row['since'])[:12]}, which this repository "
                f"does not contain or cannot date. 'I could not check the "
                f"deadline' must not read as 'the deadline is fine'.")
            continue
        try:
            bound = float(row["max_days"])
        except (TypeError, ValueError):
            out[label] = (
                f"AN INHERITED RED'S BOUND IS NOT A NUMBER — {label} declares "
                f"max_days={row['max_days']!r}.")
            continue
        if bound > MAX_BOUND_DAYS:
            out[label] = (
                f"AN INHERITED RED IS ACKNOWLEDGED WITHOUT A REACHABLE "
                f"DEADLINE — {label} declares max_days={_days(bound)}, beyond "
                f"the {_days(MAX_BOUND_DAYS)}-day ceiling. A deadline that "
                f"cannot arrive is not a deadline; renew by moving `since` "
                f"forward.")
            continue
        if behind > bound:
            out[label] = (
                f"THE DEADLINE ON AN INHERITED RED HAS PASSED — {label} has "
                f"been red since {str(row['since'])[:12]}, {_days(behind)} "
                f"day(s) ago, and the bound this row set for itself was "
                f"{_days(bound)}. {row.get('owner') or 'nobody'} owns it.")
    return [out[k] for k in sorted(out)]


def git_commit_date(repo: Path) -> Callable[[str], Optional[str]]:
    """`rev` -> that commit's own ISO-8601 committer date, or None.

    None means one indivisible thing to every caller: this repository could not
    tell me when that commit was made — it does not contain it, `git` failed,
    or the ref names something that is not a commit. Callers grade that as
    UNDETERMINED, never as an age.
    """

    def dated(rev: str) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), "show", "-s", "--format=%cI", rev],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None

    return dated


def git_age_days(repo: Path,
                 head: str = "HEAD") -> Callable[[str], Optional[float]]:
    """Days between a commit's date and `head`'s date, or None if unreadable.

    THE CLOCK USED TO BE `rev-list --count <since>..<head>` (measured
    2026-08-22). A commit count is a property of the MERGE TOPOLOGY, and a merge
    is something the acknowledgement's author does not control: on a 97-branch
    assembly every merged branch's commits land inside that range, so all five
    shipped rows read 1590-2109 against bounds of 140-210 and every one would
    have been called EXPIRED by an assembly none of them had anything to do
    with. `--first-parent` is not the repair either — three of the five `since`
    shas are not on the head's first-parent chain, so it would have silently
    mis-aged exactly those three while appearing to fix the problem.

    How stale a promise is, is a property of when it was made. Dates keep the
    two properties the commit clock was chosen for: derivable from the
    repository alone, and identical for every reader of the same (tree,
    endpoint) pair. The wall clock would keep neither, which is why the
    endpoint is still a ref.

    `head` EXISTS BECAUSE THE CANDIDATE MUST NOT MOVE THE CLOCK (2026-08-22).
    Dating every row against a candidate branch's own HEAD lets that branch
    shelter or expire rows it has nothing to do with. The deadline is a
    property of the base, so a landing counts to the base — the same rule as
    the one that requires the LEDGER to be the base's.

    A NEGATIVE AGE IS RETURNED AS IT IS, not clamped. It means the endpoint
    predates the acknowledgement — an old checkout, or a rewritten history —
    and it can never exceed a positive bound, so it cannot expire a row. The
    endpoint and its date are printed on every run, which is where a reader
    sees that the answer was measured against a tree older than the promise.
    """
    dated = git_commit_date(repo)

    def age(sha: str) -> Optional[float]:
        start = _parse_iso(dated(sha))
        end = _parse_iso(dated(head))
        if start is None or end is None:
            return None
        return (end - start).total_seconds() / _SECONDS_PER_DAY

    return age


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="an acknowledged red must expire (vibe-ic#1025)")
    ap.add_argument("--record", type=Path, required=True,
                    help="dispatch record written by _gate_dispatch.sh "
                         "--summary-json")
    ap.add_argument("--ledger", type=Path,
                    help=f"acknowledgement ledger (default: <repo>/{LEDGER_REL})")
    ap.add_argument("--repo", type=Path, default=Path.cwd(),
                    help="repository whose history dates the acknowledgements")
    ap.add_argument("--ledger-ref",
                    help=("read the ledger from this git ref instead of the "
                          "working tree. A landing passes its BASE: the "
                          "candidate's own ledger would let a branch renew a "
                          "row in the same commit that needs the renewal"))
    ap.add_argument("--head-ref", default="HEAD",
                    help=("the ref the clock counts TO (default HEAD). A "
                          "landing passes its BASE: counting to a candidate's "
                          "own head lets a large branch expire rows it never "
                          "touched"))
    args = ap.parse_args(argv)

    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[FAIL] gate_red_since: unreadable dispatch record: {exc}")
        return _vx.RC_FAIL

    if args.ledger and args.ledger_ref:
        print("[FAIL] gate_red_since: --ledger and --ledger-ref name two "
              "different ledgers; pick one")
        return _vx.RC_FAIL
    try:
        if args.ledger_ref:
            ledger = load_ledger_from_ref(args.repo, args.ledger_ref)
        else:
            ledger = load_ledger(args.ledger or (args.repo / LEDGER_REL))
    except LedgerUnreadable as exc:
        # A GATE THAT COULD NOT LOOK IS NOT A GATE THAT FOUND SOMETHING.
        # Same three channels the vacuous branch below uses, from the same
        # reason token, so the printed word and the exit code cannot disagree:
        # the rc-independent stderr sentinel, the `[VACUOUS]` verdict line that
        # cannot read as a bare PASS, and a last line that NAMES what could not
        # be read -- which is the line `gate_red_since_gate` quotes.
        why = str(exc)
        _vx.announce_vacuous("gate_red_since", why)
        print(_vx.verdict_line("gate_red_since", passed=True, skipped=True,
                               reason=why))
        print(f"gate_red_since: NOT CHECKED — {why}")
        return _vx.exit_code(passed=True, skipped=True)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # READ AND WRONG, which is a different sentence: the bytes exist and
        # say something this program cannot act on. That is a defect of the
        # tree holding them and it blocks.
        print(f"[FAIL] gate_red_since: unreadable ledger: {exc}")
        return _vx.RC_FAIL

    why = record_is_vacuous(record)
    if why is not None:
        # Both channels, from the SAME reason token, exactly as the shipped
        # convention prescribes: the rc-independent stderr sentinel, and the
        # human verdict line that cannot print a bare PASS for it.
        _vx.announce_vacuous("gate_red_since", why)
        print(_vx.verdict_line("gate_red_since", passed=True, skipped=True,
                               reason=why))
        print(f"gate_red_since: 0 gate state(s) examined — {why}")
        return _vx.exit_code(passed=True, skipped=True)

    findings, known, new = adjudicate(
        record, ledger,
        git_age_days(args.repo, args.head_ref),
        git_commit_date(args.repo))

    # SHALLOWNESS IS ONLY AN ANSWER WHEN A ROW ACTUALLY FAILED TO RESOLVE.
    #
    # Asking `--is-shallow-repository` FIRST and refusing on it was my own
    # first attempt and it was wrong: this repository is itself shallow — a
    # `.git/shallow` written 2026-08-22 06:09 — and every `since` in the
    # shipped ledger still resolves in it, because `--depth` truncates the
    # history a clone FETCHED, not the history it later acquired. A pre-emptive
    # refusal would have blocked every landing on this host over a condition
    # that changes no verdict.
    #
    # So the question is asked only once something is unresolvable, and then it
    # is asked to EXPLAIN, not to decide: measured on a `--depth 20` clone,
    # both the oldest and the newest `since` are absent, and without this the
    # output is one finding per row naming an innocent commit and not one
    # naming the cause.
    _unresolvable = [f for f in findings if f.kind == "unresolvable"]
    if _unresolvable:
        _depth = repository_is_shallow(args.repo)
        if _depth is not None:
            print(f"gate_red_since: {len(_unresolvable)} row(s) cite commits "
                  f"this repository does not contain, AND it is a SHALLOW "
                  f"clone ({_depth} commit(s)) — the history is truncated, "
                  f"which is a cause the rows cannot be blamed for.")
            print(f"  Remedy: git -C {args.repo} fetch --unshallow"
                  f"   (or clone without --depth)")

    # THE ENDPOINT IS PART OF THE NUMBER (2026-08-22). Every age below reads
    # "N commit(s) ago" and, until this line existed, never said ago RELATIVE
    # TO WHAT. Measured: the same ledger and the same record gave 7 expired
    # counted to a candidate branch's head and 5 counted to origin/main, and
    # nothing in the output distinguished the two runs. A reader cannot audit a
    # deadline without knowing which tree it was measured against — and a
    # STALE `origin/main` in the subject checkout would shift every age in the
    # permissive direction while looking identical, which is the shape this
    # disclosure exists to expose.
    #
    # Same rule as `gate_discloses_denominator_check` applies to every other
    # gate: a number without its population is a silence.
    print(f"gate_red_since: {int(record.get('declared') or 0)} gate(s) "
          f"declared, {len(known) + len(new)} red "
          f"({len(known)} acknowledged, {len(new)} NEW), "
          f"{len(ledger)} ledger row(s)")
    _end_date = git_commit_date(args.repo)(args.head_ref)
    print(f"  clock: ages are DAYS, counted to {args.head_ref} "
          f"({_describe_ref(args.repo, args.head_ref)} dated "
          f"{_end_date or 'UNREADABLE'}); "
          f"rows read from "
          + (f"{args.ledger_ref} ({_describe_ref(args.repo, args.ledger_ref)})"
             if args.ledger_ref
             else f"the working tree at {args.ledger or (args.repo / LEDGER_REL)}"))
    _unrun = sorted({str(r.get("gate")) for r in ledger
                     if _did_not_run(_states(record).get(str(r.get("gate"))))})
    if _unrun:
        print("  NOT ADJUDICABLE in this record (the gate did not run here, so "
              "this run says nothing about it): " + ", ".join(_unrun))
    # THE PARTITION IS THREE-WAY, BECAUSE THE RECORD KNOWS THREE THINGS. A red
    # can be owned by a row here, owned by a DATED EXEMPTION the dispatcher
    # recorded beside it, or owned by nobody. Folding the middle case into the
    # last one was measured to report 30 unowned reds where 12 were unowned.
    _exempt = dispatcher_exemptions(record)
    exempted = [l for l in new if l in _exempt]
    new = [l for l in new if l not in _exempt]
    if exempted:
        # THE WORDS "owned by nobody" APPEAR ON EXACTLY ONE LINE OF THIS
        # OUTPUT, and it is the line below this one. A reader — and the test
        # that pins this — must be able to find the unowned reds by that
        # phrase without a second line answering to it.
        print(f"  red, and DATED by the dispatcher's own exemption "
              f"(acknowledged in tools/ci/_gate_dispatch.sh, not here): "
              f"{len(exempted)} — "
              + ", ".join(f"{l} (until {_exempt[l]})" for l in exempted[:4])
              + (" …" if len(exempted) > 4 else ""))
    if new:
        # The line the doctrine was actually worried about: when the wall of
        # red is the steady state, this is what separates today's red from
        # last month's.
        print("  NEW red this run (owned by nobody): " + ", ".join(new[:8])
              + (" …" if len(new) > 8 else ""))
    if known:
        print("  acknowledged red: " + ", ".join(known[:8])
              + (" …" if len(known) > 8 else ""))
    for f in findings:
        print(f.line())

    # The verdict line carries the PARTITION, not just the verdict. A caller
    # that keeps one line of this program's output — `gatekeeper_review` keeps
    # exactly one — must still learn how much of today's red is new, because
    # that is the entire thing this program was built to make visible. A
    # trailing "0 acknowledgement(s) overdue" with the NEW count dropped would
    # be a summary that omits its own subject.
    tail = (f"{len(new)} NEW red, {len(known)} acknowledged"
            + (f", {len(exempted)} dispatcher-exempt" if exempted else "")
            + (f" (NEW: {', '.join(new[:4])}"
               + (" …" if len(new) > 4 else "") + ")" if new else ""))
    graded = [f for f in findings if f.kind not in UNDETERMINED_KINDS]
    ungraded = [f for f in findings if f.kind in UNDETERMINED_KINDS]
    if graded:
        # A REAL FINDING OUTRANKS "I COULD NOT LOOK". rc 2 asserts that this run
        # reached no verdict, and the moment one row genuinely failed that
        # sentence is false. The ungraded rows are still NAMED above and their
        # count is carried here, so folding them in cannot make them invisible.
        kinds = ", ".join(sorted({f.kind for f in graded}))
        print(f"[FAIL] gate_red_since: {len(graded)} acknowledgement(s) "
              f"{kinds} — {tail}"
              + (f"; {len(ungraded)} row(s) NOT adjudicable" if ungraded
                 else ""))
        return _vx.RC_FAIL
    if ungraded:
        # NEITHER PASS NOR EXPIRED. The row cites a commit this repository
        # cannot date, so the only honest answer is that the deadline was not
        # evaluated — and it is delivered through the same three channels the
        # vacuous branch uses, from one reason token, so the printed word and
        # the exit code cannot disagree.
        why = (f"{len(ungraded)} acknowledgement(s) could not be aged: "
               + "; ".join(f"{f.gate} ({f.kind})" for f in ungraded))
        _vx.announce_vacuous("gate_red_since", why)
        print(_vx.verdict_line("gate_red_since", passed=True, skipped=True,
                               reason=why))
        print(f"gate_red_since: NOT CHECKED — {why}")
        return _vx.exit_code(passed=True, skipped=True)
    print(f"[PASS] gate_red_since: every red is NEW or owned by a live, "
          f"unexpired acknowledgement — {tail}")
    return _vx.RC_PASS


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
