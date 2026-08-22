"""v0.1.96 — Yosys synthesis-log error classifier (synth-doctor Pattern-B → program).

Doctrine: `skills/synth-doctor/SKILL.md` documents a 10-pattern Yosys-synth-log
classifier mined from the 135-IC campaign (`PRACTICAL_NOTES.md`). Each pattern
maps a log signature → a canonical auto-fix. This makes that table run
identically every time instead of being re-derived from prose per session.

Chip-AGNOSTIC: every signature is matched against generic Yosys / tool message
text — no benchmark name, no chip-specific path, signal, or register address.

The 10 canonical patterns (SKILL.md "10 known patterns from 135-IC campaign"):
    UNPACKED_ARRAY    — flatten unpacked array to packed
    MULTI_DRIVER      — merge drivers into a single always_ff
    RETURN_IN_FUNC    — assign function name instead of `return`
    PAST_IN_COMB      — shadow register for $past in comb
    AUTOMATIC_IN_FF   — module-level wire instead of automatic in FF
    LATCH_INFERENCE   — add default assignments (complete the case/if)
    SYNTAX_ERROR      — manual review (parse failure)
    MODULE_NOT_FOUND  — add the missing source file / read_verilog it
    WIDTH_MISMATCH    — explicit sizing / zero- or sign-extend
    UNKNOWN           — no known signature → manual review (the safe default)

Each finding carries `{matched_pattern, canonical_fix, confidence}`. `confidence`
is the deterministic per-pattern auto-fix success rate from PRACTICAL_NOTES.md.

No-false-alert contract:
  * Deny-list: known-benign Yosys progress lines (`Executing`, `=== ... ===`,
    `Warnings: 0 errors`) never trigger a match.
  * Length-floor: a log shorter than MIN_LOG_CHARS, or with no error/warning
    token at all, yields verdict CLEAN (no UNKNOWN spam).
  * The catch-all UNKNOWN is emitted only when there IS an error/warning the
    structured patterns did not recognise — never for a clean log.

CLI:
    python3 synth_doctor.py synth.log              # human diagnosis
    python3 synth_doctor.py synth.log --fix        # include the fix recipe
    python3 synth_doctor.py synth.log --json        # machine output
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# Patterns in priority order. The catch-all UNKNOWN is handled separately.
PATTERNS = (
    "UNPACKED_ARRAY",
    "MULTI_DRIVER",
    "RETURN_IN_FUNC",
    "PAST_IN_COMB",
    "AUTOMATIC_IN_FF",
    "LATCH_INFERENCE",
    "MODULE_NOT_FOUND",
    "WIDTH_MISMATCH",
    "SYNTAX_ERROR",
)

# Canonical fix per pattern — verbatim intent from SKILL.md + PRACTICAL_NOTES.md.
CANONICAL_FIX: Dict[str, str] = {
    "UNPACKED_ARRAY": (
        "Flatten the unpacked array to a packed vector "
        "(e.g. `logic [7:0] r [0:3]` -> `logic [31:0] r_flat`); "
        "Yosys does not support unpacked arrays as ports."),
    "MULTI_DRIVER": (
        "Merge all drivers of the signal into ONE always_ff block with a "
        "priority if-else chain (do not leave two always_ff driving the net). "
        "Preserve any keep/spare-tagged cells while merging."),
    "RETURN_IN_FUNC": (
        "Verilog functions return by assigning the function name, not "
        "`return`; replace `return expr;` with `<func_name> = expr;`."),
    "PAST_IN_COMB": (
        "`$past` is illegal in combinational/synthesis context; add a shadow "
        "register clocked on the same edge and read the shadow instead."),
    "AUTOMATIC_IN_FF": (
        "Hoist the automatic/local variable out of the always_ff block to a "
        "module-level wire/reg (automatic vars are not synthesizable in FF)."),
    "LATCH_INFERENCE": (
        "Complete the case/if: add a default assignment at the top of the "
        "always_comb (or a default: branch) so every path drives the signal."),
    "SYNTAX_ERROR": (
        "Manual review needed — fix the reported syntax/parse error; if it is "
        "a SystemVerilog-only construct, re-run with `read_verilog -sv`."),
    "MODULE_NOT_FOUND": (
        "Add the missing module's source file to the read_verilog list "
        "(no stub modules — DTOP must instantiate everything)."),
    "WIDTH_MISMATCH": (
        "Add explicit sizing to the assignment (zero-extend `{N'b0, x}` or "
        "sign-extend); decide zero- vs sign-extend per the signal's signedness."),
    "UNKNOWN": (
        "No known Yosys signature matched — present the raw error to a human "
        "for manual review (do not auto-apply a fix)."),
}

# Deterministic per-pattern confidence = auto-fix success rate from
# PRACTICAL_NOTES.md section 2. Manual-review patterns are 0.0.
CONFIDENCE: Dict[str, float] = {
    "UNPACKED_ARRAY": 0.95,
    "MULTI_DRIVER": 0.90,
    "RETURN_IN_FUNC": 0.90,
    "PAST_IN_COMB": 0.80,
    "AUTOMATIC_IN_FF": 0.95,
    "LATCH_INFERENCE": 0.95,
    "SYNTAX_ERROR": 0.0,
    "MODULE_NOT_FOUND": 0.95,
    "WIDTH_MISMATCH": 0.85,
    "UNKNOWN": 0.0,
}

# Signatures (chip-agnostic Yosys message text). First match wins, by priority.
SIGNATURES: List = [
    # UNPACKED_ARRAY — Yosys rejects unpacked arrays as ports / in some contexts.
    ("UNPACKED_ARRAY", re.compile(
        r"unpacked\s+array|array\s+as\s+.*port|"
        r"cannot\s+.*unpacked|memory.*as.*port", re.I)),
    # MULTI_DRIVER — multiple drivers on the same net.
    ("MULTI_DRIVER", re.compile(
        r"multiple\s+(?:conflicting\s+)?drivers|"
        r"driven\s+by\s+(?:multiple|more\s+than\s+one)|"
        r"signal\s+\S+\s+is\s+driven\s+by", re.I)),
    # RETURN_IN_FUNC — `return` used inside a Verilog function.
    ("RETURN_IN_FUNC", re.compile(
        r"return\s+statement.*function|"
        r"`?return`?\s+(?:is\s+)?(?:not\s+(?:allowed|supported)|illegal)",
        re.I)),
    # PAST_IN_COMB — $past in a non-clocked / synthesis context.
    ("PAST_IN_COMB", re.compile(
        r"\$past\b.*(?:combinational|not\s+(?:allowed|supported)|"
        r"synthesis)|system\s+function\s+\\?\$past", re.I)),
    # AUTOMATIC_IN_FF — automatic variable inside an FF / not synthesizable.
    ("AUTOMATIC_IN_FF", re.compile(
        r"automatic\s+(?:variable|task|function).*"
        r"(?:not\s+supported|synthesi|always)|"
        r"Local\s+declaration\s+in\s+unnamed\s+block", re.I)),
    # LATCH_INFERENCE — inferred latch from incomplete case/if.
    ("LATCH_INFERENCE", re.compile(
        r"inferr?ing\s+(?:a\s+)?latch|latch\s+inferr?ed|"
        r"incomplete\s+(?:case|assignment)|"
        r"signal\s+\S+\s+is\s+(?:used|read)\s+before", re.I)),
    # MODULE_NOT_FOUND — referenced module has no source.
    ("MODULE_NOT_FOUND", re.compile(
        r"(?:module|cell\s+type)\s+\\?\S+\s+(?:not\s+found|"
        r"is\s+not\s+(?:a\s+)?(?:known\s+)?(?:module|defined))|"
        r"cannot\s+find\s+module|referenced\s+module.*not\s+(?:found|defined)",
        re.I)),
    # WIDTH_MISMATCH — width/truncation mismatch (Yosys warns, not errors).
    ("WIDTH_MISMATCH", re.compile(
        r"width\s+mismatch|operand\s+size.*mismatch|"
        r"(?:truncat|sign-?extend|zero-?extend)\w*\s+(?:from|to)\s+\d+\s+bits|"
        r"port\s+\S+\s+(?:expects|has)\s+\d+\s+bits", re.I)),
    # SYNTAX_ERROR — generic parse failure (kept LAST of the structured set so
    # the more specific signatures win first).
    ("SYNTAX_ERROR", re.compile(
        r"syntax\s+error|parse\s+error|unexpected\s+(?:token|"
        r"TOK_|symbol|end\s+of\s+file)|expecting\s+\S+\s+(?:before|near)",
        re.I)),
]

# Deny-list: benign Yosys/tool progress lines that must NEVER trigger a match,
# even if they happen to contain a word like "error" inside a count of 0.
_BENIGN = re.compile(
    r"^\s*(?:===|---|\|)|"
    r"\bExecuting\b|\bRunning\b|"
    r"\b0\s+errors?\b|\bWarnings:\s*0\b|"
    r"successfully\s+(?:finished|completed)|"
    r"\bDone\b|\bEnd\s+of\s+script", re.I)

# Does a line look like an actual error/warning worth classifying?
_PROBLEM = re.compile(
    r"\b(?:error|warning|fatal|abort|fail(?:ed|ure)?)\b|"
    r"\bERROR\b|\bWARNING\b|^\s*ERROR:|^\s*Warning:", re.I)

# A log shorter than this is treated as "not a real log" -> CLEAN, no UNKNOWN.
MIN_LOG_CHARS = 8


@dataclass
class Diagnosis:
    matched_pattern: str
    canonical_fix: str
    confidence: float
    auto_fixable: bool
    evidence_line: str
    line_no: int

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_line(line: str) -> Optional[str]:
    """Return the pattern name for a single synth-log line, or None.

    Benign progress lines are denied first; the first matching signature
    (in priority order) wins. Never raises."""
    if not line or _BENIGN.search(line):
        return None
    for name, pat in SIGNATURES:
        if pat.search(line):
            return name
    return None


def classify_log(text: str) -> List[Diagnosis]:
    """Classify every problem line in a Yosys synth log.

    Returns one Diagnosis per matched (pattern) — deduplicated so a repeated
    signature is reported once with its first evidence line. An unrecognised
    error/warning line yields a single UNKNOWN. A clean log yields []."""
    if not text or len(text.strip()) < MIN_LOG_CHARS:
        return []

    matched: Dict[str, Diagnosis] = {}
    saw_unknown_problem = False
    unknown_line, unknown_no = "", 0

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        name = classify_line(line)
        if name:
            if name not in matched:
                matched[name] = Diagnosis(
                    matched_pattern=name,
                    canonical_fix=CANONICAL_FIX[name],
                    confidence=CONFIDENCE[name],
                    auto_fixable=CONFIDENCE[name] > 0.0,
                    evidence_line=line.strip()[:240],
                    line_no=lineno,
                )
            continue
        # Not matched — but is it a real problem the patterns missed?
        if _BENIGN.search(line):
            continue
        if _PROBLEM.search(line) and not saw_unknown_problem:
            saw_unknown_problem = True
            unknown_line, unknown_no = line.strip()[:240], lineno

    findings = list(matched.values())
    # Only emit UNKNOWN if there was an unrecognised problem AND nothing
    # structured matched (avoid drowning a real diagnosis in UNKNOWN noise).
    if saw_unknown_problem and not findings:
        findings.append(Diagnosis(
            matched_pattern="UNKNOWN",
            canonical_fix=CANONICAL_FIX["UNKNOWN"],
            confidence=CONFIDENCE["UNKNOWN"],
            auto_fixable=False,
            evidence_line=unknown_line,
            line_no=unknown_no,
        ))
    # Stable order: by line number.
    findings.sort(key=lambda d: d.line_no)
    return findings


def diagnose(text: str) -> Dict[str, Any]:
    """Top-level result envelope (importable)."""
    findings = classify_log(text)
    if not findings:
        verdict = "CLEAN"
    elif all(f.matched_pattern == "UNKNOWN" for f in findings):
        verdict = "MANUAL_REVIEW"
    else:
        verdict = "DIAGNOSED"
    return {
        "tool": "synth_doctor",
        "verdict": verdict,
        "findings": [f.as_dict() for f in findings],
        "count": len(findings),
        "emitted_by": _pmd.emitted_by("synth_doctor"),
    }


def report_to_text(result: Dict[str, Any], with_fix: bool) -> str:
    out = [f"synth_doctor: {result['verdict']} "
           f"({result['count']} pattern(s) matched)"]
    for f in result["findings"]:
        out.append(
            f"  [{f['matched_pattern']}] conf={f['confidence']:.2f} "
            f"auto_fixable={f['auto_fixable']} "
            f"(line {f['line_no']}): {f['evidence_line']}")
        if with_fix:
            out.append(f"      FIX: {f['canonical_fix']}")
    if result["verdict"] == "CLEAN":
        out.append("  No known error/warning signatures found.")
    return "\n".join(out)


def _cli(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Yosys synth-log error classifier (synth-doctor).")
    p.add_argument("log", type=Path, help="Yosys synthesis log file")
    p.add_argument("--fix", action="store_true",
                   help="Include the canonical fix recipe per finding")
    p.add_argument("--json", action="store_true",
                   help="Emit machine-readable JSON")
    p.add_argument("--out-json", type=Path, help="Write JSON to this file")
    args = p.parse_args(argv)

    if not args.log.is_file():
        print(f"synth_doctor: MISSING — log not found: {args.log}",
              file=sys.stderr)
        # MISSING, not crash: emit an empty CLEAN-equivalent envelope.
        result = {"tool": "synth_doctor", "verdict": "MISSING",
                  "findings": [], "count": 0,
                  "emitted_by": _pmd.emitted_by("synth_doctor")}
        if args.json:
            print(json.dumps(result, indent=2))
        return 2

    text = args.log.read_text(errors="replace")
    result = diagnose(text)
    if args.out_json:
        args.out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(report_to_text(result, with_fix=args.fix))
    # Exit 0 always for a readable log (advisory tool, MCP PASS contract).
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
