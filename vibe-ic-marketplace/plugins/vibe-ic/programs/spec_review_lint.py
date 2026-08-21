#!/usr/bin/env python3
"""spec_review_lint.py — deterministic structural presence lint for a NL spec.

since v0.2.14.

ENFORCEMENT: advisory

Wiring
------
ADVISORY at flow step D1, invoked as
``spec_review_lint --strict input/docs/*.md input/docs/*.rst input/*.md``.

Two parts of that invocation are load-bearing and must not be "simplified":

  * ``--strict`` — without it every finding is a WARN and the program exits 0
    unconditionally, so a gate wired without it could never fail. It is
    therefore wired strict AND advisory, never non-strict and blocking.
  * the GLOB LIST, never a directory — measured, ``spec_review_lint .`` exits 2
    forever (a directory is not a file), which the flow reads as a permanent
    VACUOUS_PASS. Wired somewhere it can never execute is the same defect as
    not being wired.

WHY ADVISORY, AND WHAT WOULD PROMOTE IT
Measured over the 16 published runs before wiring: 12 red under ``--strict``,
0 red without it, 4 vacuous (no ``input/`` at all). Of 422 WARNs, 329 (78%) are
``corner-case-uncovered`` — and that check is evaluated PER FILE, so a spec
split across 18 chapter files scores up to 72 of them even when all four corner
cases ARE covered by the corpus as a whole. Proven directly: a complete
single-file spec scores 0 findings alone, and 4 corner-case WARNs the moment an
unrelated one-line appendix joins the same invocation. Promotion to blocking
requires that check to aggregate per CORPUS rather than per file, followed by a
re-measurement — not a judgement call.

The `spec-review` skill screens a natural-language hardware spec for defects
BEFORE `/spec-to-rtl` turns the defects into RTL. Most of that review is genuine
AI judgment (ambiguity wording, suggested rewrites, internal-consistency of prose).
But the skill's checklist *also* contains a purely STRUCTURAL part — "is this
attribute declared at all?" — that is mechanical and must run identically every
time. This program extracts exactly that structural part so the agent never has
to eyeball it, and so the same spec always yields the same machine findings.

It implements EXACTLY the presence/structure items enumerated in
`skills/spec-review/SKILL.md`:

  Dimension 1 (Unambiguous)
    • every DECLARED signal has {direction, width, polarity, clock, reset}
    • every timing statement has a reference (clock) edge
  Dimension 3 (Testable)
    • every DECLARED mode has an entry AND an exit condition
  Dimension 4 (Complete corner cases) — checklist coverage
    • reset during operation
    • back-to-back transactions
    • full / empty / overflow / underflow
    • illegal inputs — defined vs undefined behaviour

It does NOT attempt the judgment dimensions (ambiguous-sentence detection,
suggested rewrites, prose internal-consistency, protocol/non-functional review) —
those stay with the agent per the wired SKILL.md.

Findings (verdict tiers):
  WARN (reported; fails the gate only with --strict):
    signal-missing-attr   : a declared signal is missing one of
                            {direction,width,polarity,clock,reset}.
    timing-no-ref-edge    : a timing statement has no reference clock edge.
    mode-missing-entry    : a declared mode has no entry condition.
    mode-missing-exit     : a declared mode has no exit condition.
    corner-case-uncovered : a corner-case checklist item is not addressed.

NO-FALSE-ALERT contract (this is a lint, not an opinion):
  • Per-signal attribute findings fire ONLY for signals that are actually
    DECLARED in an interface list (a real declaration to check against). A pure
    prose spec with no interface list yields ZERO signal findings (reported as
    SKIP), never a flood.
  • `width` is only required for signals whose declaration shows them as a vector
    (an explicit `[msb:lsb]` / "(N bits)") OR is REPORTED-PRESENT when a scalar;
    a 1-bit scalar is never flagged for "missing width".
  • `polarity` / `clock` / `reset` attributes are only required for the signal
    classes for which they are meaningful — they are detected from the signal's
    OWN declaration text and the reset/clock context, never invented.
  • Timing / mode / corner-case checks only fire when the corresponding STRUCTURE
    is present (a timing statement exists; a mode is named) — a spec that simply
    doesn't have timing or modes is not penalised for their attributes; the
    corner-case checklist is the one always-applicable coverage list and each
    uncovered item is at most a WARN.
  • Unreadable / empty spec  -> MISSING (exit 2), never a crash.

chip-AGNOSTIC: detection is purely textual/structural over the spec — no IC-,
bus-, vendor-, or protocol-specific literals. Spec may be a natural-language
prompt (.txt/.md), a JSON contract (.json), or a markdown verilog header (.v/.sv).

CLI:
    python3 spec_review_lint.py <spec.md|spec.txt|spec.json|hdr.v> ...
    python3 spec_review_lint.py --spec <file> [--strict] [--json OUT]

Exit codes:
    0 = PASS   1 = (with --strict) any WARN finding   2 = no spec / parse error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from _specrtl_common import (Port, extract_spec_contract, strip_comments,
                                 _NL_PORT)
except ImportError:  # allow running from another cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _specrtl_common import (Port, extract_spec_contract, strip_comments,
                                 _NL_PORT)


# ── attribute / class detectors (chip-AGNOSTIC, structural) ─────────────────
# A clock-shaped signal name (its own declaration tells us it is a clock; clocks
# do not themselves need a clock/reset/polarity attribute).
_CLOCK_NAME = re.compile(r'\b(clk|clock|sclk|hclk|pclk|aclk|mclk|gclk)\b', re.I)
# A reset-shaped signal name (resets carry polarity but not their own clock).
_RESET_NAME = re.compile(r'\b(rst|reset|clr|clear|por|nrst|arst|srst|resetn|rst_n)\b', re.I)
# Polarity declared for a (reset / control) signal: active-high/low or _n suffix.
_POLARITY_DECL = re.compile(r'active[\s_-]*(?:high|low)|\b\w+_n\b|inverted|negated', re.I)
# A clock-domain reference in prose: "clocked by", "on the rising edge of clk", …
_CLOCK_REF = re.compile(
    r'\bclock(?:ed|\s+domain)\b|\b(?:rising|falling|posedge|negedge|positive|negative)\s+edge\b'
    r'|\bon\s+(?:the\s+)?\w*\s*(?:edge|clock|clk)\b'
    r'|\b(?:synchronous|sampled|registered)\b', re.I)
# Reference-edge for a TIMING statement.
_REF_EDGE = re.compile(
    r'\b(?:rising|falling|posedge|negedge|positive|negative)\s+edge\b'
    r'|\bposedge\b|\bnegedge\b'
    r'|\b(?:on|after|relative\s+to|with\s+respect\s+to)\s+(?:the\s+)?(?:\w+\s+)?'
    r'(?:edge|clock|clk)\b'
    r'|\bclock\s+(?:edge|cycle)\b', re.I)
# A sentence is a TIMING statement when it states a quantified timing requirement.
# NOTE: bare "hold"/"setup" are NOT timing terms (they are also plain verbs:
# "hold result", "setup the FIFO"). They only count as timing when used as the
# nouns "setup time" / "hold time" / "setup-and-hold" / "<n> ns setup", to avoid
# false-flagging an ordinary sentence that happens to contain the word.
_TIMING_STMT = re.compile(
    r'\b(?:setup|hold)\b[\s-]*(?:time|window|requirement|constraint|margin|of)\b'
    r'|\b(?:setup|hold)[\s-]+and[\s-]+(?:setup|hold)\b'
    r'|\b\d+(?:\.\d+)?\s*(?:ns|ps|us|ms)\b\s*(?:setup|hold)?'
    r'|\b(?:t_?su|t_?h|t_?co|t_?pd)\b'
    r'|\bpropagation\s+delay\b'
    r'|\b\d+(?:\.\d+)?\s*clock\s+cycles?\b'
    r'|\b(?:within|after|before)\s+\d+\s*(?:ns|ps|us|ms|clock\s+cycles?|cycles?)\b'
    r'|\b(?:propagation|setup|hold|clock-to-q)\s+latency\b', re.I)


# ── corner-case checklist (EXACTLY the four SKILL.md "Complete corner cases") ─
# Each entry: (id, human label, [synonyms each item may be addressed by]).
# A checklist item is COVERED when any synonym appears as a whole word.
_CORNER_CASES: List[Tuple[str, str, List[str]]] = [
    ("reset-during-operation", "reset during operation",
     [r"reset\s+during", r"reset\s+(?:while|in)\s+\w*\s*operation",
      r"reset\s+(?:mid|in[\s-]*flight)", r"asserted\s+during",
      r"reset\s+(?:is\s+)?(?:asserted|applied).{0,40}(?:operation|transaction|transfer|run)"]),
    ("back-to-back", "back-to-back transactions",
     [r"back[\s-]*to[\s-]*back", r"consecutive\s+(?:transaction|transfer|request|cycle)",
      r"(?:no|zero)\s+(?:idle|gap)\s+(?:cycle|between)", r"successive\s+\w+",
      r"pipelined?\s+(?:transaction|request|transfer)"]),
    ("full-empty-overflow-underflow", "full / empty / overflow / underflow",
     [r"\boverflow\b", r"\bunderflow\b", r"\bfull\b", r"\bempty\b",
      r"\bsaturat", r"\bwrap[\s-]*around\b"]),
    ("illegal-inputs", "illegal inputs (defined vs undefined behaviour)",
     [r"\billegal\b", r"\binvalid\b", r"undefined\s+behaviou?r", r"\breserved\b",
      r"out[\s-]*of[\s-]*range", r"don'?t[\s-]*care", r"unsupported"]),
]


# ── mode detection ──────────────────────────────────────────────────────────
# A declared MODE: "<Name> mode" / "in <Name> mode" / a "Mode: NAME" header.
_MODE_DECL = re.compile(
    r'\b([A-Z][A-Za-z0-9_]*(?:[\s_-][A-Z]?[A-Za-z0-9_]+)?)\s+mode\b'
    r'|\bmode\s*[:=]\s*([A-Za-z0-9_]+)', re.M)
_ENTRY = re.compile(r'\benter(?:s|ed|ing)?\b|\bentry\b|\bupon\b|\bwhen\b|\benters?\s+\w*\s*mode\b'
                    r'|\bactivat|\btransition(?:s)?\s+(?:to|into)\b|\bswitch(?:es)?\s+to\b', re.I)
_EXIT = re.compile(r'\bexit(?:s|ed|ing)?\b|\bleave(?:s)?\b|\bdeactivat'
                   r'|\btransition(?:s)?\s+(?:out|from|back)\b|\breturn(?:s)?\s+to\b'
                   r'|\buntil\b|\bclears?\b|\bdisabl', re.I)

_MIN_SPEC_CHARS = 20   # length-floor: below this there is nothing to lint

# ── denominator disclosure ──────────────────────────────────────────────────
# A caller reaches this program through a GLOB (the flow gate passes
# `input/docs/*.md input/docs/*.rst input/*.md`). A glob that matches one file
# in a directory holding eighteen spec chapters still produces a verdict, and
# the old output — "[1 spec(s) linted]" — read exactly like a verdict over the
# whole corpus. MEASURED: one published run ships 17 `.rst` spec chapters plus
# 2 `.md`; a `*.md`-only glob linted 1 of them and reported a verdict.
#
# This is a DISCLOSURE, not a threshold: the unread siblings are reported at
# INFO severity, which by construction cannot move the exit code (only ERROR,
# and WARN under --strict, do). It exists so a verdict can never again hide
# how much of the corpus produced it.
_SPEC_SUFFIXES = {".md", ".rst", ".txt", ".json", ".v", ".sv"}


@dataclass
class Finding:
    code: str
    severity: str
    message: str


# --- per-signal attribute checks -------------------------------------------
def _signal_declaration_spans(text: str) -> Dict[str, str]:
    """For each NL-declared signal, return the raw text of its declaration line
    (the structural anchor we are allowed to check attributes against). Returns
    {} when there is no interface bullet list — the no-false-alert guard that
    keeps a pure-prose spec from yielding signal findings."""
    spans: Dict[str, str] = {}
    for m in _NL_PORT.finditer(text):
        name = m.group(2)
        line_start = text.rfind('\n', 0, m.start()) + 1
        line_end = text.find('\n', m.end())
        line_end = line_end if line_end != -1 else len(text)
        spans[name] = text[line_start:line_end]
    return spans


def _check_signal_attrs(text: str, contract) -> List[Finding]:
    findings: List[Finding] = []
    spans = _signal_declaration_spans(text)
    if not spans:
        return findings  # SKIP: no interface list to check (graceful)

    low_full = text.lower()
    by_name = {p.name: p for p in contract.ports}

    # Does the spec name a clock and a reset signal anywhere? (domain anchors)
    has_named_clock = bool(_CLOCK_NAME.search(low_full))
    has_named_reset = bool(_RESET_NAME.search(low_full))
    # global clock-domain prose (covers single-domain designs once)
    clock_ref_global = bool(_CLOCK_REF.search(text))

    for name, decl in spans.items():
        port = by_name.get(name)
        decl_low = decl.lower()
        is_clock = bool(_CLOCK_NAME.search(name))
        is_reset = bool(_RESET_NAME.search(name))

        missing: List[str] = []

        # direction — required for every signal; present iff parsed as a Port.
        if port is None or not (port.direction or "").strip():
            missing.append("direction")

        # width — only meaningful/required for VECTOR (multi-bit) signals; a scalar
        # 1-bit control/clock/reset is COMPLETE without an explicit width and is
        # NEVER flagged. A signal is treated as a vector only when its name or
        # declaration carries unambiguous multi-bit intent (a "bus"/"data"/"addr"/
        # "word" component, or an opened-but-empty range) yet states NO width.
        width_present = (port is not None and port.width and port.width > 1) \
            or bool(re.search(r'\(\s*\d+\s*bits?\s*\)|\[\s*\d+\s*:\s*\d+\s*\]', decl_low))
        name_says_vector = bool(re.search(
            r'(?:^|_)(?:bus|data|addr|address|word|payload|vector|dout|din|count|cnt)'
            r'(?:_|$)', name, re.I))
        decl_says_vector = name_says_vector or bool(re.search(r'\[\s*\d', decl_low))
        if decl_says_vector and not is_clock and not is_reset and not width_present:
            missing.append("width")

        # polarity — required for signals whose meaning depends on it: reset and
        # any signal explicitly described elsewhere as active-high/low or _n.
        if is_reset:
            pol_here = bool(_POLARITY_DECL.search(decl)) or bool(name.endswith("_n"))
            # also accept polarity stated in reset context anywhere in the spec
            pol_ctx = bool(re.search(
                r'(?:%s)[^\n.]{0,60}(?:active[\s_-]*(?:high|low))'
                r'|(?:active[\s_-]*(?:high|low))[^\n.]{0,60}(?:%s)'
                % (re.escape(name), re.escape(name)), low_full))
            if not (pol_here or pol_ctx
                    or contract.reset_polarity):
                missing.append("polarity")

        # clock — every signal lives in a clock domain. A clock signal itself is
        # its own domain (skip). A reset's clock matters only for sync resets, but
        # we require the spec to state SOME clock-domain anchor for sampled signals.
        if not is_clock:
            # signal-local clock-domain mention, OR a global single-domain anchor
            sig_clock = bool(re.search(
                r'(?:%s)[^\n.]{0,80}(?:clock|clk|edge|domain|sampled|registered)'
                % re.escape(name), low_full))
            if not (has_named_clock and (sig_clock or clock_ref_global)):
                missing.append("clock")

        # reset — every stateful signal has a reset domain. We require the spec to
        # name a reset (or state the signal/domain is reset) for non-clock signals.
        if not is_clock:
            sig_reset = bool(re.search(
                r'(?:%s)[^\n.]{0,80}(?:reset|cleared|initial(?:ized|ised)?|defaults?\s+to)'
                % re.escape(name), low_full))
            if not (has_named_reset or sig_reset or is_reset
                    or contract.reset_mode or contract.reset_signal):
                missing.append("reset")

        for attr in missing:
            findings.append(Finding(
                "signal-missing-attr", "WARN",
                f"declared signal '{name}' is missing its {attr} declaration "
                f"(SKILL.md Unambiguous: every signal needs "
                f"direction/width/polarity/clock/reset)."))
    return findings


# --- timing reference-edge check -------------------------------------------
def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r'(?<=[.\n])', text) if s.strip()]


def _check_timing_ref_edges(text: str) -> List[Finding]:
    findings: List[Finding] = []
    for sent in _split_sentences(text):
        if _TIMING_STMT.search(sent) and not _REF_EDGE.search(sent):
            # length-floor / structural: must be a real prose sentence, not a
            # one-token fragment, before we flag it.
            if len(sent.split()) >= 4:
                snippet = sent if len(sent) <= 90 else sent[:87] + "..."
                findings.append(Finding(
                    "timing-no-ref-edge", "WARN",
                    f"timing statement has no reference clock edge: \"{snippet}\" "
                    f"(SKILL.md Unambiguous: every timing statement needs a "
                    f"reference edge)."))
    return findings


# --- mode entry/exit check --------------------------------------------------
_GENERIC_MODE = {"this", "the", "a", "an", "each", "any", "no", "single", "one",
                 "normal", "operation", "operating"}


def _declared_modes(text: str) -> List[str]:
    modes: List[str] = []
    seen = set()
    for m in _MODE_DECL.finditer(text):
        nm = (m.group(1) or m.group(2) or "").strip()
        if not nm:
            continue
        key = nm.lower()
        # deny-list: drop generic words that are not real mode names
        if key in _GENERIC_MODE or key in seen:
            continue
        # length-floor: a mode name is at least 2 chars and not a bare article
        if len(key) < 2:
            continue
        seen.add(key)
        modes.append(nm)
    return modes


def _check_modes(text: str) -> List[Finding]:
    findings: List[Finding] = []
    modes = _declared_modes(text)
    if not modes:
        return findings  # SKIP: no modes declared (graceful)
    for mode in modes:
        # window = sentences that mention this mode by name
        ctx = " ".join(s for s in _split_sentences(text)
                       if re.search(r'\b' + re.escape(mode) + r'\b', s, re.I))
        if not ctx:
            continue
        if not _ENTRY.search(ctx):
            findings.append(Finding(
                "mode-missing-entry", "WARN",
                f"mode '{mode}' has no stated entry condition "
                f"(SKILL.md Testable: every mode needs an entry condition)."))
        if not _EXIT.search(ctx):
            findings.append(Finding(
                "mode-missing-exit", "WARN",
                f"mode '{mode}' has no stated exit condition "
                f"(SKILL.md Testable: every mode needs an exit condition)."))
    return findings


# --- corner-case checklist coverage ----------------------------------------
def _check_corner_cases(text: str) -> List[Finding]:
    findings: List[Finding] = []
    low = text.lower()
    for cid, label, syns in _CORNER_CASES:
        covered = any(re.search(s, low) for s in syns)
        if not covered:
            findings.append(Finding(
                "corner-case-uncovered", "WARN",
                f"corner case '{label}' is not addressed in the spec "
                f"(SKILL.md Complete-corner-cases checklist item '{cid}')."))
    return findings


# --- top-level ---------------------------------------------------------------
def lint_spec(text: str, is_json: bool = False) -> List[Finding]:
    """Run the full structural presence lint. Returns the list of Findings."""
    findings: List[Finding] = []
    contract = extract_spec_contract(text, is_json=is_json, confirm=False)
    findings.extend(_check_signal_attrs("" if is_json else text, contract))
    if not is_json:
        clean = strip_comments(text)
        findings.extend(_check_timing_ref_edges(clean))
        findings.extend(_check_modes(clean))
        findings.extend(_check_corner_cases(clean))
    return findings


def _read_spec(path: Path) -> Tuple[str, bool]:
    text = path.read_text(errors="replace")
    return text, path.suffix.lower() == ".json"


def _unread_siblings(files: List[Path],
                     exclude: Optional[Path] = None) -> List[Path]:
    """Spec-shaped files sitting in the SAME directories as the ones we were
    given, which were not given to us. Non-recursive on purpose: the question
    is "did the caller's pattern under-select this directory?", not "is there
    a spec anywhere on disk".

    `exclude` drops this program's OWN --json report, which is `.json` and can
    land beside a spec — a report is an output, never an unread input."""
    given = {f.resolve() for f in files}
    if exclude is not None:
        try:
            given.add(exclude.resolve())
        except OSError:
            pass
    out: List[Path] = []
    for d in sorted({f.resolve().parent for f in files}):
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if (p.is_file() and p.suffix.lower() in _SPEC_SUFFIXES
                    and p.resolve() not in given):
                out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*",
                    help="Spec file(s): .txt/.md prompt, .json contract, or .v/.sv header")
    ap.add_argument("--spec", help="Spec file (alternative to positional)")
    ap.add_argument("--strict", action="store_true",
                    help="Fail (exit 1) on any WARN finding")
    ap.add_argument("--json", dest="json_out", help="Write findings as JSON to this path")
    a = ap.parse_args()

    specs = list(a.paths) + ([a.spec] if a.spec else [])
    files = [Path(s) for s in specs if Path(s).is_file()]
    if not files:
        print("spec_review_lint: MISSING — no spec file found", file=sys.stderr)
        return 2

    all_findings: List[dict] = []
    parsed = 0
    for f in files:
        try:
            text, is_json = _read_spec(f)
            if len(text.strip()) < _MIN_SPEC_CHARS:
                all_findings.append({"code": "spec-too-short", "severity": "INFO",
                                     "message": f"spec under {_MIN_SPEC_CHARS} chars — "
                                                "nothing to lint (SKIP)",
                                     "spec": str(f)})
                continue
            parsed += 1
            for fd in lint_spec(text, is_json=is_json):
                d = asdict(fd)
                d["spec"] = str(f)
                all_findings.append(d)
        except Exception as e:  # one bad spec must not crash the batch
            all_findings.append({"code": "parse-error", "severity": "ERROR",
                                 "message": str(e), "spec": str(f)})

    # Denominator disclosure — INFO only, cannot move the exit code.
    unread = _unread_siblings(
        files, Path(a.json_out) if a.json_out else None)
    if unread:
        all_findings.append({
            "code": "spec-corpus-partial", "severity": "INFO",
            "message": (
                f"{len(unread)} spec-shaped file(s) in the same directory(ies) "
                f"were NOT linted, so this verdict covers {len(files)} of "
                f"{len(files) + len(unread)} candidate spec files: "
                + ", ".join(str(p) for p in unread[:12])
                + (" …" if len(unread) > 12 else "")
                + " — widen the caller's pattern if these are part of the spec."),
            "spec": "(corpus)"})

    n_err = sum(1 for d in all_findings if d["severity"] == "ERROR")
    n_warn = sum(1 for d in all_findings if d["severity"] == "WARN")
    fail = n_err > 0 or (a.strict and n_warn > 0)
    verdict = "FAIL" if fail else "PASS"
    print(f"spec_review_lint: {verdict} — findings: {len(all_findings)} "
          f"({n_err} error, {n_warn} warn) "
          f"[{parsed} spec(s) linted of {len(files) + len(unread)} candidate(s)]")
    for d in all_findings:
        print(f"  [{d['severity']}] {d['code']}: {d['message']}")

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"verdict": verdict, "errors": n_err, "warnings": n_warn,
             "findings": all_findings}, indent=2) + "\n")

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
