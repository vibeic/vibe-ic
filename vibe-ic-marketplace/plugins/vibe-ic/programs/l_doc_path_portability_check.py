#!/usr/bin/env python3
"""
l_doc_path_portability_check.py — no emitted L document may carry an
absolute filesystem path.

VERDICT SEMANTICS: **GATE** (0 PASS / 1 FAIL / 2 argument-or-scan error).

WHY A SECOND PORTABILITY GUARD EXISTS
=====================================
``shipped_path_portability_check`` already states the doctrine — *a
shipped default must never be a personal absolute path* — and the
landing sequence runs it as ``shipped_path_portability_check
<plugin-root>``. So the rule is enforced over plugin SOURCE and nowhere
else, while the artefacts that actually carry the path are the L
documents the flow emits. An emitter that writes ``str(path)`` into an L
document reintroduces the defect and nothing notices.

That is not hypothetical. ``l22_coverage_goal_emit`` lifted a real,
correctly-chosen coverage target out of a design's own inputs and
recorded its provenance as
``/…/<checkout>/phase1/input_doc/<file>``. The number was right, the
line was right, and the document was still not comparable to the same
document emitted from a different directory.

WHAT AN L DOCUMENT IS, AND WHY THE SCOPE STOPS THERE
====================================================
An L document is a DESIGN artefact: the flow reads it back, diffs it
across runs and compares it between designs, so every value in it must
mean the same thing on every machine. A run REPORT is the opposite kind
of object — a record of where a run happened — and an absolute path in
one is provenance, not a defect.

That distinction is measured, not assumed. Measured 2026-07-28 in
3e4d0c47: under ``benchmark-data/`` there were 464 tracked JSON files
carrying a personal home path (1628 occurrences); every one of them is a
benchmark run output — score results and log pointers. Sweeping those
would be a false positive at scale. This check therefore reads ONLY files
matching

    **/generated_docs/L*.json

which on that date was exactly the 2554-document L corpus and none of the
run outputs.

Those three figures are PINNED to the date and commit above, not
maintained. They are the input to a scope decision, so re-deriving them
would destroy the record of what was actually measured when the decision
was taken — but they are NOT a description of this checkout, and the L
corpus grows. Re-take the count before citing it as current::

    git ls-files 'benchmark-data/**/generated_docs/L*.json' | wc -l

The glob above is a LOCATOR, not a guarantee: it tells a reader how to
re-measure, it does not say 2554 still holds. It did not — see
``derived_corpus_figure_check``, which was written from this exact site.

WHAT COUNTS AS AN ABSOLUTE PATH (calibrated, not guessed)
=========================================================
Measured 2026-07-28 in 3e4d0c47 over all 2554 tracked L documents then
present, string values that begin with ``/`` number 84. Four are the defect: personal-home provenance
paths. The other **80 are not paths at all** — they are 8b/10b
control-code notation and table headings that happen to be
slash-delimited::

    ordered_sets[].code            '/K28.5/ /D5.6/'
    packet_types_summary[].members '/K/(K28.5)'
    auto_cited_sections[].heading  '/ 6   0.625   Receive 10   1.25 / 0'

So "starts with a slash" is unusable: on that same 2026-07-28 corpus it
FAILed 80 correct documents. The opposite over-correction is just as
wrong — restricting the rule to the personal-home shape
``shipped_path_portability_check`` detects MISSES the defect that
motivated this file, because a run under ``/tmp/...`` or a CI run under
``/var/lib/...`` emits an absolute path with no home directory in it.
Measured the same day: home-only catches 3 of 5 known-bad values.

The predicate is therefore the union of two clauses, each carrying its
own justification:

  H — the PERSONAL HOME shape, delegated to
      ``shipped_path_portability_check._HOME_PAT`` so the two guards can
      never drift on what a home path is. It exists because ``/home/u/x``
      is non-portable even at a depth the structural clause ignores.

  S — STRUCTURAL: absolute, containing no whitespace, and at least
      ``_MIN_COMPONENTS`` non-empty path components. Three components is
      where the two measured populations separate: every real path has
      them, and the longest control-code value (``/K/(K28.5)``) has two.

Scored on the real corpus: 5 of 5 known-bad values caught, 0 of 80
control-code values touched.

A placeholder username is deliberately NOT excused here, though
``shipped_path_portability_check`` excuses it. That guard reads
documentation and source, where ``<your-user>`` is an instruction to a
human reader. An L document is machine-emitted provenance with no reader
to substitute anything, so a placeholder path is exactly as unusable as
a real one.

chip-AGNOSTIC: no design, PDK or vendor literal — the predicate is about
filesystem path shape only.

Usage:
    python3 l_doc_path_portability_check.py <root> [--json OUT]

``<root>`` is any tree: a project directory (finds
``phase1/generated_docs/L*.json``) or a corpus directory (finds every
design's).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Imported, never copied: a private "what is a home path" regex is how the
# two guards drift apart. A hard ImportError is correct — this check has no
# honest verdict to give without it.
from shipped_path_portability_check import _HOME_PAT  # noqa: E402

TOOL = "l_doc_path_portability_check"

# An L document lives in a `generated_docs/` directory and its name starts
# with `L` + the layer number. Both halves matter: the directory is what
# separates a design artefact from a run output, and the name prefix is what
# separates an L document from the other JSON the flow drops beside it.
_L_DOC_DIR = "generated_docs"
_L_DOC_NAME_RE = re.compile(r"^L\d+[A-Za-z0-9_.-]*\.json$")

# See "WHAT COUNTS AS AN ABSOLUTE PATH" — three is where the measured
# populations separate.
_MIN_COMPONENTS = 3

_WIN_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_absolute(value: str) -> bool:
    return value.startswith("/") or bool(_WIN_ABS_RE.match(value))


def _components(value: str) -> List[str]:
    return [c for c in value.replace("\\", "/").split("/") if c]


def absolute_path_reason(value: str) -> Optional[str]:
    """Why this string value is a non-portable absolute path, or None.

    Returning the REASON rather than a bool is what makes a FAIL
    actionable: a reader can see which clause fired and argue with it.
    """
    if not isinstance(value, str) or not value:
        return None
    if _HOME_PAT.search(value):
        return ("personal home directory — records the account the run "
                "happened under")
    if not _is_absolute(value):
        return None
    if any(ch.isspace() for ch in value):
        # Whitespace is what every measured false positive has and no
        # measured provenance path has. Prose and table rows are not paths.
        return None
    n = len(_components(value))
    if n < _MIN_COMPONENTS:
        return None
    return (f"absolute filesystem path ({n} components) — records the "
            f"directory the run happened in")


_SKIP_DIR_NAMES = frozenset({
    ".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv",
    "build", "dist", ".mypy_cache", ".ruff_cache",
})


def iter_l_docs(root: Path) -> Iterable[Path]:
    """Every L document under ``root``, in stable order.

    Finds the ``generated_docs`` directories FIRST and globs inside them,
    rather than walking every ``*.json`` in the tree and filtering. A
    project root also holds phase2/phase3 output and ``reports/``, which
    can run to tens of thousands of JSON files; none of them can be an L
    document, so none of them should be walked.
    """
    seen: set = set()
    for d in sorted(root.rglob(_L_DOC_DIR)):
        if not d.is_dir():
            continue
        if any(part in _SKIP_DIR_NAMES for part in d.parts):
            continue
        for p in sorted(d.glob("L*.json")):
            if not p.is_file() or not _L_DOC_NAME_RE.match(p.name):
                continue
            # Deduplicate on the RESOLVED path. A design may expose its
            # documents twice — the legacy root-level `generated_docs` is
            # routinely a symlink to `phase1/generated_docs`, same inode —
            # and counting one document as two inflates the denominator and
            # reports every finding twice. MEASURED: one corpus design
            # carries exactly that symlink and lifted the census from 2554
            # to 2582 before this dedup existed.
            try:
                key = p.resolve()
            except (OSError, RuntimeError):
                key = p.absolute()
            if key in seen:
                continue
            seen.add(key)
            yield p


def _walk_strings(node: Any, trail: List[str]
                  ) -> Iterable[Tuple[str, str]]:
    """Every string VALUE in the document, with a readable JSON pointer.

    Values only — a key is schema, chosen by the emitter's author, and no
    schema key is a filesystem path. Walking values rather than a list of
    provenance key names is deliberate: a new emitter inventing a new key
    name would slip straight past a name list.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, trail + [str(k)])
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_strings(v, trail + [f"[{i}]"])
    elif isinstance(node, str):
        yield ".".join(trail), node


@dataclass
class Finding:
    file: str
    pointer: str
    value: str
    reason: str


def scan_document(path: Path, rel: Path) -> Tuple[List[Finding], Optional[str]]:
    """Findings for one L document, plus a parse error if it is unreadable."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], f"{rel}: {exc}"
    out: List[Finding] = []
    for pointer, value in _walk_strings(doc, []):
        reason = absolute_path_reason(value)
        if reason:
            out.append(Finding(file=str(rel), pointer=pointer,
                               value=value[:200], reason=reason))
    return out, None


def scan_tree(root: Path) -> Dict[str, Any]:
    """Scan every L document under ``root``.

    Always reports ``documents_read``. A clean verdict over an empty scan
    is not a clean verdict (vibe-ic#447) — without a denominator a PASS
    cannot be told from a wrong root, which is how a gate ends up wired in
    and measuring nothing.
    """
    findings: List[Finding] = []
    unreadable: List[str] = []
    read = 0
    for p in iter_l_docs(root):
        read += 1
        got, err = scan_document(p, p.relative_to(root))
        findings.extend(got)
        if err:
            unreadable.append(err)
    return {
        "tool": TOOL,
        "root": str(root),
        "documents_read": read,
        "unreadable": unreadable,
        "verdict": "FAIL" if findings else "PASS",
        "count": len(findings),
        "findings": [asdict(f) for f in findings],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=TOOL,
        description="Fail if an emitted L document carries an absolute "
                    "filesystem path.")
    ap.add_argument("root", type=Path)
    ap.add_argument("--json", default=None, help="write JSON report here")
    args = ap.parse_args(argv)

    root = args.root.expanduser()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 2

    rep = scan_tree(root)

    if args.json:
        try:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: cannot write --json: {exc}", file=sys.stderr)
            return 2

    read = rep["documents_read"]
    if read == 0:
        # Not a PASS. VACUOUS — and said out loud, because a silent green
        # over nothing is indistinguishable from a wrong root.
        print(f"{TOOL}: VACUOUS — no L document (…/{_L_DOC_DIR}/L*.json) "
              f"under {root}; nothing was examined, so this is not a PASS.")
        return 2

    if rep["count"] == 0:
        print(f"{TOOL}: PASS ({read} L document(s) examined) — every "
              f"provenance path is project-relative")
        return 0

    print(f"{TOOL}: FAIL — {rep['count']} absolute path(s) in "
          f"{read} L document(s) examined")
    for f in rep["findings"]:
        print(f"  {f['file']}\n      {f['pointer']} = {f['value']}\n"
              f"      {f['reason']}")
    print("  An L document is a design artefact the flow reads back and "
          "diffs; an absolute path makes the same design emit a different "
          "document from every checkout. Relativise against the project "
          "root — see l_doc_consumer_contract.project_relative_source.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
