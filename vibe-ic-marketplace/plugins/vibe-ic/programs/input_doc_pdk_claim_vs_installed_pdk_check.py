#!/usr/bin/env python3
"""input_doc_pdk_claim_vs_installed_pdk_check.py — decide a design-input
document's factual claims about the INSTALLED PDK against the installed PDK.

WHY THIS GATE EXISTS
====================
A design-input constraints document stated, as a fact, that its target PDK
ships no ngspice corner library, and mandated that every corner result be
labelled a hand-written LEVEL=1 standin in consequence. The PDK installed in
the pinned EDA image ships sectioned corner libraries for every device class,
and the deck resolver binds them successfully. The document was wrong, the
mandated disclosure would have propagated into every downstream corner artefact
as a statement contradicted by the very library the run bound against, and
NOTHING IN THE FLOW NOTICED.

The direction of that error is the reason it survived. It UNDERSTATES: it
labels real foundry corner sections as approximations. Every honesty gate in
this repo is pointed at the opposite direction — a result claiming more rigour
than it has — so a disclosure claiming LESS rigour than it has passes every one
of them. A false claim is a false claim whichever way it leans, and a mandated
disclosure is not inert: it is copied verbatim into artefacts that are then
read as the run's own account of itself.

WHAT THIS GATE DECIDES
======================
Exactly one claim shape, chosen because it is the shape the corpus actually
contains (measured, not assumed) and because it is decidable without judgement:

    an ABSENCE or EXCLUSIVITY assertion, about a named installed PDK, about a
    library artefact format that PDK actually ships

    "<PDK> has no <format> corner lib"          -> ABSENCE
    "<PDK> ships only the <name> corner lib"    -> EXCLUSIVITY

For each such line the gate resolves the named PDK to a directory in the
INSTALLED PDK ROOT, walks that directory, and answers from what is on disk.

WHAT THIS GATE EXPLICITLY DOES NOT DECIDE
=========================================
  * Anything about UPSTREAM PUBLICATION. A claim worded "no PUBLIC corner lib"
    is answered against the tree that is installed here, and the report says so
    in `decides` / `does_not_decide`. If a maintainer means "the foundry has
    not released one", the installed tree cannot settle that and the finding
    should be read as "the artefact the document says does not exist is on disk
    at these paths", which is the load-bearing part either way.
  * Whether a claim is a REQUIREMENT rather than an assertion. "must sign off
    at ss/tt/ff" names a corner vocabulary but asserts nothing about the PDK;
    it carries no absence/exclusivity quantifier and is never a candidate.
  * Any claim whose named PDK does not resolve to an installed directory. That
    is UNDECIDED, never agreement. A project naming a PDK that is not installed
    gets silence from this gate, and the silence is recorded as such.
  * Whether the extra members of an artefact class are CORNER VARIANTS of one
    library or unrelated files, in the general case. Where sibling structure is
    detectable (a shared stem prefix differing by one trailing token) the gate
    decides; where it is not, it reports UNDECIDED with the count and paths.
  * A denial about a DIRECTORY that holds no artefact of the claimed format.
    "no <dir> <format> lib" is a claim about a place; if that place is real and
    empty of that format, the files of that format sitting somewhere else in
    the tree answer a different question, and answering a different question in
    the affirmative is exactly this gate's own failure mode (vibe-ic#965).

AGREEMENT IS NOT THE DEFAULT
===========================
CORROBORATED is a decision, and every decision here has to be paid for. An
absence claim is corroborated only when all three of these are POSITIVE facts:

    the claimed FORMAT is present in this PDK at all, and
    every DIRECTORY the claim named holds files of that format, and
    those files were the ones read, and none of their names carries the denied
    word under any reading of that name.

"EVERY DIRECTORY" is a UNIVERSAL and is now enforced as one. It was written as
an intersection with the union of the named directories, so one productive
qualifier kept the gate answering while another named directory held nothing of
the format at all — and the answer was CORROBORATED, over a population that
included a directory the gate never read (vibe-ic#981). The reason string was
built from the same union, so it printed the barren directory's name inside its
own account of what it had examined.

CONTRADICTION is deliberately NOT universal, and the asymmetry is the logic
rather than a concession: a denial is FALSIFIED by one artefact in any one
named directory, and CONFIRMED only by having read all of them.

When any of them is missing the gate returns UNDECIDED with the reason, and
UNDECIDED is counted nowhere. This was the defect in the first version: a
denied-word lookup that MISSED fell straight through to CORROBORATED, so a
false claim about an artefact whose name hid the word inside an uppercase run
was reported as agreement — and agreement is the only route to rc 0.

NOTHING HERE IS A TABLE OF WHAT PDKs CONTAIN
============================================
Every fact the gate uses about a PDK is read from the installed tree at
runtime: which PDKs exist (directory listing), which artefact formats they ship
(file suffixes actually present), which directory qualifiers are meaningful
(directory component names actually present), which library variants exist
(file stems actually present), and which corner sections a library defines
(`.lib <name>` section-definition lines parsed out of the file). Change the
image and every answer changes. A hardcoded list of library names would have
been a second copy of the same unverified claim, which is the defect.

The claim-side vocabulary the gate does type out is natural-language
QUANTIFIERS ("no", "only", the CJK equivalents) — the grammar of assertion, not
the vocabulary of any PDK.

THE REPORT STATES THE ENVIRONMENT IT WAS TAKEN IN
=================================================
Every fact this gate uses is read from an INSTALLED tree, so the same commit
legitimately gets different answers in different environments — and until
vibe-ic#1491 the report did not say which environment produced the answer it
carried. Measured on one host, one commit, one tree: `--container <name>` gave
`[FAIL]` over 134 documents and 7 claims; the same command without it gave
`VACUOUS_PASS` over 0 documents. Both are correct readings of their own
environment and neither said so.

Worse, FOUR different environments printed one sentence,
`installed_pdk_root_unreadable`:

    the root does not exist                     -> nothing was read
    the root exists and holds no PDK            -> it WAS read, and was empty
    the root exists and cannot be opened        -> a real read error
    `docker exec` never ran at all              -> the backend, not the root

The fourth is the one that bites. `docker_backends` turned every failure —
container down, container misnamed, docker absent, deadline expired — into an
empty listing, and the report then said `backend_not_exercised: []`, i.e. it
asserted that the container backend HAD run. So `--container <name>` could be
wired at a call site, be completely inert, exit 2, and read as "this host has
no PDK". A repair that cannot be distinguished from doing nothing is not a
repair, and the same class one level down is what #965 and #981 were about.

So the root is PROBED for its state rather than inferred from an empty list,
each state gets its own reason token, `backend_not_exercised` is computed from
what actually ran, and `installed_pdk_root_state` plus the `[ENVIRONMENT]` line
appear on EVERY run, pass or not. A verdict states where it was taken.

A SECOND THING THE ENVIRONMENT MOVED, IN SILENCE: HOW MUCH WAS READ
-------------------------------------------------------------------
The walk of one installed PDK is bounded at `_MAX_PDK_FILES`. That bound is
about the machine, not about the design, and it decided verdicts. Measured on
one host, one commit, one claim, with the real bound and the SAME two artefacts
installed either way:

    PDK holds 20000 files, and the second `.lib` falls past the cut
                        -> CORROBORATED, `[PASS]`, rc 0
    the same PDK with the filler removed, both `.lib` files listed
                        -> UNDECIDED, `VACUOUS_PASS`, rc 2

The claim ("this PDK ships only the typical library") is FALSE both times. The
first run agreed with it, because agreement was quantified over a listing that
stopped, and `truncated_at` — recorded one line after the walk — was read by
nothing: not by a verdict branch, not by `_emit_human`, not by the
`[ENVIRONMENT]` line. rc 0 is this gate's ONLY route to a pass, so the cap
could manufacture the one verdict that means "I looked and it was true".

The asymmetry is the same one #981 settled for directories, applied to the
population itself. A CONTRADICTION stands under truncation: one artefact in the
part that WAS listed falsifies a denial, and the unread tail cannot rescue it.
An AGREEMENT does not: it is a universal over every artefact installed, and a
listing that stopped never covered that set. Agreement quantified over files
that were never listed is not agreement.

EXIT CODES / VERDICT
====================
The report always carries a machine-readable top-level `verdict`, and the exit
code is routed from the gate's own conclusion via `_vacuous_exit` (#515):

    verdict FAIL            rc 1   >=1 claim CONTRADICTED by the installed tree,
                                   OR a backend the caller NAMED could not be
                                   reached (`failure_kind: environment`)
    verdict PASS            rc 0   >=1 claim DECIDED, none contradicted
    verdict NOT_APPLICABLE  rc 2   nothing decidable was examined, + the
                                   `VACUOUS_PASS:` sentinel on stderr

The asymmetry in the FAIL row is deliberate and is the #1491 repair. A host
that simply has no installed PDK is NOT_APPLICABLE — that is a fact about the
host and making every PDK-less host red would be a verdict about the machine.
But a caller that passes `--container <name>` has ASSERTED an environment; when
that environment does not answer, the gate has not "found nothing applicable",
it has failed to run. `cvdp_gate` settled the identical question for an absent
`iverilog` (#1345): a check that COULD NOT RUN and a check that found nothing
wrong are not the same result, and the one that could not run must not be the
quieter of the two.

rc 0 from this gate means "at least one factual claim about the installed PDK
was settled BY EXAMINING THE ARTEFACTS IT IS ABOUT, and none of them was
false". It never means "the tree was quiet", and since #965 it no longer means
"one lookup came back empty for a reason nobody checked". A tree with no input
documents, no resolvable claims, no readable PDK root, or nothing but claims
the gate refused lands in the NOT_APPLICABLE tier, so neither an empty run nor
a run of pure ignorance can read as a substantive pass (vibe-ic#901).

Tightening corroboration moves runs DOWN the tiers, never up: a claim that used
to buy rc 0 by defaulting to agreement now either contradicts (rc 1) or is
refused, and a run whose every claim is refused is `all_claims_undecided`,
which is rc 2 with the `VACUOUS_PASS:` sentinel — not a pass.

Usage:
    python3 input_doc_pdk_claim_vs_installed_pdk_check.py <tree>
        [--pdks-root /foss/pdks] [--container <name>] [--json out.json|-]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _container_exec  # noqa: E402
import _vacuous_exit  # noqa: E402

GATE = "input_doc_pdk_claim_vs_installed_pdk"

DEFAULT_PDKS_ROOT = "/foss/pdks"

# ── the installed root's STATE, which an empty listing cannot express ───────
#
# `entries()` returns [] for a root that is absent, for a root that is present
# and empty, for a root that cannot be opened, and for a backend that never ran.
# Those are four different worlds and the gate used to print one sentence over
# all of them (vibe-ic#1491). A prober answers the question the listing cannot.
ROOT_READ = "read"
ROOT_ABSENT = "absent"
ROOT_NOT_A_DIRECTORY = "not_a_directory"
ROOT_UNREADABLE = "unreadable"
ROOT_BACKEND_UNAVAILABLE = "backend_unavailable"
#: No prober was supplied with an injected backend, so the reason an empty
#: listing came back is genuinely unknown. Recorded as unknown, never as empty.
ROOT_UNPROBED = "unprobed"

#: The machine-readable reason token each state contributes. Distinct by
#: construction: collapsing any two of them is the defect this table removes.
_ROOT_STATE_REASON = {
    ROOT_ABSENT: "installed_pdk_root_absent",
    ROOT_NOT_A_DIRECTORY: "installed_pdk_root_not_a_directory",
    ROOT_UNREADABLE: "installed_pdk_root_unreadable",
    ROOT_BACKEND_UNAVAILABLE: "container_backend_unavailable",
    ROOT_UNPROBED: "installed_pdk_root_state_unknown",
    ROOT_READ: "installed_pdk_root_holds_no_pdk",
}

# Container-side deadline for one backend round trip, in seconds. The landing
# harness bounds a whole pytest SESSION at 180s with `--timeout-method=thread`,
# and `ci_harness_timeout_ceiling_check` derives the per-call ceiling as
# `180 // 3 = 60`; `_container_exec` adds `CLIENT_GRACE_S` on top of this
# number for its client-side backstop, so the total stays under that ceiling.
# Measured 2026-08-14 on a live image: the whole gate answers in 3.0s over six
# installed PDKs, so this bound is a safety net rather than a budget.
_CONTAINER_DEADLINE_S = 40

# Document formats treated as design-input prose. A document-container format
# list, not a PDK vocabulary; overridable on the command line.
DEFAULT_DOC_SUFFIXES = (".md", ".txt")

# The path component that marks a design INPUT tree in this repo's layout.
INPUT_COMPONENT = "input"

# ── the one typed vocabulary here: natural-language ASSERTION GRAMMAR ───────
# These are quantifiers of English/CJK prose, not names of anything any PDK
# ships. A document that phrases absence some other way is simply not a
# candidate, and the report counts it nowhere — silence, not agreement.
_ABSENCE_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(no|not|none|never|lacks?|without|missing|"
    r"unavailable|absent)(?![A-Za-z0-9_])"
    r"|無|沒有|未提供|不隨附|欠缺|不提供")
_EXCLUSIVITY_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(only|sole|solely|just)(?![A-Za-z0-9_])"
    r"|僅|只有|唯一")

# `.lib <bare-identifier>` on a line of its own — a SPICE section DEFINITION.
# Shared with the deck-context resolver so the convention has one site; the
# local fallback keeps this gate runnable in a stripped install.
try:  # pragma: no cover - exercised implicitly by the full tree
    from analog_pdk_deck_context import _LIB_SECTION_RE as _SECTION_DEF_RE
except Exception:  # pragma: no cover
    _SECTION_DEF_RE = re.compile(r"(?im)^\s*\.lib\s+([A-Za-z_]\w*)\s*$")

# Infrastructure entries that sit alongside PDK directories under a pdks root
# and are not themselves PDKs. Shared with the availability resolver.
try:  # pragma: no cover
    from analog_pdk_availability import _NON_PDK_ENTRIES
except Exception:  # pragma: no cover
    _NON_PDK_ENTRIES = frozenset({"versions.txt", "ciel", "volare", ".", ".."})

# A subject shorter than this, after normalisation, is too weak to anchor a
# claim to a PDK without false matches against ordinary prose.
_MIN_SUBJECT_LEN = 4

# A file suffix must be at least this long, and a claim word may extend it by
# at most this many letters, before the word counts as naming that suffix.
_MIN_SUFFIX_LEN = 3
_SUFFIX_WORD_SLACK = 5

# How close, in characters, the word saying WHICH artefact is denied must sit
# to the format word it modifies. A whole clause away is a different sentence.
_HEAD_GAP_CHARS = 3

# How far either side of a quantifier its claim reaches, in characters before
# snapping outwards to whole tokens. A design-document line is often a table
# row holding several independent propositions; this is the neighbourhood one
# quantifier is taken to govern.
SCOPE_WIDTH_CHARS = 30

# Reading a whole PDK tree to answer one sentence is not worth an unbounded
# walk; these bound the work and every truncation is DISCLOSED in the report
# AND WITHHELD FROM AGREEMENT (a silent cap would be the same defect one layer
# down, and until vibe-ic#1491 that is exactly what it was: `truncated_at` was
# written onto the record and read by nothing).
_MAX_PDK_FILES = 20000
_MAX_SECTION_BYTES = 4_000_000


# ── tokenisation ───────────────────────────────────────────────────────────

_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]+")

# Where an UPPERCASE RUN abuts a lowercase run the word boundary is genuinely
# ambiguous without a lexicon: `ABChv` is `abc`+`hv` or `ab`+`chv`, and `ABCDef`
# is `abc`+`def`. Exactly one of the two readings is right in each case and no
# rule expressible here can tell which, so `lookup_tokens` returns BOTH rather
# than guessing. Guessing is what the shipped tokeniser did — it took the whole
# run plus its lowercase tail as one word, so the word hidden at the front of a
# compound stem could never be found, and a denial of that word came back
# CORROBORATED (vibe-ic#965).
_ACRONYM_WORD_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")   # ABCDef -> ABC|Def
_ACRONYM_TAIL_RE = re.compile(r"(?<=[A-Z][A-Z])(?=[a-z])")   # ABChv  -> ABC|hv

# A fragment shorter than this is not a word anyone denies; keeping them would
# let a single stray letter of an acronym match a claim.
_MIN_LOOKUP_FRAGMENT = 2


def tokens(text: str) -> List[str]:
    """Lowercase alphanumeric tokens of `text`, splitting camelCase humps.

    Used identically on claim prose and on installed file paths, so a claim
    word and a path word are comparable without either side owning a
    dictionary. camelCase is split only at a lower/digit -> upper boundary,
    which recovers the leading word of a compound file stem without
    shredding an all-caps run into fragments.

    This is the ORDERED, one-reading segmentation, and it stays that way:
    sibling-family detection reads token POSITIONS ("stems sharing every token
    but the last"), so it needs a single sequence, not a bag of alternatives.
    For "does this word occur in that name" use `lookup_tokens`.
    """
    split = _NON_ALNUM_RE.split(_CAMEL_SPLIT_RE.sub(" ", text))
    return [t.lower() for t in split if t]


def lookup_tokens(text: str) -> set:
    """Every word `text` can be READ as containing — the union of the readings.

    `tokens()` commits to one segmentation. This does not: wherever an
    uppercase run abuts a lowercase run, both boundaries are emitted, so a
    compound name yields the acronym AND the tail AND the one-word form. It is
    an unordered set used for one question only — is this claim word the name
    of that artefact — where a missed reading is a MISS, and a miss in this
    gate used to fall through to agreement.

    Purely structural: no name of anything any PDK ships appears here, and the
    rule is about letter case, so a differently-named tree gets the same
    treatment.
    """
    out = set()
    for run in re.finditer(r"[A-Za-z0-9]+", text):
        for piece in _CAMEL_SPLIT_RE.sub(" ", run.group(0)).split(" "):
            if not piece:
                continue
            out.add(piece.lower())
            for rx in (_ACRONYM_WORD_RE, _ACRONYM_TAIL_RE):
                for frag in rx.sub(" ", piece).split(" "):
                    if len(frag) >= _MIN_LOOKUP_FRAGMENT:
                        out.add(frag.lower())
    return out


def token_spans(text: str) -> List[Tuple[str, int, int]]:
    """`tokens(text)` with each token's character span in the ORIGINAL text.

    Spans are what make a proximity scope possible on prose that mixes Latin
    words with CJK, where the quantifier itself ("僅", "無") is a character the
    tokeniser drops. Character offsets survive that; token indices do not.
    """
    out: List[Tuple[str, int, int]] = []
    for m in re.finditer(r"[A-Za-z0-9]+", text):
        run, base = m.group(0), m.start()
        pos = 0
        for piece in _CAMEL_SPLIT_RE.sub(" ", run).split(" "):
            if not piece:
                continue
            start = run.index(piece, pos)
            out.append((piece.lower(), base + start, base + start + len(piece)))
            pos = start + len(piece)
    return out


def scope_around(text: str, start: int, end: int,
                 width: int) -> Tuple[str, List[str]]:
    """The claim's SCOPE: `width` characters either side of the quantifier,
    snapped outwards to whole tokens.

    A line of a design document is not one proposition. "PDK has no LVS deck →
    waive; structural CDL check optional" carries a denial and, a clause later,
    an unrelated noun that happens to name a file format the PDK ships. Reading
    the whole line as the denial's subject matter manufactured a contradiction
    out of an adjacent clause — measured, on a real document, on the first run
    of this gate. The quantifier governs its neighbourhood, so the
    neighbourhood is what gets read.
    """
    lo, hi = max(0, start - width), min(len(text), end + width)
    toks = []
    for tok, s, e in token_spans(text):
        if s < hi and e > lo:
            toks.append(tok)
            lo, hi = min(lo, s), max(hi, e)
    return text[lo:hi], toks


def normalise(text: str) -> str:
    """Lowercase, alphanumerics only — the form subject matching compares in,
    so `Alpha Node`, `alpha-node` and `alpha_node` are one string."""
    return _NON_ALNUM_RE.sub("", text).lower()


# ── installed-tree access (local FS or inside the EDA container) ───────────

class InstalledTree:
    """Read-only view of an INSTALLED PDK root, local or in a container.

    Two operations only — list the files under a directory, and read one file.
    Everything this gate knows about a PDK comes through here, so pointing it
    at a different image is the whole of "the answer changes when the image
    changes".
    """

    def __init__(self, root: str,
                 lister: Optional[Callable[[str], List[str]]] = None,
                 reader: Optional[Callable[[str], Optional[str]]] = None,
                 walker: Optional[Callable[[str], List[str]]] = None,
                 prober: Optional[Callable[[str], Tuple[str, str]]] = None):
        self.root = root.rstrip("/") or "/"
        self._lister = lister or _local_file_lister
        self._reader = reader or _local_reader
        self._walker = walker or _local_walker
        # The prober defaults ONLY alongside the default lister. An injected
        # backend that supplies no prober cannot have its silence explained by
        # probing the LOCAL disk — that would answer about a tree the backend
        # never touched — so it is recorded as unknown instead.
        self._prober = prober or (_local_prober if lister is None else None)
        self._cache: Dict[str, List[str]] = {}
        self._walk_cache: Dict[str, List[str]] = {}
        self._probe: Optional[Tuple[str, str]] = None

    def probe_root(self) -> Tuple[str, str]:
        """WHY the root listed the way it did: `(state, detail)`.

        Called only when the listing yielded no PDK, so the happy path costs
        nothing and a container run still answers in one bulk round trip.
        """
        if self._probe is None:
            if self._prober is None:
                self._probe = (ROOT_UNPROBED,
                               "this backend supplies no prober, so an empty "
                               "listing cannot be explained")
            else:
                self._probe = self._prober(self.root)
        return self._probe

    def entries(self, path: str) -> List[str]:
        """Immediate entry names of `path` (files and directories)."""
        if path not in self._cache:
            self._cache[path] = self._lister(path)
        return self._cache[path]

    def files_under(self, path: str) -> List[str]:
        """Absolute paths of every regular file under `path`, recursively.

        ONE bulk call per subtree, not one per directory: a container-backed
        walk that round-tripped per directory took minutes on a real PDK and a
        gate nobody can afford to run is a gate nobody runs.
        """
        if path not in self._walk_cache:
            self._walk_cache[path] = self._walker(path)[:_MAX_PDK_FILES]
        return self._walk_cache[path]

    def read(self, path: str) -> Optional[str]:
        return self._reader(path)


def _local_file_lister(path: str) -> List[str]:
    """`find <path>` style listing: absolute paths of files, one per call
    level. Returns entry names for a directory; [] when unreadable.

    `Path.is_dir()` DEREFERENCES, so a PDK installed as a link into a package
    store gets its trailing slash here and enters the population. The container
    backend had to be told to do the same (vibe-ic#964).
    """
    p = Path(path)
    if not p.is_dir():
        return []
    try:
        return sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir())
    except OSError:
        return []


def _local_prober(path: str) -> Tuple[str, str]:
    """Why the LOCAL listing of `path` came back the way it did.

    `_local_file_lister` returns [] for an absent root, a non-directory root, a
    root that cannot be opened, and a root that is genuinely empty. Only the
    last of those is a fact about the PDKs; the other three are facts about the
    machine, and reporting them as one was vibe-ic#1491.

    `os.listdir` rather than `Path.iterdir`, because `iterdir` is lazy and a
    permission error surfaces on the first `next()` — outside the `try` a
    careless caller would write.
    """
    p = Path(path)
    if not p.exists():
        return ROOT_ABSENT, "the path does not exist on this host"
    if not p.is_dir():
        return ROOT_NOT_A_DIRECTORY, "the path exists but is not a directory"
    try:
        os.listdir(path)
    except OSError as exc:
        return ROOT_UNREADABLE, str(exc)
    return ROOT_READ, ""


def _local_walker(path: str) -> List[str]:
    """Every regular file under `path`, absolute, bounded by _MAX_PDK_FILES.

    Symlinked subdirectories are FOLLOWED. An image that installs a PDK, or a
    part of one, as a link into a versioned package store is the ordinary case
    rather than an edge case, and a walk that stops at the link reports the PDK
    as empty — which this gate reads as "unreadable", i.e. silence, on a tree
    that is fully present (vibe-ic#964).

    Following links can cycle, so real paths are remembered and a directory
    already walked under another name is not walked again. That bound is
    structural; the _MAX_PDK_FILES bound only fires on files.
    """
    root = Path(path)
    if not root.is_dir():
        return []
    out: List[str] = []
    seen: set = set()
    for dirpath, dirnames, filenames in os.walk(path, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen:
            dirnames[:] = []
            continue
        seen.add(real)
        dirnames[:] = [d for d in dirnames
                       if os.path.realpath(os.path.join(dirpath, d)) not in seen]
        for fn in filenames:
            out.append(f"{dirpath.rstrip('/')}/{fn}")
            if len(out) >= _MAX_PDK_FILES:
                return sorted(out)
    return sorted(out)


def _local_reader(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as fh:
            return fh.read(_MAX_SECTION_BYTES).decode("utf-8", "replace")
    except OSError:
        return None


def _strip_banner(lines: Sequence[str]) -> List[str]:
    """Drop the container login banner the EDA image prints before real output.

    Same filtering the availability resolver applies; a banner line swallowed
    into a listing would look like a PDK directory named `[INFO]`.
    """
    out = []
    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("[INFO]") or s.startswith("[ERROR]"):
            continue
        out.append(s)
    return out


def _docker_exec(container: str, cmd: str) -> Tuple[bool, str, str]:
    """Run `cmd` in `container`. Returns `(reached, stdout, why_not)`.

    `reached` answers ONE question — did the container run this command at all
    — and it is a different question from whether the command found anything.
    The old shape returned `Optional[str]` and collapsed the two: a container
    that was down, misnamed, or absent produced `None`, `None` became `[]` one
    layer up, and `[]` was reported as an empty PDK root (vibe-ic#1491).

    Routed through `_container_exec.run_in_container`, the repo's sanctioned
    site for this call, so the deadline runs as the tool's PARENT INSIDE the
    container and can signal it. A client-side `timeout=` bounds only the local
    docker client and leaves the containerised tool running as an orphan, which
    is what `container_exec_deadline_check` exists to find; this call site used
    to be one of its findings.
    """
    try:
        cp = _container_exec.run_in_container(
            container, cmd, deadline_s=_CONTAINER_DEADLINE_S)
    except Exception as exc:  # docker absent, container wedged past the grace
        return False, "", f"{type(exc).__name__}: {exc}"
    # A killed run has no verdict. `describe_result` names the deadline and the
    # missing-`timeout` cases in the module that owns those exit codes.
    why = _container_exec.describe_result(cp, _CONTAINER_DEADLINE_S)
    if why:
        return False, "", why
    if cp.returncode != 0:
        detail = (cp.stderr or "").strip().splitlines()
        return False, "", (f"`docker exec {container}` exited "
                           f"{cp.returncode}"
                           + (f": {detail[0]}" if detail else ""))
    return True, cp.stdout or "", ""


def docker_prober(container: str) -> Callable[[str], Tuple[str, str]]:
    """Why the CONTAINER listing of a root came back the way it did.

    One round trip that exits 0 whenever the container is reachable, so a
    non-zero rc is unambiguously "the backend did not run" and never "the
    directory was empty". Without this, wiring `--container <name>` at a call
    site can be entirely inert and still report the container backend as
    exercised — the trap sitting directly under vibe-ic#1491's own first ask.
    """
    _ABSENT, _NOTDIR, _NOPERM, _OK = (
        "__ROOT_ABSENT__", "__ROOT_NOT_A_DIR__", "__ROOT_UNREADABLE__",
        "__ROOT_READ__")

    def prober(path: str) -> Tuple[str, str]:
        q = shlex.quote(path)
        reached, out, why = _docker_exec(
            container,
            f"if [ ! -e {q} ]; then echo {_ABSENT}; "
            f"elif [ ! -d {q} ]; then echo {_NOTDIR}; "
            f"elif ls -1pL {q} >/dev/null 2>&1; then echo {_OK}; "
            f"else echo {_NOPERM}; fi")
        if not reached:
            return ROOT_BACKEND_UNAVAILABLE, why
        # `_strip_banner` for the same reason every other consumer here uses
        # it: `bash -lc` prepends the image's login banner to stdout.
        lines = _strip_banner(out.splitlines())
        token = lines[-1] if lines else ""
        mapping = {_ABSENT: (ROOT_ABSENT,
                             "the path does not exist inside the container"),
                   _NOTDIR: (ROOT_NOT_A_DIRECTORY,
                             "the path exists inside the container but is not "
                             "a directory"),
                   _NOPERM: (ROOT_UNREADABLE,
                             "the path cannot be listed inside the container"),
                   _OK: (ROOT_READ, "")}
        if token not in mapping:
            # The container answered, and the answer is not one of ours. That
            # is a fact about the backend, not about the root.
            return ROOT_BACKEND_UNAVAILABLE, (
                "the container answered with no recognisable state token "
                f"({token[:80]!r})")
        return mapping[token]

    return prober


def docker_backends(container: str
                    ) -> Tuple[Callable[[str], List[str]],
                               Callable[[str], Optional[str]],
                               Callable[[str], List[str]]]:
    """Lister + reader + bulk walker that see the tree INSIDE the container."""

    def _run(cmd: str) -> Optional[str]:
        reached, out, _why = _docker_exec(container, cmd)
        return out if reached else None

    def lister(path: str) -> List[str]:
        # -L DEREFERENCES, and it is load-bearing: -p appends the trailing
        # slash to REAL directories only, `discover_installed_pdks` keeps an
        # entry only if it carries that slash, and an image that installs a PDK
        # as a link into a package store therefore had that PDK silently
        # outside the population — no decision and no refusal, on a PDK that is
        # installed (vibe-ic#964). The local lister already dereferenced.
        out = _run(f"ls -1pL {shlex.quote(path)} 2>/dev/null")
        if out is None:
            return []
        return sorted(_strip_banner(out.splitlines()))

    def reader(path: str) -> Optional[str]:
        out = _run(f"head -c {_MAX_SECTION_BYTES} {shlex.quote(path)} 2>/dev/null")
        return out

    def walker(path: str) -> List[str]:
        # -L for the same reason one level down: without it `find` will not
        # descend through a linked directory, and will not even open a start
        # path that is itself a link, so the PDK reads as empty.
        out = _run(f"find -L {shlex.quote(path)} -type f 2>/dev/null | "
                   f"head -n {_MAX_PDK_FILES}")
        if out is None:
            return []
        return sorted(_strip_banner(out.splitlines()))

    return lister, reader, walker


# ── installed PDK discovery ────────────────────────────────────────────────

def discover_installed_pdks(tree: InstalledTree) -> List[str]:
    """Names of the PDK directories the installed root actually contains.

    This is the gate's entire notion of "which PDKs exist". There is no list.
    """
    out = []
    for name in tree.entries(tree.root):
        if not name.endswith("/"):
            continue
        bare = name[:-1]
        if bare in _NON_PDK_ENTRIES or bare.startswith("."):
            continue
        if len(normalise(bare)) < _MIN_SUBJECT_LEN:
            continue
        out.append(bare)
    return sorted(out)


def resolve_subject(line: str, installed: Sequence[str]) -> Tuple[Optional[str], str]:
    """Which installed PDK, if any, this line is talking about.

    Normalised containment — `Alpha Node` finds `alpha-node` — with the LONGEST
    match winning, so a family name that is a prefix of another cannot capture
    a claim about the longer one. A tie between two equally long names is
    genuinely ambiguous and is refused rather than guessed.
    """
    hay = normalise(line)
    matched = [p for p in installed if normalise(p) in hay]
    if not matched:
        return None, "no installed PDK name appears in the line"
    longest = max(len(normalise(p)) for p in matched)
    best = [p for p in matched if len(normalise(p)) == longest]
    if len(best) > 1:
        return None, f"ambiguous subject: {', '.join(sorted(best))}"
    return best[0], ""


# ── claim extraction ───────────────────────────────────────────────────────

class Claim:
    __slots__ = ("doc", "line_no", "text", "subject", "quantifier", "reason",
                 "scope", "scope_tokens")

    def __init__(self, doc: str, line_no: int, text: str,
                 subject: Optional[str], quantifier: Optional[str],
                 reason: str = "", scope: str = "",
                 scope_tokens: Optional[Sequence[str]] = None):
        self.doc = doc
        self.line_no = line_no
        self.text = text
        self.subject = subject
        self.quantifier = quantifier
        self.reason = reason
        self.scope = scope or text
        self.scope_tokens = list(scope_tokens or [])

    def as_dict(self) -> Dict[str, Any]:
        return {"document": self.doc, "line": self.line_no,
                "claim": self.text, "claim_scope": self.scope,
                "subject_pdk": self.subject,
                "quantifier": self.quantifier}


def find_input_documents(tree_root: Path,
                         suffixes: Sequence[str] = DEFAULT_DOC_SUFFIXES
                         ) -> List[Path]:
    """Design-input prose documents under `tree_root`.

    A document is design INPUT when a component of its path is `input/` — the
    repo-wide convention for "what the design was given", as distinct from what
    a run produced. Nothing under a produced-artefact path is a claim this gate
    adjudicates, because a produced artefact is the flow's own output and a
    different gate's business.
    """
    if not tree_root.is_dir():
        return []
    sfx = tuple(s.lower() for s in suffixes)
    out = []
    for p in sorted(tree_root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in sfx:
            continue
        if INPUT_COMPONENT not in p.parts:
            continue
        out.append(p)
    return out


def extract_claims(doc_path: Path, rel: str,
                   installed: Sequence[str]) -> List[Claim]:
    """Candidate claims in one document.

    A candidate is a quantifier occurrence whose SCOPE — its token
    neighbourhood, not its whole line — also names an installed PDK. Requiring
    the subject inside the scope is what stops a PDK mentioned in one clause
    from being made the subject of a denial in another.

    A scope carrying both an absence and an exclusivity quantifier is kept but
    marked ambiguous, because deciding which one governs is reading intent, and
    this gate does not read intent.
    """
    try:
        text = doc_path.read_text(errors="replace")
    except OSError:
        return []
    claims = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        seen_scopes = set()
        for quant, rx in (("ABSENCE", _ABSENCE_RE),
                          ("EXCLUSIVITY", _EXCLUSIVITY_RE)):
            for m in rx.finditer(line):
                scope, stoks = scope_around(line, m.start(), m.end(),
                                            SCOPE_WIDTH_CHARS)
                if scope in seen_scopes:
                    continue
                subject, _why = resolve_subject(scope, installed)
                if subject is None:
                    continue
                seen_scopes.add(scope)
                other = (_EXCLUSIVITY_RE if quant == "ABSENCE"
                         else _ABSENCE_RE)
                if other.search(scope):
                    q, reason = None, ("claim scope carries both an absence "
                                       "and an exclusivity quantifier")
                else:
                    q, reason = quant, ""
                claims.append(Claim(rel, i, line[:400], subject, q, reason,
                                    scope=scope, scope_tokens=stoks))
    return claims


# ── adjudication against the installed tree ────────────────────────────────

def head_modifiers(scope: str, fmt: Sequence[str],
                   subject_tokens: Sequence[str]) -> List[str]:
    """The word(s) the claim uses to say WHICH artefact of a format it denies.

    "no ngspice corner lib" denies the CORNER libs, not every `.lib` in the
    tree. The distinguishing word is the one immediately in front of the format
    word, and "immediately" is enforced in characters as well as tokens: on a
    real bilingual document the nearest Latin token to `GDS` was six words and
    a clause away, and treating it as the modifier would have made a true
    statement about a staged macro look like a claim about the PDK.

    A quantifier is never a modifier ("ships no lib" denies nothing in
    particular), and neither is the subject's own name.
    """
    drop = {t.lower() for t in subject_tokens}
    spans = token_spans(scope)
    out: List[str] = []
    for idx, (tok, start, _end) in enumerate(spans):
        if not any(tok == s or tok.startswith(s) for s in fmt):
            continue
        if idx == 0:
            continue
        prev, _pstart, pend = spans[idx - 1]
        if start - pend > _HEAD_GAP_CHARS:
            continue
        if prev in drop or any(prev == s or prev.startswith(s) for s in fmt):
            continue
        if _ABSENCE_RE.fullmatch(prev) or _EXCLUSIVITY_RE.fullmatch(prev):
            continue
        out.append(prev)
    return out


def _stem_tokens(path: str) -> List[str]:
    return tokens(Path(path).stem)


def _suffix(path: str) -> str:
    return Path(path).suffix.lstrip(".").lower()


def _sibling_family(paths: Sequence[str]) -> Optional[Tuple[str, Dict[str, str]]]:
    """Detect a variant family: stems sharing every token but the last.

    `<name>_typical` / `<name>_slow` / `<name>_fast` is a family whose members
    are variants of one library. The shared prefix is the library, the trailing
    token is the variant. Purely structural — the gate never has to know that
    `slow` names a corner, only that it is the position in which these files
    differ. Returns (prefix, {variant_token: path}) for the LARGEST family, or
    None when no two stems share a prefix in that shape.
    """
    fams: Dict[str, Dict[str, str]] = {}
    for p in paths:
        tk = _stem_tokens(p)
        if len(tk) < 2:
            continue
        prefix = " ".join(tk[:-1])
        fams.setdefault(prefix, {})[tk[-1]] = p
    best = None
    for prefix, members in fams.items():
        if len(members) < 2:
            continue
        if best is None or len(members) > len(best[1]):
            best = (prefix, members)
    return best


def _sections_of(tree: InstalledTree, paths: Sequence[str],
                 limit: int = 12) -> Dict[str, List[str]]:
    """Corner-section vocabulary each library actually defines, scraped now.

    The section names are READ, never assumed. A gate that shipped a list of
    section names would be promising that no PDK will ever name one
    differently, which is the promise this whole issue is about.
    """
    out: Dict[str, List[str]] = {}
    for p in list(paths)[:limit]:
        body = tree.read(p)
        if not body:
            continue
        names = sorted(set(_SECTION_DEF_RE.findall(body)))
        if names:
            out[p] = names
    return out


def _refuse_corroboration_over_a_barren_directory(
        rec: Dict[str, Any]) -> Dict[str, Any]:
    """Withhold agreement that was quantified over a directory nobody read.

    The docstring at the top of this file promises a UNIVERSAL — "every
    DIRECTORY the claim named holds files of that format" — and the narrowing
    that feeds the verdict is an INTERSECTION with the union of those
    directories. One productive qualifier therefore kept the gate answering
    while another named directory held nothing at all, and the answer it gave
    was CORROBORATED, which is the only route to rc 0 (vibe-ic#981).

    This is the ONE place that decision is made, and it is made LAST, on the
    finished record, for two reasons. Applying the universal earlier would
    refuse before the tree had been asked, which would throw away a
    CONTRADICTION standing on a productive sibling directory — measured on the
    real corpus, not hypothesised. And placing it after the verdict means every
    route to CORROBORATED passes through it, including ones added later, rather
    than each route having to remember.

    UNDECIDED is counted nowhere, so a run whose only claim lands here is
    `all_claims_undecided` — rc 2 with the `VACUOUS_PASS:` sentinel, never a
    pass. The withheld reason is KEPT, under its own key: a reader has to be
    able to see what the gate would have said and why it did not say it.
    """
    barren = rec.get("directory_qualifiers_without_that_format") or []
    if rec.get("verdict") != "CORROBORATED" or not barren:
        return rec
    named = rec.get("directory_qualifiers") or []
    fmt = "/".join(rec.get("artefact_format") or [])
    rec["verdict"] = "UNDECIDED"
    rec["corroboration_withheld"] = rec.get("reason", "")
    rec["reason"] = (
        f"the claim names {len(named)} director(y/ies) — {', '.join(named)} — "
        f"and agreement with it would be a statement about all of them; "
        f"{', '.join(barren)} exist(s) in the installed PDK but holds no "
        f"artefact of format {fmt}, so the claim was never checked there. "
        "Agreement quantified over a directory that was never read is not "
        "agreement")
    return rec


def _refuse_agreement_over_a_truncated_population(
        rec: Dict[str, Any]) -> Dict[str, Any]:
    """Withhold agreement that was quantified over a listing that stopped.

    `files_under` caps one PDK's walk at `_MAX_PDK_FILES`, and the cap is a
    fact about the machine's patience, not about the design. Until vibe-ic#1491
    `truncated_at` was written onto the record one line after the walk and read
    by NOTHING, so every route to CORROBORATED — the gate's only route to rc 0
    — could run over a population it had not finished listing. Measured with
    the real bound: an exclusivity claim that is FALSE against the installed
    tree returned `[PASS]` when 20000 unrelated files pushed the falsifying
    artefact past the cut, and UNDECIDED when the same two artefacts were
    listed in full.

    CONTRADICTED is deliberately left alone. A denial is falsified by ONE
    artefact in the part that WAS listed, and nothing in the unread tail can
    put that artefact back; an agreement is a universal over the whole install,
    and a listing that stopped never covered it. That is the #981 asymmetry —
    stated there for the directories a claim names — applied to the population
    the claim is answered over.

    Applied LAST, on the finished record, for the reason the barren-directory
    refusal is: every route to CORROBORATED passes through here, including
    routes added later, rather than each route having to remember. The withheld
    reason is KEPT under `corroboration_withheld`, so a reader can see what the
    gate would have said and why it did not say it. UNDECIDED is counted
    nowhere, so a run whose only claim lands here is `all_claims_undecided` —
    rc 2 with the `VACUOUS_PASS:` sentinel, never a pass.
    """
    bound = rec.get("truncated_at")
    if rec.get("verdict") != "CORROBORATED" or not bound:
        return rec
    rec["verdict"] = "UNDECIDED"
    rec["corroboration_withheld"] = rec.get("reason", "")
    rec["reason"] = (
        f"the walk of '{rec.get('subject_pdk')}' stopped at the {bound}-file "
        "bound, so the installed artefacts were never fully listed; agreeing "
        "with this claim would be a statement about every artefact installed, "
        "including the ones past the cut. A contradiction found in the part "
        "that WAS listed would still stand — agreement quantified over files "
        "that were never listed is not agreement")
    return rec


def adjudicate(claim: Claim, tree: InstalledTree) -> Dict[str, Any]:
    """Settle one claim against the installed tree, or refuse to.

    Three steps, deliberately separate. `_decide_against_the_tree` reads the
    tree and answers; `_refuse_corroboration_over_a_barren_directory` then
    withholds an agreement whose NAMED DIRECTORIES the read did not cover; and
    `_refuse_agreement_over_a_truncated_population` withholds one whose FILE
    LISTING stopped at the bound. Splitting them is what lets a CONTRADICTION
    survive a narrowing, and a cap, that a CORROBORATION may not.
    """
    return _refuse_agreement_over_a_truncated_population(
        _refuse_corroboration_over_a_barren_directory(
            _decide_against_the_tree(claim, tree)))


def _decide_against_the_tree(claim: Claim, tree: InstalledTree) -> Dict[str, Any]:
    """Answer one claim from what is on disk, or record why it cannot be.

    Every narrowing step below is driven by the intersection of the CLAIM's own
    words with what the installed tree actually contains — file suffixes,
    directory component names, file stems. Nothing is matched against a
    vocabulary this file carries.
    """
    rec = claim.as_dict()
    rec["verdict"] = "UNDECIDED"
    rec["evidence"] = []
    rec["installed_pdk_path"] = f"{tree.root}/{claim.subject}"

    if claim.quantifier is None:
        rec["reason"] = claim.reason or "quantifier not determinable"
        return rec

    pdk_dir = f"{tree.root}/{claim.subject}"
    files = tree.files_under(pdk_dir)
    if not files:
        rec["reason"] = "installed PDK directory is empty or unreadable"
        return rec
    if len(files) >= _MAX_PDK_FILES:
        rec["truncated_at"] = _MAX_PDK_FILES

    claim_tokens = set(claim.scope_tokens or tokens(claim.scope))
    # The subject's OWN words are not evidence about the subject. Both the
    # split form and the joined form are removed, so a directory named
    # `<family>` cannot be mistaken for a qualifier the claim supplied.
    subject_tokens = set(tokens(claim.subject)) | {normalise(claim.subject)}
    claim_tokens = {t for t in claim_tokens
                    if t not in subject_tokens
                    and normalise(t) != normalise(claim.subject)}

    # (1) artefact FORMAT: a claim token naming a file suffix actually present.
    # Prose spells a suffix out — "corner library", "corner liberty" — where
    # the tree writes `.lib`, so a claim token that EXTENDS a present suffix
    # counts as naming it. The suffix comes from the tree, never from a synonym
    # table here; the bounds (>=3 chars, <=_SUFFIX_WORD_SLACK extra letters)
    # keep a one- or two-letter suffix from matching half the dictionary.
    present_suffixes = {_suffix(f) for f in files if _suffix(f)}
    fmt = {s for s in present_suffixes
           if len(s) >= _MIN_SUFFIX_LEN
           and any(t == s or (t.startswith(s)
                              and len(t) - len(s) <= _SUFFIX_WORD_SLACK)
                   for t in claim_tokens)}
    if not fmt:
        rec["reason"] = ("no artefact format named in the claim corresponds to "
                         "a file suffix present in the installed PDK "
                         f"({len(files)} files scanned)")
        return rec
    rec["artefact_format"] = sorted(fmt)
    candidates = [f for f in files if _suffix(f) in fmt]

    # (2) directory QUALIFIER: a claim token that is a real directory component
    # of the PDK — of the WHOLE PDK, not merely of the files that already carry
    # the claimed format. Reading the qualifier off the already-narrowed set
    # makes it impossible to notice the one case that matters: the claim names
    # a directory that exists and holds NOTHING of that format, so the files
    # answering the claim came from somewhere else entirely (vibe-ic#965).
    #
    # Components are taken RELATIVE to the PDK directory, so the mount path's
    # own words cannot be mistaken for a qualifier the claim supplied.
    prefix = pdk_dir.rstrip("/") + "/"

    def _rel_components(path: str) -> set:
        rel = path[len(prefix):] if path.startswith(prefix) else path
        return {c.lower() for c in Path(rel).parent.parts
                if c not in ("/", ".", "")}

    pdk_components: set = set()
    for f in files:
        pdk_components |= _rel_components(f)
    dir_quals = (claim_tokens & pdk_components) - subject_tokens - fmt

    # The population the claim is answered over is the UNION of the directories
    # it named; the population a CORROBORATION quantifies over is EVERY one of
    # them. Those are different sets and they need separate bookkeeping,
    # because the union alone cannot tell you which member contributed nothing
    # (vibe-ic#981).
    #
    # The asymmetry is not a compromise, it is the logic. A denial is falsified
    # by ONE artefact in ANY named directory — "no corner lib under a/ or b/"
    # is false the moment a corner lib turns up under b/, and what a/ holds
    # cannot rescue it. But a denial is CONFIRMED only by having looked in all
    # of them, so a directory that contributed zero files of the format leaves
    # the universal unverified. Measured on the real corpus: the false claim at
    # a project's L5 analog spec names two directories, one of which holds no
    # file of the claimed format at all — applying the universal before the
    # verdict would have thrown that true CONTRADICTION away.
    per_dir: Dict[str, List[str]] = {}
    barren: List[str] = []
    if dir_quals:
        rec["directory_qualifiers"] = sorted(dir_quals)
        for qual in sorted(dir_quals):
            per_dir[qual] = [f for f in candidates if qual in _rel_components(f)]
            if not per_dir[qual]:
                barren.append(qual)
        rec["examined_by_directory"] = {q: len(v) for q, v in per_dir.items()}
        if barren:
            # Read by `_refuse_corroboration_over_a_barren_directory` after the
            # verdict is known, so a CONTRADICTION found in a productive
            # sibling directory still stands.
            rec["directory_qualifiers_without_that_format"] = sorted(barren)
        narrowed = [f for f in candidates if _rel_components(f) & dir_quals]
        if not narrowed:
            # The claim is about a place; that place is real and empty of this
            # format. Answering it from the files of that format found in some
            # OTHER directory is answering a different question, and answering
            # a different question in the affirmative is the failure this gate
            # exists to catch, one level up.
            rec["reason"] = (
                "the claim narrows to directory "
                f"'{'/'.join(sorted(dir_quals))}', which exists in the "
                f"installed PDK but holds no artefact of format "
                f"{'/'.join(sorted(fmt))}; the {len(candidates)} file(s) of "
                "that format found elsewhere in the tree cannot settle a claim "
                "about that directory")
            rec["evidence_count"] = len(candidates)
            return rec
        candidates = narrowed
    if not candidates:
        rec["reason"] = "no installed file matches the claim's artefact format"
        return rec

    # (3) stem QUALIFIER: a claim token occurring in at least one candidate stem
    stem_vocab = set()
    for f in candidates:
        stem_vocab.update(_stem_tokens(f))
    stem_quals = (claim_tokens & stem_vocab) - subject_tokens - fmt - dir_quals

    if claim.quantifier == "ABSENCE":
        # A denial needs a DISCRIMINATOR before the tree can answer it: the
        # word the claim puts in front of the format, saying WHICH artefacts of
        # that format it denies. Without one the claim denies "some file of
        # format X" and no listing can settle that — the gate's first run
        # answered such a claim by matching every file of the format and
        # reported an unrelated file as the contradiction. Refusing is the only
        # honest answer, recorded as UNDECIDED, never as agreement.
        heads = head_modifiers(claim.scope, sorted(fmt), sorted(subject_tokens))
        if not heads:
            rec["reason"] = (
                "the claim names an artefact format but no adjacent word "
                "saying which artefacts of that format it denies; the "
                "installed tree cannot settle a denial it cannot localise")
            rec["evidence_count"] = len(candidates)
            return rec
        rec["denied_artefact"] = sorted(set(heads))
        head_set = set(heads)
        # `lookup_tokens`, not `tokens`: a name that hides the denied word
        # inside an uppercase run used to read as a name that does not contain
        # it, the lookup missed, and the miss fell through to agreement. The
        # tree side is the side that is enriched — the claim's own word is
        # taken as written, so widening cannot invent a denial the document
        # never made.
        matched = [f for f in candidates if lookup_tokens(Path(f).stem) & head_set]
        if matched:
            rec["verdict"] = "CONTRADICTED"
            rec["reason"] = (
                f"the installed PDK ships {len(matched)} artefact(s) the claim "
                f"says it does not")
            rec["evidence"] = matched[:40]
            rec["evidence_count"] = len(matched)
            secs = _sections_of(tree, matched)
            if secs:
                rec["sections_discovered"] = secs
        else:
            # Corroboration here is EARNED, not defaulted: the format is
            # present in this PDK, every directory the claim named holds files
            # of that format, those are the files that were read, and the
            # denied word is in none of their names under any reading of them.
            # Each of those three is a positive fact; when any of them is
            # missing the branches above have already returned UNDECIDED.
            # The reason states the population it actually read, PER DIRECTORY.
            # Naming the directories and then printing one total let a
            # corroboration say "the claim holds over the 1 file(s) of that
            # format under a/b" when b contributed the file and a contributed
            # nothing — a sentence whose subject is a set the gate never
            # examined (vibe-ic#981). A per-directory count cannot say that:
            # the zero is written down where the reader is.
            where = (" under " + ", ".join(f"{q} ({len(per_dir[q])})"
                                           for q in sorted(dir_quals))
                     if dir_quals else " anywhere in the installed PDK")
            rec["verdict"] = "CORROBORATED"
            rec["reason"] = (
                f"no installed artefact of format {'/'.join(sorted(fmt))} is "
                f"named {'/'.join(sorted(head_set))}; the claim holds over the "
                f"{len(candidates)} file(s) of that format{where}")
            rec["evidence_count"] = 0
            rec["examined_count"] = len(candidates)
        return rec

    # EXCLUSIVITY
    if len(candidates) == 1:
        only = candidates[0]
        if set(_stem_tokens(only)) & claim_tokens:
            rec["verdict"] = "CORROBORATED"
            rec["reason"] = ("the installed PDK ships exactly one artefact of "
                             "the claimed format, and the claim names it")
            rec["evidence"] = [only]
            rec["evidence_count"] = 1
        else:
            rec["reason"] = ("the installed PDK ships exactly one artefact of "
                             "the claimed format but the claim does not name "
                             "it; the claim may be about something else")
            rec["evidence"] = [only]
        return rec

    fam = _sibling_family(candidates)
    if fam is None:
        rec["reason"] = (
            f"the installed PDK ships {len(candidates)} artefacts of the "
            "claimed format with no detectable variant-family structure; "
            "deciding whether the extras are variants of one library needs a "
            "corner-role vocabulary this gate deliberately does not carry")
        rec["evidence"] = candidates[:40]
        rec["evidence_count"] = len(candidates)
        return rec

    prefix, members = fam
    unnamed = {v: p for v, p in members.items() if v not in claim_tokens}
    if unnamed:
        rec["verdict"] = "CONTRADICTED"
        rec["reason"] = (
            f"the installed PDK ships {len(members)} variants of "
            f"'{prefix}' and the claim admits only the ones it names; "
            f"unnamed: {', '.join(sorted(unnamed))}")
        rec["evidence"] = [unnamed[v] for v in sorted(unnamed)][:40]
        rec["evidence_count"] = len(unnamed)
        secs = _sections_of(tree, list(members.values()))
        if secs:
            rec["sections_discovered"] = secs
    else:
        rec["verdict"] = "CORROBORATED"
        rec["reason"] = (f"every installed variant of '{prefix}' is named in "
                         "the claim")
        rec["evidence"] = sorted(members.values())[:40]
        rec["evidence_count"] = len(members)
    return rec


# ── report ─────────────────────────────────────────────────────────────────

def run(tree_root: Path, pdks_root: str,
        container: Optional[str] = None,
        doc_suffixes: Sequence[str] = DEFAULT_DOC_SUFFIXES,
        lister: Optional[Callable[[str], List[str]]] = None,
        reader: Optional[Callable[[str], Optional[str]]] = None,
        walker: Optional[Callable[[str], List[str]]] = None,
        prober: Optional[Callable[[str], Tuple[str, str]]] = None,
        ) -> Dict[str, Any]:
    """Adjudicate every decidable claim in `tree_root` against `pdks_root`."""
    if container and lister is None and reader is None and walker is None:
        lister, reader, walker = docker_backends(container)
        if prober is None:
            prober = docker_prober(container)
    tree = InstalledTree(pdks_root, lister=lister, reader=reader,
                         walker=walker, prober=prober)

    report: Dict[str, Any] = {
        "gate": GATE,
        "installed_pdk_root": pdks_root,
        "installed_pdk_source": f"container:{container}" if container else "local",
        "tree": str(tree_root),
        "decides": (
            "absence / exclusivity assertions, in design-input documents, "
            "about library artefacts of a PDK that is installed here"),
        "does_not_decide": [
            "upstream publication status of any artefact (only what is "
            "installed here)",
            "claims about a PDK that is not installed in this root",
            "requirements and targets, which assert nothing about the PDK",
            "whether extra artefacts are corner variants when no sibling "
            "family structure is detectable",
            "a denial about a directory that exists but holds no artefact of "
            "the claimed format; the format's files elsewhere in the tree "
            "answer a different question",
            "a claim naming SEVERAL directories where any one of them holds "
            "no artefact of the claimed format; agreement would be a "
            "statement about a directory that was never read, so it is "
            "withheld — a contradiction found in the others still stands",
            "a claim whose PDK holds more files than the walk's bound; "
            "agreement would be a statement about artefacts past the cut, so "
            "it is withheld — a contradiction found in the listed part still "
            "stands",
        ],
    }

    installed = discover_installed_pdks(tree)
    report["installed_pdks"] = installed
    if not installed:
        # NAME THE BACKEND THAT CAME BACK EMPTY (vibe-ic#981), and then say WHY
        # it came back empty (vibe-ic#1491). The wired call site passes no
        # `--container`, so on a host with no local PDK tree this is the branch
        # that always fires and the container backend — `docker_backends`, and
        # with it the `-L` dereference that #964 exists for — is not merely
        # undecided, it is NOT EXECUTED AT ALL.
        #
        # #981 disclosed the un-run half. It did not fix the sentence: an
        # absent root, a root holding no PDK, an unopenable root and a backend
        # that never ran all printed `installed_pdk_root_unreadable`, and the
        # fourth also printed `backend_not_exercised: []` — asserting that the
        # container backend HAD run when `docker exec` had never returned. The
        # root is PROBED now, and the disclosure is computed from what actually
        # ran rather than from which flags were passed.
        state, detail = tree.probe_root()
        report["installed_pdk_root_state"] = state
        if detail:
            report["installed_pdk_root_probe"] = detail
        unreached = state == ROOT_BACKEND_UNAVAILABLE
        # "Exercised" is a measurement, not a restatement of the argv. A
        # `--container` that never reached its container leaves the container
        # backend in this list, so wiring the flag can no longer be inert and
        # look exercised at the same time.
        report["backend_not_exercised"] = (
            ["container"] if (unreached or not container) else [])
        token = _ROOT_STATE_REASON.get(state, "installed_pdk_root_unreadable")
        note = ""
        if unreached:
            note = ("; the container backend was NAMED but never ran, so "
                    "nothing about the installed PDK was learned by this run")
        elif not container:
            note = ("; the container backend was NOT exercised by this run — "
                    "pass --container <name> to read the PDK inside the EDA "
                    "image")
        report["reason"] = (
            f"{token} (backend: {report['installed_pdk_source']}"
            + (f"; {detail}" if detail else "")
            + note + ")")
        if unreached:
            # A caller that passes `--container <name>` has ASSERTED an
            # environment. When that environment does not answer, the gate has
            # not "found nothing applicable" — it has failed to run, and the
            # quieter of the two verdicts is the wrong one (#1345). A host that
            # merely has no installed PDK keeps the NOT_APPLICABLE tier below.
            report["verdict"] = "FAIL"
            report["failure_kind"] = "environment"
        else:
            report["verdict"] = "NOT_APPLICABLE"
        report["documents_scanned"] = 0
        report["claims"] = []
        report["counts"] = {"contradicted": 0, "corroborated": 0,
                            "undecided": 0}
        return report
    # A listing that yielded PDK names IS a successful read of the root, so the
    # happy path records the state without paying for a second round trip. Both
    # keys are recorded on EVERY route through this function, not only the
    # empty one: the whole point of #1491 is that a verdict which does not say
    # where it was taken cannot be compared with another verdict at the same
    # commit.
    report["installed_pdk_root_state"] = ROOT_READ
    report["backend_not_exercised"] = [] if container else ["container"]

    docs = find_input_documents(tree_root, doc_suffixes)
    report["documents_scanned"] = len(docs)
    if not docs:
        report["verdict"] = "NOT_APPLICABLE"
        report["reason"] = "no_input_documents"
        report["claims"] = []
        report["counts"] = {"contradicted": 0, "corroborated": 0,
                            "undecided": 0}
        return report

    claims: List[Claim] = []
    for d in docs:
        try:
            rel = str(d.relative_to(tree_root))
        except ValueError:  # pragma: no cover - rglob keeps these relative
            rel = str(d)
        claims.extend(extract_claims(d, rel, installed))

    results = [adjudicate(c, tree) for c in claims]
    report["claims"] = results
    # HOW MUCH WAS READ is part of the environment a verdict was taken in
    # (vibe-ic#1491), so it is disclosed beside the root and the backend rather
    # than only inside a per-claim record nobody prints. Named per PDK, because
    # the bound is per PDK: one oversized install does not make the answer
    # about the others partial.
    truncated = sorted({r.get("subject_pdk") for r in results
                        if r.get("truncated_at") and r.get("subject_pdk")})
    if truncated:
        report["population_truncated"] = truncated
        report["population_truncated_at"] = _MAX_PDK_FILES
    counts = {
        "contradicted": sum(1 for r in results if r["verdict"] == "CONTRADICTED"),
        "corroborated": sum(1 for r in results if r["verdict"] == "CORROBORATED"),
        "undecided": sum(1 for r in results if r["verdict"] == "UNDECIDED"),
    }
    report["counts"] = counts

    if counts["contradicted"]:
        report["verdict"] = "FAIL"
        report["reason"] = (f"{counts['contradicted']} design-input claim(s) "
                            "contradicted by the installed PDK")
    elif counts["corroborated"]:
        report["verdict"] = "PASS"
        report["reason"] = (f"{counts['corroborated']} claim(s) decided, none "
                            "contradicted")
    elif claims:
        report["verdict"] = "NOT_APPLICABLE"
        report["reason"] = "all_claims_undecided"
    else:
        report["verdict"] = "NOT_APPLICABLE"
        report["reason"] = "no_decidable_pdk_claim"
    return report


def _environment_line(report: Dict[str, Any]) -> str:
    """The one line that makes two verdicts at the same commit comparable.

    vibe-ic#1491 measured `[FAIL]` over 134 documents and `VACUOUS_PASS` over 0
    from the same tree on the same host, minutes apart, with nothing in either
    output naming what differed. Printed on EVERY run — a disclosure that
    appears only when the news is bad teaches a reader to read its absence as
    good news.
    """
    bits = [f"root={report.get('installed_pdk_root')}",
            f"backend={report.get('installed_pdk_source')}",
            f"state={report.get('installed_pdk_root_state', 'unrecorded')}",
            f"installed_pdks={len(report.get('installed_pdks') or [])}"]
    unrun = report.get("backend_not_exercised") or []
    if unrun:
        bits.append(f"not_exercised={','.join(unrun)}")
    cut = report.get("population_truncated") or []
    if cut:
        bits.append(f"truncated_at_{report.get('population_truncated_at')}"
                    f"={','.join(cut)}")
    probe = report.get("installed_pdk_root_probe")
    line = f"[ENVIRONMENT] {GATE}: {' '.join(bits)}"
    return line + (f"\n              probe: {probe}" if probe else "")


def _emit_human(report: Dict[str, Any]) -> None:
    print(_environment_line(report))
    if report.get("failure_kind") == "environment":
        print(f"[ENVIRONMENT-FAILURE] {report.get('reason')}")
    for r in report.get("claims", []):
        if r["verdict"] == "CONTRADICTED":
            print(f"[CONTRADICTED] {r['document']}:{r['line']}")
            print(f"    claim    : {r['claim']}")
            print(f"    installed: {r['reason']}")
            for path in r.get("evidence", [])[:10]:
                print(f"    artefact : {path}")
            for path, secs in (r.get("sections_discovered") or {}).items():
                print(f"    sections : {Path(path).name}: {', '.join(secs)}")
        elif r["verdict"] == "UNDECIDED":
            print(f"[UNDECIDED] {r['document']}:{r['line']} — {r['reason']}")
    c = report.get("counts", {})
    print(f"{GATE}: {report.get('documents_scanned', 0)} input document(s), "
          f"{len(report.get('claims', []))} candidate claim(s) — "
          f"contradicted={c.get('contradicted', 0)} "
          f"corroborated={c.get('corroborated', 0)} "
          f"undecided={c.get('undecided', 0)}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[1],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tree", help="project or repository tree to scan")
    ap.add_argument("--pdks-root", default=os.environ.get(
        "VIBEIC_PDKS_ROOT", DEFAULT_PDKS_ROOT),
        help="installed PDK root (default %(default)s)")
    ap.add_argument("--container", default=None,
                    help="read the installed PDK inside this container")
    ap.add_argument("--doc-suffix", action="append", default=None,
                    help="input-document suffix (repeatable)")
    ap.add_argument("--json", default=None, help="JSON report path, or - for stdout")
    args = ap.parse_args(argv)

    report = run(Path(args.tree), args.pdks_root, container=args.container,
                 doc_suffixes=tuple(args.doc_suffix or DEFAULT_DOC_SUFFIXES))

    if args.json == "-":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(
                json.dumps(report, indent=2, ensure_ascii=False))
        _emit_human(report)

    skipped = report["verdict"] == "NOT_APPLICABLE"
    passed = report["verdict"] != "FAIL"
    reason = report.get("reason", "unspecified")
    print(_vacuous_exit.verdict_line(GATE, passed, skipped, reason),
          file=sys.stderr)
    if skipped:
        _vacuous_exit.announce_vacuous(GATE, reason)
    return _vacuous_exit.exit_code(passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
