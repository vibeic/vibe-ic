#!/usr/bin/env python3
"""programs/defect_artifact_fixture_check.py — v0.2.98

Deterministic pre-close gate for the core-agent loop (issue #478, Bucket A
half 2; snapshot-preference added for issue #487, LOW).

WHY THIS EXISTS
---------------
The #460/#466 reopens shared a second failure mode: the regression test the
core agent added "to lock the fix" only asserted that a bridge FILE existed
— it never built a defect-artifact fixture shaped like the issue's 現象, and
never executed the real program/gate to assert an END STATE. A file-existence
assertion passes trivially and proves nothing about behaviour, so the field
agent's end-to-end acceptance run still flipped.

This program enforces the acceptance doctrine on the regression test SOURCE,
deterministically. Given an issue body that carries a "## 驗收"/acceptance
section and the path to the new regression test, it asserts the test:

  (a) DEFECT-ARTIFACT FIXTURE — constructs or loads a fixture shaped like the
      issue's named artifacts (a tmp_path / tmpdir write, a fixture-builder
      reference, or a load of a named artifact the issue mentions), AND
  (b) END-STATE ASSERTION — invokes the real program/gate (a
      `subprocess.run(...)` of the named program, OR an import + call of its
      `main(...)` / `audit(...)` entry point) and asserts on its verdict /
      return code — NOT merely that some output file exists.

Issues with NO acceptance section are vacuous (exit 0): there is nothing the
regression test must replay end-to-end.

This program is chip-AGNOSTIC: it inspects the STRUCTURE of the test source
(AST + regex) and the markdown structure of the issue body. It contains no
chip / vendor / SKU literal in its detection logic.

DETECTION RULES (necessarily heuristic — kept structural + documented)
----------------------------------------------------------------------
Detection runs over the AST of the test file, falling back to regex when the
file does not parse.

(a) DEFECT-ARTIFACT FIXTURE — at least one of:
    F1  a `tmp_path` / `tmpdir` pytest fixture is used AND a write happens
        through it (`(tmp_path / "...").write_text(...)`, `.write_bytes`,
        `open(... , "w")`, `Path(...).write_text`), i.e. the test SHAPES an
        artifact rather than only reading a checked-in one;
    F2  a call to a fixture/artifact builder — a function whose name
        contains one of: build / make / emit / write / create / fixture /
        artifact / scaffold / setup_ + (defect | artifact | fixture | case
        | repro) — or an explicit `*_fixture` helper;
    F3  the test references, by string literal, an artifact NAME that the
        issue body names (path-like or quoted filename in the 現象 /
        acceptance text), proving the fixture mirrors the issue's shape.

(b) END-STATE ASSERTION — at least one of:
    E1  a `subprocess.run([...])` / `subprocess.check_call` / `check_output`
        / `Popen` whose argv references a program file (a `*.py` /
        `programs/...` / a runner verb) AND an assertion on the result's
        `.returncode` / `.stdout` / `.stderr` (a verdict),
        OR a `pytest.raises(SystemExit)` / assertion on an exit code
        captured from the program;
    E2  an import of (or call to) the named program's `main(...)` /
        `audit(...)` / `evaluate(...)` / `run(...)` entry point with an
        assertion on its return value (verdict / rc).
    A test whose ONLY assertions are `*.exists()` / `*.is_file()` /
    `os.path.exists(...)` (no program invocation + verdict assert) FAILS (b):
    file-existence-only is the exact #460/#466 anti-pattern.

SNAPSHOT PREFERENCE (issue #487, LOW)
-------------------------------------
Run dirs evolve between filing and verification: a cited LIVE artifact can
be replaced by a healthy rerun before the verifier dereferences it, so a
fixture bound to a mutable live path silently rots. When the FILER has
frozen the defect artifact with `defect_artifact_snapshot.py` (writing an
immutable copy + manifest.json under the archive convention
`<repo-root>/community/captures/<slug>/`), the issue body should name BOTH
the live path AND the snapshot path in its 證據區.

DETECTION RULE (snapshot wins over the mutable live file):
    S1  the issue body names a SNAPSHOT path — a path under
        `community/captures/<slug>/` (the archive convention), recognised
        structurally (the `community/captures/` path segment), OR
    S2  a snapshot ARCHIVE exists on disk for this issue per the
        convention — `<repo-root>/community/captures/<slug>/manifest.json`
        whose `issue_ref`/`issue_number`/`slug` matches an issue-named
        token — even if the body only names the live path.

When a snapshot is detected, `resolve_defect_artifact_source()` returns the
SNAPSHOT path as the accepted defect-artifact source (and, when the
archive's manifest is present, re-verifies the captured file's sha256
against the manifest so the resolution is to FROZEN content, not whatever
the live path currently holds). For (a) DEFECT-ARTIFACT FIXTURE, a test
that references the SNAPSHOT path (F3) satisfies the rule, and the verdict
no longer depends on the mutated live file. When NO snapshot exists, the
current behaviour is unchanged: the live-path / tmp-fixture rules apply.

EXIT CODES
----------
  0  PASS  — no acceptance section (vacuous SKIP), or the test satisfies
            both (a) and (b).
  1  FAIL  — acceptance section present but the test is missing (a) and/or
            (b); the named gaps are printed.
  2  usage / I/O error (bad args, missing file, unparseable + no regex hit
            on a hard-required input).

OPTIONAL OUTPUT
---------------
  --json PATH   write a machine-readable verdict report.

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Set, Tuple


# --------------------------------------------------------------------------
# Acceptance-section reuse (same structural cue as program 1, inlined to
# keep this program standalone / importable on its own).
# --------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_ACCEPTANCE_HEADING_TOKEN_RE = re.compile(r"驗收|acceptance", re.IGNORECASE)


def has_acceptance_section(body: str) -> bool:
    for m in _HEADING_RE.finditer(body):
        if _ACCEPTANCE_HEADING_TOKEN_RE.search(m.group(2)):
            return True
    return False


# Artifact-name literals the issue names: path-like tokens or quoted
# filenames anywhere in the body. chip-AGNOSTIC: shape-based, not SKU-based.
_ARTIFACT_NAME_RE = re.compile(
    r"`([^`\n]*?[/.][^`\n]*?)`"               # inline-code with a / or .
    r"|(?<![\w/])([\w./-]+\.(?:json|xml|log|flag|v|sv|def|gds|"
    r"lef|lib|rpt|txt|csv|yaml|yml|tcl|spice|sp|cir))",
)


def issue_artifact_names(body: str) -> Set[str]:
    names: Set[str] = set()
    for m in _ARTIFACT_NAME_RE.finditer(body):
        tok = m.group(1) or m.group(2) or ""
        tok = tok.strip()
        if not tok:
            continue
        # Keep the basename too — tests often reference just the file.
        names.add(tok)
        base = tok.rstrip("/").split("/")[-1]
        if base:
            names.add(base)
    return names


# --------------------------------------------------------------------------
# Snapshot preference (issue #487) — resolve the FROZEN defect artifact
# in preference to the mutable live run-dir path.
# --------------------------------------------------------------------------
# Archive convention from defect_artifact_snapshot.py:
#   <repo-root>/community/captures/<slug>/<basename>  (+ manifest.json)
_CAPTURES_SEGMENT = "community/captures/"
# A snapshot path token in the issue body: any path that traverses the
# capture archive segment. chip-AGNOSTIC: matches the path SHAPE only.
_SNAPSHOT_PATH_RE = re.compile(
    r"`?([\w./\-]*community/captures/[\w./\-]+)`?",
)
# Live-path heuristic: a path-like token that is NOT under the capture
# archive (so we can tell "names BOTH a live and a snapshot path").
_PATHLIKE_RE = re.compile(r"`?((?:/|\./|\.\./)?[\w./\-]+/[\w./\-]+)`?")

# Issue-ref tokens, used to match an on-disk archive to this issue when the
# body only names the live path (S2).
_ISSUE_NUM_RE = re.compile(r"#(\d{1,7})\b")


def _find_repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """Canonical repo root: prefer the git-toplevel ancestor that also has a
    `community/` dir (the marketplace mirror lacks `.git`), then the first
    ancestor with `community/`."""
    here = (start or Path(__file__)).resolve()
    first_community: Optional[Path] = None
    for anc in here.parents:
        has_community = (anc / "community").is_dir()
        if has_community and first_community is None:
            first_community = anc
        if has_community and (anc / ".git").exists():
            return anc
    return first_community


def snapshot_paths_in_body(body: str) -> List[str]:
    """All capture-archive paths named in the issue body (S1)."""
    out: List[str] = []
    for m in _SNAPSHOT_PATH_RE.finditer(body):
        tok = (m.group(1) or "").strip()
        if tok and tok not in out:
            out.append(tok)
    return out


def live_paths_in_body(body: str, snapshot_paths: List[str]) -> List[str]:
    """Path-like tokens that are NOT under the capture archive — the LIVE
    run-dir paths the issue cites as defect evidence."""
    snaps = set(snapshot_paths)
    out: List[str] = []
    for m in _PATHLIKE_RE.finditer(body):
        tok = (m.group(1) or "").strip()
        if not tok or _CAPTURES_SEGMENT in tok:
            continue
        if tok in snaps or tok in out:
            continue
        out.append(tok)
    return out


def _archive_for_issue(body: str, repo_root: Optional[Path]
                       ) -> Optional[Path]:
    """S2 — find an on-disk capture archive whose manifest matches an
    issue-named token (issue number/slug), even if the body only cites the
    live path."""
    root = repo_root or _find_repo_root()
    if root is None:
        return None
    captures = root / "community" / "captures"
    if not captures.is_dir():
        return None

    # Tokens to match: every `#<n>` issue number and the basenames of any
    # snapshot paths named in the body.
    nums = {m.group(1) for m in _ISSUE_NUM_RE.finditer(body)}
    snap_dirs = set()
    for sp in snapshot_paths_in_body(body):
        # the directory just under community/captures/
        parts = sp.split(_CAPTURES_SEGMENT, 1)
        if len(parts) == 2 and parts[1]:
            snap_dirs.add(parts[1].split("/", 1)[0])

    for child in sorted(captures.iterdir()):
        if not child.is_dir():
            continue
        if child.name in snap_dirs:
            return child
        man = child / "manifest.json"
        if not man.is_file():
            # match by directory-name convention issue-<n>-...
            for n in nums:
                if child.name == f"issue-{n}" or \
                        child.name.startswith(f"issue-{n}-"):
                    return child
            continue
        try:
            data = json.loads(man.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        in_ = str(data.get("issue_number") or "")
        ref = str(data.get("issue_ref") or "")
        if in_ and in_ in nums:
            return child
        for n in nums:
            if ref in (f"#{n}", n):
                return child
    return None


@dataclass
class SnapshotResolution:
    has_snapshot: bool = False
    has_live: bool = False
    snapshot_path: str = ""          # accepted defect-artifact source
    live_paths: List[str] = field(default_factory=list)
    archive_dir: str = ""
    sha256_verified: Optional[bool] = None   # None=not checked on disk
    notes: List[str] = field(default_factory=list)

    @property
    def prefer_snapshot(self) -> bool:
        return self.has_snapshot


def resolve_defect_artifact_source(
        body: str, repo_root: Optional[Path] = None) -> SnapshotResolution:
    """Return which defect-artifact SOURCE the fixture should bind to.

    When a snapshot is detected (S1: a `community/captures/...` path in the
    body, OR S2: an archive on disk matching this issue), the SNAPSHOT path
    is the accepted source — preferred over the mutable live path — and,
    when the archive's manifest.json is present, the captured file's sha256
    is re-verified against the manifest so resolution is to FROZEN content.
    """
    res = SnapshotResolution()
    snaps = snapshot_paths_in_body(body)
    lives = live_paths_in_body(body, snaps)
    res.live_paths = lives
    res.has_live = bool(lives)

    chosen: str = ""
    archive: Optional[Path] = None

    if snaps:
        res.has_snapshot = True
        chosen = snaps[0]
        res.notes.append("S1: snapshot path named in issue body")
    else:
        archive = _archive_for_issue(body, repo_root)
        if archive is not None:
            res.has_snapshot = True
            res.notes.append(
                "S2: capture archive on disk matches this issue "
                "(body cites only the live path)")

    # Resolve the on-disk archive (for both S1 and S2) to verify sha256.
    root = repo_root or _find_repo_root()
    if archive is None and chosen and root is not None:
        # chosen is a repo-relative or absolute snapshot path → archive dir
        seg = chosen.split(_CAPTURES_SEGMENT, 1)
        if len(seg) == 2 and seg[1]:
            slug = seg[1].split("/", 1)[0]
            cand = root / "community" / "captures" / slug
            if cand.is_dir():
                archive = cand

    if archive is not None:
        res.archive_dir = str(archive)
        if not chosen:
            # S2: pick the first captured member from the manifest as the
            # accepted snapshot path.
            man = archive / "manifest.json"
            if man.is_file():
                try:
                    data = json.loads(man.read_text(encoding="utf-8"))
                    arts = data.get("artifacts") or []
                    if arts:
                        chosen = arts[0].get("snapshot_rel") or \
                            arts[0].get("snapshot_path") or ""
                except (OSError, ValueError):
                    pass
        res.sha256_verified = _verify_archive_sha256(archive)
        if res.sha256_verified is False:
            res.notes.append(
                "WARNING: a captured file's sha256 no longer matches the "
                "manifest — the snapshot archive itself was mutated")

    res.snapshot_path = chosen
    return res


def _verify_archive_sha256(archive: Path) -> Optional[bool]:
    """Re-hash each captured member and compare to the manifest. Returns
    True (all match), False (a mismatch), or None (no manifest / no
    captured members to verify)."""
    man = archive / "manifest.json"
    if not man.is_file():
        return None
    try:
        data = json.loads(man.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    arts = data.get("artifacts") or []
    checked = False
    for a in arts:
        sp = a.get("snapshot_path") or ""
        expect = a.get("sha256") or ""
        if not sp or not expect:
            # fall back to basename within the archive
            base = a.get("basename") or ""
            if base:
                sp = str(archive / base)
        p = Path(sp)
        if not p.is_file():
            continue
        checked = True
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        got = "sha256:" + h.hexdigest()
        if got != expect:
            return False
    return True if checked else None


# --------------------------------------------------------------------------
# AST-based detection on the test source
# --------------------------------------------------------------------------
_WRITE_METHODS = {"write_text", "write_bytes"}
_SUBPROCESS_RUNNERS = {"run", "check_call", "check_output", "Popen", "call"}
_PROGRAM_ENTRYPOINTS = {"main", "audit", "evaluate", "run"}
_EXIST_METHODS = {"exists", "is_file", "is_dir"}

_BUILDER_NAME_RE = re.compile(
    r"(build|make|emit|write|create|scaffold|setup_).*"
    r"(defect|artifact|fixture|case|repro|bug)"
    r"|(defect|artifact|repro|bug).*(fixture|artifact|case)"
    r"|_fixture$|^fixture_|make_fixture|build_fixture",
    re.IGNORECASE,
)

_RUNNER_VERB_RE = re.compile(
    r"\b(python3?|pytest|bash|sh|make|gh|git)\b|\.py\b|programs/|\./",
)


@dataclass
class FixtureSignals:
    f1_tmp_write: bool = False
    f2_builder_ref: bool = False
    f3_artifact_name: bool = False
    builder_names: List[str] = field(default_factory=list)
    matched_artifacts: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.f1_tmp_write or self.f2_builder_ref or self.f3_artifact_name


@dataclass
class EndStateSignals:
    e1_subprocess_verdict: bool = False
    e2_entrypoint_call: bool = False
    has_subprocess_call: bool = False
    has_returncode_assert: bool = False
    has_entrypoint_call: bool = False
    exists_only: bool = False

    @property
    def ok(self) -> bool:
        return self.e1_subprocess_verdict or self.e2_entrypoint_call


def _attr_chain(node: ast.AST) -> str:
    """Return a dotted attribute chain like 'subprocess.run' or 'tmp_path'."""
    parts: List[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _string_literals(node: ast.AST) -> List[str]:
    out: List[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def _analyze_ast(tree: ast.AST, artifact_names: Set[str],
                 source: str) -> Tuple[FixtureSignals, EndStateSignals]:
    fx = FixtureSignals()
    es = EndStateSignals()

    uses_tmp = False
    tmp_write = False
    has_exists_assert = False
    has_other_assert = False

    # Track imported entrypoint names from the program (e.g.
    # `from acceptance_evidence_in_fix_comment_check import main`).
    imported_entrypoints: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for alias in n.names:
                nm = alias.asname or alias.name
                if alias.name in _PROGRAM_ENTRYPOINTS:
                    imported_entrypoints.add(nm)

    for n in ast.walk(tree):
        # tmp_path / tmpdir usage anywhere.
        if isinstance(n, ast.Name) and n.id in ("tmp_path", "tmpdir"):
            uses_tmp = True

        # Calls.
        if isinstance(n, ast.Call):
            func = n.func
            chain = _attr_chain(func) if isinstance(
                func, (ast.Attribute, ast.Name)) else ""

            # F1: a write through a path expression.
            if isinstance(func, ast.Attribute) and \
                    func.attr in _WRITE_METHODS:
                # Heuristic: the receiver references tmp_path/tmpdir OR a
                # Path(...) construction => the test SHAPES an artifact.
                recv_src = _segment(source, func.value)
                if ("tmp_path" in recv_src or "tmpdir" in recv_src
                        or "Path(" in recv_src):
                    tmp_write = True
            # open(..., "w") writing.
            if chain == "open":
                for a in n.args[1:]:
                    if isinstance(a, ast.Constant) and \
                            isinstance(a.value, str) and \
                            "w" in a.value:
                        recv_src = _segment(source, n)
                        if "tmp_path" in recv_src or "tmpdir" in recv_src:
                            tmp_write = True

            # F2: a builder-named call.
            callee = chain.split(".")[-1] if chain else ""
            if callee and _BUILDER_NAME_RE.search(callee):
                fx.f2_builder_ref = True
                fx.builder_names.append(callee)

            # E1: subprocess invocation of a program.
            if chain.startswith("subprocess.") and \
                    chain.split(".")[-1] in _SUBPROCESS_RUNNERS:
                argv_strs = _string_literals(n)
                if any(_RUNNER_VERB_RE.search(s) for s in argv_strs):
                    es.has_subprocess_call = True

            # E2: import-and-call of a program entrypoint with capture.
            if callee in _PROGRAM_ENTRYPOINTS and \
                    (callee in imported_entrypoints
                     or "." in chain  # module.main(...)
                     or callee in imported_entrypoints):
                es.has_entrypoint_call = True

        # Assertions.
        if isinstance(n, ast.Assert):
            seg = _segment(source, n.test)
            # exists-only detection.
            is_exists = any(
                isinstance(c, ast.Attribute) and c.attr in _EXIST_METHODS
                for c in ast.walk(n.test)
            ) or "os.path.exists" in seg
            mentions_verdict = bool(re.search(
                r"returncode|return_code|\.rc\b|\brc\b|stdout|stderr|"
                r"exit|verdict|PASS|FAIL|==\s*0|==\s*1|!=\s*0",
                seg))
            if is_exists and not mentions_verdict:
                has_exists_assert = True
            else:
                has_other_assert = True
            if mentions_verdict:
                es.has_returncode_assert = True

        # pytest.raises(SystemExit) → capturing an exit code.
        if isinstance(n, ast.Call):
            ch = _attr_chain(n.func) if isinstance(
                n.func, (ast.Attribute, ast.Name)) else ""
            if ch.endswith("raises"):
                for a in n.args:
                    seg = _segment(source, a)
                    if "SystemExit" in seg:
                        es.has_returncode_assert = True

    # F3: artifact-name literal cross-ref.
    src_strings = set(_string_literals(tree))
    for art in artifact_names:
        if not art:
            continue
        # Match either the exact name or its basename appearing in any
        # test string literal.
        for s in src_strings:
            if art in s or s in art and len(s) > 3:
                fx.f3_artifact_name = True
                fx.matched_artifacts.append(art)
                break

    fx.f1_tmp_write = uses_tmp and tmp_write

    es.e1_subprocess_verdict = (
        es.has_subprocess_call and es.has_returncode_assert)
    es.e2_entrypoint_call = (
        es.has_entrypoint_call and es.has_returncode_assert)
    es.exists_only = has_exists_assert and not (
        has_other_assert or es.ok)

    return fx, es


def _segment(source: str, node: ast.AST) -> str:
    """Best-effort source text for an AST node (Python 3.8+ get_source_segment)."""
    try:
        seg = ast.get_source_segment(source, node)
        if seg:
            return seg
    except Exception:
        pass
    return ""


# --------------------------------------------------------------------------
# Regex fallback (file does not parse as Python)
# --------------------------------------------------------------------------
def _analyze_regex(source: str, artifact_names: Set[str]
                   ) -> Tuple[FixtureSignals, EndStateSignals]:
    fx = FixtureSignals()
    es = EndStateSignals()

    fx.f1_tmp_write = bool(
        re.search(r"tmp_path|tmpdir", source) and
        re.search(r"\.write_text\(|\.write_bytes\(|open\([^)]*['\"]w", source))
    fx.f2_builder_ref = bool(_BUILDER_NAME_RE.search(source))
    for art in artifact_names:
        if art and art in source:
            fx.f3_artifact_name = True
            fx.matched_artifacts.append(art)

    has_subproc = bool(re.search(r"subprocess\.(run|check_call|"
                                 r"check_output|Popen|call)\(", source)) and \
        bool(_RUNNER_VERB_RE.search(source))
    has_verdict = bool(re.search(
        r"returncode|return_code|\.rc\b|stdout|stderr|"
        r"SystemExit|==\s*[01]|!=\s*0|verdict", source))
    has_entry = bool(re.search(
        r"\b(main|audit|evaluate|run)\s*\(", source))
    es.has_subprocess_call = has_subproc
    es.has_returncode_assert = has_verdict
    es.has_entrypoint_call = has_entry
    es.e1_subprocess_verdict = has_subproc and has_verdict
    es.e2_entrypoint_call = has_entry and has_verdict
    exists_only = bool(re.search(r"\.exists\(\)|\.is_file\(\)|"
                                 r"os\.path\.exists", source))
    es.exists_only = exists_only and not (es.ok)
    return fx, es


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------
@dataclass
class Verdict:
    verdict: str                       # PASS | FAIL | SKIP
    has_acceptance: bool
    test_path: str = ""
    fixture_ok: bool = False
    end_state_ok: bool = False
    fixture_signals: dict = field(default_factory=dict)
    end_state_signals: dict = field(default_factory=dict)
    gaps: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    snapshot_resolution: dict = field(default_factory=dict)


def evaluate(issue_body: str, test_source: str,
             test_path: str = "",
             repo_root: Optional[Path] = None) -> Verdict:
    if not has_acceptance_section(issue_body):
        return Verdict(
            verdict="SKIP",
            has_acceptance=False,
            test_path=test_path,
            notes=["issue has no '## 驗收'/acceptance section — the "
                   "defect-artifact + end-state requirement is vacuous"],
        )

    # Snapshot preference (#487): if the issue froze its defect artifact,
    # the snapshot path is the accepted defect-artifact SOURCE — preferred
    # over the mutable live run-dir path. We add the resolved snapshot path
    # to the artifact-name set so a test referencing the snapshot satisfies
    # (a), and the verdict no longer depends on the mutated live file.
    snap = resolve_defect_artifact_source(issue_body, repo_root=repo_root)
    artifact_names = issue_artifact_names(issue_body)
    if snap.prefer_snapshot and snap.snapshot_path:
        artifact_names.add(snap.snapshot_path)
        base = snap.snapshot_path.rstrip("/").split("/")[-1]
        if base:
            artifact_names.add(base)

    try:
        tree = ast.parse(test_source)
        fx, es = _analyze_ast(tree, artifact_names, test_source)
    except SyntaxError:
        fx, es = _analyze_regex(test_source, artifact_names)

    notes: List[str] = list(snap.notes)
    gaps: List[str] = []
    if not fx.ok:
        gaps.append(
            "(a) no defect-artifact fixture: the test neither shapes a "
            "tmp_path artifact, nor calls a fixture/artifact builder, nor "
            "references an issue-named artifact")
    if not es.ok:
        if es.exists_only:
            gaps.append(
                "(b) end-state assertion missing: the test only asserts "
                "file existence (.exists()/.is_file()) — it never invokes "
                "the real program/gate to assert a verdict (the #460/#466 "
                "anti-pattern)")
        else:
            gaps.append(
                "(b) end-state assertion missing: no subprocess.run of the "
                "named program (with a returncode/stdout assert) and no "
                "import+call of its main/audit/evaluate with a verdict "
                "assert")

    verdict = "PASS" if (fx.ok and es.ok) else "FAIL"
    return Verdict(
        verdict=verdict,
        has_acceptance=True,
        test_path=test_path,
        fixture_ok=fx.ok,
        end_state_ok=es.ok,
        fixture_signals=asdict(fx),
        end_state_signals=asdict(es),
        gaps=gaps,
        notes=notes,
        snapshot_resolution=asdict(snap),
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Refuse a regression test that does not build a "
                    "defect-artifact fixture AND assert an end state by "
                    "invoking the real program/gate.")
    ap.add_argument("--issue-body-file", required=True,
                    help="path to a file holding the issue body markdown")
    ap.add_argument("--test-file", required=True,
                    help="path to the new regression test source")
    ap.add_argument("--json", default=None,
                    help="write a JSON verdict report to this path")
    ap.add_argument("--repo-root", default=None,
                    help="repo root for locating the "
                         "community/captures/<slug>/ snapshot archive "
                         "(default: auto-discover)")
    args = ap.parse_args(argv)

    ipath = Path(args.issue_body_file)
    tpath = Path(args.test_file)
    if not ipath.is_file():
        print(f"ERROR: --issue-body-file not found: {ipath}",
              file=sys.stderr)
        return 2
    if not tpath.is_file():
        print(f"ERROR: --test-file not found: {tpath}", file=sys.stderr)
        return 2

    issue_body = ipath.read_text(encoding="utf-8")
    if not issue_body.strip():
        print("ERROR: --issue-body-file is empty", file=sys.stderr)
        return 2
    test_source = tpath.read_text(encoding="utf-8")

    repo_root = Path(args.repo_root) if args.repo_root else None
    v = evaluate(issue_body, test_source, test_path=str(tpath),
                 repo_root=repo_root)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(asdict(v), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")

    if v.verdict == "SKIP":
        print("SKIP (PASS): " + "; ".join(v.notes))
        return 0

    if v.verdict == "PASS":
        print("PASS: regression test builds a defect-artifact fixture "
              "AND asserts an end state via the real program/gate.")
        for n in v.notes:
            print(f"  note: {n}")
        return 0

    print("FAIL: regression test does not satisfy the defect-artifact "
          "+ end-state doctrine.", file=sys.stderr)
    for g in v.gaps:
        print(f"  - {g}", file=sys.stderr)
    print("\n  Build a fixture shaped like the issue's 現象 and assert the "
          "END state by invoking the real program/gate, not just "
          "file existence.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
