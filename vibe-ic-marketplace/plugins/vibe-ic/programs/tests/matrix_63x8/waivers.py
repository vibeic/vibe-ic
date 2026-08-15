"""matrix_63x8.waivers — the accepted-gap registry.

A waiver is a public, dated admission that one cell of the 504 is NOT enforced
and WHY. It is not a way to make a red test green; it is a way to make an
unenforced cell *visible and machine-checkable* instead of silently absent.

====================================================================
HOW A WAIVER IS CONSUMED
====================================================================
A waived cell's test is marked::

    @pytest.mark.xfail(strict=True, reason=waiver.reason)

``strict=True`` is REQUIRED and is the entire anti-rot mechanism: the moment
the underlying gap is fixed and the predicate starts passing, the suite goes
**red** on XPASS and forces the waiver's removal. A non-strict xfail rots
silently forever, which is the same silent-absence disease in a different
costume.

====================================================================
WHAT COUNTS AS A REASON
====================================================================
``reason`` must say what a program *cannot decide* and why, in terms someone
who has never seen the cell can check. ``evidence`` must be independently
verifiable: a ``path:line``, a measured value with the command that produced
it, or a decision reference.

    GOOD  reason:   "The artefact is emitted on only one branch of a real PDK
                     condition, so an unconditional declaration converts every
                     honest run of the other branch into MISSING."
          evidence: "programs/mixed_signal_top_lvs_run.py::`(rpt_dir / "top_lvs.json").write_text(`"

                    (a CONTENT anchor. The example a reader copies decides how
                     the next waiver is written, and a `path:line` here rots the
                     moment that file shifts — measured 2026-08-14, the `:917`
                     this carried resolved on main but FAILED inside three
                     separate batches.)

    GOOD  reason:   "Deciding this needs a real converged project tree; the
                     required artefact is produced only by a tool absent from CI."
          evidence: "`which verilator` -> rc=1 on 192.168.1.120; measured 2026-07-25"

    BAD   "not implemented yet"          - says nothing checkable
    BAD   "too hard"                     - says nothing checkable
    BAD   "flaky"                        - names a symptom, not a cause
    BAD   "covered elsewhere"            - then point at it in `evidence`, or
                                           it is not covered

====================================================================
A CITATION MUST RESOLVE, AND `validate()` CHECKS THAT IT DOES
====================================================================
Everything above was true of this module for a fortnight while all four
dimension-7 entries cited line numbers that had MOVED. ``validate()`` checked
the dim range, the step id, and two length floors; it never opened a cited
file. ``programs/mixed_signal_top_lvs_run.py:256`` — the M1/d7 producer
citation — read ``chosen_path, chosen, chosen_ref = parsed[0]``; the write it
names is 661 lines further down at :917. Step 23's six citations into
``phase3_one_shot_runner.py`` were ~9,450 lines off. The docstring's own GOOD
example named ``programs/rtl_dispatch.py``, a file this repository does not
have. A citation nobody can follow is the same silent-absence disease the
504-cell matrix exists to catch, one level up: in the mechanism that records
why a cell is exempt.

:func:`validate` now RESOLVES every citation, and an unresolvable one is a
failure. Three things must hold.

1. **The path must exist**, spelled relative to the plugin root, so anyone with
   the commit can ``sed -n`` it. ``fmeda_coverage_check.py:3`` is not a
   citation; ``programs/fmeda_coverage_check.py:3`` is. ``foo:12`` is accepted
   only when ``programs/foo.py`` exists, and ``… :20638`` inherits the file
   named before it — both forms are already in use here.
2. **The lines must be inside the file**, and a citation may not span more than
   :data:`MAX_CITATION_SPAN` lines. A range wide enough to contain anything
   points at a chapter, not at a line.
3. **The cited lines must contain something this waiver names.** The waiver's
   own text is mined for code-shaped tokens — quoted fragments, dotted and
   underscored identifiers, path tails — and at least one of them, at least
   :data:`MIN_ANCHOR_LEN` characters long, must occur inside the cited span.

Rule 3 is where "resolves" could have degenerated into "passes anything", and
the guard against that is :data:`MAX_ANCHOR_LINE_HITS`: a token that occurs on
more than that many lines of the cited file does not distinguish the cited line
from any other, so it does not count as an anchor. The number is MEASURED, not
picked. Over the citations this registry actually makes, the tightest anchor a
true citation needs is ``top_lvs`` on 16 of the 166 lines of
``programs/mixed_signal_merge_check.py``; the loosest tokens that must NOT
count are ``merge`` (80 lines) and ``phase3`` (367 lines) in the files they are
cited against. 20 sits in that gap with a measured margin on both sides. All
ten of the stale citations this check was written to catch fail it at every
threshold in 12..30, so the verdict does not hang on the exact value.

A consequence worth stating plainly: a bare ``path:line`` with no statement of
WHAT is there can no longer pass. The citation and the claim about it travel
together, which is what makes the pair checkable at all.

====================================================================
THIS TUPLE STARTS EMPTY AND IS APPLIED CENTRALLY
====================================================================
The eight dimension modules share this worktree. A sibling that needs a waiver
**reports it to the orchestrator in its return value** and does NOT edit this
file — concurrent edits to a shared registry lose entries. The orchestrator
applies them in one pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterator, List, Optional, Tuple, Union

from . import flowref
from .flowref import StepId


@dataclass(frozen=True)
class Waiver:
    """One accepted, evidence-backed gap in the 504-cell matrix."""

    step_id: Union[str, int]
    dim: int
    reason: str
    evidence: str

    @property
    def key(self) -> Tuple[str, int]:
        return (flowref.normalize_id(self.step_id), self.dim)

    @property
    def label(self) -> str:
        return f"{flowref.normalize_id(self.step_id)}/d{self.dim}"

    @property
    def xfail_reason(self) -> str:
        """The string to hand ``pytest.mark.xfail(strict=True, reason=...)``."""
        return f"WAIVED {self.label}: {self.reason} [evidence: {self.evidence}]"


#: Phrases that are NOT reasons. Matched with WORD BOUNDARIES, not as bare
#: substrings — a naive ``"later" in reason`` also fires on "related" and
#: "translated", which is the same false-positive-by-adjacent-measurement error
#: this whole package exists to avoid. Checked by the meta-test so a
#: placeholder can never be smuggled in as an accepted gap.
FORBIDDEN_REASON_SUBSTRINGS: Tuple[str, ...] = (
    "not implemented",
    "todo",
    "tbd",
    "fixme",
    "too hard",
    "will fix later",
    "unknown",
)

_FORBIDDEN_RE = tuple(
    (phrase, re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", re.IGNORECASE))
    for phrase in FORBIDDEN_REASON_SUBSTRINGS
)

#: Minimum lengths. A one-word reason cannot be evidence-backed.
MIN_REASON_LEN = 40
MIN_EVIDENCE_LEN = 8

# ====================================================================
# CITATION RESOLUTION — see "A CITATION MUST RESOLVE" in the module
# docstring for why each of these exists and how the numbers were chosen.
# ====================================================================

#: An anchor shorter than this is a word, not a code landmark: ``json``,
#: ``path``, ``file``, ``sta``. Six characters is the floor at which the
#: registry's real anchors survive — ``top_lvs`` (7) and ``stance`` (6) are the
#: shortest any true citation here depends on.
MIN_ANCHOR_LEN = 6

#: A token occurring on more than this many lines of the cited file does not
#: distinguish the cited line from any other, so it is not an anchor. See the
#: docstring for the measured gap this sits in (needed: <=16; must not count:
#: >=80).
MAX_ANCHOR_LINE_HITS = 20

#: A citation wider than this is a chapter reference. The widest true citation
#: in this registry is 29 lines.
MAX_CITATION_SPAN = 40

#: File suffixes a ``path:line`` citation may carry. The grammar is
#: deliberately CLOSED: a token that merely looks like ``word:12`` — a ratio, a
#: timestamp, a JSON fragment — must not be promoted into a claim that is then
#: reported as unverifiable.
_CITATION_SUFFIXES: Tuple[str, ...] = (
    "py", "json", "yaml", "yml", "md", "txt", "cfg", "toml",
    "v", "sv", "tcl", "sh", "lef", "lib", "sdc", "spef", "rpt", "def",
)

#: ``12``, ``12-30``, ``3,45``, ``3,45-50``. NO spaces are allowed: every
#: citation in this registry is written without them, and permitting them would
#: let "``…py:12``, and 30 tracked roots" parse ``30`` as a line number.
_LINE_SPEC = r"\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*"

_PATH_CITE_RE = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_.+-]+/)*[A-Za-z0-9_.+-]+"
    r"\.(?:" + "|".join(_CITATION_SUFFIXES) + r"))"
    r":(?P<lines>" + _LINE_SPEC + r")"
)

#: ``vibe_ic_one_shot_runner:928`` — a module citation with the suffix dropped.
#: Accepted ONLY when ``programs/<stem>.py`` exists, so ordinary prose can never
#: be mistaken for one. Without this form the whole check has a hole a future
#: entry could walk through by leaving off ``.py``.
_MODULE_CITE_RE = re.compile(
    r"(?<![\w./:])(?P<stem>[a-z_][a-z0-9_]{3,}):(?P<lines>" + _LINE_SPEC + r")"
)

#: ``… and :20638`` — a continuation inheriting the last file named before it.
_BARE_CITE_RE = re.compile(r"(?<![\w./:]):(?P<lines>" + _LINE_SPEC + r")")

#: ``programs/foo.py::`the exact source text``` — a CONTENT citation (#1289).
#:
#: WHY THIS FORM EXISTS. A ``path:LINE`` citation rots on every edit ABOVE the
#: line it names, and it rots in the worst possible way: it still resolves to a
#: line, so it still READS as evidence while pointing at unrelated code.
#: Measured on ``a38902d1`` — ``flow_compliance_check.py:2439-2441`` had come to
#: read ``return result``, and ``phase3_one_shot_runner.py:30288`` an EMPTY
#: LINE, after the file moved by ~680 lines. Nothing about those waivers had
#: changed. Three separate hand re-verifications of the same rows are recorded
#: in this file (``2026-08-08``, ``was 29776-29796``, ``re-verified
#: 2026-08-13``); this form is what ends that.
#:
#: The anchor is the evidence and the line number is derived, not stored, so an
#: edit anywhere else in the cited file cannot invalidate it.
_CONTENT_CITE_RE = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_.+-]+/)*[A-Za-z0-9_.+-]+"
    r"\.(?:" + "|".join(_CITATION_SUFFIXES) + r"))"
    r"::(?:`(?P<btick>[^`\n]{3,160})`"
    r"|'(?P<squote>[^'\n]{3,160})'"
    r"|\"(?P<dquote>[^\"\n]{3,160})\")"
)

#: Quoted runs and code-shaped bare tokens: the two places a waiver states what
#: is at the line it cites. A bare token must carry a ``_``, ``.`` or ``/`` —
#: English words are not anchors.
_QUOTED_RE = re.compile(r"'([^'\n]{3,160})'|\"([^\"\n]{3,160})\"|`([^`\n]{3,160})`")
_CODEY_RE = re.compile(
    r"[A-Za-z0-9_]+(?:[./][A-Za-z0-9_]+)+|[A-Za-z0-9]*_[A-Za-z0-9_]*"
)

_ANCHOR_SPLIT_RE = re.compile(r"[\s./,;:()\[\]{}<>]+")


def _anchors(text: str) -> Tuple[str, ...]:
    """Every code-shaped token *text* names, longest first.

    Longest-first so the message a failure prints points at the most specific
    thing the waiver said, not at the vaguest one that happened to match.
    """
    out = set()

    def add(fragment: str) -> None:
        fragment = fragment.strip()
        if len(fragment) >= MIN_ANCHOR_LEN:
            out.add(fragment)
        for piece in _ANCHOR_SPLIT_RE.split(fragment):
            if len(piece) >= MIN_ANCHOR_LEN:
                out.add(piece)

    for m in _QUOTED_RE.finditer(text):
        add(next(g for g in m.groups() if g is not None))
    for m in _CODEY_RE.finditer(text):
        add(m.group(0))
    return tuple(sorted(out, key=lambda s: (-len(s), s)))


@lru_cache(maxsize=64)
def _cited_file(rel: str) -> Optional[Tuple[Tuple[str, ...], Tuple[str, ...]]]:
    """``(lines, lowercased lines)`` of ``PLUGIN_ROOT/rel``, or ``None``.

    Paths are PLUGIN-ROOT-relative and nothing else. Resolving them against the
    operator's cwd, or walking up to the repository root, would make a waiver's
    validity a property of the machine — the host-dependence #527 removed from
    dimension 3.
    """
    path = flowref.PLUGIN_ROOT / rel
    if not path.is_file():
        return None
    lines = tuple(path.read_text(errors="replace").splitlines())
    return lines, tuple(line.lower() for line in lines)


def _iter_citations(text: str) -> Iterator[Tuple[str, int, int, str]]:
    """Yield ``(rel_path, lo, hi, as_written)`` for every citation in *text*."""
    spans: List[Tuple[int, int, Optional[str], str]] = []
    for m in _PATH_CITE_RE.finditer(text):
        spans.append((m.start(), m.end(), m.group("path"), m.group("lines")))
    taken = [(s, e) for s, e, _p, _l in spans]
    for m in _MODULE_CITE_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        rel = f"programs/{m.group('stem')}.py"
        if _cited_file(rel) is None:
            continue
        spans.append((m.start(), m.end(), rel, m.group("lines")))
    taken = [(s, e) for s, e, _p, _l in spans]
    for m in _BARE_CITE_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        spans.append((m.start(), m.end(), None, m.group("lines")))
    spans.sort()

    last: Optional[str] = None
    for _s, _e, path, lines in spans:
        if path is not None:
            last = path
        elif last is None:
            # A bare `:12` with no file named before it is prose, not a
            # citation. Reporting it would red the registry over a ratio.
            continue
        rel = path or last
        assert rel is not None
        for part in lines.split(","):
            lo, _dash, hi = part.partition("-")
            yield rel, int(lo), int(hi or lo), f"{rel}:{part}"


def _unanchored_problem(
    raw: str,
    rel: str,
    lo: int,
    hi: int,
    lines: Tuple[str, ...],
    lower: Tuple[str, ...],
    anchors: Tuple[str, ...],
    self_names: frozenset,
) -> str:
    """The failure message, WITH the lines the named anchors are really on.

    Printing where the anchor actually is turns the repair into a lookup
    instead of an investigation — the reason a stale citation survives is that
    following it up is work.
    """
    shown = lines[lo - 1].strip()
    hints: List[str] = []
    for anchor in anchors:
        low = anchor.lower()
        if low in self_names:
            continue
        where = [i + 1 for i, line in enumerate(lower) if low in line]
        if 0 < len(where) <= MAX_ANCHOR_LINE_HITS:
            hints.append(f"{anchor!r} is at {where[:6]}")
        if len(hints) == 3:
            break
    span = str(lo) if hi == lo else f"{lo}-{hi}"
    head = (
        f"citation {raw!r} does not resolve: {rel}:{span} reads "
        f"{shown[:70]!r}, which contains nothing this waiver names"
    )
    if hints:
        return head + " — " + "; ".join(hints)
    return (
        head + f"; and this waiver names no token of {MIN_ANCHOR_LEN}+ chars "
        f"that occurs on at most {MAX_ANCHOR_LINE_HITS} lines of {rel}, so "
        f"the citation says nothing that could be checked"
    )


def _iter_content_citations(text: str) -> Iterator[Tuple[str, str, str]]:
    """Yield ``(rel_path, anchor, as_written)`` for every CONTENT citation.

    Deliberately requires a QUOTE immediately after ``::``. A pytest node id —
    ``tests/test_x.py::test_name`` — is written without one and this registry
    already contains several, so the quote is what keeps a test reference from
    being promoted into an evidence claim it was never making.
    """
    for m in _CONTENT_CITE_RE.finditer(text):
        anchor = m.group("btick") or m.group("squote") or m.group("dquote")
        yield m.group("path"), anchor, m.group(0)


def content_citation_problems(waiver: Waiver) -> Tuple[str, ...]:
    """Every CONTENT citation that does not resolve to exactly one line.

    THE THREE OUTCOMES, and why each is what it is (#1289):

    * **one hit** — the construct is there. The line number is REPORTED for a
      human reader and never stored, which is the whole point: nothing to rot.
    * **no hits** — FAIL. The construct this waiver rests on is gone from the
      file, which is precisely when a waiver must be re-examined. A line-number
      citation cannot express this: a deleted construct and a moved one both
      leave *some* line at that number.
    * **more than one hit** — FAIL, as ambiguous. This is the guard against the
      failure mode that would make the form worse than what it replaces: an
      anchor loose enough to always match is a waiver that can never be
      re-examined. Measured while writing this — ``len(corners) < 2`` occurs 3
      times in ``phase3_one_shot_runner.py`` and ``single_corner_stance.json``
      4 times, so both are refused; the assignment that writes it,
      ``stance_path = rpt_phase3 / "single_corner_stance.json"``, occurs once
      and is accepted. The rule makes the author name the construct rather than
      gesture at the topic.
    """
    text = f"{waiver.reason or ''}\n{waiver.evidence or ''}"
    problems: List[str] = []
    for rel, anchor, raw in _iter_content_citations(text):
        got = _cited_file(rel)
        if got is None:
            problems.append(
                f"content citation {raw!r} names no file — {rel} does not "
                f"exist under the plugin root, so nobody can follow it"
            )
            continue
        lines, lower = got
        needle = anchor.lower()
        hits = [i + 1 for i, line in enumerate(lower) if needle in line]
        if not hits:
            problems.append(
                f"content citation {raw!r} resolves to NOTHING — no line of "
                f"{rel} contains {anchor!r}. The construct this waiver rests "
                f"on is gone, so the waiver has to be re-examined rather than "
                f"re-pointed"
            )
        elif len(hits) > 1:
            problems.append(
                f"content citation {raw!r} is AMBIGUOUS — {len(hits)} lines "
                f"of {rel} contain {anchor!r} (at {hits[:6]}). An anchor that "
                f"matches in several places cannot show WHICH construct the "
                f"waiver rests on; tighten it to the line that does the work"
            )
    return tuple(problems)


def citation_problems(waiver: Waiver) -> Tuple[str, ...]:
    """Every citation in *waiver* that cannot be followed. Empty means clean.

    Reads BOTH fields. A ``path:line`` in a ``reason`` is exactly as much a
    claim as one in ``evidence``; checking only the latter would leave the
    obvious place to put an unchecked citation.
    """
    text = f"{waiver.reason or ''}\n{waiver.evidence or ''}"
    anchors = _anchors(text)
    problems: List[str] = []
    for rel, lo, hi, raw in _iter_citations(text):
        got = _cited_file(rel)
        if got is None:
            problems.append(
                f"citation {raw!r} names no file — {rel} does not exist under "
                f"the plugin root, so nobody can follow it"
            )
            continue
        lines, lower = got
        if lo < 1 or hi < lo or hi > len(lines):
            problems.append(
                f"citation {raw!r} is outside {rel}, which has {len(lines)} "
                f"lines"
            )
            continue
        if hi - lo + 1 > MAX_CITATION_SPAN:
            problems.append(
                f"citation {raw!r} spans {hi - lo + 1} lines, over the "
                f"{MAX_CITATION_SPAN}-line ceiling — that is a chapter "
                f"reference, and a range wide enough to contain anything "
                f"cannot be checked against what the waiver claims"
            )
            continue
        base = rel.rsplit("/", 1)[-1].lower()
        self_names = frozenset(
            {rel.lower(), base, base[:-3] if base.endswith(".py") else base}
        )
        span_text = "\n".join(lower[lo - 1:hi])
        anchored = False
        for anchor in anchors:
            low = anchor.lower()
            if low in self_names or low not in span_text:
                continue
            # DISCRIMINATION: an anchor spread over the whole file anchors
            # nothing — with it, any line number at all would "resolve".
            if sum(1 for line in lower if low in line) <= MAX_ANCHOR_LINE_HITS:
                anchored = True
                break
        if not anchored:
            problems.append(
                _unanchored_problem(
                    raw, rel, lo, hi, lines, lower, anchors, self_names
                )
            )
    # Both grammars go through THIS entry point. A content citation checked by
    # a second function nobody calls would be the orphan-checker shape — the
    # registry has one validator and it must judge everything a waiver writes.
    return tuple(problems) + content_citation_problems(waiver)


#: Applied 2026-07-27 by the close-out pass, from the eight dimension agents'
#: reported ``waiver_requests``. Every entry names a SPECIFIC obstacle with
#: independently checkable evidence; generic reasons ("needs a real run", "hard
#: to test") were rejected and are carried as residual gaps instead.
#:
#: THIS IS THE ONLY REGISTRY. The dimension modules used to keep local mirrors
#: of their own entries, and the two copies drifted unnoticed (#527, #530). No
#: dimension module may define one; ``waiver_for`` reads this tuple and nothing
#: else.
#:
#: 2026-07-28: the ten dimension-4 entries and the five dimension-5 entries are
#: gone, and so are five of the nine dimension-7 entries — every one of them
#: because the defect it named was FIXED in the flow definition or in the gate
#: program, each with a mutation control showing the cell red on the old code.
#: The two that used to be described here as "ONE-LINE REPO DEFECTS we are not
#: fixing because it edits the production flow" (4/step 2's ``--json`` vs
#: ``--out`` mismatch, 4/P0's unregisterable gate name) are among them: the
#: flow WAS edited, and verified.
WAIVERS: Tuple[Waiver, ...] = (
    # ── dimension 2 — can the gate ever FAIL? ─────────────────────────
    #
    # 2026-08-06. Dimension 2 published 129 reds and 33 of them proved
    # nothing: they were `files_exist` / `json_field_true` clauses measured on
    # the default EMPTY fixture, whose builder is
    # `test_matrix_d2_falsifiable._f_empty` ("""Nothing was produced at
    # all.""", empty body). `flow_compliance_check._check_files_exist` is
    # `passed = len(missing) == 0` and nothing else (:2239-2243), so on an
    # empty directory that clause is RED by construction — 33/33, 100 %, zero
    # exceptions — while the SAME clause PASSES against a stub: step 21's
    # `files_exist: ['phase3/stage3/pnr/routed.def']` answers PASS to the 25
    # bytes `VERSION 5.8 ;\nEND DESIGN\n`.
    #
    # SIX steps had NO OTHER RED: 1, 6, 12, 28, 30, 35. Three are now reddened
    # for real, against projects that produced work and got it wrong — a
    # Quartus build reporting success over a map report carrying stuck-at-GND
    # (step 6), a PERC aggregate concluding an ESD FAIL (step 28), a design
    # taken through SPEF and post-route STA with no SPICE correlation at all
    # (step 30) — which also de-registered three UNREDDENED entries. Nothing
    # was relaxed to get them: the count of clauses driven to a real FAIL went
    # UP.
    #
    # The three below could not be closed and are not going to be closed by a
    # fixture. Their gates consist of `files_exist` clauses and nothing else,
    # so there is no input other than absence that reaches a FAIL — this is a
    # property of the FLOW DEFINITION, not of the test suite, and the repair
    # is to give the step a clause that judges what the artefact says. Each
    # premise is a statement about this commit, re-derived live on every run
    # by test_d2_the_waived_cells_are_gated_by_existence_alone (the clause
    # census) and test_d2_a_files_exist_clause_is_satisfied_by_a_zero_byte_file
    # (the zero-byte measurement over every such clause in the flow).
    Waiver(
        step_id="1",
        dim=2,
        reason=(
            "PERMANENT, by design — not a pending flow-definition decision. "
            "Step 1's gate is ONE clause, `files_exist(any_of): "
            "['phase2/stage1/rtl/*.sv', 'phase2/stage1/rtl/*.v']`, and a "
            "files_exist clause has no predicate but path resolution — the "
            "consumer computes `passed = len(found) > 0` and evaluates "
            "nothing about the file. In isolation that clause cannot fail on "
            "content. But the flow yaml carries an explicit AUDIT NOTE on "
            "this step: spec->RTL is the irreducible AI-authoring step (no "
            "deterministic spec->RTL checker exists), and RTL substance is "
            "verified DELIBERATELY DOWNSTREAM by Steps 2-6 (lint / CDC / "
            "simulation / formal) plus the P0 structural-RTL gates — not by "
            "Step 1 itself. Owner-confirmed 2026-08-08: do not add a "
            "duplicate content check to Step 1; the separation of concerns "
            "(Step 1 authors, Step 2 judges) is intentional."
        ),
        evidence=(
            "flow/phase1_phase2_phase3.yaml, the AUDIT NOTE comment directly "
            "above step id 1 ('this gate is files_exist-only ON PURPOSE ... "
            "Do not re-flag as a missing checker'). "
            "programs/flow_compliance_check.py::`passed = "
            "len(found) > 0` (the any_of branch) is the entire predicate — "
            "re-executed live by programs/tests/test_matrix_d2_falsifiable.py"
            "::test_d2_a_files_exist_clause_is_satisfied_by_a_zero_byte_file "
            "and ::test_d2_the_waived_cells_are_gated_by_existence_alone."
        ),
    ),
    Waiver(
        step_id="35",
        dim=2,
        reason=(
            "PERMANENT, by design — not a pending flow-definition decision. "
            "Step 35's gate carries `files_exist: "
            "['reports/phase3/dfm_screen.json']` plus `dfm_screen_check` "
            "wired as `advisory_program_exit_zero`, so the only BLOCKING term "
            "is path resolution. Promoting the DFM finding to blocking was "
            "considered and explicitly rejected in the flow yaml's own "
            "comment on this step: Step 31 owns the litho/min-width RULES and "
            "Step 34 owns the density EXECUTION gate, and OpenROAD ships no "
            "via-doubling repair pass — so failing Step 35 on a DFM "
            "optimisation finding would fabricate a FAIL nobody is allowed to "
            "fix. Owner-confirmed 2026-08-08: leave the DFM clause advisory."
        ),
        evidence=(
            "flow/phase1_phase2_phase3.yaml, the comment on step id 35's "
            "ADVISORY half (#306) naming Step 31/34's ownership and the "
            "absent OpenROAD repair pass. "
            "programs/flow_compliance_check.py::`passed = "
            "len(missing) == 0` is the blocking term's entire predicate; "
            "flowref.GateClause.is_advisory excludes the DFM clause from "
            "this dimension by the module's own rule 1. Re-executed live by "
            "programs/tests/test_matrix_d2_falsifiable.py::"
            "test_d2_the_waived_cells_are_gated_by_existence_alone and "
            "::test_d2_a_files_exist_clause_is_satisfied_by_a_zero_byte_file."
        ),
    ),

    # ── dimension 3 — are the declared outputs actually produced? ──────
    #
    # #527 — A WAIVER'S PREMISE MUST BE A STATEMENT ABOUT THIS COMMIT.
    # The four entries this block used to hold were premised on `find ~`.
    # "`find ~ -maxdepth 10 -name '*.sof'` -> 0 hits (measured 2026-07-27)" is
    # a count over a directory OUTSIDE the repository. It was true the day it
    # was written and false a fortnight later — the same command returns 203
    # today, every hit untracked, one of them in the user's Trash — and nothing
    # in the repository could notice, because the repository was never what the
    # claim was about. A waiver whose premise expires on its own is a waiver
    # nobody can audit. Every premise below is now a statement `git ls-tree -r
    # HEAD` answers identically for everyone who has the commit, re-executed on
    # every run by
    # `test_d3_waived_unproven_entries_have_no_committed_artefact`.
    #
    # 2026-07-28: A8's waiver was NARROWED, not closed. Its `.gds` had no
    # producer anywhere in the plugin — `magic_port_extract_emit
    # .build_gds_write_tcl` shipped in v0.1.114 with a unit test and no caller
    # — so `programs/analog_hardmacro_gds_emit.py` was written, DECLARED in
    # A8's `programs:` and invoked by
    # `analog_one_shot_runner.step_for_block("A8_hardmacro_gen")`. It is
    # deliberately NOT a clause of A8's gate: `flow_compliance_check` is the
    # acceptance auditor and an auditor that writes a declared
    # `required_output` into the project it audits certifies its own output
    # (`test_d3_the_compliance_audit_does_not_create_declared_outputs` holds
    # that line). What did NOT change then was the cell's state: the producer
    # needs Magic in the EDA container to stream anything, so on CI and on a
    # fresh clone the entry was UNMEASURED, and a cell that is green only
    # where a container runs is the host-dependence #527 removed.
    #
    # 2026-08-06: **A8's WAIVER IS REMOVED, and the anti-rot mechanism is what
    # removed it.** That waiver's evidence field asserted, verbatim, that
    # "`git ls-tree -r --name-only HEAD` matches ZERO paths against
    # phase3/analog/hardmacro/*/*.gds". Commit b1665ec8 made that false: it
    # published
    # `benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A/phase3/analog/hardmacro/
    # {delta_sigma,ldo}/*.gds` (111096 B and 641262 B), so the same command now
    # matches 2, and `test_d3_waived_unproven_entries_have_no_committed_
    # artefact` turned the suite red exactly as designed.
    #
    # The reason was re-argued and did not survive, because the waiver had
    # written down its own closing condition — "Closing this needs a published
    # analog run whose A8 actually streamed the layout" — and that is
    # precisely what b1665ec8 published. Re-arguing it on the technicality
    # that the published cell is not one of the seven `provenance.jsonl` /
    # `reports/orchestrator/` run trees would be measuring the marker instead
    # of the property: the property this dimension asks about is whether the
    # declared output is PRODUCED, and two real GDSII streams — valid HEADER,
    # 1721 and 9997 geometry records, each defining a structure named after
    # its own block directory, neither a symlink, both tracked at HEAD — are
    # the answer. So the cell is ENFORCED and its `.gds` is recorded
    # PRODUCED_BY_RUN against the published cell, which
    # `test_matrix_d3_outputs_produced` admits as an evidence root on the
    # publish contract's own precondition (`benchmark_evidence_publish.py`
    # REFUSES a non-converged run) rather than by widening the marker list.
    # Bidirectional control:
    # `programs/tests/test_matrix_a8_published_gds_control.py` (the name
    # deliberately avoids the `test_matrix_d[1-8]_*` prefix, which
    # `test_matrix_63x8_coverage.DIMENSION_MODULE_GLOB` reserves for the eight
    # dimension modules themselves).
    #
    # STEPS 6 AND 39 STAY WAIVED — the NA_TOOLCHAIN_ABSENT reclassification was
    # REFUTED BY ITS OWN ASSERTION. The proposal was to move both cells out of
    # this registry and call them NA because Intel Quartus, the sole producer
    # of their bitstream entries, "is reachable from nowhere this suite can
    # run", asserted live through the flow's own locator
    # (`design_one_shot_runner._find_host_quartus_sh`). Re-measured 2026-07-28
    # on the maintainer host, that locator returns a real, executable
    # `quartus_sh` under an external mount, so the NA's self-invalidating
    # assertion FIRES and both cells go red. The premise is a property of the
    # machine, which is the exact host-dependence #527 removed from this
    # dimension; the premises below are properties of the COMMIT and are true
    # everywhere. Re-checked 2026-08-06 against the same command that unseated
    # A8: `git ls-tree -r --name-only HEAD` still matches 0 `*.sof` and 0
    # `*.map.rpt` anywhere in the repository, so both premises hold.
    Waiver(
        step_id="6",
        dim=3,
        reason=(
            "Two of the three entries are Intel Quartus outputs — a .sof "
            "bitstream and a .map.rpt — and no program in this repository "
            "synthesises an FPGA bitstream, so nothing here can produce them "
            "and no archived run tree carries one either. The dimension-3 "
            "manifest records no producer for either entry, which is the same "
            "fact from the other side: there is no command this suite could "
            "run to close the gap. NOTE (2026-07-28): a host having Quartus "
            "installed does NOT close this. The claim is about the "
            "repository, and a cell whose colour depends on whether the "
            "operator's machine has a vendor toolchain is the host-dependence "
            "#527 was written to remove."
        ),
        evidence=(
            "`git ls-tree -r --name-only HEAD` matches ZERO paths against "
            "either entry — 0 tracked '*.sof' and 0 tracked '*.map.rpt' in the "
            "whole repository, and 0 under any of the 7 admissible in-repo run "
            "roots. The sibling entry reports/phase2/fpga/"
            "quartus_map_audit.json IS produced (263 B in benchmark-data/ic/"
            "spm/v1.5.66_gf180mcuD), so the step runs and only the bitstream "
            "half is missing; programs/fpga_board_capability.py:8 names 'no "
            "Quartus on host' as the expected disclosed gap. Re-executed live "
            "by programs/tests/test_matrix_d3_outputs_produced.py::"
            "test_d3_waived_unproven_entries_have_no_committed_artefact"
        ),
    ),
    Waiver(
        step_id="39",
        dim=3,
        reason=(
            "The entry phase2/stage1/fpga/final/*.sof is the recompiled Intel "
            "Quartus bitstream for on-board sign-off; the same missing "
            "producer as step 6 applies, so nothing in this repository can "
            "write it, while the sibling on_board_pass.json is produced "
            "normally."
        ),
        evidence=(
            "`git ls-tree -r --name-only HEAD` matches ZERO paths against "
            "phase2/stage1/fpga/final/*.sof anywhere in the repository or "
            "under any admissible in-repo run root; the sibling entry "
            "reports/phase2/fpga/on_board_pass.json resolves at 732 B in "
            "benchmark-data/ic/spm/v1.5.66_gf180mcuD. Re-executed live by "
            "programs/tests/test_matrix_d3_outputs_produced.py::"
            "test_d3_waived_unproven_entries_have_no_committed_artefact"
        ),
    ),
    # A8/d3 STOOD HERE AND IS GONE — see the 2026-08-06 note above. It is
    # deleted rather than re-argued because its own stated closing condition
    # was met by commit b1665ec8, and because a waiver kept alive on a
    # narrower story than the one it was written with is the rot this registry
    # exists to prevent.
    # M1/d3 STOOD HERE AND IS GONE, and not because anyone accepted less.
    # Its own reason was "no admissible run root is a mixed-signal project, so
    # the producer returns its documented rc=2 'inputs missing' skip everywhere
    # it can run" — which is DORMANCY described one artefact at a time. M1
    # carries the same step-level condition as M2-M4,
    # `phase1/analog/analog_block_list.json`, and that path occurs ZERO times
    # in `git ls-tree -r HEAD` over the whole repository. The step has never
    # run here, so there is no gap to accept; there is a state to record, and
    # dimension 3 now records it as `NA_DORMANT_CONDITION`.
    #
    # That is STRICTLY STRONGER than the waiver it replaces. A waiver is
    # inert: it says "known, accepted" and stays green whatever the tree does.
    # The NA re-derives on every run and reddens in BOTH directions — publish
    # any tree carrying the condition file, or let either declared output
    # appear anywhere, and the cell fails. Both were injected and both fired.
    #
    # The waiver ALSO covered only one of M1's two entries, which is why
    # `test_d3_waived_steps_still_produce_their_unwaived_entries` was red on
    # `merge.json`: a per-entry waiver cannot express "this step never ran".
    # M1's dimension-7 waiver is untouched — different dimension, different
    # reason, and its artefact question survives dormancy.

    # ── dimension 5 — is blocks_on the true dependency graph? ──────────
    Waiver(
        step_id="12",
        dim=5,
        reason=(
            "dft_post_optimization_scan_survival_check (step 12's new "
            "content clause, landed 2026-08-08 to close a dimension-2 gap) "
            "reads phase2/stage2/synth/netlist.v to detect the 'pre-DFT "
            "netlist copied over' substitution. That path's TRUE producer, "
            "step 9, is already inside step 12's blocks_on closure "
            "(blocks_on=[11], closure includes 9 via 11->10->...->9) — so "
            "the real dependency is already covered. The finding fires "
            "because step 14 ALSO declares the identical path in ITS OWN "
            "required_outputs, even though step 14 does not produce it "
            "(it audits an input already correctly declared via its own "
            "required_inputs from step 9) — a pre-existing duplicate "
            "declaration this fix did not create. depends_on cannot simply "
            "add step 14: step 14 already has step 12 in its own blocks_on "
            "ancestry (14 -> ... -> 13 -> 12), so the edge would be "
            "circular. Removing the duplicate from step 14 was tried and "
            "reverted: 63x8's own dimension-3/6/8 modules (and two "
            "ledger census constants) depend on step 14 declaring a "
            "non-empty required_outputs list for reasons unrelated to this "
            "fix, and removing it traded one narrow, understood gap for "
            "four new ones. Closing this needs step 14's duplicate "
            "declaration reconciled against everything that currently "
            "reads it — a separate, wider change, not a step-12 fix."
        ),
        evidence=(
            "flow/phase1_phase2_phase3.yaml: step 9's required_outputs "
            "declares phase2/stage2/synth/netlist.v (the true producer); "
            "step 14's required_outputs ALSO declares the identical path "
            "(the duplicate) while step 14's OWN required_inputs already "
            "correctly cites `from: 9` for the same file. "
            "programs/dft_post_optimization_scan_survival_check.py reads "
            "phase2/stage2/synth/netlist.v via `project / \"phase2\" / "
            "\"stage2\" / \"synth\" / \"netlist.v\"` to compare against "
            "post_dft_netlist.v. MEASURED 2026-08-08: "
            "test_matrix_d5_deps_correct.py::derived_dependencies('12') "
            "returns step 9 (already in closure, no finding) AND step 14 "
            "(not in closure, D5-MISSING-EDGE, would-cycle) for the same "
            "artefact — both from `producers()` legitimately returning "
            "('9', '14') for phase2/stage2/synth/netlist.v. Negative "
            "control: deleting step 14's required_outputs entry (tested, "
            "then reverted) makes this cell pass but reddens "
            "test_matrix_63x8_ledger.py::"
            "test_required_outputs_non_empty_exactly_where_declared, "
            "::test_output_entries_classify_into_the_four_kinds, "
            "::test_accessors_track_a_removed_field, "
            "test_matrix_d3_outputs_produced.py[step14], "
            "test_matrix_d6_skip_discipline.py[step14] and "
            "test_matrix_d8_missing_caught.py::"
            "test_d8_downgrade_is_reachable_through_each_steps_own_real_gate "
            "— confirming the duplicate is load-bearing elsewhere and this "
            "is a real cross-dimension conflict, not a step-12-local one."
        ),
    ),

    # ── dimension 6 — skip discipline (the ARITHMETIC half) ───────────
    # EMPTY, and that is the point. This block used to hold THREE waivers
    # (FS1, 30, 14) charged by leg L3c of test_matrix_d6_skip_discipline:
    # each landed on the VACUOUS_PASS tier — its own label, its own counter
    # — while `flow_compliance_check` folded the tier straight back into the
    # published `X/Y executed PASS` numerator
    # (`pass_count = counts['PASS'] + counts['VACUOUS_PASS']`), so the number
    # a reviewer reads was unchanged by the disclosure. A fourth cell (step
    # 4) is charged by the same leg on hosts where its gate resolves to
    # VACUOUS_PASS rather than FAIL, and had no waiver at all — that is the
    # cell that turned main red.
    #
    # All four are CLOSED by the fix, not by a waiver: the owner ruled
    # VACUOUS_PASS out of the numerator. `pass_count = counts['PASS']`, the
    # tier stays in `total_required` (it is an unmet requirement, not an
    # inapplicable step), and every rendering of the numerator moved with it
    # — the checker headline, `final_report_generate._counts_snapshot`, its
    # prose bullet, its stage-breakdown PASS column and its resource log.
    #
    # MEASURED on this host over all 12 tracked run roots of
    # programs/tests/fixtures/matrix_d3_output_manifest.json, each COPIED
    # and re-run with the shipped checker, full flow, --strict: 12/12 roots
    # move their headline numerator and 37 step-instances leave X on the
    # numerator ruling alone. That half changes NO verdict, and the reason is
    # structural rather than a property of this corpus: `pass_count` is
    # assigned once and read once, in the headline `print`, and feeds none of
    # `failing` / `missing` / `setup_required_skipped` / `oss_blocked_skipped`
    # / `ok`. #01 4/7->3/7, #02 3/39->2/39, #03 11/26->6/26,
    # #04 18/39->13/39, #05 7/53->4/53, #06 14/30->11/30, #07 20/42->16/42,
    # #08 19/32->16/32, #09 15/53->11/53, #10 5/10->4/10, #11 7/41->4/41,
    # #12 31/42->27/42.
    #
    # AS SHIPPED, the same sweep run against the whole commit — which also
    # carries the dimension-7 declaration on step 27 — reads: 12/12 headlines
    # move, 40 step-instances leave X (37 vacuous + 3 from step 27), 3 of 756
    # per-step verdicts change and 0 of 12 Overall verdicts change (all 12
    # FAIL before and after). The three are all step 27, on the three roots
    # that carry a crosstalk report and no MCF report: #03 PASS ->
    # DEFERRED-BY-UPSTREAM (a cascade, which is also why its denominator
    # moves 26 -> 25), #04 and #09 PASS -> MISSING. Combined headlines:
    # #03 11/26->5/25, #04 18/39->12/39, #09 15/53->10/53; the other nine are
    # the numbers above.

    # ── dimension 6 — skip discipline (the CONDITION half) ────────────
    Waiver(
        step_id="DT2",
        dim=6,
        reason=(
            "RE-OPENED 2026-07-28 at the convergence merge, with a sharper "
            "reason than it carried before. DT2's step-level condition is "
            "ALL-of over three paths, two of which "
            "(phase2/stage2/dft/cut_netlist.v and phase3/stage3/pnr/*_pnr.v) "
            "are artefacts whose absence DT2 exists to detect, so the step "
            "disappears in the scenario it was written for. The repo AGREES: "
            "flow_condition_reachability_check classifies it 'self-disabling' "
            "and it is carried in flow_condition_reachability_baseline.json as "
            "a known-open hole owned by vibe-ic#235. WHAT IS NEW, and why the "
            "cell is not enforced-clean by the obvious repair: re-arming the "
            "condition on the PRODUCER'S OWN OUTPUTS (any-of over "
            "reports/phase2/dft/path_delay_coverage.json or "
            "phase2/stage2/dft/path_delay_atpg_not_run.json) was tried, "
            "measured, and WITHDRAWN — it moves the self-disable from the "
            "input side to the output side, where it is strictly worse: "
            "deleting the one artefact DT2 exists to report on turns the step "
            "from MISSING/rc 1 into SKIPPED-CONDITION/rc 0 and removes it from "
            "the executed-PASS denominator, because total_required subtracts "
            "SKIPPED-CONDITION. Closing this cell needs a flow-level non-fatal "
            "verdict for 'ran, disclosed, could not measure' that COSTS the "
            "denominator; no spelling of the condition alone can do it."
        ),
        evidence=(
            "flow/flow_condition_reachability_baseline.json (owner: "
            "vibe-ic#235). Reproduce the hole: `python3 "
            "programs/flow_condition_reachability_check.py .` -> 'KNOWN-OPEN: "
            "1 self-disabling condition(s)' naming step DT2. Reproduce the "
            "withdrawn repair, on a project holding cut_netlist.v + *.spef + "
            "*_pnr.v and NO at-speed grade and NO not-run record, with a "
            "single-step DT2 flow lifted from each yaml: ALL-of condition -> "
            "'MISSING=1' / 'Overall: FAIL (strict=True)' / rc 1; "
            "producer-outputs condition -> 'SKIPPED=2' / 'Steps: 1 total "
            "(0/-1 executed PASS)' / 'Overall: PASS' / rc 0. Measured "
            "2026-07-28 with programs/flow_compliance_check.py from this tree "
            "on both flow definitions."
        ),
    ),

    # ── dimension 7 — is the required_outputs list complete? ───────────
    # Five of the nine original entries were CLOSED on 2026-07-28 by declaring
    # the artefact (D1, 21, 25, 28, 31). The four below are the residue and
    # they are blocked on three different things. Two (7, 23) share one:
    # `required_outputs` is ALL-of-N with no conditional spelling, so an
    # artefact the flow emits only on one branch of a genuine design/PDK
    # condition cannot be declared without failing the other branch. M1 is
    # blocked on evidence: the artefact exists in no published run root, so
    # declaring it would move the gap from dimension 7 to dimension 3. FS1 is
    # blocked on WIRING, and its entry below is the one that was briefly closed
    # and reopened the same day — the closure rested on the compliance checker
    # accepting an artefact it had created itself.
    Waiver(
        step_id="FS1",
        dim=7,
        reason=(
            "FS1 declares no required_outputs key at all while its gate writes "
            "two real JSON artefacts, so there is no list for the flow's "
            "presence checks to key off. REOPENED 2026-07-28 with the reason "
            "sharpened from 'adding one is a yaml change nobody has made yet' "
            "to the thing that actually blocks it: FS1's artefacts have NO "
            "producer anywhere in the plugin except the first command of its "
            "own gate, so a declaration cannot be satisfied by a run — only by "
            "the auditor. flow_compliance_check returns MISSING before the "
            "gate runs when every declared entry is absent, so declaring both "
            "paths makes FS1 a permanent red (MEASURED: two consecutive "
            "check_step runs on a fixture holding only phase2/stage1/rtl both "
            "report MISSING and leave no file under reports/). The withdrawn "
            "closure removed that early return for this step SHAPE so the gate "
            "would run and a post-gate probe would find what the gate had just "
            "written; the same suppression turned step 8 from a correct "
            "MISSING into PASS on benchmark-data/ic/ibex, certifying it on "
            "reports/phase2/sdc_check.json which the audit itself created and "
            "12 other tracked roots really do carry. WHAT CLOSES THIS, exactly "
            "one thing: wire fmeda_fault_injection_coverage into a runner the "
            "way phase3_one_shot_runner._DECLARED_SIGNOFF_GATES wired the four "
            "sign-off gates on 2026-07-27, so the artefact exists BEFORE the "
            "audit looks; then declare both paths."
        ),
        evidence=(
            "flow/phase1_phase2_phase3.yaml FS1 step has no required_outputs "
            "key while its gate runs 'fmeda_fault_injection_coverage ... "
            "--json reports/phase2/safety/fmeda_coverage.json' and "
            "'fmeda_coverage_check ... --json "
            "reports/phase2/safety/fmeda_coverage_gate.json'. NO OTHER "
            "PRODUCER: `grep -rn fmeda_fault_injection_coverage programs/ "
            "flow/` reaches exactly ONE invocation — that yaml gate line. "
            "Re-measured 2026-08-06: everything else it reaches imports the "
            "module as a library or names it in prose — "
            "programs/fmeda_coverage_check.py:3,48 (docstring, then `import "
            "fmeda_fault_injection_coverage as fi`), "
            "programs/result_md_audit_provenance_check.py:72 (the same "
            "import), plus comments and tests. "
            "All 7 tracked roots carrying reports/phase2/safety/"
            "fmeda_coverage.json hold the auditor's vacuous-skip document "
            "({'program': 'fmeda_fault_injection_coverage', 'verdict': "
            "'NOT_APPLICABLE'}), i.e. compliance-gate output committed "
            "alongside a run, not a fault-injection measurement."
        ),
    ),
    Waiver(
        step_id="7",
        dim=7,
        reason=(
            "reports/phase3/single_corner_stance.json is emitted ONLY on the "
            "single-corner branch — phase3_one_shot_runner writes it under "
            "`if len(corners) < 2 and not pvt.get('multi_corner')` — and a "
            "multi-corner run legitimately produces none, so an unconditional "
            "required_outputs entry converts every honest multi-corner run "
            "into MISSING. required_outputs is ALL-of-N and its only any-of "
            "spelling is ' OR ' between paths; every alternative that would "
            "cover the multi-corner branch (pvt_matrix.json, the gate's own "
            "reports/phase2/gates/pvt_matrix.json) is present on EVERY run, "
            "so the entry could never fail and would be a declaration that "
            "measures nothing. Closing this needs a producer change that "
            "emits a corner-stance disclosure on BOTH branches, plus a "
            "re-publish of the affected roots — a flow change with its own "
            "verification, not a declaration change."
        ),
        evidence=(
            "producer programs/phase3_one_shot_runner.py::`rpt_phase3 / "
            "\"single_corner_stance.json\"` — the write guarded by "
            "`len(corners) < 2`. CONTENT-addressed (#1289/#1290): the "
            "anchor IS the evidence and the line is derived, not stored. "
            "Cited by line until 2026-08-14 and re-measured three times as "
            "the block drifted (29776-29796, then 29941-29964, then "
            "30621-30646); #1110's atomic-write conversion then moved it "
            "two lines further, which is the churn this notation ends. "
            "Historical numbers carry no leading colon on purpose — a bare "
            "`:NNNN` inherits the last-named file and would be validated as "
            "a live citation; consumer "
            "programs/pvt_matrix_check.py:44-45 then :105. MEASURED "
            "2026-07-28 with flow_compliance_check.check_step over the nine "
            "tracked roots holding phase2/stage2/constraints/pvt_matrix.json: "
            "adding the entry moves benchmark-data/ic/spm/v1.5.58_ihp-sg13g2, "
            "v1.5.65_sky130A and v1.5.66_gf180mcuD from PASS to MISSING "
            "('required_outputs missing: "
            "[reports/phase3/single_corner_stance.json]') — three "
            "multi-corner runs failed for producing no single-corner "
            "disclosure. The other six are FAIL/PASS-unchanged."
        ),
    ),
    Waiver(
        step_id="M1",
        dim=7,
        reason=(
            "reports/analog/mixed_signal/top_lvs.json is the artefact that "
            "substantiates M1's PASS — mixed_signal_top_lvs_run writes it and "
            "mixed_signal_merge_check's PASS branch is contingent on reading "
            "it — yet M1's required_outputs names only top_merged.gds and "
            "merge.json, so nothing independently verifies its presence. "
            "Declaring it was PREPARED and then withdrawn on evidence: the "
            "artefact exists in NONE of the twelve admissible run roots and "
            "its producer needs KLayout + Magic + netgen in a container, so "
            "it cannot be shown produced live here either. Declaring it would "
            "add a second UNPROVEN entry to M1's dimension-3 waiver — moving "
            "the gap between dimensions rather than closing it. What closes "
            "this: publish one run root in which mixed_signal_top_lvs_run "
            "actually executed, then declare the artefact and record it."
        ),
        evidence=(
            # vibe-ic#1289 — CONTENT anchor, not a line number. Measured
            # 2026-08-14: this citation read `:917` and rotted in THREE separate
            # batches (the 22-PR INDEX.md batch, the 10-PR hygiene batch, and a
            # 64-PR extension), each time manufacturing a red that belonged to
            # no PR in the batch, because those batches shift lines in
            # mixed_signal_top_lvs_run.py. Re-pointing the number resets the
            # counter; anchoring to the text removes the failure mode. The
            # anchor resolves to exactly ONE line, which the validator requires.
            "producer programs/mixed_signal_top_lvs_run.py::`"
            '(rpt_dir / "top_lvs.json").write_text(' "` (in the same block "
            "as the already-declared merge.json); consumer "
            "programs/mixed_signal_merge_check.py:89-91 then :108. MEASURED "
            "2026-07-28 with test_matrix_d3_outputs_produced.resolve_anywhere("
            "'reports/analog/mixed_signal/top_lvs.json') -> None over all 12 "
            "run roots, while the sibling merge.json resolves at "
            "AI_IC_design/4th_benchmark/U_Hawaii_EE628_DeltaSigma_ADC_e2e "
            "(497 B). Mutation check that the declaration WOULD be live: with "
            "mixed_signal_merge_check's MERGE_NOT_LVS_SUBSTANTIATED branch "
            "flipped to its historical PASS-on-presence stub, M1 reports PASS "
            "without the declaration and MISSING with it."
        ),
    ),
    Waiver(
        step_id="23",
        dim=7,
        reason=(
            "Fourteen artefacts remain undeclared after "
            "reports/phase3/sta/sta_corner_record_completeness.json was "
            "declared on 2026-07-28 (that one is the step's own unconditional "
            "gate --json target, so it closed with no verdict change on any "
            "published root). The residue splits in two and BOTH halves are "
            "conditional-by-design. (a) The two multi-corner STANCE files are "
            "written only when the post-route DEF exists, and six of the "
            "eight tracked roots carrying this step's already-declared "
            "post_route_timing.rpt predate that emitter; five of them PASS "
            "today and go MISSING if the stance files are declared. (b) The "
            "three sign-off .rpt files are each emitted on one branch of a "
            "real PDK condition — sta_mcorner_ocv.rpt only when the ss and ff "
            "process libraries genuinely differ, sta_spef_multicorner.rpt "
            "only with two or more corner SPEFs, sta_spef_based.rpt only with "
            "a non-empty SPEF — and their absence is DISCLOSED in the stance "
            "files (`report: null`, `multicorner_sta_report: null`). Pairing "
            "each .rpt with its stance file via ' OR ' would declare the "
            "name, but with the stance ALSO declared the pair could never "
            "fail on its own, so it would be decoration. Closing this needs "
            "the (a) decision — re-publish the six roots, or add a "
            "conditional/disclosed-skip spelling to required_outputs — taken "
            "first; then (b) follows as OR-pairs that can actually fail. "
            "COUNT RE-MEASURED 2026-08-14 (#1215): sixteen, not the fourteen "
            "recorded above — the population drifted upward while this cell "
            "stayed red and nobody re-read it, which is what a waived cell "
            "makes easy. #1215 declared one of the sixteen, "
            "reports/phase3/sta/post_route_signoff_corner.json (this step's "
            "own post_route_signoff_corner_check --json target, promoted by "
            "the write record and undeclared), taking it to FIFTEEN. That is "
            "a finding removed, not a colour change: this cell was red before "
            "and is red after, and the (a)/(b) split above is untouched — "
            "both halves of the residue are exactly the artefacts named "
            "there."
        ),
        evidence=(
            "producers programs/phase3_one_shot_runner.py::`sta_out / "
            "\"sta_spef_based.rpt\"` and "
            "programs/phase3_one_shot_runner.py::`sta_out / "
            "\"sta_mcorner_ocv.rpt\"`, with mirrors "
            "programs/phase3_one_shot_runner.py::`mirror = rpt_phase3 / "
            "\"sta_spef_based.rpt\"` and "
            "programs/phase3_one_shot_runner.py::`mc_ocv_mirror = "
            "rpt_phase3 / \"sta_mcorner_ocv.rpt\"`, and the two stance "
            "emissions programs/phase3_one_shot_runner.py::`mc_stance = "
            "rpt_phase3 / \"multi_corner_spef_stance.json\"` and "
            "programs/phase3_one_shot_runner.py::`mc_ocv_stance = "
            "rpt_phase3 / \"mcorner_ocv_stance.json\"` — both guarded by "
            "`if primary_def.is_file() and _signoff_regen(...)`. "
            "CONTENT-addressed (#1289/#1290). Cited by line until "
            "2026-08-14 and re-measured twice "
            "(30169/30286/30175/30316/30188/30288, then "
            "30849/30966/30855/30996/30867/30967); #1110's atomic-write "
            "conversion then moved all six two lines further, which is the "
            "churn this notation ends. Historical numbers are written "
            "WITHOUT a leading colon on purpose: a bare `:NNNN` inherits "
            "the last-named file and would be validated as a live "
            "citation, so a historical number written that way re-breaks "
            "this waiver); "
            "consumer "
            "programs/sta_corner_record_completeness_check.py:194-223 "
            "(_PROCESS_STANCE_CANDIDATES / _RC_STANCE_CANDIDATES / "
            "_MULTICORNER_CANDIDATES / _MCORNER_OCV_CANDIDATES / "
            "_NOMINAL_SPEF_CANDIDATES). MEASURED 2026-07-28 with "
            "flow_compliance_check.check_step over the eight tracked roots "
            "holding phase3/stage3/sta/post_route_timing.rpt: declaring the "
            "two stance files moves phase1_parity/{espi,lpc/phase3,mdio,"
            "sgmii} and benchmark-data/ic/caravel_user_project from PASS to "
            "MISSING (5 of 8); the other three are FAIL before and after."
        ),
    ),
    Waiver(
        step_id="34",
        dim=7,
        reason=(
            "W2 charges reports/phase3/cmp_fill_emit.json as produced, "
            "gate-read and undeclared, and the READ half is an artefact of "
            "the consumer oracle rather than a fact about the flow. "
            "_gate_consumers builds {path: steps whose gate reads it} by "
            "mining every gate program's SOURCE for path literals, so a "
            "program that names its OWN DEFAULT OUTPUT in a module constant "
            "is recorded as a consumer of that output. metal_fill_emit is "
            "step 34's gate program and _REPORT_REL is exactly that "
            "constant: it is the FALLBACK the emitter writes to when no "
            "--json is supplied. Nothing in the repository reads the path. "
            "The flow's only gate invocation of the program passes an "
            "explicit --json reports/phase2/gates/cmp_fill_emit.json, which "
            "is a DIFFERENT file and is the one step 34's gate actually "
            "consumes. Declaring the phase3 path would also assert an "
            "UNCONDITIONAL production the flow itself denies: the runner "
            "half returns before invoking the emitter when there is no GDS "
            "to fill and when the density config declares no layers, and the "
            "emitter DISCLOSED_SKIPs when no KLayout runner is reachable, so "
            "an honest run of any of those branches would report MISSING. "
            "That is the same objection the dimension's own module docstring "
            "already sustains against declaring the DFT skip sentinels. "
            "Closing this needs the CONSUMER oracle taught to tell a gate "
            "program's own default-output constant from a path it reads — "
            "not a declaration, and not a change to W2's rule."
        ),
        evidence=(
            "producer default programs/metal_fill_emit.py:82 "
            "(_REPORT_REL = \"reports/phase3/cmp_fill_emit.json\") applied at "
            "programs/metal_fill_emit.py:133 and "
            "programs/metal_fill_emit.py:319 as "
            "`rep = Path(report) if report else (project / _REPORT_REL)`, so "
            "the constant is reached only when --json is absent; the runner "
            "invocation that reaches it is "
            "programs/phase3_one_shot_runner.py:22551 "
            "(`\"--cell\", top, \"--in-place\"],` — the last argv element, so "
            "the whole argv is visible and carries no --json), guarded by the "
            "two early returns at "
            "programs/phase3_one_shot_runner.py:22525-22527 "
            "(\"no GDS to fill\" / \"metal_fill_density config has no "
            "layers\"). The competing path the gate really reads is "
            "flow/phase1_phase2_phase3.yaml::\"metal_fill_emit . "
            "--verify-only --json "
            "reports/phase2/gates/cmp_fill_emit.json\". The oracle rule that "
            "conflates the two is "
            "programs/tests/matrix_d7_artifact_graph.py::"
            "`for lit in program_literals(prog)` (the mining loop of "
            "_gate_consumers). "
            # vibe-ic#1289/#1290 — CONTENT anchors, not line numbers. BOTH of
            # the citations above were written by line and BOTH had rotted by
            # 2026-08-15, in the two different ways this notation exists to
            # end. The yaml citation named 4242 and the flow grew 40 lines
            # above it, so 4242 now reads a comment and `validate()` reported
            # the citation unresolvable — a HARD red on
            # test_waivers_meet_the_registry_standard. The oracle citation
            # named 1074-1085, which held exactly that loop when it was
            # written (9167b162e) and now holds the body of a DIFFERENT
            # function, `flow_consumers`; `_gate_consumers` has moved to 1184
            # and its `for lit in program_literals(prog)` to 1190. That
            # citation still RESOLVED — `flow_consumers` calls
            # `gate_input_paths`, a token this waiver also names in
            # `gate_input_paths("34")` — so it went on READING as evidence
            # while pointing at unrelated code, which is the worse of the two
            # failures because nothing reports it.
            # Historical numbers above carry no leading colon on purpose: a
            # bare `:NNNN` inherits the last-named file and would be graded as
            # a live citation.
            #
            # The remaining `path:line` citations in this entry are NOT
            # converted, and the reason is measured rather than editorial: a
            # content anchor must resolve to exactly ONE line, and
            # `rep = Path(report) if report else (project / _REPORT_REL)`
            # occurs twice in metal_fill_emit.py (at 133 and 319 — the pair is
            # the point of the claim) while "no GDS to fill" occurs twice in
            # phase3_one_shot_runner.py. Both would be refused as AMBIGUOUS by
            # this registry's own rule, so the line form is the only form
            # available there.
            "MEASURED 2026-08-14 on the rebased tree: "
            "`grep -rn cmp_fill_emit flow/ programs/*.py` names "
            "reports/phase3/cmp_fill_emit.json in metal_fill_emit.py alone, "
            "and matrix_d7_artifact_graph.gate_input_paths(\"34\") contains "
            "no cmp_fill_emit entry at all — only "
            "input/pdk/bridge/cmp_fill_targets.json and "
            "signoff/cmp_fill_targets.json, which are different artefacts."
        ),
    ),
)


_BY_KEY: Dict[Tuple[str, int], Waiver] = {w.key: w for w in WAIVERS}


def waiver_for(step_id: StepId, dim: int) -> Optional[Waiver]:
    """The waiver at ``(step_id, dim)``, or ``None``. Accepts int or str ids."""
    return _BY_KEY.get((flowref.normalize_id(step_id), int(dim)))


def waivers_for_dim(dim: int) -> Tuple[Waiver, ...]:
    """Every waiver of one dimension, in registry order."""
    return tuple(w for w in WAIVERS if w.dim == int(dim))


def is_waived(step_id: StepId, dim: int) -> bool:
    return waiver_for(step_id, dim) is not None


def validate(waiver: Waiver) -> Tuple[str, ...]:
    """Return the list of problems with *waiver*; empty tuple means valid.

    Used by the meta-test. Kept as a function (not an ``__post_init__``) so a
    bad waiver produces a readable aggregate failure instead of an import-time
    explosion that hides every other problem.

    Reads the filesystem, via :func:`citation_problems`: a citation is a claim
    about this commit, and the only way to grade it is to open the file. The
    length floors below say a reason is long enough to be an argument; they
    never said the argument was true, and for a fortnight every dimension-7
    citation was false while this function returned ``()``.
    """
    problems = []
    if waiver.dim not in range(1, 9):
        problems.append(f"dim {waiver.dim!r} is not in 1..8")
    if not flowref.has_step(waiver.step_id):
        problems.append(f"step {waiver.step_id!r} is not declared in the flow yaml")
    reason = (waiver.reason or "").strip()
    evidence = (waiver.evidence or "").strip()
    if not reason:
        problems.append("reason is empty")
    elif len(reason) < MIN_REASON_LEN:
        problems.append(
            f"reason is {len(reason)} chars, under the {MIN_REASON_LEN}-char "
            f"floor — say what a program cannot decide and why"
        )
    for bad, rx in _FORBIDDEN_RE:
        if rx.search(reason):
            problems.append(f"reason contains the non-reason phrase {bad!r}")
    if not evidence:
        problems.append("evidence is empty")
    elif len(evidence) < MIN_EVIDENCE_LEN:
        problems.append(
            f"evidence is {len(evidence)} chars — needs a path:line, a measured "
            f"value, or a decision reference"
        )
    problems.extend(citation_problems(waiver))
    return tuple(problems)


def xfail_mark(step_id: StepId, dim: int):
    """The pytest mark for ``(step_id, dim)``, or ``None`` when not waived.

    Exists so that ``strict=True`` is decided HERE, once, instead of eight
    times by eight agents. A non-strict ``xfail`` rots silently forever: the
    gap gets fixed, the test starts passing, and nobody is told the waiver is
    now a lie. With ``strict=True`` an XPASS turns the suite red and forces the
    waiver's removal — that is the entire anti-rot mechanism, and it is not a
    per-module style choice.

    Usage::

        mark = waivers.xfail_mark(sid, 4)
        if mark:
            request.applymarker(mark)

    or at collection time::

        pytest.param(sid, marks=[m] if (m := waivers.xfail_mark(sid, 4)) else [])
    """
    import pytest  # local import: the substrate stays importable without pytest

    w = waiver_for(step_id, dim)
    if w is None:
        return None
    return pytest.mark.xfail(strict=True, reason=w.xfail_reason)


__all__ = [
    "Waiver",
    "WAIVERS",
    "xfail_mark",
    "waiver_for",
    "waivers_for_dim",
    "is_waived",
    "validate",
    "citation_problems",
    "FORBIDDEN_REASON_SUBSTRINGS",
    "MIN_REASON_LEN",
    "MIN_EVIDENCE_LEN",
    "MIN_ANCHOR_LEN",
    "MAX_ANCHOR_LINE_HITS",
    "MAX_CITATION_SPAN",
]
