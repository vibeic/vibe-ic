#!/usr/bin/env python3
"""ic_expert_db_capture.py — GATED writer that files a design-craft lesson back
into the IC Expert DB from a Phase-1 IC-Expert DIALOGUE (a real user design
session), not only from a scored benchmark recovery.

Why this exists (Karpathy LLM-Wiki study -> F3): today the DB is only grown by
the benchmark-enhancement-capture flow, whose trigger is a fail->pass recovery
against an oracle. A plain user dialogue that surfaces genuinely general,
chip-AGNOSTIC class craft has NO write-back path, so that knowledge evaporates.
This tool is the "file the good answer back" step — but routed through the SAME
governance the benchmark path obeys, so a dialogue can never mutate the DB
autonomously or unreviewed.

GOVERNANCE (every guarantee is load-bearing):
  * VALIDATE-BEFORE-WRITE. The candidate lesson is appended to a TRIAL copy and
    run through ic_expert_db_consistency_check (blindness / oracle-value /
    gate-override / structural) AND an explicit chip-deny-token scan (source_
    chip_agnostic_check does NOT walk agents/, so the DB path is uncovered — we
    reuse its _FORBIDDEN_TOKENS here). ANY finding => REFUSE, write nothing.
  * §4.05 / advisory boundary. A captured lesson is design-CRAFT ADVICE; it may
    never quote the oracle/harness/golden nor claim to override a gate (the
    consistency regexes enforce this).
  * NOT AUTONOMOUS. --write only stages an UNCOMMITTED working-tree edit (a git
    diff) + a capture_log.md line; it never commits or pushes. The repo-gatekeeper
    still reviews the diff and assigns the version. Default is DRY-RUN.

Usage:
  ic_expert_db_capture.py --ic-class <name> --lesson "<advice>" [--source dialogue]
  ic_expert_db_capture.py --ic-class <name> --lesson-file f.txt --write   # stage it
"""
from __future__ import annotations
import argparse, copy, json, sys, tempfile
import re as _re
from datetime import datetime, timezone
from pathlib import Path

import ic_expert_db_consistency_check as C
try:
    from source_chip_agnostic_check import _FORBIDDEN_TOKENS as _DENY
except Exception:  # noqa: BLE001 — best-effort; empty deny list falls back to consistency-only
    _DENY = tuple()

_HERE = Path(__file__).resolve().parent
_DEFAULT_DB = _HERE.parent / "agents" / "ic_expert_db" / "ic_expert_db.json"
_DEFAULT_LOG = _HERE.parent / "agents" / "ic_expert_db" / "capture_log.md"
_MIN_LESSON_CHARS = 40


def _deny_hits(text: str, tokens) -> list[str]:
    low = text
    hits = []
    for tok in tokens:
        if _re.search(r"\b" + _re.escape(tok) + r"\b", low, _re.I):
            hits.append(tok)
    return hits


def validate(db: dict, ic_class: str, lesson: str, deny_tokens=_DENY) -> list[str]:
    """Return a list of governance findings; empty list == safe to file."""
    findings: list[str] = []
    lesson = (lesson or "").strip()
    if len(lesson) < _MIN_LESSON_CHARS:
        findings.append(f"lesson too thin ({len(lesson)}<{_MIN_LESSON_CHARS} chars) — "
                        f"a captured lesson must be a substantive general insight")
    if not ic_class or not ic_class.strip():
        findings.append("ic_class is required")
    # chip-deny-token scan (agents/ is outside source_chip_agnostic_check's walk)
    for t in _deny_hits(lesson, deny_tokens):
        findings.append(f"chip-SPECIFIC token '{t}' in lesson — captures must be chip-AGNOSTIC")
    for t in _deny_hits(ic_class, deny_tokens):
        findings.append(f"chip-SPECIFIC token '{t}' in ic_class name")
    # trial-append then run the SHIP gate on the trial DB
    trial = copy.deepcopy(db)
    _apply(trial, ic_class, lesson)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(trial, tf, ensure_ascii=False)
        tpath = Path(tf.name)
    try:
        rep = C.check(tpath)
        for f in rep.get("findings", []):
            findings.append(f"consistency: {f}")
    finally:
        tpath.unlink(missing_ok=True)
    return findings


def _apply(db: dict, ic_class: str, lesson: str) -> None:
    """Append `lesson` to `ic_class` (create the entry if new); keep counts honest."""
    entries = db.setdefault("entries", [])
    for e in entries:
        if e.get("ic_class") == ic_class:
            e.setdefault("lessons", []).append(lesson)
            e["lesson_count"] = len(e["lessons"])
            break
    else:
        entries.append({"ic_class": ic_class, "lesson_count": 1, "lessons": [lesson]})
    db["classes"] = len(entries)
    db["total_lessons"] = sum(len(e.get("lessons", [])) for e in entries)


def _dump_db(db: dict, orig_text: str) -> str:
    body = json.dumps(db, ensure_ascii=False, indent=1)
    return body + ("\n" if orig_text.endswith("\n") else "")


def _log_line(source: str, ic_class: str, lesson: str, stamp: str) -> str:
    snippet = " ".join(lesson.split())[:90]
    return f"## [{stamp}] capture | source={source} ic_class={ic_class} | " \
           f"VALIDATED(consistency+deny) | {snippet}\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ic-class", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lesson")
    g.add_argument("--lesson-file", type=Path)
    ap.add_argument("--source", default="dialogue",
                    help="provenance for the capture_log (default: dialogue)")
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--log", type=Path, default=_DEFAULT_LOG)
    ap.add_argument("--deny-list", type=Path, default=None,
                    help="override the chip-deny-token file (default: the shipped list)")
    ap.add_argument("--write", action="store_true",
                    help="STAGE the lesson (uncommitted working-tree edit). Default: dry-run.")
    ap.add_argument("--stamp", default=None, help="log timestamp override (for reproducibility)")
    a = ap.parse_args(argv)

    # normalize ONCE so validate() checks EXACTLY what _apply() will write (no
    # validate-stripped / write-raw drift).
    raw = a.lesson if a.lesson is not None else a.lesson_file.read_text(errors="replace")
    lesson = raw.strip()
    orig = a.db.read_text()
    db = json.loads(orig)
    if not isinstance(db.get("entries"), list):
        print(f"REFUSE: --db {a.db} is not an IC Expert DB (no entries[] list) — NOTHING written.")
        return 1
    deny = _DENY
    if a.deny_list is not None:
        from source_chip_agnostic_check import _load_deny_tokens
        deny = _load_deny_tokens(a.deny_list)
    # FAIL-CLOSED: the chip-deny scan is the ONLY guard covering agents/ (source_
    # chip_agnostic_check does not walk it). An empty deny list — a stripped install,
    # a missing chip_deny_list.txt, or an import failure — silently disables that
    # guard, so REFUSE rather than stage content the log would falsely attest as
    # deny-validated.
    if not deny:
        print("REFUSE: chip-deny token list is unavailable/empty — cannot attest chip-AGNOSTIC "
              "(fail-closed). Restore programs/tests/chip_deny_list.txt. NOTHING written.")
        return 1

    findings = validate(db, a.ic_class, lesson, deny)
    if findings:
        print(f"REFUSE: candidate lesson for [{a.ic_class}] failed {len(findings)} governance "
              f"check(s) — NOTHING written:")
        for f in findings:
            print(f"  ! {f}")
        return 1

    if not a.write:
        print(f"DRY-RUN OK: [{a.ic_class}] lesson passes consistency + chip-deny. "
              f"Re-run with --write to STAGE it (a reviewable diff, NOT a commit).")
        return 0

    _apply(db, a.ic_class, lesson)
    a.db.write_text(_dump_db(db, orig))
    stamp = a.stamp or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    with a.log.open("a", encoding="utf-8") as fh:
        fh.write(_log_line(a.source, a.ic_class, lesson.strip(), stamp))
    print(f"STAGED [{a.ic_class}] (+1 lesson) in {a.db.name} and logged to {a.log.name}.")
    print("NOT committed. Review `git diff`, run ic_expert_db_consistency_check, and let the "
          "repo-gatekeeper review + version it before landing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
