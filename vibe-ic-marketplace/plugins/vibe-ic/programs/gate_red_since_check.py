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
  L1 incomplete   a row without `gate` / `since` / `max_commits`. An
                  acknowledgement with no bound is the thing being removed, so
                  it cannot be written.
  L2 stale        a row naming a gate that is now PASS (or absent from the
                  record). The fix landed and the row outlived its truth — a
                  stale acknowledgement is indistinguishable, to the next
                  reader, from a live one, and it is the row that will be
                  believed. Delete it in the commit that fixes the gate.
  L3 expired      `since` is more than `max_commits` commits behind HEAD. This
                  is the deadline actually biting, and it is the only reason
                  this program exists rather than a report.
  L4 unresolvable a row citing a commit this repository does not contain. The
                  age cannot be computed, so the bound cannot be enforced, and
                  "I could not check the deadline" must not read as "the
                  deadline is fine".

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
from pathlib import Path
from typing import (Any, Callable, Dict, Iterable, List, Optional, Sequence,
                    Tuple)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _vacuous_exit as _vx  # noqa: E402

#: States the dispatcher can record. Everything that is not PASS and not LISTED
#: is RED for this program's purpose: a gate that FAILED, one that REFUSED
#: (NOT_CHECKED), and one that WROTE_CORPUS are all gates whose result a reader
#: has to act on. Lumping them is safe in the strict direction — it can only
#: keep an acknowledgement alive, never retire one early.
_PASS = "PASS"
_LISTED = "LISTED"

#: Ledger location, relative to the repository root.
LEDGER_REL = "tools/ci/gate_red_since.json"

_REQUIRED_KEYS = ("gate", "since", "max_commits")

#: The largest bound that is still a bound. MEASURED while probing this
#: program against itself: a row with `max_commits: 9999999` satisfies every
#: other rule here and never expires, so the mechanism can be switched off by
#: editing the file it adjudicates — the same "wired where it can never
#: block" shape it exists to catch. The ceiling does not forbid a long
#: remediation; it forbids an unattended one. A red that genuinely needs
#: longer is renewed by moving `since` forward, which is a visible act that
#: shows up in review, rather than a number nobody reads again.
MAX_BOUND_COMMITS = 500


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

    A ledger that cannot be read AT THE REF IS AN ERROR, unlike an absent
    ledger at a path: the caller named a ref and was wrong about it, which is
    the `$VIBE_IC_BENCHMARK_DATA set + unreadable` shape — never excused.
    An empty `acknowledged` at a valid ref is still the normal starting state.
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:{LEDGER_REL}"],
        capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        if "does not exist" in proc.stderr or "exists on disk" in proc.stderr:
            return []          # the ref predates the ledger: no acknowledgements
        raise ValueError(f"cannot read {LEDGER_REL} at {ref}: "
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
               age: Callable[[str], Optional[int]],
               ) -> Tuple[List[Finding], List[str], List[str]]:
    """The whole decision, as a pure function. Returns (findings, known, new).

    `age(sha) -> commits behind HEAD, or None if this repo does not contain it`
    is injected so every branch below is reachable from a test without building
    a git history per case — including L4, which by definition cannot be staged
    with a real commit.
    """
    states = _states(record)
    findings: List[Finding] = []
    acknowledged_gates: set = set()

    for row in ledger:
        label = str(row.get("gate") or "")
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

        since = str(row["since"])
        behind = age(since)
        if behind is None:
            findings.append(Finding(
                "unresolvable", label,
                f"the row cites commit {since[:12]}, which this repository "
                f"does not contain, so its deadline cannot be evaluated"))
            continue
        try:
            bound = int(row["max_commits"])
        except (TypeError, ValueError):
            findings.append(Finding(
                "incomplete", label,
                f"max_commits is not an integer: {row['max_commits']!r}"))
            continue
        if bound > MAX_BOUND_COMMITS:
            findings.append(Finding(
                "unbounded", label,
                f"max_commits is {bound}, beyond the {MAX_BOUND_COMMITS}-commit "
                f"ceiling. A deadline that cannot arrive is not a deadline; "
                f"renew the row by moving `since` forward instead"))
            continue
        if behind > bound:
            findings.append(Finding(
                "expired", label,
                f"red since {since[:12]} — {behind} commit(s) ago, and the "
                f"bound this row set for itself was {bound}. "
                f"{row.get('owner') or 'nobody'} owns it"))

    red = sorted(l for l, s in states.items() if s not in (_PASS, _LISTED))
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

    The DECLARED N is `max_commits`, per gate, in the row you must then write —
    required by `_REQUIRED_KEYS`, bounded by `MAX_BOUND_COMMITS`, and read at
    the `bound` line below exactly as `adjudicate` reads it. Writing the row is
    the amnesty: a reason, an owner, and an expiry, all visible in a tracked
    file. Renewal is moving `since` forward, which is a visible act; raising
    `max_commits` past the ceiling is refused, so immortality cannot be bought.

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
                f"max_commits bound, or fix the gate. A red that belongs to "
                f"nobody is the one that survives everything.")
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
                f"does not contain. 'I could not check the deadline' must not "
                f"read as 'the deadline is fine'.")
            continue
        try:
            bound = int(row["max_commits"])
        except (TypeError, ValueError):
            out[label] = (
                f"AN INHERITED RED'S BOUND IS NOT A NUMBER — {label} declares "
                f"max_commits={row['max_commits']!r}.")
            continue
        if bound > MAX_BOUND_COMMITS:
            out[label] = (
                f"AN INHERITED RED IS ACKNOWLEDGED WITHOUT A REACHABLE "
                f"DEADLINE — {label} declares max_commits={bound}, beyond the "
                f"{MAX_BOUND_COMMITS}-commit ceiling. A deadline that cannot "
                f"arrive is not a deadline; renew by moving `since` forward.")
            continue
        if behind > bound:
            out[label] = (
                f"THE DEADLINE ON AN INHERITED RED HAS PASSED — {label} has "
                f"been red since {str(row['since'])[:12]}, {behind} commit(s) "
                f"ago, and the bound this row set for itself was {bound}. "
                f"{row.get('owner') or 'nobody'} owns it.")
    return [out[k] for k in sorted(out)]


def git_age(repo: Path, head: str = "HEAD") -> Callable[[str], Optional[int]]:
    """Commits between a sha and `head`, or None when the sha is unknown here.

    The clock is COMMITS and not wall time on purpose: it is derivable from the
    repository alone, identical for every reader of the same tree, and needs no
    persisted run history — which is precisely what this repo does not keep.

    `head` EXISTS BECAUSE THE CANDIDATE MUST NOT MOVE THE CLOCK (2026-08-22).
    Counting to a candidate branch's own HEAD adds that branch's commits to
    EVERY row's age, so a large branch expires rows it has nothing to do with —
    and a small one shelters them. MEASURED on a 15-commit branch: 7 rows read
    as expired against its HEAD and 5 against `origin/main`, the tree that
    actually lands. Two of the difference were rows the branch never touched.

    The deadline is a property of the base, so a landing counts to the base.
    This is the same rule as the one that requires the LEDGER to be the base's:
    a branch must not be able to change what counts as overdue, in either
    direction.
    """

    def age(sha: str) -> Optional[int]:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), "rev-list", "--count", f"{sha}..{head}"],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        try:
            return int(proc.stdout.strip())
        except ValueError:
            return None

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
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
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

    findings, known, new = adjudicate(record, ledger, git_age(args.repo, args.head_ref))

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
    print(f"  clock: ages counted to {args.head_ref} ({_describe_ref(args.repo, args.head_ref)}); "
          f"rows read from "
          + (f"{args.ledger_ref} ({_describe_ref(args.repo, args.ledger_ref)})"
             if args.ledger_ref
             else f"the working tree at {args.ledger or (args.repo / LEDGER_REL)}"))
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
            + (f" (NEW: {', '.join(new[:4])}"
               + (" …" if len(new) > 4 else "") + ")" if new else ""))
    if findings:
        kinds = ", ".join(sorted({f.kind for f in findings}))
        print(f"[FAIL] gate_red_since: {len(findings)} acknowledgement(s) "
              f"{kinds} — {tail}")
        return _vx.RC_FAIL
    print(f"[PASS] gate_red_since: every red is NEW or owned by a live, "
          f"unexpired acknowledgement — {tail}")
    return _vx.RC_PASS


if __name__ == "__main__":
    sys.exit(main())
