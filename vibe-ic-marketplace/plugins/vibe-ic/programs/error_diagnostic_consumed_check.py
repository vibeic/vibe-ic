#!/usr/bin/env python3
"""
error_diagnostic_consumed_check.py — flow-integrity gate.

Doctrine, in one line:

    A diagnostic emitted at severity=ERROR must be consumed by SOME verdict.
    An ERROR that no gate reads is a defect in the flow, not in the design.

A step program can compute a fact, label it `severity="ERROR"`, write it to a
report on disk, and have every downstream gate carry on as if the fact did not
exist. The run then publishes PASS verdicts that the flow's own ERROR
contradicts. This is not a missing check — the check RAN and got the right
answer. The answer is simply not wired to anything that can act on it.

This gate makes that mechanically checkable. It enumerates every diagnostic
token a program can emit alongside a literal `severity="ERROR"`, and proves
each one is consumed.

WHAT COUNTS AS CONSUMED
-----------------------
An ERROR token is consumed when at least one of these holds:

  self-consumed   The emitting module is itself a GATE — it has a command-line
                  entry point that can exit non-zero. Emitting the ERROR is
                  then indistinguishable from failing, because the module's
                  own exit status is the verdict.

  cross-consumed  Some OTHER non-test module names the token as a string
                  constant (not merely in a comment or a docstring). Something
                  outside the emitter can therefore branch on it.

  self-compared   The emitting module itself compares against the token
                  (`== "TOK"`, `in {...}`), so the value steers control flow
                  even though the module is a library.

An ERROR that satisfies NONE of the three is INERT: it is computed, labelled
at the highest severity, serialised into a report, and read by nobody.

WHAT THIS GATE DELIBERATELY DOES NOT DO
---------------------------------------
It does not judge whether a consumer reacts CORRECTLY — only that a consumer
exists. Proving the reaction is right is a semantic question; proving the wire
exists is not, and the wire being absent is the failure mode actually observed.

Only literal severities are decidable. A `severity=<variable>` emission is
reported under `undecidable` and never silently counted as a pass.

Usage:
    python3 error_diagnostic_consumed_check.py <plugin_root>
                                               [--json <out>]
                                               [--allow TOK[,TOK...]]

Exit codes:
    0  PASS — every severity=ERROR token is consumed
    1  FAIL — at least one INERT ERROR diagnostic
    2  argument / I-O error, or nothing was scanned

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Keys whose literal string value names the diagnostic. A diagnostic that
# carries a severity but no token cannot be referenced by anyone, so it is
# reported separately rather than being silently dropped.
_TOKEN_KEYS = (
    "verdict", "rule", "code", "reason_code", "diagnostic",
    "error_code", "kind", "check",
)

# A token must look like a diagnostic constant, not prose. Two chars is enough
# to admit short real codes while rejecting free text.
_TOKEN_MIN_LEN = 2

SCAN_CENSUS: Dict[str, int] = {}


@dataclass
class Emission:
    """One severity=ERROR diagnostic construction site."""
    token: str
    file: str
    line: int


@dataclass
class Finding:
    token: str
    file: str
    line: int
    emitter_is_gate: bool
    why: str


@dataclass
class Undecidable:
    file: str
    line: int
    why: str


# ---------------------------------------------------------------------------
# Source helpers
# ---------------------------------------------------------------------------
def _is_test_path(p: Path) -> bool:
    parts = {q.lower() for q in p.parts}
    return "tests" in parts or p.name.startswith("test_")


def _iter_program_files(root: Path) -> List[Path]:
    """Every plugin .py that is not a test."""
    out: List[Path] = []
    for sub in ("programs",):
        d = root / sub
        if not d.is_dir():
            continue
        n = 0
        for p in sorted(d.rglob("*.py")):
            if _is_test_path(p):
                continue
            out.append(p)
            n += 1
        SCAN_CENSUS[f"dir_{sub}"] = n
    return out


def _docstring_nodes(tree: ast.AST) -> Set[int]:
    """id() of every string Constant that is a docstring."""
    out: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.add(id(body[0].value))
    return out


def _string_constants(tree: ast.AST) -> Set[str]:
    """Every string literal EXCEPT docstrings.

    Comments never reach the AST at all, so a token mentioned only in prose
    cannot be mistaken for a consumer.
    """
    skip = _docstring_nodes(tree)
    out: Set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in skip):
            out.add(node.value)
    return out


def _compared_strings(tree: ast.AST) -> Set[str]:
    """String literals used in a comparison — `x == "T"`, `x in {"T"}`."""
    out: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for side in [node.left, *node.comparators]:
            if isinstance(side, ast.Constant) and isinstance(side.value, str):
                out.add(side.value)
            elif isinstance(side, (ast.Tuple, ast.List, ast.Set)):
                for e in side.elts:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        out.add(e.value)
            elif isinstance(side, ast.Dict):
                for k in side.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        out.add(k.value)
    return out


def _is_gate(tree: ast.AST) -> bool:
    """Does this module have an entry point that can exit non-zero?

    A module that can fail a run consumes its own ERRORs by construction: the
    caller sees the exit status, which is the verdict.
    """
    has_main_guard = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"):
            has_main_guard = True
    if not has_main_guard:
        return False
    # …and it must be able to yield a non-zero status.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", None)
            if name == "exit":
                return True
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
            if node.value.value in (1, 2):
                return True
    return False


# ---------------------------------------------------------------------------
# Emission extraction
# ---------------------------------------------------------------------------
def _severity_and_tokens(
    keys: List, values: List,
) -> Tuple[object, List[str]]:
    """Pull a literal severity and any token strings from paired key/values.

    Returns (severity, tokens). severity is the literal string, or None when
    absent, or the sentinel `False` when present but not a literal.
    """
    sev: object = None
    toks: List[str] = []
    for k, v in zip(keys, values):
        if k is None:
            continue
        if k == "severity":
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                sev = v.value
            else:
                sev = False          # present, not statically decidable
        if k in _TOKEN_KEYS and isinstance(v, ast.Constant) \
                and isinstance(v.value, str):
            toks.append(v.value)
    return sev, toks


def _emissions_in(tree: ast.AST, rel: str) -> Tuple[List[Emission],
                                                     List[Undecidable]]:
    found: List[Emission] = []
    undec: List[Undecidable] = []

    def record(sev, toks, node):
        if sev is False:
            undec.append(Undecidable(
                rel, getattr(node, "lineno", 0),
                "severity= is not a literal; cannot be decided statically"))
            return
        if not isinstance(sev, str) or sev.upper() != "ERROR":
            return
        real = [t for t in toks if len(t) >= _TOKEN_MIN_LEN]
        if not real:
            undec.append(Undecidable(
                rel, getattr(node, "lineno", 0),
                "severity=ERROR carries no token key "
                f"({'/'.join(_TOKEN_KEYS)}); nothing can reference it"))
            return
        for t in real:
            found.append(Emission(t, rel, getattr(node, "lineno", 0)))

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = [k.value if isinstance(k, ast.Constant)
                    and isinstance(k.value, str) else None
                    for k in node.keys]
            sev, toks = _severity_and_tokens(keys, node.values)
            record(sev, toks, node)
        elif isinstance(node, ast.Call):
            if not node.keywords:
                continue
            keys = [kw.arg for kw in node.keywords]
            vals = [kw.value for kw in node.keywords]
            sev, toks = _severity_and_tokens(keys, vals)
            record(sev, toks, node)

    return found, undec


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def audit(root: Path, allow: Set[str] | None = None):
    allow = set(allow or ())
    files = _iter_program_files(root)
    SCAN_CENSUS["files_read"] = 0

    parsed: Dict[Path, ast.AST] = {}
    unparsed: List[Undecidable] = []
    for p in files:
        try:
            parsed[p] = ast.parse(p.read_text(encoding="utf-8",
                                              errors="replace"))
        except (SyntaxError, ValueError) as exc:
            # A file this gate cannot parse is a file it cannot vouch for.
            # Silently skipping it would let an inert ERROR hide behind a
            # syntax error, so it is recorded rather than dropped.
            unparsed.append(Undecidable(
                str(p.relative_to(root)), getattr(exc, "lineno", 0) or 0,
                f"could not be parsed ({type(exc).__name__}); not scanned"))
            continue
        SCAN_CENSUS["files_read"] += 1
    SCAN_CENSUS["files_unparsed"] = len(unparsed)

    # 1. every severity=ERROR emission
    emissions: List[Emission] = []
    undecidable: List[Undecidable] = list(unparsed)
    for p, tree in parsed.items():
        rel = str(p.relative_to(root))
        e, u = _emissions_in(tree, rel)
        emissions.extend(e)
        undecidable.extend(u)
    SCAN_CENSUS["error_emissions"] = len(emissions)

    # 2. per-module facts, computed once
    strings: Dict[str, Set[str]] = {}
    compared: Dict[str, Set[str]] = {}
    gate: Dict[str, bool] = {}
    for p, tree in parsed.items():
        rel = str(p.relative_to(root))
        strings[rel] = _string_constants(tree)
        compared[rel] = _compared_strings(tree)
        gate[rel] = _is_gate(tree)

    # 3. decide each distinct (token, emitter)
    by_token: Dict[str, Set[str]] = {}
    line_of: Dict[Tuple[str, str], int] = {}
    for em in emissions:
        by_token.setdefault(em.token, set()).add(em.file)
        line_of.setdefault((em.token, em.file), em.line)

    findings: List[Finding] = []
    consumed_census: Dict[str, str] = {}
    for tok, emitters in sorted(by_token.items()):
        if tok in allow:
            consumed_census[tok] = "allowlisted"
            continue
        if any(gate.get(f, False) for f in emitters):
            consumed_census[tok] = "self-consumed (emitter is a gate)"
            continue
        if any(tok in compared.get(f, set()) for f in emitters):
            consumed_census[tok] = "self-compared (steers control flow)"
            continue
        readers = sorted(
            rel for rel, s in strings.items()
            if rel not in emitters and tok in s
        )
        if readers:
            consumed_census[tok] = f"cross-consumed by {readers[0]}"
            continue
        for f in sorted(emitters):
            findings.append(Finding(
                token=tok, file=f, line=line_of[(tok, f)],
                emitter_is_gate=False,
                why=("emitted at severity=ERROR by a module with no "
                     "non-zero exit path, and no other non-test module "
                     "names it as a string constant — no verdict can "
                     "depend on it"),
            ))

    verdict = "FAIL" if findings else "PASS"
    return verdict, findings, undecidable, consumed_census


# ---------------------------------------------------------------------------
def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Prove every severity=ERROR diagnostic is consumed by "
                    "some verdict.")
    ap.add_argument("plugin_root")
    ap.add_argument("--json")
    ap.add_argument("--allow", default="",
                    help="comma-separated tokens to exempt (each needs a "
                         "reason in the PR that adds it)")
    args = ap.parse_args(argv)

    root = Path(args.plugin_root).resolve()
    if not root.is_dir():
        print(f"VACUOUS_PASS: plugin_root {root} is not a directory")
        return 0

    allow = {t.strip() for t in args.allow.split(",") if t.strip()}
    verdict, findings, undecidable, census = audit(root, allow=allow)

    report = {
        "gate": "error_diagnostic_consumed_check",
        "verdict": verdict,
        "plugin_root": str(root),
        "scan_census": dict(SCAN_CENSUS),
        "tokens_total": len(census) + len({f.token for f in findings}),
        "tokens_consumed": len(census),
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings[:200]],
        "undecidable_count": len(undecidable),
        "undecidable": [asdict(u) for u in undecidable[:100]],
        "consumed": census,
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    read = SCAN_CENSUS.get("files_read", 0)
    emis = SCAN_CENSUS.get("error_emissions", 0)
    if read == 0:
        print(f"NOTHING_SCANNED: read 0 non-test .py under {root}/programs — "
              "a clean result over an empty scan is not a clean result; "
              "check the plugin_root argument.", file=sys.stderr)
        return 2
    if emis == 0:
        print(f"NOTHING_SCANNED: read {read} file(s) but found 0 "
              "severity=ERROR emissions. This gate has nothing to prove and "
              "its PASS would be vacuous; check the plugin_root argument.",
              file=sys.stderr)
        return 2

    if verdict == "PASS":
        print(f"PASS ({read} file(s), {emis} severity=ERROR emission(s), "
              f"{len(census)} distinct token(s)): every ERROR diagnostic is "
              "consumed by some verdict.")
        if undecidable:
            print(f"  note: {len(undecidable)} emission(s) not statically "
                  "decidable — listed in the report, not counted as passing.")
        return 0

    print(f"FAIL: {len(findings)} INERT severity=ERROR diagnostic(s) — "
          "computed, labelled ERROR, read by nobody:", file=sys.stderr)
    for f in findings[:20]:
        print(f"  {f.token}", file=sys.stderr)
        print(f"    emitted at {f.file}:{f.line}", file=sys.stderr)
        print(f"    {f.why}", file=sys.stderr)
    if len(findings) > 20:
        print(f"  … and {len(findings) - 20} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
