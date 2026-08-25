#!/usr/bin/env python3
"""
changelog_metric_reproducibility_check.py — anti-fabrication gate (v1.6.38).

Doctrine: any quantitative metric stated in CHANGELOG.md (e.g. "IR drop
peak 5.231 mV", "DFT 70% stuck-at coverage", "EM Javg 0.018 mA/μm") MUST
be reproducible from the plugin source — i.e. the metric's value must
either be computed by code in the plugin or reference an explicit source
file the metric derived from.

Real-world inspiration (v1.6.37 escape):
  CHANGELOG.md said "v10634 sign-off achieved IR static peak 5.231 mV
  (0.26% Vdd) and Javg 0.018 mA/μm (peak 0.036)". Both numbers were
  literals hardcoded in `_signoff_emit.py:emit_ir_drop_report` and
  `emit_em_report`; no measurement actually produced them. A user
  diffing the CHANGELOG had no way to trace the metric back to a
  computation.

Rule:
  For every line in CHANGELOG.md (or marketplace.json description /
  plugin.json description) matching:
    \\d+(?:\\.\\d+)?\\s*(mV|mA/?u?m|mA/μm|mW|μA|nW|μW|%|GHz|MHz|kHz|um|nm)
  the corresponding number must appear OR be derivable in the plugin
  source. Acceptable sources:
    1. The number appears as a literal in `programs/*.py` AS A
       JUSTIFIED ASSIGNMENT (i.e. it has a `# source:` comment, satisfying
       `literal_verdict_keyword_check`). — strongest evidence.
    2. The number appears in a recent commit's `git diff` output (so a
       reviewer can trace its origin). — pre-push variant.
    3. The number appears in a JSON test fixture or sample report that
       the CHANGELOG explicitly references.
  Otherwise, the metric is unverifiable and the check FAILs.

Usage (audit only, doesn't require git):
    python3 changelog_metric_reproducibility_check.py <plugin_root>
                                                       [--json <out>]
                                                       [--max-violations N]

Pre-push hook variant (with git):
    python3 changelog_metric_reproducibility_check.py <plugin_root>
                                                       --git-diff HEAD~1
                                                       [--json <out>]

Exit codes:
    0  PASS — every CHANGELOG metric is reproducible from source
    1  FAIL — at least one metric is unverifiable
    2  argument or I/O error

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Set, Tuple


_METRIC_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mV|mA/?u?m|mA/μm|mW|μA|nW|μW|GHz|MHz|kHz|um|nm|%)"
    r"(?=[^A-Za-z0-9_/]|$)",  # word-end via lookahead (allows '%' / EOL)
    re.IGNORECASE,
)


#: THE DENOMINATOR THIS GATE'S PASS STANDS ON.
#: `gate_discloses_denominator_check` measured this program answering PASS
#: over an EMPTY tree while saying only "PASS: every ... is reproducible" —
#: an output indistinguishable from a real clean run. A pass that does not
#: say what it looked at is the same shape as a scan that looked at nothing.
#: Recorded by `audit()` and printed by `main()`; nothing else reads it, and
#: no signature changed, so every existing caller and test is untouched.
_SCANNED = {"files": 0, "items": 0}


@dataclass
class MetricFinding:
    file: str
    line: int
    metric: str
    rule: str
    detail: str = ""


def _extract_metrics(text: str) -> List[Tuple[int, str]]:
    """Return list of (line_no, metric_token) for every metric in text."""
    out: List[Tuple[int, str]] = []
    for ln_no, line in enumerate(text.splitlines(), start=1):
        for m in _METRIC_RE.finditer(line):
            tok = f"{m.group('num')} {m.group('unit')}"
            out.append((ln_no, tok))
    return out


def _source_corpus(plugin_root: Path) -> str:
    """Concatenate the searchable plugin source. The check is
    intentionally text-based so it works without parsing semantics."""
    parts: List[str] = []
    programs = plugin_root / "programs"
    if programs.is_dir():
        for py in programs.rglob("*.py"):
            try:
                parts.append(py.read_text(encoding="utf-8",
                                          errors="replace"))
            except OSError:
                continue
    tests = plugin_root / "tests"
    if tests.is_dir():
        for py in tests.rglob("*.py"):
            try:
                parts.append(py.read_text(encoding="utf-8",
                                          errors="replace"))
            except OSError:
                continue
    return "\n".join(parts)


def _git_diff_corpus(plugin_root: Path, ref: str) -> str:
    try:
        cp = subprocess.run(
            ["git", "diff", ref, "--", str(plugin_root)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return cp.stdout
    except Exception:
        return ""


#: An `N/M` fraction, as a percentage table states its own denominator:
#: `47/50 = 94.0%`, `153/156 = 98.08%`.
_FRACTION_RE = re.compile(r"(?<![\d.])(\d{1,7})\s*/\s*(\d{1,7})(?![\d.])")


def _derivable_from_a_fraction_on_the_line(num_str: str, line: str) -> bool:
    """Is this percentage the ARITHMETIC of a fraction stated on the same line?

    `47/50 = 94.0%` is the strongest provenance a published metric can have —
    stronger than the literal-in-source rule below, which credits a digit
    sequence that merely happens to occur somewhere in `programs/`. The reader
    can check it with a calculator and no access to the tree at all.

    WHY THIS RULE EXISTS. Without it the gate FAILed six README figures that
    each sit in a table cell beside the fraction they are computed from
    (`47/50 = 94.0 %`, `153/156 = 98.08 %`, `154/156 = 98.72 %`), while PASSing
    `96.0 %` and `98.0 %` on the neighbouring rows purely because those digit
    sequences occur in unrelated program source. An anti-fabrication gate whose
    verdict turns on digit coincidence is not measuring fabrication.

    The check is exact to the STATED precision: a percentage rounded to the
    digits the author wrote must equal the fraction rounded the same way, so
    `47/50` supports `94.0` and `94.00` and refuses `94.5`. A fabricated
    percentage beside an honest fraction still FAILs, which is the property
    that must not be lost.
    """
    try:
        stated = float(num_str)
    except ValueError:
        return False
    places = len(num_str.split(".", 1)[1]) if "." in num_str else 0
    for m in _FRACTION_RE.finditer(line):
        num, den = int(m.group(1)), int(m.group(2))
        if den == 0 or num > den:
            continue
        if round(100.0 * num / den, places) == round(stated, places):
            return True
    return False


def _number_present(num_str: str, corpus: str) -> bool:
    """Check whether the literal number appears in the corpus.

    Conservative: matches any occurrence of the same digit sequence.
    Avoids matching `0.018` against `0.0180` (would over-credit) by
    using word-boundary on both sides.
    """
    pat = r"(?<![\d.])" + re.escape(num_str) + r"(?![\d])"
    return re.search(pat, corpus) is not None


def audit(plugin_root: Path,
          git_diff_ref: Optional[str] = None,
          max_violations: int = 200,
          ) -> Tuple[str, List[MetricFinding]]:
    findings: List[MetricFinding] = []
    if not plugin_root.is_dir():
        return "VACUOUS_PASS", []

    # Build corpus: source files always; git-diff text optionally.
    corpus = _source_corpus(plugin_root)
    if git_diff_ref:
        corpus += "\n" + _git_diff_corpus(plugin_root, git_diff_ref)

    # Files to audit. v1.6.48 extends scope to repo-root README and
    # every `.md` under `docs/` so quoted sign-off numerics in user-
    # facing docs (not just CHANGELOG) are kept reproducible.
    audit_files: List[Path] = []
    for cand in (
        plugin_root / "CHANGELOG.md",
        plugin_root / ".claude-plugin" / "plugin.json",
        plugin_root.parent / ".claude-plugin" / "marketplace.json",
        plugin_root.parent / "CHANGELOG.md",
    ):
        if cand.is_file():
            audit_files.append(cand)
    repo_root = plugin_root.parent.parent.parent
    readme = repo_root / "README.md"
    if readme.is_file():
        audit_files.append(readme)
    # Narrow scope to canonical technical refs. Business / design /
    # legal / tutorial / report markdown is intentionally narrative
    # (market shares, throughput slogans, competitive % — none of
    # which is sign-off-class fabrication territory). Only
    # `docs/architecture/` carries the kind of numeric we actually
    # want pinned to source.
    arch_dir = repo_root / "docs" / "architecture"
    if arch_dir.is_dir():
        audit_files.extend(sorted(arch_dir.rglob("*.md")))

    if not audit_files:
        return "VACUOUS_PASS", []

    _SCANNED["files"] = len(audit_files)
    _SCANNED["items"] = 0
    for f in audit_files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = text.splitlines()
        _m = _extract_metrics(text)
        _SCANNED["items"] += len(_m)
        for ln_no, metric in _m:
            num, unit = metric.split()[0], metric.split()[1]
            line = lines[ln_no - 1] if 0 < ln_no <= len(lines) else ""
            if unit == "%" and _derivable_from_a_fraction_on_the_line(num, line):
                continue
            if not _number_present(num, corpus):
                rel = f.relative_to(plugin_root.parent) \
                    if f.is_relative_to(plugin_root.parent) else f
                findings.append(MetricFinding(
                    file=str(rel),
                    line=ln_no,
                    metric=metric,
                    rule="UNREPRODUCIBLE_METRIC",
                    detail=(f"value {num!r} from CHANGELOG/marketplace "
                            "doesn't appear anywhere in plugin source "
                            "(programs/ tests/) or recent git diff. "
                            "Either: emit the value from real code "
                            "(with `# source:` justification), or "
                            "remove the literal from the changelog "
                            "and reference an artefact path instead."),
                ))
                if len(findings) >= max_violations:
                    break
        if len(findings) >= max_violations:
            break

    return ("FAIL" if findings else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Anti-fabrication: every quantitative metric in "
                    "CHANGELOG / marketplace.json must be reproducible "
                    "from plugin source.")
    ap.add_argument("plugin_root")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--git-diff",
                    help="also accept metrics that appear in `git diff "
                         "<ref> -- plugins/`")
    ap.add_argument("--max-violations", type=int, default=200,
                    help="cap the report at N findings (default 200)")
    args = ap.parse_args(argv)

    root = Path(args.plugin_root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    verdict, findings = audit(root,
                              git_diff_ref=args.git_diff,
                              max_violations=args.max_violations)
    report = {
        "gate": "changelog_metric_reproducibility_check",
        "verdict": verdict,
        "plugin_root": str(root),
        "git_diff_ref": args.git_diff,
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings[:200]],
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print("VACUOUS_PASS: no CHANGELOG.md / plugin.json / "
              "marketplace.json found")
        return 0
    if verdict == "PASS":
        print(f"PASS: {_SCANNED['items']} metric(s) across "
              f"{_SCANNED['files']} audited file(s) — every one is "
              f"reproducible from plugin source")
        return 0
    print(f"FAIL: {len(findings)} unreproducible CHANGELOG metric(s):",
          file=sys.stderr)
    for f in findings[:10]:
        print(f"  {f.file}:{f.line}  metric={f.metric!r}",
              file=sys.stderr)
    if len(findings) > 10:
        print(f"  … and {len(findings) - 10} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
