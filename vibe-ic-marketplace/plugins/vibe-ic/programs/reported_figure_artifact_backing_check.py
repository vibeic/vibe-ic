#!/usr/bin/env python3
"""reported_figure_artifact_backing_check.py — the ARTIFACT-BACKING gate.

WHY THIS EXISTS (measured defect, 2026-07-21 campaign)
======================================================
A campaign ledger published the GDS size ``91,520,898 B`` for a design. That
number matches NO file anywhere in the tree — the real candidates were
91,548,734 and 91,152,610. An independent auditor caught it only by re-deriving
every figure from disk by hand.

The same entry had a deeper problem: the run dir it reported on held 27 files,
ALL under ``input/``, zero outputs — the run never produced anything. Every
figure in that scorecard row had been silently imported from a SIBLING run dir
whose comparison the same document's own caveat section forbade.

Both failures share ONE root cause:
    **a reported number with nothing on disk behind it.**

This gate closes that root cause. It takes a run dir and the report(s) that
speak for it, and asks of every quantitative claim: *can I re-derive this from
an artifact in THIS run dir?* Three outcomes, and the middle one is the whole
point:

  RESOLVED  — the figure equals a real measurement of a real file in this run
              dir. Evidence records the path and the measured value.
  IMPORTED  — the figure matches NO artifact here but DOES match one in a
              SIBLING run dir. This is the precise defect above: a figure
              carried across runs. FAIL, naming BOTH paths. This is the
              highest-value signal the gate emits — a plain "not found" fails
              safe, but "found in the WRONG RUN" names the actual mistake.
  UNRESOLVED— the figure matches nothing anywhere. FAIL, naming the figure.

Plus the structural precondition:

  NO_OUTPUTS_ONLY_INPUTS — every file under the run dir is confined to the
              input subtree. The run produced nothing, so NO verdict may be
              reported for it at all. (Complementary to
              ``run_output_completeness_check.py``, which answers the prior
              question "is there a DELIVERABLE at all?" — that gate passes an
              input-only dir COMPLETE as soon as a RESULT.md exists, because
              it never looks at whether the run had OUTPUTS. See that program's
              docstring; this one is the outputs-and-backing half.)

WHAT SHAPES THIS RECOGNISES — AND WHAT IT DELIBERATELY IGNORES
==============================================================
This is the gate's own most dangerous seam, so it is stated explicitly and
emitted as evidence on EVERY run (see ``numeric_inventory``).

The defect this gate fixes was itself caused by a checker that measured
something ADJACENT to the question and was read as if it answered it. A figure
parser that recognises too little will pass a document full of untraceable
numbers and report a clean bill — reproducing that same failure in a new place.
So a clean verdict from this gate is NEVER "every number is verified"; it is
"every number OF A RECOGNISED SHAPE is verified, and here is the count of what
was not recognised."

RECOGNISED (these are resolved against disk, and fail if they cannot be):
  * BYTE_SIZE_EXACT   an integer with a byte unit and no scale prefix:
                      ``91,520,898 B``, ``854822 bytes``, ``707898B``.
                      Resolved against ``os.stat().st_size`` of files in the
                      run dir. Exact equality. This is the caravel shape.
  * DRC_COUNT         a VIOLATION/ERROR count: ``0 DRC violations``,
                      ``violations=0``, ``DRC violations: 130``, ``errors: 5``.
                      Resolved against this run dir's DRC artifacts: the number
                      of ``<item>`` elements in a KLayout ``report-database``
                      XML (any extension — .rpt, .lyrdb, .xml), else a
                      ``violations=N`` / ``Total: N`` line in a text report.
                      The subject must be an explicit violation/error word; a
                      bare ``mismatch`` is NOT included, because a simulation
                      mismatch count is not a DRC count and resolving it against
                      a DRC database would measure the wrong thing.
  * CHECK_VERDICT     a PASS/FAIL/CLEAN/MISMATCH token bound to a named check
                      (DRC / LVS / LEC / STA / antenna): ``LVS: clean``,
                      ``DRC PASS``. Resolved by requiring the verdict token to
                      appear in a report artifact of THIS run dir.

DELIBERATELY IGNORED (counted and reported, never silently dropped):
  * ROUNDED byte magnitudes — ``58.4 MB``, ``2.6 GB``, ``257 KB``. A rounded
    figure is an order of magnitude, not an artifact identifier: many unrelated
    files round to the same value, and in the real corpus these overwhelmingly
    described peak MEMORY, a docker image, a PDK tarball, or a file outside the
    run dir. Every one of them was a false positive on the corpus sweep. Only an
    EXACT integer byte count — a value that can only have come from ``stat()``
    — is resolved. Counted as ``ignored_rounded_magnitude``.
  * Byte units in a MEMORY context (``killed, 3.7 GB RSS``) — a footprint is
    not a file.
  * Bare numbers with no unit and no recognised subject — section numbers,
    list indices, percentages, ratios, table row counts. There is no defined
    artifact to resolve them against; flagging them would make the gate noise
    and train people to ignore it.
  * Dates and datestamps (``20260721``, ``2026-07-21``), version tokens
    (``v1467``, ``1.4.83``), git SHAs, and numbers inside a URL or a path.
    These are identifiers, not measurements of an artifact.
  * Numbers inside fenced code blocks that are COMMANDS rather than reported
    results — a command line is an instruction, not a claim about an output.
    (Byte sizes and DRC counts inside fences ARE still read: the caravel
    figure appeared in a table, and tables/fences are where real figures live.)

Every ignored token is counted by category in ``evidence.numeric_inventory``
so a reader can see exactly how much of the document the gate spoke for. A
verdict without attached evidence cannot be cross-checked; this program emits
the evidence it judged on so an independent track can re-judge the same inputs.

CLI
===
    reported_figure_artifact_backing_check.py <run_dir>
        [--report PATH ...]      # reports that speak FOR this run dir. May live
                                 # OUTSIDE it (a campaign ledger / scorecard —
                                 # exactly the caravel case). Default: the
                                 # run dir's own RESULT.md / final_summary.md /
                                 # BENCHMARK_VERIFICATION_REPORT.md.
        [--section NAME]         # only judge figures under this heading of the
                                 # report (for a multi-design ledger)
        [--input-dir-name NAME]  # input subtree name (default: input)
        [--no-sibling-scan]      # disable cross-run import detection
        [--json OUT]

Exit codes
----------
    0  CLEAN  — every recognised figure resolved in this run dir
    1  FAIL   — an UNRESOLVED / IMPORTED figure, or NO_OUTPUTS_ONLY_INPUTS
    2  usage error

chip-AGNOSTIC + tool-AGNOSTIC + benchmark-AGNOSTIC: reasons over file sizes,
XML element counts, token presence and directory structure only. No IC name, no
vendor, no SKU, no benchmark identifier appears as logic. Any Phase-1/2/3 run
can invoke it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── unit scales (binary and decimal both accepted; the report chooses) ────────
_SCALES = {
    "b": 1, "byte": 1, "bytes": 1,
    "kb": 1000, "kib": 1024,
    "mb": 1000 ** 2, "mib": 1024 ** 2,
    "gb": 1000 ** 3, "gib": 1024 ** 3,
}
_EXACT_UNITS = {"b", "byte", "bytes"}

# A byte-size figure: a (possibly comma-grouped, possibly decimal) number with a
# byte unit. The unit must be a standalone token so "4 Basic blocks" never reads
# as 4 bytes.
#
# Thousands may be grouped by comma OR by a space / NBSP / thin space — real
# reports in this corpus write "118 146 B" and "20 350 cells". Matching only the
# comma form silently truncated "118 146 B" to "146 B" and then failed to
# resolve it: a WRONG figure, invented by the parser, reported as a defect. The
# space-grouped alternative is therefore listed FIRST so it wins the match.
_GROUPED = r"\d{1,3}(?:[   ]\d{3})+|\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?"
_BYTE_RE = re.compile(
    rf"(?<![\w.])({_GROUPED})[^\S\n]*(bytes|byte|[KMG]i?B|B)(?![\w])")

# A DELTA is a difference between two artifacts, not the size of one ("Δ+252 B",
# "+1,024 B larger"). There is no single file whose stat() equals it.
_DELTA_CTX_RE = re.compile(r"(?:Δ|delta|diff|[+\-−±])\s*$", re.I)

# A DRC/violation count bound to a named subject, in either order:
#   "DRC = 0" / "DRC violations: 130" / "violations=0" / "0 DRC violations"
#
# NARROWED 2026-07-21 after a corpus sweep produced false positives. The subject
# must be an explicit VIOLATION/ERROR word — a bare "mismatch" is NOT included,
# because a simulation mismatch count ("NIST self-verify, 0 mismatch") is not a
# DRC count and resolving it against a DRC database is measuring the wrong
# thing. That is precisely the adjacent-measurement error this gate exists to
# prevent, so the gate must not commit it itself.
# "violation" is a DRC term of art and stands alone. "error" is NOT: a testbench
# line like "2498 checks / 0 errors" is a SIMULATION result, and resolving it
# against a DRC database measures the wrong thing. "error" therefore only counts
# when DRC/LVS is named adjacent to it.
_DRC_SUBJ = r"violations?"
_DRC_RE_SUBJ_FIRST = re.compile(
    rf"\b(?:drc[^\S\n]*)?({_DRC_SUBJ}|(?<=drc )errors?)\b"
    rf"[^\S\n]*[:=][^\S\n]*(\d+)", re.I)
# Markdown wraps lines, so "…→ 0\n   violations in 8 iterations" is one claim.
# At most ONE newline may be crossed — unbounded \s+ would join a number at the
# end of one paragraph to an unrelated word in the next.
_DRC_RE_NUM_FIRST = re.compile(
    rf"\b(\d+)[^\S\n]*\n?[^\S\n]*(?:drc[^\S\n]+)?{_DRC_SUBJ}\b", re.I)

# Byte units also measure MEMORY and RUNTIME footprints ("killed, 3.7 GB RSS"),
# which are not artifacts on disk and must never be resolved against files.
_MEMORY_CTX_RE = re.compile(
    r"\b(rss|ram|memory|heap|swap|resident|peak|footprint|virt)\b", re.I)

# Below this size a byte count is not a DISTINGUISHING measurement — small files
# collide across runs by coincidence — so it may not carry the IMPORTED
# accusation. It still fails as UNRESOLVED, so the gate fails safe either way.
_MIN_DISTINGUISHING_BYTES = 1024

# A verdict token bound to a named check.
_CHECK_NAMES = r"(?:drc|lvs|lec|sta|antenna|density)"
_VERDICT_TOKENS = r"(?:pass|fail|clean|mismatch|violation-free)"
_VERDICT_RE = re.compile(
    rf"\b({_CHECK_NAMES})\b[^\S\n]*[:=\-—]?[^\S\n]*\**({_VERDICT_TOKENS})\b", re.I)

# Ignored-token classifiers (for the honesty inventory).
_DATE_RE = re.compile(r"\b(?:20\d{6}|20\d{2}-\d{2}-\d{2})\b")
_VERSION_RE = re.compile(r"\bv?\d+\.\d+(?:\.\d+)+\b|\bv\d{3,}\b")
_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)
_URLPATH_RE = re.compile(r"(?:https?://|/)\S*\d\S*")
_ANY_NUM_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")

# DRC text-report count lines.
#   "violations: 5" / "Total = 12"  AND the number-first form the OpenROAD and
#   KLayout text reports actually emit: "0 violation(s) found".
_DRC_TEXT_COUNT_RE = re.compile(
    r"(?:total|violations?|count)\s*[:=]\s*(\d+)"
    r"|(\d+)\s+violation(?:\(s\)|s)?\s+found", re.I)


# ---------------------------------------------------------------------------
# Data model.
# ---------------------------------------------------------------------------
@dataclass
class Figure:
    kind: str                  # BYTE_SIZE_EXACT | DRC_COUNT | CHECK_VERDICT
    raw: str                   # the literal text as it appears in the report
    value: object              # normalised value (int bytes / int count / str verdict)
    source_report: str
    line: int
    status: str = "PENDING"    # RESOLVED | IMPORTED | UNRESOLVED
    resolved_path: Optional[str] = None
    resolved_value: object = None
    imported_from: Optional[str] = None
    looked_in: List[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "raw": self.raw, "value": self.value,
            "source_report": self.source_report, "line": self.line,
            "status": self.status, "resolved_path": self.resolved_path,
            "resolved_value": self.resolved_value,
            "imported_from": self.imported_from,
            "looked_in": self.looked_in, "note": self.note,
        }


@dataclass
class BackingReport:
    run_dir: str
    verdict: str                       # CLEAN | FAIL
    state: str                         # BACKED | UNBACKED_FIGURE | CROSS_RUN_IMPORT | NO_OUTPUTS_ONLY_INPUTS
    reason: str
    figures: List[Figure] = field(default_factory=list)
    evidence: Dict[str, object] = field(default_factory=dict)
    blocking: List[str] = field(default_factory=list)
    highlight: str = ""
    capture_candidate: Optional[dict] = None

    @property
    def rc(self) -> int:
        return 0 if self.verdict == "CLEAN" else 1


# ---------------------------------------------------------------------------
# Artifact indexing (pure).
# ---------------------------------------------------------------------------
def _iter_files(root: Path) -> List[Path]:
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.is_symlink():
                try:
                    p.resolve(strict=True)
                except OSError:
                    continue
            out.append(p)
    return out


def _size_index(root: Path) -> Dict[int, List[Path]]:
    """size(bytes) -> [paths]. Built once per directory tree."""
    idx: Dict[int, List[Path]] = {}
    for p in _iter_files(root):
        try:
            if p.is_file():
                idx.setdefault(p.stat().st_size, []).append(p)
        except OSError:
            continue
    return idx


def _outputs_are_input_only(run_dir: Path, input_dir_name: str,
                            exclude: Optional[List[Path]] = None) -> Tuple[bool, int, int]:
    """(all_confined_to_input, total_files, files_outside_input).

    A run dir whose every file sits under the input subtree produced NOTHING.
    Reporting a verdict for it is the caravel failure.

    `exclude` drops the REPORT files themselves from the output census. A report
    is the CLAIM being judged, not an output artifact of the run — counting it
    as an output would let a report about an empty run vouch for itself.
    """
    files = _iter_files(run_dir)
    ex = set()
    for e in (exclude or []):
        try:
            ex.add(Path(e).resolve())
        except OSError:
            continue
    total = 0
    outside = 0
    inp = (run_dir / input_dir_name).resolve()
    for p in files:
        try:
            rp = p.resolve()
        except OSError:
            rp = p
        if rp in ex:
            continue
        total += 1
        try:
            rp.relative_to(inp)
        except ValueError:
            outside += 1
    return (total > 0 and outside == 0), total, outside


def _drc_item_counts(root: Path) -> Dict[int, List[Path]]:
    """count -> [paths] for every DRC-ish artifact under root.

    A KLayout DRC database is XML rooted at <report-database> REGARDLESS of its
    extension (.rpt / .lyrdb / .xml all occur in practice), so detection is by
    CONTENT not by name. Falls back to a `violations=N` / `Total: N` line for
    plain-text DRC reports.
    """
    counts: Dict[int, List[Path]] = {}
    for p in _iter_files(root):
        try:
            if not p.is_file() or p.stat().st_size > 64 * 1024 * 1024:
                continue
            head = p.open("rb").read(400).decode("utf-8", errors="replace")
        except OSError:
            continue
        found: List[int] = []
        if "report-database" in head:
            try:
                found.append(sum(1 for _ in ET.parse(str(p)).getroot().iter("item")))
            except Exception:
                pass
        elif p.suffix.lower() in {".rpt", ".log", ".txt", ".json"}:
            # Match on CONTENT, not on the filename. A run's DRC count is often
            # stated in a convergence/tool LOG whose name says nothing about DRC
            # (e.g. `converge_r6.log` carrying `drc violations=5`). Restricting
            # this scan to drc-NAMED files made the gate report a real, properly
            # backed figure as unbacked — a false positive caused by looking in
            # the wrong place rather than by the claim being wrong.
            try:
                txt = p.read_text(errors="replace")
            except OSError:
                continue
            # A text report may state a count per layer/stage; every stated
            # count is a legitimate resolution target for a quoted figure.
            for m in _DRC_TEXT_COUNT_RE.finditer(txt):
                found.append(int(m.group(1) or m.group(2)))
        for n in found:
            counts.setdefault(n, []).append(p)
    return counts


def _report_texts(root: Path) -> List[Tuple[Path, str]]:
    """Textual report artifacts under root, for verdict-token resolution."""
    out: List[Tuple[Path, str]] = []
    for p in _iter_files(root):
        if p.suffix.lower() not in {".md", ".rpt", ".log", ".json", ".txt", ".xml", ".lyrdb"}:
            continue
        try:
            if p.stat().st_size > 16 * 1024 * 1024:
                continue
            out.append((p, p.read_text(errors="replace")))
        except OSError:
            continue
    return out


# ---------------------------------------------------------------------------
# Figure extraction (pure).
# ---------------------------------------------------------------------------
def _norm_number(tok: str) -> float:
    """Strip thousands grouping — comma, space, NBSP or thin space."""
    for sep in (",", " ", " ", " "):
        tok = tok.replace(sep, "")
    return float(tok)


def _in_code_command(text: str, pos: int) -> bool:
    """True if `pos` sits on a line that reads as a shell COMMAND rather than a
    reported result — a command line is an instruction, not a claim."""
    ls = text.rfind("\n", 0, pos) + 1
    le = text.find("\n", pos)
    line = text[ls: le if le != -1 else len(text)].strip().lstrip("$ ").lstrip()
    return bool(re.match(r"^(?:python3?|bash|sh|git|find|grep|stat|ls|cd|make|"
                         r"docker|klayout|magic|netgen|yosys|openroad)\b", line))


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def extract_figures(text: str, source: str) -> List[Figure]:
    """Every RECOGNISED quantitative claim in `text`. See the module docstring
    for the exact shapes recognised and the shapes deliberately ignored."""
    figs: List[Figure] = []

    for m in _BYTE_RE.finditer(text):
        if _in_code_command(text, m.start()):
            continue
        num_tok, unit = m.group(1), m.group(2)
        scale = _SCALES.get(unit.lower())
        if scale is None:
            continue
        # A SCALED/rounded magnitude ("58.4 MB", "2.6 GB") is not an artifact
        # identifier. It names an order of magnitude that may describe a docker
        # image, a PDK tarball, peak memory, or a file outside the run dir, and
        # many unrelated files round to the same value. Recognising it produced
        # only false positives on the corpus sweep, so it is IGNORED and counted
        # as such — see `numeric_inventory.ignored_rounded_magnitude`.
        if unit.lower() not in _EXACT_UNITS or "." in num_tok:
            continue
        # A byte unit in a MEMORY context measures a footprint, not a file.
        ls = text.rfind("\n", 0, m.start()) + 1
        le = text.find("\n", m.start())
        line_txt = text[ls: le if le != -1 else len(text)]
        if _MEMORY_CTX_RE.search(line_txt):
            continue
        # A DELTA between two artifacts is not the size of either one.
        if _DELTA_CTX_RE.search(text[max(0, m.start() - 12):m.start()]):
            continue
        figs.append(Figure(kind="BYTE_SIZE_EXACT", raw=m.group(0).strip(),
                           value=int(_norm_number(num_tok)),
                           source_report=source, line=_line_of(text, m.start())))

    for m in _DRC_RE_SUBJ_FIRST.finditer(text):
        if _in_code_command(text, m.start()):
            continue
        figs.append(Figure(kind="DRC_COUNT", raw=m.group(0).strip(),
                           value=int(m.group(2)), source_report=source,
                           line=_line_of(text, m.start())))
    for m in _DRC_RE_NUM_FIRST.finditer(text):
        if _in_code_command(text, m.start()):
            continue
        figs.append(Figure(kind="DRC_COUNT", raw=m.group(0).strip(),
                           value=int(m.group(1)), source_report=source,
                           line=_line_of(text, m.start())))

    for m in _VERDICT_RE.finditer(text):
        if _in_code_command(text, m.start()):
            continue
        figs.append(Figure(kind="CHECK_VERDICT", raw=m.group(0).strip(),
                           value=f"{m.group(1).lower()}:{m.group(2).lower()}",
                           source_report=source, line=_line_of(text, m.start())))

    # dedupe on (kind, value, line)
    out, seen = [], set()
    for f in figs:
        k = (f.kind, str(f.value), f.line)
        if k in seen:
            continue
        seen.add(k)
        out.append(f)
    return out


def numeric_inventory(text: str, figures: List[Figure]) -> Dict[str, int]:
    """The honesty accounting: how much of the document did the gate speak for?

    A clean verdict is NEVER "every number is verified" — it is "every number of
    a recognised shape is verified, and here is what was not recognised". This
    inventory is emitted on EVERY run so a reader can judge the coverage of a
    clean bill instead of trusting it.
    """
    total = dates = versions = shas = urls = 0
    for m in _ANY_NUM_RE.finditer(text):
        total += 1
        ctx_s = text.rfind("\n", 0, m.start()) + 1
        ctx_e = text.find("\n", m.start())
        ctx = text[ctx_s: ctx_e if ctx_e != -1 else len(text)]
        tok = m.group(0)
        if _DATE_RE.search(tok) or _DATE_RE.search(ctx):
            dates += 1
        elif _VERSION_RE.search(ctx):
            versions += 1
        elif _URLPATH_RE.search(ctx):
            urls += 1
        elif len(tok) >= 7 and _SHA_RE.fullmatch(tok):
            shas += 1
    # Rounded byte magnitudes are recognised as a SHAPE but deliberately not
    # resolved (see extract_figures) — counted separately so the exclusion is
    # visible rather than buried in "unclassified".
    rounded = 0
    for m in _BYTE_RE.finditer(text):
        unit, num_tok = m.group(2), m.group(1)
        if unit.lower() not in _EXACT_UNITS or "." in num_tok:
            rounded += 1
    recognised = len(figures)
    return {
        "numeric_tokens_seen": total,
        "recognised_as_figures": recognised,
        "ignored_dates": dates,
        "ignored_versions": versions,
        "ignored_url_or_path": urls,
        "ignored_shalike": shas,
        "ignored_rounded_magnitude": rounded,
        "ignored_unclassified": max(
            0, total - recognised - dates - versions - urls - shas - rounded),
        "coverage_note": (
            "a CLEAN verdict speaks ONLY for `recognised_as_figures`; the "
            "ignored counts are numbers this gate does not claim to have "
            "verified (see the module docstring for why each is ignored)"),
    }


# ---------------------------------------------------------------------------
# Resolution.
# ---------------------------------------------------------------------------
def _sibling_dirs(run_dir: Path) -> List[Path]:
    parent = run_dir.parent
    if not parent.is_dir():
        return []
    out = []
    for p in sorted(parent.iterdir()):
        try:
            if p.is_dir() and p.resolve() != run_dir.resolve():
                out.append(p)
        except OSError:
            continue
    return out


def _resolve_byte(fig: Figure, idx: Dict[int, List[Path]]) -> Optional[Path]:
    """An EXACT byte count identifies a file by stat() equality. Only exact
    counts are extracted (rounded magnitudes are ignored — see the module
    docstring), so equality is the whole resolution rule."""
    hits = idx.get(int(fig.value))
    return hits[0] if hits else None


def _resolve_in_tree(fig: Figure, tree: Path, caches: Dict[str, dict]) -> Optional[Path]:
    key = str(tree)
    c = caches.setdefault(key, {})
    if fig.kind == "BYTE_SIZE_EXACT":
        if "sizes" not in c:
            c["sizes"] = _size_index(tree)
        return _resolve_byte(fig, c["sizes"])
    if fig.kind == "DRC_COUNT":
        if "drc" not in c:
            c["drc"] = _drc_item_counts(tree)
        hits = c["drc"].get(int(fig.value))
        return hits[0] if hits else None
    if fig.kind == "CHECK_VERDICT":
        if "texts" not in c:
            c["texts"] = _report_texts(tree)
        check, verdict = str(fig.value).split(":", 1)
        pat = re.compile(rf"\b{re.escape(check)}\b.{{0,80}}?\b{re.escape(verdict)}\b",
                         re.I | re.S)
        for p, txt in c["texts"]:
            if pat.search(txt):
                return p
        return None
    return None


# ---------------------------------------------------------------------------
# The gate.
# ---------------------------------------------------------------------------
_DEFAULT_REPORTS = ["RESULT.md", "reports/final_summary.md",
                    "BENCHMARK_VERIFICATION_REPORT.md", "final_summary.md"]


def _slice_section(text: str, section: str) -> str:
    """The body under the first heading/row mentioning `section`, up to the next
    heading of the same-or-shallower level. Lets a multi-design ledger be judged
    per design without splitting the file."""
    lines = text.splitlines()
    start = None
    level = 6
    for i, ln in enumerate(lines):
        if section.lower() in ln.lower():
            m = re.match(r"^(#{1,6})\s", ln)
            if m:
                start, level = i, len(m.group(1))
                break
            if start is None:
                start, level = i, 6
    if start is None:
        return ""
    out = [lines[start]]
    for ln in lines[start + 1:]:
        m = re.match(r"^(#{1,6})\s", ln)
        if m and len(m.group(1)) <= level:
            break
        out.append(ln)
    return "\n".join(out)


def check(run_dir: Path, *,
          reports: Optional[List[Path]] = None,
          section: Optional[str] = None,
          input_dir_name: str = "input",
          sibling_scan: bool = True) -> BackingReport:
    """Verify every recognised figure in `reports` is backed by an artifact in
    `run_dir`. Pure + deterministic."""
    run_dir = Path(run_dir)

    rep_paths: List[Path] = []
    if reports:
        rep_paths = [Path(r) for r in reports]
    else:
        for rel in _DEFAULT_REPORTS:
            p = run_dir / rel
            if p.is_file():
                rep_paths.append(p)

    # ── structural precondition: a run with zero outputs may report nothing ──
    # Only CLAIM DOCUMENTS are excluded from the output census — a claim must
    # never count as the output that vouches for its own run. A claim document
    # is an explicitly-supplied --report, or the run's top-level RESULT.md
    # deliverable. Everything the RUNNER emitted (reports/final_summary.md, a
    # verification report, any artifact) IS a real output and is counted: one
    # genuine output is enough to leave the zero-output class.
    claim_docs: List[Path] = list(reports or [])
    claim_docs.append(run_dir / "RESULT.md")
    input_only, n_files, n_outside = _outputs_are_input_only(
        run_dir, input_dir_name, exclude=claim_docs)

    figures: List[Figure] = []
    inventory: Dict[str, int] = {}
    read_reports: List[str] = []
    for rp in rep_paths:
        if not rp.is_file():
            continue
        try:
            txt = rp.read_text(errors="replace")
        except OSError:
            continue
        if section:
            txt = _slice_section(txt, section)
            if not txt.strip():
                continue
        read_reports.append(str(rp))
        fs = extract_figures(txt, str(rp))
        figures.extend(fs)
        inv = numeric_inventory(txt, fs)
        for k, v in inv.items():
            if isinstance(v, int):
                inventory[k] = inventory.get(k, 0) + v
        inventory["coverage_note"] = inv["coverage_note"]

    evidence: Dict[str, object] = {
        "reports_read": read_reports,
        "reports_requested": [str(r) for r in rep_paths],
        "section_filter": section,
        "run_dir_files_total": n_files,
        "run_dir_files_outside_input": n_outside,
        "input_dir_name": input_dir_name,
        "input_only": input_only,
        "sibling_scan": sibling_scan,
        "numeric_inventory": inventory,
    }

    if input_only:
        rep = BackingReport(
            run_dir=str(run_dir), verdict="FAIL", state="NO_OUTPUTS_ONLY_INPUTS",
            reason=(f"the run dir holds {n_files} file(s), ALL confined to "
                    f"'{input_dir_name}/' — ZERO outputs. The run produced "
                    f"nothing, so NO figure or verdict may be reported for it. "
                    f"{len(figures)} figure(s) were nonetheless found in "
                    f"{len(read_reports)} report(s)."),
            figures=figures, evidence=evidence)
        rep.blocking.append(f"NO_OUTPUTS_ONLY_INPUTS: {rep.reason}")
        rep.highlight = _highlight(rep)
        rep.capture_candidate = _capture_candidate(rep)
        return rep

    # ── resolve each figure: this run dir first, siblings only to NAME an import ──
    caches: Dict[str, dict] = {}
    siblings = _sibling_dirs(run_dir) if sibling_scan else []
    for f in figures:
        f.looked_in.append(str(run_dir))
        hit = _resolve_in_tree(f, run_dir, caches)
        if hit is not None:
            f.status = "RESOLVED"
            f.resolved_path = str(hit)
            try:
                f.resolved_value = (hit.stat().st_size
                                    if f.kind == "BYTE_SIZE_EXACT" else f.value)
            except OSError:
                f.resolved_value = None
            continue
        # The IMPORTED label is a strong, specific accusation — "this figure was
        # carried over from THAT run". It may only be raised on a DISTINGUISHING
        # value, i.e. one unlikely to collide by coincidence. A zero count
        # matches every clean sibling; a tiny file size matches many siblings.
        # Non-distinguishing figures skip the sibling scan and stay UNRESOLVED,
        # so the gate still FAILS — it just declines to name a culprit it cannot
        # actually prove.
        distinguishing = True
        if f.kind == "DRC_COUNT" and int(f.value) == 0:
            distinguishing = False
            f.note = ("zero is not a distinguishing count — sibling scan skipped "
                      "(cannot attribute an import)")
        elif f.kind == "BYTE_SIZE_EXACT" and int(f.value) < _MIN_DISTINGUISHING_BYTES:
            distinguishing = False
            f.note = (f"below {_MIN_DISTINGUISHING_BYTES} B — not a distinguishing "
                      f"size; sibling scan skipped (cannot attribute an import)")
        if not distinguishing:
            f.status = "UNRESOLVED"
            continue

        found_sib = None
        for sib in siblings:
            f.looked_in.append(str(sib))
            h = _resolve_in_tree(f, sib, caches)
            if h is not None:
                found_sib = h
                break
        if found_sib is not None:
            f.status = "IMPORTED"
            f.imported_from = str(found_sib)
            try:
                f.resolved_value = (found_sib.stat().st_size
                                    if f.kind == "BYTE_SIZE_EXACT" else f.value)
            except OSError:
                f.resolved_value = None
        else:
            f.status = "UNRESOLVED"

    imported = [f for f in figures if f.status == "IMPORTED"]
    unresolved = [f for f in figures if f.status == "UNRESOLVED"]
    resolved = [f for f in figures if f.status == "RESOLVED"]
    evidence["figures_resolved"] = len(resolved)
    evidence["figures_imported"] = len(imported)
    evidence["figures_unresolved"] = len(unresolved)

    if imported:
        state = "CROSS_RUN_IMPORT"
        reason = (f"{len(imported)} figure(s) match NO artifact in this run dir "
                  f"but DO match one in a SIBLING run dir — the figure was "
                  f"imported across runs")
        verdict = "FAIL"
    elif unresolved:
        state = "UNBACKED_FIGURE"
        reason = (f"{len(unresolved)} figure(s) cannot be traced to any artifact "
                  f"in this run dir or any sibling — a reported number with "
                  f"nothing on disk behind it")
        verdict = "FAIL"
    else:
        state = "BACKED"
        reason = (f"all {len(resolved)} recognised figure(s) across "
                  f"{len(read_reports)} report(s) resolve to artifacts in this "
                  f"run dir")
        verdict = "CLEAN"

    rep = BackingReport(run_dir=str(run_dir), verdict=verdict, state=state,
                        reason=reason, figures=figures, evidence=evidence)
    if verdict == "FAIL":
        for f in imported:
            rep.blocking.append(
                f"IMPORTED: {f.kind} `{f.raw}` ({f.source_report}:{f.line}) matches "
                f"NOTHING in {run_dir} but matches {f.imported_from}")
        for f in unresolved:
            rep.blocking.append(
                f"UNRESOLVED: {f.kind} `{f.raw}` ({f.source_report}:{f.line}) "
                f"matches no artifact in {len(f.looked_in)} tree(s) searched")
        rep.highlight = _highlight(rep)
        rep.capture_candidate = _capture_candidate(rep)
    return rep


def _highlight(rep: BackingReport) -> str:
    bar = "!" * 72
    lines = [bar,
             f"!! REPORTED FIGURE NOT BACKED BY ARTIFACT — {rep.state}",
             f"!! run_dir : {rep.run_dir}",
             f"!! why     : {rep.reason}"]
    for b in rep.blocking:
        lines.append(f"!! {b}")
    inv = rep.evidence.get("numeric_inventory", {})
    if inv:
        lines.append(
            f"!! coverage: recognised={inv.get('recognised_as_figures', 0)} of "
            f"{inv.get('numeric_tokens_seen', 0)} numeric tokens "
            f"(unclassified={inv.get('ignored_unclassified', 0)})")
    lines.append("!! ACTION  : re-derive every figure from THIS run dir's "
                 "artifacts, or withdraw the claim. A number with nothing on "
                 "disk behind it must never be published.")
    lines.append(bar)
    return "\n".join(lines)


def _capture_candidate(rep: BackingReport) -> dict:
    return {
        "step": "orchestration.result_figure_backing",
        "design": Path(rep.run_dir).name or rep.run_dir,
        "bucket": "A",
        "failure_mode": rep.state,
        "detected_by": "reported_figure_artifact_backing_check.py",
        "title": f"{rep.state}: {rep.reason[:120]}",
        "suggested_fix": (
            "Re-derive every quantitative claim from the run dir's own "
            "artifacts before publishing. Run "
            "reported_figure_artifact_backing_check.py on the run dir + the "
            "report that speaks for it; a figure that resolves only in a "
            "sibling run dir is an import across runs and must be withdrawn."),
        "backlog_slug": f"unbacked-figure-{rep.state.lower()}",
        "backlog_type": "bug",
        "severity": "P1",
        "component": "orchestration/figure-artifact-backing",
        "session_context": json.dumps(rep.evidence, ensure_ascii=False)[:2000],
    }


def report_to_dict(rep: BackingReport) -> dict:
    return {
        "run_dir": rep.run_dir, "verdict": rep.verdict, "state": rep.state,
        "reason": rep.reason,
        "figures": [f.to_dict() for f in rep.figures],
        "evidence": rep.evidence, "blocking": rep.blocking,
        "highlight": rep.highlight, "capture_candidate": rep.capture_candidate,
        "rc": rep.rc,
    }


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify every reported figure is backed by an artifact in "
                    "the run dir it speaks for.")
    ap.add_argument("run_dir")
    ap.add_argument("--report", action="append", default=None,
                    help="a report that speaks FOR this run dir (repeatable); "
                         "may live outside the run dir (a campaign ledger)")
    ap.add_argument("--section", default=None,
                    help="only judge figures under this heading (multi-design "
                         "ledger)")
    ap.add_argument("--input-dir-name", default="input")
    ap.add_argument("--no-sibling-scan", action="store_true",
                    help="disable cross-run import detection")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"ERROR: not a directory: {run_dir}")
        return 2

    rep = check(run_dir,
                reports=[Path(r) for r in args.report] if args.report else None,
                section=args.section,
                input_dir_name=args.input_dir_name,
                sibling_scan=not args.no_sibling_scan)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report_to_dict(rep), indent=2, ensure_ascii=False) + "\n")

    if rep.highlight:
        print(rep.highlight)
    print(f"[{'CLEAN' if rep.verdict == 'CLEAN' else 'FAIL'}] {rep.state} — {rep.reason}")
    for f in rep.figures:
        if f.status == "RESOLVED":
            print(f"  ok   {f.kind} `{f.raw}` -> {f.resolved_path}")
        elif f.status == "IMPORTED":
            print(f"  IMP  {f.kind} `{f.raw}` -> NOT HERE; found in {f.imported_from}")
        elif f.status == "UNRESOLVED":
            print(f"  MISS {f.kind} `{f.raw}` -> no artifact in "
                  f"{len(f.looked_in)} tree(s)")
    if rep.capture_candidate:
        print("CAPTURE: emitted an enhancement-capture candidate "
              f"(failure_mode={rep.state}).")
    return rep.rc


if __name__ == "__main__":
    raise SystemExit(main())
