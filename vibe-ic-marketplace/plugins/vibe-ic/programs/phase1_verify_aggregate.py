"""v0.1.50 — Phase 1 output verification aggregator (Pattern-C → program).

Doctrine: `skills/phase1-output-verify/SKILL.md` asks Claude to spot-check
13 L*.json layer documents emitted by `phase1_one_shot_runner`. The
spot-check is enumerable (file presence + schema conformance + cross-
layer consistency). All deterministic.

This aggregator runs the existing phase1_*_check programs and emits a
unified verdict per L doc, so the skill becomes a thin wrapper that
narrates residuals the program flagged.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)
from l_doc_taxonomy import L_DOCS_V1


# The chip-centric L-doc set phase1 emits, in taxonomy order.  L8 has TWO
# independent documents (constants and timing), so the current contract is 14
# files even though its numeric labels end at L13.  This used to be a private,
# obsolete list of pre-taxonomy names; it consequently called a complete
# current output "missing".  Import the producer's single source of truth.
L_DOCS = tuple(spec.full_name for spec in L_DOCS_V1)
_L_DOC_CODES = {spec.full_name: spec.code for spec in L_DOCS_V1}

# Accept historical long stems while projects migrate, but REPORT under the
# canonical current taxonomy.  L8C deliberately has no ambiguous ``L8`` short
# alias: one legacy file must never satisfy both independent L8 documents.
_LEGACY_STEMS = {
    "L1_DATASHEET": ("L1_PRODUCT_VISION",),
    "L3_CMD_PROTOCOL": ("L3_USE_CASES",),
    "L4_REGMAP": ("L4_USER_FLOW",),
    "L5_ADI_SPEC": ("L5_BLOCK_PLAN",),
    "L6_CONTROL_LOGIC": ("L6_INTERFACE_LIST",),
    "L7_TEST_DEBUG": ("L7_REGISTER_MAP",),
    "L9_INTEGRATION_SPEC": ("L9_CONSTRAINTS",),
    "L10_TEST_CASES": ("L10_TEST_PLAN",),
    "L11_OTP_CONTENT": ("L11_VERIFICATION_PLAN",),
    "L13_LAB_CALIBRATION": ("L13_DELIVERABLES",),
}

# Backing programs (all existing as of v0.1.50)
BACKING_CHECKS = (
    "phase1_all_l_docs_present_check.py",
    "phase1_doc_presence_check.py",
    "phase1_doc_input_completeness_check.py",
    "phase1_doc_content_implementation_completeness_check.py",
    "phase1_consistency_check.py",
    "phase1_input_vs_generated_completeness_check.py",
    "phase1_gate_contract_check.py",
    # v1.2.37 — ANTI-FABRICATION grounding: every direct input-doc evidence
    # literal's NAME identifiers must appear in the input (catches an
    # LLM-/extractor-invented fact that the completeness + provenance-presence +
    # schema gates above do NOT — the OUTPUT->INPUT direction). §4.2 / §4.05.
    "phase1_evidence_grounding_check.py",
)

PROGRAMS_DIR = Path(__file__).resolve().parent

# Per-check ARGUMENT SHAPE. The backing checks do NOT share one CLI contract:
#   PROJECT   — takes the PROJECT root and resolves generated_docs/ itself.
#   DOCS_DIR  — takes the generated_docs/ directory DIRECTLY.
#   NONE      — takes NO positional at all (introspects the gate programs via
#               its own --gates default; the project dir is meaningless to it).
# Passing <project> positionally to every check (the prior behaviour) made the
# DOCS_DIR checks look at the wrong directory (spurious FAIL) and made the NONE
# check argparse-error on an "unrecognized argument" (spurious FAIL) — even
# though each PASSES when invoked with its correct arg shape. This map restores
# the correct shape per check. chip-AGNOSTIC.
CHECK_ARG_SHAPE = {
    "phase1_all_l_docs_present_check.py": "PROJECT",
    "phase1_doc_presence_check.py": "DOCS_DIR",
    "phase1_doc_input_completeness_check.py": "PROJECT",
    "phase1_doc_content_implementation_completeness_check.py": "PROJECT",
    "phase1_consistency_check.py": "DOCS_DIR",
    "phase1_input_vs_generated_completeness_check.py": "PROJECT",
    "phase1_gate_contract_check.py": "NONE",
    "phase1_evidence_grounding_check.py": "PROJECT",
}


def resolve_docs_dir(project_dir: Path) -> Path:
    """Return the generated_docs/ directory for ``project_dir``.

    Tolerant of BOTH the canonical runner layout (``phase1/generated_docs`` —
    _path_layout.generated_docs_dir) and the flat ``generated_docs`` layout.
    Prefers a candidate that actually holds L*.json; else the first that
    exists; else the canonical path (so a caller still gets a sensible dir)."""
    candidates = [
        project_dir / "phase1" / "generated_docs",
        project_dir / "generated_docs",
    ]
    for c in candidates:
        if c.is_dir() and any(c.glob("L*.json")):
            return c
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


@dataclass
class CheckResult:
    name: str
    exit_code: int
    stdout_tail: str
    stderr_tail: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self) | {"passed": self.passed}


@dataclass
class Phase1Report:
    project_dir: str
    l_doc_presence: Dict[str, bool]
    check_results: List[CheckResult]
    pass_count: int
    fail_count: int
    verdict: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "l_doc_presence": self.l_doc_presence,
            "check_results": [c.as_dict() for c in self.check_results],
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "verdict": self.verdict,
            "emitted_by": _pmd.emitted_by("phase1_verify_aggregate"),
        }


def scan_l_doc_presence(project_dir: Path) -> Dict[str, bool]:
    """Look for L*.json in the project's generated_docs/ (canonical or flat)."""
    out: Dict[str, bool] = {}
    docs_dir = resolve_docs_dir(project_dir)
    for doc in L_DOCS:
        stems = [doc, *_LEGACY_STEMS.get(doc, ())]
        code = _L_DOC_CODES[doc]
        if code == "L8T":
            stems.append("L8")
        elif code != "L8C":
            stems.append(code)
        candidates = tuple(docs_dir / f"{stem}.json" for stem in stems)
        out[doc] = any(p.exists() for p in candidates)
    return out


def build_check_cmd(name: str, project_dir: Path) -> List[str]:
    """Construct the argv for a backing check with the ARG SHAPE it expects.

    Unknown checks default to PROJECT (the historical behaviour) so a newly
    added backing check never silently drops its argument."""
    shape = CHECK_ARG_SHAPE.get(name, "PROJECT")
    cmd = [sys.executable, str(PROGRAMS_DIR / name)]
    if shape == "DOCS_DIR":
        cmd.append(str(resolve_docs_dir(project_dir)))
    elif shape == "NONE":
        pass  # takes no positional (introspects the gate programs itself)
    else:  # PROJECT
        cmd.append(str(project_dir))
    return cmd


def _run_check(name: str, project_dir: Path) -> CheckResult:
    cmd = build_check_cmd(name, project_dir)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, check=False)
        return CheckResult(
            name=name, exit_code=proc.returncode,
            stdout_tail=proc.stdout[-500:],
            stderr_tail=proc.stderr[-500:],
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name=name, exit_code=124,
                            stdout_tail="", stderr_tail="timeout")
    except FileNotFoundError:
        return CheckResult(name=name, exit_code=127,
                            stdout_tail="", stderr_tail="program not found")


def aggregate(project_dir: Path,
              checks: List[CheckResult],
              presence: Dict[str, bool]) -> Phase1Report:
    pass_count = sum(1 for c in checks if c.passed)
    fail_count = len(checks) - pass_count
    missing = [d for d, p in presence.items() if not p]
    if missing or fail_count:
        verdict = "FAIL"
    else:
        verdict = "PASS"
    return Phase1Report(
        project_dir=str(project_dir),
        l_doc_presence=presence,
        check_results=checks,
        pass_count=pass_count,
        fail_count=fail_count,
        verdict=verdict,
    )


def verify(project_dir: Path) -> Phase1Report:
    presence = scan_l_doc_presence(project_dir)
    checks = [_run_check(name, project_dir) for name in BACKING_CHECKS]
    return aggregate(project_dir, checks, presence)


def report_to_markdown(rep: Phase1Report) -> str:
    out = ["# Phase 1 verification aggregate",
           "",
           f"_Emitted by `phase1_verify_aggregate.py` "
           f"(v{_pmd.running_plugin_version()}). "
           f"Refuse to overclaim — every L doc must be present AND every "
           f"backing check must PASS._",
           "",
           f"- **Verdict**: {rep.verdict}",
           f"- **Backing checks**: {rep.pass_count}/{len(rep.check_results)} PASS",
           ""]
    out.append("## L doc presence")
    out.append("")
    out.append("| L doc | Present |")
    out.append("|---|---|")
    for doc, present in rep.l_doc_presence.items():
        out.append(f"| {doc} | {'✓' if present else '✗'} |")
    out.append("")
    out.append("## Backing check results")
    out.append("")
    out.append("| Check | Exit | Verdict |")
    out.append("|---|---|---|")
    for c in rep.check_results:
        out.append(f"| `{c.name}` | {c.exit_code} | "
                   f"{'PASS' if c.passed else 'FAIL'} |")
    out.append("")
    return "\n".join(out)


def _cli() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project_dir", type=Path)
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    p.add_argument("--strict", action="store_true")
    args = p.parse_args()
    if not args.project_dir.exists():
        print(f"project not found: {args.project_dir}", file=sys.stderr)
        return 2
    rep = verify(args.project_dir)
    md = report_to_markdown(rep)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(rep.as_dict(), indent=2), encoding="utf-8")
    if args.strict and rep.verdict != "PASS":
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
