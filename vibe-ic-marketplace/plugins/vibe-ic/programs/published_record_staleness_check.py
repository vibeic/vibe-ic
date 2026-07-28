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
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _gate_denominator as _gd
import _record_adjudication as _ra

_HERE = Path(__file__).resolve().parent

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
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                           capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        r = None
    if r is not None and r.returncode == 0:
        rels = [p.decode("utf-8", "replace")
                for p in r.stdout.split(b"\0") if p]
        return [root / p for p in rels], "git-tracked"
    return sorted(root.rglob("*.json")), "filesystem-walk"


def discover(root: Path) -> Discovery:
    """Every published gate record under ``root``, read-only."""
    d = Discovery()
    paths, how = _tracked_paths(root)
    d.enumeration = how
    for p in paths:
        if p.suffix != ".json":
            continue
        d.json_files += 1
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
        },
    )
    summary: Dict[str, Any] = {
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
                    help="reason (>=30 chars) a --write-baseline may GROW the "
                         "register, naming what is now adjudicated that was "
                         "not before")
    ap.add_argument("--print-decision-digest", dest="digest_of", default=None,
                    help="print the current decision fingerprint for one gate "
                         "and exit; use it to refresh a declaration")
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
        root = Path(a.corpus_root).resolve()
    else:
        # programs -> vibe-ic -> plugins -> vibe-ic-marketplace -> repo root
        root = programs_dir.parents[3] / "benchmark-data"
    if not root.is_dir():
        # rc 1, not 2: rc 2 is the disclosed-skip tier and a run that never
        # started must not be credited as one.
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 1

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
    # THE DEFAULT REGISTER BELONGS TO THE DEFAULT CORPUS AND NOTHING ELSE.
    # It records specific records of this repo's published tree; applying it to
    # some other tree would report every recorded entry as debt that was PAID
    # merely because a different corpus was handed in. Point the check
    # elsewhere and the register must be named explicitly.
    bl_path = (Path(a.baseline) if a.baseline
               else (None if a.corpus_root else _HERE / DEFAULT_BASELINE))
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

    if new or resolved or s["gates_unreviewed"] or strict_gates:
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
    print(f"[PASS] no NEW superseded record "
          f"({len(now)} recorded as debt) — {s['records_adjudicated']} of "
          f"{s['records_found']} published record(s) re-adjudicated, "
          f"{s['records_undecidable']} could not be and are listed above.",
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
    if scope_expanded is not None and len(scope_expanded.strip()) < 30:
        print("[FAIL] --scope-expanded needs a real reason (>=30 chars) "
              "naming which gate's rules newly adjudicate these records.",
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
         "scope_expanded": scope_expanded,
         "known": now}, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {bl_path} ({len(now)} entr(ies))", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
