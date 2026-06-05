#!/usr/bin/env python3
"""blindness_audit.py — deterministic prompt-only blindness audit.

ORGANIC-20260605-blindness-deterministic-audit-guard: the blindness contract
(read ONLY the current problem's prompt; never hidden tests/refs, sibling
files, build files, or score channels) was enforced purely by instruction
TEXT — and was skirted twice in one campaign (an agent self-ran the host
scorer mid-loop; another read a dataset makefile for naming authority). Text
rules degrade under agent creativity; this program is the deterministic
audit that inspects what agents actually ACCESSED.

WHAT IT SCANS
-------------
Authoring / close-loop agent transcripts (plain text, JSONL, or any
fs-access log). Feed transcript files or directories; with --run it scans
`<RUNDIR>/transcripts/` (the documented export location for batch-agent
transcripts).

WHAT IT FLAGS
-------------
V1  dataset-file access beyond the allowed PROMPT files — any path under
    --dataset whose basename does not match an allowed prompt glob:
      * hidden oracle files  (*_test.*, *_ref.*, testbench*, verified_*,
        anything under a score/ dir)
      * build files          (Makefile / makefile / GNUmakefile / *.mk /
        CMakeLists.txt — dataset-internal naming/flow authority)
      * any other non-prompt dataset file
    Bare mentions of the dataset ROOT are NOT flagged (the orchestrator's
    own prompt text legitimately carries the dataset path).
V2  agent-side invocation of a host scorer (a verdict-level oracle query
    mid-loop): command-shaped `score_*.py` invocations and
    `benchmark_dispatch … --score`. Scoring is the HOST's post-generation
    step — an authoring/close-loop transcript must never contain it.
    (Mere mentions of a scorer name in instruction prose are not flagged —
    only command-shaped lines.)
V3  access to a `canonical_samples/` path (any root): the harness's
    vetted defect-audit samples are dataset-adjacent SOLUTION KNOWLEDGE
    (ORGANIC-20260605-scorer-disagreeing-golden-flag); only the host
    scorer may touch them. Path-shaped references only (a trailing
    file/dir component must follow the segment).

KNOWN HONEST LIMIT: a batch agent legitimately reads EVERY prompt in its
batch, so cross-problem reads of *prompt* files are not distinguishable
here; the audit enforces the strongest deterministic subset (non-prompt
dataset files + scorer self-runs). chip-AGNOSTIC: pure path/command
structure; no IC/vendor/bench-name literals in detection logic.

EXIT CODES
----------
0 = scanned >=1 transcript, no violations
1 = violations found (printed + optional --json)
2 = nothing to audit (no transcript files found) / usage error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent / "benchmark-harness"
REGISTRY = HARNESS / "BENCHMARK_REGISTRY.json"

# Default allowed prompt-file globs (basename match). --bench narrows this to
# the registry layout's declared prompt file(s); --allowed-glob overrides.
_DEFAULT_ALLOWED = ["*_prompt.txt", "design_description.txt", "PROMPT.txt",
                    "specification.md"]

_BUILD_FILE_RE = re.compile(
    r"^(?:makefile|gnumakefile|cmakelists\.txt)$|\.mk$", re.IGNORECASE)
_ORACLE_FILE_RE = re.compile(
    r"(?:_test\.[a-z0-9]+|_ref\.[a-z0-9]+|^testbench|^verified_)",
    re.IGNORECASE)

# Command-shaped scorer invocations only (a prose mention of the scorer name,
# e.g. inside shipped instructions quoted in the prompt, must NOT fire).
_SCORER_INVOKE_RE = re.compile(
    r"(?:python3?\s+\S*score_[a-z0-9_]+\.py)"          # python …/score_x.py
    r"|(?:\S*/score_[a-z0-9_]+\.py\s+--)"              # …/score_x.py --args
    r"|(?:^|\s)score_[a-z0-9_]+\.py\s+--"              # score_x.py --args
    r"|(?:benchmark_dispatch(?:\.py)?\s+\S+.*--score)",  # dispatch … --score
    re.IGNORECASE)

# V3: path-shaped reference into a canonical_samples tree (any root). A bare
# mention of the word in prose lacks the trailing path component and does
# not fire; instruction text referring to "canonical_samples/" alone is safe.
_CANONICAL_PATH_RE = re.compile(
    r"canonical_samples/[A-Za-z0-9_\-./]+")


def _allowed_globs(bench: str | None, extra: list[str]) -> list[str]:
    if extra:
        return list(extra)
    if bench and REGISTRY.is_file():
        try:
            e = json.loads(REGISTRY.read_text())["benchmarks"].get(bench) or {}
            lay = e.get("layout", {})
            out = []
            if lay.get("prompt_suffix"):
                out.append("*" + lay["prompt_suffix"])
            if lay.get("prompt_filename"):
                out.append(lay["prompt_filename"])
            if out:
                return out
        except Exception:
            pass
    return list(_DEFAULT_ALLOWED)


def _classify_rel(rel: str) -> str:
    base = Path(rel.rstrip("/")).name
    parts = [p.lower() for p in Path(rel).parts]
    if "score" in parts:
        return "hidden oracle file (score/ channel)"
    if _BUILD_FILE_RE.search(base):
        return "build file (dataset-internal flow/naming authority)"
    if _ORACLE_FILE_RE.search(base):
        return "hidden oracle file (test/ref/golden)"
    return "non-prompt dataset file"


def _iter_transcripts(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            out += sorted(f for f in pp.rglob("*") if f.is_file())
        elif pp.is_file():
            out.append(pp)
    return out


def audit_text(text: str, dataset: Path, allowed: list[str],
               source: str) -> list[dict]:
    """Pure scanner: return violation dicts for one transcript text."""
    from fnmatch import fnmatch
    findings: list[dict] = []
    ds = str(dataset).rstrip("/")
    path_re = re.compile(re.escape(ds) + r"([A-Za-z0-9_\-./]*)")
    for ln_no, line in enumerate(text.splitlines(), 1):
        # V1 — dataset paths beyond allowed prompt files
        for m in path_re.finditer(line):
            rel = m.group(1).lstrip("/")
            if not rel:
                continue                       # bare dataset root: benign
            base = Path(rel.rstrip("/")).name
            if not base:
                continue
            if any(fnmatch(base, g) for g in allowed):
                continue
            findings.append({
                "kind": "dataset-file-access",
                "class": _classify_rel(rel),
                "path": f"{ds}/{rel}",
                "transcript": source, "line": ln_no,
                "evidence": line.strip()[:300],
            })
        # V2 — agent-side scorer invocation (verdict-level oracle query)
        if _SCORER_INVOKE_RE.search(line):
            findings.append({
                "kind": "scorer-self-run",
                "class": "agent-side host-scorer invocation (oracle query)",
                "transcript": source, "line": ln_no,
                "evidence": line.strip()[:300],
            })
        # V3 — vetted canonical-sample access (defect-audit data is
        # solution knowledge; host-scorer-only)
        if _CANONICAL_PATH_RE.search(line):
            findings.append({
                "kind": "canonical-sample-access",
                "class": "vetted canonical defect-audit sample "
                         "(solution knowledge — host scorer only)",
                "transcript": source, "line": ln_no,
                "evidence": line.strip()[:300],
            })
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic prompt-only blindness audit over agent "
                    "transcripts (ORGANIC-20260605).")
    ap.add_argument("transcripts", nargs="*",
                    help="transcript files or directories to scan")
    ap.add_argument("--run", help="run dir — scans <RUN>/transcripts/")
    ap.add_argument("--dataset", required=True, help="dataset root path")
    ap.add_argument("--bench",
                    help="registry bench name (narrows allowed prompt globs)")
    ap.add_argument("--allowed-glob", action="append", default=[],
                    help="override allowed basename glob (repeatable)")
    ap.add_argument("--json", help="write findings JSON here")
    a = ap.parse_args(argv)

    srcs = list(a.transcripts)
    if a.run:
        srcs.append(str(Path(a.run) / "transcripts"))
    files = _iter_transcripts(srcs)
    if not files:
        print("blindness_audit: NOTHING TO AUDIT — no transcript files found "
              "(export batch-agent transcripts to <RUNDIR>/transcripts/).",
              file=sys.stderr)
        return 2

    dataset = Path(a.dataset).resolve()
    allowed = _allowed_globs(a.bench, a.allowed_glob)
    findings: list[dict] = []
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except Exception as exc:  # noqa: BLE001
            print(f"blindness_audit: unreadable transcript {f}: {exc}",
                  file=sys.stderr)
            continue
        findings += audit_text(text, dataset, allowed, str(f))

    if a.json:
        Path(a.json).write_text(json.dumps(findings, indent=2) + "\n")

    if findings:
        print(f"blindness_audit: FAIL — {len(findings)} violation(s) across "
              f"{len(files)} transcript(s) [allowed prompt globs: {allowed}]")
        for fd in findings:
            loc = f"{fd['transcript']}:{fd['line']}"
            what = fd.get("path", fd["class"])
            print(f"  [{fd['kind']}] {loc} -> {what}\n"
                  f"      {fd['class']}\n      | {fd['evidence']}")
        return 1
    print(f"blindness_audit: PASS — {len(files)} transcript(s) clean "
          f"[allowed prompt globs: {allowed}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
