#!/usr/bin/env python3
"""run_output_completeness_check.py — the EMPTY / MISSING / STUB deliverable gate.

WHY THIS EXISTS (owner directive 2026-07-08)
============================================
"為什麼常常沒寫 result 或 output 空? 一定要檢查出來為什麼，而且要能 identify 出來
這是有問題的。要有一個 gate，如果 result 空或 output 空就 highlight + 找出問題 +
capture 到 enhancement." — an empty RESULT / empty output must NEVER pass silently.

ROOT CAUSE this gate defends against (observed 3× in one session)
-----------------------------------------------------------------
An agent that delegates a multi-hour run launches the runner as a DETACHED
background process, then its turn ENDS (idle). When the detached process later
finishes, NOTHING re-invokes the agent, so the agent's "then write RESULT.md"
step NEVER runs. The runner's OWN outputs (``reports/final_summary.md`` /
orchestrator ``*_one_shot.json`` verdict / GDS/SPEF artifacts) exist, but the
agent's synthesis deliverable (``RESULT.md``) is never written. Nothing catches
it because every gate keyed off the runner's outputs is green. THIS gate keys
off the DELIVERABLE and names that exact failure mode loudly:
``COMPUTE_DONE_DELIVERABLE_MISSING`` — the launch-and-idle abandon bug.

This is complementary to two neighbours, not a duplicate:
  * ``run_status.py``            answers "is the RUNNER PROCESS done/hung/dead?"
                                 (process + heartbeat). This program answers
                                 "is the DELIVERABLE actually written + real?"
  * ``benchmark_result_md_lint`` answers "does a PRESENT RESULT.md carry the 7
                                 mandatory §6 sections?". This program answers
                                 the prior question — "is there a real,
                                 non-empty, non-stub deliverable AT ALL, and if
                                 not WHY?".

THE FAILURE-MODE TAXONOMY (the WHY is automatic, not a guess)
============================================================
For the run's declared deliverable (default ``RESULT.md``) the classifier emits
exactly one state, each with the evidence it judged on:

  COMPLETE                        — deliverable present, >= a real-content byte
                                    threshold, real section content (not header-
                                    only / not a stub marker), and every declared
                                    artifact/agent-output present + non-empty.
                                    PASS (rc 0) — the only genuinely-done state.
  RUN_STILL_IN_PROGRESS           — the deliverable is not complete YET, but a
                                    runner process or a live ``.runner.lock`` is
                                    STILL ALIVE → this is NOT a fail, the agent
                                    just hasn't reached its write step. Distinct
                                    non-fail status (rc 3). Gated on a genuinely
                                    LIVE pid/lock so it can never mask a truly-
                                    abandoned run (a stale lock from a dead pid
                                    does NOT count as live).
  COMPUTE_DONE_DELIVERABLE_MISSING— the LOAD-BEARING case (the idle-abandon bug):
                                    the runner's compute finished (final_summary
                                    / orchestrator verdict / a declared artifact
                                    present) but RESULT.md is ABSENT or empty and
                                    no runner is live. FAIL (rc 1), loudest.
  DELIVERABLE_STUB                — RESULT.md EXISTS but is hollow (below the byte
                                    threshold, too few content lines, or all-
                                    placeholder). The write step ran but produced
                                    nothing real. FAIL (rc 1).
  RUN_DIED_EARLY                  — RESULT.md absent AND no final_summary AND no
                                    orchestrator verdict AND no artifacts → the
                                    run never got far enough to produce anything.
                                    FAIL (rc 1).
  DECLARED_ARTIFACT_MISSING       — RESULT.md itself is complete, but a
                                    ``--require-artifacts`` entry (or a
                                    ``--agent-output`` file) is missing/empty:
                                    the deliverable claims an output the run did
                                    not produce. FAIL (rc 1).
  NO_OUTPUTS_ONLY_INPUTS          — the deliverable READS as complete, but every
                                    file in the run dir OTHER THAN the
                                    deliverable itself is confined to the input
                                    subtree: the run produced ZERO outputs, so
                                    the verdict the deliverable reports is
                                    backed by nothing. FAIL (rc 1).

  DELIVERABLE_SELF_DECLARED_INTERIM
                                  — the deliverable READS as complete, but SAYS
                                    OF ITSELF that it is not final: it carries an
                                    INTERIM/PROVISIONAL banner, or its headline
                                    verdict/score slot holds a placeholder
                                    (``PENDING``) instead of a measurement. The
                                    document is the authority on its own status
                                    and it states it is unfinished. FAIL (rc 1),
                                    or RUN_STILL_IN_PROGRESS (rc 3) when a runner
                                    is genuinely still live.

                                    Added 2026-08-01 from a MEASURED escape
                                    (sha256 × sky130A, round E). The runner was
                                    killed 9 minutes in by a 10-minute harness
                                    timeout (``Exit code 143``); Phase 3 never
                                    started and the LEC produced no verdict. The
                                    agent had honestly written a RESULT.md
                                    stamped ``⚠️ INTERIM`` with four ``PENDING``
                                    numbers and a promise to fill them "from the
                                    run's own artefacts when it finishes". THIS
                                    gate — the one the operating brief names as
                                    the final act, "only exit 0 / COMPLETE
                                    counts" — returned:

                                        [PASS] COMPLETE — deliverable RESULT.md
                                        present (14023 B, 148 content lines)

                                    rc 0. Because ``_is_all_placeholder``
                                    requires EVERY content line to be a
                                    placeholder, a 14 kB report with 4 unfilled
                                    numbers is nowhere near it, and the verdict
                                    reduced to "RESULT.md is >= 400 B". The gate
                                    written to catch the launch-and-idle abandon
                                    bug (see ROOT CAUSE above) was cleared by the
                                    abandoned run's own interim file. Length is
                                    not doneness.

  DELIVERABLE_CONTRADICTS_ORCHESTRATOR
                                  — the deliverable READS as complete, but its
                                    own HEADLINE VERDICT claims a PASS while the
                                    orchestrator JSON it summarises records
                                    FAIL. FAIL (rc 1).

                                    Added 2026-07-26 from a MEASURED escape
                                    (spm × ihp-sg13g2): RESULT.md written 01:39
                                    with headline PASS_WITH_WAIVERS; a 09:44
                                    invocation moved
                                    ``reports/orchestrator/vibe_ic_one_shot.json``
                                    to ``verdict: FAIL`` and nothing re-read it.
                                    This gate returned COMPLETE / PASS — with
                                    ``orchestrator_verdict='FAIL'`` sitting in
                                    its OWN evidence dict. It had both numbers
                                    and never compared them. The comparison now
                                    lives in
                                    ``deliverable_verdict_consistency_check``,
                                    which sources the two values from different
                                    producers (agent markdown vs runner JSON) so
                                    it cannot be satisfied by re-stating either.

                                    Added 2026-07-21 from a MEASURED escape: a
                                    run dir holding 27 files, 100 % under
                                    ``input/``, carried a RESULT.md claiming
                                    PASS and this gate returned COMPLETE / rc 0.
                                    ``require_artifacts`` defaults to empty, so
                                    ``artifacts_ok`` was VACUOUSLY true and the
                                    verdict reduced to "RESULT.md is ≥400 B" —
                                    prose alone cleared it. The gate that exists
                                    to catch empty outputs greenlit a report
                                    over an empty run. This state closes that.
                                    Companion check (figure-level backing):
                                    ``reported_figure_artifact_backing_check.py``.

On any FAIL the program prints a LOUD HIGHLIGHT block and emits a machine-
readable ``capture_candidate`` (ingestible by the enhancement-capture flow —
``enhancement_emit.py`` schema) so an empty output is captured, never silent.

CLI
===
    run_output_completeness_check.py <run_dir>
        [--result <path>]                 # deliverable (default <run_dir>/RESULT.md)
        [--require-artifacts gds,spef,…]   # declared artifacts (ext or glob)
        [--agent-output <path>]            # a captured agent-return file to check
        [--claimed-verdict PASS|FAIL]      # what the run CLAIMED, for consistency
        [--pid N]                          # runner pid (else run.pid/.runner.lock)
        [--json OUT]

Exit codes
----------
    0  COMPLETE (PASS)
    0  ... nothing else maps to 0
    1  a FAIL classification (any of the four fail states above)
    2  usage error
    3  RUN_STILL_IN_PROGRESS  (distinct NON-FAIL — "in progress", do not block)

chip-AGNOSTIC + tool-AGNOSTIC + pure: reasons over file existence, byte sizes,
content-line counts, process liveness and generic artifact extensions only — no
IC / vendor / SKU literal appears as logic.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ── Real-content thresholds (calibrated against the live benchmark-data RESULT.md
#    corpus: the SMALLEST genuine deliverable is 1252 bytes / 16 content lines,
#    so these floors sit far below every real one and only a genuine empty /
#    header-only / stub file trips them). These are DELIVERABLE-content floors,
#    NOT a per-run size budget — a large run produces a larger RESULT, a small
#    run a smaller one, but neither dips below "a real paragraph of substance".
_MIN_REAL_BYTES = 400
_MIN_CONTENT_LINES = 3

# A line is "content" if it carries substance — not blank, not a bare markdown
# heading / horizontal rule / table separator / bullet marker with no text.
_NON_CONTENT_RE = re.compile(r"^\s*(#{1,6}\s.*|[-=*_]{3,}|\|[\s|:-]*\||[-*+]\s*)?$")
# Placeholder tokens that, when they are the WHOLE of the content, mean "stub".
_PLACEHOLDER_RE = re.compile(
    r"^\s*[-*+>#\s]*("
    r"todo|tbd|fixme|xxx|placeholder|to be written|to be filled|fill in|"
    r"coming soon|n/?a|pending|\.\.\.+|<[^>]*>)"
    r"[\s.:;,)\]]*$",
    re.IGNORECASE,
)

# ── Self-declared-INTERIM detection (the "length is not doneness" rule) ──────
# TWO independent, deliberately NARROW signals. Each was calibrated against the
# whole published RESULT.md corpus in this repo (see
# test_selfdeclared_interim_corpus_sweep) and fires on ZERO of them.
#
# S1 — the DOCUMENT declares itself provisional. Recognised only when the token
#      is ALL-CAPS *and* either emphasised (`**INTERIM**`) or opening a
#      blockquote/callout line (`> ⚠️ INTERIM …`). Caps+emphasis is a deliberate
#      self-declaration; lowercase "a draft of the spec" in prose is not, and
#      does not match. Fenced code blocks are excluded — a report that QUOTES a
#      tool banner is not declaring itself interim.
_INTERIM_WORDS = ("INTERIM", "PROVISIONAL", "PRELIMINARY", "DRAFT", "WIP")
_INTERIM_EMPH_RE = re.compile(
    r"(?:\*\*|__)\s*(" + "|".join(_INTERIM_WORDS) + r")\b")
_INTERIM_CALLOUT_RE = re.compile(
    r"^\s{0,3}>[\s>]*[^\w\s]{0,4}\s*(" + "|".join(_INTERIM_WORDS) + r")\b")

# S2 — the deliverable's HEADLINE verdict/score slot holds a PLACEHOLDER rather
#      than a measurement, i.e. the document reached for a verdict and wrote
#      "PENDING". Distinct from `deliverable_verdict_consistency_check`, which
#      compares a STATED verdict against the orchestrator and returns
#      NOT_APPLICABLE when none is stated: this asks whether the slot was filled
#      at all. Deliberately NOT "any PENDING anywhere" — a FINAL report may
#      legitimately mark an unreachable sub-row (the corpus has one that marks
#      two of six pillars PENDING beside a fully-written headline and an
#      explicit "no tapeout claim"); that is honest reporting, not an unfinished
#      document, and it must not fail.
_UNFILLED_TOKEN_RE = re.compile(
    r"^(PENDING|TBD|TO_BE_FILLED|TO_BE_DETERMINED|TO_BE_WRITTEN|UNMEASURED|"
    r"UNFILLED|TODO|FIXME|XXX|PLACEHOLDER|\?{1,})$")
_HEADLINE_SLOT_LABEL_RE = re.compile(
    r"^(?:final|overall|headline|run|top[- ]?level|sign[- ]?off)?\s*"
    r"(?:verdict|score|result|outcome)$", re.IGNORECASE)
_SLOT_LIST_PREFIX_RE = re.compile(r"^\s{0,8}(?:[-*+>]\s+|\d+[.)]\s+)?")
_SLOT_DECO_CHARS = "`*_~\"' \t"
# An emphasised run whose ENTIRE text is a placeholder, e.g. `**PENDING**`.
_EMPH_RUN_RE = re.compile(r"(?:\*\*|__)([^*_\n]{1,48}?)(?:\*\*|__)")
_FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")

_RUN_PID_FILE = "run.pid"
_LOCK_FILE = ".runner.lock"

# Where a runner's OWN "compute finished" evidence plausibly lives. Newest,
# non-empty match wins. Kept in sync in spirit with run_status.py / _path_layout.
_FINAL_SUMMARY_GLOBS = [
    "reports/final_summary.md",
    "reports/orchestrator/final_summary.md",
    "final_summary.md",
]
_ORCH_REPORT_GLOBS = [
    "reports/orchestrator/*_one_shot.json",
    "reports/*_one_shot.json",
    "reports/orchestrator/vibe_ic_one_shot.json",
]


# ---------------------------------------------------------------------------
# Result data model.
# ---------------------------------------------------------------------------
@dataclass
class CompletenessReport:
    run_dir: str
    deliverable: str
    state: str                     # COMPLETE | RUN_STILL_IN_PROGRESS | … (see module doc)
    verdict: str                   # PASS | IN_PROGRESS | FAIL
    reason: str
    evidence: Dict[str, object] = field(default_factory=dict)
    blocking: List[str] = field(default_factory=list)
    highlight: str = ""
    capture_candidate: Optional[dict] = None
    claimed_verdict: Optional[str] = None

    @property
    def is_fail(self) -> bool:
        return self.verdict == "FAIL"

    @property
    def rc(self) -> int:
        return _EXIT.get(self.state, 2)


_EXIT = {
    "COMPLETE": 0,
    "RUN_STILL_IN_PROGRESS": 3,
    "COMPUTE_DONE_DELIVERABLE_MISSING": 1,
    "DELIVERABLE_STUB": 1,
    "RUN_DIED_EARLY": 1,
    "DECLARED_ARTIFACT_MISSING": 1,
    "NO_OUTPUTS_ONLY_INPUTS": 1,
    "DELIVERABLE_CONTRADICTS_ORCHESTRATOR": 1,
    "DELIVERABLE_SELF_DECLARED_INTERIM": 1,
}

# The run-dir subtree that holds a run's INPUTS. A run whose every file lives
# here produced nothing. Overridable per-call; the name is a layout convention,
# not a benchmark/IC literal.
_INPUT_DIR_NAME = "input"


# ---------------------------------------------------------------------------
# Low-level probes (pure).
# ---------------------------------------------------------------------------
def _pid_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _resolve_pid(run_dir: Path, pid_arg: Optional[int]) -> Optional[int]:
    """Resolve the runner pid: explicit --pid, else <run_dir>/run.pid, else the
    holder pid recorded in an existing <run_dir>/.runner.lock. Reuses EXISTING
    artifacts (run_status.py convention) — no new pid file convention."""
    if pid_arg:
        return pid_arg
    pf = run_dir / _RUN_PID_FILE
    if pf.is_file():
        try:
            return int(pf.read_text().strip().split()[0])
        except Exception:
            pass
    lock = run_dir / _LOCK_FILE
    if lock.is_file():
        try:
            d = json.loads(lock.read_text())
            v = int(d.get("pid", -1))
            return v if v > 0 else None
        except Exception:
            return None
    return None


def _liveness(run_dir: Path, pid_arg: Optional[int]) -> Dict[str, object]:
    """Is a runner genuinely LIVE for this run_dir? A stale lock (dead pid) is
    NOT live — that must not mask an abandoned run (the false-negative the owner
    directive forbids). RUN_STILL_IN_PROGRESS is gated on this returning
    live=True."""
    pid = _resolve_pid(run_dir, pid_arg)
    alive = _pid_alive(pid)
    lock = run_dir / _LOCK_FILE
    lock_exists = lock.is_file()
    lock_live = False
    if lock_exists:
        try:
            d = json.loads(lock.read_text())
            lock_pid = int(d.get("pid", -1))
            lock_live = _pid_alive(lock_pid)
        except Exception:
            lock_live = False
    live = bool(alive or lock_live)
    return {
        "pid": pid,
        "pid_alive": alive,
        "lock": str(lock) if lock_exists else None,
        "lock_live": lock_live,
        "live": live,
    }


def _content_lines(text: str) -> List[str]:
    """Lines carrying real substance (not blank / bare heading / rule / table
    separator / empty bullet)."""
    out = []
    for ln in text.splitlines():
        if _NON_CONTENT_RE.match(ln):
            continue
        out.append(ln.strip())
    return out


def _is_all_placeholder(content: List[str]) -> bool:
    """True iff EVERY content line is a placeholder token (a whole-file stub)."""
    if not content:
        return False
    return all(_PLACEHOLDER_RE.match(ln) for ln in content)


def _assess_deliverable(path: Path) -> Dict[str, object]:
    """Existence + real-content assessment of one deliverable file (pure)."""
    exists = path.is_file()
    if not exists:
        return {"exists": False, "bytes": 0, "content_lines": 0,
                "all_placeholder": False, "complete": False}
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return {"exists": True, "bytes": 0, "content_lines": 0,
                "all_placeholder": False, "complete": False}
    nbytes = len(raw)
    content = _content_lines(text)
    all_ph = _is_all_placeholder(content)
    complete = (nbytes >= _MIN_REAL_BYTES
                and len(content) >= _MIN_CONTENT_LINES
                and not all_ph)
    return {"exists": True, "bytes": nbytes, "content_lines": len(content),
            "all_placeholder": all_ph, "complete": complete}


# ---------------------------------------------------------------------------
# Self-declared-INTERIM probes (PURE — the tests call these directly).
# ---------------------------------------------------------------------------
def _prose_lines(text: str) -> List[tuple]:
    """(1-based lineno, line) for every line OUTSIDE a fenced code block.

    A deliverable routinely quotes a tool's own banner inside a fence. Quoting
    someone else's "INTERIM" is not declaring yourself interim, so fences are
    excluded from every signal below.
    """
    out: List[tuple] = []
    in_fence = False
    for i, ln in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(ln):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((i, ln))
    return out


def _slot_strip(s: str) -> str:
    """Strip markdown decoration from both ends until stable."""
    prev, cur = None, s.strip()
    while cur != prev:
        prev, cur = cur, cur.strip(_SLOT_DECO_CHARS)
    return cur


def _is_unfilled(raw: str) -> bool:
    """True iff `raw` reduces to a bare placeholder token (`**PENDING**`,
    `TBD`, `_UNMEASURED_`). Prose that merely CONTAINS the word does not."""
    t = _slot_strip(raw)
    if not t:
        return False
    return bool(_UNFILLED_TOKEN_RE.match(
        re.sub(r"[\s\-]+", "_", t).upper().strip("_")))


def find_interim_banner(text: str) -> List[tuple]:
    """S1 — every line on which the document declares ITSELF provisional.
    Returns [(lineno, matched_word, line_excerpt)]."""
    hits: List[tuple] = []
    for lineno, ln in _prose_lines(text):
        m = _INTERIM_CALLOUT_RE.search(ln) or _INTERIM_EMPH_RE.search(ln)
        if m:
            hits.append((lineno, m.group(1), ln.strip()[:120]))
    return hits


def find_placeholder_headline(text: str) -> Optional[tuple]:
    """S2 — the headline verdict/score slot holds a placeholder instead of a
    measurement. Returns (lineno, label, raw_value) or None.

    Matches a LABELLED line only (`**Score: PENDING — …**`, `Overall verdict:
    TBD`). A body opening with a backtick is a quotation of some other file's
    field, not this deliverable's own headline — rejected, mirroring
    `deliverable_verdict_consistency_check._r_labelled_line`.
    """
    for lineno, ln in _prose_lines(text):
        body = _SLOT_LIST_PREFIX_RE.sub("", ln, count=1).strip()
        body = body.strip("*_ \t")
        if not body or body.startswith("`"):
            continue
        m = re.match(r"^(.{1,40}?)\s*(?::|=|—|--)\s*(.+)$", body)
        if not m:
            continue
        if not _HEADLINE_SLOT_LABEL_RE.match(_slot_strip(m.group(1))):
            continue
        # The value up to the first annotation separator — a real headline
        # annotates on the same line ("PENDING — filled on completion").
        value = re.split(r"\s+[—–]\s+|\s+--?\s+|\s*[(,;]", m.group(2),
                         maxsplit=1)[0]
        if _is_unfilled(value):
            return (lineno, _slot_strip(m.group(1)), _slot_strip(value))
    return None


def find_unfilled_slots(text: str) -> List[tuple]:
    """ADVISORY (never gating) — every placeholder standing ALONE in a slot:
    the whole of an emphasised run, or the whole of a table cell. Reported so a
    FAIL names exactly what still has to be filled. Non-gating by construction,
    so it can never turn an honest final report into a false FAIL."""
    hits: List[tuple] = []
    for lineno, ln in _prose_lines(text):
        s = ln.strip()
        if s.startswith("|") and s.endswith("|") and s.count("|") >= 2:
            for cell in s.strip("|").split("|"):
                if _is_unfilled(cell):
                    hits.append((lineno, _slot_strip(cell), s[:120]))
        for run in _EMPH_RUN_RE.findall(ln):
            if _is_unfilled(run):
                hits.append((lineno, _slot_strip(run), s[:120]))
    # de-duplicate (lineno, token) while preserving order
    seen = set()
    out = []
    for h in hits:
        k = (h[0], h[1])
        if k not in seen:
            seen.add(k)
            out.append(h)
    return out


def assess_self_declared_interim(path: Path) -> Dict[str, object]:
    """Read `path` and evaluate S1 + S2 + the advisory slot census."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"readable": False, "banner": [], "headline_placeholder": None,
                "unfilled_slots": [], "self_declared_interim": False}
    banner = find_interim_banner(text)
    headline = find_placeholder_headline(text)
    return {
        "readable": True,
        "banner": [{"line": n, "word": w, "text": t} for n, w, t in banner],
        "headline_placeholder": (
            {"line": headline[0], "label": headline[1], "value": headline[2]}
            if headline else None),
        "unfilled_slots": [{"line": n, "token": tok, "text": t}
                           for n, tok, t in find_unfilled_slots(text)],
        "self_declared_interim": bool(banner or headline),
    }


def _newest_nonempty(run_dir: Path, globs: List[str]) -> Optional[Path]:
    newest: Optional[Path] = None
    newest_m = -1.0
    for pat in globs:
        for p in run_dir.glob(pat):
            try:
                if p.is_file() and p.stat().st_size > 0:
                    m = p.stat().st_mtime
                    if m > newest_m:
                        newest_m, newest = m, p
            except OSError:
                continue
    return newest


def _orchestrator_verdict(run_dir: Path) -> Dict[str, object]:
    """The newest orchestrator/phase one_shot.json that carries a `verdict`."""
    best: Optional[Path] = None
    best_m = -1.0
    verdict = None
    for pat in _ORCH_REPORT_GLOBS:
        for p in run_dir.glob(pat):
            try:
                if not (p.is_file() and p.stat().st_size > 0):
                    continue
                d = json.loads(p.read_text(errors="replace"))
            except Exception:
                continue
            if isinstance(d, dict) and d.get("verdict"):
                m = p.stat().st_mtime
                if m > best_m:
                    best_m, best, verdict = m, p, d.get("verdict")
    return {"report": str(best) if best else None, "verdict": verdict}


def _output_census(run_dir: Path, deliverable: Path,
                   input_dir_name: str = _INPUT_DIR_NAME) -> Dict[str, object]:
    """Did this run produce any OUTPUT at all?

    Counts every file under run_dir EXCEPT the deliverable itself, and asks how
    many live outside the input subtree. The deliverable is excluded because it
    is the CLAIM being judged — a RESULT.md must never count as the output that
    vouches for its own run.

    ``input_only`` is True only when there is at least one file and NONE of them
    is an output. An empty dir is NOT input_only (RUN_DIED_EARLY already owns
    that case), and a run dir with no input subtree at all is never input_only.
    """
    inp = (run_dir / input_dir_name)
    try:
        inp_r = inp.resolve()
    except OSError:
        inp_r = inp
    try:
        deliv_r = deliverable.resolve()
    except OSError:
        deliv_r = deliverable
    total = 0
    outside = 0
    for dirpath, dirnames, filenames in os.walk(run_dir):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                pr = p.resolve()
            except OSError:
                pr = p
            if pr == deliv_r:
                continue
            total += 1
            try:
                pr.relative_to(inp_r)
            except ValueError:
                outside += 1
    return {"files_total": total, "files_outside_input": outside,
            "input_dir": str(inp), "input_dir_exists": inp.is_dir(),
            "input_only": bool(total > 0 and outside == 0 and inp.is_dir())}


def _norm_artifact_globs(req: List[str]) -> List[str]:
    """Turn 'gds,spef' or globs into concrete glob patterns. A bare token like
    'gds' becomes a recursive '**/*.gds'; a token already containing a glob
    metachar or a slash is used verbatim (recursive if it has no '/')."""
    out = []
    for tok in req:
        tok = tok.strip()
        if not tok:
            continue
        if any(c in tok for c in "*?[") or "/" in tok:
            out.append(tok)
        else:
            out.append(f"**/*.{tok.lstrip('.')}")
    return out


def _check_artifacts(run_dir: Path, req: List[str]) -> Dict[str, object]:
    """For each declared artifact type, find a non-empty match. Returns
    per-token findings + the list of missing/empty tokens."""
    findings: Dict[str, object] = {}
    missing: List[str] = []
    for tok, pat in zip(req, _norm_artifact_globs(req)):
        hit = None
        nbytes = 0
        for p in run_dir.glob(pat):
            try:
                if p.is_file() and p.stat().st_size > 0:
                    hit = p
                    nbytes = p.stat().st_size
                    break
            except OSError:
                continue
        ok = hit is not None
        findings[tok] = {"found": str(hit) if hit else None,
                         "bytes": nbytes, "ok": ok}
        if not ok:
            missing.append(tok)
    return {"findings": findings, "missing": missing,
            "any_present": any(v["ok"] for v in findings.values()) if findings else False}


# ---------------------------------------------------------------------------
# The classifier.
# ---------------------------------------------------------------------------
def check(run_dir: Path, *,
          result: Optional[Path] = None,
          require_artifacts: Optional[List[str]] = None,
          agent_output: Optional[Path] = None,
          claimed_verdict: Optional[str] = None,
          pid: Optional[int] = None) -> CompletenessReport:
    """Judge whether the run's declared deliverable is genuinely COMPLETE, and if
    not, WHY — see the module docstring for the taxonomy. Pure + deterministic."""
    run_dir = Path(run_dir)
    deliverable = Path(result) if result is not None else run_dir / "RESULT.md"
    req = list(require_artifacts or [])

    dl = _assess_deliverable(deliverable)
    fs = _newest_nonempty(run_dir, _FINAL_SUMMARY_GLOBS)
    orch = _orchestrator_verdict(run_dir)
    arts = _check_artifacts(run_dir, req)
    ao = None
    if agent_output is not None:
        ao = _assess_deliverable(Path(agent_output))
        # agent-output need only be NON-EMPTY (bytes>0, ≥1 content line);
        # it is not a full RESULT.md so it need not meet the byte floor.
        ao_ok = bool(ao["exists"] and ao["bytes"] > 0 and ao["content_lines"] >= 1)
    else:
        ao_ok = True
    live = _liveness(run_dir, pid)
    census = _output_census(run_dir, deliverable)
    interim = assess_self_declared_interim(deliverable) if dl["exists"] else {
        "readable": False, "banner": [], "headline_placeholder": None,
        "unfilled_slots": [], "self_declared_interim": False}

    compute_done = bool(fs is not None or orch["verdict"] or arts["any_present"])

    evidence: Dict[str, object] = {
        "deliverable_exists": dl["exists"],
        "deliverable_bytes": dl["bytes"],
        "deliverable_content_lines": dl["content_lines"],
        "deliverable_all_placeholder": dl["all_placeholder"],
        "deliverable_complete": dl["complete"],
        "min_real_bytes": _MIN_REAL_BYTES,
        "min_content_lines": _MIN_CONTENT_LINES,
        "final_summary": str(fs) if fs else None,
        "orchestrator_report": orch["report"],
        "orchestrator_verdict": orch["verdict"],
        "required_artifacts": arts["findings"],
        "missing_artifacts": arts["missing"],
        "agent_output": (str(agent_output) if agent_output is not None else None),
        "agent_output_ok": ao_ok,
        "compute_done": compute_done,
        "liveness": live,
        "output_census": census,
        "self_declared_interim": interim["self_declared_interim"],
        "interim_banner": interim["banner"],
        "headline_placeholder": interim["headline_placeholder"],
        "unfilled_slots": interim["unfilled_slots"],
    }

    artifacts_ok = not arts["missing"]
    deliverable_complete = bool(dl["complete"] and artifacts_ok and ao_ok)

    # ── the CONTRADICTION escape (2026-07-26, measured) ─────────────────────
    # Note what `evidence` above already holds: `orchestrator_verdict`. This
    # gate has ALWAYS read the runner's verdict — and never compared it to what
    # the deliverable CLAIMS. On spm × ihp-sg13g2 that produced
    # `COMPLETE / PASS` over a RESULT.md reporting PASS_WITH_WAIVERS while
    # `vibe_ic_one_shot.json` said FAIL, for 8 hours, with every gate green.
    # `deliverable_verdict_consistency_check` supplies the missing half: it
    # parses the deliverable's OWN headline (agent-produced markdown) and
    # compares POLARITY against the runner's JSON. Best-effort import so a
    # missing sibling degrades to the prior behaviour and never crashes a run.
    contradiction = None
    try:
        import deliverable_verdict_consistency_check as _dvc
        _c = _dvc.check(run_dir, result=deliverable)
        evidence["deliverable_headline_verdict"] = _c.headline.get("token")
        evidence["verdict_consistency_state"] = _c.state
        if _c.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR":
            contradiction = _c
    except Exception:
        evidence["verdict_consistency_state"] = "UNAVAILABLE"

    # ── classify ────────────────────────────────────────────────────────────
    # The contradiction and zero-output escapes are judged FIRST, because they
    # are the cases where every other signal reads green: the deliverable is
    # complete, no artifact was DECLARED so none can be missing, and the verdict
    # would be PASS. Scoped to `deliverable_complete` so the STUB /
    # RUN_DIED_EARLY / IN_PROGRESS classifications below keep their exact prior
    # semantics.
    if deliverable_complete and contradiction is not None:
        state, verdict, reason = (
            "DELIVERABLE_CONTRADICTS_ORCHESTRATOR", "FAIL", contradiction.reason)
    elif deliverable_complete and interim["self_declared_interim"]:
        # LENGTH IS NOT DONENESS. Every other signal here reads green — the file
        # is large, has hundreds of content lines, is nowhere near all-
        # placeholder — and the document itself says it is not finished. The
        # document is the authority on its own status.
        why = []
        if interim["banner"]:
            b = interim["banner"][0]
            why.append(f"declares itself {b['word']} at line {b['line']}")
        if interim["headline_placeholder"]:
            h = interim["headline_placeholder"]
            why.append(f"its headline '{h['label']}' slot holds the placeholder "
                       f"'{h['value']}' at line {h['line']} instead of a "
                       f"measurement")
        n_slots = len(interim["unfilled_slots"])
        if live["live"]:
            # A runner is genuinely still going: this is honestly IN PROGRESS,
            # not a failure — but it is NOT COMPLETE, and rc 3 != 0 so an
            # "only exit 0 counts" caller still refuses to sign it off.
            who = (f"pid {live['pid']} alive" if live["pid_alive"]
                   else f"live lock {live['lock']}")
            state, verdict, reason = "RUN_STILL_IN_PROGRESS", "IN_PROGRESS", (
                f"{deliverable.name} is present but {'; '.join(why)}, and a "
                f"runner is LIVE ({who}) — the deliverable is an interim "
                f"snapshot, not the finished report"
                + (f"; {n_slots} unfilled slot(s) remain" if n_slots else ""))
        else:
            state, verdict, reason = (
                "DELIVERABLE_SELF_DECLARED_INTERIM", "FAIL", (
                    f"{deliverable.name} reads as complete ({dl['bytes']} B, "
                    f"{dl['content_lines']} content lines) but {'; '.join(why)}"
                    + (f"; {n_slots} placeholder slot(s) are still unfilled"
                       if n_slots else "")
                    + f". No runner is live, so nothing is going to fill them: "
                      f"this is an ABANDONED interim report, not a result. "
                      f"Length is not doneness."))
    elif deliverable_complete and census["input_only"] and not live["live"]:
        state, verdict, reason = "NO_OUTPUTS_ONLY_INPUTS", "FAIL", (
            f"{deliverable.name} reads as complete ({dl['bytes']} B) but the run "
            f"produced ZERO outputs: all {census['files_total']} other file(s) in "
            f"the run dir are confined to '{Path(census['input_dir']).name}/'. The "
            f"reported verdict is backed by nothing on disk — a run that produced "
            f"no output may never be reported as a result.")
    elif deliverable_complete:
        state, verdict, reason = "COMPLETE", "PASS", (
            f"deliverable {deliverable.name} present ({dl['bytes']} B, "
            f"{dl['content_lines']} content lines)"
            + (f"; all {len(req)} declared artifact(s) present" if req else "")
            + (" ; agent-output present" if agent_output is not None else ""))
    elif live["live"]:
        who = (f"pid {live['pid']} alive" if live["pid_alive"]
               else f"live lock {live['lock']}")
        state, verdict, reason = "RUN_STILL_IN_PROGRESS", "IN_PROGRESS", (
            f"deliverable not complete yet, but a runner is LIVE ({who}) — the "
            f"agent has not reached its write step; not a failure (re-check "
            f"after the run exits)")
    elif not dl["complete"]:
        if dl["exists"]:
            why = ("all content lines are placeholders" if dl["all_placeholder"]
                   else f"only {dl['bytes']} B / {dl['content_lines']} content "
                        f"line(s) (< {_MIN_REAL_BYTES} B / {_MIN_CONTENT_LINES} "
                        f"lines)")
            state, verdict, reason = "DELIVERABLE_STUB", "FAIL", (
                f"{deliverable.name} EXISTS but is hollow: {why} — the write "
                f"step ran but produced no real content")
        elif compute_done:
            ev = []
            if fs:
                ev.append(f"final_summary={Path(fs).name}")
            if orch["verdict"]:
                ev.append(f"orchestrator verdict={orch['verdict']}")
            if arts["any_present"]:
                ev.append("declared artifact(s) present")
            state, verdict, reason = "COMPUTE_DONE_DELIVERABLE_MISSING", "FAIL", (
                f"the run's COMPUTE FINISHED ({', '.join(ev)}) but "
                f"{deliverable.name} is ABSENT — the launch-and-idle abandon "
                f"bug: the agent's turn ended before it wrote the deliverable. "
                f"THIS RUN IS A FAILED RUN (no synthesis output).")
        else:
            state, verdict, reason = "RUN_DIED_EARLY", "FAIL", (
                f"{deliverable.name} absent AND no final_summary, no "
                f"orchestrator verdict, no declared artifact — the run never "
                f"got far enough to produce anything (died early / never ran)")
    else:
        # RESULT itself is complete but a declared artifact / agent-output is
        # missing → the deliverable claims an output the run did not produce.
        gaps = []
        if arts["missing"]:
            gaps.append(f"artifact(s) {arts['missing']}")
        if not ao_ok:
            gaps.append("agent-output empty/missing")
        state, verdict, reason = "DECLARED_ARTIFACT_MISSING", "FAIL", (
            f"{deliverable.name} is complete but a declared deliverable is "
            f"missing/empty: {', '.join(gaps)}")

    rep = CompletenessReport(
        run_dir=str(run_dir), deliverable=str(deliverable),
        state=state, verdict=verdict, reason=reason, evidence=evidence,
        claimed_verdict=claimed_verdict)

    # blocking list + claimed-verdict consistency
    if verdict == "FAIL":
        rep.blocking.append(f"{state}: {reason}")
        if contradiction is not None:
            # Carry the consistency gate's OWN both-sides evidence (deliverable
            # path:line + the exact orchestrator report it compared against).
            # `evidence['orchestrator_verdict']` above is the NEWEST-by-mtime
            # report, which is a different selection rule from this gate's
            # (aggregate-first), so without this the highlight can show two
            # different orchestrator verdicts in one block.
            rep.blocking.extend(contradiction.blocking)
        if claimed_verdict and str(claimed_verdict).upper() == "PASS":
            rep.blocking.append(
                f"INCONSISTENCY: run CLAIMED verdict=PASS but produced no "
                f"complete deliverable ({state})")
        rep.highlight = _highlight(rep)
        rep.capture_candidate = _capture_candidate(rep)
    return rep


def _highlight(rep: CompletenessReport) -> str:
    bar = "!" * 72
    lines = [
        bar,
        f"!! EMPTY / MISSING / STUB DELIVERABLE — {rep.state}",
        f"!! run_dir     : {rep.run_dir}",
        f"!! deliverable : {rep.deliverable}",
        f"!! why         : {rep.reason}",
    ]
    ev = rep.evidence
    lines.append(
        f"!! evidence    : exists={ev['deliverable_exists']} "
        f"bytes={ev['deliverable_bytes']} lines={ev['deliverable_content_lines']} "
        f"compute_done={ev['compute_done']} "
        f"final_summary={'yes' if ev['final_summary'] else 'no'} "
        f"orch_verdict={ev['orchestrator_verdict']!r} "
        f"live={ev['liveness']['live']}")
    if ev["missing_artifacts"]:
        lines.append(f"!! missing artifacts: {ev['missing_artifacts']}")
    for b in ev.get("interim_banner") or []:
        lines.append(f"!! self-declared {b['word']} @ line {b['line']}: "
                     f"{b['text']}")
    hp = ev.get("headline_placeholder")
    if hp:
        lines.append(f"!! headline '{hp['label']}' @ line {hp['line']} = "
                     f"'{hp['value']}' — the deliverable states NO verdict")
    for s in (ev.get("unfilled_slots") or []):
        lines.append(f"!! UNFILLED @ line {s['line']}: {s['token']} — "
                     f"{s['text']}")
    for b in rep.blocking:
        lines.append(f"!! {b}")
    lines.append("!! ACTION      : write the deliverable from the artifacts, "
                 "then re-run this gate — NO RESULT / empty output = the run "
                 "FAILED.")
    lines.append(bar)
    return "\n".join(lines)


def _capture_candidate(rep: CompletenessReport) -> dict:
    """A machine-readable enhancement-capture record (enhancement_emit.py
    schema, Bucket C) so an empty output is captured, never silent."""
    ev = rep.evidence
    return {
        "step": "orchestration.deliverable_finalize",
        "design": Path(rep.run_dir).name or rep.run_dir,
        "bucket": "C",
        "why_not_bucket_a": (
            "run_output_completeness_check.py IS the deterministic gate; the "
            "residual is the ORCHESTRATION discipline a program cannot enforce "
            "on the agent's turn lifecycle — an agent that detaches a long run "
            "and idles never gets re-invoked to write the deliverable."),
        "failure_mode": rep.state,
        "detected_by": "run_output_completeness_check.py",
        "title": f"{rep.state}: {Path(rep.deliverable).name} — {rep.reason[:120]}",
        "suggested_fix": (
            "Run the long tool through the BLOCKING _watchdog.run_supervised "
            "(returns only on exit/stall) so the agent's turn stays alive to "
            "completion; the agent's FINAL act before reporting done is to WRITE "
            "+ SELF-VERIFY the deliverable by running "
            "run_output_completeness_check on its own run_dir. No RESULT / empty "
            "output = the run FAILED."),
        "backlog_slug": f"empty-run-deliverable-{rep.state.lower()}",
        "backlog_type": "bug",
        "severity": "P1",
        "component": "orchestration/deliverable-completeness",
        "session_context": (
            f"run_dir={rep.run_dir}; deliverable={rep.deliverable}; "
            f"exists={ev['deliverable_exists']} bytes={ev['deliverable_bytes']} "
            f"content_lines={ev['deliverable_content_lines']} "
            f"compute_done={ev['compute_done']} "
            f"final_summary={ev['final_summary']} "
            f"orchestrator_verdict={ev['orchestrator_verdict']} "
            f"missing_artifacts={ev['missing_artifacts']} "
            f"live={ev['liveness']['live']}"),
    }


def report_to_dict(rep: CompletenessReport) -> dict:
    return {
        "run_dir": rep.run_dir,
        "deliverable": rep.deliverable,
        "state": rep.state,
        "verdict": rep.verdict,
        "reason": rep.reason,
        "evidence": rep.evidence,
        "blocking": rep.blocking,
        "highlight": rep.highlight,
        "capture_candidate": rep.capture_candidate,
        "claimed_verdict": rep.claimed_verdict,
        "rc": rep.rc,
    }


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Gate an EMPTY / MISSING / STUB run deliverable — highlight "
                    "it, diagnose WHY, and emit a capture candidate.")
    ap.add_argument("run_dir", help="the run directory to check")
    ap.add_argument("--result", default=None,
                    help="deliverable path (default <run_dir>/RESULT.md)")
    ap.add_argument("--require-artifacts", default=None,
                    help="comma-separated declared artifacts: extensions "
                         "(gds,spef,def) or globs")
    ap.add_argument("--agent-output", default=None,
                    help="a captured agent-return file to check is non-empty")
    ap.add_argument("--claimed-verdict", default=None,
                    help="what the run CLAIMED (PASS/FAIL) — flags a PASS claim "
                         "with no complete deliverable")
    ap.add_argument("--pid", type=int, default=None,
                    help="runner pid (else <run_dir>/run.pid or .runner.lock)")
    ap.add_argument("--json", default=None, help="write the verdict JSON here")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"ERROR: not a directory: {run_dir}")
        return 2
    req = ([t for t in args.require_artifacts.split(",") if t.strip()]
           if args.require_artifacts else None)

    rep = check(run_dir,
                result=Path(args.result) if args.result else None,
                require_artifacts=req,
                agent_output=Path(args.agent_output) if args.agent_output else None,
                claimed_verdict=args.claimed_verdict,
                pid=args.pid)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report_to_dict(rep), indent=2, ensure_ascii=False) + "\n")

    if rep.highlight:
        print(rep.highlight)
    tag = {"PASS": "PASS", "IN_PROGRESS": "IN-PROGRESS", "FAIL": "FAIL"}[rep.verdict]
    print(f"[{tag}] {rep.state} — {rep.reason}")
    if rep.capture_candidate:
        print("CAPTURE: emitted an enhancement-capture candidate "
              "(failure_mode=" + rep.state + ") — feed to enhancement_emit.py "
              "so this empty output is absorbed, not silent.")
    return rep.rc


if __name__ == "__main__":
    raise SystemExit(main())
