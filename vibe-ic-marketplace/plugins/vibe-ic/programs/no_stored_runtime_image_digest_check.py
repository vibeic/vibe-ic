#!/usr/bin/env python3
"""no_stored_runtime_image_digest_check.py — the runtime image's identity is
RESOLVED from the host; it is never STORED in this repository's Python source.

THE DEFECT THIS GUARDS
======================
A container-image digest copied into tracked source turns "adopt a newer
runtime image" into "edit this repository". That coupling was removed once by
name, and then quietly re-grew in THREE separate files — the plugin's pin
module, the CI hermetic runner, and the landing register — each as a plain
module-level constant:

    SOME_IMAGE_DIGEST = ("sha256:" + "<64 hex>")      # the shape, not a value

MEASURED BEFORE THE REMOVAL: the literal moved ONCE in ten days while eighteen
image versions shipped; nothing in the release loop touched it; and the drift
test that was supposed to protect it bound the copies to EACH OTHER rather than
to any image that exists — so every host tracking the current release reported a
mismatch from day zero, through no operator error. The stored copy was not a
safety property. It was a scheduled outage with a hand-edit as its only remedy.

THE RULE, IN ONE SENTENCE
=========================
A ``sha256:`` + 64-hex literal, in TRACKED PYTHON SOURCE, bound to a name that
refers to the runtime image, outside test / fixture / recorded-evidence venues.

Three predicates, all required at the SAME binding site:

  VALUE   the string literals the binding site is built from, CONCATENATED in
          source order, contain ``sha256:`` followed by 64 hex characters.
          Concatenating is what stops ``"sha256:" + "<64 hex>"`` — one line, the
          same value — from being a way around the first form. A BARE 64-hex run
          with no ``sha256:`` anywhere is NOT a finding: that is how a checksum
          is written, and this tree is full of honest ones.
  NAME    the name the value is stored UNDER has a WHOLE identifier segment out
          of `_IMAGE_SEGMENTS`. The surrounding name is what separates "the
          identity of the toolchain we run" from every other sha256 in a tree
          that also implements SHA-2 cores.
  SITE    the value is bound — an assignment target, or a ``return`` inside a
          function. Nothing else in a function body is judged under its name,
          which is what keeps a docstring that honestly records which image a
          measurement was taken on out of this.

WHY ``return`` IS A BINDING SITE — THE VACUITY THIS ROUND CLOSED
================================================================
The shape the three files were changed INTO is a FUNCTION. A guard that reads
only assignments is blind to its own regression: ONE hunk replacing
``resolved_image_digest()``'s ``raise`` with ``return "<digest>"`` restores the
coupling in full, and the guard still says PASS. So a ``return`` counts, judged
by its enclosing function's name — and by the string an enclosing ``if`` tested
on, because the other half of the real fix is PEP 562's module
``__getattr__`` (``if name == "IMAGE_DIGEST": return _resolve_digest()``,
tools/ci/hermetic_candidate_runner.py), where the name the value is served FOR
is in the test rather than in the function's own name. That branch context is
reset at every function boundary.

``except`` and ``match`` bodies are descended into explicitly, because neither
``ast.ExceptHandler`` nor ``ast.match_case`` is an ``ast.stmt`` subclass and a
plain "descend into statements" walk skips them silently — while "resolve from
the host, fall back to the stored value" is written in Python as exactly
``try: … except ImportError: IMAGE_DIGEST = "…"``.

PROSE CANNOT TRIP THIS, AND CANNOT CLEAR IT
===========================================
This tree is full of honest records — ``_eda_pin.py``'s own module docstring
carries the digest a 2026-09-07 measurement was taken on — and a guard that
fires on those is a guard someone deletes, taking the real rule with it. Prose
is excluded STRUCTURALLY, not by a list and not by a text filter: Python is read
through its ABSTRACT SYNTAX TREE, a comment does not survive parsing at all, and
a docstring is a bare expression statement that binds nothing, so it never
acquires a name to be judged under. Editing only a comment or a docstring can
therefore neither create a finding here nor clear one.

THE EXEMPTION IS A VENUE, NEVER A LIST OF FILES
===============================================
Fixtures and recorded evidence LEGITIMATELY name the image a past run used —
that is data describing something that happened, not configuration anything
reads to decide what to run. A list of the files that hold one today is wrong
the moment a sixth is written, so the exemption is structural: any path
component named tests/test/fixtures/testdata (or ending in ``fixtures``), and
any file named ``test_*`` / ``*_test`` / ``conftest.py``. No filename appears
anywhere in this program.

BOTH DEFENCES, MEASURED ON THE TREE THIS SHIPS AGAINST
======================================================
The venue holds 1567 non-exempt ``.py``, and exactly FOUR string literals in
them carry a ``sha256:`` + 64 hex. That is the whole population, and each is
accounted for:

  * TWO are module DOCSTRINGS — ``_eda_pin.py`` line 15 records the pin a
    2026-09-07 measurement was taken on, between double backticks, and
    ``flow_output_substance.py`` does the same. The AST is what keeps them out.
    (A whitespace "is this a sentence?" test on the literal was tried in an
    earlier round and MEASURED to suppress neither of them — the AST had
    already done it — while ONE added space, or a ``.strip()`` on the value,
    disarmed the rule with the defect left live. It is gone.)
  * TWO are the sha256 OF THE EMPTY FILE, spelled with its prefix, under
    ``EMPTY_FILE_SHA256`` and ``_EMPTY_SHA``. Only the NAME predicate keeps
    those out: switch it off and those two files — ordinary, correct source —
    turn a clean tree red.

Switching the VENUE exemption off instead reddens two more, both evidence:
``programs/tests/test_container_image_provenance.py:25 PINNED_ID`` and
``mcp-eda/test/test_restart_eda_pinned_default.py:250``. So neither exemption
is decoration, and neither is a list.

KNOWN CONSERVATISM — WHAT THIS DELIBERATELY DOES NOT SEE
========================================================
Each of these is a FALSE NEGATIVE accepted on purpose. Every one of them was an
available mechanism, and every mechanism this rule grew to chase an edge case
cost more than it bought. Missing a case is the cheaper mistake; mis-firing on
working code, or being disarmable by a one-line edit, is not.

  * SHELL, ENTIRELY. ``.sh`` is not opened. Shell has no AST here, so the
    prose-immunity above would have to be rebuilt out of a quote-tracking text
    stripper — and in THIS venue that is not theoretical: 34 shell files, and
    the house style embeds whole Python programs in quoted here-documents
    (``python3 - "$1" <<'PY'``). A line-oriented scanner mis-reads those as
    configuration; a here-doc tracker that mis-reads one line mutes the rest of
    the file. Both were measured in earlier rounds. So a digest stored in
    ``restart-eda.sh`` is invisible to this gate, and that is the price.
  * RECORDS. A digest moved into a tracked ``.json`` / ``.toml`` / ``.yml`` /
    Dockerfile / Makefile and read back restores the coupling in full, and this
    gate says PASS. Only files named ``*.py`` are opened, so an extensionless
    Python hook (``tools/git-hooks/pre-push``) is not read either.
  * A NAME THAT SAYS NOTHING. ``_D = "sha256:…"`` escapes, because the NAME
    predicate is the only thing that separates this from the honest checksums
    measured above. Its price is that a deliberately anonymous name is out of
    scope, and so is a wrapper whose own name says nothing
    (``def _d(): return "sha256:…"``).
  * A SPLIT THAT IS NOT A LITERAL. ``"sha256:" + HEX_CONST``, where the second
    half is a NAME rather than a literal, is not seen: only literal text is
    concatenated. (``"sha256:" + "<64 hex>"``, both halves literal, IS seen.)
  * PARAMETER DEFAULTS, walrus targets, ``yield``, and a digest passed straight
    into a call — ``add_argument("--image", default="sha256:…")``, or a
    decorator argument — are not binding sites here.
  * VENUE. Only the trees whose Python decides what this product RUNS are
    scanned (see DEFAULT_VENUES). Campaign and documentation trees are out of
    scope and do hold stored digests today — those are records of a campaign,
    and the verdict line names the venues it read rather than claiming the whole
    repository. ``--venue .`` sweeps everything for anyone who wants that.

Exit codes:
    0  PASS    — source was read, and no stored runtime-image digest is in it
    1  FAIL    — at least one stored digest, each named with file and line
    2  REFUSE  — the question could not be asked: the root is not a directory,
                 a declared venue is absent, no source file was read, or one
                 could not be read/parsed. "I could not look" never shares an
                 exit code with "I looked and it was clean".

Usage:
    python3 no_stored_runtime_image_digest_check.py [ROOT]
                                                    [--venue REL]...
                                                    [--json OUT]

chip-AGNOSTIC.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE name.
# Python puts a file's own directory on `sys.path` only when that file is run as
# `__main__`; under `importlib.util.spec_from_file_location` — how the gates and
# much of the suite load a program — it does not. Restore the condition this
# file is written for. Idempotent, same shape the sibling programs carry.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import argparse
import ast
import json
import re
import sys
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:                                    # optional: restricts the sweep to the
    import _published_tree as _pt       # PUBLISHED tree when there is one
except Exception:                       # pragma: no cover - standalone use
    _pt = None                          # type: ignore[assignment]

RC_PASS, RC_FAIL, RC_REFUSE = 0, 1, 2

CHECK_NAME = "no_stored_runtime_image_digest_check"

#: The tracked trees whose Python decides what this product runs: the two the
#: removed copies lived in, plus the plugin-side mirror of `tools` and the MCP
#: server that launches the same runtime. A venue stated as "where the copies
#: were" would miss a fourth copy written one directory over, which is the whole
#: failure mode this guards. `--venue` replaces the set for a caller that knows
#: better, and a venue that does not exist is REFUSED, never assumed.
DEFAULT_VENUES: Tuple[str, ...] = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs",
    "vibe-ic-marketplace/plugins/vibe-ic/tools",
    "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda",
    "tools",
)

#: A registry digest, written out. No bare-64-hex form: a run of 64 hex with no
#: `sha256:` in front of it is how a CHECKSUM is written, and this tree holds
#: many honest ones.
_DIGEST = re.compile(r"sha256:[0-9a-fA-F]{64}(?![0-9a-fA-F])")

#: An identifier SEGMENT equal to one of these refers to the runtime image.
#: WHOLE segments, not prefixes: `PING`, `PINOUT`, `EDAT`, `IMGUI` and
#: `CONTAINERD` merely BEGIN with one of these words and are not containers.
#: The PIN family is here because `_PIN`, `PIN_DIGEST`, `PINNED_ID` and
#: `_FALLBACK_PIN` are the likeliest regression spellings of the very file this
#: rule guards (`_eda_pin.py`), and `PINNED_ID` is what a live test module
#: already stores this identity under. It collides with this repository's chip
#: pins — MEASURED, 733 of the 1053 image-ish assignment sites in the venue
#: match ONLY via this family, every one of them a pin. That collision is
#: defused by the VALUE predicate, not by the vocabulary: a golden SHA-2 vector
#: under a pin name is written BARE, a bare run is not a finding, and measured,
#: none of those 733 sites holds one today.
_IMAGE_SEGMENTS = frozenset({
    "IMAGE", "IMAGES", "IMG", "IMGS",
    "CONTAINER", "CONTAINERS",
    "RUNTIME", "RUNTIMES",
    "TOOLCHAIN", "TOOLCHAINS",
    "DOCKER", "PODMAN", "OCI",
    "EDA",
    "PIN", "PINS", "PINNED",
})

#: Splits an identifier into segments across `_`, `-`, `.` and camelCase, so
#: `edaImageDigest`, `EDA_IMAGE_DIGEST` and `eda-image-digest` read alike.
_SEGMENT = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")

#: Evidence, not configuration — stated as venue, never as a list of files.
_EXEMPT_DIR_NAMES = {"tests", "test", "fixtures", "testdata", "test_data",
                     "__pycache__", "node_modules", ".git"}
_EXEMPT_FILE_NAMES = {"conftest.py"}


# ---------------------------------------------------------------------------
# predicates
# ---------------------------------------------------------------------------
def name_refers_to_the_runtime_image(name: str) -> bool:
    """Does `name` store the identity of the runtime image?

    True when any WHOLE segment of the identifier is one of `_IMAGE_SEGMENTS`.
    Segment-wise so that `EMPTY_FILE_SHA256` is not dragged in by a substring
    match; WHOLE-segment so that `PINOUT_SHA256`, `PING_PAYLOAD_SHA256`,
    `EDAT_HASH`, `IMGUI_BLOB_SHA` and `CONTAINERD_LOG_SHA` are not dragged in by
    a prefix match either.
    """
    return any(seg.upper() in _IMAGE_SEGMENTS
               for seg in _SEGMENT.findall(name or ""))


def literal_text(node: Optional[ast.AST]) -> str:
    """Every string literal under `node`, concatenated in SOURCE order.

    `IMAGE_DIGEST = "sha256:" + "<64 hex>"` is the same stored identity as
    `IMAGE_DIGEST = "sha256:<64 hex>"`, one line apart, so the two must not have
    different verdicts. Joining the literals is the whole of it: no rule about
    what a neighbouring field is called, and nothing a bare checksum can satisfy
    — `X = "<64 hex>"` joins to itself and still carries no `sha256:`.
    """
    if node is None:
        return ""
    parts = [(getattr(n, "lineno", 0), getattr(n, "col_offset", 0), n.value)
             for n in ast.walk(node)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return "".join(text for _, _, text in sorted(parts))


def digest_in(node: Optional[ast.AST]) -> Optional[str]:
    """The registry digest this bound value carries, or None."""
    m = _DIGEST.search(literal_text(node))
    return m.group(0) if m else None


@dataclass
class Finding:
    path: str
    line: int
    name: str
    digest: str

    def line_of(self) -> str:
        return f"{self.path}:{self.line}: {self.name} = <{self.digest[:19]}…>"


# ---------------------------------------------------------------------------
# Python: read through the AST, so prose is structurally unable to participate
# ---------------------------------------------------------------------------
def _target_names(node: ast.AST) -> List[str]:
    """Every name an assignment stores UNDER, including subscript keys.

    `CFG["eda_image"] = "sha256:…"` stores under a string key, and that key is
    as much "the surrounding name" as an identifier is.
    """
    if isinstance(node, ast.Assign):
        targets: Sequence[ast.AST] = node.targets
    else:                                       # AnnAssign / AugAssign
        targets = [node.target]                 # type: ignore[attr-defined]
    names: List[str] = []
    for t in targets:
        for sub in ast.walk(t):
            if isinstance(sub, ast.Name):
                names.append(sub.id)
            elif isinstance(sub, ast.Attribute):
                names.append(sub.attr)
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                names.append(sub.value)
    return names


def _record(out: List[Finding], rel: str, lineno: int, names: Sequence[str],
            value: Optional[ast.AST], label: Optional[str] = None) -> None:
    """Judge ONE binding site: the conjunction, and at most one finding."""
    matched = [n for n in names if name_refers_to_the_runtime_image(n)]
    if not matched:
        return
    digest = digest_in(value)
    if digest:
        out.append(Finding(rel, lineno, label or matched[0], digest))


def _if_strings(node: ast.AST) -> Tuple[str, ...]:
    """The string literals an `if` test selects ON.

    `if name == "IMAGE_DIGEST": return "<digest>"` is PEP 562's module
    `__getattr__` — half of the real fix — and the name the value is served FOR
    is in the test, not in the function's own name.
    """
    return tuple(c.value for c in ast.walk(node.test)   # type: ignore[attr-defined]
                 if isinstance(c, ast.Constant) and isinstance(c.value, str))


def _collect(body: Sequence[ast.AST], rel: str, out: List[Finding],
             func: Optional[str] = None, guard: Tuple[str, ...] = ()) -> None:
    """Walk statements, recording every BINDING SITE that can hold a literal.

    `func` is the enclosing function's name, which is what a `return` is judged
    by; it is re-set (and `guard` cleared) at every function boundary, because a
    branch is about its branch and a name is about its function.
    """
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _collect(node.body, rel, out, func=node.name, guard=())
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            _record(out, rel, node.lineno, _target_names(node), node.value)
        elif isinstance(node, ast.Return) and func:
            _record(out, rel, node.lineno, [func, *guard], node.value,
                    label=f"{func}() -> literal")
        taken = _if_strings(node) if isinstance(node, ast.If) else ()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                inside = taken if any(child is b for b in node.body) else ()
                _collect([child], rel, out, func, guard + inside)
            elif isinstance(child, (ast.ExceptHandler, ast.match_case)):
                # NEITHER is an `ast.stmt`, so the branch above cannot see them
                # — and `try: … except ImportError: IMAGE_DIGEST = "…"` is how
                # "fall back to the stored value" is spelled in Python.
                _collect(child.body, rel, out, func, guard)


def scan_python(rel: str, text: str) -> List[Finding]:
    """Findings in one Python source. Raises SyntaxError if it will not parse.

    Warnings raised while parsing belong to the file being READ, not to this
    audit: a scanned file with a stray ``\\s`` in a non-raw string would
    otherwise print a `SyntaxWarning` above this program's own verdict, on the
    same channel a refusal uses. A real `SyntaxError` still propagates, and is
    what makes the file a REFUSE rather than a silent skip.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(text)
    out: List[Finding] = []
    _collect(tree.body, rel, out)
    seen: set = set()
    uniq: List[Finding] = []
    for f in out:
        key = (f.line, f.name, f.digest)
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq


# ---------------------------------------------------------------------------
# venue
# ---------------------------------------------------------------------------
def is_exempt(rel_parts: Sequence[str]) -> bool:
    """Evidence, by VENUE — never by a list of filenames."""
    for part in rel_parts[:-1]:
        low = part.lower()
        if low in _EXEMPT_DIR_NAMES or low.endswith("fixtures"):
            return True
    name = rel_parts[-1]
    if name in _EXEMPT_FILE_NAMES:
        return True
    stem = name[:-3] if name.endswith(".py") else name
    return stem.startswith("test_") or stem.endswith("_test")


def scan(root: str, venues: Sequence[str] = DEFAULT_VENUES
         ) -> Tuple[List[Finding], Dict[str, object]]:
    """Return (findings, statistics). Statistics ARE the denominator."""
    r = Path(root)
    stats: Dict[str, object] = {
        "root": str(r), "venues_declared": list(venues), "venues_present": [],
        "venues_missing": [], "files_considered": 0, "files_scanned": 0,
        "files_exempt": 0, "files_unreadable": [], "files_unparseable": [],
        "enumeration": "filesystem-walk",
    }
    if not r.is_dir():
        stats["refusal"] = f"root is not a directory: {root!r}"
        return [], stats

    present: List[Path] = []
    for rel in venues:
        d = (r / rel) if rel not in (".", "") else r
        if d.is_dir():
            present.append(d)
        else:
            stats["venues_missing"].append(rel)      # type: ignore[union-attr]
    stats["venues_present"] = [str(p) for p in present]

    published = None
    if _pt is not None:
        try:
            published = _pt.published_paths(r)
        except Exception:                                 # pragma: no cover
            published = None
    if published is not None:
        stats["enumeration"] = "git-tracked"

    # Resolved once: `rel` must be spelled the way the published set spells
    # it, which is relative to the RESOLVED root.
    r_res = r.resolve()
    findings: List[Finding] = []
    seen: set = set()
    for base in present:
        for path in sorted(base.rglob("*.py")):
            if not path.is_file():
                continue
            try:
                rel = path.resolve().relative_to(r_res).as_posix()
            except ValueError:                            # pragma: no cover
                rel = str(path)
            if rel in seen:
                continue
            seen.add(rel)
            stats["files_considered"] = int(stats["files_considered"]) + 1
            if is_exempt(Path(rel).parts):
                stats["files_exempt"] = int(stats["files_exempt"]) + 1
                continue
            # `published` is a frozenset of tracked relative paths, asked for
            # ONCE. Per-file `filter_to_published` would re-run git for every
            # file, and the answer cannot change mid-audit anyway.
            if published is not None and rel not in published:
                continue
            # NOTE: this file DESCRIBES the shape it forbids and is NOT excluded
            # from the sweep. An earlier draft skipped it by path; measured, the
            # exclusion suppressed ZERO findings, because every digest here is a
            # placeholder or a regex and none is bound to an image-ish name. A
            # permanent blind spot inside the venue is not worth a saving of
            # nothing.
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                stats["files_unreadable"].append(rel)     # type: ignore[union-attr]
                continue
            stats["files_scanned"] = int(stats["files_scanned"]) + 1
            try:
                findings.extend(scan_python(rel, text))
            except SyntaxError as exc:
                stats["files_unparseable"].append(        # type: ignore[union-attr]
                    f"{rel}: {exc}")
    return findings, stats


# ---------------------------------------------------------------------------
def _refuse(why: str) -> int:
    """NO VERDICT, said in both channels.

    stdout carries it because a caller reading only the verdict line must not
    mistake a refusal for a PASS; stderr carries it because the shell gate
    harness surfaces stderr for a non-zero rc. Neither channel alone reaches
    both readers, and a refusal that only one reader sees is how "I could not
    look" gets filed as "I looked and it was clean".
    """
    print(f"[REFUSE] {CHECK_NAME}: {why}")
    print(f"REFUSE: {why}", file=sys.stderr)
    return RC_REFUSE


def _verdict(findings: Sequence[Finding], stats: Dict[str, object],
             venues: Sequence[str]) -> Tuple[str, Optional[str]]:
    """(verdict, refused_because) — decided BEFORE anything is written out.

    The machine channel has to be able to tell "I looked and it was clean" from
    "I could not look"; deciding here is what lets `--json` carry the same
    three-way answer the exit code does.
    """
    if findings:
        return "FAIL", None
    if "refusal" in stats:
        return "REFUSE", str(stats["refusal"])
    if stats["venues_missing"]:
        return "REFUSE", (
            f"declared venue(s) absent under {stats['root']!r}: "
            f"{stats['venues_missing']}. A venue that is not there was not "
            f"searched; point ROOT at the repository root, or name the venues "
            f"with --venue.")
    if int(stats["files_scanned"]) == 0:
        return "REFUSE", (
            "no Python source file was read under "
            f"{', '.join(stats['venues_present']) or '(none)'!r}. This is NOT "
            f"a clean bill of health — nothing was searched.")
    blind = list(stats["files_unreadable"]) + list(  # type: ignore[arg-type]
        stats["files_unparseable"])                 # type: ignore[arg-type]
    if blind:
        return "REFUSE", (f"{len(blind)} file(s) could not be read or parsed, "
                          f"so they were never searched: {blind[:5]}")
    return "PASS", None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("root", nargs="?", default=".",
                    help="repository root holding the scanned venues")
    ap.add_argument("--venue", action="append", dest="venues", default=None,
                    metavar="REL",
                    help=("venue relative to ROOT; repeatable. Default: "
                          + " and ".join(DEFAULT_VENUES)))
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the full machine record here")
    args = ap.parse_args(list(argv) if argv is not None else sys.argv[1:])

    venues = tuple(args.venues) if args.venues else DEFAULT_VENUES
    findings, stats = scan(args.root, venues)
    verdict, refused_because = _verdict(findings, stats, venues)

    record = {"check": CHECK_NAME,
              "verdict": verdict,
              "refused_because": refused_because,
              "findings": [asdict(f) for f in findings],
              "stats": stats}
    if args.json_out:
        try:
            Path(args.json_out).write_text(json.dumps(record, indent=2),
                                           encoding="utf-8")
        except OSError as exc:
            return _refuse(f"cannot write --json {args.json_out}: {exc}")

    scanned = int(stats["files_scanned"])
    where = ", ".join(stats["venues_present"]) or "(none)"   # type: ignore[arg-type]
    denom = (f"{scanned} Python source file(s) read "
             f"[{stats['enumeration']}]; "
             f"{stats['files_exempt']} exempt by venue; venue: {where}")

    if verdict == "FAIL":
        for f in findings:
            print(f.line_of())
        print(f"[FAIL] {CHECK_NAME}: {len(findings)} stored runtime-image "
              f"digest(s) in tracked source — the image identity must be "
              f"RESOLVED from the host, not remembered here, or every image "
              f"release needs an edit to this repository; {denom}")
        return RC_FAIL

    if verdict == "REFUSE":
        why = str(refused_because)
        return _refuse(why if scanned == 0 or "refusal" in stats
                       else f"{why}; {denom}")

    # Scoped to what was READ. The venue is narrower than the repository, and
    # Python is narrower than the venue (see KNOWN CONSERVATISM); a headline
    # wider than its denominator is the false certificate this program refuses.
    print(f"[PASS] {CHECK_NAME}: no runtime-image digest is stored in the "
          f"Python of the scanned venues; {denom}")
    return RC_PASS


if __name__ == "__main__":
    raise SystemExit(main())
