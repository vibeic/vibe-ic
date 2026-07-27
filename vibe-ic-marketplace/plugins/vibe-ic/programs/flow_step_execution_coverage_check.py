#!/usr/bin/env python3
"""flow_step_execution_coverage_check.py — enforce "every applicable step ran, in order".

`flow_compliance_check.py` already classifies each canonical step
(PASS / FAIL / MISSING / SKIPPED-CONDITION / WAIVED / VACUOUS-PASS) by inspecting
its `required_outputs`. What it does NOT do — and what this gate adds — is enforce
the two invariants an author actually cares about:

  1. NO-SKIP COMPLETENESS. Every *applicable* step (i.e. not legitimately
     SKIPPED-CONDITION / WAIVED / DEFERRED) must have actually run and produced
     output. An applicable step whose status is MISSING is a silently-skipped
     step — the exact "中間漏步驟" failure: the runner never drove it.

  2. ORDERING GUARD. No step may be marked done (PASS / VACUOUS-PASS) while an
     applicable step it declares it depends on has not truly PASSed. This is
     enforced two ways, and the code is wider than the name "terminal guard"
     suggests:

       * PRIMARY (graph): for EVERY step claimed done, walk its transitive
         `blocks_on` ancestry from the flow yaml and flag any applicable
         ancestor that is MISSING / FAIL — or VACUOUS-PASS when a vacuous
         ancestor is not an acceptable predecessor (see `_blocks_when_vacuous`).
         This is not restricted to terminal steps or to sign-off ancestors.
       * FALLBACK (name): a terminal hand-off step (GDSII output / Foundry
         Handoff / Tapeout checklist) that ships NO `blocks_on` edges at all is
         still guarded against every applicable sign-off step (Physical
         Verification / DRC / LVS / ERC / post-route STA / parasitic extraction
         / antenna / IR-drop / SI). Producing a GDS or ticking "ready for
         foundry" while DRC never ran is an integrity violation, not a warning.

Ordering edges come from the flow yaml's own `blocks_on` field (`_load_blocks_on`);
the *roles* used by the name-based fallback and by the vacuous-ancestor rule are
derived from the step NAME and `stage` (universal flow-stage vocabulary), NOT from a
per-chip allow-list — so the guard is chip-AGNOSTIC and survives flow-yaml
renumbering.

Usage:
    python3 flow_step_execution_coverage_check.py <project_dir> [--json report.json]
                                                  [--compliance-json <precomputed.json>]
    exit 0 = every applicable step ran AND no step outran a step it blocks_on
    exit 1 = one or more applicable steps MISSING, or an ORDERING-VIOLATION

The compliance classification is reused verbatim: this gate runs
`flow_compliance_check.py --json` itself (or consumes a precomputed report via
--compliance-json) so there is exactly ONE source of per-step verdicts.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT_FLOW = _HERE.parent / "flow" / "phase1_phase2_phase3.yaml"

# ── role classification by universal flow-stage name ─────────────────────────
# Terminal hand-off steps: emitting/ticking these asserts the design is done.
_TERMINAL_RE = re.compile(
    r"gdsii|gds\s*out|gds\s*ii|foundry\s*hand[- ]?off|tape\s*-?out\s*checklist",
    re.IGNORECASE)
# Sign-off predecessors: physical/timing sign-off that MUST pass before hand-off.
_SIGNOFF_RE = re.compile(
    r"physical\s*verification|(?<![a-z])drc(?![a-z])|(?<![a-z])lvs(?![a-z])"
    r"|(?<![a-z])erc(?![a-z])|post-?route\s*sta|post-?layout.*\bsta\b"
    r"|parasitic\s*extraction|antenna|signal\s*integrity|ir\s*drop"
    r"|post-?layout\s*spice|spice\s*(?:correlation|verification)|(?<![a-z])perc(?![a-z])",
    re.IGNORECASE)

# Silicon / manufacturing attestation steps (flow stage 5). These do not verify a
# design property — they attest that a PHYSICAL EVENT happened: the mask set and
# wafer lot came back from the foundry, wafers were sorted, parts were packaged,
# final-tested, reliability-qualified. Classified by the flow's own `stage` field
# first (declarative, immune to rewording) with a name fallback for reports that
# carry no stage.
_SILICON_STAGE_PREFIX = "stage5"
_SILICON_ATTEST_RE = re.compile(
    r"fabrication|wafer\s*(?:sort|fab|lot|probe)|probe\s*test|packaging"
    r"|final\s*test|burn-?in|reliability\s*qual|(?<![a-z])htol(?![a-z])",
    re.IGNORECASE)

# A step is "legitimately not run" (does NOT count as a skip) in these states.
_NOT_APPLICABLE = {"SKIPPED-CONDITION", "SKIPPED", "WAIVED",
                   "WAIVED-DEFERRED", "DEFERRED-BY-UPSTREAM", "DEFERRED"}
# A real PASS always satisfies a predecessor.
_REAL_DONE = {"PASS"}
# VACUOUS-PASS = the gate RAN and legitimately had nothing applicable to check
# (rc=2 "input not applicable", e.g. the synthesis-handoff gate on a design with
# no hi/lo tie cells or no yosys-script template). For an ordinary design PROCESS
# step that is an acceptable predecessor — it ran, it did not fail, it was not
# silently MISSING. It is NOT acceptable for a step whose whole job is to certify
# something: a SIGN-OFF (DRC/LVS/PERC/SPICE/…) that verified nothing, or a
# stage-5 SILICON ATTESTATION (fab intake / wafer sort / packaging / final test /
# reliability qual) that attested to nothing. Both must still block a downstream
# done-claim — you cannot wafer-sort a lot the foundry never delivered, and the
# downstream step's own PASS asserts the upstream physical event occurred. See
# `_blocks_when_vacuous`, applied in analyze().
_VACUOUS = {"VACUOUS-PASS"}


def _blocks_when_vacuous(step: dict) -> bool:
    """True when a VACUOUS-PASS on `step` must STILL block a downstream done-claim.

    Sign-off steps and stage-5 silicon attestations both certify something; a
    vacuous verdict on either means nothing was certified, so a successor may not
    be credited as done on top of it. Ordinary process steps return False — they
    ran and did not fail, which is a legitimate predecessor state.
    """
    name = step.get("name", "") or ""
    stage = str(step.get("stage") or "")
    return bool(_SIGNOFF_RE.search(name)
                or stage.startswith(_SILICON_STAGE_PREFIX)
                or _SILICON_ATTEST_RE.search(name))


def _norm(status: str) -> str:
    return str(status or "").upper().replace("_", "-").strip()


def _run_compliance(project: Path) -> dict:
    out = Path(tempfile.mkstemp(suffix="_compliance.json")[1])
    prog = _HERE / "flow_compliance_check.py"
    subprocess.run([sys.executable, str(prog), str(project), "--json", str(out)],
                   capture_output=True, text=True)
    # flow_compliance_check exits 1 on FAIL/MISSING; that is expected — we only
    # need the JSON it writes, not its exit code.
    try:
        return json.loads(out.read_text())
    finally:
        try:
            out.unlink()
        except OSError:
            pass


def _load_blocks_on(flow_path: Path) -> dict:
    """Build the {step_id: [parent_id,...]} dependency graph from the flow yaml's
    declared `blocks_on` edges — the SAME edges flow_compliance_check consumes.
    Returns {} if the yaml or PyYAML is unavailable (the gate then falls back to
    the name-based terminal guard). Ids are stringified for uniform lookup."""
    try:
        import yaml
        doc = yaml.safe_load(flow_path.read_text())
    except Exception:
        return {}
    graph: dict = {}

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and ("name" in o or "blocks_on" in o):
                edges = o.get("blocks_on") or []
                if isinstance(edges, (list, tuple)):
                    graph[str(o["id"])] = [str(e) for e in edges]
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return graph


def _ancestors(sid: str, graph: dict) -> list:
    """Transitive blocks_on ancestry of sid (BFS, cycle-safe)."""
    out, queue, seen = [], list(graph.get(sid, [])), set()
    while queue:
        p = queue.pop(0)
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        queue.extend(graph.get(p, []))
    return out


def analyze(report: dict, graph: dict | None = None) -> dict:
    graph = graph or {}
    steps = report.get("steps", [])
    by_id = {str(s.get("id")): s for s in steps}
    status_of = {sid: _norm(s.get("status")) for sid, s in by_id.items()}

    applicable_missing = []
    signoff_steps = []
    terminal_steps = []
    for s in steps:
        name = s.get("name", "")
        st = _norm(s.get("status"))
        if st not in _NOT_APPLICABLE and st == "MISSING":
            applicable_missing.append(s)
        if _SIGNOFF_RE.search(name):
            signoff_steps.append(s)
        if _TERMINAL_RE.search(name):
            terminal_steps.append(s)

    ordering_violations = []
    seen_pairs = set()

    def _emit(term, anc_id):
        anc = by_id.get(str(anc_id))
        key = (str(term.get("id")), str(anc_id))
        if anc is None or key in seen_pairs:
            return
        seen_pairs.add(key)
        ordering_violations.append({
            "terminal_id": term.get("id"), "terminal": term.get("name"),
            "terminal_status": _norm(term.get("status")),
            "signoff_id": anc.get("id"), "signoff": anc.get("name"),
            "signoff_status": _norm(anc.get("status")),
        })

    # ── PRIMARY: graph-based. Any step claimed done (PASS/VACUOUS-PASS) whose
    # transitive blocks_on ancestry reaches an APPLICABLE step that has not truly
    # PASSed (MISSING / FAIL / VACUOUS-PASS) is out of order — it was marked done
    # before a step it declares it depends on. Uses the flow's own edges, so it
    # is precise (no cross-track false positives).
    for s in steps:
        if _norm(s.get("status")) not in ("PASS", "VACUOUS-PASS"):
            continue
        for anc_id in _ancestors(str(s.get("id")), graph):
            ast = status_of.get(anc_id)
            if ast is None or ast in _NOT_APPLICABLE:
                continue
            if ast in _REAL_DONE:
                continue
            # VACUOUS-PASS ancestor: acceptable UNLESS the ancestor's job was to
            # certify something — a sign-off that verified nothing, or a stage-5
            # silicon attestation that attested to nothing, must still block. A
            # vacuous PROCESS step (e.g. synth-handoff with no tie-cells to check)
            # ran and did not fail — it is not a silent MISSING and does not break
            # ordering.
            if ast in _VACUOUS:
                anc = by_id.get(anc_id)
                if anc and not _blocks_when_vacuous(anc):
                    continue
            _emit(s, anc_id)

    # ── FALLBACK: name-based terminal guard, for terminal hand-off steps that
    # declare NO blocks_on edges at all (the exact data bug where GDSII/handoff
    # ship `blocks_on: []`). Guards them against every applicable sign-off step.
    for t in terminal_steps:
        if _norm(t.get("status")) not in ("PASS", "VACUOUS-PASS"):
            continue
        if graph.get(str(t.get("id"))):
            continue  # has real edges → already covered by the graph pass
        for sg in signoff_steps:
            sst = _norm(sg.get("status"))
            if sst in _NOT_APPLICABLE or sst in _REAL_DONE:
                continue
            _emit(t, sg.get("id"))

    ok = not applicable_missing and not ordering_violations
    return {
        "verdict": "PASS" if ok else "FAIL",
        "applicable_missing": [
            {"id": s.get("id"), "name": s.get("name"), "stage": s.get("stage")}
            for s in applicable_missing],
        "ordering_violations": ordering_violations,
        "counts": {
            "steps_total": len(steps),
            "applicable_missing": len(applicable_missing),
            "signoff_steps": len(signoff_steps),
            "terminal_steps": len(terminal_steps),
            "ordering_violations": len(ordering_violations),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project")
    ap.add_argument("--json", help="write this gate's report here")
    ap.add_argument("--compliance-json",
                    help="reuse a precomputed flow_compliance_check --json report")
    ap.add_argument("--flow-def", default=str(_DEFAULT_FLOW),
                    help="flow yaml providing blocks_on dependency edges")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    if args.compliance_json:
        report = json.loads(Path(args.compliance_json).read_text())
    else:
        report = _run_compliance(project)

    graph = _load_blocks_on(Path(args.flow_def))
    res = analyze(report, graph)
    res["project"] = str(project)
    res["compliance_overall"] = report.get("overall")

    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2, ensure_ascii=False))

    print(f"=== flow step-execution coverage — {project.name} ===")
    c = res["counts"]
    print(f"steps={c['steps_total']}  applicable-MISSING={c['applicable_missing']}"
          f"  sign-off-steps={c['signoff_steps']}  terminal-steps={c['terminal_steps']}"
          f"  ordering-violations={c['ordering_violations']}")
    if res["applicable_missing"]:
        print("\nSILENTLY-SKIPPED (applicable step never produced output):")
        for s in res["applicable_missing"]:
            print(f"  MISSING  [{s['id']}] {s['name']}")
    if res["ordering_violations"]:
        # NB the JSON keys are historical: `terminal_*` is the step CLAIMED DONE
        # (any step, not only a terminal hand-off) and `signoff_*` is the
        # PREDECESSOR that had not PASSed (any applicable ancestor, not only a
        # sign-off). The keys are kept for report consumers; the wording here
        # describes what the check actually emits.
        print("\nORDERING-VIOLATION (step marked done before a step it depends on passed):")
        for v in res["ordering_violations"]:
            print(f"  [{v['terminal_id']}] {v['terminal']} = {v['terminal_status']}"
                  f"  ⟵ but  [{v['signoff_id']}] {v['signoff']} = {v['signoff_status']}")
    print(f"\nVERDICT: {res['verdict']}")
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
