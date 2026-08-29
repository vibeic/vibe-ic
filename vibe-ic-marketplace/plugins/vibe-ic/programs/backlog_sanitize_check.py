#!/usr/bin/env python3
"""
backlog_sanitize_check.py — Organic Plugin gate: verify that a community
backlog submission is IC-agnostic and contains no vendor/confidential data.

General pattern:

    Vibe-IC is an Organic Plugin — community agents contribute backlogs
    that describe general capability gaps.  Every submission MUST be
    IC-agnostic: no chip names, vendor names, proprietary protocol
    details, confidential OTP content, or tester-specific command bytes.

    This gate scans all text fields of a YAML backlog file against a
    catalogue of HARD (reject) and SOFT (warn) patterns, reusing the
    same rule set as ``practical_notes_specificity_check.py``.

THE SECOND QUESTION THIS PROGRAM OWNS (vibe-ic#794): IS THE ITEM IN GIT?
=======================================================================
Thirteen ORGANIC backlog items were written into
``vibe-ic-marketplace/community/backlogs/`` between 2026-06-14 and 2026-07-12
and never committed. Twenty-five of their siblings in the same directory WERE
tracked, so the directory held two populations that were indistinguishable in
``ls``: one that had entered the process and one that had not.

The write path is prose. ``skills/community-backlog-submit/SKILL.md`` Step 3
says "create a file in ``community/backlogs/``"; Step 4 sanitizes it; Step 5
optionally opens a GitHub issue. **No step commits it, and no gate ever asked.**
A rule that depends on an agent remembering to `git add` is not a rule, and the
loss is silent: a reader opening the directory cannot tell a live backlog item
from a dropped one, and a fresh clone simply does not receive the dropped ones.

``--audit tracked`` is that missing predicate, in the program that already owns
this directory. A backlog YAML present on disk but unknown to git — untracked,
or hidden behind a ``.gitignore`` — is reported as an ERROR naming the file.

WHY A PREDICATE HERE RATHER THAN AN AUTO-COMMIT. Committing from the write path
is not available: the filing agent is frequently a benchmark-agent, which
``agent_checkin_scope_guard`` forbids from checking in to this zone at all, and
a program that commits on the author's behalf would put results and process
records into whatever commit happened to be open. Failing loudly AT WRITE TIME
is wrong for the opposite reason — at the moment the file is written, being
untracked is CORRECT. What was missing is the third option: an observation
made later, by a gate that runs on every landing.

WHY IT IS A SEPARATE ``--audit`` LANE AND NOT FOLDED INTO THE CONTENT VERDICT.
Measured 2026-08-04 on this repo's own 25 tracked items, the CONTENT audit
returns rc 1 with 18 ERROR findings (7 MISSING_FIELD, 6 INVALID_COMPONENT,
5 INVALID_TYPE) — a legacy pile that predates this change. Wiring the combined
verdict would make the gate red on day one, which is how a gate becomes
something people route around. The two questions therefore keep separate exit
lanes: ``--audit content`` (the default, unchanged) and ``--audit tracked``
(green today, and blocking from its first run).

Usage:
    python3 backlog_sanitize_check.py --file <backlog.yaml> [--json <report.json>]
    python3 backlog_sanitize_check.py --dir <backlogs_dir> [--json <report.json>]
    python3 backlog_sanitize_check.py --dir <backlogs_dir> --audit tracked

Exit: 0 = PASS (clean), 1 = FAIL (specificity violations found), 2 = IO error
      or REFUSED (trackedness could not be determined / nothing to certify).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

try:  # config-driven NDA-token source (detector reconstructs SKU from encoded form)
    import _commercial_pdk as _cpdk
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _commercial_pdk as _cpdk

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    field: str = ""
    line: int = 0
    matched: str = ""



# ---------------------------------------------------------------------------
# The NDA codename rule is only a RULE when there are literals to build it from
# ---------------------------------------------------------------------------
# `_commercial_pdk` RAISES `NoNdaLiterals` rather than return an alternation of
# nothing, because that alternation matches every line. Its own docstring states
# the consequence and the obligation:
#
#     "the empty set is the ORDINARY state of every public checkout and of every
#      CI job that has not been given the tokens. Every caller must handle this
#      raise, and `nda_literals_available()` is the cheap way to ask first."
#
# This caller did not handle it, and the call sits inside a module-level rule
# table — so the raise escaped at IMPORT, before argparse, before `--help`, and
# before any subject was opened. MEASURED 2026-08-30 on a gf180mcuD benchmark
# run with no token store configured: rc 1 with a bare traceback on stdout, and
# `flow_compliance_check` records an rc-1 gate by its FIRST OUTPUT LINE — so the
# design's completion audit carried
#     {"name": "backlog_sanitize_check", "verdict": "FAIL",
#      "message": "Traceback (most recent call last):"}
# and Phase 2 failed. A crash in this gate was rendered as a defect in the
# design under test, which is the one thing a gate must never do.
#
# rc 2 is this program's existing "cannot answer" channel (see the other
# `return 2` paths below), and `flow_compliance_check` already routes rc 2 to
# NOT_INVOCABLE / SKIP with the callee's own reason line rather than to a
# verdict. The same disposition `nda_diff_scan_check.py` and
# `source_chip_agnostic_check.py` already reached for this identical raise.
try:
    _NDA_CODENAME_PATTERN: Optional[str] = _cpdk.nda_source_regex_str()
    _NDA_UNAVAILABLE: str = ""
except _cpdk.NoNdaLiterals as _exc:                       # pragma: no cover
    _NDA_CODENAME_PATTERN = None
    _NDA_UNAVAILABLE = str(_exc)


HARD_RULES: List[Tuple[str, str, str]] = [
    # A genuinely sensitive internal project codename is NOT hard-coded in this
    # alternation as a literal (that would be the leak); its real value(s) come
    # from the PRIVATE config and are appended as codename rules at load time
    # (see the `HARD_RULES +=` extension below). The names kept here are public
    # commercial chip/IC part numbers used to teach chip-AGNOSTIC description.
    ("chip_name",
     r"\bAS3616\b|\bSC16IS750\b|\bLM75\b|\bDS1307\b"
     r"|\bPCA9685\b|\bTCA9534\b|\bMCP4725\b|\b24LC256\b|\bBME280\b",
     "Chip/IC product name — describe the IC class instead"),
    ("vendor_name",
     r"\bApple\b|\bMaxim\b|\bTexas Instruments\b|\bAnalog Devices\b"
     r"|\bMicrochip\b|\bNXP\b|\bSTMicro\b|\bInfineon\b|\bBosch\b",
     "Vendor company name — describe the protocol or IC class instead"),
    ("vendor_product",
     r"\bLightning\b|\bThunderbolt\b|\bMFi\b",
     "Vendor product/certification name"),
    ("tester_sku",
     r"MD[-_ ]?905\b|\bDE10[-_ ]?Lite\b|\bKeysight\b",
     "Test equipment SKU — describe the test methodology instead"),
    ("otp_content",
     r"(?:0x[0-9A-Fa-f]{2}\s*,?\s*){8,}",
     "Raw OTP/hex dump (≥8 bytes) — likely confidential content"),
    ("vendor_pdf",
     r"\b[A-Z][A-Za-z0-9_-]*\.(pdf|PDF)\b",
     "Vendor document filename — describe the information, not the source"),
    ("hid_cmd_byte",
     r"0x[0-9A-Fa-f]{2}\s*(?://|#)?\s*CMD_[A-Z_]+",
     "Hard-coded tester command byte — describe the test action instead"),
    ("pass_marker",
     r"\bbyte\s*\[\s*\d+\s*\]\s*=\s*0x[0-9A-Fa-f]+\b",
     "Tester-specific PASS/FAIL byte marker"),
    ("project_version",
     r"\bv0[5-9]\d\b(?!\.\d)",
     "Project iteration codename (v052/v068/...) — use 'prior version' instead"),
    ("chip_pin_name",
     r"\bACC_ID\b|\bPIN_V[0-9]+\b|\bPIN_W[0-9]+\b",
     "Chip-specific pin name"),
    ("register_address",
     r"\b(?:reg|register)\s*(?:0x[0-9A-Fa-f]{1,4}|addr\s*=\s*0x[0-9A-Fa-f]{1,4})",
     "Specific register address from a proprietary register map"),
    ("dated_validation",
     r"validated.*\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}\s+(MD-?905|DE10)",
     "Dated test-rig validation stamp"),
    ("file_path_leak",
     r"/home/\w+/|/Users/\w+/|C:\\Users\\",
     "Local file path leaks user/project structure"),
]


# NDA PDK/process codename family — pattern reconstructed at runtime from the
# encoded token store so no SKU literal lives in this detector's source. Appended
# rather than inlined above so an EMPTY token store leaves the other rules
# standing instead of killing the import (see `_NDA_CODENAME_PATTERN`).
if _NDA_CODENAME_PATTERN is not None:
    HARD_RULES.append((
        "pdk_codename",
        _NDA_CODENAME_PATTERN,
        "PDK/process codename specific to one project",
    ))



def _nda_rule_unmeasured(findings_present: bool) -> bool:
    """Should this run answer NOT_MEASURED because the codename rule was absent?

    Only when the run is otherwise CLEAN. A rule that never ran cannot weaken a
    POSITIVE finding — a violation the other rules caught is a real measurement
    and keeps its rc-1 verdict. What it does weaken is the negative: "I found
    nothing" over a catalogue missing one detector is not the same claim as "I
    found nothing" over the whole catalogue, and the two must not print the same
    thing. `source_chip_agnostic_check` states the rule this follows: "I have
    nothing to match with" must never print what "I matched and found nothing"
    prints.
    """
    return _NDA_CODENAME_PATTERN is None and not findings_present


def _print_nda_unmeasured(gate: str, rule_id: str) -> None:
    print(f"NOT_MEASURED: {gate}: rule {rule_id!r} could not be built: "
          f"{_NDA_UNAVAILABLE} Every other rule in the catalogue ran and found "
          f"nothing, but this run is NOT a complete clean bill of health. "
          f"Configure VIBEIC_NDA_TOKENS (a JSON object {{role: literal}}) or "
          f"the private config's 'nda_tokens' key on the host that runs this "
          f"gate.", file=sys.stderr)


# PRIVATE-config project codenames: the REAL sensitive codename(s) are not
# stored as a literal above (that would be the leak) — they come from
# `_commercial_pdk.project_codenames()` (empty in public / default) and are
# appended as HARD rules at load time, so a submission naming the true codename
# is still sanitized on a configured host without shipping the literal.
for _cn in _cpdk.project_codenames():
    HARD_RULES.append((
        "chip_name",
        rf"\b{re.escape(_cn)}\b",
        "Project codename — describe the IC class / benchmark instead",
    ))

SOFT_RULES: List[Tuple[str, str, str]] = [
    ("provenance_chip",
     r"(real bug|known incident|observed in|debug session)\s+"
     r"(from|of|on)\s+\w+",
     "Provenance line may reference a specific chip — verify it's generalized"),
    ("specific_timing",
     r"\b\d+\s*[uµn]s\b",
     "Specific timing value — ensure it describes a general constraint, not one IC's spec"),
    ("specific_frequency",
     r"\b\d+(\.\d+)?\s*(MHz|kHz|GHz)\b",
     "Specific frequency — ensure it's a general protocol requirement, not one IC's clock"),
]

# --- OSS-core codename SOFT registry (general-not-keyword doctrine) ---------
#
# Open-source IP-core codenames (picorv32, ibex, serv, ...) are LEGITIMATE in
# most places: ip_catalog_* programs reuse OSS IP, and a backlog's
# session_context / pattern / suggested_fix legitimately records WHICH design
# was run or lists a corpus by name.  The one place a codename should NOT
# stand in for a generic description is the backlog's one-line ``title`` — the
# generic gap summary, which must describe the IC CLASS ("a bit-serial RISC-V
# core"), not a specific core ("serv").
#
# So this is a SOFT (WARN) rule, scoped to the generic-description field set
# below, keyed on a MAINTAINED DATA FILE (oss_core_registry.json), NOT a regex
# literal baked into the detector.
OSS_REGISTRY_PATH = Path(__file__).resolve().parent / "oss_core_registry.json"

# Fields where a codename should describe the IC class generically.  Scoped to
# ``title`` only: ``pattern`` / ``suggested_fix`` legitimately carry a codename
# as provenance ("catalog-glue-author pulls cpu/serv@1.4.0") or as a corpus
# list ("subservient → darkriscv → picorv32 → …"), and ``session_context``
# records what was actually run, so neither is flagged.
OSS_GENERIC_DESC_FIELDS = ("title",)


def _load_oss_cores(path: Path = OSS_REGISTRY_PATH) -> List[str]:
    """Load the curated OSS-core codename registry. Missing/garbage => []
    (honest skip — the rule simply does not fire), never a fabricated list."""
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return []
    cores = data.get("cores", [])
    if not isinstance(cores, list):
        return []
    return [c for c in cores if isinstance(c, str) and c.strip()]


def _build_oss_pattern(cores: List[str]) -> str:
    """Whole-word, case-insensitive alternation over the registry tokens.
    Returns '' when the registry is empty so the caller skips the rule."""
    if not cores:
        return ""
    alts = "|".join(re.escape(c) for c in sorted(set(cores), key=len, reverse=True))
    return r"\b(?:" + alts + r")\b"


_OSS_CORES = _load_oss_cores()
_OSS_PATTERN = _build_oss_pattern(_OSS_CORES)

REQUIRED_FIELDS = ["type", "component", "title", "pattern", "plugin_version"]


def _shipped_plugin_version() -> str:
    """The version `.claude-plugin/plugin.json` actually declares, or "".

    Returns "" when it cannot be read — an unreadable manifest must not
    manufacture a MISMATCH against a record that may be perfectly correct.
    Unknown is not disagreement."""
    import json as _json
    here = Path(__file__).resolve().parent
    for base in (here.parent, here.parent.parent):
        mf = base / ".claude-plugin" / "plugin.json"
        if mf.is_file():
            try:
                return str(_json.loads(mf.read_text()).get("version", "")).strip()
            except (OSError, ValueError):
                return ""
    return ""
VALID_TYPES = {"bug", "issue", "enhancement"}
COMPONENT_RE = re.compile(
    r"^(skill|program|mcp|flow):[\w_-]+$", re.IGNORECASE
)


def _parse_yaml(path: Path) -> Dict:
    text = path.read_text(errors="replace")
    if HAS_YAML:
        return yaml.safe_load(text) or {}
    result = {}
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' in line:
            key, _, val = line.partition(':')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val and not val.startswith('|') and not val.startswith('>'):
                result[key] = val
    if not result:
        result["_raw"] = text
    return result


def _check_text(text: str, fname: str, field: str) -> List[Finding]:
    findings = []
    for rule_id, pattern, desc in HARD_RULES:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            findings.append(Finding(
                "ERROR", rule_id, desc,
                file=fname, field=field, matched=m.group(),
            ))
    for rule_id, pattern, desc in SOFT_RULES:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            findings.append(Finding(
                "WARN", rule_id, desc,
                file=fname, field=field, matched=m.group(),
            ))
    # OSS-core codename SOFT rule — scoped to generic-description fields only.
    if _OSS_PATTERN and field in OSS_GENERIC_DESC_FIELDS:
        for m in re.finditer(_OSS_PATTERN, text, re.IGNORECASE):
            findings.append(Finding(
                "WARN", "oss_core_codename",
                "Open-source-core codename in the generic-description "
                f"'{field}' — describe the IC class instead "
                "(e.g. 'a bit-serial RISC-V core', not the core's name)",
                file=fname, field=field, matched=m.group(),
            ))
    return findings


def _check_structure(data: Dict, fname: str) -> List[Finding]:
    findings = []
    for field in REQUIRED_FIELDS:
        val = data.get(field, "")
        if not val or val == '""' or val.startswith("<"):
            findings.append(Finding(
                "ERROR", "MISSING_FIELD",
                f"Required field '{field}' is missing or empty",
                file=fname, field=field,
            ))

    # plugin_version must MATCH the shipped release, not merely be filled in.
    #
    # MEASURED (#835): the field was validated as "present and non-empty" and
    # nothing read `plugin.json` to compare. A record hand-written against one
    # release stays green after a rebase onto a main that has bumped — it then
    # asserts a release it was never written against, and every check still
    # passes. A field nobody compares is a field that decays silently, which is
    # exactly the shape this checker exists to catch elsewhere.
    declared = str(data.get("plugin_version", "")).strip().strip('"')
    shipped = _shipped_plugin_version()
    if declared and shipped and declared != shipped:
        findings.append(Finding(
            "ERROR", "PLUGIN_VERSION_MISMATCH",
            f"plugin_version says '{declared}' but the shipped plugin.json "
            f"says '{shipped}' — the record asserts a release it was not "
            f"written against",
            file=fname, field="plugin_version",
        ))

    btype = data.get("type", "")
    if btype and btype not in VALID_TYPES:
        findings.append(Finding(
            "ERROR", "INVALID_TYPE",
            f"type must be one of {VALID_TYPES}, got '{btype}'",
            file=fname, field="type",
        ))

    component = data.get("component", "")
    if component and not COMPONENT_RE.match(component):
        findings.append(Finding(
            "ERROR", "INVALID_COMPONENT",
            f"component must match 'skill:<name>' | 'program:<name>' | "
            f"'mcp:<tool>' | 'flow:<step>', got '{component}'",
            file=fname, field="component",
        ))

    return findings


def audit_file(path: Path) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []
    fname = str(path)

    try:
        data = _parse_yaml(path)
    except Exception as e:
        findings.append(Finding(
            "ERROR", "PARSE_ERROR", f"Cannot parse YAML: {e}", file=fname
        ))
        return findings, {}

    findings.extend(_check_structure(data, fname))

    text_fields = ["title", "pattern", "suggested_fix",
                    "steps_to_reproduce", "gate_output",
                    "session_context", "_raw"]
    for field in text_fields:
        val = data.get(field, "")
        if isinstance(val, str) and val:
            findings.extend(_check_text(val, fname, field))

    return findings, {
        "file": fname,
        "type": data.get("type", ""),
        "component": data.get("component", ""),
        "title": data.get("title", ""),
    }


# ---------------------------------------------------------------------------
# TRACKEDNESS AUDIT (vibe-ic#794)
# ---------------------------------------------------------------------------
# The population is EXACTLY the one the content audit already walks — the
# `*.yaml` / `*.yml` files in the scanned directory. Producer and consumer
# disagreeing about which file set they mean is the same defect one level up,
# so the tracked audit is handed the paths the caller already resolved rather
# than re-globbing them with a second, drifting rule.

#: A backlog file git does not know about. ERROR, because a fresh clone never
#: receives it and every consumer of the directory is therefore reading a
#: different set than the author wrote.
CAT_UNTRACKED = "UNTRACKED_BACKLOG"
#: Worse than untracked: `git add` would silently refuse it. Reported apart so
#: the remedy differs (`git add -f`, or delete the ignore rule).
CAT_IGNORED = "IGNORED_BACKLOG"


def _git(dirpath: Path, *args: str) -> Optional[subprocess.CompletedProcess]:
    """Run git, or None if git itself could not be executed.

    A missing/unexecutable `git` is a THIRD outcome, distinct from "git said
    no": it must not surface as a traceback (rc 1 reads as "found a defect")
    and must not surface as an empty tracked set (which would report every
    file on disk as lost). Both would be a verdict this program has not
    earned; the caller turns None into the same REFUSAL as a non-repo tree.
    """
    try:
        return subprocess.run(["git", "-C", str(dirpath), *args],
                              capture_output=True, text=True)
    except OSError:
        return None


def _git_tracked_names(dirpath: Path) -> Optional[List[str]]:
    """Names git TRACKS directly in `dirpath`, or None when it cannot answer.

    None means "not inside a git work tree" — never an empty set. A checker
    that cannot see the population must not speak for it: the caller turns
    None into a REFUSAL (rc 2), not into a clean pass.
    """
    r = _git(dirpath, "ls-files", "-z", "--", ".")
    if r is None or r.returncode != 0:
        return None
    return [n for n in (r.stdout or "").split("\0") if n]


def _git_ignored_names(dirpath: Path, names: List[str]) -> List[str]:
    """Subset of `names` that a .gitignore rule excludes."""
    if not names:
        return []
    # `check-ignore` exits 1 when nothing matched — a normal answer, not an
    # error; only rc >= 2 is a real failure and is reported as "none known".
    try:
        proc = subprocess.run(["git", "-C", str(dirpath), "check-ignore", "-z",
                               "--stdin"],
                              input="\0".join(names),
                              capture_output=True, text=True)
    except OSError:
        return []
    if proc.returncode >= 2:
        return []
    return [n for n in (proc.stdout or "").split("\0") if n]


def audit_tracked(dirpath: Path,
                  paths: List[Path]) -> Tuple[Optional[List[Finding]], Dict]:
    """Every backlog file on disk must be one git knows about.

    Returns (findings, summary). `findings is None` means REFUSED — the
    directory is not inside a git work tree, so trackedness is unanswerable
    here and the caller must exit 2 rather than report a pass.
    """
    tracked = _git_tracked_names(dirpath)
    if tracked is None:
        return None, {
            "audit": "tracked",
            "dir": str(dirpath),
            "refused": ("not inside a git work tree — trackedness is "
                        "unanswerable here"),
            "on_disk": len(paths),
        }

    tracked_set = set(tracked)
    on_disk = [p.name for p in paths]
    missing = [n for n in on_disk if n not in tracked_set]
    ignored = set(_git_ignored_names(dirpath, missing))

    findings: List[Finding] = []
    for name in missing:
        is_ignored = name in ignored
        findings.append(Finding(
            "ERROR",
            CAT_IGNORED if is_ignored else CAT_UNTRACKED,
            (f"backlog file is present on disk but "
             + ("EXCLUDED by a .gitignore rule" if is_ignored
                else "NOT TRACKED by git")
             + " — a fresh clone never receives it, so it is invisible to "
               "every consumer of this directory. Commit it (or delete it "
               "if it was abandoned); leaving it on disk is what makes a "
               "dropped item indistinguishable from a live one."),
            file=str(dirpath / name),
            field="",
        ))

    return findings, {
        "audit": "tracked",
        "dir": str(dirpath),
        # The denominator, always printed — a run that examined nothing must
        # not read the same as a run that examined everything and found it
        # clean (`gate_discloses_denominator_check`).
        "on_disk": len(on_disk),
        "tracked": len([n for n in on_disk if n in tracked_set]),
        "untracked": sorted(n for n in missing if n not in ignored),
        "ignored": sorted(ignored),
    }


def audit(paths: List[Path]) -> Tuple[List[Finding], Dict]:
    all_findings: List[Finding] = []
    summaries = []

    for p in paths:
        findings, summary = audit_file(p)
        all_findings.extend(findings)
        summaries.append(summary)

    return all_findings, {
        "files_checked": len(paths),
        "files": summaries,
        "hard_violations": sum(1 for f in all_findings if f.severity == "ERROR"),
        "soft_warnings": sum(1 for f in all_findings if f.severity == "WARN"),
    }


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify community backlog submissions are IC-agnostic "
                    "and contain no vendor/confidential data."
    )
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--file", dest="file_path", help="Single YAML backlog file")
    grp.add_argument("--dir", dest="dir_path", help="Directory of YAML backlog files")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="Treat SOFT warnings as errors")
    ap.add_argument("--audit", choices=("content", "tracked", "both"),
                    default="content",
                    help="content (default) = the IC-agnostic text scan; "
                         "tracked = every backlog file on disk must be known "
                         "to git (vibe-ic#794); both = run the two together")
    args = ap.parse_args(argv)

    paths: List[Path] = []
    if args.file_path:
        p = Path(args.file_path)
        if not p.exists():
            print(f"ERROR: file not found: {p}", file=sys.stderr)
            return 2
        paths = [p]
        base_dir = p.parent
    else:
        d = Path(args.dir_path)
        if not d.exists():
            print(f"ERROR: directory not found: {d}", file=sys.stderr)
            return 2
        base_dir = d
        paths = sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml"))
        if not paths:
            if args.audit != "content":
                # A zero population is not a clean tracked-audit: the whole
                # point is that this directory holds records, and one that
                # holds none certifies nothing. REFUSE rather than pass.
                print("REFUSED: 0 backlog file(s) on disk in "
                      f"{d} — nothing to certify as tracked", file=sys.stderr)
                print(json.dumps({"program": "backlog_sanitize_check",
                                  "summary": {"pass": False, "refused": True,
                                              "audit": args.audit,
                                              "files_checked": 0}}))
                return 2
            print(json.dumps({"program": "backlog_sanitize_check",
                              "summary": {"pass": True, "files_checked": 0,
                                          "note": "no YAML files found"}}))
            return 0

    findings: List[Finding] = []
    summary: Dict = {"files_checked": len(paths), "audit": args.audit}

    if args.audit in ("content", "both"):
        try:
            c_findings, c_summary = audit(paths)
        except OSError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        findings.extend(c_findings)
        summary.update(c_summary)

    if args.audit in ("tracked", "both"):
        t_findings, t_summary = audit_tracked(base_dir, paths)
        summary["tracked_audit"] = t_summary
        if t_findings is None:
            print(f"REFUSED: {t_summary['refused']}: {base_dir} "
                  f"({t_summary['on_disk']} backlog file(s) on disk)",
                  file=sys.stderr)
            print(json.dumps({"program": "backlog_sanitize_check",
                              "summary": {"pass": False, "refused": True,
                                          **summary}}))
            return 2
        findings.extend(t_findings)
        # The denominator, on every run, pass or fail. stderr so a caller
        # parsing stdout as JSON is unaffected.
        print(f"backlog trackedness: {t_summary['on_disk']} backlog file(s) "
              f"examined in {base_dir}, {t_summary['tracked']} tracked, "
              f"{len(t_summary['untracked'])} untracked, "
              f"{len(t_summary['ignored'])} git-ignored", file=sys.stderr)

    if args.strict:
        is_pass = len(findings) == 0
    else:
        is_pass = not any(f.severity == "ERROR" for f in findings)

    report = {
        "program": "backlog_sanitize_check",
        "version": "1.2.0",
        # A consumer of this JSON must not have to infer "the whole catalogue
        # ran" from the absence of a field (vibe-ic#1476's lesson, same shape).
        "nda_codename_rule": (
            "applied" if _NDA_CODENAME_PATTERN is not None else "NOT_MEASURED"),
        "summary": {"pass": is_pass, "findings_count": len(findings), **summary},
        "findings": [asdict(f) for f in findings],
    }
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json_out), out)
    print(out)
    if _nda_rule_unmeasured(bool(findings)):
        _print_nda_unmeasured("backlog_sanitize_check", "pdk_codename")
        return 2
    return 0 if is_pass else 1


if __name__ == "__main__":
    sys.exit(main())
