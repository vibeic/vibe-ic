#!/usr/bin/env python3
"""Per-VIEW timing rows out of STA artefacts. The domain half of the split.

WHY PER VIEW, AND NOT PER DESIGN
================================
A design does not have "a" WNS. It has a timing MATRIX — mode x corner x check
— and the worst number in that matrix is a different fact from each cell of it.
Collapsing the matrix to a single WNS is how a multi-corner claim quietly
becomes a single-corner claim: nobody decides to drop the slow corner, the
report simply has one row and the row that would have failed is not in it.

So every row this module emits carries the full `scope` from
`docs/PPA_INTERFACES.md` §2 — stage, mode, process, voltage, temperature,
rc_corner, clock, check — because a number without them cannot be compared with
anything, and two numbers whose scope differs are not a winner and a loser but
an UNDETERMINED comparison.

THE PARSING IS NOT HERE
=======================
`_ppa.backends.opensta` turns text into numbers and decides nothing else. This
module decides what those numbers MEAN: which status a row carries, which view
a section belongs to, and when a number must be withheld. That is the split
`docs/PPA_INTERFACES.md` §4 freezes, and it is what lets a second timing engine
be added by writing one backend and changing no rule here.

WHAT THIS MODULE REFUSES TO DO
==============================
* **Return rc=1.** This is an EXTRACTOR. rc=1 is a claim about silicon, and an
  extractor has no claim to make: whether a design's timing is CLOSED is asked
  by `_ppa.feasibility` and by `sta_corner_record_completeness_check.py`.
  Deciding it a second time here is the duplication the backend/domain split
  exists to prevent, and it would put a verdict in a module a future author
  would have to remember to keep in step with the real gate.
* **Turn a missing view into a passing row.** A view that was not analysed is
  `NOT_MEASURED` with a reason and no `value` key at all. It is never `0`,
  never `-1`, never omitted (§2: "A report prints the literal NOT_MEASURED
  row; it does not omit it").
* **Read the no-paths sentinel as met timing.** See `_withhold_reason`.
* **Guess a scope field.** An unknown stage, mode, voltage or temperature is
  OMITTED from `scope` with the reason recorded in `scope_gaps`. A fabricated
  scope is worse than an absent one: it makes two incomparable numbers look
  comparable, which is the exact failure `scope` was introduced to stop.
* **Write a scope key as `null`.** Until v1.11.69 this module emitted all eight
  keys always, `null` for the ones it could not establish, on the stated ground
  that "an omitted key and a null key are different claims to a reader". They
  are -- and only one of them is SAFE, because `null == null`: two records that
  could not read their corner compared as the SAME corner. `PPA_INTERFACES` §2
  has said so in writing since v1.11.53 ("A `scope` key that is present and
  null is worse than one that is absent... is OMITTED and the reason is
  recorded outside `scope`"), and `_ppa/metrics.validate` enforces it as
  `SCOPE_SENTINEL`. Two lanes held opposite rules; the one that can REFUSE is
  the rule. MEASURED before the change, over 12 real run trees on this host:
  152 rows refused `SCOPE_SENTINEL`, all of them from this module.
* **Derive a number and call it measured.** OpenSTA's `wns` is
  `min(0, worst_slack)`. If the report printed no `wns` line, the wns row is
  NOT_MEASURED — it is not computed from the worst slack. §3: hash the value
  you PARSED.

EXIT CODES (`docs/PPA_INTERFACES.md` §1)
  0  at least one MEASURED row was extracted
  2  UNDETERMINED — no STA artefact, or none of them yielded a measurement.
     Printed with a `[CANNOT CHECK]` marker so a 2 can never read as a silent
     skip, and never mapped to PASS by anything downstream.
  3  BAD INVOCATION — the project path does not exist. Never a design FAIL.
  1  never returned; see above.

chip/PDK/vendor-AGNOSTIC: no design, IC, PDK, vendor or corner-name literal
drives any row. Corner identity, roles and PVT all come from the run's own
artefacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _ppa import canonical_json as cj                       # noqa: E402
from _ppa.backends import opensta                           # noqa: E402

try:                                                        # noqa: E402
    import _sta_basis                                       # the ONE stamp reader
except Exception:                                           # pragma: no cover
    _sta_basis = None
try:                                                        # noqa: E402
    from _atomic_artefact import write_text as _atomic_write_text
except Exception:                                           # pragma: no cover
    _atomic_write_text = None

__all__ = [
    "SCHEMA", "RC_OK", "RC_UNDETERMINED", "RC_BAD_INVOCATION",
    "MEASURED", "NOT_MEASURED", "INVALID",
    "Row", "timing_rows", "rows_from_report", "row_digest", "main",
]

SCHEMA = "vibeic.ppa.metric.v1"
UNIT_NS = "ns"

#: The metrics a reported view is expected to carry. Every one of them gets a
#: row for every view, MEASURED or NOT_MEASURED — never an ABSENT row.
#:
#: An omitted row and a met row are not the same fact, but they LOOK the same to
#: anything that scans a table for violations and finds none. `report_wns` being
#: absent from a report means OpenSTA was never asked for it, which is exactly
#: the "unqueried is indistinguishable from met" disease this lane exists to
#: cure — so it is stated, in the table, as a row.
_VIEW_METRIC_KINDS = ("worst_slack", "wns", "tns")

RC_OK, RC_UNDETERMINED, RC_BAD_INVOCATION = 0, 2, 3

MEASURED = "MEASURED"
NOT_MEASURED = "NOT_MEASURED"
INVALID = "INVALID"

#: `STA_BASIS:` stamp -> measurement STAGE. The stamp is prefix-matched to a
#: coarse basis by `_sta_basis.normalise_basis`, which deliberately maps
#: POST_ROUTE_SPEF and POST_ROUTE_NO_SPEF to one value; those are two different
#: stages for a metric (one has extracted parasitics behind it and one does
#: not), so the fine mapping is made here on the RAW stamp.
_STAGE_BY_STAMP = {
    "POST_ROUTE_SPEF": "post_route_extracted",
    "POST_ROUTE_NO_SPEF": "post_route_no_extraction",
    "PRE_LAYOUT_ESTIMATE": "pre_layout_estimate",
}

#: Where this flow writes sign-off STA. Directories, not files: every
#: `sta*.rpt` under them is read, so a new corner report is picked up without a
#: change here. Ordered, and every hit is globbed and SORTED, so two runs over
#: one tree produce rows in the same order and therefore the same digests.
_STA_DIRS = (
    "phase3/stage3/sta",
    "reports/phase3/sta",
    "reports/phase3",
)
_STA_GLOB = "sta*.rpt"

#: Role-bearing corner declarations. ONLY these are read.
#:
#: `corners_available` / `corners_extracted` / the `pvt_matrix` corner list are
#: AVAILABILITY, not configuration — `nom` is extracted on every run and
#: deliberately never analysed, because setup signs off at the slow corner and
#: hold at the fast one. Treating availability as configuration would emit a
#: NOT_MEASURED row for a corner nobody ever intended to analyse, on every
#: healthy run. That distinction is `sta_corner_record_completeness_check.py`'s
#: measured lesson and it is honoured, not re-derived.
_PROCESS_STANCE = (
    "reports/phase3/mcorner_ocv_stance.json",
    "reports/phase3/sta/mcorner_ocv_stance.json",
)
_RC_STANCE = (
    "reports/phase3/multi_corner_spef_stance.json",
    "reports/phase3/sta/multi_corner_spef_stance.json",
)
_PVT_MATRIX = (
    "phase2/stage2/constraints/pvt_matrix.json",
    "constraints/pvt_matrix.json",
    "phase3/stage3/constraints/pvt_matrix.json",
)

#: The ONLY scope keys a timing row may carry beyond the eight, and the metric
#: that may carry them. Declared here so the schema, the test and the emitter
#: cannot drift: an undeclared scope key silently makes a record incomparable
#: to every other record, which is the failure mode the eight exist to prevent,
#: so the set of permitted extras is closed and named rather than left open.
_PATH_SCOPE_KEYS = ("path_startpoint", "path_endpoint", "path_ordinal")
_PATH_METRIC_SUFFIX = ".worst_path_slack_ns"

_SCOPE_KEYS = ("stage", "mode", "process", "voltage_v", "temperature_c",
               "rc_corner", "clock", "check")

Row = Dict[str, Any]

_PARSER_DIGEST_CACHE: Dict[str, Optional[str]] = {}


def _parser_identity() -> Tuple[str, Optional[str]]:
    """The parser that produced a row, and the hash of its bytes.

    The backend, not this module: `source.parser` answers "what turned the text
    into this number", and if the answer changes the number can change with it.
    """
    p = Path(opensta.__file__).resolve()
    name = "_ppa/backends/" + p.name
    if name not in _PARSER_DIGEST_CACHE:
        try:
            _PARSER_DIGEST_CACHE[name] = (
                "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest())
        except OSError:                                      # pragma: no cover
            _PARSER_DIGEST_CACHE[name] = None
    return name, _PARSER_DIGEST_CACHE[name]


def _first_existing(project: Path, rels: Sequence[str]) -> Optional[Path]:
    for rel in rels:
        p = project / rel
        if p.is_file():
            return p
    return None


def _load_json(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """A JSON object, or None. An unreadable file and an absent one are both
    None here, but the CALLER never turns either into a clean row — the only
    thing a missing declaration can do is remove a NOT_MEASURED row it would
    otherwise have demanded, never add a passing one."""
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _rel(project: Path, p: Path) -> str:
    try:
        return str(p.relative_to(project))
    except ValueError:                                       # pragma: no cover
        return str(p)


def discover_reports(project: Path,
                     collapsed: Optional[List[Tuple[Path, Path]]] = None
                     ) -> List[Path]:
    """Every sign-off STA report under this project, de-duplicated and sorted.

    Sorted because row order feeds document identity: an unsorted glob makes the
    same tree hash two ways on two filesystems.

    DE-DUPLICATED BY PATH. Byte equality is DETECTED here and decided
    elsewhere -- see the comment below, and `collapse_declared_mirrors`.

    `_STA_DIRS` names three directories and this flow's runner publishes each
    report into TWO of them, as separate files with identical bytes -- measured
    on a real run, all three sign-off reports satisfy
    `sha256(phase3/stage3/sta/X.rpt) == sha256(reports/phase3/X.rpt)`.
    De-duplicating on the resolved path alone (which is all this did until
    v1.11.33) sees two files and reads both, so EVERY row was emitted twice and
    all 20 (metric, scope) groups in the document collided.

    THIS DOCSTRING SAID "DE-DUPLICATED BY CONTENT" AND THE CODE HAD STOPPED
    DOING THAT (v1.11.57). A comment that states the opposite of the code is
    worse than no comment: it is read as the contract. It was, and it cost
    three red arms in `test_ppa_layer_timing_view_dedup.py`, which were written
    against this sentence rather than against the function.

    Every byte-identical pair is appended to `collapsed` so the caller can say
    what it found instead of finding it quietly. NOTHING IS DROPPED HERE.
    """
    candidates: Dict[str, Path] = {}
    for rel in _STA_DIRS:
        d = project / rel
        if not d.is_dir():
            continue
        for f in sorted(d.glob(_STA_GLOB)):
            if f.is_file():
                candidates.setdefault(str(f.resolve()), f)

    # BYTE EQUALITY DETECTS, IT DOES NOT DECIDE. Two lanes fixed F-10
    # independently and their tests assert opposite things:
    #
    #   "a report published into two directories is ONE artefact and ONE
    #    reading -- the second copy is the publisher's, not the tool's"
    #   "two DIFFERENT sign-off reports whose bytes happen to agree are TWO
    #    measurements; collapsing them by digest would delete evidence"
    #
    # Both are true, and NOTHING IN THE BYTES TELLS THEM APART. So the bytes no
    # longer drop anything. The producer's own declaration
    # (`collapse_declared_mirrors`) drops declared mirrors, which is the case
    # the first quote describes and which the runner now writes down; an
    # UNDECLARED byte-identical pair is reported and BOTH are kept, because
    # deleting a real second measurement is the worse error of the two -- a
    # double count is visible in the document and a deletion is not.
    #
    # An undeclared pair is itself a finding: the producer published a mirror
    # without saying so. `collapsed` carries it so the caller can say that.
    by_digest: Dict[str, Path] = {}
    kept: List[Path] = []
    for key in sorted(candidates):
        f = candidates[key]
        digest = opensta.file_digest(f)
        if digest is None:
            # Unhashable is NOT a duplicate. It is read, and `timing_rows`
            # gives it an INVALID row if it cannot be opened either.
            kept.append(f)
            continue
        first = by_digest.get(digest)
        if first is not None and collapsed is not None:
            collapsed.append((f, first))
        else:
            by_digest.setdefault(digest, f)
        kept.append(f)
    return kept


#: Where a step records that one artefact it wrote is a COPY of another.
#: Written by `phase3_one_shot_runner._publish_artefact_mirror`.
_MIRROR_MANIFEST = "reports/phase3/artefact_mirrors.json"


def collapse_declared_mirrors(project: Path, reports: List[Path]
                              ) -> Tuple[List[Path], List[str]]:
    """Drop reports the RUN ITSELF declared to be copies. Returns (kept, notes).

    MEASURED DEFECT: this flow publishes each sign-off STA report into two of
    the directories `_STA_DIRS` names, so one measurement arrived here as two
    byte-identical files:

        sha256(phase3/stage3/sta/sta_spef_based.rpt)
            == sha256(reports/phase3/sta_spef_based.rpt)

    Every row was therefore emitted twice under one scope, and ALL 20
    (metric, scope) groups in the timing document collided as
    CONFLICTING_RECORD -- correctly, because two numbers claiming to be the
    same fact IS a conflict. One fact was arriving as two records.

    WHY HERE AND NOT IN THE EMITTER: both locations are load-bearing. Five
    shipped checkers read the `reports/phase3/` copy and the step writes the
    `phase3/stage3/sta/` one; dropping either breaks a consumer.

    WHY NOT BY CONTENT HASH: a genuine SECOND measurement that happens to agree
    to the byte is a real reading of a real artefact, and collapsing it would
    erase evidence -- exactly the silence this lane exists to remove. Identical
    bytes are not proof of a copy. So the collapse is driven by the run's OWN
    declaration: only a pair the producing step RECORDED as a mirror collapses,
    and only while both files still match the digest recorded at copy time.

    DEGRADES LOUDLY: no manifest, or a mirror whose content has diverged from
    its source, means nothing is collapsed and the note says why. "I could not
    tell" must not look like "there was nothing to collapse".
    """
    notes: List[str] = []
    manifest = project / _MIRROR_MANIFEST
    if not manifest.is_file():
        return reports, notes
    doc = _load_json(manifest)
    entries = (doc or {}).get("mirrors")
    if not isinstance(entries, list):
        notes.append("mirror manifest %s declares no `mirrors` list; nothing "
                     "collapsed" % _MIRROR_MANIFEST)
        return reports, notes

    by_rel = {_rel(project, f): f for f in reports}
    drop: Dict[str, str] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        mirror, of, want = e.get("mirror"), e.get("of"), e.get("sha256")
        if not (isinstance(mirror, str) and isinstance(of, str)):
            continue
        if mirror not in by_rel:
            continue
        if of not in by_rel:
            # The thing it mirrors is not in scope, so this copy is the only
            # reading present. Keeping it is the honest answer.
            notes.append("declared mirror %s kept: its source %s is not among "
                         "the artefacts read" % (mirror, of))
            continue
        digests = {r: opensta.file_digest(by_rel[r]) for r in (mirror, of)}
        if not isinstance(want, str) or set(digests.values()) != {want}:
            notes.append(
                "declared mirror %s NOT collapsed: it and %s no longer both "
                "match the digest recorded when the copy was made, so they are "
                "two contents and therefore two facts" % (mirror, of))
            continue
        drop[mirror] = of

    if not drop:
        return reports, notes
    kept = [f for f in reports if _rel(project, f) not in drop]
    for mirror, of in sorted(drop.items()):
        notes.append("collapsed declared mirror %s (a copy of %s made by the "
                     "run itself); it contributes no second row" % (mirror, of))
    return kept, notes


def _stage_for(report: opensta.Report) -> Tuple[Optional[str], Optional[str]]:
    """(stage, gap-reason). Unknown is null and says why — never a guess.

    HISTORY, kept because it is why this function refuses instead of guessing.
    MEASURED at v1.11.33 (`grep -n 'puts .*STA_BASIS'
    phase3_one_shot_runner.py`): the SINGLE-corner emitter stamped
    `STA_BASIS: POST_ROUTE_SPEF`, and the two MULTI-corner sign-off emitters —
    the ones that write `sta_spef_multicorner.rpt` and `sta_mcorner_ocv.rpt` —
    stamped nothing at all, so 48 of 56 timing rows on one real run were
    refused as SCOPE_INCOMPLETE. Those two emitters now stamp per stanza, in
    the step's own tool, which is where the netlist/liberty/SPEF a stanza read
    is actually known.

    Nothing here changed for it, and nothing here should: inferring
    `post_route_extracted` from the filename would let a pre-layout estimate be
    compared against sign-off evidence the moment somebody adds a pre-layout
    report to the same directory, so an unstamped report still degrades LOUDLY.
    """
    stamp = report.basis_stamp
    if not stamp:
        return None, "report carries no STA_BASIS stamp"
    fine = _STAGE_BY_STAMP.get(stamp.upper())
    if fine:
        return fine, None
    coarse = (_sta_basis.normalise_basis(stamp)
              if _sta_basis is not None else None)
    if coarse == "PRE_LAYOUT":
        return "pre_layout_estimate", None
    if coarse == "POST_ROUTE":
        # Post-route, but the stamp does not say whether parasitics were
        # extracted. Say exactly that rather than picking the flattering one.
        return "post_route_unspecified_extraction", None
    return None, "unrecognised STA_BASIS stamp %r" % stamp


def _mode_for(project: Path) -> Tuple[Optional[str], Optional[str]]:
    """The run's timing MODE, from `pvt_matrix.json`'s own `modes` list.

    Exactly one declared mode is attributable to a report that never names one.
    Two or more is not: the reports carry no mode marker, so choosing between
    them would be invention. Zero declared modes is likewise null.
    """
    pvt = _load_json(_first_existing(project, _PVT_MATRIX))
    if not pvt:
        return None, "no pvt_matrix.json declaring a mode"
    modes = pvt.get("modes")
    if not isinstance(modes, list) or not modes:
        return None, "pvt_matrix.json declares no modes"
    modes = [str(m) for m in modes]
    if len(set(modes)) != 1:
        return None, ("pvt_matrix.json declares %d modes (%s) and the STA "
                      "reports name none" % (len(set(modes)), ",".join(sorted(set(modes)))))
    return modes[0], None


def _ident(value: Optional[str]) -> Optional[str]:
    """A corner identifier, case-normalised. See `_scope`."""
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


#: The RC-corner vocabulary the extraction step actually emits, as a CLOSED set
#: (`phase3_one_shot_runner._SPEF_CORNERS`). Closed rather than "whatever token
#: sits before `.spef`": an open rule turns `chip_top.pnr.spef` into an RC
#: corner named `pnr`, and a corner nobody extracted is worse than none.
_RC_CORNER_TOKENS = ("min", "nom", "max")


def _rc_corner_from_spef(spef: Optional[str]) -> Optional[str]:
    """The RC corner a parasitic file NAMES, or None.

    `<top>.<corner>.spef` with `<corner>` in the closed vocabulary is the
    extraction step's own naming, so reading the corner back out of it is
    reading a stamp, not guessing from a filename. Anything else -- including
    the un-cornered `<top>.spef` the single-corner STA step reads -- establishes
    NOTHING. Two runs may extract the un-cornered file with different models,
    and a corner inferred from a name that does not carry one is exactly the
    invented identity `scope` exists to prevent.
    """
    if not isinstance(spef, str) or not spef.strip():
        return None
    stem = spef.strip().replace("\\", "/").rsplit("/", 1)[-1]
    if not stem.lower().endswith(".spef"):
        return None
    parts = stem[: -len(".spef")].split(".")
    if len(parts) < 2:
        return None
    token = parts[-1].strip().lower()
    return token if token in _RC_CORNER_TOKENS else None


#: Why a scope key is ABSENT, when the caller has no more specific sentence.
#: Every omission is explained -- an unexplained absent key and a `null` one are
#: the same silence, and the whole point of omitting is that the reason moves
#: somewhere a reader can see it (`scope_gaps`) instead of somewhere two records
#: can silently compare equal (`scope`).
_SCOPE_OMISSION_REASON = {
    "stage": "the artefact carries no stamp saying which stage it analysed",
    "mode": "nothing in this project attributes a timing mode to this artefact",
    "process": "this section names no process corner",
    "voltage_v": "no liberty path was available to read a supply voltage from",
    "temperature_c": "no liberty path was available to read a temperature from",
    "rc_corner": ("this section names neither an RC corner nor the parasitic "
                  "file it read"),
    "clock": ("not_applicable: this row is the DESIGN-WIDE figure and is not "
              "scoped to one clock; the per-clock evidence is "
              "`timing.*.worst_path_slack_ns`, which carries the clock it names"),
    "check": "this section labels neither a setup nor a hold check",
}


def _scope(stage: Optional[str], mode: Optional[str], process: Optional[str],
           voltage_v: Optional[float], temperature_c: Optional[float],
           rc_corner: Optional[str], clock: Optional[str],
           check: Optional[str]) -> Dict[str, Any]:
    """The scope keys this artefact ESTABLISHED, in the frozen order.

    A key the producer could not establish is ABSENT, never `null`. Until
    v1.11.69 this returned all eight always, and the reasoning written here was
    that "an omitted key and a null key are different claims to a reader, and
    only one of them is true". Both halves of that sentence are right and the
    conclusion drawn from it was wrong: `null == null`, so two records that
    could not read their RC corner compared as records taken at the SAME RC
    corner, and a head-to-head could put them side by side. An absent key
    cannot do that -- `_ppa/metrics.record_key` hashes the scope it is given, so
    two records missing different keys hash differently and stay incomparable,
    which is the honest answer.

    The claim the null was carrying is not lost. It moves to `scope_gaps`
    (`_gaps_for`), which is OUTSIDE scope and therefore cannot make anything
    compare equal. That is `PPA_INTERFACES` §2, and `_ppa/metrics.validate`
    refuses the null spelling as `SCOPE_SENTINEL`.

    `process` and `rc_corner` are case-normalised. They are IDENTIFIERS, and a
    view the process stance spells `SS` while its liberty stem spells `ss` is
    one view: leaving both spellings in would make §2's rule ("two numbers are
    comparable only if their `scope` matches") report two identical corners as
    incomparable. The verbatim spelling survives in `source.raw`.
    """
    full = {"stage": stage, "mode": mode, "process": _ident(process),
            "voltage_v": voltage_v, "temperature_c": temperature_c,
            "rc_corner": _ident(rc_corner), "clock": clock, "check": check}
    # `""` as well as None: the empty string is §6.1's third sentinel and
    # `"" == ""` compares equal exactly the way `null == null` does.
    return {k: v for k, v in full.items() if v is not None and v != ""}


def _gaps_for(scope: Dict[str, Any],
              base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """`base` plus a reason for every scope key `_scope` left out.

    The caller's own sentence always wins: it knows WHY this particular
    artefact was silent, and `_SCOPE_OMISSION_REASON` is only the fallback for
    a key nobody explained. What this function guarantees is that no key is
    absent WITHOUT a reason -- an unexplained hole in a scope is the same
    invisible claim as a `null`, moved one field over.
    """
    out = dict(base or {})
    for key in _SCOPE_KEYS:
        if key not in scope and key not in out:
            out[key] = _SCOPE_OMISSION_REASON[key]
    return out


def _path_names(obs: Any) -> Tuple[Optional[str], Optional[str]]:
    """The (startpoint, endpoint) pair this observation names, or (None, None).

    One reader, so `_path_scope` and the collision pre-scan in
    `rows_from_report` cannot come to different conclusions about whether a
    path was named -- which would put a row in the "named" bucket and then
    scope it by ordinal, or the reverse.
    """
    start = getattr(obs, "startpoint", None)
    end = getattr(obs, "endpoint", None)
    return (start, end) if (start and end) else (None, None)


def _path_scope(base: Dict[str, Any], obs: Any, ordinal: int,
                names_identify: bool = True) -> Dict[str, Any]:
    """`base` plus the identity of ONE reported path.

    THE ENDPOINTS WHEN THE ARTEFACT NAMES THEM AND THE NAMES TELL THE PATHS
    APART, THE ORDINAL OTHERWISE. A path is identified by where it starts and
    ends, and those names are the same in two runs of one design -- so two arms'
    records for one path carry equal scope and remain comparable, which is the
    whole point of scope.

    An ORDINAL is a position in a printed list. It distinguishes the rows inside
    one document, which is what stops the collision, but it is NOT an identity:
    if a tool prints the same paths in a different order the ordinals move, and
    two arms would be compared across different paths. So it is used only when
    the names cannot do the job, and then the cross-arm comparison REFUSES on
    differing scope -- which is the honest answer, because a path that cannot be
    shown to be the same path must not be compared as if it were.

    `names_identify=False` IS THE CASE THIS FUNCTION MISSED UNTIL v1.11.69.
    It checked whether the artefact PRINTED two names, never whether the two
    names it printed were UNIQUE in the view. OpenSTA prints one
    `Startpoint:`/`Endpoint:` pair per reported path and nothing stops two
    reported paths of one group from sharing both -- and when they do, the
    "identity" is shared, the rows collide, and the index refuses the second as
    SAME_ARTEFACT_TWO_VALUES: one artefact, one scope, two numbers. REPRODUCED
    on this checkout with a two-path stamped report; MEASURED at 0 occurrences
    across 2572 path identities in every STA report on this host, so it is a
    hole in the rule and not a defect anyone has hit yet. The caller decides,
    because only the caller can see the whole section.

    Both keys are never emitted together: adding a volatile key next to a stable
    one would make the stable one useless. When the names do not identify, they
    are DROPPED rather than kept alongside -- a name that two rows share is not
    a weaker identity, it is a wrong one, and `source.raw` still carries the
    line the row came from for anyone reading by hand.
    """
    out = dict(base)
    start, end = _path_names(obs)
    if start and end and names_identify:
        out["path_startpoint"] = start
        out["path_endpoint"] = end
    else:
        out["path_ordinal"] = ordinal
    return out


def _source(project: Path, path: Optional[Path], sha: Optional[str],
            line: Optional[int], raw: Optional[str]) -> Dict[str, Any]:
    parser, parser_sha = _parser_identity()
    return {
        "path": _rel(project, path) if path is not None else None,
        "sha256": sha,
        "tool": opensta.TOOL,
        # The report does not record which build produced it, and this program
        # will not ask a container at parse time to find out — a metric's
        # provenance must be reproducible from the artefact alone.
        "tool_commit": None,
        "parser": parser,
        "parser_sha256": parser_sha,
        "line": line,
        "raw": raw,
    }


def _row(metric: str, status: str, scope: Dict[str, Any],
         source: Dict[str, Any], *, value: Optional[float] = None,
         reason: Optional[str] = None,
         scope_gaps: Optional[Dict[str, str]] = None) -> Row:
    """One canonical metric record.

    A non-MEASURED row carries NO `value` key. Not `null`, not `0`: absent, so
    that a consumer which reads `row["value"]` raises instead of quietly
    comparing a sentinel (§2, "No numeric sentinels").
    """
    row: Row = {"schema": SCHEMA, "metric": metric, "status": status}
    if status == MEASURED:
        if value is None:                                    # pragma: no cover
            raise ValueError("a MEASURED row must carry a value")
        row["value"] = value
        row["unit"] = UNIT_NS
    else:
        row["reason"] = reason or "unspecified"
        row["unit"] = UNIT_NS
    row["scope"] = scope
    if scope_gaps:
        row["scope_gaps"] = dict(sorted(scope_gaps.items()))
    row["source"] = source
    return row


def row_digest(row: Row) -> str:
    """`sha256:<hex>` of a row, via the one serializer (§3)."""
    return cj.digest_of(row)


#: What a `worst_slack` line that IS the infinity sentinel carries.
_SENTINEL_REASON = "no_paths_analysed: OpenSTA reported the infinity sentinel"


def _withhold_reason(check_no_paths: bool, kind: str,
                     value: Optional[float]) -> Optional[str]:
    """Why a parsed number must NOT be published as a measurement.

    THE FOUNDING DEFECT OF THIS CORPUS, and the reason this function exists.
    `worst_slack` starts at infinity and takes the min over the analysed paths,
    so it is still infinity exactly when the path set was EMPTY. Three published
    reports in the tracked corpus had a whole body of::

        No paths found. / tns max 0.00 / wns max 0.00 / worst slack max INF

    The `0.00` there is `min(0, INF)` — arithmetic ABOUT infinity, carrying no
    independent evidence. It reads 0.00 *because nothing was analysed*, not
    because timing was met. Publishing it as a met +0.000 ns is precisely
    "an unreported view is indistinguishable from a met one", reproduced inside
    the reader that is supposed to prevent it.

    MEASURED against the real tool (OpenSTA 2.7.0 f21d4a3878, from the image
    family this checkout anchors), two designs, one liberty, one clock:

        design with real reg-to-reg paths     design with no timing paths
          tns max 0.00                          tns max 0.00
          wns max 0.00                          wns max 0.00
          worst slack max 0.19                  worst slack max INF

    The first two lines are BYTE-IDENTICAL. Timing met with +0.19 ns of slack,
    and nothing analysed at all, print the same summary -- both clamp to zero.
    The `worst slack` line is the ONLY thing that separates them, which is why
    the withholding decision is keyed on it and on nothing else.

    PER CHECK, never per report. A report routinely carries a real setup slack
    beside a hold analysis that found no paths, and withholding the setup
    summary because the HOLD view was empty would suppress a measurement that
    exists. Not hypothetical: that was this function's first shape, and the
    real-tool output above is what exposed it.

    A NEGATIVE summary is never withheld. It cannot be an echo of infinity, and
    suppressing evidence of a violation is the one error worse than publishing
    a phantom pass.
    """
    if not check_no_paths:
        return None
    if value is not None and value < 0:
        return None
    return ("no_paths_analysed_in_view: this view's worst slack was the "
            "infinity sentinel, so a non-negative %s is arithmetic from "
            "infinity and not evidence of met timing" % kind)


def rows_from_report(project: Path, path: Path, report: opensta.Report,
                     *, mode: Optional[str],
                     mode_gap: Optional[str]) -> List[Row]:
    """Every row a single parsed report supports."""
    rows: List[Row] = []
    stage, stage_gap = _stage_for(report)
    parser_src_sha = report.sha256

    if report.empty:
        _empty_scope = _scope(stage, mode, None, None, None, None, None, None)
        rows.append(_row(
            "timing.report", INVALID,
            _empty_scope,
            _source(project, path, parser_src_sha, None, None),
            reason="the STA artefact exists but is empty",
            scope_gaps=_gaps_for(_empty_scope, {
                k: v for k, v in
                (("stage", stage_gap), ("mode", mode_gap)) if v})))
        return rows

    for sec in report.sections:
        # ── the view's identity ────────────────────────────────────────────
        liberty = sec.liberty
        rc_corner = sec.rc_corner
        process = sec.process
        # Which parasitic file this view was timed against. Dialect A/B name it
        # on the banner; the unbannered dialect can only say so whole-file.
        spef = sec.spef
        if sec.banner is None:
            # Dialect C: one implicit section, and the whole-file stamps are
            # what describe it. Relating them is meaning, so the BACKEND left
            # it alone and it happens here.
            liberty = liberty or report.basis_liberty
            process = process or report.signoff_corner
            spef = spef or report.basis_spef
        pvt = opensta.parse_liberty_pvt(liberty)
        gaps: Dict[str, str] = {}
        if stage_gap:
            gaps["stage"] = stage_gap
        if mode_gap:
            gaps["mode"] = mode_gap
        for fld in ("voltage_v", "temperature_c"):
            if pvt.gaps.get(fld):
                gaps[fld] = "liberty %s: %s" % (
                    pvt.stem or "path absent", pvt.gaps[fld])
        # The banner's declared process label wins over the one implied by the
        # liberty stem: the label is what the run SAID it was analysing, and a
        # disagreement between them is information, not noise.
        if process is None and pvt.process is not None:
            process = pvt.process
        elif (process is not None and pvt.process is not None
                and process.lower() != pvt.process.lower()):
            gaps["process"] = (
                "banner declares process=%s but its liberty stem %s reads %s"
                % (process, pvt.stem, pvt.process))
        # THE RC AXIS IS AN AXIS. Only dialect A prints a `<x>-RC corner`
        # label, so every other dialect used to leave `rc_corner` unestablished
        # -- and two views timed against DIFFERENT parasitic files then carried
        # one identity and collided as if they contradicted each other. They do
        # not: a max-RC slack and a nominal-RC slack are two facts. The corner
        # is recoverable from the parasitic file the artefact NAMES, which is a
        # stamp the extraction step wrote, so read it.
        if rc_corner is None:
            rc_corner = _rc_corner_from_spef(spef)
        if rc_corner is None:
            gaps["rc_corner"] = (
                ("this report names the parasitic file %r, whose stem carries "
                 "no %s corner token; an RC corner is not inferred from a file "
                 "name that does not state one"
                 % (spef, "/".join(_RC_CORNER_TOKENS)))
                if spef else
                ("this report names neither an RC corner nor the parasitic "
                 "file it read, so which extraction it was timed against is "
                 "not recoverable from it"))

        # ── which CHECKS analysed nothing? Keyed per check, never per
        # report: an unbannered report carries BOTH checks in one section, and
        # a real setup slack must not be suppressed because hold was empty.
        no_paths_by_check = {
            (m.check or sec.check): True
            for m in sec.measurements if m.kind == "worst_slack" and m.no_paths}

        # Which check(s) this section is about. A banner says so outright; the
        # unbannered dialect is described only by the max/min labels on its own
        # numbers. A section that mentions neither is `unlabelled` — stated,
        # never silently attributed to setup.
        if sec.check is not None:
            checks = [sec.check]
        else:
            checks = sorted({m.check for m in sec.measurements if m.check})
            if not checks:
                checks = ["unlabelled"]

        for check in checks:
            scope = _scope(stage, mode, process, pvt.voltage_v,
                           pvt.temperature_c, rc_corner, None, check)
            # ONE gap map per view, so every row of the view explains the same
            # absences the same way. `clock` is absent here by DESIGN, not by
            # failure -- `report_worst_slack` is a design-wide figure -- and
            # `_SCOPE_OMISSION_REASON["clock"]` says exactly that.
            view_gaps = _gaps_for(scope, gaps)
            for kind in _VIEW_METRIC_KINDS:
                metric = "timing.%s.%s_ns" % (check, kind)
                m = next((x for x in sec.measurements
                          if x.kind == kind
                          and (x.check or sec.check or check) == check), None)
                if m is None:
                    rows.append(_row(
                        metric, NOT_MEASURED, scope,
                        _source(project, path, parser_src_sha, None, None),
                        reason=("not_reported: the artefact carries no %s line "
                                "for this view — the tool was not asked, or the "
                                "query failed" % kind),
                        scope_gaps=view_gaps))
                    continue
                src = _source(project, path, parser_src_sha, m.line, m.raw)
                if m.no_paths or m.value is None:
                    rows.append(_row(
                        metric, NOT_MEASURED, scope, src,
                        reason=(_SENTINEL_REASON if m.no_paths
                                else "the tool printed no usable number"),
                        scope_gaps=view_gaps))
                    continue
                why = _withhold_reason(
                    no_paths_by_check.get(check, False), m.kind, m.value)
                if why:
                    rows.append(_row(metric, NOT_MEASURED, scope, src,
                                     reason=why, scope_gaps=view_gaps))
                else:
                    rows.append(_row(metric, MEASURED, scope, src,
                                     value=m.value, scope_gaps=view_gaps))

        # ── per-CLOCK rows, from the only per-clock evidence there is ──────
        # `report_worst_slack` is design-wide; these path blocks name a path
        # group. They are a PARTIAL census (the emitter dumps the worst few), so
        # they get their own metric name and can never be mistaken for the
        # design-wide worst.
        ordinals: Dict[Tuple[str, str], int] = {}
        # WHICH NAMED PAIRS ACTUALLY IDENTIFY A PATH IN THIS SECTION. Counted
        # BEFORE any row is built, because the answer for the first path
        # depends on a path that has not been read yet. A pair printed twice
        # names two different measurements and therefore identifies neither.
        named_seen: Dict[Tuple[Any, ...], int] = {}
        for p in sec.paths:
            if p.slack is None or p.clock is None:
                continue
            start, end = _path_names(p)
            if not (start and end):
                continue
            ck = ({"max": "setup", "min": "hold"}.get(p.path_type or "")
                  or sec.check or "unlabelled")
            k = (start, end, p.clock, ck)
            named_seen[k] = named_seen.get(k, 0) + 1
        for p in sec.paths:
            if p.slack is None or p.clock is None:
                continue
            check = ({"max": "setup", "min": "hold"}.get(p.path_type or "")
                     or sec.check or "unlabelled")
            # WHICH PATH. The emitter dumps the worst FEW paths of a group, so
            # several of these land in one (clock, check) view with different
            # slacks. Until v1.11.33 they all carried the same scope, and a
            # metric named "worst path slack" therefore held three values for
            # one view -- ambiguous on its face, and refused as a conflict by
            # every consumer. The reading is not duplicated and the numbers do
            # not disagree: the SCOPE was missing the field that tells the
            # paths apart (PPA_INTERFACES §2.1, last paragraph).
            #
            # v1.11.53 added the endpoint names and v1.11.69 added the half
            # that was missing: names only identify a path if they are UNIQUE
            # in the view. Two reported paths sharing one (startpoint,
            # endpoint) pair rebuilt the original defect exactly -- one
            # artefact, one scope, two numbers -- and `named_seen` above is
            # what notices.
            key = (p.clock, check)
            ordinals[key] = ordinals.get(key, 0) + 1
            scope = _scope(stage, mode, process, pvt.voltage_v,
                           pvt.temperature_c, rc_corner, p.clock, check)
            start, end = _path_names(p)
            identifies = bool(start and end) and named_seen.get(
                (start, end, p.clock, check), 0) == 1
            path_scope = _path_scope(scope, p, ordinals[key], identifies)
            rows.append(_row(
                "timing.%s.worst_path_slack_ns" % check, MEASURED,
                path_scope,
                _source(project, path, parser_src_sha, p.line, p.raw),
                value=p.slack, scope_gaps=_gaps_for(path_scope, gaps)))
    return rows


def _declared_views(project: Path) -> List[Dict[str, Optional[str]]]:
    """(axis, corner, check) triples the run was CONFIGURED to analyse.

    Role-bearing declarations only — see `_PROCESS_STANCE` / `_RC_STANCE`. An
    availability list is not a configuration and is never read here.
    """
    out: List[Dict[str, Optional[str]]] = []
    proc = _load_json(_first_existing(project, _PROCESS_STANCE))
    if proc:
        for key, check in (("setup_process_corner", "setup"),
                           ("hold_process_corner", "hold")):
            val = proc.get(key)
            if isinstance(val, str) and val.strip():
                out.append({"axis": "process", "corner": val.strip(),
                            "check": check})
    rc = _load_json(_first_existing(project, _RC_STANCE))
    if rc:
        for key, check in (("setup_corner", "setup"), ("hold_corner", "hold")):
            val = rc.get(key)
            if isinstance(val, str) and val.strip():
                out.append({"axis": "rc", "corner": val.strip(),
                            "check": check})
    return out


def _covers(row: Row, decl: Dict[str, Optional[str]]) -> bool:
    """Does this row already account for a declared view?

    ANY status counts, not just MEASURED. A hold corner that WAS analysed and
    found no paths already has a row saying exactly that; adding a second row
    claiming it was "declared but not reported" would be false — it was
    reported, and the accurate reason is the one already on the table. This
    rule fires only for a view with NO row at all.

    Only rows that came from an artefact can cover a declaration
    (`source.path`), so one synthesised row can never satisfy another.
    """
    if not (row.get("source") or {}).get("path"):
        return False
    scope = row.get("scope") or {}
    if (scope.get("check") or "") != decl["check"]:
        return False
    field = "process" if decl["axis"] == "process" else "rc_corner"
    got = scope.get(field)
    return bool(got) and str(got).lower() == str(decl["corner"]).lower()


def timing_rows(project: Path) -> Tuple[List[Row], List[str]]:
    """Every per-view timing row this project's STA artefacts support.

    Returns `(rows, notes)`. `notes` carries what a human needs to read the
    result — which files were opened, and what was declared but never reported.
    """
    notes: List[str] = []
    # TWO LANES FIXED F-10 INDEPENDENTLY AND BOTH ARE KEPT, because they are
    # not the same mechanism and neither subsumes the other:
    #
    #   discover_reports(..., collapsed)   REPORTS byte-identical artefacts by
    #                                      CONTENT DIGEST and drops none of
    #                                      them. It catches duplicates nobody
    #                                      declared, which is the only thing
    #                                      that can catch a duplicate the
    #                                      producer does not know it made --
    #                                      but a hash cannot tell that copy
    #                                      from a second reading that agrees,
    #                                      so it reports and does not decide.
    #   collapse_declared_mirrors(...)     collapses what the RUN ITSELF wrote
    #                                      down as a copy, in
    #                                      reports/phase3/artefact_mirrors.json.
    #                                      It carries a REASON, and it still
    #                                      collapses a mirror whose bytes have
    #                                      since diverged in a header.
    #
    # Order is forced: discovery has to happen before anything can be dropped.
    # Both record what they dropped -- `collapsed` below, `mirror_notes` here --
    # because the hazard in either is a genuine SECOND measurement that happens
    # to look like the first, and a reader has to be able to see that it was
    # dropped and why.
    collapsed: List[Tuple[Path, Path]] = []
    reports = discover_reports(project, collapsed)
    reports, mirror_notes = collapse_declared_mirrors(project, reports)
    notes.extend(mirror_notes)
    mode, mode_gap = _mode_for(project)
    rows: List[Row] = []
    for f in reports:
        try:
            text = f.read_text(errors="replace")
        except OSError as exc:
            # Unreadable is NOT clean. It gets a row that says so.
            _unreadable_scope = _scope(None, mode, None, None, None, None,
                                       None, None)
            rows.append(_row(
                "timing.report", INVALID,
                _unreadable_scope,
                _source(project, f, opensta.file_digest(f), None, None),
                scope_gaps=_gaps_for(_unreadable_scope, {
                    "stage": "the artefact could not be read, so nothing in it "
                             "could stamp a stage"}),
                reason="the STA artefact could not be read: %s" % exc))
            notes.append("[CANNOT CHECK] unreadable: %s" % _rel(project, f))
            continue
        rep = opensta.parse_report(text, path=_rel(project, f),
                                   sha256=opensta.file_digest(f))
        rows.extend(rows_from_report(project, f, rep, mode=mode,
                                     mode_gap=mode_gap))
    notes.append("opened %d STA artefact(s): %s" % (
        len(reports), ", ".join(_rel(project, f) for f in reports) or "none"))
    for dup, first in collapsed:
        # REPORTED, NOT COLLAPSED. These two artefacts have the same bytes and
        # the run declared NEITHER of them a mirror of the other, so nothing
        # here can tell "the publisher wrote the same file twice" from "two
        # sign-off reports that happen to agree". Both are read and both count;
        # what is emitted is the FINDING, which is that the producer published
        # a mirror without saying so. Declared mirrors are collapsed by
        # `collapse_declared_mirrors` and they carry the producer's reason.
        notes.append(
            "undeclared byte-identical artefacts: %s and %s have the same "
            "bytes and neither is declared a mirror of the other in %s. BOTH "
            "were read and both count -- deleting a real second measurement is "
            "worse than double-counting one, because a double count is visible "
            "in this document and a deletion is not. The producer should "
            "declare the mirror."
            % (_rel(project, dup), _rel(project, first), _MIRROR_MANIFEST))

    # Declared-but-never-reported views become explicit NOT_MEASURED rows. A
    # view the run was configured to analyse and did not is the defect this
    # whole lane exists to make visible; leaving it out of the table would be
    # the same silence in a new place.
    reported = list(rows)          # snapshot: declared rows cannot cover each other
    for decl in _declared_views(project):
        if any(_covers(r, decl) for r in reported):
            continue
        field = "process" if decl["axis"] == "process" else "rc_corner"
        decl_scope = _scope(
            None, mode, decl["corner"] if field == "process" else None,
            None, None,
            decl["corner"] if field == "rc_corner" else None,
            None, decl["check"])
        rows.append(_row(
            "timing.%s.worst_slack_ns" % decl["check"], NOT_MEASURED,
            decl_scope,
            _source(project, None, None, None, None),
            scope_gaps=_gaps_for(decl_scope, {
                "stage": "no artefact reports this view at all, so nothing "
                         "stamps a stage for it"}),
            reason=("declared_but_not_reported: the run declared %s corner %r "
                    "for the %s check on the %s axis and no STA artefact "
                    "reports a slack for it"
                    % (decl["axis"], decl["corner"], decl["check"],
                       decl["axis"]))))
        notes.append("declared but not reported: %s corner %s (%s)"
                     % (decl["axis"], decl["corner"], decl["check"]))
    return rows, notes


def _document(project: Path, rows: List[Row], notes: List[str]) -> Dict[str, Any]:
    measured = [r for r in rows if r.get("status") == MEASURED]
    return {
        "schema": "vibeic.ppa.timing_rows.v1",
        "program": "_ppa.timing",
        "project": str(project),
        "row_count": len(rows),
        "measured_count": len(measured),
        "not_measured_count": len([r for r in rows
                                   if r.get("status") == NOT_MEASURED]),
        "invalid_count": len([r for r in rows if r.get("status") == INVALID]),
        "notes": notes,
        "rows": rows,
        "row_digests": [row_digest(r) for r in rows],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="_ppa.timing",
        description="Per-view timing rows from a project's STA artefacts. "
                    "An extractor: it never returns 1, because it makes no "
                    "claim about the design.")
    ap.add_argument("project", nargs="?", default=".",
                    help="project root to read STA artefacts from")
    ap.add_argument("--json", dest="json_path", default=None,
                    help="write the row document here (atomically)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    project = Path(args.project)
    if not project.is_dir():
        print("[REFUSE] _ppa.timing: %r is not a directory. Nothing was read, "
              "so nothing is claimed." % str(project), file=sys.stderr)
        return RC_BAD_INVOCATION

    rows, notes = timing_rows(project)
    doc = _document(project, rows, notes)

    if args.json_path:
        # NOT sort_keys. §5 requires `schema` to be the document's FIRST key,
        # and sorting would bury it under `invalid_count`. This is the HUMAN
        # document; every identity in it (`row_digests`) went through
        # `canonical_json`, which sorts — the two orders answer two different
        # questions and only one of them is a hash.
        payload = json.dumps(doc, indent=2, ensure_ascii=False)
        if _atomic_write_text is not None:
            _atomic_write_text(args.json_path, payload + "\n")
        else:                                                # pragma: no cover
            Path(args.json_path).write_text(payload + "\n", encoding="utf-8")

    for n in notes:
        print(n)
    for r in rows:
        s = r["scope"]
        val = ("%.6g" % r["value"]) if r.get("status") == MEASURED \
            else r.get("status")
        # `-` for an ABSENT key, and it is not the same as a key holding the
        # string "-": the row's `scope_gaps` says why each one is absent, and
        # this line is a summary for a human, not the record.
        def _f(key):
            return s[key] if key in s else "-"
        print("%-34s %-8s stage=%s mode=%s process=%s V=%s T=%s rc=%s clock=%s "
              "check=%s  %s" % (
                  r["metric"], r["status"], _f("stage"), _f("mode"),
                  _f("process"), _f("voltage_v"), _f("temperature_c"),
                  _f("rc_corner"), _f("clock"), _f("check"), val))

    if doc["measured_count"] == 0:
        print("[CANNOT CHECK] _ppa.timing: %d STA artefact(s) opened and NOT "
              "ONE measured timing row came out of them. This is UNDETERMINED, "
              "not clean: a run that measured nothing and a run that measured "
              "zero violations are different facts."
              % len(discover_reports(project)), file=sys.stderr)
        return RC_UNDETERMINED
    return RC_OK


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
