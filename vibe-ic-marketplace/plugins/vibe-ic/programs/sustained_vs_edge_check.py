#!/usr/bin/env python3
"""
sustained_vs_edge_check.py — Flag RTL using edge-detect when spec calls for sustained.

A common protocol-comprehension bug: the spec text says a signal must be
*held* / *sustained* / *maintained* / *持續* / *維持* in some state for some
duration to trigger an action — but the RTL author writes a 1-cycle edge
detector instead, so every transient transition fires the action.

This gate cross-checks input spec docs (FRS / measurements / timing PPT
extracted to text) against RTL implementation. Findings:

  - SPEC contains a sustain-class word AND a duration figure (e.g.
    "ID_BUS held LOW for 80us triggers reset", "持續低 80us 才觸發",
    "由 High 轉為 Low 並維持 X ms").
  - RTL contains an edge detector pattern on the same signal:
        signal_q <= signal;
        edge_event <= signal && !signal_q;     // rising
    or  edge_event <= !signal && signal_q;     // falling
  - No counter / sustained-low-duration check is present near the edge
    detector.

Exit codes:
    0 = PASS (no risky pattern, OR the signal has a sustain counter, OR no
        spec text existed to compare against — which the verdict SAYS)
    1 = FAIL (edge detector with no sustain counter while spec says sustain)
    2 = NOT CHECKED / usage error — no readable RTL, --rtl-dir absent, or an
        explicit --spec-text that does not exist. Never a PASS: rc 0 over a
        denominator of nothing certifies a check that examined nothing.

Generality: works for ANY single-wire / ID-bus / wake / reset / brownout
protocol. No chip / tester / PDK identifiers in this code.

Usage:
    python3 sustained_vs_edge_check.py \\
        --rtl-dir ./rtl/ \\
        --spec-text ./generated_docs/spec_text.txt

`--out-dir` is OPTIONAL and has no default: omit it and the gate writes no
file at all (verdict on stdout). Pass a project-relative directory —
e.g. `--out-dir ./reports/` — when you want the JSON report on disk.

The `--spec-text` is any concatenation of input docs (post-pdftotext,
libreoffice convert) — it just needs to be searchable text.

SPEC DISCOVERY — why `--spec-text` is not required for the FAIL arm to exist
---------------------------------------------------------------------------
The ERROR severity (the one that produces rc 1) is gated on `spec_match`, and
`spec_match` could only ever be set from `--spec-text`. The P0 umbrella
(`flow_compliance_check._STRUCTURAL_GATE_ARGV_ADAPTERS`) invokes this gate with
`("--rtl-dir",)` and nothing else, and it does not pass `--strict` either — so
as invoked, BOTH routes to a non-zero exit were closed and the gate was
structurally incapable of returning 1. It printed the finding it exists to
report (`[WARN] ... signal=... sustain_counter=False`) and exited 0, and the
umbrella recorded PASS. `flow_compliance_check` names that exact hazard for a
sibling gate — "clearing the bar precisely BECAUSE it is incapable of failing"
— and the bar was never applied to this row.

The fix is to make the DEFAULT correct rather than to make the caller louder:
when `--spec-text` is omitted the gate now finds the project's own spec prose
itself (`phase1/input_doc`, `phase1/input_prompt`, `phase1/generated_docs/L*.json`
— the canonical `_path_layout` locations), anchored by walking up from
`--rtl-dir` and falling back to the cwd the umbrella already sets to the project
root. `--strict` is deliberately NOT wired into the umbrella: without spec
evidence a WARN is "an edge detector with no counter nearby", which is a normal
and usually-correct RTL idiom, so escalating it would redden designs for having
written ordinary Verilog. Only the evidence-backed pairing — the spec says a
named signal must be HELD for a duration, and the RTL edge-detects that same
signal with no sustain counter — is an ERROR, and that is now reachable from
the argv the umbrella actually builds.

Every verdict therefore discloses which spec sources it read, so a PASS is
legible as "compared against N documents" or as "no spec text was found, so
nothing was compared" — never silently the second while looking like the first.
"""
from __future__ import annotations
import argparse, json, re, sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Tuple

import _path_layout as _pl

# Sustain-class words across English and Traditional Chinese.
SUSTAIN_WORDS = [
    "sustain", "sustained", "held", "hold", "stable",
    "maintain", "maintained", "continue", "continuous",
    "持續", "維持", "保持", "穩定",
]
# Duration token pattern (number + time unit).
DURATION_RE = re.compile(r'\b(\d+(?:\.\d+)?)\s*(us|μs|ms|ns|s|cyc|cycle)s?\b', re.IGNORECASE)

# Edge-detect RTL pattern: a previous-value latch + AND of current-and-not-previous (or inverse).
# Match Verilog/SystemVerilog idioms.
EDGE_PATTERNS = [
    # rising edge: x && !x_prev / !x_q && x
    re.compile(r'(\w+)\s*&&\s*!\s*(\w+_(?:q|prev|d|r))', re.IGNORECASE),
    re.compile(r'!\s*(\w+_(?:q|prev|d|r))\s*&&\s*(\w+)', re.IGNORECASE),
    # falling edge
    re.compile(r'!\s*(\w+)\s*&&\s*(\w+_(?:q|prev|d|r))', re.IGNORECASE),
]
# Sustain counter pattern: a register that increments while a level is held.
SUSTAIN_COUNTER_PATTERNS = [
    re.compile(r'(\w+_(?:cnt|counter|cyc|low|high|hold|sustain))\s*<=\s*\1\s*\+\s*\d', re.IGNORECASE),
    re.compile(r'if\s*\(\s*(\w+_(?:cnt|counter|cyc|low|high|hold|sustain))\s*[><=]', re.IGNORECASE),
    re.compile(r'>=\s*[`\w]+(?:_(?:CYC|MS|US|NS|TIME|THRESHOLD))', re.IGNORECASE),
]


@dataclass
class SignalFinding:
    signal: str
    file: str
    line: int
    edge_pattern: str
    has_sustain_counter: bool
    spec_match: Optional[str] = None
    severity: str = "WARN"


@dataclass
class Result:
    status: str
    findings: List[SignalFinding] = field(default_factory=list)
    files_scanned: int = 0          # files actually OPENED, not files globbed
    files_unreadable: int = 0       # #492 — globbed but could not be read
    spec_signals: List[str] = field(default_factory=list)
    # Provenance of the OTHER half of the comparison. Without these a PASS
    # cannot be told apart from "no spec was read, so the ERROR arm was never
    # exercised" — which is the state every umbrella run was in.
    spec_provenance: str = "none"   # explicit | discovered | none
    spec_sources: List[str] = field(default_factory=list)
    spec_source_root: Optional[str] = None
    spec_clauses: int = 0


#: Ancestors of `--rtl-dir` to consider when looking for the project root.
#: The umbrella's rtl_dir is `<project>/phase2/stage1/rtl` at the deepest, so 4
#: levels reaches it; 5 leaves one spare without letting the walk wander into a
#: corpus root that happens to hold an unrelated `phase1/`.
_SPEC_DISCOVERY_MAX_LEVELS = 5
#: Bounds so discovery cannot blow the umbrella's 60 s per-gate subprocess
#: timeout on a project with a large doc tree.
_SPEC_DISCOVERY_MAX_FILES = 80
_SPEC_DISCOVERY_MAX_BYTES = 4_000_000


def _spec_source_files(project: Path) -> List[Path]:
    """The project's natural-language spec sources, in a stable order.

    Same set `design_one_shot_runner._gather_spec_text` uses, so a gate and the
    runner read the same prose rather than two different ideas of "the spec".
    """
    files: List[Path] = []
    for d in (_pl.input_doc_dir(project), _pl.input_prompt_dir(project)):
        try:
            if d.is_dir():
                files += [f for f in sorted(d.rglob("*"))
                          if f.is_file() and f.suffix.lower() in {".md", ".txt"}]
        except OSError:
            continue
    gd = _pl.generated_docs_dir(project)
    try:
        if gd.is_dir():
            files += sorted(gd.glob("L*.json"))
    except OSError:
        pass
    return files


def _discover_project_root(rtl_dir: Path) -> Optional[Path]:
    """First ancestor of `rtl_dir` (then the cwd) that holds spec sources.

    Walking up from the RTL being scanned is what PAIRS the spec with that RTL;
    the cwd fallback is there because the umbrella runs every structural gate
    with `cwd=project`, so it is the project root by construction even when the
    rtl dir was handed in from elsewhere.
    """
    candidates: List[Path] = []
    try:
        p = rtl_dir.resolve()
    except OSError:
        p = rtl_dir
    for _ in range(_SPEC_DISCOVERY_MAX_LEVELS + 1):
        candidates.append(p)
        if p.parent == p:
            break
        p = p.parent
    try:
        candidates.append(Path.cwd())
    except OSError:
        pass
    for c in candidates:
        if _spec_source_files(c):
            return c
    return None


def _load_spec_text(explicit: Optional[Path],
                    rtl_dir: Path) -> Tuple[str, str, List[Path], Optional[Path]]:
    """Return (text, provenance, sources_read, project_root).

    `provenance` is one of `explicit` / `discovered` / `none`, and it is the
    field that keeps a PASS honest: `none` means the RTL was scanned but never
    compared against anything.
    """
    if explicit is not None:
        return explicit.read_text(errors="replace"), "explicit", [explicit], None
    root = _discover_project_root(rtl_dir)
    if root is None:
        return "", "none", [], None
    chunks: List[str] = []
    read: List[Path] = []
    total = 0
    for f in _spec_source_files(root)[:_SPEC_DISCOVERY_MAX_FILES]:
        try:
            t = f.read_text(errors="replace")
        except OSError:
            continue
        chunks.append(t)
        read.append(f)
        total += len(t)
        if total >= _SPEC_DISCOVERY_MAX_BYTES:
            break
    if not read:
        return "", "none", [], None
    return "\n\n".join(chunks), "discovered", read, root


def clause_names_signal(clause: str, sig: str) -> bool:
    """True when `clause` names `sig` as a whole identifier.

    Substring containment was enough while `sustain_clauses` was always empty;
    with real spec prose in play it is a false-positive engine — a two-letter
    signal like `en` is inside "when", "enable" and "length", so any timing
    sentence would "name" it. Identifier boundaries, not `\\b`, because a signal
    may legitimately start or end with `_` and `\\b` treats `_` as a word char.
    """
    if not sig:
        return False
    return re.search(r'(?<![A-Za-z0-9_])' + re.escape(sig) + r'(?![A-Za-z0-9_])',
                     clause, re.IGNORECASE) is not None


def extract_sustain_clauses(spec_text: str) -> List[str]:
    """Pull sentences/lines that mention a sustain-class word AND a duration."""
    out = []
    for line in spec_text.splitlines():
        s = line.strip()
        if not s:
            continue
        if not any(w in s.lower() if w.isascii() else w in s for w in SUSTAIN_WORDS):
            continue
        if not DURATION_RE.search(s):
            continue
        out.append(s)
    return out


def _is_readable(p: Path) -> bool:
    """True when `p` can actually be opened.

    #492 — separates "the glob yielded this path" from "this file exists and can
    be read". A dangling symlink satisfies the former and not the latter, and
    conflating them is how a denominator ends up counting a file that is not
    there. Opens and closes without reading, so it stays cheap.
    """
    try:
        with p.open("rb"):
            return True
    except OSError:
        return False


def scan_rtl_file(p: Path) -> List[tuple]:
    """Return list of (line_no, edge_signal, raw_line, has_local_sustain)."""
    found = []
    try:
        text = p.read_text(errors="replace")
    except Exception:
        return found
    lines = text.splitlines()
    # First pass: collect all sustain-counter-looking lines per file
    sustain_lines = set()
    for i, ln in enumerate(lines, 1):
        if any(p.search(ln) for p in SUSTAIN_COUNTER_PATTERNS):
            sustain_lines.add(i)

    for i, ln in enumerate(lines, 1):
        if "//" in ln:
            ln_clean = ln.split("//", 1)[0]
        else:
            ln_clean = ln
        for pat in EDGE_PATTERNS:
            m = pat.search(ln_clean)
            if not m:
                continue
            # The "live" signal is the one without _q/_prev/_d/_r suffix
            g1, g2 = m.group(1), m.group(2)
            live = g1 if not re.search(r'_(?:q|prev|d|r)$', g1, re.IGNORECASE) else g2
            base = re.sub(r'_(?:q|prev|d|r)$', '', live, flags=re.IGNORECASE)
            # sustain counter present within +/- 30 lines of the edge?
            has_sus = any(abs(s - i) <= 30 for s in sustain_lines)
            found.append((i, base, ln.rstrip(), has_sus))
            break
    return found


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--rtl-dir", required=True, type=Path)
    ap.add_argument("--spec-text", type=Path,
                    help="Concatenated spec text. OPTIONAL: when omitted the "
                         "gate discovers the project's own spec sources by "
                         "walking up from --rtl-dir (phase1/input_doc, "
                         "phase1/input_prompt, phase1/generated_docs/L*.json). "
                         "Pass it to pin an exact document instead.")
    # #494 — a read-only validator writes NOTHING unless a caller asks for it.
    # This used to default to a hardcoded `/tmp/sustained_vs_edge`, so every
    # invocation — including the P0 umbrella's, which passes only --rtl-dir —
    # deposited a JSON report at a fixed shared path nobody requested. Two
    # concurrent umbrella runs (two projects, or CI alongside a local run)
    # silently overwrote each other's report, so the file a human later read
    # while diagnosing could belong to a different design with nothing marking
    # it as such. A fixed name under a world-writable directory is also the
    # textbook symlink-hijack target, and this repo's own
    # `project_outputs_in_tree_check` FAILs a project for citing exactly such a
    # /tmp artifact. Omitted now means stdout only; pass --out-dir to opt in.
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Directory to write the JSON report into. Omitted "
                         "(the default) = write no file at all; the verdict "
                         "goes to stdout only.")
    ap.add_argument("--strict", action="store_true", help="Treat warns as errors (exit 1)")
    args = ap.parse_args(argv)

    if not args.rtl_dir.is_dir():
        print(f"ERROR: rtl-dir not found: {args.rtl_dir}", file=sys.stderr)
        return 2
    # A caller that ASKED for a spec comparison and named a file that is not
    # there used to get the silent no-spec mode — the same false green this
    # change exists to remove, one layer up. Input-missing is rc 2 everywhere
    # else in this gate; it is rc 2 here too. Zero blast radius on the umbrella,
    # which never supplies this flag.
    if args.spec_text is not None and not args.spec_text.is_file():
        print(f"SKIP: sustained_vs_edge_check — --spec-text not found: "
              f"{args.spec_text}; nothing to compare RTL against, no verdict",
              file=sys.stderr)
        return 2
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    spec_text, spec_provenance, spec_sources, spec_root = _load_spec_text(
        args.spec_text, args.rtl_dir)
    sustain_clauses = extract_sustain_clauses(spec_text) if spec_text else []
    spec_signals: List[str] = []
    # Heuristic: extract identifier-like words from each sustain clause
    for cl in sustain_clauses:
        for tok in re.findall(r'\b([A-Za-z][A-Za-z0-9_]+)\b', cl):
            if tok.lower() in {"if", "the", "and", "for", "with", "must", "is", "be", "on"}:
                continue
            spec_signals.append(tok.lower())
    spec_signals = list(set(spec_signals))

    # #492 — a path the glob yields is not necessarily a path that can be READ.
    # A dangling symlink matches `*.v` and `scan_rtl_file` swallows the resulting
    # OSError and returns no findings, so the file was counted as scanned while
    # contributing nothing. The count is now what was actually opened, and files
    # that could not be are disclosed separately instead of padding the number.
    _globbed = sorted([p for p in args.rtl_dir.rglob("*")
                       if p.suffix.lower() in {".v", ".sv", ".vh", ".svh"}])
    rtl_files = [p for p in _globbed if _is_readable(p)]
    unreadable = [p for p in _globbed if p not in rtl_files]

    # #492 — NOT CHECKED is not PASS. With nothing readable there is no evidence
    # for any verdict, and rc 0 would certify a check that examined nothing.
    # rc 2 is this repo's "NOT CHECKED / VACUOUS" code and is what the sibling
    # `phase1_k5_quality_check` returns in the same situation.
    if not rtl_files:
        print(f"SKIP: sustained_vs_edge_check — no readable RTL under "
              f"{args.rtl_dir} ({len(unreadable)} unreadable of "
              f"{len(_globbed)} globbed); nothing examined, no verdict",
              file=sys.stderr)
        return 2

    findings: List[SignalFinding] = []
    for rf in rtl_files:
        for line_no, sig, raw, has_sus in scan_rtl_file(rf):
            # An EXPLICIT --spec-text is a caller narrowing the scope to the
            # document it named, so the pre-filter still applies there. A
            # DISCOVERED spec must not narrow it: the discovered corpus is
            # broad, and letting it drop WARNs would silently shrink the finding
            # set every current umbrella run already produces. This change is
            # additive on the ERROR arm and leaves the WARN arm exactly as it
            # was.
            if (spec_provenance == "explicit" and spec_signals
                    and sig.lower() not in spec_signals):
                continue
            spec_match = None
            for cl in sustain_clauses:
                if clause_names_signal(cl, sig):
                    spec_match = cl[:200]
                    break
            severity = "ERROR" if (spec_match and not has_sus) else "WARN"
            if has_sus and not spec_match:
                # Edge with local sustain counter — likely correct.
                continue
            findings.append(SignalFinding(
                signal=sig, file=str(rf), line=line_no,
                edge_pattern=raw[:150], has_sustain_counter=has_sus,
                spec_match=spec_match, severity=severity,
            ))

    errors = [f for f in findings if f.severity == "ERROR"]
    warns = [f for f in findings if f.severity == "WARN"]
    status = "PASS" if not errors and (not args.strict or not warns) else "FAIL"

    res = Result(status=status, findings=findings, files_scanned=len(rtl_files),
                 files_unreadable=len(unreadable), spec_signals=spec_signals[:30],
                 spec_provenance=spec_provenance,
                 spec_sources=[str(p) for p in spec_sources[:30]],
                 spec_source_root=str(spec_root) if spec_root else None,
                 spec_clauses=len(sustain_clauses))
    # #494 — write only when asked. Kept at the original position (before the
    # summary print) so the stdout the umbrella reads is byte-identical when
    # --out-dir IS supplied; `out_json` stays None otherwise and the trailing
    # `json:` line — which would name a path that does not exist — is dropped
    # with it.
    out_json = None
    if args.out_dir is not None:
        out_json = args.out_dir / "sustained_vs_edge_check.json"
        out_json.write_text(json.dumps(asdict(res), indent=2, default=str))
    print(f"sustained_vs_edge_check: {status} — {len(errors)} errors, {len(warns)} warns, {len(rtl_files)} files scanned")
    # The other half of the denominator, stated on EVERY verdict. `none` is the
    # state every umbrella run was silently in: RTL scanned, spec never read,
    # ERROR arm never exercised, and a PASS printed anyway.
    if spec_provenance == "none":
        print("spec: none — no spec text supplied or discovered; RTL was NOT "
              "compared against any spec (sustain/edge mismatch not evaluated)")
    else:
        print(f"spec: {spec_provenance} — {len(spec_sources)} source(s), "
              f"{len(sustain_clauses)} sustain clause(s)"
              + (f", root={spec_root}" if spec_root else ""))
    print(f"findings: {len(findings)}")
    for f in findings[:20]:
        print(f"  [{f.severity}] {f.file}:{f.line} signal={f.signal}  sustain_counter={f.has_sustain_counter}")
        if f.spec_match:
            print(f"    spec: {f.spec_match}")
    if out_json is not None:
        print(f"json: {out_json}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
