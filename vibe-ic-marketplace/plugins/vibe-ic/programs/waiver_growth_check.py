#!/usr/bin/env python3
"""
waiver_growth_check.py — v0.112 release-gate (BACKLOG-v10 P0 follow-up).

Compares the current `<project>/waivers.json` against a baseline (frozen at
the previous release tag), as a SET of root waivers rather than a count of
them. Fails CI if:
  - root waivers the baseline did not carry appeared without an explicit
    `growth_rationale` in waivers.json — including at constant count, because
    closing one waiver does not pay for opening another (vibe-ic#948), or
  - a previously-closed waiver re-appeared, or
  - a waiver's evidence pointer became stale (referenced file deleted).

Why this exists: the v0.108 <benchmark> benchmark showed waivers grew from 6
(Round 3 digital) → 9 (Round 4 + analog) without anyone tracking the
delta. Without this gate, "PASS_WITH_WAIVERS" can silently rot — every
release accumulates one more waiver until the chip has more deferred
work than executed.

Cascading entries (root + cascades_to) count ONCE for growth purposes —
the cascade is bookkeeping, not new deferred work. A `cascades_to` TARGET is
only resolved in the dialect whose target vocabulary is defined; in the other,
an entry declares its own derivation with `cascade_source`. See
:func:`_cascade_target_name` for why guessing the other vocabulary loses
waivers.

BOTH WAIVER DIALECTS ARE COUNTED
================================
A waivers.json carries its entry list under one of two top-level keys, and
this gate used to read ``waived_steps`` only — with a ``{"waived_steps": []}``
default that turned "I cannot see this dialect" into "there are no waivers".
Measured over the tracked corpus, 6 of 11 projects and 8 of 19 entries were
invisible to it: it reported 0, compared 0 against 0, and passed. A growth
gate that cannot see the dialect its own runner emits is not measuring growth,
and a project could have accumulated that dialect indefinitely without ever
moving the number. Same shape as the gate that reported "0 problems" because
it could not find the data.

The entry list now comes from ``_waiver_entries`` — the ONE reader of "where a
project's waiver entries live" — so this gate cannot drift from the other
waiver gates about what a waivers.json contains.

Parsing stays local rather than using ``_waiver_entries.read_document``,
deliberately: that helper fail-softs an unparseable file to None, and this gate
must keep exiting 2 on a corrupt document. Turning a corrupt waivers.json into
"0 waivers, PASS" would reintroduce the exact defect above one layer down. The
shared module blesses this split — callers that must distinguish "no entries"
from "malformed" use ``entries_by_key`` plus ``malformed_keys``, which is what
happens here.

WHAT IDENTIFIES A WAIVER, FOR GROWTH ACCOUNTING
==============================================
Growth is a set difference across runs, so every entry needs a key that is
(a) STABLE — the same deferred obligation must produce the same key on the
next run, or the gate reports a phantom close plus a phantom open; and
(b) DISCRIMINATING — two genuinely different obligations must produce
different keys, or real growth hides inside a collision.

The two dialects name themselves differently, so each is keyed by the fields
it actually carries:

  * ``waived_steps`` entries carry a canonical flow-step ``id``. Their key is
    ``repr(id)`` — byte-for-byte what this gate has always used, so adopting
    the shared reader cannot move a verdict this dialect already decided.
  * ``waivers`` entries carry no ``id``. They carry ``step`` (a runner-local
    role name), ``phase`` and ``ticket``, and their key is the triple.

Three fields are deliberately EXCLUDED from the key, each for a reason that
would otherwise break stability:

  * ``rationale``, ``evidence`` and ``reviewer_action`` are prose, and the
    auto-generated form of ``reviewer_action`` embeds the emitting runner's
    VERSION STRING. Keying on them would make one runner upgrade look like
    every waiver closed and an equal number opened — churn reported as
    turnover, on a gate whose whole job is to notice real turnover.
  * ``verdict_tier`` moves when an obligation is re-graded (deferred →
    partially satisfied). That is the SAME obligation changing severity, not
    one closing and another opening. Growth counts how many, not how bad.

And the step name is compared AS WRITTEN, never resolved through
``_waiver_entries.STEP_NAME_TO_ID``. That map is MANY-TO-ONE — several
physical-verification role names share one canonical step id — so resolving
first would fuse a project that separately waives two of those roles, which is
the shape the runner actually emits, into a single counted waiver. On the
tracked corpus that alone would have under-counted 8 entries as 6. The shared
module states this constraint explicitly; this gate obeys it.

The key is rendered as a string because the two dialects' identities are not
mutually orderable, and the report sorts them. The renderings cannot collide:
a ``waivers`` key is prefixed ``waivers:``, while a ``waived_steps`` key is
``repr()`` of its id — which for a string id always begins with a quote.

THE RATIONALE REMEMBERS WHAT IT WAS WRITTEN AGAINST (vibe-ic#922)
=================================================================
``growth_rationale`` used to be one document-level string, and the whole test
applied to it was ``len(strip()) >= 30``. Thirty characters of anything —
measured, thirty literal ``x`` — made ``growth_justified`` true for ANY net
growth of ANY size, and it stayed true forever. Three properties followed, none
of them intended: the string that justified one waiver justified fifty
(UNBOUNDED); it named nothing, so a sentence written about waiver X covered
waiver Y added three releases later (UNSCOPED); and it was never renewed
(NON-EXPIRING). This gate's own ``details`` text describes the harm it believes
it prevents — "every release accumulates more deferred work until the project
has more open waivers than executed steps" — which is precisely what a
permanent blanket produces while the gate reports PASS.

So the rationale now carries the population it was written against:
``growth_rationale_covers``, the root-waiver count present when the author
wrote it. The rationale justifies growth only while that number still equals
the count in the file.

EQUAL, not "at least". ``covers >= current`` would let a single edit reserve
headroom — write 51 beside a file holding one waiver and the next fifty are
pre-authorised, which is the same blanket with a number in front of it. Under
equality a rationale can only ever describe the population beside it, so every
subsequent waiver forces the author back to this field, in the same edit, with
the reason in view. That is what "the ratchet has a memory" buys: growth is
still an operator decision made in the data, but it is a decision made once per
growth rather than once per project.

Of the three options the issue put up, this is the one that removes the
unboundedness at the least contract churn. Measured over the tracked corpus at
the time of the fix: 9 ``waivers.json``, 15 entries, and ZERO carrying a
``growth_rationale`` at all — so no existing document needed new prose under
any option. What separates them is the cost of each FUTURE growth event.
Scoping the rationale to the waiver identities it justifies (option 1) is more
faithful to intent, but a waiver's identity here is a gate-internal key —
``repr(id)``, or a ``step;phase;ticket`` triple — and requiring maintainers to
transcribe it would couple the file format to this module's private
representation and cost one written sentence per waiver. Expiry by age or
release count (option 3) bounds how long a blanket lasts but not how wide it
is, and this gate already carries a per-waiver ``approved_at`` clock; a second
document-level clock would age a rationale that is still exactly right. The
recorded count costs one integer, and it is an integer the gate already prints
on its own report line ("current: N root waivers").

AND THE RATIONALE SAYS WHAT IT IS A RATIONALE FOR (vibe-ic#922, second half)
===========================================================================
The recorded count made the population change LOUD. It did nothing about the
sentence beside it being about something else by then, because a COUNT cannot
bind prose to a population — it says how many, never which. Two states the
count-memory alone reports as PASS:

  * SWAP. Baseline holds ``alpha``; the file holds ``alpha, beta, gamma`` with
    ``growth_rationale_covers: 3``. A later edit closes ``gamma`` and opens
    ``delta``. The count is still 3, so it still equals the current count, net
    growth is still +2, and the rationale block is not touched at all: a
    sentence written about ``gamma`` now authorises ``delta``, and no field in
    the document moved.
  * DRIFT. Growth beyond the recorded count forces the author back to the
    integer — and to nothing else. Bumping 3 to 4 with the old sentence left
    standing renews the memory without renewing the reason.

So the memory now has a SECOND SPELLING, and the gate can also see when the
first one has gone stale.

``growth_rationale_covers`` may be written as a COUNT (an integer — exactly the
#945 contract, unchanged) or as a POPULATION: a LIST naming the root waivers
the rationale was written about. As a count it must EQUAL the current root
count. As a population it must BE the current root population — every root
waiver named, every name naming exactly one root. A name that matches no
current entry is refused for the same reason ``covers >= current`` is: a
rationale may describe the waivers beside it, never reserve room for waivers
that do not exist yet.

THE NAMES COME FROM THE DOCUMENT, NOT FROM THIS MODULE. A name is any value the
entry itself publishes under ``ticket``, ``id`` or ``step`` — fields the waiver
schema defines and the author writes. This gate's own growth key (``repr(id)``,
or a ``step;phase;ticket`` triple) is deliberately NOT the vocabulary: making
maintainers transcribe a composite key would bind waivers.json to this module's
private representation, which is the objection that kept option 1 shut. Names
are compared AS WRITTEN and never resolved through
``_waiver_entries.STEP_NAME_TO_ID``, for the reason stated above — that map is
many-to-one. For the same reason an AMBIGUOUS name — one published by more than
one current root, which is what ``step: "lvs"`` becomes the moment a project
defers that role twice — covers NOTHING and is reported. A name that could mean
either of two obligations has not identified either.

AND THE OLD SENTENCE CANNOT SIT STILL. The baseline is a frozen copy of a
previous waivers.json, so it may carry the ``growth_rationale`` that was on
record then. When it does, and the current document repeats that rationale
WORD FOR WORD (whitespace and case normalised, so re-wrapping or re-casing a
paragraph is not a renewal), and waivers have been added since — that sentence
demonstrably predates them. It is not a rationale for them; it is a rationale
that outlived its subject. ``GROWTH_RATIONALE_UNRENEWED``.

The way out is the author writing the reason for the population that is
actually there. A legitimate shrink is never asked to renew anything — the
rationale is consulted only when root waivers have been ADDED.

BOTH SPELLINGS ARE HELD TO IT (vibe-ic#968)
===========================================
``GROWTH_RATIONALE_UNRENEWED`` first shipped applying to the COUNT spelling
only: naming the population was accepted as its own renewal, on the reasoning
that "keeping the words and re-declaring which waivers they cover is a decision
the author made in the data". Measured, it is not a decision at all. The scope
list is a PURE FUNCTION OF waivers.json — twenty lines that never open the
baseline and never read ``growth_rationale`` derive it from the entries' own
``ticket``/``id``/``step`` — so the identical argument that retired the count as
a binding of prose to a population (#945: a count is mechanically derivable,
therefore it cannot say the sentence is about these waivers) retires the list.
Worse, the count-arm failure message PRINTED the derivation as its suggested
repair, so the gate shipped the recipe for its own bypass; and because the list
spelling was rejected outright before the scope work, that bypass was NEW.

So neither spelling exempts the sentence. ``not rationale_unrenewed`` is a
factor of ``growth_justified``, not a term inside one arm of it, which is what
the comment beside that decision already claimed. The scope list keeps every
job it was added for — it is still the only thing that says WHICH waivers a
reason covers, and ``GROWTH_RATIONALE_SCOPE_MISMATCH`` still bites — it simply
no longer doubles as a renewal. A reason and its subject are two statements and
the document has to carry both.

GROWTH IS A POPULATION, NOT A CARDINALITY (vibe-ic#948)
=======================================================
The gate used to consult the rationale only when NET growth exceeded tolerance,
and net is a difference of two counts. Delete one waiver and add another and
the difference is zero: the population changed completely, and the gate did not
look — not renewed, not scope-checked, not read. The rationale could describe a
waiver that no longer exists while authorising one it has never seen, and every
field in the report said PASS. That is the same defect as counting an
unreadable document as zero waivers, one level up: a number that moves for two
reasons is not a measurement of either.

The set difference was already computed here — ``new_waivers`` and
``removed_waivers`` are printed on the report — and only the TRIGGER was
scalar. It is now the added set: the rationale is consulted when more than
``--tolerance`` root waivers are present that the baseline did not carry,
whatever else closed in the same edit. A pure shrink adds nothing and is still
never asked to renew; closing an unrelated waiver no longer PAYS for opening a
new one, because deferred work is not fungible by the count.

WHERE THE GATE CANNOT YET SPEAK, IT SAYS SO (vibe-ic#948)
=========================================================
Renewal is decidable only against an earlier sentence on record. Where the
baseline carries no substantive ``growth_rationale`` — which is the state of
every tracked waivers.json in this repo today, and precisely why the scope
work's contract impact was 0 files — the gate cannot tell a fresh reason from a
copied one, and #945's count/scope memory is the whole of what it can say.

It used to pass in silence there, and "0 files affected" reads like safety when
it is a statement about REACH. So that state is now disclosed in its own right:
``GROWTH_RATIONALE_RENEWAL_UNDECIDED`` (WARN, and ``growth_rationale_renewal``
in the JSON) says the renewal question was asked and could not be answered.
It is a WARN and not an ERROR deliberately — turning "I cannot check this" into
a block would re-price every growth event this repo has already sanctioned
under the count contract, which is a different decision from making the gate's
own silence visible.

THE BASELINE IS NEVER REWRITTEN BY THIS GATE
============================================
Making the second dialect visible means projects carrying it now compare a
real count against whatever baseline they have. This gate does NOT re-baseline
them, and does not write a baseline at all — a gate that edits its own
reference to stay green is issuing a certificate about itself.

When no baseline file exists there is nothing frozen to preserve: the
comparison is against an EMPTY document, and entries then read as growth. That
is not a new policy invented here — it is the behaviour this gate already
applies, and already has a shipped test for, on the dialect it could see. The
escape hatches are the ones that were always there and are all operator-driven
and recorded in the data: a substantive top-level ``growth_rationale``, an
explicit ``--baseline``, or ``--tolerance``.

Because "compared against an absent baseline" and "compared against a recorded
baseline of zero" produce the same number and very different meanings, the
report now says which one happened, in both the text and the JSON
(``baseline_present``).

Usage:
  python3 waiver_growth_check.py <project_dir> \\
      [--baseline <path>] [--tolerance N] [--json [PATH]]

Default baseline: `<project>/.vibe-ic-state/waivers_baseline.json`
Default tolerance: 0 (any root waiver the baseline did not carry, without a
rationale, fails)
Exit codes:
  0  PASS — no root waiver was added since the baseline, OR every addition has
     an explicit rationale that records the current waiver population
     (`growth_rationale_covers`, as a count or as a list naming it) and is not
     the sentence frozen in the baseline
  1  FAIL — waivers grew unjustifiably
  2  IO error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _waiver_entries as _we  # noqa: E402  (after sys.path bootstrap)

#: Fields that identify a ``waivers``-dialect entry, in key order. See the
#: module docstring for why prose, version-bearing and severity fields are not
#: among them.
_WAIVERS_IDENTITY_FIELDS: Tuple[str, ...] = ("step", "phase", "ticket")

#: Minimum length of a substantive ``growth_rationale``. Unchanged from the
#: value this gate has always applied; named so the docstring, the finding
#: text and the predicate cannot drift apart about what "substantive" is.
GROWTH_RATIONALE_MIN_CHARS = 30

#: The population a ``growth_rationale`` was written against — spelled as the
#: root-waiver COUNT (an integer) or as the population itself (a list of names
#: the entries publish). See "THE RATIONALE REMEMBERS WHAT IT WAS WRITTEN
#: AGAINST" and "AND THE RATIONALE SAYS WHAT IT IS A RATIONALE FOR" in the
#: module docstring.
_COVERS_FIELD = "growth_rationale_covers"

#: The fields an entry publishes a NAME under, in preference order. Every one
#: is written by the document's author and defined by the waiver schema — this
#: gate's own composite growth key is deliberately not among them, so naming a
#: waiver never requires knowing how this module keys one.
_PUBLISHED_NAME_FIELDS: Tuple[str, ...] = ("ticket", "id", "step")


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


def _load(path: Path) -> Tuple[Dict[str, Any], bool]:
    """``(document, present)``.

    An ABSENT file yields an empty document and ``present=False`` — the caller
    must be able to say so, because "no baseline was ever frozen" and "the
    frozen baseline held zero waivers" are the same number and different
    facts. An UNPARSEABLE file still exits 2: a corrupt waiver list must never
    be silently downgraded to "no waivers"."""
    if not path.exists():
        return {}, False
    try:
        return json.loads(path.read_text()), True
    except Exception as exc:
        print(f"[ERROR] cannot parse {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)


def _identity(dialect: str, entry: Any) -> str:
    """The stable, discriminating key for one waiver entry.

    ``!r`` is used on every field value so that an absent field (``None``) can
    never be confused with the literal string ``"None"``, nor an integer step
    with its decimal spelling — an identity that is ambiguous about its own
    inputs cannot support a set difference."""
    if not isinstance(entry, dict):
        # Malformed, but it is still an entry. Counting it keeps a shape this
        # gate does not understand from silently reading as zero.
        return f"{dialect}:<non-dict>{entry!r}"
    if dialect == "waived_steps" and "id" in entry:
        return repr(entry["id"])
    fields = ";".join(f"{f}={entry.get(f)!r}" for f in _WAIVERS_IDENTITY_FIELDS)
    return f"{dialect}:{fields}"


def _covers_count(waivers_doc: Any) -> Optional[int]:
    """The root-waiver count recorded beside ``growth_rationale``, or None when
    the document records no usable one.

    ``bool`` is excluded even though it is an ``int`` subclass: a
    ``growth_rationale_covers: true`` would otherwise read as "this rationale
    was written against exactly one waiver", which is a number the author
    never wrote. A memory the gate invented is not a memory.

    A malformed value returns None rather than raising, and None is reported —
    the same shape as every other unreadable field in this gate: what cannot
    be read is disclosed, never counted as satisfied."""
    if not isinstance(waivers_doc, dict):
        return None
    raw = waivers_doc.get(_COVERS_FIELD)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def _covers_names(waivers_doc: Any) -> Optional[List[Any]]:
    """The POPULATION spelling of the memory — the list of names recorded
    beside ``growth_rationale`` — or None when the document does not use it.

    Elements are returned RAW. Whether each one names a waiver is decided by
    :func:`_scope_report` against the entries actually present, because a name
    is only meaningful relative to the population it is claimed over."""
    if not isinstance(waivers_doc, dict):
        return None
    raw = waivers_doc.get(_COVERS_FIELD)
    return raw if isinstance(raw, list) else None


def _render_name(value: Any) -> Optional[str]:
    """One JSON scalar as the name it spells, or None when it spells none.

    BOTH SIDES of the comparison are rendered here — the value an entry
    publishes and the value the rationale's scope list records — so a waiver
    whose ``id`` the document writes as the integer ``39`` is named by ``39``
    or by ``"39"``, whichever the author reaches for. One renderer is the
    point: two would let the scope list and the entry disagree about what a
    name is, which is how a scope that looks satisfied covers nothing.

    Booleans are excluded for the same reason they are excluded from the
    count — ``True`` is not a name anybody wrote — and a container is not a
    name at all."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float)):
        return None
    rendered = str(value).strip()
    return rendered or None


def _published_names(entry: Any) -> List[str]:
    """The names an entry publishes for itself, from its own fields.

    Compared AS WRITTEN, and never resolved through the many-to-one step-name
    map — see the module docstring."""
    if not isinstance(entry, dict):
        return []
    names: List[str] = []
    for field in _PUBLISHED_NAME_FIELDS:
        rendered = _render_name(entry.get(field))
        if rendered and rendered not in names:
            names.append(rendered)
    return names


def _normalized_rationale(text: Any) -> str:
    """A rationale reduced to what it SAYS, for comparing one against another.

    Whitespace is collapsed and case folded, so re-wrapping a paragraph or
    re-casing a word is not mistaken for renewing the reason. Anything that is
    not a string normalises to the empty string, which compares equal to
    nothing substantive."""
    if not isinstance(text, str):
        return ""
    return " ".join(text.split()).casefold()


def _scope_report(cover_names: List[Any],
                  root_pairs: List[Tuple[str, Any]]) -> Dict[str, List[str]]:
    """How a recorded population lines up with the waivers actually present.

    Returns the three ways it can fail to be that population, each reported
    rather than collapsed into a bare False — an author told only "the scope is
    wrong" has to guess which waiver the gate meant.

      * ``unnamed`` — root waivers no recorded name identifies. These are the
        waivers the rationale does not cover.
      * ``unmatched`` — recorded names that identify no current entry. Either
        the waiver was closed and the rationale still talks about it, or the
        name is for a waiver that does not exist yet, which is the headroom
        the count spelling is already forbidden from reserving.
      * ``ambiguous`` — names published by more than one root. A role name is
        not unique; a name that could mean either of two obligations has
        identified neither, so it covers neither.
    """
    by_name: Dict[str, List[str]] = {}
    for dialect, entry in root_pairs:
        identity = _identity(dialect, entry)
        for name in _published_names(entry):
            by_name.setdefault(name, []).append(identity)

    covered: set = set()
    unmatched: List[str] = []
    ambiguous: List[str] = []
    for raw in cover_names:
        name = _render_name(raw)
        owners = by_name.get(name, []) if name else []
        if not owners:
            unmatched.append(repr(raw))
        elif len(owners) > 1:
            ambiguous.append(repr(raw))
        else:
            covered.add(owners[0])

    unnamed = [_identity(d, e) for d, e in root_pairs
               if _identity(d, e) not in covered]
    return {"unnamed": sorted(unnamed),
            "unmatched": sorted(unmatched),
            "ambiguous": sorted(ambiguous)}


def _cascade_target_name(dialect: str, entry: Dict[str, Any]) -> Any:
    """The value another entry's ``cascades_to`` list would name this entry by,
    or None when this dialect has no defined target vocabulary.

    Only ``waived_steps`` has one: its targets are canonical step ids, unique
    within a document. The attestation dialect names itself by a step ROLE, and
    a role is NOT unique — a project can defer the same role twice under two
    tickets, which is the corpus shape. Treating a ``cascades_to`` target as a
    role name would suppress EVERY entry sharing that role: measured, one such
    declaration hid two genuinely distinct obligations, turning real growth
    into a PASS. A growth gate must not guess a vocabulary in the direction
    that loses waivers, so in that dialect derivation is only ever taken from
    the entry's OWN ``cascade_source``, which cannot over-reach."""
    return entry.get("id") if dialect == "waived_steps" else None


def _dialect_entries(waivers_doc: Any) -> List[Tuple[str, Any]]:
    """``[(dialect, entry)]`` for every entry under either list key, in the
    shared reader's documented order."""
    out: List[Tuple[str, Any]] = []
    for dialect, entries in _we.entries_by_key(waivers_doc).items():
        out.extend((dialect, entry) for entry in entries)
    return out


def _root_entries(waivers_doc: Any) -> List[Tuple[str, Any]]:
    """``[(dialect, entry)]`` for the root waivers — entries that are NOT
    cascades.

    A 'root' is any entry that is neither the target of another entry's
    ``cascades_to`` list nor self-declared derived via ``cascade_source``.
    Cascade targets are resolved WITHIN a dialect, never across one, and only
    in the dialect whose target vocabulary is defined — see
    :func:`_cascade_target_name`.

    The ENTRIES are returned, not only their identities, because scoping a
    rationale asks each root what names it publishes. Counting and naming must
    walk the same set: a root that growth counts but scope cannot see would be
    a waiver nobody has to name."""
    pairs = _dialect_entries(waivers_doc)

    cascade_targets: Dict[str, set] = {}
    for dialect, entry in pairs:
        targets = cascade_targets.setdefault(dialect, set())
        if not isinstance(entry, dict):
            continue
        for child in entry.get("cascades_to") or []:
            try:
                targets.add(child)
            except TypeError:
                continue  # unhashable target cannot name any entry

    roots: List[Tuple[str, Any]] = []
    for dialect, entry in pairs:
        if isinstance(entry, dict):
            target_name = _cascade_target_name(dialect, entry)
            try:
                is_child = (target_name is not None
                            and target_name in cascade_targets.get(dialect, set()))
            except TypeError:
                # An unhashable identifier cannot be named by any target, and a
                # traceback is not a verdict — the entry is simply a root.
                is_child = False
            if is_child:
                continue  # this entry is a cascaded child, not a root
            if entry.get("cascade_source") is not None:
                continue  # explicitly marked as derived
        roots.append((dialect, entry))
    return roots


def _root_identities(waivers_doc: Any) -> List[str]:
    """Identities of the root waivers — :func:`_root_entries`, keyed."""
    return [_identity(dialect, entry)
            for dialect, entry in _root_entries(waivers_doc)]


def _looks_like_path(tok: str) -> bool:
    return "/" in tok and not tok.startswith(("http://", "https://"))


def _strip_locator(tok: str) -> str:
    """A trailing ``#fragment`` locates a position INSIDE the referenced file.
    It is not part of the filename, and leaving it attached would report every
    precise pointer as stale."""
    return tok.split("#", 1)[0].strip().rstrip(",.;")


def _evidence_files(entry: Dict[str, Any]) -> List[str]:
    """File paths an entry's ``evidence`` points at.

    ``evidence`` appears in two shapes and the gate used to read only one of
    them: ``isinstance(ev, str)`` and otherwise nothing. Across the tracked
    corpus EVERY entry carries the list shape, so this check examined zero
    pointers and had never once fired — the same "cannot read it, so report
    nothing" failure as the entry-list key itself, one field further down.

    The two shapes are mined differently because they mean different things:

      * a STRING evidence field is free text that may CONTAIN paths, so it is
        split into tokens and every path-looking token is checked (unchanged
        historical behaviour);
      * a LIST is a sequence of discrete pointer slots, so each element is ONE
        candidate pointer. An element containing whitespace is prose occupying
        a pointer slot, not a pointer — token-mining it yields fragments of
        sentences reported as missing files, which trains readers to ignore
        the finding. A real pointer is its own element.
    """
    ev = entry.get("evidence", "")
    files: List[str] = []
    if isinstance(ev, str):
        for tok in ev.replace(";", " ").split():
            if _looks_like_path(tok):
                files.append(_strip_locator(tok))
    elif isinstance(ev, (list, tuple)):
        for element in ev:
            if not isinstance(element, str):
                continue
            tokens = element.split()
            if len(tokens) != 1:
                continue  # empty, or prose rather than a single pointer
            if _looks_like_path(tokens[0]):
                files.append(_strip_locator(tokens[0]))
    return [f for f in files if f]


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Block CI when waivers grow unjustifiably. Reduces accumulation "
            "of deferred work across releases."
        )
    )
    ap.add_argument("project_dir", help="Project directory containing waivers.json")
    ap.add_argument("--baseline", default=None,
                    help="Baseline waivers.json (default: <project>/.vibe-ic-state/waivers_baseline.json)")
    ap.add_argument("--tolerance", type=int, default=0,
                    help=("Root waivers that may be ADDED without a rationale "
                          "(default 0). Counted over the added set, not the "
                          "net difference: closing one waiver does not pay "
                          "for opening another (vibe-ic#948)"))
    ap.add_argument("--stale-warn-days", type=int, default=90,
                    help="Waivers older than N days approved_at → WARN (default 90)")
    ap.add_argument("--stale-error-days", type=int, default=180,
                    help="Waivers older than N days approved_at → ERROR (default 180)")
    ap.add_argument("--json", nargs="?", const="-", default=None,
                    help="Emit JSON. Bare flag → stdout, with PATH → file")
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    cur_path = project / "waivers.json"
    base_path = Path(args.baseline) if args.baseline else (
        project / ".vibe-ic-state" / "waivers_baseline.json"
    )

    cur_doc, _cur_present = _load(cur_path)
    base_doc, base_present = _load(base_path)

    cur_roots = set(_root_identities(cur_doc))
    base_roots = set(_root_identities(base_doc))

    # The POPULATION, three ways, not one cardinality. `net_growth` keeps being
    # reported because it is the number this gate has always printed and other
    # readers key on it — but it is no longer what the verdict turns on: a swap
    # is net 0 and is a complete change of population (vibe-ic#948).
    new_waivers = cur_roots - base_roots
    removed_waivers = base_roots - cur_roots
    retained_waivers = cur_roots & base_roots
    net_growth = len(new_waivers) - len(removed_waivers)

    findings: List[Finding] = []

    # A document whose top level is not a JSON object carries no readable keys
    # at all. The shared reader fail-softs it to "no entries" — correct for a
    # caller asking "is this step waived", and a silent PASS for this one. It
    # is reported, in both documents: a growth number computed from a document
    # the gate could not read is not a measurement of anything.
    # An ABSENT file is not unreadable — `_load` gives it an empty object, and
    # its absence is disclosed separately.
    for label, doc, path in (("current", cur_doc, cur_path),
                             ("baseline", base_doc, base_path)):
        if not isinstance(doc, dict):
            findings.append(Finding(
                severity="ERROR",
                category="WAIVER_DOCUMENT_UNREADABLE",
                message=(
                    f"the {label} waiver document is a JSON "
                    f"{type(doc).__name__}, not an object, so it carries no "
                    f"readable entry list: {path}"
                ),
                details=(
                    "Counting an unreadable document as zero waivers is the "
                    "failure this gate was fixed for. Repair the document."
                ),
            ))

    # A list key that is PRESENT but does not hold a list contributes no
    # entries. Reading that as "no waivers" is the defect this gate was fixed
    # for, so the unreadable shape is reported instead of counted as zero.
    for key in _we.malformed_keys(cur_doc):
        findings.append(Finding(
            severity="ERROR",
            category="WAIVER_LIST_UNREADABLE",
            message=(
                f"{cur_path.name} has a top-level `{key}` that is not a list "
                f"(found {type(cur_doc.get(key)).__name__}). Its entries "
                f"cannot be counted, so the growth number below is computed "
                f"over an incomplete list."
            ),
            details=(
                "A growth verdict computed over entries the gate could not "
                "read is not a verdict. Fix the shape or remove the key."
            ),
        ))

    # Stale evidence check — referenced files must still exist. Every dialect
    # is walked: an unchecked evidence pointer is an unchecked waiver.
    for _dialect, entry in _dialect_entries(cur_doc):
        if not isinstance(entry, dict):
            continue
        for f in _evidence_files(entry):
            f_path = (project / f).resolve() if not f.startswith("/") else Path(f)
            try:
                f_path.relative_to(project)
            except ValueError:
                continue  # outside project, skip
            if not f_path.exists():
                # Heuristic — only WARN, since evidence may reference foundry-side
                # tools or future artefacts.
                findings.append(Finding(
                    severity="WARN",
                    category="STALE_EVIDENCE",
                    message=(
                        f"waiver {_identity(_dialect, entry)} evidence references "
                        f"{f} which does not exist in the project."
                    ),
                ))

    # v0.113 (BACKLOG-v10 P1.3): staleness-by-age. Waivers with an
    # `approved_at` field older than --stale-warn-days WARN; older than
    # --stale-error-days ERROR. Forces deferred work to actually progress
    # rather than rotting under "review_required: true" forever.
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for _dialect, entry in _dialect_entries(cur_doc):
        if not isinstance(entry, dict):
            continue
        approved_at = entry.get("approved_at", "")
        if not approved_at:
            continue
        if not isinstance(approved_at, str):
            # Widening this loop to every dialect must not widen a crash: a
            # non-string timestamp is a reportable defect, not a traceback.
            findings.append(Finding(
                severity="WARN",
                category="APPROVED_AT_INVALID",
                message=(f"waiver {_identity(_dialect, entry)} has non-string "
                         f"approved_at: {approved_at!r}"),
            ))
            continue
        try:
            ts = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        except ValueError:
            findings.append(Finding(
                severity="WARN",
                category="APPROVED_AT_INVALID",
                message=(f"waiver {_identity(_dialect, entry)} has malformed "
                         f"approved_at: {approved_at!r}"),
            ))
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = (now - ts).days
        if age_days >= args.stale_error_days:
            findings.append(Finding(
                severity="ERROR",
                category="WAIVER_STALE_ERROR",
                message=(
                    f"waiver {_identity(_dialect, entry)} approved {age_days} days ago "
                    f"(>= {args.stale_error_days} day error threshold). "
                    f"Either close it (run the deferred check on the foundry "
                    f"deck and remove the waiver) or update approved_at with "
                    f"explicit `staleness_extension_rationale`."
                ),
            ))
        elif age_days >= args.stale_warn_days:
            findings.append(Finding(
                severity="WARN",
                category="WAIVER_STALE_WARN",
                message=(
                    f"waiver {_identity(_dialect, entry)} approved {age_days} days ago "
                    f"(>= {args.stale_warn_days} day warn threshold)."
                ),
            ))

    # Growth check.
    #
    # The rationale is substantive prose AND it carries the waiver population
    # it was written against. Both halves are required: prose alone is the
    # permanent blanket this gate was fixed for (vibe-ic#922), and a count
    # alone authorises nothing because nobody said why.
    rationale = cur_doc.get("growth_rationale", "") if isinstance(cur_doc, dict) else ""
    rationale_substantive = (
        isinstance(rationale, str)
        and len(rationale.strip()) >= GROWTH_RATIONALE_MIN_CHARS
    )
    covers = _covers_count(cur_doc)
    cover_names = _covers_names(cur_doc)
    current_root_count = len(cur_roots)
    # EQUAL, not >=. A rationale may describe the population it was written
    # beside; it may not reserve headroom above it. `covers >= current` would
    # let one edit pre-authorise every waiver up to the recorded ceiling, which
    # is the unbounded blanket again with a number in front of it.
    covers_current = covers is not None and covers == current_root_count

    # The POPULATION spelling: the same memory written as identities instead of
    # a cardinality. It is satisfied only when the recorded names ARE the
    # current root population — nothing unnamed, nothing named that is not
    # here, nothing named ambiguously.
    scope = _scope_report(cover_names, _root_entries(cur_doc)) \
        if cover_names is not None else None
    scope_ok = scope is not None and not any(scope.values())

    # An unchanged sentence cannot be a rationale for waivers added after it
    # was written. The baseline is a frozen waivers.json, so when it carries a
    # substantive rationale the gate has the earlier sentence on record and can
    # say so; when it does not, it has nothing to compare and says nothing.
    base_rationale = (base_doc.get("growth_rationale", "")
                      if isinstance(base_doc, dict) else "")
    baseline_rationale_substantive = (
        isinstance(base_rationale, str)
        and len(base_rationale.strip()) >= GROWTH_RATIONALE_MIN_CHARS
    )
    rationale_unrenewed = (
        baseline_rationale_substantive
        and bool(new_waivers)
        and _normalized_rationale(rationale) == _normalized_rationale(base_rationale)
    )

    # Three independent requirements, and `not rationale_unrenewed` is a factor
    # of the whole rather than a term inside one arm (vibe-ic#968). It used to
    # sit only in the count arm, so `scope_ok` short-circuited it — and since
    # the scope list is derivable from waivers.json without ever reading the
    # rationale or the baseline, that made an unrenewed sentence authorise
    # growth through a spelling the gate's own failure message recommended.
    # Both spellings say WHICH waivers; neither says the sentence is new.
    growth_justified = (
        rationale_substantive
        and not rationale_unrenewed
        and (scope_ok or covers_current)
    )

    # The rationale is consulted when root waivers were ADDED — not when a
    # difference of counts happens to be positive. A swap is an addition.
    population_grew = len(new_waivers) > args.tolerance

    # What the gate was able to decide about the reason itself, reported in its
    # own right so the reach of the check is visible instead of inferred from a
    # zero (vibe-ic#948).
    if not (population_grew and rationale_substantive):
        renewal_state = "not_consulted"
    elif not baseline_rationale_substantive:
        renewal_state = "undecided"
    elif rationale_unrenewed:
        renewal_state = "unrenewed"
    else:
        renewal_state = "renewed"

    if renewal_state == "undecided":
        findings.append(Finding(
            severity="WARN",
            category="GROWTH_RATIONALE_RENEWAL_UNDECIDED",
            message=(
                f"{len(new_waivers)} root waiver(s) were added since the "
                f"baseline and are authorised by a `growth_rationale`, but "
                + (f"there is no baseline file at {base_path}"
                   if not base_present else
                   f"the baseline at {base_path} carries no substantive "
                   f"`growth_rationale`")
                + ", so this gate has no earlier sentence on record and "
                f"CANNOT say whether that reason was written for these "
                f"waivers or copied forward. UNDECIDED, not verified: what "
                f"was checked here is the recorded population "
                f"(`{_COVERS_FIELD}`), never the freshness of the prose."
            ),
            details=(
                "Freeze a baseline that carries the rationale on record "
                "(this gate never writes one) to make renewal decidable from "
                "the next release on. Reported rather than passed in silence "
                "because a gate that cannot yet speak must not look like one "
                "that checked and approved."
            ),
        ))

    if population_grew and not growth_justified:
        no_baseline_note = ("" if base_present else
                            "No baseline file exists at the path below, so the "
                            "comparison was made against an EMPTY document and every "
                            "current waiver counts as new. Freeze a baseline (or pass "
                            "--baseline) to measure growth against a real reference. ")
        added_note = (
            f"{len(new_waivers)} root waiver(s) the baseline did not carry "
            f"(> tolerance {args.tolerance}; net count change {net_growth})")
        if not rationale_substantive:
            # Unchanged CATEGORY: a document with no usable rationale fails
            # exactly as it always has, and every caller matching on the
            # category keeps matching. The wording moved because the number it
            # quoted moved — a swap adds a waiver at net 0, and reporting that
            # as "net count grew by 0" would be the gate lying about its own
            # trigger (vibe-ic#948).
            findings.append(Finding(
                severity="ERROR",
                category="UNJUSTIFIED_WAIVER_GROWTH",
                message=(
                    f"waivers.json adds {added_note} without `growth_rationale`. "
                    f"New waivers: {sorted(new_waivers)}. "
                    + no_baseline_note
                    + f"Either close one of the new waivers, OR add a top-level "
                    f"`growth_rationale` field to waivers.json explaining why "
                    f"this deferred work is acceptable for this release, "
                    f"together with `{_COVERS_FIELD}: {current_root_count}` "
                    f"recording the waiver count it was written against."
                ),
                details=(
                    "Repeated growth without rationale leads to silent rot: every "
                    "release accumulates more deferred work until the project has "
                    "more open waivers than executed steps. This gate enforces "
                    "that growth is a deliberate, documented decision. Closing an "
                    "unrelated waiver in the same edit does not pay for a new "
                    "one: deferred work is not fungible by the count."
                ),
            ))
        else:
            # TWO INDEPENDENT DEFECTS, REPORTED INDEPENDENTLY. A rationale can
            # fail to say WHICH waivers it covers, and it can be a sentence
            # that predates them, and those are different repairs. Chaining
            # them behind one elif made the second invisible until the first
            # was fixed — and, before vibe-ic#968, made the second unreachable
            # for the whole population spelling.
            if cover_names is not None:
                # The author chose the population spelling, so the complaint is
                # about WHICH waivers it names — never "add a count instead".
                if not scope_ok:
                    parts = []
                    if scope["unnamed"]:
                        parts.append(
                            f"it names no waiver for {scope['unnamed']}, so those "
                            f"waiver(s) are not covered by it")
                    if scope["unmatched"]:
                        parts.append(
                            f"it names {scope['unmatched']}, which no current waiver "
                            f"publishes — a rationale may describe the waivers beside "
                            f"it, not ones that were closed or do not exist yet")
                    if scope["ambiguous"]:
                        parts.append(
                            f"it names {scope['ambiguous']}, which more than one "
                            f"current waiver publishes, so the name identifies none "
                            f"of them")
                    findings.append(Finding(
                        severity="ERROR",
                        category="GROWTH_RATIONALE_SCOPE_MISMATCH",
                        message=(
                            f"`{_COVERS_FIELD}` records the population the "
                            f"`growth_rationale` was written about, but it is not the "
                            f"population in waivers.json: " + "; ".join(parts) + ". "
                            f"waivers.json adds {added_note}. "
                            f"New waivers: {sorted(new_waivers)}. "
                            + no_baseline_note
                            + f"Name each of the {current_root_count} root waiver(s) "
                            f"exactly once, using a value the entry itself publishes "
                            f"under {', '.join(_PUBLISHED_NAME_FIELDS)}."
                        ),
                        details=(
                            "A rationale has to say what it is a rationale FOR. A "
                            "scope that omits a waiver is silent about it, and a "
                            "scope that names one which is not there is prose about "
                            "the wrong waiver — the state a document-level sentence "
                            "drifts into on its own."
                        ),
                    ))
            elif covers is None:
                findings.append(Finding(
                    severity="ERROR",
                    category="GROWTH_RATIONALE_WITHOUT_MEMORY",
                    message=(
                        f"waivers.json carries a substantive `growth_rationale` but no "
                        f"integer `{_COVERS_FIELD}`, so the rationale records no waiver "
                        f"population and authorises {added_note} without bound. "
                        f"New waivers: {sorted(new_waivers)}. "
                        + no_baseline_note
                        + f"Add `{_COVERS_FIELD}: {current_root_count}` beside the "
                        f"rationale to record the {current_root_count} root waiver(s) "
                        f"it is being written against."
                    ),
                    details=(
                        "A rationale with no recorded population is a permanent "
                        "authorization: the sentence written to justify one waiver "
                        "goes on justifying every waiver added after it, in any "
                        "number, forever. Recording the count is what makes the "
                        "next growth need its own decision."
                    ),
                ))
            elif not covers_current:
                findings.append(Finding(
                    severity="ERROR",
                    category="GROWTH_RATIONALE_STALE",
                    message=(
                        f"`growth_rationale` was written against {covers} root waiver(s) "
                        f"(`{_COVERS_FIELD}`), but waivers.json now holds "
                        f"{current_root_count}, and it adds {added_note}. "
                        f"The waivers added since are not covered by it. "
                        f"New waivers: {sorted(new_waivers)}. "
                        + no_baseline_note
                        + f"Either close the uncovered waiver(s), OR renew the "
                        f"rationale for the current population and set "
                        f"`{_COVERS_FIELD}: {current_root_count}`."
                    ),
                    details=(
                        "The recorded count is the rationale's memory. Growth beyond "
                        "it is growth nobody has justified yet — the renewal is the "
                        "decision, and moving the number without rewriting the "
                        "reason is a statement the author is making on the record."
                    ),
                ))

            if rationale_unrenewed:
                # Reported for BOTH spellings of the memory, and no longer
                # printing a way around itself. The old text ended by telling
                # the reader to swap the count for the list — which was a
                # working bypass derivable from waivers.json without opening
                # the baseline or reading the rationale (vibe-ic#968). A
                # failure message that names an escape it cannot check is a
                # recipe, not a repair.
                spelling = (
                    f"the list of names in `{_COVERS_FIELD}`, which says WHICH "
                    f"waivers the reason covers"
                    if cover_names is not None else
                    f"the count in `{_COVERS_FIELD}`, which says HOW MANY "
                    f"waivers stand beside the reason")
                findings.append(Finding(
                    severity="ERROR",
                    category="GROWTH_RATIONALE_UNRENEWED",
                    message=(
                        f"`growth_rationale` is word for word the sentence "
                        f"already frozen in the baseline at {base_path}, and "
                        f"{len(new_waivers)} root waiver(s) have been added "
                        f"since it was written: {sorted(new_waivers)}. It is "
                        f"not a rationale for them. "
                        + no_baseline_note
                        + f"Rewrite the reason for the waivers that are "
                        f"actually there, or close the waiver(s) that arrived "
                        f"after it. Recording the population — {spelling} — "
                        f"is still required and is not a renewal: both "
                        f"spellings are derivable from waivers.json alone, so "
                        f"neither one is the author saying this sentence is "
                        f"about these waivers."
                    ),
                    details=(
                        "The recorded population is a memory of WHICH, never "
                        "of WHEN. Renewing it while the reason sits untouched "
                        "leaves an old sentence authorising waivers it was "
                        "never written about. Rewriting the reason is what "
                        "says the author re-read it — and it is the one thing "
                        "in this document no script can derive."
                    ),
                ))

    pass_flag = not any(f.severity == "ERROR" for f in findings)

    result = {
        "program": "waiver_growth_check",
        "version": "1.0.0",
        "project": str(project),
        "baseline_path": str(base_path),
        "baseline_present": base_present,
        "summary": {
            "current_root_waivers": len(cur_roots),
            "baseline_root_waivers": len(base_roots),
            "current_waivers_by_key": {k: len(v) for k, v in
                                       _we.entries_by_key(cur_doc).items()},
            "net_growth": net_growth,
            # The population, reported as the three sets it actually is. The
            # verdict turns on `added_root_waivers`, not on `net_growth`: a
            # swap is +1/-1, net 0, and a complete change of population
            # (vibe-ic#948).
            "added_root_waivers": len(new_waivers),
            "removed_root_waivers": len(removed_waivers),
            "retained_root_waivers": len(retained_waivers),
            "population_grew": population_grew,
            "tolerance": args.tolerance,
            "growth_justified": growth_justified,
            # Disclosed separately from the verdict: "the rationale covers the
            # current population" and "no count was recorded at all" both make
            # `growth_justified` false and mean different things to fix.
            "growth_rationale_present": rationale_substantive,
            # The count spelling keeps reporting the integer it always did;
            # the population spelling reports the names. `None` still means
            # "no usable memory was recorded", in either spelling.
            _COVERS_FIELD: covers if covers is not None else cover_names,
            # Disclosed separately again: a document can be rejected for the
            # scope its rationale claims, for the reason having outlived the
            # waivers, or for neither, and those are different repairs.
            "growth_rationale_scope": scope,
            "growth_rationale_unrenewed": rationale_unrenewed,
            # What the gate could DECIDE about the reason, as opposed to what
            # it checked: "renewed" / "unrenewed" / "undecided" (no earlier
            # sentence on record) / "not_consulted" (nothing was added, or
            # there is no rationale to consult). `unrenewed: false` alone reads
            # as a clean bill of health for a question that was never
            # answerable (vibe-ic#948).
            "growth_rationale_renewal": renewal_state,
            "baseline_present": base_present,
            "new_waivers": sorted(new_waivers),
            "removed_waivers": sorted(removed_waivers),
            "pass": pass_flag,
        },
        "findings": [asdict(f) for f in findings],
    }

    if args.json is None:
        verdict = "PASS" if pass_flag else "FAIL"
        print(f"[{verdict}] waiver_growth_check")
        print(f"  current: {len(cur_roots)} root waivers")
        # "no baseline was ever frozen" and "the frozen baseline held zero"
        # print the same number, so the report says which one this was.
        if base_present:
            print(f"  baseline: {len(base_roots)} root waivers ({base_path})")
        else:
            print(f"  baseline: ABSENT — no file at {base_path}; compared "
                  f"against an empty document (0 root waivers)")
        # Added and closed are printed as separate numbers because they are
        # separate facts: a single net figure reports +1/-1 and 0/0 with the
        # same digit, and only one of those is a population that changed.
        print(f"  added since baseline: {len(new_waivers)} "
              f"(tolerance {args.tolerance}) | closed: {len(removed_waivers)} "
              f"| retained: {len(retained_waivers)} | net: {net_growth}")
        if new_waivers:
            print(f"  new this release: {sorted(new_waivers)}")
        if removed_waivers:
            print(f"  closed since baseline: {sorted(removed_waivers)}")
        print(f"  rationale renewal: {renewal_state.upper()}")
        for f in findings:
            print(f"  [{f.severity}] {f.category}: {f.message}")
    elif args.json == "-":
        print(json.dumps(result, indent=2))
    else:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"json: {args.json}")

    return 0 if pass_flag else 1


if __name__ == "__main__":
    sys.exit(main())
