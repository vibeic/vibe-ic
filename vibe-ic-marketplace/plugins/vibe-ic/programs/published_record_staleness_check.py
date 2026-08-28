#!/usr/bin/env python3
"""published_record_staleness_check.py — a landed gate rule does not reach the
records the gate already published.

THE DEFECT, MEASURED (vibe-ic#510)
==================================
v1.7.73 landed #502: an SI sign-off that re-derived ZERO coupling folds is no
longer ``PASS``, it is ``VACUOUS_PASS`` at rc 2 with a written reason. Verified
on the shipped fixture. But every tracked ``si_mcf_sta_check.json``, read out of
``HEAD`` at that same version, still said otherwise:

    ic/edge_llm_accel                    PASS | coupling_pairs = 0     <- stale
    ic/spm/v1.5.58_<pdk>                 PASS | coupling_pairs = 0     <- stale
    ic/spm/v1.5.65_<pdk>                 PASS | coupling_pairs = 1558
    ic/spm/v1.5.66_<pdk>                 PASS | coupling_pairs = 1570
    ic/sha256/clean_run_v1422            PASS | coupling_pairs = 50603
    ic/sha256/clean_run_v1427            PASS | coupling_pairs = 50042
    ic/sha256/clean_run_v1461            PASS | coupling_pairs = 34721

Two of seven carried a ``PASS`` the current gate would refuse to issue — one of
them the exact artefact #502 was filed about. A ``PASS`` byte-indistinguishable
in verdict from the ones that folded 1,558 and 34,721 pairs.

THE GENERAL DEFECT IS NOT THOSE TWO FILES. A landed gate fix changes what the
plugin certifies FROM NOW ON and does nothing to already-published records, and
before this program nothing in the repo measured the gap. So a corpus can
indefinitely carry verdicts its own gate would no longer issue, and a reader has
no way to tell a current record from a superseded one. That is not a
hypothetical drift: it happened within one version of the fix landing, on the
design the fix was about.

WHAT THIS PROGRAM DOES
======================
It reads every PUBLISHED gate record in the corpus, asks the record's own
producing gate which verdict its current rules would issue, and compares —
DECIDING FROM THE RECORD'S FIELDS, never by re-running the tool. That
constraint is not a shortcut, it is the requirement: the inputs are gone. The
older records name absolute SPEF paths inside an authoring machine's campaign
directory (#506), so nothing here can be re-derived and never will be for old
cells. ``coupling_pairs: 0`` beside ``verdict: PASS`` needs no SPEF to refute.

WHAT IT DOES NOT DO — IT DOES NOT REWRITE ANYTHING
---------------------------------------------------
Correcting a published record is the benchmark-agent's call under NO-MIX:
results and plugin fixes never share a commit, or a hand-patch could inflate a
published number. This program names which records and why. It opens every file
read-only and writes nothing under the corpus.

AN UNDECIDABLE RECORD IS DISCLOSED, NOT PASSED
-----------------------------------------------
Most gates' verdicts are NOT re-adjudicable on paper — whether a design's
timing actually closed is not a fact its report carries. Silently skipping
those would rebuild the repo's oldest failure one level up: a check that
examined 7 records and a check that examined 224 would print the same clean
sentence. So every record lands in exactly one of two buckets, both counted,
with the reason for every undecidable one named:

    adjudicated  the producing gate has rules AND the record carries the fields
                 they read
    undecidable  NO_RULES_REGISTERED / GATE_MODULE_ABSENT / RULES_UNREVIEWED /
                 FIELDS_ABSENT / FIELD_UNREADABLE / RULE_ERRORED / ...

and the denominator is published through ``_gate_denominator`` — the type that
exists so a zero cannot be stated without a written reason.

HOW A RULE REGISTERS ITSELF, AND WHY THERE IS NO LIST HERE
===========================================================
A hand-maintained list of gates-with-rules would go stale exactly the way the
records did — the failure mode this check exists to catch. So nothing is
hand-maintained:

  * WHICH GATES ARE UNDER AUDIT is read off the CORPUS. Every record names its
    producer in its own ``program`` field. A gate that starts publishing
    records is covered by its first record, and a gate that stops is dropped,
    with nobody editing anything here.
  * WHAT ITS RULES ARE lives in the GATE'S OWN MODULE, under
    ``_record_adjudication.DECLARATION_ATTR``. The author changing a verdict is
    editing the file that carries the declaration.
  * DRIFT IS LOUD. Each declaration pins a fingerprint over its gate's decision
    logic (see ``_record_adjudication.decision_fingerprint``). Land a rule
    change without re-reviewing the declaration and this check reports
    ``RULES_UNREVIEWED``, books that gate's records as undecidable, and FAILS.

THE DEBT THIS CANNOT PAY, AND WHY IT IS A REGISTER AND NOT A SHRUG
------------------------------------------------------------------
Two published records are superseded right now, and this program is forbidden
to correct them: that is the benchmark-agent's commit. Wiring an unconditional
rc 1 into CI would leave main permanently red on a defect the plugin cannot
fix, and a permanently-red gate is an ignored gate. So superseded records are
recorded in a baseline register (same shape as
``flow_gate_enforcement_baseline.json``, #306/#316): the register MAY ONLY
SHRINK, a recorded entry that stops being stale FAILS so it cannot become
standing permission, and anything NEW FAILS. The corpus stops growing
superseded records without this program deciding another role's commit.

RULE DRIFT IS NEVER BASELINEABLE. ``RULES_UNREVIEWED`` is plugin-side debt,
fixable in the same commit that caused it, by the same person. Letting it be
recorded would defeat the one requirement the register exists beside.

MAY ONLY SHRINK IS ENFORCED ON THE READ PATH TOO (vibe-ic#922)
---------------------------------------------------------------
Until #922 the ratchet lived entirely inside ``--write-baseline``: the writer
refused to GROW the register without ``--scope-expanded``, and the reader took
whatever ``known`` list it found on disk as the recorded debt. A register is a
plain JSON file, so the writer was never the only way to add an entry to it —
and adding one by hand is precisely how a NEW superseded record stops being
NEW. The rule that FAILs the tree was one text editor away from being optional.

That is not hypothetical. This repo shipped the default register in a state its
own writer refuses to produce: ``previous_size: 2`` beside five ``known``
entries and ``scope_expanded: null`` — the growth that landed with the
``dfm_screen_check`` rule (v1.8.75), authorised in that commit's message and in
the register's own ``_comment``, but written into neither field the program can
read. Run ``--write-baseline`` over that same growth and it exits 1 with
*refusing to GROW the register (2 -> 5)*. Two paths to the same edit, one of
them ratcheted.

So the reader now asks one question of the register before it trusts it: COULD
``_write_baseline`` HAVE PRODUCED THIS DOCUMENT? The writer records the count it
sanctioned (``size``) beside the count it grew from (``previous_size``) and the
reason it was allowed to grow (``scope_expanded``), and :func:`_register_defects`
re-checks the writer's own rules against those recorded numbers. An entry
appended by hand leaves ``size`` behind and is caught; growing the recorded
numbers as well requires forging two coupled counts and writing a reason, which
is a deliberate false statement rather than an omission nothing measures.

The reason is checked against the SAME minimum the writer applies
(:data:`SCOPE_REASON_MIN_CHARS`), read from one constant, so the two sides
cannot drift into disagreeing about what a written reason is.

AND THE REASON IS SPENT BY THE WRITE THAT USED IT. A ``scope_expanded`` left
standing on a register that grew nothing would be the finding this issue is
named for, reproduced one file over: a permanent string that pre-authorises
whatever growth comes next, reducing the forgery to a single number. So the
writer records it only for the write it authorised, and a register carrying one
without the growth it justifies is reported.

A register written by an older version carries no ``size``. It is reported, not
waved through: "no recorded size" is exactly the state a hand-edit produces once
someone notices the field, so treating it as "nothing to check" would reopen the
hole one key over. The repair is the writer — ``--write-baseline`` re-records
the file — and the validator therefore runs on the READ path only, never in
front of the writer that fixes it.

A RECORDED ENTRY IS ONLY "PAID" IF SOMETHING RE-EXAMINED IT (vibe-ic#536)
-------------------------------------------------------------------------
The register's shrink-only rule needs a way to notice that an entry stopped
being stale, and until #536 that way was set subtraction: an entry in the
register that produced no finding this run was booked as PAID and the gate
printed *shrink the register*. Set subtraction cannot tell "the record was
re-adjudicated and is clean" from "the record was never adjudicated at all",
and those are the same observation — no finding.

Measured, on this repo's own corpus at v1.7.89: the declared decision digest
was stale, so ``si_mcf_sta_check``'s seven records were UNDECIDABLE, so neither
recorded entry produced a finding, so both were reported *no longer superseded
— the debt was paid; shrink the register*. Both records still carried ``PASS``
and both still superseded to ``VACUOUS_PASS`` when the rule was run directly.
The instruction was to delete two live debts from a register that MAY ONLY
SHRINK, i.e. an irreversible edit derived from an absence of evidence. The same
false claim is produced — alone, with nothing else red — by a gate module going
missing or a declaration being withdrawn: three different undecidability
classes, one wrong inference.

So the resolution question is asked ONLY of the ADJUDICATED population, per
entry, per RULE:

    RESOLVED           the rule named in the entry RAN over the record named in
                       the entry, this run, and declined to supersede it. The
                       only positive evidence available, and the only status
                       that instructs a shrink.
    STILL_SUPERSEDED   the entry reproduced its finding — the recorded debt.
    UNADJUDICATED      the record was not adjudicated by that rule (any
                       undecidability class, or the rule no longer runs over
                       it). NOT evidence about the debt, in either direction;
                       reported with what blocked it, and never a shrink.
    RECORD_NOT_PUBLISHED  the corpus no longer carries the record. The entry is
                       inert — it can suppress nothing — but its inertness is
                       an observation of the corpus, not an adjudication, so it
                       is reported and does not instruct anything either.

``adjudicated == 0`` therefore yields no resolution claim at all, by
construction rather than by a special case. ``--write-baseline`` obeys the same
rule from the other side: it REFUSES to drop an entry that was not adjudicated,
because shrinking on an absence of evidence is the deletion this check exists
to prevent, merely performed by the tool instead of by hand.

Exit: 0 = PASS (records adjudicated, nothing superseded beyond the recorded
debt, no rule drift), 1 = FAIL (a NEW superseded record, a recorded entry that
was RE-ADJUDICATED and is no longer stale, a gate whose rules are unreviewed,
or --strict and a publishing gate registered nothing), 2 = VACUOUS_PASS (no
record could be adjudicated at all — a disclosed skip, never a sign-off).

chip-AGNOSTIC: keyed on gate names and record field paths only. No design, PDK
or vendor name appears here, and a rule cannot introduce one because a rule
never sees anything but a record's own fields.

WHERE THE CORPUS IS, NOW THAT IT IS NOT HERE (vibe-ic#1710's treatment)
=======================================================================
The default corpus root was ``<repo>/benchmark-data``. v1.10.56 moved the
published trees into their own repositories, and this program then answered

    ERROR: not a directory: <repo>/benchmark-data                        rc 1

A CRASH IS NOT A VERDICT, and rc 1 is worse than the wrong number here: in this
program rc 1 MEANS "a published record carries a verdict its gate would not
issue today". There was no such record. The gate reported a defect it had not
measured, which is the same false certificate as a pass it had not measured,
pointed the other way. (The rc was chosen deliberately — "rc 2 is the
disclosed-skip tier and a run that never started must not be credited as one" —
and that reasoning is right about rc 2 and wrong about rc 1: the honest answer
was neither, it was a corpus that had moved.)

``_corpus_location`` resolves the root now, the override is ANNOUNCED, and the
four outcomes stay distinct (see that module). ``$VIBE_IC_BENCHMARK_DATA``
names the CLONE ROOT, which is what ``benchmark-data/`` was, so record keys
(``ic/<design>/reports/...``) are unchanged and the DEFAULT register still
describes the corpus the pointer reaches.

A CORPUS THAT IS NOT A CHECKOUT IS REFUSED, NOT WALKED
------------------------------------------------------
``_tracked_paths`` asks ``git ls-files`` and FALLS BACK to ``rglob("*.json")``
when git cannot answer, disclosing which it used. That fallback is right for a
run tree handed over on its own and wrong for a corpus reached through the
pointer: a tarball fetch, an archive export or a dead clone would be walked from
the DISK, which admits untracked scratch output and adjudicates records nobody
published. So a pointer-supplied root that is not a git checkout is
UNDETERMINED (rc 2), never a population swap nothing announced.

AND THE REGISTER IS NOT EXCUSED WITH THE SCAN
----------------------------------------------
``published_record_staleness_baseline.json`` lives beside this program and did
not move with the corpus. Under NO_CORPUS the SCAN is excused and the register
is still put through :func:`_register_defects` — the #922 question "could
``_write_baseline`` have produced this document?" needs no corpus to ask, and
an rc 0 that never asked it would hand back the hole that check closed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _corpus_location as _cloc
import _gate_denominator as _gd
import _record_adjudication as _ra

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

_HERE = Path(__file__).resolve().parent

GATE = "published_record_staleness_check"

#: A gate record is small. A multi-megabyte JSON is a data blob that happens to
#: live in the corpus, and parsing the whole tree's worth of them would make
#: this check slow enough to get dropped from CI. Skipped files are COUNTED and
#: reported, never silently passed over.
MAX_RECORD_BYTES = 4_000_000

#: Why a record could not be re-adjudicated. Every record that is not
#: adjudicated carries exactly one of these plus prose.
UNDECIDABLE_FIELDS_ABSENT = "FIELDS_ABSENT"
UNDECIDABLE_FIELD_UNREADABLE = "FIELD_UNREADABLE"
UNDECIDABLE_RULE_ERRORED = "RULE_ERRORED"
UNDECIDABLE_RULES_UNREVIEWED = "RULES_UNREVIEWED"

STALE = "STALE_VERDICT"

#: Where the debt owed to the benchmark-agent is recorded when no `--baseline`
#: is given. Beside the program, like the register #306/#316 established.
DEFAULT_BASELINE = "published_record_staleness_baseline.json"

#: What this run found out about one RECORDED register entry. Exactly one is
#: attached to every entry, and only ``DEBT_RESOLVED`` instructs a shrink —
#: everything else is either the debt reproducing itself or an absence of
#: evidence, and an absence of evidence must never drive an irreversible edit
#: to a register that MAY ONLY SHRINK (#536).
DEBT_STILL_SUPERSEDED = "STILL_SUPERSEDED"
DEBT_RESOLVED = "RESOLVED"
DEBT_UNADJUDICATED = "UNADJUDICATED"
DEBT_RECORD_UNPUBLISHED = "RECORD_NOT_PUBLISHED"
DEBT_ENTRY_UNREADABLE = "ENTRY_UNREADABLE"

#: The blocker for an entry whose RECORD was adjudicated but whose RULE did not
#: run over it — removed, renamed, or blocked on a field the rules that DID run
#: did not need. Distinct from the record-level undecidability reasons because
#: the record itself was decidable; this rule was not applied to it.
DEBT_RULE_NOT_APPLIED = "RULE_NOT_APPLIED"

#: Field separator of a register entry. Kept in one place so ``debt_key`` and
#: ``parse_debt_key`` cannot drift apart.
KEY_SEP = "::"

#: What counts as a WRITTEN reason for growing the register. The writer demands
#: it of ``--scope-expanded`` and the reader re-checks it against the recorded
#: ``scope_expanded``; one constant so a future edit cannot leave the reader
#: accepting a reason the writer would have rejected (#922).
SCOPE_REASON_MIN_CHARS = 30


def debt_key(finding: Dict[str, Any]) -> str:
    """The identity of one superseded record, for the debt register.

    Carries the VERDICT PAIR and the rule, not just the path: a record that
    later goes stale a DIFFERENT way, or under a rule landed afterwards, is a
    new defect and must not be covered by an entry recorded for the old one.
    """
    return (f"{finding['gate']}{KEY_SEP}{finding['record']}{KEY_SEP}"
            f"{finding['carried_verdict']}->{finding['would_issue']}{KEY_SEP}"
            f"{finding['rule_id']}")


def parse_debt_key(key: str) -> Optional[Tuple[str, str, str, str]]:
    """``(gate, record, verdict_pair, rule_id)`` for one register entry.

    Read from the OUTSIDE IN. The gate name and the rule id are program-level
    identifiers and carry no separator; the RECORD is a corpus path and is not
    this program's to constrain, so whatever is between them is the record.
    Anything that does not split into at least four fields returns None: an
    entry nobody can resolve to a record must not be resolvable to a verdict
    about that record either, and guessing would put the wrong record's
    adjudication behind someone's debt.
    """
    parts = str(key).split(KEY_SEP)
    if len(parts) < 4:
        return None
    gate, rule_id, pair = parts[0], parts[-1], parts[-2]
    record = KEY_SEP.join(parts[1:-2])
    if not gate or not record or not rule_id:
        return None
    return gate, record, pair, rule_id


def _adjudication_index(report: Dict[str, Any]) -> Tuple[
        set, Dict[str, Dict[str, Any]], set]:
    """What this run actually examined, keyed the way an entry names it.

    ``ran`` is per (record, RULE): a record can be adjudicated by one rule while
    another is blocked on a field only it reads, and an entry recorded for the
    blocked rule was not re-examined merely because its record appears in the
    adjudicated list.
    """
    ran = {(a["record"], rid)
           for a in report.get("adjudicated", [])
           for rid in (a.get("rules_applied") or [])}
    undecidable = {u["record"]: u for u in report.get("undecidable", [])}
    present = {a["record"] for a in report.get("adjudicated", [])} | set(
        undecidable)
    return ran, undecidable, present


def classify_recorded_debt(prev: List[str], now: List[str],
                           report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What this run learned about each RECORDED entry — one status each.

    The whole point is the middle two statuses. Before #536 this was
    ``[k for k in prev if k not in now]`` and everything that was not still
    stale was called PAID, so a stale declaration, a missing gate module or a
    withdrawn declaration each produced *the debt was paid; shrink the
    register* over live debt. Nothing here asks whether an entry produced a
    finding until after it has established that something re-examined it.
    """
    ran, undecidable, present = _adjudication_index(report)
    now_set = set(now)
    out: List[Dict[str, Any]] = []
    for key in prev:
        parsed = parse_debt_key(key)
        if parsed is None:
            out.append({
                "entry": key, "status": DEBT_ENTRY_UNREADABLE,
                "blocked_by": DEBT_ENTRY_UNREADABLE,
                "detail": (f"not in <gate>{KEY_SEP}<record>{KEY_SEP}"
                           f"<carried>-><would_issue>{KEY_SEP}<rule_id> form, "
                           f"so it names no record this run could look at")})
            continue
        gate, record, _pair, rule_id = parsed
        common = {"entry": key, "gate": gate, "record": record,
                  "rule_id": rule_id}
        if key in now_set:
            out.append({**common, "status": DEBT_STILL_SUPERSEDED,
                        "blocked_by": "",
                        "detail": (f"{rule_id} ran over this record and it "
                                   f"still carries the verdict recorded here")})
        elif (record, rule_id) in ran:
            out.append({**common, "status": DEBT_RESOLVED, "blocked_by": "",
                        "detail": (f"{rule_id} ran over this record this run "
                                   f"and did not supersede it — the entry now "
                                   f"describes a verdict the record no longer "
                                   f"carries")})
        elif record in undecidable:
            u = undecidable[record]
            out.append({**common, "status": DEBT_UNADJUDICATED,
                        "blocked_by": u.get("reason", ""),
                        "detail": u.get("detail", "")})
        elif record in present:
            out.append({**common, "status": DEBT_UNADJUDICATED,
                        "blocked_by": DEBT_RULE_NOT_APPLIED,
                        "detail": (f"the record was adjudicated, but not by "
                                   f"{rule_id}: that rule is no longer "
                                   f"registered under this name, or its "
                                   f"required fields are absent from a record "
                                   f"the other rules could still read")})
        else:
            out.append({**common, "status": DEBT_RECORD_UNPUBLISHED,
                        "blocked_by": "",
                        "detail": ("the corpus scanned here carries no such "
                                   "record, so the entry can suppress nothing "
                                   "— which is an observation of the corpus, "
                                   "not an adjudication of the verdict")})
    return out


@dataclass
class Record:
    """One published gate record: where it is, and what it says."""

    path: Path
    rel: str
    gate: str
    data: Dict[str, Any]


@dataclass
class Discovery:
    """The corpus scan, with everything it did NOT read still counted."""

    records: List[Record] = field(default_factory=list)
    json_files: int = 0
    unparsable: int = 0
    oversize: int = 0
    not_a_record: int = 0
    #: tracked by git, not present on disk — a partial checkout, NOT a
    #: corrupt file. Counted apart so the population is comparable
    #: across machines (vibe-ic#555).
    absent_from_disk: int = 0
    #: symlink into a tree `.gitignore` excludes on purpose — outside
    #: the population by the repository's own declaration (#555).
    deliberately_untracked: int = 0
    enumeration: str = ""


def _tracked_paths(root: Path) -> Tuple[List[Path], str]:
    """Tracked files under ``root``, and how the list was obtained.

    PUBLISHED means COMMITTED. A local run drops its output into the same
    directory tree as the committed records, and adjudicating scratch output
    would report a defect nobody published. So the tracked set is the
    population, and when git cannot supply it that is stated in the report
    rather than assumed away.
    """
    try:
        r = _pr.run(["git", "-C", str(root), "ls-files", "-z"],
                           capture_output=True, text=False)
    except (OSError, subprocess.SubprocessError):
        r = None
    if r is not None and r.returncode == 0:
        rels = [p.decode("utf-8", "replace")
                for p in r.stdout.split(b"\0") if p]
        return [root / p for p in rels], "git-tracked"
    return sorted(root.rglob("*.json")), "filesystem-walk"


def _target_deliberately_untracked(root: Path, p: Path) -> bool:
    """Is this symlink's target excluded by the repository's own .gitignore?

    Asked of git, never matched here: negations, nested ignore files and
    precedence are git's rules, and a second implementation of them disagrees
    with the first. (Verified the hard way in #555 — my model of what a negation
    inside an excluded directory does was wrong, and git's answer was right.)
    """
    try:
        rel = str(p.relative_to(root))
        target = os.path.normpath(os.path.join(os.path.dirname(rel),
                                               os.readlink(p)))
    except (OSError, ValueError):
        return False
    return _pr.run(
        ["git", "-C", str(root), "check-ignore", "-q", "--", target],
        capture_output=True).returncode == 0


def discover(root: Path) -> Discovery:
    """Every published gate record under ``root``, read-only."""
    d = Discovery()
    paths, how = _tracked_paths(root)
    d.enumeration = how
    for p in paths:
        if p.suffix != ".json":
            continue
        d.json_files += 1
        # LISTED BY GIT AND ABSENT FROM DISK IS ITS OWN STATE (vibe-ic#555).
        # Enumeration comes from `git ls-files` and reading comes from the
        # filesystem, and those disagree in a sparse or partial checkout: the
        # path is tracked, `stat` raises, and the record was being counted as
        # `unparsable` — a bucket meaning "this file's CONTENT is bad".
        #
        # Measured, and it is what made this gate host-dependent: a working
        # checkout adjudicated 225 records and a fresh `--detach` worktree 224,
        # same commit, because one tracked file had never been materialised
        # there. Both runs said PASS, from different populations. A denominator
        # that moves with the machine makes every ratio above it unreadable.
        # A RECORD WHOSE TARGET THE REPO DELIBERATELY DOES NOT TRACK IS NOT
        # PART OF THE POPULATION. Disclosing the shortfall (the previous fix)
        # made the difference legible; it did not remove it, and the probe still
        # reported HOST_DEPENDENT because 225 != 224.
        #
        # The cause, once #556's investigation named it: these are symlinks into
        # `benchmark-data/ic/*/clean_run_*/`, which `.gitignore:138` excludes on
        # purpose — a raw run directory can carry a commercial-PDK identifier in
        # its NAME. Whether such a record resolves is a fact about which machine
        # ran the flow, never about the commit.
        #
        # Measured: 11 of the corpus's 114 `.json` symlinks point into that
        # ignored tree. Excluding them by the repository's OWN declaration makes
        # the denominator identical on every machine by construction, rather
        # than by hoping every checkout ran the same things.
        if p.is_symlink() and _target_deliberately_untracked(root, p):
            d.deliberately_untracked += 1
            continue
        if not p.exists():
            d.absent_from_disk += 1
            continue
        try:
            if p.stat().st_size > MAX_RECORD_BYTES:
                d.oversize += 1
                continue
            data = json.loads(p.read_text(errors="replace"))
        except (OSError, ValueError):
            d.unparsable += 1
            continue
        if (not isinstance(data, dict)
                or not isinstance(data.get(_ra.PROGRAM_KEY), str)
                or _ra.VERDICT_KEY not in data):
            d.not_a_record += 1
            continue
        try:
            rel = str(p.relative_to(root))
        except ValueError:  # pragma: no cover - paths come from root
            rel = str(p)
        d.records.append(Record(path=p, rel=rel,
                                gate=data[_ra.PROGRAM_KEY], data=data))
    d.records.sort(key=lambda rec: (rec.gate, rec.rel))
    return d


def adjudicate(disc: Discovery, programs_dir: Path) -> Dict[str, Any]:
    """Compare every published verdict against its gate's CURRENT rules."""
    gates = sorted({r.gate for r in disc.records})
    loads: Dict[str, _ra.GateLoad] = {
        g: _ra.load_gate(g, programs_dir) for g in gates}

    # A declaration whose fingerprint no longer matches its gate is not a
    # softer form of "no rules": it is a rule change that landed without the
    # rules being re-reviewed, which is the exact staleness this check exists
    # for, one level up. It FAILS, and every record of that gate is undecidable.
    drift: Dict[str, str] = {}
    for g, load in loads.items():
        if load.rules is not None:
            d = load.rules.drift()
            if d:
                drift[g] = d

    findings: List[Dict[str, Any]] = []
    undecidable: List[Dict[str, Any]] = []
    adjudicated: List[Dict[str, Any]] = []

    for rec in disc.records:
        load = loads[rec.gate]
        if load.rules is None:
            undecidable.append({"record": rec.rel, "gate": rec.gate,
                                "reason": load.reason, "detail": load.detail})
            continue
        if rec.gate in drift:
            undecidable.append({"record": rec.rel, "gate": rec.gate,
                                "reason": UNDECIDABLE_RULES_UNREVIEWED,
                                "detail": drift[rec.gate]})
            continue

        ran: List[str] = []
        blocked: List[Tuple[str, str, str]] = []
        for rule in load.rules.rules:
            absent = rule.applies_to(rec.data)
            if absent:
                blocked.append((rule.rule_id, UNDECIDABLE_FIELDS_ABSENT,
                                f"the record does not carry {absent} — a rule "
                                f"whose inputs are not published cannot "
                                f"re-adjudicate the verdict beside them"))
                continue
            try:
                outcome = rule.decide(rec.data)
            except Exception as exc:  # noqa: BLE001 - disclosed, never swallowed
                blocked.append((rule.rule_id, UNDECIDABLE_RULE_ERRORED,
                                f"rule raised {exc!r}"))
                continue
            if isinstance(outcome, _ra.Undecidable):
                blocked.append((rule.rule_id, UNDECIDABLE_FIELD_UNREADABLE,
                                outcome.reason))
                continue
            ran.append(rule.rule_id)
            if isinstance(outcome, _ra.Supersession):
                findings.append({
                    "kind": STALE,
                    "record": rec.rel,
                    "gate": rec.gate,
                    "rule_id": rule.rule_id,
                    "landed_in": rule.landed_in,
                    "carried_verdict": rec.data.get(_ra.VERDICT_KEY),
                    "would_issue": outcome.would_issue,
                    "because": outcome.because,
                })
        if ran:
            adjudicated.append({"record": rec.rel, "gate": rec.gate,
                                "rules_applied": ran})
        else:
            reason, detail = (blocked[0][1], blocked[0][2]) if blocked else (
                UNDECIDABLE_FIELDS_ABSENT,
                "the gate declares no rule that reaches this record")
            undecidable.append({"record": rec.rel, "gate": rec.gate,
                                "reason": reason, "detail": detail,
                                "rules_blocked": [b[0] for b in blocked]})

    by_reason = Counter(u["reason"] for u in undecidable)
    by_gate: Dict[str, Dict[str, int]] = defaultdict(dict)
    for u in undecidable:
        by_gate[u["gate"]][u["reason"]] = by_gate[u["gate"]].get(
            u["reason"], 0) + 1

    for gate, why in sorted(drift.items()):
        findings.append({"kind": UNDECIDABLE_RULES_UNREVIEWED, "gate": gate,
                         "record": "", "because": why})

    n_total = len(disc.records)
    n_adj = len(adjudicated)
    denom = _gd.Denominator(
        unit=("published gate record re-adjudicated against its producing "
              "gate's CURRENT decision rules, from the record's own fields"),
        examined=n_adj,
        considered=n_total,
        not_applicable_reason="" if n_adj else _vacuous_reason(disc, by_reason),
        details={
            "records_undecidable": len(undecidable),
            "undecidable_by_reason": dict(sorted(by_reason.items())),
            "undecidable_by_gate": {k: dict(sorted(v.items()))
                                    for k, v in sorted(by_gate.items())},
            "gates_publishing_records": len(loads),
            "gates_with_registered_rules": sum(
                1 for l in loads.values() if l.rules is not None),
            "enumeration": disc.enumeration,
            "json_files_scanned": disc.json_files,
            "json_not_a_gate_record": disc.not_a_record,
            "json_unparsable": disc.unparsable,
            "json_over_size_cap": disc.oversize,
            # Tracked by git and not on disk. Non-zero means this run saw a
            # SMALLER population than a full checkout would, so its ratios
            # are not comparable with another machine's (vibe-ic#555).
            "json_tracked_but_absent_from_disk": disc.absent_from_disk,
        },
    )
    summary: Dict[str, Any] = {
        # Carried into the SUMMARY as well as the denominator block: the
        # PASS line reads `summary`, and a key present only in the other
        # dict would have made the disclosure silently always-zero.
        "json_tracked_but_absent_from_disk": disc.absent_from_disk,
        "records_found": n_total,
        "records_adjudicated": n_adj,
        "records_undecidable": len(undecidable),
        "stale_count": sum(1 for f in findings if f["kind"] == STALE),
        "gates_unreviewed": sorted(drift),
        "vacuous": n_adj == 0,
    }
    _gd.attach(summary, denom)
    return {
        "program": "published_record_staleness_check",
        "version": "1.0.0",
        "summary": summary,
        "findings": findings,
        "undecidable": undecidable,
        "adjudicated": adjudicated,
    }


def _vacuous_reason(disc: Discovery, by_reason: Counter) -> str:
    """Why nothing could be adjudicated — required when ``examined == 0``."""
    if not disc.records:
        return (f"no published gate record was found: {disc.json_files} JSON "
                f"file(s) enumerated ({disc.enumeration}), none carrying both "
                f"a '{_ra.PROGRAM_KEY}' and a '{_ra.VERDICT_KEY}' field. "
                f"Nothing was compared against any gate's current rules.")
    spread = ", ".join(f"{k}={v}" for k, v in sorted(by_reason.items()))
    return (f"{len(disc.records)} published record(s) were found and NONE could "
            f"be re-adjudicated ({spread}). No verdict in this corpus has been "
            f"compared against the rules its gate applies today. Read this as "
            f"NOT CHECKED, not as a clean corpus.")


def _print_human(report: Dict[str, Any], strict_gates: List[str]) -> None:
    s = report["summary"]
    d = s[_gd.DENOMINATOR_KEY]
    det = d["details"]
    for f in report["findings"]:
        if f["kind"] == STALE:
            print(f"  [{f['kind']}] {f['record']}", file=sys.stderr)
            print(f"      gate {f['gate']} rule {f['rule_id']} "
                  f"(landed {f['landed_in']})", file=sys.stderr)
            print(f"      carries {f['carried_verdict']!r}; current rules "
                  f"would issue {f['would_issue']!r}", file=sys.stderr)
            print(f"      {f['because']}", file=sys.stderr)
        else:
            print(f"  [{f['kind']}] gate {f['gate']}", file=sys.stderr)
            print(f"      {f['because']}", file=sys.stderr)
    for g in strict_gates:
        print(f"  [NO_RULES_REGISTERED] gate {g} publishes records and "
              f"registers no re-adjudication rule (--strict)", file=sys.stderr)
    print(f"  denominator: adjudicated {s['records_adjudicated']} / "
          f"undecidable {s['records_undecidable']} / found "
          f"{s['records_found']} published gate record(s), from "
          f"{det['gates_publishing_records']} publishing gate(s) of which "
          f"{det['gates_with_registered_rules']} register rules "
          f"({det['enumeration']}, {det['json_files_scanned']} JSON file(s) "
          f"scanned)", file=sys.stderr)
    for reason, n in sorted(det["undecidable_by_reason"].items()):
        print(f"    undecidable {reason}: {n}", file=sys.stderr)
    _print_recorded_debt(s.get("recorded_debt_status") or [])


def _print_recorded_debt(recorded: List[Dict[str, Any]]) -> None:
    """Every recorded entry, with what this run could say about it.

    Printed at EVERY exit code on purpose. The classes that carry no
    instruction are the ones a reader most needs: a register entry nothing
    re-examined is invisible in the findings, and invisibility is what let an
    unexamined entry be read as a paid one (#536).
    """
    order = {DEBT_RESOLVED: 0, DEBT_UNADJUDICATED: 1,
             DEBT_ENTRY_UNREADABLE: 1, DEBT_RECORD_UNPUBLISHED: 2,
             DEBT_STILL_SUPERSEDED: 3}
    for c in sorted(recorded, key=lambda c: (order.get(c["status"], 9),
                                             c["entry"])):
        tag = c["status"]
        if c.get("blocked_by") and tag != DEBT_ENTRY_UNREADABLE:
            tag = f"{tag} blocked_by={c['blocked_by']}"
        print(f"  (recorded debt: {tag}) {c['entry']}", file=sys.stderr)
        if c["status"] in (DEBT_UNADJUDICATED, DEBT_ENTRY_UNREADABLE,
                           DEBT_RECORD_UNPUBLISHED):
            print(f"      {c['detail']}", file=sys.stderr)
            # Deliberately worded without the words this program uses when it
            # DOES have evidence. The two claims must not be confusable by
            # grep, by a scrollback skim, or by the tests: the instruction to
            # shrink the register is issued in exactly one situation and its
            # vocabulary belongs to that situation alone (#536).
            print(f"      NOT a resolution: nothing re-adjudicated this "
                  f"entry, so this run says nothing about whether the record "
                  f"is still superseded. The entry stays.", file=sys.stderr)


def _adjudicate_register_without_a_corpus(bl_path: Optional[Path]) -> int:
    """NO_CORPUS has been decided; now answer for the debt register itself.

    The corpus moved to its own repository; this register did not. Every
    recorded entry is a published record this program is FORBIDDEN to correct,
    so the register is the only thing standing between "two records are known
    stale" and "nobody is counting" — and #922 established that a register is a
    plain JSON file, so `--write-baseline` was never the only way to add an
    entry to it.

    That question needs no corpus: :func:`_register_defects` asks whether
    `_write_baseline` COULD have produced this document, from the numbers the
    document itself records. Asking it here is what keeps the rc 0 from
    covering a register nobody looked at.

    WHAT THIS DOES NOT CLAIM. It says nothing about whether the recorded
    entries are still superseded, or whether new ones appeared — both need the
    records, and this run did not have them. The printed verdict says so.
    """
    if bl_path is None:
        print(f"[NOT CHECKED] {GATE}: no corpus was scanned and no register "
              f"was resolved (a non-default corpus suppresses the default "
              f"register), so this run adjudicated NOTHING — neither a record "
              f"nor the register. That is not a pass.", file=sys.stderr)
        return 2
    entries = _read_register(bl_path)
    if entries is None:
        # `_read_register` returns None for BOTH absent and unreadable. With a
        # corpus that is harmless — every recorded finding re-surfaces as NEW
        # and the run FAILs loudly on its own. With no corpus there is nothing
        # to re-surface, so the two must be refused here instead.
        state = ("does not exist" if not bl_path.is_file()
                 else "could not be read as a register")
        print(f"[NOT CHECKED] {GATE}: no corpus was scanned, so the debt "
              f"register is the only thing left to adjudicate, and {bl_path} "
              f"{state}. With no corpus nothing re-derives the entries it "
              f"should hold, so this run has judged NOTHING.", file=sys.stderr)
        return 2
    defects = _register_defects(bl_path)
    if defects:
        for d in defects:
            print(f"  (register) {d}", file=sys.stderr)
        print(f"[FAIL] {GATE}: no corpus was scanned, and {bl_path.name} is "
              f"not a state --write-baseline could have produced, so the "
              f"MAY-ONLY-SHRINK ratchet cannot be shown to have run over it. "
              f"Recorded debt read out of an unratcheted register is standing "
              f"permission wearing a register's name (vibe-ic#922). Re-write "
              f"it with --write-baseline (and --scope-expanded '<why>' if the "
              f"growth is genuinely newly-adjudicated scope).", file=sys.stderr)
        return 1
    print(f"[{GATE}] register: {len(entries)} recorded superseded record(s), "
          f"and {bl_path.name} is a document --write-baseline could have "
          f"produced.", file=sys.stderr)
    for e in entries:
        print(f"   recorded {e}", file=sys.stderr)
    print(f"[{GATE}] NO_CORPUS: 0 published gate record(s) found, 0 "
          f"adjudicated. NOTHING was re-adjudicated by this run — the entries "
          f"above are neither confirmed still stale nor shown to be paid, and "
          f"no NEW superseded record is ruled out. Point "
          f"${_cloc.CORPUS_ENV} at a clone to make this gate check the "
          f"records themselves.", file=sys.stderr)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="GATE: published gate records still say what their gate "
                    "would say today (re-adjudicated from the record alone).")
    ap.add_argument("corpus_root", nargs="?", default=None,
                    help="tree holding the published records "
                         "(default: <repo>/benchmark-data)")
    ap.add_argument("--programs-dir", default=None,
                    help="where the gate modules live (default: this "
                         "program's own directory)")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the machine-readable report here")
    ap.add_argument("--strict", action="store_true",
                    help="also FAIL when a gate publishes records and "
                         "registers no rules at all")
    ap.add_argument("--baseline", default=None,
                    help="debt register of ALREADY-REPORTED superseded "
                         "records; NEW ones still FAIL "
                         f"(default: {DEFAULT_BASELINE} beside this program)")
    ap.add_argument("--ignore-baseline", action="store_true",
                    help="answer as if no debt were recorded — every "
                         "superseded record FAILs")
    ap.add_argument("--write-baseline", action="store_true",
                    help="record today's superseded records as debt")
    ap.add_argument("--scope-expanded", default=None,
                    help=f"reason (>={SCOPE_REASON_MIN_CHARS} chars) a "
                         f"--write-baseline may GROW the register, naming what "
                         f"is now adjudicated that was not before; recorded "
                         f"only for the write that actually grew it")
    ap.add_argument("--print-decision-digest", dest="digest_of", default=None,
                    help="print the current decision fingerprint for one gate "
                         "and exit; use it to refresh a declaration")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="the caller asserts this repo need not carry the "
                         "published corpus. Turns 'no corpus discoverable "
                         "anywhere' from UNDETERMINED into NO_CORPUS (rc 0), "
                         "which STATES that 0 published records were "
                         f"adjudicated. It does NOT excuse a ${_cloc.CORPUS_ENV} "
                         "that is set and broken, and it does NOT excuse the "
                         "debt register: that lives in this repo and is still "
                         "put through the may-only-shrink checks.")
    a = ap.parse_args(argv)

    programs_dir = (Path(a.programs_dir).resolve() if a.programs_dir else _HERE)

    if a.digest_of:
        load = _ra.load_gate(a.digest_of, programs_dir)
        src = (programs_dir / f"{a.digest_of}.py")
        if not src.is_file():
            print(f"ERROR: no {a.digest_of}.py under {programs_dir}",
                  file=sys.stderr)
            return 1
        roots = (load.rules.decision_roots if load.rules is not None
                 else ("build_report",))
        try:
            digest = _ra.decision_fingerprint(
                src.read_text(errors="replace"), roots)
        except _ra.FingerprintError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"{a.digest_of} roots={list(roots)} digest={digest}")
        return 0

    if a.corpus_root:
        named = Path(a.corpus_root).resolve()
    else:
        # programs -> vibe-ic -> plugins -> vibe-ic-marketplace -> repo root
        named = programs_dir.parents[3] / "benchmark-data"
    # The pointer names a clone whose ROOT is what `benchmark-data/` was, so no
    # subdir is appended here — unlike the gates that sweep `<corpus>/ic`.
    root, origin = _cloc.resolve(named, gate=GATE, announce=True)

    # The register is resolved BEFORE the corpus, because it has to be
    # adjudicated on the NO_CORPUS path too and that path returns early.
    #
    # THE DEFAULT REGISTER BELONGS TO THE DEFAULT CORPUS AND NOTHING ELSE.
    # It records specific records of this repo's published tree; applying it to
    # some other tree would report every recorded entry as debt that was PAID
    # merely because a different corpus was handed in. Point the check
    # elsewhere and the register must be named explicitly. `$VIBE_IC_BENCHMARK_DATA`
    # is NOT "some other tree": it names the clone the default corpus BECAME,
    # with the same record keys, so it keeps the default register.
    bl_path = (Path(a.baseline) if a.baseline
               else (None if a.corpus_root else _HERE / DEFAULT_BASELINE))

    if not root.is_dir():
        # WAS: `ERROR: not a directory` at rc 1 — the code this program uses
        # for "a published record carries a verdict its gate would not issue".
        # It reported a finding against records it never opened. A crash is not
        # a verdict; see the module docstring.
        rc = _cloc.refuse(GATE, named, root, origin, a.corpus_may_be_absent,
                          "published gate record(s)")
        if rc != 0:
            return rc
        if a.write_baseline:
            # `now` would be [] over a scan that did not happen, and the writer
            # would silently shrink the register to nothing — a MAY-ONLY-SHRINK
            # rule satisfied by proving the opposite of what it exists to prove.
            print(f"[REFUSED] {GATE}: --write-baseline with no corpus would "
                  f"record 0 superseded records as a measurement and drop "
                  f"every recorded entry. NOTHING WAS SCANNED.",
                  file=sys.stderr)
            return 2
        return _adjudicate_register_without_a_corpus(bl_path)

    if origin == _cloc.ENV:
        # `_tracked_paths` falls back to a filesystem walk when git cannot
        # answer, and over a pointer-supplied tree that silently swaps the
        # population for one that includes untracked scratch output.
        why = _cloc.not_a_checkout_reason(root, "published gate records")
        if why:
            print(f"[{GATE}] UNDETERMINED: {why} `_tracked_paths` would fall "
                  f"back to a filesystem walk and adjudicate records nobody "
                  f"published, against a register keyed on the tracked ones.",
                  file=sys.stderr)
            return 2

    disc = discover(root)
    report = adjudicate(disc, programs_dir)
    report["corpus_root"] = str(root)

    strict_gates: List[str] = []
    if a.strict:
        by_gate = report["summary"][_gd.DENOMINATOR_KEY]["details"][
            "undecidable_by_gate"]
        strict_gates = sorted(
            g for g, reasons in by_gate.items()
            if _ra.LOAD_NO_DECLARATION in reasons)
    report["summary"]["strict_unregistered_gates"] = strict_gates

    s = report["summary"]
    now = sorted(debt_key(f) for f in report["findings"]
                 if f["kind"] == STALE)
    # `bl_path` was resolved above, before the corpus, because the NO_CORPUS
    # path adjudicates the register and returns before reaching here.
    on_disk = _read_register(bl_path)
    prev: Optional[List[str]] = None if a.ignore_baseline else on_disk

    if a.write_baseline:
        if bl_path is None:
            print("ERROR: --write-baseline over a non-default corpus needs an "
                  "explicit --baseline; the default register describes the "
                  "default corpus.", file=sys.stderr)
            return 1
        # ON_DISK, NOT PREV. `--ignore-baseline` asks for an answer computed as
        # if nothing were recorded — a READ semantic. A write that honoured it
        # would not know what it was about to delete, which disables both the
        # refuse-to-grow guard and the refuse-to-drop-the-unadjudicated guard
        # below, i.e. it would be a flag that reopens the hole they close.
        return _write_baseline(bl_path, now, on_disk, a.scope_expanded,
                               classify_recorded_debt(on_disk or [], now,
                                                      report))

    # A register is a plain JSON file, so --write-baseline was never the only
    # way to add an entry to it — and adding one by hand is how a NEW
    # superseded record stops being NEW. Before the recorded debt is trusted,
    # the file is asked whether the writer could have produced it (#922).
    # `--ignore-baseline` does not suppress this: it asks for an answer
    # computed as if nothing were recorded, which says nothing about whether
    # the file on disk was ratcheted.
    register_defects = _register_defects(bl_path)

    # Shrinking the register by hand on this program's say-so and shrinking it
    # with --write-baseline are the same irreversible edit, so both rest on the
    # same classification (#536).
    recorded = classify_recorded_debt(prev or [], now, report)

    new = [k for k in now if prev is None or k not in set(prev)]
    resolved = [c["entry"] for c in recorded if c["status"] == DEBT_RESOLVED]
    s["superseded_new"] = new
    s["superseded_recorded_as_debt"] = [] if prev is None else prev
    s["superseded_debt_resolved"] = resolved
    s["superseded_debt_unadjudicated"] = [
        c["entry"] for c in recorded
        if c["status"] in (DEBT_UNADJUDICATED, DEBT_ENTRY_UNREADABLE)]
    s["superseded_debt_record_unpublished"] = [
        c["entry"] for c in recorded
        if c["status"] == DEBT_RECORD_UNPUBLISHED]
    s["recorded_debt_status"] = recorded
    s["register_path"] = None if bl_path is None else str(bl_path)
    s["register_defects"] = register_defects

    if (new or resolved or s["gates_unreviewed"] or strict_gates
            or register_defects):
        verdict = "FAIL"
    elif s["vacuous"]:
        verdict = "VACUOUS_PASS"
    else:
        verdict = "PASS"
    report["verdict"] = verdict

    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    _print_human(report, strict_gates)

    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: "
              f"{s[_gd.DENOMINATOR_KEY]['not_applicable_reason']}",
              file=sys.stderr)
        return 2
    if verdict == "FAIL":
        if register_defects:
            for d in register_defects:
                print(f"  (register) {d}", file=sys.stderr)
            print(f"[FAIL] {bl_path.name if bl_path else DEFAULT_BASELINE} is "
                  f"not a state --write-baseline could have produced, so the "
                  f"MAY-ONLY-SHRINK ratchet cannot be shown to have run over "
                  f"it. Recorded debt read out of an unratcheted register is "
                  f"standing permission wearing a register's name. Re-write it "
                  f"with --write-baseline (and --scope-expanded '<why>' if the "
                  f"growth is genuinely newly-adjudicated scope).",
                  file=sys.stderr)
        if resolved:
            print(f"[FAIL] {len(resolved)} recorded entr(ies) were "
                  f"RE-ADJUDICATED by the rule that recorded them and are no "
                  f"longer superseded — the debt was paid; shrink "
                  f"{bl_path.name if bl_path else DEFAULT_BASELINE} so "
                  f"it cannot become standing permission.", file=sys.stderr)
        if new:
            print(f"[FAIL] {len(new)} published record(s) carry a verdict "
                  f"their gate's current rules would NOT issue. THIS PROGRAM "
                  f"DOES NOT REWRITE THEM — correcting a published record is "
                  f"the benchmark-agent's commit under NO-MIX; this names "
                  f"which and why.", file=sys.stderr)
        if s["gates_unreviewed"]:
            print(f"[FAIL] {len(s['gates_unreviewed'])} gate(s) changed their "
                  f"decision logic without their re-adjudication rules being "
                  f"re-reviewed. Never recordable as debt: it is fixable in "
                  f"the commit that caused it.", file=sys.stderr)
        return 1
    # A population that differs by machine makes every ratio above it
    # unreadable, so say so on the PASS line rather than only in the JSON.
    # This gate was reported HOST-DEPENDENT (vibe-ic#555) for exactly one
    # record: tracked by git, never materialised in a `--detach` worktree.
    absent = s.get("json_tracked_but_absent_from_disk") or 0
    absent_note = (f" {absent} tracked record(s) are NOT on disk in this "
                   f"checkout, so this population is smaller than a full one "
                   f"and these counts are not comparable across machines."
                   if absent else "")
    print(f"[PASS] no NEW superseded record "
          f"({len(now)} recorded as debt) — {s['records_adjudicated']} of "
          f"{s['records_found']} published record(s) re-adjudicated, "
          f"{s['records_undecidable']} could not be and are listed above."
          f"{absent_note}",
          file=sys.stderr)
    return 0


def _read_register(bl_path: Optional[Path]) -> Optional[List[str]]:
    """The recorded entries, or None when there is no readable register.

    None is "nothing is recorded", which is exactly what the caller needs to
    distinguish from an empty register: an unreadable file must not be read as
    a register that records nothing.
    """
    if bl_path is None or not bl_path.is_file():
        return None
    try:
        return sorted(str(x) for x in
                      (json.loads(bl_path.read_text()).get("known") or []))
    except (OSError, ValueError):
        return None


def _register_defects(bl_path: Optional[Path]) -> List[str]:
    """Ways this register is NOT a document ``_write_baseline`` could produce.

    Empty list = the file is consistent with the writer's own rules, which is
    the only evidence available on the read path that the ratchet was actually
    applied to it (#922). Each defect is prose a maintainer can act on.

    An ABSENT register is not a defect: "nothing is recorded" is a legitimate
    state and is already handled by the caller. An UNREADABLE one is not
    reported here either — :func:`_read_register` turns it into "nothing
    recorded", which makes every current finding NEW and FAILs the run loudly
    on its own.
    """
    if bl_path is None or not bl_path.is_file():
        return []
    try:
        doc = json.loads(bl_path.read_text())
    except (OSError, ValueError):
        return []                      # already fails via _read_register
    if not isinstance(doc, dict):
        return []                      # ditto
    defects: List[str] = []

    known = doc.get("known") or []
    if not isinstance(known, list):
        return []                      # ditto
    n = len(known)

    size = doc.get("size")
    if size is None:
        defects.append(
            f"records no `size`, so there is no count the writer sanctioned "
            f"to compare its {n} entr(ies) against. A register written by "
            f"--write-baseline always carries one; re-write it with "
            f"--write-baseline so the ratchet has something to hold.")
    elif not isinstance(size, int) or isinstance(size, bool):
        defects.append(f"has a non-integer `size` ({size!r}); the writer "
                       f"records the entry count it sanctioned.")
    elif size != n:
        defects.append(
            f"holds {n} entr(ies) but records `size` {size}: "
            f"{'entries were added to' if n > size else 'entries were removed from'}"
            f" it outside --write-baseline, so the MAY-ONLY-SHRINK ratchet "
            f"never ran over "
            f"{'them' if abs(n - size) != 1 else 'it'}.")

    prev_size = doc.get("previous_size")
    if prev_size is not None and (not isinstance(prev_size, int)
                                  or isinstance(prev_size, bool)):
        defects.append(f"has a non-integer `previous_size` ({prev_size!r}).")
        prev_size = None

    reason = doc.get("scope_expanded")
    reason_ok = (isinstance(reason, str)
                 and len(reason.strip()) >= SCOPE_REASON_MIN_CHARS)
    if reason is not None and not reason_ok:
        defects.append(
            f"records a `scope_expanded` that is not a written reason "
            f"(>= {SCOPE_REASON_MIN_CHARS} chars): {reason!r}. The writer "
            f"refuses one this short.")

    # The writer's own growth rule, re-checked against the recorded counts. It
    # is asked of `size` — the count the writer sanctioned — and not of the
    # length on disk, so a hand-appended entry is reported as the tamper it is
    # (above) rather than as unjustified growth it never went through.
    grown_to = size if isinstance(size, int) and not isinstance(size, bool) else n
    grew = isinstance(prev_size, int) and grown_to > prev_size
    if grew and not reason_ok:
        defects.append(
            f"grew {prev_size} -> {grown_to} with no written "
            f"`scope_expanded`. The register records debt owed to the "
            f"benchmark-agent, never permission to publish more superseded "
            f"records; --write-baseline exits 1 on exactly this, so a "
            f"register in this state did not come from it.")
    # A REASON IS SPENT BY THE WRITE THAT USED IT. Left behind on a write that
    # grew nothing, it becomes exactly what #922 was filed about one file over:
    # a standing string that pre-authorises the NEXT growth, so the only edit
    # left to forge is a number. The writer therefore records it only when it
    # actually authorised growth, and a register carrying one anyway did not
    # come from the writer either.
    if reason is not None and not grew:
        defects.append(
            f"records a `scope_expanded` reason on a register that did not "
            f"grow ({prev_size} -> {grown_to}). The writer records the reason "
            f"only for the write it authorised; one kept past that write is a "
            f"standing authorisation for a growth nobody has justified yet.")

    if known != sorted(str(k) for k in known):
        defects.append("has an unsorted `known` list; the writer always "
                       "writes it sorted, so this was edited by hand.")
    return defects


def _write_baseline(bl_path: Path, now: List[str], prev: Optional[List[str]],
                    scope_expanded: Optional[str],
                    recorded: List[Dict[str, Any]]) -> int:
    """Record today's superseded records as debt. MAY ONLY SHRINK.

    A register that may grow is not a register, it is a habit. Growing it needs
    a written reason naming what is newly ADJUDICATED — because a rule landing
    for a gate that had none genuinely widens what this check can see, and
    pre-existing staleness surfacing there is not a regression. Anything else
    that grows it is the corpus getting worse, which is what the register
    exists to stop.

    AND IT MAY NOT SHRINK ON AN ABSENCE OF EVIDENCE (#536). Shrink-only makes
    every drop irreversible by this program, so a drop needs the same positive
    evidence the read path now requires: the entry's own rule ran over the
    entry's own record and declined to supersede it. An entry that was merely
    not adjudicated — stale declaration, absent gate module, withdrawn
    declaration, unreadable field — is dropped by set subtraction just as
    quietly, and that is the deletion this check exists to prevent, performed
    by the tool instead of by hand.
    """
    blocked = [c for c in recorded
               if c["status"] in (DEBT_UNADJUDICATED, DEBT_ENTRY_UNREADABLE)]
    if blocked:
        for c in blocked:
            print(f"  (not adjudicated: {c.get('blocked_by') or '?'}) "
                  f"{c['entry']}", file=sys.stderr)
        print(f"[FAIL] refusing to DROP {len(blocked)} recorded entr(ies) "
              f"nothing re-adjudicated this run. The register MAY ONLY SHRINK, "
              f"so a drop is irreversible here, and 'produced no finding' is "
              f"not evidence the debt was paid when the rule never ran (#536). "
              f"Fix what made them undecidable, then write.", file=sys.stderr)
        return 1
    if (scope_expanded is not None
            and len(scope_expanded.strip()) < SCOPE_REASON_MIN_CHARS):
        print(f"[FAIL] --scope-expanded needs a real reason "
              f"(>={SCOPE_REASON_MIN_CHARS} chars) "
              f"naming which gate's rules newly adjudicate these records.",
              file=sys.stderr)
        return 1
    if prev is not None and len(now) > len(prev) and scope_expanded is None:
        print(f"[FAIL] refusing to GROW the register "
              f"({len(prev)} -> {len(now)}): it records debt owed to the "
              f"benchmark-agent, never permission to publish more superseded "
              f"records. If a NEWLY-REGISTERED rule is what surfaced these, "
              f"say so with --scope-expanded '<why>'.", file=sys.stderr)
        return 1
    bl_path.write_text(json.dumps(
        {"_comment": (
            "Published gate records carrying a verdict their gate's CURRENT "
            "rules would not issue (vibe-ic#510). MAY ONLY SHRINK. Correcting "
            "one is the benchmark-agent's commit under NO-MIX — results and "
            "plugin fixes never share a commit — so they are recorded here, "
            "not silently fixed by the plugin that found them."),
         "previous_size": None if prev is None else len(prev),
         # The count THIS write sanctioned. `previous_size` alone cannot carry
         # the ratchet on the read path: it is the size grown FROM, so a hand
         # appended entry sits above it just as a legitimately written one does
         # (#922).
         "size": len(now),
         # Recorded ONLY for the write it authorised. Carried past that write
         # it would be a standing permission for the NEXT growth, which is the
         # defect this ratchet exists to refuse (#922).
         "scope_expanded": (scope_expanded if (prev is not None
                                               and len(now) > len(prev))
                            else None),
         "known": now}, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {bl_path} ({len(now)} entr(ies))", file=sys.stderr)
    return 0


if __name__ == "__main__":
    # A stall is not a verdict about the commit: reach the stamp as rc 2
    # (this gate's 'could not measure'), announced, never as a finding.
    raise SystemExit(_pr.exit_undetermined_on_stall(main))
