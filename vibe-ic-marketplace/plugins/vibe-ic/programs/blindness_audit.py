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
1 = blindness violation(s) found (printed + optional --json)
2 = nothing to audit (no transcript files found) / usage error
3 = AUDIT_ERROR — an auditor-internal exception (e.g. an OSError while
    classifying a path) aborted the scan. This is a TOOL failure, NOT a
    blindness violation; the consumer must NEVER fold it into a FAIL
    verdict (ORGANIC-20260607-blindness-audit-jsonl-crash, #480).

JSONL TRANSCRIPTS (Claude-Code export)
--------------------------------------
A Claude-Code transcript is one JSON object per line. The auditor parses
each line with json.loads and inspects the structured tool-use input FIELDS
(file_path / command / paths / pattern / …) — it never regexes over the raw
JSON line, because a single line concatenates a legal prompt-file read with
the rest of the JSON ({"file_path":".../X_prompt.txt"},"caller":{"type":
"direct"}}…) and a raw-tail extraction would glue them into one enormous
non-existent path → OSError: File name too long → a genuinely-blind run
mis-scored as a blindness FAIL (#480). Non-JSON lines fall back to the
legacy plain-text line scan, so READ-line / fs-access-log transcripts still
work unchanged.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent / "benchmark"
REGISTRY = HARNESS / "BENCHMARK_REGISTRY.json"

# Exit codes (see module docstring). EXIT_AUDIT_ERROR is distinct from the
# blindness-violation code so a tool crash can never masquerade as a FAIL.
EXIT_CLEAN = 0
EXIT_VIOLATION = 1
EXIT_NOTHING = 2
EXIT_AUDIT_ERROR = 3


class AuditError(Exception):
    """An auditor-internal failure (not a blindness violation)."""

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


# Shell punctuation that glues onto a path token's right edge inside a
# command fragment (closing quotes, statement separators, pipes, subshell
# closers). Stripped from disk-truth probes before the existence test —
# v0.3.6 #504: `…/design_description.txt";` never EXISTS as written, so
# the ladder shrank past the space inside the directory name instead.
_SHELL_TRAILER_CHARS = "\"';)|&,>"


def _extract_rel(line: str, end: int, ds: str) -> str:
    """Path tail after a dataset-root match, SPACE-safe
    (ORGANIC-20260606-blindness-audit-space-path-truncation): the legacy
    charclass tail had no space, so a dataset whose directory names contain
    spaces ("…/Misc category/Frequency divider/…") truncated at the first
    space — the ALLOWED spec read then mis-matched the glob and hard-blocked
    scoring. Resolution ladder:
      0. shell-token quote context (v0.3.6 — ORGANIC #504): when the
         dataset-root match sits directly after an opening `"` / `'`, the
         path token is the WHOLE quoted span — `cat "…/dir with space/f"`
         resolves to the closing quote, host-independently (no existence
         probe needed; #480 fixed quote-TERMINATION, this fixes
         quote-PROTECTION);
      1. disk-truth longest prefix: extend to EOL and shrink right-to-left at
         whitespace until the path EXISTS (each probe first stripped of
         glued shell trailers like `";` — #504 — and of trailers like
         "(123 bytes)" / CMD flags after the path);
      2. READ-line convention: a transcript `READ <path>` line carries ONE
         path — take everything to EOL;
      3. legacy conservative charclass tail (space-free) as the fallback for
         prose mentions / paths not present on this host."""
    start = end - len(ds)
    # 0 — quoted shell token: the span between the opening quote that
    # immediately precedes the dataset root and its closing twin IS the
    # path, spaces included. Dataset-AGNOSTIC and host-independent.
    if start > 0 and line[start - 1] in ('"', "'"):
        closing = line.find(line[start - 1], end)
        if closing != -1:
            return line[end:closing].lstrip("/")
    tail = line[end:]
    full = (ds + tail).rstrip()
    probe = full
    while len(probe) > len(ds):
        cand = probe.rstrip(_SHELL_TRAILER_CHARS)
        try:
            if len(cand) > len(ds) and Path(cand).exists():
                return cand[len(ds):].lstrip("/")
        except OSError:
            # an over-long / malformed candidate (e.g. a JSON line whose tail
            # was glued onto the path) can't name a real file — treat as
            # absent and keep shrinking; never let it abort the scan (#480).
            pass
        cut = probe.rfind(" ")
        if cut <= len(ds):
            break
        probe = probe[:cut].rstrip()
    if re.match(r"\s*READ\b", line):
        return full[len(ds):].lstrip("/")
    m2 = re.match(r"[A-Za-z0-9_\-./]*", tail)
    return m2.group(0).lstrip("/")


# Tool-use input fields that can carry a filesystem path or a shell command.
# Claude-Code Read/Write/Edit use file_path; Bash uses command; Grep/Glob use
# path + pattern; generic tools may use paths[]/files[]/cwd. We pull these
# VALUES out of the parsed JSON and scan them directly — never the raw line.
_PATH_FIELDS = ("file_path", "path", "notebook_path", "cwd", "directory",
                "filename", "target_file", "absolute_path")
_LIST_FIELDS = ("paths", "files", "file_paths")
_CMD_FIELDS = ("command", "cmd", "pattern", "query", "script")


def _harvest_tool_strings(obj) -> list[str]:
    """Recursively pull tool-use input string VALUES (paths + commands) out of
    a parsed JSON transcript object. We walk the whole structure so it works
    regardless of the exact Claude-Code envelope nesting (message.content[]
    blocks, tool_result content, sub-agent caller frames, …)."""
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            # tool_use blocks carry the actionable fields under "input"; but be
            # liberal and also scan path/command fields wherever they appear.
            inp = node.get("input")
            scopes = [node]
            if isinstance(inp, dict):
                scopes.append(inp)
            for sc in scopes:
                for k in _PATH_FIELDS + _CMD_FIELDS:
                    v = sc.get(k)
                    if isinstance(v, str):
                        out.append(v)
                for k in _LIST_FIELDS:
                    v = sc.get(k)
                    if isinstance(v, list):
                        out.extend(x for x in v if isinstance(x, str))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(obj)
    # de-dup while preserving first-seen order: the same field can be reached
    # both as a sub-scope of its parent and again when recursion descends into
    # it as its own node, so a single read would otherwise be flagged twice.
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


# v0.3.8 — ORGANIC #504 ROUND-2: shell-token semantics for two
# false-positive shapes that blocked the canonical scoring front door on a
# real 9-transcript run.
#
# (A) ASSIGNMENT RHS — `VAR=<dataset-path>` (incl. `export`/`local`/
#     `readonly` prefixes and array-subscript `arr[k]=` forms) STORES a
#     path; it is not an access. The consumption side (`"$VAR/..."`) is
#     scanned separately wherever the dataset root is visible. Round-1
#     doctrine already named the `SRC=` shape; this is its `declare -A`
#     sibling generalised to all assignment forms.
_ASSIGN_PREFIX_RE = re.compile(
    r"(?:^|[\s;&|({])"
    r"(?:export\s+|local\s+|readonly\s+)?"
    r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?="
    r"[\"']?$"
)

# Statement separators that bound an `A || B` fallback pair (a `;`,
# newline or `&&` between the `||` and the candidate breaks the pair).
_STMT_SEP_RE = re.compile(r";|&&|\n")


def _is_assignment_rhs(frag: str, start: int) -> bool:
    """True when the dataset-root match at `start` is the right-hand side
    of a shell variable assignment (storage, not access). #504 R2."""
    return bool(_ASSIGN_PREFIX_RE.search(frag[:start]))


def _is_or_fallback_family_twin(frag: str, start: int, base: str,
                                ds: str, allowed: list[str]) -> bool:
    """#504 R2 — (B) OR-FALLBACK FAMILY TWIN. True when the candidate at
    `start` (basename `base`) is the RIGHT branch of an `A || B` shell
    fallback whose LEFT branch (same statement) references an ALLOWED
    dataset file, and `base` shares its name-STEM with an allowed glob
    (extension twin, e.g. the documented `.md` fallback of an allowed
    `.txt` prompt). The twin branch is the blind-instructions fallback
    idiom — when the allowed file exists the twin branch never executes,
    and when it executes it reads the same prompt content under the
    family name. A right branch naming a NON-family file (oracle/build)
    still flags; a twin with no allowed LEFT reference still flags."""
    from fnmatch import fnmatch
    # (1) family-stem membership against the allowed globs.
    stem_b = base.rsplit(".", 1)[0]
    fam = False
    for g in allowed:
        g_base = g.rsplit("/", 1)[-1]
        stem_g = g_base.rsplit(".", 1)[0] if "." in g_base else g_base
        if fnmatch(stem_b, stem_g):
            fam = True
            break
    if not fam:
        return False
    # (2) nearest `||` before the candidate, unbroken by a statement
    # separator → the candidate is the fallback's right branch.
    q = frag.rfind("||", 0, start)
    if q == -1:
        return False
    if _STMT_SEP_RE.search(frag, q + 2, start):
        return False
    # (3) the LEFT branch (statement start … `||`) must reference an
    # allowed dataset file.
    left_lo = 0
    for msep in _STMT_SEP_RE.finditer(frag, 0, q):
        left_lo = msep.end()
    left = frag[left_lo:q]
    for m2 in re.finditer(re.escape(ds), left):
        rel2 = _extract_rel(left, m2.end(), ds)
        if rel2:
            b2 = Path(rel2.rstrip("/")).name
            if b2 and any(fnmatch(b2, g) for g in allowed):
                return True
    return False


def _scan_fragment(frag: str, ds: str, allowed: list[str], source: str,
                   ln_no: int) -> list[dict]:
    """Run V1/V2/V3 over one already-isolated fragment (a JSON field value, or
    a whole legacy text line). `frag` is self-terminated, so V1 path
    extraction never bleeds into adjacent JSON (#480). v0.3.8 (#504 R2):
    assignment-RHS and OR-fallback family-twin candidates are shell-token
    exemptions, not violations."""
    from fnmatch import fnmatch
    findings: list[dict] = []
    path_re = re.compile(re.escape(ds))
    # V1 — dataset paths beyond allowed prompt files
    for m in path_re.finditer(frag):
        rel = _extract_rel(frag, m.end(), ds)
        if not rel:
            continue                           # bare dataset root: benign
        base = Path(rel.rstrip("/")).name
        if not base:
            continue
        if any(fnmatch(base, g) for g in allowed):
            continue
        # v0.3.8 — #504 R2 shell-token exemptions (see helpers above).
        if _is_assignment_rhs(frag, m.start()):
            continue
        if _is_or_fallback_family_twin(frag, m.start(), base, ds, allowed):
            continue
        findings.append({
            "kind": "dataset-file-access",
            "class": _classify_rel(rel),
            "path": f"{ds}/{rel}",
            "allowed_globs": list(allowed),
            "transcript": source, "line": ln_no,
            "evidence": frag.strip()[:300],
        })
    # V2 — agent-side scorer invocation (verdict-level oracle query)
    if _SCORER_INVOKE_RE.search(frag):
        findings.append({
            "kind": "scorer-self-run",
            "class": "agent-side host-scorer invocation (oracle query)",
            "transcript": source, "line": ln_no,
            "evidence": frag.strip()[:300],
        })
    # V3 — vetted canonical-sample access (solution knowledge; host-only)
    if _CANONICAL_PATH_RE.search(frag):
        findings.append({
            "kind": "canonical-sample-access",
            "class": "vetted canonical defect-audit sample "
                     "(solution knowledge — host scorer only)",
            "transcript": source, "line": ln_no,
            "evidence": frag.strip()[:300],
        })
    return findings


def audit_text(text: str, dataset: Path, allowed: list[str],
               source: str) -> list[dict]:
    """Pure scanner: return violation dicts for one transcript text.

    Each line is parsed with json.loads first; a Claude-Code JSONL line is
    scanned through its STRUCTURED tool-use input field values (so a legal
    prompt read does not concatenate with the rest of the JSON, #480). A line
    that is not a JSON object falls back to the legacy raw-line text scan
    (READ-lines / fs-access logs / prose mentions)."""
    findings: list[dict] = []
    ds = str(dataset).rstrip("/")
    for ln_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        obj = None
        if stripped[:1] in ("{", "["):
            try:
                obj = json.loads(stripped)
            except (ValueError, TypeError):
                obj = None                     # non-JSON / truncated → fallback
        if obj is not None:
            for frag in _harvest_tool_strings(obj):
                findings += _scan_fragment(frag, ds, allowed, source, ln_no)
        else:
            findings += _scan_fragment(line, ds, allowed, source, ln_no)
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
        return EXIT_NOTHING

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
        # An auditor-internal exception while SCANNING (e.g. a residual OSError
        # from path classification) is a TOOL failure — surface it as a named
        # AUDIT_ERROR with its own exit code; it must NEVER be reported as a
        # blindness violation (#480).
        try:
            findings += audit_text(text, dataset, allowed, str(f))
        except Exception as exc:  # noqa: BLE001
            print(f"blindness_audit: AUDIT_ERROR — internal failure while "
                  f"scanning {f}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return EXIT_AUDIT_ERROR

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
        return EXIT_VIOLATION
    print(f"blindness_audit: PASS — {len(files)} transcript(s) clean "
          f"[allowed prompt globs: {allowed}]")
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
