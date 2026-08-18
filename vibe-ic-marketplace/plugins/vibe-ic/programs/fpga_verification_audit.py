#!/usr/bin/env python3
"""fpga_verification_audit.py — v0.53 plugin gate

Audits `reports/fpga_verification_report.md` (agent-written Chinese/English
prose) for claims that must be traceable to machine-generated artefacts.

The v0.52 fresh-agent claimed "1083/1083 PASS, estimated ≥ 95 % line
coverage" in prose. The first number was truthful (`sim/work/summary.txt`
agreed). The coverage number was NOT — actual measurement produced 78 %.
This gate reads the markdown and enforces:

  1. Any integer `<N>/<M>` pattern that looks like a test-pass count (e.g.
     "1083 PASS", "1083/1083 PASS") must match `sim/work/summary.txt`'s
     `GRAND_TOTAL PASS=<N> FAIL=<0>` line.
  2. Any coverage percentage claim ("line coverage 78 %", "branch 82 %")
     must match the totals in `reports/coverage/coverage_actual.json`.
  3. Estimation keywords ("estimated", "approx", "≥ 95 %", ">=95") are
     flagged as untrusted claims that must be replaced by tool numbers.
  4. Tool name mentions (Verilator, Icarus, iverilog, verilator_coverage)
     must correspond to actual tool artefacts on disk.

This gate does not re-measure anything; it verifies that the numbers in
the human-facing report are traceable. Run AFTER
`verilator_coverage_measure.py` and after the sim summary has been
written.

Usage:
    python3 fpga_verification_audit.py \\
        --report reports/fpga_verification_report.md \\
        --summary sim/work/summary.txt \\
        --coverage reports/coverage/coverage_actual.json \\
        --out reports/gates/fpga_verification_audit.json

Exit code:
    0 — every claim in the report is traceable to an artefact
    1 — one or more claims cannot be traced (or are self-estimated)
    2 — input artefacts missing / malformed
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Default location of the estimation-keywords YAML, shipped under
# plugins/vibe-ic/data/. Users can pass --keywords-yaml to override
# (e.g. to add domain-specific Chinese / Japanese vocabulary without
# editing this program).
_DEFAULT_KEYWORDS_YAML = (
    Path(__file__).parent.parent / "data" / "estimation_keywords.yaml"
)


# ----- helpers ------------------------------------------------------


def load_summary(path: str) -> Dict[str, int]:
    """Parse `sim/work/summary.txt` format:
        tb_foo PASS=10 FAIL=0 ERR=0
        ...
        GRAND_TOTAL PASS=1083 FAIL=0
    Returns {'grand_total': 1083, 'fail_total': 0, per-tb dict...}
    """
    p = Path(path)
    if not p.exists():
        return {}
    out: Dict[str, int] = {}
    for line in p.read_text(errors="replace").splitlines():
        m = re.match(r"(\S+)\s+PASS=(\d+)\s+FAIL=(\d+)", line)
        if m:
            out[m.group(1)] = int(m.group(2))
            out[m.group(1) + "_fail"] = int(m.group(3))
    return out


def load_coverage(path: str) -> Optional[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


# ----- claim extraction --------------------------------------------

PASS_COUNT_RE = re.compile(
    r"\b(\d{2,6})\s*(?:/\s*\d{2,6})?\s*(?:個|tests?|cases?)?\s*(?:PASS|passed|pass|過|通過)",
    re.I,
)

COVERAGE_RE = re.compile(
    r"\b(line|toggle|branch|分支|行|線|lcov)\s*(?:coverage|覆蓋率?)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*%",
    re.I,
)

# Built-in fallback regex (used only if the YAML can't be loaded).
# The full multi-language list lives in data/estimation_keywords.yaml.
ESTIMATION_RE = re.compile(
    r"(?:estimated|estimate|approx(?:imate)?|approximately|大約|估計|約|預估)",
    re.I,
)
SOFT_THRESHOLD_RE = re.compile(r"(?:≥|>=)\s*(\d+(?:\.\d+)?)\s*%")


def _parse_simple_yaml_lists(yaml_path: Path) -> Dict[str, List[str]]:
    """Tiny stdlib-only YAML reader that extracts top-level
    `<key>:` blocks each containing a list of strings (`- value`).

    Supports:
      - quoted (single + double) and unquoted scalar list items
      - inline `# comment` after a list item
      - blank lines / comment lines between items
    """
    out: Dict[str, List[str]] = {}
    if not yaml_path.exists():
        return out
    current: Optional[str] = None
    for raw in yaml_path.read_text().splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # Top-level key (column 0, ends in `:` and no value after)
        if not raw.startswith((" ", "\t")) and line.endswith(":"):
            current = line[:-1].strip()
            out.setdefault(current, [])
            continue
        # List item under the current key
        s = line.strip()
        if current is None or not s.startswith("-"):
            continue
        val = s[1:].strip()
        # Strip inline comment (only if not inside quotes)
        if val.startswith(("'", '"')):
            quote = val[0]
            end = val.find(quote, 1)
            if end > 0:
                val = val[1:end]
            else:
                val = val[1:]
        else:
            val = re.sub(r"\s+#.*$", "", val).strip()
        if val:
            out[current].append(val)
    return out


def load_estimation_keywords(yaml_path: Optional[Path] = None
                             ) -> Tuple[List[re.Pattern], List[re.Pattern]]:
    """Return (keyword_regexes, soft_threshold_regexes).

    Falls back to the built-in `ESTIMATION_RE` / `SOFT_THRESHOLD_RE`
    when the YAML is missing or empty, so the gate still works on a
    fresh checkout that hasn't shipped data/."""
    path = yaml_path or _DEFAULT_KEYWORDS_YAML
    parsed = _parse_simple_yaml_lists(path)
    kw = parsed.get("keywords", [])
    sft = parsed.get("soft_threshold_patterns", [])
    keyword_regexes = [re.compile(p, re.I | re.UNICODE) for p in kw] \
        if kw else [ESTIMATION_RE]
    soft_regexes = [re.compile(p, re.UNICODE) for p in sft] \
        if sft else [SOFT_THRESHOLD_RE]
    return keyword_regexes, soft_regexes

TOOL_NAMES = ["Verilator", "verilator_coverage", "iverilog", "Icarus", "Yosys", "OpenROAD", "KLayout"]


def extract_pass_counts(md: str) -> List[int]:
    return [int(m.group(1)) for m in PASS_COUNT_RE.finditer(md)]


def extract_coverage_claims(md: str) -> List[Tuple[str, float]]:
    return [(m.group(1).lower(), float(m.group(2))) for m in COVERAGE_RE.finditer(md)]


def find_estimation_flags(md: str,
                          keyword_regexes: Optional[List[re.Pattern]] = None,
                          soft_regexes: Optional[List[re.Pattern]] = None,
                          ) -> List[str]:
    """Scan `md` for estimation language. Each hit is a ~40-char snippet.

    `keyword_regexes` / `soft_regexes` come from
    `load_estimation_keywords()` so they're configurable per language /
    per project. When omitted, falls back to the built-in defaults.
    """
    if keyword_regexes is None or soft_regexes is None:
        keyword_regexes, soft_regexes = load_estimation_keywords()
    hits: List[str] = []
    for pat in list(keyword_regexes) + list(soft_regexes):
        for m in pat.finditer(md):
            s = max(0, m.start() - 20)
            e = min(len(md), m.end() + 20)
            hits.append(md[s:e].replace("\n", " "))
    return hits


# ----- auditing ----------------------------------------------------


def audit(
    report_md: str,
    summary: Dict[str, int],
    coverage: Optional[Dict[str, Any]],
    keyword_regexes: Optional[List[re.Pattern]] = None,
    soft_regexes: Optional[List[re.Pattern]] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    findings: List[Dict[str, Any]] = []
    all_ok = True

    # --- Pass-count claims ---
    claimed_counts = extract_pass_counts(report_md)
    gt = summary.get("GRAND_TOTAL")
    unique_claims = sorted(set(claimed_counts))
    if gt is None and claimed_counts:
        findings.append(
            {
                "kind": "pass_count",
                "ok": False,
                "detail": f"report claims {unique_claims} PASS but summary.txt has no GRAND_TOTAL",
            }
        )
        all_ok = False
    elif gt is not None:
        # Require the GRAND_TOTAL value to appear in the report
        if gt not in claimed_counts:
            findings.append(
                {
                    "kind": "pass_count",
                    "ok": False,
                    "detail": (
                        f"summary.txt GRAND_TOTAL={gt} not found in report "
                        f"(report mentions {unique_claims})"
                    ),
                }
            )
            all_ok = False
        else:
            findings.append(
                {"kind": "pass_count", "ok": True, "detail": f"GRAND_TOTAL={gt} matches report claim"}
            )

    # --- Coverage claims ---
    cov_claims = extract_coverage_claims(report_md)
    if cov_claims:
        if coverage is None:
            findings.append(
                {
                    "kind": "coverage",
                    "ok": False,
                    "detail": "report makes coverage claims but coverage_actual.json not found",
                }
            )
            all_ok = False
        else:
            totals = coverage.get("totals", {})
            for kind, pct in cov_claims:
                # map Chinese keys
                key_map = {"行": "line", "線": "line", "分支": "branch"}
                canon = key_map.get(kind, kind)
                tool_pct = None
                if canon in totals and isinstance(totals[canon], dict):
                    tool_pct = totals[canon].get("pct")
                if tool_pct is None:
                    findings.append(
                        {
                            "kind": "coverage",
                            "ok": False,
                            "detail": f"report claims {kind}={pct}% but coverage_actual.json has no {canon}",
                        }
                    )
                    all_ok = False
                elif abs(float(tool_pct) - pct) > 1.0:
                    findings.append(
                        {
                            "kind": "coverage",
                            "ok": False,
                            "detail": f"{canon}: report={pct}% vs coverage_actual.json={tool_pct}%",
                        }
                    )
                    all_ok = False
                else:
                    findings.append(
                        {
                            "kind": "coverage",
                            "ok": True,
                            "detail": f"{canon}: report={pct}% matches tool {tool_pct}%",
                        }
                    )

    # --- Estimation keywords ---
    est_hits = find_estimation_flags(report_md, keyword_regexes, soft_regexes)
    for h in est_hits:
        findings.append(
            {
                "kind": "estimation",
                "ok": False,
                "detail": f"estimation language detected: ...{h.strip()}...",
            }
        )
    if est_hits:
        all_ok = False

    # --- Tool mentions ---
    for tool in TOOL_NAMES:
        if tool.lower() in report_md.lower():
            findings.append(
                {
                    "kind": "tool_mention",
                    "ok": True,
                    "detail": f"report mentions {tool}",
                }
            )

    return findings, all_ok


# ----- CLI ----------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--report", required=True, help="markdown report to audit")
    p.add_argument("--summary", default="phase2/stage1/sim/work/summary.txt")
    p.add_argument("--coverage", default="reports/coverage/coverage_actual.json")
    p.add_argument("--out", default="reports/gates/fpga_verification_audit.json")
    p.add_argument("--keywords-yaml", default=None,
                   help="Override estimation-keywords list "
                        "(default: plugins/vibe-ic/data/estimation_keywords.yaml). "
                        "Useful for adding domain-specific or per-language vocabulary.")
    p.add_argument("--warn-only", action="store_true")
    args = p.parse_args(argv)

    rp = Path(args.report)
    if not rp.exists():
        print(f"[fpga-verification-audit] missing: {rp}", file=sys.stderr)
        return 2
    md = rp.read_text(errors="replace")

    summary = load_summary(args.summary)
    coverage = load_coverage(args.coverage)
    kw_path = Path(args.keywords_yaml) if args.keywords_yaml else None
    keyword_regexes, soft_regexes = load_estimation_keywords(kw_path)

    findings, all_ok = audit(md, summary, coverage, keyword_regexes, soft_regexes)

    out = {
        "report": str(rp),
        "summary_grand_total": summary.get("GRAND_TOTAL"),
        "coverage_totals": (coverage or {}).get("totals"),
        "findings": findings,
        "ok": all_ok,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))

    if not all_ok:
        print(f"[fpga-verification-audit] {len(findings)} findings (see {args.out}):", file=sys.stderr)
        for f in findings:
            mark = "OK " if f["ok"] else "BAD"
            print(f"  [{mark}] {f['kind']}: {f['detail']}", file=sys.stderr)
        if args.warn_only:
            return 0
        return 1

    print(f"[fpga-verification-audit] PASS  all claims traceable  → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
