#!/usr/bin/env python3
"""programs/defect_artifact_fixture_check.py — v0.2.97

Deterministic pre-close gate for the core-agent loop (issue #478, Bucket A
half 2).

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


def evaluate(issue_body: str, test_source: str,
             test_path: str = "") -> Verdict:
    if not has_acceptance_section(issue_body):
        return Verdict(
            verdict="SKIP",
            has_acceptance=False,
            test_path=test_path,
            notes=["issue has no '## 驗收'/acceptance section — the "
                   "defect-artifact + end-state requirement is vacuous"],
        )

    artifact_names = issue_artifact_names(issue_body)
    try:
        tree = ast.parse(test_source)
        fx, es = _analyze_ast(tree, artifact_names, test_source)
    except SyntaxError:
        fx, es = _analyze_regex(test_source, artifact_names)

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

    v = evaluate(issue_body, test_source, test_path=str(tpath))

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
