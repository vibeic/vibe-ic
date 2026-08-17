#!/usr/bin/env python3
"""vibe_ic_entry_guard.py — enforce single entry point for benchmark + IC runs.

Doctrine (owner directive 2026-06-28, BINDING):

    A benchmark / IC-design number is meaningful ONLY if it measures what the
    Vibe-IC deterministic runner chain can produce.  Therefore every run MUST
    enter through the Vibe-IC plugin's Phase-1 path; direct-agent authoring or
    patching followed by a host-scorer invocation measures "Opus + MCP-EDA",
    not Vibe-IC.

Canonical single entry point:

    python3 vibe_ic_one_shot_runner.py <project>

That orchestrator already integrates phase1_one_shot_runner.py (which in turn
invokes phase1_engine.cli), then phase2 / analog / phase3.

This guard accepts any of the following as evidence that the run went through
the Vibe-IC runner:

  - reports/orchestrator/vibe_ic_one_shot.json   (full orchestrator report)
  - reports/orchestrator/phase1_one_shot.json    (phase1 standalone runner)
  - reports/phase1_one_shot.json                 (legacy phase1 location)
  - phase1/generated_docs/L1_DATASHEET.json      (phase1 engine output)
  - work/<design>/reports/orchestrator/vibe_ic_one_shot.json (Shape-B run)
  - work/<design>/phase1/generated_docs/L*.json  (Shape-B fact graph)

Trust boundary: this is a cooperative workflow/evidence-integrity gate, not a
cryptographic or OS-principal attestation service.  It rejects missing,
malformed, stale-taxonomy, or structurally impossible runner records.  Code
already executing as the same uid can reconstruct local files and is outside
this gate's authority; claiming protection against that caller would require a
separate principal or signing service.  Score reports must not describe this
check as proof against a malicious same-uid author.

A run dir that lacks all of these is rejected unless the caller explicitly
passes --allow-direct-agent (which still emits a mandatory disclosure).

Usage:
    python3 vibe_ic_entry_guard.py <project|run_dir> [--strict]
    python3 vibe_ic_entry_guard.py <project|run_dir> --allow-direct-agent

Exit codes:
    0  entry-point evidence found (or --allow-direct-agent warn issued)
    1  no evidence (only under --strict; default is warn + rc=0 for back-compat)

Verdict mode: ``--strict`` is BLOCKING; the default and the explicit
``--allow-direct-agent`` compatibility path are ADVISORY and disclose the
missing evidence on stderr/stdout respectively.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple

import l_doc_generator_stamp as _generator_stamp
import l_doc_taxonomy as _l_doc_taxonomy


# Ordered: strongest evidence first.  Any one of these is sufficient.
_EVIDENCE_FILES = [
    "reports/orchestrator/vibe_ic_one_shot.json",
    "reports/orchestrator/phase1_one_shot.json",
    # Pre-project-layout legacy location.  Kept as a compatibility reader;
    # both locations use the same producer-envelope validator below.
    "reports/phase1_one_shot.json",
    "phase1/generated_docs/L1_DATASHEET.json",
]

# Shape-C per-problem evidence (open-benchmark-methodology § 7.5 rule 3).
#
# An atomic-micro-problem (Shape-C) run does NOT have a single run-root phase1
# tree: the harness drives `phase1_engine` ONCE PER PROBLEM, so the fact-graph
# lands under `<run>/work/<problem>/…/generated_docs/L*.json`.  § 7.5 rule 3 is
# explicit that this path still counts as Phase-1 entry ("the Phase-1
# fact-graph is still produced; the gate simply wraps the emit") — the run-root
# file list above simply had no branch for that layout, so a fully-compliant
# Shape-C run was rejected as if it were direct-agent authoring.
#
# Both layouts `gates_atomic.py` itself accepts are honoured (see its
# `out/generated_docs` / `phase1_proj/phase1/generated_docs` lookup).
#
# NO-LEAK (§ 4.05): this is a guard-RELAXING branch, so it is deliberately
# narrow — it requires an actual rendered phase1 LAYER DOC (`L<digits>_*.json`)
# inside a `generated_docs/` directory under a per-problem work dir.  A bare
# `work/` tree, an empty `generated_docs/`, or hand-dropped non-layer JSON does
# NOT satisfy it, so direct-agent authoring is still caught.
_EVIDENCE_GLOBS = [
    # Shape-B: one canonical project per benchmark design.
    "work/*/phase1/generated_docs/L*.json",
    # Shape-C: one atomic phase1 project per problem.
    "work/*/out/generated_docs/L*.json",
    "work/*/phase1_proj/phase1/generated_docs/L*.json",
]

# Shape-B's full orchestrator evidence is a fixed filename, not a layer doc.
# Keep it separate from the L-doc regex so an arbitrary JSON file at a similar
# depth cannot satisfy the guard.
_EVIDENCE_REPORT_GLOBS = [
    "work/*/reports/orchestrator/vibe_ic_one_shot.json",
]

# A layer doc is L<digits>_<NAME>.json — pinned so a stray `Lfoo.json` or a
# `L1_DATASHEET.json.bak` cannot stand in for real phase1 output.
_LAYER_DOC_RE = re.compile(r"^L\d+_[A-Za-z0-9_]+\.json$")
_CANONICAL_LAYER_FILES = {
    f"{spec.full_name}.json": spec.code
    for spec in _l_doc_taxonomy.L_DOCS_V2
}
_ORCHESTRATOR_VERDICTS = {"PASS", "PASS_WITH_WAIVERS", "FAIL"}
_PHASE_VERDICTS = _ORCHESTRATOR_VERDICTS | {
    "WAIVED", "SKIP", "SKIPPED", "COVERAGE-INCOMPLETE"
}
_PHASE1_STEP_STATUSES = {"PASS", "FAIL", "BLOCKED", "WAIVED", "SKIP"}
_ORCHESTRATOR_PHASES = {
    "phase1", "phase2", "analog", "phase3", "mixed_signal"
}


@dataclass
class EntryGuardFinding:
    rule: str
    path: str
    detail: str


def _read_json_object(path: Path) -> dict | None:
    """Read one evidence file as a JSON object, or fail closed."""
    try:
        data = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _project_matches(value: object, expected_project: Path) -> bool:
    """The runners write the resolved project path; bind evidence to it."""
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = Path(value)
    if not candidate.is_absolute():
        return False
    try:
        return candidate.resolve() == expected_project.resolve()
    except (OSError, RuntimeError):
        return False


def _valid_phase_row(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    rc = row.get("rc")
    return (row.get("name") in _ORCHESTRATOR_PHASES
            and row.get("verdict") in _PHASE_VERDICTS
            and isinstance(rc, int) and not isinstance(rc, bool))


def _is_orchestrator_report(path: Path, expected_project: Path) -> bool:
    """Require the minimal canonical one-shot report structure.

    The exact filename/depth prevents similar-path leakage; checking the report
    envelope prevents an empty file or hand-dropped ``{"verdict": "PASS"}``
    from standing in for evidence that the orchestrator actually ran.
    """
    data = _read_json_object(path)
    if data is None or data.get("phase") != "vibe-ic":
        return False
    phases = data.get("phases")
    if (not _project_matches(data.get("project"), expected_project)
            or data.get("verdict") not in _ORCHESTRATOR_VERDICTS
            or not isinstance(phases, list)
            or [row.get("name") if isinstance(row, dict) else None
                for row in phases] != [
                    "phase1", "phase2", "analog", "phase3", "mixed_signal"]
            or not all(_valid_phase_row(row) for row in phases)):
        return False
    digital = [row["verdict"] for row in phases
               if row["name"] not in {"analog", "mixed_signal"}
               and row["verdict"] != "SKIPPED"]
    if not digital:
        expected_verdict = "FAIL"
    elif "FAIL" in digital:
        expected_verdict = "FAIL"
    elif any(verdict in {"PASS_WITH_WAIVERS", "WAIVED",
                         "COVERAGE-INCOMPLETE"}
             for verdict in digital):
        expected_verdict = "PASS_WITH_WAIVERS"
    else:
        expected_verdict = "PASS"
    return data["verdict"] == expected_verdict


def _valid_phase1_step(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    duration = row.get("duration_s")
    return (isinstance(row.get("name"), str) and bool(row["name"])
            and row.get("status") in _PHASE1_STEP_STATUSES
            and isinstance(duration, (int, float))
            and not isinstance(duration, bool) and duration >= 0
            and isinstance(row.get("detail"), str)
            and isinstance(row.get("extras"), dict))


def _phase1_steps_verdict(steps: list) -> str:
    statuses = {row["status"] for row in steps}
    if statuses & {"FAIL", "BLOCKED"}:
        return "FAIL"
    if statuses & {"WAIVED", "SKIP"}:
        return "PASS_WITH_WAIVERS"
    return "PASS"


def _is_phase1_report(path: Path, expected_project: Path) -> bool:
    """Validate the mode-specific envelope the Phase-1 producer emits."""
    data = _read_json_object(path)
    if (data is None or data.get("phase") != 1
            or not _project_matches(data.get("project"), expected_project)
            or data.get("verdict") not in _ORCHESTRATOR_VERDICTS):
        return False

    mode = data.get("mode")
    if mode == "docs":
        rc = data.get("delegated_rc")
        if (data.get("delegated_to") != "phase1_doc_one_shot_runner"
                or not isinstance(rc, int) or isinstance(rc, bool)
                or not 0 <= rc <= 255):
            return False
        return data["verdict"] == ("PASS" if rc == 0 else "FAIL")

    if mode == "prompt":
        # Prompt mode is not a delegation.  Its producer-owned evidence is the
        # two StepResult rows assembled by phase1_one_shot_runner itself.
        steps = data.get("steps")
        if (not isinstance(steps, list) or len(steps) != 2
                or not all(_valid_phase1_step(row) for row in steps)):
            return False
        if [row["name"] for row in steps] != [
                "phase1_ingest_render", "phase1_human_docs"]:
            return False
        return data["verdict"] == _phase1_steps_verdict(steps)

    return False


def _emitter_source(emitter: object) -> Path | None:
    """Resolve a stamp's derived ``module.function`` to shipped source."""
    if not isinstance(emitter, str):
        return None
    match = re.fullmatch(r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)", emitter)
    if not match:
        return None
    module = match.group(1)
    candidates = (
        Path(__file__).resolve().parent / f"{module}.py",
        Path(__file__).resolve().parent.parent / "tools" / "phase1_engine"
        / f"{module}.py",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _is_shipped_l_doc_writer(emitter: object) -> bool:
    """The named function must exist and directly call the stamp chokepoint."""
    source = _emitter_source(emitter)
    if source is None:
        return False
    function = str(emitter).rpartition(".")[2]
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return False

    def _walk_without_nested_scopes(root: ast.AST):
        """Walk one lexical scope, excluding nested functions/classes."""
        stack = list(ast.iter_child_nodes(root))
        while stack:
            node = stack.pop()
            yield node
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.Lambda, ast.ClassDef)):
                continue
            stack.extend(ast.iter_child_nodes(node))

    # Bind the call receiver to the actual L-document stamping module.  A
    # mere ``*.dump(...)`` shape is insufficient: many shipped utilities call
    # ``json.dump`` and would otherwise become valid (but unrelated) producer
    # names a hand-authored stamp could borrow.  ``phase1_engine.cli``
    # intentionally re-exports ``render._stamp`` because package execution
    # cannot import programs/ directly; that single producer-owned re-export
    # is part of the same chokepoint.
    stamp_aliases = set()
    direct_dump_aliases = set()
    module_nodes = list(_walk_without_nested_scopes(tree))
    for node in module_nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "l_doc_generator_stamp":
                    stamp_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "l_doc_generator_stamp":
                    stamp_aliases.add(alias.asname or alias.name)
                if node.module == "l_doc_generator_stamp" \
                        and alias.name == "dump":
                    direct_dump_aliases.add(alias.asname or alias.name)
                if source.parent.name == "phase1_engine" \
                        and source.name == "cli.py" \
                        and node.module == "render" \
                        and alias.name == "_stamp":
                    stamp_aliases.add(alias.asname or alias.name)

    def _is_stamp_dump_call(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        if isinstance(node.func, ast.Name):
            return node.func.id in direct_dump_aliases
        return (isinstance(node.func, ast.Attribute)
                and node.func.attr == "dump"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in stamp_aliases)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                or node.name != function:
            continue
        function_nodes = list(_walk_without_nested_scopes(node))
        # A writer may import the chokepoint locally.  Do not borrow an import
        # from a sibling/nested function when deciding this function's claim.
        for child in function_nodes:
            if isinstance(child, ast.Import):
                for alias in child.names:
                    if alias.name == "l_doc_generator_stamp":
                        stamp_aliases.add(alias.asname or alias.name)
            elif isinstance(child, ast.ImportFrom) \
                    and child.module == "l_doc_generator_stamp":
                for alias in child.names:
                    if alias.name == "dump":
                        direct_dump_aliases.add(alias.asname or alias.name)
        return any(_is_stamp_dump_call(child) for child in function_nodes)
    return False


def _is_layer_doc(path: Path) -> bool:
    """Require a substantive L-document carrying the shared writer stamp.

    Filename shape alone is not runner evidence: an empty or hand-dropped
    ``L1_FAKE.json`` previously satisfied the entry guard.  Every current
    Phase-1 writer routes through ``l_doc_generator_stamp.dump``; its
    deterministic ``_generator`` envelope is therefore the common structural
    proof available across the heterogeneous L1-L28 document schemas.
    """
    if (not _LAYER_DOC_RE.match(path.name)
            or path.name not in _CANONICAL_LAYER_FILES):
        return False
    data = _read_json_object(path)
    if data is None:
        return False
    stamp = data.get("_generator")
    if not isinstance(stamp, dict):
        return False
    if stamp.get("plugin") != _generator_stamp.PLUGIN_NAME:
        return False
    current_digest, current_docs = _generator_stamp.taxonomy_digest()
    version = stamp.get("plugin_version")
    digest = stamp.get("l_doc_taxonomy_digest")
    docs = stamp.get("l_doc_taxonomy_docs")
    emitter = stamp.get("emitter")
    if version != _generator_stamp.plugin_version():
        return False
    if not current_digest or digest != current_digest:
        return False
    if (not isinstance(docs, int) or isinstance(docs, bool)
            or docs != current_docs or docs <= 0):
        return False
    if not _is_shipped_l_doc_writer(emitter):
        return False
    doc_id = data.get("doc_id")
    if doc_id is not None and doc_id != _CANONICAL_LAYER_FILES[path.name]:
        return False
    bookkeeping = {"_generator", "_comment", "source_documents", "provenance"}
    return any(key not in bookkeeping for key in data)


def _has_evidence(project: Path) -> Tuple[bool, List[EntryGuardFinding]]:
    """Return (has_evidence, findings)."""
    findings: List[EntryGuardFinding] = []
    for rel in _EVIDENCE_FILES:
        p = project / rel
        if not p.is_file():
            continue
        if rel == "reports/orchestrator/vibe_ic_one_shot.json" \
                and _is_orchestrator_report(p, project):
            return True, findings
        if rel in {"reports/orchestrator/phase1_one_shot.json",
                   "reports/phase1_one_shot.json"} \
                and _is_phase1_report(p, project):
            return True, findings
        if rel == "phase1/generated_docs/L1_DATASHEET.json" \
                and _is_layer_doc(p):
            return True, findings
    for pattern in _EVIDENCE_REPORT_GLOBS:
        if any(p.is_file() and _is_orchestrator_report(p, p.parents[2])
               for p in project.glob(pattern)):
            return True, findings
    # Per-design/per-problem phase1 evidence (§ 7.5 rule 3). Narrow by design:
    # the matched path must be a real rendered layer doc, not merely a file
    # sitting at the right depth.
    for pattern in _EVIDENCE_GLOBS:
        for p in project.glob(pattern):
            if p.is_file() and _is_layer_doc(p):
                return True, findings
    # None found — build a human finding.
    checked = ", ".join(
        _EVIDENCE_FILES + _EVIDENCE_REPORT_GLOBS + _EVIDENCE_GLOBS)
    findings.append(EntryGuardFinding(
        rule="MISSING_VIBE_IC_ENTRY_EVIDENCE",
        path=str(project),
        detail=(f"no Vibe-IC runner evidence found. Expected one of: {checked}. "
                "Run through `vibe_ic_one_shot_runner.py <project>` first.")))
    return False, findings


def audit(project: Path) -> Tuple[str, List[EntryGuardFinding]]:
    ok, findings = _has_evidence(project)
    return ("PASS", []) if ok else ("FAIL", findings)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=("Validate structural evidence that a benchmark/IC run "
                     "started through the Vibe-IC plugin "
                     "(vibe_ic_one_shot_runner.py)."))
    ap.add_argument("project", help="project / run directory to audit")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when evidence is missing (default: warn only)")
    ap.add_argument("--allow-direct-agent", action="store_true",
                    help=("explicit opt-out for exploratory direct-agent runs; "
                          "emits a mandatory disclosure"))
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    project = Path(args.project)
    if not project.exists():
        print(f"error: project/run dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings = audit(project)

    report = {
        "gate": "vibe_ic_entry_guard",
        "verdict": verdict,
        "project": str(project.resolve()),
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
        "doctrine": ("every benchmark / IC run MUST enter through "
                     "vibe_ic_one_shot_runner.py (owner directive 2026-06-28)"),
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "PASS":
        print(f"PASS: Vibe-IC structural runner-entry evidence found — "
              f"{project}")
        return 0

    # FAIL branch
    detail = findings[0].detail if findings else "missing runner evidence"
    if args.allow_direct_agent:
        print(f"WARN(direct-agent): {detail}")
        return 0

    print(f"FAIL: {detail}", file=sys.stderr)
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
