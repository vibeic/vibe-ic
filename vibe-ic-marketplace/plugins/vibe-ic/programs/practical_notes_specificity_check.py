#!/usr/bin/env python3
"""
practical_notes_specificity_check.py — meta-gate for plugin docs.

Vibe-IC's `feedback_general_not_specific` rule is non-negotiable: every
skill (and every PRACTICAL_NOTES.md) must work for ANY IC. References to
a single benchmark chip — the <chip-class> / <benchmark> / <half-duplex-tester> stack we used to
discover bugs — are evidence, not rules. Hard-coded vendor command bytes,
specific opcodes, dated test rigs, or vendor product names defeat the
generality and bias future agents toward one IC class.

This gate scans PRACTICAL_NOTES.md (and optionally SKILL.md) for two
classes of issue:

  HARD  — chip names, vendor products, dated test setups, hard-coded
          tester command bytes, vendor doc filenames, specific timing
          numbers presented as "the value to use" rather than as a
          parameter symbol. ALWAYS exits 1 (FAIL).

  SOFT  — provenance lines such as "Real bug from <chip-class> debug" or
          "from <half-duplex-tester> 2026-04-25 session". The rule itself may be
          general but the chip name in the prose biases the reader.
          Default: WARN. With --strict: ERROR.

Allowlist: any line containing the marker
    <!-- specificity-allow: <reason> -->
is exempted (use sparingly; the reason is logged).

Usage
-----
    practical_notes_specificity_check.py [--paths <glob>] [--strict] [--json]

By default scans PRACTICAL_NOTES.md under
    vibe-ic-marketplace/plugins/vibe-ic/skills/*/

Exit codes
----------
    0 = pass (no HARD; no SOFT in --strict)
    1 = fail (≥1 HARD; or ≥1 SOFT in --strict)
    2 = io / argument error

Rule enforced
-------------
Plugin docs must work for ANY IC. Concretely:

  * No vendor product names (Lightning, Apple).
  * No specific chip names (<chip-class>, <benchmark>, <pdk-codename>, <PDK>).
  * No tester product names (<half-duplex-tester>) or dated test-rig validation.
  * No hard-coded vendor HID command bytes (`0x10 CMD_CONNECT_CHK`),
    PASS markers (`byte[6]=0xF2`), or chip pin labels (ACC_ID).
  * Provenance lines (`Real bug from <chip> debug …`) restate as
    `Observed pattern …` / `Known failure mode …`.

Generic pattern
---------------
Use parameter symbols, not literal numbers; describe the protocol class
("single-wire pulse-width-modulated bus"), not the SKU; cite incident
counts, not vendor sessions.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

try:  # config-driven NDA-token source (detector reconstructs SKU from encoded form)
    import _commercial_pdk as _cpdk
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _commercial_pdk as _cpdk


PLUGIN_ROOT = Path(__file__).resolve().parents[1]   # vibe-ic
CORE_SKILLS = PLUGIN_ROOT / "skills"

ALLOW_MARKER = "<!-- specificity-allow"


# ---------------------------------------------------------------------------
# Rule catalogue
# ---------------------------------------------------------------------------
# Each rule = (id, severity, regex, description)
# regex matches a substring on a line; the file/line is reported.
HARD_RULES: list[tuple[str, str, str]] = [
    ("chip_name_as3616", r"\bAS3616\b",
     "Hard-coded benchmark chip name <chip-class>"),
    # A genuinely sensitive internal project codename is NOT hard-coded here as
    # a literal (that would be the leak). Its real value(s) come from the
    # PRIVATE config and are turned into `project_codename_<value>` rules at
    # runtime by `_deny_list_codename_rules()` below.
    ("tester_md905", r"MD[-_ ]?905\b",
     "Tester product name <half-duplex-tester> — describe protocol, not a SKU"),
    ("vendor_product_lightning", r"\bLightning\b",
     "Vendor product name 'Lightning' (Apple) — describe the protocol class instead"),
    ("vendor_product_apple", r"\bApple\b",
     "Vendor name 'Apple'"),
    ("specific_otp_file", r"\bapple\.ver\b",
     "OTP filename apple.ver is benchmark-specific"),
    # The NDA PDK/process codename family is NOT built here — it is resolved
    # below, guarded, because the resolver raises on a host without the private
    # token store and a raise inside this literal kills the module at import.
    ("vendor_pdf_filename",
     r"\b[A-Z][A-Za-z0-9_-]*訊號格式\.pdf\b"
     r"|\b[A-Z][A-Za-z0-9_-]*_TxRx[^\s]*\.pdf\b"
     r"|\b(AS|SN|HP)[0-9]{3,5}[A-Za-z_-]*\.pdf\b",
     "Vendor datasheet filename (chip-prefixed .pdf)"),
    ("dated_validation", r"validated.*\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}\s+(MD-?905|DE10)",
     "Dated test-rig validation — couples doc to one calibration moment"),
    ("hid_cmd_byte_decl", r"0x[0-9A-Fa-f]{2}\s*(?://|#)?\s*CMD_[A-Z_]+",
     "Hard-coded vendor HID command byte (e.g., `0x10 CMD_CONNECT_CHK`) — tester-specific"),
    ("specific_pass_marker", r"\bbyte\s*\[\s*6\s*\]\s*=\s*0x?F2\b|\bF2\s*=\s*PASS\b",
     "<half-duplex-tester>-specific PASS byte marker"),
    ("project_version_codename", r"\bv0[5-9]\d\b(?!\.\d)",
     "Project iteration codename (v052/v068/...) leaks into general docs"),
    ("chip_specific_pin", r"\bACC_ID\b|\bPIN_V[0-9]+\b|\bPIN_W[0-9]+\b",
     "Chip-specific pin name (ACC_ID is <chip-class>'s ID-bus pin)"),
]


# ---------------------------------------------------------------------------
# Deny-list-derived project-codename rules.
#
# The hand-curated HARD_RULES above only spell out the codenames known at
# authoring time. chip_deny_list.txt is the canonical, growing
# registry of benchmark project/chip codenames; rather than re-typing each new
# token into HARD_RULES, derive a `project_codename_<token>` rule for every
# codename-shaped token in the deny list. chip-AGNOSTIC: this is a registry
# scan, not a hardcode — adding a token to the deny list automatically gates
# its leakage into general docs.
# ---------------------------------------------------------------------------
# The canonical deny list lives under programs/tests/ (next to this program),
# NOT PLUGIN_ROOT/tests/. (Fixed alongside the private-codename scrub: the old
# PLUGIN_ROOT/"tests" path never existed, so the deny-list-derived rules were
# silently dead — the private-config codename rules below now always run too.)
_DENY_LIST_PATH = Path(__file__).resolve().parent / "tests" / "chip_deny_list.txt"
# Codename shape: a few leading letters then a 3+ digit run (optional trailing
# letters). Mirrors the test's _CODENAME_TOKEN_RE so the two stay in lock-step.
_CODENAME_TOKEN_RE = re.compile(r"^[a-z]{2,5}\d{3,}[a-z]*$")


def _deny_list_codename_rules() -> list[tuple[str, str, str]]:
    rules: list[tuple[str, str, str]] = []
    try:
        raw = _DENY_LIST_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        raw = []   # deny list missing -> still emit the private-config rules below
    seen: set[str] = set()
    for ln in raw:
        s = ln.strip()
        if not s or s.startswith("#") or s in seen:
            continue
        seen.add(s)
        if "-" in s:
            continue
        if _CODENAME_TOKEN_RE.match(s):
            rid = f"project_codename_{s}"
            # Skip if the hand-curated catalogue already covers this exact id.
            if any(existing_rid == rid for existing_rid, _, _ in HARD_RULES):
                continue
            rules.append((
                rid,
                rf"\b{re.escape(s)}\b",
                f"Project/chip codename {s.upper()!r} (deny list) leaks "
                f"into general-purpose docs",
            ))
    # PRIVATE-config codenames: the real sensitive value(s) are NOT in the deny
    # list as a literal — they come from `_commercial_pdk.project_codenames()`
    # (empty in public). On a configured host each becomes a rule so the real
    # codename is still flagged in general docs, without shipping the literal.
    for cn in _cpdk.project_codenames():
        rid = f"project_codename_{cn.lower()}"
        if any(existing_rid == rid for existing_rid, _, _ in HARD_RULES) \
                or any(existing_rid == rid for existing_rid, _, _ in rules):
            continue
        rules.append((
            rid,
            rf"\b{re.escape(cn)}\b",
            f"Project codename {cn.upper()!r} (private config) leaks into "
            f"general-purpose docs",
        ))
    return rules


HARD_RULES.extend(_deny_list_codename_rules())

# ---------------------------------------------------------------------------
# THE NDA CODENAME RULE, RESOLVED WITHOUT DYING AT IMPORT.
#
# `_cpdk.nda_source_regex_str()` RAISES `NoNdaLiterals` on any host whose
# private config carries no `nda_tokens`. Since the token store moved out of
# tracked source that is not an edge case — the raise's own docstring says it is
# "the ORDINARY state of every public checkout and of every CI job that has not
# been given the tokens", and it ends "A caller must report NOT_MEASURED."
#
# Calling it inside the rule-table literal made the raise escape at IMPORT, so
# the process died before argparse ran and even `--help` exited 1. rc 1 is a
# MEASURED verdict: `flow_compliance_check` maps it to a gate FAIL. A host that
# merely lacks OPTIONAL config therefore produced a confident, specific failure
# about the subject — the same defect class the resolver was rewritten to
# prevent, arriving through the caller instead of the pattern.
#
# MEASURED 2026-08-30, gf180mcuD/spm through the one-shot runner at v1.12.80:
# this gate and `backlog_sanitize_check` were the ONLY two of the P0 umbrella's
# 246 structural checkers to FAIL. They took `Overall: PASS_WITH_WAIVERS` to
# `Overall: FAIL`, Phase 2 to FAIL, and Phase 3 to SKIPPED — the design never
# reached place-and-route. With `VIBEIC_NDA_TOKENS` set, both gates instead exit
# 2 at argparse and the run proceeds, so the blocker is the absence of optional
# config and nothing about the design.
#
# rc 2 / NOT_MEASURED is the channel `source_chip_agnostic_check`,
# `nda_diff_scan_check` and `commit_msg_nda_check` already use for this exact
# raise. This file is named in the resolver's own list of callers that must
# recognise the tokens; it was not converted with them.
# ---------------------------------------------------------------------------
NDA_TOKENS_MISSING: str = ""
try:
    _NDA_CODENAME_RULES: list[tuple[str, str, str]] = [
        ("specific_pdk_codename", _cpdk.nda_source_regex_str(),
         "PDK / process codename specific to one project"),
    ]
except _cpdk.NoNdaLiterals as _nda_exc:            # noqa: F841 - reported below
    _NDA_CODENAME_RULES = []
    NDA_TOKENS_MISSING = str(_nda_exc)

HARD_RULES.extend(_NDA_CODENAME_RULES)

SOFT_RULES: list[tuple[str, str, str]] = [
    ("provenance_chip_in_prose",
     r"(real bug|known incident|observed in|debug session|session log)\s+(from|of|on)\s+(<chip-class>|<benchmark>|v0[5-9]\d|MD-?905)",
     "Provenance line names a specific chip — restate as 'observed pattern' or 'known failure mode'"),
    ("from_chip_debug",
     r"\bfrom\s+(<chip-class>|<benchmark>|v0[5-9]\d)\s+(debug|fresh-agent|pilot|session)",
     "'from <chip> debug' provenance"),
]


@dataclass
class Finding:
    file: str
    line: int
    severity: str   # ERROR / WARN
    rule: str
    detail: str
    snippet: str


def scan_file(path: Path, strict: bool) -> list[Finding]:
    out: list[Finding] = []
    try:
        text = path.read_text(errors="replace")
    except OSError as e:
        return [Finding(str(path), 0, "ERROR", "io_error", str(e), "")]
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for rid, pat, desc in HARD_RULES:
            if re.search(pat, line, re.IGNORECASE):
                out.append(Finding(
                    file=str(path), line=lineno, severity="ERROR",
                    rule=rid, detail=desc, snippet=line.strip()[:160]))
        for rid, pat, desc in SOFT_RULES:
            if re.search(pat, line, re.IGNORECASE):
                out.append(Finding(
                    file=str(path), line=lineno,
                    severity="ERROR" if strict else "WARN",
                    rule=rid, detail=desc, snippet=line.strip()[:160]))
    return out


def collect_paths(globs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for g in globs:
        if "*" in g or "?" in g:
            paths.extend(Path(".").glob(g))
        else:
            p = Path(g)
            if p.is_dir():
                paths.extend(p.rglob("PRACTICAL_NOTES.md"))
            elif p.exists():
                paths.append(p)
    return sorted(set(paths))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Audit PRACTICAL_NOTES.md for chip-specific content.")
    ap.add_argument(
        "--paths", nargs="*",
        help="Files / directories / globs to scan. Default: all "
             "PRACTICAL_NOTES.md under vibe-ic/skills/.")
    ap.add_argument("--strict", action="store_true",
                    help="Treat SOFT (provenance) findings as ERROR.")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON.")
    args = ap.parse_args()

    # The NDA codename rule could not be built on this host (see
    # NDA_TOKENS_MISSING above). Refuse on the NOT_MEASURED channel instead of
    # scanning with a rule table that is silently one rule short: "I have
    # nothing to match with" must never print what "I matched and found
    # nothing" prints, and it must never print what a real finding prints.
    if NDA_TOKENS_MISSING:
        print(f"NO_NDA_TOKENS: {NDA_TOKENS_MISSING} Configure "
              "VIBEIC_NDA_TOKENS (a JSON object {role: literal}) or the "
              "private config's 'nda_tokens' key on the host that runs this "
              "gate. This run is NOT a clean bill of health.", file=sys.stderr)
        return 2

    if args.paths:
        paths = collect_paths(args.paths)
    else:
        if not CORE_SKILLS.exists():
            print(f"error: skills directory not found: {CORE_SKILLS}",
                  file=sys.stderr)
            return 2
        paths = sorted(CORE_SKILLS.rglob("PRACTICAL_NOTES.md"))

    if not paths:
        print("error: no PRACTICAL_NOTES.md files matched", file=sys.stderr)
        return 2

    all_findings: list[Finding] = []
    for p in paths:
        all_findings.extend(scan_file(p, strict=args.strict))

    errors = [f for f in all_findings if f.severity == "ERROR"]
    warnings = [f for f in all_findings if f.severity == "WARN"]
    verdict = "FAIL" if errors else "PASS"

    if args.json:
        print(json.dumps({
            "files_scanned": len(paths),
            "total_errors": len(errors),
            "total_warnings": len(warnings),
            "findings": [asdict(f) for f in all_findings],
            "verdict": verdict,
        }, indent=2))
    else:
        # Group by file for readability
        by_file: dict[str, list[Finding]] = {}
        for f in all_findings:
            by_file.setdefault(f.file, []).append(f)
        for fpath, fs in sorted(by_file.items()):
            print(f"\n{fpath}")
            for f in fs:
                print(f"  [{f.severity}] line {f.line} :: {f.rule}")
                print(f"        {f.detail}")
                print(f"        > {f.snippet}")
        print()
        print(f"Files scanned : {len(paths)}")
        print(f"Errors        : {len(errors)}")
        print(f"Warnings      : {len(warnings)}")
        print(verdict)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
